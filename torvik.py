"""Download and parse Bart Torvik (T-Rank) team ratings.

Replaces pasting data into the old "KenPom" sheet.
"""

from __future__ import annotations

VERSION = "2026-11-07.2"

import io
from datetime import date
from pathlib import Path

import pandas as pd
import requests

import config

# Column positions in barttorvik.com/{season}_team_results.csv
# (the file has a header row, but "rank" appears twice so we go by position)
_COLS = {
    "rank": 0,
    "team": 1,
    "conf": 2,
    "record": 3,
    "adj_o": 4,
    "adj_o_rank": 5,
    "adj_d": 6,
    "adj_d_rank": 7,
    "barthag": 8,
}
_ADJT_HEADER = "adjt"


def season_for(day: date) -> int:
    """College hoops season label = the year it ends (Nov 2026 -> 2027)."""
    if config.SEASON:
        return int(config.SEASON)
    return day.year + 1 if day.month >= 8 else day.year


def _parse(text: str) -> pd.DataFrame:
    if text.lstrip().startswith("<"):
        raise RuntimeError(
            "Barttorvik returned a web page instead of CSV data (it may be "
            "showing a browser check). Open the CSV link in your browser, "
            "save it, and run again with --ratings-file <path>."
        )
    raw = pd.read_csv(io.StringIO(text), header=None, dtype=str)
    first = [str(x).strip().lower() for x in raw.iloc[0].tolist()]
    has_header = first[1] == "team" if len(first) > 1 else False
    adjt_idx = first.index(_ADJT_HEADER) if has_header and _ADJT_HEADER in first else raw.shape[1] - 1
    if has_header:
        raw = raw.iloc[1:]

    df = pd.DataFrame({name: raw.iloc[:, idx] for name, idx in _COLS.items()})
    df["adj_t"] = raw.iloc[:, adjt_idx]
    for c in ["rank", "adj_o", "adj_o_rank", "adj_d", "adj_d_rank", "barthag", "adj_t"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["team"] = df["team"].str.strip()
    df = df.dropna(subset=["team", "adj_o", "adj_d"])
    df["rank"] = df["rank"].astype(int)
    df["adj_o_rank"] = df["adj_o_rank"].astype(int)
    df["adj_d_rank"] = df["adj_d_rank"].astype(int)
    df["adj_t_rank"] = df["adj_t"].rank(ascending=False, method="min").astype(int)
    df["net_rtg"] = df["adj_o"] - df["adj_d"]
    return df.sort_values("rank").reset_index(drop=True)


RATING_COLS = ["rank", "team", "conf", "record", "adj_o", "adj_o_rank", "adj_d", "adj_d_rank",
               "adj_t", "adj_t_rank", "net_rtg", "barthag", "bpi", "bpi_off", "bpi_def"]
BROWSER_HEADERS = {
    "Accept": "text/csv,text/plain,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://barttorvik.com/trank.php",
}
CBBD_URL = "https://api.collegebasketballdata.com"


def _from_barttorvik(season: int) -> pd.DataFrame:
    url = config.TORVIK_URL.format(season=season)
    resp = requests.get(url, headers={"User-Agent": config.USER_AGENT, **BROWSER_HEADERS},
                        timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return _parse(resp.text)


def cbbd_key() -> str:
    import os
    return (getattr(config, "CBBD_API_KEY", "") or os.environ.get("CBBD_API_KEY", "")).strip()


def _cbbd_get(path: str, params: dict):
    key = cbbd_key()
    if not key:
        raise RuntimeError("no CBBD_API_KEY set")
    r = requests.get(f"{CBBD_URL}{path}", params=params, timeout=config.HTTP_TIMEOUT,
                     headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def _cbbd_is_current(label: int, team: str, season: int) -> bool:
    """CBBD's season label may be the start or end year. Look at one team's
    game dates to see if this label is the season we're in."""
    try:
        games = _cbbd_get("/games", {"season": label, "team": team})
        dates = [str(g.get("startDate") or g.get("start_date") or "")[:10] for g in games]
        dates = [d for d in dates if d]
        if dates:
            return max(dates) >= f"{season - 1}-08-01"
    except Exception:
        pass
    return label == season


def _cbbd_frame(rows: list, pace: dict) -> pd.DataFrame:
    out = []
    for x in rows:
        rk = x.get("rankings") or {}
        out.append({
            "team": x.get("team"), "conf": x.get("conference"),
            "record": (pace.get(x.get("team")) or {}).get("record", ""),
            "adj_o": x.get("offensiveRating"), "adj_d": x.get("defensiveRating"),
            "rank": rk.get("net"), "adj_o_rank": rk.get("offense"), "adj_d_rank": rk.get("defense"),
            "adj_t": (pace.get(x.get("team")) or {}).get("pace"), "barthag": None,
        })
    df = pd.DataFrame(out).dropna(subset=["team", "adj_o", "adj_d"])
    df["adj_t"] = pd.to_numeric(df["adj_t"], errors="coerce").fillna(config.TEMPO_BASELINE)
    df["net_rtg"] = df["adj_o"] - df["adj_d"]
    for col, src, asc in (("rank", "net_rtg", False), ("adj_o_rank", "adj_o", False), ("adj_d_rank", "adj_d", True)):
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].fillna(df[src].rank(ascending=asc, method="min")).astype(int)
    df["adj_t_rank"] = df["adj_t"].rank(ascending=False, method="min").astype(int)
    return df.sort_values("rank").reset_index(drop=True)[RATING_COLS]


def _cbbd_pace(label: int) -> dict:
    """team -> {"pace": float, "record": "W-L"} from CBBD season stats."""
    try:
        out = {}
        for x in _cbbd_get("/stats/team/season", {"season": label}):
            w, l = x.get("wins"), x.get("losses")
            out[x.get("team")] = {"pace": x.get("pace"),
                                  "record": f"{int(w)}-{int(l)}" if w is not None and l is not None else ""}
        return out
    except Exception as e:
        print(f"  CBBD pace unavailable ({e}); using league-average tempo")
        return {}


_CBBD_STALE: dict = {}


def _from_cbbd(season: int) -> pd.DataFrame:
    """CollegeBasketballData.com, current season only. Last season's final
    ratings are kept aside in _CBBD_STALE as a last resort."""
    found_any = False
    for label in (season, season - 1):
        rows = _cbbd_get("/ratings/adjusted", {"season": label})
        if not rows:
            continue
        found_any = True
        if _cbbd_is_current(label, rows[0].get("team", "Duke"), season):
            return _cbbd_frame(rows, _cbbd_pace(label))
        _CBBD_STALE[season] = (rows, label)
    raise RuntimeError("current-season ratings not posted yet" if found_any else
                       f"no ratings returned for {season} or {season - 1}")


ESPN_BPI_URL = ("https://site.web.api.espn.com/apis/fitt/v3/sports/basketball/"
                "mens-college-basketball/powerindex")
LEAGUE_AVG_EFF = 105.0   # D1 average points per 100 possessions, used to express BPI on that scale


def _team_name(t: dict) -> str:
    """School name from an ESPN team object ('Duke Blue Devils' -> 'Duke')."""
    if t.get("location"):
        return t["location"]
    disp, mascot = t.get("displayName") or "", t.get("name") or ""
    if mascot and disp.endswith(" " + mascot):
        return disp[: -len(mascot) - 1]
    return t.get("shortDisplayName") or t.get("nickname") or disp


def _from_espn_bpi(season: int) -> pd.DataFrame:
    """ESPN Basketball Power Index. It starts each season from a preseason
    projection and updates with results, so it is usable from opening night.
    BPI offense/defense are points above an average team per 70 possessions;
    they are converted to a per-100-possession scale so the rest of the model
    works unchanged."""
    def season_of(js):
        for k in ("requestedSeason", "currentSeason"):
            y = (js.get(k) or {}).get("year")
            if y:
                return int(y)
        y = (js.get("currentValues") or {}).get("season")
        return int(y) if y else None

    def get(params):
        r = requests.get(ESPN_BPI_URL, params=params, headers={"User-Agent": config.USER_AGENT},
                         timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()

    # ESPN has used different parameter names; use whichever returns this season.
    base, js, seen = None, None, []
    for extra in ({"season": season}, {"year": season}, {"season": season, "seasontype": 1},
                  {"season": season, "seasontype": 2}, {}):
        try:
            js = get({**extra, "limit": 50, "page": 1})
        except Exception as e:
            seen.append(f"{extra}: {e.__class__.__name__}")
            continue
        got = season_of(js)
        seen.append(f"{extra or 'default'} -> {got}")
        if got == season and js.get("teams"):
            base = extra
            break
    if base is None:
        raise RuntimeError(f"no {season} BPI posted yet ({'; '.join(seen)})")
    teams, labels = [], None
    pages = int((js.get("pagination") or {}).get("pages") or 1)
    page = 1
    while True:
        for cat in js.get("categories") or []:
            if cat.get("name") == "bpi" and cat.get("names"):
                labels = [str(n).lower() for n in cat["names"]]
        teams += js.get("teams") or []
        page += 1
        if page > min(pages, 20):
            break
        js = get({**base, "limit": 50, "page": page})
    i_bpi, i_off, i_def = 0, 3, 4
    if labels:
        for i, n in enumerate(labels):
            if n in ("bpi",):
                i_bpi = i
            elif "off" in n and "rank" not in n:
                i_off = i
            elif "def" in n and "rank" not in n:
                i_def = i
    rows = []
    for t in teams:
        info = t.get("team") or {}
        cat = next((c for c in t.get("categories") or [] if c.get("name") == "bpi"), None)
        if not cat:
            continue
        v = cat.get("values") or []
        try:
            off, dfn = float(v[i_off]), float(v[i_def])
        except (IndexError, TypeError, ValueError):
            continue
        scale = 100 / 70
        rows.append({
            "team": _team_name(info),
            "conf": ((info.get("group") or {}).get("abbreviation") or "").upper(),
            "record": "",
            "adj_o": LEAGUE_AVG_EFF + off * scale,
            "adj_d": LEAGUE_AVG_EFF - dfn * scale,
            "barthag": None,
            "bpi": float(v[i_bpi]) if len(v) > i_bpi and v[i_bpi] is not None else off + dfn,
            "bpi_off": off, "bpi_def": dfn,
        })
    if not rows:
        raise RuntimeError("no teams returned")
    df = pd.DataFrame(rows)
    pace = _cbbd_tempo(season)
    df["adj_t"] = df["team"].map(lambda n: _lookup(pace, n, "pace"))
    df["record"] = df["team"].map(lambda n: _lookup(pace, n, "record") or "")
    return _finish(df)


def _lookup(table: dict, team: str, field: str):
    from names import key
    row = table.get(team) or table.get(key(team)) or {}
    return row.get(field)


def _cbbd_tempo(season: int) -> dict:
    """Pace and record by team from CBBD (this season if posted, else last
    season's pace). Keys are both the raw and normalized names."""
    if not cbbd_key():
        return {}
    from names import key
    out = {}
    for label in (season, season - 1):
        data = _cbbd_pace(label)
        if data:
            current = label == season or _cbbd_is_current(label, next(iter(data)), season)
            for team, row in data.items():
                row = dict(row)
                if not current:
                    row["record"] = ""
                if team:
                    out.setdefault(team, row)
                    out.setdefault(key(team), row)
            if current:
                break
    return out


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    df["adj_t"] = pd.to_numeric(df["adj_t"], errors="coerce").fillna(config.TEMPO_BASELINE)
    df["net_rtg"] = df["adj_o"] - df["adj_d"]
    df["rank"] = df["net_rtg"].rank(ascending=False, method="min").astype(int)
    df["adj_o_rank"] = df["adj_o"].rank(ascending=False, method="min").astype(int)
    df["adj_d_rank"] = df["adj_d"].rank(ascending=True, method="min").astype(int)
    df["adj_t_rank"] = df["adj_t"].rank(ascending=False, method="min").astype(int)
    for c in RATING_COLS:
        if c not in df:
            df[c] = None
    return df.sort_values("rank").reset_index(drop=True)[RATING_COLS]


def _regress(df: pd.DataFrame, amount: float) -> pd.DataFrame:
    """Pull last season's ratings part of the way back to average (rosters turn over)."""
    df = df.copy()
    for c in ("adj_o", "adj_d"):
        mean = df[c].mean()
        df[c] = mean + (df[c] - mean) * (1 - amount)
    return _finish(df)


def load_ratings(day: date, data_dir: Path, ratings_file: str | None = None) -> pd.DataFrame:
    """Ratings in this order: Barttorvik, ESPN BPI, CollegeBasketballData.com,
    last saved copy, then last season's final ratings pulled toward average."""
    if ratings_file:
        return _parse(Path(ratings_file).read_text(encoding="utf-8-sig"))

    season = season_for(day)
    cache = data_dir / f"ratings_{season}_{date.today():%Y-%m-%d}.csv"
    if config.CACHE_RATINGS_SAME_DAY and cache.exists():
        return _read_saved(cache)

    errors = []
    for name, fn in (("Barttorvik", _from_barttorvik), ("ESPN BPI", _from_espn_bpi),
                     ("CollegeBasketballData.com", _from_cbbd)):
        try:
            df = fn(season)
            if len(df) < 200:
                raise RuntimeError(f"only {len(df)} teams returned")
            df.attrs["source"] = name
            df.attrs["skipped"] = list(errors)
            for c in RATING_COLS:
                if c not in df:
                    df[c] = None
            df[RATING_COLS].to_csv(cache, index=False)
            return df
        except Exception as e:
            errors.append(f"{name}: {str(e)[:160]}")
            print(f"  {name} unavailable ({e})")

    older = sorted(data_dir.glob(f"ratings_{season}_*.csv"))
    if older:
        print(f"  Using last saved ratings {older[-1].name}")
        df = _read_saved(older[-1])
        df.attrs["source"] = f"saved copy {older[-1].stem.split('_')[-1]}"
        df.attrs["skipped"] = list(errors)
        return df
    if season in _CBBD_STALE:
        rows, label = _CBBD_STALE[season]
        amt = getattr(config, "LAST_SEASON_REGRESSION", 0.35)
        df = _regress(_cbbd_frame(rows, _cbbd_pace(label)), amt)
        df.attrs["source"] = (f"CollegeBasketballData.com LAST SEASON final ratings, pulled {amt:.0%} "
                              "toward average (this season's not posted yet; switches automatically)")
        print("  Using last season's final ratings until this season's are posted.")
        df.attrs["skipped"] = list(errors)
        return df
    raise RuntimeError("no ratings source worked. " + " | ".join(errors))


def _read_saved(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    for c in RATING_COLS:
        if c not in df:
            df[c] = None
    df.attrs["source"] = "saved copy"
    return df
