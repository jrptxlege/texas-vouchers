"""Home page: headline numbers and the application funnel (Nov dashboard)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tefa import charts, config as C, ui

st.set_page_config(page_title="TEFA Data Explorer", layout="wide")
base = ui.base_dir()

st.title("TEFA public data explorer")
st.write("Texas Education Freedom Accounts — applications, participants, and spending "
         "from the July release, the Oct 1 data request, and the Nov 2026 public dashboard.")

k = ui.get("nov_kpis", base)
if k is None:
    st.stop()
if k.value.isna().all():
    st.error(f"No headline files found under {base}. Check the **Data folder** in the sidebar.")
    st.stop()
kv = dict(zip(k.kpi, k.value, strict=True))

st.subheader("Nov 2026 dashboard: headline numbers")
c = st.columns(4)
c[0].metric("Applications received", ui.fmt_int(kv.get("Applications received")))
c[1].metric("Eligible applicants", ui.fmt_int(kv.get("Eligible applicants")))
c[2].metric("Funded participants", ui.fmt_int(kv.get("Funded participants")))
c[3].metric("On waiting list", ui.fmt_int(kv.get("On waiting list")))
c = st.columns(4)
spend = kv.get("Total program expenditure ($)")
c[0].metric("Total expenditure", "—" if pd.isna(spend) else f"${spend / 1e6:,.1f}M")
c[1].metric("Participating schools", ui.fmt_int(kv.get("Participating schools")))
c[2].metric("Vendors with spending", ui.fmt_int(kv.get("Vendors (with spending)")))
share = kv.get("Share of participants with a disability")
c[3].metric("Participants with a disability", "—" if pd.isna(share) else f"{share:.1%}")

# Funnel: where eligible applicants ended up
stages = pd.DataFrame({
    "stage": ["Applications received", "Eligible applicants", "Funded participants", "On waiting list", "Opted out"],
    "value": [kv.get(s) for s in ["Applications received", "Eligible applicants", "Funded participants", "On waiting list", "Opted out"]],
})
fig = go.Figure(go.Bar(x=stages.value, y=stages.stage, orientation="h", marker_color=charts.PALETTE[0],
                       text=[ui.fmt_int(v) for v in stages.value], textposition="outside",
                       hovertemplate="%{y}: %{x:,.0f}<extra></extra>"))
fig.update_yaxes(autorange="reversed")
fig = charts._style(fig, height=300)
fig.update_xaxes(range=[0, (stages.value.max() or 1) * 1.12])  # room for end labels
fig.update_layout(title="Application funnel")
gap = stages.value.iloc[1] - stages.value.iloc[2:].sum()
ui.chart(fig, stages, key="funnel",
         alt=f"Funded + waiting list + opted out leaves {gap:,.0f} eligible applicants unaccounted for "
             "in the published tiles" + ("." if C.public_mode() else " (see Data & QA)."))
ui.source("nov_kpis")

st.info("Use the pages in the sidebar: **Participants** (who is funded), **Districts**, **Spending**, "
        "**Vendors**, **Special education funding**, **Legislative map**"
        + (", and **Data & QA** (file inventory and cross-file checks)." if not C.public_mode() else "."))
