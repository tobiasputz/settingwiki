from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.features import init_feature_db, save_player_character, save_session
from app.latex import build_wiki
from app.living import list_journals, list_party_journals, save_journal
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


def test_character_scoped_journals_allow_same_session_title_and_filter(tmp_path: Path):
    s=setup(tmp_path);inv=create_player_invite(s,'Alice')
    from app.campaigns import default_campaign_id, set_campaign_members
    set_campaign_members(s,default_campaign_id(s),[inv['id']])
    a=save_player_character(s,{'name':'Aster'},invite_id=inv['id'])
    b=save_player_character(s,{'name':'Bram'},invite_id=inv['id'])
    general=save_journal(s,{'session_id':7,'title':'Session journal','body':'Player-wide'},inv['id'])
    ja=save_journal(s,{'character_id':a['id'],'session_id':7,'title':'Session journal','body':'Aster only'},inv['id'])
    jb=save_journal(s,{'character_id':b['id'],'session_id':7,'title':'Session journal','body':'Bram only'},inv['id'])
    assert {general['id'],ja['id'],jb['id']} <= {j['id'] for j in list_journals(s,inv['id'])}
    a_rows=list_journals(s,inv['id'],character_id=a['id'])
    assert {x['body'] for x in a_rows}=={'Player-wide','Aster only'}
    party_a=list_party_journals(s,inv['id'],character_id=a['id'])
    assert 'Aster only' in {x['body'] for x in party_a} and 'Bram only' not in {x['body'] for x in party_a}
    assert next(x for x in a_rows if x['id']==ja['id'])['character_name']=='Aster'


def test_session_character_choice_scopes_new_notes_and_switches_visibility(tmp_path: Path, monkeypatch):
    import app.main as main
    s=setup(tmp_path);seed_wiki(s);set_setting(s,'player_access_mode','invite');monkeypatch.setattr(main,'settings',s)
    inv=create_player_invite(s,'Alice')
    from app.campaigns import default_campaign_id, set_campaign_members
    set_campaign_members(s,default_campaign_id(s),[inv['id']])
    a=save_player_character(s,{'name':'Aster'},invite_id=inv['id'])
    b=save_player_character(s,{'name':'Bram'},invite_id=inv['id'])
    save_session(s,{'session_number':12,'title':'The Glass Road','status':'live'})
    c=TestClient(main.app);assert c.get(inv['invite_path'],follow_redirects=False).status_code==303
    first=c.get('/session');assert first.status_code==200
    assert 'Who are you playing tonight?' in first.text and 'Aster' in first.text and 'Bram' in first.text
    assert c.post('/api/player/session-character',json={'character_id':a['id']}).status_code==200
    note=c.post('/api/player/journals',json={'session_id':12,'title':'Private clue','body':'Aster remembers the sigil','visibility':'private'})
    assert note.status_code==200 and note.json()['character_id']==a['id']
    a_view=c.get('/session').text
    assert 'Aster remembers the sigil' in a_view and 'Switch character' in a_view
    assert c.post('/api/player/session-character',json={'character_id':b['id']}).status_code==200
    b_view=c.get('/session').text
    assert 'Aster remembers the sigil' not in b_view
    note2=c.post('/api/player/journals',json={'session_id':12,'title':'Private clue','body':'Bram remembers the bell','visibility':'private'})
    assert note2.status_code==200 and note2.json()['character_id']==b['id']
    assert 'Bram remembers the bell' in c.get('/session').text
    assert c.post('/api/player/session-character',json={'character_id':a['id']}).status_code==200
    final=c.get('/session').text
    assert 'Aster remembers the sigil' in final and 'Bram remembers the bell' not in final


def test_journal_rejects_character_owned_by_another_invite(tmp_path: Path):
    s=setup(tmp_path);alice=create_player_invite(s,'Alice');bob=create_player_invite(s,'Bob')
    from app.campaigns import default_campaign_id, set_campaign_members
    set_campaign_members(s,default_campaign_id(s),[alice['id'],bob['id']])
    bob_char=save_player_character(s,{'name':'Bram'},invite_id=bob['id'])
    try:
        save_journal(s,{'character_id':bob_char['id'],'title':'Nope'},alice['id'])
        assert False,'cross-player character journal ownership must be rejected'
    except PermissionError:
        pass


def test_v4_player_qol_assets_and_compact_nav_are_shipped():
    root=Path(__file__).resolve().parents[1]
    base=(root/'templates'/'base.html').read_text(encoding='utf-8')
    session=(root/'templates'/'session.html').read_text(encoding='utf-8')
    living_js=(root/'static'/'living.js').read_text(encoding='utf-8')
    wiki_js=(root/'static'/'wiki.js').read_text(encoding='utf-8')
    tour=(root/'static'/'tour.js').read_text(encoding='utf-8')
    sw=(root/'static'/'sw.js').read_text(encoding='utf-8')
    assert 'gm-nav-menu' in base and '<summary>GM ' in base
    assert 'data-start-tour' in base and '/static/tour.js?v=9003' in base
    assert 'data-session-character' in session and 'SESSION IDENTITY' in session
    assert 'loreforge.journal.draft.v4' in living_js and 'data-journal-filter' in living_js
    assert "editing?(j.character_id||null)" in living_js  # editing a player-wide note must not silently rescope it
    assert 'Recently viewed' in wiki_js and 'Quick jumps' in wiki_js
    assert 'loreforge.quickTour.v4' in tour and 'Enter as your character' in tour
    assert "seeker-static-v9003" in sw and '/static/tour.js?v=9003' in sw

def test_v3_journal_table_is_migrated_without_losing_notes(tmp_path: Path):
    from app.storage import connect
    s=make_settings(tmp_path);init_db(s);inv=create_player_invite(s,'Alice')
    now=123.0
    with connect(s) as conn:
        conn.execute("""CREATE TABLE player_journals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invite_id INTEGER NOT NULL,
            session_id INTEGER,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            visibility TEXT NOT NULL DEFAULT 'private',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(invite_id,session_id,title)
        )""")
        conn.execute("INSERT INTO player_journals(invite_id,session_id,title,body,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(inv['id'],1,'Old note','Still here','private',now,now))
    init_feature_db(s)
    with connect(s) as conn:
        cols={r[1] for r in conn.execute('PRAGMA table_info(player_journals)').fetchall()}
        row=conn.execute('SELECT character_id,title,body FROM player_journals').fetchone()
    assert 'character_id' in cols and row['character_id'] is None
    assert row['title']=='Old note' and row['body']=='Still here'
