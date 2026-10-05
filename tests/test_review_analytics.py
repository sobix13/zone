from copy import deepcopy
from datetime import timedelta
import csv
import io
import json
import os
import zipfile
import xml.etree.ElementTree as ET

import pytest

import review_analytics as analytics
from review_support_xlsx import export_support_report
from runtime_utils import utc_iso
from tests.conftest import GID, AUTHOR, OWNER
from tests.test_review_support import NOW, PEOPLE, MODS, seed_support, first_task, evaluate, FEEDBACK
from xlsx_report import TAG


async def report(db, *, count=10, sample_count=3, members=True, overrides=None):
    await seed_support(db, count=count, sample_count=sample_count, members=members)
    data = await analytics.snapshot(db.db_path, str(GID), NOW-timedelta(days=14), NOW+timedelta(days=1))
    return data, analytics.analyze(data, overrides)


@pytest.mark.asyncio
async def test_participation_and_estimates_trace_to_matching_cycle_cohorts(db):
    data, payload = await report(db)
    assert payload['summary']['posts'] == 3 and payload['summary']['reviews'] == 30
    assert payload['summary']['current_reviewers'] == 10
    assert payload['summary']['mature_completion_rate'] == 1
    assert payload['summary']['current_role_completion_rate'] == 1
    assert payload['baseline_estimate']['score_regular_mc'] == 15
    assert payload['baseline_estimate']['review_goal_mc'] == 20
    assert payload['baseline_estimate']['comment_bonus_mc'] == 10
    assert payload['baseline_estimate']['submission_goal_mc'] == 2
    assert payload['baseline_estimate']['estimated_total_mc'] == 56
    assert sum(g['completed_assignments'] for g in payload['weekly_goals']) == 30
    assert all(p['observed_mean_score']==8 for p in payload['posts'])
    current_limit = data['config']['max_reviews_per_week']
    assert all(abs(r['suggested']-current_limit)<=2 for r in payload['recommendations'] if r['setting']=='max_reviews_per_week')
    # A defaultdict can contain dozens of empty authors; only the one active author counts.
    assert next(r['suggested'] for r in payload['recommendations'] if r['setting']=='max_submits_per_week') == 4


@pytest.mark.asyncio
async def test_missing_opportunities_do_not_turn_into_zero_and_do_not_suggest_pressure(db):
    _, payload = await report(db, sample_count=0)
    assert payload['summary']['mature_completion_rate'] is None
    assert payload['summary']['observed_capacity_per_week'] is None
    assert payload['reviewers'][0]['opportunity_completion_rate'] is None
    assert payload['reviewers'][0]['moderator_review_score'] is None
    assert payload['reviewers'][0]['review_opportunity_state'] == 'No review opportunities observed'
    assert payload['recommendations'][0]['suggested'] is None
    assert payload['estimate']['estimated_total_mc'] == 0


@pytest.mark.asyncio
async def test_actual_ledger_is_separate_from_prediction_and_balance_is_current(db):
    await seed_support(db, count=10, members=True)
    await db.get_or_create_user(str(AUTHOR), str(GID), '=unsafe-name')
    await db.add_mc(str(AUTHOR), str(GID), 12, 'regular', 'Existing award')
    await db.add_mc(str(AUTHOR), str(GID), 4, 'golden', 'Special')
    conn = await db._get_conn()
    # Imported correction records are valid report inputs, not a new award API.
    await conn.execute('UPDATE users SET mc_regular=mc_regular-3 WHERE guild_id=? AND user_id=?',(str(GID),str(AUTHOR)))
    await conn.execute('INSERT INTO mc_transactions(transaction_id,user_id,guild_id,amount,mc_type,reason) VALUES (?,?,?,?,?,?)',
        ('fixture-correction',str(AUTHOR),str(GID),-3,'regular','Correction'))
    await conn.execute('UPDATE mc_transactions SET timestamp=?', (utc_iso(NOW),))
    await conn.commit()
    cfg_before = await db.get_guild_config(str(GID))
    data = await analytics.snapshot(db.db_path, str(GID), NOW-timedelta(days=14), NOW+timedelta(days=1))
    payload = analytics.analyze(data, {'mc_score_high':0, 'mc_review_reward':0, 'mc_showcase_reward':0})
    member = next(m for m in payload['members'] if m['discord_id']==str(AUTHOR))
    assert (member['regular_mc'],member['golden_mc'],member['total_mc']) == (9,4,13)
    assert member['mc_earned_in_window']==16 and member['mc_deducted_in_window']==3
    assert payload['summary']['regular_mc_paid']==12 and payload['summary']['golden_mc_paid']==4
    assert payload['estimate']['score_regular_mc']==0
    assert payload['estimate']['review_goal_mc']==0
    assert payload['estimate']['showcase_golden_mc']==0
    assert await db.get_guild_config(str(GID))==cfg_before


@pytest.mark.asyncio
async def test_snapshot_half_open_utc_mixed_timestamps_and_guild_isolation(db):
    await seed_support(db, count=1, sample_count=0)
    start, end = NOW-timedelta(days=14), NOW
    conn = await db._get_conn()
    events = [('at-start',str(GID),utc_iso(start)), ('at-end',str(GID),utc_iso(end)),
              ('sql-date',str(GID),(start+timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')),
              ('local-offset',str(GID),(start+timedelta(days=1)).isoformat().replace('+00:00','+03:30')),
              ('previous',str(GID),utc_iso(start-timedelta(days=1))), ('foreign','other',utc_iso(start))]
    for pid,gid,at in events:
        await conn.execute('INSERT INTO posts(post_id,guild_id,author_id,tweet_link,week_id,submitted_at) VALUES (?,?,?,?,?,?)',
            (pid,gid,str(AUTHOR),'https://x.com/test/status/123','week',at))
        await conn.execute('INSERT INTO reviews(review_id,post_id,reviewer_id,score,week_id,submitted_at) VALUES (?,?,?,?,?,?)',
            ('r-'+pid,pid,PEOPLE[0],8,'week',at))
    await conn.commit()
    data = await analytics.snapshot(db.db_path,str(GID),start,end)
    payload = analytics.analyze(data)
    assert payload['summary']['posts']==3 and payload['summary']['reviews']==3
    assert payload['summary']['previous_posts']==1 and payload['summary']['previous_reviews']==1
    assert all(r['guild_id']==str(GID) for r in data['reviews'])
    assert not any(p['post_id'] in ('at-end','foreign') for p in data['posts'])


@pytest.mark.asyncio
async def test_pending_future_due_and_reassigned_do_not_lower_mature_completion(db):
    data, _ = await report(db, count=1, sample_count=1)
    template = deepcopy(data['assignments'][0])
    data['assignments'] += [{**template,'assignment_id':'future','status':'pending','completed_at':None,'due_date':utc_iso(NOW+timedelta(days=7))},
                            {**template,'assignment_id':'moved','status':'reassigned','completed_at':None}]
    row = analytics.analyze(data)['reviewers'][0]
    assert row['mature_opportunities']==1 and row['opportunity_completion_rate']==1
    assert row['pending_future_due']==1 and row['reassigned_removed']==1


@pytest.mark.asyncio
async def test_post_sample_uses_as_of_reviews_not_present_final_status(db):
    await seed_support(db, count=1, sample_count=1)
    conn=await db._get_conn()
    await conn.execute("UPDATE posts SET status='scored',final_score=10")
    await conn.execute('INSERT INTO reviews(review_id,post_id,reviewer_id,score,week_id,submitted_at) VALUES (?,?,?,?,?,?)',
        ('future-review','sample-post-0',PEOPLE[1],10,'future',utc_iso(NOW+timedelta(days=3))))
    await conn.commit()
    data=await analytics.snapshot(db.db_path,str(GID),NOW-timedelta(days=14),NOW+timedelta(days=1))
    payload=analytics.analyze(data)
    assert payload['posts'][0]['reviews_before_cutoff']==1
    assert payload['posts'][0]['finalized_before_cutoff'] is False
    assert payload['members'][0]['posts_scored']==0
    assert payload['baseline_estimate']['score_regular_mc']==0


@pytest.mark.asyncio
async def test_score_band_boundaries_and_what_if_never_rewrites_sources(db):
    data, _ = await report(db,count=10)
    baseline = deepcopy(data)
    for score, expected in [(3.999,0),(4,1),(5.999,1),(6,3),(7.999,3),(8,5),(10,5)]:
        for r in data['reviews']:
            r['score']=score
        estimate = analytics.estimate(data, {'min_reviews':1})
        assert estimate['score_regular_mc']==expected*3
    assert data['config']==baseline['config']
    for r in data['reviews']:
        r['score']=8
    for p in data['posts']:
        p['required_reviews']=20
    payload=analytics.analyze(data)
    assert payload['baseline_estimate']['score_regular_mc']==0
    assert payload['estimate']['score_regular_mc']==15


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [{'bad':1},{'max_reviews_per_week':0},{'max_reviews_per_week':1.5},
    {'min_reviews':11},{'mc_review_reward':-1},{'mc_review_reward':float('inf')},{'mc_review_reward':True},
    {'showcase_threshold':11},{'total_review_days':15}])
async def test_calculator_validates_all_supported_bounds(db,overrides):
    data,_=await report(db,count=1,sample_count=0)
    with pytest.raises(ValueError):
        analytics.estimate(data,overrides)


@pytest.mark.asyncio
async def test_second_look_corrections_have_an_as_of_cutoff(db):
    await seed_support(db,count=1)
    item=await first_task(db)
    eid=await evaluate(db,item,score=6)
    request=await db.request_second_look(str(GID),item['user_id'],eid,'Please check my examples in the sample.')
    await db.resolve_second_look(str(GID),request,str(OWNER),FEEDBACK,8)
    conn=await db._get_conn()
    await conn.execute('UPDATE support_second_looks SET resolved_at=?',(utc_iso(NOW+timedelta(days=2)),))
    await conn.commit()
    data=await analytics.snapshot(db.db_path,str(GID),NOW-timedelta(days=14),NOW+timedelta(days=1))
    assert data['evaluations'][0]['score']==6
    later=await analytics.snapshot(db.db_path,str(GID),NOW-timedelta(days=14),NOW+timedelta(days=3))
    assert later['evaluations'][0]['score']==8 and later['evaluations'][0]['original_score']==6


@pytest.mark.asyncio
async def test_snapshot_row_budget_fails_visibly_not_partial(db,monkeypatch):
    await seed_support(db,count=10)
    monkeypatch.setattr(analytics,'ROW_BUDGET',5)
    with pytest.raises(ValueError,match='No partial report'):
        await analytics.snapshot(db.db_path,str(GID),NOW-timedelta(days=14),NOW+timedelta(days=1))


def test_csv_injection_bom_names_and_negative_numeric_values():
    payload={'participation':[{'discord_id':'100000000000000001','username':'  =HYPERLINK("x")','display_name':'رضا',
        'x_handle':'@person','balance':-1.5,'blank':None,'enabled':True}]}
    raw=analytics.participation_csv(payload)
    assert raw.startswith(b'\xef\xbb\xbf')
    row=next(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    assert row['username'].startswith("'") and row['x_handle']=="'@person"
    assert row['display_name']=='رضا' and row['balance']=='-1.5' and row['blank']=='' and row['enabled']=='1'


def xml_cell(root,address):
    return root.find(f".//{TAG('c')}[@r='{address}']")


@pytest.mark.asyncio
async def test_xlsx_numeric_dates_text_ids_formulas_extended_and_private_file(db,tmp_path):
    _,payload=await report(db,count=10,overrides={'mc_score_high':0,'max_reviews_per_week':2})
    payload['members'][0]['username']='=HYPERLINK("untrusted")'
    path=export_support_report(payload,tmp_path/'report.xlsx')
    assert os.stat(path).st_mode & 0o777 == 0o600
    with zipfile.ZipFile(path) as archive:
        roots=[ET.fromstring(archive.read(f'xl/worksheets/sheet{n}.xml')) for n in range(1,9)]
        members=roots[2]
        assert xml_cell(members,'A6').get('t')=='inlineStr'
        assert xml_cell(members,'B6').get('t')=='inlineStr' and xml_cell(members,'B6').find(TAG('f')) is None
        assert float(xml_cell(members,'E6').find(TAG('v')).text)>45000
        assert xml_cell(members,'N6').find(TAG('f')).text=='SUM(K6:M6)'
        calc=roots[1]
        assert "'Posts'!$K$6:$K$8" in xml_cell(calc,'B24').find(TAG('f')).text
        assert '$H$6:$H$16' in xml_cell(calc,'C25').find(TAG('f')).text
        assert float(xml_cell(calc,'B30').find(TAG('v')).text)==56
        assert float(xml_cell(calc,'C24').find(TAG('v')).text)==0
        assert xml_cell(calc,'C10').get('s')  # Authoring style retained for editable input.
        assert len(calc.findall(TAG('dataValidations'))) == 1
        assert roots[6].find(TAG('autoFilter')).get('ref')=='A5:I35'
        assert 'C' in xml_cell(roots[5],'I8').find(TAG('f')).text
        assert float(xml_cell(roots[5],'I8').find(TAG('v')).text)==0
        assert ET.fromstring(archive.read('xl/workbook.xml')).find(TAG('calcPr')).get('calcMode')=='auto'


@pytest.mark.asyncio
async def test_empty_xlsx_does_not_introduce_phantom_posts_or_dates(db,tmp_path):
    _,payload=await report(db,count=1,sample_count=0)
    path=export_support_report(payload,tmp_path/'empty.xlsx')
    with zipfile.ZipFile(path) as archive:
        posts=ET.fromstring(archive.read('xl/worksheets/sheet6.xml'))
        assert xml_cell(posts,'A6').find(TAG('v')) is None
        assert xml_cell(posts,'D6').find(TAG('v')) is None
        calc=ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
        assert xml_cell(calc,'B33').get('t')=='str' and xml_cell(calc,'B33').find(TAG('v')).text is None


@pytest.mark.asyncio
async def test_mean_is_not_rounded_across_reward_tier(db):
    data,_=await report(db,count=1,sample_count=1)
    source=data['reviews'][0]
    data['reviews']=[{**source,'review_id':str(n),'score':8 if n else 7} for n in range(2500)]
    estimated=analytics.estimate(data)
    assert estimated['score_regular_mc']==3
    assert estimated['showcase_golden_mc']==0


@pytest.mark.asyncio
async def test_old_assignments_completed_inside_short_window_are_included(db):
    await seed_support(db,count=1)
    conn=await db._get_conn()
    await conn.execute('UPDATE assignments SET assigned_at=?,completed_at=?',
        (utc_iso(NOW-timedelta(days=8)),utc_iso(NOW-timedelta(hours=1))))
    await conn.commit()
    data=await analytics.snapshot(db.db_path,str(GID),NOW-timedelta(days=1),NOW)
    assert analytics.estimate(data)['review_goal_mc']==2
    assert analytics.analyze(data)['reviewers'][0]['assignments_received']==0
