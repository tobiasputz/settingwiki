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
    save_foundry_prepared_content, queue_foundry_command, recent_foundry_commands,
)
from .aon import AoNImportError, fetch_aon_creatures, normalize_aon_url
from .v7 import (
    ALL_PERMISSIONS, asset_catalog, dependency_warnings, effective_permissions, get_encounter, get_entity,
    get_loot_item, get_loot_pool, ingest_foundry_command_results, integration_registry, list_encounters,
    list_entities, list_loot_pools, list_token_recipes, mark_sync_resolved, memory_search, recent_audit,
    record_recall, register_asset_ref, review_session_change, save_dependency, save_encounter,
    save_encounter_creature, delete_encounter_creature, save_entity, delete_entity, save_invite_permissions,
    save_knowledge_fact, save_loot_item, save_loot_pool, save_relation, save_relationship_state,
    save_role_permissions, save_token_recipe, session_changes, set_sync_link, sync_existing_entities,
    sync_link, v7_dashboard, visible_entity_facts, reveal_fact, reveal_fact_to_party, share_revealed_fact,
    list_player_observations, save_player_observation, set_player_observation_visibility,
    delete_player_observation, review_player_observation, claim_loot, create_session_change,
    invite_permission_overrides, delete_token_recipe, player_entity_view, entity_allows_public_statblock,
    entity_versions, restore_entity_version, upsert_source_entity, list_creature_folders, get_creature_folder,
    sync_links_for_entities,
    save_creature_folder, add_creature_to_folder, remove_creature_from_folder, delete_creature_folder,
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
        sync_map=sync_links_for_entities(settings,dashboard['entities'])
        for entity in dashboard['entities']:
            entity['sync']=sync_map.get(int(entity['id']))
        return {
            'campaign':get_campaign(settings,cid) or {}, 'session':session, 'sessions':sessions,
            'scenes':scenes,
            'dashboard':dashboard, 'entities':dashboard['entities'], 'encounters':dashboard['encounters'],
            'loot':dashboard['loot'], 'changes':dashboard['changes'], 'warnings':dashboard['warnings'],
            'members':members, 'characters':chars, 'maps':list_maps(settings,public=False),
            'fronts':list_fronts(settings,admin=True,campaign_id=cid), 'objectives':list_objectives(settings,cid),
            'foundry':foundry_state(settings,cid), 'foundry_actors':foundry_actors(settings,cid),
            'foundry_commands':recent_foundry_commands(settings,cid,30), 'token_recipes':list_token_recipes(settings,cid),
            'creature_folders':list_creature_folders(settings,cid),
            'integrations':integration_registry(), 'permissions':{role:effective_permissions(settings,role) for role in ('owner','co-gm','player','spectator')},
            'all_permissions':ALL_PERMISSIONS, 'current_is_owner':bool(helpers.get('is_admin',lambda _r:False)(request)),
        }

    def _prepared_entity(row:dict) -> dict:
        p=row.get('payload') if isinstance(row.get('payload'),dict) else {}
        kind=str(row.get('kind') or 'monster').lower()
        vis='players' if bool(p.get('codex_publish') or p.get('publish_codex')) else 'gm'
        return upsert_source_entity(settings,int(row['campaign_id']),'foundry_prepared',str(row['id']),{
            'kind':kind,'name':row.get('title') or 'Imported creature','subtitle':row.get('subtitle') or '',
            'summary':row.get('summary') or '','body':p.get('description') or '', 'visibility':vis,
            'image_ref':p.get('img') or '', 'token_ref':p.get('token_img') or '',
            'tags':[x.strip() for x in str(row.get('tags') or '').split(',') if x.strip()],
            'data':{**p,'prepared_content_id':int(row['id']),'legacy_source':'foundry_prepared'},
        })

    def _bundle_entry(entity:dict, prepared_lookup:dict[int,dict]|None=None) -> dict:
        payload=_entity_foundry_payload(entity,prepared_lookup)
        link=sync_link(settings,int(entity['id']))
        if link and link.get('foundry_uuid'):payload['foundry_uuid']=link['foundry_uuid']
        return payload

    def _queue_creature_bundle(request:Request, *, title:str, bundle_kind:str, bundle_id:int, entities:list[dict]) -> dict:
        cid=active_campaign_id(request);entries=[];seen=set();prepared_lookup={int(r['id']):r for r in list_foundry_prepared_content(settings,cid)}
        for entity in entities:
            if not entity or str(entity.get('kind') or '').lower() not in {'monster','npc','creature'}:continue
            eid=int(entity['id'])
            if eid in seen:continue
            seen.add(eid);entries.append(_bundle_entry(entity,prepared_lookup))
        if not entries:raise ValueError('There are no importable creatures in this collection.')
        command=queue_foundry_command(settings,cid,'push_content_bundle',{
            'folder_name':str(title or 'Seeker creatures')[:180], 'bundle_kind':str(bundle_kind)[:40],
            'bundle_id':int(bundle_id), 'entries':entries,
        },scope='world',requested_by=requester_label(request))
        return {'ok':True,'command':command,'count':len(entries),'folder_name':str(title or 'Seeker creatures')[:180]}

    def _entity_foundry_payload(entity:dict, prepared_lookup:dict[int,dict]|None=None) -> dict:
        data=dict(entity.get('data') or {})
        prepared_id=data.get('prepared_content_id')
        if prepared_id:
            if prepared_lookup is not None: row=prepared_lookup.get(int(prepared_id))
            else: row=next((x for x in list_foundry_prepared_content(settings,int(entity['campaign_id'])) if int(x.get('id') or 0)==int(prepared_id)),None)
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
        prepared_kind='monster' if kind in {'creature','monster'} else 'npc' if kind=='npc' else 'feat' if kind=='feat' else 'action' if kind=='action' else 'item' if kind in {'item','weapon','armor','consumable','equipment'} else 'homebrew'
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

    @app.get('/gm/living-table',response_class=HTMLResponse)
    @app.get('/gm/v7',response_class=HTMLResponse,include_in_schema=False)
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
        rows=list_entities(settings,cid,include_hidden=gm,kind=kind,query=q,tracked_only=True)
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
            entity['observations']=list_player_observations(settings,cid,entity_id,invite_id(request),gm=True)
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
        mode=str(payload.get('disclosure_mode') or payload.get('mode') or 'exact').lower()
        try:
            if payload.get('party') is True or str(payload.get('invite_id') or '').lower()=='party':
                return {'ok':True,'reveals':reveal_fact_to_party(settings,cid,fact_id,mode,payload.get('session_id'))}
            if not payload.get('invite_id'):raise HTTPException(400,'Choose a player or the whole party.')
            return reveal_fact(settings,fact_id,int(payload['invite_id']),payload.get('session_id'),campaign_id=cid,disclosure_mode=mode)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/facts/{fact_id}/share-party')
    def v7_fact_share_party(request:Request,fact_id:int,payload:dict=Body(default={})):
        if not player_allowed(request):raise HTTPException(401)
        if not has_permission(request,'share_player_knowledge'):raise HTTPException(403,'Your role cannot share knowledge with the party.')
        iid=invite_id(request)
        if not iid:raise HTTPException(403,'A player invitation is required to share knowledge.')
        try:return share_revealed_fact(settings,active_campaign_id(request),fact_id,int(iid),payload.get('session_id'))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/entities/{entity_id}/recall')
    def v7_recall(request:Request,entity_id:int,payload:dict=Body(...)):
        require_permission(request,'reveal_lore')
        try:return record_recall(settings,active_campaign_id(request),entity_id,payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v7/entities/{entity_id}/observations')
    def v7_observations(request:Request,entity_id:int):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);gm=bool(has_permission(request,'reveal_lore'));entity=get_entity(settings,cid,entity_id)
        if not entity or (entity.get('visibility')=='gm' and not gm):raise HTTPException(404,'Entity not found.')
        return list_player_observations(settings,cid,entity_id,invite_id(request),gm=gm)

    @app.post('/api/v7/entities/{entity_id}/observations')
    def v7_observation_save(request:Request,entity_id:int,payload:dict=Body(...)):
        if not player_allowed(request):raise HTTPException(401)
        if not has_permission(request,'create_player_notes'):raise HTTPException(403,'Your role cannot add field deductions.')
        iid=invite_id(request)
        if not iid:raise HTTPException(403,'A player invitation is required to add field deductions.')
        try:return save_player_observation(settings,active_campaign_id(request),entity_id,int(iid),payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/observations/{observation_id}/visibility')
    def v7_observation_visibility(request:Request,observation_id:int,payload:dict=Body(...)):
        if not player_allowed(request):raise HTTPException(401)
        if not has_permission(request,'share_player_knowledge'):raise HTTPException(403,'Your role cannot share field deductions.')
        iid=invite_id(request)
        if not iid:raise HTTPException(403,'A player invitation is required.')
        try:return set_player_observation_visibility(settings,active_campaign_id(request),observation_id,int(iid),str(payload.get('visibility') or 'party'))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.delete('/api/v7/observations/{observation_id}')
    def v7_observation_delete(request:Request,observation_id:int):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);gm=bool(has_permission(request,'reveal_lore'));iid=invite_id(request)
        try:delete_player_observation(settings,cid,observation_id,iid,gm=gm);return {'ok':True}
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/observations/{observation_id}/review')
    def v7_observation_review(request:Request,observation_id:int,payload:dict=Body(...)):
        require_permission(request,'reveal_lore')
        try:return review_player_observation(settings,active_campaign_id(request),observation_id,str(payload.get('status') or 'inferred'))
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
        entities=[]
        for row in enc.get('creatures') or []:
            entity=get_entity(settings,cid,int(row['entity_id'])) if row.get('entity_id') else None
            if not entity and row.get('prepared_content_id'):
                entity=next((e for e in list_entities(settings,cid) if e.get('source_type')=='foundry_prepared' and str(e.get('source_key'))==str(row['prepared_content_id'])),None)
            if entity:entities.append(entity)
        try:out=_queue_creature_bundle(request,title=f"Encounter · {enc.get('title') or 'Untitled'}",bundle_kind='encounter',bundle_id=encounter_id,entities=entities)
        except ValueError as exc:raise HTTPException(400,str(exc))
        save_encounter(settings,cid,{**enc,'status':'queued'},actor_label=requester_label(request))
        return out

    @app.post('/api/v7/creature-folders')
    def v7_creature_folder_save(request:Request,payload:dict=Body(...)):
        require_permission(request,'edit_monsters')
        try:return save_creature_folder(settings,active_campaign_id(request),payload,actor_label=requester_label(request))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.delete('/api/v7/creature-folders/{folder_id}')
    def v7_creature_folder_delete(request:Request,folder_id:int):
        require_permission(request,'edit_monsters')
        try:delete_creature_folder(settings,active_campaign_id(request),folder_id,actor_label=requester_label(request));return {'ok':True}
        except ValueError as exc:raise HTTPException(404,str(exc))

    @app.post('/api/v7/creature-folders/{folder_id}/members')
    def v7_creature_folder_member_add(request:Request,folder_id:int,payload:dict=Body(...)):
        require_permission(request,'edit_monsters')
        try:return add_creature_to_folder(settings,active_campaign_id(request),folder_id,int(payload.get('entity_id') or 0))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.delete('/api/v7/creature-folders/{folder_id}/members/{entity_id}')
    def v7_creature_folder_member_delete(request:Request,folder_id:int,entity_id:int):
        require_permission(request,'edit_monsters')
        try:remove_creature_from_folder(settings,active_campaign_id(request),folder_id,entity_id);return {'ok':True}
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/creature-folders/{folder_id}/push-foundry')
    def v7_creature_folder_push(request:Request,folder_id:int):
        require_permission(request,'edit_monsters');cid=active_campaign_id(request);folder=get_creature_folder(settings,cid,folder_id)
        if not folder:raise HTTPException(404,'Creature folder not found.')
        try:return _queue_creature_bundle(request,title=f"Seeker · {folder['name']}",bundle_kind='creature_folder',bundle_id=folder_id,entities=folder.get('members') or [])
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v7/aon/import')
    async def v7_aon_import(request:Request,payload:dict=Body(...)):
        require_permission(request,'edit_monsters');cid=active_campaign_id(request)
        raw_urls=payload.get('urls') or []
        if isinstance(raw_urls,str):raw_urls=[x.strip() for x in raw_urls.replace(',', '\n').splitlines() if x.strip()]
        if not isinstance(raw_urls,list) or not raw_urls:raise HTTPException(400,'Paste at least one Archives of Nethys creature URL.')
        try:
            canonical=[];seen=set()
            for raw in raw_urls:
                u=normalize_aon_url(str(raw))
                if u not in seen:seen.add(u);canonical.append(u)
            fetched=await fetch_aon_creatures(canonical)
        except AoNImportError as exc:raise HTTPException(400,str(exc))
        refresh=bool(payload.get('refresh_existing'));publish=bool(payload.get('publish_codex'))
        codex_visibility=str(payload.get('codex_visibility') or 'field_notes')
        if codex_visibility not in {'field_notes','full'}:codex_visibility='field_notes'
        folder=None
        folder_id=int(payload.get('folder_id') or 0)
        folder_name=str(payload.get('folder_name') or '').strip()
        if folder_id:
            folder=get_creature_folder(settings,cid,folder_id)
            if not folder:raise HTTPException(400,'Creature folder not found.')
        elif folder_name:
            try:folder=save_creature_folder(settings,cid,{'name':folder_name,'source':'aon'},actor_label=requester_label(request))
            except ValueError as exc:raise HTTPException(400,str(exc))
        encounter_id=int(payload.get('encounter_id') or 0)
        encounter=get_encounter(settings,cid,encounter_id) if encounter_id else None
        if encounter_id and not encounter:raise HTTPException(400,'Encounter not found.')
        prepared=list_foundry_prepared_content(settings,cid);results=[];errors=[]
        for result in fetched:
            if result.error or not result.parsed:
                errors.append({'url':result.url,'error':result.error or 'Could not parse creature.'});continue
            parsed_doc=dict(result.parsed);parsed=dict(parsed_doc.get('payload') or {});url=str(parsed.get('aon_url') or result.url)
            existing=next((r for r in prepared if str((r.get('payload') or {}).get('aon_url') or '')==url),None)
            mode='imported'
            if existing and not refresh:
                row=existing;mode='reused'
                # Reusing an AoN creature must not silently overwrite hand-edited mechanics.
                # Publishing is metadata-only, though, so honor an explicit Codex request.
                if publish:
                    oldp=dict(row.get('payload') or {})
                    if not bool(oldp.get('codex_publish') or oldp.get('publish_codex')) or str(oldp.get('codex_visibility') or '') != codex_visibility:
                        content={**oldp,'codex_publish':True,'publish_codex':True,'codex_visibility':codex_visibility}
                        content.setdefault('codex_category','Archives of Nethys')
                        content.setdefault('codex_blurb',row.get('summary') or parsed.get('description') or '')
                        row=save_foundry_prepared_content(settings,cid,{'id':int(row['id']),'kind':row.get('kind') or 'monster','title':row.get('title') or parsed_doc.get('title') or 'Imported creature','subtitle':row.get('subtitle') or parsed_doc.get('subtitle') or '', 'target_type':row.get('target_type') or 'world','summary':row.get('summary') or parsed_doc.get('summary') or '', 'tags':row.get('tags') or parsed_doc.get('tags') or '', 'payload':content})
                        prepared=[r for r in prepared if int(r.get('id') or 0)!=int(row['id'])]+[row]
            else:
                oldp=dict((existing or {}).get('payload') or {})
                preserved={k:oldp.get(k) for k in ('img','token_img','codex_publish','publish_codex','codex_visibility','codex_blurb','codex_category','gm_notes') if k in oldp}
                content={**oldp,**parsed,**preserved}
                if publish:
                    content['codex_publish']=True;content['publish_codex']=True;content['codex_visibility']=codex_visibility
                elif not existing:
                    content['codex_visibility']=codex_visibility
                content.setdefault('codex_category','Archives of Nethys')
                content.setdefault('codex_blurb',parsed.get('description') or parsed.get('summary') or '')
                save_payload={'id':int(existing['id']) if existing else 0,'kind':'monster','title':parsed_doc.get('title') or 'Imported creature','subtitle':parsed_doc.get('subtitle') or f"Archives of Nethys · Level {parsed.get('level',0)}",'target_type':'world','summary':parsed_doc.get('summary') or parsed.get('description') or '', 'tags':parsed_doc.get('tags') or str(parsed.get('traits') or ''),'payload':content}
                try:row=save_foundry_prepared_content(settings,cid,save_payload)
                except ValueError as exc:errors.append({'url':url,'error':str(exc)});continue
                prepared=[r for r in prepared if int(r.get('id') or 0)!=int(row['id'])]+[row];mode='updated' if existing else 'imported'
            entity=_prepared_entity(row)
            if folder:add_creature_to_folder(settings,cid,int(folder['id']),int(entity['id']))
            if encounter and not any(int(x.get('entity_id') or 0)==int(entity['id']) for x in (encounter.get('creatures') or [])):
                save_encounter_creature(settings,cid,encounter_id,{'entity_id':entity['id'],'prepared_content_id':row['id'],'name':row['title'],'level':int((row.get('payload') or {}).get('level') or 0),'quantity':1,'disposition':'enemy'})
            results.append({'url':url,'mode':mode,'prepared_id':row['id'],'entity_id':entity['id'],'name':row['title']})
        return {'ok':not errors,'results':results,'errors':errors,'count':len(results),'folder':folder}

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
                    p=_entity_foundry_payload(entity);p['quantity']=q;p['entity_id']=int(entity['id']);p['actor_uuid']=str(link.get('actor_uuid') or '')
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
        tracked=len(list_entities(settings,cid,tracked_only=True))
        backups=settings.data_dir/'migration-backups'
        return {'ok':True,'version':'8.0.1','campaign_id':cid,'entities':tracked,'objects':tracked,'foundry_queue':queue,'asset_bytes':assets['total_bytes'],'asset_files':assets['count'],'dependency_warnings':len(dependency_warnings(settings,cid)),'migration_backups':len(list(backups.glob('pre-v7-*.sqlite'))) if backups.exists() else 0}

    @app.get('/entity/{entity_id}',response_class=HTMLResponse)
    def v7_entity_page(request:Request,entity_id:int):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);gm=bool(has_permission(request,'edit_entities'));entity=get_entity(settings,cid,entity_id)
        if not entity or (entity.get('visibility')=='gm' and not gm):raise HTTPException(404,'Entity not found.')
        can_stats=bool(has_permission(request,'view_statblocks') or entity_allows_public_statblock(entity))
        iid=invite_id(request);facts=visible_entity_facts(settings,entity_id,iid,gm=gm)
        observations=list_player_observations(settings,cid,entity_id,iid,gm=gm)
        view=entity if gm else player_entity_view(settings,entity,iid,can_view_statblock=can_stats)
        role='owner' if helpers.get('is_admin',lambda _r:False)(request) else player_role(request)
        perms=effective_permissions(settings,role,iid,cid)
        return templates.TemplateResponse('v7_entity.html',{'request':request,'wiki':visible_wiki(request),'maps':list_maps(settings,public=not gm),'entity':view,'facts':facts,'observations':observations,'gm_view':gm,'can_view_statblock':can_stats,'v7_permissions':perms,'viewer_invite_id':iid})

    @app.get('/app',response_class=HTMLResponse)
    def v7_player_app(request:Request,character_id:int|None=None):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);iid=invite_id(request);gm=bool(has_permission(request,'manage_sessions'))
        chars=list_player_characters(settings,invite_id=iid,admin=gm,campaign_id=cid)
        selected=next((c for c in chars if character_id and int(c['id'])==int(character_id)),chars[0] if chars else None)
        foundry=foundry_link_for_character(settings,int(selected['id'])) if selected else None
        loot=list_loot_pools(settings,cid,None,public=not gm)
        entities=list_entities(settings,cid,include_hidden=gm,tracked_only=True)
        role='owner' if helpers.get('is_admin',lambda _r:False)(request) else player_role(request)
        perms=effective_permissions(settings,role,iid,cid)
        if not gm:
            entities=[player_entity_view(settings,e,iid,can_view_statblock=bool(perms.get('view_statblocks'))) for e in entities]
        session=_campaign_session(request,cid)
        return templates.TemplateResponse('v7_player.html',{'request':request,'wiki':visible_wiki(request),'maps':list_maps(settings,public=True),'characters':chars,'character':selected,'foundry_actor':foundry,'loot_pools':loot,'entities':entities,'live_session':session,'v7_permissions':perms,'gm_view':gm})
