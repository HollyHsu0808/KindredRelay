"""KindredRelay app shell (the Streamlit entry point deploy/serve.py starts). The family timeline
(../1_Family_timeline.py) is the default page, run as it is; beside it, two read-only pages:
  Evaluation & Safety Scorecard  (scorecard.py)   the results in this repository, each number with its source
  AMD Runtime                    (amd_runtime.py) this browser session's model calls: model, endpoint host, latency,
                                                  token usage, and what the backend's checks did with each reply
While a page runs, llm_client's opt-in call recorder for this session is active (runtime_trace.py), so the model
clients the family timeline creates report their calls to it; a compact AMD Runtime panel sits in the sidebar. The
files live under ui/pages/ because Dockerfile.release copies only that folder of ui/. No credentials are read or shown.

Run:  streamlit run handoff_day1/ui/pages/shell/kindred_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent                    # handoff_day1/ui/pages/shell
FAMILY_PAGE = HERE.parent / "1_Family_timeline.py"
for _p in (HERE, HERE.parents[2] / "agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import runtime_trace  # noqa: E402

family = st.Page(FAMILY_PAGE, title="Family timeline", icon="👪", default=True)
scorecard = st.Page(HERE / "scorecard.py", title="Evaluation & Safety Scorecard", icon="📊")
runtime = st.Page(HERE / "amd_runtime.py", title="AMD Runtime", icon="⚙️")
page = st.navigation([family, scorecard, runtime])
on_family = page.url_path == family.url_path
runtime_trace.restore_family_params(st, on_family)
recorder = runtime_trace.session_recorder(st.session_state)
panel = st.sidebar.container() if page.url_path != runtime.url_path else None   # filled after the page has run
token = runtime_trace.activate(recorder)
try:
    page.run()
finally:
    runtime_trace.deactivate(token)
runtime_trace.remember_page(st, on_family)
if panel is not None:
    with panel:
        runtime_trace.sidebar_panel(st, recorder, runtime)
