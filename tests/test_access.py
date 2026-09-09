from pathlib import Path

from app.config import Settings
from app.storage import create_player_invite, init_db, register_player_device, revoke_player_invite, set_setting


def make_settings(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


class DummyRequest:
    def __init__(self, session=None):
        self.session = session or {}


def test_invite_mode_requires_live_personal_invitation_session(tmp_path: Path, monkeypatch):
    import app.main as main
    s=make_settings(tmp_path);init_db(s);set_setting(s,'player_access_mode','invite')
    monkeypatch.setattr(main,'settings',s)
    assert main.player_allowed(DummyRequest()) is False
    invite=create_player_invite(s,'Piotr')
    device=register_player_device(s,invite['id'],invite['access_version'])
    req=DummyRequest({'player_invite_id':invite['id'],'player_invite_version':invite['access_version'],'player_device_id':device})
    assert main.player_allowed(req) is True
    revoke_player_invite(s,invite['id'])
    assert main.player_allowed(req) is False


def test_admin_always_has_player_view_access(tmp_path: Path, monkeypatch):
    import app.main as main
    s=make_settings(tmp_path);init_db(s);set_setting(s,'player_access_mode','invite')
    monkeypatch.setattr(main,'settings',s)
    assert main.player_allowed(DummyRequest({'admin':True})) is True


def test_invitation_route_authenticates_one_browser_and_revocation_is_live(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    s=make_settings(tmp_path);init_db(s);set_setting(s,'player_access_mode','invite')
    monkeypatch.setattr(main,'settings',s)

    admin=TestClient(main.app)
    assert admin.post('/admin/login',data={'password':'admin'},follow_redirects=False).status_code==303
    created=admin.post('/api/admin/invitations',json={'label':'Sarah','max_devices':1})
    assert created.status_code==200
    invite=created.json()

    player=TestClient(main.app)
    assert player.get('/',follow_redirects=False).headers['location']=='/access'
    assert player.get(invite['invite_path'],follow_redirects=False).status_code==303
    assert player.get('/',follow_redirects=False).status_code==200

    # A second fresh browser cannot consume another slot on a one-device link.
    second=TestClient(main.app)
    assert second.get(invite['invite_path'],follow_redirects=False).status_code==403

    # Resetting devices invalidates the old browser without changing the bearer URL.
    assert admin.post(f"/api/admin/invitations/{invite['id']}/reset-devices").status_code==200
    assert player.get('/',follow_redirects=False).headers['location']=='/access'
    assert second.get(invite['invite_path'],follow_redirects=False).status_code==303

    # Revocation is checked on the next protected request, not only at login time.
    assert admin.post(f"/api/admin/invitations/{invite['id']}/revoke").status_code==200
    assert second.get('/',follow_redirects=False).headers['location']=='/access'


def test_player_page_template_contains_admin_source_bridge():
    root=Path(__file__).resolve().parents[1]
    page=(root/'templates'/'page.html').read_text(encoding='utf-8')
    admin_js=(root/'static'/'admin.js').read_text(encoding='utf-8')
    wiki_js=(root/'static'/'wiki.js').read_text(encoding='utf-8')
    assert 'data-gm-edit-source' in page
    assert 'admin_view' in page
    assert "qp.get('file')" in admin_js and "qp.get('line')" in admin_js
    assert 'updateGmEditTarget' in wiki_js


def test_admin_opening_invite_does_not_consume_device_slot(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    from app.storage import get_player_invite

    s=make_settings(tmp_path);init_db(s);set_setting(s,'player_access_mode','invite')
    monkeypatch.setattr(main,'settings',s)
    admin=TestClient(main.app)
    assert admin.post('/admin/login',data={'password':'admin'},follow_redirects=False).status_code==303
    invite=admin.post('/api/admin/invitations',json={'label':'Player','max_devices':1}).json()
    assert admin.get(invite['invite_path'],follow_redirects=False).status_code==303
    assert get_player_invite(s,invite['id'])['device_count']==0
    player=TestClient(main.app)
    assert player.get(invite['invite_path'],follow_redirects=False).status_code==303
    assert get_player_invite(s,invite['id'])['device_count']==1
