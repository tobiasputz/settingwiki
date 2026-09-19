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
    assert 'const BRIDGE_VERSION = "1.11.0"' in bridge
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
    # The default library still renders one ancestry card. Feats may exist in the
    # dedicated PF2e Feat index, but that index is hidden until the Feats filter
    # is explicitly selected and does not duplicate them as ancestry cards.
    assert homebrew.text.count('data-homebrew-entry="source-jotunari"') == 1
    assert 'data-homebrew-section="feats" data-homebrew-index="true" hidden' in homebrew.text
    assert 'Stone Memory' in homebrew.text and "Giant&#39;s Step" in homebrew.text
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
\textbf{Access:} Tomb Jotunari\\
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
    assert rule['access']=='Tomb Jotunari'
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


def test_forge_complete_ancestry_creator_roundtrips_homebrew_latex_and_foundry(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed(s);monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s);cid=default_campaign_id(s)
    created=gm.post('/api/v61/foundry/content',json={
        'kind':'homebrew','title':'Jotunari','subtitle':'Children of the old mountains','summary':'Large stone-blooded people.',
        'payload':{
            'homebrew_document':'ancestry','homebrew_publish':True,'library_section':'ancestry','library_group':'Jotunari',
            'description':'Jotunari remember the first mountains.\nTheir clans keep long oral histories.',
            'ancestry_hp':'10','ancestry_size':'lg','ancestry_speed':'25','ancestry_reach':'10','ancestry_vision':'low-light-vision',
            'ancestry_languages':'common, jotun','ancestry_additional_languages':'1','ancestry_traits':'humanoid, jotunari',
            'ancestry_boosts':'Strength, Constitution','ancestry_free_boosts':'1','ancestry_flaws':'Dexterity',
            'heritages':[
                {'title':'Tomb Jotunari','rarity':'common','traits':'jotunari','description':'Your body carries funerary stone.'},
                {'title':'Flame Jotunari','rarity':'uncommon','traits':'jotunari, fire','description':'An ember burns inside you.'},
            ],
            'bundle_feats':[
                {'title':'Colossal Resilience','level':'1','traits':'jotunari, ancestry','access':'Jotunari of the Tomb Clans','prerequisites':'Tomb Jotunari','frequency':'once per day','trigger':'You would take physical damage','requirements':'You are conscious','special':'Tomb Jotunari reduce the initial damage.','description':'Brace for impact.'},
                {'title':'Long Limbs','level':'13','traits':'jotunari, ancestry','description':'Your reach grows.'},
            ],
        }
    })
    assert created.status_code==200,created.text;eid=created.json()['id']
    landing=gm.get('/homebrew');assert landing.status_code==200
    assert 'Jotunari' in landing.text and '2 heritages' in landing.text and '2 feats' in landing.text
    assert 'LEVEL 0' not in landing.text
    detail=gm.get(f'/homebrew/entry/{eid}');assert detail.status_code==200
    for needle in ('Children of the old mountains','Reach','10 ft','Tomb Jotunari','Flame Jotunari','Colossal Resilience','Access','Jotunari of the Tomb Clans','Prerequisites','once per day','You would take physical damage','Tomb Jotunari reduce the initial damage.'):
        assert needle in detail.text

    latex=gm.get(f'/api/homebrew/{eid}/latex');assert latex.status_code==200
    snippet=latex.json()['snippet']
    assert r'\section{Jotunari}' in snippet and r'\subsection{Ancestry Statistics}' in snippet
    assert r'\textbf{Additional Languages:} 1' in snippet and r'\textbf{Traits:} humanoid, jotunari' in snippet
    assert r'\subsection{Heritages}' in snippet and r'\subsubsection{Tomb Jotunari}' in snippet
    assert r'\feat{Colossal Resilience}{1}' in snippet and r'\textbf{Access:} Jotunari of the Tomb Clans' in snippet and r'\textbf{Frequency:} once per day' in snippet

    pushed=gm.post(f'/api/v61/foundry/content/{eid}/push',json={'target_type':'world'});assert pushed.status_code==200,pushed.text
    commands=claim_foundry_commands(s,cid,integration_config(s,cid,include_secret=True)['foundry_bridge_token'])
    command=next(c for c in commands if c['id']==pushed.json()['command']['id'])
    assert command['command_type']=='push_ancestry_bundle'
    assert command['payload']['ancestry']['hp']==10 and command['payload']['ancestry']['reach']==10
    assert command['payload']['ancestry']['traits']=='humanoid, jotunari'
    assert len(command['payload']['heritages'])==2 and len(command['payload']['rules'])==2


def test_forge_complete_archetype_creator_roundtrips_homebrew_latex_and_foundry(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed(s);monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s);cid=default_campaign_id(s)
    created=gm.post('/api/v61/foundry/content',json={
        'kind':'homebrew','title':'Stonebound','summary':'An archetype for characters who borrow the endurance of mountains.',
        'payload':{
            'homebrew_document':'archetype','homebrew_publish':True,'library_section':'archetype','library_group':'Stonebound',
            'description':'Stonebound initiates learn to turn flesh toward living stone.','archetype_access':'You have survived a sacred burial rite.','archetype_traits':'archetype, uncommon',
            'dedication_title':'Stonebound Dedication','dedication_level':'2','dedication_action_cost':'','dedication_traits':'archetype, dedication',
            'dedication_prerequisites':'Constitution +2','dedication_special':'You cannot select another dedication feat until you have gained two other Stonebound feats.',
            'dedication_description':'Your skin hardens and you gain the Stonebound training.',
            'bundle_feats':[
                {'title':'Granite Guard','level':'4','traits':'archetype','action_cost':'reaction','trigger':'You are hit by a Strike','frequency':'once per hour','description':'Harden your body against the blow.'},
                {'title':'Walking Mountain','level':'8','traits':'archetype','description':'You become difficult to move.'},
            ],
        }
    })
    assert created.status_code==200,created.text;eid=created.json()['id']
    landing=gm.get('/homebrew');assert landing.status_code==200 and 'Archetypes' in landing.text and 'Stonebound' in landing.text and 'Dedication 2' in landing.text
    detail=gm.get(f'/homebrew/entry/{eid}');assert detail.status_code==200
    for needle in ('ACCESS','sacred burial rite','Stonebound Dedication','Constitution +2','Granite Guard','once per hour','Walking Mountain'):
        assert needle in detail.text

    snippet=gm.get(f'/api/homebrew/{eid}/latex').json()['snippet']
    assert r'\section{Stonebound}' in snippet and r'\textbf{Traits:} archetype, uncommon' in snippet
    assert r'\textbf{Access:} You have survived a sacred burial rite.' in snippet
    assert r'\subsection{Dedication}' in snippet and r'\feat{Stonebound Dedication}{2}' in snippet
    assert r'\feat{Granite Guard}{4}' in snippet and r'\textbf{Trigger:} You are hit by a Strike' in snippet

    pushed=gm.post(f'/api/v61/foundry/content/{eid}/push',json={'target_type':'world'});assert pushed.status_code==200,pushed.text
    commands=claim_foundry_commands(s,cid,integration_config(s,cid,include_secret=True)['foundry_bridge_token'])
    command=next(c for c in commands if c['id']==pushed.json()['command']['id'])
    assert command['command_type']=='push_homebrew_rule_bundle'
    assert command['payload']['section']=='archetype' and command['payload']['access'].startswith('You have survived')
    assert [r['title'] for r in command['payload']['rules']]==['Stonebound Dedication','Granite Guard','Walking Mountain']
    assert command['payload']['rules'][0]['is_dedication'] is True


def test_forge_bundle_draft_and_creator_controls_exist(tmp_path: Path, monkeypatch):
    import app.main as main
    from app.storage import create_player_invite
    from app.campaigns import set_campaign_members
    s=setup(tmp_path);seed(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s);cid=default_campaign_id(s)
    draft=gm.post('/api/v61/foundry/content',json={'kind':'homebrew','title':'Work in Progress Ancestry','payload':{'homebrew_document':'ancestry','homebrew_publish':False,'ancestry_hp':'8','heritages':[],'bundle_feats':[]}})
    assert draft.status_code==200
    assert 'Work in Progress Ancestry' in gm.get('/homebrew').text
    inv=create_player_invite(s,'Reader');set_campaign_members(s,cid,[inv['id']]);player=TestClient(main.app);player.get(inv['invite_path'],follow_redirects=False)
    assert 'Work in Progress Ancestry' not in player.get('/homebrew').text

    workshop=gm.get('/gm/foundry-workshop');assert workshop.status_code==200
    html=workshop.text
    for needle in ('data-fw-kind="ancestry"','data-fw-kind="archetype"','name="ancestry_hp"','data-fw-heritages','name="dedication_title"','data-fw-bundle-feats','data-fw-template="ancestry-standard"','data-fw-template="archetype-standard"'):
        assert needle in html


def test_source_ancestry_uses_chapter_title_reads_chassis_and_keeps_actions_inline(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    (s.project_dir/'chapters').mkdir()
    source=s.project_dir/'chapters/jotunari.tex'
    source.write_text(r'''\chapter{Jotunari}
\section{Origins}
The Jotunari remember the first mountain.

\begin{multicols}{2}
\textbf{Hitpoints:} 8

\textbf{Size:} Medium

\textbf{Speed:} 25 feet

\textbf{Ability Boosts:} Charisma, Strength, Free

\textbf{Ability Flaw:} Wisdom

\textbf{Languages:} Draconic, Common plus additional languages equal to your Intelligence modifier (if it's positive).
\end{multicols}

\action{Stone Roar}{\actionTwo}{auditory, jotunari}{%
\textbf{Frequency:} once per day\\
\textbf{Requirements:} You are standing on stone.\\
You unleash a roar that shakes the mountain.
}

\section{Jotunari Heritages}
Choose a lineage.
\subsection{Tomb Jotunari}
\textbf{Traits:} jotunari, uncommon\\
Your body carries funerary stone.

\section{Jotunari Feats}
\subsection{1st Level}
\feat{Stone Memory}{1}{jotunari, ancestry}{%
\textbf{Prerequisites:} Tomb Jotunari\\
Remember the voice of the mountain.
}
''',encoding='utf-8')
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}\begin{document}\input{chapters/jotunari}\end{document}''',encoding='utf-8')
    build_wiki(s);gm=gm_client(main,s);cid=default_campaign_id(s)
    assert gm.put('/api/admin/file/homebrew',json={'path':'chapters/jotunari.tex','kind':'ancestry'}).status_code==200

    pages=gm.get('/api/admin/codex').json()['pages']
    source_pages=[p for p in pages if p.get('source_file')=='chapters/jotunari.tex']
    assert source_pages
    assert {p.get('homebrew_owner_title') for p in source_pages}=={'Jotunari'}
    owner=source_pages[0]['homebrew_owner_slug']

    detail=gm.get(f'/homebrew/source/{owner}')
    assert detail.status_code==200
    text=detail.text
    assert '<h1>Jotunari</h1>' in text
    assert 'Hit Points' in text and '>8<' in text and 'Medium' in text and '25 feet' in text
    assert 'Charisma, Strength, Free' in text and 'Wisdom' in text
    assert 'Tomb Jotunari' in text and 'Your body carries funerary stone.' in text
    assert text.count('<h3 id="stone-roar">Stone Roar')==1
    assert text.index('Stone Roar') < text.index('Ancestry feats')
    assert 'homebrew-rule-meta' in text
    assert text.index('Requirements') < text.index('You unleash a roar that shakes the mountain.')
    assert text.index('You unleash a roar that shakes the mountain.') < text.index('Ancestry feats')

    pushed=gm.post(f'/api/homebrew/source/{owner}/foundry')
    assert pushed.status_code==200,pushed.text
    commands=claim_foundry_commands(s,cid,integration_config(s,cid,include_secret=True)['foundry_bridge_token'])
    command=next(c for c in commands if c['id']==pushed.json()['command']['id'])
    payload=command['payload']
    assert payload['title']=='Jotunari'
    assert payload['ancestry']['hp']==8 and payload['ancestry']['size']=='med' and payload['ancestry']['speed']==25
    assert payload['ancestry']['boosts']=='Charisma, Strength' and payload['ancestry']['free_boosts']==1 and payload['ancestry']['flaws']=='Wisdom'
    assert len(payload['heritages'])==1 and payload['heritages'][0]['title']=='Tomb Jotunari'
    assert {r['title'] for r in payload['rules']}=={'Stone Roar','Stone Memory'}
    action=next(r for r in payload['rules'] if r['title']=='Stone Roar')
    assert action['frequency']=='once per day' and action['requirements']=='You are standing on stone.'
    assert 'Frequency' not in action['description_html'] and 'Requirements' not in action['description_html']


def test_homebrew_library_has_heritage_and_pf2e_feat_indexes(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed(s);monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s)
    ancestry=gm.post('/api/v61/foundry/content',json={
        'kind':'homebrew','title':'Cloudkin','summary':'People of the high valleys.',
        'payload':{
            'homebrew_document':'ancestry','homebrew_publish':True,'library_section':'ancestry','library_group':'Cloudkin',
            'description':'Cloudkin live above the storms.','ancestry_hp':'8','ancestry_size':'med','ancestry_speed':'25',
            'heritages':[{'title':'Skyborn Cloudkin','traits':'cloudkin, air','description':'Thin air feels like home.'}],
            'bundle_feats':[{'title':'Ride the Gale','level':1,'traits':'cloudkin, ancestry','description':'Move with the wind.'}],
        }
    })
    assert ancestry.status_code==200,ancestry.text
    skill=gm.post('/api/v61/foundry/content',json={
        'kind':'feat','title':'Impossible Appraisal','summary':'Read value at a glance.',
        'payload':{'homebrew_publish':True,'library_section':'general','library_group':'General Feats','feat_category':'skill','level':2,'traits':'skill, general','description':'Appraise an object instantly.'}
    })
    assert skill.status_code==200,skill.text
    bonus=gm.post('/api/v61/foundry/content',json={
        'kind':'feat','title':'Unsorted Gift','summary':'A deliberately uncategorized boon.',
        'payload':{'homebrew_publish':True,'library_section':'general','library_group':'Miscellaneous','feat_category':'bonus','level':0,'traits':'fortune','description':'Gain a strange boon.'}
    })
    assert bonus.status_code==200,bonus.text

    page=gm.get('/homebrew');assert page.status_code==200
    html=page.text
    assert 'data-section="heritages"' in html and 'data-section="feats"' in html
    assert 'data-homebrew-section="heritages" data-homebrew-index="true" hidden' in html
    assert 'Skyborn Cloudkin' in html and 'Cloudkin' in html
    assert 'data-feat-category="general"' in html and 'data-feat-category="skill"' in html and 'data-feat-category="other"' in html
    assert 'Impossible Appraisal' in html and 'data-feat-category-card="skill"' in html
    # Existing PF2e/Foundry "bonus" feats are intentionally collected under
    # the human-facing Other filter instead of disappearing from the library.
    assert 'Unsorted Gift' in html and 'data-feat-category-card="other"' in html


def test_foundry_token_rotation_endpoint_is_atomic_and_does_not_500(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed(s);monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s);cid=default_campaign_id(s)
    before=integration_config(s,cid,include_secret=True)
    rotated=gm.post('/api/v6/integrations/rotate/foundry',json={})
    assert rotated.status_code==200,rotated.text
    after=rotated.json()
    assert after['rotated']=='foundry'
    assert after['foundry_bridge_token']!=before['foundry_bridge_token']
    assert after['calendar_token']==before['calendar_token']
    assert after['display_token']==before['display_token']


def test_source_ancestry_can_open_in_forge_and_insert_new_feat_into_matching_level(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    (s.project_dir/'chapters').mkdir()
    source=s.project_dir/'chapters/jotunari.tex'
    source.write_text(r'''\chapter{Jotunari}
\section{Origins}
Stone-born giantkin.

\begin{multicols}{2}
\textbf{Hitpoints:} 8

\textbf{Size:} Medium

\textbf{Speed:} 25 feet
\end{multicols}

\section{Jotunari Heritages}
\subsection{Tomb Jotunari}
Your body carries funerary stone.

\section{Jotunari Feats}
\subsection{1st Level}
\feat{Stone Memory}{1}{jotunari, ancestry}{%
Remember the mountain.
}
\subsection{5th Level}
\feat{Giant Step}{5}{jotunari, ancestry}{%
Stride far.
}

\section{Culture}
The old songs endure.
''',encoding='utf-8')
    (s.project_dir/'main.tex').write_text(r'\documentclass{book}\begin{document}\input{chapters/jotunari}\end{document}',encoding='utf-8')
    build_wiki(s);gm=gm_client(main,s)
    marked=gm.put('/api/admin/file/homebrew',json={'path':'chapters/jotunari.tex','kind':'ancestry'})
    assert marked.status_code==200,marked.text
    pages=gm.get('/api/admin/codex').json()['pages'];owner=next(p['homebrew_owner_slug'] for p in pages if p.get('source_file')=='chapters/jotunari.tex')

    opened=gm.post(f'/api/homebrew/source/{owner}/forge');assert opened.status_code==200,opened.text
    entry=opened.json()['entry'];assert entry['payload']['source_linked'] is True
    assert entry['payload']['source_link_path']=='chapters/jotunari.tex'
    assert {x['title'] for x in entry['payload']['bundle_feats']}=={'Stone Memory','Giant Step'}
    assert entry['payload']['heritages'][0]['title']=='Tomb Jotunari'

    edited=dict(entry);edited['payload']=dict(entry['payload'])
    edited['payload']['bundle_feats']=[dict(x) for x in entry['payload']['bundle_feats']]+[{
        'kind':'feat','title':'Sky Titan','level':'17','traits':'jotunari, ancestry',
        'requirements':'You are outdoors.','frequency':'once per day','description':'Become as vast as a storm cloud.'
    }]
    saved=gm.post('/api/v61/foundry/content',json=edited);assert saved.status_code==200,saved.text
    saved_row=saved.json();assert saved_row['source_sync']['changed'] is True
    text=source.read_text(encoding='utf-8')
    assert r'\subsection{17th Level}' in text and r'\feat{Sky Titan}{17}' in text
    assert text.index(r'\subsection{17th Level}') < text.index(r'\section{Culture}')
    assert text.count('Sky Titan')==1
    assert r'\textbf{Requirements:} You are outdoors.\\' in text
    assert r'\textbf{Frequency:} once per day\\' in text

    # The source stays authoritative: saving the returned Forge row again must
    # update the same source rule, not create a second Homebrew entry or feat.
    saved_again=gm.post('/api/v61/foundry/content',json=saved_row);assert saved_again.status_code==200,saved_again.text
    assert source.read_text(encoding='utf-8').count('Sky Titan')==1
    rebuilt=gm.get(f'/homebrew/source/{owner}');assert rebuilt.status_code==200
    assert 'Sky Titan' in rebuilt.text and 'LEVEL 17' in rebuilt.text.upper()
    reopened=gm.post(f'/api/homebrew/source/{owner}/forge');assert reopened.status_code==200
    assert reopened.json()['entry']['id']==entry['id']


def test_mobile_more_sheet_has_internal_scroller_and_mobile_gm_switcher_is_suppressed(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed(s);monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s)
    page=gm.get('/');assert page.status_code==200
    assert 'class="mobile-sheet-scroll" data-mobile-sheet-scroll' in page.text
    assert page.text.count('class="mobile-tabbar"')==1
    css=(Path(__file__).parents[1]/'static/wiki.css').read_text(encoding='utf-8')
    js=(Path(__file__).parents[1]/'static/wiki.js').read_text(encoding='utf-8')
    assert '.gm-view-switcher{display:none!important}' in css
    assert '.mobile-sheet-scroll{' in css and 'overflow-y:auto' in css
    assert "document.body.classList.toggle('mobile-more-open',active)" in js
