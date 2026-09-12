from __future__ import annotations

import functools
import html
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request as UrlRequest, build_opener, urlopen

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import load_settings
from .latex import analyze_project, build_wiki, choose_main, compile_pdf, compiled_pdf_path, load_wiki
from .maps import create_map, create_marker, delete_map, delete_marker, get_map, list_maps, map_locations_for_page, update_map, update_marker
from .storage import (
    cleanup_legacy_import_artifacts, connect, create_player_invite, delete_player_invite, export_project_zip,
    get_codex_presentation, get_setting, get_player_invite, init_db, list_player_invites, list_project_files, list_revisions,
    register_player_device, replace_project_from_zip, reset_player_invite_devices, resolve_player_invite,
    restore_player_invite, restore_revision, revoke_player_invite, rotate_player_invite, safe_project_path,
    save_codex_presentation, save_text_file, seed_project, set_setting, storage_report, validate_player_invite_session,
)
from .features import (
    add_annotation, delete_annotation, add_mystery_pin, add_session_update, aliases, apply_reveals_to_html, campaign_health,
    delete_mystery_edge, delete_mystery_pin,
    create_snapshot, delete_session, entity_style, fog_regions, get_live_session, init_feature_db,
    list_annotations, list_bookmarks, list_handouts, list_mysteries, list_relationships, list_reveal_blocks_from_wiki, list_reveal_states,
    list_sessions, session_appearances_for_page, list_snapshots, list_timeline, list_timeline_eras, list_variants, log_activity, map_layers, page_relationships,
    recent_updates, reveal_state, restore_snapshot, save_alias, save_entity_style, save_fog_region, save_handout, save_map_layer,
    save_mystery, save_mystery_edge, save_relationship, save_session, save_timeline_event, save_timeline_era, delete_timeline_era,
    save_variant, delete_variant, set_reveal, set_session_lore, toggle_bookmark, travel_between_markers,
    list_player_characters, get_player_character, save_player_character, delete_player_character, add_character_image, delete_character_image,
)

from .living import (
    init_living_db, knowledge_state, set_knowledge, list_knowledge, knowledge_index, knowledge_allows, list_fronts, save_front, advance_front,
    runtime_states, runtime_state_for_page, save_runtime_state, relationship_history, save_relationship_history, hierarchies, save_hierarchy_edge,
    map_regions, save_map_region, save_region_history, list_rumors, save_rumor, random_rumor, list_threads, save_thread, add_thread_note, update_thread_note, delete_thread_note, save_thread_link, delete_thread_link,
    list_journals, list_party_journals, save_journal, inbox_items, save_inbox, list_submissions, save_submission, review_submission,
    publishing_state, set_publishing_state, publishing_states, capture_session_state, session_state_snapshots, scan_suggestions, update_suggestion,
    list_media_catalog, save_media_meta, create_notification, list_notifications, mark_notification_read, dismiss_notification, delete_notification,
    character_relationships, save_character_relationship, character_arcs, save_character_arc, entity_provenance, continuity_report,
    export_foundry_journal, create_portable_archive, validate_portable_archive_file, media_usage, replace_media_reference,
)
from .campaigns import (
    list_campaigns, get_campaign, campaign_members, save_campaign, archive_campaign, delete_campaign, make_default_campaign,
    set_campaign_members, invite_has_campaign, resolve_campaign_id, default_campaign_id,
)
from .scheduling import (
    init_schedule_db, list_player_availability, save_player_availability, player_campaigns, campaign_schedule,
)
from .semantic_search import semantic_search
from .aon import sanitize_aon_summary
from .homebrew import (
    NON_MONSTER_KINDS, HOME_BREW_SECTIONS, HOME_BREW_SOURCE_TITLES, classify_homebrew, group_homebrew, homebrew_latex_snippet,
    is_homebrew_page, page_homebrew_kind, is_homebrew_source_path, source_homebrew_bucket, truthy, upsert_latex_block,
    insert_latex_block_in_heading, remove_latex_block, load_homebrew_file_kinds, set_file_homebrew_kind,
    move_file_homebrew_metadata, delete_file_homebrew_metadata, sync_source_linked_bundle_text,
)

from .v5 import (
    init_v5_db, list_follows, set_follow, followers_for_target, list_party_notes, save_party_note, delete_party_note,
    investigation_board, save_investigation_node, delete_investigation_node, save_investigation_edge, delete_investigation_edge,
    list_objectives, save_objective, delete_objective, character_milestones, save_character_milestone, delete_character_milestone,
    save_rsvp, session_rsvps, get_preparation, save_preparation, list_prepared_sessions, map_discovery_states, set_map_discovery,
    campaign_fog_regions, set_campaign_fog, notification_prefs, set_notification_pref, filter_notifications_for_prefs,
)
from .v51 import (
    init_v51_db, prep_workspace, list_scenes, save_scenes, list_clues, save_clue, delete_clue,
    list_npc_cards, save_npc_card, delete_npc_card, list_events, add_event, delete_event, list_consequences, save_consequence, delete_consequence,
    list_clocks, save_clock, delete_clock, record_spotlight, spotlight_status, list_templates, save_template, delete_template,
    list_random_tables, save_random_table, delete_random_table, roll_random_table, forgotten_items, save_closeout, BUILTIN_TEMPLATES,
)
from .v6 import (
    init_v6_db, integration_config, save_integration_config, rotate_integration_token, discord_post, discord_session_confirmation,
    foundry_accept, foundry_state, foundry_actors, foundry_link, foundry_link_for_character, foundry_manifest, build_foundry_module_zip,
    list_foundry_prepared_content, save_foundry_prepared_content, delete_foundry_prepared_content,
    queue_foundry_command, claim_foundry_commands, complete_foundry_commands, recent_foundry_commands,
    get_foundry_command, start_foundry_commands, retry_foundry_command,
    calendar_feed, session_ics,
    sync_lore_revisions, lore_revisions, lore_revision_diff, restore_lore_source_revision, page_update_status, knowledge_matrix, converge_campaigns,
    changes_since_last_session, continuity_v6, player_dashboard, command_rows, save_map_annotation, list_map_annotations, delete_map_annotation,
    record_travel_leg, travel_legs, delete_travel_leg, list_media_items, save_media_item, delete_media_item, display_state, set_display_state,
    campaign_keepsake, create_backup, list_backups, delete_backup, maybe_auto_backup, restore_backup,
)
from .v7 import (
    init_v7_db, sync_existing_entities, list_entities, get_entity, save_entity, delete_entity, save_relation, restore_entity_version,
    save_relationship_state, relationship_timeline, save_knowledge_fact, reveal_fact, visible_entity_facts, record_recall,
    list_encounters, get_encounter, save_encounter, save_encounter_creature, delete_encounter_creature,
    save_loot_pool, save_loot_item, list_loot_pools, get_loot_pool, claim_loot,
    create_session_change, session_changes, review_session_change, effective_permissions, save_role_permissions, save_invite_permissions,
    save_dependency, dependency_warnings, list_token_recipes, save_token_recipe, register_asset_ref, asset_usage, asset_catalog,
    ingest_foundry_managed_state, ingest_foundry_command_results, set_sync_link, sync_link, mark_sync_resolved, memory_search, v7_dashboard,
    recent_audit, integration_registry, ALL_PERMISSIONS,
)
from .v7_api import register_v7_routes
from .v8 import init_v8_db
from .v8_api import register_v8_routes
from .homebrew_global import init_global_homebrew
from .v9 import init_v9_db
from .v9_api import register_v9_routes
from .bootstrap import initialize_storage
from .realtime import BUS
from .v10 import indexed_assets, log_best_effort, log_diagnostic, refresh_asset_index
from .v10_api import register_v10_routes

settings = load_settings()
BUILD_LOCK = threading.Lock()
initialize_storage(settings)

app = FastAPI(title="Seeker", docs_url=None, redoc_url=None)
_secure_session_cookie = os.getenv("SESSION_COOKIE_SECURE", "1" if os.getenv("RAILWAY_ENVIRONMENT") else "0").lower() in {"1", "true", "yes"}
app.add_middleware(
    SessionMiddleware, secret_key=settings.session_secret, https_only=_secure_session_cookie,
    same_site="lax", max_age=60 * 60 * 24 * 30,
)
app.mount("/static", StaticFiles(directory=settings.root_dir / "static"), name="static")
templates = Jinja2Templates(directory=settings.root_dir / "templates")


def _asset_file_response(path: Path, *, headers: dict[str, str] | None = None, media_type: str | None = None) -> FileResponse:
    """Serve local campaign media with an inert policy for SVG documents.

    SVG remains supported for maps/art, but imported source files must never gain
    application script privileges merely by being opened directly in a browser.
    """
    out_headers = dict(headers or {})
    if Path(path).suffix.lower() == ".svg":
        out_headers["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'none'; object-src 'none'; frame-src 'none'; sandbox"
        out_headers.setdefault("X-Content-Type-Options", "nosniff")
    return FileResponse(path, headers=out_headers, media_type=media_type)

# Authentication throttling stays in-process by design: Seeker's normal deployment
# is a single web process and this avoids another service dependency. Successful
# logins clear the bucket immediately.
_LOGIN_GUARD: dict[tuple[str, str], list[float]] = {}
_LOGIN_GUARD_LOCK = threading.Lock()

def _login_key(request: Request, scope: str) -> tuple[str, str]:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    host = forwarded or (request.client.host if request.client else "unknown")
    return (scope, host[:120])

def _login_allowed(request: Request, scope: str) -> tuple[bool, int]:
    key = _login_key(request, scope); now = time.time(); window = 15 * 60
    with _LOGIN_GUARD_LOCK:
        rows = [x for x in _LOGIN_GUARD.get(key, []) if now - x < window]
        _LOGIN_GUARD[key] = rows
    if len(rows) < 5:
        return True, 0
    wait = max(1, int(window - (now - rows[0])))
    return False, wait

def _login_failed(request: Request, scope: str) -> None:
    key = _login_key(request, scope)
    with _LOGIN_GUARD_LOCK:
        _LOGIN_GUARD.setdefault(key, []).append(time.time())

def _login_succeeded(request: Request, scope: str) -> None:
    with _LOGIN_GUARD_LOCK:
        _LOGIN_GUARD.pop(_login_key(request, scope), None)


def _external_base_url(request: Request) -> str:
    """Return the browser-facing origin when Seeker is behind Railway/reverse proxies.

    Foundry needs the *actual* public origin the GM is using. Railway can expose more
    than one domain for a service, so RAILWAY_PUBLIC_DOMAIN is only a fallback: a stale
    or secondary Railway domain must not override the Host/X-Forwarded-Host that reached
    Seeker (for this deployment, for example, ``seeker.up.railway.app``). An explicit
    SEEKER_PUBLIC_URL still wins when the deployment owner deliberately pins an origin.
    """
    explicit = os.getenv("SEEKER_PUBLIC_URL", "").strip().rstrip("/")
    if explicit:
        if not re.match(r"^https?://", explicit, flags=re.I):
            explicit = "https://" + explicit
        return explicit

    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip()
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip()
    host = forwarded_host or (request.headers.get("host") or "").strip()
    host_name = host.rsplit(":", 1)[0].strip("[]").lower() if host else ""
    local_hosts = {"", "localhost", "127.0.0.1", "0.0.0.0", "::1", "testserver"}
    if host_name not in local_hosts:
        scheme = forwarded_proto or request.url.scheme or "https"
        # Railway's edge is HTTPS even if an upstream/internal hop reports HTTP.
        if os.getenv("RAILWAY_ENVIRONMENT") or host_name.endswith(".up.railway.app"):
            scheme = "https"
        return f"{scheme}://{host}".rstrip("/")

    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip().strip("/")
    if railway_domain:
        return "https://" + railway_domain
    return str(request.base_url).rstrip("/")


async def _stream_upload(upload: UploadFile, target: Path, max_bytes: int, too_large: str) -> int:
    """Stream an upload to disk with a hard bound on resident memory."""
    target.parent.mkdir(parents=True, exist_ok=True)
    total=0
    try:
        with target.open("wb") as fh:
            while True:
                chunk=await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(413, too_large)
                fh.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return total


def _view_as_invite_id(request: Request) -> int | None:
    """Return the owner-selected player preview target, if any.

    The raw owner session is deliberately retained so the banner can exit preview
    mode, but every normal authorization helper treats preview mode exactly like
    the selected player.
    """
    if not request.session.get("admin"):
        return None
    try:
        return int(request.session.get("view_as_invite_id"))
    except (TypeError, ValueError):
        return None


def is_admin(request: Request) -> bool:
    """True only for the campaign owner acting as the owner (not View As)."""
    return bool(request.session.get("admin")) and _view_as_invite_id(request) is None


def is_co_gm(request: Request) -> bool:
    if _view_as_invite_id(request) is not None:
        return False
    invite = current_player_invite(request) if request.session.get("player_invite_id") else None
    return bool(request.session.get("co_gm") and invite and invite.get("role") == "co-gm")


def is_gm(request: Request) -> bool:
    return is_admin(request) or is_co_gm(request)


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Campaign owner login required")


def require_gm(request: Request) -> None:
    if not is_gm(request):
        raise HTTPException(status_code=401, detail="GM access required")


def player_role(request: Request) -> str:
    if is_admin(request):
        return "owner"
    invite=current_player_invite(request)
    return str((invite or {}).get("role") or "player").lower()


def requester_label(request: Request) -> str:
    if is_admin(request):
        return 'GM'
    invite=current_player_invite(request)
    return str((invite or {}).get('label') or (invite or {}).get('name') or 'Player')[:160]


def v7_has_permission(request: Request, permission: str) -> bool:
    if is_admin(request):
        role='owner';invite_id=None
    elif is_co_gm(request):
        role='co-gm';invite=current_player_invite(request);invite_id=int(invite['id']) if invite else None
    else:
        invite=current_player_invite(request);role=str((invite or {}).get('role') or 'player').lower();invite_id=int(invite['id']) if invite else None
    return bool(effective_permissions(settings,role,invite_id,_active_campaign_id(request)).get(permission,False))


def require_v7_permission(request: Request, permission: str) -> None:
    if not v7_has_permission(request,permission):
        raise HTTPException(403,f'Missing Seeker permission: {permission}')


def archive_mode() -> bool:
    return get_setting(settings,"campaign_archive_mode","0").strip().lower() in {"1","true","yes","on"}


def require_player_author(request: Request) -> None:
    """Require an identified personal player invitation for mutable player-owned state."""
    if is_gm(request):
        return
    if archive_mode():
        raise HTTPException(403,"This campaign is archived and player editing is read-only.")
    invite=current_player_invite(request)
    if not invite:
        raise HTTPException(403,"A personal player invitation is required to contribute campaign state.")
    if str(invite.get("role") or "player").lower() != "player":
        raise HTTPException(403,"This invitation is read-only. Player-author access is required.")


def knowledge_visible(request: Request, target_type: str, target_key: str, *, default: bool=True) -> tuple[bool,str]:
    if is_gm(request):
        return True,"gm"
    return knowledge_allows(settings,_invite_id(request),target_type,str(target_key),default=default,campaign_id=_active_campaign_id(request))


def _knowledge_visible_from_index(index: dict[tuple[str,str],dict], target_type: str, target_key: str, *, default: bool=True) -> tuple[bool,str]:
    row=index.get((str(target_type),str(target_key)))
    if not row:return default,"default"
    state=str(row.get("state") or "unknown")
    return state!="unknown",state


def player_access_mode() -> str:
    mode = get_setting(settings, "player_access_mode", "invite").strip().lower()
    return mode if mode in {"invite", "password", "public"} else "invite"


def current_player_invite(request: Request) -> dict | None:
    # Invitation validation is used by several helpers on one page render. Cache
    # it on the Starlette request object so a single request never revalidates
    # the same device/session repeatedly. Tiny request shims used by scripts/tests
    # may not expose Starlette's ``state`` attribute, so caching is opportunistic.
    state = getattr(request, "state", None)
    if state is not None and getattr(state, "_seeker_invite_checked", False):
        return getattr(state, "_seeker_invite", None)
    preview_id = _view_as_invite_id(request)
    if preview_id is not None:
        invite = get_player_invite(settings, preview_id)
        if invite and not invite.get("active"):
            invite = None
    else:
        invite = validate_player_invite_session(
            settings, request.session.get("player_invite_id"), request.session.get("player_invite_version"),
            request.session.get("player_device_id"),
        )
    if state is not None:
        state._seeker_invite_checked = True
        state._seeker_invite = invite
    return invite


def player_allowed(request: Request) -> bool:
    if is_admin(request):
        return True
    mode = player_access_mode()
    if mode == "public":
        return True
    if mode == "password":
        return bool(settings.player_password and request.session.get("player_password"))
    return current_player_invite(request) is not None


def player_gate_redirect(request: Request) -> RedirectResponse:
    mode = player_access_mode()
    return RedirectResponse("/login" if mode == "password" else "/access", status_code=303)


_ARCHIVE_WRITE_ALLOW = (
    "/api/logout",
    "/api/admin/archive-mode",
    "/api/admin/access",
    "/api/admin/invitations",
    "/api/admin/storage/cleanup",
    "/api/admin/portable-archive/test",
    "/api/assistant/query",
    "/api/public/notifications/",
    "/api/public/bookmark/",
    "/api/public/activity",
    "/api/v6/foundry/push/",
)


# Route `archive_read_only_guard` moved to app.route_runtime.


def _same_origin_request(request: Request) -> bool:
    origin = (request.headers.get("origin") or "").strip()
    if not origin or origin == "null":
        return True
    parsed = urlparse(origin)
    origin_host = (parsed.netloc or "").lower()
    forwarded = (request.headers.get("x-forwarded-host") or "").split(",", 1)[0].strip().lower()
    host = forwarded or (request.headers.get("host") or "").strip().lower()
    return bool(origin_host and host and origin_host == host)


# Route `v10_request_guard_and_diagnostics` moved to app.route_runtime.


def _log_soft_failure(subsystem: str, event_type: str, exc: Exception, *, path: str = "") -> None:
    """Record best-effort subsystem failures without changing legacy behavior."""
    log_diagnostic(
        settings, level="warning", subsystem=subsystem, event_type=event_type,
        message=f"{type(exc).__name__}: {exc}", path=path,
    )


def ensure_built() -> dict:
    try:
        wiki=load_wiki(settings)
        # V6 keeps a bounded rendered revision history. This is essentially free
        # on normal requests because sync_lore_revisions exits immediately when
        # the wiki generation timestamp has not changed.
        try:
            sync_lore_revisions(settings,wiki)
        except Exception as exc:
            _log_soft_failure("lore-revisions", "sync.failed", exc)
        return wiki
    except Exception as exc:
        _log_soft_failure("wiki", "load.failed", exc)
        return {"title": "Seeker", "tagline": "Import a LaTeX campaign project in /admin.", "categories": [], "pages": [], "generated_at": time.time(), "renderer_version": 9000}


def _invite_id(request: Request) -> int | None:
    invite = current_player_invite(request)
    return int(invite["id"]) if invite else None

def _campaign_context(request: Request) -> dict:
    """Resolve the table campaign for this request and cache it on request.state.

    The Codex/Atlas are shared setting material. Party-owned state is filtered by
    this campaign id, allowing the same person/invitation to participate in more
    than one table without mixing characters, sessions, notes or spoilers.
    """
    state=getattr(request,'state',None)
    if state is not None and getattr(state,'_seeker_campaign_checked',False):
        return getattr(state,'_seeker_campaign_context')
    gm=is_gm(request);iid=_invite_id(request)
    campaigns=list_campaigns(settings,invite_id=iid,admin=gm,include_archived=gm)
    # A named player invitation must never silently fall back into another
    # table when all of its active memberships were removed or archived. Table
    # access is explicit: authentication alone does not imply membership.
    if not campaigns and iid is not None and not gm:
        raise HTTPException(403, "This invitation is not assigned to an active campaign. Ask the GM to add you to a campaign.")
    if not campaigns:
        # GM/public setting-only routes still need a deterministic context for
        # legacy campaign-scoped helpers. This is a fallback id, not a membership
        # grant and not a user-visible default table.
        cid=default_campaign_id(settings);campaigns=[get_campaign(settings,cid) or {'id':cid,'name':'Main Campaign','slug':'main-campaign','status':'active','is_default':0}]
    allowed={int(c['id']) for c in campaigns if c and (gm or c.get('status')=='active')}
    requested=request.session.get('active_campaign_id')
    try:requested=int(requested)
    except (TypeError,ValueError):requested=0
    if requested not in allowed:
        active=next((c for c in campaigns if c and int(c['id']) in allowed),campaigns[0])
        requested=int(active['id']);request.session['active_campaign_id']=requested
    active=next((c for c in campaigns if c and int(c['id'])==requested),None) or campaigns[0]
    ctx={'campaigns':[c for c in campaigns if c],'active_campaign':active,'active_campaign_id':int(active['id']),'multi_campaign':len([c for c in campaigns if c and c.get('status')=='active'])>1}
    if state is not None:
        state._seeker_campaign_checked=True;state._seeker_campaign_context=ctx
    return ctx


def _active_campaign_id(request: Request) -> int:
    return int(_campaign_context(request)['active_campaign_id'])

def _campaign_payload(request: Request, payload: dict) -> dict:
    out=dict(payload or {})
    out.setdefault('campaign_id',_active_campaign_id(request))
    return out


def _template_campaign_context(request: Request) -> dict:
    return _campaign_context(request)

# Base and standalone GM templates can resolve campaign context without every
# route having to repeat the same three context variables.
templates.env.globals['campaign_context']=_template_campaign_context


def _asset_ref_url(ref: str) -> str:
    ref = str(ref or "").strip()
    if not ref:
        return ""
    if ref.startswith("project:"):
        return "/project-asset/" + quote(ref.split(":",1)[1], safe="/")
    if ref.startswith("upload:"):
        return "/uploads/" + quote(ref.split(":",1)[1], safe="/")
    if ref.startswith(("/project-asset/","/uploads/")):
        return ref
    return "/project-asset/" + quote(ref, safe="/")


def _calendar_config() -> dict:
    def read_json(key: str, fallback):
        raw=get_setting(settings,key,json.dumps(fallback))
        try: return json.loads(raw) if raw else fallback
        except Exception: return fallback
    return {
        "name":get_setting(settings,"calendar_name","Campaign Calendar"),
        "current_date":get_setting(settings,"campaign_date",""),
        "season":get_setting(settings,"campaign_season",""),
        "months":read_json("calendar_months_json",[]),
        "weekdays":read_json("calendar_weekdays_json",[]),
        "moons":read_json("calendar_moons_json",[]),
        "festivals":read_json("calendar_festivals_json",[]),
        "world_width":get_setting(settings,"world_width","1000"),
        "travel_speed":get_setting(settings,"travel_speed","40"),
    }


def _media_asset_rows() -> list[dict]:
    allowed={".mp3",".ogg",".wav",".m4a",".aac",".flac"};rows=[]
    for base,prefix,url_prefix,source in ((settings.project_dir,"project:","/project-asset/","project"),(settings.uploads_dir,"upload:","/uploads/","upload")):
        if not base.exists(): continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in allowed:
                rel=path.relative_to(base).as_posix();rows.append({"ref":prefix+rel,"url":url_prefix+quote(rel,safe="/"),"path":rel,"source":source,"name":path.name})
    rows.sort(key=lambda x:(x["source"],x["path"].lower()));return rows


def _gallery_from_html(html_text: str) -> list[dict]:
    seen=set();out=[]
    for m in re.finditer(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>',html_text or "",re.I):
        src=m.group(1)
        low=src.lower()
        if "/images/symbols/" in low or "action" in Path(low).stem and "symbol" in low: continue
        if src in seen: continue
        seen.add(src);out.append({"url":src,"caption":""})
    return out[:24]


def _effective_reveal(row: dict | None, invite_id: int | None, now: float) -> dict:
    if not row:
        return {"state":"hidden","rumor_text":"","configured":False,"audience":[]}
    out=dict(row); out["configured"]=True
    if out.get("expires_at") and float(out["expires_at"]) <= now:
        out["state"]="hidden"
    try:
        audience=json.loads(out.get("audience_json") or "[]")
    except Exception:
        audience=[]
    if audience:
        try: allowed={int(x) for x in audience}
        except Exception: allowed=set()
        if invite_id is None or int(invite_id) not in allowed:
            out["state"]="hidden"
    out["audience"]=audience
    return out


def _wiki_dynamic_state(invite_id: int | None, admin: bool, campaign_id:int) -> dict:
    """Load Codex state for one table campaign in one SQLite connection."""
    cid=int(campaign_id)
    with connect(settings) as conn:
        reveals=[dict(r) for r in conn.execute("SELECT * FROM lore_reveals WHERE campaign_id=?",(cid,)).fetchall()]
        publishing=[dict(r) for r in conn.execute("SELECT * FROM publishing_states").fetchall()]
        if invite_id is None:
            knowledge=[]
        else:
            knowledge=[dict(r) for r in conn.execute(
                "SELECT * FROM player_knowledge WHERE campaign_id=? AND invite_id=?", (cid,int(invite_id))
            ).fetchall()]
        styles=[dict(r) for r in conn.execute("SELECT * FROM entity_styles").fetchall()]
        relationships=[dict(r) for r in conn.execute("SELECT * FROM lore_relationships").fetchall()]
        variants=[dict(r) for r in conn.execute("SELECT * FROM lore_variants ORDER BY id").fetchall()]
        alias_rows=[dict(r) for r in conn.execute("SELECT alias,page_slug FROM page_aliases").fetchall()]
        live_row=conn.execute("SELECT id,session_number,title,status,updated_at FROM campaign_sessions WHERE campaign_id=? AND status='live' ORDER BY updated_at DESC,id DESC LIMIT 1",(cid,)).fetchone()
    if not admin:
        relationships=[r for r in relationships if r.get("visibility") not in {"gm","hidden"}]
        variants=[r for r in variants if r.get("visibility") not in {"gm","hidden"}]
    rel_by: dict[str,list[dict]]={}
    for r in relationships:
        rel_by.setdefault(str(r.get("source_slug") or ""),[]).append(r)
        rel_by.setdefault(str(r.get("target_slug") or ""),[]).append(r)
    variants_by: dict[str,list[dict]]={}
    for r in variants:variants_by.setdefault(str(r.get("page_slug") or ""),[]).append(r)
    return {
        "reveals": {(str(r.get("target_type")),str(r.get("target_key"))):r for r in reveals},
        "publishing": {str(r.get("page_slug")):str(r.get("state") or "published") for r in publishing},
        "knowledge": {(str(r.get("target_type")),str(r.get("target_key"))):r for r in knowledge},
        "styles": {str(r.get("page_slug")):r for r in styles},
        "relationships": rel_by,"variants": variants_by,
        "aliases": {str(r.get("alias") or "").casefold():str(r.get("page_slug") or "") for r in alias_rows},
        "live_session": dict(live_row) if live_row else None,
    }

def _apply_reveals_from_index(html_text: str, page_slug: str, state: dict, invite_id: int | None, now: float) -> str:
    def repl(match):
        key=match.group(1); rumor=match.group(2) or ""
        reveal=_effective_reveal(state["reveals"].get(("block",f"{page_slug}:{key}")),invite_id,now)
        if reveal.get("state") in {"discovered","public"}: return match.group(3)
        if reveal.get("state")=="rumor":
            return f'<aside class="lore-rumor"><small>RUMOR</small><p>{reveal.get("rumor_text") or rumor}</p></aside>'
        return '<div class="lore-undiscovered"><span>✦</span><small>UNDISCOVERED LORE</small></div>'
    return _REVEAL_SECTION_RE.sub(repl, html_text or "")


def _path_signature(path: Path) -> tuple[int,int]:
    try:
        st=path.stat(); return int(st.st_mtime_ns), int(st.st_size)
    except OSError:
        return 0,0


def _visible_wiki_signature(invite_id: int | None, admin: bool, campaign_id:int) -> tuple:
    """Return a compact revision fingerprint for one campaign's Codex state."""
    index=settings.build_dir / "wiki_index.json";cid=int(campaign_id)
    with connect(settings) as conn:
        knowledge_clause = "WHERE campaign_id=? AND invite_id=?" if (invite_id is not None and not admin) else "WHERE campaign_id=? AND 0"
        kparams=(cid,int(invite_id)) if (invite_id is not None and not admin) else (cid,)
        # Keep campaign-scoped subqueries separate from shared setting metadata.
        row=conn.execute(f"""
            SELECT
              (SELECT COUNT(*) FROM lore_reveals WHERE campaign_id=?),
              (SELECT COALESCE(MAX(updated_at),0) FROM lore_reveals WHERE campaign_id=?),
              (SELECT COUNT(*) FROM publishing_states),
              (SELECT COALESCE(MAX(updated_at),0) FROM publishing_states),
              (SELECT COUNT(*) FROM player_knowledge {knowledge_clause}),
              (SELECT COALESCE(MAX(updated_at),0) FROM player_knowledge {knowledge_clause}),
              (SELECT COUNT(*) FROM entity_styles),
              (SELECT COALESCE(MAX(updated_at),0) FROM entity_styles),
              (SELECT COUNT(*) FROM lore_relationships),
              (SELECT COALESCE(MAX(updated_at),0) FROM lore_relationships),
              (SELECT COUNT(*) FROM lore_variants),
              (SELECT COALESCE(MAX(updated_at),0) FROM lore_variants),
              (SELECT COUNT(*) FROM page_aliases),
              (SELECT COALESCE(MAX(updated_at),0) FROM page_aliases),
              (SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id=? AND status='live'),
              (SELECT COALESCE(MAX(updated_at),0) FROM campaign_sessions WHERE campaign_id=? AND status='live')
        """, (cid,cid)+kparams+kparams+(cid,cid)).fetchone()
    return (str(index), *_path_signature(index), cid, *(tuple(row) if row else ()))

@functools.lru_cache(maxsize=12)
def _visible_wiki_cached(admin: bool, invite_id: int | None, player_label: str, player_access_key: str, campaign_id:int, signature: tuple) -> dict:
    # ``signature`` is intentionally unused inside the body: it is part of the
    # cache key and changes whenever the generated Codex or SQLite state changes.
    del signature
    base = ensure_built()
    wiki = {k:v for k,v in base.items() if k not in {"pages","categories"}}
    dynamic = _wiki_dynamic_state(invite_id, admin, campaign_id)
    now=time.time()
    visible_pages = []
    allowed_slugs = set()
    for source_page in base.get("pages", []):
        page=dict(source_page)
        page["presentation"]=dict(source_page.get("presentation",{}))
        visibility = page.get("presentation", {}).get("visibility", "public")
        page_reveal = _effective_reveal(dynamic["reveals"].get(("page",str(page.get("slug", "")))), invite_id, now)
        publish = dynamic["publishing"].get(str(page.get("slug","")),"published")
        player_knowledge = dynamic["knowledge"].get(("page",str(page.get("slug",""))))
        page["publishing_state"] = publish
        page["knowledge_state"] = player_knowledge
        if not admin:
            if publish in {"draft", "ready"}:
                continue
            if player_knowledge and player_knowledge.get("state") == "unknown":
                continue
            if player_knowledge and player_knowledge.get("state") == "rumor":
                page["presentation"]["visibility"] = "teaser"
                if player_knowledge.get("note"):
                    page["excerpt"] = player_knowledge["note"]
            if visibility == "hidden":
                continue
            if page_reveal.get("configured") and page_reveal.get("state") == "hidden":
                continue
            if page_reveal.get("configured") and page_reveal.get("state") == "rumor":
                page["presentation"]["visibility"] = "teaser"
                if page_reveal.get("rumor_text"):
                    page["excerpt"] = page_reveal["rumor_text"]
            source_html=page.get("html", "")
            if 'data-lore-reveal=' in source_html:
                page["html"] = _apply_reveals_from_index(source_html, page.get("slug", ""), dynamic, invite_id, now)
                page["plain_text"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page["html"])).strip()
        style = dict(dynamic["styles"].get(str(page.get("slug",""))) or {"page_slug":page.get("slug",""),"crest_ref":"","accent":"","motif":"","ambient_audio_ref":"","dossier_type":"auto"})
        style["crest_url"] = _asset_ref_url(style.get("crest_ref", ""))
        style["ambient_audio_url"] = _asset_ref_url(style.get("ambient_audio_ref", ""))
        page["entity_style"] = style
        page["explicit_relationships"] = [dict(r) for r in dynamic["relationships"].get(str(page.get("slug","")),[])]
        page["variants"] = [dict(r) for r in dynamic["variants"].get(str(page.get("slug","")),[])]
        visible_pages.append(page)
        allowed_slugs.add(page.get("slug"))
    wiki["pages"] = visible_pages
    clean_categories = []
    by_slug={p.get("slug"):p for p in visible_pages}
    for source_category in base.get("categories", []):
        category=dict(source_category)
        category["presentation"]=dict(source_category.get("presentation",{}))
        # Reuse the already filtered/mutated visible page objects so teaser
        # state and player-specific excerpts are consistent in sidebars/home.
        category["pages"]=[by_slug[p.get("slug")] for p in source_category.get("pages",[]) if p.get("slug") in by_slug and not is_homebrew_page(by_slug[p.get("slug")])]
        if category["pages"]:
            clean_categories.append(category)
    wiki["categories"] = clean_categories
    if not admin:
        for page in visible_pages:
            page["explicit_relationships"] = [
                r for r in page.get("explicit_relationships", [])
                if r.get("source_slug") in allowed_slugs and r.get("target_slug") in allowed_slugs
            ]
    wiki["aliases"] = dynamic["aliases"]
    wiki["live_session"] = dynamic["live_session"]
    wiki["player_label"] = player_label
    wiki["gm_view"] = admin
    wiki["player_access_key"] = player_access_key
    wiki["active_campaign_id"] = int(campaign_id)
    return wiki


def _visible_wiki(request: Request, *, include_hidden_for_admin: bool = True) -> dict:
    del include_hidden_for_admin
    admin=is_gm(request);cid=_active_campaign_id(request)
    invite=None if admin else current_player_invite(request)
    invite_id=int(invite["id"]) if invite else None
    player_label=("Co-GM" if is_co_gm(request) else "GM") if admin else str((invite or {}).get("label") or "")
    access_key=("admin" if is_admin(request) else "co-gm") if admin else (f"invite:{invite.get('id')}:{invite.get('access_version')}" if invite else player_access_mode())
    return _visible_wiki_cached(admin, invite_id, player_label, access_key, cid, _visible_wiki_signature(invite_id, admin, cid))

def _asset_rows() -> list[dict]:
    # V10 keeps an incremental index. The refresh only stats files whose metadata
    # changed, avoiding full re-hashing/image inspection on every asset picker.
    return indexed_assets(settings)


# Route `startup_build` moved to app.route_runtime.


_V6_BACKUP_THREAD_STARTED=False
# Route `startup_v6_backups` moved to app.route_runtime.


# Route `health` moved to app.route_public_access.


# Route `invitation_required_page` moved to app.route_public_access.


# Route `accept_player_invite` moved to app.route_public_access.


# Route `player_login_page` moved to app.route_public_access.


# Route `player_login` moved to app.route_public_access.


# Route `admin_login_page` moved to app.route_public_access.


# Route `admin_login` moved to app.route_public_access.


# Route `logout` moved to app.route_public_access.

# Route `campaign_context_api` moved to app.route_public_access.


# Route `campaign_select_api` moved to app.route_public_access.


# Route `all_tables_page` moved to app.route_public_access.


# Route `admin_campaign_save_api` moved to app.route_public_access.


# Route `admin_campaign_default_api` moved to app.route_public_access.


# Route `admin_campaign_archive_api` moved to app.route_public_access.


# Route `admin_campaign_delete_api` moved to app.route_public_access.


# Route `home` moved to app.route_public_access.


# Route `wiki_page` moved to app.route_public_access.


# Route `structures_page` moved to app.route_public_access.


# Route `lore_network` moved to app.route_public_access.


# Route `map_page` moved to app.route_public_access.


# Route `public_search` moved to app.route_public_access.


# Route `web_manifest` moved to app.route_public_access.


# Route `service_worker` moved to app.route_public_access.


# Route `player_session_screen` moved to app.route_public_access.


# Route `player_recap_screen` moved to app.route_public_access.


# Route `player_session_character` moved to app.route_public_access.


# Route `schedule_page` moved to app.route_public_access.


# Route `schedule_me_api` moved to app.route_public_access.


# Route `schedule_me_save_api` moved to app.route_public_access.


# Route `gm_schedule_api` moved to app.route_public_access.


# Route `timeline_page` moved to app.route_public_access.


# Route `calendar_page` moved to app.route_public_access.


# Route `updates_page` moved to app.route_public_access.


# Route `mysteries_page` moved to app.route_public_access.


# Route `handouts_page` moved to app.route_public_access.


# Route `handout_page` moved to app.route_public_access.


# Route `public_session_pulse` moved to app.route_public_access.


# Route `page_card` moved to app.route_public_access.


# Route `public_annotations` moved to app.route_public_access.


# Route `public_add_annotation` moved to app.route_public_access.


# Route `public_delete_annotation` moved to app.route_public_access.


# Route `public_bookmark` moved to app.route_public_access.


# Route `public_bookmarks` moved to app.route_public_access.


# Route `public_activity` moved to app.route_public_access.


# Route `public_map_travel` moved to app.route_public_access.


# Route `share_qr` moved to app.route_public_access.


# Route `gm_session_screen` moved to app.route_public_access.


# Route `admin_campaign_page` moved to app.route_public_access.


# Route `project_asset` moved to app.route_public_access.


# ---------------------------------------------------------------------------
# Player-owned character dossiers
# ---------------------------------------------------------------------------
# Route `characters_page` moved to app.route_public_access.

# Route `character_page` moved to app.route_public_access.

# Route `player_characters_api` moved to app.route_public_access.

# Route `player_character_create` moved to app.route_public_access.

# Route `player_character_update` moved to app.route_public_access.

# Route `player_character_delete` moved to app.route_public_access.

# Route `player_character_image_upload` moved to app.route_public_access.

# Route `player_character_image_delete` moved to app.route_public_access.


# Route `uploaded_asset` moved to app.route_public_access.


# Route `admin` moved to app.route_studio.


# Route `admin_wiki_preview` moved to app.route_studio.


# Route `preview_pdf` moved to app.route_studio.


def _runtime_memory_report() -> dict:
    """Small Linux-friendly runtime snapshot for Studio diagnostics.

    Railway's container graph includes child processes such as XeLaTeX, while
    /proc/self only describes the web process. Keep both where the platform
    exposes them so a future spike is easier to attribute.
    """
    out={"rss_mb":None,"peak_rss_mb":None,"child_peak_rss_mb":None}
    try:
        values={}
        for line in Path("/proc/self/status").read_text(encoding="utf-8",errors="ignore").splitlines():
            if line.startswith(("VmRSS:","VmHWM:")):
                key,val,*_=line.split(); values[key.rstrip(":")]=float(val)/1024
        out["rss_mb"]=round(values.get("VmRSS"),1) if values.get("VmRSS") is not None else None
        out["peak_rss_mb"]=round(values.get("VmHWM"),1) if values.get("VmHWM") is not None else None
    except Exception as exc:
        log_best_effort(settings,"runtime","memory.proc_probe",exc,level="debug")
    try:
        import resource
        child_kb=float(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss or 0)
        if child_kb: out["child_peak_rss_mb"]=round(child_kb/1024,1)
    except Exception as exc:
        log_best_effort(settings,"runtime","memory.child_probe",exc,level="debug")
    try: out["db_mb"]=round(settings.db_path.stat().st_size/(1024*1024),2)
    except Exception: out["db_mb"]=0
    try: out["wiki_index_mb"]=round((settings.build_dir/"wiki_index.json").stat().st_size/(1024*1024),2)
    except Exception: out["wiki_index_mb"]=0
    out["startup_pdf_compile"]=os.getenv("COMPILE_ON_START","0").lower() in {"1","true","yes"}
    try: tail_bytes=max(512_000,int(os.getenv("SEEKER_BUILD_LOG_TAIL_BYTES","4194304")))
    except (TypeError,ValueError): tail_bytes=4_194_304
    out["build_log_tail_mb"]=round(tail_bytes/(1024*1024),1)
    out["build_running"]=BUILD_LOCK.locked()
    return out


# Route `admin_status` moved to app.route_studio.


# Route `admin_storage_cleanup` moved to app.route_studio.


# Route `admin_access` moved to app.route_studio.


# Route `admin_access_update` moved to app.route_studio.


# Route `admin_invitation_create` moved to app.route_studio.


# Route `admin_invitation_revoke` moved to app.route_studio.


# Route `admin_invitation_restore` moved to app.route_studio.


# Route `admin_invitation_rotate` moved to app.route_studio.


# Route `admin_invitation_reset_devices` moved to app.route_studio.


# Route `admin_invitation_delete` moved to app.route_studio.


# Route `admin_files` moved to app.route_studio.


# Route `admin_file_homebrew` moved to app.route_studio.


# Route `admin_folders` moved to app.route_studio.


# Route `admin_wiki_pages` moved to app.route_studio.


# Route `admin_file` moved to app.route_studio.


# Route `admin_save_file` moved to app.route_studio.


# Route `admin_new_file` moved to app.route_studio.


# Route `admin_delete_file` moved to app.route_studio.


def _rewrite_moved_tex_references(old_rel:str,new_rel:str,is_dir:bool) -> list[str]:
    r"""Update ordinary \input/\include/\subfile references after a Studio move.

    Seeker keeps this deliberately narrow: only literal project-local include paths
    are rewritten. Macro-generated includes are left untouched and Build Doctor can
    report them if the move makes them invalid.
    """
    root=settings.project_dir.resolve();old_rel=old_rel.replace('\\','/').strip('/');new_rel=new_rel.replace('\\','/').strip('/')
    old_path=(root/old_rel).resolve();new_path=(root/new_rel).resolve();changed=[]
    command_re=re.compile(r"\\(input|include|subfile)\s*\{([^}]+)\}")
    for src in settings.project_dir.rglob('*'):
        if not src.is_file() or src.suffix.lower() not in {'.tex','.sty','.cls'}:continue
        try:text=src.read_text(encoding='utf-8',errors='replace')
        except OSError:continue
        def repl(match):
            raw=match.group(2).strip();raw_norm=raw.replace('\\','/').lstrip('./')
            candidates=[]
            for base in (root,src.parent):
                target=(base/raw_norm).resolve();candidates.append(target)
                if not Path(raw_norm).suffix:candidates.append(target.with_suffix('.tex'))
            hit=next((x for x in candidates if (x==old_path or (is_dir and old_path in x.parents))),None)
            if hit is None:return match.group(0)
            suffix=hit.relative_to(old_path) if is_dir and hit!=old_path else Path('')
            mapped=(new_path/suffix).resolve() if is_dir else new_path
            # Project-root paths are the least surprising in a multi-file Overleaf workflow.
            replacement=mapped.relative_to(root).as_posix()
            if not Path(raw).suffix and replacement.endswith('.tex'):replacement=replacement[:-4]
            return f"\\{match.group(1)}{{{replacement}}}"
        updated=command_re.sub(repl,text)
        if updated!=text:
            rel=src.relative_to(root).as_posix();save_text_file(settings,rel,updated);changed.append(rel)
    return changed


# Route `admin_new_folder` moved to app.route_studio.


# Route `admin_move_file` moved to app.route_studio.


def _source_fix_edits(fix: dict) -> list[dict]:
    edits = fix.get("edits")
    if isinstance(edits, list) and edits:
        return [x for x in edits if isinstance(x, dict)]
    return [fix]


def _apply_verified_source_fixes(fixes: list[dict]) -> dict:
    """Apply one or more Build Doctor repairs atomically per source snapshot.

    Every proposed line is verified before *any* file is written. This allows the
    UI to offer an "apply all safe fixes" action without risking half-applied
    repairs when the GM edited one of the files after the diagnostic was created.
    """
    edits: list[dict] = []
    for fix in fixes:
        edits.extend(_source_fix_edits(fix))
    if not edits or len(edits) > 80:
        raise HTTPException(400, "No source fixes were supplied, or too many fixes were requested at once.")

    grouped: dict[str, list[dict]] = {}
    seen: dict[tuple[str, int], tuple[str, str]] = {}
    for edit in edits:
        path = str(edit.get("path") or "")
        expected = str(edit.get("expected") or "")
        replacement = str(edit.get("replacement") or "")
        try:
            line_no = int(edit.get("line") or 0)
        except (TypeError, ValueError):
            line_no = 0
        if not path or line_no < 1:
            raise HTTPException(400, "A source fix is missing its path or line number.")
        if "\n" in replacement or "\r" in replacement:
            raise HTTPException(400, "Build Doctor quick fixes may only replace one source line at a time.")
        key = (path, line_no)
        value = (expected, replacement)
        if key in seen:
            if seen[key] != value:
                raise HTTPException(409, f"Conflicting Build Doctor fixes target {path}:{line_no}.")
            continue
        seen[key] = value
        grouped.setdefault(path, []).append({
            "path": path, "line": line_no, "expected": expected, "replacement": replacement,
        })

    snapshots: dict[str, tuple[list[str], Path]] = {}
    # Verify the complete batch before mutating any source file.
    for path, path_edits in grouped.items():
        p = safe_project_path(settings, path)
        if not p.exists() or not p.is_file():
            raise HTTPException(404, f"Source file not found: {path}")
        raw = p.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines(keepends=True)
        for edit in path_edits:
            line_no = edit["line"]
            if line_no > len(lines):
                raise HTTPException(409, f"{path} moved since this diagnostic was created. Compile again.")
            entry = lines[line_no - 1]
            current = entry.rstrip("\r\n")
            if current != edit["expected"]:
                raise HTTPException(409, f"{path}:{line_no} changed since Build Doctor inspected it. Compile again before applying fixes.")
        snapshots[path] = (lines, p)

    changed_files: list[str] = []
    for path, path_edits in grouped.items():
        lines, _ = snapshots[path]
        for edit in path_edits:
            idx = edit["line"] - 1
            entry = lines[idx]
            current = entry.rstrip("\r\n")
            ending = entry[len(current):]
            lines[idx] = edit["replacement"] + ending
        result = save_text_file(settings, path, "".join(lines))
        if result.get("changed"):
            changed_files.append(path)

    try:
        build_wiki(settings)
    except Exception as exc:
        return {"ok": True, "files": changed_files, "edits": len(seen), "wiki_warning": str(exc)}
    return {"ok": True, "files": changed_files, "edits": len(seen)}


# Route `admin_source_fix` moved to app.route_studio.


# Route `admin_source_fixes` moved to app.route_studio.


# Route `admin_compile` moved to app.route_studio.


# Route `admin_rebuild` moved to app.route_studio.


# Route `admin_import` moved to app.route_studio.


# Route `admin_export` moved to app.route_studio.


# Route `admin_revisions` moved to app.route_studio.


# Route `admin_restore` moved to app.route_studio.


# Route `admin_settings` moved to app.route_studio.


# Route `admin_codex` moved to app.route_studio.


# Route `admin_codex_presentation` moved to app.route_studio.


# Route `admin_assets` moved to app.route_studio.


def _sanitize_uploaded_svg(path: Path) -> None:
    """Strip active/external content while preserving normal SVG artwork."""
    import xml.etree.ElementTree as ET
    raw = path.read_text(encoding="utf-8", errors="strict")
    if "<!DOCTYPE" in raw.upper() or "<!ENTITY" in raw.upper():
        raise ValueError("SVG document types/entities are not allowed.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("The SVG is not valid XML.") from exc
    dangerous = {"script", "foreignobject", "iframe", "object", "embed"}
    href_names = {"href", "{http://www.w3.org/1999/xlink}href"}
    for parent in list(root.iter()):
        for child in list(parent):
            local = child.tag.rsplit("}", 1)[-1].lower() if isinstance(child.tag, str) else ""
            if local in dangerous:
                parent.remove(child)
        for key in list(parent.attrib):
            low = key.rsplit("}", 1)[-1].lower()
            value = str(parent.attrib.get(key) or "").strip()
            if low.startswith("on"):
                parent.attrib.pop(key, None)
            elif key in href_names or low == "href":
                vl = value.lower()
                if vl.startswith(("javascript:", "vbscript:", "http://", "https://", "//")):
                    parent.attrib.pop(key, None)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


# Route `admin_asset_upload` moved to app.route_studio.


# Route `admin_maps` moved to app.route_studio.


# Route `admin_create_map` moved to app.route_studio.


# Route `admin_update_map` moved to app.route_studio.


# Route `admin_delete_map` moved to app.route_studio.


# Route `admin_create_marker` moved to app.route_studio.


# Route `admin_update_marker` moved to app.route_studio.


# Route `admin_delete_marker` moved to app.route_studio.

def _notify_page_followers(campaign_id:int, page_slug:str, title:str, body:str, *, kind:str='follow') -> None:
    slug=str(page_slug or '').split('::',1)[0].strip()
    if not slug:return
    audience=followers_for_target(settings,int(campaign_id),'page',slug)
    if not audience:return
    create_notification(settings,{
        'campaign_id':int(campaign_id),'title':str(title or 'Followed lore changed'),'body':str(body or ''),
        'target_type':'page','target_key':slug,'kind':kind,'audience':audience,
    })


# ---------------------------------------------------------------------------
# Seeker campaign-runtime APIs
# ---------------------------------------------------------------------------
# Route `admin_campaign_overview` moved to app.route_studio.


# Route `admin_save_session` moved to app.route_studio.


# Route `admin_delete_session` moved to app.route_studio.


# Route `admin_session_lore` moved to app.route_studio.


# Route `admin_session_update` moved to app.route_studio.


# Route `admin_timeline_save` moved to app.route_studio.


# Route `admin_timeline_delete` moved to app.route_studio.


# Route `admin_timeline_era_save` moved to app.route_studio.

# Route `admin_timeline_era_delete` moved to app.route_studio.


# Route `admin_relationship_save` moved to app.route_studio.


# Route `admin_relationship_delete` moved to app.route_studio.


# Route `admin_reveal_save` moved to app.route_studio.


# Route `admin_variant_save` moved to app.route_studio.


# Route `admin_variant_delete` moved to app.route_studio.


# Route `admin_alias_save` moved to app.route_studio.


# Route `admin_entity_style_save` moved to app.route_studio.


# Route `admin_mystery_save` moved to app.route_studio.


# Route `admin_mystery_pin` moved to app.route_studio.


# Route `admin_mystery_edge` moved to app.route_studio.


# Route `admin_mystery_edge_delete` moved to app.route_studio.


# Route `admin_mystery_pin_delete` moved to app.route_studio.


# Route `admin_mystery_delete` moved to app.route_studio.


# Route `admin_handout_save` moved to app.route_studio.


def _creator_handout(request,handout_id):
    try: hid=int(handout_id)
    except (TypeError,ValueError): raise HTTPException(400,"Invalid handout ID")
    with connect(settings) as conn: row=conn.execute("SELECT * FROM handouts WHERE id=? AND campaign_id=?",(hid,_active_campaign_id(request))).fetchone()
    if not row: raise HTTPException(404,"Handout not found")
    return dict(row)


# Route `admin_handout_delete` moved to app.route_studio.


# Route `handout_creator_page` moved to app.route_studio.


# Route `handout_creator_list` moved to app.route_studio.


# Route `handout_creator_preview` moved to app.route_studio.


# Route `handout_export` moved to app.route_studio.


# Route `admin_map_layer_save` moved to app.route_studio.


# Route `admin_map_layer_delete` moved to app.route_studio.


# Route `admin_map_fog_save` moved to app.route_studio.


# Route `admin_map_fog_delete` moved to app.route_studio.


# Route `admin_snapshot_create` moved to app.route_studio.


# Route `admin_snapshot_download` moved to app.route_studio.


# Route `admin_snapshot_restore` moved to app.route_studio.


# Route `admin_health_report` moved to app.route_studio.


# Route `admin_world_settings` moved to app.route_studio.


# Route `admin_revision_diff` moved to app.route_studio.


def _entry_template_content(kind: str, title: str) -> str:
    kind=str(kind or "person").lower(); title=str(title or "New Entry").strip()
    templates_map={
        "person":f"\\pon{{{title}}}\n\\section{{Profile}}\n\\begin{{multicols}}{{2}}\n\\textbf{{Ancestry:}} \\\\\n\\textbf{{Class:}} \\\\\n\\textbf{{Age:}} \\\\\n\\textbf{{Place of Residence:}} \\\\\n\\textbf{{Status:}} Alive\n\\end{{multicols}}\n\nWrite the character overview here.\n\n\\section{{Biography}}\n",
        "settlement":f"\\section{{{title}}}\n\\subsection{{Overview}}\n\n\\subsection{{Government}}\n\n\\subsection{{Notable Locations}}\n\n\\subsection{{People}}\n",
        "faction":f"\\section{{{title}}}\n\\subsection{{Purpose}}\n\n\\subsection{{Leadership}}\n\n\\subsection{{Members}}\n\n\\subsection{{Relationships}}\n",
        "deity":f"\\section{{{title}}}\n\\subsection{{Doctrine}}\n\\textbf{{Edicts:}} \\\\\n\\textbf{{Anathema:}} \\\\\n\n\\subsection{{Worshippers}}\n",
        "event":f"\\section{{{title}}}\n\\subsection{{Background}}\n\n\\subsection{{Event}}\n\n\\subsection{{Aftermath}}\n",
        "creature":f"\\begin{{monster}}{{{title}}}{{1}}{{Medium, Creature}}{{Homebrew}}\n\\monstersection{{Perception}}\n\\monsterline{{Perception}}{{+0}}\n\\monsterabilityscores{{+0}}{{+0}}{{+0}}{{+0}}{{+0}}{{+0}}\n\\monstersection{{Defense}}\n\\monsterdefenses{{15}}{{+5, +5, +5}}{{20 HP}}{{}}\n\\monstersection{{Offense}}\n\\monsterspeed{{25 feet}}\n\\end{{monster}}\n",
        "handout":f"% In-world handout source\n\\section{{{title}}}\n\n",
    }
    return templates_map.get(kind,templates_map["person"])


# Route `admin_entry_template` moved to app.route_studio.


# Route `admin_entry_template_create` moved to app.route_studio.


# Route `admin_map_layer_upload` moved to app.route_studio.

# ---------------------------------------------------------------------------
# Seeker · Living Campaign layer
# ---------------------------------------------------------------------------

def _player_label(request: Request) -> str:
    if is_admin(request): return "GM"
    if is_co_gm(request): return "Co-GM"
    return str((current_player_invite(request) or {}).get("label") or "Player")


def _character_owned(request: Request, character_id: int) -> dict:
    iid=_invite_id(request); char=get_player_character(settings,character_id,invite_id=iid,admin=is_gm(request),campaign_id=_active_campaign_id(request))
    if not char: raise HTTPException(404,"Character not found")
    if not is_gm(request) and int(char.get("invite_id") or -1)!=int(iid or -2): raise HTTPException(403,"You can only edit your own character.")
    return char


def _own_player_characters(request: Request) -> list[dict]:
    iid=_invite_id(request)
    if iid is None or is_gm(request): return []
    rows=list_player_characters(settings,invite_id=iid,admin=False,campaign_id=_active_campaign_id(request))
    own=[c for c in rows if int(c.get("invite_id") or -1)==int(iid)]
    return sorted(own,key=lambda c:(str(c.get("status") or "active")!="active",str(c.get("name") or "").lower()))


def _session_character_context(request: Request, live: dict|None) -> tuple[list[dict],dict|None,bool]:
    """Return own characters, selected character, and whether identity was chosen for this session.

    The choice is stored in the signed login session and keyed to the live campaign
    session, so a new tabletop session asks multi-character players again instead
    of silently reusing last week's identity.
    """
    chars=_own_player_characters(request)
    if not chars: return [],None,False
    session_key=int((live or {}).get("id") or 0)
    selected_for=int(request.session.get("session_character_session_id") or -1)==session_key
    selected_id=int(request.session.get("session_character_id") or 0) if selected_for else 0
    active=next((c for c in chars if int(c.get("id") or -1)==selected_id),None)
    if len(chars)==1 and not selected_for:
        active=chars[0];selected_for=True
        request.session["session_character_id"]=int(active["id"]);request.session["session_character_session_id"]=session_key
    elif selected_id and active is None:
        request.session.pop("session_character_id",None);request.session.pop("session_character_session_id",None);selected_for=False
    return chars,active,selected_for


# Route `living_campaign_page` moved to app.route_living.


# Route `living_threads_alias` moved to app.route_living.


# Route `living_admin_page` moved to app.route_living.


# Route `living_overview` moved to app.route_living.


# Route `living_admin_overview` moved to app.route_living.


# Route `admin_set_knowledge` moved to app.route_living.


# Route `admin_save_front` moved to app.route_living.
# Route `admin_advance_front` moved to app.route_living.
# Route `admin_delete_front` moved to app.route_living.


# Route `admin_runtime_state` moved to app.route_living.


# Route `admin_relationship_history` moved to app.route_living.
# Route `admin_relationship_history_delete` moved to app.route_living.


# Route `admin_hierarchy_save` moved to app.route_living.
# Route `admin_hierarchy_delete` moved to app.route_living.


# Route `admin_map_region_save` moved to app.route_living.
# Route `admin_map_region_history` moved to app.route_living.
# Route `admin_map_region_history_delete` moved to app.route_living.
# Route `admin_map_region_delete` moved to app.route_living.
# Route `public_map_regions` moved to app.route_living.


# Route `admin_rumor_save` moved to app.route_living.
# Route `admin_rumor_delete` moved to app.route_living.
# Route `admin_random_rumor` moved to app.route_living.

# Route `admin_rumor_share` moved to app.route_living.


# Route `thread_save_api` moved to app.route_living.
# Route `thread_delete_api` moved to app.route_living.
# Route `thread_note_api` moved to app.route_living.
# Route `thread_link_api` moved to app.route_living.


# Route `thread_note_update_api` moved to app.route_living.

# Route `thread_note_delete_api` moved to app.route_living.

# Route `thread_link_delete_api` moved to app.route_living.


# Route `player_journal_save` moved to app.route_living.


# Route `admin_inbox_save` moved to app.route_living.
# Route `admin_inbox_archive` moved to app.route_living.


# Route `player_submission_save` moved to app.route_living.
# Route `player_submission_upload` moved to app.route_living.

# Route `admin_inbox_upload` moved to app.route_living.


# Route `admin_submission_review` moved to app.route_living.


# Route `admin_publish_state` moved to app.route_living.
# Route `admin_publish_batch` moved to app.route_living.


# Route `admin_session_state_snapshot` moved to app.route_living.


# Route `admin_suggestions_scan` moved to app.route_living.
# Route `admin_suggestion_update` moved to app.route_living.


# Route `admin_media_meta` moved to app.route_living.


# Route `admin_media_usage` moved to app.route_living.

# Route `admin_media_replace` moved to app.route_living.

# Route `admin_media_thumb` moved to app.route_living.


# Route `admin_notification_create` moved to app.route_living.
# Route `public_notifications` moved to app.route_living.
# Route `public_notification_read` moved to app.route_living.

# Route `public_notification_delete` moved to app.route_living.

# Route `public_notifications_read_all` moved to app.route_living.


# Route `player_character_relationship_save` moved to app.route_living.
# Route `player_character_relationship_delete` moved to app.route_living.
# Route `player_character_arc_save` moved to app.route_living.
# Route `player_character_arc_delete` moved to app.route_living.


# Route `page_provenance_api` moved to app.route_living.


# Route `foundry_page_export` moved to app.route_living.
# Route `foundry_character_export` moved to app.route_living.


# Route `portable_archive_download` moved to app.route_living.
# Route `portable_archive_test` moved to app.route_living.


# Route `archive_mode_set` moved to app.route_living.
# Route `campaign_archive_page` moved to app.route_living.


# Route `lore_assistant_query` moved to app.route_living.


# Route `admin_invitation_role` moved to app.route_living.

# ---------------------------------------------------------------------------
# Seeker V5 · player session companion
# ---------------------------------------------------------------------------

# Route `investigation_page` moved to app.route_session_tools.


# Route `v5_follows` moved to app.route_session_tools.


# Route `v5_follow_save` moved to app.route_session_tools.


# Route `v5_party_notes` moved to app.route_session_tools.


# Route `v5_party_note_save` moved to app.route_session_tools.


# Route `v5_party_note_delete` moved to app.route_session_tools.


# Route `v5_investigation_get` moved to app.route_session_tools.


# Route `v5_investigation_node_save` moved to app.route_session_tools.


# Route `v5_investigation_node_delete` moved to app.route_session_tools.


# Route `v5_investigation_edge_save` moved to app.route_session_tools.


# Route `v5_investigation_edge_delete` moved to app.route_session_tools.


# Route `v5_objectives_get` moved to app.route_session_tools.


# Route `v5_objective_save` moved to app.route_session_tools.


# Route `v5_objective_delete` moved to app.route_session_tools.


# Route `v5_character_milestone_save` moved to app.route_session_tools.


# Route `v5_character_milestone_delete` moved to app.route_session_tools.


# Route `v5_session_rsvp` moved to app.route_session_tools.


# Route `v5_session_rsvps` moved to app.route_session_tools.


# Route `gm_prep_page` moved to app.route_session_tools.


# Route `v5_gm_prep_get` moved to app.route_session_tools.


# Route `v5_gm_prep_save` moved to app.route_session_tools.



# Route `v51_gm_workspace` moved to app.route_session_tools.


# Route `v51_gm_scenes_save` moved to app.route_session_tools.


# Route `v51_gm_clue_save` moved to app.route_session_tools.


# Route `v51_gm_clue_delete` moved to app.route_session_tools.


# Route `v51_gm_npc_save` moved to app.route_session_tools.


# Route `v51_gm_npc_delete` moved to app.route_session_tools.


# Route `v51_gm_event_add` moved to app.route_session_tools.


# Route `v51_gm_event_delete` moved to app.route_session_tools.


# Route `v51_gm_consequence_save` moved to app.route_session_tools.


# Route `v51_gm_consequence_delete` moved to app.route_session_tools.


# Route `v51_gm_clock_save` moved to app.route_session_tools.


# Route `v51_gm_clock_delete` moved to app.route_session_tools.


# Route `v51_gm_spotlight_mark` moved to app.route_session_tools.


# Route `v51_gm_template_save` moved to app.route_session_tools.


# Route `v51_gm_template_delete` moved to app.route_session_tools.


# Route `v51_gm_random_table_save` moved to app.route_session_tools.


# Route `v51_gm_random_table_delete` moved to app.route_session_tools.


# Route `v51_gm_random_table_roll` moved to app.route_session_tools.


# Route `v51_gm_push` moved to app.route_session_tools.


# Route `v51_gm_apply_template` moved to app.route_session_tools.


# Route `v51_gm_closeout` moved to app.route_session_tools.


# Route `v5_map_discovery_save` moved to app.route_session_tools.


# Route `v5_map_fog_save` moved to app.route_session_tools.


# Route `v5_notification_prefs_get` moved to app.route_session_tools.


# Route `v5_notification_pref_save` moved to app.route_session_tools.

# ---------------------------------------------------------------------------
# Seeker V6 — continuity, integrations and table companion infrastructure
# ---------------------------------------------------------------------------

# Route `v6_continuity_page` moved to app.route_gm_integrations.


# Route `v6_integrations_page` moved to app.route_gm_integrations.


# Route `v61_foundry_workshop_page` moved to app.route_gm_integrations.


def _foundry_image_bucket(campaign_id:int,kind:str) -> Path:
    bucket='tokens' if str(kind or '').lower()=='token' else 'art'
    folder=settings.uploads_dir/'foundry'/str(int(campaign_id))/bucket
    folder.mkdir(parents=True,exist_ok=True)
    return folder


def _optimize_foundry_image(source:Path,campaign_id:int,kind:str,stem_hint:str='art') -> dict:
    """Normalize workshop art to compact, deduplicated WebP files.

    Foundry and modern browsers handle WebP well. Keeping a single bounded format
    avoids storing multi-megabyte phone/PNG originals for portraits and tokens.
    """
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except Exception as exc:
        raise HTTPException(500,'Image optimization is unavailable on this Seeker install.') from exc
    try:
        with Image.open(source) as opened:
            image=ImageOps.exif_transpose(opened)
            image.load()
    except (UnidentifiedImageError,OSError,ValueError) as exc:
        raise HTTPException(400,'That file is not a readable image.') from exc
    max_side=1024 if str(kind or '').lower()=='token' else 1600
    if max(image.size)>max_side:
        image.thumbnail((max_side,max_side),Image.Resampling.LANCZOS)
    has_alpha='A' in image.getbands() or ('transparency' in getattr(image,'info',{}))
    image=image.convert('RGBA' if has_alpha else 'RGB')
    out=io.BytesIO()
    # Tokens get a little more quality because hard frame edges expose compression;
    # portraits favor smaller storage. WebP preserves alpha for token frames.
    quality=88 if str(kind or '').lower()=='token' else 82
    image.save(out,format='WEBP',quality=quality,method=4,exact=bool(has_alpha))
    data=out.getvalue()
    digest=hashlib.sha256(data).hexdigest()[:24]
    folder=_foundry_image_bucket(campaign_id,kind)
    # The content hash *is* the filename. This makes de-duplication independent
    # of whether the same artwork was uploaded as monster.png, portrait.jpg, etc.
    filename=f'{digest}.webp'
    target=folder/filename
    existed=target.exists()
    if not existed:
        target.write_bytes(data)
    rel=target.relative_to(settings.uploads_dir).as_posix()
    return {
        'ok':True,
        'url':'/uploads/'+quote(rel,safe='/'),
        'ref':'upload:'+rel,
        'name':filename,
        'width':int(image.width),'height':int(image.height),'bytes':len(data),
        'deduplicated':existed,
    }


def _prune_unused_foundry_images(campaign_id:int,grace_seconds:int=86400) -> dict:
    """Remove abandoned workshop images without touching referenced art.

    The creator can generate several crops/tokens while experimenting. We keep
    unreferenced files for a short grace period so an unsaved browser draft is
    not destroyed, then reclaim them automatically. Originals are never kept:
    only the optimized WebP derivative reaches this bucket.
    """
    cid=int(campaign_id);root=settings.uploads_dir/'foundry'/str(cid)
    if not root.exists():return {'removed':0,'bytes':0}
    keep=set()
    prefix=f'/uploads/foundry/{cid}/'
    for row in list_foundry_prepared_content(settings,cid):
        data=row.get('payload') or {}
        for key in ('img','token_img'):
            raw=str(data.get(key) or '')
            if raw.startswith(prefix):keep.add(unquote(raw[len('/uploads/'):]).lstrip('/'))
    cutoff=time.time()-max(0,int(grace_seconds));removed=0;reclaimed=0
    for path in root.rglob('*.webp'):
        try:
            rel=path.relative_to(settings.uploads_dir).as_posix()
            if rel in keep or path.stat().st_mtime>cutoff:continue
            reclaimed+=path.stat().st_size;path.unlink();removed+=1
        except OSError:continue
    for folder in sorted((p for p in root.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
        try:folder.rmdir()
        except OSError:pass
    return {'removed':removed,'bytes':reclaimed}


def _validate_public_remote_url(raw:str) -> str:
    value=str(raw or '').strip()
    if len(value)>4000:raise HTTPException(400,'Artwork URL is too long.')
    parsed=urlparse(value)
    if parsed.scheme not in {'http','https'} or not parsed.hostname:
        raise HTTPException(400,'Use a public http(s) image URL.')
    host=parsed.hostname.strip().lower()
    if host in {'localhost','localhost.localdomain'}:
        raise HTTPException(400,'Local/private artwork URLs cannot be imported.')
    try:
        infos=socket.getaddrinfo(host,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)
    except OSError as exc:
        raise HTTPException(400,'Seeker could not resolve that image host.') from exc
    for info in infos:
        try:ip=ipaddress.ip_address(info[4][0])
        except ValueError:continue
        if not ip.is_global:
            raise HTTPException(400,'Local/private artwork URLs cannot be imported.')
    return value


def _download_remote_foundry_image(raw_url:str,campaign_id:int,kind:str='art') -> dict:
    url=_validate_public_remote_url(raw_url)
    temp=Path(tempfile.gettempdir())/f'seeker-foundry-art-{secrets.token_hex(8)}.img'
    req=UrlRequest(url,headers={'User-Agent':'Seeker/10.0.0 (+Foundry Workshop)','Accept':'image/*'})
    class _SafeImageRedirect(HTTPRedirectHandler):
        def redirect_request(self,request,fp,code,msg,headers,newurl):
            return super().redirect_request(request,fp,code,msg,headers,_validate_public_remote_url(newurl))
    opener=build_opener(_SafeImageRedirect())
    try:
        with opener.open(req,timeout=10) as response, temp.open('wb') as fh:
            final=_validate_public_remote_url(response.geturl())
            ctype=str(response.headers.get('Content-Type') or '').split(';',1)[0].lower()
            if ctype and not ctype.startswith('image/'):
                raise HTTPException(400,'That URL did not return an image.')
            total=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>20_000_000:raise HTTPException(413,'Remote artwork is limited to 20 MB.')
                fh.write(chunk)
        hint=Path(urlparse(final).path).stem or 'linked-art'
        return _optimize_foundry_image(temp,campaign_id,kind,hint)
    except HTTPException:raise
    except Exception as exc:
        raise HTTPException(400,'Seeker could not import that remote artwork. The host may block server-side downloads.') from exc
    finally:
        temp.unlink(missing_ok=True)


# Route `v613_foundry_asset_upload` moved to app.route_gm_integrations.


# Route `v614_foundry_asset_import` moved to app.route_gm_integrations.


def _published_bestiary_rows(campaign_id:int) -> list[dict]:
    rows=[]
    for row in list_foundry_prepared_content(settings,campaign_id):
        if str(row.get('kind') or '') not in {'monster','npc'}:
            continue
        payload=row.get('payload') or {}
        publish=payload.get('codex_publish')
        if isinstance(publish,str):publish=publish.strip().lower() in {'1','true','yes','on'}
        if not bool(publish):
            continue
        # Old AoN imports could accidentally capture responsive site navigation
        # as their meta description. Clean at presentation time as well as in the
        # importer so existing campaign databases heal immediately after update.
        if payload.get('aon_url'):
            row['summary']=sanitize_aon_summary(str(row.get('summary') or ''),title=str(row.get('title') or ''))
            payload=dict(payload)
            payload['description']=sanitize_aon_summary(str(payload.get('description') or ''),title=str(row.get('title') or ''))
            payload['codex_blurb']=sanitize_aon_summary(str(payload.get('codex_blurb') or ''),title=str(row.get('title') or ''))
            row['payload']=payload
        rows.append(row)
    return rows


def _foundry_asset_signature(campaign_id:int,rel:str) -> str:
    message=f"foundry-asset:{int(campaign_id)}:{rel}".encode('utf-8')
    return hmac.new(settings.session_secret.encode('utf-8'),message,hashlib.sha256).hexdigest()


def _foundry_push_asset_url(request:Request,campaign_id:int,raw:str) -> str:
    value=str(raw or '').strip()
    prefix=f'/uploads/foundry/{int(campaign_id)}/'
    if not value.startswith(prefix):return value
    rel=unquote(value[len(prefix):]).lstrip('/')
    if not rel:return value
    sig=_foundry_asset_signature(campaign_id,rel)
    return f"{_external_base_url(request)}/api/v6/foundry/asset/{int(campaign_id)}/{quote(rel,safe='/')}?sig={sig}"


# Route `v613_foundry_asset` moved to app.route_gm_integrations.


CODEX_SECTION_KEYS=('identity','awareness','defenses','movement','strikes','abilities','spellcasting','description')

def _codex_section_visibility(payload:dict, *, gm:bool=False) -> dict[str,bool]:
    raw=payload.get('codex_sections') if isinstance(payload.get('codex_sections'),dict) else {}
    broad=str(payload.get('codex_visibility') or 'field_notes').lower()=='full'
    # Existing full-statblock entries predate granular controls, so missing keys
    # default to visible. Field-note entries stay mechanically private.
    return {key:(True if gm else bool(broad and raw.get(key,True))) for key in CODEX_SECTION_KEYS}


# Route `v613_bestiary_page` moved to app.route_gm_integrations.


# Route `v613_bestiary_entry` moved to app.route_gm_integrations.


# Route `v704_bestiary_update` moved to app.route_gm_integrations.


# Route `v704_bestiary_remove` moved to app.route_gm_integrations.


def _strip_source_feat_cards(value:str) -> str:
    """Remove collected feat cards while preserving inline actions/activities.

    Source-backed Homebrew is a document, not a bag of rule commands. Feats are
    normalized into the level-grouped feat index at the bottom, but actions and
    activities belong exactly where the author put them in the LaTeX body.
    """
    return re.sub(
        r'<section class="pf2-rule-card\s+pf2-feat\b[^>]*>.*?</section>',
        '', str(value or ''), flags=re.I|re.S,
    ).strip()


def _homebrew_source_sections(wiki:dict) -> list[dict]:
    """Return one Homebrew bundle per classified LaTeX source/owner.

    The Homebrew landing page should show *Jotunari*, not every ``1st Level`` /
    ``5th Level`` subsection that happened to become a Codex page.  The bundle
    keeps those pages internally for the detail view and gathers all detected
    \feat / \action commands into one rules list.
    """
    bundles: dict[tuple[str, str], dict] = {}
    for page in sorted(wiki.get('pages',[]), key=lambda x:int(x.get('order') or 0)):
        section=page_homebrew_kind(page)
        if section=='codex':continue
        owner_slug=str(page.get('homebrew_owner_slug') or page.get('slug') or '')
        owner_title=str(page.get('homebrew_owner_title') or page.get('title') or 'Homebrew')
        key=(section,owner_slug)
        bundle=bundles.setdefault(key,{
            'key':section,'name':owner_title,'owner_slug':owner_slug,'pages':[],'lore_pages':[],
            'rules':[],'feat_rules':[],'action_rules':[],'source_file':page.get('source_file') or '',
            'source_meta':dict(page.get('homebrew_source_meta') or {}),
        })
        bundle['pages'].append(page)
        lore_html=_strip_source_feat_cards(page.get('html') or '')
        lore_plain=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',lore_html)).strip()
        heritage_titles={str(h.get('title') or h.get('name') or '').strip().casefold() for h in (bundle.get('source_meta') or {}).get('heritages',[]) if isinstance(h,dict)}
        # Structured heritage children belong in the heritage section below the
        # ancestry overview, not duplicated as ordinary lore pages.
        is_heritage_page=str(page.get('title') or '').strip().casefold() in heritage_titles
        if lore_plain and not is_heritage_page:
            lore=dict(page);lore['lore_html']=lore_html;lore['lore_plain']=lore_plain
            bundle['lore_pages'].append(lore)
        for rule in page.get('pf2e_rules') or []:
            item=dict(rule);item['source_page_slug']=page.get('slug');item['source_page_title']=page.get('title');item['source_file']=page.get('source_file') or ''
            bundle['rules'].append(item)
    grouped={}
    for (section,_),bundle in bundles.items():
        bundle['rules'].sort(key=lambda x:(int(x.get('level') or 0),str(x.get('title') or '').casefold()))
        bundle['feat_rules']=[x for x in bundle['rules'] if str(x.get('kind') or '')=='feat']
        bundle['action_rules']=[x for x in bundle['rules'] if str(x.get('kind') or '')=='action']
        bundle['feat_count']=len(bundle['feat_rules'])
        bundle['action_count']=len(bundle['action_rules'])
        source_meta=dict(bundle.get('source_meta') or {})
        bundle['ancestry']=dict(source_meta.get('ancestry') or {}) if section=='ancestry' else {}
        bundle['heritages']=[dict(x) for x in (source_meta.get('heritages') or []) if isinstance(x,dict)] if section=='ancestry' else []
        bundle['heritage_count']=len(bundle['heritages'])
        first_lore=(bundle.get('lore_pages') or [{}])[0]
        bundle['summary']=str(first_lore.get('excerpt') or first_lore.get('lore_plain') or '')[:260]
        grouped.setdefault(section,[]).append(bundle)
    order=['ancestry','archetype','class','general','actions','items','other'];out=[]
    for section in order:
        rows=grouped.get(section,[])
        if not rows:continue
        rows.sort(key=lambda x:x['name'].casefold())
        out.append({'key':section,'title':HOME_BREW_SOURCE_TITLES.get(section,HOME_BREW_SECTIONS.get(section,'Other Homebrew')),'groups':rows})
    return out


def _homebrew_feat_category(raw_category:str='', traits:list|tuple|set|str=(), section:str='') -> str:
    raw=str(raw_category or '').strip().lower()
    if isinstance(traits,str): trait_set={x.strip().lower() for x in traits.split(',') if x.strip()}
    else: trait_set={str(x or '').strip().lower() for x in (traits or []) if str(x or '').strip()}
    section=str(section or '').strip().lower()
    if section in {'ancestry','archetype','class'}: return section
    if raw in {'ancestry','archetype','class','general','skill'}: return raw
    if 'ancestry' in trait_set:return 'ancestry'
    if 'archetype' in trait_set:return 'archetype'
    if 'class' in trait_set:return 'class'
    if 'skill' in trait_set:return 'skill'
    if 'general' in trait_set:return 'general'
    return 'other'


def _homebrew_library_indexes(source_sections:list[dict], rows:list[dict], *, include_drafts:bool=False) -> tuple[list[dict],list[dict]]:
    """Build secondary Heritage and Feat indexes without creating duplicate records.

    These are navigation views over the existing source/Forge objects. A heritage or
    feat still belongs to its ancestry/archetype/source; the index only makes PF2e-style
    browsing possible from the Homebrew library.
    """
    heritages=[];feats=[]
    def anchor(value:str)->str:
        slug=re.sub(r'[^a-z0-9]+','-',str(value or '').casefold()).strip('-') or 'entry'
        return slug[:100]
    def add_feat(rule:dict, *, parent:str, href:str, section:str='', category:str=''):
        title=str(rule.get('title') or rule.get('name') or '').strip()
        if not title:return
        traits=rule.get('traits') or []
        cat=_homebrew_feat_category(category or str(rule.get('feat_category') or ''),traits,section)
        try:level=int(rule.get('level') or 0)
        except (TypeError,ValueError):level=0
        feats.append({'title':title,'parent':parent,'href':href,'category':cat,
                      'category_label':{'general':'General','skill':'Skill','class':'Class','ancestry':'Ancestry','archetype':'Archetype','other':'Other'}[cat],
                      'level':level,'traits':traits if isinstance(traits,list) else [x.strip() for x in str(traits).split(',') if x.strip()],
                      'description':str(rule.get('description') or rule.get('plain_text') or ''),'action_cost':str(rule.get('action_cost') or '')})
    for sec in source_sections:
        section=str(sec.get('key') or '')
        for group in sec.get('groups',[]):
            parent=str(group.get('name') or 'Homebrew');href=f"/homebrew/source/{group.get('owner_slug')}"
            if section=='ancestry':
                for h in group.get('heritages') or []:
                    if not isinstance(h,dict):continue
                    title=str(h.get('title') or h.get('name') or '').strip()
                    if not title:continue
                    traits=h.get('traits') or ''
                    heritages.append({'title':title,'parent':parent,'href':href,'traits':traits,
                                      'description':str(h.get('description') or ''),'source':'latex'})
            for rule in group.get('feat_rules') or []:
                add_feat(rule,parent=parent,href=href,section=section)
    for row in rows:
        if str(row.get('kind') or '').lower() not in NON_MONSTER_KINDS:continue
        meta=classify_homebrew(row)
        if not include_drafts and not meta.get('published'):continue
        p=dict(row.get('payload') or {});doc=str(p.get('homebrew_document') or '').strip().lower();parent=str(row.get('title') or meta.get('group') or 'Homebrew')
        href=f"/homebrew/entry/{row.get('id')}" if doc in {'ancestry','archetype'} else f"/homebrew#homebrew-entry-{row.get('id')}"
        if doc=='ancestry':
            for h in p.get('heritages') or []:
                if not isinstance(h,dict):continue
                title=str(h.get('title') or h.get('name') or '').strip()
                if not title:continue
                heritages.append({'title':title,'parent':parent,'href':href,'traits':str(h.get('traits') or ''),
                                  'description':str(h.get('description') or ''),'source':'forge'})
            for rule in p.get('bundle_feats') or []:
                if isinstance(rule,dict):add_feat(rule,parent=parent,href=href,section='ancestry')
        elif doc=='archetype':
            dedication_title=str(p.get('dedication_title') or f'{parent} Dedication').strip()
            if dedication_title:
                add_feat({'title':dedication_title,'level':p.get('dedication_level') or 2,'traits':p.get('dedication_traits') or 'archetype, dedication',
                          'description':p.get('dedication_description') or '','action_cost':p.get('dedication_action_cost') or ''},parent=parent,href=href,section='archetype')
            for rule in p.get('bundle_feats') or []:
                if isinstance(rule,dict):add_feat(rule,parent=parent,href=href,section='archetype')
        elif str(meta.get('effective_kind') or '')=='feat':
            rule={'title':row.get('title'),'level':p.get('level'),'traits':p.get('traits') or row.get('tags') or '',
                  'description':p.get('description') or row.get('summary') or '','action_cost':p.get('action_cost') or '', 'feat_category':p.get('feat_category') or ''}
            add_feat(rule,parent=str(meta.get('group') or 'Ungrouped'),href=href,section='',category=str(p.get('feat_category') or ''))
    heritages.sort(key=lambda x:(x['parent'].casefold(),x['title'].casefold()))
    order={'ancestry':0,'archetype':1,'class':2,'general':3,'skill':4,'other':5}
    feats.sort(key=lambda x:(order.get(x['category'],9),x['parent'].casefold(),x['level'],x['title'].casefold()))
    return heritages,feats


def _source_rule_index(source_sections:list[dict]) -> set[tuple[str,str,str]]:
    found=set()
    for section in source_sections:
        for group in section.get('groups',[]):
            source=str(group.get('source_file') or '').replace('\\','/').strip('/')
            for rule in group.get('rules',[]):
                found.add((source,str(rule.get('kind') or '').casefold(),str(rule.get('title') or '').strip().casefold()))
    return found


def _source_bundle_index(source_sections:list[dict]) -> set[tuple[str,str,str]]:
    """Index source-backed ancestry/archetype roots for Forge export de-duplication."""
    found=set()
    for section in source_sections:
        section_key=str(section.get('key') or '').casefold()
        if section_key not in {'ancestry','archetype'}:continue
        for group in section.get('groups',[]):
            source=str(group.get('source_file') or '').replace('\\','/').strip('/')
            name=str(group.get('name') or '').strip().casefold()
            if source and name:found.add((source,section_key,name))
    return found


def _dedupe_exported_homebrew_rows(rows:list[dict],source_sections:list[dict]) -> list[dict]:
    """Hide a Forge row once its generated rule is represented by classified LaTeX.

    The Workshop record remains the editable source of truth; this only prevents
    the Homebrew library from showing the same exported feat twice.
    """
    source_rules=_source_rule_index(source_sections);source_bundles=_source_bundle_index(source_sections);out=[]
    for row in rows:
        payload=dict(row.get('payload') or {})
        path=str(payload.get('latex_export_path') or '').replace('\\','/').strip('/')
        if path and truthy(payload.get('latex_exported')):
            meta=classify_homebrew(row)
            kind=str(meta.get('effective_kind') or '').casefold();title=str(row.get('title') or '').strip().casefold()
            key=(path,kind,title)
            if kind in {'ancestry','archetype'} and key in source_bundles:
                continue
            if key in source_rules:
                continue
        out.append(row)
    return out


# Route `homebrew_library_page` moved to app.route_gm_integrations.


# Route `homebrew_structured_bundle_detail` moved to app.route_gm_integrations.


def _source_homebrew_bundle_or_404(wiki:dict, owner_slug:str) -> dict:
    for section in _homebrew_source_sections(wiki):
        for group in section.get('groups',[]):
            if str(group.get('owner_slug') or '')==str(owner_slug):
                return {'section':section.get('key'),'section_title':section.get('title'),'group':group}
    raise HTTPException(404,'Homebrew source entry not found.')


# Route `homebrew_source_detail` moved to app.route_gm_integrations.


def _source_rule_to_forge(rule:dict) -> dict:
    traits=rule.get('traits') or []
    if isinstance(traits,(list,tuple,set)):traits=', '.join(str(x).strip() for x in traits if str(x).strip())
    try:level=int(rule.get('level') or 0)
    except (TypeError,ValueError):level=0
    title=str(rule.get('title') or '').strip()
    return {
        'kind':'feat','title':title,'level':level,'traits':str(traits or ''),'action_cost':str(rule.get('action_cost') or ''),
        'access':str(rule.get('access') or ''),'prerequisites':str(rule.get('prerequisites') or ''),
        'frequency':str(rule.get('frequency') or ''),'trigger':str(rule.get('trigger') or ''),
        'requirements':str(rule.get('requirements') or ''),'special':str(rule.get('special') or ''),
        'description':str(rule.get('description') or rule.get('plain_text') or ''),
        '_source_original_title':title,'_source_original_level':level,
    }


def _source_bundle_forge_payload(bundle:dict) -> dict:
    section=str(bundle.get('section') or '').strip().lower();group=bundle.get('group') or {}
    title=str(group.get('name') or 'Homebrew').strip();source=str(group.get('source_file') or '').replace('\\','/').strip('/')
    if section not in {'ancestry','archetype'}:raise HTTPException(400,'Only source-backed ancestries and archetypes can currently open as complete Forge documents.')
    feats=[_source_rule_to_forge(r) for r in (group.get('feat_rules') or []) if isinstance(r,dict)]
    payload={
        'homebrew_document':section,'homebrew_publish':True,'library_section':section,'library_group':title,
        'description':'','source_linked':True,'source_link_path':source,'source_link_owner_slug':str(group.get('owner_slug') or ''),
        'source_link_original_title':title,'source_link_current_title':title,'latex_exported':True,'latex_export_path':source,
    }
    if section=='ancestry':
        a=dict(group.get('ancestry') or {})
        payload.update({
            'ancestry_trait':re.sub(r'[^a-z0-9]+','-',title.casefold()).strip('-'),
            'ancestry_hp':str(a.get('hp') or 8),'ancestry_size':str(a.get('size') or 'med'),'ancestry_speed':str(a.get('speed') or 25),
            'ancestry_reach':str(a.get('reach') or 5),'ancestry_vision':str(a.get('vision') or 'normal'),
            'ancestry_languages':str(a.get('languages') or ''),'ancestry_additional_languages':str(a.get('additional_languages') or 0),
            'ancestry_traits':str(a.get('traits') or ''),'ancestry_boosts':str(a.get('boosts') or ''),
            'ancestry_free_boosts':str(a.get('free_boosts') if a.get('free_boosts') is not None else 0),'ancestry_flaws':str(a.get('flaws') or ''),
        })
        heritages=[]
        for raw in group.get('heritages') or []:
            if not isinstance(raw,dict):continue
            h={'title':str(raw.get('title') or raw.get('name') or ''),'rarity':str(raw.get('rarity') or 'common'),'traits':str(raw.get('traits') or ''),'description':str(raw.get('description') or '')}
            h['_source_original_title']=h['title'];heritages.append(h)
        payload['heritages']=heritages;payload['bundle_feats']=feats
    else:
        dedication_index=next((i for i,r in enumerate(feats) if 'dedication' in {x.strip().casefold() for x in str(r.get('traits') or '').split(',')} or str(r.get('title') or '').casefold().endswith(' dedication')),None)
        dedication=feats.pop(dedication_index) if dedication_index is not None else None
        payload.update({'archetype_name':title,'archetype_access':'','archetype_traits':''})
        if dedication:
            payload.update({
                'dedication_title':dedication.get('title') or f'{title} Dedication','dedication_level':str(dedication.get('level') or 2),
                'dedication_action_cost':dedication.get('action_cost') or '','dedication_traits':dedication.get('traits') or 'archetype, dedication',
                'dedication_prerequisites':dedication.get('prerequisites') or '','dedication_frequency':dedication.get('frequency') or '',
                'dedication_trigger':dedication.get('trigger') or '','dedication_requirements':dedication.get('requirements') or '',
                'dedication_special':dedication.get('special') or '','dedication_description':dedication.get('description') or '',
                'source_link_dedication_original_title':dedication.get('title') or '',
            })
        else:
            payload.update({'dedication_title':f'{title} Dedication','dedication_level':'2','dedication_traits':'archetype, dedication'})
        payload['heritages']=[];payload['bundle_feats']=feats
    payload['source_link_snapshot']={
        'title':title,
        'ancestry':{k:payload.get(k,'') for k in ('ancestry_hp','ancestry_size','ancestry_speed','ancestry_reach','ancestry_vision','ancestry_languages','ancestry_additional_languages','ancestry_traits','ancestry_boosts','ancestry_free_boosts','ancestry_flaws')},
        'heritages':[dict(x) for x in payload.get('heritages') or []],
        'bundle_feats':[dict(x) for x in payload.get('bundle_feats') or []],
        'dedication':{k:payload.get(k,'') for k in ('dedication_title','dedication_level','dedication_action_cost','dedication_traits','dedication_prerequisites','dedication_frequency','dedication_trigger','dedication_requirements','dedication_special','dedication_description')},
    }
    lore='\n\n'.join(str(p.get('lore_plain') or '') for p in group.get('lore_pages') or [] if str(p.get('lore_plain') or '').strip())
    return {'kind':'homebrew','title':title,'subtitle':f'Source-linked {section}','summary':lore[:8000],'tags':payload.get('ancestry_traits') or payload.get('archetype_traits') or '', 'target_type':'world','payload':payload}


# Route `homebrew_source_open_in_forge` moved to app.route_gm_integrations.


def _source_rule_foundry_html(rule:dict) -> str:
    # Metadata is sent as structured fields and rendered by the Foundry bridge
    # *before* the body. Keeping description_html body-only avoids duplicated
    # Frequency/Requirements/etc. and guarantees a clean break into rules text.
    return str(rule.get('description_html') or rule.get('html') or '').strip()


# Route `homebrew_source_foundry_push` moved to app.route_gm_integrations.


def _homebrew_entry_or_404(campaign_id:int,entry_id:int) -> dict:
    row=next((x for x in list_foundry_prepared_content(settings,campaign_id) if int(x.get('id') or 0)==int(entry_id)),None)
    if not row or str(row.get('kind') or '').lower() not in NON_MONSTER_KINDS:raise HTTPException(404,'Homebrew entry not found.')
    return row


# Route `homebrew_update` moved to app.route_gm_integrations.


# Route `homebrew_delete` moved to app.route_gm_integrations.


def _project_latex_targets() -> list[dict]:
    rows=[];heading_re=re.compile(r'\\(part|chapter|section|subsection|subsubsection)\*?\s*\{([^{}]+)\}')
    for info in list_project_files(settings):
        if str(info.get('suffix') or '').lower()!='.tex':continue
        rel=str(info.get('path') or '')
        try:text=safe_project_path(settings,rel).read_text(encoding='utf-8',errors='replace')
        except OSError:continue
        seen={};headings=[]
        for match in heading_re.finditer(text):
            level,title=match.group(1),re.sub(r'\s+',' ',match.group(2)).strip();key=(level,title);index=seen.get(key,0);seen[key]=index+1
            headings.append({'level':level,'title':title,'index':index})
        rows.append({'path':rel,'headings':headings})
    return rows


# Route `homebrew_latex` moved to app.route_gm_integrations.


def _suggest_homebrew_tex_path(row:dict) -> str:
    meta=classify_homebrew(row);group=re.sub(r'[^a-z0-9]+','-',str(meta.get('group') or 'misc').lower()).strip('-') or 'misc'
    folder={'ancestry':'ancestries','archetype':'archetypes','class':'classes','general':'feats','actions':'actions','items':'items','other':'misc'}.get(meta['section'],'misc')
    return f'homebrew/{folder}/{group}.tex'


def _manual_homebrew_duplicate(text:str,row:dict) -> bool:
    meta=classify_homebrew(row);kind=str(meta.get('effective_kind') or '')
    title=str(row.get('title') or '').strip()
    if not title:return False
    if kind in {'ancestry','archetype'}:
        # Complete Forge bundles export as a named section. Treat an existing
        # chapter/section/subsection of the same name as the source-backed copy
        # instead of appending an entire duplicate ancestry/archetype.
        return bool(re.search(r'\\(?:chapter|section|subsection)\*?\s*\{\s*'+re.escape(title)+r'\s*\}',text,re.I))
    command='feat' if kind=='feat' else 'action' if kind=='action' else 'itemtemplate' if kind=='item' else ''
    if not command:return False
    return bool(re.search(r'\\'+re.escape(command)+r'\s*\{\s*'+re.escape(title)+r'\s*\}',text,re.I))


# Route `homebrew_latex_write` moved to app.route_gm_integrations.



# Route `v6_media_page` moved to app.route_gm_integrations.


def _display_payload_for_token(state:dict,campaign_id:int,token:str='')->dict:
    out=dict(state or {})
    source=str(out.get('source_url') or '')
    if token and out.get('media_item_id') and (source.startswith('/uploads/') or source.startswith('/project-asset/')):
        out['source_url']=f"/api/v6/display/{int(campaign_id)}/asset/{int(out['media_item_id'])}?token={quote(str(token))}"
    return out


# Route `v6_display_page` moved to app.route_gm_integrations.


# Route `v6_lore_history_page` moved to app.route_gm_integrations.


# Route `v6_integrations_get` moved to app.route_integration_api.


# Route `v6_integrations_save` moved to app.route_integration_api.


# Route `v6_integrations_rotate` moved to app.route_integration_api.


# Route `v6_discord_test` moved to app.route_integration_api.


# Route `v6_discord_send` moved to app.route_integration_api.


_FOUNDRY_CORS={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type','Access-Control-Max-Age':'86400'}


# Route `v6_foundry_push_options` moved to app.route_integration_api.


# Route `v61_foundry_push_ack_options` moved to app.route_integration_api.


# Route `v614_foundry_commands_options` moved to app.route_integration_api.


# Route `v704_foundry_commands_start_options` moved to app.route_integration_api.


# Route `v6_foundry_push` moved to app.route_integration_api.


# Route `v61_foundry_push_ack` moved to app.route_integration_api.


# Route `v614_foundry_commands` moved to app.route_integration_api.


# Route `v704_foundry_commands_start` moved to app.route_integration_api.


# Route `v704_foundry_command_list` moved to app.route_integration_api.


# Route `v704_foundry_command_status` moved to app.route_integration_api.


# Route `v704_foundry_command_retry` moved to app.route_integration_api.


# Route `v6_foundry_state` moved to app.route_integration_api.


# Route `v61_foundry_manifest` moved to app.route_integration_api.


# Route `v61_foundry_public_module` moved to app.route_integration_api.


# Route `v6_foundry_module` moved to app.route_integration_api.


# Route `v61_foundry_actors` moved to app.route_integration_api.


# Route `v61_foundry_workshop_state` moved to app.route_integration_api.


# Route `v61_foundry_content_save` moved to app.route_integration_api.


# Route `v61_foundry_content_delete` moved to app.route_integration_api.


def _forge_bundle_foundry_payload(item:dict) -> tuple[str,dict] | None:
    """Translate a structured Forge ancestry/archetype into a bridge bundle.

    The Workshop stores the whole object as one editable row.  Foundry receives
    a bundle so the ancestry/heritages/feats or archetype/dedication/feats stay
    together without creating duplicate Forge rows for their child rules.
    """
    data=dict(item.get('payload') or {})
    document=str(data.get('homebrew_document') or '').strip().lower()
    if str(item.get('kind') or '').lower()!='homebrew' or document not in {'ancestry','archetype'}:
        return None
    title=str(item.get('title') or ('Custom Ancestry' if document=='ancestry' else 'Custom Archetype')).strip()
    rules=[]
    if document=='archetype':
        dedication={
            'kind':'feat','title':str(data.get('dedication_title') or f'{title} Dedication'),
            'level':int(data.get('dedication_level') or 2),'traits':str(data.get('dedication_traits') or 'archetype, dedication'),
            'action_cost':str(data.get('dedication_action_cost') or ''),'prerequisites':str(data.get('dedication_prerequisites') or ''),
            'frequency':str(data.get('dedication_frequency') or ''),'trigger':str(data.get('dedication_trigger') or ''),
            'requirements':str(data.get('dedication_requirements') or ''),'special':str(data.get('dedication_special') or ''),
            'description':str(data.get('dedication_description') or ''),'is_dedication':True,
        }
        if dedication['title'].strip():rules.append(dedication)
    for raw in data.get('bundle_feats') if isinstance(data.get('bundle_feats'),list) else []:
        if not isinstance(raw,dict):continue
        rule=dict(raw);rule.setdefault('kind','feat');rules.append(rule)
    payload={
        'title':title,'section':document,'owner_slug':f"forge-{int(item.get('id') or 0)}",
        'prepared_id':int(item.get('id') or 0),'description':str(data.get('description') or item.get('summary') or ''),
        'description_html':'','folder_name':f'Seeker · {title}','rules':rules,
    }
    if document=='ancestry':
        payload['ancestry']={
            'hp':int(data.get('ancestry_hp') or 8),'size':str(data.get('ancestry_size') or 'med'),
            'speed':int(data.get('ancestry_speed') or 25),'reach':int(data.get('ancestry_reach') or 5),
            'vision':str(data.get('ancestry_vision') or 'normal'),'languages':str(data.get('ancestry_languages') or 'common'),
            'additional_languages':int(data.get('ancestry_additional_languages') or 0),'boosts':str(data.get('ancestry_boosts') or ''),
            'free_boosts':int(data.get('ancestry_free_boosts') or 2),'flaws':str(data.get('ancestry_flaws') or ''),
            'traits':str(data.get('ancestry_traits') or data.get('traits') or item.get('tags') or ''),
        }
        payload['heritages']=[dict(x) for x in (data.get('heritages') or []) if isinstance(x,dict)]
    else:
        payload['access']=str(data.get('archetype_access') or '')
    return ('push_ancestry_bundle' if document=='ancestry' else 'push_homebrew_rule_bundle'),payload


# Route `v61_foundry_content_push` moved to app.route_integration_api.


# Route `v71_character_foundry_state` moved to app.route_integration_api.


# Route `v61_character_foundry_action` moved to app.route_integration_api.


# Route `v61_character_foundry_link` moved to app.route_integration_api.


# Route `v6_calendar_feed` moved to app.route_integration_api.


# Route `v6_session_ics` moved to app.route_integration_api.


# Route `v6_lore_revisions` moved to app.route_integration_api.


# Route `v6_lore_revision_diff` moved to app.route_integration_api.


# Route `v6_lore_restore` moved to app.route_integration_api.


# Route `v6_knowledge_matrix` moved to app.route_integration_api.


# Route `v6_converge` moved to app.route_integration_api.


# Route `v6_changes` moved to app.route_integration_api.


# Route `v6_continuity` moved to app.route_integration_api.


# Route `v6_checkpoint` moved to app.route_integration_api.


# Route `v6_undo_latest` moved to app.route_integration_api.


# Route `v6_commands` moved to app.route_integration_api.


# Route `v6_command_action` moved to app.route_integration_api.


# Route `v6_map_annotations` moved to app.route_integration_api.


# Route `v6_map_annotation_save` moved to app.route_integration_api.


# Route `v6_map_annotation_delete` moved to app.route_integration_api.


# Route `v6_travel_history` moved to app.route_integration_api.


# Route `v6_travel_save` moved to app.route_integration_api.


# Route `v6_travel_delete` moved to app.route_integration_api.


# Route `v6_media_list` moved to app.route_integration_api.


# Route `v6_media_save` moved to app.route_integration_api.


# Route `v6_media_delete` moved to app.route_integration_api.


# Route `v6_media_upload` moved to app.route_integration_api.


# Route `v6_display_state` moved to app.route_integration_api.


# Route `v6_display_asset` moved to app.route_integration_api.


# Route `v6_display_set` moved to app.route_integration_api.


# Route `v6_campaign_archive` moved to app.route_integration_api.


# Route `v6_backups` moved to app.route_integration_api.


# Route `v6_backup_create` moved to app.route_integration_api.


# Route `v6_backup_download` moved to app.route_integration_api.


# Route `v6_backup_restore` moved to app.route_integration_api.


# Route `v6_backup_delete` moved to app.route_integration_api.


# Mature legacy endpoints are registered from domain route modules in their
# original ordering. Importing them here keeps ``main`` as the composition root
# while avoiding a 5k-line router and preserving every existing URL/handler.
from . import route_runtime as _routes_runtime  # noqa: E402,F401
from . import route_public_access as _routes_public_access  # noqa: E402,F401
from . import route_studio as _routes_studio  # noqa: E402,F401
from . import route_living as _routes_living  # noqa: E402,F401
from . import route_session_tools as _routes_session_tools  # noqa: E402,F401
from . import route_gm_integrations as _routes_gm_integrations  # noqa: E402,F401
from . import route_integration_api as _routes_integration_api  # noqa: E402,F401

# Route contracts retained in the domain modules: "/api/v6/foundry/push/".
# Runtime guardrails remain: os.getenv("COMPILE_ON_START", "0") and BUILD_LOCK.acquire(blocking=False).
# Service-worker responses retain: {"Cache-Control": "no-cache, no-store, must-revalidate"}.
# Studio responses retain: TemplateResponse("admin.html", {"request": request, "title": "Seeker Studio"}, headers={"Cache-Control": "no-store"})

# V7 routes live in their own module to keep the legacy main router readable.
register_v7_routes(app,settings,templates,{
    'settings_provider':lambda: settings,
    'active_campaign_id':_active_campaign_id,
    'visible_wiki':_visible_wiki,
    'require_gm':require_gm,
    'require_admin':require_admin,
    'player_allowed':player_allowed,
    'invite_id':_invite_id,
    'requester_label':requester_label,
    'player_role':player_role,
    'has_permission':v7_has_permission,
    'require_permission':require_v7_permission,
    'is_admin':is_admin,
})

# Campaign Workspace is a unifying layer over the mature V5–V7 subsystems.
register_v8_routes(app,settings,templates,{
    'settings_provider':lambda: settings,
    'active_campaign_id':_active_campaign_id,
    'visible_wiki':_visible_wiki,
    'require_gm':require_gm,
    'require_admin':require_admin,
    'player_allowed':player_allowed,
    'player_gate_redirect':player_gate_redirect,
    'invite_id':_invite_id,
    'requester_label':requester_label,
    'is_gm':is_gm,
    'ensure_built':ensure_built,
})

# Live-play and library extensions build on the Campaign Workspace without
# changing its public route or branding.
register_v9_routes(app,settings,{
    'active_campaign_id':_active_campaign_id,
    'visible_wiki':_visible_wiki,
    'require_gm':require_gm,
    'require_admin':require_admin,
    'invite_id':_invite_id,
    'requester_label':requester_label,
})

# V10 is deliberately additive: old URLs and feature APIs remain intact while
# the workspace gains realtime events, diagnostics, preview and run-of-show cues.
register_v10_routes(app,settings,{
    'active_campaign_id':_active_campaign_id,
    'visible_wiki':_visible_wiki,
    'require_gm':require_gm,
    'require_admin':require_admin,
    'player_allowed':player_allowed,
    'requester_label':requester_label,
})

# Route `handout_creator_artwork` moved to app.route_studio.
