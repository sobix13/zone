"""Additive operations schema and transaction boundaries for Melee Zone V3."""
import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from runtime_utils import emoji_key, parse_time, utc_iso, valid_amount


SCHEMA = (
    '''CREATE TABLE IF NOT EXISTS onboarding_notices (
        guild_id TEXT NOT NULL,user_id TEXT NOT NULL,notified_at TEXT NOT NULL,
        PRIMARY KEY(guild_id,user_id))''',
    '''CREATE TABLE IF NOT EXISTS reaction_event_inbox (
        id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
        message_id TEXT NOT NULL, admin_id TEXT NOT NULL, emoji TEXT NOT NULL,
        amount REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT NOT NULL, last_error TEXT)''',
    '''CREATE TABLE IF NOT EXISTS operation_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT, actor_id TEXT,
        category TEXT NOT NULL, result TEXT NOT NULL, reference_id TEXT,
        detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS reaction_award_keys (
        message_id TEXT NOT NULL, admin_id TEXT NOT NULL, emoji_key TEXT NOT NULL,
        PRIMARY KEY(message_id,admin_id,emoji_key))''',
    '''CREATE TABLE IF NOT EXISTS notification_outbox (
        id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
        content TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        next_at TEXT NOT NULL, last_error TEXT, created_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS activity_watches (
        guild_id TEXT NOT NULL, role_id TEXT NOT NULL, started_at TEXT NOT NULL,
        PRIMARY KEY(guild_id,role_id))''',
    '''CREATE TABLE IF NOT EXISTS activity_messages (
        message_id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, user_id TEXT NOT NULL,
        channel_id TEXT NOT NULL, parent_id TEXT, created_at TEXT NOT NULL,
        excerpt TEXT NOT NULL DEFAULT '', deleted INTEGER NOT NULL DEFAULT 0)''',
    '''CREATE INDEX IF NOT EXISTS idx_activity_user_time
        ON activity_messages(guild_id,user_id,created_at DESC)''',
    '''CREATE TABLE IF NOT EXISTS activity_deletions (
        message_id TEXT PRIMARY KEY, observed_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS activity_events (
        event_key TEXT PRIMARY KEY, guild_id TEXT NOT NULL, user_id TEXT NOT NULL,
        event_type TEXT NOT NULL, channel_id TEXT, created_at TEXT NOT NULL)''',
    '''CREATE INDEX IF NOT EXISTS idx_activity_event_user
        ON activity_events(guild_id,user_id,created_at DESC)''',
    '''CREATE TABLE IF NOT EXISTS role_report_jobs (
        id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, role_id TEXT NOT NULL,
        role_name TEXT NOT NULL, requested_by TEXT NOT NULL, requested_at TEXT NOT NULL,
        cutoff TEXT, upper_at TEXT NOT NULL, max_messages INTEGER NOT NULL, scanned INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL DEFAULT 'queued', error TEXT, output_path TEXT,
        members_json TEXT NOT NULL, discovery_complete INTEGER NOT NULL DEFAULT 0)''',
    '''CREATE TABLE IF NOT EXISTS role_report_channels (
        job_id TEXT NOT NULL, channel_id TEXT NOT NULL, channel_name TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending', before_id TEXT, scanned INTEGER NOT NULL DEFAULT 0,
        detail TEXT, PRIMARY KEY(job_id,channel_id))''',
    '''CREATE TABLE IF NOT EXISTS onboarding_progress (
        guild_id TEXT NOT NULL,user_id TEXT NOT NULL,step INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,PRIMARY KEY(guild_id,user_id))''',
)


class OperationsDB:
    async def finalize_review_rewards(self,post_id):
        """Commit the post result and its score/showcase balances together."""
        from config import Config
        db=await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                async with db.execute('SELECT * FROM posts WHERE post_id=?',(post_id,)) as cur:
                    row=await cur.fetchone()
                if not row or row['status'] not in ('pending','assigned'):
                    await db.rollback();return None
                post=dict(row)
                async with db.execute('SELECT * FROM guild_config WHERE guild_id=?',(post['guild_id'],)) as cur:
                    cfg=await cur.fetchone();config=dict(cfg) if cfg else {}
                async with db.execute('SELECT score FROM reviews WHERE post_id=?',(post_id,)) as cur:
                    reviews=await cur.fetchall()
                if len(reviews)<int(post['required_reviews'] or Config.get_min_reviews(config)):
                    await db.rollback();return None
                score=sum(r['score'] for r in reviews)/len(reviews)
                amount=Config.calculate_mc_from_score(score,config)
                showcase=score>=Config.get_showcase_threshold(config)
                await self._award_row(db,user_id=post['author_id'],guild_id=post['guild_id'],username=post['author_id'],
                    amount=amount,mc_type='regular',reason=f'Score: {score:.1f}/10',reference_id=post_id,
                    reward_key=f"score:{post['guild_id']}:{post_id}")
                if showcase:
                    await self._award_row(db,user_id=post['author_id'],guild_id=post['guild_id'],username=post['author_id'],
                        amount=Config.get_showcase_reward(config),mc_type='golden',reason=f'Showcase: {score:.1f}/10',
                        reference_id=post_id,reward_key=f"showcase:{post['guild_id']}:{post_id}")
                await db.execute('UPDATE posts SET status=?,final_score=?,mc_earned=? WHERE post_id=?',
                    ('approved' if score>=6 else 'rejected',score,amount,post_id))
                if config.get('credit_log_channel_id'):
                    await self._enqueue_notice(db,post['guild_id'],config['credit_log_channel_id'],
                        f"Post {post_id}: score {score:.1f}/10; {amount:g} regular MC. Author: <@{post['author_id']}>.",f'post:{post_id}')
                await db.commit()
                return {'post':post,'config':config,'score':score,'amount':amount,'showcase':showcase}
            except BaseException:
                await db.rollback();raise

    async def complete_quiz_atomic(self,*,guild_id,user_id,quiz_id,session_id,correct,total,
                                   score_pct,mc_earned,elapsed_seconds,completed_at,title):
        """One quiz result, session completion and MC reward in one transaction."""
        db=await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                async with db.execute('SELECT 1 FROM quiz_sessions WHERE id=? AND guild_id=? AND user_id=? AND quiz_id=?',
                    (session_id,guild_id,user_id,quiz_id)) as cur:
                    if not await cur.fetchone():
                        raise ValueError('Quiz session not found.')
                cur=await db.execute('''INSERT OR IGNORE INTO quiz_results
                    (guild_id,user_id,quiz_id,session_id,correct_count,total_questions,score_pct,mc_earned,elapsed_seconds,completed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',(guild_id,user_id,quiz_id,session_id,correct,total,score_pct,mc_earned,elapsed_seconds,utc_iso(completed_at)))
                created=cur.rowcount==1
                if created:
                    await self._award_row(db,user_id=user_id,guild_id=guild_id,username=user_id,amount=mc_earned,
                        mc_type='regular',reason=f'Quiz: {title} ({score_pct:.0f}%)',reference_id=str(quiz_id),
                        reward_key=f'quiz:{guild_id}:{user_id}:{quiz_id}')
                await db.execute('UPDATE quiz_sessions SET completed=1 WHERE id=?',(session_id,))
                await db.commit();return created
            except BaseException:
                await db.rollback();raise

    async def create_review_assignment_atomic(self,post_id,reviewer_id,week_id,due_date):
        db=await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                async with db.execute('SELECT * FROM posts WHERE post_id=?',(post_id,)) as cur:
                    post=await cur.fetchone()
                if not post or post['author_id']==reviewer_id or post['status'] not in ('pending','assigned'):
                    await db.rollback();return None
                async with db.execute('SELECT 1 FROM reviews WHERE post_id=? AND reviewer_id=?',(post_id,reviewer_id)) as cur:
                    if await cur.fetchone():
                        await db.rollback();return None
                async with db.execute('''SELECT (SELECT COUNT(*) FROM reviews WHERE post_id=?)+
                    (SELECT COUNT(*) FROM assignments WHERE post_id=? AND status IN ('pending','warning'))''',(post_id,post_id)) as cur:
                    filled=(await cur.fetchone())[0]
                if filled>=int(post['required_reviews'] or 3):
                    await db.rollback();return None
                async with db.execute('SELECT max_reviews_per_week FROM guild_config WHERE guild_id=?',(post['guild_id'],)) as cur:
                    config=await cur.fetchone()
                async with db.execute('''SELECT COUNT(*) FROM assignments a JOIN posts p ON p.post_id=a.post_id
                    WHERE p.guild_id=? AND a.reviewer_id=? AND a.week_id=? AND a.status NOT IN ('reassigned','removed')
                    AND COALESCE(a.assignment_type,'primary')='primary' ''',(post['guild_id'],reviewer_id,week_id)) as cur:
                    load=(await cur.fetchone())[0]
                if load>=int(config[0] if config else 5):
                    await db.rollback();return None
                aid=str(uuid.uuid4())
                cur=await db.execute('''INSERT OR IGNORE INTO assignments(assignment_id,post_id,reviewer_id,week_id,due_date,assigned_at)
                    VALUES (?,?,?,?,?,?)''',(aid,post_id,reviewer_id,week_id,utc_iso(due_date),utc_iso()))
                if cur.rowcount!=1:
                    await db.rollback();return None
                await db.execute("UPDATE posts SET status='assigned' WHERE post_id=? AND status='pending'",(post_id,))
                await db.commit();return aid
            except BaseException:
                await db.rollback();raise

    async def rescue_assignment_atomic(self,guild_id,old_id,reviewer_id,week_id,due_date):
        db=await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                async with db.execute('''SELECT a.*,p.author_id,p.guild_id,p.status post_status FROM assignments a
                    JOIN posts p ON p.post_id=a.post_id WHERE a.assignment_id=? AND p.guild_id=?''',(old_id,guild_id)) as cur:
                    old=await cur.fetchone()
                async with db.execute('SELECT * FROM guild_config WHERE guild_id=?',(guild_id,)) as cur:
                    config=await cur.fetchone()
                async with db.execute('SELECT ready_for_more FROM users WHERE user_id=? AND guild_id=?',(reviewer_id,guild_id)) as cur:
                    ready=await cur.fetchone()
                if not old or old['status']!='warning' or old['post_status'] not in ('pending','assigned') or reviewer_id in (old['author_id'],old['reviewer_id']) or not ready or not ready[0]:
                    await db.rollback();return None
                async with db.execute('SELECT 1 FROM reviews WHERE post_id=? AND reviewer_id=?',(old['post_id'],reviewer_id)) as cur:
                    if await cur.fetchone():
                        await db.rollback();return None
                grace=int(config['warning_grace_hours'] if config else 12)
                if not old['warning_sent_at'] or (datetime.now(timezone.utc)-parse_time(old['warning_sent_at'])).total_seconds()<grace*3600:
                    await db.rollback();return None
                async with db.execute('''SELECT COUNT(*) FROM assignments a JOIN posts p ON p.post_id=a.post_id
                    WHERE p.guild_id=? AND a.reviewer_id=? AND a.week_id=? AND a.status IN ('pending','warning')
                    AND COALESCE(a.assignment_type,'primary')='primary' ''',(guild_id,reviewer_id,week_id)) as cur:
                    pending=(await cur.fetchone())[0]
                async with db.execute('''SELECT COUNT(*) FROM assignments a JOIN posts p ON p.post_id=a.post_id
                    WHERE p.guild_id=? AND a.reviewer_id=? AND a.week_id=? AND a.assignment_type='rescue'
                    AND a.status NOT IN ('reassigned','removed')''',(guild_id,reviewer_id,week_id)) as cur:
                    load=(await cur.fetchone())[0]
                limit=int(config['rescue_review_limit'] if config else 3)
                if pending or load>=limit:
                    await db.rollback();return None
                aid=str(uuid.uuid4())
                cur=await db.execute('''INSERT OR IGNORE INTO assignments
                    (assignment_id,post_id,reviewer_id,week_id,due_date,assigned_at,assignment_type,original_assignment_id)
                    VALUES (?,?,?,?,?,?,'rescue',?)''',(aid,old['post_id'],reviewer_id,week_id,utc_iso(due_date),utc_iso(),old_id))
                if cur.rowcount!=1:
                    await db.rollback();return None
                await db.execute("UPDATE assignments SET status='reassigned',reassigned_at=? WHERE assignment_id=?",(utc_iso(),old_id))
                if load+1>=limit:
                    await db.execute('UPDATE users SET ready_for_more=0,ready_for_more_at=NULL WHERE user_id=? AND guild_id=?',(reviewer_id,guild_id))
                await db.commit();return aid
            except BaseException:
                await db.rollback();raise

    async def claim_onboarding_notice(self,guild_id,user_id):
        db=await self._get_conn()
        async with self._lock:
            cur=await db.execute('INSERT OR IGNORE INTO onboarding_notices VALUES (?,?,?)',(guild_id,user_id,utc_iso()))
            await db.commit();return cur.rowcount==1

    async def decline_review(self,guild_id,reviewer_id,assignment_id,reason):
        db=await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                cur=await db.execute('''UPDATE assignments SET status='reassigned',reassigned_at=?
                    WHERE assignment_id=? AND reviewer_id=? AND status IN ('pending','warning')
                    AND post_id IN (SELECT post_id FROM posts WHERE guild_id=?)''',(utc_iso(),assignment_id,reviewer_id,guild_id))
                if cur.rowcount:
                    await db.execute('''INSERT INTO operation_events(guild_id,actor_id,category,result,reference_id,detail,created_at)
                        VALUES (?,?, 'review_skip','reassigned',?,?,?)''',(guild_id,reviewer_id,assignment_id,reason,utc_iso()))
                await db.commit();return cur.rowcount==1
            except BaseException:
                await db.rollback();raise

    async def enqueue_reaction(self, guild_id,channel_id,message_id,admin_id,emoji,amount):
        db=await self._get_conn()
        key=f'{message_id}:{admin_id}:{emoji_key(emoji)}'
        async with self._lock:
            await db.execute('''INSERT OR IGNORE INTO reaction_event_inbox
                (id,guild_id,channel_id,message_id,admin_id,emoji,amount,next_at)
                VALUES (?,?,?,?,?,?,?,?)''',(key,guild_id,channel_id,message_id,admin_id,str(emoji),valid_amount(amount),utc_iso()))
            await db.commit()

    async def pending_reactions(self,limit=10):
        db=await self._get_conn()
        async with self._lock:
            async with db.execute("SELECT * FROM reaction_event_inbox WHERE state='pending' AND next_at<=? ORDER BY next_at LIMIT ?",(utc_iso(),limit)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def reaction_result(self,event,error=None):
        db=await self._get_conn()
        attempts=event['attempts']+1
        next_at=utc_iso(datetime.now(timezone.utc)+timedelta(seconds=min(900,10*2**min(attempts,6))))
        state='done' if not error else ('failed' if attempts>=8 else 'pending')
        async with self._lock:
            await db.execute('UPDATE reaction_event_inbox SET state=?,attempts=?,next_at=?,last_error=? WHERE id=?',
                (state,attempts,next_at,str(error)[:200] if error else None,event['id']))
            await db.execute("DELETE FROM reaction_event_inbox WHERE state='done' AND next_at<?",(utc_iso(datetime.now(timezone.utc)-timedelta(days=7)),))
            await db.commit()

    async def retry_failed_reactions(self,guild_id):
        db=await self._get_conn()
        async with self._lock:
            cur=await db.execute("UPDATE reaction_event_inbox SET state='pending',attempts=0,next_at=? WHERE guild_id=? AND state='failed'",(utc_iso(),guild_id))
            await db.commit();return cur.rowcount

    async def init_operations(self):
        db = await self._get_conn()
        async with self._lock:
            try:
                for statement in SCHEMA:
                    await db.execute(statement)
                async with db.execute('SELECT message_id,admin_id,emoji FROM reaction_credits') as cur:
                    legacy = await cur.fetchall()
                await db.executemany('INSERT OR IGNORE INTO reaction_award_keys VALUES (?,?,?)',
                    [(r['message_id'], r['admin_id'], emoji_key(r['emoji'])) for r in legacy])
                # A stopped process resumes queued work. Paused jobs stay paused.
                await db.execute("UPDATE role_report_jobs SET state='queued' WHERE state='running'")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def record_operation(self, category, result, *, guild_id=None, actor_id=None, reference_id=None, detail=''):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('''INSERT INTO operation_events
                (guild_id,actor_id,category,result,reference_id,detail,created_at) VALUES (?,?,?,?,?,?,?)''',
                (guild_id,actor_id,category,result,reference_id,str(detail)[:500],utc_iso()))
            await db.execute('DELETE FROM operation_events WHERE event_id < (SELECT COALESCE(MAX(event_id),0)-10000 FROM operation_events)')
            await db.commit()

    async def recent_operations(self, guild_id, limit=15):
        db = await self._get_conn()
        async with db.execute('SELECT * FROM operation_events WHERE guild_id=? ORDER BY event_id DESC LIMIT ?', (guild_id,limit)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def _award_row(self, db, *, user_id, guild_id, username, amount, mc_type, reason,
                         reference_id=None, admin_id=None, reward_key=None):
        """Caller owns the transaction. Return false only for an existing reward key."""
        if mc_type not in ('regular','golden','assignment'):
            raise ValueError('Unknown MC type.')
        amount = valid_amount(amount, allow_zero=True)
        if amount == 0:
            return False
        async with db.execute('SELECT max_submits_per_week FROM guild_config WHERE guild_id=?', (guild_id,)) as cur:
            cfg = await cur.fetchone()
        await db.execute('''INSERT OR IGNORE INTO users(user_id,guild_id,username,weekly_submits)
            VALUES (?,?,?,?)''', (user_id,guild_id,username,cfg[0] if cfg else 5))
        cur = await db.execute('''INSERT OR IGNORE INTO mc_transactions
            (transaction_id,user_id,guild_id,amount,mc_type,reason,reference_id,admin_id,reward_key)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (str(uuid.uuid4()),user_id,guild_id,amount,mc_type,str(reason)[:500],reference_id,admin_id,reward_key))
        if cur.rowcount != 1:
            return False
        col = {'regular':'mc_regular','golden':'mc_golden','assignment':'mc_assignment'}[mc_type]
        updated = await db.execute(f'UPDATE users SET {col}=COALESCE({col},0)+? WHERE user_id=? AND guild_id=?', (amount,user_id,guild_id))
        if updated.rowcount != 1:
            raise RuntimeError('MC recipient balance was not updated.')
        return True

    async def award_batch_atomic(self, guild_id, admin_id, members, amount, mc_type, reason,
                                 operation_id, *, notice_channel=None, snapshot_id=None):
        amount = valid_amount(amount)
        if mc_type not in ('regular','golden','assignment') or not members:
            raise ValueError('Choose members and a valid MC type.')
        members = list({str(m['id']):m for m in members}.values())
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                granted = []
                for m in members:
                    uid = str(m['id'])
                    key = f'manual:{guild_id}:{admin_id}:{operation_id}:{uid}'
                    if await self._award_row(db,user_id=uid,guild_id=guild_id,username=m['name'],amount=amount,
                        mc_type=mc_type,reason=reason,reference_id=operation_id,admin_id=admin_id,reward_key=key):
                        granted.append(uid)
                        if snapshot_id:
                            await db.execute('''INSERT OR IGNORE INTO snapshot_awards
                                (snapshot_id,guild_id,user_id,amount,mc_type) VALUES (?,?,?,?,?)''',
                                (snapshot_id,guild_id,uid,amount,mc_type))
                if granted and notice_channel:
                    content = f'{len(granted)} member(s) received {amount:g} {mc_type} MC each. Reason: {reason}. Awarded by <@{admin_id}>. Ref: {operation_id}'
                    await self._enqueue_notice(db,guild_id,notice_channel,content,f'batch:{guild_id}:{operation_id}')
                await db.commit()
                return {'created':granted,'already_exists':len(members)-len(granted)}
            except BaseException:
                await db.rollback()
                raise

    async def award_reaction_atomic(self, *, guild_id, channel_id, message_id, author_id,
                                    username, admin_id, emoji, amount, notice_channel=None):
        amount = valid_amount(amount)
        ek = emoji_key(emoji)
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                cur = await db.execute('INSERT OR IGNORE INTO reaction_award_keys VALUES (?,?,?)', (message_id,admin_id,ek))
                if cur.rowcount != 1:
                    await db.rollback()
                    return False
                key = f'reaction:{guild_id}:{message_id}:{admin_id}:{ek}'
                created = await self._award_row(db,user_id=author_id,guild_id=guild_id,username=username,
                    amount=amount,mc_type='regular',reason=f'Reaction award by {admin_id}',
                    reference_id=message_id,admin_id=admin_id,reward_key=key)
                if not created:
                    await db.rollback()
                    return False
                await db.execute('''INSERT INTO reaction_credits
                    (id,message_id,channel_id,author_id,admin_id,emoji,amount) VALUES (?,?,?,?,?,?,?)''',
                    (str(uuid.uuid4()),message_id,channel_id,author_id,admin_id,str(emoji),amount))
                if notice_channel:
                    await self._enqueue_notice(db,guild_id,notice_channel,
                        f'<@{author_id}> received {amount:g} MC. Awarded by <@{admin_id}>. https://discord.com/channels/{guild_id}/{channel_id}/{message_id}',key)
                await db.commit()
                return True
            except BaseException:
                await db.rollback()
                raise

    async def _enqueue_notice(self, db, guild_id, channel_id, content, key):
        await db.execute('''INSERT OR IGNORE INTO notification_outbox
            (id,guild_id,channel_id,content,next_at,created_at) VALUES (?,?,?,?,?,?)''',
            (key,guild_id,str(channel_id),content[:1900],utc_iso(),utc_iso()))

    async def pending_notices(self):
        db = await self._get_conn()
        async with self._lock:
            async with db.execute("SELECT * FROM notification_outbox WHERE state='pending' AND next_at<=? ORDER BY created_at LIMIT 20",(utc_iso(),)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def notice_result(self, notice, error=None):
        db = await self._get_conn()
        attempts = notice['attempts']+1
        state = 'done' if not error else ('failed' if attempts>=8 else 'pending')
        next_at = utc_iso(datetime.now(timezone.utc)+timedelta(seconds=min(900,15*2**min(attempts,6))))
        async with self._lock:
            await db.execute('UPDATE notification_outbox SET state=?,attempts=?,next_at=?,last_error=? WHERE id=?',
                (state,attempts,next_at,str(error)[:200] if error else None,notice['id']))
            await db.execute("DELETE FROM notification_outbox WHERE state='done' AND created_at<?",(utc_iso(datetime.now(timezone.utc)-timedelta(days=30)),))
            await db.commit()

    async def retry_failed_notices(self, guild_id):
        db = await self._get_conn()
        async with self._lock:
            cur=await db.execute("UPDATE notification_outbox SET state='pending',attempts=0,next_at=? WHERE guild_id=? AND state='failed'",(utc_iso(),guild_id))
            await db.commit()
            return cur.rowcount

    async def accept_task_message(self, assignment, user_id, timestamp):
        """Reserve a cooldown and record participation together, including rapid messages."""
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                async with db.execute('SELECT last_msg_at FROM assignment_cooldowns WHERE thread_id=? AND user_id=?',(assignment['thread_id'],user_id)) as cur:
                    previous=await cur.fetchone()
                if previous:
                    remaining=assignment['cooldown_seconds']-(parse_time(timestamp)-parse_time(previous[0])).total_seconds()
                    if remaining>0:
                        await db.rollback()
                        return int(remaining)+1
                await db.execute('INSERT OR IGNORE INTO assignment_participants(assignment_id,user_id) VALUES (?,?)',(assignment['id'],user_id))
                await db.execute('''INSERT INTO assignment_cooldowns VALUES (?,?,?)
                    ON CONFLICT(thread_id,user_id) DO UPDATE SET last_msg_at=excluded.last_msg_at''',(assignment['thread_id'],user_id,timestamp))
                await db.commit()
                return 0
            except BaseException:
                await db.rollback()
                raise

    async def reset_task_cooldown(self, thread_id, user_id):
        db=await self._get_conn()
        async with self._lock:
            await db.execute('DELETE FROM assignment_cooldowns WHERE thread_id=? AND user_id=?',(thread_id,user_id))
            await db.commit()

    async def watch_role(self, guild_id, role_id):
        db=await self._get_conn()
        async with self._lock:
            await db.execute('INSERT OR IGNORE INTO activity_watches VALUES (?,?,?)',(guild_id,role_id,utc_iso()))
            await db.commit()

    async def watched_roles(self, guild_id):
        db=await self._get_conn()
        async with db.execute('SELECT role_id FROM activity_watches WHERE guild_id=?',(guild_id,)) as cur:
            return {r[0] for r in await cur.fetchall()}

    async def store_activity_messages(self, rows, *, job_id=None, channel_id=None, before_id=None, scanned=0, complete=False):
        db=await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                if rows:
                    await db.executemany('''INSERT INTO activity_messages(message_id,guild_id,user_id,channel_id,parent_id,created_at,excerpt)
                        VALUES (?,?,?,?,?,?,?) ON CONFLICT(message_id) DO UPDATE SET
                        excerpt=CASE WHEN activity_messages.deleted=1 THEN '' ELSE excluded.excerpt END''',rows)
                    await db.executemany('''UPDATE activity_messages SET deleted=1,excerpt=''
                        WHERE message_id=? AND EXISTS(SELECT 1 FROM activity_deletions d WHERE d.message_id=activity_messages.message_id)''',[(r[0],) for r in rows])
                if job_id:
                    await db.execute('''UPDATE role_report_channels SET before_id=?,scanned=scanned+?,state=?
                        WHERE job_id=? AND channel_id=?''',(before_id,scanned,'complete' if complete else 'pending',job_id,channel_id))
                    await db.execute('UPDATE role_report_jobs SET scanned=scanned+? WHERE id=?',(scanned,job_id))
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def store_activity_event(self, guild_id,user_id,event_type,channel_id,event_key):
        db=await self._get_conn()
        async with self._lock:
            await db.execute('INSERT OR IGNORE INTO activity_events VALUES (?,?,?,?,?,?)',(event_key,guild_id,user_id,event_type,channel_id,utc_iso()))
            # Keep recent events, while retaining last observed activity per member below.
            await db.execute('''DELETE FROM activity_events WHERE guild_id=? AND user_id=? AND event_key NOT IN
                (SELECT event_key FROM activity_events WHERE guild_id=? AND user_id=? ORDER BY created_at DESC LIMIT 50)''',
                (guild_id,user_id,guild_id,user_id))
            await db.commit()

    async def mark_activity_deleted(self,message_ids):
        db=await self._get_conn()
        async with self._lock:
            ids=[str(i) for i in message_ids]
            await db.executemany('INSERT OR REPLACE INTO activity_deletions VALUES (?,?)',[(i,utc_iso()) for i in ids])
            await db.executemany('UPDATE activity_messages SET deleted=1,excerpt=\'\' WHERE message_id=?',[(i,) for i in ids])
            await db.execute('''DELETE FROM activity_deletions WHERE message_id NOT IN
                (SELECT message_id FROM activity_deletions ORDER BY observed_at DESC LIMIT 10000)''')
            await db.commit()

    async def create_role_job(self,guild_id,role,requested_by,members,cutoff,max_messages):
        db=await self._get_conn()
        job_id=uuid.uuid4().hex[:12]
        async with self._lock:
            async with db.execute("SELECT COUNT(*) FROM role_report_jobs WHERE guild_id=? AND state IN ('queued','running','paused')",(guild_id,)) as cur:
                if (await cur.fetchone())[0]>=3:
                    raise ValueError('Three reports are already queued. Wait for one to finish.')
            await db.execute('''INSERT INTO role_report_jobs
                (id,guild_id,role_id,role_name,requested_by,requested_at,cutoff,upper_at,max_messages,members_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',(job_id,guild_id,str(role.id),role.name,requested_by,utc_iso(),cutoff,utc_iso(),max_messages,json.dumps(members)))
            await db.commit()
        return job_id

    async def get_role_job(self,job_id,guild_id=None):
        db=await self._get_conn()
        query='SELECT * FROM role_report_jobs WHERE id=?'
        args=[job_id]
        if guild_id is not None:
            query+=' AND guild_id=?';args.append(guild_id)
        async with db.execute(query,args) as cur:
            row=await cur.fetchone()
            return dict(row) if row else None

    async def next_role_job(self):
        db=await self._get_conn()
        async with db.execute("SELECT * FROM role_report_jobs WHERE state='queued' ORDER BY requested_at LIMIT 1") as cur:
            row=await cur.fetchone();return dict(row) if row else None

    async def update_role_job(self,job_id,**kwargs):
        allowed={'state','error','output_path','discovery_complete','max_messages'}
        if not kwargs or not set(kwargs)<=allowed:
            raise ValueError('Unknown report field.')
        db=await self._get_conn()
        async with self._lock:
            guard=" AND state!='cancelled'" if kwargs.get('state') and kwargs['state']!='cancelled' else ''
            await db.execute('UPDATE role_report_jobs SET '+','.join(f'{k}=?' for k in kwargs)+' WHERE id=?'+guard,[*kwargs.values(),job_id])
            await db.commit()

    async def add_report_channel(self,job_id,channel_id,name,*,state='pending',detail=None):
        db=await self._get_conn()
        async with self._lock:
            await db.execute('''INSERT OR IGNORE INTO role_report_channels(job_id,channel_id,channel_name,state,detail)
                VALUES (?,?,?,?,?)''',(job_id,str(channel_id),name,state,detail))
            await db.commit()

    async def report_channels(self,job_id):
        db=await self._get_conn()
        async with db.execute('SELECT * FROM role_report_channels WHERE job_id=? ORDER BY channel_id',(job_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def set_report_channel(self,job_id,channel_id,state,detail=None):
        db=await self._get_conn()
        async with self._lock:
            await db.execute('UPDATE role_report_channels SET state=?,detail=? WHERE job_id=? AND channel_id=?',(state,detail,job_id,channel_id))
            await db.commit()

    async def activity_for_member(self,guild_id,user_id,cutoff,upper_at):
        db=await self._get_conn()
        async with db.execute('''SELECT COUNT(*) known_messages,MAX(created_at) last_message_at,
            SUM(CASE WHEN deleted=0 THEN 1 ELSE 0 END) retained_messages
            FROM activity_messages WHERE guild_id=? AND user_id=?''',(guild_id,user_id)) as cur:
            result=dict(await cur.fetchone())
        async with db.execute('''SELECT COUNT(*) FROM activity_messages WHERE guild_id=? AND user_id=?
            AND deleted=0 AND created_at>=? AND created_at<=?''',(guild_id,user_id,cutoff or '',upper_at)) as cur:
            result['window_messages']=(await cur.fetchone())[0]
        async with db.execute('''SELECT * FROM activity_messages WHERE guild_id=? AND user_id=? AND deleted=0
            ORDER BY created_at DESC LIMIT 5''',(guild_id,user_id)) as cur:
            result['recent_messages']=[dict(r) for r in await cur.fetchall()]
        async with db.execute('''SELECT event_type,created_at FROM activity_events WHERE guild_id=? AND user_id=?
            ORDER BY created_at DESC LIMIT 1''',(guild_id,user_id)) as cur:
            event=await cur.fetchone()
        async with db.execute('''SELECT * FROM activity_events WHERE guild_id=? AND user_id=?
            ORDER BY created_at DESC LIMIT 5''',(guild_id,user_id)) as cur:
            result['recent_events']=[dict(r) for r in await cur.fetchall()]
        result['last_activity_at']=result['last_message_at']
        result['last_activity_type']='message' if result['last_message_at'] else None
        if event and (not result['last_activity_at'] or event['created_at']>result['last_activity_at']):
            result.update(last_activity_at=event['created_at'],last_activity_type=event['event_type'])
        return result

    async def set_onboarding(self,guild_id,user_id,step):
        db=await self._get_conn()
        async with self._lock:
            await db.execute('''INSERT INTO onboarding_progress VALUES (?,?,?,?)
                ON CONFLICT(guild_id,user_id) DO UPDATE SET step=excluded.step,updated_at=excluded.updated_at''',(guild_id,user_id,step,utc_iso()))
            await db.commit()

    async def get_onboarding(self,guild_id,user_id):
        db=await self._get_conn()
        async with db.execute('SELECT step FROM onboarding_progress WHERE guild_id=? AND user_id=?',(guild_id,user_id)) as cur:
            row=await cur.fetchone();return row[0] if row else 0

    async def db_health(self):
        db=await self._get_conn()
        async with db.execute('SELECT 1') as cur:
            return (await cur.fetchone())[0]==1

    async def online_backup(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        db=await self._get_conn()
        async with self._lock:
            target=sqlite3.connect(path)
            try:
                await db.backup(target,pages=128,sleep=0.01)
            finally:
                target.close()
        path.chmod(0o600)
        return path
