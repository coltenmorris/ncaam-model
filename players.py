"""Player availability, box scores and injuries from ESPN.

1. Box-score log (data/player_log.json): for every finished Division I game,
   each team's minutes by player plus the team box score (shooting,
   rebounds, assists, turnovers, possessions). It backfills the season a few
   hundred games per run, then keeps up with each day's games.

2. Availability before each game (columns in data/model_dataset.csv), worked
   out from games played BEFORE that date only, so it is fair for backtests:
     regulars       players averaging REGULAR_MINUTES+ minutes in the games
                    they played, who appeared in at least half the team's games
     regulars_out   regulars who did not play in the team's most recent game
     min_out        the season minutes per game of those players (how much of
                    the rotation is missing; a full game is 200 minutes)
     out_players    their names, with how many games in a row they've missed
   plus rest days, record and average margin over the last 5 games.

3. ESPN's injury list for upcoming games, when ESPN posts one (college
   coverage is patchy, so empty does not mean healthy).

Nothing here changes the picks yet. Once enough games are logged,
backtest.py shows whether skipping games with players out helps.
"""
from __future__ import annotations

VERSION = "2026-11-25.1"

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

import config
import espn

REGULAR_MINUTES = float(getattr(config, "REGULAR_MINUTES", 20.0))
MIN_TEAM_GAMES = 3                     # fewer games than this = availability unknown
LONG_TERM_GAMES = 6                    # missed this many in a row = season-long absence
MAX_SUMMARIES = int(getattr(config, "PLAYER_BOX_SCORES_PER_RUN", 400))
MAX_INJURY_LOOKUPS = 120

BOX_STATS = ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "reb", "ast", "tov", "poss")
PRE_COLS = ("espn_id", "games", "record", "rest_days", "last5_margin",
            "regulars_out", "min_out", "out_players", "injuries", "inj_out")
DATASET_COLUMNS = ([f"{s}_{c}" for c in PRE_COLS for s in ("t1", "t2")]
                   + [f"{s}_{c}" for c in BOX_STATS for s in ("t1", "t2")])

_session = requests.Session()
_session.headers["User-Agent"] = config.USER_AGENT


def _log_path(data_dir: Path) -> Path:
    return Path(data_dir) / "player_log.json"


def load_log(data_dir: Path, season: int) -> dict:
    p = _log_path(data_dir)
    if p.exists():
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            if st.get("season") == season:
                return st
        except Exception:
            pass
    return {"season": season, "dates_done": [], "games": {}, "names": {}}


def save_log(data_dir: Path, st: dict) -> None:
    _log_path(data_dir).write_text(json.dumps(st, separators=(",", ":")), encoding="utf-8")


def fetch_summary(game_id: str) -> dict:
    r = _session.get(espn.SUMMARY_URL, params={"event": game_id}, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------
# Parsing ESPN's game summary
# --------------------------------------------------------------------------
def _f(x):
    try:
        v = float(str(x).replace("+", ""))
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _team_stats(t: dict) -> dict:
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
                return _f(a), _f(b)
        return None, None

    def one(*keys):
        for k in keys:
            v = _f(stats.get(k))
            if v is not None:
                return v
        return None

    out = {}
    out["fgm"], out["fga"] = pair("fieldgoalsmade-fieldgoalsattempted", "fg")
    out["tpm"], out["tpa"] = pair("threepointfieldgoalsmade-threepointfieldgoalsattempted", "3pt")
    out["ftm"], out["fta"] = pair("freethrowsmade-freethrowsattempted", "ft")
    out["oreb"] = one("offensiverebounds", "offensive rebounds", "or")
    out["reb"] = one("totalrebounds", "rebounds", "reb")
    out["ast"] = one("assists", "ast")
    out["tov"] = one("turnovers", "totalturnovers", "total turnovers", "to")
    if None not in (out["fga"], out["oreb"], out["tov"], out["fta"]):
        out["poss"] = round(out["fga"] - out["oreb"] + out["tov"] + 0.475 * out["fta"], 1)
    return {k: v for k, v in out.items() if v is not None}


def _minutes(block: dict, names: dict) -> dict:
    """{athlete id: minutes} for one team (0 for did-not-play)."""
    out = {}
    for grp in block.get("statistics") or []:
        keys = [str(k).lower() for k in (grp.get("keys") or [])]
        labels = [str(k).upper() for k in (grp.get("labels") or grp.get("names") or [])]
        idx = keys.index("minutes") if "minutes" in keys else (labels.index("MIN") if "MIN" in labels else None)
        for a in grp.get("athletes") or []:
            ath = a.get("athlete") or {}
            pid = str(ath.get("id") or "")
            if not pid:
                continue
            names[pid] = ath.get("displayName") or ath.get("shortName") or pid
            vals = a.get("stats") or []
            m = _f(vals[idx]) if idx is not None and idx < len(vals) else None
            if a.get("didNotPlay") or m is None:
                m = 0.0
            out[pid] = max(out.get(pid, 0.0), m)
    return out


def parse_box(js: dict, names: dict) -> dict | None:
    comp = ((js.get("header") or {}).get("competitions") or [{}])[0]
    side = {}
    for c in comp.get("competitors") or []:
        tid = str(c.get("id") or (c.get("team") or {}).get("id") or "")
        if tid:
            side[tid] = {"ha": c.get("homeAway"), "score": _f(c.get("score")),
                         "name": (c.get("team") or {}).get("location") or (c.get("team") or {}).get("displayName")}
    if len(side) != 2:
        return None
    box = js.get("boxscore") or {}
    teams = {}
    for t in box.get("teams") or []:
        tid = str((t.get("team") or {}).get("id") or "")
        if tid in side:
            teams.setdefault(tid, {})["stats"] = _team_stats(t)
    for p in box.get("players") or []:
        tid = str((p.get("team") or {}).get("id") or "")
        if tid in side:
            teams.setdefault(tid, {})["min"] = _minutes(p, names)
    if not any(t.get("min") for t in teams.values()):
        return None
    home = next((k for k, v in side.items() if v["ha"] == "home"), None)
    away = next((k for k, v in side.items() if v["ha"] == "away"), None)
    for tid, v in side.items():
        t = teams.setdefault(tid, {})
        t["score"], t["name"] = v["score"], v["name"]
    return {"home": home, "away": away, "teams": teams}


def parse_injuries(js: dict) -> dict:
    """{team id: [(name, status), ...]} from ESPN's injuries section."""
    out = {}
    for block in js.get("injuries") or []:
        tid = str((block.get("team") or {}).get("id") or "")
        items = []
        for inj in block.get("injuries") or []:
            ath = inj.get("athlete") or {}
            name = ath.get("displayName") or ath.get("shortName")
            status = inj.get("status") or (inj.get("type") or {}).get("description") or ""
            if name:
                items.append((name, str(status)))
        if tid:
            out[tid] = items
    return out


# --------------------------------------------------------------------------
# Building the log
# --------------------------------------------------------------------------
def update_log(data_dir: Path, season: int, today: date | None = None) -> tuple[dict, str]:
    today = today or date.today()
    st = load_log(data_dir, season)
    start = date.fromisoformat(getattr(config, "SEASON_START", f"{season - 1}-11-01"))
    left, added, failed = MAX_SUMMARIES, 0, 0
    d = start
    while d < today + timedelta(days=1) and left > 0:
        ds = d.isoformat()
        if ds in st["dates_done"]:
            d += timedelta(days=1)
            continue
        try:
            games = espn.get_games(d)
        except Exception:
            d += timedelta(days=1)
            continue
        complete = True
        for g in games:
            gid = g["game_id"]
            if gid in st["games"]:
                continue
            if not g["completed"]:
                complete = False
                continue
            if left <= 0:
                complete = False
                break
            left -= 1
            try:
                box = parse_box(fetch_summary(gid), st["names"])
            except Exception:
                box, complete = None, False
                failed += 1
                continue
            if box is None:
                st["games"][gid] = {"date": ds, "nobox": True}
                continue
            box["date"], box["neutral"] = ds, bool(g.get("neutral"))
            st["games"][gid] = box
            added += 1
        if complete and d < today:
            st["dates_done"].append(ds)
        d += timedelta(days=1)
    save_log(data_dir, st)
    n = sum(1 for g in st["games"].values() if not g.get("nobox"))
    behind = "" if left > 0 else " (more to backfill next run)"
    return st, f"Box scores: {n} games logged ({added} new{', ' + str(failed) + ' failed' if failed else ''}){behind}"


def _team_games(st: dict) -> dict:
    """{team id: [(date, game_id, game), ...]} sorted by date."""
    out = {}
    for gid, g in st["games"].items():
        if g.get("nobox"):
            continue
        for tid in g.get("teams", {}):
            out.setdefault(tid, []).append((g["date"], gid, g))
    for v in out.values():
        v.sort(key=lambda x: (x[0], x[1]))
    return out


def availability(tid: str, as_of: str, by_team: dict, names: dict) -> dict:
    """Team status before a game on date as_of, from earlier games only."""
    games = [x for x in by_team.get(tid, []) if x[0] < as_of]
    out = {"games": len(games)}
    if not games:
        return out
    w = l = 0
    margins = []
    for _, _, g in games:
        me = g["teams"][tid]
        opp = next((v for k, v in g["teams"].items() if k != tid), {})
        if me.get("score") is not None and opp.get("score") is not None:
            m = me["score"] - opp["score"]
            margins.append(m)
            w, l = w + (m > 0), l + (m < 0)
    out["record"] = f"{w}-{l}"
    out["rest_days"] = (date.fromisoformat(as_of) - date.fromisoformat(games[-1][0])).days
    if margins:
        last = margins[-5:]
        out["last5_margin"] = round(sum(last) / len(last), 1)
    if len(games) < MIN_TEAM_GAMES:
        return out
    tot, apps = {}, {}
    for _, _, g in games:
        for pid, m in (g["teams"][tid].get("min") or {}).items():
            if m > 0:
                tot[pid] = tot.get(pid, 0.0) + m
                apps[pid] = apps.get(pid, 0) + 1
    last_min = games[-1][2]["teams"][tid].get("min") or {}
    out_list, min_out = [], 0.0
    for pid, n in apps.items():
        avg = tot[pid] / n
        if avg < REGULAR_MINUTES or n < max(2, len(games) / 2):
            continue
        if last_min.get(pid, 0) > 0:
            continue
        streak = 0
        for _, _, g in reversed(games):
            if (g["teams"][tid].get("min") or {}).get(pid, 0) > 0:
                break
            streak += 1
        nm = names.get(pid, pid)
        if streak >= LONG_TERM_GAMES:
            out_list.append(f"{nm} ({avg:.0f} mpg, out {streak}+, long-term)")
            continue
        out_list.append(f"{nm} ({avg:.0f} mpg, out {streak})")
        min_out += avg
    out["regulars_out"] = sum("long-term" not in s for s in out_list)
    out["min_out"] = round(min_out, 1)
    out["out_players"] = "; ".join(out_list)
    return out


# --------------------------------------------------------------------------
# Writing to the research dataset
# --------------------------------------------------------------------------
def pregame_injuries(games: list) -> dict:
    """{game_id: {team id: [(name, status)]}} for upcoming games with a line."""
    out, n = {}, 0
    for g in games:
        if n >= MAX_INJURY_LOOKUPS:
            break
        if not espn.is_pregame(g) or (g.get("spread") is None and g.get("cons_home_line") is None):
            continue
        n += 1
        try:
            out[g["game_id"]] = parse_injuries(fetch_summary(g["game_id"]))
        except Exception:
            continue
    return out


def fill_dataset(path: Path, st: dict, games: list | None = None, injuries: dict | None = None) -> int:
    """Add availability (as of each game's date) and final box scores to
    data/model_dataset.csv. Returns how many rows changed."""
    if not path.exists():
        return 0
    df = pd.read_csv(path, dtype={"game_id": str, "date": str})
    for c in DATASET_COLUMNS:
        if c not in df:
            df[c] = None
        df[c] = df[c].astype(object)
    ids = {g["game_id"]: (g["away"].get("id"), g["home"].get("id")) for g in games or []}
    by_team = _team_games(st)
    changed = 0
    for i, r in df.iterrows():
        gid = str(r["game_id"])
        logged = st["games"].get(gid) or {}
        t1, t2 = r.get("t1_espn_id"), r.get("t2_espn_id")
        if gid in ids:
            t1, t2 = ids[gid]
        elif logged.get("away"):
            t1, t2 = logged["away"], logged["home"]
        t1 = None if t1 is None or pd.isna(t1) or t1 == "" else str(t1).split(".")[0]
        t2 = None if t2 is None or pd.isna(t2) or t2 == "" else str(t2).split(".")[0]
        if not (t1 and t2):
            continue
        row = {"t1_espn_id": t1, "t2_espn_id": t2}
        as_of = str(r["date"])[:10]
        for s, tid in (("t1", t1), ("t2", t2)):
            av = availability(tid, as_of, by_team, st["names"])
            for c in ("games", "record", "rest_days", "last5_margin", "regulars_out", "min_out", "out_players"):
                row[f"{s}_{c}"] = av.get(c)
            box = (logged.get("teams") or {}).get(tid, {}).get("stats") or {}
            for c in BOX_STATS:
                if box.get(c) is not None:
                    row[f"{s}_{c}"] = box[c]
            inj = (injuries or {}).get(gid)
            if inj is not None:
                items = inj.get(tid) or []
                row[f"{s}_injuries"] = "; ".join(f"{n} ({stt})" for n, stt in items)
                row[f"{s}_inj_out"] = sum(1 for _, stt in items if stt.lower().startswith("out"))
        for k, v in row.items():
            old = r.get(k)
            if v is None or (not isinstance(old, str) and pd.notna(old) and str(old) == str(v)):
                continue
            if isinstance(old, str) and old == str(v):
                continue
            df.at[i, k] = v
            changed += 1
    df.to_csv(path, index=False)
    return changed


def run(data_dir: Path, dataset: Path, season: int, games: list | None = None) -> str:
    st, msg = update_log(data_dir, season)
    inj = pregame_injuries(games) if games else {}
    n = fill_dataset(dataset, st, games, inj)
    posted = sum(1 for v in inj.values() if any(v.values()))
    return f"{msg}; availability filled ({n} values); ESPN injury lists on {posted} of {len(inj)} upcoming games"
