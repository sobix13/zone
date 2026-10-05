import asyncio
import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import discord
import pytest
from access_policy import is_operator, is_primary, normalize_guild_changes
from config_service import request_config_change
from database import Database
from cogs.control_center import RulesModal, ScoreRewardsModal, ConfigRoleSelect, ConfigChannelSelect
from cogs.governance import AccessView, DecisionView, DecisionModal, show_requests, show_request, manage_user
from cogs.assignments import (AssignmentsCog, CreateAssignmentModal, CloseAssignmentModal,
                              AssignmentAdminView, change_task_cooldown, parse_task_cooldown)
from cogs.reactions import ReactionsCog
from award_service import manual_award
from tests.conftest import GID, OWNER, ADMIN2, AUTHOR, THREAD, PARENT, interaction, member

MOD_ROLE = 100000000000000020
PRIMARY_ROLE = 100000000000000021


async def make_mod(db, guild):
    role = SimpleNamespace(id=MOD_ROLE)
    guild.roster[AUTHOR].roles = [role]
    await db.update_guild_config(str(GID), moderator_role_id=str(MOD_ROLE))
    return guild.roster[AUTHOR]


async def propose(db, guild, *, changes=None, source='proposal', now=None):
    return await db.submit_config_change(str(GID), guild.roster[ADMIN2], 'guild',
        changes or {'min_reviews':3}, source_id=source, reason='Test request', now=now)


@pytest.mark.asyncio
async def test_primary_role_named_user_and_legacy_owner(db, guild):
    config = await db.get_guild_config(str(GID))
    assert is_primary(guild.roster[OWNER], config)
    assert not is_primary(guild.roster[ADMIN2], config)  # native Administrator is operational only
    assert is_operator(guild.roster[ADMIN2], config)
    mod = await make_mod(db, guild)
    config = await db.get_guild_config(str(GID))
    assert is_operator(mod, config) and not is_primary(mod, config)
    await db.submit_config_change(str(GID), guild.roster[OWNER], 'guild',
        {'super_admin_role_id':str(PRIMARY_ROLE)}, source_id='role-grant', access=True)
    config = await db.get_guild_config(str(GID))
    mod.roles.append(SimpleNamespace(id=PRIMARY_ROLE))
    assert is_primary(mod, config)
    mod.roles = []
    assert not is_primary(mod, config)
    await db.submit_config_change(str(GID), guild.roster[OWNER], 'guild',
        {'super_admin_user_ids':[str(AUTHOR)]}, source_id='user-grant', access=True)
    assert is_primary(mod, await db.get_guild_config(str(GID)))
    guild.roster[OWNER].guild_permissions = discord.Permissions.none()
    assert is_primary(guild.roster[OWNER], await db.get_guild_config(str(GID)))


@pytest.mark.asyncio
async def test_pending_request_does_not_mutate_config_and_owner_approves(db, guild):
    before = await db.get_guild_config(str(GID))
    row = await propose(db, guild)
    assert row['state'] == 'pending'
    assert await db.get_guild_config(str(GID)) == before
    result = await db.decide_config_request(str(GID), guild.roster[OWNER], row['id'], approve=True, note='Reviewed')
    assert result['state'] == 'approved' and result['decided_by'] == str(OWNER)
    assert (await db.get_guild_config(str(GID)))['min_reviews'] == 3
    conn = await db._get_conn()
    events = await (await conn.execute('SELECT event FROM config_audit ORDER BY id')).fetchall()
    assert [r['event'] for r in events] == ['pending', 'approved']


@pytest.mark.asyncio
async def test_native_admin_cannot_approve_or_promote_self(db, guild):
    row = await propose(db, guild)
    with pytest.raises(PermissionError):
        await db.decide_config_request(str(GID), guild.roster[ADMIN2], row['id'], approve=True)
    with pytest.raises(PermissionError):
        await db.submit_config_change(str(GID), guild.roster[ADMIN2], 'guild',
            {'super_admin_user_ids':[str(ADMIN2)]}, source_id='attack', access=True)
    with pytest.raises(ValueError):
        await propose(db, guild, changes={'super_admin_role_id':str(MOD_ROLE)}, source='attack2')
    assert (await db.get_guild_config(str(GID)))['min_reviews'] == 5


@pytest.mark.asyncio
async def test_revoked_operator_and_removed_primary_role_cannot_use_stale_views(db, guild, fakebot, thread):
    mod = await make_mod(db, guild)
    i = interaction(fakebot, guild, thread, user_id=AUTHOR)
    view = AssignmentAdminView(db, await db.get_guild_config(str(GID)), guild)
    assert await view.interaction_check(i)
    mod.roles = []
    assert not await view.interaction_check(i)
    assert not await request_config_change(i, min_reviews=2)
    await db.update_guild_config(str(GID), super_admin_role_id=str(PRIMARY_ROLE))
    mod.roles = [SimpleNamespace(id=PRIMARY_ROLE)]
    decision = DecisionView('missing')
    assert await decision.interaction_check(i)
    mod.roles = []
    assert not await decision.interaction_check(i)


@pytest.mark.asyncio
async def test_reject_expire_and_stale_do_not_change_settings(db, guild):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = await propose(db, guild, source='reject', now=start)
    result = await db.decide_config_request(str(GID), guild.roster[OWNER], row['id'], approve=False, note='Keep current', now=start)
    assert result['state'] == 'rejected'
    row = await propose(db, guild, source='expired', now=start)
    result = await db.decide_config_request(str(GID), guild.roster[OWNER], row['id'], approve=True, now=start + timedelta(days=8))
    assert result['state'] == 'expired'
    row = await propose(db, guild, source='stale')
    await db.update_guild_config(str(GID), min_reviews=4)
    result = await db.decide_config_request(str(GID), guild.roster[OWNER], row['id'], approve=True)
    assert result['state'] == 'stale'
    assert (await db.get_guild_config(str(GID)))['min_reviews'] == 4


@pytest.mark.asyncio
async def test_approval_revalidates_related_current_metrics(db, guild):
    row = await propose(db, guild, changes={'total_review_days':6})
    await db.update_guild_config(str(GID), primary_review_days=7, total_review_days=8)
    result = await db.decide_config_request(str(GID), guild.roster[OWNER], row['id'], approve=True)
    assert result['state'] == 'stale'
    assert (await db.get_guild_config(str(GID)))['total_review_days'] == 8


@pytest.mark.asyncio
async def test_cross_guild_requests_and_bot_actors_rejected(db, guild):
    row = await propose(db, guild)
    other = MagicMock(spec=discord.Guild); other.id = GID + 1; other.owner_id = OWNER
    outsider = member(other, OWNER, admin=True)
    assert not is_primary(outsider, await db.get_guild_config(str(GID)))
    with pytest.raises(PermissionError):
        await db.decide_config_request(str(GID), outsider, row['id'], approve=True)
    with pytest.raises(PermissionError):
        await db.submit_config_change(str(GID), member(guild, OWNER, admin=True, bot=True), 'guild',
                                     {'min_reviews':2}, source_id='bot')
    await db.create_guild_config(str(other.id))
    with pytest.raises(ValueError):
        await db.decide_config_request(str(other.id), outsider, row['id'], approve=True)


@pytest.mark.asyncio
async def test_two_connections_approve_once_and_durable_restart(db, guild):
    row = await propose(db, guild)
    other = Database(db.db_path); await other.init()
    try:
        results = await asyncio.gather(*(writer.decide_config_request(str(GID), guild.roster[OWNER], row['id'], approve=True)
                                         for writer in [db, other] * 15))
        assert all(r['state'] == 'approved' for r in results)
        conn = await db._get_conn()
        count = (await (await conn.execute("SELECT COUNT(*) FROM config_audit WHERE event='approved'")).fetchone())[0]
        assert count == 1
        assert (await other.get_guild_config(str(GID)))['min_reviews'] == 3
    finally:
        await other.close()


@pytest.mark.asyncio
async def test_submit_idempotence_and_request_overload_bounded(db, guild):
    results = await asyncio.gather(*(propose(db, guild) for _ in range(30)))
    assert len({r['id'] for r in results}) == 1
    with pytest.raises(ValueError):await propose(db, guild, changes={'min_reviews':2})
    for n in range(9):await propose(db, guild, source=f'limit-{n}')
    with pytest.raises(ValueError):await propose(db, guild, source='overflow')
    assert len(await db.list_config_requests(str(GID), guild.roster[OWNER])) == 10
    row = results[0]
    await db.decide_config_request(str(GID), guild.roster[OWNER], row['id'], approve=False)
    assert (await propose(db, guild, source='after-review'))['state'] == 'pending'


@pytest.mark.asyncio
async def test_request_list_privacy_history_and_paging(db, guild):
    await make_mod(db, guild)
    own = await db.submit_config_change(str(GID), guild.roster[AUTHOR], 'guild', {'min_reviews':2}, source_id='own')
    other = await propose(db, guild)
    assert [r['id'] for r in await db.list_config_requests(str(GID), guild.roster[AUTHOR])] == [own['id']]
    assert await db.get_config_request(str(GID), guild.roster[AUTHOR], other['id']) is None
    await db.decide_config_request(str(GID), guild.roster[OWNER], own['id'], approve=False)
    assert not await db.list_config_requests(str(GID), guild.roster[AUTHOR])
    assert len(await db.list_config_requests(str(GID), guild.roster[AUTHOR], state='all')) == 1
    page = await db.list_config_requests(str(GID), guild.roster[OWNER], state='all', limit=1)
    next_page = await db.list_config_requests(str(GID), guild.roster[OWNER], state='all', after=page[0]['id'], limit=1)
    assert len(page) == len(next_page) == 1 and page[0]['id'] != next_page[0]['id']


@pytest.mark.parametrize('changes', [
    {'min_reviews':0}, {'max_reviews_per_week':101}, {'mc_score_high':float('nan')},
    {'reaction_mc_1':float('inf')}, {'quiz_mc_90':-1}, {'quiz_mc_min_pct':101},
    {'primary_review_days':10, 'total_review_days':5}, {'min_feedback_length':2001},
    {'moderator_role_id':str(MOD_ROLE)}, {'guild_id':'other'}, {'panel_message_id':'1'},
    {'min_reviews=1; DROP TABLE users; --':1}, {'reaction_emoji_1':'x' * 2001},
    {'showcase_threshold':float('nan')}, {'min_reviews':1.5}, {'admin_role_id':'not-an-id'},
])
@pytest.mark.asyncio
async def test_invalid_proposals_rejected_before_queue(db, guild, changes):
    before = await db.get_guild_config(str(GID))
    with pytest.raises((ValueError, TypeError)):
        await propose(db, guild, changes=changes)
    assert await db.get_guild_config(str(GID)) == before
    assert not await db.list_config_requests(str(GID), guild.roster[OWNER])
    assert not (await db._get_conn()).in_transaction


@pytest.mark.asyncio
async def test_support_config_is_approved_atomically_and_cycle_anchor_preserved(db, guild):
    changes = dict(enabled=True, reviewer_role_id=str(MOD_ROLE), moderator_role_id=str(PRIMARY_ROLE),
                   member_role_id=None, weekly_cap=10, sample_size=3)
    row = await db.submit_config_change(str(GID), guild.roster[ADMIN2], 'support', changes, source_id='support')
    assert not (await db.support_settings(str(GID)))['enabled']
    result = await db.decide_config_request(str(GID), guild.roster[OWNER], row['id'], approve=True)
    assert result['state'] == 'approved'
    first = await db.support_settings(str(GID))
    await db.submit_config_change(str(GID), guild.roster[OWNER], 'support', {**changes, 'weekly_cap':20}, source_id='support-primary')
    next_settings = await db.support_settings(str(GID))
    assert next_settings['anchor_at'] == first['anchor_at']
    assert next_settings['next_report_at'] == first['next_report_at']
    assert next_settings['weekly_cap'] == 20


@pytest.mark.asyncio
async def test_atomic_failure_rolls_back_settings_decision_and_audit(db, guild, monkeypatch):
    row = await propose(db, guild)
    original = db._governance_audit
    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError('Injected audit failure')
    monkeypatch.setattr(db, '_governance_audit', fail)
    with pytest.raises(RuntimeError):
        await db.decide_config_request(str(GID), guild.roster[OWNER], row['id'], approve=True)
    assert (await db.get_guild_config(str(GID)))['min_reviews'] == 5
    assert (await db.get_config_request(str(GID), guild.roster[OWNER], row['id']))['state'] == 'pending'
    assert not (await db._get_conn()).in_transaction


@pytest.mark.asyncio
async def test_modal_direct_callback_is_guarded_and_primary_gets_followup(db, guild, fakebot, thread):
    cfg = await db.get_guild_config(str(GID))
    modal = RulesModal(db, cfg)
    for field, text in [(modal.submits,'5'), (modal.reviews,'7'), (modal.minimum,'3'), (modal.showcase,'8')]:field._value = text
    i = interaction(fakebot, guild, thread, user_id=ADMIN2)
    await modal.on_submit(i)
    assert (await db.get_guild_config(str(GID)))['min_reviews'] == 5
    rows = await db.list_config_requests(str(GID), guild.roster[OWNER])
    assert len(rows) == 1
    assert 'pending' in i.followup.send.await_args.args[0]
    owner_i = interaction(fakebot, guild, thread, ident=2)
    await modal.on_submit(owner_i)
    assert (await db.get_guild_config(str(GID)))['min_reviews'] == 3
    assert 'updated' in owner_i.followup.send.await_args.args[0]


@pytest.mark.asyncio
async def test_all_legacy_configuration_writes_use_service():
    # Only runtime-generated message pointers and weekly cursor bypass approval.
    allowed = {('cogs/leaderboard.py', 'leaderboard_message_id'), ('cogs/panel.py', 'panel_message_id'),
               ('cogs/tasks.py', 'last_weekly_cycle')}
    root = Path(__file__).resolve().parents[1]
    for file in (root / 'cogs').glob('*.py'):
        tree = ast.parse(file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != 'configure_support', f'Unguarded support write: {file}:{node.lineno}'
                if node.func.attr == 'update_guild_config':
                    assert node.keywords and all((str(file.relative_to(root)), kw.arg) in allowed for kw in node.keywords), f'Unguarded settings write: {file}:{node.lineno}'


@pytest.mark.asyncio
async def test_request_ui_views_are_within_discord_limits(db, guild, fakebot, thread):
    row = await propose(db, guild)
    i = interaction(fakebot, guild, thread)
    await show_requests(i)
    view = i.followup.send.await_args.kwargs['view']
    assert len(view.children) <= 25 and all(len(str(c.custom_id)) <= 100 for c in view.children)
    i2 = interaction(fakebot, guild, thread, ident=2)
    await show_request(i2, row['id'])
    result = i2.followup.send.await_args.kwargs
    assert len(result['embed']) <= 6000
    assert isinstance(result['view'], DecisionView)
    payload = json.loads(result['file'].fp.getvalue())
    assert payload['before']['min_reviews'] == 5 and payload['after']['min_reviews'] == 3
    assert len(AccessView().children) == 7


@pytest.mark.asyncio
async def test_named_admin_access_update_rejects_stale_concurrent_list(db, guild):
    cfg = await db.get_guild_config(str(GID))
    await db.submit_config_change(str(GID), guild.roster[OWNER], 'guild', {'super_admin_user_ids':[str(AUTHOR)]},
                                 source_id='first-user', access=True)
    with pytest.raises(ValueError):
        await db.submit_config_change(str(GID), guild.roster[OWNER], 'guild', {'super_admin_user_ids':[str(ADMIN2)]},
                                     source_id='second-user', access=True, expected={'super_admin_user_ids':cfg['super_admin_user_ids']})
    assert json.loads((await db.get_guild_config(str(GID)))['super_admin_user_ids']) == [str(AUTHOR)]


@pytest.mark.asyncio
async def test_mod_task_create_edit_bypass_skip_close_and_award_without_approval(db, guild, fakebot, thread):
    mod = await make_mod(db, guild)
    parent = MagicMock(spec=discord.TextChannel); parent.id=PARENT; parent.guild=guild
    parent.permissions_for.return_value=discord.Permissions.all()
    parent.create_thread=AsyncMock(return_value=thread)
    guild.get_channel.side_effect=lambda cid:parent if cid==PARENT else None
    guild.get_thread.return_value=thread
    modal = CreateAssignmentModal(db, await db.get_guild_config(str(GID)), guild)
    modal.name._value='Free-form task'; modal.body._value='Any community task'; modal.cooldown._value='24h'; modal.recurring._value='yes'
    i = interaction(fakebot, guild, thread, user_id=AUTHOR)
    await modal.on_submit(i)
    task = await db.get_assignment_by_thread(str(THREAD))
    assert task and task['cooldown_seconds'] == 86400 and task['is_recurring'] == 1
    parent.create_thread.assert_awaited_once()
    await change_task_cooldown(interaction(fakebot, guild, thread, user_id=AUTHOR, ident=2), task['id'], '30m')
    assert (await db.get_assignment_by_thread(str(THREAD)))['cooldown_seconds'] == 1800
    await db.set_assignment_cooldown(str(THREAD), str(AUTHOR), datetime.now(timezone.utc).isoformat())
    cog = AssignmentsCog(fakebot)
    msg=SimpleNamespace(author=mod,guild=guild,channel=thread,created_at=datetime.now(timezone.utc),delete=AsyncMock())
    await cog.on_message(msg); await cog.on_message(msg)
    msg.delete.assert_not_awaited()
    from cogs.mc_tools import MCToolsCog
    tools=MCToolsCog(fakebot)
    await tools.task_reset_cooldown.callback(tools,interaction(fakebot,guild,thread,user_id=AUTHOR,ident=3),guild.roster[ADMIN2])
    assert await db.get_assignment_cooldown(str(THREAD),str(ADMIN2)) is None
    await manual_award(interaction(fakebot,guild,thread,user_id=AUTHOR,ident=4), [ADMIN2,OWNER], 2,'regular','Thanks')
    assert (await db.get_user(str(ADMIN2),str(GID)))['mc_regular'] == 2
    close=CloseAssignmentModal(db,guild);close.assignment_id._value=str(task['id']);close.archive._value='yes'
    await close.on_submit(interaction(fakebot,guild,thread,user_id=AUTHOR,ident=5))
    assert (await db.get_assignment_by_thread(str(THREAD)))['status']=='closed'
    assert not await db.list_config_requests(str(GID),guild.roster[OWNER],state='all')


@pytest.mark.asyncio
async def test_mod_reaction_in_thread_and_config_request_do_not_interfere(db, guild, fakebot, thread):
    mod=await make_mod(db,guild)
    await request_config_change(interaction(fakebot,guild,thread,user_id=AUTHOR), reaction_mc_1=5)
    thread.fetch_message.return_value=SimpleNamespace(author=guild.roster[ADMIN2])
    reactions=ReactionsCog(fakebot)
    payload=SimpleNamespace(guild_id=GID,channel_id=THREAD,message_id=990,user_id=AUTHOR,emoji='✅',member=mod)
    await reactions.on_raw_reaction_add(payload)
    event=(await db.pending_reactions())[0]
    assert await reactions.process_event(event)=='awarded'
    assert (await db.get_user(str(ADMIN2),str(GID)))['mc_regular']==1  # current rate, not proposed rate


@pytest.mark.parametrize('text,expected',[('0',0),('30m',1800),('1h',3600),('24h',86400),('7d',604800),('120',120)])
def test_task_cooldown_parser(text,expected):assert parse_task_cooldown(text)==expected


@pytest.mark.parametrize('text',['8d','-1','invalid','inf','1.5h'])
def test_invalid_task_cooldown(text):
    with pytest.raises(ValueError):parse_task_cooldown(text)


@pytest.mark.asyncio
async def test_initial_setup_cannot_be_claimed_by_unapproved_native_admin(db,guild,fakebot,thread):
    from cogs.setup import SetupCog
    await db.update_guild_config(str(GID),admin_user_id=None,is_configured=0)
    cog=SetupCog(fakebot)
    i=interaction(fakebot,guild,thread,user_id=ADMIN2)
    await cog.setup_start.callback(cog,i)
    assert 'primary' in i.followup.send.await_args.args[0]
    assert (await db.get_guild_config(str(GID)))['admin_user_id'] is None
    owner_i=interaction(fakebot,guild,thread,ident=2)
    await cog.setup_start.callback(cog,owner_i)
    view=owner_i.followup.send.await_args.kwargs['view']
    # A copied or forged old button cannot claim ownership for a different actor.
    forged=interaction(fakebot,guild,thread,user_id=ADMIN2,ident=3)
    await view.children[0].callback(forged)
    assert (await db.get_guild_config(str(GID)))['admin_user_id'] is None
    confirmed=interaction(fakebot,guild,thread,ident=4)
    await view.children[0].callback(confirmed)
    assert (await db.get_guild_config(str(GID)))['admin_user_id']==str(OWNER)


@pytest.mark.asyncio
async def test_moderator_setup_reset_is_pending_and_preserves_data_and_primary_access(db,guild,fakebot,thread):
    from cogs.setup import SetupCog
    await make_mod(db,guild)
    await db.add_mc(str(AUTHOR),str(GID),11,'regular','Preservation test',reward_key='preserve-reset')
    await db.update_guild_config(str(GID),super_admin_role_id=str(PRIMARY_ROLE),super_admin_user_ids=json.dumps([str(ADMIN2)]))
    # The operational moderator, not the newly granted named primary admin, requests reset.
    cog=SetupCog(fakebot)
    i=interaction(fakebot,guild,thread,user_id=AUTHOR)
    await cog.setup_reset.callback(cog,i)
    view=i.followup.send.await_args.kwargs['view']
    confirmation=interaction(fakebot,guild,thread,user_id=AUTHOR,ident=2)
    await view.children[0].callback(confirmation)
    assert (await db.get_guild_config(str(GID)))['is_configured']==1
    row=(await db.list_config_requests(str(GID),guild.roster[OWNER]))[0]
    result=await db.decide_config_request(str(GID),guild.roster[OWNER],row['id'],approve=True)
    assert result['state']=='approved'
    cfg=await db.get_guild_config(str(GID))
    assert cfg['is_configured']==0 and cfg['admin_user_id']==str(OWNER)
    assert cfg['moderator_role_id']==str(MOD_ROLE) and cfg['super_admin_role_id']==str(PRIMARY_ROLE)
    assert json.loads(cfg['super_admin_user_ids'])==[str(ADMIN2)]
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_regular']==11
    assert is_primary(guild.roster[OWNER],cfg) and is_primary(guild.roster[ADMIN2],cfg)


@pytest.mark.asyncio
async def test_direct_decision_modal_rejects_non_primary(db,guild,fakebot,thread):
    row=await propose(db,guild)
    modal=DecisionModal(row['id'],True);modal.note._value='Please approve'
    await modal.on_submit(interaction(fakebot,guild,thread,user_id=ADMIN2))
    assert (await db.get_config_request(str(GID),guild.roster[OWNER],row['id']))['state']=='pending'
    assert (await db.get_guild_config(str(GID)))['min_reviews']==5


@pytest.mark.asyncio
async def test_unrelated_setting_change_does_not_invalidate_approval(db,guild):
    row=await propose(db,guild)
    await db.submit_config_change(str(GID),guild.roster[OWNER],'guild',{'mc_score_low':2},source_id='unrelated')
    assert (await db.decide_config_request(str(GID),guild.roster[OWNER],row['id'],approve=True))['state']=='approved'
    cfg=await db.get_guild_config(str(GID))
    assert cfg['min_reviews']==3 and cfg['mc_score_low']==2


@pytest.mark.asyncio
async def test_governance_busy_queue_does_not_block_mc_or_health(db,guild,fakebot,thread):
    from health_runtime import HealthRuntime
    await make_mod(db,guild)
    await asyncio.gather(*(propose(db,guild,source=f'queue-{n}') for n in range(10)))
    health=HealthRuntime(fakebot);health.db_ok=True;fakebot.cogs={}
    assert health.snapshot()['ready']
    result=await manual_award(interaction(fakebot,guild,thread,user_id=AUTHOR),[ADMIN2],2,'regular','Independent operation')
    assert result['created'] and (await db.get_user(str(ADMIN2),str(GID)))['mc_regular']==2
    assert health.snapshot()['ready']


@pytest.mark.asyncio
async def test_task_cooldown_cannot_change_foreign_guild_or_closed_task(db,guild,fakebot,thread):
    await make_mod(db,guild)
    foreign=await db.create_assignment_mgr(str(GID+1),'Foreign','Body',str(THREAD+1),3600,0,str(OWNER))
    await change_task_cooldown(interaction(fakebot,guild,thread,user_id=AUTHOR),foreign,'0')
    assert (await db.get_assignment_by_thread(str(THREAD+1)))['cooldown_seconds']==3600
    local=await db.create_assignment_mgr(str(GID),'Closed','Body',str(THREAD),3600,0,str(OWNER))
    await db.close_assignment_mgr(local)
    await change_task_cooldown(interaction(fakebot,guild,thread,user_id=AUTHOR,ident=2),local,'0')
    assert (await db.get_assignment_by_thread(str(THREAD)))['cooldown_seconds']==3600


@pytest.mark.asyncio
async def test_mod_has_setup_view_and_report_download_access(db,guild,fakebot,thread,tmp_path,monkeypatch):
    from cogs.setup import SetupCog
    from cogs.review_support import ReviewSupportCog
    await make_mod(db,guild)
    i=interaction(fakebot,guild,thread,user_id=AUTHOR)
    setup=SetupCog(fakebot)
    await setup.setup_view.callback(setup,i)
    assert i.followup.send.await_args.kwargs['embed'].title=='⚙️ Full Configuration'
    base=tmp_path/'reports';directory=base/'review-support';directory.mkdir(parents=True)
    monkeypatch.setenv('REPORT_DIR',str(base))
    now=datetime.now(timezone.utc)
    job=await db.queue_support_report(str(GID),now-timedelta(days=14),now,str(AUTHOR))
    file=directory/(job['id']+'.xlsx');file.write_bytes(b'Synthetic attachment fixture')
    file.with_suffix('.csv').write_bytes(b'Name,MC\nFixture,0\n')
    await db.finish_support_report(job['id'],payload={},path=file)
    support=ReviewSupportCog(fakebot)
    try:
        dl=interaction(fakebot,guild,thread,user_id=AUTHOR,ident=2)
        await support.review_analytics_status.callback(support,dl,job['id'])
        sent=dl.response.send_message.await_args or dl.followup.send.await_args
        assert len(sent.kwargs['files'])==2
    finally:await support.cog_unload()


@pytest.mark.parametrize('missing_key',['admin_role_id','assignment_channel_id'])
@pytest.mark.asyncio
async def test_missing_role_or_channel_cannot_be_proposed(db,guild,fakebot,thread,missing_key):
    i=interaction(fakebot,guild,thread,user_id=ADMIN2)
    assert not await request_config_change(i,**{missing_key:str(MOD_ROLE)})
    assert not await db.list_config_requests(str(GID),guild.roster[OWNER])


@pytest.mark.asyncio
async def test_deleted_role_cannot_be_approved_from_stale_modal(db,guild,fakebot,thread):
    row=await propose(db,guild,changes={'pro_role_id':str(MOD_ROLE)})
    modal=DecisionModal(row['id'],True);modal.note._value=''
    await modal.on_submit(interaction(fakebot,guild,thread))
    assert (await db.get_config_request(str(GID),guild.roster[OWNER],row['id']))['state']=='pending'
    assert (await db.get_guild_config(str(GID)))['pro_role_id'] is None


@pytest.mark.parametrize('scope',['guild','support'])
@pytest.mark.asyncio
async def test_config_readers_cannot_use_uncommitted_approval_values(db,guild,monkeypatch,scope):
    if scope=='guild':
        changes={'reaction_mc_1':5}
        reader=lambda:db.get_guild_config(str(GID))
        key,old='reaction_mc_1',1
    else:
        base=dict(enabled=True,reviewer_role_id=str(MOD_ROLE),moderator_role_id=str(PRIMARY_ROLE),
                  member_role_id=None,weekly_cap=10,sample_size=3)
        await db.configure_support(str(GID),**base)
        changes={**base,'weekly_cap':20}
        reader=lambda:db.support_settings(str(GID))
        key,old='weekly_cap',10
    row=await db.submit_config_change(str(GID),guild.roster[ADMIN2],scope,changes,source_id='atomic-reader')
    written,release=asyncio.Event(),asyncio.Event()
    async def fail_after_write(*args,**kwargs):
        written.set()
        await release.wait()
        raise RuntimeError('Injected failure after config UPDATE, before COMMIT')
    monkeypatch.setattr(db,'_governance_audit',fail_after_write)
    approval=asyncio.create_task(db.decide_config_request(str(GID),guild.roster[OWNER],row['id'],approve=True))
    await asyncio.wait_for(written.wait(),2)
    read=asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    assert not read.done()  # an MC/support worker cannot consume tentative values
    release.set()
    with pytest.raises(RuntimeError):await approval
    assert (await read)[key]==old
    assert not (await db._get_conn()).in_transaction


@pytest.mark.asyncio
async def test_original_primary_anchor_cannot_be_overwritten_by_access_request(db,guild):
    with pytest.raises(PermissionError):
        await db.submit_config_change(str(GID),guild.roster[OWNER],'guild',{'admin_user_id':str(ADMIN2)},
                                      source_id='overwrite-anchor',access=True)
    assert (await db.get_guild_config(str(GID)))['admin_user_id']==str(OWNER)
