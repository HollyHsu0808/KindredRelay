"""AMD Runtime (a page of the KindredRelay app shell, kindred_app.py): the model calls this browser session made, with
model, endpoint host, latency, token usage and what the backend's checks did with each reply (runtime_trace.py), under
a session summary: calls to the AMD Token Factory endpoint versus other hosts, and each model's role (its calls' stages).
Read-only; the API key is never read or shown."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parents[2] / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import runtime_trace  # noqa: E402

st.set_page_config(page_title="KindredRelay · AMD Runtime", layout="wide")
runtime_trace.render_page(st, runtime_trace.session_recorder(st.session_state), st.session_state)
