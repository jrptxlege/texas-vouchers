"""Where TEFA money goes: school tuition vs. marketplace purchases."""
import streamlit as st

from tefa import charts, ui

st.set_page_config(page_title="Spending · TEFA", layout="wide")
base = ui.base_dir()
st.title("Spending (Nov 2026 dashboard)")

fa = ui.get("nov_funding_allocation", base)
if fa is not None:
    ui.chart(charts.share_bar(fa, "type", "amount", title="School funding vs. marketplace spend", money=True),
             fa, key="alloc", alt=", ".join(f"{r.type}: ${r.amount:,.0f}" for r in fa.itertuples()))
    ui.source("nov_funding_allocation")

tab_s, tab_m = st.tabs(["Schools (tuition)", "Marketplace (vendors)"])

with tab_s:
    sch = ui.get("nov_all_schools", base)
    if sch is not None:
        n = st.slider("Top schools", 10, 100, 25, key="ns")
        ui.chart(charts.hbar(sch, "school", "expenditure", money=True, n=n, title="Expenditure by school"),
                 sch.sort_values("expenditure", ascending=False), key="schools",
                 alt="Amounts in the full school list are rounded to $100.")
        conc = sch.expenditure.sort_values(ascending=False)
        top10 = conc.head(int(len(conc) * 0.1)).sum() / conc.sum()
        st.metric("Share of school funding going to the top 10% of schools", f"{top10:.0%}")
        q = st.text_input("Find a school")
        if q:
            st.dataframe(sch[sch.school.str.contains(q, case=False, na=False)], hide_index=True)
        ui.source("nov_all_schools")

with tab_m:
    cat = ui.get("nov_category", base)
    if cat is not None:
        ui.chart(charts.hbar(cat, "category", "expenditure", money=True, title="Marketplace spend by category"),
                 cat, key="cat")
    sub = ui.get("nov_subcategory", base)
    if sub is not None:
        ui.chart(charts.hbar(sub, "subcategory", "expenditure", money=True, n=20, title="Top 20 subcategories"),
                 sub, key="subcat")
    ven = ui.get("nov_all_vendors", base)
    if ven is not None:
        n = st.slider("Top vendors", 10, 100, 25, key="nv")
        ui.chart(charts.hbar(ven, "vendor", "expenditure", money=True, n=n, title="Expenditure by vendor (full list)"),
                 ven.sort_values("expenditure", ascending=False), key="vendors",
                 alt="The dashboard's Top-20 vendor export reports different amounts for its first 10 vendors "
                     "than this full list — see Data & QA.")
    dist = ui.get("nov_vendor_distribution", base)
    if dist is not None:
        ui.chart(charts.hbar(dist, "range", "vendors", title="Vendors by total expenditure range"), dist, key="vdist")
    ui.source("nov_category", "nov_subcategory", "nov_all_vendors", "nov_vendor_distribution")
