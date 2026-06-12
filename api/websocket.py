"""
WebSocket connection manager.

Tracks every connected dashboard client and fans out events to all of them.
A single background task subscribes to the Redis `events_live` pub/sub channel
(published by the processor's EventStore) and broadcasts each message to all
open sockets.

Design:
  - one Redis pub/sub subscription per server process (not per client)
  - broadcast is best-effort; a dead socket is dropped, never blocks others
"""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import WebSocket

log = logging.getLogger("ws")

EVENTS_CHANNEL = "events_live"


class ConnectionManager:
    def __init__(self):
        self._active: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._active.add(ws)
        log.info("client connected (%d total)", len(self._active))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._active.discard(ws)
        log.info("client disconnected (%d total)", len(self._active))

    async def broadcast(self, message: str) -> None:
        async with self._lock:
            targets = list(self._active)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._active.discard(ws)


async def redis_subscriber(manager: ConnectionManager, redis_url: str) -> None:
    """Background task: relay Redis pub/sub messages to all WebSocket clients."""
    r = aioredis.from_url(redis_url, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    log.info("subscribed to '%s'", EVENTS_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            await manager.broadcast(message["data"])
    except asyncio.CancelledError:
        await pubsub.unsubscribe(EVENTS_CHANNEL)
        await r.aclose()
        raise
