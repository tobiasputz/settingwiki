from __future__ import annotations

# Route declarations were extracted from the historical monolithic router.
# They intentionally retain the same handler bodies, endpoint paths and names.
from .route_bridge import bind_composition_root

bind_composition_root(globals())

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
    allowed, wait = _login_allowed(request, "player")
    if not allowed:
        return templates.TemplateResponse("login.html", {"request": request, "mode": "player", "error": f"Too many attempts. Try again in about {max(1, wait // 60)} minute(s).", "title": ensure_built().get("title", "Campaign Atlas")}, status_code=429)
    if settings.player_password and secrets.compare_digest(password, settings.player_password):
        _login_succeeded(request, "player")
        request.session["player_password"] = True
        return RedirectResponse("/", status_code=303)
    _login_failed(request, "player")
    return templates.TemplateResponse("login.html", {"request": request, "mode": "player", "error": "Wrong password.", "title": ensure_built().get("title", "Campaign Atlas")}, status_code=401)

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "mode": "admin", "title": "Seeker Studio"})

@app.post("/admin/login")
def admin_login(request: Request, password: str = Form(...)):
    allowed, wait = _login_allowed(request, "admin")
    if not allowed:
        return templates.TemplateResponse("login.html", {"request": request, "mode": "admin", "error": f"Too many attempts. Try again in about {max(1, wait // 60)} minute(s).", "title": "Seeker Studio"}, status_code=429)
    if secrets.compare_digest(password, settings.admin_password):
        _login_succeeded(request, "admin")
        request.session["admin"] = True
        request.session.pop("view_as_invite_id", None)
        request.session.pop("view_as_label", None)
        return RedirectResponse("/admin", status_code=303)
    _login_failed(request, "admin")
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
        delete_campaign(settings,campaign_id)
        if int(request.session.get("active_campaign_id") or 0)==int(campaign_id):
            request.session.pop("active_campaign_id",None)
        return {"ok":True,"deleted":int(campaign_id),"active_campaign_id":request.session.get('active_campaign_id')}
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
    pages=[p for p in wiki.get("pages",[]) if not is_homebrew_page(p)]
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
    journal_authors=[m for m in campaign_members(settings,cid) if int(m.get("campaign_member") or 0)==1 and str(m.get("role") or "player").lower()=="player"]
    journal_characters=(list_player_characters(settings,invite_id=iid,admin=True,campaign_id=cid) if gm else session_characters)
    can_journal_author=bool(can_author and (iid is not None or journal_authors))
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
        'gm_view':gm,'can_author':can_author,'can_journal_author':can_journal_author,'archive_mode':archive_mode(),'session_characters':session_characters,'journal_characters':journal_characters,'journal_authors':journal_authors,'active_character':active_character,
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
    from .handout_creator import metadata, clean_html
    row["body"]=clean_html(row["body"]); row["theme"]=(metadata(settings,row["id"]) or {}).get("theme","parchment")
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
    return _asset_file_response(path)

@app.get("/characters", response_class=HTMLResponse)
def characters_page(request: Request):
    if not player_allowed(request): return player_gate_redirect(request)
    wiki=_visible_wiki(request); maps=list_maps(settings,public=True); iid=_invite_id(request); admin_view=is_gm(request)
    cid=_active_campaign_id(request); chars=list_player_characters(settings,invite_id=iid,admin=admin_view,campaign_id=cid)
    for c in chars:
        link=foundry_link_for_character(settings,int(c['id']))
        c['foundry_actor_id']=str((link or {}).get('actor_id') or '')
        c['foundry_linked']=bool(link and not link.get('stale'))
    return templates.TemplateResponse("characters.html",{"request":request,"wiki":wiki,"maps":maps,"characters":chars,"player":current_player_invite(request),"admin_view":admin_view,"character_campaigns":list_campaigns(settings,invite_id=iid,admin=admin_view,include_archived=admin_view),"foundry_actors":foundry_actors(settings,cid)})

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
    return templates.TemplateResponse("character.html",{"request":request,"wiki":wiki,"maps":maps,"character":char,"can_edit":can_edit,"admin_view":admin_view,"wiki_pages":wiki.get("pages",[]),"character_campaigns":list_campaigns(settings,invite_id=iid,admin=admin_view,include_archived=admin_view),"character_sessions":list_sessions(settings,public=False,campaign_id=cid),"foundry_actor":foundry_view,"foundry_actors":foundry_actors(settings,cid) if can_edit else []})

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
        except Exception as exc: log_best_effort(settings,"characters","character_asset.cleanup",exc,path=str(path),meta={"character_id":character_id})
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
        except Exception as cleanup_exc: log_best_effort(settings,"characters","character_asset.rollback_cleanup",cleanup_exc,path=str(path),meta={"character_id":character_id})
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
        except Exception as exc: log_best_effort(settings,"characters","character_asset.delete_cleanup",exc,path=str(path),meta={"image_id":image_id})
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
    return _asset_file_response(path)

