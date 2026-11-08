"""Game-by-game research dataset: data/model_dataset.csv

One row per game (with a line), built up across the day's runs:
  * every pregame input the model used, including each team's ESPN BPI
    (overall, offense, defense) as of the last run before tip-off,
  * the opening line (first run that saw the game) and the closing line
    (last run before tip-off), with the source book,
  * the Edge pick, edge, Cover % and confidence at close,
  * once the game is final: the score, whether the pick covered the opening
    and closing lines, and closing line value (CLV).

It is meant for testing formula changes later (weights, home court, Cover %
settings) against real results.
"""
from __future__ import annotations

VERSION = "2026-11-07.2"

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import espn

COLUMNS = [
    "date", "game_id", "start", "away", "home", "neutral", "venue", "ratings_source",
    "t1_rank", "t2_rank", "t1_bpi", "t1_bpi_off", "t1_bpi_def", "t2_bpi", "t2_bpi_off", "t2_bpi_def",
    "t1_off", "t1_def", "t1_net", "t1_tempo", "t2_off", "t2_def", "t2_net", "t2_tempo", "avg_tempo",
    "proj_t1_margin", "model_t1_win", "market_t1_win",
    "open_t1_line", "open_source", "open_at", "close_t1_line", "close_source", "close_books", "close_at",
    "edge_side", "edge_pick", "edge_pts", "cover_prob", "confidence",
    "t1_score", "t2_score", "t1_margin", "pick_result_close", "pick_result_open", "clv_pts", "graded_at",
]

_SNAPSHOT = {  # dataset column -> results column (refreshed on every pregame run)
    "away": "T1 Team", "home": "T2 Team", "venue": "Venue",
    "t1_rank": "T1 Rk", "t2_rank": "T2 Rk",
    "t1_bpi": "T1 BPI", "t1_bpi_off": "T1 BPI Off", "t1_bpi_def": "T1 BPI Def",
    "t2_bpi": "T2 BPI", "t2_bpi_off": "T2 BPI Off", "t2_bpi_def": "T2 BPI Def",
    "t1_off": "T1 Off", "t1_def": "T1 Def", "t1_net": "T1 Net", "t1_tempo": "T1 AdjT",
    "t2_off": "T2 Off", "t2_def": "T2 Def", "t2_net": "T2 Net", "t2_tempo": "T2 AdjT", "avg_tempo": "Avg Tempo",
    "proj_t1_margin": "Proj T1 Margin", "model_t1_win": "Model T1 Win%", "market_t1_win": "Market T1 Win%",
    "close_t1_line": "_t1_line", "close_source": "Line Source", "close_books": "Books",
    "edge_side": "_edge_side", "edge_pick": "Edge Pick", "edge_pts": "Edge Size",
    "cover_prob": "Cover %", "confidence": "Confidence",
}


def _v(x):
    try:
        return None if x is None or (not isinstance(x, str) and pd.isna(x)) else x
    except (TypeError, ValueError):
        return x


def load(path: Path) -> pd.DataFrame:
    if path.exists():
        df = pd.read_csv(path, dtype={"game_id": str, "date": str})
        for c in COLUMNS:
            if c not in df:
                df[c] = None
        return df[COLUMNS].astype(object).where(pd.notna(df[COLUMNS]), None)
    return pd.DataFrame(columns=COLUMNS)


def update(path: Path, results: pd.DataFrame, games: list, day: date, ratings_source: str) -> int:
    """Add or refresh a row for every game that hasn't tipped off and has a line."""
    if results is None or results.empty or "_t1_line" not in results:
        return 0
    pregame = {g["game_id"]: espn.is_pregame(g) for g in games}
    neutral = {g["game_id"]: bool(g.get("neutral")) for g in games}
    df = load(path)
    idx = {gid: i for i, gid in zip(df.index, df["game_id"].astype(str))}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_rows, n = [], 0
    for _, r in results.iterrows():
        gid = str(r.get("game_id"))
        if not pregame.get(gid) or _v(r.get("_t1_line")) is None:
            continue
        snap = {k: _v(r.get(col)) for k, col in _SNAPSHOT.items()}
        snap.update({"close_at": now, "ratings_source": ratings_source, "neutral": neutral.get(gid, False),
                     "start": str(_v(r.get("_start")) or ""), "date": day.isoformat()})
        if gid in idx:
            for k, v in snap.items():
                df.at[idx[gid], k] = v
        else:
            row = {c: None for c in COLUMNS}
            row.update(snap)
            row.update({"game_id": gid, "open_t1_line": snap["close_t1_line"],
                        "open_source": snap["close_source"], "open_at": now})
            new_rows.append(row)
        n += 1
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows, columns=COLUMNS)], ignore_index=True)
    df.to_csv(path, index=False)
    return n


def _result(margin_for_pick: float) -> str:
    return "W" if margin_for_pick > 0 else "P" if margin_for_pick == 0 else "L"


def grade(path: Path, today: date | None = None) -> int:
    """Fill in final scores, cover results and closing line value."""
    today = today or date.today()
    df = load(path)
    if df.empty:
        return 0
    pend = df[df["t1_score"].isna() & (df["date"].astype(str) <= today.isoformat())]
    done = 0
    for d in sorted(pend["date"].astype(str).unique()):
        try:
            games = {g["game_id"]: g for g in espn.get_games(date.fromisoformat(d))}
        except Exception:
            games = {}
        for i in pend.index[pend["date"].astype(str) == d]:
            gid = str(df.at[i, "game_id"])
            g = games.get(gid)
            if g is None or (not g["completed"] and date.fromisoformat(d) < today):
                try:
                    g = espn.get_game_result(gid) or g
                except Exception:
                    pass
            if not (g and g["completed"] and g["away"]["score"] is not None and g["home"]["score"] is not None):
                continue
            s1, s2 = float(g["away"]["score"]), float(g["home"]["score"])
            df.at[i, "t1_score"], df.at[i, "t2_score"], df.at[i, "t1_margin"] = s1, s2, s1 - s2
            side = df.at[i, "edge_side"]
            close, opn = _v(df.at[i, "close_t1_line"]), _v(df.at[i, "open_t1_line"])
            if side in ("T1", "T2") and close is not None:
                sign = 1 if side == "T1" else -1
                pick_margin = sign * (s1 - s2)
                pick_close = sign * float(close)
                df.at[i, "pick_result_close"] = _result(pick_margin + pick_close)
                if opn is not None:
                    pick_open = sign * float(opn)
                    df.at[i, "pick_result_open"] = _result(pick_margin + pick_open)
                    df.at[i, "clv_pts"] = round(pick_open - pick_close, 2)  # + = got a better number than close
            df.at[i, "graded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            done += 1
    df.to_csv(path, index=False)
    return done


def clv_summary(path: Path) -> dict:
    """How often the Edge pick's opening number beat the closing line."""
    df = load(path)
    if df.empty:
        return {}
    g = df[df["clv_pts"].notna()]
    if g.empty:
        return {"games": int(df["t1_score"].notna().sum())}
    clv = g["clv_pts"].astype(float)
    moved = clv[clv != 0]
    return {
        "games": int(len(g)),
        "moved": int(len(moved)),
        "beat": int((moved > 0).sum()),
        "beat_rate": round(float((moved > 0).mean()), 4) if len(moved) else None,
        "avg_clv": round(float(clv.mean()), 3),
    }
