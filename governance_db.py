"""Durable approval queue. Decisions and configuration changes commit together."""
import json
import uuid
from datetime import timedelta
from access_policy import (ACCESS_KEYS, is_operator, is_primary, same_guild,
                           normalize_guild_changes, normalize_support_changes)
from runtime_utils import parse_time, utc_iso


class GovernanceDB:
    async def init_governance(self):
        db = await self._get_conn()
        async with self._lock:
            for column, typedef in [('moderator_role_id', 'TEXT'), ('super_admin_role_id', 'TEXT'),
                                    ('super_admin_user_ids', "TEXT NOT NULL DEFAULT '[]'")]:
                fields = {r[1] for r in await (await db.execute('PRAGMA table_info(guild_config)')).fetchall()}
                if column not in fields:
                    await db.execute(f'ALTER TABLE guild_config ADD COLUMN {column} {typedef}')
            await db.execute('''CREATE TABLE IF NOT EXISTS config_requests (
                id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                scope TEXT NOT NULL, source_id TEXT NOT NULL, old_json TEXT NOT NULL,
                changes_json TEXT NOT NULL, reason TEXT NOT NULL, state TEXT NOT NULL,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                decided_by TEXT, decided_at TEXT, decision_note TEXT,
                UNIQUE(guild_id, source_id))''')
            await db.execute('''CREATE TABLE IF NOT EXISTS config_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL,
                request_id TEXT NOT NULL, actor_id TEXT NOT NULL, event TEXT NOT NULL,
                detail TEXT NOT NULL, created_at TEXT NOT NULL)''')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_config_pending ON config_requests(guild_id,state,created_at)')
            await db.commit()

    async def _governance_config(self, db, guild_id):
        row = await (await db.execute('SELECT * FROM guild_config WHERE guild_id=?', (str(guild_id),))).fetchone()
        return dict(row) if row else {}

    async def _governance_values(self, db, guild_id, scope):
        if scope == 'guild':
            return await self._governance_config(db, guild_id)
        if scope != 'support':
            raise ValueError('Unknown configuration scope.')
        row = await (await db.execute('SELECT * FROM support_config WHERE guild_id=?', (str(guild_id),))).fetchone()
        return dict(row) if row else {'enabled': 0, 'weekly_cap': 10, 'sample_size': 3}

    async def _governance_apply(self, db, guild_id, scope, changes, now):
        if scope == 'guild':
            fields = ','.join(f'{key}=?' for key in changes)
            await db.execute('UPDATE guild_config SET ' + fields + ' WHERE guild_id=?', (*changes.values(), str(guild_id)))
            if changes.get('is_configured') == 0:
                await db.execute('UPDATE guild_config SET panel_message_id=NULL,leaderboard_message_id=NULL WHERE guild_id=?', (str(guild_id),))
        else:
            await self._configure_support_locked(db, guild_id, changes, now=now)

    async def _governance_audit(self, db, guild_id, request_id, actor_id, event, detail, now):
        await db.execute('INSERT INTO config_audit(guild_id,request_id,actor_id,event,detail,created_at) VALUES(?,?,?,?,?,?)',
                         (str(guild_id), request_id, str(actor_id), event, detail[:2000], utc_iso(now)))

    async def _expire_config_requests(self, db, guild_id, now):
        rows = await (await db.execute("SELECT id FROM config_requests WHERE guild_id=? AND state='pending' AND expires_at<=?",
                                      (str(guild_id), utc_iso(now)))).fetchall()
        for row in rows:
            await db.execute("UPDATE config_requests SET state='expired',decided_at=?,decision_note='Expired after seven days.' WHERE id=?",
                             (utc_iso(now), row['id']))
            await self._governance_audit(db, guild_id, row['id'], 'system', 'expired', 'Seven-day expiry', now)

    async def submit_config_change(self, guild_id, member, scope, changes, *, source_id, reason='', access=False, expected=None, now=None):
        now = parse_time(now or utc_iso())
        if not source_id or len(str(source_id)) > 100 or len(reason) > 1000:
            raise ValueError('Invalid request source or reason.')
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                config = await self._governance_config(db, guild_id)
                if not config or not same_guild(member, guild_id) or not is_operator(member, config):
                    raise PermissionError('Moderator access required.')
                primary = is_primary(member, config)
                if access and (not primary or scope != 'guild' or not set(changes) <= ACCESS_KEYS):
                    raise PermissionError('Only a primary administrator can manage access.')
                if access and 'admin_user_id' in changes and config.get('admin_user_id') and str(changes['admin_user_id']) != str(config['admin_user_id']):
                    raise PermissionError('The original primary-admin ID is retained. Add or remove named primary admins instead.')
                current = await self._governance_values(db, guild_id, scope)
                changes = (normalize_guild_changes(current, changes, access=access) if scope == 'guild'
                           else normalize_support_changes(changes))
                await self._expire_config_requests(db, guild_id, now)
                existing = await (await db.execute('SELECT * FROM config_requests WHERE guild_id=? AND source_id=?',
                                                  (str(guild_id), str(source_id)))).fetchone()
                if existing:
                    if existing['actor_id'] != str(member.id) or existing['scope'] != scope or json.loads(existing['changes_json']) != changes:
                        raise ValueError('This operation ID already belongs to a different request.')
                    await db.commit()
                    return dict(existing)
                if expected is not None and any(current.get(k) != v for k, v in expected.items()):
                    raise ValueError('These settings changed while the form was open. Refresh and try again.')
                if not changes or not any(current.get(k) != v for k, v in changes.items()):
                    await db.commit()
                    return {'id': None, 'state': 'unchanged'}
                if not primary:
                    counts = await (await db.execute("SELECT COUNT(*),SUM(actor_id=?) FROM config_requests WHERE guild_id=? AND state='pending'",
                                                    (str(member.id), str(guild_id)))).fetchone()
                    if counts[0] >= 200 or (counts[1] or 0) >= 10:
                        raise ValueError('The pending request limit was reached. Ask a primary admin to review existing requests.')
                rid = uuid.uuid4().hex
                state = 'applied' if primary else 'pending'
                old = {k: current.get(k) for k in changes}
                await db.execute('''INSERT INTO config_requests
                    (id,guild_id,actor_id,scope,source_id,old_json,changes_json,reason,state,created_at,expires_at,decided_by,decided_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (rid, str(guild_id), str(member.id), scope, str(source_id),
                    json.dumps(old, sort_keys=True), json.dumps(changes, sort_keys=True), reason, state, utc_iso(now),
                    utc_iso(now + timedelta(days=7)), str(member.id) if primary else None, utc_iso(now) if primary else None))
                if primary:
                    await self._governance_apply(db, guild_id, scope, changes, now)
                await self._governance_audit(db, guild_id, rid, member.id, state, reason, now)
                row = await (await db.execute('SELECT * FROM config_requests WHERE id=?', (rid,))).fetchone()
                await db.commit()
                return dict(row)
            except BaseException:
                await db.rollback()
                raise

    async def list_config_requests(self, guild_id, member, *, after='', limit=20, state='pending', now=None):
        now = parse_time(now or utc_iso())
        if state not in {'pending', 'applied', 'approved', 'rejected', 'stale', 'expired', 'all'}:
            raise ValueError('Invalid request state.')
        db = await self._get_conn()
        async with self._lock:
            config = await self._governance_config(db, guild_id)
            if not same_guild(member, guild_id) or not is_operator(member, config):
                raise PermissionError('Moderator access required.')
            await self._expire_config_requests(db, guild_id, now)
            query = 'SELECT * FROM config_requests WHERE guild_id=?'
            args = [str(guild_id)]
            if after:
                cursor = await (await db.execute('SELECT created_at,actor_id FROM config_requests WHERE guild_id=? AND id=?',
                                                (str(guild_id), after))).fetchone()
                if cursor is None or (not is_primary(member, config) and cursor['actor_id'] != str(member.id)):
                    await db.rollback()
                    raise ValueError('Invalid request-page cursor. Refresh the list.')
                query += ' AND (created_at,id)>(?,?)'; args.extend([cursor['created_at'], after])
            if state != 'all':
                query += ' AND state=?'; args.append(state)
            if not is_primary(member, config):
                query += ' AND actor_id=?'; args.append(str(member.id))
            rows = await (await db.execute(query + ' ORDER BY created_at,id LIMIT ?', (*args, max(1, min(25, int(limit)))))).fetchall()
            await db.commit()
            return [dict(row) for row in rows]

    async def get_config_request(self, guild_id, member, request_id):
        db = await self._get_conn()
        async with self._lock:
            config = await self._governance_config(db, guild_id)
            if not same_guild(member, guild_id) or not is_operator(member, config):
                raise PermissionError('Moderator access required.')
            row = await (await db.execute('SELECT * FROM config_requests WHERE guild_id=? AND id=?',
                                         (str(guild_id), request_id))).fetchone()
            if row and (is_primary(member, config) or row['actor_id'] == str(member.id)):
                return dict(row)
            return None

    async def decide_config_request(self, guild_id, member, request_id, *, approve, note='', now=None):
        now = parse_time(now or utc_iso())
        db = await self._get_conn()
        async with self._lock:
            try:
                await db.execute('BEGIN IMMEDIATE')
                config = await self._governance_config(db, guild_id)
                if not same_guild(member, guild_id) or not is_primary(member, config):
                    raise PermissionError('Primary administrator access required.')
                await self._expire_config_requests(db, guild_id, now)
                row = await (await db.execute('SELECT * FROM config_requests WHERE guild_id=? AND id=?',
                                             (str(guild_id), request_id))).fetchone()
                if not row:
                    raise ValueError('Request not found in this server.')
                if row['state'] != 'pending':
                    await db.commit()
                    return dict(row)
                changes, old = json.loads(row['changes_json']), json.loads(row['old_json'])
                current = await self._governance_values(db, guild_id, row['scope'])
                state = 'rejected'
                if approve:
                    if any(current.get(k) != v for k, v in old.items()):
                        state = 'stale'
                        note = 'Current values changed. Submit a new request.'
                    else:
                        try:
                            changes = (normalize_guild_changes(current, changes) if row['scope'] == 'guild'
                                       else normalize_support_changes(changes))
                        except ValueError as exc:
                            state, note = 'stale', str(exc)
                        else:
                            await self._governance_apply(db, guild_id, row['scope'], changes, now)
                            state = 'approved'
                await db.execute('UPDATE config_requests SET state=?,decided_by=?,decided_at=?,decision_note=? WHERE id=?',
                                 (state, str(member.id), utc_iso(now), note[:1000], request_id))
                await self._governance_audit(db, guild_id, request_id, member.id, state, note, now)
                result = await (await db.execute('SELECT * FROM config_requests WHERE id=?', (request_id,))).fetchone()
                await db.commit()
                return dict(result)
            except BaseException:
                await db.rollback()
                raise
