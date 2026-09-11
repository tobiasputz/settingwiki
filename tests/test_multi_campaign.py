from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.storage import init_db, create_player_invite, set_setting, connect
from app.features import (
    init_feature_db, save_player_character, list_player_characters,
    save_session, list_sessions, set_reveal, reveal_state,
)
from app.living import save_journal, list_journals, set_knowledge, knowledge_state
from app.campaigns import list_campaigns, save_campaign, default_campaign_id, set_campaign_members
from app.latex import build_wiki


def make_settings(tmp_path: Path) -> Settings:
    project=tmp_path/'project'; project.mkdir(); build=tmp_path/'build'; build.mkdir(); history=tmp_path/'history'; history.mkdir(); uploads=tmp_path/'uploads'; uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=make_settings(tmp_path); init_db(s); init_feature_db(s); return s


def seed_wiki(s: Settings) -> None:
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}
\begin{document}\chapter{World}\section{Crossroads}A place shared by many stories.\end{document}''',encoding='utf-8')
    build_wiki(s)


def test_upgrade_creates_fallback_campaign_without_auto_enrolling_invites(tmp_path: Path):
    # Simulate an older database by creating core state before the campaign
    # migration is run manually.
    s=make_settings(tmp_path); init_db(s)
    inv=create_player_invite(s,'Alice')
    with connect(s) as conn:
        conn.execute('CREATE TABLE campaign_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,status TEXT NOT NULL DEFAULT "planned",created_at REAL NOT NULL,updated_at REAL NOT NULL)')
        conn.execute('INSERT INTO campaign_sessions(title,status,created_at,updated_at) VALUES("Old session","ended",1,1)')
    from app.campaigns import init_campaign_db
    init_campaign_db(s)
    cid=default_campaign_id(s)
    assert list_campaigns(s,invite_id=inv['id'])==[]
    with connect(s) as conn:
        assert conn.execute('SELECT campaign_id FROM campaign_sessions').fetchone()[0]==cid


def test_campaign_owned_state_does_not_mix_between_tables(tmp_path: Path):
    s=setup(tmp_path); alice=create_player_invite(s,'Alice')
    main_id=default_campaign_id(s)
    second=save_campaign(s,{'name':'Ashen Coast','member_ids':[alice['id']]}); second_id=second['id']
    set_campaign_members(s,main_id,[alice['id']])

    a=save_player_character(s,{'name':'Aster','campaign_id':main_id},invite_id=alice['id'])
    b=save_player_character(s,{'name':'Bram','campaign_id':second_id},invite_id=alice['id'])
    sa=save_session(s,{'title':'Main table','status':'live','campaign_id':main_id})
    sb=save_session(s,{'title':'Coast table','status':'live','campaign_id':second_id})
    save_journal(s,{'title':'Main clue','body':'Only Aster knows','character_id':a['id'],'session_id':sa['id'],'campaign_id':main_id},alice['id'])
    save_journal(s,{'title':'Coast clue','body':'Only Bram knows','character_id':b['id'],'session_id':sb['id'],'campaign_id':second_id},alice['id'])
    set_reveal(s,{'target_type':'lore','target_key':'crossroads','state':'discovered','campaign_id':main_id})
    set_reveal(s,{'target_type':'lore','target_key':'crossroads','state':'hidden','campaign_id':second_id})
    set_knowledge(s,alice['id'],'page','crossroads','known',campaign_id=main_id)
    set_knowledge(s,alice['id'],'page','crossroads','unknown',campaign_id=second_id)

    assert [c['name'] for c in list_player_characters(s,invite_id=alice['id'],campaign_id=main_id)]==['Aster']
    assert [c['name'] for c in list_player_characters(s,invite_id=alice['id'],campaign_id=second_id)]==['Bram']
    assert [x['title'] for x in list_sessions(s,campaign_id=main_id)]==['Main table']
    assert [x['title'] for x in list_sessions(s,campaign_id=second_id)]==['Coast table']
    assert [x['body'] for x in list_journals(s,alice['id'],campaign_id=main_id)]==['Only Aster knows']
    assert [x['body'] for x in list_journals(s,alice['id'],campaign_id=second_id)]==['Only Bram knows']
    assert reveal_state(s,'lore','crossroads',campaign_id=main_id)['state']=='discovered'
    assert reveal_state(s,'lore','crossroads',campaign_id=second_id)['state']=='hidden'
    assert knowledge_state(s,alice['id'],'page','crossroads',campaign_id=main_id)['state']=='known'
    assert knowledge_state(s,alice['id'],'page','crossroads',campaign_id=second_id)['state']=='unknown'


def test_player_can_switch_campaign_and_character_shelf_follows(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path); seed_wiki(s); set_setting(s,'player_access_mode','invite'); monkeypatch.setattr(main,'settings',s)
    alice=create_player_invite(s,'Alice'); main_id=default_campaign_id(s)
    second=save_campaign(s,{'name':'The Northern Table','member_ids':[alice['id']]}); second_id=second['id']
    set_campaign_members(s,main_id,[alice['id']])
    save_player_character(s,{'name':'Aster','campaign_id':main_id},invite_id=alice['id'])
    save_player_character(s,{'name':'Bram','campaign_id':second_id},invite_id=alice['id'])

    c=TestClient(main.app); assert c.get(alice['invite_path'],follow_redirects=False).status_code==303
    first=c.get('/characters'); assert first.status_code==200
    assert 'Aster' in first.text and 'Bram' not in first.text and 'The Northern Table' in first.text
    switched=c.post('/api/campaign/select',json={'campaign_id':second_id}); assert switched.status_code==200
    second_page=c.get('/characters'); assert second_page.status_code==200
    assert 'Bram' in second_page.text and 'Aster' not in second_page.text


def test_player_cannot_switch_to_campaign_without_membership(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path); seed_wiki(s); set_setting(s,'player_access_mode','invite'); monkeypatch.setattr(main,'settings',s)
    alice=create_player_invite(s,'Alice'); locked=save_campaign(s,{'name':'Other Party','member_ids':[]})
    c=TestClient(main.app); c.get(alice['invite_path'])
    assert c.post('/api/campaign/select',json={'campaign_id':locked['id']}).status_code==403


def test_player_with_no_active_campaign_membership_cannot_fall_back_into_default(tmp_path: Path,monkeypatch):
    """Removing a player's table memberships must fail closed, not expose Main Campaign."""
    import app.main as main
    s=setup(tmp_path); seed_wiki(s); set_setting(s,'player_access_mode','invite'); monkeypatch.setattr(main,'settings',s)
    alice=create_player_invite(s,'Alice'); main_id=default_campaign_id(s)
    set_campaign_members(s,main_id,[alice['id']])
    save_player_character(s,{'name':'Other Party PC','campaign_id':main_id},invite_id=alice['id'])
    # Simulate the GM removing Alice from the only active campaign.
    set_campaign_members(s,main_id,[])
    c=TestClient(main.app); c.get(alice['invite_path'],follow_redirects=False)
    response=c.get('/characters')
    assert response.status_code==403
    assert 'not assigned to an active campaign' in response.text


def test_new_invitation_has_no_table_until_gm_assigns_one(tmp_path: Path):
    s=setup(tmp_path)
    alice=create_player_invite(s,'Alice')
    assert list_campaigns(s,invite_id=alice['id'])==[]
    table=save_campaign(s,{'name':'North Table','member_ids':[alice['id']]})
    assert [c['id'] for c in list_campaigns(s,invite_id=alice['id'])]==[table['id']]


def test_player_character_cannot_self_grant_another_table(tmp_path: Path):
    s=setup(tmp_path)
    alice=create_player_invite(s,'Alice')
    first=save_campaign(s,{'name':'First Table','member_ids':[alice['id']]})
    locked=save_campaign(s,{'name':'Locked Table','member_ids':[]})
    save_player_character(s,{'name':'Aster','campaign_id':first['id']},invite_id=alice['id'])
    try:
        save_player_character(s,{'name':'Sneak','campaign_id':locked['id']},invite_id=alice['id'])
    except PermissionError:
        pass
    else:
        raise AssertionError('player self-enrolled into a table via character creation')
    assert [c['id'] for c in list_campaigns(s,invite_id=alice['id'])]==[first['id']]


def test_tables_page_only_lists_explicit_player_memberships(tmp_path: Path,monkeypatch):
    import app.main as main
    s=setup(tmp_path); seed_wiki(s); set_setting(s,'player_access_mode','invite'); monkeypatch.setattr(main,'settings',s)
    alice=create_player_invite(s,'Alice')
    visible=save_campaign(s,{'name':'Alice Table','member_ids':[alice['id']]})
    hidden=save_campaign(s,{'name':'Other Party','member_ids':[]})
    c=TestClient(main.app); c.get(alice['invite_path'],follow_redirects=False)
    page=c.get('/tables')
    assert page.status_code==200
    assert 'Alice Table' in page.text
    assert 'Other Party' not in page.text
    assert c.post('/api/campaign/select',json={'campaign_id':visible['id']}).status_code==200
    assert c.post('/api/campaign/select',json={'campaign_id':hidden['id']}).status_code==403
