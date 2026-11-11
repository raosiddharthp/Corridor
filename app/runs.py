"""HTTP surface for runs: start a run and stream its events."""
import asyncio
import json
import secrets
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

import pipeline.seed as seed
from pipeline.events import to_dict

ORDERS = {s.ref: s for s in (seed.FP_88213, seed.FP_88214)}
POLL_SECONDS = 0.02
WINDOW_SECONDS = 60
_RUN_ID = r"^[A-Za-z0-9_-]{1,64}$"


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_ref: str
    demo_hostile: bool = False


def _sse(kind: str, data: dict) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def make_router(
    *,
    make_orchestrator,
    events,
    clock=time.monotonic,
    max_concurrent: int = 4,
    max_per_minute: int = 30,
) -> APIRouter:
    router = APIRouter()
    active = 0
    stamps: deque = deque()
    tasks: set = set()

    def allow() -> bool:
        now = clock()
        while stamps and now - stamps[0] > WINDOW_SECONDS:
            stamps.popleft()
        if len(stamps) >= max_per_minute:
            return False
        stamps.append(now)
        return True

    async def stream(run_id, task):
        sent = 0
        while True:
            finished = task.done()
            for event in events.read(run_id, after=sent):
                sent = event.seq
                yield _sse(event.kind, to_dict(event))
            if finished:
                break
            await asyncio.sleep(POLL_SECONDS)
        try:
            yield _sse("result", task.result().to_dict())
        except Exception:
            yield _sse("error", {"reason": "run failed"})

    @router.post("/runs")
    async def start_run(body: RunRequest):
        nonlocal active
        order = ORDERS.get(body.order_ref)
        if order is None:
            raise HTTPException(status_code=404, detail="unknown order")
        if active >= max_concurrent or not allow():
            raise HTTPException(status_code=429, detail="too many runs, try again shortly")
        run_id = secrets.token_urlsafe(9)
        orchestrator = make_orchestrator(body.demo_hostile)
        active += 1
        task = asyncio.create_task(orchestrator.run(run_id, order))
        tasks.add(task)

        def done(finished):
            nonlocal active
            active -= 1
            tasks.discard(finished)

        task.add_done_callback(done)
        return StreamingResponse(
            stream(run_id, task),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @router.get("/runs/{run_id}/events")
    async def read_events(run_id: str = Path(pattern=_RUN_ID), after: int = 0):
        stored = events.read(run_id)
        if not stored:
            raise HTTPException(status_code=404, detail="unknown run")
        return {"events": [to_dict(e) for e in stored if e.seq > max(after, 0)]}

    return router
