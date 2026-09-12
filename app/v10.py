from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import time
import threading
from pathlib import Path
from typing import Any

from .config import Settings
from .storage import connect

_ASSET_SCAN_LOCK = threading.Lock()
_ASSET_LAST_SCAN: dict[str, float] = {}

V10_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS seeker_schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    applied_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS v10_diagnostic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER,
    level TEXT NOT NULL DEFAULT 'info',
    subsystem TEXT NOT NULL DEFAULT 'app',
    event_type TEXT NOT NULL DEFAULT 'event',
    message TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    duration_ms REAL,
    path TEXT NOT NULL DEFAULT '',
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v10_diag_campaign_created ON v10_diagnostic_events(campaign_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_v10_diag_level_created ON v10_diagnostic_events(level,created_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS v10_asset_index (
    ref TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    mtime_ns INTEGER NOT NULL DEFAULT 0,
    width INTEGER,
    height INTEGER,
    sha256 TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v10_asset_source_path ON v10_asset_index(source,path);

CREATE TABLE IF NOT EXISTS v10_gm_cues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL,
    session_id INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'note',
    title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT '',
    target_key TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'ready',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    executed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_v10_cues_campaign_session ON v10_gm_cues(campaign_id,session_id,status,sort_order,id);
'''


def init_v10_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(V10_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO seeker_schema_migrations(version,description,applied_at) VALUES(?,?,?)",
            ("10.0.0", "Consolidated GM workspace, realtime events, diagnostics, asset index and cue system", time.time()),
        )


def migration_registry(settings: Settings) -> list[dict]:
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM seeker_schema_migrations ORDER BY applied_at,version").fetchall()
    return [dict(r) for r in rows]


def log_diagnostic(
    settings: Settings,
    *,
    campaign_id: int | None = None,
    level: str = "info",
    subsystem: str = "app",
    event_type: str = "event",
    message: str = "",
    request_id: str = "",
    duration_ms: float | None = None,
    path: str = "",
    meta: dict | None = None,
) -> int:
    level = str(level or "info").lower()
    if level not in {"debug", "info", "warning", "error"}:
        level = "info"
    now = time.time()
    try:
        with connect(settings) as conn:
            cur = conn.execute(
                """INSERT INTO v10_diagnostic_events(campaign_id,level,subsystem,event_type,message,request_id,duration_ms,path,meta_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(campaign_id) if campaign_id is not None else None,
                    level,
                    str(subsystem or "app")[:100],
                    str(event_type or "event")[:100],
                    str(message or "")[:2000],
                    str(request_id or "")[:80],
                    float(duration_ms) if duration_ms is not None else None,
                    str(path or "")[:500],
                    json.dumps(meta or {}, separators=(",", ":"), ensure_ascii=False)[:12000],
                    now,
                ),
            )
            return int(cur.lastrowid)
    except Exception:
        # Diagnostics must never create a second application failure.
        return 0


def log_best_effort(
    settings: Settings,
    subsystem: str,
    event_type: str,
    exc: BaseException,
    *,
    campaign_id: int | None = None,
    path: str = "",
    meta: dict | None = None,
    level: str = "warning",
) -> int:
    """Record a swallowed/best-effort failure without changing legacy behavior.

    Older Seeker subsystems deliberately treat some cleanup, optional metadata
    and compatibility operations as non-fatal. Those paths should remain
    non-fatal, but they should no longer disappear without a trace when a GM is
    diagnosing an odd UI or data-state issue.
    """
    detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return log_diagnostic(
        settings,
        campaign_id=campaign_id,
        level=level,
        subsystem=subsystem,
        event_type=event_type,
        message=detail,
        path=path,
        meta=meta or {},
    )


def diagnostic_events(settings: Settings, campaign_id: int | None = None, limit: int = 120) -> list[dict]:
    lim = max(1, min(int(limit), 500))
    with connect(settings) as conn:
        if campaign_id is None:
            rows = conn.execute("SELECT * FROM v10_diagnostic_events ORDER BY created_at DESC,id DESC LIMIT ?", (lim,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM v10_diagnostic_events WHERE campaign_id IS NULL OR campaign_id=? ORDER BY created_at DESC,id DESC LIMIT ?",
                (int(campaign_id), lim),
            ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["meta"] = json.loads(item.pop("meta_json") or "{}")
        except Exception:
            item["meta"] = {}
            item.pop("meta_json", None)
        out.append(item)
    return out


def performance_summary(settings: Settings, campaign_id: int | None = None, hours: float = 24.0) -> dict:
    cutoff = time.time() - max(0.25, float(hours)) * 3600
    where = "created_at>=? AND event_type='request.slow'"
    args: list[Any] = [cutoff]
    if campaign_id is not None:
        where += " AND (campaign_id IS NULL OR campaign_id=?)"
        args.append(int(campaign_id))
    with connect(settings) as conn:
        rows = conn.execute(
            f"""SELECT path,COUNT(*) AS n,ROUND(AVG(duration_ms),1) AS avg_ms,ROUND(MAX(duration_ms),1) AS max_ms
                FROM v10_diagnostic_events WHERE {where}
                GROUP BY path ORDER BY max_ms DESC,n DESC LIMIT 20""",
            tuple(args),
        ).fetchall()
        err_where = "created_at>=? AND level='error'"
        err_args: list[Any] = [cutoff]
        if campaign_id is not None:
            err_where += " AND (campaign_id IS NULL OR campaign_id=?)"
            err_args.append(int(campaign_id))
        errors = int(conn.execute(f"SELECT COUNT(*) FROM v10_diagnostic_events WHERE {err_where}", tuple(err_args)).fetchone()[0])
    return {"hours": hours, "slow": [dict(r) for r in rows], "errors": errors}


def _asset_dimensions(path: Path) -> tuple[int | None, int | None]:
    if path.suffix.lower() == ".svg":
        return None, None
    try:
        from PIL import Image
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return None, None


def _asset_hash(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def refresh_asset_index(settings: Settings, *, force: bool = False) -> dict:
    """Incrementally refresh campaign media metadata.

    The legacy media screens rediscovered every file on every request. V10 keeps
    a persistent index and rate-limits the directory walk; unchanged files are
    only stat'd and changed files alone are re-hashed/decoded. Explicit reindex
    actions and upload hooks can still force an immediate scan.
    """
    key = str(settings.db_path.resolve())
    now = time.time()
    ttl = max(2.0, float(os.getenv("SEEKER_ASSET_SCAN_TTL", "30") or 30))
    with _ASSET_SCAN_LOCK:
        last = _ASSET_LAST_SCAN.get(key, 0.0)
        if not force and now - last < ttl:
            with connect(settings) as conn:
                indexed = int(conn.execute("SELECT COUNT(*) FROM v10_asset_index").fetchone()[0])
            return {"indexed": indexed, "changed": 0, "removed": 0, "skipped": True}
        allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".mp3", ".ogg", ".wav"}
        roots = (("project", settings.project_dir), ("upload", settings.uploads_dir))
        seen: set[str] = set()
        indexed = changed = 0
        with connect(settings) as conn:
            current = {str(r["ref"]): dict(r) for r in conn.execute("SELECT * FROM v10_asset_index").fetchall()}
            for source, root in roots:
                if not root.exists():
                    continue
                for path in root.rglob("*"):
                    if not path.is_file() or path.suffix.lower() not in allowed:
                        continue
                    rel = path.relative_to(root).as_posix()
                    ref = f"{source}:{rel}"
                    seen.add(ref)
                    indexed += 1
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    old = current.get(ref)
                    if not force and old and int(old.get("mtime_ns") or 0) == int(stat.st_mtime_ns) and int(old.get("size_bytes") or 0) == int(stat.st_size):
                        continue
                    width, height = _asset_dimensions(path)
                    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    conn.execute(
                        """INSERT INTO v10_asset_index(ref,source,path,name,mime,size_bytes,mtime_ns,width,height,sha256,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(ref) DO UPDATE SET source=excluded.source,path=excluded.path,name=excluded.name,mime=excluded.mime,
                           size_bytes=excluded.size_bytes,mtime_ns=excluded.mtime_ns,width=excluded.width,height=excluded.height,
                           sha256=excluded.sha256,updated_at=excluded.updated_at""",
                        (ref, source, rel, path.name, mime, int(stat.st_size), int(stat.st_mtime_ns), width, height, _asset_hash(path), now),
                    )
                    changed += 1
            stale = [ref for ref in current if ref not in seen]
            if stale:
                conn.executemany("DELETE FROM v10_asset_index WHERE ref=?", [(x,) for x in stale])
        _ASSET_LAST_SCAN[key] = now
        return {"indexed": indexed, "changed": changed, "removed": len(stale), "skipped": False}


def indexed_assets(settings: Settings, *, refresh: bool = True) -> list[dict]:
    # Stat-only incremental refresh is cheap and makes uploads immediately visible.
    if refresh:
        refresh_asset_index(settings)
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM v10_asset_index ORDER BY source,path COLLATE NOCASE").fetchall()
    out = []
    for r in rows:
        item = dict(r)
        rel = str(item["path"])
        item["url"] = ("/project-asset/" if item["source"] == "project" else "/uploads/") + rel
        out.append(item)
    return out


def asset_storage_summary(settings: Settings) -> dict:
    with connect(settings) as conn:
        rows = conn.execute("SELECT source,COUNT(*) AS files,COALESCE(SUM(size_bytes),0) AS bytes FROM v10_asset_index GROUP BY source").fetchall()
        total = conn.execute("SELECT COUNT(*),COALESCE(SUM(size_bytes),0) FROM v10_asset_index").fetchone()
    return {"total_files": int(total[0]), "total_bytes": int(total[1]), "sources": [dict(r) for r in rows]}


def _decode_cue(row: Any) -> dict:
    out = dict(row)
    try:
        out["payload"] = json.loads(out.pop("payload_json") or "{}")
    except Exception:
        out["payload"] = {}
        out.pop("payload_json", None)
    return out


def list_cues(settings: Settings, campaign_id: int, session_id: int | None = None, *, include_done: bool = True) -> list[dict]:
    args: list[Any] = [int(campaign_id)]
    where = "campaign_id=?"
    if session_id is not None:
        where += " AND session_id=?"
        args.append(int(session_id))
    if not include_done:
        where += " AND status<>'done'"
    with connect(settings) as conn:
        rows = conn.execute(f"SELECT * FROM v10_gm_cues WHERE {where} ORDER BY sort_order,id", tuple(args)).fetchall()
    return [_decode_cue(r) for r in rows]


def get_cue(settings: Settings, campaign_id: int, cue_id: int) -> dict | None:
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM v10_gm_cues WHERE id=? AND campaign_id=?", (int(cue_id), int(campaign_id))).fetchone()
    return _decode_cue(row) if row else None


def save_cue(settings: Settings, campaign_id: int, payload: dict) -> dict:
    cid = int(campaign_id)
    cue_id = int(payload.get("id") or 0)
    kind = str(payload.get("kind") or "note").strip().lower()[:60]
    title = str(payload.get("title") or "Cue").strip()[:240]
    notes = str(payload.get("notes") or "")[:8000]
    target_type = str(payload.get("target_type") or "")[:80]
    target_key = str(payload.get("target_key") or "")[:300]
    data = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    session_id = int(payload.get("session_id")) if payload.get("session_id") not in {None, ""} else None
    sort_order = int(payload.get("sort_order") or 0)
    status = str(payload.get("status") or "ready").lower()
    if status not in {"ready", "done", "skipped"}:
        status = "ready"
    now = time.time()
    with connect(settings) as conn:
        if cue_id:
            exists = conn.execute("SELECT 1 FROM v10_gm_cues WHERE id=? AND campaign_id=?", (cue_id, cid)).fetchone()
            if not exists:
                raise ValueError("Cue not found.")
            conn.execute(
                """UPDATE v10_gm_cues SET session_id=?,sort_order=?,kind=?,title=?,notes=?,target_type=?,target_key=?,payload_json=?,status=?,updated_at=? WHERE id=? AND campaign_id=?""",
                (session_id, sort_order, kind, title, notes, target_type, target_key, json.dumps(data, separators=(",", ":")), status, now, cue_id, cid),
            )
            out = cue_id
        else:
            if not payload.get("sort_order"):
                row = conn.execute("SELECT COALESCE(MAX(sort_order),0)+10 FROM v10_gm_cues WHERE campaign_id=? AND session_id IS ?", (cid, session_id)).fetchone()
                sort_order = int(row[0] or 10)
            out = int(conn.execute(
                """INSERT INTO v10_gm_cues(campaign_id,session_id,sort_order,kind,title,notes,target_type,target_key,payload_json,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, session_id, sort_order, kind, title, notes, target_type, target_key, json.dumps(data, separators=(",", ":")), status, now, now),
            ).lastrowid)
    return get_cue(settings, cid, out) or {}


def delete_cue(settings: Settings, campaign_id: int, cue_id: int) -> None:
    with connect(settings) as conn:
        conn.execute("DELETE FROM v10_gm_cues WHERE id=? AND campaign_id=?", (int(cue_id), int(campaign_id)))


def mark_cue(settings: Settings, campaign_id: int, cue_id: int, status: str) -> dict:
    status = str(status or "done").lower()
    if status not in {"ready", "done", "skipped"}:
        raise ValueError("Invalid cue status.")
    now = time.time()
    with connect(settings) as conn:
        conn.execute(
            "UPDATE v10_gm_cues SET status=?,updated_at=?,executed_at=? WHERE id=? AND campaign_id=?",
            (status, now, now if status == "done" else None, int(cue_id), int(campaign_id)),
        )
    row = get_cue(settings, campaign_id, cue_id)
    if not row:
        raise ValueError("Cue not found.")
    return row


def table_counts(settings: Settings) -> dict:
    with connect(settings) as conn:
        tables = [str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    return {"tables": len(tables), "names": tables}
