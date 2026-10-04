import asyncio
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import AsyncMock,MagicMock
import pytest
from aiohttp.test_utils import TestClient,TestServer
from tests.conftest import GID,OWNER,AUTHOR,THREAD
from database import Database,DuplicateSubmissionError
from config import parse_x_post_url,Config
from health_runtime import HealthRuntime
from recovery_daemon import Recovery,RECOVERY_TASKS


@pytest.mark.asyncio
async def test_durable_reaction_inbox_restart(db):
    await db.enqueue_reaction(str(GID),str(THREAD),'1',str(OWNER),'✅',1)
    path=db.db_path;await db.close()
    reopened=Database(path);await reopened.init()
    events=await reopened.pending_reactions()
    assert len(events)==1
    await reopened.enqueue_reaction(str(GID),str(THREAD),'1',str(OWNER),'✅',1)
    assert len(await reopened.pending_reactions())==1
    await reopened.close()


@pytest.mark.asyncio
async def test_notifications_retry_does_not_reaward(db):
    await db.award_batch_atomic(str(GID),str(OWNER),[{'id':str(AUTHOR),'name':'author'}],2,'regular','Reason','op',notice_channel=str(THREAD))
    notice=(await db.pending_notices())[0]
    for attempt in range(8):
        notice['attempts']=attempt
        await db.notice_result(notice,error='Forbidden')
    conn=await db._get_conn()
    async with conn.execute('SELECT state,attempts FROM notification_outbox') as cur:
        row=await cur.fetchone();assert row['state']=='failed' and row['attempts']==8
    assert await db.retry_failed_notices(str(GID))==1
    assert len(await db.pending_notices())==1
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_regular']==2


@pytest.mark.asyncio
async def test_real_health_not_constant_ok(db,fakebot,tmp_path,monkeypatch):
    monkeypatch.setenv('RUNTIME_DIR',str(tmp_path/'runtime'))
    fakebot.cogs={}
    health=HealthRuntime(fakebot);health.db_ok=True
    assert health.snapshot()['ready']
    health.db_ok=False;assert not health.snapshot()['alive']
    health.db_ok=True;fakebot.is_ready.return_value=False
    state=health.snapshot();assert state['alive'] and not state['ready']
    fakebot.is_ready.return_value=True
    health.lag_seconds=20;assert 'event loop stalled' in health.snapshot()['issues']
    health.lag_seconds=0
    await health.start(port=0)
    await asyncio.sleep(0.02)
    port=health.runner.addresses[0][1]
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(f'http://127.0.0.1:{port}/ready') as response:
            assert response.status==200 and (await response.json())['ready']
    await health.stop()


def recovery_config(runtime):
    runtime.mkdir(exist_ok=True)
    (runtime/'recovery.json').write_text(json.dumps({'owner_id':str(OWNER),'guild_id':str(GID),'channel_id':str(THREAD),'message_id':'100000000000000111','emoji':'🔄'}))


@pytest.mark.asyncio
async def test_recovery_owner_check_and_restart_budget(db,tmp_path,monkeypatch):
    runtime=tmp_path/'recovery';recovery_config(runtime)
    monkeypatch.delenv('RESCUE_OWNER_ID',raising=False)
    recovery=Recovery(runtime=runtime,db_path=db.db_path)
    recovery.systemctl=AsyncMock()
    ok,_=await recovery.recover(actor_id=str(AUTHOR));assert not ok
    recovery.systemctl.assert_not_awaited()
    ok,_=await recovery.recover(actor_id=str(OWNER));assert ok
    assert [c.args[0] for c in recovery.systemctl.await_args_list]==['reset-failed','restart']
    ok,reason=await recovery.recover(actor_id=str(OWNER));assert not ok and 'budget' in reason
    recovery.history=[time.time()-180,time.time()-300,time.time()-500]
    assert not recovery.budget_available()


@pytest.mark.asyncio
async def test_recovery_database_corruption_blocks_restart(tmp_path,monkeypatch):
    runtime=tmp_path/'recovery';recovery_config(runtime)
    broken=tmp_path/'broken.db';broken.write_bytes(b'not a SQLite database')
    monkeypatch.delenv('RESCUE_OWNER_ID',raising=False)
    recovery=Recovery(runtime=runtime,db_path=broken);recovery.systemctl=AsyncMock()
    try:
        ok,reason=await recovery.recover(actor_id=str(OWNER))
    except sqlite3.DatabaseError:
        pytest.fail('Corruption must return an actionable result, not raise.')
    assert not ok;recovery.systemctl.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_endpoint_auth_and_owner(db,tmp_path,monkeypatch):
    runtime=tmp_path/'recovery';recovery_config(runtime)
    monkeypatch.delenv('RESCUE_OWNER_ID',raising=False)
    recovery=Recovery(runtime=runtime,db_path=db.db_path);recovery.systemctl=AsyncMock()
    app=recovery.app()
    async with TestClient(TestServer(app)) as client:
        r=await client.post('/recover',json={'actor_id':str(OWNER)});assert r.status==401
        headers={'Authorization':'Bearer '+recovery.secret}
        r=await client.post('/recover',headers=headers,json={'actor_id':str(AUTHOR)});assert r.status==403
        r=await client.post('/recover',headers=headers,json={'actor_id':str(OWNER)});assert r.status==202
        r=await client.post('/recover',headers=headers,json={'actor_id':str(OWNER)});assert r.status==429
        for task in list(app[RECOVERY_TASKS]):
            task.cancel()
        await asyncio.gather(*list(app[RECOVERY_TASKS]),return_exceptions=True)
    recovery.systemctl.assert_not_awaited()


@pytest.mark.asyncio
async def test_independent_pulse_without_main_bot(db,tmp_path,monkeypatch):
    runtime=tmp_path/'recovery';recovery_config(runtime)
    recovery=Recovery(runtime=runtime,db_path=db.db_path);recovery.token='test-token'
    async def request(method,path,**kwargs):
        if method=='GET':
            return [{'id':str(OWNER)}]
        if method=='DELETE':
            return True
        return {'id':'1'}
    recovery.discord_request=AsyncMock(side_effect=request)
    recovery.recover=AsyncMock(return_value=(True,'Main bot restarted.'))
    await recovery.poll_pulse()
    recovery.recover.assert_awaited_once_with(actor_id=str(OWNER))
    assert [c.args[0] for c in recovery.discord_request.await_args_list]==['GET','DELETE','POST']


@pytest.mark.asyncio
async def test_fatal_configuration_does_not_restart_loop(db,tmp_path,monkeypatch):
    runtime=tmp_path/'recovery';recovery_config(runtime)
    (runtime/'heartbeat.json').write_text(json.dumps({'fatal':'Invalid token'}))
    recovery=Recovery(runtime=runtime,db_path=db.db_path);recovery.systemctl=AsyncMock()
    ok,reason=await recovery.recover(automatic=True)
    assert not ok and 'configuration' in reason
    recovery.systemctl.assert_not_awaited()


@pytest.mark.asyncio
async def test_consistent_backup_and_no_secrets(db,tmp_path):
    await db.add_mc(str(AUTHOR),str(GID),3,'regular','Test')
    path=await db.online_backup(tmp_path/'backup.db')
    conn=sqlite3.connect(path)
    assert conn.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    assert conn.execute('SELECT SUM(mc_regular) FROM users').fetchone()[0]==3
    conn.close()
    assert path.stat().st_mode&0o777==0o600


@pytest.mark.asyncio
async def test_review_atomic_and_duplicate_post_keys(db):
    post=await db.create_post(str(AUTHOR),str(GID),'https://x.com/i/status/123?s=20','2026-W40',x_status_id='123')
    with pytest.raises(DuplicateSubmissionError):
        await db.create_post(str(AUTHOR),str(GID),'https://twitter.com/name/status/123','2026-W41',x_status_id='123')
    aid=await db.create_assignment(post,str(OWNER),'2026-W40',datetime.now(timezone.utc)+timedelta(days=5))
    values=await asyncio.gather(*(db.submit_review_atomic(aid,str(OWNER),8,None,'Useful feedback with enough details.','2026-W40') for _ in range(10)))
    assert sum(v['status']=='created' for v in values)==1
    assert len(await db.get_reviews_by_post(post))==1


@pytest.mark.parametrize('score,reward',[(3.99,0),(4,1),(5.99,1),(6,3),(7.99,3),(8,5),(10,5)])
def test_score_boundaries_unchanged(score,reward):
    assert Config.calculate_mc_from_score(score,{})==reward


@pytest.mark.parametrize('url',['https://x.com/i/status/123?s=20','https://twitter.com/user/status/123?t=abc','https://www.x.com/user/status/123'])
def test_x_normalization_unchanged(url):
    assert parse_x_post_url(url)['status_id']=='123'


@pytest.mark.asyncio
async def test_all_extensions_commands_and_persistent_views(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'boot.db'))
    from bot import MeleeZoneBot
    async with MeleeZoneBot() as bot:
        await bot.setup_hook()
        assert len(bot.cogs)==18
        commands=bot.tree.get_commands()
        assert len(commands)==48
        assert {c.name for c in commands}>={'give_mc','role_report','health','doctor','recovery_setup','onboard','snapshot'}
        ids=[c.custom_id for v in bot.persistent_views for c in v.children]
        assert len(ids)==len(set(ids))


@pytest.mark.asyncio
async def test_legacy_migration_preserves_existing_data(tmp_path):
    original=os.getenv('LEGACY_TEST_DB')
    if not original:
        pytest.skip('Set LEGACY_TEST_DB to test a private backup.')
    from scripts.preflight import fingerprint,compare
    target=tmp_path/'legacy.db'
    source=sqlite3.connect(original);dest=sqlite3.connect(target);source.backup(dest);source.close();dest.close()
    before=fingerprint(target)
    db=Database(str(target));await db.init();await db.close();compare(before,target)
    db=Database(str(target));await db.init();await db.close();compare(before,target)
