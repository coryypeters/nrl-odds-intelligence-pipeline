"""
FastAPI app (Step 4): REST + WebSocket bridge to the dashboard.

  - REST routes from routes/events.py (history, odds, health)
  - WS /ws/events: client connects, receives every detected event live
  - On startup, a background task subscribes to Redis `events_live` and
    fans messages out to all connected sockets.

CORS is open in dev so the Vite frontend (different port) can call the API.
Tighten the allowed origins for a real deployment.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from routes.events import router as events_router
from websocket import ConnectionManager, redis_subscriber

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("api")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(redis_subscriber(manager, REDIS_URL))
    log.info("API started, Redis subscriber running")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    log.info("API shut down")


app = FastAPI(title="Odds Intelligence API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # dev only; restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events_router)


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # We don't expect client messages; this keeps the socket open and
            # detects disconnects.
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception:
        await manager.disconnect(ws)
