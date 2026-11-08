"""Static web dashboard (docs/index.html) for GitHub Pages.

The page is one self-contained HTML file: data is embedded as JSON and drawn
with a little plain JavaScript, so it works on GitHub Pages and on a phone.
"""

from __future__ import annotations

VERSION = "2026-11-07.2"

import json
import math
from datetime import date, datetime
from pathlib import Path

import pandas as pd

import config

TODAY_COLS = [
    ("Time", "Time"), ("T1 Team", "Away"), ("T2 Team", "Home"), ("Line", "Line"),
    ("Books", "Books"), ("Best T1", "Best away"), ("Best T2", "Best home"),
    ("Proj T1 Margin", "Proj away margin"), ("Edge Pick", "Edge pick"), ("Edge Size", "Edge"), ("Cover %", "Cover %"),
    ("Model T1 Win%", "Model away win"), ("Market T1 Win%", "Market away win"),
    ("Confidence", "Conf."), ("Model Pick", "Model pick"),
    ("Line Source", "Line source"), ("Line Tag", "Line tag"), ("_start", "Start"),
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
    names = {r["game_id"]: (r.get("t1") or r.get("espn_t1"), r.get("t2") or r.get("espn_t2")) for r in rows}
    out = []
    for g in sorted(games, key=lambda x: str(x.get("start") or "")):
        from odds_api import standard_line
        dk, books = standard_line(g)
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
                    "closed": bool(g.get("closing_snapshot")) or not g.get("_pregame", True),
                    "closedAt": g.get("closing_snapshot") if isinstance(g.get("closing_snapshot"), str) else "",
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
        df.attrs["ref"] = ref.stem.split("_")[-1] if ref is not None else ""
        df.attrs["files"] = len(files)
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
        "ESPN Rk": pd.to_numeric(df.get("espn_bpi_rank_now"), errors="coerce") if "espn_bpi_rank_now" in df else None,
    })
    if out["ESPN Rk"].notna().any():
        out["vs ESPN"] = out["ESPN Rk"] - out["Rk"]
    else:
        out = out.drop(columns=["ESPN Rk"])
    out.attrs.update(df.attrs)
    return out


def espn_compare(power: pd.DataFrame, data_dir) -> dict:
    """How closely the learned ratings agree with ESPN's current BPI today,
    plus how accurately each has projected finished games."""
    out = {}
    if power is not None and "ESPN Rk" in power:
        m = power.dropna(subset=["ESPN Rk"])
        if len(m) > 10:
            out["n"] = int(len(m))
            out["corr"] = round(float(m[["Rk", "ESPN Rk"]].corr(method="spearman").iloc[0, 1]), 3)
            out["mad"] = round(float((m["ESPN Rk"] - m["Rk"]).abs().mean()), 1)
            d = m.assign(diff=m["ESPN Rk"] - m["Rk"])
            pick = lambda x: [{"team": r["Team"], "rk": int(r["Rk"]), "espn": int(r["ESPN Rk"])} for _, r in x.iterrows()]
            out["higher"] = pick(d.sort_values("diff", ascending=False).head(5))
            out["lower"] = pick(d.sort_values("diff").head(5))
    try:
        import gamelog
        out["acc"] = gamelog.accuracy_summary(Path(data_dir) / "model_dataset.csv") if data_dir else {}
    except Exception:
        out["acc"] = {}
    return _sanitize(out)


def _market_eval(data_dir):
    try:
        import tracker
        return tracker.market_check(Path(data_dir) / "pick_history.csv") if data_dir else {}
    except Exception:
        return {}


def _clv(data_dir):
    try:
        import gamelog
        return gamelog.clv_summary(Path(data_dir) / "model_dataset.csv") if data_dir else {}
    except Exception:
        return {}


def portfolio(history: pd.DataFrame) -> dict:
    """Every Edge pick as a flat bet at -110 (default $100 per pick)."""
    stake = float(getattr(config, "PORTFOLIO_STAKE", 100))
    price = float(getattr(config, "PORTFOLIO_PRICE", -110))
    win = stake * (100 / -price if price < 0 else price / 100)
    bets = []
    if history is not None and not history.empty:
        h = history[(history["pick_type"] == "Edge") & (history["result"] != "NR")].copy()
        h = h.sort_values(["date", "start"], na_position="last")
        for _, r in h.iterrows():
            res = r.get("result")
            res = res if res in ("W", "L", "P") else None
            pl = None if res is None else (win if res == "W" else -stake if res == "L" else 0.0)
            bets.append(_sanitize({
                "date": r["date"], "away": r["t1"], "home": r["t2"], "team": r["pick_team"],
                "line": r.get("pick_line"), "edge": r.get("edge"), "cover": r.get("cover_prob"),
                "conf": r.get("confidence") or "Low", "result": res, "pl": pl,
                "s1": r.get("t1_score"), "s2": r.get("t2_score"),
            }))
    return {"stake": stake, "price": price, "win": round(win, 2), "bets": bets}


def live_picks(results: pd.DataFrame, history: pd.DataFrame | None = None) -> dict:
    """Edge pick per ESPN game id for the Live tab. The pick that was logged
    (pick history) wins, so finished games keep their pick even after the
    sportsbooks take the line down; today's board fills in the rest."""
    out = {}
    if results is not None and not results.empty and "_edge_side" in results:
        for _, r in results.iterrows():
            side, t1_line = r.get("_edge_side"), r.get("_t1_line")
            if not isinstance(side, str) or t1_line is None or pd.isna(t1_line):
                continue
            line = float(t1_line) if side == "T1" else -float(t1_line)
            out[str(r["game_id"])] = _sanitize({
                "side": "away" if side == "T1" else "home",
                "team": r["T1 Team"] if side == "T1" else r["T2 Team"],
                "line": line, "edge": r.get("Edge Size"), "cover": r.get("Cover %"),
                "conf": r.get("Confidence"), "model": str(r.get("Model Pick") or "").replace(" covers", ""),
            })
    if history is not None and not history.empty:
        cutoff = (pd.Timestamp.today().normalize() - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        h = history[(history["pick_type"] == "Edge") & (history["date"] >= cutoff)]
        for _, r in h.iterrows():
            line = r.get("pick_line")
            if line is None or pd.isna(line) or r.get("pick_side") not in ("T1", "T2"):
                continue
            out[str(r["game_id"])] = _sanitize({
                "side": "away" if r["pick_side"] == "T1" else "home", "team": r["pick_team"],
                "line": float(line), "edge": r.get("edge"), "cover": r.get("cover_prob"),
                "conf": r.get("confidence"), "logged": True,
            })
    return out


def conf_key() -> list[dict]:
    hi = getattr(config, "COVER_HIGH", 0.56)
    md = getattr(config, "COVER_MEDIUM", 0.54)
    ce = getattr(config, "CHECK_EDGE", 10.0)
    cs = getattr(config, "CHECK_SPREAD_SHARE", 0.30)
    return [
        {"tier": "High", "range": f"Cover {hi:.0%}+",
         "text": "The model's strongest spots: a solid edge the market hasn't closed."},
        {"tier": "Medium", "range": f"Cover {md:.0%} to {hi:.0%}",
         "text": "A real but modest edge. Worth a look alongside injury news and line moves."},
        {"tier": "Low", "range": f"Cover under {md:.0%}",
         "text": "Small disagreement with the line. Close to break-even (52.4% at -110)."},
        {"tier": "Check", "range": f"Edge {ce:g}+ pts, or {cs:.0%} of the spread if larger",
         "text": "The model and the books disagree too much to trust. Usually injuries, roster changes or "
                 "a stale rating. Check the news first; if nothing explains it, pass."},
    ]


def tips() -> dict:
    line_src = ("the most common line across all sportsbooks from The Odds API (falls back to DraftKings)"
                if config.LINE_SOURCE == "consensus" else "DraftKings via the ESPN schedule")
    hca = config.HOME_COURT_POINTS
    return {
        "today": {
            "Time": "Scheduled tip-off, Eastern time.",
            "Matchup": "Away team @ home team. Away is T1 in the original spreadsheet; the win % and margin columns are from the away team's side.",
            "Away": "Away team (T1 in the original spreadsheet). Win % and margin columns are from this team's side.",
            "Home": "Home team (T2). On a neutral court no home-court points are applied.",
            "Line": f"The spread the model compares against: {line_src}. If DraftKings has no line for a game, the next biggest book is used and a small tag shows which (FD = FanDuel, MGM = BetMGM, CZR = Caesars). PRE = pregame line: the game has started, so the line saved before tip-off is shown instead of live odds.",
            "Books": "How many sportsbooks posted a spread for this game (The Odds API).",
            "Best away": "The most points available on the away team at any single book. Higher is better for an away bet.",
            "Best home": "The most points available on the home team at any single book. Higher is better for a home bet.",
            "Proj away margin": f"Points the model expects the away team to win (+) or lose (-) by. (Away net rating - Home net rating) x average tempo / 100, minus {hca:g} for home court. Net rating = adjusted offense - adjusted defense, per 100 possessions.",
            "Edge pick": "The side the model likes against the spread, at the line shown. It is whichever side the Edge points to.",
            "Edge": "How many points the model disagrees with the line. |Proj away margin + away line|. Example: model Arizona by 34.3, line Arizona -31, edge 3.3 on Arizona. Yellow = 2+, green = 4+.",
            "Model away win": f"Model's chance the away team wins outright (spread ignored). Normal distribution of the projected margin with a standard deviation of {config.MARGIN_STDEV:g} points.",
            "Market away win": "The market's chance the away team wins outright: average of Kalshi and Polymarket prices, or the sportsbooks' moneylines with the bookmaker's cut removed if neither lists the game.",
            "Cover %": "Estimated chance the Edge pick covers. Very large edges are flattened (they are usually a model miss, not value), only " + f"{getattr(config, 'COVER_MODEL_WEIGHT', 0.35):.0%}" + " of the model's disagreement with the line is trusted, and lopsided games get a wider range of outcomes. A 3 point edge is about 53.5%, 7 points about 56%. Realistic values stay between 50% and 58%. Break-even at -110 is 52.4%.",
            "Conf.": "From Cover %: High " + f"{getattr(config, 'COVER_HIGH', 0.56):.0%}" + "+, Medium " + f"{getattr(config, 'COVER_MEDIUM', 0.54):.0%}" + "+, Low below that. Check = an edge of " + f"{getattr(config, 'CHECK_EDGE', 10.0):g}" + "+ points (or " + f"{getattr(config, 'CHECK_SPREAD_SHARE', 0.30):.0%}" + " of the spread in lopsided games): the model and the books disagree too much to trust. See the key below the table.",
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
            "ESPN Rk": "Where ESPN's own current BPI ranks this team today (fetched fresh each run), for comparison.",
            "vs ESPN": "ESPN's rank minus this model's rank. Positive (green) = this model rates the team higher than ESPN does; negative = lower.",
            "Change": "Places moved in the rankings since the comparison date shown above the table (about 7 days ago once enough history is saved). Green up, red down.",
        },
    }


def history_groups(history: pd.DataFrame, limit_days: int = 120) -> list[dict]:
    """One entry per game, with every pick on that game nested inside."""
    if history is None or history.empty:
        return []
    h = history[history["pick_type"] != "Watch"].copy()
    dates = sorted(h["date"].dropna().unique(), reverse=True)[:limit_days]
    h = h[h["date"].isin(dates)]
    order = {"Edge": 0, "Model": 1, "Market": 2}
    out = []
    for (d, gid), grp in h.groupby(["date", "game_id"], sort=False):
        grp = grp.sort_values("pick_type", key=lambda c: c.map(order).fillna(9))
        first = grp.iloc[0]
        picks = []
        for _, r in grp.iterrows():
            picks.append(_sanitize({
                "type": r["pick_type"], "team": r["pick_team"], "side": r["pick_side"],
                "line": r.get("pick_line"), "edge": r.get("edge"), "conf": r.get("confidence"),
                "ev": r.get("enhanced_value"), "cover": r.get("cover_prob"), "mprob": r.get("market_prob"), "modelp": r.get("model_prob"),
                "result": r.get("result"), "source": r.get("line_source"),
            }))
        out.append(_sanitize({
            "date": d, "start": first.get("start"), "gid": gid, "away": first["t1"], "home": first["t2"],
            "s1": first.get("t1_score"), "s2": first.get("t2_score"), "picks": picks,
        }))
    out.sort(key=lambda g: (g["date"] or "", -(pd.Timestamp(g["start"]).timestamp() if g.get("start") else 0)),
             reverse=True)
    return out


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
        "ratingsSource": ratings_source,
        "confKey": conf_key(),
        "today": {"cols": [h for _, h in TODAY_COLS], "rows": _records(today, TODAY_COLS)},
        "record": {"cols": list(record.columns), "rows": _records(record, [(c, c) for c in record.columns])},
        "trend": {"cols": list(trend.columns), "rows": _records(trend, [(c, c) for c in trend.columns])},
        "history": history_groups(history),
        "livePicks": live_picks(results, history),
        "portfolio": portfolio(history),
        "marketEval": _market_eval(data_dir),
        "clv": _clv(data_dir),
        "marketEdges": int((pd.to_numeric(results["Win% Edge (T1)"], errors="coerce").abs() >= config.MARKET_EDGE_MIN).sum())
                       if not results.empty and "Win% Edge (T1)" in results else 0,
        "odds": _sanitize(odds_compare(games, rows)),
        "espnCompare": espn_compare(power, data_dir),
        "power": {"cols": list(power.columns), "rows": _records(power, [(c, c) for c in power.columns]),
                  "source": ratings_source, "ref": power.attrs.get("ref", ""), "files": power.attrs.get("files", 0)},
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{
  color-scheme:light;
  --bg:#e7e7e4; --paper:#f3f3f1; --paper-2:#ebebe8; --ink:#0a0a0a; --ink-2:#3d3d3b; --muted:#7b7b77;
  --line:#c8c8c3; --rule:#0a0a0a; --blue:#1f3fe6; --on-blue:#ffffff; --block:#0a0a0a; --on-block:#f3f3f1;
  --good:#0d7a3c; --good-bg:#d9efe1; --bad:#b3261e; --bad-bg:#f6dcd9; --warn-bg:#fdeec2;
  --grid:#d4d4cf; --stripe:#ebebe8; --hover:#e1e1dc; --child:#e5e5e1;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4;
}
@media (prefers-color-scheme:dark){
  :root:where(:not([data-theme="light"])){
    color-scheme:dark;
    --bg:#0c0c0c; --paper:#151515; --paper-2:#1d1d1c; --ink:#f1f1ee; --ink-2:#c4c4bf; --muted:#8c8c87;
    --line:#2f2f2d; --rule:#f1f1ee; --blue:#3b5bff; --on-blue:#ffffff; --block:#f1f1ee; --on-block:#0c0c0c;
    --good:#5fd08f; --good-bg:#13301f; --bad:#f2897f; --bad-bg:#3a1a17; --warn-bg:#3a3110; --grid:#262625; --stripe:#1d1d1c; --hover:#252524; --child:#202020;
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0c0c0c; --paper:#151515; --paper-2:#1d1d1c; --ink:#f1f1ee; --ink-2:#c4c4bf; --muted:#8c8c87;
  --line:#2f2f2d; --rule:#f1f1ee; --blue:#3b5bff; --on-blue:#ffffff; --block:#f1f1ee; --on-block:#0c0c0c;
  --good:#5fd08f; --good-bg:#13301f; --bad:#f2897f; --bad-bg:#3a1a17; --warn-bg:#3a3110; --grid:#262625; --stripe:#1d1d1c; --hover:#252524; --child:#202020;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 "Inter Tight","Helvetica Neue",Helvetica,Arial,sans-serif;font-feature-settings:"tnum" 1}
.wrap{max-width:1240px;margin:0 auto;padding:28px 24px 56px}
.lbl{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase}
.muted{color:var(--muted)}

/* header */
.mast{display:grid;grid-template-columns:1fr auto;gap:16px;align-items:start;border-bottom:1px solid var(--rule);padding-bottom:18px}
.mast h1{margin:0;font-weight:800;font-size:clamp(56px,11vw,148px);line-height:.84;letter-spacing:-.055em;text-transform:lowercase}
.mast .side{position:relative;text-align:left;min-width:180px;padding:4px 0 0 18px}
.mast .side:before{content:"";position:absolute;left:0;top:0;bottom:0;border-left:1px solid var(--rule)}
.mast .side .stack{font-size:13px;font-weight:700;letter-spacing:.02em;text-transform:uppercase;line-height:1.25}
.mast .side .credit{color:var(--blue);text-decoration:none;border-bottom:1px solid currentColor}
.mast .side .credit:hover{color:var(--ink)}
.mast .side .meta{margin-top:26px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-2)}
.theme{margin-top:10px;background:none;border:1px solid var(--rule);color:var(--ink);padding:5px 10px;font:600 10.5px/1 inherit;letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
.sub{color:var(--ink-2);font-size:12.5px}

/* nav */
nav{display:flex;gap:0;margin:0 0 22px;overflow-x:auto;border-bottom:1px solid var(--line)}
nav button{background:none;border:0;border-bottom:3px solid transparent;color:var(--muted);font:600 12px/1 inherit;letter-spacing:.07em;text-transform:uppercase;padding:16px 18px 13px 0;margin-right:22px;cursor:pointer;white-space:nowrap}
nav button .n{color:var(--muted);margin-right:8px;font-weight:500}
nav button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--blue)}
nav button[aria-selected="true"] .n{color:var(--blue)}
section[hidden]{display:none}

/* tiles */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:18px}
.tile{position:relative;background:var(--paper);border:1px solid var(--line);padding:14px 16px 16px;min-height:150px;display:flex;flex-direction:column}
.tile .top{display:flex;justify-content:space-between;gap:8px}
.tile .v{font-size:52px;font-weight:700;letter-spacing:-.04em;line-height:1;margin-top:auto;padding-top:18px}
.tile .s{font-size:12.5px;margin-top:8px;color:var(--ink-2)}
.tile .arrow{position:absolute;right:14px;bottom:12px;font-size:16px}
.tile .v.long{font-size:clamp(28px,3.4vw,44px)}
.tile.blue{background:var(--blue);border-color:var(--blue);color:var(--on-blue)}
.tile.blue .s,.tile.blue .lbl{color:var(--on-blue)}
.tile.black{background:var(--block);border-color:var(--block);color:var(--on-block)}
.tile.black .s,.tile.black .lbl{color:var(--on-block)}

/* cards & controls */
.card{background:var(--paper);border:1px solid var(--line);padding:16px;margin-bottom:16px}
.card-h{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--rule);padding-bottom:10px;margin-bottom:12px}
.card-h h2{margin:0;font-size:22px;font-weight:700;letter-spacing:-.02em}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px}
select,input[type=search]{background:var(--paper);color:var(--ink);border:1px solid var(--rule);border-radius:0;padding:8px 10px;font:500 13px inherit}
input[type=search]{min-width:0;flex:1 1 200px}
.btn{background:var(--ink);color:var(--bg);border:1px solid var(--ink);border-radius:0;padding:8px 14px;font:600 11px inherit;letter-spacing:.08em;text-transform:uppercase;cursor:pointer}
label.chk{display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--ink-2)}

/* tables */
.tbl{overflow-x:auto;background:var(--paper);border:1px solid var(--line)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:9px 12px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
th{position:sticky;top:0;background:var(--paper);color:var(--ink);font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--rule);cursor:pointer;user-select:none}
td.n,th.n{text-align:right}
tbody tr.alt>td{background:var(--stripe)}
tbody tr:hover>td{background:var(--hover)}
.chip{display:inline-block;padding:2px 7px;font-size:11px;font-weight:700;letter-spacing:.04em;border:1px solid var(--line);background:transparent}
.W{background:var(--good-bg);color:var(--good);border-color:transparent}
.L{background:var(--bad-bg);color:var(--bad);border-color:transparent}
.hi{background:var(--blue);color:var(--on-blue);border-color:var(--blue)}
.md{border-color:var(--ink);color:var(--ink)}
.indent{padding-left:22px;color:var(--ink-2)}
.empty{color:var(--muted);padding:22px 14px}
.info{background:none;border:0;padding:0 0 0 5px;margin:0;color:var(--muted);font:inherit;font-size:12px;cursor:help;line-height:1}
.info:hover,.info:focus-visible{color:var(--blue);outline:none}
#hint{position:fixed;z-index:50;max-width:310px;background:var(--ink);color:var(--bg);padding:10px 12px;font-size:12.5px;line-height:1.45;display:none}
#hint b{display:block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px}
.up{color:var(--good);font-weight:700}.down{color:var(--bad);font-weight:700}

/* expandable rows (odds + history) */
tr.parent{cursor:pointer}
tr.parent td.tog{width:30px;color:var(--ink);font-weight:700}
tr.child>td{background:var(--child);font-size:12.5px}
tr.child>td:first-child{box-shadow:inset 3px 0 0 var(--blue)}
tr.child td.bk{padding-left:30px;color:var(--ink-2)}
.px{color:var(--muted);font-size:11.5px;margin-left:4px}
.better{background:var(--good-bg)!important;color:var(--good);font-weight:700}
.better:before{content:"\25B2 ";font-size:9px}
.dk{font-weight:700}
button.src{background:none;font-family:inherit;cursor:help}
.src{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.06em;color:var(--muted);border:1px solid var(--line);padding:0 3px;margin-left:5px;vertical-align:2px;line-height:1.4}
.srcnote{display:block;font-size:10.5px;color:var(--muted);margin-top:2px;font-weight:400}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;font-size:12.5px;color:var(--ink-2);margin:0 0 12px}
.legend .sw{display:inline-block;padding:1px 6px}

/* today: compact board + phone cards */
.cards{display:none}
.gcard{border-top:1px solid var(--rule);padding:12px 2px 14px}
.gcard .row1{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.gcard .teams{font-size:15px;font-weight:700;letter-spacing:-.01em}
.gcard .meta{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);white-space:nowrap}
.gcard .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;margin-top:10px}
.gcard .k{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.gcard .v{font-size:13.5px;font-weight:600;margin-top:2px}
@media (max-width:720px){ #todayTbl{display:none} .cards{display:block} label[for=todayMore],#todayMoreWrap{display:none} }
.key{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--rule);margin-top:14px}
.key>div{padding:12px 14px 4px 0}
.key>div+div{padding-left:14px;border-left:1px solid var(--line)}
.key .kt{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.key .kr{font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.key p{margin:0;font-size:12.5px;color:var(--ink-2)}
@media (max-width:900px){.key{grid-template-columns:1fr 1fr}.key>div:nth-child(3){padding-left:0;border-left:0}}
@media (max-width:520px){.key{grid-template-columns:1fr}.key>div{padding-left:0!important;border-left:0!important;border-bottom:1px solid var(--line);padding-bottom:10px}}
/* live: ticker ribbon */
.ticker{position:sticky;top:0;z-index:40;background:var(--block);color:var(--on-block);height:34px;overflow:hidden;display:flex;align-items:center;border-bottom:3px solid var(--blue)}
.ticker[hidden]{display:none}
.ticker .tlabel[hidden]{display:none}
.ticker .tlabel{flex:0 0 auto;height:100%;display:flex;align-items:center;gap:6px;padding:0 12px;background:var(--blue);color:var(--on-blue);font:700 11px/1 inherit;letter-spacing:.1em;text-transform:uppercase;z-index:1}
.ticker .viewport{flex:1;overflow:hidden;height:100%;position:relative}
.ticker .track{display:inline-flex;white-space:nowrap;height:100%;align-items:center;will-change:transform;animation:tick var(--dur,60s) linear infinite}
.ticker:hover .track{animation-play-state:paused}
@keyframes tick{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.ticker .it{display:inline-flex;align-items:center;gap:7px;padding:0 18px;font-size:12.5px;font-weight:600;border-right:1px solid rgba(127,127,127,.35);height:100%}
.ticker .it .sc{font-weight:800;font-variant-numeric:tabular-nums}
.ticker .it .st{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;opacity:.7}
.ticker .it .rk{font-size:10px;opacity:.6}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--muted)}
.dot.live{background:#ff3b30;animation:pulse 1.4s ease-in-out infinite}
.dot.cov{background:#2ecc71}.dot.not{background:#ff5a4f}
@keyframes pulse{50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){.ticker .track{animation:none}.ticker .viewport{overflow-x:auto}}
/* live: tab list */
.lrow{display:grid;grid-template-columns:92px minmax(0,1.6fr) minmax(0,1fr) 120px;gap:12px;align-items:center;padding:11px 12px;border-bottom:1px solid var(--line)}
.lrow:nth-child(even){background:var(--stripe)}
.lrow .when{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.lrow .teams{display:grid;gap:3px}
.lrow .tm{display:flex;justify-content:space-between;gap:10px;font-size:13.5px}
.lrow .tm b{font-variant-numeric:tabular-nums}
.lrow .tm.win{font-weight:700}
.lrow .pick{font-size:12.5px;color:var(--ink-2)}
.lrow .stat{text-align:right}
.lhead{display:grid;grid-template-columns:92px minmax(0,1.6fr) minmax(0,1fr) 120px;gap:12px;padding:9px 12px;border-bottom:1px solid var(--rule);font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.lhead div:last-child{text-align:right}
.seg{display:inline-flex;border:1px solid var(--rule)}
.seg button{background:none;border:0;border-right:1px solid var(--rule);padding:7px 12px;font:600 11px inherit;letter-spacing:.06em;text-transform:uppercase;color:var(--ink);cursor:pointer}
.seg button:last-child{border-right:0}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--bg)}
.livemeta{font-size:12px;color:var(--ink-2);display:flex;align-items:center;gap:6px}
@media (max-width:620px){.lrow,.lhead{grid-template-columns:70px minmax(0,1fr) 92px}.lrow .pick,.lhead .ph{grid-column:2/4;grid-row:2}.lhead .ph{display:none}.lrow .stat{grid-column:3;grid-row:1}}
/* live: dock (minimizes to the bottom like a chat window) */
.dock{position:fixed;right:20px;bottom:0;width:340px;z-index:45;background:var(--paper);border:1px solid var(--rule);border-bottom:0;box-shadow:0 -6px 24px rgba(0,0,0,.14);display:flex;flex-direction:column;max-height:min(70vh,560px)}
.dock .dh{display:flex;align-items:center;gap:8px;padding:12px 14px;cursor:pointer;user-select:none;border-bottom:1px solid var(--rule)}
.dock.min .dh{border-bottom:0}
.dock .dh h3{margin:0;font-size:15px;font-weight:700;letter-spacing:-.01em;flex:1}
.dock .badge{background:#ff3b30;color:#fff;font-size:10.5px;font-weight:700;padding:1px 6px;border-radius:9px}
.dock .ib{background:none;border:0;color:var(--ink);font-size:16px;line-height:1;cursor:pointer;padding:2px 4px}
.dock .db{overflow-y:auto}
.dock.min .db,.dock.min .df,.dock.min .dset{display:none}
#espnDiff{display:grid;gap:8px;margin:4px 0 8px}
@media (max-width:1200px){#powerTbl th,#powerTbl td{padding:9px 8px}}
details.about{border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:0 0 12px}
details.about summary{cursor:pointer;padding:10px 0;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;list-style:none;display:flex;justify-content:space-between}
details.about summary::-webkit-details-marker{display:none}
details.about summary::after{content:"+";font-size:14px}
details.about[open] summary::after{content:"\2212"}
details.about .about-body{padding:0 0 10px}
.dock .dset{display:flex;flex-wrap:wrap;gap:4px 14px;padding:8px 14px;border-bottom:1px solid var(--line);font-size:11.5px;color:var(--ink-2)}
.dock .dset label{display:flex;align-items:center;gap:5px;cursor:pointer}
.dock .dg .pk{margin-top:5px;font-size:11.5px;color:var(--ink);display:flex;justify-content:space-between;gap:8px;align-items:center}
.dock .dg .pk .pt{font-weight:600}
.dock .dg{padding:10px 14px;border-bottom:1px solid var(--line)}
.dock .dg:nth-child(even){background:var(--stripe)}
.dock .dg .r{display:flex;justify-content:space-between;gap:8px;font-size:13px}
.dock .dg .r b{font-variant-numeric:tabular-nums}
.dock .dg .m{display:flex;justify-content:space-between;gap:8px;margin-top:4px;font-size:11.5px;color:var(--ink-2)}
.dock .df{padding:8px 14px;border-top:1px solid var(--line);font-size:11px;color:var(--muted);display:flex;justify-content:space-between}
.dock .sec{padding:7px 14px;font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--line);background:var(--paper)}
@media (max-width:620px){.dock{right:0;left:0;width:auto}}
body.has-dock .wrap{padding-bottom:90px}
/* mobile list rows (History, Odds by Book) */
.mlist .mi{padding:12px 12px;border-bottom:1px solid var(--line)}
.mlist .mi.alt{background:var(--stripe)}
.mlist .mi.tap{cursor:pointer}
.mlist .mt{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.mlist .mt b{font-size:14px;letter-spacing:-.01em}
.mlist .ms{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);white-space:nowrap}
.mlist .mg{display:grid;grid-template-columns:1fr 1fr;gap:6px 12px;margin-top:8px}
.mlist .mg .k{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.mlist .mg .v{font-size:13px;font-weight:600;margin-top:1px}
.mlist .mx{margin-top:10px;border-top:1px solid var(--line);padding-top:8px;display:grid;gap:6px}
.mlist .mx .xr{display:grid;grid-template-columns:minmax(0,1.1fr) 1fr 1fr;gap:6px;font-size:12.5px;align-items:center}
.mlist .mx .xr.h{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.mlist .mx .xr span{padding:3px 4px}
.mlist .more{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--blue);margin-top:8px}
.psub{display:block;font-size:11px;color:var(--muted);margin-top:2px;white-space:normal}
@media (max-width:720px){
  th,td{padding:8px 8px;font-size:12.5px}
  th{font-size:9.5px;letter-spacing:.06em}
  .card{padding:12px}
  .card-h{flex-wrap:wrap;gap:4px}
  .card-h h2{font-size:19px}
  .controls{gap:8px}
  .controls select,.controls input[type=search],.controls .btn{flex:1 1 100%}
  .legend{font-size:12px}
  .controls .seg{display:flex !important;flex-wrap:wrap;width:100%;max-width:100%}
  .controls .seg button{flex:1 1 auto;padding:8px 6px}
  #recordTbl td:first-child,#powerTbl td:nth-child(2){white-space:normal}
  #recordTbl .indent{padding-left:12px}
}
/* portfolio */
.pfsec .card-h{cursor:pointer}
.pfsec .card-h h2{display:flex;align-items:center;gap:10px}
.pfsec .sw{display:inline-block;width:12px;height:12px}
.pfsum{display:flex;flex-wrap:wrap;gap:6px 22px;font-size:12.5px;color:var(--ink-2);margin-bottom:10px}
.pfsum b{color:var(--ink);font-size:14px;margin-left:4px}
.pos{color:var(--good);font-weight:700}.neg{color:var(--bad);font-weight:700}
.legend .li{display:inline-flex;align-items:center;gap:6px}
.legend .li i{display:inline-block;width:14px;height:3px}
/* snowfall (behind everything; cards stay readable) */
#snow{position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:0}
.wrap{position:relative;z-index:1}
/* chart */
.chart{position:relative}
.chart svg{display:block;width:100%;height:auto}
.tip{position:absolute;pointer-events:none;background:var(--ink);color:var(--bg);padding:7px 10px;font-size:12px;display:none;white-space:nowrap}

/* footer */
footer{margin-top:34px;display:grid;grid-template-columns:auto 1fr 1fr auto;gap:18px;align-items:start;border-top:1px solid var(--rule);padding-top:18px}
footer .sq{width:44px;height:44px;background:var(--blue);color:var(--on-blue);display:flex;align-items:center;justify-content:center;font-size:20px;text-decoration:none}
footer .cta{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.02em;line-height:1.25}
footer ul{margin:0;padding:0;list-style:none;font-size:11.5px;color:var(--ink-2)}
footer ul li{padding:1px 0}
footer a{color:var(--ink)}
@media (max-width:720px){
  .wrap{padding:18px 16px 40px}
  .mast{grid-template-columns:1fr}
  .mast .side{padding:12px 0 0;border-top:1px solid var(--rule)}
  .mast .side:before{display:none}
  .mast .side .credit{color:var(--blue);text-decoration:none;border-bottom:1px solid currentColor}
.mast .side .credit:hover{color:var(--ink)}
.mast .side .meta{margin-top:10px}
  .tiles{grid-template-columns:1fr 1fr;gap:10px}
  .tile{min-height:118px;padding:12px}.tile .v{font-size:36px;padding-top:12px}
  footer{grid-template-columns:auto 1fr}
}
</style>
</head>
<body class="has-dock">
<canvas id="snow" aria-hidden="true"></canvas>
<div class="ticker" id="ticker" hidden aria-label="Live scores">
  <div class="tlabel" id="tickerLabel" hidden><span class="dot live"></span>Live</div>
  <div class="viewport"><div class="track" id="tickerTrack"></div></div>
</div>
<div class="wrap">
  <header class="mast">
    <h1>ncaam<br>model</h1>
    <div class="side">
      <div class="stack">Designed by<br>Colten Morris<br><a class="credit" href="https://www.linkedin.com/in/colten-morris/" target="_blank" rel="noopener">LinkedIn &#8599;</a></div>
      <div class="meta"><div id="day"></div><div id="updated"></div></div>
      <button class="theme" id="theme" type="button">Theme</button>
      <button class="theme" id="tickerToggle" type="button" aria-pressed="true">Live ticker: On</button>
      <button class="theme" id="snowToggle" type="button" aria-pressed="true">Snow: On</button>
    </div>
  </header>

  <nav role="tablist">
    <button role="tab" aria-selected="true" data-tab="today"><span class="n">01</span>Today</button>
    <button role="tab" aria-selected="false" data-tab="live"><span class="n">02</span>Live</button>
    <button role="tab" aria-selected="false" data-tab="rate"><span class="n">03</span>Success Rate</button>
    <button role="tab" aria-selected="false" data-tab="history"><span class="n">04</span>History</button>
    <button role="tab" aria-selected="false" data-tab="books"><span class="n">05</span>Odds by Book</button>
    <button role="tab" aria-selected="false" data-tab="power"><span class="n">06</span>Power Rankings</button>
    <button role="tab" aria-selected="false" data-tab="portfolio"><span class="n">07</span>Portfolio</button>
  </nav>

  <section id="today">
    <div class="tiles" id="todayTiles"></div>
    <div class="card">
      <div class="card-h"><h2>Today's board</h2><span class="lbl muted">Sorted by edge</span></div>
      <div class="controls">
        <label class="lbl muted" for="edgeMin">Edge at least</label>
        <select id="edgeMin"></select>
        <input type="search" id="todaySearch" placeholder="Search team">
        <label class="chk" id="todayMoreWrap"><input type="checkbox" id="todayMore"> Show all columns</label>
      </div>
      <div class="tbl" id="todayTbl"></div>
      <div class="cards" id="todayCards"></div>
      <p class="sub">Away = T1, Home = T2. Hover or tap &#9432; for what each column means. <span id="ratingsSrc"></span></p>
      <div class="key" id="confKey" aria-label="Confidence key"></div>
    </div>
  </section>

  <section id="live" hidden>
    <div class="tiles" id="liveTiles"></div>
    <div class="card">
      <div class="card-h"><h2>Today's games</h2><span class="livemeta"><span class="dot" id="liveDot"></span><span id="liveStamp">Loading live scores</span></span></div>
      <div class="controls">
        <div class="seg" id="liveFilter" role="group" aria-label="Filter games">
          <button type="button" data-f="all" aria-pressed="true">All</button>
          <button type="button" data-f="in" aria-pressed="false">Live</button>
          <button type="button" data-f="pre" aria-pressed="false">Upcoming</button>
          <button type="button" data-f="post" aria-pressed="false">Final</button>
        </div>
        <label class="chk"><input type="checkbox" id="livePicksOnly"> Only games with a pick</label>
        <input type="search" id="liveSearch" placeholder="Search team">
      </div>
      <div class="tbl" id="liveList"></div>
      <p class="sub">Sorted by start time. Scores refresh every 30 seconds while this page is open. Covering status uses the line the Edge pick was logged at.</p>
    </div>
  </section>

  <section id="rate" hidden>
    <div class="tiles" id="rateTiles"></div>
    <div class="card"><div class="card-h"><h2>Cumulative success rate</h2><span class="lbl muted">Sportsbook edge picks</span></div>
      <div class="chart" id="chart"></div>
      <p class="sub">Dashed line = 52.4%, break-even against the spread at -110.</p>
    </div>
    <div class="card"><div class="card-h"><h2>How to read this</h2><span class="lbl muted">Units</span></div>
      <p class="sub" style="margin:0">A <b>unit</b> is one standard bet. <b>Units</b> = profit or loss if you bet 1 unit on every pick in a group. Against the spread at the usual -110 price, a win pays <b>+0.91</b>, a loss costs <b>-1</b>, and a push is <b>0</b>. So +5.00 units means you would be up five bets' worth; with $100 bets that is +$500. Because a loss costs more than a win pays, you need to win <b>52.4%</b> just to break even. Market picks are paid at the market's own price instead of -110.</p>
    </div>
    <div class="card"><div class="card-h"><h2>Closing line value</h2><span class="lbl muted">Edge picks</span></div>
      <div class="tiles" id="clvTiles" style="margin-bottom:8px"></div>
      <p class="sub" style="margin:0">The line usually moves toward the right number before tip-off, as sharp money comes in. If the line you could have bet when the pick first appeared is <b>better than the closing line</b> (the last line before tip-off), the pick beat the close. Beating the close more than half the time is one of the strongest signs a model finds real value, and it shows up after far fewer games than win-loss does. Opening = first run that saw the game; closing = last run before tip-off.</p>
    </div>
    <div class="card"><div class="card-h"><h2>Record by pick type</h2><button class="btn" id="recExpand" type="button">Expand all</button></div><div class="tbl" id="recordTbl"></div>
      <p class="sub">Click a group to show its breakdown. Success is judged on the Sportsbook Edge picks; Model and Market picks are tracked as supplemental information only. Confidence uses the current rules for every pick.</p></div>
    <div class="card"><div class="card-h"><h2>Model odds vs market odds</h2><span class="lbl muted">Supplemental</span></div>
      <div id="mktEval"></div>
    </div>
    <div class="card"><div class="card-h"><h2>Edge picks by day</h2><span class="lbl muted">Against the spread</span></div><div class="tbl" id="trendTbl"></div></div>
  </section>

  <section id="history" hidden>
    <div class="card">
      <div class="card-h"><h2>Pick history</h2><span class="lbl muted">Judged on the Edge pick. Click a game for supplemental picks.</span></div>
      <div class="controls">
        <select id="histRes"><option value="">All edge results</option><option>W</option><option>L</option><option>P</option><option value="pending">Pending</option></select>
        <input type="search" id="histSearch" placeholder="Search team or date">
        <button class="btn" id="histExpand" type="button">Expand all</button>
      </div>
      <div class="tbl" id="histTbl"></div>
    </div>
  </section>

  <section id="books" hidden>
    <div class="card">
      <div class="card-h"><h2>Odds by book</h2><span class="lbl muted">DraftKings is the standard line</span></div>
      <div class="controls">
        <input type="search" id="bookSearch" placeholder="Search team">
        <label class="chk"><input type="checkbox" id="betterOnly"> Only games where another book beats the standard line</label>
        <button class="btn" id="expandAll" type="button">Expand all</button>
      </div>
      <div class="legend"><span>DraftKings is the standard line. If it has no line for a game, the next biggest book is used and tagged (e.g. <span class="src" style="margin:0">FD</span> = FanDuel). Click a game to see every book.</span>
        <span><span class="sw better">better</span> more points, a better price, or a better moneyline than the standard line for that side</span></div>
      <div class="tbl" id="bookTbl"></div>
    </div>
  </section>

  <section id="power" hidden>
    <div class="card">
      <div class="card-h"><h2>Power rankings</h2><span class="lbl muted" id="powerSrc"></span></div>
      <div class="controls">
        <select id="powerConf"><option value="">All conferences</option></select>
        <input type="search" id="powerSearch" placeholder="Search team">
        <label class="chk"><input type="checkbox" id="powerEspn"> Show ESPN comparison columns</label>
      </div>
      <details class="about" id="powerAbout">
        <summary>About these rankings</summary>
        <div class="about-body">
          <p class="sub" id="espnAgree"></p>
          <div id="espnDiff"></div>
          <p class="sub">This model starts from ESPN's preseason BPI and learns from every finished game: each result moves a team's offense, defense and tempo toward what actually happened, a little less with every game played. ESPN's current BPI is fetched separately each run so you can see whether the two agree. Large gaps on a team usually mean a few unusual results, or something ESPN accounts for that results alone don't show (injuries, roster changes).</p>
        </div>
      </details>
      <div class="tbl" id="powerTbl"></div>
    </div>
  </section>

  <section id="portfolio" hidden>
    <div class="tiles" id="pfTiles"></div>
    <div class="card">
      <div class="card-h"><h2>Bankroll</h2><span class="lbl muted" id="pfRule"></span></div>
      <div class="controls">
        <div class="seg" id="pfSections" role="group" aria-label="Sections to show"></div>
        <select id="pfRange" aria-label="Date range"><option value="all">Whole season</option><option value="30">Last 30 days</option><option value="7">Last 7 days</option></select>
      </div>
      <div class="chart" id="pfChart"></div>
      <div class="legend" id="pfLegend"></div>
    </div>
    <div id="pfCards"></div>
  </section>

  <footer>
    <a class="sq" href="NCAAM_Dashboard.xlsx" aria-label="Download the Excel dashboard">&#8599;</a>
    <div class="cta">Download<br>the full<br>dashboard.</div>
    <div><div class="lbl">Data</div><ul><li><a href="NCAAM_Dashboard.xlsx">Excel dashboard</a></li><li><a href="pick_history.csv">Pick history (CSV)</a></li><li id="mode"></li></ul></div>
    <div><div class="lbl">Last run</div><ul id="notes"></ul></div>
  </footer>
  <div id="hint" role="tooltip"></div>
</div>
<aside class="dock min" id="dock" aria-label="Live game tracker">
  <div class="dh" id="dockHead" role="button" tabindex="0" aria-expanded="false">
    <span class="dot" id="dockDot"></span><h3>Live games</h3><span class="badge" id="dockBadge" hidden>0</span>
    <button class="ib" id="dockToggle" type="button" aria-label="Expand live tracker">&#9650;</button>
  </div>
  <div class="dset" id="dockSet">
    <label><input type="checkbox" id="dockPicks"> Show Edge picks</label>
    <label><input type="checkbox" id="dockLined"> Hide games with no line</label>
  </div>
  <div class="db" id="dockBody"></div>
  <div class="df"><span id="dockStamp"></span><a href="#" id="dockAll">All games &#8599;</a></div>
</aside>

<script id="payload" type="application/json">__DATA__</script>
<script>
(function(){
const D = JSON.parse(document.getElementById('payload').textContent);
const $ = id => document.getElementById(id);
const el = (tag, props, kids) => { const e = document.createElement(tag); if (props) Object.assign(e, props); (kids||[]).forEach(k => e.append(k)); return e; };
const isNum = v => typeof v === 'number' && isFinite(v);
const pct = v => isNum(v) ? (v*100).toFixed(1) + '%' : '';
const sgn = v => isNum(v) ? (v > 0 ? '+' : '') + (Math.round(v*10)/10).toFixed(1) : '';
const line = v => !isNum(v) ? '' : v === 0 ? 'PK' : (v > 0 ? '+' : '') + v;
const chip = (text, cls) => el('span', {className: 'chip ' + (cls || ''), textContent: text});
const pad2 = n => String(n).padStart(2, '0');
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch(e) { return d; } },
                set(k, v) { try { localStorage.setItem(k, v); } catch(e) {} } };
var pfReady = false;
const MQ = matchMedia('(max-width: 720px)');
const mobile = () => MQ.matches;
const kv2 = (k, v) => el('div', null, [el('div', {className: 'k', textContent: k}), (() => { const d = el('div', {className: 'v'}); if (v instanceof Node) d.append(v); else d.textContent = v == null ? '' : v; return d; })()]);

// theme
const root = document.documentElement;
try { const t = localStorage.getItem('theme'); if (t) root.dataset.theme = t; } catch(e) {}
$('theme').onclick = () => {
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('theme', root.dataset.theme); } catch(e) {}
  drawChart(); if (pfReady) drawPortfolio();
};
$('day').textContent = D.day;
$('updated').textContent = 'Updated ' + D.updated;
$('mode').textContent = 'Mode: ' + D.mode;
D.notes.forEach(n => $('notes').append(el('li', {textContent: n, className: n.startsWith('OUT OF DATE') ? 'down' : ''})));

// tabs
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.setAttribute('aria-selected', x === b));
  document.querySelectorAll('section').forEach(s => s.hidden = s.id !== b.dataset.tab);
  if (b.dataset.tab === 'rate') drawChart();
  if (b.dataset.tab === 'portfolio' && pfReady) drawPortfolio();
  try { localStorage.setItem('tab', b.dataset.tab); } catch(e) {}
});
try { const t = localStorage.getItem('tab'); if (t) { const b = document.querySelector('nav button[data-tab="'+t+'"]'); if (b) b.click(); } } catch(e) {}

// info tooltips
const hint = $('hint'); let pinned = null;
function showHint(btn) {
  hint.replaceChildren(el('b', {textContent: btn.dataset.label}), document.createTextNode(btn.dataset.tip));
  hint.style.display = 'block';
  const r = btn.getBoundingClientRect(), w = hint.offsetWidth, h = hint.offsetHeight;
  const left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8);
  let top = r.bottom + 8; if (top + h > innerHeight - 8) top = r.top - h - 8;
  hint.style.left = left + 'px'; hint.style.top = top + 'px';
}
function hideHint() { hint.style.display = 'none'; pinned = null; }
function infoBtn(label, tip) {
  const b = el('button', {type: 'button', className: 'info', textContent: 'ⓘ'});
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

function tile(host, i, k, v, s, cls) {
  host.append(el('div', {className: 'tile ' + (cls || '')}, [
    el('div', {className: 'top'}, [el('span', {className: 'lbl', textContent: k}), el('span', {className: 'lbl', textContent: pad2(i)})]),
    el('div', {className: 'v' + (String(v).length >= 7 ? ' long' : ''), textContent: v}), el('div', {className: 's', textContent: s}),
    el('span', {className: 'arrow', textContent: '↗'})]));
}

// sortable table
function tagText(tag, src) {
  if (tag === 'PRE') return 'PRE = pregame line. This game has already tipped off, so the board shows the line, pick and confidence saved before the game. Live in-game odds are ignored.' + (src ? ' Source: ' + String(src).replace(/^Pregame: /, '') + '.' : '');
  return tag + ' = ' + (src || 'another sportsbook') + '. DraftKings had no line for this game, so the next biggest sportsbook was used.';
}
function tagBtnText(tag, label, text) {
  const b = infoBtn(label, text);
  b.className = 'src'; b.textContent = tag; b.style.cursor = 'help';
  return b;
}
function tagBtn(tag, src) {
  const b = infoBtn(tag === 'PRE' ? 'Pregame line' : 'Line source', tagText(tag, src));
  b.className = 'src'; b.textContent = tag; b.style.cursor = 'help';
  return b;
}
function table(host, cols, rows, fmt, tipMap, sortBy) {
  host.replaceChildren();
  if (!rows.length) { host.append(el('div', {className: 'empty', textContent: 'Nothing to show yet.'})); return; }
  let sortI = -1, dir = 1;
  const numCol = cols.map((_, i) => rows.some(r => isNum(r[i])) && rows.every(r => r[i] == null || isNum(r[i])));
  const t = el('table'), tb = el('tbody'), hr = el('tr');
  cols.forEach((c, i) => {
    const th = el('th', {textContent: c, className: numCol[i] ? 'n' : ''});
    if (tipMap && tipMap[c]) th.append(infoBtn(c, tipMap[c]));
    th.onclick = () => { dir = sortI === i ? -dir : (numCol[i] && !/^Conf/.test(c) ? -1 : 1); sortI = i; body(); };
    hr.append(th);
  });
  t.append(el('thead', null, [hr]), tb); host.append(t);
  function body() {
    const rs = rows.slice();
    const RANK = {High: 0, Medium: 1, Low: 2, Check: 3};
    const key = v => (typeof v === 'string' && v in RANK) ? RANK[v] : v;
    const kv = r => { const k = sortBy ? sortBy(cols[sortI], r) : undefined; return k !== undefined ? k : key(r[sortI]); };
    if (sortI >= 0) rs.sort((a, b) => { const x = kv(a), y = kv(b); if (x == null || x === '') return 1; if (y == null || y === '') return -1; return (x > y ? 1 : x < y ? -1 : 0) * dir; });
    tb.replaceChildren(...rs.map((r, ri) => {
      const tr = el('tr', {className: ri % 2 ? 'alt' : ''});
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

// ---------- 01 Today
const T = D.today, ti = n => T.cols.indexOf(n);
const buckets = D.edgeBuckets.length ? D.edgeBuckets : [0, 2, 4, 6];
const b1 = buckets[1] || 2, b2 = buckets[2] || 4;
buckets.forEach(b => $('edgeMin').append(el('option', {value: b, textContent: b === 0 ? 'Any' : b + '+ pts'})));
$('edgeMin').value = b1;
const nStrong = T.rows.filter(r => isNum(r[ti('Edge')]) && r[ti('Edge')] >= b1).length;
const nBig = T.rows.filter(r => isNum(r[ti('Edge')]) && r[ti('Edge')] >= b2).length;
tile($('todayTiles'), 1, 'Games', D.games, 'On the ESPN schedule', '');
tile($('todayTiles'), 2, 'Edges ' + b2 + '+', nBig, nStrong + ' at ' + b1 + '+ points', 'blue');
tile($('todayTiles'), 3, 'With a line', T.rows.length, 'Priced by sportsbooks', '');
tile($('todayTiles'), 4, 'High confidence', T.rows.filter(r => r[ti('Conf.')] === 'High').length, T.rows.filter(r => r[ti('Conf.')] === 'Medium').length + ' Medium \u00b7 ' + T.rows.filter(r => r[ti('Conf.')] === 'Check').length + ' Check', 'black');
let lineTags = {};
const subTag = t => t && t !== 'DK' && t !== 'CONS';
function fmtToday(c, v, r) {
  if (v == null) return '';
  if (c === 'Line' && r) {
    const [tag, src] = lineTags[r[1]] || [];
    if (subTag(tag)) return el('span', null, [document.createTextNode(v), tagBtn(tag, src)]);
  }
  if (c === 'Edge') return chip(v.toFixed(1), v >= b2 ? 'hi' : v >= b1 ? 'md' : '');
  if (c === 'Conf.') return v ? chip(v === 'Check' ? 'Check' : v, v === 'High' ? 'hi' : v === 'Medium' ? 'md' : v === 'Check' ? 'L' : '') : '';
  if (c.indexOf('win') >= 0 || c === 'Cover %') return pct(v);
  if (c.indexOf('margin') >= 0 || c.indexOf('Best') === 0) return sgn(v);
  return null;
}
const MAIN = ['Time', 'Matchup', 'Line', 'Edge pick', 'Edge', 'Cover %', 'Conf.'];
const MORE = ['Proj away margin', 'Model away win', 'Market away win', 'Books', 'Best away', 'Best home'];
const short = v => v == null ? '' : String(v).replace(/ covers$/, '');
function todayRows() {
  const min = +$('edgeMin').value, q = $('todaySearch').value.trim().toLowerCase();
  return T.rows.filter(r => (min === 0 || (isNum(r[ti('Edge')]) && r[ti('Edge')] >= min)) &&
    (!q || (String(r[ti('Away')]) + ' ' + String(r[ti('Home')])).toLowerCase().includes(q)));
}
function drawToday() {
  const rows = todayRows(), more = $('todayMore').checked;
  const cols = MAIN.concat(more ? MORE : []);
  const data = rows.map(r => { const d = cols.map(c => c === 'Matchup' ? r[ti('Away')] + ' @ ' + r[ti('Home')]
    : c === 'Model pick' ? short(r[ti(c)]) : r[ti(c)]); d._start = r[ti('Start')] || ''; return d; });
  lineTags = {}; rows.forEach(r => { lineTags[r[ti('Away')] + ' @ ' + r[ti('Home')]] = [r[ti('Line tag')], r[ti('Line source')]]; });
  table($('todayTbl'), cols, data, fmtToday, (D.tips || {}).today, (c, r) => c === 'Time' ? r._start : undefined);
  // phone: one card per game
  const host = $('todayCards'); host.replaceChildren();
  if (!rows.length) { host.append(el('div', {className: 'empty', textContent: 'Nothing to show yet.'})); return; }
  rows.forEach(r => {
    const kv = (k, v) => el('div', null, [el('div', {className: 'k', textContent: k}), (() => { const d = el('div', {className: 'v'}); if (v instanceof Node) d.append(v); else d.textContent = v == null ? '' : v; return d; })()]);
    const edge = r[ti('Edge')], conf = r[ti('Conf.')];
    host.append(el('div', {className: 'gcard'}, [
      el('div', {className: 'row1'}, [el('div', {className: 'teams', textContent: r[ti('Away')] + ' @ ' + r[ti('Home')]}), el('div', {className: 'meta'}, [document.createTextNode((r[ti('Time')] || '') + '  ' + (r[ti('Line')] || '')), ...(subTag(r[ti('Line tag')]) ? [tagBtn(r[ti('Line tag')], r[ti('Line source')])] : [])])]),
      el('div', {className: 'grid'}, [
        kv('Edge pick', r[ti('Edge pick')]),
        kv('Edge', isNum(edge) ? chip(edge.toFixed(1), edge >= b2 ? 'hi' : edge >= b1 ? 'md' : '') : ''),
        kv('Cover %', pct(r[ti('Cover %')])),
        kv('Confidence', conf ? chip(conf, conf === 'High' ? 'hi' : conf === 'Medium' ? 'md' : conf === 'Check' ? 'L' : '') : ''),
        kv('Proj away margin', sgn(r[ti('Proj away margin')])),
        kv('Away win: model / market', pct(r[ti('Model away win')]) + (isNum(r[ti('Market away win')]) ? ' / ' + pct(r[ti('Market away win')]) : ''))
      ])]));
  });
}
$('todayMore').onchange = drawToday;
(D.confKey || []).forEach(k => {
  const cls = k.tier === 'High' ? 'hi' : k.tier === 'Medium' ? 'md' : k.tier === 'Check' ? 'L' : '';
  $('confKey').append(el('div', null, [
    el('div', {className: 'kt'}, [chip(k.tier, cls), el('span', {className: 'kr', textContent: k.range})]),
    el('p', {textContent: k.text})]));
});
if (D.ratingsSource) $('ratingsSrc').textContent = 'Ratings: ' + D.ratingsSource + '.';
$('edgeMin').onchange = drawToday; $('todaySearch').oninput = drawToday; drawToday();

// ---------- 02 Success rate
const R = D.record, ri = n => R.cols.indexOf(n);
const recRow = label => R.rows.find(r => String(r[0]).trim() === label);
const e = recRow('Sportsbook Edge (all)') || [], m = recRow('Market Edge (all, straight up)') || [];
tile($('rateTiles'), 1, 'Edge record', e.length ? e[ri('W')] + '-' + e[ri('L')] + '-' + e[ri('P')] : '0-0-0', 'W-L-P against the spread', '');
tile($('rateTiles'), 2, 'Edge success', pct(e[ri('Success Rate')]) || 'n/a', 'Break-even is 52.4%', 'blue');
tile($('rateTiles'), 3, 'Edge units', isNum(e[ri('Units')]) ? (e[ri('Units')] > 0 ? '+' : '') + e[ri('Units')].toFixed(2) : 'n/a', '1 unit per pick at -110', '');
const ME = D.marketEval || {};
const l7 = recRow('Last 7 days') || [];
tile($('rateTiles'), 4, 'Last 7 days', l7.length ? l7[ri('W')] + '-' + l7[ri('L')] + '-' + l7[ri('P')] : '0-0-0',
  (isNum(l7[ri('Success Rate')]) ? pct(l7[ri('Success Rate')]) + ' \u00b7 ' : '') + 'Edge picks against the spread', 'black');
const units = v => isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(2) : '';
const recOpen = new Set(); let recAll = false;
const REC_TIPS = {
  'W': 'Wins.', 'L': 'Losses.', 'P': 'Pushes (exactly on the line), counted as no bet.',
  'Success Rate': 'Wins / (wins + losses). Break-even against the spread at -110 is 52.4%.',
  'Units': 'Profit or loss betting 1 unit per pick. At -110 a win is +0.91, a loss -1, a push 0. Market picks are paid at the market price.',
  'Rate': 'Wins / (wins + losses). Break-even is 52.4%.'
};
function recGroups() {
  const groups = []; let cur = null;
  R.rows.forEach(r => { const lbl = String(r[0]); if (lbl.startsWith('  ')) { if (cur) cur.kids.push(r); } else { cur = {row: r, kids: []}; groups.push(cur); } });
  return groups;
}
function drawRecord() {
  const host = $('recordTbl'); host.replaceChildren();
  const mob = mobile();
  const cols = mob ? ['Pick type', 'W-L-P', 'Rate', 'Units'] : ['', 'Pick type', 'W', 'L', 'P', 'Picks', 'Success Rate', 'Units'];
  const vals = r => mob ? [r[ri('W')] + '-' + r[ri('L')] + '-' + r[ri('P')], pct(r[ri('Success Rate')]), units(r[ri('Units')])]
                        : [r[ri('W')], r[ri('L')], r[ri('P')], r[ri('Picks')], pct(r[ri('Success Rate')]), units(r[ri('Units')])];
  const t = el('table'), tb = el('tbody'), hr = el('tr');
  cols.forEach((c, i) => { const th = el('th', {textContent: c, className: i >= (mob ? 1 : 2) ? 'n' : ''}); if (REC_TIPS[c]) th.append(infoBtn(c, REC_TIPS[c])); hr.append(th); });
  t.append(el('thead', null, [hr]), tb); host.append(t);
  recGroups().forEach((g, gi) => {
    const label = String(g.row[0]).trim(), open = recAll || recOpen.has(label), has = g.kids.length > 0;
    const tr = el('tr', {className: 'parent' + (gi % 2 ? ' alt' : '')});
    const name = el('span', null, [document.createTextNode((mob && has ? (open ? '− ' : '+ ') : '') + label)]);
    if (!mob) tr.append(el('td', {className: 'tog', textContent: has ? (open ? '−' : '+') : ''}));
    tr.append(el('td', null, [el('b', null, [name])]));
    vals(g.row).forEach(v => tr.append(el('td', {className: 'n', textContent: v})));
    if (has) tr.onclick = () => { if (recOpen.has(label)) recOpen.delete(label); else recOpen.add(label); recAll = false; drawRecord(); };
    tb.append(tr);
    if (open) g.kids.forEach(k => {
      const c = el('tr', {className: 'child'});
      if (!mob) c.append(el('td'));
      c.append(el('td', {className: 'bk', textContent: String(k[0]).trim()}));
      vals(k).forEach(v => c.append(el('td', {className: 'n', textContent: v})));
      tb.append(c);
    });
  });
}
$('recExpand').onclick = () => { recAll = !recAll; if (!recAll) recOpen.clear(); $('recExpand').textContent = recAll ? 'Collapse all' : 'Expand all'; drawRecord(); };
function drawMarketEval() {
  const host = $('mktEval'); host.replaceChildren();
  if (!ME.picks) { host.append(el('p', {className: 'sub', textContent: 'Appears once some Market picks have been graded.'})); return; }
  const better = ME.brier_model <= ME.brier_market;
  host.append(el('p', {className: 'sub', style: 'margin-top:0', textContent:
    'A Market pick is a game where the model gave a team at least 5 points more win chance than Kalshi, Polymarket or the books. Those are usually underdogs, so they lose most of the time even when the model is right; a 1-17 record can still be fine if the model expected about 1 win. The fair test is whose probabilities were closer to what happened. The Brier score is the average squared gap between the probability and the result (1 = win, 0 = loss): lower is better.'}));
  const rows = [
    ['Games compared', ME.picks, ''], ['Actual wins', ME.wins, ''],
    ['Wins the model expected', ME.expected_model.toFixed(1), 'Sum of model win %'],
    ['Wins the market expected', ME.expected_market.toFixed(1), 'Sum of market win %'],
    ['Brier score, model', ME.brier_model.toFixed(4), better ? 'Lower: model was closer' : ''],
    ['Brier score, market', ME.brier_market.toFixed(4), better ? '' : 'Lower: market was closer']];
  table(host.appendChild(el('div', {className: 'tbl'})), ['Measure', 'Value', 'Note'], rows);
  host.append(el('p', {className: 'sub', textContent: better
    ? 'So far the model’s odds were closer than the market’s on these games.'
    : 'So far the market’s odds were closer than the model’s on these games, so the model is overrating these teams. Treat Market picks with caution until this flips.'}));
}
drawMarketEval();
(function () {
  const C = D.clv || {}, host = $('clvTiles');
  tile(host, 1, 'Beat the close', isNum(C.beat_rate) ? pct(C.beat_rate) : 'n/a', C.moved ? C.beat + ' of ' + C.moved + ' picks where the line moved' : 'Needs finished games', 'blue');
  tile(host, 2, 'Average CLV', isNum(C.avg_clv) ? (C.avg_clv > 0 ? '+' : '') + C.avg_clv.toFixed(2) + ' pts' : 'n/a', 'Opening minus closing number, pick side', '');
  tile(host, 3, 'Games tracked', C.games || 0, 'Finished games in the research dataset', '');
})();
function drawTrend() {
  const tc = D.trend.cols, t = n => tc.indexOf(n), rows = D.trend.rows.slice().reverse();
  if (mobile()) {
    const data = rows.map(r => [r[t('Date')], r[t('W')] + '-' + r[t('L')] + '-' + r[t('P')], r[t('Day Rate')],
      r[t('Cumulative W')] + '-' + r[t('Cumulative L')] + (isNum(r[t('Cumulative Rate')]) ? ' (' + pct(r[t('Cumulative Rate')]) + ')' : '')]);
    table($('trendTbl'), ['Date', 'W-L-P', 'Day', 'Cumulative'], data, (c, v) => (c === 'Day' ? pct(v) : c === 'Date' ? String(v).slice(5) : null));
    return;
  }
  table($('trendTbl'), tc, rows, (c, v) => (c.indexOf('Rate') >= 0 ? pct(v) : null));
}
drawRecord(); drawTrend();

function drawChart() {
  const host = $('chart'); host.replaceChildren();
  const tc = D.trend.cols, rows = D.trend.rows, di = tc.indexOf('Date'), ci = tc.indexOf('Cumulative Rate'), wi = tc.indexOf('Cumulative W'), li = tc.indexOf('Cumulative L');
  const pts = rows.filter(r => isNum(r[ci]));
  if (pts.length < 2) { host.append(el('div', {className: 'empty', textContent: 'The chart appears after two days of graded edge picks.'})); return; }
  const W = Math.max(host.clientWidth || 640, 300), H = 240, pad = {l: 44, r: 14, t: 12, b: 28};
  const cs = getComputedStyle(document.documentElement), col = n => cs.getPropertyValue(n).trim();
  const ys = pts.map(p => p[ci]).concat([0.524]);
  const lo = Math.max(0, Math.floor((Math.min(...ys) - 0.05) * 10) / 10), hi = Math.min(1, Math.ceil((Math.max(...ys) + 0.05) * 10) / 10);
  const x = i => pad.l + i * (W - pad.l - pad.r) / (pts.length - 1), y = v => pad.t + (hi - v) * (H - pad.t - pad.b) / (hi - lo);
  const NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg');
  s.setAttribute('viewBox', '0 0 ' + W + ' ' + H); s.setAttribute('role', 'img'); s.setAttribute('aria-label', 'Cumulative success rate of edge picks by day');
  const add = (tag, at) => { const n = document.createElementNS(NS, tag); for (const k in at) n.setAttribute(k, at[k]); s.append(n); return n; };
  for (let v = lo; v <= hi + 1e-9; v += 0.1) {
    add('line', {x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: col('--grid'), 'stroke-width': 1});
    add('text', {x: pad.l - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: col('--muted')}).textContent = Math.round(v * 100) + '%';
  }
  add('line', {x1: pad.l, x2: W - pad.r, y1: y(0.524), y2: y(0.524), stroke: col('--ink-2'), 'stroke-width': 1, 'stroke-dasharray': '4 4'});
  const step = Math.ceil(pts.length / 6);
  pts.forEach((p, i) => { if (i % step === 0 || i === pts.length - 1) add('text', {x: x(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: col('--muted')}).textContent = String(p[di]).slice(5); });
  add('path', {d: pts.map((p, i) => (i ? 'L' : 'M') + x(i) + ' ' + y(p[ci])).join(' '), fill: 'none', stroke: col('--blue'), 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'});
  const last = pts.length - 1;
  add('circle', {cx: x(last), cy: y(pts[last][ci]), r: 4, fill: col('--blue'), stroke: col('--paper'), 'stroke-width': 2});
  const hair = add('line', {y1: pad.t, y2: H - pad.b, stroke: col('--ink-2'), 'stroke-width': 1, visibility: 'hidden'});
  const dot = add('circle', {r: 4, fill: col('--blue'), stroke: col('--paper'), 'stroke-width': 2, visibility: 'hidden'});
  const tip = el('div', {className: 'tip'}); host.append(s, tip);
  const hit = add('rect', {x: pad.l, y: 0, width: W - pad.l - pad.r, height: H, fill: 'transparent'});
  const show = ev => {
    const b = s.getBoundingClientRect(), px = (ev.clientX - b.left) * W / b.width;
    const i = Math.max(0, Math.min(last, Math.round((px - pad.l) / ((W - pad.l - pad.r) / last)))), p = pts[i];
    hair.setAttribute('x1', x(i)); hair.setAttribute('x2', x(i)); hair.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', x(i)); dot.setAttribute('cy', y(p[ci])); dot.setAttribute('visibility', 'visible');
    tip.replaceChildren(el('div', {textContent: p[di]}), el('div', {textContent: 'Cumulative ' + pct(p[ci]) + ' (' + p[wi] + '-' + p[li] + ')'}));
    tip.style.display = 'block';
    tip.style.left = Math.min(x(i) * b.width / W + 10, b.width - tip.offsetWidth - 4) + 'px'; tip.style.top = '8px';
  };
  hit.addEventListener('pointermove', show); hit.addEventListener('pointerdown', show);
  hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; hair.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); });
}
addEventListener('resize', () => { if (!$('rate').hidden) drawChart(); if (!$('portfolio').hidden && pfReady) drawPortfolio(); });
if (!$('rate').hidden) drawChart();


// ---------- 04 Portfolio ($ per Edge pick at -110)
const PF = D.portfolio || {bets: [], stake: 100, win: 90.91};
const SECTIONS = [
  {id: 'Overall', color: '--s1', test: b => true},
  {id: 'High', color: '--s2', test: b => b.conf === 'High'},
  {id: 'Medium', color: '--s3', test: b => b.conf === 'Medium'},
  {id: 'Low', color: '--s4', test: b => b.conf === 'Low'},
  {id: 'Check', color: '--s5', test: b => b.conf === 'Check'}];
const money = v => isNum(v) ? (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '';
const smoney = v => isNum(v) ? (v > 0 ? '+' : '') + money(v) : '';
let pfShow = new Set((store.get('pfShow', 'Overall,High,Medium,Check')).split(',').filter(Boolean));
const pfOpen = new Set();
const pfLimit = {};
const pfRes = {};
$('pfRule').textContent = money(PF.stake) + ' on every Edge pick at ' + (PF.price || -110) + ' (a win pays ' + money(PF.win) + ')';
SECTIONS.forEach(sc => {
  const b = el('button', {type: 'button', textContent: sc.id}); b.dataset.s = sc.id; b.setAttribute('aria-pressed', pfShow.has(sc.id));
  b.onclick = () => { if (pfShow.has(sc.id)) pfShow.delete(sc.id); else pfShow.add(sc.id); b.setAttribute('aria-pressed', pfShow.has(sc.id)); store.set('pfShow', [...pfShow].join(',')); drawPortfolio(); };
  $('pfSections').append(b);
});
$('pfRange').onchange = () => drawPortfolio();
function pfBets() {
  const r = $('pfRange').value;
  if (r === 'all') return PF.bets;
  const cut = new Date(Date.now() - (+r) * 864e5).toISOString().slice(0, 10);
  return PF.bets.filter(b => b.date >= cut);
}
function pfStats(bets) {
  const g = bets.filter(b => b.result), w = g.filter(b => b.result === 'W').length, l = g.filter(b => b.result === 'L').length, pu = g.filter(b => b.result === 'P').length;
  const net = g.reduce((a, b) => a + (b.pl || 0), 0), wag = (w + l) * PF.stake;
  return {n: g.length, pending: bets.length - g.length, w, l, p: pu, net, wag, roi: wag ? net / wag : null, rate: (w + l) ? w / (w + l) : null};
}
function drawPortfolio() {
  const bets = pfBets(), cs = getComputedStyle(document.documentElement), col = n => cs.getPropertyValue(n).trim();
  // tiles (overall)
  const o = pfStats(bets), th = $('pfTiles'); th.replaceChildren();
  tile(th, 1, 'Net profit', smoney(o.net) || '$0.00', o.n + ' graded bets', o.net >= 0 ? 'blue' : 'black');
  tile(th, 2, 'Return on money bet', o.roi == null ? 'n/a' : (o.roi * 100).toFixed(1) + '%', 'Net profit / amount risked', '');
  tile(th, 3, 'Record', o.w + '-' + o.l + '-' + o.p, o.rate == null ? 'No graded bets yet' : pct(o.rate) + ' wins (52.4% to break even)', '');
  tile(th, 4, 'Pending', o.pending, 'Bets on games not final yet', '');
  // chart: cumulative profit by date for each visible section
  const host = $('pfChart'); host.replaceChildren(); $('pfLegend').replaceChildren();
  const graded = bets.filter(b => b.result);
  const dates = [...new Set(graded.map(b => b.date))].sort();
  const vis = SECTIONS.filter(sc => pfShow.has(sc.id));
  if (dates.length < 2 || !vis.length) {
    host.append(el('div', {className: 'empty', textContent: !vis.length ? 'Pick at least one section above.' : 'The chart appears after two days of graded bets.'}));
  } else {
    const series = vis.map(sc => {
      let run = 0; const byDate = {};
      graded.filter(sc.test).forEach(b => { byDate[b.date] = (byDate[b.date] || 0) + (b.pl || 0); });
      return {sc, vals: dates.map(d => (run += (byDate[d] || 0)))};
    });
    const all = series.flatMap(x => x.vals).concat([0]);
    let lo = Math.min(...all), hi = Math.max(...all);
    const raw = Math.max(100, (hi - lo) / 4), mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const tick = [1, 2, 2.5, 5, 10].map(m => m * mag).find(t => t >= raw);
    lo = Math.floor(lo / tick) * tick; hi = Math.ceil(hi / tick) * tick; if (hi === lo) hi = lo + tick;
    const W = Math.max(host.clientWidth || 640, 300), H = 260, pad = {l: 62, r: mobile() ? 14 : 70, t: 12, b: 28};
    const x = i => pad.l + i * (W - pad.l - pad.r) / (dates.length - 1), y = v => pad.t + (hi - v) * (H - pad.t - pad.b) / (hi - lo);
    const NS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Cumulative profit by day');
    const add = (tag, at) => { const n = document.createElementNS(NS, tag); for (const k in at) n.setAttribute(k, at[k]); svg.append(n); return n; };
    for (let v = lo; v <= hi + 1e-6; v += tick) {
      add('line', {x1: pad.l, x2: W - pad.r, y1: y(v), y2: y(v), stroke: col('--grid'), 'stroke-width': 1});
      add('text', {x: pad.l - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: col('--muted')}).textContent = smoney(Math.round(v)).replace('.00', ''); }
    add('line', {x1: pad.l, x2: W - pad.r, y1: y(0), y2: y(0), stroke: col('--ink-2'), 'stroke-width': 1});
    const st = Math.ceil(dates.length / 6);
    dates.forEach((d, i) => { if (i % st === 0 || i === dates.length - 1) add('text', {x: x(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: col('--muted')}).textContent = d.slice(5); });
    series.forEach(sr => {
      const c = col(sr.sc.color);
      add('path', {d: sr.vals.map((v, i) => (i ? 'L' : 'M') + x(i) + ' ' + y(v)).join(' '), fill: 'none', stroke: c, 'stroke-width': sr.sc.id === 'Overall' ? 2.5 : 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'});
      const last = sr.vals.length - 1;
      add('circle', {cx: x(last), cy: y(sr.vals[last]), r: 4, fill: c, stroke: col('--paper'), 'stroke-width': 2});
      sr.ly = y(sr.vals[last]);
      $('pfLegend').append(el('span', {className: 'li'}, [el('i', {style: 'background:' + c}), document.createTextNode(sr.sc.id + ' ' + smoney(sr.vals[last]))]));
    });
    if (!mobile()) {   // end-of-line labels, nudged apart so they never overlap
      const labs = series.slice().sort((a, b) => a.ly - b.ly);
      for (let k = 1; k < labs.length; k++) if (labs[k].ly - labs[k - 1].ly < 13) labs[k].ly = labs[k - 1].ly + 13;
      labs.forEach(sr => { add('text', {x: W - pad.r + 8, y: sr.ly + 4, 'font-size': 11, 'font-weight': 700, fill: col('--ink')}).textContent = sr.sc.id; });
    }
    const hair = add('line', {y1: pad.t, y2: H - pad.b, stroke: col('--ink-2'), 'stroke-width': 1, visibility: 'hidden'});
    const tip = el('div', {className: 'tip'}); host.append(svg, tip);
    const hit = add('rect', {x: pad.l, y: 0, width: W - pad.l - pad.r, height: H, fill: 'transparent'});
    const show = ev => {
      const b = svg.getBoundingClientRect(), px = (ev.clientX - b.left) * W / b.width, last = dates.length - 1;
      const i = Math.max(0, Math.min(last, Math.round((px - pad.l) / ((W - pad.l - pad.r) / last))));
      hair.setAttribute('x1', x(i)); hair.setAttribute('x2', x(i)); hair.setAttribute('visibility', 'visible');
      tip.replaceChildren(el('div', {textContent: dates[i]}), ...series.map(sr => el('div', {textContent: sr.sc.id + ': ' + smoney(sr.vals[i])})));
      tip.style.display = 'block';
      tip.style.left = Math.min(x(i) * b.width / W + 10, b.width - tip.offsetWidth - 4) + 'px'; tip.style.top = '8px';
    };
    hit.addEventListener('pointermove', show); hit.addEventListener('pointerdown', show);
    hit.addEventListener('pointerleave', () => { tip.style.display = 'none'; hair.setAttribute('visibility', 'hidden'); });
  }
  // section cards
  const cards = $('pfCards'); cards.replaceChildren();
  SECTIONS.filter(sc => pfShow.has(sc.id)).forEach(sc => {
    const sb = bets.filter(sc.test), stt = pfStats(sb), isOpen = pfOpen.has(sc.id);
    const card = el('div', {className: 'card pfsec'});
    const head = el('div', {className: 'card-h'}, [
      el('h2', null, [el('span', {className: 'sw', style: 'background:' + col(sc.color)}), document.createTextNode(sc.id === 'Overall' ? 'Overall' : sc.id + ' confidence')]),
      el('span', {className: 'lbl muted', textContent: isOpen ? 'Hide bets −' : 'Show bets +'})]);
    head.onclick = () => { if (pfOpen.has(sc.id)) pfOpen.delete(sc.id); else pfOpen.add(sc.id); drawPortfolio(); };
    const sum = el('div', {className: 'pfsum'}, [
      el('span', null, ['Net', el('b', {className: stt.net > 0 ? 'pos' : stt.net < 0 ? 'neg' : '', textContent: smoney(stt.net) || '$0.00'})]),
      el('span', null, ['Return', el('b', {textContent: stt.roi == null ? 'n/a' : (stt.roi * 100).toFixed(1) + '%'})]),
      el('span', null, ['Record', el('b', {textContent: stt.w + '-' + stt.l + '-' + stt.p})]),
      el('span', null, ['Win rate', el('b', {textContent: stt.rate == null ? 'n/a' : pct(stt.rate)})]),
      el('span', null, ['Risked', el('b', {textContent: money(stt.wag)})]),
      el('span', null, ['Pending', el('b', {textContent: stt.pending})])]);
    card.append(head, sum);
    if (isOpen) {
      const ctr = el('div', {className: 'controls'});
      const sel = el('select', {'aria-label': 'Result'}); [['', 'All results'], ['W', 'Wins'], ['L', 'Losses'], ['P', 'Pushes'], ['pending', 'Pending']].forEach(([v, t]) => sel.append(el('option', {value: v, textContent: t})));
      sel.value = pfRes[sc.id] || ''; sel.onchange = () => { pfRes[sc.id] = sel.value; drawPortfolio(); };
      ctr.append(sel); card.append(ctr);
      const rf = pfRes[sc.id] || '';
      let run = 0; const rows = [];
      sb.forEach(b => { if (b.result) run += b.pl || 0; rows.push({b, run}); });
      const allShown = rows.filter(x => !rf || (rf === 'pending' ? !x.b.result : x.b.result === rf)).reverse();
      const lim = pfLimit[sc.id] || 25, shown = allShown.slice(0, lim);
      const mob = mobile();
      const cols = mob ? ['Date', 'Pick', 'Result', 'Profit'] : ['Date', 'Matchup', 'Pick', 'Conf.', 'Final', 'Result', 'Profit', 'Running total'];
      const data = shown.map(({b, run}) => {
        const pick = b.team + ' ' + line(b.line);
        return mob ? [String(b.date).slice(5), pick, b.result || 'Pending', b.result ? b.pl : null]
          : [b.date, b.away + ' @ ' + b.home, pick, b.conf, isNum(b.s1) && isNum(b.s2) ? Math.round(b.s1) + ' - ' + Math.round(b.s2) : '', b.result || 'Pending', b.result ? b.pl : null, b.result ? run : null];
      });
      const tb = el('div', {className: 'tbl'}); card.append(tb);
      table(tb, cols, data, (c, v) => {
        if (c === 'Result') return v === 'Pending' ? chip('Pending') : chip(v, v === 'W' ? 'W' : v === 'L' ? 'L' : '');
        if (c === 'Profit' || c === 'Running total') return isNum(v) ? el('span', {className: v > 0 ? 'pos' : v < 0 ? 'neg' : '', textContent: smoney(v)}) : '';
        if (c === 'Conf.') return v ? chip(v, v === 'High' ? 'hi' : v === 'Medium' ? 'md' : v === 'Check' ? 'L' : '') : '';
        return null;
      });
      if (allShown.length > lim) {
        const more = el('button', {type: 'button', className: 'btn', textContent: 'Show ' + Math.min(25, allShown.length - lim) + ' more (' + (allShown.length - lim) + ' left)', style: 'margin-top:10px'});
        more.onclick = () => { pfLimit[sc.id] = lim + 25; drawPortfolio(); };
        card.append(more);
      }
    }
    cards.append(card);
  });
}
pfReady = true;
drawPortfolio();

// ---------- 03 History (grouped by game)
const HG = D.history || [];
const histOpen = new Set(); let histAll = false;
const resChip = r => r ? chip(r, r === 'W' ? 'W' : r === 'L' ? 'L' : '') : chip('Pending');
const primary = g => g.picks.find(p => p.type === 'Edge') || g.picks[0] || {};
const HH = ['', 'Date', 'Away', 'Home', 'Final', 'Edge pick', 'Edge', 'Conf.', 'Result'];
const HT = {
  'Final': 'Final score, away first, from ESPN. Blank until the game is final.',
  'Edge pick': 'The side the model liked against the line when the pick was logged, with that line.',
  'Edge': 'Points of disagreement between the model and the line when logged.',
  'Result': 'Edge pick result against the spread: W, L, P (push). Pending until the game is final.',
  'Conf.': 'Confidence of the Edge pick (current rules).'
};
function pickDetail(x) {
  if (x.type === 'Edge') return (isNum(x.edge) ? x.edge.toFixed(1) + ' pt edge' : '') + (isNum(x.cover) ? ', ' + pct(x.cover) + ' to cover' : '') + (x.conf ? ' (' + x.conf + ')' : '');
  if (x.type === 'Model') return 'Stronger team by efficiency';
  if (x.type === 'Market') return 'Model ' + pct(x.modelp) + ' vs market ' + pct(x.mprob);
  return '';
}
function histMobile(host, games) {
  const list = el('div', {className: 'mlist'});
  games.forEach((g, gi) => {
    const id = g.date + '|' + g.gid, open = histAll || histOpen.has(id), p = primary(g);
    const others = g.picks.filter(x => x !== p);
    const card = el('div', {className: 'mi tap' + (gi % 2 ? ' alt' : '')});
    const score = isNum(g.s1) && isNum(g.s2) ? Math.round(g.s1) + ' - ' + Math.round(g.s2) : 'Not final';
    card.append(
      el('div', {className: 'mt'}, [el('b', {textContent: g.away + ' @ ' + g.home}), el('span', {className: 'ms', textContent: String(g.date).slice(5)})]),
      el('div', {className: 'mg'}, [
        kv2('Edge pick', p.team ? p.team + ' ' + line(p.line) : ''), kv2('Result', resChip(p.result)),
        kv2('Final', score), kv2('Edge', p.type === 'Edge' && isNum(p.edge) ? p.edge.toFixed(1) + ' pts' + (p.conf ? ' \u00b7 ' + p.conf : '') : '')]));

    if (open) {
      const x = el('div', {className: 'mx'});
      g.picks.forEach(pk => { const supp = pk.type !== 'Edge'; x.append(el('div', null, [
        el('div', {className: 'mt'}, [el(supp ? 'span' : 'b', {textContent: (pk.type === 'Market' ? 'Market: ' + pk.team + ' to win' : pk.type + ': ' + pk.team + ' ' + line(pk.line)) + (supp ? ' (supplemental)' : '')}),
          supp ? el('span', {className: 'muted', textContent: pk.result ? (pk.result === 'W' ? 'Won' : pk.result === 'L' ? 'Lost' : pk.result) : 'Pending'}) : resChip(pk.result)]),
        el('div', {className: 'psub', textContent: pickDetail(pk)})])); });
      card.append(x);
    } else if (g.picks.length > 1) card.append(el('div', {className: 'more', textContent: 'Tap for details'}));
    card.onclick = () => { if (histOpen.has(id)) histOpen.delete(id); else histOpen.add(id); histAll = false; drawHist(); };
    list.append(card);
  });
  host.append(list);
}
function drawHist() {
  const host = $('histTbl'); host.replaceChildren();
  const rf = $('histRes').value, q = $('histSearch').value.trim().toLowerCase();
  const games = HG.filter(g => {
    const p = primary(g);
    if (rf && (rf === 'pending' ? p.result : p.result !== rf)) return false;
    return !q || (g.date + ' ' + g.away + ' ' + g.home).toLowerCase().includes(q);
  });
  if (!games.length) { host.append(el('div', {className: 'empty', textContent: HG.length ? 'No games match.' : 'Nothing logged yet.'})); return; }
  if (mobile()) { histMobile(host, games); return; }
  const t = el('table'), tb = el('tbody'), hr = el('tr');
  HH.forEach(h => { const th = el('th', {textContent: h, className: h === 'Edge' ? 'n' : ''}); if (HT[h]) th.append(infoBtn(h, HT[h])); hr.append(th); });
  t.append(el('thead', null, [hr]), tb); host.append(t);
  games.forEach((g, gi) => {
    const id = g.date + '|' + g.gid, open = histAll || histOpen.has(id), p = primary(g);
    const others = g.picks.filter(x => x !== p);
    const tr = el('tr', {className: 'parent' + (gi % 2 ? ' alt' : '')});
    const td = (c, cls) => { const d = el('td', {className: cls || ''}); if (c instanceof Node) d.append(c); else d.textContent = c == null ? '' : c; return d; };
    const confChip = v => v ? chip(v, v === 'High' ? 'hi' : v === 'Medium' ? 'md' : v === 'Check' ? 'L' : '') : '';
    tr.append(td(g.picks.length > 1 ? (open ? '\u2212' : '+') : '', 'tog'), td(g.date), td(g.away), td(g.home),
      td(isNum(g.s1) && isNum(g.s2) ? Math.round(g.s1) + ' - ' + Math.round(g.s2) : ''),
      td(p.team ? p.team + ' ' + line(p.line) : ''), td(p.type === 'Edge' && isNum(p.edge) ? p.edge.toFixed(1) : '', 'n'),
      td(p.type === 'Edge' ? confChip(p.conf) : ''), td(resChip(p.result)));
    tr.setAttribute('aria-expanded', open);
    tr.onclick = () => { if (histOpen.has(id)) histOpen.delete(id); else histOpen.add(id); histAll = false; drawHist(); };
    tb.append(tr);
    if (!open) return;
    g.picks.forEach(x => {
      let detail = '';
      if (x.type === 'Edge') detail = (isNum(x.edge) ? x.edge.toFixed(1) + ' pt edge' : '') + (isNum(x.cover) ? ', ' + pct(x.cover) + ' to cover' : '') + (x.conf ? ' (' + x.conf + ')' : '');
      else if (x.type === 'Model') detail = 'Stronger team by efficiency';
      else if (x.type === 'Market') detail = 'Model ' + pct(x.modelp) + ' vs market ' + pct(x.mprob) + ' to win';
      const label = x.type === 'Market' ? x.team + ' to win' : x.team + ' ' + line(x.line);
      const supp = x.type !== 'Edge';
      const c = el('tr', {className: 'child'});
      c.append(el('td'), el('td', {className: 'bk', textContent: supp ? (x.type === 'Model' ? 'Model pick' : 'Market pick') + ' (supplemental)' : 'Edge pick'}),
        el('td', {textContent: label, colSpan: 3}), el('td', {textContent: detail, colSpan: 2}),
        supp ? el('td', {className: 'muted', textContent: x.result ? (x.result === 'W' ? 'Won' : x.result === 'L' ? 'Lost' : x.result) : 'Pending'}) : td(resChip(x.result)));
      tb.append(c);
    });
  });
}
$('histRes').onchange = drawHist; $('histSearch').oninput = drawHist;
$('histExpand').onclick = () => { histAll = !histAll; if (!histAll) histOpen.clear(); $('histExpand').textContent = histAll ? 'Collapse all' : 'Expand all'; drawHist(); };
drawHist();

// ---------- 04 Odds by book
const O = D.odds || [];
const sp = (pt, px) => { const f = el('span'); f.append(document.createTextNode(line(pt))); if (isNum(px)) f.append(el('span', {className: 'px', textContent: '(' + (px > 0 ? '+' : '') + Math.round(px) + ')'})); return f; };
const ml = v => isNum(v) ? (v > 0 ? '+' : '') + Math.round(v) : '';
const open = new Set(); let allOpen = false;
const BH = ['', 'Time', 'Away', 'Home', 'Away spread', 'Home spread', 'Away ML', 'Home ML', 'Books', 'Better books'];
const BT = {
  'Away spread': 'Points on the away team, price in parentheses. Game rows show DraftKings. If DraftKings has no line, the next biggest book is used and a small tag shows which (FD = FanDuel, MGM = BetMGM, CZR = Caesars).',
  'Home spread': 'Points on the home team, price in parentheses. Game rows show DraftKings. If DraftKings has no line, the next biggest book is used and a small tag shows which (FD = FanDuel, MGM = BetMGM, CZR = Caesars).',
  'Away ML': 'Moneyline for the away team to win outright (American odds).',
  'Home ML': 'Moneyline for the home team to win outright (American odds).',
  'Books': 'Other sportsbooks with a line on this game. Click the row to see them.',
  'Better books': 'How many other books beat the standard line (DraftKings, or the tagged substitute) on at least one number: more points on a side, the same points at a better price, or a better moneyline.'
};
function srcTag(node, dk) {
  if (!dk || dk.is_dk) return node;
  const w = el('span', null, [node, tagBtn(dk.tag, dk.source)]);
  return w;
}
function booksMobile(host, games) {
  const list = el('div', {className: 'mlist'});
  games.forEach((g, gi) => {
    const id = g.away + '|' + g.home + '|' + g.time, isOpen = allOpen || open.has(id), dk = g.dk || {};
    const card = el('div', {className: 'mi' + (g.books.length ? ' tap' : '') + (gi % 2 ? ' alt' : '')});
    card.append(
      el('div', {className: 'mt'}, [el('b', {textContent: g.away + ' @ ' + g.home}), el('span', {className: 'ms'}, [document.createTextNode(g.time), ...(g.closed ? [tagBtnText('CLOSED', 'Closing line', 'This game has started. These are the last pregame odds the model saw. Live in-game odds are not shown.')] : [])])]),
      ...(g.dk && !dk.is_dk ? [el('span', {className: 'srcnote', textContent: 'Line from ' + dk.source + ' (no DraftKings line)'})] : []),
      el('div', {className: 'mg'}, [
        kv2((dk.tag || 'DK') + ' ' + (g.awayAbbr || 'away'), g.dk ? sp(dk.away_pt, dk.away_px) : 'n/a'), kv2((dk.tag || 'DK') + ' ' + (g.homeAbbr || 'home'), g.dk ? sp(dk.home_pt, dk.home_px) : 'n/a'),
        kv2('Moneyline', (ml(dk.away_ml) || '-') + ' / ' + (ml(dk.home_ml) || '-')),
        kv2('Better books', g.better ? chip(g.better + (g.better === 1 ? ' book' : ' books'), 'hi') : (g.books.length ? 'None' : 'No other books'))]));
    if (isOpen && g.books.length) {
      const x = el('div', {className: 'mx'});
      x.append(el('div', {className: 'xr h'}, [el('span', {textContent: 'Book'}), el('span', {textContent: g.awayAbbr || 'Away'}), el('span', {textContent: g.homeAbbr || 'Home'})]));
      g.books.forEach(b => {
        const bt = b.better || {};
        const cell = (pt, px, mlv, okS, okM) => {
          const c = el('span', {className: okS || okM ? 'better' : ''});
          c.append(sp(pt, px)); if (isNum(mlv)) c.append(el('span', {className: 'psub', textContent: 'ML ' + ml(mlv)}));
          return c;
        };
        x.append(el('div', {className: 'xr'}, [el('span', {textContent: b.book}),
          cell(b.away_pt, b.away_px, b.away_ml, bt.away_sp, bt.away_ml), cell(b.home_pt, b.home_px, b.home_ml, bt.home_sp, bt.home_ml)]));
      });
      card.append(x);
    } else if (g.books.length) card.append(el('div', {className: 'more', textContent: 'Tap to compare ' + g.books.length + ' books'}));
    if (g.books.length) card.onclick = () => { if (open.has(id)) open.delete(id); else open.add(id); allOpen = false; drawBooks(); };
    list.append(card);
  });
  host.append(list);
}
function drawBooks() {
  const host = $('bookTbl'); host.replaceChildren();
  const q = $('bookSearch').value.trim().toLowerCase(), only = $('betterOnly').checked;
  const games = O.filter(g => (!q || (g.away + ' ' + g.home).toLowerCase().includes(q)) && (!only || g.better > 0));
  if (!games.length) { host.append(el('div', {className: 'empty', textContent: O.length ? 'No games match.' : 'No lines yet for this slate. Lines appear once sportsbooks post them; for games that have already started, the last pregame odds are shown once a run has saved them.'})); return; }
  if (mobile()) { booksMobile(host, games); return; }
  const t = el('table'), hr = el('tr'), tb = el('tbody');
  BH.forEach(h => { const th = el('th', {textContent: h, className: /spread|ML|Books|Better/.test(h) ? 'n' : ''}); if (BT[h]) th.append(infoBtn(h, BT[h])); hr.append(th); });
  t.append(el('thead', null, [hr]), tb); host.append(t);
  games.forEach((g, gi) => {
    const id = g.away + '|' + g.home + '|' + g.time, isOpen = allOpen || open.has(id), dk = g.dk || {};
    const tr = el('tr', {className: 'parent' + (gi % 2 ? ' alt' : '')});
    const cell = (c, cls) => { const td = el('td', {className: cls || ''}); if (c instanceof Node) td.append(c); else td.textContent = c == null ? '' : c; return td; };
    const timeCell = g.closed ? el('span', null, [document.createTextNode(g.time), tagBtnText('CLOSED', 'Closing line', 'This game has started. These are the last pregame odds the model saw' + (g.closedAt ? ' (saved ' + g.closedAt + ')' : '') + '. Live in-game odds are not shown.')]) : g.time;
    tr.append(cell(g.books.length ? (isOpen ? '−' : '+') : '', 'tog'), cell(timeCell), cell(g.away), cell(g.home),
      cell(g.dk ? srcTag(sp(dk.away_pt, dk.away_px), dk) : 'n/a', 'n dk'), cell(g.dk ? srcTag(sp(dk.home_pt, dk.home_px), dk) : 'n/a', 'n dk'),
      cell(ml(dk.away_ml), 'n dk'), cell(ml(dk.home_ml), 'n dk'), cell(g.books.length, 'n'),
      cell(g.better ? chip(g.better + (g.better === 1 ? ' book' : ' books'), 'hi') : '', 'n'));
    tr.title = g.dk ? 'Standard line: ' + dk.source + (dk.is_dk ? '' : ' (no DraftKings line)') + ', via ' + dk.via : 'No line for this game';
    tr.onclick = () => { if (open.has(id)) open.delete(id); else open.add(id); allOpen = false; drawBooks(); };
    tb.append(tr);
    if (!isOpen) return;
    g.books.forEach(b => {
      const r = el('tr', {className: 'child'}), bt = b.better || {};
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

// ---------- 05 Power rankings
const P = D.power || {cols: [], rows: []}, pi = n => P.cols.indexOf(n);
$('powerSrc').textContent = P.source ? 'Source: ' + P.source : '';
(function () {
  const note = el('p', {className: 'sub', style: 'margin:0 0 10px'});
  note.textContent = P.ref ? 'Change = places moved since the ratings saved on ' + P.ref + '. Ratings update every run as games finish.'
    : 'Change fills in once ratings from an earlier day have been saved (' + (P.files || 0) + ' daily ratings file(s) saved so far).';
  $('powerTbl').before(note);
})();
[...new Set(P.rows.map(r => r[pi('Conf')]).filter(Boolean))].sort().forEach(c => $('powerConf').append(el('option', {value: c, textContent: c})));
const MQP = matchMedia('(max-width: 960px)');
MQP.addEventListener('change', () => drawPower());
function drawPower() {
  const cf = $('powerConf').value, q = $('powerSearch').value.trim().toLowerCase();
  const rows = P.rows.filter(r => (!cf || r[pi('Conf')] === cf) && (!q || String(r[pi('Team')]).toLowerCase().includes(q)));
  if (mobile() || MQP.matches) {
    const info = {};
    rows.forEach(r => { info[r[pi('Team')]] = r; });
    const data = rows.map(r => [r[pi('Rk')], r[pi('Team')], r[pi('Net')], r[pi('Change')]]);
    const f1 = v => isNum(v) ? v.toFixed(1) : '';
    table($('powerTbl'), ['Rk', 'Team', 'Net', 'Change'], data, (c, v) => {
      if (c === 'Team') {
        const r = info[v] || [];
        const sub = [r[pi('Conf')], r[pi('Record')], 'O ' + f1(r[pi('Adj O')]) + ' (' + r[pi('O Rk')] + ')', 'D ' + f1(r[pi('Adj D')]) + ' (' + r[pi('D Rk')] + ')', 'Tempo ' + f1(r[pi('Tempo')]), $('powerEspn').checked && pi('ESPN Rk') >= 0 && isNum(r[pi('ESPN Rk')]) ? 'ESPN #' + Math.round(r[pi('ESPN Rk')]) : ''].filter(Boolean).join(' · ');
        return el('span', null, [el('b', {textContent: v}), el('span', {className: 'psub', textContent: sub})]);
      }
      if (c === 'Net') return isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(1) : '';
      if (c === 'Change') { if (!isNum(v)) return ''; if (v === 0) return '0'; return el('span', {className: v > 0 ? 'up' : 'down', textContent: (v > 0 ? '\u25B2 ' : '\u25BC ') + Math.abs(v)}); }
      return null;
    }, (D.tips || {}).power);
    return;
  }
  const showEspn = $('powerEspn').checked && pi('ESPN Rk') >= 0;
  const cols = ['Rk', 'Team', 'Conf', 'Record', 'Net', 'Adj O', 'Adj D', 'Tempo', 'Change'].concat(showEspn ? ['ESPN Rk', 'vs ESPN'] : []);
  const rk = {'Adj O': 'O Rk', 'Adj D': 'D Rk', 'Tempo': 'Tempo Rk'};
  const data = rows.map(r => { const d = cols.map(c => r[pi(c)]); d._r = r; return d; });
  table($('powerTbl'), cols, data, (c, v, d) => {
    if (c === 'Net') return isNum(v) ? (v > 0 ? '+' : '') + v.toFixed(1) : '';
    if (rk[c]) {   // value with its national rank in small type
      if (!isNum(v)) return '';
      const rank = d && d._r ? d._r[pi(rk[c])] : null;
      return el('span', null, [document.createTextNode(v.toFixed(1)), ...(isNum(rank) ? [el('span', {className: 'px', textContent: '(' + rank + ')'})] : [])]);
    }
    if (c === 'ESPN Rk') return isNum(v) ? String(Math.round(v)) : '';
    if (c === 'vs ESPN') { if (!isNum(v)) return ''; if (v === 0) return '0'; return el('span', {className: v > 0 ? 'up' : 'down', textContent: (v > 0 ? '+' : '') + Math.round(v)}); }
    if (c === 'Change') { if (!isNum(v)) return ''; if (v === 0) return '0'; return el('span', {className: v > 0 ? 'up' : 'down', textContent: (v > 0 ? '▲ ' : '▼ ') + Math.abs(v)}); }
    return null;
  }, Object.assign({}, (D.tips || {}).power, {
    'Adj O': 'Points scored per 100 possessions, adjusted for opponent and venue. National rank in parentheses.',
    'Adj D': 'Points allowed per 100 possessions, adjusted for opponent and venue (lower is better). National rank in parentheses.',
    'Tempo': 'Possessions per 40 minutes. Rank (1 = fastest) in parentheses.'}));
}
$('powerEspn').checked = store.get('powerEspn', 'off') === 'on';
$('powerEspn').onchange = e => { store.set('powerEspn', e.target.checked ? 'on' : 'off'); drawPower(); };
$('powerConf').onchange = drawPower; $('powerSearch').oninput = drawPower; drawPower();
(function () {
  const E = D.espnCompare || {};
  $('espnAgree').textContent = isNum(E.corr)
    ? 'Agreement with ESPN’s current BPI today: ' + E.corr.toFixed(2) + ' (1.00 = the same order for all ' + E.n + ' teams). On average the two rankings are ' + (isNum(E.mad) ? E.mad.toFixed(1) : '?') + ' places apart.'
    : 'ESPN’s current BPI was not available on the last run, so there is nothing to compare yet.';
  const dh = $('espnDiff');
  if (E.higher && E.higher.length) {
    const list = (title, arr) => el('div', null, [el('div', {className: 'lbl muted', textContent: title}),
      el('div', {className: 'sub', textContent: arr.map(x => x.team + ' (' + x.rk + ' here, ' + x.espn + ' ESPN)').join(' · ')})]);
    dh.append(list('This model is higher on', E.higher), list('This model is lower on', E.lower));
  }
})();

MQ.addEventListener('change', () => { drawToday(); drawRecord(); drawTrend(); drawHist(); drawBooks(); drawPower(); drawPortfolio(); });


// ---------- Snowfall (light flurries in the page background)
(function snow() {
  const cv = $('snow'), ctx = cv.getContext('2d'), btn = $('snowToggle');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let on = store.get('snow', reduce ? 'off' : 'on') === 'on', flakes = [], raf = null, w = 0, h = 0, dpr = 1;
  const label = () => { btn.textContent = 'Snow: ' + (on ? 'On' : 'Off'); btn.setAttribute('aria-pressed', on); };
  function size() {
    dpr = Math.min(devicePixelRatio || 1, 2); w = innerWidth; h = innerHeight;
    cv.width = w * dpr; cv.height = h * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.round(Math.min(110, (w * h) / 16000));   // fewer flakes on small screens
    while (flakes.length < n) flakes.push(make(true));
    flakes.length = n;
  }
  function make(anywhere) {
    return {x: Math.random() * w, y: anywhere ? Math.random() * h : -6, r: 0.8 + Math.random() * 2.2,
            vy: 0.25 + Math.random() * 0.6, vx: -0.15 + Math.random() * 0.3, ph: Math.random() * 6.28, a: 0.35 + Math.random() * 0.45};
  }
  function color() {
    const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    return dark ? '255,255,255' : '120,132,158';   // white flakes on dark, soft blue-gray on the light background
  }
  function frame(t) {
    ctx.clearRect(0, 0, w, h);
    const c = color();
    for (const f of flakes) {
      f.y += f.vy * f.r * 0.6; f.x += f.vx + Math.sin(t / 1600 + f.ph) * 0.25;
      if (f.y > h + 6) Object.assign(f, make(false));
      if (f.x < -6) f.x = w + 6; else if (f.x > w + 6) f.x = -6;
      ctx.beginPath(); ctx.arc(f.x, f.y, f.r, 0, 6.2832); ctx.fillStyle = 'rgba(' + c + ',' + f.a + ')'; ctx.fill();
    }
    raf = requestAnimationFrame(frame);
  }
  function start() { if (raf || !on || document.hidden) return; size(); raf = requestAnimationFrame(frame); }
  function stop() { if (raf) cancelAnimationFrame(raf); raf = null; ctx.clearRect(0, 0, w, h); }
  btn.onclick = () => { on = !on; store.set('snow', on ? 'on' : 'off'); label(); on ? start() : stop(); };
  addEventListener('resize', () => { if (raf) size(); });
  document.addEventListener('visibilitychange', () => { document.hidden ? stop() : start(); });
  label(); start();
})();

// ---------- Live scores (ticker, Live tab, dock)
const SCORE_URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard';
const PICKS = D.livePicks || {};
let LIVE = [], liveOk = null, liveFilter = 'all';
function etDate() {
  const p = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  return p.replace(/-/g, '');
}
function parseScoreboard(js) {
  return (js.events || []).map(ev => {
    const c = (ev.competitions || [])[0] || {};
    const t = {}; (c.competitors || []).forEach(x => { t[x.homeAway] = x; });
    if (!t.home || !t.away) return null;
    const st = ((c.status || ev.status || {}).type) || {};
    const side = x => ({ name: (x.team || {}).shortDisplayName || (x.team || {}).location || '', abbr: (x.team || {}).abbreviation || '',
      score: x.score != null && x.score !== '' ? +x.score : null, rank: ((x.curatedRank || {}).current || 99) <= 25 ? x.curatedRank.current : null });
    return { id: String(ev.id), start: ev.date, state: st.state || 'pre', detail: st.shortDetail || st.detail || '',
             away: side(t.away), home: side(t.home), neutral: !!c.neutralSite };
  }).filter(Boolean).sort((a, b) => (a.start || '').localeCompare(b.start || ''));
}
function coverInfo(g) {
  const p = PICKS[g.id];
  if (!p) return null;
  if (g.state === 'pre' || g.away.score == null || g.home.score == null) return { p, status: 'pre', margin: null };
  const mine = p.side === 'away' ? g.away.score : g.home.score, theirs = p.side === 'away' ? g.home.score : g.away.score;
  const m = mine - theirs + p.line;
  return { p, margin: m, status: m > 0 ? 'cov' : m < 0 ? 'not' : 'push' };
}
const startTime = g => { try { return new Date(g.start).toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}); } catch(e) { return ''; } };
function coverText(ci, final) {
  if (!ci) return '';
  if (ci.status === 'pre') return '';
  const n = Math.abs(ci.margin);
  if (ci.status === 'push') return final ? 'Push' : 'Even with the line';
  return final ? (ci.status === 'cov' ? 'Covered by ' : 'Missed by ') + n.toFixed(1) : (ci.status === 'cov' ? 'Covering by ' : 'Not covering by ') + n.toFixed(1);
}
function coverChip(ci, final) {
  if (!ci || ci.status === 'pre') return el('span', {className: 'muted', textContent: ci ? 'Not started' : ''});
  const cls = ci.status === 'cov' ? 'W' : ci.status === 'not' ? 'L' : '';
  return chip(coverText(ci, final), cls);
}

// ticker
let tickerOn = store.get('ticker', 'on') === 'on';
function setTickerButton() { const b = $('tickerToggle'); b.textContent = 'Live ticker: ' + (tickerOn ? 'On' : 'Off'); b.setAttribute('aria-pressed', tickerOn); }
$('tickerToggle').onclick = () => { tickerOn = !tickerOn; store.set('ticker', tickerOn ? 'on' : 'off'); setTickerButton(); drawTicker(); };
setTickerButton();
function tickerItem(g) {
  const ci = coverInfo(g), it = el('span', {className: 'it'});
  const team = s => { const f = el('span'); if (s.rank) f.append(el('span', {className: 'rk', textContent: s.rank + ' '})); f.append(document.createTextNode(s.abbr || s.name)); return f; };
  if (ci && ci.status !== 'pre') it.append(el('span', {className: 'dot ' + (ci.status === 'cov' ? 'cov' : ci.status === 'not' ? 'not' : '')}));
  else if (g.state === 'in') it.append(el('span', {className: 'dot live'}));
  it.append(team(g.away));
  if (g.state !== 'pre') it.append(el('span', {className: 'sc', textContent: g.away.score}));
  it.append(team(g.home));
  if (g.state !== 'pre') it.append(el('span', {className: 'sc', textContent: g.home.score}));
  it.append(el('span', {className: 'st', textContent: g.state === 'pre' ? startTime(g) : g.detail}));
  return it;
}
function drawTicker() {
  const bar = $('ticker'), track = $('tickerTrack');
  if (!tickerOn || !LIVE.length) { bar.hidden = true; return; }
  const order = {in: 0, post: 1, pre: 2};
  const games = LIVE.slice().sort((a, b) => (order[a.state] - order[b.state]) || (a.start || '').localeCompare(b.start || ''));
  track.replaceChildren();
  for (let k = 0; k < 2; k++) games.forEach(g => track.append(tickerItem(g)));   // two copies for a seamless loop
  bar.hidden = false;
  $('tickerLabel').hidden = !LIVE.some(g => g.state === 'in');   // "LIVE" only while games are in progress
  requestAnimationFrame(() => { const w = track.scrollWidth / 2; track.style.setProperty('--dur', Math.max(20, w / 60) + 's'); });
}

// Live tab
function liveTiles() {
  const host = $('liveTiles'); host.replaceChildren();
  const n = st => LIVE.filter(g => g.state === st).length;
  const picks = LIVE.map(g => ({g, ci: coverInfo(g)})).filter(x => x.ci && x.ci.status !== 'pre');
  const cov = picks.filter(x => x.ci.status === 'cov').length, notc = picks.filter(x => x.ci.status === 'not').length;
  tile(host, 1, 'Live now', n('in'), 'Games in progress', 'blue');
  tile(host, 2, 'Upcoming', n('pre'), 'Still to tip off', '');
  tile(host, 3, 'Final', n('post'), 'Completed today', '');
  tile(host, 4, 'Edge picks', cov + '-' + notc, 'Covering vs not (live + final)', 'black');
}
function drawLive() {
  const host = $('liveList'); host.replaceChildren();
  if (liveOk === false && !LIVE.length) { host.append(el('div', {className: 'empty', textContent: 'Live scores could not be loaded in this browser. They will show once ESPN responds; final results are still graded on each scheduled run.'})); return; }
  if (!LIVE.length) { host.append(el('div', {className: 'empty', textContent: liveOk === null ? 'Loading live scores...' : 'No Division I games on today’s schedule.'})); return; }
  const q = $('liveSearch').value.trim().toLowerCase(), only = $('livePicksOnly').checked;
  const games = LIVE.filter(g => (liveFilter === 'all' || g.state === liveFilter) && (!only || PICKS[g.id]) &&
    (!q || (g.away.name + ' ' + g.home.name).toLowerCase().includes(q)));
  host.append(el('div', {className: 'lhead'}, [el('div', {textContent: 'Start'}), el('div', {textContent: 'Score'}), el('div', {className: 'ph', textContent: 'Edge pick'}), el('div', {textContent: 'Status'})]));
  if (!games.length) { host.append(el('div', {className: 'empty', textContent: 'No games match.'})); return; }
  games.forEach(g => {
    const ci = coverInfo(g), fin = g.state === 'post';
    const tm = (s, other) => el('div', {className: 'tm' + (fin && s.score > other.score ? ' win' : '')}, [
      el('span', {textContent: (s.rank ? s.rank + ' ' : '') + s.name}), el('b', {textContent: g.state === 'pre' ? '' : s.score})]);
    const pick = el('div', {className: 'pick'});
    if (ci) { pick.append(el('div', {textContent: ci.p.team + ' ' + (ci.p.line > 0 ? '+' : '') + (ci.p.line === 0 ? 'PK' : ci.p.line) + (ci.p.conf ? '  ·  ' + ci.p.conf : '')})); pick.append(coverChip(ci, fin)); }
    else pick.append(el('span', {className: 'muted', textContent: 'No pick'}));
    const stat = el('div', {className: 'stat'});
    if (g.state === 'in') stat.append(el('span', {className: 'dot live'}), document.createTextNode(' ' + g.detail));
    else stat.append(document.createTextNode(fin ? 'Final' + (/OT/.test(g.detail) ? ' (' + g.detail.replace(/^Final\/?/, '') + ')' : '') : g.detail || startTime(g)));
    host.append(el('div', {className: 'lrow'}, [el('div', {className: 'when', textContent: startTime(g)}),
      el('div', {className: 'teams'}, [tm(g.away, g.home), tm(g.home, g.away)]), pick, stat]));
  });
}
document.querySelectorAll('#liveFilter button').forEach(b => b.onclick = () => {
  liveFilter = b.dataset.f; document.querySelectorAll('#liveFilter button').forEach(x => x.setAttribute('aria-pressed', x === b)); drawLive();
});
$('livePicksOnly').onchange = drawLive; $('liveSearch').oninput = drawLive;

// dock
const dock = $('dock');
function setDock(open) {
  dock.classList.toggle('min', !open); $('dockHead').setAttribute('aria-expanded', open);
  $('dockToggle').innerHTML = open ? '&#9660;' : '&#9650;'; $('dockToggle').setAttribute('aria-label', open ? 'Minimize live tracker' : 'Expand live tracker');
  store.set('dock', open ? 'open' : 'min');
}
setDock(store.get('dock', innerWidth > 720 ? 'open' : 'min') === 'open');
$('dockHead').onclick = () => setDock(dock.classList.contains('min'));
$('dockHead').onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setDock(dock.classList.contains('min')); } };
$('dockAll').onclick = e => { e.preventDefault(); document.querySelector('nav button[data-tab="live"]').click(); scrollTo({top: 0, behavior: 'smooth'}); };
let dockPicks = store.get('dockPicks', 'on') === 'on', dockLined = store.get('dockLined', 'off') === 'on';
$('dockPicks').checked = dockPicks; $('dockLined').checked = dockLined;
$('dockPicks').onchange = e => { dockPicks = e.target.checked; store.set('dockPicks', dockPicks ? 'on' : 'off'); drawDock(); };
$('dockLined').onchange = e => { dockLined = e.target.checked; store.set('dockLined', dockLined ? 'on' : 'off'); drawDock(); };
function drawDock() {
  const body = $('dockBody'); body.replaceChildren();
  const pool = dockLined ? LIVE.filter(g => PICKS[g.id]) : LIVE;   // "no line" = no Edge pick/line logged for the game
  const live = pool.filter(g => g.state === 'in'), next = pool.filter(g => g.state === 'pre').slice(0, 6);
  const recent = pool.filter(g => g.state === 'post' && PICKS[g.id]).slice(-4).reverse();
  const allLive = LIVE.filter(g => g.state === 'in').length;
  $('dockBadge').hidden = !allLive; $('dockBadge').textContent = allLive;
  $('dockDot').className = 'dot' + (allLive ? ' live' : '');
  if (liveOk === false && !LIVE.length) { body.append(el('div', {className: 'empty', textContent: 'Live scores unavailable right now.'})); return; }
  const card = g => {
    const ci = coverInfo(g), fin = g.state === 'post';
    const r = (s) => el('div', {className: 'r'}, [el('span', {textContent: (s.rank ? s.rank + ' ' : '') + s.name}), el('b', {textContent: g.state === 'pre' ? '' : s.score})]);
    const meta = el('div', {className: 'm'}, [el('span', {textContent: g.state === 'pre' ? startTime(g) : g.detail}),
      !dockPicks && ci ? coverChip(ci, fin) : el('span', {className: 'muted', textContent: !PICKS[g.id] ? 'No line' : ''})]);
    const kids = [r(g.away), r(g.home), meta];
    if (dockPicks && ci) {
      const p = ci.p;
      kids.push(el('div', {className: 'pk'}, [
        el('span', {className: 'pt', textContent: 'Edge: ' + p.team + ' ' + (p.line === 0 ? 'PK' : (p.line > 0 ? '+' : '') + p.line) + (p.conf ? ' · ' + p.conf : '')}),
        coverChip(ci, fin)]));
    }
    return el('div', {className: 'dg'}, kids);
  };
  const sec = (label, list) => { if (!list.length) return; body.append(el('div', {className: 'sec', textContent: label})); list.forEach(g => body.append(card(g))); };
  sec('Live now', live); sec('Up next', next); sec('Recent finals with picks', recent);
  if (!body.children.length) body.append(el('div', {className: 'empty', textContent: dockLined ? 'No games with a line right now.' : 'No games right now.'}));
}

// refresh loop
async function refreshLive() {
  try {
    const r = await fetch(SCORE_URL + '?dates=' + etDate() + '&groups=50&limit=500', {cache: 'no-store'});
    if (!r.ok) throw new Error(r.status);
    LIVE = parseScoreboard(await r.json()); liveOk = true;
    const t = new Date().toLocaleTimeString([], {hour: 'numeric', minute: '2-digit', second: '2-digit'});
    $('liveStamp').textContent = 'Updated ' + t; $('dockStamp').textContent = 'Updated ' + t;
    $('liveDot').className = 'dot' + (LIVE.some(g => g.state === 'in') ? ' live' : '');
  } catch (e) {
    liveOk = false; $('liveStamp').textContent = 'Live scores unavailable'; $('dockStamp').textContent = 'Live scores unavailable';
  }
  liveTiles(); drawLive(); drawDock(); drawTicker();
}
refreshLive();
setInterval(() => { if (!document.hidden) refreshLive(); }, 30000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshLive(); });
})();
</script>
</body>
</html>
"""
