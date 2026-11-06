"""
NCAAM Model settings.

Every number that drives the model lives here (this replaces the old
"Assumptions" sheet). Change a value, save, and run main.py again.
"""

# ---------------------------------------------------------------------------
# Model mode
# ---------------------------------------------------------------------------
# False (recommended): the Enhanced columns use the real adjusted ORtg / DRtg
#   values, the +HCA boost goes to the actual ESPN home team (none on neutral
#   courts), and Confidence uses all three tiers (High / Medium / Low).
# True: reproduces NCAAM Model v5.1.xlsm exactly, including the Enhanced
#   columns being calculated from the offense/defense RANK columns, the
#   "first word of team name appears in the venue" home-court test, and
#   Confidence showing only "High".
LEGACY_EXCEL_MODE = False

# ---------------------------------------------------------------------------
# Efficiency weighting (Assumptions rows 5-6)
# ---------------------------------------------------------------------------
OFFENSE_WEIGHT = 0.40
DEFENSE_WEIGHT = 0.60

# ---------------------------------------------------------------------------
# Home court (Assumptions row 10)
# ---------------------------------------------------------------------------
HOME_COURT_POINTS = 3.0
# Your Assumptions sheet says the boost is "added to ORtg and subtracted from
# DRtg of the home team". The Excel formula only applied it to ORtg.
# True follows the written assumption; ignored in LEGACY_EXCEL_MODE.
HCA_APPLIES_TO_DEFENSE = True

# ---------------------------------------------------------------------------
# Tempo (Assumptions rows 14-15)
# ---------------------------------------------------------------------------
TEMPO_BASELINE = 68.0

# ---------------------------------------------------------------------------
# Confidence tiers on Enhanced Value (Assumptions rows 19-21)
# ---------------------------------------------------------------------------
HIGH_THRESHOLD = 3.0
MEDIUM_THRESHOLD = 1.0

# ---------------------------------------------------------------------------
# "Games to Watch" screen (original columns O:Q)
# A game qualifies when T1 rank + T2 rank < RANK_SUM_LIMIT and
# |rank diff / spread| is >= WATCH_HIGH_RATIO (back the better team)
# or < WATCH_LOW_RATIO (back the worse team).
# ---------------------------------------------------------------------------
RANK_SUM_LIMIT = 350
WATCH_HIGH_RATIO = 22
WATCH_LOW_RATIO = 1

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
# Season is the year the season ENDS (2026-27 season = 2027).
# None = work it out from the date being run.
SEASON = None

TORVIK_URL = "https://barttorvik.com/{season}_team_results.csv"
ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/"
    "mens-college-basketball/scoreboard"
)
# 50 = all Division I games. Without it ESPN only returns featured games.
ESPN_GROUP = "50"

HTTP_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)

# Re-download Barttorvik on every run so the afternoon run picks up any
# overnight/in-day rating updates. True = reuse the morning download.
CACHE_RATINGS_SAME_DAY = False

# ---------------------------------------------------------------------------
# Odds sources
# ---------------------------------------------------------------------------
# The Odds API (multi-book lines). Free key at https://the-odds-api.com
# Paste it here, OR put it in data/odds_api_key.txt, OR set env var ODDS_API_KEY.
ODDS_API_KEY = ""
ODDS_API_REGIONS = "us"
# Each market costs 1 request per call. "spreads,h2h" = 2 per run,
# about 4 per day with two runs (roughly 120 of your 500 free per month).
ODDS_API_MARKETS = "spreads,h2h"
# Optional: limit to specific books, e.g. "draftkings,fanduel,betmgm,williamhill_us"
ODDS_API_BOOKMAKERS = ""

# Which spread the model uses:
#   "consensus" = median line across all books from The Odds API (falls back to ESPN)
#   "espn"      = ESPN's DraftKings line (falls back to consensus)
LINE_SOURCE = "consensus"

# Prediction markets (win probability only; no key needed)
USE_KALSHI = True
USE_POLYMARKET = True
# Leave empty to auto-detect. If auto-detect finds nothing during the season,
# put the series here, e.g. KALSHI_SERIES = ["KXNCAAMBGAME"]
KALSHI_SERIES: list[str] = []
POLYMARKET_SERIES_ID = ""

# ---------------------------------------------------------------------------
# Edge tracking
# ---------------------------------------------------------------------------
# Std. deviation of college game margins vs projection, used to turn the
# projected margin into a win probability.
MARGIN_STDEV = 11.0
# Log a sportsbook Edge pick when |projected margin + line| is at least this.
EDGE_LOG_MIN = 0.0
# Success-rate buckets for Edge picks (points of edge)
EDGE_BUCKETS = [0, 2, 4, 6]
# Log a Market pick when model win % beats market win % by at least this.
MARKET_EDGE_MIN = 0.05
MARKET_EDGE_BUCKETS = [0.05, 0.10, 0.15]

# ---------------------------------------------------------------------------
# Automatic daily runs on your own PC (used by setup_daily_tasks.py).
# On GitHub the run times are in .github/workflows/daily.yml instead.
# ---------------------------------------------------------------------------
# 10:00 grades yesterday and pulls the day's ratings, schedule and odds.
# 17:00 refreshes ratings and odds for games that haven't tipped yet.
DAILY_RUN_TIMES = ["10:00", "17:00"]

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
OPEN_REPORT_WHEN_DONE = False  # True = open the Excel report automatically
# Build docs/index.html, the web dashboard GitHub Pages publishes.
WEB_DASHBOARD = True
