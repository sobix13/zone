#!/usr/bin/env python3
"""Synthetic 50-reviewer scenario only. Requires requirements-dev.txt."""
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from database import Database
from review_analytics import snapshot,analyze,participation_csv
from review_support_xlsx import export_support_report
from runtime_utils import utc_iso
from tests.conftest import GID,AUTHOR
from tests.test_review_support import NOW,seed_support,FEEDBACK


async def main(output):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mz-review-example-') as temporary:
        db=Database(str(Path(temporary)/'example.db'))
        await db.init();await db.create_guild_config(str(GID))
        try:
            await seed_support(db,count=50,members=True)
            await db.get_or_create_user(str(AUTHOR),str(GID),'Synthetic author')
            await db.add_mc(str(AUTHOR),str(GID),42,'regular','Synthetic existing balance')
            conn=await db._get_conn()
            await conn.execute('UPDATE mc_transactions SET timestamp=?',(utc_iso(NOW),));await conn.commit()
            for item in (await db.support_work(str(GID),now=NOW))[:8]:
                await db.rate_support(str(GID),item['id'],item['moderator_id'],8,FEEDBACK,
                    [s['id'] for s in json.loads(item['samples_json'])],now=NOW)
            data=await snapshot(db.db_path,str(GID),NOW-timedelta(days=14),NOW+timedelta(days=1))
            payload=analyze(data)
            payload['captured_at']='2026-10-10T09:00:00+00:00'
            export_support_report(payload,output/'Synthetic-review-analysis.xlsx')
            (output/'Synthetic-participation.csv').write_bytes(participation_csv(payload))
            (output/'synthetic-payload.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
            print(json.dumps({'synthetic':True,'reviewers':len(payload['reviewers']),'baseline_total':payload['baseline_estimate']['estimated_total_mc']}))
        finally:
            await db.close()


if __name__=='__main__':
    asyncio.run(main(Path(sys.argv[1])))
