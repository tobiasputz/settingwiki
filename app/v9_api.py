from __future__ import annotations

from typing import Any, Callable

from fastapi import Body, HTTPException, Request

from .config import Settings
from .storage import connect
from .features import list_sessions, list_handouts
from .maps import list_maps
from .v7 import (
    list_entities, get_entity, list_encounters, save_relation, mark_sync_resolved,
)
from .v6 import queue_foundry_command, create_backup, list_backups, restore_backup
from .homebrew_global import list_global_homebrew, touch_global_homebrew
from .v9 import (
    session_director, save_session_director, knowledge_fields, save_knowledge_field, reveal_knowledge_field,
    timeline_with_consequences, save_timeline_consequence, relationship_suggestions, decide_relationship_suggestion,
    universal_search, foundry_sync_matrix, asset_library, save_asset_metadata, link_asset,
    list_map_states, capture_map_state, apply_map_state, discover_extensions, migration_status, extension_foundry_action,
)


def register_v9_routes(app, settings: Settings, helpers: dict[str, Callable[..., Any]]) -> None:
    active_campaign_id=helpers['active_campaign_id'];visible_wiki=helpers['visible_wiki'];require_gm=helpers['require_gm'];require_admin=helpers['require_admin'];requester_label=helpers['requester_label'];invite_id=helpers.get('invite_id')

    def _session_or_404(cid:int,session_id:int)->dict:
        row=next((x for x in list_sessions(settings,campaign_id=cid) if int(x['id'])==int(session_id)),None)
        if not row: raise HTTPException(404,'Session not found.')
        return row

    @app.get('/api/v9/state')
    def v9_state(request:Request):
        require_gm(request);cid=active_campaign_id(request);sessions=list_sessions(settings,campaign_id=cid)
        current=next((s for s in sessions if s.get('status')=='live'),None) or next((s for s in sessions if s.get('status')=='planned'),None)
        return {
            'version':'9.0.4','sessions':sessions,'session':current,
            'director':session_director(settings,cid,int(current['id'])) if current else None,
            'encounters':list_encounters(settings,cid,int(current['id'])) if current else list_encounters(settings,cid)[:20],
            'entities':list_entities(settings,cid,tracked_only=True),
            'handouts':list_handouts(settings,admin=True,campaign_id=cid),'maps':list_maps(settings,public=False),
            'homebrew':list_global_homebrew(settings,cid),'sync':foundry_sync_matrix(settings,cid),
            'timeline':timeline_with_consequences(settings,cid,admin=True),'extensions':discover_extensions(settings),
        }

    @app.get('/api/v9/session/{session_id}/director')
    def v9_director_get(request:Request,session_id:int):
        require_gm(request);cid=active_campaign_id(request);_session_or_404(cid,session_id);return session_director(settings,cid,session_id)

    @app.put('/api/v9/session/{session_id}/director')
    def v9_director_save(request:Request,session_id:int,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request);_session_or_404(cid,session_id)
        return save_session_director(settings,cid,session_id,payload)

    @app.post('/api/v9/session/{session_id}/reveal-handout')
    def v9_director_reveal_handout(request:Request,session_id:int,payload:dict=Body(default={})):
        require_gm(request);cid=active_campaign_id(request);_session_or_404(cid,session_id)
        director=session_director(settings,cid,session_id);hid=int(payload.get('handout_id') or director.get('handout_id') or 0)
        if not hid: raise HTTPException(400,'Choose a handout first.')
        now=__import__('time').time()
        with connect(settings) as conn:
            cur=conn.execute("UPDATE handouts SET visibility='players',updated_at=? WHERE id=? AND campaign_id=?",(now,hid,cid))
            if not cur.rowcount: raise HTTPException(404,'Handout not found in this campaign.')
        row=next((h for h in list_handouts(settings,admin=True,campaign_id=cid) if int(h['id'])==hid),None)
        return {'ok':True,'handout':row}

    @app.get('/api/v9/entity/{entity_id}/knowledge')
    def v9_knowledge_get(request:Request,entity_id:int):
        require_gm(request);cid=active_campaign_id(request)
        if not get_entity(settings,cid,entity_id): raise HTTPException(404,'Object not found.')
        return {'fields':knowledge_fields(settings,cid,entity_id,gm=True)}

    @app.post('/api/v9/entity/{entity_id}/knowledge')
    def v9_knowledge_save(request:Request,entity_id:int,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request)
        if not get_entity(settings,cid,entity_id): raise HTTPException(404,'Object not found.')
        try:return save_knowledge_field(settings,cid,entity_id,payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v9/knowledge/{field_id}/reveal')
    def v9_knowledge_reveal(request:Request,field_id:int,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request);ids=payload.get('invite_ids') if isinstance(payload.get('invite_ids'),list) else []
        if payload.get('party'):
            with connect(settings) as conn: ids=[int(r['invite_id']) for r in conn.execute('SELECT invite_id FROM campaign_memberships WHERE campaign_id=? AND invite_id IS NOT NULL',(cid,)).fetchall()]
        try:return reveal_knowledge_field(settings,cid,field_id,[int(x) for x in ids],payload.get('session_id'),revealed=bool(payload.get('revealed',True)))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v9/timeline/{event_id}/consequence')
    def v9_timeline_consequence(request:Request,event_id:int,payload:dict=Body(...)):
        require_gm(request)
        try:return save_timeline_consequence(settings,active_campaign_id(request),event_id,payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v9/relationships/suggestions')
    def v9_relationship_suggestions(request:Request,refresh:int=0):
        require_gm(request);return relationship_suggestions(settings,active_campaign_id(request),visible_wiki(request),refresh=bool(refresh))

    @app.post('/api/v9/relationships/suggestions/{suggestion_id}')
    def v9_relationship_decide(request:Request,suggestion_id:int,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request);status=str(payload.get('status') or 'rejected')
        try:
            row=decide_relationship_suggestion(settings,cid,suggestion_id,status)
            relation=None
            if status=='accepted':
                relation=save_relation(settings,cid,{'source_entity_id':row['source_entity_id'],'target_entity_id':row['target_entity_id'],'relation':payload.get('relation') or row.get('suggested_relation') or 'related to'},actor_label=requester_label(request))
            return {'ok':True,'suggestion':row,'relation':relation}
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v9/search')
    def v9_search(request:Request,q:str=''):
        require_gm(request);return universal_search(settings,active_campaign_id(request),visible_wiki(request),q,gm=True,limit=80)

    @app.get('/api/v9/foundry/sync')
    def v9_sync_state(request:Request):
        require_gm(request);return foundry_sync_matrix(settings,active_campaign_id(request))

    @app.post('/api/v9/foundry/sync/bulk')
    def v9_sync_bulk(request:Request,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request);action=str(payload.get('action') or 'push').lower();ids=[int(x) for x in (payload.get('entity_ids') or [])]
        results=[];errors=[]
        matrix={int(x['entity_id']):x.get('link') for x in foundry_sync_matrix(settings,cid).get('rows',[])}
        for eid in ids[:200]:
            entity=get_entity(settings,cid,eid)
            if not entity: errors.append({'entity_id':eid,'error':'Object not found.'});continue
            try:
                sl=matrix.get(eid)
                if action=='accept_foundry':
                    results.append({'entity_id':eid,'sync':mark_sync_resolved(settings,cid,eid,'accept_foundry')});continue
                data=dict(entity.get('data') or {})
                prepared_kind='monster' if str(entity.get('kind') or '').lower() in {'monster','creature'} else 'npc' if str(entity.get('kind') or '').lower()=='npc' else 'feat' if str(entity.get('kind') or '').lower()=='feat' else 'action' if str(entity.get('kind') or '').lower()=='action' else 'item'
                command_payload={'entity_id':eid,'prepared_kind':prepared_kind,'title':entity.get('name'),'subtitle':entity.get('subtitle') or '','summary':entity.get('summary') or '','tags':', '.join(entity.get('tags') or []),'data':data}
                ctype='sync_entity_document' if sl and sl.get('foundry_uuid') else 'push_prepared_content'
                if ctype=='sync_entity_document':command_payload['foundry_uuid']=sl['foundry_uuid']
                results.append({'entity_id':eid,'command':queue_foundry_command(settings,cid,ctype,command_payload,scope='world',requested_by=requester_label(request))})
            except Exception as exc: errors.append({'entity_id':eid,'error':str(exc)})
        return {'ok':not errors,'results':results,'errors':errors}

    @app.get('/api/v9/assets')
    def v9_assets(request:Request):
        require_gm(request);return asset_library(settings,active_campaign_id(request))

    @app.put('/api/v9/assets/meta')
    def v9_asset_meta(request:Request,payload:dict=Body(...)):
        require_gm(request)
        try:return save_asset_metadata(settings,str(payload.get('ref') or ''),payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v9/assets/link')
    def v9_asset_link(request:Request,payload:dict=Body(...)):
        require_gm(request)
        try:return link_asset(settings,active_campaign_id(request),str(payload.get('ref') or ''),str(payload.get('target_type') or 'entity'),str(payload.get('target_key') or ''),str(payload.get('purpose') or 'art'))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v9/maps/states')
    def v9_map_states(request:Request,map_id:int|None=None):
        require_gm(request);return list_map_states(settings,active_campaign_id(request),map_id)

    @app.post('/api/v9/maps/{map_id}/states')
    def v9_map_state_capture(request:Request,map_id:int,payload:dict=Body(...)):
        require_gm(request)
        try:return capture_map_state(settings,active_campaign_id(request),map_id,str(payload.get('name') or ''),str(payload.get('description') or ''),player_visible=bool(payload.get('player_visible')))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v9/maps/states/{state_id}/apply')
    def v9_map_state_apply(request:Request,state_id:int):
        require_gm(request)
        try:return apply_map_state(settings,active_campaign_id(request),state_id)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v9/homebrew')
    def v9_homebrew(request:Request):
        require_gm(request);return {'entries':list_global_homebrew(settings,active_campaign_id(request)),'scope':'global'}

    @app.post('/api/v9/homebrew/{item_id}/use')
    def v9_homebrew_use(request:Request,item_id:int,payload:dict=Body(default={})):
        require_gm(request);touch_global_homebrew(settings,item_id,active_campaign_id(request),pinned=payload.get('pinned'));return {'ok':True}

    @app.get('/api/v9/backups')
    def v9_backups(request:Request):
        require_gm(request);return {'backups':list_backups(settings),'migration':migration_status(settings)}

    @app.post('/api/v9/backups')
    def v9_backup_create(request:Request,payload:dict=Body(default={})):
        require_gm(request);return create_backup(settings,str(payload.get('label') or 'Campaign Workspace backup'),'manual')

    @app.post('/api/v9/backups/{backup_id}/restore')
    def v9_backup_restore(request:Request,backup_id:int):
        require_admin(request)
        try:return restore_backup(settings,backup_id)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v9/offline-pack')
    def v9_offline_pack(request:Request,session_id:int|None=None):
        require_gm(request);cid=active_campaign_id(request);urls=['/','/portal','/homebrew','/timeline','/characters','/app/v8']
        if session_id:
            _session_or_404(cid,session_id);urls.extend(['/session',f'/app/v8#session/{session_id}'])
            with connect(settings) as conn:
                sl=conn.execute('SELECT page_slug FROM session_lore WHERE session_id=? ORDER BY sort_order',(int(session_id),)).fetchall()
            urls.extend(f"/lore/{r['page_slug']}" for r in sl)
        for m in list_maps(settings,public=True): urls.append(f"/atlas/{m['slug']}")
        for h in list_handouts(settings,admin=False,campaign_id=cid): urls.append(f"/handout/{h['slug']}")
        return {'urls':list(dict.fromkeys(urls)),'count':len(set(urls))}

    @app.post('/api/v9/extensions/{plugin_id}/foundry/{action_id}')
    def v9_extension_foundry_action(request:Request,plugin_id:str,action_id:str,payload:dict=Body(default={})):
        require_gm(request);cid=active_campaign_id(request)
        try: action=extension_foundry_action(settings,plugin_id,action_id)
        except ValueError as exc: raise HTTPException(400,str(exc))
        base=action.get('payload') if isinstance(action.get('payload'),dict) else {}
        command_payload={**base,**(payload if isinstance(payload,dict) else {})}
        eid=int(command_payload.get('entity_id') or 0)
        if eid:
            entity=get_entity(settings,cid,eid)
            if not entity: raise HTTPException(404,'Object not found.')
            command_payload.setdefault('title',entity.get('name'));command_payload.setdefault('summary',entity.get('summary') or '')
            command_payload.setdefault('data',entity.get('data') or {})
        command=queue_foundry_command(settings,cid,action['command_type'],command_payload,scope=str(action.get('scope') or 'world'),requested_by=requester_label(request))
        return {'ok':True,'action':action,'command':command}

    @app.get('/api/v9/extensions')
    def v9_extensions(request:Request):
        require_gm(request);return {'extensions':discover_extensions(settings)}
