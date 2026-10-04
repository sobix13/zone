#!/usr/bin/env python3
"""Independent recovery process. Does not import the main bot or its cogs."""
import asyncio
import fcntl
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote
from aiohttp import ClientSession,ClientTimeout,web
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent/'.env')
log=logging.getLogger('MeleeZone.Recovery')
RECOVERY_TASKS=web.AppKey('recovery_tasks',set)


class Recovery:
    def __init__(self,*,runtime=None,service=None,db_path=None):
        self.runtime=Path(runtime or os.getenv('RUNTIME_DIR','runtime')).resolve()
        self.runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.service=service or os.getenv('MZ_SERVICE','melee-zone.service')
        if not self.service.endswith('.service') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.@' for c in self.service):
            raise ValueError('Invalid service name.')
        self.db_path=Path(db_path or os.getenv('DATABASE_PATH','bot.db')).resolve()
        self.lock=asyncio.Lock()
        self.failures=0
        self.started=time.time()
        self.next_pulse_at=0
        self.state_path=self.runtime/'recovery-state.json'
        self.history=[]
        if self.state_path.exists():
            try:
                self.history=json.loads(self.state_path.read_text()).get('restarts',[])
            except (ValueError,OSError):
                pass
        secret_path=self.runtime/'recovery.secret'
        if not secret_path.exists():
            self.write_json_secret(secret_path,secrets.token_urlsafe(48))
        self.secret=secret_path.read_text().strip()
        self.token=os.getenv('DISCORD_TOKEN','')
        self.session=None
        self.last_result='Ready'
        self.scheduled=False

    @staticmethod
    def write_json_secret(path,value):
        path=Path(path);tmp=path.with_suffix('.tmp')
        tmp.write_text(value if isinstance(value,str) else json.dumps(value))
        tmp.chmod(0o600);os.replace(tmp,path)

    def config(self):
        path=self.runtime/'recovery.json'
        if not path.exists():
            return None
        value=json.loads(path.read_text())
        if not all(str(value.get(k,'')).isdigit() for k in ('owner_id','channel_id','message_id','guild_id')):
            raise ValueError('Invalid recovery control IDs.')
        return value

    def budget_available(self,now=None):
        now=now or time.time()
        self.history=[float(t) for t in self.history if now-float(t)<900]
        return len(self.history)<3 and (not self.history or now-self.history[-1]>=120)

    def integrity(self):
        if not self.db_path.exists():
            return 'Database not found. Check DATABASE_PATH before restarting.'
        try:
            conn=sqlite3.connect(self.db_path.as_uri()+'?mode=ro',uri=True,timeout=2)
            deadline=time.monotonic()+3
            conn.set_progress_handler(lambda: int(time.monotonic()>deadline),1000)
            try:
                answer=conn.execute('PRAGMA quick_check').fetchone()
                return None if answer and answer[0]=='ok' else 'Database integrity check failed. Restore a verified backup.'
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            return 'Database diagnostic failed: '+type(exc).__name__+'. Restore a verified backup if integrity is damaged.'

    async def systemctl(self,action):
        if action not in ('reset-failed','restart'):
            raise ValueError('Unsupported recovery action.')
        prefix=[] if os.geteuid()==0 else ['/usr/bin/sudo','-n']
        proc=await asyncio.create_subprocess_exec(*prefix,'/usr/bin/systemctl',action,self.service,
            stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
        try:
            _,error=await asyncio.wait_for(proc.communicate(),timeout=45)
        except asyncio.TimeoutError:
            proc.kill();await proc.communicate()
            raise RuntimeError('Service command timed out.')
        if proc.returncode:
            raise RuntimeError('Service restart rejected. Check the recovery sudo rule and unit logs.')

    async def recover(self,*,actor_id=None,automatic=False):
        if self.lock.locked():
            return False,'Recovery already running.'
        async with self.lock:
            config=self.config()
            owner=str(os.getenv('RESCUE_OWNER_ID') or (config or {}).get('owner_id',''))
            if not automatic and (not owner or str(actor_id)!=owner):
                return False,'Recovery owner access required.'
            if not self.budget_available():
                return False,'Recovery restart budget reached. Wait for the 15-minute window or use the server console.'
            heartbeat=self.runtime/'heartbeat.json'
            if automatic and heartbeat.exists():
                try:
                    if json.loads(heartbeat.read_text()).get('fatal'):
                        return False,'Startup configuration error requires an owner fix.'
                except (OSError,ValueError):
                    pass
            problem=await asyncio.to_thread(self.integrity)
            if problem:
                self.last_result=problem
                return False,problem
            self.history.append(time.time())
            self.write_json_secret(self.state_path,{'restarts':self.history,'source':'automatic' if automatic else 'owner','at':time.time()})
            try:
                await self.systemctl('reset-failed')
                await self.systemctl('restart')
            except RuntimeError as exc:
                self.last_result=str(exc)
                return False,self.last_result
            self.failures=0
            self.last_result='Main bot service restarted. Health is being checked.'
            log.info('Recovery restart completed. Source: %s','automatic' if automatic else 'owner')
            return True,self.last_result

    async def discord_request(self,method,path,**kwargs):
        headers={'Authorization':'Bot '+self.token}
        async with self.session.request(method,'https://discord.com/api/v10'+path,headers=headers,**kwargs) as response:
            if response.status==429:
                value=await response.json()
                self.next_pulse_at=time.time()+float(value.get('retry_after',30))
                return None
            if response.status>=400:
                log.warning('Recovery REST request status: %s',response.status)
                return None
            if response.status==204:
                return True
            return await response.json()

    async def poll_pulse(self):
        if not self.token or time.time()<self.next_pulse_at:
            return
        config=self.config()
        if not config:
            return
        emoji=quote(config['emoji'],safe='')
        base=f"/channels/{config['channel_id']}/messages/{config['message_id']}"
        # Fetch around the owner's ID. Crowded reactions cannot hide the owner in a 100-user page.
        users=await self.discord_request('GET',base+'/reactions/'+emoji,params={'limit':'1','after':str(max(0,int(config['owner_id'])-1))})
        if not users or str(users[0].get('id'))!=config['owner_id']:
            return
        removed=await self.discord_request('DELETE',base+'/reactions/'+emoji+'/'+config['owner_id'])
        if removed is not True:
            return
        ok,message=await self.recover(actor_id=config['owner_id'])
        await self.discord_request('POST',f"/channels/{config['channel_id']}/messages",json={'content':message,'allowed_mentions':{'parse':[]}})

    async def check_main(self):
        try:
            async with self.session.get(f"http://127.0.0.1:{int(os.getenv('HEALTH_PORT','3020'))}/health") as response:
                state=await response.json()
                alive=response.status==200 and state.get('alive')
                if alive and (state.get('gateway_connected') or state.get('disconnected_seconds',0)<300):
                    self.failures=0
                    return
        except (OSError,ValueError,asyncio.TimeoutError):
            pass
        self.failures+=1
        if self.failures>=3 and time.time()-self.started>120:
            await self.recover(automatic=True)

    async def daily_backup(self):
        # SQLite backup includes committed WAL records without copying inconsistent DB/WAL files.
        from datetime import datetime,timezone
        directory=Path(os.getenv('BACKUP_DIR','backups')).resolve()
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        target=directory/f"daily-{datetime.now(timezone.utc).strftime('%Y%m%d')}.db"
        if target.exists() or not self.db_path.exists():
            return
        def backup():
            src=sqlite3.connect(self.db_path.as_uri()+'?mode=ro',uri=True,timeout=2)
            dest=sqlite3.connect(target.with_suffix('.tmp'))
            deadline=time.monotonic()+20
            def progress(status,left,total):
                if time.monotonic()>deadline:
                    raise TimeoutError('Backup timed out.')
            try:
                src.backup(dest,pages=128,sleep=0.05,progress=progress)
                dest.close();src.close()
                temp=target.with_suffix('.tmp')
                temp.chmod(0o600);os.replace(temp,target)
            finally:
                dest.close();src.close()
        await asyncio.to_thread(backup)
        for old in sorted(directory.glob('daily-*.db'))[:-7]:
            old.unlink()

    async def loop(self):
        while True:
            try:
                await self.check_main()
            except Exception as exc:
                log.warning('Health check: %s',type(exc).__name__)
            try:
                await self.poll_pulse()
            except Exception as exc:
                log.warning('Recovery pulse: %s',type(exc).__name__)
            try:
                await self.daily_backup()
            except Exception as exc:
                log.warning('Daily backup: %s',type(exc).__name__)
            await asyncio.sleep(15)

    def app(self):
        app=web.Application(client_max_size=2048)
        async def status(request):
            return web.json_response({'service':'melee-zone-recovery','running':True,'last_result':self.last_result})
        async def recover(request):
            if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+self.secret):
                return web.json_response({'message':'Unauthorized.'},status=401)
            data=await request.json()
            config=self.config()
            owner=str(os.getenv('RESCUE_OWNER_ID') or (config or {}).get('owner_id',''))
            if not owner or str(data.get('actor_id'))!=owner:
                return web.json_response({'message':'Recovery owner access required.'},status=403)
            if not self.budget_available() or self.lock.locked() or self.scheduled:
                return web.json_response({'message':'Recovery is busy or its restart budget is reached.'},status=429)
            # Acknowledge first. Let the main bot deliver the response before it is stopped.
            async def later():
                try:
                    await asyncio.sleep(3)
                    await self.recover(actor_id=owner)
                finally:
                    self.scheduled=False
            self.scheduled=True
            task=asyncio.create_task(later())
            app[RECOVERY_TASKS].add(task);task.add_done_callback(app[RECOVERY_TASKS].discard)
            return web.json_response({'message':'Recovery accepted. The main bot will restart after diagnostics.'},status=202)
        app[RECOVERY_TASKS]=set()
        app.router.add_get('/health',status);app.router.add_post('/recover',recover)
        return app


async def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(name)s %(message)s')
    recovery=Recovery()
    guard=open(recovery.runtime/'recovery.lock','w')
    try:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        log.error('Another recovery watcher is active.');return
    async with ClientSession(timeout=ClientTimeout(total=8)) as session:
        recovery.session=session
        app=recovery.app();runner=web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner,'127.0.0.1',int(os.getenv('RECOVERY_PORT','3021'))).start()
        try:
            await recovery.loop()
        finally:
            pending=list(app[RECOVERY_TASKS])
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending,return_exceptions=True)
            await runner.cleanup()
    guard.close()


if __name__=='__main__':
    asyncio.run(main())
