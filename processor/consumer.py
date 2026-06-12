"""
Processor entrypoint (Step 2): consume raw_odds, run the diff engine.

Reads the `raw_odds` stream through a Redis consumer group so that:
  - each message is delivered at-least-once (we XACK only after handling)
  - a crash/restart resumes from un-acked messages (no lost snapshots)
  - we *could* scale to multiple processor replicas sharing the group

For Step 2 we just log detected deltas. Step 3 plugs the movement/steam and
arb detectors in right where `handle_deltas` is called; Step 4 publishes the
resulting events to Redis for the API/WebSocket layer.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time

import redis

from diff_engine import DiffEngine
from models import PriceDelta
from movement_detector import MovementSteamDetector
from arb_scanner import scan_arbitrage
from event_store import EventStore

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("processor")

RAW_ODDS_STREAM = "raw_odds"
GROUP = "processors"
CONSUMER = os.getenv("CONSUMER_NAME", "processor-1")
BLOCK_MS = 5000          # how long XREADGROUP blocks waiting for new messages
BATCH = 50               # max messages per read


class Processor:
    def __init__(self):
        url = os.environ.get("REDIS_URL", "redis://redis:6379")
        self._r = redis.from_url(url, decode_responses=True)
        self._diff = DiffEngine(redis_url=url)
        self._detector = MovementSteamDetector()
        self._store = EventStore(redis_url=url)
        self._running = True

    def ensure_group(self) -> None:
        """Create the consumer group, tolerating 'already exists'."""
        try:
            # mkstream so we don't error if the poller hasn't created it yet;
            # id='0' so we read the full backlog the first time.
            self._r.xgroup_create(RAW_ODDS_STREAM, GROUP, id="0", mkstream=True)
            log.info("Created consumer group '%s' on '%s'", GROUP, RAW_ODDS_STREAM)
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                log.info("Consumer group '%s' already exists", GROUP)
            else:
                raise

    def handle_snapshot(self, snapshot: dict) -> None:
        """Diff, detect, and publish events for one snapshot."""
        deltas = self._diff.process(snapshot)

        movements, steams = self._detector.detect(deltas)
        arb = scan_arbitrage(snapshot)

        for m in movements:
            log.info("MOVEMENT %s | %s @ %s: %.2f -> %.2f (%+.2f%%) %s",
                     m.sport_key, m.outcome, m.bookmaker,
                     m.old_price, m.new_price, m.pct_change, m.direction)
            self._store.publish(m.to_dict())

        for s in steams:
            log.info("STEAM %s | %s %s across %d books (avg %+.2f%%): %s",
                     s.sport_key, s.outcome, s.direction, len(s.books_moved),
                     s.avg_pct_change, ", ".join(s.books_moved))
            self._store.publish(s.to_dict())

        if arb is not None:
            legs = " | ".join(f"{l.outcome}@{l.price} ({l.bookmaker})" for l in arb.legs)
            log.info("ARB %s | %s vs %s: %.2f%% implied, %+.2f%% profit -> %s",
                     arb.sport_key, arb.home_team, arb.away_team,
                     arb.implied_pct, arb.profit_pct, legs)
            self._store.publish(arb.to_dict())

    def run(self) -> None:
        self.ensure_group()
        log.info("Processor '%s' consuming '%s'...", CONSUMER, RAW_ODDS_STREAM)
        while self._running:
            try:
                resp = self._r.xreadgroup(
                    GROUP, CONSUMER, {RAW_ODDS_STREAM: ">"},
                    count=BATCH, block=BLOCK_MS,
                )
            except redis.RedisError:
                log.exception("XREADGROUP failed; retrying in 2s")
                time.sleep(2)
                continue

            if not resp:
                continue  # block timed out, just loop

            for _stream, messages in resp:
                for msg_id, fields in messages:
                    try:
                        snapshot = json.loads(fields["payload"])
                        self.handle_snapshot(snapshot)
                        self._r.xack(RAW_ODDS_STREAM, GROUP, msg_id)
                    except Exception:
                        # Don't ack: message stays pending for retry/inspection.
                        log.exception("Failed handling message %s", msg_id)

    def stop(self, *_):
        log.info("Stopping processor...")
        self._running = False


def main() -> None:
    proc = Processor()
    signal.signal(signal.SIGTERM, proc.stop)
    signal.signal(signal.SIGINT, proc.stop)
    proc.run()


if __name__ == "__main__":
    main()
