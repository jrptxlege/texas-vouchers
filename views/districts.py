"""District-level participation, joined to district enrollment."""
import streamlit as st

from tefa import charts, config as C, datasets as D, districts, ui

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

esc = ui.get("esc_regions", base, quiet=True)  # region labels; falls back to "Region N" if missing
t["esc_region"] = t.region.map(lambda r: D.region_label(r, esc))

labels = {"funded": "Funded participants", "prior_public": "Prior-year public school participants"}
# Plain-text options (label -> (release, metric)) so the selection survives reruns cleanly.
series = {f"{r} — {labels.get(m, m)}": (r, m)
          for r, m in t[["release", "metric"]].drop_duplicates().itertuples(index=False)}
pick = series[st.selectbox("Series", list(series))]
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
ui.chart(fig, show[["district", "county", "esc_region", "district_type", "value", "student_count", "per_1000_students"]],
         key="district_bar", alt=f"Top {n} districts by {measure.lower()}.")

flag = d[d.per_1000_students > 200]
if len(flag):
    why = ("which likely reflects how the source assigns participants to districts"
           if C.public_mode() else "likely an attribution or name-matching issue worth checking")
    st.warning(f"{len(flag)} district(s) show more than 200 participants per 1,000 enrolled students — "
               f"{why}: "
               + ", ".join(f"{r.district} ({r.value:,.0f} vs {r.student_count:,.0f} enrolled)" for r in flag.itertuples()))

st.subheader("By education service center region")
reg = d.dropna(subset=["region"]).groupby("region", as_index=False).agg(
    value=("value", "sum"), students=("student_count", "sum"))
reg["region"] = reg.region.astype(int)
reg["per_1000_students"] = reg.value / reg.students * 1000
reg["esc_region"] = reg.region.map(lambda r: D.region_label(r, esc))
if esc is not None:
    reg = reg.merge(esc[["region", "hq_city", "website"]], on="region", how="left")
ycol = "value" if measure == "Count" else "per_1000_students"
fig = charts.hbar(reg, "esc_region", ycol)
fig.update_traces(hovertemplate="%{y}: %{x:,.0f}" + (" per 1,000 enrolled" if ycol != "value" else "") + "<extra></extra>")
ui.chart(fig, reg[[c for c in ["region", "esc_region", "hq_city", "website", "value", "students", "per_1000_students"]
                   if c in reg]].sort_values(ycol, ascending=False),
         key="region",
         alt="Regions ranked; each is labelled with its education service center's headquarters city. "
             "Totals for listed districts only; unlisted (suppressed or non-top-30) districts are not included.")
if esc is not None:
    st.caption(f"Region names: {esc.attrs.get('source', 'ESC regions file')} (ESC headquarters city). "
               "District-to-region assignments come from the district roster.")

ui.source("july_district", "oct1_district", "nov_isd", "oct_district_prior_public", "district_roster")
if len(unmatched) and not C.public_mode():  # internal name-matching QA (staff only)
    with st.expander(f"{len(unmatched)} district names not matched to the roster"):
        st.dataframe(unmatched, hide_index=True)
        st.caption("Add spellings to ALIASES or CITY_COUNTY in tefa/districts.py.")
