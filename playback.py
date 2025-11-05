from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.logging import log_event, with_trace
from utils.db import Database
from utils import ytdlp_helper
from utils.audio import create_ffmpeg_source_with_retries
from utils.errors import (
    QueueEmptyError,
    PermissionDeniedError,
    VoiceNotConnectedError,
)
from utils.cookies_store import CookiesStore

LOG = logging.getLogger(__name__)

@dataclass
class Track:
    title: str
    url: str
    duration: Optional[int]
    requested_by: int
    source: str
    added_at: float = field(default_factory=lambda: time.time())

def _has_manage_or_dj(user: discord.Member, db: Database, guild_id: int, *, require_manage=False) -> bool:
    if require_manage and not user.guild_permissions.manage_guild:
        return False
    # DJ role check
    # (sync call to DB per command is ok; could be cached)
    async def _get():
        return await db.get_settings(guild_id)
    loop = asyncio.get_event_loop()
    settings = loop.run_until_complete(_get())  # safe in app_commands thread context
    dj_role_id = settings.get("dj_role_id")
    if dj_role_id and isinstance(user, discord.Member):
        return user.guild_permissions.manage_guild or any(r.id == dj_role_id for r in user.roles)
    return user.guild_permissions.manage_guild

class GuildPlayer:
    def __init__(self, bot: commands.Bot, guild_id: int, db: Database):
        self.bot = bot
        self.guild_id = guild_id
        self.db = db

        self.queue: List[Track] = []
        self.lock = asyncio.Lock()
        self.voice: Optional[discord.VoiceClient] = None
        self.current: Optional[Track] = None
        self.loop_mode: str = "off"  # off|one|all
        self.volume: int = 70  # 0-100
        self.idle_task: Optional[asyncio.Task] = None
        self.stop_event = asyncio.Event()

    async def ensure_voice(self, interaction: discord.Interaction) -> None:
        if not interaction.user or not isinstance(interaction.user, discord.Member):
            raise PermissionDeniedError("لا يمكن تحديد القناة الصوتية للمستخدم.")
        if not interaction.user.voice or not interaction.user.voice.channel:
            raise PermissionDeniedError("ادخل قناة صوتية أولًا.")

        channel = interaction.user.voice.channel
        if self.voice and self.voice.is_connected():
            if self.voice.channel != channel:
                raise PermissionDeniedError("البوت متصل في قناة صوتية أخرى بهذا السيرفر.")
            return
        self.voice = await channel.connect(timeout=10)
        log_event(logging.INFO, "voice_connected", "voice", guild_id=self.guild_id, channel_id=channel.id)

    async def enqueue(self, track: Track) -> int:
        async with self.lock:
            settings = await self.db.get_settings(self.guild_id)
            max_q = int(settings.get("max_queue_size", os.getenv("MAX_QUEUE_SIZE", 300)))
            if len(self.queue) >= max_q:
                raise QueueEmptyError("قائمة الانتظار ممتلئة.")
            self.queue.append(track)
            pos = len(self.queue)
            log_event(logging.INFO, "queue_add", "queue", guild_id=self.guild_id, title=track.title, url=track.url, position_in_queue=pos)
            if not self.voice or not self.voice.is_connected():
                # No auto join here; caller should call ensure_voice
                pass
            # Auto start if nothing is playing
            if not self.voice or not self.voice.is_playing():
                self.bot.loop.create_task(self._maybe_start_next())
            return pos

    async def _maybe_start_next(self) -> None:
        async with self.lock:
            if self.voice is None or not self.voice.is_connected():
                return
            if self.voice.is_playing() or self.voice.is_paused():
                return
            if self.current and self.loop_mode in ("one",):
                # replay current
                track = self.current
            else:
                if not self.queue:
                    self.current = None
                    await self._schedule_idle_disconnect()
                    return
                track = self.queue.pop(0)
                if self.current and self.loop_mode == "all":
                    self.queue.append(self.current)
                self.current = track

            # Play
            try:
                await self._play_track(track)
            except Exception as e:  # noqa: BLE001
                log_event(logging.ERROR, "play_failed", "ffmpeg", guild_id=self.guild_id, message=str(e))
                # Move on
                self.bot.loop.create_task(self._maybe_start_next())

    def _provider_for(self, url: str) -> str:
        if "facebook.com" in url.lower():
            return "facebook"
        return "youtube"

    async def _play_track(self, track: Track, *, seek_seconds: Optional[int] = None) -> None:
        assert self.voice is not None
        # Resolve best stream URL via yt-dlp with per-guild cookies when enabled
        settings = await self.db.get_settings(self.guild_id)
        use_cookies = bool(settings.get("use_cookies", True))
        cookies_path: Optional[str] = None
        if use_cookies:
            store = CookiesStore(self.db)
            temp = await store.get_temp_path(self.guild_id, self._provider_for(track.url))
            cookies_path = temp

        try:
            info = await ytdlp_helper.extract_single(track.url, guild_id=self.guild_id, cookies_path=cookies_path)
            stream_url = info.get("url")
            title = info.get("title", track.title)
            volume = int(settings.get("volume", self.volume))

            source = await create_ffmpeg_source_with_retries(
                input_url=stream_url,
                volume=volume,
                guild_id=self.guild_id,
                seek_seconds=seek_seconds,
            )

            def after_play(err: Optional[Exception]) -> None:
                if err:
                    log_event(logging.ERROR, "playback_after_error", "voice", guild_id=self.guild_id, message=str(err))
                # schedule next
                fut = self.bot.loop.create_task(self._maybe_start_next())
                try:
                    fut.add_done_callback(lambda f: f.exception())  # trigger exception if any
                except Exception:  # noqa: BLE001
                    pass

            self.voice.play(source, after=after_play)
            log_event(logging.INFO, "playback_start", "voice", guild_id=self.guild_id, title=title, url=track.url, duration=track.duration)
            await self._cancel_idle_disconnect()
        finally:
            # Ensure temp cookies removed if any
            try:
                if cookies_path and os.path.exists(cookies_path):
                    os.remove(cookies_path)
            except Exception:
                pass

    async def _cancel_idle_disconnect(self) -> None:
        if self.idle_task and not self.idle_task.done():
            self.idle_task.cancel()
            self.idle_task = None

    async def _schedule_idle_disconnect(self) -> None:
        settings = await self.db.get_settings(self.guild_id)
        idle_minutes = int(settings.get("idle_minutes", os.getenv("DEFAULT_IDLE_MINUTES", 10)))
        if self.idle_task and not self.idle_task.done():
            return

        async def _idle() -> None:
            try:
                await asyncio.sleep(idle_minutes * 60)
                if self.voice and self.voice.is_connected():
                    await self.voice.disconnect(force=True)
                    log_event(logging.INFO, "auto_leave", "voice", guild_id=self.guild_id)
            except asyncio.CancelledError:
                return

        self.idle_task = asyncio.create_task(_idle())

    # Public controls
    async def skip(self, count: int = 1) -> None:
        if not self.voice or not self.voice.is_connected():
            raise VoiceNotConnectedError("غير متصل بقناة صوتية.")
        if self.voice.is_playing() or self.voice.is_paused():
            self.voice.stop()
        # popping additional tracks if count > 1
        async with self.lock:
            for _ in range(max(0, count - 1)):
                if self.queue:
                    self.queue.pop(0)
        log_event(logging.INFO, "skip", "queue", guild_id=self.guild_id, message=f"count={count}")

    async def pause(self) -> None:
        if self.voice and self.voice.is_playing():
            self.voice.pause()
            log_event(logging.INFO, "pause", "voice", guild_id=self.guild_id)

    async def resume(self) -> None:
        if self.voice and self.voice.is_paused():
            self.voice.resume()
            log_event(logging.INFO, "resume", "voice", guild_id=self.guild_id)

    async def stop(self) -> None:
        if self.voice and self.voice.is_connected():
            self.queue.clear()
            self.voice.stop()
            log_event(logging.INFO, "stop", "voice", guild_id=self.guild_id)

    async def set_volume(self, volume: int) -> None:
        self.volume = max(0, min(100, volume))
        log_event(logging.INFO, "volume_set", "voice", guild_id=self.guild_id, message=str(self.volume))

    async def seek(self, mm: int, ss: int) -> None:
        if not self.current:
            raise VoiceNotConnectedError("لا يوجد تشغيل حالي.")
        seconds = max(0, mm * 60 + ss)
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()
        await self._play_track(self.current, seek_seconds=seconds)
        log_event(logging.INFO, "seek", "voice", guild_id=self.guild_id, message=f"{mm:02d}:{ss:02d}")

PLAYERS: Dict[int, GuildPlayer] = {}

def get_player(bot: commands.Bot, guild: discord.Guild) -> GuildPlayer:
    if guild.id not in PLAYERS:
        assert isinstance(bot, commands.Bot)
        assert hasattr(bot, "db") and bot.db is not None
        PLAYERS[guild.id] = GuildPlayer(bot, guild.id, bot.db)
    return PLAYERS[guild.id]


class PlaybackCog(commands.Cog, name="playback"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="join", description="ادخل القناة الصوتية الحالية")
    @with_trace
    async def join(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        player = get_player(self.bot, interaction.guild)
        try:
            await player.ensure_voice(interaction)
            await interaction.followup.send("تم الاتصال بالقناة الصوتية.", ephemeral=True)
        except Exception as e:  # noqa: BLE001
            await interaction.followup.send(f"تعذّر الاتصال: {e}", ephemeral=True)

    @app_commands.command(name="skip", description="تخطي العنصر الحالي أو أكثر")
    @app_commands.describe(count="عدد العناصر لتخطيها")
    @with_trace
    async def skip(self, interaction: discord.Interaction, count: Optional[int] = 1) -> None:
        player = get_player(self.bot, interaction.guild)
        await interaction.response.defer(ephemeral=True)
        # Restrict skipping many to DJ/manage
        if (count or 1) > 1:
            user = interaction.user
            if isinstance(user, discord.Member):
                if not (user.guild_permissions.manage_guild or any(r.id == (await self.bot.db.get_settings(interaction.guild_id)).get("dj_role_id") for r in user.roles)):
                    await interaction.followup.send("هذا الأمر يتطلب صلاحيات DJ أو Manage Guild.", ephemeral=True)
                    return
        try:
            await player.skip(count or 1)
            await interaction.followup.send(f"تم التخطي ({count}).", ephemeral=True)
        except Exception as e:  # noqa: BLE001
            await interaction.followup.send(f"تعذّر التخطي: {e}", ephemeral=True)

    @app_commands.command(name="pause", description="إيقاف مؤقت")
    @with_trace
    async def pause(self, interaction: discord.Interaction) -> None:
        player = get_player(self.bot, interaction.guild)
        await player.pause()
        await interaction.response.send_message("إيقاف مؤقت.", ephemeral=True)

    @app_commands.command(name="resume", description="استئناف")
    @with_trace
    async def resume(self, interaction: discord.Interaction) -> None:
        player = get_player(self.bot, interaction.guild)
        await player.resume()
        await interaction.response.send_message("استئناف التشغيل.", ephemeral=True)

    @app_commands.command(name="stop", description="إيقاف ومسح الصف")
    @with_trace
    async def stop(self, interaction: discord.Interaction) -> None:
        # Restrict to DJ/manage
        user = interaction.user
        if isinstance(user, discord.Member):
            if not (user.guild_permissions.manage_guild or any(r.id == (await self.bot.db.get_settings(interaction.guild_id)).get("dj_role_id") for r in user.roles)):
                await interaction.response.send_message("هذا الأمر يتطلب صلاحيات DJ أو Manage Guild.", ephemeral=True)
                return
        player = get_player(self.bot, interaction.guild)
        await player.stop()
        await interaction.response.send_message("تم الإيقاف ومسح الصف.", ephemeral=True)

    @app_commands.command(name="now", description="المشغل الآن")
    @with_trace
    async def now(self, interaction: discord.Interaction) -> None:
        player = get_player(self.bot, interaction.guild)
        current = player.current
        if not current:
            await interaction.response.send_message("لا يوجد تشغيل حالي.", ephemeral=True)
            return
        embed = discord.Embed(title="يعمل الآن", description=current.title)
        embed.add_field(name="المصدر", value=current.source)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="volume", description="تعيين مستوى الصوت (0-100)")
    @with_trace
    async def volume(self, interaction: discord.Interaction, value: app_commands.Range[int, 0, 100]) -> None:
        # Restrict >80 to DJ/manage
        if value > 80:
            user = interaction.user
            if isinstance(user, discord.Member):
                if not (user.guild_permissions.manage_guild or any(r.id == (await self.bot.db.get_settings(interaction.guild_id)).get("dj_role_id") for r in user.roles)):
                    await interaction.response.send_message("رفع الصوت فوق 80 يتطلب صلاحيات DJ أو Manage Guild.", ephemeral=True)
                    return
        player = get_player(self.bot, interaction.guild)
        await player.set_volume(value)
        await interaction.response.send_message(f"تم تعيين الصوت إلى {value}.", ephemeral=True)

    @app_commands.command(name="seek", description="الانتقال إلى وقت محدد (mm:ss)")
    @with_trace
    async def seek(self, interaction: discord.Interaction, mm_ss: str) -> None:
        player = get_player(self.bot, interaction.guild)
        try:
            mm, ss = mm_ss.split(":")
            mm_i = int(mm); ss_i = int(ss)
            await player.seek(mm_i, ss_i)
            await interaction.response.send_message(f"تم الانتقال إلى {mm_i:02d}:{ss_i:02d}.", ephemeral=True)
        except Exception as e:  # noqa: BLE001
            await interaction.response.send_message(f"تعذّر تنفيذ seek: {e}", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlaybackCog(bot))
