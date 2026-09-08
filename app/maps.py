from __future__ import annotations

import re
import time
from pathlib import Path

from .config import Settings
from .storage import connect


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "map"


def list_maps(settings: Settings, *, public: bool = False) -> list[dict]:
    with connect(settings) as conn:
        maps = [dict(r) for r in conn.execute("SELECT * FROM maps ORDER BY sort_order, name").fetchall()]
        for m in maps:
            q = "SELECT * FROM markers WHERE map_id=?" + (" AND visible_to_players=1" if public else "") + " ORDER BY id"
            m["markers"] = [dict(x) for x in conn.execute(q, (m["id"],)).fetchall()]
            m["cloud_enabled"] = bool(m["cloud_enabled"])
            for marker in m["markers"]:
                marker["visible_to_players"] = bool(marker["visible_to_players"])
    return maps


def get_map(settings: Settings, map_id_or_slug: str | int, *, public: bool = False) -> dict | None:
    with connect(settings) as conn:
        if str(map_id_or_slug).isdigit():
            row = conn.execute("SELECT * FROM maps WHERE id=?", (int(map_id_or_slug),)).fetchone()
        else:
            row = conn.execute("SELECT * FROM maps WHERE slug=?", (str(map_id_or_slug),)).fetchone()
        if not row:
            return None
        m = dict(row)
        q = "SELECT * FROM markers WHERE map_id=?" + (" AND visible_to_players=1" if public else "") + " ORDER BY id"
        m["markers"] = [dict(x) for x in conn.execute(q, (m["id"],)).fetchall()]
    m["cloud_enabled"] = bool(m["cloud_enabled"])
    for marker in m["markers"]:
        marker["visible_to_players"] = bool(marker["visible_to_players"])
    return m


def create_map(settings: Settings, name: str, image_path: str, description: str = "") -> dict:
    now = time.time(); base = slugify(name); slug = base
    with connect(settings) as conn:
        i = 2
        while conn.execute("SELECT 1 FROM maps WHERE slug=?", (slug,)).fetchone():
            slug = f"{base}-{i}"; i += 1
        cur = conn.execute(
            "INSERT INTO maps(name,slug,image_path,description,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (name.strip() or "Untitled Map", slug, image_path, description, now, now),
        )
        map_id = cur.lastrowid
    return get_map(settings, map_id)  # type: ignore


def update_map(settings: Settings, map_id: int, payload: dict) -> dict | None:
    allowed = {"name", "description", "cloud_enabled", "cloud_opacity", "cloud_speed", "sort_order"}
    fields = []; values = []
    for key in allowed:
        if key in payload:
            fields.append(f"{key}=?")
            value = payload[key]
            if key == "cloud_enabled": value = 1 if value else 0
            values.append(value)
    if fields:
        values.extend([time.time(), map_id])
        with connect(settings) as conn:
            conn.execute(f"UPDATE maps SET {', '.join(fields)}, updated_at=? WHERE id=?", values)
    return get_map(settings, map_id)


def delete_map(settings: Settings, map_id: int) -> None:
    with connect(settings) as conn:
        row = conn.execute("SELECT image_path FROM maps WHERE id=?", (map_id,)).fetchone()
        conn.execute("DELETE FROM maps WHERE id=?", (map_id,))
    if row:
        p = settings.uploads_dir / row["image_path"]
        p.unlink(missing_ok=True)


def create_marker(settings: Settings, map_id: int, payload: dict) -> dict:
    now = time.time()
    values = (
        map_id, str(payload.get("title") or "New place"), str(payload.get("body") or ""),
        min(1.0, max(0.0, float(payload.get("x", 0.5)))), min(1.0, max(0.0, float(payload.get("y", 0.5)))),
        str(payload.get("kind") or "place"), payload.get("page_slug") or None,
        1 if payload.get("visible_to_players", True) else 0, now, now,
    )
    with connect(settings) as conn:
        cur = conn.execute("INSERT INTO markers(map_id,title,body,x,y,kind,page_slug,visible_to_players,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", values)
        marker_id = cur.lastrowid
        row = conn.execute("SELECT * FROM markers WHERE id=?", (marker_id,)).fetchone()
    d = dict(row); d["visible_to_players"] = bool(d["visible_to_players"]); return d


def update_marker(settings: Settings, marker_id: int, payload: dict) -> dict | None:
    allowed = {"title", "body", "x", "y", "kind", "page_slug", "visible_to_players"}
    fields=[]; values=[]
    for key in allowed:
        if key in payload:
            fields.append(f"{key}=?"); value=payload[key]
            if key == "visible_to_players": value=1 if value else 0
            if key in {"x","y"}: value=min(1.0,max(0.0,float(value)))
            values.append(value)
    if fields:
        values.extend([time.time(), marker_id])
        with connect(settings) as conn:
            conn.execute(f"UPDATE markers SET {', '.join(fields)}, updated_at=? WHERE id=?", values)
    with connect(settings) as conn:
        row=conn.execute("SELECT * FROM markers WHERE id=?",(marker_id,)).fetchone()
    if not row: return None
    d=dict(row); d["visible_to_players"]=bool(d["visible_to_players"]); return d


def delete_marker(settings: Settings, marker_id: int) -> None:
    with connect(settings) as conn:
        conn.execute("DELETE FROM markers WHERE id=?", (marker_id,))
