from __future__ import annotations

import datetime as dt
import time
from typing import Any

from .config import Settings
from .storage import connect

AVAILABILITY_STATUSES = {"available", "if_needed", "unavailable"}

SCHEDULE_SCHEMA = r'''
CREATE TABLE IF NOT EXISTS player_availability (
    invite_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL,
    PRIMARY KEY(invite_id,date),
    FOREIGN KEY(invite_id) REFERENCES player_invites(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_player_availability_date ON player_availability(date,invite_id);
CREATE INDEX IF NOT EXISTS idx_player_availability_invite_date ON player_availability(invite_id,date);
'''


def init_schedule_db(settings: Settings) -> None:
    with connect(settings) as conn:
        conn.executescript(SCHEDULE_SCHEMA)


def _date(value: Any) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value or ""))
    except Exception as exc:
        raise ValueError("Dates must use YYYY-MM-DD.") from exc


def _range(start: Any, end: Any, *, max_days: int = 370) -> tuple[dt.date, dt.date]:
    a, b = _date(start), _date(end)
    if b < a:
        raise ValueError("End date must not be before start date.")
    if (b - a).days > max_days:
        raise ValueError(f"Choose a range of at most {max_days + 1} days.")
    return a, b


def list_player_availability(settings: Settings, invite_id: int, start: Any, end: Any) -> list[dict]:
    a, b = _range(start, end)
    with connect(settings) as conn:
        rows = conn.execute(
            "SELECT date,status,note,updated_at FROM player_availability WHERE invite_id=? AND date BETWEEN ? AND ? ORDER BY date",
            (int(invite_id), a.isoformat(), b.isoformat()),
        ).fetchall()
    return [dict(r) for r in rows]


def save_player_availability(settings: Settings, invite_id: int, changes: list[dict]) -> list[dict]:
    if not isinstance(changes, list):
        raise ValueError("Availability changes must be a list.")
    if len(changes) > 370:
        raise ValueError("Too many dates in one update.")
    normalized: dict[str, tuple[str, str]] = {}
    today = dt.date.today()
    max_date = today + dt.timedelta(days=730)
    for item in changes:
        if not isinstance(item, dict):
            continue
        day = _date(item.get("date"))
        if day < today - dt.timedelta(days=2) or day > max_date:
            raise ValueError("Availability can be edited from today through the next two years.")
        status = str(item.get("status") or "").strip().lower()
        if status and status not in AVAILABILITY_STATUSES:
            raise ValueError("Availability must be available, if_needed, unavailable, or blank.")
        note = str(item.get("note") or "")[:500]
        normalized[day.isoformat()] = (status, note)
    now = time.time(); iid=int(invite_id)
    deletes=[(iid,date_s) for date_s,(status,_note) in normalized.items() if not status]
    upserts=[(iid,date_s,status,note,now) for date_s,(status,note) in normalized.items() if status]
    with connect(settings) as conn:
        if deletes:
            conn.executemany("DELETE FROM player_availability WHERE invite_id=? AND date=?",deletes)
        if upserts:
            conn.executemany(
                """INSERT INTO player_availability(invite_id,date,status,note,updated_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(invite_id,date) DO UPDATE SET status=excluded.status,note=excluded.note,updated_at=excluded.updated_at""",
                upserts,
            )
    return [{"date": d, "status": s, "note": n} for d, (s, n) in sorted(normalized.items())]


def player_campaigns(settings: Settings, invite_id: int) -> list[dict]:
    """Campaigns this player participates in via at least one character.

    Availability itself is deliberately *not* campaign-scoped. The character is
    the bridge between one player identity and one or more campaign tables.
    """
    with connect(settings) as conn:
        rows = conn.execute(
            """SELECT c.id,c.name,c.slug,c.accent,c.status,
                      GROUP_CONCAT(pc.name, ' / ') AS characters
               FROM campaigns c
               JOIN player_characters pc ON pc.campaign_id=c.id
               WHERE pc.invite_id=? AND c.status='active'
               GROUP BY c.id,c.name,c.slug,c.accent,c.status
               ORDER BY c.name COLLATE NOCASE,c.id""",
            (int(invite_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def campaign_schedule_participants(settings: Settings, campaign_id: int) -> list[dict]:
    """Unique players represented by a current character in this campaign.

    Character assignment is the scheduling source of truth. Availability is
    player-level and must keep applying even if campaign membership bookkeeping
    is edited later by a GM. This also prevents the same person from appearing
    twice when they have multiple PCs.
    """
    inactive = ("retired", "dead", "inactive")
    now = time.time()
    with connect(settings) as conn:
        rows = conn.execute(
            """SELECT i.id AS invite_id,i.label,
                      GROUP_CONCAT(pc.name, ' / ') AS characters
               FROM player_characters pc
               JOIN player_invites i ON i.id=pc.invite_id
               WHERE pc.campaign_id=?
                 AND LOWER(COALESCE(pc.status,'active')) NOT IN (?,?,?)
                 AND i.revoked_at IS NULL
                 AND (i.expires_at IS NULL OR i.expires_at>?)
               GROUP BY i.id,i.label
               ORDER BY i.label COLLATE NOCASE,i.id""",
            (int(campaign_id), *inactive, now),
        ).fetchall()
    return [dict(r) for r in rows]


def campaign_schedule(settings: Settings, campaign_id: int, start: Any, end: Any) -> dict:
    a, b = _range(start, end)
    participants = campaign_schedule_participants(settings, int(campaign_id))
    ids = [int(p["invite_id"]) for p in participants]
    by_player: dict[int, dict[str, str]] = {iid: {} for iid in ids}
    if ids:
        placeholders = ",".join("?" for _ in ids)
        with connect(settings) as conn:
            rows = conn.execute(
                f"SELECT invite_id,date,status FROM player_availability WHERE invite_id IN ({placeholders}) AND date BETWEEN ? AND ?",
                tuple(ids) + (a.isoformat(), b.isoformat()),
            ).fetchall()
        for row in rows:
            by_player[int(row["invite_id"])][str(row["date"])] = str(row["status"])

    days: list[dict] = []
    day = a
    total = len(participants)
    while day <= b:
        key = day.isoformat()
        detail = []
        counts = {"available": 0, "if_needed": 0, "unavailable": 0, "unknown": 0}
        for p in participants:
            status = by_player[int(p["invite_id"])].get(key, "unknown")
            counts[status] += 1
            detail.append({"invite_id": int(p["invite_id"]), "label": p["label"], "characters": p.get("characters") or "", "status": status})
        if total and counts["available"] == total:
            state = "all_available"
        elif total and counts["unknown"] == 0 and counts["unavailable"] == 0:
            state = "if_needed"
        elif counts["unavailable"]:
            state = "blocked"
        else:
            state = "waiting"
        days.append({"date": key, "state": state, "counts": counts, "players": detail})
        day += dt.timedelta(days=1)

    all_green = [d for d in days if d["state"] == "all_available"]
    soft = [d for d in days if d["state"] == "if_needed"]
    # Soft candidates with fewer reluctant players are more useful; chronology
    # breaks ties. The headline still uses the earliest all-green date.
    soft_ranked = sorted(soft, key=lambda d: (d["counts"]["if_needed"], d["date"]))
    candidates = all_green[:8]
    if len(candidates) < 8:
        candidates += soft_ranked[: 8 - len(candidates)]
    coverage = []
    span = max(1, (b - a).days + 1)
    for p in participants:
        entries = by_player[int(p["invite_id"])]
        responded = sum(1 for k in entries if a.isoformat() <= k <= b.isoformat())
        coverage.append({**p, "responded_days": responded, "coverage": round(responded / span, 3)})
    return {
        "campaign_id": int(campaign_id),
        "start": a.isoformat(),
        "end": b.isoformat(),
        "participants": coverage,
        "days": days,
        "next_all_available": all_green[0] if all_green else None,
        "next_if_needed": soft[0] if soft else None,
        "candidates": candidates,
    }
