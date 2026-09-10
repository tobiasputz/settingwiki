from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, asdict
from typing import Any, Iterable

from .config import Settings
from .storage import connect

V7_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS v7_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'lore',
    source_type TEXT NOT NULL DEFAULT 'manual',
    source_key TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    subtitle TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    visibility TEXT NOT NULL DEFAULT 'players',
    image_ref TEXT NOT NULL DEFAULT '',
    token_ref TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(campaign_id,source_type,source_key)
);
CREATE INDEX IF NOT EXISTS idx_v7_entities_campaign_kind ON v7_entities(campaign_id,kind,lower(name));
CREATE INDEX IF NOT EXISTS idx_v7_entities_updated ON v7_entities(campaign_id,updated_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS v7_entity_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    source_entity_id INTEGER NOT NULL,
    target_entity_id INTEGER NOT NULL,
    relation TEXT NOT NULL DEFAULT 'related to',
    label TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'players',
    session_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(campaign_id,source_entity_id,target_entity_id,relation),
    FOREIGN KEY(source_entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(target_entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v7_relations_source ON v7_entity_relations(campaign_id,source_entity_id,active);
CREATE INDEX IF NOT EXISTS idx_v7_relations_target ON v7_entity_relations(campaign_id,target_entity_id,active);

CREATE TABLE IF NOT EXISTS v7_entity_sessions (
    entity_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'appeared',
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    PRIMARY KEY(entity_id,session_id,role),
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS v7_entity_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    map_id INTEGER,
    marker_id INTEGER,
    label TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    is_current INTEGER NOT NULL DEFAULT 1,
    session_id INTEGER,
    created_at REAL NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE SET NULL,
    FOREIGN KEY(marker_id) REFERENCES markers(id) ON DELETE SET NULL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v7_locations_entity ON v7_entity_locations(entity_id,is_current,created_at DESC);

CREATE TABLE IF NOT EXISTS v7_entity_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    UNIQUE(entity_id,version_no),
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS v7_foundry_sync_links (
    entity_id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    foundry_uuid TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT '',
    seeker_hash TEXT NOT NULL DEFAULT '',
    foundry_hash TEXT NOT NULL DEFAULT '',
    base_snapshot_json TEXT NOT NULL DEFAULT '{}',
    foundry_snapshot_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'unlinked',
    last_seen_at REAL,
    last_synced_at REAL,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v7_sync_campaign_status ON v7_foundry_sync_links(campaign_id,status,last_seen_at DESC);

CREATE TABLE IF NOT EXISTS v7_encounters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    party_level INTEGER NOT NULL DEFAULT 1,
    party_size INTEGER NOT NULL DEFAULT 4,
    status TEXT NOT NULL DEFAULT 'prepared',
    map_id INTEGER,
    scene_label TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    terrain TEXT NOT NULL DEFAULT '',
    tactics TEXT NOT NULL DEFAULT '',
    reinforcements TEXT NOT NULL DEFAULT '',
    treasure TEXT NOT NULL DEFAULT '',
    secrets TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL,
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v7_encounters_session ON v7_encounters(campaign_id,session_id,status,updated_at DESC);

CREATE TABLE IF NOT EXISTS v7_encounter_creatures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_id INTEGER NOT NULL,
    entity_id INTEGER,
    prepared_content_id INTEGER,
    name TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL DEFAULT 1,
    disposition TEXT NOT NULL DEFAULT 'enemy',
    xp_override INTEGER,
    note TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    FOREIGN KEY(encounter_id) REFERENCES v7_encounters(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE SET NULL,
    FOREIGN KEY(prepared_content_id) REFERENCES foundry_prepared_content(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v7_encounter_creatures_enc ON v7_encounter_creatures(encounter_id,id);

CREATE TABLE IF NOT EXISTS v7_creature_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(campaign_id,name)
);
CREATE INDEX IF NOT EXISTS idx_v7_creature_folders_campaign ON v7_creature_folders(campaign_id,lower(name),id);

CREATE TABLE IF NOT EXISTS v7_creature_folder_members (
    folder_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    PRIMARY KEY(folder_id,entity_id),
    FOREIGN KEY(folder_id) REFERENCES v7_creature_folders(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v7_creature_folder_members_entity ON v7_creature_folder_members(entity_id,folder_id);

CREATE TABLE IF NOT EXISTS v7_loot_pools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER,
    title TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    visibility TEXT NOT NULL DEFAULT 'players',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v7_loot_session ON v7_loot_pools(campaign_id,session_id,status,updated_at DESC);

CREATE TABLE IF NOT EXISTS v7_loot_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pool_id INTEGER NOT NULL,
    entity_id INTEGER,
    prepared_content_id INTEGER,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1,
    claimed_quantity INTEGER NOT NULL DEFAULT 0,
    visibility TEXT NOT NULL DEFAULT 'players',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(pool_id) REFERENCES v7_loot_pools(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE SET NULL,
    FOREIGN KEY(prepared_content_id) REFERENCES foundry_prepared_content(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS v7_loot_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loot_item_id INTEGER NOT NULL,
    invite_id INTEGER,
    character_id INTEGER,
    quantity INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'claimed',
    foundry_command_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(loot_item_id) REFERENCES v7_loot_items(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE SET NULL,
    FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE SET NULL,
    FOREIGN KEY(foundry_command_id) REFERENCES foundry_command_queue(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v7_loot_claim_item ON v7_loot_claims(loot_item_id,status,created_at DESC);

CREATE TABLE IF NOT EXISTS v7_knowledge_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    tier TEXT NOT NULL DEFAULT 'known',
    mechanics_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v7_facts_entity ON v7_knowledge_facts(entity_id,tier,sort_order,id);

CREATE TABLE IF NOT EXISTS v7_fact_reveals (
    fact_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'revealed',
    disclosure_mode TEXT NOT NULL DEFAULT 'exact',
    reveal_source TEXT NOT NULL DEFAULT 'gm',
    shared_by_invite_id INTEGER,
    session_id INTEGER,
    revealed_at REAL NOT NULL,
    PRIMARY KEY(fact_id,invite_id),
    FOREIGN KEY(fact_id) REFERENCES v7_knowledge_facts(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE,
    FOREIGN KEY(shared_by_invite_id) REFERENCES player_invites(id) ON DELETE SET NULL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS v7_player_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    metric TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    lower_bound REAL,
    upper_bound REAL,
    visibility TEXT NOT NULL DEFAULT 'private',
    status TEXT NOT NULL DEFAULT 'inferred',
    data_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v7_observations_entity ON v7_player_observations(campaign_id,entity_id,visibility,updated_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_v7_observations_invite ON v7_player_observations(campaign_id,invite_id,updated_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS v7_recall_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    invite_id INTEGER,
    character_id INTEGER,
    skill TEXT NOT NULL DEFAULT '',
    result INTEGER,
    dc INTEGER,
    degree TEXT NOT NULL DEFAULT '',
    revealed_fact_ids_json TEXT NOT NULL DEFAULT '[]',
    session_id INTEGER,
    created_at REAL NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE SET NULL,
    FOREIGN KEY(character_id) REFERENCES player_characters(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS v7_session_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'event',
    entity_id INTEGER,
    target_type TEXT NOT NULL DEFAULT '',
    target_key TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'proposed',
    visible_to_players INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    applied_at REAL,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v7_changes_session ON v7_session_changes(campaign_id,session_id,status,created_at,id);

CREATE TABLE IF NOT EXISTS v7_relationship_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    source_entity_id INTEGER NOT NULL,
    target_entity_id INTEGER NOT NULL,
    state TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    session_id INTEGER,
    sort_key REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    FOREIGN KEY(source_entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(target_entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE,
    FOREIGN KEY(session_id) REFERENCES campaign_sessions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_v7_relationship_timeline ON v7_relationship_states(campaign_id,source_entity_id,target_entity_id,sort_key,created_at);

CREATE TABLE IF NOT EXISTS v7_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    source_entity_id INTEGER,
    source_field TEXT NOT NULL DEFAULT 'status',
    operator TEXT NOT NULL DEFAULT 'equals',
    expected_value TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT 'session',
    target_key TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(source_entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS v7_role_permissions (
    role TEXT NOT NULL,
    permission TEXT NOT NULL,
    allowed INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY(role,permission)
);
CREATE TABLE IF NOT EXISTS v7_invite_permissions (
    campaign_id INTEGER NOT NULL,
    invite_id INTEGER NOT NULL,
    permission TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(campaign_id,invite_id,permission),
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS v7_token_recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(campaign_id,name)
);

CREATE TABLE IF NOT EXISTS v7_asset_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    asset_ref TEXT NOT NULL,
    entity_id INTEGER,
    purpose TEXT NOT NULL DEFAULT 'image',
    source_label TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    UNIQUE(campaign_id,asset_ref,entity_id,purpose),
    FOREIGN KEY(entity_id) REFERENCES v7_entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_v7_asset_ref ON v7_asset_refs(campaign_id,asset_ref);

CREATE TABLE IF NOT EXISTS v7_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    actor_label TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_key TEXT NOT NULL DEFAULT '',
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v7_audit_campaign ON v7_audit_log(campaign_id,created_at DESC,id DESC);
'''

DEFAULT_PERMISSIONS = {
    'owner': {
        'view_statblocks','create_player_notes','share_player_knowledge','manage_own_inventory','push_foundry_character','reveal_lore','edit_entities',
        'edit_monsters','manage_sessions','edit_canon','manage_encounters','manage_loot','manage_permissions','manage_integrations'
    },
    'co-gm': {
        'view_statblocks','create_player_notes','share_player_knowledge','manage_own_inventory','push_foundry_character','reveal_lore','edit_entities',
        'edit_monsters','manage_sessions','manage_encounters','manage_loot'
    },
    'player': {'create_player_notes','share_player_knowledge','manage_own_inventory','push_foundry_character'},
    'spectator': set(),
}
ALL_PERMISSIONS = sorted(set().union(*DEFAULT_PERMISSIONS.values()))

XP_BY_DELTA = {-4:10,-3:15,-2:20,-1:30,0:40,1:60,2:80,3:120,4:160}
PWL_XP_BY_DELTA = {-7:9,-6:12,-5:14,-4:18,-3:21,-2:26,-1:32,0:40,1:48,2:60,3:72,4:90,5:108,6:135,7:160}
DIFFICULTY_BUDGETS = [('Trivial',40),('Low',60),('Moderate',80),('Severe',120),('Extreme',160)]
TIER_ORDER = {'unknown':0,'rumored':1,'known':2,'full':3}
DISCLOSURE_MODES = {'exact','vague','comparative'}
DISCLOSURE_RANK = {'vague':1,'comparative':1,'exact':2}
OBSERVATION_KINDS = {'note','range','comparative','hypothesis'}
CREATURE_KINDS = {'monster','creature','npc'}


def _json(raw: Any, default: Any):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or '')
    except Exception:
        return default


def _rows(settings: Settings, sql: str, args: tuple = ()) -> list[dict]:
    with connect(settings) as conn:
        return [dict(r) for r in conn.execute(sql,args).fetchall()]


def _row(settings: Settings, sql: str, args: tuple = ()) -> dict | None:
    with connect(settings) as conn:
        r=conn.execute(sql,args).fetchone()
    return dict(r) if r else None


def _hash(obj: Any) -> str:
    raw=json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return hashlib.blake2b(raw,digest_size=16).hexdigest()


def _entity_in_campaign(settings: Settings,campaign_id:int,entity_id:int|None)->bool:
    if not entity_id:return False
    return _row(settings,'SELECT id FROM v7_entities WHERE id=? AND campaign_id=?',(int(entity_id),int(campaign_id))) is not None


def _session_in_campaign(settings: Settings,campaign_id:int,session_id:int|None)->bool:
    if session_id is None:return True
    return _row(settings,'SELECT id FROM campaign_sessions WHERE id=? AND campaign_id=?',(int(session_id),int(campaign_id))) is not None


def _prepared_in_campaign(settings: Settings,campaign_id:int,prepared_id:int|None)->bool:
    if prepared_id is None:return True
    return _row(settings,'SELECT id FROM foundry_prepared_content WHERE id=? AND campaign_id=?',(int(prepared_id),int(campaign_id))) is not None


def _invite_in_campaign(settings: Settings,campaign_id:int,invite_id:int|None)->bool:
    if invite_id is None:return False
    return _row(settings,'SELECT 1 AS ok FROM campaign_memberships WHERE campaign_id=? AND invite_id=?',(int(campaign_id),int(invite_id))) is not None


def init_v7_db(settings: Settings) -> None:
    # A major-version migration should always leave a recovery point. Use
    # SQLite's backup API rather than copying only the main database file: that
    # also captures committed WAL content when Railway is using WAL mode.
    marker=settings.data_dir/'.v7-schema-initialized'
    if not marker.exists() and settings.db_path.exists():
        backup_dir=settings.data_dir/'migration-backups';backup_dir.mkdir(parents=True,exist_ok=True)
        target=backup_dir/f'pre-v7-{time.strftime("%Y%m%d-%H%M%S")}.sqlite'
        try:
            with sqlite3.connect(settings.db_path) as src, sqlite3.connect(target) as dst:
                src.backup(dst)
        except (OSError, sqlite3.Error):
            # The migration itself is still additive; failure to create the
            # convenience backup must not make an otherwise healthy database
            # permanently unbootable.
            try: shutil.copy2(settings.db_path,target)
            except OSError: pass
    with connect(settings) as conn:
        conn.executescript(V7_SCHEMA)
        # Early V7 development builds used invite-global overrides. Migrate
        # them into the selected campaign only if such a table is encountered.
        invite_cols={r['name'] for r in conn.execute('PRAGMA table_info(v7_invite_permissions)').fetchall()}
        if invite_cols and 'campaign_id' not in invite_cols:
            conn.execute('ALTER TABLE v7_invite_permissions RENAME TO v7_invite_permissions_legacy')
            conn.execute('''CREATE TABLE v7_invite_permissions (
                campaign_id INTEGER NOT NULL, invite_id INTEGER NOT NULL,
                permission TEXT NOT NULL, allowed INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(campaign_id,invite_id,permission),
                FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
            )''')
            # Preserve overrides for every campaign the invite belongs to.
            conn.execute('''INSERT OR IGNORE INTO v7_invite_permissions(campaign_id,invite_id,permission,allowed,updated_at)
                            SELECT cm.campaign_id,p.invite_id,p.permission,p.allowed,p.updated_at
                            FROM v7_invite_permissions_legacy p
                            JOIN campaign_memberships cm ON cm.invite_id=p.invite_id''')
            conn.execute('DROP TABLE v7_invite_permissions_legacy')
        # V7.0.3 adds disclosure fidelity and party-sharing metadata without
        # rebuilding the reveal table, preserving every existing knowledge reveal.
        reveal_cols={r['name'] for r in conn.execute('PRAGMA table_info(v7_fact_reveals)').fetchall()}
        if 'disclosure_mode' not in reveal_cols:
            conn.execute("ALTER TABLE v7_fact_reveals ADD COLUMN disclosure_mode TEXT NOT NULL DEFAULT 'exact'")
        if 'reveal_source' not in reveal_cols:
            conn.execute("ALTER TABLE v7_fact_reveals ADD COLUMN reveal_source TEXT NOT NULL DEFAULT 'gm'")
        if 'shared_by_invite_id' not in reveal_cols:
            conn.execute('ALTER TABLE v7_fact_reveals ADD COLUMN shared_by_invite_id INTEGER')
        now=time.time()
        for role, allowed in DEFAULT_PERMISSIONS.items():
            for permission in ALL_PERMISSIONS:
                conn.execute('''INSERT OR IGNORE INTO v7_role_permissions(role,permission,allowed,updated_at) VALUES(?,?,?,?)''',
                             (role,permission,1 if permission in allowed else 0,now))
    try: marker.write_text('Seeker 7 schema initialized\n',encoding='utf-8')
    except OSError: pass


def audit(settings: Settings,campaign_id:int,actor_label:str,action:str,target_type:str='',target_key:str='',before:Any=None,after:Any=None)->None:
    with connect(settings) as conn:
        conn.execute('''INSERT INTO v7_audit_log(campaign_id,actor_label,action,target_type,target_key,before_json,after_json,created_at)
                        VALUES(?,?,?,?,?,?,?,?)''',(int(campaign_id),str(actor_label or '')[:160],str(action)[:120],str(target_type)[:80],str(target_key)[:240],json.dumps(before or {},ensure_ascii=False),json.dumps(after or {},ensure_ascii=False),time.time()))


def recent_audit(settings: Settings,campaign_id:int,limit:int=50)->list[dict]:
    out=_rows(settings,'SELECT * FROM v7_audit_log WHERE campaign_id=? ORDER BY created_at DESC,id DESC LIMIT ?',(int(campaign_id),max(1,min(int(limit),200))))
    for r in out:
        r['before']=_json(r.pop('before_json','{}'),{});r['after']=_json(r.pop('after_json','{}'),{})
    return out


def entity_payload(row: dict) -> dict:
    out=dict(row)
    out['tags']=_json(out.pop('tags_json','[]'),[])
    out['data']=_json(out.pop('data_json','{}'),{})
    return out


def entity_allows_public_statblock(entity:dict)->bool:
    data=entity.get('data') if isinstance(entity.get('data'),dict) else {}
    mode=str(data.get('codex_visibility') or data.get('statblock_visibility') or '').strip().lower()
    published=bool(data.get('publish_codex') or data.get('codex_publish'))
    return published and mode in {'full','statblock','full_statblock'}


def player_entity_view(settings: Settings,entity:dict,invite_id:int|None,*,can_view_statblock:bool=False)->dict:
    """Return a player-safe entity projection.

    V7 entities can mirror GM-authored Foundry prep payloads, so returning a raw
    entity row to a player would expose hidden mechanics even when the HTML
    dossier only renders field notes. Keep the public API safe as well.
    """
    out=dict(entity)
    full_stats=bool(can_view_statblock or entity_allows_public_statblock(out))
    data=dict(out.get('data') or {})
    for key in list(data):
        if str(key).lower().startswith('gm_') or str(key).lower() in {'gmnotes','private_notes','secret_notes'}:
            data.pop(key,None)
    if str(out.get('kind') or '').lower() in CREATURE_KINDS and not full_stats:
        safe_keys={'codex_blurb','codex_category','public_notes','public_description','size','rarity','traits','legacy_source','prepared_content_id','publish_codex','codex_publish','codex_visibility'}
        data={k:v for k,v in data.items() if k in safe_keys}
        # The detailed body of a prepared creature often contains full rules.
        public_blurb=str(data.get('codex_blurb') or data.get('public_description') or data.get('public_notes') or out.get('summary') or '')
        out['summary']=public_blurb
        out['body']=public_blurb
    out['data']=data
    out['facts']=visible_entity_facts(settings,int(out['id']),invite_id,gm=False)
    out['visible_facts']=out['facts']
    out['relations']=[r for r in (out.get('relations') or []) if str(r.get('visibility') or 'players')!='gm']
    # These tables currently have no per-row visibility column; avoid leaking
    # GM location/session bookkeeping through the JSON API.
    out.pop('locations',None);out.pop('sessions',None);out.pop('sync',None)
    return out


def list_entities(settings: Settings,campaign_id:int,*,include_hidden:bool=True,kind:str='',query:str='')->list[dict]:
    sql='SELECT * FROM v7_entities WHERE campaign_id=?';args:[Any]=[int(campaign_id)]
    if not include_hidden:
        sql+=" AND visibility!='gm'"
    if kind:
        sql+=' AND kind=?';args.append(str(kind))
    q=str(query or '').strip().lower()
    if q:
        sql+=' AND (lower(name) LIKE ? OR lower(summary) LIKE ? OR lower(tags_json) LIKE ?)';like=f'%{q}%';args.extend([like,like,like])
    sql+=' ORDER BY CASE status WHEN \'active\' THEN 0 ELSE 1 END, lower(name),id'
    return [entity_payload(r) for r in _rows(settings,sql,tuple(args))]


def get_entity(settings: Settings,campaign_id:int,entity_id:int)->dict|None:
    row=_row(settings,'SELECT * FROM v7_entities WHERE campaign_id=? AND id=?',(int(campaign_id),int(entity_id)))
    if not row:return None
    out=entity_payload(row)
    out['relations']=entity_relations(settings,campaign_id,int(entity_id))
    out['facts']=knowledge_facts(settings,int(entity_id))
    out['locations']=_rows(settings,'SELECT * FROM v7_entity_locations WHERE entity_id=? ORDER BY is_current DESC,created_at DESC,id DESC',(int(entity_id),))
    out['sessions']=_rows(settings,'''SELECT es.*,s.title AS session_title,s.session_number,s.session_date FROM v7_entity_sessions es
                                     LEFT JOIN campaign_sessions s ON s.id=es.session_id WHERE es.entity_id=? ORDER BY s.session_number DESC,s.id DESC''',(int(entity_id),))
    out['sync']=sync_link(settings,int(entity_id))
    return out


def save_entity(settings: Settings,campaign_id:int,payload:dict,*,actor_label:str='')->dict:
    eid=int(payload.get('id') or 0);before=get_entity(settings,campaign_id,eid) if eid else None
    name=str(payload.get('name') or '').strip()[:200]
    if not name:raise ValueError('Entity name is required.')
    kind=str(payload.get('kind') or 'lore').strip().lower()[:60]
    source_type=str(payload.get('source_type') or ('manual' if not eid else (before or {}).get('source_type','manual')))[:80]
    source_key=str(payload.get('source_key') or ('manual:'+str(eid) if eid else 'manual:'+hashlib.blake2b(f'{time.time()}:{name}'.encode(),digest_size=8).hexdigest()))[:300]
    tags=payload.get('tags') if isinstance(payload.get('tags'),list) else [x.strip() for x in str(payload.get('tags') or '').split(',') if x.strip()]
    data=payload.get('data') if isinstance(payload.get('data'),dict) else {}
    now=time.time()
    vals=(kind,source_type,source_key,name,str(payload.get('subtitle') or '')[:300],str(payload.get('summary') or '')[:6000],str(payload.get('body') or '')[:60000],str(payload.get('status') or 'active')[:40],str(payload.get('visibility') or 'players')[:40],str(payload.get('image_ref') or '')[:1000],str(payload.get('token_ref') or '')[:1000],json.dumps(tags[:80],ensure_ascii=False),json.dumps(data,ensure_ascii=False),now)
    with connect(settings) as conn:
        if eid:
            cur=conn.execute('''UPDATE v7_entities SET kind=?,source_type=?,source_key=?,name=?,subtitle=?,summary=?,body=?,status=?,visibility=?,image_ref=?,token_ref=?,tags_json=?,data_json=?,updated_at=? WHERE id=? AND campaign_id=?''',vals+(eid,int(campaign_id)))
            if not cur.rowcount:raise ValueError('Entity not found.')
        else:
            cur=conn.execute('''INSERT INTO v7_entities(campaign_id,kind,source_type,source_key,name,subtitle,summary,body,status,visibility,image_ref,token_ref,tags_json,data_json,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(int(campaign_id),)+vals[:-1]+(now,now))
            eid=int(cur.lastrowid or 0)
    after=get_entity(settings,campaign_id,eid) or {}
    _snapshot_entity(settings,eid,actor_label)
    audit(settings,campaign_id,actor_label,'entity.save','entity',str(eid),before,after)
    return after


def _snapshot_entity(settings: Settings,entity_id:int,actor_label:str='')->None:
    row=_row(settings,'SELECT * FROM v7_entities WHERE id=?',(int(entity_id),))
    if not row:return
    snap=entity_payload(row)
    with connect(settings) as conn:
        v=int(conn.execute('SELECT COALESCE(MAX(version_no),0)+1 AS n FROM v7_entity_versions WHERE entity_id=?',(int(entity_id),)).fetchone()['n'])
        conn.execute('INSERT INTO v7_entity_versions(entity_id,version_no,snapshot_json,created_by,created_at) VALUES(?,?,?,?,?)',(int(entity_id),v,json.dumps(snap,ensure_ascii=False),str(actor_label)[:160],time.time()))


def entity_versions(settings: Settings,entity_id:int,limit:int=30)->list[dict]:
    rows=_rows(settings,'SELECT * FROM v7_entity_versions WHERE entity_id=? ORDER BY version_no DESC LIMIT ?',(int(entity_id),max(1,min(int(limit),100))))
    for r in rows:r['snapshot']=_json(r.pop('snapshot_json','{}'),{})
    return rows


def restore_entity_version(settings: Settings,campaign_id:int,entity_id:int,version_id:int,*,actor_label:str='')->dict:
    row=_row(settings,'''SELECT v.* FROM v7_entity_versions v JOIN v7_entities e ON e.id=v.entity_id
                         WHERE v.id=? AND v.entity_id=? AND e.campaign_id=?''',(int(version_id),int(entity_id),int(campaign_id)))
    if not row:raise ValueError('Entity version not found.')
    snap=_json(row.get('snapshot_json'),{})
    current=get_entity(settings,campaign_id,entity_id)
    if not current:raise ValueError('Entity not found.')
    payload={**snap,'id':int(entity_id),'source_type':current.get('source_type'),'source_key':current.get('source_key')}
    out=save_entity(settings,campaign_id,payload,actor_label=actor_label or 'Version restore')
    audit(settings,campaign_id,actor_label or 'Version restore','entity.restore','entity',str(entity_id),current,out)
    return out


def delete_entity(settings: Settings,campaign_id:int,entity_id:int,*,actor_label:str='')->None:
    before=get_entity(settings,campaign_id,entity_id)
    if not before:return
    with connect(settings) as conn:conn.execute('DELETE FROM v7_entities WHERE id=? AND campaign_id=?',(int(entity_id),int(campaign_id)))
    audit(settings,campaign_id,actor_label,'entity.delete','entity',str(entity_id),before,{})


def upsert_source_entity(settings: Settings,campaign_id:int,source_type:str,source_key:str,payload:dict)->dict:
    existing=_row(settings,'SELECT id FROM v7_entities WHERE campaign_id=? AND source_type=? AND source_key=?',(int(campaign_id),str(source_type),str(source_key)))
    if existing:
        current=get_entity(settings,campaign_id,int(existing['id'])) or {}
        desired={
            'kind':payload.get('kind') or 'lore','name':payload.get('name') or '', 'subtitle':payload.get('subtitle') or '',
            'summary':payload.get('summary') or '', 'body':payload.get('body') or '', 'status':payload.get('status') or 'active',
            'visibility':payload.get('visibility') or 'players','image_ref':payload.get('image_ref') or '', 'token_ref':payload.get('token_ref') or '',
            'tags':payload.get('tags') if isinstance(payload.get('tags'),list) else [x.strip() for x in str(payload.get('tags') or '').split(',') if x.strip()],
            'data':payload.get('data') if isinstance(payload.get('data'),dict) else {},
        }
        observed={k:current.get(k) for k in desired}
        if _hash(observed)==_hash(desired):
            return current
    data={**payload,'id':int(existing['id']) if existing else 0,'source_type':source_type,'source_key':source_key}
    return save_entity(settings,campaign_id,data,actor_label='Seeker migration')


def sync_existing_entities(settings: Settings,campaign_id:int,wiki:dict|None=None)->int:
    """Populate the V7 registry from existing first-class Seeker objects without taking ownership of them."""
    count=0
    for p in (wiki or {}).get('pages',[]) or []:
        pres=p.get('presentation') or {}
        upsert_source_entity(settings,campaign_id,'lore',str(p.get('slug') or ''),{
            'kind':'lore','name':p.get('title') or p.get('slug') or 'Lore','subtitle':p.get('chapter') or '',
            'summary':p.get('excerpt') or '', 'body':p.get('plain_text') or '', 'visibility':'gm' if pres.get('visibility')=='hidden' else 'players',
            'image_ref':pres.get('hero_image_url') or pres.get('toc_image_url') or '', 'tags':[p.get('chapter')] if p.get('chapter') else [],
            'data':{'slug':p.get('slug'),'chapter':p.get('chapter'),'legacy_source':'wiki'}
        });count+=1
    # Characters
    for r in _rows(settings,'SELECT id,name,pronouns,ancestry,class_name,summary,portrait_path,status,campaign_id FROM player_characters WHERE campaign_id=?',(int(campaign_id),)):
        upsert_source_entity(settings,campaign_id,'character',str(r['id']),{'kind':'character','name':r.get('name') or 'Character','subtitle':' · '.join(x for x in [r.get('ancestry'),r.get('class_name')] if x), 'summary':r.get('summary') or '', 'status':r.get('status') or 'active','image_ref':r.get('portrait_path') or '', 'visibility':'players','data':{'character_id':r['id'],'pronouns':r.get('pronouns') or ''}});count+=1
    # Prepared content, including bestiary creatures and items.
    for r in _rows(settings,'SELECT * FROM foundry_prepared_content WHERE campaign_id=?',(int(campaign_id),)):
        p=_json(r.get('payload_json'),{})
        kind=str(r.get('kind') or 'item')
        vis='players' if bool(p.get('publish_codex')) else 'gm'
        upsert_source_entity(settings,campaign_id,'foundry_prepared',str(r['id']),{'kind':kind,'name':r.get('title') or 'Prepared content','subtitle':r.get('subtitle') or '', 'summary':r.get('summary') or '', 'body':p.get('description') or '', 'visibility':vis,'image_ref':p.get('img') or '', 'token_ref':p.get('token_img') or '', 'tags':[x.strip() for x in str(r.get('tags') or '').split(',') if x.strip()],'data':{**p,'prepared_content_id':r['id'],'legacy_source':'foundry_prepared'}});count+=1
    return count


def save_relation(settings: Settings,campaign_id:int,payload:dict,*,actor_label:str='')->dict:
    sid=int(payload.get('source_entity_id') or 0);tid=int(payload.get('target_entity_id') or 0)
    if not sid or not tid or sid==tid:raise ValueError('Choose two different entities.')
    if not _entity_in_campaign(settings,campaign_id,sid) or not _entity_in_campaign(settings,campaign_id,tid):raise ValueError('Both entities must belong to this campaign.')
    if payload.get('session_id') is not None and not _session_in_campaign(settings,campaign_id,payload.get('session_id')):raise ValueError('Session does not belong to this campaign.')
    relation=str(payload.get('relation') or 'related to').strip()[:120]
    now=time.time()
    with connect(settings) as conn:
        conn.execute('''INSERT INTO v7_entity_relations(campaign_id,source_entity_id,target_entity_id,relation,label,visibility,session_id,active,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(campaign_id,source_entity_id,target_entity_id,relation)
                        DO UPDATE SET label=excluded.label,visibility=excluded.visibility,session_id=excluded.session_id,active=excluded.active,updated_at=excluded.updated_at''',
                     (int(campaign_id),sid,tid,relation,str(payload.get('label') or '')[:300],str(payload.get('visibility') or 'players'),payload.get('session_id'),1 if payload.get('active',True) else 0,now,now))
    out=_row(settings,'SELECT * FROM v7_entity_relations WHERE campaign_id=? AND source_entity_id=? AND target_entity_id=? AND relation=?',(int(campaign_id),sid,tid,relation)) or {}
    audit(settings,campaign_id,actor_label,'relation.save','relation',str(out.get('id') or ''),{},out)
    return out


def entity_relations(settings: Settings,campaign_id:int,entity_id:int)->list[dict]:
    return _rows(settings,'''SELECT r.*,s.name AS source_name,t.name AS target_name,s.kind AS source_kind,t.kind AS target_kind
                             FROM v7_entity_relations r JOIN v7_entities s ON s.id=r.source_entity_id JOIN v7_entities t ON t.id=r.target_entity_id
                             WHERE r.campaign_id=? AND (r.source_entity_id=? OR r.target_entity_id=?) AND r.active=1 ORDER BY lower(r.relation),r.id''',(int(campaign_id),int(entity_id),int(entity_id)))


def save_relationship_state(settings: Settings,campaign_id:int,payload:dict)->dict:
    sid=int(payload.get('source_entity_id') or 0);tid=int(payload.get('target_entity_id') or 0)
    if not sid or not tid:raise ValueError('Choose two entities.')
    if sid==tid:raise ValueError('Choose two different entities.')
    if not _entity_in_campaign(settings,campaign_id,sid) or not _entity_in_campaign(settings,campaign_id,tid):raise ValueError('Both entities must belong to this campaign.')
    if payload.get('session_id') is not None and not _session_in_campaign(settings,campaign_id,payload.get('session_id')):raise ValueError('Session does not belong to this campaign.')
    now=time.time();sort=float(payload.get('sort_key') or now)
    with connect(settings) as conn:
        cur=conn.execute('''INSERT INTO v7_relationship_states(campaign_id,source_entity_id,target_entity_id,state,label,note,session_id,sort_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)''',
                         (int(campaign_id),sid,tid,str(payload.get('state') or 'changed')[:120],str(payload.get('label') or '')[:200],str(payload.get('note') or '')[:5000],payload.get('session_id'),sort,now))
        rid=int(cur.lastrowid or 0)
    return _row(settings,'SELECT * FROM v7_relationship_states WHERE id=?',(rid,)) or {}


def relationship_timeline(settings: Settings,campaign_id:int,source_entity_id:int,target_entity_id:int)->list[dict]:
    return _rows(settings,'''SELECT rs.*,s.title AS session_title FROM v7_relationship_states rs LEFT JOIN campaign_sessions s ON s.id=rs.session_id
                             WHERE rs.campaign_id=? AND ((source_entity_id=? AND target_entity_id=?) OR (source_entity_id=? AND target_entity_id=?)) ORDER BY sort_key,created_at,id''',
                 (int(campaign_id),int(source_entity_id),int(target_entity_id),int(target_entity_id),int(source_entity_id)))


def knowledge_facts(settings: Settings,entity_id:int)->list[dict]:
    rows=_rows(settings,'SELECT * FROM v7_knowledge_facts WHERE entity_id=? ORDER BY sort_order,id',(int(entity_id),))
    for r in rows:r['mechanics']=_json(r.pop('mechanics_json','{}'),{})
    return rows


def _disclosure_payload(fact:dict,mode:str='exact')->dict:
    # Project one GM-authored fact to one disclosure fidelity. Never send the
    # complete mechanics JSON to players because it can contain exact data.
    mode=str(mode or 'exact').strip().lower()
    if mode not in DISCLOSURE_MODES:mode='exact'
    mechanics=fact.get('mechanics') if isinstance(fact.get('mechanics'),dict) else {}
    disclosures=mechanics.get('disclosures') if isinstance(mechanics.get('disclosures'),dict) else {}
    variant=disclosures.get(mode) if isinstance(disclosures.get(mode),dict) else {}
    if mode=='exact':
        title=str(variant.get('title') or fact.get('title') or '')
        body=str(variant.get('body') or fact.get('body') or '')
    else:
        title=str(variant.get('title') or fact.get('title') or '')
        body=str(variant.get('body') or '')
    out={k:v for k,v in fact.items() if k!='mechanics'}
    out['title']=title;out['body']=body;out['disclosure_mode']=mode
    out['display']={'mode':mode,'category':str(mechanics.get('category') or '')[:80],'metric':str(mechanics.get('metric') or '')[:80]}
    return out


def fact_disclosure_modes(fact:dict)->list[str]:
    mechanics=fact.get('mechanics') if isinstance(fact.get('mechanics'),dict) else {}
    disclosures=mechanics.get('disclosures') if isinstance(mechanics.get('disclosures'),dict) else {}
    modes=['exact']
    for mode in ('vague','comparative'):
        row=disclosures.get(mode) if isinstance(disclosures.get(mode),dict) else {}
        if str(row.get('title') or '').strip() or str(row.get('body') or '').strip():modes.append(mode)
    return modes


def save_knowledge_fact(settings: Settings,entity_id:int,payload:dict,campaign_id:int|None=None)->dict:
    if campaign_id is not None and not _entity_in_campaign(settings,campaign_id,entity_id):raise ValueError('Entity does not belong to this campaign.')
    fid=int(payload.get('id') or 0);now=time.time();tier=str(payload.get('tier') or 'known').lower()
    if tier not in TIER_ORDER:raise ValueError('Unknown knowledge tier.')
    mechanics=payload.get('mechanics') if isinstance(payload.get('mechanics'),dict) else {}
    disclosures=mechanics.get('disclosures') if isinstance(mechanics.get('disclosures'),dict) else {}
    for mode in ('vague','comparative'):
        title=str(payload.get(f'{mode}_title') or '').strip()[:240]
        body=str(payload.get(f'{mode}_body') or '')[:10000]
        if title or body:disclosures[mode]={'title':title,'body':body}
    if disclosures:mechanics={**mechanics,'disclosures':disclosures}
    vals=(str(payload.get('title') or '').strip()[:240],str(payload.get('body') or '')[:10000],tier,json.dumps(mechanics,ensure_ascii=False),int(payload.get('sort_order') or 0),now)
    if not vals[0]:raise ValueError('Fact title is required.')
    with connect(settings) as conn:
        if fid:
            cur=conn.execute('UPDATE v7_knowledge_facts SET title=?,body=?,tier=?,mechanics_json=?,sort_order=?,updated_at=? WHERE id=? AND entity_id=?',vals+(fid,int(entity_id)))
            if not cur.rowcount:raise ValueError('Knowledge fact not found.')
        else:
            cur=conn.execute('INSERT INTO v7_knowledge_facts(entity_id,title,body,tier,mechanics_json,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(int(entity_id),)+vals[:-1]+(now,now));fid=int(cur.lastrowid or 0)
    return next((x for x in knowledge_facts(settings,entity_id) if int(x['id'])==fid),{})


def reveal_fact(settings: Settings,fact_id:int,invite_id:int,session_id:int|None=None,state:str='revealed',campaign_id:int|None=None,disclosure_mode:str='exact',reveal_source:str='gm',shared_by_invite_id:int|None=None)->dict:
    fact_row=_row(settings,'SELECT f.*,e.campaign_id FROM v7_knowledge_facts f JOIN v7_entities e ON e.id=f.entity_id WHERE f.id=?',(int(fact_id),))
    if not fact_row:raise ValueError('Knowledge fact not found.')
    fact=dict(fact_row);fact['mechanics']=_json(fact.pop('mechanics_json','{}'),{})
    actual_campaign=int(fact['campaign_id'])
    if campaign_id is not None and actual_campaign!=int(campaign_id):raise ValueError('Fact does not belong to this campaign.')
    if not _invite_in_campaign(settings,actual_campaign,invite_id):raise ValueError('Player does not belong to this campaign.')
    if session_id is not None and not _session_in_campaign(settings,actual_campaign,session_id):raise ValueError('Session does not belong to this campaign.')
    mode=str(disclosure_mode or 'exact').lower()
    if mode not in DISCLOSURE_MODES:raise ValueError('Choose exact, vague, or comparative disclosure.')
    if mode not in fact_disclosure_modes(fact):raise ValueError(f'This fact has no {mode} disclosure written yet.')
    if shared_by_invite_id is not None and not _invite_in_campaign(settings,actual_campaign,shared_by_invite_id):raise ValueError('Sharing player does not belong to this campaign.')
    now=time.time()
    with connect(settings) as conn:
        existing=conn.execute('SELECT disclosure_mode FROM v7_fact_reveals WHERE fact_id=? AND invite_id=?',(int(fact_id),int(invite_id))).fetchone()
        if existing and str(reveal_source)=='player_share':
            old=str(existing['disclosure_mode'] or 'exact')
            if DISCLOSURE_RANK.get(old,0)>=DISCLOSURE_RANK.get(mode,0):
                row=conn.execute('SELECT * FROM v7_fact_reveals WHERE fact_id=? AND invite_id=?',(int(fact_id),int(invite_id))).fetchone()
                return dict(row) if row else {}
        conn.execute('''INSERT INTO v7_fact_reveals(fact_id,invite_id,state,disclosure_mode,reveal_source,shared_by_invite_id,session_id,revealed_at) VALUES(?,?,?,?,?,?,?,?)
                        ON CONFLICT(fact_id,invite_id) DO UPDATE SET state=excluded.state,disclosure_mode=excluded.disclosure_mode,reveal_source=excluded.reveal_source,shared_by_invite_id=excluded.shared_by_invite_id,session_id=excluded.session_id,revealed_at=excluded.revealed_at''',
                     (int(fact_id),int(invite_id),str(state)[:40],mode,str(reveal_source or 'gm')[:40],shared_by_invite_id,session_id,now))
    return _row(settings,'SELECT * FROM v7_fact_reveals WHERE fact_id=? AND invite_id=?',(int(fact_id),int(invite_id))) or {}


def reveal_fact_to_party(settings: Settings,campaign_id:int,fact_id:int,disclosure_mode:str='exact',session_id:int|None=None,reveal_source:str='gm',shared_by_invite_id:int|None=None)->list[dict]:
    rows=_rows(settings,'SELECT invite_id FROM campaign_memberships WHERE campaign_id=? AND invite_id IS NOT NULL',(int(campaign_id),))
    out=[]
    for row in rows:
        out.append(reveal_fact(settings,fact_id,int(row['invite_id']),session_id,campaign_id=campaign_id,disclosure_mode=disclosure_mode,reveal_source=reveal_source,shared_by_invite_id=shared_by_invite_id))
    return out


def share_revealed_fact(settings: Settings,campaign_id:int,fact_id:int,source_invite_id:int,session_id:int|None=None)->dict:
    if not _invite_in_campaign(settings,campaign_id,source_invite_id):raise ValueError('Player does not belong to this campaign.')
    source=_row(settings,'''SELECT r.* FROM v7_fact_reveals r JOIN v7_knowledge_facts f ON f.id=r.fact_id JOIN v7_entities e ON e.id=f.entity_id
                            WHERE r.fact_id=? AND r.invite_id=? AND e.campaign_id=? AND r.state='revealed' ''',(int(fact_id),int(source_invite_id),int(campaign_id)))
    if not source:raise ValueError('You can only share information that has been revealed to you.')
    rows=reveal_fact_to_party(settings,campaign_id,fact_id,str(source.get('disclosure_mode') or 'exact'),session_id,reveal_source='player_share',shared_by_invite_id=int(source_invite_id))
    return {'ok':True,'count':len(rows),'fact_id':int(fact_id),'disclosure_mode':str(source.get('disclosure_mode') or 'exact')}


def visible_entity_facts(settings: Settings,entity_id:int,invite_id:int|None,*,gm:bool=False)->list[dict]:
    facts=knowledge_facts(settings,entity_id)
    if gm:
        for fact in facts:fact['available_disclosures']=fact_disclosure_modes(fact)
        return facts
    if invite_id is None:return [_disclosure_payload(f,'exact') for f in facts if f.get('tier')=='rumored']
    reveals={int(r['fact_id']):r for r in _rows(settings,"SELECT * FROM v7_fact_reveals WHERE invite_id=? AND state='revealed'",(int(invite_id),))}
    out=[]
    for fact in facts:
        row=reveals.get(int(fact['id']))
        if not row and fact.get('tier')!='rumored':continue
        mode=str((row or {}).get('disclosure_mode') or 'exact')
        projected=_disclosure_payload(fact,mode)
        if row:
            projected['reveal_source']=str(row.get('reveal_source') or 'gm')
            projected['shared_by_invite_id']=row.get('shared_by_invite_id')
            projected['can_share']=True
        else:
            projected['reveal_source']='public';projected['can_share']=False
        out.append(projected)
    return out


def record_recall(settings: Settings,campaign_id:int,entity_id:int,payload:dict)->dict:
    if not _entity_in_campaign(settings,campaign_id,entity_id):raise ValueError('Entity does not belong to this campaign.')
    if payload.get('invite_id') is not None and not _invite_in_campaign(settings,campaign_id,payload.get('invite_id')):raise ValueError('Player does not belong to this campaign.')
    if payload.get('session_id') is not None and not _session_in_campaign(settings,campaign_id,payload.get('session_id')):raise ValueError('Session does not belong to this campaign.')
    result=payload.get('result');dc=payload.get('dc')
    try:result=int(result) if result is not None and str(result)!='' else None
    except Exception:result=None
    try:dc=int(dc) if dc is not None and str(dc)!='' else None
    except Exception:dc=None
    degree=str(payload.get('degree') or '').lower()
    if not degree and result is not None and dc is not None:
        margin=result-dc;degree='critical success' if margin>=10 else 'success' if margin>=0 else 'critical failure' if margin<=-10 else 'failure'
    facts={int(f['id']):f for f in knowledge_facts(settings,entity_id)}
    reveal_specs=[]
    structured=payload.get('reveal_facts') if isinstance(payload.get('reveal_facts'),list) else []
    for spec in structured:
        if not isinstance(spec,dict):continue
        try:fid=int(spec.get('fact_id'))
        except Exception:continue
        if fid not in facts:continue
        mode=str(spec.get('mode') or 'exact').lower()
        if mode not in DISCLOSURE_MODES:continue
        reveal_specs.append({'fact_id':fid,'mode':mode})
    for x in payload.get('reveal_fact_ids',[]):
        if str(x).isdigit() and int(x) in facts and not any(r['fact_id']==int(x) for r in reveal_specs):reveal_specs.append({'fact_id':int(x),'mode':'exact'})
    invite=payload.get('invite_id')
    if invite:
        for spec in reveal_specs:reveal_fact(settings,spec['fact_id'],int(invite),payload.get('session_id'),campaign_id=campaign_id,disclosure_mode=spec['mode'])
    now=time.time();fact_ids=[r['fact_id'] for r in reveal_specs]
    with connect(settings) as conn:
        cur=conn.execute('''INSERT INTO v7_recall_checks(campaign_id,entity_id,invite_id,character_id,skill,result,dc,degree,revealed_fact_ids_json,session_id,created_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(int(campaign_id),int(entity_id),invite,payload.get('character_id'),str(payload.get('skill') or '')[:80],result,dc,degree,json.dumps(reveal_specs),payload.get('session_id'),now));rid=int(cur.lastrowid or 0)
    out=_row(settings,'SELECT * FROM v7_recall_checks WHERE id=?',(rid,)) or {};raw=_json(out.pop('revealed_fact_ids_json','[]'),[]);out['revealed_facts']=raw;out['revealed_fact_ids']=[x.get('fact_id') if isinstance(x,dict) else x for x in raw];return out


def _observation_payload(row:dict)->dict:
    out=dict(row);out['data']=_json(out.pop('data_json','{}'),{})
    return out


def list_player_observations(settings: Settings,campaign_id:int,entity_id:int,viewer_invite_id:int|None=None,*,gm:bool=False)->list[dict]:
    sql='''SELECT o.*,p.label AS author_label FROM v7_player_observations o LEFT JOIN player_invites p ON p.id=o.invite_id
           WHERE o.campaign_id=? AND o.entity_id=?''';args=[int(campaign_id),int(entity_id)]
    if not gm:
        if viewer_invite_id is None:return []
        sql+=" AND (o.invite_id=? OR o.visibility='party')";args.append(int(viewer_invite_id))
    sql+=" ORDER BY CASE o.status WHEN 'confirmed' THEN 0 WHEN 'inferred' THEN 1 ELSE 2 END,o.updated_at DESC,o.id DESC"
    return [_observation_payload(r) for r in _rows(settings,sql,tuple(args))]


def save_player_observation(settings: Settings,campaign_id:int,entity_id:int,invite_id:int,payload:dict)->dict:
    if not _entity_in_campaign(settings,campaign_id,entity_id):raise ValueError('Entity does not belong to this campaign.')
    if not _invite_in_campaign(settings,campaign_id,invite_id):raise ValueError('Player does not belong to this campaign.')
    oid=int(payload.get('id') or 0);kind=str(payload.get('kind') or 'note').strip().lower()
    if kind not in OBSERVATION_KINDS:raise ValueError('Unknown observation type.')
    visibility=str(payload.get('visibility') or 'private').strip().lower()
    if visibility not in {'private','party'}:raise ValueError('Observation visibility must be private or party.')
    metric=str(payload.get('metric') or '').strip().lower()[:80]
    data=payload.get('data') if isinstance(payload.get('data'),dict) else {}
    def bound(name):
        val=payload.get(name)
        if val in (None,''):return None
        try:return float(val)
        except Exception:raise ValueError('Range bounds must be numbers.')
    lower=bound('lower_bound');upper=bound('upper_bound')
    if kind=='range' and metric=='ac':
        miss=payload.get('miss_total');hit=payload.get('hit_total')
        if miss not in (None,''):
            try:lower=max(lower if lower is not None else float('-inf'),float(miss)+1)
            except Exception:raise ValueError('Miss total must be a number.')
            data['miss_total']=float(miss)
        if hit not in (None,''):
            try:upper=min(upper if upper is not None else float('inf'),float(hit))
            except Exception:raise ValueError('Hit total must be a number.')
            data['hit_total']=float(hit)
    if lower is not None and upper is not None and lower>upper:raise ValueError('Those observations produce an impossible range. Check the hit/miss totals or enter the range manually.')
    title=str(payload.get('title') or '').strip()[:240]
    if not title:
        label={'ac':'AC','fortitude':'Fortitude','reflex':'Reflex','will':'Will','perception':'Perception','spell_dc':'Spell DC'}.get(metric,metric.replace('_',' ').title() or 'Observation')
        if kind=='range' and (lower is not None or upper is not None):
            lo='?' if lower is None else str(int(lower) if float(lower).is_integer() else lower);hi='?' if upper is None else str(int(upper) if float(upper).is_integer() else upper)
            title=f'{label} range: {lo}–{hi}'
        else:title=label
    body=str(payload.get('body') or '')[:10000]
    now=time.time();vals=(kind,metric,title,body,lower,upper,visibility,json.dumps(data,ensure_ascii=False),now)
    with connect(settings) as conn:
        if oid:
            cur=conn.execute('''UPDATE v7_player_observations SET kind=?,metric=?,title=?,body=?,lower_bound=?,upper_bound=?,visibility=?,data_json=?,updated_at=?
                                WHERE id=? AND campaign_id=? AND entity_id=? AND invite_id=?''',vals+(oid,int(campaign_id),int(entity_id),int(invite_id)))
            if not cur.rowcount:raise ValueError('Observation not found or does not belong to you.')
        else:
            cur=conn.execute('''INSERT INTO v7_player_observations(campaign_id,entity_id,invite_id,kind,metric,title,body,lower_bound,upper_bound,visibility,status,data_json,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(int(campaign_id),int(entity_id),int(invite_id),kind,metric,title,body,lower,upper,visibility,'inferred',json.dumps(data,ensure_ascii=False),now,now));oid=int(cur.lastrowid or 0)
    rows=list_player_observations(settings,campaign_id,entity_id,invite_id,gm=True)
    return next((r for r in rows if int(r['id'])==oid),{})


def set_player_observation_visibility(settings: Settings,campaign_id:int,observation_id:int,invite_id:int,visibility:str)->dict:
    visibility=str(visibility or '').lower()
    if visibility not in {'private','party'}:raise ValueError('Choose private or party visibility.')
    with connect(settings) as conn:
        cur=conn.execute('UPDATE v7_player_observations SET visibility=?,updated_at=? WHERE id=? AND campaign_id=? AND invite_id=?',(visibility,time.time(),int(observation_id),int(campaign_id),int(invite_id)))
        if not cur.rowcount:raise ValueError('Observation not found or does not belong to you.')
    row=_row(settings,'SELECT * FROM v7_player_observations WHERE id=?',(int(observation_id),)) or {};return _observation_payload(row)


def delete_player_observation(settings: Settings,campaign_id:int,observation_id:int,invite_id:int|None=None,*,gm:bool=False)->None:
    with connect(settings) as conn:
        if gm:cur=conn.execute('DELETE FROM v7_player_observations WHERE id=? AND campaign_id=?',(int(observation_id),int(campaign_id)))
        else:cur=conn.execute('DELETE FROM v7_player_observations WHERE id=? AND campaign_id=? AND invite_id=?',(int(observation_id),int(campaign_id),int(invite_id or 0)))
        if not cur.rowcount:raise ValueError('Observation not found or you cannot delete it.')


def review_player_observation(settings: Settings,campaign_id:int,observation_id:int,status:str)->dict:
    status=str(status or '').lower()
    if status not in {'inferred','confirmed','rejected'}:raise ValueError('Choose inferred, confirmed, or rejected.')
    with connect(settings) as conn:
        cur=conn.execute('UPDATE v7_player_observations SET status=?,updated_at=? WHERE id=? AND campaign_id=?',(status,time.time(),int(observation_id),int(campaign_id)))
        if not cur.rowcount:raise ValueError('Observation not found.')
    row=_row(settings,'SELECT * FROM v7_player_observations WHERE id=?',(int(observation_id),)) or {};return _observation_payload(row)


def normalize_encounter_rules_variant(value:Any)->str:
    raw=str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
    if raw in {'pwl','proficiency_without_level','proficiencywithoutlevel','no_level','without_level'}:
        return 'proficiency_without_level'
    return 'standard'


def encounter_xp_for_level(creature_level:int,party_level:int,rules_variant:str='standard')->int|None:
    """Return the creature XP cost for an encounter.

    Standard PF2e retains Seeker's existing behaviour.  Proficiency Without
    Level uses GM Core Table 4-18 exactly; the published table only defines
    party level -7 through +7, so values outside that range deliberately
    return None and the encounter builder asks the GM for an XP override.
    """
    delta=int(creature_level)-int(party_level)
    variant=normalize_encounter_rules_variant(rules_variant)
    if variant == 'proficiency_without_level':
        return PWL_XP_BY_DELTA.get(delta)
    if delta < -4:return 0
    if delta > 4:return 160 + (delta-4)*80
    return XP_BY_DELTA.get(delta,0)


def encounter_budget(party_size:int,difficulty:str)->int:
    base={'trivial':40,'low':60,'moderate':80,'severe':120,'extreme':160}.get(str(difficulty).lower(),80)
    return max(1,round(base*max(1,int(party_size))/4))


def encounter_summary(encounter:dict,creatures:list[dict])->dict:
    size=max(1,int(encounter.get('party_size') or 4));level=int(encounter.get('party_level') or 1)
    data=encounter.get('data') if isinstance(encounter.get('data'),dict) else _json(encounter.get('data_json','{}'),{})
    variant=normalize_encounter_rules_variant((data or {}).get('rules_variant'))
    xp=0;warnings=[];breakdown=[]
    for c in creatures:
        qty=max(1,int(c.get('quantity') or 1));override=c.get('xp_override')
        if override is not None and str(override).strip()!='':
            per=int(override);source='override'
        else:
            per=encounter_xp_for_level(int(c.get('level') or 0),level,variant);source=variant
        if per is None:
            warnings.append(f"{c.get('name') or 'Creature'} is outside the official PWL XP table (party level ±7). Set an XP override for this row.")
            breakdown.append({'row_id':int(c.get('id') or 0),'per_xp':None,'total_xp':None,'source':'manual_required'})
            continue
        total=int(per)*qty;xp+=total
        breakdown.append({'row_id':int(c.get('id') or 0),'per_xp':int(per),'total_xp':total,'source':source})
    scaled={name:round(budget*size/4) for name,budget in DIFFICULTY_BUDGETS}
    if warnings:difficulty='Needs XP override'
    elif xp < scaled['Trivial']:difficulty='Below trivial'
    elif xp < scaled['Low']:difficulty='Trivial'
    elif xp < scaled['Moderate']:difficulty='Low'
    elif xp < scaled['Severe']:difficulty='Moderate'
    elif xp < scaled['Extreme']:difficulty='Severe'
    else:difficulty='Extreme+'
    return {'xp':xp,'difficulty':difficulty,'budgets':scaled,'party_level':level,'party_size':size,'rules_variant':variant,'rules_label':'Proficiency without Level' if variant=='proficiency_without_level' else 'Standard PF2e','complete':not warnings,'warnings':warnings,'breakdown':breakdown}


def save_encounter(settings: Settings,campaign_id:int,payload:dict,*,actor_label:str='')->dict:
    eid=int(payload.get('id') or 0);now=time.time();title=str(payload.get('title') or '').strip()[:240]
    if not title:raise ValueError('Encounter title is required.')
    if payload.get('session_id') is not None and not _session_in_campaign(settings,campaign_id,payload.get('session_id')):raise ValueError('Session does not belong to this campaign.')
    vals=(payload.get('session_id'),title,str(payload.get('summary') or '')[:6000],int(payload.get('party_level') or 1),max(1,int(payload.get('party_size') or 4)),str(payload.get('status') or 'prepared')[:40],payload.get('map_id'),str(payload.get('scene_label') or '')[:240],str(payload.get('objective') or '')[:6000],str(payload.get('terrain') or '')[:6000],str(payload.get('tactics') or '')[:6000],str(payload.get('reinforcements') or '')[:6000],str(payload.get('treasure') or '')[:6000],str(payload.get('secrets') or '')[:6000],json.dumps(payload.get('data') if isinstance(payload.get('data'),dict) else {},ensure_ascii=False),now)
    with connect(settings) as conn:
        if eid:
            conn.execute('''UPDATE v7_encounters SET session_id=?,title=?,summary=?,party_level=?,party_size=?,status=?,map_id=?,scene_label=?,objective=?,terrain=?,tactics=?,reinforcements=?,treasure=?,secrets=?,data_json=?,updated_at=? WHERE id=? AND campaign_id=?''',vals+(eid,int(campaign_id)))
        else:
            cur=conn.execute('''INSERT INTO v7_encounters(campaign_id,session_id,title,summary,party_level,party_size,status,map_id,scene_label,objective,terrain,tactics,reinforcements,treasure,secrets,data_json,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(int(campaign_id),)+vals[:-1]+(now,now));eid=int(cur.lastrowid or 0)
    out=get_encounter(settings,campaign_id,eid) or {};audit(settings,campaign_id,actor_label,'encounter.save','encounter',str(eid),{},out);return out


def list_encounters(settings: Settings,campaign_id:int,session_id:int|None=None)->list[dict]:
    sql='SELECT * FROM v7_encounters WHERE campaign_id=?';args:[Any]=[int(campaign_id)]
    if session_id is not None:sql+=' AND session_id=?';args.append(int(session_id))
    sql+=' ORDER BY CASE status WHEN \'live\' THEN 0 WHEN \'prepared\' THEN 1 ELSE 2 END,updated_at DESC,id DESC'
    out=[]
    for r in _rows(settings,sql,tuple(args)):
        r['data']=_json(r.pop('data_json','{}'),{});cs=_rows(settings,'SELECT * FROM v7_encounter_creatures WHERE encounter_id=? ORDER BY id',(int(r['id']),));r['creatures']=cs;r['budget']=encounter_summary(r,cs);out.append(r)
    return out


def get_encounter(settings: Settings,campaign_id:int,encounter_id:int)->dict|None:
    return next((x for x in list_encounters(settings,campaign_id) if int(x['id'])==int(encounter_id)),None)


def save_encounter_creature(settings: Settings,campaign_id:int,encounter_id:int,payload:dict)->dict:
    enc=_row(settings,'SELECT id FROM v7_encounters WHERE id=? AND campaign_id=?',(int(encounter_id),int(campaign_id)))
    if not enc:raise ValueError('Encounter not found.')
    rid=int(payload.get('id') or 0);name=str(payload.get('name') or '').strip()[:240]
    if not name:raise ValueError('Creature name is required.')
    if payload.get('entity_id') is not None and not _entity_in_campaign(settings,campaign_id,payload.get('entity_id')):raise ValueError('Creature entity does not belong to this campaign.')
    if not _prepared_in_campaign(settings,campaign_id,payload.get('prepared_content_id')):raise ValueError('Prepared creature does not belong to this campaign.')
    raw_override=payload.get('xp_override');xp_override=None
    if raw_override is not None and str(raw_override).strip()!='':
        try:xp_override=int(raw_override)
        except Exception:raise ValueError('XP override must be a whole number.')
        if xp_override < 0:raise ValueError('XP override cannot be negative.')
    vals=(payload.get('entity_id'),payload.get('prepared_content_id'),name,int(payload.get('level') or 0),max(1,int(payload.get('quantity') or 1)),str(payload.get('disposition') or 'enemy')[:40],xp_override,str(payload.get('note') or '')[:3000])
    with connect(settings) as conn:
        if rid:
            cur=conn.execute('UPDATE v7_encounter_creatures SET entity_id=?,prepared_content_id=?,name=?,level=?,quantity=?,disposition=?,xp_override=?,note=? WHERE id=? AND encounter_id=?',vals+(rid,int(encounter_id)))
            if not cur.rowcount:raise ValueError('Encounter creature not found.')
        else:
            cur=conn.execute('INSERT INTO v7_encounter_creatures(encounter_id,entity_id,prepared_content_id,name,level,quantity,disposition,xp_override,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(int(encounter_id),)+vals+(time.time(),));rid=int(cur.lastrowid or 0)
    return _row(settings,'SELECT * FROM v7_encounter_creatures WHERE id=?',(rid,)) or {}


def delete_encounter_creature(settings: Settings,campaign_id:int,encounter_id:int,row_id:int)->None:
    with connect(settings) as conn:
        conn.execute('''DELETE FROM v7_encounter_creatures WHERE id=? AND encounter_id=? AND encounter_id IN (SELECT id FROM v7_encounters WHERE campaign_id=?)''',(int(row_id),int(encounter_id),int(campaign_id)))


def save_creature_folder(settings: Settings,campaign_id:int,payload:dict,*,actor_label:str='')->dict:
    rid=int(payload.get('id') or 0);name=str(payload.get('name') or '').strip()[:180]
    if not name:raise ValueError('Folder name is required.')
    now=time.time();note=str(payload.get('note') or '')[:3000];source=str(payload.get('source') or 'manual')[:40]
    with connect(settings) as conn:
        if rid:
            cur=conn.execute('UPDATE v7_creature_folders SET name=?,note=?,source=?,updated_at=? WHERE id=? AND campaign_id=?',(name,note,source,now,rid,int(campaign_id)))
            if not cur.rowcount:raise ValueError('Creature folder not found.')
        else:
            existing=conn.execute('SELECT id FROM v7_creature_folders WHERE campaign_id=? AND lower(name)=lower(?)',(int(campaign_id),name)).fetchone()
            if existing:rid=int(existing['id']);conn.execute('UPDATE v7_creature_folders SET note=?,updated_at=? WHERE id=?',(note,now,rid))
            else:
                cur=conn.execute('INSERT INTO v7_creature_folders(campaign_id,name,note,source,created_at,updated_at) VALUES(?,?,?,?,?,?)',(int(campaign_id),name,note,source,now,now));rid=int(cur.lastrowid or 0)
    out=get_creature_folder(settings,campaign_id,rid) or {};audit(settings,campaign_id,actor_label,'creature_folder.save','creature_folder',str(rid),{},out);return out


def get_creature_folder(settings: Settings,campaign_id:int,folder_id:int)->dict|None:
    r=_row(settings,'SELECT * FROM v7_creature_folders WHERE id=? AND campaign_id=?',(int(folder_id),int(campaign_id)))
    if not r:return None
    members=[]
    rows=_rows(settings,'SELECT entity_id,sort_order FROM v7_creature_folder_members WHERE folder_id=? ORDER BY sort_order,created_at,entity_id',(int(folder_id),))
    for m in rows:
        e=get_entity(settings,campaign_id,int(m['entity_id']))
        if e:members.append(e)
    r['members']=members;return r


def list_creature_folders(settings: Settings,campaign_id:int)->list[dict]:
    rows=_rows(settings,'SELECT id FROM v7_creature_folders WHERE campaign_id=? ORDER BY lower(name),id',(int(campaign_id),))
    return [x for x in (get_creature_folder(settings,campaign_id,int(r['id'])) for r in rows) if x]


def add_creature_to_folder(settings: Settings,campaign_id:int,folder_id:int,entity_id:int)->dict:
    folder=get_creature_folder(settings,campaign_id,folder_id)
    if not folder:raise ValueError('Creature folder not found.')
    entity=get_entity(settings,campaign_id,entity_id)
    if not entity:raise ValueError('Creature entity not found.')
    if str(entity.get('kind') or '').lower() not in {'monster','npc','creature'}:raise ValueError('Only creatures and NPCs can be added to creature folders.')
    with connect(settings) as conn:
        pos=conn.execute('SELECT COALESCE(MAX(sort_order),-1)+1 n FROM v7_creature_folder_members WHERE folder_id=?',(int(folder_id),)).fetchone()['n']
        conn.execute('INSERT OR IGNORE INTO v7_creature_folder_members(folder_id,entity_id,sort_order,created_at) VALUES(?,?,?,?)',(int(folder_id),int(entity_id),int(pos),time.time()))
    return get_creature_folder(settings,campaign_id,folder_id) or {}


def remove_creature_from_folder(settings: Settings,campaign_id:int,folder_id:int,entity_id:int)->None:
    if not get_creature_folder(settings,campaign_id,folder_id):raise ValueError('Creature folder not found.')
    with connect(settings) as conn:conn.execute('DELETE FROM v7_creature_folder_members WHERE folder_id=? AND entity_id=?',(int(folder_id),int(entity_id)))


def delete_creature_folder(settings: Settings,campaign_id:int,folder_id:int,*,actor_label:str='')->None:
    if not get_creature_folder(settings,campaign_id,folder_id):raise ValueError('Creature folder not found.')
    with connect(settings) as conn:conn.execute('DELETE FROM v7_creature_folders WHERE id=? AND campaign_id=?',(int(folder_id),int(campaign_id)))
    audit(settings,campaign_id,actor_label,'creature_folder.delete','creature_folder',str(folder_id),{}, {})


def save_loot_pool(settings: Settings,campaign_id:int,payload:dict)->dict:
    rid=int(payload.get('id') or 0);now=time.time();title=str(payload.get('title') or '').strip()[:240]
    if not title:raise ValueError('Loot pool title is required.')
    if payload.get('session_id') is not None and not _session_in_campaign(settings,campaign_id,payload.get('session_id')):raise ValueError('Session does not belong to this campaign.')
    vals=(payload.get('session_id'),title,str(payload.get('note') or '')[:5000],str(payload.get('status') or 'open')[:40],str(payload.get('visibility') or 'players')[:40],now)
    with connect(settings) as conn:
        if rid:conn.execute('UPDATE v7_loot_pools SET session_id=?,title=?,note=?,status=?,visibility=?,updated_at=? WHERE id=? AND campaign_id=?',vals+(rid,int(campaign_id)))
        else:
            cur=conn.execute('INSERT INTO v7_loot_pools(campaign_id,session_id,title,note,status,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(int(campaign_id),)+vals[:-1]+(now,now));rid=int(cur.lastrowid or 0)
    return get_loot_pool(settings,campaign_id,rid) or {}


def save_loot_item(settings: Settings,campaign_id:int,pool_id:int,payload:dict)->dict:
    if not _row(settings,'SELECT id FROM v7_loot_pools WHERE id=? AND campaign_id=?',(int(pool_id),int(campaign_id))):raise ValueError('Loot pool not found.')
    rid=int(payload.get('id') or 0);name=str(payload.get('name') or '').strip()[:240]
    if not name:raise ValueError('Loot item name is required.')
    if payload.get('entity_id') is not None and not _entity_in_campaign(settings,campaign_id,payload.get('entity_id')):raise ValueError('Loot entity does not belong to this campaign.')
    if not _prepared_in_campaign(settings,campaign_id,payload.get('prepared_content_id')):raise ValueError('Prepared item does not belong to this campaign.')
    now=time.time();vals=(payload.get('entity_id'),payload.get('prepared_content_id'),name,str(payload.get('description') or '')[:6000],max(1,int(payload.get('quantity') or 1)),str(payload.get('visibility') or 'players')[:40],json.dumps(payload.get('payload') if isinstance(payload.get('payload'),dict) else {},ensure_ascii=False),now)
    with connect(settings) as conn:
        if rid:
            cur=conn.execute('UPDATE v7_loot_items SET entity_id=?,prepared_content_id=?,name=?,description=?,quantity=?,visibility=?,payload_json=?,updated_at=? WHERE id=? AND pool_id=?',vals+(rid,int(pool_id)))
            if not cur.rowcount:raise ValueError('Loot item not found.')
        else:
            cur=conn.execute('INSERT INTO v7_loot_items(pool_id,entity_id,prepared_content_id,name,description,quantity,visibility,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(int(pool_id),)+vals[:-1]+(now,now));rid=int(cur.lastrowid or 0)
    out=_loot_item(settings,rid)
    if not out or int(out.get('pool_id') or 0)!=int(pool_id):raise ValueError('Loot item not found.')
    return out


def _loot_item(settings: Settings,item_id:int)->dict|None:
    r=_row(settings,'SELECT * FROM v7_loot_items WHERE id=?',(int(item_id),))
    if not r:return None
    r['payload']=_json(r.pop('payload_json','{}'),{});r['remaining']=max(0,int(r.get('quantity') or 0)-int(r.get('claimed_quantity') or 0));return r


def get_loot_item(settings: Settings,item_id:int)->dict|None:
    return _loot_item(settings,item_id)


def get_loot_pool(settings: Settings,campaign_id:int,pool_id:int)->dict|None:
    r=_row(settings,'SELECT * FROM v7_loot_pools WHERE id=? AND campaign_id=?',(int(pool_id),int(campaign_id)))
    if not r:return None
    r['items']=[_loot_item(settings,int(x['id'])) for x in _rows(settings,'SELECT id FROM v7_loot_items WHERE pool_id=? ORDER BY id',(int(pool_id),))]
    return r


def list_loot_pools(settings: Settings,campaign_id:int,session_id:int|None=None,*,public:bool=False)->list[dict]:
    sql='SELECT id FROM v7_loot_pools WHERE campaign_id=?';args:[Any]=[int(campaign_id)]
    if session_id is not None:sql+=' AND session_id=?';args.append(int(session_id))
    if public:sql+=" AND visibility!='gm'"
    sql+=' ORDER BY CASE status WHEN \'open\' THEN 0 ELSE 1 END,updated_at DESC,id DESC'
    return [get_loot_pool(settings,campaign_id,int(r['id'])) for r in _rows(settings,sql,tuple(args))]


def claim_loot(settings: Settings,campaign_id:int,item_id:int,invite_id:int|None,character_id:int|None,quantity:int=1,foundry_command_id:int|None=None)->dict:
    q=max(1,int(quantity));now=time.time()
    with connect(settings) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('''SELECT li.*,lp.campaign_id,lp.status FROM v7_loot_items li JOIN v7_loot_pools lp ON lp.id=li.pool_id WHERE li.id=? AND lp.campaign_id=?''',(int(item_id),int(campaign_id))).fetchone()
        if not row:raise ValueError('Loot item not found.')
        if row['status']!='open':raise ValueError('This loot pool is closed.')
        remaining=max(0,int(row['quantity'])-int(row['claimed_quantity']))
        if q>remaining:raise ValueError('Not enough of this item remains.')
        conn.execute('UPDATE v7_loot_items SET claimed_quantity=claimed_quantity+?,updated_at=? WHERE id=?',(q,now,int(item_id)))
        cur=conn.execute('''INSERT INTO v7_loot_claims(loot_item_id,invite_id,character_id,quantity,status,foundry_command_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)''',(int(item_id),invite_id,character_id,q,'claimed',foundry_command_id,now,now));rid=int(cur.lastrowid or 0)
    return _row(settings,'SELECT * FROM v7_loot_claims WHERE id=?',(rid,)) or {}


def create_session_change(settings: Settings,campaign_id:int,session_id:int,payload:dict,*,actor_label:str='')->dict:
    if not _session_in_campaign(settings,campaign_id,session_id):raise ValueError('Session does not belong to this campaign.')
    if payload.get('entity_id') is not None and not _entity_in_campaign(settings,campaign_id,payload.get('entity_id')):raise ValueError('Entity does not belong to this campaign.')
    summary=str(payload.get('summary') or '').strip()[:1000]
    if not summary:raise ValueError('Describe the campaign change.')
    now=time.time()
    with connect(settings) as conn:
        cur=conn.execute('''INSERT INTO v7_session_changes(campaign_id,session_id,kind,entity_id,target_type,target_key,summary,payload_json,status,visible_to_players,created_by,created_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(int(campaign_id),int(session_id),str(payload.get('kind') or 'event')[:80],payload.get('entity_id'),str(payload.get('target_type') or '')[:80],str(payload.get('target_key') or '')[:240],summary,json.dumps(payload.get('payload') if isinstance(payload.get('payload'),dict) else {},ensure_ascii=False),'proposed',1 if payload.get('visible_to_players') else 0,str(actor_label)[:160],now));rid=int(cur.lastrowid or 0)
    out=_row(settings,'SELECT * FROM v7_session_changes WHERE id=?',(rid,)) or {};out['payload']=_json(out.pop('payload_json','{}'),{});return out


def session_changes(settings: Settings,campaign_id:int,session_id:int,status:str='')->list[dict]:
    sql='SELECT * FROM v7_session_changes WHERE campaign_id=? AND session_id=?';args:[Any]=[int(campaign_id),int(session_id)]
    if status:sql+=' AND status=?';args.append(status)
    sql+=' ORDER BY created_at,id'
    rows=_rows(settings,sql,tuple(args))
    for r in rows:r['payload']=_json(r.pop('payload_json','{}'),{})
    return rows


def review_session_change(settings: Settings,campaign_id:int,change_id:int,status:str,*,actor_label:str='')->dict:
    status=str(status).lower()
    if status not in {'approved','rejected','applied'}:raise ValueError('Unsupported review state.')
    row=_row(settings,'SELECT * FROM v7_session_changes WHERE id=? AND campaign_id=?',(int(change_id),int(campaign_id)))
    if not row:raise ValueError('Session change not found.')
    now=time.time();applied=now if status=='applied' else None
    with connect(settings) as conn:conn.execute('UPDATE v7_session_changes SET status=?,applied_at=? WHERE id=?',(status,applied,int(change_id)))
    out=_row(settings,'SELECT * FROM v7_session_changes WHERE id=?',(int(change_id),)) or {};audit(settings,campaign_id,actor_label,'session_change.review','session_change',str(change_id),row,out);return out


def effective_permissions(settings: Settings,role:str,invite_id:int|None=None,campaign_id:int|None=None)->dict[str,bool]:
    role='owner' if role=='admin' else str(role or 'player').lower()
    rows=_rows(settings,'SELECT permission,allowed FROM v7_role_permissions WHERE role=?',(role,))
    perms={p:False for p in ALL_PERMISSIONS};perms.update({r['permission']:bool(r['allowed']) for r in rows})
    if invite_id is not None and campaign_id is not None:
        for r in _rows(settings,'SELECT permission,allowed FROM v7_invite_permissions WHERE campaign_id=? AND invite_id=?',(int(campaign_id),int(invite_id))):perms[r['permission']]=bool(r['allowed'])
    return perms


def save_role_permissions(settings: Settings,role:str,permissions:dict[str,bool])->dict[str,bool]:
    role=str(role or 'player').lower();now=time.time()
    if role not in DEFAULT_PERMISSIONS:raise ValueError('Unsupported role.')
    with connect(settings) as conn:
        for p in ALL_PERMISSIONS:
            if p in permissions:conn.execute('''INSERT INTO v7_role_permissions(role,permission,allowed,updated_at) VALUES(?,?,?,?) ON CONFLICT(role,permission) DO UPDATE SET allowed=excluded.allowed,updated_at=excluded.updated_at''',(role,p,1 if permissions[p] else 0,now))
    return effective_permissions(settings,role)


def save_invite_permissions(settings: Settings,campaign_id:int,invite_id:int,permissions:dict[str,bool|None])->dict[str,bool|None]:
    now=time.time()
    with connect(settings) as conn:
        for p,v in permissions.items():
            if p not in ALL_PERMISSIONS:continue
            if v is None:conn.execute('DELETE FROM v7_invite_permissions WHERE campaign_id=? AND invite_id=? AND permission=?',(int(campaign_id),int(invite_id),p))
            else:conn.execute('''INSERT INTO v7_invite_permissions(campaign_id,invite_id,permission,allowed,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(campaign_id,invite_id,permission) DO UPDATE SET allowed=excluded.allowed,updated_at=excluded.updated_at''',(int(campaign_id),int(invite_id),p,1 if v else 0,now))
    return {r['permission']:bool(r['allowed']) for r in _rows(settings,'SELECT permission,allowed FROM v7_invite_permissions WHERE campaign_id=? AND invite_id=?',(int(campaign_id),int(invite_id)))}


def invite_permission_overrides(settings: Settings,campaign_id:int,invite_id:int)->dict[str,bool]:
    """Return only explicit per-invite overrides, not inherited role values."""
    return {r['permission']:bool(r['allowed']) for r in _rows(settings,'SELECT permission,allowed FROM v7_invite_permissions WHERE campaign_id=? AND invite_id=?',(int(campaign_id),int(invite_id)))}


def save_dependency(settings: Settings,campaign_id:int,payload:dict)->dict:
    rid=int(payload.get('id') or 0);now=time.time();message=str(payload.get('message') or '').strip()[:2000]
    if not message:raise ValueError('Dependency warning message is required.')
    if payload.get('source_entity_id') is not None and not _entity_in_campaign(settings,campaign_id,payload.get('source_entity_id')):raise ValueError('Dependency entity does not belong to this campaign.')
    vals=(payload.get('source_entity_id'),str(payload.get('source_field') or 'status')[:120],str(payload.get('operator') or 'equals')[:40],str(payload.get('expected_value') or '')[:500],str(payload.get('target_type') or 'session')[:80],str(payload.get('target_key') or '')[:300],message,str(payload.get('severity') or 'warning')[:40],1 if payload.get('active',True) else 0,now)
    with connect(settings) as conn:
        if rid:
            cur=conn.execute('UPDATE v7_dependencies SET source_entity_id=?,source_field=?,operator=?,expected_value=?,target_type=?,target_key=?,message=?,severity=?,active=?,updated_at=? WHERE id=? AND campaign_id=?',vals+(rid,int(campaign_id)))
            if not cur.rowcount:raise ValueError('Dependency rule not found.')
        else:
            cur=conn.execute('INSERT INTO v7_dependencies(campaign_id,source_entity_id,source_field,operator,expected_value,target_type,target_key,message,severity,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(int(campaign_id),)+vals[:-1]+(now,now));rid=int(cur.lastrowid or 0)
    return _row(settings,'SELECT * FROM v7_dependencies WHERE id=? AND campaign_id=?',(rid,int(campaign_id))) or {}


def _field_value(entity:dict,field:str)->Any:
    if field in entity:return entity.get(field)
    cur=entity.get('data') or {}
    for part in str(field).split('.'):
        if not isinstance(cur,dict):return None
        cur=cur.get(part)
    return cur


def dependency_warnings(settings: Settings,campaign_id:int)->list[dict]:
    warnings=[]
    for rule in _rows(settings,'SELECT * FROM v7_dependencies WHERE campaign_id=? AND active=1 ORDER BY severity DESC,id',(int(campaign_id),)):
        entity=get_entity(settings,campaign_id,int(rule['source_entity_id'])) if rule.get('source_entity_id') else None
        value=_field_value(entity or {},str(rule.get('source_field') or 'status'));expected=rule.get('expected_value') or '';op=rule.get('operator') or 'equals'
        match=(str(value).casefold()==str(expected).casefold()) if op=='equals' else (str(value).casefold()!=str(expected).casefold()) if op=='not_equals' else (str(expected).casefold() in str(value).casefold()) if op=='contains' else bool(value)
        if match:warnings.append({**rule,'entity':entity,'actual_value':value})
    # Automatic high-value contradiction: dead/destroyed entities named in upcoming scene cards.
    upcoming=_rows(settings,"SELECT id,title FROM campaign_sessions WHERE campaign_id=? AND status IN ('planned','live') ORDER BY CASE status WHEN 'live' THEN 0 ELSE 1 END,session_date,id LIMIT 3",(int(campaign_id),))
    if upcoming:
        ids=[int(x['id']) for x in upcoming];marks=','.join('?' for _ in ids)
        scenes=_rows(settings,f'SELECT * FROM gm_scene_cards WHERE campaign_id=? AND session_id IN ({marks})',(int(campaign_id),*ids))
        hay='\n'.join(' '.join(str(s.get(k) or '') for k in ('title','purpose','complication','fallback','notes')) for s in scenes).casefold()
        for e in list_entities(settings,campaign_id):
            if str(e.get('status') or '').casefold() in {'dead','destroyed','gone','inactive'} and len(e.get('name') or '')>=4 and str(e['name']).casefold() in hay:
                warnings.append({'id':f'auto-{e["id"]}','severity':'warning','message':f'{e["name"]} is marked {e["status"]} but is referenced in upcoming session prep.','entity':e,'target_type':'session','target_key':str(upcoming[0]['id']),'automatic':True})
    return warnings


def save_token_recipe(settings: Settings,campaign_id:int,payload:dict)->dict:
    name=str(payload.get('name') or '').strip()[:160]
    if not name:raise ValueError('Token recipe name is required.')
    now=time.time();settings_json=json.dumps(payload.get('settings') if isinstance(payload.get('settings'),dict) else {},ensure_ascii=False)
    with connect(settings) as conn:
        conn.execute('''INSERT INTO v7_token_recipes(campaign_id,name,description,settings_json,created_at,updated_at) VALUES(?,?,?,?,?,?)
                        ON CONFLICT(campaign_id,name) DO UPDATE SET description=excluded.description,settings_json=excluded.settings_json,updated_at=excluded.updated_at''',(int(campaign_id),name,str(payload.get('description') or '')[:1000],settings_json,now,now))
    return next((x for x in list_token_recipes(settings,campaign_id) if x['name']==name),{})


def list_token_recipes(settings: Settings,campaign_id:int)->list[dict]:
    rows=_rows(settings,'SELECT * FROM v7_token_recipes WHERE campaign_id=? ORDER BY lower(name)',(int(campaign_id),))
    for r in rows:r['settings']=_json(r.pop('settings_json','{}'),{})
    return rows


def delete_token_recipe(settings: Settings,campaign_id:int,recipe_id:int)->None:
    with connect(settings) as conn:
        conn.execute('DELETE FROM v7_token_recipes WHERE campaign_id=? AND id=?',(int(campaign_id),int(recipe_id)))


def register_asset_ref(settings: Settings,campaign_id:int,asset_ref:str,entity_id:int|None=None,purpose:str='image',source_label:str='')->None:
    if not str(asset_ref or '').strip():return
    with connect(settings) as conn:
        conn.execute('INSERT OR IGNORE INTO v7_asset_refs(campaign_id,asset_ref,entity_id,purpose,source_label,created_at) VALUES(?,?,?,?,?,?)',(int(campaign_id),str(asset_ref)[:1200],entity_id,str(purpose)[:80],str(source_label)[:240],time.time()))


def asset_usage(settings: Settings,campaign_id:int)->list[dict]:
    # Include V7 references plus known legacy references. This never deletes anything.
    refs=_rows(settings,'''SELECT asset_ref,COUNT(*) AS ref_count,GROUP_CONCAT(DISTINCT purpose) AS purposes FROM v7_asset_refs WHERE campaign_id=? GROUP BY asset_ref ORDER BY ref_count DESC,asset_ref''',(int(campaign_id),))
    return refs


def asset_catalog(settings: Settings,campaign_id:int)->dict:
    usage={r['asset_ref']:{**r,'references':int(r.get('ref_count') or 0)} for r in asset_usage(settings,campaign_id)}
    # Pull legacy Foundry workshop references into the usage count without
    # rewriting those records. This is deliberately read-only.
    for row in _rows(settings,'SELECT title,payload_json FROM foundry_prepared_content WHERE campaign_id=?',(int(campaign_id),)):
        payload=_json(row.get('payload_json'),{})
        for purpose,key in [('portrait','img'),('token','token_img')]:
            ref=str(payload.get(key) or '')
            if not ref:continue
            item=usage.setdefault(ref,{'asset_ref':ref,'references':0,'purposes':''})
            item['references']=int(item.get('references') or 0)+1
            purposes={x for x in str(item.get('purposes') or '').split(',') if x};purposes.add(purpose);item['purposes']=','.join(sorted(purposes))
    files=[];total=0
    for path in settings.uploads_dir.rglob('*'):
        if not path.is_file():continue
        try:size=path.stat().st_size
        except OSError:continue
        total+=size
        rel=path.relative_to(settings.uploads_dir).as_posix();url='/uploads/'+rel
        ref=usage.get(url) or usage.get('upload:'+rel) or {'references':0,'purposes':''}
        files.append({'url':url,'name':path.name,'relative':rel,'size_bytes':size,'references':int(ref.get('references') or 0),'purposes':str(ref.get('purposes') or ''),'modified_at':path.stat().st_mtime})
    files.sort(key=lambda x:(-x['references'],-x['modified_at'],x['relative']))
    return {'total_bytes':total,'count':len(files),'files':files,'referenced':sum(1 for x in files if x['references']),'orphaned':sum(1 for x in files if not x['references'])}


def sync_link(settings: Settings,entity_id:int)->dict|None:
    r=_row(settings,'SELECT * FROM v7_foundry_sync_links WHERE entity_id=?',(int(entity_id),))
    if not r:return None
    r['base_snapshot']=_json(r.pop('base_snapshot_json','{}'),{});r['foundry_snapshot']=_json(r.pop('foundry_snapshot_json','{}'),{})
    raw=_row(settings,'SELECT * FROM v7_entities WHERE id=? AND campaign_id=?',(int(entity_id),int(r['campaign_id']))) if r.get('campaign_id') else None
    entity=entity_payload(raw) if raw else None
    if entity:
        r['diffs']=_sync_diffs(entity,r['foundry_snapshot'])
    else:r['diffs']=[]
    return r


def _seeker_sync_snapshot(entity:dict)->dict:
    return {'name':entity.get('name'),'summary':entity.get('summary'),'image_ref':entity.get('image_ref'),'token_ref':entity.get('token_ref'),'data':entity.get('data') or {}}


def _unwrap_value(value:Any)->Any:
    if isinstance(value,dict) and 'value' in value:return _unwrap_value(value.get('value'))
    return value


def _sync_projection_seeker(entity:dict)->dict:
    d=entity.get('data') or {}
    attacks=d.get('attacks') if isinstance(d.get('attacks'),list) else []
    abilities=d.get('abilities') if isinstance(d.get('abilities'),list) else []
    spells=d.get('spells') if isinstance(d.get('spells'),list) else []
    return {
        'name':entity.get('name') or '', 'image':entity.get('image_ref') or '', 'token':entity.get('token_ref') or '',
        'level':d.get('level'), 'ac':d.get('ac'), 'hp':d.get('hp'), 'speed':d.get('speed'), 'perception':d.get('perception'),
        'fortitude':d.get('fortitude'), 'reflex':d.get('reflex'), 'will':d.get('will'),
        'attacks':[(a.get('name'),a.get('bonus'),a.get('damage')) for a in attacks if isinstance(a,dict)],
        'abilities':[(a.get('name'),a.get('actions'),a.get('dc')) for a in abilities if isinstance(a,dict)],
        'spells':[(s.get('name'),s.get('rank')) for s in spells if isinstance(s,dict)],
    }


def _sync_projection_foundry(snapshot:dict)->dict:
    sys=snapshot.get('system') if isinstance(snapshot.get('system'),dict) else {}
    details=sys.get('details') if isinstance(sys.get('details'),dict) else {}
    attrs=sys.get('attributes') if isinstance(sys.get('attributes'),dict) else {}
    saves=sys.get('saves') if isinstance(sys.get('saves'),dict) else {}
    items=snapshot.get('items') if isinstance(snapshot.get('items'),list) else []
    attacks=[];abilities=[];spells=[]
    for item in items:
        if not isinstance(item,dict):continue
        role=str(item.get('role') or '');isys=item.get('system') if isinstance(item.get('system'),dict) else {}
        if role=='strike':
            damage=isys.get('damageRolls') if isinstance(isys.get('damageRolls'),dict) else {}
            first=next(iter(damage.values()),{}) if damage else {}
            attacks.append((item.get('name'),_unwrap_value(isys.get('bonus')),first.get('damage') if isinstance(first,dict) else None))
        elif role=='ability':abilities.append((item.get('name'),_unwrap_value(isys.get('actions')),_unwrap_value((isys.get('frequency') or {}).get('value') if isinstance(isys.get('frequency'),dict) else None)))
        elif role=='spell':spells.append((item.get('name'),_unwrap_value((isys.get('location') or {}).get('heightenedLevel') if isinstance(isys.get('location'),dict) else None)))
    hp=attrs.get('hp') if isinstance(attrs.get('hp'),dict) else {}
    speed=attrs.get('speed') if isinstance(attrs.get('speed'),dict) else {}
    ac=attrs.get('ac') if isinstance(attrs.get('ac'),dict) else attrs.get('ac')
    perception=sys.get('perception') if isinstance(sys.get('perception'),dict) else attrs.get('perception')
    return {
        'name':snapshot.get('name') or '', 'image':snapshot.get('img') or '',
        'token':((snapshot.get('prototypeToken') or {}).get('texture') or {}).get('src') if isinstance(snapshot.get('prototypeToken'),dict) else '',
        'level':_unwrap_value(details.get('level')), 'ac':_unwrap_value(ac), 'hp':_unwrap_value(hp.get('max') if isinstance(hp,dict) else hp),
        'speed':_unwrap_value(speed.get('value') if isinstance(speed,dict) else speed), 'perception':_unwrap_value(perception),
        'fortitude':_unwrap_value(saves.get('fortitude')), 'reflex':_unwrap_value(saves.get('reflex')), 'will':_unwrap_value(saves.get('will')),
        'attacks':attacks,'abilities':abilities,'spells':spells,
    }


def _sync_diffs(entity:dict,foundry_snapshot:dict)->list[dict]:
    if not foundry_snapshot:return []
    seeker=_sync_projection_seeker(entity);foundry=_sync_projection_foundry(foundry_snapshot);out=[]
    for key in ('name','level','ac','hp','speed','perception','fortitude','reflex','will','attacks','abilities','spells'):
        a=seeker.get(key);b=foundry.get(key)
        if a in ('',None,[]) and b in ('',None,[]):continue
        if json.dumps(a,sort_keys=True,default=str)!=json.dumps(b,sort_keys=True,default=str):out.append({'field':key,'seeker':a,'foundry':b})
    return out


def set_sync_link(settings: Settings,campaign_id:int,entity_id:int,foundry_uuid:str,document_type:str='',base_snapshot:dict|None=None)->dict:
    entity=get_entity(settings,campaign_id,entity_id)
    if not entity:raise ValueError('Entity not found.')
    snap=base_snapshot or _seeker_sync_snapshot(entity)
    now=time.time();h=_hash(snap)
    with connect(settings) as conn:
        conn.execute('''INSERT INTO v7_foundry_sync_links(entity_id,campaign_id,foundry_uuid,document_type,seeker_hash,foundry_hash,base_snapshot_json,foundry_snapshot_json,status,last_seen_at,last_synced_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET foundry_uuid=excluded.foundry_uuid,document_type=excluded.document_type,seeker_hash=excluded.seeker_hash,status='awaiting_snapshot',last_seen_at=excluded.last_seen_at,last_synced_at=excluded.last_synced_at''',
                     (int(entity_id),int(campaign_id),str(foundry_uuid)[:500],str(document_type)[:80],h,'',json.dumps({'seeker':snap,'foundry':{}},ensure_ascii=False),'{}','awaiting_snapshot',now,now))
    return sync_link(settings,entity_id) or {}


def ingest_foundry_command_results(settings: Settings,campaign_id:int,results:list[dict])->int:
    """Capture UUIDs returned by the bridge after Seeker-created documents land in Foundry."""
    count=0
    for item in results or []:
        result=item.get('result') if isinstance(item,dict) and isinstance(item.get('result'),dict) else {}
        result_rows=[result]
        if isinstance(result.get('items'),list):result_rows.extend(x for x in result['items'] if isinstance(x,dict))
        for resolved in result_rows:
            eid=resolved.get('entity_id');uuid=str(resolved.get('uuid') or '').strip()
            if not eid or not uuid:continue
            try:eid=int(eid)
            except Exception:continue
            try:
                set_sync_link(settings,campaign_id,eid,uuid,str(resolved.get('document_type') or ''))
                count+=1
            except ValueError:
                continue
    return count


def ingest_foundry_managed_state(settings: Settings,campaign_id:int,payload:dict)->int:
    docs=payload.get('managed_documents') if isinstance(payload.get('managed_documents'),list) else []
    count=0;now=time.time()
    for doc in docs[:500]:
        if not isinstance(doc,dict):continue
        flags=doc.get('seeker') if isinstance(doc.get('seeker'),dict) else {}
        eid=flags.get('entity_id')
        if not eid:continue
        try:eid=int(eid)
        except Exception:continue
        if not _row(settings,'SELECT id FROM v7_entities WHERE id=? AND campaign_id=?',(eid,int(campaign_id))):continue
        snapshot=doc.get('snapshot') if isinstance(doc.get('snapshot'),dict) else doc
        foundry_hash=_hash(snapshot);entity=get_entity(settings,campaign_id,eid) or {};seeker_snap=_seeker_sync_snapshot(entity);seeker_hash=_hash(seeker_snap)
        old=sync_link(settings,eid);base=(old or {}).get('base_snapshot') or {}
        modern=isinstance(base,dict) and isinstance(base.get('seeker'),dict) and isinstance(base.get('foundry'),dict)
        if not old or str((old or {}).get('status') or '')=='awaiting_snapshot' or not modern:
            status='synced';base={'seeker':seeker_snap,'foundry':snapshot};last_synced=now
        else:
            seeker_changed=seeker_hash!=_hash(base.get('seeker') or {})
            foundry_changed=foundry_hash!=_hash(base.get('foundry') or {})
            status='conflict' if seeker_changed and foundry_changed else 'seeker_changed' if seeker_changed else 'foundry_changed' if foundry_changed else 'synced'
            last_synced=(old or {}).get('last_synced_at')
        with connect(settings) as conn:
            conn.execute('''INSERT INTO v7_foundry_sync_links(entity_id,campaign_id,foundry_uuid,document_type,seeker_hash,foundry_hash,base_snapshot_json,foundry_snapshot_json,status,last_seen_at,last_synced_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET foundry_uuid=excluded.foundry_uuid,document_type=excluded.document_type,seeker_hash=excluded.seeker_hash,foundry_hash=excluded.foundry_hash,base_snapshot_json=excluded.base_snapshot_json,foundry_snapshot_json=excluded.foundry_snapshot_json,status=excluded.status,last_seen_at=excluded.last_seen_at,last_synced_at=excluded.last_synced_at''',
                         (eid,int(campaign_id),str(doc.get('uuid') or '')[:500],str(doc.get('document_type') or '')[:80],seeker_hash,foundry_hash,json.dumps(base,ensure_ascii=False),json.dumps(snapshot,ensure_ascii=False),status,now,last_synced))
        count+=1
    return count


def mark_sync_resolved(settings: Settings,campaign_id:int,entity_id:int,mode:str)->dict:
    entity=get_entity(settings,campaign_id,entity_id);link=sync_link(settings,entity_id)
    if not entity or not link:raise ValueError('Entity is not linked to Foundry.')
    if mode=='accept_foundry':
        f=link.get('foundry_snapshot') or {};data=entity.get('data') or {}
        # Pull only fields that Seeker owns safely. Unknown Foundry system internals remain in snapshot.
        updated={**entity,'name':f.get('name') or entity.get('name'),'summary':f.get('summary') or f.get('description') or entity.get('summary'),'data':{**data,'last_foundry_pull':f}}
        save_entity(settings,campaign_id,updated,actor_label='Foundry pull');entity=get_entity(settings,campaign_id,entity_id) or entity
    seeker_snap=_seeker_sync_snapshot(entity);foundry_snap=link.get('foundry_snapshot') or {};now=time.time();base={'seeker':seeker_snap,'foundry':foundry_snap}
    with connect(settings) as conn:
        conn.execute('UPDATE v7_foundry_sync_links SET seeker_hash=?,foundry_hash=?,base_snapshot_json=?,status=?,last_synced_at=? WHERE entity_id=?',(_hash(seeker_snap),_hash(foundry_snap),json.dumps(base,ensure_ascii=False),'synced',now,int(entity_id)))
    return sync_link(settings,entity_id) or {}


_TOKEN_RE=re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]{1,40}")
_STOP={'the','and','for','that','with','this','from','are','was','were','have','has','had','not','but','into','their','they','them','than','who','what','when','where','which','while','about','also','only','after','before','between','through','can','could','would','should','there','here','his','her','our','your','you','she','he','its','of','to','in','on','at','by','as','is','be','or','if','a','an'}


def _tokens(text:str)->list[str]:
    return [x.casefold() for x in _TOKEN_RE.findall(str(text or '')) if x.casefold() not in _STOP]


def memory_search(settings: Settings,campaign_id:int,wiki:dict,query:str,limit:int=20,*,gm:bool=False,invite_id:int|None=None,can_view_statblocks:bool=False)->list[dict]:
    q=_tokens(query)
    if not q:return []
    docs=[]
    for p in wiki.get('pages',[]) or []:
        docs.append({'kind':'lore','key':p.get('slug'),'title':p.get('title') or p.get('slug'),'body':p.get('plain_text') or p.get('excerpt') or '','href':f"/lore/{p.get('slug')}"})
    for e in list_entities(settings,campaign_id,include_hidden=gm):
        view=e if gm else player_entity_view(settings,e,invite_id,can_view_statblock=can_view_statblocks)
        docs.append({'kind':view.get('kind'),'key':view.get('id'),'title':view.get('name'),'body':' '.join([view.get('summary') or '',view.get('body') or '',json.dumps(view.get('data') or {}), ' '.join((f.get('title','')+' '+f.get('body','')) for f in (view.get('facts') or []))]),'href':f"/entity/{view.get('id')}"})
    if gm:
        session_rows=_rows(settings,'SELECT id,title,summary,gm_notes FROM campaign_sessions WHERE campaign_id=?',(int(campaign_id),))
    else:
        session_rows=_rows(settings,'SELECT id,title,summary FROM campaign_sessions WHERE campaign_id=?',(int(campaign_id),))
    for s in session_rows:
        docs.append({'kind':'session','key':s['id'],'title':s.get('title') or 'Session','body':(s.get('summary') or '')+(' '+(s.get('gm_notes') or '') if gm else ''),'href':f"/session?session_id={s['id']}"})
    if gm:
        for ev in _rows(settings,'SELECT session_id,event_type,body,target_type,target_key FROM gm_session_events WHERE campaign_id=?',(int(campaign_id),)):
            docs.append({'kind':'session event','key':ev['session_id'],'title':ev.get('event_type') or 'Event','body':ev.get('body') or '','href':f"/gm/session?session_id={ev['session_id']}"})
    results=[]
    for d in docs:
        title=str(d.get('title') or '');body=str(d.get('body') or '');ts=_tokens(title);bs=_tokens(body[:70000]);score=0.0
        for term in q:
            score += ts.count(term)*6 + min(bs.count(term),8)*1.2
            if term in title.casefold():score+=3
        if score:
            # Context around first query hit.
            low=body.casefold();positions=[low.find(term) for term in q if low.find(term)>=0];pos=min(positions) if positions else 0;start=max(0,pos-120);excerpt=body[start:start+360].strip()
            results.append({**d,'score':round(score,2),'excerpt':excerpt})
    results.sort(key=lambda x:(-x['score'],str(x.get('title')).casefold()))
    return results[:max(1,min(int(limit),50))]


def v7_dashboard(settings: Settings,campaign_id:int,wiki:dict,session:dict|None=None)->dict:
    sid=int(session['id']) if session else None
    entities=list_entities(settings,campaign_id)
    encounters=list_encounters(settings,campaign_id,sid) if sid else list_encounters(settings,campaign_id)[:8]
    loot=list_loot_pools(settings,campaign_id,sid) if sid else list_loot_pools(settings,campaign_id)[:6]
    changes=session_changes(settings,campaign_id,sid) if sid else []
    warnings=dependency_warnings(settings,campaign_id)
    syncs=_rows(settings,"SELECT status,COUNT(*) AS n FROM v7_foundry_sync_links WHERE campaign_id=? GROUP BY status",(int(campaign_id),))
    return {'entities':entities,'entity_counts':_count_by(entities,'kind'),'encounters':encounters,'loot':loot,'changes':changes,'warnings':warnings,'sync_counts':{r['status']:r['n'] for r in syncs},'audit':recent_audit(settings,campaign_id,15),'session':session}


def _count_by(rows:Iterable[dict],key:str)->dict[str,int]:
    out={}
    for r in rows:
        k=str(r.get(key) or 'other');out[k]=out.get(k,0)+1
    return out


@dataclass(frozen=True)
class SeekerIntegration:
    id:str
    title:str
    description:str
    capabilities:tuple[str,...]
    health_path:str=''


BUILTIN_INTEGRATIONS=(
    SeekerIntegration('foundry','Foundry VTT','Bidirectional table mechanics bridge with safe queued writes.',('context.read','actors.read','documents.sync','commands.write'),'foundry'),
    SeekerIntegration('discord','Discord','Campaign announcements and session coordination.',('messages.write','mentions.write'),'discord'),
    SeekerIntegration('calendar','Calendar','Private subscription feed for planned sessions.',('calendar.read',),'calendar'),
    SeekerIntegration('display','Table Display','Player-safe second-screen media surface.',('display.write',),'display'),
)


def integration_registry()->list[dict]:
    return [asdict(x) for x in BUILTIN_INTEGRATIONS]
