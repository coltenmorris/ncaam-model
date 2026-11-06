"""Multi-sportsbook lines from The Odds API (the-odds-api.com).

Free key: 500 requests/month. One call returns every NCAAB game at every US
book, so this program uses about 2 requests per run (spreads + moneylines).
"""
from __future__ import annotations

import os
import statistics
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests

import config
from names import key

URL = "https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds"


def api_key(root: Path) -> str:
    k = (config.ODDS_API_KEY or "").strip() or os.environ.get("ODDS_API_KEY", "").strip()
    f = root / "data" / "odds_api_key.txt"
    if not k and f.exists():
        k = f.read_text(encoding="utf-8").strip()
    return k


def fetch(root: Path) -> tuple[list[dict], str]:
    """Return (events, status message)."""
    k = api_key(root)
    if not k:
        return [], "The Odds API: no key set (see README), skipped"
    params = {
        "apiKey": k,
        "regions": config.ODDS_API_REGIONS,
        "markets": config.ODDS_API_MARKETS,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    if config.ODDS_API_BOOKMAKERS:
        params["bookmakers"] = config.ODDS_API_BOOKMAKERS
        params.pop("regions")
    resp = requests.get(URL, params=params, timeout=config.HTTP_TIMEOUT)
    if resp.status_code == 401:
        return [], "The Odds API: key rejected (check data/odds_api_key.txt)"
    if resp.status_code == 429:
        return [], "The Odds API: monthly request limit reached"
    resp.raise_for_status()
    left = resp.headers.get("x-requests-remaining", "?")
    return resp.json(), f"The Odds API: {len(resp.json())} games, {left} requests left this month"


def _no_vig(p_home: float | None, p_away: float | None):
    if p_home is None or p_away is None:
        return None
    return p_home / (p_home + p_away)


def american_to_prob(price) -> float | None:
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    if price == 0:
        return None
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def _same_team(odds_name: str, espn_team: dict) -> bool:
    k = key(odds_name)
    return k in {key(espn_team["display"]), key(espn_team["location"]), key(espn_team["short"])}


def attach(games: list[dict], events: list[dict]) -> None:
    """Add consensus / best lines and per-book lines to each ESPN game."""
    for g in games:
        g.setdefault("books", {})
        start = g.get("start")
        for ev in events:
            h, a = ev.get("home_team", ""), ev.get("away_team", "")
            straight = _same_team(h, g["home"]) and _same_team(a, g["away"])
            swapped = _same_team(h, g["away"]) and _same_team(a, g["home"])
            if not (straight or swapped):
                continue
            try:
                ct = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
                if start and abs(ct - start) > timedelta(hours=18):
                    continue
            except Exception:
                pass
            for bk in ev.get("bookmakers", []):
                book = {}
                for m in bk.get("markets", []):
                    for o in m.get("outcomes", []):
                        is_home = _same_team(o.get("name", ""), g["home"])
                        is_away = _same_team(o.get("name", ""), g["away"])
                        side = "home" if is_home else "away" if is_away else None
                        if not side:
                            continue
                        if m.get("key") == "spreads" and o.get("point") is not None:
                            book[f"{side}_point"] = float(o["point"])
                            book[f"{side}_price"] = o.get("price")
                        elif m.get("key") == "h2h":
                            book[f"ml_{side}"] = o.get("price")
                if book:
                    g["books"][bk.get("title") or bk.get("key")] = book
            break
        summarize(g)


def consensus(points: list[float]) -> float:
    """Most common line across books; ties go to the one nearest the median."""
    counts = Counter(points)
    top = max(counts.values())
    tied = [p for p, c in counts.items() if c == top]
    med = statistics.median(points)
    return min(tied, key=lambda p: (abs(p - med), abs(p)))


def summarize(g: dict) -> None:
    books = g.get("books") or {}
    home_pts = [b["home_point"] for b in books.values() if "home_point" in b]
    if home_pts:
        g["cons_home_line"] = consensus(home_pts)
        g["best_home_line"] = max(home_pts)   # most points for the home side
        g["best_away_line"] = -min(home_pts)  # most points for the away side
        g["n_books"] = len(home_pts)
    probs = []
    for b in books.values():
        p = _no_vig(american_to_prob(b.get("ml_home")), american_to_prob(b.get("ml_away")))
        if p is not None:
            probs.append(p)
    if probs:
        g["book_home_prob"] = statistics.mean(probs)
    else:
        p = _no_vig(american_to_prob(g.get("ml_home")), american_to_prob(g.get("ml_away")))
        if p is not None:
            g["book_home_prob"] = p
