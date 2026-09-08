from __future__ import annotations

import json
import re
import time
from copy import deepcopy

from .config import Settings
from .storage import connect


DEFAULT_EFFECTS: dict = {
    # View and markers
    "viewport_mode": "cover",       # cover keeps map edges at the viewport edges
    "edge_lock": True,
    "marker_labels": True,
    "marker_pulse": True,
    "marker_scale": 1.0,
    # Global animation controls
    "effect_intensity": 0.58,
    "motion_speed": 0.65,
    # Sky / atmosphere
    "clouds": True,
    "cloud_shadows": False,
    "fog": False,
    "low_mist": False,
    "sun_rays": False,
    "aurora": False,
    "stars": False,
    "shooting_stars": False,
    # Weather / terrain
    "rain": False,
    "lightning": False,
    "snow": False,
    "blizzard": False,
    "ash": False,
    "dust": False,
    "heat_haze": False,
    "ocean_shimmer": False,
    "wave_crests": False,
    # Living world
    "embers": False,
    "fireflies": False,
    "pollen": False,
    "leaves": False,
    "petals": False,
    "birds": False,
    "bats": False,
    "dragon_shadow": False,
    # Magical / supernatural
    "magic_motes": False,
    "spectral_wisps": False,
    "cursed_miasma": False,
    "ley_lines": False,
    "rune_pulses": False,
    "spores": False,
    # Cartographic finish
    "vignette": True,
    "parchment": False,
    "moonlight": False,
    "blood_moon": False,
    "edge_fog": False,
    "grid": False,
    "compass": True,
}


BOOLEAN_EFFECT_KEYS = {
    key for key, value in DEFAULT_EFFECTS.items() if isinstance(value, bool)
}
NUMERIC_EFFECT_KEYS = {"marker_scale", "effect_intensity", "motion_speed"}


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "map"


def normalize_effects(raw: object, *, legacy: dict | None = None) -> dict:
    effects = deepcopy(DEFAULT_EFFECTS)
    if legacy:
        effects["clouds"] = bool(legacy.get("cloud_enabled", True))
        try:
            effects["effect_intensity"] = max(0.05, min(1.0, float(legacy.get("cloud_opacity", effects["effect_intensity"])) * 1.7))
            effects["motion_speed"] = max(0.05, min(2.0, float(legacy.get("cloud_speed", effects["motion_speed"]))))
        except (TypeError, ValueError):
            pass
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except json.JSONDecodeError:
            raw = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key not in effects:
                continue
            if key in BOOLEAN_EFFECT_KEYS:
                effects[key] = bool(value)
            elif key in NUMERIC_EFFECT_KEYS:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if key == "marker_scale":
                    effects[key] = max(0.65, min(1.8, number))
                elif key == "effect_intensity":
                    effects[key] = max(0.05, min(1.0, number))
                else:
                    effects[key] = max(0.05, min(2.0, number))
            elif key == "viewport_mode":
                effects[key] = value if value in {"cover", "contain"} else "cover"
    return effects


def _normalize_map(row: dict, markers: list[dict]) -> dict:
    m = dict(row)
    m["markers"] = markers
    m["cloud_enabled"] = bool(m.get("cloud_enabled", 1))
    effects_raw = m.get("effects_json", "{}")
    m["effects"] = normalize_effects(effects_raw, legacy=m)
    # Do not expose an implementation detail to Jinja/client JSON.
    m.pop("effects_json", None)
    for marker in m["markers"]:
        marker["visible_to_players"] = bool(marker["visible_to_players"])
    return m


def list_maps(settings: Settings, *, public: bool = False) -> list[dict]:
    with connect(settings) as conn:
        maps = [dict(r) for r in conn.execute("SELECT * FROM maps ORDER BY sort_order, name").fetchall()]
        result = []
        for m in maps:
            q = "SELECT * FROM markers WHERE map_id=?" + (" AND visible_to_players=1" if public else "") + " ORDER BY id"
            markers = [dict(x) for x in conn.execute(q, (m["id"],)).fetchall()]
            result.append(_normalize_map(m, markers))
    return result


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
        markers = [dict(x) for x in conn.execute(q, (m["id"],)).fetchall()]
    return _normalize_map(m, markers)


def create_map(settings: Settings, name: str, image_path: str, description: str = "") -> dict:
    now = time.time(); base = slugify(name); slug = base
    effects_json = json.dumps(DEFAULT_EFFECTS, separators=(",", ":"))
    with connect(settings) as conn:
        i = 2
        while conn.execute("SELECT 1 FROM maps WHERE slug=?", (slug,)).fetchone():
            slug = f"{base}-{i}"; i += 1
        cur = conn.execute(
            "INSERT INTO maps(name,slug,image_path,description,effects_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (name.strip() or "Untitled Map", slug, image_path, description, effects_json, now, now),
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
    if "effects" in payload:
        # Merge with the stored map so partial saves remain forward compatible.
        current = get_map(settings, map_id)
        merged_raw = dict((current or {}).get("effects") or {})
        if isinstance(payload.get("effects"), dict):
            merged_raw.update(payload["effects"])
        merged = normalize_effects(merged_raw, legacy=current or {})
        fields.append("effects_json=?")
        values.append(json.dumps(merged, separators=(",", ":")))
        # Keep v1 cloud columns synchronized for backwards compatibility.
        if "cloud_enabled" not in payload:
            fields.append("cloud_enabled=?"); values.append(1 if merged["clouds"] else 0)
        if "cloud_opacity" not in payload:
            fields.append("cloud_opacity=?"); values.append(min(0.8, merged["effect_intensity"] / 1.7))
        if "cloud_speed" not in payload:
            fields.append("cloud_speed=?"); values.append(merged["motion_speed"])
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
        map_id, str(payload.get("title") or "New location"), str(payload.get("body") or ""),
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
