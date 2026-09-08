from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
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


def safe_extract_zip(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if target != dest.resolve() and dest.resolve() not in target.parents:
                raise ValueError(f"Unsafe path in ZIP: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def replace_project_from_zip(settings: Settings, zip_path: Path) -> None:
    tmp = settings.data_dir / f"import-{int(time.time())}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    safe_extract_zip(zip_path, tmp)
    tex = list(tmp.rglob("*.tex"))
    if not tex:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("The archive does not contain any .tex files.")
    # Overleaf exports sometimes contain one wrapper folder. Flatten only that case.
    roots = {p.relative_to(tmp).parts[0] for p in tex if p.relative_to(tmp).parts}
    source = tmp
    if len(roots) == 1:
        only = tmp / next(iter(roots))
        if only.is_dir() and list(only.rglob("*.tex")):
            source = only
    backup = settings.data_dir / f"project-backup-{int(time.time())}"
    if any(settings.project_dir.iterdir()):
        shutil.copytree(settings.project_dir, backup, dirs_exist_ok=True)
    shutil.rmtree(settings.project_dir, ignore_errors=True)
    shutil.copytree(source, settings.project_dir)
    shutil.rmtree(tmp, ignore_errors=True)


def export_project_zip(settings: Settings, out: Path) -> Path:
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in settings.project_dir.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                zf.write(path, path.relative_to(settings.project_dir).as_posix())
    return out


def seed_project(settings: Settings) -> None:
    if any(settings.project_dir.iterdir()):
        return
    seed = settings.root_dir / "campaign"
    if seed.exists() and any(seed.iterdir()):
        shutil.copytree(seed, settings.project_dir, dirs_exist_ok=True)
