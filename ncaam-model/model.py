"""All of the spreadsheet formulas, as Python.

T1 = first team listed (ESPN away team), T2 = second team (ESPN home team),
same as columns A and B of the old "ESPN Game Schedule" sheet.
"""
from __future__ import annotations

import math

import pandas as pd

import config
import espn


def _abs_ratio(num, den):
    if num is None or den in (None, 0) or pd.isna(num) or pd.isna(den):
        return None
    return abs(num / den)


def _first_word_in_venue(team: str, venue: str) -> bool:
    """Excel: ISNUMBER(SEARCH(LEFT(A2,FIND(" ",A2&" ")-1),F2))"""
    first = (team or "").split(" ")[0]
    return bool(first) and first.lower() in (venue or "").lower()


def _confidence(ev):
    if ev is None:
        return ""
    if config.LEGACY_EXCEL_MODE:
        return "High" if ev >= config.HIGH_THRESHOLD else ""
    if ev >= config.HIGH_THRESHOLD:
        return "High"
    if ev >= config.MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def _t1(home_val):
    """Flip a home-team number to the T1 (away) side."""
    return None if home_val is None else -home_val


def build_rows(games: list[dict], matcher) -> list[dict]:
    """Turn ESPN games (plus attached odds) into model input rows."""
    rows = []
    for g in games:
        a, h = g["away"], g["home"]
        t1 = matcher.match(a["location"], a["short"], a["display"])
        t2 = matcher.match(h["location"], h["short"], h["display"])

        espn_home = espn.home_line(g)
        cons_home = g.get("cons_home_line")
        if config.LINE_SOURCE == "consensus" and cons_home is not None:
            primary, source = cons_home, f"Consensus ({g.get('n_books', 0)} books)"
        elif espn_home is not None:
            primary, source = espn_home, "ESPN (DraftKings)"
        else:
            primary, source = cons_home, (f"Consensus ({g.get('n_books', 0)} books)" if cons_home is not None else "")

        fav = None if not primary else ("T2" if primary < 0 else "T1")
        if primary is None:
            line_text = ""
        elif primary == 0:
            line_text = "EVEN"
        else:
            line_text = f"{(h if fav == 'T2' else a)['abbr']} -{abs(primary):g}"

        home_p = g.get("book_home_prob")
        mkts = [g.get(k) for k in ("kalshi_home_prob", "poly_home_prob") if g.get(k) is not None]
        rows.append({
            "game_id": g["game_id"],
            "start": g.get("start"),
            "date": g["start"].date() if g.get("start") else None,
            "time": g.get("time", ""),
            "tv": g.get("tv", ""),
            "espn_t1": a["location"] or a["short"],
            "espn_t2": h["location"] or h["short"],
            "t1": t1,
            "t2": t2,
            "venue": g.get("venue", ""),
            "neutral": g.get("neutral", False),
            "line_text": line_text,
            "line_source": source,
            "over_under": g.get("over_under"),
            "spread": None if primary is None else abs(primary),
            "fav": fav,
            "status": g.get("status", ""),
            "dk_t1": _t1(espn_home),
            "cons_t1": _t1(cons_home),
            "best_t1": g.get("best_away_line"),
            "best_t2": g.get("best_home_line"),
            "n_books": g.get("n_books"),
            "book_t1_prob": None if home_p is None else 1 - home_p,
            "kalshi_t1_prob": None if g.get("kalshi_home_prob") is None else 1 - g["kalshi_home_prob"],
            "poly_t1_prob": None if g.get("poly_home_prob") is None else 1 - g["poly_home_prob"],
            "mkt_t1_prob": (1 - sum(mkts) / len(mkts)) if mkts else (None if home_p is None else 1 - home_p),
            "books": g.get("books", {}),
        })
    return rows


def run_model(rows: list[dict], ratings: pd.DataFrame) -> pd.DataFrame:
    r = ratings.set_index("team")
    by_rank = ratings.drop_duplicates("rank").set_index("rank")["team"]
    hca_pts = config.HOME_COURT_POINTS
    legacy = config.LEGACY_EXCEL_MODE
    out = []

    for row in rows:
        t1, t2 = row["t1"], row["t2"]
        L = row["spread"]
        rec = {
            "Date": row["date"], "Time": row["time"], "TV": row["tv"],
            "T1 Team": t1 or f"{row['espn_t1']} (no match)",
            "T2 Team": t2 or f"{row['espn_t2']} (no match)",
            "Venue": row["venue"], "Neutral": "Yes" if row["neutral"] else "",
            "Line": row["line_text"], "O/U": row["over_under"],
        }
        ok = t1 in r.index and t2 in r.index
        if not ok:
            rec["Note"] = "Team not in ratings (likely non-D1); skipped"
            out.append(rec | {"game_id": row["game_id"]})
            continue
        a, b = r.loc[t1], r.loc[t2]

        # --- Original columns I:Q -------------------------------------------
        I, J = int(a["rank"]), int(b["rank"])
        K = I - J
        M = _abs_ratio(K, L)
        watch, line_pick, pick_side = "", "", None
        if M is not None and I + J < config.RANK_SUM_LIMIT:
            if M >= config.WATCH_HIGH_RATIO:
                watch, pick_side = "YES", ("T1" if I < J else "T2")
            elif M < config.WATCH_LOW_RATIO:
                watch, pick_side = "YES", ("T1" if I > J else "T2")
        if pick_side:
            # Excel looked the team up by MIN/MAX rank; same result.
            line_pick = by_rank.get(I if pick_side == "T1" else J, t1 if pick_side == "T1" else t2)

        rec.update({"Spread": L, "T1 Rk": I, "T2 Rk": J, "Diff": K, "Value": M,
                    "Games to Watch": watch, "Watch Pick": f"{line_pick} covers spread" if line_pick else ""})

        # --- Offense / defense columns U:AL ----------------------------------
        U, V, W, X = a["adj_o"], int(a["adj_o_rank"]), b["adj_o"], int(b["adj_o_rank"])
        AB, AC, AD, AE = a["adj_d"], int(a["adj_d_rank"]), b["adj_d"], int(b["adj_d_rank"])
        yes = watch == "YES"
        Y = V - X if yes else None
        AF = AC - AE
        AI = V - AE if yes else None
        AK = X - AC if yes else None
        rec.update({
            "T1 Off": U, "T1 OR": V, "T2 Off": W, "T2 OR": X,
            "OR1 - OR2": Y, "OR Value": _abs_ratio(Y, L) if yes else None,
            "T1 Def": AB, "T1 DR": AC, "T2 Def": AD, "T2 DR": AE,
            "DR1 - DR2": AF, "DR Value": _abs_ratio(AF, L) if yes else None,
            "OR1 - DR2": AI, "OR1-DR2 Value": _abs_ratio(AI, L) if yes else None,
            "OR2 - DR1": AK, "OR2-DR1 Value": _abs_ratio(AK, L) if yes else None,
        })

        # --- Enhanced columns AV:BE ------------------------------------------
        AV, AW = a["adj_t"], b["adj_t"]
        AX = (AV + AW) / 2
        AY = AX / config.TEMPO_BASELINE
        if legacy:
            h1 = hca_pts if _first_word_in_venue(t1, row["venue"]) else 0
            h2 = hca_pts if _first_word_in_venue(t2, row["venue"]) else 0
            AZ = (V + h1) - (X + h2)     # uses offense RANK, as the workbook did
            BA = AE - AC                 # uses defense RANK, as the workbook did
        else:
            h1 = 0.0                     # T1 is ESPN's away team
            h2 = 0.0 if row["neutral"] else hca_pts
            d_adj = 1.0 if config.HCA_APPLIES_TO_DEFENSE else 0.0
            AZ = (U + h1) - (W + h2)
            BA = (AD - h2 * d_adj) - (AB - h1 * d_adj)
        BB = config.OFFENSE_WEIGHT * AZ + config.DEFENSE_WEIGHT * BA
        BC = _abs_ratio(BB, L)
        BC = BC * AY if BC is not None else None
        BD = _confidence(BC)
        BE_side = "T1" if BB > 0 else "T2"
        BE = f"{t1 if BE_side == 'T1' else t2} covers"

        rec.update({
            "T1 AdjT": AV, "T2 AdjT": AW, "Avg Tempo": AX, "Tempo Mod": AY,
            "OR Diff (HCA)": AZ, "DR Diff": BA, "Wtd Eff": BB,
            "Enhanced Value": BC, "Confidence": BD, "Model Pick": BE,
        })

        # --- Sportsbook edge and prediction-market columns -------------------
        t1_line = None
        if L is not None:
            t1_line = 0.0 if L == 0 else (-L if row["fav"] == "T1" else L if row["fav"] == "T2" else None)
        proj = (a["net_rtg"] - b["net_rtg"]) * AX / 100 - (0 if row["neutral"] else hca_pts)
        edge = (proj + t1_line) if t1_line is not None else None
        edge_side = None if edge is None or edge == 0 else ("T1" if edge > 0 else "T2")
        model_p = 0.5 * (1 + math.erf(proj / (config.MARGIN_STDEV * math.sqrt(2))))
        mkt_p = row.get("mkt_t1_prob")
        p_edge = (model_p - mkt_p) if mkt_p is not None else None
        mkt_side = None
        if p_edge is not None and abs(p_edge) >= config.MARKET_EDGE_MIN:
            mkt_side = "T1" if p_edge > 0 else "T2"
        edge_team = (t1 if edge_side == "T1" else t2) if edge_side else ""
        rec.update({
            "Line Source": row.get("line_source", ""),
            "T1 Line": t1_line,
            "DK Line (T1)": row.get("dk_t1"),
            "Consensus (T1)": row.get("cons_t1"),
            "Best T1": row.get("best_t1"),
            "Best T2": row.get("best_t2"),
            "Books": row.get("n_books"),
            "Proj T1 Margin": proj,
            "Edge vs Line (T1)": edge,
            "Edge Pick": (f"{edge_team} {'PK' if t1_line == 0 else format(t1_line if edge_side == 'T1' else -t1_line, '+g')}"
                          if edge_side else ""),
            "Edge Size": abs(edge) if edge is not None else None,
            "Model T1 Win%": model_p,
            "Book T1 Win%": row.get("book_t1_prob"),
            "Kalshi T1 Win%": row.get("kalshi_t1_prob"),
            "Poly T1 Win%": row.get("poly_t1_prob"),
            "Market T1 Win%": mkt_p,
            "Win% Edge (T1)": p_edge,
        })

        rec.update({
            "game_id": row["game_id"], "_start": row.get("start"),
            "_watch_side": pick_side, "_model_side": BE_side, "_t1_line": t1_line,
            "_edge_side": edge_side, "_edge": abs(edge) if edge is not None else None,
            "_mkt_side": mkt_side, "_p_edge": abs(p_edge) if p_edge is not None else None,
            "_mkt_prob": (mkt_p if mkt_side == "T1" else 1 - mkt_p) if mkt_side else None,
        })
        out.append(rec)

    return pd.DataFrame(out)
