"""Choropleth of TEFA data by Texas House or Senate district, with toggleable layers."""
from pathlib import Path

import plotly.express as px
import streamlit as st

from tefa import charts, config as C, geo, layers, ui

st.set_page_config(page_title="Legislative map · TEFA", layout="wide")
base = ui.base_dir()
sdir = ui.shape_dir()
st.title("TEFA by legislative district")

plans = geo.find_plans(sdir)
if not plans:
    st.error(f"No Legislative Council plan shapefiles (PLANH####.zip / PLANS####.zip) found under {sdir}.")
    st.stop()

order = [c for c in ("H", "S", "C") if c in plans]
c1, c2, c3 = st.columns([1, 2, 1.4])
ch = c1.radio("Chamber", order, format_func=lambda c: geo.CHAMBERS[c], horizontal=False)
plan = plans[ch]
# Exact (published-by-district) layers exist for the Texas House and Senate only.
options = [l.id for l in layers.LAYERS if not l.exact or ch in ("H", "S")]
layer = layers.BY_ID[c2.selectbox("Data layer", options, format_func=lambda i: layers.BY_ID[i].label)]
measures = ["Total"] + (["Per 1,000 residents under 18"] if layer.per_child else [])
measure = c3.radio("Measure", measures)
col = "per_1000_u18" if measure != "Total" else "value"


@st.cache_data(show_spinner="Loading boundaries…")
def _geo(p: geo.Plan):
    return geo.boundaries_geojson(p)


@st.cache_data(show_spinner="Building layer…")
def _layer(layer_id, b, p: geo.Plan):
    return layers.build(layer_id, Path(b), p)


try:
    df, diag = _layer(layer.id, str(base), plan)
except Exception as e:  # noqa: BLE001
    st.error(f"Could not build **{layer.label}**: {e}")
    st.stop()

mem = layers.members(sdir, base, ch)
mem_source = mem.attrs.get("source", "") if mem is not None else ""
if mem is not None:
    df = df.merge(mem, on="district", how="left")
df["label"] = df.district.map(lambda d: f"{'HD' if ch == 'H' else 'SD' if ch == 'S' else 'CD'} {d}")
if "member" in df:
    df["label"] = df.label + df.member.map(lambda m: f" · {m}" if isinstance(m, str) else "")

fmt = ":$,.0f" if layer.kind == "money" else (":,.1f" if col == "per_1000_u18" else ":,.0f")
hover = {"district": False, "label": True, col: fmt, "pop_u18": ":,.0f"}
if col != "value":
    hover["value"] = ":,.0f"

t1, t2 = st.columns([1, 2])
focus = t1.selectbox("Focus", list(charts.FOCUS))
basemap = t2.toggle("Street basemap (needs internet and WebGL)", value=False,
                    help="Off: district shapes drawn without map tiles; works offline, behind firewalls, and in exported images.")
common = dict(geojson=_geo(plan), locations="district", color=col, color_continuous_scale=charts.SEQUENTIAL,
              hover_name="label", hover_data=hover,
              labels={col: measure, "value": "Total", "pop_u18": "Under-18 pop.", "member": "Member", "label": "District"})
if basemap:
    fig = px.choropleth_map(df, map_style="carto-positron", center={"lat": 31.2, "lon": -99.3},
                            zoom=4.6, opacity=0.8, **common)
    fig.update_traces(marker_line_width=0.5, marker_line_color="white")
    fig.update_layout(height=640, margin=dict(l=0, r=0, t=0, b=0),
                      coloraxis_colorbar=dict(title="", tickformat="$,.0f" if layer.kind == "money" else ",.0f"))
else:
    extra = {"value": "Total", "pop_u18": "Under-18 pop."}  # member is already in the label
    if col == "value":
        extra.pop("value")
    fig = charts.district_map(_geo(plan), df, col, hover_cols=extra, money=layer.kind == "money",
                              bounds=charts.FOCUS[focus], value_label=measure)
st.plotly_chart(fig, width="stretch", key="map")
src = "values as published by district" if layer.exact else f"crosswalk: {plan.crosswalk_source} (2020 Census)"
st.caption(f"{layer.label} — {measure.lower()}. Districts without a value are blank. {layer.note} "
           f"Boundaries: {plan.name}; {src}." + (f" Member names: {mem_source}." if mem_source else ""))

cov = diag.get("share_of_total_allocated")
m1, m2, m3 = st.columns(3)
m1.metric("Districts with a value", f"{df[col].notna().sum()} of {len(df)}")
if cov is not None:
    m2.metric("Share of source total placed on the map", f"{cov:.1%}")
if diag.get("unplaced"):
    m3.metric("Published with no district", f"${diag['unplaced']:,.0f}" if layer.kind == "money" else f"{diag['unplaced']:,.0f}")
elif diag.get("unmatched"):
    with m3.popover(f"{len(diag['unmatched'])} source names not placed"):
        st.write("Mostly non-geographic entities (county departments, university schools, charters)."
                 + ("" if C.public_mode() else " Spelling fixes go in tefa/districts.py."))
        st.dataframe({"name": diag["unmatched"]}, hide_index=True)

st.subheader("Ranked")
n = st.slider("Show top", 10, len(df), min(25, len(df)))
top = df.dropna(subset=[col]).sort_values(col, ascending=False).head(n)
ui.chart(charts.hbar(top, "label", col, money=layer.kind == "money"), top.drop(columns=["label"]), key="leg_rank")

st.subheader("What's inside a district")
pick = st.selectbox("District", sorted(df.district), format_func=lambda d: df.set_index("district").label[d])
pieces = geo.isd_pieces(plan, pick)
st.dataframe(pieces.rename(columns={"isd": "School district", "isd_pct": "% of ISD population in this district",
                                    "pop": "Population", "pop_u18": "Under 18", "w_u18": "Allocation weight"}),
             hide_index=True, width="stretch")
if layer.exact:
    st.caption("This layer uses numbers the Nov dashboard publishes for each legislative district, so it does not "
               "depend on the school-district split below. The table shows which school districts the district contains.")
else:
    st.caption("Values from school-district data are split across legislative districts by each piece's share of "
               "the ISD's under-18 population. This is an estimate; the source data does not place participants "
               "by address. Charter schools have no boundaries and are not allocated.")
