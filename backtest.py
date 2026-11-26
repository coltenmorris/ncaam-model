"""Backtest the current rules against every game in data/model_dataset.csv.

Each game is re-scored with today's settings (config.py):
  * projected margin = ESPN current BPI (away - home) - home court, or the
    locally stored ratings' projection when ESPN's is missing,
  * Edge = projected margin + closing line, pick = the side the Edge favors,
  * confidence tier from model.cover_tier (Check / High / Medium / Low),
  * graded against the closing line with the final score.

Run it by hand:   python backtest.py
It prints the record for every tier, and PASS when High-confidence picks win
at least config.BACKTEST_TARGET (52%) of graded bets. The daily run calls
run() too, and the Portfolio tab is built from its picks.

Note: the rules were chosen by testing on this same data, so the record on
games before the rules were set (2026-11-25) flatters them. Games after that
date are a true out-of-sample test.
"""
from __future__ import annotations

VERSION = "2026-11-25.1"

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import model  # noqa: E402

DATASET = ROOT / "data" / "model_dataset.csv"
RULES_SET_ON = "2026-11-25"
TIERS = ("High", "Medium", "Low", "Check")


def _num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def _bool(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "yes")


def score(df: pd.DataFrame) -> list[dict]:
    """One pick per game with a closing line, re-scored with the current rules."""
    bets = []
    for _, r in df.iterrows():
        t1_line = _num(r.get("close_t1_line"))
        if t1_line is None:
            continue
        neutral = _bool(r.get("neutral"))
        local = _num(r.get("proj_t1_margin"))
        if _num(r.get("espn_proj_t1_margin")) is None:
            # proj_t1_margin was the locally stored ratings' projection
            proj, src = local, "Local ratings"
        else:
            proj, src = model.projection(r.get("espn_t1_bpi_now"), r.get("espn_t2_bpi_now"), local, neutral)
        if proj is None:
            continue
        edge = proj + t1_line
        if edge == 0:
            continue
        side = "T1" if edge > 0 else "T2"
        pick_line = t1_line if side == "T1" else -t1_line
        spread = abs(t1_line)
        p = model.cover_probability(edge, spread)
        tier = model.cover_tier(p, edge, spread, pick_line)
        s1, s2 = _num(r.get("t1_score")), _num(r.get("t2_score"))
        result = None
        if s1 is not None and s2 is not None:
            ats = (s1 - s2 + t1_line) * (1 if side == "T1" else -1)
            result = "W" if ats > 0 else "L" if ats < 0 else "P"
        bets.append({
            "date": str(r["date"]), "start": r.get("start"), "game_id": str(r["game_id"]),
            "away": r["away"], "home": r["home"], "side": side,
            "team": r["away"] if side == "T1" else r["home"], "line": pick_line,
            "edge": round(abs(edge), 2), "cover": round(p, 4), "conf": tier, "proj_source": src,
            "result": result, "s1": s1, "s2": s2,
            "out_pick": _num(r.get("t1_regulars_out" if side == "T1" else "t2_regulars_out")),
            "out_opp": _num(r.get("t2_regulars_out" if side == "T1" else "t1_regulars_out")),
        })
    bets.sort(key=lambda b: (b["date"], str(b["start"] or "")))
    return bets


def _summary(bets: list[dict]) -> dict:
    w = sum(b["result"] == "W" for b in bets)
    l = sum(b["result"] == "L" for b in bets)
    p = sum(b["result"] == "P" for b in bets)
    return {"w": w, "l": l, "p": p, "rate": (w / (w + l)) if w + l else None,
            "units": round(w * 100 / 110 - l, 2), "pending": sum(b["result"] is None for b in bets)}


def run(path: Path = DATASET) -> dict:
    df = pd.read_csv(path, dtype={"game_id": str, "date": str})
    bets = score(df)
    tiers = {t: _summary([b for b in bets if b["conf"] == t]) for t in TIERS}
    tiers["Overall"] = _summary(bets)
    after = [b for b in bets if b["date"] > RULES_SET_ON and b["conf"] == "High"]
    known = [b for b in bets if b["conf"] == "High" and b["out_pick"] is not None and b["out_opp"] is not None]
    availability = {
        "No regulars out": _summary([b for b in known if not b["out_pick"] and not b["out_opp"]]),
        "Picked team missing a regular": _summary([b for b in known if b["out_pick"]]),
        "Opponent missing a regular": _summary([b for b in known if b["out_opp"] and not b["out_pick"]]),
    }
    target = float(getattr(config, "BACKTEST_TARGET", 0.52))
    hi = tiers["High"]
    return {
        "games": sum(b["result"] is not None for b in bets),
        "tiers": tiers,
        "high_after_rules": _summary(after),
        "availability": availability,
        "rules_set_on": RULES_SET_ON,
        "target": target,
        "passed": hi["rate"] is not None and hi["rate"] >= target,
        "bets": bets,
    }


# Edge picks logged before the new rules went live (the 2026-11-26 03:54 ET
# merge) came from the old model. rebuild_history() swaps them for the
# backtest picks so the History and Success Rate tabs match the backtest.
OLD_MODEL_BEFORE = "2026-11-26 03:54"


def rebuild_history(history: Path, dataset: Path = DATASET, before: str = OLD_MODEL_BEFORE) -> dict:
    """Replace old-model Edge picks in pick_history.csv with the backtest pick
    for the same game. The replaced picks are saved (once) to
    pick_history_old_model_edge.csv. Running it again changes nothing."""
    import tracker
    from datetime import datetime
    hist = tracker.load(history)
    is_edge = hist["pick_type"] == "Edge"
    logged = hist["logged_at"].fillna("").astype(str)
    old = is_edge & (logged < before) & (logged != "backtest")
    backup = history.with_name("pick_history_old_model_edge.csv")
    if old.any():
        prev = tracker.load(backup) if backup.exists() else pd.DataFrame(columns=tracker.COLUMNS)
        tracker.save(pd.concat([prev, hist[old]], ignore_index=True), backup)
    old_games = set(hist.loc[old, "game_id"].astype(str))
    kept_edge = set(hist.loc[is_edge & ~old, "game_id"].astype(str))
    ds = pd.read_csv(dataset, dtype={"game_id": str, "date": str})
    src = dict(zip(ds["game_id"].astype(str), ds["close_source"]))
    cutoff_day = before[:10]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for b in score(ds):
        gid = b["game_id"]
        if gid in kept_edge or not (gid in old_games or b["date"] < cutoff_day):
            continue
        rows.append({
            "date": b["date"], "start": b["start"], "game_id": gid, "pick_type": "Edge",
            "t1": b["away"], "t2": b["home"], "pick_team": b["team"], "pick_side": b["side"],
            "pick_line": b["line"], "line_source": f"Backtest: closing line ({src.get(gid) or 'consensus'})",
            "confidence": b["conf"], "edge": b["edge"], "cover_prob": b["cover"],
            "result": b["result"], "t1_score": b["s1"], "t2_score": b["s2"],
            "logged_at": "backtest", "graded_on": now if b["result"] else None, "confidence_logged": b["conf"],
        })
    new = hist[~old]
    if rows:
        new = pd.concat([new, pd.DataFrame(rows, columns=tracker.COLUMNS)], ignore_index=True)
    new = new.sort_values(["date", "start", "game_id"], na_position="last", kind="stable")
    tracker.save(new, history)
    return {"removed": int(old.sum()), "added": len(rows), "dropped_games": len(old_games - {r["game_id"] for r in rows})}


def _halves(bets: list[dict], tier: str) -> str:
    graded = [b for b in bets if b["result"] and b["conf"] == tier]
    dates = sorted({b["date"] for b in graded})
    if len(dates) < 2:
        return ""
    mid = dates[len(dates) // 2]
    a = _summary([b for b in graded if b["date"] < mid])
    b = _summary([b for b in graded if b["date"] >= mid])
    f = lambda s: f"{s['w']}-{s['l']} ({s['rate']:.1%})" if s["rate"] is not None else "n/a"
    return f"before {mid}: {f(a)} | from {mid}: {f(b)}"


def main() -> int:
    if "--rebuild-history" in sys.argv:
        r = rebuild_history(ROOT / "data" / "pick_history.csv")
        print(f"History rebuilt: {r['removed']} old-model Edge picks replaced by {r['added']} backtest picks "
              f"({r['dropped_games']} games had no backtest pick; originals in pick_history_old_model_edge.csv)\n")
    bt = run()
    print(f"Backtest of {bt['games']} graded games in {DATASET.name} (closing lines, -110)")
    print(f"Rules: underdog picks, High = edge {config.HIGH_EDGE_MIN:g}+ pts on a spread of "
          f"{config.HIGH_SPREAD_MIN:g}+, Check = edge {config.CHECK_EDGE:g}+, favorites = Low\n")
    print(f"{'Tier':8s} {'Record':>12s} {'Win %':>7s} {'Units':>8s}")
    for t in ("High", "Medium", "Low", "Check", "Overall"):
        s = bt["tiers"][t]
        rate = f"{s['rate']:.1%}" if s["rate"] is not None else "n/a"
        print(f"{t:8s} {s['w']:>5d}-{s['l']:<4d}{s['p']:>2d}P {rate:>7s} {s['units']:>+8.1f}")
    print(f"\nHigh, split in half by date: {_halves(bt['bets'], 'High')}")
    a = bt["high_after_rules"]
    if a["w"] + a["l"]:
        print(f"High since the rules were set ({bt['rules_set_on']}): {a['w']}-{a['l']} ({a['rate']:.1%})")
    av = bt["availability"]
    if any(v["w"] + v["l"] for v in av.values()):
        print("\nHigh picks by player availability (regulars who sat out the team's last game):")
        for k, v in av.items():
            rate = f"{v['rate']:.1%}" if v["rate"] is not None else "n/a"
            print(f"  {k:32s} {v['w']:>4d}-{v['l']:<4d} {rate:>7s} {v['units']:>+7.1f}")
    else:
        print("\nPlayer availability: not logged yet (players.py fills it in on the next daily runs).")
    print(f"\nTarget: High picks win {bt['target']:.0%}+ -> {'PASS' if bt['passed'] else 'BELOW TARGET'}")
    return 0 if bt["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
