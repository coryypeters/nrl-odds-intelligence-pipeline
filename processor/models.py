"""
Shared data shapes for the processor stage.

The poller writes JSON snapshots into the `raw_odds` stream. Here we define:
  - PriceKey   : uniquely identifies one quotable price (event/book/market/outcome)
  - PriceDelta : a single price change between two snapshots of the same event
  - flatten()  : turn a raw snapshot's outcome list into a {PriceKey: price} map

Design note on Betfair: the feed carries both `h2h` (back) and `h2h_lay`
markets. We keep `market` in the key so lay prices never get compared against,
or mistaken for, back prices. The arb scanner (Step 3) will explicitly ignore
`*_lay` markets when computing cross-book arbitrage.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceKey:
    event_id: str
    bookmaker: str
    market: str       # h2h, h2h_lay, spreads, totals, ...
    outcome: str      # team name / Over / Under

    def __str__(self) -> str:
        return f"{self.event_id}|{self.bookmaker}|{self.market}|{self.outcome}"


@dataclass
class PriceDelta:
    key: PriceKey
    old_price: float
    new_price: float
    old_fetched_at: float
    new_fetched_at: float
    # convenience context for downstream detectors / dashboard
    sport_key: str
    home_team: str
    away_team: str
    commence_time: str

    @property
    def abs_change(self) -> float:
        return round(self.new_price - self.old_price, 4)

    @property
    def pct_change(self) -> float:
        if self.old_price == 0:
            return 0.0
        return round((self.new_price - self.old_price) / self.old_price * 100, 3)

    @property
    def direction(self) -> str:
        if self.new_price > self.old_price:
            return "lengthened"   # odds drifted out (less likely)
        if self.new_price < self.old_price:
            return "shortened"    # odds came in (more likely / money came)
        return "unchanged"


def flatten(snapshot: dict) -> dict[PriceKey, float]:
    """Map a raw snapshot dict -> {PriceKey: price} for easy diffing."""
    prices: dict[PriceKey, float] = {}
    event_id = snapshot.get("event_id", "")
    for o in snapshot.get("outcomes", []):
        key = PriceKey(
            event_id=event_id,
            bookmaker=o.get("bookmaker", "?"),
            market=o.get("market", "h2h"),
            outcome=o.get("outcome", "?"),
        )
        prices[key] = float(o.get("price", 0.0))
    return prices
