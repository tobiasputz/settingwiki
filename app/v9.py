from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .storage import connect
from .v7 import list_entities, knowledge_facts, sync_link, memory_search
from .v6 import foundry_state, recent_foundry_commands
from .features import list_handouts, list_timeline
from .maps import list_maps
from .homebrew_global import list_global_homebrew

V9_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v9_session_director (
    session_id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    scene_label TEXT NOT NULL DEFAULT '',
    encounter_id INTEGER,
    map_id INTEGER,
    handout_id INTEGER,
    mode TEXT NOT NULL DEFAULT 'scene',
    gm_notes TEXT NOT NULL DEFAULT '',
    clock_json TEXT NOT NULL DEFAULT '[]',
    data_json TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(encounter_id) REFERENCES v7_encounters(id) ON DELETE SET NULL,
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE SET NULL,
    FOREIGN KEY(handout_id) REFERENCES handouts(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS v9_knowledge_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    field_key TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    public_value TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'hidden',
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    UNIQUE(entity_id,field_key),
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v9_knowledge_entity ON v9_knowledge_fields(campaign_id,entity_id,sort_order,id);
CREATE TABLE IF NOT EXISTS v9_knowledge_field_reveals (
    field_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    revealed_at REAL NOT NULL,
    session_id INTEGER,
    PRIMARY KEY(field_id,invite_id),
    FOREIGN KEY(field_id) REFERENCES v9_knowledge_fields(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS v9_timeline_consequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    timeline_event_id INTEGER NOT NULL,
    entity_id INTEGER,
    consequence TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(timeline_event_id) REFERENCES timeline_events(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v9_timeline_consequence ON v9_timeline_consequences(campaign_id,timeline_event_id,status,sort_order,id);
CREATE TABLE IF NOT EXISTS v9_relationship_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    source_entity_id INTEGER NOT NULL,
    target_entity_id INTEGER NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    evidence TEXT NOT NULL DEFAULT '',
    suggested_relation TEXT NOT NULL DEFAULT 'related to',
    status TEXT NOT NULL DEFAULT 'pending',
    updated_at REAL NOT NULL,
    UNIQUE(campaign_id,source_entity_id,target_entity_id),
    FOREIGN KEY(source_entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(target_entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS v9_asset_metadata (
    asset_ref TEXT PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '',
    alt_text TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    sha256 TEXT NOT NULL DEFAULT '',
    width INTEGER,
    height INTEGER,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS v9_asset_links (
    campaign_id INTEGER NOT NULL,
    asset_ref TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT 'art',
    created_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,asset_ref,target_type,target_key,purpose)
);
CREATE TABLE IF NOT EXISTS v9_map_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    map_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    state_json TEXT NOT NULL DEFAULT '{}',
    player_visible INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(campaign_id,map_id,name),
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS v9_schema_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    applied_at REAL NOT NULL
);
'''


def _rows(settings: Settings, sql: str, args: tuple[Any, ...] = ()) -> list[dict]:
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _row(settings: Settings, sql: str, args: tuple[Any, ...] = ()) -> dict | None:
    with connect(settings) as conn:
        r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def _j(raw: Any, default: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or '')
    except Exception:
        return default


def init_v9_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(V9_SCHEMA)
        if not conn.execute("SELECT 1 FROM v9_schema_history WHERE version='9.0.0'").fetchone():
            conn.execute("INSERT INTO v9_schema_history(version,note,applied_at) VALUES(?,?,?)", ('9.0.0','Live play, global Homebrew, knowledge, search, assets, map states and extension API',time.time()))


# ---------------- Session Director ----------------
def session_director(settings: Settings, campaign_id: int, session_id: int) -> dict:
    row = _row(settings, 'SELECT * FROM v9_session_director WHERE campaign_id=? AND session_id=?', (int(campaign_id), int(session_id)))
    if not row:
        with connect(settings) as conn:
            conn.execute('INSERT OR IGNORE INTO v9_session_director(session_id,campaign_id,updated_at) VALUES(?,?,?)', (int(session_id), int(campaign_id), time.time()))
        row = _row(settings, 'SELECT * FROM v9_session_director WHERE campaign_id=? AND session_id=?', (int(campaign_id), int(session_id))) or {}
    row['clocks'] = _j(row.pop('clock_json', '[]'), [])
    row['data'] = _j(row.pop('data_json', '{}'), {})
    return row


def save_session_director(settings: Settings, campaign_id: int, session_id: int, payload: dict) -> dict:
    current = session_director(settings, campaign_id, session_id)
    mode = str(payload.get('mode') or current.get('mode') or 'scene').strip().lower()
    if mode not in {'scene','encounter','exploration','downtime'}:
        mode = 'scene'
    clocks = payload.get('clocks') if isinstance(payload.get('clocks'), list) else current.get('clocks', [])
    data = payload.get('data') if isinstance(payload.get('data'), dict) else current.get('data', {})
    vals = (
        str(payload.get('scene_label', current.get('scene_label') or ''))[:240],
        payload.get('encounter_id', current.get('encounter_id')),
        payload.get('map_id', current.get('map_id')),
        payload.get('handout_id', current.get('handout_id')),
        mode,
        str(payload.get('gm_notes', current.get('gm_notes') or ''))[:20000],
        json.dumps(clocks, ensure_ascii=False), json.dumps(data, ensure_ascii=False), time.time(),
        int(session_id), int(campaign_id),
    )
    with connect(settings) as conn:
        conn.execute('''UPDATE v9_session_director SET scene_label=?,encounter_id=?,map_id=?,handout_id=?,mode=?,gm_notes=?,clock_json=?,data_json=?,updated_at=? WHERE session_id=? AND campaign_id=?''', vals)
    return session_director(settings, campaign_id, session_id)


# ---------------- Field-level player knowledge ----------------
def knowledge_fields(settings: Settings, campaign_id: int, entity_id: int, invite_id: int | None = None, *, gm: bool = True) -> list[dict]:
    try:
        rows = _rows(settings, 'SELECT * FROM v9_knowledge_fields WHERE campaign_id=? AND entity_id=? ORDER BY sort_order,id', (int(campaign_id), int(entity_id)))
    except sqlite3.OperationalError as exc:
        if 'no such table' in str(exc).lower():
            return []
        raise
    if gm:
        for r in rows:
            r['revealed_to'] = [int(x['invite_id']) for x in _rows(settings, 'SELECT invite_id FROM v9_knowledge_field_reveals WHERE field_id=?', (int(r['id']),))]
        return rows
    if invite_id is None:
        return [r for r in rows if r.get('visibility') == 'public']
    revealed = {int(x['field_id']) for x in _rows(settings, 'SELECT field_id FROM v9_knowledge_field_reveals WHERE invite_id=?', (int(invite_id),))}
    out=[]
    for r in rows:
        visibility=str(r.get('visibility') or 'hidden')
        if visibility=='public' or int(r['id']) in revealed:
            out.append({**r,'value':r.get('public_value') or r.get('value') or ''})
        elif visibility=='teaser' and r.get('public_value'):
            out.append({**r,'value':r.get('public_value')})
    return out


def save_knowledge_field(settings: Settings, campaign_id: int, entity_id: int, payload: dict) -> dict:
    key = re.sub(r'[^a-z0-9_-]+','-',str(payload.get('field_key') or payload.get('label') or '').strip().casefold()).strip('-')[:120]
    label = str(payload.get('label') or '').strip()[:180]
    if not key or not label:
        raise ValueError('Field label is required.')
    visibility = str(payload.get('visibility') or 'hidden').lower()
    if visibility not in {'hidden','teaser','public'}: visibility='hidden'
    now=time.time()
    with connect(settings) as conn:
        conn.execute('''INSERT INTO v9_knowledge_fields(campaign_id,entity_id,field_key,label,value,public_value,visibility,sort_order,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(entity_id,field_key) DO UPDATE SET label=excluded.label,value=excluded.value,public_value=excluded.public_value,visibility=excluded.visibility,sort_order=excluded.sort_order,updated_at=excluded.updated_at''',
                     (int(campaign_id),int(entity_id),key,label,str(payload.get('value') or '')[:20000],str(payload.get('public_value') or '')[:20000],visibility,int(payload.get('sort_order') or 0),now))
    return next(x for x in knowledge_fields(settings,campaign_id,entity_id,gm=True) if x['field_key']==key)


def reveal_knowledge_field(settings: Settings, campaign_id: int, field_id: int, invite_ids: list[int], session_id: int | None = None, *, revealed: bool = True) -> dict:
    field=_row(settings,'SELECT * FROM v9_knowledge_fields WHERE id=? AND campaign_id=?',(int(field_id),int(campaign_id)))
    if not field: raise ValueError('Knowledge field not found.')
    with connect(settings) as conn:
        for iid in invite_ids:
            if revealed:
                conn.execute('''INSERT INTO v9_knowledge_field_reveals(field_id,invite_id,revealed_at,session_id) VALUES(?,?,?,?)
                                ON CONFLICT(field_id,invite_id) DO UPDATE SET revealed_at=excluded.revealed_at,session_id=excluded.session_id''',(int(field_id),int(iid),time.time(),session_id))
            else:
                conn.execute('DELETE FROM v9_knowledge_field_reveals WHERE field_id=? AND invite_id=?',(int(field_id),int(iid)))
    return {'ok':True,'field_id':int(field_id),'invite_ids':[int(x) for x in invite_ids],'revealed':bool(revealed)}


# ---------------- Timeline consequences ----------------
def timeline_with_consequences(settings: Settings, campaign_id: int, *, admin: bool = True) -> list[dict]:
    events=list_timeline(settings,admin=admin)
    out=[]
    for e in events:
        # Older databases may not scope timeline rows. Filter when a campaign_id column is present.
        if e.get('campaign_id') not in (None,int(campaign_id)): continue
        cons=_rows(settings,'''SELECT c.*,ve.name AS entity_name FROM v9_timeline_consequences c LEFT JOIN v7_entities ve ON ve.id=c.entity_id
                               WHERE c.campaign_id=? AND c.timeline_event_id=? ORDER BY c.sort_order,c.id''',(int(campaign_id),int(e['id'])))
        out.append({**e,'consequences':cons})
    return out


def save_timeline_consequence(settings: Settings, campaign_id: int, event_id: int, payload: dict) -> dict:
    text=str(payload.get('consequence') or '').strip()
    if not text: raise ValueError('Consequence text is required.')
    rid=int(payload.get('id') or 0);now=time.time();status=str(payload.get('status') or 'active')[:40]
    with connect(settings) as conn:
        if rid:
            cur=conn.execute('UPDATE v9_timeline_consequences SET entity_id=?,consequence=?,status=?,sort_order=?,updated_at=? WHERE id=? AND campaign_id=?',
                             (payload.get('entity_id'),text[:8000],status,int(payload.get('sort_order') or 0),now,rid,int(campaign_id)))
            if not cur.rowcount: raise ValueError('Timeline consequence not found.')
        else:
            cur=conn.execute('''INSERT INTO v9_timeline_consequences(campaign_id,timeline_event_id,entity_id,consequence,status,sort_order,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,?)''',(int(campaign_id),int(event_id),payload.get('entity_id'),text[:8000],status,int(payload.get('sort_order') or 0),now,now));rid=int(cur.lastrowid or 0)
    return _row(settings,'SELECT * FROM v9_timeline_consequences WHERE id=?',(rid,)) or {}


# ---------------- Relationship suggestions ----------------
def relationship_suggestions(settings: Settings, campaign_id: int, wiki: dict, *, refresh: bool = False) -> list[dict]:
    entities=list_entities(settings,campaign_id,tracked_only=True)
    if refresh:
        names=[(int(e['id']),str(e.get('name') or '').strip()) for e in entities if len(str(e.get('name') or '').strip())>=3]
        pages=wiki.get('pages',[]) or []
        current_rel={(min(int(r['source_entity_id']),int(r['target_entity_id'])),max(int(r['source_entity_id']),int(r['target_entity_id']))) for r in _rows(settings,'SELECT source_entity_id,target_entity_id FROM v7_entity_relations WHERE campaign_id=? AND active=1',(int(campaign_id),))}
        counts={}
        evidence={}
        for p in pages:
            text=' '.join([str(p.get('title') or ''),str(p.get('plain_text') or ''),str(p.get('excerpt') or '')]).casefold()
            hits=[(eid,name) for eid,name in names if name.casefold() in text]
            if len(hits)>1:
                for i,(a,an) in enumerate(hits):
                    for b,bn in hits[i+1:]:
                        pair=(min(a,b),max(a,b))
                        if pair in current_rel: continue
                        counts[pair]=counts.get(pair,0)+1
                        evidence.setdefault(pair,[]).append(str(p.get('title') or p.get('slug') or 'Codex page'))
        now=time.time()
        with connect(settings) as conn:
            for pair,n in counts.items():
                if n < 1: continue
                ev=', '.join(dict.fromkeys(evidence.get(pair,[])))[:1000]
                conn.execute('''INSERT INTO v9_relationship_suggestions(campaign_id,source_entity_id,target_entity_id,score,evidence,suggested_relation,status,updated_at)
                                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id,source_entity_id,target_entity_id) DO UPDATE SET score=excluded.score,evidence=excluded.evidence,updated_at=excluded.updated_at''',
                             (int(campaign_id),pair[0],pair[1],float(n),ev,'related to','pending',now))
    return _rows(settings,'''SELECT s.*,a.name AS source_name,b.name AS target_name FROM v9_relationship_suggestions s
                             JOIN v7_entities a ON a.id=s.source_entity_id JOIN v7_entities b ON b.id=s.target_entity_id
                             WHERE s.campaign_id=? AND s.status='pending' ORDER BY s.score DESC,s.updated_at DESC''',(int(campaign_id),))


def decide_relationship_suggestion(settings: Settings, campaign_id: int, suggestion_id: int, status: str) -> dict:
    status=str(status or '').lower()
    if status not in {'accepted','rejected','pending'}: raise ValueError('Unknown suggestion decision.')
    with connect(settings) as conn:
        cur=conn.execute('UPDATE v9_relationship_suggestions SET status=?,updated_at=? WHERE id=? AND campaign_id=?',(status,time.time(),int(suggestion_id),int(campaign_id)))
        if not cur.rowcount: raise ValueError('Relationship suggestion not found.')
    return _row(settings,'SELECT * FROM v9_relationship_suggestions WHERE id=?',(int(suggestion_id),)) or {}


# ---------------- Universal search ----------------
def universal_search(settings: Settings, campaign_id: int, wiki: dict, query: str, *, gm: bool = True, invite_id: int | None = None, limit: int = 60) -> list[dict]:
    q=str(query or '').strip(); low=q.casefold(); docs=[]
    # Start with the existing semantic-ish campaign memory index.
    for r in memory_search(settings,campaign_id,wiki,q,limit=80,gm=gm,invite_id=invite_id,can_view_statblocks=gm):
        docs.append({**r,'source':'campaign','search_blob':f"{r.get('title','')} {r.get('excerpt','')}"})
    for h in list_global_homebrew(settings,campaign_id):
        p=h.get('payload') or {}; docs.append({'kind':'homebrew','key':h['id'],'title':h.get('title'),'excerpt':h.get('summary') or p.get('description') or '',
            'href':f"/homebrew/entry/{h['id']}",'source':'homebrew','level':p.get('level'),'category':p.get('feat_category') or p.get('homebrew_document'),'search_blob':json.dumps(h,ensure_ascii=False,default=str)})
    for e in timeline_with_consequences(settings,campaign_id,admin=gm):
        docs.append({'kind':'timeline','key':e['id'],'title':e.get('title'),'excerpt':e.get('body') or '', 'href':'/timeline','source':'timeline','search_blob':json.dumps(e,ensure_ascii=False,default=str)})
    for h in list_handouts(settings,admin=gm,campaign_id=campaign_id):
        docs.append({'kind':'handout','key':h['id'],'title':h.get('title'),'excerpt':h.get('body') or '', 'href':f"/handout/{h.get('slug')}",'source':'handout','search_blob':json.dumps(h,ensure_ascii=False,default=str)})
    for m in list_maps(settings,public=not gm):
        docs.append({'kind':'map','key':m['id'],'title':m.get('name'),'excerpt':m.get('description') or '', 'href':f"/atlas/{m.get('slug')}",'source':'map','search_blob':json.dumps(m,ensure_ascii=False,default=str)})
    # Declarative extensions can contribute search providers without loading arbitrary Python.
    if gm:
        for ext in discover_extensions(settings):
            for i, entry in enumerate(ext.get('search_entries') or []):
                if not isinstance(entry,dict): continue
                title=str(entry.get('title') or '').strip()
                if not title: continue
                docs.append({'kind':str(entry.get('kind') or 'extension'),'key':f"{ext['id']}:{entry.get('id',i)}",
                    'title':title,'excerpt':str(entry.get('excerpt') or entry.get('description') or ''),
                    'href':str(entry.get('href') or (ext.get('workspace_tab') or {}).get('href') or '#'),
                    'source':ext['id'],'search_blob':json.dumps(entry,ensure_ascii=False,default=str)})
    # Natural-language filters for common GM questions.
    want_kind=None
    for token,k in [('handout','handout'),('timeline','timeline'),('map','map'),('session','session'),('feat','homebrew'),('homebrew','homebrew'),('npc','npc'),('place','place')]:
        if token in low: want_kind=k;break
    level_match=re.search(r'\blevel\s+(\d+)\b',low);want_level=int(level_match.group(1)) if level_match else None
    unrevealed='not yet revealed' in low or 'unrevealed' in low
    terms=[x for x in re.findall(r"[\w'’-]+",low) if len(x)>1 and x not in {'where','what','show','find','all','the','and','with','that','have','not','yet','revealed','level','sessions','session'}]
    seen=set();scored=[]
    for d in docs:
        sig=(str(d.get('kind')),str(d.get('key')),str(d.get('href')))
        if sig in seen: continue
        seen.add(sig)
        kind=str(d.get('kind') or '')
        if want_kind and want_kind not in {kind,str(d.get('source') or '')} and not (want_kind=='homebrew' and kind in {'feat','ancestry','archetype'}): continue
        if want_level is not None and d.get('source')=='homebrew':
            try:
                if int(d.get('level') or 0)!=want_level: continue
            except Exception: continue
        if unrevealed and d.get('source')=='handout' and str(_j(d.get('search_blob'),{}).get('visibility') if isinstance(_j(d.get('search_blob'),{}),dict) else '')=='players':
            continue
        blob=str(d.get('search_blob') or f"{d.get('title','')} {d.get('excerpt','')}").casefold()
        score=sum((8 if str(d.get('title') or '').casefold().startswith(t) else 2)*blob.count(t) for t in terms)
        if not terms: score=1
        if q.casefold() in blob: score+=12
        if score: scored.append((score,d))
    scored.sort(key=lambda x:(-x[0],str(x[1].get('title') or '').casefold()))
    return [{k:v for k,v in d.items() if k!='search_blob'} for _,d in scored[:max(1,min(int(limit),100))]]


# ---------------- Foundry sync manager ----------------
def foundry_sync_matrix(settings: Settings, campaign_id: int) -> dict:
    rows=[]
    for e in list_entities(settings,campaign_id,tracked_only=True):
        link=sync_link(settings,int(e['id']))
        rows.append({'entity_id':int(e['id']),'name':e.get('name'),'kind':e.get('kind'),'status':(link or {}).get('status') or 'not_imported','link':link})
    counts={}
    for r in rows: counts[r['status']]=counts.get(r['status'],0)+1
    return {'foundry':foundry_state(settings,campaign_id),'rows':rows,'counts':counts,'commands':recent_foundry_commands(settings,campaign_id,40)}


# ---------------- Asset Library ----------------
def _asset_file(settings: Settings, ref: str) -> Path | None:
    value=str(ref or '')
    if value.startswith('upload:'): return settings.uploads_dir/value[7:]
    if value.startswith('project:'): return settings.project_dir/value[8:]
    if value.startswith('/uploads/'): return settings.uploads_dir/value[len('/uploads/'):]
    if value.startswith('/project-asset/'): return settings.project_dir/value[len('/project-asset/'):]
    return None


def asset_library(settings: Settings, campaign_id: int) -> dict:
    refs={}
    for root,prefix,urlprefix in ((settings.uploads_dir,'upload:','/uploads/'),(settings.project_dir,'project:','/project-asset/')):
        for path in root.rglob('*'):
            if not path.is_file() or path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.gif','.svg','.pdf','.mp3','.ogg','.wav'}: continue
            rel=path.relative_to(root).as_posix();ref=prefix+rel
            refs[ref]={'ref':ref,'url':urlprefix+rel,'name':path.name,'path':rel,'size_bytes':path.stat().st_size,'modified_at':path.stat().st_mtime}
    meta={r['asset_ref']:r for r in _rows(settings,'SELECT * FROM v9_asset_metadata')}
    links=_rows(settings,'SELECT * FROM v9_asset_links WHERE campaign_id=?',(int(campaign_id),));byref={}
    for l in links: byref.setdefault(l['asset_ref'],[]).append(l)
    out=[]
    for ref,row in refs.items():
        m=meta.get(ref,{})
        out.append({**row,'label':m.get('label') or row['name'],'alt_text':m.get('alt_text') or '','tags':_j(m.get('tags_json'),[]),'sha256':m.get('sha256') or '','links':byref.get(ref,[])})
    out.sort(key=lambda x:(-len(x['links']),-x['modified_at'],x['name'].casefold()))
    hashes={};dupes=[]
    for r in out:
        if r.get('sha256'): hashes.setdefault(r['sha256'],[]).append(r['ref'])
    dupes=[v for v in hashes.values() if len(v)>1]
    return {'count':len(out),'total_bytes':sum(x['size_bytes'] for x in out),'assets':out,'duplicates':dupes}


def save_asset_metadata(settings: Settings, ref: str, payload: dict) -> dict:
    path=_asset_file(settings,ref)
    if not path or not path.exists(): raise ValueError('Asset not found.')
    digest=''
    if path.stat().st_size <= 40*1024*1024:
        h=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
        digest=h.hexdigest()
    tags=payload.get('tags') if isinstance(payload.get('tags'),list) else [x.strip() for x in str(payload.get('tags') or '').split(',') if x.strip()]
    with connect(settings) as conn:
        conn.execute('''INSERT INTO v9_asset_metadata(asset_ref,label,alt_text,tags_json,sha256,updated_at) VALUES(?,?,?,?,?,?)
                        ON CONFLICT(asset_ref) DO UPDATE SET label=excluded.label,alt_text=excluded.alt_text,tags_json=excluded.tags_json,sha256=excluded.sha256,updated_at=excluded.updated_at''',
                     (ref,str(payload.get('label') or path.name)[:240],str(payload.get('alt_text') or '')[:1000],json.dumps(tags,ensure_ascii=False),digest,time.time()))
    return next(x for x in asset_library(settings,0)['assets'] if x['ref']==ref)


def link_asset(settings: Settings, campaign_id: int, ref: str, target_type: str, target_key: str, purpose: str='art') -> dict:
    if not _asset_file(settings,ref) or not _asset_file(settings,ref).exists(): raise ValueError('Asset not found.')
    with connect(settings) as conn:
        conn.execute('INSERT OR IGNORE INTO v9_asset_links(campaign_id,asset_ref,target_type,target_key,purpose,created_at) VALUES(?,?,?,?,?,?)',
                     (int(campaign_id),ref,str(target_type)[:80],str(target_key)[:300],str(purpose)[:80],time.time()))
    return {'ok':True,'asset_ref':ref,'target_type':target_type,'target_key':target_key,'purpose':purpose}


# ---------------- Map states ----------------
def list_map_states(settings: Settings, campaign_id: int, map_id: int | None = None) -> list[dict]:
    sql='SELECT * FROM v9_map_states WHERE campaign_id=?';args=[int(campaign_id)]
    if map_id is not None: sql+=' AND map_id=?';args.append(int(map_id))
    sql+=' ORDER BY map_id,lower(name),id'
    rows=_rows(settings,sql,tuple(args))
    for r in rows:r['state']=_j(r.pop('state_json','{}'),{})
    return rows


def capture_map_state(settings: Settings, campaign_id: int, map_id: int, name: str, description: str='', *, player_visible: bool=False) -> dict:
    name=str(name or '').strip()[:180]
    if not name: raise ValueError('Map state name is required.')
    markers=_rows(settings,'SELECT id,title,visible_to_players,x,y FROM markers WHERE map_id=? ORDER BY id',(int(map_id),))
    try: layers=_rows(settings,'SELECT id,name,enabled,visible_to_players,opacity FROM map_layers WHERE map_id=? ORDER BY sort_order,id',(int(map_id),))
    except Exception: layers=[]
    state={'markers':markers,'layers':layers}
    now=time.time()
    with connect(settings) as conn:
        conn.execute('''INSERT INTO v9_map_states(campaign_id,map_id,name,description,state_json,player_visible,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)
                        ON CONFLICT(campaign_id,map_id,name) DO UPDATE SET description=excluded.description,state_json=excluded.state_json,player_visible=excluded.player_visible,updated_at=excluded.updated_at''',
                     (int(campaign_id),int(map_id),name,str(description)[:3000],json.dumps(state,ensure_ascii=False),1 if player_visible else 0,now,now))
    return next(x for x in list_map_states(settings,campaign_id,map_id) if x['name']==name)


def apply_map_state(settings: Settings, campaign_id: int, state_id: int) -> dict:
    row=next((x for x in list_map_states(settings,campaign_id) if int(x['id'])==int(state_id)),None)
    if not row: raise ValueError('Map state not found.')
    state=row.get('state') or {}
    with connect(settings) as conn:
        for m in state.get('markers') or []:
            conn.execute('UPDATE markers SET visible_to_players=?,updated_at=? WHERE id=? AND map_id=?',(1 if m.get('visible_to_players') else 0,time.time(),int(m['id']),int(row['map_id'])))
        for l in state.get('layers') or []:
            try: conn.execute('UPDATE map_layers SET enabled=?,visible_to_players=?,opacity=?,updated_at=? WHERE id=? AND map_id=?',(1 if l.get('enabled') else 0,1 if l.get('visible_to_players') else 0,float(l.get('opacity') or 0.7),time.time(),int(l['id']),int(row['map_id'])))
            except Exception: pass
    return {'ok':True,'state':row}


# ---------------- Extension manifests ----------------
def discover_extensions(settings: Settings) -> list[dict]:
    root=settings.root_dir/'plugins';out=[]
    if not root.exists(): return out
    for manifest in sorted(root.glob('*/plugin.json')):
        try: data=json.loads(manifest.read_text(encoding='utf-8'))
        except Exception: continue
        if not isinstance(data,dict) or not data.get('id') or not data.get('title'): continue
        out.append({
            'id':str(data['id'])[:100],'title':str(data['title'])[:180],'description':str(data.get('description') or '')[:1000],
            'version':str(data.get('version') or '1.0.0')[:40],'workspace_tab':data.get('workspace_tab') if isinstance(data.get('workspace_tab'),dict) else None,
            'search_entries':data.get('search_entries') if isinstance(data.get('search_entries'),list) else [],
            'object_types':data.get('object_types') if isinstance(data.get('object_types'),list) else [],
            'forge_types':data.get('forge_types') if isinstance(data.get('forge_types'),list) else [],
            'foundry_actions':data.get('foundry_actions') if isinstance(data.get('foundry_actions'),list) else [],
            'manifest_path':manifest.relative_to(settings.root_dir).as_posix(),
        })
    return out



def get_extension(settings: Settings, plugin_id: str) -> dict | None:
    wanted=str(plugin_id or '').strip()
    return next((x for x in discover_extensions(settings) if x.get('id')==wanted),None)


def extension_foundry_action(settings: Settings, plugin_id: str, action_id: str) -> dict:
    ext=get_extension(settings,plugin_id)
    if not ext: raise ValueError('Extension not found.')
    action=next((a for a in (ext.get('foundry_actions') or []) if isinstance(a,dict) and str(a.get('id') or '')==str(action_id or '')),None)
    if not action: raise ValueError('Extension Foundry action not found.')
    # Declarative actions deliberately map only to bridge commands Seeker already
    # understands. Extensions never execute server-side Python or arbitrary JS.
    command_type=str(action.get('command_type') or '').strip().lower()
    allowed={'push_prepared_content','push_ancestry_bundle','push_homebrew_rule_bundle','push_content_bundle','sync_entity_document','grant_prepared_content','adjust_resource','adjust_item_quantity'}
    if command_type not in allowed: raise ValueError('Extension action uses an unsupported Foundry command type.')
    return {**action,'command_type':command_type,'plugin_id':ext['id'],'plugin_title':ext['title']}

def migration_status(settings: Settings) -> dict:
    rows=_rows(settings,'SELECT * FROM v9_schema_history ORDER BY applied_at DESC,id DESC')
    return {'schema_history':rows,'current':'9.0.2','database':str(settings.db_path),'data_dir':str(settings.data_dir)}
