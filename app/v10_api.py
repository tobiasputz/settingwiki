from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from fastapi import Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from .campaigns import campaign_members, invite_has_campaign
from .features import get_live_session, list_handouts, list_sessions, save_handout
from .living import list_submissions
from .maps import list_maps
from .realtime import BUS
from .storage import connect, get_player_invite
from .v6 import list_backups, queue_foundry_command, set_display_state
from .v7 import entity_relations, reveal_fact_to_party, visible_entity_facts
from .v8 import entity_inspector
from .v9 import apply_map_state, foundry_sync_matrix, list_map_states, relationship_suggestions
from .v10 import (
    asset_storage_summary,
    delete_cue,
    diagnostic_events,
    get_cue,
    indexed_assets,
    list_cues,
    log_diagnostic,
    mark_cue,
    migration_registry,
    performance_summary,
    refresh_asset_index,
    save_cue,
    table_counts,
)


def register_v10_routes(app, settings, helpers: dict[str, Callable[..., Any]]) -> None:
    active_campaign_id = helpers["active_campaign_id"]
    visible_wiki = helpers["visible_wiki"]
    require_gm = helpers["require_gm"]
    require_admin = helpers["require_admin"]
    player_allowed = helpers["player_allowed"]
    requester_label = helpers["requester_label"]

    @app.get("/api/events")
    async def realtime_events(request: Request):
        if not player_allowed(request):
            raise HTTPException(401)
        cid = active_campaign_id(request)
        try:
            last = int(request.headers.get("last-event-id") or request.query_params.get("since") or 0)
        except (TypeError, ValueError):
            last = 0

        async def stream():
            nonlocal last
            yield "retry: 4000\n\n"
            hello = BUS.publish("stream.ready", campaign_id=cid, payload={"heartbeat": True})
            last = max(last, hello.seq)
            yield BUS.sse(hello)
            last_heartbeat = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                events = BUS.after(last, campaign_id=cid)
                for event in events:
                    last = max(last, event.seq)
                    yield BUS.sse(event)
                if time.monotonic() - last_heartbeat > 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(0.8)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v10/attention")
    def attention(request: Request):
        require_gm(request)
        cid = active_campaign_id(request)
        wiki = visible_wiki(request)
        items: list[dict] = []
        pending = [x for x in list_submissions(settings, admin=True, campaign_id=cid) if str(x.get("status")) == "pending"]
        if pending:
            items.append({"kind": "submissions", "severity": "info", "title": f"{len(pending)} player submission{'s' if len(pending) != 1 else ''} waiting", "detail": "Review player contributions before they disappear into the backlog.", "href": "/admin/living#submissions"})
        suggestions = relationship_suggestions(settings, cid, wiki, refresh=False)
        if suggestions:
            items.append({"kind": "relations", "severity": "info", "title": f"{len(suggestions)} relationship suggestion{'s' if len(suggestions) != 1 else ''}", "detail": "Suggestions remain opt-in; nothing is created automatically.", "href": "/app/v8#entities"})
        matrix = foundry_sync_matrix(settings, cid)
        failed = [x for x in matrix.get("commands", []) if str(x.get("status")) == "failed"]
        conflicts = [x for x in matrix.get("rows", []) if str(x.get("status")) in {"conflict", "seeker_newer", "foundry_newer"}]
        if failed:
            items.append({"kind": "foundry", "severity": "error", "title": f"{len(failed)} Foundry delivery failure{'s' if len(failed) != 1 else ''}", "detail": "Open Foundry sync to inspect and retry failed writes.", "href": "/app/v8#foundry"})
        if conflicts:
            items.append({"kind": "foundry", "severity": "warning", "title": f"{len(conflicts)} Foundry sync conflict{'s' if len(conflicts) != 1 else ''}", "detail": "Choose which side should win before the next edit.", "href": "/app/v8#foundry"})
        recent_errors = [x for x in diagnostic_events(settings, cid, 40) if x.get("level") == "error"]
        if recent_errors:
            items.append({"kind": "diagnostics", "severity": "warning", "title": f"{len(recent_errors)} recent application error{'s' if len(recent_errors) != 1 else ''}", "detail": str(recent_errors[0].get("message") or "Open diagnostics for details.")[:180], "href": "/app/v8#diagnostics"})
        backups = list_backups(settings)
        latest = max((float(x.get("created_at") or 0) for x in backups), default=0)
        if not latest or time.time() - latest > 36 * 3600:
            items.append({"kind": "backup", "severity": "warning", "title": "Campaign backup is getting old" if latest else "No campaign backup found", "detail": "Create a fresh portable backup before substantial editing.", "href": "/app/v8#diagnostics"})
        return {"items": items, "count": len(items)}

    @app.get("/api/v10/view-as")
    def view_as_state(request: Request):
        require_admin(request)
        cid = active_campaign_id(request)
        rows = []
        now = time.time()
        for row in campaign_members(settings, cid):
            expires = row.get("expires_at")
            inactive = bool(row.get("revoked_at")) or bool(expires is not None and float(expires) <= now)
            if not row.get("campaign_member") or inactive:
                continue
            rows.append({"id": int(row["id"]), "label": row.get("label") or "Player", "role": row.get("role") or "player"})
        return {"active": request.session.get("view_as_invite_id"), "members": rows}

    @app.post("/api/v10/view-as")
    def view_as_set(request: Request, payload: dict = Body(...)):
        # Raw owner session check is intentional: the owner chooses the target
        # before effective permissions switch to the player's view.
        if not request.session.get("admin"):
            raise HTTPException(401, "Campaign owner login required")
        cid = active_campaign_id(request)
        try:
            invite_id = int(payload.get("invite_id"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Choose a player.")
        invite = get_player_invite(settings, invite_id)
        if not invite or not invite.get("active") or not invite_has_campaign(settings, invite_id, cid):
            raise HTTPException(404, "That player is not an active member of this campaign.")
        request.session["view_as_invite_id"] = invite_id
        request.session["view_as_label"] = str(invite.get("label") or "Player")[:160]
        # Make the viewed campaign deterministic and keep the normal player
        # membership resolver in charge from this point onward.
        request.session["active_campaign_id"] = cid
        return {"ok": True, "invite_id": invite_id, "label": request.session["view_as_label"]}

    @app.delete("/api/v10/view-as")
    def view_as_clear(request: Request):
        if not request.session.get("admin"):
            raise HTTPException(401, "Campaign owner login required")
        request.session.pop("view_as_invite_id", None)
        request.session.pop("view_as_label", None)
        return {"ok": True}

    @app.get("/api/v10/object/{entity_id}")
    def universal_object(request: Request, entity_id: int):
        require_gm(request)
        cid = active_campaign_id(request)
        try:
            base = entity_inspector(settings, cid, entity_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        relations = entity_relations(settings, cid, entity_id)
        facts = visible_entity_facts(settings, entity_id, None, gm=True)
        with connect(settings) as conn:
            appearances = [dict(r) for r in conn.execute(
                """SELECT t.*,s.title AS session_title,s.session_date
                   FROM v8_session_touches t LEFT JOIN campaign_sessions s ON s.id=t.session_id
                   WHERE t.campaign_id=? AND t.target_type='entity' AND t.target_key=?
                   ORDER BY t.created_at DESC LIMIT 20""",
                (cid, str(entity_id)),
            ).fetchall()]
        return {
            **base,
            "relations": relations,
            "facts": facts,
            "appearances": appearances,
            "context": {
                "live_session": get_live_session(settings, admin=True, campaign_id=cid),
                "maps": list_maps(settings, public=False),
            },
        }

    @app.get("/api/v10/diagnostics")
    def extended_diagnostics(request: Request):
        require_gm(request)
        cid = active_campaign_id(request)
        # Keep the index hot while diagnostics is explicitly open; the refresh
        # performs cheap stat checks and hashes only changed files.
        refresh_asset_index(settings)
        return {
            "events": diagnostic_events(settings, cid, 80),
            "performance": performance_summary(settings, cid, 24),
            "assets": asset_storage_summary(settings),
            "migrations": migration_registry(settings),
            "database": table_counts(settings),
        }

    @app.post("/api/v10/diagnostics/browser")
    def browser_diagnostic(request: Request, payload: dict = Body(...)):
        if not player_allowed(request):
            raise HTTPException(401)
        try:
            cid = active_campaign_id(request)
        except Exception:
            cid = None
        log_diagnostic(
            settings,
            campaign_id=cid,
            level="error",
            subsystem="browser",
            event_type=str(payload.get("event_type") or "browser.error")[:100],
            message=str(payload.get("message") or "Browser error")[:1800],
            path=str(payload.get("path") or request.headers.get("referer") or "")[:500],
            meta={"source": payload.get("source"), "line": payload.get("line"), "column": payload.get("column")},
        )
        return {"ok": True}

    @app.post("/api/v10/assets/reindex")
    def assets_reindex(request: Request):
        require_gm(request)
        result = refresh_asset_index(settings, force=True)
        result["assets"] = len(indexed_assets(settings, refresh=False))
        return result

    @app.get("/api/v10/cues")
    def cues_get(request: Request, session_id: int | None = None):
        require_gm(request)
        cid = active_campaign_id(request)
        return {
            "cues": list_cues(settings, cid, session_id),
            "handouts": list_handouts(settings, admin=True, campaign_id=cid),
            "map_states": list_map_states(settings, cid),
            "sessions": list_sessions(settings, public=False, campaign_id=cid),
        }

    @app.post("/api/v10/cues")
    def cues_save(request: Request, payload: dict = Body(...)):
        require_gm(request)
        try:
            return save_cue(settings, active_campaign_id(request), payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.put("/api/v10/cues/{cue_id}")
    def cues_update(request: Request, cue_id: int, payload: dict = Body(...)):
        require_gm(request)
        try:
            return save_cue(settings, active_campaign_id(request), {**payload, "id": cue_id})
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.delete("/api/v10/cues/{cue_id}")
    def cues_delete(request: Request, cue_id: int):
        require_gm(request)
        delete_cue(settings, active_campaign_id(request), cue_id)
        return {"ok": True}

    @app.post("/api/v10/cues/{cue_id}/skip")
    def cues_skip(request: Request, cue_id: int):
        require_gm(request)
        try:
            return mark_cue(settings, active_campaign_id(request), cue_id, "skipped")
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @app.post("/api/v10/cues/{cue_id}/execute")
    def cues_execute(request: Request, cue_id: int):
        require_gm(request)
        cid = active_campaign_id(request)
        cue = get_cue(settings, cid, cue_id)
        if not cue:
            raise HTTPException(404, "Cue not found.")
        payload = cue.get("payload") or {}
        kind = str(cue.get("kind") or "note")
        result: Any = {"ok": True}
        try:
            if kind == "reveal_handout":
                hid = int(cue.get("target_key") or payload.get("handout_id") or 0)
                row = next((x for x in list_handouts(settings, admin=True, campaign_id=cid) if int(x.get("id") or 0) == hid), None)
                if not row:
                    raise ValueError("Handout not found.")
                result = save_handout(settings, {**row, "visibility": "players", "campaign_id": cid})
            elif kind == "reveal_fact":
                fid = int(cue.get("target_key") or payload.get("fact_id") or 0)
                rows = reveal_fact_to_party(settings, cid, fid, str(payload.get("disclosure_mode") or "exact"), payload.get("session_id"), reveal_source="gm")
                result = {"ok": True, "revealed_to": len(rows)}
            elif kind == "display":
                result = set_display_state(settings, cid, payload)
            elif kind == "map_state":
                sid = int(cue.get("target_key") or payload.get("state_id") or 0)
                result = apply_map_state(settings, cid, sid)
            elif kind == "foundry":
                result = queue_foundry_command(
                    settings,
                    cid,
                    str(payload.get("command_type") or ""),
                    payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
                    actor_id=str(payload.get("actor_id") or ""),
                    scope=str(payload.get("scope") or "actor"),
                    requested_by=requester_label(request),
                )
            elif kind in {"note", "open_object"}:
                result = {"ok": True, "href": payload.get("href") or ""}
            else:
                raise ValueError("Unknown cue type.")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        cue = mark_cue(settings, cid, cue_id, "done")
        BUS.publish("cue.executed", campaign_id=cid, path=f"/api/v10/cues/{cue_id}/execute", payload={"cue_id": cue_id, "kind": kind})
        return {"cue": cue, "result": result}
