"""Current-season adjustments learned from ESPN final scores.

Starts from ESPN's preseason BPI (a fixed prior) and, after every finished
Division I game, nudges both teams' offense, defense and tempo toward what
actually happened:

  expected points per 100 possessions (home) = home AdjO + away AdjD - average
                                                 + half the home-court edge
  actual points per 100 possessions           = points / possessions x 100
  error = actual - expected   (capped so one blowout can't swing a rating)

  home offense  += k x home error      away defense += k x home error
  away offense  += k x away error      home defense += k x away error

k = 1 / (games played + PRIOR_GAMES), so early games move a team a little and
each new game counts less as the season goes on (like a running average that
starts from the preseason rating). Tempo blends the same way toward the
team's actual possessions per game.

State lives in data/team_adjustments.json; every game is processed once.
"""
from __future__ import annotations

VERSION = "2026-11-07.2"

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

import config
import espn

ERROR_CAP = 30.0          # max error per game, points per 100 possessions
MAX_BOX_SCORES = 150      # box-score lookups per run (for possession counts)


def _prior() -> float:
    return float(getattr(config, "PRIOR_GAMES", 8))


def _state_path(data_dir: Path) -> Path:
    return Path(data_dir) / "team_adjustments.json"


def load_state(data_dir: Path, season: int) -> dict:
    p = _state_path(data_dir)
    if p.exists():
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            if st.get("season") == season:
                return st
        except Exception:
            pass
    return {"season": season, "teams": {}, "games": {}, "dates_done": []}


def save_state(data_dir: Path, st: dict) -> None:
    _state_path(data_dir).write_text(json.dumps(st, indent=0), encoding="utf-8")


def apply(ratings: pd.DataFrame, st: dict) -> pd.DataFrame:
    """Base ratings + learned adjustments (offense, defense, tempo, record)."""
    df = ratings.copy()
    for c in ("adj_o", "adj_d", "adj_t"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["record"] = df["record"].astype(object)
    prior = _prior()
    for i, team in df["team"].items():
        t = st["teams"].get(team)
        if not t:
            continue
        df.at[i, "adj_o"] = float(df.at[i, "adj_o"]) + t.get("d_off", 0.0)
        df.at[i, "adj_d"] = float(df.at[i, "adj_d"]) + t.get("d_def", 0.0)
        n_t = t.get("tempo_n", 0)
        if n_t:
            w = n_t / (n_t + prior)
            df.at[i, "adj_t"] = (1 - w) * float(df.at[i, "adj_t"]) + w * (t["tempo_sum"] / n_t)
        df.at[i, "record"] = f"{t.get('w', 0)}-{t.get('l', 0)}"
    from torvik import _finish
    return _finish(df)


def _possessions(game_id: str):
    """Possessions in a game from ESPN's box score (average of both teams'
    FGA - ORB + TO + 0.475 x FTA). None if the box score isn't available."""
    try:
        r = requests.get(espn.SUMMARY_URL, params={"event": game_id},
                         headers={"User-Agent": config.USER_AGENT}, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        teams = (r.json().get("boxscore") or {}).get("teams") or []
        poss = []
        for t in teams:
            stats = {}
            for s in t.get("statistics") or []:
                for k in (s.get("name"), s.get("label"), s.get("abbreviation")):
                    if k:
                        stats[str(k).lower()] = str(s.get("displayValue", ""))

            def pair(*keys):
                for k in keys:
                    v = stats.get(k)
                    if v and "-" in v:
                        a, b = v.split("-")[:2]
                        return float(a), float(b)
                return None, None

            def one(*keys):
                for k in keys:
                    v = stats.get(k)
                    if v not in (None, ""):
                        try:
                            return float(v)
                        except ValueError:
                            pass
                return None

            _, fga = pair("fieldgoalsmade-fieldgoalsattempted", "fg")
            _, fta = pair("freethrowsmade-freethrowsattempted", "ft")
            orb = one("offensiverebounds", "offensive rebounds", "or")
            tov = one("turnovers", "totalturnovers", "total turnovers", "to")
            if None in (fga, fta, orb, tov):
                return None
            poss.append(fga - orb + tov + 0.475 * fta)
        return sum(poss) / len(poss) if len(poss) == 2 else None
    except Exception:
        return None


def update(ratings_base: pd.DataFrame, data_dir: Path, season: int, today: date | None = None,
           start: str | None = None) -> tuple[pd.DataFrame, str]:
    """Process newly finished games, save the state, and return
    (adjusted ratings, short status for the run log)."""
    from names import TeamMatcher
    today = today or date.today()
    start = start or getattr(config, "SEASON_START", f"{season - 1}-11-01")
    st = load_state(data_dir, season)
    aliases = Path(data_dir).parent / "team_aliases.csv"
    if not aliases.exists():
        aliases = Path(data_dir) / "team_aliases.csv"
    matcher = TeamMatcher(ratings_base["team"].tolist(), aliases)
    current = apply(ratings_base, st).set_index("team")
    prior = _prior()
    hca = float(config.HOME_COURT_POINTS)
    avg = float(ratings_base["adj_o"].mean() + ratings_base["adj_d"].mean()) / 2
    box_left, new_games = MAX_BOX_SCORES, 0

    d = date.fromisoformat(start)
    while d <= today:
        ds = d.isoformat()
        if ds in st["dates_done"]:
            d += timedelta(days=1)
            continue
        try:
            games = espn.get_games(d)
        except Exception:
            d += timedelta(days=1)
            continue
        all_final = True
        for g in games:
            gid = g["game_id"]
            if gid in st["games"]:
                continue
            if not g["completed"] or g["away"]["score"] is None or g["home"]["score"] is None:
                all_final = False
                continue
            a = matcher.match(g["away"]["location"], g["away"]["short"], g["away"]["display"])
            h = matcher.match(g["home"]["location"], g["home"]["short"], g["home"]["display"])
            if not a or not h or a not in current.index or h not in current.index:
                st["games"][gid] = {"skip": "not two D1 teams"}
                continue
            A, H = current.loc[a], current.loc[h]
            tempo_exp = (float(A["adj_t"]) + float(H["adj_t"])) / 2
            poss = None
            if box_left > 0:
                poss = _possessions(gid)
                box_left -= 1
            p = poss or tempo_exp
            hca100 = 0.0 if g.get("neutral") else hca * 100 / p
            exp_h = float(H["adj_o"]) + float(A["adj_d"]) - avg + hca100 / 2
            exp_a = float(A["adj_o"]) + float(H["adj_d"]) - avg - hca100 / 2
            act_h = g["home"]["score"] * 100 / p
            act_a = g["away"]["score"] * 100 / p
            err_h = max(-ERROR_CAP, min(ERROR_CAP, act_h - exp_h))
            err_a = max(-ERROR_CAP, min(ERROR_CAP, act_a - exp_a))
            for team, off_err, def_err, won in ((h, err_h, err_a, g["home"]["score"] > g["away"]["score"]),
                                                (a, err_a, err_h, g["away"]["score"] > g["home"]["score"])):
                t = st["teams"].setdefault(team, {"n": 0, "d_off": 0.0, "d_def": 0.0, "tempo_sum": 0.0,
                                                  "tempo_n": 0, "w": 0, "l": 0})
                k = 1 / (t["n"] + 1 + prior)
                t["d_off"] += k * off_err
                t["d_def"] += k * def_err
                t["n"] += 1
                t["w" if won else "l"] += 1
                if poss:
                    t["tempo_sum"] += poss
                    t["tempo_n"] += 1
            st["games"][gid] = {"date": ds, "home": h, "away": a, "poss": poss,
                                "err_home": round(err_h, 2), "err_away": round(err_a, 2)}
            new_games += 1
            current = apply(ratings_base, st).set_index("team")
        if all_final and d < today:
            st["dates_done"].append(ds)
        d += timedelta(days=1)

    save_state(data_dir, st)
    played = sum(1 for t in st["teams"].values() if t.get("n"))
    counted = sum(1 for g in st["games"].values() if "skip" not in g)
    msg = f"{counted} finished games applied ({new_games} new), {played} teams adjusted"
    return apply(ratings_base, st), msg
