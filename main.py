"""
NCAAM Model: run this file (PyCharm: right-click > Run 'main').

Each run:
  1. grades earlier picks with ESPN final scores,
  2. downloads fresh Barttorvik ratings, the ESPN schedule, sportsbook lines
     (ESPN/DraftKings + The Odds API) and prediction-market prices
     (Kalshi, Polymarket),
  3. runs the model, logs the picks, and updates output/NCAAM_Dashboard.xlsx
     (Today, Success Rate, History, Full Slate, Odds by Book, Ratings).

To have it run by itself every day, run setup_daily_tasks.py once.

Options (PyCharm: Run > Edit Configurations > Parameters):
  --date 2026-11-14     run a different date (also: today, tomorrow, yesterday)
  --legacy              reproduce the v5.1 spreadsheet math exactly
  --ratings-file PATH   use a ratings CSV you saved instead of downloading
  --grade-only          only grade past picks and refresh the record
  --no-log              do not save picks to the history file
  --scheduled           used by the daily task: writes output to a log file
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

import config  # noqa: E402
import espn, markets, odds_api, report, torvik, tracker, web  # noqa: E402
from model import build_rows, run_model  # noqa: E402
from names import TeamMatcher  # noqa: E402

VERSION = "2026-11-07.2"
CODE_FILES = ("config", "espn", "markets", "model", "names", "odds_api", "report", "torvik", "tracker", "web")


def code_check() -> tuple[str, list[str]]:
    """Every .py file carries a VERSION. List any that are older than main.py
    (a file that didn't get replaced during an upload)."""
    import importlib
    stale = []
    for name in CODE_FILES:
        try:
            v = getattr(importlib.import_module(name), "VERSION", "old")
        except Exception:
            v = "missing"
        if v != VERSION:
            stale.append(f"{name}.py ({v})")
    return VERSION, stale


DATA = ROOT / "data"
OUTPUT = ROOT / "output"
LOGS = OUTPUT / "logs"
HISTORY = DATA / "pick_history.csv"
ALIASES = ROOT / "team_aliases.csv" if (ROOT / "team_aliases.csv").exists() else DATA / "team_aliases.csv"
DASHBOARD = OUTPUT / "NCAAM_Dashboard.xlsx"
DOCS = ROOT / "docs"  # GitHub Pages site


def parse_day(text: str) -> date:
    t = text.strip().lower()
    if t == "today":
        return date.today()
    if t == "tomorrow":
        return date.today() + timedelta(days=1)
    if t == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(text)


def open_file(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
    except Exception:
        pass


def start_log_file() -> Path:
    LOGS.mkdir(parents=True, exist_ok=True)
    for old in sorted(LOGS.glob("run_*.log"))[:-60]:
        old.unlink(missing_ok=True)
    path = LOGS / f"run_{datetime.now():%Y-%m-%d_%H%M}.log"
    f = open(path, "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f
    return path


def save_workbook(fn, path: Path, notes: list[str]) -> Path | None:
    try:
        return fn(path)
    except PermissionError:
        alt = path.with_name(f"{path.stem} ({datetime.now():%H%M}){path.suffix}")
        notes.append(f"{path.name} was open in Excel, so this update was saved as {alt.name}")
        print(f"  {path.name} is open in Excel; saved {alt.name} instead.")
        return fn(alt)


def run(args) -> int:
    if args.legacy:
        config.LEGACY_EXCEL_MODE = True
    for d in (DATA, OUTPUT, OUTPUT / "daily", DATA / "slates"):
        d.mkdir(parents=True, exist_ok=True)
    day = parse_day(args.date)
    notes = [f"Run started {datetime.now():%Y-%m-%d %H:%M}"]
    ver, stale = code_check()
    if stale:
        msg = f"OUT OF DATE FILES (re-upload these): {', '.join(stale)}"
        print(f"\nWARNING: {msg}\n")
        notes.append(msg)
    notes.append(f"Code version {ver}" + ("" if stale else " (all files current)"))

    print("Grading earlier picks...")
    n = tracker.grade(HISTORY)
    print(f"  {n} pick(s) graded.")
    notes.append(f"Graded {n} pick(s)")
    try:
        rl = tracker.relabel_edge_picks(HISTORY)
        if rl:
            notes.append(f"Re-scored {rl} Edge pick(s) with the current confidence rules")
    except Exception as e:
        notes.append(f"Confidence re-score skipped ({e.__class__.__name__})")

    print(f"Downloading team ratings (season {torvik.season_for(day)})...")
    try:
        ratings = torvik.load_ratings(day, DATA, args.ratings_file)
    except Exception as e:
        print(f"\nERROR loading ratings: {e}")
        return 1
    src = ratings.attrs.get("source", "Barttorvik")
    print(f"  {len(ratings)} teams from {src}.")
    notes.append(f"Ratings: {len(ratings)} teams from {src}")
    for err in ratings.attrs.get("skipped", []):
        notes.append(f"Ratings source skipped: {err}")

    games, results, rows = [], pd.DataFrame(), []
    if not args.grade_only:
        print(f"Downloading ESPN schedule for {day:%Y-%m-%d}...")
        try:
            games = espn.get_games(day)
        except Exception as e:
            print(f"\nERROR loading ESPN schedule: {e}")
            return 1
        print(f"  {len(games)} games.")
        notes.append(f"ESPN: {len(games)} games, {sum(g.get('spread') is not None for g in games)} with a DraftKings line")

        if games:
            print("Downloading sportsbook lines...")
            try:
                events, msg = odds_api.fetch(ROOT)
                odds_api.attach(games, events)
            except Exception as e:
                msg = f"The Odds API: unavailable ({e.__class__.__name__}: {e})"
                for g in games:
                    odds_api.summarize(g)
            print(f"  {msg}")
            notes.append(msg)

            matcher = TeamMatcher(ratings["team"].tolist(), ALIASES)
            pre = {r["game_id"]: r for r in build_rows(games, matcher)}
            print("Downloading prediction markets...")
            entries, msgs = markets.fetch_all()
            markets.attach(games, pre, entries)
            for m in msgs:
                print(f"  {m}")
            notes += msgs

            rows = build_rows(games, matcher)
            results = run_model(rows, ratings)

            if matcher.unmatched:
                print("\nTeams not in Barttorvik (usually non-D1 opponents; those games are skipped).")
                print("If one IS a D1 team, add it to data/team_aliases.csv:")
                for name in sorted(matcher.unmatched):
                    print(f"   - {name}")

            if not args.no_log and day >= date.today():
                added = tracker.log_picks(results, day, HISTORY)
                print(f"\n{added} pick(s) logged for games that haven't started.")
                notes.append(f"Logged {added} pick(s)")

            report._public(results).to_csv(DATA / "slates" / f"slate_{day:%Y-%m-%d}.csv", index=False)

    record = tracker.record_summary(HISTORY)
    trend = tracker.daily_trend(HISTORY, "Edge")
    report.print_console(results, day, record, notes[1:] if args.scheduled else [])

    history = tracker.load(HISTORY)

    def build(p):
        return report.write_dashboard(p, day, results, rows, ratings, history, record, trend, notes)

    saved = save_workbook(build, DASHBOARD, notes)
    if not results.empty and day >= date.today() - timedelta(days=1):
        save_workbook(build, OUTPUT / "daily" / f"NCAAM_Model_{day:%Y-%m-%d}.xlsx", notes)
    print(f"Dashboard saved: {saved}")

    if config.WEB_DASHBOARD:
        import shutil
        payload = web.build_payload(day, results, record, trend, history, games, rows, ratings,
                                    src, DATA, notes)
        page = web.write_site(DOCS, payload)
        if saved:
            shutil.copyfile(saved, DOCS / "NCAAM_Dashboard.xlsx")
        if HISTORY.exists():
            shutil.copyfile(HISTORY, DOCS / "pick_history.csv")
        print(f"Web dashboard saved: {page}")
    if config.OPEN_REPORT_WHEN_DONE and not args.scheduled and saved:
        open_file(saved)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NCAAM betting model")
    ap.add_argument("--date", default="today")
    ap.add_argument("--legacy", action="store_true")
    ap.add_argument("--ratings-file")
    ap.add_argument("--grade-only", action="store_true")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--scheduled", action="store_true")
    args = ap.parse_args(argv)
    if args.scheduled:
        start_log_file()
    try:
        return run(args)
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if args.scheduled:
            sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
