import asyncio
import os
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands,tasks
from helpers import BotHelpers
from runtime_utils import authorized,utc_iso
from activity_service import message_row,role_roster,process_report


class RoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder='Select a role for the activity report',min_values=1,max_values=1)

    async def callback(self,interaction):
        if not await authorized(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await interaction.client.get_cog('Activity').queue_report(interaction,self.values[0],30,20000)


class RoleReportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(RoleSelect())

    async def interaction_check(self,interaction):
        return await authorized(interaction)


class ActivityCog(BotHelpers,commands.Cog,name='Activity'):
    def __init__(self,bot):
        self.bot=bot
        self._watch_cache={}

    async def cog_load(self):
        self.report_worker.start()

    async def cog_unload(self):
        self.report_worker.cancel()
        task=self.report_worker.get_task()
        if task:
            await asyncio.gather(task,return_exceptions=True)

    async def watched(self,member):
        guild=getattr(member,'guild',None)
        if not guild or getattr(member,'bot',False):
            return False
        key=str(guild.id)
        cached=self._watch_cache.get(key)
        if not cached or cached[0]<time.monotonic():
            roles=await self.db.watched_roles(key)
            config=await self.db.get_guild_config(key) or {}
            if config.get('pro_role_id'):
                roles.add(str(config['pro_role_id']))
            cached=(time.monotonic()+30,roles)
            self._watch_cache[key]=cached
        return any(str(r.id) in cached[1] for r in getattr(member,'roles',[]))

    @commands.Cog.listener()
    async def on_message(self,message):
        if message.guild and await self.watched(message.author):
            await self.db.store_activity_messages([message_row(message)])

    @commands.Cog.listener()
    async def on_raw_message_delete(self,payload):
        await self.db.mark_activity_deleted([payload.message_id])

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self,payload):
        await self.db.mark_activity_deleted(payload.message_ids)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self,payload):
        member=getattr(payload,'member',None)
        if member and await self.watched(member):
            await self.db.store_activity_event(str(payload.guild_id),str(payload.user_id),'reaction: '+str(payload.emoji),str(payload.channel_id),
                f'reaction-event:{payload.message_id}:{payload.user_id}:{time.time_ns()}')

    @commands.Cog.listener()
    async def on_interaction(self,interaction):
        if interaction.guild and await self.watched(interaction.user):
            action='command: '+interaction.command.name if interaction.command else 'panel action'
            await self.db.store_activity_event(str(interaction.guild_id),str(interaction.user.id),action,str(interaction.channel_id),f'interaction:{interaction.id}')

    @tasks.loop(seconds=5)
    async def report_worker(self):
        await self.bot.wait_until_ready()
        job=await self.db.next_role_job()
        if not job:
            return
        try:
            await process_report(self.bot,job,time_budget=int(os.getenv('REPORT_TIME_BUDGET','1200')))
        except asyncio.CancelledError:
            await self.db.update_role_job(job['id'],state='queued')
            raise
        except Exception as exc:
            await self.db.update_role_job(job['id'],state='paused',error=f'Report paused: {type(exc).__name__}. Use resume.')
            await self.db.record_operation('role_report','paused',guild_id=job['guild_id'],reference_id=job['id'],detail=type(exc).__name__)

    @report_worker.before_loop
    async def before_reports(self):
        await self.bot.wait_until_ready()

    async def queue_report(self,interaction,role,days,max_messages):
        if role.is_default():
            return await interaction.followup.send('Choose a specific role.',ephemeral=True)
        try:
            members=await role_roster(interaction.guild,role)
        except (discord.HTTPException,asyncio.TimeoutError) as exc:
            return await interaction.followup.send(f'Full member inventory failed: {type(exc).__name__}. Check Server Members Intent. No partial roster was used.',ephemeral=True)
        if not members:
            return await interaction.followup.send('This role has no members.',ephemeral=True)
        cutoff=utc_iso(datetime.now(timezone.utc)-timedelta(days=days)) if days else None
        try:
            job_id=await self.db.create_role_job(str(interaction.guild_id),role,str(interaction.user.id),members,cutoff,max_messages)
        except ValueError as exc:
            return await interaction.followup.send(str(exc),ephemeral=True)
        await self.db.watch_role(str(interaction.guild_id),str(role.id))
        self._watch_cache.pop(str(interaction.guild_id),None)
        await interaction.followup.send(f'Report {job_id} queued for {len(members)} members. Use `/role_report_status job_id:{job_id}` to get the Excel file. Activity tracking for this role is active.',ephemeral=True)

    @app_commands.command(name='role_report',description='Export role members, activity and MC to Excel (admin)')
    @app_commands.describe(days='0 scans all accessible history. Default: 30 days.',max_messages='Total messages scanned across channels. Resume adds another budget.')
    async def role_report(self,interaction:discord.Interaction,role:discord.Role,days:app_commands.Range[int,0,3650]=30,max_messages:app_commands.Range[int,100,200000]=20000):
        await interaction.response.defer(ephemeral=True)
        if await self.require_admin(interaction) is None:
            return
        await self.queue_report(interaction,role,days,max_messages)

    @app_commands.command(name='role_report_status',description='Get report progress and its current Excel file (admin)')
    async def role_report_status(self,interaction:discord.Interaction,job_id:str):
        await interaction.response.defer(ephemeral=True)
        if await self.require_admin(interaction) is None:
            return
        job=await self.db.get_role_job(job_id,str(interaction.guild_id))
        if not job:
            return await interaction.followup.send('Report not found in this server.',ephemeral=True)
        text=f"Report {job_id}: {job['state']}. Scanned: {job['scanned']:,}/{job['max_messages']:,}."
        if job.get('error'):
            text+=' '+job['error']
        file=None
        if job.get('output_path'):
            path=Path(job['output_path']).resolve()
            base=Path(os.getenv('REPORT_DIR','runtime/reports')).resolve()
            if path.is_relative_to(base) and path.is_file() and path.stat().st_size<8*1024*1024:
                file=discord.File(path)
            elif path.is_file():
                text+=' Export exceeds the attachment limit. Download it from the server reports folder.'
        await interaction.followup.send(text,file=file,ephemeral=True) if file else await interaction.followup.send(text,ephemeral=True)

    @app_commands.command(name='role_report_resume',description='Continue a paused report from its saved cursor (admin)')
    async def role_report_resume(self,interaction:discord.Interaction,job_id:str,extra_messages:app_commands.Range[int,100,200000]=20000):
        await interaction.response.defer(ephemeral=True)
        if await self.require_admin(interaction) is None:
            return
        job=await self.db.get_role_job(job_id,str(interaction.guild_id))
        if not job or job['state']!='paused':
            return await interaction.followup.send('Select a paused report.',ephemeral=True)
        await self.db.update_role_job(job_id,state='queued',error=None,max_messages=job['max_messages']+extra_messages)
        await interaction.followup.send('Queued to continue from the saved cursor.',ephemeral=True)

    @app_commands.command(name='role_report_cancel',description='Stop a report and retain the collected history (admin)')
    async def role_report_cancel(self,interaction:discord.Interaction,job_id:str):
        await interaction.response.defer(ephemeral=True)
        if await self.require_admin(interaction) is None:
            return
        job=await self.db.get_role_job(job_id,str(interaction.guild_id))
        if not job or job['state'] not in ('queued','running','paused'):
            return await interaction.followup.send('Select an active or paused report.',ephemeral=True)
        await self.db.update_role_job(job_id,state='cancelled')
        await interaction.followup.send('Report cancelled. Its indexed messages remain available.',ephemeral=True)


async def setup(bot):
    await bot.add_cog(ActivityCog(bot))
