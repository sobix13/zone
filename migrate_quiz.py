"""
migrate_quiz.py — Run ONCE on VPS to add quiz feature to Melee Zone bot.
Usage: python3 migrate_quiz.py
"""
import asyncio
import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'bot.db')


async def migrate():
    print(f"Migrating: {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:

        # ── guild_config new columns ──────────────────────────────────
        new_cols = [
            ("quiz_pass_role_id", "TEXT"),
            ("quiz_mc_40",        "REAL DEFAULT 1.0"),
            ("quiz_mc_70",        "REAL DEFAULT 2.0"),
            ("quiz_mc_80",        "REAL DEFAULT 3.0"),
            ("quiz_mc_90",        "REAL DEFAULT 5.0"),
            ("quiz_mc_min_pct",   "REAL DEFAULT 40.0"),
        ]
        for col, typedef in new_cols:
            try:
                await db.execute(f"ALTER TABLE guild_config ADD COLUMN {col} {typedef}")
                print(f"  ✅ Added column: {col}")
            except Exception:
                print(f"  ⏭  Skip {col} (already exists)")

        # ── quizzes table ─────────────────────────────────────────────
        await db.execute('''
            CREATE TABLE IF NOT EXISTS quizzes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                article_slug TEXT NOT NULL,
                title       TEXT NOT NULL,
                questions_json TEXT NOT NULL,
                loaded_by   TEXT,
                loaded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active   INTEGER DEFAULT 1
            )
        ''')
        print("  ✅ Table: quizzes")

        # ── quiz_sessions table ───────────────────────────────────────
        await db.execute('''
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                quiz_id     INTEGER NOT NULL,
                questions_json TEXT NOT NULL,
                completed   INTEGER DEFAULT 0,
                started_at  TIMESTAMP NOT NULL
            )
        ''')
        print("  ✅ Table: quiz_sessions")

        # ── quiz_results table ────────────────────────────────────────
        await db.execute('''
            CREATE TABLE IF NOT EXISTS quiz_results (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id        TEXT NOT NULL,
                user_id         TEXT NOT NULL,
                quiz_id         INTEGER NOT NULL,
                session_id      INTEGER,
                correct_count   INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                score_pct       REAL NOT NULL,
                mc_earned       REAL DEFAULT 0,
                elapsed_seconds INTEGER DEFAULT 0,
                completed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, user_id, quiz_id)
            )
        ''')
        print("  ✅ Table: quiz_results")

        await db.commit()
        print("\n✅ Migration complete. No existing data was changed.")
        print("   Next: python3 bot.py (or systemctl restart melee-zone)")


if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        print(f"ERROR: bot.db not found at {DB_PATH}")
        print("Run this script from /root/Melee-Zone/")
        exit(1)
    asyncio.run(migrate())
