"""Read-only, time-bounded participation metrics and explainable setup estimates."""
import csv
import io
import math
import statistics
from collections import Counter, defaultdict
from datetime import timedelta

import aiosqlite

from config import Config, is_valid_content_url
from runtime_utils import parse_time, utc_iso

ROW_BUDGET = 50000


def average(values):
    values = [v for v in values if v is not None]
    # Round for display only. Rounding here can move a mean across an MC band.
    return statistics.mean(values) if values else None


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def percentile(values, fraction=.9):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def in_window(value, start, end):
    return value is not None and start <= parse_time(value) < end


async def snapshot(db_path, guild_id, start, end):
    """A separate SQLite read transaction cannot accidentally join an MC write."""
    start, end = parse_time(start), parse_time(end)
    previous = start - (end - start)
    gid = str(guild_id)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute('PRAGMA query_only=ON')
        await db.execute('PRAGMA busy_timeout=3000')
        await db.execute('BEGIN')
        remaining = ROW_BUDGET

        async def rows(sql, args=()):
            nonlocal remaining
            async with db.execute(sql + ' LIMIT ?', (*args, remaining + 1)) as cur:
                values = [dict(r) for r in await cur.fetchall()]
            if len(values) > remaining:
                raise ValueError('This window exceeds 50,000 source rows. Choose a shorter report window. No partial report was produced.')
            remaining -= len(values)
            return values

        config = await rows('SELECT * FROM guild_config WHERE guild_id=?', (gid,))
        support = await rows('SELECT * FROM support_config WHERE guild_id=?', (gid,))
        roster = await rows('SELECT * FROM support_roster WHERE guild_id=?', (gid,))
        users = await rows('SELECT * FROM users WHERE guild_id=?', (gid,))
        posts = await rows('''SELECT * FROM posts WHERE guild_id=? AND julianday(submitted_at)<julianday(?)
            AND (julianday(submitted_at)>=julianday(?) OR status IN ('pending','assigned'))''', (gid, utc_iso(end), utc_iso(previous)))
        reviews = await rows('''SELECT r.*,p.author_id,p.tweet_link,p.guild_id FROM reviews r JOIN posts p ON p.post_id=r.post_id
            WHERE p.guild_id=? AND julianday(r.submitted_at)<julianday(?) AND (julianday(r.submitted_at)>=julianday(?)
            OR julianday(p.submitted_at)>=julianday(?) OR p.status IN ('pending','assigned')
            OR p.post_id IN (SELECT post_id FROM reviews WHERE julianday(submitted_at)>=julianday(?)))''',
            (gid, utc_iso(end), utc_iso(previous), utc_iso(previous), utc_iso(previous)))
        assignments = await rows('''SELECT a.* FROM assignments a JOIN posts p ON p.post_id=a.post_id
            WHERE p.guild_id=? AND julianday(a.assigned_at)<julianday(?) AND
            (julianday(a.assigned_at)>=julianday(?) OR julianday(a.completed_at)>=julianday(?))''',
            (gid, utc_iso(end), utc_iso(previous), utc_iso(previous)))
        transactions = await rows('''SELECT * FROM mc_transactions WHERE guild_id=?
            AND julianday(timestamp)>=julianday(?) AND julianday(timestamp)<julianday(?)''', (gid, utc_iso(previous), utc_iso(end)))
        evaluations = await rows('''SELECT e.*,e.score original_score,
            CASE WHEN s.state='resolved' AND julianday(s.resolved_at)<julianday(?) THEN s.revised_score END revised_score,
            CASE WHEN s.state='resolved' AND julianday(s.resolved_at)<julianday(?) THEN s.resolved_at END revised_at
            FROM support_evaluations e LEFT JOIN support_second_looks s ON s.evaluation_id=e.id WHERE e.guild_id=?
            AND julianday(e.created_at)>=julianday(?) AND julianday(e.created_at)<julianday(?)''',
            (utc_iso(end), utc_iso(end), gid, utc_iso(previous), utc_iso(end)))
        for evaluation in evaluations:
            if evaluation['revised_score'] is not None:
                evaluation['score'] = evaluation['revised_score']
        oversight = await rows('''SELECT a.*,c.starts_at,c.ends_at FROM support_assignments a JOIN support_cycles c ON c.id=a.cycle_id
            WHERE a.guild_id=? AND julianday(c.starts_at)>=julianday(?) AND julianday(c.starts_at)<julianday(?)''', (gid, utc_iso(start), utc_iso(end)))
        activity = await rows('''SELECT user_id,COUNT(*) messages FROM activity_messages WHERE guild_id=?
            AND julianday(created_at)>=julianday(?) AND julianday(created_at)<julianday(?) GROUP BY user_id''', (gid, utc_iso(start), utc_iso(end)))
        events = await rows('''SELECT user_id,COUNT(*) events FROM activity_events WHERE guild_id=?
            AND julianday(created_at)>=julianday(?) AND julianday(created_at)<julianday(?) GROUP BY user_id''', (gid, utc_iso(start), utc_iso(end)))
        volunteers = await rows('SELECT * FROM support_volunteers WHERE guild_id=?', (gid,))
        skips = await rows('''SELECT s.* FROM support_skips s JOIN support_assignments a ON a.id=s.assignment_id
            WHERE a.guild_id=? AND julianday(s.created_at)>=julianday(?) AND julianday(s.created_at)<julianday(?)''', (gid, utc_iso(start), utc_iso(end)))
        await db.rollback()
    return dict(config=config[0] if config else {}, support=support[0] if support else {}, roster=roster, users=users,
                posts=posts, reviews=reviews, assignments=assignments, transactions=transactions, evaluations=evaluations,
                oversight=oversight, activity=activity, events=events, volunteers=volunteers, skips=skips,
                start=utc_iso(start), end=utc_iso(end), captured_at=utc_iso())


def estimate(data, overrides=None):
    """A what-if estimate, not a replay of payments or an automatic rules update."""
    cfg = dict(data['config'])
    allowed = {'max_reviews_per_week', 'max_submits_per_week', 'min_reviews', 'total_review_days',
               'mc_review_reward', 'mc_comment_bonus', 'mc_score_low', 'mc_score_medium', 'mc_score_high',
               'mc_submit_completion', 'mc_showcase_reward', 'showcase_threshold'}
    for key, value in (overrides or {}).items():
        if key not in allowed or isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError('Unknown or invalid calculator setting.')
        if key in {'max_reviews_per_week', 'max_submits_per_week'}:
            if int(value) != value or not 1 <= value <= 20:
                raise ValueError('Weekly limits must be integers from 1 to 20.')
        elif key == 'min_reviews':
            if int(value) != value or not 1 <= value <= 10:
                raise ValueError('Reviews per post must be an integer from 1 to 10.')
        elif key == 'total_review_days':
            if int(value) != value or not 1 <= value <= 14:
                raise ValueError('Review window must be an integer from 1 to 14.')
        elif not 0 <= value <= (10 if key == 'showcase_threshold' else 1000):
            raise ValueError('Reward must be 0-1000 MC. Showcase threshold must be 0-10.')
        cfg[key] = value
    start, end = parse_time(data['start']), parse_time(data['end'])
    posts = [p for p in data['posts'] if in_window(p['submitted_at'], start, end)]
    reviews = [r for r in data['reviews'] if in_window(r['submitted_at'], start, end)]
    scores = defaultdict(list)
    for r in data['reviews']:
        scores[r['post_id']].append(r['score'])
    finalized = [average(scores[p['post_id']]) for p in posts if len(scores[p['post_id']]) >=
                 (Config.get_min_reviews(cfg) if overrides and 'min_reviews' in overrides else int(p.get('required_reviews') or Config.get_min_reviews(cfg)))]
    assignments = [a for a in data['assignments'] if a.get('completed_at') and in_window(a['completed_at'], start, end) and a['status'] == 'completed']
    goals = Counter((a['reviewer_id'], a['week_id']) for a in assignments)
    review_groups = defaultdict(list)
    for r in reviews:
        review_groups[(r['reviewer_id'], r['week_id'])].append(r)
    submit_groups = Counter((p['author_id'], p['week_id']) for p in posts)
    max_reviews, max_submits = Config.get_max_reviews(cfg), Config.get_max_submits(cfg)
    goals_met = [key for key, count in goals.items() if count >= max_reviews]
    comment_goals = sum(bool(review_groups[key]) and all(is_valid_content_url(r['twitter_comment'] or '') for r in review_groups[key]) for key in goals_met)
    result = {'score_regular_mc': sum(Config.calculate_mc_from_score(s, cfg) for s in finalized),
              'showcase_golden_mc': sum(Config.get_showcase_reward(cfg) for s in finalized if s >= Config.get_showcase_threshold(cfg)),
              'review_goal_mc': len(goals_met) * Config.get_review_reward(cfg),
              'comment_bonus_mc': comment_goals * Config.get_comment_bonus(cfg),
              'submission_goal_mc': sum(n >= max_submits for n in submit_groups.values()) * Config.get_submit_completion_reward(cfg),
              'scored_posts': len(finalized), 'reviewer_weeks_at_goal': len(goals_met), 'comment_eligible_weeks': comment_goals,
              'submission_weeks_at_goal': sum(n >= max_submits for n in submit_groups.values()), 'config': cfg}
    result['estimated_regular_mc'] = sum(result[k] for k in ('score_regular_mc', 'review_goal_mc', 'comment_bonus_mc', 'submission_goal_mc'))
    result['estimated_total_mc'] = result['estimated_regular_mc'] + result['showcase_golden_mc']
    return result


def analyze(data, overrides=None):
    start, end = parse_time(data['start']), parse_time(data['end'])
    previous = start - (end - start)
    cfg = data['config']
    roster = defaultdict(set)
    names = {u['user_id']: u for u in data['users']}
    for p in data['roster']:
        if p['present']:
            roster[p['kind']].add(p['user_id'])
            names[p['user_id']] = {**names.get(p['user_id'], {}), **p}
    posts = [p for p in data['posts'] if in_window(p['submitted_at'], start, end)]
    reviews = [r for r in data['reviews'] if in_window(r['submitted_at'], start, end)]
    assignments = [a for a in data['assignments'] if in_window(a['assigned_at'], start, end)]
    txs = [t for t in data['transactions'] if in_window(t['timestamp'], start, end)]
    evaluations = [e for e in data['evaluations'] if in_window(e['created_at'], start, end)]
    by_author, by_reviewer, by_assignee, by_transaction, by_rating, by_post = [defaultdict(list) for _ in range(6)]
    for p in posts:
        by_author[p['author_id']].append(p)
    for r in data['reviews']:
        by_post[r['post_id']].append(r)
    for r in reviews:
        by_reviewer[r['reviewer_id']].append(r)
    for a in assignments:
        by_assignee[a['reviewer_id']].append(a)
    for t in txs:
        by_transaction[t['user_id']].append(t)
    for e in evaluations:
        by_rating[(e['user_id'], e['kind'])].append(e)
    message_counts = {r['user_id']: r['messages'] for r in data['activity']}
    event_counts = {r['user_id']: r['events'] for r in data['events']}
    people = set(names) | set(by_author) | set(by_reviewer) | set(by_assignee) | set(by_transaction) | {e['user_id'] for e in evaluations}
    if len(people) > 15000:
        raise ValueError('Participant inventory exceeds the 15,000-person reporting budget.')

    def ratings(uid, kind):
        found = by_rating[(uid, kind)]
        return average([r['score'] for r in found if not r['limited_evidence']]), average([r['score'] for r in found if r['limited_evidence']]), len(found)

    def identity(uid):
        person = names.get(uid, {})
        return {'discord_id': uid, 'username': person.get('username') or uid,
                'display_name': person.get('display_name') or person.get('username') or uid,
                'x_handle': person.get('twitter_username') or '', 'joined_at': person.get('joined_at'),
                'current_reviewer': uid in roster['reviewer'], 'current_member': uid in roster['member']}

    member_rows, reviewer_rows, csv_rows = [], [], []
    all_response_hours, all_mature, all_completed = [], 0, 0
    for uid in sorted(people, key=lambda u: ((names.get(u, {}).get('display_name') or '').casefold(), u)):
        person = names.get(uid, {})
        mine_posts, mine_reviews, mine_assignments = by_author[uid], by_reviewer[uid], by_assignee[uid]
        scored = [(p, average([r['score'] for r in by_post[p['post_id']]])) for p in mine_posts
                  if len(by_post[p['post_id']]) >= int(p.get('required_reviews') or Config.get_min_reviews(cfg))]
        mature = [a for a in mine_assignments if parse_time(a['due_date']) < end and a['status'] not in ('reassigned', 'removed')]
        completed = [a for a in mature if a['completed_at'] and parse_time(a['completed_at']) < end]
        responses = [max(0, (parse_time(a['completed_at']) - parse_time(a['assigned_at'])).total_seconds() / 3600)
                     for a in mine_assignments if a['completed_at'] and parse_time(a['completed_at']) < end]
        all_mature += len(mature)
        all_completed += len(completed)
        all_response_hours.extend(responses)
        rating, limited, rating_count = ratings(uid, 'member')
        reviewer_rating, reviewer_limited, reviewer_rating_count = ratings(uid, 'reviewer')
        balances = {f'{k}_mc': float(person.get(f'mc_{k}') or 0) for k in ('regular', 'golden', 'assignment')}
        earnings = sum(t['amount'] for t in by_transaction[uid] if t['amount'] > 0)
        deductions = -sum(t['amount'] for t in by_transaction[uid] if t['amount'] < 0)
        base = identity(uid)
        state = 'Participated' if mine_posts or mine_reviews else 'No recorded post/review participation'
        if person.get('joined_at') and parse_time(person['joined_at']) > start and not mine_posts and not mine_reviews:
            state = 'New member; partial window'
        member = {**base, 'posts_submitted': len(mine_posts), 'posts_scored': len(scored),
                  'average_post_score': average([s for _, s in scored]),
                  'posts_waiting_for_reviews': len(mine_posts) - len(scored),
                  'post_comment_links': sum(bool(r['twitter_comment']) for p in mine_posts for r in by_post[p['post_id']]),
                  'moderator_score': rating, 'limited_evidence_score': limited, 'evaluations': rating_count,
                  'indexed_messages': message_counts.get(uid, 0), 'observed_bot_actions_reactions': event_counts.get(uid, 0),
                  **balances, 'total_mc': sum(balances.values()), 'mc_earned_in_window': earnings,
                  'mc_deducted_in_window': deductions, 'participation': state}
        repeated = Counter(' '.join((r['summary'] or '').casefold().split()) for r in mine_reviews)
        deviation = []
        for review in mine_reviews:
            peers = [r['score'] for r in by_post[review['post_id']] if r['reviewer_id'] != uid]
            if len(peers) >= 2:
                deviation.append(abs(review['score'] - statistics.mean(peers)))
        reviewer = {**base, 'reviews_submitted': len(mine_reviews), 'assignments_received': len(mine_assignments),
                    'mature_opportunities': len(mature), 'completed_mature_opportunities': len(completed),
                    'opportunity_completion_rate': ratio(len(completed), len(mature)),
                    'reassigned_removed': sum(a['status'] in ('reassigned', 'removed') for a in mine_assignments),
                    'pending_future_due': sum(parse_time(a['due_date']) >= end and not a['completed_at'] for a in mine_assignments),
                    'average_response_hours': average(responses), 'average_score_given': average([r['score'] for r in mine_reviews]),
                    'comment_links_recorded': sum(bool(r['twitter_comment']) for r in mine_reviews),
                    'mean_feedback_characters': average([len((r['summary'] or '').strip()) for r in mine_reviews]),
                    'repeated_feedback_groups': sum(bool(text) and n >= 3 for text, n in repeated.items()),
                    'peer_score_difference': average(deviation), 'peer_comparisons': len(deviation),
                    'moderator_review_score': reviewer_rating, 'limited_review_score': reviewer_limited,
                    'review_evaluations': reviewer_rating_count,
                    'review_opportunity_state': 'No review opportunities observed' if not mine_assignments and not mine_reviews else 'Recorded opportunities'}
        if uid in roster['member'] or mine_posts or by_transaction[uid] or by_rating[(uid, 'member')]:
            member_rows.append(member)
        if uid in roster['reviewer'] or mine_reviews or mine_assignments or by_rating[(uid, 'reviewer')]:
            reviewer_rows.append(reviewer)
        csv_rows.append({**member, **{k: v for k, v in reviewer.items() if k not in base}, 'window_start_utc': data['start'], 'window_end_exclusive_utc': data['end']})

    weeks = (end - start).total_seconds() / (7 * 86400)
    completion_rate = ratio(all_completed, all_mature)
    current_mature = sum(r['mature_opportunities'] for r in reviewer_rows if r['current_reviewer'])
    current_completed = sum(r['completed_mature_opportunities'] for r in reviewer_rows if r['current_reviewer'])
    calibration_rate = ratio(current_completed, current_mature)
    active_reviewers = sum(bool(by_reviewer[uid]) for uid in roster['reviewer'])
    active_authors = sum(bool(records) for records in by_author.values())
    posts_per_week = len(posts) / weeks
    required = Config.get_min_reviews(cfg)
    capacity = len(roster['reviewer']) * Config.get_max_reviews(cfg)
    observed_capacity = active_reviewers * Config.get_max_reviews(cfg) * calibration_rate if calibration_rate is not None else None
    needed = posts_per_week * required
    p90 = percentile(all_response_hours)
    recommendations = []
    if current_mature >= 10 and active_reviewers and calibration_rate:
        needed_limit = math.ceil(needed / (active_reviewers * calibration_rate))
        gentle_limit = max(1, min(20, max(Config.get_max_reviews(cfg) - 2, min(Config.get_max_reviews(cfg) + 2, needed_limit))))
        recommendations.append({'setting': 'max_reviews_per_week', 'current': Config.get_max_reviews(cfg), 'suggested': gentle_limit,
                                'reason': f'{needed:.1f} reviews/week demanded; {active_reviewers} active current-role reviewers; {calibration_rate:.1%} current-role mature completion. Change bounded to two.'})
        if active_authors:
            suggested_submits = max(1, min(20, math.floor(observed_capacity / (active_authors * required))))
            suggested_submits = max(Config.get_max_submits(cfg)-1, min(Config.get_max_submits(cfg)+1, suggested_submits))
            recommendations.append({'setting': 'max_submits_per_week', 'current': Config.get_max_submits(cfg),
                                    'suggested': suggested_submits,
                                    'reason': 'Capacity estimate using active authors and current reviews/post. Change bounded to one. Prefer voluntary help before restricting access.'})
    else:
        recommendations.append({'setting': 'workload', 'current': None, 'suggested': None,
                                'reason': 'Need at least 10 mature assignments and an observed completion rate before recommending workload changes.'})
    if len(all_response_hours) >= 10:
        recommendations.append({'setting': 'total_review_days', 'current': Config.get_review_window(cfg),
                                'suggested': max(Config.get_review_window(cfg), min(14, max(3, math.ceil(p90 / 24)))),
                                'reason': f'90th percentile response: {p90:.1f} hours. This recommendation does not shorten deadlines.'})
    cap = int(data['support'].get('weekly_cap', 10))
    available_mods = [m for m in data['volunteers'] if m['available'] and m['moderator_id'] in roster['moderator']]
    reviewer_slots = sum(min(cap, m['reviewer_capacity']) for m in available_mods)
    member_slots = sum(min(cap, m['member_capacity']) for m in available_mods)
    recommendations.append({'setting': 'reviewer_moderators_needed', 'current': len(available_mods),
                            'suggested': math.ceil(len(roster['reviewer']) / cap),
                            'reason': f'{len(roster["reviewer"])} reviewers; cap {cap}; volunteered reviewer slots {reviewer_slots}. Skips never force another moderator above capacity.'})
    mod_rows = []
    for mod in sorted(roster['moderator'] | {e['moderator_id'] for e in evaluations}):
        work = [a for a in data['oversight'] if a['moderator_id'] == mod]
        ratings_for_mod = [e for e in evaluations if e['moderator_id'] == mod]
        volunteer = next((m for m in data['volunteers'] if m['moderator_id'] == mod), {})
        mod_rows.append({**identity(mod), 'reviewer_capacity': volunteer.get('reviewer_capacity', 0), 'member_capacity': volunteer.get('member_capacity', 0),
                         'available': bool(volunteer.get('available')), 'assigned_people': len(work), 'evaluated_people': len(ratings_for_mod),
                         'skipped_people': sum(s['moderator_id'] == mod for s in data['skips']),
                         'average_score_given': average([e['score'] for e in ratings_for_mod]),
                         'limited_evidence_evaluations': sum(e['limited_evidence'] for e in ratings_for_mod)})
    previous_posts = sum(in_window(p['submitted_at'], previous, start) for p in data['posts'])
    previous_reviews = sum(in_window(r['submitted_at'], previous, start) for r in data['reviews'])
    paid_regular = sum(t['amount'] for t in txs if t['amount'] > 0 and t['mc_type'] == 'regular')
    paid_golden = sum(t['amount'] for t in txs if t['amount'] > 0 and t['mc_type'] == 'golden')
    paid_assignment = sum(t['amount'] for t in txs if t['amount'] > 0 and t['mc_type'] == 'assignment')
    scenario = {**(overrides or {})}
    scenario.setdefault('min_reviews', Config.get_min_reviews(cfg))
    estimate_result = estimate(data, scenario)
    summary = {'posts': len(posts), 'previous_posts': previous_posts, 'reviews': len(reviews), 'previous_reviews': previous_reviews,
               'current_reviewers': len(roster['reviewer']), 'current_members': len(roster['member']), 'active_reviewers': active_reviewers,
               'mature_opportunities': all_mature, 'completed_mature_opportunities': all_completed, 'mature_completion_rate': completion_rate,
               'current_role_completion_rate': calibration_rate,
               'theoretical_reviews_per_week': capacity, 'observed_capacity_per_week': observed_capacity, 'demand_reviews_per_week': needed,
               'posts_per_week': posts_per_week, 'p90_response_hours': p90, 'current_reviewer_slots': reviewer_slots, 'current_member_slots': member_slots,
               'regular_mc_paid': paid_regular, 'golden_mc_paid': paid_golden, 'assignment_mc_paid': paid_assignment,
               'moderator_evaluations': len(evaluations), 'full_evidence_evaluations': sum(not e['limited_evidence'] for e in evaluations),
               'roster_refreshed_at': data['support'].get('roster_at'), 'outcomes_reconstructed_before_end': True}
    assignment_goals = Counter((a['reviewer_id'], a['week_id']) for a in data['assignments']
                               if a['status'] == 'completed' and a.get('completed_at') and in_window(a['completed_at'], start, end))
    review_goals = defaultdict(list)
    for review in reviews:
        review_goals[(review['reviewer_id'], review['week_id'])].append(review)
    submit_goals = Counter((p['author_id'], p['week_id']) for p in posts)
    weekly_goals = [{'discord_id': uid, 'week_id': week, 'completed_assignments': assignment_goals[(uid, week)],
                     'all_comment_links': bool(review_goals[(uid, week)]) and all(is_valid_content_url(r['twitter_comment'] or '') for r in review_goals[(uid, week)]),
                     'submitted_posts': submit_goals[(uid, week)]}
                    for uid, week in sorted(set(assignment_goals) | set(review_goals) | set(submit_goals))]
    post_inputs = [{**p, 'reviews_before_cutoff': len(by_post[p['post_id']]),
                    'observed_mean_score': average([r['score'] for r in by_post[p['post_id']]]),
                    'finalized_before_cutoff': len(by_post[p['post_id']]) >= int(p.get('required_reviews') or Config.get_min_reviews(cfg))}
                   for p in posts]
    return {'start': data['start'], 'end': data['end'], 'captured_at': data['captured_at'], 'summary': summary,
            'members': member_rows, 'reviewers': reviewer_rows, 'moderators': mod_rows, 'participation': csv_rows,
            'posts': post_inputs, 'reviews': reviews, 'evaluations': evaluations, 'recommendations': recommendations,
            'estimate': estimate_result, 'baseline_estimate': estimate(data), 'weekly_goals': weekly_goals,
            'definitions': 'UTC half-open window. Legacy timezone-free timestamps are interpreted as UTC. Current roster/balances are as of capture. Message counts are indexed only. MC estimates use current rules, not historical rate reconstruction. Moderator scores are private and do not award or remove MC.'}


def safe_csv_value(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def participation_csv(payload):
    rows = payload['participation']
    output = io.StringIO(newline='')
    columns = list(rows[0]) if rows else ['discord_id', 'username', 'window_start_utc', 'window_end_exclusive_utc']
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows({key: safe_csv_value(value) for key, value in row.items()} for row in rows)
    # UTF-8 BOM makes names readable in Excel on Windows as well as other CSV tools.
    return output.getvalue().encode('utf-8-sig')
