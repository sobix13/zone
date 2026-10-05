#!/usr/bin/env python3
import discord
from discord.ext import commands
import os
import asyncio
from aiohttp import web
from dotenv import load_dotenv
from database import Database
import logging
import logging.handlers
import traceback
from datetime import datetime
from pathlib import Path
from health_runtime import HealthRuntime,write_private_json

load_dotenv(Path(__file__).parent / '.env')

handler = logging.handlers.RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(), handler]
)
log = logging.getLogger('MeleeZone')

HEALTH_PORT = int(os.getenv('HEALTH_PORT', 3020))

COGS = [
    'cogs.panel',
    'cogs.leaderboard',
    'cogs.assigner',
    'cogs.setup',
    'cogs.guide',
    'cogs.submit',
    'cogs.review',
    'cogs.admin',
    'cogs.tasks',
    'cogs.reactions',
    'cogs.quiz',
    'cogs.raffle',
    'cogs.snapshot',
    'cogs.assignments',
    'cogs.control_center',
    'cogs.activity',
    'cogs.mc_tools',
    'cogs.health',
    'cogs.review_support',
    'cogs.governance',
]


class MeleeZoneBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = False
        intents.reactions = True
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        self.db = Database(os.getenv('DATABASE_PATH','bot.db'))
        self.health = HealthRuntime(self)
        self.health.disconnected_since = self.health.started
        self._guild_commands_synced = False
        self.tree.on_error = self.on_app_command_error
        self.tree.interaction_check = self._guild_interaction_check

    async def _guild_interaction_check(self,interaction):
        if interaction.guild is not None:
            return True
        await interaction.response.send_message('Use this command inside the server.',ephemeral=True)
        return False

    async def setup_hook(self):
        await self.db.init()
        log.info("Database initialized")
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info(f"Loaded: {cog}")
            except Exception as e:
                log.error(f"Failed to load {cog}: {e}", exc_info=True)
                self.health.failed_cogs.append(cog)
        if self.health.failed_cogs:
            raise RuntimeError('Required extensions failed to load: '+','.join(self.health.failed_cogs))

    async def on_ready(self):
        self.health.disconnected_since = None
        log.info(f"Ready: {self.user} | Guilds: {len(self.guilds)}")
        if not self._guild_commands_synced:
            failures=[]
            for guild in self.guilds:
                try:
                    self.tree.copy_global_to(guild=guild)
                    synced = await self.tree.sync(guild=guild)
                    log.info(f"Synced {len(synced)} commands to {guild.name}")
                except Exception as e:
                    failures.append(str(guild.id))
                    log.warning(f"Sync failed {guild.name}: {e}")
            self.health.command_sync_errors=failures
            self._guild_commands_synced = not failures
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="/guide for help")
        )

    async def on_guild_join(self, guild: discord.Guild):
        log.info(f"Joined: {guild.name} ({guild.id})")
        await self.db.create_guild_config(str(guild.id))
        channel = guild.system_channel or next(
            (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None
        )
        if channel:
            await channel.send(embed=discord.Embed(
                title="Melee Zone",
                description="Thanks for adding me!\nAn admin should run `/setup_start` to configure.",
                color=discord.Color.from_rgb(220, 50, 50)
            ))
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        except Exception as e:
            log.warning(f"Sync error on join: {e}")

    async def on_error(self, event: str, *args, **kwargs):
        self.health.last_error = f'Event {event} failed. Check the service log.'
        log.error(f"Unhandled error in {event}:\n{traceback.format_exc()}")

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        cmd = getattr(interaction.command, 'name', '?')
        log.error(f"Command error [{cmd}]: {error}", exc_info=True)
        msg = "An error occurred. Please try again."
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            msg = f"Please wait {error.retry_after:.1f}s."
        elif "Missing Permissions" in str(error):
            msg = "I don't have permission to do that."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

    async def on_disconnect(self):
        import time
        if self.health.disconnected_since is None:
            self.health.disconnected_since=time.monotonic()
        log.warning("Bot disconnected — will auto-reconnect")

    async def on_resumed(self):
        self.health.disconnected_since = None
        log.info("Bot session resumed")

    async def close(self):
        await self.health.stop()
        await super().close()
        await self.db.close()


def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        write_private_json(Path(os.getenv('RUNTIME_DIR','runtime'))/'heartbeat.json',{'fatal':'Discord token is missing','ready':False})
        log.critical("DISCORD_TOKEN not found in .env")
        raise SystemExit(1)

    bot = MeleeZoneBot()

    async def runner():
        async with bot:
            await bot.health.start(HEALTH_PORT)
            await bot.start(token)

    try:
        asyncio.run(runner())
    except discord.LoginFailure:
        write_private_json(Path(os.getenv('RUNTIME_DIR','runtime'))/'heartbeat.json',{'fatal':'Invalid Discord token','ready':False})
        log.critical("Invalid token")
        raise SystemExit(1)
    except discord.PrivilegedIntentsRequired:
        write_private_json(Path(os.getenv('RUNTIME_DIR','runtime'))/'heartbeat.json',{'fatal':'Server Members and Message Content intents required','ready':False})
        log.critical("Enable privileged intents in Discord Developer Portal")
        raise SystemExit(1)
    except KeyboardInterrupt:
        log.info("Shutdown requested")
    except Exception as e:
        log.critical(f"Fatal: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
