"""FastAPI backend for LifeOps Agent.

Serves the dashboard from `frontend/` and exposes the planning API. The Gemini
key stays on the server; the browser only ever talks to these endpoints.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agent
import agent_trace

FRONTEND_DIR = Path(__file__).parent / "frontend"
HEARTBEAT_SECONDS = 15
POLL_SECONDS = 0.1


def load_dotenv(path: Path) -> None:
    """Read `KEY=value` lines from a local .env, for development convenience.

    Real environment variables always win, so hosted deployments that inject
    their own configuration are unaffected. Kept dependency-free on purpose.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_dotenv(Path(__file__).parent / ".env")

app = FastAPI(
    title="LifeOps Agent",
    description="Plan tonight around tomorrow.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class PlanRequest(BaseModel):
    message: str = Field(default="", max_length=4000)
    energy_level: str = Field(default="medium")
    location: str | None = Field(default=None, max_length=120)
    saved_places: dict[str, str] = Field(default_factory=dict)
    # The visitor's own Gemini key. Used for their request only: never logged,
    # never written to disk, never echoed back in a response.
    api_key: str | None = Field(default=None, max_length=200, repr=False, exclude=True)


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Readiness probe that also tells the UI whether a visitor needs their own key."""
    return {
        "status": "ok",
        "llm_configured": agent.is_configured(),
        "byo_key_required": not agent.is_configured(),
        "model": agent.model_name(),
    }


@app.post("/api/plan")
def plan(request: PlanRequest) -> dict[str, Any]:
    """Plan one evening and return the full dashboard payload in one response."""
    return agent.run(
        message=request.message,
        energy_level=request.energy_level,
        location=request.location,
        saved_places=_clean_places(request.saved_places),
        api_key=request.api_key,
    )


@app.post("/api/plan/stream")
async def plan_stream(request: PlanRequest) -> StreamingResponse:
    """Same as /api/plan, but streams each tool call as it happens (SSE)."""
    recorder = agent_trace.TraceRecorder()

    async def events():
        task = asyncio.create_task(
            asyncio.to_thread(
                agent.run,
                message=request.message,
                energy_level=request.energy_level,
                location=request.location,
                saved_places=_clean_places(request.saved_places),
                api_key=request.api_key,
                recorder=recorder,
            )
        )
        yield _sse({"type": "start"})
        idle = 0.0
        while True:
            drained = _drain(recorder.events)
            for event in drained:
                yield _sse(event)
            if drained:
                idle = 0.0
            if task.done():
                break
            await asyncio.sleep(POLL_SECONDS)
            idle += POLL_SECONDS
            if idle >= HEARTBEAT_SECONDS:
                idle = 0.0
                yield ": keep-alive\n\n"

        try:
            payload = task.result()
        except Exception as error:  # noqa: BLE001 - reported to the client
            payload = {
                "status": "error",
                "error": {"code": "server_error", "message": f"{type(error).__name__}: {error}"},
                "agent_trace": agent.build_trace(recorder),
                "recommended_plan": None,
                "alternatives": [],
            }
        yield _sse({"type": "result", "payload": payload})
        yield _sse({"type": "done"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _clean_places(places: dict[str, str]) -> dict[str, str]:
    """Keep the saved-places payload small and printable."""
    cleaned = {}
    for name, value in list(places.items())[:12]:
        name, value = str(name).strip()[:40], str(value).strip()[:120]
        if name and value:
            cleaned[name] = value
    return cleaned


def _drain(source: queue.Queue) -> list[dict[str, Any]]:
    events = []
    while True:
        try:
            events.append(source.get_nowait())
        except queue.Empty:
            return events


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


# The dashboard is served from the same origin, so the browser never needs a key.
if FRONTEND_DIR.is_dir():

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=bool(os.getenv("DEV_RELOAD")),
    )
