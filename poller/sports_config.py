"""
Sport definitions and match-window-aware polling schedules.

All sport keys below are verified against The Odds API's live sports list
(/v4/sports). Super Rugby is intentionally absent — The Odds API does not
cover it, so it cannot feed the odds-diff pipeline.

The Odds API free tier = 500 requests/month, so polling cadence is tiered:
  - idle     : no live/upcoming matches      -> poll slowly (conserve quota)
  - pre_match: kickoff within PRE_MATCH_HRS  -> poll faster (lines firming up)
  - in_play  : match in progress             -> poll fastest (steam/arb windows)
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PollCadence:
    idle_seconds: int = 600        # 10 min when nothing is on
    pre_match_seconds: int = 60    # 1 min in the 2h before kickoff
    in_play_seconds: int = 30      # 30s while live


@dataclass(frozen=True)
class Sport:
    key: str                       # The Odds API sport key (verified)
    label: str                     # human-friendly name for the dashboard
    group: str                     # dashboard grouping: Rugby / Soccer
    regions: str                   # comma-sep: 'au' covers NZ/AU books, 'uk' EPL/UCL depth
    markets: str = "h2h"           # h2h = moneyline; add 'spreads,totals' later
    cadence: PollCadence = field(default_factory=PollCadence)


# Regions note:
#   'au' returns Sportsbet, TAB, Ladbrokes, Neds, PointsBet (covers NZ punters)
#   'uk' returns Bet365, William Hill, Betfair, Paddy Power (best soccer depth)
#
# Keys verified against https://the-odds-api.com/sports-odds-data/sports-apis.html
SPORTS: dict[str, Sport] = {
    "nrl": Sport(
        key="rugbyleague_nrl",
        label="NRL",
        group="Rugby",
        regions="au",
    ),
    "nrl_origin": Sport(
        key="rugbyleague_nrl_state_of_origin",
        label="NRL State of Origin",
        group="Rugby",
        regions="au",
    ),
    "six_nations": Sport(
        key="rugbyunion_six_nations",
        label="Six Nations",
        group="Rugby",
        regions="uk,au",
    ),
    "epl": Sport(
        key="soccer_epl",
        label="EPL",
        group="Soccer",
        regions="uk,au",
    ),
    "ucl": Sport(
        key="soccer_uefa_champs_league",
        label="Champions League",
        group="Soccer",
        regions="uk,au",
    ),
}

PRE_MATCH_HRS = 2  # how long before kickoff we switch idle -> pre_match
