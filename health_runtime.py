"""Real readiness, heartbeat, bounded task repair and separate recovery requests."""
import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from datetime import datetime,timezone,timedelta
import aiohttp
from aiohttp import web
from discord.ext import tasks
from runtime_utils import utc_iso

VERSION='3.0.0'
log=logging.getLogger('MeleeZone.Health')


def write_private_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value),encoding='utf-8')
    temporary.chmod(0o600)
    os.replace(temporary,path)


class HealthRuntime:
    def __init__(self,bot):
        self.bot=bot
        self.started=time.monotonic()
        self.last_tick=self.started
        self.lag_seconds=0.0
        self.db_ok=False
        self.db_error=None
        self.last_error=None
        self.fatal=None
        self.failed_cogs=[]
        self.command_sync_errors=[]
        self.ready_since=None
        self.disconnected_since=None
        self._repairs={}
        self.task=None
        self.runner=None

    def snapshot(self):
        ready=self.bot.is_ready()
        problems=[]
        if not self.db_ok:
            problems.append(self.db_error or 'database unavailable')
        if self.lag_seconds>10 or time.monotonic()-self.last_tick>45:
            problems.append('event loop stalled')
        if self.failed_cogs:
            problems.append('extensions failed: '+','.join(self.failed_cogs))
        if self.fatal:
            problems.append(self.fatal)
        if self.command_sync_errors:
            problems.append('command registration pending: '+','.join(self.command_sync_errors))
        if shutil.disk_usage(Path(self.bot.db.db_path).resolve().parent).free<100*1024*1024:
            problems.append('less than 100 MiB disk space')
        alive=not problems
        loops={}
        for cog in self.bot.cogs.values():
            for name in ('weekly_cycle','daily_check','daily_update','report_worker','reaction_worker','notification_worker'):
                loop=getattr(cog,name,None)
                if isinstance(loop,tasks.Loop):
                    loops[f'{cog.qualified_name}.{name}']='running' if loop.is_running() else 'stopped'
        stopped=[key for key,value in loops.items() if value=='stopped']
        if ready and stopped:
            problems.append('background tasks stopped: '+', '.join(stopped))
        alive=not problems
        return {'version':VERSION,'pid':os.getpid(),'at':utc_iso(),'uptime_seconds':round(time.monotonic()-self.started),
            'alive':alive,'ready':alive and ready,'gateway_connected':ready,'db_ok':self.db_ok,
            'lag_seconds':round(self.lag_seconds,3),'issues':problems,'loops':loops,
            'last_error':self.last_error,'fatal':self.fatal,'failed_cogs':self.failed_cogs,
            'disconnected_seconds':round(time.monotonic()-self.disconnected_since) if self.disconnected_since else 0}

    async def start(self,port=3020):
        app=web.Application(client_max_size=8192)
        async def health(request):
            state=self.snapshot()
            return web.json_response(state,status=200 if state['alive'] else 503)
        async def ready(request):
            state=self.snapshot()
            return web.json_response(state,status=200 if state['ready'] else 503)
        app.router.add_get('/',health)
        app.router.add_get('/health',health)
        app.router.add_get('/ready',ready)
        self.runner=web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner,'127.0.0.1',port).start()
        self.task=asyncio.create_task(self._monitor(),name='melee-health-monitor')

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
        if self.runner:
            await self.runner.cleanup()

    async def repair_loops(self):
        repaired=[]
        if not self.bot.is_ready():
            return repaired
        for cog in list(self.bot.cogs.values()):
            for name in ('weekly_cycle','daily_check','daily_update','report_worker','reaction_worker','notification_worker'):
                loop=getattr(cog,name,None)
                if not isinstance(loop,tasks.Loop) or loop.is_running() or self.bot.is_closed():
                    continue
                key=f'{cog.qualified_name}.{name}'
                recent=[t for t in self._repairs.get(key,[]) if time.monotonic()-t<3600]
                if len(recent)>=3:
                    continue
                recent.append(time.monotonic());self._repairs[key]=recent
                loop.start();repaired.append(key)
                log.warning('Restarted stopped background task: %s',key)
        return repaired

    async def _monitor(self):
        while True:
            started=time.monotonic()
            self.lag_seconds=max(0,started-self.last_tick-10)
            self.last_tick=started
            try:
                self.db_ok=await asyncio.wait_for(self.bot.db.db_health(),timeout=3)
                self.db_error=None
                await self.repair_loops()
            except Exception as exc:
                self.db_ok=False;self.db_error=type(exc).__name__
            await asyncio.to_thread(write_private_json,Path(os.getenv('RUNTIME_DIR','runtime'))/'heartbeat.json',self.snapshot())
            await asyncio.sleep(10)

    async def recover(self,actor_id):
        token_path=Path(os.getenv('RUNTIME_DIR','runtime'))/'recovery.secret'
        if not token_path.is_file():
            raise ValueError('Recovery service is not installed. Run install.sh first.')
        port=int(os.getenv('RECOVERY_PORT','3021'))
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(f'http://127.0.0.1:{port}/recover',json={'actor_id':str(actor_id)},
                headers={'Authorization':'Bearer '+token_path.read_text().strip()}) as response:
                result=await response.json()
                if response.status!=202:
                    raise ValueError(result.get('message','Recovery request rejected.'))
                return result['message']
