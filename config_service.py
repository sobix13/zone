"""The only interaction-facing configuration writer, shared by old and new UI."""
import logging
import asyncio
import discord
from role_utils import resolve_member

log = logging.getLogger('MeleeZone.Configuration')


async def reply(interaction, content=None, **kwargs):
    kwargs.setdefault('ephemeral', True)
    kwargs.setdefault('allowed_mentions', discord.AllowedMentions.none())
    if interaction.response.is_done():
        return await interaction.followup.send(content, **kwargs)
    return await interaction.response.send_message(content, **kwargs)


async def current_member(interaction):
    if not interaction.guild:
        raise PermissionError('Use this inside the server.')
    member = await resolve_member(interaction.guild, interaction.user.id)
    if member is None:
        raise PermissionError('Your current server membership could not be verified.')
    return member


def validate_targets(interaction, changes):
    """Discord selectors/slash commands must reference extant, specific targets."""
    for key, value in changes.items():
        if value is None:
            continue
        if key.endswith('_role_id'):
            role = interaction.guild.get_role(int(value))
            if role is None or role.is_default():
                raise ValueError(f'{key}: select an existing specific role in this server, not @everyone.')
        elif key.endswith('_channel_id'):
            channel = interaction.guild.get_channel(int(value))
            if channel is None:
                raise ValueError(f'{key}: select an existing channel in this server.')


async def request_config_change(interaction, *, scope='guild', reason='', **changes):
    """True means applied by a primary admin. False means queued/denied/no-op."""
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    try:
        member = await current_member(interaction)
        validate_targets(interaction, changes)
        result = await interaction.client.db.submit_config_change(str(interaction.guild_id), member, scope, changes,
                    source_id=str(interaction.id), reason=reason or f"{getattr(interaction.command, 'name', None) or 'Panel'} configuration change")
    except (ValueError, PermissionError) as exc:
        await reply(interaction, str(exc))
        return False
    if result['state'] == 'applied':
        return True
    if result['state'] == 'unchanged':
        await reply(interaction, 'No settings changed.')
    else:
        await reply(interaction, f"Request `{result['id']}`: **{result['state']}**. Settings stay unchanged until a primary administrator approves. Use Admin Panel → Change requests to follow it.")
        # The durable queue is authoritative. Notification delivery is best-effort.
        channel_id = (await interaction.client.db.get_guild_config(str(interaction.guild_id)) or {}).get('log_channel_id')
        channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
        if channel:
            try:
                async with asyncio.timeout(5):
                    await channel.send(f"Configuration request `{result['id']}` from <@{member.id}> is waiting. Open Admin Panel → Change requests.",
                                       allowed_mentions=discord.AllowedMentions.none())
            except (discord.HTTPException, asyncio.TimeoutError, OSError):
                log.warning('Could not deliver config-request notification; durable queue retained.')
    return False
