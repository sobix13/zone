import asyncio
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import discord
import pytest
from tests.conftest import GID,OWNER,ADMIN2,AUTHOR,THREAD,PARENT,interaction
from runtime_utils import emoji_key,parse_member_ids,valid_amount,utc_iso,resolve_channel
from cogs.reactions import ReactionsCog,reaction_amount
from cogs.assignments import AssignmentsCog
from award_service import manual_award


async def scalar(db,sql):
    conn=await db._get_conn()
    async with conn.execute(sql) as cur:
        return (await cur.fetchone())[0]


@pytest.mark.parametrize('value',[-1,0,float('nan'),float('inf'),1001,'abc'])
def test_invalid_mc_amount(value):
    with pytest.raises((ValueError,TypeError)):
        valid_amount(value)


@pytest.mark.parametrize('text', ['<@100000000000000004> 100000000000000004','<@!100000000000000004>,100000000000000004'])
def test_member_mentions_deduplicate(text):
    assert parse_member_ids(text)==[str(AUTHOR)]


@pytest.mark.parametrize('text',['','everyone','<@100000000000000004','100000000000000004>','123'])
def test_member_mentions_reject_invalid(text):
    with pytest.raises(ValueError):
        parse_member_ids(text)


def test_emoji_identity():
    assert emoji_key('<:old:123456789012345678>')==emoji_key('<a:new:123456789012345678>')
    assert emoji_key('❤️')==emoji_key('❤')
    assert reaction_amount({'reaction_emoji_1':'❤','reaction_mc_1':2},'❤️')==2
    assert reaction_amount({'reaction_emoji_1':'✅','reaction_mc_1':0},'✅') is None


@pytest.mark.asyncio
async def test_same_admin_concurrent_reaction_once(db):
    kwargs=dict(guild_id=str(GID),channel_id=str(THREAD),message_id='901',author_id=str(AUTHOR),
        username='author',admin_id=str(OWNER),emoji='✅',amount=1,notice_channel=str(PARENT))
    results=await asyncio.gather(*(db.award_reaction_atomic(**kwargs) for _ in range(50)))
    assert sum(results)==1
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_regular']==1
    assert await scalar(db,'SELECT COUNT(*) FROM mc_transactions')==1
    assert await scalar(db,'SELECT COUNT(*) FROM reaction_credits')==1
    assert await scalar(db,'SELECT COUNT(*) FROM notification_outbox')==1


@pytest.mark.asyncio
async def test_multiple_admins_receive_independent_awards(db):
    async def award(admin):
        return await db.award_reaction_atomic(guild_id=str(GID),channel_id=str(THREAD),message_id='902',author_id=str(AUTHOR),
            username='author',admin_id=str(admin),emoji='✅',amount=2)
    results=await asyncio.gather(*(award(a) for a in [OWNER,ADMIN2]*20))
    assert sum(results)==2
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_regular']==4


@pytest.mark.asyncio
async def test_custom_emoji_rename_does_not_pay_twice(db):
    kwargs=dict(guild_id=str(GID),channel_id=str(THREAD),message_id='903',author_id=str(AUTHOR),username='author',admin_id=str(OWNER),amount=1)
    assert await db.award_reaction_atomic(**kwargs,emoji='<:old:123456789012345678>')
    assert not await db.award_reaction_atomic(**kwargs,emoji='<a:new:123456789012345678>')


@pytest.mark.asyncio
async def test_manual_batch_idempotent_and_atomic(db,monkeypatch):
    members=[{'id':str(AUTHOR),'name':'a'},{'id':str(ADMIN2),'name':'b'}]
    result=await db.award_batch_atomic(str(GID),str(OWNER),members,3,'regular','Good posts','op1')
    assert len(result['created'])==2
    retry=await db.award_batch_atomic(str(GID),str(OWNER),members,3,'regular','Good posts','op1')
    assert retry['created']==[] and retry['already_exists']==2
    assert await scalar(db,'SELECT COUNT(*) FROM mc_transactions')==2
    original=db._award_row
    async def fail_second(conn,**kwargs):
        result=await original(conn,**kwargs)
        if kwargs['user_id']==str(ADMIN2):
            raise RuntimeError('Injected failure')
        return result
    monkeypatch.setattr(db,'_award_row',fail_second)
    with pytest.raises(RuntimeError):
        await db.award_batch_atomic(str(GID),str(OWNER),members,10,'golden','Rollback test','op2')
    assert await scalar(db,'SELECT COUNT(*) FROM mc_transactions')==2
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_golden']==0
    assert not (await db._get_conn()).in_transaction


@pytest.mark.asyncio
async def test_manual_validation_has_no_partial_award(fakebot,guild,thread,db):
    i=interaction(fakebot,guild,thread)
    with pytest.raises(ValueError):
        await manual_award(i,[AUTHOR,100000000000000090],1,'regular','Test')
    assert await scalar(db,'SELECT COUNT(*) FROM mc_transactions')==0


@pytest.mark.asyncio
async def test_manual_non_admin_blocked(fakebot,guild,thread,db):
    i=interaction(fakebot,guild,thread,user_id=AUTHOR)
    assert await manual_award(i,[AUTHOR],1,'regular','Test') is None
    assert await scalar(db,'SELECT COUNT(*) FROM mc_transactions')==0


@pytest.mark.asyncio
async def test_add_mc_key_and_missing_user(db):
    assert await db.add_mc(str(AUTHOR),str(GID),5,'regular','Test',reward_key='reward:once')
    assert not await db.add_mc(str(AUTHOR),str(GID),5,'regular','Test',reward_key='reward:once')
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_regular']==5
    assert not (await db._get_conn()).in_transaction


@pytest.mark.asyncio
async def test_snapshot_retry_same_id(db):
    members=[{'id':str(AUTHOR),'name':'author'}]
    async def award():
        return await db.award_batch_atomic(str(GID),str(OWNER),members,2,'assignment','Snapshot','snapshot-op',snapshot_id='snapshot-op')
    results=await asyncio.gather(award(),award())
    assert sum(len(r['created']) for r in results)==1
    assert await scalar(db,'SELECT COUNT(*) FROM snapshot_awards')==1
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_assignment']==2


@pytest.mark.asyncio
async def test_reaction_in_thread_not_found_by_get_channel(fakebot,guild,thread,db):
    guild.get_channel.return_value=None
    message=SimpleNamespace(author=guild.get_member(AUTHOR))
    thread.fetch_message.return_value=message
    cog=ReactionsCog(fakebot)
    payload=SimpleNamespace(guild_id=GID,channel_id=THREAD,message_id=990,user_id=OWNER,emoji='✅',member=guild.get_member(OWNER))
    await cog.on_raw_reaction_add(payload)
    events=await db.pending_reactions()
    assert len(events)==1
    assert await cog.process_event(events[0])=='awarded'
    await db.reaction_result(events[0])
    assert (await db.get_user(str(AUTHOR),str(GID)))['mc_regular']==1


@pytest.mark.asyncio
async def test_reaction_cache_miss_rest_fallback(fakebot,guild,thread,db):
    guild.get_channel_or_thread.side_effect=lambda _:None
    fakebot.get_channel.side_effect=lambda _:None
    fakebot.fetch_channel.side_effect=None;fakebot.fetch_channel.return_value=thread
    channel=await resolve_channel(fakebot,guild,THREAD)
    assert channel is thread
    fakebot.fetch_channel.assert_awaited_once()


@pytest.mark.asyncio
async def test_reaction_admin_member_cache_miss(fakebot,guild,thread,db):
    admin=guild.roster[OWNER]
    guild.get_member.side_effect=lambda _:None
    guild.fetch_member.side_effect=None;guild.fetch_member.return_value=admin
    thread.fetch_message.return_value=SimpleNamespace(author=guild.roster[AUTHOR])
    cog=ReactionsCog(fakebot)
    event={'guild_id':str(GID),'channel_id':str(THREAD),'message_id':'991','admin_id':str(OWNER),'emoji':'✅','amount':1}
    assert await cog.process_event(event)=='awarded'


@pytest.mark.asyncio
async def test_non_admin_reaction_and_self_award(fakebot,guild,thread,db):
    cog=ReactionsCog(fakebot)
    payload=SimpleNamespace(guild_id=GID,channel_id=THREAD,message_id=992,user_id=AUTHOR,emoji='✅',member=guild.get_member(AUTHOR))
    await cog.on_raw_reaction_add(payload)
    assert await db.pending_reactions()==[]
    thread.fetch_message.return_value=SimpleNamespace(author=guild.get_member(OWNER))
    event={'guild_id':str(GID),'channel_id':str(THREAD),'message_id':'992','admin_id':str(OWNER),'emoji':'✅','amount':1}
    assert await cog.process_event(event)=='ineligible_author'
    assert await scalar(db,'SELECT COUNT(*) FROM mc_transactions')==0


@pytest.mark.asyncio
async def test_reaction_missing_history_has_no_payment(fakebot,guild,thread,db):
    thread.permissions_for.return_value=discord.Permissions(view_channel=True,read_message_history=False)
    event={'guild_id':str(GID),'channel_id':str(THREAD),'message_id':'993','admin_id':str(OWNER),'emoji':'✅','amount':1}
    with pytest.raises(RuntimeError,match='Read Message History'):
        await ReactionsCog(fakebot).process_event(event)
    assert await scalar(db,'SELECT COUNT(*) FROM mc_transactions')==0


@pytest.mark.asyncio
async def test_task_cooldown_race(db):
    aid=await db.create_assignment_mgr(str(GID),'Trade','Body',str(THREAD),86400,1,str(OWNER))
    assignment=await db.get_assignment_by_thread(str(THREAD))
    now=utc_iso()
    values=await asyncio.gather(*(db.accept_task_message(assignment,str(AUTHOR),now) for _ in range(30)))
    assert values.count(0)==1
    assert await scalar(db,'SELECT COUNT(*) FROM assignment_participants')==1
    await db.reset_task_cooldown(str(THREAD),str(AUTHOR))
    assert await db.accept_task_message(assignment,str(AUTHOR),now)==0


@pytest.mark.asyncio
async def test_task_admin_bypass_and_member_enforcement(fakebot,guild,thread,db):
    await db.create_assignment_mgr(str(GID),'Trade','Body',str(THREAD),86400,1,str(OWNER))
    cog=AssignmentsCog(fakebot)
    def message(uid,seconds=0):
        return SimpleNamespace(author=guild.get_member(uid),guild=guild,channel=thread,
            created_at=datetime.now(timezone.utc)+timedelta(seconds=seconds),delete=AsyncMock())
    first=message(OWNER);second=message(OWNER,1)
    await cog.on_message(first);await cog.on_message(second)
    first.delete.assert_not_awaited();second.delete.assert_not_awaited()
    assert await db.get_assignment_cooldown(str(THREAD),str(OWNER)) is None
    first=message(AUTHOR);second=message(AUTHOR,1)
    await cog.on_message(first);await cog.on_message(second)
    first.delete.assert_not_awaited();second.delete.assert_awaited_once()
