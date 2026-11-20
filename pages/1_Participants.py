"""Who applies and who is funded, by any published breakdown, across releases."""
import pandas as pd
import streamlit as st

from tefa import charts, datasets as D, ui

st.set_page_config(page_title="Participants · TEFA", layout="wide")
base = ui.base_dir()
st.title("Applicants and participants")

b = ui.breakdowns(str(base))
if b.empty:
    st.error("No breakdown tables could be loaded from the data folder.")
    st.stop()

dims = list(dict.fromkeys(b.dimension))
dim = st.selectbox("Breakdown", dims, index=dims.index("Priority tier") if "Priority tier" in dims else 0)
d = b[b.dimension == dim]
releases = [r for r in D.C.RELEASE_ORDER if r in set(d.release)]
st.caption("Published in: " + ", ".join(releases))

# Keep category order as published (grade, age, tier orders matter).
order = list(dict.fromkeys(d.category))
if dim == "Grade":
    order = [g for g in D.GRADE_ORDER if g in order]

# 1) Each release: eligible vs funded side by side
for rel in releases:
    dr = d[d.release == rel].copy()
    dr["category"] = pd.Categorical(dr.category, categories=order, ordered=True)
    dr = dr.sort_values("category")
    is_pct = set(dr.metric) == {"share_funded"}
    fig = charts.compare_bars(dr, color="metric", title=f"{dim} — {rel}", pct=is_pct)
    ui.chart(fig, dr[["category", "metric", "value"]], key=f"bd_{dim}_{rel}",
             alt=f"{dim} breakdown, {rel}. Blank bars mean the source suppressed the value.")

    p = D.funding_rate(dr)
    if "funded_rate" in p and p.funded_rate.notna().any():
        ui.chart(charts.rate_bars(p, title=f"Share of eligible applicants funded — {rel}"),
                 p, key=f"rate_{dim}_{rel}",
                 alt="Funded participants divided by eligible applicants, per category.")

# 2) Across releases: funded counts where the same categories appear in >1 release
f = d[d.metric == "funded"]
shared = f.groupby("category").release.nunique()
shared = shared[shared > 1].index.tolist()
if len(f.release.unique()) > 1 and shared:
    st.subheader("Funded participants across releases")
    fx = f[f.category.isin(shared)].copy()
    fx["category"] = pd.Categorical(fx.category, categories=[c for c in order if c in shared], ordered=True)
    fx = fx.sort_values("category")
    ui.chart(charts.compare_bars(fx, color="release", title=f"Funded by {dim.lower()}"),
             fx[["release", "category", "value"]], key=f"xrel_{dim}",
             alt="Same categories compared across releases. Releases are cumulative snapshots, not separate cohorts.")
elif len(f.release.unique()) > 1:
    st.info("This breakdown appears in more than one release, but the categories differ "
            "(e.g. single-year ages vs. age bands), so they are not overlaid.")

ui.source(*sorted(set(d.dataset)))
