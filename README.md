# Real-Time Odds Intelligence Pipeline

An event-driven streaming pipeline that polls live sports betting odds, diffs
successive snapshots to detect **line movement**, **steam moves**, and
**arbitrage windows**, and pushes alerts to a live dashboard over WebSocket.

> **Status:** Step 1 complete — the ingestion layer (poller → Redis Streams).
> Remaining steps scoped below.

## Architecture

```
The Odds API
     │
     ▼
Poller (APScheduler, match-window-aware cadence)   ◄── Step 1 (done)
     │  raw odds snapshots
     ▼
Redis Streams  ──── raw_odds stream
     │
     ▼
Stream Processor (consumer group)                  ◄── Step 2
     ├── diff engine        (snapshot deltas)
     ├── movement / steam   (line shift + multi-book consensus)
     └── arb scanner        (cross-book +EV windows)
     │
     ▼
Redis (live event store)
     │
     ▼
FastAPI + WebSocket                                ◄── Step 4
     │
     ▼
React dashboard                                    ◄── Step 5
```

## Coverage

Odds come from **The Odds API** (free tier, 500 requests/month). Sports are
limited to what the API actually covers with real multi-bookmaker odds:

| Group  | League              | Sport key                         |
| ------ | ------------------- | --------------------------------- |
| Rugby  | NRL                 | `rugbyleague_nrl`                 |
| Rugby  | NRL State of Origin | `rugbyleague_nrl_state_of_origin` |
| Rugby  | Six Nations         | `rugbyunion_six_nations`          |
| Soccer | EPL                 | `soccer_epl`                      |
| Soccer | Champions League    | `soccer_uefa_champs_league`       |

> Super Rugby Pacific is **not** offered by The Odds API and the free
> rugby-specific providers don't expose multi-book odds, so it's out of scope
> for the odds-diff pipeline.

## Quota strategy

The free tier is 500 requests/month, so the poller polls at a cadence that
adapts to each sport's match windows (learned from event kickoff times, not a
hardcoded calendar):

| State       | Cadence | When                              |
| ----------- | ------- | --------------------------------- |
| `idle`      | 10 min  | no matches near                   |
| `pre_match` | 1 min   | kickoff within 2 hours            |
| `in_play`   | 30 sec  | match in progress                 |

When the API reports zero remaining requests, the poller backs every sport off
to hourly so a runaway loop can't blow a paid plan.

## Run it (Step 1)

```bash
cp .env.example .env       # add your ODDS_API_KEY
docker compose up --build
```

Watch snapshots land in the stream:

```bash
docker compose exec redis redis-cli XRANGE raw_odds - + COUNT 5
```


## Access (full stack)

After `docker compose up --build`, five services run: redis, poller, processor,
api, frontend.

| Surface            | URL                              |
| ------------------ | -------------------------------- |
| Dashboard          | http://localhost:5173            |
| API — events       | http://localhost:8000/api/events |
| API — odds         | http://localhost:8000/api/odds   |
| API — health       | http://localhost:8000/api/health |
| API — match detail | http://localhost:8000/api/match/{event_id} |

The match detail page adds a derived expected-margin model (computed from market
win probability — labelled as a model, not a bookmaker line) and live/recent
scores from The Odds API's free scores endpoint.

The dashboard loads event history on open, then streams new signals live over
WebSocket. Pick a match in the odds panel to chart its line movement.


## Team imagery

Club logos are trademarked, so this project does not bundle or hotlink them.
Each team instead gets a **generated crest** — its real club colours plus a
monogram — produced deterministically in `frontend/src/teams.js`. This needs no
network, carries no copyright risk, and updates automatically for any team in
the feed. The hero uses an Unsplash-licensed stadium photo (free for commercial
use, no attribution required) with a CSS gradient fallback.

## Project layout

```
odds-intelligence-pipeline/
├── poller/                    # Step 1 — ingestion (done)
│   ├── sports_config.py       # verified sport keys + poll cadences
│   ├── odds_client.py         # The Odds API wrapper + quota tracking
│   ├── stream_writer.py       # Redis Streams producer
│   ├── scheduler.py           # cadence loop, the poller entrypoint
│   ├── requirements.txt
│   └── Dockerfile
├── processor/                 # Step 2/3 — diff + detection (next)
├── api/                       # Step 4 — FastAPI + WebSocket
├── frontend/                  # Step 5 — React dashboard
├── docker-compose.yml
└── .env.example
```

## Roadmap

- [x] **Step 1** — poller + Redis Streams ingestion
- [x] **Step 2** — diff engine (snapshot deltas per outcome per book)
- [x] **Step 3** — movement/steam detector + arbitrage scanner
- [x] **Step 4** — FastAPI WebSocket push + event history endpoints
- [x] **Step 5** — React dashboard (event feed, odds table, movement chart)
- [ ] **Step 6** — Railway deploy
