"""Build the data snapshot a hosted copy of the app reads (data/ and data/geo/).

Run from the tefa_viz folder, on a machine that can see the shared drive:

    python scripts/build_bundle.py            # rebuild the snapshot
    python scripts/build_bundle.py --check    # only report whether it is up to date

What it does
1. Runs every loader against the live TEFA folder and records each file they open, then
   copies exactly those files into data/, keeping their folder layout. File names are
   tidied (non-breaking and doubled spaces become one space); the loaders find files
   by normalized name, so they still match.
2. Pre-builds the map: for each Texas Legislative Council plan (House, Senate,
   Congressional) it writes data/geo/PLAN####.geojson (boundaries simplified to ~150 m,
   coordinates rounded to ~1 m) and data/geo/PLAN####_isd_crosswalk.csv (the parsed
   Red-160 school-district report). The hosted app then needs neither geopandas nor python-calamine.
   It also copies the newest ESC####.csv (education service center regions: number,
   headquarters city, website) from the shapefile folder into data/geo/.
3. Writes data/MANIFEST.json: every bundled file with its source, size and SHA-256.

Needs the full local requirements (requirements-dev.txt), since it reads the shapefiles.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from tefa import config as C  # noqa: E402
from tefa import datasets as D  # noqa: E402
from tefa import geo, readers  # noqa: E402

BUNDLE = C.BUNDLE_DIR
GEO = C.BUNDLE_GEO_DIR
COORD_DECIMALS = 5  # ~1 m; the boundaries are already simplified to ~150 m


def tidy_name(name: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name).replace(" ", " ")).strip()


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def files_read_by_loaders(base: Path) -> list[Path]:
    """Run every loader with find_file wrapped, and return the files actually opened."""
    used: set[Path] = set()
    orig = readers.find_file

    def recording(b, rel):
        p = orig(b, rel)
        if p is not None:
            used.add(p.resolve())
        return p

    D.find_file = recording  # datasets imported find_file by name
    try:
        errors = {}
        for d in D.DATASETS:
            _, err = D.load(d.id, base)
            if err:
                errors[d.id] = err
        D.oct1_totals(base)
    finally:
        D.find_file = orig
    if errors:
        raise SystemExit("Loaders failed against the live folder; fix these before bundling:\n"
                         + "\n".join(f"  {k}: {v}" for k, v in errors.items()))
    return sorted(used)


def _round_coords(obj):
    if isinstance(obj, float):
        return round(obj, COORD_DECIMALS)
    if isinstance(obj, list):
        return [_round_coords(x) for x in obj]
    return obj


def plan_outputs(plan: geo.Plan) -> dict[str, object]:
    """name -> content (dict for JSON, DataFrame for CSV) for one plan."""
    gj = geo.boundaries_geojson(plan)
    for f in gj["features"]:
        f["geometry"]["coordinates"] = _round_coords(f["geometry"]["coordinates"])
        f["properties"] = {"district": f["properties"]["district"]}
    xw = geo.read_r160(plan.r160) if plan.r160 else None
    meta = {"chamber": plan.chamber, "plan": plan.name, "school_year": plan.school_year,
            "source_shapefile": plan.shapefile_zip.name if plan.shapefile_zip else None,
            "source_r160": plan.r160.name if plan.r160 else None,
            "simplify_meters": geo.SIMPLIFY_METERS, "coord_decimals": COORD_DECIMALS}
    out = {geo.PREBUILT_GEOJSON.format(name=plan.name): gj, geo.PREBUILT_META.format(name=plan.name): meta}
    if xw is not None:
        out[geo.PREBUILT_CROSSWALK.format(name=plan.name)] = xw
    return out


def esc_source(src_shapes: Path) -> Path | None:
    hits = sorted(p for p in src_shapes.glob("ESC*.csv") if re.fullmatch(r"ESC\d{4}\.csv", p.name, re.I))
    return hits[-1] if hits else None


def reference_hashes(src_shapes: Path) -> dict[str, str]:
    """Shapefile-folder reference files (not read through find_file) tracked for staleness."""
    e = esc_source(src_shapes)
    return {f"{src_shapes.name}/{e.name}": sha256(e)} if e else {}


def _sync(src: Path, dst: Path):
    """Make dst match src: copy new/changed files, delete files src doesn't have.
    Empty folders left behind are removed when possible (OneDrive may hold them briefly)."""
    want = {p.relative_to(src) for p in src.rglob("*") if p.is_file()}
    for rel in sorted(want):
        s_, d_ = src / rel, dst / rel
        if d_.exists() and sha256(d_) == sha256(s_):
            continue
        d_.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s_, d_)
    if dst.exists():
        for p in sorted(dst.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            rel = p.relative_to(dst)
            if p.is_file() and rel not in want:
                p.unlink()
            elif p.is_dir() and not any(p.iterdir()):
                try:
                    p.rmdir()
                except OSError:
                    pass


def build(src_data: Path, src_shapes: Path) -> dict:
    if (src_data.resolve() == BUNDLE.resolve()) or not (src_data / C.NOV_DIR).exists():
        raise SystemExit(f"Live TEFA folder not found at {src_data}. Run this where the shared drive is available "
                         "(or set TEFA_DATA_DIR).")
    plans = {ch: p for ch, p in geo.find_plans(src_shapes).items() if p.shapefile_zip is not None}
    if not plans:
        raise SystemExit(f"No TLC plan zips found under {src_shapes} (set TEFA_SHAPE_DIR).")

    # Build into a temporary folder, then sync it into data/ file by file. Deleting data/
    # wholesale fails on OneDrive (it can lock folders mid-delete) and would leave a
    # half-empty bundle if anything went wrong.
    stage = Path(tempfile.mkdtemp(prefix="tefa_bundle_"))
    out, out_geo = stage / "data", stage / "data" / "geo"
    out_geo.mkdir(parents=True)

    entries = []
    for src in files_read_by_loaders(src_data):
        rel = src.relative_to(src_data.resolve())
        dest_rel = Path(*[tidy_name(part) for part in rel.parts])
        dest = out / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        entries.append({"path": dest_rel.as_posix(), "source": rel.as_posix(),
                        "bytes": dest.stat().st_size, "sha256": sha256(dest)})

    for ch, plan in sorted(plans.items()):
        for name, content in plan_outputs(plan).items():
            dest = out_geo / name
            if name.endswith(".csv"):
                content.to_csv(dest, index=False)
            else:
                dest.write_text(json.dumps(content, separators=(",", ":")), encoding="utf-8")
            src = plan.r160 if name.endswith(".csv") else plan.shapefile_zip
            entries.append({"path": f"geo/{name}", "source": f"{src_shapes.name}/{src.relative_to(src_shapes).as_posix()}",
                            "bytes": dest.stat().st_size, "sha256": sha256(dest)})

    esc = esc_source(src_shapes)
    if esc is not None:
        dest = out_geo / esc.name
        shutil.copy2(esc, dest)
        entries.append({"path": f"geo/{esc.name}", "source": f"{src_shapes.name}/{esc.name}",
                        "bytes": dest.stat().st_size, "sha256": sha256(dest)})
    else:
        print("Note: no ESC####.csv in the shapefile folder; regions will show as plain numbers.")

    manifest = {"built": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "source_data_dir": src_data.name, "source_shape_dir": src_shapes.name,
                "plans": {ch: p.name for ch, p in sorted(plans.items())},
                "source_hashes": {**{p.relative_to(src_data.resolve()).as_posix(): sha256(p)
                                     for p in files_read_by_loaders(src_data)},
                                  **reference_hashes(src_shapes)},
                "files": entries}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (out / "README.md").write_text(
        "# Bundled data snapshot\n\nGenerated by `scripts/build_bundle.py` — do not edit by hand.\n"
        "Copies of the public TEFA files the app reads, plus pre-built map boundaries and ISD crosswalks\n"
        "(`geo/`). `MANIFEST.json` lists each file's source and SHA-256. Rebuild after new data lands.\n",
        encoding="utf-8")
    _sync(out, BUNDLE)
    shutil.rmtree(stage, ignore_errors=True)
    return manifest


def check(src_data: Path, src_shapes: Path | None = None) -> list[str]:
    """Differences between the live files the loaders read and the snapshot's record."""
    mf = BUNDLE / "MANIFEST.json"
    if not mf.exists():
        return ["No bundle yet (data/MANIFEST.json missing)."]
    recorded = json.loads(mf.read_text(encoding="utf-8")).get("source_hashes", {})
    live = {p.relative_to(src_data.resolve()).as_posix(): sha256(p) for p in files_read_by_loaders(src_data)}
    live.update(reference_hashes(src_shapes or C.live_shape_dir()))
    out = [f"changed: {k}" for k in live if k in recorded and live[k] != recorded[k]]
    out += [f"new: {k}" for k in live if k not in recorded]
    out += [f"no longer read: {k}" for k in recorded if k not in live]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="only report whether data/ is up to date")
    args = ap.parse_args()
    src_data, src_shapes = C.DEFAULT_DATA_DIR, C.live_shape_dir()
    import os
    src_data = Path(os.environ.get("TEFA_DATA_DIR", src_data))
    src_shapes = Path(os.environ.get("TEFA_SHAPE_DIR", src_shapes))
    if args.check:
        diffs = check(src_data, src_shapes)
        print("Bundle is up to date." if not diffs else "Bundle is out of date:\n  " + "\n  ".join(diffs))
        sys.exit(1 if diffs else 0)
    m = build(src_data, src_shapes)
    total = sum(f["bytes"] for f in m["files"])
    print(f"Wrote {len(m['files'])} files ({total / 1e6:.1f} MB) to {BUNDLE.relative_to(APP_DIR)}/ "
          f"— plans: {', '.join(m['plans'].values())}")


if __name__ == "__main__":
    main()
