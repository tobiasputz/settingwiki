from pathlib import Path

from app.config import Settings
from app.maps import DEFAULT_EFFECTS, create_map, get_map, update_map
from app.storage import connect, init_db


def make_settings(tmp_path: Path) -> Settings:
    project=tmp_path/'project'; project.mkdir(); build=tmp_path/'build'; build.mkdir(); history=tmp_path/'history'; history.mkdir(); uploads=tmp_path/'uploads'; uploads.mkdir()
    return Settings(tmp_path,tmp_path,project,build,history,uploads,tmp_path/'db.sqlite','s','a',None,'pdflatex',20,False)


def test_new_maps_have_edge_locked_fantasy_effects(tmp_path: Path):
    s=make_settings(tmp_path); init_db(s)
    m=create_map(s,'Kiragon','maps/kiragon.png')
    assert m['effects']['viewport_mode']=='cover'
    assert m['effects']['edge_lock'] is True
    assert m['effects']['clouds'] is True
    assert m['effects']['compass'] is True
    assert m['effects']['edge_fog'] is False
    assert m['effects']['dragon_shadow'] is False


def test_effect_settings_roundtrip_and_validate(tmp_path: Path):
    s=make_settings(tmp_path); init_db(s)
    m=create_map(s,'Kiragon','maps/kiragon.png')
    updated=update_map(s,m['id'],{'effects':{'clouds':False,'rain':True,'lightning':True,'dragon_shadow':True,'rune_pulses':True,'effect_intensity':9,'motion_speed':-2,'viewport_mode':'nonsense'}})
    assert updated['effects']['clouds'] is False
    assert updated['effects']['rain'] is True
    assert updated['effects']['lightning'] is True
    assert updated['effects']['dragon_shadow'] is True
    assert updated['effects']['rune_pulses'] is True
    assert updated['effects']['effect_intensity']==1.0
    assert updated['effects']['motion_speed']==0.05
    assert updated['effects']['viewport_mode']=='cover'


def test_existing_database_gets_effects_json_migration(tmp_path: Path):
    s=make_settings(tmp_path)
    # Simulate an older persistent volume schema.
    with connect(s) as conn:
        conn.execute('CREATE TABLE maps (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,slug TEXT UNIQUE NOT NULL,image_path TEXT NOT NULL,description TEXT NOT NULL DEFAULT "",cloud_enabled INTEGER NOT NULL DEFAULT 1,cloud_opacity REAL NOT NULL DEFAULT 0.34,cloud_speed REAL NOT NULL DEFAULT 0.55,sort_order INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL,updated_at REAL NOT NULL)')
    init_db(s)
    with connect(s) as conn:
        cols={row[1] for row in conn.execute('PRAGMA table_info(maps)').fetchall()}
    assert 'effects_json' in cols


def test_partial_effect_update_preserves_existing_choices(tmp_path: Path):
    s=make_settings(tmp_path); init_db(s)
    m=create_map(s,'Kiragon','maps/kiragon.png')
    first=update_map(s,m['id'],{'effects':{'aurora':True,'stars':True,'clouds':False}})
    second=update_map(s,m['id'],{'effects':{'rain':True}})
    assert first['effects']['aurora'] is True
    assert second['effects']['aurora'] is True
    assert second['effects']['stars'] is True
    assert second['effects']['clouds'] is False
    assert second['effects']['rain'] is True
