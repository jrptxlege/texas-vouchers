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


def _env_flag(name: str) -> bool | None:
    v = os.environ.get(name, "").strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return None


def live_data_available() -> bool:
    """True when the shared-drive TEFA folder is reachable (never the case on a host)."""
    return (DEFAULT_DATA_DIR / NOV_DIR).exists()


def public_mode() -> bool:
    """Public (hosted) mode: sidebar folder boxes and the Data & QA page are not shown.

    On by default whenever the shared drive isn't reachable or the bundle is forced, so a
    hosted copy is locked down without any setting. TEFA_PUBLIC=1 forces it on (e.g. to
    preview the public version locally); TEFA_PUBLIC=0 forces it off."""
    flag = _env_flag("TEFA_PUBLIC")
    if flag is not None:
        return flag
    return use_bundle() or not live_data_available()


def live_shape_dir() -> Path:
    """EO Team/EO Data/Texas Shapefiles, found relative to the live TEFA data folder
    (…/EO Team/PubEd/Vouchers/TEFA Public Data)."""
    d = DEFAULT_DATA_DIR
    # On a host the app sits at a shallow path (e.g. /mount/src/<repo>), so there is no
    # EO Team folder to climb to. Return a path that won't exist rather than falling back
    # to the app's parent folder, which does exist and would hide the bundled maps.
    base = d.parents[2] if len(d.parents) > 2 else d
    return base / "EO Data" / "Texas Shapefiles"


def data_dir() -> Path:
    env = os.environ.get("TEFA_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if not use_bundle() and live_data_available():
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
