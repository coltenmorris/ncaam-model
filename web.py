"""Static web dashboard (docs/index.html) for GitHub Pages.

The page is one self-contained HTML file: data is embedded as JSON and drawn
with a little plain JavaScript, so it works on GitHub Pages and on a phone.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

import pandas as pd

import config

TODAY_COLS = [
    ("Time", "Time"), ("T1 Team", "Away"), ("T2 Team", "Home"), ("Line", "Line"),
    ("Books", "Books"), ("Best T1", "Best away"), ("Best T2", "Best home"),
    ("Proj T1 Margin", "Proj away margin"), ("Edge Pick", "Edge pick"), ("Edge Size", "Edge"),
    ("Model T1 Win%", "Model away win"), ("Market T1 Win%", "Market away win"),
    ("Games to Watch", "Watch"), ("Confidence", "Conf."), ("Model Pick", "Model pick"),
]
HIST_COLS = [
    ("date", "Date"), ("pick_type", "Type"), ("t1", "Away"), ("t2", "Home"), ("pick_team", "Pick"),
    ("pick_line", "Line"), ("edge", "Edge"), ("confidence", "Conf."), ("t1_score", "Away pts"),
    ("t2_score", "Home pts"), ("result", "Result"),
]


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return str(v)
    if hasattr(v, "item"):
        try:
            return _clean(v.item())
        except Exception:
            return str(v)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _sanitize(x):
    if isinstance(x, dict):
        return {k: _sanitize(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_sanitize(v) for v in x]
    if isinstance(x, (str, bool)) or x is None:
        return x
    return _clean(x)


def _records(df: pd.DataFrame, cols) -> list[list]:
    if df is None or df.empty:
        return []
    have = [c for c, _ in cols]
    out = []
    for _, r in df.iterrows():
        out.append([_clean(r.get(c)) for c in have])
    return out


def _payout(american):
    """Decimal payout for an American price (higher = better for the bettor)."""
    try:
        a = float(american)
    except (TypeError, ValueError):
        return None
    if a == 0 or a != a:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def _better_spread(pt, px, ref_pt, ref_px) -> bool:
    if pt is None or ref_pt is None:
        return False
    if pt > ref_pt + 1e-9:
        return True
    if abs(pt - ref_pt) < 1e-9:
        p, r = _payout(px), _payout(ref_px)
        return p is not None and r is not None and p > r + 1e-9
    return False


def _better_ml(ml, ref_ml) -> bool:
    p, r = _payout(ml), _payout(ref_ml)
    return p is not None and r is not None and p > r + 1e-9


def odds_compare(games: list[dict], rows: list[dict]) -> list[dict]:
    """One entry per game: the DraftKings line (from ESPN) and every other book,
    flagging any number that is better than DraftKings for that side."""
    from espn import home_line
    names = {r["game_id"]: (r.get("t1") or r.get("espn_t1"), r.get("t2") or r.get("espn_t2")) for r in rows}
    out = []
    for g in sorted(games, key=lambda x: str(x.get("start") or "")):
        books = dict(g.get("books") or {})
        dk_api = next((books.pop(k) for k in list(books) if k.lower().startswith("draftkings")), None)
        h = home_line(g)
        if h is not None:
            dk = {"source": "DraftKings (ESPN)", "home_pt": h, "away_pt": -h,
                  "home_px": g.get("spread_price_home"), "away_px": g.get("spread_price_away"),
                  "home_ml": g.get("ml_home"), "away_ml": g.get("ml_away")}
            if dk_api:  # fill any prices ESPN didn't include
                for k_dk, k_api in (("home_px", "home_price"), ("away_px", "away_price"),
                                    ("home_ml", "ml_home"), ("away_ml", "ml_away")):
                    if dk[k_dk] is None:
                        dk[k_dk] = dk_api.get(k_api)
        elif dk_api and dk_api.get("home_point") is not None:
            dk = {"source": "DraftKings (The Odds API)", "home_pt": dk_api.get("home_point"),
                  "away_pt": dk_api.get("away_point"), "home_px": dk_api.get("home_price"),
                  "away_px": dk_api.get("away_price"), "home_ml": dk_api.get("ml_home"),
                  "away_ml": dk_api.get("ml_away")}
        else:
            dk = None
        if dk is None and not books:
            continue
        others, n_better = [], 0
        for name, b in sorted(books.items()):
            row = {"book": name, "away_pt": b.get("away_point"), "home_pt": b.get("home_point"),
                   "away_px": b.get("away_price"), "home_px": b.get("home_price"),
                   "away_ml": b.get("ml_away"), "home_ml": b.get("ml_home")}
            better = {}
            if dk:
                better = {
                    "away_sp": _better_spread(row["away_pt"], row["away_px"], dk["away_pt"], dk["away_px"]),
                    "home_sp": _better_spread(row["home_pt"], row["home_px"], dk["home_pt"], dk["home_px"]),
                    "away_ml": _better_ml(row["away_ml"], dk["away_ml"]),
                    "home_ml": _better_ml(row["home_ml"], dk["home_ml"]),
                }
            row["better"] = better
            if any(better.values()):
                n_better += 1
            others.append(row)
        t1, t2 = names.get(g["game_id"], (g["away"]["location"], g["home"]["location"]))
        out.append({"time": g.get("time", ""), "away": t1, "home": t2,
                    "awayAbbr": g["away"]["abbr"], "homeAbbr": g["home"]["abbr"],
                    "dk": dk, "books": others, "better": n_better})
    return out


def power_table(ratings: pd.DataFrame, data_dir: Path | None) -> pd.DataFrame:
    df = ratings.copy()
    df = df.sort_values("net_rtg", ascending=False).reset_index(drop=True)
    df["Rk"] = range(1, len(df) + 1)
    change = [None] * len(df)
    if data_dir is not None:
        files = sorted(Path(data_dir).glob("ratings_*_*.csv"))
        today = date.today().isoformat()
        past = [f for f in files if f.stem.split("_")[-1] < today]
        week_ago = (pd.Timestamp(today) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        pick = [f for f in past if f.stem.split("_")[-1] <= week_ago]
        ref = pick[-1] if pick else (past[0] if past else None)
        if ref is not None:
            try:
                old = pd.read_csv(ref).sort_values("net_rtg", ascending=False).reset_index(drop=True)
                old_rk = {t: i + 1 for i, t in enumerate(old["team"])}
                change = [old_rk[t] - r if t in old_rk else None for t, r in zip(df["team"], df["Rk"])]
            except Exception:
                pass
    df["Change"] = change
    out = pd.DataFrame({
        "Rk": df["Rk"], "Team": df["team"], "Conf": df["conf"], "Record": df["record"],
        "Net": df["net_rtg"], "Adj O": df["adj_o"], "O Rk": df["adj_o_rank"],
        "Adj D": df["adj_d"], "D Rk": df["adj_d_rank"], "Tempo": df["adj_t"], "Tempo Rk": df["adj_t_rank"],
        "Change": df["Change"],
    })
    return out


def tips() -> dict:
    line_src = ("the median line across all sportsbooks from The Odds API (falls back to DraftKings via ESPN)"
                if config.LINE_SOURCE == "consensus" else "DraftKings via ESPN (falls back to the multi-book consensus)")
    hca = config.HOME_COURT_POINTS
    return {
        "today": {
            "Time": "Scheduled tip-off, Eastern time.",
            "Away": "Away team (T1 in the original spreadsheet). Win % and margin columns are from this team's side.",
            "Home": "Home team (T2). On a neutral court no home-court points are applied.",
            "Line": f"The spread the model compares against: {line_src}.",
            "Books": "How many sportsbooks posted a spread for this game (The Odds API).",
            "Best away": "The most points available on the away team at any single book. Higher is better for an away bet.",
            "Best home": "The most points available on the home team at any single book. Higher is better for a home bet.",
            "Proj away margin": f"Points the model expects the away team to win (+) or lose (-) by. (Away net rating - Home net rating) x average tempo / 100, minus {hca:g} for home court. Net rating = adjusted offense - adjusted defense, per 100 possessions.",
            "Edge pick": "The side the model likes against the spread, at the line shown. It is whichever side the Edge points to.",
            "Edge": "How many points the model disagrees with the line. |Proj away margin + away line|. Example: model Arizona by 34.3, line Arizona -31, edge 3.3 on Arizona. Yellow = 2+, green = 4+.",
            "Model away win": f"Model's chance the away team wins outright (spread ignored). Normal distribution of the projected margin with a standard deviation of {config.MARGIN_STDEV:g} points.",
            "Market away win": "The market's chance the away team wins outright: average of Kalshi and Polymarket prices, or the sportsbooks' moneylines with the bookmaker's cut removed if neither lists the game.",
            "Watch": f"Original 'Games to Watch' screen. YES when the two teams' ranks add to under {config.RANK_SUM_LIMIT} and |rank gap / spread| is {config.WATCH_HIGH_RATIO}+ (backs the better team) or under {config.WATCH_LOW_RATIO} (backs the worse team).",
            "Conf.": f"Enhanced Value tier. Wtd Eff = {config.OFFENSE_WEIGHT:g} x offensive gap + {config.DEFENSE_WEIGHT:g} x defensive gap (home team gets {hca:g} pts). Enhanced Value = |Wtd Eff / spread| x (avg tempo / {config.TEMPO_BASELINE:g}). High {config.HIGH_THRESHOLD:g}+, Medium {config.MEDIUM_THRESHOLD:g} to {config.HIGH_THRESHOLD:g}, Low under {config.MEDIUM_THRESHOLD:g}. Measures the efficiency gap relative to the spread, not cover likelihood.",
            "Model pick": "The team with the better weighted efficiency (Wtd Eff). It always backs the stronger team and does not check whether it is stronger by more than the line. Use Edge for that.",
        },
        "power": {
            "Rk": "Rank by net rating (adjusted offense minus adjusted defense).",
            "Team": "Team name as used by the ratings source.",
            "Conf": "Conference.",
            "Record": "Season win-loss record.",
            "Net": "Adjusted offense minus adjusted defense: points better than an average Division I team per 100 possessions.",
            "Adj O": "Points scored per 100 possessions, adjusted for opponent strength and venue. Higher is better.",
            "O Rk": "National rank in adjusted offense.",
            "Adj D": "Points allowed per 100 possessions, adjusted for opponent strength and venue. Lower is better.",
            "D Rk": "National rank in adjusted defense (1 = best).",
            "Tempo": "Possessions per 40 minutes. Higher = faster pace.",
            "Tempo Rk": "Rank in tempo (1 = fastest).",
            "Change": "Places moved in the rankings over about the last 7 days. Green up, red down.",
        },
    }


def build_payload(day: date, results: pd.DataFrame, record: pd.DataFrame, trend: pd.DataFrame,
                  history: pd.DataFrame, games: list[dict], rows: list[dict], ratings: pd.DataFrame,
                  ratings_source: str, data_dir: Path | None, notes: list[str]) -> dict:
    today = pd.DataFrame()
    if not results.empty and "Edge Size" in results:
        today = results[results["Line"].fillna("") != ""].sort_values("Edge Size", ascending=False, na_position="last")
    hist = history.copy()
    if not hist.empty:
        hist = hist.sort_values(["date", "start"], ascending=[False, True], na_position="last").head(3000)
    power = power_table(ratings, data_dir) if ratings is not None and not ratings.empty else pd.DataFrame()
    return {
        "day": day.strftime("%A, %B %d, %Y").replace(" 0", " "),
        "updated": datetime.now().strftime("%b %d, %Y %I:%M %p ET").replace(" 0", " "),
        "mode": "Legacy Excel" if config.LEGACY_EXCEL_MODE else "Standard",
        "edgeBuckets": list(config.EDGE_BUCKETS),
        "tips": tips(),
        "today": {"cols": [h for _, h in TODAY_COLS], "rows": _records(today, TODAY_COLS)},
        "record": {"cols": list(record.columns), "rows": _records(record, [(c, c) for c in record.columns])},
        "trend": {"cols": list(trend.columns), "rows": _records(trend, [(c, c) for c in trend.columns])},
        "history": {"cols": [h for _, h in HIST_COLS], "rows": _records(hist, HIST_COLS)},
        "odds": _sanitize(odds_compare(games, rows)),
        "power": {"cols": list(power.columns), "rows": _records(power, [(c, c) for c in power.columns]),
                  "source": ratings_source},
        "notes": list(notes),
        "games": int(len(results)) if not results.empty else 0,
    }


def write_site(docs: Path, payload: dict) -> Path:
    docs.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, default=str).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data)
    path = docs / "index.html"
    path.write_text(html, encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NCAAM Model</title>
<meta name="robots" content="noindex">
<style>
:root{
  color-scheme:light;
  --bg:#f6f6f4; --surface:#fcfcfb; --surface-2:#f0efeb; --border:#e2e1dc;
  --text:#0b0b0b; --text-2:#52514e; --muted:#7a7974;
  --accent:#2a78d6; --series-1:#2a78d6; --grid:#e6e5e0;
  --good:#0f7b3d; --good-bg:#e3f4e9; --bad:#b42318; --bad-bg:#fbe9e7;
  --warn-bg:#fff4d6; --chip:#eceae4;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    color-scheme:dark;
    --bg:#121211; --surface:#1a1a19; --surface-2:#232321; --border:#33332f;
    --text:#f0efec; --text-2:#c3c2b7; --muted:#8f8e86;
    --accent:#3987e5; --series-1:#3987e5; --grid:#2c2c29;
    --good:#5cc98a; --good-bg:#16301f; --bad:#f08b80; --bad-bg:#3a1d1a;
    --warn-bg:#3a3214; --chip:#2a2a27;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#121211; --surface:#1a1a19; --surface-2:#232321; --border:#33332f;
  --text:#f0efec; --text-2:#c3c2b7; --muted:#8f8e86;
  --accent:#3987e5; --series-1:#3987e5; --grid:#2c2c29;
  --good:#5cc98a; --good-bg:#16301f; --bad:#f08b80; --bad-bg:#3a1d1a;
  --warn-bg:#3a3214; --chip:#2a2a27;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between}
h1{font-size:22px;margin:0}
.sub{color:var(--text-2);font-size:13px}
nav{display:flex;gap:4px;margin:18px 0 14px;overflow-x:auto;border-bottom:1px solid var(--border)}
nav button{background:none;border:0;border-bottom:2px solid transparent;color:var(--text-2);font:inherit;font-weight:600;padding:10px 12px;cursor:pointer;white-space:nowrap}
nav button[aria-selected="true"]{color:var(--text);border-bottom-color:var(--accent)}
section[hidden]{display:none}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.tile .k{color:var(--text-2);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.tile .v{font-size:24px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.tile .s{color:var(--muted);font-size:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 10px}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
select,input[type=search]{background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font:inherit;font-size:14px}
input[type=search]{min-width:0;flex:1 1 180px}
.tbl{overflow-x:auto;border:1px solid var(--border);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--border)}
th{position:sticky;top:0;background:var(--surface-2);color:var(--text-2);font-weight:600;cursor:pointer;user-select:none}
td.n,th.n{text-align:right}
tbody tr:hover{background:var(--surface-2)}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;background:var(--chip)}
.W{background:var(--good-bg);color:var(--good)} .L{background:var(--bad-bg);color:var(--bad)}
.hi{background:var(--good-bg);color:var(--good)} .md{background:var(--warn-bg)}
.indent{padding-left:22px;color:var(--text-2)}
.chart{position:relative}
.chart svg{display:block;width:100%;height:auto}
.tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 9px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.15);display:none;white-space:nowrap}
.empty{color:var(--muted);padding:18px 4px}
footer{color:var(--muted);font-size:12px;margin-top:22px}
footer ul{margin:6px 0 0;padding-left:18px}
a{color:var(--accent)}
.info{background:none;border:0;padding:0 0 0 4px;margin:0;color:var(--muted);font:inherit;font-size:12px;cursor:help;line-height:1;vertical-align:baseline}
.info:hover,.info:focus-visible{color:var(--accent);outline:none}
#hint{position:fixed;z-index:50;max-width:300px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px 10px;font-size:12.5px;line-height:1.45;font-weight:400;text-transform:none;letter-spacing:0;white-space:normal;box-shadow:0 6px 18px rgba(0,0,0,.18);display:none}
#hint b{display:block;margin-bottom:2px}
.odds td.sp{min-width:96px}
.odds tr.game{cursor:pointer}
.odds tr.game td:first-child{width:28px;color:var(--text-2)}
.odds tr.book td{background:var(--surface-2);font-size:12.5px}
.odds tr.book td.bk{padding-left:28px;color:var(--text-2)}
.odds .px{color:var(--muted);font-size:11.5px;margin-left:4px}
.better{background:var(--good-bg)!important;color:var(--good);font-weight:700}
.better::before{content:"\25B2 ";font-size:9px}
.dkcell{font-weight:600}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;font-size:12.5px;color:var(--text-2);margin:2px 0 10px}
.legend .sw{display:inline-block;padding:0 6px;border-radius:4px}
.btn{background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 12px;font:inherit;font-size:13px;cursor:pointer}
.up{color:var(--good);font-weight:600}.down{color:var(--bad);font-weight:600}
.theme{background:none;border:1px solid var(--border);color:var(--text-2);border-radius:8px;padding:4px 10px;font:inherit;font-size:12px;cursor:pointer}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div><h1>NCAAM Model</h1><div class="sub" id="day"></div></div>
    <div class="sub"><span id="updated"></span> &nbsp;<button class="theme" id="theme">Theme</button></div>
  </header>
  <nav role="tablist">
    <button role="tab" aria-selected="true" data-tab="today">Today</button>
    <button role="tab" aria-selected="false" data-tab="rate">Success Rate</button>
    <button role="tab" aria-selected="false" data-tab="history">History</button>
    <button role="tab" aria-selected="false" data-tab="books">Odds by Book</button>
    <button role="tab" aria-selected="false" data-tab="power">Power Rankings</button>
  </nav>

  <section id="today">
    <div class="tiles" id="todayTiles"></div>
    <div class="controls">
      <label class="sub" for="edgeMin">Show edges of at least</label>
      <select id="edgeMin"></select>
      <input type="search" id="todaySearch" placeholder="Search team">
    </div>
    <div class="tbl" id="todayTbl"></div>
    <p class="sub">Away = T1, Home = T2. Edge = projected margin vs the line (points). Win % columns are for the away team.</p>
  </section>

  <section id="rate" hidden>
    <div class="tiles" id="rateTiles"></div>
    <div class="card"><h2>Cumulative success rate, sportsbook edge picks</h2>
      <div class="chart" id="chart"></div>
      <p class="sub">Dashed line = 52.4%, break-even against the spread at -110.</p>
    </div>
    <div class="card"><h2>Record by pick type</h2><div class="tbl" id="recordTbl"></div></div>
    <div class="card"><h2>Edge picks by day</h2><div class="tbl" id="trendTbl"></div></div>
  </section>

  <section id="history" hidden>
    <div class="controls">
      <select id="histType"><option value="">All pick types</option><option>Edge</option><option>Market</option><option>Watch</option><option>Model</option></select>
      <select id="histRes"><option value="">All results</option><option>W</option><option>L</option><option>P</option><option value="pending">Pending</option></select>
      <input type="search" id="histSearch" placeholder="Search team or date">
    </div>
    <div class="tbl" id="histTbl"></div>
  </section>

  <section id="books" hidden>
    <div class="controls">
      <input type="search" id="bookSearch" placeholder="Search team">
      <label class="sub"><input type="checkbox" id="betterOnly"> Only games with a better number than DraftKings</label>
      <button class="btn" id="expandAll" type="button">Expand all</button>
    </div>
    <div class="legend"><span>DraftKings (from the ESPN schedule) is the standard line. Click a game to see every book.</span>
      <span><span class="sw better">better</span> = more points, better price, or a better moneyline than DraftKings for that side</span></div>
    <div class="tbl" id="bookTbl"></div>
  </section>

  <section id="power" hidden>
    <div class="controls">
      <select id="powerConf"><option value="">All conferences</option></select>
      <input type="search" id="powerSearch" placeholder="Search team">
    </div>
    <p class="sub" id="powerSrc"></p>
    <div class="tbl" id="powerTbl"></div>
  </section>
  <div id="hint" role="tooltip"></div>

  <footer>
    <div><a href="NCAAM_Dashboard.xlsx">Download the Excel dashboard</a> &middot; <a href="pick_history.csv">Pick history (CSV)</a></div>
    <div id="mode"></div>
    <ul id="notes"></ul>
  </footer>
</div>

<script id="payload" type="application/json">__DATA__</script>
<script>
(function(){
const D = JSON.parse(document.getElementById('payload').textContent);
const $ = id => document.getElementById(id);
const el = (tag, props, kids) => { const e = document.createElement(tag); if (props) Object.assign(e, props); (kids||[]).forEach(k => e.append(k)); return e; };
const isNum = v => typeof v === 'number' && isFinite(v);
const pct = v => isNum(v) ? (v*100).toFixed(1) + '%' : '';
const sgn = v => isNum(v) ? (v > 0 ? '+' : '') + (Math.round(v*10)/10).toFixed(1) : '';

// theme toggle
const root = document.documentElement;
try { const t = localStorage.getItem('theme'); if (t) root.dataset.theme = t; } catch(e) {}
$('theme').onclick = () => {
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('theme', root.dataset.theme); } catch(e) {}
  drawChart();
};

$('day').textContent = D.day;
$('updated').textContent = 'Updated ' + D.updated;
$('mode').textContent = 'Model mode: ' + D.mode;
D.notes.forEach(n => $('notes').append(el('li', {textContent: n})));

// tabs
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.setAttribute('aria-selected', x === b));
  document.querySelectorAll('section').forEach(s => s.hidden = s.id !== b.dataset.tab);
  if (b.dataset.tab === 'rate') drawChart();
  try { localStorage.setItem('tab', b.dataset.tab); } catch(e) {}
});
try { const t = localStorage.getItem('tab'); if (t) { const b = document.querySelector('nav button[data-tab="'+t+'"]'); if (b) b.click(); } } catch(e) {}

// generic sortable table
// ---------- info tooltips
const hint = $('hint');
let pinned = null;
function showHint(btn) {
  hint.replaceChildren(el('b', {textContent: btn.dataset.label}), document.createTextNode(btn.dataset.tip));
  hint.style.display = 'block';
  const r = btn.getBoundingClientRect(), w = hint.offsetWidth, h = hint.offsetHeight;
  let left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8);
  let top = r.bottom + 8; if (top + h > innerHeight - 8) top = r.top - h - 8;
  hint.style.left = left + 'px'; hint.style.top = top + 'px';
}
function hideHint() { hint.style.display = 'none'; pinned = null; }
function infoBtn(label, tip) {
  const b = el('button', {type: 'button', className: 'info', textContent: '\u24D8'});
  b.setAttribute('aria-label', 'About ' + label); b.dataset.label = label; b.dataset.tip = tip;
  b.addEventListener('mouseenter', () => showHint(b));
  b.addEventListener('mouseleave', () => { if (pinned !== b) hideHint(); });
  b.addEventListener('focus', () => showHint(b));
  b.addEventListener('blur', hideHint);
  b.addEventListener('click', ev => { ev.stopPropagation(); if (pinned === b) hideHint(); else { showHint(b); pinned = b; } });
  return b;
}
document.addEventListener('click', () => { if (pinned) hideHint(); });
addEventListener('scroll', () => { if (hint.style.display === 'block' && !pinned) hideHint(); }, true);
addEventListener('keydown', ev => { if (ev.key === 'Escape') hideHint(); });

function table(host, cols, rows, fmt, tipMap) {
  host.replaceChildren();
  if (!rows.length) { host.append(el('div', {className: 'empty', textContent: 'Nothing to show yet.'})); return; }
  let sortI = -1, dir = 1;
  const numCol = cols.map((_, i) => rows.some(r => isNum(r[i])) && rows.every(r => r[i] == null || isNum(r[i])));
  const t = el('table'), thead = el('thead'), tb = el('tbody'), hr = el('tr');
  cols.forEach((c, i) => {
    const th = el('th', {textContent: c, className: numCol[i] ? 'n' : ''});
    if (tipMap && tipMap[c]) th.append(infoBtn(c, tipMap[c]));
    th.onclick = () => { dir = sortI === i ? -dir : (numCol[i] ? -1 : 1); sortI = i; body(); };
    hr.append(th);
  });
  thead.append(hr); t.append(thead, tb); host.append(t);
  function body() {
    const rs = rows.slice();
    if (sortI >= 0) rs.sort((a, b) => {
      const x = a[sortI], y = b[sortI];
      if (x == null) return 1; if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * dir;
    });
    tb.replaceChildren(...rs.map(r => {
      const tr = el('tr');
      r.forEach((v, i) => {
        const td = el('td', {className: numCol[i] ? 'n' : ''});
        const out = fmt ? fmt(cols[i], v, r) : null;
        if (out instanceof Node) td.append(out); else td.textContent = out != null ? out : (v == null ? '' : String(v));
        tr.append(td);
      });
      return tr;
    }));
  }
  body();
}
const chip = (text, cls) => el('span', {className: 'chip ' + (cls || ''), textContent: text});

// ---------- Today
const T = D.today, ti = name => T.cols.indexOf(name);
const buckets = D.edgeBuckets.length ? D.edgeBuckets : [0, 2, 4, 6];
buckets.forEach(b => $('edgeMin').append(el('option', {value: b, textContent: b === 0 ? 'Any edge' : b + '+ pts'})));
if (buckets.length > 1) $('edgeMin').value = buckets[1];
const strong = T.rows.filter(r => isNum(r[ti('Edge')]) && r[ti('Edge')] >= (buckets[1] || 2)).length;
const big = T.rows.filter(r => isNum(r[ti('Edge')]) && r[ti('Edge')] >= (buckets[2] || 4)).length;
const watch = T.rows.filter(r => r[ti('Watch')] === 'YES').length;
[['Games', D.games, 'on the ESPN slate'], ['With a line', T.rows.length, 'priced by books'],
 ['Edges ' + (buckets[1] || 2) + '+ pts', strong, (big) + ' at ' + (buckets[2] || 4) + '+ pts'],
 ['Games to Watch', watch, 'original screen']].forEach(([k, v, s]) =>
  $('todayTiles').append(el('div', {className: 'tile'}, [el('div', {className: 'k', textContent: k}), el('div', {className: 'v', textContent: v}), el('div', {className: 's', textContent: s})])));
function fmtToday(c, v) {
  if (v == null) return '';
  if (c === 'Edge') return chip(v.toFixed(1), v >= (buckets[2] || 4) ? 'hi' : v >= (buckets[1] || 2) ? 'md' : '');
  if (c === 'Conf.') return v ? chip(v, v === 'High' ? 'hi' : v === 'Medium' ? 'md' : '') : '';
  if (c === 'Watch') return v === 'YES' ? chip('YES', 'md') : '';
  if (c.indexOf('win') >= 0) return pct(v);
  if (c.indexOf('margin') >= 0 || c.indexOf('Best') === 0) return sgn(v);
  return null;
}
function drawToday() {
  const min = +$('edgeMin').value, q = $('todaySearch').value.trim().toLowerCase();
  const rows = T.rows.filter(r => (min === 0 || (isNum(r[ti('Edge')]) && r[ti('Edge')] >= min)) &&
    (!q || (String(r[ti('Away')]) + ' ' + String(r[ti('Home')])).toLowerCase().includes(q)));
  table($('todayTbl'), T.cols, rows, fmtToday, (D.tips || {}).today);
}
$('edgeMin').onchange = drawToday; $('todaySearch').oninput = drawToday; drawToday();

// ---------- Success rate
const R = D.record, ri = n => R.cols.indexOf(n);
function recRow(label) { return R.rows.find(r => String(r[0]).trim() === label); }
const e = recRow('Sportsbook Edge (all)') || [], m = recRow('Market Edge (all, straight up)') || [];
const tile = (k, v, s) => $('rateTiles').append(el('div', {className: 'tile'}, [el('div', {className: 'k', textContent: k}), el('div', {className: 'v', textContent: v}), el('div', {className: 's', textContent: s})]));
tile('Edge record', e.length ? e[ri('W')] + '-' + e[ri('L')] + '-' + e[ri('P')] : '0-0-0', 'W-L-P against the spread');
tile('Edge success', pct(e[ri('Success Rate')]) || 'n/a', 'break-even 52.4%');
tile('Edge units', isNum(e[ri('Units')]) ? (e[ri('Units')] > 0 ? '+' : '') + e[ri('Units')].toFixed(2) : 'n/a', '1 unit per pick at -110');
tile('Market picks', m.length ? m[ri('W')] + '-' + m[ri('L')] : '0-0', (isNum(m[ri('Success Rate')]) ? pct(m[ri('Success Rate')]) + ' ' : '') + 'straight up');
table($('recordTbl'), R.cols, R.rows, (c, v, r) => {
  if (c === 'Pick Type') { const s = String(v); return el('span', {className: s.startsWith('  ') ? 'indent' : '', textContent: s.trim()}); }
  if (c === 'Success Rate') return pct(v);
  if (c === 'Units') return isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(2) : '';
  return null;
});
table($('trendTbl'), D.trend.cols, D.trend.rows.slice().reverse(), (c, v) => (c.indexOf('Rate') >= 0 ? pct(v) : null));

function drawChart() {
  const host = $('chart'); host.replaceChildren();
  const tc = D.trend.cols, rows = D.trend.rows, di = tc.indexOf('Date'), ci = tc.indexOf('Cum Rate'), wi = tc.indexOf('Cum W'), li = tc.indexOf('Cum L');
  const pts = rows.filter(r => isNum(r[ci]));
  if (pts.length < 2) { host.append(el('div', {className: 'empty', textContent: 'The chart appears after two days of graded edge picks.'})); return; }
  const W = Math.max(host.clientWidth || 640, 300), H = 240, pad = {l: 44, r: 14, t: 12, b: 28};
  const cs = getComputedStyle(document.documentElement), col = n => cs.getPropertyValue(n).trim();
  const ys = pts.map(p => p[ci]).concat([0.524]);
  let lo = Math.max(0, Math.floor((Math.min(...ys) - 0.05) * 10) / 10), hi = Math.min(1, Math.ceil((Math.max(...ys) + 0.05) * 10) / 10);
  const x = i => pad.l + i * (W - pad.l - pad.r) / (pts.length - 1), y = v => pad.t + (hi - v) * (H - pad.t - pad.b) / (hi - lo);
  const NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg');
  s.setAttribute('viewBox', '0 0 ' + W + ' ' + H); s.setAttribute('role', 'img');
  s.setAttribute('aria-label', 'Cumulative success rate of edge picks by day');
  const add = (tag, at) => { const n = document.createElementNS(NS, tag); for (const k in at) n.setAttribute(k, at[k]); s.append(n); return n; };
  for (let v = lo; v <= hi + 1e-9; v += 0.1) {
    add('line', {x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: col('--grid'), 'stroke-width': 1});
    add('text', {x: pad.l - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: col('--muted')}).textContent = Math.round(v * 100) + '%';
  }
  add('line', {x1: pad.l, x2: W - pad.r, y1: y(0.524), y2: y(0.524), stroke: col('--text-2'), 'stroke-width': 1, 'stroke-dasharray': '4 4'});
  const step = Math.ceil(pts.length / 6);
  pts.forEach((p, i) => { if (i % step === 0 || i === pts.length - 1) add('text', {x: x(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: col('--muted')}).textContent = String(p[di]).slice(5); });
  add('path', {d: pts.map((p, i) => (i ? 'L' : 'M') + x(i) + ' ' + y(p[ci])).join(' '), fill: 'none', stroke: col('--series-1'), 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'});
  const last = pts.length - 1;
  add('circle', {cx: x(last), cy: y(pts[last][ci]), r: 4, fill: col('--series-1'), stroke: col('--surface'), 'stroke-width': 2});
  const hair = add('line', {y1: pad.t, y2: H - pad.b, stroke: col('--text-2'), 'stroke-width': 1, visibility: 'hidden'});
  const dot = add('circle', {r: 4, fill: col('--series-1'), stroke: col('--surface'), 'stroke-width': 2, visibility: 'hidden'});
  const tip = el('div', {className: 'tip'});
  host.append(s, tip);
  const hit = add('rect', {x: pad.l, y: 0, width: W - pad.l - pad.r, height: H, fill: 'transparent'});
  const show = ev => {
    const b = s.getBoundingClientRect(), px = (ev.clientX - b.left) * W / b.width;
    const i = Math.max(0, Math.min(last, Math.round((px - pad.l) / ((W - pad.l - pad.r) / last)))), p = pts[i];
    hair.setAttribute('x1', x(i)); hair.setAttribute('x2', x(i)); hair.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', x(i)); dot.setAttribute('cy', y(p[ci])); dot.setAttribute('visibility', 'visible');
    tip.replaceChildren(el('div', {textContent: p[di]}), el('div', {textContent: 'Cumulative ' + pct(p[ci]) + ' (' + p[wi] + '-' + p[li] + ')'}));
    tip.style.display = 'block';
    const left = x(i) * b.width / W;
    tip.style.left = Math.min(left + 10, b.width - tip.offsetWidth - 4) + 'px'; tip.style.top = '8px';
  };
  hit.addEventListener('pointermove', show); hit.addEventListener('pointerdown', show);
  hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; hair.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); });
}
addEventListener('resize', () => { if (!$('rate').hidden) drawChart(); });
if (!$('rate').hidden) drawChart();

// ---------- History
const Hh = D.history, hi_ = n => Hh.cols.indexOf(n);
function drawHist() {
  const ty = $('histType').value, rs = $('histRes').value, q = $('histSearch').value.trim().toLowerCase();
  const rows = Hh.rows.filter(r => (!ty || r[hi_('Type')] === ty) &&
    (!rs || (rs === 'pending' ? !r[hi_('Result')] : r[hi_('Result')] === rs)) &&
    (!q || r.join(' ').toLowerCase().includes(q)));
  table($('histTbl'), Hh.cols, rows, (c, v, r) => {
    if (c === 'Result') return v ? chip(v, v === 'W' ? 'W' : v === 'L' ? 'L' : '') : chip('Pending');
    if (c === 'Line') return isNum(v) ? (v > 0 ? '+' : '') + v : '';
    if (c === 'Edge') return isNum(v) ? (r[hi_('Type')] === 'Market' ? pct(v) : v.toFixed(1)) : '';
    return null;
  });
}
['histType', 'histRes'].forEach(i => $(i).onchange = drawHist); $('histSearch').oninput = drawHist; drawHist();

// ---------- Odds by Book (DraftKings standard + expandable books)
const O = D.odds || [];
const sp = (pt, px) => { const f = el('span'); f.append(document.createTextNode(!isNum(pt) ? '' : pt === 0 ? 'PK' : (pt > 0 ? '+' : '') + pt)); if (isNum(px)) f.append(el('span', {className: 'px', textContent: '(' + (px > 0 ? '+' : '') + Math.round(px) + ')'})); return f; };
const ml = v => isNum(v) ? (v > 0 ? '+' : '') + Math.round(v) : '';
const open = new Set();
let allOpen = false;
const BH = ['', 'Time', 'Away', 'Home', 'Away spread', 'Home spread', 'Away ML', 'Home ML', 'Books', 'Better than DK'];
const BT = {
  'Away spread': 'Points on the away team, with the price in parentheses. Game rows show DraftKings from the ESPN schedule.',
  'Home spread': 'Points on the home team, with the price in parentheses. Game rows show DraftKings from the ESPN schedule.',
  'Away ML': 'Moneyline for the away team to win outright (American odds).',
  'Home ML': 'Moneyline for the home team to win outright (American odds).',
  'Books': 'Other sportsbooks with a line on this game. Click the row to see them.',
  'Better than DK': 'How many other books offer at least one number better than DraftKings: more points on a side, the same points at a better price, or a better moneyline.'
};
function drawBooks() {
  const host = $('bookTbl'); host.replaceChildren();
  const q = $('bookSearch').value.trim().toLowerCase(), only = $('betterOnly').checked;
  const games = O.filter(g => (!q || (g.away + ' ' + g.home).toLowerCase().includes(q)) && (!only || g.better > 0));
  if (!games.length) { host.append(el('div', {className: 'empty', textContent: O.length ? 'No games match.' : 'No lines posted yet for this slate.'})); return; }
  const t = el('table', {className: 'odds'}), hr = el('tr'), tb = el('tbody');
  BH.forEach(h => { const th = el('th', {textContent: h, className: /spread|ML|Books|Better/.test(h) ? 'n' : ''}); if (BT[h]) th.append(infoBtn(h, BT[h])); hr.append(th); });
  t.append(el('thead', null, [hr]), tb); host.append(t);
  games.forEach((g, gi) => {
    const id = g.away + '|' + g.home + '|' + g.time, isOpen = allOpen || open.has(id), dk = g.dk || {};
    const tr = el('tr', {className: 'game'});
    tr.setAttribute('aria-expanded', isOpen);
    const cell = (c, cls) => { const td = el('td', {className: cls || ''}); if (c instanceof Node) td.append(c); else td.textContent = c == null ? '' : c; return td; };
    tr.append(cell(g.books.length ? (isOpen ? '▾' : '▸') : ''), cell(g.time), cell(g.away), cell(g.home),
      cell(g.dk ? sp(dk.away_pt, dk.away_px) : 'n/a', 'n dkcell sp'), cell(g.dk ? sp(dk.home_pt, dk.home_px) : 'n/a', 'n dkcell sp'),
      cell(ml(dk.away_ml), 'n dkcell'), cell(ml(dk.home_ml), 'n dkcell'), cell(g.books.length, 'n'),
      cell(g.better ? chip(g.better + (g.better === 1 ? ' book' : ' books'), 'hi') : '', 'n'));
    tr.title = g.dk ? 'Standard line: ' + dk.source : 'No DraftKings line for this game';
    tr.onclick = () => { if (open.has(id)) open.delete(id); else open.add(id); allOpen = false; drawBooks(); };
    tb.append(tr);
    if (!isOpen) return;
    g.books.forEach(b => {
      const r = el('tr', {className: 'book'}), bt = b.better || {};
      const c = (v, ok) => { const td = el('td', {className: 'n' + (ok ? ' better' : '')}); if (v instanceof Node) td.append(v); else td.textContent = v; if (ok) td.title = 'Better than DraftKings'; return td; };
      r.append(el('td'), el('td', {className: 'bk', textContent: b.book, colSpan: 3}),
        c(sp(b.away_pt, b.away_px), bt.away_sp), c(sp(b.home_pt, b.home_px), bt.home_sp),
        c(ml(b.away_ml), bt.away_ml), c(ml(b.home_ml), bt.home_ml), el('td'), el('td'));
      tb.append(r);
    });
  });
}
$('bookSearch').oninput = drawBooks; $('betterOnly').onchange = drawBooks;
$('expandAll').onclick = () => { allOpen = !allOpen; if (!allOpen) open.clear(); $('expandAll').textContent = allOpen ? 'Collapse all' : 'Expand all'; drawBooks(); };
drawBooks();

// ---------- Power rankings
const P = D.power || {cols: [], rows: []}, pi = n => P.cols.indexOf(n);
$('powerSrc').textContent = P.source ? 'Ratings source: ' + P.source + '. Ranked by net rating (adjusted offense minus adjusted defense).' : '';
[...new Set(P.rows.map(r => r[pi('Conf')]).filter(Boolean))].sort().forEach(c => $('powerConf').append(el('option', {value: c, textContent: c})));
function drawPower() {
  const cf = $('powerConf').value, q = $('powerSearch').value.trim().toLowerCase();
  const rows = P.rows.filter(r => (!cf || r[pi('Conf')] === cf) && (!q || String(r[pi('Team')]).toLowerCase().includes(q)));
  table($('powerTbl'), P.cols, rows, (c, v) => {
    if (c === 'Net') return isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(1) : '';
    if (c === 'Adj O' || c === 'Adj D' || c === 'Tempo') return isNum(v) ? v.toFixed(1) : '';
    if (c === 'Change') { if (!isNum(v) || v === 0) return isNum(v) ? '–' : ''; return el('span', {className: v > 0 ? 'up' : 'down', textContent: (v > 0 ? '▲ ' : '▼ ') + Math.abs(v)}); }
    return null;
  }, (D.tips || {}).power);
}
$('powerConf').onchange = drawPower; $('powerSearch').oninput = drawPower; drawPower();
})();
</script>
</body>
</html>
"""
