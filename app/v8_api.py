from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, HTTPException, Request
from fastapi.responses import HTMLResponse

from .config import Settings
from .storage import connect, safe_project_path, save_text_file
from .campaigns import get_campaign, campaign_members
from .features import (
    add_session_update, get_live_session, list_handouts, list_player_characters, list_sessions,
    recent_updates, save_handout, save_session,
)
from .maps import create_marker, list_maps
from .living import list_fronts, list_threads
from .v51 import list_clocks, list_scenes
from .v6 import foundry_actors, foundry_state, recent_foundry_commands, foundry_link_for_character
from .v7 import (
    list_entities, sync_existing_entities, save_relation, mark_sync_resolved, promote_wiki_page, untrack_wiki_entity,
    sync_links_for_entities, dependency_warnings, list_encounters,
)
from .latex import build_wiki
from .v8 import (
    command_catalog, diagnostics, entity_inspector, init_v8_db, link_handout, link_object,
    module_settings, record_touch, refresh_source_mappings, restore_source_revision,
    revisions, save_module_settings, save_workflow, snapshot_source, source_map, workflow,
)


def register_v8_routes(app, settings: Settings, templates, helpers: dict[str, Callable[..., Any]]) -> None:
    initial_settings=settings
    provider=helpers.get('settings_provider')
    if provider:
        class _SettingsProxy:
            def __getattr__(self,name):return getattr(provider() or initial_settings,name)
        settings=_SettingsProxy()

    active_campaign_id=helpers['active_campaign_id'];visible_wiki=helpers['visible_wiki']
    require_gm=helpers['require_gm'];require_admin=helpers['require_admin'];player_allowed=helpers['player_allowed']
    invite_id=helpers['invite_id'];requester_label=helpers['requester_label'];is_gm=helpers['is_gm']
    ensure_built=helpers.get('ensure_built')

    def _session(cid:int,request:Request)->dict|None:
        live=get_live_session(settings,invite_id=invite_id(request),admin=is_gm(request),campaign_id=cid)
        if live:return live
        rows=list_sessions(settings,public=False,campaign_id=cid)
        planned=[r for r in rows if r.get('status')=='planned']
        return planned[0] if planned else (rows[-1] if rows else None)

    def _sync_registry(cid:int,wiki:dict)->list[dict]:
        sync_existing_entities(settings,cid,wiki)
        entities=list_entities(settings,cid,tracked_only=True)
        refresh_source_mappings(settings,cid,entities)
        return entities

    def _codex_candidates(wiki:dict,entities:list[dict])->list[dict]:
        tracked={str((e.get('data') or {}).get('slug') or '') for e in entities if e.get('source_type')=='lore'}
        out=[]
        for page in wiki.get('pages',[]) or []:
            slug=str(page.get('slug') or '')
            if not slug or slug in tracked:continue
            # Whole source-backed Homebrew is already represented by one object;
            # its internal level/heritage headings should not reappear here.
            if str(page.get('homebrew_kind') or 'codex').lower()!='codex':continue
            out.append({'slug':slug,'title':page.get('title') or slug,'chapter':page.get('chapter') or '',
                        'level':page.get('level') or '', 'source_file':page.get('source_file') or ''})
        return out

    def _table_payload(cid:int,session:dict|None)->dict:
        actors=foundry_actors(settings,cid)
        # Join actor snapshots back to Seeker characters so the Campaign Workspace table surface can
        # write HP/resources through the same permission-checked endpoint as the
        # character sheet instead of inventing a second Foundry command path.
        by_actor={}
        for ch in list_player_characters(settings,admin=True,campaign_id=cid):
            try: link=foundry_link_for_character(settings,int(ch['id']))
            except Exception: link=None
            if link and link.get('actor_id'):
                by_actor[str(link['actor_id'])]={'character_id':int(ch['id']),'character_name':ch.get('name') or ''}
        for actor in actors:
            actor.update(by_actor.get(str(actor.get('actor_id')),{}))
        scenes=list_scenes(settings,cid,int(session['id'])) if session else []
        clocks=list_clocks(settings,cid,include_done=False)
        encounters=list_encounters(settings,cid,int(session['id'])) if session else []
        return {'actors':actors,'scenes':scenes,'clocks':clocks,'encounters':encounters}

    @app.get('/app/v8',response_class=HTMLResponse)
    def v8_workspace(request:Request):
        require_gm(request);cid=active_campaign_id(request);wiki=visible_wiki(request);entities=_sync_registry(cid,wiki);session=_session(cid,request)
        mods=module_settings(settings,cid)
        return templates.TemplateResponse('v8_workspace.html',{
            'request':request,'wiki':wiki,'maps':list_maps(settings,public=False),'campaign':get_campaign(settings,cid) or {},
            'v8_modules':mods,'session':session,'entity_count':len(entities),'foundry':foundry_state(settings,cid),
        })

    @app.get('/portal',response_class=HTMLResponse)
    def v8_player_portal(request:Request):
        if not player_allowed(request):
            gate=helpers.get('player_gate_redirect')
            if gate:return gate(request)
            raise HTTPException(401)
        cid=active_campaign_id(request);wiki=visible_wiki(request);iid=invite_id(request);gm=is_gm(request)
        session=get_live_session(settings,invite_id=iid,admin=gm,campaign_id=cid)
        sessions=list_sessions(settings,public=not gm,invite_id=iid,campaign_id=cid)
        chars=list_player_characters(settings,invite_id=iid,admin=gm,campaign_id=cid)
        handouts=list_handouts(settings,admin=gm,campaign_id=cid)
        updates=recent_updates(settings,iid,20,admin=gm,campaign_id=cid)
        return templates.TemplateResponse('v8_player_portal.html',{
            'request':request,'wiki':wiki,'maps':list_maps(settings,public=True),'campaign':get_campaign(settings,cid) or {},
            'session':session,'sessions':sessions,'characters':chars,'handouts':handouts,'updates':updates,
        })

    @app.get('/api/v8/state')
    def v8_state(request:Request):
        require_gm(request);cid=active_campaign_id(request);wiki=visible_wiki(request);entities=_sync_registry(cid,wiki);session=_session(cid,request)
        syncs=sync_links_for_entities(settings,entities)
        compact=[]
        for e in entities:
            compact.append({**e,'sync':syncs.get(int(e['id']))})
        wf=workflow(settings,cid,int(session['id'])) if session else None
        return {
            'version':'9.0.5','campaign':get_campaign(settings,cid) or {},'modules':module_settings(settings,cid),
            'session':session,'workflow':wf,'sessions':list_sessions(settings,public=False,campaign_id=cid),
            'entities':compact,'codex_candidates':_codex_candidates(wiki,entities),'table':_table_payload(cid,session),'maps':list_maps(settings,public=False),
            'handouts':list_handouts(settings,admin=True,campaign_id=cid),'threads':list_threads(settings,admin=True,campaign_id=cid),
            'fronts':list_fronts(settings,admin=True,campaign_id=cid),'foundry':foundry_state(settings,cid),
            'foundry_commands':recent_foundry_commands(settings,cid,25),'warnings':dependency_warnings(settings,cid),
        }

    @app.get('/api/v8/command')
    def v8_command(request:Request,q:str=''):
        if not player_allowed(request):raise HTTPException(401)
        cid=active_campaign_id(request);wiki=visible_wiki(request)
        # GM receives the full command catalog; players are limited to visible wiki via the existing global search elsewhere.
        if not is_gm(request):
            allowed=[]
            low=str(q or '').casefold().strip()
            for p in wiki.get('pages',[]) or []:
                s=f"{p.get('title','')} {p.get('chapter','')} {p.get('excerpt','')}".casefold()
                if not low or low in s:allowed.append({'type':'codex','title':p.get('title') or p.get('slug'),'subtitle':p.get('chapter') or 'Codex','href':f"/lore/{p.get('slug')}"})
            return allowed[:30]
        return command_catalog(settings,cid,wiki,q)

    @app.post('/api/v8/codex/track')
    def v8_track_codex_page(request:Request,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request);wiki=visible_wiki(request)
        try:
            entity=promote_wiki_page(settings,cid,wiki,str(payload.get('slug') or ''),kind=str(payload.get('kind') or 'lore'),actor_label=requester_label(request))
            refresh_source_mappings(settings,cid,list_entities(settings,cid,tracked_only=True))
            return {'ok':True,'entity':entity}
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v8/entity/{entity_id}/untrack')
    def v8_untrack_codex_page(request:Request,entity_id:int):
        require_gm(request);cid=active_campaign_id(request)
        try:return {'ok':True,'entity':untrack_wiki_entity(settings,cid,entity_id,actor_label=requester_label(request))}
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v8/entity/{entity_id}/inspector')
    def v8_entity_inspector(request:Request,entity_id:int):
        require_gm(request);cid=active_campaign_id(request);_sync_registry(cid,visible_wiki(request))
        try:return entity_inspector(settings,cid,entity_id)
        except ValueError as exc:raise HTTPException(404,str(exc))

    @app.post('/api/v8/entity/{entity_id}/relation')
    def v8_entity_relation(request:Request,entity_id:int,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request)
        try:return save_relation(settings,cid,{**payload,'source_entity_id':entity_id},actor_label=requester_label(request))
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.post('/api/v8/entity/{entity_id}/handout')
    def v8_entity_handout(request:Request,entity_id:int,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request);ins=entity_inspector(settings,cid,entity_id);e=ins['entity']
        kind=str(payload.get('kind') or 'dossier')
        body=str(payload.get('body') or '').strip() or str(e.get('summary') or e.get('body') or '')[:12000]
        title=str(payload.get('title') or '').strip() or ({'wanted':'Wanted: ','newspaper':'News: ','decree':'Decree: ','dossier':'Dossier: '}.get(kind,'')+str(e.get('name') or 'Handout'))
        h=save_handout(settings,{'campaign_id':cid,'title':title,'body':body,'kind':kind,'visibility':payload.get('visibility') or 'players','session_id':payload.get('session_id')})
        link_handout(settings,int(h['id']),entity_id,str(payload.get('relation') or 'about'));link_object(settings,cid,entity_id,'handout',str(h['id']),label=h.get('title') or '')
        return {'ok':True,'handout':h,'href':f"/handout/{h.get('slug')}"}

    @app.post('/api/v8/entity/{entity_id}/map')
    def v8_entity_map(request:Request,entity_id:int,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request);ins=entity_inspector(settings,cid,entity_id);e=ins['entity']
        map_id=int(payload.get('map_id') or 0)
        if not map_id:raise HTTPException(400,'Choose a map.')
        marker=create_marker(settings,map_id,{'title':payload.get('title') or e.get('name'),'body':payload.get('body') or e.get('summary') or '',
            'x':payload.get('x',.5),'y':payload.get('y',.5),'kind':payload.get('kind') or 'place','visible_to_players':payload.get('visible_to_players',True),
            'page_slug':(e.get('data') or {}).get('slug')})
        link_object(settings,cid,entity_id,'map_marker',str(marker['id']),label=marker.get('title') or '',data={'map_id':map_id})
        return {'ok':True,'marker':marker}

    @app.post('/api/v8/entity/{entity_id}/foundry/resolve')
    def v8_entity_foundry_resolve(request:Request,entity_id:int,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request);mode=str(payload.get('mode') or 'accept_seeker')
        if mode not in {'accept_seeker','accept_foundry'}:raise HTTPException(400,'Unknown resolution mode.')
        try:return mark_sync_resolved(settings,cid,entity_id,mode)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/v8/sources')
    def v8_sources(request:Request):
        require_gm(request);cid=active_campaign_id(request);entities=_sync_registry(cid,visible_wiki(request));return source_map(settings,cid,entities)

    @app.get('/api/v8/source')
    def v8_source_get(request:Request,path:str):
        require_gm(request);target=safe_project_path(settings,path)
        if not target.exists() or target.suffix.lower() not in {'.tex','.sty','.cls'}:raise HTTPException(404,'Source file not found.')
        text=target.read_text(encoding='utf-8',errors='replace')
        from .v8 import source_structure
        return {'path':path,'text':text,'structure':source_structure(text),'revisions':revisions(settings,active_campaign_id(request),'source',path,30)}

    @app.put('/api/v8/source')
    def v8_source_save(request:Request,payload:dict=Body(...)):
        require_admin(request);cid=active_campaign_id(request);path=str(payload.get('path') or '').strip();text=str(payload.get('text') or '')
        if not path:raise HTTPException(400,'Source path is required.')
        target=safe_project_path(settings,path)
        if target.suffix.lower() not in {'.tex','.sty','.cls'}:raise HTTPException(400,'Source Studio only writes LaTeX source files.')
        snapshot_source(settings,cid,path,label=str(payload.get('label') or 'Before Source Studio edit'),created_by=requester_label(request))
        result=save_text_file(settings,path,text)
        build=None
        try: build=build_wiki(settings)
        except Exception as exc: build={'warning':str(exc)}
        _sync_registry(cid,build if isinstance(build,dict) else visible_wiki(request))
        return {'ok':True,'result':result,'build_warning':(build or {}).get('warning') if isinstance(build,dict) else None}

    @app.post('/api/v8/source/revision/{revision_id}/restore')
    def v8_source_restore(request:Request,revision_id:int):
        require_admin(request);cid=active_campaign_id(request)
        try:out=restore_source_revision(settings,cid,revision_id,created_by=requester_label(request))
        except ValueError as exc:raise HTTPException(404,str(exc))
        try: build_wiki(settings)
        except Exception: pass
        return out

    @app.put('/api/v8/modules')
    def v8_modules_save(request:Request,payload:dict=Body(...)):
        require_gm(request);rows=payload.get('modules') if isinstance(payload.get('modules'),list) else []
        return {'modules':save_module_settings(settings,active_campaign_id(request),rows)}

    @app.get('/api/v8/session/{session_id}/workflow')
    def v8_workflow_get(request:Request,session_id:int):
        require_gm(request);return workflow(settings,active_campaign_id(request),session_id)

    @app.put('/api/v8/session/{session_id}/workflow')
    def v8_workflow_save(request:Request,session_id:int,payload:dict=Body(...)):
        require_gm(request);return save_workflow(settings,active_campaign_id(request),session_id,payload,actor=requester_label(request))

    @app.post('/api/v8/session/{session_id}/start')
    def v8_session_start(request:Request,session_id:int,payload:dict=Body(default={})):
        require_gm(request);cid=active_campaign_id(request)
        rows=list_sessions(settings,public=False,campaign_id=cid);s=next((x for x in rows if int(x['id'])==int(session_id)),None)
        if not s:raise HTTPException(404,'Session not found.')
        save_session(settings,{**s,'campaign_id':cid,'status':'live'});wf=save_workflow(settings,cid,session_id,{'stage':'run','run':{'started_by':requester_label(request),'note':payload.get('note') or ''}},actor=requester_label(request))
        return {'ok':True,'session':next((x for x in list_sessions(settings,public=False,campaign_id=cid) if int(x['id'])==session_id),s),'workflow':wf}

    @app.post('/api/v8/session/{session_id}/finish')
    def v8_session_finish(request:Request,session_id:int,payload:dict=Body(...)):
        require_gm(request);cid=active_campaign_id(request);rows=list_sessions(settings,public=False,campaign_id=cid);s=next((x for x in rows if int(x['id'])==int(session_id)),None)
        if not s:raise HTTPException(404,'Session not found.')
        summary=str(payload.get('summary') or s.get('summary') or '').strip();unresolved=str(payload.get('unresolved') or '').strip()
        ended=save_session(settings,{**s,'campaign_id':cid,'status':'ended','summary':summary})
        wf=save_workflow(settings,cid,session_id,{'stage':'chronicle','chronicle':{'summary':summary,'unresolved':unresolved,'publish':bool(payload.get('publish',False))}},actor=requester_label(request))
        update=None
        if payload.get('publish') and summary:
            update=add_session_update(settings,{'campaign_id':cid,'session_id':session_id,'title':f"Session {s.get('session_number') or ''} · {s.get('title') or 'Chronicle'}".strip(' ·'),'body':summary,'target_type':'session','target_key':str(session_id),'visibility':'players'})
        return {'ok':True,'session':ended,'workflow':wf,'chronicle_update':update}

    @app.post('/api/v8/session/{session_id}/touch')
    def v8_session_touch(request:Request,session_id:int,payload:dict=Body(...)):
        require_gm(request);return record_touch(settings,active_campaign_id(request),session_id,str(payload.get('target_type') or 'entity'),str(payload.get('target_key') or ''),str(payload.get('action') or 'opened'),payload.get('meta') if isinstance(payload.get('meta'),dict) else {})

    @app.get('/api/v8/diagnostics')
    def v8_diagnostics(request:Request):
        require_gm(request);cid=active_campaign_id(request);wiki=visible_wiki(request);_sync_registry(cid,wiki)
        return diagnostics(settings,cid,foundry=foundry_state(settings,cid),wiki=wiki)
