from __future__ import annotations

# Route declarations were extracted from the historical monolithic router.
# They intentionally retain the same handler bodies, endpoint paths and names.
from .route_bridge import bind_composition_root

bind_composition_root(globals())

@app.get('/api/v6/integrations')
def v6_integrations_get(request: Request):
    require_gm(request);return integration_config(settings,_active_campaign_id(request),include_secret=True)

@app.put('/api/v6/integrations')
def v6_integrations_save(request: Request,payload:dict=Body(...)):
    require_gm(request);return save_integration_config(settings,_active_campaign_id(request),payload)

@app.post('/api/v6/integrations/rotate/{kind}')
def v6_integrations_rotate(request: Request,kind:str):
    require_gm(request)
    try:return rotate_integration_token(settings,_active_campaign_id(request),kind)
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.post('/api/v6/discord/test')
def v6_discord_test(request: Request):
    require_gm(request);cid=_active_campaign_id(request);camp=get_campaign(settings,cid) or {}
    cfg=integration_config(settings,cid,include_secret=True)
    mention=str(cfg.get('discord_mention') or '').strip()
    if mention.lower().replace(' ','') in {'everyone','@everyone'}: mention='@everyone'
    elif mention.lower().replace(' ','') in {'here','@here'}: mention='@here'
    elif re.fullmatch(r'\d{2,24}',mention): mention=f'<@&{mention}>'
    message=f"✦ Seeker is connected to **{camp.get('name','this campaign')}**."
    if mention: message=f"{mention}\n{message}"
    try:return discord_post(settings,cid,message)
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.post('/api/v6/discord/send')
def v6_discord_send(request: Request,payload:dict=Body(...)):
    require_gm(request)
    try:return discord_post(settings,_active_campaign_id(request),str(payload.get('content') or ''))
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.options('/api/v6/foundry/push/{campaign_id}')
def v6_foundry_push_options(campaign_id:int):
    return Response(status_code=204,headers=_FOUNDRY_CORS)

@app.options('/api/v6/foundry/push/{campaign_id}/ack')
def v61_foundry_push_ack_options(campaign_id:int):
    return Response(status_code=204,headers=_FOUNDRY_CORS)

@app.options('/api/v6/foundry/push/{campaign_id}/commands')
def v614_foundry_commands_options(campaign_id:int):
    return Response(status_code=204,headers=_FOUNDRY_CORS)

@app.options('/api/v6/foundry/push/{campaign_id}/commands/start')
def v704_foundry_commands_start_options(campaign_id:int):
    return Response(status_code=204,headers=_FOUNDRY_CORS)

@app.post('/api/v6/foundry/push/{campaign_id}')
def v6_foundry_push(campaign_id:int,token:str='',payload:dict=Body(...)):
    try:
        result=foundry_accept(settings,campaign_id,token,payload)
        # V7-managed Foundry documents piggy-back on the existing authenticated
        # heartbeat. Ingestion is additive and never blocks the table bridge if
        # a stale V7 link happens to be malformed.
        try: ingest_foundry_managed_state(settings,campaign_id,payload)
        except Exception as exc: _log_soft_failure("foundry", "managed-ingest.failed", exc, path=f"/api/v6/foundry/push/{campaign_id}")
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
        except Exception as exc:
            result['v7_links']=0
            _log_soft_failure("foundry", "command-ingest.failed", exc, path=f"/api/v6/foundry/push/{campaign_id}/ack")
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

@app.post('/api/v6/foundry/push/{campaign_id}/commands/start')
def v704_foundry_commands_start(campaign_id:int,token:str='',payload:dict=Body(...)):
    try:
        ids=payload.get('ids') if isinstance(payload.get('ids'),list) else []
        return JSONResponse(start_foundry_commands(settings,campaign_id,token,ids),headers=_FOUNDRY_CORS)
    except PermissionError as exc:
        return JSONResponse({'detail':str(exc)},status_code=403,headers=_FOUNDRY_CORS)
    except Exception:
        return JSONResponse({'detail':'Seeker could not mark Foundry actions as executing.'},status_code=500,headers=_FOUNDRY_CORS)

@app.get('/api/v6/foundry/commands')
def v704_foundry_command_list(request:Request):
    require_gm(request)
    return {'commands':recent_foundry_commands(settings,_active_campaign_id(request),50)}

@app.get('/api/v6/foundry/commands/{command_id}')
def v704_foundry_command_status(request:Request,command_id:int):
    if not player_allowed(request): raise HTTPException(401)
    cid=_active_campaign_id(request)
    row=get_foundry_command(settings,cid,command_id)
    if not row: raise HTTPException(404,'Foundry action not found.')
    if not is_gm(request):
        label=requester_label(request)
        if str(row.get('requested_by') or '') != str(label):
            raise HTTPException(403,'You can only view your own Foundry actions.')
    return row

@app.post('/api/v6/foundry/commands/{command_id}/retry')
def v704_foundry_command_retry(request:Request,command_id:int):
    require_gm(request)
    try:return {'ok':True,'command':retry_foundry_command(settings,_active_campaign_id(request),command_id)}
    except ValueError as exc:raise HTTPException(400,str(exc))

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
    out=settings.build_dir/'seeker-foundry-bridge-1.10.1.zip'
    build_foundry_module_zip(settings,_external_base_url(request),out)
    return FileResponse(out,filename='seeker-foundry-bridge.zip',media_type='application/zip',headers={'Cache-Control':'public, max-age=300','Access-Control-Allow-Origin':'*'})

@app.get('/api/v6/foundry/module.zip')
def v6_foundry_module(request:Request):
    require_gm(request)
    out=settings.build_dir/'seeker-foundry-bridge-1.10.1.zip'
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
    prepared=dict(payload or {})
    content=dict(prepared.get('payload') or {}) if isinstance(prepared.get('payload'),dict) else {}
    source_sync=None
    if truthy(content.get('source_linked')):
        rel=str(content.get('source_link_path') or '').replace('\\','/').strip('/')
        if not rel or not rel.lower().endswith('.tex'):
            raise HTTPException(400,'This source-linked Forge entry no longer points to a valid .tex file.')
        source=safe_project_path(settings,rel)
        if not source.exists():raise HTTPException(404,'The linked LaTeX source file no longer exists.')
        try:existing=source.read_text(encoding='utf-8',errors='replace')
        except OSError as exc:raise HTTPException(500,'Could not read the linked LaTeX source.') from exc
        rendered,content,changes=sync_source_linked_bundle_text(existing,{**prepared,'payload':content})
        prepared['payload']=content
        if rendered!=existing:
            save_text_file(settings,rel,rendered)
            source_sync={'path':rel,'changes':changes,'changed':True}
        else:
            source_sync={'path':rel,'changes':changes,'changed':False}
    try:
        out=save_foundry_prepared_content(settings,cid,prepared)
        if source_sync and source_sync.get('changed'):
            try:build_wiki(settings)
            except Exception as exc:source_sync['wiki_warning']=str(exc)
        _prune_unused_foundry_images(cid)
        if source_sync:out['source_sync']=source_sync
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
    actor_uuid=''
    if target_type=='actor':
        actor_uuid=str(next((x.get('actor_uuid') for x in foundry_actors(settings,cid) if str(x.get('actor_id'))==actor_id),'') or '')
    bundle=_forge_bundle_foundry_payload(item)
    if bundle:
        if target_type!='world': raise HTTPException(400,'Ancestries and archetypes are imported to the Foundry world, not directly onto one actor.')
        command_type,bundle_payload=bundle
        command=queue_foundry_command(settings,cid,command_type,bundle_payload,scope='world',requested_by=requester_label(request))
        return {'ok':True,'command':command,'bundle':True,'section':bundle_payload.get('section'),'rules':len(bundle_payload.get('rules') or [])}
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
        'actor_uuid':actor_uuid,
        'data':content_data,
    },actor_id=actor_id,scope=target_type,requested_by=requester_label(request))
    return {'ok':True,'command':command}

@app.get('/api/v61/characters/{character_id}/foundry-state')
def v71_character_foundry_state(request:Request,character_id:int):
    if not player_allowed(request): raise HTTPException(401)
    _character_owned(request,character_id)
    link=foundry_link_for_character(settings,character_id)
    if not link or not link.get('actor_id'): raise HTTPException(404,'This character is not linked to a Foundry actor.')
    return {
        'ok':True,'actor_id':link.get('actor_id'),'actor_uuid':link.get('actor_uuid') or '',
        'name':link.get('name') or '','received_at':link.get('received_at'),
        'sheet':link.get('sheet') or {},
    }

@app.post('/api/v61/characters/{character_id}/foundry/action')
def v61_character_foundry_action(request:Request,character_id:int,payload:dict=Body(...)):
    if not player_allowed(request): raise HTTPException(401)
    char=_character_owned(request,character_id)
    link=foundry_link_for_character(settings,character_id)
    if not link or not link.get('actor_id'): raise HTTPException(400,'This character is not linked to a Foundry actor.')
    action=str(payload.get('action') or '').strip().lower()
    if action in {'adjust_resource','set_resource'}:
        resource=str(payload.get('resource') or '').strip().lower()
        if resource not in {'hp','temp_hp','hero_points','focus'}: raise HTTPException(400,'Unsupported resource.')
        command_payload={'resource':resource,'character_id':int(character_id),'character_name':char.get('name'),'actor_uuid':str(link.get('actor_uuid') or '')}
        if action=='set_resource':
            try:value=max(0,min(999999,int(payload.get('value'))))
            except Exception:raise HTTPException(400,'value must be an integer.')
            command_payload.update({'mode':'set','value':value})
        else:
            try: delta=max(-999999,min(999999,int(payload.get('delta') or 0)))
            except Exception: raise HTTPException(400,'delta must be an integer.')
            if delta==0: raise HTTPException(400,'delta cannot be zero.')
            command_payload.update({'mode':'adjust','delta':delta})
        command=queue_foundry_command(settings,int(link['campaign_id']),'adjust_resource',command_payload,actor_id=str(link['actor_id']),requested_by=requester_label(request))
    elif action=='adjust_item_quantity':
        item_id=str(payload.get('item_id') or '').strip();
        if not item_id: raise HTTPException(400,'item_id is required.')
        try: delta=max(-99,min(99,int(payload.get('delta') or 0)))
        except Exception: raise HTTPException(400,'delta must be an integer.')
        if delta==0: raise HTTPException(400,'delta cannot be zero.')
        command=queue_foundry_command(settings,int(link['campaign_id']),'adjust_item_quantity',{'item_id':item_id,'delta':delta,'character_id':int(character_id),'character_name':char.get('name'),'actor_uuid':str(link.get('actor_uuid') or '')},actor_id=str(link['actor_id']),requested_by=requester_label(request))
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
    return _asset_file_response(path)

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

