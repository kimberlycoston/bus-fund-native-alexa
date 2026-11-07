"""Native Lisans prototype: the Lisans Band plus the Lisans Portal hospital web app.

Run:  streamlit run band_app.py

Two pages share one data store:
  • Lisans Band   – the clickable wearable (live interpretation through OpenAI Realtime)
  • Lisans Portal – hospital sign-in, live bilingual transcripts, history, band
                    assignment and Section 1557 compliance reporting
Open them in two browser tabs to show a conversation appearing in the Portal live.
"""
from __future__ import annotations

import streamlit as st

from native import band_view, portal_view

st.set_page_config(page_title="Native Lisans", page_icon=None, layout="wide")
st.markdown("<style>.block-container{padding:3.6rem 2rem 1rem;max-width:1600px}"
            "[data-testid=stAppDeployButton]{display:none}</style>", unsafe_allow_html=True)

pages = [
    st.Page(band_view.render, title="Lisans Band", default=True),
    st.Page(portal_view.render, title="Lisans Portal", url_path="portal"),
]
st.navigation(pages, position="top").run()
