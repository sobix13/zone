"""Thread-aware reactions with a durable inbox and atomic per-admin awards."""
import logging
import discord
from discord.ext import commands
from helpers import BotHelpers
from role_utils import role_manage_error, resolve_member
from runtime_utils import emoji_key, resolve_channel, valid_amount

log=logging.getLogger('MeleeZone.Reactions')


def reaction_amount(config,emoji):
    key=emoji_key(emoji)
    for n in range(1,6):
        configured=config.get(f'reaction_emoji_{n}')
        if configured and emoji_key(configured)==key:
            value=config.get(f'reaction_mc_{n}')
            if value is None:
                value=n
            if float(value)==0:
                return None
            return valid_amount(value)
    return None


class ReactionsCog(BotHelpers,commands.Cog,name='Reactions'):
    def __init__(self,bot):
        self.bot=bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self,payload: discord.RawReactionActionEvent):
        if not payload.guild_id or payload.user_id==getattr(self.bot.user,'id',None):
            return
        guild=self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        config=await self.db.get_guild_config(str(guild.id)) or {}
        if config.get('raffle_reaction_emoji') and emoji_key(payload.emoji)==emoji_key(config['raffle_reaction_emoji']):
            admin=getattr(payload,'member',None) or await resolve_member(guild,payload.user_id)
            if admin and not admin.bot and self.is_admin(admin,config):
                await self._handle_raffle_reaction(payload,guild,config)
            return
        try:
            amount=reaction_amount(config,payload.emoji)
        except ValueError:
            await self.db.record_operation('reaction','invalid_configuration',guild_id=str(guild.id),detail='Invalid configured MC value.')
            return
        if amount is None:
            return
        member=getattr(payload,'member',None)
        if member and (member.bot or not self.is_admin(member,config)):
            return
        await self.db.enqueue_reaction(str(guild.id),str(payload.channel_id),str(payload.message_id),str(payload.user_id),payload.emoji,amount)

    async def process_event(self,event):
        guild=self.bot.get_guild(int(event['guild_id']))
        if guild is None:
            raise RuntimeError('Server is not ready.')
        config=await self.db.get_guild_config(str(guild.id)) or {}
        admin=await resolve_member(guild,int(event['admin_id']))
        if not admin or admin.bot or not self.is_admin(admin,config):
            return 'unauthorized'
        channel=await resolve_channel(self.bot,guild,event['channel_id'])
        if not channel or not hasattr(channel,'fetch_message'):
            raise RuntimeError('Channel or thread is unavailable. Check View Channel and thread membership.')
        if not channel.permissions_for(guild.me).read_message_history:
            raise RuntimeError('Missing Read Message History in the target channel or thread.')
        try:
            message=await channel.fetch_message(int(event['message_id']))
        except discord.NotFound:
            return 'deleted_message'
        if not message.author or message.author.bot or str(message.author.id)==event['admin_id']:
            return 'ineligible_author'
        created=await self.db.award_reaction_atomic(
            guild_id=event['guild_id'],channel_id=event['channel_id'],message_id=event['message_id'],
            author_id=str(message.author.id),username=message.author.name,admin_id=event['admin_id'],
            emoji=event['emoji'],amount=event['amount'],notice_channel=config.get('credit_log_channel_id'))
        result='awarded' if created else 'already_awarded'
        await self.db.record_operation('reaction',result,guild_id=event['guild_id'],actor_id=event['admin_id'],reference_id=event['message_id'])
        return result

    async def _handle_raffle_reaction(self,payload,guild,config):
        role=guild.get_role(int(config['raffle_role_id'])) if config.get('raffle_role_id') else None
        if not role:
            return
        error=role_manage_error(guild,role)
        if error:
            await self.db.record_operation('raffle_reaction','blocked',guild_id=str(guild.id),detail=error)
            return
        channel=await resolve_channel(self.bot,guild,payload.channel_id)
        if not channel:
            return
        try:
            message=await channel.fetch_message(payload.message_id)
            if message.author.bot:
                return
            member=await resolve_member(guild,message.author.id)
            if member and role not in member.roles:
                await member.add_roles(role,reason=f'Raffle reaction by {payload.user_id}')
        except discord.HTTPException as exc:
            log.warning('Raffle reaction failed: %s',type(exc).__name__)
            await self.db.record_operation('raffle_reaction','failed',guild_id=str(guild.id),detail=type(exc).__name__)


async def setup(bot):
    await bot.add_cog(ReactionsCog(bot))
