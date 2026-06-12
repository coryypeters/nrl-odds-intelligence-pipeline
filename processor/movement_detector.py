"""
Movement + steam detection.

MOVEMENT: a single price shift past a threshold on one book/outcome.
  Trigger: |pct_change| >= MOVEMENT_PCT_THRESHOLD

STEAM: the sharp-money signal — several *different* books shortening (or
lengthening) the *same* outcome in the *same* direction within a short window.
A lone book moving is noise; the whole market moving together is signal.
  Trigger: >= STEAM_MIN_BOOKS distinct books move the same outcome+direction
           within STEAM_WINDOW_SECONDS.

We keep a short rolling history of recent moves per (event, outcome, direction)
in memory. Entries older than the window are pruned on each call, so memory
stays bounded by "moves in the last N seconds" — tiny in practice.

Both functions are pure-ish (state is an explicit field) so they unit-test
without Redis or a live feed.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from models import PriceDelta
from events import MovementEvent, SteamEvent

# Tunables (could be surfaced in the dashboard later).
MOVEMENT_PCT_THRESHOLD = 2.0    # report single moves of >= 2%
STEAM_WINDOW_SECONDS = 120      # books must move within this window to count as steam
STEAM_MIN_BOOKS = 3             # how many distinct books = consensus / steam
STEAM_MIN_AVG_PCT = 1.0         # ignore trivially small coordinated moves


class MovementSteamDetector:
    def __init__(self):
        # (event_id, outcome, direction) -> deque[(ts, bookmaker, pct_change)]
        self._recent: dict[tuple[str, str, str], deque] = defaultdict(deque)

    def detect(self, deltas: list[PriceDelta], now: float | None = None):
        """Return (movements, steams) detected from this batch of deltas."""
        now = now if now is not None else time.time()
        movements: list[MovementEvent] = []
        steams: list[SteamEvent] = []

        for d in deltas:
            # Only consider real bookmaker back markets for steam/movement.
            # Exchange lay prices (h2h_lay) move for different reasons; skip them.
            if d.key.market.endswith("_lay"):
                continue

            # --- single-move movement event ---
            if abs(d.pct_change) >= MOVEMENT_PCT_THRESHOLD:
                movements.append(MovementEvent(
                    sport_key=d.sport_key, event_id=d.key.event_id,
                    home_team=d.home_team, away_team=d.away_team,
                    commence_time=d.commence_time,
                    bookmaker=d.key.bookmaker, market=d.key.market,
                    outcome=d.key.outcome,
                    old_price=d.old_price, new_price=d.new_price,
                    pct_change=d.pct_change, direction=d.direction,
                    detected_at=now,
                ))

            # --- feed the steam window ---
            if d.direction == "unchanged":
                continue
            bucket = self._recent[(d.key.event_id, d.key.outcome, d.direction)]
            bucket.append((now, d.key.bookmaker, d.pct_change))

        # --- evaluate steam across all buckets, pruning old entries ---
        cutoff = now - STEAM_WINDOW_SECONDS
        for (event_id, outcome, direction), bucket in list(self._recent.items()):
            while bucket and bucket[0][0] < cutoff:
                bucket.popleft()
            if not bucket:
                del self._recent[(event_id, outcome, direction)]
                continue

            books = {bm for (_ts, bm, _pct) in bucket}
            if len(books) < STEAM_MIN_BOOKS:
                continue
            avg_pct = sum(abs(pct) for (_ts, _bm, pct) in bucket) / len(bucket)
            if avg_pct < STEAM_MIN_AVG_PCT:
                continue

            # grab a delta in this group for match context
            ctx = next((d for d in deltas
                        if d.key.event_id == event_id and d.key.outcome == outcome), None)
            steams.append(SteamEvent(
                sport_key=ctx.sport_key if ctx else "",
                event_id=event_id,
                home_team=ctx.home_team if ctx else "",
                away_team=ctx.away_team if ctx else "",
                commence_time=ctx.commence_time if ctx else "",
                outcome=outcome,
                books_moved=sorted(books),
                avg_pct_change=round(avg_pct, 3),
                direction=direction,
                detected_at=now,
            ))
            # Clear this bucket so the same steam isn't re-emitted every poll.
            bucket.clear()
            del self._recent[(event_id, outcome, direction)]

        return movements, steams
