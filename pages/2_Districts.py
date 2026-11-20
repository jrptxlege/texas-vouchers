"""District-level participation, joined to district enrollment."""
import plotly.express as px
import streamlit as st

from tefa import charts, districts, ui

st.set_page_config(page_title="Districts · TEFA", layout="wide")
base = ui.base_dir()
st.title("Participation by school district")
st.write("Counts are by the district a participant lives in or previously attended, as each release defines it. "
         "The Nov dashboard publishes only the top 30 ISDs; July lists districts with 30+ participants; "
         "the Oct 1 data request lists funded participants in districts with 30+ and, separately, "
         "participants who previously attended public school.")


@st.cache_data(show_spinner=False)
def load(b):
    from pathlib import Path
    return districts.combined(Path(b))


t, unmatched = load(str(base))
if t.empty:
    st.error("No district tables could be loaded.")
    st.stop()

labels = {"funded": "Funded participants", "prior_public": "Prior-year public school participants"}
opts = [(r, m) for r, m in t[["release", "metric"]].drop_duplicates().itertuples(index=False)]
pick = st.selectbox("Series", opts, format_func=lambda x: f"{x[0]} — {labels.get(x[1], x[1])}")
measure = st.radio("Measure", ["Count", "Per 1,000 enrolled students"], horizontal=True)
n = st.slider("Show top", 10, 100, 30, step=5)

d = t[(t.release == pick[0]) & (t.metric == pick[1])].copy()
col = "value" if measure == "Count" else "per_1000_students"
d = d.dropna(subset=[col])
if measure != "Count":
    min_enr = st.number_input("Minimum enrollment (rates for tiny districts are volatile)", 0, 50000, 1000, step=500)
    d = d[d.student_count >= min_enr]

show = d.sort_values(col, ascending=False).head(n)
fig = charts.hbar(show, "district", col, title=f"{labels.get(pick[1])} — {pick[0]}")
ui.chart(fig, show[["district", "county", "region", "district_type", "value", "student_count", "per_1000_students"]],
         key="district_bar", alt=f"Top {n} districts by {measure.lower()}.")

flag = d[d.per_1000_students > 200]
if len(flag):
    st.warning(f"{len(flag)} district(s) show more than 200 participants per 1,000 enrolled students — "
               "likely an attribution or name-matching issue worth checking: "
               + ", ".join(f"{r.district} ({r.value:,.0f} vs {r.student_count:,.0f} enrolled)" for r in flag.itertuples()))

st.subheader("By education service center region")
reg = d.groupby("region", as_index=False).agg(value=("value", "sum"), students=("student_count", "sum"))
reg["per_1000_students"] = reg.value / reg.students * 1000
fig = px.bar(reg.sort_values("region"), x="region", y="value" if measure == "Count" else "per_1000_students",
             labels={"region": "ESC region", "value": "", "per_1000_students": ""})
fig.update_traces(marker_color=charts.PALETTE[0])
fig.update_xaxes(type="category")
ui.chart(charts._style(fig, height=340), reg, key="region",
         alt="Totals for listed districts only; unlisted (suppressed or non-top-30) districts are not included.")

ui.source("july_district", "oct1_district", "nov_isd", "oct_district_prior_public", "district_roster")
if len(unmatched):
    with st.expander(f"{len(unmatched)} district names not matched to the roster"):
        st.dataframe(unmatched, hide_index=True)
        st.caption("Add spellings to ALIASES or CITY_COUNTY in tefa/districts.py.")
