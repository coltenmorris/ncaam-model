"""Match ESPN team names to Barttorvik team names.

Replaces the DeleteAt / StateToSt / DeleteUni macros. Matching runs in order:
  1. data/team_aliases.csv (your own fixes, always wins)
  2. built-in aliases below
  3. normalized name match (State -> St., drop "University", punctuation, etc.)
Anything still unmatched (usually non-Division I opponents) is skipped and
listed in the console, so you can add a line to data/team_aliases.csv.
"""

from __future__ import annotations

VERSION = "2026-11-07"

import csv
import re
from pathlib import Path

# ESPN name -> Barttorvik name
BUILTIN_ALIASES = {
    "UConn": "Connecticut",
    "Ole Miss": "Mississippi",
    "Miami": "Miami FL",
    "Miami (FL)": "Miami FL",
    "Miami (OH)": "Miami OH",
    "NC State": "N.C. State",
    "Pitt": "Pittsburgh",
    "UL Monroe": "Louisiana Monroe",
    "Louisiana-Monroe": "Louisiana Monroe",
    "Louisiana": "Louisiana Lafayette",
    "Texas A&M-Corpus Christi": "Texas A&M Corpus Chris",
    "Texas A&M-CC": "Texas A&M Corpus Chris",
    "SE Louisiana": "Southeastern Louisiana",
    "Hawai'i": "Hawaii",
    "San José State": "San Jose St.",
    "Long Island University": "LIU",
    "Long Island": "LIU",
    "Sam Houston": "Sam Houston St.",
    "Grambling": "Grambling St.",
    "App State": "Appalachian St.",
    "IU Indianapolis": "IU Indy",
    "IUPUI": "IU Indy",
    "St. Thomas-Minnesota": "St. Thomas",
    "Loyola Maryland": "Loyola MD",
    "UMass": "Massachusetts",
    "CSU Bakersfield": "Cal St. Bakersfield",
    "CSU Fullerton": "Cal St. Fullerton",
    "CSU Northridge": "Cal St. Northridge",
    "CSUN": "Cal St. Northridge",
    "Seattle U": "Seattle",
    "UT Martin": "Tennessee Martin",
    "Florida International": "FIU",
    "McNeese": "McNeese St.",
    "Nicholls": "Nicholls St.",
    "Charleston": "College of Charleston",
    "UAlbany": "Albany",
    "Omaha": "Nebraska Omaha",
    "Kansas City": "UMKC",
    "UMKC": "UMKC",
    "Southern Miss": "Southern Miss",
    "Detroit": "Detroit Mercy",
    "Saint Francis (PA)": "Saint Francis",
    "St. Francis (PA)": "Saint Francis",
    "Mississippi Valley State": "Mississippi Valley St.",
    "Texas A&M-Commerce": "East Texas A&M",
    "UNC Greensboro": "UNC Greensboro",
    "Queens University": "Queens",
    "Queens (NC)": "Queens",
    "SIU Edwardsville": "SIU Edwardsville",
    "UIC": "Illinois Chicago",
    "Purdue Fort Wayne": "Purdue Fort Wayne",
    "Boston University": "Boston University",
}


def key(name: str) -> str:
    """Normalize a team name so ESPN and Barttorvik spellings line up."""
    s = name.lower().strip()
    s = s.replace("’", "'").replace("é", "e").replace("ñ", "n")
    s = s.replace("@", " ")
    s = re.sub(r"\buniversity\b", " ", s)
    s = re.sub(r"\bstate\b", "st", s)
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"[.'()]", "", s)
    s = re.sub(r"[-/]", " ", s)
    s = s.replace("&", " and ")
    return re.sub(r"\s+", " ", s).strip()


class TeamMatcher:
    def __init__(self, torvik_names: list[str], alias_file: Path):
        self.names = list(torvik_names)
        self.exact = {n: n for n in self.names}
        self.by_key = {}
        for n in self.names:
            self.by_key.setdefault(key(n), n)
        self.aliases = dict(BUILTIN_ALIASES)
        self.aliases.update(self._load_user_aliases(alias_file))
        self.unmatched: set[str] = set()

    @staticmethod
    def _load_user_aliases(path: Path) -> dict:
        out = {}
        if path.exists():
            with path.open(newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    e, t = (row.get("espn_name") or "").strip(), (row.get("torvik_name") or "").strip()
                    if e and t and not e.startswith("#"):
                        out[e] = t
        return out

    def match(self, *candidates: str) -> str | None:
        cands = [c for c in candidates if c]
        for c in cands:
            t = self.aliases.get(c)
            if t and t in self.exact:
                return t
        for c in cands:
            if c in self.exact:
                return c
        for c in cands:
            t = self.by_key.get(key(c))
            if t:
                return t
        if cands:
            self.unmatched.add(cands[0])
        return None
