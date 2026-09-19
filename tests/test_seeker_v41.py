from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.storage import init_db, set_setting
from app.features import init_feature_db
from app.living import init_living_db
from app.latex import _load_wiki_file_cached, build_wiki, load_wiki


def make_settings(tmp_path: Path) -> Settings:
    project=tmp_path/'project';project.mkdir();build=tmp_path/'build';build.mkdir();history=tmp_path/'history';history.mkdir();uploads=tmp_path/'uploads';uploads.mkdir()
    return Settings(root_dir=tmp_path,data_dir=tmp_path,project_dir=project,build_dir=build,history_dir=history,uploads_dir=uploads,db_path=tmp_path/'db.sqlite',session_secret='test',admin_password='test',player_password=None,latex_engine='pdflatex',latex_timeout=20,allow_shell_escape=False)


def setup_all(tmp_path: Path) -> Settings:
    s=make_settings(tmp_path);init_db(s);init_feature_db(s);init_living_db(s);return s


def test_generated_wiki_json_is_signature_cached_with_one_entry(tmp_path: Path):
    s=setup_all(tmp_path)
    (s.project_dir/'main.tex').write_text(r'\documentclass{book}\begin{document}\chapter{World}\section{Gate}Hello.\end{document}',encoding='utf-8')
    build_wiki(s);_load_wiki_file_cached.cache_clear()
    first=load_wiki(s);before=_load_wiki_file_cached.cache_info();second=load_wiki(s);after=_load_wiki_file_cached.cache_info()
    assert first is second
    assert after.hits==before.hits+1
    assert after.maxsize==1


def test_visible_wiki_uses_one_bulk_dynamic_connection_and_defers_gallery(tmp_path: Path,monkeypatch):
    import app.main as main
    from app.storage import connect as real_connect
    s=setup_all(tmp_path);set_setting(s,'player_access_mode','public');monkeypatch.setattr(main,'settings',s)
    pages=[]
    for i in range(160):
        pages.append({'slug':f'entry-{i}','title':f'Entry {i}','html':f'<p>Text {i}</p>','plain_text':f'Text {i}','excerpt':f'Text {i}','presentation':{'visibility':'public'},'related':[],'backlinks':[]})
    monkeypatch.setattr(main,'ensure_built',lambda:{'title':'Kiragon','tagline':'','pages':pages,'categories':[{'title':'World','slug':'world','presentation':{},'pages':pages}]})
    monkeypatch.setattr(main,'_gallery_from_html',lambda *_: (_ for _ in ()).throw(AssertionError('gallery should only be extracted by the article route')))
    count={'n':0}
    def counted(_settings):
        count['n']+=1;return real_connect(s)
    monkeypatch.setattr(main,'connect',counted)
    wiki=main._visible_wiki(SimpleNamespace(session={}))
    assert len(wiki['pages'])==160
    assert count['n']==2  # one lightweight revision fingerprint + one bulk dynamic-state load
    again=main._visible_wiki(SimpleNamespace(session={}))
    assert len(again['pages'])==160
    assert count['n']==3  # cached Codex view: only the lightweight fingerprint query repeats


def test_map_listing_bulk_loads_markers_once(tmp_path: Path,monkeypatch):
    import app.maps as maps
    from app.storage import connect as real_connect
    s=setup_all(tmp_path)
    for i in range(6):
        m=maps.create_map(s,f'Map {i}',f'map-{i}.png')
        maps.create_marker(s,m['id'],{'title':'Place','x':.2,'y':.4})
    statements=[]
    class ConnContext:
        def __enter__(self):
            self.conn=real_connect(s);self.conn.set_trace_callback(statements.append);return self.conn
        def __exit__(self,*args):
            self.conn.close()
    monkeypatch.setattr(maps,'connect',lambda _settings:ConnContext())
    rows=maps.list_maps(s,public=True)
    marker_selects=[q for q in statements if q.lstrip().upper().startswith('SELECT * FROM MARKERS')]
    assert len(rows)==6 and len(marker_selects)==1


def test_resource_guardrails_are_shipped():
    root=Path(__file__).resolve().parents[1]
    latex=(root/'app'/'latex.py').read_text(encoding='utf-8')
    main=(root/'app'/'main.py').read_text(encoding='utf-8')
    wiki=(root/'static'/'wiki.js').read_text(encoding='utf-8')
    assert 'TemporaryFile(mode="w+b")' in latex and 'stdout=subprocess.PIPE' not in latex
    assert 'COMPILE_ON_START", "0"' in main and 'BUILD_LOCK.acquire(blocking=False)' in main
    assert '_stream_upload' in main and 'await file.read(30_000_001)' not in main and 'await file.read(40_000_001)' not in main
    assert '_visible_wiki_cached' in main and 'player_activity' not in main[main.index('def _visible_wiki_signature'):main.index('@functools.lru_cache(maxsize=12)')]
    assert 'searchAbort?.abort()' in wiki and 'hoverCache.size>32' in wiki
    assert 'setInterval(pollNotifications,60000)' in wiki and "addEventListener('seeker:event'" in wiki and 'if(document.hidden)return' in wiki


def test_seeker_brand_is_player_facing_and_legacy_name_is_only_internal_compatibility():
    root=Path(__file__).resolve().parents[1]
    templates='\n'.join(p.read_text(encoding='utf-8') for p in (root/'templates').glob('*.html'))
    base=(root/'templates'/'base.html').read_text(encoding='utf-8')
    assert 'Loreforge' not in templates
    assert 'Chronicle' in base and '<summary>Discover ' in base and 'Worldcraft' in base and 'World State' in base
    assert '/static/seeker-icon.svg' in base


def test_entity_provenance_union_orders_without_sqlite_compound_select_error(tmp_path: Path):
    from app.features import save_session, set_session_lore, add_session_update
    from app.living import entity_provenance

    s=setup_all(tmp_path)
    later=save_session(s,{"session_number":7,"title":"Later","session_date":"2026-09-09","status":"ended"})
    undated=save_session(s,{"session_number":None,"title":"Unnumbered","session_date":"2026-09-10","status":"ended"})
    earlier=save_session(s,{"session_number":2,"title":"Earlier","session_date":"2026-09-01","status":"ended"})

    # Exercise both halves of the UNION and make one session appear in both so
    # the query must also deduplicate provenance rows.
    set_session_lore(s,later["id"],"test-page",enabled=True)
    set_session_lore(s,earlier["id"],"test-page",enabled=True)
    add_session_update(s,{"session_id":later["id"],"title":"Reveal","target_key":"test-page"})
    add_session_update(s,{"session_id":undated["id"],"title":"Reveal","target_key":"test-page"})

    rows=entity_provenance(s,"test-page")
    assert [r["title"] for r in rows] == ["Earlier","Later","Unnumbered"]
    assert len(rows) == 3


def test_codex_article_route_survives_session_provenance_query(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    from app.features import save_session, set_session_lore, add_session_update
    from app.storage import set_setting

    s=setup_all(tmp_path)
    set_setting(s,"player_access_mode","public")
    session=save_session(s,{"session_number":3,"title":"A Session","session_date":"2026-09-09","status":"ended"})
    set_session_lore(s,session["id"],"test-page",enabled=True)
    add_session_update(s,{"session_id":session["id"],"title":"A reveal","target_key":"test-page"})

    page={
        "slug":"test-page","title":"Test Page","chapter":"World","level":"section",
        "html":"<p>Hello</p>","plain_text":"Hello","excerpt":"Hello",
        "presentation":{"visibility":"public"},"related":[],"backlinks":[],"outline":[],
        "source_file":"main.tex","source_line":1,
    }
    wiki={"title":"Seeker","tagline":"","pages":[page],"categories":[{"title":"World","slug":"world","presentation":{},"pages":[page]}]}
    monkeypatch.setattr(main,"settings",s)
    monkeypatch.setattr(main,"ensure_built",lambda:wiki)
    main._visible_wiki_cached.cache_clear()

    with TestClient(main.app) as client:
        response=client.get("/wiki/test-page")
    assert response.status_code == 200
    assert "Test Page" in response.text and "A Session" in response.text
