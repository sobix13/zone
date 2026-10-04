import asyncio
import sqlite3
import time
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
import pytest
from tests.conftest import GID,OWNER,ADMIN2,AUTHOR,THREAD,PARENT,interaction
from health_runtime import HealthRuntime
from cogs.health import HealthCog
from cogs.reactions import ReactionsCog
from cogs.control_center import UnifiedAdminView
from cogs.guide import GuideCog
from runtime_utils import utc_iso
from activity_service import process_report,discover_channels
from tests.test_reports import job,attach_history


@pytest.mark.asyncio
async def test_many_concurrent_posts_cannot_exceed_reviewer_capacity(db):
    await db.update_guild_config(str(GID),max_reviews_per_week=2)
    posts=[]
    for i in range(12):
        posts.append(await db.create_post(str(AUTHOR),str(GID),f'https://x.com/i/status/{900+i}','W',x_status_id=str(900+i)))
    due=datetime.now(timezone.utc)+timedelta(days=5)
    values=await asyncio.gather(*(db.create_assignment(p,str(OWNER),'W',due) for p in posts))
    assert sum(bool(v) for v in values)==2


@pytest.mark.asyncio
async def test_concurrent_assignment_cannot_overfill_post(db):
    post=await db.create_post(str(AUTHOR),str(GID),'https://x.com/i/status/800','W',x_status_id='800',required_reviews=3)
    due=datetime.now(timezone.utc)+timedelta(days=5)
    values=await asyncio.gather(*(db.create_assignment(post,str(200000000000000000+i),'W',due) for i in range(30)))
    assert sum(bool(v) for v in values)==3
    assert await db.create_assignment(post,str(AUTHOR),'W',due) is None


@pytest.mark.asyncio
async def test_rescue_handoff_atomic_and_primary_pending_blocks(db):
    post=await db.create_post(str(AUTHOR),str(GID),'https://x.com/i/status/700','W',x_status_id='700')
    due=datetime.now(timezone.utc)+timedelta(days=5)
    old=await db.create_assignment(post,str(OWNER),'W',due)
    await db.mark_assignment_warning(old,datetime.now(timezone.utc)-timedelta(hours=13))
    await db.get_or_create_user(str(ADMIN2),str(GID),'rescuer')
    await db.set_ready_for_more(str(ADMIN2),str(GID),1)
    results=await asyncio.gather(*(db.rescue_assignment_atomic(str(GID),old,str(ADMIN2),'W',due) for _ in range(10)))
    assert sum(bool(r) for r in results)==1
    items=await db.get_assignments_by_reviewer(str(ADMIN2),'W')
    assert len(items)==1 and items[0]['assignment_type']=='rescue' and items[0]['original_assignment_id']==old
    previous=await db.get_assignment_by_partial_id(old,str(OWNER));assert previous['status']=='reassigned'
    post2=await db.create_post(str(AUTHOR),str(GID),'https://x.com/i/status/701','W',x_status_id='701')
    own_primary=await db.create_assignment(post2,str(ADMIN2),'W',due)
    assert own_primary
    old2=await db.create_assignment(post2,str(OWNER),'W',due)
    await db.mark_assignment_warning(old2,datetime.now(timezone.utc)-timedelta(hours=13))
    assert await db.rescue_assignment_atomic(str(GID),old2,str(ADMIN2),'W',due) is None
    assert (await db.get_assignment_by_partial_id(old2,str(OWNER)))['status']=='warning'


@pytest.mark.asyncio
async def test_inbox_failure_retry_and_repair(db,fakebot,guild,thread):
    await db.enqueue_reaction(str(GID),str(THREAD),'555',str(OWNER),'✅',1)
    event=(await db.pending_reactions())[0]
    thread.fetch_message.side_effect=RuntimeError('Injected REST failure')
    reaction=ReactionsCog(fakebot)
    fakebot.get_cog.return_value=reaction
    health=HealthCog(fakebot)
    await health.reaction_worker.coro(health)
    assert (await db.get_user(str(AUTHOR),str(GID))) is None
    conn=await db._get_conn()
    async with conn.execute('SELECT attempts,last_error FROM reaction_event_inbox') as cursor:
        row=await cursor.fetchone();assert row['attempts']==1 and 'RuntimeError' in row['last_error']
    await db.retry_failed_reactions(str(GID))
    # Force the retry deadline in this fault injection test.
    async with db._lock:
        await conn.execute("UPDATE reaction_event_inbox SET next_at='2000-01-01T00:00:00+00:00'");await conn.commit()
    thread.fetch_message.side_effect=None
    thread.fetch_message.return_value=SimpleNamespace(author=guild.get_member(AUTHOR))
    await health.reaction_worker.coro(health)
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_regular']==1


@pytest.mark.asyncio
async def test_log_delivery_failure_leaves_award(db,fakebot,guild,thread):
    await db.award_batch_atomic(str(GID),str(OWNER),[{'id':str(AUTHOR),'name':'author'}],5,'regular','Test','op',notice_channel=str(THREAD))
    thread.send.side_effect=RuntimeError('Network error')
    cog=HealthCog(fakebot)
    await cog.notification_worker.coro(cog)
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_regular']==5
    conn=await db._get_conn()
    async with conn.execute('SELECT attempts,state FROM notification_outbox') as cursor:
        row=await cursor.fetchone();assert row['attempts']==1 and row['state']=='pending'


@pytest.mark.asyncio
async def test_admin_panel_rechecks_authorization(db,fakebot,guild,thread):
    view=UnifiedAdminView(db)
    assert await view.interaction_check(interaction(fakebot,guild,thread,OWNER))
    assert not await view.interaction_check(interaction(fakebot,guild,thread,AUTHOR))


@pytest.mark.asyncio
async def test_onboarding_once_and_progress_survives(db):
    assert await db.claim_onboarding_notice(str(GID),str(AUTHOR))
    assert not await db.claim_onboarding_notice(str(GID),str(AUTHOR))
    await db.set_onboarding(str(GID),str(AUTHOR),3)
    assert await db.get_onboarding(str(GID),str(AUTHOR))==3


@pytest.mark.asyncio
async def test_cancel_cannot_be_overwritten_by_worker(db,guild):
    value=await job(db,guild)
    await db.update_role_job(value['id'],state='cancelled')
    await db.update_role_job(value['id'],state='complete')
    assert (await db.get_role_job(value['id']))['state']=='cancelled'


@pytest.mark.asyncio
async def test_thread_discovery_failure_is_reported(db,fakebot,guild,thread):
    response=SimpleNamespace(status=403,reason='Forbidden')
    guild.active_threads.side_effect=discord.Forbidden(response,{'message':'Access denied','code':50013})
    value=await job(db,guild)
    await discover_channels(fakebot,guild,value)
    rows=await db.report_channels(value['id'])
    assert any(r['channel_id']=='discovery:active' and r['state']=='skipped' for r in rows)
    assert any(r['channel_id']==str(THREAD) for r in rows)


@pytest.mark.asyncio
async def test_discord_history_server_error_pauses_with_cursor(db,fakebot,guild,thread,tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_DIR',str(tmp_path/'reports'))
    response=SimpleNamespace(status=503,reason='Unavailable')
    async def history(**kwargs):
        raise discord.HTTPException(response,{'message':'Unavailable','code':0})
        yield
    thread.history=history
    value=await job(db,guild)
    await process_report(fakebot,value)
    saved=await db.get_role_job(value['id'])
    assert saved['state']=='paused' and '503' in saved['error']
    assert saved['scanned']==0

@pytest.mark.asyncio
async def test_post_rewards_are_atomic_with_finalization(db,monkeypatch):
    post=await db.create_post(str(AUTHOR),str(GID),'https://x.com/i/status/999','W',required_reviews=1)
    await db.create_review(post,str(OWNER),9,None,'Detailed review','W')
    original=db._award_row
    async def fail_golden(conn,**kwargs):
        if kwargs['mc_type']=='golden':
            raise RuntimeError('Injected interruption before commit')
        return await original(conn,**kwargs)
    monkeypatch.setattr(db,'_award_row',fail_golden)
    with pytest.raises(RuntimeError):
        await db.finalize_review_rewards(post)
    assert (await db.get_post(post))['status']=='pending'
    assert await db.get_user(str(AUTHOR),str(GID)) is None
    monkeypatch.setattr(db,'_award_row',original)
    outcomes=await asyncio.gather(*(db.finalize_review_rewards(post) for _ in range(20)))
    assert sum(bool(r) for r in outcomes)==1
    user=await db.get_user(str(AUTHOR),str(GID))
    assert user['mc_regular']==5 and user['mc_golden']==3
    assert (await db.get_post(post))['status']=='approved'


@pytest.mark.asyncio
async def test_quiz_completion_and_mc_exactly_once(db):
    questions=[{'question':'Test','options':['A','B'],'correct':0}]
    await db.create_quiz(str(GID),'test','Test quiz',questions,str(OWNER))
    quiz=(await db.get_active_quiz(str(GID)))['id']
    session=await db.create_quiz_session(str(GID),str(AUTHOR),quiz,questions,datetime.now(timezone.utc))
    values=await asyncio.gather(*(db.complete_quiz_atomic(guild_id=str(GID),user_id=str(AUTHOR),quiz_id=quiz,
        session_id=session,correct=1,total=1,score_pct=100,mc_earned=5,elapsed_seconds=10,
        completed_at=datetime.now(timezone.utc),title='Test quiz') for _ in range(20)))
    assert sum(values)==1
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_regular']==5
    assert (await db.get_quiz_result(str(GID),str(AUTHOR),quiz))['mc_earned']==5


@pytest.mark.asyncio
async def test_quiz_failure_does_not_save_unpaid_result(db,monkeypatch):
    await db.create_quiz(str(GID),'test','Quiz',[],str(OWNER))
    quiz=(await db.get_active_quiz(str(GID)))['id']
    session=await db.create_quiz_session(str(GID),str(AUTHOR),quiz,[],datetime.now(timezone.utc))
    monkeypatch.setattr(db,'_award_row',AsyncMock(side_effect=RuntimeError('Injected payment failure')))
    with pytest.raises(RuntimeError):
        await db.complete_quiz_atomic(guild_id=str(GID),user_id=str(AUTHOR),quiz_id=quiz,session_id=session,
            correct=1,total=1,score_pct=100,mc_earned=5,elapsed_seconds=10,completed_at=datetime.now(timezone.utc),title='Quiz')
    assert await db.get_quiz_result(str(GID),str(AUTHOR),quiz) is None
    conn=await db._get_conn()
    async with conn.execute('SELECT completed FROM quiz_sessions WHERE id=?',(session,)) as cur:
        assert (await cur.fetchone())[0]==0


@pytest.mark.asyncio
async def test_configuration_rejects_invalid_reward_and_preserves_old_values(db):
    for bad in [float('nan'),float('inf'),-1,1001]:
        with pytest.raises(ValueError):
            await db.update_guild_config(str(GID),reaction_mc_1=bad)
    assert (await db.get_guild_config(str(GID)))['reaction_mc_1']==1
    await db.update_guild_config(str(GID),review_window_days=9)
    assert (await db.get_guild_config(str(GID)))['total_review_days']==9


@pytest.mark.asyncio
async def test_background_repair_has_a_budget(db,fakebot):
    from discord.ext import tasks
    from health_runtime import HealthRuntime
    class Worker:
        qualified_name='Worker'
        @tasks.loop(seconds=100)
        async def reaction_worker(self):
            await asyncio.sleep(0)
    worker=Worker();fakebot.cogs={'Worker':worker}
    health=HealthRuntime(fakebot);health.db_ok=True
    assert not health.snapshot()['ready']
    for _ in range(3):
        assert await health.repair_loops()==['Worker.reaction_worker']
        worker.reaction_worker.cancel()
        await asyncio.gather(worker.reaction_worker.get_task(),return_exceptions=True)
    assert await health.repair_loops()==[]
    assert not health.snapshot()['ready']
    health.command_sync_errors=['test-guild']
    assert any('registration' in issue for issue in health.snapshot()['issues'])

@pytest.mark.asyncio
async def test_balance_reader_and_outbox_wait_for_commit(db):
    conn=await db._get_conn()
    async with db._lock:
        await conn.execute('BEGIN IMMEDIATE')
        await db._award_row(conn,user_id=str(AUTHOR),guild_id=str(GID),username='Author',amount=5,mc_type='regular',reason='Uncommitted')
        await db._enqueue_notice(conn,str(GID),str(THREAD),'Uncommitted notice','uncommitted')
        balance=asyncio.create_task(db.get_user(str(AUTHOR),str(GID)))
        notices=asyncio.create_task(db.pending_notices())
        await asyncio.sleep(0.01)
        assert not balance.done() and not notices.done()
        await conn.rollback()
    assert await balance is None
    assert await notices==[]

@pytest.mark.asyncio
async def test_delete_arriving_before_index_does_not_retain_text(db):
    from runtime_utils import utc_iso
    await db.mark_activity_deleted(['future-message'])
    row=('future-message',str(GID),str(AUTHOR),str(THREAD),None,utc_iso(),'Sensitive deleted text')
    await db.store_activity_messages([row])
    await db.store_activity_messages([row])
    activity=await db.activity_for_member(str(GID),str(AUTHOR),None,utc_iso())
    assert activity['known_messages']==1 and activity['window_messages']==0
    assert activity['recent_messages']==[]
    conn=await db._get_conn()
    async with conn.execute('SELECT excerpt FROM activity_messages WHERE message_id=?',('future-message',)) as cur:
        assert (await cur.fetchone())[0]==''
