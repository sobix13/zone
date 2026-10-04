#!/usr/bin/env python3
"""Offline boot plus additive migration preservation checks. Never logs a token."""
import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path


def fingerprint(path):
    conn=sqlite3.connect(path)
    result={}
    for table in ('users','posts','reviews','assignments','mc_transactions','guild_config','reaction_credits','quizzes','quiz_sessions','quiz_results','snapshot_awards','assignments_mgr','assignment_cooldowns','assignment_participants'):
        exists=conn.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()
        if not exists:
            continue
        columns=[r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
        # Normalization fills status IDs. Other existing values must remain identical.
        columns=[c for c in columns if c not in ('x_status_id','normalized_url')]
        rows=conn.execute('SELECT '+','.join(columns)+' FROM '+table).fetchall()
        encoded=sorted(json.dumps(row,default=str) for row in rows)
        result[table]={'columns':columns,'rows':len(rows),'sha256':hashlib.sha256('\n'.join(encoded).encode()).hexdigest()}
    conn.close()
    return result


def compare(before,path):
    conn=sqlite3.connect(path)
    for table,entry in before.items():
        rows=conn.execute('SELECT '+','.join(entry['columns'])+' FROM '+table).fetchall()
        encoded=sorted(json.dumps(row,default=str) for row in rows)
        if len(rows)!=entry['rows'] or hashlib.sha256('\n'.join(encoded).encode()).hexdigest()!=entry['sha256']:
            raise RuntimeError(f'Existing data changed in {table}.')
    if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':
        raise RuntimeError('Database integrity check failed.')
    conn.close()


async def check(path,source):
    before=fingerprint(path)
    sys.path.insert(0,str(source))
    os.environ['DATABASE_PATH']=str(path)
    os.environ['RUNTIME_DIR']=str(path.parent/'preflight-runtime')
    from bot import MeleeZoneBot
    async with MeleeZoneBot() as bot:
        await bot.setup_hook()
        commands=bot.tree.get_commands()
        names=[(c.name,c.type.value if hasattr(c,'type') else 1) for c in commands]
        if len(names)!=len(set(names)):
            raise RuntimeError('Duplicate application command.')
        if len([c for c in commands if not hasattr(c,'type')])>100:
            raise RuntimeError('Slash command count exceeds Discord limits.')
        views=bot.persistent_views
        ids=[child.custom_id for v in views for child in v.children if hasattr(child,'custom_id')]
        if len(ids)!=len(set(ids)):
            raise RuntimeError('Persistent component IDs collide.')
        print(json.dumps({'offline_boot':'passed','cogs':len(bot.cogs),'commands':len(commands),'persistent_views':len(views)}))
    compare(before,path)
    # Repeat migration to check restart idempotency.
    from database import Database
    db=Database(str(path))
    await db.init();await db.close();compare(before,path)
    print(json.dumps({'migration':'passed','preserved_tables':{k:v['rows'] for k,v in before.items()}}))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True,type=Path)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    asyncio.run(check(args.database.resolve(),args.source.resolve()))


if __name__=='__main__':
    main()
