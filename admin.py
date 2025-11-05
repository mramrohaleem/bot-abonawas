from __future__ import annotations

import logging
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.logging import log_event, with_trace
from utils import ytdlp_helper

LOG = logging.getLogger(__name__)


class AdminCog(commands.Cog, name="admin"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    admin_group = app_commands.Group(name="admin", description="أوامر إدارية")
    logs_group = app_commands.Group(name="logs", description="عرض اللوج", parent=admin_group)

    @admin_group.command(name="ytdlp-update", description="تحديث yt-dlp")
    @with_trace
    async def ytdlp_update(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("يتطلب Manage Guild.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ok, out = await ytdlp_helper.autoupdate()
        await interaction.followup.send("تم التحديث." if ok else f"فشل التحديث: {out}", ephemeral=True)

    @admin_group.command(name="diag", description="تشخيص سريع")
    @with_trace
    async def diag(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("يتطلب Manage Guild.", ephemeral=True)
            return
        info = await ytdlp_helper.versions()
        lines = [f"ffmpeg: {info.get('ffmpeg')}", f"yt-dlp: {info.get('yt_dlp')}"]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @logs_group.command(name="show", description="عرض اللوج (افتراضي آخر 50 سطر)")
    @app_commands.describe(lines="عدد الأسطر", level="المستوى (اختياري)")
    @with_trace
    async def logs_show(self, interaction: discord.Interaction, lines: Optional[int] = 50, level: Optional[str] = None) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("يتطلب Manage Guild.", ephemeral=True)
            return
        path = os.getenv("LOG_FILE", "logs/bot.jsonl")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.readlines()[-int(lines or 50):]
        except FileNotFoundError:
            await interaction.response.send_message("لا يوجد ملف لوج بعد.", ephemeral=True)
            return
        # Simple filter by level word
        if level:
            lvl = level.upper()
            data = [d for d in data if f'"level": "{lvl}"' in d or f'"levelname": "{lvl}"' in d]
        content = "".join(data)[-1900:]
        await interaction.response.send_message(f"```json\n{content}\n```", ephemeral=True)

    @admin_group.command(name="loglevel", description="تعيين مستوى اللوج")
    @with_trace
    async def loglevel(self, interaction: discord.Interaction, level: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("يتطلب Manage Guild.", ephemeral=True)
            return
        lvl = getattr(logging, level.value)
        logging.getLogger().setLevel(lvl)
        await interaction.response.send_message(f"تم ضبط المستوى إلى {level.value}", ephemeral=True)

    @loglevel.autocomplete("level")
    async def level_ac(self, interaction: discord.Interaction, current: str):
        opts = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        return [app_commands.Choice(name=o, value=o) for o in opts if current.upper() in o]

async def setup(bot: commands.Bot) -> None:
    cog = AdminCog(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.admin_group)
    bot.tree.add_command(cog.logs_group)
