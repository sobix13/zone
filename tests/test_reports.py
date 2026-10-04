import asyncio
import json
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
import pytest
from tests.conftest import GID,OWNER,AUTHOR,THREAD,PARENT,member
from database import Database
from activity_service import message_row,role_roster,process_report,export_job
from runtime_utils import utc_iso
from xlsx_report import export_role_report,TAG


def attach_history(channel,guild,uid,days=range(1,151)):
    messages=[]
    for day in days:
        when=datetime.now(timezone.utc)-timedelta(days=day)
        mid=discord.utils.time_snowflake(when)
        messages.append(SimpleNamespace(id=mid,guild=guild,channel=channel,author=guild.roster[uid],
            created_at=when,content=f'Message from {day} days ago',attachments=[]))
    messages.sort(key=lambda m:m.id,reverse=True)
    def history(*,limit=100,before=None,after=None,oldest_first=False):
        async def generate():
            selected=[m for m in messages if (before is None or m.id<before.id) and (after is None or m.created_at>after)]
            for m in selected[:limit]:
                yield m
        return generate()
    channel.history=history
    return messages


async def job(db,guild,*,max_messages=100,cutoff=None):
    role=SimpleNamespace(id=100000000000000020,name='OG')
    roster=[{'id':str(AUTHOR),'username':'author','display_name':'Author','joined_at':utc_iso(datetime.now(timezone.utc)-timedelta(days=200)),'is_bot':False}]
    ident=await db.create_role_job(str(GID),role,str(OWNER),roster,cutoff,max_messages)
    return await db.get_role_job(ident)


@pytest.mark.asyncio
async def test_full_history_beyond_720_hours(fakebot,guild,thread,db,tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_DIR',str(tmp_path/'reports'))
    attach_history(thread,guild,AUTHOR,days=[60,90])
    value=await job(db,guild,max_messages=100)
    await process_report(fakebot,value)
    saved=await db.get_role_job(value['id'])
    assert saved['state']=='complete' and saved['scanned']==2
    result=await db.activity_for_member(str(GID),str(AUTHOR),None,saved['upper_at'])
    assert result['known_messages']==2 and result['window_messages']==2
    assert zipfile.is_zipfile(saved['output_path'])


@pytest.mark.asyncio
async def test_scan_budget_resume_cursor_and_dedup(fakebot,guild,thread,db,tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_DIR',str(tmp_path/'reports'))
    attach_history(thread,guild,AUTHOR)
    value=await job(db,guild,max_messages=100)
    await process_report(fakebot,value)
    paused=await db.get_role_job(value['id'])
    assert paused['state']=='paused' and paused['scanned']==100
    channels=await db.report_channels(value['id'])
    assert channels[0]['before_id'] is not None
    await db.update_role_job(value['id'],state='queued',max_messages=200)
    await process_report(fakebot,await db.get_role_job(value['id']))
    finished=await db.get_role_job(value['id'])
    assert finished['state']=='complete' and finished['scanned']==150
    activity=await db.activity_for_member(str(GID),str(AUTHOR),None,finished['upper_at'])
    assert activity['known_messages']==150 and len(activity['recent_messages'])==5
    # Re-import the same message: no increase in observed counts.
    messages=attach_history(thread,guild,AUTHOR,days=[1])
    row=message_row(messages[0])
    await db.store_activity_messages([row,row])
    current=await db.activity_for_member(str(GID),str(AUTHOR),None,finished['upper_at'])
    assert current['known_messages']==151


@pytest.mark.asyncio
async def test_recent_window_is_not_all_time(fakebot,guild,thread,db,tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_DIR',str(tmp_path/'reports'))
    attach_history(thread,guild,AUTHOR,days=[1,20,60])
    cutoff=utc_iso(datetime.now(timezone.utc)-timedelta(days=30))
    value=await job(db,guild,max_messages=100,cutoff=cutoff)
    await process_report(fakebot,value)
    activity=await db.activity_for_member(str(GID),str(AUTHOR),cutoff,value['upper_at'])
    assert activity['known_messages']==2 and activity['window_messages']==2


@pytest.mark.asyncio
async def test_missing_history_explicit_coverage(fakebot,guild,thread,db,tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_DIR',str(tmp_path/'reports'))
    thread.permissions_for.return_value=discord.Permissions(view_channel=True,read_message_history=False)
    value=await job(db,guild)
    await process_report(fakebot,value)
    coverage=await db.report_channels(value['id'])
    assert coverage[0]['state']=='skipped'
    assert 'Read Message History' in coverage[0]['detail']
    saved=await db.get_role_job(value['id'])
    with zipfile.ZipFile(saved['output_path']) as file:
        assert b'Partial history' in file.read('xl/worksheets/sheet1.xml')


@pytest.mark.asyncio
async def test_activity_reactions_and_deletions(db):
    past=utc_iso(datetime.now(timezone.utc)-timedelta(days=3))
    await db.store_activity_messages([('555',str(GID),str(AUTHOR),str(THREAD),str(PARENT),past,'Text')])
    await db.store_activity_event(str(GID),str(AUTHOR),'reaction',str(THREAD),'event1')
    await db.mark_activity_deleted(['555'])
    result=await db.activity_for_member(str(GID),str(AUTHOR),None,utc_iso())
    assert result['known_messages']==1 and result['retained_messages']==0
    assert result['recent_messages']==[] and result['last_activity_type']=='reaction'


@pytest.mark.asyncio
async def test_roster_uses_full_fetch_not_partial_cache(guild):
    role=SimpleNamespace(id=33)
    original=member(guild,AUTHOR,roles=[role]);original.joined_at=datetime.now(timezone.utc)
    extra=member(guild,100000000000000040,roles=[role]);extra.joined_at=None
    guild.members=[original]
    def fetch_members(limit=None):
        async def generate():
            yield original;yield extra
        return generate()
    guild.fetch_members=fetch_members
    roster=await role_roster(guild,role)
    assert {r['id'] for r in roster}=={str(AUTHOR),'100000000000000040'}


@pytest.mark.asyncio
async def test_report_running_resumes_after_process_restart(db,guild):
    value=await job(db,guild)
    await db.update_role_job(value['id'],state='running')
    path=db.db_path
    await db.close()
    reopened=Database(path)
    await reopened.init()
    assert (await reopened.get_role_job(value['id']))['state']=='queued'
    await reopened.close()


@pytest.mark.asyncio
async def test_report_is_guild_scoped_and_queue_bounded(db,guild):
    first=await job(db,guild)
    assert await db.get_role_job(first['id'],'another-guild') is None
    await job(db,guild);await job(db,guild)
    with pytest.raises(ValueError,match='Three reports'):
        await job(db,guild)


def test_xlsx_exact_ids_dates_formulas_and_injection(tmp_path):
    malicious='=HYPERLINK("https://example.invalid","bad")'
    payload={'role_name':'OG','cutoff':None,'upper_at':'2026-10-04T18:00:00+00:00','state':'complete','scanned':7,
        'members':[['12345678901234567890',malicious,'Test','sobix','2026-01-01T12:00:00+00:00',None,'Not observed',None,7,7,1,2,3,None,'Accessible history scanned','']],
        'recent':[],'coverage':[['100000000000000005','Trade talk','complete',7,'']]}
    target=export_role_report(payload,tmp_path/'report.xlsx')
    with zipfile.ZipFile(target) as file:
        root=ET.fromstring(file.read('xl/worksheets/sheet1.xml'))
        cells={c.attrib['r']:c for c in root.iter(TAG('c'))}
        assert cells['A6'].attrib['t']=='inlineStr'
        assert cells['A6'].find(TAG('is')).find(TAG('t')).text=='12345678901234567890'
        assert cells['B6'].attrib['t']=='inlineStr' and cells['B6'].find(TAG('f')) is None
        assert cells['E6'].find(TAG('v')) is not None and 't' not in cells['E6'].attrib
        assert cells['N6'].find(TAG('f')).text=='SUM(K6:M6)'
        assert float(cells['N6'].find(TAG('v')).text)==6
        assert root.find(TAG('autoFilter')).attrib['ref']=='A5:P6'
        pane=root.find(TAG('sheetViews')).find(TAG('sheetView')).find(TAG('pane'))
        assert pane.attrib.get('ySplit')=='5'


def test_empty_xlsx_all_sheets_valid(tmp_path):
    payload={'role_name':'Empty','upper_at':utc_iso(),'state':'complete','scanned':0,'members':[],'recent':[],'coverage':[]}
    path=export_role_report(payload,tmp_path/'empty.xlsx')
    with zipfile.ZipFile(path) as file:
        for i in range(1,5):
            xml=file.read(f'xl/worksheets/sheet{i}.xml');ET.fromstring(xml)
            assert b'No records found' in xml


def test_report_has_real_discord_hyperlinks(tmp_path):
    link='https://discord.com/channels/100000000000000001/100000000000000005/100000000000000100'
    payload={'role_name':'Test','upper_at':utc_iso(),'state':'complete','scanned':1,
        'members':[['12345678901234567890','member','Member','',None,None,'Not observed',None,1,1,1,0,0,None,'Accessible history scanned',link]],
        'recent':[],'coverage':[],'events':[]}
    path=export_role_report(payload,tmp_path/'linked.xlsx')
    with zipfile.ZipFile(path) as file:
        sheet=ET.fromstring(file.read('xl/worksheets/sheet1.xml'))
        assert sheet.find(TAG('hyperlinks')).find(TAG('hyperlink')).attrib['ref']=='P6'
        rel=ET.fromstring(file.read('xl/worksheets/_rels/sheet1.xml.rels'))
        assert list(rel)[0].attrib['Target']==link and list(rel)[0].attrib['TargetMode']=='External'
        cells={c.attrib['r']:c for c in sheet.iter(TAG('c'))}
        styles=ET.fromstring(file.read('xl/styles.xml'))
        formats=styles.find(TAG('cellXfs'))
        fmt=list(formats)[int(cells['A6'].attrib['s'])].attrib['numFmtId']
        assert fmt=='49' or any(x.attrib.get('numFmtId')==fmt and x.attrib.get('formatCode')=='@' for x in styles.iter(TAG('numFmt')))
