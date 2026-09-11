from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_landing_animation_contract_and_cache_bust():
    home=(ROOT/'templates/home.html').read_text(encoding='utf-8')
    css=(ROOT/'static/wiki.css').read_text(encoding='utf-8')
    js=(ROOT/'static/wiki.js').read_text(encoding='utf-8')
    sw=(ROOT/'static/sw.js').read_text(encoding='utf-8')
    assert 'data-home-hero' in home
    assert '@keyframes heroOrbit' in css and '@keyframes heroRise' in css
    assert 'hero-motion-ready' in css and 'heroScrollCue' in css
    assert "document.querySelector('[data-home-hero]')" in js
    assert "requestAnimationFrame(()=>requestAnimationFrame" in js
    assert 'seeker-static-v9001' in sw and '/static/wiki.css?v=9001' in sw
