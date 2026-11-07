"""Prediction-market win probabilities from Kalshi and Polymarket.

Both are public, no-key APIs. They list game-winner markets, not point spreads,
so these give an implied win % for each team that we compare to the model's
win %. If a market isn't listed for a game (common for small-conference
games) the columns are left blank.

Market listings change: if a source finds nothing for a full slate, check the
console message and set KALSHI_SERIES / POLYMARKET_SERIES_ID in config.py.
"""

from __future__ import annotations

VERSION = "2026-11-07.2"

import json
from datetime import datetime, timedelta

import requests

import config
from names import key

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
POLY = "https://gamma-api.polymarket.com"
_SKIP_WORDS = ("women", "half", "total", "spread", "season", "wins", "champion", "tournament",
               "seed", "upset", "mvp", "conference", "march", "final four", "points")


def _get(url, params=None):
    r = requests.get(url, params=params, headers={"User-Agent": config.USER_AGENT}, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _when(text):
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except Exception:
        return None


# --------------------------------------------------------------------------- Kalshi
def _kalshi_series() -> list[str]:
    if config.KALSHI_SERIES:
        return list(config.KALSHI_SERIES)
    data = _get(f"{KALSHI}/series", {"category": "Sports"})
    out = []
    for s in data.get("series", []):
        title = (s.get("title") or "").lower()
        if "college basketball" in title and "men" in title and not any(w in title for w in _SKIP_WORDS):
            out.append(s["ticker"])
    return out


def _kalshi_price(m: dict):
    bid, ask = _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars"))
    if bid is None and m.get("yes_bid") is not None:  # older cent fields
        bid, ask = _f(m.get("yes_bid")) / 100, (_f(m.get("yes_ask")) or 0) / 100
    if bid and ask and 0 < bid <= ask < 1:
        return (bid + ask) / 2
    last = _f(m.get("last_price_dollars"))
    if last is None and m.get("last_price") is not None:
        last = _f(m.get("last_price")) / 100
    return last if last and 0 < last < 1 else None


def kalshi() -> tuple[list[dict], str]:
    series = _kalshi_series()
    if not series:
        return [], "Kalshi: no men's college basketball game series listed right now"
    out = []
    for tk in series:
        cursor = None
        for _ in range(10):
            params = {"series_ticker": tk, "status": "open", "with_nested_markets": "true", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = _get(f"{KALSHI}/events", params)
            for ev in data.get("events", []):
                if ev.get("series_ticker") and ev["series_ticker"] != tk:
                    continue
                probs, when = {}, None
                for m in ev.get("markets", []):
                    team, p = m.get("yes_sub_title") or "", _kalshi_price(m)
                    if team and p is not None:
                        probs[team] = p
                    when = when or _when(m.get("expected_expiration_time") or m.get("close_time"))
                if len(probs) >= 1:
                    out.append({"source": "kalshi", "probs": probs, "when": when, "title": ev.get("title", "")})
            cursor = data.get("cursor")
            if not cursor:
                break
    return out, f"Kalshi: {len(out)} open game markets ({', '.join(series)})"


# ----------------------------------------------------------------------- Polymarket
def _poly_series() -> str | None:
    if config.POLYMARKET_SERIES_ID:
        return str(config.POLYMARKET_SERIES_ID)
    for s in _get(f"{POLY}/sports"):
        code, name = (s.get("sport") or "").lower(), (s.get("name") or "").lower()
        if code in ("cbb", "ncaab", "ncaamb", "mcbb") or ("college basketball" in name and "women" not in name):
            return str(s.get("series"))
    return None


def polymarket() -> tuple[list[dict], str]:
    sid = _poly_series()
    if not sid:
        return [], "Polymarket: no men's college basketball series listed right now"
    out = []
    for offset in range(0, 1000, 200):
        evs = _get(f"{POLY}/events", {"series_id": sid, "closed": "false", "active": "true",
                                      "limit": 200, "offset": offset})
        if not evs:
            break
        for ev in evs:
            if str((ev.get("series") or [{}])[0].get("id", sid)) not in (sid, "None"):
                continue
            for m in ev.get("markets", []):
                smt = (m.get("sportsMarketType") or "moneyline").lower()
                if smt != "moneyline":
                    continue
                try:
                    names = json.loads(m.get("outcomes") or "[]")
                    prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
                except Exception:
                    continue
                if len(names) != 2 or len(prices) != 2 or {n.lower() for n in names} == {"yes", "no"}:
                    continue
                when = _when(m.get("gameStartTime") or ev.get("startTime") or ev.get("endDate"))
                out.append({"source": "poly", "probs": dict(zip(names, prices)), "when": when,
                            "title": ev.get("title", "")})
                break
        if len(evs) < 200:
            break
    return out, f"Polymarket: {len(out)} open game markets (series {sid})"


# --------------------------------------------------------------------------- attach
def _keys(t: dict, torvik_name: str | None) -> set[str]:
    ks = {key(t["display"]), key(t["location"]), key(t["short"]), t["abbr"].lower()}
    if torvik_name:
        ks.add(key(torvik_name))
    return {k for k in ks if k}


def attach(games: list[dict], rows_by_id: dict, entries: list[dict]) -> None:
    for g in games:
        row = rows_by_id.get(g["game_id"], {})
        hk, ak = _keys(g["home"], row.get("t2")), _keys(g["away"], row.get("t1"))
        for e in entries:
            if e["when"] and g.get("start") and abs(e["when"] - g["start"]) > timedelta(hours=96):
                continue
            ph = pa = None
            for name, p in e["probs"].items():
                k = key(name)
                if k in hk:
                    ph = p
                elif k in ak:
                    pa = p
            if ph is None and pa is None:
                continue
            if ph is not None and pa is not None and ph + pa > 0:
                prob = ph / (ph + pa)
            elif ph is not None and len(e["probs"]) == 1:
                prob = ph
            elif pa is not None and len(e["probs"]) == 1:
                prob = 1 - pa
            else:
                continue
            g[f"{e['source']}_home_prob"] = prob
            break


def fetch_all() -> tuple[list[dict], list[str]]:
    entries, msgs = [], []
    for name, fn, on in (("Kalshi", kalshi, config.USE_KALSHI), ("Polymarket", polymarket, config.USE_POLYMARKET)):
        if not on:
            continue
        try:
            e, msg = fn()
            entries += e
            msgs.append(msg)
        except Exception as ex:
            msgs.append(f"{name}: unavailable ({ex.__class__.__name__})")
    return entries, msgs
