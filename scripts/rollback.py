#!/usr/bin/env python3
"""Restore the previous application code while keeping current MC transactions."""
import argparse,json,os,subprocess,tarfile
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('backup',type=Path)
    args=parser.parse_args()
    if os.geteuid()!=0:
        raise SystemExit('Run as root or with sudo.')
    folder=args.backup.resolve()
    state=json.loads((folder/'rollback.json').read_text())
    app=Path(state['app']);services=[state['service'],state['recovery_service']]
    subprocess.run(['/usr/bin/systemctl','stop',*services],check=True)
    with tarfile.open(folder/'previous-code.tar.gz') as source:
        dbpath=Path(state['database']).resolve()
        members=[m for m in source.getmembers() if m.name!='.env' and (app/m.name).resolve() not in {dbpath,Path(str(dbpath)+'-wal'),Path(str(dbpath)+'-shm')}]
        source.extractall(app,members=members,filter='data')
    for service in services:
        destination=Path('/etc/systemd/system')/service
        saved=folder/service
        if saved.exists():
            destination.write_bytes(saved.read_bytes())
        else:
            destination.unlink(missing_ok=True)
    subprocess.run(['/usr/bin/systemctl','daemon-reload'],check=True)
    subprocess.run(['/usr/bin/systemctl','reset-failed',state['service']],check=True)
    subprocess.run(['/usr/bin/systemctl','start',state['service']],check=True)
    print('Previous code restored. Current database, MC and .env preserved.')


if __name__=='__main__':
    main()
