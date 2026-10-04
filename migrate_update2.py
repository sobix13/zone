"""
migrate_update2.py — Adds Raffle Role, MC Assignment type, Snapshot, Assignment Manager.
Run ONCE on VPS: python3 migrate_update2.py
Safe — only adds columns/tables, never touches existing data.
"""
import asyncio
import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'bot.db')


async def migrate():
    print(f"Migrating: {DB_PATH}")
    async with aiosqlite.connect(DB_PATH) as db:

        # ── users: mc_assignment column ───────────────────────────────
        try:
            await db.execute("ALTER TABLE users ADD COLUMN mc_assignment REAL DEFAULT 0.0")
            print("  ✅ users.mc_assignment")
        except Exception:
            print("  ⏭  users.mc_assignment (exists)")

        # ── guild_config new columns ──────────────────────────────────
        cols = [
            ("raffle_role_id",         "TEXT"),
            ("assignment_channel_id",  "TEXT"),
            ("reaction_emoji_4",       "TEXT"),
            ("reaction_emoji_5",       "TEXT"),
            ("reaction_mc_4",          "REAL DEFAULT 4.0"),
            ("reaction_mc_5",          "REAL DEFAULT 5.0"),
            ("raffle_reaction_emoji",  "TEXT"),
        ]
        for col, typedef in cols:
            try:
                await db.execute(f"ALTER TABLE guild_config ADD COLUMN {col} {typedef}")
                print(f"  ✅ guild_config.{col}")
            except Exception:
                print(f"  ⏭  guild_config.{col} (exists)")

        # ── snapshot_awards table (dedup within a snapshot) ───────────
        await db.execute('''
            CREATE TABLE IF NOT EXISTS snapshot_awards (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id TEXT NOT NULL,
                guild_id    TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                amount      REAL NOT NULL,
                mc_type     TEXT NOT NULL,
                awarded_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(snapshot_id, user_id)
            )
        ''')
        print("  ✅ table: snapshot_awards")

        # ── assignments table ─────────────────────────────────────────
        await db.execute('''
            CREATE TABLE IF NOT EXISTS assignments_mgr (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      TEXT NOT NULL,
                name          TEXT NOT NULL,
                body          TEXT NOT NULL,
                thread_id     TEXT,
                cooldown_seconds INTEGER DEFAULT 0,
                is_recurring  INTEGER DEFAULT 0,
                status        TEXT DEFAULT 'active',
                created_by    TEXT,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at     TIMESTAMP
            )
        ''')
        print("  ✅ table: assignments_mgr")

        # ── assignment_cooldowns table (per-user per-thread) ──────────
        await db.execute('''
            CREATE TABLE IF NOT EXISTS assignment_cooldowns (
                thread_id   TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                last_msg_at TIMESTAMP NOT NULL,
                PRIMARY KEY (thread_id, user_id)
            )
        ''')
        print("  ✅ table: assignment_cooldowns")

        # ── assignment_participants (track who posted, for counts) ────
        await db.execute('''
            CREATE TABLE IF NOT EXISTS assignment_participants (
                assignment_id INTEGER NOT NULL,
                user_id       TEXT NOT NULL,
                first_post_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (assignment_id, user_id)
            )
        ''')
        print("  ✅ table: assignment_participants")

        await db.commit()
        print("\n✅ Migration complete. No existing data changed.")


if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        print(f"ERROR: bot.db not found at {DB_PATH}")
        exit(1)
    asyncio.run(migrate())
