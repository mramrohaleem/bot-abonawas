from __future__ import annotations

import logging
import random
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .playback import get_player, Track
from utils.logging import with_trace

LOG = logging.getLogger(__name__)


class QueueCog(commands.Cog, name="queue"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="queue", description="عرض قائمة الانتظار")
    @with_trace
    async def queue(self, interaction: discord.Interaction) -> None:
        player = get_player(self.bot, interaction.guild)
        if not player.queue:
            await interaction.response.send_message("قائمة الانتظار فارغة.", ephemeral=True)
            return
        lines = []
        for i, t in enumerate(player.queue, start=1):
            dur = f" ({t.duration//60}:{t.duration%60:02d})" if t.duration else ""
            lines.append(f"**{i}.** {t.title}{dur} – <{t.url}>")
        embed = discord.Embed(title="قائمة الانتظار", description="\n".join(lines)[:3900])
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remove", description="إزالة عنصر من الصف")
    @with_trace
    async def remove(self, interaction: discord.Interaction, index: int) -> None:
        player = get_player(self.bot, interaction.guild)
        if 1 <= index <= len(player.queue):
            removed = player.queue.pop(index - 1)
            await interaction.response.send_message(f"تمت إزالة: {removed.title}", ephemeral=True)
        else:
            await interaction.response.send_message("فهرس غير صالح.", ephemeral=True)

    @app_commands.command(name="move", description="نقل عنصر داخل الصف")
    @with_trace
    async def move(self, interaction: discord.Interaction, from_index: int, to_index: int) -> None:
        player = get_player(self.bot, interaction.guild)
        if not (1 <= from_index <= len(player.queue) and 1 <= to_index <= len(player.queue)):
            await interaction.response.send_message("فهرس غير صالح.", ephemeral=True)
            return
        item = player.queue.pop(from_index - 1)
        player.queue.insert(to_index - 1, item)
        await interaction.response.send_message("تم النقل.", ephemeral=True)

    @app_commands.command(name="shuffle", description="خلط الصف")
    @with_trace
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = get_player(self.bot, interaction.guild)
        random.shuffle(player.queue)
        await interaction.response.send_message("تم الخلط.", ephemeral=True)

    @app_commands.command(name="loop", description="تكرار: off|one|all")
    @with_trace
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        player = get_player(self.bot, interaction.guild)
        player.loop_mode = mode.value
        await interaction.response.send_message(f"تم التكرار: {mode.value}", ephemeral=True)

    @loop.autocomplete("mode")
    async def loop_autocomplete(self, interaction: discord.Interaction, current: str):
        opts = ["off", "one", "all"]
        return [app_commands.Choice(name=o, value=o) for o in opts if current.lower() in o]

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QueueCog(bot))
