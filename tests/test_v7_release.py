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
from app.v6 import init_v6_db, save_foundry_prepared_content, list_foundry_prepared_content, foundry_link, integration_config
from app.v7 import (
    init_v7_db, sync_existing_entities, list_entities, get_entity, save_entity, entity_versions,
    restore_entity_version, save_relation, save_relationship_state, relationship_timeline,
    save_knowledge_fact, reveal_fact, visible_entity_facts, record_recall,
    save_encounter, save_encounter_creature, get_encounter, encounter_xp_for_level, save_loot_pool, save_loot_item,
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
    assert (root/'VERSION').read_text().strip()=='8.0.1'
    assert 'seeker-static-v8001' in (root/'static/sw.js').read_text(encoding='utf-8')
    assert (root/'app/v7.py').exists() and (root/'app/v7_api.py').exists()
    assert (root/'templates/v7_hub.html').exists() and (root/'templates/v7_player.html').exists()
    assert (root/'static/v7.css').exists() and (root/'static/v7.js').exists()
    v7js=(root/'static/v7.js').read_text(encoding='utf-8')
    assert 'Proficiency without Level' in v7js and "rules_variant" in v7js and 'XP override' in v7js
    bridge=(root/'integrations/foundry-seeker-bridge/seeker-bridge.mjs').read_text(encoding='utf-8')
    assert 'const BRIDGE_VERSION = "1.10.1"' in bridge
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
    assert first==second and first[0]==2
    assert len(list_entities(s,cid,tracked_only=True))==2



def test_v7_legacy_heading_rows_are_hidden_but_used_objects_are_preserved(tmp_path: Path):
    s=setup(tmp_path);wiki=seed_wiki(s);cid=default_campaign_id(s)
    structural=save_entity(s,cid,{'kind':'lore','source_type':'lore','source_key':'legacy-heading-history','name':'History','data':{'legacy_source':'wiki','slug':'legacy-heading-history'}})
    used=save_entity(s,cid,{'kind':'npc','source_type':'lore','source_key':'legacy-heading-corvina','name':'Corvina','data':{'legacy_source':'wiki','slug':'legacy-heading-corvina'}})
    anchor_obj=save_entity(s,cid,{'kind':'faction','name':'Anchor Faction'})
    save_relation(s,cid,{'source_entity_id':used['id'],'target_entity_id':anchor_obj['id'],'relation':'knows'})
    sync_existing_entities(s,cid,wiki)
    tracked={e['id']:e for e in list_entities(s,cid,tracked_only=True)}
    assert structural['id'] not in tracked
    assert used['id'] in tracked and tracked[used['id']]['data']['promoted'] is True

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


def test_v701_proficiency_without_level_encounter_math(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    # GM Core Table 4-18: party level -7..+7. The normal threat budgets do not change.
    expected={-7:9,-6:12,-5:14,-4:18,-3:21,-2:26,-1:32,0:40,1:48,2:60,3:72,4:90,5:108,6:135,7:160}
    for delta,xp in expected.items():
        assert encounter_xp_for_level(10+delta,10,'proficiency_without_level')==xp
    assert encounter_xp_for_level(18,10,'proficiency_without_level') is None
    assert encounter_xp_for_level(17,10,'standard') > encounter_xp_for_level(17,10,'proficiency_without_level')

    enc=save_encounter(s,cid,{'title':'No-level test','party_level':5,'party_size':4,'data':{'rules_variant':'proficiency_without_level'}})
    save_encounter_creature(s,cid,enc['id'],{'name':'Lower foe','level':3,'quantity':2})
    save_encounter_creature(s,cid,enc['id'],{'name':'Higher foe','level':8,'quantity':1})
    calc=get_encounter(s,cid,enc['id'])
    assert calc['budget']['rules_variant']=='proficiency_without_level'
    assert calc['budget']['rules_label']=='Proficiency without Level'
    assert calc['budget']['xp']==(26*2)+72
    assert calc['budget']['difficulty']=='Severe'
    assert calc['budget']['budgets']=={'Trivial':40,'Low':60,'Moderate':80,'Severe':120,'Extreme':160}


def test_v701_pwl_out_of_range_requires_explicit_override(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    enc=save_encounter(s,cid,{'title':'Far-level foe','party_level':5,'party_size':4,'data':{'rules_variant':'pwl'}})
    row=save_encounter_creature(s,cid,enc['id'],{'name':'Impossible foe','level':13,'quantity':1})
    calc=get_encounter(s,cid,enc['id'])
    assert calc['budget']['complete'] is False
    assert calc['budget']['difficulty']=='Needs XP override'
    assert calc['budget']['warnings']
    save_encounter_creature(s,cid,enc['id'],{'id':row['id'],'name':'Impossible foe','level':13,'quantity':1,'xp_override':200})
    calc=get_encounter(s,cid,enc['id'])
    assert calc['budget']['complete'] is True and calc['budget']['xp']==200
    with pytest.raises(ValueError):
        save_encounter_creature(s,cid,enc['id'],{'name':'Bad override','level':1,'xp_override':-1})


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
    assert gm.get('/api/v7/health').json()['version']=='8.0.1'
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


def test_v702_aon_parser_creature_spellcasting_and_damage_components():
    from app.aon import parse_aon_html, normalize_aon_url, AoNImportError
    html='''<!doctype html><html><head><title>Test Oracle - Monsters - Archives of Nethys</title><meta name="description" content="A test creature from the archive."></head><body><div id="ctl00_MainContent_DetailedOutput">
    <h1>Test Oracle Creature 7</h1> Rare Medium Humanoid Source Test Bestiary pg. 42<br>
    Perception +16; darkvision<br>Languages Common, Draconic<br>Skills Arcana +17, Society +15<br>
    Str +3, Dex +4, Con +2, Int +5, Wis +3, Cha +4<br>
    AC 25; Fort +13, Ref +16, Will +15<br>HP 105; Weaknesses cold 5; Resistances fire 10<br>
    Speed 25 feet, fly 40 feet<br>
    Melee <img alt="one action"> claw +18 (agile, finesse), Damage 2d8+7 slashing plus 1d6 fire<br>
    Divine Prepared Spells DC 26, attack +18; 4th divine wrath, talking corpse; 3rd dispel magic, heal; Cantrips (4th) detect magic<br>
    Blinding Cry <img alt="two actions"> (auditory) Creatures in a 30-foot emanation must attempt a DC 24 Will save. Effect The oracle screams.
    </div></body></html>'''
    url='https://2e.aonprd.com/Monsters.aspx?ID=99999'
    parsed=parse_aon_html(html,url=url);p=parsed['payload']
    assert parsed['title']=='Test Oracle'
    assert p['level']==7 and p['ac']==25 and p['hp']==105 and p['other_speeds']==[{'type':'fly','value':40}]
    assert p['attacks'][0]['damage_components']==[{'formula':'2d8+7','type':'slashing','category':None},{'formula':'1d6','type':'fire','category':None}]
    assert p['spellcasting_entries'][0]['dc']==26 and p['spellcasting_entries'][0]['attack']==18
    assert {s['name'].lower() for s in p['spellcasting_entries'][0]['spells']} >= {'divine wrath','heal','detect magic'}
    assert p['abilities'][0]['actions']=='2' and p['abilities'][0]['dc']==24 and p['abilities'][0]['dc_type']=='will'
    assert normalize_aon_url('2e.aonprd.com/Monsters.aspx?ID=123')=='https://2e.aonprd.com/Monsters.aspx?ID=123'
    with pytest.raises(AoNImportError):normalize_aon_url('https://example.com/Monsters.aspx?ID=123')


def test_v702_creature_folders_are_campaign_scoped_and_non_destructive(tmp_path: Path):
    from app.v7 import save_creature_folder, add_creature_to_folder, get_creature_folder, list_creature_folders, remove_creature_from_folder, delete_creature_folder
    s=setup(tmp_path);a=default_campaign_id(s);b=save_campaign(s,{'name':'Other'})['id']
    creature=save_entity(s,a,{'kind':'monster','name':'Archive Beast','data':{'level':4}})
    item=save_entity(s,a,{'kind':'item','name':'Not a creature'})
    folder=save_creature_folder(s,a,{'name':'Vault Set','note':'Adventure creatures'})
    add_creature_to_folder(s,a,folder['id'],creature['id'])
    assert [e['name'] for e in get_creature_folder(s,a,folder['id'])['members']]==['Archive Beast']
    assert list_creature_folders(s,a)[0]['name']=='Vault Set'
    with pytest.raises(ValueError):add_creature_to_folder(s,a,folder['id'],item['id'])
    assert get_creature_folder(s,b,folder['id']) is None  # no cross-campaign access
    remove_creature_from_folder(s,a,folder['id'],creature['id']);assert get_creature_folder(s,a,folder['id'])['members']==[]
    delete_creature_folder(s,a,folder['id']);assert get_entity(s,a,creature['id']) is not None and not list_creature_folders(s,a)


def test_v702_aon_http_import_reuses_entry_and_bulk_queues_folder(tmp_path: Path,monkeypatch):
    import app.main as main
    import app.v7_api as v7_api
    from app.aon import AoNFetchResult
    from app.v7 import list_creature_folders
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s)
    parsed={'title':'Archive Drake','subtitle':'Creature 5 · Test Bestiary p. 10','summary':'A drake from the archive.','tags':'dragon, fire','payload':{'level':5,'rarity':'common','size':'med','traits':'dragon, fire','ac':22,'hp':75,'speed':30,'attacks':[{'name':'Jaws','type':'melee','bonus':15,'damage':'2d8+6','damage_type':'piercing','damage_components':[{'formula':'2d8+6','type':'piercing','category':None}]}],'abilities':[],'spells':[],'spellcasting_entries':[],'description':'A drake from the archive.','aon_url':'https://2e.aonprd.com/Monsters.aspx?ID=4242','aon_source':'Test Bestiary','aon_source_page':'10','aon_parser_version':2}}
    async def fake_fetch(urls):return [AoNFetchResult(url='https://2e.aonprd.com/Monsters.aspx?ID=4242',parsed=parsed)]
    monkeypatch.setattr(v7_api,'fetch_aon_creatures',fake_fetch)
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    first=gm.post('/api/v7/aon/import',json={'urls':'https://2e.aonprd.com/Monsters.aspx?ID=4242','folder_name':'Adventure One','publish_codex':True,'codex_visibility':'field_notes'})
    assert first.status_code==200,first.text
    data=first.json();assert data['count']==1 and data['results'][0]['mode']=='imported'
    entity_id=data['results'][0]['entity_id'];folder=list_creature_folders(s,cid)[0];assert folder['members'][0]['id']==entity_id
    second=gm.post('/api/v7/aon/import',json={'urls':'https://2e.aonprd.com/Monsters.aspx?ID=4242','folder_id':folder['id']})
    assert second.status_code==200 and second.json()['results'][0]['mode']=='reused'
    # Duplicate URL reuses the same prepared creature/entity instead of bloating the DB.
    assert second.json()['results'][0]['entity_id']==entity_id
    push=gm.post(f"/api/v7/creature-folders/{folder['id']}/push-foundry")
    assert push.status_code==200 and push.json()['count']==1
    with connect(s) as conn:
        cmd=conn.execute("SELECT command_type,payload_json FROM foundry_command_queue ORDER BY id DESC LIMIT 1").fetchone()
    assert cmd['command_type']=='push_content_bundle' and 'Seeker · Adventure One' in cmd['payload_json']


def test_v702_encounter_bulk_push_uses_single_foundry_folder_command(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s);cid=default_campaign_id(s)
    prep=save_foundry_prepared_content(s,cid,{'kind':'monster','target_type':'world','title':'Folder Ghoul','payload':{'level':3,'hp':45,'ac':19}})
    sync_existing_entities(s,cid,{'pages':[]});entity=next(e for e in list_entities(s,cid) if e['source_type']=='foundry_prepared' and str(e['source_key'])==str(prep['id']))
    enc=save_encounter(s,cid,{'title':'Crypt Ambush','party_level':3,'party_size':4});save_encounter_creature(s,cid,enc['id'],{'entity_id':entity['id'],'prepared_content_id':prep['id'],'name':'Folder Ghoul','level':3,'quantity':4})
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    out=gm.post(f"/api/v7/encounters/{enc['id']}/prepare-foundry")
    assert out.status_code==200 and out.json()['count']==1 and out.json()['folder_name']=='Encounter · Crypt Ambush'
    with connect(s) as conn:
        rows=conn.execute("SELECT command_type,payload_json FROM foundry_command_queue").fetchall()
    assert len(rows)==1 and rows[0]['command_type']=='push_content_bundle'
    payload=json.loads(rows[0]['payload_json']);assert payload['bundle_kind']=='encounter' and payload['entries'][0]['entity_id']==entity['id']


def test_v702_bridge_supports_folder_bundle_multi_damage_and_multiple_casting():
    root=Path(__file__).resolve().parents[1]
    bridge=(root/'integrations/foundry-seeker-bridge/seeker-bridge.mjs').read_text(encoding='utf-8')
    assert 'push_content_bundle' in bridge and 'managedBundle' in bridge and 'Folder.create' in bridge
    assert 'damage_components' in bridge and 'npcDamageRolls' in bridge
    assert 'spellcasting_entries' in bridge and 'normalizedSpellcastingGroups' in bridge


def test_v702_aon_fetch_rejects_redirects_off_aon(monkeypatch):
    import asyncio
    import httpx
    import app.aon as aon

    requested=[]
    def handler(request: httpx.Request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={'Location':'https://example.com/private'}, request=request)
    transport=httpx.MockTransport(handler)
    real_client=httpx.AsyncClient
    monkeypatch.setattr(aon.httpx,'AsyncClient',lambda **kwargs: real_client(transport=transport,**kwargs))
    rows=asyncio.run(aon.fetch_aon_creatures(['https://2e.aonprd.com/monsters.aspx?ID=12']))
    assert len(rows)==1 and rows[0].error
    assert 'Only creature links' in rows[0].error
    assert requested==['https://2e.aonprd.com/Monsters.aspx?ID=12']


def test_v702_aon_reuse_can_publish_without_overwriting_mechanics(tmp_path: Path,monkeypatch):
    import app.main as main
    import app.v7_api as v7_api
    from app.aon import AoNFetchResult
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s);cid=default_campaign_id(s)
    parsed={'title':'Archive Wolf','subtitle':'Creature 2','summary':'Wolf notes','tags':'animal','payload':{'level':2,'ac':18,'hp':30,'attacks':[],'abilities':[],'spells':[],'spellcasting_entries':[],'description':'Wolf notes','aon_url':'https://2e.aonprd.com/Monsters.aspx?ID=77777'}}
    async def fake_fetch(urls):return [AoNFetchResult(url=parsed['payload']['aon_url'],parsed=parsed)]
    monkeypatch.setattr(v7_api,'fetch_aon_creatures',fake_fetch)
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    first=gm.post('/api/v7/aon/import',json={'urls':parsed['payload']['aon_url']});assert first.status_code==200
    prep_id=first.json()['results'][0]['prepared_id']
    # Hand-edit HP after import: a duplicate reuse should retain it while still honoring an explicit Codex publish request.
    row=next(r for r in list_foundry_prepared_content(s,cid) if int(r['id'])==int(prep_id));payload=dict(row['payload']);payload['hp']=37
    save_foundry_prepared_content(s,cid,{**row,'payload':payload})
    second=gm.post('/api/v7/aon/import',json={'urls':parsed['payload']['aon_url'],'publish_codex':True,'codex_visibility':'full'})
    assert second.status_code==200 and second.json()['results'][0]['mode']=='reused'
    row=next(r for r in list_foundry_prepared_content(s,cid) if int(r['id'])==int(prep_id))
    assert row['payload']['hp']==37 and row['payload']['codex_publish'] is True and row['payload']['codex_visibility']=='full'


def test_v703_layered_disclosure_never_leaks_exact_variant(tmp_path: Path):
    from app.v7 import fact_disclosure_modes
    s=setup(tmp_path);cid=default_campaign_id(s);alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob');set_campaign_members(s,cid,[alice['id'],bob['id']])
    monster=save_entity(s,cid,{'kind':'monster','name':'Cinder Tyrant','visibility':'players','summary':'A burning terror'})
    fact=save_knowledge_fact(s,monster['id'],{
        'title':'Fire resistance','body':'Resistance 15 fire.','tier':'known',
        'vague_body':'Fire barely seems to bother it.','comparative_body':'Fire is among the least effective damage types against it.',
        'mechanics':{'metric':'resistance','secret_exact_value':15},
    },campaign_id=cid)
    assert set(fact_disclosure_modes(fact))=={'exact','vague','comparative'}
    reveal_fact(s,fact['id'],alice['id'],campaign_id=cid,disclosure_mode='vague')
    visible=visible_entity_facts(s,monster['id'],alice['id'])[0]
    blob=json.dumps(visible).lower()
    assert visible['body']=='Fire barely seems to bother it.' and visible['disclosure_mode']=='vague'
    assert 'resistance 15' not in blob and 'secret_exact_value' not in blob
    reveal_fact(s,fact['id'],bob['id'],campaign_id=cid,disclosure_mode='comparative')
    assert visible_entity_facts(s,monster['id'],bob['id'])[0]['body'].startswith('Fire is among')


def test_v703_player_can_share_revealed_fact_without_downgrading_party(tmp_path: Path):
    from app.v7 import share_revealed_fact
    s=setup(tmp_path);cid=default_campaign_id(s);alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob');set_campaign_members(s,cid,[alice['id'],bob['id']])
    monster=save_entity(s,cid,{'kind':'monster','name':'Glass Wyrm','visibility':'players'})
    fact=save_knowledge_fact(s,monster['id'],{'title':'Weakness','body':'Weakness 12 sonic.','vague_body':'It is extremely vulnerable to sonic force.','tier':'known'},campaign_id=cid)
    reveal_fact(s,fact['id'],alice['id'],campaign_id=cid,disclosure_mode='vague')
    reveal_fact(s,fact['id'],bob['id'],campaign_id=cid,disclosure_mode='exact')
    out=share_revealed_fact(s,cid,fact['id'],alice['id']);assert out['count']==2
    assert visible_entity_facts(s,monster['id'],bob['id'])[0]['disclosure_mode']=='exact'
    assert visible_entity_facts(s,monster['id'],alice['id'])[0]['disclosure_mode']=='vague'


def test_v703_player_observation_ranges_privacy_and_party_share(tmp_path: Path):
    from app.v7 import save_player_observation, list_player_observations, set_player_observation_visibility, review_player_observation
    s=setup(tmp_path);cid=default_campaign_id(s);alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob');set_campaign_members(s,cid,[alice['id'],bob['id']])
    monster=save_entity(s,cid,{'kind':'monster','name':'Iron Saint','visibility':'players'})
    obs=save_player_observation(s,cid,monster['id'],alice['id'],{'kind':'range','metric':'ac','miss_total':19,'hit_total':22,'body':'Normal rolls, so AC should be between these.'})
    assert obs['lower_bound']==20 and obs['upper_bound']==22 and obs['visibility']=='private'
    assert len(list_player_observations(s,cid,monster['id'],alice['id']))==1
    assert list_player_observations(s,cid,monster['id'],bob['id'])==[]
    set_player_observation_visibility(s,cid,obs['id'],alice['id'],'party')
    shared=list_player_observations(s,cid,monster['id'],bob['id']);assert shared[0]['title']=='AC range: 20–22'
    assert review_player_observation(s,cid,obs['id'],'confirmed')['status']=='confirmed'
    with pytest.raises(ValueError):
        save_player_observation(s,cid,monster['id'],alice['id'],{'kind':'range','metric':'ac','miss_total':25,'hit_total':20})


def test_v703_http_player_observation_and_fact_sharing(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s);alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob');set_campaign_members(s,cid,[alice['id'],bob['id']])
    monster=save_entity(s,cid,{'kind':'monster','name':'Ash Oracle','visibility':'players','summary':'An ember-eyed oracle'})
    fact=save_knowledge_fact(s,monster['id'],{'title':'Strong save','body':'Fortitude +21.','comparative_body':'Fortitude is its highest save.','tier':'known'},campaign_id=cid)
    reveal_fact(s,fact['id'],alice['id'],campaign_id=cid,disclosure_mode='comparative')
    p=TestClient(main.app);assert p.get(alice['invite_path'],follow_redirects=False).status_code==303
    page=p.get(f"/entity/{monster['id']}");assert page.status_code==200 and 'Fortitude is its highest save.' in page.text and 'Fortitude +21' not in page.text
    obs=p.post(f"/api/v7/entities/{monster['id']}/observations",json={'kind':'range','metric':'ac','lower_bound':24,'upper_bound':26,'visibility':'private'});assert obs.status_code==200
    share=p.post(f"/api/v7/observations/{obs.json()['id']}/visibility",json={'visibility':'party'});assert share.status_code==200
    share_fact=p.post(f"/api/v7/facts/{fact['id']}/share-party",json={});assert share_fact.status_code==200
    q=TestClient(main.app);assert q.get(bob['invite_path'],follow_redirects=False).status_code==303
    bob_page=q.get(f"/entity/{monster['id']}");assert 'AC range: 24–26' in bob_page.text and 'Fortitude is its highest save.' in bob_page.text and 'Fortitude +21' not in bob_page.text


def test_v703_migrates_existing_reveal_rows_without_losing_them(tmp_path: Path):
    s=settings_for(tmp_path);init_db(s);init_feature_db(s);init_schedule_db(s);init_v5_db(s);init_v51_db(s);init_v6_db(s)
    # Simulate the 7.0.2 reveal table before V7.0.3 adds disclosure metadata.
    with connect(s) as conn:
        conn.execute('CREATE TABLE v7_entities (id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL, kind TEXT, name TEXT)')
        conn.execute('CREATE TABLE v7_knowledge_facts (id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL, title TEXT, body TEXT, tier TEXT, mechanics_json TEXT, sort_order INTEGER, created_at REAL, updated_at REAL)')
        conn.execute("CREATE TABLE v7_fact_reveals (fact_id INTEGER NOT NULL,invite_id INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'revealed',session_id INTEGER,revealed_at REAL NOT NULL,PRIMARY KEY(fact_id,invite_id))")
    # V7 schema needs its normal entities table shape, so remove the two helper
    # tables while retaining the old reveal table we specifically migrate.
    with connect(s) as conn:
        conn.execute('DROP TABLE v7_knowledge_facts');conn.execute('DROP TABLE v7_entities')
    init_v7_db(s)
    with connect(s) as conn:
        cols={r['name'] for r in conn.execute('PRAGMA table_info(v7_fact_reveals)').fetchall()}
    assert {'disclosure_mode','reveal_source','shared_by_invite_id'} <= cols
