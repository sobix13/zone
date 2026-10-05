"""Primary-admin access management and durable configuration request review."""
import io
import json
import discord
from discord import app_commands
from discord.ext import commands
from access_policy import is_primary
from config import mz
from config_service import current_member, reply, validate_targets
from ui_security import AdminView, AdminModal


async def require_primary(i):
    try:
        member = await current_member(i)
        config = await i.client.db.get_guild_config(str(i.guild_id)) or {}
        if not is_primary(member, config):
            raise PermissionError('Only a primary administrator can do this. Discord Administrator alone does not grant approval access.')
        return member
    except PermissionError as exc:
        await reply(i, str(exc))
        return None


class PrimaryView(AdminView):
    async def interaction_check(self, i):
        return bool(await require_primary(i))


async def manage_role(i, key, role):
    if not i.response.is_done():await i.response.defer(ephemeral=True)
    member = await require_primary(i)
    if member is None:return
    if role and (role.guild.id != i.guild_id or role.is_default()):
        return await reply(i, 'Select a specific role in this server, not @everyone.')
    try:
        result = await i.client.db.submit_config_change(str(i.guild_id), member, 'guild',
            {key:str(role.id) if role else None}, source_id=str(i.id), access=True, reason='Primary-admin access management')
    except (ValueError, PermissionError) as exc:
        return await reply(i, str(exc))
    await reply(i, f"Access setting: {result['state']}. Server owner and the original named primary admin are retained.")


async def manage_user(i, user, grant):
    if not i.response.is_done():await i.response.defer(ephemeral=True)
    member = await require_primary(i)
    if member is None:return
    if user.guild.id != i.guild_id or user.bot:
        return await reply(i, 'Choose a human member of this server.')
    config = await i.client.db.get_guild_config(str(i.guild_id)) or {}
    stored = config.get('super_admin_user_ids') or '[]'
    ids = set(json.loads(stored))
    ids.add(str(user.id)) if grant else ids.discard(str(user.id))
    try:
        result = await i.client.db.submit_config_change(str(i.guild_id), member, 'guild',
            {'super_admin_user_ids':sorted(ids)}, source_id=str(i.id), access=True,
            expected={'super_admin_user_ids':stored}, reason=f"{'Grant' if grant else 'Remove'} named primary admin {user.id}")
    except (ValueError, PermissionError) as exc:
        return await reply(i, str(exc))
    await reply(i, f"Named primary admin: {result['state']}. Removing a named grant does not remove access inherited from the primary role, original primary-admin ID or server ownership.")


class AccessRolePicker(discord.ui.RoleSelect):
    def __init__(self, key, label, row):
        super().__init__(placeholder=label, min_values=1, max_values=1, row=row)
        self.key = key
    async def callback(self, i):await manage_role(i, self.key, self.values[0])


class AccessUserPicker(discord.ui.UserSelect):
    def __init__(self, grant, row):
        super().__init__(placeholder='Add named primary admin' if grant else 'Remove named primary admin',
                         min_values=1, max_values=1, row=row)
        self.grant = grant
    async def callback(self, i):
        if not i.response.is_done():await i.response.defer(ephemeral=True)
        user = i.guild.get_member(self.values[0].id)
        if user is None:
            from role_utils import resolve_member
            user = await resolve_member(i.guild, self.values[0].id)
        if user is None:return await reply(i, 'This member could not be verified.')
        await manage_user(i, user, self.grant)


class AccessView(PrimaryView):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(AccessRolePicker('moderator_role_id', 'Moderator panel role', 0))
        self.add_item(AccessRolePicker('super_admin_role_id', 'Primary admin role', 1))
        self.add_item(AccessUserPicker(True, 2))
        self.add_item(AccessUserPicker(False, 3))

    @discord.ui.button(label='View access', style=discord.ButtonStyle.secondary, row=4)
    async def view(self, i, button):
        c = await i.client.db.get_guild_config(str(i.guild_id)) or {}
        ids = json.loads(c.get('super_admin_user_ids') or '[]')
        text = f"Server owner: {i.guild.owner_id}\nOriginal primary admin: {c.get('admin_user_id') or 'not set'}\nModerator panel role: {c.get('moderator_role_id') or 'not set'}\nLegacy operational role: {c.get('admin_role_id') or 'not set'}\nPrimary admin role: {c.get('super_admin_role_id') or 'not set'}\nNamed primary admins: {', '.join(ids) or 'none'}"
        await reply(i, text[:1900])

    @discord.ui.button(label='Clear primary role', style=discord.ButtonStyle.danger, row=4)
    async def clear_primary_role(self, i, button):await manage_role(i, 'super_admin_role_id', None)

    @discord.ui.button(label='Clear moderator role', style=discord.ButtonStyle.secondary, row=4)
    async def clear_moderator_role(self, i, button):await manage_role(i, 'moderator_role_id', None)


def request_embed(row):
    old, changes = json.loads(row['old_json']), json.loads(row['changes_json'])
    lines = [f"**{discord.utils.escape_markdown(key)}**\n{str(old.get(key))[:180]} → {str(value)[:180]}" for key, value in changes.items()]
    e = discord.Embed(title=f"Configuration request: {row['state']}", description='\n\n'.join(lines)[:3400], color=mz('secondary'))
    e.add_field(name='Request ID', value=row['id'], inline=False)
    e.add_field(name='Requested by / scope', value=f"{row['actor_id']} / {row['scope']}", inline=False)
    e.add_field(name='Reason', value=(row['reason'] or 'Not supplied')[:1000], inline=False)
    if row.get('decided_by'):
        e.add_field(name='Decision', value=f"{row['decided_by']} / {(row.get('decision_note') or 'No note')[:900]}", inline=False)
    e.set_footer(text='The attached JSON contains every complete before/after value. Pending requests do not change active settings.')
    return e


async def show_request(i, request_id):
    if not i.response.is_done():await i.response.defer(ephemeral=True)
    try:
        row = await i.client.db.get_config_request(str(i.guild_id), await current_member(i), request_id)
    except PermissionError as exc:
        return await reply(i, str(exc))
    if row is None:return await reply(i, 'Request not found or not accessible.')
    c = await i.client.db.get_guild_config(str(i.guild_id)) or {}
    primary = is_primary(await current_member(i), c)
    data = dict(row)
    data['before'], data['after'] = json.loads(data.pop('old_json')), json.loads(data.pop('changes_json'))
    file = discord.File(io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode()), filename=f"request-{row['id']}.json")
    await reply(i, embed=request_embed(row), file=file,
                view=DecisionView(row['id']) if primary and row['state'] == 'pending' else None)


class DecisionModal(AdminModal, title='Configuration decision'):
    note = discord.ui.TextInput(label='Reason or note (optional)', style=discord.TextStyle.paragraph, required=False, max_length=1000)
    def __init__(self, request_id, approve):
        super().__init__(); self.request_id, self.approve = request_id, approve
    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        member = await require_primary(i)
        if member is None:return
        try:
            if self.approve:
                pending = await i.client.db.get_config_request(str(i.guild_id), member, self.request_id)
                if pending and pending['state'] == 'pending':
                    validate_targets(i, json.loads(pending['changes_json']))
            row = await i.client.db.decide_config_request(str(i.guild_id), member, self.request_id,
                                                         approve=self.approve, note=self.note.value.strip())
        except (ValueError, PermissionError) as exc:
            return await reply(i, str(exc))
        await reply(i, f"Request `{row['id']}`: **{row['state']}**. " +
                    ('The configuration was applied atomically.' if row['state'] == 'approved' else 'No new settings were applied.') +
                    (f"\n{row['decision_note']}" if row.get('decision_note') else ''))


class DecisionView(PrimaryView):
    def __init__(self, request_id):super().__init__(timeout=300); self.request_id = request_id
    @discord.ui.button(label='Approve', style=discord.ButtonStyle.success)
    async def approve(self, i, button):
        if await require_primary(i):await i.response.send_modal(DecisionModal(self.request_id, True))
    @discord.ui.button(label='Reject', style=discord.ButtonStyle.danger)
    async def reject(self, i, button):
        if await require_primary(i):await i.response.send_modal(DecisionModal(self.request_id, False))


class RequestPicker(discord.ui.Select):
    def __init__(self, rows):
        options = [discord.SelectOption(label=f"{r['id'][:12]} · {r['state']}", value=r['id'],
                  description=f"{r['scope']} | {r['actor_id']} | {', '.join(json.loads(r['changes_json']))}"[:100]) for r in rows]
        super().__init__(placeholder='Open a request and its complete before/after values', options=options)
    async def callback(self, i):await show_request(i, self.values[0])


class RequestListView(AdminView):
    def __init__(self, rows, state):
        super().__init__(timeout=300); self.state = state
        self.cursor = rows[-1]['id'] if rows else ''
        if rows:self.add_item(RequestPicker(rows))
        self.next_page.disabled = len(rows) < 20
    @discord.ui.button(label='Next page', style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, i, button):await show_requests(i, state=self.state, after=self.cursor)
    @discord.ui.button(label='Refresh pending', style=discord.ButtonStyle.primary, row=1)
    async def refresh(self, i, button):await show_requests(i)
    @discord.ui.button(label='Decision history', style=discord.ButtonStyle.secondary, row=1)
    async def history(self, i, button):await show_requests(i, state='all')


async def show_requests(i, *, state='pending', after=''):
    if not i.response.is_done():await i.response.defer(ephemeral=True)
    try:
        member = await current_member(i)
        rows = await i.client.db.list_config_requests(str(i.guild_id), member, state=state, after=after)
    except (PermissionError, ValueError) as exc:
        return await reply(i, str(exc))
    config = await i.client.db.get_guild_config(str(i.guild_id)) or {}
    who = 'All server requests. Only primary admins approve or reject.' if is_primary(member, config) else 'Your requests only. Active settings remain unchanged until approval.'
    await reply(i, who + f"\n{len(rows)} request(s) on this page.", view=RequestListView(rows, state))


class GovernanceCog(commands.Cog, name='Governance'):
    def __init__(self, bot):self.bot = bot
    @app_commands.command(name='admin_access', description='Primary-admin-only access management')
    async def admin_access(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        if await require_primary(i):await reply(i, 'Select an operational moderator role, a primary-admin role, or named primary admins.', view=AccessView())
    @app_commands.command(name='config_requests', description='Review pending settings requests or view your request history')
    async def config_requests(self, i: discord.Interaction):await show_requests(i)
    @app_commands.command(name='config_request', description='Open a configuration request by its full ID')
    async def config_request(self, i: discord.Interaction, request_id: str):await show_request(i, request_id)


async def setup(bot):await bot.add_cog(GovernanceCog(bot))
