from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from app.config import Settings
from app.storage import init_db, set_setting
from app.features import init_feature_db
from app.scheduling import init_schedule_db
from app.v5 import init_v5_db
from app.v51 import init_v51_db
from app.v6 import init_v6_db, integration_config, claim_foundry_commands
from app.v7 import init_v7_db
from app.campaigns import default_campaign_id
from app.latex import build_wiki
from app.homebrew import classify_homebrew, group_homebrew, homebrew_latex_snippet, upsert_latex_block


def settings_for(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=settings_for(tmp_path);init_db(s);init_feature_db(s);init_schedule_db(s);init_v5_db(s);init_v51_db(s);init_v6_db(s);init_v7_db(s);return s


def seed(s: Settings):
    (s.project_dir/'main.tex').write_text(r'\documentclass{book}\begin{document}\chapter{World}\section{Moon Court}A court.\end{document}',encoding='utf-8');build_wiki(s)


def gm_client(main,s):
    c=TestClient(main.app);assert c.post('/admin/login',data={'password':'admin'}).status_code in {200,303};return c


def test_homebrew_helpers_group_like_rules_reference_and_generate_native_latex():
    ancestry={'id':1,'kind':'feat','title':'Moon Step','summary':'Move lightly.','tags':'elf, ancestry','payload':{'level':5,'traits':'elf, ancestry','feat_category':'ancestry','ancestry_trait':'Elf','description':'Stride up to your Speed.'}}
    action={'id':2,'kind':'action','title':'Emergency Audit','summary':'','payload':{'level':2,'traits':'concentrate','action_cost':'reaction','trigger':'A foe lies about taxes.','description':'Expose the discrepancy.'}}
    grouped=group_homebrew([action,ancestry],include_drafts=True)
    assert grouped[0]['key']=='ancestry' and grouped[0]['groups'][0]['name']=='Elf'
    assert classify_homebrew(action)['section']=='actions'
    assert '\\feat{Moon Step}{5}' in homebrew_latex_snippet(ancestry)
    assert '\\action{Emergency Audit}{\\reaction}' in homebrew_latex_snippet(action)
    once=upsert_latex_block('',2,homebrew_latex_snippet(action));twice=upsert_latex_block(once,2,homebrew_latex_snippet({**action,'title':'Emergency Audit II'}))
    assert twice.count('SEEKER-HOMEBREW:2:BEGIN')==1 and 'Emergency Audit II' in twice


def test_homebrew_page_action_world_item_and_latex_write(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed(s);monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s);cid=default_campaign_id(s)
    created=gm.post('/api/v61/foundry/content',json={'kind':'action','title':'Cinder Leap','summary':'Leap through flame.','payload':{'level':4,'traits':'fire, move','action_cost':'2','description':'Leap 20 feet.','homebrew_publish':True,'library_section':'actions'}})
    assert created.status_code==200;eid=created.json()['id']
    page=gm.get('/homebrew');assert page.status_code==200 and 'Cinder Leap' in page.text and 'Actions &amp; Activities' in page.text
    blocked=gm.put(f'/api/homebrew/{eid}',json={'kind':'monster','title':'Nope','payload':{}});assert blocked.status_code==400
    pushed=gm.post(f'/api/v61/foundry/content/{eid}/push',json={'target_type':'world'});assert pushed.status_code==200
    cfg=integration_config(s,cid,include_secret=True);cmds=claim_foundry_commands(s,cid,cfg['foundry_bridge_token']);cmd=next(c for c in cmds if c['id']==pushed.json()['command']['id'])
    assert cmd['command_type']=='push_prepared_content' and cmd['payload']['prepared_kind']=='action' and cmd['payload']['target_type']=='world'
    latex=gm.get(f'/api/homebrew/{eid}/latex');assert latex.status_code==200 and '\\action{Cinder Leap}{\\actionTwo}' in latex.json()['snippet']
    write=gm.post(f'/api/homebrew/{eid}/latex/write',json={'path':'homebrew/actions/cinder.tex'});assert write.status_code==200
    text=(s.project_dir/'homebrew/actions/cinder.tex').read_text();assert 'SEEKER-HOMEBREW' in text and '\\action{Cinder Leap}' in text


def test_codex_granular_sections_are_server_rendered(tmp_path: Path,monkeypatch):
    import app.main as main
    from app.storage import create_player_invite
    from app.campaigns import set_campaign_members
    s=setup(tmp_path);seed(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s);cid=default_campaign_id(s)
    made=gm.post('/api/v61/foundry/content',json={'kind':'monster','title':'Veiled Drake','summary':'A hidden-scaled hunter.','payload':{'level':6,'ac':24,'hp':95,'perception':15,'traits':'dragon','codex_publish':True,'codex_visibility':'full','codex_sections':{'identity':True,'awareness':False,'defenses':False,'movement':True,'strikes':False,'abilities':False,'spellcasting':False,'description':False},'codex_blurb':'A drake seen at dusk.'}})
    inv=create_player_invite(s,'Alice');set_campaign_members(s,cid,[inv['id']]);player=TestClient(main.app);player.get(inv['invite_path'],follow_redirects=False)
    html=player.get(f"/bestiary/{made.json()['id']}").text
    assert 'IDENTITY' in html and 'MOVEMENT' in html and '>6<' in html
    assert 'DEFENSES' not in html and 'AWARENESS' not in html and '>95<' not in html and '>24<' not in html
    gmhtml=gm.get(f"/bestiary/{made.json()['id']}").text;assert 'DEFENSES' in gmhtml and 'GM ONLY' in gmhtml


def test_studio_move_rewrites_tex_include_and_homebrew_leaves_main_codex(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    (s.project_dir/'chapters').mkdir();(s.project_dir/'chapters/elf.tex').write_text(r'\section{Moon-Blooded Elf}Custom ancestry rules.',encoding='utf-8')
    (s.project_dir/'main.tex').write_text(r'\documentclass{book}\begin{document}\chapter{Setting}Normal lore.\input{chapters/elf}\end{document}',encoding='utf-8');build_wiki(s)
    gm=gm_client(main,s)
    moved=gm.post('/api/admin/file/move',json={'source':'chapters/elf.tex','destination':'homebrew/ancestries/elf/moon-blooded.tex','rewrite_includes':True})
    assert moved.status_code==200 and (s.project_dir/'homebrew/ancestries/elf/moon-blooded.tex').exists()
    assert r'\input{homebrew/ancestries/elf/moon-blooded}' in (s.project_dir/'main.tex').read_text()
    main_page=gm.get('/');assert main_page.status_code==200 and 'Moon-Blooded Elf' not in main_page.text
    hb=gm.get('/homebrew');assert hb.status_code==200 and 'Moon-Blooded Elf' in hb.text and 'homebrew/ancestries/elf/moon-blooded.tex' in hb.text


def test_bridge_has_first_class_action_item_support():
    bridge=(Path(__file__).resolve().parents[1]/'integrations/foundry-seeker-bridge/seeker-bridge.mjs').read_text(encoding='utf-8')
    assert 'const BRIDGE_VERSION = "1.8.0"' in bridge
    assert 'kind === "action" ? "action"' in bridge
    assert 'Item.create(' in bridge and 'createEmbeddedDocuments("Item"' in bridge

def test_homebrew_player_sees_published_not_drafts(tmp_path: Path, monkeypatch):
    import app.main as main
    from app.storage import create_player_invite
    from app.campaigns import set_campaign_members
    s=setup(tmp_path);seed(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s);cid=default_campaign_id(s)
    pub=gm.post('/api/v61/foundry/content',json={'kind':'feat','title':'Shared Feat','payload':{'level':2,'traits':'general','homebrew_publish':True}});assert pub.status_code==200
    draft=gm.post('/api/v61/foundry/content',json={'kind':'feat','title':'Secret Draft','payload':{'level':2,'traits':'general','homebrew_publish':False}});assert draft.status_code==200
    inv=create_player_invite(s,'Reader');set_campaign_members(s,cid,[inv['id']]);player=TestClient(main.app);assert player.get(inv['invite_path'],follow_redirects=False).status_code==303
    page=player.get('/homebrew');assert page.status_code==200 and 'Shared Feat' in page.text and 'Secret Draft' not in page.text


def test_studio_folder_move_rewrites_nested_include_and_main_file(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    (s.project_dir/'rules/ancestry').mkdir(parents=True)
    (s.project_dir/'rules/ancestry/elf.tex').write_text(r'\section{Elf Rules}Moon rules.',encoding='utf-8')
    (s.project_dir/'main.tex').write_text(r'\documentclass{book}\begin{document}\input{rules/ancestry/elf}\end{document}',encoding='utf-8')
    build_wiki(s);gm=gm_client(main,s)
    moved=gm.post('/api/admin/file/move',json={'source':'rules/ancestry','destination':'homebrew/ancestries/elf','rewrite_includes':True})
    assert moved.status_code==200
    assert (s.project_dir/'homebrew/ancestries/elf/elf.tex').exists()
    assert r'\input{homebrew/ancestries/elf/elf}' in (s.project_dir/'main.tex').read_text()
