"""Pull the daily schedule, betting lines, and final scores from ESPN.

Replaces pasting the ESPN schedule page into the "ESPN Game Schedule" sheet.
"""

from __future__ import annotations

VERSION = "2026-11-07.2"

import re
from datetime import date, datetime

import requests

import config

_LINE_RE = re.compile(r"^\s*([A-Za-z0-9&.'\-]+)\s+([+-]?\d+(?:\.\d+)?)\s*$")


def fetch_scoreboard(day: date) -> dict:
    params = {"dates": day.strftime("%Y%m%d"), "groups": config.ESPN_GROUP, "limit": 500}
    resp = requests.get(
        config.ESPN_SCOREBOARD_URL,
        params=params,
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_odds(comp: dict, away: dict, home: dict) -> dict:
    """Return favorite abbreviation, spread size, O/U and the raw line text."""
    out = {"line_text": "", "fav_abbr": None, "spread": None, "over_under": None,
           "ml_home": None, "ml_away": None, "spread_price_home": None,
           "spread_price_away": None, "provider": None}
    odds_list = comp.get("odds") or []
    if not odds_list:
        return out
    odds = odds_list[0]
    out["over_under"] = _num(odds.get("overUnder"))
    details = (odds.get("details") or "").strip()
    out["line_text"] = details

    if details.upper() in ("EVEN", "PK", "PICK", "PICK'EM"):
        out["spread"] = 0.0
        _moneylines(odds, out)
        return out

    m = _LINE_RE.match(details)
    if m:
        abbr, val = m.group(1).upper(), abs(float(m.group(2)))
        if abbr == away["abbr"].upper():
            out["fav_abbr"] = away["abbr"]
        elif abbr == home["abbr"].upper():
            out["fav_abbr"] = home["abbr"]
        out["spread"] = val
        if out["fav_abbr"]:
            _moneylines(odds, out)
            return out

    # Fallback: numeric spread is from the home team's point of view.
    spread = _num(odds.get("spread"))
    if spread is not None:
        out["spread"] = abs(spread)
        if spread < 0:
            out["fav_abbr"] = home["abbr"]
        elif spread > 0:
            out["fav_abbr"] = away["abbr"]
    for side, team in (("homeTeamOdds", home), ("awayTeamOdds", away)):
        if (odds.get(side) or {}).get("favorite") is True:
            out["fav_abbr"] = team["abbr"]
    _moneylines(odds, out)
    if not out["line_text"] and out["spread"] is not None:
        out["line_text"] = f"{out['fav_abbr']} -{out['spread']:g}" if out["fav_abbr"] else "EVEN"
    return out


def _moneylines(odds: dict, out: dict) -> None:
    """American moneylines, if ESPN includes them (two known layouts)."""
    for side in ("home", "away"):
        ml = _num((odds.get(f"{side}TeamOdds") or {}).get("moneyLine"))
        if ml is None:
            node = ((odds.get("moneyline") or {}).get(side) or {})
            node = node.get("close") or node.get("open") or {}
            ml = _num(str(node.get("odds", "")).replace("+", ""))
        out[f"ml_{side}"] = ml
        # spread price (DraftKings juice), e.g. -110
        price = _num((odds.get(f"{side}TeamOdds") or {}).get("spreadOdds"))
        if price is None:
            node = ((odds.get("pointSpread") or {}).get(side) or {})
            node = node.get("close") or node.get("open") or {}
            price = _num(str(node.get("odds", "")).replace("+", ""))
        out[f"spread_price_{side}"] = price
    out["provider"] = ((odds.get("provider") or {}).get("name")) or "DraftKings"


def is_pregame(g: dict) -> bool:
    """True until tip-off (ESPN state 'pre' and start time still in the future)."""
    if g.get("state") and g["state"] != "pre":
        return False
    start = g.get("start")
    if start is not None:
        try:
            return start > datetime.now(start.tzinfo)
        except Exception:
            pass
    return True


def home_line(g: dict):
    """Spread from the home team's view (negative = home favored)."""
    if g.get("spread") is None:
        return None
    if g["spread"] == 0:
        return 0.0
    if g.get("fav_abbr") == g["home"]["abbr"]:
        return -g["spread"]
    if g.get("fav_abbr") == g["away"]["abbr"]:
        return g["spread"]
    return None


def _team(c: dict) -> dict:
    t = c.get("team") or {}
    return {
        "id": str(t.get("id", "")),
        "location": t.get("location") or "",
        "short": t.get("shortDisplayName") or "",
        "display": t.get("displayName") or "",
        "abbr": t.get("abbreviation") or "",
        "score": _num(c.get("score")),
    }


def parse_games(payload: dict) -> list[dict]:
    games = []
    for ev in payload.get("events", []):
        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        teams = {c.get("homeAway"): _team(c) for c in comp.get("competitors", [])}
        if "home" not in teams or "away" not in teams:
            continue
        away, home = teams["away"], teams["home"]

        venue = comp.get("venue") or {}
        addr = venue.get("address") or {}
        venue_str = ", ".join(x for x in [venue.get("fullName"), addr.get("city"), addr.get("state")] if x)

        tv = []
        for b in comp.get("broadcasts") or []:
            tv.extend(b.get("names") or [])

        status = ((comp.get("status") or ev.get("status") or {}).get("type")) or {}
        start = ev.get("date") or comp.get("date")
        try:
            start_local = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone()
        except Exception:
            start_local = None

        g = {
            "game_id": str(ev.get("id")),
            "start": start_local,
            "time": start_local.strftime("%I:%M %p").lstrip("0") if start_local else "",
            "tv": ", ".join(dict.fromkeys(tv)),
            "venue": venue_str,
            "neutral": bool(comp.get("neutralSite")),
            "completed": bool(status.get("completed")),
            "status": status.get("shortDetail") or status.get("description") or "",
            "state": status.get("state") or ("post" if status.get("completed") else "pre"),
            "away": away,
            "home": home,
        }
        g.update(_parse_odds(comp, away, home))
        if not is_pregame(g):
            # Once a game tips off, the feed's odds are live in-game odds, not the
            # pregame line the pick was made on. Drop them; main.py restores the
            # pregame line from the pick log.
            for k in ("spread", "fav_abbr", "ml_home", "ml_away", "spread_price_home", "spread_price_away"):
                g[k] = None
            g["line_text"] = ""
        games.append(g)
    return games


def get_games(day: date) -> list[dict]:
    return parse_games(fetch_scoreboard(day))


SUMMARY_URL = ("https://site.api.espn.com/apis/site/v2/sports/basketball/"
               "mens-college-basketball/summary")


def get_game_result(game_id: str) -> dict | None:
    """Final score for one game from ESPN's game page data. Used when a game
    doesn't appear on the day's scoreboard (late tip, date shift, etc.)."""
    r = requests.get(SUMMARY_URL, params={"event": game_id},
                     headers={"User-Agent": config.USER_AGENT}, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    comp = ((r.json().get("header") or {}).get("competitions") or [{}])[0]
    teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
    if "home" not in teams or "away" not in teams:
        return None
    status = ((comp.get("status") or {}).get("type")) or {}
    return {
        "game_id": str(game_id),
        "completed": bool(status.get("completed")),
        "away": {"score": _num(teams["away"].get("score"))},
        "home": {"score": _num(teams["home"].get("score"))},
    }
