from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
import time
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .storage import connect, safe_project_path

FEATURE_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS campaign_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_number INTEGER,
    title TEXT NOT NULL,
    session_date TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned',
    summary TEXT NOT NULL DEFAULT '',
    gm_notes TEXT NOT NULL DEFAULT '',
    current_location_slug TEXT,
    spotlight_map_slug TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS session_lore (
    session_id INTEGER NOT NULL,
    page_slug TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'reference',
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(session_id,page_slug,role),
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_session_lore_page ON session_lore(page_slug, session_id);
CREATE TABLE IF NOT EXISTS session_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT 'lore',
    target_key TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'players',
    audience_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    date_label TEXT NOT NULL DEFAULT '',
    sort_key REAL NOT NULL DEFAULT 0,
    body TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'event',
    page_slug TEXT,
    image_ref TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'players',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS lore_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_slug TEXT NOT NULL,
    target_slug TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'related to',
    label TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'players',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(source_slug,target_slug,relation)
);
CREATE TABLE IF NOT EXISTS lore_reveals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'hidden',
    rumor_text TEXT NOT NULL DEFAULT '',
    audience_json TEXT NOT NULL DEFAULT '[]',
    expires_at REAL,
    revealed_at REAL,
    session_id INTEGER,
    updated_at REAL NOT NULL,
    UNIQUE(target_type,target_key)
);
CREATE TABLE IF NOT EXISTS lore_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_slug TEXT NOT NULL,
    variant_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    common_text TEXT NOT NULL DEFAULT '',
    truth_text TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'common',
    visibility TEXT NOT NULL DEFAULT 'players',
    updated_at REAL NOT NULL,
    UNIQUE(page_slug,variant_key)
);
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_slug TEXT NOT NULL,
    anchor TEXT NOT NULL DEFAULT '',
    quote TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private',
    invite_id INTEGER,
    author_label TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mysteries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    visibility TEXT NOT NULL DEFAULT 'players',
    image_ref TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mystery_pins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mystery_id INTEGER NOT NULL,
    page_slug TEXT,
    label TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    x REAL NOT NULL DEFAULT 0.5,
    y REAL NOT NULL DEFAULT 0.5,
    visibility TEXT NOT NULL DEFAULT 'players',
    created_at REAL NOT NULL,
    FOREIGN KEY(mystery_id) REFERENCES mysteries(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS mystery_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mystery_id INTEGER NOT NULL,
    source_pin INTEGER NOT NULL,
    target_pin INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'players',
    FOREIGN KEY(mystery_id) REFERENCES mysteries(id) ON DELETE CASCADE,
    FOREIGN KEY(source_pin) REFERENCES mystery_pins(id) ON DELETE CASCADE,
    FOREIGN KEY(target_pin) REFERENCES mystery_pins(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS handouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'parchment',
    image_ref TEXT NOT NULL DEFAULT '',
    page_slug TEXT,
    session_id INTEGER,
    visibility TEXT NOT NULL DEFAULT 'players',
    expires_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS page_aliases (
    alias TEXT PRIMARY KEY COLLATE NOCASE,
    page_slug TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_styles (
    page_slug TEXT PRIMARY KEY,
    crest_ref TEXT NOT NULL DEFAULT '',
    accent TEXT NOT NULL DEFAULT '',
    motif TEXT NOT NULL DEFAULT '',
    ambient_audio_ref TEXT NOT NULL DEFAULT '',
    dossier_type TEXT NOT NULL DEFAULT 'auto',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS map_layers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    map_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    image_path TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'overlay',
    opacity REAL NOT NULL DEFAULT 0.7,
    visible_to_players INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS map_fog_regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    map_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT 'Unknown region',
    points_json TEXT NOT NULL DEFAULT '[]',
    revealed INTEGER NOT NULL DEFAULT 0,
    style TEXT NOT NULL DEFAULT 'parchment',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS player_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invite_id INTEGER,
    event_type TEXT NOT NULL,
    target_key TEXT NOT NULL DEFAULT '',
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS player_bookmarks (
    invite_id INTEGER NOT NULL,
    page_slug TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(invite_id,page_slug)
);
CREATE TABLE IF NOT EXISTS campaign_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS timeline_eras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_label TEXT NOT NULL DEFAULT '',
    end_label TEXT NOT NULL DEFAULT '',
    start_sort REAL NOT NULL DEFAULT 0,
    end_sort REAL NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    accent TEXT NOT NULL DEFAULT '#b79661',
    sort_order INTEGER NOT NULL DEFAULT 0,
    visibility TEXT NOT NULL DEFAULT 'players',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS player_characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invite_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    pronouns TEXT NOT NULL DEFAULT '',
    ancestry TEXT NOT NULL DEFAULT '',
    class_name TEXT NOT NULL DEFAULT '',
    level INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    summary TEXT NOT NULL DEFAULT '',
    biography TEXT NOT NULL DEFAULT '',
    goals TEXT NOT NULL DEFAULT '',
    player_notes TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'party',
    portrait_path TEXT NOT NULL DEFAULT '',
    theme_color TEXT NOT NULL DEFAULT '#b79661',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_player_characters_invite ON player_characters(invite_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS character_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'inspiration',
    caption TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE CASCADE
);
"""


def init_feature_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(FEATURE_SCHEMA)
        # Forward-compatible migrations for persistent Railway volumes. CREATE
        # TABLE IF NOT EXISTS does not add columns to an existing v2 preview DB.
        update_cols = {r[1] for r in conn.execute("PRAGMA table_info(session_updates)").fetchall()}
        if "audience_json" not in update_cols:
            conn.execute("ALTER TABLE session_updates ADD COLUMN audience_json TEXT NOT NULL DEFAULT '[]'")
        timeline_cols = {r[1] for r in conn.execute("PRAGMA table_info(timeline_events)").fetchall()}
        timeline_add = {
            "era_id": "INTEGER",
            "end_date_label": "TEXT NOT NULL DEFAULT ''",
            "end_sort_key": "REAL",
            "significance": "INTEGER NOT NULL DEFAULT 2",
            "certainty": "TEXT NOT NULL DEFAULT 'recorded'",
        }
        for col, ddl in timeline_add.items():
            if col not in timeline_cols:
                conn.execute(f"ALTER TABLE timeline_events ADD COLUMN {col} {ddl}")
        relationship_cols = {r[1] for r in conn.execute("PRAGMA table_info(lore_relationships)").fetchall()}
        if "updated_at" not in relationship_cols:
            conn.execute("ALTER TABLE lore_relationships ADD COLUMN updated_at REAL NOT NULL DEFAULT 0")
        alias_cols = {r[1] for r in conn.execute("PRAGMA table_info(page_aliases)").fetchall()}
        if "updated_at" not in alias_cols:
            conn.execute("ALTER TABLE page_aliases ADD COLUMN updated_at REAL NOT NULL DEFAULT 0")
        # Hot-path indexes for live table polling and Codex article lookups.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_campaign_sessions_live ON campaign_sessions(status,updated_at DESC,id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_updates_visibility_created ON session_updates(visibility,created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_updates_target_session ON session_updates(target_key,session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lore_reveals_updated ON lore_reveals(updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handouts_visibility_updated ON handouts(visibility,updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lore_relationships_source ON lore_relationships(source_slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lore_relationships_target ON lore_relationships(target_slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lore_variants_page ON lore_variants(page_slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_character_images_character ON character_images(character_id,sort_order,id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mystery_pins_board ON mystery_pins(mystery_id,id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mystery_edges_board ON mystery_edges(mystery_id,id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_styles_updated ON entity_styles(updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lore_relationships_updated ON lore_relationships(updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_page_aliases_updated ON page_aliases(updated_at DESC)")

    # v3 extends the feature database with living-campaign state. Keep this
    # initialization chained here so older integrations/tests that have always
    # called init_feature_db() automatically receive the new schema too.
    from .living import init_living_db
    init_living_db(settings)



def _rows(settings: Settings, sql: str, params: tuple = ()) -> list[dict]:
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _row(settings: Settings, sql: str, params: tuple = ()) -> dict | None:
    with connect(settings) as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def _slug(value: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return out or f"item-{int(time.time())}"


def _visible(value: str, admin: bool) -> bool:
    return admin or value not in {"gm", "hidden"}


# --- Sessions ---------------------------------------------------------------
def _audience_allows(row: dict, invite_id: int | None) -> bool:
    try:
        audience = json.loads(row.get("audience_json") or "[]")
    except Exception:
        audience = []
    if not audience:
        return True
    try:
        allowed = {int(x) for x in audience}
    except Exception:
        return False
    return invite_id is not None and int(invite_id) in allowed


def list_sessions(settings: Settings, *, public: bool = False, invite_id: int | None = None) -> list[dict]:
    """Load session history in three bulk queries rather than 2N+1 queries."""
    with connect(settings) as conn:
        session_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM campaign_sessions ORDER BY COALESCE(session_number,999999), session_date, id"
        ).fetchall()]
        if public:
            session_rows = [r for r in session_rows if r["status"] in {"live", "ended"}]
        if not session_rows:
            return []
        ids = [int(r["id"]) for r in session_rows]
        placeholders = ",".join("?" for _ in ids)
        lore_rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM session_lore WHERE session_id IN ({placeholders}) ORDER BY session_id,sort_order,page_slug", ids
        ).fetchall()]
        update_rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM session_updates WHERE session_id IN ({placeholders}) AND visibility!='gm' ORDER BY session_id,created_at DESC", ids
        ).fetchall()]
    lore_by: dict[int,list[dict]] = {sid: [] for sid in ids}
    updates_by: dict[int,list[dict]] = {sid: [] for sid in ids}
    for row in lore_rows:
        lore_by.setdefault(int(row["session_id"]), []).append(row)
    for row in update_rows:
        if not public or _audience_allows(row, invite_id):
            updates_by.setdefault(int(row["session_id"]), []).append(row)
    for row in session_rows:
        sid = int(row["id"]); row["lore"] = lore_by.get(sid, []); row["updates"] = updates_by.get(sid, [])
    return session_rows



def session_appearances_for_page(settings: Settings, page_slug: str, *, public: bool = False) -> list[dict]:
    """Return only sessions that reference one Codex page.

    Article rendering used to load the complete session history, every linked lore
    row and every player update just to answer this tiny question. This indexed
    join keeps Codex navigation essentially constant as the campaign grows.
    """
    sql = """
        SELECT s.*
        FROM campaign_sessions AS s
        JOIN session_lore AS sl ON sl.session_id=s.id
        WHERE sl.page_slug=?
    """
    params: list[Any] = [str(page_slug)]
    if public:
        sql += " AND s.status IN ('live','ended')"
    sql += " GROUP BY s.id ORDER BY COALESCE(s.session_number,999999),s.session_date,s.id"
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

def get_live_session(settings: Settings, *, invite_id: int | None = None, admin: bool = False) -> dict | None:
    """Load the live-session payload using one SQLite connection."""
    with connect(settings) as conn:
        found = conn.execute("SELECT * FROM campaign_sessions WHERE status='live' ORDER BY updated_at DESC,id DESC LIMIT 1").fetchone()
        if not found:
            return None
        row = dict(found); sid = int(row["id"])
        row["lore"] = [dict(r) for r in conn.execute(
            "SELECT * FROM session_lore WHERE session_id=? ORDER BY sort_order,page_slug", (sid,)
        ).fetchall()]
        updates = [dict(r) for r in conn.execute(
            "SELECT * FROM session_updates WHERE session_id=? AND visibility!='gm' ORDER BY created_at DESC", (sid,)
        ).fetchall()]
        handouts = [dict(r) for r in conn.execute(
            "SELECT * FROM handouts WHERE session_id=? AND visibility!='gm' ORDER BY created_at DESC", (sid,)
        ).fetchall()]
    row["updates"] = updates if admin else [u for u in updates if _audience_allows(u, invite_id)]
    if not admin:
        now=time.time(); handouts=[h for h in handouts if not h.get("expires_at") or float(h["expires_at"])>now]
    row["handouts"] = handouts
    return row


def save_session(settings: Settings, payload: dict) -> dict:
    now = time.time(); sid = payload.get("id")
    title = str(payload.get("title") or "Untitled session").strip()[:200]
    status = str(payload.get("status") or "planned")
    if status not in {"planned", "live", "ended"}: status = "planned"
    values = (
        payload.get("session_number"), title, str(payload.get("session_date") or ""), status,
        str(payload.get("summary") or ""), str(payload.get("gm_notes") or ""),
        payload.get("current_location_slug") or None, payload.get("spotlight_map_slug") or None, now,
    )
    with connect(settings) as conn:
        if status == "live": conn.execute("UPDATE campaign_sessions SET status='ended',updated_at=? WHERE status='live' AND id!=?", (now, int(sid or 0)))
        if sid:
            conn.execute("UPDATE campaign_sessions SET session_number=?,title=?,session_date=?,status=?,summary=?,gm_notes=?,current_location_slug=?,spotlight_map_slug=?,updated_at=? WHERE id=?", values + (int(sid),))
            rid = int(sid)
        else:
            cur = conn.execute("INSERT INTO campaign_sessions(session_number,title,session_date,status,summary,gm_notes,current_location_slug,spotlight_map_slug,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", values[:-1] + (now, now))
            rid = cur.lastrowid
    return _row(settings, "SELECT * FROM campaign_sessions WHERE id=?", (rid,)) or {}


def delete_session(settings: Settings, sid: int) -> None:
    with connect(settings) as conn: conn.execute("DELETE FROM campaign_sessions WHERE id=?", (int(sid),))


def set_session_lore(settings: Settings, sid: int, page_slug: str, role: str = "reference", enabled: bool = True) -> None:
    with connect(settings) as conn:
        if enabled:
            conn.execute("INSERT OR IGNORE INTO session_lore(session_id,page_slug,role,sort_order) VALUES(?,?,?,0)", (int(sid), page_slug, role))
        else:
            conn.execute("DELETE FROM session_lore WHERE session_id=? AND page_slug=? AND role=?", (int(sid), page_slug, role))


def add_session_update(settings: Settings, payload: dict) -> dict:
    now=time.time(); audience=payload.get("audience") or []
    with connect(settings) as conn:
        cur=conn.execute("INSERT INTO session_updates(session_id,title,body,target_type,target_key,visibility,audience_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (payload.get("session_id"), str(payload.get("title") or "Update"), str(payload.get("body") or ""), str(payload.get("target_type") or "lore"), str(payload.get("target_key") or ""), str(payload.get("visibility") or "players"), json.dumps(audience), now))
        rid=cur.lastrowid
    return _row(settings,"SELECT * FROM session_updates WHERE id=?",(rid,)) or {}


# --- Historical timeline / world chronology ---------------------------------
HISTORICAL_KINDS = {"event","founding","war","reign","catastrophe","treaty","discovery","migration","birth","death","journey","age","revolution"}


def list_timeline_eras(settings: Settings, *, admin: bool = False) -> list[dict]:
    rows=_rows(settings,"SELECT * FROM timeline_eras ORDER BY sort_order,start_sort,id")
    return [r for r in rows if _visible(r["visibility"],admin)]


def save_timeline_era(settings: Settings, p: dict) -> dict:
    now=time.time(); rid=p.get("id")
    vals=(str(p.get("name") or "Unnamed era").strip(),str(p.get("start_label") or ""),str(p.get("end_label") or ""),float(p.get("start_sort") or 0),float(p.get("end_sort") or 0),str(p.get("summary") or ""),str(p.get("accent") or "#b79661"),int(p.get("sort_order") or 0),str(p.get("visibility") or "players"),now)
    with connect(settings) as conn:
        if rid:
            conn.execute("UPDATE timeline_eras SET name=?,start_label=?,end_label=?,start_sort=?,end_sort=?,summary=?,accent=?,sort_order=?,visibility=?,updated_at=? WHERE id=?",vals+(int(rid),)); out=int(rid)
        else:
            out=conn.execute("INSERT INTO timeline_eras(name,start_label,end_label,start_sort,end_sort,summary,accent,sort_order,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",vals[:-1]+(now,now)).lastrowid
    return _row(settings,"SELECT * FROM timeline_eras WHERE id=?",(out,)) or {}


def delete_timeline_era(settings: Settings, rid: int) -> None:
    with connect(settings) as conn:
        conn.execute("UPDATE timeline_events SET era_id=NULL WHERE era_id=?",(int(rid),))
        conn.execute("DELETE FROM timeline_eras WHERE id=?",(int(rid),))


def list_timeline(settings: Settings, *, admin: bool = False, historical_only: bool = False) -> list[dict]:
    rows=_rows(settings,"SELECT e.*, r.name AS era_name, r.accent AS era_accent FROM timeline_events e LEFT JOIN timeline_eras r ON r.id=e.era_id ORDER BY COALESCE(r.sort_order,999999), e.sort_key,e.date_label,e.id")
    rows=[r for r in rows if _visible(r["visibility"],admin)]
    if historical_only:
        rows=[r for r in rows if r.get("kind") in HISTORICAL_KINDS]
    return rows


def save_timeline_event(settings: Settings,p:dict)->dict:
    now=time.time(); rid=p.get("id")
    end_sort=p.get("end_sort_key")
    vals=(str(p.get("title") or "Event"),str(p.get("date_label") or ""),float(p.get("sort_key") or 0),str(p.get("end_date_label") or ""),float(end_sort) if end_sort not in (None,"") else None,str(p.get("body") or ""),str(p.get("kind") or "event"),int(p.get("era_id")) if p.get("era_id") not in (None,"") else None,p.get("page_slug") or None,str(p.get("image_ref") or ""),max(1,min(5,int(p.get("significance") or 2))),str(p.get("certainty") or "recorded"),str(p.get("visibility") or "players"),now)
    with connect(settings) as conn:
        if rid:
            conn.execute("UPDATE timeline_events SET title=?,date_label=?,sort_key=?,end_date_label=?,end_sort_key=?,body=?,kind=?,era_id=?,page_slug=?,image_ref=?,significance=?,certainty=?,visibility=?,updated_at=? WHERE id=?",vals+(int(rid),)); out=int(rid)
        else:
            out=conn.execute("INSERT INTO timeline_events(title,date_label,sort_key,end_date_label,end_sort_key,body,kind,era_id,page_slug,image_ref,significance,certainty,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",vals[:-1]+(now,now)).lastrowid
    return _row(settings,"SELECT * FROM timeline_events WHERE id=?",(out,)) or {}


# --- Relationships, aliases, entity styles ---------------------------------
def list_relationships(settings: Settings, *, admin: bool=False) -> list[dict]:
    rows=_rows(settings,"SELECT * FROM lore_relationships ORDER BY source_slug,relation,target_slug")
    return [r for r in rows if _visible(r["visibility"],admin)]


def save_relationship(settings: Settings,p:dict)->dict:
    now=time.time(); rid=p.get("id"); vals=(str(p.get("source_slug") or ""),str(p.get("target_slug") or ""),str(p.get("relation") or "related to"),str(p.get("label") or ""),str(p.get("visibility") or "players"))
    if not vals[0] or not vals[1] or vals[0]==vals[1]: raise ValueError("Choose two different Codex entries.")
    with connect(settings) as conn:
        if rid: conn.execute("UPDATE lore_relationships SET source_slug=?,target_slug=?,relation=?,label=?,visibility=?,updated_at=? WHERE id=?",vals+(now,int(rid))); out=int(rid)
        else: out=conn.execute("INSERT INTO lore_relationships(source_slug,target_slug,relation,label,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",vals+(now,now)).lastrowid
    return _row(settings,"SELECT * FROM lore_relationships WHERE id=?",(out,)) or {}


def page_relationships(settings: Settings, slug: str, *, admin: bool=False) -> list[dict]:
    rels=_rows(settings,"SELECT * FROM lore_relationships WHERE source_slug=? OR target_slug=? ORDER BY relation",(slug,slug))
    return [r for r in rels if _visible(r["visibility"],admin)]


def aliases(settings: Settings) -> dict[str,str]:
    return {r["alias"].casefold():r["page_slug"] for r in _rows(settings,"SELECT * FROM page_aliases")}


def save_alias(settings: Settings, alias: str, slug: str) -> None:
    alias=str(alias or "").strip()
    if not alias: raise ValueError("Alias cannot be empty")
    now=time.time()
    with connect(settings) as conn: conn.execute("INSERT INTO page_aliases(alias,page_slug,updated_at) VALUES(?,?,?) ON CONFLICT(alias) DO UPDATE SET page_slug=excluded.page_slug,updated_at=excluded.updated_at",(alias,slug,now))


def entity_style(settings: Settings, slug: str) -> dict:
    return _row(settings,"SELECT * FROM entity_styles WHERE page_slug=?",(slug,)) or {"page_slug":slug,"crest_ref":"","accent":"","motif":"","ambient_audio_ref":"","dossier_type":"auto"}


def save_entity_style(settings: Settings, slug: str, p: dict) -> dict:
    now=time.time(); vals=(slug,str(p.get("crest_ref") or ""),str(p.get("accent") or ""),str(p.get("motif") or ""),str(p.get("ambient_audio_ref") or ""),str(p.get("dossier_type") or "auto"),now)
    with connect(settings) as conn: conn.execute("INSERT INTO entity_styles(page_slug,crest_ref,accent,motif,ambient_audio_ref,dossier_type,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(page_slug) DO UPDATE SET crest_ref=excluded.crest_ref,accent=excluded.accent,motif=excluded.motif,ambient_audio_ref=excluded.ambient_audio_ref,dossier_type=excluded.dossier_type,updated_at=excluded.updated_at",vals)
    return entity_style(settings,slug)


# --- Reveals / unreliable lore ---------------------------------------------
def reveal_state(settings: Settings, target_type: str, target_key: str, invite_id: int|None=None) -> dict:
    row=_row(settings,"SELECT * FROM lore_reveals WHERE target_type=? AND target_key=?",(target_type,target_key))
    if not row: return {"target_type":target_type,"target_key":target_key,"state":"hidden","rumor_text":"","audience_json":"[]","expires_at":None,"configured":False}
    row["configured"] = True
    if row.get("expires_at") and float(row["expires_at"])<=time.time(): row["state"]="hidden"
    try: audience=json.loads(row.get("audience_json") or "[]")
    except Exception: audience=[]
    if audience and invite_id not in audience: row["state"]="hidden"
    row["audience"]=audience
    return row


def list_reveal_states(settings: Settings) -> list[dict]:
    rows = _rows(settings, "SELECT * FROM lore_reveals ORDER BY updated_at DESC,id DESC")
    for row in rows:
        try: row["audience"] = json.loads(row.get("audience_json") or "[]")
        except Exception: row["audience"] = []
    return rows


def set_reveal(settings: Settings,p:dict)->dict:
    now=time.time(); tt=str(p.get("target_type") or "block"); tk=str(p.get("target_key") or ""); state=str(p.get("state") or "hidden")
    if state not in {"hidden","rumor","discovered","public"}: state="hidden"
    audience=p.get("audience") or []
    with connect(settings) as conn:
        conn.execute("INSERT INTO lore_reveals(target_type,target_key,state,rumor_text,audience_json,expires_at,revealed_at,session_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(target_type,target_key) DO UPDATE SET state=excluded.state,rumor_text=excluded.rumor_text,audience_json=excluded.audience_json,expires_at=excluded.expires_at,revealed_at=excluded.revealed_at,session_id=excluded.session_id,updated_at=excluded.updated_at",(tt,tk,state,str(p.get("rumor_text") or ""),json.dumps(audience),p.get("expires_at"),now if state in {"discovered","public","rumor"} else None,p.get("session_id"),now))
    return reveal_state(settings,tt,tk)


def apply_reveals_to_html(settings: Settings, html_text: str, page_slug: str, *, admin: bool=False, invite_id: int|None=None) -> str:
    if admin: return html_text
    # Web-only authoring syntax creates wrappers with data-lore-reveal. The truth
    # lives inside the wrapper; hidden/rumor states are replaced server-side so it
    # never reaches the player's HTML or browser search index.
    pat=re.compile(r'<section class="lore-reveal" data-lore-reveal="([^"]+)"(?: data-rumor="([^"]*)")?>(.*?)</section>',re.S)
    def repl(m):
        key=m.group(1); rumor=m.group(2) or ""; state=reveal_state(settings,"block",f"{page_slug}:{key}",invite_id)
        if state["state"] in {"discovered","public"}: return m.group(3)
        if state["state"]=="rumor": return f'<aside class="lore-rumor"><small>RUMOR</small><p>{state.get("rumor_text") or rumor}</p></aside>'
        return '<div class="lore-undiscovered"><span>✦</span><small>UNDISCOVERED LORE</small></div>'
    return pat.sub(repl,html_text)


def list_reveal_blocks_from_wiki(wiki:dict)->list[dict]:
    out=[]
    for page in wiki.get("pages",[]):
        for m in re.finditer(r'data-lore-reveal="([^"]+)"(?: data-rumor="([^"]*)")?',page.get("html", "")):
            out.append({"page_slug":page["slug"],"page_title":page["title"],"key":m.group(1),"rumor":m.group(2) or "","target_key":f"{page['slug']}:{m.group(1)}"})
    return out


def list_variants(settings:Settings,slug:str,*,admin=False)->list[dict]:
    rows=_rows(settings,"SELECT * FROM lore_variants WHERE page_slug=? ORDER BY id",(slug,))
    return [r for r in rows if _visible(r["visibility"],admin)]


def save_variant(settings: Settings, p: dict) -> dict:
    now=time.time(); rid=p.get("id")
    page_slug=str(p.get("page_slug") or "").strip(); key=str(p.get("variant_key") or _slug(str(p.get("label") or "account"))).strip()
    if not page_slug: raise ValueError("Choose a Codex entry for the lore variant.")
    vals=(page_slug,key,str(p.get("label") or "Accounts differ"),str(p.get("common_text") or ""),str(p.get("truth_text") or ""),str(p.get("state") or "common"),str(p.get("visibility") or "players"),now)
    with connect(settings) as conn:
        if rid:
            conn.execute("UPDATE lore_variants SET page_slug=?,variant_key=?,label=?,common_text=?,truth_text=?,state=?,visibility=?,updated_at=? WHERE id=?",vals+(int(rid),)); out=int(rid)
        else:
            conn.execute("INSERT INTO lore_variants(page_slug,variant_key,label,common_text,truth_text,state,visibility,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(page_slug,variant_key) DO UPDATE SET label=excluded.label,common_text=excluded.common_text,truth_text=excluded.truth_text,state=excluded.state,visibility=excluded.visibility,updated_at=excluded.updated_at",vals)
            row=conn.execute("SELECT id FROM lore_variants WHERE page_slug=? AND variant_key=?",(page_slug,key)).fetchone(); out=int(row[0])
    return _row(settings,"SELECT * FROM lore_variants WHERE id=?",(out,)) or {}


def delete_variant(settings: Settings, rid: int) -> None:
    with connect(settings) as conn: conn.execute("DELETE FROM lore_variants WHERE id=?",(int(rid),))


# --- Notes / journal --------------------------------------------------------
def list_annotations(settings:Settings,page_slug:str,*,invite_id:int|None=None,admin=False)->list[dict]:
    if admin: return _rows(settings,"SELECT * FROM annotations WHERE page_slug=? ORDER BY created_at",(page_slug,))
    return _rows(settings,"SELECT * FROM annotations WHERE page_slug=? AND (visibility='party' OR (visibility='private' AND invite_id=?)) ORDER BY created_at",(page_slug,invite_id))


def add_annotation(settings:Settings,p:dict,*,invite_id:int|None,author_label:str,admin=False)->dict:
    visibility=str(p.get("visibility") or ("gm" if admin else "private"))
    allowed={"private","party","gm"}; visibility=visibility if visibility in allowed else "private"
    if not admin and visibility=="gm": visibility="private"
    now=time.time()
    with connect(settings) as conn:
        rid=conn.execute("INSERT INTO annotations(page_slug,anchor,quote,note,visibility,invite_id,author_label,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(str(p.get("page_slug") or ""),str(p.get("anchor") or ""),str(p.get("quote") or "")[:500],str(p.get("note") or ""),visibility,invite_id,author_label,now,now)).lastrowid
    return _row(settings,"SELECT * FROM annotations WHERE id=?",(rid,)) or {}


def log_activity(settings:Settings,invite_id:int|None,event_type:str,target_key:str="",meta:dict|None=None)->None:
    with connect(settings) as conn: conn.execute("INSERT INTO player_activity(invite_id,event_type,target_key,meta_json,created_at) VALUES(?,?,?,?,?)",(invite_id,event_type,target_key,json.dumps(meta or {}),time.time()))


def recent_updates(settings:Settings,invite_id:int|None,limit:int=30,*,admin:bool=False)->list[dict]:
    # Audience-scoped discoveries must never leak through the player feed. Fetch a
    # bounded superset, filter in Python for SQLite compatibility, then apply limit.
    fetch_limit=max(100,min(1000,int(limit)*8))
    rows=_rows(settings,"SELECT * FROM session_updates WHERE visibility!='gm' ORDER BY created_at DESC LIMIT ?",(fetch_limit,))
    if not admin:
        rows=[r for r in rows if _audience_allows(r,invite_id)]
    return rows[:int(limit)]


def toggle_bookmark(settings:Settings,invite_id:int,page_slug:str,enabled:bool)->None:
    with connect(settings) as conn:
        if enabled: conn.execute("INSERT OR REPLACE INTO player_bookmarks(invite_id,page_slug,created_at) VALUES(?,?,?)",(invite_id,page_slug,time.time()))
        else: conn.execute("DELETE FROM player_bookmarks WHERE invite_id=? AND page_slug=?",(invite_id,page_slug))


def list_bookmarks(settings:Settings,invite_id:int)->list[str]:
    return [r["page_slug"] for r in _rows(settings,"SELECT page_slug FROM player_bookmarks WHERE invite_id=? ORDER BY created_at DESC",(invite_id,))]


# --- Mysteries / handouts ---------------------------------------------------
def list_mysteries(settings:Settings,*,admin=False)->list[dict]:
    """Load investigation boards in three queries regardless of board count."""
    with connect(settings) as conn:
        rows=[dict(r) for r in conn.execute("SELECT * FROM mysteries ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'solved' THEN 1 ELSE 2 END,updated_at DESC").fetchall()]
        rows=[r for r in rows if _visible(r["visibility"],admin)]
        if not rows:return []
        ids=[int(r["id"]) for r in rows];ph=','.join('?' for _ in ids)
        pin_rows=[dict(x) for x in conn.execute(f"SELECT * FROM mystery_pins WHERE mystery_id IN ({ph}) ORDER BY mystery_id,id",ids).fetchall()]
        edge_rows=[dict(x) for x in conn.execute(f"SELECT * FROM mystery_edges WHERE mystery_id IN ({ph}) ORDER BY mystery_id,id",ids).fetchall()]
    pins_by={mid:[] for mid in ids};edges_by={mid:[] for mid in ids}
    for pin in pin_rows:
        if _visible(pin["visibility"],admin):pins_by.setdefault(int(pin["mystery_id"]),[]).append(pin)
    for edge in edge_rows:
        if _visible(edge["visibility"],admin):edges_by.setdefault(int(edge["mystery_id"]),[]).append(edge)
    for r in rows:
        mid=int(r["id"]);pins=pins_by.get(mid,[]);pin_by_id={int(x["id"]):x for x in pins};edges=[]
        for edge in edges_by.get(mid,[]):
            source=pin_by_id.get(int(edge["source_pin"]));target=pin_by_id.get(int(edge["target_pin"]))
            if not source or not target:continue
            edge["source_x"],edge["source_y"]=float(source["x"]),float(source["y"])
            edge["target_x"],edge["target_y"]=float(target["x"]),float(target["y"])
            edge["source_label"],edge["target_label"]=source["label"],target["label"];edges.append(edge)
        r["pins"]=pins;r["edges"]=edges
    return rows


def save_mystery(settings:Settings,p:dict)->dict:
    now=time.time(); rid=p.get("id"); title=str(p.get("title") or "Untitled mystery"); slug=_slug(p.get("slug") or title); vals=(title,slug,str(p.get("description") or ""),str(p.get("status") or "open"),str(p.get("visibility") or "players"),str(p.get("image_ref") or ""),now)
    with connect(settings) as conn:
        if rid: conn.execute("UPDATE mysteries SET title=?,slug=?,description=?,status=?,visibility=?,image_ref=?,updated_at=? WHERE id=?",vals+(int(rid),)); out=int(rid)
        else: out=conn.execute("INSERT INTO mysteries(title,slug,description,status,visibility,image_ref,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",vals[:-1]+(now,now)).lastrowid
    return _row(settings,"SELECT * FROM mysteries WHERE id=?",(out,)) or {}


def add_mystery_pin(settings:Settings,mid:int,p:dict)->dict:
    now=time.time()
    with connect(settings) as conn:
        rid=conn.execute("INSERT INTO mystery_pins(mystery_id,page_slug,label,note,x,y,visibility,created_at) VALUES(?,?,?,?,?,?,?,?)",(int(mid),p.get("page_slug") or None,str(p.get("label") or "Clue"),str(p.get("note") or ""),float(p.get("x") or .5),float(p.get("y") or .5),str(p.get("visibility") or "players"),now)).lastrowid
    return _row(settings,"SELECT * FROM mystery_pins WHERE id=?",(rid,)) or {}


def save_mystery_edge(settings:Settings,mid:int,p:dict)->dict:
    mid=int(mid); source=int(p.get("source_pin") or 0); target=int(p.get("target_pin") or 0)
    if not source or not target or source==target:
        raise ValueError("Choose two different clues to connect.")
    with connect(settings) as conn:
        owned=conn.execute("SELECT COUNT(*) FROM mystery_pins WHERE mystery_id=? AND id IN (?,?)",(mid,source,target)).fetchone()[0]
        if int(owned)!=2:
            raise ValueError("Both clues must belong to this mystery board.")
        rid=p.get("id")
        label=str(p.get("label") or "").strip()[:160]
        visibility=str(p.get("visibility") or "players")
        if visibility not in {"players","gm"}: visibility="players"
        if rid:
            row=conn.execute("SELECT id FROM mystery_edges WHERE id=? AND mystery_id=?",(int(rid),mid)).fetchone()
            if not row: raise ValueError("Connection not found on this mystery board.")
            conn.execute("UPDATE mystery_edges SET source_pin=?,target_pin=?,label=?,visibility=? WHERE id=?",(source,target,label,visibility,int(rid)))
            out=int(rid)
        else:
            out=conn.execute("INSERT INTO mystery_edges(mystery_id,source_pin,target_pin,label,visibility) VALUES(?,?,?,?,?)",(mid,source,target,label,visibility)).lastrowid
    return _row(settings,"SELECT * FROM mystery_edges WHERE id=?",(out,)) or {}


def delete_mystery_edge(settings:Settings,edge_id:int)->None:
    with connect(settings) as conn:
        conn.execute("DELETE FROM mystery_edges WHERE id=?",(int(edge_id),))


def delete_mystery_pin(settings:Settings,pin_id:int)->None:
    # Foreign-key cascade removes strings connected to this clue.
    with connect(settings) as conn:
        conn.execute("DELETE FROM mystery_pins WHERE id=?",(int(pin_id),))


def list_handouts(settings:Settings,*,admin=False)->list[dict]:
    now=time.time(); rows=_rows(settings,"SELECT * FROM handouts ORDER BY created_at DESC")
    return [r for r in rows if _visible(r["visibility"],admin) and (admin or not r.get("expires_at") or float(r["expires_at"])>now)]


def save_handout(settings:Settings,p:dict)->dict:
    now=time.time(); rid=p.get("id"); title=str(p.get("title") or "Handout"); slug=_slug(p.get("slug") or title); vals=(title,slug,str(p.get("body") or ""),str(p.get("kind") or "parchment"),str(p.get("image_ref") or ""),p.get("page_slug") or None,p.get("session_id"),str(p.get("visibility") or "players"),p.get("expires_at"),now)
    with connect(settings) as conn:
        if rid: conn.execute("UPDATE handouts SET title=?,slug=?,body=?,kind=?,image_ref=?,page_slug=?,session_id=?,visibility=?,expires_at=?,updated_at=? WHERE id=?",vals+(int(rid),)); out=int(rid)
        else: out=conn.execute("INSERT INTO handouts(title,slug,body,kind,image_ref,page_slug,session_id,visibility,expires_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",vals[:-1]+(now,now)).lastrowid
    return _row(settings,"SELECT * FROM handouts WHERE id=?",(out,)) or {}


# --- Map layers/fog/travel --------------------------------------------------
def map_layers(settings:Settings,map_id:int,*,public=False)->list[dict]:
    if public:
        return _rows(settings,"SELECT * FROM map_layers WHERE map_id=? AND enabled=1 AND visible_to_players=1 ORDER BY sort_order,id",(int(map_id),))
    # Admins must still see disabled layers so they can re-enable or edit them.
    return _rows(settings,"SELECT * FROM map_layers WHERE map_id=? ORDER BY sort_order,id",(int(map_id),))


def save_map_layer(settings:Settings,map_id:int,p:dict)->dict:
    now=time.time(); rid=p.get("id"); vals=(int(map_id),str(p.get("name") or "Layer"),str(p.get("image_path") or ""),str(p.get("kind") or "overlay"),max(0,min(1,float(p.get("opacity",.7)))),1 if p.get("visible_to_players",True) else 0,1 if p.get("enabled",True) else 0,int(p.get("sort_order") or 0),now)
    with connect(settings) as conn:
        if rid: conn.execute("UPDATE map_layers SET map_id=?,name=?,image_path=?,kind=?,opacity=?,visible_to_players=?,enabled=?,sort_order=?,updated_at=? WHERE id=?",vals+(int(rid),)); out=int(rid)
        else: out=conn.execute("INSERT INTO map_layers(map_id,name,image_path,kind,opacity,visible_to_players,enabled,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",vals[:-1]+(now,now)).lastrowid
    return _row(settings,"SELECT * FROM map_layers WHERE id=?",(out,)) or {}


def fog_regions(settings:Settings,map_id:int,*,public=False)->list[dict]:
    rows=_rows(settings,"SELECT * FROM map_fog_regions WHERE map_id=? ORDER BY id",(int(map_id),))
    for r in rows:
        try:r["points"]=json.loads(r.get("points_json") or "[]")
        except:r["points"]=[]
    return [r for r in rows if not public or not r["revealed"]]


def save_fog_region(settings:Settings,map_id:int,p:dict)->dict:
    now=time.time(); rid=p.get("id"); pts=p.get("points") or []; vals=(int(map_id),str(p.get("title") or "Unknown region"),json.dumps(pts),1 if p.get("revealed") else 0,str(p.get("style") or "parchment"),now)
    with connect(settings) as conn:
        if rid: conn.execute("UPDATE map_fog_regions SET map_id=?,title=?,points_json=?,revealed=?,style=?,updated_at=? WHERE id=?",vals+(int(rid),)); out=int(rid)
        else: out=conn.execute("INSERT INTO map_fog_regions(map_id,title,points_json,revealed,style,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",vals[:-1]+(now,now)).lastrowid
    return _row(settings,"SELECT * FROM map_fog_regions WHERE id=?",(out,)) or {}


def travel_between_markers(marker_a:dict,marker_b:dict,world_width:float=1000.0,speed:float=40.0)->dict:
    dist=math.hypot(float(marker_a["x"])-float(marker_b["x"]),float(marker_a["y"])-float(marker_b["y"]))*float(world_width)
    return {"distance":round(dist,1),"days":round(dist/max(.1,float(speed)),1),"world_width":world_width,"speed":speed}



# --- Player-owned characters ------------------------------------------------
def _character_payload(settings: Settings, row: dict, images: list[dict] | None = None) -> dict:
    out=dict(row)
    out["portrait_url"] = ("/uploads/" + out["portrait_path"]) if out.get("portrait_path") else ""
    if images is None:
        images=_rows(settings,"SELECT * FROM character_images WHERE character_id=? ORDER BY sort_order,id",(int(out["id"]),))
    imgs=[dict(x) for x in images]
    for img in imgs:img["url"]="/uploads/"+img["image_path"]
    out["images"]=imgs
    return out


def list_player_characters(settings: Settings, *, invite_id: int|None=None, admin: bool=False) -> list[dict]:
    """Load character dossiers and image boards in two queries total."""
    with connect(settings) as conn:
        if admin:
            rows=[dict(r) for r in conn.execute("SELECT c.*, i.label AS player_label FROM player_characters c JOIN player_invites i ON i.id=c.invite_id ORDER BY c.updated_at DESC,c.id DESC").fetchall()]
        elif invite_id is None:
            rows=[dict(r) for r in conn.execute("SELECT c.*, i.label AS player_label FROM player_characters c JOIN player_invites i ON i.id=c.invite_id WHERE c.visibility='party' ORDER BY c.updated_at DESC,c.id DESC").fetchall()]
        else:
            rows=[dict(r) for r in conn.execute("SELECT c.*, i.label AS player_label FROM player_characters c JOIN player_invites i ON i.id=c.invite_id WHERE c.visibility='party' OR c.invite_id=? ORDER BY CASE WHEN c.invite_id=? THEN 0 ELSE 1 END,c.updated_at DESC,c.id DESC",(int(invite_id),int(invite_id))).fetchall()]
        ids=[int(r['id']) for r in rows]
        image_rows=[]
        if ids:
            ph=','.join('?' for _ in ids)
            image_rows=[dict(x) for x in conn.execute(f"SELECT * FROM character_images WHERE character_id IN ({ph}) ORDER BY character_id,sort_order,id",ids).fetchall()]
    images_by={cid:[] for cid in ids}
    for image in image_rows:images_by.setdefault(int(image['character_id']),[]).append(image)
    return [_character_payload(settings,r,images_by.get(int(r['id']),[])) for r in rows]


def get_player_character(settings: Settings, character_id: int, *, invite_id: int|None=None, admin: bool=False) -> dict|None:
    with connect(settings) as conn:
        row=conn.execute("SELECT c.*, i.label AS player_label FROM player_characters c JOIN player_invites i ON i.id=c.invite_id WHERE c.id=?",(int(character_id),)).fetchone()
        if not row:return None
        row=dict(row)
        if not admin and row.get("visibility")!="party" and int(row.get("invite_id") or 0)!=int(invite_id or -1):return None
        images=[dict(x) for x in conn.execute("SELECT * FROM character_images WHERE character_id=? ORDER BY sort_order,id",(int(character_id),)).fetchall()]
    return _character_payload(settings,row,images)


def save_player_character(settings: Settings, p: dict, *, invite_id: int|None, admin: bool=False) -> dict:
    rid=p.get("id"); now=time.time()
    owner=int(p.get("invite_id") or invite_id or 0)
    if not owner: raise ValueError("A player invitation is required to own this character.")
    if rid:
        current=_row(settings,"SELECT * FROM player_characters WHERE id=?",(int(rid),))
        if not current: raise ValueError("Character not found.")
        if not admin and int(current["invite_id"])!=int(invite_id or -1): raise PermissionError("You can only edit your own characters.")
        owner=int(current["invite_id"])
    name=str(p.get("name") or "Unnamed hero").strip()[:160]
    vis=str(p.get("visibility") or "party"); vis=vis if vis in {"party","private"} else "party"
    status=str(p.get("status") or "active")[:40]
    theme=str(p.get("theme_color") or "#b79661")
    if not re.match(r"^#[0-9a-fA-F]{6}$",theme): theme="#b79661"
    vals=(owner,name,str(p.get("pronouns") or "")[:80],str(p.get("ancestry") or "")[:120],str(p.get("class_name") or "")[:120],int(p.get("level")) if str(p.get("level") or "").isdigit() else None,status,str(p.get("summary") or "")[:5000],str(p.get("biography") or "")[:30000],str(p.get("goals") or "")[:10000],str(p.get("player_notes") or "")[:15000],vis,theme,now)
    with connect(settings) as conn:
        if rid:
            conn.execute("UPDATE player_characters SET invite_id=?,name=?,pronouns=?,ancestry=?,class_name=?,level=?,status=?,summary=?,biography=?,goals=?,player_notes=?,visibility=?,theme_color=?,updated_at=? WHERE id=?",vals+(int(rid),)); out=int(rid)
        else:
            base=_slug(name); slug=base
            n=2
            while conn.execute("SELECT 1 FROM player_characters WHERE slug=?",(slug,)).fetchone(): slug=f"{base}-{n}"; n+=1
            out=conn.execute("INSERT INTO player_characters(invite_id,name,slug,pronouns,ancestry,class_name,level,status,summary,biography,goals,player_notes,visibility,theme_color,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",vals[:2]+(slug,)+vals[2:-1]+(now,now)).lastrowid
    return get_player_character(settings,out,invite_id=owner,admin=True) or {}


def delete_player_character(settings: Settings, character_id: int, *, invite_id: int|None, admin: bool=False) -> list[str]:
    row=_row(settings,"SELECT * FROM player_characters WHERE id=?",(int(character_id),))
    if not row: return []
    if not admin and int(row["invite_id"])!=int(invite_id or -1): raise PermissionError("You can only delete your own characters.")
    paths=[x["image_path"] for x in _rows(settings,"SELECT image_path FROM character_images WHERE character_id=?",(int(character_id),))]
    if row.get("portrait_path"): paths.append(row["portrait_path"])
    with connect(settings) as conn: conn.execute("DELETE FROM player_characters WHERE id=?",(int(character_id),))
    return list(dict.fromkeys(paths))


def add_character_image(settings: Settings, character_id:int, image_path:str, kind:str="inspiration", caption:str="", *, invite_id:int|None, admin:bool=False) -> dict:
    char=_row(settings,"SELECT * FROM player_characters WHERE id=?",(int(character_id),))
    if not char: raise ValueError("Character not found.")
    if not admin and int(char["invite_id"])!=int(invite_id or -1): raise PermissionError("You can only upload art for your own characters.")
    kind=kind if kind in {"portrait","inspiration","gallery"} else "inspiration"
    with connect(settings) as conn:
        rid=conn.execute("INSERT INTO character_images(character_id,image_path,kind,caption,created_at) VALUES(?,?,?,?,?)",(int(character_id),image_path,kind,str(caption or "")[:500],time.time())).lastrowid
        if kind=="portrait": conn.execute("UPDATE player_characters SET portrait_path=?,updated_at=? WHERE id=?",(image_path,time.time(),int(character_id)))
    row=_row(settings,"SELECT * FROM character_images WHERE id=?",(rid,)) or {}; row["url"]="/uploads/"+image_path
    return row


def delete_character_image(settings: Settings, image_id:int, *, invite_id:int|None, admin:bool=False) -> str:
    row=_row(settings,"SELECT ci.*,pc.invite_id,pc.portrait_path FROM character_images ci JOIN player_characters pc ON pc.id=ci.character_id WHERE ci.id=?",(int(image_id),))
    if not row: return ""
    if not admin and int(row["invite_id"])!=int(invite_id or -1): raise PermissionError("You can only remove art from your own characters.")
    with connect(settings) as conn:
        conn.execute("DELETE FROM character_images WHERE id=?",(int(image_id),))
        if row.get("portrait_path")==row.get("image_path"): conn.execute("UPDATE player_characters SET portrait_path='' WHERE id=?",(int(row["character_id"]),))
    return str(row.get("image_path") or "")


# --- Campaign snapshots / health -------------------------------------------
def create_snapshot(settings:Settings,label:str)->dict:
    snap_dir=settings.history_dir/"snapshots";snap_dir.mkdir(parents=True,exist_ok=True);stamp=time.strftime("%Y%m%d-%H%M%S");safe=_slug(label or "snapshot");path=snap_dir/f"{stamp}-{safe}.zip"
    # SQLite backup gives a transactionally consistent metadata copy. Map uploads
    # are included too so restoring a snapshot truly recreates the campaign state.
    db_copy=snap_dir/f".{stamp}-loreforge.db"
    src=sqlite3.connect(settings.db_path);dst=sqlite3.connect(db_copy);src.backup(dst);dst.close();src.close()
    try:
        with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
            for f in settings.project_dir.rglob("*"):
                if f.is_file(): z.write(f,"project/"+f.relative_to(settings.project_dir).as_posix())
            for f in settings.uploads_dir.rglob("*"):
                if f.is_file(): z.write(f,"uploads/"+f.relative_to(settings.uploads_dir).as_posix())
            z.write(db_copy,"loreforge.db")
    finally:
        db_copy.unlink(missing_ok=True)
    with connect(settings) as conn: rid=conn.execute("INSERT INTO campaign_snapshots(label,path,created_at) VALUES(?,?,?)",(label or "Snapshot",str(path),time.time())).lastrowid
    return _row(settings,"SELECT * FROM campaign_snapshots WHERE id=?",(rid,)) or {}


def restore_snapshot(settings: Settings, snapshot_path: str | Path) -> dict:
    snapshot_path=Path(snapshot_path)
    if not snapshot_path.exists(): raise FileNotFoundError(snapshot_path)
    temp=Path(tempfile.mkdtemp(prefix="loreforge-snapshot-"))
    try:
        with zipfile.ZipFile(snapshot_path) as z:
            for member in z.infolist():
                name=member.filename.replace("\\","/")
                if name.startswith("/") or ".." in Path(name).parts: raise ValueError("Unsafe snapshot path")
            z.extractall(temp)
        project=temp/"project"; uploads=temp/"uploads"; snap_db=temp/"loreforge.db"
        if not project.exists() or not snap_db.exists(): raise ValueError("Snapshot is missing campaign source or metadata.")
        # Copy to temporary siblings first, then swap directories.
        new_project=settings.data_dir/".restore-project"; new_uploads=settings.data_dir/".restore-uploads"
        shutil.rmtree(new_project,ignore_errors=True); shutil.rmtree(new_uploads,ignore_errors=True)
        shutil.copytree(project,new_project)
        if uploads.exists(): shutil.copytree(uploads,new_uploads)
        else: new_uploads.mkdir(parents=True,exist_ok=True)
        old_project=settings.data_dir/".restore-old-project"; old_uploads=settings.data_dir/".restore-old-uploads"
        shutil.rmtree(old_project,ignore_errors=True); shutil.rmtree(old_uploads,ignore_errors=True)
        if settings.project_dir.exists(): settings.project_dir.rename(old_project)
        new_project.rename(settings.project_dir)
        if settings.uploads_dir.exists(): settings.uploads_dir.rename(old_uploads)
        new_uploads.rename(settings.uploads_dir)
        try:
            src=sqlite3.connect(snap_db); dst=sqlite3.connect(settings.db_path); src.backup(dst); dst.close(); src.close()
        except Exception:
            shutil.rmtree(settings.project_dir,ignore_errors=True); old_project.rename(settings.project_dir)
            shutil.rmtree(settings.uploads_dir,ignore_errors=True); old_uploads.rename(settings.uploads_dir)
            raise
        shutil.rmtree(old_project,ignore_errors=True); shutil.rmtree(old_uploads,ignore_errors=True)
        return {"ok":True,"snapshot":str(snapshot_path)}
    finally:
        shutil.rmtree(temp,ignore_errors=True)

def list_snapshots(settings:Settings)->list[dict]: return _rows(settings,"SELECT * FROM campaign_snapshots ORDER BY created_at DESC")


def campaign_health(settings:Settings,wiki:dict,maps:list[dict])->dict:
    pages=wiki.get("pages",[]); slugs={p["slug"] for p in pages}; rels=list_relationships(settings,admin=True)
    issues=[]
    for p in pages:
        if p.get("level")=="entity" and "lore-profile-grid" not in p.get("html",""): issues.append({"kind":"profile","severity":"info","title":p["title"],"message":"Person of Note has no structured Profile grid.","href":f"/wiki/{p['slug']}"})
        if not (p.get("presentation",{}).get("auto_image_url") or p.get("presentation",{}).get("hero_image_url")): issues.append({"kind":"image","severity":"info","title":p["title"],"message":"No artwork discovered for this entry.","href":f"/wiki/{p['slug']}"})
    for r in rels:
        if r["source_slug"] not in slugs or r["target_slug"] not in slugs: issues.append({"kind":"relationship","severity":"warning","title":r["relation"],"message":"Relationship points to a missing Codex entry.","href":"/network"})
    for m in maps:
        for marker in m.get("markers",[]):
            if marker.get("page_slug") and marker["page_slug"] not in slugs: issues.append({"kind":"map","severity":"warning","title":marker["title"],"message":"Map marker links to a missing Codex entry.","href":f"/atlas/{m['slug']}"})
    linked={r["source_slug"] for r in rels}|{r["target_slug"] for r in rels}
    orphan=[p for p in pages if not p.get("outgoing_links") and not p.get("backlinks") and p["slug"] not in linked]
    viewed={r["target_key"] for r in _rows(settings,"SELECT DISTINCT target_key FROM player_activity WHERE event_type='view' AND target_key!=''")}
    unvisited=[p for p in pages if p["slug"] not in viewed]
    for p in unvisited[:20]: issues.append({"kind":"unvisited","severity":"info","title":p["title"],"message":"No invited player has opened this entry yet.","href":f"/wiki/{p['slug']}"})
    return {"issues":issues,"counts":{"pages":len(pages),"relationships":len(rels),"maps":len(maps),"orphans":len(orphan),"unvisited":len(unvisited),"issues":len(issues)},"orphans":[{"slug":p["slug"],"title":p["title"]} for p in orphan[:50]],"unvisited":[{"slug":p["slug"],"title":p["title"]} for p in unvisited[:50]]}
