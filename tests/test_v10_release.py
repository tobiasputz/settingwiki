from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.realtime import EventBus
from app.storage import init_db
from app.v10 import (
    asset_storage_summary,
    delete_cue,
    diagnostic_events,
    indexed_assets,
    init_v10_db,
    list_cues,
    log_diagnostic,
    mark_cue,
    migration_registry,
    refresh_asset_index,
    save_cue,
)


def settings_for(tmp_path: Path) -> Settings:
    project = tmp_path / "project"; project.mkdir()
    build = tmp_path / "build"; build.mkdir()
    history = tmp_path / "history"; history.mkdir()
    uploads = tmp_path / "uploads"; uploads.mkdir()
    return Settings(
        root_dir=tmp_path,
        data_dir=tmp_path,
        project_dir=project,
        build_dir=build,
        history_dir=history,
        uploads_dir=uploads,
        db_path=tmp_path / "db.sqlite",
        session_secret="test-secret",
        admin_password="admin",
        player_password=None,
        latex_engine="auto",
        latex_timeout=20,
        allow_shell_escape=False,
    )


def setup_v10(tmp_path: Path) -> Settings:
    settings = settings_for(tmp_path)
    init_db(settings)
    init_v10_db(settings)
    return settings


def test_v10_release_surface_is_shipped_and_player_styles_remain_opt_in():
    root = Path(__file__).resolve().parents[1]
    assert (root / "VERSION").read_text().strip() == "10.0.1"
    assert (root / "app/realtime.py").exists()
    assert (root / "app/bootstrap.py").exists()
    assert (root / "app/v10.py").exists() and (root / "app/v10_api.py").exists()
    assert (root / "static/ui-core.css").exists() and (root / "static/ui-core.js").exists()
    assert (root / "static/v10.css").exists() and (root / "static/v10.js").exists()

    base = (root / "templates/base.html").read_text(encoding="utf-8")
    studio = (root / "templates/admin.html").read_text(encoding="utf-8")
    workspace = (root / "templates/v8_workspace.html").read_text(encoding="utf-8")
    homebrew = (root / "static/homebrew.css").read_text(encoding="utf-8")
    v10js = (root / "static/v10.js").read_text(encoding="utf-8")
    ui = (root / "static/ui-core.css").read_text(encoding="utf-8")

    # Studio belongs to the normal GM suite without deleting its mature editor.
    assert "GM Tools" in studio and "Campaign Workspace" in studio and "Source Studio" in studio
    assert "/static/vendor/codemirror/lib/codemirror.js" in studio
    assert "cdnjs.cloudflare.com" not in studio
    assert "v10ViewAs" in workspace and "GM cues" in workspace

    # View-as and the universal drawer are GM-only surfaces; normal player markup
    # still comes from the established base shell rather than a redesign.
    assert "preview_mode" in base and "VIEWING AS" in base and "universalObjectDrawer" in base
    assert "new EventSource('/api/events')" in v10js
    assert ".seeker-ui-card" in ui
    assert ".homebrew-source-card-actions" in homebrew and "position:static" in homebrew


def test_v10_realtime_bus_filters_campaigns_and_formats_sse():
    bus = EventBus(max_events=8)
    global_event = bus.publish("global.changed", payload={"n": 1})
    a = bus.publish("campaign.changed", campaign_id=10, path="/api/test", payload={"n": 2})
    bus.publish("campaign.changed", campaign_id=20, payload={"n": 3})
    rows = bus.after(global_event.seq - 1, campaign_id=10)
    assert [row.seq for row in rows] == [global_event.seq, a.seq]
    text = bus.sse(a)
    assert f"id: {a.seq}" in text and "event: seeker" in text and '"campaign_id":10' in text


def test_v10_migration_diagnostics_assets_and_cues(tmp_path: Path):
    settings = setup_v10(tmp_path)
    assert any(row["version"] == "10.0.0" for row in migration_registry(settings))

    log_diagnostic(
        settings,
        campaign_id=1,
        level="error",
        subsystem="test",
        event_type="browser.error",
        message="Synthetic regression event",
        request_id="req-test",
        meta={"safe": True},
    )
    events = diagnostic_events(settings, 1)
    assert events and events[0]["message"] == "Synthetic regression event"
    assert events[0]["meta"]["safe"] is True

    # Persistent asset indexing notices additions, preserves stable URLs and
    # removes deleted files on a forced refresh.
    media = settings.uploads_dir / "portrait.png"
    media.write_bytes(b"not-a-real-png-but-valid-index-input")
    first = refresh_asset_index(settings, force=True)
    assert first["indexed"] == 1 and first["changed"] == 1
    rows = indexed_assets(settings, refresh=False)
    assert rows[0]["ref"] == "upload:portrait.png" and rows[0]["url"] == "/uploads/portrait.png"
    assert asset_storage_summary(settings)["total_files"] == 1
    media.unlink()
    second = refresh_asset_index(settings, force=True)
    assert second["removed"] == 1 and indexed_assets(settings, refresh=False) == []

    one = save_cue(settings, 1, {"kind": "note", "title": "Opening beat", "notes": "Describe the storm."})
    two = save_cue(settings, 1, {"kind": "display", "title": "Show map", "target_key": "main", "payload": {"mode": "map"}})
    assert [row["title"] for row in list_cues(settings, 1)] == ["Opening beat", "Show map"]
    assert two["sort_order"] > one["sort_order"]
    done = mark_cue(settings, 1, one["id"], "done")
    assert done["status"] == "done" and done["executed_at"] is not None
    assert [row["id"] for row in list_cues(settings, 1, include_done=False)] == [two["id"]]
    delete_cue(settings, 1, two["id"])
    assert [row["id"] for row in list_cues(settings, 1)] == [one["id"]]


def test_v10_router_is_domain_split_and_best_effort_failures_are_observable():
    import ast

    root = Path(__file__).resolve().parents[1]
    main = root / "app" / "main.py"
    assert len(main.read_text(encoding="utf-8").splitlines()) < 3000

    route_files = [
        root / "app" / "route_runtime.py",
        root / "app" / "route_public_access.py",
        root / "app" / "route_studio.py",
        root / "app" / "route_living.py",
        root / "app" / "route_session_tools.py",
        root / "app" / "route_gm_integrations.py",
        root / "app" / "route_integration_api.py",
    ]
    assert all(path.exists() for path in route_files)
    route_contracts = sum(path.read_text(encoding="utf-8").count("@app.") for path in route_files)
    assert route_contracts >= 330

    bridge = (root / "app" / "route_bridge.py").read_text(encoding="utf-8")
    assert "_DynamicObject" in bridge and "_LATE_CALLABLES" in bridge
    v10 = (root / "app" / "v10.py").read_text(encoding="utf-8")
    assert "def log_best_effort(" in v10

    # Broad catches are allowed for compatibility, but a completely swallowed
    # broad exception must not reappear anywhere in the application package.
    swallowed = []
    for path in (root / "app").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception")
            if broad and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                swallowed.append(f"{path.name}:{node.lineno}")
    assert swallowed == []


def test_v1001_source_linked_forge_type_picker_stays_clickable():
    root = Path(__file__).resolve().parents[1]
    js = (root / "static" / "foundry-workshop.js").read_text(encoding="utf-8")
    # Source-linked entries may not be converted in place, but the palette must
    # remain interactive. A different type starts a fresh unsaved entry instead.
    assert "b.disabled=false" in js
    assert "function beginDifferentType" in js
    assert "the linked source was left unchanged" in js
    assert "b.disabled=linked&&b.dataset.fwKind!==fieldValue('kind')" not in js
