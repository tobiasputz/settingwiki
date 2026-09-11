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
from app.latex import build_wiki, extract_pf2e_rules
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
    assert 'const BRIDGE_VERSION = "1.9.1"' in bridge
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


def test_normal_latex_file_can_be_classified_as_one_ancestry_without_moving_source(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    (s.project_dir/'chapters').mkdir()
    source=(s.project_dir/'chapters/jotunari.tex')
    original=r'''\section{Jotunari}
The Jotunari are stone-blooded wanderers.
\subsection{Heritages}
Choose a Jotunari heritage appropriate to your lineage.
\subsection{1st Level}
\feat{Stone Memory}{1}{jotunari, ancestry}{Recall the voice of the mountain.}
\subsection{5th Level}
\feat{Giant's Step}{5}{jotunari, ancestry}{Stride with impossible reach.}
'''
    source.write_text(original,encoding='utf-8')
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}\begin{document}
\chapter{Ancestries}
\input{chapters/jotunari}
\end{document}''',encoding='utf-8')
    build_wiki(s);gm=gm_client(main,s);cid=default_campaign_id(s)

    # This is the backend used by the three-dot menu beside jotunari.tex.
    marked=gm.put('/api/admin/file/homebrew',json={'path':'chapters/jotunari.tex','kind':'ancestry'})
    assert marked.status_code==200,marked.text
    file_row=next(f for f in gm.get('/api/admin/files').json() if f['path']=='chapters/jotunari.tex')
    assert file_row['homebrew_kind']=='ancestry'

    # Classification changes Seeker's library placement only: the campaign
    # source remains byte-for-byte in its original folder for PDF compilation.
    assert source.read_text(encoding='utf-8')==original
    assert source.exists() and not (s.project_dir/'homebrew').exists()

    rebuilt=gm.get('/api/admin/codex').json()
    source_pages=[p for p in rebuilt['pages'] if p.get('source_file')=='chapters/jotunari.tex']
    assert source_pages
    jot=next(p for p in source_pages if p['title']=='Jotunari')
    assert all(p['homebrew_kind']=='ancestry' for p in source_pages)
    assert all(p['homebrew_owner_slug']==jot['slug'] for p in source_pages)
    assert all(p['homebrew_owner_title']=='Jotunari' for p in source_pages)
    detected=[r for p in source_pages for r in p.get('pf2e_rules',[])]
    assert [(r['title'],r['level']) for r in detected]==[('Stone Memory',1),("Giant's Step",5)]

    main_codex=gm.get('/')
    assert main_codex.status_code==200 and 'Jotunari' not in main_codex.text
    homebrew=gm.get('/homebrew')
    assert homebrew.status_code==200
    assert 'Jotunari' in homebrew.text
    # The landing page is intentionally one ancestry card, not a second list of
    # all 1st/5th/etc. subsections or feat cards.
    assert 'Stone Memory' not in homebrew.text and "Giant&#39;s Step" not in homebrew.text
    detail=gm.get(f"/homebrew/source/{jot['slug']}")
    assert detail.status_code==200
    assert 'The Jotunari are stone-blooded wanderers.' in detail.text
    assert 'Heritages' in detail.text and 'Stone Memory' in detail.text and "Giant&#39;s Step" in detail.text
    assert 'LEVEL 1' in detail.text and 'LEVEL 5' in detail.text

    pushed=gm.post(f"/api/homebrew/source/{jot['slug']}/foundry")
    assert pushed.status_code==200,pushed.text
    commands=claim_foundry_commands(s,cid,integration_config(s,cid,include_secret=True)['foundry_bridge_token'])
    command=next(c for c in commands if c['id']==pushed.json()['command']['id'])
    assert command['command_type']=='push_ancestry_bundle'
    assert command['payload']['title']=='Jotunari'
    assert command['payload']['source_file'].endswith('chapters/jotunari.tex')
    assert command['payload']['command_nonce']
    assert [(r['title'],r['level']) for r in command['payload']['rules']]==[('Stone Memory',1),("Giant's Step",5)]


def test_source_scoped_archetypes_are_separate_from_ancestries(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    (s.project_dir/'chapters').mkdir()
    (s.project_dir/'chapters/jotunari.tex').write_text(r'''\section{Jotunari}\subsection{1st Level}\feat{Stone Memory}{1}{jotunari, ancestry}{Remember.}''',encoding='utf-8')
    (s.project_dir/'chapters/stonebound.tex').write_text(r'''\section{Stonebound}\subsection{Dedication Feats}\feat{Stonebound Dedication}{2}{archetype, dedication}{Become stonebound.}''',encoding='utf-8')
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}\begin{document}\chapter{Rules}\input{chapters/jotunari}\input{chapters/stonebound}\end{document}''',encoding='utf-8')
    build_wiki(s);gm=gm_client(main,s)
    assert gm.put('/api/admin/file/homebrew',json={'path':'chapters/jotunari.tex','kind':'ancestry'}).status_code==200
    assert gm.put('/api/admin/file/homebrew',json={'path':'chapters/stonebound.tex','kind':'archetype'}).status_code==200
    landing=gm.get('/homebrew')
    assert landing.status_code==200 and 'Ancestries' in landing.text and 'Archetypes' in landing.text
    assert 'Jotunari' in landing.text and 'Stonebound' in landing.text
    codex=gm.get('/api/admin/codex').json()['pages']
    arch=next(p for p in codex if p['title']=='Stonebound')
    detail=gm.get(f"/homebrew/source/{arch['slug']}")
    assert detail.status_code==200 and 'Archetype feats' in detail.text and 'Stonebound Dedication' in detail.text


def test_pf2e_rule_metadata_is_structured_instead_of_flattened(tmp_path: Path):
    s=setup(tmp_path)
    raw=r'''\feat{Colossal Resilience}{1}{Jotunari}{%
\textbf{Frequency:} once per day\\
\textbf{Prerequisites:} Titan Fortitude\\
\textbf{Trigger:} You would take physical damage\\
\textbf{Requirements:} You are conscious\\
\textbf{Special:} Tomb Jotunari reduce the initial damage.\\
You brace for impact and steel your titanic resolve.
}'''
    rules=extract_pf2e_rules(raw,s,{"custom_macros":[]})
    assert len(rules)==1
    rule=rules[0]
    assert rule['frequency']=='once per day'
    assert rule['prerequisites']=='Titan Fortitude'
    assert rule['trigger']=='You would take physical damage'
    assert rule['requirements']=='You are conscious'
    assert rule['special']=='Tomb Jotunari reduce the initial damage.'
    assert rule['description']=='You brace for impact and steel your titanic resolve.'
    assert 'Frequency' not in rule['description'] and 'Trigger' not in rule['description']


def test_homebrew_forge_latex_target_heading_move_and_duplicate_detection(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    target=s.project_dir/'main.tex'
    target.write_text(r'''\documentclass{book}\begin{document}
\chapter{Rules}
Existing prose.
\chapter{Appendix}
Appendix prose.
\end{document}''',encoding='utf-8')
    build_wiki(s);gm=gm_client(main,s)
    created=gm.post('/api/v61/foundry/content',json={'kind':'feat','title':'Cinder Step','payload':{'level':2,'traits':'fire, general','description':'Stride through cinders.','homebrew_publish':True,'library_section':'general'}})
    assert created.status_code==200;eid=created.json()['id']
    meta=gm.get(f'/api/homebrew/{eid}/latex').json()
    main_target=next(t for t in meta['targets'] if t['path']=='main.tex')
    assert any(h['level']=='chapter' and h['title']=='Rules' for h in main_target['headings'])

    first=gm.post(f'/api/homebrew/{eid}/latex/write',json={'path':'main.tex','heading_level':'chapter','heading_title':'Rules','heading_index':0})
    assert first.status_code==200 and not first.json()['duplicate_detected']
    text=target.read_text(encoding='utf-8')
    assert text.count('SEEKER-HOMEBREW:'+str(eid)+':BEGIN')==1
    assert text.index('SEEKER-HOMEBREW') < text.index(r'\chapter{Appendix}')

    # Re-exporting/moving the same Forge object is an update, never a second copy.
    second=gm.post(f'/api/homebrew/{eid}/latex/write',json={'path':'main.tex','heading_level':'chapter','heading_title':'Appendix','heading_index':0})
    assert second.status_code==200
    text=target.read_text(encoding='utf-8')
    assert text.count('SEEKER-HOMEBREW:'+str(eid)+':BEGIN')==1
    assert text.index('SEEKER-HOMEBREW') > text.index(r'\chapter{Appendix}')

    # If a same-name rule already exists manually, Seeker links to it and does
    # not append a generated duplicate.
    manual=gm.post('/api/v61/foundry/content',json={'kind':'feat','title':'Already Here','payload':{'level':1,'traits':'general','description':'No duplicate.','homebrew_publish':True}})
    mid=manual.json()['id']
    with target.open('a',encoding='utf-8') as fh: fh.write('\n\\feat{Already Here}{1}{general}{Manual source.}\n')
    linked=gm.post(f'/api/homebrew/{mid}/latex/write',json={'path':'main.tex','heading_level':'chapter','heading_title':'Rules','heading_index':0})
    assert linked.status_code==200 and linked.json()['duplicate_detected'] is True
    assert target.read_text(encoding='utf-8').count(r'\feat{Already Here}')==1

def test_bridge_contains_ancestry_bundle_nonce_dedupe_and_absolute_resource_updates():
    bridge=(Path(__file__).resolve().parents[1]/'integrations/foundry-seeker-bridge/seeker-bridge.mjs').read_text(encoding='utf-8')
    assert 'function commandDedupeKey' in bridge and 'payload?.command_nonce' in bridge
    assert 'push_ancestry_bundle' in bridge and 'type: "ancestry"' in bridge
    assert 'mode === "set"' in bridge and 'await actor.update({ [path]: next })' in bridge


def test_exported_forge_rule_merges_with_classified_source_in_homebrew(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    (s.project_dir/'chapters').mkdir()
    source=s.project_dir/'chapters/custom-rules.tex'
    source.write_text(r'''\section{Ashen Customs}\subsection{Feats}\n''',encoding='utf-8')
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}\begin{document}\chapter{Rules}\input{chapters/custom-rules}\end{document}''',encoding='utf-8')
    build_wiki(s);gm=gm_client(main,s)
    assert gm.put('/api/admin/file/homebrew',json={'path':'chapters/custom-rules.tex','kind':'general'}).status_code==200
    created=gm.post('/api/v61/foundry/content',json={'kind':'feat','title':'Ash Walker','payload':{'level':3,'traits':'fire, general','description':'Walk across hot ash.','homebrew_publish':True,'library_section':'general'}})
    eid=created.json()['id']
    written=gm.post(f'/api/homebrew/{eid}/latex/write',json={'path':'chapters/custom-rules.tex','heading_level':'subsection','heading_title':'Feats','heading_index':0})
    assert written.status_code==200
    landing=gm.get('/homebrew')
    # The source-backed bundle owns the exported feat now; the Forge record is
    # retained for editing but is not rendered as a second library card.
    assert f'data-homebrew-entry="{eid}"' not in landing.text
    codex=gm.get('/api/admin/codex').json()['pages']
    owner=next(p for p in codex if p['title']=='Ashen Customs')
    detail=gm.get(f"/homebrew/source/{owner['slug']}")
    assert detail.status_code==200 and detail.text.count('Ash Walker')>=1
