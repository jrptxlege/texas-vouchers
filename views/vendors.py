"""The participating-vendor directory: who is approved, what they do, where they are."""
import plotly.express as px
import streamlit as st

from tefa import charts, ui

st.set_page_config(page_title="Vendors · TEFA", layout="wide")
base = ui.base_dir()
st.title("Participating vendor directory")

v = ui.get("vendor_directory", base)
if v is None:
    st.stop()

c1, c2, c3 = st.columns(3)
types = c1.multiselect("Type of business", sorted(v.type_of_business.dropna().unique()))
methods = c2.multiselect("Service delivery", sorted(v.service_delivery_method.dropna().unique()))
in_tx = c3.selectbox("Location", ["All", "Texas only", "Out of state only"])
f = v.copy()
if types:
    f = f[f.type_of_business.isin(types)]
if methods:
    f = f[f.service_delivery_method.isin(methods)]
if in_tx != "All":
    f = f[(f.state == "TX") == (in_tx == "Texas only")]

st.metric("Vendors matching filters", f"{len(f):,} of {len(v):,}")

t = f.type_of_business.fillna("(blank)").value_counts().rename_axis("type").reset_index(name="vendors")
ui.chart(charts.hbar(t, "type", "vendors", title="Vendors by type of business"), t, key="vtype")

cities = f[f.state == "TX"].city.str.title().value_counts().head(20).rename_axis("city").reset_index(name="vendors")
ui.chart(charts.hbar(cities, "city", "vendors", title="Top 20 Texas cities by vendor count"), cities, key="vcity")

monthly = f.dropna(subset=["created_at"]).set_index("created_at").resample("MS").size().rename("vendors").reset_index()
monthly["cumulative"] = monthly.vendors.cumsum()
fig = px.line(monthly, x="created_at", y="cumulative", title="Vendors registered (cumulative, by created_at)")
fig.update_traces(line=dict(color=charts.PALETTE[0], width=2),
                  hovertemplate="%{x|%b %Y}: %{y:,.0f} vendors registered<extra></extra>")
charts.no_axis_titles(fig)
ui.chart(charts._style(fig, height=320), monthly, key="vtime")

with st.expander("Browse vendors"):
    st.dataframe(f.drop(columns=["phone", "email"]), hide_index=True, width="stretch")
ui.source("vendor_directory")
