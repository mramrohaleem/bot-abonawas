import asyncio
import logging
import os
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv

from utils.logging import init_logger, log_event
from utils.db import Database

# Optional: uvloop on Linux
try:
    import uvloop  # type: ignore
    uvloop.install()
except Exception:
    pass

# Load .env
load_dotenv()

INTENTS = discord.Intents.default()
INTENTS.message_content = False
INTENTS.guilds = True
INTENTS.members = False

LOG = init_logger()

DB_PATH = os.getenv("DB_PATH", "./data/bot.db")

class QuranBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned_or("/"),
            intents=INTENTS,
            application_id=None,
        )
        self.db: Optional[Database] = None

    async def setup_hook(self) -> None:
        # Init DB
        self.db = Database(DB_PATH)
        await self.db.initialize()

        # Load cogs
        await self.load_extension("cogs.playback")
        await self.load_extension("cogs.queue")
        await self.load_extension("cogs.search")
        await self.load_extension("cogs.cookies")
        await self.load_extension("cogs.settings")
        await self.load_extension("cogs.admin")

        try:
            await self.tree.sync()
            LOG.info("Commands synced.")
        except Exception as e:
            LOG.exception("Failed to sync commands: %s", e)

    async def on_ready(self) -> None:
        log_event(
            logging.INFO,
            event="startup",
            component="admin",
            message=f"Logged in as {self.user} (id={self.user and self.user.id})",
        )
        await self.change_presence(activity=discord.Game(name="/play "))

async def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set")

    bot = QuranBot()
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
