from __future__ import annotations

# Route declarations were extracted from the historical monolithic router.
# They intentionally retain the same handler bodies, endpoint paths and names.
from .route_bridge import bind_composition_root

bind_composition_root(globals())

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

