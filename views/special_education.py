"""TEFA special-education add-on by IEP instructional code and district (2026-27)."""
import plotly.express as px
import streamlit as st

from tefa import charts, datasets as D, ui

st.set_page_config(page_title="Special education · TEFA", layout="wide")
base = ui.base_dir()
st.title("Special education add-on, 2026–27")

params = D.sped_params(base) if ui.get("sped_by_code", base, quiet=True) is not None else {}
if params:
    st.write(f"Base account: **${params.get('Base amount', 0):,.0f}**; base + add-on capped at "
             f"**${params.get('Account cap', 0):,.0f}**.")

codes = ui.get("sped_by_code", base)
if codes is not None:
    c = codes.sort_values("Median district").copy()
    c["label"] = c["Code"] + " · " + c["PEIMS instructional setting"].str.slice(0, 45)
    fig = px.scatter(c, x="Median district", y="label", labels={"label": "", "Median district": ""},
                     title="Add-on by code: lowest, median, highest district",
                     hover_data={"Lowest district": ":$,.0f", "Highest district": ":$,.0f", "Median district": ":$,.0f"})
    fig.update_traces(marker=dict(size=9, color=charts.PALETTE[0]),
                      error_x=dict(type="data", symmetric=False, color=charts.MUTED, thickness=2, width=0,
                                   array=c["Highest district"] - c["Median district"],
                                   arrayminus=c["Median district"] - c["Lowest district"]))
    fig.update_xaxes(tickprefix="$", tickformat=",")
    ui.chart(charts._style(fig, height=26 * len(c) + 120), codes, key="codes",
             alt="Dot = median district's add-on; line spans lowest to highest district.")
    ui.source("sped_by_code")

dt = ui.get("sped_district_table", base)
if dt is not None:
    st.subheader("Compare districts")
    picks = st.multiselect("Districts (up to 3)", sorted(dt.district.unique()),
                           default=[d for d in ["HOUSTON ISD", "SAN ANTONIO ISD"] if d in set(dt.district)], max_selections=3)
    speech = st.toggle("Include speech therapy (+ code 00 amount)")
    sel = dt[dt.district.isin(picks) & (dt.speech == speech)].sort_values("code")
    if len(sel):
        fig = px.bar(sel, x="code", y="addon", color="district", barmode="group",
                     color_discrete_sequence=charts.PALETTE, labels={"code": "IEP instructional code", "addon": "", "district": ""})
        fig.update_xaxes(type="category")
        ui.chart(charts._style(fig, money=True), sel, key="sped_cmp")

with st.expander("Notes from the source workbook"):
    for n in D.sped_notes(base) if codes is not None else []:
        st.markdown(n)
