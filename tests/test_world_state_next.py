"""Seeker world-state regression and publication safety tests."""
from pathlib import Path
import pytest
from app.config import Settings
from app.storage import init_db, connect
from app.features import init_feature_db, save_session
from app.scheduling import init_schedule_db
from app.v5 import init_v5_db
from app.v51 import init_v51_db
from app.v6 import init_v6_db
from app.v7 import init_v7_db
from app.v8 import init_v8_db
from app.v10 import init_v10_db
from app.world_state import init_world_state_db, write_event, events_for_gm, events_for_player
from app.campaigns import default_campaign_id


def setup(tmp_path):
    for part in ('project','build','history','uploads'):(tmp_path/part).mkdir()
    s=Settings(tmp_path,tmp_path,tmp_path/'project',tmp_path/'build',tmp_path/'history',tmp_path/'uploads',tmp_path/'db.sqlite','secret','admin',None,'auto',20,False)
    for init in (init_db,init_feature_db,init_schedule_db,init_v5_db,init_v51_db,init_v6_db,init_v7_db,init_v8_db,init_v10_db,init_world_state_db):init(s)
    return s


def test_event_draft_publication_and_gm_only_fields(tmp_path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    session=save_session(s,{'campaign_id':cid,'title':'Secrets','status':'planned'})
    original=write_event(s,cid,{'title':'SECRET cult headquarters','gm_notes':'The king is the villain','session_id':session['id'],'kind':'discovery'})
    assert original['status']=='draft' and events_for_player(s,cid)==[]
    with pytest.raises(ValueError,match='player-safe'):
        write_event(s,cid,{'status':'published','confirm_publish':True},event_id=original['id'])
    with pytest.raises(ValueError,match='explicit confirmation'):
        write_event(s,cid,{'status':'published','player_title':'A discovery','player_summary':'There was a mysterious trail.'},event_id=original['id'])
    updated=write_event(s,cid,{'status':'published','confirm_publish':True,'player_title':'A discovery','player_summary':'A mysterious trail was found.'},event_id=original['id'])
    assert updated['title']==original['title']
    safe=events_for_player(s,cid)
    assert safe==[{'id':original['id'],'kind':'discovery','title':'A discovery','summary':'A mysterious trail was found.','occurred_at':original['occurred_at']}]
    assert 'king' not in str(safe).lower() and 'headquarters' not in str(safe).lower()
    assert events_for_gm(s,cid,session_id=session['id'])[0]['gm_notes']=='The king is the villain'
    write_event(s,cid,{'status':'archived'},event_id=original['id'])
    assert events_for_player(s,cid)==[]


def test_event_rejects_wrong_campaign_session_and_update(tmp_path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    with connect(s) as conn:
        row=conn.execute('INSERT INTO campaigns(name,slug,created_at,updated_at) VALUES(?,?,?,?)',('Other campaign','other-campaign',1,1))
        other=row.lastrowid
    session=save_session(s,{'campaign_id':other,'title':'Other campaign session','status':'planned'})
    with pytest.raises(ValueError,match='not part of'):
        write_event(s,cid,{'title':'Stolen event','session_id':session['id']})
    owned=write_event(s,cid,{'title':'Private event'})
    assert events_for_gm(s,other)==[]
    with pytest.raises(ValueError,match='not found'):
        write_event(s,other,{'title':'Should fail'},event_id=owned['id'])


def test_event_model_validates_input(tmp_path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    with pytest.raises(ValueError,match='title'):write_event(s,cid,{'title':'  '})
    with pytest.raises(ValueError,match='type'):write_event(s,cid,{'title':'A','kind':'broken'})
    with pytest.raises(ValueError,match='date'):write_event(s,cid,{'title':'A','occurred_at':'NaN'})
    assert write_event(s,cid,{'title':'A','gm_notes':'private','status':'draft'})['id']>0


def test_world_routes_enforce_gm_and_approved_player_projection(tmp_path,monkeypatch):
    import app.main as main
    from fastapi.testclient import TestClient
    from app.storage import create_player_invite,set_setting
    from app.campaigns import set_campaign_members
    s=setup(tmp_path);cid=default_campaign_id(s)
    (s.project_dir/'main.tex').write_text('\\documentclass{article}\\begin{document}Test\\end{document}',encoding='utf-8')
    set_setting(s,'player_access_mode','invite')
    monkeypatch.setattr(main,'settings',s)
    inv=create_player_invite(s,'Reader')
    set_campaign_members(s,cid,[inv['id']])
    guest=TestClient(main.app)
    assert guest.get('/api/world/events').status_code in {401,403}
    assert guest.post('/api/world/events',json={'title':'Unauthorized'}).status_code in {401,403}
    gm=TestClient(main.app)
    assert gm.post('/admin/login',data={'password':'admin'}).status_code in {200,303}
    created=gm.post('/api/world/events',json={'title':'Secrets','gm_notes':'Hidden cult','status':'draft'})
    assert created.status_code==200,created.text
    assert gm.get('/api/world/events').json()['events'][0]['gm_notes']=='Hidden cult'
    assert guest.get(inv['invite_path'],follow_redirects=False).status_code==303
    assert guest.get('/api/world/known-events').json()['events']==[]
    event_id=created.json()['id']
    pub=gm.put(f'/api/world/events/{event_id}',json={'status':'published','player_title':'A known event','player_summary':'People saw lights.','confirm_publish':True})
    assert pub.status_code==200,pub.text
    safe=guest.get('/api/world/known-events')
    assert safe.status_code==200
    assert safe.json()['events'][0]['title']=='A known event'
    assert 'Hidden cult' not in safe.text and 'gm_notes' not in safe.text and 'entity_id' not in safe.text


def test_source_studio_refuses_stale_hash(tmp_path,monkeypatch):
    import app.main as main
    from fastapi.testclient import TestClient
    from app.storage import set_setting
    s=setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    (s.project_dir/'main.tex').write_text('Original source',encoding='utf-8')
    gm=TestClient(main.app)
    assert gm.post('/admin/login',data={'password':'admin'}).status_code in {200,303}
    opened=gm.get('/api/v8/source?path=main.tex')
    assert opened.status_code==200,opened.text
    old=opened.json()['source_hash']
    (s.project_dir/'main.tex').write_text('Other editor changed it',encoding='utf-8')
    conflict=gm.put('/api/v8/source',json={'path':'main.tex','text':'Stale overwriting text','expected_hash':old})
    assert conflict.status_code==409,conflict.text
    assert (s.project_dir/'main.tex').read_text()=='Other editor changed it'
