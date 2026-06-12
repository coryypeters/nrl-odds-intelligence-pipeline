"""
Detected-event shapes emitted by the Step 3 detectors.

Three event types, one common envelope so the API/WebSocket layer (Step 4) and
the dashboard (Step 5) can treat them uniformly:

  MovementEvent  - a single notable price shift on one book/outcome
  SteamEvent     - several books shortening the same outcome together (sharp money)
  ArbEvent       - a cross-book back-price combination implying < 100% (locked profit)

Each carries enough match context to render a dashboard card without a second
lookup, plus an epoch `detected_at` for ordering and a stable `event_key` used
for de-duplication in the live store.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class MovementEvent:
    kind: str = field(default="movement", init=False)
    sport_key: str = ""
    event_id: str = ""
    home_team: str = ""
    away_team: str = ""
    commence_time: str = ""
    bookmaker: str = ""
    market: str = ""
    outcome: str = ""
    old_price: float = 0.0
    new_price: float = 0.0
    pct_change: float = 0.0
    direction: str = ""
    detected_at: float = field(default_factory=time.time)

    @property
    def event_key(self) -> str:
        return f"movement|{self.event_id}|{self.bookmaker}|{self.outcome}|{self.new_price}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind
        d["event_key"] = self.event_key
        return d


@dataclass
class SteamEvent:
    kind: str = field(default="steam", init=False)
    sport_key: str = ""
    event_id: str = ""
    home_team: str = ""
    away_team: str = ""
    commence_time: str = ""
    outcome: str = ""
    books_moved: list[str] = field(default_factory=list)
    avg_pct_change: float = 0.0
    direction: str = ""
    detected_at: float = field(default_factory=time.time)

    @property
    def event_key(self) -> str:
        books = ",".join(sorted(self.books_moved))
        return f"steam|{self.event_id}|{self.outcome}|{books}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind
        d["event_key"] = self.event_key
        d["n_books"] = len(self.books_moved)
        return d


@dataclass
class ArbLeg:
    bookmaker: str
    outcome: str
    price: float
    stake_pct: float          # fraction of bankroll to put on this leg (0..1)


@dataclass
class ArbEvent:
    kind: str = field(default="arbitrage", init=False)
    sport_key: str = ""
    event_id: str = ""
    home_team: str = ""
    away_team: str = ""
    commence_time: str = ""
    legs: list[ArbLeg] = field(default_factory=list)
    implied_pct: float = 0.0      # sum of 1/price across legs; < 100 means arb
    profit_pct: float = 0.0       # guaranteed return on total stake
    detected_at: float = field(default_factory=time.time)

    @property
    def event_key(self) -> str:
        legs = ",".join(f"{l.bookmaker}:{l.outcome}:{l.price}" for l in sorted(
            self.legs, key=lambda x: x.outcome))
        return f"arb|{self.event_id}|{legs}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind
        d["event_key"] = self.event_key
        return d
