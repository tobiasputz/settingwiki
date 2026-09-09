from __future__ import annotations

import copy
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import load_settings
from .latex import analyze_project, build_wiki, choose_main, compile_pdf, compiled_pdf_path, load_wiki
from .maps import create_map, create_marker, delete_map, delete_marker, get_map, list_maps, update_map, update_marker
from .storage import (
    cleanup_legacy_import_artifacts, connect, create_player_invite, delete_player_invite, export_project_zip,
    get_codex_presentation, get_setting, init_db, list_player_invites, list_project_files, list_revisions,
    register_player_device, replace_project_from_zip, reset_player_invite_devices, resolve_player_invite,
    restore_player_invite, restore_revision, revoke_player_invite, rotate_player_invite, safe_project_path,
    save_codex_presentation, save_text_file, seed_project, set_setting, storage_report, validate_player_invite_session,
)
from .features import (
    add_annotation, add_mystery_pin, add_session_update, aliases, apply_reveals_to_html, campaign_health,
    delete_mystery_edge, delete_mystery_pin,
    create_snapshot, delete_session, entity_style, fog_regions, get_live_session, init_feature_db,
    list_annotations, list_bookmarks, list_handouts, list_mysteries, list_relationships, list_reveal_blocks_from_wiki, list_reveal_states,
    list_sessions, list_snapshots, list_timeline, list_timeline_eras, list_variants, log_activity, map_layers, page_relationships,
    recent_updates, reveal_state, restore_snapshot, save_alias, save_entity_style, save_fog_region, save_handout, save_map_layer,
    save_mystery, save_mystery_edge, save_relationship, save_session, save_timeline_event, save_timeline_era, delete_timeline_era,
    save_variant, delete_variant, set_reveal, set_session_lore, toggle_bookmark, travel_between_markers,
    list_player_characters, get_player_character, save_player_character, delete_player_character, add_character_image, delete_character_image,
)

from .living import (
    init_living_db, knowledge_state, set_knowledge, list_knowledge, knowledge_index, knowledge_allows, list_fronts, save_front, advance_front,
    runtime_states, save_runtime_state, relationship_history, save_relationship_history, hierarchies, save_hierarchy_edge,
    map_regions, save_map_region, save_region_history, list_rumors, save_rumor, random_rumor, list_threads, save_thread, add_thread_note, update_thread_note, delete_thread_note, save_thread_link, delete_thread_link,
    list_journals, list_party_journals, save_journal, inbox_items, save_inbox, list_submissions, save_submission, review_submission,
    publishing_state, set_publishing_state, publishing_states, capture_session_state, session_state_snapshots, scan_suggestions, update_suggestion,
    list_media_catalog, save_media_meta, create_notification, list_notifications, mark_notification_read,
    character_relationships, save_character_relationship, character_arcs, save_character_arc, entity_provenance, continuity_report,
    export_foundry_journal, create_portable_archive, validate_portable_archive_file, media_usage, replace_media_reference,
)

settings = load_settings()
init_db(settings)
init_feature_db(settings)
seed_project(settings)

app = FastAPI(title="Loreforge", docs_url=None, redoc_url=None)
_secure_session_cookie = os.getenv("SESSION_COOKIE_SECURE", "1" if os.getenv("RAILWAY_ENVIRONMENT") else "0").lower() in {"1", "true", "yes"}
app.add_middleware(
    SessionMiddleware, secret_key=settings.session_secret, https_only=_secure_session_cookie,
    same_site="lax", max_age=60 * 60 * 24 * 30,
)
app.mount("/static", StaticFiles(directory=settings.root_dir / "static"), name="static")
templates = Jinja2Templates(directory=settings.root_dir / "templates")


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
    return knowledge_allows(settings,_invite_id(request),target_type,str(target_key),default=default)


def player_access_mode() -> str:
    mode = get_setting(settings, "player_access_mode", "invite").strip().lower()
    return mode if mode in {"invite", "password", "public"} else "invite"


def current_player_invite(request: Request) -> dict | None:
    return validate_player_invite_session(
        settings, request.session.get("player_invite_id"), request.session.get("player_invite_version"),
        request.session.get("player_device_id"),
    )


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
        return load_wiki(settings)
    except Exception:
        return {"title": "Loreforge", "tagline": "Import a LaTeX campaign project in /admin.", "categories": [], "pages": [], "generated_at": time.time()}


def _invite_id(request: Request) -> int | None:
    invite = current_player_invite(request)
    return int(invite["id"]) if invite else None


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


def _visible_wiki(request: Request, *, include_hidden_for_admin: bool = True) -> dict:
    wiki = copy.deepcopy(ensure_built())
    admin = is_gm(request)
    invite_id = _invite_id(request)
    visible_pages = []
    allowed_slugs = set()
    for page in wiki.get("pages", []):
        visibility = page.get("presentation", {}).get("visibility", "public")
        page_reveal = reveal_state(settings, "page", page.get("slug", ""), invite_id)
        publish = publishing_state(settings, page.get("slug", ""))
        player_knowledge = knowledge_state(settings, invite_id, "page", page.get("slug", ""))
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
            page["html"] = apply_reveals_to_html(settings, page.get("html", ""), page.get("slug", ""), admin=False, invite_id=invite_id)
            # Regenerate searchable text from the filtered HTML so hidden truth is
            # never leaked by search snippets or hover previews.
            page["plain_text"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page["html"])).strip()
        style = entity_style(settings, page.get("slug", ""))
        style["crest_url"] = _asset_ref_url(style.get("crest_ref", ""))
        style["ambient_audio_url"] = _asset_ref_url(style.get("ambient_audio_ref", ""))
        page["entity_style"] = style
        page["explicit_relationships"] = page_relationships(settings, page.get("slug", ""), admin=admin)
        page["variants"] = list_variants(settings, page.get("slug", ""), admin=admin)
        page["gallery"] = _gallery_from_html(page.get("html", ""))
        visible_pages.append(page)
        allowed_slugs.add(page.get("slug"))
    wiki["pages"] = visible_pages
    clean_categories = []
    for category in wiki.get("categories", []):
        category["pages"] = [p for p in category.get("pages", []) if p.get("slug") in allowed_slugs]
        if category["pages"]:
            clean_categories.append(category)
    wiki["categories"] = clean_categories
    # Explicit semantic edges are spoiler-safe too: relationships to hidden
    # entries are removed rather than exposing a secret slug/title indirectly.
    if not admin:
        for page in visible_pages:
            page["explicit_relationships"] = [
                r for r in page.get("explicit_relationships", [])
                if r.get("source_slug") in allowed_slugs and r.get("target_slug") in allowed_slugs
            ]
    wiki["aliases"] = aliases(settings)
    wiki["live_session"] = get_live_session(settings, invite_id=invite_id, admin=admin)
    active_invite=current_player_invite(request) if not admin else None
    wiki["player_label"] = (active_invite or {}).get("label", "") if not admin else ("Co-GM" if is_co_gm(request) else "GM")
    wiki["gm_view"] = admin
    # Used only to segregate browser-local/offline state when the same device is
    # handed from one invitation to another. It is not an authentication token.
    wiki["player_access_key"] = (f"invite:{active_invite.get('id')}:{active_invite.get('access_version')}" if active_invite else ("admin" if admin else player_access_mode()))
    return wiki


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
        if list(settings.project_dir.rglob("*.tex")):
            build_wiki(settings)
            if os.getenv("COMPILE_ON_START", "1").lower() in {"1", "true", "yes"}:
                compile_pdf(settings)
    except Exception as exc:
        print(f"Loreforge startup build warning: {exc}", flush=True)


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
    return templates.TemplateResponse("login.html", {"request": request, "mode": "admin", "title": "Loreforge Editor"})


@app.post("/admin/login")
def admin_login(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, settings.admin_password):
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "mode": "admin", "error": "Wrong password.", "title": "Loreforge Editor"}, status_code=401)


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear(); return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); maps = list_maps(settings, public=True)
    featured = [p for p in wiki.get("pages", []) if p.get("presentation", {}).get("featured")][:6]
    iid=_invite_id(request); gm=is_gm(request); updates=recent_updates(settings,iid,6,admin=gm);live=get_live_session(settings,invite_id=iid,admin=gm)
    if not gm:
        allowed={p.get("slug") for p in wiki.get("pages",[])}
        updates=[u for u in updates if u.get("target_type")!="lore" or not u.get("target_key") or u.get("target_key") in allowed]
    home_threads=list_threads(settings,admin=gm,invite_id=iid)[:5]
    home_chars=list_player_characters(settings,invite_id=iid,admin=gm)[:5]
    home_fronts=list_fronts(settings,admin=gm,invite_id=iid)[:4]
    home_notifications=list_notifications(settings,iid,admin=gm)[:6]
    return templates.TemplateResponse("home.html", {"request": request, "wiki": wiki, "maps": maps, "featured": featured,"updates":updates,"live_session":live,"mysteries":list_mysteries(settings,admin=gm)[:4],"threads":home_threads,"characters":home_chars,"fronts":home_fronts,"notifications":home_notifications,"calendar":_calendar_config()})


@app.get("/wiki/{slug}", response_class=HTMLResponse)
def wiki_page(request: Request, slug: str):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); pages = wiki.get("pages", [])
    page = next((p for p in pages if p["slug"] == slug), None)
    if not page:
        alias_target=aliases(settings).get(unquote(slug).casefold())
        if alias_target and any(p.get("slug")==alias_target for p in pages): return RedirectResponse(f"/wiki/{alias_target}",status_code=302)
        raise HTTPException(404, "Wiki page not found")
    idx = pages.index(page)
    prev_page = pages[idx-1] if idx > 0 else None
    next_page = pages[idx+1] if idx + 1 < len(pages) else None
    page_locked = (not is_gm(request) and page.get("presentation", {}).get("visibility") == "teaser")
    all_maps=list_maps(settings,public=not is_gm(request)); map_locations=[]
    for m in all_maps:
        for marker in m.get("markers",[]):
            if marker.get("page_slug")==slug: map_locations.append({"map":m,"marker":marker})
    appearances=[]
    for sess in list_sessions(settings,public=not is_gm(request),invite_id=_invite_id(request)):
        if any(x.get("page_slug")==slug for x in sess.get("lore",[])): appearances.append(sess)
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
            "page_locked": page_locked, "admin_view": is_gm(request),"maps":all_maps,"map_locations":map_locations,"appearances":appearances,
            "runtime_state": next((x for x in runtime_states(settings,admin=is_gm(request)) if x.get("page_slug")==slug),None),"provenance":entity_provenance(settings,slug),
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
    map_data["fog_regions"] = fog_regions(settings, int(map_data["id"]), public=True)
    if not is_gm(request):
        map_data["markers"]=[m for m in map_data.get("markers",[]) if knowledge_visible(request,"map_marker",f"{map_data['id']}:{m.get('id')}")[0]]
    map_data["regions"] = map_regions(settings, int(map_data["id"]), admin=is_gm(request))
    if not is_gm(request):
        map_data["regions"]=[r for r in map_data["regions"] if knowledge_visible(request,"map_region",str(r.get('id')))[0]]
    map_data["history_min"] = min([float(h.get("start_sort")) for r in map_data["regions"] for h in r.get("history",[]) if h.get("start_sort") is not None], default=0)
    map_data["history_max"] = max([float(h.get("end_sort") if h.get("end_sort") is not None else h.get("start_sort")) for r in map_data["regions"] for h in r.get("history",[]) if h.get("start_sort") is not None], default=0)
    map_data["world_width"] = float(get_setting(settings,"world_width","1000") or 1000)
    map_data["travel_speed"] = float(get_setting(settings,"travel_speed","40") or 40)
    return templates.TemplateResponse("map.html", {"request": request, "wiki": wiki, "map": map_data, "maps": list_maps(settings,public=True)})


@app.get("/api/public/search")
def public_search(request: Request, q: str = ""):
    if not player_allowed(request): raise HTTPException(401)
    qn = q.strip().lower()
    if not qn: return []
    wiki = _visible_wiki(request)
    alias_map = aliases(settings)
    ranked=[]
    # Aliases and redirects resolve fantasy titles, old spellings, epithets, and
    # hidden true names to the same canonical entry without duplicate pages.
    for alias, target in alias_map.items():
        if qn in alias or alias in qn:
            p = next((x for x in wiki.get("pages",[]) if x.get("slug")==target), None)
            if p:
                ranked.append((88 if qn==alias else 42,{"type":"alias","href":f"/wiki/{p['slug']}","slug":p["slug"],"title":p["title"],"chapter":p.get("chapter"),"excerpt":f"Also known as {alias}. {p.get('excerpt','')}"}))
    for p in wiki.get("pages", []):
        visibility = p.get("presentation", {}).get("visibility", "public")
        title=p["title"].lower()
        text=(p.get("excerpt", "") if visibility == "teaser" else p.get("plain_text", "")).lower()
        score=0
        if qn == title: score += 100
        else:
            try:
                import difflib
                ratio=difflib.SequenceMatcher(None,qn,title).ratio()
                if ratio>=0.72: score += int(ratio*24)
            except Exception:
                pass
        if qn in title: score += 30
        score += min(10, text.count(qn))
        if all(term in text or term in title for term in qn.split()): score += 5
        if score:
            ranked.append((score, {"type":"lore","href":f"/wiki/{p['slug']}","slug":p["slug"],"title":p["title"],"chapter":p.get("chapter"),"excerpt":p.get("excerpt","")}))
    # Player-owned character dossiers participate in the same command/search
    # palette as campaign lore. Private characters are returned only to their
    # owner (and the GM) by list_player_characters.
    for character in list_player_characters(settings, invite_id=_invite_id(request), admin=is_gm(request)):
        title=(character.get("name") or "").lower(); body=" ".join(str(character.get(k) or "") for k in ("summary","biography","goals","ancestry","class_name")).lower(); score=0
        if qn==title: score+=100
        if qn in title: score+=34
        score+=min(9,body.count(qn))
        if score:
            ranked.append((score,{"type":"character","href":f"/characters/{character['id']}","title":character.get("name") or "Character","chapter":"Player Characters","excerpt":character.get("summary") or " · ".join(x for x in (character.get("ancestry"),character.get("class_name")) if x)}))

    for map_data in list_maps(settings, public=True):
        map_title = (map_data.get("name") or "").lower()
        map_desc = (map_data.get("description") or "").lower()
        score = (35 if qn in map_title else 0) + min(6, map_desc.count(qn))
        if score:
            ranked.append((score, {"type":"map","href":f"/atlas/{map_data['slug']}","title":map_data["name"],"chapter":"Atlas","excerpt":map_data.get("description","")}))
        for marker in map_data.get("markers", []):
            title = (marker.get("title") or "").lower(); body=(marker.get("body") or "").lower(); score=0
            if qn == title: score += 90
            if qn in title: score += 28
            score += min(8, body.count(qn))
            if score:
                ranked.append((score,{"type":"location","href":f"/atlas/{map_data['slug']}?focus={marker['id']}","title":marker.get("title","Location"),"chapter":map_data["name"],"excerpt":marker.get("body","")}))
    ranked.sort(key=lambda x:(-x[0],x[1]["title"]))
    return [item for _,item in ranked[:24]]


@app.get("/manifest.webmanifest")
def web_manifest(request: Request):
    wiki = ensure_built()
    payload = {
        "name": wiki.get("title", "Loreforge Campaign Atlas"),
        "short_name": "Loreforge",
        "description": wiki.get("tagline", "A living campaign atlas."),
        "start_url": "/?source=pwa",
        "scope": "/",
        "display": "standalone",
        "background_color": "#0b0c0b",
        "theme_color": "#17130f",
        "orientation": "any",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/loreforge-icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}
        ],
        "shortcuts": [
            {"name": "Session", "url": "/session", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]},
            {"name": "Codex", "url": "/#codex", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]},
            {"name": "History", "url": "/timeline", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]},
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
    wiki = _visible_wiki(request); maps = list_maps(settings, public=True); iid=_invite_id(request); live = get_live_session(settings,invite_id=iid,admin=is_gm(request))
    by_slug = {p["slug"]: p for p in wiki.get("pages", [])}
    if live:
        live["lore_pages"] = [by_slug[x["page_slug"]] for x in live.get("lore", []) if x.get("page_slug") in by_slug]
        live["spotlight_map"] = next((m for m in maps if m.get("slug") == live.get("spotlight_map_slug")), None)
    invite = current_player_invite(request)
    notes = []
    history=[x for x in list_sessions(settings,public=True,invite_id=iid) if x.get("status")=="ended"][-12:]
    if not is_gm(request):
        allowed={p.get("slug") for p in wiki.get("pages",[])}
        if live: live["lore"]=[x for x in live.get("lore",[]) if x.get("page_slug") in allowed]
        for row in history: row["lore"]=[x for x in row.get("lore",[]) if x.get("page_slug") in allowed]
    mysteries=list_mysteries(settings, admin=is_gm(request))[:6]
    if not is_gm(request):
        allowed={p.get("slug") for p in wiki.get("pages",[])}
        for mystery in mysteries:
            mystery["pins"]=[x for x in mystery.get("pins",[]) if not x.get("page_slug") or x.get("page_slug") in allowed]
            pin_ids={x.get("id") for x in mystery["pins"]}
            mystery["edges"]=[e for e in mystery.get("edges",[]) if e.get("source_pin") in pin_ids and e.get("target_pin") in pin_ids]
    can_author = is_gm(request) or (not archive_mode() and bool(current_player_invite(request)) and player_role(request) == "player")
    session_characters,active_character,character_selection_made=_session_character_context(request,live)
    journal_character_filter=None
    if not is_gm(request) and character_selection_made:
        journal_character_filter=int((active_character or {}).get("id") or 0)
    party_journals=list_party_journals(settings,iid,admin=is_gm(request),character_id=journal_character_filter)
    return templates.TemplateResponse("session.html", {
        "request": request, "wiki": wiki, "maps": maps, "session": live, "player": invite,
        "updates": recent_updates(settings, iid, 12,admin=is_gm(request)), "mysteries": mysteries,
        "session_history":list(reversed(history)),"calendar":_calendar_config(),
        "threads":list_threads(settings,admin=is_gm(request),invite_id=iid),"party_journals":party_journals,
        "gm_view":is_gm(request),"can_author":can_author,"archive_mode":archive_mode(),
        "session_characters":session_characters,"active_character":active_character,
        "character_selection_made":character_selection_made,
    })


@app.post("/api/player/session-character")
def player_session_character(request:Request,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    if is_gm(request): raise HTTPException(403,"GM view does not use a player character identity.")
    iid=_invite_id(request)
    if iid is None: raise HTTPException(403,"A personal invitation is required to choose a session character.")
    live=get_live_session(settings,invite_id=iid,admin=False);session_key=int((live or {}).get("id") or 0)
    requested=payload.get("character_id")
    if requested in (None,"",0,"0"):
        request.session["session_character_id"]=0;request.session["session_character_session_id"]=session_key
        return {"ok":True,"character":None,"session_id":session_key}
    try: cid=int(requested)
    except (TypeError,ValueError): raise HTTPException(400,"Invalid character.")
    char=get_player_character(settings,cid,invite_id=iid,admin=False)
    if not char or int(char.get("invite_id") or -1)!=int(iid): raise HTTPException(403,"You can only enter a session as one of your own characters.")
    request.session["session_character_id"]=cid;request.session["session_character_session_id"]=session_key
    return {"ok":True,"character":{"id":cid,"name":char.get("name"),"portrait_url":char.get("portrait_url","")},"session_id":session_key}


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True)
    events=list_timeline(settings,admin=is_gm(request),historical_only=True)
    eras=list_timeline_eras(settings,admin=is_gm(request))
    if not is_gm(request):
        events=[e for e in events if knowledge_visible(request,"timeline_event",str(e.get('id')))[0]]
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
    updates=recent_updates(settings,_invite_id(request),100,admin=is_gm(request))
    if not is_gm(request): updates=[u for u in updates if u.get("target_type")!="lore" or not u.get("target_key") or u.get("target_key") in allowed]
    return templates.TemplateResponse("updates.html", {"request":request,"wiki":wiki,"maps":maps,"updates":updates,"sessions":list_sessions(settings,public=True,invite_id=_invite_id(request))})


@app.get("/mysteries", response_class=HTMLResponse)
def mysteries_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); rows=list_mysteries(settings,admin=is_gm(request))
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
    rows=list_handouts(settings,admin=is_gm(request)); allowed={p.get("slug") for p in wiki.get("pages",[])}
    for h in rows:
        h["image_url"]=_asset_ref_url(h.get("image_ref",""))
        if not is_gm(request) and h.get("page_slug") not in allowed: h["page_slug"]=None
    return templates.TemplateResponse("handouts.html", {"request":request,"wiki":wiki,"maps":maps,"handouts":rows})


@app.get("/handout/{slug}", response_class=HTMLResponse)
def handout_page(request: Request, slug: str):
    if not player_allowed(request): return player_gate_redirect(request)
    row=next((x for x in list_handouts(settings,admin=is_gm(request)) if x["slug"]==slug),None)
    if not row: raise HTTPException(404,"Handout not found")
    row["image_url"]=_asset_ref_url(row.get("image_ref","")); wiki=_visible_wiki(request); maps=list_maps(settings,public=True)
    if not is_admin(request) and row.get("page_slug") not in {p.get("slug") for p in wiki.get("pages",[])}: row["page_slug"]=None
    return templates.TemplateResponse("handout.html", {"request":request,"wiki":wiki,"maps":maps,"handout":row,"admin_view":is_gm(request)})


@app.get("/api/public/session-pulse")
def public_session_pulse(request: Request):
    if not player_allowed(request): raise HTTPException(401)
    iid=_invite_id(request); admin=is_gm(request); live=get_live_session(settings,invite_id=iid,admin=admin)
    visible_updates=recent_updates(settings,iid,1,admin=admin); u=visible_updates[0].get("created_at",0) if visible_updates else 0
    reveal_rows=list_reveal_states(settings)
    if not admin:
        def audience_ok(row):
            try: audience=json.loads(row.get("audience_json") or "[]")
            except Exception: audience=[]
            return not audience or (iid is not None and int(iid) in {int(x) for x in audience})
        reveal_rows=[x for x in reveal_rows if audience_ok(x)]
    r=max([float(x.get("updated_at") or 0) for x in reveal_rows],default=0)
    with connect(settings) as conn: h=conn.execute("SELECT MAX(updated_at) FROM handouts WHERE visibility!='gm'").fetchone()[0] or 0
    return {"session_id":live.get("id") if live else None,"session_updated":live.get("updated_at",0) if live else 0,"latest_update":u,"latest_reveal":r,"latest_handout":h}


@app.get("/api/public/page-card/{slug}")
def page_card(request: Request, slug: str):
    if not player_allowed(request): raise HTTPException(401)
    wiki=_visible_wiki(request); p=next((x for x in wiki.get("pages",[]) if x["slug"]==slug),None)
    if not p: raise HTTPException(404)
    return {"slug":p["slug"],"title":p["title"],"chapter":p.get("chapter"),"excerpt":p.get("excerpt","")[:300],"image":p.get("presentation",{}).get("hero_image_url") or p.get("presentation",{}).get("auto_image_url") or p.get("entity_style",{}).get("crest_url","") ,"relationships":p.get("explicit_relationships",[])[:4]}


@app.get("/api/public/annotations/{slug}")
def public_annotations(request: Request, slug: str):
    if not player_allowed(request): raise HTTPException(401)
    return list_annotations(settings,slug,invite_id=_invite_id(request),admin=is_gm(request))


@app.post("/api/public/annotations")
def public_add_annotation(request: Request,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    invite=current_player_invite(request); label="GM" if is_gm(request) else (invite or {}).get("label","Player")
    return add_annotation(settings,payload,invite_id=_invite_id(request),author_label=label,admin=is_gm(request))


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
    target=str(request.base_url).rstrip("/")+path
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
    wiki=_visible_wiki(request); maps=list_maps(settings,public=False); live=get_live_session(settings,admin=True)
    chars=list_player_characters(settings,admin=True)
    for c in chars:c["arcs"]=character_arcs(settings,int(c["id"]),owner=True)
    return templates.TemplateResponse("gm_session.html", {"request":request,"wiki":wiki,"maps":maps,"session":live,"sessions":list_sessions(settings),"reveals":list_reveal_blocks_from_wiki(ensure_built()),"mysteries":list_mysteries(settings,admin=True),"handouts":list_handouts(settings,admin=True),"updates":recent_updates(settings,None,20,admin=True),"fronts":list_fronts(settings,admin=True),"characters":chars,"rumors":list_rumors(settings,admin=True)})


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
    chars=list_player_characters(settings,invite_id=iid,admin=admin_view)
    return templates.TemplateResponse("characters.html",{"request":request,"wiki":wiki,"maps":maps,"characters":chars,"player":current_player_invite(request),"admin_view":admin_view})

@app.get("/characters/{character_id}", response_class=HTMLResponse)
def character_page(request: Request, character_id:int):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); iid=_invite_id(request); admin_view=is_gm(request)
    char=get_player_character(settings,character_id,invite_id=iid,admin=admin_view)
    if not char: raise HTTPException(404,"Character not found")
    owner=admin_view or (iid is not None and int(char.get("invite_id") or 0)==int(iid))
    char["arcs"]=character_arcs(settings,character_id,owner=owner)
    char["relationships"]=character_relationships(settings,character_id,owner=owner)
    can_edit=admin_view or (owner and player_role(request)=="player" and not archive_mode())
    return templates.TemplateResponse("character.html",{"request":request,"wiki":wiki,"maps":maps,"character":char,"can_edit":can_edit,"admin_view":admin_view,"wiki_pages":wiki.get("pages",[])})

@app.get("/api/player/characters")
def player_characters_api(request:Request):
    if not player_allowed(request): raise HTTPException(401)
    return list_player_characters(settings,invite_id=_invite_id(request),admin=is_gm(request))

@app.post("/api/player/characters")
def player_character_create(request:Request,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    require_player_author(request)
    iid=_invite_id(request)
    if not is_gm(request) and iid is None: raise HTTPException(403,"An invitation is required to create a character.")
    try: return save_player_character(settings,payload,invite_id=iid,admin=is_gm(request))
    except PermissionError as exc: raise HTTPException(403,str(exc))
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.put("/api/player/characters/{character_id}")
def player_character_update(request:Request,character_id:int,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    require_player_author(request)
    payload=dict(payload); payload["id"]=character_id
    try: return save_player_character(settings,payload,invite_id=_invite_id(request),admin=is_gm(request))
    except PermissionError as exc: raise HTTPException(403,str(exc))
    except ValueError as exc: raise HTTPException(400,str(exc))

@app.delete("/api/player/characters/{character_id}")
def player_character_delete(request:Request,character_id:int):
    if not player_allowed(request): raise HTTPException(401)
    require_player_author(request)
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
    char=get_player_character(settings,character_id,invite_id=iid,admin=admin_view)
    if not char: raise HTTPException(404,"Character not found")
    if not admin_view and int(char.get("invite_id") or 0)!=int(iid or -1): raise HTTPException(403,"You can only upload art for your own characters.")
    ext=Path(image.filename or "image.jpg").suffix.lower()
    if ext not in {".png",".jpg",".jpeg",".webp",".gif"}: raise HTTPException(400,"Use PNG, JPG, WebP, or GIF images.")
    data=await image.read(15_000_001)
    if len(data)>15_000_000: raise HTTPException(413,"Character images are limited to 15 MB each.")
    owner=int(char.get("invite_id") or 0); folder=settings.uploads_dir/"characters"/str(owner)/str(character_id); folder.mkdir(parents=True,exist_ok=True)
    safe_name=re.sub(r"[^A-Za-z0-9._-]+","-",Path(image.filename or "image").stem).strip("-")[:80] or "image"
    filename=f"{int(time.time()*1000)}-{safe_name}{ext}"; path=folder/filename; path.write_bytes(data)
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
        char=get_player_character(settings,character_id,invite_id=_invite_id(request),admin=is_gm(request))
        if not char: raise HTTPException(404)
        try:
            if int(char.get("invite_id") or 0)!=int(parts[1]): raise HTTPException(404)
        except (TypeError,ValueError): raise HTTPException(404)
    return FileResponse(path)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    if is_co_gm(request): return RedirectResponse("/admin/campaign", status_code=303)
    if not is_admin(request): return RedirectResponse("/admin/login")
    return templates.TemplateResponse("admin.html", {"request": request, "title": "Loreforge Editor"}, headers={"Cache-Control": "no-store"})


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


@app.get("/api/admin/status")
def admin_status(request: Request):
    require_admin(request)
    has_tex=bool(list(settings.project_dir.rglob("*.tex")))
    analysis={}
    error=None
    if has_tex:
        try: analysis=analyze_project(settings)
        except Exception as exc: error=str(exc)
    persistent = (os.getenv("RAILWAY_ENVIRONMENT") is None) or os.path.ismount(str(settings.data_dir)) or os.getenv("LOREFORGE_ASSUME_PERSISTENT", "").lower() in {"1","true","yes"}
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
    try:
        wiki=build_wiki(settings); result=compile_pdf(settings, clean=clean)
        return {"wiki_pages":len(wiki.get("pages",[])), **result.__dict__}
    except Exception as exc:
        raise HTTPException(400,str(exc))


@app.post("/api/admin/rebuild-wiki")
def admin_rebuild(request: Request):
    require_admin(request)
    try:
        wiki=build_wiki(settings); return {"ok":True,"pages":len(wiki.get("pages",[])),"analysis":wiki.get("analysis",{})}
    except Exception as exc: raise HTTPException(400,str(exc))


@app.post("/api/admin/import")
async def admin_import(request: Request, archive: UploadFile = File(...)):
    require_admin(request)
    if not archive.filename or not archive.filename.lower().endswith(".zip"): raise HTTPException(400,"Upload an Overleaf/project .zip archive")
    # Keep the uploaded archive off the persistent /data volume. Railway Free/Trial
    # volumes are small, while the service temp filesystem is intended for scratch I/O.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="loreforge-upload-", suffix=".zip", delete=False) as f:
            tmp_path = Path(f.name)
            uploaded = 0
            while chunk := await archive.read(1024 * 1024):
                uploaded += len(chunk)
                if uploaded > 1_000_000_000:
                    raise HTTPException(413, "Project ZIP is larger than the 1 GB upload safety limit.")
                f.write(chunk)
        import_info = replace_project_from_zip(settings, tmp_path)
        set_setting(settings,"main_file","")
        analysis=analyze_project(settings); wiki=build_wiki(settings); result=compile_pdf(settings)
        return {"ok":True,"analysis":analysis,"wiki_pages":len(wiki.get("pages",[])),"compile":result.__dict__,"import":import_info}
    except HTTPException:
        raise
    except OSError as exc:
        if getattr(exc, "errno", None) == 28:
            raise HTTPException(507, "Persistent storage is full. Loreforge now stages imports outside /data, but your volume itself needs more room. Increase the Railway volume or use Storage cleanup in Project settings.")
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
        folder = settings.project_dir / "Images" / "Loreforge"
        ref_prefix = "project:"
        url_prefix = "/project-asset/Images/Loreforge/"
        ref_path_prefix = "Images/Loreforge/"
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
    with target.open("wb") as f:
        while chunk := await image.read(1024*1024): f.write(chunk)
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

# ---------------------------------------------------------------------------
# Loreforge 2 campaign-runtime APIs
# ---------------------------------------------------------------------------
@app.get("/api/admin/campaign/overview")
def admin_campaign_overview(request: Request):
    require_gm(request)
    wiki=ensure_built(); maps=list_maps(settings,public=False)
    for m in maps:
        m["layers"] = map_layers(settings, int(m["id"]), public=False)
        m["fog_regions"] = fog_regions(settings, int(m["id"]), public=False)
    return {
        "maps":maps,
        "sessions":list_sessions(settings),"timeline":list_timeline(settings,admin=True),"timeline_eras":list_timeline_eras(settings,admin=True),
        "relationships":list_relationships(settings,admin=True),"reveals":list_reveal_blocks_from_wiki(wiki),
        "mysteries":list_mysteries(settings,admin=True),"handouts":list_handouts(settings,admin=True),
        "snapshots":list_snapshots(settings),"health":campaign_health(settings,wiki,maps),
        "reveal_states":list_reveal_states(settings),"recent_updates":recent_updates(settings,None,12,admin=True),
        "calendar":_calendar_config(),
        "aliases":aliases(settings),"invitations":list_player_invites(settings),
        "variants":[v for p in wiki.get("pages",[]) for v in list_variants(settings,p.get("slug",""),admin=True)],
        "entity_styles":{p.get("slug",""):entity_style(settings,p.get("slug","")) for p in wiki.get("pages",[])},
        "assets":_asset_rows(),"media_assets":_media_asset_rows(),
        "player_characters":list_player_characters(settings,admin=True),
    }


@app.post("/api/admin/sessions")
def admin_save_session(request: Request,payload:dict=Body(...)):
    require_gm(request)
    before=None
    if payload.get("id"):
        before=next((x for x in list_sessions(settings) if int(x.get("id"))==int(payload["id"])),None)
    row=save_session(settings,payload)
    # Lightweight knowledge/state checkpoints answer “what did the party know before/after this session?”
    # without duplicating the multi-hundred-megabyte campaign archive.
    if row.get("status")=="live" and (not before or before.get("status")!="live"):
        capture_session_state(settings,int(row["id"]),"before")
    if row.get("status")=="ended" and (not before or before.get("status")!="ended"):
        capture_session_state(settings,int(row["id"]),"after")
    return row


@app.delete("/api/admin/sessions/{session_id}")
def admin_delete_session(request:Request,session_id:int):
    require_gm(request);delete_session(settings,session_id);return {"ok":True}


@app.post("/api/admin/sessions/{session_id}/lore")
def admin_session_lore(request:Request,session_id:int,payload:dict=Body(...)):
    require_gm(request);set_session_lore(settings,session_id,str(payload.get("page_slug") or ""),str(payload.get("role") or "reference"),bool(payload.get("enabled",True)));return {"ok":True}


@app.post("/api/admin/session-updates")
def admin_session_update(request:Request,payload:dict=Body(...)):
    require_gm(request);return add_session_update(settings,payload)


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
    require_gm(request);return save_relationship(settings,payload)


@app.delete("/api/admin/relationships/{relationship_id}")
def admin_relationship_delete(request:Request,relationship_id:int):
    require_gm(request)
    from .storage import connect
    with connect(settings) as conn: conn.execute("DELETE FROM lore_relationships WHERE id=?",(relationship_id,))
    return {"ok":True}


@app.post("/api/admin/reveals")
def admin_reveal_save(request:Request,payload:dict=Body(...)):
    require_gm(request);row=set_reveal(settings,payload)
    if row.get("state") in {"rumor","discovered","public"}:
        title=str(payload.get("title") or payload.get("target_key") or "Lore discovered")
        add_session_update(settings,{"session_id":payload.get("session_id"),"title":title,"body":str(payload.get("update_body") or "New lore has been revealed."),"target_type":payload.get("target_type") or "lore","target_key":payload.get("target_key") or "","visibility":"players","audience":payload.get("audience") or []})
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
    require_gm(request);return save_mystery(settings,payload)


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
    require_gm(request);return save_handout(settings,payload)


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
    result=restore_snapshot(settings,row["path"]);init_db(settings);init_feature_db(settings);build_wiki(settings)
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
    filename=f"{int(time.time())}-{secrets.token_hex(4)}{suffix}";target=folder/filename;size=0
    with target.open("wb") as fh:
        while chunk:=await image.read(1024*1024):
            size+=len(chunk)
            if size>80*1024*1024:
                target.unlink(missing_ok=True);raise HTTPException(413,"Map layer is larger than 80 MB")
            fh.write(chunk)
    return save_map_layer(settings,map_id,{"name":name,"kind":kind,"opacity":opacity,"visible_to_players":visible_to_players,"image_path":f"maps/layers/{filename}"})

# ---------------------------------------------------------------------------
# Loreforge 3 · Living Campaign layer
# ---------------------------------------------------------------------------

def _player_label(request: Request) -> str:
    if is_admin(request): return "GM"
    if is_co_gm(request): return "Co-GM"
    return str((current_player_invite(request) or {}).get("label") or "Player")


def _character_owned(request: Request, character_id: int) -> dict:
    iid=_invite_id(request); char=get_player_character(settings,character_id,invite_id=iid,admin=is_gm(request))
    if not char: raise HTTPException(404,"Character not found")
    if not is_gm(request) and int(char.get("invite_id") or -1)!=int(iid or -2): raise HTTPException(403,"You can only edit your own character.")
    return char


def _own_player_characters(request: Request) -> list[dict]:
    iid=_invite_id(request)
    if iid is None or is_gm(request): return []
    rows=list_player_characters(settings,invite_id=iid,admin=False)
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
    iid=_invite_id(request); gm=is_gm(request); wiki=_visible_wiki(request); maps=list_maps(settings,public=not gm)
    chars=list_player_characters(settings,invite_id=iid,admin=gm)
    for c in chars:
        owner=gm or int(c.get("invite_id") or -1)==int(iid or -2)
        c["arcs"]=character_arcs(settings,int(c["id"]),owner=owner)
        c["relationships"]=character_relationships(settings,int(c["id"]),owner=owner)
    can_author = gm or (not archive_mode() and bool(current_player_invite(request)) and player_role(request) == "player")
    return templates.TemplateResponse("living.html",{
        "request":request,"wiki":wiki,"maps":maps,"gm_view":gm,"player":current_player_invite(request),
        "threads":list_threads(settings,admin=gm,invite_id=iid),"fronts":list_fronts(settings,admin=gm,invite_id=iid),
        "rumors":list_rumors(settings,admin=gm),"journals":([] if iid is None else list_journals(settings,iid,admin=gm)),
        "characters":chars,"notifications":list_notifications(settings,iid,admin=gm),"runtime_states":runtime_states(settings,admin=gm),
        "submissions":list_submissions(settings,invite_id=iid,admin=gm),"calendar":_calendar_config(),"can_author":can_author,"archive_mode":archive_mode(),
        "journal_characters":[c for c in chars if iid is not None and int(c.get("invite_id") or -1)==int(iid)],
        "journal_sessions":list_sessions(settings,public=not gm,invite_id=iid),
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
    iid=_invite_id(request);gm=is_gm(request)
    chars=list_player_characters(settings,invite_id=iid,admin=gm)
    for c in chars:
        owner=gm or int(c.get("invite_id") or -1)==int(iid or -2);c["arcs"]=character_arcs(settings,int(c["id"]),owner=owner);c["relationships"]=character_relationships(settings,int(c["id"]),owner=owner)
    return {"threads":list_threads(settings,admin=gm,invite_id=iid),"fronts":list_fronts(settings,admin=gm,invite_id=iid),"rumors":list_rumors(settings,admin=gm),"journals":([] if iid is None else list_journals(settings,iid,admin=gm)),"characters":chars,"notifications":list_notifications(settings,iid,admin=gm),"runtime_states":runtime_states(settings,admin=gm),"submissions":list_submissions(settings,invite_id=iid,admin=gm)}


@app.get("/api/admin/living/overview")
def living_admin_overview(request: Request):
    require_gm(request);wiki=ensure_built();maps=list_maps(settings,public=False)
    region_rows=[]
    for m in maps: region_rows.extend([{**r,"map_name":m.get("name"),"map_slug":m.get("slug")} for r in map_regions(settings,int(m["id"]),admin=True)])
    return {
        "pages":[{"slug":p.get("slug"),"title":p.get("title"),"chapter":p.get("chapter")} for p in wiki.get("pages",[])],"maps":maps,
        "invitations":list_player_invites(settings),"knowledge":list_knowledge(settings),"fronts":list_fronts(settings,admin=True),"runtime_states":runtime_states(settings,admin=True),
        "relationship_history":relationship_history(settings,admin=True),"hierarchies":hierarchies(settings,admin=True),"regions":region_rows,"rumors":list_rumors(settings,admin=True),
        "threads":list_threads(settings,admin=True),"inbox":inbox_items(settings),"submissions":list_submissions(settings,admin=True),"publishing":publishing_states(settings),
        "session_snapshots":session_state_snapshots(settings),"suggestions":scan_suggestions(settings,wiki),"media_meta":list_media_catalog(settings),"assets":_asset_rows(),"media_assets":_media_asset_rows(),
        "notifications":list_notifications(settings,None,admin=True),"characters":list_player_characters(settings,admin=True),"continuity":continuity_report(settings,wiki),
        "ai_configured":bool(os.getenv("LOREFORGE_AI_API_KEY") and os.getenv("LOREFORGE_AI_MODEL")),"archive_mode":get_setting(settings,"campaign_archive_mode","0") in {"1","true","yes"},
    }


@app.post("/api/admin/knowledge")
def admin_set_knowledge(request:Request,payload:dict=Body(...)):
    require_gm(request);return set_knowledge(settings,int(payload.get("invite_id")),str(payload.get("target_type") or "page"),str(payload.get("target_key") or ""),str(payload.get("state") or "known"),str(payload.get("note") or ""),"gm")


@app.post("/api/admin/fronts")
def admin_save_front(request:Request,payload:dict=Body(...)):
    require_gm(request);return save_front(settings,payload)
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
    require_gm(request);return save_rumor(settings,payload)
@app.delete("/api/admin/rumors/{rid}")
def admin_rumor_delete(request:Request,rid:int):
    require_gm(request)
    with connect(settings) as conn:conn.execute("DELETE FROM rumors WHERE id=?",(rid,))
    return {"ok":True}
@app.get("/api/admin/rumors/random")
def admin_random_rumor(request:Request,location_slug:str="",faction_slug:str=""):
    require_gm(request);row=random_rumor(settings,location_slug=location_slug,faction_slug=faction_slug)
    return row or {}

@app.post("/api/admin/rumors/{rid}/share")
def admin_rumor_share(request:Request,rid:int,payload:dict=Body(...)):
    require_gm(request);r=next((x for x in list_rumors(settings,admin=True) if int(x['id'])==rid),None)
    if not r:raise HTTPException(404)
    r=save_rumor(settings,{**r,"status":"heard"});create_notification(settings,{"title":"A new rumor is circulating","body":r['body'],"target_type":"rumor","target_key":str(rid),"kind":"rumor","audience":payload.get('audience') or []});return r


@app.post("/api/threads")
def thread_save_api(request:Request,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    try:return save_thread(settings,payload,invite_id=_invite_id(request),admin=is_gm(request))
    except PermissionError as e:raise HTTPException(403,str(e))
@app.delete("/api/threads/{tid}")
def thread_delete_api(request:Request,tid:int):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request)
    rows=list_threads(settings,admin=is_gm(request),invite_id=_invite_id(request));t=next((x for x in rows if int(x['id'])==tid),None)
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
    payload=dict(payload)
    # Session note forms inherit the character identity chosen for the current
    # live session unless the client explicitly chose a different/general scope.
    if "character_id" not in payload:
        live=get_live_session(settings,invite_id=iid,admin=False);session_key=int((live or {}).get("id") or 0)
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
    return save_submission(settings,payload,iid)
@app.post("/api/player/submissions/upload")
async def player_submission_upload(request:Request,file:UploadFile=File(...)):
    if not player_allowed(request):raise HTTPException(401)
    require_player_author(request);iid=_invite_id(request)
    if iid is None:raise HTTPException(403,"A personal invitation is required.")
    ext=Path(file.filename or "asset").suffix.lower()
    allowed={'.png','.jpg','.jpeg','.webp','.gif','.pdf','.mp3','.m4a','.wav','.ogg'}
    if ext not in allowed:raise HTTPException(400,"Use an image, PDF, or common audio file.")
    data=await file.read(30_000_001)
    if len(data)>30_000_000:raise HTTPException(413,"Contribution files are limited to 30 MB.")
    folder=settings.uploads_dir/'submissions'/str(iid);folder.mkdir(parents=True,exist_ok=True)
    stem=re.sub(r'[^A-Za-z0-9._-]+','-',Path(file.filename or 'asset').stem).strip('-')[:70] or 'asset'
    name=f"{int(time.time()*1000)}-{secrets.token_hex(3)}-{stem}{ext}";path=folder/name;path.write_bytes(data)
    rel=path.relative_to(settings.uploads_dir).as_posix();return {"ref":"upload:"+rel,"url":"/uploads/"+quote(rel,safe='/'),"name":file.filename or name}

@app.post("/api/admin/inbox/upload")
async def admin_inbox_upload(request:Request,file:UploadFile=File(...)):
    require_gm(request);ext=Path(file.filename or 'asset').suffix.lower()
    allowed={'.png','.jpg','.jpeg','.webp','.gif','.pdf','.mp3','.m4a','.wav','.ogg','.webm','.txt'}
    if ext not in allowed:raise HTTPException(400,"Unsupported quick-capture file type.")
    data=await file.read(40_000_001)
    if len(data)>40_000_000:raise HTTPException(413,"Inbox files are limited to 40 MB.")
    folder=settings.uploads_dir/'gm-inbox';folder.mkdir(parents=True,exist_ok=True)
    stem=re.sub(r'[^A-Za-z0-9._-]+','-',Path(file.filename or 'asset').stem).strip('-')[:70] or 'asset'
    name=f"{int(time.time()*1000)}-{secrets.token_hex(3)}-{stem}{ext}";path=folder/name;path.write_bytes(data)
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
    if state=='published':create_notification(settings,{"title":"New lore published","body":f"A group of {len(rows)} lore entries was published.","kind":"publish"})
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
    require_gm(request);return create_notification(settings,payload)
@app.get("/api/public/notifications")
def public_notifications(request:Request,since:float=0):
    if not player_allowed(request):raise HTTPException(401)
    return list_notifications(settings,_invite_id(request),admin=is_gm(request),since=since)
@app.post("/api/public/notifications/{nid}/read")
def public_notification_read(request:Request,nid:int):
    if not player_allowed(request):raise HTTPException(401)
    iid=_invite_id(request)
    if iid is not None:mark_notification_read(settings,nid,iid)
    return {"ok":True}


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
    return entity_provenance(settings,slug)


@app.get("/api/export/foundry/page/{slug}")
def foundry_page_export(request:Request,slug:str):
    if not player_allowed(request):raise HTTPException(401)
    p=next((x for x in _visible_wiki(request).get('pages',[]) if x.get('slug')==slug),None)
    if not p:raise HTTPException(404)
    return JSONResponse(export_foundry_journal(p['title'],p.get('html',''),p.get('presentation',{}).get('hero_image_url') or ''))
@app.get("/api/export/foundry/character/{character_id}")
def foundry_character_export(request:Request,character_id:int):
    char=get_player_character(settings,character_id,invite_id=_invite_id(request),admin=is_gm(request))
    if not char:raise HTTPException(404)
    body=f"<h2>{char.get('name','')}</h2><p>{char.get('summary','')}</p><h3>Biography</h3><p>{char.get('biography','')}</p><h3>Goals</h3><p>{char.get('goals','')}</p>"
    img='/uploads/'+char.get('portrait_path','') if char.get('portrait_path') else ''
    return JSONResponse(export_foundry_journal(char.get('name','Character'),body,img))


@app.get("/api/admin/portable-archive")
def portable_archive_download(request:Request):
    require_admin(request);out=settings.build_dir/'loreforge-portable-campaign.zip';create_portable_archive(settings,out);return FileResponse(out,filename='loreforge-portable-campaign.zip',media_type='application/zip')
@app.post("/api/admin/portable-archive/test")
async def portable_archive_test(request:Request,file:UploadFile=File(...)):
    require_admin(request)
    if not str(file.filename or '').lower().endswith('.zip'): raise HTTPException(400,'Choose a Loreforge portable ZIP.')
    tmp=Path(tempfile.gettempdir())/f"loreforge-backup-test-{secrets.token_hex(8)}.zip"
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
        create_notification(settings,{'title':'Campaign archive published','body':'The campaign has been frozen into read-only archive mode.','kind':'archive'})
    return {'enabled':enabled}
@app.get("/archive", response_class=HTMLResponse)
def campaign_archive_page(request:Request):
    if not player_allowed(request):return player_gate_redirect(request)
    wiki=_visible_wiki(request);maps=list_maps(settings,public=True)
    return templates.TemplateResponse('archive.html',{'request':request,'wiki':wiki,'maps':maps,'sessions':list_sessions(settings,public=True,invite_id=_invite_id(request)),'timeline':list_timeline(settings,admin=is_gm(request),historical_only=True),'characters':list_player_characters(settings,invite_id=_invite_id(request),admin=is_gm(request))})


@app.post("/api/assistant/query")
def lore_assistant_query(request:Request,payload:dict=Body(...)):
    if not player_allowed(request):raise HTTPException(401)
    q=str(payload.get('q') or '').strip()
    if not q:raise HTTPException(400,'Ask a question about the campaign.')
    wiki=_visible_wiki(request);terms=[x for x in re.findall(r'[A-Za-z0-9]+',q.lower()) if len(x)>2]
    ranked=[]
    for p in wiki.get('pages',[]):
        text=(p.get('plain_text') or '')[:12000];low=text.lower();score=sum(low.count(t) for t in terms)+(8 if any(t in p.get('title','').lower() for t in terms) else 0)
        if score:ranked.append((score,p))
    ranked.sort(key=lambda x:-x[0]);context=[]
    for _,p in ranked[:8]:
        plain=re.sub(r'\s+',' ',p.get('plain_text','')).strip();context.append({'title':p.get('title'),'slug':p.get('slug'),'text':plain[:1600]})
    api_key=os.getenv('LOREFORGE_AI_API_KEY','').strip();model=os.getenv('LOREFORGE_AI_MODEL','').strip();base=os.getenv('LOREFORGE_AI_BASE_URL','https://api.openai.com/v1').rstrip('/')
    if api_key and model and payload.get('use_ai',True):
        try:
            system='You are the Loreforge campaign assistant. Answer ONLY from the supplied spoiler-filtered campaign context. If the answer is not in the context, say so. Keep fantasy names exact.'
            prompt='QUESTION:\n'+q+'\n\nVISIBLE CAMPAIGN CONTEXT:\n'+'\n\n'.join(f"[{c['title']}] {c['text']}" for c in context)
            body=json.dumps({'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':prompt}],'temperature':0.2}).encode()
            req=UrlRequest(base+'/chat/completions',data=body,headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json'})
            with urlopen(req,timeout=35) as resp:data=json.loads(resp.read().decode())
            answer=data['choices'][0]['message']['content'];return {'mode':'ai','answer':answer,'sources':[{k:c[k] for k in ('title','slug')} for c in context]}
        except Exception as exc:
            ai_error=str(exc)
        else: ai_error=''
    else:ai_error=''
    if not context:return {'mode':'local','answer':'I could not find that in the lore currently visible to you.','sources':[],'ai_error':ai_error}
    snippets=[]
    for c in context[:4]:
        snippets.append(f"{c['title']}: {c['text'][:420].rstrip()}…")
    return {'mode':'local','answer':'\n\n'.join(snippets),'sources':[{k:c[k] for k in ('title','slug')} for c in context[:4]],'ai_error':ai_error}


@app.put("/api/admin/invitations/{invite_id}/role")
def admin_invitation_role(request:Request,invite_id:int,payload:dict=Body(...)):
    require_admin(request);role=str(payload.get('role') or 'player').lower()
    if role not in {'player','observer','guest','co-gm'}:raise HTTPException(400,'Unknown role')
    with connect(settings) as conn:
        cur=conn.execute('UPDATE player_invites SET role=?,access_version=access_version+1 WHERE id=?',(role,int(invite_id)))
        if cur.rowcount!=1:raise HTTPException(404)
        conn.execute('DELETE FROM player_devices WHERE invite_id=?',(int(invite_id),))
    return next((x for x in list_player_invites(settings) if int(x['id'])==invite_id),{})
