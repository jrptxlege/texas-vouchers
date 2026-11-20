"""Legislative boundaries and the school-district → legislative-district crosswalk.

Inputs (Texas Legislative Council "all files" downloads, in the shapefile folder):
  * PLANH####.zip / PLANS####.zip  – district shapefiles (House / Senate)
  * PLANH####_r160_ISDsSY##-##.xls – Red-160 "District Population Analysis with School
    District Subtotals": for every legislative district, each school district inside it
    with 2020 Census total and under-18 population.

The newest plan zip in the folder is used, and the newest school-year Red-160 for that
plan, so dropping in a new TLC download upgrades the app without code changes.
A Congressional layer appears automatically if a PLANC####.zip shapefile is added.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import config as C

CHAMBERS = {"H": "Texas House", "S": "Texas Senate", "C": "U.S. House (Texas)"}
SIMPLIFY_METERS = 150  # boundary simplification for web maps; 0 keeps full detail


@dataclass(frozen=True)
class Plan:
    chamber: str        # "H" | "S" | "C"
    name: str           # e.g. "PLANH2316"
    shapefile_zip: Path
    r160: Path | None   # ISD crosswalk report, if present
    school_year: str | None


def _plan_zips(shape_dir: Path) -> list[Path]:
    return [p for p in shape_dir.rglob("*.zip") if re.fullmatch(r"PLAN[HSC]\d+\.zip", p.name, re.I)]


def find_plans(shape_dir: Path) -> dict[str, Plan]:
    """Latest plan per chamber found under shape_dir."""
    out: dict[str, Plan] = {}
    if not shape_dir.exists():
        return out
    for z in sorted(_plan_zips(shape_dir), key=lambda p: p.stat().st_mtime):
        name = z.stem.upper()
        ch = name[4]
        reports = [(m.group(1), p) for p in z.parent.glob(f"{z.stem}*r160*ISDs*SY*.xls*")
                   if (m := re.search(r"SY(\d{2}-\d{2})", p.name))]
        sy, r160 = max(reports) if reports else (None, None)
        out[ch] = Plan(ch, name, z, r160, sy)
    return out


# ------------------------------------------------------------------- boundaries
def _cache_dir() -> Path:
    d = C.APP_DIR / ".cache"
    d.mkdir(exist_ok=True)
    return d


def boundaries_geojson(plan: Plan) -> dict:
    """District polygons as WGS84 GeoJSON (cached next to the app; rebuilt if the zip changes).

    Feature id = district number (int), so choropleths join on it directly."""
    stamp = int(plan.shapefile_zip.stat().st_mtime)
    cache = _cache_dir() / f"{plan.name}_{stamp}_s{SIMPLIFY_METERS}.geojson"
    if cache.exists():
        return json.loads(cache.read_text())
    import geopandas as gpd  # imported lazily so the rest of the app runs without it

    inner = f"{plan.name}/{plan.name}.shp"
    try:
        g = gpd.read_file(f"zip://{plan.shapefile_zip}!{inner}")
    except Exception:  # shapefile at the zip root instead of a subfolder
        g = gpd.read_file(f"zip://{plan.shapefile_zip}")
    dcol = next(c for c in g.columns if c.lower() in ("district", "dist", "district_n"))
    g = g.rename(columns={dcol: "district"})[["district", "geometry"]]
    g["district"] = g["district"].astype(int)
    if SIMPLIFY_METERS and g.crs and g.crs.is_projected:
        g["geometry"] = g.geometry.simplify(SIMPLIFY_METERS, preserve_topology=True)
    g = g.to_crs(4326)
    gj = json.loads(g.to_json())
    for f in gj["features"]:
        f["id"] = int(f["properties"]["district"])
    for old in _cache_dir().glob(f"{plan.name}_*.geojson"):
        old.unlink()
    cache.write_text(json.dumps(gj))
    return gj


# -------------------------------------------------------------------- crosswalk
def read_r160(path: Path) -> pd.DataFrame:
    """Parse a Red-160 report into: district, isd, isd_pct, pop, pop_u18.

    Layout: 'DISTRICT n' header rows; then for each school district a row
    'Name ISD (37%)' with 'Total:' values and the next row with '<18:' values.
    The (%) is the share of that school district's population inside the legislative
    district (rounded) — we recompute exact shares from the population columns."""
    raw = pd.read_excel(path, header=None)
    rows, dist, cur = [], None, None
    for r in raw.itertuples(index=False):
        c0, label, val = r[0], r[3], r[4]
        if isinstance(c0, str) and re.match(r"\s*DISTRICT \d+", c0):
            dist, cur = int(c0.split()[1]), None
            continue
        if isinstance(c0, str) and c0.strip():
            cur = c0.strip()
        if label == "Total:" and cur and dist:
            rows.append({"district": dist, "isd_raw": cur, "pop": float(val)})
        elif label == "<18:" and cur and dist and rows and rows[-1]["isd_raw"] == cur:
            rows[-1]["pop_u18"] = float(val)
            cur = None
    df = pd.DataFrame(rows)
    df["isd_pct"] = df.isd_raw.str.extract(r"\(([\d.]+)%\)\s*$").astype(float)
    df["isd"] = df.isd_raw.str.replace(r"\s*\([\d.]+%\)\s*$", "", regex=True)
    return df[["district", "isd", "isd_pct", "pop", "pop_u18"]]


@lru_cache(maxsize=8)
def _crosswalk_cached(path: str, mtime: float) -> pd.DataFrame:
    return read_r160(Path(path))


def crosswalk(plan: Plan) -> pd.DataFrame:
    """ISD × legislative district with allocation weights.

    w_u18 = this piece's share of the ISD's under-18 population (default weight — the
    closest Census proxy for where students live); w_pop = share of total population.
    Each ISD's weights sum to 1 across districts."""
    if plan.r160 is None:
        raise FileNotFoundError(f"No r160 ISD report next to {plan.shapefile_zip.name}")
    df = _crosswalk_cached(str(plan.r160), plan.r160.stat().st_mtime).copy()
    from .districts import key, _clean
    names = df.isd.map(lambda n: _clean(re.sub(r"\s*\(.*\)$", "", n)))
    dups = set(names[df.isd.str.contains(r"\(")])  # TLC qualifies duplicate names with (County)
    df["key"] = df.isd.map(lambda n: key(n, dups))
    tot = df.groupby("key")[["pop", "pop_u18"]].transform("sum")
    df["w_pop"] = (df["pop"] / tot["pop"]).fillna(0)
    df["w_u18"] = (df["pop_u18"] / tot["pop_u18"]).where(tot["pop_u18"] > 0, df["w_pop"]).fillna(0)
    return df


def district_population(plan: Plan) -> pd.DataFrame:
    xw = crosswalk(plan)
    return xw.groupby("district", as_index=False)[["pop", "pop_u18"]].sum()


def allocate(values: pd.DataFrame, plan: Plan, name_col="district", value_col="value",
             weight="w_u18", how="sum") -> tuple[pd.DataFrame, dict]:
    """Apportion school-district values to legislative districts.

    how="sum":  counts (participants, enrollment) split by population share.
    how="mean": rates/amounts (e.g. a per-student add-on) averaged across the ISD
                pieces in each legislative district, weighted by under-18 population.
    Returns (table by legislative district, diagnostics)."""
    from .districts import key
    xw = crosswalk(plan)
    dups = set(k.split(" | ")[0] for k in xw.key if " | " in k)
    v = values[[name_col, value_col]].dropna().copy()
    v["key"] = v[name_col].map(lambda n: key(n, dups))
    # Some sources truncate long names ("CARROLLTON FARMERS"); accept a unique prefix match.
    known = set(xw.key)
    def _prefix(k):
        if k in known:
            return k
        hits = [x for x in known if x.startswith(k + " ")]
        return hits[0] if len(hits) == 1 else k
    v["key"] = v["key"].map(_prefix)
    v = v.groupby("key", as_index=False)[value_col].sum() if how == "sum" else v.groupby("key", as_index=False)[value_col].mean()
    m = xw.merge(v, on="key", how="inner")
    if how == "sum":
        m["alloc"] = m[value_col] * m[weight]
        out = m.groupby("district", as_index=False)["alloc"].sum()
    else:
        m["wv"] = m[value_col] * m["pop_u18"]
        g = m.groupby("district", as_index=False).agg(wv=("wv", "sum"), w=("pop_u18", "sum"))
        out = pd.DataFrame({"district": g.district, "alloc": g.wv / g.w})
    unmatched = sorted(set(v.key) - set(xw.key))
    total = v[value_col].sum()
    diag = {"source_rows": len(v), "matched_rows": len(v) - len(unmatched), "unmatched": unmatched,
            "share_of_total_allocated": (m.drop_duplicates("key")[value_col].sum() / total) if total and how == "sum" else None}
    return out.rename(columns={"alloc": "value"}), diag


def isd_pieces(plan: Plan, district: int) -> pd.DataFrame:
    """The school districts that make up one legislative district (for drill-down)."""
    xw = crosswalk(plan)
    return xw[xw.district == district][["isd", "isd_pct", "pop", "pop_u18", "w_u18"]].sort_values("pop", ascending=False)
