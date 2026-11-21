"""Run with:  pytest -q   (from the tefa_viz folder)

Unit tests for the readers run anywhere. Data tests run against the real folder
(TEFA_DATA_DIR or the default) and are skipped if it isn't there."""
import numpy as np
import pytest

from tefa import checks, config, datasets as D, districts
from tefa.readers import norm_name, to_number


def test_to_number():
    assert to_number("$1,234") == 1234
    assert to_number("41,711") == 41711
    assert to_number("12%") == pytest.approx(0.12)
    assert np.isnan(to_number("*")) and np.isnan(to_number("<30"))
    assert to_number("(5)") == -5


def test_norm_name():
    assert norm_name("Funded Participants  by Race.xlsx") == "funded participants by race.xlsx"


def test_district_keys():
    dups = {"NORTHSIDE ISD"}
    assert districts.key("Northside ISD - San Antonio", dups) == "NORTHSIDE ISD | BEXAR"
    assert districts.key("NORTHSIDE ISD (BEXAR)", dups) == "NORTHSIDE ISD | BEXAR"
    assert districts.key("Northside ISD - Vernon", dups) == "NORTHSIDE ISD | WILBARGER"
    assert districts.key("Houston ISD", dups) == "HOUSTON ISD"


BASE = config.data_dir()
needs_data = pytest.mark.skipif(not (BASE / "Nov.26-Dashboard").exists(), reason="data folder not present")


@needs_data
def test_core_datasets_load():
    core = ["nov_kpis", "nov_tier", "nov_income", "nov_grade", "nov_all_vendors", "july_age", "oct_grade",
            "vendor_directory", "sped_by_code"]
    for ds in core:
        df, err = D.load(ds, BASE)
        assert err is None, f"{ds}: {err}"
        assert len(df) > 0


@needs_data
def test_breakdowns_reconcile_with_headline():
    c = checks.run_checks(BASE)
    for name in ["Eligible vs funded by grade: sum of funded", "Funded by age band: sum of funded",
                 "Funding allocation total"]:
        assert c.loc[c.check == name, "status"].iloc[0] == "ok", name


SHAPES = config.shape_dir()
needs_shapes = pytest.mark.skipif(not SHAPES.exists(), reason="shapefile folder not present")


def test_qualifier_styles():
    from tefa.districts import split_qualifier
    assert split_qualifier("Northside ISD (Bexar) (37%)") == ("NORTHSIDE ISD", "BEXAR")
    assert split_qualifier("Dawson ISD - Welch") == ("DAWSON ISD", "DAWSON")
    assert split_qualifier("Burnet CISD")[0] == "BURNET CONS ISD"


@needs_shapes
def test_plans_and_crosswalk():
    from tefa import geo
    plans = geo.find_plans(SHAPES)
    assert {"H", "S"} <= set(plans)
    for ch, n in [("H", 150), ("S", 31)]:
        xw = geo.crosswalk(plans[ch])
        assert xw.district.nunique() == n
        # every ISD's allocation weights sum to 1
        assert (xw.groupby("key").w_u18.sum().round(6) == 1).all()
        assert len(geo.boundaries_geojson(plans[ch])["features"]) == n


@needs_shapes
@needs_data
def test_layers_build():
    from tefa import geo, layers
    plan = geo.find_plans(SHAPES)["S"]
    for l in layers.LAYERS:
        df, diag = layers.build(l.id, BASE, plan)
        assert len(df) == 31 and df.value.notna().any(), l.id
    df, diag = layers.build("july_funded", BASE, plan)
    assert diag["share_of_total_allocated"] > 0.98


@needs_data
def test_race_shares():
    df, err = D.load("nov_race", BASE)
    assert err is None
    assert set(df.metric) == {"share_funded"}
    assert "White" in set(df.category) and "Hispanic" in set(df.category)
    assert df.value.sum() == pytest.approx(1, abs=0.001)


@needs_data
def test_legislative_tables():
    for ds, n in [("nov_house", 150), ("nov_senate", 31)]:
        df, err = D.load(ds, BASE)
        assert err is None, err
        assert df.district.dropna().nunique() == n
        assert df.member.notna().sum() == n
    c = checks.run_checks(BASE)
    for name in ["House district table: funded total", "Senate district table: funded total",
                 "House vs Senate tables: funded"]:
        assert c.loc[c.check == name, "status"].iloc[0] == "ok", name


@needs_shapes
@needs_data
def test_exact_layers_and_members():
    from tefa import geo, layers
    plans = geo.find_plans(SHAPES)
    df, diag = layers.build("nov_funded", BASE, plans["H"])
    assert df.value.notna().sum() == 150
    assert 0.99 < diag["share_of_total_allocated"] < 1
    m = layers.members(SHAPES, BASE, "S")
    assert m is not None and len(m) == 31


@needs_data
def test_oct1_district():
    df, err = D.load("oct1_district", BASE)
    assert err is None, err
    assert len(df) == df.district.nunique() > 300
    assert df.funded.min() >= 30
    tot = D.oct1_totals(BASE)
    assert df.funded.sum() == tot["in_listed_isds"]
    assert tot["in_listed_isds"] + tot["in_isds_under_30"] == tot["total_reported"]


# ------------------------------------------------------------------ bundled snapshot
BUNDLE_MANIFEST = config.BUNDLE_DIR / "MANIFEST.json"
needs_bundle = pytest.mark.skipif(not BUNDLE_MANIFEST.exists(), reason="no bundled snapshot (data/)")


@needs_bundle
def test_bundle_files_match_manifest():
    import hashlib
    import json
    m = json.loads(BUNDLE_MANIFEST.read_text(encoding="utf-8"))
    for f in m["files"]:
        p = config.BUNDLE_DIR / f["path"]
        assert p.exists(), f["path"]
        assert hashlib.sha256(p.read_bytes()).hexdigest() == f["sha256"], f"{f['path']} changed by hand"


@needs_bundle
def test_bundle_runs_without_geo_libraries():
    """What a hosted copy does: read data/ only, with geopandas/xlrd not installed."""
    import subprocess
    import sys
    code = """
import sys
for m in ("geopandas", "xlrd", "pyogrio"):
    sys.modules[m] = None
from tefa import config as C, datasets as D, geo, layers
assert C.data_dir() == C.BUNDLE_DIR and C.shape_dir() == C.BUNDLE_GEO_DIR
bad = [d.id for d in D.DATASETS if D.load(d.id, C.data_dir())[1]]
assert not bad, bad
plans = geo.find_plans(C.shape_dir())
assert set(plans) == {"H", "S", "C"}, plans
for ch, p in plans.items():
    assert len(geo.boundaries_geojson(p)["features"]) == {"H": 150, "S": 31, "C": 38}[ch]
    for l in layers.LAYERS:
        if l.exact and ch == "C":
            continue
        df, _ = layers.build(l.id, C.data_dir(), p)
        assert df.value.notna().any(), (ch, l.id)
print("ok")
"""
    env = {**__import__("os").environ, "TEFA_USE_BUNDLE": "1"}
    env.pop("TEFA_DATA_DIR", None)
    env.pop("TEFA_SHAPE_DIR", None)
    r = subprocess.run([sys.executable, "-c", code], cwd=config.APP_DIR, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stderr[-2000:]


@needs_bundle
@pytest.mark.skipif(not (config.DEFAULT_DATA_DIR / config.NOV_DIR).exists(), reason="live folder not present")
def test_bundle_is_up_to_date():
    """Fails when the live files changed since the last bundle: run scripts/build_bundle.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_bundle", config.APP_DIR / "scripts" / "build_bundle.py")
    bb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bb)
    assert bb.check(config.DEFAULT_DATA_DIR) == [], "Bundle is stale - run: python scripts/build_bundle.py"
