"""Streamlit helpers shared by every page: data folder picker, cached loading,
source captions, and a 'show the table' toggle under each chart."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from . import config as C
from . import datasets as D


def _path_box(label: str, store: str, default: str, help: str) -> str:
    """Sidebar folder box whose value survives page changes.

    Streamlit resets a widget when you switch pages (each page's widget is a new widget),
    so the value lives under a separate, non-widget key (`store`). The widget's own key is
    re-seeded from it on every run, and an on_change callback copies edits back before the
    rerun. (Passing the stored value as `value=` instead makes the widget's identity depend
    on that value, so returning to an earlier value revives that widget's stale state.)"""
    st.session_state.setdefault(store, default)
    wkey = f"{store}_box"
    st.session_state[wkey] = st.session_state[store]

    def _sync():
        st.session_state[store] = st.session_state[wkey].strip()

    st.sidebar.text_input(label, key=wkey, help=help, on_change=_sync)
    return st.session_state[store]


def _snapshot_note(base: Path):
    """Public mode: one quiet line saying which data the app is showing."""
    import json
    mf = base / "MANIFEST.json"
    built = ""
    if mf.exists():
        try:
            built = json.loads(mf.read_text(encoding="utf-8")).get("built", "")[:10]
        except (OSError, ValueError):
            pass
    st.sidebar.caption(f"Data: TEFA public files{f', snapshot of {built}' if built else ''}.")


def base_dir() -> Path:
    """Data folder. In public mode it is fixed (config / environment) and not editable:
    a hosted visitor must not be able to point the app at other paths on the server."""
    if C.public_mode():
        base = C.data_dir()
        _snapshot_note(base)
        return base
    path = _path_box("Data folder", "_data_dir", str(C.data_dir()),
                     "Folder holding the TEFA public files (defaults to the folder above this app).")
    if st.sidebar.button("Reload data"):
        st.cache_data.clear()
    return Path(path)


def shape_dir() -> Path:
    if C.public_mode():
        return C.shape_dir()
    return Path(_path_box("Shapefile folder", "_shape_dir", str(C.shape_dir()),
                          "Folder with Texas Legislative Council plan downloads (PLANH####.zip, PLANS####.zip)."))


@st.cache_data(show_spinner=False)
def _cached(ds_id: str, base: str):
    return D.load(ds_id, Path(base))


def get(ds_id: str, base: Path, quiet=False):
    df, err = _cached(ds_id, str(base))
    if err and not quiet:
        st.warning(f"**{D.BY_ID[ds_id].title}** unavailable — {err}")
    return df


@st.cache_data(show_spinner=False)
def breakdowns(base: str) -> pd.DataFrame:
    return D.breakdowns(Path(base))


def source(*ds_ids: str):
    parts = []
    for i in ds_ids:
        d = D.BY_ID[i]
        parts.append(f"{d.group}: {d.source}" + (f" — {d.notes}" if d.notes else ""))
    st.caption("Source: " + " · ".join(parts))


def chart(fig, df: pd.DataFrame | None = None, key: str | None = None, alt: str = ""):
    """Render a chart with an accessible text summary and an optional data table."""
    st.plotly_chart(fig, width="stretch", key=key)
    if alt:
        st.caption(alt)
    if df is not None:
        with st.expander("Show data"):
            st.dataframe(df, width="stretch", hide_index=True)
            st.download_button("Download CSV", df.to_csv(index=False).encode(), file_name=f"{key or 'data'}.csv",
                               key=f"dl_{key}")


def fmt_int(v) -> str:
    return "—" if pd.isna(v) else f"{v:,.0f}"
