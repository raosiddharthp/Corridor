import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Corridor")

ALWAYS_ON = ("/health",)


def live_enabled() -> bool:
    return os.environ.get("LIVE_ENABLED", "true").lower() == "true"


@app.middleware("http")
async def pause_gate(request: Request, call_next):
    if not live_enabled() and request.url.path not in ALWAYS_ON:
        return JSONResponse(
            {"status": "paused", "detail": "Corridor is paused to protect the spend cap."},
            status_code=503,
        )
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok", "service": "corridor", "live_enabled": live_enabled()}
