import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.review_support import ReviewSupportCog, RatingModal, TeamInboxView, ModeratorPanelView
from cogs.panel import ReviewsView
from database import Database
from health_runtime import HealthRuntime
from review_support_db import week_window
from runtime_utils import utc_iso
from tests.conftest import GID, AUTHOR, OWNER, interaction, member

NOW = datetime(2026, 10, 10, 9, tzinfo=timezone.utc)
REVIEW_ROLE, MOD_ROLE, MEMBER_ROLE = '31', '32', '33'
MODS = [str(100000000000000100 + n) for n in range(5)]
PEOPLE = [str(100000000000001000 + n) for n in range(150)]
FEEDBACK = 'Your feedback was specific and useful. Please add one concrete example next time.'


async def seed_support(db, count=50, *, sample_count=3, now=NOW, members=False):
    await db.configure_support(str(GID), enabled=True, reviewer_role_id=REVIEW_ROLE, moderator_role_id=MOD_ROLE,
                               member_role_id=MEMBER_ROLE if members else None, now=now)
    roster = [{'id': uid, 'kind': kind, 'username': 'person-' + uid[-4:], 'display_name': 'Display ' + uid[-4:],
               'joined_at': utc_iso(now - timedelta(days=60))}
              for kind, ids in [('reviewer', PEOPLE[:count]), ('moderator', MODS), ('member', [str(AUTHOR)] if members else [])] for uid in ids]
    await db.save_support_roster(str(GID), roster, now=now)
    for mod in MODS:
        await db.support_volunteer(str(GID), mod, available=True, member_capacity=2 if members else 0)
    await db.update_guild_config(str(GID), max_reviews_per_week=3, max_submits_per_week=3, min_reviews=3)
    conn = await db._get_conn()
    when = week_window(now)[0] - timedelta(days=4)
    for n in range(sample_count):
        pid = 'sample-post-' + str(n)
        await conn.execute('''INSERT INTO posts(post_id,guild_id,author_id,tweet_link,week_id,submitted_at,required_reviews)
            VALUES (?,?,?,?,?,?,?)''', (pid, str(GID), str(AUTHOR), 'https://x.com/test/status/' + str(1000+n), 'fixture-week', utc_iso(when), 3))
        for uid in PEOPLE[:count]:
            await conn.execute('''INSERT INTO reviews(review_id,post_id,reviewer_id,score,twitter_comment,summary,week_id,submitted_at)
                VALUES (?,?,?,?,?,?,?,?)''', (f'rev-{n}-{uid}', pid, uid, 8, f'https://x.com/test/status/{2000+n}', FEEDBACK, 'fixture-week', utc_iso(when)))
            await conn.execute('''INSERT INTO assignments(assignment_id,post_id,reviewer_id,week_id,assigned_at,due_date,status,completed_at)
                VALUES (?,?,?,?,?,?,'completed',?)''', (f'asn-{n}-{uid}', pid, uid, 'fixture-week', utc_iso(when-timedelta(days=1)), utc_iso(when+timedelta(days=2)), utc_iso(when)))
    await conn.commit()
    return await db.start_support_cycle(str(GID), now=now)


async def first_task(db, now=NOW):
    return next(w for w in await db.support_work(str(GID), now=now) if w['state'] == 'pending')


async def evaluate(db, item, score=8, checked=None, *, now=NOW):
    ids = [s['id'] for s in json.loads(item['samples_json'])]
    return await db.rate_support(str(GID), item['id'], item['moderator_id'], score, FEEDBACK,
                                 ids if checked is None else checked, now=now)


def test_week_starts_saturday_tehran_across_year():
    start, end = week_window(datetime(2027, 1, 1, 23, tzinfo=timezone.utc))
    assert start == datetime(2027, 1, 1, 20, 30, tzinfo=timezone.utc)
    assert end - start == timedelta(days=7)


@pytest.mark.asyncio
async def test_fifty_reviewers_five_mods_ten_each_and_restart_stability(db):
    cycle = await seed_support(db)
    work = await db.support_work(str(GID), now=NOW)
    assert len(work) == 50
    assert Counter(w['moderator_id'] for w in work) == {m: 10 for m in MODS}
    assert len({w['user_id'] for w in work}) == 50
    assert all(len(json.loads(w['samples_json'])) == 3 and w['user_id'] != w['moderator_id'] for w in work)
    assert await db.start_support_cycle(str(GID), now=NOW) == cycle
    assert await db.support_work(str(GID), now=NOW) == work
    assert await db.support_work('other-guild', now=NOW) == []


@pytest.mark.asyncio
async def test_skip_redistributes_with_room_but_never_overloads(db):
    await seed_support(db)
    item = await first_task(db)
    await db.skip_support(str(GID), item['id'], item['moderator_id'], now=NOW)
    queued = await db.support_assignment(str(GID), item['id'])
    assert queued['state'] == 'queued' and queued['moderator_id'] is None
    spare = next(m for m in MODS if m != item['moderator_id'])
    await db.configure_support(str(GID), enabled=True, reviewer_role_id=REVIEW_ROLE, moderator_role_id=MOD_ROLE, weekly_cap=11, now=NOW)
    await db.support_volunteer(str(GID), spare, available=True, reviewer_capacity=11)
    await db.start_support_cycle(str(GID), now=NOW)
    assigned = await db.support_assignment(str(GID), item['id'])
    assert assigned['moderator_id'] == spare and assigned['samples_json'] == item['samples_json']


@pytest.mark.asyncio
async def test_rotation_and_expired_work_does_not_become_zero_score(db):
    await seed_support(db, count=10)
    original = await db.support_work(str(GID), now=NOW)
    for task in original:
        await evaluate(db, task)
    await db.start_support_cycle(str(GID), now=NOW+timedelta(days=7))
    rotated = await db.support_work(str(GID), now=NOW+timedelta(days=7))
    old = {w['user_id']: w['moderator_id'] for w in original}
    assert all(w['moderator_id'] != old[w['user_id']] for w in rotated)
    assert all(json.loads(w['samples_json']) == [] for w in rotated)
    conn = await db._get_conn()
    assert (await (await conn.execute('SELECT COUNT(*) FROM support_evaluations')).fetchone())[0] == 10


@pytest.mark.asyncio
async def test_large_roster_is_processed_in_bounded_batches(db):
    await seed_support(db, count=150, sample_count=0)
    first = await db.support_work(str(GID), now=NOW)
    assert len(first) == 100 and sum(w['state']=='pending' for w in first) == 50
    await db.start_support_cycle(str(GID), now=NOW)
    second = await db.support_work(str(GID), now=NOW)
    assert len(second) == 150 and sum(w['state']=='pending' for w in second) == 50
    assert sum(w['state']=='queued' for w in second) == 100


@pytest.mark.asyncio
async def test_pause_and_departed_role_remove_pending_tasks(db):
    await seed_support(db, count=10)
    item = await first_task(db)
    await db.support_volunteer(str(GID), item['moderator_id'], available=False, reviewer_capacity=0)
    await db.start_support_cycle(str(GID), now=NOW)
    revised = await db.support_assignment(str(GID), item['id'])
    assert revised['moderator_id'] != item['moderator_id']
    conn = await db._get_conn()
    await conn.execute('UPDATE support_roster SET present=0 WHERE user_id=?', (item['user_id'],))
    await conn.commit()
    await db.start_support_cycle(str(GID), now=NOW)
    assert (await db.support_assignment(str(GID), item['id']))['state'] == 'withdrawn'


@pytest.mark.asyncio
async def test_member_scope_is_separate_opt_in_capacity(db):
    await seed_support(db, members=True)
    work = await db.support_work(str(GID), now=NOW)
    members = [w for w in work if w['kind'] == 'member']
    assert len(members) == 1 and members[0]['state'] == 'pending'
    assert len(json.loads(members[0]['samples_json'])) == 3
    ident = await evaluate(db, members[0], score=10)
    assert (await db.team_inbox(str(GID), str(AUTHOR)))[0]['evaluation_id'] == ident


@pytest.mark.asyncio
@pytest.mark.parametrize('score', [0, 11, 1.2, True, float('nan'), '8'])
async def test_rating_range_is_not_bypassed(db, score):
    await seed_support(db, count=1)
    with pytest.raises(ValueError, match='integer'):
        await evaluate(db, await first_task(db), score)


@pytest.mark.asyncio
async def test_missing_evidence_and_limited_evidence_stay_distinct(db):
    await seed_support(db, count=1, sample_count=1)
    item = await first_task(db)
    for score, ids in [(None, []), (8, []), (8, ['invented'])]:
        with pytest.raises(ValueError, match='saved sample'):
            await evaluate(db, item, score, ids)
    await evaluate(db, item)
    inbox = await db.team_inbox(str(GID), item['user_id'])
    assert inbox[0]['limited_evidence'] == 1 and inbox[0]['score'] == 8


@pytest.mark.asyncio
async def test_no_samples_can_be_friendly_check_in_but_not_scored(db):
    await seed_support(db, count=1, sample_count=0)
    item = await first_task(db)
    with pytest.raises(ValueError):
        await evaluate(db, item, score=1)
    await evaluate(db, item, score=None)
    assert (await db.team_inbox(str(GID), item['user_id']))[0]['score'] is None


@pytest.mark.asyncio
async def test_concurrent_score_is_atomic_and_never_changes_mc_or_rules(db):
    await seed_support(db, count=1)
    before = await db.get_guild_config(str(GID))
    item = await first_task(db)
    await db.get_or_create_user(item['user_id'], str(GID), 'Reviewer')
    await db.add_mc(item['user_id'], str(GID), 20, 'regular', 'Existing balance')
    results = await asyncio.gather(evaluate(db, item), evaluate(db, item), return_exceptions=True)
    assert sum(isinstance(r, str) for r in results) == 1
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert len(await db.team_inbox(str(GID), item['user_id'])) == 1
    assert (await db.get_user(item['user_id'], str(GID)))['mc_regular'] == 20
    assert await db.get_guild_config(str(GID)) == before


@pytest.mark.asyncio
async def test_wrong_mod_guild_self_and_deadline_are_denied(db):
    await seed_support(db, count=1)
    item = await first_task(db)
    for gid, mod, now in [('other', item['moderator_id'], NOW), (str(GID), 'wrong', NOW),
                          (str(GID), item['moderator_id'], week_window(NOW)[1])]:
        with pytest.raises(ValueError):
            await db.skip_support(gid, item['id'], mod, now=now)
    conn = await db._get_conn()
    await conn.execute('UPDATE support_assignments SET moderator_id=user_id WHERE id=?', (item['id'],))
    await conn.commit()
    item = await db.support_assignment(str(GID), item['id'])
    with pytest.raises(ValueError, match='Self-evaluation'):
        await evaluate(db, item)


@pytest.mark.asyncio
async def test_inbox_owner_checks_read_reply_and_appeal(db):
    await seed_support(db, count=1)
    item = await first_task(db)
    eid = await evaluate(db, item)
    assert await db.team_inbox('other', item['user_id']) == []
    assert await db.team_inbox(str(GID), 'stranger') == []
    await db.team_read(str(GID), 'stranger', [eid])
    assert (await db.team_inbox(str(GID), item['user_id']))[0]['read_at'] is None
    with pytest.raises(ValueError):
        await db.reply_team_message(str(GID), 'stranger', eid, 'hello', '1')
    with pytest.raises(ValueError):
        await db.request_second_look(str(GID), 'stranger', eid, 'Please check the context again.')
    await db.reply_team_message(str(GID), item['user_id'], eid, 'Thanks for this example.', 'one')
    await db.reply_team_message(str(GID), item['user_id'], eid, 'Duplicate click.', 'one')
    assert len(await db.team_inbox(str(GID), item['moderator_id'])) == 1
    for index in range(4):
        await db.reply_team_message(str(GID), item['user_id'], eid, 'A useful follow-up.', str(index))
    with pytest.raises(ValueError, match='Five replies'):
        await db.reply_team_message(str(GID), item['user_id'], eid, 'A sixth reply.', 'six')


@pytest.mark.asyncio
async def test_second_look_keeps_original_and_independent_admin_revision(db):
    await seed_support(db, count=1)
    item = await first_task(db)
    eid = await evaluate(db, item, score=6)
    request = await db.request_second_look(str(GID), item['user_id'], eid, 'Please include my concrete examples.')
    assert await db.request_second_look(str(GID), item['user_id'], eid, 'A repeated request cannot duplicate this.') == request
    with pytest.raises(ValueError, match='different admin'):
        await db.resolve_second_look(str(GID), request, item['moderator_id'], FEEDBACK, 8)
    await db.resolve_second_look(str(GID), request, str(OWNER), FEEDBACK, 8)
    assert await db.second_looks(str(GID)) == []
    inbox = await db.team_inbox(str(GID), item['user_id'])
    assert len(inbox) == 2 and inbox[0]['score'] == 8 and inbox[0]['original_score'] == 6


@pytest.mark.asyncio
async def test_reports_two_week_cadence_queue_budget_and_restart(db):
    await seed_support(db, count=1)
    assert await db.queue_due_support_report(str(GID), now=NOW+timedelta(days=13)) is None
    job = await db.queue_due_support_report(str(GID), now=NOW+timedelta(days=43))
    assert job['ends_at'] == utc_iso(NOW+timedelta(days=42))
    assert job['starts_at'] == utc_iso(NOW+timedelta(days=28))
    assert await db.queue_due_support_report(str(GID), now=NOW+timedelta(days=43)) is None
    assert (await db.queue_support_report(str(GID), job['starts_at'], job['ends_at'], 'me'))['id'] == job['id']
    await db.queue_support_report(str(GID), NOW-timedelta(days=7), NOW, 'me')
    with pytest.raises(ValueError, match='Two reports'):
        await db.queue_support_report(str(GID), NOW-timedelta(days=8), NOW, 'me')
    claimed = await db.next_support_report()
    await db.init_support()
    assert (await db.get_support_report(str(GID), claimed['id']))['state'] == 'queued'
    claimed = await db.next_support_report()
    await db.finish_support_report(claimed['id'], error='Injected failure')
    assert (await db.get_support_report(str(GID), claimed['id']))['state'] == 'failed'


@pytest.mark.asyncio
async def test_discord_role_revocation_and_private_views(fakebot, guild, thread, db):
    await seed_support(db, count=1)
    support = ReviewSupportCog(fakebot)
    fakebot.get_cog.return_value = support
    role = SimpleNamespace(id=int(MOD_ROLE))
    moderator = member(guild, OWNER, roles=[role])
    guild.roster[OWNER] = moderator
    i = interaction(fakebot, guild, thread)
    assert await support.require_moderator(i)
    moderator.roles = []
    assert not await support.require_moderator(i)
    view = ModeratorPanelView(OWNER)
    assert not await view.interaction_check(i)
    inbox = TeamInboxView('different-owner', [])
    assert not await inbox.interaction_check(i)
    modal = RatingModal(await first_task(db), OWNER)
    assert not await modal.interaction_check(i)


@pytest.mark.asyncio
@pytest.mark.parametrize('opt_out', [True, False])
async def test_closed_dms_and_opt_out_never_lose_feedback(fakebot, guild, db, opt_out):
    await seed_support(db, count=1, now=datetime.now(timezone.utc))
    item = await first_task(db, datetime.now(timezone.utc))
    eid = await evaluate(db, item, now=datetime.now(timezone.utc))
    if opt_out:
        await db.team_dm_preference(str(GID), item['user_id'], False)
    recipient = SimpleNamespace(bot=False, send=AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason='DMs closed'), 'Blocked')))
    guild.fetch_member = AsyncMock(return_value=recipient)
    support = ReviewSupportCog(fakebot)
    await support.support_message_worker()
    messages = await db.team_inbox(str(GID), item['user_id'])
    assert messages[0]['id'] == eid and messages[0]['dm_state'] == 'inbox_only'
    if opt_out:
        guild.fetch_member.assert_not_awaited()
    else:
        recipient.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_incomplete_discord_roster_is_never_persisted(fakebot, guild, db):
    await seed_support(db, count=1)
    before = (await db.support_settings(str(GID)))['roster_at']
    guild.get_role.side_effect = None
    guild.get_role.return_value = SimpleNamespace(id=31)
    async def broken(limit=None):
        yield SimpleNamespace(bot=False, id=int(PEOPLE[0]), name='new-name', display_name='new', joined_at=None, roles=[SimpleNamespace(id=31)])
        raise discord.HTTPException(SimpleNamespace(status=500, reason='temporary'), 'failure')
    guild.fetch_members = broken
    with pytest.raises(discord.HTTPException):
        await ReviewSupportCog(fakebot).refresh_roster(guild)
    assert (await db.support_settings(str(GID)))['roster_at'] == before
    conn = await db._get_conn()
    assert (await (await conn.execute('SELECT username FROM support_roster WHERE user_id=?', (PEOPLE[0],))).fetchone())[0] != 'new-name'


@pytest.mark.asyncio
async def test_role_change_invalidates_roster_and_prevents_stale_actions(db):
    await seed_support(db,count=1)
    item=await first_task(db)
    await db.configure_support(str(GID),enabled=True,reviewer_role_id='different',moderator_role_id=MOD_ROLE,now=NOW)
    assert (await db.support_settings(str(GID)))['roster_at'] is None
    assert await db.start_support_cycle(str(GID),now=NOW) is None
    with pytest.raises(ValueError):
        await evaluate(db,item)


@pytest.mark.asyncio
async def test_report_claim_is_serial_across_separate_connections(db):
    await seed_support(db,count=1)
    job=await db.queue_support_report(str(GID),NOW-timedelta(days=14),NOW,str(OWNER))
    other=Database(db.db_path)
    await other._get_conn()  # Do not reinitialize an active process's in-flight jobs.
    try:
        results=await asyncio.gather(db.next_support_report(),other.next_support_report())
        assert sum(r is not None for r in results)==1
        assert next(r for r in results if r)['id']==job['id']
    finally:
        await other.close()


@pytest.mark.asyncio
async def test_failed_report_retry_is_bounded_and_guild_owned(db):
    await seed_support(db,count=1)
    job=await db.queue_support_report(str(GID),NOW-timedelta(days=14),NOW,str(OWNER))
    for attempt in range(3):
        claimed=await db.next_support_report()
        await db.finish_support_report(claimed['id'],error='Transient fixture fault')
        with pytest.raises(ValueError):
            await db.retry_support_report('other',job['id'])
        if attempt<2:
            await db.retry_support_report(str(GID),job['id'])
    with pytest.raises(ValueError,match='fewer than three'):
        await db.retry_support_report(str(GID),job['id'])


@pytest.mark.asyncio
async def test_worker_builds_private_xlsx_csv_without_financial_write(fakebot,guild,db,tmp_path,monkeypatch):
    now=datetime.now(timezone.utc)
    await seed_support(db,count=5,now=now,members=True)
    job=await db.queue_support_report(str(GID),now-timedelta(days=14),now,str(OWNER))
    monkeypatch.setenv('REPORT_DIR',str(tmp_path/'reports'))
    before=await db.get_guild_config(str(GID))
    support=ReviewSupportCog(fakebot)
    await support.support_worker()
    saved=await db.get_support_report(str(GID),job['id'])
    assert saved['state']=='completed' and saved['attempts']==1
    from pathlib import Path
    assert Path(saved['output_path']).is_file() and Path(saved['output_path']).with_suffix('.csv').is_file()
    assert len(json.loads(saved['payload_json'])['reviewers'])==5
    assert await db.get_guild_config(str(GID))==before


@pytest.mark.asyncio
async def test_health_detects_and_bounds_support_loop_repairs(fakebot,db):
    support=ReviewSupportCog(fakebot)
    fakebot.cogs={'ReviewSupport':support}
    health=HealthRuntime(fakebot);health.db_ok=True
    assert len(health.snapshot()['loops'])==3 and not health.snapshot()['alive']
    try:
        repaired=await health.repair_loops()
        assert len(repaired)==3
        assert health.snapshot()['alive']
        for loop in (support.support_scheduler,support.support_worker,support.support_message_worker):
            loop.cancel()
        await asyncio.gather(*(loop.get_task() for loop in (support.support_scheduler,support.support_worker,support.support_message_worker)),return_exceptions=True)
        import time
        health._repairs={key:[time.monotonic()]*3 for key in repaired}
        assert await health.repair_loops()==[]
    finally:
        await support.cog_unload()


@pytest.mark.asyncio
async def test_review_panel_opens_modal_as_initial_response(fakebot,guild,thread,db):
    role=SimpleNamespace(id=31)
    guild.get_role.side_effect=None;guild.get_role.return_value=role
    guild.roster[OWNER].roles=[role]
    config={'pro_role_id':'31','require_twitter_id':0}
    view=ReviewsView(db,config)
    i=interaction(fakebot,guild,thread)
    await view.submit_review.callback(i)
    i.response.send_modal.assert_awaited_once()
    i.response.defer.assert_not_awaited()
