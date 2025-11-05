from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.cookies_store import CookiesStore
from utils.logging import with_trace

LOG = logging.getLogger(__name__)

PROVIDERS = ["youtube", "facebook"]


class CookiesCog(commands.Cog, name="cookies"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.store = CookiesStore(bot.db)  # type: ignore[arg-type]

    cookie_group = app_commands.Group(name="cookies", description="إدارة الكوكيز")

    @cookie_group.command(name="set", description="رفع cookies.txt مع اختيار المزوّد")
    @app_commands.describe(file="ملف cookies.txt", provider="youtube | facebook")
    @with_trace
    async def set(self, interaction: discord.Interaction, file: discord.Attachment, provider: Optional[str] = None) -> None:
        await interaction.response.defer(ephemeral=True)
        if not file.filename.endswith(".txt"):
            await interaction.followup.send("يجب أن يكون الملف بصيغة .txt (cookies.txt)", ephemeral=True)
            return
        prov = (provider or "youtube").lower()
        if prov not in PROVIDERS:
            await interaction.followup.send("مزود غير مدعوم.", ephemeral=True)
            return
        data = await file.read()
        await self.store.save_cookies(interaction.guild_id, prov, data)
        await interaction.followup.send("تم حفظ الكوكيز مشفّرة.", ephemeral=True)

    @cookie_group.command(name="info", description="حالة الكوكيز")
    @with_trace
    async def info(self, interaction: discord.Interaction) -> None:
        rows = await self.store.info(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("لا توجد كوكيز محفوظة.", ephemeral=True)
            return
        lines = []
        for r in rows:
            lines.append(
                f"- {r['provider']}: valid={bool(r['is_valid'])} | last_validated_at={r['last_validated_at'] or '-'}"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @cookie_group.command(name="test", description="اختبار صلاحية الكوكيز")
    @app_commands.describe(provider="youtube | facebook")
    @with_trace
    async def test(self, interaction: discord.Interaction, provider: Optional[str] = None) -> None:
        await interaction.response.defer(ephemeral=True)
        prov = (provider or "youtube").lower()
        ok, reason = await self.store.validate(interaction.guild_id, prov)
        if ok:
            await interaction.followup.send("الكوكيز صالحة.", ephemeral=True)
        else:
            await interaction.followup.send(f"الكوكيز غير صالحة: {reason}", ephemeral=True)

    @cookie_group.command(name="delete", description="حذف الكوكيز")
    @app_commands.describe(provider="youtube | facebook")
    @with_trace
    async def delete(self, interaction: discord.Interaction, provider: Optional[str] = None) -> None:
        prov = (provider or "youtube").lower()
        await self.store.delete(interaction.guild_id, prov)
        await interaction.response.send_message("تم حذف الكوكيز.", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    cog = CookiesCog(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.cookie_group)
