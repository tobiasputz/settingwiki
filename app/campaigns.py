from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from .config import Settings
from .storage import connect

CAMPAIGN_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    accent TEXT NOT NULL DEFAULT '#b79661',
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_memberships (
    campaign_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,invite_id),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_campaign_memberships_invite ON campaign_memberships(invite_id,campaign_id);
'''


def _slug(value: str) -> str:
    out = re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')
    return out or f'campaign-{int(time.time())}'


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _default_campaign_id_conn(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM campaigns WHERE is_default=1 ORDER BY id LIMIT 1").fetchone()
    if row:
        return int(row[0])
    row = conn.execute("SELECT id FROM campaigns ORDER BY id LIMIT 1").fetchone()
    if row:
        cid = int(row[0])
        conn.execute("UPDATE campaigns SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END", (cid,))
        return cid
    now = time.time()
    cid = int(conn.execute(
        "INSERT INTO campaigns(name,slug,description,status,accent,is_default,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        ("Main Campaign", "main-campaign", "The original table carried forward from the single-campaign Seeker setup.", "active", "#b79661", 1, now, now),
    ).lastrowid)
    return cid


def _add_campaign_column(conn: sqlite3.Connection, table: str, default_id: int) -> None:
    cols = _columns(conn, table)
    if not cols:
        return
    if 'campaign_id' not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN campaign_id INTEGER")
    conn.execute(f"UPDATE {table} SET campaign_id=? WHERE campaign_id IS NULL", (int(default_id),))


def _rebuild_player_knowledge(conn: sqlite3.Connection, default_id: int) -> None:
    if not _table_exists(conn, 'player_knowledge'):
        return
    cols = _columns(conn, 'player_knowledge')
    # Older versions used (invite_id,target_type,target_key) as the primary key,
    # which cannot represent different knowledge in two campaigns.
    pk_cols = [r[1] for r in sorted(conn.execute("PRAGMA table_info(player_knowledge)").fetchall(), key=lambda x: x[5] or 999) if r[5]]
    if 'campaign_id' in cols and pk_cols == ['campaign_id','invite_id','target_type','target_key']:
        conn.execute("UPDATE player_knowledge SET campaign_id=? WHERE campaign_id IS NULL", (default_id,))
        return
    conn.execute("ALTER TABLE player_knowledge RENAME TO player_knowledge_pre_campaign")
    conn.execute('''CREATE TABLE player_knowledge (
        campaign_id INTEGER NOT NULL,
        invite_id INTEGER NOT NULL,
        target_type TEXT NOT NULL DEFAULT 'page',
        target_key TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'unknown',
        note TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'gm',
        updated_at REAL NOT NULL,
        PRIMARY KEY(campaign_id,invite_id,target_type,target_key),
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
        FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
    )''')
    old_cols = _columns(conn, 'player_knowledge_pre_campaign')
    campaign_expr = "COALESCE(campaign_id,?)" if 'campaign_id' in old_cols else "?"
    conn.execute(f'''INSERT OR REPLACE INTO player_knowledge(campaign_id,invite_id,target_type,target_key,state,note,source,updated_at)
                     SELECT {campaign_expr},invite_id,target_type,target_key,state,note,source,updated_at FROM player_knowledge_pre_campaign''', (default_id,))
    conn.execute("DROP TABLE player_knowledge_pre_campaign")


def _rebuild_lore_reveals(conn: sqlite3.Connection, default_id: int) -> None:
    if not _table_exists(conn, 'lore_reveals'):
        return
    cols = _columns(conn, 'lore_reveals')
    # The old UNIQUE(target_type,target_key) likewise made reveals global.
    has_composite = False
    for idx in conn.execute("PRAGMA index_list(lore_reveals)").fetchall():
        if not int(idx[2]):
            continue
        names = [r[2] for r in conn.execute(f"PRAGMA index_info('{idx[1]}')").fetchall()]
        if names == ['campaign_id','target_type','target_key']:
            has_composite = True
            break
    if 'campaign_id' in cols and has_composite:
        conn.execute("UPDATE lore_reveals SET campaign_id=? WHERE campaign_id IS NULL", (default_id,))
        return
    conn.execute("ALTER TABLE lore_reveals RENAME TO lore_reveals_pre_campaign")
    conn.execute('''CREATE TABLE lore_reveals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        target_type TEXT NOT NULL,
        target_key TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'hidden',
        rumor_text TEXT NOT NULL DEFAULT '',
        audience_json TEXT NOT NULL DEFAULT '[]',
        expires_at REAL,
        revealed_at REAL,
        session_id INTEGER,
        updated_at REAL NOT NULL,
        UNIQUE(campaign_id,target_type,target_key),
        FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )''')
    old_cols = _columns(conn, 'lore_reveals_pre_campaign')
    campaign_expr = "COALESCE(campaign_id,?)" if 'campaign_id' in old_cols else "?"
    conn.execute(f'''INSERT OR REPLACE INTO lore_reveals(id,campaign_id,target_type,target_key,state,rumor_text,audience_json,expires_at,revealed_at,session_id,updated_at)
                     SELECT id,{campaign_expr},target_type,target_key,state,rumor_text,audience_json,expires_at,revealed_at,session_id,updated_at FROM lore_reveals_pre_campaign''', (default_id,))
    conn.execute("DROP TABLE lore_reveals_pre_campaign")


def init_campaign_db(settings: Settings) -> None:
    """Add the multi-campaign layer and migrate all single-campaign state safely.

    Canonical setting data (Codex, maps, historical timeline, relationships and
    current world-state records) stays shared. Party/session state receives a
    campaign_id so two tables can inhabit the same setting without leaking notes,
    spoilers, handouts or characters into one another.
    """
    with connect(settings) as conn:
        conn.executescript(CAMPAIGN_SCHEMA)
        default_id = _default_campaign_id_conn(conn)

        # Existing invitations belonged to the original campaign. Preserve that
        # assumption during upgrade so nobody loses access after deployment.
        if _table_exists(conn, 'player_invites'):
            conn.execute('''INSERT OR IGNORE INTO campaign_memberships(campaign_id,invite_id,created_at)
                            SELECT ?,id,? FROM player_invites''', (default_id, time.time()))

        for table in (
            'campaign_sessions','session_updates','mysteries','handouts','player_characters',
            'campaign_fronts','rumors','campaign_threads','player_journals',
            'player_submissions','campaign_notifications',
        ):
            _add_campaign_column(conn, table, default_id)

        # Where possible, inherit campaign from the stronger parent relation.
        if _table_exists(conn, 'session_updates'):
            conn.execute('''UPDATE session_updates SET campaign_id=COALESCE(
                (SELECT s.campaign_id FROM campaign_sessions s WHERE s.id=session_updates.session_id),campaign_id,?)''',(default_id,))
        if _table_exists(conn, 'handouts'):
            conn.execute('''UPDATE handouts SET campaign_id=COALESCE(
                (SELECT s.campaign_id FROM campaign_sessions s WHERE s.id=handouts.session_id),campaign_id,?)''',(default_id,))
        if _table_exists(conn, 'player_journals'):
            conn.execute('''UPDATE player_journals SET campaign_id=COALESCE(
                (SELECT c.campaign_id FROM player_characters c WHERE c.id=player_journals.character_id),
                (SELECT s.campaign_id FROM campaign_sessions s WHERE s.id=player_journals.session_id),campaign_id,?)''',(default_id,))

        _rebuild_player_knowledge(conn, default_id)
        _rebuild_lore_reveals(conn, default_id)

        # Hot-path selectors used on essentially every player page.
        indexes = {
            'campaign_sessions': 'CREATE INDEX IF NOT EXISTS idx_sessions_campaign_status ON campaign_sessions(campaign_id,status,updated_at DESC,id DESC)',
            'session_updates': 'CREATE INDEX IF NOT EXISTS idx_updates_campaign_created ON session_updates(campaign_id,created_at DESC)',
            'player_characters': 'CREATE INDEX IF NOT EXISTS idx_characters_campaign_owner ON player_characters(campaign_id,invite_id,updated_at DESC)',
            'mysteries': 'CREATE INDEX IF NOT EXISTS idx_mysteries_campaign_status ON mysteries(campaign_id,status,updated_at DESC)',
            'handouts': 'CREATE INDEX IF NOT EXISTS idx_handouts_campaign_created ON handouts(campaign_id,created_at DESC)',
            'campaign_fronts': 'CREATE INDEX IF NOT EXISTS idx_fronts_campaign_status ON campaign_fronts(campaign_id,status,updated_at DESC)',
            'rumors': 'CREATE INDEX IF NOT EXISTS idx_rumors_campaign_status ON rumors(campaign_id,status,updated_at DESC)',
            'campaign_threads': 'CREATE INDEX IF NOT EXISTS idx_threads_campaign_status ON campaign_threads(campaign_id,status,updated_at DESC)',
            'player_journals': 'CREATE INDEX IF NOT EXISTS idx_journals_campaign_owner ON player_journals(campaign_id,invite_id,updated_at DESC)',
            'player_submissions': 'CREATE INDEX IF NOT EXISTS idx_submissions_campaign_owner ON player_submissions(campaign_id,invite_id,created_at DESC)',
            'campaign_notifications': 'CREATE INDEX IF NOT EXISTS idx_notifications_campaign_created ON campaign_notifications(campaign_id,created_at DESC)',
            'player_knowledge': 'CREATE INDEX IF NOT EXISTS idx_knowledge_campaign_invite ON player_knowledge(campaign_id,invite_id,updated_at DESC)',
            'lore_reveals': 'CREATE INDEX IF NOT EXISTS idx_reveals_campaign_updated ON lore_reveals(campaign_id,updated_at DESC)',
        }
        for table, ddl in indexes.items():
            if _table_exists(conn, table):
                conn.execute(ddl)


def default_campaign_id(settings: Settings) -> int:
    with connect(settings) as conn:
        conn.executescript(CAMPAIGN_SCHEMA)
        return _default_campaign_id_conn(conn)


def resolve_campaign_id(settings: Settings, campaign_id: Any = None) -> int:
    try:
        cid = int(campaign_id)
    except (TypeError, ValueError):
        cid = 0
    if cid:
        with connect(settings) as conn:
            if conn.execute("SELECT 1 FROM campaigns WHERE id=?", (cid,)).fetchone():
                return cid
    return default_campaign_id(settings)


def list_campaigns(settings: Settings, *, invite_id: int | None = None, admin: bool = False, include_archived: bool = False) -> list[dict]:
    with connect(settings) as conn:
        status = "" if include_archived else " AND c.status='active'"
        if admin:
            rows = conn.execute(f'''SELECT c.*, (SELECT COUNT(*) FROM campaign_memberships cm WHERE cm.campaign_id=c.id) AS member_count
                                    FROM campaigns c WHERE 1=1 {status} ORDER BY c.is_default DESC,c.name COLLATE NOCASE,c.id''').fetchall()
        elif invite_id is not None:
            rows = conn.execute(f'''SELECT c.*,1 AS member_count FROM campaigns c
                                    JOIN campaign_memberships cm ON cm.campaign_id=c.id
                                    WHERE cm.invite_id=? {status} ORDER BY c.is_default DESC,c.name COLLATE NOCASE,c.id''',(int(invite_id),)).fetchall()
        else:
            rows = conn.execute(f'''SELECT c.*,0 AS member_count FROM campaigns c
                                    WHERE c.is_default=1 {status} ORDER BY c.id LIMIT 1''').fetchall()
        return [dict(r) for r in rows]


def get_campaign(settings: Settings, campaign_id: int) -> dict | None:
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?", (int(campaign_id),)).fetchone()
        return dict(row) if row else None


def campaign_members(settings: Settings, campaign_id: int) -> list[dict]:
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute('''SELECT i.*,CASE WHEN cm.invite_id IS NULL THEN 0 ELSE 1 END AS campaign_member
            FROM player_invites i LEFT JOIN campaign_memberships cm ON cm.invite_id=i.id AND cm.campaign_id=?
            ORDER BY i.label COLLATE NOCASE,i.id''',(int(campaign_id),)).fetchall()]


def invite_has_campaign(settings: Settings, invite_id: int | None, campaign_id: int) -> bool:
    if invite_id is None:
        return False
    with connect(settings) as conn:
        return conn.execute("SELECT 1 FROM campaign_memberships WHERE invite_id=? AND campaign_id=?",(int(invite_id),int(campaign_id))).fetchone() is not None


def set_campaign_members(settings: Settings, campaign_id: int, invite_ids: list[int]) -> None:
    cid = resolve_campaign_id(settings, campaign_id)
    wanted = {int(x) for x in (invite_ids or [])}
    now = time.time()
    with connect(settings) as conn:
        conn.execute("DELETE FROM campaign_memberships WHERE campaign_id=?", (cid,))
        conn.executemany("INSERT OR IGNORE INTO campaign_memberships(campaign_id,invite_id,created_at) VALUES(?,?,?)",[(cid,i,now) for i in wanted])


def ensure_campaign_membership(settings: Settings, campaign_id: int, invite_id: int) -> None:
    with connect(settings) as conn:
        conn.execute("INSERT OR IGNORE INTO campaign_memberships(campaign_id,invite_id,created_at) VALUES(?,?,?)",(int(campaign_id),int(invite_id),time.time()))


def save_campaign(settings: Settings, payload: dict) -> dict:
    now = time.time(); cid = payload.get('id')
    name = str(payload.get('name') or 'Untitled Campaign').strip()[:160]
    if not name:
        raise ValueError('Campaign name cannot be empty.')
    status = str(payload.get('status') or 'active')
    if status not in {'active','archived'}:
        status = 'active'
    accent = str(payload.get('accent') or '#b79661')[:20]
    description = str(payload.get('description') or '')[:4000]
    with connect(settings) as conn:
        if cid:
            row = conn.execute("SELECT * FROM campaigns WHERE id=?",(int(cid),)).fetchone()
            if not row:
                raise ValueError('Campaign not found.')
            if status=='archived' and int(row['is_default'] or 0):
                raise ValueError('The default campaign cannot be archived. Make another campaign the default first.')
            slug = str(payload.get('slug') or row['slug'] or _slug(name))
            conn.execute("UPDATE campaigns SET name=?,slug=?,description=?,status=?,accent=?,updated_at=? WHERE id=?",(name,slug,description,status,accent,now,int(cid)))
            out = int(cid)
        else:
            base = _slug(payload.get('slug') or name); slug = base; n = 2
            while conn.execute("SELECT 1 FROM campaigns WHERE slug=?",(slug,)).fetchone():
                slug=f'{base}-{n}'; n+=1
            out = int(conn.execute("INSERT INTO campaigns(name,slug,description,status,accent,is_default,created_at,updated_at) VALUES(?,?,?,?,?,0,?,?)",(name,slug,description,status,accent,now,now)).lastrowid)
    if 'member_ids' in payload:
        set_campaign_members(settings,out,[int(x) for x in (payload.get('member_ids') or [])])
    return get_campaign(settings,out) or {}


def archive_campaign(settings: Settings, campaign_id: int) -> dict:
    cid = int(campaign_id)
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM campaigns WHERE id=?",(cid,)).fetchone()
        if not row:
            raise ValueError('Campaign not found.')
        if int(row['is_default'] or 0):
            raise ValueError('The default campaign cannot be archived. Make another campaign the default first.')
        conn.execute("UPDATE campaigns SET status='archived',updated_at=? WHERE id=?",(time.time(),cid))
    return get_campaign(settings,cid) or {}


def make_default_campaign(settings: Settings, campaign_id: int) -> dict:
    cid = int(campaign_id)
    with connect(settings) as conn:
        row=conn.execute("SELECT status FROM campaigns WHERE id=?",(cid,)).fetchone()
        if not row:
            raise ValueError('Campaign not found.')
        if str(row['status'])!='active':
            raise ValueError('An archived campaign cannot be the default.')
        conn.execute("UPDATE campaigns SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END",(cid,))
    return get_campaign(settings,cid) or {}


def delete_campaign(settings: Settings, campaign_id: int) -> None:
    """Permanently delete one non-default campaign and all campaign-scoped state.

    Player identities and player-global availability are intentionally preserved;
    canonical setting data is shared and is never removed with a table.
    """
    cid=int(campaign_id)
    with connect(settings) as conn:
        row=conn.execute("SELECT * FROM campaigns WHERE id=?",(cid,)).fetchone()
        if not row:
            raise ValueError('Campaign not found.')
        if int(row['is_default'] or 0):
            raise ValueError('The default campaign cannot be deleted. Make another campaign the default first.')
        # Delete every table that explicitly carries campaign_id. This keeps the
        # cleanup forward-compatible with V5 features while leaving shared canon
        # and player-global scheduling untouched.
        tables=[r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        protected={'campaigns'}
        for table in tables:
            if table in protected: continue
            try:
                cols={r['name'] for r in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}
            except Exception:
                continue
            if 'campaign_id' in cols:
                conn.execute(f'DELETE FROM "{table}" WHERE campaign_id=?',(cid,))
        conn.execute("DELETE FROM campaign_memberships WHERE campaign_id=?",(cid,))
        conn.execute("DELETE FROM campaigns WHERE id=?",(cid,))
