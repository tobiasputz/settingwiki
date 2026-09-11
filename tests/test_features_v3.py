from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.features import init_feature_db
from app.latex import build_wiki
from app.living import (
    add_thread_note,
    create_portable_archive,
    validate_portable_archive_file,
    list_threads,
    map_regions,
    media_usage,
    replace_media_reference,
    save_map_region,
    save_region_history,
    save_thread,
    update_thread_note,
)
from app.maps import create_map
from app.storage import create_player_invite, init_db, set_setting


def make_settings(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=make_settings(tmp_path);init_db(s);init_feature_db(s);return s


def seed_wiki(s: Settings) -> None:
    (s.project_dir/'main.tex').write_text(r'''\documentclass{book}
\begin{document}
\chapter{World}
\section{Welcome}
Welcome to the campaign.
\end{document}
''',encoding='utf-8')
    build_wiki(s)


def test_player_agency_party_threads_and_note_ownership(tmp_path: Path):
    s=setup(tmp_path)
    a=create_player_invite(s,'Alice');b=create_player_invite(s,'Bob')
    from app.campaigns import default_campaign_id, set_campaign_members
    set_campaign_members(s,default_campaign_id(s),[a['id'],b['id']])
    thread=save_thread(s,{'title':'Who stole the crown?','editing':'party','visibility':'party'},invite_id=a['id'])
    # Party-owned thread itself is collaboratively editable.
    edited=save_thread(s,{**thread,'summary':'Bob added the witness clue.'},invite_id=b['id'])
    assert edited['summary']=='Bob added the witness clue.'
    # Notes retain authorship even on a party-editable thread.
    note=add_thread_note(s,thread['id'],{'body':'Alice theory','visibility':'party'},invite_id=a['id'],author_label='Alice')
    try:
        update_thread_note(s,note['id'],{'body':'Bob rewrite'},invite_id=b['id'])
        assert False,'another player must not overwrite a player-owned note'
    except PermissionError:
        pass
    # GM can supplement/correct shared state without taking authorship away from players.
    gm=update_thread_note(s,note['id'],{'body':'GM clarification','visibility':'party'},admin=True)
    assert gm['body']=='GM clarification' and gm['gm_edited']==1
    assert list_threads(s,invite_id=b['id'])[0]['notes'][0]['body']=='GM clarification'


def test_observer_is_read_only_player_can_author_and_cogm_is_not_owner(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    player_inv=create_player_invite(s,'Player',role='player')
    observer_inv=create_player_invite(s,'Observer',role='observer')
    cogm_inv=create_player_invite(s,'Co-GM',role='co-gm')
    from app.campaigns import default_campaign_id, set_campaign_members
    set_campaign_members(s,default_campaign_id(s),[player_inv['id'],observer_inv['id'],cogm_inv['id']])

    player=TestClient(main.app);observer=TestClient(main.app);cogm=TestClient(main.app)
    assert player.get(player_inv['invite_path'],follow_redirects=False).status_code==303
    assert observer.get(observer_inv['invite_path'],follow_redirects=False).status_code==303
    assert cogm.get(cogm_inv['invite_path'],follow_redirects=False).status_code==303

    assert player.post('/api/threads',json={'title':'Player-maintained plot','editing':'party'}).status_code==200
    assert observer.post('/api/threads',json={'title':'Should fail'}).status_code==403
    assert observer.post('/api/player/submissions',json={'title':'Should fail'}).status_code==403
    assert cogm.get('/admin/living').status_code==200
    assert cogm.get('/api/admin/portable-archive').status_code==401


def test_archive_mode_freezes_campaign_writes_but_owner_can_unfreeze(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    inv=create_player_invite(s,'Alice')
    from app.campaigns import default_campaign_id, set_campaign_members
    set_campaign_members(s,default_campaign_id(s),[inv['id']])
    player=TestClient(main.app); assert player.get(inv['invite_path'],follow_redirects=False).status_code==303
    set_setting(s,'campaign_archive_mode','1')
    assert player.get('/archive').status_code==200
    r=player.post('/api/threads',json={'title':'No edits after freeze'})
    assert r.status_code==403 and 'archived' in r.json()['detail'].lower()

    owner=TestClient(main.app);assert owner.post('/admin/login',data={'password':'admin'}).status_code==200
    assert owner.put('/api/admin/archive-mode',json={'enabled':False}).status_code==200
    assert player.post('/api/threads',json={'title':'Edits resume'}).status_code==200


def test_historical_region_shapes_roundtrip_as_drawable_points(tmp_path: Path):
    s=setup(tmp_path)
    m=create_map(s,'Old World','maps/old-world.webp')
    r=save_map_region(s,m['id'],{'title':'Sun Empire','points':[[.1,.1],[.8,.1],[.6,.7]],'fill':'#a9834d'})
    h=save_region_history(s,r['id'],{'title':'Before the Sundering','start_sort':400,'end_sort':500,'points':[[.05,.05],[.9,.08],[.55,.8]],'fill':'#8a6f47'})
    rows=map_regions(s,m['id'],admin=True)
    assert rows[0]['history'][0]['points']==[[.05,.05],[.9,.08],[.55,.8]]
    active=map_regions(s,m['id'],admin=True,at_sort=450)[0]
    assert active['points']==[[.05,.05],[.9,.08],[.55,.8]] and active['history_label']=='Before the Sundering'
    assert h['id']==rows[0]['history'][0]['id']


def test_media_usage_and_replacement_update_source(tmp_path: Path):
    s=setup(tmp_path)
    tex=s.project_dir/'NPC.tex';tex.write_text(r'\includegraphics{Images/old.png}',encoding='utf-8')
    usage=media_usage(s,'project:Images/old.png')
    assert usage['count']==1 and usage['uses'][0]['path']=='NPC.tex'
    result=replace_media_reference(s,'project:Images/old.png','project:Images/new.png')
    assert 'NPC.tex' in result['source_files']
    assert 'Images/new.png' in tex.read_text(encoding='utf-8') and 'Images/old.png' not in tex.read_text(encoding='utf-8')


def test_portable_archive_contains_source_uploads_database_and_manifest(tmp_path: Path):
    s=setup(tmp_path);(s.project_dir/'main.tex').write_text('campaign',encoding='utf-8')
    asset=s.uploads_dir/'characters'/'portrait.png';asset.parent.mkdir(parents=True);asset.write_bytes(b'portrait')
    out=create_portable_archive(s,tmp_path/'portable.zip')
    with zipfile.ZipFile(out) as z:
        names=set(z.namelist())
        assert {'project/main.tex','uploads/characters/portrait.png','loreforge.db','manifest.json'} <= names
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['format']=='loreforge-portable-v1'


def test_portable_archive_restore_test_exercises_manifest_and_database(tmp_path: Path):
    s=setup(tmp_path);(s.project_dir/'main.tex').write_text('campaign',encoding='utf-8')
    out=create_portable_archive(s,tmp_path/'portable.zip')
    report=validate_portable_archive_file(out)
    assert report['ok'] is True and report['tex_files']==1 and report['database_tables']>0
    # A syntactically valid ZIP is not enough: a missing Loreforge DB must fail.
    bad=tmp_path/'bad.zip'
    with zipfile.ZipFile(bad,'w') as z:
        z.writestr('manifest.json',json.dumps({'format':'loreforge-portable-v1'}));z.writestr('project/main.tex','x')
    try:
        validate_portable_archive_file(bad)
        assert False,'missing DB should fail restore test'
    except ValueError as exc:
        assert 'missing' in str(exc).lower()


def test_v3_player_session_and_worldbuilding_ui_are_integrated():
    root=Path(__file__).resolve().parents[1]
    session=(root/'templates'/'session.html').read_text(encoding='utf-8')
    living=(root/'templates'/'living.html').read_text(encoding='utf-8')
    admin_js=(root/'static'/'living-admin.js').read_text(encoding='utf-8')
    assert 'PARTY-OWNED MEMORY' in session and 'data-new-journal' in session and '/static/living.js' in session
    assert 'can_author' in living and 'Archived · read only' in living
    assert 'polygonEditor' in admin_js and 'click the map to add a border point' in admin_js
    assert 'Where is this used?' in admin_js and '/api/admin/inbox/upload' in admin_js
    assert 'Record voice memo' in admin_js and '/api/admin/portable-archive/test' in admin_js
    sw=(root/'static'/'sw.js').read_text(encoding='utf-8'); assert "'/campaign'" in sw and "'/archive'" in sw

def test_public_reader_mode_does_not_grant_anonymous_authoring(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','public');monkeypatch.setattr(main,'settings',s)
    c=TestClient(main.app)
    assert c.get('/campaign').status_code==200
    assert c.post('/api/threads',json={'title':'Anonymous edit'}).status_code==403

def test_portable_backup_test_endpoint_is_owner_only_and_non_destructive(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    archive=create_portable_archive(s,tmp_path/'backup.zip')
    anon=TestClient(main.app)
    with archive.open('rb') as fh:
        assert anon.post('/api/admin/portable-archive/test',files={'file':('backup.zip',fh,'application/zip')}).status_code==401
    owner=TestClient(main.app);assert owner.post('/admin/login',data={'password':'admin'}).status_code==200
    before=(s.project_dir/'main.tex').read_text(encoding='utf-8')
    with archive.open('rb') as fh:
        r=owner.post('/api/admin/portable-archive/test',files={'file':('backup.zip',fh,'application/zip')})
    assert r.status_code==200 and r.json()['ok'] is True
    assert (s.project_dir/'main.tex').read_text(encoding='utf-8')==before
