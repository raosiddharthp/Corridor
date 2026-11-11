import contextlib
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import deps, runs
from pipeline import seed

log = logging.getLogger(__name__)

ALWAYS_ON = ("/health",)
API_PREFIXES = ("/runs", "/demo")
STATIC_DIR = Path(__file__).parent / "static"
RESET_COOLDOWN_SECONDS = 10
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def live_enabled() -> bool:
    return os.environ.get("LIVE_ENABLED", "true").lower() == "true"


def _paused_for(request: Request) -> bool:
    """When paused, block runs and writes. The UI page, /config and /health stay up."""
    path = request.url.path
    if live_enabled() or path in ALWAYS_ON:
        return False
    return request.method != "GET" or path.startswith(API_PREFIXES)


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

    api = FastAPI(
        title="Corridor",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @api.middleware("http")
    async def pause_gate(request: Request, call_next):
        if _paused_for(request):
            return JSONResponse(
                {"status": "paused", "detail": "Corridor is paused to protect the spend cap."},
                status_code=503,
            )
        return await call_next(request)

    @api.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @api.get("/health")
    def health():
        return {"status": "ok", "service": "corridor", "live_enabled": live_enabled()}

    @api.get("/config")
    def config():
        return {
            "currency": seed.CURRENCY,
            "buyer": seed.BUYER.name,
            "supplier": seed.SUPPLIER.name,
            "mandate": {
                "cap_minor": seed.MANDATE_CAP_MINOR,
                "budget_minor": seed.MANDATE_BUDGET_MINOR,
                "max_uses": seed.MANDATE_MAX_USES,
                "frequency": seed.MANDATE_FREQUENCY,
            },
            "price_tolerance_bps": seed.PRICE_TOLERANCE_BPS,
            "scenarios": [
                {"order_ref": s.ref, "agreed_minor": s.agreed_minor}
                for s in runs.ORDERS.values()
            ],
        }

    if services is None:

        @api.post("/runs")
        async def runs_unavailable():
            raise HTTPException(status_code=503, detail="Corridor is not configured")

        @api.post("/demo/reset")
        async def reset_unavailable():
            raise HTTPException(status_code=503, detail="Corridor is not configured")

    else:
        api.include_router(
            runs.make_router(
                make_orchestrator=deps.orchestrator_factory(services),
                events=services.events,
            )
        )
        last_reset = [float("-inf")]

        @api.post("/demo/reset")
        def demo_reset():
            now = time.monotonic()
            if now - last_reset[0] < RESET_COOLDOWN_SECONDS:
                raise HTTPException(status_code=429, detail="reset was just used, try again shortly")
            last_reset[0] = now
            deps.reset_demo_state(services)
            return {"status": "reset"}

    if STATIC_DIR.is_dir():
        api.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    return api


app = create_app()
