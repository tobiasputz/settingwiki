from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .storage import connect, safe_project_path, save_text_file, storage_report
from .v7 import get_entity, list_entities, entity_versions, sync_link, dependency_warnings, recent_audit

V8_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v8_object_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    entity_id INTEGER,
    link_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(campaign_id, link_type, target_key, entity_id),
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v8_links_entity ON v8_object_links(campaign_id,entity_id,link_type);
CREATE INDEX IF NOT EXISTS idx_v8_links_target ON v8_object_links(campaign_id,link_type,target_key);

CREATE TABLE IF NOT EXISTS v8_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    object_type TEXT NOT NULL,
    object_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    source_path TEXT NOT NULL DEFAULT '',
    source_text TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v8_revisions_target ON v8_revisions(campaign_id,object_type,object_key,created_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS v8_module_settings (
    campaign_id INTEGER NOT NULL,
    module_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    pinned INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,module_id)
);

CREATE TABLE IF NOT EXISTS v8_session_workflow (
    session_id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    stage TEXT NOT NULL DEFAULT 'prep',
    prep_json TEXT NOT NULL DEFAULT '{}',
    run_json TEXT NOT NULL DEFAULT '{}',
    chronicle_json TEXT NOT NULL DEFAULT '{}',
    started_at REAL,
    ended_at REAL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v8_workflow_campaign ON v8_session_workflow(campaign_id,stage,updated_at DESC);

CREATE TABLE IF NOT EXISTS v8_handout_links (
    handout_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    relation TEXT NOT NULL DEFAULT 'about',
    created_at REAL NOT NULL,
    PRIMARY KEY(handout_id,entity_id,relation),
    FOREIGN KEY(handout_id) REFERENCES handouts(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS v8_source_mappings (
    campaign_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    root_command TEXT NOT NULL DEFAULT '',
    root_title TEXT NOT NULL DEFAULT '',
    structure_json TEXT NOT NULL DEFAULT '[]',
    source_hash TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,entity_id,source_path),
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v8_source_path ON v8_source_mappings(campaign_id,source_path);

CREATE TABLE IF NOT EXISTS v8_session_touches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'opened',
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    UNIQUE(session_id,target_type,target_key,action),
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
);
'''

MODULES = [
    ('dashboard','Dashboard','What matters now: session, prep, recent changes and warnings.',1),
    ('session','Session','Prep → Run → Chronicle workflow and table controls.',1),
    ('codex','Codex','Campaign entities, relationships, backlinks and source ownership.',1),
    ('homebrew','Homebrew','PF2e authoring and source-linked rules content.',1),
    ('atlas','Atlas','World, region, city and dungeon maps with campaign links.',1),
    ('handouts','Handouts','Campaign-connected letters, notices, dossiers and relics.',1),
    ('foundry','Foundry','Bidirectional document and live table synchronization.',1),
    ('chronicle','Chronicle','Session history, unresolved hooks and campaign changes.',1),
    ('diagnostics','Diagnostics','System health, source warnings, sync status and storage.',0),
]

_HEADING_RE = re.compile(r"\\(part|chapter|section|subsection|subsubsection)\*?\s*\{([^{}]*)\}", re.I)
_INCLUDE_RE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}", re.I)


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


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def init_v8_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(V8_SCHEMA)
        now = time.time()
        for order, (mid, _title, _desc, pinned) in enumerate(MODULES):
            conn.execute(
                'INSERT OR IGNORE INTO v8_module_settings(campaign_id,module_id,enabled,pinned,sort_order,updated_at) '
                'SELECT id,?,?,?,?,? FROM campaigns',
                (mid, 1, pinned, order, now),
            )


def ensure_campaign_modules(settings: Settings, campaign_id: int) -> None:
    now = time.time()
    with connect(settings) as conn:
        for order, (mid, _title, _desc, pinned) in enumerate(MODULES):
            conn.execute(
                'INSERT OR IGNORE INTO v8_module_settings(campaign_id,module_id,enabled,pinned,sort_order,updated_at) VALUES(?,?,?,?,?,?)',
                (int(campaign_id), mid, 1, pinned, order, now),
            )


def module_settings(settings: Settings, campaign_id: int) -> list[dict]:
    ensure_campaign_modules(settings, campaign_id)
    saved = {r['module_id']: r for r in _rows(settings, 'SELECT * FROM v8_module_settings WHERE campaign_id=?', (int(campaign_id),))}
    out=[]
    for order,(mid,title,desc,pinned_default) in enumerate(MODULES):
        r=saved.get(mid,{})
        out.append({'id':mid,'title':title,'description':desc,'enabled':bool(r.get('enabled',1)),'pinned':bool(r.get('pinned',pinned_default)),'sort_order':int(r.get('sort_order',order))})
    out.sort(key=lambda x:(x['sort_order'],x['title'].lower()))
    return out


def save_module_settings(settings: Settings, campaign_id: int, rows: list[dict]) -> list[dict]:
    allowed={m[0] for m in MODULES}; now=time.time()
    with connect(settings) as conn:
        for order,row in enumerate(rows or []):
            mid=str(row.get('id') or row.get('module_id') or '').strip()
            if mid not in allowed: continue
            conn.execute('''INSERT INTO v8_module_settings(campaign_id,module_id,enabled,pinned,sort_order,updated_at) VALUES(?,?,?,?,?,?)
                            ON CONFLICT(campaign_id,module_id) DO UPDATE SET enabled=excluded.enabled,pinned=excluded.pinned,sort_order=excluded.sort_order,updated_at=excluded.updated_at''',
                         (int(campaign_id),mid,1 if row.get('enabled',True) else 0,1 if row.get('pinned',False) else 0,int(row.get('sort_order',order)),now))
    return module_settings(settings,campaign_id)


def snapshot(settings: Settings, campaign_id: int, object_type: str, object_key: str, snapshot_data: dict | list | None = None,
             *, label: str = '', source_path: str = '', source_text: str = '', created_by: str = '') -> int:
    now=time.time()
    with connect(settings) as conn:
        cur=conn.execute('''INSERT INTO v8_revisions(campaign_id,object_type,object_key,label,snapshot_json,source_path,source_text,created_by,created_at)
                            VALUES(?,?,?,?,?,?,?,?,?)''',
                         (int(campaign_id),str(object_type)[:80],str(object_key)[:300],str(label)[:300],json.dumps(snapshot_data or {},ensure_ascii=False),str(source_path)[:1000],source_text,str(created_by)[:160],now))
        return int(cur.lastrowid or 0)


def revisions(settings: Settings, campaign_id: int, object_type: str, object_key: str, limit: int = 40) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM v8_revisions WHERE campaign_id=? AND object_type=? AND object_key=? ORDER BY created_at DESC,id DESC LIMIT ?',
               (int(campaign_id),str(object_type),str(object_key),max(1,min(int(limit),100))))
    for r in rows:
        r['snapshot']=_j(r.pop('snapshot_json','{}'),{})
        r['has_source']=bool(r.get('source_path') and r.get('source_text'))
        if r.get('source_text'): r['source_text_preview']=r['source_text'][:800]
        r.pop('source_text',None)
    return rows


def snapshot_source(settings: Settings, campaign_id: int, path: str, *, label: str = 'Before edit', created_by: str = '') -> int | None:
    target=safe_project_path(settings,path)
    if not target.exists() or not target.is_file(): return None
    text=target.read_text(encoding='utf-8',errors='replace')
    return snapshot(settings,campaign_id,'source',path,{'sha256':_hash_text(text)},label=label,source_path=path,source_text=text,created_by=created_by)


def restore_source_revision(settings: Settings, campaign_id: int, revision_id: int, *, created_by: str = '') -> dict:
    row=_row(settings,'SELECT * FROM v8_revisions WHERE id=? AND campaign_id=? AND object_type=?',(int(revision_id),int(campaign_id),'source'))
    if not row or not row.get('source_path'): raise ValueError('Source revision not found.')
    path=str(row['source_path']); target=safe_project_path(settings,path)
    current=target.read_text(encoding='utf-8',errors='replace') if target.exists() else ''
    snapshot(settings,campaign_id,'source',path,{'sha256':_hash_text(current)},label='Before restore',source_path=path,source_text=current,created_by=created_by)
    result=save_text_file(settings,path,str(row.get('source_text') or ''))
    return {'ok':True,'path':path,'result':result}


def source_structure(text: str) -> list[dict]:
    out=[]
    levels={'part':0,'chapter':1,'section':2,'subsection':3,'subsubsection':4}
    matches=list(_HEADING_RE.finditer(text))
    for idx,m in enumerate(matches):
        command=m.group(1).lower(); title=re.sub(r'\\[A-Za-z@]+\*?(?:\[[^\]]*\])?','',m.group(2)).strip()
        end=matches[idx+1].start() if idx+1<len(matches) else len(text)
        segment=text[m.end():end]
        out.append({'command':command,'level':levels[command],'title':title,'start':m.start(),'end':end,
                    'feat_count':len(re.findall(r'\\feat\s*\{',segment)),
                    'action_count':len(re.findall(r'\\(?:action|activity)\s*\{',segment)),
                    'word_count':len(re.findall(r"\b[\w'’-]+\b",re.sub(r'\\[A-Za-z@]+',' ',segment)))})
    return out


def source_map(settings: Settings, campaign_id: int, entities: list[dict] | None = None) -> dict:
    entity_rows=entities if entities is not None else list_entities(settings,campaign_id,tracked_only=True)
    by_source={}
    for e in entity_rows:
        # Source ownership is a property of the object, not of one particular
        # backend source_type.  This also keeps a source-linked Forge/Foundry
        # representation attached to the same LaTeX file instead of duplicating
        # the object merely to make Source Map work.
        data=e.get('data') or {}; path=str(data.get('source_path') or data.get('source_link_path') or '').replace('\\','/').strip('/')
        if path: by_source.setdefault(path,[]).append(e)
    files=[]; warnings=[]; include_targets=set()
    for path in sorted(settings.project_dir.rglob('*.tex')):
        rel=path.relative_to(settings.project_dir).as_posix()
        try:text=path.read_text(encoding='utf-8',errors='replace')
        except OSError:continue
        headings=source_structure(text)
        includes=[]
        for raw in _INCLUDE_RE.findall(text):
            inc=raw.strip(); inc=inc if inc.lower().endswith('.tex') else inc+'.tex'; includes.append(inc); include_targets.add(inc)
        root=next((h for h in headings if h['command'] in {'part','chapter'}),headings[0] if headings else None)
        if not headings and text.strip(): warnings.append({'severity':'info','path':rel,'message':'No structural LaTeX headings detected.'})
        files.append({'path':rel,'root':root,'headings':headings,'includes':includes,'entity_ids':[int(e['id']) for e in by_source.get(rel,[])],
                      'sha256':_hash_text(text),'bytes':len(text.encode('utf-8'))})
    paths={f['path'] for f in files}
    for f in files:
        for inc in f['includes']:
            # Resolve includes relative to the including file as well as project root.
            candidate=(Path(f['path']).parent/inc).as_posix()
            if inc not in paths and candidate not in paths: warnings.append({'severity':'warning','path':f['path'],'message':f'Included source not found: {inc}'})
    return {'files':files,'warnings':warnings,'count':len(files)}


def refresh_source_mappings(settings: Settings, campaign_id: int, entities: list[dict] | None = None) -> int:
    entities=entities if entities is not None else list_entities(settings,campaign_id,tracked_only=True)
    smap=source_map(settings,campaign_id,entities)
    entity_by_id={int(e['id']):e for e in entities}; count=0; now=time.time()
    with connect(settings) as conn:
        for f in smap['files']:
            for eid in f['entity_ids']:
                if eid not in entity_by_id: continue
                root=f.get('root') or {}
                conn.execute('''INSERT INTO v8_source_mappings(campaign_id,entity_id,source_path,root_command,root_title,structure_json,source_hash,updated_at)
                                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id,entity_id,source_path) DO UPDATE SET root_command=excluded.root_command,root_title=excluded.root_title,structure_json=excluded.structure_json,source_hash=excluded.source_hash,updated_at=excluded.updated_at''',
                             (int(campaign_id),eid,f['path'],root.get('command',''),root.get('title',''),json.dumps(f['headings'],ensure_ascii=False),f['sha256'],now));count+=1
    return count


def link_object(settings: Settings, campaign_id: int, entity_id: int, link_type: str, target_key: str, *, label: str = '', data: dict | None = None) -> dict:
    now=time.time()
    with connect(settings) as conn:
        conn.execute('''INSERT INTO v8_object_links(campaign_id,entity_id,link_type,target_key,label,data_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)
                        ON CONFLICT(campaign_id,link_type,target_key,entity_id) DO UPDATE SET label=excluded.label,data_json=excluded.data_json,updated_at=excluded.updated_at''',
                     (int(campaign_id),int(entity_id),str(link_type)[:80],str(target_key)[:300],str(label)[:300],json.dumps(data or {},ensure_ascii=False),now,now))
    return object_links(settings,campaign_id,entity_id)[-1] if object_links(settings,campaign_id,entity_id) else {}


def object_links(settings: Settings, campaign_id: int, entity_id: int) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM v8_object_links WHERE campaign_id=? AND entity_id=? ORDER BY link_type,label,target_key',(int(campaign_id),int(entity_id)))
    for r in rows:r['data']=_j(r.pop('data_json','{}'),{})
    return rows


def link_handout(settings: Settings, handout_id: int, entity_id: int, relation: str = 'about') -> None:
    with connect(settings) as conn:
        conn.execute('INSERT OR IGNORE INTO v8_handout_links(handout_id,entity_id,relation,created_at) VALUES(?,?,?,?)',(int(handout_id),int(entity_id),str(relation)[:80],time.time()))


def entity_inspector(settings: Settings, campaign_id: int, entity_id: int) -> dict:
    entity=get_entity(settings,campaign_id,entity_id)
    if not entity: raise ValueError('Entity not found.')
    mappings=_rows(settings,'SELECT * FROM v8_source_mappings WHERE campaign_id=? AND entity_id=? ORDER BY source_path',(int(campaign_id),int(entity_id)))
    for r in mappings:r['structure']=_j(r.pop('structure_json','[]'),[])
    handouts=_rows(settings,'''SELECT h.*,l.relation FROM v8_handout_links l JOIN handouts h ON h.id=l.handout_id WHERE l.entity_id=? ORDER BY h.updated_at DESC''',(int(entity_id),))
    maps=_rows(settings,'''SELECT ol.*,m.name AS map_name,m.slug AS map_slug,mk.title AS marker_title FROM v8_object_links ol
                           LEFT JOIN markers mk ON ol.link_type='map_marker' AND CAST(ol.target_key AS INTEGER)=mk.id
                           LEFT JOIN maps m ON m.id=mk.map_id WHERE ol.campaign_id=? AND ol.entity_id=? AND ol.link_type='map_marker' ORDER BY ol.updated_at DESC''',(int(campaign_id),int(entity_id)))
    return {'entity':entity,'links':object_links(settings,campaign_id,entity_id),'source_mappings':mappings,'handouts':handouts,'maps':maps,
            'versions':entity_versions(settings,entity_id,20),'foundry':sync_link(settings,entity_id)}


def workflow(settings: Settings, campaign_id: int, session_id: int) -> dict:
    row=_row(settings,'SELECT * FROM v8_session_workflow WHERE campaign_id=? AND session_id=?',(int(campaign_id),int(session_id)))
    if not row:
        now=time.time()
        with connect(settings) as conn:
            conn.execute('INSERT OR IGNORE INTO v8_session_workflow(session_id,campaign_id,stage,prep_json,run_json,chronicle_json,updated_at) VALUES(?,?,?,?,?,?,?)',(int(session_id),int(campaign_id),'prep','{}','{}','{}',now))
        row=_row(settings,'SELECT * FROM v8_session_workflow WHERE campaign_id=? AND session_id=?',(int(campaign_id),int(session_id))) or {}
    row['prep']=_j(row.pop('prep_json','{}'),{}); row['run']=_j(row.pop('run_json','{}'),{}); row['chronicle']=_j(row.pop('chronicle_json','{}'),{})
    row['touches']=session_touches(settings,campaign_id,session_id)
    return row


def save_workflow(settings: Settings, campaign_id: int, session_id: int, payload: dict, *, actor: str = '') -> dict:
    current=workflow(settings,campaign_id,session_id)
    snapshot(settings,campaign_id,'session_workflow',str(session_id),current,label=f"Before {payload.get('stage') or current.get('stage') or 'workflow'} update",created_by=actor)
    stage=str(payload.get('stage') or current.get('stage') or 'prep').lower()
    if stage not in {'prep','run','chronicle','closed'}: stage='prep'
    prep=payload.get('prep') if isinstance(payload.get('prep'),dict) else current.get('prep',{})
    run=payload.get('run') if isinstance(payload.get('run'),dict) else current.get('run',{})
    chron=payload.get('chronicle') if isinstance(payload.get('chronicle'),dict) else current.get('chronicle',{})
    now=time.time(); started=current.get('started_at'); ended=current.get('ended_at')
    if stage=='run' and not started: started=now
    if stage in {'chronicle','closed'} and not ended: ended=now
    with connect(settings) as conn:
        conn.execute('''UPDATE v8_session_workflow SET stage=?,prep_json=?,run_json=?,chronicle_json=?,started_at=?,ended_at=?,updated_at=? WHERE session_id=? AND campaign_id=?''',
                     (stage,json.dumps(prep,ensure_ascii=False),json.dumps(run,ensure_ascii=False),json.dumps(chron,ensure_ascii=False),started,ended,now,int(session_id),int(campaign_id)))
    return workflow(settings,campaign_id,session_id)


def record_touch(settings: Settings, campaign_id: int, session_id: int, target_type: str, target_key: str, action: str = 'opened', meta: dict | None = None) -> dict:
    now=time.time()
    with connect(settings) as conn:
        conn.execute('''INSERT INTO v8_session_touches(campaign_id,session_id,target_type,target_key,action,meta_json,created_at) VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(session_id,target_type,target_key,action) DO UPDATE SET meta_json=excluded.meta_json,created_at=excluded.created_at''',
                     (int(campaign_id),int(session_id),str(target_type)[:80],str(target_key)[:300],str(action)[:80],json.dumps(meta or {},ensure_ascii=False),now))
    return {'ok':True,'target_type':target_type,'target_key':target_key,'action':action}


def session_touches(settings: Settings, campaign_id: int, session_id: int) -> list[dict]:
    rows=_rows(settings,'SELECT * FROM v8_session_touches WHERE campaign_id=? AND session_id=? ORDER BY created_at,id',(int(campaign_id),int(session_id)))
    for r in rows:r['meta']=_j(r.pop('meta_json','{}'),{})
    return rows


def duplicates(settings: Settings, campaign_id: int) -> list[dict]:
    """Duplicate names among deliberate campaign objects only.

    Structural Codex headings are intentionally excluded; otherwise a repeated
    heading such as "History" or "Culture" produces meaningless warnings.
    """
    buckets={}
    for e in list_entities(settings,campaign_id,tracked_only=True):
        key=str(e.get('name') or '').strip().casefold()
        if not key:continue
        buckets.setdefault(key,[]).append(e)
    rows=[]
    for key,items in buckets.items():
        if len(items)<2:continue
        rows.append({'key':key,'n':len(items),'ids':[int(x['id']) for x in items],
                     'kinds':','.join(str(x.get('kind') or '') for x in items),'name':items[0].get('name') or key})
    rows.sort(key=lambda r:(-int(r['n']),str(r['name']).casefold()))
    return rows


def diagnostics(settings: Settings, campaign_id: int, *, foundry: dict | None = None, wiki: dict | None = None) -> dict:
    checks=[]
    try:
        with connect(settings) as conn:
            conn.execute('SELECT 1').fetchone(); fk=conn.execute('PRAGMA foreign_key_check').fetchall()
        checks.append({'id':'database','label':'Database','status':'ok' if not fk else 'warning','detail':'SQLite healthy.' if not fk else f'{len(fk)} foreign-key issue(s).'})
    except Exception as exc: checks.append({'id':'database','label':'Database','status':'error','detail':str(exc)})
    sm=source_map(settings,campaign_id,list_entities(settings,campaign_id,tracked_only=True)); sw=sm['warnings']
    checks.append({'id':'sources','label':'LaTeX sources','status':'warning' if any(x['severity']=='warning' for x in sw) else 'ok','detail':f"{sm['count']} .tex files · {len(sw)} parser notice(s)."})
    dup=duplicates(settings,campaign_id);checks.append({'id':'duplicates','label':'Duplicate tracked objects','status':'warning' if dup else 'ok','detail':f'{len(dup)} duplicate name group(s).' if dup else 'No duplicate tracked-object names detected.'})
    failed=_row(settings,"SELECT COUNT(*) AS n FROM foundry_command_queue WHERE campaign_id=? AND status='failed'",(int(campaign_id),)) or {'n':0}
    fs=foundry or {};last=float(fs.get('updated_at') or fs.get('received_at') or 0);age=max(0,time.time()-last) if last else None
    if not fs: fstatus='warning';fdetail='No Foundry bridge state received yet.'
    elif age is not None and age>120: fstatus='warning';fdetail=f'Bridge last seen {int(age)}s ago · {failed["n"]} failed command(s).'
    else: fstatus='ok' if not int(failed['n']) else 'warning';fdetail=f'Bridge connected · {failed["n"]} failed command(s).'
    checks.append({'id':'foundry','label':'Foundry Bridge','status':fstatus,'detail':fdetail})
    store=storage_report(settings); free_pct=(store['free_bytes']/store['total_bytes']*100) if store['total_bytes'] else 100
    checks.append({'id':'storage','label':'Storage','status':'warning' if free_pct<10 else 'ok','detail':f"{store['project_bytes']//1024//1024} MB campaign · {free_pct:.0f}% disk free."})
    warnings=dependency_warnings(settings,campaign_id)
    checks.append({'id':'continuity','label':'Continuity','status':'warning' if warnings else 'ok','detail':f'{len(warnings)} dependency warning(s).' if warnings else 'No active dependency warnings.'})
    version=(settings.root_dir/'VERSION').read_text(encoding='utf-8').strip() if (settings.root_dir/'VERSION').exists() else '9.0.3'
    return {'version':version,'checks':checks,'source_warnings':sw,'duplicates':dup,'storage':store,'dependency_warnings':warnings,'audit':recent_audit(settings,campaign_id,20)}


def command_catalog(settings: Settings, campaign_id: int, wiki: dict, query: str = '') -> list[dict]:
    q=str(query or '').strip().casefold(); items=[]
    commands=[
        ('Open Campaign Workspace','Campaign dashboard','/app/v8','workspace dashboard command'),
        ('Start / run session','Prep → Run → Chronicle','/app/v8#session','session run start'),
        ('Open Table App','Live party resources and table tools','/app','table life hp'),
        ('Create Homebrew','Ancestry, archetype, feat, item or action','/gm/foundry-workshop','homebrew forge create ancestry archetype'),
        ('Open Source Map','LaTeX structure and ownership','/app/v8#sources','latex source map studio'),
        ('System diagnostics','Bridge, parser, duplicates and storage','/app/v8#diagnostics','diagnostics system health'),
        ('Create handout','Campaign-connected handout workshop','/handout-creator','handout letter poster dossier'),
        ('Open Atlas','Interactive campaign maps','/#atlas','map atlas world region city dungeon'),
    ]
    for title,sub,href,keywords in commands:items.append({'type':'command','title':title,'subtitle':sub,'href':href,'search':f'{title} {sub} {keywords}'.casefold()})
    for e in list_entities(settings,campaign_id,tracked_only=True):items.append({'type':e.get('kind') or 'object','title':e.get('name') or 'Campaign object','subtitle':e.get('subtitle') or e.get('summary') or 'Tracked campaign object','href':f"/entity/{e['id']}",'search':f"{e.get('name','')} {e.get('subtitle','')} {e.get('summary','')} {' '.join(e.get('tags') or [])}".casefold()})
    for p in wiki.get('pages',[]) or []:items.append({'type':'codex','title':p.get('title') or p.get('slug'),'subtitle':p.get('chapter') or 'Codex','href':f"/lore/{p.get('slug')}",'search':f"{p.get('title','')} {p.get('chapter','')} {p.get('excerpt','')}".casefold()})
    for r in _rows(settings,'SELECT id,title,session_number,session_date,status FROM campaign_sessions WHERE campaign_id=? ORDER BY updated_at DESC',(int(campaign_id),)):
        items.append({'type':'session','title':r.get('title') or f"Session {r.get('session_number') or ''}",'subtitle':f"{r.get('status','')} · {r.get('session_date','')}",'href':f"/app/v8#session/{r['id']}",'search':f"session {r.get('title','')} {r.get('session_number','')} {r.get('status','')}".casefold()})
    if not q:return items[:20]
    terms=[x for x in re.findall(r"[\w'’-]+",q) if x]
    scored=[]
    for item in items:
        s=item['search'];score=sum((8 if s.startswith(t) else 3)*s.count(t) for t in terms)
        if q in s:score+=12
        if score:scored.append((score,item))
    scored.sort(key=lambda x:(-x[0],x[1]['title'].casefold()))
    return [{k:v for k,v in item.items() if k!='search'} for _,item in scored[:40]]
