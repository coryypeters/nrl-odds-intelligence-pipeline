"""
Match-window-aware poller.

Loop, per sport:
  1. Determine cadence (idle / pre_match / in_play) from upcoming kickoff times.
  2. If due, fetch odds via OddsAPIClient and write snapshots to Redis Streams.
  3. Reschedule the next poll for that sport at the chosen cadence.

Cadence decision uses commence_time on the events we already fetched, so we
"learn" the schedule from the data instead of hardcoding fixture calendars.
On a cold start (no cached events) we do one idle-cadence poll to discover them.

Quota safety: OddsAPIClient raises QuotaExhausted when the monthly budget is
gone; we catch it, log loudly, and back the whole poller off to hourly so a
runaway loop can't burn a paid plan.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from odds_client import OddsAPIClient, QuotaExhausted, MatchSnapshot
from sports_config import SPORTS, Sport, PRE_MATCH_HRS
from stream_writer import StreamWriter

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("poller")

QUOTA_BACKOFF_SECONDS = 3600  # when exhausted, slow everything to hourly


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def choose_cadence(sport: Sport, snaps: list[MatchSnapshot]) -> int:
    """Pick poll interval (seconds) from the nearest kickoff among snapshots."""
    now = datetime.now(timezone.utc)
    nearest_delta_hrs: float | None = None
    any_live = False

    for s in snaps:
        kickoff = _parse_iso(s.commence_time)
        if kickoff is None:
            continue
        delta_hrs = (kickoff - now).total_seconds() / 3600.0
        if -3.0 <= delta_hrs <= 0.0:   # kicked off within last ~3h -> assume live
            any_live = True
        if delta_hrs >= 0 and (nearest_delta_hrs is None or delta_hrs < nearest_delta_hrs):
            nearest_delta_hrs = delta_hrs

    if any_live:
        return sport.cadence.in_play_seconds
    if nearest_delta_hrs is not None and nearest_delta_hrs <= PRE_MATCH_HRS:
        return sport.cadence.pre_match_seconds
    return sport.cadence.idle_seconds


class Poller:
    def __init__(self):
        self.api = OddsAPIClient(api_key=os.environ["ODDS_API_KEY"])
        self.writer = StreamWriter(redis_url=os.environ.get("REDIS_URL", "redis://redis:6379"))
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self._quota_exhausted = False

    def start(self) -> None:
        if not self.writer.ping():
            raise RuntimeError("Cannot reach Redis")
        log.info("Redis OK. Scheduling %d sports.", len(SPORTS))
        # Kick each sport off immediately; each run reschedules its own next poll.
        for sid, sport in SPORTS.items():
            self.scheduler.add_job(
                self.poll_sport, args=[sid, sport], id=sid,
                next_run_time=datetime.now(timezone.utc),
            )
        self.scheduler.start()

    def poll_sport(self, sport_id: str, sport: Sport) -> None:
        try:
            snaps = self.api.fetch_odds(sport.key, sport.regions, sport.markets)
            written = self.writer.write_many(snaps)
            # Scores are a free endpoint; fetch live/recent results too (best-effort).
            try:
                scores = self.api.fetch_scores(sport.key, days_from=1)
                n_scores = self.writer.write_scores(scores)
            except Exception:
                n_scores = 0
            cadence = QUOTA_BACKOFF_SECONDS if self._quota_exhausted else choose_cadence(sport, snaps)
            log.info("%s: %d events, %d snapshots, %d scores, next in %ds",
                     sport.label, len(snaps), written, n_scores, cadence)
        except QuotaExhausted as e:
            self._quota_exhausted = True
            cadence = QUOTA_BACKOFF_SECONDS
            log.error("QUOTA EXHAUSTED (%s) — backing off %s to %ds", e, sport.label, cadence)
        except Exception:
            cadence = sport.cadence.idle_seconds
            log.exception("%s: poll failed, retrying in %ds", sport.label, cadence)

        # Reschedule this sport's next poll.
        self.scheduler.add_job(
            self.poll_sport, args=[sport_id, sport], id=sport_id, replace_existing=True,
            next_run_time=datetime.fromtimestamp(time.time() + cadence, tz=timezone.utc),
        )

    def shutdown(self) -> None:
        log.info("Shutting down poller...")
        self.scheduler.shutdown(wait=False)
        self.api.close()


def main() -> None:
    poller = Poller()

    def _handle(signum, _frame):
        poller.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    poller.start()
    log.info("Poller running. Ctrl-C to stop.")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
