from __future__ import annotations

# Route declarations were extracted from the historical monolithic router.
# They intentionally retain the same handler bodies, endpoint paths and names.
from .route_bridge import bind_composition_root

bind_composition_root(globals())

@app.get("/campaign", response_class=HTMLResponse)
def living_campaign_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    iid=_invite_id(request); gm=is_gm(request); cid=_active_campaign_id(request); wiki=_visible_wiki(request); maps=list_maps(settings,public=not gm)
    chars=list_player_characters(settings,invite_id=iid,admin=gm,campaign_id=cid)
    journal_authors=[m for m in campaign_members(settings,cid) if int(m.get("campaign_member") or 0)==1 and str(m.get("role") or "player").lower()=="player"]
    for c in chars:
        owner=gm or int(c.get("invite_id") or -1)==int(iid or -2)
        c["arcs"]=character_arcs(settings,int(c["id"]),owner=owner)
        c["relationships"]=character_relationships(settings,int(c["id"]),owner=owner)
    can_author = gm or (not archive_mode() and bool(current_player_invite(request)) and player_role(request) == "player")
    journals=(list_party_journals(settings,admin=True,campaign_id=cid) if gm else ([] if iid is None else list_journals(settings,iid,admin=False,campaign_id=cid)))
    journal_characters=(chars if gm else [c for c in chars if iid is not None and int(c.get("invite_id") or -1)==int(iid)])
    can_journal_author=bool(can_author and (iid is not None or journal_authors))
    return templates.TemplateResponse("living.html",{
        "request":request,"wiki":wiki,"maps":maps,"gm_view":gm,"player":current_player_invite(request),
        "threads":list_threads(settings,admin=gm,invite_id=iid,campaign_id=cid),"fronts":list_fronts(settings,admin=gm,invite_id=iid,campaign_id=cid),
        "rumors":list_rumors(settings,admin=gm,campaign_id=cid),"journals":journals,
        "characters":chars,"notifications":list_notifications(settings,iid,admin=gm,campaign_id=cid),"runtime_states":runtime_states(settings,admin=gm),
        "submissions":list_submissions(settings,invite_id=iid,admin=gm,campaign_id=cid),"calendar":_calendar_config(),"can_author":can_author,"can_contribute":bool(can_author and not gm and iid is not None),"can_journal_author":can_journal_author,"archive_mode":archive_mode(),
        "journal_characters":journal_characters,"journal_authors":journal_authors,
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
    payload=_campaign_payload(request,payload)
    iid=_invite_id(request)
    if is_gm(request):
        target_iid=payload.get("author_invite_id")
        if payload.get("id") and not target_iid:
            with connect(settings) as conn:
                row=conn.execute("SELECT invite_id FROM player_journals WHERE id=?",(int(payload["id"]),)).fetchone()
            target_iid=(int(row["invite_id"]) if row else None)
        try: target_iid=int(target_iid) if target_iid is not None else None
        except (TypeError,ValueError): target_iid=None
        if target_iid is None or not invite_has_campaign(settings,target_iid,_active_campaign_id(request)):
            raise HTTPException(400,"Choose a player at this table for the journal entry.")
        iid=target_iid
    if iid is None:raise HTTPException(403,"A personal invitation is required for journals.")
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
    except Exception as exc:_log_soft_failure("wiki", "rebuild.failed", exc, path=request.url.path)
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
    if src.suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.gif'}:return _asset_file_response(src)
    import hashlib
    from PIL import Image,ImageOps
    thumb_dir=settings.build_dir/'media-thumbs';thumb_dir.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256((ref+str(src.stat().st_mtime_ns)).encode()).hexdigest()[:24];out=thumb_dir/(key+'.webp')
    if not out.exists():
        try:
            with Image.open(src) as im:
                im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((520,360));im.save(out,'WEBP',quality=78,method=4)
        except Exception:return _asset_file_response(src)
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
        except Exception as exc: log_best_effort(settings,"archive","portable_archive.cleanup",exc,path=str(tmp))

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

