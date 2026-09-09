from __future__ import annotations

import json
import time
from typing import Any

from .config import Settings
from .storage import connect

V5_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS player_follows (
    campaign_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'page',
    target_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,invite_id,target_type,target_key),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v5_follows_target ON player_follows(campaign_id,target_type,target_key,invite_id);

CREATE TABLE IF NOT EXISTS party_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER,
    invite_id INTEGER,
    author_label TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v5_party_notes_session ON party_notes(campaign_id,session_id,updated_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS investigation_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'note',
    target_key TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    x REAL NOT NULL DEFAULT 0.5,
    y REAL NOT NULL DEFAULT 0.5,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v5_investigation_owner ON investigation_nodes(campaign_id,invite_id,updated_at DESC);
CREATE TABLE IF NOT EXISTS investigation_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES investigation_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(target_id) REFERENCES investigation_nodes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v5_investigation_edges_owner ON investigation_edges(campaign_id,invite_id);

CREATE TABLE IF NOT EXISTS campaign_objectives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    kind TEXT NOT NULL DEFAULT 'party',
    creator_invite_id INTEGER,
    creator_label TEXT NOT NULL DEFAULT '',
    linked_type TEXT NOT NULL DEFAULT '',
    linked_key TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(creator_invite_id) REFERENCES player_invites(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v5_objectives_campaign ON campaign_objectives(campaign_id,status,updated_at DESC);

CREATE TABLE IF NOT EXISTS character_milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    session_id INTEGER,
    label TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v5_character_milestones ON character_milestones(character_id,created_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS session_rsvps (
    session_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'maybe',
    note TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL,
    PRIMARY KEY(session_id,invite_id),
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v5_rsvps_session ON session_rsvps(session_id,status,invite_id);

CREATE TABLE IF NOT EXISTS session_preparations (
    session_id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    opening TEXT NOT NULL DEFAULT '',
    beats_json TEXT NOT NULL DEFAULT '[]',
    secrets TEXT NOT NULL DEFAULT '',
    contingencies TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    references_json TEXT NOT NULL DEFAULT '[]',
    updated_at REAL NOT NULL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v5_session_preps_campaign ON session_preparations(campaign_id,updated_at DESC);

CREATE TABLE IF NOT EXISTS campaign_map_discoveries (
    campaign_id INTEGER NOT NULL,
    marker_id INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'discovered',
    first_session_id INTEGER,
    updated_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,marker_id),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(marker_id) REFERENCES markers(id) ON DELETE CASCADE,
    FOREIGN KEY(first_session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v5_map_discoveries_campaign ON campaign_map_discoveries(campaign_id,state,marker_id);

CREATE TABLE IF NOT EXISTS campaign_fog_reveals (
    campaign_id INTEGER NOT NULL,
    fog_region_id INTEGER NOT NULL,
    revealed INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,fog_region_id),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(fog_region_id) REFERENCES map_fog_regions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS player_notification_prefs (
    invite_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL,
    PRIMARY KEY(invite_id,kind),
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
'''


def init_v5_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(V5_SCHEMA)
        # V5 keeps character sheets deliberately narrative. Preserve v4's JSON
        # rather than deleting it so a rollback never loses player data.
        cols={r[1] for r in conn.execute("PRAGMA table_info(player_characters)").fetchall()}
        if "external_sheet_url" not in cols:
            conn.execute("ALTER TABLE player_characters ADD COLUMN external_sheet_url TEXT NOT NULL DEFAULT ''")
        if "foundry_actor_url" not in cols:
            conn.execute("ALTER TABLE player_characters ADD COLUMN foundry_actor_url TEXT NOT NULL DEFAULT ''")


def _json(raw: Any, default: Any):
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw or "")
    except Exception:
        return default


def list_follows(settings: Settings, invite_id: int, campaign_id: int) -> list[dict]:
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM player_follows WHERE invite_id=? AND campaign_id=? ORDER BY created_at DESC",
            (int(invite_id), int(campaign_id)),
        ).fetchall()]


def set_follow(settings: Settings, invite_id: int, campaign_id: int, target_type: str, target_key: str, enabled: bool, label: str='') -> bool:
    t=str(target_type or 'page')[:40]; k=str(target_key or '')[:500]
    if not k: raise ValueError('A follow target is required.')
    with connect(settings) as conn:
        if enabled:
            conn.execute("INSERT OR REPLACE INTO player_follows(campaign_id,invite_id,target_type,target_key,label,created_at) VALUES(?,?,?,?,?,?)",
                         (int(campaign_id),int(invite_id),t,k,str(label or '')[:300],time.time()))
        else:
            conn.execute("DELETE FROM player_follows WHERE campaign_id=? AND invite_id=? AND target_type=? AND target_key=?",
                         (int(campaign_id),int(invite_id),t,k))
    return bool(enabled)


def followers_for_target(settings: Settings, campaign_id: int, target_type: str, target_key: str) -> list[int]:
    with connect(settings) as conn:
        return [int(r[0]) for r in conn.execute(
            "SELECT invite_id FROM player_follows WHERE campaign_id=? AND target_type=? AND target_key=?",
            (int(campaign_id),str(target_type),str(target_key)),
        ).fetchall()]


def list_party_notes(settings: Settings, campaign_id: int, session_id: int | None, limit: int=100) -> list[dict]:
    params=[int(campaign_id)]; where="campaign_id=?"
    if session_id is None:
        where += " AND session_id IS NULL"
    else:
        where += " AND session_id=?"; params.append(int(session_id))
    params.append(max(1,min(int(limit),300)))
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM party_notes WHERE {where} ORDER BY updated_at DESC,id DESC LIMIT ?", tuple(params)
        ).fetchall()]


def save_party_note(settings: Settings, campaign_id: int, session_id: int|None, invite_id: int|None, author_label: str, body: str, note_id: int|None=None, admin: bool=False) -> dict:
    text=str(body or '').strip()
    if not text: raise ValueError('Write something before saving the note.')
    if len(text)>12000: raise ValueError('Party notes are limited to 12,000 characters.')
    now=time.time(); cid=int(campaign_id); iid=int(invite_id) if invite_id is not None else None
    with connect(settings) as conn:
        if session_id is not None:
            s=conn.execute("SELECT campaign_id FROM campaign_sessions WHERE id=?",(int(session_id),)).fetchone()
            if not s or int(s['campaign_id'] or 0)!=cid: raise ValueError('Session does not belong to this campaign.')
        if note_id:
            row=conn.execute("SELECT * FROM party_notes WHERE id=? AND campaign_id=?",(int(note_id),cid)).fetchone()
            if not row: raise ValueError('Party note not found.')
            if not admin and int(row['invite_id'] or -1)!=int(iid or -2): raise PermissionError('You can only edit your own party notes.')
            conn.execute("UPDATE party_notes SET body=?,updated_at=? WHERE id=?",(text,now,int(note_id))); out=int(note_id)
        else:
            out=int(conn.execute("INSERT INTO party_notes(campaign_id,session_id,invite_id,author_label,body,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                                 (cid,int(session_id) if session_id is not None else None,iid,str(author_label or 'Player')[:160],text,now,now)).lastrowid)
        return dict(conn.execute("SELECT * FROM party_notes WHERE id=?",(out,)).fetchone())


def delete_party_note(settings: Settings, note_id: int, invite_id: int|None, admin: bool=False) -> None:
    with connect(settings) as conn:
        row=conn.execute("SELECT invite_id FROM party_notes WHERE id=?",(int(note_id),)).fetchone()
        if not row: return
        if not admin and int(row['invite_id'] or -1)!=int(invite_id or -2): raise PermissionError('You can only delete your own party notes.')
        conn.execute("DELETE FROM party_notes WHERE id=?",(int(note_id),))


def investigation_board(settings: Settings, campaign_id: int, invite_id: int) -> dict:
    cid=int(campaign_id); iid=int(invite_id)
    with connect(settings) as conn:
        nodes=[dict(r) for r in conn.execute("SELECT * FROM investigation_nodes WHERE campaign_id=? AND invite_id=? ORDER BY id",(cid,iid)).fetchall()]
        edges=[dict(r) for r in conn.execute("SELECT * FROM investigation_edges WHERE campaign_id=? AND invite_id=? ORDER BY id",(cid,iid)).fetchall()]
    return {'nodes':nodes,'edges':edges}


def save_investigation_node(settings: Settings, campaign_id: int, invite_id: int, payload: dict) -> dict:
    cid=int(campaign_id);iid=int(invite_id);nid=payload.get('id');now=time.time()
    node_type=str(payload.get('node_type') or 'note')[:40];target=str(payload.get('target_key') or '')[:500]
    title=str(payload.get('title') or 'Untitled clue').strip()[:300];note=str(payload.get('note') or '')[:8000]
    x=max(0.02,min(.98,float(payload.get('x',.5) or .5)));y=max(0.02,min(.98,float(payload.get('y',.5) or .5)))
    with connect(settings) as conn:
        if nid:
            row=conn.execute("SELECT 1 FROM investigation_nodes WHERE id=? AND campaign_id=? AND invite_id=?",(int(nid),cid,iid)).fetchone()
            if not row: raise PermissionError('Investigation card not found.')
            conn.execute("UPDATE investigation_nodes SET node_type=?,target_key=?,title=?,note=?,x=?,y=?,updated_at=? WHERE id=?",
                         (node_type,target,title,note,x,y,now,int(nid))); out=int(nid)
        else:
            out=int(conn.execute("INSERT INTO investigation_nodes(campaign_id,invite_id,node_type,target_key,title,note,x,y,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                 (cid,iid,node_type,target,title,note,x,y,now,now)).lastrowid)
        return dict(conn.execute("SELECT * FROM investigation_nodes WHERE id=?",(out,)).fetchone())


def delete_investigation_node(settings: Settings, node_id: int, campaign_id: int, invite_id: int) -> None:
    with connect(settings) as conn:
        conn.execute("DELETE FROM investigation_nodes WHERE id=? AND campaign_id=? AND invite_id=?",(int(node_id),int(campaign_id),int(invite_id)))


def save_investigation_edge(settings: Settings, campaign_id: int, invite_id: int, payload: dict) -> dict:
    cid=int(campaign_id);iid=int(invite_id);src=int(payload.get('source_id') or 0);dst=int(payload.get('target_id') or 0)
    if not src or not dst or src==dst: raise ValueError('Choose two different cards to connect.')
    label=str(payload.get('label') or '')[:300];now=time.time()
    with connect(settings) as conn:
        owned=conn.execute("SELECT COUNT(*) FROM investigation_nodes WHERE campaign_id=? AND invite_id=? AND id IN (?,?)",(cid,iid,src,dst)).fetchone()[0]
        if int(owned)!=2: raise PermissionError('You can only connect cards on your own board.')
        eid=int(conn.execute("INSERT INTO investigation_edges(campaign_id,invite_id,source_id,target_id,label,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                             (cid,iid,src,dst,label,now,now)).lastrowid)
        return dict(conn.execute("SELECT * FROM investigation_edges WHERE id=?",(eid,)).fetchone())


def delete_investigation_edge(settings: Settings, edge_id: int, campaign_id: int, invite_id: int) -> None:
    with connect(settings) as conn:
        conn.execute("DELETE FROM investigation_edges WHERE id=? AND campaign_id=? AND invite_id=?",(int(edge_id),int(campaign_id),int(invite_id)))


def list_objectives(settings: Settings, campaign_id: int, *, include_done: bool=True) -> list[dict]:
    sql="SELECT * FROM campaign_objectives WHERE campaign_id=?"
    if not include_done: sql += " AND status IN ('active','hold')"
    sql += " ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'hold' THEN 1 WHEN 'completed' THEN 2 ELSE 3 END, updated_at DESC,id DESC"
    with connect(settings) as conn:return [dict(r) for r in conn.execute(sql,(int(campaign_id),)).fetchall()]


def save_objective(settings: Settings, campaign_id: int, payload: dict, invite_id: int|None, creator_label: str, admin: bool=False) -> dict:
    cid=int(campaign_id);oid=payload.get('id');now=time.time();status=str(payload.get('status') or 'active').lower()
    if status not in {'active','hold','completed','failed'}: status='active'
    title=str(payload.get('title') or '').strip()[:300]
    if not title: raise ValueError('Objective title is required.')
    body=str(payload.get('body') or '')[:8000]; kind=str(payload.get('kind') or 'party')[:40]
    linked_type=str(payload.get('linked_type') or '')[:40];linked_key=str(payload.get('linked_key') or '')[:500]
    with connect(settings) as conn:
        if oid:
            row=conn.execute("SELECT * FROM campaign_objectives WHERE id=? AND campaign_id=?",(int(oid),cid)).fetchone()
            if not row: raise ValueError('Objective not found.')
            if not admin and row['creator_invite_id'] is not None and int(row['creator_invite_id'])!=int(invite_id or -1):
                raise PermissionError('Only the creator or GM can edit this objective.')
            conn.execute("UPDATE campaign_objectives SET title=?,body=?,status=?,kind=?,linked_type=?,linked_key=?,updated_at=? WHERE id=?",
                         (title,body,status,kind,linked_type,linked_key,now,int(oid)));out=int(oid)
        else:
            out=int(conn.execute("INSERT INTO campaign_objectives(campaign_id,title,body,status,kind,creator_invite_id,creator_label,linked_type,linked_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 (cid,title,body,status,kind,int(invite_id) if invite_id is not None else None,str(creator_label or 'GM')[:160],linked_type,linked_key,now,now)).lastrowid)
        return dict(conn.execute("SELECT * FROM campaign_objectives WHERE id=?",(out,)).fetchone())


def delete_objective(settings: Settings, objective_id: int, invite_id: int|None, admin: bool=False) -> None:
    with connect(settings) as conn:
        row=conn.execute("SELECT creator_invite_id FROM campaign_objectives WHERE id=?",(int(objective_id),)).fetchone()
        if not row:return
        if not admin and row['creator_invite_id'] is not None and int(row['creator_invite_id'])!=int(invite_id or -1):raise PermissionError('Only the creator or GM can delete this objective.')
        conn.execute("DELETE FROM campaign_objectives WHERE id=?",(int(objective_id),))


def character_milestones(settings: Settings, character_id: int) -> list[dict]:
    with connect(settings) as conn:
        rows=[dict(r) for r in conn.execute("SELECT m.*,s.session_number,s.title AS session_title FROM character_milestones m LEFT JOIN campaign_sessions s ON s.id=m.session_id WHERE m.character_id=? ORDER BY m.created_at DESC,m.id DESC",(int(character_id),)).fetchall()]
    for r in rows:r['snapshot']=_json(r.pop('snapshot_json','{}'),{})
    return rows


def save_character_milestone(settings: Settings, character: dict, label: str, note: str='', session_id: int|None=None) -> dict:
    snapshot={k:character.get(k) for k in ('name','pronouns','ancestry','class_name','level','status','summary','biography','goals','quote','portrait_url')}
    now=time.time()
    with connect(settings) as conn:
        mid=int(conn.execute("INSERT INTO character_milestones(character_id,session_id,label,note,snapshot_json,created_at) VALUES(?,?,?,?,?,?)",
                             (int(character['id']),int(session_id) if session_id else None,str(label or 'Milestone')[:300],str(note or '')[:8000],json.dumps(snapshot),now)).lastrowid)
        row=dict(conn.execute("SELECT * FROM character_milestones WHERE id=?",(mid,)).fetchone());row['snapshot']=_json(row.pop('snapshot_json','{}'),{});return row


def delete_character_milestone(settings: Settings, milestone_id: int, character_id: int) -> None:
    with connect(settings) as conn:conn.execute("DELETE FROM character_milestones WHERE id=? AND character_id=?",(int(milestone_id),int(character_id)))


def save_rsvp(settings: Settings, session_id: int, invite_id: int, status: str, note: str='') -> dict:
    st=str(status or 'maybe').lower()
    if st not in {'going','maybe','cant'}: raise ValueError('RSVP must be going, maybe, or cant.')
    now=time.time()
    with connect(settings) as conn:
        session=conn.execute("SELECT id,campaign_id FROM campaign_sessions WHERE id=?",(int(session_id),)).fetchone()
        if not session: raise ValueError('Session not found.')
        member=conn.execute("SELECT 1 FROM campaign_memberships WHERE campaign_id=? AND invite_id=?",(int(session['campaign_id']),int(invite_id))).fetchone()
        if not member: raise PermissionError('You are not a member of this campaign.')
        conn.execute("INSERT OR REPLACE INTO session_rsvps(session_id,invite_id,status,note,updated_at) VALUES(?,?,?,?,?)",
                     (int(session_id),int(invite_id),st,str(note or '')[:1000],now))
        return dict(conn.execute("SELECT * FROM session_rsvps WHERE session_id=? AND invite_id=?",(int(session_id),int(invite_id))).fetchone())


def session_rsvps(settings: Settings, session_id: int) -> list[dict]:
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute("SELECT r.*,i.label FROM session_rsvps r JOIN player_invites i ON i.id=r.invite_id WHERE r.session_id=? ORDER BY i.label COLLATE NOCASE",(int(session_id),)).fetchall()]


def get_preparation(settings: Settings, session_id: int) -> dict:
    with connect(settings) as conn:
        row=conn.execute("SELECT * FROM session_preparations WHERE session_id=?",(int(session_id),)).fetchone()
    if not row:return {'session_id':int(session_id),'opening':'','beats':[],'secrets':'','contingencies':'','notes':'','references':[]}
    out=dict(row);out['beats']=_json(out.pop('beats_json','[]'),[]);out['references']=_json(out.pop('references_json','[]'),[]);return out


def save_preparation(settings: Settings, session_id: int, campaign_id: int, payload: dict) -> dict:
    beats=payload.get('beats') if isinstance(payload.get('beats'),list) else []
    clean_beats=[]
    for b in beats[:80]:
        if isinstance(b,dict):clean_beats.append({'title':str(b.get('title') or '')[:300],'note':str(b.get('note') or '')[:5000],'done':bool(b.get('done'))})
        elif str(b).strip():clean_beats.append({'title':str(b)[:300],'note':'','done':False})
    refs=payload.get('references') if isinstance(payload.get('references'),list) else []
    clean_refs=[]
    for r in refs[:120]:
        if isinstance(r,dict) and r.get('key'):
            clean_refs.append({'type':str(r.get('type') or 'page')[:40],'key':str(r.get('key'))[:500],'label':str(r.get('label') or r.get('key'))[:300]})
    now=time.time()
    with connect(settings) as conn:
        row=conn.execute("SELECT campaign_id FROM campaign_sessions WHERE id=?",(int(session_id),)).fetchone()
        if not row or int(row['campaign_id'] or 0)!=int(campaign_id): raise ValueError('Session does not belong to this campaign.')
        conn.execute("INSERT OR REPLACE INTO session_preparations(session_id,campaign_id,opening,beats_json,secrets,contingencies,notes,references_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (int(session_id),int(campaign_id),str(payload.get('opening') or '')[:12000],json.dumps(clean_beats),str(payload.get('secrets') or '')[:16000],str(payload.get('contingencies') or '')[:12000],str(payload.get('notes') or '')[:24000],json.dumps(clean_refs),now))
    return get_preparation(settings,session_id)


def list_prepared_sessions(settings: Settings, campaign_id: int) -> list[dict]:
    with connect(settings) as conn:
        rows=[dict(r) for r in conn.execute("""SELECT s.*,p.updated_at AS prep_updated_at
            FROM campaign_sessions s LEFT JOIN session_preparations p ON p.session_id=s.id
            WHERE s.campaign_id=? ORDER BY CASE s.status WHEN 'live' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END,
            COALESCE(NULLIF(s.session_date,''),'9999-99-99'),COALESCE(s.session_number,999999),s.id DESC""",(int(campaign_id),)).fetchall()]
    return rows


def map_discovery_states(settings: Settings, campaign_id: int, marker_ids: list[int]) -> dict[int,dict]:
    ids=[int(x) for x in marker_ids if x is not None]
    if not ids:return {}
    q=','.join('?' for _ in ids)
    with connect(settings) as conn:
        rows=conn.execute(f"SELECT * FROM campaign_map_discoveries WHERE campaign_id=? AND marker_id IN ({q})",(int(campaign_id),*ids)).fetchall()
    return {int(r['marker_id']):dict(r) for r in rows}


def set_map_discovery(settings: Settings, campaign_id: int, marker_id: int, state: str, session_id: int|None=None) -> dict:
    st=str(state or 'discovered').lower()
    if st not in {'unknown','rumored','discovered','visited'}:raise ValueError('Unknown discovery state.')
    now=time.time()
    with connect(settings) as conn:
        conn.execute("INSERT OR REPLACE INTO campaign_map_discoveries(campaign_id,marker_id,state,first_session_id,updated_at) VALUES(?,?,?,?,?)",
                     (int(campaign_id),int(marker_id),st,int(session_id) if session_id else None,now))
        return dict(conn.execute("SELECT * FROM campaign_map_discoveries WHERE campaign_id=? AND marker_id=?",(int(campaign_id),int(marker_id))).fetchone())


def campaign_fog_regions(settings: Settings, campaign_id: int, fog_rows: list[dict], *, admin: bool=False) -> list[dict]:
    if admin:return fog_rows
    ids=[int(r['id']) for r in fog_rows]
    if not ids:return []
    q=','.join('?' for _ in ids)
    with connect(settings) as conn:
        overrides={int(r['fog_region_id']):bool(r['revealed']) for r in conn.execute(f"SELECT fog_region_id,revealed FROM campaign_fog_reveals WHERE campaign_id=? AND fog_region_id IN ({q})",(int(campaign_id),*ids)).fetchall()}
    out=[]
    for row in fog_rows:
        revealed=overrides.get(int(row['id']),bool(row.get('revealed')))
        if not revealed:out.append(row)
    return out


def set_campaign_fog(settings: Settings, campaign_id: int, fog_region_id: int, revealed: bool) -> None:
    with connect(settings) as conn:
        conn.execute("INSERT OR REPLACE INTO campaign_fog_reveals(campaign_id,fog_region_id,revealed,updated_at) VALUES(?,?,?,?)",
                     (int(campaign_id),int(fog_region_id),1 if revealed else 0,time.time()))


def notification_prefs(settings: Settings, invite_id: int) -> dict[str,bool]:
    defaults={'reveal':True,'follow':True,'session':True,'handout':True,'comment':True,'spotlight':True,'notice':True}
    with connect(settings) as conn:
        for r in conn.execute("SELECT kind,enabled FROM player_notification_prefs WHERE invite_id=?",(int(invite_id),)).fetchall():defaults[str(r['kind'])]=bool(r['enabled'])
    return defaults


def set_notification_pref(settings: Settings, invite_id: int, kind: str, enabled: bool) -> dict[str,bool]:
    k=str(kind or 'notice')[:60]
    with connect(settings) as conn:
        conn.execute("INSERT OR REPLACE INTO player_notification_prefs(invite_id,kind,enabled,updated_at) VALUES(?,?,?,?)",(int(invite_id),k,1 if enabled else 0,time.time()))
    return notification_prefs(settings,invite_id)


def filter_notifications_for_prefs(settings: Settings, invite_id: int|None, rows: list[dict], admin: bool=False) -> list[dict]:
    if admin or invite_id is None:return rows
    prefs=notification_prefs(settings,int(invite_id))
    return [r for r in rows if prefs.get(str(r.get('kind') or 'notice'),True)]
