"""Map layers: every data point that can be toggled on the legislative map.

A layer turns the TEFA data into one number per legislative district. To add a layer,
write a function `(base, plan) -> (DataFrame[district, value], diagnostics)` and add a
Layer to LAYERS. The map page builds its dropdown from this list.

Most TEFA data is published by school district, so layers apportion ISD values to
House/Senate districts by the ISD's under-18 population in each piece (geo.allocate).
That is an estimate: it assumes participants are spread across an ISD like its children.
Charter schools have no geography in the crosswalk and are not allocated.

Exception: the Nov dashboard publishes funded/waitlisted students and award dollars by
House and Senate district directly. Those layers (exact=True) use the published numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from . import datasets as D
from . import geo


@dataclass
class Layer:
    id: str
    label: str
    fn: Callable
    kind: str = "count"         # count | money | rate
    per_child: bool = True      # offer "per 1,000 residents under 18"
    note: str = ""
    exact: bool = False         # published by legislative district (no ISD apportionment)


# ------------------------------------------------- exact: published by legislative district
_LEG_DATASET = {"H": "nov_house", "S": "nov_senate"}


def _published(col: str):
    """Layer fn reading one column of the Nov dashboard's House/Senate tables."""
    def fn(base: Path, plan):
        ds = _LEG_DATASET.get(plan.chamber)
        if ds is None:
            raise RuntimeError("The Nov dashboard publishes this for Texas House and Senate districts only.")
        df, err = D.load(ds, base)
        if err:
            raise RuntimeError(err)
        placed = df.dropna(subset=["district"])
        vals = placed[["district", col]].rename(columns={col: "value"}).astype({"district": int})
        diag = {"unmatched": [], "share_of_total_allocated": None}
        if col in ("funded", "waitlisted", "funded_award", "total_students"):
            total = df[col].sum()
            diag["share_of_total_allocated"] = placed[col].sum() / total if total else None
            diag["unplaced"] = total - placed[col].sum()
        return vals, diag
    return fn


def _isd_counts(df: pd.DataFrame, name_col: str, value_col: str, plan, how="sum"):
    return geo.allocate(df.rename(columns={name_col: "district", value_col: "value"}), plan, how=how)


def july_funded(base: Path, plan):
    df, err = D.load("july_district", base)
    if err:
        raise RuntimeError(err)
    return _isd_counts(df, "district", "funded", plan)


def oct1_funded(base: Path, plan):
    df, err = D.load("oct1_district", base)
    if err:
        raise RuntimeError(err)
    return _isd_counts(df, "district", "funded", plan)


def oct_prior_public(base: Path, plan):
    df, err = D.load("oct_district_prior_public", base)
    if err:
        raise RuntimeError(err)
    return _isd_counts(df, "district", "count_prior_public", plan)


def nov_top30(base: Path, plan):
    df, err = D.load("nov_isd", base)
    if err:
        raise RuntimeError(err)
    return _isd_counts(df, "district", "funded", plan)


def enrollment(base: Path, plan):
    df, err = D.load("district_roster", base)
    if err:
        raise RuntimeError(err)
    df = df[df.district_type.astype(str).str.upper() != "CHARTER"].copy()
    # The roster has no qualifier on duplicate names; add the county so they can be told apart.
    dup = df.district.duplicated(keep=False)
    df.loc[dup, "district"] = df.loc[dup, "district"] + " (" + df.loc[dup, "county"].astype(str) + ")"
    return _isd_counts(df, "district", "student_count", plan)


def pop_u18(base: Path, plan):
    p = geo.district_population(plan)
    return p[["district", "pop_u18"]].rename(columns={"pop_u18": "value"}), {"share_of_total_allocated": 1.0, "unmatched": []}


def sped_addon_41(base: Path, plan):
    dt, err = D.load("sped_district_table", base)
    if err:
        raise RuntimeError(err)
    d = dt[(dt.code == "41") & (~dt.speech)].copy()
    # Duplicate names appear as "(1 of 2)"/"(2 of 2)" with no county, so they can't be placed; drop them.
    d = d[~d.district.str.contains(r"\(\d of 2\)$")]
    return _isd_counts(d, "district", "addon", plan, how="mean")


_EXACT_NOTE = "Published by the Nov dashboard for each district (not apportioned); a small number of participants have no district."

LAYERS: list[Layer] = [
    Layer("nov_funded", "Funded participants (Nov dashboard, by district)", _published("funded"),
          note=_EXACT_NOTE, exact=True),
    Layer("nov_waitlisted", "Waitlisted students (Nov dashboard, by district)", _published("waitlisted"),
          note=_EXACT_NOTE, exact=True),
    Layer("nov_funded_award", "Award dollars to funded participants (Nov dashboard)", _published("funded_award"),
          kind="money", per_child=False, note=_EXACT_NOTE, exact=True),
    Layer("nov_avg_award", "Average award per funded participant (Nov dashboard)", _published("avg_award"),
          kind="money", per_child=False, note="Funded-participant award dollars ÷ funded participants, per district.",
          exact=True),
    Layer("july_funded", "Funded participants (July release)", july_funded,
          note="July district list covers districts with 30+ participants; apportioned by under-18 population."),
    Layer("oct1_funded", "Funded participants (Oct 1 request)", oct1_funded,
          note="Districts with 30+ participants only (4,486 statewide are in smaller ISDs); apportioned by under-18 population."),
    Layer("oct_prior_public", "Participants who attended public school prior year (Oct 1 request)", oct_prior_public,
          note="Parent-reported; apportioned by under-18 population."),
    Layer("nov_top30", "Funded participants, top 30 ISDs only (Nov dashboard)", nov_top30,
          note="Only 30 ISDs are published, so most districts show no value."),
    Layer("enrollment", "Public school enrollment (ISDs, excl. charters)", enrollment,
          note="From the gsheet_2025 roster; apportioned by under-18 population."),
    Layer("pop_u18", "Residents under 18 (2020 Census)", pop_u18, per_child=False,
          note="Exact, from the Legislative Council Red-160 report."),
    Layer("sped_addon_41", "SPED add-on, code 41 (resource room <21%)", sped_addon_41, kind="money", per_child=False,
          note="Average of ISD add-on amounts in the district, weighted by under-18 population."),
]
BY_ID = {l.id: l for l in LAYERS}


def build(layer_id: str, base: Path, plan) -> tuple[pd.DataFrame, dict]:
    """Layer values + under-18 population + per-1,000-children rate, one row per district."""
    layer = BY_ID[layer_id]
    vals, diag = layer.fn(base, plan)
    pop = geo.district_population(plan)
    out = pop.merge(vals, on="district", how="left")
    if layer.per_child:
        out["per_1000_u18"] = out["value"] / out["pop_u18"] * 1000
    return out, diag


def members(shape_dir: Path, data_dir: Path, chamber: str) -> pd.DataFrame | None:
    """Optional member names for hovers, from a '*legislators*.csv' (see config.MEMBERS_GLOB).

    Needs a district column, a chamber column (values like H/S, House/Senate) unless the file
    holds one chamber, and any column whose name contains 'member' or 'name'."""
    from . import config as C
    files = [p for d in (shape_dir, data_dir) if d.exists() for p in d.glob(C.MEMBERS_GLOB)]
    if not files:
        # Fall back to the member names on the Nov dashboard's House/Senate tables.
        if chamber not in _LEG_DATASET:
            return None
        df, err = D.load(_LEG_DATASET[chamber], data_dir)
        if err:
            return None
        return df.dropna(subset=["district", "member"])[["district", "member"]].astype({"district": int, "member": str})
    df = pd.read_csv(files[0])
    cols = {c.lower(): c for c in df.columns}
    dcol = next((cols[c] for c in cols if c in ("district", "dist", "district_number")), None)
    ncol = next((cols[c] for c in cols if "member" in c or "name" in c), None)
    if not dcol or not ncol:
        return None
    ccol = next((cols[c] for c in cols if c in ("chamber", "body", "house_senate")), None)
    if ccol:
        df = df[df[ccol].astype(str).str.upper().str[0] == chamber]
    out = df[[dcol, ncol]].rename(columns={dcol: "district", ncol: "member"})
    out["district"] = pd.to_numeric(out.district, errors="coerce")
    return out.dropna(subset=["district"]).astype({"district": int}).drop_duplicates("district")
