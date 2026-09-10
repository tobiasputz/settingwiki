from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .config import Settings
from .storage import connect
from .campaigns import campaign_members, get_campaign
from .features import get_live_session, list_sessions, list_player_characters, save_session
from .living import list_fronts, advance_front
from .maps import list_maps
from .v5 import list_objectives
from .v51 import list_scenes, save_closeout
from .v6 import (
    foundry_state, foundry_actors, foundry_link_for_character, list_foundry_prepared_content,
    queue_foundry_command, recent_foundry_commands,
)
from .v7 import (
    ALL_PERMISSIONS, asset_catalog, dependency_warnings, effective_permissions, get_encounter, get_entity,
    get_loot_item, get_loot_pool, ingest_foundry_command_results, integration_registry, list_encounters,
    list_entities, list_loot_pools, list_token_recipes, mark_sync_resolved, memory_search, recent_audit,
    record_recall, register_asset_ref, review_session_change, save_dependency, save_encounter,
    save_encounter_creature, delete_encounter_creature, save_entity, delete_entity, save_invite_permissions,
    save_knowledge_fact, save_loot_item, save_loot_pool, save_relation, save_relationship_state,
    save_role_permissions, save_token_recipe, session_changes, set_sync_link, sync_existing_entities,
    sync_link, v7_dashboard, visible_entity_facts, reveal_fact, claim_loot, create_session_change,
    invite_permission_overrides, delete_token_recipe, player_entity_view, entity_allows_public_statblock,
    entity_versions, restore_entity_version,
)


def register_v7_routes(app, settings: Settings, templates, helpers: dict[str, Callable[..., Any]]) -> None:
    """Install V7 routes without making app.main responsible for another feature family."""

    # Keep route registration testable and compatible with deployments that
    # replace their Settings object during a controlled reload. Production
    # normally resolves to the original object; tests can supply a provider.
    initial_settings=settings
    settings_provider=helpers.get('settings_provider')
    if settings_provider:
        class _SettingsProxy:
            def __getattr__(self,name):
                return getattr(settings_provider() or initial_settings,name)
        settings=_SettingsProxy()

    active_campaign_id=helpers['active_campaign_id']
    visible_wiki=helpers['visible_wiki']
    require_gm=helpers['require_gm']
    require_admin=helpers['require_admin']
    player_allowed=helpers['player_allowed']
    invite_id=helpers['invite_id']
    requester_label=helpers['requester_label']
    player_role=helpers['player_role']
    has_permission=helpers['has_permission']
    require_permission=helpers['require_permission']

    def _campaign_session(request:Request, cid:int) -> dict|None:
        live=get_live_session(settings,invite_id=invite_id(request),admin=True,campaign_id=cid)
        if live:return live
        rows=list_sessions(settings,public=False,campaign_id=cid)
        return next((s for s in rows if s.get('status')=='planned'), rows[0] if rows else None)

    def _workspace_state(request:Request) -> dict:
        require_gm(request)
        cid=active_campaign_id(request);wiki=visible_wiki(request)
        sync_existing_entities(settings,cid,wiki)
        session=_campaign_session(request,cid)
        members=[m for m in campaign_members(settings,cid) if m.get('campaign_member')]
        for m in members:
            role=str(m.get('role') or 'player').lower()
            m['v7_role']=role
            m['v7_permissions']=effective_permissions(settings,role,int(m['id']),cid)
            m['v7_overrides']=invite_permission_overrides(settings,cid,int(m['id']))
        chars=list_player_characters(settings,admin=True,campaign_id=cid)
        sessions=list_sessions(settings,public=False,campaign_id=cid)
        dashboard=v7_dashboard(settings,cid,wiki,session)
        scenes=list_scenes(settings,cid,int(session['id'])) if session else []
        for entity in dashboard['entities']:
            entity['sync']=sync_link(settings,int(entity['id']))
        return {
            'campaign':get_campaign(settings,cid) or {}, 'session':session, 'sessions':sessions,
            'scenes':scenes,
            'dashboard':dashboard, 'entities':dashboard['entities'], 'encounters':dashboard['encounters'],
            'loot':dashboard['loot'], 'changes':dashboard['changes'], 'warnings':dashboard['warnings'],
            'members':members, 'characters':chars, 'maps':list_maps(settings,public=False),
            'fronts':list_fronts(settings,admin=True,campaign_id=cid), 'objectives':list_objectives(settings,cid),
            'foundry':foundry_state(settings,cid), 'foundry_actors':foundry_actors(settings,cid),
            'foundry_commands':recent_foundry_commands(settings,cid,30), 'token_recipes':list_token_recipes(settings,cid),
            'integrations':integration_registry(), 'permissions':{role:effective_permissions(settings,role) for role in ('owner','co-gm','player','spectator')},
            'all_permissions':ALL_PERMISSIONS, 'current_is_owner':bool(helpers.get('is_admin',lambda _r:False)(request)),
        }

    def _entity_foundry_payload(entity:dict) -> dict:
        data=dict(entity.get('data') or {})
        prepared_id=data.get('prepared_content_id')
        if prepared_id:
            row=next((x for x in list_foundry_prepared_content(settings,int(entity['campaign_id'])) if int(x.get('id') or 0)==int(prepared_id)),None)
        else: row=None
        if row:
            merged={**(row.get('payload') or {}),**data}
            return {
                'entity_id':int(entity['id']), 'prepared_id':int(row['id']), 'prepared_content_id':int(row['id']),
                'prepared_kind':row.get('kind') or entity.get('kind') or 'item', 'title':row.get('title') or entity.get('name'),
                'subtitle':row.get('subtitle') or entity.get('subtitle') or '', 'summary':row.get('summary') or entity.get('summary') or '',
                'tags':row.get('tags') or ', '.join(entity.get('tags') or []), 'data':merged,
            }
        kind=str(entity.get('kind') or 'item').lower()
        prepared_kind='monster' if kind in {'creature','monster'} else 'npc' if kind=='npc' else 'feat' if kind=='feat' else 'item' if kind in {'item','weapon','armor','consumable','equipment'} else 'homebrew'
        return {
            'entity_id':int(entity['id']), 'prepared_kind':prepared_kind, 'title':entity.get('name') or 'Seeker entity',
            'subtitle':entity.get('subtitle') or '', 'summary':entity.get('summary') or '',
            'tags':', '.join(entity.get('tags') or []), 'data':data,
        }

    def _queue_entity_push(request:Request, entity:dict) -> dict:
        cid=int(entity['campaign_id']);payload=_entity_foundry_payload(entity);link=sync_link(settings,int(entity['id']))
        if entity.get('image_ref'): register_asset_ref(settings,cid,str(entity['image_ref']),int(entity['id']),'portrait',entity.get('name') or '')
        if entity.get('token_ref'): register_asset_ref(settings,cid,str(entity['token_ref']),int(entity['id']),'token',entity.get('name') or '')
        if link and link.get('foundry_uuid'):
            payload['foundry_uuid']=link['foundry_uuid']
            return queue_foundry_command(settings,cid,'sync_entity_document',payload,scope='world',requested_by=requester_label(request))
        return queue_foundry_command(settings,cid,'push_prepared_content',payload,scope='world',requested_by=requester_label(request))

    def _apply_change(request:Request, cid:int, change:dict) -> dict:
        payload=change.get('payload') or {}
        kind=str(change.get('kind') or '').lower()
        if kind=='entity_status' and change.get('entity_id'):
            entity=get_entity(settings,cid,int(change['entity_id']))
            if entity:
                save_entity(settings,cid,{**entity,'status':payload.get('status') or entity.get('status'),'data':{**(entity.get('data') or {}),**(payload.get('data') or {})}},actor_label=requester_label(request))
        elif kind=='relationship':
            save_relationship_state(settings,cid,{**payload,'session_id':change.get('session_id')})
        elif kind=='knowledge' and payload.get('fact_id') and payload.get('invite_id'):
            reveal_fact(settings,int(payload['fact_id']),int(payload['invite_id']),int(change['session_id']))
        elif kind=='front' and payload.get('front_id'):
            advance_front(settings,int(payload['front_id']),int(payload.get('delta') or 1),str(payload.get('label') or change.get('summary') or 'Front advanced'),str(payload.get('body') or ''),int(change['session_id']),bool(change.get('visible_to_players')))
        return review_session_change(settings,cid,int(change['id']),'applied',actor_label=requester_label(request))

    @app.get('/gm/v7',response_class=HTMLResponse)
    def v7_hub(request:Request):
        state=_workspace_state(request)
        return templates.TemplateResponse('v7_hub.html',{'request':request,'wiki':visible_wiki(request),'maps':state['maps'],'v7':state})

    @app.get('/api/v7/workspace')
    def v7_workspace(request:Request):
        return _workspace_state(request)

    @app.get('/api/v7/entities')
    def v7_entities(request:Request,kind:str='',q:str=''):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);gm=bool(has_permission(request,'edit_entities'))
        if gm:sync_existing_entities(settings,cid,visible_wiki(request))
        rows=list_entities(settings,cid,include_hidden=gm,kind=kind,query=q)
        if gm:return rows
        return [player_entity_view(settings,e,invite_id(request),can_view_statblock=bool(has_permission(request,'view_statblocks'))) for e in rows]

    @app.get('/api/v7/entities/{entity_id}')
    def v7_entity_get(request:Request,entity_id:int):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);entity=get_entity(settings,cid,entity_id)
        if not entity or (entity.get('visibility')=='gm' and not has_permission(request,'edit_entities')):raise HTTPException(404,'Entity not found.')
        gm=bool(has_permission(request,'edit_entities'))
        if gm:
            entity['visible_facts']=visible_entity_facts(settings,entity_id,invite_id(request),gm=True)
            return entity
        return player_entity_view(settings,entity,invite_id(request),can_view_statblock=bool(has_permission(request,'view_statblocks')))

    @app.post('/api/v7/entities')
    def v7_entity_save(request:Request,payload:dict=Body(...)):
        require_permission(request,'edit_entities');cid=active_campaign_id(request)
        try:return save_entity(settings,cid,payload,actor_label=requester_label(request))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.delete('/api/v7/entities/{entity_id}')
    def v7_entity_delete(request:Request,entity_id:int):
        require_permission(request,'edit_entities');delete_entity(settings,active_campaign_id(request),entity_id,actor_label=requester_label(request));return {'ok':True}

    @app.get('/api/v7/entities/{entity_id}/versions')
    def v7_entity_versions(request:Request,entity_id:int):
        require_permission(request,'edit_entities');cid=active_campaign_id(request)
        if not get_entity(settings,cid,entity_id):raise HTTPException(404,'Entity not found.')
        return entity_versions(settings,entity_id,40)

    @app.post('/api/v7/entities/{entity_id}/versions/{version_id}/restore')
    def v7_entity_version_restore(request:Request,entity_id:int,version_id:int):
        require_permission(request,'edit_entities');cid=active_campaign_id(request)
        try:return restore_entity_version(settings,cid,entity_id,version_id,actor_label=requester_label(request))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/entities/{entity_id}/relations')
    def v7_relation_save(request:Request,entity_id:int,payload:dict=Body(...)):
        require_permission(request,'edit_entities');cid=active_campaign_id(request)
        try:return save_relation(settings,cid,{**payload,'source_entity_id':entity_id},actor_label=requester_label(request))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/entities/{entity_id}/relationship-state')
    def v7_relationship_state_save(request:Request,entity_id:int,payload:dict=Body(...)):
        require_permission(request,'edit_entities');cid=active_campaign_id(request)
        try:return save_relationship_state(settings,cid,{**payload,'source_entity_id':entity_id})
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v7/entities/{entity_id}/relationship/{target_id}')
    def v7_relationship_history(request:Request,entity_id:int,target_id:int):
        require_permission(request,'edit_entities')
        from .v7 import relationship_timeline
        return relationship_timeline(settings,active_campaign_id(request),entity_id,target_id)

    @app.post('/api/v7/entities/{entity_id}/facts')
    def v7_fact_save(request:Request,entity_id:int,payload:dict=Body(...)):
        require_permission(request,'reveal_lore');cid=active_campaign_id(request)
        try:return save_knowledge_fact(settings,entity_id,payload,campaign_id=cid)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/facts/{fact_id}/reveal')
    def v7_fact_reveal(request:Request,fact_id:int,payload:dict=Body(...)):
        require_permission(request,'reveal_lore');cid=active_campaign_id(request)
        if not payload.get('invite_id'):raise HTTPException(400,'Choose a player.')
        try:return reveal_fact(settings,fact_id,int(payload['invite_id']),payload.get('session_id'),campaign_id=cid)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/entities/{entity_id}/recall')
    def v7_recall(request:Request,entity_id:int,payload:dict=Body(...)):
        require_permission(request,'reveal_lore')
        try:return record_recall(settings,active_campaign_id(request),entity_id,payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/entities/{entity_id}/foundry')
    def v7_entity_foundry(request:Request,entity_id:int,payload:dict=Body(default={})):
        require_permission(request,'edit_entities');cid=active_campaign_id(request);entity=get_entity(settings,cid,entity_id)
        if not entity:raise HTTPException(404,'Entity not found.')
        mode=str(payload.get('mode') or 'push').lower()
        try:
            if mode=='accept_foundry':return {'ok':True,'sync':mark_sync_resolved(settings,cid,entity_id,'accept_foundry')}
            return {'ok':True,'command':_queue_entity_push(request,entity)}
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/encounters')
    def v7_encounter_save(request:Request,payload:dict=Body(...)):
        require_permission(request,'manage_encounters')
        try:return save_encounter(settings,active_campaign_id(request),payload,actor_label=requester_label(request))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v7/encounters/{encounter_id}')
    def v7_encounter_get(request:Request,encounter_id:int):
        require_permission(request,'manage_encounters')
        row=get_encounter(settings,active_campaign_id(request),encounter_id)
        if not row:raise HTTPException(404,'Encounter not found.')
        return row

    @app.post('/api/v7/encounters/{encounter_id}/creatures')
    def v7_encounter_creature_save(request:Request,encounter_id:int,payload:dict=Body(...)):
        require_permission(request,'manage_encounters')
        try:return save_encounter_creature(settings,active_campaign_id(request),encounter_id,payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.delete('/api/v7/encounters/{encounter_id}/creatures/{row_id}')
    def v7_encounter_creature_delete(request:Request,encounter_id:int,row_id:int):
        require_permission(request,'manage_encounters');delete_encounter_creature(settings,active_campaign_id(request),encounter_id,row_id);return {'ok':True}

    @app.post('/api/v7/encounters/{encounter_id}/prepare-foundry')
    def v7_encounter_prepare_foundry(request:Request,encounter_id:int):
        require_permission(request,'manage_encounters');cid=active_campaign_id(request);enc=get_encounter(settings,cid,encounter_id)
        if not enc:raise HTTPException(404,'Encounter not found.')
        commands=[];seen=set()
        for row in enc.get('creatures') or []:
            entity=None
            if row.get('entity_id'):entity=get_entity(settings,cid,int(row['entity_id']))
            if not entity and row.get('prepared_content_id'):
                entity=next((e for e in list_entities(settings,cid) if e.get('source_type')=='foundry_prepared' and str(e.get('source_key'))==str(row['prepared_content_id'])),None)
            if not entity:continue
            if int(entity['id']) in seen:continue
            seen.add(int(entity['id']));commands.append(_queue_entity_push(request,entity))
        save_encounter(settings,cid,{**enc,'status':'queued'},actor_label=requester_label(request))
        return {'ok':True,'commands':commands,'count':len(commands)}

    @app.post('/api/v7/loot')
    def v7_loot_pool_save(request:Request,payload:dict=Body(...)):
        require_permission(request,'manage_loot')
        try:return save_loot_pool(settings,active_campaign_id(request),payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/loot/{pool_id}/items')
    def v7_loot_item_save(request:Request,pool_id:int,payload:dict=Body(...)):
        require_permission(request,'manage_loot')
        try:return save_loot_item(settings,active_campaign_id(request),pool_id,payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/loot/items/{item_id}/claim')
    def v7_loot_claim(request:Request,item_id:int,payload:dict=Body(...)):
        if not player_allowed(request):raise HTTPException(401)
        if not has_permission(request,'manage_own_inventory') and not has_permission(request,'manage_loot'):raise HTTPException(403,'Inventory permission required.')
        cid=active_campaign_id(request);item=get_loot_item(settings,item_id)
        if not item:raise HTTPException(404,'Loot item not found.')
        pool=get_loot_pool(settings,cid,int(item['pool_id']))
        if not pool:raise HTTPException(404,'Loot item not found in this campaign.')
        if not has_permission(request,'manage_loot') and (str(pool.get('visibility') or 'players')=='gm' or str(item.get('visibility') or 'players')=='gm'):
            raise HTTPException(404,'Loot item not found.')
        try:q=max(1,int(payload.get('quantity') or 1))
        except Exception:raise HTTPException(400,'quantity must be an integer.')
        iid=invite_id(request);character_id=payload.get('character_id')
        if character_id:
            chars=list_player_characters(settings,invite_id=iid,admin=bool(has_permission(request,'manage_loot')),campaign_id=cid)
            char=next((c for c in chars if int(c['id'])==int(character_id)),None)
            if not char:raise HTTPException(403,'That character is not available to you.')
        else:char=None
        # Reserve the loot first. A previous implementation queued the Foundry
        # grant before this transactional quantity check, so a losing race or
        # over-claim could still put an item into Foundry. The database claim is
        # the authority; the bridge command is attached only after it succeeds.
        try:claim=claim_loot(settings,cid,item_id,iid,int(character_id) if character_id else None,q,None)
        except ValueError as exc:raise HTTPException(400,str(exc))
        cmd=None
        if char:
            link=foundry_link_for_character(settings,int(char['id']))
            if link and link.get('actor_id'):
                entity=get_entity(settings,cid,int(item['entity_id'])) if item.get('entity_id') else None
                if not entity and item.get('prepared_content_id'):
                    entity=next((e for e in list_entities(settings,cid) if e.get('source_type')=='foundry_prepared' and str(e.get('source_key'))==str(item['prepared_content_id'])),None)
                if entity:
                    p=_entity_foundry_payload(entity);p['quantity']=q;p['entity_id']=int(entity['id'])
                    cmd=queue_foundry_command(settings,cid,'grant_prepared_content',p,actor_id=str(link['actor_id']),scope='actor',requested_by=requester_label(request))
                    with connect(settings) as conn:
                        conn.execute('UPDATE v7_loot_claims SET foundry_command_id=?,updated_at=? WHERE id=?',(int(cmd['id']),time.time(),int(claim['id'])))
                    claim['foundry_command_id']=int(cmd['id'])
        # Claims are automatically part of the session review record.
        if pool and pool.get('session_id'):
            create_session_change(settings,cid,int(pool['session_id']),{'kind':'loot','entity_id':item.get('entity_id'),'summary':f"{requester_label(request)} claimed {q}× {item.get('name')}",'payload':{'claim_id':claim['id'],'character_id':character_id},'visible_to_players':True},actor_label=requester_label(request))
        return {'ok':True,'claim':claim,'command':cmd}

    @app.post('/api/v7/session/{session_id}/changes')
    def v7_session_change_add(request:Request,session_id:int,payload:dict=Body(...)):
        require_permission(request,'manage_sessions')
        try:return create_session_change(settings,active_campaign_id(request),session_id,payload,actor_label=requester_label(request))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/session-changes/{change_id}/review')
    def v7_session_change_review(request:Request,change_id:int,payload:dict=Body(...)):
        require_permission(request,'manage_sessions');cid=active_campaign_id(request);status=str(payload.get('status') or 'approved')
        try:
            if status=='applied':
                change=next((x for x in session_changes(settings,cid,int(payload.get('session_id') or 0)) if int(x['id'])==change_id),None)
                if not change:raise ValueError('Session change not found.')
                return _apply_change(request,cid,change)
            return review_session_change(settings,cid,change_id,status,actor_label=requester_label(request))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/session/{session_id}/finish')
    def v7_session_finish(request:Request,session_id:int,payload:dict=Body(default={})):
        require_permission(request,'manage_sessions');cid=active_campaign_id(request)
        rows=session_changes(settings,cid,session_id)
        applied=[]
        for change in rows:
            if change.get('status')=='approved':applied.append(_apply_change(request,cid,change))
        session=next((s for s in list_sessions(settings,public=False,campaign_id=cid) if int(s['id'])==int(session_id)),None)
        if not session:raise HTTPException(404,'Session not found.')
        session=save_session(settings,{**session,'campaign_id':cid,'status':'ended','summary':str(payload.get('summary') or session.get('summary') or '')})
        save_closeout(settings,cid,session_id,str(payload.get('summary') or ''),str(payload.get('unresolved') or ''),None)
        return {'ok':True,'session':session,'applied':len(applied),'remaining':len([x for x in rows if x.get('status')=='proposed'])}

    @app.get('/api/v7/memory')
    def v7_memory(request:Request,q:str=''):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);gm=bool(has_permission(request,'manage_sessions') or has_permission(request,'edit_entities'))
        return memory_search(settings,cid,visible_wiki(request),q,24,gm=gm,invite_id=invite_id(request),can_view_statblocks=bool(has_permission(request,'view_statblocks')))

    @app.post('/api/v7/dependencies')
    def v7_dependency_save(request:Request,payload:dict=Body(...)):
        require_permission(request,'edit_entities')
        try:return save_dependency(settings,active_campaign_id(request),payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v7/dependencies/warnings')
    def v7_dependency_warning_list(request:Request):
        require_gm(request);return dependency_warnings(settings,active_campaign_id(request))

    @app.get('/api/v7/permissions')
    def v7_permissions_get(request:Request):
        require_gm(request);cid=active_campaign_id(request)
        members=[m for m in campaign_members(settings,cid) if m.get('campaign_member')]
        for m in members:
            role=str(m.get('role') or 'player').lower()
            m['v7_role']=role
            m['v7_permissions']=effective_permissions(settings,role,int(m['id']),cid)
            m['v7_overrides']=invite_permission_overrides(settings,cid,int(m['id']))
        return {'roles':{r:effective_permissions(settings,r) for r in ('owner','co-gm','player','spectator')},'members':members,'all_permissions':ALL_PERMISSIONS}

    @app.put('/api/v7/permissions/roles/{role}')
    def v7_permissions_role(request:Request,role:str,payload:dict=Body(...)):
        require_admin(request)
        try:return save_role_permissions(settings,role,payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.put('/api/v7/permissions/invites/{member_id}')
    def v7_permissions_invite(request:Request,member_id:int,payload:dict=Body(...)):
        require_admin(request);cid=active_campaign_id(request)
        if not any(int(m['id'])==int(member_id) and m.get('campaign_member') for m in campaign_members(settings,cid)):
            raise HTTPException(404,'Campaign member not found.')
        return save_invite_permissions(settings,cid,member_id,payload)

    @app.post('/api/v7/token-recipes')
    def v7_token_recipe_save(request:Request,payload:dict=Body(...)):
        require_permission(request,'edit_monsters')
        try:return save_token_recipe(settings,active_campaign_id(request),payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v7/token-recipes')
    def v7_token_recipe_list(request:Request):
        if not player_allowed(request):raise HTTPException(401)
        return list_token_recipes(settings,active_campaign_id(request))

    @app.delete('/api/v7/token-recipes/{recipe_id}')
    def v7_token_recipe_delete(request:Request,recipe_id:int):
        require_permission(request,'edit_monsters');delete_token_recipe(settings,active_campaign_id(request),recipe_id);return {'ok':True}

    @app.get('/api/v7/assets')
    def v7_assets(request:Request):
        require_gm(request);return asset_catalog(settings,active_campaign_id(request))

    @app.get('/api/v7/audit')
    def v7_audit(request:Request,limit:int=60):
        require_gm(request);return recent_audit(settings,active_campaign_id(request),limit)

    @app.get('/api/v7/integrations')
    def v7_integrations(request:Request):
        require_gm(request);return integration_registry()

    @app.get('/api/v7/health')
    def v7_health(request:Request):
        require_gm(request);cid=active_campaign_id(request);assets=asset_catalog(settings,cid)
        with connect(settings) as conn:
            queue={r['status']:r['n'] for r in conn.execute('SELECT status,COUNT(*) AS n FROM foundry_command_queue WHERE campaign_id=? GROUP BY status',(cid,)).fetchall()}
            pages=int(conn.execute('SELECT COUNT(*) AS n FROM v7_entities WHERE campaign_id=?',(cid,)).fetchone()['n'])
        backups=settings.data_dir/'migration-backups'
        return {'ok':True,'version':'7.0.0','campaign_id':cid,'entities':pages,'foundry_queue':queue,'asset_bytes':assets['total_bytes'],'asset_files':assets['count'],'dependency_warnings':len(dependency_warnings(settings,cid)),'migration_backups':len(list(backups.glob('pre-v7-*.sqlite'))) if backups.exists() else 0}

    @app.get('/entity/{entity_id}',response_class=HTMLResponse)
    def v7_entity_page(request:Request,entity_id:int):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);gm=bool(has_permission(request,'edit_entities'));entity=get_entity(settings,cid,entity_id)
        if not entity or (entity.get('visibility')=='gm' and not gm):raise HTTPException(404,'Entity not found.')
        can_stats=bool(has_permission(request,'view_statblocks') or entity_allows_public_statblock(entity))
        facts=visible_entity_facts(settings,entity_id,invite_id(request),gm=gm)
        view=entity if gm else player_entity_view(settings,entity,invite_id(request),can_view_statblock=can_stats)
        return templates.TemplateResponse('v7_entity.html',{'request':request,'wiki':visible_wiki(request),'maps':list_maps(settings,public=not gm),'entity':view,'facts':facts,'gm_view':gm,'can_view_statblock':can_stats})

    @app.get('/app',response_class=HTMLResponse)
    def v7_player_app(request:Request,character_id:int|None=None):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);iid=invite_id(request);gm=bool(has_permission(request,'manage_sessions'))
        chars=list_player_characters(settings,invite_id=iid,admin=gm,campaign_id=cid)
        selected=next((c for c in chars if character_id and int(c['id'])==int(character_id)),chars[0] if chars else None)
        foundry=foundry_link_for_character(settings,int(selected['id'])) if selected else None
        loot=list_loot_pools(settings,cid,None,public=not gm)
        entities=list_entities(settings,cid,include_hidden=gm)
        session=_campaign_session(request,cid)
        role='owner' if helpers.get('is_admin',lambda _r:False)(request) else player_role(request)
        perms=effective_permissions(settings,role,iid,cid)
        return templates.TemplateResponse('v7_player.html',{'request':request,'wiki':visible_wiki(request),'maps':list_maps(settings,public=True),'characters':chars,'character':selected,'foundry_actor':foundry,'loot_pools':loot,'entities':entities,'live_session':session,'v7_permissions':perms,'gm_view':gm})
