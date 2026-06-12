"""
Diff engine.

Keeps the most recent snapshot's price map for each event in Redis, then on
each new snapshot computes the per-price deltas versus what we last saw.

Why store the previous snapshot in Redis (not just in memory)?
  - the processor can restart without losing its comparison baseline
  - later we may run multiple processor replicas; shared state keeps them consistent

Keys in Redis:
  prev:{event_id}  -> JSON {("book|market|outcome"): price}  (last seen prices)
                      with a TTL so finished matches age out automatically.

The diff itself is pure (compute_deltas) so it's trivially unit-testable
without Redis — see test at the bottom of the file / processor tests.
"""

from __future__ import annotations

import json
import logging

import redis

from models import PriceKey, PriceDelta, flatten

log = logging.getLogger("diff_engine")

PREV_KEY_PREFIX = "prev:"
PREV_TTL_SECONDS = 60 * 60 * 6  # 6h: long enough to span a match + pre-match drift


def _inner_key(k: PriceKey) -> str:
    """Serialise the non-event part of a PriceKey for the stored map."""
    return f"{k.bookmaker}|{k.market}|{k.outcome}"


def compute_deltas(
    prev_prices: dict[str, float],
    snapshot: dict,
) -> list[PriceDelta]:
    """
    Pure diff: compare a previous {inner_key: price} map against a new snapshot.
    Returns one PriceDelta per price that changed. New prices (no previous
    value) are not deltas — they establish a baseline for next time.
    """
    deltas: list[PriceDelta] = []
    event_id = snapshot.get("event_id", "")
    new_fetched = float(snapshot.get("fetched_at", 0.0))
    ctx = dict(
        sport_key=snapshot.get("sport_key", ""),
        home_team=snapshot.get("home_team", ""),
        away_team=snapshot.get("away_team", ""),
        commence_time=snapshot.get("commence_time", ""),
    )

    for key, new_price in flatten(snapshot).items():
        ik = _inner_key(key)
        if ik not in prev_prices:
            continue  # first time we've seen this price; baseline only
        old_price = prev_prices[ik]
        if old_price == new_price:
            continue  # no movement
        deltas.append(
            PriceDelta(
                key=key,
                old_price=old_price,
                new_price=new_price,
                old_fetched_at=0.0,        # previous fetch time not retained per-price
                new_fetched_at=new_fetched,
                **ctx,
            )
        )
    return deltas


class DiffEngine:
    def __init__(self, redis_url: str):
        self._r = redis.from_url(redis_url, decode_responses=True)

    def process(self, snapshot: dict) -> list[PriceDelta]:
        """Diff one snapshot against stored state, then update the baseline."""
        event_id = snapshot.get("event_id", "")
        if not event_id:
            return []

        prev_raw = self._r.get(PREV_KEY_PREFIX + event_id)
        prev_prices: dict[str, float] = json.loads(prev_raw) if prev_raw else {}

        deltas = compute_deltas(prev_prices, snapshot)

        # Update baseline with the full new price map.
        new_map = {_inner_key(k): v for k, v in flatten(snapshot).items()}
        self._r.set(PREV_KEY_PREFIX + event_id, json.dumps(new_map), ex=PREV_TTL_SECONDS)

        if deltas:
            log.info("%s vs %s: %d price change(s)",
                     snapshot.get("home_team"), snapshot.get("away_team"), len(deltas))
        return deltas
