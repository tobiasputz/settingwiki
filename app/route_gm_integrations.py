from __future__ import annotations

# Route declarations were extracted from the historical monolithic router.
# They intentionally retain the same handler bodies, endpoint paths and names.
from .route_bridge import bind_composition_root

bind_composition_root(globals())

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
    return templates.TemplateResponse('gm_integrations.html', {
        'request':request,'wiki':_visible_wiki(request),'maps':list_maps(settings,public=True),
        'integration':cfg,'campaign':camp,'foundry':foundry_state(settings,cid),
        'foundry_actors':foundry_actors(settings,cid),'foundry_commands':recent_foundry_commands(settings,cid,50),
    })

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
        'command_log':recent_foundry_commands(settings,cid,50),
        'project_tex_files':[f['path'] for f in list_project_files(settings) if f.get('suffix')=='.tex'],
    })

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

@app.get('/api/v6/foundry/asset/{campaign_id}/{asset_path:path}')
def v613_foundry_asset(campaign_id:int,asset_path:str,sig:str=''):
    rel=unquote(asset_path).lstrip('/')
    expected=_foundry_asset_signature(campaign_id,rel)
    if not sig or not secrets.compare_digest(expected,str(sig)):
        raise HTTPException(404,'Asset not found.')
    base=(settings.uploads_dir/'foundry'/str(int(campaign_id))).resolve()
    path=(base/rel).resolve()
    if base not in path.parents or not path.is_file():raise HTTPException(404,'Asset not found.')
    return _asset_file_response(path,headers={'Cache-Control':'private, max-age=86400','Access-Control-Allow-Origin':'*'})

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
    payload=entry.get('payload') or {};gm=is_gm(request)
    full=gm or str(payload.get('codex_visibility') or 'field_notes').lower()=='full'
    return templates.TemplateResponse('bestiary_entry.html',{
        'request':request,'wiki':wiki,'maps':list_maps(settings,public=not gm),
        'entry':entry,'monster':payload,'show_statblock':full,'gm_view':gm,
        'codex_sections':_codex_section_visibility(payload,gm=gm),
        'player_codex_sections':_codex_section_visibility(payload,gm=False),
    })

@app.put('/api/bestiary/{entry_id}')
def v704_bestiary_update(request:Request,entry_id:int,payload:dict=Body(...)):
    require_gm(request);cid=_active_campaign_id(request)
    current=next((x for x in list_foundry_prepared_content(settings,cid) if int(x.get('id') or 0)==int(entry_id)),None)
    if not current or str(current.get('kind') or '') not in {'monster','npc'}:
        raise HTTPException(404,'Monster Codex entry not found.')
    data=dict(current.get('payload') or {})
    incoming=payload.get('payload') if isinstance(payload.get('payload'),dict) else {}
    data.update(incoming)
    data['codex_publish']=True
    visibility=str(data.get('codex_visibility') or 'field_notes').lower()
    data['codex_visibility']='full' if visibility=='full' else 'field_notes'
    section_raw=data.get('codex_sections') if isinstance(data.get('codex_sections'),dict) else {}
    data['codex_sections']={key:bool(section_raw.get(key,True)) for key in CODEX_SECTION_KEYS}
    if data.get('aon_url'):
        data['description']=sanitize_aon_summary(str(data.get('description') or ''),title=str(payload.get('title') or current.get('title') or ''))
        data['codex_blurb']=sanitize_aon_summary(str(data.get('codex_blurb') or ''),title=str(payload.get('title') or current.get('title') or ''))
    try:
        return save_foundry_prepared_content(settings,cid,{
            'id':int(entry_id),'kind':current.get('kind'),'title':payload.get('title',current.get('title')),
            'subtitle':payload.get('subtitle',current.get('subtitle')),'target_type':current.get('target_type') or 'world',
            'summary':payload.get('summary',current.get('summary')),'tags':payload.get('tags',current.get('tags')),
            'payload':data,
        })
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.delete('/api/bestiary/{entry_id}')
def v704_bestiary_remove(request:Request,entry_id:int):
    """Remove an entry from the Codex without destroying its Workshop source."""
    require_gm(request);cid=_active_campaign_id(request)
    current=next((x for x in list_foundry_prepared_content(settings,cid) if int(x.get('id') or 0)==int(entry_id)),None)
    if not current or str(current.get('kind') or '') not in {'monster','npc'}:
        raise HTTPException(404,'Monster Codex entry not found.')
    data=dict(current.get('payload') or {});data['codex_publish']=False;data['publish_codex']=False
    save_foundry_prepared_content(settings,cid,{**current,'payload':data})
    return {'ok':True,'removed':True,'source_preserved':True}

@app.get('/homebrew', response_class=HTMLResponse)
def homebrew_library_page(request:Request):
    if not player_allowed(request):return player_gate_redirect(request)
    cid=_active_campaign_id(request);gm=is_gm(request);wiki=_visible_wiki(request)
    source_sections=_homebrew_source_sections(wiki)
    rows=_dedupe_exported_homebrew_rows(list_foundry_prepared_content(settings,cid),source_sections)
    heritage_index,feat_index=_homebrew_library_indexes(source_sections,rows,include_drafts=gm)
    return templates.TemplateResponse('homebrew.html',{
        'request':request,'wiki':wiki,'maps':list_maps(settings,public=not gm),'gm_view':gm,
        'homebrew_sections':group_homebrew(rows,include_drafts=gm),'source_sections':source_sections,
        'heritage_index':heritage_index,'feat_index':feat_index,
        'foundry_actors':foundry_actors(settings,cid) if gm else [],
        'project_tex_files':[f['path'] for f in list_project_files(settings) if f.get('suffix')=='.tex'] if gm else [],
    })

@app.get('/homebrew/entry/{entry_id}', response_class=HTMLResponse)
def homebrew_structured_bundle_detail(request:Request,entry_id:int):
    if not player_allowed(request):return player_gate_redirect(request)
    cid=_active_campaign_id(request);gm=is_gm(request);row=_homebrew_entry_or_404(cid,entry_id)
    payload=dict(row.get('payload') or {});document=str(payload.get('homebrew_document') or '').strip().lower()
    if document not in {'ancestry','archetype'}:raise HTTPException(404,'This Homebrew entry is not a complete ancestry or archetype.')
    meta=classify_homebrew(row)
    if not gm and not meta.get('published'):raise HTTPException(404,'Homebrew entry not found.')
    rules=[dict(x) for x in (payload.get('bundle_feats') or []) if isinstance(x,dict)]
    rules.sort(key=lambda x:(int(x.get('level') or 0),str(x.get('title') or '').casefold()))
    return templates.TemplateResponse('homebrew_bundle.html',{
        'request':request,'wiki':_visible_wiki(request),'maps':list_maps(settings,public=not gm),'gm_view':gm,
        'entry':row,'payload':payload,'meta':meta,'document':document,'rules':rules,
    })

@app.get('/homebrew/source/{owner_slug}', response_class=HTMLResponse)
def homebrew_source_detail(request:Request,owner_slug:str):
    if not player_allowed(request):return player_gate_redirect(request)
    gm=is_gm(request);wiki=_visible_wiki(request);bundle=_source_homebrew_bundle_or_404(wiki,owner_slug)
    return templates.TemplateResponse('homebrew_source.html',{
        'request':request,'wiki':wiki,'maps':list_maps(settings,public=not gm),'gm_view':gm,
        'bundle':bundle,'group':bundle['group'],
    })

@app.post('/api/homebrew/source/{owner_slug}/forge')
def homebrew_source_open_in_forge(request:Request,owner_slug:str):
    require_gm(request);cid=_active_campaign_id(request);bundle=_source_homebrew_bundle_or_404(_visible_wiki(request),owner_slug)
    section=str(bundle.get('section') or '').strip().lower();source=str((bundle.get('group') or {}).get('source_file') or '').replace('\\','/').strip('/')
    if section not in {'ancestry','archetype'}:raise HTTPException(400,'Complete Forge editing is available for source-backed ancestries and archetypes.')
    existing=next((row for row in list_foundry_prepared_content(settings,cid) if truthy((row.get('payload') or {}).get('source_linked')) and str((row.get('payload') or {}).get('source_link_path') or '').replace('\\','/').strip('/')==source and str((row.get('payload') or {}).get('homebrew_document') or '').strip().lower()==section),None)
    if existing:return {'ok':True,'entry':existing,'created':False,'url':f"/gm/foundry-workshop?entry={int(existing['id'])}"}
    prepared=_source_bundle_forge_payload(bundle);saved=save_foundry_prepared_content(settings,cid,prepared)
    return {'ok':True,'entry':saved,'created':True,'url':f"/gm/foundry-workshop?entry={int(saved['id'])}"}

@app.post('/api/homebrew/source/{owner_slug}/foundry')
def homebrew_source_foundry_push(request:Request,owner_slug:str):
    require_gm(request);cid=_active_campaign_id(request);wiki=_visible_wiki(request)
    bundle=_source_homebrew_bundle_or_404(wiki,owner_slug);section=str(bundle['section'] or 'other')
    group=bundle['group'];pages=group.get('pages') or []
    root=next((p for p in pages if str(p.get('slug') or '')==str(owner_slug)),pages[0] if pages else None)
    if not root:raise HTTPException(404,'Homebrew source entry not found.')
    rules=[]
    for rule in group.get('rules') or []:
        if str(rule.get('kind') or '') not in {'feat','action'}:continue
        rules.append({
            'kind':str(rule.get('kind') or 'feat'),'title':str(rule.get('title') or 'Untitled'),
            'level':int(rule.get('level') or 0),'traits':list(rule.get('traits') or []),
            'description_html':_source_rule_foundry_html(rule),'description':str(rule.get('description') or rule.get('plain_text') or ''),
            'access':str(rule.get('access') or ''),'prerequisites':str(rule.get('prerequisites') or ''),'frequency':str(rule.get('frequency') or ''),
            'trigger':str(rule.get('trigger') or ''),'requirements':str(rule.get('requirements') or ''),'special':str(rule.get('special') or ''),
            'action_cost':str(rule.get('action_cost') or ''),'source_page_slug':str(rule.get('source_page_slug') or ''),
        })
    lore_html=''.join(
        f"<h2>{html.escape(str(p.get('title') or ''))}</h2>{str(p.get('lore_html') or '')}"
        for p in group.get('lore_pages') or []
    )
    payload={
        'title':str(group.get('name') or root.get('title') or 'Custom Homebrew'),'section':section,
        'owner_slug':str(owner_slug),'source_file':str(group.get('source_file') or root.get('source_file') or ''),
        'description_html':lore_html or str(root.get('html') or ''),'description':'\n\n'.join(str(p.get('lore_plain') or '') for p in group.get('lore_pages') or []),
        'rules':rules,'folder_name':f"Seeker · {str(group.get('name') or root.get('title') or 'Custom Homebrew')}",
    }
    if section=='ancestry':
        ancestry=dict(group.get('ancestry') or {})
        # Keep bridge defaults for genuinely unspecified fields, but pass every
        # ancestry chassis value that the source parser could identify.
        payload['ancestry']={
            'hp':int(ancestry.get('hp') or 8),'size':str(ancestry.get('size') or 'med'),
            'speed':int(ancestry.get('speed') or 25),'reach':int(ancestry.get('reach') or 5),
            'vision':str(ancestry.get('vision') or 'normal'),'languages':str(ancestry.get('languages') or 'common'),
            'additional_languages':int(ancestry.get('additional_languages') or 0),'boosts':str(ancestry.get('boosts') or ''),
            'free_boosts':int(ancestry.get('free_boosts') if ancestry.get('free_boosts') is not None else 2),
            'flaws':str(ancestry.get('flaws') or ''),'traits':str(ancestry.get('traits') or ''),
        }
        payload['heritages']=[dict(x) for x in (group.get('heritages') or []) if isinstance(x,dict)]
    command_type='push_ancestry_bundle' if section=='ancestry' else 'push_homebrew_rule_bundle'
    command=queue_foundry_command(settings,cid,command_type,payload,scope='world',requested_by=requester_label(request))
    return {'ok':True,'command':command,'rules':len(rules),'section':section}

@app.put('/api/homebrew/{entry_id}')
def homebrew_update(request:Request,entry_id:int,payload:dict=Body(...)):
    require_gm(request);cid=_active_campaign_id(request);current=_homebrew_entry_or_404(cid,entry_id)
    data=dict(current.get('payload') or {});incoming=payload.get('payload') if isinstance(payload.get('payload'),dict) else {};data.update(incoming)
    if 'homebrew_publish' in incoming:data['homebrew_publish']=truthy(incoming.get('homebrew_publish'))
    section=str(data.get('library_section') or 'auto').strip().lower()
    if section not in {'auto',*HOME_BREW_SECTIONS.keys()}:data['library_section']='auto'
    requested_kind=str(payload.get('kind') or current.get('kind') or 'homebrew').strip().lower()
    if requested_kind not in NON_MONSTER_KINDS:
        raise HTTPException(400,'Homebrew entries can only be feats, actions, items, or freeform homebrew.')
    try:
        return save_foundry_prepared_content(settings,cid,{
            'id':entry_id,'kind':requested_kind,
            'title':payload.get('title',current.get('title')),'subtitle':payload.get('subtitle',current.get('subtitle')),
            'target_type':current.get('target_type') or 'world','summary':payload.get('summary',current.get('summary')),
            'tags':payload.get('tags',current.get('tags')),'payload':data,
        })
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.delete('/api/homebrew/{entry_id}')
def homebrew_delete(request:Request,entry_id:int):
    require_gm(request);cid=_active_campaign_id(request);_homebrew_entry_or_404(cid,entry_id);delete_foundry_prepared_content(settings,cid,entry_id);return {'ok':True}

@app.get('/api/homebrew/{entry_id}/latex')
def homebrew_latex(request:Request,entry_id:int):
    require_gm(request);row=_homebrew_entry_or_404(_active_campaign_id(request),entry_id);payload=dict(row.get('payload') or {})
    suggested=str(payload.get('latex_export_path') or _suggest_homebrew_tex_path(row))
    return {
        'id':entry_id,'snippet':homebrew_latex_snippet(row),'suggested_path':suggested,'targets':_project_latex_targets(),
        'selected_heading':{
            'level':str(payload.get('latex_heading_level') or ''),'title':str(payload.get('latex_heading_title') or ''),
            'index':int(payload.get('latex_heading_index') or 0),
        },
    }

@app.post('/api/homebrew/{entry_id}/latex/write')
def homebrew_latex_write(request:Request,entry_id:int,payload:dict=Body(...)):
    require_admin(request);cid=_active_campaign_id(request);row=_homebrew_entry_or_404(cid,entry_id)
    rel=str(payload.get('path') or _suggest_homebrew_tex_path(row)).replace('\\','/').strip('/')
    if not rel.lower().endswith('.tex'):raise HTTPException(400,'Homebrew LaTeX must be written to a .tex file.')
    snippet=str(payload.get('snippet') or homebrew_latex_snippet(row))
    heading_level=str(payload.get('heading_level') or '').strip().lower();heading_title=str(payload.get('heading_title') or '').strip()
    try:heading_index=max(0,int(payload.get('heading_index') or 0))
    except (TypeError,ValueError):heading_index=0

    # A Forge item has one generated LaTeX identity. Remove the old marker from
    # every project file before writing/moving it so changing the target chapter
    # can never leave a second copy behind.
    removed_any=False;changed_paths=[]
    for info in list_project_files(settings):
        if str(info.get('suffix') or '').lower()!='.tex':continue
        path=str(info.get('path') or '');src=safe_project_path(settings,path)
        try:text=src.read_text(encoding='utf-8',errors='replace')
        except OSError:continue
        cleaned,removed=remove_latex_block(text,entry_id)
        if removed:
            removed_any=True
            if path!=rel:
                save_text_file(settings,path,cleaned);changed_paths.append(path)
            else:
                # Reuse the cleaned version below instead of writing twice.
                pass

    target=safe_project_path(settings,rel)
    existing=target.read_text(encoding='utf-8',errors='replace') if target.exists() else '% Seeker homebrew\n'
    existing,_=remove_latex_block(existing,entry_id)
    duplicate=bool(not removed_any and _manual_homebrew_duplicate(existing,row))
    if duplicate:
        rendered=existing
    else:
        rendered=insert_latex_block_in_heading(existing,entry_id,snippet,heading_level=heading_level,heading_title=heading_title,heading_index=heading_index)
    result=save_text_file(settings,rel,rendered)

    # Persist the link between the Forge entry and its LaTeX representation. The
    # Homebrew library uses it to merge the generated/source-backed views.
    data=dict(row.get('payload') or {});data.update({
        'latex_exported':True,'latex_export_path':rel,'latex_heading_level':heading_level,
        'latex_heading_title':heading_title,'latex_heading_index':heading_index,
    })
    save_foundry_prepared_content(settings,cid,{**row,'payload':data})
    try:build_wiki(settings)
    except Exception as exc:result['wiki_warning']=str(exc)
    result.update({'ok':True,'snippet':snippet,'duplicate_detected':duplicate,'changed_paths':changed_paths,'path':rel});return result

@app.get('/gm/media', response_class=HTMLResponse)
def v6_media_page(request: Request, session_id: int|None=None):
    require_gm(request);cid=_active_campaign_id(request);sessions=list_sessions(settings,campaign_id=cid)
    session=next((s for s in sessions if session_id and int(s['id'])==int(session_id)),None)
    if not session:session=next((s for s in sessions if s.get('status') in {'live','planned'}),None)
    items=list_media_items(settings,cid,int(session['id'])) if session else []
    return templates.TemplateResponse('gm_media.html', {'request':request,'wiki':_visible_wiki(request),'maps':list_maps(settings,public=True),'sessions':sessions,'session':session,'media_items':items,'display_state':display_state(settings,cid)})

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

