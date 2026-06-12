"""
REST routes.

  GET /api/events        - recent detected events (movement/steam/arb), newest first
  GET /api/events?kind=  - filter by kind: movement | steam | arbitrage
  GET /api/odds          - current best odds per outcome for each live event
  GET /api/health        - liveness + quick Redis check

The dashboard calls /api/events on load to populate history, then switches to
the WebSocket for live updates. /api/odds backs the odds-comparison table.
"""

from __future__ import annotations

import json
import os

import redis
from fastapi import APIRouter, Query

router = APIRouter()

EVENTS_STREAM = "events"
RAW_ODDS_STREAM = "raw_odds"
_redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
_r = redis.from_url(_redis_url, decode_responses=True)


@router.get("/api/health")
def health():
    try:
        _r.ping()
        return {"status": "ok", "redis": "up"}
    except Exception as e:
        return {"status": "degraded", "redis": "down", "error": str(e)}


@router.get("/api/events")
def get_events(
    kind: str | None = Query(default=None, pattern="^(movement|steam|arbitrage)$"),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Recent detected events, newest first, optionally filtered by kind."""
    raw = _r.xrevrange(EVENTS_STREAM, count=limit * 2)  # over-fetch to allow filtering
    events = []
    for _msg_id, fields in raw:
        try:
            ev = json.loads(fields["payload"])
        except (KeyError, json.JSONDecodeError):
            continue
        if kind and ev.get("kind") != kind:
            continue
        events.append(ev)
        if len(events) >= limit:
            break
    return {"count": len(events), "events": events}


@router.get("/api/odds")
def get_odds():
    """
    Best back price per outcome for each event that is still upcoming or in-play.
    Powers the odds-comparison table. Reads the most recent snapshot per event
    and drops events whose kickoff is well in the past (finished games leave the
    Odds API feed, but a stale snapshot can linger in the stream).
    """
    import time
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    def hours_since_kickoff(iso: str):
        if not iso:
            return None
        try:
            ko = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (now - ko).total_seconds() / 3600.0

    # Read a generous slice so no current event is pushed out of the window.
    raw = _r.xrevrange(RAW_ODDS_STREAM, count=2000)
    seen: set[str] = set()
    events = []
    for _msg_id, fields in raw:
        try:
            snap = json.loads(fields["payload"])
        except (KeyError, json.JSONDecodeError):
            continue
        eid = snap.get("event_id")
        if not eid or eid in seen:
            continue
        seen.add(eid)  # first time we hit an event in reverse = its latest snapshot

        # Drop finished games: kickoff more than 3h ago is past full-time.
        hsk = hours_since_kickoff(snap.get("commence_time", ""))
        if hsk is not None and hsk > 3.0:
            continue

        best: dict[str, dict] = {}
        for o in snap.get("outcomes", []):
            if o.get("market", "").endswith("_lay"):
                continue
            name = o.get("outcome")
            price = float(o.get("price", 0))
            if name not in best or price > best[name]["price"]:
                best[name] = {"price": price, "bookmaker": o.get("bookmaker")}
        events.append({
            "event_id": eid,
            "sport_key": snap.get("sport_key"),
            "home_team": snap.get("home_team"),
            "away_team": snap.get("away_team"),
            "commence_time": snap.get("commence_time"),
            "best": best,
        })

    # Sort by kickoff so the next games to start appear first.
    events.sort(key=lambda e: e.get("commence_time") or "")
    return {"count": len(events), "events": events}


# ─────────────────────────────────────────────────────────────────────────────
# Match detail: full book-by-book prices + movement history + market analysis
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/api/match/{event_id}")
def get_match(event_id: str):
    """
    Everything we know about one event, assembled from the raw_odds stream:
      - latest book-by-book prices per outcome (the full market, not just best)
      - best price per outcome + which book offers it
      - implied probabilities and the bookmaker margin (overround)
      - line-movement history per outcome (best price over time)
      - data-grounded market read: favourite, value flags, arb if present

    This is market analysis from odds data only — no form/injury model — so the
    'recommendation' is explicitly tied to signal strength in the prices.
    """
    # Pull this event's snapshots oldest->newest for a movement series.
    raw = _r.xrange(RAW_ODDS_STREAM, count=5000)
    snaps = []
    for _id, fields in raw:
        try:
            s = json.loads(fields["payload"])
        except (KeyError, json.JSONDecodeError):
            continue
        if s.get("event_id") == event_id:
            snaps.append(s)
    if not snaps:
        return {"found": False, "event_id": event_id}

    latest = snaps[-1]
    outcomes = sorted({o["outcome"] for o in latest.get("outcomes", [])
                       if not o.get("market", "").endswith("_lay")})

    # Live/recent score for this event, if the scores poller has stored one.
    score = None
    try:
        raw_score = _r.get(f"score:{event_id}")
        if raw_score:
            sc = json.loads(raw_score)
            scores_list = sc.get("scores") or []
            score = {
                "completed": sc.get("completed", False),
                "last_update": sc.get("last_update"),
                "scores": {s.get("name"): s.get("score") for s in scores_list} if scores_list else {},
            }
    except Exception:
        score = None

    # full book table: {outcome: [{bookmaker, price}], ...}
    book_table: dict[str, list] = {o: [] for o in outcomes}
    best: dict[str, dict] = {}
    for o in latest.get("outcomes", []):
        if o.get("market", "").endswith("_lay"):
            continue
        name, price, book = o.get("outcome"), float(o.get("price", 0)), o.get("bookmaker")
        if name not in book_table:
            continue
        book_table[name].append({"bookmaker": book, "price": price})
        if name not in best or price > best[name]["price"]:
            best[name] = {"price": price, "bookmaker": book}
    for name in book_table:
        book_table[name].sort(key=lambda r: r["price"], reverse=True)

    # implied probability + margin, computed two ways:
    #   - "best line" (sharpest available across books): sum of 1/best can be <100 (=arb)
    #   - "typical book" (median per outcome): the real overround a single book charges
    import statistics
    best_implied = {o: round(100.0 / best[o]["price"], 2) for o in best}
    best_overround = round(sum(best_implied.values()), 2)

    median_price = {o: statistics.median([r["price"] for r in book_table[o]]) for o in outcomes if book_table[o]}
    median_implied = {o: round(100.0 / median_price[o], 2) for o in median_price}
    median_overround = round(sum(median_implied.values()), 2)

    # normalised (vig-removed) probabilities from the typical book — the market's
    # genuine implied chance for each outcome.
    fair = {}
    if median_overround:
        for o in median_implied:
            fair[o] = round(median_implied[o] / median_overround * 100, 1)

    # favourite = lowest fair probability outcome... no: highest probability.
    favourite = max(fair, key=fair.get) if fair else None

    # ── Derived expected-margin model (h2h only, two-way markets) ──────────────
    # We have no handicap lines on the free tier, so we MODEL an expected margin
    # from the win probability. This is a derived analytic, clearly labelled as
    # such — not a bookmaker line.
    #
    # Method: map win probability -> expected points margin via the logit of the
    # favourite's probability, scaled to a realistic NRL spread. NRL margins are
    # roughly logistic; a coefficient of ~9 points per logit unit fits typical
    # favourite prices (e.g. ~67% fav ≈ 6-7 pts, ~80% ≈ 12-13 pts). This is a
    # heuristic for context, NOT a calibrated prediction.
    import math
    margin_model = None
    if favourite and len(fair) == 2 and fair.get(favourite):
        p = min(max(fair[favourite] / 100.0, 0.5001), 0.9899)  # clamp to valid range
        logit = math.log(p / (1 - p))
        exp_margin = round(9.0 * logit, 1)   # expected favourite margin in points
        # confidence band: how decisive the market thinks it is
        if fair[favourite] >= 75:
            band = "Strong favourite"
        elif fair[favourite] >= 62:
            band = "Clear favourite"
        elif fair[favourite] >= 55:
            band = "Slight favourite"
        else:
            band = "Coin-flip"
        margin_model = {
            "favourite": favourite,
            "expected_margin": exp_margin,        # points
            "win_prob": fair[favourite],          # %
            "confidence_band": band,
            "note": "Derived from market win probability, not a bookmaker handicap line.",
        }

    # value flags: a book priced meaningfully above consensus = value on that outcome.
    value_flags = []
    for o in outcomes:
        if not book_table[o]:
            continue
        top = book_table[o][0]
        med = median_price.get(o)
        if med and top["price"] >= med * 1.03:  # 3%+ above median
            edge = round((top["price"] / med - 1) * 100, 1)
            value_flags.append({
                "outcome": o, "bookmaker": top["bookmaker"],
                "price": top["price"], "median": round(med, 2), "edge_pct": edge,
            })

    is_arb = best_overround < 100.0
    arb_profit = round(100.0 / best_overround * 100 - 100, 2) if is_arb else 0.0

    # movement series: best price per outcome at each snapshot over time
    series = []
    for s in snaps:
        row = {"t": s.get("fetched_at")}
        b = {}
        for o in s.get("outcomes", []):
            if o.get("market", "").endswith("_lay"):
                continue
            nm, pr = o.get("outcome"), float(o.get("price", 0))
            if nm not in b or pr > b[nm]:
                b[nm] = pr
        for o in outcomes:
            if o in b:
                row[o] = b[o]
        series.append(row)

    # opening vs current (drift) per outcome, from the series
    drift = {}
    for o in outcomes:
        pts = [(r["t"], r[o]) for r in series if o in r]
        if len(pts) >= 2:
            opening, current = pts[0][1], pts[-1][1]
            drift[o] = {
                "open": opening, "current": current,
                "change_pct": round((current - opening) / opening * 100, 2) if opening else 0.0,
            }

    return {
        "found": True,
        "event_id": event_id,
        "sport_key": latest.get("sport_key"),
        "home_team": latest.get("home_team"),
        "away_team": latest.get("away_team"),
        "commence_time": latest.get("commence_time"),
        "outcomes": outcomes,
        "book_table": book_table,
        "best": best,
        "n_books": len({r["bookmaker"] for o in outcomes for r in book_table[o]}),
        "implied": {
            "best_overround": best_overround,
            "median_overround": median_overround,
            "fair_probabilities": fair,     # vig-removed market probabilities
        },
        "favourite": favourite,
        "margin_model": margin_model,
        "score": score,
        "value_flags": value_flags,
        "arbitrage": {"is_arb": is_arb, "profit_pct": arb_profit},
        "drift": drift,
        "movement_series": series[-40:],    # last 40 points
        "snapshots_seen": len(snaps),
    }
