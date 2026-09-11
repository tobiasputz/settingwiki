from test_compendium import setup, seed, gm_client
from fastapi.testclient import TestClient
from app.handout_creator import PRESETS, normalize, render_body, metadata
from app.features import save_handout
from app.campaigns import default_campaign_id, save_campaign


def document(**overrides):
    d={'preset':'letter','theme':'ivory','heading':'Dear travelers','body':'First paragraph.\n\nSecond paragraph.','subtitle':'Harvest moon','signature':'The steward','seal':'✦','gm_notes':'SECRET TRAITOR','folder':'Act I'}
    return {'title':'Royal Letter','design':d,'visibility':'gm',**overrides}


def test_presets_render_safely():
    assert len(PRESETS)>=30
    for preset in PRESETS:
        d=normalize({**preset,'preset':preset['id'],'theme':'parchment','body':'<script>alert(1)</script>'})
        html=render_body(d)
        assert '<script>' not in html and '&lt;script&gt;' in html
        assert 'gm_notes' not in html


def test_workshop_roundtrip_visibility_exports_and_delete(tmp_path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed(s);monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s)
    assert gm.get('/gm/handouts').status_code==200
    made=gm.post('/api/admin/handouts',json=document());assert made.status_code==200,made.text
    row=made.json();hid=row['id'];url='/handout/'+row['slug']
    assert metadata(s,hid)['gm_notes']=='SECRET TRAITOR'
    from app.storage import create_player_invite, set_setting
    from app.campaigns import set_campaign_members
    set_setting(s,"player_access_mode","invite")
    invite=create_player_invite(s,"Reader");set_campaign_members(s,default_campaign_id(s),[invite["id"]])
    public=TestClient(main.app);public.get(invite["invite_path"],follow_redirects=False)
    assert public.get('/gm/handouts').status_code in {401,403}
    assert public.get('/api/admin/handout-creator').status_code in {401,403}
    assert public.get(url).status_code==404
    assert public.get(url+'/export').status_code==404
    preview=gm.post('/api/admin/handout-creator/preview',json=document())
    assert preview.status_code==200 and 'SECRET TRAITOR' not in preview.text and 'theme-ivory' in preview.text
    updated=gm.post('/api/admin/handouts',json=document(id=hid,title='Changed title',visibility='players'))
    assert updated.status_code==200 and updated.json()['slug']==row['slug']
    for path in [url,url+'/export','/handouts']:
        page=public.get(path);assert page.status_code==200,page.text
        assert 'SECRET TRAITOR' not in page.text
    expired=gm.post('/api/admin/handouts',json=document(id=hid,visibility='players',expires_at=1));assert expired.status_code==200
    assert public.get(url+'/export').status_code==404
    assert gm.delete('/api/admin/handouts/'+str(hid)).status_code==200
    assert metadata(s,hid) is None and gm.get(url).status_code==404


def test_campaign_scope_and_duplicate_titles(tmp_path,monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed(s);monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s)
    other=save_campaign(s,{'name':'Other table'})
    foreign=save_handout(s,{'campaign_id':other['id'],'title':'Foreign secret','visibility':'gm'})
    assert gm.post('/api/admin/handouts',json=document(id=foreign['id'])).status_code==404
    assert gm.delete('/api/admin/handouts/'+str(foreign['id'])).status_code==404
    one=gm.post('/api/admin/handouts',json=document(campaign_id=other['id']));two=gm.post('/api/admin/handouts',json=document())
    assert one.status_code==two.status_code==200
    assert one.json()['campaign_id']==default_campaign_id(s)
    assert one.json()['slug']!=two.json()['slug']
    assert gm.post('/api/admin/handouts',json=document(session_id=99999)).status_code==400
    invalid=document();invalid['design']['theme']='evil';assert gm.post('/api/admin/handouts',json=invalid).status_code==400


def test_artwork_upload_and_preview(tmp_path,monkeypatch):
    import app.main as main
    import io
    from PIL import Image
    s=setup(tmp_path);seed(s);monkeypatch.setattr(main,'settings',s);gm=gm_client(main,s)
    image=io.BytesIO();Image.new('RGB',(20,20),'red').save(image,format='PNG')
    made=gm.post('/api/admin/handout-creator/artwork',files={'image':('map.png',image.getvalue(),'image/png')})
    assert made.status_code==200,made.text
    ref=made.json()['ref'];assert (s.uploads_dir/ref.removeprefix('upload:')).exists()
    bad=gm.post('/api/admin/handout-creator/artwork',files={'image':('bad.png',b'not an image','image/png')})
    assert bad.status_code==400
    d=document(image_ref=ref);row=gm.post('/api/admin/handouts',json=d).json()
    assert '/uploads/handouts/' in gm.get('/handout/'+row['slug']+'/export').text
    assert '/uploads/handouts/' in gm.post('/api/admin/handout-creator/preview',json=d).text
