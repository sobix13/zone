import asyncio
import time
from types import SimpleNamespace
import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from runtime_utils import authorized,utc_iso
from award_service import manual_award
from cogs.reactions import reaction_amount


class MessageAwardModal(discord.ui.Modal,title='Award MC for this message'):
    amount=discord.ui.TextInput(label='MC amount',default='1',max_length=8)
    reason=discord.ui.TextInput(label='Reason',default='Useful contribution',max_length=200)

    def __init__(self,message):
        super().__init__()
        self.message=message

    async def interaction_check(self,interaction):
        return await authorized(interaction)

    async def on_submit(self,interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            result=await manual_award(interaction,[self.message.author.id],self.amount.value,'regular',self.reason.value,
                operation_id=f'message-action:{self.message.id}:{interaction.id}')
        except ValueError as exc:
            return await interaction.followup.send(str(exc),ephemeral=True)
        if result is not None:
            await interaction.followup.send(f"MC recorded for {len(result['created'])} member(s).",ephemeral=True)


class MCToolsCog(BotHelpers,commands.Cog,name='MCTools'):
    def __init__(self,bot):
        self.bot=bot
        self.menu=app_commands.ContextMenu(name='Award MC',callback=self.message_award)
        self.quick_menu=app_commands.ContextMenu(name='Award 1 MC',callback=self.quick_award)
        self._reconcile_lock=asyncio.Lock()
        self._reconcile_last={}

    async def cog_load(self):
        self.bot.tree.add_command(self.menu)
        self.bot.tree.add_command(self.quick_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.menu.name,type=self.menu.type)
        self.bot.tree.remove_command(self.quick_menu.name,type=self.quick_menu.type)

    async def message_award(self,interaction:discord.Interaction,message:discord.Message):
        if await authorized(interaction):
            await interaction.response.send_modal(MessageAwardModal(message))

    async def quick_award(self,interaction:discord.Interaction,message:discord.Message):
        await interaction.response.defer(ephemeral=True)
        try:
            result=await manual_award(interaction,[message.author.id],1,'regular','Useful contribution',
                operation_id=f'quick-message:{message.id}')
        except ValueError as exc:
            return await interaction.followup.send(str(exc),ephemeral=True)
        if result is not None:
            await interaction.followup.send('1 MC awarded.' if result['created'] else 'You already gave 1 MC to this message with this action.',ephemeral=True)

    @app_commands.command(name='mc_audit',description='View recent MC transactions for a member (admin)')
    async def mc_audit(self,interaction:discord.Interaction,user:discord.Member):
        await interaction.response.defer(ephemeral=True)
        if await self.require_admin(interaction) is None:
            return
        rows=await self.db.get_mc_transactions(str(user.id),str(interaction.guild_id),15)
        text='\n'.join(f"{r['timestamp']} | +{r['amount']:g} {r['mc_type']} | {(r['reason'] or '')[:60]} | {r.get('admin_id') or 'automatic'}" for r in rows)
        await interaction.followup.send(text[:1900] or 'No MC transactions.',ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name='mc_reconcile',description='Recover uncredited admin reactions in this channel or thread (admin)')
    async def mc_reconcile(self,interaction:discord.Interaction,hours:app_commands.Range[int,1,168]=24):
        await interaction.response.defer(ephemeral=True)
        config=await self.require_admin(interaction)
        if config is None:
            return
        key=(interaction.guild_id,interaction.channel_id)
        if self._reconcile_lock.locked() or time.monotonic()-self._reconcile_last.get(key,-1e9)<60:
            return await interaction.followup.send('A reconciliation is running or ran within the last minute.',ephemeral=True)
        from datetime import datetime,timedelta,timezone
        cutoff=datetime.now(timezone.utc)-timedelta(hours=hours)
        examined=queued=0
        async with self._reconcile_lock:
            self._reconcile_last[key]=time.monotonic()
            async with asyncio.timeout(90):
                try:
                    async for message in interaction.channel.history(limit=200,after=cutoff,oldest_first=False):
                        examined+=1
                        for reaction in message.reactions:
                            amount=reaction_amount(config,reaction.emoji)
                            if amount is None:
                                continue
                            async for user in reaction.users(limit=100):
                                if user.bot:
                                    continue
                                member=interaction.guild.get_member(user.id)
                                if member and self.is_admin(member,config):
                                    await self.db.enqueue_reaction(str(interaction.guild_id),str(interaction.channel_id),str(message.id),str(user.id),reaction.emoji,amount)
                                    queued+=1
                except discord.HTTPException as exc:
                    return await interaction.followup.send(f'History scan failed: {type(exc).__name__}. Queued awards remain safe to retry.',ephemeral=True)
        await interaction.followup.send(f'Examined {examined} recent messages. Queued {queued} admin reactions. Existing awards stay unchanged. The scan is limited to 200 messages and 100 users per reaction.',ephemeral=True)

    @app_commands.command(name='task_reset_cooldown',description='Reset one member cooldown in the current community task (admin)')
    async def task_reset_cooldown(self,interaction:discord.Interaction,user:discord.Member):
        await interaction.response.defer(ephemeral=True)
        if await self.require_admin(interaction) is None:
            return
        assignment=await self.db.get_assignment_by_thread(str(interaction.channel_id))
        if not assignment:
            return await interaction.followup.send('Run this inside a community task thread.',ephemeral=True)
        await self.db.reset_task_cooldown(str(interaction.channel_id),str(user.id))
        await interaction.followup.send('Member cooldown reset.',ephemeral=True)


async def setup(bot):
    await bot.add_cog(MCToolsCog(bot))
