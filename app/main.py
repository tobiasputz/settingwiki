from __future__ import annotations

import functools
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
    get_codex_presentation, get_setting, init_db, list_player_invites, list_project_files, list_revisions,
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
    init_v6_db, integration_config, save_integration_config, discord_post, discord_session_confirmation,
    foundry_accept, foundry_state, foundry_actors, foundry_link, foundry_link_for_character, foundry_manifest, build_foundry_module_zip,
    list_foundry_prepared_content, save_foundry_prepared_content, delete_foundry_prepared_content,
    queue_foundry_command, claim_foundry_commands, complete_foundry_commands, recent_foundry_commands,
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

settings = load_settings()
BUILD_LOCK = threading.Lock()
init_db(settings)
init_feature_db(settings)
init_schedule_db(settings)
init_v5_db(settings)
init_v51_db(settings)
init_v6_db(settings)
init_v7_db(settings)
seed_project(settings)

app = FastAPI(title="Seeker", docs_url=None, redoc_url=None)
_secure_session_cookie = os.getenv("SESSION_COOKIE_SECURE", "1" if os.getenv("RAILWAY_ENVIRONMENT") else "0").lower() in {"1", "true", "yes"}
app.add_middleware(
    SessionMiddleware, secret_key=settings.session_secret, https_only=_secure_session_cookie,
    same_site="lax", max_age=60 * 60 * 24 * 30,
)
app.mount("/static", StaticFiles(directory=settings.root_dir / "static"), name="static")
templates = Jinja2Templates(directory=settings.root_dir / "templates")


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


def is_admin(request: Request) -> bool:
    """True only for the campaign owner authenticated with ADMIN_PASSWORD."""
    return bool(request.session.get("admin"))


def is_co_gm(request: Request) -> bool:
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


@app.middleware("http")
async def archive_read_only_guard(request: Request, call_next):
    """Freeze campaign mutations while archive mode is enabled.

    Reader-local state (notification reads/bookmarks/activity) and access control
    remain usable. The owner can always disable archive mode again.
    """
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and archive_mode():
        path = request.url.path
        if path.startswith("/api/") and not any(path.startswith(prefix) for prefix in _ARCHIVE_WRITE_ALLOW):
            return JSONResponse(
                {"detail": "This campaign is archived and read-only. Disable archive mode as the owner before changing campaign content."},
                status_code=403,
            )
    return await call_next(request)


def ensure_built() -> dict:
    try:
        wiki=load_wiki(settings)
        # V6 keeps a bounded rendered revision history. This is essentially free
        # on normal requests because sync_lore_revisions exits immediately when
        # the wiki generation timestamp has not changed.
        try:
            sync_lore_revisions(settings,wiki)
        except Exception:
            pass
        return wiki
    except Exception:
        return {"title": "Seeker", "tagline": "Import a LaTeX campaign project in /admin.", "categories": [], "pages": [], "generated_at": time.time(), "renderer_version": 6100}


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
    # table when all of its active campaign memberships were removed or
    # archived. Without this guard, read routes would inherit the default
    # campaign id and could expose that party's session state. Public/password
    # access has no invitation membership to resolve, so it intentionally uses
    # the default campaign as the setting's public table.
    if not campaigns and iid is not None and not gm:
        raise HTTPException(403, "This invitation is not assigned to an active campaign. Ask the GM to add you to a campaign.")
    if not campaigns:
        cid=default_campaign_id(settings);campaigns=[get_campaign(settings,cid) or {'id':cid,'name':'Main Campaign','slug':'main-campaign','status':'active','is_default':1}]
    allowed={int(c['id']) for c in campaigns if c and (gm or c.get('status')=='active')}
    requested=request.session.get('active_campaign_id')
    try:requested=int(requested)
    except (TypeError,ValueError):requested=0
    if requested not in allowed:
        preferred=next((c for c in campaigns if c and int(c.get('is_default') or 0) and int(c['id']) in allowed),None)
        active=preferred or next((c for c in campaigns if c and int(c['id']) in allowed),campaigns[0])
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
        category["pages"]=[by_slug[p.get("slug")] for p in source_category.get("pages",[]) if p.get("slug") in by_slug]
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
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    rows: list[dict] = []
    for path in settings.project_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in allowed:
            rel = path.relative_to(settings.project_dir).as_posix()
            rows.append({"ref": f"project:{rel}", "url": "/project-asset/" + quote(rel, safe="/"), "path": rel, "source": "project", "name": path.name})
    for path in settings.uploads_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in allowed:
            rel = path.relative_to(settings.uploads_dir).as_posix()
            rows.append({"ref": f"upload:{rel}", "url": "/uploads/" + quote(rel, safe="/"), "path": rel, "source": "upload", "name": path.name})
    rows.sort(key=lambda x: (x["source"], x["path"].lower()))
    return rows


@app.on_event("startup")
def startup_build() -> None:
    try:
        tex_files=list(settings.project_dir.rglob("*.tex"))
        if tex_files:
            index_path=settings.build_dir / "wiki_index.json"
            needs_build=not index_path.exists()
            if not needs_build:
                try:
                    existing=load_wiki(settings)
                    needs_build=int(existing.get("renderer_version") or 0) < 6100
                    index_mtime=index_path.stat().st_mtime_ns
                    if not needs_build:
                        source_files=tex_files+list(settings.project_dir.rglob("*.sty"))+list(settings.project_dir.rglob("*.cls"))
                        needs_build=any(p.stat().st_mtime_ns>index_mtime for p in source_files)
                except Exception:
                    needs_build=True
            if needs_build:
                build_wiki(settings)
            # PDF compilation is intentionally opt-in on boot. TeX is the
            # heaviest process in this container and can transiently consume far
            # more memory than the web app. The Studio compile action remains
            # available, and COMPILE_ON_START=1 restores the old behavior.
            if os.getenv("COMPILE_ON_START", "0").lower() in {"1", "true", "yes"}:
                compile_pdf(settings)
    except Exception as exc:
        print(f"Seeker startup build warning: {exc}", flush=True)


_V6_BACKUP_THREAD_STARTED=False
@app.on_event("startup")
def startup_v6_backups() -> None:
    """Keep rolling portable backups without putting archive work on requests.

    The sleeping daemon wakes only a few times per day and creates at most one
    archive per 24h, so steady-state Railway cost is negligible.
    """
    global _V6_BACKUP_THREAD_STARTED
    if _V6_BACKUP_THREAD_STARTED:
        return
    _V6_BACKUP_THREAD_STARTED=True
    def worker():
        time.sleep(12)
        while True:
            try:
                maybe_auto_backup(settings)
            except Exception as exc:
                print(f"Seeker automatic backup warning: {exc}", flush=True)
            time.sleep(6*60*60)
    threading.Thread(target=worker,name="seeker-backups",daemon=True).start()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "project": bool(list(settings.project_dir.rglob("*.tex")))}


@app.get("/access", response_class=HTMLResponse)
def invitation_required_page(request: Request):
    if player_allowed(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "mode": "invite", "title": ensure_built().get("title", "Campaign Atlas")},
        status_code=401,
    )


@app.get("/invite/{token}")
def accept_player_invite(request: Request, token: str):
    invite = resolve_player_invite(settings, token, record_use=False)
    if not invite:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request, "mode": "invite", "title": ensure_built().get("title", "Campaign Atlas"),
                "error": "This invitation is invalid, expired, or has been revoked. Ask your GM for a new link.",
            },
            status_code=403,
        )
    target = request.query_params.get("next", "/")
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    # A GM following a link to inspect it should never consume one of a player's
    # optional device slots. The admin session already has player-view access.
    if is_admin(request):
        return RedirectResponse(target, status_code=303)

    old_device = None
    if request.session.get("player_invite_id") == int(invite["id"]) and request.session.get("player_invite_version") == int(invite["access_version"]):
        old_device = request.session.get("player_device_id")
    try:
        device_id = register_player_device(
            settings, int(invite["id"]), int(invite["access_version"]),
            existing_device_id=old_device, user_agent=request.headers.get("user-agent", ""),
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "mode": "invite", "title": ensure_built().get("title", "Campaign Atlas"), "error": str(exc)},
            status_code=403,
        )
    invite = resolve_player_invite(settings, token, record_use=True) or invite
    request.session.clear()
    request.session["player_invite_id"] = int(invite["id"])
    request.session["player_invite_version"] = int(invite["access_version"])
    request.session["player_invite_label"] = str(invite["label"])
    request.session["player_device_id"] = device_id
    if str(invite.get("role") or "player") == "co-gm":
        request.session["co_gm"] = True
        if target in {"/", "/access"}: target = "/admin/campaign"
    return RedirectResponse(target, status_code=303)


@app.get("/login", response_class=HTMLResponse)
def player_login_page(request: Request):
    if player_access_mode() != "password":
        return RedirectResponse("/access", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "mode": "player", "title": ensure_built().get("title", "Campaign Atlas")})


@app.post("/login")
def player_login(request: Request, password: str = Form(...)):
    if player_access_mode() != "password":
        return RedirectResponse("/access", status_code=303)
    if settings.player_password and secrets.compare_digest(password, settings.player_password):
        request.session["player_password"] = True
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "mode": "player", "error": "Wrong password.", "title": ensure_built().get("title", "Campaign Atlas")}, status_code=401)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "mode": "admin", "title": "Seeker Studio"})


@app.post("/admin/login")
def admin_login(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, settings.admin_password):
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "mode": "admin", "error": "Wrong password.", "title": "Seeker Studio"}, status_code=401)


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear(); return {"ok": True}

@app.get("/api/campaign/context")
def campaign_context_api(request: Request):
    if not player_allowed(request): raise HTTPException(401)
    return _campaign_context(request)


@app.post("/api/campaign/select")
def campaign_select_api(request: Request,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    try: cid=int(payload.get("campaign_id"))
    except (TypeError,ValueError): raise HTTPException(400,"Choose a valid campaign.")
    if is_gm(request):
        campaign=get_campaign(settings,cid)
        if not campaign: raise HTTPException(404,"Campaign not found.")
    else:
        iid=_invite_id(request)
        campaign=get_campaign(settings,cid)
        if not campaign or campaign.get("status")!="active" or not invite_has_campaign(settings,iid,cid):
            raise HTTPException(403,"This invitation does not have access to that campaign.")
    request.session["active_campaign_id"]=cid
    # Character identity is table-specific. Never carry it across campaigns.
    request.session.pop("session_character_id",None)
    request.session.pop("session_character_session_id",None)
    return {"ok":True,"campaign":campaign}


@app.get("/tables", response_class=HTMLResponse)
def all_tables_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    gm=is_gm(request);iid=_invite_id(request);wiki=_visible_wiki(request);maps=list_maps(settings,public=True)
    campaigns=list_campaigns(settings,invite_id=iid,admin=gm,include_archived=gm)
    today=__import__('datetime').date.today();end=today+__import__('datetime').timedelta(days=120)
    cards=[]
    for c in campaigns:
        cid=int(c['id']);chars=list_player_characters(settings,invite_id=iid,admin=gm,campaign_id=cid)
        own=[x for x in chars if iid is not None and int(x.get('invite_id') or -1)==int(iid)]
        planner=None
        if gm and c.get('status')=='active':
            try: planner=campaign_schedule(settings,cid,today.isoformat(),end.isoformat())
            except Exception: planner=None
        cards.append({**c,'characters':chars,'own_characters':own,'planner':planner,'live_session':get_live_session(settings,invite_id=iid,admin=gm,campaign_id=cid)})
    return templates.TemplateResponse('tables.html',{'request':request,'wiki':wiki,'maps':maps,'table_cards':cards,'gm_view':gm,'all_tables_view':True})


@app.post("/api/admin/campaigns")
def admin_campaign_save_api(request:Request,payload:dict=Body(...)):
    require_admin(request)
    try:return save_campaign(settings,payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post("/api/admin/campaigns/{campaign_id}/default")
def admin_campaign_default_api(request:Request,campaign_id:int):
    require_admin(request)
    try:return make_default_campaign(settings,campaign_id)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post("/api/admin/campaigns/{campaign_id}/archive")
def admin_campaign_archive_api(request:Request,campaign_id:int):
    require_admin(request)
    try:return archive_campaign(settings,campaign_id)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete("/api/admin/campaigns/{campaign_id}")
def admin_campaign_delete_api(request:Request,campaign_id:int):
    require_admin(request)
    try:
        row=get_campaign(settings,campaign_id)
        if not row:raise ValueError('Campaign not found.')
        # The UI used to make the default campaign effectively undeletable. For an
        # owner-requested permanent deletion, transparently promote another active
        # table first. The final remaining campaign is still protected.
        if int(row.get('is_default') or 0):
            alternatives=[c for c in list_campaigns(settings,admin=True,include_archived=True) if int(c['id'])!=int(campaign_id)]
            if not alternatives:raise ValueError('Create another campaign before deleting the final table.')
            replacement=next((c for c in alternatives if c.get('status')=='active'),alternatives[0])
            if replacement.get('status')!='active':
                save_campaign(settings,{**replacement,'status':'active'})
            make_default_campaign(settings,int(replacement['id']))
        delete_campaign(settings,campaign_id)
        if int(request.session.get("campaign_id") or 0)==int(campaign_id):request.session["campaign_id"]=default_campaign_id(settings)
        return {"ok":True,"deleted":int(campaign_id),"active_campaign_id":request.session.get('campaign_id')}
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); maps = list_maps(settings, public=True)
    featured = [p for p in wiki.get("pages", []) if p.get("presentation", {}).get("featured")][:6]
    iid=_invite_id(request); gm=is_gm(request); cid=_active_campaign_id(request); updates=recent_updates(settings,iid,6,admin=gm,campaign_id=cid);live=get_live_session(settings,invite_id=iid,admin=gm,campaign_id=cid)
    if not gm:
        allowed={p.get("slug") for p in wiki.get("pages",[])}
        updates=[u for u in updates if u.get("target_type")!="lore" or not u.get("target_key") or u.get("target_key") in allowed]
    home_threads=list_threads(settings,admin=gm,invite_id=iid,campaign_id=cid)[:5]
    home_chars=list_player_characters(settings,invite_id=iid,admin=gm,campaign_id=cid)[:5]
    home_fronts=list_fronts(settings,admin=gm,invite_id=iid,campaign_id=cid)[:4]
    home_notifications=list_notifications(settings,iid,admin=gm,campaign_id=cid)[:6]
    player_v6=player_dashboard(settings,cid,int(iid)) if (iid is not None and not gm) else None
    return templates.TemplateResponse("home.html", {"request": request, "wiki": wiki, "maps": maps, "featured": featured,"updates":updates,"live_session":live,"mysteries":list_mysteries(settings,admin=gm,campaign_id=cid)[:4],"threads":home_threads,"characters":home_chars,"fronts":home_fronts,"notifications":home_notifications,"calendar":_calendar_config(),"player_v6":player_v6})


@app.get("/wiki/{slug}", response_class=HTMLResponse)
def wiki_page(request: Request, slug: str):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); pages = wiki.get("pages", [])
    found = next(((i,p) for i,p in enumerate(pages) if p["slug"] == slug), None)
    if not found:
        alias_target=wiki.get("aliases",{}).get(unquote(slug).casefold())
        if alias_target and any(p.get("slug")==alias_target for p in pages): return RedirectResponse(f"/wiki/{alias_target}",status_code=302)
        raise HTTPException(404, "Wiki page not found")
    idx,cached_page=found
    # The visible Codex is a bounded shared cache. Article-only enrichment must
    # never mutate that cached object or one reader could affect later requests.
    page=dict(cached_page)
    page["presentation"]=dict(cached_page.get("presentation",{}))
    page["entity_style"]=dict(cached_page.get("entity_style",{}))
    page["explicit_relationships"]=[dict(r) for r in cached_page.get("explicit_relationships",[])]
    page["variants"]=[dict(v) for v in cached_page.get("variants",[])]
    # Gallery extraction is only useful on the article being rendered. v4 did
    # this regex scan for every visible page on every Codex/search request.
    page["gallery"] = _gallery_from_html(page.get("html", ""))
    prev_page = pages[idx-1] if idx > 0 else None
    next_page = pages[idx+1] if idx + 1 < len(pages) else None
    page_locked = (not is_gm(request) and page.get("presentation", {}).get("visibility") == "teaser")
    has_maps,map_locations=map_locations_for_page(settings,slug,public=not is_gm(request))
    cid=_active_campaign_id(request); appearances=session_appearances_for_page(settings,slug,public=not is_gm(request),campaign_id=cid)
    by_slug={p["slug"]:p for p in pages}
    for rel in page.get("explicit_relationships",[]):
        other=rel["target_slug"] if rel["source_slug"]==slug else rel["source_slug"]
        rel["other_slug"]=other;rel["other_title"]=by_slug.get(other,{}).get("title",other)
        rel["direction"]="out" if rel["source_slug"]==slug else "in"
    dossier_type=page.get("entity_style",{}).get("dossier_type","auto")
    if dossier_type=="auto": dossier_type="person" if page.get("level")=="entity" else ("location" if map_locations else "lore")
    page["dossier_type"]=dossier_type
    return templates.TemplateResponse(
        "page.html",
        {
            "request": request, "wiki": wiki, "page": page, "prev_page": prev_page, "next_page": next_page,
            "page_locked": page_locked, "admin_view": is_gm(request),"maps":([{"id":1}] if has_maps else []),"map_locations":map_locations,"appearances":appearances,
            "runtime_state": runtime_state_for_page(settings,slug,admin=is_gm(request)),"provenance":entity_provenance(settings,slug,campaign_id=cid),
            "update_status":page_update_status(settings,slug,_invite_id(request)) if not is_gm(request) else {'updated_since_read':False},
        },
    )


@app.get("/structures", response_class=HTMLResponse)
def structures_page(request:Request):
    if not player_allowed(request):return player_gate_redirect(request)
    wiki=_visible_wiki(request);allowed={p.get('slug') for p in wiki.get('pages',[])};titles={p.get('slug'):p.get('title') for p in wiki.get('pages',[])}
    charts=[]
    for chart in hierarchies(settings,admin=is_gm(request)):
        edges=[e for e in chart.get('nodes',[]) if e.get('child_slug') in allowed and (not e.get('parent_slug') or e.get('parent_slug') in allowed)]
        if not edges:continue
        children={};relations={};child_set=set()
        for e in edges:
            child=e.get('child_slug');parent=e.get('parent_slug');child_set.add(child);relations[child]=e.get('relation') or ''
            if parent:children.setdefault(parent,[]).append(child)
        roots=[]
        for e in edges:
            p=e.get('parent_slug');c=e.get('child_slug')
            if p and p not in child_set and p not in roots:roots.append(p)
            if not p and c not in roots:roots.append(c)
        if not roots:
            roots=[edges[0].get('parent_slug') or edges[0].get('child_slug')]
        charts.append({**chart,'nodes':edges,'children':children,'relations':relations,'roots':roots,'titles':titles})
    return templates.TemplateResponse('structures.html',{'request':request,'wiki':wiki,'maps':list_maps(settings,public=True),'charts':charts})


@app.get("/network", response_class=HTMLResponse)
def lore_network(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); maps = list_maps(settings, public=True)
    allowed = {p.get("slug") for p in wiki.get("pages", [])}
    nodes = [{
        "slug": p["slug"], "title": p["title"], "chapter": p.get("chapter") or "Setting",
        "level": p.get("level") or "section",
        "image": p.get("presentation", {}).get("display_toc_image_url") or p.get("entity_style",{}).get("crest_url","") or "",
    } for p in wiki.get("pages", [])]
    edges=[]; seen_pairs=set()
    for p in wiki.get("pages", []):
        for target in p.get("outgoing_links", []):
            if target not in allowed or target == p.get("slug"): continue
            key=tuple(sorted((p["slug"],target)))
            if key in seen_pairs: continue
            seen_pairs.add(key); edges.append({"source":p["slug"],"target":target,"kind":"reference","explicit":False})
    explicit_seen=set()
    for rel in list_relationships(settings,admin=is_gm(request)):
        source,target=rel.get("source_slug"),rel.get("target_slug")
        if source not in allowed or target not in allowed or source==target: continue
        key=tuple(sorted((source,target)))+(str(rel.get("relation") or "related to"),)
        if key in explicit_seen: continue
        explicit_seen.add(key); edges.append({"source":source,"target":target,"label":rel.get("label") or rel.get("relation") or "related to","relation":rel.get("relation") or "related to","kind":"relationship","explicit":True})
    historical=[]
    for rel in relationship_history(settings,admin=is_gm(request)):
        source,target=rel.get('source_slug'),rel.get('target_slug')
        if source in allowed and target in allowed and source!=target:
            historical.append({"source":source,"target":target,"label":rel.get('label') or rel.get('relation') or 'related to',"relation":rel.get('relation') or 'related to',"kind":"historical","explicit":True,"start_sort":rel.get('start_sort'),"end_sort":rel.get('end_sort'),"start_label":rel.get('start_label') or '',"end_label":rel.get('end_label') or ''})
    bounds=[]
    for h in historical:
        if h.get('start_sort') is not None:bounds.append(float(h['start_sort']))
        if h.get('end_sort') is not None:bounds.append(float(h['end_sort']))
    network={"nodes":nodes,"edges":edges,"historical_edges":historical,"history_min":min(bounds) if bounds else None,"history_max":max(bounds) if bounds else None,"explicit_count":sum(1 for e in edges if e.get("explicit")),"reference_count":sum(1 for e in edges if not e.get("explicit"))}
    return templates.TemplateResponse("network.html", {"request":request,"wiki":wiki,"maps":maps,"network":network})


@app.get("/atlas/{slug}", response_class=HTMLResponse)
def map_page(request: Request, slug: str):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); map_data = get_map(settings, slug, public=True)
    if not map_data: raise HTTPException(404, "Map not found")
    map_data["layers"] = map_layers(settings, int(map_data["id"]), public=True)
    cid=_active_campaign_id(request)
    # Fog geometry is shared canon, while reveal state is table-specific in V5.
    all_fog=fog_regions(settings, int(map_data["id"]), public=False)
    map_data["fog_regions"] = campaign_fog_regions(settings,cid,all_fog,admin=is_gm(request))
    discovery=map_discovery_states(settings,cid,[int(m.get("id")) for m in map_data.get("markers",[]) if m.get("id") is not None])
    discovery_session_ids={int(r.get("first_session_id")) for r in discovery.values() if r.get("first_session_id")}
    discovery_session_labels={}
    if discovery_session_ids:
        with connect(settings) as conn:
            q=','.join('?' for _ in discovery_session_ids)
            for r in conn.execute(f"SELECT id,session_number,title,session_date FROM campaign_sessions WHERE id IN ({q})",tuple(discovery_session_ids)).fetchall():
                discovery_session_labels[int(r['id'])]=(f"Session {r['session_number']} · " if r['session_number'] else "")+str(r['title'] or r['session_date'] or 'Session')
    for marker in map_data.get("markers",[]):
        drow=discovery.get(int(marker.get("id") or 0)) or {}
        marker["discovery_state"]=drow.get("state") or "discovered"
        marker["first_session_id"]=drow.get("first_session_id")
        marker["discovery_session_label"]=discovery_session_labels.get(int(drow.get("first_session_id") or 0),"")
    if is_gm(request) and all_fog:
        fog_ids=[int(r['id']) for r in all_fog]
        q=','.join('?' for _ in fog_ids)
        with connect(settings) as conn:
            overrides={int(r['fog_region_id']):bool(r['revealed']) for r in conn.execute(f"SELECT fog_region_id,revealed FROM campaign_fog_reveals WHERE campaign_id=? AND fog_region_id IN ({q})",(cid,*fog_ids)).fetchall()}
        for fog in map_data["fog_regions"]:fog["campaign_revealed"]=overrides.get(int(fog['id']),bool(fog.get('revealed')))
    if not is_gm(request):
        kidx=knowledge_index(settings,_invite_id(request),campaign_id=cid)
        map_data["markers"]=[m for m in map_data.get("markers",[]) if m.get("discovery_state")!="unknown" and _knowledge_visible_from_index(kidx,"map_marker",f"{map_data['id']}:{m.get('id')}")[0]]
    else:
        kidx={}
    map_data["regions"] = map_regions(settings, int(map_data["id"]), admin=is_gm(request))
    if not is_gm(request):
        map_data["regions"]=[r for r in map_data["regions"] if _knowledge_visible_from_index(kidx,"map_region",str(r.get('id')))[0]]
    map_data["history_min"] = min([float(h.get("start_sort")) for r in map_data["regions"] for h in r.get("history",[]) if h.get("start_sort") is not None], default=0)
    map_data["history_max"] = max([float(h.get("end_sort") if h.get("end_sort") is not None else h.get("start_sort")) for r in map_data["regions"] for h in r.get("history",[]) if h.get("start_sort") is not None], default=0)
    map_data["world_width"] = float(get_setting(settings,"world_width","1000") or 1000)
    map_data["travel_speed"] = float(get_setting(settings,"travel_speed","40") or 40)
    map_data["annotations"] = list_map_annotations(settings,cid,int(map_data["id"]),_invite_id(request),admin=is_gm(request))
    map_data["travel_history"] = travel_legs(settings,cid,int(map_data["id"]))
    live=next((x for x in list_sessions(settings,campaign_id=cid) if x.get("status")=="live"),None)
    return templates.TemplateResponse("map.html", {"request": request, "wiki": wiki, "map": map_data, "maps": list_maps(settings,public=True),"gm_view":is_gm(request),"live_session_id":(live or {}).get("id")})


@app.get("/api/public/search")
def public_search(request: Request, q: str = ""):
    if not player_allowed(request): raise HTTPException(401)
    qn = q.strip()
    if not qn: return []
    wiki = _visible_wiki(request)
    pages=wiki.get("pages",[])
    ranked=[]
    # Local semantic retrieval runs only over the already spoiler-filtered Codex.
    for hit in semantic_search(pages,qn,limit=18):
        ranked.append((float(hit.get("score") or 0)+20,{"type":"lore","href":f"/wiki/{hit['slug']}","slug":hit["slug"],"title":hit["title"],"chapter":hit.get("chapter"),"excerpt":hit.get("excerpt","") ,"semantic_matches":hit.get("semantic_matches",[])}))
    alias_map = wiki.get("aliases", {})
    low=qn.casefold()
    by_slug={p.get("slug"):p for p in pages}
    for alias,target in alias_map.items():
        if low in alias.casefold() or alias.casefold() in low:
            p=by_slug.get(target)
            if p: ranked.append((120 if low==alias.casefold() else 65,{"type":"alias","href":f"/wiki/{p['slug']}","slug":p["slug"],"title":p["title"],"chapter":p.get("chapter"),"excerpt":f"Also known as {alias}. {p.get('excerpt','')}"}))
    # Character dossiers and map locations stay in the same palette.
    for character in list_player_characters(settings, invite_id=_invite_id(request), admin=is_gm(request),campaign_id=_active_campaign_id(request)):
        title=(character.get("name") or "").casefold(); body=" ".join(str(character.get(k) or "") for k in ("summary","biography","goals","ancestry","class_name")).casefold(); score=0
        if low==title: score+=115
        if low in title: score+=45
        for t in re.findall(r"[\w'-]+",low):
            if len(t)>2: score+=min(5,body.count(t))
        if score: ranked.append((score,{"type":"character","href":f"/characters/{character['id']}","title":character.get("name") or "Character","chapter":"Player Characters","excerpt":character.get("summary") or " · ".join(x for x in (character.get("ancestry"),character.get("class_name")) if x)}))
    for map_data in list_maps(settings, public=True):
        map_title=(map_data.get("name") or "").casefold();map_desc=(map_data.get("description") or "").casefold();score=(45 if low in map_title else 0)+sum(min(3,map_desc.count(t)) for t in re.findall(r"[\w'-]+",low) if len(t)>2)
        if score: ranked.append((score,{"type":"map","href":f"/atlas/{map_data['slug']}","title":map_data["name"],"chapter":"Atlas","excerpt":map_data.get("description","")}))
        for marker in map_data.get("markers",[]):
            title=(marker.get("title") or "").casefold();body=(marker.get("body") or "").casefold();ms=(100 if low==title else 38 if low in title else 0)+sum(min(3,body.count(t)) for t in re.findall(r"[\w'-]+",low) if len(t)>2)
            if ms: ranked.append((ms,{"type":"location","href":f"/atlas/{map_data['slug']}?focus={marker['id']}","title":marker.get("title","Location"),"chapter":map_data["name"],"excerpt":marker.get("body","")}))
    # De-duplicate the same Codex entry when an alias and semantic result both hit.
    ranked.sort(key=lambda x:(-x[0],str(x[1].get("title") or "").casefold()))
    out=[];seen=set()
    for _score,item in ranked:
        key=item.get("href") or (item.get("type"),item.get("title"))
        if key in seen: continue
        seen.add(key);out.append(item)
        if len(out)>=24: break
    return out


@app.get("/manifest.webmanifest")
def web_manifest(request: Request):
    wiki = ensure_built()
    campaign_title=str(wiki.get("title") or "").strip()
    payload = {
        "name": f"Seeker — {campaign_title}" if campaign_title and campaign_title.casefold() != "seeker" else "Seeker",
        "short_name": "Seeker",
        "description": wiki.get("tagline", "A living record of the world."),
        "start_url": "/?source=pwa",
        "scope": "/",
        "display": "standalone",
        "background_color": "#0b0c0b",
        "theme_color": "#17130f",
        "orientation": "any",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/seeker-icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}
        ],
        "shortcuts": [
            {"name": "Session", "url": "/session", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]},
            {"name": "Codex", "url": "/#codex", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]},
            {"name": "Chronicle of Ages", "url": "/timeline", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]},
            {"name": "Characters", "url": "/characters", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]},
            {"name": "Calendar", "url": "/calendar", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]}
        ],
    }
    return JSONResponse(payload, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    path = settings.root_dir / "static" / "sw.js"
    return FileResponse(path, media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/session", response_class=HTMLResponse)
def player_session_screen(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request);maps=list_maps(settings,public=True);iid=_invite_id(request);cid=_active_campaign_id(request);gm=is_gm(request)
    live=get_live_session(settings,invite_id=iid,admin=gm,campaign_id=cid)
    all_sessions=list_sessions(settings,public=False,invite_id=iid,campaign_id=cid)
    planned=[dict(x) for x in all_sessions if x.get('status')=='planned']
    # Planned sessions are visible to members for RSVP, but never expose GM-only notes.
    for row in planned: row.pop('gm_notes',None)
    upcoming=planned[0] if planned else None
    session=live or upcoming
    by_slug={p['slug']:p for p in wiki.get('pages',[])}
    if session:
        session['lore_pages']=[by_slug[x['page_slug']] for x in session.get('lore',[]) if x.get('page_slug') in by_slug]
        session['spotlight_map']=next((m for m in maps if m.get('slug')==session.get('spotlight_map_slug')),None)
        # Planned sessions loaded through list_sessions do not carry handouts.
        if 'handouts' not in session:session['handouts']=[]
    allowed={p.get('slug') for p in wiki.get('pages',[])}
    if session and not gm:session['lore']=[x for x in session.get('lore',[]) if x.get('page_slug') in allowed]
    ended=[x for x in all_sessions if x.get('status')=='ended']
    history=list(reversed(ended[-12:]))
    if not gm:
        for row in history:row['lore']=[x for x in row.get('lore',[]) if x.get('page_slug') in allowed]
    previous=history[0] if history else None
    invite=current_player_invite(request)
    can_author=gm or (not archive_mode() and bool(invite) and player_role(request)=='player')
    session_characters,active_character,character_selection_made=_session_character_context(request,session)
    journal_character_filter=None
    if not gm and character_selection_made:journal_character_filter=int((active_character or {}).get('id') or 0)
    party_journals=list_party_journals(settings,iid,admin=gm,character_id=journal_character_filter,campaign_id=cid)
    shared_notes=list_party_notes(settings,cid,int(session['id']) if session else None,120)
    objectives=list_objectives(settings,cid,include_done=False)
    follows=list_follows(settings,int(iid),cid) if iid is not None and not gm else []
    followed_pages=[]
    for f in follows:
        if f.get('target_type')=='page' and f.get('target_key') in by_slug:followed_pages.append({**f,'page':by_slug[f['target_key']]})
    mysteries=list_mysteries(settings,admin=gm,campaign_id=cid)[:12]
    if not gm:
        for mystery in mysteries:
            mystery['pins']=[x for x in mystery.get('pins',[]) if not x.get('page_slug') or x.get('page_slug') in allowed]
            pin_ids={x.get('id') for x in mystery['pins']};mystery['edges']=[e for e in mystery.get('edges',[]) if e.get('source_pin') in pin_ids and e.get('target_pin') in pin_ids]
    own_rsvp=None
    if session and invite:
        own_rsvp=next((r for r in session_rsvps(settings,int(session['id'])) if int(r.get('invite_id') or -1)==int(invite['id'])),None)
    notifications=filter_notifications_for_prefs(settings,iid,list_notifications(settings,iid,admin=gm,campaign_id=cid)[:12],admin=gm)
    # Campaign clocks may be private GM pressure trackers or explicitly public.
    # Never leak GM-only clocks into a player response.
    campaign_clocks=[c for c in list_clocks(settings,cid) if gm or c.get('visibility')=='player']
    return templates.TemplateResponse('session.html',{
        'request':request,'wiki':wiki,'maps':maps,'session':session,'live_session':live,'upcoming_session':upcoming,'previous_session':previous,
        'player':invite,'updates':recent_updates(settings,iid,16,admin=gm,campaign_id=cid),'mysteries':mysteries,'session_history':history,
        'calendar':_calendar_config(),'threads':list_threads(settings,admin=gm,invite_id=iid,campaign_id=cid),'party_journals':party_journals,
        'party_notes':shared_notes,'objectives':objectives,'follows':follows,'followed_pages':followed_pages,'notifications':notifications,
        'gm_view':gm,'can_author':can_author,'archive_mode':archive_mode(),'session_characters':session_characters,'active_character':active_character,
        'character_selection_made':character_selection_made,'own_rsvp':own_rsvp,'campaign_clocks':campaign_clocks,
    })


@app.get("/recap", response_class=HTMLResponse)
def player_recap_screen(request:Request):
    if not player_allowed(request):return player_gate_redirect(request)
    wiki=_visible_wiki(request);iid=_invite_id(request);cid=_active_campaign_id(request);gm=is_gm(request)
    sessions=list_sessions(settings,public=False,invite_id=iid,campaign_id=cid)
    ended=[x for x in sessions if x.get('status')=='ended'];previous=ended[-1] if ended else None
    allowed={p.get('slug') for p in wiki.get('pages',[])}
    by_slug={p.get('slug'):p for p in wiki.get('pages',[])}
    lore=[]
    if previous:
        for ref in previous.get('lore',[]):
            if ref.get('page_slug') in allowed and ref.get('page_slug') in by_slug:lore.append(by_slug[ref['page_slug']])
    mysteries=list_mysteries(settings,admin=gm,campaign_id=cid)[:10]
    if not gm:
        for m in mysteries:m['pins']=[x for x in m.get('pins',[]) if not x.get('page_slug') or x.get('page_slug') in allowed]
    journals=list_party_journals(settings,iid,admin=gm,campaign_id=cid)[:16]
    return templates.TemplateResponse('recap.html',{
        'request':request,'wiki':wiki,'maps':list_maps(settings,public=True),'previous':previous,'lore':lore,
        'updates':recent_updates(settings,iid,16,admin=gm,campaign_id=cid),'objectives':list_objectives(settings,cid,include_done=False),
        'mysteries':mysteries,'journals':journals,'gm_view':gm,
    })


@app.post("/api/player/session-character")
def player_session_character(request:Request,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    if is_gm(request): raise HTTPException(403,"GM view does not use a player character identity.")
    iid=_invite_id(request)
    if iid is None: raise HTTPException(403,"A personal invitation is required to choose a session character.")
    cid_active=_active_campaign_id(request);live=get_live_session(settings,invite_id=iid,admin=False,campaign_id=cid_active);session_key=int((live or {}).get("id") or 0)
    requested=payload.get("character_id")
    if requested in (None,"",0,"0"):
        request.session["session_character_id"]=0;request.session["session_character_session_id"]=session_key
        return {"ok":True,"character":None,"session_id":session_key}
    try: cid=int(requested)
    except (TypeError,ValueError): raise HTTPException(400,"Invalid character.")
    char=get_player_character(settings,cid,invite_id=iid,admin=False,campaign_id=cid_active)
    if not char or int(char.get("invite_id") or -1)!=int(iid): raise HTTPException(403,"You can only enter a session as one of your own characters.")
    request.session["session_character_id"]=cid;request.session["session_character_session_id"]=session_key
    return {"ok":True,"character":{"id":cid,"name":char.get("name"),"portrait_url":char.get("portrait_url","")},"session_id":session_key}


@app.get("/schedule", response_class=HTMLResponse)
def schedule_page(request: Request):
    if not player_allowed(request):
        return player_gate_redirect(request)
    gm_view=is_gm(request); invite=current_player_invite(request)
    if not gm_view and not invite:
        raise HTTPException(403,"A personal player invitation is required to save availability.")
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); ctx=_campaign_context(request)
    return templates.TemplateResponse("schedule.html", {
        "request":request,"wiki":wiki,"maps":maps,"gm_view":gm_view,"player":invite,
        "active_campaign":ctx["active_campaign"],
        "player_campaigns":player_campaigns(settings,int(invite["id"])) if invite else [],
    })


@app.get("/api/schedule/me")
def schedule_me_api(request: Request,start:str,end:str):
    if not player_allowed(request): raise HTTPException(401)
    invite=current_player_invite(request)
    if not invite: raise HTTPException(403,"A personal player invitation is required.")
    try: rows=list_player_availability(settings,int(invite["id"]),start,end)
    except ValueError as exc: raise HTTPException(400,str(exc))
    return {"availability":rows,"campaigns":player_campaigns(settings,int(invite["id"]))}


@app.post("/api/schedule/me")
def schedule_me_save_api(request: Request,payload:dict=Body(...)):
    require_player_author(request)
    invite=current_player_invite(request)
    if not invite: raise HTTPException(403,"A personal player invitation is required.")
    try: rows=save_player_availability(settings,int(invite["id"]),payload.get("changes") or [])
    except ValueError as exc: raise HTTPException(400,str(exc))
    return {"ok":True,"saved":rows}


@app.get("/api/gm/schedule")
def gm_schedule_api(request: Request,start:str,end:str,campaign_id:int|None=None):
    require_gm(request)
    cid=resolve_campaign_id(settings,campaign_id if campaign_id is not None else _active_campaign_id(request))
    campaign=get_campaign(settings,cid)
    if not campaign: raise HTTPException(404,"Campaign not found.")
    try: out=campaign_schedule(settings,cid,start,end)
    except ValueError as exc: raise HTTPException(400,str(exc))
    out["campaign"]=campaign
    return out


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True)
    events=list_timeline(settings,admin=is_gm(request),historical_only=True)
    eras=list_timeline_eras(settings,admin=is_gm(request))
    if not is_gm(request):
        kidx=knowledge_index(settings,_invite_id(request),campaign_id=_active_campaign_id(request))
        events=[e for e in events if _knowledge_visible_from_index(kidx,"timeline_event",str(e.get('id')))[0]]
    allowed={p.get("slug") for p in wiki.get("pages",[])}
    for event in events:
        event["image_url"]=_asset_ref_url(event.get("image_ref",""))
        if not is_gm(request) and event.get("page_slug") not in allowed: event["page_slug"]=None
    by_era={int(e["id"]):[] for e in eras}; unplaced=[]
    for event in events:
        eid=event.get("era_id")
        if eid is not None and int(eid) in by_era: by_era[int(eid)].append(event)
        else: unplaced.append(event)
    grouped=[]
    for era in eras:
        row=dict(era); row["events"]=by_era.get(int(era["id"]),[]); grouped.append(row)
    if unplaced: grouped.append({"id":None,"name":"Unplaced history","start_label":"","end_label":"","summary":"Historical records not yet assigned to an era.","accent":"#75674f","events":unplaced})
    return templates.TemplateResponse("timeline.html", {"request":request,"wiki":wiki,"maps":maps,"events":events,"eras":grouped,"calendar_name":get_setting(settings,"calendar_name","Campaign Calendar"),"current_date":get_setting(settings,"campaign_date",""),"calendar":_calendar_config()})


@app.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); cal=_calendar_config()
    festivals=[e for e in list_timeline(settings,admin=is_gm(request)) if e.get("kind")=="festival"]
    return templates.TemplateResponse("calendar.html", {"request":request,"wiki":wiki,"maps":maps,"calendar":cal,"festivals":festivals})


@app.get("/updates", response_class=HTMLResponse)
def updates_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True)
    allowed={p.get("slug") for p in wiki.get("pages",[])}
    cid=_active_campaign_id(request); updates=recent_updates(settings,_invite_id(request),100,admin=is_gm(request),campaign_id=cid)
    if not is_gm(request): updates=[u for u in updates if u.get("target_type")!="lore" or not u.get("target_key") or u.get("target_key") in allowed]
    return templates.TemplateResponse("updates.html", {"request":request,"wiki":wiki,"maps":maps,"updates":updates,"sessions":list_sessions(settings,public=True,invite_id=_invite_id(request),campaign_id=cid)})


@app.get("/mysteries", response_class=HTMLResponse)
def mysteries_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); cid=_active_campaign_id(request); rows=list_mysteries(settings,admin=is_gm(request),campaign_id=cid)
    if not is_gm(request):
        allowed={p.get("slug") for p in wiki.get("pages",[])}
        for mystery in rows:
            mystery["pins"]=[x for x in mystery.get("pins",[]) if not x.get("page_slug") or x.get("page_slug") in allowed]
            pin_ids={x.get("id") for x in mystery["pins"]}
            mystery["edges"]=[e for e in mystery.get("edges",[]) if e.get("source_pin") in pin_ids and e.get("target_pin") in pin_ids]
    return templates.TemplateResponse("mysteries.html", {"request":request,"wiki":wiki,"maps":maps,"mysteries":rows})


@app.get("/handouts", response_class=HTMLResponse)
def handouts_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True)
    cid=_active_campaign_id(request); rows=list_handouts(settings,admin=is_gm(request),campaign_id=cid); allowed={p.get("slug") for p in wiki.get("pages",[])}
    for h in rows:
        h["image_url"]=_asset_ref_url(h.get("image_ref",""))
        if not is_gm(request) and h.get("page_slug") not in allowed: h["page_slug"]=None
    return templates.TemplateResponse("handouts.html", {"request":request,"wiki":wiki,"maps":maps,"handouts":rows})


@app.get("/handout/{slug}", response_class=HTMLResponse)
def handout_page(request: Request, slug: str):
    if not player_allowed(request): return player_gate_redirect(request)
    cid=_active_campaign_id(request); row=next((x for x in list_handouts(settings,admin=is_gm(request),campaign_id=cid) if x["slug"]==slug),None)
    if not row: raise HTTPException(404,"Handout not found")
    row["image_url"]=_asset_ref_url(row.get("image_ref","")); wiki=_visible_wiki(request); maps=list_maps(settings,public=True)
    if not is_admin(request) and row.get("page_slug") not in {p.get("slug") for p in wiki.get("pages",[])}: row["page_slug"]=None
    return templates.TemplateResponse("handout.html", {"request":request,"wiki":wiki,"maps":maps,"handout":row,"admin_view":is_gm(request)})


@app.get("/api/public/session-pulse")
def public_session_pulse(request: Request):
    """Very small live-session heartbeat used every few seconds by clients.

    Do not build a full live-session object here: v4 loaded lore, updates and
    handouts separately on every pulse. This route now uses one connection and
    returns only the timestamps the browser actually compares.
    """
    if not player_allowed(request): raise HTTPException(401)
    iid=_invite_id(request); admin=is_gm(request); cid=_active_campaign_id(request)
    with connect(settings) as conn:
        live_row=conn.execute("SELECT id,updated_at FROM campaign_sessions WHERE campaign_id=? AND status='live' ORDER BY updated_at DESC,id DESC LIMIT 1",(cid,)).fetchone()
        handout_row=conn.execute("SELECT MAX(updated_at) AS value FROM handouts WHERE campaign_id=? AND visibility!='gm'",(cid,)).fetchone()
        if admin:
            update_row=conn.execute("SELECT MAX(created_at) AS value FROM session_updates WHERE campaign_id=? AND visibility!='gm'",(cid,)).fetchone()
            reveal_row=conn.execute("SELECT MAX(updated_at) AS value FROM lore_reveals WHERE campaign_id=?",(cid,)).fetchone()
        elif iid is None:
            update_row=conn.execute("SELECT MAX(created_at) AS value FROM session_updates WHERE campaign_id=? AND visibility!='gm' AND COALESCE(audience_json,'[]')='[]'",(cid,)).fetchone()
            reveal_row=conn.execute("SELECT MAX(updated_at) AS value FROM lore_reveals WHERE campaign_id=? AND COALESCE(audience_json,'[]')='[]'",(cid,)).fetchone()
        else:
            try:
                # JSON1 lets SQLite calculate the newest event visible to this
                # invitation instead of shipping whole reveal/update tables to
                # Python every five seconds for every player at the table.
                audience_clause="(COALESCE(audience_json,'[]')='[]' OR EXISTS (SELECT 1 FROM json_each(audience_json) WHERE CAST(json_each.value AS INTEGER)=?))"
                update_row=conn.execute(f"SELECT MAX(created_at) AS value FROM session_updates WHERE campaign_id=? AND visibility!='gm' AND {audience_clause}",(cid,int(iid))).fetchone()
                reveal_row=conn.execute(f"SELECT MAX(updated_at) AS value FROM lore_reveals WHERE campaign_id=? AND {audience_clause}",(cid,int(iid))).fetchone()
            except Exception:
                # Conservative compatibility fallback for SQLite builds without
                # JSON1. It is bounded so a malformed/ancient database cannot
                # turn the heartbeat into an unbounded allocation.
                update_rows=[dict(r) for r in conn.execute("SELECT created_at,audience_json FROM session_updates WHERE campaign_id=? AND visibility!='gm' ORDER BY created_at DESC LIMIT 250",(cid,)).fetchall()]
                reveal_rows=[dict(r) for r in conn.execute("SELECT updated_at,audience_json FROM lore_reveals WHERE campaign_id=? ORDER BY updated_at DESC LIMIT 250",(cid,)).fetchall()]
                def audience_ok(row):
                    try: audience=json.loads(row.get("audience_json") or "[]")
                    except Exception: audience=[]
                    if not audience:return True
                    try:return int(iid) in {int(x) for x in audience}
                    except Exception:return False
                update_row={"value":next((float(x.get("created_at") or 0) for x in update_rows if audience_ok(x)),0)}
                reveal_row={"value":next((float(x.get("updated_at") or 0) for x in reveal_rows if audience_ok(x)),0)}
    u=float(update_row["value"] or 0) if update_row else 0
    r=float(reveal_row["value"] or 0) if reveal_row else 0
    return {
        "session_id":int(live_row["id"]) if live_row else None,
        "session_updated":float(live_row["updated_at"] or 0) if live_row else 0,
        "latest_update":u,"latest_reveal":r,
        "latest_handout":float(handout_row["value"] or 0) if handout_row else 0,
    }


@app.get("/api/public/page-card/{slug}")
def page_card(request: Request, slug: str):
    if not player_allowed(request): raise HTTPException(401)
    wiki=_visible_wiki(request); p=next((x for x in wiki.get("pages",[]) if x["slug"]==slug),None)
    if not p: raise HTTPException(404)
    return {"slug":p["slug"],"title":p["title"],"chapter":p.get("chapter"),"excerpt":p.get("excerpt","")[:300],"image":p.get("presentation",{}).get("hero_image_url") or p.get("presentation",{}).get("auto_image_url") or p.get("entity_style",{}).get("crest_url","") ,"relationships":p.get("explicit_relationships",[])[:4]}


@app.get("/api/public/annotations/{slug}")
def public_annotations(request: Request, slug: str):
    if not player_allowed(request): raise HTTPException(401)
    iid=_invite_id(request);gm=is_gm(request)
    rows=list_annotations(settings,slug,invite_id=iid,admin=gm)
    for row in rows:
        row["can_delete"]=bool(gm or (iid is not None and row.get("invite_id") is not None and int(row["invite_id"])==int(iid)))
    return rows


@app.post("/api/public/annotations")
def public_add_annotation(request: Request,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    invite=current_player_invite(request); label="GM" if is_gm(request) else (invite or {}).get("label","Player")
    return add_annotation(settings,payload,invite_id=_invite_id(request),author_label=label,admin=is_gm(request))


@app.delete("/api/public/annotations/{annotation_id}")
def public_delete_annotation(request: Request, annotation_id:int):
    if not player_allowed(request): raise HTTPException(401)
    try:
        ok=delete_annotation(settings,annotation_id,invite_id=_invite_id(request),admin=is_gm(request))
    except PermissionError as exc:
        raise HTTPException(403,str(exc))
    if not ok: raise HTTPException(404,"Note not found.")
    return {"ok":True}


@app.post("/api/public/bookmark/{slug}")
def public_bookmark(request: Request,slug:str,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    iid=_invite_id(request)
    if iid is None: return {"ok":True,"local_only":True}
    toggle_bookmark(settings,iid,slug,bool(payload.get("enabled",True))); return {"ok":True}


@app.get("/api/public/bookmarks")
def public_bookmarks(request: Request):
    if not player_allowed(request): raise HTTPException(401)
    iid=_invite_id(request); return [] if iid is None else list_bookmarks(settings,iid)


@app.post("/api/public/activity")
def public_activity(request: Request,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    log_activity(settings,_invite_id(request),str(payload.get("event_type") or "view"),str(payload.get("target_key") or ""),payload.get("meta") or {}); return {"ok":True}


@app.get("/api/public/map/{slug}/travel")
def public_map_travel(request: Request,slug:str,from_id:int,to_id:int):
    if not player_allowed(request): raise HTTPException(401)
    m=get_map(settings,slug,public=True)
    if not m: raise HTTPException(404)
    a=next((x for x in m.get("markers",[]) if int(x["id"])==int(from_id)),None);b=next((x for x in m.get("markers",[]) if int(x["id"])==int(to_id)),None)
    if not a or not b: raise HTTPException(404,"Marker not found")
    width=float(get_setting(settings,"world_width", "1000") or 1000);speed=float(get_setting(settings,"travel_speed", "40") or 40)
    return {"from":a,"to":b,**travel_between_markers(a,b,width,speed)}


@app.get("/share/qr")
def share_qr(request: Request, path: str = "/"):
    if not player_allowed(request): return player_gate_redirect(request)
    if not path.startswith("/") or path.startswith("//"): path="/"
    target=_external_base_url(request)+path
    try:
        import qrcode
        import qrcode.image.svg
        image=qrcode.make(target,image_factory=qrcode.image.svg.SvgPathImage,box_size=8,border=2)
        import io
        out=io.BytesIO(); image.save(out); return Response(out.getvalue(),media_type="image/svg+xml",headers={"Cache-Control":"no-store"})
    except Exception:
        # QR is an enhancement; do not break sharing if the optional renderer is absent.
        return Response(f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="120"><rect width="100%" height="100%" fill="#111"/><text x="20" y="65" fill="#ddd" font-family="sans-serif" font-size="13">{target}</text></svg>',media_type="image/svg+xml")


@app.get("/gm/session", response_class=HTMLResponse)
def gm_session_screen(request: Request):
    require_gm(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=False); cid=_active_campaign_id(request); live=get_live_session(settings,admin=True,campaign_id=cid)
    chars=list_player_characters(settings,admin=True,campaign_id=cid)
    for c in chars:c["arcs"]=character_arcs(settings,int(c["id"]),owner=True)
    all_sessions=list_sessions(settings,campaign_id=cid); objectives=list_objectives(settings,cid,include_done=False)
    workspace=prep_workspace(settings,cid,int(live['id']),chars,all_sessions,objectives) if live else None
    return templates.TemplateResponse("gm_session.html", {"request":request,"wiki":wiki,"maps":maps,"session":live,"sessions":all_sessions,"reveals":list_reveal_blocks_from_wiki(ensure_built()),"mysteries":list_mysteries(settings,admin=True,campaign_id=cid),"handouts":list_handouts(settings,admin=True,campaign_id=cid),"updates":recent_updates(settings,None,20,admin=True,campaign_id=cid),"fronts":list_fronts(settings,admin=True,campaign_id=cid),"characters":chars,"rumors":list_rumors(settings,admin=True,campaign_id=cid),"prep":(get_preparation(settings,int(live["id"])) if live else None),"objectives":objectives,"rsvps":(session_rsvps(settings,int(live["id"])) if live else []),"v51_workspace":workspace})


@app.get("/admin/campaign", response_class=HTMLResponse)
def admin_campaign_page(request: Request):
    require_gm(request)
    wiki=ensure_built(); maps=list_maps(settings,public=False)
    return templates.TemplateResponse("campaign_admin.html", {"request":request,"wiki":wiki,"maps":maps})


@app.get("/project-asset/{asset_path:path}")
def project_asset(request: Request, asset_path: str):
    if not player_allowed(request): raise HTTPException(401)
    path = safe_project_path(settings, unquote(asset_path))
    if not path.exists() or not path.is_file(): raise HTTPException(404)
    return FileResponse(path)


# ---------------------------------------------------------------------------
# Player-owned character dossiers
# ---------------------------------------------------------------------------
@app.get("/characters", response_class=HTMLResponse)
def characters_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); iid=_invite_id(request); admin_view=is_gm(request)
    cid=_active_campaign_id(request); chars=list_player_characters(settings,invite_id=iid,admin=admin_view,campaign_id=cid)
    for c in chars:
        link=foundry_link_for_character(settings,int(c['id']))
        c['foundry_actor_id']=str((link or {}).get('actor_id') or '')
        c['foundry_linked']=bool(link and not link.get('stale'))
    return templates.TemplateResponse("characters.html",{"request":request,"wiki":wiki,"maps":maps,"characters":chars,"player":current_player_invite(request),"admin_view":admin_view,"character_campaigns":list_campaigns(settings,admin=True,include_archived=admin_view),"foundry_actors":foundry_actors(settings,cid)})

@app.get("/characters/{character_id}", response_class=HTMLResponse)
def character_page(request: Request, character_id:int):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); iid=_invite_id(request); admin_view=is_gm(request)
    cid=_active_campaign_id(request); char=get_player_character(settings,character_id,invite_id=iid,admin=admin_view,campaign_id=cid)
    if not char: raise HTTPException(404,"Character not found")
    owner=admin_view or (iid is not None and int(char.get("invite_id") or 0)==int(iid))
    char["arcs"]=character_arcs(settings,character_id,owner=owner)
    char["relationships"]=character_relationships(settings,character_id,owner=owner)
    char["milestones"]=character_milestones(settings,character_id)
    foundry_linked=foundry_link_for_character(settings,character_id)
    char['foundry_actor_id']=str((foundry_linked or {}).get('actor_id') or '')
    can_edit=admin_view or (owner and player_role(request)=="player" and not archive_mode())
    # Detailed Foundry mechanics are private to the character owner and GMs.
    # Party-facing story dossiers stay lightweight even when the actor is linked.
    foundry_view=foundry_linked if (owner or admin_view) else None
    return templates.TemplateResponse("character.html",{"request":request,"wiki":wiki,"maps":maps,"character":char,"can_edit":can_edit,"admin_view":admin_view,"wiki_pages":wiki.get("pages",[]),"character_campaigns":list_campaigns(settings,admin=True,include_archived=admin_view),"character_sessions":list_sessions(settings,public=False,campaign_id=cid),"foundry_actor":foundry_view,"foundry_actors":foundry_actors(settings,cid) if can_edit else []})

@app.get("/api/player/characters")
def player_characters_api(request:Request):
    if not player_allowed(request): raise HTTPException(401)
    return list_player_characters(settings,invite_id=_invite_id(request),admin=is_gm(request),campaign_id=_active_campaign_id(request))

@app.post("/api/player/characters")
def player_character_create(request:Request,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    require_player_author(request)
    iid=_invite_id(request)
    if not is_gm(request) and iid is None: raise HTTPException(403,"An invitation is required to create a character.")
    try: return save_player_character(settings,_campaign_payload(request,payload),invite_id=iid,admin=is_gm(request))
    except PermissionError as exc: raise HTTPException(403,str(exc))
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.put("/api/player/characters/{character_id}")
def player_character_update(request:Request,character_id:int,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    require_player_author(request)
    payload=_campaign_payload(request,payload); payload["id"]=character_id
    try: return save_player_character(settings,payload,invite_id=_invite_id(request),admin=is_gm(request))
    except PermissionError as exc: raise HTTPException(403,str(exc))
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.delete("/api/player/characters/{character_id}")
def player_character_delete(request:Request,character_id:int):
    if not player_allowed(request): raise HTTPException(401)
    require_player_author(request)
    _character_owned(request,character_id)
    try: paths=delete_player_character(settings,character_id,invite_id=_invite_id(request),admin=is_gm(request))
    except PermissionError as exc: raise HTTPException(403,str(exc))
    for rel in paths:
        try:
            path=(settings.uploads_dir/rel).resolve()
            if settings.uploads_dir.resolve() in path.parents and path.exists(): path.unlink()
        except Exception: pass
    return {"ok":True}

@app.post("/api/player/characters/{character_id}/images")
async def player_character_image_upload(request:Request,character_id:int,image:UploadFile=File(...),kind:str=Form("inspiration"),caption:str=Form("")):
    if not player_allowed(request): raise HTTPException(401)
    require_player_author(request)
    iid=_invite_id(request); admin_view=is_gm(request)
    cid=_active_campaign_id(request); char=get_player_character(settings,character_id,invite_id=iid,admin=admin_view,campaign_id=cid)
    if not char: raise HTTPException(404,"Character not found")
    if not admin_view and int(char.get("invite_id") or 0)!=int(iid or -1): raise HTTPException(403,"You can only upload art for your own characters.")
    ext=Path(image.filename or "image.jpg").suffix.lower()
    if ext not in {".png",".jpg",".jpeg",".webp",".gif"}: raise HTTPException(400,"Use PNG, JPG, WebP, or GIF images.")
    owner=int(char.get("invite_id") or 0); folder=settings.uploads_dir/"characters"/str(owner)/str(character_id); folder.mkdir(parents=True,exist_ok=True)
    safe_name=re.sub(r"[^A-Za-z0-9._-]+","-",Path(image.filename or "image").stem).strip("-")[:80] or "image"
    filename=f"{int(time.time()*1000)}-{safe_name}{ext}"; path=folder/filename
    await _stream_upload(image,path,15_000_000,"Character images are limited to 15 MB each.")
    rel=path.relative_to(settings.uploads_dir).as_posix()
    try: return add_character_image(settings,character_id,rel,kind,caption,invite_id=iid,admin=admin_view)
    except (PermissionError,ValueError) as exc:
        try:path.unlink()
        except Exception:pass
        raise HTTPException(403 if isinstance(exc,PermissionError) else 400,str(exc))

@app.delete("/api/player/character-images/{image_id}")
def player_character_image_delete(request:Request,image_id:int):
    if not player_allowed(request): raise HTTPException(401)
    require_player_author(request)
    try: rel=delete_character_image(settings,image_id,invite_id=_invite_id(request),admin=is_gm(request))
    except PermissionError as exc: raise HTTPException(403,str(exc))
    if rel:
        try:
            path=(settings.uploads_dir/rel).resolve()
            if settings.uploads_dir.resolve() in path.parents and path.exists(): path.unlink()
        except Exception: pass
    return {"ok":True}


@app.get("/uploads/{asset_path:path}")
def uploaded_asset(request: Request, asset_path: str):
    if not player_allowed(request): raise HTTPException(401)
    decoded=unquote(asset_path)
    path=(settings.uploads_dir / decoded).resolve()
    if settings.uploads_dir.resolve() not in path.parents or not path.exists() or not path.is_file(): raise HTTPException(404)
    # Character inspiration/portraits can be private to one invited player.
    # Do not let a guessed /uploads/characters/<invite>/<character>/... URL
    # bypass the character visibility rules.
    parts=Path(decoded).parts
    if parts and parts[0]=="gm-inbox" and not is_gm(request):
        raise HTTPException(404)
    if len(parts)>=3 and parts[0]=="submissions":
        if not is_gm(request):
            try:owner=int(parts[1])
            except (TypeError,ValueError):raise HTTPException(404)
            if owner!=int(_invite_id(request) or -1):raise HTTPException(404)
    if len(parts)>=4 and parts[0]=="characters":
        try: character_id=int(parts[2])
        except (TypeError,ValueError): raise HTTPException(404)
        char=get_player_character(settings,character_id,invite_id=_invite_id(request),admin=is_gm(request),campaign_id=_active_campaign_id(request))
        if not char: raise HTTPException(404)
        try:
            if int(char.get("invite_id") or 0)!=int(parts[1]): raise HTTPException(404)
        except (TypeError,ValueError): raise HTTPException(404)
    return FileResponse(path)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    if is_co_gm(request): return RedirectResponse("/admin/campaign", status_code=303)
    if not is_admin(request): return RedirectResponse("/admin/login")
    return templates.TemplateResponse("admin.html", {"request": request, "title": "Seeker Studio"}, headers={"Cache-Control": "no-store"})


@app.get("/admin/preview/wiki", response_class=HTMLResponse)
def admin_wiki_preview(request: Request):
    require_admin(request)
    wiki=ensure_built(); pages=wiki.get("pages",[]); page=pages[0] if pages else {"title":"No pages yet","html":"<p>Import or create a LaTeX project.</p>","chapter":None}
    return templates.TemplateResponse("preview.html", {"request":request,"wiki":wiki,"page":page})


@app.get("/preview/pdf")
def preview_pdf(request: Request):
    if not player_allowed(request): raise HTTPException(401)
    path=compiled_pdf_path(settings)
    if path is None: raise HTTPException(404, "No compiled PDF yet")
    return FileResponse(path, media_type="application/pdf", headers={"Cache-Control":"no-store"})


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
    except Exception:
        pass
    try:
        import resource
        child_kb=float(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss or 0)
        if child_kb: out["child_peak_rss_mb"]=round(child_kb/1024,1)
    except Exception:
        pass
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


@app.get("/api/admin/status")
def admin_status(request: Request):
    require_admin(request)
    has_tex=bool(list(settings.project_dir.rglob("*.tex")))
    analysis={}
    error=None
    if has_tex:
        try: analysis=analyze_project(settings)
        except Exception as exc: error=str(exc)
    persistent = (os.getenv("RAILWAY_ENVIRONMENT") is None) or os.path.ismount(str(settings.data_dir)) or (os.getenv("SEEKER_ASSUME_PERSISTENT") or os.getenv("LOREFORGE_ASSUME_PERSISTENT", "")).lower() in {"1","true","yes"}
    return {
        "has_project":has_tex,"analysis":analysis,"error":error,"data_dir":str(settings.data_dir),
        "persistent_storage_detected":bool(persistent),"latex_engine":settings.latex_engine,
        "shell_escape":settings.allow_shell_escape,
        "pdf_ready":compiled_pdf_path(settings) is not None,
        "wiki_ready":(settings.build_dir/"wiki_index.json").exists(),
        "site_title":get_setting(settings,"site_title","") or analysis.get("title","Campaign Atlas"),
        "tagline":get_setting(settings,"tagline","Explore the people, places, histories, and mysteries of the campaign."),
        "main_file":get_setting(settings,"main_file","") or analysis.get("main_file",""),
        "auto_link_codex":get_setting(settings,"auto_link_codex","1").strip().lower() not in {"0","false","no","off"},
        "auto_navigation_art":get_setting(settings,"auto_navigation_art","1").strip().lower() not in {"0","false","no","off"},
        "player_access_mode":player_access_mode(),
        "active_invites":sum(1 for row in list_player_invites(settings) if row.get("active")),
        "storage":storage_report(settings),
        "runtime":_runtime_memory_report(),
    }


@app.post("/api/admin/storage/cleanup")
def admin_storage_cleanup(request: Request):
    require_admin(request)
    return cleanup_legacy_import_artifacts(settings)


@app.get("/api/admin/access")
def admin_access(request: Request):
    require_admin(request)
    return {
        "mode": player_access_mode(),
        "legacy_password_configured": bool(settings.player_password),
        "invitations": list_player_invites(settings),
    }


@app.put("/api/admin/access")
def admin_access_update(request: Request, payload: dict = Body(...)):
    require_admin(request)
    mode = str(payload.get("mode") or "invite").strip().lower()
    if mode not in {"invite", "password", "public"}:
        raise HTTPException(400, "Access mode must be invite, password, or public.")
    if mode == "password" and not settings.player_password:
        raise HTTPException(400, "Set PLAYER_PASSWORD in Railway before enabling shared-password mode.")
    set_setting(settings, "player_access_mode", mode)
    return {"ok": True, "mode": mode}


@app.post("/api/admin/invitations")
def admin_invitation_create(request: Request, payload: dict = Body(...)):
    require_admin(request)
    expires_at = payload.get("expires_at")
    if expires_at in ("", None):
        expires_at = None
    try:
        invite = create_player_invite(
            settings, str(payload.get("label") or ""), expires_at, payload.get("max_devices"), str(payload.get("role") or "player")
        )
        # Creating a personal invitation is an explicit choice to use the private
        # invitation gate. Keep the backend authoritative instead of relying on
        # the browser to make a second request.
        set_setting(settings, "player_access_mode", "invite")
        return invite
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/admin/invitations/{invite_id}/revoke")
def admin_invitation_revoke(request: Request, invite_id: int):
    require_admin(request)
    try:
        return revoke_player_invite(settings, invite_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/admin/invitations/{invite_id}/restore")
def admin_invitation_restore(request: Request, invite_id: int):
    require_admin(request)
    try:
        return restore_player_invite(settings, invite_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/admin/invitations/{invite_id}/rotate")
def admin_invitation_rotate(request: Request, invite_id: int):
    require_admin(request)
    try:
        return rotate_player_invite(settings, invite_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/admin/invitations/{invite_id}/reset-devices")
def admin_invitation_reset_devices(request: Request, invite_id: int):
    require_admin(request)
    try:
        return reset_player_invite_devices(settings, invite_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.delete("/api/admin/invitations/{invite_id}")
def admin_invitation_delete(request: Request, invite_id: int):
    require_admin(request)
    try:
        delete_player_invite(settings, invite_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True}


@app.get("/api/admin/files")
def admin_files(request: Request): require_admin(request); return list_project_files(settings)


@app.get("/api/admin/wiki-pages")
def admin_wiki_pages(request: Request):
    require_admin(request)
    return [{"slug": p["slug"], "title": p["title"], "chapter": p.get("chapter")} for p in ensure_built().get("pages", [])]


@app.get("/api/admin/file")
def admin_file(request: Request, path: str):
    require_admin(request); p=safe_project_path(settings,path)
    if not p.exists() or not p.is_file(): raise HTTPException(404)
    if p.stat().st_size > 2_000_000: raise HTTPException(413,"File too large for text editor")
    return {"path":path,"content":p.read_text(encoding="utf-8",errors="replace")}


@app.put("/api/admin/file")
def admin_save_file(request: Request, payload: dict = Body(...)):
    require_admin(request); path=str(payload.get("path") or ""); content=str(payload.get("content") or "")
    if not path: raise HTTPException(400,"Missing path")
    result=save_text_file(settings,path,content)
    if path.lower().endswith(".tex"):
        try: build_wiki(settings)
        except Exception as exc: result["wiki_warning"]=str(exc)
    return result


@app.post("/api/admin/file/new")
def admin_new_file(request: Request, payload: dict = Body(...)):
    require_admin(request); path=str(payload.get("path") or "").strip()
    if not path: raise HTTPException(400,"Missing path")
    p=safe_project_path(settings,path)
    if p.exists(): raise HTTPException(409,"File already exists")
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(str(payload.get("content") or ""),encoding="utf-8")
    return {"ok":True,"path":path}


@app.delete("/api/admin/file")
def admin_delete_file(request: Request, path: str):
    require_admin(request); p=safe_project_path(settings,path)
    if not p.exists(): raise HTTPException(404)
    if p.is_dir(): shutil.rmtree(p)
    else: p.unlink()
    return {"ok":True}


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


@app.post("/api/admin/source-fix")
def admin_source_fix(request: Request, payload: dict = Body(...)):
    """Apply one revision-safe Build Doctor repair."""
    require_admin(request)
    return _apply_verified_source_fixes([payload])


@app.post("/api/admin/source-fixes")
def admin_source_fixes(request: Request, payload: dict = Body(...)):
    """Apply all explicitly approved high-confidence Build Doctor repairs once."""
    require_admin(request)
    fixes = payload.get("fixes")
    if not isinstance(fixes, list):
        raise HTTPException(400, "Expected a fixes array.")
    return _apply_verified_source_fixes([x for x in fixes if isinstance(x, dict)])


@app.post("/api/admin/compile")
def admin_compile(request: Request, clean: bool = False):
    require_admin(request)
    if not BUILD_LOCK.acquire(blocking=False):
        raise HTTPException(409, "A Seeker build is already running. Wait for it to finish instead of starting another resource-heavy TeX process.")
    try:
        wiki=build_wiki(settings); result=compile_pdf(settings, clean=clean)
        return {"wiki_pages":len(wiki.get("pages",[])), **result.__dict__}
    except Exception as exc:
        raise HTTPException(400,str(exc))
    finally:
        BUILD_LOCK.release()


@app.post("/api/admin/rebuild-wiki")
def admin_rebuild(request: Request):
    require_admin(request)
    if not BUILD_LOCK.acquire(blocking=False):
        raise HTTPException(409, "A Seeker build is already running.")
    try:
        wiki=build_wiki(settings); return {"ok":True,"pages":len(wiki.get("pages",[])),"analysis":wiki.get("analysis",{})}
    except Exception as exc: raise HTTPException(400,str(exc))
    finally: BUILD_LOCK.release()


@app.post("/api/admin/import")
async def admin_import(request: Request, archive: UploadFile = File(...)):
    require_admin(request)
    if not archive.filename or not archive.filename.lower().endswith(".zip"): raise HTTPException(400,"Upload an Overleaf/project .zip archive")
    # Keep the uploaded archive off the persistent /data volume. Railway Free/Trial
    # volumes are small, while the service temp filesystem is intended for scratch I/O.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="seeker-upload-", suffix=".zip", delete=False) as f:
            tmp_path = Path(f.name)
            uploaded = 0
            while chunk := await archive.read(1024 * 1024):
                uploaded += len(chunk)
                if uploaded > 1_000_000_000:
                    raise HTTPException(413, "Project ZIP is larger than the 1 GB upload safety limit.")
                f.write(chunk)
        if not BUILD_LOCK.acquire(blocking=False):
            raise HTTPException(409,"A Seeker build is already running. Wait for it to finish before importing a project.")
        try:
            import_info = replace_project_from_zip(settings, tmp_path)
            set_setting(settings,"main_file","")
            analysis=analyze_project(settings); wiki=build_wiki(settings); result=compile_pdf(settings)
            return {"ok":True,"analysis":analysis,"wiki_pages":len(wiki.get("pages",[])),"compile":result.__dict__,"import":import_info}
        finally:
            BUILD_LOCK.release()
    except HTTPException:
        raise
    except OSError as exc:
        if getattr(exc, "errno", None) == 28:
            raise HTTPException(507, "Persistent storage is full. Seeker stages imports outside /data, but your volume itself needs more room. Increase the Railway volume or use Storage cleanup in Project settings.")
        raise HTTPException(400,str(exc))
    except Exception as exc:
        raise HTTPException(400,str(exc))
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


@app.get("/api/admin/export")
def admin_export(request: Request):
    require_admin(request); out=settings.build_dir / "campaign-project.zip"; export_project_zip(settings,out)
    return FileResponse(out,filename="campaign-project.zip",media_type="application/zip")


@app.get("/api/admin/revisions")
def admin_revisions(request: Request, path: str): require_admin(request); return list_revisions(settings,path)


@app.post("/api/admin/revisions/restore")
def admin_restore(request: Request, payload: dict = Body(...)):
    require_admin(request); restore_revision(settings,str(payload.get("path") or ""),str(payload.get("revision_id") or "")); build_wiki(settings); return {"ok":True}


@app.put("/api/admin/settings")
def admin_settings(request: Request, payload: dict = Body(...)):
    require_admin(request)
    for key in ("site_title","tagline","main_file"):
        if key in payload: set_setting(settings,key,str(payload[key]))
    if "auto_link_codex" in payload:
        set_setting(settings,"auto_link_codex","1" if payload.get("auto_link_codex") else "0")
    if "auto_navigation_art" in payload:
        set_setting(settings,"auto_navigation_art","1" if payload.get("auto_navigation_art") else "0")
    if payload.get("main_file"): choose_main(settings)
    try: build_wiki(settings)
    except Exception: pass
    return {"ok":True}


@app.get("/api/admin/codex")
def admin_codex(request: Request):
    require_admin(request)
    wiki = ensure_built()
    return {"categories": wiki.get("categories", []), "pages": wiki.get("pages", [])}


@app.put("/api/admin/codex/presentation")
def admin_codex_presentation(request: Request, payload: dict = Body(...)):
    require_admin(request)
    target_type = str(payload.get("target_type") or "")
    target_key = str(payload.get("target_key") or "")
    data = save_codex_presentation(settings, target_type, target_key, payload.get("presentation") or {})
    wiki = build_wiki(settings)
    return {"ok": True, "presentation": data, "wiki_pages": len(wiki.get("pages", []))}


@app.get("/api/admin/assets")
def admin_assets(request: Request):
    require_admin(request)
    return _asset_rows()


@app.post("/api/admin/assets/upload")
async def admin_asset_upload(request: Request, image: UploadFile = File(...), destination: str = Form("uploads")):
    require_admin(request)
    suffix = Path(image.filename or "image.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
        raise HTTPException(400, "Artwork must be PNG, JPG, WebP, GIF, or SVG.")
    destination = destination.lower()
    if destination == "project":
        folder = settings.project_dir / "Images" / "Seeker"
        ref_prefix = "project:"
        url_prefix = "/project-asset/Images/Seeker/"
        ref_path_prefix = "Images/Seeker/"
    else:
        folder = settings.uploads_dir / "codex"
        ref_prefix = "upload:"
        url_prefix = "/uploads/codex/"
        ref_path_prefix = "codex/"
    folder.mkdir(parents=True, exist_ok=True)
    stem = "".join(c for c in Path(image.filename or "art").stem if c.isalnum() or c in "-_ ").strip().replace(" ", "-")[:70] or "art"
    filename = f"{int(time.time())}-{secrets.token_hex(3)}-{stem}{suffix}"
    target = folder / filename
    size = 0
    with target.open("wb") as fh:
        while chunk := await image.read(1024 * 1024):
            size += len(chunk)
            if size > 40 * 1024 * 1024:
                target.unlink(missing_ok=True)
                raise HTTPException(413, "Artwork is larger than the 40 MB limit.")
            fh.write(chunk)
    rel = ref_path_prefix + filename
    return {"ref": ref_prefix + rel, "url": url_prefix + quote(filename), "path": rel, "source": "project" if destination == "project" else "upload", "name": filename}


@app.get("/api/admin/maps")
def admin_maps(request: Request):
    require_admin(request)
    rows=list_maps(settings,public=False)
    for m in rows:
        m["layers"]=map_layers(settings,int(m["id"]),public=False)
        m["fog_regions"]=fog_regions(settings,int(m["id"]),public=False)
    return rows


@app.post("/api/admin/maps")
async def admin_create_map(request: Request, name: str = Form(...), description: str = Form(""), image: UploadFile = File(...)):
    require_admin(request)
    suffix=Path(image.filename or "map.png").suffix.lower()
    if suffix not in {".png",".jpg",".jpeg",".webp"}: raise HTTPException(400,"Map must be PNG, JPG, or WebP")
    map_dir=settings.uploads_dir/"maps"; map_dir.mkdir(parents=True,exist_ok=True)
    filename=f"{int(time.time())}-{secrets.token_hex(4)}{suffix}"; target=map_dir/filename
    await _stream_upload(image,target,100*1024*1024,"Map image is larger than the 100 MB safety limit.")
    return create_map(settings,name,f"maps/{filename}",description)


@app.put("/api/admin/maps/{map_id}")
def admin_update_map(request: Request,map_id:int,payload:dict=Body(...)): require_admin(request); return update_map(settings,map_id,payload)


@app.delete("/api/admin/maps/{map_id}")
def admin_delete_map(request: Request,map_id:int): require_admin(request); delete_map(settings,map_id); return {"ok":True}


@app.post("/api/admin/maps/{map_id}/markers")
def admin_create_marker(request: Request,map_id:int,payload:dict=Body(...)): require_admin(request); return create_marker(settings,map_id,payload)


@app.put("/api/admin/markers/{marker_id}")
def admin_update_marker(request: Request,marker_id:int,payload:dict=Body(...)): require_admin(request); return update_marker(settings,marker_id,payload)


@app.delete("/api/admin/markers/{marker_id}")
def admin_delete_marker(request: Request,marker_id:int): require_admin(request); delete_marker(settings,marker_id); return {"ok":True}

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
@app.get("/api/admin/campaign/overview")
def admin_campaign_overview(request: Request):
    require_gm(request)
    wiki=ensure_built(); maps=list_maps(settings,public=False); cid=_active_campaign_id(request)
    for m in maps:
        m["layers"] = map_layers(settings, int(m["id"]), public=False)
        m["fog_regions"] = fog_regions(settings, int(m["id"]), public=False)
    return {
        "maps":maps,
        "sessions":list_sessions(settings,campaign_id=cid),"timeline":list_timeline(settings,admin=True),"timeline_eras":list_timeline_eras(settings,admin=True),
        "relationships":list_relationships(settings,admin=True),"reveals":list_reveal_blocks_from_wiki(wiki),
        "mysteries":list_mysteries(settings,admin=True,campaign_id=cid),"handouts":list_handouts(settings,admin=True,campaign_id=cid),
        "snapshots":list_snapshots(settings),"health":campaign_health(settings,wiki,maps),
        "reveal_states":list_reveal_states(settings,campaign_id=cid),"recent_updates":recent_updates(settings,None,12,admin=True,campaign_id=cid),
        "calendar":_calendar_config(),
        "aliases":aliases(settings),"invitations":list_player_invites(settings),"campaigns":[{**c,"member_ids":[int(m["id"]) for m in campaign_members(settings,int(c["id"])) if m.get("campaign_member")]} for c in list_campaigns(settings,admin=True,include_archived=True)],"active_campaign":get_campaign(settings,cid),
        "variants":[v for p in wiki.get("pages",[]) for v in list_variants(settings,p.get("slug",""),admin=True)],
        "entity_styles":{p.get("slug",""):entity_style(settings,p.get("slug","")) for p in wiki.get("pages",[])},
        "assets":_asset_rows(),"media_assets":_media_asset_rows(),
        "player_characters":list_player_characters(settings,admin=True,campaign_id=cid),
    }


@app.post("/api/admin/sessions")
def admin_save_session(request: Request,payload:dict=Body(...)):
    require_gm(request)
    before=None
    if payload.get("id"):
        before=next((x for x in list_sessions(settings,campaign_id=_active_campaign_id(request)) if int(x.get("id"))==int(payload["id"])),None)
    row=save_session(settings,_campaign_payload(request,payload))
    # Lightweight knowledge/state checkpoints answer “what did the party know before/after this session?”
    # without duplicating the multi-hundred-megabyte campaign archive.
    if row.get("status")=="live" and (not before or before.get("status")!="live"):
        capture_session_state(settings,int(row["id"]),"before")
    if row.get("status")=="ended" and (not before or before.get("status")!="ended"):
        capture_session_state(settings,int(row["id"]),"after")
    if row.get("status")=="planned" and (not before or before.get("status")!="planned" or before.get("session_date")!=row.get("session_date") or before.get("title")!=row.get("title")):
        create_notification(settings,{"campaign_id":int(row["campaign_id"]),"title":"Session planned · "+str(row.get("title") or "Next session"),"body":str(row.get("session_date") or "A date has been proposed."),"target_type":"session","target_key":str(row["id"]),"kind":"session","audience":[]})
    # V6.1: a confirmed/changed date can announce itself in the campaign's
    # Discord channel. The webhook is deliberately best-effort: a Discord
    # outage must never prevent Seeker from saving the session.
    date_now=str(row.get("session_date") or "").strip()
    date_before=str((before or {}).get("session_date") or "").strip()
    if date_now and date_now != date_before and row.get("status") in {"planned","live"}:
        try:
            row["discord_announcement"]=discord_session_confirmation(settings,int(row["campaign_id"]),row,base_url=_external_base_url(request))
        except Exception as exc:
            row["discord_announcement"]={"ok":False,"error":str(exc)[:300]}
    return row


@app.delete("/api/admin/sessions/{session_id}")
def admin_delete_session(request:Request,session_id:int):
    require_gm(request);delete_session(settings,session_id);return {"ok":True}


@app.post("/api/admin/sessions/{session_id}/lore")
def admin_session_lore(request:Request,session_id:int,payload:dict=Body(...)):
    require_gm(request);set_session_lore(settings,session_id,str(payload.get("page_slug") or ""),str(payload.get("role") or "reference"),bool(payload.get("enabled",True)));return {"ok":True}


@app.post("/api/admin/session-updates")
def admin_session_update(request:Request,payload:dict=Body(...)):
    require_gm(request);p=_campaign_payload(request,payload);row=add_session_update(settings,p)
    if str(row.get("visibility") or "players")!="gm" and str(row.get("target_type") or "") in {"page","lore"}:
        _notify_page_followers(_active_campaign_id(request),str(row.get("target_key") or ""),str(row.get("title") or "Followed lore changed"),str(row.get("body") or "A followed entry was updated."))
    return row


@app.post("/api/admin/timeline")
def admin_timeline_save(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_timeline_event(settings,payload)


@app.delete("/api/admin/timeline/{event_id}")
def admin_timeline_delete(request:Request,event_id:int):
    require_gm(request)
    from .storage import connect
    with connect(settings) as conn: conn.execute("DELETE FROM timeline_events WHERE id=?",(event_id,))
    return {"ok":True}


@app.post("/api/admin/timeline-eras")
def admin_timeline_era_save(request:Request,payload:dict=Body(...)):
    require_gm(request); return save_timeline_era(settings,payload)

@app.delete("/api/admin/timeline-eras/{era_id}")
def admin_timeline_era_delete(request:Request,era_id:int):
    require_gm(request); delete_timeline_era(settings,era_id); return {"ok":True}


@app.post("/api/admin/relationships")
def admin_relationship_save(request:Request,payload:dict=Body(...)):
    require_gm(request);row=save_relationship(settings,payload);cid=_active_campaign_id(request)
    for slug in {str(row.get("source_slug") or ""),str(row.get("target_slug") or "")}:
        if slug:_notify_page_followers(cid,slug,"A connection changed","A relationship involving this followed entry was updated.")
    return row


@app.delete("/api/admin/relationships/{relationship_id}")
def admin_relationship_delete(request:Request,relationship_id:int):
    require_gm(request)
    from .storage import connect
    with connect(settings) as conn: conn.execute("DELETE FROM lore_relationships WHERE id=?",(relationship_id,))
    return {"ok":True}


@app.post("/api/admin/reveals")
def admin_reveal_save(request:Request,payload:dict=Body(...)):
    require_gm(request);payload=_campaign_payload(request,payload);row=set_reveal(settings,payload)
    if row.get("state") in {"rumor","discovered","public"}:
        title=str(payload.get("title") or payload.get("target_key") or "Lore discovered")
        add_session_update(settings,{"campaign_id":_active_campaign_id(request),"session_id":payload.get("session_id"),"title":title,"body":str(payload.get("update_body") or "New lore has been revealed."),"target_type":payload.get("target_type") or "lore","target_key":payload.get("target_key") or "","visibility":"players","audience":payload.get("audience") or []})
        _notify_page_followers(_active_campaign_id(request),str(payload.get("target_key") or ""),title,str(payload.get("update_body") or "New information about a followed entry has been revealed."))
    return row


@app.post("/api/admin/variants")
def admin_variant_save(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_variant(settings,payload)


@app.delete("/api/admin/variants/{variant_id}")
def admin_variant_delete(request:Request,variant_id:int):
    require_gm(request);delete_variant(settings,variant_id);return {"ok":True}


@app.post("/api/admin/aliases")
def admin_alias_save(request:Request,payload:dict=Body(...)):
    require_gm(request);save_alias(settings,str(payload.get("alias") or ""),str(payload.get("page_slug") or ""));return {"ok":True}


@app.put("/api/admin/entity-style/{slug}")
def admin_entity_style_save(request:Request,slug:str,payload:dict=Body(...)):
    require_gm(request);return save_entity_style(settings,slug,payload)


@app.post("/api/admin/mysteries")
def admin_mystery_save(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_mystery(settings,_campaign_payload(request,payload))


@app.post("/api/admin/mysteries/{mystery_id}/pins")
def admin_mystery_pin(request:Request,mystery_id:int,payload:dict=Body(...)):
    require_gm(request);return add_mystery_pin(settings,mystery_id,payload)


@app.post("/api/admin/mysteries/{mystery_id}/edges")
def admin_mystery_edge(request:Request,mystery_id:int,payload:dict=Body(...)):
    require_gm(request)
    try: return save_mystery_edge(settings,mystery_id,payload)
    except ValueError as e: raise HTTPException(status_code=400,detail=str(e))


@app.delete("/api/admin/mystery-edges/{edge_id}")
def admin_mystery_edge_delete(request:Request,edge_id:int):
    require_gm(request);delete_mystery_edge(settings,edge_id);return {"ok":True}


@app.delete("/api/admin/mystery-pins/{pin_id}")
def admin_mystery_pin_delete(request:Request,pin_id:int):
    require_gm(request);delete_mystery_pin(settings,pin_id);return {"ok":True}


@app.delete("/api/admin/mysteries/{mystery_id}")
def admin_mystery_delete(request:Request,mystery_id:int):
    require_gm(request)
    from .storage import connect
    with connect(settings) as conn:conn.execute("DELETE FROM mysteries WHERE id=?",(mystery_id,))
    return {"ok":True}


@app.post("/api/admin/handouts")
def admin_handout_save(request:Request,payload:dict=Body(...)):
    require_gm(request);row=save_handout(settings,_campaign_payload(request,payload))
    if str(row.get("visibility") or "players")!="gm":
        create_notification(settings,{"campaign_id":_active_campaign_id(request),"title":"New handout · "+str(row.get("title") or "Handout"),"body":"A new letter, relic, or handout is available.","target_type":"handout","target_key":str(row.get("id") or ""),"kind":"handout","audience":[]})
    return row


@app.delete("/api/admin/handouts/{handout_id}")
def admin_handout_delete(request:Request,handout_id:int):
    require_gm(request)
    from .storage import connect
    with connect(settings) as conn:conn.execute("DELETE FROM handouts WHERE id=?",(handout_id,))
    return {"ok":True}


@app.post("/api/admin/maps/{map_id}/layers")
def admin_map_layer_save(request:Request,map_id:int,payload:dict=Body(...)):
    require_gm(request);return save_map_layer(settings,map_id,payload)


@app.delete("/api/admin/map-layers/{layer_id}")
def admin_map_layer_delete(request:Request,layer_id:int):
    require_gm(request)
    from .storage import connect
    with connect(settings) as conn:conn.execute("DELETE FROM map_layers WHERE id=?",(layer_id,))
    return {"ok":True}


@app.post("/api/admin/maps/{map_id}/fog")
def admin_map_fog_save(request:Request,map_id:int,payload:dict=Body(...)):
    require_gm(request);return save_fog_region(settings,map_id,payload)


@app.delete("/api/admin/map-fog/{fog_id}")
def admin_map_fog_delete(request:Request,fog_id:int):
    require_gm(request)
    from .storage import connect
    with connect(settings) as conn:conn.execute("DELETE FROM map_fog_regions WHERE id=?",(fog_id,))
    return {"ok":True}


@app.post("/api/admin/snapshots")
def admin_snapshot_create(request:Request,payload:dict=Body(...)):
    require_gm(request);return create_snapshot(settings,str(payload.get("label") or "Campaign snapshot"))


@app.get("/api/admin/snapshots/{snapshot_id}/download")
def admin_snapshot_download(request:Request,snapshot_id:int):
    require_gm(request);row=next((x for x in list_snapshots(settings) if int(x["id"])==int(snapshot_id)),None)
    if not row or not Path(row["path"]).exists():raise HTTPException(404)
    return FileResponse(row["path"],filename=Path(row["path"]).name,media_type="application/zip")


@app.post("/api/admin/snapshots/{snapshot_id}/restore")
def admin_snapshot_restore(request:Request,snapshot_id:int):
    require_admin(request);row=next((x for x in list_snapshots(settings) if int(x["id"])==int(snapshot_id)),None)
    if not row or not Path(row["path"]).exists(): raise HTTPException(404,"Snapshot not found")
    # Safety net: keep the current state as a new downloadable checkpoint first.
    backup=create_snapshot(settings,f"Automatic backup before restoring {row['label']}")
    result=restore_snapshot(settings,row["path"]);init_db(settings);init_feature_db(settings);init_schedule_db(settings);build_wiki(settings)
    result["backup"]=backup;return result


@app.get("/api/admin/health-report")
def admin_health_report(request:Request):
    require_gm(request);return campaign_health(settings,ensure_built(),list_maps(settings,public=False))


@app.put("/api/admin/world-settings")
def admin_world_settings(request:Request,payload:dict=Body(...)):
    require_gm(request)
    for key in ("calendar_name","campaign_date","campaign_season","world_width","travel_speed"):
        if key in payload:set_setting(settings,key,str(payload[key]))
    for key in ("calendar_months","calendar_weekdays","calendar_moons","calendar_festivals"):
        if key in payload:set_setting(settings,key+"_json",json.dumps(payload.get(key) or []))
    return {"ok":True,"calendar":_calendar_config()}


@app.get("/api/admin/revisions/diff")
def admin_revision_diff(request:Request,path:str,revision_id:str):
    require_gm(request)
    import difflib
    current=safe_project_path(settings,path).read_text(encoding="utf-8",errors="replace").splitlines()
    rev_dir=settings.history_dir/Path(path)
    candidate=next((x for x in rev_dir.glob("*.txt") if x.stem==revision_id),None)
    if not candidate: raise HTTPException(404,"Revision not found")
    old=candidate.read_text(encoding="utf-8",errors="replace").splitlines()
    diff=list(difflib.unified_diff(old,current,fromfile=f"{path}@{revision_id}",tofile=path,lineterm=""))
    return {"path":path,"revision_id":revision_id,"diff":"\n".join(diff[:5000])}


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


@app.post("/api/admin/entry-template")
def admin_entry_template(request:Request,payload:dict=Body(...)):
    require_gm(request)
    kind=str(payload.get("kind") or "person").lower(); title=str(payload.get("title") or "New Entry").strip()
    return {"kind":kind,"title":title,"content":_entry_template_content(kind,title)}


@app.post("/api/admin/entry-template/create")
def admin_entry_template_create(request:Request,payload:dict=Body(...)):
    """Create a structured lore file and wire it into the canonical main TeX.

    This turns World Builder into a real authoring surface rather than a template
    clipboard.  The operation is explicit, revision-backed for main.tex, and the
    generated file remains ordinary LaTeX that can be exported back to Overleaf.
    """
    require_gm(request)
    kind=str(payload.get("kind") or "person").lower(); title=str(payload.get("title") or "New Entry").strip()
    if not title: raise HTTPException(400,"Give the new lore entry a title.")
    folder_map={"person":"People","settlement":"Places","faction":"Factions","deity":"Deities","event":"History","creature":"Creatures","handout":"Handouts"}
    folder=folder_map.get(kind,"Lore")
    stem=re.sub(r"[^A-Za-z0-9_-]+","_",title).strip("_")[:90] or "New_Entry"
    rel=Path("Worldbuilding")/folder/f"{stem}.tex"
    candidate=rel; n=2
    while safe_project_path(settings,candidate.as_posix()).exists():
        candidate=rel.with_name(f"{rel.stem}_{n}.tex"); n+=1
    target=safe_project_path(settings,candidate.as_posix()); target.parent.mkdir(parents=True,exist_ok=True)
    content=_entry_template_content(kind,title); target.write_text(content,encoding="utf-8")
    main_rel=choose_main(settings); main_path=safe_project_path(settings,main_rel)
    main_text=main_path.read_text(encoding="utf-8",errors="replace")
    include_ref=candidate.with_suffix("").as_posix()
    include_line=f"\\include{{{include_ref}}}"
    if include_line not in main_text:
        if "\\end{document}" in main_text:
            changed=main_text.replace("\\end{document}",include_line+"\n\\end{document}",1)
        else:
            changed=main_text.rstrip()+"\n"+include_line+"\n"
        save_text_file(settings,main_rel,changed)
    try: build_wiki(settings)
    except Exception: pass
    return {"ok":True,"kind":kind,"title":title,"path":candidate.as_posix(),"main_file":main_rel,"content":content,"edit_url":"/admin?file="+quote(candidate.as_posix())+"&line=1"}


@app.post("/api/admin/maps/{map_id}/layers/upload")
async def admin_map_layer_upload(request:Request,map_id:int,name:str=Form("Map layer"),kind:str=Form("overlay"),opacity:float=Form(.7),visible_to_players:bool=Form(True),image:UploadFile=File(...)):
    require_gm(request)
    suffix=Path(image.filename or "layer.png").suffix.lower()
    if suffix not in {".png",".jpg",".jpeg",".webp"}: raise HTTPException(400,"Layer must be PNG, JPG, JPEG, or WebP")
    folder=settings.uploads_dir/"maps"/"layers";folder.mkdir(parents=True,exist_ok=True)
    filename=f"{int(time.time())}-{secrets.token_hex(4)}{suffix}";target=folder/filename
    await _stream_upload(image,target,80*1024*1024,"Map layer is larger than 80 MB")
    return save_map_layer(settings,map_id,{"name":name,"kind":kind,"opacity":opacity,"visible_to_players":visible_to_players,"image_path":f"maps/layers/{filename}"})

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


@app.get("/campaign", response_class=HTMLResponse)
def living_campaign_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    iid=_invite_id(request); gm=is_gm(request); cid=_active_campaign_id(request); wiki=_visible_wiki(request); maps=list_maps(settings,public=not gm)
    chars=list_player_characters(settings,invite_id=iid,admin=gm,campaign_id=cid)
    for c in chars:
        owner=gm or int(c.get("invite_id") or -1)==int(iid or -2)
        c["arcs"]=character_arcs(settings,int(c["id"]),owner=owner)
        c["relationships"]=character_relationships(settings,int(c["id"]),owner=owner)
    can_author = gm or (not archive_mode() and bool(current_player_invite(request)) and player_role(request) == "player")
    return templates.TemplateResponse("living.html",{
        "request":request,"wiki":wiki,"maps":maps,"gm_view":gm,"player":current_player_invite(request),
        "threads":list_threads(settings,admin=gm,invite_id=iid,campaign_id=cid),"fronts":list_fronts(settings,admin=gm,invite_id=iid,campaign_id=cid),
        "rumors":list_rumors(settings,admin=gm,campaign_id=cid),"journals":([] if iid is None else list_journals(settings,iid,admin=gm,campaign_id=cid)),
        "characters":chars,"notifications":list_notifications(settings,iid,admin=gm,campaign_id=cid),"runtime_states":runtime_states(settings,admin=gm),
        "submissions":list_submissions(settings,invite_id=iid,admin=gm,campaign_id=cid),"calendar":_calendar_config(),"can_author":can_author,"archive_mode":archive_mode(),
        "journal_characters":[c for c in chars if iid is not None and int(c.get("invite_id") or -1)==int(iid)],
        "journal_sessions":list_sessions(settings,public=not gm,invite_id=iid,campaign_id=cid),
    })


@app.get("/campaign/threads", response_class=HTMLResponse)
def living_threads_alias(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    return RedirectResponse("/campaign#threads",status_code=302)


@app.get("/admin/living", response_class=HTMLResponse)
def living_admin_page(request: Request):
    require_gm(request)
    wiki=ensure_built();maps=list_maps(settings,public=False)
    return templates.TemplateResponse("living_admin.html",{"request":request,"wiki":wiki,"maps":maps,"owner":is_admin(request)})


@app.get("/api/living/overview")
def living_overview(request: Request):
    if not player_allowed(request): raise HTTPException(401)
    iid=_invite_id(request);gm=is_gm(request);cid=_active_campaign_id(request)
    chars=list_player_characters(settings,invite_id=iid,admin=gm,campaign_id=cid)
    for c in chars:
        owner=gm or int(c.get("invite_id") or -1)==int(iid or -2);c["arcs"]=character_arcs(settings,int(c["id"]),owner=owner);c["relationships"]=character_relationships(settings,int(c["id"]),owner=owner)
    return {"threads":list_threads(settings,admin=gm,invite_id=iid,campaign_id=cid),"fronts":list_fronts(settings,admin=gm,invite_id=iid,campaign_id=cid),"rumors":list_rumors(settings,admin=gm,campaign_id=cid),"journals":([] if iid is None else list_journals(settings,iid,admin=gm,campaign_id=cid)),"characters":chars,"notifications":list_notifications(settings,iid,admin=gm,campaign_id=cid),"runtime_states":runtime_states(settings,admin=gm),"submissions":list_submissions(settings,invite_id=iid,admin=gm,campaign_id=cid),"active_campaign":get_campaign(settings,cid)}


@app.get("/api/admin/living/overview")
def living_admin_overview(request: Request):
    require_gm(request);wiki=ensure_built();maps=list_maps(settings,public=False);cid=_active_campaign_id(request)
    region_rows=[]
    for m in maps: region_rows.extend([{**r,"map_name":m.get("name"),"map_slug":m.get("slug")} for r in map_regions(settings,int(m["id"]),admin=True)])
    return {
        "pages":[{"slug":p.get("slug"),"title":p.get("title"),"chapter":p.get("chapter")} for p in wiki.get("pages",[])],"maps":maps,
        "invitations":list_player_invites(settings),"knowledge":list_knowledge(settings,campaign_id=cid),"fronts":list_fronts(settings,admin=True,campaign_id=cid),"runtime_states":runtime_states(settings,admin=True),
        "relationship_history":relationship_history(settings,admin=True),"hierarchies":hierarchies(settings,admin=True),"regions":region_rows,"rumors":list_rumors(settings,admin=True,campaign_id=cid),
        "threads":list_threads(settings,admin=True,campaign_id=cid),"inbox":inbox_items(settings),"submissions":list_submissions(settings,admin=True,campaign_id=cid),"publishing":publishing_states(settings),
        "session_snapshots":session_state_snapshots(settings),"suggestions":scan_suggestions(settings,wiki),"media_meta":list_media_catalog(settings),"assets":_asset_rows(),"media_assets":_media_asset_rows(),
        "notifications":list_notifications(settings,None,admin=True,campaign_id=cid),"characters":list_player_characters(settings,admin=True,campaign_id=cid),"continuity":continuity_report(settings,wiki),
        "ai_configured":bool((os.getenv("SEEKER_AI_API_KEY") or os.getenv("LOREFORGE_AI_API_KEY")) and (os.getenv("SEEKER_AI_MODEL") or os.getenv("LOREFORGE_AI_MODEL"))),"archive_mode":get_setting(settings,"campaign_archive_mode","0") in {"1","true","yes"},
    }


@app.post("/api/admin/knowledge")
def admin_set_knowledge(request:Request,payload:dict=Body(...)):
    require_gm(request);return set_knowledge(settings,int(payload.get("invite_id")),str(payload.get("target_type") or "page"),str(payload.get("target_key") or ""),str(payload.get("state") or "known"),str(payload.get("note") or ""),"gm",campaign_id=_active_campaign_id(request))


@app.post("/api/admin/fronts")
def admin_save_front(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_front(settings,_campaign_payload(request,payload))
@app.post("/api/admin/fronts/{front_id}/advance")
def admin_advance_front(request:Request,front_id:int,payload:dict=Body(...)):
    require_gm(request);return advance_front(settings,front_id,int(payload.get("delta") or 1),str(payload.get("label") or "Front advanced"),str(payload.get("body") or ""),payload.get("session_id"),bool(payload.get("visible_to_players",False)))
@app.delete("/api/admin/fronts/{front_id}")
def admin_delete_front(request:Request,front_id:int):
    require_gm(request)
    with connect(settings) as conn:conn.execute("DELETE FROM campaign_fronts WHERE id=?",(front_id,))
    return {"ok":True}


@app.put("/api/admin/runtime-state/{slug}")
def admin_runtime_state(request:Request,slug:str,payload:dict=Body(...)):
    require_gm(request);return save_runtime_state(settings,slug,payload)


@app.post("/api/admin/relationship-history")
def admin_relationship_history(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_relationship_history(settings,payload)
@app.delete("/api/admin/relationship-history/{rid}")
def admin_relationship_history_delete(request:Request,rid:int):
    require_gm(request)
    with connect(settings) as conn:conn.execute("DELETE FROM relationship_history WHERE id=?",(rid,))
    return {"ok":True}


@app.post("/api/admin/hierarchies")
def admin_hierarchy_save(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_hierarchy_edge(settings,payload)
@app.delete("/api/admin/hierarchies/{rid}")
def admin_hierarchy_delete(request:Request,rid:int):
    require_gm(request)
    with connect(settings) as conn:conn.execute("DELETE FROM entity_hierarchy WHERE id=?",(rid,))
    return {"ok":True}


@app.post("/api/admin/maps/{map_id}/regions")
def admin_map_region_save(request:Request,map_id:int,payload:dict=Body(...)):
    require_gm(request);return save_map_region(settings,map_id,payload)
@app.post("/api/admin/map-regions/{region_id}/history")
def admin_map_region_history(request:Request,region_id:int,payload:dict=Body(...)):
    require_gm(request);return save_region_history(settings,region_id,payload)
@app.delete("/api/admin/map-region-history/{history_id}")
def admin_map_region_history_delete(request:Request,history_id:int):
    require_gm(request)
    with connect(settings) as conn: conn.execute("DELETE FROM map_region_history WHERE id=?",(history_id,))
    return {"ok":True}
@app.delete("/api/admin/map-regions/{rid}")
def admin_map_region_delete(request:Request,rid:int):
    require_gm(request)
    with connect(settings) as conn:conn.execute("DELETE FROM map_regions WHERE id=?",(rid,))
    return {"ok":True}
@app.get("/api/public/map/{slug}/regions")
def public_map_regions(request:Request,slug:str,at:float|None=None):
    if not player_allowed(request):raise HTTPException(401)
    m=get_map(settings,slug,public=True)
    if not m:raise HTTPException(404)
    rows=map_regions(settings,int(m["id"]),admin=is_gm(request),at_sort=at)
    if not is_gm(request):rows=[r for r in rows if knowledge_visible(request,"map_region",str(r.get('id')))[0]]
    return rows


@app.post("/api/admin/rumors")
def admin_rumor_save(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_rumor(settings,_campaign_payload(request,payload))
@app.delete("/api/admin/rumors/{rid}")
def admin_rumor_delete(request:Request,rid:int):
    require_gm(request)
    with connect(settings) as conn:conn.execute("DELETE FROM rumors WHERE id=?",(rid,))
    return {"ok":True}
@app.get("/api/admin/rumors/random")
def admin_random_rumor(request:Request,location_slug:str="",faction_slug:str=""):
    require_gm(request);row=random_rumor(settings,location_slug=location_slug,faction_slug=faction_slug,campaign_id=_active_campaign_id(request))
    return row or {}

@app.post("/api/admin/rumors/{rid}/share")
def admin_rumor_share(request:Request,rid:int,payload:dict=Body(...)):
    require_gm(request);r=next((x for x in list_rumors(settings,admin=True,campaign_id=_active_campaign_id(request)) if int(x['id'])==rid),None)
    if not r:raise HTTPException(404)
    r=save_rumor(settings,{**r,"status":"heard","campaign_id":_active_campaign_id(request)});create_notification(settings,{"campaign_id":_active_campaign_id(request),"title":"A new rumor is circulating","body":r['body'],"target_type":"rumor","target_key":str(rid),"kind":"rumor","audience":payload.get('audience') or []});return r


@app.post("/api/threads")
def thread_save_api(request:Request,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    try:return save_thread(settings,_campaign_payload(request,payload),invite_id=_invite_id(request),admin=is_gm(request))
    except PermissionError as e:raise HTTPException(403,str(e))
@app.delete("/api/threads/{tid}")
def thread_delete_api(request:Request,tid:int):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    rows=list_threads(settings,admin=is_gm(request),invite_id=_invite_id(request),campaign_id=_active_campaign_id(request));t=next((x for x in rows if int(x['id'])==tid),None)
    if not t:raise HTTPException(404)
    from .living import can_edit_thread
    if not can_edit_thread(t,_invite_id(request),is_gm(request)):raise HTTPException(403)
    with connect(settings) as conn:conn.execute('DELETE FROM campaign_threads WHERE id=?',(tid,))
    return {"ok":True}
@app.post("/api/threads/{tid}/notes")
def thread_note_api(request:Request,tid:int,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    try:return add_thread_note(settings,tid,payload,invite_id=_invite_id(request),author_label=_player_label(request),admin=is_gm(request))
    except PermissionError as e:raise HTTPException(403,str(e))
@app.post("/api/threads/{tid}/links")
def thread_link_api(request:Request,tid:int,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    try:return save_thread_link(settings,tid,payload,invite_id=_invite_id(request),admin=is_gm(request))
    except PermissionError as e:raise HTTPException(403,str(e))


@app.put("/api/thread-notes/{note_id}")
def thread_note_update_api(request:Request,note_id:int,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    try:return update_thread_note(settings,note_id,payload,invite_id=_invite_id(request),admin=is_gm(request))
    except PermissionError as e:raise HTTPException(403,str(e))
    except ValueError as e:raise HTTPException(404,str(e))

@app.delete("/api/thread-notes/{note_id}")
def thread_note_delete_api(request:Request,note_id:int):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    try:delete_thread_note(settings,note_id,invite_id=_invite_id(request),admin=is_gm(request));return {"ok":True}
    except PermissionError as e:raise HTTPException(403,str(e))
    except ValueError as e:raise HTTPException(404,str(e))

@app.delete("/api/threads/{tid}/links")
def thread_link_delete_api(request:Request,tid:int,target_type:str="page",target_key:str=""):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    try:delete_thread_link(settings,tid,target_type,target_key,invite_id=_invite_id(request),admin=is_gm(request));return {"ok":True}
    except PermissionError as e:raise HTTPException(403,str(e))


@app.post("/api/player/journals")
def player_journal_save(request:Request,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    iid=_invite_id(request)
    if iid is None:raise HTTPException(403,"A personal invitation is required for journals.")
    payload=_campaign_payload(request,payload)
    # Session note forms inherit the character identity chosen for the current
    # live session unless the client explicitly chose a different/general scope.
    if "character_id" not in payload:
        cid_active=_active_campaign_id(request);live=get_live_session(settings,invite_id=iid,admin=False,campaign_id=cid_active);session_key=int((live or {}).get("id") or 0)
        if int(request.session.get("session_character_session_id") or -1)==session_key:
            payload["character_id"]=int(request.session.get("session_character_id") or 0) or None
    try:return save_journal(settings,payload,iid)
    except PermissionError as e:raise HTTPException(403,str(e))
    except ValueError as e:raise HTTPException(400,str(e))


@app.post("/api/admin/inbox")
def admin_inbox_save(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_inbox(settings,payload)
@app.post("/api/admin/inbox/{iid}/archive")
def admin_inbox_archive(request:Request,iid:int):
    require_gm(request);row=next((x for x in inbox_items(settings) if int(x['id'])==iid),None)
    if not row:raise HTTPException(404)
    return save_inbox(settings,{**row,"status":"archived"})


@app.post("/api/player/submissions")
def player_submission_save(request:Request,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    iid=_invite_id(request)
    if iid is None:raise HTTPException(403,"A personal invitation is required.")
    return save_submission(settings,_campaign_payload(request,payload),iid)
@app.post("/api/player/submissions/upload")
async def player_submission_upload(request:Request,file:UploadFile=File(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request);iid=_invite_id(request)
    if iid is None:raise HTTPException(403,"A personal invitation is required.")
    ext=Path(file.filename or "asset").suffix.lower()
    allowed={'.png','.jpg','.jpeg','.webp','.gif','.pdf','.mp3','.m4a','.wav','.ogg'}
    if ext not in allowed:raise HTTPException(400,"Use an image, PDF, or common audio file.")
    folder=settings.uploads_dir/'submissions'/str(iid);folder.mkdir(parents=True,exist_ok=True)
    stem=re.sub(r'[^A-Za-z0-9._-]+','-',Path(file.filename or 'asset').stem).strip('-')[:70] or 'asset'
    name=f"{int(time.time()*1000)}-{secrets.token_hex(3)}-{stem}{ext}";path=folder/name
    await _stream_upload(file,path,30_000_000,"Contribution files are limited to 30 MB.")
    rel=path.relative_to(settings.uploads_dir).as_posix();return {"ref":"upload:"+rel,"url":"/uploads/"+quote(rel,safe='/'),"name":file.filename or name}

@app.post("/api/admin/inbox/upload")
async def admin_inbox_upload(request:Request,file:UploadFile=File(...)):
    require_gm(request);ext=Path(file.filename or 'asset').suffix.lower()
    allowed={'.png','.jpg','.jpeg','.webp','.gif','.pdf','.mp3','.m4a','.wav','.ogg','.webm','.txt'}
    if ext not in allowed:raise HTTPException(400,"Unsupported quick-capture file type.")
    folder=settings.uploads_dir/'gm-inbox';folder.mkdir(parents=True,exist_ok=True)
    stem=re.sub(r'[^A-Za-z0-9._-]+','-',Path(file.filename or 'asset').stem).strip('-')[:70] or 'asset'
    name=f"{int(time.time()*1000)}-{secrets.token_hex(3)}-{stem}{ext}";path=folder/name
    await _stream_upload(file,path,40_000_000,"Inbox files are limited to 40 MB.")
    rel=path.relative_to(settings.uploads_dir).as_posix();return {"ref":"upload:"+rel,"url":"/uploads/"+quote(rel,safe='/'),"name":file.filename or name}


@app.post("/api/admin/submissions/{sid}/review")
def admin_submission_review(request:Request,sid:int,payload:dict=Body(...)):
    require_gm(request);return review_submission(settings,sid,str(payload.get('status') or 'approved'),str(payload.get('gm_note') or ''))


@app.put("/api/admin/publishing/{slug}")
def admin_publish_state(request:Request,slug:str,payload:dict=Body(...)):
    require_gm(request);return set_publishing_state(settings,slug,str(payload.get('state') or 'published'),str(payload.get('publish_group') or ''))
@app.post("/api/admin/publishing/batch")
def admin_publish_batch(request:Request,payload:dict=Body(...)):
    require_gm(request);group=str(payload.get('publish_group') or '');state=str(payload.get('state') or 'published');rows=[]
    with connect(settings) as conn:slugs=[r[0] for r in conn.execute('SELECT page_slug FROM publishing_states WHERE publish_group=?',(group,)).fetchall()]
    for slug in slugs:rows.append(set_publishing_state(settings,slug,state,group))
    if state=='published':create_notification(settings,{"campaign_id":_active_campaign_id(request),"title":"New lore published","body":f"A group of {len(rows)} lore entries was published.","kind":"publish"})
    return rows


@app.post("/api/admin/session-state-snapshot")
def admin_session_state_snapshot(request:Request,payload:dict=Body(...)):
    require_gm(request);return capture_session_state(settings,payload.get('session_id'),str(payload.get('phase') or 'manual'))


@app.post("/api/admin/suggestions/scan")
def admin_suggestions_scan(request:Request):
    require_gm(request);return scan_suggestions(settings,ensure_built())
@app.post("/api/admin/suggestions/{sid}")
def admin_suggestion_update(request:Request,sid:int,payload:dict=Body(...)):
    require_gm(request);return update_suggestion(settings,sid,str(payload.get('status') or 'dismissed'))


@app.put("/api/admin/media-meta")
def admin_media_meta(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_media_meta(settings,str(payload.get('ref') or ''),payload)


@app.get("/api/admin/media-usage")
def admin_media_usage(request:Request,ref:str):
    require_gm(request);return media_usage(settings,ref)

@app.post("/api/admin/media-replace")
def admin_media_replace(request:Request,payload:dict=Body(...)):
    require_admin(request);old=str(payload.get('old_ref') or '');new=str(payload.get('new_ref') or '')
    if not old or not new or old==new:raise HTTPException(400,'Choose two different media references.')
    result=replace_media_reference(settings,old,new)
    try:build_wiki(settings)
    except Exception:pass
    return result

@app.get("/api/admin/media-thumb")
def admin_media_thumb(request:Request,ref:str):
    require_gm(request)
    ref=unquote(ref);prefix,_,rel=ref.partition(':')
    if prefix=='project':base=settings.project_dir
    elif prefix=='upload':base=settings.uploads_dir
    else:raise HTTPException(400,'Unknown media reference')
    src=(base/rel).resolve()
    if base.resolve() not in src.parents or not src.exists() or not src.is_file():raise HTTPException(404)
    if src.suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.gif'}:return FileResponse(src)
    import hashlib
    from PIL import Image,ImageOps
    thumb_dir=settings.build_dir/'media-thumbs';thumb_dir.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256((ref+str(src.stat().st_mtime_ns)).encode()).hexdigest()[:24];out=thumb_dir/(key+'.webp')
    if not out.exists():
        try:
            with Image.open(src) as im:
                im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((520,360));im.save(out,'WEBP',quality=78,method=4)
        except Exception:return FileResponse(src)
    return FileResponse(out,media_type='image/webp',headers={'Cache-Control':'private, max-age=604800'})


@app.post("/api/admin/notifications")
def admin_notification_create(request:Request,payload:dict=Body(...)):
    require_gm(request);return create_notification(settings,_campaign_payload(request,payload))
@app.get("/api/public/notifications")
def public_notifications(request:Request,since:float=0):
    if not player_allowed(request):raise HTTPException(401)
    rows=list_notifications(settings,_invite_id(request),admin=is_gm(request),since=since,campaign_id=_active_campaign_id(request))
    iid=_invite_id(request)
    return rows if is_gm(request) or iid is None else filter_notifications_for_prefs(settings,int(iid),rows)
@app.post("/api/public/notifications/{nid}/read")
def public_notification_read(request:Request,nid:int):
    if not player_allowed(request):raise HTTPException(401)
    iid=_invite_id(request)
    reader_id=int(iid) if iid is not None else (-1 if is_gm(request) else None)
    if reader_id is not None:mark_notification_read(settings,nid,reader_id)
    return {"ok":True}

@app.delete("/api/public/notifications/{nid}")
def public_notification_delete(request:Request,nid:int):
    if not player_allowed(request):raise HTTPException(401)
    cid=_active_campaign_id(request)
    rows=list_notifications(settings,_invite_id(request),admin=is_gm(request),since=0,campaign_id=cid)
    if not any(int(r.get('id') or 0)==int(nid) for r in rows):raise HTTPException(404,'Notification not found.')
    if is_gm(request):
        delete_notification(settings,nid,campaign_id=cid)
        return {"ok":True,"deleted":"global"}
    iid=_invite_id(request)
    if iid is None:raise HTTPException(403,'A personal invitation is required.')
    dismiss_notification(settings,nid,int(iid))
    return {"ok":True,"deleted":"personal"}

@app.post("/api/v5/notifications/read-all")
def public_notifications_read_all(request:Request):
    if not player_allowed(request):raise HTTPException(401)
    iid=_invite_id(request)
    reader_id=int(iid) if iid is not None else (-1 if is_gm(request) else None)
    if reader_id is None:return {"ok":True,"count":0}
    rows=list_notifications(settings,iid,admin=is_gm(request),since=0,campaign_id=_active_campaign_id(request))
    for row in rows:mark_notification_read(settings,int(row["id"]),reader_id)
    return {"ok":True,"count":len(rows)}


@app.post("/api/player/characters/{character_id}/relationships")
def player_character_relationship_save(request:Request,character_id:int,payload:dict=Body(...)):
    require_player_author(request);_character_owned(request,character_id);return save_character_relationship(settings,character_id,payload)
@app.delete("/api/player/characters/{character_id}/relationships/{rid}")
def player_character_relationship_delete(request:Request,character_id:int,rid:int):
    require_player_author(request);_character_owned(request,character_id)
    with connect(settings) as conn:conn.execute('DELETE FROM character_relationships WHERE id=? AND character_id=?',(rid,character_id))
    return {"ok":True}
@app.post("/api/player/characters/{character_id}/arcs")
def player_character_arc_save(request:Request,character_id:int,payload:dict=Body(...)):
    require_player_author(request);_character_owned(request,character_id);return save_character_arc(settings,character_id,payload)
@app.delete("/api/player/characters/{character_id}/arcs/{aid}")
def player_character_arc_delete(request:Request,character_id:int,aid:int):
    require_player_author(request);_character_owned(request,character_id)
    with connect(settings) as conn:conn.execute('DELETE FROM character_arcs WHERE id=? AND character_id=?',(aid,character_id))
    return {"ok":True}


@app.get("/api/public/page-provenance/{slug}")
def page_provenance_api(request:Request,slug:str):
    if not player_allowed(request):raise HTTPException(401)
    allowed={p.get('slug') for p in _visible_wiki(request).get('pages',[])}
    if slug not in allowed and not is_gm(request):raise HTTPException(404)
    return entity_provenance(settings,slug,campaign_id=_active_campaign_id(request))


@app.get("/api/export/foundry/page/{slug}")
def foundry_page_export(request:Request,slug:str):
    if not player_allowed(request):raise HTTPException(401)
    p=next((x for x in _visible_wiki(request).get('pages',[]) if x.get('slug')==slug),None)
    if not p:raise HTTPException(404)
    return JSONResponse(export_foundry_journal(p['title'],p.get('html',''),p.get('presentation',{}).get('hero_image_url') or ''))
@app.get("/api/export/foundry/character/{character_id}")
def foundry_character_export(request:Request,character_id:int):
    char=get_player_character(settings,character_id,invite_id=_invite_id(request),admin=is_gm(request),campaign_id=_active_campaign_id(request))
    if not char:raise HTTPException(404)
    body=f"<h2>{char.get('name','')}</h2><p>{char.get('summary','')}</p><h3>Biography</h3><p>{char.get('biography','')}</p><h3>Goals</h3><p>{char.get('goals','')}</p>"
    img='/uploads/'+char.get('portrait_path','') if char.get('portrait_path') else ''
    return JSONResponse(export_foundry_journal(char.get('name','Character'),body,img))


@app.get("/api/admin/portable-archive")
def portable_archive_download(request:Request):
    require_admin(request);out=settings.build_dir/'seeker-portable-campaign.zip';create_portable_archive(settings,out);return FileResponse(out,filename='seeker-portable-campaign.zip',media_type='application/zip')
@app.post("/api/admin/portable-archive/test")
async def portable_archive_test(request:Request,file:UploadFile=File(...)):
    require_admin(request)
    if not str(file.filename or '').lower().endswith('.zip'): raise HTTPException(400,'Choose a Seeker portable ZIP.')
    tmp=Path(tempfile.gettempdir())/f"seeker-backup-test-{secrets.token_hex(8)}.zip"
    total=0
    try:
        with tmp.open('wb') as out:
            while True:
                chunk=await file.read(1024*1024)
                if not chunk: break
                total+=len(chunk)
                if total>2_500_000_000: raise HTTPException(413,'Backup test is limited to 2.5 GB.')
                out.write(chunk)
        try:return validate_portable_archive_file(tmp)
        except ValueError as exc: raise HTTPException(400,str(exc))
    finally:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass


@app.put("/api/admin/archive-mode")
def archive_mode_set(request:Request,payload:dict=Body(...)):
    require_admin(request);enabled=bool(payload.get('enabled'));set_setting(settings,'campaign_archive_mode','1' if enabled else '0')
    if enabled:
        capture_session_state(settings,None,'archive-freeze')
        create_notification(settings,{'campaign_id':_active_campaign_id(request),'title':'Campaign archive published','body':'The campaign has been frozen into read-only archive mode.','kind':'archive'})
    return {'enabled':enabled}
@app.get("/archive", response_class=HTMLResponse)
def campaign_archive_page(request:Request):
    if not player_allowed(request):return player_gate_redirect(request)
    wiki=_visible_wiki(request);maps=list_maps(settings,public=True)
    return templates.TemplateResponse('archive.html',{'request':request,'wiki':wiki,'maps':maps,'sessions':list_sessions(settings,public=True,invite_id=_invite_id(request),campaign_id=_active_campaign_id(request)),'timeline':list_timeline(settings,admin=is_gm(request),historical_only=True),'characters':list_player_characters(settings,invite_id=_invite_id(request),admin=is_gm(request),campaign_id=_active_campaign_id(request))})


@app.post("/api/assistant/query")
def lore_assistant_query(request:Request,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    q=str(payload.get('q') or '').strip()
    if not q:raise HTTPException(400,'Ask a question about the campaign.')
    wiki=_visible_wiki(request);pages=wiki.get('pages',[])
    hits=semantic_search(pages,q,limit=8);by_slug={p.get('slug'):p for p in pages};context=[]
    for hit in hits:
        p=by_slug.get(hit.get('slug')) or {}
        plain=re.sub(r'\s+',' ',p.get('plain_text') or p.get('excerpt') or '').strip()
        context.append({'title':hit.get('title'),'slug':hit.get('slug'),'text':plain[:1800],'semantic_matches':hit.get('semantic_matches',[])})
    api_key=(os.getenv('SEEKER_AI_API_KEY') or os.getenv('LOREFORGE_AI_API_KEY','')).strip();model=(os.getenv('SEEKER_AI_MODEL') or os.getenv('LOREFORGE_AI_MODEL','')).strip();base=(os.getenv('SEEKER_AI_BASE_URL') or os.getenv('LOREFORGE_AI_BASE_URL','https://api.openai.com/v1')).rstrip('/')
    if api_key and model and payload.get('use_ai',True):
        try:
            system='You are Seeker, the campaign companion. Answer ONLY from the supplied spoiler-filtered campaign context. If the answer is not in the context, say so. Keep fantasy names exact.'
            prompt='QUESTION:\n'+q+'\n\nVISIBLE CAMPAIGN CONTEXT:\n'+'\n\n'.join(f"[{c['title']}] {c['text']}" for c in context)
            body=json.dumps({'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':prompt}],'temperature':0.2}).encode()
            req=UrlRequest(base+'/chat/completions',data=body,headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json'})
            with urlopen(req,timeout=35) as resp:data=json.loads(resp.read().decode())
            answer=data['choices'][0]['message']['content'];return {'mode':'ai','answer':answer,'sources':[{k:c[k] for k in ('title','slug')} for c in context]}
        except Exception as exc:
            ai_error=str(exc)
        else: ai_error=''
    else:ai_error=''
    if not context:return {'mode':'semantic','answer':'I could not find that in the lore currently visible to you.','sources':[],'ai_error':ai_error}
    snippets=[]
    for c in context[:4]:
        snippets.append(f"{c['title']}: {c['text'][:420].rstrip()}…")
    return {'mode':'semantic','answer':'\n\n'.join(snippets),'sources':[{k:c[k] for k in ('title','slug')} for c in context[:4]],'ai_error':ai_error}


@app.put("/api/admin/invitations/{invite_id}/role")
def admin_invitation_role(request:Request,invite_id:int,payload:dict=Body(...)):
    require_admin(request);role=str(payload.get('role') or 'player').lower()
    if role not in {'player','observer','guest','co-gm'}:raise HTTPException(400,'Unknown role')
    with connect(settings) as conn:
        cur=conn.execute('UPDATE player_invites SET role=?,access_version=access_version+1 WHERE id=?',(role,int(invite_id)))
        if cur.rowcount!=1:raise HTTPException(404)
        conn.execute('DELETE FROM player_devices WHERE invite_id=?',(int(invite_id),))
    return next((x for x in list_player_invites(settings) if int(x['id'])==invite_id),{})

# ---------------------------------------------------------------------------
# Seeker V5 · player session companion
# ---------------------------------------------------------------------------

@app.get('/investigation', response_class=HTMLResponse)
def investigation_page(request:Request):
    if not player_allowed(request): return player_gate_redirect(request)
    invite=current_player_invite(request)
    if not invite: raise HTTPException(403,'A personal player invitation is required for a private investigation board.')
    wiki=_visible_wiki(request);cid=_active_campaign_id(request)
    board=investigation_board(settings,cid,int(invite['id']))
    return templates.TemplateResponse('investigation.html',{'request':request,'wiki':wiki,'maps':list_maps(settings,public=True),'board':board,'player':invite})


@app.get('/api/v5/follows')
def v5_follows(request:Request):
    if not player_allowed(request): raise HTTPException(401)
    invite=current_player_invite(request)
    if not invite:return []
    return list_follows(settings,int(invite['id']),_active_campaign_id(request))


@app.post('/api/v5/follows')
def v5_follow_save(request:Request,payload:dict=Body(...)):
    require_player_author(request);invite=current_player_invite(request)
    if not invite:raise HTTPException(403)
    try:enabled=set_follow(settings,int(invite['id']),_active_campaign_id(request),str(payload.get('target_type') or 'page'),str(payload.get('target_key') or ''),bool(payload.get('enabled',True)),str(payload.get('label') or ''))
    except ValueError as exc:raise HTTPException(400,str(exc))
    return {'ok':True,'enabled':enabled}


@app.get('/api/v5/party-notes')
def v5_party_notes(request:Request,session_id:int|None=None):
    if not player_allowed(request):raise HTTPException(401)
    cid=_active_campaign_id(request)
    return list_party_notes(settings,cid,session_id,150)


@app.post('/api/v5/party-notes')
def v5_party_note_save(request:Request,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    if not is_gm(request):require_player_author(request)
    invite=current_player_invite(request);iid=int(invite['id']) if invite else None
    try:return save_party_note(settings,_active_campaign_id(request),payload.get('session_id'),iid,_player_label(request),payload.get('body',''),payload.get('id'),admin=is_gm(request))
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v5/party-notes/{note_id}')
def v5_party_note_delete(request:Request,note_id:int):
    if not player_allowed(request):raise HTTPException(401)
    if not is_gm(request):require_player_author(request)
    try:delete_party_note(settings,note_id,_invite_id(request),admin=is_gm(request))
    except PermissionError as exc:raise HTTPException(403,str(exc))
    return {'ok':True}


@app.get('/api/v5/investigation')
def v5_investigation_get(request:Request):
    if not player_allowed(request):raise HTTPException(401)
    invite=current_player_invite(request)
    if not invite:raise HTTPException(403)
    return investigation_board(settings,_active_campaign_id(request),int(invite['id']))


@app.post('/api/v5/investigation/nodes')
def v5_investigation_node_save(request:Request,payload:dict=Body(...)):
    require_player_author(request);invite=current_player_invite(request)
    try:return save_investigation_node(settings,_active_campaign_id(request),int(invite['id']),payload)
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v5/investigation/nodes/{node_id}')
def v5_investigation_node_delete(request:Request,node_id:int):
    require_player_author(request);invite=current_player_invite(request);delete_investigation_node(settings,node_id,_active_campaign_id(request),int(invite['id']));return {'ok':True}


@app.post('/api/v5/investigation/edges')
def v5_investigation_edge_save(request:Request,payload:dict=Body(...)):
    require_player_author(request);invite=current_player_invite(request)
    try:return save_investigation_edge(settings,_active_campaign_id(request),int(invite['id']),payload)
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v5/investigation/edges/{edge_id}')
def v5_investigation_edge_delete(request:Request,edge_id:int):
    require_player_author(request);invite=current_player_invite(request);delete_investigation_edge(settings,edge_id,_active_campaign_id(request),int(invite['id']));return {'ok':True}


@app.get('/api/v5/objectives')
def v5_objectives_get(request:Request):
    if not player_allowed(request):raise HTTPException(401)
    return list_objectives(settings,_active_campaign_id(request))


@app.post('/api/v5/objectives')
def v5_objective_save(request:Request,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    if not is_gm(request):require_player_author(request)
    try:return save_objective(settings,_active_campaign_id(request),payload,_invite_id(request),_player_label(request),admin=is_gm(request))
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v5/objectives/{objective_id}')
def v5_objective_delete(request:Request,objective_id:int):
    if not is_gm(request):require_player_author(request)
    try:delete_objective(settings,objective_id,_invite_id(request),admin=is_gm(request))
    except PermissionError as exc:raise HTTPException(403,str(exc))
    return {'ok':True}


@app.post('/api/v5/characters/{character_id}/milestones')
def v5_character_milestone_save(request:Request,character_id:int,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    if not is_gm(request):require_player_author(request)
    char=_character_owned(request,character_id)
    return save_character_milestone(settings,char,str(payload.get('label') or 'Milestone'),str(payload.get('note') or ''),payload.get('session_id'))


@app.delete('/api/v5/characters/{character_id}/milestones/{milestone_id}')
def v5_character_milestone_delete(request:Request,character_id:int,milestone_id:int):
    if not is_gm(request):require_player_author(request)
    _character_owned(request,character_id);delete_character_milestone(settings,milestone_id,character_id);return {'ok':True}


@app.post('/api/v5/sessions/{session_id}/rsvp')
def v5_session_rsvp(request:Request,session_id:int,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    invite=current_player_invite(request)
    if not invite:raise HTTPException(403,'A personal invitation is required to RSVP.')
    try:return save_rsvp(settings,session_id,int(invite['id']),str(payload.get('status') or 'maybe'),str(payload.get('note') or ''))
    except PermissionError as exc:raise HTTPException(403,str(exc))
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.get('/api/v5/sessions/{session_id}/rsvps')
def v5_session_rsvps(request:Request,session_id:int):
    require_gm(request);return session_rsvps(settings,session_id)


@app.get('/gm/prep',response_class=HTMLResponse)
def gm_prep_page(request:Request,session_id:int|None=None):
    require_gm(request);cid=_active_campaign_id(request);wiki=_visible_wiki(request);sessions=list_prepared_sessions(settings,cid)
    selected=None
    if session_id:selected=next((s for s in sessions if int(s['id'])==int(session_id)),None)
    if selected is None:selected=next((s for s in sessions if s.get('status') in {'live','planned'}),None)
    prep=get_preparation(settings,int(selected['id'])) if selected else None
    chars=list_player_characters(settings,admin=True,campaign_id=cid)
    for c in chars:c['arcs']=character_arcs(settings,int(c['id']),owner=True)
    objectives=list_objectives(settings,cid)
    workspace=prep_workspace(settings,cid,int(selected['id']),chars,sessions,objectives) if selected else {
        'scenes':[],'clues':list_clues(settings,cid),'npc_cards':list_npc_cards(settings,cid),'events':[],
        'consequences':list_consequences(settings,cid),'clocks':list_clocks(settings,cid),'spotlights':spotlight_status(settings,cid,chars,sessions),
        'templates':list_templates(settings,cid),'random_tables':list_random_tables(settings,cid),'forgotten':forgotten_items(settings,cid,chars,sessions,objectives)}
    return templates.TemplateResponse('gm_prep.html',{
        'request':request,'wiki':wiki,'maps':list_maps(settings,public=False),'sessions':sessions,'selected_session':selected,'prep':prep,
        'mysteries':list_mysteries(settings,admin=True,campaign_id=cid),'handouts':list_handouts(settings,admin=True,campaign_id=cid),
        'fronts':list_fronts(settings,admin=True,campaign_id=cid),'rumors':list_rumors(settings,admin=True,campaign_id=cid),
        'characters':chars,'objectives':objectives,'v51_workspace':workspace,'foundry_v6':foundry_state(settings,cid),
    })


@app.get('/api/v5/gm/prep/{session_id}')
def v5_gm_prep_get(request:Request,session_id:int):
    require_gm(request);return get_preparation(settings,session_id)


@app.put('/api/v5/gm/prep/{session_id}')
def v5_gm_prep_save(request:Request,session_id:int,payload:dict=Body(...)):
    require_gm(request)
    try:return save_preparation(settings,session_id,_active_campaign_id(request),payload)
    except ValueError as exc:raise HTTPException(400,str(exc))



@app.get('/api/v51/gm/workspace/{session_id}')
def v51_gm_workspace(request:Request,session_id:int):
    require_gm(request);cid=_active_campaign_id(request)
    sessions=list_prepared_sessions(settings,cid);selected=next((x for x in sessions if int(x['id'])==int(session_id)),None)
    if not selected:raise HTTPException(404,'Session not found in this campaign.')
    chars=list_player_characters(settings,admin=True,campaign_id=cid)
    return prep_workspace(settings,cid,session_id,chars,sessions,list_objectives(settings,cid))


@app.put('/api/v51/gm/scenes/{session_id}')
def v51_gm_scenes_save(request:Request,session_id:int,payload:dict=Body(...)):
    require_gm(request)
    try:return save_scenes(settings,_active_campaign_id(request),session_id,payload.get('scenes') or [])
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post('/api/v51/gm/clues')
def v51_gm_clue_save(request:Request,payload:dict=Body(...)):
    require_gm(request)
    try:return save_clue(settings,_active_campaign_id(request),payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v51/gm/clues/{clue_id}')
def v51_gm_clue_delete(request:Request,clue_id:int):
    require_gm(request);delete_clue(settings,_active_campaign_id(request),clue_id);return {'ok':True}


@app.post('/api/v51/gm/npc-cards')
def v51_gm_npc_save(request:Request,payload:dict=Body(...)):
    require_gm(request)
    try:return save_npc_card(settings,_active_campaign_id(request),payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v51/gm/npc-cards/{page_slug:path}')
def v51_gm_npc_delete(request:Request,page_slug:str):
    require_gm(request);delete_npc_card(settings,_active_campaign_id(request),page_slug);return {'ok':True}


@app.post('/api/v51/gm/events/{session_id}')
def v51_gm_event_add(request:Request,session_id:int,payload:dict=Body(...)):
    require_gm(request)
    try:return add_event(settings,_active_campaign_id(request),session_id,payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v51/gm/events/{event_id}')
def v51_gm_event_delete(request:Request,event_id:int):
    require_gm(request);delete_event(settings,_active_campaign_id(request),event_id);return {'ok':True}


@app.post('/api/v51/gm/consequences')
def v51_gm_consequence_save(request:Request,payload:dict=Body(...)):
    require_gm(request)
    try:return save_consequence(settings,_active_campaign_id(request),payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v51/gm/consequences/{item_id}')
def v51_gm_consequence_delete(request:Request,item_id:int):
    require_gm(request);delete_consequence(settings,_active_campaign_id(request),item_id);return {'ok':True}


@app.post('/api/v51/gm/clocks')
def v51_gm_clock_save(request:Request,payload:dict=Body(...)):
    require_gm(request)
    try:
        row=save_clock(settings,_active_campaign_id(request),payload)
        if row.get('visibility')=='player':
            create_notification(settings,{'campaign_id':_active_campaign_id(request),'title':row['title'],'body':f"Campaign clock: {row['current_segments']}/{row['total_segments']}",'kind':'notice'})
        return row
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v51/gm/clocks/{item_id}')
def v51_gm_clock_delete(request:Request,item_id:int):
    require_gm(request);delete_clock(settings,_active_campaign_id(request),item_id);return {'ok':True}


@app.post('/api/v51/gm/spotlights/{character_id}')
def v51_gm_spotlight_mark(request:Request,character_id:int,payload:dict=Body(default={})):
    require_gm(request);cid=_active_campaign_id(request)
    char=get_player_character(settings,character_id,admin=True,campaign_id=cid)
    if not char:raise HTTPException(404,'Character not found in this campaign.')
    return record_spotlight(settings,cid,character_id,payload.get('session_id'),str(payload.get('note') or ''))


@app.post('/api/v51/gm/templates')
def v51_gm_template_save(request:Request,payload:dict=Body(...)):
    require_gm(request)
    try:return save_template(settings,_active_campaign_id(request),payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v51/gm/templates/{item_id}')
def v51_gm_template_delete(request:Request,item_id:int):
    require_gm(request);delete_template(settings,_active_campaign_id(request),item_id);return {'ok':True}


@app.post('/api/v51/gm/random-tables')
def v51_gm_random_table_save(request:Request,payload:dict=Body(...)):
    require_gm(request)
    try:return save_random_table(settings,_active_campaign_id(request),payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v51/gm/random-tables/{item_id}')
def v51_gm_random_table_delete(request:Request,item_id:int):
    require_gm(request);delete_random_table(settings,_active_campaign_id(request),item_id);return {'ok':True}


@app.post('/api/v51/gm/random-tables/roll')
def v51_gm_random_table_roll(request:Request,payload:dict=Body(...)):
    require_gm(request)
    try:return roll_random_table(settings,_active_campaign_id(request),str(payload.get('table_id') or ''))
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post('/api/v51/gm/push')
def v51_gm_push(request:Request,payload:dict=Body(...)):
    require_gm(request);cid=_active_campaign_id(request);kind=str(payload.get('kind') or 'notice')[:50]
    target_type=str(payload.get('target_type') or '')[:50];target_key=str(payload.get('target_key') or '')[:500]
    title=str(payload.get('title') or 'New table information')[:250];body=str(payload.get('body') or '')[:5000]
    # Pushes are intentionally explicit: they notify, but do not silently publish hidden Codex truth.
    return create_notification(settings,{'campaign_id':cid,'title':title,'body':body,'target_type':target_type,'target_key':target_key,'kind':kind})


@app.post('/api/v51/gm/apply-template/{session_id}')
def v51_gm_apply_template(request:Request,session_id:int,payload:dict=Body(...)):
    require_gm(request);cid=_active_campaign_id(request);template_id=str(payload.get('template_id') or '')
    template=next((x for x in list_templates(settings,cid) if str(x.get('id'))==template_id),None)
    if not template:raise HTTPException(404,'Template not found.')
    data=template if template.get('builtin') else (template.get('payload') or {})
    scenes=data.get('scenes') or (data.get('payload') or {}).get('scenes') or []
    if scenes:save_scenes(settings,cid,session_id,scenes)
    prep=get_preparation(settings,session_id)
    source=data.get('prep') or (data.get('payload') or {}).get('prep') or {}
    for key in ('opening','secrets','contingencies','notes','pacing'):
        if source.get(key):prep[key]=source[key]
    if not prep.get('pacing'):prep['pacing']=[{'label':x,'done':False,'note':''} for x in ('Opening','Exploration','Social pressure','Escalation','Climax','Fallout')]
    save_preparation(settings,session_id,cid,prep)
    return {'ok':True,'prep':get_preparation(settings,session_id),'scenes':list_scenes(settings,cid,session_id)}


@app.post('/api/v51/gm/closeout/{session_id}')
def v51_gm_closeout(request:Request,session_id:int,payload:dict=Body(...)):
    require_gm(request);cid=_active_campaign_id(request)
    sessions=list_prepared_sessions(settings,cid);session=next((x for x in sessions if int(x['id'])==int(session_id)),None)
    if not session:raise HTTPException(404,'Session not found.')

    # Guided closeout updates. Everything is campaign-scoped and optional so an
    # old/simple client can still close a session with only summary text.
    clue_states=payload.get('clue_states') if isinstance(payload.get('clue_states'),dict) else {}
    if clue_states:
        by_id={int(x['id']):x for x in list_clues(settings,cid)}
        for raw_id,state in clue_states.items():
            try:rid=int(raw_id)
            except Exception:continue
            row=by_id.get(rid);state=str(state or '')
            if row and state in {'not_found','hinted','discovered','misinterpreted'} and state!=row.get('status'):
                save_clue(settings,cid,{**row,'status':state,'delivered_session_id':(session_id if state=='discovered' else row.get('delivered_session_id'))})

    objective_states=payload.get('objective_states') if isinstance(payload.get('objective_states'),dict) else {}
    if objective_states:
        by_id={int(x['id']):x for x in list_objectives(settings,cid,include_done=True)}
        for raw_id,state in objective_states.items():
            try:rid=int(raw_id)
            except Exception:continue
            row=by_id.get(rid);state=str(state or '')
            if row and state in {'active','hold','completed','failed'} and state!=row.get('status'):
                save_objective(settings,cid,{**row,'status':state},None,'GM',admin=True)

    consequence_states=payload.get('consequence_states') if isinstance(payload.get('consequence_states'),dict) else {}
    if consequence_states:
        by_id={int(x['id']):x for x in list_consequences(settings,cid,include_resolved=True)}
        for raw_id,state in consequence_states.items():
            try:rid=int(raw_id)
            except Exception:continue
            row=by_id.get(rid);state=str(state or '')
            if row and state in {'pending','resolved','cancelled'} and state!=row.get('status'):
                save_consequence(settings,cid,{**row,'status':state})

    clock_values=payload.get('clock_values') if isinstance(payload.get('clock_values'),dict) else {}
    if clock_values:
        by_id={int(x['id']):x for x in list_clocks(settings,cid,include_done=True)}
        for raw_id,value in clock_values.items():
            try:rid=int(raw_id);value=int(value)
            except Exception:continue
            row=by_id.get(rid)
            if row and value!=int(row.get('current_segments') or 0):
                save_clock(settings,cid,{**row,'current_segments':value})

    session=save_session(settings,{**session,'campaign_id':cid,'status':'ended','summary':str(payload.get('summary') or session.get('summary') or '')})
    next_id=None
    if bool(payload.get('create_next',True)):
        nums=[int(x['session_number']) for x in sessions if x.get('session_number') is not None]
        next_row=save_session(settings,{'campaign_id':cid,'session_number':(max(nums)+1 if nums else None),'title':str(payload.get('next_title') or 'Next session')[:200],'session_date':'','status':'planned','summary':''})
        next_id=int(next_row['id'])
        old_prep=get_preparation(settings,session_id);unfinished=[s for s in list_scenes(settings,cid,session_id) if s.get('status') not in {'done','skipped'}]

        # Seed the next runbook from campaign state, not merely from whatever
        # happened to be typed into the previous prep page.
        carry_refs=list(old_prep.get('references') or [])
        seen={(str(r.get('type')),str(r.get('key'))) for r in carry_refs if isinstance(r,dict)}
        def add_ref(kind,key,label):
            token=(str(kind),str(key))
            if token not in seen and len(carry_refs)<120:
                carry_refs.append({'type':str(kind),'key':str(key),'label':str(label)[:300]});seen.add(token)
        for obj in list_objectives(settings,cid):
            if obj.get('status') in {'active','hold'}:add_ref('objective',obj['id'],obj.get('title') or 'Objective')
        for mystery in list_mysteries(settings,admin=True,campaign_id=cid):
            if mystery.get('status')=='open':add_ref('mystery',mystery['id'],mystery.get('title') or 'Mystery')
        for front in list_fronts(settings,admin=True,campaign_id=cid):
            if front.get('status')=='active':add_ref('front',front['id'],front.get('title') or 'Front')
        for char in list_player_characters(settings,admin=True,campaign_id=cid):
            for arc in (char.get('arcs') or []):
                if arc.get('status')=='active':add_ref('character',char['id'],f"{char.get('name','Character')} · {arc.get('title','Arc')}")

        carry=[]
        unresolved=str(payload.get('unresolved') or '').strip()
        if unresolved:carry.append(unresolved)
        pending_cons=list_consequences(settings,cid)
        if pending_cons:carry.append('Pending consequences:\n'+'\n'.join('• '+str(x.get('title') or '') for x in pending_cons[:12]))
        pending_clues=[x for x in list_clues(settings,cid) if x.get('status')!='discovered']
        if pending_clues:carry.append('Undelivered / unresolved clues:\n'+'\n'.join('• '+str(x.get('title') or '') for x in pending_clues[:12]))
        if old_prep.get('notes'):carry.append('Previous scratchpad:\n'+str(old_prep.get('notes')))
        seed={'opening':'','beats':[],'secrets':'','contingencies':'','notes':('CARRY FORWARD\n\n'+'\n\n'.join(carry)) if carry else '', 'references':carry_refs,'pacing':[{'label':x,'done':False,'note':''} for x in ('Opening','Exploration','Social pressure','Escalation','Climax','Fallout')]}
        save_preparation(settings,next_id,cid,seed)
        if unfinished:
            copied=[]
            for scene in unfinished:
                copied.append({k:scene.get(k) for k in ('title','purpose','location_slug','npc_slugs','complication','fallback','notes','estimated_minutes')}|{'status':'ready'})
            save_scenes(settings,cid,next_id,copied)
    save_closeout(settings,cid,session_id,str(payload.get('summary') or ''),str(payload.get('unresolved') or ''),next_id)
    return {'ok':True,'session':session,'next_session_id':next_id}


@app.post('/api/v5/gm/map-markers/{marker_id}/discovery')
def v5_map_discovery_save(request:Request,marker_id:int,payload:dict=Body(...)):
    require_gm(request)
    try:return set_map_discovery(settings,_active_campaign_id(request),marker_id,str(payload.get('state') or 'discovered'),payload.get('session_id'))
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post('/api/v5/gm/map-fog/{fog_id}')
def v5_map_fog_save(request:Request,fog_id:int,payload:dict=Body(...)):
    require_gm(request);set_campaign_fog(settings,_active_campaign_id(request),fog_id,bool(payload.get('revealed')));return {'ok':True}


@app.get('/api/v5/notification-prefs')
def v5_notification_prefs_get(request:Request):
    if not player_allowed(request):raise HTTPException(401)
    invite=current_player_invite(request)
    return notification_prefs(settings,int(invite['id'])) if invite else {}


@app.put('/api/v5/notification-prefs/{kind}')
def v5_notification_pref_save(request:Request,kind:str,payload:dict=Body(...)):
    require_player_author(request);invite=current_player_invite(request);return set_notification_pref(settings,int(invite['id']),kind,bool(payload.get('enabled',True)))

# ---------------------------------------------------------------------------
# Seeker V6 — continuity, integrations and table companion infrastructure
# ---------------------------------------------------------------------------

@app.get('/gm/continuity', response_class=HTMLResponse)
def v6_continuity_page(request: Request):
    require_gm(request)
    wiki=_visible_wiki(request);cid=_active_campaign_id(request)
    sync_lore_revisions(settings, ensure_built())
    extra=continuity_v6(settings,cid,wiki);base=continuity_report(settings,wiki)
    continuity={'issues':base.get('issues',[])+extra.get('issues',[])};continuity['count']=len(continuity['issues'])
    return templates.TemplateResponse('gm_continuity.html', {
        'request':request,'wiki':wiki,'maps':list_maps(settings,public=True),
        'changes':changes_since_last_session(settings,cid),
        'continuity_v6':continuity,
        'matrix':knowledge_matrix(settings),
        'snapshots':list_snapshots(settings),
        'backups':list_backups(settings),
    })


@app.get('/gm/integrations', response_class=HTMLResponse)
def v6_integrations_page(request: Request):
    require_gm(request);cid=_active_campaign_id(request);cfg=integration_config(settings,cid,include_secret=True)
    camp=get_campaign(settings,cid) or {}
    base=_external_base_url(request)
    cfg['calendar_feed_url']=f"{base}/calendar-feed/{cid}/{cfg.get('calendar_token')}.ics"
    cfg['foundry_push_url']=f"{base}/api/v6/foundry/push/{cid}?token={quote(str(cfg.get('foundry_bridge_token') or ''))}"
    cfg['foundry_manifest_url']=f"{base}/foundry/seeker-bridge/module.json"
    cfg['display_url']=f"{base}/display?campaign_id={cid}&token={quote(str(cfg.get('display_token') or ''))}"
    return templates.TemplateResponse('gm_integrations.html', {'request':request,'wiki':_visible_wiki(request),'maps':list_maps(settings,public=True),'integration':cfg,'campaign':camp,'foundry':foundry_state(settings,cid),'foundry_actors':foundry_actors(settings,cid)})


@app.get('/gm/foundry-workshop', response_class=HTMLResponse)
def v61_foundry_workshop_page(request: Request):
    require_gm(request)
    cid=_active_campaign_id(request)
    return templates.TemplateResponse('gm_foundry_workshop.html', {
        'request':request,
        'wiki':_visible_wiki(request),
        'maps':list_maps(settings,public=True),
        'foundry':foundry_state(settings,cid),
        'foundry_actors':foundry_actors(settings,cid),
        'prepared_content':list_foundry_prepared_content(settings,cid),
        'command_log':recent_foundry_commands(settings,cid),
    })


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
    req=UrlRequest(url,headers={'User-Agent':'Seeker/7.0.3 (+Foundry Workshop)','Accept':'image/*'})
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


@app.post('/api/v61/foundry/assets')
async def v613_foundry_asset_upload(request:Request,image:UploadFile=File(...),kind:str=Form('art')):
    require_gm(request)
    suffix=Path(image.filename or 'image.png').suffix.lower()
    if suffix not in {'.png','.jpg','.jpeg','.webp'}:
        raise HTTPException(400,'Foundry artwork must be PNG, JPG, or WebP.')
    cid=_active_campaign_id(request)
    temp=Path(tempfile.gettempdir())/f'seeker-foundry-upload-{secrets.token_hex(8)}{suffix}'
    try:
        await _stream_upload(image,temp,20_000_000,'Foundry artwork is limited to 20 MB per image.')
        return _optimize_foundry_image(temp,cid,kind,Path(image.filename or 'art').stem)
    finally:
        temp.unlink(missing_ok=True)


@app.post('/api/v61/foundry/assets/import')
def v614_foundry_asset_import(request:Request,payload:dict=Body(...)):
    require_gm(request)
    return _download_remote_foundry_image(str(payload.get('url') or ''),_active_campaign_id(request),str(payload.get('kind') or 'art'))


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


@app.get('/api/v6/foundry/asset/{campaign_id}/{asset_path:path}')
def v613_foundry_asset(campaign_id:int,asset_path:str,sig:str=''):
    rel=unquote(asset_path).lstrip('/')
    expected=_foundry_asset_signature(campaign_id,rel)
    if not sig or not secrets.compare_digest(expected,str(sig)):
        raise HTTPException(404,'Asset not found.')
    base=(settings.uploads_dir/'foundry'/str(int(campaign_id))).resolve()
    path=(base/rel).resolve()
    if base not in path.parents or not path.is_file():raise HTTPException(404,'Asset not found.')
    return FileResponse(path,headers={'Cache-Control':'private, max-age=86400','Access-Control-Allow-Origin':'*'})


@app.get('/bestiary', response_class=HTMLResponse)
def v613_bestiary_page(request:Request):
    if not player_allowed(request):return player_gate_redirect(request)
    cid=_active_campaign_id(request);wiki=_visible_wiki(request)
    return templates.TemplateResponse('bestiary.html',{
        'request':request,'wiki':wiki,'maps':list_maps(settings,public=not is_gm(request)),
        'monsters':_published_bestiary_rows(cid),'gm_view':is_gm(request),
    })


@app.get('/bestiary/{entry_id}', response_class=HTMLResponse)
def v613_bestiary_entry(request:Request,entry_id:int):
    if not player_allowed(request):return player_gate_redirect(request)
    cid=_active_campaign_id(request);wiki=_visible_wiki(request)
    entry=next((r for r in _published_bestiary_rows(cid) if int(r.get('id') or 0)==int(entry_id)),None)
    if not entry:raise HTTPException(404,'Bestiary entry not found.')
    payload=entry.get('payload') or {}
    full=is_gm(request) or str(payload.get('codex_visibility') or 'rough').lower()=='full'
    return templates.TemplateResponse('bestiary_entry.html',{
        'request':request,'wiki':wiki,'maps':list_maps(settings,public=not is_gm(request)),
        'entry':entry,'monster':payload,'show_statblock':full,'gm_view':is_gm(request),
    })


@app.get('/gm/media', response_class=HTMLResponse)
def v6_media_page(request: Request, session_id: int|None=None):
    require_gm(request);cid=_active_campaign_id(request);sessions=list_sessions(settings,campaign_id=cid)
    session=next((s for s in sessions if session_id and int(s['id'])==int(session_id)),None)
    if not session:session=next((s for s in sessions if s.get('status') in {'live','planned'}),None)
    items=list_media_items(settings,cid,int(session['id'])) if session else []
    return templates.TemplateResponse('gm_media.html', {'request':request,'wiki':_visible_wiki(request),'maps':list_maps(settings,public=True),'sessions':sessions,'session':session,'media_items':items,'display_state':display_state(settings,cid)})


def _display_payload_for_token(state:dict,campaign_id:int,token:str='')->dict:
    out=dict(state or {})
    source=str(out.get('source_url') or '')
    if token and out.get('media_item_id') and (source.startswith('/uploads/') or source.startswith('/project-asset/')):
        out['source_url']=f"/api/v6/display/{int(campaign_id)}/asset/{int(out['media_item_id'])}?token={quote(str(token))}"
    return out


@app.get('/display', response_class=HTMLResponse)
def v6_display_page(request: Request, campaign_id: int|None=None, token: str=''):
    cid=resolve_campaign_id(settings,campaign_id or request.session.get('active_campaign_id'))
    allowed=player_allowed(request)
    if not allowed and token:
        cfg=integration_config(settings,cid,include_secret=True)
        allowed=secrets.compare_digest(str(cfg.get('display_token') or ''),str(token or ''))
    if not allowed:return player_gate_redirect(request)
    camp=get_campaign(settings,cid) or {}
    return templates.TemplateResponse('display.html', {'request':request,'wiki':_visible_wiki(request) if player_allowed(request) else {'title':'Seeker'},'maps':list_maps(settings,public=True),'campaign':camp,'display_state':_display_payload_for_token(display_state(settings,cid),cid,token if not player_allowed(request) else ''),'display_campaign_id':cid,'display_token':token if not player_allowed(request) else ''})


@app.get('/lore-history/{slug}', response_class=HTMLResponse)
def v6_lore_history_page(request: Request, slug: str):
    require_gm(request);sync_lore_revisions(settings,ensure_built())
    wiki=_visible_wiki(request);page=next((p for p in wiki.get('pages',[]) if p.get('slug')==slug),None)
    if not page:raise HTTPException(404,'Codex entry not found.')
    return templates.TemplateResponse('lore_history.html', {'request':request,'wiki':wiki,'maps':list_maps(settings,public=True),'page':page,'revisions':lore_revisions(settings,slug)})


@app.get('/api/v6/integrations')
def v6_integrations_get(request: Request):
    require_gm(request);return integration_config(settings,_active_campaign_id(request),include_secret=True)


@app.put('/api/v6/integrations')
def v6_integrations_save(request: Request,payload:dict=Body(...)):
    require_gm(request);return save_integration_config(settings,_active_campaign_id(request),payload)


@app.post('/api/v6/discord/test')
def v6_discord_test(request: Request):
    require_gm(request);cid=_active_campaign_id(request);camp=get_campaign(settings,cid) or {}
    cfg=integration_config(settings,cid,include_secret=True)
    mention=str(cfg.get('discord_mention') or '').strip()
    if mention.lower().replace(' ','') in {'everyone','@everyone'}: mention='@everyone'
    elif mention.lower().replace(' ','') in {'here','@here'}: mention='@here'
    message=f"✦ Seeker is connected to **{camp.get('name','this campaign')}**."
    if mention: message=f"{mention}\n{message}"
    try:return discord_post(settings,cid,message)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post('/api/v6/discord/send')
def v6_discord_send(request: Request,payload:dict=Body(...)):
    require_gm(request)
    try:return discord_post(settings,_active_campaign_id(request),str(payload.get('content') or ''))
    except ValueError as exc:raise HTTPException(400,str(exc))


_FOUNDRY_CORS={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Methods':'POST, OPTIONS','Access-Control-Allow-Headers':'Content-Type','Access-Control-Max-Age':'86400'}


@app.options('/api/v6/foundry/push/{campaign_id}')
def v6_foundry_push_options(campaign_id:int):
    return Response(status_code=204,headers=_FOUNDRY_CORS)


@app.options('/api/v6/foundry/push/{campaign_id}/ack')
def v61_foundry_push_ack_options(campaign_id:int):
    return Response(status_code=204,headers=_FOUNDRY_CORS)


@app.options('/api/v6/foundry/push/{campaign_id}/commands')
def v614_foundry_commands_options(campaign_id:int):
    return Response(status_code=204,headers=_FOUNDRY_CORS)


@app.post('/api/v6/foundry/push/{campaign_id}')
def v6_foundry_push(campaign_id:int,token:str='',payload:dict=Body(...)):
    try:
        result=foundry_accept(settings,campaign_id,token,payload)
        # V7-managed Foundry documents piggy-back on the existing authenticated
        # heartbeat. Ingestion is additive and never blocks the table bridge if
        # a stale V7 link happens to be malformed.
        try: ingest_foundry_managed_state(settings,campaign_id,payload)
        except Exception: pass
        return JSONResponse(result,headers=_FOUNDRY_CORS)
    except PermissionError as exc:
        return JSONResponse({'detail':str(exc)},status_code=403,headers=_FOUNDRY_CORS)
    except Exception:
        # Keep CORS headers even on a bridge-side server failure so Foundry can
        # report the HTTP status instead of masking it as a generic CORS error.
        return JSONResponse({'detail':'Seeker could not store the Foundry bridge state.'},status_code=500,headers=_FOUNDRY_CORS)


@app.post('/api/v6/foundry/push/{campaign_id}/ack')
def v61_foundry_push_ack(campaign_id:int,token:str='',payload:dict=Body(...)):
    try:
        rows=payload.get('results') if isinstance(payload.get('results'),list) else []
        result=complete_foundry_commands(settings,campaign_id,token,rows)
        try: result['v7_links']=ingest_foundry_command_results(settings,campaign_id,rows)
        except Exception: result['v7_links']=0
        return JSONResponse(result,headers=_FOUNDRY_CORS)
    except PermissionError as exc:
        return JSONResponse({'detail':str(exc)},status_code=403,headers=_FOUNDRY_CORS)
    except Exception:
        return JSONResponse({'detail':'Seeker could not acknowledge the Foundry action results.'},status_code=500,headers=_FOUNDRY_CORS)


@app.post('/api/v6/foundry/push/{campaign_id}/commands')
def v614_foundry_commands(campaign_id:int,token:str=''):
    """Tiny command-only poll so Seeker → Foundry actions feel immediate.

    The regular actor snapshot remains low-frequency; a visible GM client only
    checks this lightweight endpoint for queued actions.
    """
    try:
        return JSONResponse({'commands':claim_foundry_commands(settings,campaign_id,token,limit=25)},headers=_FOUNDRY_CORS)
    except PermissionError as exc:
        return JSONResponse({'detail':str(exc)},status_code=403,headers=_FOUNDRY_CORS)
    except Exception:
        return JSONResponse({'detail':'Seeker could not read the Foundry action queue.'},status_code=500,headers=_FOUNDRY_CORS)


@app.get('/api/v6/foundry/state')
def v6_foundry_state(request:Request):
    require_gm(request);return foundry_state(settings,_active_campaign_id(request))


@app.get('/foundry/seeker-bridge/module.json')
def v61_foundry_manifest(request:Request):
    data=foundry_manifest(settings,_external_base_url(request))
    return JSONResponse(data,headers={'Cache-Control':'no-cache','Access-Control-Allow-Origin':'*'})


@app.get('/foundry/seeker-bridge/seeker-bridge.zip')
def v61_foundry_public_module(request:Request):
    source=settings.root_dir/'integrations'/'foundry-seeker-bridge'
    if not source.exists():raise HTTPException(404,'Foundry bridge module is not included in this build.')
    out=settings.build_dir/'seeker-foundry-bridge-1.6.0.zip'
    build_foundry_module_zip(settings,_external_base_url(request),out)
    return FileResponse(out,filename='seeker-foundry-bridge.zip',media_type='application/zip',headers={'Cache-Control':'public, max-age=300','Access-Control-Allow-Origin':'*'})


@app.get('/api/v6/foundry/module.zip')
def v6_foundry_module(request:Request):
    require_gm(request)
    out=settings.build_dir/'seeker-foundry-bridge-1.6.0.zip'
    build_foundry_module_zip(settings,_external_base_url(request),out)
    return FileResponse(out,filename='seeker-foundry-bridge.zip',media_type='application/zip')


@app.get('/api/v61/foundry/actors')
def v61_foundry_actors(request:Request,campaign_id:int|None=None):
    if not player_allowed(request):raise HTTPException(401)
    cid=resolve_campaign_id(settings,campaign_id if campaign_id is not None else _active_campaign_id(request))
    if not is_gm(request):
        iid=_invite_id(request)
        if iid is None or not invite_has_campaign(settings,iid,cid):raise HTTPException(403,'You are not a member of that campaign.')
    rows=foundry_actors(settings,cid)
    return [{k:v for k,v in r.items() if k!='sheet'} for r in rows]


@app.get('/api/v61/foundry/workshop')
def v61_foundry_workshop_state(request:Request):
    require_gm(request)
    cid=_active_campaign_id(request)
    return {
        'foundry':foundry_state(settings,cid),
        'actors':[{k:v for k,v in r.items() if k!='sheet'} for r in foundry_actors(settings,cid)],
        'prepared_content':list_foundry_prepared_content(settings,cid),
        'commands':recent_foundry_commands(settings,cid),
    }


@app.post('/api/v61/foundry/content')
def v61_foundry_content_save(request:Request,payload:dict=Body(...)):
    require_gm(request)
    cid=_active_campaign_id(request)
    try:
        out=save_foundry_prepared_content(settings,cid,payload)
        _prune_unused_foundry_images(cid)
        return out
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v61/foundry/content/{item_id}')
def v61_foundry_content_delete(request:Request,item_id:int):
    require_gm(request);cid=_active_campaign_id(request);delete_foundry_prepared_content(settings,cid,item_id);_prune_unused_foundry_images(cid);return {'ok':True}


@app.post('/api/v61/foundry/content/{item_id}/push')
def v61_foundry_content_push(request:Request,item_id:int,payload:dict=Body(...)):
    require_gm(request)
    cid=_active_campaign_id(request)
    item=next((x for x in list_foundry_prepared_content(settings,cid) if int(x.get('id') or 0)==int(item_id)),None)
    if not item: raise HTTPException(404,'Prepared content not found.')
    target_type=str(payload.get('target_type') or item.get('target_type') or 'world').lower()
    actor_id=str(payload.get('actor_id') or '').strip()
    if target_type not in {'world','actor'}: raise HTTPException(400,'target_type must be world or actor.')
    if target_type=='actor' and not actor_id: raise HTTPException(400,'Choose a target actor.')
    content_data=json.loads(json.dumps(item.get('payload') or {}))
    for image_key in ('img','token_img'):
        if content_data.get(image_key):content_data[image_key]=_foundry_push_asset_url(request,cid,str(content_data.get(image_key)))
    command=queue_foundry_command(settings,cid,'grant_prepared_content' if target_type=='actor' else 'push_prepared_content',{
        'prepared_id':int(item['id']),
        'prepared_kind':item.get('kind'),
        'title':item.get('title'),
        'subtitle':item.get('subtitle'),
        'summary':item.get('summary'),
        'tags':item.get('tags'),
        'target_type':target_type,
        'data':content_data,
    },actor_id=actor_id,scope=target_type,requested_by=requester_label(request))
    return {'ok':True,'command':command}


@app.post('/api/v61/characters/{character_id}/foundry/action')
def v61_character_foundry_action(request:Request,character_id:int,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    char=_character_owned(request,character_id)
    link=foundry_link_for_character(settings,character_id)
    if not link or not link.get('actor_id'): raise HTTPException(400,'This character is not linked to a Foundry actor.')
    action=str(payload.get('action') or '').strip().lower()
    if action=='adjust_resource':
        resource=str(payload.get('resource') or '').strip().lower()
        if resource not in {'hp','temp_hp','hero_points','focus'}: raise HTTPException(400,'Unsupported resource.')
        try: delta=max(-999,min(999,int(payload.get('delta') or 0)))
        except Exception: raise HTTPException(400,'delta must be an integer.')
        if delta==0: raise HTTPException(400,'delta cannot be zero.')
        command=queue_foundry_command(settings,int(link['campaign_id']),'adjust_resource',{'resource':resource,'delta':delta,'character_id':int(character_id),'character_name':char.get('name')},actor_id=str(link['actor_id']),requested_by=requester_label(request))
    elif action=='adjust_item_quantity':
        item_id=str(payload.get('item_id') or '').strip();
        if not item_id: raise HTTPException(400,'item_id is required.')
        try: delta=max(-99,min(99,int(payload.get('delta') or 0)))
        except Exception: raise HTTPException(400,'delta must be an integer.')
        if delta==0: raise HTTPException(400,'delta cannot be zero.')
        command=queue_foundry_command(settings,int(link['campaign_id']),'adjust_item_quantity',{'item_id':item_id,'delta':delta,'character_id':int(character_id),'character_name':char.get('name')},actor_id=str(link['actor_id']),requested_by=requester_label(request))
    else:
        raise HTTPException(400,'Unsupported Foundry action.')
    return {'ok':True,'command':command}


@app.put('/api/v61/characters/{character_id}/foundry-link')
def v61_character_foundry_link(request:Request,character_id:int,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    iid=_invite_id(request);admin=is_gm(request)
    char=get_player_character(settings,character_id,invite_id=iid,admin=admin,campaign_id=None)
    if not char:raise HTTPException(404,'Character not found.')
    if not admin and int(char.get('invite_id') or 0)!=int(iid or -1):raise HTTPException(403,'You can only link your own character.')
    try:return foundry_link(settings,character_id,int(char['campaign_id']),payload.get('actor_id')) or {'ok':True,'actor_id':''}
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.get('/calendar-feed/{campaign_id}/{token}.ics')
def v6_calendar_feed(request:Request,campaign_id:int,token:str):
    try:data=calendar_feed(settings,campaign_id,token,_external_base_url(request))
    except PermissionError as exc:raise HTTPException(404,str(exc))
    return Response(data,media_type='text/calendar; charset=utf-8',headers={'Content-Disposition':'inline; filename="seeker-campaign.ics"','Cache-Control':'no-cache'})


@app.get('/api/v6/sessions/{session_id}.ics')
def v6_session_ics(request:Request,session_id:int):
    if not player_allowed(request):raise HTTPException(401)
    cid=_active_campaign_id(request);session=next((s for s in list_sessions(settings,campaign_id=cid) if int(s['id'])==int(session_id)),None)
    if not session:raise HTTPException(404,'Session not found.')
    try:data=session_ics(session,(get_campaign(settings,cid) or {}).get('name','Seeker'),_external_base_url(request))
    except ValueError as exc:raise HTTPException(400,str(exc))
    return Response(data,media_type='text/calendar; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="seeker-session-{session_id}.ics"'})


@app.get('/api/v6/lore/{slug}/revisions')
def v6_lore_revisions(request:Request,slug:str):
    require_gm(request);sync_lore_revisions(settings,ensure_built());return lore_revisions(settings,slug)


@app.get('/api/v6/lore/{slug}/revisions/{revision_id}/diff')
def v6_lore_revision_diff(request:Request,slug:str,revision_id:int):
    require_gm(request)
    try:return lore_revision_diff(settings,slug,revision_id)
    except ValueError as exc:raise HTTPException(404,str(exc))


@app.post('/api/v6/lore/revisions/{revision_id}/restore')
def v6_lore_restore(request:Request,revision_id:int):
    require_admin(request)
    try:
        create_snapshot(settings,'Automatic checkpoint before lore restore')
        result=restore_lore_source_revision(settings,revision_id);build_wiki(settings);sync_lore_revisions(settings,ensure_built());return result
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.get('/api/v6/knowledge-matrix')
def v6_knowledge_matrix(request:Request):
    require_gm(request);return knowledge_matrix(settings)


@app.post('/api/v6/converge')
def v6_converge(request:Request,payload:dict=Body(...)):
    require_gm(request)
    try:
        create_snapshot(settings,'Automatic checkpoint before campaign convergence')
        return converge_campaigns(settings,int(payload.get('target_campaign_id') or _active_campaign_id(request)),payload.get('source_campaign_ids') or [],payload.get('options') or {})
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.get('/api/v6/changes')
def v6_changes(request:Request):
    require_gm(request);return changes_since_last_session(settings,_active_campaign_id(request))


@app.get('/api/v6/continuity')
def v6_continuity(request:Request):
    require_gm(request);wiki=_visible_wiki(request);extra=continuity_v6(settings,_active_campaign_id(request),wiki);base=continuity_report(settings,wiki);issues=base.get('issues',[])+extra.get('issues',[]);return {'issues':issues,'count':len(issues)}


@app.post('/api/v6/checkpoint')
def v6_checkpoint(request:Request,payload:dict=Body(default={})):
    require_gm(request);return create_snapshot(settings,str(payload.get('label') or 'V6 checkpoint'))


@app.post('/api/v6/undo-latest')
def v6_undo_latest(request:Request):
    require_admin(request);rows=list_snapshots(settings)
    if not rows:raise HTTPException(404,'No campaign checkpoint exists yet.')
    latest=rows[0];safety=create_snapshot(settings,'Safety backup before undo')
    result=restore_snapshot(settings,latest['path']);result['restored_snapshot']=latest;result['safety_snapshot']=safety;return result


@app.get('/api/v6/commands')
def v6_commands(request:Request,q:str=''):
    if not player_allowed(request):raise HTTPException(401)
    return command_rows(settings,q,_active_campaign_id(request),gm=is_gm(request),wiki=_visible_wiki(request))


@app.post('/api/v6/commands/action')
def v6_command_action(request:Request,payload:dict=Body(...)):
    require_gm(request);kind=str(payload.get('kind') or '');cid=_active_campaign_id(request)
    if kind=='advance_clock':
        row=next((x for x in list_clocks(settings,cid,include_done=True) if int(x['id'])==int(payload.get('id') or 0)),None)
        if not row:raise HTTPException(404,'Clock not found.')
        return save_clock(settings,cid,{**row,'current_segments':min(int(row.get('total_segments') or 6),int(row.get('current_segments') or 0)+1)})
    if kind=='reveal_page':
        slug=str(payload.get('slug') or '')
        return set_reveal(settings,{'campaign_id':cid,'target_type':'page','target_key':slug,'state':'discovered'})
    raise HTTPException(400,'Unknown command action.')


@app.get('/api/v6/maps/{map_id}/annotations')
def v6_map_annotations(request:Request,map_id:int):
    if not player_allowed(request):raise HTTPException(401)
    return list_map_annotations(settings,_active_campaign_id(request),map_id,_invite_id(request),admin=is_gm(request))


@app.post('/api/v6/maps/{map_id}/annotations')
def v6_map_annotation_save(request:Request,map_id:int,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    invite=current_player_invite(request);label=('GM' if is_gm(request) else str((invite or {}).get('label') or 'Player'))
    try:return save_map_annotation(settings,_active_campaign_id(request),map_id,_invite_id(request),label,payload,admin=is_gm(request))
    except (ValueError,PermissionError) as exc:raise HTTPException(400 if isinstance(exc,ValueError) else 403,str(exc))


@app.delete('/api/v6/map-annotations/{annotation_id}')
def v6_map_annotation_delete(request:Request,annotation_id:int):
    if not player_allowed(request):raise HTTPException(401)
    try:delete_map_annotation(settings,annotation_id,_invite_id(request),admin=is_gm(request));return {'ok':True}
    except PermissionError as exc:raise HTTPException(403,str(exc))


@app.get('/api/v6/maps/{map_id}/travel-history')
def v6_travel_history(request:Request,map_id:int):
    if not player_allowed(request):raise HTTPException(401)
    return travel_legs(settings,_active_campaign_id(request),map_id)


@app.post('/api/v6/maps/{map_id}/travel-history')
def v6_travel_save(request:Request,map_id:int,payload:dict=Body(...)):
    require_gm(request)
    try:return record_travel_leg(settings,_active_campaign_id(request),map_id,payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v6/travel-history/{leg_id}')
def v6_travel_delete(request:Request,leg_id:int):
    require_gm(request);delete_travel_leg(settings,leg_id);return {'ok':True}


@app.get('/api/v6/media/{session_id}')
def v6_media_list(request:Request,session_id:int):
    require_gm(request);return list_media_items(settings,_active_campaign_id(request),session_id)


@app.post('/api/v6/media/{session_id}')
def v6_media_save(request:Request,session_id:int,payload:dict=Body(...)):
    require_gm(request)
    try:return save_media_item(settings,_active_campaign_id(request),session_id,payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v6/media-item/{item_id}')
def v6_media_delete(request:Request,item_id:int):
    require_gm(request);delete_media_item(settings,item_id);return {'ok':True}


@app.post('/api/v6/media/{session_id}/upload')
async def v6_media_upload(request:Request,session_id:int,file:UploadFile=File(...),title:str=Form('')):
    require_gm(request);suffix=Path(file.filename or '').suffix.lower()
    if suffix not in {'.png','.jpg','.jpeg','.webp','.gif','.mp4','.webm','.mp3','.ogg','.pdf'}:raise HTTPException(400,'Unsupported media type.')
    folder=settings.uploads_dir/'session-media';folder.mkdir(parents=True,exist_ok=True)
    name=f"{int(time.time())}-{secrets.token_hex(4)}{suffix}";target=folder/name
    await _stream_upload(file,target,150*1024*1024,'Session media is limited to 150 MB.')
    kind='image' if suffix in {'.png','.jpg','.jpeg','.webp','.gif'} else ('video' if suffix in {'.mp4','.webm'} else ('audio' if suffix in {'.mp3','.ogg'} else 'document'))
    return save_media_item(settings,_active_campaign_id(request),session_id,{'title':title or Path(file.filename or name).stem,'kind':kind,'source_url':'/uploads/session-media/'+name})


@app.get('/api/v6/display/{campaign_id}')
def v6_display_state(request:Request,campaign_id:int,token:str=''):
    if player_allowed(request):
        if not is_gm(request) and not invite_has_campaign(settings,int(_invite_id(request) or 0),int(campaign_id)):raise HTTPException(403)
    else:
        cfg=integration_config(settings,int(campaign_id),include_secret=True)
        if not token or not secrets.compare_digest(str(cfg.get('display_token') or ''),str(token)):
            raise HTTPException(401)
    state=display_state(settings,campaign_id)
    return _display_payload_for_token(state,campaign_id,token if not player_allowed(request) else '')


@app.get('/api/v6/display/{campaign_id}/asset/{item_id}')
def v6_display_asset(campaign_id:int,item_id:int,token:str=''):
    cfg=integration_config(settings,int(campaign_id),include_secret=True)
    if not token or not secrets.compare_digest(str(cfg.get('display_token') or ''),str(token)):
        raise HTTPException(401)
    with connect(settings) as conn:
        row=conn.execute('SELECT source_url FROM session_media_items WHERE id=? AND campaign_id=?',(int(item_id),int(campaign_id))).fetchone()
    if not row:raise HTTPException(404,'Display media not found.')
    source=str(row['source_url'] or '')
    if source.startswith('/uploads/'):
        rel=unquote(source[len('/uploads/'):]);path=(settings.uploads_dir/rel).resolve();base=settings.uploads_dir.resolve()
    elif source.startswith('/project-asset/'):
        rel=unquote(source[len('/project-asset/'):]);path=(settings.project_dir/rel).resolve();base=settings.project_dir.resolve()
    else:raise HTTPException(404,'This media item is not a local Seeker asset.')
    if base not in path.parents or not path.is_file():raise HTTPException(404)
    return FileResponse(path)


@app.post('/api/v6/display')
def v6_display_set(request:Request,payload:dict=Body(...)):
    require_gm(request)
    try:return set_display_state(settings,_active_campaign_id(request),payload)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.get('/api/v6/campaign-archive')
def v6_campaign_archive(request:Request):
    require_gm(request);cid=_active_campaign_id(request);camp=get_campaign(settings,cid) or {'slug':'campaign'}
    out=settings.build_dir/f"seeker-{camp.get('slug','campaign')}-chronicle.zip";campaign_keepsake(settings,cid,out)
    return FileResponse(out,filename=out.name,media_type='application/zip')


@app.get('/api/v6/backups')
def v6_backups(request:Request):
    require_gm(request);return list_backups(settings)


@app.post('/api/v6/backups')
def v6_backup_create(request:Request,payload:dict=Body(default={})):
    require_gm(request);return create_backup(settings,str(payload.get('label') or 'Manual backup'),'manual')


@app.get('/api/v6/backups/{backup_id}/download')
def v6_backup_download(request:Request,backup_id:int):
    require_gm(request);row=next((x for x in list_backups(settings) if int(x['id'])==int(backup_id)),None)
    if not row:raise HTTPException(404,'Backup not found.')
    return FileResponse(row['path'],filename=Path(row['path']).name,media_type='application/zip')


@app.post('/api/v6/backups/{backup_id}/restore')
def v6_backup_restore(request:Request,backup_id:int):
    require_admin(request)
    try:return restore_backup(settings,backup_id)
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.delete('/api/v6/backups/{backup_id}')
def v6_backup_delete(request:Request,backup_id:int):
    require_admin(request);delete_backup(settings,backup_id);return {'ok':True}


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
