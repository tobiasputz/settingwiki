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
    list_sessions, list_snapshots, list_timeline, list_variants, log_activity, map_layers, page_relationships,
    recent_updates, reveal_state, restore_snapshot, save_alias, save_entity_style, save_fog_region, save_handout, save_map_layer,
    save_mystery, save_mystery_edge, save_relationship, save_session, save_timeline_event, save_variant, delete_variant, set_reveal, set_session_lore,
    toggle_bookmark, travel_between_markers,
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
    return bool(request.session.get("admin"))


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Admin login required")


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
    admin = is_admin(request)
    invite_id = _invite_id(request)
    visible_pages = []
    allowed_slugs = set()
    for page in wiki.get("pages", []):
        visibility = page.get("presentation", {}).get("visibility", "public")
        page_reveal = reveal_state(settings, "page", page.get("slug", ""), invite_id)
        if not admin:
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
    wiki["player_label"] = (active_invite or {}).get("label", "") if not admin else "GM"
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
    iid=_invite_id(request); updates=recent_updates(settings,iid,6,admin=is_admin(request));live=get_live_session(settings,invite_id=iid,admin=is_admin(request))
    if not is_admin(request):
        allowed={p.get("slug") for p in wiki.get("pages",[])}
        updates=[u for u in updates if u.get("target_type")!="lore" or not u.get("target_key") or u.get("target_key") in allowed]
    return templates.TemplateResponse("home.html", {"request": request, "wiki": wiki, "maps": maps, "featured": featured,"updates":updates,"live_session":live,"mysteries":list_mysteries(settings,admin=is_admin(request))[:4]})


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
    page_locked = (not is_admin(request) and page.get("presentation", {}).get("visibility") == "teaser")
    all_maps=list_maps(settings,public=not is_admin(request)); map_locations=[]
    for m in all_maps:
        for marker in m.get("markers",[]):
            if marker.get("page_slug")==slug: map_locations.append({"map":m,"marker":marker})
    appearances=[]
    for sess in list_sessions(settings,public=not is_admin(request),invite_id=_invite_id(request)):
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
            "page_locked": page_locked, "admin_view": is_admin(request),"maps":all_maps,"map_locations":map_locations,"appearances":appearances,
        },
    )


@app.get("/network", response_class=HTMLResponse)
def lore_network(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request)
    maps = list_maps(settings, public=True)
    allowed = {p.get("slug") for p in wiki.get("pages", [])}
    nodes = [{
        "slug": p["slug"], "title": p["title"], "chapter": p.get("chapter") or "Setting",
        "image": p.get("presentation", {}).get("display_toc_image_url") or "",
    } for p in wiki.get("pages", [])]
    edges = []
    seen = set()
    for p in wiki.get("pages", []):
        for target in p.get("outgoing_links", []):
            if target not in allowed or target == p.get("slug"):
                continue
            key = tuple(sorted((p["slug"], target)))
            if key in seen:
                continue
            seen.add(key); edges.append({"source": p["slug"], "target": target})
    # Add deliberate semantic relationships to the same graph. Hidden/GM-only
    # edges are already removed by _visible_wiki/page_relationships.
    for p in wiki.get("pages", []):
        for rel in p.get("explicit_relationships", []):
            source,target=rel.get("source_slug"),rel.get("target_slug")
            if source not in allowed or target not in allowed or source==target: continue
            key=(source,target,rel.get("relation") or "related to")
            if key in seen: continue
            seen.add(key); edges.append({"source":source,"target":target,"label":rel.get("label") or rel.get("relation") or "related to","explicit":True})
    network = {"nodes": nodes, "edges": edges}
    return templates.TemplateResponse("network.html", {"request": request, "wiki": wiki, "maps": maps, "network": network})


@app.get("/atlas/{slug}", response_class=HTMLResponse)
def map_page(request: Request, slug: str):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); map_data = get_map(settings, slug, public=True)
    if not map_data: raise HTTPException(404, "Map not found")
    map_data["layers"] = map_layers(settings, int(map_data["id"]), public=True)
    map_data["fog_regions"] = fog_regions(settings, int(map_data["id"]), public=True)
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
            {"name": "Timeline", "url": "/timeline", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]},
            {"name": "Calendar", "url": "/calendar", "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]}
        ],
    }
    return JSONResponse(payload, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    path = settings.root_dir / "static" / "sw.js"
    return FileResponse(path, media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})


@app.get("/session", response_class=HTMLResponse)
def player_session_screen(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); maps = list_maps(settings, public=True); iid=_invite_id(request); live = get_live_session(settings,invite_id=iid,admin=is_admin(request))
    by_slug = {p["slug"]: p for p in wiki.get("pages", [])}
    if live:
        live["lore_pages"] = [by_slug[x["page_slug"]] for x in live.get("lore", []) if x.get("page_slug") in by_slug]
        live["spotlight_map"] = next((m for m in maps if m.get("slug") == live.get("spotlight_map_slug")), None)
    invite = current_player_invite(request)
    notes = []
    history=[x for x in list_sessions(settings,public=True,invite_id=iid) if x.get("status")=="ended"][-12:]
    if not is_admin(request):
        allowed={p.get("slug") for p in wiki.get("pages",[])}
        if live: live["lore"]=[x for x in live.get("lore",[]) if x.get("page_slug") in allowed]
        for row in history: row["lore"]=[x for x in row.get("lore",[]) if x.get("page_slug") in allowed]
    mysteries=list_mysteries(settings, admin=is_admin(request))[:6]
    if not is_admin(request):
        allowed={p.get("slug") for p in wiki.get("pages",[])}
        for mystery in mysteries:
            mystery["pins"]=[x for x in mystery.get("pins",[]) if not x.get("page_slug") or x.get("page_slug") in allowed]
            pin_ids={x.get("id") for x in mystery["pins"]}
            mystery["edges"]=[e for e in mystery.get("edges",[]) if e.get("source_pin") in pin_ids and e.get("target_pin") in pin_ids]
    return templates.TemplateResponse("session.html", {"request": request, "wiki": wiki, "maps": maps, "session": live, "player": invite, "updates": recent_updates(settings, iid, 12,admin=is_admin(request)), "mysteries": mysteries,"session_history":list(reversed(history)),"calendar":_calendar_config()})


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); events=list_timeline(settings,admin=is_admin(request))
    allowed={p.get("slug") for p in wiki.get("pages",[])}
    for event in events:
        event["image_url"]=_asset_ref_url(event.get("image_ref",""))
        if not is_admin(request) and event.get("page_slug") not in allowed: event["page_slug"]=None
    return templates.TemplateResponse("timeline.html", {"request":request,"wiki":wiki,"maps":maps,"events":events,"calendar_name":get_setting(settings,"calendar_name","Campaign Calendar"),"current_date":get_setting(settings,"campaign_date",""),"calendar":_calendar_config()})


@app.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); cal=_calendar_config()
    festivals=[e for e in list_timeline(settings,admin=is_admin(request)) if e.get("kind")=="festival"]
    return templates.TemplateResponse("calendar.html", {"request":request,"wiki":wiki,"maps":maps,"calendar":cal,"festivals":festivals})


@app.get("/updates", response_class=HTMLResponse)
def updates_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True)
    allowed={p.get("slug") for p in wiki.get("pages",[])}
    updates=recent_updates(settings,_invite_id(request),100,admin=is_admin(request))
    if not is_admin(request): updates=[u for u in updates if u.get("target_type")!="lore" or not u.get("target_key") or u.get("target_key") in allowed]
    return templates.TemplateResponse("updates.html", {"request":request,"wiki":wiki,"maps":maps,"updates":updates,"sessions":list_sessions(settings,public=True,invite_id=_invite_id(request))})


@app.get("/mysteries", response_class=HTMLResponse)
def mysteries_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); rows=list_mysteries(settings,admin=is_admin(request))
    if not is_admin(request):
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
    rows=list_handouts(settings,admin=is_admin(request)); allowed={p.get("slug") for p in wiki.get("pages",[])}
    for h in rows:
        h["image_url"]=_asset_ref_url(h.get("image_ref",""))
        if not is_admin(request) and h.get("page_slug") not in allowed: h["page_slug"]=None
    return templates.TemplateResponse("handouts.html", {"request":request,"wiki":wiki,"maps":maps,"handouts":rows})


@app.get("/handout/{slug}", response_class=HTMLResponse)
def handout_page(request: Request, slug: str):
    if not player_allowed(request): return player_gate_redirect(request)
    row=next((x for x in list_handouts(settings,admin=is_admin(request)) if x["slug"]==slug),None)
    if not row: raise HTTPException(404,"Handout not found")
    row["image_url"]=_asset_ref_url(row.get("image_ref","")); wiki=_visible_wiki(request); maps=list_maps(settings,public=True)
    if not is_admin(request) and row.get("page_slug") not in {p.get("slug") for p in wiki.get("pages",[])}: row["page_slug"]=None
    return templates.TemplateResponse("handout.html", {"request":request,"wiki":wiki,"maps":maps,"handout":row,"admin_view":is_admin(request)})


@app.get("/api/public/session-pulse")
def public_session_pulse(request: Request):
    if not player_allowed(request): raise HTTPException(401)
    iid=_invite_id(request); admin=is_admin(request); live=get_live_session(settings,invite_id=iid,admin=admin)
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
    return list_annotations(settings,slug,invite_id=_invite_id(request),admin=is_admin(request))


@app.post("/api/public/annotations")
def public_add_annotation(request: Request,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    invite=current_player_invite(request); label="GM" if is_admin(request) else (invite or {}).get("label","Player")
    return add_annotation(settings,payload,invite_id=_invite_id(request),author_label=label,admin=is_admin(request))


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
    require_admin(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=False); live=get_live_session(settings,admin=True)
    return templates.TemplateResponse("gm_session.html", {"request":request,"wiki":wiki,"maps":maps,"session":live,"sessions":list_sessions(settings),"reveals":list_reveal_blocks_from_wiki(ensure_built()),"mysteries":list_mysteries(settings,admin=True),"handouts":list_handouts(settings,admin=True),"updates":recent_updates(settings,None,20,admin=True)})


@app.get("/admin/campaign", response_class=HTMLResponse)
def admin_campaign_page(request: Request):
    require_admin(request)
    wiki=ensure_built(); maps=list_maps(settings,public=False)
    return templates.TemplateResponse("campaign_admin.html", {"request":request,"wiki":wiki,"maps":maps})


@app.get("/project-asset/{asset_path:path}")
def project_asset(request: Request, asset_path: str):
    if not player_allowed(request): raise HTTPException(401)
    path = safe_project_path(settings, unquote(asset_path))
    if not path.exists() or not path.is_file(): raise HTTPException(404)
    return FileResponse(path)


@app.get("/uploads/{asset_path:path}")
def uploaded_asset(request: Request, asset_path: str):
    if not player_allowed(request): raise HTTPException(401)
    path=(settings.uploads_dir / unquote(asset_path)).resolve()
    if settings.uploads_dir.resolve() not in path.parents or not path.exists(): raise HTTPException(404)
    return FileResponse(path)


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    if not is_admin(request): return RedirectResponse("/admin/login")
    return templates.TemplateResponse("admin.html", {"request": request, "title": "Loreforge Editor"})


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
            settings, str(payload.get("label") or ""), expires_at, payload.get("max_devices")
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
    require_admin(request)
    wiki=ensure_built(); maps=list_maps(settings,public=False)
    for m in maps:
        m["layers"] = map_layers(settings, int(m["id"]), public=False)
        m["fog_regions"] = fog_regions(settings, int(m["id"]), public=False)
    return {
        "maps":maps,
        "sessions":list_sessions(settings),"timeline":list_timeline(settings,admin=True),
        "relationships":list_relationships(settings,admin=True),"reveals":list_reveal_blocks_from_wiki(wiki),
        "mysteries":list_mysteries(settings,admin=True),"handouts":list_handouts(settings,admin=True),
        "snapshots":list_snapshots(settings),"health":campaign_health(settings,wiki,maps),
        "reveal_states":list_reveal_states(settings),"recent_updates":recent_updates(settings,None,12,admin=True),
        "calendar":_calendar_config(),
        "aliases":aliases(settings),"invitations":list_player_invites(settings),
        "variants":[v for p in wiki.get("pages",[]) for v in list_variants(settings,p.get("slug",""),admin=True)],
        "entity_styles":{p.get("slug",""):entity_style(settings,p.get("slug","")) for p in wiki.get("pages",[])},
        "assets":_asset_rows(),"media_assets":_media_asset_rows(),
    }


@app.post("/api/admin/sessions")
def admin_save_session(request: Request,payload:dict=Body(...)):
    require_admin(request); return save_session(settings,payload)


@app.delete("/api/admin/sessions/{session_id}")
def admin_delete_session(request:Request,session_id:int):
    require_admin(request);delete_session(settings,session_id);return {"ok":True}


@app.post("/api/admin/sessions/{session_id}/lore")
def admin_session_lore(request:Request,session_id:int,payload:dict=Body(...)):
    require_admin(request);set_session_lore(settings,session_id,str(payload.get("page_slug") or ""),str(payload.get("role") or "reference"),bool(payload.get("enabled",True)));return {"ok":True}


@app.post("/api/admin/session-updates")
def admin_session_update(request:Request,payload:dict=Body(...)):
    require_admin(request);return add_session_update(settings,payload)


@app.post("/api/admin/timeline")
def admin_timeline_save(request:Request,payload:dict=Body(...)):
    require_admin(request);return save_timeline_event(settings,payload)


@app.delete("/api/admin/timeline/{event_id}")
def admin_timeline_delete(request:Request,event_id:int):
    require_admin(request)
    from .storage import connect
    with connect(settings) as conn: conn.execute("DELETE FROM timeline_events WHERE id=?",(event_id,))
    return {"ok":True}


@app.post("/api/admin/relationships")
def admin_relationship_save(request:Request,payload:dict=Body(...)):
    require_admin(request);return save_relationship(settings,payload)


@app.delete("/api/admin/relationships/{relationship_id}")
def admin_relationship_delete(request:Request,relationship_id:int):
    require_admin(request)
    from .storage import connect
    with connect(settings) as conn: conn.execute("DELETE FROM lore_relationships WHERE id=?",(relationship_id,))
    return {"ok":True}


@app.post("/api/admin/reveals")
def admin_reveal_save(request:Request,payload:dict=Body(...)):
    require_admin(request);row=set_reveal(settings,payload)
    if row.get("state") in {"rumor","discovered","public"}:
        title=str(payload.get("title") or payload.get("target_key") or "Lore discovered")
        add_session_update(settings,{"session_id":payload.get("session_id"),"title":title,"body":str(payload.get("update_body") or "New lore has been revealed."),"target_type":payload.get("target_type") or "lore","target_key":payload.get("target_key") or "","visibility":"players","audience":payload.get("audience") or []})
    return row


@app.post("/api/admin/variants")
def admin_variant_save(request:Request,payload:dict=Body(...)):
    require_admin(request);return save_variant(settings,payload)


@app.delete("/api/admin/variants/{variant_id}")
def admin_variant_delete(request:Request,variant_id:int):
    require_admin(request);delete_variant(settings,variant_id);return {"ok":True}


@app.post("/api/admin/aliases")
def admin_alias_save(request:Request,payload:dict=Body(...)):
    require_admin(request);save_alias(settings,str(payload.get("alias") or ""),str(payload.get("page_slug") or ""));return {"ok":True}


@app.put("/api/admin/entity-style/{slug}")
def admin_entity_style_save(request:Request,slug:str,payload:dict=Body(...)):
    require_admin(request);return save_entity_style(settings,slug,payload)


@app.post("/api/admin/mysteries")
def admin_mystery_save(request:Request,payload:dict=Body(...)):
    require_admin(request);return save_mystery(settings,payload)


@app.post("/api/admin/mysteries/{mystery_id}/pins")
def admin_mystery_pin(request:Request,mystery_id:int,payload:dict=Body(...)):
    require_admin(request);return add_mystery_pin(settings,mystery_id,payload)


@app.post("/api/admin/mysteries/{mystery_id}/edges")
def admin_mystery_edge(request:Request,mystery_id:int,payload:dict=Body(...)):
    require_admin(request)
    try: return save_mystery_edge(settings,mystery_id,payload)
    except ValueError as e: raise HTTPException(status_code=400,detail=str(e))


@app.delete("/api/admin/mystery-edges/{edge_id}")
def admin_mystery_edge_delete(request:Request,edge_id:int):
    require_admin(request);delete_mystery_edge(settings,edge_id);return {"ok":True}


@app.delete("/api/admin/mystery-pins/{pin_id}")
def admin_mystery_pin_delete(request:Request,pin_id:int):
    require_admin(request);delete_mystery_pin(settings,pin_id);return {"ok":True}


@app.delete("/api/admin/mysteries/{mystery_id}")
def admin_mystery_delete(request:Request,mystery_id:int):
    require_admin(request)
    from .storage import connect
    with connect(settings) as conn:conn.execute("DELETE FROM mysteries WHERE id=?",(mystery_id,))
    return {"ok":True}


@app.post("/api/admin/handouts")
def admin_handout_save(request:Request,payload:dict=Body(...)):
    require_admin(request);return save_handout(settings,payload)


@app.delete("/api/admin/handouts/{handout_id}")
def admin_handout_delete(request:Request,handout_id:int):
    require_admin(request)
    from .storage import connect
    with connect(settings) as conn:conn.execute("DELETE FROM handouts WHERE id=?",(handout_id,))
    return {"ok":True}


@app.post("/api/admin/maps/{map_id}/layers")
def admin_map_layer_save(request:Request,map_id:int,payload:dict=Body(...)):
    require_admin(request);return save_map_layer(settings,map_id,payload)


@app.delete("/api/admin/map-layers/{layer_id}")
def admin_map_layer_delete(request:Request,layer_id:int):
    require_admin(request)
    from .storage import connect
    with connect(settings) as conn:conn.execute("DELETE FROM map_layers WHERE id=?",(layer_id,))
    return {"ok":True}


@app.post("/api/admin/maps/{map_id}/fog")
def admin_map_fog_save(request:Request,map_id:int,payload:dict=Body(...)):
    require_admin(request);return save_fog_region(settings,map_id,payload)


@app.delete("/api/admin/map-fog/{fog_id}")
def admin_map_fog_delete(request:Request,fog_id:int):
    require_admin(request)
    from .storage import connect
    with connect(settings) as conn:conn.execute("DELETE FROM map_fog_regions WHERE id=?",(fog_id,))
    return {"ok":True}


@app.post("/api/admin/snapshots")
def admin_snapshot_create(request:Request,payload:dict=Body(...)):
    require_admin(request);return create_snapshot(settings,str(payload.get("label") or "Campaign snapshot"))


@app.get("/api/admin/snapshots/{snapshot_id}/download")
def admin_snapshot_download(request:Request,snapshot_id:int):
    require_admin(request);row=next((x for x in list_snapshots(settings) if int(x["id"])==int(snapshot_id)),None)
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
    require_admin(request);return campaign_health(settings,ensure_built(),list_maps(settings,public=False))


@app.put("/api/admin/world-settings")
def admin_world_settings(request:Request,payload:dict=Body(...)):
    require_admin(request)
    for key in ("calendar_name","campaign_date","campaign_season","world_width","travel_speed"):
        if key in payload:set_setting(settings,key,str(payload[key]))
    for key in ("calendar_months","calendar_weekdays","calendar_moons","calendar_festivals"):
        if key in payload:set_setting(settings,key+"_json",json.dumps(payload.get(key) or []))
    return {"ok":True,"calendar":_calendar_config()}


@app.get("/api/admin/revisions/diff")
def admin_revision_diff(request:Request,path:str,revision_id:str):
    require_admin(request)
    import difflib
    current=safe_project_path(settings,path).read_text(encoding="utf-8",errors="replace").splitlines()
    rev_dir=settings.history_dir/Path(path)
    candidate=next((x for x in rev_dir.glob("*.txt") if x.stem==revision_id),None)
    if not candidate: raise HTTPException(404,"Revision not found")
    old=candidate.read_text(encoding="utf-8",errors="replace").splitlines()
    diff=list(difflib.unified_diff(old,current,fromfile=f"{path}@{revision_id}",tofile=path,lineterm=""))
    return {"path":path,"revision_id":revision_id,"diff":"\n".join(diff[:5000])}


@app.post("/api/admin/entry-template")
def admin_entry_template(request:Request,payload:dict=Body(...)):
    require_admin(request)
    kind=str(payload.get("kind") or "person").lower();title=str(payload.get("title") or "New Entry").strip()
    templates_map={
        "person":f"\\pon{{{title}}}\n\\section{{Profile}}\n\\begin{{multicols}}{{2}}\n\\textbf{{Ancestry:}} \\\\\n\\textbf{{Class:}} \\\\\n\\textbf{{Age:}} \\\\\n\\textbf{{Place of Residence:}} \\\\\n\\textbf{{Status:}} Alive\n\\end{{multicols}}\n\nWrite the character overview here.\n\n\\section{{Biography}}\n",
        "settlement":f"\\section{{{title}}}\n\\subsection{{Overview}}\n\n\\subsection{{Government}}\n\n\\subsection{{Notable Locations}}\n\n\\subsection{{People}}\n",
        "faction":f"\\section{{{title}}}\n\\subsection{{Purpose}}\n\n\\subsection{{Leadership}}\n\n\\subsection{{Members}}\n\n\\subsection{{Relationships}}\n",
        "deity":f"\\section{{{title}}}\n\\subsection{{Doctrine}}\n\\textbf{{Edicts:}} \\\\\n\\textbf{{Anathema:}} \\\\\n\n\\subsection{{Worshippers}}\n",
        "event":f"\\section{{{title}}}\n\\subsection{{Background}}\n\n\\subsection{{Event}}\n\n\\subsection{{Aftermath}}\n",
        "creature":f"\\begin{{monster}}{{{title}}}{{1}}{{Medium, Creature}}{{Homebrew}}\n\\monstersection{{Perception}}\n\\monsterline{{Perception}}{{+0}}\n\\monsterabilityscores{{+0}}{{+0}}{{+0}}{{+0}}{{+0}}{{+0}}\n\\monstersection{{Defense}}\n\\monsterdefenses{{15}}{{+5, +5, +5}}{{20 HP}}{{}}\n\\monstersection{{Offense}}\n\\monsterspeed{{25 feet}}\n\\end{{monster}}\n",
        "handout":f"% In-world handout source\n\\section{{{title}}}\n\n",
    }
    return {"kind":kind,"title":title,"content":templates_map.get(kind,templates_map["person"])}

@app.post("/api/admin/maps/{map_id}/layers/upload")
async def admin_map_layer_upload(request:Request,map_id:int,name:str=Form("Map layer"),kind:str=Form("overlay"),opacity:float=Form(.7),visible_to_players:bool=Form(True),image:UploadFile=File(...)):
    require_admin(request)
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
