from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.campaigns import default_campaign_id, delete_campaign, get_campaign, save_campaign
from app.config import Settings
from app.features import init_feature_db, save_player_character, save_session
from app.latex import build_wiki
from app.scheduling import list_player_availability, save_player_availability
from app.storage import connect, create_player_invite, init_db, set_setting
from app.v5 import (
    campaign_fog_regions,
    investigation_board,
    list_party_notes,
    map_discovery_states,
    save_investigation_node,
    save_party_note,
    save_preparation,
    save_rsvp,
    set_campaign_fog,
    set_follow,
    set_map_discovery,
)


def settings_for(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=settings_for(tmp_path);init_db(s);init_feature_db(s);return s


def seed_wiki(s: Settings) -> None:
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}
\begin{document}
\chapter{World}
\section{Moon Court}
The Moon Court watches the old road and guards a secret observatory.
\section{Old Road}
A pilgrim road crossing the northern hills.
\end{document}
''',encoding='utf-8')
    build_wiki(s)


def test_v5_schema_and_narrative_character_links(tmp_path: Path):
    s=setup(tmp_path);inv=create_player_invite(s,'Alice');cid=default_campaign_id(s)
    char=save_player_character(s,{'name':'Aster','campaign_id':cid,'external_sheet_url':'https://pathbuilder.example/aster','foundry_actor_url':'https://foundry.example/actor/aster'},invite_id=inv['id'])
    with connect(s) as conn:
        cols={r['name'] for r in conn.execute('PRAGMA table_info(player_characters)').fetchall()}
        tables={r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {'external_sheet_url','foundry_actor_url'} <= cols
    assert {'party_notes','investigation_nodes','campaign_objectives','session_rsvps','session_preparations','campaign_map_discoveries','player_follows'} <= tables
    assert char['external_sheet_url'].startswith('https://pathbuilder') and char['foundry_actor_url'].startswith('https://foundry')


def test_party_notes_and_investigation_are_campaign_and_player_scoped(tmp_path: Path):
    s=setup(tmp_path);a=create_player_invite(s,'Alice');b=create_player_invite(s,'Bob');cid=default_campaign_id(s)
    save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=a['id']);save_player_character(s,{'name':'Bram','campaign_id':cid},invite_id=b['id'])
    sess=save_session(s,{'campaign_id':cid,'title':'Night Watch','status':'live'})
    note=save_party_note(s,cid,sess['id'],a['id'],'Alice','The bell rang twice.')
    assert list_party_notes(s,cid,sess['id'])[0]['id']==note['id']
    n=save_investigation_node(s,cid,a['id'],{'title':'Bell theory','note':'Maybe the ferryman.','x':.3,'y':.4})
    assert investigation_board(s,cid,a['id'])['nodes'][0]['id']==n['id']
    assert investigation_board(s,cid,b['id'])['nodes']==[]


def test_campaign_delete_removes_table_state_but_keeps_global_availability(tmp_path: Path):
    s=setup(tmp_path);inv=create_player_invite(s,'Alice');main=default_campaign_id(s);other=save_campaign(s,{'name':'Second Table'})
    save_player_character(s,{'name':'Bram','campaign_id':other['id']},invite_id=inv['id'])
    day=(dt.date.today()+dt.timedelta(days=14)).isoformat();save_player_availability(s,inv['id'],[{'date':day,'status':'available'}])
    save_session(s,{'campaign_id':other['id'],'title':'Second Table Session','status':'planned'})
    with pytest.raises(ValueError): delete_campaign(s,main)
    delete_campaign(s,other['id'])
    assert get_campaign(s,other['id']) is None
    assert list_player_availability(s,inv['id'],day,day)[0]['status']=='available'
    with connect(s) as conn:
        assert conn.execute('SELECT COUNT(*) FROM player_characters WHERE campaign_id=?',(other['id'],)).fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id=?',(other['id'],)).fetchone()[0]==0


def test_rsvp_and_gm_preparation_roundtrip(tmp_path: Path):
    s=setup(tmp_path);inv=create_player_invite(s,'Alice');cid=default_campaign_id(s)
    save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=inv['id'])
    sess=save_session(s,{'campaign_id':cid,'title':'Glass Road','session_date':'2030-05-05','status':'planned'})
    rsvp=save_rsvp(s,sess['id'],inv['id'],'going','I will bring snacks')
    assert rsvp['status']=='going'
    prep=save_preparation(s,sess['id'],cid,{'opening':'Rain on the bridge.','beats':[{'title':'The ambush','note':'After the bell','done':False}],'secrets':'The guide is compromised.','contingencies':'If they turn back, move the clue.','notes':'Remember Corvina.','references':[{'type':'page','key':'moon-court','label':'Moon Court'}]})
    assert prep['opening']=='Rain on the bridge.' and prep['beats'][0]['title']=='The ambush'
    assert prep['references'][0]['key']=='moon-court'


def test_followed_lore_generates_campaign_notification(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    inv=create_player_invite(s,'Alice');cid=default_campaign_id(s);save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=inv['id'])
    player=TestClient(main.app);assert player.get(inv['invite_path'],follow_redirects=False).status_code==303
    assert player.post('/api/v5/follows',json={'target_type':'page','target_key':'moon-court','label':'Moon Court','enabled':True}).status_code==200
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    update=gm.post('/api/admin/session-updates',json={'title':'The bells changed','body':'Something is different at the court.','target_type':'page','target_key':'moon-court','visibility':'players'})
    assert update.status_code==200
    rows=player.get('/api/public/notifications').json()
    assert any(r['kind']=='follow' and r['target_key']=='moon-court' for r in rows)


def test_campaign_map_discovery_and_fog_are_table_specific(tmp_path: Path):
    s=setup(tmp_path);main=default_campaign_id(s);other=save_campaign(s,{'name':'Other Table'})
    now=1.0
    with connect(s) as conn:
        map_id=conn.execute("INSERT INTO maps(name,slug,image_path,description,created_at,updated_at) VALUES('World','world','map.png','',?,?)",(now,now)).lastrowid
        marker_id=conn.execute("INSERT INTO markers(map_id,title,body,x,y,kind,visible_to_players,created_at,updated_at) VALUES(?,?,?,?,?,'place',1,?,?)",(map_id,'Hidden Shrine','',.5,.5,now,now)).lastrowid
        fog_id=conn.execute("INSERT INTO map_fog_regions(map_id,title,style,points_json,revealed,created_at,updated_at) VALUES(?,?,?,?,0,?,?)",(map_id,'North Mist','mist','[[0,0],[1,0],[1,1]]',now,now)).lastrowid
    set_map_discovery(s,main,marker_id,'visited');set_map_discovery(s,other['id'],marker_id,'rumored')
    assert map_discovery_states(s,main,[marker_id])[marker_id]['state']=='visited'
    assert map_discovery_states(s,other['id'],[marker_id])[marker_id]['state']=='rumored'
    fog=[{'id':fog_id,'revealed':False,'points':[[0,0],[1,0],[1,1]]}]
    assert campaign_fog_regions(s,main,fog)==fog
    set_campaign_fog(s,main,fog_id,True)
    assert campaign_fog_regions(s,main,fog)==[] and campaign_fog_regions(s,other['id'],fog)==fog


def test_v5_session_prep_recap_and_investigation_routes_render(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    inv=create_player_invite(s,'Alice');cid=default_campaign_id(s);save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=inv['id']);save_session(s,{'campaign_id':cid,'title':'Next Session','status':'planned'})
    p=TestClient(main.app);p.get(inv['invite_path'])
    for path in ['/session','/recap','/investigation']:
        r=p.get(path);assert r.status_code==200,path
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    assert gm.get('/gm/prep').status_code==200


def test_v5_frontend_release_contracts():
    root=Path(__file__).resolve().parents[1]
    session=(root/'templates/session.html').read_text(encoding='utf-8')
    prep=(root/'templates/gm_prep.html').read_text(encoding='utf-8')
    investigation=(root/'templates/investigation.html').read_text(encoding='utf-8')
    recap=(root/'templates/recap.html').read_text(encoding='utf-8')
    chars=(root/'templates/character.html').read_text(encoding='utf-8')
    schedule=(root/'static/schedule.js').read_text(encoding='utf-8')
    campaign=(root/'static/campaign-admin.js').read_text(encoding='utf-8')
    sw=(root/'static/sw.js').read_text(encoding='utf-8')
    assert 'PARTY-OWNED MEMORY' in session and 'session-v5-tabs' in session and 'data-rsvp' in session
    assert 'PINNED TO TONIGHT' in prep and 'SEEKER_PREP' in prep
    assert 'INVESTIGATION' in investigation and 'investigation.js?v=7301' in investigation
    assert 'Previously on' in recap
    assert 'Pathbuilder / sheet URL' in chars and 'Foundry actor' in chars and 'shAttacks' not in (root/'static/characters.js').read_text()
    assert 'planSession(key)' in schedule and '/gm/prep?session_id=' in schedule
    assert "'/api/admin/campaigns/'+b.dataset.archiveCampaign+'/archive'" in campaign and 'data-delete-campaign' in campaign
    assert 'seeker-static-v7301' in sw and "'/investigation','/recap'" in sw
