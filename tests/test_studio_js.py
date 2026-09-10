from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_studio_bootstrap_helpers_are_shipped():
    source = (ROOT / "static" / "admin.js").read_text(encoding="utf-8")
    for helper in ("refreshStatus", "refreshFiles", "renderFileTree"):
        assert f"function {helper}(" in source or f"async function {helper}(" in source


def test_studio_refresh_helpers_reconnect_status_files_and_project_controls():
    source = (ROOT / "static" / "admin.js").read_text(encoding="utf-8")
    assert "S.status=await api('/api/admin/status')" in source
    assert "S.files=await api('/api/admin/files')" in source
    assert "renderMainFileSelect()" in source
    assert "renderProjectHealth()" in source
    assert "data-file-path" in source


def test_admin_bundle_uses_new_cache_buster():
    html = (ROOT / "templates" / "admin.html").read_text(encoding="utf-8")
    assert '/static/admin.js?v=7100' in html
    assert '/static/admin.js?v=3002' not in html


def test_service_worker_does_not_pin_static_assets_cache_first():
    source = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    assert "seeker-static-v7100" in source
    assert "fetch(e.request).then" in source
    assert ".catch(()=>caches.match(e.request))" in source
    assert "caches.match(e.request).then(hit=>hit||fetch(e.request)" not in source


def test_all_versioned_static_assets_use_current_cache_buster():
    stale=[]
    for folder in (ROOT / "templates", ROOT / "static"):
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix in {".html", ".js", ".css"}:
                text=path.read_text(encoding="utf-8", errors="ignore")
                if "v=3000" in text or "v=3002" in text or "v=4000" in text:
                    stale.append(str(path.relative_to(ROOT)))
    assert stale == []


def test_admin_html_is_not_browser_cached():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert 'TemplateResponse("admin.html", {"request": request, "title": "Seeker Studio"}, headers={"Cache-Control": "no-store"})' in source
    assert '"Cache-Control": "no-cache, no-store, must-revalidate"' in source
