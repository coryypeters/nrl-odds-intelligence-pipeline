"""
Writes raw odds snapshots into a Redis Stream.

Stream layout:
  key   : "raw_odds"
  fields: sport_key, event_id, payload (JSON-encoded MatchSnapshot)

Downstream, the processor reads this stream via a consumer group so we get
at-least-once delivery + replay. We cap the stream length (MAXLEN ~) so a
long-running deploy doesn't grow Redis unbounded — the processor only needs
recent snapshots to diff against.
"""

from __future__ import annotations

import dataclasses
import json
import logging

import redis

from odds_client import MatchSnapshot

log = logging.getLogger("stream_writer")

RAW_ODDS_STREAM = "raw_odds"
STREAM_MAXLEN = 5000  # approximate cap; Redis trims with '~' for efficiency


class StreamWriter:
    def __init__(self, redis_url: str):
        self._r = redis.from_url(redis_url, decode_responses=True)

    def ping(self) -> bool:
        return self._r.ping()

    def write_snapshot(self, snap: MatchSnapshot) -> str:
        payload = json.dumps(dataclasses.asdict(snap))
        msg_id = self._r.xadd(
            RAW_ODDS_STREAM,
            {
                "sport_key": snap.sport_key,
                "event_id": snap.event_id,
                "payload": payload,
            },
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
        log.debug("xadd %s -> %s (%d outcomes)", snap.event_id, msg_id, len(snap.outcomes))
        return msg_id

    def write_many(self, snaps: list[MatchSnapshot]) -> int:
        for s in snaps:
            self.write_snapshot(s)
        return len(snaps)

    def write_scores(self, scores: list[dict]) -> int:
        """Store scores in a Redis hash keyed by event_id (TTL so they age out)."""
        n = 0
        for sc in scores:
            eid = sc.get("id")
            if not eid:
                continue
            self._r.set(f"score:{eid}", json.dumps(sc), ex=60 * 60 * 12)  # 12h TTL
            n += 1
        return n
