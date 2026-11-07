"""Pick log, automatic grading, and success rates.

Every pick is saved to data/pick_history.csv:
  Model   original "Model Pick" (Enhanced columns), graded against the spread
  Edge    side the model's projected margin likes vs the sportsbook line, ATS
  Market  side where model win % beats the market's implied win %, straight up
Grading pulls final scores from ESPN and marks W, L, P (push) or NR (no result).
"""

from __future__ import annotations

VERSION = "2026-11-07.2"

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import config
import espn

COLUMNS = [
    "date", "start", "game_id", "pick_type", "t1", "t2", "pick_team", "pick_side", "pick_line",
    "line_source", "confidence", "enhanced_value", "edge", "cover_prob", "market_prob", "model_prob",
    "result", "t1_score", "t2_score", "logged_at", "graded_on", "confidence_logged",
]
NUMERIC = ("pick_line", "enhanced_value", "edge", "cover_prob", "market_prob", "model_prob", "t1_score", "t2_score")


def load(path: Path) -> pd.DataFrame:
    if path.exists():
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = ""
        df = df[COLUMNS].astype(object)
        for c in NUMERIC:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.replace({"": None})
    return pd.DataFrame(columns=COLUMNS)


def save(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


def _pending(df: pd.DataFrame) -> pd.Series:
    return df["result"].isna() | df["result"].astype(str).str.strip().isin(["", "nan", "None"])


def _v(x):
    """None for NaN / NaT / missing, else the value."""
    try:
        return None if x is None or (not isinstance(x, str) and pd.isna(x)) else x
    except (TypeError, ValueError):
        return x


def _started(start, now) -> bool:
    start = _v(start)
    if start is None:
        return False
    if isinstance(start, str):
        try:
            start = datetime.fromisoformat(start)
        except ValueError:
            return False
    return start <= now


def log_picks(results: pd.DataFrame, day: date, path: Path) -> int:
    """Save picks for games that haven't tipped off yet. Re-running the same day
    replaces those games' ungraded picks, so the latest pre-game line counts."""
    hist = load(path)
    now = datetime.now(timezone.utc).astimezone()
    new = []
    if "_t1_line" not in results:
        return 0
    for _, r in results.iterrows():
        if _started(r.get("_start"), now):
            continue
        r = {k: _v(v) for k, v in r.items()}
        t1_line = r.get("_t1_line")
        has_line = t1_line is not None
        model_p = r.get("Model T1 Win%")
        base = {
            "date": day.isoformat(),
            "start": pd.Timestamp(r["_start"]).isoformat() if r.get("_start") is not None else None,
            "game_id": str(r["game_id"]), "t1": r["T1 Team"], "t2": r["T2 Team"],
            "line_source": r.get("Line Source"), "result": None, "t1_score": None, "t2_score": None,
            "logged_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "graded_on": None,
        }

        def add(ptype, side, **extra):
            pick = dict(base, pick_type=ptype, pick_side=side,
                        pick_team=r["T1 Team"] if side == "T1" else r["T2 Team"])
            if has_line and ptype != "Market":
                pick["pick_line"] = t1_line if side == "T1" else -t1_line
            if model_p is not None:
                pick["model_prob"] = round(model_p if side == "T1" else 1 - model_p, 4)
            pick.update(extra)
            new.append(pick)

        if has_line:
            if r.get("_model_side"):
                ev = r.get("Enhanced Value")
                add("Model", r["_model_side"],
                    enhanced_value=round(float(ev), 3) if ev is not None else None)
            if r.get("_edge_side") and (r.get("_edge") or 0) >= config.EDGE_LOG_MIN:
                add("Edge", r["_edge_side"], edge=round(float(r["_edge"]), 2),
                    confidence=r.get("Confidence", ""),
                    cover_prob=round(float(r["_cover"]), 4) if r.get("_cover") is not None else None)
        if r.get("_mkt_side") and r.get("_mkt_prob") is not None:
            add("Market", r["_mkt_side"], edge=round(float(r["_p_edge"]), 4),
                market_prob=round(float(r["_mkt_prob"]), 4))

    new_df = pd.DataFrame(new, columns=COLUMNS)
    if not hist.empty:
        logged_games = set(new_df["game_id"]) | {
            str(g) for g, s in zip(results["game_id"], results["_start"])
            if _v(s) is not None and not _started(s, now)}
        replace = _pending(hist) & hist["game_id"].isin(logged_games) & (hist["date"] == day.isoformat())
        done = set(zip(hist.loc[~_pending(hist), "game_id"], hist.loc[~_pending(hist), "pick_type"]))
        hist = hist[~replace]
        if not new_df.empty:
            new_df = new_df[[(g, p) not in done for g, p in zip(new_df["game_id"], new_df["pick_type"])]]
    frames = [f for f in (hist, new_df) if not f.empty]
    save(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS), path)
    return len(new_df)


def grade_result(pick_type, pick_side, pick_line, t1_score, t2_score) -> str:
    mine, theirs = (t1_score, t2_score) if pick_side == "T1" else (t2_score, t1_score)
    margin = mine - theirs + (0 if pick_type == "Market" or pick_line is None or pd.isna(pick_line)
                              else float(pick_line))
    return "W" if margin > 0 else "P" if margin == 0 else "L"


def grade(path: Path, today: date | None = None, fetch=espn.get_games) -> int:
    today = today or date.today()
    hist = load(path)
    if hist.empty:
        return 0
    pend = hist[_pending(hist)]
    graded = 0
    for d in sorted(pend["date"].unique()):
        day = date.fromisoformat(d)
        if day > today:
            continue
        try:
            games = {g["game_id"]: g for g in fetch(day)}
        except Exception as e:
            print(f"  Scoreboard for {d} unavailable ({e}); looking games up one by one")
            games = {}
        for idx in pend.index[pend["date"] == d]:
            gid = str(hist.at[idx, "game_id"])
            g = games.get(gid)
            if g is None or (not g["completed"] and day < today):
                try:
                    g = espn.get_game_result(gid) or g   # look the game up directly
                    if g:
                        games[gid] = g
                except Exception:
                    pass
            if g and g["completed"] and g["away"]["score"] is not None and g["home"]["score"] is not None:
                s1, s2 = g["away"]["score"], g["home"]["score"]
                hist.at[idx, "t1_score"], hist.at[idx, "t2_score"] = s1, s2
                hist.at[idx, "result"] = grade_result(hist.at[idx, "pick_type"], hist.at[idx, "pick_side"],
                                                      hist.at[idx, "pick_line"], s1, s2)
                hist.at[idx, "graded_on"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                graded += 1
            elif day < today - timedelta(days=3):
                hist.at[idx, "result"] = "NR"
                hist.at[idx, "graded_on"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save(hist, path)
    return graded


# --------------------------------------------------------------------- summaries
def _line(label, sub, ats=True):
    w, l, p = (int((sub["result"] == x).sum()) for x in ("W", "L", "P"))
    rate = w / (w + l) if (w + l) else None
    units = None
    if ats and (w + l):
        units = w * (100 / 110) - l          # flat 1-unit bets at -110
    elif not ats and "market_prob" in sub and (w + l):
        mp = sub.loc[sub["result"].isin(["W", "L"]), ["result", "market_prob"]].dropna()
        # payout at the market's price: win pays (1-p)/p per unit staked
        units = sum(((1 - x) / x) if r == "W" else -1 for r, x in zip(mp["result"], mp["market_prob"]) if 0 < x < 1)
    return {"Pick Type": label, "W": w, "L": l, "P": p, "Picks": w + l + p,
            "Success Rate": rate, "Units": units}


def record_summary(path: Path) -> pd.DataFrame:
    hist = load(path)
    hist = hist[hist["result"].isin(["W", "L", "P"])]
    rows = [
        _line("Sportsbook Edge (all)", hist[hist["pick_type"] == "Edge"]),
    ]
    edges = hist[hist["pick_type"] == "Edge"]
    b = list(config.EDGE_BUCKETS) + [float("inf")]
    for lo, hi in zip(b[:-1], b[1:]):
        sub = edges[(edges["edge"] >= lo) & (edges["edge"] < hi)]
        rows.append(_line(f"  Edge {lo:g}+ pts" if hi == float("inf") else f"  Edge {lo:g} to {hi:g} pts", sub))
    for tier in ("High", "Medium", "Low", "Check"):
        rows.append(_line(f"  Confidence {tier}",
                          edges[(edges["confidence"] == tier)]))
    rows.append(_line("Market Edge (all, straight up)", hist[hist["pick_type"] == "Market"], ats=False))
    mk = hist[hist["pick_type"] == "Market"]
    mb = list(config.MARKET_EDGE_BUCKETS) + [float("inf")]
    for lo, hi in zip(mb[:-1], mb[1:]):
        sub = mk[(mk["edge"] >= lo) & (mk["edge"] < hi)]
        lab = f"  Win% edge {lo:.0%}+" if hi == float("inf") else f"  Win% edge {lo:.0%} to {hi:.0%}"
        rows.append(_line(lab, sub, ats=False))
    rows.append(_line("Model Pick (all)", hist[hist["pick_type"] == "Model"]))
    return pd.DataFrame(rows)


def daily_trend(path: Path, pick_type: str = "Edge") -> pd.DataFrame:
    hist = load(path)
    hist = hist[(hist["pick_type"] == pick_type) & hist["result"].isin(["W", "L", "P"])]
    if hist.empty:
        return pd.DataFrame(columns=["Date", "W", "L", "P", "Day Rate", "Cumulative W", "Cumulative L", "Cumulative Rate"])
    g = hist.groupby("date")["result"].value_counts().unstack(fill_value=0)
    for c in ("W", "L", "P"):
        if c not in g:
            g[c] = 0
    g = g[["W", "L", "P"]].sort_index().reset_index().rename(columns={"date": "Date"})
    g["Day Rate"] = g["W"] / (g["W"] + g["L"]).where((g["W"] + g["L"]) > 0)
    g["Cumulative W"], g["Cumulative L"] = g["W"].cumsum(), g["L"].cumsum()
    g["Cumulative Rate"] = g["Cumulative W"] / (g["Cumulative W"] + g["Cumulative L"]).where((g["Cumulative W"] + g["Cumulative L"]) > 0)
    return g


def relabel_edge_picks(path: Path) -> int:
    """Re-score every Edge pick's Cover % and Confidence with the current rules,
    from the edge and line saved with the pick, so every tier on the Success
    Rate and Portfolio tabs uses one definition. The label the pick had when it
    was logged is kept in confidence_logged."""
    import model
    hist = load(path)
    if hist.empty:
        return 0
    changed = 0
    for idx in hist.index[hist["pick_type"] == "Edge"]:
        edge, line = hist.at[idx, "edge"], hist.at[idx, "pick_line"]
        if edge is None or pd.isna(edge):
            continue
        spread = abs(float(line)) if line is not None and not pd.isna(line) else None
        p = model.cover_probability(float(edge), spread)
        tier = model.cover_tier(p, float(edge), spread)
        if hist.at[idx, "confidence_logged"] in (None, "") or pd.isna(hist.at[idx, "confidence_logged"]):
            hist.at[idx, "confidence_logged"] = hist.at[idx, "confidence"] or ""
        if hist.at[idx, "confidence"] != tier or hist.at[idx, "cover_prob"] != round(p, 4):
            hist.at[idx, "confidence"], hist.at[idx, "cover_prob"] = tier, round(p, 4)
            changed += 1
    save(hist, path)
    return changed


def market_check(path: Path) -> dict:
    """Were the model's win probabilities better than the market's on the
    games where they disagreed? Uses the Brier score (average squared error
    between probability and outcome; lower is better) and expected vs actual
    wins, which is fairer than the raw win-loss of mostly-underdog picks."""
    hist = load(path)
    m = hist[(hist["pick_type"] == "Market") & hist["result"].isin(["W", "L"])].dropna(subset=["model_prob", "market_prob"])
    if m.empty:
        return {}
    y = (m["result"] == "W").astype(float)
    pm, pk = m["model_prob"].astype(float), m["market_prob"].astype(float)
    return {
        "picks": int(len(m)), "wins": int(y.sum()),
        "expected_model": round(float(pm.sum()), 2), "expected_market": round(float(pk.sum()), 2),
        "brier_model": round(float(((pm - y) ** 2).mean()), 4), "brier_market": round(float(((pk - y) ** 2).mean()), 4),
        "avg_model": round(float(pm.mean()), 4), "avg_market": round(float(pk.mean()), 4),
    }
