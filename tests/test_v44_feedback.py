from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi.testclient import TestClient

from app.campaigns import default_campaign_id, save_campaign
from app.config import Settings
from app.features import get_player_character, init_feature_db, save_player_character
from app.latex import build_wiki
from app.scheduling import init_schedule_db
from app.semantic_search import semantic_search
from app.storage import create_player_invite, init_db, set_setting


def make_settings(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=make_settings(tmp_path);init_db(s);init_feature_db(s);init_schedule_db(s);return s


def seed_wiki(s: Settings) -> None:
    text = """\\documentclass{book}
\\begin{document}
\\chapter{World}
\\section{The Crown of Frost}
King Vael rules the northern realm from a city of white towers.
\\section{Hidden Cellar}
An old wine cellar beneath the inn.
\\end{document}
"""
    (s.project_dir/'main.tex').write_text(text,encoding='utf-8')
    build_wiki(s)


def future(days: int=7) -> str:
    return (dt.date.today()+dt.timedelta(days=days)).isoformat()


def test_availability_stays_global_after_second_campaign_character(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    alice=create_player_invite(s,'Alice');main_id=default_campaign_id(s)
    save_player_character(s,{'name':'Aster','campaign_id':main_id},invite_id=alice['id'])
    player=TestClient(main.app);player.get(alice['invite_path'])
    day=future();assert player.post('/api/schedule/me',json={'changes':[{'date':day,'status':'available'}]}).status_code==200
    second=save_campaign(s,{'name':'Second Campaign','member_ids':[]})
    save_player_character(s,{'name':'Bram','campaign_id':second['id']},invite_id=alice['id'])
    owner=TestClient(main.app);owner.post('/admin/login',data={'password':'admin'})
    a=owner.get('/api/gm/schedule',params={'start':day,'end':day,'campaign_id':main_id})
    b=owner.get('/api/gm/schedule',params={'start':day,'end':day,'campaign_id':second['id']})
    assert a.status_code==b.status_code==200
    assert a.json()['next_all_available']['date']==day
    assert b.json()['next_all_available']['date']==day
    mine=player.get('/api/schedule/me',params={'start':day,'end':day}).json()
    assert len(mine['availability'])==1 and mine['availability'][0]['date']==day and mine['availability'][0]['status']=='available'
    assert {c['name'] for c in mine['campaigns']}=={'Main Campaign','Second Campaign'}


def test_codex_comment_owner_and_gm_can_delete_but_other_player_cannot(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob')
    a=TestClient(main.app);a.get(alice['invite_path']);b=TestClient(main.app);b.get(bob['invite_path'])
    made=a.post('/api/public/annotations',json={'page_slug':'the-crown-of-frost','note':'Remember this','visibility':'party'});assert made.status_code==200
    note_id=made.json()['id']
    assert b.delete(f'/api/public/annotations/{note_id}').status_code==403
    assert a.delete(f'/api/public/annotations/{note_id}').status_code==200
    made=a.post('/api/public/annotations',json={'page_slug':'the-crown-of-frost','note':'GM may remove this','visibility':'party'});note_id=made.json()['id']
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    assert gm.delete(f'/api/public/annotations/{note_id}').status_code==200


def test_gm_can_edit_and_delete_player_character_and_advanced_sheet_roundtrips(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    alice=create_player_invite(s,'Alice');cid=default_campaign_id(s)
    char=save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=alice['id'])
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    sheet={'initiative':'+12','focus_points':'2/3','spell_dc':'27','armor':'Explorer clothing','currency':'42 gp','appearance':'Silver braid','personality':'Restless but kind','bonds':'Owes Corvina a life-debt','attacks':[{'name':'Moon blade','bonus':'+18','note':'2d8 slashing'}],'resources':[{'name':'Panache','value':'1 / 1','note':'Reset after rest'}],'proficiencies':[{'name':'Occultism','rank':'master','note':''}],'display':{'subtitle':'Seeker of the Pale Road','symbol':'☾','secondary_color':'#665588','density':'compact'}}
    edited=gm.put(f"/api/player/characters/{char['id']}",json={'name':'Aster Vale','sheet':sheet,'theme_style':'fey'})
    assert edited.status_code==200
    row=get_player_character(s,char['id'],admin=True,campaign_id=cid)
    assert row['name']=='Aster Vale' and row['theme_style']=='fey'
    assert row['sheet']['attacks'][0]['bonus']=='+18' and row['sheet']['display']['symbol']=='☾'
    # Render both GM and owner views so advanced-sheet Jinja changes are exercised.
    gm_page=gm.get(f"/characters/{char['id']}")
    assert gm_page.status_code==200 and 'Seeker of the Pale Road' in gm_page.text and 'Moon blade' in gm_page.text
    player=TestClient(main.app);player.get(alice['invite_path'])
    player_page=player.get(f"/characters/{char['id']}")
    assert player_page.status_code==200 and 'Aster Vale' in player_page.text and 'Panache' in player_page.text
    assert gm.delete(f"/api/player/characters/{char['id']}").status_code==200
    assert get_player_character(s,char['id'],admin=True,campaign_id=cid) is None


def test_semantic_search_is_integrated_into_player_search_and_ask_seeker(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    monkeypatch.delenv('SEEKER_AI_API_KEY',raising=False);monkeypatch.delenv('LOREFORGE_AI_API_KEY',raising=False)
    monkeypatch.delenv('SEEKER_AI_MODEL',raising=False);monkeypatch.delenv('LOREFORGE_AI_MODEL',raising=False)
    invite=create_player_invite(s,'Searcher');client=TestClient(main.app);client.get(invite['invite_path'])
    results=client.get('/api/public/search',params={'q':'ruler of the northern realm'})
    assert results.status_code==200 and any(x.get('slug')=='the-crown-of-frost' for x in results.json())
    answer=client.post('/api/assistant/query',json={'q':'Who rules the northern realm?','use_ai':True})
    assert answer.status_code==200 and answer.json()['mode']=='semantic'
    assert any(x['slug']=='the-crown-of-frost' for x in answer.json()['sources'])


def test_semantic_search_defensively_skips_hidden_presentations():
    pages=[
        {'slug':'public','title':'Known Gate','chapter':'Places','plain_text':'A public stone gate.','excerpt':'A public gate.'},
        {'slug':'secret','title':'The Black Archive','chapter':'Secrets','plain_text':'The forbidden crown is beneath the observatory.','excerpt':'Hidden.','presentation':{'visibility':'hidden'}},
    ]
    hits=semantic_search(pages,'forbidden crown observatory',limit=5)
    assert all(hit['slug']!='secret' for hit in hits)


def test_local_semantic_search_understands_concepts_without_api():
    pages=[
        {'slug':'vael','title':'Vael','chapter':'People','plain_text':'King Vael holds the crown and commands the northern court.','excerpt':'King of the north.'},
        {'slug':'river','title':'Blue River','chapter':'Geography','plain_text':'A cold river crosses the valley.','excerpt':'A river.'},
    ]
    hits=semantic_search(pages,'the ruler of the northern realm',limit=3)
    assert hits and hits[0]['slug']=='vael'


def test_v44_feedback_ui_assets_are_shipped_and_click_paths_are_resilient():
    root=Path(__file__).resolve().parents[1]
    cc=(root/'static'/'campaign-admin.js').read_text(encoding='utf-8')
    schedule=(root/'static'/'schedule.js').read_text(encoding='utf-8')
    admin=(root/'static'/'admin.js').read_text(encoding='utf-8')
    effects=(root/'static'/'fantasy-map-effects.js').read_text(encoding='utf-8')
    chars=(root/'static'/'characters.js').read_text(encoding='utf-8')
    base=(root/'templates'/'base.html').read_text(encoding='utf-8')
    admin_tpl=(root/'templates'/'admin.html').read_text(encoding='utf-8')
    sw=(root/'static'/'sw.js').read_text(encoding='utf-8')
    assert 'ccRelationshipSearch' in cc and 'relationshipLimit=36' in cc and "closest?.('#ccNewRelationship')" in cc
    assert 'lastTouchScroll' in schedule and 'scrollY-origin.scrollY' in schedule and 'elapsed<650' in schedule
    assert "dragon_lair:'◈'" in admin and "lighthouse:'✺'" in admin and 'value="sacred_grove"' in admin_tpl
    assert 'max="1.6"' in admin_tpl and 'sourceBoost' in effects
    assert 'external_sheet_url' in chars and '/api/v61/characters/' in chars and 'foundry_actor_id' in chars and 'shAttacks' not in chars
    assert 'All Tables' in base and 'table-sensitive' in base
    assert "'/schedule','/tables'" in sw
