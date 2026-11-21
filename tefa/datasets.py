"""Dataset registry: one loader per published table, all returning tidy DataFrames.

Conventions
-----------
* Breakdown tables (tier, income, grade, age, ...) share one long schema:
      release | dimension | category | metric | value
  where metric is one of "eligible", "funded", "share_funded", "count".
  That lets one chart function compare releases or metrics for any breakdown.
* Every loader takes the data folder and returns a DataFrame. Missing files raise
  FileNotFoundError; `load()` turns failures into a status the UI can display.
* Values are taken exactly as published. Suppressed cells ("*" or blank) stay NaN;
  nothing is imputed.

To add a new release: write a loader that emits the same schema, register it in
DATASETS, and the existing pages pick it up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from . import config as C
from .readers import add_bounds, crosstab, find_file, numeric_cols, read_csv_any, read_raw, scalar, to_number, wide_rows

TIDY_COLS = ["release", "dimension", "category", "metric", "value"]


def _need(base: Path, rel: str) -> Path:
    p = find_file(base, rel)
    if p is None:
        raise FileNotFoundError(rel)
    return p


def _metric_key(label: str) -> str:
    l = label.lower()
    if "eligible" in l:
        return "eligible"
    if "funded" in l or "particip" in l:
        return "funded"
    return "count"


def _tidy(rows, release, dimension) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["category", "metric", "value"])
    df.insert(0, "dimension", dimension)
    df.insert(0, "release", release)
    return df[TIDY_COLS]


# =================================================================== Nov dashboard
NOV_KPI_FILES = {
    "Applications received": f"{C.NOV_DIR}/Applications Received.xlsx",
    "Eligible applicants": f"{C.NOV_DIR}/Eligible Applicants.xlsx",
    "Funded participants": f"{C.NOV_DIR}/Funded Participants.xlsx",
    "On waiting list": f"{C.NOV_DIR}/Applicants on Waiting List.xlsx",
    "Opted out": f"{C.NOV_DIR}/Applicants Opted Out.csv",
    "Low-income funded participants": f"{C.NOV_DIR}/Low Income Funded Participants.xlsx",
    "Share of participants with a disability": f"{C.NOV_DIR}/Particiapts With Disability.xlsx",
    "Total program expenditure ($)": f"{C.NOV_EXP}/Tuition Total Expenditure.xlsx",
    "Participating schools": f"{C.NOV_EXP}/Participating Schools.xlsx",
    "School transactions": f"{C.NOV_EXP}/School Transactions.xlsx",
    "Vendors (with spending)": f"{C.NOV_EXP}/Vendors.xlsx",
    "Vendor transactions": f"{C.NOV_EXP}/Vendor Transactions.xlsx",
}


def nov_kpis(base: Path) -> pd.DataFrame:
    """Single-number tiles from the Nov dashboard."""
    rows = []
    for name, rel in NOV_KPI_FILES.items():
        p = find_file(base, rel)
        rows.append({"kpi": name, "value": scalar(p) if p else np.nan,
                     "source": rel if p else f"MISSING: {rel}"})
    return pd.DataFrame(rows)


def nov_tier(base: Path) -> pd.DataFrame:
    ct = crosstab(_need(base, f"{C.NOV_DIR}/Participation by Priority Tier.xlsx"))
    rows = [(r.row_label, _metric_key(r.col_label), r.value) for r in ct.itertuples()]
    return _tidy(rows, C.REL_NOV, "Priority tier")


def nov_income(base: Path) -> pd.DataFrame:
    ct = crosstab(_need(base, f"{C.NOV_DIR}/Applicants by Income.xlsx"))
    rows = [(r.col_label, _metric_key(r.row_label), r.value) for r in ct.itertuples()]
    return _tidy(rows, C.REL_NOV, "Income")


def nov_disability_tier(base: Path) -> pd.DataFrame:
    ct = crosstab(_need(base, f"{C.NOV_DIR}/Applicants With Disabilities.xlsx"))
    rows = [(r.col_label, _metric_key(r.row_label), r.value) for r in ct.itertuples()]
    return _tidy(rows, C.REL_NOV, "Applicants with disabilities, by tier")


def nov_grade(base: Path) -> pd.DataFrame:
    ct = crosstab(_need(base, f"{C.NOV_DIR}/Participants by Grade level.xlsx"))
    rows = [(r.col_label, _metric_key(r.row_label), r.value) for r in ct.itertuples()]
    return _tidy(rows, C.REL_NOV, "Grade")


def nov_age(base: Path) -> pd.DataFrame:
    ct = crosstab(_need(base, f"{C.NOV_DIR}/Funded Participants by Age.xlsx"))
    rows = [(r.row_label, "funded", r.value) for r in ct.itertuples()]
    return _tidy(rows, C.REL_NOV, "Age")


def nov_gender(base: Path) -> pd.DataFrame:
    ct = crosstab(_need(base, f"{C.NOV_DIR}/Funded Participants by Gender.xlsx"))
    rows = [(r.row_label, "share_funded", r.value) for r in ct.itertuples()]
    return _tidy(rows, C.REL_NOV, "Gender")


def nov_race(base: Path) -> pd.DataFrame:
    """Two columns, no header row: category | percent of funded participants.
    The export writes percents on a 0-100 scale; they are converted to shares (0-1)
    to match the gender table."""
    raw = read_raw(_need(base, f"{C.NOV_DIR}/Funded Participants  by Race_Ethnicity.xlsx"))
    raw = raw.iloc[:, :2].dropna(how="all")
    cats = raw.iloc[:, 0].astype(str).str.strip()
    vals = raw.iloc[:, 1].map(to_number)
    if vals.max() > 1.5:  # percent scale
        vals = vals / 100
    rows = [(c, "share_funded", v) for c, v in zip(cats, vals) if c and c.lower() != "nan"]
    return _tidy(rows, C.REL_NOV, "Race/ethnicity")


def nov_legislative(base: Path, chamber: str) -> pd.DataFrame:
    """Funded / waitlisted students and award dollars by House ('H') or Senate ('S')
    district, as published on the Nov dashboard. These are exact counts by district,
    not estimates. One row has no district (participants the dashboard could not place);
    it is kept with district = NaN so totals match the source."""
    rel = {"H": "Funded Participants by House Districts.xlsx", "S": "Funded Participants by Senate Districts.xlsx"}[chamber]
    df = pd.read_excel(_need(base, f"{C.NOV_DIR}/{rel}"))
    cols = list(df.columns)
    out = pd.DataFrame({
        "district": pd.to_numeric(df[cols[1]], errors="coerce").astype("Int64"),
        "member": df[cols[0]].astype("string").str.strip(),
    })
    names = {"Funded Participants": "funded", "Funded Participants - Award": "funded_award",
             "Waitlisted Students": "waitlisted", "Waitlisted Students - Award": "waitlisted_award",
             "Total Students": "total_students", "Total Award": "total_award"}
    for src, dst in names.items():
        out[dst] = df[src].map(to_number)
    out["avg_award"] = out.funded_award / out.funded
    out["release"] = C.REL_NOV
    return out.sort_values("district", na_position="first").reset_index(drop=True)


def nov_house(base: Path) -> pd.DataFrame:
    return nov_legislative(base, "H")


def nov_senate(base: Path) -> pd.DataFrame:
    return nov_legislative(base, "S")


def nov_prior_public(base: Path) -> pd.DataFrame:
    df = pd.read_excel(_need(base, f"{C.NOV_DIR}/Prior Year Public School Participation.xlsx"), sheet_name=0)
    rows = [(c, "funded", to_number(v)) for c, v in zip(df["Indicator"], df["Count"]) if not pd.isna(c)]
    return _tidy(rows, C.REL_NOV, "Prior-year schooling")


def nov_isd(base: Path) -> pd.DataFrame:
    """Top ISDs by funded participants (the dashboard heat map shows the top 30)."""
    w = wide_rows(_need(base, f"{C.NOV_DIR}/ISD Participation Heat Map.xlsx"))
    names, funded = w["Metric"], w["Funded"]
    df = pd.DataFrame({"district": names, "funded": [to_number(v) for v in funded]})
    df = df.dropna(subset=["district"])
    df["release"] = C.REL_NOV
    return df


# ------------------------------------------------------------- Nov: expenditures
def nov_funding_allocation(base: Path) -> pd.DataFrame:
    df = pd.read_excel(_need(base, f"{C.NOV_EXP}/Funding Allocation.xlsx"))
    df = df.rename(columns={"Expenditure Type": "type", "Amount": "amount"})
    return df[["type", "amount"]]


def _top20(base: Path, rel: str, label: str) -> pd.DataFrame:
    ct = crosstab(_need(base, rel))
    ct = ct[ct.col_label == "Selected Metric"]  # exact amount; "Expenditure Label" is rounded
    return ct.rename(columns={"row_label": label, "value": "expenditure"})[[label, "expenditure"]]


def nov_top_schools(base):
    return _top20(base, f"{C.NOV_EXP}/Top 20 Schools by Expenditure or Transactions.xlsx", "school")


def nov_top_vendors(base):
    return _top20(base, f"{C.NOV_EXP}/Top 20 Vendors by Expenditure or Transactions.xlsx", "vendor")


def nov_top_subcats(base):
    return _top20(base, f"{C.NOV_EXP}/Top 20 Sub Categories by Expenditure or Transactions.xlsx", "subcategory")


def nov_vendor_distribution(base: Path) -> pd.DataFrame:
    ct = crosstab(_need(base, f"{C.NOV_EXP}/Vendor Distribution by Expenditure.xlsx"))
    return ct.rename(columns={"row_label": "range", "value": "vendors"})[["range", "vendors"]]


def nov_category(base: Path) -> pd.DataFrame:
    df = pd.read_excel(_need(base, f"{C.NOV_VEND}/Category.xlsx"))
    df.columns = [c.strip().lower() for c in df.columns]
    return numeric_cols(df, ["transactions", "expenditure"])


def nov_subcategory(base: Path) -> pd.DataFrame:
    df = pd.read_excel(_need(base, f"{C.NOV_VEND}/Sub Category.xlsx"), dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]
    return numeric_cols(df, ["transactions", "expenditure"])


def _with_bands(df: pd.DataFrame) -> pd.DataFrame:
    """Full school/vendor lists publish amounts under $10,000 as $2,500 bands and
    transaction counts under 10 as '<10'. `expenditure`/`transactions` stay exact (NaN for a
    band); *_low/*_high give the band ends (equal for exact values); *_published keeps the text."""
    for c in ("transactions", "expenditure"):
        df[f"{c}_published"] = df[c].fillna("").str.strip()
        add_bounds(df, c)
        df[c] = df[c].map(to_number)
    return df


def nov_all_schools(base: Path) -> pd.DataFrame:
    df = read_csv_any(_need(base, f"{C.NOV_VEND}/All Schools.csv"))
    df.columns = ["school", "transactions", "expenditure"]
    return _with_bands(df)


def nov_all_vendors(base: Path) -> pd.DataFrame:
    df = read_csv_any(_need(base, f"{C.NOV_VEND}/All Vendors (2).csv"))
    df.columns = ["vendor", "transactions", "expenditure"]
    return _with_bands(df)


# ===================================================================== July release
def july_age(base: Path) -> pd.DataFrame:
    raw = read_raw(_need(base, "Voucher Data - July Release.xlsx"), "Age & Gender")
    body = raw.iloc[2:, 0:3].dropna(how="all")
    rows = []
    for a, e, f in body.itertuples(index=False):
        rows += [(str(a), "eligible", to_number(e)), (str(a), "funded", to_number(f))]
    return _tidy(rows, C.REL_JULY, "Age")


def july_gender(base: Path) -> pd.DataFrame:
    raw = read_raw(_need(base, "Voucher Data - July Release.xlsx"), "Age & Gender")
    body = raw.iloc[2:, 7:10].dropna(how="all")
    rows = []
    for s, e, f in body.itertuples(index=False):
        rows += [(str(s), "eligible", to_number(e)), (str(s), "funded", to_number(f))]
    return _tidy(rows, C.REL_JULY, "Gender")


def july_race(base: Path) -> pd.DataFrame:
    raw = read_raw(_need(base, "Voucher Data - July Release.xlsx"), "Ethnicity")
    body = raw.iloc[2:, 0:3].dropna(how="all")
    rows = []
    for r, e, f in body.itertuples(index=False):
        rows += [(str(r), "eligible", to_number(e)), (str(r), "funded", to_number(f))]
    return _tidy(rows, C.REL_JULY, "Race/ethnicity")


def july_district(base: Path) -> pd.DataFrame:
    raw = read_raw(_need(base, "Voucher Data - July Release.xlsx"), "District")
    df = raw.iloc[2:, 0:2].dropna(how="all")
    df.columns = ["funded", "district"]
    df["funded"] = df["funded"].map(to_number)
    df["release"] = C.REL_JULY
    return df


def july_campus(base: Path) -> pd.DataFrame:
    raw = read_raw(_need(base, "Voucher Data - July Release.xlsx"), "Campus")
    # Column C holds a single stray label ("Houston"), not a per-row district, so it is ignored.
    df = raw.iloc[1:, 0:2].copy()
    df.columns = ["funded", "campus"]
    df["funded"] = df["funded"].map(to_number)
    return df.dropna(subset=["campus"])


# ================================================================ Oct data request
_OCT = "TEFA_Data-Copy.xlsx"


GRADE_ORDER = ["Pre-K", "K", "1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th", "11th", "12th"]
_GRADE_MAP = {"PK": "Pre-K", "K": "K", **{str(i): GRADE_ORDER[i + 1] for i in range(1, 13)}}


def oct_grade(base: Path) -> pd.DataFrame:
    df = pd.read_excel(_need(base, _OCT), "by grade")
    # Relabel "PK","1".."12" to the Nov dashboard's "Pre-K","1st".. so releases line up.
    rows = [(_GRADE_MAP.get(str(g).strip(), str(g)), "funded", to_number(c)) for g, c in zip(df.grade_level, df.Count)]
    return _tidy(rows, C.REL_OCT, "Grade")


def oct_priority(base: Path) -> pd.DataFrame:
    df = pd.read_excel(_need(base, _OCT), "by priority").dropna(subset=["Count"])
    rows = [(f"Tier {int(p)}" if not pd.isna(p) else "?", "funded", to_number(c))
            for p, c in zip(df.priority, df.Count) if str(p)[0].isdigit()]
    return _tidy(rows, C.REL_OCT, "Priority tier")


def oct_school_selected(base: Path) -> pd.DataFrame:
    df = pd.read_excel(_need(base, _OCT), "by school selected").dropna(subset=["school_selected"])
    rows = [(s, "funded", to_number(c)) for s, c in zip(df.school_selected, df.Count)]
    return _tidy(rows, C.REL_OCT, "School selected")


def oct_sped_flag(base: Path) -> pd.DataFrame:
    df = pd.read_excel(_need(base, _OCT), "by sped flag")
    rows = [(s, "funded", to_number(c)) for s, c in zip(df.sped_flag, df.Count)]
    return _tidy(rows, C.REL_OCT, "SPED flag")


def oct_district_prior_public(base: Path) -> pd.DataFrame:
    """Sheet 'by district and previous public'. Only the count and enrollment columns
    are kept: the sheet's Loss column uses the superseded flat $8,198.69 rate."""
    df = pd.read_excel(_need(base, _OCT), "by district and previous public").iloc[:, :6]
    df.columns = ["district", "count_prior_public", "_loss_superseded", "type", "student_count", "_takeup"]
    df = df.dropna(subset=["district"])
    df = df[~df.district.astype(str).str.startswith("Note")]  # footnote row: "Data is parent-reported."
    df["count_prior_public"] = df["count_prior_public"].map(to_number)
    df["student_count"] = df["student_count"].map(to_number)
    return df[["district", "type", "count_prior_public", "student_count"]]


_OCT1 = "Oct1_TEFA-Funded-Participants - Data  Request.xlsx"


def _oct1_raw(base: Path) -> pd.DataFrame:
    return read_raw(_need(base, _OCT1), "District")


def oct1_district(base: Path) -> pd.DataFrame:
    """Funded participants by school district, Oct 1 data request (districts with 30+ only).

    The sheet has headers for race, sex, prior school, tier and disability, but those
    columns are empty in the published file; only District and Participating Students
    are filled. The 'Campus' sheet repeats the same numbers. A few stray scratch cells
    to the right of one row are ignored."""
    raw = _oct1_raw(base)
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "District"][0]
    body = raw.iloc[hdr + 1:, [0, 2]]
    body.columns = ["district", "funded"]
    body = body[body.district.notna() & ~body.district.astype(str).str.contains("Total", case=False)]
    body = body[body.district.astype(str).str.contains(r"[A-Za-z]")]  # drop the bare total rows
    body["funded"] = body["funded"].map(to_number)
    body["district"] = body["district"].astype(str).str.strip()
    body["release"] = C.REL_OCT
    return body.dropna(subset=["funded"]).reset_index(drop=True)


def oct1_totals(base: Path) -> dict:
    """Footer of the Oct 1 District sheet: total reported, in listed ISDs, in ISDs under 30."""
    raw = _oct1_raw(base)
    i = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Total Reported"][0]
    v = raw.loc[i + 1]
    return {"total_reported": to_number(v.iloc[0]), "in_listed_isds": to_number(v.iloc[2]),
            "in_isds_under_30": to_number(v.iloc[3])}


def district_roster(base: Path) -> pd.DataFrame:
    """Region/county/type/enrollment roster from the 'gsheet_2025' sheet, used to join
    district names to enrollment. Loss columns there are superseded and dropped.
    Student Count = -999 marks masked values; converted to NaN."""
    df = pd.read_excel(_need(base, _OCT), "gsheet_2025").iloc[:, :6]
    df.columns = ["region", "county", "district", "district_number", "district_type", "student_count"]
    df.loc[df.student_count < 0, "student_count"] = np.nan
    return df


# ================================================================ ESC regions
def esc_file(base: Path) -> Path:
    """Newest ESC####.csv: the bundled copy (data/geo) if present, else the shapefile folder
    (EO Data/Texas Shapefiles). It is a TEA/ESC GIS layer's attribute table: region,
    headquarters city and website for the 20 education service centers."""
    import re as _re
    for d in (base / "geo", C.shape_dir()):
        hits = sorted((p for p in d.glob("ESC*.csv") if _re.fullmatch(r"ESC\d{4}\.csv", p.name, _re.I)),
                      key=lambda p: p.stem) if d.exists() else []
        if hits:
            return hits[-1]
    raise FileNotFoundError("ESC####.csv (in data/geo or the shapefile folder)")


def esc_regions(base: Path) -> pd.DataFrame:
    """region (int 1-20), hq_city, website, label ("Region 4 · Houston"). GIS area/length
    columns are dropped (their units aren't documented in the export)."""
    p = esc_file(base)
    df = pd.read_csv(p)
    df.columns = [c.strip().upper() for c in df.columns]
    out = pd.DataFrame({"region": pd.to_numeric(df["ESC_REGION"], errors="coerce").astype("Int64"),
                        "hq_city": df["CITY"].astype(str).str.strip(),
                        "website": df["WEBSITE"].astype(str).str.strip()})
    out = out.dropna(subset=["region"]).sort_values("region").reset_index(drop=True)
    out["website"] = out.website.map(lambda w: w if w.startswith("http") else f"https://{w}")
    out["label"] = "Region " + out.region.astype(str) + " · " + out.hq_city
    out.attrs["source"] = p.name
    return out


def region_label(region, esc: pd.DataFrame | None) -> str:
    """'Region 4 · Houston' (falls back to 'Region 4' if the ESC table is unavailable)."""
    if region is None or pd.isna(region):
        return "No region"
    r = int(region)
    if esc is not None:
        hit = esc.loc[esc.region == r, "label"]
        if len(hit):
            return hit.iloc[0]
    return f"Region {r}"


# ============================================================ vendors & special ed
def vendor_directory(base: Path) -> pd.DataFrame:
    df = pd.read_excel(_need(base, "TEFA-Participating-Vendors.xlsx"))
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["zip"] = df["zip"].astype(str).str[:5]
    return df


_VENDOR_SUFFIX = r"(LLC|L L C|INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLLC|PLC|LP|LLP|PC|PA|THE|DBA)"


def vendor_key(name) -> str:
    """Join key for vendor names: the directory says 'ROOM FOR CHANGE, PLLC', the
    spending list 'Room For Change Pllc'. Uppercase, drop punctuation and company suffixes."""
    import re
    s = str(name).upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(_VENDOR_SUFFIX, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def vendor_directory_spend(base: Path) -> pd.DataFrame:
    """Vendor directory with each vendor's marketplace transactions and expenditure from
    the Nov dashboard's all-vendors list. Vendors under $10,000 are published as a band, so
    expenditure is exact or NaN; use expenditure_low/high for totals. Vendors not in the
    list have no spending recorded (0, has_spending False).

    Some vendors are registered more than once (e.g. under two business types); every row
    of such a vendor carries the vendor's full total, so de-duplicate on `vendor_key`
    before summing. attrs["unmatched"]: spending-list vendors not in the directory."""
    v = vendor_directory(base)
    a = nov_all_vendors(base)
    v["vendor_key"] = v.vendor_name.map(vendor_key)
    a["vendor_key"] = a.vendor.map(vendor_key)
    cols = ["transactions", "transactions_low", "transactions_high", "transactions_published",
            "expenditure", "expenditure_low", "expenditure_high", "expenditure_published"]
    spend = a.drop_duplicates("vendor_key")[["vendor_key"] + cols]
    out = v.merge(spend, on="vendor_key", how="left")
    out["has_spending"] = out.expenditure_high.notna()
    none = ~out.has_spending  # not in the spending list: no marketplace spending recorded
    out.loc[none, ["transactions", "transactions_low", "transactions_high",
                   "expenditure", "expenditure_low", "expenditure_high"]] = 0.0
    out.loc[none, ["transactions_published", "expenditure_published"]] = ""
    # Plain records (not a DataFrame): attrs travel with every slice and must stay JSON-able.
    um = a[~a.vendor_key.isin(set(v.vendor_key))].sort_values("expenditure_high", ascending=False)
    out.attrs["unmatched"] = [{"vendor": r.vendor, "expenditure": r.expenditure_published}
                              for r in um.itertuples()]
    out.attrs["spend_low"] = float(a.expenditure_low.sum())
    out.attrs["spend_high"] = float(a.expenditure_high.sum())
    return out


def sped_by_code(base: Path) -> pd.DataFrame:
    raw = read_raw(_need(base, "TEFA_SpecialEd_Funding_by_Code_2026-27.xlsx"), "By Code")
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Code"][0]
    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr]]
    df = df[df["Code"].astype(str).str.fullmatch(r"\d{2}")].reset_index(drop=True)
    # "<30" award counts are suppressed: keep the raw text, add a numeric column.
    award_col = next((c for c in df.columns if c.lower().startswith("priority-one awards")), None)
    if award_col:
        df["awards_numeric"] = df[award_col].map(to_number)
        df[award_col] = df[award_col].astype(str)
    for c in ("Funding tier (1 = lowest)", "Lowest district", "Median district", "Highest district"):
        if c in df.columns:
            df[c] = df[c].map(to_number)
    return df


def sped_notes(base: Path) -> list[str]:
    raw = read_raw(_need(base, "TEFA_SpecialEd_Funding_by_Code_2026-27.xlsx"), "By Code")
    col = raw.iloc[:, 0].dropna().astype(str)
    return [s.strip() for s in col if s.strip().startswith(("•", "Source:"))]


def sped_params(base: Path) -> dict:
    raw = read_raw(_need(base, "TEFA_SpecialEd_Funding_by_Code_2026-27.xlsx"), "By Code")
    d = {}
    for k in ("Base amount", "Account cap"):
        hit = raw[raw.iloc[:, 0].astype(str).str.strip() == k]
        if len(hit):
            d[k] = to_number(hit.iloc[0, 1])
    return d


def sped_district_table(base: Path) -> pd.DataFrame:
    """Wide district x code table -> long: district, code, speech (bool), addon."""
    df = pd.read_excel(_need(base, "TEFA_SpecialEd_Funding_by_Code_2026-27.xlsx"), "District Table")
    long = df.melt(id_vars="District", var_name="code_col", value_name="addon")
    long["code_col"] = long["code_col"].astype(str)
    long["speech"] = long.code_col.str.contains("speech")
    long["code"] = long.code_col.str.replace(" + speech", "", regex=False).str.zfill(2)
    long["addon"] = long["addon"].map(to_number)
    return long.rename(columns={"District": "district"})[["district", "code", "speech", "addon"]]


# ======================================================================== registry
@dataclass
class Dataset:
    id: str
    title: str
    group: str
    loader: Callable[[Path], object]
    source: str
    notes: str = ""
    tags: list = field(default_factory=list)


DATASETS: list[Dataset] = [
    Dataset("nov_kpis", "Headline counts", "Nov dashboard", nov_kpis, "Nov.26-Dashboard/*.xlsx (1x1 tiles)"),
    Dataset("nov_tier", "Eligible vs funded by priority tier", "Nov dashboard", nov_tier,
            "Participation by Priority Tier.xlsx", "Tier 4(a) funded is blank in the source (suppressed).", ["breakdown"]),
    Dataset("nov_income", "Eligible vs funded by income band", "Nov dashboard", nov_income, "Applicants by Income.xlsx", tags=["breakdown"]),
    Dataset("nov_disability_tier", "Applicants with disabilities by tier", "Nov dashboard", nov_disability_tier,
            "Applicants With Disabilities.xlsx", "Only tiers 1, 4(a), 4(b) appear in the source.", ["breakdown"]),
    Dataset("nov_grade", "Eligible vs funded by grade", "Nov dashboard", nov_grade, "Participants by Grade level.xlsx", tags=["breakdown"]),
    Dataset("nov_age", "Funded by age band", "Nov dashboard", nov_age, "Funded Participants by Age.xlsx", tags=["breakdown"]),
    Dataset("nov_gender", "Funded share by gender", "Nov dashboard", nov_gender, "Funded Participants by Gender.xlsx", "Shares only, no counts.", ["breakdown"]),
    Dataset("nov_race", "Funded share by race/ethnicity", "Nov dashboard", nov_race, "Funded Participants  by Race_Ethnicity.xlsx",
            "Shares only, no counts (published as percents).", ["breakdown"]),
    Dataset("nov_house", "Funded & waitlisted by Texas House district", "Nov dashboard", nov_house,
            "Funded Participants by House Districts.xlsx", "Exact counts by district; one row has no district."),
    Dataset("nov_senate", "Funded & waitlisted by Texas Senate district", "Nov dashboard", nov_senate,
            "Funded Participants by Senate Districts.xlsx", "Exact counts by district; one row has no district."),
    Dataset("nov_prior_public", "Funded by prior-year schooling", "Nov dashboard", nov_prior_public,
            "Prior Year Public School Participation.xlsx", tags=["breakdown"]),
    Dataset("nov_isd", "Top 30 ISDs by funded participants", "Nov dashboard", nov_isd, "ISD Participation Heat Map.xlsx"),
    Dataset("nov_funding_allocation", "School funding vs marketplace spend", "Nov spending", nov_funding_allocation, "Expenditures/Funding Allocation.xlsx"),
    Dataset("nov_category", "Marketplace spend by category", "Nov spending", nov_category, "Vendors/Category.xlsx"),
    Dataset("nov_subcategory", "Marketplace spend by subcategory", "Nov spending", nov_subcategory, "Vendors/Sub Category.xlsx"),
    Dataset("nov_top_vendors", "Top vendors (export has 15 rows)", "Nov spending", nov_top_vendors, "Expenditures/Top 20 Vendors by Expenditure or Transactions.xlsx"),
    Dataset("nov_top_schools", "Top schools (export has 15 rows)", "Nov spending", nov_top_schools, "Expenditures/Top 20 Schools by Expenditure or Transactions.xlsx"),
    Dataset("nov_top_subcats", "Top subcategories (export has 15 rows)", "Nov spending", nov_top_subcats, "Expenditures/Top 20 Sub Categories by Expenditure or Transactions.xlsx"),
    Dataset("nov_vendor_distribution", "Vendors by expenditure range", "Nov spending", nov_vendor_distribution, "Expenditures/Vendor Distribution by Expenditure.xlsx"),
    Dataset("nov_all_schools", "All schools: transactions & expenditure", "Nov spending", nov_all_schools, "Vendors/All Schools.csv"),
    Dataset("nov_all_vendors", "All vendors: transactions & expenditure", "Nov spending", nov_all_vendors, "Vendors/All Vendors (2).csv"),
    Dataset("july_age", "Eligible vs funded by single-year age", "July release", july_age, "Voucher Data - July Release.xlsx", tags=["breakdown"]),
    Dataset("july_gender", "Eligible vs funded by sex", "July release", july_gender, "Voucher Data - July Release.xlsx", tags=["breakdown"]),
    Dataset("july_race", "Eligible vs funded by race/ethnicity", "July release", july_race, "Voucher Data - July Release.xlsx", tags=["breakdown"]),
    Dataset("july_district", "Funded participants by district", "July release", july_district, "Voucher Data - July Release.xlsx"),
    Dataset("july_campus", "Funded participants by prior campus", "July release", july_campus, "Voucher Data - July Release.xlsx",
            "Campus names only; the sheet has no per-row district."),
    Dataset("oct_grade", "Funded by grade", "Oct data request", oct_grade, "TEFA_Data-Copy.xlsx", tags=["breakdown"]),
    Dataset("oct_priority", "Funded by priority tier", "Oct data request", oct_priority, "TEFA_Data-Copy.xlsx",
            "Tiers 4-5 suppressed (<30).", ["breakdown"]),
    Dataset("oct_school_selected", "Funded by school selected", "Oct data request", oct_school_selected, "TEFA_Data-Copy.xlsx", tags=["breakdown"]),
    Dataset("oct_sped_flag", "Funded by SPED eligibility flag", "Oct data request", oct_sped_flag, "TEFA_Data-Copy.xlsx", tags=["breakdown"]),
    Dataset("oct_district_prior_public", "Prior-public participants by district", "Oct data request", oct_district_prior_public,
            "TEFA_Data-Copy.xlsx", "Source note: data is parent-reported. Loss column dropped (superseded flat-rate method)."),
    Dataset("oct1_district", "Funded participants by district (30+)", "Oct 1 data request", oct1_district,
            _OCT1, "Demographic columns in the sheet are empty; only counts are published. "
            "Districts under 30 participants are not listed."),
    Dataset("district_roster", "District roster with enrollment", "Reference", district_roster, "TEFA_Data-Copy.xlsx / gsheet_2025",
            "-999 enrollment values treated as missing."),
    Dataset("esc_regions", "Education service center regions", "Reference", esc_regions, "ESC2024.csv",
            "Region number, headquarters city and website (Texas Shapefiles folder)."),
    Dataset("vendor_directory", "Participating vendor directory", "Reference", vendor_directory, "TEFA-Participating-Vendors.xlsx"),
    Dataset("vendor_directory_spend", "Vendor directory with marketplace spending", "Reference", vendor_directory_spend,
            "TEFA-Participating-Vendors.xlsx + Vendors/All Vendors (2).csv",
            "Spending joined by vendor name; vendors not in the spending list show $0."),
    Dataset("sped_by_code", "SPED add-on by IEP instructional code", "Special education", sped_by_code, "TEFA_SpecialEd_Funding_by_Code_2026-27.xlsx"),
    Dataset("sped_district_table", "SPED add-on by district and code", "Special education", sped_district_table, "TEFA_SpecialEd_Funding_by_Code_2026-27.xlsx"),
]
BY_ID = {d.id: d for d in DATASETS}


def load(ds_id: str, base: Path):
    """Return (data, error_message). Never raises, so a missing file can't break the app."""
    try:
        return BY_ID[ds_id].loader(base), None
    except FileNotFoundError as e:
        return None, f"File not found: {e}"
    except Exception as e:  # noqa: BLE001 - surface any parse problem in the UI
        return None, f"{type(e).__name__}: {e}"


def breakdowns(base: Path) -> pd.DataFrame:
    """All breakdown tables stacked in the shared tidy schema."""
    frames = []
    for d in DATASETS:
        if "breakdown" in d.tags:
            df, err = load(d.id, base)
            if df is not None:
                frames.append(df.assign(dataset=d.id))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=TIDY_COLS + ["dataset"])


def funding_rate(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot eligible/funded and add funded ÷ eligible where both are published."""
    p = df.pivot_table(index=["release", "dimension", "category"], columns="metric",
                       values="value", aggfunc="first", sort=False).reset_index()
    if {"eligible", "funded"} <= set(p.columns):
        p["funded_rate"] = p["funded"] / p["eligible"]
    return p
