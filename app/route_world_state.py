"""Campaign consequence routes. Hidden metadata is never serialized to players."""
from __future__ import annotations
from typing import Callable, Any
from fastapi import Body, HTTPException, Request
from .world_state import events_for_gm, events_for_player, write_event


def register_world_state_routes(app,settings,helpers:dict[str,Callable[...,Any]]):
    initial_settings=settings
    provider=helpers.get('settings_provider')
    if provider:
        class _SettingsProxy:
            def __getattr__(self,name):return getattr(provider() or initial_settings,name)
        settings=_SettingsProxy()
    cid_of=helpers['active_campaign_id']
    require_gm=helpers['require_gm']
    player_allowed=helpers['player_allowed']

    @app.get('/api/world/events')
    def world_events(request:Request,session_id:int|None=None,entity_id:int|None=None,map_id:int|None=None,marker_id:int|None=None,limit:int=100):
        require_gm(request)
        return {'events':events_for_gm(settings,cid_of(request),session_id=session_id,entity_id=entity_id,map_id=map_id,marker_id=marker_id,limit=limit)}

    @app.post('/api/world/events')
    def world_create(request:Request,payload:dict=Body(...)):
        require_gm(request)
        try:return write_event(settings,cid_of(request),payload)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.put('/api/world/events/{event_id}')
    def world_update(request:Request,event_id:int,payload:dict=Body(...)):
        require_gm(request)
        try:return write_event(settings,cid_of(request),payload,event_id=event_id)
        except ValueError as exc:raise HTTPException(400,str(exc))

    @app.get('/api/world/known-events')
    def world_known(request:Request):
        if not player_allowed(request): raise HTTPException(401)
        return {'events':events_for_player(settings,cid_of(request))}
