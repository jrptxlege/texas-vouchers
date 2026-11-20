"""Streamlit helpers shared by every page: data folder picker, cached loading,
source captions, and a 'show the table' toggle under each chart."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from . import config as C
from . import datasets as D


def base_dir() -> Path:
    if "data_dir" not in st.session_state:
        st.session_state.data_dir = str(C.data_dir())
    with st.sidebar:
        st.text_input("Data folder", key="data_dir",
                      help="Folder holding the TEFA public files (defaults to the folder above this app).")
        if st.button("Reload data"):
            st.cache_data.clear()
    return Path(st.session_state.data_dir)


def shape_dir() -> Path:
    if "shape_dir" not in st.session_state:
        st.session_state.shape_dir = str(C.shape_dir())
    with st.sidebar:
        st.text_input("Shapefile folder", key="shape_dir",
                      help="Folder with Texas Legislative Council plan downloads (PLANH####.zip, PLANS####.zip).")
    return Path(st.session_state.shape_dir)


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
