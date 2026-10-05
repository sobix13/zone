"""Pure per-guild access policy and bounded configuration validation."""
import json
import math
from runtime_utils import valid_amount

ACCESS_KEYS = frozenset({'moderator_role_id', 'super_admin_role_id', 'super_admin_user_ids', 'admin_user_id'})
RUNTIME_KEYS = frozenset({'guild_id', 'panel_message_id', 'leaderboard_message_id', 'last_weekly_cycle'})
SUPPORT_KEYS = frozenset({'enabled', 'reviewer_role_id', 'moderator_role_id', 'member_role_id', 'weekly_cap', 'sample_size'})
INTEGER_BOUNDS = {
    'max_submits_per_week': (1, 100), 'max_reviews_per_week': (1, 100),
    'min_reviews': (1, 100), 'primary_review_days': (1, 90),
    'total_review_days': (1, 90), 'review_window_days': (1, 90),
    'reminder_hours': (1, 2160), 'warning_grace_hours': (1, 2160),
    'rescue_review_limit': (1, 100), 'min_feedback_length': (1, 2000),
    'is_configured': (0, 1), 'require_twitter_id': (0, 1),
}


def same_guild(member, guild_id):
    return member is not None and str(getattr(getattr(member, 'guild', None), 'id', '')) == str(guild_id)


def has_role(member, role_id):
    return bool(role_id and any(str(getattr(r, 'id', '')) == str(role_id) for r in getattr(member, 'roles', ())))


def is_primary(member, config):
    if member is None or getattr(member, 'bot', False):
        return False
    guild = getattr(member, 'guild', None)
    if not guild or (config.get('guild_id') and not same_guild(member, config['guild_id'])):
        return False
    uid = str(member.id)
    if uid == str(getattr(guild, 'owner_id', '')) or uid == str(config.get('admin_user_id') or ''):
        return True
    try:
        ids = json.loads(config.get('super_admin_user_ids') or '[]')
    except (TypeError, ValueError):
        ids = []
    return (isinstance(ids, list) and uid in ids) or has_role(member, config.get('super_admin_role_id'))


def is_operator(member, config):
    if member is None or getattr(member, 'bot', False):
        return False
    if config.get('guild_id') and not same_guild(member, config['guild_id']):
        return False
    return bool(is_primary(member, config) or has_role(member, config.get('moderator_role_id'))
                or has_role(member, config.get('admin_role_id'))
                or getattr(getattr(member, 'guild_permissions', None), 'administrator', False))


def snowflake(value):
    if value is None:
        return None
    value = str(value)
    if not value.isdigit() or not 1 <= int(value) < 2**64:
        raise ValueError('Use a valid Discord ID.')
    return value


def normalize_guild_changes(current, changes, *, access=False):
    changes = dict(changes)
    unknown = set(changes) - set(current)
    forbidden = set(changes) & (RUNTIME_KEYS | (set() if access else ACCESS_KEYS))
    if unknown or forbidden:
        raise ValueError('These fields cannot be changed here: ' + ', '.join(sorted(unknown | forbidden)))
    if 'review_window_days' in changes and 'total_review_days' not in changes:
        changes['total_review_days'] = changes['review_window_days']
    if 'total_review_days' in changes:
        changes['review_window_days'] = changes['total_review_days']
    for key, value in tuple(changes.items()):
        if key in INTEGER_BOUNDS:
            low, high = INTEGER_BOUNDS[key]
            number = float(value)
            if not math.isfinite(number) or not number.is_integer() or not low <= number <= high:
                raise ValueError(f'{key} must be an integer from {low} to {high}.')
            changes[key] = int(number)
        elif key.startswith(('mc_', 'reaction_mc_', 'quiz_mc_')) and key != 'quiz_mc_min_pct':
            changes[key] = valid_amount(value, allow_zero=True)
        elif key in {'showcase_threshold', 'quiz_mc_min_pct'}:
            high = 10 if key == 'showcase_threshold' else 100
            number = float(value)
            if not math.isfinite(number) or not 0 <= number <= high:
                raise ValueError(f'{key} must be from 0 to {high}.')
            changes[key] = number
        elif key.endswith(('_role_id', '_channel_id', '_user_id')):
            changes[key] = snowflake(value)
        elif key == 'super_admin_user_ids':
            ids = json.loads(value) if isinstance(value, str) else value
            if not isinstance(ids, list) or len(ids) > 100:
                raise ValueError('Select at most 100 primary administrators.')
            if any(v is None for v in ids):
                raise ValueError('Primary administrator IDs cannot be empty.')
            changes[key] = json.dumps(sorted(set(snowflake(v) for v in ids)))
        elif value is not None:
            changes[key] = str(value)
            if len(changes[key]) > (4000 if key == 'txt_about' else 2000):
                raise ValueError(f'{key} is too long.')
    merged = {**current, **changes}
    if int(merged.get('primary_review_days') or 5) > int(merged.get('total_review_days') or 7):
        raise ValueError('Total review days must be at least the main review period.')
    return changes


def normalize_support_changes(changes):
    if set(changes) != SUPPORT_KEYS:
        raise ValueError('Supply the complete support configuration.')
    result = {k: snowflake(changes[k]) for k in ('reviewer_role_id', 'moderator_role_id', 'member_role_id')}
    if not result['reviewer_role_id'] or not result['moderator_role_id']:
        raise ValueError('Select reviewer and moderator roles first.')
    for key, maximum in [('weekly_cap', 50), ('sample_size', 5)]:
        value = float(changes[key])
        if not math.isfinite(value) or not value.is_integer() or not 1 <= value <= maximum:
            raise ValueError(f'{key} must be an integer from 1 to {maximum}.')
        result[key] = int(value)
    if changes['enabled'] not in (False, True, 0, 1):
        raise ValueError('Enabled must be true or false.')
    result['enabled'] = int(changes['enabled'])
    return result
