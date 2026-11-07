"""Multi-sportsbook lines from The Odds API (the-odds-api.com).

Free key: 500 requests/month. One call returns every NCAAB game at every US
book, so this program uses about 2 requests per run (spreads + moneylines).
"""

from __future__ import annotations

VERSION = "2026-11-07.2"

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
    from espn import is_pregame
    for g in games:
        g.setdefault("books", {})
        start = g.get("start")
        if not is_pregame(g):      # started: these would be live in-game odds
            summarize(g)
            continue
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


# Biggest US sportsbooks first. Used when DraftKings has no line for a game.
BOOK_PRIORITY = [
    ("draftkings", "DraftKings", "DK"), ("fanduel", "FanDuel", "FD"), ("betmgm", "BetMGM", "MGM"),
    ("caesars", "Caesars", "CZR"), ("williamhill", "Caesars", "CZR"), ("espn", "ESPN BET", "ESPN"),
    ("thescore", "theScore Bet", "SCORE"), ("fanatics", "Fanatics", "FAN"), ("betrivers", "BetRivers", "BR"),
    ("hard rock", "Hard Rock Bet", "HR"), ("bet365", "bet365", "365"), ("bovada", "Bovada", "BOV"),
    ("betonline", "BetOnline", "BOL"), ("lowvig", "LowVig", "LV"), ("mybookie", "MyBookie", "MYB"),
    ("betus", "BetUS", "BUS"),
]


def book_tag(name: str) -> str:
    n = (name or "").lower()
    for key, _, tag in BOOK_PRIORITY:
        if key in n:
            return tag
    return (name or "?")[:4].upper()


def _rank(name: str) -> int:
    n = (name or "").lower()
    for i, (key, _, _) in enumerate(BOOK_PRIORITY):
        if key in n:
            return i
    return len(BOOK_PRIORITY)


def standard_line(g: dict):
    """The line to treat as standard for a game: DraftKings, or the next biggest
    book that has a line. Returns (line dict or None, other books dict)."""
    from espn import home_line
    all_books = dict(g.get("books") or {})
    books = {k: v for k, v in all_books.items() if v.get("home_point") is not None}
    cands = []   # (rank, source name, line dict, odds-api title or None)
    h = home_line(g)
    if h is not None:
        prov = g.get("provider") or "DraftKings"
        cands.append((_rank(prov), prov, {
            "home_pt": h, "away_pt": -h, "home_px": g.get("spread_price_home"), "away_px": g.get("spread_price_away"),
            "home_ml": g.get("ml_home"), "away_ml": g.get("ml_away"), "via": "ESPN schedule"}, None))
    for title, b in books.items():
        cands.append((_rank(title), title, {
            "home_pt": b.get("home_point"), "away_pt": b.get("away_point"), "home_px": b.get("home_price"),
            "away_px": b.get("away_price"), "home_ml": b.get("ml_home"), "away_ml": b.get("ml_away"),
            "via": "The Odds API"}, title))
    if not cands:
        return None, all_books
    # same book from both sources: prefer the ESPN copy (it is what the schedule shows), fill gaps from the API
    cands.sort(key=lambda c: (c[0], c[3] is not None))
    rank, name, line, title = cands[0]
    same = [c for c in cands[1:] if c[0] == rank and rank < len(BOOK_PRIORITY)]
    for c in same:
        for k, v in c[2].items():
            if line.get(k) is None:
                line[k] = v
    used = {c[3] for c in [cands[0]] + same if c[3]}
    others = {k: v for k, v in all_books.items() if k not in used}
    tag = book_tag(name)
    line.update({"source": name, "tag": tag, "is_dk": tag == "DK"})
    return line, others
