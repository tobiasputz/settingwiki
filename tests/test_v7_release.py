from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.storage import init_db, create_player_invite, connect, set_setting
from app.features import init_feature_db, save_player_character, save_session
from app.scheduling import init_schedule_db
from app.v5 import init_v5_db
from app.v51 import init_v51_db
from app.v6 import init_v6_db, save_foundry_prepared_content, foundry_link, integration_config
from app.v7 import (
    init_v7_db, sync_existing_entities, list_entities, get_entity, save_entity, entity_versions,
    restore_entity_version, save_relation, save_relationship_state, relationship_timeline,
    save_knowledge_fact, reveal_fact, visible_entity_facts, record_recall,
    save_encounter, save_encounter_creature, get_encounter, save_loot_pool, save_loot_item,
    get_loot_pool, claim_loot, create_session_change, review_session_change, session_changes,
    effective_permissions, save_invite_permissions, save_dependency, dependency_warnings,
    save_token_recipe, list_token_recipes, memory_search, set_sync_link, sync_link,
    ingest_foundry_managed_state, recent_audit, asset_catalog,
)
from app.campaigns import default_campaign_id, save_campaign, set_campaign_members
from app.latex import build_wiki


def settings_for(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=settings_for(tmp_path)
    init_db(s);init_feature_db(s);init_schedule_db(s);init_v5_db(s);init_v51_db(s);init_v6_db(s);init_v7_db(s)
    return s


def seed_wiki(s: Settings):
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}\begin{document}\chapter{Places}\section{Black Gate}An obsidian gate below the city.\chapter{People}\section{Corvina}A courier with a silver key.\end{document}''',encoding='utf-8')
    return build_wiki(s)


def test_v7_release_identity_assets_and_bridge():
    root=Path(__file__).resolve().parents[1]
    assert (root/'VERSION').read_text().strip()=='7.0.0'
    assert 'seeker-static-v7000' in (root/'static/sw.js').read_text(encoding='utf-8')
    assert (root/'app/v7.py').exists() and (root/'app/v7_api.py').exists()
    assert (root/'templates/v7_hub.html').exists() and (root/'templates/v7_player.html').exists()
    assert (root/'static/v7.css').exists() and (root/'static/v7.js').exists()
    bridge=(root/'integrations/foundry-seeker-bridge/seeker-bridge.mjs').read_text(encoding='utf-8')
    assert 'const BRIDGE_VERSION = "1.5.0"' in bridge
    assert 'managed_documents' in bridge and 'sync_entity_document' in bridge
    assert 'flags: { seeker: { managed: true' in bridge


def test_v7_schema_backup_and_permission_scope(tmp_path: Path):
    s=settings_for(tmp_path);init_db(s);init_feature_db(s);init_schedule_db(s);init_v5_db(s);init_v51_db(s);init_v6_db(s)
    assert s.db_path.exists();init_v7_db(s)
    backups=list((s.data_dir/'migration-backups').glob('pre-v7-*.sqlite'))
    assert backups
    with connect(s) as conn:
        tables={r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'v7_entities','v7_foundry_sync_links','v7_encounters','v7_loot_pools','v7_knowledge_facts','v7_session_changes','v7_dependencies','v7_token_recipes','v7_audit_log'} <= tables
    a=default_campaign_id(s);b=save_campaign(s,{'name':'Other Table'})['id'];inv=create_player_invite(s,'Alice');set_campaign_members(s,a,[inv['id']]);set_campaign_members(s,b,[inv['id']])
    save_invite_permissions(s,a,inv['id'],{'view_statblocks':True})
    assert effective_permissions(s,'player',inv['id'],a)['view_statblocks'] is True
    assert effective_permissions(s,'player',inv['id'],b)['view_statblocks'] is False


def test_v7_migration_mirroring_is_idempotent(tmp_path: Path):
    s=setup(tmp_path);wiki=seed_wiki(s);cid=default_campaign_id(s)
    inv=create_player_invite(s,'Alice');set_campaign_members(s,cid,[inv['id']]);save_player_character(s,{'campaign_id':cid,'name':'Aster','ancestry':'Human','class_name':'Rogue'},invite_id=inv['id'])
    save_foundry_prepared_content(s,cid,{'kind':'monster','target_type':'world','title':'Ash Warden','summary':'A cinder-clad guardian.','payload':{'level':5,'hp':80,'ac':22,'publish_codex':True,'codex_visibility':'field_notes','codex_blurb':'A charred guardian.'}})
    sync_existing_entities(s,cid,wiki)
    with connect(s) as conn:
        first=(conn.execute('SELECT COUNT(*) n FROM v7_entities WHERE campaign_id=?',(cid,)).fetchone()['n'],conn.execute('SELECT COUNT(*) n FROM v7_entity_versions').fetchone()['n'])
    sync_existing_entities(s,cid,wiki)
    with connect(s) as conn:
        second=(conn.execute('SELECT COUNT(*) n FROM v7_entities WHERE campaign_id=?',(cid,)).fetchone()['n'],conn.execute('SELECT COUNT(*) n FROM v7_entity_versions').fetchone()['n'])
    assert first==second and first[0]>=3


def test_v7_entity_history_relations_and_cross_campaign_guards(tmp_path: Path):
    s=setup(tmp_path);a=default_campaign_id(s);b=save_campaign(s,{'name':'B'})['id']
    one=save_entity(s,a,{'kind':'npc','name':'Vel','summary':'Friendly'},actor_label='GM')
    two=save_entity(s,a,{'kind':'faction','name':'Moon Guard'},actor_label='GM')
    foreign=save_entity(s,b,{'kind':'npc','name':'Elsewhere'},actor_label='GM')
    one=save_entity(s,a,{**one,'summary':'Hostile'},actor_label='GM')
    versions=entity_versions(s,one['id']);assert len(versions)>=2
    restored=restore_entity_version(s,a,one['id'],versions[-1]['id'],actor_label='GM');assert restored['summary']=='Friendly'
    rel=save_relation(s,a,{'source_entity_id':one['id'],'target_entity_id':two['id'],'relation':'serves','label':'Captain'},actor_label='GM');assert rel['relation']=='serves'
    save_relationship_state(s,a,{'source_entity_id':one['id'],'target_entity_id':two['id'],'state':'loyal','note':'Before betrayal'})
    save_relationship_state(s,a,{'source_entity_id':one['id'],'target_entity_id':two['id'],'state':'hostile','note':'After betrayal'})
    assert [r['state'] for r in relationship_timeline(s,a,one['id'],two['id'])][-2:]==['loyal','hostile']
    with pytest.raises(ValueError):save_relation(s,a,{'source_entity_id':one['id'],'target_entity_id':foreign['id']})


def test_v7_knowledge_recall_is_player_specific(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s);alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob');set_campaign_members(s,cid,[alice['id'],bob['id']])
    monster=save_entity(s,cid,{'kind':'monster','name':'Void Maw','visibility':'players','summary':'A subterranean predator','data':{'hp':140,'ac':28,'codex_blurb':'A huge subterranean predator.','publish_codex':True,'codex_visibility':'field_notes'}})
    f1=save_knowledge_fact(s,monster['id'],{'title':'Armored hide','body':'It resists ordinary blades.','tier':'known'},campaign_id=cid)
    f2=save_knowledge_fact(s,monster['id'],{'title':'Sonic weakness','body':'It recoils from sonic damage.','tier':'known'},campaign_id=cid)
    reveal_fact(s,f1['id'],alice['id'],campaign_id=cid)
    assert {f['id'] for f in visible_entity_facts(s,monster['id'],alice['id'])}=={f1['id']}
    assert not visible_entity_facts(s,monster['id'],bob['id'])
    out=record_recall(s,cid,monster['id'],{'invite_id':bob['id'],'skill':'Nature','result':30,'dc':25,'degree':'success','reveal_fact_ids':[f2['id']]})
    assert out['degree']=='success' and {f['id'] for f in visible_entity_facts(s,monster['id'],bob['id'])}=={f2['id']}


def test_v7_encounter_budget_and_loot_claims(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s);inv=create_player_invite(s,'Alice');set_campaign_members(s,cid,[inv['id']])
    monster=save_entity(s,cid,{'kind':'monster','name':'Mirror Knight','data':{'level':5}})
    enc=save_encounter(s,cid,{'title':'Hall of Mirrors','party_level':5,'party_size':4})
    save_encounter_creature(s,cid,enc['id'],{'entity_id':monster['id'],'name':'Mirror Knight','level':5,'quantity':2})
    calc=get_encounter(s,cid,enc['id']);assert calc['budget']['xp']==80 and calc['budget']['difficulty']=='Moderate'
    pool=save_loot_pool(s,cid,{'title':'Vault','visibility':'players'});item=save_loot_item(s,cid,pool['id'],{'name':'Silver Key','quantity':2})
    claim_loot(s,cid,item['id'],inv['id'],None,1);claim_loot(s,cid,item['id'],inv['id'],None,1)
    with pytest.raises(ValueError):claim_loot(s,cid,item['id'],inv['id'],None,1)
    assert get_loot_pool(s,cid,pool['id'])['items'][0]['remaining']==0


def test_v7_session_change_dependency_and_audit(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s);session=save_session(s,{'campaign_id':cid,'title':'The Crossing','status':'planned'})
    bridge=save_entity(s,cid,{'kind':'place','name':'Moon Bridge','status':'destroyed'})
    change=create_session_change(s,cid,session['id'],{'kind':'entity_status','entity_id':bridge['id'],'summary':'Bridge repaired','payload':{'status':'active'}},actor_label='GM')
    assert change['status']=='proposed';assert review_session_change(s,cid,change['id'],'approved',actor_label='GM')['status']=='approved'
    assert session_changes(s,cid,session['id'],'approved')
    save_dependency(s,cid,{'source_entity_id':bridge['id'],'source_field':'status','operator':'equals','expected_value':'destroyed','target_type':'session','target_key':str(session['id']),'message':'Moon Bridge is destroyed but the route crosses it.'})
    assert any('destroyed' in w['message'] for w in dependency_warnings(s,cid))
    assert recent_audit(s,cid)


def test_v7_campaign_memory_hides_gm_material(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s);inv=create_player_invite(s,'Alice');set_campaign_members(s,cid,[inv['id']])
    public=save_entity(s,cid,{'kind':'monster','name':'Ash Warden','summary':'Known guardian','visibility':'players','body':'SECRET STATBLOCK TEXT','data':{'hp':99,'gm_notes':'SECRET GM ENTITY','codex_blurb':'A charred guardian.','publish_codex':True,'codex_visibility':'field_notes'}})
    save_knowledge_fact(s,public['id'],{'title':'Hidden weakness','body':'SONIC SECRET','tier':'known'},campaign_id=cid)
    save_entity(s,cid,{'kind':'npc','name':'Secret Agent','summary':'BLACKSUN SECRET','visibility':'gm'})
    save_session(s,{'campaign_id':cid,'title':'Night','summary':'Public summary','gm_notes':'NIGHTFALL SECRET','status':'ended'})
    assert memory_search(s,cid,{'pages':[]},'nightfall',gm=True)
    assert not memory_search(s,cid,{'pages':[]},'nightfall',gm=False,invite_id=inv['id'])
    assert not memory_search(s,cid,{'pages':[]},'blacksun',gm=False,invite_id=inv['id'])
    # Exact combat body and unrevealed fact must not be searchable to the player.
    assert not memory_search(s,cid,{'pages':[]},'statblock',gm=False,invite_id=inv['id'])
    assert not memory_search(s,cid,{'pages':[]},'sonic',gm=False,invite_id=inv['id'])


def _foundry_snapshot(name='Ash Warden',hp=80,ac=22):
    return {'name':name,'type':'npc','img':'','prototypeToken':{'texture':{'src':''}},'system':{'details':{'level':{'value':5}},'attributes':{'ac':{'value':ac},'hp':{'max':hp},'speed':{'value':25}},'perception':{'mod':12},'saves':{'fortitude':{'value':13},'reflex':{'value':10},'will':{'value':11}}},'items':[]}


def test_v7_managed_foundry_sync_states(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    e=save_entity(s,cid,{'kind':'monster','name':'Ash Warden','summary':'Guardian','data':{'level':5,'hp':80,'ac':22,'speed':25,'perception':12,'fortitude':13,'reflex':10,'will':11}})
    link=set_sync_link(s,cid,e['id'],'Actor.abc','Actor');assert link['status']=='awaiting_snapshot'
    payload={'managed_documents':[{'uuid':'Actor.abc','document_type':'Actor','seeker':{'entity_id':e['id']},'snapshot':_foundry_snapshot()}]}
    assert ingest_foundry_managed_state(s,cid,payload)==1 and sync_link(s,e['id'])['status']=='synced'
    save_entity(s,cid,{**get_entity(s,cid,e['id']),'summary':'Changed in Seeker'})
    ingest_foundry_managed_state(s,cid,payload);assert sync_link(s,e['id'])['status']=='seeker_changed'
    payload2={'managed_documents':[{'uuid':'Actor.abc','document_type':'Actor','seeker':{'entity_id':e['id']},'snapshot':_foundry_snapshot(hp=90)}]}
    ingest_foundry_managed_state(s,cid,payload2);assert sync_link(s,e['id'])['status']=='conflict'


def test_v7_token_recipes_and_asset_accounting(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    recipe=save_token_recipe(s,cid,{'name':'Boss Crimson','description':'Boss frame','settings':{'shape':'circle','ring':'#812f2f','pattern':'runes'}})
    assert list_token_recipes(s,cid)[0]['settings']['pattern']=='runes'
    (s.uploads_dir/'token.webp').write_bytes(b'1234567890')
    cat=asset_catalog(s,cid);assert cat['count']==1 and cat['total_bytes']==10 and cat['orphaned']==1


def test_v7_http_gm_and_player_privacy(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);wiki=seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s);alice=create_player_invite(s,'Alice');set_campaign_members(s,cid,[alice['id']])
    char=save_player_character(s,{'campaign_id':cid,'name':'Aster','visibility':'party'},invite_id=alice['id'])
    monster=save_entity(s,cid,{'kind':'monster','name':'Void Maw','visibility':'players','summary':'A terrible predator','body':'FULL SECRET RULES','data':{'hp':150,'ac':29,'gm_notes':'DO NOT LEAK','codex_blurb':'A huge predator from below.','publish_codex':True,'codex_visibility':'field_notes'}})
    fact=save_knowledge_fact(s,monster['id'],{'title':'Secret weakness','body':'Weak to sonic','tier':'known'},campaign_id=cid)
    pool=save_loot_pool(s,cid,{'title':'Player Cache','visibility':'players'});save_loot_item(s,cid,pool['id'],{'name':'Healing Potion','description':'Restorative draught','quantity':1,'visibility':'players'})
    gm=TestClient(main.app);assert gm.post('/admin/login',data={'password':'admin'}).status_code in {200,303}
    assert gm.get('/gm/v7').status_code==200 and 'Prepare. Run. Resolve. Remember.' in gm.get('/gm/v7').text
    assert gm.get('/api/v7/health').json()['version']=='7.0.0'
    saved=gm.post('/api/v7/entities',json={'kind':'npc','name':'Test NPC','summary':'v1'}).json();gm.post('/api/v7/entities',json={**saved,'summary':'v2'})
    versions=gm.get(f"/api/v7/entities/{saved['id']}/versions").json();assert len(versions)>=2
    assert gm.post(f"/api/v7/entities/{saved['id']}/versions/{versions[-1]['id']}/restore").status_code==200

    p=TestClient(main.app);assert p.get(alice['invite_path'],follow_redirects=False).status_code==303
    api=p.get(f"/api/v7/entities/{monster['id']}");assert api.status_code==200
    blob=json.dumps(api.json()).lower();assert 'full secret rules' not in blob and 'do not leak' not in blob and '"hp": 150' not in blob and 'weak to sonic' not in blob
    listing=json.dumps(p.get('/api/v7/entities').json()).lower();assert 'full secret rules' not in listing and 'do not leak' not in listing and '"hp": 150' not in listing and 'weak to sonic' not in listing
    page=p.get(f"/entity/{monster['id']}");assert page.status_code==200 and 'Field Notes view' in page.text and '150' not in page.text
    app=p.get('/app');assert app.status_code==200 and 'Healing Potion' in app.text
    for label in ('Character','Inventory','Journal','Map','Party'):assert label in app.text
    reveal_fact(s,fact['id'],alice['id'],campaign_id=cid)
    assert 'weak to sonic' in json.dumps(p.get(f"/api/v7/entities/{monster['id']}").json()).lower()


def test_v7_cross_campaign_api_rejects_foreign_permission_override(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    a=default_campaign_id(s);b=save_campaign(s,{'name':'B'})['id'];foreign=create_player_invite(s,'Foreign');set_campaign_members(s,a,[]);set_campaign_members(s,b,[foreign['id']])
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    r=gm.put(f"/api/v7/permissions/invites/{foreign['id']}",json={'view_statblocks':True})
    assert r.status_code==404


def test_v7_foundry_module_zip_contains_managed_sync(tmp_path: Path):
    from app.v6 import build_foundry_module_zip
    s=setup(tmp_path);src=Path(__file__).resolve().parents[1]/'integrations'/'foundry-seeker-bridge';dst=s.root_dir/'integrations'/'foundry-seeker-bridge';dst.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(src,dst)
    out=tmp_path/'bridge.zip';build_foundry_module_zip(s,'https://seeker.up.railway.app',out)
    with zipfile.ZipFile(out) as z:
        manifest=json.loads(z.read('module.json'));bridge=z.read('seeker-bridge.mjs').decode()
    assert manifest['manifest']=='https://seeker.up.railway.app/foundry/seeker-bridge/module.json'
    assert 'managed_documents' in bridge and '__SEEKER_PUBLIC_ORIGIN__' not in bridge
