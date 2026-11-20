"""District name matching across releases.

Each file spells districts differently ("NORTHSIDE ISD (BEXAR)", "Northside ISD - San
Antonio", "NORTHSIDE ISD - SAN ANTONIO"). `key()` reduces a name to a join key; the
explicit ALIASES map handles cases rules can't. Unmatched names are reported on the
Data & QA page so the map can be extended.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from . import config as C
from . import datasets as D

# Name variants -> roster spelling (after basic cleanup). Extend as unmatched names show up.
ALIASES = {
    "BEN BOLT PALITO": "BEN BOLT PALITO BLANCO ISD",  # truncated in the SPED funding table
}

# Twenty-two roster districts share a name with another district. Files tell them apart
# with a city after a dash ("NORTHSIDE ISD - VERNON", TEA style) or a county in
# parentheses ("Northside ISD (Bexar)", Legislative Council / dashboard style).
# Parenthesized qualifiers are used as the county directly; dash qualifiers (cities)
# are mapped to their county here. (They must stay separate: "Dawson" is a city in
# Navarro County and also a county.)
CITY_COUNTY = {
    "BIG SANDY": "UPSHUR", "DALLARDSVILLE": "POLK", "CENTERVILLE": "LEON", "GROVETON": "TRINITY",
    "MOUNT PLEASANT": "TITUS", "TYLER": "SMITH", "WELCH": "DAWSON", "DAWSON": "NAVARRO",
    "EDGEWOOD": "VAN ZANDT", "SAN ANTONIO": "BEXAR", "BEXAR": "BEXAR", "AMARILLO": "POTTER",
    "DALLAS": "DALLAS", "HENRIETTA": "CLAY", "WOODWAY": "MCLENNAN", "VERNON": "WILBARGER",
    "PHARR": "HIDALGO", "VALLEY VIEW": "COOKE", "ABILENE": "TAYLOR", "WYLIE": "COLLIN",
    "HUBBARD": "HILL", "DE KALB": "BOWIE",
}


def _clean(s: str) -> str:
    s = str(s).upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\bINDEPENDENT SCHOOL DISTRICT\b", "ISD", s)
    s = re.sub(r"\bCONSOLIDATED\b", "CONS", s)
    s = re.sub(r"\bCISD\b", "CONS ISD", s)       # TEA "CISD" == TLC "Cons ISD"
    s = re.sub(r"\bMT\b", "MOUNTAIN", s)
    s = re.sub(r"\bFT\b", "FORT", s)
    s = re.sub(r"\bU CITY\b", "UNIVERSAL CITY", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ALIASES.get(s, s)


def split_qualifier(name: str) -> tuple[str, str | None]:
    """-> (base name, county or None).
    'Northside ISD - Vernon' -> ('NORTHSIDE ISD', 'WILBARGER'); 'Northside ISD (Bexar)' -> (.., 'BEXAR')."""
    n = re.sub(r"\s*\([\d.]+%\)\s*$", "", str(name).strip())  # drop TLC "(37%)" suffix
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", n)
    if m:
        return _clean(m.group(1)), _clean(m.group(2))
    m = re.match(r"^(.*?)\s+-\s+(.+)$", n)
    if m:
        return _clean(m.group(1)), CITY_COUNTY.get(_clean(m.group(2)))
    return _clean(n), None


def key(name: str, duplicate_names: set[str] = frozenset()) -> str:
    """Join key. For names shared by two roster districts, append the county."""
    base, county = split_qualifier(name)
    if base in duplicate_names:
        return f"{base} | {county or '?'}"
    return base


def duplicate_names(roster: pd.DataFrame) -> set[str]:
    cleaned = roster.district.map(_clean)
    return set(cleaned[cleaned.duplicated(keep=False)])


def roster_key(name: str, county: str, duplicate_names: set[str]) -> str:
    b = _clean(name)
    return f"{b} | {str(county).upper()}" if b in duplicate_names else b


def combined(base: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """District-level table across releases joined to the roster's enrollment.

    Returns (table, unmatched) where unmatched lists names that found no roster row.
    """
    roster, _ = D.load("district_roster", base)
    frames = []
    jul, _ = D.load("july_district", base)
    if jul is not None:
        frames.append(jul.assign(metric="funded")[["district", "release", "metric", "funded"]].rename(columns={"funded": "value"}))
    oct1, _ = D.load("oct1_district", base)
    if oct1 is not None:
        frames.append(oct1.assign(metric="funded")[["district", "release", "metric", "funded"]].rename(columns={"funded": "value"}))
    nov, _ = D.load("nov_isd", base)
    if nov is not None:
        frames.append(nov.assign(metric="funded")[["district", "release", "metric", "funded"]].rename(columns={"funded": "value"}))
    octd, _ = D.load("oct_district_prior_public", base)
    if octd is not None:
        frames.append(octd.assign(release=C.REL_OCT, metric="prior_public")
                      .rename(columns={"count_prior_public": "value"})[["district", "release", "metric", "value"]])
    if not frames:
        return pd.DataFrame(), pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    if roster is None:
        long["key"] = long.district.map(key)
        return long, pd.DataFrame()
    dups = duplicate_names(roster)
    long["key"] = long.district.map(lambda n: key(n, dups))
    r = roster.assign(key=[roster_key(n, c, dups) for n, c in zip(roster.district, roster.county)])
    r = r.rename(columns={"district": "roster_name"})[["key", "roster_name", "region", "county", "district_type", "student_count"]]
    out = long.merge(r, on="key", how="left")
    out["per_1000_students"] = out.value / out.student_count * 1000
    unmatched = out[out.roster_name.isna()][["release", "district"]].drop_duplicates()
    return out, unmatched
