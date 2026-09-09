from __future__ import annotations

import copy
import json
import os
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
    cleanup_legacy_import_artifacts, create_player_invite, delete_player_invite, export_project_zip,
    get_codex_presentation, get_setting, init_db, list_player_invites, list_project_files, list_revisions,
    register_player_device, replace_project_from_zip, reset_player_invite_devices, resolve_player_invite,
    restore_player_invite, restore_revision, revoke_player_invite, rotate_player_invite, safe_project_path,
    save_codex_presentation, save_text_file, seed_project, set_setting, storage_report, validate_player_invite_session,
)

settings = load_settings()
init_db(settings)
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


def _visible_wiki(request: Request, *, include_hidden_for_admin: bool = True) -> dict:
    wiki = copy.deepcopy(ensure_built())
    if include_hidden_for_admin and is_admin(request):
        return wiki
    visible_pages = []
    allowed_slugs = set()
    for page in wiki.get("pages", []):
        visibility = page.get("presentation", {}).get("visibility", "public")
        if visibility == "hidden":
            continue
        visible_pages.append(page)
        allowed_slugs.add(page.get("slug"))
    wiki["pages"] = visible_pages
    clean_categories = []
    for category in wiki.get("categories", []):
        category["pages"] = [p for p in category.get("pages", []) if p.get("slug") in allowed_slugs]
        if category["pages"]:
            clean_categories.append(category)
    wiki["categories"] = clean_categories
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
    return templates.TemplateResponse("home.html", {"request": request, "wiki": wiki, "maps": maps, "featured": featured})


@app.get("/wiki/{slug}", response_class=HTMLResponse)
def wiki_page(request: Request, slug: str):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); pages = wiki.get("pages", [])
    page = next((p for p in pages if p["slug"] == slug), None)
    if not page: raise HTTPException(404, "Wiki page not found")
    idx = pages.index(page)
    prev_page = pages[idx-1] if idx > 0 else None
    next_page = pages[idx+1] if idx + 1 < len(pages) else None
    page_locked = (not is_admin(request) and page.get("presentation", {}).get("visibility") == "teaser")
    return templates.TemplateResponse(
        "page.html",
        {
            "request": request, "wiki": wiki, "page": page, "prev_page": prev_page, "next_page": next_page,
            "page_locked": page_locked, "admin_view": is_admin(request),
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
    network = {"nodes": nodes, "edges": edges}
    return templates.TemplateResponse("network.html", {"request": request, "wiki": wiki, "maps": maps, "network": network})


@app.get("/atlas/{slug}", response_class=HTMLResponse)
def map_page(request: Request, slug: str):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki = _visible_wiki(request); map_data = get_map(settings, slug, public=True)
    if not map_data: raise HTTPException(404, "Map not found")
    return templates.TemplateResponse("map.html", {"request": request, "wiki": wiki, "map": map_data})


@app.get("/api/public/search")
def public_search(request: Request, q: str = ""):
    if not player_allowed(request): raise HTTPException(401)
    qn = q.strip().lower()
    if not qn: return []
    wiki = _visible_wiki(request)
    ranked=[]
    for p in wiki.get("pages", []):
        visibility = p.get("presentation", {}).get("visibility", "public")
        title=p["title"].lower()
        text=(p.get("excerpt", "") if visibility == "teaser" else p.get("plain_text", "")).lower()
        score=0
        if qn == title: score += 100
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
def admin_maps(request: Request): require_admin(request); return list_maps(settings,public=False)


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
