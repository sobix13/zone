#!/usr/bin/env python3
"""Backup, validate, install and roll back an existing Ubuntu deployment."""
import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request
from datetime import datetime,timezone
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]
UNIT_DIR=Path('/etc/systemd/system')
SUDOERS_DIR=Path('/etc/sudoers.d')


def run(command,**kwargs):
    return subprocess.run([str(v) for v in command],check=True,**kwargs)


def env_value(path,key,default):
    # Use the installed dotenv parser, never source user configuration as shell code.
    script='from dotenv import dotenv_values;import sys;print(dotenv_values(sys.argv[1]).get(sys.argv[2]) or sys.argv[3])'
    return subprocess.check_output([str(path),'-c',script,str(APP/'.env'),key,default],text=True).strip()


def verify_source():
    manifest=json.loads((SOURCE/'release-manifest.json').read_text())
    for filename,expected in manifest['files'].items():
        p=SOURCE/filename
        if not p.resolve().is_relative_to(SOURCE) or p.name in ('.env','bot.db') or p.is_symlink():
            raise RuntimeError('Release contains a forbidden path.')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise RuntimeError(f'Release checksum mismatch: {filename}')
    return manifest


def database_backup(database,target):
    src=sqlite3.connect(database)
    dest=sqlite3.connect(target)
    try:
        src.backup(dest)
        if dest.execute('PRAGMA quick_check').fetchone()[0]!='ok':
            raise RuntimeError('Backup integrity check failed.')
    finally:
        src.close();dest.close()
    target.chmod(0o600)


def service_unit(app,python,user,service,owner,dbpath,recovery=False):
    script='recovery_daemon.py' if recovery else 'bot.py'
    description='Melee Zone independent recovery' if recovery else 'Melee Zone bot'
    env=[f'RUNTIME_DIR={app}/runtime',f'REPORT_DIR={app}/runtime/reports',f'DATABASE_PATH={dbpath}',f'MZ_SERVICE={service}']
    if owner:
        env.append('RESCUE_OWNER_ID='+owner)
    settings='\n'.join('Environment='+v for v in env)
    return f'''[Unit]
Description={description}
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=900
StartLimitBurst=3

[Service]
Type=simple
User={user}
WorkingDirectory={app}
ExecStart={python} -u {app}/{script}
{settings}
Restart=on-failure
RestartSec=15
TimeoutStopSec=25
KillMode=control-group
UMask=0077
PrivateTmp=true
ProtectSystem=full
MemoryHigh=384M
MemoryMax=768M
TasksMax=128
LimitNOFILE=8192
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
'''


def stop_legacy_watchdogs(app):
    """Stop only an old shell watcher whose script belongs to this application."""
    target=(app/'watchdog.sh').resolve()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name)==os.getpid():
            continue
        try:
            argv=(process/'cmdline').read_bytes().split(b'\0')
            if len(argv)<2 or Path(os.fsdecode(argv[0])).name not in ('bash','sh','dash'):
                continue
            script=Path(os.fsdecode(argv[1]))
            if not script.is_absolute():
                script=(process/'cwd').resolve()/script
            if script.resolve()==target:
                os.kill(int(process.name),signal.SIGTERM)
        except (OSError,ValueError):
            continue


def main():
    global APP
    if sys.version_info<(3,11):
        raise RuntimeError('Python 3.11 or later is required. Python 3.12 is the validated version.')
    parser=argparse.ArgumentParser(description='Install Melee Zone V3 over an existing deployment.')
    parser.add_argument('--app-dir',type=Path,default=Path('/root/Melee-Zone'))
    parser.add_argument('--service',default='melee-zone.service')
    parser.add_argument('--service-user')
    parser.add_argument('--owner-id')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    APP=args.app_dir.resolve()
    if APP==SOURCE:
        raise ValueError('Extract the release into a separate folder before upgrading the current application.')
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',str(APP)) or APP==Path('/'):
        raise ValueError('Use an absolute application path without spaces.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.service',args.service):
        raise ValueError('Invalid service name.')
    if args.owner_id and not re.fullmatch(r'\d{10,22}',args.owner_id):
        raise ValueError('Use the recovery owner Discord user ID.')
    if not (APP/'.env').exists():
        raise RuntimeError('Existing .env not found. Choose the current bot application folder.')
    manifest=verify_source()
    if args.dry_run:
        print(json.dumps({'version':manifest['version'],'target':str(APP),'service':args.service,'files':len(manifest['files']),'mode':'dry-run','database_and_env':'preserved'}))
        return
    if os.geteuid()!=0:
        raise RuntimeError('Run install.sh with sudo or as root.')
    service=args.service
    recovery_service=service.removesuffix('.service')+'-recovery.service'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    release_dir=APP/'.releases'/f"{manifest['version']}-{stamp}"
    release_dir.mkdir(parents=True,mode=0o700)
    venv=release_dir/'venv'
    print('Preparing the new Python environment.',flush=True)
    run([sys.executable,'-m','venv',venv])
    python=venv/'bin'/'python'
    run([python,'-m','pip','install','--disable-pip-version-check','-q','-r',SOURCE/'requirements.txt'])
    dbpath=Path(env_value(python,'DATABASE_PATH','bot.db'))
    dbpath=(APP/dbpath).resolve() if not dbpath.is_absolute() else dbpath.resolve()
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+',str(dbpath)) or not dbpath.is_file():
        raise RuntimeError('Configured database is unavailable or its path contains spaces.')
    user=args.service_user
    if not user:
        user=subprocess.check_output(['/usr/bin/systemctl','show',service,'-p','User','--value'],text=True).strip() or 'root'
    account=pwd.getpwnam(user)
    backup=APP/'backups'/f'upgrade-{stamp}'
    backup.mkdir(parents=True,mode=0o700)
    original_env_hash=hashlib.sha256((APP/'.env').read_bytes()).hexdigest()
    unit_path=UNIT_DIR/service
    rescue_path=UNIT_DIR/recovery_service
    original_units={p:p.read_bytes() if p.exists() else None for p in (unit_path,rescue_path)}
    for p,data in original_units.items():
        if data is not None:
            (backup/p.name).write_bytes(data)
    print('Checking migration on a consistent database copy.',flush=True)
    database_backup(dbpath,backup/'before.db')
    shutil.copy2(backup/'before.db',backup/'migration-test.db')
    run([python,SOURCE/'scripts'/'preflight.py','--database',backup/'migration-test.db','--source',SOURCE],cwd=release_dir)
    archive=backup/'previous-code.tar.gz'
    skip={'venv','.venv','.releases','backups','runtime','.git','__pycache__','.pytest_cache'}
    with tarfile.open(archive,'w:gz') as tar:
        for p in APP.iterdir():
            if p.name not in skip and not p.name.startswith('bot.db') and not p.is_symlink():
                tar.add(p,arcname=p.name)
    archive.chmod(0o600)
    (backup/'rollback.json').write_text(json.dumps({'app':str(APP),'service':service,'recovery_service':recovery_service,'database':str(dbpath),'new_files':list(manifest['files'])}))
    (backup/'rollback.json').chmod(0o600)
    installed=False
    main_started=False
    try:
        print('Stopping services and taking the final backup.',flush=True)
        stop_legacy_watchdogs(APP)
        subprocess.run(['/usr/bin/systemctl','stop',recovery_service],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        run(['/usr/bin/systemctl','stop',service])
        database_backup(dbpath,backup/'before.db')
        installed=True
        for filename in manifest['files']:
            target=APP/filename;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(SOURCE/filename,target)
        run([python,APP/'scripts'/'preflight.py','--database',dbpath,'--source',APP],cwd=APP)
        if hashlib.sha256((APP/'.env').read_bytes()).hexdigest()!=original_env_hash:
            raise RuntimeError('.env changed unexpectedly.')
        (APP/'runtime').mkdir(exist_ok=True,mode=0o700)
        for directory in (APP/'runtime',APP/'backups',release_dir):
            for parent,dirs,files in os.walk(directory):
                os.chown(parent,account.pw_uid,account.pw_gid)
                for filename in files:
                    os.chown(Path(parent)/filename,account.pw_uid,account.pw_gid)
        if args.service_user:
            os.chown(APP,account.pw_uid,account.pw_gid)
            os.chown(APP/'.env',account.pw_uid,account.pw_gid)
            for p in dbpath.parent.glob(dbpath.name+'*'):
                os.chown(p,account.pw_uid,account.pw_gid)
        unit_path.write_text(service_unit(APP,python,user,service,args.owner_id,dbpath))
        rescue_path.write_text(service_unit(APP,python,user,service,args.owner_id,dbpath,recovery=True))
        if user!='root':
            sudoers=SUDOERS_DIR/('mz-recovery-'+service.removesuffix('.service'))
            sudoers.write_text(f'{user} ALL=(root) NOPASSWD: /usr/bin/systemctl restart {service}, /usr/bin/systemctl reset-failed {service}\n')
            sudoers.chmod(0o440)
            run(['/usr/sbin/visudo','-cf',sudoers])
        run(['/usr/bin/systemctl','daemon-reload'])
        run(['/usr/bin/systemctl','enable',service,recovery_service],stdout=subprocess.DEVNULL)
        run(['/usr/bin/systemctl','reset-failed',service,recovery_service])
        main_started=True
        run(['/usr/bin/systemctl','start',service,recovery_service])
        port=int(env_value(python,'HEALTH_PORT','3020'))
        ready=False
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/ready',timeout=4) as response:
                    if json.load(response).get('ready'):
                        ready=True;break
            except (OSError,ValueError):
                pass
            time.sleep(2)
        if not ready:
            raise RuntimeError('Discord readiness did not pass within 120 seconds.')
        print(f"Update installed. Backup: {backup}. Run /doctor, then /recovery_setup in a private admin channel.")
    except BaseException:
        if installed:
            print('Restoring previous code and service units. Existing MC data stays in place.',flush=True)
            subprocess.run(['/usr/bin/systemctl','stop',service,recovery_service],check=False)
            with tarfile.open(archive) as tar:
                members=[m for m in tar.getmembers() if m.name!='.env' and (APP/m.name).resolve() not in {dbpath,Path(str(dbpath)+'-wal'),Path(str(dbpath)+'-shm')}]
                tar.extractall(APP,members=members,filter='data')
            if not main_started:
                database_backup(backup/'before.db',dbpath)
            for p,data in original_units.items():
                if data is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(data)
            subprocess.run(['/usr/bin/systemctl','daemon-reload'],check=False)
            subprocess.run(['/usr/bin/systemctl','reset-failed',service],check=False)
            subprocess.run(['/usr/bin/systemctl','start',service],check=False)
        raise


if __name__=='__main__':
    main()
