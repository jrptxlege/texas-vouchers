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
    # Only non-geographic entities (no boundaries) should fail to match the crosswalk.
    _, diag = layers.build("oct1_funded", BASE, plan)
    assert diag["unmatched"] == ["HARRIS COUNTY DEPT OF ED"], diag["unmatched"]


@pytest.mark.skipif(not (config.live_shape_dir().exists() and (config.BUNDLE_GEO_DIR).exists()),
                    reason="needs both the shapefile folder and the bundled data/geo")
def test_bundled_map_files_match_live():
    """The pre-built geojson/crosswalk in data/geo must equal what the shapefiles produce."""
    import pandas as pd
    from tefa import geo
    live, bund = geo.find_plans(config.live_shape_dir()), geo.find_plans(config.BUNDLE_GEO_DIR)
    assert live["H"].shapefile_zip is not None, "live folder should hold the TLC zips"
    for ch, n in [("H", 150), ("S", 31), ("C", 38)]:
        assert live[ch].name == bund[ch].name and bund[ch].geojson is not None
        ids = sorted(f["id"] for f in geo.boundaries_geojson(bund[ch])["features"])
        assert ids == list(range(1, n + 1)), ch
        assert ids == sorted(f["id"] for f in geo.boundaries_geojson(live[ch])["features"])
        pd.testing.assert_frame_equal(geo.crosswalk(live[ch]).reset_index(drop=True),
                                      geo.crosswalk(bund[ch]).reset_index(drop=True), check_dtype=False)


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
    """What a hosted copy does: read data/ only, with geopandas/calamine not installed."""
    import subprocess
    import sys
    code = """
import sys
for m in ("geopandas", "python_calamine", "xlrd", "pyogrio"):
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


# ------------------------------------------------------------- public (hosted) mode
def test_public_mode_flag(monkeypatch):
    monkeypatch.setenv("TEFA_PUBLIC", "1")
    assert config.public_mode()
    monkeypatch.setenv("TEFA_PUBLIC", "0")
    assert not config.public_mode()
    monkeypatch.delenv("TEFA_PUBLIC")
    monkeypatch.setenv("TEFA_USE_BUNDLE", "1")
    assert config.public_mode(), "running from the bundle (as a host does) must default to public"


def _app(monkeypatch, public: str):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("TEFA_PUBLIC", public)
    at = AppTest.from_file(str(config.APP_DIR / "Home.py"), default_timeout=300)
    at.run()
    assert not at.exception, at.exception
    return at


@needs_data
def test_public_mode_locks_sidebar_and_hides_qa(monkeypatch):
    at = _app(monkeypatch, "1")
    assert [t.label for t in at.text_input] == [], "folder boxes must not render in public mode"
    assert "Reload data" not in [b.label for b in at.button]
    with pytest.raises(ValueError):  # page not registered: no menu entry, no URL
        at.switch_page("views/data_qa.py")
    at.switch_page("views/legislative_map.py").run()
    assert not at.exception and [t.label for t in at.text_input] == []


@needs_data
def test_staff_mode_keeps_tools(monkeypatch):
    at = _app(monkeypatch, "0")
    assert "Data folder" in [t.label for t in at.text_input]
    at.switch_page("views/data_qa.py").run()
    assert not at.exception


def _page_text(at) -> str:
    parts = []
    for kind in ("markdown", "caption", "warning", "info", "error", "expander", "title", "subheader"):
        for el in getattr(at, kind, []):
            parts.append(str(getattr(el, "value", "") or getattr(el, "label", "")))
    return "\n".join(parts)


DEV_MARKERS = ("tefa/", ".py", "ALIASES", "CITY_COUNTY", "worth checking", "not matched to the roster")


@needs_data
@needs_shapes
@pytest.mark.parametrize("public, expect_dev", [("1", False), ("0", True)])
def test_developer_notes_only_in_staff_mode(monkeypatch, public, expect_dev):
    at = _app(monkeypatch, public)
    found = {}
    pages = ["views/home.py", "views/participants.py", "views/districts.py", "views/spending.py",
             "views/vendors.py", "views/special_education.py", "views/legislative_map.py"]
    for page in pages:
        at.switch_page(page).run()
        assert not at.exception, (page, at.exception)
        texts = [_page_text(at)]
        if page.endswith("legislative_map.py"):  # estimated layer: shows the "names not placed" popover
            at.selectbox[0].set_value("july_funded").run()
            texts.append(_page_text(at))
        hits = [m for m in DEV_MARKERS if any(m in t for t in texts)]
        if hits:
            found[page] = hits
    if expect_dev:
        assert "views/districts.py" in found and "views/legislative_map.py" in found, found
    else:
        assert not found, f"developer notes visible in public mode: {found}"


# ---------------------------------------------------------------------- ESC regions
def test_region_label_fallback():
    assert D.region_label(4, None) == "Region 4"
    assert D.region_label(float("nan"), None) == "No region"


@needs_data
def test_esc_regions():
    esc, err = D.load("esc_regions", BASE)
    assert err is None, err
    assert list(esc.region) == list(range(1, 21))
    assert D.region_label(4, esc) == "Region 4 · Houston"
    assert esc.website.str.startswith("https://").all()
    roster, _ = D.load("district_roster", BASE)
    assert set(roster.region.dropna().astype(int)) <= set(esc.region), "roster has regions the ESC file lacks"


# ------------------------------------------------------------------ hosted path layout
@needs_bundle
def test_shallow_host_path_uses_bundled_maps(monkeypatch, tmp_path):
    """Streamlit Cloud runs the app from /mount/src/<repo>: the folder above the app exists
    but holds no shapefiles. The map must fall back to data/geo, not look in /mount/src."""
    from tefa import geo
    for v in ("TEFA_SHAPE_DIR", "TEFA_DATA_DIR", "TEFA_USE_BUNDLE", "TEFA_PUBLIC"):
        monkeypatch.delenv(v, raising=False)
    shallow = type(tmp_path)(tmp_path.anchor)  # an existing folder with no parents to climb (C:\ or /)
    assert shallow.exists()
    monkeypatch.setattr(config, "DEFAULT_DATA_DIR", shallow)
    assert config.shape_dir() == config.BUNDLE_GEO_DIR
    assert config.data_dir() == config.BUNDLE_DIR and config.public_mode()
    assert {"H", "S", "C"} <= set(geo.find_plans(config.shape_dir()))


# --------------------------------------------------------------------------- tooltips
def _hovertemplates(at):
    import json
    for el in at.get("plotly_chart"):
        spec = json.loads(el.proto.spec)
        for t in spec.get("data", []):
            if t.get("hovertemplate"):
                yield t["hovertemplate"]


@needs_bundle
def test_tooltips_have_labels(monkeypatch):
    """Blank Plotly Express labels collide and produce tooltips like '=NaN'."""
    monkeypatch.setenv("TEFA_USE_BUNDLE", "1")
    at = _app(monkeypatch, "1")
    bad, n = {}, 0
    for page in ["views/home.py", "views/participants.py", "views/districts.py", "views/spending.py",
                 "views/vendors.py", "views/special_education.py", "views/legislative_map.py"]:
        at.switch_page(page).run()
        assert not at.exception, (page, at.exception)
        for ht in _hovertemplates(at):
            n += 1
            if ht.startswith("=") or ">=" in ht or "<br>=" in ht:
                bad.setdefault(page, []).append(ht)
    assert n > 10 and not bad, bad


# ------------------------------------------------------------------- vendor spending
def test_to_bounds():
    from tefa.readers import to_bounds
    assert to_bounds("$12,267,200") == (12267200, 12267200)
    assert to_bounds("$0-2,500") == (0, 2500)
    assert to_bounds("$2.501-5,000") == (2501, 5000)  # typo in the schools export
    assert to_bounds("<10") == (0, 9)
    assert all(np.isnan(to_bounds("")))


@needs_bundle
def test_vendor_directory_spend():
    df, err = D.load("vendor_directory_spend", config.BUNDLE_DIR)
    assert err is None
    full, _ = D.load("nov_all_vendors", config.BUNDLE_DIR)
    assert full.expenditure_low.notna().all(), "every published amount (exact or band) must parse"
    u = df.drop_duplicates("vendor_key")
    unmatched = df.attrs["unmatched"]
    assert u.has_spending.sum() + len(unmatched) == len(full)  # every spending row lands somewhere once
    assert [r["vendor"] for r in unmatched][:1] == ["Amazon"]
    # directory share + unmatched == the list's band totals
    assert abs(u.expenditure_low.sum() - full[full.vendor.isin([r["vendor"] for r in unmatched]) == False]
               .expenditure_low.sum()) < 1
    assert (df.expenditure_low <= df.expenditure_high).all()
