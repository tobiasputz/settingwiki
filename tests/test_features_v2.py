from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.features import (
    add_annotation,
    add_mystery_pin,
    add_session_update,
    create_snapshot,
    fog_regions,
    get_live_session,
    init_feature_db,
    list_annotations,
    list_handouts,
    list_mysteries,
    list_sessions,
    list_timeline,
    map_layers,
    recent_updates,
    restore_snapshot,
    save_fog_region,
    save_handout,
    save_map_layer,
    save_mystery,
    save_mystery_edge,
    delete_mystery_edge,
    delete_mystery_pin,
    save_relationship,
    save_session,
    save_timeline_event,
    set_reveal,
    set_session_lore,
    travel_between_markers,
    apply_reveals_to_html,
)
from app.latex import build_wiki
from app.maps import create_map
from app.storage import connect, init_db, set_setting


def make_settings(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=make_settings(tmp_path); init_db(s); init_feature_db(s); return s


def test_session_update_audiences_are_isolated(tmp_path: Path):
    s=setup(tmp_path)
    sess=save_session(s,{"title":"Tonight","status":"live"})
    add_session_update(s,{"session_id":sess["id"],"title":"Everyone","body":"Public discovery"})
    add_session_update(s,{"session_id":sess["id"],"title":"Only A","body":"Secret discovery","audience":[11]})
    assert [x["title"] for x in recent_updates(s,11)] == ["Only A","Everyone"]
    assert [x["title"] for x in recent_updates(s,12)] == ["Everyone"]
    assert [x["title"] for x in recent_updates(s,None,admin=True)] == ["Only A","Everyone"]
    assert [x["title"] for x in get_live_session(s,invite_id=12)["updates"]] == ["Everyone"]
    assert len(list_sessions(s,public=True,invite_id=11)[0]["updates"]) == 2


def test_existing_feature_db_gets_audience_migration(tmp_path: Path):
    s=make_settings(tmp_path); init_db(s)
    with connect(s) as conn:
        conn.execute("CREATE TABLE session_updates (id INTEGER PRIMARY KEY, session_id INTEGER, title TEXT, body TEXT, target_type TEXT, target_key TEXT, visibility TEXT, created_at REAL)")
    init_feature_db(s)
    with connect(s) as conn:
        columns={r[1] for r in conn.execute("PRAGMA table_info(session_updates)").fetchall()}
    assert "audience_json" in columns


def test_progressive_lore_truth_never_reaches_wrong_audience(tmp_path: Path):
    s=setup(tmp_path)
    html='<section class="lore-reveal" data-lore-reveal="identity" data-rumor="Old rumor"><b>THE TRUE NAME</b></section>'
    set_reveal(s,{"target_type":"block","target_key":"hero:identity","state":"rumor","rumor_text":"A whispered rumor","audience":[7]})
    allowed=apply_reveals_to_html(s,html,"hero",invite_id=7)
    denied=apply_reveals_to_html(s,html,"hero",invite_id=8)
    assert "A whispered rumor" in allowed and "THE TRUE NAME" not in allowed
    assert "THE TRUE NAME" not in denied and "A whispered rumor" not in denied
    set_reveal(s,{"target_type":"block","target_key":"hero:identity","state":"discovered","audience":[7]})
    assert "THE TRUE NAME" in apply_reveals_to_html(s,html,"hero",invite_id=7)
    assert "THE TRUE NAME" not in apply_reveals_to_html(s,html,"hero",invite_id=8)


def test_annotation_privacy(tmp_path: Path):
    s=setup(tmp_path)
    add_annotation(s,{"page_slug":"hero","note":"mine","visibility":"private"},invite_id=1,author_label="A")
    add_annotation(s,{"page_slug":"hero","note":"party","visibility":"party"},invite_id=1,author_label="A")
    add_annotation(s,{"page_slug":"hero","note":"gm","visibility":"gm"},invite_id=None,author_label="GM",admin=True)
    assert {x["note"] for x in list_annotations(s,"hero",invite_id=1)} == {"mine","party"}
    assert {x["note"] for x in list_annotations(s,"hero",invite_id=2)} == {"party"}
    assert {x["note"] for x in list_annotations(s,"hero",admin=True)} == {"mine","party","gm"}


def test_timeline_handouts_layers_fog_and_travel(tmp_path: Path):
    s=setup(tmp_path)
    save_timeline_event(s,{"title":"Known","visibility":"players","sort_key":1})
    save_timeline_event(s,{"title":"Secret","visibility":"gm","sort_key":2})
    assert [x["title"] for x in list_timeline(s)] == ["Known"]
    assert {x["title"] for x in list_timeline(s,admin=True)} == {"Known","Secret"}
    save_handout(s,{"title":"Fresh","expires_at":time.time()+100})
    save_handout(s,{"title":"Expired","expires_at":time.time()-1})
    assert [x["title"] for x in list_handouts(s)] == ["Fresh"]
    assert {x["title"] for x in list_handouts(s,admin=True)} == {"Fresh","Expired"}
    map_id=create_map(s,"World","maps/world.webp")["id"]
    save_map_layer(s,map_id,{"name":"Public","enabled":True,"visible_to_players":True})
    save_map_layer(s,map_id,{"name":"GM","enabled":True,"visible_to_players":False})
    save_map_layer(s,map_id,{"name":"Disabled","enabled":False,"visible_to_players":True})
    assert {x["name"] for x in map_layers(s,map_id)} == {"Public","GM","Disabled"}
    assert [x["name"] for x in map_layers(s,map_id,public=True)] == ["Public"]
    save_fog_region(s,map_id,{"title":"Unknown","points":[[0,0],[1,0],[1,1]],"revealed":False})
    save_fog_region(s,map_id,{"title":"Known","points":[[0,0],[.5,0],[.5,.5]],"revealed":True})
    assert [x["title"] for x in fog_regions(s,map_id,public=True)] == ["Unknown"]
    travel=travel_between_markers({"x":0,"y":0},{"x":.3,"y":.4},1000,50)
    assert travel["distance"] == 500.0 and travel["days"] == 10.0


def test_snapshot_roundtrip_restores_source(tmp_path: Path):
    s=setup(tmp_path)
    source=s.project_dir/'main.tex'; source.write_text('before',encoding='utf-8')
    snap=create_snapshot(s,'Before session')
    source.write_text('after',encoding='utf-8')
    restore_snapshot(s,snap['path'])
    assert source.read_text(encoding='utf-8') == 'before'


def test_spoiler_safe_visible_wiki_removes_hidden_relationship(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path); set_setting(s,'player_access_mode','public')
    (s.project_dir/'main.tex').write_text('\\documentclass{book}\n\\begin{document}\n\\chapter{World}\n\\section{Known}\nKnown text.\n\\section{Secret}\nSecret text.\n\\end{document}\n',encoding='utf-8')
    wiki=build_wiki(s)
    known=next(p for p in wiki['pages'] if p['title']=='Known'); secret=next(p for p in wiki['pages'] if p['title']=='Secret')
    save_relationship(s,{"source_slug":known['slug'],"target_slug":secret['slug'],"relation":"knows","visibility":"players"})
    set_reveal(s,{"target_type":"page","target_key":secret['slug'],"state":"hidden"})
    monkeypatch.setattr(main,'settings',s)
    class Req:
        session={}
    visible=main._visible_wiki(Req())
    kp=next(p for p in visible['pages'] if p['slug']==known['slug'])
    assert secret['slug'] not in {p['slug'] for p in visible['pages']}
    assert kp['explicit_relationships'] == []


def test_v2_player_routes_pwa_and_mobile_shell(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path); set_setting(s,'player_access_mode','public')
    (s.project_dir/'main.tex').write_text('\\documentclass{book}\n\\begin{document}\n\\chapter{World}\n\\section{Welcome}\nHello.\n\\end{document}\n',encoding='utf-8')
    build_wiki(s); monkeypatch.setattr(main,'settings',s)
    client=TestClient(main.app)
    for path in ['/', '/session','/timeline','/calendar','/updates','/mysteries','/handouts','/network']:
        assert client.get(path).status_code == 200, path
    manifest=client.get('/manifest.webmanifest')
    assert manifest.status_code==200 and manifest.json()['display']=='standalone'
    sw=(Path(__file__).resolve().parents[1]/'static'/'sw.js').read_text(encoding='utf-8')
    assert 'loreforge-private' in sw and '/project-asset/' in sw and 'CLEAR_PRIVATE' in sw
    base=(Path(__file__).resolve().parents[1]/'templates'/'base.html').read_text(encoding='utf-8')
    admin_css=(Path(__file__).resolve().parents[1]/'static'/'admin.css').read_text(encoding='utf-8')
    admin_js=(Path(__file__).resolve().parents[1]/'static'/'admin.js').read_text(encoding='utf-8')
    assert 'apple-mobile-web-app-capable' in base and 'mobile-tabbar' in base
    assert '.admin-topbar{position:sticky' in admin_css
    assert 'data-mobile-editor-pane' in admin_js and "qp.get('search')" in admin_js


def test_mystery_connections_render_and_do_not_leak_hidden_clues(tmp_path: Path):
    s=setup(tmp_path)
    board=save_mystery(s,{"title":"The Broken Crown","visibility":"players"})
    public_a=add_mystery_pin(s,board["id"],{"label":"Ash on the seal","x":.2,"y":.3,"visibility":"players"})
    public_b=add_mystery_pin(s,board["id"],{"label":"Missing courier","x":.8,"y":.7,"visibility":"players"})
    secret=add_mystery_pin(s,board["id"],{"label":"GM culprit","x":.5,"y":.5,"visibility":"gm"})
    edge=save_mystery_edge(s,board["id"],{"source_pin":public_a["id"],"target_pin":public_b["id"],"label":"same route","visibility":"players"})
    save_mystery_edge(s,board["id"],{"source_pin":public_a["id"],"target_pin":secret["id"],"label":"secret link","visibility":"players"})
    player=list_mysteries(s)[0]
    assert {p["label"] for p in player["pins"]}=={"Ash on the seal","Missing courier"}
    assert [e["label"] for e in player["edges"]]==["same route"]
    assert player["edges"][0]["source_x"]==.2 and player["edges"][0]["target_y"]==.7
    admin=list_mysteries(s,admin=True)[0]
    assert len(admin["edges"])==2
    delete_mystery_edge(s,edge["id"])
    assert [e["label"] for e in list_mysteries(s)[0]["edges"]]==[]
    delete_mystery_pin(s,secret["id"])
    assert all(p["label"]!="GM culprit" for p in list_mysteries(s,admin=True)[0]["pins"])


def test_editor_reveal_composer_and_player_mystery_strings_are_shipped():
    root=Path(__file__).resolve().parents[1]
    admin_html=(root/'templates'/'admin.html').read_text(encoding='utf-8')
    admin_js=(root/'static'/'admin.js').read_text(encoding='utf-8')
    mysteries=(root/'templates'/'mysteries.html').read_text(encoding='utf-8')
    assert 'insertRevealBtn' in admin_html
    assert 'function showRevealPanel' in admin_js and 'loreforge-reveal-start' in admin_js
    assert 'mystery-strings' in mysteries and 'edge.source_x' in mysteries


def test_history_eras_and_historical_filter(tmp_path: Path):
    from app.features import save_timeline_era, list_timeline_eras
    s=setup(tmp_path)
    era=save_timeline_era(s,{"name":"Age of Ash","start_label":"-900","end_label":"-310","start_sort":-900,"end_sort":-310,"summary":"The old empires burned."})
    save_timeline_event(s,{"title":"The Ashfall","kind":"catastrophe","date_label":"-842","sort_key":-842,"era_id":era["id"],"significance":5,"certainty":"legend"})
    save_timeline_event(s,{"title":"Session 12","kind":"session","date_label":"Today","sort_key":999})
    assert [x["name"] for x in list_timeline_eras(s)]==["Age of Ash"]
    history=list_timeline(s,historical_only=True)
    assert [x["title"] for x in history]==["The Ashfall"]
    assert history[0]["era_name"]=="Age of Ash" and history[0]["significance"]==5


def test_player_character_ownership_privacy_and_multiple_characters(tmp_path: Path):
    from app.features import list_player_characters, save_player_character, add_character_image, get_player_character
    from app.storage import create_player_invite
    s=setup(tmp_path)
    a=create_player_invite(s,"Alice"); b=create_player_invite(s,"Bob")
    hero=save_player_character(s,{"name":"Mira","ancestry":"Elf","class_name":"Wizard","visibility":"party"},invite_id=a["id"])
    secret=save_player_character(s,{"name":"The Mask","visibility":"private"},invite_id=a["id"])
    alt=save_player_character(s,{"name":"Old Mira","status":"retired","visibility":"party"},invite_id=a["id"])
    save_player_character(s,{"name":"Borin","visibility":"party"},invite_id=b["id"])
    mine={x["name"] for x in list_player_characters(s,invite_id=a["id"])}
    theirs={x["name"] for x in list_player_characters(s,invite_id=b["id"])}
    assert {"Mira","The Mask","Old Mira","Borin"} <= mine
    assert "The Mask" not in theirs and {"Mira","Old Mira","Borin"} <= theirs
    assert get_player_character(s,secret["id"],invite_id=b["id"]) is None
    img=add_character_image(s,hero["id"],f"characters/{a['id']}/{hero['id']}/portrait.webp","portrait","Reference",invite_id=a["id"])
    updated=get_player_character(s,hero["id"],invite_id=a["id"])
    assert updated["portrait_path"].endswith("portrait.webp") and img["kind"]=="portrait"
    assert len([x for x in list_player_characters(s,invite_id=a["id"]) if x["invite_id"]==a["id"]])==3


def test_v21_network_history_characters_and_tablet_ui_are_shipped(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path); set_setting(s,'player_access_mode','public')
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}
\newcommand{\pon}[1]{\section*{#1}}
\begin{document}
\chapter{World}
\pon{Tumerich Tumadum}
Tumerich knows \wiki{Selenia}{Selenia}.
\section{Selenia}
A city.
\end{document}
''',encoding='utf-8')
    build_wiki(s); monkeypatch.setattr(main,'settings',s)
    client=TestClient(main.app)
    assert client.get('/network').status_code==200
    assert client.get('/timeline').status_code==200
    assert client.get('/characters').status_code==200
    network_js=(Path(__file__).resolve().parents[1]/'static'/'network.js').read_text(encoding='utf-8')
    admin_css=(Path(__file__).resolve().parents[1]/'static'/'admin.css').read_text(encoding='utf-8')
    admin_js=(Path(__file__).resolve().parents[1]/'static'/'admin.js').read_text(encoding='utf-8')
    base=(Path(__file__).resolve().parents[1]/'templates'/'base.html').read_text(encoding='utf-8')
    campaign=(Path(__file__).resolve().parents[1]/'templates'/'campaign_admin.html').read_text(encoding='utf-8')
    assert 'function storyEdges' in network_js and 'pointers=new Map()' in network_js
    assert '@media(max-width:1180px)' in admin_css and 'admin-mode-dock' in admin_css
    assert 'editorTabStrip' in (Path(__file__).resolve().parents[1]/'templates'/'admin.html').read_text(encoding='utf-8')
    assert 'tabs:[]' in admin_js and '/characters' in base
    assert 'History Builder' in campaign and 'World Builder' in campaign and 'cc-party' in campaign


def test_private_character_assets_and_search_follow_invite_visibility(tmp_path: Path, monkeypatch):
    import app.main as main
    from app.features import save_player_character, add_character_image
    from app.storage import create_player_invite, set_setting
    s=setup(tmp_path); set_setting(s,'player_access_mode','invite')
    (s.project_dir/'main.tex').write_text('\\documentclass{book}\n\\begin{document}\n\\chapter{World}\n\\section{Welcome}\nHello.\n\\end{document}\n',encoding='utf-8')
    build_wiki(s)
    a=create_player_invite(s,'Alice'); b=create_player_invite(s,'Bob')
    secret=save_player_character(s,{"name":"Night Mask","visibility":"private","summary":"Secret alter ego"},invite_id=a['id'])
    rel=f"characters/{a['id']}/{secret['id']}/mask.webp"; asset=s.uploads_dir/rel; asset.parent.mkdir(parents=True,exist_ok=True); asset.write_bytes(b'fake-webp')
    add_character_image(s,secret['id'],rel,'portrait','Mask',invite_id=a['id'])
    monkeypatch.setattr(main,'settings',s)
    ca=TestClient(main.app); cb=TestClient(main.app)
    assert ca.get(a['invite_path']).status_code==200
    assert cb.get(b['invite_path']).status_code==200
    assert ca.get('/uploads/'+rel).status_code==200
    assert cb.get('/uploads/'+rel).status_code==404
    assert any(x['title']=='Night Mask' for x in ca.get('/api/public/search?q=Night').json())
    assert all(x['title']!='Night Mask' for x in cb.get('/api/public/search?q=Night').json())


def test_world_builder_can_create_and_wire_real_latex_entry(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path)
    (s.project_dir/'main.tex').write_text('\\documentclass{book}\n\\begin{document}\n\\chapter{World}\n\\section{Welcome}\nHello.\n\\end{document}\n',encoding='utf-8')
    build_wiki(s); monkeypatch.setattr(main,'settings',s)
    client=TestClient(main.app); assert client.post('/admin/login',data={'password':'admin'}).status_code==200
    r=client.post('/api/admin/entry-template/create',json={'kind':'settlement','title':'Glass Harbor'})
    assert r.status_code==200, r.text
    d=r.json(); assert d['path'].startswith('Worldbuilding/Places/') and d['path'].endswith('.tex')
    assert (s.project_dir/d['path']).exists()
    main_text=(s.project_dir/'main.tex').read_text(encoding='utf-8')
    assert '\\include{'+Path(d['path']).with_suffix('').as_posix()+'}' in main_text
    assert d['edit_url'].startswith('/admin?file=')
