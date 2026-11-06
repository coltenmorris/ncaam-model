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


def load_ratings(day: date, data_dir: Path, ratings_file: str | None = None) -> pd.DataFrame:
    """Return the ratings table. Uses a local file if given, else downloads."""
    if ratings_file:
        return _parse(Path(ratings_file).read_text(encoding="utf-8-sig"))

    season = season_for(day)
    cache = data_dir / f"torvik_{season}_{date.today():%Y-%m-%d}.csv"
    if config.CACHE_RATINGS_SAME_DAY and cache.exists():
        return _parse(cache.read_text(encoding="utf-8"))

    url = config.TORVIK_URL.format(season=season)
    try:
        resp = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        df = _parse(resp.text)  # validate before caching
    except Exception as e:
        older = sorted(data_dir.glob(f"torvik_{season}_*.csv"))
        if not older:
            raise
        print(f"  Barttorvik download failed ({e}); using last saved copy {older[-1].name}")
        return _parse(older[-1].read_text(encoding="utf-8"))
    cache.write_text(resp.text, encoding="utf-8")
    for old in sorted(data_dir.glob(f"torvik_{season}_*.csv"))[:-7]:
        old.unlink(missing_ok=True)  # keep the last week of downloads
    return df
