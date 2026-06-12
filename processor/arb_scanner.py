"""
Arbitrage scanner.

For a single event, an arbitrage exists when you can back *every* outcome, each
at the best price offered by *some* book, such that the implied probabilities
sum to less than 1. Then no matter who wins you profit.

  implied = Σ over outcomes of (1 / best_back_price[outcome])
  arb if implied < 1  ->  profit_pct = (1/implied - 1) * 100

Stake split (so every outcome returns the same total): each leg gets
  stake_pct[outcome] = (1 / price[outcome]) / implied

Important exclusions:
  - Skip exchange LAY markets (h2h_lay). Backing every outcome is a back-side
    strategy; mixing in lay prices would miscompute the arb.
  - Need at least 2 distinct outcomes priced, and every outcome must have at
    least one book quoting it, or there's no valid all-outcomes cover.

This is intentionally market-agnostic on outcome count: works for 2-way (NRL)
and would extend to 3-way (soccer with a draw) if those markets are added.
"""

from __future__ import annotations

from collections import defaultdict

from models import flatten, PriceKey
from events import ArbEvent, ArbLeg

# A tiny tolerance so floating-point noise doesn't flag a 99.999% book as arb.
ARB_EPSILON = 1e-6


def scan_arbitrage(snapshot: dict) -> ArbEvent | None:
    """Return an ArbEvent if the best cross-book back prices imply < 100%."""
    # best price per outcome, and which book offers it
    best_price: dict[str, float] = {}
    best_book: dict[str, str] = {}

    for key, price in flatten(snapshot).items():
        if key.market.endswith("_lay"):
            continue  # back markets only
        if price <= 1.0:
            continue  # invalid / not a real decimal back price
        if price > best_price.get(key.outcome, 0.0):
            best_price[key.outcome] = price
            best_book[key.outcome] = key.bookmaker

    # Need every outcome covered; for h2h that's 2 outcomes.
    if len(best_price) < 2:
        return None

    implied = sum(1.0 / p for p in best_price.values())
    if implied >= 1.0 - ARB_EPSILON:
        return None  # no arb

    profit_pct = round((1.0 / implied - 1.0) * 100, 3)
    legs = [
        ArbLeg(
            bookmaker=best_book[outcome],
            outcome=outcome,
            price=best_price[outcome],
            stake_pct=round((1.0 / best_price[outcome]) / implied, 4),
        )
        for outcome in best_price
    ]
    return ArbEvent(
        sport_key=snapshot.get("sport_key", ""),
        event_id=snapshot.get("event_id", ""),
        home_team=snapshot.get("home_team", ""),
        away_team=snapshot.get("away_team", ""),
        commence_time=snapshot.get("commence_time", ""),
        legs=legs,
        implied_pct=round(implied * 100, 3),
        profit_pct=profit_pct,
    )
