"""Low-level, format-tolerant readers.

The TEFA public files come from several tools (Tableau crosstab exports, Excel
workbooks built by hand, a database query dump). These helpers absorb the quirks:
UTF-16 tab-delimited CSVs, numbers stored as "$1,234" strings, 1x1 "KPI" sheets,
and crosstabs with a blank corner cell.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- files
def norm_name(s: str) -> str:
    """Normalize a file name for fuzzy matching (whitespace, NBSP, case)."""
    s = unicodedata.normalize("NFKC", s).replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def find_file(base: Path, rel: str) -> Path | None:
    """Locate base/rel, tolerating doubled spaces / non-breaking spaces in names.

    Several exported file names contain double spaces (e.g. "Funded Participants  by
    Race_Ethnicity.xlsx"), which are easy to mistype and sometimes differ by
    Unicode space type. We match on a normalized name within the same folder.
    """
    p = base / rel
    if p.exists():
        return p
    parent = (base / rel).parent
    if not parent.exists():
        return None
    target = norm_name(Path(rel).name)
    for child in parent.iterdir():
        if norm_name(child.name) == target:
            return child
    return None


# ------------------------------------------------------------------------- numbers
_NUM_RE = re.compile(r"[,$%\s]")


def to_number(x):
    """'$1,234' -> 1234.0, '12%' -> 0.12, '*' or '' -> NaN, numbers pass through."""
    if x is None:
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip()
    if s in {"", "*", "-", "—", "n/a", "N/A", "nan"}:
        return np.nan
    pct = s.endswith("%")
    neg = s.startswith("(") and s.endswith(")")
    s = _NUM_RE.sub("", s.strip("()"))
    try:
        v = float(s)
    except ValueError:
        return np.nan
    if pct:
        v /= 100
    return -v if neg else v


def to_bounds(x) -> tuple[float, float]:
    """Published value -> (low, high). Exact numbers give (v, v); the dashboard's bands
    give their ends: '$2,501-5,000' -> (2501, 5000), '<10' -> (0, 9). Unreadable -> NaNs.
    ('$2.501-5,000' appears in one export; a '.' before three digits is a thousands mark.)"""
    v = to_number(x)
    if not np.isnan(v):
        return v, v
    s = re.sub(r"(?<=\d)\.(?=\d{3}\b)", ",", str(x).strip())
    m = re.fullmatch(r"\$?\s*([\d,]+(?:\.\d+)?)\s*[-–]\s*\$?\s*([\d,]+(?:\.\d+)?)", s)
    if m:
        return to_number(m.group(1)), to_number(m.group(2))
    m = re.fullmatch(r"<\s*\$?\s*([\d,]+)", s)
    if m:
        return 0.0, to_number(m.group(1)) - 1
    return np.nan, np.nan


def add_bounds(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Keep `col` exact (NaN for bands) and add col_low / col_high from the published text."""
    b = df[col].map(to_bounds)
    df[f"{col}_low"] = b.str[0]
    df[f"{col}_high"] = b.str[1]
    return df


def numeric_cols(df: pd.DataFrame, cols) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        df[c] = df[c].map(to_number)
    return df


# --------------------------------------------------------------------------- readers
def read_csv_any(path: Path) -> pd.DataFrame:
    """Read a CSV that may be UTF-16 tab-delimited (Tableau) or plain UTF-8."""
    raw = path.read_bytes()[:4]
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        df = pd.read_csv(path, encoding="utf-16", sep="\t", dtype=str)
    else:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    # Tableau adds a trailing empty column.
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    return df.dropna(how="all")


def read_raw(path: Path, sheet=0) -> pd.DataFrame:
    """Header-less read of one sheet (or CSV) so callers can parse layout themselves."""
    if path.suffix.lower() == ".csv":
        raw = path.read_bytes()[:4]
        enc = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
        return pd.read_csv(path, encoding=enc, sep=None, engine="python", header=None, dtype=str)
    return pd.read_excel(path, sheet_name=sheet, header=None)


def scalar(path: Path, sheet=0) -> float:
    """Value of a single-number KPI export (a 1x1 sheet, or a CSV whose only content
    is the number, which pandas reads as a header)."""
    if path.suffix.lower() == ".csv":
        # Tableau writes KPI CSVs as UTF-16 text like "41,711" — parse the whole text,
        # don't let the thousands separator be read as a delimiter.
        b = path.read_bytes()
        enc = "utf-16" if b[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
        v = to_number(b.decode(enc).strip().strip('"'))
        if np.isnan(v):
            raise ValueError(f"No numeric value found in {path.name}")
        return v
    df = read_raw(path, sheet)
    vals = [to_number(v) for v in df.to_numpy().ravel()]
    vals = [v for v in vals if not np.isnan(v)]
    if not vals:
        raise ValueError(f"No numeric value found in {path.name}")
    return vals[0]


def crosstab(path: Path, sheet=0) -> pd.DataFrame:
    """Parse a Tableau-style crosstab into long form: row_label, col_label, value.

    Layout: row 0 holds column headers (the first cell is a corner/axis title or
    blank); column 0 holds row labels. Blank column headers become 'value'.
    """
    df = read_raw(path, sheet)
    df = df.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    header = df.iloc[0].tolist()
    body = df.iloc[1:]
    out = []
    for _, row in body.iterrows():
        rlab = row.iloc[0]
        for j in range(1, len(header)):
            clab = header[j]
            clab = "value" if pd.isna(clab) else str(clab).strip()
            out.append({"row_label": str(rlab).strip(), "col_label": clab,
                        "raw": row.iloc[j], "value": to_number(row.iloc[j])})
    return pd.DataFrame(out)


def wide_rows(path: Path, sheet=0) -> dict[str, list]:
    """For sheets where categories run across columns (e.g. the ISD heat map):
    return {label in column 0: [values in columns 1..n]} for each labelled row."""
    df = read_raw(path, sheet)
    out = {}
    for _, row in df.iterrows():
        lab = row.iloc[0]
        if pd.isna(lab):
            continue
        out[str(lab).strip()] = row.iloc[1:].tolist()
    return out
