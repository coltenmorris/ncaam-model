"""Console summary and the Excel dashboard."""

from __future__ import annotations

VERSION = "2026-11-07.2"

from datetime import date, datetime
from pathlib import Path

import pandas as pd
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config

TODAY_COLS = [
    "Time", "TV", "T1 Team", "T2 Team", "Line", "Line Source", "Books", "Best T1", "Best T2",
    "Proj T1 Margin", "Edge vs Line (T1)", "Edge Pick", "Edge Size",
    "Model T1 Win%", "Market T1 Win%", "Win% Edge (T1)",
    "Games to Watch", "Watch Pick", "Enhanced Value", "Confidence", "Model Pick",
]

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HIGH_FILL = PatternFill("solid", fgColor="C6EFCE")
MED_FILL = PatternFill("solid", fgColor="FFF2CC")
WATCH_FILL = PatternFill("solid", fgColor="FFEB9C")
SECTION_FILL = PatternFill("solid", fgColor="D9E1F2")

PCT = "0.0%"
SIGNED = "+0.0;-0.0;0.0"
NUM_FORMATS = {
    "Value": "0.00", "OR Value": "0.00", "DR Value": "0.00", "OR1-DR2 Value": "0.00",
    "OR2-DR1 Value": "0.00", "Tempo Mod": "0.000", "Avg Tempo": "0.0", "Wtd Eff": "0.00",
    "Enhanced Value": "0.00", "Proj T1 Margin": SIGNED, "Edge vs Line (T1)": SIGNED, "Edge Size": "0.0",
    "T1 Line": SIGNED, "DK Line (T1)": SIGNED, "Consensus (T1)": SIGNED, "Best T1": SIGNED, "Best T2": SIGNED,
    "OR Diff (HCA)": "0.0", "DR Diff": "0.0", "Success Rate": PCT, "Units": "+0.00;-0.00;0.00",
    "Model T1 Win%": PCT, "Market T1 Win%": PCT, "Book T1 Win%": PCT, "Kalshi T1 Win%": PCT,
    "Poly T1 Win%": PCT, "Win% Edge (T1)": "+0.0%;-0.0%;0.0%", "Day Rate": PCT, "Cumulative Rate": PCT,
    "market_prob": PCT, "model_prob": PCT, "pick_line": SIGNED,
    "adj_o": "0.0", "adj_d": "0.0", "adj_t": "0.0", "net_rtg": "0.0", "barthag": "0.000",
}


def _public(results: pd.DataFrame) -> pd.DataFrame:
    return results[[c for c in results.columns if not c.startswith("_") and c != "game_id"]]


def today_view(results: pd.DataFrame) -> pd.DataFrame:
    if results.empty or "Edge Size" not in results:
        return pd.DataFrame(columns=TODAY_COLS)
    view = results[results["Line"].fillna("") != ""]
    view = view[[c for c in TODAY_COLS if c in view]].copy()
    return view.sort_values("Edge Size", ascending=False, na_position="last")


# ------------------------------------------------------------------------ console
def print_console(results: pd.DataFrame, day: date, record: pd.DataFrame | None, notes: list[str] = ()) -> None:
    print()
    print("=" * 110)
    print(f"  NCAAM MODEL  |  {day:%A, %B %d, %Y}  |  updated {datetime.now():%I:%M %p}  |  "
          f"{'Legacy Excel' if config.LEGACY_EXCEL_MODE else 'Standard'} mode")
    print("=" * 110)
    for n in notes:
        print(f"  {n}")
    if results.empty:
        print("  No Division I games found for this date.")
    else:
        lined = results["Line"].fillna("").ne("").sum()
        print(f"\n  Games: {len(results)}   with a line: {lined}   "
              f"Games to Watch: {(results.get('Games to Watch') == 'YES').sum()}")
        view = today_view(results)
        top = view[view["Edge Size"].fillna(0) >= max(config.EDGE_BUCKETS[1] if len(config.EDGE_BUCKETS) > 1 else 0, 0)]
        cols = ["Time", "T1 Team", "T2 Team", "Line", "Proj T1 Margin", "Edge Pick", "Edge Size",
                "Win% Edge (T1)", "Games to Watch", "Confidence", "Model Pick"]
        if top.empty:
            print("\n  No sportsbook edges of 2+ points right now.")
        else:
            print("\n  Biggest sportsbook edges")
            with pd.option_context("display.max_rows", 60, "display.width", 250, "display.max_colwidth", 26):
                print(top[[c for c in cols if c in top]].head(25).to_string(
                    index=False, float_format=lambda x: f"{x:.2f}"))
    if record is not None and not record.empty:
        print("\n  Success rate")
        print(record.to_string(index=False, formatters={
            "Success Rate": lambda x: "" if pd.isna(x) else f"{x:.1%}",
            "Units": lambda x: "" if pd.isna(x) else f"{x:+.2f}"}))
    print()


# -------------------------------------------------------------------------- excel
def _format_table(ws, df: pd.DataFrame, header_row: int = 1) -> None:
    for cell in ws[header_row]:
        if cell.value is None:
            continue
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cols = list(df.columns)
    for i, col in enumerate(cols, start=1):
        letter = get_column_letter(i)
        sample = [len(str(col))] + [len(str(v)) for v in df[col].head(300) if v is not None]
        ws.column_dimensions[letter].width = max(ws.column_dimensions[letter].width or 0,
                                                  min(max(sample) + 2, 42))
        fmt = NUM_FORMATS.get(col)
        if fmt:
            for row in ws.iter_rows(min_row=header_row + 1, max_row=header_row + len(df), min_col=i, max_col=i):
                row[0].number_format = fmt
    conf_i = cols.index("Confidence") + 1 if "Confidence" in cols else None
    watch_i = cols.index("Games to Watch") + 1 if "Games to Watch" in cols else None
    edge_i = cols.index("Edge Size") + 1 if "Edge Size" in cols else None
    res_i = cols.index("result") + 1 if "result" in cols else None
    for r in range(header_row + 1, header_row + len(df) + 1):
        if conf_i:
            v = ws.cell(r, conf_i).value
            if v == "High":
                ws.cell(r, conf_i).fill, ws.cell(r, conf_i).font = HIGH_FILL, Font(bold=True)
            elif v == "Medium":
                ws.cell(r, conf_i).fill = MED_FILL
        if watch_i and ws.cell(r, watch_i).value == "YES":
            ws.cell(r, watch_i).fill, ws.cell(r, watch_i).font = WATCH_FILL, Font(bold=True)
        if edge_i:
            v = ws.cell(r, edge_i).value
            if isinstance(v, (int, float)) and len(config.EDGE_BUCKETS) > 2 and v >= config.EDGE_BUCKETS[2]:
                ws.cell(r, edge_i).fill, ws.cell(r, edge_i).font = HIGH_FILL, Font(bold=True)
            elif isinstance(v, (int, float)) and len(config.EDGE_BUCKETS) > 1 and v >= config.EDGE_BUCKETS[1]:
                ws.cell(r, edge_i).fill = MED_FILL
        if res_i:
            v = ws.cell(r, res_i).value
            if v == "W":
                ws.cell(r, res_i).fill = HIGH_FILL
            elif v == "L":
                ws.cell(r, res_i).fill = PatternFill("solid", fgColor="F8CBAD")


def _title(ws, text: str, sub: str = "") -> None:
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, size=14)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = Font(italic=True, color="595959")


def _write(xw, name: str, df: pd.DataFrame, title: str | None = None, sub: str = "", freeze=True):
    start = 3 if title else 0
    df.to_excel(xw, sheet_name=name, index=False, startrow=start)
    ws = xw.sheets[name]
    if title:
        _title(ws, title, sub)
    _format_table(ws, df, header_row=start + 1)
    if freeze:
        ws.freeze_panes = ws.cell(start + 2, 1)
    if len(df):
        ws.auto_filter.ref = f"A{start + 1}:{get_column_letter(len(df.columns))}{start + 1 + len(df)}"
    return ws


def assumptions_table() -> pd.DataFrame:
    rows = [
        ("Mode", "Legacy Excel" if config.LEGACY_EXCEL_MODE else "Standard", "config.LEGACY_EXCEL_MODE"),
        ("Line used by model", config.LINE_SOURCE, "consensus = median across books (falls back to ESPN)"),
        ("Offensive Rating Weight", config.OFFENSE_WEIGHT, "Applied to OR Diff"),
        ("Defensive Rating Weight", config.DEFENSE_WEIGHT, "Applied to DR Diff"),
        ("Home Court Value", config.HOME_COURT_POINTS, "ESPN home team; none on neutral courts"),
        ("HCA applies to defense", config.HCA_APPLIES_TO_DEFENSE, "Also subtracted from home team DRtg"),
        ("Tempo Baseline", config.TEMPO_BASELINE, "Tempo Mod = Avg AdjT / baseline"),
        ("High / Medium confidence", f">= {config.HIGH_THRESHOLD} / >= {config.MEDIUM_THRESHOLD}", "Enhanced Value"),
        ("Watch screen", f"rank sum < {config.RANK_SUM_LIMIT}; ratio >= {config.WATCH_HIGH_RATIO} or < {config.WATCH_LOW_RATIO}", "Original columns O:Q"),
        ("Proj T1 Margin", "(T1 NetRtg - T2 NetRtg) x Avg Tempo / 100 - HCA", "NetRtg = AdjO - AdjD"),
        ("Edge vs Line (T1)", "Proj T1 Margin + T1 Line", "Positive = T1 side, negative = T2 side"),
        ("Model Win%", f"Normal CDF of Proj Margin / {config.MARGIN_STDEV}", "config.MARGIN_STDEV"),
        ("Market Win%", "Avg of Kalshi and Polymarket (else no-vig book moneyline)", ""),
        ("Market pick", f"Model Win% beats Market Win% by >= {config.MARKET_EDGE_MIN:.0%}", "Graded straight up"),
        ("Units", "1 unit per pick; ATS at -110, Market picks at the market price", ""),
        ("Daily runs", ", ".join(config.DAILY_RUN_TIMES), "setup_daily_tasks.py"),
    ]
    return pd.DataFrame(rows, columns=["Assumption", "Value", "Notes"])


def books_table(results: pd.DataFrame, rows: list[dict]) -> pd.DataFrame:
    by_id = {r["game_id"]: r for r in rows}
    out = []
    for _, res in results.iterrows():
        row = by_id.get(res.get("game_id"), {})
        for book, b in (row.get("books") or {}).items():
            out.append({
                "Time": res.get("Time"), "T1 Team": res.get("T1 Team"), "T2 Team": res.get("T2 Team"),
                "Book": book,
                "T1 Line": b.get("away_point"), "T2 Line": b.get("home_point"),
                "T1 Price": b.get("away_price"), "T2 Price": b.get("home_price"),
                "T1 ML": b.get("ml_away"), "T2 ML": b.get("ml_home"),
            })
    return pd.DataFrame(out, columns=["Time", "T1 Team", "T2 Team", "Book", "T1 Line", "T2 Line",
                                      "T1 Price", "T2 Price", "T1 ML", "T2 ML"])


def write_dashboard(path: Path, day: date, results: pd.DataFrame, rows: list[dict], ratings: pd.DataFrame,
                    history: pd.DataFrame, record: pd.DataFrame, trend: pd.DataFrame, notes: list[str]) -> Path:
    stamp = f"Updated {datetime.now():%A %b %d, %Y at %I:%M %p}"
    hist = history.copy()
    if not hist.empty:
        hist = hist.sort_values(["date", "start", "pick_type"], ascending=[False, True, True], na_position="last")

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        _write(xw, "Today", today_view(results), f"NCAAM Model: {day:%A, %B %d, %Y}",
               f"{stamp}. Sorted by sportsbook edge. T1 = away, T2 = home.")

        ws = _write(xw, "Success Rate", record, "Success Rate",
                    f"{stamp}. Break-even against the spread at -110 is 52.4%.")
        start = len(record) + 7
        ws.cell(start - 1, 1, "Sportsbook Edge picks by day").font = Font(bold=True, size=12)
        trend.to_excel(xw, sheet_name="Success Rate", index=False, startrow=start - 1 + 1)
        hdr = start + 1
        for c in range(1, len(trend.columns) + 1):
            cell = ws.cell(hdr, c)
            cell.font, cell.fill = Font(bold=True, color="FFFFFF"), HEADER_FILL
            name = trend.columns[c - 1]
            if name in NUM_FORMATS:
                for r in range(hdr + 1, hdr + 1 + len(trend)):
                    ws.cell(r, c).number_format = NUM_FORMATS[name]
        if len(trend) >= 2:
            ch = LineChart()
            ch.title, ch.y_axis.title, ch.height, ch.width = "Cumulative Edge success rate", "Win %", 7.5, 16
            ch.y_axis.number_format = "0%"
            ci = list(trend.columns).index("Cumulative Rate") + 1
            ch.add_data(Reference(ws, min_col=ci, min_row=hdr, max_row=hdr + len(trend)), titles_from_data=True)
            ch.set_categories(Reference(ws, min_col=1, min_row=hdr + 1, max_row=hdr + len(trend)))
            ws.add_chart(ch, f"J{start}")

        _write(xw, "History", hist, "Pick History", f"{stamp}. Newest first. NR = postponed/no result.")
        _write(xw, "Full Slate", _public(results), "Full Slate", "Every original spreadsheet column plus odds columns.")
        _write(xw, "Odds by Book", books_table(results, rows), "Odds by Book", "From The Odds API.")
        _write(xw, "Ratings", ratings[["rank", "team", "conf", "record", "adj_o", "adj_o_rank", "adj_d",
                                       "adj_d_rank", "adj_t", "adj_t_rank", "net_rtg", "barthag"]],
               "Barttorvik T-Rank", stamp)
        _write(xw, "Assumptions", assumptions_table(), "Assumptions", "Edit these in config.py", freeze=False)
        _write(xw, "Run Log", pd.DataFrame({"Source status": list(notes)}), "Last run", stamp, freeze=False)
    return path
