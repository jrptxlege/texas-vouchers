"""Inventory of every dataset the app knows about, plus cross-file consistency checks."""
import pandas as pd
import streamlit as st

from tefa import checks, datasets as D, ui
from tefa.readers import find_file, norm_name

st.set_page_config(page_title="Data & QA · TEFA", layout="wide")
base = ui.base_dir()
st.title("Data inventory and quality checks")

rows = []
for d in D.DATASETS:
    df, err = D.load(d.id, base)
    rows.append({"group": d.group, "dataset": d.title, "id": d.id, "status": "loaded" if err is None else "error",
                 "rows": getattr(df, "shape", (None,))[0], "source": d.source, "notes": d.notes, "error": err or ""})
inv = pd.DataFrame(rows)
st.dataframe(inv, hide_index=True, width="stretch")

# Files in the folder that no loader reads (new releases land here first)
known = {norm_name(rel.split("/")[-1]) for rel in D.NOV_KPI_FILES.values()}
for d in D.DATASETS:
    for part in str(d.source).split(" / "):
        known.add(norm_name(part.split("/")[-1]))
files = [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in {".xlsx", ".csv", ".pdf"}
         and "tefa_viz" not in p.parts]
unread = [str(p.relative_to(base)) for p in files if norm_name(p.name) not in known]
with st.expander(f"{len(unread)} file(s) in the folder not read by any loader"):
    st.write("PDFs are source documents; new spreadsheets here likely need a loader in tefa/datasets.py.")
    st.dataframe(pd.DataFrame({"file": sorted(unread)}), hide_index=True)

st.subheader("Cross-file checks")
c = checks.run_checks(base)
only_bad = st.toggle("Show only differences", value=True)
show = c[c.status == "differs"] if only_bad else c
st.dataframe(show.style.format({"value": "{:,.2f}", "compared_with": "{:,.2f}", "difference": "{:,.2f}",
                                "pct_difference": "{:.2%}"}), hide_index=True, width="stretch")
st.caption("Tolerance 0.1%. Top-list vs full-list differences under $100 are treated as rounding.")

ds = st.selectbox("Preview a dataset", inv.id)
df, err = D.load(ds, base)
st.dataframe(df if err is None else pd.DataFrame({"error": [err]}), width="stretch")
