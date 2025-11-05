from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.db import Database
from utils.logging import with_trace

LOG = logging.getLogger(__name__)


class SettingsCog(commands.Cog, name="settings"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="settings", description="عرض/تعديل إعدادات السيرفر")
    @with_trace
    async def settings(self, interaction: discord.Interaction) -> None:
        assert self.bot.db is not None
        s = await self.bot.db.get_settings(interaction.guild_id)
        lines = [
            f"enable_query_search: {s.get('enable_query_search', True)}",
            f"max_search_results: {s.get('max_search_results', 5)}",
            f"use_cookies: {s.get('use_cookies', True)}",
            f"idle_minutes: {s.get('idle_minutes', 10)}",
            f"max_queue_size: {s.get('max_queue_size', 300)}",
            f"volume: {s.get('volume', 70)}",
            f"dj_role_id: {s.get('dj_role_id', None)}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    settings_group = app_commands.Group(name="set", description="تعديل الإعدادات")

    @settings_group.command(name="enable_query_search")
    async def set_enable_query_search(self, interaction: discord.Interaction, value: bool) -> None:
        await self._set(interaction, "enable_query_search", value)

    @settings_group.command(name="max_search_results")
    async def set_max_search_results(self, interaction: discord.Interaction, value: app_commands.Range[int, 1, 10]) -> None:
        await self._set(interaction, "max_search_results", int(value))

    @settings_group.command(name="use_cookies")
    async def set_use_cookies(self, interaction: discord.Interaction, value: bool) -> None:
        await self._set(interaction, "use_cookies", value)

    @settings_group.command(name="idle_minutes")
    async def set_idle_minutes(self, interaction: discord.Interaction, value: app_commands.Range[int, 1, 60]) -> None:
        await self._set(interaction, "idle_minutes", int(value))

    @settings_group.command(name="max_queue_size")
    async def set_max_queue_size(self, interaction: discord.Interaction, value: app_commands.Range[int, 50, 1000]) -> None:
        await self._set(interaction, "max_queue_size", int(value))

    @settings_group.command(name="volume")
    async def set_volume(self, interaction: discord.Interaction, value: app_commands.Range[int, 0, 100]) -> None:
        await self._set(interaction, "volume", int(value))

    dj_group = app_commands.Group(name="dj", description="إعداد دور الدي جي")

    @dj_group.command(name="set")
    async def dj_set(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await self._set(interaction, "dj_role_id", role.id)

    async def _set(self, interaction: discord.Interaction, key: str, value) -> None:
        assert self.bot.db is not None
        await self.bot.db.set_setting(interaction.guild_id, key, value)
        await interaction.response.send_message(f"تم التحديث: {key} = {value}", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    cog = SettingsCog(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.settings_group)
    bot.tree.add_command(cog.dj_group)
