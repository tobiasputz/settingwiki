from __future__ import annotations

import json
import random
import time
from typing import Any

from .config import Settings
from .storage import connect

V51_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS gm_scene_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    location_slug TEXT NOT NULL DEFAULT '',
    npc_slugs_json TEXT NOT NULL DEFAULT '[]',
    complication TEXT NOT NULL DEFAULT '',
    fallback TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ready',
    estimated_minutes INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v51_scenes_session ON gm_scene_cards(campaign_id,session_id,sort_order,id);

CREATE TABLE IF NOT EXISTS gm_clues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    source_session_id INTEGER,
    delivered_session_id INTEGER,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'not_found',
    linked_page_slug TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(source_session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL,
    FOREIGN KEY(delivered_session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v51_clues_campaign ON gm_clues(campaign_id,status,updated_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS gm_npc_cards (
    campaign_id INTEGER NOT NULL,
    page_slug TEXT NOT NULL,
    pronunciation TEXT NOT NULL DEFAULT '',
    voice TEXT NOT NULL DEFAULT '',
    mannerism TEXT NOT NULL DEFAULT '',
    motivation TEXT NOT NULL DEFAULT '',
    knows TEXT NOT NULL DEFAULT '',
    wants TEXT NOT NULL DEFAULT '',
    attitude TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,page_slug),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gm_session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'event',
    body TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_key TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v51_events_session ON gm_session_events(campaign_id,session_id,created_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS gm_consequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    source_session_id INTEGER,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    trigger_kind TEXT NOT NULL DEFAULT 'manual',
    trigger_value TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    target_type TEXT NOT NULL DEFAULT '',
    target_key TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(source_session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v51_consequences_campaign ON gm_consequences(campaign_id,status,updated_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS gm_clocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    current_segments INTEGER NOT NULL DEFAULT 0,
    total_segments INTEGER NOT NULL DEFAULT 6,
    visibility TEXT NOT NULL DEFAULT 'gm',
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v51_clocks_campaign ON gm_clocks(campaign_id,status,updated_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS gm_character_spotlights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    session_id INTEGER,
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v51_spotlights_character ON gm_character_spotlights(campaign_id,character_id,created_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS gm_prep_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v51_templates_campaign ON gm_prep_templates(campaign_id,name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS gm_random_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    entries_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v51_random_tables_campaign ON gm_random_tables(campaign_id,name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS gm_session_closeouts (
    session_id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    unresolved TEXT NOT NULL DEFAULT '',
    next_session_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
    FOREIGN KEY(next_session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
'''

BUILTIN_TEMPLATES = [
    {"key":"social","name":"Social pressure","description":"A negotiation, audience, interrogation, or tense reunion.","scenes":[
        {"title":"Arrival & temperature","purpose":"Establish what everyone wants before anyone bargains.","complication":"Someone has a reason not to speak plainly."},
        {"title":"The ask","purpose":"Put a concrete choice or price on the table.","fallback":"Move the useful information to a different speaker or consequence."},
        {"title":"Aftermath","purpose":"Record who gained leverage, trust, or a grudge."}]},
    {"key":"investigation","name":"Investigation","description":"Clues that can move between scenes when players take another route.","scenes":[
        {"title":"The visible problem","purpose":"Show the contradiction that demands investigation."},
        {"title":"Pressure & witnesses","purpose":"Let PCs choose where to pull; do not gate progress behind one roll."},
        {"title":"Revelation or complication","purpose":"Deliver enough truth to create a new decision."}]},
    {"key":"travel","name":"Travel & exploration","description":"A journey with discoveries, choices, and one memorable pressure point.","scenes":[
        {"title":"Departure","purpose":"State destination, stakes and what is changing while they travel."},
        {"title":"Road discovery","purpose":"Reveal setting texture or a useful clue."},
        {"title":"Complication","purpose":"Force a meaningful route/resource/social choice."},
        {"title":"Arrival","purpose":"Make the destination feel different from the expectation."}]},
    {"key":"dungeon","name":"Dangerous site","description":"A location-based session without scripting a linear route.","scenes":[
        {"title":"Threshold","purpose":"Signal theme, danger, and a choice of approach."},
        {"title":"Living obstacle","purpose":"A faction, creature, mechanism, or inhabitant with its own goal."},
        {"title":"Deep reveal","purpose":"Put the site's core secret somewhere the party can actually reach."},
        {"title":"Exit pressure","purpose":"Change the situation even if the party retreats."}]},
    {"key":"climax","name":"Climax / boss","description":"A high-pressure session with room for unexpected solutions.","scenes":[
        {"title":"Before the point of no return","purpose":"Clarify stakes and give one last meaningful choice."},
        {"title":"Confrontation","purpose":"Put the opposing goal in motion, not just hit points."},
        {"title":"Turn","purpose":"Reveal the complication that changes what victory means."},
        {"title":"Fallout","purpose":"Let consequences land and record the new campaign state."}]},
    {"key":"downtime","name":"Downtime & relationships","description":"Player-led personal scenes, recovery, projects and world response.","scenes":[
        {"title":"Where everyone lands","purpose":"Ask each PC what they do when pressure eases."},
        {"title":"Personal spotlights","purpose":"Give character threads space without forcing equal screen time mechanically."},
        {"title":"World catches up","purpose":"Advance consequences, factions, messages and clocks."}]},
]

BUILTIN_RANDOM_TABLES = [
    {"key":"names","name":"Instant NPC names","entries":["Aren Vale","Mira Senn","Tovik Ash","Elian Voss","Sera Pell","Orin Kest","Neris Tal","Vaela Thorn","Corin Mire","Ilyra Venn","Daro Fen","Kessa Rook"]},
    {"key":"mannerisms","name":"NPC mannerisms","entries":["Never quite makes eye contact","Answers questions with another question","Keeps polishing one small object","Speaks too softly when angry","Laughs exactly once before saying something serious","Repeatedly checks the nearest exit","Remembers everyone's name immediately","Corrects tiny factual details","Treats silence as a negotiation tactic","Uses formal titles even with friends"]},
    {"key":"complications","name":"Scene complications","entries":["A third party arrives with a conflicting demand","Someone recognizes a PC for the wrong reason","The useful witness wants something first","Time suddenly matters","The apparent ally is protecting somebody else","A rumor has reached the scene before the party","The environment makes staying dangerous","The opposition offers a deal that is genuinely tempting","A PC's earlier promise becomes relevant","The truth is useful but socially costly"]},
    {"key":"rumors","name":"Rumor shapes","entries":["True fact, completely wrong explanation","Old truth that has become dangerous again","Lie told by someone otherwise trustworthy","Accurate warning nobody wants to believe","Local superstition hiding a practical clue","Two contradictory stories are both partly true","A famous person is blamed for someone else's act","A harmless detail points toward the real problem"]},
]


def _json(raw: Any, default: Any):
    if isinstance(raw,(dict,list)): return raw
    try:return json.loads(raw or '')
    except Exception:return default


def init_v51_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(V51_SCHEMA)
        cols={r['name'] for r in conn.execute("PRAGMA table_info(session_preparations)").fetchall()}
        if 'pacing_json' not in cols:
            conn.execute("ALTER TABLE session_preparations ADD COLUMN pacing_json TEXT NOT NULL DEFAULT '[]'")


def list_scenes(settings: Settings,campaign_id:int,session_id:int)->list[dict]:
    with connect(settings) as conn:
        rows=[dict(r) for r in conn.execute("SELECT * FROM gm_scene_cards WHERE campaign_id=? AND session_id=? ORDER BY sort_order,id",(int(campaign_id),int(session_id))).fetchall()]
    for r in rows:r['npc_slugs']=_json(r.pop('npc_slugs_json','[]'),[])
    return rows


def save_scenes(settings:Settings,campaign_id:int,session_id:int,scenes:list[dict])->list[dict]:
    now=time.time();cid=int(campaign_id);sid=int(session_id)
    with connect(settings) as conn:
        own=conn.execute("SELECT 1 FROM campaign_sessions WHERE id=? AND campaign_id=?",(sid,cid)).fetchone()
        if not own:raise ValueError('Session does not belong to this campaign.')
        existing={int(r['id']):r for r in conn.execute("SELECT id FROM gm_scene_cards WHERE campaign_id=? AND session_id=?",(cid,sid)).fetchall()}
        kept=set()
        for idx,raw in enumerate((scenes or [])[:80]):
            if not isinstance(raw,dict):continue
            rid=int(raw.get('id') or 0)
            vals=(idx,str(raw.get('title') or '')[:300],str(raw.get('purpose') or '')[:5000],str(raw.get('location_slug') or '')[:300],json.dumps([str(x)[:300] for x in (raw.get('npc_slugs') or [])[:20]]),str(raw.get('complication') or '')[:5000],str(raw.get('fallback') or '')[:5000],str(raw.get('notes') or '')[:8000],str(raw.get('status') or 'ready')[:30],int(raw['estimated_minutes']) if str(raw.get('estimated_minutes') or '').isdigit() else None,now)
            if rid and rid in existing:
                conn.execute("UPDATE gm_scene_cards SET sort_order=?,title=?,purpose=?,location_slug=?,npc_slugs_json=?,complication=?,fallback=?,notes=?,status=?,estimated_minutes=?,updated_at=? WHERE id=? AND campaign_id=? AND session_id=?",(*vals,rid,cid,sid));kept.add(rid)
            else:
                nid=int(conn.execute("INSERT INTO gm_scene_cards(campaign_id,session_id,sort_order,title,purpose,location_slug,npc_slugs_json,complication,fallback,notes,status,estimated_minutes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(cid,sid,*vals[:-1],now,now)).lastrowid);kept.add(nid)
        for rid in existing:
            if rid not in kept:conn.execute("DELETE FROM gm_scene_cards WHERE id=?",(rid,))
    return list_scenes(settings,cid,sid)


def list_clues(settings:Settings,campaign_id:int,session_id:int|None=None)->list[dict]:
    with connect(settings) as conn:
        if session_id is None:
            rows=conn.execute("SELECT * FROM gm_clues WHERE campaign_id=? ORDER BY CASE status WHEN 'not_found' THEN 0 WHEN 'hinted' THEN 1 WHEN 'misinterpreted' THEN 2 ELSE 3 END,updated_at DESC,id DESC",(int(campaign_id),)).fetchall()
        else:
            rows=conn.execute("SELECT * FROM gm_clues WHERE campaign_id=? AND (source_session_id=? OR status IN ('not_found','hinted','misinterpreted')) ORDER BY CASE WHEN source_session_id=? THEN 0 ELSE 1 END,updated_at DESC,id DESC",(int(campaign_id),int(session_id),int(session_id))).fetchall()
        return [dict(r) for r in rows]


def save_clue(settings:Settings,campaign_id:int,payload:dict)->dict:
    cid=int(campaign_id);now=time.time();rid=int(payload.get('id') or 0);status=str(payload.get('status') or 'not_found')
    if status not in {'not_found','hinted','discovered','misinterpreted'}:raise ValueError('Unknown clue state.')
    title=str(payload.get('title') or '').strip()[:300]
    if not title:raise ValueError('Clue title is required.')
    values=(title,str(payload.get('body') or '')[:8000],status,str(payload.get('linked_page_slug') or '')[:300],str(payload.get('notes') or '')[:5000],int(payload['source_session_id']) if payload.get('source_session_id') else None,int(payload['delivered_session_id']) if payload.get('delivered_session_id') else None,now)
    with connect(settings) as conn:
        if rid:
            conn.execute("UPDATE gm_clues SET title=?,body=?,status=?,linked_page_slug=?,notes=?,source_session_id=?,delivered_session_id=?,updated_at=? WHERE id=? AND campaign_id=?",(*values,rid,cid))
        else:
            rid=int(conn.execute("INSERT INTO gm_clues(campaign_id,title,body,status,linked_page_slug,notes,source_session_id,delivered_session_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(cid,*values[:-1],now,now)).lastrowid)
        row=conn.execute("SELECT * FROM gm_clues WHERE id=? AND campaign_id=?",(rid,cid)).fetchone()
    return dict(row)


def delete_clue(settings:Settings,campaign_id:int,clue_id:int)->None:
    with connect(settings) as conn:conn.execute("DELETE FROM gm_clues WHERE id=? AND campaign_id=?",(int(clue_id),int(campaign_id)))


def list_npc_cards(settings:Settings,campaign_id:int)->list[dict]:
    with connect(settings) as conn:return [dict(r) for r in conn.execute("SELECT * FROM gm_npc_cards WHERE campaign_id=? ORDER BY page_slug COLLATE NOCASE",(int(campaign_id),)).fetchall()]


def save_npc_card(settings:Settings,campaign_id:int,payload:dict)->dict:
    slug=str(payload.get('page_slug') or '').strip()[:300]
    if not slug:raise ValueError('Choose a Codex page for this NPC card.')
    vals=tuple(str(payload.get(k) or '')[:6000] for k in ('pronunciation','voice','mannerism','motivation','knows','wants','attitude','notes'))
    with connect(settings) as conn:
        conn.execute("INSERT INTO gm_npc_cards(campaign_id,page_slug,pronunciation,voice,mannerism,motivation,knows,wants,attitude,notes,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id,page_slug) DO UPDATE SET pronunciation=excluded.pronunciation,voice=excluded.voice,mannerism=excluded.mannerism,motivation=excluded.motivation,knows=excluded.knows,wants=excluded.wants,attitude=excluded.attitude,notes=excluded.notes,updated_at=excluded.updated_at",(int(campaign_id),slug,*vals,time.time()))
        return dict(conn.execute("SELECT * FROM gm_npc_cards WHERE campaign_id=? AND page_slug=?",(int(campaign_id),slug)).fetchone())


def delete_npc_card(settings:Settings,campaign_id:int,page_slug:str)->None:
    with connect(settings) as conn:
        conn.execute("DELETE FROM gm_npc_cards WHERE campaign_id=? AND page_slug=?",(int(campaign_id),str(page_slug or '')[:300]))


def list_events(settings:Settings,campaign_id:int,session_id:int,limit:int=120)->list[dict]:
    with connect(settings) as conn:return [dict(r) for r in conn.execute("SELECT * FROM gm_session_events WHERE campaign_id=? AND session_id=? ORDER BY created_at DESC,id DESC LIMIT ?",(int(campaign_id),int(session_id),max(1,min(int(limit),300)))).fetchall()]


def add_event(settings:Settings,campaign_id:int,session_id:int,payload:dict)->dict:
    body=str(payload.get('body') or '').strip()[:6000]
    if not body:raise ValueError('Write what happened first.')
    now=time.time()
    with connect(settings) as conn:
        eid=int(conn.execute("INSERT INTO gm_session_events(campaign_id,session_id,event_type,body,target_type,target_key,created_at) VALUES(?,?,?,?,?,?,?)",(int(campaign_id),int(session_id),str(payload.get('event_type') or 'event')[:40],body,str(payload.get('target_type') or '')[:40],str(payload.get('target_key') or '')[:500],now)).lastrowid)
        return dict(conn.execute("SELECT * FROM gm_session_events WHERE id=?",(eid,)).fetchone())


def delete_event(settings:Settings,campaign_id:int,event_id:int)->None:
    with connect(settings) as conn:conn.execute("DELETE FROM gm_session_events WHERE id=? AND campaign_id=?",(int(event_id),int(campaign_id)))


def list_consequences(settings:Settings,campaign_id:int,include_resolved:bool=False)->list[dict]:
    where="campaign_id=?" if include_resolved else "campaign_id=? AND status='pending'"
    with connect(settings) as conn:return [dict(r) for r in conn.execute(f"SELECT * FROM gm_consequences WHERE {where} ORDER BY updated_at DESC,id DESC",(int(campaign_id),)).fetchall()]


def save_consequence(settings:Settings,campaign_id:int,payload:dict)->dict:
    cid=int(campaign_id);rid=int(payload.get('id') or 0);title=str(payload.get('title') or '').strip()[:300]
    if not title:raise ValueError('Consequence title is required.')
    status=str(payload.get('status') or 'pending');status=status if status in {'pending','resolved','cancelled'} else 'pending';now=time.time()
    vals=(title,str(payload.get('body') or '')[:8000],str(payload.get('trigger_kind') or 'manual')[:40],str(payload.get('trigger_value') or '')[:500],status,str(payload.get('target_type') or '')[:40],str(payload.get('target_key') or '')[:500],int(payload['source_session_id']) if payload.get('source_session_id') else None,now)
    with connect(settings) as conn:
        if rid:conn.execute("UPDATE gm_consequences SET title=?,body=?,trigger_kind=?,trigger_value=?,status=?,target_type=?,target_key=?,source_session_id=?,updated_at=? WHERE id=? AND campaign_id=?",(*vals,rid,cid))
        else:rid=int(conn.execute("INSERT INTO gm_consequences(campaign_id,title,body,trigger_kind,trigger_value,status,target_type,target_key,source_session_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,*vals[:-1],now,now)).lastrowid)
        return dict(conn.execute("SELECT * FROM gm_consequences WHERE id=?",(rid,)).fetchone())


def delete_consequence(settings:Settings,campaign_id:int,rid:int)->None:
    with connect(settings) as conn:conn.execute("DELETE FROM gm_consequences WHERE id=? AND campaign_id=?",(int(rid),int(campaign_id)))


def list_clocks(settings:Settings,campaign_id:int,include_done:bool=False)->list[dict]:
    where="campaign_id=?" if include_done else "campaign_id=? AND status='active'"
    with connect(settings) as conn:return [dict(r) for r in conn.execute(f"SELECT * FROM gm_clocks WHERE {where} ORDER BY updated_at DESC,id DESC",(int(campaign_id),)).fetchall()]


def save_clock(settings:Settings,campaign_id:int,payload:dict)->dict:
    cid=int(campaign_id);rid=int(payload.get('id') or 0);title=str(payload.get('title') or '').strip()[:300]
    if not title:raise ValueError('Clock title is required.')
    total=max(2,min(20,int(payload.get('total_segments') or 6)));current=max(0,min(total,int(payload.get('current_segments') or 0)));status=str(payload.get('status') or 'active');status=status if status in {'active','completed','paused'} else 'active';visibility='player' if payload.get('visibility')=='player' else 'gm';now=time.time()
    vals=(title,str(payload.get('description') or '')[:6000],current,total,visibility,status,now)
    with connect(settings) as conn:
        if rid:conn.execute("UPDATE gm_clocks SET title=?,description=?,current_segments=?,total_segments=?,visibility=?,status=?,updated_at=? WHERE id=? AND campaign_id=?",(*vals,rid,cid))
        else:rid=int(conn.execute("INSERT INTO gm_clocks(campaign_id,title,description,current_segments,total_segments,visibility,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(cid,*vals[:-1],now,now)).lastrowid)
        return dict(conn.execute("SELECT * FROM gm_clocks WHERE id=?",(rid,)).fetchone())


def delete_clock(settings:Settings,campaign_id:int,rid:int)->None:
    with connect(settings) as conn:conn.execute("DELETE FROM gm_clocks WHERE id=? AND campaign_id=?",(int(rid),int(campaign_id)))


def record_spotlight(settings:Settings,campaign_id:int,character_id:int,session_id:int|None=None,note:str='')->dict:
    now=time.time()
    with connect(settings) as conn:
        sid=int(conn.execute("INSERT INTO gm_character_spotlights(campaign_id,character_id,session_id,note,created_at) VALUES(?,?,?,?,?)",(int(campaign_id),int(character_id),int(session_id) if session_id else None,str(note or '')[:1000],now)).lastrowid)
        return dict(conn.execute("SELECT * FROM gm_character_spotlights WHERE id=?",(sid,)).fetchone())


def spotlight_status(settings:Settings,campaign_id:int,characters:list[dict],sessions:list[dict])->list[dict]:
    ended=[s for s in sessions if s.get('status')=='ended'];seq={int(s['id']):idx for idx,s in enumerate(sorted(ended,key=lambda x:(x.get('session_number') if x.get('session_number') is not None else 10**9,x.get('session_date') or '',x.get('id'))))};last_idx=max(seq.values(),default=-1)
    with connect(settings) as conn:
        rows=conn.execute("SELECT character_id,session_id,created_at FROM gm_character_spotlights WHERE campaign_id=? ORDER BY created_at DESC,id DESC",(int(campaign_id),)).fetchall()
    latest={}
    for r in rows:latest.setdefault(int(r['character_id']),dict(r))
    out=[]
    for c in characters:
        hit=latest.get(int(c['id']));since=None
        if hit and hit.get('session_id') in seq:since=max(0,last_idx-seq[int(hit['session_id'])])
        elif ended:since=len(ended)
        out.append({'character_id':int(c['id']),'name':c.get('name') or 'Character','portrait_url':c.get('portrait_url') or '','sessions_since':since,'last_session_id':hit.get('session_id') if hit else None})
    return sorted(out,key=lambda x:(-(x['sessions_since'] if x['sessions_since'] is not None else 999),x['name'].casefold()))


def list_templates(settings:Settings,campaign_id:int)->list[dict]:
    with connect(settings) as conn:custom=[dict(r) for r in conn.execute("SELECT * FROM gm_prep_templates WHERE campaign_id=? ORDER BY name COLLATE NOCASE",(int(campaign_id),)).fetchall()]
    for r in custom:r['payload']=_json(r.pop('payload_json','{}'),{})
    return [{'id':'builtin:'+x['key'],**x,'builtin':True} for x in BUILTIN_TEMPLATES]+[{**r,'builtin':False} for r in custom]


def save_template(settings:Settings,campaign_id:int,payload:dict)->dict:
    name=str(payload.get('name') or '').strip()[:180]
    if not name:raise ValueError('Template name is required.')
    content=payload.get('payload') if isinstance(payload.get('payload'),dict) else {}
    now=time.time()
    with connect(settings) as conn:
        rid=int(conn.execute("INSERT INTO gm_prep_templates(campaign_id,name,description,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",(int(campaign_id),name,str(payload.get('description') or '')[:1200],json.dumps(content),now,now)).lastrowid)
        r=dict(conn.execute("SELECT * FROM gm_prep_templates WHERE id=?",(rid,)).fetchone());r['payload']=_json(r.pop('payload_json','{}'),{});return r


def delete_template(settings:Settings,campaign_id:int,rid:int)->None:
    with connect(settings) as conn:conn.execute("DELETE FROM gm_prep_templates WHERE id=? AND campaign_id=?",(int(rid),int(campaign_id)))


def list_random_tables(settings:Settings,campaign_id:int)->list[dict]:
    with connect(settings) as conn:custom=[dict(r) for r in conn.execute("SELECT * FROM gm_random_tables WHERE campaign_id=? ORDER BY name COLLATE NOCASE",(int(campaign_id),)).fetchall()]
    for r in custom:r['entries']=_json(r.pop('entries_json','[]'),[])
    return [{'id':'builtin:'+x['key'],**x,'builtin':True} for x in BUILTIN_RANDOM_TABLES]+[{**r,'builtin':False} for r in custom]


def save_random_table(settings:Settings,campaign_id:int,payload:dict)->dict:
    name=str(payload.get('name') or '').strip()[:180];entries=[str(x).strip()[:1000] for x in (payload.get('entries') or []) if str(x).strip()][:300]
    if not name or not entries:raise ValueError('A random table needs a name and at least one entry.')
    now=time.time()
    with connect(settings) as conn:
        rid=int(conn.execute("INSERT INTO gm_random_tables(campaign_id,name,entries_json,created_at,updated_at) VALUES(?,?,?,?,?)",(int(campaign_id),name,json.dumps(entries),now,now)).lastrowid)
        r=dict(conn.execute("SELECT * FROM gm_random_tables WHERE id=?",(rid,)).fetchone());r['entries']=_json(r.pop('entries_json','[]'),[]);return r


def delete_random_table(settings:Settings,campaign_id:int,rid:int)->None:
    with connect(settings) as conn:conn.execute("DELETE FROM gm_random_tables WHERE id=? AND campaign_id=?",(int(rid),int(campaign_id)))


def roll_random_table(settings:Settings,campaign_id:int,table_id:str)->dict:
    tables=list_random_tables(settings,campaign_id);table=next((t for t in tables if str(t['id'])==str(table_id)),None)
    if not table:raise ValueError('Random table not found.')
    entries=table.get('entries') or []
    if not entries:raise ValueError('Random table is empty.')
    return {'table':table.get('name'),'result':random.SystemRandom().choice(entries)}


def forgotten_items(settings:Settings,campaign_id:int,characters:list[dict],sessions:list[dict],objectives:list[dict])->list[dict]:
    cid=int(campaign_id);items=[]
    for c in list_clues(settings,cid):
        if c['status'] in {'not_found','hinted','misinterpreted'}:
            items.append({'kind':'clue','severity':'attention','title':c['title'],'body':{'not_found':'Prepared but not delivered.','hinted':'Hinted, but not actually discovered.','misinterpreted':'Players currently have the wrong read on this.'}[c['status']]})
    for c in list_consequences(settings,cid):items.append({'kind':'consequence','severity':'attention','title':c['title'],'body':f"Pending trigger: {c['trigger_kind'].replace('_',' ')} {c['trigger_value']}".strip()})
    for clock in list_clocks(settings,cid):
        if int(clock['current_segments'])>0:items.append({'kind':'clock','severity':'watch','title':clock['title'],'body':f"{clock['current_segments']}/{clock['total_segments']} segments filled."})
    for s in spotlight_status(settings,cid,characters,sessions):
        if s['sessions_since'] is not None and s['sessions_since']>=4:items.append({'kind':'spotlight','severity':'quiet','title':s['name'],'body':f"GM note: no spotlight marker in {s['sessions_since']} sessions."})
    now=time.time()
    for o in objectives:
        age=(now-float(o.get('updated_at') or now))/86400
        if o.get('status') in {'active','hold'} and age>45:items.append({'kind':'objective','severity':'quiet','title':o.get('title') or 'Objective','body':'This objective has not changed in over 45 days.'})
    return items[:80]


def prep_workspace(settings:Settings,campaign_id:int,session_id:int,characters:list[dict],sessions:list[dict],objectives:list[dict])->dict:
    return {
        'scenes':list_scenes(settings,campaign_id,session_id),
        'clues':list_clues(settings,campaign_id,session_id),
        'npc_cards':list_npc_cards(settings,campaign_id),
        'events':list_events(settings,campaign_id,session_id),
        'consequences':list_consequences(settings,campaign_id),
        'clocks':list_clocks(settings,campaign_id),
        'spotlights':spotlight_status(settings,campaign_id,characters,sessions),
        'templates':list_templates(settings,campaign_id),
        'random_tables':list_random_tables(settings,campaign_id),
        'forgotten':forgotten_items(settings,campaign_id,characters,sessions,objectives),
    }


def save_closeout(settings:Settings,campaign_id:int,session_id:int,summary:str='',unresolved:str='',next_session_id:int|None=None)->dict:
    now=time.time()
    with connect(settings) as conn:
        conn.execute("INSERT INTO gm_session_closeouts(session_id,campaign_id,summary,unresolved,next_session_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET summary=excluded.summary,unresolved=excluded.unresolved,next_session_id=excluded.next_session_id,updated_at=excluded.updated_at",(int(session_id),int(campaign_id),str(summary or '')[:16000],str(unresolved or '')[:12000],int(next_session_id) if next_session_id else None,now,now))
        return dict(conn.execute("SELECT * FROM gm_session_closeouts WHERE session_id=?",(int(session_id),)).fetchone())
