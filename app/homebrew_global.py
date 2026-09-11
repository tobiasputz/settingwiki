from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .config import Settings
from .storage import connect

GLOBAL_HOME_BREW_ID_BASE = 1_000_000_000

GLOBAL_HOME_BREW_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS global_homebrew_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'homebrew',
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT 'world',
    summary TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    origin_campaign_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_global_homebrew_kind_title ON global_homebrew_library(kind,lower(title),updated_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS global_homebrew_campaign_links (
    homebrew_id INTEGER NOT NULL,
    campaign_id INTEGER NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    last_used_at REAL,
    created_at REAL NOT NULL,
    PRIMARY KEY(homebrew_id,campaign_id),
    FOREIGN KEY(homebrew_id) REFERENCES global_homebrew_library(id) ON DELETE CASCADE,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
'''


def init_global_homebrew(settings: Settings, *, migrate: bool = True) -> None:
    with connect(settings) as conn:
        conn.executescript(GLOBAL_HOME_BREW_SCHEMA)
    if migrate:
        migrate_campaign_homebrew(settings)


def _j(raw: Any, default: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or '')
    except Exception:
        return default


def _looks_like_homebrew(kind: str, payload: dict) -> bool:
    kind = str(kind or '').strip().lower()
    if kind == 'homebrew':
        return True
    if kind not in {'item', 'feat', 'action'}:
        return False
    # Forge-created non-monster rules always carry at least one of these keys.
    return any(k in payload for k in (
        'homebrew_document', 'homebrew_publish', 'library_section', 'library_group',
        'source_linked', 'latex_exported', 'ancestry_trait', 'archetype_name', 'class_name',
    ))


def is_global_homebrew_payload(kind: str, payload: dict | None, item_id: int | None = None) -> bool:
    if item_id is not None and int(item_id or 0) >= GLOBAL_HOME_BREW_ID_BASE:
        return True
    return _looks_like_homebrew(kind, payload or {})


def external_id(global_id: int) -> int:
    return GLOBAL_HOME_BREW_ID_BASE + int(global_id)


def internal_id(item_id: int) -> int:
    value = int(item_id or 0)
    return value - GLOBAL_HOME_BREW_ID_BASE if value >= GLOBAL_HOME_BREW_ID_BASE else value


def _stable_key(kind: str, title: str, payload: dict) -> str:
    source = str(payload.get('source_link_path') or payload.get('latex_export_path') or '').replace('\\', '/').strip('/').casefold()
    document = str(payload.get('homebrew_document') or kind or '').strip().casefold()
    if source:
        return f'source:{source}|{document}'
    section = str(payload.get('library_section') or '').strip().casefold()
    group = str(payload.get('library_group') or payload.get('ancestry_trait') or payload.get('archetype_name') or '').strip().casefold()
    return f'name:{document}|{str(title or "").strip().casefold()}|{section}|{group}'


def _decorate(row: dict, campaign_id: int | None = None) -> dict:
    out = dict(row)
    gid = int(out['id'])
    out['global_homebrew_id'] = gid
    out['id'] = external_id(gid)
    out['scope'] = 'global'
    out['campaign_independent'] = True
    if campaign_id is not None:
        out['campaign_id'] = int(campaign_id)
    out['payload'] = _j(out.pop('payload_json', '{}'), {})
    out['payload']['global_homebrew_id'] = gid
    out['payload']['campaign_independent'] = True
    return out


def list_global_homebrew(settings: Settings, campaign_id: int | None = None) -> list[dict]:
    try:
        with connect(settings) as conn:
            rows = [dict(r) for r in conn.execute('SELECT * FROM global_homebrew_library ORDER BY updated_at DESC,id DESC').fetchall()]
    except Exception:
        return []
    return [_decorate(r, campaign_id) for r in rows]


def get_global_homebrew(settings: Settings, item_id: int, campaign_id: int | None = None) -> dict | None:
    gid = internal_id(item_id)
    try:
        with connect(settings) as conn:
            row = conn.execute('SELECT * FROM global_homebrew_library WHERE id=?', (gid,)).fetchone()
    except Exception:
        return None
    return _decorate(dict(row), campaign_id) if row else None


def save_global_homebrew(settings: Settings, payload: dict, campaign_id: int | None = None) -> dict:
    init_global_homebrew(settings, migrate=False)
    item_id = int(payload.get('id') or 0)
    gid = internal_id(item_id) if item_id else 0
    kind = str(payload.get('kind') or 'homebrew').strip().lower()
    title = str(payload.get('title') or '').strip()[:180]
    if not title:
        raise ValueError('A title is required.')
    target_type = str(payload.get('target_type') or 'world').strip().lower()
    if target_type not in {'world', 'actor'}:
        raise ValueError('target_type must be world or actor.')
    content = payload.get('payload') if isinstance(payload.get('payload'), dict) else {}
    content = dict(content)
    content['campaign_independent'] = True
    now = time.time()
    with connect(settings) as conn:
        if gid:
            exists = conn.execute('SELECT id FROM global_homebrew_library WHERE id=?', (gid,)).fetchone()
            if not exists:
                raise ValueError('Homebrew library entry not found.')
            conn.execute('''UPDATE global_homebrew_library SET kind=?,title=?,subtitle=?,target_type=?,summary=?,tags=?,payload_json=?,updated_at=? WHERE id=?''',
                         (kind, title, str(payload.get('subtitle') or '')[:180], target_type,
                          str(payload.get('summary') or '')[:8000], str(payload.get('tags') or '')[:400],
                          json.dumps(content, ensure_ascii=False), now, gid))
        else:
            cur = conn.execute('''INSERT INTO global_homebrew_library(uid,kind,title,subtitle,target_type,summary,tags,payload_json,origin_campaign_id,created_at,updated_at)
                                  VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                               (uuid.uuid4().hex, kind, title, str(payload.get('subtitle') or '')[:180], target_type,
                                str(payload.get('summary') or '')[:8000], str(payload.get('tags') or '')[:400],
                                json.dumps(content, ensure_ascii=False), int(campaign_id) if campaign_id else None, now, now))
            gid = int(cur.lastrowid or 0)
        if campaign_id:
            conn.execute('''INSERT INTO global_homebrew_campaign_links(homebrew_id,campaign_id,pinned,last_used_at,created_at) VALUES(?,?,?,?,?)
                            ON CONFLICT(homebrew_id,campaign_id) DO UPDATE SET last_used_at=excluded.last_used_at''',
                         (gid, int(campaign_id), 0, now, now))
    return get_global_homebrew(settings, external_id(gid), campaign_id) or {}


def delete_global_homebrew(settings: Settings, item_id: int) -> None:
    gid = internal_id(item_id)
    with connect(settings) as conn:
        conn.execute('DELETE FROM global_homebrew_library WHERE id=?', (gid,))


def touch_global_homebrew(settings: Settings, item_id: int, campaign_id: int, *, pinned: bool | None = None) -> None:
    gid = internal_id(item_id)
    now = time.time()
    with connect(settings) as conn:
        current = conn.execute('SELECT pinned FROM global_homebrew_campaign_links WHERE homebrew_id=? AND campaign_id=?', (gid, int(campaign_id))).fetchone()
        pin = int(pinned) if pinned is not None else int(current['pinned']) if current else 0
        conn.execute('''INSERT INTO global_homebrew_campaign_links(homebrew_id,campaign_id,pinned,last_used_at,created_at) VALUES(?,?,?,?,?)
                        ON CONFLICT(homebrew_id,campaign_id) DO UPDATE SET pinned=excluded.pinned,last_used_at=excluded.last_used_at''',
                     (gid, int(campaign_id), pin, now, now))


def migrate_campaign_homebrew(settings: Settings) -> dict:
    """Copy legacy campaign-scoped Forge rules into one global library.

    Legacy rows are retained for rollback safety but marked as migrated and hidden by
    the v6 adapter. This makes the migration reversible and prevents a deployment from
    destroying campaign data.
    """
    try:
        with connect(settings) as conn:
            # foundry_prepared_content might not exist in very old databases yet.
            rows = [dict(r) for r in conn.execute('SELECT * FROM foundry_prepared_content ORDER BY updated_at DESC,id DESC').fetchall()]
    except Exception:
        return {'migrated': 0, 'deduped': 0}
    candidates = []
    for row in rows:
        p = _j(row.get('payload_json'), {})
        if p.get('global_homebrew_id'):
            continue
        if _looks_like_homebrew(str(row.get('kind') or ''), p):
            candidates.append((row, p))
    migrated = deduped = 0
    for row, p in candidates:
        key = _stable_key(str(row.get('kind') or ''), str(row.get('title') or ''), p)
        with connect(settings) as conn:
            existing_rows = [dict(r) for r in conn.execute('SELECT * FROM global_homebrew_library').fetchall()]
        existing = None
        for er in existing_rows:
            ep = _j(er.get('payload_json'), {})
            if _stable_key(str(er.get('kind') or ''), str(er.get('title') or ''), ep) == key:
                existing = er
                break
        if existing:
            gid = int(existing['id']); deduped += 1
        else:
            saved = save_global_homebrew(settings, {
                'kind': row.get('kind'), 'title': row.get('title'), 'subtitle': row.get('subtitle'),
                'target_type': row.get('target_type'), 'summary': row.get('summary'), 'tags': row.get('tags'),
                'payload': p,
            }, int(row.get('campaign_id') or 0) or None)
            gid = int(saved.get('global_homebrew_id') or 0); migrated += 1
        if gid:
            p['global_homebrew_id'] = gid
            p['campaign_independent'] = True
            with connect(settings) as conn:
                conn.execute('UPDATE foundry_prepared_content SET payload_json=? WHERE id=?', (json.dumps(p, ensure_ascii=False), int(row['id'])))
                if row.get('campaign_id'):
                    now = time.time()
                    conn.execute('''INSERT OR IGNORE INTO global_homebrew_campaign_links(homebrew_id,campaign_id,pinned,last_used_at,created_at) VALUES(?,?,?,?,?)''',
                                 (gid, int(row['campaign_id']), 0, float(row.get('updated_at') or now), now))
    return {'migrated': migrated, 'deduped': deduped}
