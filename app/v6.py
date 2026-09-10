from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from .config import Settings
from .storage import connect, get_setting, set_setting, list_revisions, restore_revision
from .living import create_portable_archive, validate_portable_archive_file

V6_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS campaign_integrations (
    campaign_id INTEGER PRIMARY KEY,
    discord_webhook TEXT NOT NULL DEFAULT '',
    discord_enabled INTEGER NOT NULL DEFAULT 0,
    discord_mention TEXT NOT NULL DEFAULT '',
    discord_auto_session_confirmed INTEGER NOT NULL DEFAULT 0,
    foundry_bridge_token TEXT NOT NULL DEFAULT '',
    calendar_token TEXT NOT NULL DEFAULT '',
    display_token TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS foundry_bridge_state (
    campaign_id INTEGER PRIMARY KEY,
    scene_name TEXT NOT NULL DEFAULT '',
    scene_id TEXT NOT NULL DEFAULT '',
    world_name TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    received_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS foundry_actor_snapshots (
    campaign_id INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    actor_uuid TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    img TEXT NOT NULL DEFAULT '',
    actor_url TEXT NOT NULL DEFAULT '',
    actor_type TEXT NOT NULL DEFAULT '',
    owners_json TEXT NOT NULL DEFAULT '[]',
    sheet_json TEXT NOT NULL DEFAULT '{}',
    received_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,actor_id),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_foundry_actor_campaign_name ON foundry_actor_snapshots(campaign_id,name,actor_id);
CREATE TABLE IF NOT EXISTS foundry_character_links (
    character_id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    linked_at REAL NOT NULL,
    FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE CASCADE,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_foundry_links_campaign_actor ON foundry_character_links(campaign_id,actor_id);
CREATE TABLE IF NOT EXISTS foundry_command_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    actor_id TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'actor',
    command_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    requested_by TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    dispatched_at REAL,
    completed_at REAL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at REAL,
    started_at REAL,
    last_error TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_foundry_command_campaign_status ON foundry_command_queue(campaign_id,status,created_at,id);
CREATE TABLE IF NOT EXISTS foundry_prepared_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'item',
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT 'world',
    summary TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_foundry_prepared_campaign_kind ON foundry_prepared_content(campaign_id,kind,updated_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS lore_page_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_slug TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    chapter TEXT NOT NULL DEFAULT '',
    source_file TEXT NOT NULL DEFAULT '',
    source_line INTEGER,
    content_hash TEXT NOT NULL,
    html TEXT NOT NULL DEFAULT '',
    plain_text TEXT NOT NULL DEFAULT '',
    presentation_json TEXT NOT NULL DEFAULT '{}',
    generated_at REAL NOT NULL,
    UNIQUE(page_slug,content_hash)
);
CREATE INDEX IF NOT EXISTS idx_v6_lore_revisions_slug ON lore_page_revisions(page_slug,generated_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS campaign_map_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    map_id INTEGER NOT NULL,
    invite_id INTEGER,
    author_label TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    x REAL NOT NULL,
    y REAL NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'party',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v6_annotations_map ON campaign_map_annotations(campaign_id,map_id,updated_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS campaign_travel_legs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    map_id INTEGER NOT NULL,
    session_id INTEGER,
    from_marker_id INTEGER,
    to_marker_id INTEGER,
    from_label TEXT NOT NULL DEFAULT '',
    to_label TEXT NOT NULL DEFAULT '',
    route_json TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    traveled_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL,
    FOREIGN KEY(from_marker_id) REFERENCES markers(id) ON DELETE SET NULL,
    FOREIGN KEY(to_marker_id) REFERENCES markers(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v6_travel_map ON campaign_travel_legs(campaign_id,map_id,traveled_at,id);
CREATE TABLE IF NOT EXISTS session_media_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'image',
    source_url TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT '',
    target_key TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v6_media_session ON session_media_items(campaign_id,session_id,sort_order,id);
CREATE TABLE IF NOT EXISTS campaign_display_state (
    campaign_id INTEGER PRIMARY KEY,
    media_item_id INTEGER,
    mode TEXT NOT NULL DEFAULT 'idle',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(media_item_id) REFERENCES session_media_items(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS campaign_convergences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_campaign_id INTEGER NOT NULL,
    source_campaign_ids_json TEXT NOT NULL DEFAULT '[]',
    options_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY(target_campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS v6_backup_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'manual',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v6_backups_created ON v6_backup_catalog(created_at DESC,id DESC);
'''

_LORE_SYNC_LOCK = threading.Lock()
_LAST_LORE_GENERATION: float | None = None
_BACKUP_LOCK = threading.Lock()


def init_v6_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(V6_SCHEMA)
        cols={str(r[1]) for r in conn.execute("PRAGMA table_info(campaign_integrations)").fetchall()}
        if cols and 'display_token' not in cols:
            conn.execute("ALTER TABLE campaign_integrations ADD COLUMN display_token TEXT NOT NULL DEFAULT ''")
        if cols and 'discord_mention' not in cols:
            conn.execute("ALTER TABLE campaign_integrations ADD COLUMN discord_mention TEXT NOT NULL DEFAULT ''")
        if cols and 'discord_auto_session_confirmed' not in cols:
            conn.execute("ALTER TABLE campaign_integrations ADD COLUMN discord_auto_session_confirmed INTEGER NOT NULL DEFAULT 0")
        command_cols={str(r[1]) for r in conn.execute("PRAGMA table_info(foundry_command_queue)").fetchall()}
        if command_cols and 'attempt_count' not in command_cols:
            conn.execute("ALTER TABLE foundry_command_queue ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0")
        if command_cols and 'last_attempt_at' not in command_cols:
            conn.execute("ALTER TABLE foundry_command_queue ADD COLUMN last_attempt_at REAL")
        if command_cols and 'started_at' not in command_cols:
            conn.execute("ALTER TABLE foundry_command_queue ADD COLUMN started_at REAL")
        if command_cols and 'last_error' not in command_cols:
            conn.execute("ALTER TABLE foundry_command_queue ADD COLUMN last_error TEXT NOT NULL DEFAULT ''")


def _json(raw: Any, default: Any):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or '')
    except Exception:
        return default


_ABILITY_LABELS={
    'PF2E.ABILITYSTR':'STR','PF2E.ABILITYDEX':'DEX','PF2E.ABILITYCON':'CON',
    'PF2E.ABILITYINT':'INT','PF2E.ABILITYWIS':'WIS','PF2E.ABILITYCHA':'CHA',
}
_SAVE_LABELS={'fortitude':'Fortitude','reflex':'Reflex','will':'Will'}


def _pretty_label(label: Any, slug: Any = '', kind: str = '') -> str:
    raw=str(label or slug or '').strip()
    if not raw:
        return ''
    if raw in _ABILITY_LABELS:
        return _ABILITY_LABELS[raw]
    lower=raw.lower()
    if kind=='saves':
        return _SAVE_LABELS.get(lower, raw.title())
    if lower in _SAVE_LABELS:
        return _SAVE_LABELS[lower]
    if raw.startswith('PF2E.'):
        raw=raw.split('.')[-1]
    return raw.replace('_',' ').replace('-', ' ').strip() if kind=='abilities' else raw.replace('_',' ').replace('-', ' ').strip().title()


def _normalize_foundry_rows(rows: Any, kind: str) -> list[dict]:
    out=[]
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        item=dict(row)
        item['label']=_pretty_label(item.get('label'), item.get('slug'), kind)
        out.append(item)
    return out


def normalize_foundry_sheet(sheet: Any) -> dict:
    data=_json(sheet, {}) if not isinstance(sheet, dict) else dict(sheet)
    for kind in ('abilities','saves','skills'):
        data[kind]=_normalize_foundry_rows(data.get(kind), kind)
    return data


def _foundry_module_version() -> str:
    return '1.7.0'


def _validate_foundry_token(settings: Settings, campaign_id: int, token: str) -> None:
    cfg=integration_config(settings, campaign_id, include_secret=True)
    if not secrets.compare_digest(str(cfg.get('foundry_bridge_token') or ''), str(token or '')):
        raise PermissionError('Invalid Foundry bridge token.')


def _command_row(raw: dict) -> dict:
    row=dict(raw)
    row['payload']=_json(row.pop('payload_json','{}'),{})
    row['result']=_json(row.pop('result_json','{}'),{})
    return row


def list_foundry_prepared_content(settings: Settings, campaign_id: int) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM foundry_prepared_content WHERE campaign_id=? ORDER BY updated_at DESC,id DESC',(int(campaign_id),))
    for row in rows:
        row['payload']=_json(row.pop('payload_json','{}'),{})
    return rows


def save_foundry_prepared_content(settings: Settings, campaign_id: int, payload: dict) -> dict:
    kind=str(payload.get('kind') or 'item').strip().lower()
    if kind not in {'item','feat','monster','npc','homebrew'}:
        raise ValueError('Unsupported prep content kind.')
    target_type=str(payload.get('target_type') or 'world').strip().lower()
    if target_type not in {'world','actor'}:
        raise ValueError('target_type must be world or actor.')
    title=str(payload.get('title') or '').strip()[:180]
    if not title:
        raise ValueError('A title is required.')
    content_payload=payload.get('payload') if isinstance(payload.get('payload'),dict) else {}
    row=(
        int(payload.get('id') or 0), int(campaign_id), kind, title,
        str(payload.get('subtitle') or '')[:180], target_type,
        str(payload.get('summary') or '')[:8000], str(payload.get('tags') or '')[:400],
        json.dumps(content_payload,ensure_ascii=False), time.time(),
    )
    with connect(settings) as conn:
        if row[0]:
            exists=conn.execute('SELECT id FROM foundry_prepared_content WHERE id=? AND campaign_id=?',(row[0],row[1])).fetchone()
            if not exists:
                raise ValueError('Prepared content entry not found.')
            conn.execute('''UPDATE foundry_prepared_content SET kind=?,title=?,subtitle=?,target_type=?,summary=?,tags=?,payload_json=?,updated_at=? WHERE id=? AND campaign_id=?''',
                         (row[2],row[3],row[4],row[5],row[6],row[7],row[8],row[9],row[0],row[1]))
            out=row[0]
        else:
            cur=conn.execute('''INSERT INTO foundry_prepared_content(campaign_id,kind,title,subtitle,target_type,summary,tags,payload_json,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?)''',(row[1],row[2],row[3],row[4],row[5],row[6],row[7],row[8],row[9],row[9]))
            out=int(cur.lastrowid or 0)
    return next((x for x in list_foundry_prepared_content(settings,campaign_id) if int(x['id'])==out),{})


def delete_foundry_prepared_content(settings: Settings, campaign_id: int, item_id: int) -> None:
    with connect(settings) as conn:
        conn.execute('DELETE FROM foundry_prepared_content WHERE campaign_id=? AND id=?',(int(campaign_id),int(item_id)))


def queue_foundry_command(settings: Settings, campaign_id: int, command_type: str, payload: dict, *, actor_id: str = '', scope: str = 'actor', requested_by: str = '') -> dict:
    ctype=str(command_type or '').strip().lower()
    if ctype not in {'adjust_resource','adjust_item_quantity','grant_prepared_content','push_prepared_content','sync_entity_document','push_content_bundle'}:
        raise ValueError('Unsupported Foundry action.')
    sc=str(scope or 'actor').strip().lower()
    if sc not in {'actor','world'}:
        raise ValueError('Unsupported Foundry action scope.')
    now=time.time()
    with connect(settings) as conn:
        cur=conn.execute('INSERT INTO foundry_command_queue(campaign_id,actor_id,scope,command_type,payload_json,requested_by,status,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (int(campaign_id),str(actor_id or '')[:300],sc,ctype,json.dumps(payload or {},ensure_ascii=False),str(requested_by or '')[:160],'queued','{}',now,now))
        out=int(cur.lastrowid or 0)
    return get_foundry_command(settings,campaign_id,out) or {}


def _decorate_command(row: dict) -> dict:
    item=_command_row(row)
    status=str(item.get('status') or 'queued')
    labels={'queued':'Waiting for Foundry','dispatched':'Delivered to bridge','executing':'Applying in Foundry','done':'Applied','failed':'Failed','cancelled':'Cancelled'}
    item['delivery_label']=labels.get(status,status.replace('_',' ').title())
    payload=item.get('payload') if isinstance(item.get('payload'),dict) else {}
    result=item.get('result') if isinstance(item.get('result'),dict) else {}
    item['target_label']=str(
        payload.get('character_name') or payload.get('actor_name') or payload.get('title') or
        payload.get('folder_name') or result.get('actor_name') or item.get('actor_id') or 'Foundry world'
    )[:180]
    item['age_seconds']=max(0,int(time.time()-float(item.get('created_at') or time.time())))
    item['last_activity_at']=float(item.get('completed_at') or item.get('started_at') or item.get('last_attempt_at') or item.get('updated_at') or item.get('created_at') or 0)
    item['progress_step']={'queued':0,'dispatched':1,'executing':2,'done':3,'failed':3,'cancelled':3}.get(status,0)
    # Never offer a second copy of an action while the bridge may still be
    # executing it. Stale in-flight commands are retried automatically; manual
    # retry is reserved for an explicit terminal failure.
    item['can_retry']=status == 'failed'
    item['terminal']=status in {'done','failed','cancelled'}
    return item


def get_foundry_command(settings: Settings, campaign_id: int, command_id: int) -> dict | None:
    row=_row(settings,'SELECT * FROM foundry_command_queue WHERE campaign_id=? AND id=?',(int(campaign_id),int(command_id)))
    return _decorate_command(row) if row else None


def claim_foundry_commands(settings: Settings, campaign_id: int, token: str, limit: int = 25) -> list[dict]:
    _validate_foundry_token(settings,campaign_id,token)
    cid=int(campaign_id); now=time.time(); dispatched_stale=now-30; executing_stale=now-180
    with connect(settings) as conn:
        conn.execute('BEGIN IMMEDIATE')
        stuck=[dict(r) for r in conn.execute("SELECT id FROM foundry_command_queue WHERE campaign_id=? AND attempt_count>=5 AND ((status='dispatched' AND COALESCE(last_attempt_at,dispatched_at,0)<?) OR (status='executing' AND COALESCE(started_at,last_attempt_at,0)<?))",(cid,dispatched_stale,executing_stale)).fetchall()]
        for r in stuck:
            msg='Foundry did not acknowledge this action after several delivery attempts. The action was kept and can be retried.'
            conn.execute("UPDATE foundry_command_queue SET status='failed',last_error=?,result_json=?,updated_at=?,completed_at=? WHERE id=? AND campaign_id=?",(msg,json.dumps({'message':msg}),now,now,int(r['id']),cid))
        rows=[dict(r) for r in conn.execute("SELECT * FROM foundry_command_queue WHERE campaign_id=? AND attempt_count<5 AND (status='queued' OR (status='dispatched' AND COALESCE(last_attempt_at,dispatched_at,0)<?) OR (status='executing' AND COALESCE(started_at,last_attempt_at,0)<?)) ORDER BY created_at,id LIMIT ?",(cid,dispatched_stale,executing_stale,int(limit))).fetchall()]
        if rows:
            ids=[int(r['id']) for r in rows];marks=','.join('?' for _ in ids)
            conn.execute(f"UPDATE foundry_command_queue SET status='dispatched',attempt_count=COALESCE(attempt_count,0)+1,updated_at=?,dispatched_at=?,last_attempt_at=?,started_at=NULL,last_error='' WHERE id IN ({marks})",(now,now,now,*ids))
    fresh=[]
    for row in rows:
        row['status']='dispatched'; row['updated_at']=now; row['dispatched_at']=now; row['last_attempt_at']=now
        row['attempt_count']=int(row.get('attempt_count') or 0)+1; row['started_at']=None;row['last_error']=''
        fresh.append(_decorate_command(row))
    return fresh


def start_foundry_commands(settings: Settings, campaign_id: int, token: str, command_ids: list[int]) -> dict:
    _validate_foundry_token(settings,campaign_id,token)
    ids=[]
    for raw in command_ids or []:
        try: ids.append(int(raw))
        except Exception: continue
    ids=list(dict.fromkeys(x for x in ids if x>0))[:50]
    if not ids:return {'ok':True,'started':0}
    now=time.time();marks=','.join('?' for _ in ids)
    with connect(settings) as conn:
        cur=conn.execute(f"UPDATE foundry_command_queue SET status='executing',started_at=?,updated_at=? WHERE campaign_id=? AND id IN ({marks}) AND status='dispatched'",(now,now,int(campaign_id),*ids))
    return {'ok':True,'started':int(cur.rowcount or 0)}


def _project_foundry_command_result(conn: sqlite3.Connection, campaign_id: int, command: dict, result_obj: dict, now: float) -> None:
    """Immediately reconcile confirmed small writes into Seeker's actor snapshot.

    The bridge ACK historically arrived slightly before the follow-up actor heartbeat.
    A browser that refreshed in that gap could therefore show the old HP/quantity even
    though Foundry had already applied the change. For commands whose authoritative
    result contains the final value, update only that field in the cached projection.
    The next full Foundry heartbeat still replaces the complete snapshot.
    """
    ctype=str(command.get('command_type') or '')
    if ctype not in {'adjust_resource','adjust_item_quantity'}:
        return
    actor_id=str(command.get('actor_id') or '')
    if not actor_id:
        return
    row=conn.execute('SELECT sheet_json FROM foundry_actor_snapshots WHERE campaign_id=? AND actor_id=?',(int(campaign_id),actor_id)).fetchone()
    if not row:
        return
    sheet=_json(row['sheet_json'],{})
    if not isinstance(sheet,dict):
        return
    payload=_json(command.get('payload_json'),{})
    after=result_obj.get('after')
    try:
        after=int(after)
    except (TypeError,ValueError):
        return
    if ctype=='adjust_resource':
        resource=str(payload.get('resource') or '').lower()
        vitals=sheet.setdefault('vitals',{})
        if resource=='hp': vitals.setdefault('hp',{})['value']=after
        elif resource=='temp_hp': vitals.setdefault('hp',{})['temp']=after
        elif resource=='hero_points': vitals.setdefault('hero_points',{})['value']=after
        elif resource=='focus': vitals.setdefault('focus',{})['value']=after
        else: return
    else:
        item_id=str(payload.get('item_id') or '')
        if not item_id:return
        found=False
        for item in sheet.get('inventory') or []:
            if isinstance(item,dict) and str(item.get('id') or '')==item_id:
                item['quantity']=after;found=True;break
        if not found:return
    conn.execute('UPDATE foundry_actor_snapshots SET sheet_json=?,received_at=? WHERE campaign_id=? AND actor_id=?',(json.dumps(sheet,ensure_ascii=False),now,int(campaign_id),actor_id))


def complete_foundry_commands(settings: Settings, campaign_id: int, token: str, results: list[dict]) -> dict:
    _validate_foundry_token(settings,campaign_id,token)
    cid=int(campaign_id); now=time.time(); done=failed=0
    with connect(settings) as conn:
        for item in results or []:
            try: cmd_id=int(item.get('id') or 0)
            except Exception: continue
            command=conn.execute('SELECT * FROM foundry_command_queue WHERE campaign_id=? AND id=?',(cid,cmd_id)).fetchone()
            if not command:continue
            command=dict(command)
            status='done' if str(item.get('status') or 'done').lower() in {'ok','done','skipped'} else 'failed'
            result_obj=item.get('result') if isinstance(item.get('result'),dict) else {'message':str(item.get('result') or '')}
            result=json.dumps(result_obj,ensure_ascii=False)
            last_error='' if status=='done' else str(result_obj.get('message') or 'Foundry rejected this action.')[:2000]
            cur=conn.execute('UPDATE foundry_command_queue SET status=?,result_json=?,last_error=?,updated_at=?,completed_at=? WHERE id=? AND campaign_id=?',(status,result,last_error,now,now,cmd_id,cid))
            if cur.rowcount:
                if status=='done':
                    _project_foundry_command_result(conn,cid,command,result_obj,now)
                    done += 1
                else:
                    failed += 1
    return {'ok':True,'completed':done,'failed':failed}


def retry_foundry_command(settings: Settings, campaign_id: int, command_id: int) -> dict:
    cid=int(campaign_id);cmd=int(command_id);now=time.time()
    with connect(settings) as conn:
        row=conn.execute('SELECT * FROM foundry_command_queue WHERE campaign_id=? AND id=?',(cid,cmd)).fetchone()
        if not row:raise ValueError('Foundry action not found.')
        if str(row['status'])=='done':raise ValueError('This Foundry action has already been applied.')
        conn.execute("UPDATE foundry_command_queue SET status='queued',result_json='{}',last_error='',attempt_count=0,updated_at=?,dispatched_at=NULL,last_attempt_at=NULL,started_at=NULL,completed_at=NULL WHERE campaign_id=? AND id=?",(now,cid,cmd))
    return get_foundry_command(settings,cid,cmd) or {}


def recent_foundry_commands(settings: Settings, campaign_id: int, limit: int = 24) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM foundry_command_queue WHERE campaign_id=? ORDER BY created_at DESC,id DESC LIMIT ?',(int(campaign_id),int(limit)))
    return [_decorate_command(r) for r in rows]


def _row(settings: Settings, sql: str, params: tuple = ()) -> dict | None:
    try:
        with connect(settings) as conn:
            row = conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError as exc:
        # Test fixtures and imported legacy databases can swap Settings after
        # module import. Lazily install only the additive V6 schema, then retry.
        if "no such table" not in str(exc).lower():
            raise
        init_v6_db(settings)
        with connect(settings) as conn:
            row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _rows(settings: Settings, sql: str, params: tuple = ()) -> list[dict]:
    try:
        with connect(settings) as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        init_v6_db(settings)
        with connect(settings) as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]


def integration_config(settings: Settings, campaign_id: int, *, include_secret: bool = False) -> dict:
    cid = int(campaign_id)
    now = time.time()
    with connect(settings) as conn:
        row = conn.execute('SELECT * FROM campaign_integrations WHERE campaign_id=?', (cid,)).fetchone()
        if not row:
            foundry = secrets.token_urlsafe(24)
            calendar = secrets.token_urlsafe(24)
            conn.execute('''INSERT INTO campaign_integrations(
                campaign_id,foundry_bridge_token,calendar_token,display_token,updated_at
            ) VALUES(?,?,?,?,?)''', (cid, foundry, calendar, secrets.token_urlsafe(24), now))
            row = conn.execute('SELECT * FROM campaign_integrations WHERE campaign_id=?', (cid,)).fetchone()
    data = dict(row)
    dirty=False
    if not data.get('foundry_bridge_token'):
        data['foundry_bridge_token']=secrets.token_urlsafe(24);dirty=True
    if not data.get('calendar_token'):
        data['calendar_token']=secrets.token_urlsafe(24);dirty=True
    if not data.get('display_token'):
        data['display_token']=secrets.token_urlsafe(24);dirty=True
    if dirty:
        with connect(settings) as conn:
            conn.execute('UPDATE campaign_integrations SET foundry_bridge_token=?,calendar_token=?,display_token=?,updated_at=? WHERE campaign_id=?',(data['foundry_bridge_token'],data['calendar_token'],data['display_token'],time.time(),cid))
    data['discord_configured'] = bool(data.get('discord_webhook'))
    data['discord_auto_session_confirmed'] = bool(data.get('discord_auto_session_confirmed'))
    if not include_secret:
        data['discord_webhook'] = ''
        data['foundry_bridge_token'] = ''
        data['calendar_token'] = ''
        data['display_token'] = ''
    return data


def save_integration_config(settings: Settings, campaign_id: int, payload: dict) -> dict:
    cid = int(campaign_id)
    current = integration_config(settings, cid, include_secret=True)
    webhook = str(payload.get('discord_webhook', current.get('discord_webhook') or '')).strip()[:3000]
    enabled = 1 if payload.get('discord_enabled', current.get('discord_enabled')) else 0
    mention = _normalize_discord_mention(payload.get('discord_mention', current.get('discord_mention') or ''))[:250]
    if mention.startswith('@') and mention.lower() not in {'@everyone','@here'}:
        raise ValueError('Discord webhooks cannot resolve a role name such as @Players. Paste the role ID (or <@&ROLE_ID>) instead.')
    if mention.startswith('<@&') and not re.fullmatch(r'<@&\d{2,24}>',mention):
        raise ValueError('That Discord role mention is malformed. Paste the numeric role ID from Discord.')
    auto_session = 1 if payload.get('discord_auto_session_confirmed', current.get('discord_auto_session_confirmed')) else 0
    foundry = str(current.get('foundry_bridge_token') or secrets.token_urlsafe(24))
    calendar = str(current.get('calendar_token') or secrets.token_urlsafe(24))
    display = str(current.get('display_token') or secrets.token_urlsafe(24))
    if payload.get('rotate_foundry_token'):
        foundry = secrets.token_urlsafe(24)
    if payload.get('rotate_calendar_token'):
        calendar = secrets.token_urlsafe(24)
    if payload.get('rotate_display_token'):
        display = secrets.token_urlsafe(24)
    with connect(settings) as conn:
        conn.execute('''INSERT INTO campaign_integrations(
            campaign_id,discord_webhook,discord_enabled,discord_mention,discord_auto_session_confirmed,
            foundry_bridge_token,calendar_token,display_token,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id) DO UPDATE SET
            discord_webhook=excluded.discord_webhook,discord_enabled=excluded.discord_enabled,
            discord_mention=excluded.discord_mention,discord_auto_session_confirmed=excluded.discord_auto_session_confirmed,
            foundry_bridge_token=excluded.foundry_bridge_token,calendar_token=excluded.calendar_token,
            display_token=excluded.display_token,updated_at=excluded.updated_at''',
            (cid, webhook, enabled, mention, auto_session, foundry, calendar, display, time.time()))
    return integration_config(settings, cid, include_secret=True)


def _normalize_discord_mention(value: Any) -> str:
    raw=str(value or '').strip()
    if not raw:
        return ''
    lowered=raw.lower().replace(' ', '')
    if lowered in {'everyone','@everyone'}:
        return '@everyone'
    if lowered in {'here','@here'}:
        return '@here'
    # Raw Discord role IDs are unambiguous and convenient to paste. Plain role
    # names cannot be resolved by an incoming webhook because the webhook has no
    # guild role-directory API.
    if re.fullmatch(r'\d{2,24}', raw):
        return f'<@&{raw}>'
    return raw


def _discord_allowed_mentions(content: str) -> dict:
    """Build a narrow Discord allowed_mentions payload from explicit markup.

    Avoid the broad ``parse: ['roles','users']`` mode: Seeker should only ping
    IDs the GM actually typed. @everyone/@here is enabled only when it is
    literally present in the outgoing message.
    """
    text=str(content or '')
    parse=[]
    if re.search(r'(?<!\w)@(everyone|here)\b',text,re.I):
        parse.append('everyone')
    roles=list(dict.fromkeys(re.findall(r'<@&(\d{2,24})>',text)))[:100]
    users=list(dict.fromkeys(re.findall(r'<@!?(\d{2,24})>',text)))[:100]
    out={'parse':parse}
    if roles:
        out['roles']=roles
    if users:
        out['users']=users
    return out


def discord_post(settings: Settings, campaign_id: int, content: str, *, username: str = 'Seeker') -> dict:
    cfg = integration_config(settings, campaign_id, include_secret=True)
    if not cfg.get('discord_enabled') or not cfg.get('discord_webhook'):
        raise ValueError('Discord webhook is not enabled for this campaign.')
    message=str(content or '')[:1900]
    allowed=_discord_allowed_mentions(message)
    body = json.dumps({
        'content': message,
        'username': username[:80],
        'allowed_mentions': allowed,
    }).encode('utf-8')
    # wait=true returns the actual Discord Message object. That lets Seeker tell
    # the difference between “message posted” and “Discord activated the ping”.
    raw_url=str(cfg['discord_webhook'])
    parts=urllib.parse.urlsplit(raw_url)
    query=urllib.parse.parse_qsl(parts.query,keep_blank_values=True)
    query=[(k,v) for k,v in query if k.lower()!='wait']+[('wait','true')]
    webhook_url=urllib.parse.urlunsplit((parts.scheme,parts.netloc,parts.path,urllib.parse.urlencode(query),parts.fragment))
    req = urllib.request.Request(webhook_url, data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'Seeker/7.1.0'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            status=int(resp.status)
            raw=b''
            try: raw=resp.read()
            except Exception: pass
            created={}
            if raw:
                try: created=json.loads(raw.decode('utf-8'))
                except Exception: created={}
            requested_everyone=bool(re.search(r'(?<!\w)@(everyone|here)\b',message,re.I))
            requested_roles=list(dict.fromkeys(re.findall(r'<@&(\d{2,24})>',message)))
            requested_users=list(dict.fromkeys(re.findall(r'<@!?(\d{2,24})>',message)))
            mention_everyone=bool(created.get('mention_everyone')) if isinstance(created,dict) else False
            mention_roles=[str(x) for x in (created.get('mention_roles') or [])] if isinstance(created,dict) else []
            mentioned_users=[str(x.get('id')) for x in (created.get('mentions') or []) if isinstance(x,dict) and x.get('id')] if isinstance(created,dict) else []
            ping_ok=(not requested_everyone or mention_everyone) and all(r in mention_roles for r in requested_roles) and all(u in mentioned_users for u in requested_users)
            warning=''
            if (requested_everyone or requested_roles or requested_users) and created and not ping_ok:
                warning='Discord posted the message but did not activate every requested mention. Check the channel/server “Mention @everyone, @here, and All Roles” permission; specific roles must be mentionable or addressed by role ID.'
            return {'ok': 200 <= status < 300, 'status': status, 'ping_ok': ping_ok, 'warning': warning,
                    'mention_everyone': mention_everyone, 'mention_roles': mention_roles, 'mentioned_users': mentioned_users}
    except urllib.error.HTTPError as exc:
        detail=''
        try: detail=exc.read().decode('utf-8','replace')[:500]
        except Exception: pass
        raise ValueError(f'Discord rejected the webhook ({exc.code}){": "+detail if detail else "."}') from exc
    except Exception as exc:
        raise ValueError(f'Could not reach Discord: {exc}') from exc


def discord_session_confirmation(settings: Settings, campaign_id: int, session: dict, *, base_url: str = '') -> dict:
    cfg = integration_config(settings, campaign_id, include_secret=True)
    if not cfg.get('discord_auto_session_confirmed'):
        return {'ok': False, 'skipped': 'disabled'}
    if not cfg.get('discord_enabled') or not cfg.get('discord_webhook'):
        return {'ok': False, 'skipped': 'discord-not-configured'}
    raw = str(session.get('session_date') or '').strip()
    if not raw:
        return {'ok': False, 'skipped': 'no-date'}
    try:
        day = dt.date.fromisoformat(raw[:10])
        pretty = day.strftime('%A, %d %B %Y').replace(' 0', ' ')
    except Exception:
        pretty = raw
    camp = _row(settings, 'SELECT name FROM campaigns WHERE id=?', (int(campaign_id),)) or {'name': 'Campaign'}
    mention = _normalize_discord_mention(cfg.get('discord_mention'))
    title = str(session.get('title') or 'Next session').strip()
    lines = []
    if mention:
        lines.append(mention)
    lines += [
        f'📅 **Session confirmed · {camp.get("name") or "Campaign"}**',
        f'**{title}**',
        f'🗓️ {pretty}',
    ]
    if base_url:
        lines.append(f'🔗 {base_url.rstrip("/")}/session')
    return discord_post(settings, campaign_id, '\n'.join(lines))


def _bounded_sheet(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    try:
        encoded = json.dumps(raw, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        return {}
    if len(encoded.encode('utf-8')) > 750_000:
        return {'warning': 'Actor snapshot exceeded Seeker’s 750 kB safety limit.'}
    return raw


def foundry_accept(settings: Settings, campaign_id: int, token: str, payload: dict) -> dict:
    _validate_foundry_token(settings,campaign_id,token)
    scene = payload.get('scene') or {}
    world = payload.get('world') or {}
    actors=[]
    for a in (payload.get('actors') or [])[:60]:
        if not isinstance(a, dict):
            continue
        actor={
            'id': str(a.get('id') or '')[:300],
            'uuid': str(a.get('uuid') or '')[:500],
            'name': str(a.get('name') or '')[:300],
            'img': str(a.get('img') or '')[:2000],
            'url': str(a.get('url') or '')[:2500],
            'type': str(a.get('type') or '')[:100],
            'active': bool(a.get('active', True)),
            'owners': [str(x)[:160] for x in (a.get('owners') or [])[:20]],
            'sheet': normalize_foundry_sheet(_bounded_sheet(a.get('sheet') or {})),
        }
        if actor['id']:
            actors.append(actor)
    clean = {
        'bridge_version': str(payload.get('bridge_version') or '')[:80],
        'system': str(payload.get('system') or '')[:120],
        'system_version': str(payload.get('system_version') or '')[:80],
        'foundry_version': str(payload.get('foundry_version') or '')[:80],
        'scene': {'id': str(scene.get('id') or '')[:300], 'name': str(scene.get('name') or '')[:300], 'img': str(scene.get('img') or '')[:2000]},
        'world': {'id': str(world.get('id') or '')[:300], 'title': str(world.get('title') or '')[:300]},
        'actors': [{k:v for k,v in a.items() if k != 'sheet'} for a in actors],
        'combat': payload.get('combat') if isinstance(payload.get('combat'), dict) else {},
    }
    now=time.time(); cid=int(campaign_id)
    with connect(settings) as conn:
        conn.execute('''INSERT INTO foundry_bridge_state(campaign_id,scene_name,scene_id,world_name,payload_json,received_at)
                        VALUES(?,?,?,?,?,?) ON CONFLICT(campaign_id) DO UPDATE SET scene_name=excluded.scene_name,scene_id=excluded.scene_id,world_name=excluded.world_name,payload_json=excluded.payload_json,received_at=excluded.received_at''',
                     (cid, clean['scene']['name'], clean['scene']['id'], clean['world']['title'], json.dumps(clean,ensure_ascii=False), now))
        seen=[]
        for a in actors:
            seen.append(a['id'])
            conn.execute('''INSERT INTO foundry_actor_snapshots(
                campaign_id,actor_id,actor_uuid,name,img,actor_url,actor_type,owners_json,sheet_json,received_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id,actor_id) DO UPDATE SET
                actor_uuid=excluded.actor_uuid,name=excluded.name,img=excluded.img,actor_url=excluded.actor_url,
                actor_type=excluded.actor_type,owners_json=excluded.owners_json,sheet_json=excluded.sheet_json,received_at=excluded.received_at''',
                (cid,a['id'],a['uuid'],a['name'],a['img'],a['url'],a['type'],json.dumps(a['owners'],ensure_ascii=False),json.dumps(a['sheet'],ensure_ascii=False),now))
        if seen:
            marks=','.join('?' for _ in seen)
            conn.execute(f'DELETE FROM foundry_actor_snapshots WHERE campaign_id=? AND actor_id NOT IN ({marks})',(cid,*seen))
        else:
            conn.execute('DELETE FROM foundry_actor_snapshots WHERE campaign_id=?',(cid,))
    return {'ok': True, 'actors': len(actors), 'commands': claim_foundry_commands(settings,campaign_id,token)}


def foundry_state(settings: Settings, campaign_id: int) -> dict:
    row = _row(settings, 'SELECT * FROM foundry_bridge_state WHERE campaign_id=?', (int(campaign_id),)) or {}
    row['payload'] = _json(row.get('payload_json'), {})
    return row


def foundry_actors(settings: Settings, campaign_id: int) -> list[dict]:
    rows=_rows(settings, 'SELECT actor_id,actor_uuid,name,img,actor_url,actor_type,owners_json,sheet_json,received_at FROM foundry_actor_snapshots WHERE campaign_id=? ORDER BY lower(name),actor_id', (int(campaign_id),))
    for row in rows:
        row['owners']=_json(row.pop('owners_json', '[]'), [])
        row['sheet']=normalize_foundry_sheet(_json(row.pop('sheet_json', '{}'), {}))
    return rows


def foundry_actor(settings: Settings, campaign_id: int, actor_id: str) -> dict | None:
    row=_row(settings, 'SELECT actor_id,actor_uuid,name,img,actor_url,actor_type,owners_json,sheet_json,received_at FROM foundry_actor_snapshots WHERE campaign_id=? AND actor_id=?', (int(campaign_id),str(actor_id)))
    if not row:
        return None
    row['owners']=_json(row.pop('owners_json', '[]'), [])
    row['sheet']=normalize_foundry_sheet(_json(row.pop('sheet_json', '{}'), {}))
    return row


def foundry_link(settings: Settings, character_id: int, campaign_id: int, actor_id: str | None = None) -> dict | None:
    char=_row(settings,'SELECT id,campaign_id FROM player_characters WHERE id=?',(int(character_id),))
    if not char:
        raise ValueError('Character not found.')
    cid=int(char.get('campaign_id') or campaign_id)
    if cid != int(campaign_id):
        raise ValueError('Character belongs to a different campaign.')
    aid=str(actor_id or '').strip()
    with connect(settings) as conn:
        if not aid:
            conn.execute('DELETE FROM foundry_character_links WHERE character_id=?',(int(character_id),))
            return None
        exists=conn.execute('SELECT 1 FROM foundry_actor_snapshots WHERE campaign_id=? AND actor_id=?',(cid,aid)).fetchone()
        if not exists:
            raise ValueError('That Foundry actor has not been synced for this campaign.')
        conn.execute('''INSERT INTO foundry_character_links(character_id,campaign_id,actor_id,linked_at) VALUES(?,?,?,?)
                        ON CONFLICT(character_id) DO UPDATE SET campaign_id=excluded.campaign_id,actor_id=excluded.actor_id,linked_at=excluded.linked_at''',(int(character_id),cid,aid,time.time()))
    return foundry_actor(settings,cid,aid)


def foundry_link_for_character(settings: Settings, character_id: int) -> dict | None:
    row=_row(settings,'''SELECT l.campaign_id,l.actor_id,a.actor_uuid,a.name,a.img,a.actor_url,a.actor_type,a.owners_json,a.sheet_json,a.received_at
                         FROM foundry_character_links l LEFT JOIN foundry_actor_snapshots a ON a.campaign_id=l.campaign_id AND a.actor_id=l.actor_id
                         WHERE l.character_id=?''',(int(character_id),))
    if not row:
        return None
    row['owners']=_json(row.pop('owners_json','[]'),[])
    row['sheet']=normalize_foundry_sheet(_json(row.pop('sheet_json','{}'),{}))
    row['stale']=not bool(row.get('name'))
    return row


def foundry_manifest(settings: Settings, base_url: str) -> dict:
    source=settings.root_dir/'integrations'/'foundry-seeker-bridge'/'module.json'
    try:
        data=json.loads(source.read_text(encoding='utf-8'))
    except Exception:
        data={'id':'seeker-bridge','title':'Seeker Bridge','version':_foundry_module_version(),'esmodules':['seeker-bridge.mjs']}
    base=base_url.rstrip('/')
    data['version']=_foundry_module_version()
    data['manifest']=f'{base}/foundry/seeker-bridge/module.json'
    data['download']=f'{base}/foundry/seeker-bridge/seeker-bridge.zip'
    data['url']=base
    return data


def build_foundry_module_zip(settings: Settings, base_url: str, target: Path) -> Path:
    source=settings.root_dir/'integrations'/'foundry-seeker-bridge'
    target.parent.mkdir(parents=True,exist_ok=True)
    base=base_url.rstrip('/')
    manifest=foundry_manifest(settings,base)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('module.json',json.dumps(manifest,indent=2,ensure_ascii=False))
        for path in source.rglob('*'):
            if not path.is_file() or path.name == 'module.json':
                continue
            arcname=path.relative_to(source).as_posix()
            if path.name == 'seeker-bridge.mjs':
                # Pin the downloaded bridge to the same public origin as its manifest.
                # This lets a module update repair a bridge endpoint saved with an old
                # Railway/generated hostname without hard-coding one deployment in source.
                bridge=path.read_text(encoding='utf-8').replace('__SEEKER_PUBLIC_ORIGIN__',base)
                zf.writestr(arcname,bridge)
            else:
                zf.write(path,arcname)
    return target


def calendar_feed(settings: Settings, campaign_id: int, token: str, base_url: str = '') -> str:
    cfg = integration_config(settings, campaign_id, include_secret=True)
    if not secrets.compare_digest(str(cfg.get('calendar_token') or ''), str(token or '')):
        raise PermissionError('Invalid calendar token.')
    camp = _row(settings, 'SELECT * FROM campaigns WHERE id=?', (int(campaign_id),)) or {'name': 'Seeker'}
    sessions = _rows(settings, "SELECT * FROM campaign_sessions WHERE campaign_id=? AND session_date!='' AND status IN ('planned','live') ORDER BY session_date,id", (int(campaign_id),))
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Seeker//Campaign Calendar//EN', 'CALSCALE:GREGORIAN', f'X-WR-CALNAME:{_ics(str(camp.get("name") or "Seeker"))}']
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for s in sessions:
        raw = str(s.get('session_date') or '')
        try:
            day = dt.date.fromisoformat(raw[:10])
        except Exception:
            continue
        lines += ['BEGIN:VEVENT', f'UID:seeker-session-{s["id"]}@seeker', f'DTSTAMP:{stamp}', f'DTSTART;VALUE=DATE:{day.strftime("%Y%m%d")}', f'DTEND;VALUE=DATE:{(day + dt.timedelta(days=1)).strftime("%Y%m%d")}', f'SUMMARY:{_ics(str(s.get("title") or "Session"))}']
        if s.get('summary'):
            lines.append(f'DESCRIPTION:{_ics(str(s.get("summary"))[:2000])}')
        if base_url:
            lines.append(f'URL:{base_url.rstrip("/")}/session')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines) + '\r\n'


def session_ics(session: dict, campaign_name: str = 'Seeker', base_url: str = '') -> str:
    raw = str(session.get('session_date') or '')
    try:
        day = dt.date.fromisoformat(raw[:10])
    except Exception:
        raise ValueError('This session does not have a calendar date yet.')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Seeker//Session//EN', 'CALSCALE:GREGORIAN', 'BEGIN:VEVENT', f'UID:seeker-session-{session.get("id")}@seeker', f'DTSTAMP:{stamp}', f'DTSTART;VALUE=DATE:{day.strftime("%Y%m%d")}', f'DTEND;VALUE=DATE:{(day+dt.timedelta(days=1)).strftime("%Y%m%d")}', f'SUMMARY:{_ics(str(session.get("title") or campaign_name))}']
    if session.get('summary'):
        lines.append(f'DESCRIPTION:{_ics(str(session.get("summary"))[:2000])}')
    if base_url:
        lines.append(f'URL:{base_url.rstrip("/")}/session')
    lines += ['END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(lines) + '\r\n'


def _ics(text: str) -> str:
    return text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n').replace('\r', '')


def sync_lore_revisions(settings: Settings, wiki: dict) -> int:
    global _LAST_LORE_GENERATION
    generated = float(wiki.get('generated_at') or 0)
    if _LAST_LORE_GENERATION == generated:
        return 0
    with _LORE_SYNC_LOCK:
        if _LAST_LORE_GENERATION == generated:
            return 0
        added = 0
        with connect(settings) as conn:
            for p in wiki.get('pages', []):
                slug = str(p.get('slug') or '')
                if not slug:
                    continue
                rendered = str(p.get('html') or '')
                presentation = p.get('presentation') or {}
                digest = hashlib.sha256((rendered + '\0' + json.dumps(presentation, sort_keys=True)).encode('utf-8')).hexdigest()
                exists = conn.execute('SELECT 1 FROM lore_page_revisions WHERE page_slug=? AND content_hash=?', (slug, digest)).fetchone()
                if exists:
                    continue
                conn.execute('''INSERT INTO lore_page_revisions(page_slug,title,chapter,source_file,source_line,content_hash,html,plain_text,presentation_json,generated_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?)''', (slug, str(p.get('title') or ''), str(p.get('chapter') or ''), str(p.get('source_file') or ''), int(p.get('source_line') or 0) or None, digest, rendered, str(p.get('plain_text') or ''), json.dumps(presentation), generated or time.time()))
                added += 1
                stale = conn.execute('SELECT id FROM lore_page_revisions WHERE page_slug=? ORDER BY generated_at DESC,id DESC LIMIT -1 OFFSET 30', (slug,)).fetchall()
                if stale:
                    conn.executemany('DELETE FROM lore_page_revisions WHERE id=?', [(int(r[0]),) for r in stale])
        _LAST_LORE_GENERATION = generated
        return added


def lore_revisions(settings: Settings, slug: str) -> list[dict]:
    rows = _rows(settings, 'SELECT id,page_slug,title,chapter,source_file,source_line,content_hash,generated_at FROM lore_page_revisions WHERE page_slug=? ORDER BY generated_at DESC,id DESC', (str(slug),))
    return rows


def lore_revision_diff(settings: Settings, slug: str, revision_id: int) -> dict:
    old = _row(settings, 'SELECT * FROM lore_page_revisions WHERE id=? AND page_slug=?', (int(revision_id), str(slug)))
    current = _row(settings, 'SELECT * FROM lore_page_revisions WHERE page_slug=? ORDER BY generated_at DESC,id DESC LIMIT 1', (str(slug),))
    if not old or not current:
        raise ValueError('Lore revision not found.')
    diff = difflib.unified_diff(str(old.get('plain_text') or '').splitlines(), str(current.get('plain_text') or '').splitlines(), fromfile=f'{slug}@{revision_id}', tofile=f'{slug}@current', lineterm='')
    return {'revision': old, 'current': current, 'diff': '\n'.join(list(diff)[:5000])}


def restore_lore_source_revision(settings: Settings, revision_id: int) -> dict:
    page_rev = _row(settings, 'SELECT * FROM lore_page_revisions WHERE id=?', (int(revision_id),))
    if not page_rev or not page_rev.get('source_file'):
        raise ValueError('This generated revision does not point to a restorable source file.')
    candidates = list_revisions(settings, str(page_rev['source_file']))
    if not candidates:
        raise ValueError('No archived source revision is available for this page.')
    before = [r for r in candidates if float(r.get('created_at') or 0) <= float(page_rev.get('generated_at') or 0) + 2]
    chosen = max(before, key=lambda r: float(r.get('created_at') or 0)) if before else min(candidates, key=lambda r: abs(float(r.get('created_at') or 0) - float(page_rev.get('generated_at') or 0)))
    restore_revision(settings, str(page_rev['source_file']), str(chosen['id']))
    return {'ok': True, 'source_file': page_rev['source_file'], 'source_revision': chosen['id']}



def page_update_status(settings: Settings, slug: str, invite_id: int | None) -> dict:
    """Tell a player whether the rendered lore changed since their prior view."""
    if invite_id is None:
        return {'updated_since_read':False,'latest_revision_at':0,'last_read_at':0}
    latest=_row(settings,'SELECT generated_at FROM lore_page_revisions WHERE page_slug=? ORDER BY generated_at DESC,id DESC LIMIT 1',(str(slug),))
    with connect(settings) as conn:
        read=conn.execute("SELECT MAX(created_at) FROM player_activity WHERE invite_id=? AND event_type='view' AND target_key=?",(int(invite_id),str(slug))).fetchone()
    latest_at=float((latest or {}).get('generated_at') or 0);read_at=float((read[0] if read else 0) or 0)
    return {'updated_since_read':bool(read_at and latest_at>read_at+0.01),'latest_revision_at':latest_at,'last_read_at':read_at}

def knowledge_matrix(settings: Settings, campaign_ids: list[int] | None = None) -> dict:
    with connect(settings) as conn:
        campaigns = [dict(r) for r in conn.execute("SELECT id,name,accent,status FROM campaigns WHERE status!='archived' ORDER BY name COLLATE NOCASE").fetchall()]
        if campaign_ids:
            allowed = {int(x) for x in campaign_ids}
            campaigns = [c for c in campaigns if int(c['id']) in allowed]
        ids = [int(c['id']) for c in campaigns]
        if not ids:
            return {'campaigns': [], 'rows': []}
        placeholders = ','.join('?' for _ in ids)
        knowledge = [dict(r) for r in conn.execute(f'''SELECT campaign_id,target_key,
            CASE state WHEN 'known' THEN 4 WHEN 'discovered' THEN 4 WHEN 'revealed' THEN 4 WHEN 'rumor' THEN 2 WHEN 'suspected' THEN 2 ELSE 0 END rank,
            state FROM player_knowledge WHERE target_type='page' AND campaign_id IN ({placeholders})''', tuple(ids)).fetchall()]
        reveals = [dict(r) for r in conn.execute(f'''SELECT campaign_id,target_key,state FROM lore_reveals WHERE target_type='page' AND campaign_id IN ({placeholders})''', tuple(ids)).fetchall()]
    data: dict[str, dict[int, str]] = {}
    ranks: dict[tuple[str,int], int] = {}
    for r in knowledge:
        key=(str(r['target_key']),int(r['campaign_id']));rank=int(r.get('rank') or 0)
        if rank >= ranks.get(key,-1):
            ranks[key]=rank;data.setdefault(key[0],{})[key[1]]=str(r.get('state') or 'unknown')
    for r in reveals:
        state=str(r.get('state') or 'hidden'); rank={'revealed':4,'public':4,'rumor':2,'hidden':0}.get(state,1)
        key=(str(r['target_key']),int(r['campaign_id']))
        if rank >= ranks.get(key,-1):
            ranks[key]=rank;data.setdefault(key[0],{})[key[1]]=state
    return {'campaigns': campaigns, 'rows': [{'slug':slug,'states':states} for slug,states in sorted(data.items())]}


def converge_campaigns(settings: Settings, target_campaign_id: int, source_campaign_ids: list[int], options: dict) -> dict:
    target=int(target_campaign_id); sources=sorted({int(x) for x in source_campaign_ids if int(x)!=target})
    if not sources:
        raise ValueError('Choose at least one source campaign.')
    summary={'knowledge':0,'reveals':0,'discoveries':0,'objectives':0,'memberships':0}
    with connect(settings) as conn:
        if not conn.execute('SELECT 1 FROM campaigns WHERE id=?',(target,)).fetchone(): raise ValueError('Target campaign not found.')
        placeholders=','.join('?' for _ in sources)
        if options.get('memberships', True):
            cur=conn.execute(f'''INSERT OR IGNORE INTO campaign_memberships(campaign_id,invite_id,created_at)
                SELECT ?,invite_id,? FROM campaign_memberships WHERE campaign_id IN ({placeholders})''',(target,time.time(),*sources));summary['memberships']=max(0,cur.rowcount)
        if options.get('knowledge', True):
            rows=conn.execute(f"SELECT * FROM player_knowledge WHERE campaign_id IN ({placeholders})",tuple(sources)).fetchall()
            for r in rows:
                conn.execute('''INSERT INTO player_knowledge(campaign_id,invite_id,target_type,target_key,state,note,source,updated_at) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(campaign_id,invite_id,target_type,target_key) DO UPDATE SET state=excluded.state,note=CASE WHEN excluded.note!='' THEN excluded.note ELSE player_knowledge.note END,updated_at=MAX(player_knowledge.updated_at,excluded.updated_at)''',
                    (target,r['invite_id'],r['target_type'],r['target_key'],r['state'],r['note'],r['source'],time.time()));summary['knowledge']+=1
        if options.get('reveals', True):
            rows=conn.execute(f"SELECT * FROM lore_reveals WHERE campaign_id IN ({placeholders})",tuple(sources)).fetchall()
            priority={'hidden':0,'rumor':1,'revealed':2,'public':2}
            for r in rows:
                cur=conn.execute('SELECT * FROM lore_reveals WHERE campaign_id=? AND target_type=? AND target_key=?',(target,r['target_type'],r['target_key'])).fetchone()
                if cur and priority.get(str(cur['state']),0)>priority.get(str(r['state']),0): continue
                conn.execute('''INSERT INTO lore_reveals(campaign_id,target_type,target_key,state,rumor_text,audience_json,expires_at,revealed_at,session_id,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id,target_type,target_key) DO UPDATE SET state=excluded.state,rumor_text=excluded.rumor_text,audience_json=excluded.audience_json,updated_at=excluded.updated_at''',
                    (target,r['target_type'],r['target_key'],r['state'],r['rumor_text'],r['audience_json'],r['expires_at'],r['revealed_at'],None,time.time()));summary['reveals']+=1
        if options.get('discoveries', True):
            rows=conn.execute(f"SELECT * FROM campaign_map_discoveries WHERE campaign_id IN ({placeholders})",tuple(sources)).fetchall(); pr={'unknown':0,'rumored':1,'discovered':2,'visited':3}
            for r in rows:
                cur=conn.execute('SELECT state FROM campaign_map_discoveries WHERE campaign_id=? AND marker_id=?',(target,r['marker_id'])).fetchone()
                if cur and pr.get(str(cur['state']),0)>pr.get(str(r['state']),0): continue
                conn.execute('''INSERT INTO campaign_map_discoveries(campaign_id,marker_id,state,first_session_id,updated_at) VALUES(?,?,?,?,?)
                    ON CONFLICT(campaign_id,marker_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at''',(target,r['marker_id'],r['state'],None,time.time()));summary['discoveries']+=1
        if options.get('objectives', True):
            rows=conn.execute(f"SELECT * FROM campaign_objectives WHERE campaign_id IN ({placeholders})",tuple(sources)).fetchall()
            existing={(str(r['title']).strip().casefold(),str(r['status'])) for r in conn.execute('SELECT title,status FROM campaign_objectives WHERE campaign_id=?',(target,)).fetchall()}
            for r in rows:
                key=(str(r['title']).strip().casefold(),str(r['status']))
                if key in existing: continue
                conn.execute('''INSERT INTO campaign_objectives(campaign_id,title,body,status,kind,creator_invite_id,creator_label,linked_type,linked_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(target,r['title'],r['body'],r['status'],r['kind'] or 'party',None,str(r['creator_label'] or 'Merged campaign'),r['linked_type'] or '',r['linked_key'] or '',time.time(),time.time()));existing.add(key);summary['objectives']+=1
        conn.execute('INSERT INTO campaign_convergences(target_campaign_id,source_campaign_ids_json,options_json,summary_json,created_at) VALUES(?,?,?,?,?)',(target,json.dumps(sources),json.dumps(options),json.dumps(summary),time.time()))
    return {'ok':True,'target_campaign_id':target,'source_campaign_ids':sources,'summary':summary}


def changes_since_last_session(settings: Settings, campaign_id: int) -> dict:
    cid=int(campaign_id)
    with connect(settings) as conn:
        last=conn.execute("SELECT * FROM campaign_sessions WHERE campaign_id=? AND status='ended' ORDER BY COALESCE(session_date,'' ) DESC,updated_at DESC,id DESC LIMIT 1",(cid,)).fetchone()
        since=float(last['updated_at']) if last else 0.0
        def rows(sql, params=()): return [dict(r) for r in conn.execute(sql,params).fetchall()]
        result={
            'last_session':dict(last) if last else None,'since':since,
            'objectives':rows('SELECT * FROM campaign_objectives WHERE campaign_id=? AND updated_at>? ORDER BY updated_at DESC',(cid,since)),
            'discoveries':rows('''SELECT d.*,m.title,m.page_slug FROM campaign_map_discoveries d JOIN markers m ON m.id=d.marker_id WHERE d.campaign_id=? AND d.updated_at>? ORDER BY d.updated_at DESC''',(cid,since)),
            'clues':rows('SELECT * FROM gm_clues WHERE campaign_id=? AND updated_at>? ORDER BY updated_at DESC',(cid,since)),
            'clocks':rows('SELECT * FROM gm_clocks WHERE campaign_id=? AND updated_at>? ORDER BY updated_at DESC',(cid,since)),
            'events':rows('SELECT * FROM gm_session_events WHERE campaign_id=? AND created_at>? ORDER BY created_at DESC',(cid,since)),
            'notes':rows('SELECT * FROM party_notes WHERE campaign_id=? AND updated_at>? ORDER BY updated_at DESC LIMIT 30',(cid,since)),
            'consequences':rows('SELECT * FROM gm_consequences WHERE campaign_id=? AND updated_at>? ORDER BY updated_at DESC',(cid,since)),
        }
    result['count']=sum(len(v) for k,v in result.items() if isinstance(v,list))
    return result


def continuity_v6(settings: Settings, campaign_id: int, wiki: dict) -> dict:
    cid=int(campaign_id);pages={str(p.get('slug')):p for p in wiki.get('pages',[])};issues=[]
    with connect(settings) as conn:
        for s in conn.execute('SELECT id,title,location_slug,npc_slugs_json,status FROM gm_scene_cards WHERE campaign_id=?',(cid,)).fetchall():
            if s['location_slug'] and s['location_slug'] not in pages: issues.append({'severity':'warning','title':s['title'],'message':f"Scene location is missing from the Codex: {s['location_slug']}",'href':'/gm/prep'})
            for slug in _json(s['npc_slugs_json'],[]):
                if slug and slug not in pages: issues.append({'severity':'warning','title':s['title'],'message':f'Scene references missing NPC lore: {slug}','href':'/gm/prep'})
        for c in conn.execute("SELECT * FROM gm_clues WHERE campaign_id=? AND status IN ('found','discovered') AND delivered_session_id IS NULL",(cid,)).fetchall(): issues.append({'severity':'info','title':c['title'],'message':'Clue is marked discovered but has no delivery session recorded.','href':'/gm/prep'})
        for c in conn.execute("SELECT * FROM gm_consequences WHERE campaign_id=? AND status='pending'",(cid,)).fetchall():
            if c['trigger_kind']=='date':
                try:
                    if dt.date.fromisoformat(str(c['trigger_value'])[:10]) < dt.date.today(): issues.append({'severity':'warning','title':c['title'],'message':'A dated consequence is overdue.','href':'/gm/prep'})
                except Exception: pass
        hidden={str(r['target_key']) for r in conn.execute("SELECT target_key FROM lore_reveals WHERE campaign_id=? AND target_type='page' AND state='hidden'",(cid,)).fetchall()}
        for h in conn.execute("SELECT id,title,body FROM handouts WHERE campaign_id=?",(cid,)).fetchall():
            text=(str(h['title'])+' '+str(h['body'])).casefold()
            for slug in list(hidden)[:1000]:
                page=pages.get(slug);title=str((page or {}).get('title') or '')
                if title and len(title)>3 and title.casefold() in text: issues.append({'severity':'warning','title':h['title'],'message':f'Player handout mentions hidden lore: {title}','href':'/handouts'});break
    return {'issues':issues,'count':len(issues)}


def player_dashboard(settings: Settings, campaign_id: int, invite_id: int) -> dict:
    cid=int(campaign_id);iid=int(invite_id)
    with connect(settings) as conn:
        char=conn.execute("SELECT * FROM player_characters WHERE campaign_id=? AND invite_id=? AND status NOT IN ('retired','dead','inactive') ORDER BY updated_at DESC LIMIT 1",(cid,iid)).fetchone()
        next_session=conn.execute("SELECT * FROM campaign_sessions WHERE campaign_id=? AND status='planned' ORDER BY CASE WHEN session_date='' THEN 1 ELSE 0 END,session_date,id LIMIT 1",(cid,)).fetchone()
        objectives=[dict(r) for r in conn.execute("SELECT * FROM campaign_objectives WHERE campaign_id=? AND status IN ('active','hold') ORDER BY updated_at DESC,id DESC LIMIT 6",(cid,)).fetchall()]
        follows=[dict(r) for r in conn.execute("SELECT * FROM player_follows WHERE campaign_id=? AND invite_id=? ORDER BY created_at DESC LIMIT 6",(cid,iid)).fetchall()]
        unread=int(conn.execute('''SELECT COUNT(*) FROM campaign_notifications n LEFT JOIN notification_reads r ON r.notification_id=n.id AND r.invite_id=? WHERE n.campaign_id=? AND r.notification_id IS NULL''',(iid,cid)).fetchone()[0]) if _table_exists(conn,'notification_reads') else 0
        mysteries=[dict(r) for r in conn.execute("SELECT * FROM mysteries WHERE campaign_id=? AND status NOT IN ('resolved','closed') ORDER BY updated_at DESC LIMIT 5",(cid,)).fetchall()]
    return {'character':dict(char) if char else None,'next_session':dict(next_session) if next_session else None,'objectives':objectives,'follows':follows,'unread_notifications':unread,'mysteries':mysteries}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is not None


def command_rows(settings: Settings, query: str, campaign_id: int, *, gm: bool, wiki: dict) -> list[dict]:
    q=str(query or '').strip();low=q.casefold();rows=[]
    def add(title,href,desc='',kind='jump'): rows.append({'title':title,'href':href,'excerpt':desc,'chapter':'Command','type':kind})
    commands=[('session','Session Mode','/session','Open the table companion.'),('prep','Session Prep','/gm/prep','Open the GM runbook.'),('continuity','Continuity Center','/gm/continuity','Changes, knowledge comparison, convergence and backups.'),('integrations','Integrations','/gm/integrations','Discord, Foundry and calendar feeds.'),('display','Table Display','/display','Open the player-safe presentation screen.'),('media','Media Board','/gm/media','Prepare portraits, maps and handouts for the table display.'),('tables','All Tables','/tables','Compare campaigns.'),('atlas','Atlas','/#atlas','Open maps and travel history.'),('schedule','Session Planner','/schedule','Availability and session dates.')]
    for key,title,href,desc in commands:
        if (not low or key.startswith(low) or low in title.casefold()) and (gm or not href.startswith('/gm/')): add(title,href,desc)
    if gm and low.startswith('advance clock '):
        name=q[len('advance clock '):].strip(); row=_row(settings,"SELECT id,title FROM gm_clocks WHERE campaign_id=? AND lower(title)=lower(?) AND status='active' LIMIT 1",(int(campaign_id),name))
        if row: rows.insert(0,{'title':f'Advance {row["title"]}','href':'#','excerpt':'Advance this campaign clock by one segment.','chapter':'GM action','type':'action','action':{'kind':'advance_clock','id':row['id']}})
    if gm and low.startswith('reveal '):
        name=q[len('reveal '):].strip(); match=next((p for p in wiki.get('pages',[]) if str(p.get('title','')).casefold()==name.casefold() or str(p.get('slug','')).casefold()==name.casefold()),None)
        if match: rows.insert(0,{'title':f'Reveal {match["title"]}','href':'#','excerpt':'Reveal this Codex page to the active table.','chapter':'GM action','type':'action','action':{'kind':'reveal_page','slug':match['slug']}})
    return rows[:20]


def save_map_annotation(settings: Settings, campaign_id: int, map_id: int, invite_id: int | None, author_label: str, payload: dict, *, admin: bool=False) -> dict:
    rid=payload.get('id');visibility=str(payload.get('visibility') or 'party')
    if visibility not in {'private','party'}: visibility='party'
    vals=(str(payload.get('title') or 'Map note')[:200],str(payload.get('note') or '')[:4000],max(0,min(1,float(payload.get('x') or 0))),max(0,min(1,float(payload.get('y') or 0))),visibility,time.time())
    with connect(settings) as conn:
        if rid:
            row=conn.execute('SELECT * FROM campaign_map_annotations WHERE id=? AND campaign_id=? AND map_id=?',(int(rid),int(campaign_id),int(map_id))).fetchone()
            if not row: raise ValueError('Map annotation not found.')
            if not admin and int(row['invite_id'] or -1)!=int(invite_id or -2): raise PermissionError('You can only edit your own map annotations.')
            conn.execute('UPDATE campaign_map_annotations SET title=?,note=?,x=?,y=?,visibility=?,updated_at=? WHERE id=?',vals+(int(rid),));out=int(rid)
        else:
            out=int(conn.execute('INSERT INTO campaign_map_annotations(campaign_id,map_id,invite_id,author_label,title,note,x,y,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(int(campaign_id),int(map_id),int(invite_id) if invite_id else None,str(author_label or 'GM')[:120],*vals[:-1],vals[-1],vals[-1])).lastrowid)
    return _row(settings,'SELECT * FROM campaign_map_annotations WHERE id=?',(out,)) or {}


def list_map_annotations(settings: Settings, campaign_id: int, map_id: int, invite_id: int | None, *, admin: bool=False) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM campaign_map_annotations WHERE campaign_id=? AND map_id=? ORDER BY created_at,id',(int(campaign_id),int(map_id)))
    if admin:
        for r in rows:r['can_delete']=True
        return rows
    visible=[r for r in rows if r.get('visibility')=='party' or int(r.get('invite_id') or -1)==int(invite_id or -2)]
    for r in visible:r['can_delete']=int(r.get('invite_id') or -1)==int(invite_id or -2)
    return visible


def delete_map_annotation(settings: Settings, annotation_id: int, invite_id: int | None, *, admin: bool=False) -> None:
    with connect(settings) as conn:
        row=conn.execute('SELECT invite_id FROM campaign_map_annotations WHERE id=?',(int(annotation_id),)).fetchone()
        if not row:return
        if not admin and int(row['invite_id'] or -1)!=int(invite_id or -2): raise PermissionError('You can only delete your own map annotations.')
        conn.execute('DELETE FROM campaign_map_annotations WHERE id=?',(int(annotation_id),))


def record_travel_leg(settings: Settings, campaign_id: int, map_id: int, payload: dict) -> dict:
    a=int(payload.get('from_marker_id') or 0);b=int(payload.get('to_marker_id') or 0)
    with connect(settings) as conn:
        ma=conn.execute('SELECT * FROM markers WHERE id=? AND map_id=?',(a,int(map_id))).fetchone();mb=conn.execute('SELECT * FROM markers WHERE id=? AND map_id=?',(b,int(map_id))).fetchone()
        if not ma or not mb:raise ValueError('Choose two locations on this map.')
        route=[[float(ma['x']),float(ma['y'])],[float(mb['x']),float(mb['y'])]]
        rid=int(conn.execute('''INSERT INTO campaign_travel_legs(campaign_id,map_id,session_id,from_marker_id,to_marker_id,from_label,to_label,route_json,note,traveled_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',(int(campaign_id),int(map_id),int(payload.get('session_id')) if payload.get('session_id') else None,a,b,ma['title'],mb['title'],json.dumps(route),str(payload.get('note') or '')[:2000],time.time())).lastrowid)
    return travel_legs(settings,campaign_id,map_id)[-1]


def travel_legs(settings: Settings, campaign_id: int, map_id: int) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM campaign_travel_legs WHERE campaign_id=? AND map_id=? ORDER BY traveled_at,id',(int(campaign_id),int(map_id)))
    for r in rows:r['route']=_json(r.get('route_json'),[])
    return rows


def delete_travel_leg(settings: Settings, leg_id: int) -> None:
    with connect(settings) as conn:conn.execute('DELETE FROM campaign_travel_legs WHERE id=?',(int(leg_id),))


def list_media_items(settings: Settings, campaign_id: int, session_id: int) -> list[dict]:
    return _rows(settings,'SELECT * FROM session_media_items WHERE campaign_id=? AND session_id=? ORDER BY sort_order,id',(int(campaign_id),int(session_id)))


def save_media_item(settings: Settings, campaign_id: int, session_id: int, payload: dict) -> dict:
    rid=payload.get('id');vals=(str(payload.get('title') or 'Media')[:200],str(payload.get('kind') or 'image')[:40],str(payload.get('source_url') or '')[:3000],str(payload.get('target_type') or '')[:40],str(payload.get('target_key') or '')[:500],str(payload.get('caption') or '')[:2000],int(payload.get('sort_order') or 0),time.time())
    with connect(settings) as conn:
        if rid:
            row=conn.execute('SELECT 1 FROM session_media_items WHERE id=? AND campaign_id=? AND session_id=?',(int(rid),int(campaign_id),int(session_id))).fetchone()
            if not row:raise ValueError('Media item not found.')
            conn.execute('UPDATE session_media_items SET title=?,kind=?,source_url=?,target_type=?,target_key=?,caption=?,sort_order=?,updated_at=? WHERE id=?',vals+(int(rid),));out=int(rid)
        else:
            now=vals[-1];out=int(conn.execute('INSERT INTO session_media_items(campaign_id,session_id,title,kind,source_url,target_type,target_key,caption,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(int(campaign_id),int(session_id),*vals[:-1],now,now)).lastrowid)
    return _row(settings,'SELECT * FROM session_media_items WHERE id=?',(out,)) or {}


def delete_media_item(settings: Settings, item_id: int) -> None:
    with connect(settings) as conn:conn.execute('DELETE FROM session_media_items WHERE id=?',(int(item_id),))


def display_state(settings: Settings, campaign_id: int) -> dict:
    return _row(settings,'SELECT * FROM campaign_display_state WHERE campaign_id=?',(int(campaign_id),)) or {'campaign_id':int(campaign_id),'mode':'idle','title':'','body':'','source_url':'','updated_at':0}


def set_display_state(settings: Settings, campaign_id: int, payload: dict) -> dict:
    mode=str(payload.get('mode') or 'idle')[:40];item_id=int(payload.get('media_item_id')) if payload.get('media_item_id') else None
    title=str(payload.get('title') or '')[:300];body=str(payload.get('body') or '')[:5000];source=str(payload.get('source_url') or '')[:3000]
    if item_id:
        item=_row(settings,'SELECT * FROM session_media_items WHERE id=? AND campaign_id=?',(item_id,int(campaign_id)))
        if not item:raise ValueError('Media item not found.')
        title=title or str(item.get('title') or '');body=body or str(item.get('caption') or '');source=source or str(item.get('source_url') or '');mode=mode if mode!='idle' else str(item.get('kind') or 'image')
    with connect(settings) as conn:
        conn.execute('''INSERT INTO campaign_display_state(campaign_id,media_item_id,mode,title,body,source_url,updated_at) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(campaign_id) DO UPDATE SET media_item_id=excluded.media_item_id,mode=excluded.mode,title=excluded.title,body=excluded.body,source_url=excluded.source_url,updated_at=excluded.updated_at''',(int(campaign_id),item_id,mode,title,body,source,time.time()))
    return display_state(settings,campaign_id)


def campaign_keepsake(settings: Settings, campaign_id: int, out: Path) -> Path:
    """Create a human-readable keepsake plus machine-readable campaign archive."""
    cid=int(campaign_id);out.parent.mkdir(parents=True,exist_ok=True)
    with connect(settings) as conn:
        camp=dict(conn.execute('SELECT * FROM campaigns WHERE id=?',(cid,)).fetchone() or {})
        if not camp:raise ValueError('Campaign not found.')
        sessions=[dict(r) for r in conn.execute('SELECT * FROM campaign_sessions WHERE campaign_id=? ORDER BY COALESCE(session_number,999999),session_date,id',(cid,)).fetchall()]
        chars=[dict(r) for r in conn.execute('SELECT * FROM player_characters WHERE campaign_id=? ORDER BY name COLLATE NOCASE',(cid,)).fetchall()]
        milestones=[dict(r) for r in conn.execute('''SELECT m.*,c.name AS character_name,s.title AS session_title,s.session_number FROM character_milestones m JOIN player_characters c ON c.id=m.character_id LEFT JOIN campaign_sessions s ON s.id=m.session_id WHERE c.campaign_id=? ORDER BY m.created_at,m.id''',(cid,)).fetchall()]
        objs=[dict(r) for r in conn.execute('SELECT * FROM campaign_objectives WHERE campaign_id=? ORDER BY status,updated_at DESC,id',(cid,)).fetchall()]
        disc=[dict(r) for r in conn.execute('''SELECT d.state,d.updated_at,d.first_session_id,m.title,m.page_slug,m.map_id FROM campaign_map_discoveries d JOIN markers m ON m.id=d.marker_id WHERE d.campaign_id=? ORDER BY d.updated_at''',(cid,)).fetchall()]
        handouts=[dict(r) for r in conn.execute('SELECT * FROM handouts WHERE campaign_id=? ORDER BY created_at,id',(cid,)).fetchall()]
        clocks=[dict(r) for r in conn.execute('SELECT * FROM gm_clocks WHERE campaign_id=? ORDER BY created_at,id',(cid,)).fetchall()]
        mysteries=[dict(r) for r in conn.execute('SELECT * FROM mysteries WHERE campaign_id=? ORDER BY created_at,id',(cid,)).fetchall()]
        party_notes=[dict(r) for r in conn.execute('SELECT * FROM party_notes WHERE campaign_id=? ORDER BY created_at,id',(cid,)).fetchall()]
        travel=[dict(r) for r in conn.execute('''SELECT t.*,m.name AS map_name FROM campaign_travel_legs t LEFT JOIN maps m ON m.id=t.map_id WHERE t.campaign_id=? ORDER BY t.traveled_at,t.id''',(cid,)).fetchall()]
        media=[dict(r) for r in conn.execute('''SELECT mi.*,s.title AS session_title FROM session_media_items mi JOIN campaign_sessions s ON s.id=mi.session_id WHERE mi.campaign_id=? ORDER BY mi.session_id,mi.sort_order,mi.id''',(cid,)).fetchall()]
    title=html.escape(str(camp.get('name') or 'Campaign'))
    style='body{font:16px/1.6 system-ui;max-width:960px;margin:40px auto;padding:0 24px;color:#241c15;background:#faf7f1}h1,h2,h3{font-family:Georgia,serif}h1{font-size:3rem}article{border-top:1px solid #d5c7b7;padding:16px 0}small{color:#75685c}.pill{display:inline-block;border:1px solid #c9b9a7;border-radius:999px;padding:2px 7px;font-size:.75rem}nav a{margin-right:12px}'
    parts=['<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+' · Seeker chronicle</title><style>'+style+'</style><h1>'+title+'</h1><p>'+html.escape(str(camp.get('description') or ''))+'</p><nav><a href="#sessions">Sessions</a><a href="#characters">Characters</a><a href="#objectives">Objectives</a><a href="#discoveries">Discoveries</a></nav>']
    parts.append('<h2 id="characters">Characters & milestones</h2>')
    by_char={int(c['id']):[] for c in chars}
    for m in milestones:by_char.setdefault(int(m['character_id']),[]).append(m)
    for c in chars:
        parts.append('<article><h3>'+html.escape(str(c.get('name') or ''))+'</h3><p>'+html.escape(str(c.get('summary') or ''))+'</p>')
        for m in by_char.get(int(c['id']),[]):
            parts.append('<p><span class="pill">Milestone</span> <b>'+html.escape(str(m.get('label') or ''))+'</b> — '+html.escape(str(m.get('note') or ''))+'</p>')
        parts.append('</article>')
    parts.append('<h2 id="sessions">Sessions</h2>'+''.join('<article><small>'+html.escape(str(x.get('session_date') or ''))+'</small><h3>'+html.escape(str(x.get('title') or 'Session'))+'</h3><p>'+html.escape(str(x.get('summary') or ''))+'</p></article>' for x in sessions))
    parts.append('<h2 id="objectives">Objectives</h2>'+''.join('<article><b>'+html.escape(str(x.get('title') or ''))+'</b> <span class="pill">'+html.escape(str(x.get('status') or ''))+'</span><p>'+html.escape(str(x.get('body') or ''))+'</p></article>' for x in objs))
    parts.append('<h2 id="discoveries">Atlas discoveries & travel</h2>'+''.join('<article><b>'+html.escape(str(x.get('title') or ''))+'</b> — '+html.escape(str(x.get('state') or ''))+'</article>' for x in disc)+''.join('<article><b>'+html.escape(str(x.get('from_label') or ''))+' → '+html.escape(str(x.get('to_label') or ''))+'</b><p>'+html.escape(str(x.get('map_name') or ''))+' · '+html.escape(str(x.get('note') or ''))+'</p></article>' for x in travel))
    parts.append('<h2>Mysteries</h2>'+''.join('<article><b>'+html.escape(str(x.get('title') or ''))+'</b> <span class="pill">'+html.escape(str(x.get('status') or ''))+'</span><p>'+html.escape(str(x.get('description') or ''))+'</p></article>' for x in mysteries))
    parts.append('<h2>Party notes</h2>'+''.join('<article><small>'+html.escape(str(x.get('author_label') or 'Party'))+'</small><p>'+html.escape(str(x.get('body') or ''))+'</p></article>' for x in party_notes))
    parts.append('<h2>Handouts</h2>'+''.join('<article><h3>'+html.escape(str(x.get('title') or 'Handout'))+'</h3><p>'+html.escape(str(x.get('body') or ''))+'</p></article>' for x in handouts))
    parts.append('<h2>Campaign clocks</h2>'+''.join('<article><b>'+html.escape(str(x.get('title') or ''))+'</b> — '+str(int(x.get('current_segments') or 0))+'/'+str(int(x.get('total_segments') or 0))+'<p>'+html.escape(str(x.get('description') or ''))+'</p></article>' for x in clocks))
    manifest={'format':'seeker-keepsake-v2','campaign':camp,'sessions':sessions,'characters':chars,'milestones':milestones,'objectives':objs,'discoveries':disc,'travel':travel,'mysteries':mysteries,'party_notes':party_notes,'handouts':handouts,'clocks':clocks,'session_media':media,'created_at':time.time()}
    def local_asset(ref: str):
        raw=str(ref or '').strip(); candidates=[]
        if raw.startswith('/uploads/'):candidates.append((settings.uploads_dir/raw[len('/uploads/'):], 'assets/uploads/'+raw[len('/uploads/'):],settings.uploads_dir))
        elif raw.startswith('upload:'):candidates.append((settings.uploads_dir/raw[len('upload:'):], 'assets/uploads/'+raw[len('upload:'):],settings.uploads_dir))
        elif raw.startswith('/project-asset/'):candidates.append((settings.project_dir/raw[len('/project-asset/'):], 'assets/project/'+raw[len('/project-asset/'):],settings.project_dir))
        elif raw.startswith('project:'):candidates.append((settings.project_dir/raw[len('project:'):], 'assets/project/'+raw[len('project:'):],settings.project_dir))
        for path,arc,base in candidates:
            try:
                path=path.resolve();base=base.resolve()
                if path.is_file() and base in path.parents:return path,arc
            except Exception:pass
        return None
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as z:
        z.writestr('campaign-chronicle.html',''.join(parts));z.writestr('campaign-data.json',json.dumps(manifest,indent=2,ensure_ascii=False))
        seen=set();refs=[]
        for h in handouts:refs.append(str(h.get('image_ref') or ''))
        for m in media:refs.append(str(m.get('source_url') or ''))
        for c in chars:refs += [str(c.get('portrait_path') or ''),str(c.get('banner_path') or ''),str(c.get('portrait_url') or '')]
        for ref in refs:
            found=local_asset(ref)
            if found and found[1] not in seen:
                seen.add(found[1]);z.write(found[0],found[1])
    return out

def create_backup(settings: Settings, label: str='Manual backup', kind: str='manual') -> dict:
    with _BACKUP_LOCK:
        folder=settings.history_dir/'backups';folder.mkdir(parents=True,exist_ok=True)
        stamp=time.strftime('%Y%m%d-%H%M%S');path=folder/f'{stamp}-{kind}.zip';create_portable_archive(settings,path)
        size=path.stat().st_size
        with connect(settings) as conn:
            rid=int(conn.execute('INSERT INTO v6_backup_catalog(label,path,kind,size_bytes,created_at) VALUES(?,?,?,?,?)',(str(label)[:300],str(path),str(kind)[:40],size,time.time())).lastrowid)
        return _row(settings,'SELECT * FROM v6_backup_catalog WHERE id=?',(rid,)) or {}


def list_backups(settings: Settings) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM v6_backup_catalog ORDER BY created_at DESC,id DESC')
    return [r for r in rows if Path(str(r.get('path') or '')).exists()]


def prune_backups(settings: Settings, keep_auto: int=7) -> None:
    with connect(settings) as conn:
        autos=[dict(r) for r in conn.execute("SELECT * FROM v6_backup_catalog WHERE kind='auto' ORDER BY created_at DESC,id DESC").fetchall()]
        for r in autos[max(1,int(keep_auto)):]:
            Path(str(r['path'])).unlink(missing_ok=True);conn.execute('DELETE FROM v6_backup_catalog WHERE id=?',(int(r['id']),))


def maybe_auto_backup(settings: Settings, max_age_hours: float=24.0) -> dict | None:
    if os.getenv('SEEKER_AUTO_BACKUPS','1').lower() not in {'1','true','yes','on'}:
        return None
    latest=_row(settings,"SELECT * FROM v6_backup_catalog WHERE kind='auto' ORDER BY created_at DESC,id DESC LIMIT 1")
    if latest and time.time()-float(latest.get('created_at') or 0) < max_age_hours*3600:
        return None
    result=create_backup(settings,'Automatic rolling backup','auto');prune_backups(settings,int(os.getenv('SEEKER_AUTO_BACKUPS_KEEP','7') or 7));return result


def delete_backup(settings: Settings, backup_id: int) -> None:
    row=_row(settings,'SELECT * FROM v6_backup_catalog WHERE id=?',(int(backup_id),))
    if not row:return
    Path(str(row.get('path') or '')).unlink(missing_ok=True)
    with connect(settings) as conn:conn.execute('DELETE FROM v6_backup_catalog WHERE id=?',(int(backup_id),))


def restore_backup(settings: Settings, backup_id: int) -> dict:
    row=_row(settings,'SELECT * FROM v6_backup_catalog WHERE id=?',(int(backup_id),))
    if not row or not Path(str(row.get('path') or '')).exists(): raise ValueError('Backup not found.')
    path=Path(str(row['path']));validate_portable_archive_file(path);temp=Path(tempfile.mkdtemp(prefix='seeker-v6-restore-'))
    try:
        with zipfile.ZipFile(path,'r') as z:
            for info in z.infolist():
                pp=Path(info.filename)
                if pp.is_absolute() or '..' in pp.parts: raise ValueError('Unsafe backup path.')
            z.extractall(temp)
        db=temp/'loreforge.db';project=temp/'project';uploads=temp/'uploads'
        if not db.exists(): raise ValueError('Backup database is missing.')
        # Preserve a last-chance backup before mutating the live volume.
        safety=settings.history_dir/'backups'/f"{time.strftime('%Y%m%d-%H%M%S')}-pre-restore.zip"
        create_portable_archive(settings,safety)
        new_project=settings.data_dir/'.v6-restore-project';new_uploads=settings.data_dir/'.v6-restore-uploads'
        old_project=settings.data_dir/'.v6-old-project';old_uploads=settings.data_dir/'.v6-old-uploads'
        for d in (new_project,new_uploads,old_project,old_uploads): shutil.rmtree(d,ignore_errors=True)
        if project.exists(): shutil.copytree(project,new_project)
        else: new_project.mkdir(parents=True,exist_ok=True)
        if uploads.exists(): shutil.copytree(uploads,new_uploads)
        else: new_uploads.mkdir(parents=True,exist_ok=True)
        if settings.project_dir.exists(): settings.project_dir.rename(old_project)
        new_project.rename(settings.project_dir)
        if settings.uploads_dir.exists(): settings.uploads_dir.rename(old_uploads)
        new_uploads.rename(settings.uploads_dir)
        try:
            src=sqlite3.connect(db);dst=sqlite3.connect(settings.db_path);src.backup(dst);dst.close();src.close()
        except Exception:
            shutil.rmtree(settings.project_dir,ignore_errors=True);old_project.rename(settings.project_dir)
            shutil.rmtree(settings.uploads_dir,ignore_errors=True);old_uploads.rename(settings.uploads_dir)
            raise
        shutil.rmtree(old_project,ignore_errors=True);shutil.rmtree(old_uploads,ignore_errors=True)
        return {'ok':True,'restored':int(backup_id),'safety_backup':str(safety)}
    finally:
        shutil.rmtree(temp,ignore_errors=True)
