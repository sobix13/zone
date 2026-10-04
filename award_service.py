"""One manual-award path for slash commands, panels and message actions."""
from role_utils import resolve_member
from runtime_utils import authorized,valid_amount


async def manual_award(interaction,ids,amount,mc_type,reason,*,operation_id=None):
    if not await authorized(interaction):
        return None
    amount=valid_amount(amount)
    reason=(reason or '').strip()
    if not reason:
        raise ValueError('Add a reason for the award.')
    members=[]
    for uid in dict.fromkeys(str(x) for x in ids):
        member=await resolve_member(interaction.guild,int(uid))
        if not member or member.bot:
            raise ValueError(f'Member {uid} is unavailable or is a bot. No MC was awarded.')
        members.append({'id':str(member.id),'name':member.name})
    if not 1<=len(members)<=25:
        raise ValueError('Select between 1 and 25 members.')
    config=await interaction.client.db.get_guild_config(str(interaction.guild_id)) or {}
    return await interaction.client.db.award_batch_atomic(str(interaction.guild_id),str(interaction.user.id),
        members,amount,mc_type,reason,str(operation_id or interaction.id),notice_channel=config.get('credit_log_channel_id'))
