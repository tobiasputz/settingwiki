from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.storage import init_db, create_player_invite, set_setting, connect
from app.features import init_feature_db, save_player_character, save_session
from app.campaigns import default_campaign_id
from app.latex import build_wiki
from app.living import create_notification, list_notifications
from app.v51 import (
    list_scenes, save_scenes, list_clues, save_clue, list_npc_cards, save_npc_card,
    delete_npc_card, list_events, add_event, list_consequences, save_consequence,
    list_clocks, save_clock, list_templates, list_random_tables, prep_workspace,
)


def settings_for(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=settings_for(tmp_path);init_db(s);init_feature_db(s);return s


def seed_wiki(s: Settings) -> None:
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}
\begin{document}\chapter{People}\section{Corvina}A courier with more secrets than luggage.\section{Old Keep}An old keep above the road.\end{document}''',encoding='utf-8')
    build_wiki(s)


def test_v51_schema_is_created_by_feature_init_and_pacing_migrates(tmp_path: Path):
    s=setup(tmp_path)
    with connect(s) as conn:
        tables={r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        prep_cols={r['name'] for r in conn.execute('PRAGMA table_info(session_preparations)')}
    assert {'gm_scene_cards','gm_clues','gm_npc_cards','gm_session_events','gm_consequences','gm_clocks','gm_character_spotlights','gm_prep_templates','gm_random_tables','gm_session_closeouts'} <= tables
    assert 'pacing_json' in prep_cols


def test_v51_gm_resources_roundtrip_and_are_campaign_scoped(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s);sess=save_session(s,{'campaign_id':cid,'title':'Glass Road','status':'planned'})
    scenes=save_scenes(s,cid,sess['id'],[{'title':'At the gate','purpose':'Make them choose','npc_slugs':['corvina'],'status':'ready'}])
    assert scenes[0]['title']=='At the gate' and scenes[0]['npc_slugs']==['corvina']
    clue=save_clue(s,cid,{'title':'Broken seal','body':'The wax is warm.','source_session_id':sess['id']})
    assert list_clues(s,cid)[0]['id']==clue['id']
    npc=save_npc_card(s,cid,{'page_slug':'corvina','voice':'Quiet','knows':'Who opened the gate'})
    assert list_npc_cards(s,cid)[0]['voice']=='Quiet'
    ev=add_event(s,cid,sess['id'],{'body':'The party promised to return.'})
    assert list_events(s,cid,sess['id'])[0]['id']==ev['id']
    consequence=save_consequence(s,cid,{'title':'The courier leaves','trigger_kind':'next_session','trigger_value':'If ignored'})
    assert list_consequences(s,cid)[0]['id']==consequence['id']
    clock=save_clock(s,cid,{'title':'The siege begins','current_segments':2,'total_segments':6,'visibility':'player'})
    assert list_clocks(s,cid)[0]['visibility']=='player' and clock['current_segments']==2
    assert any(t.get('builtin') for t in list_templates(s,cid))
    assert any(t.get('builtin') for t in list_random_tables(s,cid))
    delete_npc_card(s,cid,'corvina'); assert list_npc_cards(s,cid)==[]


def test_spotlight_and_gm_workspace_are_strictly_gm_only(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    inv=create_player_invite(s,'Alice');cid=default_campaign_id(s);char=save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=inv['id']);sess=save_session(s,{'campaign_id':cid,'title':'Next','status':'planned'})
    player=TestClient(main.app);player.get(inv['invite_path'])
    assert player.get(f'/api/v51/gm/workspace/{sess["id"]}').status_code==401
    assert player.post(f'/api/v51/gm/spotlights/{char["id"]}',json={'session_id':sess['id']}).status_code==401
    # Player-facing templates must never mention the private balancing language.
    root=Path(__file__).resolve().parents[1]
    for name in ['base.html','session.html','character.html','characters.html','recap.html']:
        text=(root/'templates'/name).read_text(encoding='utf-8')
        assert 'SPOTLIGHT BALANCE' not in text
        assert 'no spotlight marker' not in text.lower()
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    page=gm.get('/gm/prep?session_id='+str(sess['id']))
    assert page.status_code==200 and 'SPOTLIGHT BALANCE' in page.text and 'private reminder' in page.text


def test_notification_read_state_persists_and_player_can_dismiss(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    inv=create_player_invite(s,'Alice');cid=default_campaign_id(s);save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=inv['id'])
    note=create_notification(s,{'campaign_id':cid,'title':'New clue','body':'Look at the old keep.'})
    p=TestClient(main.app);p.get(inv['invite_path'])
    assert p.post(f'/api/public/notifications/{note["id"]}/read',json={}).status_code==200
    # Navigate to force a new page/request, then load notifications again.
    assert p.get('/session').status_code==200
    rows=p.get('/api/public/notifications').json(); row=next(x for x in rows if x['id']==note['id']); assert row['read'] is True
    assert p.delete(f'/api/public/notifications/{note["id"]}').status_code==200
    assert all(x['id']!=note['id'] for x in p.get('/api/public/notifications').json())
    # Personal dismissal must not erase the campaign notification itself.
    assert any(x['id']==note['id'] for x in list_notifications(s,None,admin=True,campaign_id=cid))


def test_gm_notification_read_state_uses_stable_owner_identity_and_delete_is_global(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s);cid=default_campaign_id(s)
    note=create_notification(s,{'campaign_id':cid,'title':'GM notice','body':'Persistent.'})
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    assert gm.post(f'/api/public/notifications/{note["id"]}/read',json={}).status_code==200
    assert gm.get('/').status_code==200
    rows=gm.get('/api/public/notifications').json(); assert next(x for x in rows if x['id']==note['id'])['read'] is True
    assert gm.delete(f'/api/public/notifications/{note["id"]}').json()['deleted']=='global'
    assert all(x['id']!=note['id'] for x in list_notifications(s,None,admin=True,campaign_id=cid))


def test_v51_frontend_repairs_and_gm_tools_are_shipped():
    root=Path(__file__).resolve().parents[1]
    prep=(root/'templates/gm_prep.html').read_text(encoding='utf-8')
    prep_js=(root/'static/gm-prep.js').read_text(encoding='utf-8')
    prep_css=(root/'static/admin.css').read_text(encoding='utf-8')
    map_js=(root/'static/map.js').read_text(encoding='utf-8')
    map_tpl=(root/'templates/map.html').read_text(encoding='utf-8')
    char_tpl=(root/'templates/character.html').read_text(encoding='utf-8')
    wiki_css=(root/'static/wiki.css').read_text(encoding='utf-8')
    wiki_js=(root/'static/wiki.js').read_text(encoding='utf-8')
    sw=(root/'static/sw.js').read_text(encoding='utf-8')
    assert 'gm-prep-html' in prep and 'overflow-y:auto!important' in prep_css and 'overflow:visible!important' in prep_css
    for marker in ['SCENE CARDS','PACING STRIP','NPC desk','CONTINUITY CHECK','SPOTLIGHT BALANCE','RANDOM DRAWER','SESSION CLOSEOUT']:
        assert marker in prep
    assert 'Improv mode' in prep and 'data-ref-reveal' in prep_js and '/api/admin/reveals' in prep_js
    assert "image.complete&&image.naturalWidth" in map_js and "stage.addEventListener('click'" in map_js and 'aria-hidden="true" role="dialog"' in map_tpl
    assert 'character-hero-v5' in char_tpl and '.character-page.story-only' in wiki_css and 'Pathbuilder / sheet URL' in char_tpl
    assert 'data-notification-delete' in wiki_js and "method:'DELETE'" in wiki_js
    assert 'seeker-static-v7301' in sw
