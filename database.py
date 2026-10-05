import aiosqlite
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import logging
import re
from operations_db import OperationsDB
from review_support_db import ReviewSupportDB
from governance_db import GovernanceDB

log = logging.getLogger('MeleeZone.DB')

class DuplicateSubmissionError(Exception):
    pass


class Database(OperationsDB, ReviewSupportDB, GovernanceDB):
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        async with self._connect_lock:
            if self._conn is None:
                conn = await aiosqlite.connect(self.db_path)
                conn.row_factory = aiosqlite.Row
                await conn.execute("PRAGMA busy_timeout=5000")
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute("PRAGMA foreign_keys=ON")
                self._conn = conn
        return self._conn

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def init(self):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id TEXT PRIMARY KEY,
                    pro_role_id TEXT,
                    basic_role_id TEXT,
                    admin_role_id TEXT,
                    admin_user_id TEXT,
                    bot_content_channel_id TEXT,
                    submit_channel_id TEXT,
                    review_channel_id TEXT,
                    showcase_channel_id TEXT,
                    log_channel_id TEXT,
                    credit_log_channel_id TEXT,
                    leaderboard_channel_id TEXT,
                    mention_role_id TEXT,
                    is_configured INTEGER DEFAULT 0,
                    configured_at TEXT,
                    leaderboard_message_id TEXT,
                    panel_message_id TEXT,
                    review_window_days INTEGER DEFAULT 5,
                    min_reviews INTEGER DEFAULT 5,
                    max_submits_per_week INTEGER DEFAULT 5,
                    max_reviews_per_week INTEGER DEFAULT 7,
                    showcase_threshold REAL DEFAULT 8.0,
                    reminder_hours INTEGER DEFAULT 72,
                    require_twitter_id INTEGER DEFAULT 1,
                    quiz_pass_role_id TEXT,
                    quiz_mc_40 REAL DEFAULT 1.0,
                    quiz_mc_70 REAL DEFAULT 2.0,
                    quiz_mc_80 REAL DEFAULT 3.0,
                    quiz_mc_90 REAL DEFAULT 5.0,
                    quiz_mc_min_pct REAL DEFAULT 40.0,
                    raffle_role_id TEXT,
                    assignment_channel_id TEXT,
                    reaction_emoji_4 TEXT,
                    reaction_emoji_5 TEXT,
                    reaction_mc_4 REAL DEFAULT 4.0,
                    reaction_mc_5 REAL DEFAULT 5.0,
                    raffle_reaction_emoji TEXT,
                    reaction_emoji_1 TEXT,
                    reaction_emoji_2 TEXT,
                    reaction_emoji_3 TEXT,
                    reaction_mc_1 REAL DEFAULT 1.0,
                    reaction_mc_2 REAL DEFAULT 2.0,
                    reaction_mc_3 REAL DEFAULT 3.0,
                    mc_score_6 REAL DEFAULT 2.0,
                    mc_score_7 REAL DEFAULT 4.0,
                    mc_score_8 REAL DEFAULT 5.0,
                    mc_score_9 REAL DEFAULT 3.0,
                    mc_review_reward REAL DEFAULT 2.0,
                    mc_comment_bonus REAL DEFAULT 1.0,
                    mc_showcase_reward REAL DEFAULT 3.0,
                    txt_bot_name TEXT DEFAULT 'Melee Zone',
                    txt_mc_name TEXT DEFAULT 'MC',
                    txt_pro_role TEXT DEFAULT 'Reviewer',
                    txt_basic_role TEXT DEFAULT 'Basic',
                    txt_welcome TEXT DEFAULT 'Welcome to Melee Zone! You are now on record.',
                    txt_submit_success TEXT DEFAULT 'Your post has been recorded!',
                    txt_review_received TEXT DEFAULT 'Thank you for your review!',
                    txt_showcase TEXT DEFAULT 'Outstanding content featured!',
                    txt_reminder TEXT DEFAULT 'You have a pending review. Please complete it.',
                    txt_panel_title TEXT DEFAULT 'Melee Zone',
                    txt_panel_desc TEXT DEFAULT 'Use the buttons below. All responses are private.',
                    txt_dashboard_btn TEXT DEFAULT 'Dashboard',
                    txt_submission_btn TEXT DEFAULT 'Submission',
                    txt_reviews_btn TEXT DEFAULT 'Reviews',
                    txt_about TEXT DEFAULT '',
                    btn_color_dashboard TEXT DEFAULT 'blurple',
                    btn_color_submission TEXT DEFAULT 'red',
                    btn_color_reviews TEXT DEFAULT 'gray',
                    btn_color_admin_primary TEXT DEFAULT 'red',
                    btn_color_admin_secondary TEXT DEFAULT 'gray'
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    username TEXT,
                    role_type TEXT DEFAULT 'basic',
                    mc_regular REAL DEFAULT 0.0,
                    mc_golden REAL DEFAULT 0.0,
                    mc_assignment REAL DEFAULT 0.0,
                    weekly_submits INTEGER DEFAULT 5,
                    twitter_username TEXT,
                    twitter_changes_used INTEGER DEFAULT 0,
                    ready_for_more INTEGER DEFAULT 0,
                    ready_for_more_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS posts (
                    post_id TEXT PRIMARY KEY,
                    guild_id TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    tweet_link TEXT NOT NULL,
                    week_id TEXT NOT NULL,
                    month_id TEXT NOT NULL DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    final_score REAL,
                    mc_earned REAL DEFAULT 0.0,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS reviews (
                    review_id TEXT PRIMARY KEY,
                    post_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    score INTEGER CHECK(score >= 1 AND score <= 10),
                    twitter_comment TEXT,
                    summary TEXT,
                    week_id TEXT NOT NULL,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(post_id, reviewer_id)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS assignments (
                    assignment_id TEXT PRIMARY KEY,
                    post_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    week_id TEXT NOT NULL,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    due_date TIMESTAMP NOT NULL,
                    reminder_sent INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    completed_at TIMESTAMP,
                    UNIQUE(post_id, reviewer_id)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS mc_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    mc_type TEXT DEFAULT 'regular',
                    reason TEXT,
                    reference_id TEXT,
                    admin_id TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS reaction_credits (
                    id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    admin_id TEXT NOT NULL,
                    emoji TEXT NOT NULL,
                    amount REAL NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            await db.execute('CREATE INDEX IF NOT EXISTS idx_posts_guild_week ON posts(guild_id, week_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_posts_guild_month ON posts(guild_id, month_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id, guild_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_reviews_post ON reviews(post_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_reviews_reviewer_week ON reviews(reviewer_id, week_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_assignments_reviewer_week ON assignments(reviewer_id, week_id)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_mc_tx_user ON mc_transactions(user_id, guild_id)')

            # Safe additive migrations for reward integrity and normalized X links.
            for table, column, typedef in [
                ('posts','x_status_id','TEXT'), ('posts','normalized_url','TEXT'),
                ('posts','required_reviews','INTEGER DEFAULT 3'), ('posts','finalized_at','TEXT'),
                ('assignments','warning_sent_at','TEXT'), ('assignments','reassigned_at','TEXT'),
                ('assignments','assignment_type',"TEXT DEFAULT 'primary'"),
                ('assignments','original_assignment_id','TEXT'),
                ('mc_transactions','reward_key','TEXT'),
                ('guild_config','mc_score_low','REAL DEFAULT 1.0'),
                ('guild_config','mc_score_medium','REAL DEFAULT 3.0'),
                ('guild_config','mc_score_high','REAL DEFAULT 5.0'),
                ('guild_config','mc_submit_completion','REAL DEFAULT 2.0'),
                ('guild_config','rescue_review_limit','INTEGER DEFAULT 3'),
                ('guild_config','warning_grace_hours','INTEGER DEFAULT 12'),
                ('guild_config','min_feedback_length','INTEGER DEFAULT 30'),
                ('guild_config','primary_review_days','INTEGER DEFAULT 5'),
                ('guild_config','total_review_days','INTEGER DEFAULT 7')]:
                try:
                    await db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {typedef}')
                except Exception as exc:
                    if 'duplicate column' not in str(exc).lower():
                        raise
            try:
                await db.execute("ALTER TABLE guild_config ADD COLUMN last_weekly_cycle TEXT")
            except Exception as exc:
                if 'duplicate column' not in str(exc).lower(): raise
            await db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_reward_key_unique ON mc_transactions(reward_key) WHERE reward_key IS NOT NULL')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_posts_status_author ON posts(guild_id, author_id, x_status_id)')
            async with db.execute("SELECT post_id, tweet_link FROM posts WHERE x_status_id IS NULL OR x_status_id = ''") as cur:
                for row in await cur.fetchall():
                    match = re.search(r'/(?:status)/(\d+)', row['tweet_link'] or '', re.I)
                    if match:
                        sid = match.group(1)
                        await db.execute('UPDATE posts SET x_status_id=?, normalized_url=? WHERE post_id=?', (sid, f'https://x.com/i/status/{sid}', row['post_id']))
            await db.execute('''CREATE TABLE IF NOT EXISTS submitted_status_keys (
                guild_id TEXT NOT NULL, author_id TEXT NOT NULL, x_status_id TEXT NOT NULL,
                post_id TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(guild_id,author_id,x_status_id))''')
            await db.execute('''INSERT OR IGNORE INTO submitted_status_keys(guild_id,author_id,x_status_id,post_id)
                SELECT guild_id,author_id,x_status_id,post_id FROM posts WHERE x_status_id IS NOT NULL AND x_status_id!='' ORDER BY submitted_at''')

            # Quiz tables
            await db.execute('''
                CREATE TABLE IF NOT EXISTS quizzes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL, article_slug TEXT NOT NULL,
                    title TEXT NOT NULL, questions_json TEXT NOT NULL,
                    loaded_by TEXT, loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS quiz_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL, user_id TEXT NOT NULL, quiz_id INTEGER NOT NULL,
                    questions_json TEXT NOT NULL, completed INTEGER DEFAULT 0,
                    started_at TIMESTAMP NOT NULL
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS quiz_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL, user_id TEXT NOT NULL, quiz_id INTEGER NOT NULL,
                    session_id INTEGER, correct_count INTEGER NOT NULL, total_questions INTEGER NOT NULL,
                    score_pct REAL NOT NULL, mc_earned REAL DEFAULT 0, elapsed_seconds INTEGER DEFAULT 0,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, user_id, quiz_id)
                )
            ''')

            # Update 2 tables — Snapshot & Assignment Manager
            await db.execute('''
                CREATE TABLE IF NOT EXISTS snapshot_awards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL, guild_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    amount REAL NOT NULL, mc_type TEXT NOT NULL,
                    awarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(snapshot_id, user_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS assignments_mgr (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id TEXT NOT NULL, name TEXT NOT NULL, body TEXT NOT NULL,
                    thread_id TEXT, cooldown_seconds INTEGER DEFAULT 0, is_recurring INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active', created_by TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, closed_at TIMESTAMP
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS assignment_cooldowns (
                    thread_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    last_msg_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (thread_id, user_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS assignment_participants (
                    assignment_id INTEGER NOT NULL, user_id TEXT NOT NULL,
                    first_post_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (assignment_id, user_id)
                )
            ''')

            await db.commit()
        await self.init_operations()
        await self.init_support()
        await self.init_governance()
        log.info("Database ready")

    async def get_guild_config(self, guild_id: str) -> Optional[Dict]:
        db = await self._get_conn()
        async with self._lock:
            async with db.execute('SELECT * FROM guild_config WHERE guild_id = ?', (guild_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def create_guild_config(self, guild_id: str):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)', (guild_id,))
            await db.commit()

    async def update_guild_config(self, guild_id: str, **kwargs):
        """Trusted internal writer. User-facing configuration must use governance."""
        current = await self.get_guild_config(guild_id) or {}
        if set(kwargs) - set(current):
            raise ValueError('Unknown configuration field.')
        from runtime_utils import valid_amount
        for key,value in tuple(kwargs.items()):
            if key.startswith(('mc_','reaction_mc_','quiz_mc_')) and key!='quiz_mc_min_pct':
                kwargs[key]=valid_amount(value,allow_zero=True)
        if 'review_window_days' in kwargs and 'total_review_days' not in kwargs:
            kwargs['total_review_days']=kwargs['review_window_days']
        if 'total_review_days' in kwargs:
            kwargs['review_window_days']=kwargs['total_review_days']
        if not kwargs:
            return
        db = await self._get_conn()
        async with self._lock:
            fields = ', '.join(f"{k} = ?" for k in kwargs)
            values = list(kwargs.values()) + [guild_id]
            await db.execute(f"UPDATE guild_config SET {fields} WHERE guild_id = ?", values)
            await db.commit()

    async def edit_task_cooldown(self, guild_id, assignment_id, cooldown_seconds):
        seconds = int(cooldown_seconds)
        if not 0 <= seconds <= 7 * 86400:
            raise ValueError('Task cooldown must be between zero and seven days.')
        db = await self._get_conn()
        async with self._lock:
            cursor = await db.execute("UPDATE assignments_mgr SET cooldown_seconds=? WHERE guild_id=? AND id=? AND status='active'",
                                      (seconds, str(guild_id), int(assignment_id)))
            await db.commit()
            return bool(cursor.rowcount)

    async def is_guild_configured(self, guild_id: str) -> bool:
        config = await self.get_guild_config(guild_id)
        return config is not None and config.get('is_configured') == 1

    async def get_or_create_user(self, user_id: str, guild_id: str,
                                  username: str, role_type: str = 'basic') -> Dict:
        db = await self._get_conn()
        existing=await self.get_user(user_id,guild_id)
        if existing:
            return existing
        async with self._lock:
            config = await self._governance_config(db, guild_id)
            max_s = config.get('max_submits_per_week', 5) if config else 5
            await db.execute(
                'INSERT OR IGNORE INTO users (user_id, guild_id, username, role_type, weekly_submits) VALUES (?, ?, ?, ?, ?)',
                (user_id, guild_id, username, role_type, max_s)
            )
            await db.commit()
        return await self.get_user(user_id,guild_id) or {'user_id':user_id,'guild_id':guild_id,
            'username':username,'role_type':role_type,'mc_regular':0.0,'mc_golden':0.0,'mc_assignment':0.0,
            'weekly_submits':max_s,'twitter_username':None,'twitter_changes_used':0}

    async def get_user(self, user_id: str, guild_id: str) -> Optional[Dict]:
        db = await self._get_conn()
        async with self._lock:
            async with db.execute('SELECT * FROM users WHERE user_id = ? AND guild_id = ?', (user_id, guild_id)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_all_users(self, guild_id: str) -> List[Dict]:
        db = await self._get_conn()
        async with self._lock:
            async with db.execute('SELECT * FROM users WHERE guild_id = ?', (guild_id,)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def update_user_twitter(self, user_id: str, guild_id: str, twitter_username: str):
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                'UPDATE users SET twitter_username = ?, twitter_changes_used = twitter_changes_used + 1 WHERE user_id = ? AND guild_id = ?',
                (twitter_username, user_id, guild_id)
            )
            await db.commit()

    async def twitter_already_registered(self, guild_id: str, twitter_username: str) -> bool:
        db = await self._get_conn()
        async with db.execute(
            'SELECT 1 FROM users WHERE guild_id = ? AND LOWER(twitter_username) = LOWER(?) LIMIT 1',
            (guild_id, twitter_username)
        ) as cur:
            return await cur.fetchone() is not None

    async def reset_weekly_submits(self, guild_id: str, amount: int = 5):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('UPDATE users SET weekly_submits = ? WHERE guild_id = ?', (amount, guild_id))
            await db.commit()

    async def decrement_submits(self, user_id: str, guild_id: str):
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                'UPDATE users SET weekly_submits = MAX(0, weekly_submits - 1) WHERE user_id = ? AND guild_id = ?',
                (user_id, guild_id)
            )
            await db.commit()

    async def set_ready_for_more(self, user_id: str, guild_id: str, value: int):
        db = await self._get_conn()
        async with self._lock:
            ts = datetime.now().isoformat() if value == 1 else None
            await db.execute(
                'UPDATE users SET ready_for_more = ?, ready_for_more_at = ? WHERE user_id = ? AND guild_id = ?',
                (value, ts, user_id, guild_id)
            )
            await db.commit()

    async def get_ready_for_more_users(self, guild_id: str) -> List[Dict]:
        db = await self._get_conn()
        async with db.execute(
            'SELECT * FROM users WHERE guild_id = ? AND ready_for_more = 1 ORDER BY ready_for_more_at ASC', (guild_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def create_post(self, author_id: str, guild_id: str, tweet_link: str, week_id: str, x_status_id: str = None, normalized_url: str = None, required_reviews: int = 3) -> str:
        post_id = str(uuid.uuid4())
        month_id = datetime.now().strftime('%Y-%m')
        db = await self._get_conn()
        async with self._lock:
            try:
                if x_status_id:
                    await db.execute('INSERT INTO submitted_status_keys(guild_id,author_id,x_status_id,post_id) VALUES (?,?,?,?)',(guild_id,author_id,x_status_id,post_id))
                await db.execute('INSERT INTO posts (post_id, guild_id, author_id, tweet_link, week_id, month_id, x_status_id, normalized_url, required_reviews) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                 (post_id, guild_id, author_id, tweet_link, week_id, month_id, x_status_id, normalized_url, required_reviews))
                await db.commit()
            except Exception as exc:
                await db.rollback()
                if x_status_id and 'unique' in str(exc).lower(): raise DuplicateSubmissionError()
                raise
        return post_id

    async def has_user_submitted_status(self, author_id: str, guild_id: str, status_id: str) -> bool:
        db = await self._get_conn()
        async with db.execute('SELECT 1 FROM posts WHERE author_id=? AND guild_id=? AND x_status_id=? LIMIT 1', (author_id,guild_id,status_id)) as cur:
            return await cur.fetchone() is not None

    async def get_post(self, post_id: str) -> Optional[Dict]:
        db = await self._get_conn()
        async with db.execute('SELECT * FROM posts WHERE post_id = ?', (post_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_posts_by_week(self, guild_id: str, week_id: str, status: Optional[str] = None) -> List[Dict]:
        db = await self._get_conn()
        if status:
            async with db.execute(
                'SELECT * FROM posts WHERE guild_id = ? AND week_id = ? AND status = ? ORDER BY submitted_at',
                (guild_id, week_id, status)
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
        async with db.execute(
            'SELECT * FROM posts WHERE guild_id = ? AND week_id = ? ORDER BY submitted_at',
            (guild_id, week_id)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_posts_by_author(self, author_id: str, guild_id: str, limit: int = 50, offset: int = 0) -> List[Dict]:
        db = await self._get_conn()
        async with db.execute(
            'SELECT * FROM posts WHERE author_id = ? AND guild_id = ? ORDER BY submitted_at DESC LIMIT ? OFFSET ?',
            (author_id, guild_id, limit, offset)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_posts_by_author_count(self, author_id: str, guild_id: str) -> int:
        db = await self._get_conn()
        async with db.execute('SELECT COUNT(*) FROM posts WHERE author_id = ? AND guild_id = ?', (author_id, guild_id)) as cur:
            return (await cur.fetchone())[0]

    async def get_pending_posts_for_assignment(self, guild_id: str, week_id: str, min_reviews: int = 5) -> List[Dict]:
        db = await self._get_conn()
        async with db.execute('''
            SELECT p.* FROM posts p
            LEFT JOIN (SELECT post_id, COUNT(*) as ac FROM assignments WHERE status != 'removed' GROUP BY post_id) a
            ON p.post_id = a.post_id
            WHERE p.guild_id = ? AND p.week_id = ? AND p.status IN ('pending','assigned')
            AND (a.ac IS NULL OR a.ac < ?)
        ''', (guild_id, week_id, min_reviews)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_all_open_posts_for_assignment(self, guild_id: str) -> List[Dict]:
        db=await self._get_conn()
        async with db.execute('''SELECT p.*,COALESCE(r.cnt,0) review_count,COALESCE(a.cnt,0) active_assignment_count FROM posts p
            LEFT JOIN (SELECT post_id,COUNT(*) cnt FROM reviews GROUP BY post_id) r ON r.post_id=p.post_id
            LEFT JOIN (SELECT post_id,COUNT(*) cnt FROM assignments WHERE status IN ('pending','warning') GROUP BY post_id) a ON a.post_id=p.post_id
            WHERE p.guild_id=? AND p.finalized_at IS NULL AND p.status IN ('pending','assigned')
            AND COALESCE(r.cnt,0)<COALESCE(p.required_reviews,3)
            ORDER BY p.submitted_at ASC''',(guild_id,)) as cur:return [dict(r) for r in await cur.fetchall()]

    async def update_post_status(self, post_id: str, status: str, final_score: Optional[float] = None, mc_earned: Optional[float] = None):
        db = await self._get_conn()
        async with self._lock:
            if final_score is not None:
                await db.execute('UPDATE posts SET status = ?, final_score = ?, mc_earned = ? WHERE post_id = ?', (status, final_score, mc_earned, post_id))
            else:
                await db.execute('UPDATE posts SET status = ? WHERE post_id = ?', (status, post_id))
            await db.commit()

    async def finalize_post_once(self, post_id: str, status: str, final_score: float, mc_earned: float) -> bool:
        db = await self._get_conn()
        async with self._lock:
            cur = await db.execute('UPDATE posts SET status=?,final_score=?,mc_earned=?,finalized_at=? WHERE post_id=? AND finalized_at IS NULL',
                                   (status,final_score,mc_earned,datetime.now().isoformat(),post_id))
            await db.commit()
            return cur.rowcount == 1

    async def create_review(self, post_id: str, reviewer_id: str, score: int, twitter_comment: Optional[str], summary: Optional[str], week_id: str) -> str:
        review_id = str(uuid.uuid4())
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                'INSERT OR IGNORE INTO reviews (review_id, post_id, reviewer_id, score, twitter_comment, summary, week_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (review_id, post_id, reviewer_id, score, twitter_comment, summary, week_id)
            )
            await db.commit()
        return review_id

    async def submit_review_atomic(self, assignment_id: str, reviewer_id: str, score: int,
                                   twitter_comment: Optional[str], summary: str, week_id: str):
        """Insert the review and complete its assignment as one transaction."""
        review_id = str(uuid.uuid4())
        db = await self._get_conn()
        async with self._lock:
            await db.execute('BEGIN IMMEDIATE')
            try:
                async with db.execute('SELECT post_id,status FROM assignments WHERE assignment_id=? AND reviewer_id=?', (assignment_id,reviewer_id)) as cur:
                    assignment = await cur.fetchone()
                if not assignment:
                    await db.rollback(); return {'status':'not_found'}
                if assignment['status'] not in ('pending','warning'):
                    await db.rollback(); return {'status':'already_completed'}
                try:
                    await db.execute('INSERT INTO reviews (review_id,post_id,reviewer_id,score,twitter_comment,summary,week_id) VALUES (?,?,?,?,?,?,?)',
                                     (review_id,assignment['post_id'],reviewer_id,score,twitter_comment,summary,week_id))
                except Exception as exc:
                    if 'unique' in str(exc).lower():
                        await db.rollback(); return {'status':'duplicate'}
                    raise
                await db.execute("UPDATE assignments SET status='completed',completed_at=? WHERE assignment_id=?", (datetime.now().isoformat(),assignment_id))
                await db.commit()
                return {'status':'created','review_id':review_id,'post_id':assignment['post_id']}
            except Exception:
                await db.rollback()
                raise

    async def get_reviews_by_post(self, post_id: str) -> List[Dict]:
        db = await self._get_conn()
        async with db.execute('SELECT * FROM reviews WHERE post_id = ?', (post_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_reviews_by_reviewer(self, reviewer_id: str, week_id: str) -> List[Dict]:
        db = await self._get_conn()
        async with db.execute('SELECT * FROM reviews WHERE reviewer_id = ? AND week_id = ?', (reviewer_id, week_id)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_reviews_received_by_user(self, author_id: str, guild_id: str, limit: int = 30) -> List[Dict]:
        db = await self._get_conn()
        async with db.execute('''
            SELECT r.*, p.tweet_link FROM reviews r
            JOIN posts p ON r.post_id = p.post_id
            WHERE p.author_id = ? AND p.guild_id = ?
            ORDER BY r.submitted_at DESC LIMIT ?
        ''', (author_id, guild_id, limit)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_average_score_given(self, reviewer_id: str, since: datetime) -> Optional[float]:
        db = await self._get_conn()
        async with db.execute('SELECT AVG(score) FROM reviews WHERE reviewer_id = ? AND submitted_at > ?', (reviewer_id, since.isoformat())) as cur:
            result = await cur.fetchone()
            return result[0] if result and result[0] else None

    async def get_review_count(self, week_id: str) -> int:
        db = await self._get_conn()
        async with db.execute('SELECT COUNT(*) FROM reviews WHERE week_id = ?', (week_id,)) as cur:
            return (await cur.fetchone())[0]

    async def create_assignment(self, post_id: str, reviewer_id: str, week_id: str, due_date: datetime) -> str:
        return await self.create_review_assignment_atomic(post_id,reviewer_id,week_id,due_date)

    async def get_reviewer_ids_for_post(self, post_id: str):
        db=await self._get_conn()
        async with db.execute('SELECT reviewer_id FROM assignments WHERE post_id=?',(post_id,)) as cur:return {r[0] for r in await cur.fetchall()}

    async def get_assignment_by_partial_id(self, partial_id: str, reviewer_id: str) -> Optional[Dict]:
        db = await self._get_conn()
        async with db.execute('''
            SELECT a.*, p.tweet_link, p.author_id FROM assignments a
            JOIN posts p ON a.post_id = p.post_id
            WHERE a.reviewer_id = ? AND a.assignment_id LIKE ? LIMIT 1
        ''', (reviewer_id, f'{partial_id}%')) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_assignments_by_reviewer(self, reviewer_id: str, week_id: str, status: Optional[str] = None) -> List[Dict]:
        db = await self._get_conn()
        if status:
            async with db.execute('''
                SELECT a.*, p.tweet_link, p.author_id FROM assignments a
                JOIN posts p ON a.post_id = p.post_id
                WHERE a.reviewer_id = ? AND a.week_id = ? AND a.status = ?
            ''', (reviewer_id, week_id, status)) as cur:
                return [dict(r) for r in await cur.fetchall()]
        async with db.execute('''
            SELECT a.*, p.tweet_link, p.author_id FROM assignments a
            JOIN posts p ON a.post_id = p.post_id
            WHERE a.reviewer_id = ? AND a.week_id = ?
        ''', (reviewer_id, week_id)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def complete_assignment(self, assignment_id: str):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('UPDATE assignments SET status = ?, completed_at = ? WHERE assignment_id = ?', ('completed', datetime.now().isoformat(), assignment_id))
            await db.commit()

    async def mark_reminder_sent(self, assignment_id: str):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('UPDATE assignments SET reminder_sent = 1 WHERE assignment_id = ?', (assignment_id,))
            await db.commit()

    async def get_assignments_for_rescue(self, guild_id: str, warning_before: datetime):
        db = await self._get_conn()
        async with db.execute('''SELECT a.*,p.tweet_link,p.guild_id FROM assignments a JOIN posts p ON p.post_id=a.post_id
            WHERE p.guild_id=? AND a.status='pending' AND a.assigned_at<=?''', (guild_id,warning_before.isoformat())) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def mark_assignment_warning(self, assignment_id: str, when: datetime):
        db=await self._get_conn()
        async with self._lock:
            cur=await db.execute("UPDATE assignments SET status='warning',warning_sent_at=? WHERE assignment_id=? AND status='pending'",(when.isoformat(),assignment_id));await db.commit();return cur.rowcount==1

    async def get_expired_warnings(self, guild_id: str, cutoff: datetime):
        db=await self._get_conn()
        async with db.execute('''SELECT a.*,p.tweet_link,p.guild_id,p.author_id FROM assignments a JOIN posts p ON p.post_id=a.post_id
            WHERE p.guild_id=? AND a.status='warning' AND a.warning_sent_at<=?''',(guild_id,cutoff.isoformat())) as cur:return [dict(r) for r in await cur.fetchall()]

    async def mark_assignment_reassigned(self, assignment_id: str):
        db=await self._get_conn()
        async with self._lock:
            cur=await db.execute("UPDATE assignments SET status='reassigned',reassigned_at=? WHERE assignment_id=? AND status='warning'",(datetime.now().isoformat(),assignment_id));await db.commit();return cur.rowcount==1

    async def get_overdue_assignments(self, hours: int) -> List[Dict]:
        cutoff = datetime.now() - timedelta(hours=hours)
        db = await self._get_conn()
        async with db.execute('''
            SELECT a.*, p.tweet_link, p.guild_id FROM assignments a
            JOIN posts p ON a.post_id = p.post_id
            WHERE a.status = 'pending' AND a.reminder_sent = 0 AND a.assigned_at < ?
        ''', (cutoff.isoformat(),)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_pending_assignments_count(self, guild_id: str, week_id: str) -> int:
        db = await self._get_conn()
        async with db.execute('''
            SELECT COUNT(*) FROM assignments a JOIN posts p ON a.post_id = p.post_id
            WHERE p.guild_id = ? AND a.week_id = ? AND a.status = 'pending'
        ''', (guild_id, week_id)) as cur:
            return (await cur.fetchone())[0]

    async def get_completed_assignments_count(self, guild_id: str, week_id: str) -> int:
        db = await self._get_conn()
        async with db.execute('''
            SELECT COUNT(*) FROM assignments a JOIN posts p ON a.post_id = p.post_id
            WHERE p.guild_id = ? AND a.week_id = ? AND a.status = 'completed'
        ''', (guild_id, week_id)) as cur:
            return (await cur.fetchone())[0]

    async def add_mc(self, user_id: str, guild_id: str, amount: float, mc_type: str, reason: str, reference_id: Optional[str] = None, admin_id: Optional[str] = None, reward_key: Optional[str] = None) -> bool:
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                result = await self._award_row(db,user_id=user_id,guild_id=guild_id,username='',amount=amount,
                    mc_type=mc_type,reason=reason,reference_id=reference_id,admin_id=admin_id,reward_key=reward_key)
                await db.commit()
                return result
            except BaseException:
                await db.rollback()
                raise

    async def get_mc_transactions(self, user_id: str, guild_id: str, limit: int = 10) -> List[Dict]:
        db = await self._get_conn()
        async with self._lock:
            async with db.execute('SELECT * FROM mc_transactions WHERE user_id = ? AND guild_id = ? ORDER BY timestamp DESC LIMIT ?', (user_id, guild_id, limit)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def reward_already_given(self, user_id: str, guild_id: str, reason_contains: str) -> bool:
        db = await self._get_conn()
        async with db.execute('SELECT 1 FROM mc_transactions WHERE user_id = ? AND guild_id = ? AND reason LIKE ? LIMIT 1', (user_id, guild_id, f'%{reason_contains}%')) as cur:
            return await cur.fetchone() is not None

    async def get_leaderboard(self, guild_id: str, limit: int = 10) -> List[Dict]:
        db = await self._get_conn()
        async with self._lock:
            async with db.execute('''
                SELECT user_id, username, twitter_username, mc_regular, mc_golden, mc_assignment, (mc_regular + mc_golden + mc_assignment) as total_mc
                FROM users WHERE guild_id = ? ORDER BY total_mc DESC LIMIT ?
            ''', (guild_id, limit)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def get_leaderboard_period(self, guild_id: str, since: datetime, limit: int = 10) -> List[Dict]:
        db = await self._get_conn()
        async with db.execute('''
            SELECT t.user_id, u.username, u.twitter_username, SUM(t.amount) as earned
            FROM mc_transactions t JOIN users u ON t.user_id = u.user_id AND t.guild_id = u.guild_id
            WHERE t.guild_id = ? AND t.timestamp >= ?
            GROUP BY t.user_id ORDER BY earned DESC LIMIT ?
        ''', (guild_id, since.isoformat(), limit)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_user_rank_alltime(self, user_id: str, guild_id: str) -> int:
        db = await self._get_conn()
        async with db.execute('''
            SELECT COUNT(*) FROM users WHERE guild_id = ? AND (mc_regular + mc_golden + mc_assignment) > (
                SELECT mc_regular + mc_golden + mc_assignment FROM users WHERE user_id = ? AND guild_id = ?
            )
        ''', (guild_id, user_id, guild_id)) as cur:
            return (await cur.fetchone())[0] + 1

    async def get_user_mc_period(self, user_id: str, guild_id: str, since: datetime) -> float:
        db = await self._get_conn()
        async with db.execute('SELECT COALESCE(SUM(amount), 0) FROM mc_transactions WHERE user_id = ? AND guild_id = ? AND timestamp >= ?', (user_id, guild_id, since.isoformat())) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0.0

    async def get_user_rank_period(self, user_id: str, guild_id: str, since: datetime) -> int:
        db = await self._get_conn()
        cur = await db.execute('SELECT COALESCE(SUM(amount),0) FROM mc_transactions WHERE user_id = ? AND guild_id = ? AND timestamp >= ?', (user_id, guild_id, since.isoformat()))
        row = await cur.fetchone()
        user_total = row[0] if row else 0
        async with db.execute('''
            SELECT COUNT(*) FROM (
                SELECT t.user_id, SUM(t.amount) as earned FROM mc_transactions t
                WHERE t.guild_id = ? AND t.timestamp >= ? GROUP BY t.user_id HAVING earned > ?
            )
        ''', (guild_id, since.isoformat(), user_total)) as cur2:
            row2 = await cur2.fetchone()
            return (row2[0] if row2 else 0) + 1

    async def get_stalled_posts(self, guild_id: str, week_id: str, min_reviews: int = 5) -> List[Dict]:
        db = await self._get_conn()
        async with db.execute('''
            SELECT p.*, COALESCE(r.cnt, 0) as review_count FROM posts p
            LEFT JOIN (SELECT post_id, COUNT(*) as cnt FROM reviews GROUP BY post_id) r ON p.post_id = r.post_id
            WHERE p.guild_id = ? AND p.week_id = ? AND p.status NOT IN ('approved','rejected')
            AND COALESCE(r.cnt, 0) < ?
        ''', (guild_id, week_id, min_reviews)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def log_reaction_credit(self, message_id: str, channel_id: str, author_id: str, admin_id: str, emoji: str, amount: float):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('INSERT INTO reaction_credits VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (str(uuid.uuid4()), message_id, channel_id, author_id, admin_id, emoji, amount, datetime.now().isoformat()))
            await db.commit()

    async def has_reaction_credit(self, message_id: str, admin_id: str, emoji: str) -> bool:
        db = await self._get_conn()
        async with db.execute('SELECT 1 FROM reaction_credits WHERE message_id = ? AND admin_id = ? AND emoji = ?', (message_id, admin_id, emoji)) as cur:
            return await cur.fetchone() is not None

    async def get_posts_range(self, guild_id: str, date_from: datetime, date_to: datetime) -> List[Dict]:
        db = await self._get_conn()
        async with db.execute('SELECT * FROM posts WHERE guild_id = ? AND submitted_at >= ? AND submitted_at <= ? ORDER BY submitted_at', (guild_id, date_from.isoformat(), date_to.isoformat())) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def create_quiz(self, guild_id: str, article_slug: str, title: str,
                          questions: list, loaded_by: str):
        import json
        db = await self._get_conn()
        async with self._lock:
            await db.execute('UPDATE quizzes SET is_active = 0 WHERE guild_id = ?', (guild_id,))
            await db.execute(
                'INSERT INTO quizzes (guild_id, article_slug, title, questions_json, loaded_by, is_active) VALUES (?, ?, ?, ?, ?, 1)',
                (guild_id, article_slug, title, json.dumps(questions), loaded_by)
            )
            await db.commit()

    async def get_active_quiz(self, guild_id: str):
        db = await self._get_conn()
        async with db.execute(
            'SELECT * FROM quizzes WHERE guild_id = ? AND is_active = 1 ORDER BY loaded_at DESC LIMIT 1',
            (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def create_quiz_session(self, guild_id: str, user_id: str, quiz_id: int,
                                   questions: list, started_at) -> int:
        import json
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                'INSERT INTO quiz_sessions (guild_id, user_id, quiz_id, questions_json, started_at) VALUES (?, ?, ?, ?, ?)',
                (guild_id, user_id, quiz_id, json.dumps(questions), started_at.isoformat())
            )
            await db.commit()
        async with db.execute(
            'SELECT id FROM quiz_sessions WHERE guild_id = ? AND user_id = ? AND quiz_id = ? ORDER BY started_at DESC LIMIT 1',
            (guild_id, user_id, quiz_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def complete_quiz_session(self, session_id: int):
        db = await self._get_conn()
        async with self._lock:
            await db.execute('UPDATE quiz_sessions SET completed = 1 WHERE id = ?', (session_id,))
            await db.commit()

    async def save_quiz_result(self, guild_id: str, user_id: str, quiz_id: int,
                                session_id: int, correct: int, total: int,
                                score_pct: float, mc_earned: float,
                                elapsed_seconds: int, completed_at):
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                'INSERT OR IGNORE INTO quiz_results '
                '(guild_id, user_id, quiz_id, session_id, correct_count, total_questions, score_pct, mc_earned, elapsed_seconds, completed_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (guild_id, user_id, quiz_id, session_id, correct, total, score_pct, mc_earned, elapsed_seconds, completed_at.isoformat())
            )
            await db.commit()

    async def get_quiz_result(self, guild_id: str, user_id: str, quiz_id: int):
        db = await self._get_conn()
        async with db.execute(
            'SELECT qr.*, q.title FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.guild_id = ? AND qr.user_id = ? AND qr.quiz_id = ?',
            (guild_id, user_id, quiz_id)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_user_quiz_results(self, guild_id: str, user_id: str, limit: int = 10):
        db = await self._get_conn()
        async with db.execute(
            'SELECT qr.*, q.title, q.article_slug FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.guild_id = ? AND qr.user_id = ? ORDER BY qr.completed_at DESC LIMIT ?',
            (guild_id, user_id, limit)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_all_quiz_results(self, guild_id: str, quiz_id: int):
        db = await self._get_conn()
        async with db.execute(
            'SELECT qr.*, q.title FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.guild_id = ? AND qr.quiz_id = ? ORDER BY qr.score_pct DESC',
            (guild_id, quiz_id)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_quiz_stats(self, guild_id: str, quiz_id: int) -> dict:
        db = await self._get_conn()
        async with db.execute(
            'SELECT COUNT(*) as total_participants, SUM(CASE WHEN score_pct >= 70 THEN 1 ELSE 0 END) as passed, AVG(score_pct) as avg_score, SUM(mc_earned) as total_mc, AVG(elapsed_seconds) as avg_time FROM quiz_results WHERE guild_id = ? AND quiz_id = ?',
            (guild_id, quiz_id)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else {'total_participants': 0, 'passed': 0, 'avg_score': 0, 'total_mc': 0, 'avg_time': 0}

    async def get_user_quiz_summary(self, guild_id: str, user_id: str) -> dict:
        db = await self._get_conn()
        async with db.execute(
            'SELECT COUNT(*) as total_quizzes, SUM(CASE WHEN score_pct >= 70 THEN 1 ELSE 0 END) as passed, AVG(score_pct) as avg_score, SUM(mc_earned) as total_mc_from_quiz FROM quiz_results WHERE guild_id = ? AND user_id = ?',
            (guild_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else {'total_quizzes': 0, 'passed': 0, 'avg_score': 0, 'total_mc_from_quiz': 0}

    # ══════════════════════════════════════════════════════════════
    # UPDATE 2 — Raffle, Snapshot, Assignment Manager
    # ══════════════════════════════════════════════════════════════

    # ── Snapshot ───────────────────────────────────────────────────
    async def snapshot_award_exists(self, snapshot_id: str, user_id: str) -> bool:
        db = await self._get_conn()
        async with db.execute(
            'SELECT 1 FROM snapshot_awards WHERE snapshot_id = ? AND user_id = ? LIMIT 1',
            (snapshot_id, user_id)
        ) as cur:
            return await cur.fetchone() is not None

    async def record_snapshot_award(self, snapshot_id: str, guild_id: str,
                                     user_id: str, amount: float, mc_type: str):
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                'INSERT OR IGNORE INTO snapshot_awards (snapshot_id, guild_id, user_id, amount, mc_type) '
                'VALUES (?, ?, ?, ?, ?)',
                (snapshot_id, guild_id, user_id, amount, mc_type)
            )
            await db.commit()

    # ── Assignment Manager ─────────────────────────────────────────
    async def create_assignment_mgr(self, guild_id: str, name: str, body: str,
                                     thread_id: str, cooldown_seconds: int,
                                     is_recurring: int, created_by: str) -> int:
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                'INSERT INTO assignments_mgr (guild_id, name, body, thread_id, cooldown_seconds, is_recurring, created_by) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (guild_id, name, body, thread_id, cooldown_seconds, is_recurring, created_by)
            )
            await db.commit()
        async with db.execute(
            'SELECT id FROM assignments_mgr WHERE guild_id = ? AND thread_id = ? ORDER BY created_at DESC LIMIT 1',
            (guild_id, thread_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_assignment_by_thread(self, thread_id: str):
        db = await self._get_conn()
        async with db.execute(
            'SELECT * FROM assignments_mgr WHERE thread_id = ?', (thread_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_assignments_mgr(self, guild_id: str, status: str = None):
        db = await self._get_conn()
        if status:
            async with db.execute(
                'SELECT * FROM assignments_mgr WHERE guild_id = ? AND status = ? ORDER BY created_at DESC',
                (guild_id, status)
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]
        async with db.execute(
            'SELECT * FROM assignments_mgr WHERE guild_id = ? ORDER BY created_at DESC',
            (guild_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def close_assignment_mgr(self, assignment_id: int):
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                "UPDATE assignments_mgr SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (assignment_id,)
            )
            await db.commit()

    async def get_assignment_participant_count(self, assignment_id: int) -> int:
        db = await self._get_conn()
        async with db.execute(
            'SELECT COUNT(*) FROM assignment_participants WHERE assignment_id = ?',
            (assignment_id,)
        ) as cur:
            return (await cur.fetchone())[0]

    async def record_assignment_participant(self, assignment_id: int, user_id: str):
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                'INSERT OR IGNORE INTO assignment_participants (assignment_id, user_id) VALUES (?, ?)',
                (assignment_id, user_id)
            )
            await db.commit()

    # ── Assignment cooldowns ───────────────────────────────────────
    async def get_assignment_cooldown(self, thread_id: str, user_id: str):
        db = await self._get_conn()
        async with db.execute(
            'SELECT last_msg_at FROM assignment_cooldowns WHERE thread_id = ? AND user_id = ?',
            (thread_id, user_id)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def set_assignment_cooldown(self, thread_id: str, user_id: str, ts: str):
        db = await self._get_conn()
        async with self._lock:
            await db.execute(
                'INSERT INTO assignment_cooldowns (thread_id, user_id, last_msg_at) VALUES (?, ?, ?) '
                'ON CONFLICT(thread_id, user_id) DO UPDATE SET last_msg_at = ?',
                (thread_id, user_id, ts, ts)
            )
            await db.commit()
