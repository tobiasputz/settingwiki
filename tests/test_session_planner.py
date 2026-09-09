from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.storage import init_db, create_player_invite, set_setting
from app.features import init_feature_db, save_player_character
from app.campaigns import save_campaign, default_campaign_id, invite_has_campaign
from app.scheduling import init_schedule_db, save_player_availability, list_player_availability, campaign_schedule, player_campaigns
from app.latex import build_wiki


def make_settings(tmp_path: Path) -> Settings:
    project=tmp_path/'project'; project.mkdir(); build=tmp_path/'build'; build.mkdir(); history=tmp_path/'history'; history.mkdir(); uploads=tmp_path/'uploads'; uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=make_settings(tmp_path);init_db(s);init_feature_db(s);init_schedule_db(s);return s


def seed_wiki(s: Settings) -> None:
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}\begin{document}\chapter{World}\section{Crossroads}Shared setting.\end{document}''',encoding='utf-8')
    build_wiki(s)


def future(days: int) -> str:
    return (dt.date.today()+dt.timedelta(days=days)).isoformat()


def test_one_player_calendar_applies_to_every_campaign_character(tmp_path: Path):
    s=setup(tmp_path);alice=create_player_invite(s,'Alice');main=default_campaign_id(s)
    coast=save_campaign(s,{'name':'Ashen Coast','member_ids':[alice['id']]})['id']
    save_player_character(s,{'name':'Aster','campaign_id':main},invite_id=alice['id'])
    save_player_character(s,{'name':'Bram','campaign_id':coast},invite_id=alice['id'])
    day=future(5);save_player_availability(s,alice['id'],[{'date':day,'status':'available'}])
    assert list_player_availability(s,alice['id'],day,day)[0]['status']=='available'
    assert campaign_schedule(s,main,day,day)['next_all_available']['date']==day
    assert campaign_schedule(s,coast,day,day)['next_all_available']['date']==day
    assert {c['name'] for c in player_campaigns(s,alice['id'])}=={'Main Campaign','Ashen Coast'}


def test_planner_distinguishes_green_soft_blocked_and_unknown(tmp_path: Path):
    s=setup(tmp_path);alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob');cid=default_campaign_id(s)
    save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=alice['id'])
    save_player_character(s,{'name':'Borin','campaign_id':cid},invite_id=bob['id'])
    d1,d2,d3,d4=[future(n) for n in (2,3,4,5)]
    save_player_availability(s,alice['id'],[
        {'date':d1,'status':'available'},{'date':d2,'status':'available'},{'date':d3,'status':'unavailable'},{'date':d4,'status':'available'}])
    save_player_availability(s,bob['id'],[
        {'date':d1,'status':'available'},{'date':d2,'status':'if_needed'},{'date':d3,'status':'available'}])
    out=campaign_schedule(s,cid,d1,d4);states={d['date']:d['state'] for d in out['days']}
    assert states[d1]=='all_available'
    assert states[d2]=='if_needed'
    assert states[d3]=='blocked'
    assert states[d4]=='waiting'
    assert out['next_all_available']['date']==d1
    assert out['next_if_needed']['date']==d2


def test_same_player_with_two_characters_counts_once(tmp_path: Path):
    s=setup(tmp_path);alice=create_player_invite(s,'Alice');cid=default_campaign_id(s)
    save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=alice['id'])
    save_player_character(s,{'name':'Backup','campaign_id':cid},invite_id=alice['id'])
    day=future(1);save_player_availability(s,alice['id'],[{'date':day,'status':'available'}])
    out=campaign_schedule(s,cid,day,day)
    assert len(out['participants'])==1
    assert 'Aster' in out['participants'][0]['characters'] and 'Backup' in out['participants'][0]['characters']
    assert out['next_all_available'] is not None


def test_character_assignment_can_self_join_active_campaign(tmp_path: Path):
    s=setup(tmp_path);alice=create_player_invite(s,'Alice');other=save_campaign(s,{'name':'Second Story','member_ids':[]})
    assert not invite_has_campaign(s,alice['id'],other['id'])
    save_player_character(s,{'name':'Wayfarer','campaign_id':other['id']},invite_id=alice['id'])
    assert invite_has_campaign(s,alice['id'],other['id'])


def test_schedule_http_player_save_and_gm_summary(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    alice=create_player_invite(s,'Alice');cid=default_campaign_id(s);save_player_character(s,{'name':'Aster','campaign_id':cid},invite_id=alice['id'])
    day=future(6)
    player=TestClient(main.app);player.get(alice['invite_path'])
    page=player.get('/schedule');assert page.status_code==200 and 'Mark it once' in page.text
    saved=player.post('/api/schedule/me',json={'changes':[{'date':day,'status':'available'}]});assert saved.status_code==200
    owner=TestClient(main.app);owner.post('/admin/login',data={'password':'admin'})
    summary=owner.get('/api/gm/schedule',params={'start':day,'end':day,'campaign_id':cid});assert summary.status_code==200
    assert summary.json()['next_all_available']['date']==day
    gm_page=owner.get('/schedule');assert gm_page.status_code==200 and 'Find the next night everyone can make.' in gm_page.text
