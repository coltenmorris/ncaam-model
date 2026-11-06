"""Download and parse Bart Torvik (T-Rank) team ratings.

Replaces pasting data into the old "KenPom" sheet.
"""
from __future__ import annotations

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
               "adj_t", "adj_t_rank", "net_rtg", "barthag"]
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


def _from_cbbd(season: int) -> pd.DataFrame:
    """CollegeBasketballData.com adjusted efficiency + pace (free key)."""
    key = cbbd_key()
    if not key:
        raise RuntimeError("no CBBD_API_KEY set")
    h = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    r = requests.get(f"{CBBD_URL}/ratings/adjusted", params={"season": season}, headers=h,
                     timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise RuntimeError(f"CBBD has no {season} ratings yet")
    pace = {}
    try:
        p = requests.get(f"{CBBD_URL}/stats/team/season", params={"season": season}, headers=h,
                         timeout=config.HTTP_TIMEOUT)
        p.raise_for_status()
        pace = {x.get("team"): x.get("pace") for x in p.json() if x.get("pace")}
    except Exception as e:
        print(f"  CBBD pace unavailable ({e}); using league-average tempo")
    out = []
    for x in rows:
        rk = x.get("rankings") or {}
        out.append({
            "team": x.get("team"), "conf": x.get("conference"), "record": "",
            "adj_o": x.get("offensiveRating"), "adj_d": x.get("defensiveRating"),
            "rank": rk.get("net"), "adj_o_rank": rk.get("offense"), "adj_d_rank": rk.get("defense"),
            "adj_t": pace.get(x.get("team")), "barthag": None,
        })
    df = pd.DataFrame(out).dropna(subset=["team", "adj_o", "adj_d"])
    df["adj_t"] = pd.to_numeric(df["adj_t"], errors="coerce").fillna(config.TEMPO_BASELINE)
    df["net_rtg"] = df["adj_o"] - df["adj_d"]
    for col, src, asc in (("rank", "net_rtg", False), ("adj_o_rank", "adj_o", False), ("adj_d_rank", "adj_d", True)):
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].fillna(df[src].rank(ascending=asc, method="min")).astype(int)
    df["adj_t_rank"] = df["adj_t"].rank(ascending=False, method="min").astype(int)
    return df.sort_values("rank").reset_index(drop=True)[RATING_COLS]


def load_ratings(day: date, data_dir: Path, ratings_file: str | None = None) -> pd.DataFrame:
    """Ratings in this order: Barttorvik, CollegeBasketballData.com, last saved copy."""
    if ratings_file:
        return _parse(Path(ratings_file).read_text(encoding="utf-8-sig"))

    season = season_for(day)
    cache = data_dir / f"ratings_{season}_{date.today():%Y-%m-%d}.csv"
    if config.CACHE_RATINGS_SAME_DAY and cache.exists():
        return _read_saved(cache)

    errors = []
    for name, fn in (("Barttorvik", _from_barttorvik), ("CollegeBasketballData.com", _from_cbbd)):
        try:
            df = fn(season)
            if len(df) < 200:
                raise RuntimeError(f"only {len(df)} teams returned")
            df.attrs["source"] = name
            for c in RATING_COLS:
                if c not in df:
                    df[c] = None
            df[RATING_COLS].to_csv(cache, index=False)
            for old in sorted(data_dir.glob(f"ratings_{season}_*.csv"))[:-7]:
                old.unlink(missing_ok=True)
            return df
        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"  {name} unavailable ({e})")

    older = sorted(data_dir.glob(f"ratings_{season}_*.csv"))
    if older:
        print(f"  Using last saved ratings {older[-1].name}")
        df = _read_saved(older[-1])
        df.attrs["source"] = f"saved copy {older[-1].stem.split('_')[-1]}"
        return df
    raise RuntimeError("no ratings source worked. " + " | ".join(errors))


def _read_saved(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.attrs["source"] = "saved copy"
    return df
