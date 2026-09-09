from pathlib import Path


def test_studio_bootstrap_helpers_are_shipped():
    source = (Path(__file__).parents[1] / "static" / "admin.js").read_text(encoding="utf-8")
    for helper in ("refreshStatus", "refreshFiles", "renderFileTree"):
        assert f"function {helper}(" in source or f"async function {helper}(" in source


def test_studio_refresh_helpers_reconnect_status_files_and_project_controls():
    source = (Path(__file__).parents[1] / "static" / "admin.js").read_text(encoding="utf-8")
    assert "S.status=await api('/api/admin/status')" in source
    assert "S.files=await api('/api/admin/files')" in source
    assert "renderMainFileSelect()" in source
    assert "renderProjectHealth()" in source
    assert "data-file-path" in source
