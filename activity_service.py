"""Resumable, bounded channel history scanning for selected role members."""
import asyncio
import json
import os
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
import discord
from runtime_utils import parse_time,resolve_channel,utc_iso
from xlsx_report import export_role_report


def message_row(message):
    text=(message.content or '').replace('\x00','')[:350]
    attachments=len(getattr(message,'attachments',[]))
    if attachments:
        text+=f' [{attachments} attachment(s)]'
    return (str(message.id),str(message.guild.id),str(message.author.id),str(message.channel.id),
        str(message.channel.parent_id) if getattr(message.channel,'parent_id',None) else None,
        utc_iso(message.created_at),text)


async def role_roster(guild,role):
    """Fetch the full member list. A partial cache never becomes a complete roster."""
    members=[]
    async with asyncio.timeout(180):
        async for member in guild.fetch_members(limit=None):
            if any(r.id==role.id for r in member.roles):
                members.append({'id':str(member.id),'username':member.name,'display_name':member.display_name,
                    'joined_at':utc_iso(member.joined_at) if member.joined_at else None,'is_bot':member.bot})
    return members


async def discover_channels(bot,guild,job):
    db=bot.db
    seen=set()
    cap=int(os.getenv('REPORT_MAX_THREADS','500'))
    discovered_threads=0
    async def add(channel):
        if channel.id in seen:
            return
        seen.add(channel.id)
        permissions=channel.permissions_for(guild.me)
        readable=permissions.view_channel and permissions.read_message_history
        await db.add_report_channel(job['id'],channel.id,channel.name,
            state='pending' if readable else 'skipped',detail=None if readable else 'Missing View Channel or Read Message History.')

    for channel in guild.text_channels:
        await add(channel)
    try:
        active=await guild.active_threads()
    except discord.HTTPException as exc:
        active=list(guild.threads)
        await db.add_report_channel(job['id'],'discovery:active','Active threads',state='skipped',detail=f'Active thread listing failed: {type(exc).__name__}. Cached threads included.')
    for thread in active:
        await add(thread)
    for parent in [*guild.text_channels,*guild.forums]:
        if not parent.permissions_for(guild.me).view_channel:
            continue
        modes=[{}]
        if isinstance(parent,discord.TextChannel):
            modes.append({'private':True,'joined':not parent.permissions_for(guild.me).manage_threads})
        for mode in modes:
            label='Private archived threads' if mode else 'Archived threads'
            try:
                remaining=max(0,cap-discovered_threads)
                async for thread in parent.archived_threads(limit=remaining+1,**mode):
                    if discovered_threads>=cap:
                        await db.add_report_channel(job['id'],f'discovery:{parent.id}:{bool(mode)}',f'{parent.name}: {label}',state='skipped',detail=f'Thread enumeration budget ({cap}) reached. Increase REPORT_MAX_THREADS for a new report.')
                        break
                    if thread.id not in seen:
                        discovered_threads+=1
                    await add(thread)
            except discord.HTTPException as exc:
                await db.add_report_channel(job['id'],f'discovery:{parent.id}:{bool(mode)}',f'{parent.name}: {label}',state='skipped',detail=f'Listing unavailable: {type(exc).__name__}.')
    await db.update_role_job(job['id'],discovery_complete=1)


async def process_report(bot,job,*,time_budget=1200):
    db=bot.db
    guild=bot.get_guild(int(job['guild_id']))
    if not guild:
        await db.update_role_job(job['id'],state='paused',error='Server unavailable. Resume when connected.')
        return
    await db.update_role_job(job['id'],state='running',error=None)
    if not job['discovery_complete']:
        await discover_channels(bot,guild,job)
    wanted={m['id'] for m in json.loads(job['members_json'])}
    started=time.monotonic()
    after=parse_time(job['cutoff']) if job['cutoff'] else None
    upper=discord.Object(id=discord.utils.time_snowflake(parse_time(job['upper_at']),high=False))
    for saved in await db.report_channels(job['id']):
        if saved['state']!='pending':
            continue
        channel=await resolve_channel(bot,guild,saved['channel_id'])
        if not channel:
            await db.set_report_channel(job['id'],saved['channel_id'],'skipped','Channel deleted or no longer accessible.')
            continue
        before=discord.Object(id=int(saved['before_id'])) if saved['before_id'] else upper
        while True:
            current=await db.get_role_job(job['id'])
            if current['state']=='cancelled':
                await export_job(db,current)
                return
            remaining=current['max_messages']-current['scanned']
            if remaining<=0 or time.monotonic()-started>=time_budget:
                await db.update_role_job(job['id'],state='paused',error='Scan budget reached. Resume to continue from the saved cursor.')
                await export_job(db,await db.get_role_job(job['id']))
                return
            page_size=min(100,remaining)
            try:
                page=[m async for m in channel.history(limit=page_size,before=before,after=after,oldest_first=False)]
            except (discord.Forbidden,discord.NotFound) as exc:
                await db.set_report_channel(job['id'],saved['channel_id'],'skipped',type(exc).__name__)
                break
            except discord.HTTPException as exc:
                await db.update_role_job(job['id'],state='paused',error=f'Discord history request failed ({exc.status}). Resume later.')
                await export_job(db,await db.get_role_job(job['id']))
                return
            rows=[message_row(m) for m in page if str(m.author.id) in wanted and not m.author.bot]
            last=str(page[-1].id) if page else (str(before.id) if before else None)
            complete=len(page)<page_size
            await db.store_activity_messages(rows,job_id=job['id'],channel_id=saved['channel_id'],
                before_id=last,scanned=len(page),complete=complete)
            if complete:
                break
            before=discord.Object(id=int(last))
            await asyncio.sleep(0)
    await db.update_role_job(job['id'],state='complete',error=None)
    await export_job(db,await db.get_role_job(job['id']))


async def export_job(db,job):
    roster=json.loads(job['members_json'])
    coverage=await db.report_channels(job['id'])
    full=job['discovery_complete'] and bool(coverage) and all(c['state']=='complete' for c in coverage)
    coverage_label='Accessible history scanned' if full else 'Partial history'
    members=[]
    recent=[]
    events=[]
    for member in roster:
        activity=await db.activity_for_member(job['guild_id'],member['id'],job['cutoff'],job['upper_at'])
        user=await db.get_user(member['id'],job['guild_id']) or {}
        last=activity['recent_messages'][0] if activity['recent_messages'] else None
        link=f"https://discord.com/channels/{job['guild_id']}/{last['channel_id']}/{last['message_id']}" if last else ''
        members.append([member['id'],member['username'],member['display_name'],user.get('twitter_username') or '',
            member['joined_at'],activity['last_activity_at'],activity['last_activity_type'] or 'Not observed',
            activity['last_message_at'],activity['window_messages'],activity['known_messages'],
            user.get('mc_regular',0) or 0,user.get('mc_golden',0) or 0,user.get('mc_assignment',0) or 0,
            None,coverage_label,link])
        for msg in activity['recent_messages']:
            recent.append([member['id'],member['display_name'],msg['created_at'],msg['channel_id'],msg['excerpt'],
                f"https://discord.com/channels/{job['guild_id']}/{msg['channel_id']}/{msg['message_id']}"])
        for event in activity['recent_events']:
            link=f"https://discord.com/channels/{job['guild_id']}/{event['channel_id']}" if event['channel_id'] else ''
            if event['event_key'].startswith('reaction-event:'):
                link+='/'+event['event_key'].split(':')[1]
            events.append([member['id'],member['display_name'],event['created_at'],event['event_type'],event['channel_id'] or '',link])
    directory=Path(os.getenv('REPORT_DIR','runtime/reports')).resolve()
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    output=directory/f"role-report-{job['id']}.xlsx"
    payload={'role_name':job['role_name'],'cutoff':job['cutoff'],'upper_at':job['upper_at'],
        'state':job['state'],'scanned':job['scanned'],'members':members,'recent':recent,'events':events,
        'coverage':[[c['channel_id'],c['channel_name'],c['state'],c['scanned'],c['detail'] or ''] for c in coverage]}
    await asyncio.to_thread(export_role_report,payload,output)
    output.chmod(0o600)
    await db.update_role_job(job['id'],output_path=str(output))
    return output
