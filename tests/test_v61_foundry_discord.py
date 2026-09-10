from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.storage import init_db, create_player_invite, connect, set_setting
from app.features import init_feature_db, save_player_character
from app.campaigns import default_campaign_id, set_campaign_members
from app.latex import build_wiki
from app.v6 import (
    init_v6_db,
    integration_config,
    save_integration_config,
    foundry_accept,
    foundry_actors,
    foundry_link,
    foundry_link_for_character,
    discord_session_confirmation,
)


def settings_for(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=settings_for(tmp_path);init_db(s);init_feature_db(s);init_v6_db(s);return s


def seed_wiki(s: Settings) -> None:
    (s.project_dir/'main.tex').write_text(r'\documentclass{book}\begin{document}\chapter{World}\section{Moon Court}A court.\end{document}',encoding='utf-8')
    build_wiki(s)


def actor_payload():
    return {
        'bridge_version':'1.1.0','foundry_version':'13.0','system':'pf2e','system_version':'7.0',
        'world':{'id':'kiragon','title':'Kiragon'},'scene':{'id':'road','name':'Old Road'},
        'actors':[{
            'id':'abc123','uuid':'Actor.abc123','name':'Aster','img':'https://foundry.example/aster.webp',
            'url':'https://foundry.example/game?seekerActor=Actor.abc123','type':'character','owners':['Alice'],
            'sheet':{
                'identity':{'level':7,'class_name':'Thaumaturge','ancestry':'Human','heritage':'Versatile Heritage','background':'Scholar','languages':['Common','Elven'],'traits':['human']},
                'vitals':{'hp':{'value':72,'max':80,'temp':0},'ac':26,'perception':{'mod':16},'speed':{'value':25,'other':[]},'hero_points':{'value':2,'max':3},'focus':{'value':1,'max':1}},
                'abilities':[{'label':'STR','mod':2},{'label':'CHA','mod':4}],
                'saves':[{'label':'fortitude','mod':14,'rank_label':'Expert'}],
                'skills':[{'label':'occultism','mod':17,'rank_label':'Master'}],
                'strikes':[{'name':'Sword','mod':16,'damage':'2d8+4','traits':['versatile']}],
                'conditions':[], 'feats':[{'name':'Diverse Lore','type':'feat','description':'Recall more.'}],
                'actions':[], 'inventory':[{'name':'Lantern','type':'equipment','quantity':1,'equipped':False}],
                'spells':{}, 'lore':[], 'effects':[]
            }
        }]
    }


def test_v61_schema_foundry_actor_sync_and_link(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s);cfg=integration_config(s,cid,include_secret=True)
    with connect(s) as conn:
        cols={r['name'] for r in conn.execute('PRAGMA table_info(campaign_integrations)').fetchall()}
        tables={r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {'discord_mention','discord_auto_session_confirmed'} <= cols
    assert {'foundry_actor_snapshots','foundry_character_links'} <= tables
    assert foundry_accept(s,cid,cfg['foundry_bridge_token'],actor_payload())=={'ok':True,'actors':1}
    actors=foundry_actors(s,cid);assert actors[0]['name']=='Aster' and actors[0]['sheet']['vitals']['ac']==26
    inv=create_player_invite(s,'Alice');set_campaign_members(s,cid,[inv['id']])
    char=save_player_character(s,{'campaign_id':cid,'name':'Aster'},invite_id=inv['id'])
    linked=foundry_link(s,char['id'],cid,'abc123');assert linked['actor_id']=='abc123'
    view=foundry_link_for_character(s,char['id']);assert view['name']=='Aster' and view['sheet']['skills'][0]['label']=='occultism'
    assert foundry_link(s,char['id'],cid,'') is None and foundry_link_for_character(s,char['id']) is None


def test_v61_public_foundry_manifest_and_install_zip(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s)
    import shutil
    src=Path(__file__).resolve().parents[1]/'integrations'/'foundry-seeker-bridge'
    dst=s.root_dir/'integrations'/'foundry-seeker-bridge';dst.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(src,dst)
    monkeypatch.setattr(main,'settings',s)
    client=TestClient(main.app)
    manifest=client.get('/foundry/seeker-bridge/module.json')
    assert manifest.status_code==200
    data=manifest.json();assert data['id']=='seeker-bridge' and data['version']=='1.1.2'
    assert data['manifest'].endswith('/foundry/seeker-bridge/module.json')
    assert data['download'].endswith('/foundry/seeker-bridge/seeker-bridge.zip')
    package=client.get('/foundry/seeker-bridge/seeker-bridge.zip')
    assert package.status_code==200 and package.headers['content-type'].startswith('application/zip')
    out=tmp_path/'module.zip';out.write_bytes(package.content)
    with zipfile.ZipFile(out) as zf:
        names=set(zf.namelist());assert {'module.json','seeker-bridge.mjs'} <= names
        inside=json.loads(zf.read('module.json'))
        assert inside['manifest']==data['manifest'] and inside['download']==data['download']


def test_v61_player_character_renders_linked_foundry_sheet_but_not_to_other_player(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s);alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob');set_campaign_members(s,cid,[alice['id'],bob['id']])
    char=save_player_character(s,{'campaign_id':cid,'name':'Aster','visibility':'party'},invite_id=alice['id'])
    cfg=integration_config(s,cid,include_secret=True);foundry_accept(s,cid,cfg['foundry_bridge_token'],actor_payload());foundry_link(s,char['id'],cid,'abc123')
    pa=TestClient(main.app);assert pa.get(alice['invite_path'],follow_redirects=False).status_code==303
    own=pa.get(f'/characters/{char["id"]}');assert own.status_code==200
    assert 'LIVE FROM FOUNDRY' in own.text and 'Thaumaturge' in own.text and 'Diverse Lore' in own.text
    pb=TestClient(main.app);assert pb.get(bob['invite_path'],follow_redirects=False).status_code==303
    other=pb.get(f'/characters/{char["id"]}');assert other.status_code==200
    assert 'LIVE FROM FOUNDRY' not in other.text and 'Diverse Lore' not in other.text


def test_v61_discord_confirmed_date_uses_campaign_mention(tmp_path: Path, monkeypatch):
    import app.v6 as v6
    s=setup(tmp_path);cid=default_campaign_id(s)
    save_integration_config(s,cid,{
        'discord_webhook':'https://discord.invalid/api/webhooks/1/token','discord_enabled':True,
        'discord_mention':'<@&123456789>','discord_auto_session_confirmed':True,
    })
    captured={}
    class FakeResponse:
        status=204
        def __enter__(self):return self
        def __exit__(self,*args):return False
    def fake_open(req,timeout=0):
        captured['body']=json.loads(req.data.decode('utf-8'));captured['timeout']=timeout;return FakeResponse()
    monkeypatch.setattr(v6.urllib.request,'urlopen',fake_open)
    out=discord_session_confirmation(s,cid,{'id':2,'title':'The Moon Gate','session_date':'2026-10-03','status':'planned'},base_url='https://seeker.example')
    assert out['ok'] and captured['body']['content'].startswith('<@&123456789>\n📅 **Session confirmed')
    assert 'Saturday, 3 October 2026' in captured['body']['content'] and 'https://seeker.example/session' in captured['body']['content']
    assert 'roles' in captured['body']['allowed_mentions']['parse']


def test_v61_session_save_triggers_discord_only_when_date_is_new_or_changed(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    calls=[]
    monkeypatch.setattr(main,'discord_session_confirmation',lambda settings,cid,session,base_url='': calls.append((cid,session['session_date'])) or {'ok':True})
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    first=gm.post('/api/admin/sessions',json={'title':'Next Session','session_date':'2026-10-04','status':'planned'});assert first.status_code==200
    row=first.json();assert calls==[(row['campaign_id'],'2026-10-04')]
    second=gm.post('/api/admin/sessions',json={**row,'title':'Renamed only'});assert second.status_code==200 and len(calls)==1
    third=gm.post('/api/admin/sessions',json={**second.json(),'session_date':'2026-10-11'});assert third.status_code==200 and calls[-1][1]=='2026-10-11' and len(calls)==2


def test_v61_scroll_contract_and_foundry_frontend_assets():
    root=Path(__file__).resolve().parents[1]
    admin=(root/'static/admin.css').read_text(encoding='utf-8')
    wiki=(root/'static/wiki.css').read_text(encoding='utf-8')
    base=(root/'templates/base.html').read_text(encoding='utf-8')
    integrations=(root/'templates/gm_integrations.html').read_text(encoding='utf-8')
    chars=(root/'static/characters.js').read_text(encoding='utf-8')
    sw=(root/'static/sw.js').read_text(encoding='utf-8')
    assert 'html,body{margin:0;height:100%;overflow:hidden' not in admin
    assert '.admin-body{height:100dvh;overflow:hidden}' in admin
    assert 'body:not(.table-display):not(.admin-body)' in wiki and 'overflow-y:auto' in wiki
    assert 'mobile-more-sheet{max-height:calc(100dvh - 16px);overflow-y:auto' in wiki
    assert 'data-foundry-manifest' in integrations and 'Automatically announce confirmed session dates' in integrations
    assert '/api/v61/characters/' in chars and 'data-foundry-tab' in chars
    assert 'data-notification-pref="spotlight"' not in base
    assert 'seeker-static-v6100' in sw


def test_v61_public_urls_respect_railway_https(tmp_path: Path, monkeypatch):
    import app.main as main
    import shutil
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    src=Path(__file__).resolve().parents[1]/'integrations'/'foundry-seeker-bridge'
    dst=s.root_dir/'integrations'/'foundry-seeker-bridge';dst.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(src,dst)
    monkeypatch.setenv('RAILWAY_PUBLIC_DOMAIN','seeker.example')
    client=TestClient(main.app)
    manifest=client.get('/foundry/seeker-bridge/module.json').json()
    assert manifest['manifest']=='https://seeker.example/foundry/seeker-bridge/module.json'
    assert manifest['download']=='https://seeker.example/foundry/seeker-bridge/seeker-bridge.zip'
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    page=gm.get('/gm/integrations')
    assert page.status_code==200
    assert 'https://seeker.example/api/v6/foundry/push/' in page.text
    assert 'https://seeker.example/calendar-feed/' in page.text


def test_v61_foundry_bridge_has_connection_diagnostics_and_https_repair():
    root=Path(__file__).resolve().parents[1]
    bridge=(root/'integrations/foundry-seeker-bridge/seeker-bridge.mjs').read_text(encoding='utf-8')
    assert 'const BRIDGE_VERSION = "1.1.2"' in bridge
    assert 'function normalizedEndpoint' in bridge
    assert 'u.protocol === "http:" && !local' in bridge
    assert 'Seeker Bridge connected' in bridge
    assert 'Seeker Bridge cannot reach Seeker' in bridge
    assert 'Could not serialize actor' in bridge


def test_v61_foundry_push_errors_keep_cors_headers(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s)
    client=TestClient(main.app)
    bad=client.post(f'/api/v6/foundry/push/{cid}?token=wrong',json={'world':{},'scene':{},'actors':[]})
    assert bad.status_code==403
    assert bad.headers.get('access-control-allow-origin')=='*'
    assert 'Invalid Foundry bridge token' in bad.text


def test_v611_request_host_beats_secondary_railway_domain(tmp_path: Path, monkeypatch):
    import app.main as main
    import shutil
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    src=Path(__file__).resolve().parents[1]/'integrations'/'foundry-seeker-bridge'
    dst=s.root_dir/'integrations'/'foundry-seeker-bridge';dst.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(src,dst)
    monkeypatch.delenv('SEEKER_PUBLIC_URL',raising=False)
    monkeypatch.setenv('RAILWAY_ENVIRONMENT','production')
    monkeypatch.setenv('RAILWAY_PUBLIC_DOMAIN','seeker-default.up.railway.app')
    client=TestClient(main.app)
    headers={'host':'seeker.up.railway.app','x-forwarded-host':'seeker.up.railway.app','x-forwarded-proto':'https'}
    manifest=client.get('/foundry/seeker-bridge/module.json',headers=headers).json()
    assert manifest['manifest']=='https://seeker.up.railway.app/foundry/seeker-bridge/module.json'
    assert manifest['download']=='https://seeker.up.railway.app/foundry/seeker-bridge/seeker-bridge.zip'
    package=client.get('/foundry/seeker-bridge/seeker-bridge.zip',headers=headers)
    out=tmp_path/'bridge.zip';out.write_bytes(package.content)
    with zipfile.ZipFile(out) as zf:
        bridge=zf.read('seeker-bridge.mjs').decode('utf-8')
        assert 'const BUNDLED_SEEKER_ORIGIN = "https://seeker.up.railway.app";' in bridge
        assert '__SEEKER_PUBLIC_ORIGIN__' not in bridge


def test_v611_explicit_public_url_still_wins(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    monkeypatch.setenv('SEEKER_PUBLIC_URL','https://seeker.up.railway.app/')
    monkeypatch.setenv('RAILWAY_PUBLIC_DOMAIN','other.up.railway.app')
    client=TestClient(main.app)
    manifest=client.get('/foundry/seeker-bridge/module.json',headers={'host':'wrong.example'}).json()
    assert manifest['manifest'].startswith('https://seeker.up.railway.app/')


def test_v611_archive_mode_does_not_block_foundry_heartbeat():
    root=Path(__file__).resolve().parents[1]
    main=(root/'app/main.py').read_text(encoding='utf-8')
    assert '"/api/v6/foundry/push/"' in main
    bridge=(root/'integrations/foundry-seeker-bridge/seeker-bridge.mjs').read_text(encoding='utf-8')
    assert 'BUNDLED_SEEKER_ORIGIN' in bridge and 'canonical.host' in bridge
