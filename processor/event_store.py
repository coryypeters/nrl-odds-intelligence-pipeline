"""
Event store + live publish.

Every detected event is:
  1. de-duplicated by its stable `event_key` (a steam/arb seen twice in quick
     succession shouldn't spam the feed),
  2. appended to a capped Redis Stream `events` (history the API can page),
  3. published to a Redis pub/sub channel `events_live` (Step 4's WebSocket
     layer subscribes and pushes straight to the dashboard).

De-dup uses a short-TTL SET key per event_key so identical events within
DEDUP_TTL_SECONDS are dropped, while the same logical arb reappearing much
later is still allowed through.
"""

from __future__ import annotations

import json
import logging

import redis

log = logging.getLogger("event_store")

EVENTS_STREAM = "events"          # history (XADD, capped)
EVENTS_CHANNEL = "events_live"    # pub/sub for live push
EVENTS_MAXLEN = 2000
DEDUP_TTL_SECONDS = 90


class EventStore:
    def __init__(self, redis_url: str):
        self._r = redis.from_url(redis_url, decode_responses=True)

    def publish(self, event: dict) -> bool:
        """Store + broadcast one event. Returns False if de-duped."""
        event_key = event.get("event_key", "")
        if event_key:
            # SET NX EX -> only succeeds if not seen in the last TTL window.
            fresh = self._r.set(f"seen:{event_key}", "1", nx=True, ex=DEDUP_TTL_SECONDS)
            if not fresh:
                return False

        payload = json.dumps(event)
        self._r.xadd(EVENTS_STREAM, {"payload": payload},
                     maxlen=EVENTS_MAXLEN, approximate=True)
        self._r.publish(EVENTS_CHANNEL, payload)
        return True
