"""KindredRelay family timeline (Streamlit page): the episode builds itself from the family's recordings, photos and notes;
every family member sees the current picture and what is new since they last looked, in their own time zone. Adding is
two big buttons: a medication list or note (photograph a paper, or write a few words) and a recording.

Runs in-process on agent/episode.py (no server needed); the HTML comes from agent/timeline_html.py. Facts come from the
recorded demo extraction (replay) or, when an OpenAI-compatible model is configured (CARERELAY_LLM_BASE_URL,
CARERELAY_LLM_MODEL, CARERELAY_LLM_API_KEY, e.g. AMD Token Factory), from the live model for updates added here. A photo of
a paper is read by the same endpoint's vision model (e.g. Gemma-4-31B-IT); a recording is written out by Whisper where it
is installed (model/requirements-asr.txt; not in the Docker image, where the words are typed). Either way the person
checks every line with a number or a stop / continue before it is added, then facts are read from the checked text.
Fictional data only.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import html
import importlib
import io
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from contextlib import contextmanager, nullcontext
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

import streamlit as st

WORKING_HINT = None   # Root placeholder; callbacks retain the previous render's slot.

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "ui"))

from timeline_storage import StoreError, StoreMissing, TimelineSession, TimelineStore  # noqa: E402


@st.cache_resource(show_spinner=False)
def project_module_lock():
    """One process-wide lock for dependency-ordered project module refreshes."""
    return threading.RLock()


def refresh_project_modules() -> None:
    """A normal page rerun adopts changed project code while retaining session objects.

    Streamlit can keep imported modules from the earlier page revision. A source
    fingerprint refreshes them once, in dependency order; unchanged reruns retain
    the same classes/functions. Existing episodes are upgraded by get_episode.
    """
    with project_module_lock():
        dependency_changed = False
        for name in ("episode_events", "evidence_gate", "episode", "episode_qa", "timeline_html"):
            source = ROOT / "agent" / f"{name}.py"
            fingerprint = hashlib.sha256(source.read_bytes()).hexdigest()
            module = sys.modules.get(name)
            if module is None:
                module = importlib.import_module(name)
                dependency_changed = True
            else:
                loaded_path = Path(module.__file__).resolve()
                if loaded_path != source.resolve():
                    raise ImportError(f"The cached {name} module is outside this project")
                if dependency_changed or getattr(module, "_kindred_page_source_sha256", None) != fingerprint:
                    module = importlib.reload(module)
                    dependency_changed = True
            module._kindred_page_source_sha256 = fingerprint


refresh_project_modules()

from asr_whisper import check_reasons as asr_check_reasons  # noqa: E402
from episode import Episode, llm_extractor, load_scenario, norm, photo_reader, upgrade_episode  # noqa: E402
from episode_qa import refresh  # noqa: E402
from evidence_gate import checker_from_env, render_audit_panel  # noqa: E402
from timeline_html import (ABOUT, CSS, PRODUCT, TAGLINE, answer_html, display_headline, first_name, header_html, hello_html, hero_html,  # noqa: E402
                           left_hospital, presentation_model, question_html, side_html, source_archive_html, timeline_html)

SCENARIO = Path(os.environ.get("CARERELAY_STORY") or ROOT / "care_cases" / "episode_hip_fracture.json")   # the demo story
SAMPLE_PHOTO = ROOT / "care_cases" / "photos" / "discharge_medication_list.jpg"
READING_STATE = ("photo_reading", "photo_text", "photo_of_text")
PHOTO_STATE = ("photo", *READING_STATE, "photo_upload_seen", "photo_camera_seen")
ICON = {"recording": "🎙️", "photo": "📷", "note": "✍️"}
KIND_LABEL = {"recording": "Recording", "photo": "Photo", "note": "Note"}
LOOKS = {   # the page's look: pastel (soft white, pastel tiles, butter buttons) by default; honey and oat to compare
    "pastel": "--cr-ground:#F5F5F1;--cr-surface:#FFFFFF;--cr-surface-hi:#FFFFFF;--cr-panel:#FFFFFF;--cr-well:#F1F1EC;"
              "--cr-shadow:rgba(45,45,30,.09);--cr-light:rgba(255,255,255,0);--cr-accent-a:#F8DF94;--cr-accent-b:#F2CF6C;"
              "--cr-on-accent:#43330A;--cr-accent-soft:#FFF4D2;--cr-accent-ink:#7A5A10;--cr-chip:#FFF7DE;--cr-ink:#2A2B2E;"
              "--cr-muted:#62656D;--cr-blur:none",
    "honey": "--cr-ground:#F7F3EC;--cr-surface:#FBF8F3;--cr-surface-hi:#FFFFFF;--cr-panel:#FCFAF6;--cr-well:#F3EDE3;"
             "--cr-shadow:rgba(171,150,118,.30);--cr-light:rgba(255,255,255,.95);--cr-accent-a:#F9CF6A;--cr-accent-b:#F2A93E;"
             "--cr-on-accent:#4A2F00;--cr-accent-soft:#FFF3D6;--cr-accent-ink:#9A5B00;--cr-chip:#FFF8E8;--cr-ink:#2B2A26;"
             "--cr-muted:#766E60;--cr-blur:none",
    "oat": "--cr-ground:#E7E1D7;--cr-surface:rgba(255,255,255,.40);--cr-surface-hi:rgba(255,255,255,.66);--cr-panel:rgba(255,255,255,.42);"
           "--cr-well:rgba(255,255,255,.45);--cr-shadow:rgba(118,98,76,.22);--cr-light:rgba(255,255,255,.70);--cr-accent-a:#FFFFFF;"
           "--cr-accent-b:#EFE9E0;--cr-on-accent:#3A332B;--cr-accent-soft:rgba(255,255,255,.55);--cr-accent-ink:#5E5345;"
           "--cr-chip:rgba(255,255,255,.55);--cr-ink:#2F2B26;--cr-muted:#6F665A;--cr-blur:blur(14px) saturate(1.2)",
    "sunlit": "--cr-ground:#EFE3D3;--cr-surface:rgba(255,251,245,.50);--cr-surface-hi:rgba(255,252,248,.66);--cr-panel:rgba(255,250,244,.48);"
              "--cr-well:rgba(255,255,255,.55);--cr-shadow:rgba(110,72,40,.20);--cr-light:rgba(255,255,255,.70);--cr-accent-a:#F3D3B2;"
              "--cr-accent-b:#E8B68C;--cr-on-accent:#3A2312;--cr-accent-soft:rgba(246,214,184,.60);--cr-accent-ink:#7C3F17;"
              "--cr-chip:rgba(255,255,255,.55);--cr-ink:#2E241C;--cr-muted:#574334;--cr-blur:blur(18px) saturate(1.25);"
              "--cr-key:#4A3A2E;--cr-note-dot:#AE9884;--cr-now:#8E4518;"   # key events: charcoal brown, like the main button
              "--cr-p0:#2E6A60;--cr-p1:#94401C;--cr-p2:#7B3F63;--cr-p3:#85560C;--cr-p4:#3D5A75;--cr-p5:#9A4152;--cr-p6:#47622E",
    # the family's colours in earth tones (pine, rust, plum, ochre, slate, rosewood, moss): each >= 4.5:1 as text on the
    # warm glass and with white initials
    "frostsky": "--cr-ground:#F5E9DA;--cr-surface:rgba(255,251,246,.62);--cr-surface-hi:rgba(255,252,248,.76);--cr-panel:rgba(255,250,244,.60);"
                "--cr-well:rgba(255,255,255,.66);--cr-shadow:rgba(120,78,46,.20);--cr-light:rgba(255,255,255,.75);--cr-accent-a:#F3D3B6;"
                "--cr-accent-b:#E7B28C;--cr-on-accent:#3A2312;--cr-accent-soft:rgba(246,218,194,.62);--cr-accent-ink:#7A3F1E;"
                "--cr-chip:rgba(255,255,255,.62);--cr-ink:#2E241C;--cr-muted:#584434;--cr-blur:blur(12px) saturate(1.2);"
                "--cr-key:#865A44;--cr-note-dot:#A88E7A;--cr-now:#FFEFDF;"   # key events in the deep apricot of the buttons
                "--cr-p0:#2F6A62;--cr-p1:#8E4A2A;--cr-p2:#4E6178;--cr-p3:#7E5A1E;--cr-p4:#625A86;--cr-p5:#8A4C64;--cr-p6:#4E6634",
    # frostsky: soft frost, apricot with a touch of misty blue (Mia, the viewer in the demo, is the misty blue); the family
    # colours: pine, cinnamon, misty blue, ochre, misty violet, rose, moss, each >= 4.5:1 on the glass and with white initials
}
PAGE_CSS = """
[data-testid='stMainBlockContainer']{max-width:1240px;padding-top:2.5rem}
.stApp,header[data-testid='stHeader']{background:var(--cr-ground)}
[data-testid^='stBaseButton-primary']{background:linear-gradient(145deg,var(--cr-accent-a),var(--cr-accent-b));border:none;
 color:var(--cr-on-accent);border-radius:999px;font-weight:700;box-shadow:0 6px 16px var(--cr-shadow)}
[data-testid^='stBaseButton-primary']:hover{filter:brightness(1.04);color:var(--cr-on-accent);border:none}
[data-testid^='stBaseButton-primary']:active{box-shadow:inset 3px 3px 8px var(--cr-shadow)}
.st-key-add_paper button,.st-key-add_recording button,.st-key-add_ask button{width:100%;min-height:150px;border:none;
 border-radius:24px;padding:16px 18px;text-align:left;box-shadow:0 1px 2px rgba(0,0,0,.04);transition:transform .12s,filter .12s}
.st-key-add_ask button,.st-key-add_ask button:hover,.st-key-add_ask button:active,.st-key-add_ask button:focus{background-color:#E4E7F7;color:#2F3B78}
.st-key-add_recording button,.st-key-add_recording button:hover,.st-key-add_recording button:active,.st-key-add_recording button:focus{
 background-color:#F9E0D6;color:#843820}
.st-key-add_paper button,.st-key-add_paper button:hover,.st-key-add_paper button:active,.st-key-add_paper button:focus{background-color:#E4EDC0;color:#3F5A17}
.st-key-add_ask button{min-height:316px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 160 120'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='0' y2='1'%3E%3Cstop offset='0' stop-color='%23A7B2F2'/%3E%3Cstop offset='1' stop-color='%23F4BBC9'/%3E%3C/linearGradient%3E%3C/defs%3E%3Cg fill='url(%23g)' opacity='.9'%3E%3Crect x='6' y='36' width='26' height='48' rx='13'/%3E%3Crect x='46' y='8' width='26' height='104' rx='13'/%3E%3Crect x='86' y='22' width='26' height='76' rx='13'/%3E%3Crect x='126' y='34' width='26' height='52' rx='13'/%3E%3C/g%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 40px center;
 background-size:150px auto}
.st-key-add_paper button:hover,.st-key-add_recording button:hover,.st-key-add_ask button:hover{filter:brightness(.97);transform:translateY(-2px);border:none}
.st-key-add_paper button:active,.st-key-add_recording button:active,.st-key-add_ask button:active{transform:scale(.985)}
.st-key-add_paper button:focus-visible,.st-key-add_recording button:focus-visible,.st-key-add_ask button:focus-visible{
 outline:3px solid currentColor;outline-offset:3px}
.st-key-add_paper button>div,.st-key-add_recording button>div,.st-key-add_ask button>div{width:100%;align-self:stretch;justify-content:flex-start}
.st-key-add_paper span[data-has-shortcut],.st-key-add_recording span[data-has-shortcut],.st-key-add_ask span[data-has-shortcut]{
 display:flex;flex-direction:column;justify-content:space-between;align-items:flex-start;width:100%;min-height:118px;gap:14px}
.st-key-add_ask span[data-has-shortcut]{min-height:284px}
.st-key-add_paper span:has(>[data-testid='stIconMaterial']),.st-key-add_recording span:has(>[data-testid='stIconMaterial']),
.st-key-add_ask span:has(>[data-testid='stIconMaterial']){width:auto;height:auto;margin:0;display:flex}
.st-key-add_paper [data-testid='stIconMaterial'],.st-key-add_recording [data-testid='stIconMaterial'],.st-key-add_ask [data-testid='stIconMaterial']{
 font-size:calc(26px*var(--cr-fs,1));width:48px;height:48px;border-radius:15px;background:#FFFFFF;display:flex;align-items:center;justify-content:center;
 color:currentColor;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.st-key-add_paper [data-testid='stMarkdownContainer'],.st-key-add_recording [data-testid='stMarkdownContainer'],
.st-key-add_ask [data-testid='stMarkdownContainer']{text-align:left;color:currentColor;white-space:normal;overflow:visible;text-overflow:clip}
.st-key-add_paper button p,.st-key-add_recording button p,.st-key-add_ask button p{display:block;white-space:normal;margin:0;color:currentColor;
 font-size:calc(15px*var(--cr-fs,1));line-height:1.35}
.st-key-add_paper button p:first-child,.st-key-add_recording button p:first-child,.st-key-add_ask button p:first-child{
 font-size:calc(21px*var(--cr-fs,1));font-weight:700;line-height:1.2;margin-bottom:4px}
.st-key-add_ask{flex:1 1 auto}
.st-key-add_ask [data-testid='stButton'],.st-key-add_ask [data-testid='stButton']>div,.st-key-add_ask button{height:100%}
.st-key-add_ask button{align-items:stretch}
.st-key-add_ask button>div,.st-key-add_ask span[data-has-shortcut]{height:100%}
@media (max-width:640px){[data-testid='stHorizontalBlock']:has(.st-key-add_ask){flex-wrap:nowrap;gap:12px}
 [data-testid='stHorizontalBlock']:has(.st-key-add_ask)>[data-testid='stColumn']{min-width:0;flex:1 1 0}
 .st-key-add_ask button{background-size:84px auto;background-position:center 46%}
 .st-key-add_paper button p:first-child,.st-key-add_recording button p:first-child,.st-key-add_ask button p:first-child{
 font-size:calc(19px*var(--cr-fs,1))}
 .st-key-add_paper button p,.st-key-add_recording button p,.st-key-add_ask button p{font-size:calc(14px*var(--cr-fs,1));overflow-wrap:anywhere}}
[data-testid='stSidebar']{background:var(--cr-surface);color:var(--cr-ink,#2E241C)} [data-testid='stSidebarNav'] a *,[data-testid='stSidebar'] label p,[data-testid='stSelectbox'] label p,[data-testid='stSelectbox'] [role='group'] div,[data-baseweb='popover'] li,[data-baseweb='menu'] li{color:var(--cr-ink,#2E241C)}
.stApp .st-key-about_kindredrelay [data-testid='stMarkdownContainer'] p,
.stApp .st-key-about_kindredrelay [data-testid='stMarkdownContainer'] strong{color:var(--cr-ink,#2E241C)}
.stApp .st-key-about_kindredrelay [data-testid='stCaptionContainer'] p{color:var(--cr-muted,#584434)}
[data-testid='stCaptionContainer']{opacity:1;color:var(--cr-muted)}
[data-testid='stHorizontalBlock']:has(.st-key-mark_read){flex-wrap:wrap;row-gap:.75rem}
[data-testid='stHorizontalBlock']:has(.st-key-mark_read)>[data-testid='stColumn']{flex:1 1 12rem;min-width:min(100%,12rem)}
[data-testid='stHorizontalBlock']:has(.cr-rail){flex-wrap:wrap}
[data-testid='stHorizontalBlock']:has(.cr-rail)>[data-testid='stColumn']{min-width:min(100%,12rem)}
[data-testid='InputInstructions']{color:var(--cr-muted)}
[data-testid='stCaptionContainer'] p{color:inherit}
.st-key-text_size button{font-weight:700;color:var(--cr-ink);background:var(--cr-surface-hi);border-color:var(--cr-well)}
.st-key-text_size button[aria-checked='true'],.st-key-text_size button[aria-checked='true']:hover{background:var(--cr-accent-soft) !important;
 border-color:var(--cr-accent-b) !important;color:var(--cr-accent-ink) !important}
.st-key-text_size button[aria-checked='true'] p{color:var(--cr-accent-ink) !important}
.st-key-text_size button:hover{color:var(--cr-ink);border-color:var(--cr-accent-b)}
.st-key-text_size button:nth-child(2) p{font-size:calc(17px*var(--cr-fs,1))}
.st-key-text_size button:nth-child(3) p{font-size:calc(20px*var(--cr-fs,1))}
[data-testid='stSelectbox'] [role='group']{border-radius:14px;background:var(--cr-surface-hi);border-color:transparent;
 box-shadow:0 1px 3px var(--cr-shadow)}
[data-testid='stSelectbox'] [role='group']:focus-within{border-color:var(--cr-accent-b)}
.stApp .st-key-rec_speaker_type [data-baseweb='radio'] [data-testid='stMarkdownContainer'] p,
.stApp .st-key-hosp_how [data-baseweb='radio'] [data-testid='stMarkdownContainer'] p,
.stApp [class*='st-key-correction_'][class*='_speaker_type'] [data-baseweb='radio'] [data-testid='stMarkdownContainer'] p{
 color:var(--cr-ink,#2E241C)}
.stApp .st-key-rec_family_member [data-baseweb='select']>div,
.stApp [class*='st-key-correction_'][class*='_family_member'] [data-baseweb='select']>div{background:var(--cr-well,#FFF4E8)}
.stApp .st-key-rec_family_member [data-baseweb='select'] div,
.stApp [class*='st-key-correction_'][class*='_family_member'] [data-baseweb='select'] div{color:var(--cr-ink,#2E241C)}
.st-key-add_panel{background:var(--cr-panel);border:none !important;border-radius:32px;padding:22px 24px;backdrop-filter:var(--cr-blur);
 box-shadow:12px 12px 30px var(--cr-shadow),-10px -10px 26px var(--cr-light)}
.st-key-add_panel [data-testid='stTextInputRootElement'],.st-key-add_panel [data-testid='stTextAreaRootElement'],
.st-key-add_panel [data-baseweb='input'],.st-key-add_panel [data-baseweb='textarea'],.st-key-add_panel [data-baseweb='base-input'],
.st-key-add_panel [data-baseweb='select']>div{background:var(--cr-well);border-color:transparent;border-radius:18px;
 box-shadow:inset 4px 4px 10px var(--cr-shadow),inset -4px -4px 10px var(--cr-light)}
.st-key-add_panel input,.st-key-add_panel textarea{background:transparent;color:var(--cr-ink)}
.st-key-add_panel [data-testid='stFileUploaderDropzone'],.st-key-add_panel [data-testid='stAudioInput']>div{background:var(--cr-well);
 border-radius:20px;border:none}
.st-key-add_panel [data-testid='stAudioInput'],.st-key-add_panel [data-testid='stAudioInput'] button{color:var(--cr-ink,#2E241C)}
.st-key-add_panel [data-testid='stAudioInputActionButton'] svg{fill:currentColor}
.st-key-add_panel [data-testid^='stBaseButton-secondary'],.st-key-add_cancel button{border-radius:999px;border:none;background:var(--cr-surface-hi);
 color:var(--cr-ink);box-shadow:4px 4px 10px var(--cr-shadow),-4px -4px 10px var(--cr-light)}
.st-key-qa_chips button{border-radius:999px;background:var(--cr-chip);border:none;padding:6px 14px;color:var(--cr-accent-ink);
 box-shadow:3px 3px 8px var(--cr-shadow),-3px -3px 8px var(--cr-light)}
.st-key-qa_chips button:hover{color:var(--cr-ink)}
.st-key-add_panel [data-testid='stFormSubmitButton'] button{padding:8px 26px;font-size:calc(17px*var(--cr-fs,1))}
[class*='st-key-qa_save_'] button,[class*='st-key-qdone_'] button{border-radius:999px;border:none;padding:6px 16px;
 background:var(--cr-surface-hi);color:var(--cr-accent-ink);box-shadow:4px 4px 10px var(--cr-shadow),-4px -4px 10px var(--cr-light)}
[class*='st-key-qa_save_'] button:hover,[class*='st-key-qdone_'] button:hover{color:var(--cr-ink)}
.cr-hero{margin-bottom:24px}
.st-key-q_record button{border-radius:999px;border:none;background:var(--cr-surface-hi);box-shadow:5px 5px 12px var(--cr-shadow),-5px -5px 12px var(--cr-light)}
.cr-hero{background:var(--cr-surface-hi);border-radius:28px;box-shadow:10px 10px 26px var(--cr-shadow),-8px -8px 22px var(--cr-light);backdrop-filter:var(--cr-blur)}
.cr-working{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:10000;box-sizing:border-box;
 width:min(680px,calc(100vw - 32px));padding:14px 18px;border-radius:18px;border:1px solid var(--cr-accent-ink,#7A3F1E);
 background:var(--cr-surface-hi,#FFFCF8);color:var(--cr-ink,#2E241C);box-shadow:0 8px 28px var(--cr-shadow,rgba(0,0,0,.2));
 backdrop-filter:blur(16px);pointer-events:none;font-family:system-ui,sans-serif;font-size:calc(15px*var(--cr-fs,1));line-height:1.4}
.cr-working strong{display:block;margin-bottom:4px}.cr-working small{display:block;color:var(--cr-muted,#584434);font-size:.9em}
.cr-working-spin{display:inline-block;width:16px;height:16px;margin-right:10px;vertical-align:-2px;border:2px solid currentColor;
 border-right-color:transparent;border-radius:50%;animation:cr-working-turn .9s linear infinite}
@keyframes cr-working-turn{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.cr-working-spin{animation:none}}
"""   # Streamlit's own parts in the warm look: soft raised tiles, a pressed state, inset fields, honey buttons
# "sunlit": a warm beige room lit from the top left, soft low-saturation orange glows, frosted glass panes with bright
# rims, a charcoal pill with an orange round arrow for the main action. Each pane carries its own glow under a frosted
# layer, so the glass still reads where backdrop-filter is not supported.
_SUN_SHEEN = "linear-gradient(152deg,rgba(255,255,255,.60) 0%,rgba(255,255,255,.16) 32%,rgba(255,255,255,0) 56%)"   # light on the glass
_SUN_PANE = "linear-gradient(165deg,rgba(255,252,247,.66) 0%,rgba(255,247,238,.42) 100%)"   # the frosted body
_SUN_BLUR = "backdrop-filter:blur(18px) saturate(1.25);-webkit-backdrop-filter:blur(18px) saturate(1.25)"
_SUN_SHADOW = ("box-shadow:inset 0 1.5px 0 rgba(255,255,255,.95),inset 0 -14px 28px rgba(255,230,204,.20),"
               "0 26px 48px -22px rgba(104,66,34,.42),0 6px 16px -6px rgba(104,66,34,.16);" + _SUN_BLUR)   # bright rim, warm shadow
_SUN_RIM = "border:1px solid rgba(255,255,255,.82);" + _SUN_SHADOW
_SUN_RIM_STILL = _SUN_RIM.replace(_SUN_BLUR, "")   # big panes that scroll: their painted glow, no live blur (smooth scrolling)
_SUN_RIM_UP = ("box-shadow:inset 0 1.5px 0 #FFFFFF,inset 0 -14px 28px rgba(255,230,204,.24),0 36px 60px -22px rgba(104,66,34,.50),"
               "0 10px 22px -8px rgba(104,66,34,.20)")


def _sun_glow(r: int, at: str, a: float, rgb: str = "228,146,92") -> str:
    """A soft orange orb inside a pane: strongest at its centre, gone at r px."""
    return (f"radial-gradient(circle {r}px at {at},rgba({rgb},{a}) 0%,rgba({rgb},{a * .66:.2f}) 34%,rgba({rgb},{a * .26:.2f}) 66%,"
            f"rgba({rgb},0) 100%)")


def _sun_orb(r: int, x: str, y: str) -> str:
    """The orange orb glowing through the big tile, as in the reference: a fuller body with a soft edge, lit from the top
    left."""
    return (f"radial-gradient(circle {r * 9 // 20}px at calc({x} - {r // 5}px) calc({y} - {r // 4}px),rgba(255,228,198,.50) 0%,"
            f"rgba(255,228,198,0) 100%),radial-gradient(circle {r}px at {x} {y},rgba(232,156,102,.92) 0%,rgba(232,156,102,.86) 38%,"
            "rgba(234,162,110,.62) 56%,rgba(238,176,128,.28) 72%,rgba(240,188,148,.08) 86%,rgba(240,188,148,0) 100%)")


_SUN_ROOM = ("radial-gradient(ellipse 72% 62% at 0% 0%,rgba(255,250,240,.96) 0%,rgba(255,247,234,.52) 46%,rgba(255,247,234,0) 76%),"
             + _sun_glow(360, "92% 20%", .34) + "," + _sun_glow(320, "3% 92%", .26) + ","
             "linear-gradient(112deg,rgba(255,252,244,0) 30%,rgba(255,252,244,.32) 37%,rgba(255,252,244,0) 45%,rgba(255,252,244,0) 52%,"
             "rgba(255,252,244,.22) 57%,rgba(255,252,244,0) 64%),linear-gradient(160deg,#F6EDE0 0%,#EEE1CF 46%,#E4D2BC 100%)")
_SUN_TILES = (".st-key-add_ask", ".st-key-add_recording", ".st-key-add_paper")
_SUN_PILLS = (".st-key-add_cancel button", ".st-key-add_panel [data-testid^='stBaseButton-secondary']", ".st-key-qa_chips button",
              "[class*='st-key-qa_save_'] button", "[class*='st-key-qdone_'] button", "[class*='st-key-qhint_'] button",
              "[class*='st-key-qopen_'] button", ".st-key-q_record button", "[data-testid='stSidebar'] [data-testid^='stBaseButton-secondary']")
_SUN_STATES = ("", ":hover", ":active", ":focus")   # PAGE_CSS gives the pastel tiles their colour in every one of these


def _sun_all(selectors, states=("",)) -> str:
    return ",".join(f".stApp {s}{x}" for s in selectors for x in states)


def _sun_tile(states=("",), tiles=_SUN_TILES) -> str:
    return ",".join(f"{t} button{x}" for t in tiles for x in states)


_SUN_ARROW = ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23FFF8EE' "
              "stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12h14M13 6l6 6-6 6'/%3E%3C/svg%3E\")")
_SUN_ARROW_INK = _SUN_ARROW.replace("%23FFF8EE", "%237C3F17")
_SUN_PRIMARY = "[data-testid^='stBaseButton-primary']"
_SUN_EDGE = "#94735A"   # the edge of a field: 3.7:1 or more against the glass, so older eyes find where to type
# "frostsky" (soft frost, apricot with misty blue): softfrost's soft light on sunlit's structure. A cream room lit softly
# from the top left; soft raised panes (a white highlight top left, a warm shadow bottom right); the three tiles are
# cushions of colour under frost (apricot, misty blue, rose apricot), each with an orb glowing behind the frost (painted
# inside the tile, so it reads without backdrop-filter) and a big raised bead for its icon. The deep colours sit only
# where the eye should go first: the "Right now" band and its warning, and the buttons. Misty blue is the one cool touch.
_FS_DEEP = "linear-gradient(180deg,#926450 0%,#79533F 100%)"   # deep apricot (#C8906A, #E8A06E darkened, dusted): cream text >= 5:1
_FS_DEEP_UP = "linear-gradient(180deg,#996B52 0%,#7F5843 100%)"
_FS_EDGE = "#9A7A62"   # the edge of a glass pill or a segment: >= 3:1 on the glass behind it
_FS_RING = "outline:3px solid #4E6178"   # keyboard focus: deep misty blue, >= 5:1 on the cream
_FS_PANE = "linear-gradient(165deg,rgba(255,253,249,.80) 0%,rgba(255,248,240,.58) 100%)"
_FS_SHEEN = "linear-gradient(150deg,rgba(255,255,255,.62) 0%,rgba(255,255,255,.14) 30%,rgba(255,255,255,0) 52%)"
_FS_RAISED = ("border:1px solid rgba(255,255,255,.88);box-shadow:inset 0 1.5px 0 #FFFFFF,-10px -10px 24px rgba(255,255,255,.55),"
              "16px 20px 40px -18px rgba(120,78,46,.34),0 4px 12px -4px rgba(120,78,46,.12)")   # soft raised: light top left, warm shadow
_FS_BLUR = "backdrop-filter:blur(12px) saturate(1.2);-webkit-backdrop-filter:blur(12px) saturate(1.2)"
_FS_GRAIN = ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E"
             "%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 .45 "
             "0 0 0 0 .34 0 0 0 0 .24 0 0 0 .09 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")")
# a faint grain: the matte, velvety feel of the reference cushions (an SVG noise, drawn once per size)
_FS_ROOM = ("radial-gradient(ellipse 70% 60% at 0% 0%,rgba(255,253,247,.98) 0%,rgba(255,250,242,.55) 45%,rgba(255,250,242,0) 75%),"
            + _sun_glow(380, "94% 14%", .30, "232,160,110") + "," + _sun_glow(360, "2% 96%", .20, "168,184,204") + ","
            + _sun_glow(300, "98% 98%", .22, "214,170,180") + ",linear-gradient(162deg,#FAF3E9 0%,#F5E9DA 46%,#F0DECD 100%)")
_FS_PRIMARY_SHADOW = ("inset 0 1px 0 rgba(255,232,208,.55),inset 0 -3px 8px rgba(60,32,16,.24),0 14px 26px -12px rgba(120,74,48,.60),"
                      "0 3px 8px rgba(110,66,40,.16)")


def _fs_plate(bloom: bool = True) -> str:
    """The "Right now" plate: a cushion of deep dusty apricot under frost, set into the light card (not a block across it).
    A frost sheen along its top edge, a faint grain, a soft bloom of light low on the right where no words sit (desktop),
    shading from deep apricot into a dusk plum. Cream text on it >= 4.9:1."""
    return ("background:" + _FS_GRAIN + ",linear-gradient(180deg,rgba(255,255,255,.30) 0,rgba(255,255,255,.10) 8px,rgba(255,255,255,0) 16px),"
            + ("radial-gradient(ellipse 40% 130% at 100% 100%,rgba(255,236,224,.12) 0%,rgba(255,236,224,0) 70%)," if bloom else "")
            + "linear-gradient(100deg,#84604F 0%,#7F5D56 55%,#7A5A66 100%);"
            "box-shadow:inset 0 1px 0 rgba(255,242,230,.50),inset 0 0 0 1px rgba(255,236,222,.14),inset 0 -12px 24px rgba(48,24,16,.16),"
            "0 14px 24px -16px rgba(90,52,34,.60)")
_FS_TILE_BG = ("background:" + _FS_GRAIN + "," + _FS_SHEEN + ",var(--fs-rings,linear-gradient(transparent,transparent)),"
               "linear-gradient(165deg,rgba(255,252,248,.40) 0%,rgba(255,250,244,.12) 55%,rgba(255,248,240,.26) 100%),"   # the frost
               "radial-gradient(circle calc(var(--fs-or)*.45) at calc(var(--fs-ox) - var(--fs-or)*.22) calc(var(--fs-oy) - var(--fs-or)*.26),"
               "rgba(255,242,230,.32) 0%,rgba(255,242,230,0) 100%),"   # light on the orb, from the top left
               "radial-gradient(circle var(--fs-or) at var(--fs-ox) var(--fs-oy),rgba(var(--fs-glow),var(--fs-a,.82)) 0%,"
               "rgba(var(--fs-glow),calc(var(--fs-a,.82)*.74)) 40%,rgba(var(--fs-glow),calc(var(--fs-a,.82)*.30)) 72%,rgba(var(--fs-glow),0) 100%),"
               "linear-gradient(160deg,var(--fs-t1) 0%,var(--fs-t2) 100%)")   # the cushion of colour under the frost
_FS_TILE_SHADOW = ("inset 0 1.5px 0 rgba(255,255,255,.92),inset 0 -18px 32px rgba(var(--fs-orb),.18),0 0 0 1px rgba(var(--fs-orb),.26),"
                   "-8px -8px 20px rgba(255,255,255,.6),14px 18px 34px -16px rgba(110,70,40,.40)")
_FS_TILE_UP = ("inset 0 1.5px 0 #FFFFFF,inset 0 -18px 32px rgba(var(--fs-orb),.14),0 0 0 1px rgba(var(--fs-orb),.40),"
               "-8px -8px 22px rgba(255,255,255,.7),20px 32px 52px -16px rgba(110,70,40,.58),0 8px 14px -6px rgba(110,70,40,.22)")
_FS_TILE_IN = ("inset 0 4px 12px rgba(90,50,24,.24),inset 0 0 0 1px rgba(255,255,255,.5),0 0 0 1px rgba(var(--fs-orb),.34),"
               "4px 6px 12px -6px rgba(110,70,40,.30)")


def _fs_chevron(ink: str) -> str:
    return ("url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23" + ink.lstrip("#")
            + "' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M10 6l6 6-6 6'/%3E%3C/svg%3E\")")


def _fs_rings(r1: int, r2: int) -> str:
    """The Ask tile's two faint listening rings round its orb."""
    return (f"radial-gradient(circle at var(--fs-ox) var(--fs-oy),rgba(255,250,244,0) 0 {r1 - 1}px,rgba(255,250,244,.72) {r1}px {r1 + 2}px,"
            f"rgba(255,250,244,0) {r1 + 3}px {r2 - 1}px,rgba(255,250,244,.46) {r2}px {r2 + 2}px,rgba(255,250,244,0) {r2 + 3}px)")


LOOK_CSS = {   # CSS only one look needs, after PAGE_CSS (so it overrides the pastel tiles' fixed colours)
    "sunlit": "".join([
        # the room: warm beige wall, sunlight from the top left falling off to the lower right, two soft orange glows,
        # a faint beam of window light
        ".stApp{color:#2E241C;background:" + _SUN_ROOM + ";background-attachment:fixed}",
        "header[data-testid='stHeader']{background:linear-gradient(180deg,#F7EFE4 0%,#F5ECDF 100%);"
        "box-shadow:0 1px 0 rgba(122,86,56,.10),0 8px 14px -10px rgba(104,66,34,.25)}",
        "[data-testid='stSidebar']{background:linear-gradient(180deg,rgba(255,251,245,.58),rgba(255,247,238,.40));"
        "border-right:1px solid rgba(255,255,255,.8);box-shadow:inset -1px 0 0 rgba(255,255,255,.5),14px 0 34px -20px rgba(104,66,34,.34);"
        + _SUN_BLUR + "}",
        ".stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp [data-testid='stWidgetLabel'] p{color:#2E241C}",
        ".stApp [data-testid='stCaptionContainer']{color:#574334;opacity:1}",   # Streamlit greys captions with opacity .6
        ".stApp [data-testid='stAlertContainer']:has([data-testid='stAlertContentInfo']){background:linear-gradient(160deg,"
        "rgba(255,255,255,.66),rgba(255,250,244,.44));border:1px solid rgba(255,255,255,.9);border-radius:18px;"
        "box-shadow:inset 0 1px 0 #FFFFFF,0 10px 22px -14px rgba(104,66,34,.4)}",
        ".stApp [data-testid='stAlertContentInfo'],.stApp [data-testid='stAlertContentInfo'] p{color:#4A3729}",
        ".stApp [data-testid='stAlertContentWarning'],.stApp [data-testid='stAlertContentWarning'] p{color:#6B4306}",
        ".stApp [data-testid='stAlertContainer']:has([data-testid='stAlertContentSuccess']){background:rgba(150,160,84,.18)}",
        ".stApp [data-testid='stAlertContentSuccess'],.stApp [data-testid='stAlertContentSuccess'] p{color:#46521A}",
        # the three big tiles: frosted glass, bright rims, a glow inside each (the big one carries the orange orb)
        _sun_tile(_SUN_STATES) + "{color:#2E241C;border:1px solid rgba(255,255,255,.85);border-radius:30px;padding:18px 20px;"
        + _SUN_SHADOW + ";transition:transform .14s,box-shadow .14s,filter .14s}",
        _sun_tile(_SUN_STATES, [".st-key-add_ask"]) + "{background:" + _SUN_SHEEN + "," + _sun_orb(170, "72%", "42%") + ","
        + _SUN_PANE + "}",
        _sun_tile(_SUN_STATES, [".st-key-add_recording"]) + "{background:" + _SUN_SHEEN + ","
        + _sun_glow(130, "97% 100%", .46, "226,156,108") + "," + _SUN_PANE + "}",
        _sun_tile(_SUN_STATES, [".st-key-add_paper"]) + "{background:" + _SUN_SHEEN + ","
        + _sun_glow(130, "97% 0%", .46, "222,170,112") + "," + _SUN_PANE + "}",
        _sun_tile([":hover"]) + "{transform:translateY(-4px);filter:brightness(1.04) saturate(1.06);border-color:#FFFFFF;"
        + _SUN_RIM_UP + "}",
        _sun_tile([":active"]) + "{transform:scale(.985);filter:none;box-shadow:inset 0 3px 10px rgba(104,66,34,.20),"
        "0 12px 24px -16px rgba(104,66,34,.34)}",
        _sun_tile([":focus-visible"]) + "{outline:3px solid #8E4518;outline-offset:4px}",
        _sun_tile() + "{position:relative}",
        _sun_tile(["::after"]) + "{content:'';position:absolute;top:18px;right:18px;width:40px;height:40px;border-radius:50%;"
        f"background:{_SUN_ARROW_INK} center/18px no-repeat,radial-gradient(circle at 32% 24%,#FFFFFF 0%,rgba(255,252,247,.78) 60%,"
        "rgba(248,232,214,.6) 100%);border:1px solid rgba(255,255,255,.95);box-shadow:0 6px 14px -6px rgba(104,66,34,.40);"
        "transition:transform .15s}",   # a round arrow: this goes somewhere
        _sun_tile([":hover::after"]) + "{transform:translateX(3px)}",
        ",".join(f"{t} button p+p" for t in _SUN_TILES) + "{color:#574334}",
        ",".join(f"{t} [data-testid='stIconMaterial']" for t in _SUN_TILES) + "{width:54px;height:54px;border-radius:50%;color:#7C3F17;"
        "background:radial-gradient(circle at 32% 24%,#FFFFFF 0%,rgba(255,252,247,.86) 42%,rgba(248,232,214,.72) 100%);"
        "border:1px solid rgba(255,255,255,.95);box-shadow:inset 0 -3px 6px rgba(176,120,76,.18),0 8px 16px -6px rgba(104,66,34,.36)}",
        ".st-key-add_ask [data-testid='stIconMaterial']{color:#F4C9A0;background:radial-gradient(circle at 32% 24%,#5E5148 0%,#2F2722 72%);"
        "border-color:rgba(255,255,255,.3)}",
        # the main action: a charcoal pill with a muted orange round arrow
        _sun_all([_SUN_PRIMARY], _SUN_STATES) + "{color:#FFF5E8;border:1px solid rgba(255,255,255,.16);"
        "background:linear-gradient(180deg,#483D35 0%,#2C2520 100%);filter:none}",
        f".stApp {_SUN_PRIMARY}{{position:relative;border-radius:999px;font-weight:700;padding:8px 54px 8px 22px;min-height:50px;"
        "box-shadow:inset 0 1px 0 rgba(255,255,255,.22),inset 0 -2px 6px rgba(0,0,0,.25),0 14px 26px -12px rgba(58,34,16,.62),"
        "0 3px 8px rgba(58,34,16,.18);transition:transform .12s,box-shadow .12s}",
        f".stApp {_SUN_PRIMARY} p{{color:#FFF5E8;white-space:normal;line-height:1.25;font-weight:700;overflow-wrap:normal;word-break:normal}}",
        f".stApp {_SUN_PRIMARY} [data-testid='stMarkdownContainer']{{white-space:normal;overflow:visible;text-overflow:clip;text-wrap:balance}}",
        "@media (max-width:1300px){.stApp .st-key-mark_read [data-testid^='stBaseButton-primary']{padding:8px 16px}"
        ".stApp .st-key-mark_read [data-testid^='stBaseButton-primary']::after{display:none}}",
        f".stApp {_SUN_PRIMARY}::after{{content:'';position:absolute;right:6px;top:50%;width:38px;height:38px;margin-top:-19px;"
        f"border-radius:50%;background:{_SUN_ARROW} center/18px no-repeat,radial-gradient(circle at 34% 28%,#F4CBA3 0%,#E2A071 56%,#CD8752 100%);"
        "box-shadow:inset 0 1px 1px rgba(255,255,255,.55),0 2px 6px rgba(0,0,0,.30);transition:transform .15s}",
        f".stApp {_SUN_PRIMARY}:hover{{background:linear-gradient(180deg,#584B42 0%,#3A312A 100%);transform:translateY(-1px)}}",
        f".stApp {_SUN_PRIMARY}:hover::after{{transform:translateX(2px)}}",
        f".stApp {_SUN_PRIMARY}:active{{transform:scale(.98);box-shadow:inset 0 3px 8px rgba(0,0,0,.45)}}",
        f".stApp {_SUN_PRIMARY}:focus-visible{{outline:3px solid #A4521C;outline-offset:3px}}",
        f".stApp {_SUN_PRIMARY}:disabled,.stApp {_SUN_PRIMARY}:disabled:hover{{background:rgba(110,86,66,.12);color:#5E4B3D;"
        "border:1px solid rgba(255,255,255,.6);box-shadow:none;padding:8px 24px;transform:none}",
        f".stApp {_SUN_PRIMARY}:disabled p{{color:#5E4B3D}}",
        f".stApp {_SUN_PRIMARY}:disabled::after{{display:none}}",
        ".st-key-add_panel [data-testid='stFormSubmitButton'] button{padding:8px 58px 8px 26px}",
        # everything else you press: small frosted glass pills
        _sun_all(_SUN_PILLS) + "{background:linear-gradient(160deg,rgba(255,255,255,.82),rgba(255,250,244,.52));"
        "border:1px solid rgba(255,255,255,.92);border-radius:999px;padding:6px 16px;color:#4A2E1A;box-shadow:inset 0 1px 0 #FFFFFF,"
        "inset 0 -2px 5px rgba(176,120,76,.12),0 10px 20px -10px rgba(104,66,34,.44),0 2px 5px rgba(104,66,34,.10);"
        "transition:transform .12s,background .12s}",
        _sun_all(_SUN_PILLS, [":hover"]) + "{background:linear-gradient(160deg,#FFFFFF,rgba(255,252,247,.76));color:#2E241C;"
        "border-color:#FFFFFF;transform:translateY(-1px)}",
        _sun_all(_SUN_PILLS, [":active"]) + "{transform:scale(.98);box-shadow:inset 0 2px 6px rgba(104,66,34,.22)}",
        _sun_all(_SUN_PILLS, [":focus-visible"]) + "{outline:3px solid #A4521C;outline-offset:2px;color:#2E241C}",
        ".stApp .st-key-qa_chips button p{color:inherit}",
        ",".join(f".stApp {x} [data-testid='stMarkdownContainer']" for x in _SUN_PILLS) + "{white-space:normal;overflow:visible;text-overflow:clip}",
        ",".join(f".stApp {x} p" for x in _SUN_PILLS) + "{white-space:normal}",
        # the controls row
        ".st-key-text_size button{background:rgba(255,255,255,.62);border-color:rgba(255,255,255,.9);color:#2E241C}",
        ".st-key-text_size button:hover{background:rgba(255,255,255,.78);border-color:#FFFFFF}",
        ".st-key-text_size button[aria-checked='true'],.st-key-text_size button[aria-checked='true']:hover{"
        "background:linear-gradient(180deg,#F4D3B0,#E6B285) !important;border-color:rgba(255,255,255,.95) !important;color:#3A2210 !important;"
        "box-shadow:inset 0 1px 0 rgba(255,255,255,.7),0 6px 14px -6px rgba(150,80,30,.5)}",
        ".st-key-text_size button[aria-checked='true'] p{color:#3A2210 !important}",
        ".st-key-text_size button:focus-visible{outline:3px solid #A4521C;outline-offset:2px}",
        "[data-testid='stSelectbox'] [role='group']{background:linear-gradient(160deg,rgba(255,255,255,.80),rgba(255,250,244,.52));"
        "border:1px solid " + _SUN_EDGE + ";border-radius:18px;box-shadow:inset 0 1px 0 #FFFFFF,0 10px 20px -12px rgba(104,66,34,.42)}",
        ".stApp [data-testid='stSelectbox'] [role='group']:focus-within{border-color:#A4521C;box-shadow:0 0 0 3px rgba(196,112,56,.28)}",
        # the "right now" card and the greeting
        ".cr-hero{background:" + _SUN_SHEEN + "," + _sun_glow(250, "98% 0%", .58) + "," + _SUN_PANE + ";border-radius:34px;"
        "padding:28px 32px;" + _SUN_RIM + "}",
        ".cr-hero .cr-fact{border-top-color:rgba(122,86,56,.20)}",
        ".cr-hero .cr-fact.cr-chg{border-top-color:#B45309}",
        ".cr-alert{background:rgba(214,120,88,.14);color:#7A2414;border:1px solid rgba(200,100,70,.24)}",
        ".cr-hello .cr-avatar{box-shadow:0 0 0 3px rgba(255,255,255,.88),0 10px 20px -8px rgba(80,50,30,.5);"
        "background-image:radial-gradient(circle at 34% 26%,rgba(255,255,255,.30),rgba(255,255,255,0) 60%) !important}",
        # the panel that opens below the tiles, its fields, and the answers as a chat
        ".st-key-add_panel{background:" + _SUN_SHEEN + "," + _sun_glow(300, "100% 0%", .40) + "," + _sun_glow(220, "0% 100%", .20)
        + "," + _SUN_PANE + ";border:1px solid rgba(255,255,255,.85) !important;border-radius:34px;padding:26px 28px;"
        + _SUN_SHADOW + "}",
        ".st-key-add_panel [data-testid='stTextInputRootElement'],.st-key-add_panel [data-testid='stTextAreaRootElement']{"
        "background:rgba(255,255,255,.80);border:1px solid " + _SUN_EDGE + ";border-radius:18px;"
        "box-shadow:inset 0 2px 6px rgba(104,66,34,.16),inset 0 -1px 0 #FFFFFF,0 1px 0 rgba(255,255,255,.9)}",
        ".st-key-add_panel [data-baseweb='input'],.st-key-add_panel [data-baseweb='textarea'],.st-key-add_panel [data-baseweb='base-input']{"
        "background:transparent;box-shadow:none;border-color:transparent}",
        ".stApp .st-key-add_panel [data-testid='stTextInputRootElement']:focus-within,.stApp .st-key-add_panel "
        "[data-testid='stTextAreaRootElement']:focus-within{border-color:#A4521C;box-shadow:inset 0 2px 6px rgba(104,66,34,.14),"
        "0 0 0 3px rgba(196,112,56,.28)}",
        ".st-key-add_panel input::placeholder,.st-key-add_panel textarea::placeholder{color:#7A6555;opacity:1}",
        ".cr-bubble-me{border:1px solid rgba(255,255,255,.75);box-shadow:inset 0 1px 0 rgba(255,255,255,.75),"
        "inset 0 -3px 8px rgba(170,96,44,.16),0 12px 24px -12px rgba(140,76,32,.5)}",
        ".cr-bot{background:radial-gradient(circle at 34% 28%,#FBE1C6 0%,#EDB283 60%,#D9965F 100%);color:#4A2410;"
        "border:1px solid rgba(255,255,255,.85);box-shadow:inset 0 1px 1px rgba(255,255,255,.7),0 8px 16px -6px rgba(140,76,32,.45)}",
        ".cr-bubble-bot{background:" + _SUN_SHEEN + ",linear-gradient(165deg,rgba(255,253,250,.76),rgba(255,249,242,.56));"
        "border:1px solid rgba(255,255,255,.9);box-shadow:inset 0 1.5px 0 #FFFFFF,0 20px 40px -22px rgba(104,66,34,.42);"
        "backdrop-filter:none;-webkit-backdrop-filter:none}",
        ".cr-qa-quotes li{background:rgba(255,255,255,.58);border:1px solid rgba(255,255,255,.85);box-shadow:inset 0 1px 0 #FFFFFF}",
        ".cr-qa-av.cr-av-care{background:radial-gradient(circle at 34% 28%,#FFFFFF,#F3E2D0);color:#7C3F17;"
        "border:1px solid rgba(255,255,255,.9);box-shadow:0 3px 8px -3px rgba(104,66,34,.35)}",
        ".cr-leaf{background:linear-gradient(160deg,rgba(250,226,202,.72),rgba(245,212,180,.48));border:1px solid rgba(255,255,255,.78);"
        "box-shadow:inset 0 1px 0 rgba(255,255,255,.8)}",
        # questions for the doctor: frosted notes with a warm glow in the corner
        ".cr-qitem{background:" + _SUN_SHEEN + "," + _sun_glow(120, "100% 0%", .36) + ",linear-gradient(165deg,rgba(255,252,247,.74),"
        "rgba(255,247,238,.50));border:1px solid rgba(255,255,255,.88);border-radius:22px;box-shadow:inset 0 1.5px 0 #FFFFFF,"
        "0 18px 32px -18px rgba(104,66,34,.45)}",
        ".cr-qhint{color:#556024}",
        "[data-testid='stExpander'] details{background:rgba(255,255,255,.50);border:1px solid rgba(255,255,255,.88);border-radius:18px}",
        ".stApp [data-testid='stExpander'] summary,.stApp [data-testid='stExpander'] summary:hover{background:transparent;color:#2E241C}",
        "[data-testid='stToast']{background:rgba(255,251,245,.96);color:#2E241C;border:1px solid #FFFFFF;"
        "box-shadow:0 18px 36px -16px rgba(104,66,34,.45)}",
        # the timeline on a large frosted sheet, the side facts on a frosted card
        "[data-testid='stColumn']:has(.cr-rail){background:" + _SUN_SHEEN + ",linear-gradient(165deg,rgba(255,252,248,.74),"
        "rgba(255,249,242,.62));border-radius:34px;padding:26px 30px 12px;" + _SUN_RIM_STILL + "}",
        ".cr-side{background:" + _SUN_SHEEN + "," + _sun_glow(160, "100% 100%", .26) + ",linear-gradient(165deg,rgba(255,252,248,.74),"
        "rgba(255,249,242,.60));border-radius:28px;padding:22px 22px;margin-top:14px;" + _SUN_RIM_STILL + "}",
        # the timeline's own colours, warmed into the same family
        ".cr{color:#2E241C}",
        ".cr-eyebrow,.cr-fact-label,.cr-fact-note,.cr-meta,.cr-day,.cr-srcrow,.cr-side-sub,.cr-side dt,.cr-foot,details.cr-src,"
        ".cr-qa-how,.cr-qa-src,.cr-qmeta{color:#574334}",
        ".cr-sub,.cr-legend,.cr-row,.cr-quiet,.cr-fam li,.cr-fam-title{color:#4A3729}",
        ".cr-time{color:#2E241C}",
        ".cr-rail{border-left-color:rgba(122,86,56,.26)}",
        ".cr-side section+section{border-top-color:rgba(122,86,56,.18)}",
        ".cr-note>.cr-dot,.cr-ref>.cr-dot{background:#AE9884}",
        ".cr-new{background:#F3D8BD;color:#6A3310}",
        ".cr-seen{color:#8E4518}",
        ".cr-seen::before{background:#8E4518}",
        ".cr-seen::after{background:rgba(164,82,28,.30)}",
        "details.cr-src summary,.cr-leaf details summary{color:#7C3F17}",
        "details.cr-src blockquote{border-left-color:rgba(122,86,56,.3);color:#3E2F24}",
        ".cr-was{background:#F1E1D0;color:#6A3A1A}",
        ".cr-care{color:#4A3628}",
        ".cr-badge-gray{border-color:#7A6656;color:#574334}",
        ".cr-thumb{background:#EADCCB;box-shadow:0 8px 18px -8px rgba(104,66,34,.4)}",
        "::selection{background:rgba(232,160,110,.40);color:#2E241C}",
        ".stApp [data-testid='stCheckbox'] label>span+div{width:20px;height:20px;border:2px solid " + _SUN_EDGE + ";"
        "background-color:rgba(255,255,255,.85)}",
        ".stApp [data-testid='stCheckbox'] label[data-selected='true']>span+div{background-color:#8E4518;border-color:#8E4518}",
        ".stApp a:focus-visible,.stApp summary:focus-visible{outline:3px solid #A4521C;outline-offset:2px;box-shadow:none}",
        "@media (max-width:640px){" + _sun_tile(_SUN_STATES, [".st-key-add_ask"]) + "{background:" + _SUN_SHEEN + ","
        + _sun_orb(64, "58%", "46%") + "," + _SUN_PANE + "}"
        " .st-key-add_ask button,.st-key-add_recording button,.st-key-add_paper button{padding:14px 14px;border-radius:24px}"
        " .st-key-add_ask button::after,.st-key-add_recording button::after,.st-key-add_paper button::after{width:32px;height:32px;"
        "background-size:15px auto}"
        " .st-key-add_ask [data-testid='stIconMaterial'],.st-key-add_recording [data-testid='stIconMaterial'],"
        ".st-key-add_paper [data-testid='stIconMaterial']{width:44px;height:44px}"
        " .cr-hero{padding:22px 20px;border-radius:28px} .st-key-add_panel{padding:18px 16px;border-radius:28px}"
        " [data-testid='stColumn']:has(.cr-rail){padding:20px 16px 8px;border-radius:28px}"
        " .cr-reply{gap:8px} .cr-bot{flex:0 0 32px;width:32px;height:32px} .cr-bot svg{width:16px;height:16px}"
        " .cr-bubble-bot{padding:14px 12px} .cr .cr-qa-quotes li{padding:10px;gap:8px} .cr-leaf{padding:12px}"
        " .st-key-add_ask button::after,.st-key-add_recording button::after,.st-key-add_paper button::after{top:14px;right:14px}}",
    ]),
    "frostsky": "".join([
        # the room: cream, lit softly from the top left, an apricot glow top right and a faint misty blue one low on the left;
        # the header is opaque, painted with the same fixed room, so nothing ghosts under it
        ".stApp{color:#2E241C;background:" + _FS_ROOM + ";background-attachment:fixed}",
        "header[data-testid='stHeader']{background:" + _FS_ROOM + ";background-attachment:fixed;"
        "box-shadow:0 1px 0 rgba(150,110,80,.14),0 10px 18px -14px rgba(104,66,34,.34)}",
        "[data-testid='stSidebar']{background:linear-gradient(180deg,rgba(255,251,246,.74),rgba(252,244,236,.58));"
        "border-right:1px solid rgba(255,255,255,.85);box-shadow:inset -1px 0 0 rgba(255,255,255,.5),14px 0 34px -20px rgba(104,66,34,.30);"
        + _FS_BLUR + "}",
        ".stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp [data-testid='stWidgetLabel'] p{color:#2E241C}",
        ".stApp [data-testid='stCaptionContainer']{color:#584434;opacity:1}",
        ".stApp [data-testid='stAlertContainer']:has([data-testid='stAlertContentInfo']){background:linear-gradient(160deg,"
        "rgba(255,255,255,.70),rgba(255,250,244,.48));border:1px solid rgba(255,255,255,.9);border-radius:18px;"
        "box-shadow:inset 0 1px 0 #FFFFFF,0 10px 22px -14px rgba(104,66,34,.4)}",
        ".stApp [data-testid='stAlertContentInfo'],.stApp [data-testid='stAlertContentInfo'] p{color:#4A3729}",
        ".stApp [data-testid='stAlertContentWarning'],.stApp [data-testid='stAlertContentWarning'] p{color:#6B4306}",
        ".stApp [data-testid='stAlertContainer']:has([data-testid='stAlertContentSuccess']){background:rgba(150,160,84,.18)}",
        ".stApp [data-testid='stAlertContentSuccess'],.stApp [data-testid='stAlertContentSuccess'] p{color:#46521A}",
        # the three tiles: cushions of colour under frost. Ask in the main apricot, Record in misty blue (the cool touch),
        # Share in rose apricot; each orb glows behind the frost, clear of the words (top right, or above the words in the
        # tall Ask tile); a raised bead holds the icon in the tile's deep colour
        ".st-key-add_ask button{--fs-t1:#F6DAC2;--fs-t2:#E2AC85;--fs-orb:236,146,88;--fs-glow:236,146,88;--fs-ox:58%;--fs-oy:44%;--fs-or:78px;"
        "--fs-ink:#552B12;--fs-hint:#5C3820;--fs-glyph:#8A4A26;--fs-chev:" + _fs_chevron("#8A4A26") + ";--fs-rings:" + _fs_rings(100, 124) + "}",
        ".st-key-add_recording button{--fs-t1:#E7ECF2;--fs-t2:#B7C4D4;--fs-orb:112,136,168;--fs-glow:230,239,252;--fs-ink:#253446;--fs-hint:#33435A;"
        "--fs-glyph:#4E6178;--fs-chev:" + _fs_chevron("#4E6178") + "}",
        ".st-key-add_paper button{--fs-t1:#F3E5E8;--fs-t2:#D6BAC6;--fs-orb:180,120,150;--fs-glow:253,232,243;--fs-ink:#4A2738;--fs-hint:#553646;"
        "--fs-glyph:#7A4A62;--fs-chev:" + _fs_chevron("#7A4A62") + "}",
        ".st-key-add_recording button,.st-key-add_paper button{--fs-ox:calc(100% - 44px - var(--fs-chs)/2);--fs-oy:var(--fs-bc);"
        "--fs-or:50px;--fs-a:.9}",   # the small tiles' orb: light blooming round the chevron, lighter than the cushion, inside the window
        _sun_tile(_SUN_STATES) + "{color:var(--fs-ink);border:1px solid rgba(255,255,255,.9);border-radius:30px;padding:18px 20px;"
        + _FS_TILE_BG + ";box-shadow:" + _FS_TILE_SHADOW + ";filter:none;transition:transform .15s,box-shadow .15s}",
        _sun_tile([":hover"]) + "{--fs-a:1;transform:translateY(-6px);border-color:#FFFFFF;box-shadow:" + _FS_TILE_UP + "}",
        _sun_tile([":active"]) + "{transform:translateY(1px) scale(.988);box-shadow:" + _FS_TILE_IN + "}",
        _sun_tile([":focus-visible"]) + "{" + _FS_RING + ";outline-offset:4px}",
        _sun_tile() + "{position:relative;--fs-chs:min(calc(36px*var(--cr-fs,1)),46px);--fs-bc:calc(18px + min(calc(34px*var(--cr-fs,1)),44px))}",
        _sun_tile(["::after"]) + "{content:'';position:absolute;top:calc(var(--fs-bc) - var(--fs-chs)/2);right:44px;width:var(--fs-chs);"
        "height:var(--fs-chs);border-radius:50%;"   # the chevron grows with the text size, level with the bead's centre
        "background:var(--fs-chev) center/calc(var(--fs-chs)*.47) no-repeat,radial-gradient(circle at 32% 26%,#FFFFFF 0%,rgba(255,251,246,.88) 60%,"
        "rgba(250,240,230,.76) 100%);border:1px solid rgba(255,255,255,.95);box-shadow:0 6px 12px -5px rgba(90,56,30,.42);"
        "transition:transform .15s}",   # a small round chevron in front of the orb: this goes somewhere
        _sun_tile([":hover::after"]) + "{transform:translateX(3px)}",
        ",".join(f"{t} button p:first-child" for t in _SUN_TILES) + "{color:var(--fs-ink)}",
        ",".join(f"{t} button p+p" for t in _SUN_TILES) + "{color:var(--fs-hint)}",
        ",".join(f"{t} [data-testid='stIconMaterial']" for t in _SUN_TILES) + "{width:min(calc(68px*var(--cr-fs,1)),88px);"
        "height:min(calc(68px*var(--cr-fs,1)),88px);border-radius:50%;font-size:calc(40px*var(--cr-fs,1));color:var(--fs-glyph);"
        "background:radial-gradient(circle at 32% 24%,#FFFFFF 0%,rgba(255,252,248,.94) 42%,rgba(250,240,230,.82) 100%);"
        "border:1px solid rgba(255,255,255,.96);box-shadow:inset 0 2px 0 #FFFFFF,inset 0 -5px 10px rgba(var(--fs-orb),.24),"
        "0 0 0 1px rgba(var(--fs-orb),.24),0 12px 22px -8px rgba(90,56,30,.42)}",
        # the main action: deep apricot, cream words, lifted on a warm glow
        _sun_all([_SUN_PRIMARY], _SUN_STATES + (":focus-visible",)) + "{color:#FFF6EC;border:1px solid rgba(255,236,216,.30);background:"
        + _FS_DEEP + ";filter:none;box-shadow:" + _FS_PRIMARY_SHADOW + "}",
        f".stApp {_SUN_PRIMARY}{{border-radius:999px;font-weight:700;padding:8px 24px;min-height:50px;transition:transform .12s,box-shadow .12s}}",
        f".stApp {_SUN_PRIMARY} p{{color:#FFF6EC;white-space:normal;line-height:1.25;font-weight:700;overflow-wrap:normal;word-break:normal}}",
        f".stApp {_SUN_PRIMARY} [data-testid='stMarkdownContainer']{{white-space:normal;overflow:visible;text-overflow:clip;text-wrap:balance}}",
        f".stApp {_SUN_PRIMARY}:hover{{background:{_FS_DEEP_UP};transform:translateY(-2px);box-shadow:inset 0 1px 0 rgba(255,232,208,.6),"
        "inset 0 -3px 8px rgba(60,32,16,.20),0 20px 32px -12px rgba(120,74,48,.68),0 4px 10px rgba(110,66,40,.18)}",
        f".stApp {_SUN_PRIMARY}:active{{transform:translateY(1px) scale(.985);box-shadow:inset 0 3px 9px rgba(50,26,12,.45)}}",
        f".stApp {_SUN_PRIMARY}:focus-visible{{{_FS_RING};outline-offset:3px}}",
        f".stApp {_SUN_PRIMARY}:disabled,.stApp {_SUN_PRIMARY}:disabled:hover{{background:rgba(255,250,244,.50);color:#6E5A49;"
        f"border:1px solid rgba(154,122,98,.60);box-shadow:none;transform:none;font-weight:400}}",
        f".stApp {_SUN_PRIMARY}:disabled p{{color:#6E5A49;font-weight:400}}",   # disabled looks disabled: flat, lighter, regular
        # everything else you press: frosted glass pills, a bright rim inside a warm edge
        _sun_all(_SUN_PILLS, ("", ":focus")) + "{background:linear-gradient(160deg,rgba(255,255,255,.80),rgba(255,249,242,.48));"
        "border:1px solid " + _FS_EDGE + ";border-radius:999px;padding:6px 18px;color:#3A2A1E;box-shadow:inset 0 1px 0 #FFFFFF,"
        "inset 0 0 0 1px rgba(255,255,255,.55),inset 0 -2px 6px rgba(176,120,76,.12),0 8px 18px -10px rgba(104,66,34,.44);"
        + _FS_BLUR + ";transition:transform .12s,background .12s}",
        _sun_all(_SUN_PILLS, [":hover"]) + "{background:linear-gradient(160deg,#FFFFFF,rgba(255,252,247,.78));color:#2E241C;"
        "border-color:#86664F;transform:translateY(-1px)}",
        _sun_all(_SUN_PILLS, [":active"]) + "{transform:scale(.98);box-shadow:inset 0 2px 6px rgba(104,66,34,.24)}",
        _sun_all(_SUN_PILLS, [":focus-visible"]) + "{" + _FS_RING + ";outline-offset:2px;color:#2E241C}",
        ".stApp .st-key-qa_chips button{color:#6E3A1C}",
        ".stApp .st-key-qa_chips button p{color:inherit}",
        ",".join(f".stApp {x} [data-testid='stMarkdownContainer']" for x in _SUN_PILLS) + "{white-space:normal;overflow:visible;text-overflow:clip}",
        ",".join(f".stApp {x} p" for x in _SUN_PILLS) + "{white-space:normal}",
        ".stApp button:focus-visible,.stApp a:focus-visible,.stApp summary:focus-visible{" + _FS_RING + ";outline-offset:2px}",
        # the controls row: glass segments with a warm edge, the chosen text size filled in misty blue
        ".stApp .st-key-text_size [role='radiogroup']{border:1px solid " + _FS_EDGE + ";border-radius:999px;padding:3px;gap:3px;"
        "background:linear-gradient(160deg,rgba(255,255,255,.82),rgba(255,249,242,.50));box-shadow:inset 0 1px 0 #FFFFFF,"
        "0 8px 18px -12px rgba(104,66,34,.40);" + _FS_BLUR + "}",
        ".stApp .st-key-text_size button{border:1px solid transparent;border-radius:999px;background:transparent;color:#2E241C}",
        ".stApp .st-key-text_size button:hover{background:rgba(255,255,255,.80);border-color:rgba(154,122,98,.45)}",
        ".stApp .st-key-text_size button:not([aria-checked='true']):focus{box-shadow:none;background:transparent}",
        ".stApp .st-key-text_size button:not([aria-checked='true']):focus-visible,.stApp .st-key-text_size "
        "button:not([aria-checked='true']):focus:hover{background:rgba(255,255,255,.80)}",
        ".st-key-text_size button[aria-checked='true'],.st-key-text_size button[aria-checked='true']:hover{"
        "background:linear-gradient(180deg,#5C7087,#4C5F75) !important;border-color:#4C5F75 !important;color:#FFF6EC !important;border-radius:999px;"
        "box-shadow:inset 0 1px 0 rgba(255,255,255,.3),0 6px 14px -6px rgba(60,80,104,.6)}",
        ".st-key-text_size button[aria-checked='true'] p{color:#FFF6EC !important}",
        ".stApp .st-key-text_size [role='radiogroup'] button:focus-visible{" + _FS_RING + ";outline-offset:-3px}",   # inside: the track clips
        ".stApp .st-key-text_size [role='radiogroup'] button[aria-checked='true']:focus-visible{outline-color:#FFF6EC;outline-offset:-6px}",
        "[data-testid='stSelectbox'] [role='group']{background:linear-gradient(160deg,rgba(255,255,255,.82),rgba(255,250,244,.56));"
        "border:1px solid " + _SUN_EDGE + ";border-radius:18px;box-shadow:inset 0 1px 0 #FFFFFF,0 10px 20px -12px rgba(104,66,34,.42)}",
        ".stApp [data-testid='stSelectbox'] [role='group']:focus-within{border-color:#4E6178;box-shadow:0 0 0 3px rgba(78,97,120,.30)}",
        # the "Right now" card: a plate of deep dusty apricot set into the light frost (the phase, where she is), the three
        # facts below in deep apricot with a colour-card rule each, and the warning signs on deep dusk rose
        ".cr-hero{background:" + _FS_SHEEN + "," + _sun_glow(260, "100% 100%", .26, "232,170,130") + "," + _FS_PANE + ";"
        "border-radius:34px;padding:10px 10px 24px;overflow:hidden;gap:18px;" + _FS_RAISED + "}",
        ".cr-hero-top{padding:18px 24px 16px;border-radius:26px;" + _fs_plate() + "}",
        ".cr-hero>.cr-facts,.cr-hero>.cr-alert,.cr-hero>.cr-strip{margin:0 22px}",
        ".cr-chip{background:rgba(246,238,230,.75);border-radius:18px;box-shadow:inset 3px 3px 7px rgba(150,112,84,.16),inset -3px -3px 7px rgba(255,255,255,.8)}",
        ".cr-chip-value{color:#6A3519}",
        ".cr-hero-top .cr-phase{color:#FFF8F0}",
        ".cr-hero-top .cr-sub,.cr-hero-top .cr-fact-note{color:#FFF0E2}",
        ".cr-hero-top .cr-badge{border-color:rgba(255,240,226,.8);color:#FFF1E4}",
        ".cr-hero .cr-fact{border-top-width:4px}",
        ".cr-hero .cr-fact:nth-child(1){border-top-color:#C8906A}",
        ".cr-hero .cr-fact:nth-child(2){border-top-color:#8193AA}",
        ".cr-hero .cr-fact:nth-child(3){border-top-color:#BC98A8}",
        ".cr-hero .cr-fact.cr-chg{border-top-color:#A85A2E}",
        ".cr-hero .cr-fact-value{color:#6A3519}",
        # the warning signs: a rose frost with the words in deep dusk rose, a deep dusk-rose edge on the left holding the sign
        ".cr-alert{position:relative;padding-left:calc(26px + 30px*var(--cr-fs,1));color:#5E2F36;background:"
        "linear-gradient(90deg,#8E5E5B 0,#85565A calc(10px + 30px*var(--cr-fs,1)),rgba(0,0,0,0) calc(10px + 30px*var(--cr-fs,1))),"
        + _FS_GRAIN + ",linear-gradient(165deg,rgba(251,235,232,.95) 0%,rgba(245,221,218,.88) 100%);"
        "border:1px solid rgba(133,86,90,.45);border-radius:18px;overflow:hidden;box-shadow:inset 0 1px 0 rgba(255,255,255,.85),"
        "inset 0 -6px 14px rgba(150,90,96,.10),0 12px 22px -14px rgba(120,58,58,.45)}",
        ".cr-alert b{color:#6E3038}",
        # two different answers from the care team: the same plate in deep amber, so it reads as "ask", not "danger"
        ".cr-alert.cr-conflict{color:#5A3A12;border-color:rgba(150,100,40,.50);background:linear-gradient(90deg,#A4742F 0,"
        "#9A6B2A calc(10px + 30px*var(--cr-fs,1)),rgba(0,0,0,0) calc(10px + 30px*var(--cr-fs,1)))," + _FS_GRAIN + ","
        "linear-gradient(165deg,rgba(255,244,224,.96) 0%,rgba(250,230,196,.90) 100%)}",
        ".cr-alert.cr-conflict b{color:#5A3510}",
        ".cr-alert svg{position:absolute;left:calc(5px + 15px*var(--cr-fs,1) - 9px*var(--cr-fs,1));color:#FFF6EE}",
        ".cr-alert svg{flex:0 0 auto;width:calc(18px*var(--cr-fs,1));height:calc(18px*var(--cr-fs,1));margin-top:.15em}",   # never squeezed
        ".cr-hello .cr-avatar{box-shadow:0 0 0 3px rgba(255,255,255,.9),0 10px 20px -8px rgba(60,70,90,.5);"
        "background-image:radial-gradient(circle at 30% 22%,rgba(255,255,255,.14),rgba(255,255,255,0) 40%) !important}",
        # the panel that opens below the tiles, its fields, and the answers as a chat (you ask in misty blue)
        ".st-key-add_panel{background:" + _FS_SHEEN + "," + _sun_glow(300, "100% 0%", .30, "232,160,110") + ","
        + _sun_glow(220, "0% 100%", .14, "168,184,204") + "," + _FS_PANE + ";border-radius:34px;padding:26px 28px;" + _FS_RAISED + "}",
        ".st-key-add_panel{border:1px solid rgba(255,255,255,.88) !important}",
        ".st-key-add_panel [data-testid='stTextInputRootElement'],.st-key-add_panel [data-testid='stTextAreaRootElement']{"
        "background:rgba(255,255,255,.82);border:1px solid " + _SUN_EDGE + ";border-radius:18px;"
        "box-shadow:inset 0 2px 6px rgba(104,66,34,.14),inset 0 -1px 0 #FFFFFF,0 1px 0 rgba(255,255,255,.9)}",
        ".st-key-add_panel [data-baseweb='input'],.st-key-add_panel [data-baseweb='textarea'],.st-key-add_panel [data-baseweb='base-input']{"
        "background:transparent;box-shadow:none;border-color:transparent}",
        ".stApp .st-key-add_panel [data-testid='stTextInputRootElement']:focus-within,.stApp .st-key-add_panel "
        "[data-testid='stTextAreaRootElement']:focus-within{border-color:#4E6178;box-shadow:inset 0 2px 6px rgba(104,66,34,.12),"
        "0 0 0 3px rgba(78,97,120,.30)}",
        ".st-key-add_panel input::placeholder,.st-key-add_panel textarea::placeholder{color:#76614F;opacity:1}",
        ".st-key-add_panel [data-testid='stFileUploaderDropzone'],.st-key-add_panel [data-testid='stAudioInput']>div{"
        "background:rgba(255,255,255,.66);border:1px dashed " + _SUN_EDGE + ";box-shadow:none}",
        ".cr-bubble-me{background:linear-gradient(150deg,#DFE6EE 0%,#BAC7D7 100%);color:#22303F;border:1px solid rgba(255,255,255,.85);"
        "box-shadow:inset 0 1px 0 rgba(255,255,255,.8),inset 0 -3px 8px rgba(86,105,127,.16),0 12px 24px -12px rgba(70,90,116,.45)}",
        ".cr-bot{background:radial-gradient(circle at 34% 28%,#FBE3CB 0%,#EBB68E 60%,#D99C6E 100%);color:#5A2A10;"
        "border:1px solid rgba(255,255,255,.85);box-shadow:inset 0 1px 1px rgba(255,255,255,.7),0 8px 16px -6px rgba(140,76,32,.45)}",
        ".cr-bubble-bot{background:" + _FS_SHEEN + ",linear-gradient(165deg,rgba(255,253,250,.82),rgba(255,249,242,.62));"
        "border:1px solid rgba(255,255,255,.9);box-shadow:inset 0 1.5px 0 #FFFFFF,-6px -6px 16px rgba(255,255,255,.45),"
        "12px 18px 34px -20px rgba(104,66,34,.42);backdrop-filter:none;-webkit-backdrop-filter:none}",
        ".cr-qa-quotes li{background:rgba(255,255,255,.62);border:1px solid rgba(255,255,255,.88);box-shadow:inset 0 1px 0 #FFFFFF,"
        "0 0 0 1px rgba(150,110,80,.10)}",
        ".cr-qa-av.cr-av-care{background:radial-gradient(circle at 34% 28%,#FFFFFF,#F3E2D0);color:#7A3F1E;"
        "border:1px solid rgba(255,255,255,.9);box-shadow:0 3px 8px -3px rgba(104,66,34,.35)}",
        ".cr-leaf{background:linear-gradient(160deg,rgba(250,228,206,.74),rgba(245,214,184,.50));border:1px solid rgba(255,255,255,.8);"
        "box-shadow:inset 0 1px 0 rgba(255,255,255,.8)}",
        # questions for the doctor: frosted notes; the expander with the answered ones in the same glass
        ".cr-qitem{background:" + _FS_SHEEN + "," + _sun_glow(120, "100% 0%", .30, "232,160,110") + ",linear-gradient(165deg,"
        "rgba(255,252,247,.78),rgba(255,247,238,.54));border:1px solid rgba(255,255,255,.9);border-radius:22px;"
        "box-shadow:inset 0 1.5px 0 #FFFFFF,0 18px 32px -18px rgba(104,66,34,.45)}",
        ".cr-qhint{color:#556024}",
        "[data-testid='stExpander'] details{background:rgba(255,255,255,.56);border:1px solid " + _FS_EDGE + ";border-radius:18px}",
        ".stApp [data-testid='stExpander'] summary,.stApp [data-testid='stExpander'] summary:hover{background:transparent;color:#2E241C}",
        ".stApp [data-testid='stExpander'] summary svg{color:#7A3F1E}",
        ".stApp [data-testid='stExpander'] summary:focus,.stApp [data-testid='stExpander'] summary:focus-visible{box-shadow:none;"
        "background:transparent}",   # no Streamlit red focus shadow: only the deep outline below
        "[data-testid='stToast']{background:rgba(255,251,245,.97);color:#2E241C;border:1px solid #FFFFFF;"
        "box-shadow:0 18px 36px -16px rgba(104,66,34,.45)}",
        # the timeline on a large frosted sheet, the side facts on a frosted card (painted, no live blur: smooth scrolling)
        "[data-testid='stColumn']:has(.cr-rail){background:" + _FS_SHEEN + ",linear-gradient(165deg,rgba(255,253,249,.76),"
        "rgba(255,249,243,.62));border-radius:34px;padding:26px 30px 12px;" + _FS_RAISED + "}",
        ".cr-side{background:" + _FS_SHEEN + "," + _sun_glow(160, "100% 100%", .22, "168,184,204") + ",linear-gradient(165deg,"
        "rgba(255,253,249,.76),rgba(255,249,243,.60));border-radius:28px;padding:22px 22px;margin-top:14px;" + _FS_RAISED + "}",
        ".cr-side{overflow-wrap:break-word;min-width:0}",   # a long word (granddaughter) wraps in a narrow side card, never clipped
        # the timeline's own colours in the same family
        ".cr{color:#2E241C}",
        ".cr-eyebrow,.cr-fact-label,.cr-fact-note,.cr-meta,.cr-day,.cr-srcrow,.cr-side-sub,.cr-side dt,.cr-foot,details.cr-src,"
        ".cr-qa-how,.cr-qa-src,.cr-qmeta{color:#584434}",
        ".cr-sub,.cr-legend,.cr-row,.cr-quiet,.cr-fam li,.cr-fam-title{color:#4A3729}",
        ".cr-time{color:#2E241C}",
        ".cr-rail{border-left-color:rgba(122,86,56,.24)}",
        ".cr-side section+section{border-top-color:rgba(122,86,56,.18)}",
        ".cr-new{background:#F5DAC3;color:#6A3310}",
        ".cr-seen{color:#8E4518}",
        ".cr-seen::before{background:#865A44}",
        ".cr-seen::after{background:rgba(134,90,68,.32)}",
        "details.cr-src summary,.cr-leaf details summary{color:#7A3F1E}",
        "details.cr-src blockquote{border-left-color:rgba(122,86,56,.3);color:#3E2F24}",
        ".cr-was{background:#F1E1D0;color:#6A3A1A}",
        ".cr-care{color:#4A3628}",
        ".cr-badge-gray{border-color:#7A6656;color:#574334}",
        ".cr-thumb{background:#EADCCB;box-shadow:0 8px 18px -8px rgba(104,66,34,.4)}",
        "::selection{background:rgba(168,184,204,.55);color:#2E241C}",
        ".stApp [data-testid='stCheckbox'] label>span+div{width:20px;height:20px;border:2px solid " + _SUN_EDGE + ";"
        "background-color:rgba(255,255,255,.85)}",
        ".stApp [data-testid='stCheckbox'] label[data-selected='true']>span+div{background-color:#865A44;border-color:#865A44}",
        # the "Viewing as" list in the same warm glass (Streamlit draws it cool grey)
        "[data-testid='stSelectboxVirtualDropdown']{background:#FFFBF6;border:1px solid rgba(154,122,98,.45);border-radius:16px;"
        "box-shadow:0 18px 36px -16px rgba(104,66,34,.45)}",
        "[data-testid='stSelectboxVirtualDropdown'] [role='option'],[data-testid='stSelectboxVirtualDropdown'] [role='option'] *{color:#2E241C}",
        "[data-testid='stSelectboxVirtualDropdown'] [role='option']>div{border-radius:10px}",
        "[data-testid='stSelectboxVirtualDropdown'] [role='option'][aria-selected='true']>div{background:#F3E2D2}",
        "[data-testid='stSelectboxVirtualDropdown'] [role='option']:hover>div,[data-testid='stSelectboxVirtualDropdown'] "
        "[role='option'][data-focused='true']>div{background:#F8DCC4}",
        # depth (Holly, 2026-10-16: the frostsky colours with the warm-glass depth): each tile sits in a groove pressed
        # into the frost and rises out of it as a cushion; the text-size track is a groove the chosen size stands up in;
        # the "Viewing as" field is pressed in
        ",".join(_SUN_TILES) + "{padding:8px;border-radius:38px;background:linear-gradient(160deg,rgba(206,178,150,.30),"
        "rgba(255,250,244,.62));box-shadow:inset 5px 6px 12px rgba(118,80,50,.24),inset -5px -5px 11px rgba(255,255,255,.95),"
        "0 1px 0 rgba(255,255,255,.9)}",
        _sun_tile(_SUN_STATES) + "{box-shadow:" + _FS_TILE_SHADOW.rstrip() + ",0 12px 20px -10px rgba(104,66,34,.50),0 3px 6px rgba(104,66,34,.16)}",
        _sun_tile([":hover"]) + "{transform:translateY(-3px);box-shadow:" + _FS_TILE_UP.rstrip() + ",0 18px 26px -12px rgba(104,66,34,.55),"
        "0 4px 8px rgba(104,66,34,.18)}",
        _sun_tile([":active"]) + "{transform:translateY(1px) scale(.99);box-shadow:" + _FS_TILE_IN + "}",
        ".stApp .st-key-text_size [role='radiogroup']{padding:4px;gap:4px;border:1px solid rgba(154,122,98,.40);"
        "background:linear-gradient(160deg,rgba(214,190,166,.42),rgba(255,250,244,.66));box-shadow:inset 3px 4px 8px rgba(118,80,50,.26),"
        "inset -3px -3px 7px rgba(255,255,255,.95),0 1px 0 rgba(255,255,255,.9)}",
        ".st-key-text_size button[aria-checked='true'],.st-key-text_size button[aria-checked='true']:hover{"
        "box-shadow:inset 0 1px 0 rgba(255,255,255,.38),inset 0 -3px 5px rgba(28,40,58,.28),0 5px 9px -3px rgba(52,70,94,.60),"
        "0 1px 2px rgba(52,70,94,.35) !important}",
        "[data-testid='stSelectbox'] [role='group']{background:linear-gradient(160deg,rgba(232,214,196,.50),rgba(255,251,246,.80));"
        "border:1px solid rgba(154,122,98,.60);box-shadow:inset 3px 4px 8px rgba(118,80,50,.20),inset -3px -3px 7px rgba(255,255,255,.95),"
        "0 1px 0 rgba(255,255,255,.9)}",
        # mid widths (a tablet, or a laptop with the sidebar open): smaller rings, so they stay inside the Ask tile
        "@media (min-width:641px) and (max-width:1100px){.st-key-add_ask button{--fs-ox:50%;--fs-or:64px;--fs-rings:" + _fs_rings(78, 96) + "}"
        " .st-key-add_recording button,.st-key-add_paper button{--fs-or:40px} .cr-side{padding:18px 14px}}",   # and the small glows clear of a wrapped title
        # less motion for those who ask for it: no lifts, no slides
        "@media (prefers-reduced-motion:reduce){" + _sun_tile([":hover", ":active", ":hover::after"]) + f",.stApp {_SUN_PRIMARY}:hover,"
        f".stApp {_SUN_PRIMARY}:active," + _sun_all(_SUN_PILLS, [":hover", ":active"]) + "{transform:none;transition:none}}",
        # phones: the tiles a little tighter, the Ask orb and its rings up in the corner, clear of the words; the "Right now"
        # plate holds only the phase and the place (the time zone note sits under it on the light frost), so it is a strip
        "@media (max-width:640px){.st-key-add_ask button{--fs-ox:50%;--fs-oy:46%;--fs-or:52px;--fs-rings:" + _fs_rings(66, 82) + "}"
        " .st-key-add_ask button,.st-key-add_recording button,.st-key-add_paper button{padding:14px 14px;border-radius:26px;"
        "--fs-chs:min(calc(34px*var(--cr-fs,1)),42px);--fs-bc:calc(14px + min(calc(31px*var(--cr-fs,1)),40px))}"
        " .st-key-add_recording button,.st-key-add_paper button{--fs-ox:calc(100% - 16px - var(--fs-chs)/2);--fs-or:32px}"
        " .st-key-add_ask button::after,.st-key-add_recording button::after,.st-key-add_paper button::after{right:16px}"
        " .st-key-add_ask [data-testid='stIconMaterial'],.st-key-add_recording [data-testid='stIconMaterial'],"
        ".st-key-add_paper [data-testid='stIconMaterial']{width:min(calc(62px*var(--cr-fs,1)),80px);height:min(calc(62px*var(--cr-fs,1)),80px);"
        "font-size:calc(36px*var(--cr-fs,1))}"
        " .cr-hero{border-radius:28px;padding:8px 8px 20px;gap:14px}"
        " .cr-hero-top{padding:0;border-radius:0;background:none;box-shadow:none;row-gap:10px}"
        " .cr-hero-top>div:first-child{flex:1 1 100%;padding:14px 18px 12px;border-radius:22px;" + _fs_plate(False) + "}"
        " .cr-hero-top>.cr-fact-note{padding:0 10px;color:#584434}"
        " .cr-hero>.cr-facts,.cr-hero>.cr-alert{margin:0 10px}"
        " .st-key-add_panel{padding:18px 16px;border-radius:28px}"
        " [data-testid='stColumn']:has(.cr-rail){padding:20px 16px 8px;border-radius:28px}"
        " .cr-reply{gap:8px} .cr-bot{flex:0 0 32px;width:32px;height:32px} .cr-bot svg{width:16px;height:16px}"
        " .cr-bubble-bot{padding:14px 12px} .cr .cr-qa-quotes li{padding:10px;gap:8px} .cr-leaf{padding:12px}}",
    ]),
}
TEXT_SIZES = {"A": 1.0, "A+": 1.18, "A++": 1.36}   # every font on the page scales, for anyone who finds the text small
FLAG_TEXT = {"unconfirmed": "reported by family, not confirmed", "contradicted": "the care team said otherwise",
             "late": "added late; a newer update stands", "two_answers": "two different answers: ask which is right"}


def endpoint_host() -> str:
    """The model endpoint's host (and port) only: never a user name or password written into the URL."""
    u = urlsplit(os.environ.get("CARERELAY_LLM_BASE_URL", ""))
    return (u.hostname or "the model endpoint") + (f":{u.port}" if u.port else "")


def live_model_configured() -> bool:
    return bool(os.environ.get("CARERELAY_LLM_BASE_URL") and os.environ.get("CARERELAY_LLM_MODEL"))


SPACE_TTL_S = 2 * 24 * 3600   # unload idle cache entries; saved timelines have no automatic expiry
SPACE_MAX = 50   # bounds the in-process cache, never the durable store


def timeline_store() -> TimelineStore:
    directory = Path(os.environ.get("CARERELAY_STATE_DIR") or Path.home() / ".kindredrelay")
    return TimelineStore(directory / "timelines.sqlite3")


def remember_storage_error(message: str) -> None:
    st.session_state.persistence_error = message


def storage_error(message: str, *, warning: bool = False) -> None:
    (st.warning if warning else st.error)(message)
    if st.button("Reload latest timeline", key="reload_saved_timeline"):
        st.session_state.pop("persistence_error", None)
        st.session_state.pop("persistence_warning", None)
        st.rerun()


@st.cache_resource
def family_spaces() -> dict:
    """A bounded cache; SQLite retains spaces across cache eviction and server restarts."""
    return {"lock": threading.Lock(), "spaces": {}}


def current_space() -> dict | None:
    """The family space this page was opened in (?family=...), or None for a private copy of the demo."""
    sid = st.query_params.get("family")
    if not sid:
        return None
    reg = family_spaces()
    store = timeline_store()
    cache_key = (str(store.path), sid)
    with reg["lock"]:
        cached = reg["spaces"].get(cache_key)
        if cached is not None:
            return cached
        legacy = reg["spaces"].get(sid)
        try:
            session = TimelineSession.open(store, sid, "family", Episode, on_error=remember_storage_error)
        except StoreMissing:
            if legacy is None:
                return None
            # Preserve still-live invitations created before this page upgrade.
            session = TimelineSession.create(store, "family", Episode.from_snapshot(legacy["episode"].to_snapshot()),
                                             legacy["photos"], token=sid, on_error=remember_storage_error)
        _cache_space(reg, cache_key, session)
        return reg["spaces"][cache_key]


def _cache_space(reg: dict, key: tuple, session: TimelineSession) -> None:
    now = time.time()
    for old in [k for k, v in reg["spaces"].items() if now - v["at"] > SPACE_TTL_S]:
        del reg["spaces"][old]
    while len(reg["spaces"]) >= SPACE_MAX:
        del reg["spaces"][min(reg["spaces"], key=lambda k: reg["spaces"][k]["at"])]
    reg["spaces"][key] = {"episode": session.episode, "photos": session.photos,
                          "lock": session.lock, "at": now, "session": session}


def open_space(ep: Episode) -> str:
    """A new family space holding a copy of this page's story so far, and its photos; returns its id."""
    store, reg = timeline_store(), family_spaces()
    session = TimelineSession.create(store, "family", Episode.from_snapshot(ep.to_snapshot()), photo_store(),
                                     on_error=remember_storage_error)
    with reg["lock"]:
        _cache_space(reg, (str(store.path), session.token), session)
    return session.token


def space_signature(ep: Episode) -> tuple:
    """What another family member's change alters: the updates, the questions, who has read what."""
    return ep.seq, tuple((q["qid"], q["status"], len(q["askers"])) for q in ep.questions), tuple(sorted(ep.seen.items()))


def invite_link(sid: str, member_id: str) -> str:
    base = (st.context.url or "http://localhost:8501/").split("?")[0]
    return f"{base}?family={sid}&as={member_id}"


def get_episode() -> Episode:
    sp = current_space()
    if sp is not None:   # a family space: everyone's one timeline
        sp["episode"] = upgrade_episode(sp["episode"])
        sp["session"].bind()
        return sp["episode"]
    token, store = st.query_params.get("private"), timeline_store()
    session = st.session_state.get("persistent_private")
    if session is None or session.token != token or session.store.path != store.path:
        if token:
            session = TimelineSession.open(store, token, "private", Episode, on_error=remember_storage_error)
        else:
            existing = st.session_state.get("episode")
            ep = upgrade_episode(existing) if existing is not None else Episode(load_scenario(SCENARIO))
            session = TimelineSession.create(store, "private", ep, st.session_state.get("photos", {}),
                                             on_error=remember_storage_error)
            st.query_params["private"] = session.token
        st.session_state.persistent_private = session
        st.session_state.episode, st.session_state.photos = session.episode, session.photos
        st.session_state.setdefault("flash", None)
    st.session_state.episode, st.session_state.photos = session.episode, session.photos
    st.session_state.episode = upgrade_episode(st.session_state.episode)
    session.bind()
    return st.session_state.episode


def current_time(ep: Episode) -> dt.datetime:
    """The actual hospital-local reference clock for new source words and relative dates."""
    return dt.datetime.now(ZoneInfo(ep.patient.get("timezone") or "UTC"))


def get_extractor():
    cached = st.session_state.get("extractor")
    # Direct factory-built stand-ins are explicit injections. UI-owned closures
    # instead track their source generation, including migration of legacy caches.
    if (cached is not None and getattr(cached, "_kindred_explicit_factory", False)
            and not getattr(cached, "_kindred_app_owned", False)):
        return cached
    generation = sys.modules["episode"]._kindred_page_source_sha256
    if cached is None or getattr(cached, "_kindred_source_sha256", None) != generation:
        from llm_client import make_client   # imported only when a live model is used
        cached = llm_extractor(make_client(max_tokens=2000))   # a discharge letter has many facts
        cached._kindred_app_owned = True
        cached._kindred_source_sha256 = generation
        st.session_state.extractor = cached
    return st.session_state.extractor


def get_answerer():
    """Answers questions from the updates: the live model, checked, where one is connected; else the updates' own
    sentences (agent/episode_qa.py)."""
    if "answerer" not in st.session_state:
        from episode_qa import episode_answerer
        llm = None
        if live_model_configured():
            from llm_client import make_client
            llm = make_client(max_tokens=600, timeout_s=60, max_tries=2, max_wait_s=5)   # a family member waits: then the fallback
        st.session_state.answerer = episode_answerer(llm)
    return st.session_state.answerer


def get_photo_reader():
    if "photo_reader" not in st.session_state:
        from llm_client import make_photo_client   # CARERELAY_PHOTO_MODEL when the main model takes no images
        st.session_state.photo_reader = photo_reader(make_photo_client(max_tokens=1500, timeout_s=45, max_tries=2, max_wait_s=5))
    return st.session_state.photo_reader


def shrink(data: bytes) -> tuple[bytes, str]:
    """The photo as a JPEG of at most 1600 px on its long side, turned upright: a phone photo is several MB, and printed
    text reads as well at this size."""
    from PIL import Image, ImageOps   # installed with streamlit
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):   # transparent: onto white paper
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, "white")
        img.paste(rgba, mask=rgba.getchannel("A"))
    img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue(), "image/jpeg"


def entry_photo(e: dict) -> bytes | None:
    """The photo of an update: a demo-story file, or one added on the page."""
    if e.get("image"):
        path = ROOT / "care_cases" / e["image"]
        return path.read_bytes() if path.is_file() else None
    return photo_store().get(e["update_id"])


def photo_store() -> dict:
    """Photos added on the page: the family space's, so everyone sees them, else this session's."""
    sp = current_space()
    return sp["photos"] if sp is not None else st.session_state.setdefault("photos", {})


def next_update_id(ep: Episode) -> str:
    return f"c{sum(1 for u in ep.updates if u['update_id'].startswith('c')) + 1:02d}"


def flag_note(flag: str | None) -> str:
    return f" ({FLAG_TEXT[flag]})" if flag else ""


@contextmanager
def working(label: str, detail: str):
    """Immediate viewport hint plus an inline spinner for the actual operation.

    The placeholder is removed on success, error or a Streamlit interruption.
    It never changes drafts, schedules work or retries an external request.
    """
    hint = WORKING_HINT
    if hint is None:
        raise RuntimeError("The root waiting display has not been initialized")
    try:
        hint.markdown('<div class="cr-working" role="status" aria-live="polite">'
                      '<strong><span class="cr-working-spin" aria-hidden="true"></span>' + html.escape(label) + '</strong>'
                      '<span>' + html.escape(detail) + '</span>'
                      '<small>Please keep this page open. You do not need to press the button again.</small></div>',
                      unsafe_allow_html=True)
        with st.spinner(label, show_time=True):
            yield
    finally:
        hint.empty()


def md_safe(s: str) -> str:
    """Text shown as written in a widget label or a toast, which Streamlit reads as Markdown ($ starts maths, * emphasis)."""
    return re.sub(r"([\\`*_\[\]$~<>#|])", r"\\\1", s)


def tick_boxes(lines: list[str], prefix: str) -> list[bool]:
    """One checkbox per line; the key follows the line's words (an edited line must be ticked again) and its occurrence
    (a line that appears twice gets two boxes, not a duplicate-key error)."""
    seen: dict[str, int] = {}
    out = []
    for ln in lines:
        seen[ln] = seen.get(ln, 0) + 1
        out.append(st.checkbox(md_safe(ln), key=f"{prefix}_{hashlib.sha256(ln.encode()).hexdigest()[:12]}_{seen[ln]}"))
    return out


def add_as(ep: Episode, me: dict, upd: dict, **how) -> dict:
    """Add an update as the person viewing; it is not "new" for them if they had read everything before."""
    read_all = ep.unread(me["member_id"]) == 0
    e = add_verified(ep, upd, **how)
    if read_all:
        try:
            ep.mark_read(me["member_id"])
        except StoreError:
            # add_verified already committed the source. Failure of this separate
            # read-marker command must not turn that success into a retry draft.
            st.session_state.pop("persistence_error", None)
            st.session_state.persistence_warning = ("Your update was saved, but its read status could not be saved. "
                                                     "Reload the latest timeline before another action. Do not add this update again.")
    return e


def add_verified(ep: Episode, update: dict, **how) -> dict:
    """The single verifier factory boundary for both uploads and the demo story."""
    sp = current_space()
    lock = sp["lock"] if sp is not None and sp["episode"] is ep else st.session_state.setdefault("episode_mutation_lock", threading.RLock())
    with lock:
        return ep.add_update(update, evidence_checker=checker_from_env(), **how)


def add_story_update(ep: Episode, update: dict) -> None:
    """A callback completes the mutation before the next full page is rendered."""
    try:
        with working("Adding the next story update", "Checking this update before showing it in the timeline."):
            e = add_verified(ep, update)
    except Exception as ex:
        st.session_state.flash = f"Could not add the update ({type(ex).__name__}). Nothing was added."
    else:
        st.session_state.flash = f"Timeline updated: {display_headline(e)}" + flag_note(e["headline_flag"])


def same_as_latest(ep: Episode, me: dict, kind: str, text: str, speaker: str | None = None,
                   speaker_type: str | None = None) -> bool:
    """The newest update is this one already: a second click while the first was being read (not the same words from
    someone else, or again later)."""
    u = ep.updates[-1] if ep.updates else {}
    same = (u.get("author"), u.get("kind"), u.get("text"), u.get("speaker")) == (me["member_id"], kind, text, speaker)
    return same and (kind != "recording" or (u.get("speaker_type") or "care_team") == (speaker_type or "care_team"))


def draft_pending() -> bool:
    """Something is being added and not added yet: a photo or its reading, a recording or its words, a typed note."""
    ss = st.session_state
    return bool(ss.get("photo") or (ss.get("rec") or {}).get("bytes") or (ss.get("plan_recording") or {}).get("bytes")
                or (ss.get("rec_text") or "").strip()
                or (ss.get("note_text") or "").strip())


def discard_draft() -> None:
    """Cancel: the photo, its reading, the recording and the typed words go; the panel closes."""
    for k in (*PHOTO_STATE, "rec", "rec_seen", "rec_text", "rec_speaker", "rec_speaker_type", "rec_family_member", "rec_identity", "note_text", "plan_recording", "hosp_how", "adding", "adding_as"):
        st.session_state.pop(k, None)
    st.session_state.photo_n = st.session_state.get("photo_n", 0) + 1   # fresh upload boxes and ticks
    st.session_state.rec_n = st.session_state.get("rec_n", 0) + 1
    st.session_state.plan_n = st.session_state.get("plan_n", 0) + 1


def story_panel(ep: Episode) -> None:
    """The demo story, played from the sidebar: each click adds the next update as the primary caregiver would."""
    primary = next((m for m in ep.members.values() if m.get("primary")), None)
    who = primary["name"] if primary else "The primary caregiver"
    st.markdown("### Demo story")
    nxt = ep.next_scripted()
    if not nxt:
        st.success("The demo story is complete.")
        return
    what = f"{ICON[nxt['kind']]} {KIND_LABEL[nxt['kind']].lower()}" + (
        f" ({nxt['speaker']})" if nxt.get("speaker") else (f" of {nxt['photo_of'].lower()}" if nxt.get("photo_of") else ""))
    st.markdown(f"Next, **{who}** adds a {what}:")
    if nxt.get("image") and (ROOT / "care_cases" / nxt["image"]).is_file():
        st.image(str(ROOT / "care_cases" / nxt["image"]), width="stretch")
    st.caption(nxt["text"].replace("\n", " / "))
    st.button("Add this update", type="primary", key=f"add_{nxt['update_id']}", width="stretch",
              on_click=add_story_update, args=(ep, nxt))


def add_entry(ep: Episode, me: dict) -> None:
    """Open questions, hospital news (family or care-team words), or family plans as the current member."""
    mode = st.session_state.get("adding")
    if mode in ("paper", "recording", "ask") and st.session_state.get("adding_as") != me["member_id"]:
        discard_draft()   # the viewer changed: the checking and the words were someone else's
        mode = None
    name = first_name(ep)
    titles = {"paper": "Share my plans", "recording": "Share news from the hospital", "ask": f"Ask about {name}"}
    st.markdown(hello_html(ep, me, me.get("timezone") or ep.patient.get("timezone"), current_time(ep).isoformat()), unsafe_allow_html=True)
    if mode not in ("paper", "recording", "ask"):
        voice = transcriber_available()   # no recorder on this machine: the tiles promise only what is there
        hints = {"ask": "See the latest, or " + ("talk or type a question." if voice else "type a question.")
                        + " We answer from the updates.",
                 "recording": ("Record or type an update" if voice else "Type an update") + " from you or the care team, or photograph a paper.",
                 "paper": f"When you'll be there, how you can help, how {name} was."}
        icons = {"ask": ":material/mic:" if voice else ":material/search:", "recording": ":material/medical_services:",
                 "paper": ":material/event_available:"}
        tall, stack = st.columns(2, gap="small")   # like a phone's home screen: asking is the big one
        for col, key in ((tall, "ask"), (stack, "recording"), (stack, "paper")):
            if col.button(f"{titles[key]}\n\n{hints[key]}", key=f"add_{key}", icon=icons[key], width="stretch"):
                st.session_state.adding, st.session_state.adding_as = key, me["member_id"]
                st.rerun()
        return
    subs = {"paper": f"Let the family know when you'll be there, how you can help, or how {name} was when you visited.",
            "recording": "Share what happened in your own words, record the doctor or nurse with their permission, or photograph a paper. Check the words before adding.",
            "ask": "Ask in your own words: we show you what the updates say, word for word."}
    with st.container(key="add_panel"):
        title, close = st.columns([5, 1], vertical_alignment="center")
        title.subheader(titles[mode], anchor=False)
        title.caption(subs[mode])
        if mode == "ask":
            if close.button("Close", key="add_cancel", width="stretch"):
                discard_draft()
                st.rerun()
            ask_panel(ep, me)
            return
        if close.button("Cancel", key="add_cancel", width="stretch", help="Closes this and discards what is not added yet"):
            discard_draft()
            st.rerun()
        if mode == "paper":
            note_panel(ep, me)
        elif st.radio("What are you sharing?", HOSPITAL_HOW, key="hosp_how", horizontal=True,
                      label_visibility="collapsed") == HOSPITAL_HOW[1]:
            photo_panel(ep, me)
        else:
            recording_panel(ep, me)


def ask_panel(ep: Episode, me: dict) -> None:
    """A question about her care, typed or said, answered only from the updates (agent/episode_qa.py): the answer and
    every sentence it rests on, word for word, with who said it and when, and a related leaflet (general information).
    A question the updates do not answer can go on the list for the doctor. Answers are never added to the timeline."""
    tz = me.get("timezone") or ep.patient.get("timezone")
    if live_model_configured():
        host = endpoint_host()
        st.caption(f"Your question and the updates are sent to {host} to be answered; the answer is checked against the "
                   "updates before you see it.")
    heard = st.session_state.setdefault("qa_heard", {})   # recording id -> its words, in place (a stopped run keeps them)
    if transcriber_available():
        audio = st.audio_input("Say your question", key=f"qa_audio_{st.session_state.get('qa_n', 0)}")
        if audio is not None and audio.file_id not in heard:
            try:
                with working("Writing out your question", "Listening to your recording. You can check the words before asking."):
                    got = get_transcriber()(audio.getvalue(), Path(audio.name or "question.wav").suffix or ".wav")
                    heard[audio.file_id] = " ".join(got["text"].split())
                    if heard[audio.file_id]:   # only words go into the box (silence must not clear what was typed)
                        heard["_new"] = audio.file_id
            except Exception as ex:  # noqa: BLE001 - a missing ffmpeg or a broken recording must not break the page
                st.error(f"Could not write out the question ({type(ex).__name__}). Type it below instead.")
            else:
                if not heard[audio.file_id]:
                    st.warning("No words were heard in the recording. Try again, or type your question below.")
    if heard.get("_new"):   # before the box is drawn: the words go into it, to be checked, then asked
        st.session_state.qa_text = heard[heard.pop("_new")]
        st.caption("Check the words below, then press Find out.")
    tapped = None
    if ep.entries:
        st.caption("Or tap one:")
        with st.container(horizontal=True, key="qa_chips"):
            for i, chip in enumerate((f"When is {first_name(ep)} going home?", "Which medicines changed?",
                                      "What should we watch for?", "Who can we call?")):
                if st.button(chip, key=f"qa_chip_{i}", type="tertiary"):
                    tapped = chip
    with st.form("ask_form", border=False):
        q = st.text_input("What would you like to know?", key="qa_text",
                          placeholder=f"e.g. When is {first_name(ep)} coming home?")
        sent = st.form_submit_button("Find out", type="primary")
    answers = st.session_state.setdefault("qa", [])   # in place: an answer that arrives in a stopped run is kept
    if tapped:
        q, sent = tapped, True
    if sent and q.strip():
        try:
            with working("Looking through the updates", "Finding and checking source quotes for your question."):
                answers.insert(0, {**get_answerer()(ep, q.strip(), me["member_id"]), "asked_by": me["member_id"],
                                   "aid": len(answers) + 1})
        except Exception as ex:  # noqa: BLE001 - a model or network problem must not break the page
            st.error(f"Could not answer ({type(ex).__name__}). Try again.")
    for i, r in enumerate(answers[:3]):
        answers[i] = r = refresh(ep, r)
        st.markdown(answer_html(ep, r, tz, me["member_id"]), unsafe_allow_html=True)
        if r.get("saved_qid"):
            st.caption("✓ Saved for the doctor.")
        elif r["covered"] in ("no", "partly"):
            label = ("💬 Save it for the doctor" if r["covered"] == "no" else "Still wondering? Save it for the doctor")
            if st.button(label, key=f"qa_save_{r.get('aid', 0)}", type="secondary" if r["covered"] == "no" else "tertiary"):
                asker = r.get("asked_by") if r.get("asked_by") in ep.members else me["member_id"]
                qn, first = ep.add_question(r["question"], asker, asked_seq=r.get("asked_seq"))
                mine = first   # what happened for the person pressing
                if me["member_id"] != asker:   # pressed by someone else: they want it asked too, on the same entry
                    mine = "already" if me["member_id"] in qn["askers"] else "joined"
                    if mine == "joined":
                        qn, mine = ep.add_question(r["question"], me["member_id"], asked_seq=r.get("asked_seq"))
                r["saved_qid"] = qn["qid"]   # in place
                st.session_state.flash = save_message(first, mine, ep.members[asker]["name"], me["member_id"] == asker)
                st.rerun()


def save_message(first, mine, asker_name: str, own: bool) -> str:
    """The toast after "Save it for the doctor": first is what happened for the person who asked (False: a new entry,
    "joined", "already"), mine for the person pressing."""
    if first is False:
        return "Saved for the doctor." if own else f"Saved for the doctor, for {asker_name} and you."
    if own:
        return ("That question is already saved for the doctor; your name was added." if first == "joined"
                else "You already saved this question for the doctor.")
    if mine == "joined":
        return "That question is already saved for the doctor; your name was added."
    return (f"{asker_name} was added to your question for the doctor." if first == "joined"
            else "This question is already saved for the doctor.")


def doctor_questions(ep: Episode, me: dict, tz: str | None) -> None:
    """The questions the updates did not answer, from everyone, to ask together at the next talk with the doctor; a
    later care-team sentence that may answer one is shown, and the family marks it answered."""
    if not ep.questions:
        return
    from episode_qa import possible_answers, sentence_units
    units = sentence_units(ep)
    open_qs = sorted((q for q in ep.questions if q["status"] == "open"), key=lambda q: not q.get("auto"))   # two answers first
    st.markdown('<div class="cr"><div class="cr-side-title cr-display" role="heading" aria-level="2">🩺 Questions for the doctor'
                f'</div><span class="cr-side-sub">{len(open_qs)} waiting. Saved from everyone\'s questions, to ask together at the '
                'next visit.</span></div>', unsafe_allow_html=True)
    pairs = {p["qid"]: p for p in ep.two_answers(tz)}
    for q in open_qs:
        pair = pairs.get(q["qid"]) if q.get("auto") == "two_answers" else None
        if pair:   # settled only by the care team, or by the family saying which one the care team confirmed
            st.markdown(question_html(ep, q, tz), unsafe_allow_html=True)
            st.caption("Asked the care team? Tap the answer they confirmed.")
            with st.container(horizontal=True):
                for a in pair["answers"]:
                    if st.button(f"✓ {a['answer']} is right", key=f"qpick_{q['qid']}_{a['update_id']}", type="tertiary"):
                        ep.confirm_answer(q["qid"], a["update_id"], me["member_id"])
                        st.session_state.flash = f"Confirmed: {pair['subject'].lower()} {a['answer']}. Everyone sees it now."
                        st.rerun()
            continue
        hint = (possible_answers(ep, q, units) or [None])[0]
        st.markdown(question_html(ep, q, tz, hint), unsafe_allow_html=True)
        with st.container(horizontal=True):
            if hint and st.button("✓ That answers it", key=f"qhint_{q['qid']}", type="tertiary"):
                ep.set_answered(q["qid"], update_id=hint["update_id"], by=me["member_id"])   # the family confirmed the hint
                st.session_state.flash = "Marked answered by that update."
                st.rerun()
            if st.button("✓ Answered", key=f"qdone_{q['qid']}", type="tertiary"):
                ep.set_answered(q["qid"], by=me["member_id"])
                st.session_state.flash = "Marked answered. You can reopen it under Answered."
                st.rerun()
    recording_open = st.session_state.get("adding") == "recording"   # its panel already lists the questions
    if open_qs and not recording_open and st.button("🎙️ Record the doctor's answers", key="q_record", width="stretch"):
        if draft_pending() or st.session_state.get("adding") == "paper":   # a typed note is not sent until Add note
            st.session_state.flash = "Finish or cancel what you are adding first, then record the doctor's answers."
        else:
            discard_draft()
            st.session_state.adding, st.session_state.adding_as = "recording", me["member_id"]
            st.session_state.rec_speaker_type = "Doctor / nurse"
        st.rerun()
    answered = [q for q in ep.questions if q["status"] == "answered"]
    if answered:
        with st.expander(f"Answered ({len(answered)})"):
            for q in answered:
                st.markdown(question_html(ep, q, tz), unsafe_allow_html=True)
                if st.button("Reopen", key=f"qopen_{q['qid']}", type="tertiary"):
                    ep.set_answered(q["qid"], answered=False)
                    st.rerun()


CHECK_LINE = re.compile(   # lines a misread or mishearing would change the meaning of: numbers, stop / continue,
    r"\d|\b(stop|stopped|continue|start|increase|decrease|reduce|instead|until|unreadable|"   # negations and conditions,
    r"not|no|never|don't|can't|cannot|won't|without|if|unless|before|after|only|"            # days and times
    r"today|tonight|tomorrow|yesterday|morning|afternoon|evening|night|noon|midnight|week|weeks|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b", re.I)


def needs_line_check(line: str) -> bool:
    """Use Whisper's critical-word checks too, including worded doses and frequencies."""
    return bool(CHECK_LINE.search(line) or asr_check_reasons(line))


def accept_photo(data: bytes, pid: str) -> bool:
    """Keep a photo for reading: upright, at most 1600 px, as JPEG (the copy the caregiver checks and the model reads)."""
    try:
        with working("Preparing your photo", "Preparing a clear copy so you can check it against the text."):
            sent, _ = shrink(data)
    except Exception:  # noqa: BLE001 - not an image Pillow can open (a renamed PDF or HEIC, a truncated upload)
        # A rejected replacement must not leave the previous paper available to add.
        for key in ("photo", *READING_STATE):
            st.session_state.pop(key, None)
        st.error("This file could not be opened as a photo. Take the photo again, or use a JPG or PNG.")
        return False
    st.session_state.photo = {"bytes": sent, "id": pid}
    for k in READING_STATE:   # not photo_upload_seen: it says which upload is already handled
        st.session_state.pop(k, None)
    return True


def added_already(ep: Episode, r: dict | None, text: str) -> dict | None:
    """The update this photo reading was already added as (same image, same checked text), if any."""
    if not r:
        return None
    return next((u for u in ep.updates if (u.get("reading") or {}).get("image_sha256") == r.get("image_sha256")
                 and u.get("text") == text), None)


def said_when(ep: Episode, key: str) -> str | None:
    """When the words were said or written, if earlier than now: a photo of Wednesday's letter added on Friday goes in
    as Wednesday's source, so anything the care team said after it still stands. None: actual now."""
    if not st.checkbox("This was said or written earlier", key=f"{key}_earlier",
                       help="For example a photo of Wednesday's letter, added on Friday. Anything said after it still stands."):
        return None
    tz = ZoneInfo(ep.patient.get("timezone") or "UTC")
    now = current_time(ep)
    day_col, time_col = st.columns(2)
    day = day_col.date_input("Day", value=now.date(), max_value=now.date(), key=f"{key}_day", format="DD/MM/YYYY")
    clock = time_col.time_input("Time, at the hospital", value=dt.time(9, 0), key=f"{key}_time", step=900)
    at = dt.datetime.combine(day, clock, tzinfo=tz)
    if at > now:
        st.caption("That source time is in the future. Choose when the words were said, or leave this unchecked for now.")
        return None
    return at.isoformat(timespec="seconds")


def photo_panel(ep: Episode, me: dict) -> None:
    """Photo -> the vision model reads the text -> the caregiver checks every line with a number or a stop / continue
    against the photo and corrects any misread -> added; facts are read from the checked text. Lines the caregiver
    changed are her words, so their facts show as reported by family."""
    who = me["name"]
    if not live_model_configured():
        st.info("Reading a photo needs a vision model (for example on AMD Token Factory); none is connected in this "
                "deployment. In the demo story, the photo of the discharge medication list shows a recorded reading.")
        return
    host = endpoint_host()
    st.warning(f"The photo is sent to {host} to be read; a hosted service such as Token Factory keeps prompts for about 2 "
               "days. Use the sample or a fictional paper only: never photograph a real patient's document. English papers "
               "only in this prototype.")
    n = st.session_state.get("photo_n", 0)
    # Writing st.session_state is itself a point where Streamlit stops a run when the user clicks during a slow call, so
    # results of slow calls go into these objects in place, and the next run picks them up.
    photos = photo_store()
    lock = st.session_state.setdefault("photo_add_lock", threading.Lock())
    camera = st.camera_input("Take a photo", key=f"photo_camera_{n}")
    st.caption("No camera available, or prefer an existing photo? Upload it below.")
    up = st.file_uploader("Or upload a photo of the paper", type=["jpg", "jpeg", "png", "webp"],
                          key=f"photo_upload_{n}")
    seen, camera_seen = st.session_state.get("photo_upload_seen"), st.session_state.get("photo_camera_seen")
    fresh_camera = camera is not None and camera.file_id != camera_seen
    fresh_upload = up is not None and up.file_id != seen
    # Remember both values together: when both change in one rerun, the new camera
    # image wins and the older upload cannot replace it on the following rerun.
    st.session_state.photo_upload_seen = up.file_id if up is not None else None
    st.session_state.photo_camera_seen = camera.file_id if camera is not None else None
    if fresh_camera:
        accept_photo(camera.getvalue(), f"camera:{camera.file_id}")
    elif fresh_upload:
        accept_photo(up.getvalue(), up.file_id)
    elif ((up is None and seen is not None and (st.session_state.get("photo") or {}).get("id") == seen)
          or (camera is None and camera_seen is not None
              and (st.session_state.get("photo") or {}).get("id") == f"camera:{camera_seen}")):
        for k in ("photo", *READING_STATE):
            st.session_state.pop(k, None)
    if SAMPLE_PHOTO.is_file():
        if st.button("Use the sample photo (discharge medication list)"):
            accept_photo(SAMPLE_PHOTO.read_bytes(), "sample")
    photo = st.session_state.get("photo")
    if not photo:
        return
    if photo.get("reading") is not None:   # a read that finished while the page was rerunning
        st.session_state.photo_reading = photo["reading"]
        st.session_state.photo_text = photo["reading"]["text"]
        photo.pop("reading", None)
    done = photo.get("add_started") and added_already(ep, st.session_state.get("photo_reading"),
                                                       (st.session_state.get("photo_text") or "").strip())
    if done:   # an Add that finished while the page was rerunning: finish the clean-up it could not do
        photos.setdefault(done["update_id"], photo["bytes"])
        for k in PHOTO_STATE:
            st.session_state.pop(k, None)
        st.session_state.photo_n = n + 1
        st.session_state.flash = "The photo was added to the timeline."
        st.session_state.adding = None
        st.rerun()
    if photo.get("add_started"):   # an Add that stopped before the update went in: it may be pressed again
        photo.pop("add_started", None)
    st.image(photo["bytes"], width="stretch",
             caption="Check the text below against this photo (open it full screen to zoom).")
    r = st.session_state.get("photo_reading")
    model_text = (r or {}).get("text", "")
    edited = bool(r) and (st.session_state.get("photo_text") or "").strip() != model_text.strip()
    label = ("Read the text on the photo" if not r else
             "Discard my corrections and read again" if edited else "Read again")
    if st.button(label, type="secondary" if r else "primary"):
        try:
            with working("Reading the words on your photo", "Copying the document text. You will check and correct it before adding."):
                got = get_photo_reader()(photo["bytes"], "image/jpeg")
                if got["text"].strip():
                    photo["reading"] = got   # in place (see above); shown from the next run on
        except Exception as ex:  # noqa: BLE001 - a model or network problem must not break the page
            st.error(f"Could not read the photo ({type(ex).__name__}: {str(ex)[:200]}). Try again, or type the text in "
                     "the other tab." + (" Your text below is kept." if r else ""))
        else:
            if not got["text"].strip():
                st.error("The model returned no text. Try again, or type the text in the other tab.")
            else:
                st.rerun()
    r = st.session_state.get("photo_reading")
    if not r:
        return
    if r.get("finish_reason") == "length":
        st.warning("The reading stops before the end of the paper: add the missing lines by hand.")
    st.markdown("**1. Check the source text**")
    st.caption("Before adding: correct the text, tick each listed line, then enter a document title in step 3.")
    st.text_area("Text read from the photo: correct anything misread.", key="photo_text", height=220)
    st.caption(f"Read by {r.get('model') or 'the vision model'}" + (f" in {r['latency_s']:.1f} s." if r.get("latency_s") else "."))
    text = (st.session_state.get("photo_text") or "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    to_check = [ln for ln in lines if needs_line_check(ln)]
    st.markdown("**2. Compare and tick each line**")
    if to_check:
        st.markdown("**Tick each line once you have compared it with the photo** (names, numbers, units, stop / continue):")
    ticked = tick_boxes(to_check, f"photo_ok_{n}")
    said_at = said_when(ep, f"photo_{n}")
    with st.container(border=True, key="photo_finish"):
        st.markdown("**3. Finish and add to timeline**")
        st.text_input("Document title (required)", key="photo_of_text", placeholder="e.g. Medication list, discharge letter")
        st.caption("Give the paper a short title, for example Medication list or discharge letter. This is required before adding.")
        what = (st.session_state.get("photo_of_text") or "").strip()
        blocked = []
        if not what:
            blocked.append("Enter a document title in the box above.")
        if "[unreadable]" in text:
            blocked.append("Replace [unreadable] with the words from the paper, or delete that line.")
        if not text:
            blocked.append("Source text is empty. Enter the words from the paper in step 1.")
        remaining = len(ticked) - sum(ticked)
        if remaining:
            blocked.append(f"{remaining} line(s) still need checking against the photo in step 2.")
        if blocked:
            st.caption("Add is not available yet:\n\n" + "\n".join(f"- {reason}" for reason in blocked))
        else:
            st.caption("Ready to add your photo and checked words to the family timeline.")
        add_clicked = st.button("Add to the timeline", type="primary", disabled=bool(blocked))
    if add_clicked:
        model_lines = [ln.strip() for ln in model_text.splitlines() if ln.strip()]
        changed = [ln for ln in lines if ln not in model_lines]
        with lock:   # one Add at a time in this session: a second click waits for the first, then finds it
            dup = added_already(ep, r, text)
            if dup is None:
                uid = next_update_id(ep)
                photos[uid] = photo["bytes"]   # in place, before the slow call
                photo["add_started"] = True
                upd = {"update_id": uid, "at": said_at or current_time(ep).isoformat(timespec="seconds"), "kind": "photo",
                       "author": me["member_id"], "photo_of": what, "text": text, "image": None,
                       "reading": {"method": "model", "model": r.get("model"), "checked_by": who,
                                   "confirmed_lines": len(to_check), "model_text": model_text, "changed_lines": changed,
                                   "removed_lines": [ln for ln in model_lines if ln not in lines],
                                   "image_sha256": r.get("image_sha256")}}
                try:
                    with working("Checking your photo for the timeline", "Reading the checked words and checking statements against their source."):
                        ex = get_extractor()
                        e = add_as(ep, me, upd, extractor=ex)
                except Exception as err:  # noqa: BLE001 - a model or network problem must not break the page
                    photos.pop(uid, None)
                    photo.pop("add_started", None)
                    st.session_state.flash = f"Could not read facts from the photo's text ({type(err).__name__}); nothing was added."
                    st.rerun()
        for k in PHOTO_STATE:
            st.session_state.pop(k, None)
        st.session_state.photo_n = n + 1   # a fresh upload box and fresh ticks
        st.session_state.adding = None
        st.session_state.flash = ("This photo was already added." if dup is not None else
                                  f"Timeline updated: {display_headline(e)}" + flag_note(e["headline_flag"]) if ex.log and ex.log[-1]["parsed"]
                                  else "The model's reply could not be read, so the photo was added without facts.")
        st.rerun()


class _PlanExtractionTimeout(Exception):
    """A timeout raised inside the extractor, before any journal commit."""


def add_typed(ep: Episode, me: dict, kind: str, text: str, extra: dict | None = None, *, show_working: bool = True) -> bool:
    """Add a note or a recording's words as the person viewing (facts from the live model when one is connected).
    True once it is in the timeline, or already was; False if nothing was added (the caller keeps the words)."""
    extra = extra or {}
    with st.session_state.setdefault("typed_add_lock", threading.Lock()):   # a second click waits, then finds it
        reading = extra.get("reading") or {}
        duplicate_audio = reading.get("audio_source_id") and any(
            u.get("author") == me["member_id"] and u.get("topic") == "plan"
            and (u.get("reading") or {}).get("audio_source_id") == reading["audio_source_id"]
            and (u.get("reading") or {}).get("audio_sha256") == reading.get("audio_sha256") for u in ep.updates)
        if duplicate_audio or (not reading.get("audio_source_id") and same_as_latest(ep, me, kind, text, extra.get("speaker"), extra.get("speaker_type"))):
            st.session_state.flash = "That update was already added."
            return True
        upd = {"update_id": next_update_id(ep), "at": current_time(ep).isoformat(timespec="seconds"), "kind": kind,
               "author": me["member_id"], "text": text, **extra}
        own_plan = (upd["kind"] == "note" and upd.get("topic") == "plan" and upd["author"] == me["member_id"])
        try:
            if live_model_configured():
                with (working("Adding your update to the timeline", "Reading the words and checking statements against their source.")
                      if show_working else nullcontext()):
                    ex = get_extractor()
                    if own_plan:
                        from llm_client import is_timeout   # also a connect timeout, which urllib wraps in a URLError
                        before = ep.to_snapshot()

                        def extract_plan(update, episode):
                            try:
                                return ex(update, episode)
                            except Exception as err:  # noqa: BLE001 - only a timeout is converted; the rest is re-raised
                                if not is_timeout(err):
                                    raise
                                # Storage, validation and verifier failures occur outside
                                # this boundary and must never trigger a second add.
                                raise _PlanExtractionTimeout() from err

                        try:
                            e = add_as(ep, me, upd, extractor=extract_plan)
                        except _PlanExtractionTimeout:
                            if (ep.to_snapshot() != before or any(u["update_id"] == upd["update_id"] for u in ep.updates)):
                                message = ("Your plan could not be confirmed as saved. Reload the latest timeline and check it "
                                           "before submitting again. Your words are kept.")
                                st.session_state.plan_save_feedback = {"member": me["member_id"], "kind": "error", "message": message}
                                st.session_state.flash = message
                                return False
                            # The journal prepares extraction before committing. Preserve
                            # the same source ID, receipt and ASR metadata; no API retry.
                            add_as(ep, me, upd, facts=[])
                            message = "Your plan was saved. AI details are temporarily unavailable."
                            st.session_state.plan_save_feedback = {"member": me["member_id"], "kind": "warning", "message": message}
                            st.session_state.flash = message
                            return True
                    else:
                        e = add_as(ep, me, upd, extractor=ex)
                st.session_state.flash = (f"Timeline updated: {display_headline(e)}" + flag_note(e["headline_flag"]) if ex.log and ex.log[-1]["parsed"] else
                                          "The model's reply could not be read, so the update was added without facts.")
            else:
                add_as(ep, me, upd, facts=[])
                st.session_state.flash = "Added to the timeline. No model is connected, so no facts were read from it."
        except Exception as ex:  # noqa: BLE001 - a model or network problem must not break the page
            st.session_state.flash = f"Could not read facts from the update ({type(ex).__name__}); nothing was added. Your words are kept."
            if own_plan:
                st.session_state.plan_save_feedback = {
                    "member": me["member_id"], "kind": "error",
                    "message": (f"Could not save your plan ({type(ex).__name__}). Your words are kept. "
                                "Reload the latest timeline and check it before trying again."),
                }
            return False
        st.session_state.pop("plan_save_feedback", None)
    return True


HOSPITAL_HOW = ("🎙️ Record or type an update", "📷 Photograph a paper")
SPEAKER_TYPES = ("Me / a family member", "Doctor / nurse")
PLAN_STARTS = (("I'm coming…", "I'll be there on "), ("I can help…", "I can help with "), ("I just visited…", "I just visited. "))


def start_plan(words: str) -> None:
    st.session_state.note_text = words


def note_panel(ep: Episode, me: dict) -> None:
    """A plan or a few words for the family: when they will be there, how they can help, how she was. It shows under
    Who's coming, who's helping, and in the timeline as reported by family."""
    st.caption(f"Dates and times in your plan use the hospital's time ({ep.patient.get('timezone') or 'UTC'}).")
    spoken_plan_panel(ep, me)
    starts = st.columns(len(PLAN_STARTS))
    for col, (label, words) in zip(starts, PLAN_STARTS):
        col.button(label, key=f"plan_start_{label}", type="tertiary", on_click=start_plan, args=(words,))
    with st.form("note_form", border=False):   # not cleared on submit: if the add fails, the words stay
        text = st.text_area("Your plan or note", key="note_text", height=90, label_visibility="collapsed",
                            placeholder="e.g. I arrive Wednesday morning and can do the evening visits.")
        sent = st.form_submit_button("Share with the family", type="primary")
    st.caption("In your own words: the family sees it under Who's coming, who's helping, and in the timeline as reported by family.")
    if sent and text.strip():
        if add_typed(ep, me, "note", text.strip(), {"topic": "plan"}):
            st.session_state.adding = None   # the panel closes; the box is empty next time
        st.rerun()


def spoken_plan_panel(ep: Episode, me: dict) -> None:
    """One explicit save writes a microphone recording out and shares the member's own plan."""
    if not transcriber_available():
        st.info("Recording a plan needs speech-to-text on this deployment. You can type your plan below.")
        return
    n, member = st.session_state.get("plan_n", 0), me["member_id"]
    st.caption("Record your plan in English, stop, then select Save my plan.")
    audio = st.audio_input("Record your plan in English", key=f"plan_audio_{member}_{n}")
    draft = st.session_state.get("plan_recording")
    if audio is None:
        st.session_state.pop("plan_recording", None)
        draft = None
    elif not draft or (draft.get("id"), draft.get("member")) != (audio.file_id, member):
        data = audio.getvalue()
        draft = {"id": audio.file_id, "member": member, "bytes": data,
                 "sha256": hashlib.sha256(data).hexdigest(), "suffix": Path(audio.name or "plan.wav").suffix or ".wav",
                 "at": current_time(ep).isoformat(timespec="seconds")}
        st.session_state.plan_recording = draft
    if not st.button("Save my plan", key="plan_save", type="primary", disabled=not draft):
        return
    # The fingerprint belongs to the member and this recording. It also covers
    # a completed add whose Streamlit rerun interrupted the normal cleanup.
    existing = next((u for u in ep.updates if u.get("author") == member and u.get("topic") == "plan"
                     and (u.get("reading") or {}).get("audio_source_id") == draft["id"]
                     and (u.get("reading") or {}).get("audio_sha256") == draft["sha256"]), None)
    if existing is None:
        try:
            with working("Saving your spoken plan", "Writing out your recording and adding your plan to the family timeline."):
                got = draft.get("transcript")
                if got is None:
                    got = get_transcriber()(draft["bytes"], draft["suffix"])
                    if not (got.get("text") or "").strip():
                        st.warning("No words were heard. Record your plan again.")
                        return
                    draft["transcript"] = got
                text = got["text"].strip()
                saved = add_typed(ep, me, "note", text, {"topic": "plan", "at": draft["at"], "reading": {
                    "method": "asr", "model": got.get("model"), "model_text": text,
                    "changed_lines": [], "removed_lines": [], "audio_sha256": draft["sha256"],
                    "audio_source_id": draft["id"]}}, show_working=False)
                if not saved:
                    st.error(st.session_state.get("flash") or "Could not save your spoken plan. Try again.")
                    return
        except Exception as ex:  # a failed transcription keeps this recording available to retry
            st.error(f"Could not save your spoken plan ({type(ex).__name__}). Your recording is kept; try Save my plan again.")
            return
    else:
        st.session_state.flash = "That spoken plan was already saved."
    st.session_state.pop("plan_recording", None)
    st.session_state.plan_n = n + 1
    st.session_state.adding = None
    st.rerun()


def transcriber_available() -> bool:
    import asr_local
    return "transcriber" in st.session_state or not asr_local.missing()


def get_transcriber():
    """audio bytes, file suffix -> {"text", "model", "latency_s"}: Whisper on this machine (agent/asr_local.py;
    CARERELAY_ASR_MODEL, default base.en, quick on a CPU), one line per segment."""
    if "transcriber" not in st.session_state:
        import asr_local
        st.session_state.transcriber = asr_local.transcriber()
    return st.session_state.transcriber


def recording_identity(ep: Episode, me: dict, prefix: str, source: dict | None = None) -> tuple[str, str, bool]:
    """Resolve the speaker separately from the family member sharing the source."""
    source = source or {}
    default_type = 0 if not source or source.get("speaker_type") == "family" else 1
    choice = st.radio("Who is speaking in this recording?", SPEAKER_TYPES, index=default_type,
                      key=f"{prefix}_speaker_type", horizontal=True)
    if choice == SPEAKER_TYPES[0]:
        members = list(ep.members)
        selected = next((mid for mid in members if ep.members[mid].get("name") == source.get("speaker")), me["member_id"])
        member = st.selectbox("Family member speaking", members, index=members.index(selected),
                              format_func=lambda mid: ep.members[mid].get("name", mid) +
                              (f" ({ep.members[mid]['relation']})" if ep.members[mid].get("relation") else ""),
                              key=f"{prefix}_family_member")
        return "family", ep.members[member].get("name", member), member != me["member_id"]
    speaker = st.text_input("Doctor or nurse's name or role", value=source.get("speaker") or "",
                            key=f"{prefix}_speaker", placeholder="e.g. Ward nurse, orthopaedic surgeon")
    return "care_team", speaker.strip(), True


def recording_panel(ep: Episode, me: dict) -> None:
    """A recording -> written out (Whisper, where installed) or typed -> every line with a number or a stop / continue
    checked against the recording -> added; lines changed by hand are the family's words, as with a photo."""
    # A draft from the older, clinician-only form keeps its declared source on
    # first render. Do not discard its recording or silently call it family speech.
    if ("rec_identity" not in st.session_state and "rec_speaker_type" not in st.session_state
            and ((st.session_state.get("rec") or {}).get("bytes") or st.session_state.get("rec_text"))):
        st.session_state.rec_speaker_type = SPEAKER_TYPES[1]
    if (st.session_state.get("rec") or {}).get("bytes"):
        st.caption("Changing the speaker starts a new draft and clears this unsaved recording and text.")
    elif (st.session_state.get("rec_text") or "").strip():
        st.caption("Changing the speaker starts a new draft and clears this unsaved text.")
    speaker_type, speaker, another_person = recording_identity(ep, me, "rec")
    family = speaker_type == "family"
    identity = (me["member_id"], speaker_type, st.session_state.get("rec_family_member") if family else None, speaker)
    previous_identity = st.session_state.get("rec_identity")
    if previous_identity is not None and previous_identity != identity:
        # Identity widgets above keep the new selection. Everything whose checks
        # belonged to the previous speaker is replaced before its widgets exist.
        for key in ("rec", "rec_seen"):
            st.session_state.pop(key, None)
        st.session_state.rec_text = ""   # send an explicit reset to the existing textarea, not just its backend state
        st.session_state.rec_n = st.session_state.get("rec_n", 0) + 1
        st.info("Speaker changed. The previous recording and words were cleared. Record or type this speaker's update.")
    st.session_state.rec_identity = identity
    n = st.session_state.get("rec_n", 0)
    rec = st.session_state.setdefault("rec", {})   # slow results belong to this identity and capture generation
    if previous_identity is None and rec.get("bytes"):
        rec["preserve_legacy_capture"] = True   # its old widget may no longer supply the recording after a reload
    st.caption(f"Sharing as {me['name']}" + (f" ({me['relation']})." if me.get("relation") else "."))
    open_qs = sorted((q for q in ep.questions if q["status"] == "open"), key=lambda q: not q.get("auto"))   # two answers first
    if open_qs and not family:   # at the talk with the doctor: the family's questions to ask while recording
        st.markdown("**Questions to ask** (from the family's list):\n" + "\n".join(f"- {md_safe(q['text'])}" for q in open_qs))
    if not transcriber_available():   # no recorder then: it would keep audio that nothing writes out
        import asr_local
        st.info("Speech-to-text is not connected in this deployment, so type the update below. "
                f"(This machine is missing {', '.join(asr_local.missing())}; scripts/check_whisper.py says how to "
                "install it, then the recorder appears here.)")
    agreed = True
    if not transcriber_available():
        if another_person:
            st.caption("Let the speaker know that what they said will be shared with the family.")
    else:
        if another_person:
            st.markdown("**Before you record, ask:** “May I record this, so my family can hear exactly what you said?”")
            consent_key = f"rec_family_consent_{speaker}_{n}" if family else f"rec_consent_{n}"
            agreed = st.checkbox("They agreed to be recorded", key=consent_key)
        else:
            st.caption("Record your own update about what happened. Ask permission before including anyone else's voice.")
        st.caption("Fictional or role-play recordings only in this prototype." if agreed else
                   "The recorder appears once they agree. If they would rather not, type what they said below.")
        audio = st.audio_input("Record", key=f"rec_audio_{n}") if agreed else None
        upload = (st.file_uploader("Or a recording from your phone", type=["wav", "mp3", "m4a", "ogg", "webm"],
                                   key=f"rec_upload_{n}") if agreed else None)
        given = [x for x in (audio, upload) if x is not None]
        given_ids = {x.file_id for x in given}
        if rec.get("id") in given_ids:
            rec.pop("preserve_legacy_capture", None)   # normal removal works once its widget has supplied it again
        seen = st.session_state.setdefault("rec_seen", [])   # every recording handled, so the other one is not "new" each run
        fresh = [x for x in given if x.file_id not in seen]
        if fresh or (rec.get("id") and rec["id"] not in given_ids
                     and not rec.get("preserve_legacy_capture")):
            # a new recording (the newest), or the one in use was removed (its text held the hand-changed lines): start over
            src = (fresh or given or [None])[-1]
            seen.extend(x.file_id for x in fresh)
            rec.clear()
            st.session_state.pop("rec_text", None)
            if src is not None:
                rec.update(id=src.file_id, bytes=src.getvalue(), suffix=Path(src.name or "recording.wav").suffix or ".wav")
    if rec.get("add_started"):   # an Add whose run was stopped: finish its clean-up, or let it be pressed again
        rec.pop("add_started", None)
        if same_as_latest(ep, me, "recording", (st.session_state.get("rec_text") or "").strip(),
                          speaker, speaker_type):
            clear_recording()
            st.session_state.flash = "The recording was added to the timeline."
            st.rerun()
    if rec.get("transcript") and not rec.get("shown"):   # written out in a run that was stopped: show it now
        st.session_state.rec_text, rec["shown"] = rec["transcript"]["text"], True
    if rec.get("bytes"):
        got = rec.get("transcript")
        edited = bool(got) and (st.session_state.get("rec_text") or "").strip() != got["text"].strip()
        label = ("Write out the recording" if not got else
                 "Discard my corrections and write it out again" if edited else "Write it out again")
        if st.button(label, type="secondary" if got else "primary"):
            try:
                with working("Writing out your recording", "Listening to the recording. You will check the words before adding."):
                    out = get_transcriber()(rec["bytes"], rec["suffix"])
                    if out["text"].strip():
                        rec["transcript"], rec["shown"] = out, False   # in place, before the spinner ends (see photo_panel)
            except Exception as ex:  # noqa: BLE001 - a missing ffmpeg or a broken file must not break the page
                st.error(f"Could not write out the recording ({type(ex).__name__}: {str(ex)[:200]}). Type what was said below.")
            else:
                if out["text"].strip():
                    st.rerun()
                st.error("No speech was found in the recording. Type what was said below.")
    got = rec.get("transcript")
    st.text_area(("Your family's update" if family else "What was said, in their words") + (": check it against the recording and correct anything misheard" if got else ""),
                 key="rec_text", height=160)
    if got:
        st.caption(f"Written out by {got.get('model') or 'speech-to-text'}" +
                   (f" in {got['latency_s']:.1f} s." if got.get("latency_s") else "."))
    st.caption("This is a family report about what happened. It does not replace the care team's statements." if family else
               "These are the doctor or nurse's words. Lines you change by hand are marked as reported by family.")
    text = (st.session_state.get("rec_text") or "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    to_check = [ln for ln in lines if needs_line_check(ln)] if got else []
    if to_check:
        st.markdown("**Tick each line once you have listened to it again** (names, numbers, times, stop / continue):")
    ticked = tick_boxes(to_check, f"rec_ok_{n}")
    blocked = ("the text is empty" if not text else "say who is speaking" if not speaker.strip()
               else "the speaker has not agreed to this recording" if rec.get("bytes") and not agreed
               else f"{len(ticked) - sum(ticked)} line(s) not ticked yet" if not all(ticked) else "")
    said_at = said_when(ep, f"rec_{n}")
    if blocked:
        st.caption(f"Add is not available yet: {blocked}.")
    if st.button("Add to the timeline", type="primary", disabled=bool(blocked), key="rec_add"):
        extra = {"speaker": speaker.strip(), "speaker_type": speaker_type, **({"at": said_at} if said_at else {})}
        if got:
            model_lines = [ln.strip() for ln in got["text"].splitlines() if ln.strip()]
            extra["reading"] = {"method": "asr", "model": got.get("model"), "checked_by": me["name"], "confirmed_lines": len(to_check),
                                "model_text": got["text"], "changed_lines": [ln for ln in lines if ln not in model_lines],
                                "removed_lines": [ln for ln in model_lines if ln not in lines]}
        rec["add_started"] = True   # in place: a stopped run finishes the clean-up next time
        if add_typed(ep, me, "recording", text, extra):
            clear_recording()
        st.rerun()   # on failure the recording, the words and the ticks stay


def clear_recording() -> None:
    for k in ("rec", "rec_seen", "rec_text", "rec_speaker", "rec_speaker_type", "rec_family_member", "rec_identity", "adding", "adding_as"):
        st.session_state.pop(k, None)
    st.session_state.rec_n = st.session_state.get("rec_n", 0) + 1   # a fresh recorder and fresh ticks


def main() -> None:
    global WORKING_HINT
    st.set_page_config(page_title=f"{PRODUCT} family timeline", layout="wide")
    # Keep fixed-position feedback outside the frosted/filtered content panels.
    # Reusing this public placeholder also works in callbacks before the next render.
    WORKING_HINT = st.empty()
    # one <style> block: markdown reads anything after a block's closing tag as text (an underscore becomes emphasis)
    look = st.query_params.get("look", "frostsky")   # frostsky: chosen by Holly on 2026-10-16 (?look=sunlit gives the earlier one)
    look = look if look in LOOKS else "frostsky"
    if st.session_state.get("text_size") not in TEXT_SIZES:   # first visit, or the choice was tapped off: from the address, else A
        st.session_state.text_size = st.query_params.get("text") if st.query_params.get("text") in TEXT_SIZES else "A"
    scale = TEXT_SIZES[st.session_state.text_size]
    st.markdown(CSS.replace("</style>", ":root{" + LOOKS[look] + f";--cr-fs:{scale}" + "}html{font-size:calc(16px*var(--cr-fs,1))}"
                            + PAGE_CSS + LOOK_CSS.get(look, "") + "</style>"), unsafe_allow_html=True)
    if st.session_state.get("persistence_error"):
        storage_error(st.session_state.persistence_error)
    elif st.session_state.get("persistence_warning"):
        storage_error(st.session_state.persistence_warning, warning=True)
    try:
        render_saved_timeline()
    except StoreError as ex:
        st.error(str(ex))
        st.stop()


def render_saved_timeline() -> None:
    sp = current_space()
    if st.query_params.get("family") and sp is None:
        for k in ("family", "as"):
            st.query_params.pop(k, None)
        st.session_state.flash = ("That family link has ended or cannot be found. This is a private demo; "
                                  "check the original link or invite the family again. No saved family timeline was changed.")
    if sp is None:
        get_episode()
        st.session_state.persistent_private.refresh(Episode)
        page(None)
    else:
        acquired = False
        try:
            acquired = sp["lock"].acquire(blocking=False)
            if not acquired:
                with working("Waiting for the family timeline", "Another family update is being processed. Your action will continue when it finishes."):
                    acquired = sp["lock"].acquire()
            sp["session"].refresh(Episode)
            page(sp)
            st.session_state.space_sig = space_signature(sp["episode"])
        finally:
            if acquired:
                sp["lock"].release()
    family_watch()


@st.fragment(run_every=8)
def family_watch() -> None:
    """In a family space: when someone else adds, asks or answers something, show it (a check every 8 s). Not while this
    person is adding something themself; they see it once they are done."""
    sp = current_space()
    if sp is None or st.session_state.get("adding") or draft_pending():
        return
    try:
        if not sp["lock"].acquire(blocking=False):
            return   # another update is running: keep the existing view and check on the next poll
        try:
            sig = space_signature(sp["episode"])
            revision = sp["session"].store.load(sp["session"].token, "family").revision
        finally:
            sp["lock"].release()
    except StoreError as ex:
        st.error(str(ex))
        return
    except RuntimeError:   # being changed by another family member at this very moment: look again next time
        return
    if sig != st.session_state.get("space_sig") or revision != sp["session"].revision:
        st.rerun(scope="app")


def family_panel(ep: Episode, sp: dict | None, me: dict) -> None:
    """Bring the family into one place: invite links, one per person, to the same timeline."""
    st.divider()
    st.markdown("### Family space")
    if sp is None:
        st.caption("Bring the family together: each person gets their own link to this same timeline, to see what is "
                   "happening, ask, and add their own news.")
        if st.button("👪 Invite the family", key="invite_family", width="stretch"):
            sid = open_space(ep)
            st.query_params.pop("private", None)
            st.query_params["family"], st.query_params["as"] = sid, me["member_id"]
            st.session_state.flash = "The family space is ready: send each person their own link from the side panel."
            st.rerun()
        return
    sid = st.query_params.get("family")
    st.caption("Anyone with a family link can view and change this timeline, choose a family identity, or restart the story. "
               "Send links only to people you trust. Saved updates survive refresh and server restart while the host keeps its storage.")
    for m in ep.members.values():
        st.markdown(f"**{md_safe(m.get('name', m['member_id']))}**" + (" (you)" if m["member_id"] == me["member_id"] else "")
                    + (f" · {md_safe(m['relation'])}" if m.get("relation") else ""))
        st.code(invite_link(sid, m["member_id"]), language=None)
    if st.button("Leave the family space", key="leave_space"):
        for k in ("family", "as"):
            st.query_params.pop(k, None)
        private_session = st.session_state.get("persistent_private")
        if private_session is not None and private_session.store.path == timeline_store().path:
            st.query_params["private"] = private_session.token
        st.rerun()


def page(sp: dict | None) -> None:
    ep = get_episode()
    members = list(ep.members.values())
    if not members:
        st.error("This episode has no family members to show it to.")
        st.stop()
    with st.sidebar:
        with st.expander(f"About {PRODUCT}"):
            with st.container(key="about_kindredrelay"):
                st.markdown(f"**{TAGLINE}**")
                st.write(ABOUT)
                release = ROOT / "RELEASE_VERSION.txt"
                if release.is_file():
                    st.caption(release.read_text(encoding="utf-8").strip())
        story_panel(ep)
        st.divider()
        if st.button("Restart the story for everyone" if sp is not None else "Restart the demo"):
            session = sp["session"] if sp is not None else st.session_state.persistent_private
            session.replace(Episode(load_scenario(SCENARIO)))
            if sp is not None:
                sp["episode"], sp["photos"] = session.episode, session.photos
            for k in ("episode", "extractor", "photo_reader", "answerer", "qa", "qa_text", "qa_heard", "flash", "note_text", "photos",
                      "photo_add_lock", "typed_add_lock", "plan_save_feedback",
                      "adding", "adding_as", "rec", "rec_seen", "rec_text", "rec_speaker", "rec_speaker_type", "rec_family_member", "rec_identity", "plan_recording", *PHOTO_STATE):
                st.session_state.pop(k, None)
            st.session_state.photo_n = st.session_state.get("photo_n", 0) + 1   # an empty upload box
            st.session_state.rec_n = st.session_state.get("rec_n", 0) + 1
            st.session_state.plan_n = st.session_state.get("plan_n", 0) + 1
            st.rerun()
        st.caption(f"Fictional composite. Every fact is quoted from an update; {PRODUCT} does not diagnose or give medical advice.")

    st.markdown(header_html(ep), unsafe_allow_html=True)
    view, size, mark = st.columns([2.6, 2.2, 3.2], vertical_alignment="bottom")   # a row of its own: room for big text
    ids = [m["member_id"] for m in members]
    want = st.query_params.get("as")   # an invite link says who is opening it
    mid = view.selectbox("Viewing as", ids, index=ids.index(want) if want in ids else 0,
                         format_func=lambda m: ep.members[m].get("name", m) + (
                             f" ({', '.join(x for x in (ep.members[m].get('relation'), ep.members[m].get('city')) if x)})"
                             if ep.members[m].get("relation") or ep.members[m].get("city") else ""))
    me = ep.members[mid]
    feedback = st.session_state.get("plan_save_feedback")
    if feedback and feedback["member"] == mid:
        (st.warning if feedback["kind"] == "warning" else st.error)(feedback["message"])
        if st.button("Dismiss plan message", key="dismiss_plan_save_feedback"):
            st.session_state.pop("plan_save_feedback", None)
            st.rerun()
    if sp is not None:
        st.query_params["as"] = mid
    with st.sidebar:
        family_panel(ep, sp, me)
    size.segmented_control("Text size", list(TEXT_SIZES), key="text_size", width="stretch",
                           help="Make every word on the page bigger")
    st.query_params["text"] = st.session_state.text_size or "A"   # a bookmark keeps it
    unread = ep.unread(mid)
    if mark.button(f"Mark {unread} new as read" if unread else "All read", key="mark_read", disabled=unread == 0,
                   type="primary", width="stretch"):
        ep.mark_read(mid)
        st.rerun()
    if st.session_state.get("flash"):
        st.toast(md_safe(st.session_state.flash))
        st.session_state.flash = None
    tz = me.get("timezone") or ep.patient.get("timezone")
    now = current_time(ep).isoformat()
    s = ep.status(tz=tz, now=now)
    presentation = presentation_model(ep, mid, tz, now=now)
    st.markdown(hero_html(ep, s, tz, me, presentation=presentation), unsafe_allow_html=True)
    if sp is None:
        st.caption("Saved private test timeline: bookmark this address to return after refresh or in another tab. "
                   "Anyone with this address can view and change it. Saved updates survive server restart while the host keeps its storage. "
                   "Unsubmitted drafts and original audio are not saved.")
    add_entry(ep, me)
    correction_panel(ep, me)
    render_audit_panel(st, ep)
    left, right = st.columns([2, 1], gap="large")
    left.markdown(timeline_html(ep, mid, tz, photo_of=entry_photo, ward_shown=not left_hospital(s), presentation=presentation), unsafe_allow_html=True)
    left.markdown(source_archive_html(ep, photo_of=entry_photo), unsafe_allow_html=True)
    with right:
        doctor_questions(ep, me, tz)
        st.markdown(side_html(ep, s, tz, mid, presentation=presentation), unsafe_allow_html=True)
    st.markdown('<div class="cr cr-foot">Times in your own time zone unless marked as the hospital\'s. Fictional composite: '
                f'every fact is quoted from an update (open Source); {PRODUCT} does not diagnose or give medical advice.</div>',
                unsafe_allow_html=True)


def correction_reading(source: dict, text: str, checked_by: str) -> dict:
    """Retain line-level authority: editing one line never changes its neighbours."""
    old = [line for line in (source.get("text") or "").splitlines() if norm(line)]
    new = [line for line in text.splitlines() if norm(line)]
    old_words, new_words = {norm(line) for line in old}, {norm(line) for line in new}
    reading = source.get("reading") or {}
    previously_changed = {norm(line) for line in reading.get("changed_lines", [])}
    changed = [line for line in new if norm(line) not in old_words or norm(line) in previously_changed]
    removed = [line for line in [*(reading.get("removed_lines") or []), *old] if norm(line) not in new_words]
    return {**reading, "changed_lines": changed, "removed_lines": list(dict.fromkeys(removed)),
            "checked_by": checked_by, "method": "family_correction"}


def correction_panel(ep: Episode, me: dict) -> None:
    """Correct the checked source words, preserving the original source identity/time.

    Without an extractor, facts are cleared explicitly; old extraction proposals
    are never replayed against changed words.
    """
    sources = [u for u in ep.updates if u.get("author") == me["member_id"]]
    if not sources:
        return
    with st.expander("Correct an update", expanded=False):
        st.caption("Correct the source words or who was speaking. To share new care instructions, add a new update.")
        ids = [u["update_id"] for u in reversed(sources)]
        uid = st.selectbox("Update to correct", ids, key="correction_source")
        source = next(u for u in sources if u["update_id"] == uid)
        revision = ep.source_revision(uid)
        speaker_metadata = {}
        if source["kind"] == "recording":
            speaker_type, speaker, _ = recording_identity(ep, me, f"correction_{uid}_{revision}", source)
            speaker_metadata = {"speaker_type": speaker_type, "speaker": speaker}
        metadata_changed = any(value != (source.get(key) or ("care_team" if key == "speaker_type" else ""))
                               for key, value in speaker_metadata.items())
        # The edit draft carries the revision it was opened against.
        draft_key = f"correction_text_{uid}_{revision}"
        text = st.text_area("Corrected source words", value=source.get("text", ""), key=draft_key)
        checked = st.checkbox("I checked these words against the original source", key=f"correction_checked_{uid}_{revision}")
        if not live_model_configured():
            st.caption("No extraction model is connected. Saving corrected words removes the old extracted facts for this update.")
        if st.button("Save correction", key=f"correction_save_{uid}_{revision}",
                     disabled=not checked or not text.strip() or (text == source.get("text", "") and not metadata_changed)
                     or (bool(speaker_metadata) and not speaker_metadata["speaker"])):
            try:
                reading = correction_reading(source, text, me["name"]) if text != source.get("text") else source.get("reading")
                replacement = {"text": text, "reading": reading, **speaker_metadata}
                with working("Updating the corrected source", "Checking the corrected words and refreshing the timeline."):
                    options = {"extractor": get_extractor()} if live_model_configured() else {"facts": []}
                    entry = ep.revise_update(uid, replacement, expected_revision=revision,
                                             request_id=f"ui-correction-{uid}-{revision}-{hashlib.sha256(repr(replacement).encode()).hexdigest()}",
                                             evidence_checker=checker_from_env(), **options)
            except Exception as ex:
                st.error(f"Could not save the correction ({type(ex).__name__}). Your words are kept; nothing changed.")
            else:
                st.session_state.flash = ("Source updated. Answers and the timeline now use the corrected words." if entry["facts"] else
                                          "Source words saved. No structured facts were added; the previous facts from this update were removed.")
                st.rerun()


main()
