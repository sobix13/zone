"""Small shared helpers. No Discord calls occur while database locks are held."""
import math
import re
import unicodedata
from datetime import datetime, timezone
import discord

UTC = timezone.utc


def utc_iso(value=None):
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_time(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def emoji_key(value):
    """Custom emoji names change. IDs do not. Preserve Unicode ZWJ sequences."""
    eid = getattr(value, 'id', None)
    if eid:
        return f'custom:{eid}'
    text = str(value or '').strip()
    match = re.fullmatch(r'<a?:[^:>]+:(\d+)>', text)
    if match:
        return f'custom:{match.group(1)}'
    if text.startswith('custom:') and text[7:].isdigit():
        return text
    return unicodedata.normalize('NFC', text).replace('\ufe0f', '').replace('\ufe0e', '')


def valid_amount(amount, *, allow_zero=False):
    value = float(amount)
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero) or value > 1000:
        raise ValueError('Amount must be a finite number above zero and at most 1000.')
    return value


def parse_member_ids(text, limit=25):
    ids = []
    for part in re.split(r'[\s,]+', (text or '').strip()):
        if not part:
            continue
        match = re.fullmatch(r'(?:<@!?(\d{10,22})>|(\d{10,22}))', part)
        if not match:
            raise ValueError('Use member mentions or Discord IDs, separated by spaces or commas.')
        uid = match.group(1) or match.group(2)
        if uid not in ids:
            ids.append(uid)
    if not ids or len(ids) > limit:
        raise ValueError(f'Select between 1 and {limit} members.')
    return ids


async def resolve_channel(bot, guild, channel_id):
    channel = guild.get_channel_or_thread(int(channel_id))
    if channel is None:
        channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    if getattr(getattr(channel, 'guild', None), 'id', None) != guild.id:
        return None
    return channel


async def authorized(interaction):
    """Recheck current roles on every sensitive button and modal submission."""
    from helpers import BotHelpers
    from role_utils import resolve_member
    if not interaction.guild:
        return False
    member = await resolve_member(interaction.guild, interaction.user.id)
    config = await interaction.client.db.get_guild_config(str(interaction.guild_id)) or {}
    helper = BotHelpers()
    if member and helper.is_admin(member, config):
        return True
    responder = interaction.followup if interaction.response.is_done() else interaction.response
    await responder.send('Administrator access required.', ephemeral=True) if interaction.response.is_done() else await responder.send_message('Administrator access required.', ephemeral=True)
    return False
