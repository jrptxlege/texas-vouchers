"""Cross-file consistency checks.

The public files are separate exports of the same program, so their totals should
reconcile. These checks make disagreements visible instead of letting a chart quietly
pick one number. Tolerance is a share of the reference value.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import datasets as D

TOL = 0.001  # 0.1%


def _row(name, a_lab, a, b_lab, b, note=""):
    diff = a - b if not (np.isnan(a) or np.isnan(b)) else np.nan
    pct = diff / b if b else np.nan
    if np.isnan(diff):
        status = "n/a"
    elif abs(pct) <= TOL:
        status = "ok"
    else:
        status = "differs"
    return {"check": name, "value": a, "compared_with": b, "difference": diff,
            "pct_difference": pct, "status": status, "a": a_lab, "b": b_lab, "note": note}


def run_checks(base: Path) -> pd.DataFrame:
    out = []
    kpis, _ = D.load("nov_kpis", base)
    k = dict(zip(kpis.kpi, kpis.value)) if kpis is not None else {}
    funded, eligible = k.get("Funded participants", np.nan), k.get("Eligible applicants", np.nan)

    # Breakdown sums vs headline counts (Nov)
    for ds in ["nov_tier", "nov_income", "nov_grade", "nov_age", "nov_prior_public"]:
        df, err = D.load(ds, base)
        if df is None:
            continue
        for metric, ref, ref_lab in [("funded", funded, "Funded participants tile"),
                                     ("eligible", eligible, "Eligible applicants tile")]:
            s = df.loc[df.metric == metric, "value"]
            if len(s):
                out.append(_row(f"{D.BY_ID[ds].title}: sum of {metric}", ds, s.sum(min_count=1), ref_lab, ref,
                                "Suppressed cells count as 0 in the sum." if s.isna().any() else ""))

    # Funnel: eligible = funded + waiting list + opted out (+ unexplained)
    if k:
        parts = funded + k.get("On waiting list", np.nan) + k.get("Opted out", np.nan)
        out.append(_row("Funnel: funded + waiting list + opted out", "tiles", parts, "Eligible applicants", eligible,
                        "Any remainder is not explained by the published tiles."))

    # Spending reconciliation
    fa, _ = D.load("nov_funding_allocation", base)
    if fa is not None:
        fa_d = dict(zip(fa.type, fa.amount))
        out.append(_row("Funding allocation total", "Funding Allocation.xlsx", fa.amount.sum(),
                        "Tuition Total Expenditure tile", k.get("Total program expenditure ($)", np.nan)))
        mkt = fa_d.get("Marketplace Spend", np.nan)
        for ds in ["nov_category", "nov_subcategory"]:
            df, _ = D.load(ds, base)
            if df is not None:
                out.append(_row(f"{D.BY_ID[ds].title}: total", ds, df.expenditure.sum(), "Marketplace Spend", mkt))
        al, _ = D.load("nov_all_vendors", base)
        if al is not None:
            out.append(_row("All vendors CSV: total expenditure", "All Vendors (2).csv", al.expenditure.sum(), "Marketplace Spend", mkt))
            out.append(_row("All vendors CSV: vendor count", "All Vendors (2).csv", float(len(al)), "Vendors tile", k.get("Vendors (with spending)", np.nan)))
            out.append(_row("All vendors CSV: transactions", "All Vendors (2).csv", al.transactions.sum(), "Vendor transactions tile", k.get("Vendor transactions", np.nan)))
        sch, _ = D.load("nov_all_schools", base)
        if sch is not None:
            out.append(_row("All schools CSV: total expenditure", "All Schools.csv", sch.expenditure.sum(), "School Funding", fa_d.get("School Funding", np.nan)))
            out.append(_row("All schools CSV: school count", "All Schools.csv", float(len(sch)), "Participating schools tile", k.get("Participating schools", np.nan)))
            out.append(_row("All schools CSV: transactions", "All Schools.csv", sch.transactions.sum(), "School transactions tile", k.get("School transactions", np.nan)))

    # Top-N exports vs full lists, entity by entity
    for top_id, all_id, key in [("nov_top_vendors", "nov_all_vendors", "vendor"), ("nov_top_schools", "nov_all_schools", "school")]:
        top, _ = D.load(top_id, base)
        full, _ = D.load(all_id, base)
        if top is None or full is None:
            continue
        m = top.merge(full, on=key, how="left", suffixes=("_top", "_all"))
        for r in m.itertuples():
            a, b = getattr(r, "expenditure_top"), getattr(r, "expenditure_all")
            row = _row(f"{key.title()} '{getattr(r, key)}': top-list vs full list", top_id, a, all_id, b,
                       "Not found in full list" if np.isnan(b) else "")
            # Full lists are rounded to $100; only flag gaps larger than that rounding.
            if row["status"] == "differs" and abs(row["difference"]) <= 100:
                row["status"] = "ok"
            out.append(row)

    # Oct 1 district list vs its own footer
    o1, _ = D.load("oct1_district", base)
    if o1 is not None:
        try:
            tot = D.oct1_totals(base)
        except Exception:  # noqa: BLE001 - footer layout changed
            tot = {}
        if tot:
            out.append(_row("Oct 1 district list: sum of listed districts", "oct1_district", o1.funded.sum(),
                            "Footer: in listed ISDs", tot["in_listed_isds"]))
            out.append(_row("Oct 1 footer: listed + ISDs under 30", "footer", tot["in_listed_isds"] + tot["in_isds_under_30"],
                            "Footer: total reported", tot["total_reported"]))

    # Legislative-district tables vs headline tiles and each other
    house, _ = D.load("nov_house", base)
    senate, _ = D.load("nov_senate", base)
    for lab, t in [("House", house), ("Senate", senate)]:
        if t is None:
            continue
        out.append(_row(f"{lab} district table: funded total", f"nov_{lab.lower()}", t.funded.sum(),
                        "Funded participants tile", funded, "Includes the row with no district."))
        out.append(_row(f"{lab} district table: waitlisted total", f"nov_{lab.lower()}", t.waitlisted.sum(),
                        "On waiting list tile", k.get("On waiting list", np.nan)))
    if house is not None and senate is not None:
        for c in ("funded", "waitlisted", "funded_award"):
            out.append(_row(f"House vs Senate tables: {c}", "nov_house", house[c].sum(), "nov_senate", senate[c].sum()))

    r, _ = D.load("nov_race", base)
    if r is not None:
        out.append(_row("Race/ethnicity shares sum to 100%", "nov_race", r.value.sum(), "1.0", 1.0))

    g, _ = D.load("nov_gender", base)
    if g is not None:
        out.append(_row("Gender shares sum to 100%", "nov_gender", g.value.sum(), "1.0", 1.0))

    return pd.DataFrame(out)
