#!/usr/bin/env python3
"""Host-console status or owner recovery without the main Discord process."""
import argparse,json,os,sys,urllib.request,urllib.error
from pathlib import Path
from dotenv import load_dotenv

APP=Path(__file__).resolve().parents[1]
load_dotenv(APP/'.env')


def request(url,*,body=None,secret=None):
    headers={'Content-Type':'application/json'}
    if secret:
        headers['Authorization']='Bearer '+secret
    call=urllib.request.Request(url,data=json.dumps(body).encode() if body else None,headers=headers)
    try:
        with urllib.request.urlopen(call,timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())
    except OSError as exc:
        return {'message':'Local service unavailable: '+type(exc).__name__}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['status','recover'])
    args=parser.parse_args()
    if args.action=='status':
        for label,port in [('main',os.getenv('HEALTH_PORT','3020')),('recovery',os.getenv('RECOVERY_PORT','3021'))]:
            print(json.dumps({label:request(f'http://127.0.0.1:{int(port)}/health')},indent=2))
        return
    runtime=Path(os.getenv('RUNTIME_DIR',str(APP/'runtime')))
    if not runtime.is_absolute():
        runtime=APP/runtime
    config=json.loads((runtime/'recovery.json').read_text()) if (runtime/'recovery.json').exists() else {}
    owner=os.getenv('RESCUE_OWNER_ID') or config.get('owner_id')
    if not owner:
        raise SystemExit('Set up the recovery owner/control first, or use authorized systemctl access.')
    secret=(runtime/'recovery.secret').read_text().strip()
    result=request(f"http://127.0.0.1:{int(os.getenv('RECOVERY_PORT','3021'))}/recover",body={'actor_id':str(owner)},secret=secret)
    print(result.get('message','Recovery response unavailable.'))


if __name__=='__main__':
    main()
