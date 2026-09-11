from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.storage import init_db, create_player_invite, connect, set_setting
from app.features import init_feature_db, save_session
from app.scheduling import init_schedule_db
from app.v5 import init_v5_db
from app.v51 import init_v51_db
from app.v6 import init_v6_db, save_foundry_prepared_content
from app.v7 import init_v7_db, sync_existing_entities, list_entities
from app.v8 import (
    init_v8_db, module_settings, save_module_settings, source_structure, source_map,
    refresh_source_mappings, snapshot_source, restore_source_revision, revisions,
    save_workflow, workflow, command_catalog,
)
from app.campaigns import default_campaign_id, set_campaign_members
from app.latex import build_wiki


def settings_for(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=settings_for(tmp_path)
    init_db(s);init_feature_db(s);init_schedule_db(s);init_v5_db(s);init_v51_db(s);init_v6_db(s);init_v7_db(s);init_v8_db(s)
    return s


def seed_source(s: Settings):
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}
\begin{document}
\chapter{Jotunari}
\section{People of the Peaks}Lore text.
\section{17th Level}
\feat{Cloudbreaker}{17}{jotunari, ancestry}{A feat body.}
\chapter{Places}
\section{Stormhold}A city above the clouds.
\end{document}''',encoding='utf-8')
    return build_wiki(s)


def test_v8_release_contract_and_assets():
    root=Path(__file__).resolve().parents[1]
    assert (root/'VERSION').read_text().strip()=='9.0.1'
    sw=(root/'static/sw.js').read_text(encoding='utf-8')
    assert 'seeker-static-v9001' in sw and '/static/v8.js?v=9001' in sw
    assert (root/'app/v8.py').exists() and (root/'app/v8_api.py').exists()
    assert (root/'templates/v8_workspace.html').exists() and (root/'templates/v8_player_portal.html').exists()
    base=(root/'templates/base.html').read_text(encoding='utf-8')
    assert 'Campaign Workspace' in base and 'href="/app/v8"' in base and 'Seeker 8' not in base
    js=(root/'static/v8.js').read_text(encoding='utf-8')
    for marker in ['PREP → RUN → CHRONICLE','/api/v8/source','data-restore-entity','writeResource','applyModules']:
        assert marker in (root/'templates/v8_workspace.html').read_text(encoding='utf-8')+js
    forge=(root/'static/foundry-workshop.js').read_text(encoding='utf-8')
    assert 'requestedNew' in forge and 'Duplicate feat name' in forge and 'data-fw-sort-bundle-feats' in (root/'templates/gm_foundry_workshop.html').read_text(encoding='utf-8')


def test_v8_schema_modules_source_map_and_revision_restore(tmp_path: Path):
    s=setup(tmp_path);wiki=seed_source(s);cid=default_campaign_id(s)
    mods=module_settings(s,cid);assert {m['id'] for m in mods}>={'dashboard','session','codex','homebrew','atlas','handouts','foundry','chronicle','diagnostics'}
    changed=save_module_settings(s,cid,[{'id':'homebrew','enabled':False},{'id':'foundry','enabled':True}])
    assert next(m for m in changed if m['id']=='homebrew')['enabled'] is False
    sync_existing_entities(s,cid,wiki);entities=list_entities(s,cid,tracked_only=True);assert entities==[]
    # Plain chapter/section headings are document structure, not campaign objects.
    assert refresh_source_mappings(s,cid,entities)==0
    sm=source_map(s,cid,entities);main=next(x for x in sm['files'] if x['path']=='main.tex')
    assert main['root']['title']=='Jotunari' and any(h['title']=='17th Level' and h['feat_count']==1 for h in main['headings'])
    rid=snapshot_source(s,cid,'main.tex',label='Before test',created_by='pytest');assert rid
    original=(s.project_dir/'main.tex').read_text();(s.project_dir/'main.tex').write_text(original+'\n% changed',encoding='utf-8')
    restore_source_revision(s,cid,rid,created_by='pytest')
    assert (s.project_dir/'main.tex').read_text()==original
    assert revisions(s,cid,'source','main.tex')


def test_v8_session_workflow_is_persistent(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s);sess=save_session(s,{'campaign_id':cid,'title':'Storm Council','status':'planned'})
    prep=save_workflow(s,cid,sess['id'],{'stage':'prep','prep':{'notes':'Ask about the broken treaty.'}},actor='GM')
    assert prep['stage']=='prep' and prep['prep']['notes'].startswith('Ask')
    run=save_workflow(s,cid,sess['id'],{'stage':'run','run':{'notes':'The duke fled.'}},actor='GM')
    assert workflow(s,cid,sess['id'])['run']['notes']=='The duke fled.' and run['stage']=='run'


def test_v8_http_workspace_source_studio_portal_and_command_palette(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);wiki=seed_source(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s);save_session(s,{'campaign_id':cid,'title':'Storm Council','status':'planned'})
    inv=create_player_invite(s,'Alice');set_campaign_members(s,cid,[inv['id']])
    gm=TestClient(main.app);assert gm.post('/admin/login',data={'password':'admin'}).status_code in {200,303}
    page=gm.get('/app/v8');assert page.status_code==200 and 'CAMPAIGN WORKSPACE' in page.text and 'SOURCE MAP' in page.text and 'Seeker 8' not in page.text
    state=gm.get('/api/v8/state');assert state.status_code==200 and state.json()['version']=='9.0.1'
    payload=state.json();assert payload['entities']==[] and payload['codex_candidates']
    candidate=payload['codex_candidates'][0]
    tracked=gm.post('/api/v8/codex/track',json={'slug':candidate['slug'],'kind':'place'});assert tracked.status_code==200
    tracked_id=tracked.json()['entity']['id'];assert any(e['id']==tracked_id for e in gm.get('/api/v8/state').json()['entities'])
    assert gm.post(f'/api/v8/entity/{tracked_id}/untrack',json={}).status_code==200
    assert all(e['id']!=tracked_id for e in gm.get('/api/v8/state').json()['entities'])
    commands=gm.get('/api/v8/command?q=source').json();assert any(x.get('href')=='/app/v8#sources' for x in commands)
    source=gm.get('/api/v8/source',params={'path':'main.tex'});assert source.status_code==200 and 'Jotunari' in source.json()['text']
    text=source.json()['text'].replace('Lore text.','Lore text updated.')
    saved=gm.put('/api/v8/source',json={'path':'main.tex','text':text,'label':'HTTP edit'});assert saved.status_code==200
    reread=gm.get('/api/v8/source',params={'path':'main.tex'}).json();assert 'Lore text updated.' in reread['text'] and reread['revisions']
    p=TestClient(main.app);assert p.get(inv['invite_path'],follow_redirects=False).status_code==303
    portal=p.get('/portal');assert portal.status_code==200 and 'Campaign Portal' in portal.text
    assert p.get('/app/v8').status_code in {401,403}



def test_v8_source_backed_homebrew_is_one_tracked_object(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    wiki={'pages':[
        {'slug':'jotunari','title':'Jotunari','chapter':'Jotunari','level':'chapter','source_file':'jotunari.tex','homebrew_kind':'ancestry','homebrew_owner_slug':'jotunari','homebrew_owner_title':'Jotunari','homebrew_source_scope':'file','plain_text':'Lore','excerpt':'Mountain people.'},
        {'slug':'jotunari-heritages','title':'Heritages','chapter':'Jotunari','level':'section','source_file':'jotunari.tex','homebrew_kind':'ancestry','homebrew_owner_slug':'jotunari','homebrew_owner_title':'Jotunari','homebrew_source_scope':'file','plain_text':'Heritage rules','excerpt':''},
        {'slug':'jotunari-17','title':'17th Level','chapter':'Jotunari','level':'section','source_file':'jotunari.tex','homebrew_kind':'ancestry','homebrew_owner_slug':'jotunari','homebrew_owner_title':'Jotunari','homebrew_source_scope':'file','plain_text':'Cloudbreaker','excerpt':''},
    ]}
    sync_existing_entities(s,cid,wiki)
    rows=list_entities(s,cid,tracked_only=True)
    hb=[e for e in rows if e['source_type']=='homebrew_source']
    assert len(hb)==1 and hb[0]['name']=='Jotunari' and hb[0]['kind']=='ancestry'


def test_v8_explicit_object_root_is_tracked_automatically(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    wiki={'pages':[{'slug':'corvina','title':'Corvina Dampierre','chapter':'People','level':'entity','source_file':'people.tex','source_line':12,'plain_text':'A courier with a silver key.','excerpt':'Courier.'}]}
    sync_existing_entities(s,cid,wiki)
    rows=list_entities(s,cid,tracked_only=True)
    assert len(rows)==1 and rows[0]['name']=='Corvina Dampierre' and rows[0]['kind']=='npc'


def test_v8_source_linked_forge_record_does_not_duplicate_source_object(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    prepared=save_foundry_prepared_content(s,cid,{'kind':'homebrew','title':'Jotunari','payload':{'homebrew_document':'ancestry','source_linked':True,'source_link_path':'jotunari.tex'}})
    # A source-linked ancestry/archetype should not create a standalone prepared-content object.
    sync_existing_entities(s,cid,{'pages':[]})
    assert not any(e['source_type']=='foundry_prepared' for e in list_entities(s,cid,tracked_only=True))
    wiki={'pages':[{'slug':'jotunari','title':'Jotunari','chapter':'Jotunari','level':'chapter','source_file':'jotunari.tex','homebrew_kind':'ancestry','homebrew_owner_slug':'jotunari','homebrew_owner_title':'Jotunari','homebrew_source_scope':'file','plain_text':'Lore','excerpt':'Mountain people.'}]}
    sync_existing_entities(s,cid,wiki)
    rows=list_entities(s,cid,tracked_only=True)
    assert len(rows)==1 and rows[0]['source_type']=='homebrew_source' and rows[0]['name']=='Jotunari'
    assert rows[0]['data']['source_path']=='jotunari.tex'

def test_v8_command_catalog_and_source_structure_are_contextual(tmp_path: Path):
    s=setup(tmp_path);wiki=seed_source(s);cid=default_campaign_id(s);sync_existing_entities(s,cid,wiki)
    rows=command_catalog(s,cid,wiki,'jotunari')
    assert any('Jotunari' in x['title'] or 'Jotunari' in x.get('subtitle','') for x in rows)
    structure=source_structure(r'\chapter{Ancestry}\section{Lore}Words\section{1st Level}\feat{A}{1}{x}{y}')
    assert structure[0]['command']=='chapter' and structure[-1]['feat_count']==1
