from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.logging import log_event, with_trace
from utils.db import Database
from utils import ytdlp_helper
from .playback import get_player, Track
from utils.cookies_store import CookiesStore

LOG = logging.getLogger(__name__)

MAX_RESULTS_ENV = int(os.getenv("MAX_SEARCH_RESULTS", 5))


class SearchView(discord.ui.View):
    def __init__(self, results: List[Dict[str, Any]], requester_id: int, timeout: int = 60):
        super().__init__(timeout=timeout)
        self.results = results
        self.requester_id = requester_id
        options = []
        for i, r in enumerate(results[:25]):
            title = (r.get("title") or r.get("fulltitle") or "نتيجة").strip()
            if len(title) > 90:
                title = title[:87] + "…"
            options.append(discord.SelectOption(label=f"{i+1}. {title}", value=str(i)))
        self.select = discord.ui.Select(placeholder="اختر نتيجة", options=options)
        self.select.callback = self._on_select  # type: ignore
        self.add_item(self.select)
        self.selection_index: Optional[int] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user and interaction.user.id == self.requester_id

    async def _on_select(self, interaction: discord.Interaction) -> None:
        self.selection_index = int(self.select.values[0])
        await interaction.response.defer(ephemeral=True)
        self.stop()


class SearchCog(commands.Cog, name="search"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _provider_for(self, url: str) -> str:
        if "facebook.com" in url.lower():
            return "facebook"
        return "youtube"

    @app_commands.command(name="play", description="تشغيل رابط أو البحث بالكلمات")
    @app_commands.describe(url_or_query="رابط مباشر أو كلمات بحث")
    @with_trace
    async def play(self, interaction: discord.Interaction, url_or_query: str) -> None:
        assert self.bot.db is not None
        await interaction.response.defer(ephemeral=True)
        player = get_player(self.bot, interaction.guild)
        await player.ensure_voice(interaction)

        # Detect URL
        is_url = url_or_query.startswith("http://") or url_or_query.startswith("https://")

        if not is_url:
            settings = await self.bot.db.get_settings(interaction.guild_id)
            if not settings.get("enable_query_search", True):
                await interaction.followup.send("تم تعطيل البحث بالكلمات في هذا السيرفر.", ephemeral=True)
                return
            max_results = int(settings.get("max_search_results", MAX_RESULTS_ENV))
            try:
                results = await ytdlp_helper.search_yt(url_or_query, limit=max_results, guild_id=interaction.guild_id)
            except Exception as e:  # noqa: BLE001
                await interaction.followup.send(f"تعذّر البحث: {e}", ephemeral=True)
                return

            if not results:
                await interaction.followup.send("لا نتائج.", ephemeral=True)
                return

            view = SearchView(results, requester_id=interaction.user.id)
            await interaction.followup.send("اختر نتيجة للتشغيل أو الإضافة.", view=view, ephemeral=True)
            await view.wait()
            if view.selection_index is None:
                return
            choice = results[view.selection_index]
            url = choice.get("url") or choice.get("webpage_url")
            title = choice.get("title") or choice.get("fulltitle")
        else:
            url = url_or_query
            title = url

        # Try extract with per-guild cookies if enabled
        settings = await self.bot.db.get_settings(interaction.guild_id)
        use_cookies = bool(settings.get("use_cookies", True))
        cookies_path: Optional[str] = None
        temp_path: Optional[str] = None
        if use_cookies:
            store = CookiesStore(self.bot.db)
            temp_path = await store.get_temp_path(interaction.guild_id, self._provider_for(url))
            cookies_path = temp_path

        try:
            info = await ytdlp_helper.extract_single(url, guild_id=interaction.guild_id, cookies_path=cookies_path)
        except Exception as e:  # noqa: BLE001
            await interaction.followup.send(
                f"تعذّر استخراج الرابط: {e}\nنصائح: جرّب رفع/تحديث cookies، أو حدّث yt-dlp بأمر /admin ytdlp-update.",
                ephemeral=True,
            )
            return
        finally:
            # cleanup temp cookie
            import os
            try:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

        track = Track(
            title=info.get("title", title or "مقطع صوتي"),
            url=info.get("webpage_url", url),
            duration=info.get("duration"),
            requested_by=interaction.user.id,
            source=info.get("extractor_key", "source"),
        )
        pos = await player.enqueue(track)
        await interaction.followup.send(f"أُضيف **{track.title}** إلى الصف (#{pos}).", ephemeral=True)

    @app_commands.command(name="search", description="بحث فقط (يوتيوب)")
    @with_trace
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        assert self.bot.db is not None
        await interaction.response.defer(ephemeral=True)
        settings = await self.bot.db.get_settings(interaction.guild_id)
        if not settings.get("enable_query_search", True):
            await interaction.followup.send("تم تعطيل البحث بالكلمات في هذا السيرفر.", ephemeral=True)
            return
        max_results = int(settings.get("max_search_results", MAX_RESULTS_ENV))
        results = await ytdlp_helper.search_yt(query, limit=max_results, guild_id=interaction.guild_id)
        if not results:
            await interaction.followup.send("لا نتائج.", ephemeral=True)
            return
        lines = [f"**{i+1}.** {(r.get('title') or r.get('fulltitle') or 'نتيجة')}" for i, r in enumerate(results)]
        await interaction.followup.send("\n".join(lines), ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SearchCog(bot))
