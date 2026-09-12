from __future__ import annotations

# Route declarations were extracted from the historical monolithic router.
# They intentionally retain the same handler bodies, endpoint paths and names.
from .route_bridge import bind_composition_root

bind_composition_root(globals())

@app.middleware("http")
async def archive_read_only_guard(request: Request, call_next):
    """Freeze campaign mutations while archive mode is enabled.

    Reader-local state (notification reads/bookmarks/activity) and access control
    remain usable. The owner can always disable archive mode again.
    """
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and archive_mode():
        path = request.url.path
        if path.startswith("/api/") and not any(path.startswith(prefix) for prefix in _ARCHIVE_WRITE_ALLOW):
            return JSONResponse(
                {"detail": "This campaign is archived and read-only. Disable archive mode as the owner before changing campaign content."},
                status_code=403,
            )
    return await call_next(request)

@app.middleware("http")
async def v10_request_guard_and_diagnostics(request: Request, call_next):
    request_id = secrets.token_hex(6)
    request.state.request_id = request_id
    started = time.perf_counter()
    mutating = request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    # Origin validation is a low-friction CSRF defense for browser writes. API
    # clients/Foundry do not send Origin and continue to work exactly as before.
    if mutating and not _same_origin_request(request):
        return JSONResponse({"detail": "Cross-origin write rejected."}, status_code=403, headers={"X-Request-ID": request_id})
    try:
        response = await call_next(request)
    except Exception as exc:
        duration = (time.perf_counter() - started) * 1000
        ctx = getattr(request.state, "_seeker_campaign_context", None)
        cid = int(ctx.get("active_campaign_id")) if isinstance(ctx, dict) and ctx.get("active_campaign_id") else None
        log_diagnostic(settings, campaign_id=cid, level="error", subsystem="http", event_type="request.error",
                       message=f"{type(exc).__name__}: {exc}", request_id=request_id, duration_ms=duration, path=request.url.path)
        raise
    duration = (time.perf_counter() - started) * 1000
    ctx = getattr(request.state, "_seeker_campaign_context", None)
    cid = int(ctx.get("active_campaign_id")) if isinstance(ctx, dict) and ctx.get("active_campaign_id") else None
    if duration >= float(os.getenv("SEEKER_SLOW_REQUEST_MS", "500") or 500):
        log_diagnostic(settings, campaign_id=cid, level="warning", subsystem="http", event_type="request.slow",
                       message=f"{request.method} {request.url.path}", request_id=request_id, duration_ms=duration, path=request.url.path)
    if response.status_code >= 500:
        log_diagnostic(settings, campaign_id=cid, level="error", subsystem="http", event_type="request.5xx",
                       message=f"HTTP {response.status_code}", request_id=request_id, duration_ms=duration, path=request.url.path)
    if mutating and response.status_code < 400 and request.url.path.startswith("/api/") and request.url.path != "/api/v10/diagnostics/browser":
        BUS.publish("state.changed", campaign_id=cid, path=request.url.path, payload={"method": request.method.upper()})
    response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob: https:; media-src 'self' blob: https:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
    return response

@app.on_event("startup")
def startup_build() -> None:
    try:
        tex_files=list(settings.project_dir.rglob("*.tex"))
        if tex_files:
            index_path=settings.build_dir / "wiki_index.json"
            needs_build=not index_path.exists()
            if not needs_build:
                try:
                    existing=load_wiki(settings)
                    needs_build=int(existing.get("renderer_version") or 0) < 9000
                    index_mtime=index_path.stat().st_mtime_ns
                    if not needs_build:
                        source_files=tex_files+list(settings.project_dir.rglob("*.sty"))+list(settings.project_dir.rglob("*.cls"))
                        needs_build=any(p.stat().st_mtime_ns>index_mtime for p in source_files)
                except Exception:
                    needs_build=True
            if needs_build:
                build_wiki(settings)
            # PDF compilation is intentionally opt-in on boot. TeX is the
            # heaviest process in this container and can transiently consume far
            # more memory than the web app. The Studio compile action remains
            # available, and COMPILE_ON_START=1 restores the old behavior.
            if os.getenv("COMPILE_ON_START", "0").lower() in {"1", "true", "yes"}:
                compile_pdf(settings)
    except Exception as exc:
        print(f"Seeker startup build warning: {exc}", flush=True)

@app.on_event("startup")
def startup_v6_backups() -> None:
    """Keep rolling portable backups without putting archive work on requests.

    The sleeping daemon wakes only a few times per day and creates at most one
    archive per 24h, so steady-state Railway cost is negligible.
    """
    global _V6_BACKUP_THREAD_STARTED
    if _V6_BACKUP_THREAD_STARTED:
        return
    _V6_BACKUP_THREAD_STARTED=True
    def worker():
        time.sleep(12)
        while True:
            try:
                maybe_auto_backup(settings)
            except Exception as exc:
                print(f"Seeker automatic backup warning: {exc}", flush=True)
            time.sleep(6*60*60)
    threading.Thread(target=worker,name="seeker-backups",daemon=True).start()

