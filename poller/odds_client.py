"""
Thin wrapper around The Odds API v4.

Responsibilities:
  - fetch odds for a given sport key + regions + markets
  - surface remaining/used quota from response headers (free tier = 500/mo)
  - normalise the response into a flat snapshot shape the diff engine expects

The Odds API returns quota usage in response headers:
  x-requests-remaining, x-requests-used
We log these every call so the poller can back off as the month's budget drains.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("odds_client")

BASE_URL = "https://api.the-odds-api.com/v4"


@dataclass
class OddsOutcome:
    """A single price: e.g. 'Crusaders' @ 1.72 on Sportsbet."""
    bookmaker: str
    market: str          # h2h, spreads, totals
    outcome: str         # team name / Over / Under
    price: float         # decimal odds
    point: float | None = None  # line for spreads/totals; None for h2h


@dataclass
class MatchSnapshot:
    """All current prices for one match at one point in time."""
    sport_key: str
    event_id: str
    home_team: str
    away_team: str
    commence_time: str        # ISO8601 UTC kickoff
    fetched_at: float         # epoch seconds (our clock)
    outcomes: list[OddsOutcome]


class QuotaExhausted(RuntimeError):
    """Raised when the API reports zero remaining requests."""


class OddsAPIClient:
    def __init__(self, api_key: str, timeout: float = 15.0):
        if not api_key:
            raise ValueError("ODDS_API_KEY is required")
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout)
        self.requests_remaining: int | None = None
        self.requests_used: int | None = None

    def close(self) -> None:
        self._client.close()

    def fetch_odds(
        self,
        sport_key: str,
        regions: str,
        markets: str = "h2h",
        odds_format: str = "decimal",
    ) -> list[MatchSnapshot]:
        url = f"{BASE_URL}/sports/{sport_key}/odds"
        params = {
            "apiKey": self._api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": "iso",
        }
        resp = self._client.get(url, params=params)
        self._record_quota(resp)

        if resp.status_code == 422:
            # Usually an unknown/out-of-season sport key.
            log.warning("422 for sport_key=%s (likely out of season or bad key)", sport_key)
            return []
        if resp.status_code == 401:
            raise QuotaExhausted("401 from The Odds API — bad key or quota exhausted")
        resp.raise_for_status()

        fetched_at = time.time()
        return [self._parse_event(ev, sport_key, fetched_at) for ev in resp.json()]

    def fetch_scores(self, sport_key: str, days_from: int = 1) -> list[dict]:
        """
        Fetch live and recent scores for a sport (free-tier endpoint).
        Returns raw score dicts; the poller writes them to a Redis hash keyed by
        event_id so the API can attach live/recent results to a match.
        """
        url = f"{BASE_URL}/sports/{sport_key}/scores"
        params = {"apiKey": self._api_key, "daysFrom": days_from, "dateFormat": "iso"}
        resp = self._client.get(url, params=params)
        self._record_quota(resp)
        if resp.status_code in (404, 422):
            return []
        if resp.status_code == 401:
            raise QuotaExhausted("401 from The Odds API — bad key or quota exhausted")
        resp.raise_for_status()
        return resp.json()

    def _record_quota(self, resp: httpx.Response) -> None:
        remaining = resp.headers.get("x-requests-remaining")
        used = resp.headers.get("x-requests-used")
        if remaining is not None:
            self.requests_remaining = int(float(remaining))
        if used is not None:
            self.requests_used = int(float(used))
        if self.requests_remaining is not None:
            log.info("quota: %s remaining, %s used", self.requests_remaining, self.requests_used)
            if self.requests_remaining <= 0:
                raise QuotaExhausted("x-requests-remaining hit 0")

    @staticmethod
    def _parse_event(ev: dict, sport_key: str, fetched_at: float) -> MatchSnapshot:
        outcomes: list[OddsOutcome] = []
        for bm in ev.get("bookmakers", []):
            book = bm.get("title", bm.get("key", "unknown"))
            for market in bm.get("markets", []):
                mkey = market.get("key", "h2h")
                for o in market.get("outcomes", []):
                    outcomes.append(
                        OddsOutcome(
                            bookmaker=book,
                            market=mkey,
                            outcome=o.get("name", "?"),
                            price=float(o.get("price", 0.0)),
                            point=(float(o["point"]) if "point" in o else None),
                        )
                    )
        return MatchSnapshot(
            sport_key=sport_key,
            event_id=ev.get("id", ""),
            home_team=ev.get("home_team", ""),
            away_team=ev.get("away_team", ""),
            commence_time=ev.get("commence_time", ""),
            fetched_at=fetched_at,
            outcomes=outcomes,
        )
