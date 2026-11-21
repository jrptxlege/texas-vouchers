"""The participating-vendor directory: who is approved, what they do, where they are."""
import pandas as pd
import plotly.express as px
import streamlit as st

from tefa import charts, ui

st.set_page_config(page_title="Vendors · TEFA", layout="wide")
base = ui.base_dir()
st.title("Participating vendor directory")

v = ui.get("vendor_directory_spend", base, quiet=True)  # directory + Nov marketplace spending
has_spend = v is not None
if v is None:
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

def _money(x: float) -> str:
    return f"${x / 1e6:,.1f}M" if x >= 1e6 else f"${x:,.0f}"


def _spend_text(r) -> str:
    if not r.has_spending:
        return "None recorded"
    return f"${r.expenditure:,.0f}" if pd.notna(r.expenditure) else r.expenditure_published.replace("-", "–")


m1, m2, m3 = st.columns(3)
m1.metric("Vendors matching filters", f"{len(f):,}", help=f"Directory entries matching the filters, of {len(v):,}.")
if has_spend:
    u = f.drop_duplicates("vendor_key")  # a vendor registered twice is counted once
    lo, hi = u.expenditure_low.sum(), u.expenditure_high.sum()
    m2.metric("With marketplace spending", f"{int(u.has_spending.sum()):,}",
              help=f"Of {len(u):,} distinct vendors (some are registered more than once).")
    rng = (_money(lo) if hi - lo < 0.005 * max(hi, 1)
           else f"${lo / 1e6:,.1f}–{hi / 1e6:,.1f}M" if lo >= 1e6 else f"{_money(lo)}–{_money(hi)}")
    m3.metric("Marketplace spending", rng,
              help="Sum over the filtered vendors. Amounts under $10,000 are published as $2,500 bands, "
                   "so the total is a range.")

if has_spend:
    top = (f.drop_duplicates("vendor_key").dropna(subset=["expenditure"])
           .query("expenditure > 0").sort_values("expenditure", ascending=False))
    if len(top):
        n = st.slider("Top vendors by spending", 10, 50, 20, step=5)
        top = top.head(n)
        ui.chart(charts.hbar(top, "vendor_name", "expenditure", money=True,
                             title="Marketplace spending by vendor (Nov dashboard)"),
                 top[["vendor_name", "type_of_business", "city", "state", "expenditure", "transactions"]],
                 key="vspend", alt=f"Top {len(top)} directory vendors matching the filters, by total marketplace spending.")

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

with st.expander("Browse vendors", expanded=has_spend):
    show = f.drop(columns=["phone", "email"])
    if has_spend:
        show = show.assign(spending=[_spend_text(r) for r in show.itertuples()],
                           transactions_shown=show.transactions_published.where(show.has_spending, ""))                    .sort_values(["expenditure_high", "vendor_name"], ascending=[False, True])
        cols = ["vendor_name", "spending", "transactions_shown", "type_of_business", "city", "state",
                "service_delivery_method", "created_at"]
        st.dataframe(show[cols], hide_index=True, width="stretch",
                     column_config={"vendor_name": "Vendor", "spending": "Marketplace spending",
                                    "transactions_shown": "Transactions", "type_of_business": "Type of business",
                                    "service_delivery_method": "Service delivery", "created_at": "Registered"})
        dl = show.drop(columns=["spending", "transactions_shown", "vendor_key", "has_spending"])
        st.download_button("Download CSV (with spending low/high columns)", dl.to_csv(index=False).encode(),
                           file_name="vendor_directory_spending.csv")
    else:
        st.dataframe(show, hide_index=True, width="stretch")

if has_spend:
    um = v.attrs.get("unmatched", [])
    note = ("Spending is each vendor's marketplace total from the Nov dashboard's full vendor list, matched to the "
            "directory by name. Amounts under $10,000 and transaction counts under 10 are published only as "
            "ranges. A vendor registered more than once shows its total on each row but is counted once. "
            "Vendors not in the spending list show \"None recorded\".")
    if len(um):
        note += (" Not in the directory, so not shown: "
                 + ", ".join(f"{r['vendor']} ({r['expenditure']})" for r in um) + ".")
    st.caption(note)
    ui.source("vendor_directory", "nov_all_vendors")
else:
    ui.source("vendor_directory")
