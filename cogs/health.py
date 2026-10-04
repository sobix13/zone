import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands,tasks
from helpers import BotHelpers
from role_utils import resolve_member
from runtime_utils import authorized,resolve_channel
from health_runtime import write_private_json

log=logging.getLogger('MeleeZone.Operations')
PULSE='🔄'


def recovery_owner(config):
    path=Path(os.getenv('RUNTIME_DIR','runtime'))/'recovery.json'
    if path.is_file():
        return str(json.loads(path.read_text()).get('owner_id',''))
    return str(os.getenv('RESCUE_OWNER_ID') or config.get('admin_user_id') or '')


class HealthView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self,interaction):
        return await authorized(interaction)

    @discord.ui.button(label='Refresh health',style=discord.ButtonStyle.secondary)
    async def refresh(self,interaction,button):
        await interaction.response.send_message(embed=health_embed(interaction.client.health.snapshot()),ephemeral=True)

    @discord.ui.button(label='Run safe repair',style=discord.ButtonStyle.primary)
    async def repair(self,interaction,button):
        await interaction.response.defer(ephemeral=True)
        repaired=await interaction.client.health.repair_loops()
        n=await interaction.client.db.retry_failed_notices(str(interaction.guild_id))
        r=await interaction.client.db.retry_failed_reactions(str(interaction.guild_id))
        await interaction.followup.send(f'Restarted tasks: {len(repaired)}. Retried credit logs: {n}. Retried reactions: {r}.',ephemeral=True)

    @discord.ui.button(label='Recover main bot',style=discord.ButtonStyle.danger)
    async def recover(self,interaction,button):
        await interaction.response.defer(ephemeral=True)
        config=await interaction.client.db.get_guild_config(str(interaction.guild_id)) or {}
        owner=recovery_owner(config)
        if not owner or str(interaction.user.id)!=owner:
            return await interaction.followup.send('Only the configured recovery owner has access.',ephemeral=True)
        try:
            message=await interaction.client.health.recover(interaction.user.id)
        except (ValueError,OSError,asyncio.TimeoutError) as exc:
            message=str(exc)
        await interaction.followup.send(message,ephemeral=True)


def health_embed(state):
    e=discord.Embed(title='Melee Zone health',description='Ready' if state['ready'] else 'Attention required',color=0x234738 if state['ready'] else 0x8C303A)
    e.add_field(name='Runtime',value=f"Version: {state['version']}\nUptime: {state['uptime_seconds']}s\nGateway: {'connected' if state['gateway_connected'] else 'reconnecting'}\nDatabase: {'ready' if state['db_ok'] else 'unavailable'}\nLoop delay: {state['lag_seconds']}s",inline=False)
    e.add_field(name='Issues',value='\n'.join(state['issues'])[:1000] or 'No active runtime issues.',inline=False)
    stopped=[k for k,v in state['loops'].items() if v=='stopped']
    e.add_field(name='Background jobs',value='Stopped: '+', '.join(stopped) if stopped else f"{len(state['loops'])} tasks running.",inline=False)
    return e


class HealthCog(BotHelpers,commands.Cog,name='Health'):
    def __init__(self,bot):
        self.bot=bot

    async def cog_load(self):
        self.reaction_worker.start()
        self.notification_worker.start()

    async def cog_unload(self):
        self.reaction_worker.cancel();self.notification_worker.cancel()
        await asyncio.gather(*(t for t in [self.reaction_worker.get_task(),self.notification_worker.get_task()] if t),return_exceptions=True)

    @tasks.loop(seconds=2)
    async def reaction_worker(self):
        await self.bot.wait_until_ready()
        cog=self.bot.get_cog('Reactions')
        if not cog:
            return
        # Bounded serial REST work. Financial events remain durable during overload.
        for event in await self.db.pending_reactions():
            try:
                await cog.process_event(event)
                await self.db.reaction_result(event)
            except Exception as exc:
                await self.db.reaction_result(event,error=type(exc).__name__+': '+str(exc)[:150])
                await self.db.record_operation('reaction','retry',guild_id=event['guild_id'],reference_id=event['message_id'],detail=type(exc).__name__)

    @reaction_worker.before_loop
    async def before_reactions(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=5)
    async def notification_worker(self):
        await self.bot.wait_until_ready()
        for notice in await self.db.pending_notices():
            try:
                guild=self.bot.get_guild(int(notice['guild_id']))
                channel=await resolve_channel(self.bot,guild,notice['channel_id']) if guild else None
                if not channel:
                    raise ValueError('Credit log channel unavailable.')
                await channel.send(notice['content'],allowed_mentions=discord.AllowedMentions.none())
                await self.db.notice_result(notice)
            except Exception as exc:
                await self.db.notice_result(notice,error=type(exc).__name__)

    @notification_worker.before_loop
    async def before_notices(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name='health',description='Open bot health and recovery tools (admin)')
    async def health_command(self,interaction:discord.Interaction):
        if await self.require_admin(interaction) is not None:
            await interaction.response.send_message(embed=health_embed(self.bot.health.snapshot()),view=HealthView(),ephemeral=True)

    @app_commands.command(name='doctor',description='Diagnose permissions, reactions, tasks and runtime (admin)')
    async def doctor(self,interaction:discord.Interaction,repair:bool=False):
        await interaction.response.defer(ephemeral=True)
        config=await self.require_admin(interaction)
        if config is None:
            return
        permissions=interaction.channel.permissions_for(interaction.guild.me)
        names=['view_channel','read_message_history','send_messages_in_threads','manage_messages','manage_threads']
        missing=[n.replace('_',' ').title() for n in names if not getattr(permissions,n,False)]
        e=health_embed(self.bot.health.snapshot())
        e.add_field(name='Current channel or thread',value='Missing: '+', '.join(missing) if missing else 'Thread and message permissions are present.',inline=False)
        emojis=[config.get(f'reaction_emoji_{n}') for n in range(1,6) if config.get(f'reaction_emoji_{n}')]
        e.add_field(name='Reaction configuration',value=f'{len(emojis)} MC reactions configured. Admin awards use the server admin, configured admin role or configured admin user.',inline=False)
        if repair:
            repaired=await self.bot.health.repair_loops()
            retries=await self.db.retry_failed_reactions(str(interaction.guild_id))+await self.db.retry_failed_notices(str(interaction.guild_id))
            # The bot's own tasks use application cooldowns. Native slowmode must not also restrict administrators.
            assignment=await self.db.get_assignment_by_thread(str(interaction.channel_id))
            if assignment and isinstance(interaction.channel,discord.Thread) and interaction.channel.slowmode_delay:
                if permissions.manage_threads:
                    await interaction.channel.edit(slowmode_delay=0,reason='Melee Zone uses its own task cooldown with admin bypass')
                    repaired.append('native task slowmode')
            e.add_field(name='Safe repair',value=f'{len(repaired)} repairs. {retries} queued retries. Member roles, MC balances and review settings are preserved.',inline=False)
        operations=await self.db.recent_operations(str(interaction.guild_id),5)
        if operations:
            e.add_field(name='Recent operations',value='\n'.join(f"{r['category']}: {r['result']} ({r['detail'][:60]})" for r in operations)[:1000],inline=False)
        await interaction.followup.send(embed=e,view=HealthView(),ephemeral=True)

    @app_commands.command(name='recovery_setup',description='Create an owner-only recovery pulse in a private control channel')
    async def recovery_setup(self,interaction:discord.Interaction,channel:discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        config=await self.require_admin(interaction)
        if config is None:
            return
        owner=recovery_owner(config) or str(interaction.guild.owner_id)
        if str(interaction.user.id)!=owner:
            return await interaction.followup.send('Only the configured recovery owner sets up this control.',ephemeral=True)
        permissions=channel.permissions_for(interaction.guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.read_message_history and permissions.add_reactions and permissions.manage_messages):
            return await interaction.followup.send('The bot needs View Channel, Send Messages, Read Message History, Add Reactions and Manage Messages in this control channel.',ephemeral=True)
        if channel.permissions_for(interaction.guild.default_role).view_channel:
            return await interaction.followup.send('Select a private admin control channel.',ephemeral=True)
        message=await channel.send('Melee Zone recovery control\nThe configured recovery owner clicks the reset reaction once to request recovery. This control also works when the main bot process is stopped. Each pulse runs diagnostics and requests a bounded service restart.',allowed_mentions=discord.AllowedMentions.none())
        await message.add_reaction(PULSE)
        runtime=Path(os.getenv('RUNTIME_DIR','runtime'))
        await asyncio.to_thread(write_private_json,runtime/'recovery.json',{'guild_id':str(interaction.guild_id),'channel_id':str(channel.id),'message_id':str(message.id),'owner_id':owner,'emoji':PULSE})
        await interaction.followup.send(f'Recovery control: {message.jump_url}. Only <@{owner}> is accepted. The separate recovery service polls this pulse every 15 seconds.',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name='backup',description='Create a consistent database backup (recovery owner)')
    async def backup(self,interaction:discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config=await self.require_admin(interaction)
        if config is None:
            return
        if str(interaction.user.id)!=recovery_owner(config):
            return await interaction.followup.send('Recovery owner access required.',ephemeral=True)
        from datetime import datetime,timezone
        path=Path('backups')/f"manual-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.db"
        await self.db.online_backup(path)
        await interaction.followup.send(f'Database backup saved: {path.name}.',ephemeral=True)


async def setup(bot):
    await bot.add_cog(HealthCog(bot))
