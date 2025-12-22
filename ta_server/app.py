from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import RunCreateRequest, RunCreateResponse, RunDetail, RunSummary
from .run_manager import RunManager


app = FastAPI(title="TradingAgents Web API", version="0.1.0")
run_manager = RunManager()


@app.on_event("startup")
async def _on_startup() -> None:
    run_manager.set_loop(asyncio.get_running_loop())


# Local dev defaults: Vite on 5173
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/runs", response_model=RunCreateResponse)
def create_run(req: RunCreateRequest) -> RunCreateResponse:
    session = run_manager.create_run(req)
    return RunCreateResponse(run_id=session.run_id)


@app.get("/api/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    return run_manager.list_runs()


@app.get("/api/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    session = run_manager.get_run(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="run not found")
    return session.snapshot()


@app.get("/api/runs/{run_id}/events")
def get_events(run_id: str, limit: int = 500) -> dict:
    session = run_manager.get_run(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, "events": session.list_events(limit=limit)}


@app.websocket("/api/runs/{run_id}/stream")
async def run_stream(ws: WebSocket, run_id: str) -> None:
    session = run_manager.get_run(run_id)
    if session is None:
        await ws.close(code=1008)
        return

    await ws.accept()

    # Send an initial snapshot and recent events.
    await ws.send_json(
        {
            "type": "snapshot",
            "run_id": run_id,
            "payload": session.snapshot().model_dump(mode="json"),
        }
    )
    for ev in session.list_events(limit=200):
        await ws.send_json(ev)

    queue = session.subscribe()
    try:
        while True:
            ev = await queue.get()
            await ws.send_json(ev)
    except WebSocketDisconnect:
        session.unsubscribe(queue)


# Optional: if a built frontend exists, serve it from web/dist.
_DIST_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"


@app.get("/")
def serve_index():
    index = _DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "message": "Frontend not built. Run Vite dev server at http://localhost:5173",
        "api_health": "/api/health",
    }


if _DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=_DIST_DIR, html=True), name="static")


@app.get("/{full_path:path}")
def serve_spa_fallback(full_path: str):
    """
    SPA fallback for client-side routes like /en, /zh, /en/runs/:id.
    Only used when `web/dist` exists.
    """
    if not _DIST_DIR.exists():
        raise HTTPException(status_code=404, detail="frontend not built")

    # Let FastAPI handle API routes normally.
    if full_path.startswith("api"):
        raise HTTPException(status_code=404, detail="not found")

    candidate = _DIST_DIR / full_path
    if candidate.exists() and candidate.is_file():
        return FileResponse(candidate)

    index = _DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="index not found")
