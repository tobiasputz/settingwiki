from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.storage import init_db, create_player_invite, connect
from app.features import init_feature_db, save_player_character
from app.scheduling import init_schedule_db
from app.v5 import init_v5_db
from app.v51 import init_v51_db
from app.v6 import init_v6_db
from app.v7 import init_v7_db
from app.v8 import init_v8_db
from app.v9 import init_v9_db
from app.campaigns import default_campaign_id, set_campaign_members
from app.latex import build_wiki

ROOT = Path(__file__).resolve().parents[1]


def _settings(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','invite-secret','admin',None,'auto',20,False)


def _setup(tmp_path: Path) -> tuple[Settings, int, dict]:
    s=_settings(tmp_path)
    init_db(s);init_feature_db(s);init_schedule_db(s);init_v5_db(s);init_v51_db(s);init_v6_db(s);init_v7_db(s);init_v8_db(s);init_v9_db(s)
    (s.project_dir/'main.tex').write_text(r'\documentclass{book}\begin{document}\chapter{People}\section{Corvina}Courier.\end{document}',encoding='utf-8')
    build_wiki(s)
    cid=default_campaign_id(s)
    invite=create_player_invite(s,'Alice');set_campaign_members(s,cid,[invite['id']])
    return s,cid,invite


def _admin_client(main, settings):
    main.settings=settings
    c=TestClient(main.app)
    assert c.post('/admin/login',data={'password':'admin'}).status_code in {200,303}
    return c


def _player_client(main, invite):
    c=TestClient(main.app)
    assert c.get(invite['invite_path'],follow_redirects=False).status_code==303
    return c


def test_chronicle_journal_button_has_real_gm_and_player_write_paths(tmp_path: Path, monkeypatch):
    import app.main as main
    s,cid,invite=_setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    admin=_admin_client(main,s)
    html=admin.get('/campaign').text
    assert 'data-new-journal' in html
    assert '"journal_authors"' in html and 'Alice' in html
    # A GM-authored journal is explicitly attributed to a player at this table.
    created=admin.post('/api/player/journals',json={'author_invite_id':invite['id'],'campaign_id':cid,'title':'GM note for Alice','body':'Works','visibility':'party'})
    assert created.status_code==200,created.text
    assert created.json()['player_label']=='Alice'
    assert 'GM note for Alice' in admin.get('/campaign').text
    # The GM must not be offered the player-to-GM contribution action, which
    # requires a personal invitation and was previously a dead control.
    assert 'data-new-submission' not in html

    player=_player_client(main,invite)
    created=player.post('/api/player/journals',json={'campaign_id':cid,'title':'Alice journal','body':'Player path','visibility':'private'})
    assert created.status_code==200,created.text
    assert created.json()['invite_id']==invite['id']


def test_chronicle_character_arc_and_relationship_buttons_have_working_write_paths(tmp_path: Path, monkeypatch):
    import app.main as main
    s,cid,invite=_setup(tmp_path);monkeypatch.setattr(main,'settings',s)
    char=save_player_character(s,{'campaign_id':cid,'name':'Aster','ancestry':'Human','class_name':'Rogue'},invite_id=invite['id'])
    player=_player_client(main,invite)
    arc=player.post(f"/api/player/characters/{char['id']}/arcs",json={'title':'Find the key','body':'Personal goal','kind':'goal','visibility':'private','status':'active'})
    assert arc.status_code==200,arc.text
    rel=player.post(f"/api/player/characters/{char['id']}/relationships",json={'target_type':'page','target_key':'corvina','relation':'trusts','note':'Met in town','visibility':'party'})
    assert rel.status_code==200,rel.text
    admin=_admin_client(main,s)
    rel2=admin.post(f"/api/player/characters/{char['id']}/relationships",json={'target_type':'page','target_key':'corvina','relation':'owes','note':'GM edit','visibility':'party'})
    assert rel2.status_code==200,rel2.text


def test_every_literal_frontend_api_action_has_a_registered_method_and_route():
    """An actionable control is not considered wired just because JS mentions it.

    Every literal/template API call in shipped browser JS must resolve to a
    FastAPI route with the same HTTP method. Dynamic ids are normalized.
    """
    routes=[]
    for source in (ROOT/'app').glob('*.py'):
        text=source.read_text(encoding='utf-8',errors='ignore')
        routes.extend((m.group(1).upper(),m.group(2)) for m in re.finditer(r'@app\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)',text))

    def route_rx(path: str):
        bits=[];pos=0
        for m in re.finditer(r'\{[^}]+\}',path):
            bits.append(re.escape(path[pos:m.start()]));bits.append(r'[^/?]+');pos=m.end()
        bits.append(re.escape(path[pos:]));return re.compile('^'+''.join(bits)+'$')

    compiled=[(method,route_rx(path),path) for method,path in routes]
    failures=[]
    for source in (ROOT/'static').glob('*.js'):
        text=source.read_text(encoding='utf-8',errors='ignore')
        calls=[]
        for helper,method in [('post','POST'),('put','PUT'),('del','DELETE')]:
            for m in re.finditer(rf'\b{helper}\(\s*([`"\'])(.+?)\1',text,re.S):
                if m.group(2).startswith('/api/'): calls.append((method,m.group(2)))
        for helper in ('api','fetch'):
            for m in re.finditer(rf'\b{helper}\(\s*([`"\'])(.+?)\1',text,re.S):
                url=m.group(2)
                if not url.startswith('/api/'): continue
                frag=text[m.end():m.end()+300]
                mm=re.search(r'method\s*:\s*["\'](GET|POST|PUT|DELETE|PATCH)["\']',frag,re.I)
                calls.append(((mm.group(1).upper() if mm else 'GET'),url))
        for method,url in calls:
            path=url.split('?',1)[0]
            path=re.sub(r'\$\{[^}]+\}','x',path)
            matches=any(meth==method and rx.match(path) for meth,rx,_ in compiled)
            if not matches:
                # Concatenated ids are captured as a literal prefix ending in '/'.
                prefix=url.split('${',1)[0]
                matches=any(meth==method and route.startswith(prefix) for meth,_,route in compiled)
            if not matches: failures.append(f'{source.name}: {method} {url}')
    assert not failures,'Frontend actions without a matching API route/method:\n'+'\n'.join(sorted(set(failures)))


def test_template_buttons_are_bound_by_scripts_loaded_on_that_page():
    """Avoid false positives from a handler existing in an unrelated module."""
    templates=ROOT/'templates';static=ROOT/'static'
    base=(templates/'base.html').read_text(encoding='utf-8')
    base_scripts=[x.split('?',1)[0].split('/')[-1] for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',base,re.I) if x.startswith('/static/')]
    failures=[]
    for template in templates.glob('*.html'):
        if template.name.startswith('partials_'): continue
        text=template.read_text(encoding='utf-8',errors='ignore')
        scripts=[]
        if re.search(r'{%\s*extends\s+["\']base\.html',text): scripts+=base_scripts
        scripts += [x.split('?',1)[0].split('/')[-1] for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',text,re.I) if x.startswith('/static/')]
        corpus='\n'.join((static/s).read_text(encoding='utf-8',errors='ignore') for s in set(scripts) if (static/s).exists())
        corpus+='\n'+'\n'.join(re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>',text,re.S|re.I))
        for match in re.finditer(r'<button\b([^>]*)>(.*?)</button>',text,re.S|re.I):
            attrs=match.group(1);label=' '.join(re.sub(r'<.*?>',' ',match.group(2)).split())[:80]
            if 'onclick=' in attrs.lower(): continue
            typem=re.search(r'type\s*=\s*["\']([^"\']+)',attrs,re.I);typ=typem.group(1).lower() if typem else ''
            before=text[:match.start()];in_form=before.rfind('<form')>before.rfind('</form>')
            if typ in {'submit','reset'} or (in_form and typ!='button'): continue
            ids=re.findall(r'id\s*=\s*["\']([^"\']+)',attrs,re.I)
            datas=re.findall(r'(data-[\w-]+)',attrs,re.I)
            classes=(re.search(r'class\s*=\s*["\']([^"\']+)',attrs,re.I).group(1).split() if re.search(r'class\s*=\s*["\']([^"\']+)',attrs,re.I) else [])
            bound=False
            for ident in ids:
                bound |= any(tok in corpus for tok in (f'#{ident}',f"getElementById('{ident}')",f'getElementById("{ident}")'))
            for data_name in datas:
                raw=data_name[5:];parts=raw.split('-');camel=parts[0]+''.join(x.title() for x in parts[1:])
                bound |= f'[{data_name}' in corpus or f'dataset.{camel}' in corpus or f"getAttribute('{data_name}')" in corpus or f'getAttribute("{data_name}")' in corpus
            for cls in classes:
                bound |= bool(re.search(rf'(?:querySelector(?:All)?|\$\$?|closest)\([^\n]{{0,80}}["\']\.{re.escape(cls)}',corpus))
            if not bound: failures.append(f'{template.name}: {label or "<unlabelled>"}')
    assert not failures,'Buttons whose loaded page scripts do not bind them:\n'+'\n'.join(failures)
