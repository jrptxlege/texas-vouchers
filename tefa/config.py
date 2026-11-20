"""Where the app looks for data.

Default: the folder that contains this app folder (i.e. "TEFA Public Data" when the
app lives at "TEFA Public Data/tefa_viz"). Override with the TEFA_DATA_DIR environment
variable or the sidebar path box in the app.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = APP_DIR.parent


def data_dir() -> Path:
    env = os.environ.get("TEFA_DATA_DIR")
    return Path(env).expanduser() if env else DEFAULT_DATA_DIR


def shape_dir() -> Path:
    """Folder with Texas Legislative Council plan downloads (PLANH####.zip etc.).
    Default: EO Team/EO Data/Texas Shapefiles, found relative to the TEFA data folder
    (…/EO Team/PubEd/Vouchers/TEFA Public Data). Override with TEFA_SHAPE_DIR."""
    env = os.environ.get("TEFA_SHAPE_DIR")
    if env:
        return Path(env).expanduser()
    d = data_dir()
    return d.parents[2] / "EO Data" / "Texas Shapefiles" if len(d.parents) > 2 else d


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
