from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Iterable

from .config import Settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    image_path TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    cloud_enabled INTEGER NOT NULL DEFAULT 1,
    cloud_opacity REAL NOT NULL DEFAULT 0.34,
    cloud_speed REAL NOT NULL DEFAULT 0.55,
    effects_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS markers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    map_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    x REAL NOT NULL,
    y REAL NOT NULL,
    kind TEXT NOT NULL DEFAULT 'place',
    page_slug TEXT,
    visible_to_players INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(map_id) REFERENCES maps(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS edit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def connect(settings: Settings) -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(SCHEMA)
        # Lightweight forward migrations for persistent Railway volumes created
        # by older Loreforge versions. SQLite CREATE TABLE IF NOT EXISTS does
        # not add newly introduced columns to an existing table.
        map_columns = {row[1] for row in conn.execute("PRAGMA table_info(maps)").fetchall()}
        if "effects_json" not in map_columns:
            conn.execute("ALTER TABLE maps ADD COLUMN effects_json TEXT NOT NULL DEFAULT '{}' ")


def get_setting(settings: Settings, key: str, default: str = "") -> str:
    with connect(settings) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(settings: Settings, key: str, value: str) -> None:
    with connect(settings) as conn:
        conn.execute(
            "INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def safe_project_path(settings: Settings, relative: str) -> Path:
    rel = relative.replace("\\", "/").lstrip("/")
    target = (settings.project_dir / rel).resolve()
    root = settings.project_dir.resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes the campaign project.")
    return target


def list_project_files(settings: Settings) -> list[dict]:
    items: list[dict] = []
    for path in sorted(settings.project_dir.rglob("*")):
        if path.is_dir() or any(part.startswith(".") for part in path.relative_to(settings.project_dir).parts):
            continue
        rel = path.relative_to(settings.project_dir).as_posix()
        items.append({"path": rel, "size": path.stat().st_size, "suffix": path.suffix.lower()})
    return items


def save_text_file(settings: Settings, relative: str, content: str) -> dict:
    target = safe_project_path(settings, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.read_text(encoding="utf-8", errors="replace") if target.exists() else None
    if previous == content:
        return {"path": relative, "changed": False}
    if previous is not None:
        archive_revision(settings, relative, previous)
    target.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with connect(settings) as conn:
        conn.execute("INSERT INTO edit_log(path,sha256,created_at) VALUES(?,?,?)", (relative, digest, time.time()))
    return {"path": relative, "changed": True, "sha256": digest}


def archive_revision(settings: Settings, relative: str, content: str) -> Path:
    safe_name = relative.replace("/", "__").replace("\\", "__")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:10]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = settings.history_dir / f"{stamp}-{digest}-{safe_name}"
    path.write_text(content, encoding="utf-8")
    # Keep a bounded history.
    revisions = sorted(settings.history_dir.glob(f"*-{safe_name}"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in revisions[40:]:
        old.unlink(missing_ok=True)
    return path


def list_revisions(settings: Settings, relative: str) -> list[dict]:
    safe_name = relative.replace("/", "__").replace("\\", "__")
    out = []
    for path in sorted(settings.history_dir.glob(f"*-{safe_name}"), key=lambda p: p.stat().st_mtime, reverse=True):
        out.append({"id": path.name, "created_at": path.stat().st_mtime, "size": path.stat().st_size})
    return out[:40]


def restore_revision(settings: Settings, relative: str, revision_id: str) -> None:
    candidate = (settings.history_dir / Path(revision_id).name).resolve()
    if settings.history_dir.resolve() not in candidate.parents or not candidate.exists():
        raise ValueError("Revision not found.")
    save_text_file(settings, relative, candidate.read_text(encoding="utf-8", errors="replace"))


def safe_extract_zip(zip_path: Path, dest: Path, *, max_uncompressed_bytes: int = 2_000_000_000) -> None:
    """Extract a project ZIP without path traversal or accidental ZIP bombs."""
    dest = dest.resolve()
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.infolist()
        if len(members) > 50_000:
            raise ValueError("The ZIP contains too many files (maximum 50,000).")
        for member in members:
            total += int(member.file_size or 0)
            if total > max_uncompressed_bytes:
                raise ValueError("The ZIP expands beyond Loreforge's 2 GB import safety limit.")
            # Reject Unix symlinks. A campaign source archive should contain real files.
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Symbolic links are not allowed in project ZIPs: {member.filename}")
            target = (dest / member.filename).resolve()
            if target != dest and dest not in target.parents:
                raise ValueError(f"Unsafe path in ZIP: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)


def _zip_directory(source: Path, out: Path) -> None:
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in source.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                zf.write(path, path.relative_to(source).as_posix())


def replace_project_from_zip(settings: Settings, zip_path: Path) -> dict:
    """Replace the persistent project while keeping import scratch data off /data.

    Earlier versions extracted the upload and made a complete uncompressed project
    backup on the persistent Railway volume. On a 0.5 GB Free/Trial volume that could
    require several times the actual project size and fail with ENOSPC. This version
    stages the import and rollback archive in the service's ephemeral temp filesystem,
    so /data only needs room for the final imported project.
    """
    with tempfile.TemporaryDirectory(prefix="loreforge-import-") as scratch_name:
        scratch = Path(scratch_name)
        extracted = scratch / "extracted"
        extracted.mkdir(parents=True)
        safe_extract_zip(zip_path, extracted)

        tex = list(extracted.rglob("*.tex"))
        if not tex:
            raise ValueError("The archive does not contain any .tex files.")

        # Overleaf exports sometimes contain one wrapper folder. Flatten only that case.
        roots = {p.relative_to(extracted).parts[0] for p in tex if p.relative_to(extracted).parts}
        source = extracted
        if len(roots) == 1:
            only = extracted / next(iter(roots))
            if only.is_dir() and list(only.rglob("*.tex")):
                source = only

        incoming_bytes = sum(p.stat().st_size for p in source.rglob("*") if p.is_file())
        free_bytes = shutil.disk_usage(settings.data_dir).free
        # Keep a little headroom for SQLite metadata, wiki index and the compiled PDF.
        reserve = 32 * 1024 * 1024
        if incoming_bytes + reserve > free_bytes + sum(
            p.stat().st_size for p in settings.project_dir.rglob("*") if p.is_file()
        ):
            raise OSError(
                28,
                "Not enough persistent storage for the imported project. "
                f"Import needs about {incoming_bytes / 1024**2:.1f} MB plus build headroom. "
                "Increase the Railway /data volume or remove unused assets."
            )

        rollback = scratch / "previous-project.zip"
        had_project = any(settings.project_dir.iterdir())
        if had_project:
            _zip_directory(settings.project_dir, rollback)

        try:
            # Removing the old project before the final copy means the persistent volume
            # never has to hold two full uncompressed campaign trees simultaneously.
            shutil.rmtree(settings.project_dir, ignore_errors=True)
            settings.project_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, settings.project_dir, dirs_exist_ok=True)
        except Exception:
            shutil.rmtree(settings.project_dir, ignore_errors=True)
            settings.project_dir.mkdir(parents=True, exist_ok=True)
            if had_project and rollback.exists():
                safe_extract_zip(rollback, settings.project_dir)
            raise

        return {
            "incoming_bytes": incoming_bytes,
            "scratch_storage": str(scratch),
            "rollback_protected": had_project,
        }


def export_project_zip(settings: Settings, out: Path) -> Path:
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in settings.project_dir.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                zf.write(path, path.relative_to(settings.project_dir).as_posix())
    return out



def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def storage_report(settings: Settings) -> dict:
    usage = shutil.disk_usage(settings.data_dir)
    legacy = []
    for pattern in ("project-backup-*", "import-*", "upload-*.zip"):
        for path in settings.data_dir.glob(pattern):
            if path.name in {"project", "build", "history", "uploads"}:
                continue
            legacy.append({"name": path.name, "bytes": _path_size(path), "kind": "directory" if path.is_dir() else "file"})
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "project_bytes": _path_size(settings.project_dir),
        "build_bytes": _path_size(settings.build_dir),
        "history_bytes": _path_size(settings.history_dir),
        "uploads_bytes": _path_size(settings.uploads_dir),
        "legacy_import_bytes": sum(x["bytes"] for x in legacy),
        "legacy_import_items": legacy,
    }


def cleanup_legacy_import_artifacts(settings: Settings) -> dict:
    # Do not remove old backup trees unless the active project still contains TeX.
    # This protects the only recoverable copy after an interrupted legacy import.
    has_active_tex = any(settings.project_dir.rglob("*.tex"))
    removed = []
    freed = 0
    for pattern in ("import-*", "upload-*.zip", "project-backup-*"):
        for path in list(settings.data_dir.glob(pattern)):
            if pattern == "project-backup-*" and not has_active_tex:
                continue
            size = _path_size(path)
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
                removed.append(path.name)
                freed += size
            except OSError:
                continue
    return {"removed": removed, "freed_bytes": freed, "storage": storage_report(settings)}

def seed_project(settings: Settings) -> None:
    if any(settings.project_dir.iterdir()):
        return
    seed = settings.root_dir / "campaign"
    if seed.exists() and any(seed.iterdir()):
        shutil.copytree(seed, settings.project_dir, dirs_exist_ok=True)
