"""Private, additive review support. This module never changes MC or guild rules."""
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from runtime_utils import parse_time, utc_iso

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS support_config (
        guild_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
        reviewer_role_id TEXT, member_role_id TEXT, moderator_role_id TEXT,
        weekly_cap INTEGER NOT NULL DEFAULT 10, sample_size INTEGER NOT NULL DEFAULT 3,
        minimum_samples INTEGER NOT NULL DEFAULT 3, anchor_at TEXT, next_report_at TEXT,
        roster_at TEXT, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS support_roster (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, kind TEXT NOT NULL,
        username TEXT NOT NULL, display_name TEXT NOT NULL, joined_at TEXT,
        present INTEGER NOT NULL DEFAULT 1, seen_at TEXT NOT NULL,
        PRIMARY KEY(guild_id,user_id,kind))""",
    """CREATE TABLE IF NOT EXISTS support_volunteers (
        guild_id TEXT NOT NULL, moderator_id TEXT NOT NULL,
        reviewer_capacity INTEGER NOT NULL DEFAULT 10, member_capacity INTEGER NOT NULL DEFAULT 0,
        available INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
        PRIMARY KEY(guild_id,moderator_id))""",
    """CREATE TABLE IF NOT EXISTS support_cycles (
        id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, starts_at TEXT NOT NULL,
        ends_at TEXT NOT NULL, seed TEXT NOT NULL, UNIQUE(guild_id,starts_at))""",
    """CREATE TABLE IF NOT EXISTS support_assignments (
        id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, guild_id TEXT NOT NULL,
        user_id TEXT NOT NULL, kind TEXT NOT NULL, moderator_id TEXT,
        state TEXT NOT NULL DEFAULT 'queued', samples_json TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(cycle_id,user_id,kind))""",
    """CREATE TABLE IF NOT EXISTS support_skips (
        assignment_id TEXT NOT NULL, moderator_id TEXT NOT NULL, reason TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(assignment_id,moderator_id))""",
    """CREATE TABLE IF NOT EXISTS support_evaluations (
        id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL UNIQUE, guild_id TEXT NOT NULL,
        user_id TEXT NOT NULL, kind TEXT NOT NULL, moderator_id TEXT NOT NULL,
        score INTEGER CHECK(score BETWEEN 1 AND 10), feedback TEXT NOT NULL,
        checked_ids_json TEXT NOT NULL, sample_count INTEGER NOT NULL,
        limited_evidence INTEGER NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS support_messages (
        id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, sender_id TEXT NOT NULL,
        recipient_id TEXT NOT NULL, evaluation_id TEXT NOT NULL, body TEXT NOT NULL,
        read_at TEXT, dm_state TEXT NOT NULL DEFAULT 'pending', dm_attempts INTEGER NOT NULL DEFAULT 0,
        dm_next_at TEXT NOT NULL, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS support_preferences (
        guild_id TEXT NOT NULL, user_id TEXT NOT NULL, dm_enabled INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(guild_id,user_id))""",
    """CREATE TABLE IF NOT EXISTS support_second_looks (
        id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, evaluation_id TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL, reason TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open',
        resolution TEXT, resolved_by TEXT, created_at TEXT NOT NULL, resolved_at TEXT,
        revised_score INTEGER CHECK(revised_score BETWEEN 1 AND 10))""",
    """CREATE TABLE IF NOT EXISTS support_report_jobs (
        id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'queued', requested_by TEXT NOT NULL,
        payload_json TEXT, output_path TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, UNIQUE(guild_id,starts_at,ends_at))""",
    'CREATE INDEX IF NOT EXISTS idx_support_work ON support_assignments(guild_id,cycle_id,moderator_id,state)',
    'CREATE INDEX IF NOT EXISTS idx_support_inbox ON support_messages(guild_id,recipient_id,created_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_support_dm ON support_messages(dm_state,dm_next_at)',
    'CREATE INDEX IF NOT EXISTS idx_support_ratings ON support_evaluations(guild_id,user_id,created_at)',
    'CREATE INDEX IF NOT EXISTS idx_support_reports ON support_report_jobs(state,created_at)',
)


def week_window(now=None):
    """Saturday midnight, matching the deployed community's weekly cycle."""
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Tehran'))
    start = (local - timedelta(days=(local.weekday() - 5) % 7)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=7)).astimezone(timezone.utc)


def tie(seed, value):
    return hashlib.sha256(f'{seed}:{value}'.encode()).hexdigest()


class ReviewSupportDB:
    async def init_support(self):
        db = await self._get_conn()
        async with self._lock:
            try:
                for statement in SCHEMA:
                    await db.execute(statement)
                fields = {r[1] for r in await (await db.execute('PRAGMA table_info(support_second_looks)')).fetchall()}
                if 'revised_score' not in fields:
                    await db.execute('ALTER TABLE support_second_looks ADD COLUMN revised_score INTEGER CHECK(revised_score BETWEEN 1 AND 10)')
                await db.execute("UPDATE support_report_jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,error=CASE WHEN attempts>=3 THEN 'Interrupted three times. Check server health before a new report.' ELSE error END WHERE state='running'")
                # A process died during an optional DM. The inbox is already durable.
                await db.execute("UPDATE support_messages SET dm_state='pending' WHERE dm_state='sending'")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def support_settings(self, guild_id):
        db = await self._get_conn()
        async with self._lock:
            async with db.execute('SELECT * FROM support_config WHERE guild_id=?', (str(guild_id),)) as cur:
                row = await cur.fetchone()
            return dict(row) if row else {'guild_id': str(guild_id), 'enabled': 0, 'weekly_cap': 10, 'sample_size': 3, 'minimum_samples': 3}

    async def configure_support(self, guild_id, *, enabled, reviewer_role_id, moderator_role_id,
                                member_role_id=None, weekly_cap=10, sample_size=3, now=None):
        if not reviewer_role_id or not moderator_role_id:
            raise ValueError('Select reviewer and moderator roles first.')
        if not 1 <= int(weekly_cap) <= 50 or not 1 <= int(sample_size) <= 5:
            raise ValueError('Weekly capacity: 1-50. Evidence samples: 1-5.')
        now = parse_time(now or utc_iso())
        db = await self._get_conn()
        async with self._lock:
            try:
                await self._configure_support_locked(db, guild_id, dict(enabled=int(enabled), reviewer_role_id=reviewer_role_id,
                    moderator_role_id=moderator_role_id, member_role_id=member_role_id, weekly_cap=weekly_cap, sample_size=sample_size), now=now)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def _configure_support_locked(self, db, guild_id, changes, *, now):
        """Used inside a caller-owned transaction; never calls Discord or commits."""
        row = await (await db.execute('SELECT * FROM support_config WHERE guild_id=?', (str(guild_id),))).fetchone()
        old = dict(row) if row else {}
        now = parse_time(now)
        anchor = old.get('anchor_at') or utc_iso(now)
        next_at = old.get('next_report_at') or utc_iso(now + timedelta(days=14))
        await db.execute('''INSERT INTO support_config
                (guild_id,enabled,reviewer_role_id,member_role_id,moderator_role_id,weekly_cap,sample_size,minimum_samples,anchor_at,next_report_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET
                enabled=excluded.enabled,reviewer_role_id=excluded.reviewer_role_id,member_role_id=excluded.member_role_id,
                moderator_role_id=excluded.moderator_role_id,weekly_cap=excluded.weekly_cap,sample_size=excluded.sample_size,
                minimum_samples=excluded.minimum_samples,
                roster_at=CASE WHEN support_config.reviewer_role_id IS NOT excluded.reviewer_role_id OR
                support_config.member_role_id IS NOT excluded.member_role_id OR support_config.moderator_role_id IS NOT excluded.moderator_role_id
                THEN NULL ELSE support_config.roster_at END,updated_at=excluded.updated_at''',
                (str(guild_id), int(changes['enabled']), str(changes['reviewer_role_id']),
                 str(changes['member_role_id']) if changes['member_role_id'] else None,
                 str(changes['moderator_role_id']), int(changes['weekly_cap']), int(changes['sample_size']),
                 int(changes['sample_size']), anchor, next_at, utc_iso(now)))

    async def save_support_roster(self, guild_id, roster, *, now=None):
        """Only called after a successful complete Discord member inventory."""
        if len(roster) > 15000:
            raise ValueError('Selected-role inventory exceeds the 15,000-row processing budget.')
        db = await self._get_conn()
        at = utc_iso(now)
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                await db.execute('UPDATE support_roster SET present=0 WHERE guild_id=?', (str(guild_id),))
                await db.executemany('''INSERT INTO support_roster
                    (guild_id,user_id,kind,username,display_name,joined_at,present,seen_at) VALUES (?,?,?,?,?,?,1,?)
                    ON CONFLICT(guild_id,user_id,kind) DO UPDATE SET username=excluded.username,
                    display_name=excluded.display_name,joined_at=excluded.joined_at,present=1,seen_at=excluded.seen_at''',
                    [(str(guild_id), str(p['id']), p['kind'], p['username'], p['display_name'], p.get('joined_at'), at) for p in roster])
                await db.execute('UPDATE support_config SET roster_at=? WHERE guild_id=?', (at, str(guild_id)))
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def support_volunteer(self, guild_id, moderator_id, *, available, reviewer_capacity=10, member_capacity=0):
        settings = await self.support_settings(guild_id)
        cap = settings['weekly_cap']
        if not 0 <= int(reviewer_capacity) <= cap or not 0 <= int(member_capacity) <= cap:
            raise ValueError(f'Each weekly capacity must be between 0 and {cap}.')
        db = await self._get_conn()
        async with self._lock:
            await db.execute('''INSERT INTO support_volunteers VALUES (?,?,?,?,?,?)
                ON CONFLICT(guild_id,moderator_id) DO UPDATE SET reviewer_capacity=excluded.reviewer_capacity,
                member_capacity=excluded.member_capacity,available=excluded.available,updated_at=excluded.updated_at''',
                (str(guild_id), str(moderator_id), int(reviewer_capacity), int(member_capacity), int(available), utc_iso()))
            await db.commit()

    async def _support_fill(self, db, cycle, settings):
        """One short write transaction. No REST or file work under the MC lock."""
        gid = cycle['guild_id']
        rows = await (await db.execute('''SELECT v.* FROM support_volunteers v JOIN support_roster r
            ON r.guild_id=v.guild_id AND r.user_id=v.moderator_id AND r.kind='moderator'
            WHERE v.guild_id=? AND v.available=1 AND r.present=1''', (gid,))).fetchall()
        volunteers = [dict(r) for r in rows]
        live_targets = await (await db.execute("SELECT user_id,kind FROM support_roster WHERE guild_id=? AND present=1", (gid,))).fetchall()
        live = {(r['user_id'], r['kind']) for r in live_targets}
        work = await (await db.execute('SELECT * FROM support_assignments WHERE cycle_id=?', (cycle['id'],))).fetchall()
        load = {}
        available_ids = {m['moderator_id'] for m in volunteers}
        for row in work:
            if row['state'] == 'pending' and (row['moderator_id'] not in available_ids or (row['user_id'], row['kind']) not in live):
                new_state = 'queued' if (row['user_id'], row['kind']) in live else 'withdrawn'
                await db.execute('UPDATE support_assignments SET moderator_id=NULL,state=?,updated_at=? WHERE id=?', (new_state, utc_iso(), row['id']))
            elif row['state'] in ('pending', 'completed'):
                key = (row['moderator_id'], row['kind'])
                load[key] = load.get(key, 0) + 1
        queued = await (await db.execute("SELECT * FROM support_assignments WHERE cycle_id=? AND state='queued' ORDER BY created_at,id", (cycle['id'],))).fetchall()
        skips = await (await db.execute('SELECT s.assignment_id,s.moderator_id FROM support_skips s JOIN support_assignments a ON a.id=s.assignment_id WHERE a.cycle_id=?', (cycle['id'],))).fetchall()
        skip_map = {}
        for skip in skips:
            skip_map.setdefault(skip['assignment_id'], set()).add(skip['moderator_id'])
        history = await (await db.execute('''SELECT e.user_id,e.kind,e.moderator_id FROM support_evaluations e JOIN
            (SELECT user_id,kind,MAX(created_at) at FROM support_evaluations WHERE guild_id=? GROUP BY user_id,kind) h
            ON e.user_id=h.user_id AND e.kind=h.kind AND e.created_at=h.at WHERE e.guild_id=?''', (gid,gid))).fetchall()
        previous_mod = {(r['user_id'], r['kind']): r['moderator_id'] for r in history}
        total = 0
        for item in queued:
            if (item['user_id'], item['kind']) not in live:
                await db.execute("UPDATE support_assignments SET state='withdrawn',updated_at=? WHERE id=?", (utc_iso(), item['id']))
                continue
            skipped = skip_map.get(item['id'], set())
            candidates = [m for m in volunteers if m['moderator_id'] != item['user_id'] and m['moderator_id'] not in skipped
                          and load.get((m['moderator_id'], item['kind']), 0) < min(settings['weekly_cap'], m[item['kind'] + '_capacity'])]
            if not candidates:
                continue
            previous = previous_mod.get((item['user_id'], item['kind']))
            alternatives = [m for m in candidates if m['moderator_id'] != previous]
            if alternatives:
                candidates = alternatives
            candidates.sort(key=lambda m: (load.get((m['moderator_id'], item['kind']), 0),
                                            tie(cycle['seed'], item['id'] + m['moderator_id'])))
            selected = candidates[0]['moderator_id']
            await db.execute("UPDATE support_assignments SET moderator_id=?,state='pending',updated_at=? WHERE id=?", (selected, utc_iso(), item['id']))
            load[(selected, item['kind'])] = load.get((selected, item['kind']), 0) + 1
            total += 1
        return total

    async def start_support_cycle(self, guild_id, *, now=None):
        now = parse_time(now or utc_iso())
        start, end = week_window(now)
        settings = await self.support_settings(guild_id)
        if not settings['enabled'] or not settings.get('roster_at'):
            return None
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                row = await (await db.execute('SELECT * FROM support_cycles WHERE guild_id=? AND starts_at=?', (str(guild_id), utc_iso(start)))).fetchone()
                if row:
                    cycle = dict(row)
                else:
                    cycle = {'id': str(uuid.uuid4()), 'guild_id': str(guild_id), 'starts_at': utc_iso(start), 'ends_at': utc_iso(end), 'seed': secrets.token_hex(16)}
                    await db.execute('INSERT INTO support_cycles VALUES (?,?,?,?,?)', tuple(cycle.values()))
                    await db.execute("UPDATE support_assignments SET state='expired',updated_at=? WHERE guild_id=? AND state IN ('queued','pending')", (utc_iso(now), str(guild_id)))
                # New volunteers/targets join the existing cycle without duplicating work.
                people = await (await db.execute("SELECT * FROM support_roster WHERE guild_id=? AND present=1 AND kind IN ('reviewer','member')", (str(guild_id),))).fetchall()
                history = await (await db.execute('SELECT user_id,kind,MAX(created_at) last_at FROM support_evaluations WHERE guild_id=? GROUP BY user_id,kind', (str(guild_id),))).fetchall()
                last = {(r['user_id'], r['kind']): r['last_at'] for r in history}
                people = sorted(people, key=lambda p: (last.get((p['user_id'], p['kind']), ''), tie(cycle['seed'], p['user_id'] + p['kind'])))
                # Persist randomized evidence. UI refresh never redraws a flattering sample.
                existing = {(r['user_id'], r['kind']) for r in await (await db.execute(
                    'SELECT user_id,kind FROM support_assignments WHERE cycle_id=?', (cycle['id'],))).fetchall()}
                added = 0
                for index, person in enumerate(people):
                    if (person['user_id'], person['kind']) in existing:
                        continue
                    if added >= 100:
                        break  # Continue next scheduler tick; never monopolize the MC write lock.
                    if person['kind'] == 'reviewer':
                        sql = '''SELECT r.review_id id,r.summary text,r.score,r.twitter_comment comment,p.tweet_link url,
                            r.submitted_at at FROM reviews r JOIN posts p ON p.post_id=r.post_id
                            WHERE p.guild_id=? AND r.reviewer_id=? AND julianday(r.submitted_at)>=julianday(?)
                            AND julianday(r.submitted_at)<julianday(?) ORDER BY r.submitted_at DESC LIMIT 500'''
                    else:
                        sql = '''SELECT post_id id,tweet_link url,final_score score,status text,submitted_at at FROM posts
                            WHERE guild_id=? AND author_id=? AND julianday(submitted_at)>=julianday(?)
                            AND julianday(submitted_at)<julianday(?) ORDER BY submitted_at DESC LIMIT 500'''
                    samples = [dict(r) for r in await (await db.execute(sql, (str(guild_id), person['user_id'], utc_iso(start - timedelta(days=7)), utc_iso(start)))).fetchall()]
                    samples.sort(key=lambda r: tie(cycle['seed'], person['user_id'] + r['id']))
                    samples = samples[:settings['sample_size']]
                    # Stable ordering preserves least-recently-supported priority across restarts.
                    created = utc_iso(start + timedelta(microseconds=index))
                    await db.execute('''INSERT INTO support_assignments
                        (id,cycle_id,guild_id,user_id,kind,samples_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)''',
                        (str(uuid.uuid4()), cycle['id'], str(guild_id), person['user_id'], person['kind'], json.dumps(samples), created, utc_iso(now)))
                    added += 1
                await self._support_fill(db, cycle, settings)
                await db.commit()
                return cycle
            except BaseException:
                await db.rollback()
                raise

    async def support_work(self, guild_id, moderator_id=None, *, now=None):
        start, _ = week_window(parse_time(now or utc_iso()))
        db = await self._get_conn()
        where = ' AND a.moderator_id=?' if moderator_id is not None else ''
        args = [str(guild_id), utc_iso(start)] + ([str(moderator_id)] if moderator_id is not None else [])
        async with db.execute('''SELECT a.*,r.username,r.display_name,e.score FROM support_assignments a
            JOIN support_cycles c ON c.id=a.cycle_id LEFT JOIN support_roster r
            ON r.guild_id=a.guild_id AND r.user_id=a.user_id AND r.kind=a.kind
            LEFT JOIN support_evaluations e ON e.assignment_id=a.id
            WHERE a.guild_id=? AND c.starts_at=?''' + where + ' ORDER BY a.created_at,a.id', args) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def support_assignment(self, guild_id, assignment_id):
        db = await self._get_conn()
        async with db.execute('SELECT a.*,c.ends_at FROM support_assignments a JOIN support_cycles c ON c.id=a.cycle_id WHERE a.guild_id=? AND a.id=?', (str(guild_id), assignment_id)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def skip_support(self, guild_id, assignment_id, moderator_id, reason='Capacity or availability', *, now=None):
        settings = await self.support_settings(guild_id)
        now = parse_time(now or utc_iso())
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                item = await self.support_assignment(guild_id, assignment_id)
                if not settings['enabled'] or not settings.get('roster_at') or not item or item['moderator_id'] != str(moderator_id) or item['state'] != 'pending' or parse_time(item['ends_at']) <= now:
                    raise ValueError('This active task is not assigned to you.')
                await db.execute('INSERT OR IGNORE INTO support_skips VALUES (?,?,?,?)', (assignment_id, str(moderator_id), reason.strip()[:300], utc_iso(now)))
                await db.execute("UPDATE support_assignments SET moderator_id=NULL,state='queued',updated_at=? WHERE id=?", (utc_iso(now), assignment_id))
                cycle = dict(await (await db.execute('SELECT * FROM support_cycles WHERE id=?', (item['cycle_id'],))).fetchone())
                await self._support_fill(db, cycle, settings)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def rate_support(self, guild_id, assignment_id, moderator_id, score, feedback, checked_ids, *, now=None):
        now = parse_time(now or utc_iso())
        settings = await self.support_settings(guild_id)
        feedback = feedback.strip()
        if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 10):
            raise ValueError('Score must be an integer from 1 to 10.')
        if not 30 <= len(feedback) <= 1500:
            raise ValueError('Write 30-1500 characters of specific, friendly feedback.')
        checked_ids = list(dict.fromkeys(checked_ids))
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                item = await self.support_assignment(guild_id, assignment_id)
                if not settings['enabled'] or not settings.get('roster_at') or not item or item['moderator_id'] != str(moderator_id) or item['state'] != 'pending' or parse_time(item['ends_at']) <= now:
                    raise ValueError('This active task is not assigned to you.')
                if item['user_id'] == str(moderator_id):
                    raise ValueError('Self-evaluation is not allowed.')
                samples = json.loads(item['samples_json'])
                allowed = {s['id'] for s in samples}
                if any(s not in allowed for s in checked_ids) or (score is not None and not checked_ids) or (score is None and allowed):
                    raise ValueError('Rate only after checking the saved sample IDs. Leave unrated only when no samples exist.')
                evaluation_id = str(uuid.uuid4())
                limited = len(checked_ids) < settings['minimum_samples']
                await db.execute('INSERT INTO support_evaluations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (evaluation_id, assignment_id, str(guild_id), item['user_id'], item['kind'], str(moderator_id), score, feedback,
                     json.dumps(checked_ids), len(checked_ids), int(limited), utc_iso(now)))
                await db.execute("UPDATE support_assignments SET state='completed',updated_at=? WHERE id=?", (utc_iso(now), assignment_id))
                await db.execute('INSERT INTO support_messages(id,guild_id,sender_id,recipient_id,evaluation_id,body,dm_next_at,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (evaluation_id, str(guild_id), str(moderator_id), item['user_id'], evaluation_id, feedback, utc_iso(now), utc_iso(now)))
                await db.commit()
                return evaluation_id
            except BaseException:
                await db.rollback()
                raise

    async def team_inbox(self, guild_id, user_id, *, offset=0, limit=5):
        db = await self._get_conn()
        async with db.execute('''SELECT m.*,COALESCE(s.revised_score,e.score) score,e.score original_score,
            e.kind,e.limited_evidence,e.sample_count FROM support_messages m
            JOIN support_evaluations e ON e.id=m.evaluation_id LEFT JOIN support_second_looks s
            ON s.evaluation_id=e.id AND s.state='resolved' WHERE m.guild_id=? AND m.recipient_id=?
            ORDER BY m.created_at DESC,m.id LIMIT ? OFFSET ?''', (str(guild_id), str(user_id), min(10, limit), max(0, offset))) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def team_read(self, guild_id, user_id, message_ids):
        db = await self._get_conn()
        async with self._lock:
            await db.executemany('UPDATE support_messages SET read_at=COALESCE(read_at,?) WHERE guild_id=? AND recipient_id=? AND id=?',
                [(utc_iso(), str(guild_id), str(user_id), m) for m in message_ids])
            await db.commit()

    async def team_dm_preference(self, guild_id, user_id, enabled):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('INSERT INTO support_preferences VALUES (?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET dm_enabled=excluded.dm_enabled', (str(guild_id), str(user_id), int(enabled)))
            await db.commit()

    async def reply_team_message(self, guild_id, user_id, message_id, text, operation_id):
        text = text.strip()
        if not 1 <= len(text) <= 1500:
            raise ValueError('Reply must contain 1-1500 characters.')
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                row = await (await db.execute('SELECT * FROM support_messages WHERE guild_id=? AND recipient_id=? AND id=?', (str(guild_id), str(user_id), message_id))).fetchone()
                if not row:
                    raise ValueError('Message not found in your inbox.')
                existing = await (await db.execute('SELECT id FROM support_messages WHERE id=?', (f'reply:{operation_id}',))).fetchone()
                if existing:
                    await db.rollback()
                    return
                recent = await (await db.execute("SELECT COUNT(*) FROM support_messages WHERE guild_id=? AND sender_id=? AND id LIKE 'reply:%' AND julianday(created_at)>=julianday(?)",
                    (str(guild_id), str(user_id), utc_iso(datetime.now(timezone.utc) - timedelta(hours=1))))).fetchone()
                if recent[0] >= 5:
                    raise ValueError('Five replies per hour are available. Please continue this conversation later.')
                await db.execute('INSERT OR IGNORE INTO support_messages(id,guild_id,sender_id,recipient_id,evaluation_id,body,dm_next_at,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (f'reply:{operation_id}', str(guild_id), str(user_id), row['sender_id'], row['evaluation_id'], text, utc_iso(), utc_iso()))
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def request_second_look(self, guild_id, user_id, evaluation_id, reason):
        if not 10 <= len(reason.strip()) <= 1000:
            raise ValueError('Write a short reason, 10-1000 characters.')
        db = await self._get_conn()
        async with self._lock:
            row = await (await db.execute('SELECT id FROM support_evaluations WHERE guild_id=? AND user_id=? AND id=?', (str(guild_id), str(user_id), evaluation_id))).fetchone()
            if not row:
                raise ValueError('Evaluation not found for your account.')
            ident = str(uuid.uuid4())
            await db.execute('INSERT OR IGNORE INTO support_second_looks(id,guild_id,evaluation_id,user_id,reason,created_at) VALUES (?,?,?,?,?,?)', (ident, str(guild_id), evaluation_id, str(user_id), reason.strip(), utc_iso()))
            await db.commit()
            row = await (await db.execute('SELECT id FROM support_second_looks WHERE guild_id=? AND evaluation_id=?', (str(guild_id), evaluation_id))).fetchone()
            return row[0]

    async def second_looks(self, guild_id):
        db = await self._get_conn()
        async with db.execute("SELECT * FROM support_second_looks WHERE guild_id=? AND state='open' ORDER BY created_at LIMIT 25", (str(guild_id),)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def resolve_second_look(self, guild_id, request_id, admin_id, text, revised_score=None):
        if not 20 <= len(text.strip()) <= 1500:
            raise ValueError('Write 20-1500 characters of resolution.')
        if revised_score is not None and (isinstance(revised_score, bool) or not isinstance(revised_score, int) or not 1 <= revised_score <= 10):
            raise ValueError('Revised score must be an integer from 1 to 10.')
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                row = await (await db.execute("SELECT * FROM support_second_looks WHERE guild_id=? AND id=? AND state='open'", (str(guild_id), request_id))).fetchone()
                if not row:
                    raise ValueError('Open request not found.')
                original = await (await db.execute('SELECT moderator_id,score FROM support_evaluations WHERE id=?', (row['evaluation_id'],))).fetchone()
                if original and original[0] == str(admin_id):
                    raise ValueError('Ask a different admin to resolve this second look independently.')
                if revised_score is not None and original['score'] is None:
                    raise ValueError('A no-evidence check-in cannot become a scored evaluation.')
                await db.execute("UPDATE support_second_looks SET state='resolved',resolution=?,resolved_by=?,resolved_at=?,revised_score=? WHERE id=?", (text.strip(), str(admin_id), utc_iso(), revised_score, request_id))
                await db.execute('INSERT INTO support_messages(id,guild_id,sender_id,recipient_id,evaluation_id,body,dm_next_at,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (f'resolution:{request_id}', str(guild_id), str(admin_id), row['user_id'], row['evaluation_id'], 'Second look: ' + text.strip(), utc_iso(), utc_iso()))
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def pending_support_dms(self):
        db = await self._get_conn()
        async with db.execute('''SELECT m.*,COALESCE(p.dm_enabled,1) dm_enabled FROM support_messages m
            LEFT JOIN support_preferences p ON p.guild_id=m.guild_id AND p.user_id=m.recipient_id
            WHERE m.dm_state='pending' AND m.dm_next_at<=? ORDER BY m.created_at LIMIT 5''', (utc_iso(),)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def support_dm_result(self, message_id, *, state, attempts=0, delay=0):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('UPDATE support_messages SET dm_state=?,dm_attempts=?,dm_next_at=? WHERE id=?', (state, attempts, utc_iso(datetime.now(timezone.utc) + timedelta(seconds=delay)), message_id))
            await db.commit()

    async def queue_support_report(self, guild_id, start, end, requested_by):
        start, end = parse_time(start), parse_time(end)
        if not timedelta(0) < end - start <= timedelta(days=90):
            raise ValueError('Report window must be between 1 and 90 days.')
        db = await self._get_conn()
        async with self._lock:
            existing = await (await db.execute('SELECT * FROM support_report_jobs WHERE guild_id=? AND starts_at=? AND ends_at=?',
                (str(guild_id), utc_iso(start), utc_iso(end)))).fetchone()
            if existing:
                return dict(existing)
            pending = await (await db.execute("SELECT COUNT(*) FROM support_report_jobs WHERE guild_id=? AND state IN ('queued','running')", (str(guild_id),))).fetchone()
            if pending[0] >= 2:
                raise ValueError('Two reports are already waiting or running. Download or finish those first.')
            await db.execute('INSERT OR IGNORE INTO support_report_jobs(id,guild_id,starts_at,ends_at,requested_by,created_at) VALUES (?,?,?,?,?,?)',
                (str(uuid.uuid4()), str(guild_id), utc_iso(start), utc_iso(end), str(requested_by), utc_iso()))
            await db.commit()
        row = await (await db.execute('SELECT * FROM support_report_jobs WHERE guild_id=? AND starts_at=? AND ends_at=?', (str(guild_id), utc_iso(start), utc_iso(end)))).fetchone()
        return dict(row)

    async def queue_due_support_report(self, guild_id, *, now=None):
        now = parse_time(now or utc_iso())
        cfg = await self.support_settings(guild_id)
        if not cfg['enabled'] or not cfg.get('next_report_at') or parse_time(cfg['next_report_at']) > now:
            return None
        end = parse_time(cfg['next_report_at'])
        # After downtime, resume the most recent complete 14-day interval, not a queue storm.
        end += timedelta(days=14 * int((now - end).total_seconds() // (14 * 86400)))
        job = await self.queue_support_report(guild_id, end - timedelta(days=14), end, 'scheduler')
        db = await self._get_conn()
        async with self._lock:
            await db.execute('UPDATE support_config SET next_report_at=? WHERE guild_id=?', (utc_iso(end + timedelta(days=14)), str(guild_id)))
            await db.commit()
        return job

    async def next_support_report(self):
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                row = await (await db.execute("SELECT * FROM support_report_jobs WHERE state='queued' ORDER BY created_at LIMIT 1")).fetchone()
                if not row:
                    await db.rollback()
                    return None
                await db.execute("UPDATE support_report_jobs SET state='running',attempts=attempts+1 WHERE id=?", (row['id'],))
                await db.commit()
                return dict(row)
            except BaseException:
                await db.rollback()
                raise

    async def retry_support_report(self, guild_id, ident):
        db = await self._get_conn()
        async with self._lock:
            pending = await (await db.execute("SELECT COUNT(*) FROM support_report_jobs WHERE guild_id=? AND state IN ('queued','running')", (str(guild_id),))).fetchone()
            if pending[0] >= 2:
                raise ValueError('Two reports are already waiting or running.')
            result = await db.execute("UPDATE support_report_jobs SET state='queued',error=NULL WHERE guild_id=? AND id=? AND state='failed' AND attempts<3", (str(guild_id), ident))
            await db.commit()
            if not result.rowcount:
                raise ValueError('Retry requires a failed report in this server with fewer than three attempts.')

    async def finish_support_report(self, ident, *, payload=None, path=None, error=None):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('UPDATE support_report_jobs SET state=?,payload_json=?,output_path=?,error=? WHERE id=?',
                ('failed' if error else 'completed', json.dumps(payload) if payload is not None else None, str(path) if path else None, error, ident))
            await db.commit()

    async def get_support_report(self, guild_id, ident=None):
        db = await self._get_conn()
        if ident:
            sql, args = 'SELECT * FROM support_report_jobs WHERE guild_id=? AND id=?', (str(guild_id), ident)
        else:
            sql, args = 'SELECT * FROM support_report_jobs WHERE guild_id=? ORDER BY ends_at DESC,created_at DESC LIMIT 1', (str(guild_id),)
        row = await (await db.execute(sql, args)).fetchone()
        return dict(row) if row else None
