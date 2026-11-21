"""Where the app looks for data.

Order:
1. TEFA_DATA_DIR / TEFA_SHAPE_DIR environment variables (or the sidebar path boxes).
2. The live folders on the shared drive: the folder that contains this app ("TEFA Public
   Data") and EO Team/EO Data/Texas Shapefiles. Used when they exist.
3. The bundled snapshot in this repo: data/ and data/geo/ (built by
   scripts/build_bundle.py). This is what a hosted copy of the app reads.
Set TEFA_USE_BUNDLE=1 to force the snapshot even when the live folders exist.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = APP_DIR.parent
BUNDLE_DIR = APP_DIR / "data"          # snapshot of the files the loaders read
BUNDLE_GEO_DIR = BUNDLE_DIR / "geo"    # pre-built boundaries + ISD crosswalks


def use_bundle() -> bool:
    return os.environ.get("TEFA_USE_BUNDLE", "").strip().lower() in {"1", "true", "yes"}


def live_shape_dir() -> Path:
    """EO Team/EO Data/Texas Shapefiles, found relative to the live TEFA data folder
    (…/EO Team/PubEd/Vouchers/TEFA Public Data)."""
    d = DEFAULT_DATA_DIR
    return d.parents[2] / "EO Data" / "Texas Shapefiles" if len(d.parents) > 2 else d


def data_dir() -> Path:
    env = os.environ.get("TEFA_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if not use_bundle() and (DEFAULT_DATA_DIR / NOV_DIR).exists():
        return DEFAULT_DATA_DIR
    return BUNDLE_DIR


def shape_dir() -> Path:
    """Folder with Texas Legislative Council plan downloads (PLANH####.zip etc.), or the
    bundled pre-built map files. Override with TEFA_SHAPE_DIR."""
    env = os.environ.get("TEFA_SHAPE_DIR")
    if env:
        return Path(env).expanduser()
    live = live_shape_dir()
    if not use_bundle() and live.exists():
        return live
    return BUNDLE_GEO_DIR


# Optional: a CSV of current members (columns incl. chamber, district, and a name column)
# shown in map hovers. Looked for in the shapefile folder, then the data folder.
MEMBERS_GLOB = "*legislators*.csv"


# Subfolder names used by the November public dashboard export.
NOV_DIR = "Nov.26-Dashboard"
NOV_EXP = f"{NOV_DIR}/Expenditures"
NOV_VEND = f"{NOV_DIR}/Vendors"

# Release labels shown in the UI. Keep these short; they become legend entries.
REL_JULY = "July 2026 release"
REL_OCT = "Oct 1 data request"
REL_NOV = "Nov 2026 dashboard"
RELEASE_ORDER = [REL_JULY, REL_OCT, REL_NOV]
