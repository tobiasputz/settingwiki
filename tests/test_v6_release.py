from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.storage import init_db, create_player_invite, connect
from app.features import init_feature_db, save_session
from app.campaigns import default_campaign_id, save_campaign, set_campaign_members
from app.maps import create_map, create_marker
from app.living import set_knowledge
from app.v6 import (
    init_v6_db, integration_config, save_integration_config, foundry_accept, foundry_state,
    calendar_feed, session_ics, sync_lore_revisions, lore_revisions, lore_revision_diff,
    knowledge_matrix, converge_campaigns, save_map_annotation, list_map_annotations,
    record_travel_leg, travel_legs, save_media_item, set_display_state, display_state,
    create_backup, list_backups, campaign_keepsake, command_rows,
)


def settings_for(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def setup(tmp_path: Path) -> Settings:
    s=settings_for(tmp_path);init_db(s);init_feature_db(s);init_v6_db(s);return s


def test_v6_release_identity_and_assets():
    root=Path(__file__).resolve().parents[1]
    assert (root/'VERSION').read_text().strip()=='7.0.4'
    sw=(root/'static/sw.js').read_text(encoding='utf-8')
    assert 'seeker-static-v7040' in sw
    shipped='\n'.join((root/'templates'/name).read_text(encoding='utf-8') for name in ['gm_continuity.html','gm_integrations.html','gm_media.html','display.html','lore_history.html'])
    assert '/static/v6.js?v=7040' in shipped
    for name in ['gm_continuity.html','gm_integrations.html','gm_media.html','display.html','lore_history.html']:
        assert (root/'templates'/name).exists()
    foundry=root/'integrations'/'foundry-seeker-bridge'
    assert (foundry/'module.json').exists() and any(foundry.glob('*.mjs'))


def test_v6_schema_is_additive_and_tokens_are_stable(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    with connect(s) as conn:
        tables={r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'campaign_integrations','foundry_bridge_state','lore_page_revisions','campaign_map_annotations','campaign_travel_legs','session_media_items','campaign_display_state','campaign_convergences','v6_backup_catalog'} <= tables
    first=integration_config(s,cid,include_secret=True);second=integration_config(s,cid,include_secret=True)
    assert first['foundry_bridge_token']==second['foundry_bridge_token']
    assert first['calendar_token']==second['calendar_token']
    assert first['display_token']==second['display_token']
    rotated=save_integration_config(s,cid,{'rotate_calendar_token':True})
    assert rotated['calendar_token']!=first['calendar_token']


def test_foundry_bridge_and_calendar_are_token_protected(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s);cfg=integration_config(s,cid,include_secret=True)
    with pytest.raises(PermissionError):
        foundry_accept(s,cid,'wrong',{})
    assert foundry_accept(s,cid,cfg['foundry_bridge_token'],{'scene':{'id':'abc','name':'Moon Gate'},'world':{'title':'Kiragon'},'actors':[{'id':'a','name':'Aster'}]})['ok']
    state=foundry_state(s,cid);assert state['scene_name']=='Moon Gate' and state['payload']['actors'][0]['name']=='Aster'
    sess=save_session(s,{'campaign_id':cid,'title':'The Moon Gate','session_date':'2026-10-03','status':'planned','summary':'Meet at dusk.'})
    with pytest.raises(PermissionError):calendar_feed(s,cid,'wrong')
    feed=calendar_feed(s,cid,cfg['calendar_token'],'https://example.test')
    assert 'BEGIN:VCALENDAR' in feed and 'SUMMARY:The Moon Gate' in feed and '20261003' in feed
    one=session_ics(sess,'Main Campaign','https://example.test');assert 'UID:seeker-session-' in one and 'SUMMARY:The Moon Gate' in one


def test_lore_revision_history_and_diff(tmp_path: Path):
    s=setup(tmp_path)
    wiki1={'generated_at':100.0,'pages':[{'slug':'corvina','title':'Corvina','chapter':'People','source_file':'main.tex','source_line':10,'html':'<p>A courier.</p>','plain_text':'A courier.','presentation':{}}]}
    wiki2={'generated_at':200.0,'pages':[{'slug':'corvina','title':'Corvina','chapter':'People','source_file':'main.tex','source_line':10,'html':'<p>A courier with a secret.</p>','plain_text':'A courier with a secret.','presentation':{}}]}
    assert sync_lore_revisions(s,wiki1)==1
    assert sync_lore_revisions(s,wiki2)==1
    rows=lore_revisions(s,'corvina');assert len(rows)==2
    older=rows[-1]
    diff=lore_revision_diff(s,'corvina',older['id'])
    assert 'secret' in diff['diff'] and diff['revision']['id']==older['id']


def test_cross_campaign_knowledge_matrix_and_convergence(tmp_path: Path):
    s=setup(tmp_path);a=default_campaign_id(s);b=save_campaign(s,{'name':'Second Table'})['id'];inv=create_player_invite(s,'Alice')
    set_campaign_members(s,a,[inv['id']]);set_campaign_members(s,b,[inv['id']])
    set_knowledge(s,inv['id'],'page','hollow-duchess','known',campaign_id=b)
    matrix=knowledge_matrix(s);row=next(r for r in matrix['rows'] if r['slug']=='hollow-duchess');assert int(b) in {int(k) for k in row['states'].keys()}
    out=converge_campaigns(s,a,[b],{'knowledge':True,'reveals':False,'discoveries':False,'objectives':False,'memberships':False})
    assert out['summary']['knowledge']==1
    with connect(s) as conn:
        copied=conn.execute("SELECT state FROM player_knowledge WHERE campaign_id=? AND invite_id=? AND target_key='hollow-duchess'",(a,inv['id'])).fetchone()
    assert copied and copied['state']=='known'


def test_atlas_annotations_travel_media_and_display(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s);inv1=create_player_invite(s,'Alice');inv2=create_player_invite(s,'Bob')
    m=create_map(s,'World','world.jpg');a=create_marker(s,m['id'],{'title':'North Gate','x':.2,'y':.3});b=create_marker(s,m['id'],{'title':'Old Keep','x':.8,'y':.7})
    private=save_map_annotation(s,cid,m['id'],inv1['id'],'Alice',{'title':'My theory','x':.4,'y':.5,'visibility':'private'})
    shared=save_map_annotation(s,cid,m['id'],inv2['id'],'Bob',{'title':'Camp','x':.5,'y':.5,'visibility':'party'})
    aview=list_map_annotations(s,cid,m['id'],inv1['id']);assert {x['id'] for x in aview}=={private['id'],shared['id']}
    bview=list_map_annotations(s,cid,m['id'],inv2['id']);assert private['id'] not in {x['id'] for x in bview}
    leg=record_travel_leg(s,cid,m['id'],{'from_marker_id':a['id'],'to_marker_id':b['id'],'note':'Through the rain'})
    assert travel_legs(s,cid,m['id'])[0]['route']==[[.2,.3],[.8,.7]] and leg['from_label']=='North Gate'
    sess=save_session(s,{'campaign_id':cid,'title':'Road','status':'planned'})
    media=save_media_item(s,cid,sess['id'],{'title':'The Keep','kind':'image','source_url':'/project-asset/keep.jpg'})
    state=set_display_state(s,cid,{'media_item_id':media['id']});assert state['title']=='The Keep' and display_state(s,cid)['media_item_id']==media['id']


def test_backup_keepsake_and_command_palette(tmp_path: Path):
    s=setup(tmp_path);cid=default_campaign_id(s)
    (s.project_dir/'main.tex').write_text('\\documentclass{book}\\begin{document}Hello\\end{document}',encoding='utf-8')
    b=create_backup(s,'Before test');assert Path(b['path']).exists() and list_backups(s)[0]['id']==b['id']
    out=campaign_keepsake(s,cid,s.build_dir/'keepsake.zip');assert out.exists()
    import zipfile
    with zipfile.ZipFile(out) as z:assert {'campaign-chronicle.html','campaign-data.json'} <= set(z.namelist())
    rows=command_rows(s,'continuity',cid,gm=True,wiki={'pages':[]});assert rows and rows[0]['href']=='/gm/continuity'
    player=command_rows(s,'integrations',cid,gm=False,wiki={'pages':[]});assert not player

def test_v6_http_pages_smoke(tmp_path: Path, monkeypatch):
    import app.main as main
    from fastapi.testclient import TestClient
    from app.latex import build_wiki
    s=setup(tmp_path)
    (s.project_dir/'main.tex').write_text(r'\documentclass{book}\begin{document}\chapter{People}\section{Corvina}A courier.\end{document}',encoding='utf-8')
    build_wiki(s)
    monkeypatch.setattr(main,'settings',s)
    gm=TestClient(main.app); assert gm.post('/admin/login',data={'password':'admin'}).status_code in {200,303}
    for path in ['/gm/continuity','/gm/integrations','/gm/media','/display']:
        r=gm.get(path); assert r.status_code==200, (path,r.status_code,r.text[:300])
