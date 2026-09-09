from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from .config import Settings
from .storage import connect, get_setting, set_setting

LIVING_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS player_knowledge (
    invite_id INTEGER NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'page',
    target_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'unknown',
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'gm',
    updated_at REAL NOT NULL,
    PRIMARY KEY(invite_id,target_type,target_key),
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS campaign_fronts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL DEFAULT 'faction',
    summary TEXT NOT NULL DEFAULT '',
    goal TEXT NOT NULL DEFAULT '',
    next_move TEXT NOT NULL DEFAULT '',
    page_slug TEXT,
    current_value INTEGER NOT NULL DEFAULT 0,
    max_value INTEGER NOT NULL DEFAULT 6,
    status TEXT NOT NULL DEFAULT 'active',
    visibility TEXT NOT NULL DEFAULT 'gm',
    owner_invite_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS front_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    front_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    value_after INTEGER,
    session_id INTEGER,
    visible_to_players INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    FOREIGN KEY(front_id) REFERENCES campaign_fronts(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS entity_runtime_state (
    page_slug TEXT PRIMARY KEY,
    location_slug TEXT,
    status TEXT NOT NULL DEFAULT '',
    attitude TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    faction_slug TEXT,
    last_seen_session INTEGER,
    state_note TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'gm',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS relationship_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_slug TEXT NOT NULL,
    target_slug TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'related to',
    label TEXT NOT NULL DEFAULT '',
    start_label TEXT NOT NULL DEFAULT '',
    end_label TEXT NOT NULL DEFAULT '',
    start_sort REAL,
    end_sort REAL,
    visibility TEXT NOT NULL DEFAULT 'players',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS entity_hierarchy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chart_key TEXT NOT NULL,
    chart_title TEXT NOT NULL DEFAULT '',
    chart_kind TEXT NOT NULL DEFAULT 'organization',
    parent_slug TEXT,
    child_slug TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'member',
    sort_order INTEGER NOT NULL DEFAULT 0,
    visibility TEXT NOT NULL DEFAULT 'players',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS map_regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    map_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'region',
    page_slug TEXT,
    points_json TEXT NOT NULL DEFAULT '[]',
    fill TEXT NOT NULL DEFAULT '#b79661',
    opacity REAL NOT NULL DEFAULT 0.22,
    border TEXT NOT NULL DEFAULT '#d4b16f',
    visibility TEXT NOT NULL DEFAULT 'players',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS map_region_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_id INTEGER NOT NULL,
    start_sort REAL,
    end_sort REAL,
    start_label TEXT NOT NULL DEFAULT '',
    end_label TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    points_json TEXT NOT NULL DEFAULT '[]',
    fill TEXT NOT NULL DEFAULT '',
    opacity REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY(region_id) REFERENCES map_regions(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS rumors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    truth_state TEXT NOT NULL DEFAULT 'unknown',
    truth_note TEXT NOT NULL DEFAULT '',
    location_slug TEXT,
    faction_slug TEXT,
    page_slug TEXT,
    status TEXT NOT NULL DEFAULT 'unheard',
    visibility TEXT NOT NULL DEFAULT 'players',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'normal',
    visibility TEXT NOT NULL DEFAULT 'party',
    editing TEXT NOT NULL DEFAULT 'party',
    created_by_invite_id INTEGER,
    assigned_character_id INTEGER,
    due_label TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS thread_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    invite_id INTEGER,
    author_label TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    visibility TEXT NOT NULL DEFAULT 'party',
    gm_edited INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES campaign_threads(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS thread_links (
    thread_id INTEGER NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'page',
    target_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    created_by_invite_id INTEGER,
    PRIMARY KEY(thread_id,target_type,target_key),
    FOREIGN KEY(thread_id) REFERENCES campaign_threads(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS player_journals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invite_id INTEGER NOT NULL,
    character_id INTEGER,
    session_id INTEGER,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE,
    FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS gm_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'note',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    asset_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'inbox',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS player_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invite_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'lore',
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    target_key TEXT NOT NULL DEFAULT '',
    asset_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    gm_note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS publishing_states (
    page_slug TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'published',
    publish_group TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS session_state_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    phase TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(session_id,phase)
);
CREATE TABLE IF NOT EXISTS lore_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    source_slug TEXT NOT NULL,
    target_key TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(kind,source_slug,target_key,label)
);
CREATE TABLE IF NOT EXISTS media_catalog (
    ref TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'art',
    tags_json TEXT NOT NULL DEFAULT '[]',
    focal_x REAL NOT NULL DEFAULT 50,
    focal_y REAL NOT NULL DEFAULT 50,
    alt_text TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT '',
    target_key TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'notice',
    audience_json TEXT NOT NULL DEFAULT '[]',
    expires_at REAL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_reads (
    notification_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    read_at REAL NOT NULL,
    PRIMARY KEY(notification_id,invite_id),
    FOREIGN KEY(notification_id) REFERENCES campaign_notifications(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS character_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'page',
    target_key TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'knows',
    note TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'private',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS character_arcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'goal',
    status TEXT NOT NULL DEFAULT 'active',
    visibility TEXT NOT NULL DEFAULT 'private',
    session_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE CASCADE
);
'''


def init_living_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(LIVING_SCHEMA)
        # v4: session journals can belong to one of a player's characters.
        # Rebuild the v3 table once so its old uniqueness constraint cannot make
        # two characters collide on the same session/title combination.
        journal_cols = {r[1] for r in conn.execute("PRAGMA table_info(player_journals)").fetchall()}
        if "character_id" not in journal_cols:
            conn.execute("ALTER TABLE player_journals RENAME TO player_journals_v3")
            conn.execute("""CREATE TABLE player_journals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invite_id INTEGER NOT NULL,
                character_id INTEGER,
                session_id INTEGER,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                visibility TEXT NOT NULL DEFAULT 'private',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE,
                FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE SET NULL
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_player_journals_owner_character ON player_journals(invite_id,character_id,updated_at DESC)")
            conn.execute("""INSERT INTO player_journals(id,invite_id,character_id,session_id,title,body,visibility,created_at,updated_at)
                            SELECT id,invite_id,NULL,session_id,title,body,visibility,created_at,updated_at FROM player_journals_v3""")
            conn.execute("DROP TABLE player_journals_v3")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_player_journals_owner_character ON player_journals(invite_id,character_id,updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_created ON campaign_notifications(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_reads_invite ON notification_reads(invite_id,notification_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fronts_visibility_updated ON campaign_fronts(visibility,updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_threads_visibility_updated ON campaign_threads(visibility,updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_front_events_front_created ON front_events(front_id,created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_notes_thread_created ON thread_notes(thread_id,created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_links_thread_target ON thread_links(thread_id,target_type,target_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_map_region_history_region_sort ON map_region_history(region_id,start_sort,id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_player_knowledge_invite_updated ON player_knowledge(invite_id,updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_publishing_states_updated ON publishing_states(updated_at DESC)")


def _rows(settings: Settings, sql: str, params: tuple = ()) -> list[dict]:
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _row(settings: Settings, sql: str, params: tuple = ()) -> dict | None:
    with connect(settings) as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def _slug(value: str) -> str:
    out = re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')
    return out or f'item-{int(time.time())}'


def _json(value: Any, fallback):
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value if value is not None else fallback
    except Exception:
        return fallback


def knowledge_state(settings: Settings, invite_id: int | None, target_type: str, target_key: str) -> dict | None:
    if invite_id is None:
        return None
    return _row(settings, 'SELECT * FROM player_knowledge WHERE invite_id=? AND target_type=? AND target_key=?', (int(invite_id), target_type, target_key))


def set_knowledge(settings: Settings, invite_id: int, target_type: str, target_key: str, state: str, note: str = '', source: str = 'gm') -> dict:
    state = state if state in {'unknown','rumor','known','mastered'} else 'known'
    now = time.time()
    with connect(settings) as conn:
        conn.execute('''INSERT INTO player_knowledge(invite_id,target_type,target_key,state,note,source,updated_at) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(invite_id,target_type,target_key) DO UPDATE SET state=excluded.state,note=excluded.note,source=excluded.source,updated_at=excluded.updated_at''',
            (int(invite_id), target_type, target_key, state, note, source, now))
    return knowledge_state(settings, invite_id, target_type, target_key) or {}


def list_knowledge(settings: Settings, invite_id: int | None = None) -> list[dict]:
    if invite_id is None:
        return _rows(settings, 'SELECT * FROM player_knowledge ORDER BY updated_at DESC')
    return _rows(settings, 'SELECT * FROM player_knowledge WHERE invite_id=? ORDER BY updated_at DESC', (int(invite_id),))

def knowledge_index(settings: Settings, invite_id: int | None) -> dict[tuple[str,str], dict]:
    """Explicit per-player knowledge overrides keyed by (target_type,target_key)."""
    if invite_id is None:
        return {}
    return {(str(r['target_type']), str(r['target_key'])): r for r in list_knowledge(settings, invite_id)}


def knowledge_allows(settings: Settings, invite_id: int | None, target_type: str, target_key: str, *, default: bool=True) -> tuple[bool,str]:
    row = knowledge_state(settings, invite_id, target_type, target_key)
    if not row:
        return default, 'default'
    state = str(row.get('state') or 'unknown')
    return state != 'unknown', state



def list_fronts(settings: Settings, *, admin: bool = False, invite_id: int | None = None) -> list[dict]:
    """Load fronts and their event history in two queries, not one query/front."""
    with connect(settings) as conn:
        rows=[dict(r) for r in conn.execute('SELECT * FROM campaign_fronts ORDER BY status="active" DESC, updated_at DESC').fetchall()]
        visible=[]
        for r in rows:
            if not admin and r['visibility'] not in {'players','party'} and int(r.get('owner_invite_id') or -1) != int(invite_id or -2):
                continue
            visible.append(r)
        if not visible:return []
        ids=[int(r['id']) for r in visible];placeholders=','.join('?' for _ in ids)
        q=f'SELECT * FROM front_events WHERE front_id IN ({placeholders})'
        if not admin:q+=' AND visible_to_players=1'
        q+=' ORDER BY front_id,created_at DESC'
        events=[dict(e) for e in conn.execute(q,ids).fetchall()]
    by={fid:[] for fid in ids}
    for e in events:by.setdefault(int(e['front_id']),[]).append(e)
    for r in visible:r['events']=by.get(int(r['id']),[])
    return visible


def save_front(settings: Settings, p: dict) -> dict:
    now=time.time(); fid=p.get('id'); title=str(p.get('title') or 'Untitled front').strip(); slug=str(p.get('slug') or _slug(title))
    vals=(title,slug,str(p.get('kind') or 'faction'),str(p.get('summary') or ''),str(p.get('goal') or ''),str(p.get('next_move') or ''),p.get('page_slug') or None,max(0,int(p.get('current_value') or 0)),max(1,int(p.get('max_value') or 6)),str(p.get('status') or 'active'),str(p.get('visibility') or 'gm'),p.get('owner_invite_id'),now)
    with connect(settings) as conn:
        if fid:
            conn.execute('UPDATE campaign_fronts SET title=?,slug=?,kind=?,summary=?,goal=?,next_move=?,page_slug=?,current_value=?,max_value=?,status=?,visibility=?,owner_invite_id=?,updated_at=? WHERE id=?',vals+(int(fid),)); out=int(fid)
        else:
            cur=conn.execute('INSERT INTO campaign_fronts(title,slug,kind,summary,goal,next_move,page_slug,current_value,max_value,status,visibility,owner_invite_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals[:-1]+(now,now));out=cur.lastrowid
    return _row(settings,'SELECT * FROM campaign_fronts WHERE id=?',(out,)) or {}


def advance_front(settings: Settings, front_id: int, delta: int, label: str, body: str='', session_id: int|None=None, visible: bool=False) -> dict:
    front=_row(settings,'SELECT * FROM campaign_fronts WHERE id=?',(int(front_id),))
    if not front: raise ValueError('Front not found')
    value=min(int(front['max_value']),max(0,int(front['current_value'])+int(delta)))
    now=time.time()
    with connect(settings) as conn:
        conn.execute('UPDATE campaign_fronts SET current_value=?,updated_at=? WHERE id=?',(value,now,int(front_id)))
        conn.execute('INSERT INTO front_events(front_id,label,body,value_after,session_id,visible_to_players,created_at) VALUES(?,?,?,?,?,?,?)',(int(front_id),label,body,value,session_id,1 if visible else 0,now))
    return _row(settings,'SELECT * FROM campaign_fronts WHERE id=?',(int(front_id),)) or {}


def runtime_states(settings: Settings, *, admin: bool=False) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM entity_runtime_state ORDER BY updated_at DESC')
    return rows if admin else [r for r in rows if r['visibility'] in {'players','party'}]


def runtime_state_for_page(settings: Settings, slug: str, *, admin: bool=False) -> dict | None:
    """Fetch one mutable entity state without scanning the whole state table."""
    row=_row(settings,'SELECT * FROM entity_runtime_state WHERE page_slug=?',(str(slug),))
    if not row:return None
    if not admin and row.get('visibility') not in {'players','party'}:return None
    return row


def save_runtime_state(settings: Settings, slug: str, p: dict) -> dict:
    now=time.time(); vals=(p.get('location_slug') or None,str(p.get('status') or ''),str(p.get('attitude') or ''),str(p.get('objective') or ''),p.get('faction_slug') or None,p.get('last_seen_session'),str(p.get('state_note') or ''),str(p.get('visibility') or 'gm'),now,slug)
    with connect(settings) as conn:
        conn.execute('''INSERT INTO entity_runtime_state(page_slug,location_slug,status,attitude,objective,faction_slug,last_seen_session,state_note,visibility,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(page_slug) DO UPDATE SET location_slug=excluded.location_slug,status=excluded.status,attitude=excluded.attitude,objective=excluded.objective,faction_slug=excluded.faction_slug,last_seen_session=excluded.last_seen_session,state_note=excluded.state_note,visibility=excluded.visibility,updated_at=excluded.updated_at''',
          (slug,)+vals[:-1])
    return _row(settings,'SELECT * FROM entity_runtime_state WHERE page_slug=?',(slug,)) or {}


def relationship_history(settings: Settings, *, admin: bool=False, at_sort: float|None=None) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM relationship_history ORDER BY COALESCE(start_sort,-1e99),id')
    if not admin: rows=[r for r in rows if r['visibility'] not in {'gm','hidden'}]
    if at_sort is not None:
        rows=[r for r in rows if (r['start_sort'] is None or float(r['start_sort'])<=at_sort) and (r['end_sort'] is None or float(r['end_sort'])>=at_sort)]
    return rows


def save_relationship_history(settings: Settings,p:dict)->dict:
    now=time.time();rid=p.get('id');vals=(str(p.get('source_slug') or ''),str(p.get('target_slug') or ''),str(p.get('relation') or 'related to'),str(p.get('label') or ''),str(p.get('start_label') or ''),str(p.get('end_label') or ''),p.get('start_sort'),p.get('end_sort'),str(p.get('visibility') or 'players'),now)
    with connect(settings) as conn:
        if rid: conn.execute('UPDATE relationship_history SET source_slug=?,target_slug=?,relation=?,label=?,start_label=?,end_label=?,start_sort=?,end_sort=?,visibility=? WHERE id=?',vals[:-1]+(int(rid),));out=int(rid)
        else: out=conn.execute('INSERT INTO relationship_history(source_slug,target_slug,relation,label,start_label,end_label,start_sort,end_sort,visibility,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',vals).lastrowid
    return _row(settings,'SELECT * FROM relationship_history WHERE id=?',(out,)) or {}


def hierarchies(settings: Settings, *, admin: bool=False) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM entity_hierarchy ORDER BY chart_title,chart_key,sort_order,id')
    if not admin: rows=[r for r in rows if r['visibility'] not in {'gm','hidden'}]
    grouped={}
    for r in rows:
        g=grouped.setdefault(r['chart_key'],{'key':r['chart_key'],'title':r['chart_title'] or r['chart_key'],'kind':r['chart_kind'],'nodes':[]});g['nodes'].append(r)
    return list(grouped.values())


def save_hierarchy_edge(settings: Settings,p:dict)->dict:
    now=time.time();rid=p.get('id');vals=(str(p.get('chart_key') or _slug(p.get('chart_title') or 'chart')),str(p.get('chart_title') or ''),str(p.get('chart_kind') or 'organization'),p.get('parent_slug') or None,str(p.get('child_slug') or ''),str(p.get('relation') or 'member'),int(p.get('sort_order') or 0),str(p.get('visibility') or 'players'),now)
    with connect(settings) as conn:
        if rid: conn.execute('UPDATE entity_hierarchy SET chart_key=?,chart_title=?,chart_kind=?,parent_slug=?,child_slug=?,relation=?,sort_order=?,visibility=? WHERE id=?',vals[:-1]+(int(rid),));out=int(rid)
        else:out=conn.execute('INSERT INTO entity_hierarchy(chart_key,chart_title,chart_kind,parent_slug,child_slug,relation,sort_order,visibility,created_at) VALUES(?,?,?,?,?,?,?,?,?)',vals).lastrowid
    return _row(settings,'SELECT * FROM entity_hierarchy WHERE id=?',(out,)) or {}


def map_regions(settings: Settings,map_id:int,*,admin:bool=False,at_sort:float|None=None)->list[dict]:
    """Load all regions + historical shapes for one map in two queries."""
    with connect(settings) as conn:
        rows=[dict(r) for r in conn.execute('SELECT * FROM map_regions WHERE map_id=? ORDER BY id',(int(map_id),)).fetchall()]
        if not admin:rows=[r for r in rows if r['visibility'] not in {'gm','hidden'}]
        ids=[int(r['id']) for r in rows]
        history_rows=[]
        if ids:
            ph=','.join('?' for _ in ids)
            history_rows=[dict(h) for h in conn.execute(f'SELECT * FROM map_region_history WHERE region_id IN ({ph}) ORDER BY region_id,COALESCE(start_sort,-1e99),id',ids).fetchall()]
    by={rid:[] for rid in ids}
    for h in history_rows:
        h['points']=_json(h.pop('points_json','[]'),[]);by.setdefault(int(h['region_id']),[]).append(h)
    for r in rows:
        r['points']=_json(r.pop('points_json','[]'),[]);history=by.get(int(r['id']),[])
        if at_sort is not None:
            active=next((h for h in reversed(history) if (h['start_sort'] is None or float(h['start_sort'])<=at_sort) and (h['end_sort'] is None or float(h['end_sort'])>=at_sort)),None)
            if active:
                r['points']=active.get('points') or r['points'];r['fill']=active['fill'] or r['fill'];r['opacity']=active['opacity'] if active['opacity'] is not None else r['opacity'];r['history_label']=active['title'] or active['start_label']
        r['history']=history
    return rows


def save_map_region(settings: Settings,map_id:int,p:dict)->dict:
    now=time.time();rid=p.get('id');pts=json.dumps(p.get('points') or []);vals=(int(map_id),str(p.get('title') or 'Region'),str(p.get('kind') or 'region'),p.get('page_slug') or None,pts,str(p.get('fill') or '#b79661'),float(p.get('opacity') if p.get('opacity') is not None else .22),str(p.get('border') or '#d4b16f'),str(p.get('visibility') or 'players'),now)
    with connect(settings) as conn:
        if rid: conn.execute('UPDATE map_regions SET map_id=?,title=?,kind=?,page_slug=?,points_json=?,fill=?,opacity=?,border=?,visibility=?,updated_at=? WHERE id=?',vals+(int(rid),));out=int(rid)
        else:out=conn.execute('INSERT INTO map_regions(map_id,title,kind,page_slug,points_json,fill,opacity,border,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',vals[:-1]+(now,now)).lastrowid
    return next((r for r in map_regions(settings,map_id,admin=True) if int(r['id'])==int(out)),{})


def save_region_history(settings: Settings,region_id:int,p:dict)->dict:
    now=time.time();rid=p.get('id');vals=(int(region_id),p.get('start_sort'),p.get('end_sort'),str(p.get('start_label') or ''),str(p.get('end_label') or ''),str(p.get('title') or ''),json.dumps(p.get('points') or []),str(p.get('fill') or ''),p.get('opacity'),now)
    with connect(settings) as conn:
        if rid:conn.execute('UPDATE map_region_history SET region_id=?,start_sort=?,end_sort=?,start_label=?,end_label=?,title=?,points_json=?,fill=?,opacity=? WHERE id=?',vals[:-1]+(int(rid),));out=int(rid)
        else:out=conn.execute('INSERT INTO map_region_history(region_id,start_sort,end_sort,start_label,end_label,title,points_json,fill,opacity,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',vals).lastrowid
    return _row(settings,'SELECT * FROM map_region_history WHERE id=?',(out,)) or {}


def list_rumors(settings: Settings, *, admin:bool=False, location_slug:str='', faction_slug:str='')->list[dict]:
    rows=_rows(settings,'SELECT * FROM rumors ORDER BY status="unheard" DESC,updated_at DESC')
    if not admin: rows=[r for r in rows if r['visibility'] not in {'gm','hidden'} and r['status']!='unheard']
    if location_slug: rows=[r for r in rows if not r['location_slug'] or r['location_slug']==location_slug]
    if faction_slug: rows=[r for r in rows if not r['faction_slug'] or r['faction_slug']==faction_slug]
    return rows


def save_rumor(settings:Settings,p:dict)->dict:
    now=time.time();rid=p.get('id');vals=(str(p.get('title') or 'Rumor'),str(p.get('body') or ''),str(p.get('truth_state') or 'unknown'),str(p.get('truth_note') or ''),p.get('location_slug') or None,p.get('faction_slug') or None,p.get('page_slug') or None,str(p.get('status') or 'unheard'),str(p.get('visibility') or 'players'),now)
    with connect(settings) as conn:
        if rid:conn.execute('UPDATE rumors SET title=?,body=?,truth_state=?,truth_note=?,location_slug=?,faction_slug=?,page_slug=?,status=?,visibility=?,updated_at=? WHERE id=?',vals+(int(rid),));out=int(rid)
        else:out=conn.execute('INSERT INTO rumors(title,body,truth_state,truth_note,location_slug,faction_slug,page_slug,status,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',vals[:-1]+(now,now)).lastrowid
    return _row(settings,'SELECT * FROM rumors WHERE id=?',(out,)) or {}

def random_rumor(settings:Settings,*,location_slug:str='',faction_slug:str='',include_heard:bool=False)->dict|None:
    rows=list_rumors(settings,admin=True,location_slug=location_slug,faction_slug=faction_slug)
    rows=[r for r in rows if r.get('visibility') not in {'gm','hidden'} and (include_heard or r.get('status')=='unheard')]
    if not rows and not include_heard:
        return random_rumor(settings,location_slug=location_slug,faction_slug=faction_slug,include_heard=True)
    if not rows:
        return None
    import random
    return random.SystemRandom().choice(rows)



def list_threads(settings:Settings,*,admin:bool=False,invite_id:int|None=None)->list[dict]:
    """Load threads, notes and lore links with three bounded queries total."""
    with connect(settings) as conn:
        rows=[dict(r) for r in conn.execute('SELECT * FROM campaign_threads ORDER BY status="open" DESC,updated_at DESC').fetchall()]
        visible=[]
        for r in rows:
            if not admin:
                if r['visibility']=='gm':continue
                if r['visibility']=='private' and int(r.get('created_by_invite_id') or -1)!=int(invite_id or -2):continue
            visible.append(r)
        if not visible:return []
        ids=[int(r['id']) for r in visible];ph=','.join('?' for _ in ids)
        notes=[dict(n) for n in conn.execute(f'SELECT * FROM thread_notes WHERE thread_id IN ({ph}) ORDER BY thread_id,created_at DESC',ids).fetchall()]
        links=[dict(l) for l in conn.execute(f'SELECT * FROM thread_links WHERE thread_id IN ({ph}) ORDER BY thread_id,target_type,target_key',ids).fetchall()]
    notes_by={tid:[] for tid in ids};links_by={tid:[] for tid in ids}
    for n in notes:
        if admin or n['visibility']=='party' or int(n.get('invite_id') or -1)==int(invite_id or -2):notes_by.setdefault(int(n['thread_id']),[]).append(n)
    for l in links:links_by.setdefault(int(l['thread_id']),[]).append(l)
    for r in visible:
        tid=int(r['id']);r['notes']=notes_by.get(tid,[]);r['links']=links_by.get(tid,[])
    return visible


def can_edit_thread(thread:dict,invite_id:int|None,admin:bool)->bool:
    if admin:return True
    if invite_id is None:return False
    if thread['editing']=='party':return True
    return int(thread.get('created_by_invite_id') or -1)==int(invite_id)


def save_thread(settings:Settings,p:dict,*,invite_id:int|None=None,admin:bool=False)->dict:
    now=time.time();tid=p.get('id')
    if tid:
        current=_row(settings,'SELECT * FROM campaign_threads WHERE id=?',(int(tid),))
        if not current:raise ValueError('Thread not found')
        if not can_edit_thread(current,invite_id,admin):raise PermissionError('This thread is GM-managed.')
    title=str(p.get('title') or 'Untitled thread').strip();slug=str(p.get('slug') or _slug(title));created_by=p.get('created_by_invite_id') if admin else invite_id
    visibility=str(p.get('visibility') or 'party');editing=str(p.get('editing') or 'party')
    if not admin:
        visibility='private' if visibility=='private' else 'party'; editing='owner' if editing=='owner' else 'party'
    vals=(title,slug,str(p.get('summary') or ''),str(p.get('status') or 'open'),str(p.get('priority') or 'normal'),visibility,editing,created_by,p.get('assigned_character_id'),str(p.get('due_label') or ''),now)
    with connect(settings) as conn:
        if tid:conn.execute('UPDATE campaign_threads SET title=?,slug=?,summary=?,status=?,priority=?,visibility=?,editing=?,created_by_invite_id=COALESCE(created_by_invite_id,?),assigned_character_id=?,due_label=?,updated_at=? WHERE id=?',vals+(int(tid),));out=int(tid)
        else:out=conn.execute('INSERT INTO campaign_threads(title,slug,summary,status,priority,visibility,editing,created_by_invite_id,assigned_character_id,due_label,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',vals[:-1]+(now,now)).lastrowid
    return next((x for x in list_threads(settings,admin=True) if int(x['id'])==int(out)),{})


def add_thread_note(settings:Settings,thread_id:int,p:dict,*,invite_id:int|None=None,author_label:str='',admin:bool=False)->dict:
    t=_row(settings,'SELECT * FROM campaign_threads WHERE id=?',(int(thread_id),))
    if not t or not can_edit_thread(t,invite_id,admin):raise PermissionError('You cannot edit this thread.')
    now=time.time();visibility=str(p.get('visibility') or 'party')
    if not admin and visibility not in {'party','private'}:visibility='party'
    with connect(settings) as conn:
        nid=conn.execute('INSERT INTO thread_notes(thread_id,invite_id,author_label,body,kind,visibility,gm_edited,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(int(thread_id),invite_id,author_label or ('GM' if admin else 'Player'),str(p.get('body') or ''),str(p.get('kind') or 'note'),visibility,1 if admin else 0,now,now)).lastrowid
    return _row(settings,'SELECT * FROM thread_notes WHERE id=?',(nid,)) or {}

def update_thread_note(settings:Settings,note_id:int,p:dict,*,invite_id:int|None=None,admin:bool=False)->dict:
    note=_row(settings,'SELECT * FROM thread_notes WHERE id=?',(int(note_id),))
    if not note:raise ValueError('Thread note not found')
    thread=_row(settings,'SELECT * FROM campaign_threads WHERE id=?',(int(note['thread_id']),))
    owns=int(note.get('invite_id') or -1)==int(invite_id or -2)
    if not admin and (not owns or not thread or not can_edit_thread(thread,invite_id,False)):
        raise PermissionError('You can only edit your own notes on editable threads.')
    vis=str(p.get('visibility',note.get('visibility') or 'party'))
    if not admin and vis not in {'party','private'}:vis='party'
    now=time.time()
    with connect(settings) as conn:
        conn.execute('UPDATE thread_notes SET body=?,kind=?,visibility=?,gm_edited=?,updated_at=? WHERE id=?',
          (str(p.get('body',note.get('body') or '')),str(p.get('kind',note.get('kind') or 'note')),vis,1 if admin else int(note.get('gm_edited') or 0),now,int(note_id)))
    return _row(settings,'SELECT * FROM thread_notes WHERE id=?',(int(note_id),)) or {}


def delete_thread_note(settings:Settings,note_id:int,*,invite_id:int|None=None,admin:bool=False)->None:
    note=_row(settings,'SELECT * FROM thread_notes WHERE id=?',(int(note_id),))
    if not note:raise ValueError('Thread note not found')
    thread=_row(settings,'SELECT * FROM campaign_threads WHERE id=?',(int(note['thread_id']),))
    owns=int(note.get('invite_id') or -1)==int(invite_id or -2)
    if not admin and (not owns or not thread or not can_edit_thread(thread,invite_id,False)):
        raise PermissionError('You can only remove your own notes.')
    with connect(settings) as conn:
        conn.execute('DELETE FROM thread_notes WHERE id=?',(int(note_id),))



def save_thread_link(settings:Settings,thread_id:int,p:dict,*,invite_id:int|None=None,admin:bool=False)->dict:
    t=_row(settings,'SELECT * FROM campaign_threads WHERE id=?',(int(thread_id),))
    if not t or not can_edit_thread(t,invite_id,admin):raise PermissionError('You cannot edit this thread.')
    tt=str(p.get('target_type') or 'page');tk=str(p.get('target_key') or '');label=str(p.get('label') or '')
    with connect(settings) as conn:conn.execute('INSERT OR REPLACE INTO thread_links(thread_id,target_type,target_key,label,created_by_invite_id) VALUES(?,?,?,?,?)',(int(thread_id),tt,tk,label,invite_id))
    return {'thread_id':thread_id,'target_type':tt,'target_key':tk,'label':label}

def delete_thread_link(settings:Settings,thread_id:int,target_type:str,target_key:str,*,invite_id:int|None=None,admin:bool=False)->None:
    t=_row(settings,'SELECT * FROM campaign_threads WHERE id=?',(int(thread_id),))
    if not t or not can_edit_thread(t,invite_id,admin):raise PermissionError('You cannot edit this thread.')
    with connect(settings) as conn:
        conn.execute('DELETE FROM thread_links WHERE thread_id=? AND target_type=? AND target_key=?',(int(thread_id),target_type,target_key))



def _journal_rows_with_character(settings:Settings,sql:str,params:tuple=())->list[dict]:
    return _rows(settings,
        "SELECT j.*,i.label AS player_label,c.name AS character_name,c.slug AS character_slug, "
        "s.session_number AS session_number,s.title AS session_title,s.session_date AS session_date "
        "FROM player_journals j LEFT JOIN player_invites i ON i.id=j.invite_id "
        "LEFT JOIN player_characters c ON c.id=j.character_id "
        "LEFT JOIN campaign_sessions s ON s.id=j.session_id " + sql, params)


def list_journals(settings:Settings,invite_id:int,*,admin:bool=False,character_id:int|None=None)->list[dict]:
    where="WHERE j.invite_id=?";params=[int(invite_id)]
    if character_id is not None:
        if int(character_id)==0:
            where+=" AND j.character_id IS NULL"
        else:
            where+=" AND (j.character_id=? OR j.character_id IS NULL)";params.append(int(character_id))
    return _journal_rows_with_character(settings,where+" ORDER BY COALESCE(j.session_id,999999) DESC,j.updated_at DESC",tuple(params))


def list_party_journals(settings:Settings,invite_id:int|None=None,*,admin:bool=False,character_id:int|None=None)->list[dict]:
    if admin:
        return _journal_rows_with_character(settings,"ORDER BY j.updated_at DESC")
    iid=int(invite_id or -1)
    # Party-shared notes from other players stay visible. A player's own
    # character-scoped notes are filtered to the character they entered the
    # session as; unassigned legacy/player-wide notes remain available.
    where="WHERE (j.visibility='party' OR j.invite_id=?)";params=[iid]
    if character_id is not None:
        if int(character_id)==0:
            where+=" AND (j.invite_id!=? OR j.character_id IS NULL)";params.append(iid)
        else:
            where+=" AND (j.invite_id!=? OR j.character_id IS NULL OR j.character_id=?)";params.extend([iid,int(character_id)])
    return _journal_rows_with_character(settings,where+" ORDER BY j.updated_at DESC",tuple(params))


def save_journal(settings:Settings,p:dict,invite_id:int)->dict:
    now=time.time();jid=p.get('id')
    character_id=p.get('character_id')
    if character_id in ('',0,'0'): character_id=None
    if character_id is not None:
        try: character_id=int(character_id)
        except (TypeError,ValueError): raise ValueError('Invalid character.')
        owner=_row(settings,'SELECT id FROM player_characters WHERE id=? AND invite_id=?',(character_id,int(invite_id)))
        if not owner: raise PermissionError('You can only attach notes to your own character.')
    visibility=str(p.get('visibility') or 'private')
    if visibility not in {'private','party'}: visibility='private'
    session_id=p.get('session_id')
    if session_id in ('',0,'0'): session_id=None
    title=str(p.get('title') or 'Session journal')
    body=str(p.get('body') or '')
    with connect(settings) as conn:
        if jid:
            current=conn.execute('SELECT invite_id FROM player_journals WHERE id=?',(int(jid),)).fetchone()
            if not current: raise ValueError('Journal entry not found.')
            if int(current['invite_id'])!=int(invite_id): raise PermissionError('You can only edit your own journal entries.')
            conn.execute('UPDATE player_journals SET character_id=?,session_id=?,title=?,body=?,visibility=?,updated_at=? WHERE id=? AND invite_id=?',(character_id,session_id,title,body,visibility,now,int(jid),int(invite_id)));out=int(jid)
        else:
            out=conn.execute('INSERT INTO player_journals(invite_id,character_id,session_id,title,body,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(int(invite_id),character_id,session_id,title,body,visibility,now,now)).lastrowid
    rows=_journal_rows_with_character(settings,'WHERE j.id=?',(out,))
    return rows[0] if rows else {}


def inbox_items(settings:Settings)->list[dict]:return _rows(settings,'SELECT * FROM gm_inbox ORDER BY status="inbox" DESC,created_at DESC')
def save_inbox(settings:Settings,p:dict)->dict:
    now=time.time();iid=p.get('id');vals=(str(p.get('kind') or 'note'),str(p.get('title') or ''),str(p.get('body') or ''),str(p.get('asset_ref') or ''),str(p.get('status') or 'inbox'),now)
    with connect(settings) as conn:
        if iid:conn.execute('UPDATE gm_inbox SET kind=?,title=?,body=?,asset_ref=?,status=?,updated_at=? WHERE id=?',vals+(int(iid),));out=int(iid)
        else:out=conn.execute('INSERT INTO gm_inbox(kind,title,body,asset_ref,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',vals[:-1]+(now,now)).lastrowid
    return _row(settings,'SELECT * FROM gm_inbox WHERE id=?',(out,)) or {}


def list_submissions(settings:Settings,*,invite_id:int|None=None,admin:bool=False)->list[dict]:
    if admin:return _rows(settings,'SELECT s.*,p.label AS player_label FROM player_submissions s LEFT JOIN player_invites p ON p.id=s.invite_id ORDER BY s.status="pending" DESC,s.created_at DESC')
    return _rows(settings,'SELECT * FROM player_submissions WHERE invite_id=? ORDER BY created_at DESC',(int(invite_id or -1),))
def save_submission(settings:Settings,p:dict,invite_id:int)->dict:
    now=time.time();sid=p.get('id');vals=(int(invite_id),str(p.get('kind') or 'lore'),str(p.get('title') or 'Submission'),str(p.get('body') or ''),str(p.get('target_key') or ''),str(p.get('asset_ref') or ''),now)
    with connect(settings) as conn:
        if sid:conn.execute('UPDATE player_submissions SET kind=?,title=?,body=?,target_key=?,asset_ref=?,updated_at=? WHERE id=? AND invite_id=?',vals[1:]+(int(sid),int(invite_id)));out=int(sid)
        else:out=conn.execute('INSERT INTO player_submissions(invite_id,kind,title,body,target_key,asset_ref,status,created_at,updated_at) VALUES(?,?,?,?,?,? ,"pending",?,?)',vals[:-1]+(now,now)).lastrowid
    return _row(settings,'SELECT * FROM player_submissions WHERE id=?',(out,)) or {}
def review_submission(settings:Settings,sid:int,status:str,gm_note:str='')->dict:
    status=status if status in {'approved','rejected','pending'} else 'pending';now=time.time()
    with connect(settings) as conn:conn.execute('UPDATE player_submissions SET status=?,gm_note=?,updated_at=? WHERE id=?',(status,gm_note,now,int(sid)))
    return _row(settings,'SELECT * FROM player_submissions WHERE id=?',(int(sid),)) or {}


def publishing_state(settings:Settings,slug:str)->str:
    r=_row(settings,'SELECT state FROM publishing_states WHERE page_slug=?',(slug,));return str(r['state']) if r else 'published'
def set_publishing_state(settings:Settings,slug:str,state:str,group:str='')->dict:
    state=state if state in {'draft','ready','published'} else 'published';now=time.time()
    with connect(settings) as conn:conn.execute('INSERT INTO publishing_states(page_slug,state,publish_group,updated_at) VALUES(?,?,?,?) ON CONFLICT(page_slug) DO UPDATE SET state=excluded.state,publish_group=excluded.publish_group,updated_at=excluded.updated_at',(slug,state,group,now))
    return {'page_slug':slug,'state':state,'publish_group':group,'updated_at':now}
def publishing_states(settings:Settings)->list[dict]:return _rows(settings,'SELECT * FROM publishing_states ORDER BY updated_at DESC')


def capture_session_state(settings:Settings,session_id:int|None,phase:str)->dict:
    payload={'captured_at':time.time(),'knowledge':list_knowledge(settings),'reveals':_rows(settings,'SELECT * FROM lore_reveals'),'runtime_states':runtime_states(settings,admin=True),'threads':list_threads(settings,admin=True),'fronts':list_fronts(settings,admin=True),'publishing':publishing_states(settings)}
    now=time.time()
    with connect(settings) as conn:conn.execute('INSERT INTO session_state_snapshots(session_id,phase,state_json,created_at) VALUES(?,?,?,?) ON CONFLICT(session_id,phase) DO UPDATE SET state_json=excluded.state_json,created_at=excluded.created_at',(session_id,phase,json.dumps(payload),now))
    return {'session_id':session_id,'phase':phase,'created_at':now}


def session_state_snapshots(settings:Settings,session_id:int|None=None)->list[dict]:
    rows=_rows(settings,'SELECT id,session_id,phase,created_at FROM session_state_snapshots'+(' WHERE session_id=?' if session_id is not None else '')+' ORDER BY created_at DESC',((int(session_id),) if session_id is not None else ()))
    return rows


def scan_suggestions(settings:Settings,wiki:dict)->list[dict]:
    pages=wiki.get('pages',[]); titles={str(p.get('title') or ''):p.get('slug') for p in pages if p.get('title')}
    now=time.time(); found=[]
    with connect(settings) as conn:
        for p in pages:
            text=str(p.get('plain_text') or '')[:20000]; src=p.get('slug','')
            for title,target in titles.items():
                if target==src or len(title)<5: continue
                if re.search(r'\b'+re.escape(title)+r'\b',text,re.I):
                    label=f'Link “{title}” from this entry'
                    conn.execute('INSERT OR IGNORE INTO lore_suggestions(kind,source_slug,target_key,label,evidence,status,created_at,updated_at) VALUES(?,?,?,?,?,"open",?,?)',('link',src,target,label,title,now,now))
            for m in re.finditer(r'\b(\d{2,4})\s*(?:p\.C\.|PC|AC)\b',text,re.I):
                label=f'Consider adding {m.group(0)} to the Historical Chronicle'
                conn.execute('INSERT OR IGNORE INTO lore_suggestions(kind,source_slug,target_key,label,evidence,status,created_at,updated_at) VALUES(?,?,?,?,?,"open",?,?)',('history',src,m.group(0),label,m.group(0),now,now))
        found=[dict(r) for r in conn.execute('SELECT * FROM lore_suggestions WHERE status="open" ORDER BY updated_at DESC LIMIT 500').fetchall()]
    return found


def update_suggestion(settings:Settings,sid:int,status:str)->dict:
    now=time.time();status=status if status in {'open','accepted','dismissed'} else 'dismissed'
    with connect(settings) as conn:conn.execute('UPDATE lore_suggestions SET status=?,updated_at=? WHERE id=?',(status,now,int(sid)))
    return _row(settings,'SELECT * FROM lore_suggestions WHERE id=?',(int(sid),)) or {}


def list_media_catalog(settings:Settings)->list[dict]:
    rows=_rows(settings,'SELECT * FROM media_catalog ORDER BY kind,title,ref')
    for r in rows:r['tags']=_json(r.pop('tags_json','[]'),[])
    return rows

def save_media_meta(settings:Settings,ref:str,p:dict)->dict:
    now=time.time();tags=p.get('tags') or []
    with connect(settings) as conn:conn.execute('INSERT INTO media_catalog(ref,title,kind,tags_json,focal_x,focal_y,alt_text,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(ref) DO UPDATE SET title=excluded.title,kind=excluded.kind,tags_json=excluded.tags_json,focal_x=excluded.focal_x,focal_y=excluded.focal_y,alt_text=excluded.alt_text,updated_at=excluded.updated_at',(ref,str(p.get('title') or ''),str(p.get('kind') or 'art'),json.dumps(tags),float(p.get('focal_x') or 50),float(p.get('focal_y') or 50),str(p.get('alt_text') or ''),now))
    return next((x for x in list_media_catalog(settings) if x['ref']==ref),{})


def media_usage(settings:Settings,ref:str)->dict:
    ref=str(ref or ''); raw=ref.split(':',1)[1] if ':' in ref else ref
    uses=[]
    if raw:
        for path in settings.project_dir.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in {'.tex','.sty','.cls','.bib','.md','.txt'}:continue
            try:text=path.read_text(encoding='utf-8',errors='replace')
            except Exception:continue
            for n,line in enumerate(text.splitlines(),1):
                if raw in line or ref in line:
                    uses.append({'kind':'source','path':path.relative_to(settings.project_dir).as_posix(),'line':n,'excerpt':line.strip()[:220]})
    db_specs=[('entity_styles','page_slug','crest_ref'),('entity_styles','page_slug','ambient_audio_ref'),('handouts','slug','image_ref'),('timeline_events','title','image_ref')]
    with connect(settings) as conn:
        for table,key,col in db_specs:
            try:
                rows=conn.execute(f'SELECT {key} AS k FROM {table} WHERE {col}=?',(ref,)).fetchall()
                uses.extend({'kind':'metadata','table':table,'key':r['k'],'field':col} for r in rows)
            except Exception:pass
    return {'ref':ref,'count':len(uses),'uses':uses}


def replace_media_reference(settings:Settings,old_ref:str,new_ref:str)->dict:
    old_raw=old_ref.split(':',1)[1] if ':' in old_ref else old_ref
    new_raw=new_ref.split(':',1)[1] if ':' in new_ref else new_ref
    touched=[]
    if old_raw and new_raw:
        for path in settings.project_dir.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in {'.tex','.sty','.cls','.bib','.md','.txt'}:continue
            try:text=path.read_text(encoding='utf-8',errors='replace')
            except Exception:continue
            changed=text.replace(old_ref,new_ref).replace(old_raw,new_raw)
            if changed!=text:
                path.write_text(changed,encoding='utf-8');touched.append(path.relative_to(settings.project_dir).as_posix())
    with connect(settings) as conn:
        for table,col in [('entity_styles','crest_ref'),('entity_styles','ambient_audio_ref'),('handouts','image_ref'),('timeline_events','image_ref')]:
            try:conn.execute(f'UPDATE {table} SET {col}=? WHERE {col}=?',(new_ref,old_ref))
            except Exception:pass
    return {'ok':True,'source_files':touched,'old_ref':old_ref,'new_ref':new_ref}


def create_notification(settings:Settings,p:dict)->dict:
    now=time.time();aud=p.get('audience') or [];expires=p.get('expires_at')
    with connect(settings) as conn:nid=conn.execute('INSERT INTO campaign_notifications(title,body,target_type,target_key,kind,audience_json,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?)',(str(p.get('title') or 'Campaign update'),str(p.get('body') or ''),str(p.get('target_type') or ''),str(p.get('target_key') or ''),str(p.get('kind') or 'notice'),json.dumps(aud),expires,now)).lastrowid
    return _row(settings,'SELECT * FROM campaign_notifications WHERE id=?',(nid,)) or {}
def list_notifications(settings:Settings,invite_id:int|None,*,admin:bool=False,since:float=0)->list[dict]:
    # One LEFT JOIN replaces the old per-notification read-status query.
    iid=int(invite_id) if invite_id is not None else -1
    sql=("SELECT n.*, CASE WHEN nr.read_at IS NULL THEN 0 ELSE 1 END AS read "
         "FROM campaign_notifications n "
         "LEFT JOIN notification_reads nr ON nr.notification_id=n.id AND nr.invite_id=? "
         "WHERE n.created_at>? ORDER BY n.created_at DESC LIMIT 100")
    with connect(settings) as conn:
        rows=[dict(r) for r in conn.execute(sql,(iid,float(since or 0))).fetchall()]
    now=time.time();out=[]
    for r in rows:
        if r.get('expires_at') and float(r['expires_at'])<now:continue
        aud=_json(r.get('audience_json'),[])
        if not admin and aud and iid not in {int(x) for x in aud}:continue
        r['read']=bool(r.get('read'));out.append(r)
    return out
def mark_notification_read(settings:Settings,nid:int,invite_id:int)->None:
    with connect(settings) as conn:conn.execute('INSERT OR REPLACE INTO notification_reads(notification_id,invite_id,read_at) VALUES(?,?,?)',(int(nid),int(invite_id),time.time()))


def character_relationships(settings:Settings,character_id:int,*,owner:bool=False)->list[dict]:
    rows=_rows(settings,'SELECT * FROM character_relationships WHERE character_id=? ORDER BY updated_at DESC',(int(character_id),));return rows if owner else [r for r in rows if r['visibility']=='party']
def save_character_relationship(settings:Settings,character_id:int,p:dict)->dict:
    now=time.time();rid=p.get('id');vals=(int(character_id),str(p.get('target_type') or 'page'),str(p.get('target_key') or ''),str(p.get('relation') or 'knows'),str(p.get('note') or ''),str(p.get('visibility') or 'private'),now)
    with connect(settings) as conn:
        if rid:conn.execute('UPDATE character_relationships SET target_type=?,target_key=?,relation=?,note=?,visibility=?,updated_at=? WHERE id=? AND character_id=?',(vals[1],vals[2],vals[3],vals[4],vals[5],now,int(rid),int(character_id)));out=int(rid)
        else:out=conn.execute('INSERT INTO character_relationships(character_id,target_type,target_key,relation,note,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',vals[:-1]+(now,now)).lastrowid
    return _row(settings,'SELECT * FROM character_relationships WHERE id=?',(out,)) or {}
def character_arcs(settings:Settings,character_id:int,*,owner:bool=False)->list[dict]:
    rows=_rows(settings,'SELECT * FROM character_arcs WHERE character_id=? ORDER BY status="active" DESC,updated_at DESC',(int(character_id),));return rows if owner else [r for r in rows if r['visibility']=='party']
def save_character_arc(settings:Settings,character_id:int,p:dict)->dict:
    now=time.time();aid=p.get('id');vals=(int(character_id),str(p.get('title') or 'Arc'),str(p.get('body') or ''),str(p.get('kind') or 'goal'),str(p.get('status') or 'active'),str(p.get('visibility') or 'private'),p.get('session_id'),now)
    with connect(settings) as conn:
        if aid:conn.execute('UPDATE character_arcs SET title=?,body=?,kind=?,status=?,visibility=?,session_id=?,updated_at=? WHERE id=? AND character_id=?',(vals[1],vals[2],vals[3],vals[4],vals[5],vals[6],now,int(aid),int(character_id)));out=int(aid)
        else:out=conn.execute('INSERT INTO character_arcs(character_id,title,body,kind,status,visibility,session_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',vals[:-1]+(now,now)).lastrowid
    return _row(settings,'SELECT * FROM character_arcs WHERE id=?',(out,)) or {}


def entity_provenance(settings:Settings,page_slug:str)->list[dict]:
    # One UNION replaces the old N+1 pattern where every matching session update
    # caused another SQLite connection and session lookup during article renders.
    sql='''
        SELECT DISTINCT s.id,s.session_number,s.title,s.session_date,s.status
        FROM campaign_sessions s JOIN session_lore l ON l.session_id=s.id
        WHERE l.page_slug=?
        UNION
        SELECT DISTINCT s.id,s.session_number,s.title,s.session_date,s.status
        FROM campaign_sessions s JOIN session_updates u ON u.session_id=s.id
        WHERE u.target_key=? AND u.session_id IS NOT NULL
        ORDER BY COALESCE(session_number,999999),session_date,id
    '''
    return _rows(settings,sql,(page_slug,page_slug))


def continuity_report(settings:Settings,wiki:dict)->dict:
    issues=[];pages={p.get('slug'):p for p in wiki.get('pages',[])};title_groups={}
    for p in wiki.get('pages',[]):title_groups.setdefault(str(p.get('title') or '').casefold(),[]).append(p)
    for group in title_groups.values():
        if len(group)>1 and group[0].get('title'):
            issues.append({'severity':'warning','title':group[0]['title'],'message':f'Duplicate Codex title appears {len(group)} times; aliases/search may become ambiguous.','href':'/admin?search='+group[0]['title']})
    for st in runtime_states(settings,admin=True):
        p=pages.get(st['page_slug']);text=(p or {}).get('plain_text','').lower()
        if st['status'].lower()=='dead' and re.search(r'\bstatus\s*:\s*alive\b',text):issues.append({'severity':'warning','title':(p or {}).get('title',st['page_slug']),'message':'Runtime state says Dead, but the profile text appears to say Alive.','href':'/wiki/'+st['page_slug']})
        if st.get('location_slug') and st['location_slug'] not in pages:issues.append({'severity':'warning','title':st['page_slug'],'message':f"Current location points to missing lore: {st['location_slug']}",'href':'/admin/living#state'})
    for t in list_threads(settings,admin=True):
        for l in t['links']:
            if l['target_type']=='page' and l['target_key'] not in pages:issues.append({'severity':'info','title':t['title'],'message':f"Thread links to missing lore: {l['target_key']}",'href':'/campaign#threads'})
    for r in relationship_history(settings,admin=True):
        for side in ('source_slug','target_slug'):
            if r.get(side) and r[side] not in pages:issues.append({'severity':'warning','title':r.get('label') or r.get('relation') or 'Relationship','message':f"Historical relationship points to missing lore: {r[side]}",'href':'/admin/living#relationships'})
        if r.get('start_sort') is not None and r.get('end_sort') is not None and float(r['end_sort'])<float(r['start_sort']):issues.append({'severity':'warning','title':r.get('label') or r.get('relation') or 'Relationship','message':'Relationship ends before it starts.','href':'/admin/living#relationships'})
    for chart in hierarchies(settings,admin=True):
        for edge in chart.get('nodes',[]):
            for slug in (edge.get('parent_slug'),edge.get('child_slug')):
                if slug and slug not in pages:issues.append({'severity':'warning','title':chart.get('title') or 'Hierarchy','message':f'Hierarchy points to missing lore: {slug}','href':'/admin/living#hierarchies'})
    with connect(settings) as conn:
        try:
            for a in conn.execute('SELECT alias,page_slug FROM page_aliases').fetchall():
                if a['page_slug'] not in pages:issues.append({'severity':'info','title':a['alias'],'message':f"Alias targets missing lore: {a['page_slug']}",'href':'/admin/campaign'})
        except Exception:pass
        try:
            for k in conn.execute("SELECT invite_id,target_type,target_key,state FROM player_knowledge WHERE state!='unknown'").fetchall():
                if k['target_type']=='page' and k['target_key'] not in pages:issues.append({'severity':'info','title':'Player knowledge','message':f"Knowledge state targets missing lore: {k['target_key']}",'href':'/admin/living#knowledge'})
        except Exception:pass
    for p in pages.values():
        vals=[]
        for m in re.finditer(r'\bAge\s*:\s*(\d{1,4}).{0,30}?(?:as of\s*)?(\d{2,4})\s*(?:p\.?C\.?|PC|AC)',str(p.get('plain_text') or ''),re.I):vals.append((int(m.group(1)),int(m.group(2))))
        if len({year-age for age,year in vals})>1:issues.append({'severity':'warning','title':p.get('title') or p.get('slug'),'message':'Multiple dated age statements imply different birth years.','href':'/wiki/'+p.get('slug','')})
    return {'issues':issues,'counts':{'runtime_states':len(runtime_states(settings,admin=True)),'threads':len(list_threads(settings,admin=True)),'fronts':len(list_fronts(settings,admin=True)),'relationships':len(relationship_history(settings,admin=True))}}


def export_foundry_journal(title:str,html:str,img:str='')->dict:
    return {'name':title,'type':'JournalEntry','img':img or 'icons/svg/book.svg','pages':[{'name':title,'type':'text','text':{'content':html,'format':1},'ownership':{'default':0}}], 'flags':{'loreforge':{'exportedAt':time.time()}}}


def create_portable_archive(settings:Settings,out:Path)->Path:
    out.parent.mkdir(parents=True,exist_ok=True)
    # WAL keeps recent commits in a sidecar file. Copying only the main .db file
    # can therefore produce a valid-looking but stale/empty backup. SQLite's
    # backup API checkpoints a consistent snapshot without blocking readers.
    db_copy:Path|None=None
    if settings.db_path.exists():
        fd,tmp_name=tempfile.mkstemp(prefix='seeker-portable-',suffix='.db');os.close(fd);db_copy=Path(tmp_name)
        src=sqlite3.connect(settings.db_path);dst=sqlite3.connect(db_copy)
        try:src.backup(dst)
        finally:dst.close();src.close()
    try:
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as z:
            for base,prefix in ((settings.project_dir,'project'),(settings.uploads_dir,'uploads')):
                if base.exists():
                    for p in base.rglob('*'):
                        if p.is_file():z.write(p,f'{prefix}/{p.relative_to(base).as_posix()}')
            if db_copy is not None:z.write(db_copy,'loreforge.db')
            z.writestr('manifest.json',json.dumps({'format':'loreforge-portable-v1','created_at':time.time()},indent=2))
    finally:
        if db_copy is not None:db_copy.unlink(missing_ok=True)
    return out


def validate_portable_archive_file(path:Path)->dict:
    """Exercise a portable backup without mutating the live campaign.

    The check validates path safety, the manifest, presence of canonical source,
    and a real SQLite integrity check on the archived Seeker database.
    """
    import sqlite3, tempfile
    path=Path(path)
    if not path.exists() or not zipfile.is_zipfile(path):
        raise ValueError('This is not a readable Seeker ZIP archive.')
    with zipfile.ZipFile(path,'r') as z:
        infos=z.infolist();names=[i.filename for i in infos]
        for name in names:
            pp=Path(name)
            if pp.is_absolute() or '..' in pp.parts:
                raise ValueError(f'Unsafe archive path: {name}')
        required={'manifest.json','loreforge.db'}
        missing=required-set(names)
        if missing: raise ValueError('Portable archive is missing: '+', '.join(sorted(missing)))
        try: manifest=json.loads(z.read('manifest.json').decode('utf-8'))
        except Exception as exc: raise ValueError('Portable archive manifest is unreadable.') from exc
        if manifest.get('format')!='loreforge-portable-v1':
            raise ValueError('Unsupported Seeker portable archive format.')
        tex=[n for n in names if n.startswith('project/') and n.lower().endswith('.tex')]
        if not tex: raise ValueError('Portable archive contains no LaTeX source files.')
        with tempfile.TemporaryDirectory(prefix='loreforge-restore-test-') as td:
            db=Path(td)/'loreforge.db';db.write_bytes(z.read('loreforge.db'))
            try:
                with sqlite3.connect(db) as conn:
                    integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
                    table_count=conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            except Exception as exc: raise ValueError('Archived Seeker database cannot be opened.') from exc
            if str(integrity).lower()!='ok': raise ValueError('Archived database failed SQLite integrity_check: '+str(integrity))
        uploads=[n for n in names if n.startswith('uploads/') and not n.endswith('/')]
        project_files=[n for n in names if n.startswith('project/') and not n.endswith('/')]
        return {'ok':True,'format':manifest.get('format'),'created_at':manifest.get('created_at'),'project_files':len(project_files),'tex_files':len(tex),'uploads':len(uploads),'database_tables':int(table_count),'archive_bytes':path.stat().st_size}
