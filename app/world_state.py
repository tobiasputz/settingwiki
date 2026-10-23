"""Source-safe, campaign-scoped world consequences and session context.

Events are private drafts by default. Publishing requires explicit player-safe
copy; the player projection NEVER includes GM titles, notes or object links.
This is an additive companion to the existing Seeker timeline/chronicle.
"""
from __future__ import annotations

import json
import time
from typing import Any
from .config import Settings
from .storage import connect
from .v7 import get_entity

SCHEMA = '''
CREATE TABLE IF NOT EXISTS world_consequences (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 campaign_id INTEGER NOT NULL,
 session_id INTEGER,
 entity_id INTEGER,
 map_id INTEGER,
 marker_id INTEGER,
 kind TEXT NOT NULL DEFAULT 'event',
 title TEXT NOT NULL,
 gm_notes TEXT NOT NULL DEFAULT '',
 player_title TEXT NOT NULL DEFAULT '',
 player_summary TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'draft',
 occurred_at REAL NOT NULL,
 created_at REAL NOT NULL,
 updated_at REAL NOT NULL,
 FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL,
 FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE SET NULL,
 FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE SET NULL,
 FOREIGN KEY(marker_id) REFERENCES markers(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_world_consequences_campaign ON world_consequences(campaign_id,occurred_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_world_consequences_session ON world_consequences(campaign_id,session_id);
CREATE INDEX IF NOT EXISTS idx_world_consequences_entity ON world_consequences(campaign_id,entity_id);
CREATE INDEX IF NOT EXISTS idx_world_consequences_map ON world_consequences(campaign_id,map_id,marker_id);
'''
KINDS = {'event','discovery','consequence','travel','quest','relationship'}
STATES = {'draft','published','archived'}


def init_world_state_db(settings: Settings):
    with connect(settings) as conn:
        conn.executescript(SCHEMA)
        # Installation on old campaigns is additive and does not migrate/delete data.
        conn.execute("INSERT OR IGNORE INTO seeker_schema_migrations(version,description,applied_at) VALUES(?,?,?)",
                     ('10.3-world', 'Player-safe campaign consequence ledger', time.time()))


def _single(settings, statement, args=()):
    with connect(settings) as conn:
        row = conn.execute(statement, args).fetchone()
    return dict(row) if row else None


def _id(value, label):
    if value in ('', None):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'Invalid {label}.')
    if result < 1:
        raise ValueError(f'Invalid {label}.')
    return result


def _validate_links(settings, campaign_id: int, session_id, entity_id, map_id, marker_id):
    if session_id is not None and not _single(settings,'SELECT id FROM campaign_sessions WHERE id=? AND campaign_id=?',(session_id,campaign_id)):
        raise ValueError('That session is not part of the current campaign.')
    if entity_id is not None and get_entity(settings,campaign_id,entity_id) is None:
        raise ValueError('That campaign object is unavailable.')
    if map_id is not None and not _single(settings,'SELECT id FROM maps WHERE id=?',(map_id,)):
        raise ValueError('Map not found.')
    if marker_id is not None:
        marker = _single(settings,'SELECT id,map_id FROM markers WHERE id=?',(marker_id,))
        if not marker or (map_id is not None and marker['map_id'] != map_id):
            raise ValueError('Location marker is not on that map.')
        if map_id is None:
            map_id = marker['map_id']
    return map_id


def write_event(settings: Settings, campaign_id: int, data: dict[str,Any], *, event_id: int | None = None) -> dict:
    existing = None
    if event_id is not None:
        existing = _single(settings,'SELECT * FROM world_consequences WHERE id=? AND campaign_id=?',(event_id,campaign_id))
        if not existing: raise ValueError('Campaign event not found.')
    def field(name,default=None):
        return data[name] if name in data else (existing[name] if existing else default)
    sid=_id(field('session_id'),'session')
    eid=_id(field('entity_id'),'entity')
    mid=_id(field('map_id'),'map')
    marker=_id(field('marker_id'),'marker')
    mid=_validate_links(settings,campaign_id,sid,eid,mid,marker)
    title=str(field('title','') or '').strip()[:180]
    if not title: raise ValueError('An event title is required.')
    notes=str(field('gm_notes','') or '')[:12000]
    public_title=str(field('player_title','') or '').strip()[:180]
    public_summary=str(field('player_summary','') or '').strip()[:4000]
    kind=str(field('kind','event') or 'event').strip()
    if kind not in KINDS: raise ValueError('Unknown event type.')
    status=str(field('status','draft') or 'draft').strip()
    if status not in STATES: raise ValueError('Unknown publication state.')
    if status=='published':
        if not public_title or not public_summary:
            raise ValueError('Provide separate player-safe title and summary before publication.')
        changed_public = (not existing or existing['status']!='published' or
                          existing['player_title']!=public_title or existing['player_summary']!=public_summary)
        if changed_public and not bool(data.get('confirm_publish')):
            raise ValueError('Publication requires explicit confirmation.')
    if existing and data.get('expected_updated_at') is not None:
        if abs(float(data['expected_updated_at'])-float(existing['updated_at']))>0.00001:
            raise ValueError('Someone else updated this event. Reload it before saving.')
    try: occurred=float(field('occurred_at',time.time()))
    except (TypeError,ValueError): raise ValueError('Invalid event date.')
    if not 0 < occurred < 32503680000: raise ValueError('Event date out of bounds.')
    now=time.time()
    args=(sid,eid,mid,marker,kind,title,notes,public_title,public_summary,status,occurred,now)
    with connect(settings) as conn:
        if existing:
            conn.execute('''UPDATE world_consequences SET session_id=?,entity_id=?,map_id=?,marker_id=?,kind=?,title=?,gm_notes=?,player_title=?,player_summary=?,status=?,occurred_at=?,updated_at=? WHERE id=? AND campaign_id=?''',args+(event_id,campaign_id))
            new_id=event_id
        else:
            row=conn.execute('''INSERT INTO world_consequences(campaign_id,session_id,entity_id,map_id,marker_id,kind,title,gm_notes,player_title,player_summary,status,occurred_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(campaign_id,)+args[:-1]+(now,now))
            new_id=row.lastrowid
    return _single(settings,'SELECT * FROM world_consequences WHERE id=? AND campaign_id=?',(new_id,campaign_id))


def events_for_gm(settings: Settings,campaign_id: int,*,session_id: int|None=None,entity_id: int|None=None,map_id: int|None=None,marker_id: int|None=None,limit: int=100) -> list[dict]:
    conditions=['c.campaign_id=?'];args=[campaign_id]
    for column,value in [('session_id',session_id),('entity_id',entity_id),('map_id',map_id),('marker_id',marker_id)]:
        if value is not None:
            conditions.append('c.'+column+'=?');args.append(int(value))
    args.append(max(1,min(int(limit),200)))
    sql='''SELECT c.*,e.name AS entity_name,s.title AS session_title,m.name AS map_name,m.slug AS map_slug,k.title AS marker_title
             FROM world_consequences c
             LEFT JOIN v7_entities e ON e.id=c.entity_id AND e.campaign_id=c.campaign_id
             LEFT JOIN campaign_sessions s ON s.id=c.session_id AND s.campaign_id=c.campaign_id
             LEFT JOIN maps m ON m.id=c.map_id
             LEFT JOIN markers k ON k.id=c.marker_id AND k.map_id=c.map_id
             WHERE '''+' AND '.join(conditions)+' ORDER BY c.occurred_at DESC,c.id DESC LIMIT ?'
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(sql,tuple(args))]


def events_for_player(settings:Settings,campaign_id:int,*,limit:int=40) -> list[dict]:
    """Strict allowlist: GM-only text and association IDs never leave this function."""
    with connect(settings) as conn:
        rows=conn.execute('''SELECT id,kind,player_title,player_summary,occurred_at
                             FROM world_consequences WHERE campaign_id=? AND status='published'
                             AND player_title<>'' AND player_summary<>''
                             ORDER BY occurred_at DESC,id DESC LIMIT ?''',(campaign_id,max(1,min(limit,80)))).fetchall()
    return [{'id':r['id'],'kind':r['kind'],'title':r['player_title'],'summary':r['player_summary'],
             'occurred_at':r['occurred_at']} for r in rows]
