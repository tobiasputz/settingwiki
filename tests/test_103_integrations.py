"""Integration contracts added in the Seeker 10.3 release."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def test_release_assets_and_cache_generation():
    assert (ROOT/'VERSION').read_text().strip()=='10.3.0'
    templates=(ROOT/'templates'/'v8_workspace.html').read_text()
    portal=(ROOT/'templates'/'v8_player_portal.html').read_text()
    atlas=(ROOT/'templates'/'map.html').read_text()
    codex=(ROOT/'templates'/'page.html').read_text()
    sw=(ROOT/'static'/'sw.js').read_text()
    for expected in ('worldConsequenceHost','data-journey-tab','world-state.js?v=10300'):
        assert expected in templates
    assert 'worldKnownEvents' in portal and 'world-state.js?v=10300' in portal
    assert 'atlasReliefQuality' in atlas and 'markerWorldEvents' in atlas
    assert 'codexReadingTools' in codex and 'codex-reading.js?v=10300' in codex
    for expected in ('seeker-static-v10300','/static/world-state.js?v=10300',
                     '/static/codex-reading.js?v=10300','/static/map.js?v=10300'):
        assert expected in sw


def test_atlas_quality_selection_and_context_fallback_are_wired():
    shader=(ROOT/'static'/'atlas-relief.js').read_text()
    mapjs=(ROOT/'static'/'map.js').read_text()
    assert 'u_quality' in shader
    assert 'lowDetailTexture' in shader
    assert "this.quality === 'quality'" in shader
    assert 'seeker:terrain-lost' in shader and 'seeker:terrain-lost' in mapjs
    assert 'relief?.setQuality' in mapjs
    assert 'loadMarkerWorldEvents' in mapjs


def test_source_lock_and_world_consequences_integrate():
    api=(ROOT/'app'/'v8_api.py').read_text()
    assert 'expected_hash' in api and 'HTTPException(409' in api
    assert 'Session closeout · ' in api
    assert "'status':'draft'" in api
    assert 'register_world_state_routes' in (ROOT/'app'/'main.py').read_text()
    assert 'init_world_state_db(settings)' in (ROOT/'app'/'bootstrap.py').read_text()
