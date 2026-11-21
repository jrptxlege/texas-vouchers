"""TEFA public data explorer — entry point and page router.

Run:  streamlit run Home.py

Pages live in views/. They are registered here with st.navigation, so a page that
isn't registered has no menu entry and no URL. In public (hosted) mode the Data & QA
page is not registered; see tefa.config.public_mode().
"""
import streamlit as st

from tefa import config as C

st.set_page_config(page_title="TEFA Data Explorer", layout="wide")

pages = [
    st.Page("views/home.py", title="Home", default=True),
    st.Page("views/participants.py", title="Participants", url_path="Participants"),
    st.Page("views/districts.py", title="Districts", url_path="Districts"),
    st.Page("views/spending.py", title="Spending", url_path="Spending"),
    st.Page("views/vendors.py", title="Vendors", url_path="Vendors"),
    st.Page("views/special_education.py", title="Special Education Funding", url_path="Special_Education_Funding"),
    st.Page("views/legislative_map.py", title="Legislative Map", url_path="Legislative_Map"),
]
if not C.public_mode():
    # Internal: file inventory and cross-file reconciliation (staff only).
    pages.insert(6, st.Page("views/data_qa.py", title="Data and QA", url_path="Data_and_QA"))

st.navigation(pages).run()
