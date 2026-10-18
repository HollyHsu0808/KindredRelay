"""Root entry point for Streamlit Community Cloud: runs the KindredRelay app shell.

Community Cloud takes one main file at the repository root; this is it. It starts the
same shell deploy/serve.py starts, handoff_day1/ui/pages/shell/kindred_app.py (family
timeline, Evaluation & Safety Scorecard, AMD Runtime), so Dockerfile.release and the
documented local run are unchanged.

Like deploy/serve.py, it refuses to show the site when a live model setting is missing,
naming the variables and never their values, so a site without a connected model is not
mistaken for the live version. Set CARERELAY_REQUIRE_LIVE=0 to run on recorded facts.

What this host does not provide, and the page handles without it:
  speech recognition  the root requirements.txt has no openai-whisper, torch or ffmpeg,
                      so the page asks the family to type what was said
                      (handoff_day1/agent/asr_local.py reports what is missing)
  persistent storage  without CARERELAY_STATE_DIR the timelines live in ~/.kindredrelay
                      (handoff_day1/ui/PERSISTENCE.md), which this host replaces on every
                      restart and redeploy, so private and family links do not survive one
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
SHELL = ROOT / "handoff_day1" / "ui" / "pages" / "shell" / "kindred_app.py"
LIVE = ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL", "CARERELAY_PHOTO_MODEL", "CARERELAY_LLM_API_KEY")


def missing(env: dict) -> list[str]:
    """Which live model settings this host has not set; empty when recorded facts are asked for."""
    if env.get("CARERELAY_REQUIRE_LIVE", "1") == "0":
        return []
    return [name for name in LIVE if not env.get(name, "").strip()]


absent = missing(os.environ)
if absent:
    st.error("Set these deployment variables in this host's secrets: " + ", ".join(absent))
elif not SHELL.is_file():
    st.error("App shell not found: " + str(SHELL))
else:
    runpy.run_path(str(SHELL), run_name="__main__")
