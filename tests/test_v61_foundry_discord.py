from __future__ import annotations

import json
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

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
    claim_foundry_commands,
    complete_foundry_commands,
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
    assert foundry_accept(s,cid,cfg['foundry_bridge_token'],actor_payload())=={'ok':True,'actors':1,'commands':[]}
    actors=foundry_actors(s,cid);assert actors[0]['name']=='Aster' and actors[0]['sheet']['vitals']['ac']==26
    inv=create_player_invite(s,'Alice');set_campaign_members(s,cid,[inv['id']])
    char=save_player_character(s,{'campaign_id':cid,'name':'Aster'},invite_id=inv['id'])
    linked=foundry_link(s,char['id'],cid,'abc123');assert linked['actor_id']=='abc123'
    view=foundry_link_for_character(s,char['id']);assert view['name']=='Aster' and view['sheet']['skills'][0]['label']=='Occultism'
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
    data=manifest.json();assert data['id']=='seeker-bridge' and data['version']=='1.11.0'
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
    assert captured['body']['allowed_mentions']['roles']==['123456789']
    assert 'roles' not in captured['body']['allowed_mentions']['parse']

    save_integration_config(s,cid,{'discord_webhook':'https://discord.invalid/api/webhooks/1/token','discord_enabled':True,'discord_mention':'everyone','discord_auto_session_confirmed':True})
    discord_session_confirmation(s,cid,{'id':3,'title':'The Gate Opens','session_date':'2026-10-10','status':'planned'})
    assert captured['body']['content'].startswith('@everyone\n')
    assert 'everyone' in captured['body']['allowed_mentions']['parse']


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
    assert 'seeker-static-v9003' in sw


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
    assert 'const BRIDGE_VERSION = "1.11.0"' in bridge
    assert 'function normalizedEndpoint' in bridge
    assert 'u.protocol === "http:" && !local' in bridge
    assert 'processCommands(endpoint, body?.commands || [])' in bridge
    assert 'Seeker Bridge connected' in bridge
    assert 'Seeker Bridge cannot reach Seeker' in bridge
    assert 'Could not serialize actor' in bridge
    assert 'foundry.utils.slugify' not in bridge
    assert 'function seekerSlugify' in bridge
    assert 'setupCommandInterval' in bridge and '2000' in bridge


def test_v61_foundry_push_errors_keep_cors_headers(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s)
    client=TestClient(main.app)
    bad=client.post(f'/api/v6/foundry/push/{cid}?token=wrong',json={'world':{},'scene':{},'actors':[]})
    assert bad.status_code==403
    assert bad.headers.get('access-control-allow-origin')=='*'
    assert 'Invalid Foundry bridge token' in bad.text


def test_v612_workshop_and_safe_foundry_commands(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s);cfg=integration_config(s,cid,include_secret=True)
    alice=create_player_invite(s,'Alice');set_campaign_members(s,cid,[alice['id']])
    char=save_player_character(s,{'campaign_id':cid,'name':'Aster','visibility':'party'},invite_id=alice['id'])
    foundry_accept(s,cid,cfg['foundry_bridge_token'],actor_payload());foundry_link(s,char['id'],cid,'abc123')

    player=TestClient(main.app); assert player.get(alice['invite_path'],follow_redirects=False).status_code==303
    safe=player.post(f'/api/v61/characters/{char["id"]}/foundry/action',json={'action':'adjust_resource','resource':'hero_points','delta':1})
    assert safe.status_code==200 and safe.json()['command']['command_type']=='adjust_resource'
    pending=claim_foundry_commands(s,cid,cfg['foundry_bridge_token'])
    assert pending and pending[0]['payload']['resource']=='hero_points'
    assert pending[0]['payload']['command_nonce']
    assert complete_foundry_commands(s,cid,cfg['foundry_bridge_token'],[{'id':pending[0]['id'],'status':'done','result':{'message':'ok'}}])['ok']

    # Large HP adjustments and absolute edits are intentional: high-level/homebrew
    # actors can have hundreds of HP and should not require dozens of clicks.
    big=player.post(f'/api/v61/characters/{char["id"]}/foundry/action',json={'action':'adjust_resource','resource':'hp','delta':-100})
    direct=player.post(f'/api/v61/characters/{char["id"]}/foundry/action',json={'action':'set_resource','resource':'hp','value':347})
    assert big.status_code==200 and direct.status_code==200
    more=claim_foundry_commands(s,cid,cfg['foundry_bridge_token'])
    payloads=[c['payload'] for c in more if c['command_type']=='adjust_resource']
    assert any(p.get('mode')=='adjust' and p.get('delta')==-100 for p in payloads)
    assert any(p.get('mode')=='set' and p.get('value')==347 for p in payloads)
    assert len({p.get('command_nonce') for p in payloads})==len(payloads)

    gm=TestClient(main.app); assert gm.post('/admin/login',data={'password':'admin'}).status_code in {200,303}
    workshop=gm.get('/gm/foundry-workshop'); assert workshop.status_code==200
    assert 'Homebrew Forge' in workshop.text and 'foundryWorkshopForm' in workshop.text
    assert 'foundryLivePreview' in workshop.text and '/static/foundry-workshop.css?v=9003' in workshop.text
    created=gm.post('/api/v61/foundry/content',json={'kind':'item','target_type':'actor','title':'Moon Key','summary':'Opens a silver gate.','payload':{'item_type':'equipment','traits':'magical, occult','quantity':1}})
    assert created.status_code==200
    pushed=gm.post(f"/api/v61/foundry/content/{created.json()['id']}/push",json={'target_type':'actor','actor_id':'abc123'})
    assert pushed.status_code==200 and pushed.json()['command']['command_type']=='grant_prepared_content'
    queued=claim_foundry_commands(s,cid,cfg['foundry_bridge_token'])
    assert any(cmd['command_type']=='grant_prepared_content' and cmd['actor_id']=='abc123' for cmd in queued)


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


def test_v613_structured_pf2e_import_contract_and_token_support():
    root=Path(__file__).resolve().parents[1]
    bridge=(root/'integrations/foundry-seeker-bridge/seeker-bridge.mjs').read_text(encoding='utf-8')
    workshop=(root/'templates/gm_foundry_workshop.html').read_text(encoding='utf-8')
    js=(root/'static/foundry-workshop.js').read_text(encoding='utf-8')
    assert 'type: "melee"' in bridge and 'damageRolls' in bridge and 'attackEffects' in bridge
    assert 'type: "action"' in bridge and 'actionType' in bridge and 'buildNpcAbility' in bridge
    assert 'type: "spellcastingEntry"' in bridge and 'buildPreparedSpell' in bridge and 'findCompendiumSpell' in bridge
    assert 'prototypeToken' in bridge and 'data.token_img || data.img' in bridge
    assert 'data-fw-token-maker' in workshop and 'data-fw-token-canvas' in workshop
    assert 'data-fw-spells' in workshop and 'data-fw-add-spell' in workshop
    assert "payload.codex_publish" in js and 'token_img' in js
    assert 'data-fw-art-crop' in workshop and 'data-fw-crop-canvas' in workshop
    assert '/api/v61/foundry/assets/import' in js and 'ensureEditableArt' in js
    assert 'weapon_damage_dice' in workshop and 'weapon_group' in workshop and 'weapon_reload' in workshop
    assert 'system.damage' in bridge and 'system.group' in bridge and 'system.runes' in bridge
    assert 'commandsEndpoint' in bridge and 'queuePush(120)' in bridge
    assert 'npcAttackPatch' in bridge and 'system.damageRolls' in bridge
    assert 'spellcastingPatch' in bridge and 'system.spelldc.value' in bridge and 'system.spelldc.dc' in bridge
    assert 'addSpellToEntry' in bridge and 'source_uuid' in js
    assert 'data-ability-dc-type' in js and 'data-ability-cost' in js and 'frequency_per' in js
    assert workshop.count('data-token-preset=') >= 30
    assert 'data-token-pattern' in workshop and 'data-token-vignette' in workshop


def test_v613_bestiary_visibility_and_asset_upload(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s);alice=create_player_invite(s,'Alice');set_campaign_members(s,cid,[alice['id']])
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    rough=gm.post('/api/v61/foundry/content',json={
        'kind':'monster','target_type':'world','title':'Ashen Warden','subtitle':'Secret elite guardian',
        'summary':'A burning guardian.','payload':{'level':'7','traits':'fire, humanoid','ac':'25','hp':'100','codex_publish':True,'codex_visibility':'rough','codex_category':'Cinderborn','codex_blurb':'A hulking guardian wreathed in ash.'}
    })
    assert rough.status_code==200
    full=gm.post('/api/v61/foundry/content',json={
        'kind':'monster','target_type':'world','title':'Glass Hound','summary':'A crystal predator.',
        'payload':{'level':'3','ac':'19','hp':'45','codex_publish':True,'codex_visibility':'full','codex_blurb':'A translucent hunting beast.'}
    })
    assert full.status_code==200
    from PIL import Image
    import io
    image=Image.new('RGB',(1800,1200),(120,80,45));raw=io.BytesIO();image.save(raw,format='PNG');source=raw.getvalue()
    upload=gm.post('/api/v61/foundry/assets',files={'image':('token.png',source,'image/png')},data={'kind':'token'})
    assert upload.status_code==200 and '/uploads/foundry/' in upload.json()['url'] and upload.json()['url'].endswith('.webp')
    assert upload.json()['width']<=1024 and upload.json()['height']<=1024 and upload.json()['bytes']<len(source)
    duplicate=gm.post('/api/v61/foundry/assets',files={'image':('token-copy.png',source,'image/png')},data={'kind':'token'})
    assert duplicate.status_code==200 and duplicate.json()['url']==upload.json()['url'] and duplicate.json()['deduplicated'] is True
    with_art=gm.post('/api/v61/foundry/content',json={
        'kind':'monster','target_type':'world','title':'Token Beast','payload':{'hp':'10','img':upload.json()['url'],'token_img':upload.json()['url']}
    })
    assert with_art.status_code==200
    pushed=gm.post(f"/api/v61/foundry/content/{with_art.json()['id']}/push",json={'target_type':'world'})
    assert pushed.status_code==200
    cfg=integration_config(s,cid,include_secret=True);queued=claim_foundry_commands(s,cid,cfg['foundry_bridge_token'])
    pushed_data=next(cmd for cmd in queued if cmd['payload'].get('title')=='Token Beast')['payload']['data']
    assert '/api/v6/foundry/asset/' in pushed_data['img'] and '?sig=' in pushed_data['img']
    signed=urlsplit(pushed_data['img']);public_asset=TestClient(main.app).get(signed.path+'?'+signed.query)
    assert public_asset.status_code==200

    player=TestClient(main.app);assert player.get(alice['invite_path'],follow_redirects=False).status_code==303
    listing=player.get('/bestiary');assert listing.status_code==200 and 'Ashen Warden' in listing.text and 'Glass Hound' in listing.text
    assert 'Secret elite guardian' not in listing.text
    rough_page=player.get(f"/bestiary/{rough.json()['id']}");assert rough_page.status_code==200
    assert 'Field notes only.' in rough_page.text and '<strong>AC</strong> 25' not in rough_page.text and 'Secret elite guardian' not in rough_page.text
    full_page=player.get(f"/bestiary/{full.json()['id']}");assert full_page.status_code==200 and '<b>AC</b><strong>19</strong>' in full_page.text


def test_v614_remote_art_import_is_local_optimized_webp(tmp_path: Path, monkeypatch):
    import app.main as main
    from PIL import Image
    import io
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s)
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    image=Image.new('RGB',(2400,1600),(70,110,150));buf=io.BytesIO();image.save(buf,format='JPEG',quality=95);source=buf.getvalue()

    class FakeResponse(io.BytesIO):
        def __init__(self,data):
            super().__init__(data);self.headers={'Content-Type':'image/jpeg'}
        def geturl(self):return 'https://images.example.test/art.jpg'
        def __enter__(self):return self
        def __exit__(self,*args):self.close();return False
    class FakeOpener:
        def open(self,request,timeout=0):return FakeResponse(source)
    monkeypatch.setattr(main,'build_opener',lambda *a,**k:FakeOpener())
    monkeypatch.setattr(main.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])

    imported=gm.post('/api/v61/foundry/assets/import',json={'url':'https://images.example.test/art.jpg','kind':'art'})
    assert imported.status_code==200
    body=imported.json();assert body['url'].startswith('/uploads/foundry/') and body['url'].endswith('.webp')
    assert body['width']<=1600 and body['height']<=1600 and body['bytes']<len(source)
    local=gm.get(body['url']);assert local.status_code==200 and local.headers['content-type'].startswith('image/webp')


def test_v704_foundry_delivery_lifecycle_and_retry_state(tmp_path: Path):
    from app.v6 import queue_foundry_command, get_foundry_command, start_foundry_commands, retry_foundry_command
    s=setup(tmp_path);cid=default_campaign_id(s);cfg=integration_config(s,cid,include_secret=True);token=cfg['foundry_bridge_token']
    cmd=queue_foundry_command(s,cid,'adjust_resource',{'resource':'hp','delta':-1,'actor_uuid':'Actor.abc123'},actor_id='abc123',requested_by='GM')
    assert cmd['status']=='queued' and cmd['delivery_label']=='Waiting for Foundry' and cmd['attempt_count']==0
    claimed=claim_foundry_commands(s,cid,token);assert len(claimed)==1
    assert claimed[0]['status']=='dispatched' and claimed[0]['attempt_count']==1 and claimed[0]['delivery_label']=='Delivered to bridge'
    assert start_foundry_commands(s,cid,token,[cmd['id']])['started']==1
    applying=get_foundry_command(s,cid,cmd['id']);assert applying['status']=='executing' and applying['delivery_label']=='Applying in Foundry'
    assert complete_foundry_commands(s,cid,token,[{'id':cmd['id'],'status':'failed','result':{'message':'PF2e rejected test write'}}])['failed']==1
    failed=get_foundry_command(s,cid,cmd['id']);assert failed['can_retry'] and failed['last_error']=='PF2e rejected test write'
    retried=retry_foundry_command(s,cid,cmd['id']);assert retried['status']=='queued' and retried['attempt_count']==0 and not retried['last_error']
    claim_foundry_commands(s,cid,token);start_foundry_commands(s,cid,token,[cmd['id']])
    complete_foundry_commands(s,cid,token,[{'id':cmd['id'],'status':'done','result':{'message':'HP applied','after':71}}])
    done=get_foundry_command(s,cid,cmd['id']);assert done['status']=='done' and done['delivery_label']=='Applied' and done['result']['after']==71 and not done['can_retry']


def test_v704_foundry_bridge_actor_item_and_resource_contract():
    root=Path(__file__).resolve().parents[1]
    bridge=(root/'integrations/foundry-seeker-bridge/seeker-bridge.mjs').read_text(encoding='utf-8')
    table=(root/'static/v7-player.js').read_text(encoding='utf-8')
    chars=(root/'static/characters.js').read_text(encoding='utf-8')
    assert 'actor.createEmbeddedDocuments("Item", [source], { render: true })' in bridge
    assert 'Item.implementation.create(source, { parent: actor })' not in bridge
    assert 'resolveCommandActor' in bridge and 'actor_uuid' in bridge
    assert 'Foundry did not retain the requested' in bridge and 'Foundry did not retain the item' in bridge
    assert 'Could not mark command ${id} as executing' in bridge
    assert 'const result = await runFoundryCommand(command, endpoint);' in bridge
    helper=(root/'static/foundry-live.js').read_text(encoding='utf-8')
    assert '/api/v6/foundry/commands/' in helper and 'SeekerFoundryLive' in table and 'SeekerFoundryLive' in chars


def test_v704_discord_wait_response_verifies_real_mentions(tmp_path: Path, monkeypatch):
    import io
    import app.v6 as v6
    s=setup(tmp_path);cid=default_campaign_id(s)
    save_integration_config(s,cid,{'discord_webhook':'https://discord.invalid/api/webhooks/1/token','discord_enabled':True,'discord_mention':'@everyone'})
    captured={}
    class FakeResponse(io.BytesIO):
        status=200
        def __init__(self,obj):super().__init__(json.dumps(obj).encode())
        def __enter__(self):return self
        def __exit__(self,*args):return False
    def good_open(req,timeout=0):
        captured['url']=req.full_url;captured['body']=json.loads(req.data.decode());return FakeResponse({'mention_everyone':True,'mention_roles':[],'mentions':[]})
    monkeypatch.setattr(v6.urllib.request,'urlopen',good_open)
    out=v6.discord_post(s,cid,'@everyone\nSession starts now')
    assert out['ok'] and out['ping_ok'] and out['mention_everyone'] is True and 'wait=true' in captured['url']
    assert captured['body']['allowed_mentions']['parse']==['everyone']
    def denied_open(req,timeout=0):return FakeResponse({'mention_everyone':False,'mention_roles':[],'mentions':[]})
    monkeypatch.setattr(v6.urllib.request,'urlopen',denied_open)
    out=v6.discord_post(s,cid,'@everyone\nSession starts now')
    assert out['ok'] and not out['ping_ok'] and 'did not activate' in out['warning']


def test_v704_aon_chrome_sanitizer_rejects_navigation_dump():
    from app.aon import sanitize_aon_summary
    garbage='Home Actions/Activities Afflictions Ancestries Archetypes Backgrounds Classes Conditions Creatures Companions Familiars Equipment Feats Hazards Mythic Rules Setting Skills Spells/Rituals Traits Licenses Sources Contact Us Contributors Support the Archives Maximize Menu Archives of Nethys All Creatures Abilities | Monsters | NPCs Acolyte Of Pharasma This creature did not include a description. Elite | Normal |'
    cleaned=sanitize_aon_summary(garbage,title='Acolyte Of Pharasma')
    assert cleaned=='This creature did not include a description.'
    assert 'Home Actions/Activities' not in cleaned and 'Archives of Nethys' not in cleaned


def test_v704_monster_codex_inline_edit_and_remove_preserves_source(tmp_path: Path, monkeypatch):
    import app.main as main
    from app.v6 import save_foundry_prepared_content, list_foundry_prepared_content
    s=setup(tmp_path);seed_wiki(s);monkeypatch.setattr(main,'settings',s);cid=default_campaign_id(s)
    row=save_foundry_prepared_content(s,cid,{'kind':'monster','title':'Old Name','summary':'Old summary','payload':{'hp':20,'ac':17,'codex_publish':True,'codex_visibility':'full','attacks':[],'abilities':[],'spells':[]}})
    gm=TestClient(main.app);gm.post('/admin/login',data={'password':'admin'})
    page=gm.get('/bestiary');assert page.status_code==200 and 'Old Name' in page.text and 'Edit here' in page.text
    edited=gm.put(f"/api/bestiary/{row['id']}",json={'title':'New Name','summary':'Edited','payload':{'hp':33,'ac':19,'codex_visibility':'field_notes'}})
    assert edited.status_code==200 and edited.json()['title']=='New Name' and edited.json()['payload']['hp']==33
    removed=gm.delete(f"/api/bestiary/{row['id']}");assert removed.status_code==200 and removed.json()['source_preserved'] is True
    source=next(x for x in list_foundry_prepared_content(s,cid) if int(x['id'])==int(row['id']))
    assert source['title']=='New Name' and source['payload']['hp']==33 and source['payload']['codex_publish'] is False
    assert 'New Name' not in gm.get('/bestiary').text


def test_v710_foundry_ack_immediately_projects_resource_snapshot(tmp_path: Path):
    from app.v6 import queue_foundry_command, start_foundry_commands
    s=setup(tmp_path);cid=default_campaign_id(s);cfg=integration_config(s,cid,include_secret=True);token=cfg['foundry_bridge_token']
    assert foundry_accept(s,cid,token,actor_payload())['ok']
    inv=create_player_invite(s,'Alice');set_campaign_members(s,cid,[inv['id']])
    char=save_player_character(s,{'campaign_id':cid,'name':'Aster'},invite_id=inv['id']);foundry_link(s,char['id'],cid,'abc123')
    cmd=queue_foundry_command(s,cid,'adjust_resource',{'resource':'hp','delta':-7,'character_id':char['id'],'character_name':'Aster','actor_uuid':'Actor.abc123'},actor_id='abc123',requested_by='Alice')
    claim_foundry_commands(s,cid,token);start_foundry_commands(s,cid,token,[cmd['id']])
    complete_foundry_commands(s,cid,token,[{'id':cmd['id'],'status':'done','result':{'message':'HP applied','after':65}}])
    fresh=foundry_link_for_character(s,char['id'])
    assert fresh['sheet']['vitals']['hp']['value']==65


def test_v710_foundry_ack_immediately_projects_item_quantity(tmp_path: Path):
    from app.v6 import queue_foundry_command, start_foundry_commands
    s=setup(tmp_path);cid=default_campaign_id(s);cfg=integration_config(s,cid,include_secret=True);token=cfg['foundry_bridge_token']
    payload=actor_payload();payload['actors'][0]['sheet']['inventory'][0]['id']='lantern1';payload['actors'][0]['sheet']['inventory'][0]['quantity']=3
    foundry_accept(s,cid,token,payload)
    inv=create_player_invite(s,'Alice');set_campaign_members(s,cid,[inv['id']])
    char=save_player_character(s,{'campaign_id':cid,'name':'Aster'},invite_id=inv['id']);foundry_link(s,char['id'],cid,'abc123')
    cmd=queue_foundry_command(s,cid,'adjust_item_quantity',{'item_id':'lantern1','delta':-1,'character_id':char['id'],'character_name':'Aster','actor_uuid':'Actor.abc123'},actor_id='abc123',requested_by='Alice')
    claim_foundry_commands(s,cid,token);start_foundry_commands(s,cid,token,[cmd['id']])
    complete_foundry_commands(s,cid,token,[{'id':cmd['id'],'status':'done','result':{'message':'Quantity applied','after':2}}])
    inv_rows=foundry_link_for_character(s,char['id'])['sheet']['inventory']
    assert next(x for x in inv_rows if x.get('id')=='lantern1')['quantity']==2


def test_v710_foundry_state_endpoint_is_owner_scoped_and_fresh(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    cid=default_campaign_id(s);alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob');set_campaign_members(s,cid,[alice['id'],bob['id']])
    char=save_player_character(s,{'campaign_id':cid,'name':'Aster','visibility':'party'},invite_id=alice['id'])
    cfg=integration_config(s,cid,include_secret=True);foundry_accept(s,cid,cfg['foundry_bridge_token'],actor_payload());foundry_link(s,char['id'],cid,'abc123')
    pa=TestClient(main.app);assert pa.get(alice['invite_path'],follow_redirects=False).status_code==303
    own=pa.get(f'/api/v61/characters/{char["id"]}/foundry-state');assert own.status_code==200 and own.json()['sheet']['vitals']['hp']['value']==72
    pb=TestClient(main.app);assert pb.get(bob['invite_path'],follow_redirects=False).status_code==303
    other=pb.get(f'/api/v61/characters/{char["id"]}/foundry-state');assert other.status_code in {403,404}


def test_v710_live_foundry_frontend_contract_uses_shared_reconciler():
    root=Path(__file__).resolve().parents[1]
    helper=(root/'static/foundry-live.js').read_text(encoding='utf-8')
    table=(root/'static/v7-player.js').read_text(encoding='utf-8')
    chars=(root/'static/characters.js').read_text(encoding='utf-8')
    assert '/api/v6/foundry/commands/' in helper and '/foundry-state' in helper
    assert 'SeekerFoundryLive' in table and 'SeekerFoundryLive' in chars
    assert 'beginResource' in table and 'beginResource' in chars
    assert 'commit' in table and 'rollback' in table and 'commit' in chars and 'rollback' in chars
    assert 'live?.refresh()' in table and 'foundryLive?.refresh()' in chars


def test_v742_mobile_navigation_and_table_live_refresh_contract():
    root=Path(__file__).resolve().parents[1]
    base=(root/'templates/base.html').read_text(encoding='utf-8')
    css=(root/'static/refinement.css').read_text(encoding='utf-8')
    table=(root/'static/v7-player.js').read_text(encoding='utf-8')
    live=(root/'static/foundry-live.js').read_text(encoding='utf-8')
    # The critical table launcher is pinned before collapsible secondary groups,
    # rather than being buried at one end of an unbounded mobile menu.
    assert 'class="mobile-sheet-feature" href="/app"' in base
    assert base.index('class="mobile-sheet-feature" href="/app"') < base.index('class="mobile-sheet-group"')
    assert 'data-mobile-more-close' in base and 'mobile-sheet-primary' in base
    assert 'max-height:calc(100dvh - 88px - env(safe-area-inset-top))' in css
    # Table App reconciles against the same Foundry snapshot periodically and
    # cross-tab notifications make same-browser character edits effectively immediate.
    assert 'setInterval(refreshLive,2500)' in table
    assert 'visibilitychange' in table and "window.addEventListener('focus',refreshLive)" in table
    assert 'BroadcastChannel' in live and 'seeker-foundry-live' in live and 'notify()' in live
    assert 'data-player-set-resource' in table
