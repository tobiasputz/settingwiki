from __future__ import annotations

# Route declarations were extracted from the historical monolithic router.
# They intentionally retain the same handler bodies, endpoint paths and names.
from .route_bridge import bind_composition_root

bind_composition_root(globals())

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
def admin_files(request: Request):
    require_admin(request)
    kinds=load_homebrew_file_kinds(settings)
    rows=[]
    for source in list_project_files(settings):
        row=dict(source);path=str(row.get('path') or '').replace('\\','/').strip('/')
        if str(row.get('suffix') or '').lower()=='.tex':row['homebrew_kind']=kinds.get(path,'codex')
        rows.append(row)
    return rows

@app.put('/api/admin/file/homebrew')
def admin_file_homebrew(request:Request,payload:dict=Body(...)):
    require_admin(request)
    rel=str(payload.get('path') or '').replace('\\','/').strip('/')
    kind=str(payload.get('kind') or 'codex').strip().lower()
    if not rel or not rel.lower().endswith('.tex'):raise HTTPException(400,'Choose a .tex source file.')
    target=safe_project_path(settings,rel)
    if not target.exists() or not target.is_file():raise HTTPException(404,'Source file not found.')
    try:set_file_homebrew_kind(settings,rel,kind)
    except ValueError as exc:raise HTTPException(400,str(exc))
    try:wiki=build_wiki(settings);warning=''
    except Exception as exc:wiki=None;warning=str(exc)
    return {'ok':True,'path':rel,'homebrew_kind':kind,'wiki_warning':warning,'pages':len((wiki or {}).get('pages',[]))}

@app.get("/api/admin/folders")
def admin_folders(request:Request):
    require_admin(request);root=settings.project_dir.resolve();rows=[]
    for path in sorted(settings.project_dir.rglob('*')):
        if not path.is_dir():continue
        rel=path.relative_to(root).as_posix()
        if not rel or any(part.startswith('.') for part in Path(rel).parts):continue
        rows.append({'path':rel,'type':'folder'})
    return rows

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
    was_dir=p.is_dir()
    delete_file_homebrew_metadata(settings,path,is_dir=was_dir)
    if was_dir: shutil.rmtree(p)
    else: p.unlink()
    return {"ok":True}

@app.post('/api/admin/folder/new')
def admin_new_folder(request:Request,payload:dict=Body(...)):
    require_admin(request);rel=str(payload.get('path') or '').replace('\\','/').strip('/')
    if not rel:raise HTTPException(400,'Missing folder path.')
    target=safe_project_path(settings,rel)
    if target.exists():raise HTTPException(409,'A file or folder already exists there.')
    target.mkdir(parents=True,exist_ok=False)
    return {'ok':True,'path':rel}

@app.post('/api/admin/file/move')
def admin_move_file(request:Request,payload:dict=Body(...)):
    require_admin(request)
    old_rel=str(payload.get('source') or '').replace('\\','/').strip('/')
    new_rel=str(payload.get('destination') or '').replace('\\','/').strip('/')
    if not old_rel or not new_rel or old_rel==new_rel:raise HTTPException(400,'Choose a source and a different destination.')
    source=safe_project_path(settings,old_rel);dest=safe_project_path(settings,new_rel)
    if not source.exists():raise HTTPException(404,'Source file or folder was not found.')
    if dest.exists():raise HTTPException(409,'A file or folder already exists at the destination.')
    if source==settings.project_dir.resolve():raise HTTPException(400,'The project root cannot be moved.')
    if source.is_dir() and (dest==source or source in dest.parents):raise HTTPException(400,'A folder cannot be moved inside itself.')
    was_dir=source.is_dir();dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.move(str(source),str(dest))
    move_file_homebrew_metadata(settings,old_rel,new_rel,is_dir=was_dir)
    rewritten=[]
    if bool(payload.get('rewrite_includes',True)):
        rewritten=_rewrite_moved_tex_references(old_rel,new_rel,was_dir)
    configured=get_setting(settings,'main_file','')
    if configured:
        cfg=configured.replace('\\','/').strip('/')
        if cfg==old_rel or (was_dir and cfg.startswith(old_rel.rstrip('/')+'/')):
            suffix=cfg[len(old_rel):].lstrip('/')
            set_setting(settings,'main_file',new_rel.rstrip('/')+('/'+suffix if suffix else ''))
    if old_rel.lower().endswith('.tex') or new_rel.lower().endswith('.tex') or was_dir:
        try:build_wiki(settings)
        except Exception as exc:return {'ok':True,'source':old_rel,'destination':new_rel,'rewritten':rewritten,'wiki_warning':str(exc)}
    return {'ok':True,'source':old_rel,'destination':new_rel,'rewritten':rewritten}

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
    except Exception as exc: _log_soft_failure("wiki", "rebuild.failed", exc, path=request.url.path)
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
    if suffix == ".svg":
        try:
            _sanitize_uploaded_svg(target)
        except (ValueError, UnicodeError) as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(400, str(exc))
    rel = ref_path_prefix + filename
    refresh_asset_index(settings, force=True)
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
    require_gm(request)
    from .handout_creator import normalize, render_body, clean_html, save_metadata
    cid=_active_campaign_id(request); payload=dict(payload); payload['campaign_id']=cid
    previous=_creator_handout(request,payload['id']) if payload.get('id') else None
    design=normalize(payload.pop('design')) if 'design' in payload else None
    if not str(payload.get('title','')).strip(): raise HTTPException(400,"A title is required")
    if len(str(payload['title']))>300: raise HTTPException(400,"Title is too long")
    if payload.get('visibility','gm') not in {'gm','players'}: raise HTTPException(400,"Invalid visibility")
    payload.setdefault('visibility','gm')
    if payload.get('session_id'):
        with connect(settings) as conn: parent=conn.execute("SELECT id FROM campaign_sessions WHERE id=? AND campaign_id=?",(payload['session_id'],cid)).fetchone()
        if not parent: raise HTTPException(400,"Session does not belong to this campaign")
    if payload.get('expires_at') is not None:
        import math
        try: expiry=float(payload['expires_at'])
        except (ValueError,TypeError): raise HTTPException(400,"Invalid expiry")
        if not math.isfinite(expiry): raise HTTPException(400,"Invalid expiry")
        payload['expires_at']=expiry
    if design: payload.update(body=render_body(design),kind=design['preset'])
    else: payload['body']=clean_html(payload.get('body',''))
    # Keep published links stable, and make new slugs collision-free across campaigns.
    if previous: payload['slug']=previous['slug']
    else:
        import uuid
        payload['slug']=str(payload.get('slug') or payload['title'])+'-'+uuid.uuid4().hex[:10]
    row=save_handout(settings,payload)
    if design: save_metadata(settings,row['id'],design)
    if row['visibility']=='players' and (not previous or previous['visibility']=='gm'):
        create_notification(settings,{"campaign_id":cid,"title":"New handout · "+row['title'],"body":"A new handout is available.","target_type":"handout","target_key":str(row['id']),"kind":"handout","audience":[]})
    return row

@app.delete("/api/admin/handouts/{handout_id}")
def admin_handout_delete(request:Request,handout_id:int):
    require_gm(request);_creator_handout(request,handout_id)
    with connect(settings) as conn:
        conn.execute("DELETE FROM handout_designs WHERE handout_id=?",(handout_id,))
        conn.execute("DELETE FROM handouts WHERE id=? AND campaign_id=?",(handout_id,_active_campaign_id(request)))
    return {"ok":True}

@app.get('/gm/handouts',response_class=HTMLResponse)
def handout_creator_page(request:Request):
    require_gm(request)
    from .handout_creator import PRESETS
    return templates.TemplateResponse('handout_creator.html',{'request':request,'wiki':_visible_wiki(request),'maps':list_maps(settings,public=True),'presets':PRESETS})

@app.get('/api/admin/handout-creator')
def handout_creator_list(request:Request):
    require_gm(request)
    with connect(settings) as conn:
        rows=[dict(r) for r in conn.execute('SELECT h.*, d.data AS design_data FROM handouts h LEFT JOIN handout_designs d ON d.handout_id=h.id WHERE h.campaign_id=? ORDER BY h.updated_at DESC',(_active_campaign_id(request),))]
    for row in rows: row['design']=json.loads(row.pop('design_data') or 'null')
    return {'handouts':rows}

@app.post('/api/admin/handout-creator/preview',response_class=HTMLResponse)
def handout_creator_preview(request:Request,payload:dict=Body(...)):
    require_gm(request)
    from .handout_creator import normalize,render_body
    d=normalize(payload.get('design',{}))
    return templates.TemplateResponse('handout_print.html',{'request':request,'handout':{'title':str(payload.get('title',''))[:300],'body':render_body(d),'kind':d['preset'],'image_url':_asset_ref_url(payload.get('image_ref',''))},'theme':d['theme']})

@app.get('/handout/{slug}/export',response_class=HTMLResponse)
def handout_export(request:Request,slug:str):
    if not player_allowed(request): return player_gate_redirect(request)
    from .handout_creator import metadata,clean_html
    row=next((r for r in list_handouts(settings,admin=is_gm(request),campaign_id=_active_campaign_id(request)) if r['slug']==slug),None)
    if not row: raise HTTPException(404,'Handout not found')
    design=metadata(settings,row['id']);row['body']=clean_html(row['body']);row['image_url']=_asset_ref_url(row.get('image_ref',''))
    return templates.TemplateResponse('handout_print.html',{'request':request,'handout':row,'theme':(design or {}).get('theme','parchment')})

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
    except Exception as exc: _log_soft_failure("wiki", "rebuild.failed", exc, path=request.url.path)
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

@app.post('/api/admin/handout-creator/artwork')
async def handout_creator_artwork(request:Request,image:UploadFile=File(...)):
    require_gm(request)
    from PIL import Image, UnidentifiedImageError
    folder=settings.uploads_dir/'handouts';folder.mkdir(parents=True,exist_ok=True)
    token=secrets.token_hex(16);temp=folder/(token+'.tmp')
    try:
        await _stream_upload(image,temp,10*1024*1024,'Artwork exceeds 10 MB')
        with Image.open(temp) as picture:
            if picture.width*picture.height>25000000: raise HTTPException(400,'Artwork is limited to 25 megapixels')
            picture.load();picture.convert('RGBA').save(folder/(token+'.png'))
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError):
        raise HTTPException(400,'Choose a valid PNG, JPEG, WebP, or GIF image')
    finally: temp.unlink(missing_ok=True)
    return {'ref':'upload:handouts/'+token+'.png'}

