import contextlib
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app import deps, runs

log = logging.getLogger(__name__)

ALWAYS_ON = ("/health",)


def live_enabled() -> bool:
    return os.environ.get("LIVE_ENABLED", "true").lower() == "true"


def create_app(env=None) -> FastAPI:
    env = os.environ if env is None else env
    try:
        services = deps.build_services(env)
    except deps.NotConfigured as exc:
        services = None
        log.warning("run API disabled: %s", exc)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        yield
        if services is not None:
            await services.http.aclose()

    api = FastAPI(title="Corridor", lifespan=lifespan)

    @api.middleware("http")
    async def pause_gate(request: Request, call_next):
        if not live_enabled() and request.url.path not in ALWAYS_ON:
            return JSONResponse(
                {"status": "paused", "detail": "Corridor is paused to protect the spend cap."},
                status_code=503,
            )
        return await call_next(request)

    @api.get("/health")
    def health():
        return {"status": "ok", "service": "corridor", "live_enabled": live_enabled()}

    if services is None:

        @api.post("/runs")
        async def runs_unavailable():
            raise HTTPException(status_code=503, detail="Corridor is not configured")

    else:
        api.include_router(
            runs.make_router(
                make_orchestrator=deps.orchestrator_factory(services),
                events=services.events,
            )
        )
    return api


app = create_app()
