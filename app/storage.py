from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
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
CREATE TABLE IF NOT EXISTS player_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    nonce TEXT NOT NULL,
    access_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    expires_at REAL,
    max_devices INTEGER,
    revoked_at REAL,
    last_used_at REAL,
    use_count INTEGER NOT NULL DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'player'
);
CREATE TABLE IF NOT EXISTS player_devices (
    id TEXT PRIMARY KEY,
    invite_id INTEGER NOT NULL,
    access_version INTEGER NOT NULL,
    user_agent TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_player_devices_invite ON player_devices(invite_id, access_version);
CREATE TABLE IF NOT EXISTS codex_presentation (
    target_type TEXT NOT NULL,
    target_key TEXT NOT NULL,
    toc_image TEXT NOT NULL DEFAULT '',
    hero_image TEXT NOT NULL DEFAULT '',
    background_image TEXT NOT NULL DEFAULT '',
    background_opacity REAL NOT NULL DEFAULT 0.16,
    background_x REAL NOT NULL DEFAULT 50,
    background_y REAL NOT NULL DEFAULT 50,
    hero_style TEXT NOT NULL DEFAULT 'banner',
    article_layout TEXT NOT NULL DEFAULT 'standard',
    visibility TEXT NOT NULL DEFAULT 'public',
    featured INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY(target_type, target_key)
);
"""


def connect(settings: Settings) -> sqlite3.Connection:
    # Keep connections short-lived, but configure them for the concurrent read-heavy
    # workload of a campaign table. busy_timeout prevents transient "database is
    # locked" failures when several players poll while the GM saves something.
    conn = sqlite3.connect(settings.db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(settings: Settings) -> None:
    with connect(settings) as conn:
        # WAL lets readers continue while a GM write is committing. NORMAL is a
        # good durability/performance trade-off for Railway's persistent volume
        # and avoids needless fsync pressure on every small journal/poll write.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        # Lightweight forward migrations for persistent Railway volumes created
        # by older Loreforge versions. SQLite CREATE TABLE IF NOT EXISTS does
        # not add newly introduced columns to an existing table.
        map_columns = {row[1] for row in conn.execute("PRAGMA table_info(maps)").fetchall()}
        if "effects_json" not in map_columns:
            conn.execute("ALTER TABLE maps ADD COLUMN effects_json TEXT NOT NULL DEFAULT '{}' ")
        invite_columns = {row[1] for row in conn.execute("PRAGMA table_info(player_invites)").fetchall()}
        if invite_columns and "max_devices" not in invite_columns:
            conn.execute("ALTER TABLE player_invites ADD COLUMN max_devices INTEGER")
        if invite_columns and "role" not in invite_columns:
            conn.execute("ALTER TABLE player_invites ADD COLUMN role TEXT NOT NULL DEFAULT 'player'")


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




def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _invite_signature(settings: Settings, invite_id: int, version: int, nonce: str) -> str:
    payload = f"lf1.{int(invite_id)}.{int(version)}.{nonce}".encode("utf-8")
    digest = hmac.new(settings.session_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _b64url(digest[:20])


def _invite_token(settings: Settings, row: sqlite3.Row | dict) -> str:
    invite_id = int(row["id"])
    version = int(row["access_version"])
    nonce = str(row["nonce"])
    return f"lf1.{invite_id}.{version}.{nonce}.{_invite_signature(settings, invite_id, version, nonce)}"


def _invite_payload(settings: Settings, row: sqlite3.Row | dict, now: float | None = None) -> dict:
    now = time.time() if now is None else float(now)
    data = dict(row)
    expires_at = data.get("expires_at")
    revoked_at = data.get("revoked_at")
    expired = bool(expires_at is not None and float(expires_at) <= now)
    revoked = bool(revoked_at is not None)
    token = _invite_token(settings, data)
    data.update({
        "active": not expired and not revoked,
        "expired": expired,
        "revoked": revoked,
        "token": token,
        "invite_path": "/invite/" + token,
    })
    return data


def create_player_invite(settings: Settings, label: str, expires_at: float | None = None, max_devices: int | None = None, role: str = 'player') -> dict:
    label = str(label or "").strip()
    if not label:
        raise ValueError("Give the invitation a player name or label.")
    if len(label) > 120:
        raise ValueError("Invitation labels are limited to 120 characters.")
    if expires_at is not None:
        expires_at = float(expires_at)
        if expires_at <= time.time():
            raise ValueError("Invitation expiry must be in the future.")
    if max_devices in ("", None, 0, "0"):
        max_devices = None
    else:
        try:
            max_devices = int(max_devices)
        except (TypeError, ValueError):
            raise ValueError("Device limit must be a number.")
        if max_devices < 1 or max_devices > 20:
            raise ValueError("Device limit must be between 1 and 20, or unlimited.")
    role = str(role or 'player').strip().lower()
    if role not in {'player','observer','guest','co-gm'}:
        role = 'player'
    nonce = secrets.token_urlsafe(18)
    now = time.time()
    with connect(settings) as conn:
        cur = conn.execute(
            "INSERT INTO player_invites(label,nonce,access_version,created_at,expires_at,max_devices,role) VALUES(?,?,?,?,?,?,?)",
            (label, nonce, 1, now, expires_at, max_devices, role),
        )
        row = conn.execute("SELECT * FROM player_invites WHERE id=?", (cur.lastrowid,)).fetchone()
    return _invite_payload(settings, row, now)


def _attach_invite_devices(settings: Settings, payload: dict) -> dict:
    with connect(settings) as conn:
        rows = conn.execute(
            "SELECT id,user_agent,created_at,last_seen_at FROM player_devices WHERE invite_id=? AND access_version=? ORDER BY created_at",
            (int(payload["id"]), int(payload["access_version"])),
        ).fetchall()
    payload["devices"] = [dict(row) for row in rows]
    payload["device_count"] = len(rows)
    return payload


def list_player_invites(settings: Settings) -> list[dict]:
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM player_invites ORDER BY created_at DESC, id DESC").fetchall()
    now = time.time()
    return [_attach_invite_devices(settings, _invite_payload(settings, row, now)) for row in rows]


def get_player_invite(settings: Settings, invite_id: int) -> dict | None:
    try:
        invite_id = int(invite_id)
    except (TypeError, ValueError):
        return None
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM player_invites WHERE id=?", (invite_id,)).fetchone()
    return _attach_invite_devices(settings, _invite_payload(settings, row)) if row else None


def resolve_player_invite(settings: Settings, token: str, *, record_use: bool = True) -> dict | None:
    parts = str(token or "").split(".")
    if len(parts) != 5 or parts[0] != "lf1":
        return None
    try:
        invite_id = int(parts[1])
        version = int(parts[2])
    except ValueError:
        return None
    nonce, supplied_sig = parts[3], parts[4]
    if not nonce or not supplied_sig:
        return None
    with connect(settings) as conn:
        row = conn.execute("SELECT * FROM player_invites WHERE id=?", (invite_id,)).fetchone()
        if not row:
            return None
        if int(row["access_version"]) != version or not secrets.compare_digest(str(row["nonce"]), nonce):
            return None
        expected = _invite_signature(settings, invite_id, version, nonce)
        if not secrets.compare_digest(expected, supplied_sig):
            return None
        payload = _invite_payload(settings, row)
        if not payload["active"]:
            return None
        if record_use:
            now = time.time()
            conn.execute("UPDATE player_invites SET last_used_at=?, use_count=use_count+1 WHERE id=?", (now, invite_id))
            row = conn.execute("SELECT * FROM player_invites WHERE id=?", (invite_id,)).fetchone()
            payload = _invite_payload(settings, row, now)
    return payload


def register_player_device(
    settings: Settings, invite_id: int, version: int, *, existing_device_id: str | None = None, user_agent: str = ""
) -> str:
    invite = get_player_invite(settings, invite_id)
    if not invite or not invite["active"] or int(invite["access_version"]) != int(version):
        raise ValueError("Invitation is no longer active.")
    now = time.time()
    user_agent = str(user_agent or "")[:240]
    with connect(settings) as conn:
        if existing_device_id:
            row = conn.execute(
                "SELECT id FROM player_devices WHERE id=? AND invite_id=? AND access_version=?",
                (str(existing_device_id), int(invite_id), int(version)),
            ).fetchone()
            if row:
                conn.execute("UPDATE player_devices SET last_seen_at=?, user_agent=? WHERE id=?", (now, user_agent, row["id"]))
                return str(row["id"])
        count = conn.execute(
            "SELECT COUNT(*) FROM player_devices WHERE invite_id=? AND access_version=?",
            (int(invite_id), int(version)),
        ).fetchone()[0]
        limit = invite.get("max_devices")
        if limit is not None and int(count) >= int(limit):
            raise ValueError(f"This invitation has reached its {int(limit)}-device limit. Ask your GM to reset devices or create a new link.")
        device_id = secrets.token_urlsafe(18)
        conn.execute(
            "INSERT INTO player_devices(id,invite_id,access_version,user_agent,created_at,last_seen_at) VALUES(?,?,?,?,?,?)",
            (device_id, int(invite_id), int(version), user_agent, now, now),
        )
    return device_id


def validate_player_invite_session(
    settings: Settings, invite_id: int | None, version: int | None, device_id: str | None = None
) -> dict | None:
    """Validate a request session with one SQLite round-trip.

    v4 used get_player_invite() here, which also loaded the complete device list,
    then opened another connection to validate the current device. On pages that
    ask about the current invitation several times this multiplied into dozens of
    tiny DB reads. The request layer now caches this result too, so one request
    performs at most one invite validation query.
    """
    if invite_id is None or version is None or not device_id:
        return None
    try:
        invite_id_i, version_i = int(invite_id), int(version)
    except (TypeError, ValueError):
        return None
    with connect(settings) as conn:
        row = conn.execute(
            """SELECT i.* FROM player_invites i
               JOIN player_devices d ON d.invite_id=i.id AND d.access_version=i.access_version
               WHERE i.id=? AND i.access_version=? AND d.id=? LIMIT 1""",
            (invite_id_i, version_i, str(device_id)),
        ).fetchone()
    if not row:
        return None
    payload = _invite_payload(settings, row)
    return payload if payload["active"] else None


def reset_player_invite_devices(settings: Settings, invite_id: int) -> dict:
    invite = get_player_invite(settings, invite_id)
    if not invite:
        raise ValueError("Invitation not found.")
    with connect(settings) as conn:
        conn.execute("DELETE FROM player_devices WHERE invite_id=?", (int(invite_id),))
    return get_player_invite(settings, invite_id)


def revoke_player_invite(settings: Settings, invite_id: int) -> dict:
    invite = get_player_invite(settings, invite_id)
    if not invite:
        raise ValueError("Invitation not found.")
    with connect(settings) as conn:
        conn.execute("UPDATE player_invites SET revoked_at=? WHERE id=?", (time.time(), int(invite_id)))
        row = conn.execute("SELECT * FROM player_invites WHERE id=?", (int(invite_id),)).fetchone()
    return _invite_payload(settings, row)


def restore_player_invite(settings: Settings, invite_id: int) -> dict:
    invite = get_player_invite(settings, invite_id)
    if not invite:
        raise ValueError("Invitation not found.")
    with connect(settings) as conn:
        conn.execute("UPDATE player_invites SET revoked_at=NULL WHERE id=?", (int(invite_id),))
        row = conn.execute("SELECT * FROM player_invites WHERE id=?", (int(invite_id),)).fetchone()
    return _invite_payload(settings, row)


def rotate_player_invite(settings: Settings, invite_id: int) -> dict:
    invite = get_player_invite(settings, invite_id)
    if not invite:
        raise ValueError("Invitation not found.")
    nonce = secrets.token_urlsafe(18)
    new_expiry = None if invite.get("expired") else invite.get("expires_at")
    with connect(settings) as conn:
        conn.execute(
            "UPDATE player_invites SET nonce=?, access_version=access_version+1, revoked_at=NULL, expires_at=? WHERE id=?",
            (nonce, new_expiry, int(invite_id)),
        )
        conn.execute("DELETE FROM player_devices WHERE invite_id=?", (int(invite_id),))
        row = conn.execute("SELECT * FROM player_invites WHERE id=?", (int(invite_id),)).fetchone()
    return _attach_invite_devices(settings, _invite_payload(settings, row))


def delete_player_invite(settings: Settings, invite_id: int) -> None:
    with connect(settings) as conn:
        cur = conn.execute("DELETE FROM player_invites WHERE id=?", (int(invite_id),))
    if cur.rowcount == 0:
        raise ValueError("Invitation not found.")


def _clamp_number(value, minimum: float, maximum: float, default: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _normalize_codex_presentation(payload: dict | None = None) -> dict:
    payload = payload or {}
    visibility = str(payload.get("visibility") or "public").lower()
    if visibility not in {"public", "teaser", "hidden"}:
        visibility = "public"
    hero_style = str(payload.get("hero_style") or "banner").lower()
    if hero_style not in {"banner", "split", "portrait", "minimal"}:
        hero_style = "banner"
    article_layout = str(payload.get("article_layout") or "standard").lower()
    if article_layout not in {"standard", "wide", "cinematic"}:
        article_layout = "standard"
    return {
        "toc_image": str(payload.get("toc_image") or "").strip(),
        "hero_image": str(payload.get("hero_image") or "").strip(),
        "background_image": str(payload.get("background_image") or "").strip(),
        "background_opacity": _clamp_number(payload.get("background_opacity"), 0, 0.8, 0.16),
        "background_x": _clamp_number(payload.get("background_x"), 0, 100, 50),
        "background_y": _clamp_number(payload.get("background_y"), 0, 100, 50),
        "hero_style": hero_style,
        "article_layout": article_layout,
        "visibility": visibility,
        "featured": bool(payload.get("featured", False)),
    }


def get_codex_presentation(settings: Settings, target_type: str, target_key: str) -> dict:
    target_type = str(target_type or "").lower()
    target_key = str(target_key or "")
    with connect(settings) as conn:
        row = conn.execute(
            "SELECT * FROM codex_presentation WHERE target_type=? AND target_key=?",
            (target_type, target_key),
        ).fetchone()
    if not row:
        return _normalize_codex_presentation()
    return _normalize_codex_presentation(dict(row))


def list_codex_presentations(settings: Settings) -> dict[tuple[str, str], dict]:
    with connect(settings) as conn:
        rows = conn.execute("SELECT * FROM codex_presentation").fetchall()
    return {(row["target_type"], row["target_key"]): _normalize_codex_presentation(dict(row)) for row in rows}


def save_codex_presentation(settings: Settings, target_type: str, target_key: str, payload: dict) -> dict:
    target_type = str(target_type or "").lower().strip()
    target_key = str(target_key or "").strip()
    if target_type not in {"page", "category"}:
        raise ValueError("Codex presentation target must be a page or category.")
    if not target_key or len(target_key) > 240:
        raise ValueError("Invalid codex presentation target.")
    current = get_codex_presentation(settings, target_type, target_key)
    current.update({k: v for k, v in (payload or {}).items() if k in current})
    data = _normalize_codex_presentation(current)
    now = time.time()
    with connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO codex_presentation(
                target_type,target_key,toc_image,hero_image,background_image,background_opacity,
                background_x,background_y,hero_style,article_layout,visibility,featured,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(target_type,target_key) DO UPDATE SET
                toc_image=excluded.toc_image, hero_image=excluded.hero_image,
                background_image=excluded.background_image, background_opacity=excluded.background_opacity,
                background_x=excluded.background_x, background_y=excluded.background_y,
                hero_style=excluded.hero_style, article_layout=excluded.article_layout,
                visibility=excluded.visibility, featured=excluded.featured, updated_at=excluded.updated_at
            """,
            (
                target_type, target_key, data["toc_image"], data["hero_image"], data["background_image"],
                data["background_opacity"], data["background_x"], data["background_y"], data["hero_style"],
                data["article_layout"], data["visibility"], int(data["featured"]), now,
            ),
        )
    return data


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
                raise ValueError("The ZIP expands beyond Seeker's 2 GB import safety limit.")
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
        try:
            if item.is_symlink():
                # Count only the link itself. Following it would make a zero-copy
                # preview alias look like a second 100+ MB PDF in storage reports.
                total += item.lstat().st_size
            elif item.is_file():
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
