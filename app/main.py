from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import load_settings
from .latex import analyze_project, build_wiki, choose_main, compile_pdf, load_wiki
from .maps import create_map, create_marker, delete_map, delete_marker, get_map, list_maps, update_map, update_marker
from .storage import (
    export_project_zip, get_setting, init_db, list_project_files, list_revisions,
    replace_project_from_zip, restore_revision, safe_project_path, save_text_file,
    seed_project, set_setting,
)

settings = load_settings()
init_db(settings)
seed_project(settings)

app = FastAPI(title="Loreforge", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False, same_site="lax")
app.mount("/static", StaticFiles(directory=settings.root_dir / "static"), name="static")
templates = Jinja2Templates(directory=settings.root_dir / "templates")


def is_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Admin login required")


def player_allowed(request: Request) -> bool:
    return settings.player_password is None or bool(request.session.get("player")) or is_admin(request)


def ensure_built() -> dict:
    try:
        return load_wiki(settings)
    except Exception:
        return {"title": "Loreforge", "tagline": "Import a LaTeX campaign project in /admin.", "categories": [], "pages": [], "generated_at": time.time()}


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


@app.get("/login", response_class=HTMLResponse)
def player_login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "mode": "player", "title": ensure_built().get("title", "Campaign Atlas")})


@app.post("/login")
def player_login(request: Request, password: str = Form(...)):
    if settings.player_password is None or secrets.compare_digest(password, settings.player_password):
        request.session["player"] = True
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "mode": "player", "error": "Wrong password.", "title": ensure_built().get("title", "Campaign Atlas")}, status_code=401)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "mode": "admin", "title": "Loreforge Editor"})


@app.post("/admin/login")
def admin_login(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, settings.admin_password):
        request.session["admin"] = True
        request.session["player"] = True
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "mode": "admin", "error": "Wrong password.", "title": "Loreforge Editor"}, status_code=401)


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear(); return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not player_allowed(request): return RedirectResponse("/login")
    wiki = ensure_built(); maps = list_maps(settings, public=True)
    return templates.TemplateResponse("home.html", {"request": request, "wiki": wiki, "maps": maps})


@app.get("/wiki/{slug}", response_class=HTMLResponse)
def wiki_page(request: Request, slug: str):
    if not player_allowed(request): return RedirectResponse("/login")
    wiki = ensure_built(); pages = wiki.get("pages", [])
    page = next((p for p in pages if p["slug"] == slug), None)
    if not page: raise HTTPException(404, "Wiki page not found")
    idx = pages.index(page)
    prev_page = pages[idx-1] if idx > 0 else None
    next_page = pages[idx+1] if idx + 1 < len(pages) else None
    return templates.TemplateResponse("page.html", {"request": request, "wiki": wiki, "page": page, "prev_page": prev_page, "next_page": next_page})


@app.get("/atlas/{slug}", response_class=HTMLResponse)
def map_page(request: Request, slug: str):
    if not player_allowed(request): return RedirectResponse("/login")
    wiki = ensure_built(); map_data = get_map(settings, slug, public=True)
    if not map_data: raise HTTPException(404, "Map not found")
    return templates.TemplateResponse("map.html", {"request": request, "wiki": wiki, "map": map_data})


@app.get("/api/public/search")
def public_search(request: Request, q: str = ""):
    if not player_allowed(request): raise HTTPException(401)
    qn = q.strip().lower()
    pages = ensure_built().get("pages", [])
    if not qn: return []
    ranked=[]
    for p in pages:
        title=p["title"].lower(); text=p.get("plain_text","").lower(); score=0
        if qn == title: score += 100
        if qn in title: score += 30
        score += min(10, text.count(qn))
        if all(term in text or term in title for term in qn.split()): score += 5
        if score: ranked.append((score,p))
    ranked.sort(key=lambda x:(-x[0],x[1]["order"]))
    return [{"slug":p["slug"],"title":p["title"],"chapter":p.get("chapter"),"excerpt":p.get("excerpt","")} for _,p in ranked[:20]]


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
    path=settings.build_dir / "campaign.pdf"
    if not path.exists(): raise HTTPException(404, "No compiled PDF yet")
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
        "pdf_ready":(settings.build_dir/"campaign.pdf").exists(),
        "wiki_ready":(settings.build_dir/"wiki_index.json").exists(),
        "site_title":get_setting(settings,"site_title","") or analysis.get("title","Campaign Atlas"),
        "tagline":get_setting(settings,"tagline","Explore the people, places, histories, and mysteries of the campaign."),
        "main_file":get_setting(settings,"main_file","") or analysis.get("main_file",""),
    }


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


@app.post("/api/admin/compile")
def admin_compile(request: Request):
    require_admin(request)
    try:
        wiki=build_wiki(settings); result=compile_pdf(settings)
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
    tmp=settings.data_dir / f"upload-{int(time.time())}.zip"
    with tmp.open("wb") as f:
        while chunk := await archive.read(1024*1024): f.write(chunk)
    try:
        replace_project_from_zip(settings,tmp)
        set_setting(settings,"main_file","")
        analysis=analyze_project(settings); wiki=build_wiki(settings); result=compile_pdf(settings)
        return {"ok":True,"analysis":analysis,"wiki_pages":len(wiki.get("pages",[])),"compile":result.__dict__}
    except Exception as exc: raise HTTPException(400,str(exc))
    finally: tmp.unlink(missing_ok=True)


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
    if payload.get("main_file"): choose_main(settings)
    try: build_wiki(settings)
    except Exception: pass
    return {"ok":True}


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
