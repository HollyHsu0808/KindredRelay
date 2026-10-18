"""HTML for the family timeline page (design A, "key events first"): a "right now" card, one timeline where key events
(admission, a procedure, going home and its changes, medicines, follow-ups) are large and notes and family logistics are
one quiet line each, people told apart by colour (the care team by one icon), a "you last looked here" line, and a side
column for practical things (what's next, visiting the ward, medicines, family) that is visibly less important than the
patient's own events.

Pure functions over agent/episode.py's output, so the page (ui/pages/1_Family_timeline.py) only places them with
st.markdown. Every piece of text from an update is escaped. Stdlib only.
"""
from __future__ import annotations

import base64
import copy
import datetime as dt
import html
import re
from zoneinfo import ZoneInfo

from episode import CANCELS, MONTHS, ORDER, WEEKDAYS, Episode, _family_assertion_span, _family_replacement_match, _family_target_pattern, _plan_negated, _source_clauses, event_time, family_plan_text, fmt_when, norm, parse_when, source_authority

PRODUCT = "KindredRelay"   # the product name the page shows: change it here (and in the docs) to rename the product
TAGLINE = "One place to understand what's happening, and be there for each other."
ABOUT = ("When someone we love has an accident, the whole family wants to know what's happening, even when we live in different "
         "cities or countries. But the person at the hospital is already busy helping their loved one and speaking with the care "
         "team. This page gives the family one shared place to come together. The main caregiver can upload recordings and photos, "
         "then invite relatives with a link. AI organizes the updates into a clear timeline, answers questions using the shared "
         "information, and gathers anything that still needs clarification. Family members can also share when they're coming, "
         "how they can help, and what they learn along the way. So the person closest to the patient doesn't have to carry every "
         "conversation alone, and everyone has a way to be there.")
PALETTE = ("#0F766E", "#9A3412", "#6D28D9", "#A16207", "#1D4ED8", "#BE185D", "#15803D")   # one per family member
KEY_TYPES = {"discharged", "procedure_done", "admitted", "procedure_planned", "expected_discharge", "medication",
             "follow_up", "diagnosis_stated", "location"}
REFERENCE_TYPES = {"visiting", "rounds", "contact"}   # practical facts: they go to the side column, the timeline says so
DEFAULT_HEADLINES = {"Note from the family", "Recording added", "Photo added"}
CATEGORY = {"discharged": "Discharge", "procedure_done": "Procedure", "admitted": "Admission", "procedure_planned": "Planned",
            "expected_discharge": "Going home", "medication": "Medicines", "follow_up": "Follow-up",
            "diagnosis_stated": "Diagnosis", "location": "Location"}
_P = '<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{d}</svg>'
PATHS = {
    "medication": '<path d="M10.5 3.5a5 5 0 0 1 7 7l-7 7a5 5 0 0 1-7-7z"></path><path d="m7 10 7 7"></path>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"></rect><path d="M16 3v4M8 3v4M3 11h18"></path>',
    "done": '<path d="m6 12 4 4 8-9"></path>',
    "bed": '<path d="M3 18V6"></path><path d="M3 14h18v4"></path><path d="M21 14v-2a3 3 0 0 0-3-3h-7v5"></path><circle cx="7" cy="11" r="2"></circle>',
    "home": '<path d="M3 11 12 4l9 7"></path><path d="M5 10v10h14V10"></path>',
    "care": '<path d="M6 3v6a4 4 0 0 0 8 0V3"></path><path d="M10 13v3a5 5 0 0 0 10 0v-2"></path><circle cx="20" cy="12" r="2"></circle>',
    "alert": '<path d="M12 3 2 20h20z"></path><path d="M12 10v4M12 17h.01"></path>',
    "camera": '<path d="M4 8h3l2-3h6l2 3h3v11H4z"></path><circle cx="12" cy="13" r="3.5"></circle>',
    "heart": '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"></path>',
}
ICON_OF = {"medication": "medication", "expected_discharge": "calendar", "procedure_planned": "calendar", "follow_up": "calendar",
           "procedure_done": "done", "admitted": "bed", "location": "bed", "discharged": "home", "diagnosis_stated": "care"}
BLUE, AMBER = "#0B5CAD", "#B45309"

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&family=Lexend:wght@400;500;600&display=swap');
.stApp{background:#F4F6F8}
.cr{font-family:'Atkinson Hyperlegible',system-ui,sans-serif;color:#17202B;line-height:1.45}
.cr .cr-display{font-family:'Lexend',system-ui,sans-serif;font-weight:600;letter-spacing:-0.005em}
.cr-eyebrow{font-size:calc(13px*var(--cr-fs,1));letter-spacing:.08em;text-transform:uppercase;color:#5B6573;font-weight:700}
.cr-name{font-size:calc(34px*var(--cr-fs,1));line-height:1.15;margin:2px 0 0}
.cr-hero{background:#FFFFFF;border-radius:20px;padding:24px 28px;display:flex;flex-direction:column;gap:18px;margin:4px 0 8px}
.cr-hero-top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px}
.cr-phase{font-size:calc(30px*var(--cr-fs,1));line-height:1.2;margin:4px 0 2px}
.cr-sub{font-size:calc(17px*var(--cr-fs,1));color:#4A5563}
.cr-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px}
.cr-fact{display:flex;flex-direction:column;gap:4px;padding-top:12px;border-top:3px solid #DCE1E7}
.cr-fact.cr-chg{border-top-color:#B45309}
.cr-fact-label{font-size:calc(14px*var(--cr-fs,1));color:#5B6573}
.cr-fact-value{font-size:calc(21px*var(--cr-fs,1))}
.cr-fact-note{font-size:calc(14px*var(--cr-fs,1));color:#5B6573}
.cr-amber{color:#8A3B07}
.cr-alert{display:flex;gap:10px;align-items:flex-start;background:#FDECEA;color:#7A1A12;border-radius:12px;padding:12px 14px;font-size:calc(16px*var(--cr-fs,1))}
.cr-alert.cr-conflict{background:#FFF3DF;color:#5A3A0A;border:1px solid #E2B66E}
.cr-two{display:block;margin-top:6px}
.cr-two q{font-style:italic}
.cr-two-who{font-size:calc(13px*var(--cr-fs,1));opacity:.85}
.cr-sec{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:6px 0 10px}
.cr-sec-title{font-size:calc(22px*var(--cr-fs,1))}
.cr-legend{display:flex;gap:14px;font-size:calc(13px*var(--cr-fs,1));color:#4A5563;flex-wrap:wrap}
.cr-legend span{display:inline-flex;align-items:center;gap:6px}
.cr-rail{border-left:2px solid #DCE1E7;margin-left:11px;padding-left:28px}
.cr-test-topic{padding:16px 18px;margin:0 0 20px;border:1px solid #DCE1E7;border-radius:14px;background:var(--cr-surface-hi,#FFFFFF);color:var(--cr-ink,#17202B)}
.cr-test-topic .cr-h3{margin-top:0}
.cr-test-topic details{margin-top:10px;font-size:calc(14px*var(--cr-fs,1))}
.cr-test-topic summary{cursor:pointer;color:var(--cr-link,#0B5CAD)}
.cr-test-topic .cr-claim{margin:8px 0}
.cr-day{font-size:calc(13px*var(--cr-fs,1));letter-spacing:.08em;text-transform:uppercase;color:#5B6573;font-weight:700;padding:6px 0 12px}
.cr-ev{position:relative;padding:0 0 26px}
.cr-ev.cr-note,.cr-ev.cr-ref{padding-bottom:18px}
.cr li,.cr p,.cr dl,.cr dd{margin:0;padding-left:0}
.cr ul{padding-left:0}
.cr ul.cr-list{padding-left:18px}
.cr ul.cr-meds{padding-left:0}
.cr-dot{position:absolute;display:flex;align-items:center;justify-content:center;border-radius:50%;color:#FFFFFF}
.cr-key>.cr-dot{left:-41px;top:2px;width:24px;height:24px}
.cr-note>.cr-dot,.cr-ref>.cr-dot{left:-34px;top:7px;width:10px;height:10px;background:#9AA4B1}
.cr-meta{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:calc(14px*var(--cr-fs,1));color:#5B6573}
.cr-time{font-weight:700;color:#17202B}
.cr-new{background:#E8F0FA;color:#0B5CAD;font-weight:700;padding:2px 8px;border-radius:999px;font-size:calc(12px*var(--cr-fs,1))}
.cr-h3{font-size:calc(23px*var(--cr-fs,1));line-height:1.25;margin:6px 0 8px}
.cr-body{display:flex;gap:18px;flex-wrap:wrap;align-items:flex-start}
.cr-list{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:4px;font-size:calc(16px*var(--cr-fs,1));flex:1 1 320px}
.cr-meds{list-style:none;padding-left:0}
.cr-quiet{color:#4A5563}
.cr-stop{color:#B42318}
.cr-thumb{width:128px;height:90px;object-fit:cover;border-radius:10px;background:#E9EDF1}
.cr-care{display:inline-flex;align-items:center;gap:5px;color:#334155;font-weight:700}
.cr-row{display:flex;gap:4px 10px;align-items:baseline;flex-wrap:wrap;font-size:calc(15px*var(--cr-fs,1));color:#4A5563}
.cr-rowtext{flex:1 1 260px;min-width:0}
.cr-srcrow{display:flex;gap:4px 12px;align-items:baseline;flex-wrap:wrap;margin-top:8px;font-size:calc(14px*var(--cr-fs,1));color:#5B6573}
.cr-badge{border:1px solid #C2410C;color:#9A3412;padding:1px 8px;border-radius:999px;font-size:calc(12px*var(--cr-fs,1));font-weight:700}
.cr-badge-red{border-color:#B42318;color:#B42318}
.cr-badge-gray{border-color:#6B7480;color:#4A5563}
.cr-badge-amber{border-color:#B45309;color:#92400E;background:#FFF4E2}
.cr-was{background:#F1EAFB;color:#5B21B6;padding:1px 8px;border-radius:999px;font-size:calc(12px*var(--cr-fs,1))}
.cr-seen{display:flex;align-items:center;gap:10px;margin:0 0 20px -40px;font-size:calc(13px*var(--cr-fs,1));color:#0B5CAD;font-weight:700}
.cr-seen::before{content:"";width:24px;height:2px;background:#0B5CAD}
.cr-seen::after{content:"";flex:1;height:2px;background:#BFD3EA}
details.cr-src{font-size:calc(13px*var(--cr-fs,1));color:#5B6573}
details.cr-src[open]{flex-basis:100%}
details.cr-src summary{cursor:pointer;width:max-content;color:#0B5CAD;text-decoration:underline;text-underline-offset:2px}
details.cr-src blockquote{margin:6px 0;padding:0 0 0 10px;border-left:2px solid #DCE1E7;color:#2F3A47;font-size:calc(14px*var(--cr-fs,1))}
details.cr-src .cr-list{font-size:calc(13px*var(--cr-fs,1))}
.cr-side{display:flex;flex-direction:column;gap:22px}
.cr-side section{display:flex;flex-direction:column;gap:8px}
.cr-side section+section{padding-top:20px;border-top:1px solid #DCE1E7}
.cr-side-title{font-size:calc(18px*var(--cr-fs,1))}
.cr-side-sub{font-size:calc(13px*var(--cr-fs,1));color:#5B6573}
.cr-side ul{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:6px;font-size:calc(15px*var(--cr-fs,1))}
.cr-side dl{margin:0;display:flex;flex-direction:column;gap:8px;font-size:calc(15px*var(--cr-fs,1))}
.cr-side dt{color:#5B6573;font-size:calc(13px*var(--cr-fs,1))}
.cr-side dd{margin:2px 0 0}
.cr-fam-title{font-size:calc(15px*var(--cr-fs,1));font-weight:700;color:#4A5563;margin:0}
.cr-fam li{display:flex;gap:8px;align-items:center;font-size:calc(14px*var(--cr-fs,1));color:#4A5563}
.cr-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.cr-chip{display:flex;flex-direction:column;gap:2px;padding:10px 14px;border-radius:16px;background:#F4F6F9}
.cr-chip-value{font-size:calc(16px*var(--cr-fs,1));font-weight:600;color:#1F2933}
.cr-chip-value a{color:inherit;text-decoration:none;border-bottom:1px dotted currentColor}
.cr-plan-check{display:flex;gap:6px;align-items:flex-start;margin-top:4px;padding:6px 10px;border-radius:12px;background:#FFF3DF;color:#5A3A0A;font-size:calc(13px*var(--cr-fs,1))}
.cr-plans li{display:flex;gap:8px;align-items:flex-start;line-height:1.4}
.cr-tagline{font-size:calc(15px*var(--cr-fs,1));color:#5B6573;margin:2px 0 6px}
.cr-avatar{width:26px;height:26px;border-radius:50%;color:#FFFFFF;font-size:calc(12px*var(--cr-fs,1));font-weight:700;display:inline-flex;align-items:center;justify-content:center;flex:0 0 26px}
.cr-foot{font-size:calc(13px*var(--cr-fs,1));color:#5B6573;margin-top:12px}
.cr-hello{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:10px 2px 14px}
.cr-hello-hi{font-size:calc(30px*var(--cr-fs,1));line-height:1.2;color:var(--cr-ink,#2A2B2E)}
.cr-hello-sub{font-size:calc(16px*var(--cr-fs,1));color:var(--cr-muted,#62656D);margin-top:2px}
.cr-hello .cr-avatar{width:50px;height:50px;flex:0 0 50px;font-size:calc(21px*var(--cr-fs,1))}
.cr-chat{display:flex;flex-direction:column;gap:10px;margin:10px 0 16px}
.cr-me{display:flex;flex-direction:column;align-items:flex-end;gap:4px}
.cr-bubble-me{max-width:82%;background:linear-gradient(145deg,var(--cr-accent-a,#F9CF6A),var(--cr-accent-b,#F2A93E));color:var(--cr-on-accent,#4A2F00);padding:10px 18px;border-radius:22px 22px 6px 22px;font-size:calc(17px*var(--cr-fs,1));font-weight:700;box-shadow:0 6px 14px var(--cr-shadow,rgba(171,150,118,.30))}
.cr-me-who{font-size:calc(12px*var(--cr-fs,1));color:var(--cr-muted,#7B7365);margin-right:10px}
.cr-reply{display:flex;gap:10px;align-items:flex-start}
.cr-bot{flex:0 0 40px;width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--cr-accent-soft,#FFF3D6);color:var(--cr-accent-ink,#9A5B00);box-shadow:3px 3px 8px var(--cr-shadow,rgba(171,150,118,.30)),-3px -3px 8px var(--cr-light,#FFFFFF)}
.cr-bubble-bot{flex:1 1 auto;min-width:0;background:var(--cr-surface-hi,#FFFFFF);border-radius:6px 24px 24px 24px;padding:16px 18px;display:flex;flex-direction:column;gap:12px;box-shadow:8px 8px 20px var(--cr-shadow,rgba(171,150,118,.30)),-6px -6px 16px var(--cr-light,#FFFFFF);backdrop-filter:var(--cr-blur,none)}
.cr-qa-a{font-size:calc(19px*var(--cr-fs,1));line-height:1.35;color:var(--cr-ink,#2B2A26)}
.cr .cr-qa-quotes{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px}
.cr-qa-quotes li{display:flex;gap:10px;align-items:flex-start;background:var(--cr-well,#F7F3EC);border-radius:16px;padding:10px 12px}
.cr-qa-av{flex:0 0 30px;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#FFFFFF;font-size:calc(13px*var(--cr-fs,1));font-weight:700;margin-top:1px}
.cr-qa-av.cr-av-care{background:#DDF1EC;color:#0F766E}
.cr-qa-say{flex:1 1 auto;min-width:0}
.cr-qa-quote{font-size:calc(16px*var(--cr-fs,1));color:var(--cr-ink,#17202B)}
.cr-qa-old .cr-qa-quote{color:var(--cr-muted,#5B6573)}
.cr-qa-src{font-size:calc(13px*var(--cr-fs,1));color:var(--cr-muted,#5B6573);margin-top:2px}
.cr-qa-next{font-size:calc(15px*var(--cr-fs,1));color:var(--cr-accent-ink,#9A5B00)}
.cr-qa-how{font-size:calc(12px*var(--cr-fs,1));color:var(--cr-muted,#5B6573)}
.cr-leaf{background:var(--cr-accent-soft,#FFF3D6);border-radius:18px;padding:12px 16px;display:flex;flex-direction:column;gap:6px}
.cr-leaf-head{font-size:calc(15px*var(--cr-fs,1));font-weight:700;color:var(--cr-ink,#17202B)}
.cr-leaf-note{font-size:calc(12px*var(--cr-fs,1));color:var(--cr-muted,#5B6573)}
.cr .cr-leaf ul{margin:0;padding-left:18px;font-size:calc(15px*var(--cr-fs,1));color:var(--cr-ink,#2F3A47);display:flex;flex-direction:column;gap:3px}
.cr-leaf details summary{font-size:calc(13px*var(--cr-fs,1));color:var(--cr-accent-ink,#0B5CAD);cursor:pointer;width:max-content;text-decoration:underline}
.cr-qitem{display:flex;flex-direction:column;gap:4px;padding:12px 14px;margin:8px 0 2px;border-radius:18px;background:var(--cr-chip,#FFF8E8);box-shadow:5px 5px 12px var(--cr-shadow,rgba(171,150,118,.30)),-4px -4px 10px var(--cr-light,#FFFFFF)}
.cr-qtext{font-size:calc(16px*var(--cr-fs,1));color:var(--cr-ink,#17202B)}
.cr-qmeta{font-size:calc(12px*var(--cr-fs,1));color:var(--cr-muted,#5B6573)}
.cr-qhint{font-size:calc(13px*var(--cr-fs,1));color:#0F766E}
</style>"""


def esc(s) -> str:
    """Escaped, on one line: a line break (above all a blank line) inside st.markdown's HTML would end the HTML block."""
    return html.escape(re.sub(r"[\r\n\v\f\u2028\u2029]+", " ", str(s if s is not None else "")), quote=True)


def arrows(s: str) -> str:
    return s.replace("->", "→")


def icon(name: str, size: int = 14, width: float = 2.4) -> str:
    return _P.format(s=size, w=width, d=PATHS[name])


def colors_of(ep: Episode) -> dict:
    """One colour per family member, as a token (--cr-p0 ...) with the palette colour as its fallback, so a look can
    recolour the family into its own colour family."""
    return {mid: f"var(--cr-p{i % len(PALETTE)},{PALETTE[i % len(PALETTE)]})" for i, mid in enumerate(ep.members)}


def person(ep: Episode, mid: str | None, colors: dict) -> str:
    name = ep.members.get(mid, {}).get("name") or mid or "someone"
    return f'<b style="color:{colors.get(mid, "#334155")}">{esc(name)}</b>'


def local(at: str, tz: str | None) -> dt.datetime | None:
    w = parse_when(at)
    if not isinstance(w, dt.datetime):
        return None
    return w.astimezone(ZoneInfo(tz)) if tz and w.tzinfo else w


def shared_plan(e: dict) -> bool:
    return e.get("kind") == "note" and e.get("topic") == "plan"


def plan_date_text(ep: Episode, e: dict) -> str:
    """Use the core's source-grounded event time, including for an old live object."""
    timing = _plan_timing(ep, e)
    if timing.get("time_role") == "withdrawn_target" and timing.get("when"):
        # This date belongs to the cancelled appointment, not to the act of
        # cancelling it. Keep uncertainty about intent in the timing metadata.
        value = event_time_text({**timing, "status": "confirmed"}, None)
        return value + " (hospital time)" if timing.get("precision") == "clock" else value
    value = event_time_text(timing, None)
    return value + " (hospital time)" if timing.get("status") == "confirmed" and timing.get("precision") == "clock" else value


def event_time_text(timing: dict, tz: str | None) -> str:
    if timing.get("time_role") == "withdrawal_reference":
        return "Cancellation time unclear"
    if timing.get("status") != "confirmed" or not timing.get("when"):
        return ("Event date/time not stated" if timing.get("reason") == "The source does not state an event date."
                else "Event date/time unclear")
    when = parse_when(timing["when"])
    if isinstance(when, dt.datetime):
        return fmt_when(timing["when"], tz)
    if not isinstance(when, dt.date):
        return "Event date/time unclear"
    parts = set(re.findall(r"\b(morning|afternoon|evening|night)\b", timing.get("when_text") or "", re.I))
    part = next(iter(parts)).lower() if timing.get("precision") == "part_of_day" and len(parts) == 1 else ""
    return when.strftime("%a %d %b %Y") + (f" · {part}" if part else "")


def _plan_timing(ep: Episode, entry: dict) -> dict:
    if entry.get("plan_status") and entry.get("event_time"):
        return entry["event_time"]
    return event_time(ep, {**entry, "text": family_plan_text(entry), "topic": "plan", "lines": []})


def plan_headline(ep: Episode, e: dict) -> str:
    """A shared plan's source words keep tense, negation and conditions even if extraction omitted them."""
    text = " ".join((e.get("plan_text") or family_plan_text(e)).split())
    timing = plan_date_text(ep, e)
    if _plan_timing(ep, e).get("time_role") == "withdrawn_target":
        return text + f" — Cancelled target: {timing}"
    known = _plan_timing(ep, e).get("status") == "confirmed"
    return text + (f" — Date stated: {timing}" if known else f" — {timing}")


_CARE_OBSERVATION = re.compile(
    r"\b(?:patient|hospital|ward|nurs\w*|doctor|clinici\w*|medic\w*|caregiver|carer|"
    r"pain\w*|symptom\w*|fever|breath\w*|cough\w*|bleed\w*|wound\w*|dressings?|"
    r"fell|falls?|faint\w*|slip\w*|burn\w*|injur\w*|fractur\w*|seizur\w*|"
    r"walk\w*|mobility|frame|crutch\w*|wheelchair|eat\w*|drink\w*|swallow\w*|"
    r"confus\w*|dizz\w*|weak\w*|unwell|deteriorat\w*|recover\w*|"
    r"admi\w*|discharg\w*|transfer\w*|surger\w*|operation\w*|therapy|treatment|"
    r"appointment\w*|visit\w*|transport|ambulance|prevent\w*|cannot|can't|unable|unsafe)\b", re.I)


def _administrative_statement(text: str, *, pronoun_removal: bool = False) -> bool:
    """Recognise whole source statements about documents, never patient actions.

    A bare 'removing it' has no safe referent. Its caller may allow that form
    only inside an entirely administrative source naming a digital document.
    Unknown words, clinical effects, conditions and additional clauses retain
    the assertion. This classifies display importance; it never deletes data.
    """
    text = norm(text).strip(' .!?;')
    no_change = (r'(?:there (?:is|are) )?no (?:new )?'
                 r'(?:(?:clinical|care|medical|discharge|visit) (?:or |and )?)*'
                 r'(?:information|news|updates?|changes)')
    duplicate = (r'(?:(?:this|it) is (?:only |just )?a duplicate (?:upload|message|document)'
                 r'(?: with no new (?:clinical |care |medical )?information)?)')
    document = r'(?:this|that|the) (?:(?:discharge|medication|ward) )?(?:photo|document|file|upload|message)'
    wrong_file = document + r' (?:is|was) (?:from |in )?(?:the |a )?wrong (?:folder|file|upload)'
    explicit_removal = r'(?:i|we) (?:am |are |have |will )?(?:removing|deleting|removed|deleted|remove|delete) ' + document
    patterns = [no_change, duplicate, wrong_file, explicit_removal]
    if pronoun_removal:
        patterns.append(r'(?:i|we) (?:am |are |have |will )?(?:removing|deleting|removed|deleted|remove|delete) it')
    return any(re.fullmatch(pattern, text) for pattern in patterns)


def _administrative_source(entry: dict) -> bool:
    text = entry.get('text') or ''
    if not re.search(r'\b(?:photo|document|file|upload|message)\b', text, re.I):
        return False
    clauses = [part.strip() for part in re.split(r'[.!?;]+', text) if part.strip()]
    return bool(clauses) and all(_administrative_statement(part, pronoun_removal=True) for part in clauses)


def _generic_event_important(line: dict, entry: dict | None = None) -> bool:
    """A conservative retention policy over grounded source assertions.

    Keep patient status, symptoms, function, safety incidents and care access or
    arrangements; unfamiliar observations are also retained. Archive only an
    entire, unambiguous household task, static amenity/equipment statement or
    explicit duplicate/no-new-information message. Never classify by a model
    paraphrase alone, and never treat an unchanged symptom as no information.
    This projection does not delete a source or infer clinical significance.
    """
    quote = norm(line.get("quote") or "").strip(" .!?")
    if not quote:
        return True
    if (_administrative_statement(quote)
            or (entry is not None and _administrative_source(entry)
                and _administrative_statement(quote, pronoun_removal=True))):
        return False
    # Each pattern recognises a complete statement. Added conditions, effects,
    # clinical clauses and unknown words fall through to retention.
    household = (r"(?:i|we|he|she) (?:watered (?:the |my |our )?(?:house )?plants|"
                 r"washed (?:the |my |our )?(?:dishes|windows)|"
                 r"(?:did|finished) (?:the |my |our )?(?:laundry|housework)|"
                 r"(?:collected|picked up) (?:the |my |our )?(?:laundry|clothes)"
                 r"(?: from (?:the )?(?:hospital|ward|house|home|laundry))?)")
    equipment = (r"(?:the |our |my )?(?:(?:hospital|ward|reception|office) )?"
                 r"(?:kettle|router|printer|washing machine|dishwasher|lift|elevator|ticket machine)"
                 r"(?: (?:by|near|at|in) (?:the )?(?:reception|office|entrance|lobby|cafeteria))? (?:is|was) "
                 r"(?:broken|working(?: again)?|out of (?:order|service|paper)|not working)")
    amenity = (r"(?:the )?(?:cafeteria|cafe|coffee shop|car park|parking office) "
               r"(?:opens?|closes?) (?:at |from )?\d{1,2}(?::\d{2})?\s*(?:am|pm)?")
    prices = (r'(?:the )?(?:cafeteria|cafe|coffee shop|car park|parking office) '
              r'(?:(?:coffee|tea|parking) )?(?:prices?|costs?|fees?) (?:has|have) changed')
    credential = r"(?:the )?(?:(?:hospital|ward) )?(?:wi-?fi|internet) password is [a-z0-9_-]+"
    return not any(re.fullmatch(pattern, quote) for pattern in (household, equipment, amenity, prices, credential))


def important_line(ln: dict, entry: dict | None = None) -> bool:
    if ln["type"] == "event":
        return _generic_event_important(ln, entry)
    if ln["type"] in {"admitted", "discharged", "location", "diagnosis_stated", "procedure_planned",
                      "procedure_done", "expected_discharge", "follow_up"}:
        return True
    if ln["type"] in {"medication", "instruction", "next_step"}:
        return bool(ln.get("changed_from_fact") or re.search(
            r"\b(start(?:ed|ing)?|stop(?:ped|ping)?|chang\w*|cancel\w*|discontinu\w*|increas\w*|decreas\w*|delay\w*|postpon\w*)\b",
            ln.get("quote") or "", re.I))
    return False


def _clinical_event_supplement(ep: Episode, entry: dict, line: dict) -> bool:
    """Fold a generic restatement of the very same simple typed assertion.

    Exact source quote and timing equality are mandatory. Multi-clause,
    conditional and repeated source assertions remain visible; this is neither
    cross-source deduplication nor an adjudication between incompatible facts.
    """
    if line["type"] != "event":
        return False
    quote = norm(line.get("quote") or "").strip(" .!?")
    if not quote or norm(entry.get("text") or "").count(quote) != 1:
        return False
    # 'and remains there' adds no event to a simple admission assertion. Every
    # other conjunction retains both claims, including new symptoms/ward moves.
    simple_quote = re.sub(r'\s+and (?:remains?|is still) there$', '', quote)
    if re.search(r"[;!?]|\.(?:\s|$)|\b(?:and|but|while|after|before|because|if|unless|once|provided|when|or|instead|replaced|"
                 r"with|due|following|despite|although|whereas|requiring|suffering|pain\w*|fever|cough\w*|"
                 r"bleed\w*|faint\w*|fell|slip\w*|confus\w*|dizz\w*|wound\w*)\b", simple_quote):
        return False
    stated = norm(line["fact"].get("what") or "").strip(" .!?")
    aliases = {"admitted": {"admitted", "admitted to hospital", "hospital admission", "admission to hospital"},
               "discharged": {"discharged", "discharged home", "discharge home", "hospital discharge", "discharged from hospital"}}
    for typed in entry["lines"]:
        if norm(typed.get("quote") or "").strip(" .!?") != quote:
            continue
        kind = typed["type"]
        if kind in aliases:
            same = stated in aliases[kind]
            if not same and kind == 'admitted':
                name = norm(ep.patient.get('name') or '')
                subjects = {'she', 'he', 'the patient', 'mum', 'mom', 'dad'} | ({name, name.split()[0]} if name else set())
                subject = '(?:' + '|'.join(re.escape(value) for value in sorted(subjects, key=len, reverse=True)) + ')'
                complete = re.fullmatch(rf'(?P<assertion>{subject} (?:was|were|has been|had been) admitted'
                                        rf'(?: to [a-z0-9 &\'-]+?)?) on {_family_target_pattern()}', simple_quote)
                same = bool(complete and (stated == quote or
                            (' admitted to ' in complete['assertion'] and stated == complete['assertion'])))
                # This literal readmission alias still needs a complete,
                # affirmative same-patient assertion; never match a substring.
                if stated == 'readmitted to hospital' and '?' not in (line.get('quote') or ''):
                    same = bool(re.fullmatch(rf'{subject} (?:was|were|has been|had been) readmitted to hospital'
                                             rf' on {_family_target_pattern()}', simple_quote))
        elif kind in {"procedure_planned", "procedure_done"}:
            subject = norm(typed["fact"].get("what") or "").strip(" .!?")
            suffixes = ("planned", "scheduled", "booked") if kind == "procedure_planned" else ("done", "completed", "performed")
            same = bool(subject) and stated in {subject, *(subject + " " + suffix for suffix in suffixes)}
        else:
            continue
        if same:
            own, other = event_time(ep, entry, line), event_time(ep, entry, typed)
            keys = ("when", "precision", "status")
            # The event schema has no completion type. Use the typed assertion
            # only when its source calendar evidence agrees; uncertain dates
            # retain both extracted assertions for inspection.
            if own.get("status") == "confirmed" and all(own.get(key) == other.get(key) for key in keys):
                return True
    return False


def _replaced_plan_facts(ep: Episode) -> set[str]:
    """Retire one explicitly identified earlier procedure booking, if proved.

    Store history alone does not identify an occurrence. The complete new
    source must say 'the same <procedure> was previously booked for <old>'
    followed by its new target. Bind that reference to exactly the core's
    changed-from fact and one unique active, simple old booking. Missing scope,
    source edits, repeated targets, other patients/clauses and weaker authority
    retain the old assertion. Discharge/follow-up history has no such proof here.
    """
    obsolete = set()

    def active_source(record):
        entry = next((e for e in ep.entries if e['update_id'] == record['update_id']
                      and e['source_revision'] == record['source_revision']), None)
        source = ep._sources.get(record['update_id']) or {}
        if (not entry or source.get('deleted') or source.get('revision') != record['source_revision']
                or record.get('authority') != 'care_team' or entry.get('authority') != 'care_team'
                or (entry.get('reading') or {}).get('changed_lines')):
            return None
        return entry

    def same_time(left, right):
        return (left.get('status') == right.get('status') == 'confirmed'
                and all(left.get(k) == right.get(k) for k in ('when', 'precision'))
                and set(re.findall(r'\b(?:morning|afternoon|evening|night)\b', norm(left.get('when_text') or '')))
                == set(re.findall(r'\b(?:morning|afternoon|evening|night)\b', norm(right.get('when_text') or ''))))

    for current in ep.procedures.values():
        fact = current['fact']
        timing = current.get('event_time') or {}
        source = active_source(current)
        subject = norm(fact.get('what') or '')
        if (fact['type'] != 'procedure_planned' or current.get('status') != 'planned' or not subject
                or current.get('two_answers') or current.get('time_uncertain') or current.get('uncertain_alternatives')
                or timing.get('status') != 'confirmed' or source is None):
            continue
        applied = next((line for line in source['lines'] if line['fact'].get('fact_id') == fact.get('fact_id')), {})
        prior = applied.get('changed_from_fact') or {}
        history = [record for record in current.get('history', [])
                   if record['fact'].get('fact_id') == prior.get('fact_id') and prior.get('fact_id')]
        if not applied.get('applied') or applied.get('time_uncertain') or len(history) != 1:
            continue
        earlier = history[0]
        old, old_time = earlier['fact'], earlier.get('event_time') or {}
        old_source = active_source(earlier)
        if (old.get('type') != 'procedure_planned' or norm(old.get('what') or '') != subject
                or earlier.get('two_answers') or earlier.get('time_uncertain') or earlier.get('unsettled')
                or old_source is None or same_time(old_time, timing)):
            continue
        target = _family_target_pattern()
        quoted = norm(fact['quote']).strip(' .!')
        updated = re.fullmatch(rf'(?:the )?{re.escape(subject)} (?:has been|is|was) '
                              rf'(?:moved|rescheduled|postponed) to (?P<new>{target})', quoted)
        reference = re.fullmatch(rf'the same {re.escape(subject)} was previously booked for (?P<old>{target})[.!] '
                                 + re.escape(quoted) + r'[.!]?', norm(source['text']))
        original = re.fullmatch(rf'(?:the )?{re.escape(subject)} (?:is|was) (?:planned|scheduled|booked) for (?P<old>{target})[.!]?',
                                norm(old_source['text']))
        if (not updated or not reference or not original or not re.search(r'\b\d{4}\b', reference['old'])
                or norm(old_source['text']).strip(' .!') != norm(old['quote']).strip(' .!')
                or norm(source['text']).count(quoted) != 1):
            continue
        stated_old = event_time(ep, source, {'fact': {'type': 'procedure_planned', 'quote': reference['old']}})
        stated_new = event_time(ep, source, {'fact': {'type': 'procedure_planned', 'quote': updated['new']}})
        if not same_time(stated_old, old_time) or not same_time(stated_new, timing):
            continue
        matches = [line['fact']['fact_id'] for entry in ep.entries for line in entry['lines']
                   if line['type'] == 'procedure_planned' and norm(line['fact'].get('what') or '') == subject
                   and same_time(event_time(ep, entry, line), stated_old)]
        if len(matches) == 1 and matches[0] == old.get('fact_id'):
            obsolete.add(old['fact_id'])
    return obsolete


def _fulfilled_booking_facts(ep: Episode) -> set[str]:
    """Find bookings already attached to an unambiguous completed occurrence.

    Core record membership supplies occurrence identity; matching a name/date
    alone never removes a booking. Different subjects, future/repeat targets,
    unknown times, source conflicts and weaker completion reports are retained.
    Completed facts and the original source archive are never filtered here.
    """
    obsolete = set()
    for procedure in ep.procedures.values():
        if procedure.get("status") != "done" or procedure.get("time_uncertain") or procedure.get("two_answers"):
            continue
        done = procedure.get("done_record") or procedure
        completed = done.get("event_time") or {}
        if completed.get("status") != "confirmed" or not completed.get("when"):
            continue
        for record in [procedure, *procedure.get("history", [])]:
            fact = record["fact"]
            if (fact.get("type") != "procedure_planned" or not fact.get("fact_id")
                    or norm(fact.get("what") or "") != norm((procedure.get("done") or {}).get("what") or "")
                    or record.get("two_answers") or record.get("time_uncertain")
                    or (record["authority"] == "care_team" and done["authority"] != "care_team")
                    or re.search(r"\b(?:another|second|repeat|again|new)\b", norm(fact["quote"]))):
                continue
            planned = record.get("event_time") or {}
            if planned.get("status") != "confirmed" or not planned.get("when"):
                continue
            if planned.get("precision") == completed.get("precision") == "clock":
                earlier = ep._utc(planned["when"]) <= ep._utc(completed["when"])
            else:
                earlier = ep._local_date(planned["when"]) <= ep._local_date(completed["when"])
            if earlier:
                obsolete.add(fact["fact_id"])
    return obsolete


def _initial_admission_locations(ep: Episode, entry: dict, excluded_facts) -> dict[str, list[dict]]:
    """A location within one dated initial-admission assertion is context.

    Require the exact same unique source quotation and calendar evidence. A
    transfer, ward move, another assertion, uncertainty or another source stays
    a separate event. Render location context in the admission headline before
    removing the duplicate event line; the archived source is unchanged.
    """
    context = {}
    for admission in entry["lines"]:
        fid = admission["fact"].get("fact_id")
        if admission["type"] != "admitted" or not fid or fid in excluded_facts:
            continue
        quote = norm(admission["quote"]).strip(" .!?")
        if (not quote or norm(entry.get("text") or "").count(quote) != 1
                or not re.search(r"\badmitted\b", quote)
                or re.search(r"[;!?]|\.(?:\s|$)|\b(?:and|but|then|later|earlier|after|before|while|if|unless|"
                             r"transfer\w*|mov\w*|return\w*|again|another|second|not|never|cannot|can't|won't)\b", quote)
                or admission.get("contradicts") or admission.get("time_uncertain")):
            continue
        timing = event_time(ep, entry, admission)
        if timing.get("status") != "confirmed":
            continue
        for location in entry["lines"]:
            if (location["type"] != "location" or not location["fact"].get("fact_id")
                    or norm(location["quote"]).strip(" .!?") != quote
                    or location.get("changed_from_fact") or location.get("contradicts") or location.get("time_uncertain")):
                continue
            other = event_time(ep, entry, location)
            if all(timing.get(key) == other.get(key) for key in ("when", "precision", "status")):
                context.setdefault(fid, []).append(location)
    return context


def _named_family_arrival_supplement(ep: Episode, entry: dict, line: dict, owned: dict) -> bool:
    """One owned arrival assertion, including an unresolved zone qualification.

    The quote may omit only the entire zone tail. Matching pending times remain
    pending; this folds duplicate wording without supplying any calendar evidence.
    """
    name = norm(ep.members.get(entry.get('author'), {}).get('name') or '')
    source = norm(entry.get('text') or '').removesuffix('.').strip()
    quote = norm(line.get('quote') or '').removesuffix('.').strip()
    if (not name or not shared_plan(entry) or owned.get('plan_status') not in {'planned', 'pending_confirmation'}
            or source != norm(owned.get('text') or '').removesuffix('.').strip()):
        return False
    target = _family_target_pattern()
    calendar = rf'(?:on {target}|during the (?:morning|afternoon|evening|night) of {target})'
    intent = rf'(?P<intent>{re.escape(name)} will arrive)'
    zone = r'[a-z][a-z0-9_+-]*(?:/[a-z0-9_+-]+)+'
    single = rf' in {zone}(?:\s*\(utc\s*[+-]\d{{2}}:\d{{2}}\))?'
    # This optional clause only qualifies the same arrival's zone/clock; another
    # assertion, symptom or additional sentence cannot match the closed source.
    both = (rf' in both {zone} and {zone}(?:; both zones (?:specify|state|use) the same local date and clock time'
            r' for (?:this one|the same) arrival)?')
    complete = re.fullmatch(rf'(?P<base>{intent} {calendar})(?:{single}|{both})', source)
    wording = norm(line['fact'].get('what') or '').removesuffix('.').strip()
    if (complete is None or quote not in {source, complete['base']}
            or wording not in {complete['intent'], source, 'arrival'}):
        return False
    timing, plan_time = event_time(ep, entry, line), owned['event_time']
    if any(timing.get(field) != plan_time.get(field) for field in ('when', 'precision', 'status', 'temporal_status')):
        return False
    if plan_time.get('status') == 'pending_confirmation':
        return timing.get('when') is None and plan_time.get('when') is None
    return plan_time.get('status') == 'confirmed' and bool(plan_time.get('when'))


def _family_plan_supplement(ep: Episode, entry: dict, line: dict, text: str) -> bool:
    """Fold a generic family-intent restatement into its source's family row.

    Its unique source quote must itself identify the speaker's visit/arrival,
    and its paraphrase must contain only family-intent/calendar words. The
    family row owns intent, cancellation and ambiguous/replaced dates; archived
    source facts stay intact. Clinical assertions retain separate event cards.
    """
    if line["type"] != "event":
        return False
    quote = norm(line.get("quote") or "").strip(" .,;:!?")
    if not quote or len(re.findall(r"(?<![a-z0-9])" + re.escape(quote) + r"(?![a-z0-9])", norm(text))) != 1:
        return False
    owned = next((plan for plan in ep.plans() if plan['member_id'] == entry.get('author')
                  and plan['update_id'] == entry.get('update_id')
                  and plan['source_revision'] == entry.get('source_revision')
                  and norm(plan['text']) == norm(text)), None)
    if owned and _named_family_arrival_supplement(ep, entry, line, owned):
        return True
    if (owned and quote == norm(text).strip(' .,;:!?')
            and quote == norm(line['fact'].get('what') or '').strip(' .,;:!?')):
        timing = event_time(ep, entry, line)
        if (timing.get('timezone_alias') == 'Europe/London' and timing.get('status') == 'confirmed'
                and all(timing.get(field) == owned['event_time'].get(field)
                        for field in ('when', 'precision', 'status', 'temporal_status'))):
            return True
    if owned and quote == norm(text).strip(' .,;:!?'):
        # Same-author named visit, matching the observed generic proposal shape.
        # Require the complete closed source assertion and its literal intent;
        # a clinical tail or another actor cannot be erased by a visit paraphrase.
        name = norm(ep.members.get(entry.get('author'), {}).get('name') or '')
        subject = rf"(?:i|{re.escape(name)})" if name else r"i"
        intent = rf"(?P<intent>{subject} will (?:visit the patient(?: at home)?|arrive|come|be there))"
        calendar = rf"(?:on )?(?:the (?:morning|afternoon|evening|night) of )?{_family_target_pattern()}"
        zone = re.escape(norm(ep.patient.get('timezone') or ''))
        complete = re.fullmatch(intent + rf" {calendar},? {zone}(?:\s*\(utc\s*[+-]\d{{2}}:\d{{2}}\))?", quote)
        wording = norm(line['fact'].get('what') or '').strip(' .,;:!?')
        if complete and wording in {complete['intent'], quote}:
            timing = event_time(ep, entry, line)
            if (timing.get('explicit_timezone') == ep.home.key and timing.get('status') == 'confirmed'
                    and all(timing.get(field) == owned['event_time'].get(field)
                            for field in ('when', 'precision', 'status', 'temporal_status'))):
                return True
    target = _family_target_pattern()
    request = rf"(?:please )?(?:cancel|withdraw) (?:my|our) (?:visit|arrival)(?: on {target})?"
    cancellation = (rf"(?:(?:i|we) (?:have )?(?:cancelled|canceled|withdrawn) (?:my|our) {target} (?:visit|arrival)"
                    rf"|(?:i|we) (?:have )?(?:cancelled|canceled|withdrawn) (?:my|our) (?:visit|arrival)(?: on {target})?"
                    rf"|(?:i|we) (?:(?:can )?no longer|cannot|can't|won't|will not|am unable to|are unable to) "
                    rf"(?:come|arrive|visit|be there)(?: on)? {target}|{request})(?:[.;]\s*{request})?")
    logistics = (rf"(?:i|we) (?:will |can |am going to |are going to )?(?:bring|collect|pick up|drop off) "
                 rf"(?:the |my |our )?(?:keys|clothes|laundry|meals|phone|documents)(?: on {target})?")
    # The source quote itself must contain only this family arrangement. A
    # clinical consequence, another actor or an unsupported paraphrase cannot
    # disappear under the family row. The row owns withdrawn-target semantics.
    if owned and (re.fullmatch(cancellation, quote) or re.fullmatch(logistics, quote)):
        # Check every complete source assertion, including an adjacent cancel
        # request. A quote spanning two sentences must not borrow an unrelated
        # clinical sentence or lose a governing condition outside the quote.
        assertions = [quote[a:b].strip(' .,;:!?') for a, b in _source_clauses(quote)]
        complete = []
        for assertion in assertions:
            start, end = _family_assertion_span(entry.get('text') or '', assertion)
            complete.append(norm((entry.get('text') or '')[start:end]).strip(' .,;:!?') == assertion)
        status_matches = (owned['plan_status'] == 'withdrawn' if re.fullmatch(cancellation, quote)
                          else owned['plan_status'] in {'planned', 'completed'})
        if complete and all(complete) and status_matches:
            return True
    if owned and owned['plan_status'] == 'withdrawn':
        # A visit-like paraphrase cannot hide additional source content. Only
        # the complete cancellation grammar above owns a withdrawn assertion.
        return False
    if _family_replacement_match(quote) and quote == norm(text).strip(' .,;:!?'):
        # A generic event has no old/new target roles. Fold only a complete
        # duplicate of the exact typed family assertion after that assertion's
        # own source parser establishes the new target and matching precision.
        typed = [candidate for candidate in entry['lines'] if candidate['type'] == 'family'
                 and norm(candidate['quote']).strip(' .,;:!?') == quote]
        wording = norm(line['fact'].get('what') or '').strip(' .,;:!?')
        stated = set(re.findall(r'[a-z]+', wording))
        allowed = {'family', 'visit', 'arrival', 'plan', 'moved', 'postponed', 'rescheduled', 'changed', 'new', 'my'}
        if not typed or not stated & {'visit', 'arrival', 'plan'} or not (stated <= allowed or wording == quote):
            return False
        timing = event_time(ep, entry, typed[0])
        plan_time = event_time(ep, {**entry, 'text': text, 'lines': []})
        return (timing.get('status') == 'confirmed'
                and all(timing.get(key) == plan_time.get(key) for key in ('when', 'precision', 'status', 'temporal_status')))
    calendar = {*MONTHS, *(month[:3] for month in MONTHS), *WEEKDAYS,
                "morning", "afternoon", "evening", "night", "am", "pm", "noon", "midday", "midnight",
                "today", "tomorrow", "yesterday", "tonight", "next", "last", "date", "day", "time", "st", "nd", "rd", "th"}
    first_person = (r"^(?:(?:change of plan|update):\s*)?(?:i|we|i'll|we'll|i'm|we're|i've|we've)"
                    r"(?:\s+(?:will|would|may|might|can|could|cannot|can't|won't|am|are|have|had|not|never|no|longer|be|plan|planning|to)){0,5}"
                    r"\s+(?:come|coming|arrive|arriving|arrived|visit|visiting|visited|be there|was there|got there)\b")
    date_words = "|".join(re.escape(word) for word in sorted(calendar | {"new", "on", "at", "in", "the"}, key=len, reverse=True))
    possessive = (rf"^(?:(?:replace|cancel|cancelled|canceled|withdraw)\s+)?(?:my|our)\s+"
                  rf"(?:(?:{date_words}|\d{{1,4}}(?:st|nd|rd|th)?)\s+)*(?:arrival|visit)s?\b")
    if not (re.search(first_person, quote) or re.search(possessive, quote)):
        return False
    allowed = calendar | set("family member members relative relatives i we my our their will would may might can could am are have had not never no longer be there come coming visit visits visiting visited arrival arrive arriving arrived new plan plans planned planning scheduled changed change replace replacement cancel cancelled canceled withdrawn on at in the a an for of and from until".split())
    stated = [word.removesuffix("'s") for word in re.findall(r"[a-z]+(?:'[a-z]+)?", norm(line["fact"].get("what") or ""))]
    intent = {"come", "coming", "visit", "visits", "visiting", "visited", "arrival", "arrive", "arriving", "arrived", "there", "plan", "plans", "replace", "replacement"}
    return bool(set(stated) & intent) and all(word in allowed for word in stated)


def _superseded_plan_restatement(ep: Episode, entry: dict, line: dict) -> bool:
    """A planned generic event inside a superseded family plan's own words.

    The member's newer (possibly withdrawn) family row owns that plan's status,
    so the sibling event must not return as a current 'Planned' row. Assertions
    outside the family assertion and unplanned observations keep their own cards.
    """
    quote = norm(line.get("quote") or "").strip(" .,;:!?")
    return (line["type"] == "event" and bool(quote) and quote in norm(family_plan_text(entry))
            and event_time(ep, entry, line).get("temporal_status") == "planned")


def _family_own_statement(row: dict) -> bool:
    """A family source's first-person event card ('I will not bring the keys ...').

    A member's arrangement is presented only through their family-plan row
    (ep.plans()). A negated, conditional, untagged or otherwise non-arrangement
    statement that stays an ordinary event card is a family note, never an
    upcoming 'Planned' arrangement; its row and stated date stay visible.
    """
    own = r"^(?:(?:change of plan|update):\s*)?(?:(?:if|unless|when|once|provided)\b[^,;]*,\s*)?(?:i|we)(?:'ll|'m|'re|'ve|'d)?\b"
    return (source_authority(row) == "family" and not shared_plan(row) and bool(row.get("lines"))
            and all(line["type"] == "event" and re.search(own, norm(line.get("quote") or "")) for line in row["lines"]))


def event_entries(ep: Episode, member: str, tz: str | None, excluded_facts=()) -> list[dict]:
    """Project important events, splitting different dates and never falling back to upload time."""
    active_plans = {p["update_id"]: p for p in ep.plans()}
    fulfilled = _fulfilled_booking_facts(ep)
    fulfilled.update(_replaced_plan_facts(ep))
    fulfilled.update(record['fact']['fact_id'] for record in ep._stay_source_records({'expected_discharge'})
                     if ep.discharge_plan_relation(record)['status'] == 'fulfilled')
    rows = []
    for entry in ep.timeline(member, tz):
        admission_context = _initial_admission_locations(ep, entry, excluded_facts)
        initial_locations = {line["fact"]["fact_id"] for values in admission_context.values() for line in values}
        clinical_supplements = [line for line in entry['lines'] if _clinical_event_supplement(ep, entry, line)]
        supplement_ids = {line['fact']['fact_id'] for line in clinical_supplements}
        # A member's plan that is no longer their latest one (ep.plans()).
        superseded_plan = shared_plan(entry) and entry["update_id"] not in active_plans and entry.get("author") in ep.members
        if shared_plan(entry):
            if entry["update_id"] in active_plans:
                plan = active_plans[entry["update_id"]]
                row = {**entry, "lines": [], "plan_text": plan["text"],
                       "plan_status": plan["plan_status"], "event_time": plan["event_time"]}
                if "supporting_sources" in plan:
                    row["supporting_sources"] = plan["supporting_sources"]
                rows.append({**row, "headline": plan_headline(ep, row)})
        groups = {}
        for ln in entry["lines"]:
            if (not important_line(ln, entry) or ln["fact"].get("fact_id") in excluded_facts
                    or ln["fact"].get("fact_id") in initial_locations
                    or (ln["fact"].get("fact_id") in fulfilled and not ln.get("contradicts") and not ln.get("time_uncertain"))
                    or ln['fact']['fact_id'] in supplement_ids
                    or (shared_plan(entry) and _family_plan_supplement(ep, entry, ln, family_plan_text(entry)))
                    or (superseded_plan and _superseded_plan_restatement(ep, entry, ln))):
                continue
            timing = event_time(ep, entry, ln)
            key = (timing.get("when") if timing.get("status") == "confirmed" else None,
                   timing.get("precision"), timing.get("status"), timing.get("temporal_status"),
                   event_time_text(timing, tz))
            groups.setdefault(key, {"time": timing, "lines": []})["lines"].append(ln)
        for group in groups.values():
            # The source's plan UI tag does not classify its independent
            # clinical assertions as family events. Preserve their own facts.
            context = [location for line in group["lines"]
                       for location in admission_context.get(line["fact"].get("fact_id"), [])]
            row = ep.render({**entry, "topic": None if shared_plan(entry) else entry.get("topic"),
                             "lines": [*group["lines"], *context]}, tz)
            if context:
                row["lines"] = [line for line in row["lines"] if line["fact"].get("fact_id") not in initial_locations]
            if (len(row['lines']) == 1 and row['lines'][0]['type'] == 'admitted' and not context
                    and re.search(r'\b(?:re)?admitted to\b', norm(row['lines'][0]['quote']))
                    and any(norm(line['quote']) == norm(row['lines'][0]['quote']) for line in clinical_supplements)):
                # Folding the generic restatement must not erase its only
                # visible place. Keep the exact same admission assertion on
                # this card; this supplies neither a new fact nor a current
                # location. The renderer still escapes the headline and keeps
                # the original applied/authority/conflict flags.
                prefix = 'Family reports: ' if row['headline'].startswith('Family reports: ') else ''
                row['headline'] = prefix + row['lines'][0]['quote']
            if shared_plan(entry) and all(line["type"] == "event" for line in group["lines"]):
                headlines, text = [], entry.get("text") or ""
                for line in group["lines"]:
                    quote = line["quote"]
                    matches = list(re.finditer(re.escape(quote), text)) if quote else []
                    if len(matches) == 1:
                        punctuation = re.match(r"[.!?]+(?=\s|$)", text[matches[0].end():])
                        if punctuation:
                            quote += punctuation[0]
                    headlines.append(quote)
                row["headline"] = " ".join(headlines)
            for line in row["lines"]:
                if _procedure_not_planned(entry, line) or _plan_cancelled(line["fact"]):
                    # Its own words, never 'Operation planned: <date>' or 'Expected to go home: <date>' (the line is
                    # this row's rendered copy).
                    line.update(text=line["quote"] + (line.get("suffix") or ""), not_planned=True)
            top = headline_line(row)
            if top is not None and top.get("not_planned"):
                prefix = 'Family reports: ' if row['headline'].startswith('Family reports: ') else ''
                row["headline"] = prefix + top["quote"]
            rows.append({**row, "new": entry.get("new", False), "event_time": group["time"]})
    def order(row):
        timing = row["event_time"]
        known = timing.get("status") == "confirmed" and bool(timing.get("when"))
        return (known, ep._utc(timing["when"]) if known else dt.datetime.min, row["seq"])
    return sorted(rows, key=order, reverse=True)


# This is a presentation topic, never an assertion that the tests are one event.
# Surgery and other procedures deliberately keep their existing event cards.
TEST_SUBJECT = re.compile(r"\b(?:examinations?|exams?|tests?|x[ -]?rays?|mri|ct|ultrasound|scans?|imaging|ecg|ekg)\b", re.I)
GENERIC_TEST = re.compile(r"(?:(?:some|a|an|the|further|more|additional|medical|diagnostic|routine|planned|scheduled|needed|required|necessary|and|tests?|examinations?|exams?)\b[\s.,-]*)+", re.I)
TEST_CHANGE = re.compile(r"\b(?:not|no|never|cancel\w*|postpon\w*|delay\w*|won't|cannot|can't|called off|put off|withdrawn|scrapped|dropped)\b", re.I)
# Display only: other words for a cancellation, read as 'cancelled' is (_test_not_upcoming) for a test and a procedure
# alike; 'dropped' only from a list ('dropped from the theatre list', never 'dropped off by her son'). The core's
# CANCELS is left as it is: it also guards the going-home and follow-up negation (episode.grounding_problem).
CHANGE_WORDS = r"(?:call(?:ed|ing|s)?|put(?:s|ting)?)\s+off|withdrawn|scrapped|dropped\s+(?:from|off)\s+(?:[a-z'-]+\s+){0,3}?list"
PLAN_CHANGE = re.compile(CANCELS.pattern + r"|\b(?:" + CHANGE_WORDS + r")\b")


def test_plan(fact: dict) -> bool:
    """Narrow display classifier over an already grounded procedure fact."""
    what = fact.get("what") or ""
    return (fact.get("type") == "procedure_planned" and bool(TEST_SUBJECT.search(what))
            and not re.search(r"\b(?:surgery|operations?|operative)\b", what, re.I))


def _test_not_upcoming(fact: dict) -> bool:
    """Conservative display guard for an explicit change to this test's plan.

    Rule: the test leaves Right now and What's next only when the quote
    explicitly cancels, postpones or delays it (or says it is not needed) and no
    unhedged re-plan follows the LAST such statement. A statement counts when
    it names the test, directly or through a date/time phrase ('the MRI on 18
    October has been cancelled', 'the MRI scheduled for ...', 'the MRI at 14:00
    ...', 'we cancelled the MRI'), or is an elliptical clause after the test
    with no other test or operation named in between ('..., but has now been
    cancelled', 'but it has since been cancelled', 'and was then cancelled').
    A negated or modal cancellation ('has not been cancelled', 'may be
    cancelled', 'do not cancel'), one under its own condition ('... if the
    scanner is down', 'If ..., the MRI will be cancelled') and a negated
    instruction (contrast, fasting) are not changes. An unhedged rebooking or
    new date or time after the last change ('cancelled, but is now planned for
    tomorrow', 'postponed to 20 October') keeps the test upcoming, as its core
    procedure record already is. This does not create a cancellation state or
    alter the core procedure; the quote stays in the topic and source archive.
    """
    what, quote = norm(fact.get("what") or ""), norm(fact.get("quote") or "")
    generic = {"test", "tests", "exam", "exams", "examination", "examinations", "scan", "scans", "imaging"}
    subjects = {what}
    for match in TEST_SUBJECT.finditer(what):
        word = match.group(0)
        if GENERIC_TEST.fullmatch(what) or word not in generic:
            subjects.add(word)
    subject = r"\b(?:" + "|".join(re.escape(value) for value in sorted(subjects, key=len, reverse=True) if value) + r")\b"
    head = subject + r"(?:\s+(?:scans?|tests?|exams?|examinations?|imaging|appointments?))*"
    weekday = "|".join(WEEKDAYS)
    target = rf"(?:{_family_target_pattern()}|today|tonight|tomorrow|(?:next|this)\s+(?:week|{weekday})|{weekday})\b"
    clock = r"(?:\d{1,2}[:.]\d{2}(?:\s*[ap]\.?m\.?)?|\d{1,2}\s*[ap]\.?m\.?|noon|midday)"
    # 'The MRI (that was) scheduled for 18 October at 14:00 ...' still names this test.
    dated = (r"(?:\s+(?:(?:that|which)\s+(?:is|was|had\s+been|has\s+been)\s+)?(?:(?:originally|previously|first)\s+)?"
             r"(?:(?:planned|booked|scheduled|arranged|due|set)\s+)?(?:(?:on|at|for|from)\s+)?"
             rf"(?:{target}|{clock}|this\s+(?:morning|afternoon|evening))(?:\s+(?:in\s+the\s+)?(?:morning|afternoon|evening|night))?){{0,3}}")
    link = r"(?:\s+(?:is|are|was|were|has|have|had|been|being|be|now|currently|will|would|may|might)){0,5}\s+"
    firm = r"(?:\s+(?:is|are|was|were|has|have|had|been|being|be|now|currently|will)){0,5}\s+"   # 'may be cancelled' is not a change
    action = r"(?:cancel\w*|postpon\w*|delay\w*|" + CHANGE_WORDS + r")\b"
    negative = r"(?:not|no longer|isn't|aren't|wasn't|weren't|won't|cannot|can't)(?:\s+(?:be|been|being|now|currently))*\s+(?:required|needed|planned|booked|scheduled)\b"
    halted = r"(?:not|no longer|isn't|aren't|wasn't|weren't|won't|cannot|can't)(?:\s+(?:be|been|being|now|currently))*\s+go(?:es|ing)?\s+ahead\b"   # firm only: 'may not go ahead' keeps it
    negated_action = (r"\b(?:not|never|don't|doesn't|didn't|haven't|hasn't|hadn't|won't|can't|cannot|may|might|could|would|should)"
                      r"(?:\s+(?:be|been|being|ever|yet|actually|going|to|have|need|want|plan|intend))*\s*$")

    def unconditional(match, sentence=True):
        # Only the cancellation's own clause may qualify it; a condition on a later re-plan belongs to that re-plan.
        clause = re.split(r"[,;.]|\b(?:but|and|then|however|although|though)\b", quote[match.end():])[0]
        opening = re.split(r"[.;!?]", quote[:match.start()])[-1]
        return not (re.search(r"\b(?:if|unless|provided|once|pending|subject to|depending on)\b", clause)
                    or sentence and re.match(r"\s*(?:if|unless)\b", opening))
    # '..., but has now been cancelled' after the test; never 'and cancelled the CT'.
    elliptical = (r"(?:[,;]|\b(?:and|but|then|later|since))(?:\s+(?:it|that|this|which))?"
                  r"(?:\s+(?:is|was|were|has|have|had|been|being|be|now|then|since|again|also|later|subsequently|got)){0,5}\s+"
                  + action + r"(?!\s+(?:the|a|an|her|his|their|its|my|our|your|these|those|all|any|some|both)\b)"
                  r"(?!\s+(?:[a-z]+\s+)?" + TEST_SUBJECT.pattern + ")")
    # A coordinated test ('MRI and CT were ...') shares the elliptical clause; another clause's test does not.
    mentions = list(re.finditer(head + r"(?:\s*(?:,|\band\b|\bor\b|&)\s*(?:the\s+)?(?:[a-z]+\s+)?" + TEST_SUBJECT.pattern
                                + r"(?:\s+(?:scans?|tests?|exams?|examinations?|imaging|appointments?))*)*", quote))
    other = re.compile(TEST_SUBJECT.pattern + r"|\b(?:surgery|operations?|operative)\b")

    def own_clause(match):
        before = [mention for mention in mentions if mention.end() <= match.start()]
        between = quote[before[-1].end():match.start()] if before else ""
        hedge = r"(?:\b(?:not|never|may|might|could|would|should|will)|n't)(?:\s+(?:it|that|this|which|is|was|were|has|have|had|been|being|be|now|also))*\s*$"
        return (bool(before) and not any(word not in subjects for word in other.findall(between))
                and not re.search(hedge, quote[:match.start()]) and unconditional(match, sentence=False))
    changes = [*(match for match in re.finditer(head + dated + firm + action, quote) if unconditional(match)),
               *re.finditer(head + dated + link + negative, quote),
               *(match for match in re.finditer(head + dated + firm + halted, quote) if unconditional(match)),
               *(match for match in re.finditer(action + r"\s+(?:(?:the|her|his|a|an|planned|scheduled)\s+)*" + head + dated, quote)
                 if not re.search(negated_action, quote[:match.start()]) and unconditional(match)),
               *re.finditer(r"\bno\s+" + subject + link + r"(?:required|needed|planned|booked|scheduled)\b", quote),
               *re.finditer(r"\b(?:does not|do not|doesn't|don't|no longer)\s+(?:need|require)\s+(?:(?:the|a|an|any|further)\s+)*" + subject, quote),
               *(match for match in re.finditer(elliptical, quote) if own_clause(match))]
    if not changes:
        return False
    last = max(changes, key=lambda match: match.end())
    rest = quote[last.end():]
    # A new date or time right after a postponement, a delay or a hold ('postponed from Thursday to Friday').
    rebooked = (re.match(r"\s*,?\s*(?:from\s+[^,;.!?]*?\s+)?(?:to|until|till)\s+" + rf"(?:{target}|{clock})", rest)
                if re.search(r"\b(?:postpon|delay|put(?:s|ting)?\s+off)|\bahead$", last.group(0)) else None)
    replan = (r"\b(?:re-?book\w*|re-?schedul\w*|re-?arrang\w*"
              rf"|(?:moved|brought\s+forward|changed)(?:\s+(?:it|this|that))?\s+to\s+{target}"
              r"|now(?:\s+(?:been|being|be))*\s+(?:planned|booked|scheduled|arranged)\b"
              r"|(?:planned|booked|scheduled|arranged)\s+again\b)")
    hedged = (r"\b(?:not|never|no|nobody|may|might|could|would|should|if|unless|whether|perhaps|possibly|maybe|probably"
              r"|hop\w*|tr(?:y|ies|ying)|await\w*|waiting|yet|need\w*)\b|n't\b")
    for match in ([] if rebooked else re.finditer(replan, rest)):
        # Only the re-plan's own clause may qualify it; a condition may follow it.
        clause = re.split(r"[,;.]|\b(?:but|and|then|however|although|though)\b", rest[:match.start()])[-1]
        condition = re.search(r"\b(?:if|unless|provided|once|pending|subject to|depending on)\b", re.split(r"[;.]", rest[match.end():])[0])
        if not re.search(hedged, clause) and not condition:
            rebooked = match
            break
    # A later elliptical cancellation of the same test is itself a change, so it is never followed here.
    return rebooked is None


def _procedure_not_planned(entry: dict, line: dict) -> bool:
    """A procedure plan (not a test: a test topic reads its own quote above) whose quote says it will not happen.

    The core keeps such a procedure_planned ('The surgeon will not operate tomorrow morning', 'Surgery is not
    required'), so the display reads the negation as the core reads a going-home plan (episode._plan_negated, scoped to
    the parts that say the plan's time, or else its name) or as a test topic does (_test_not_upcoming). A negation in
    another clause ('..., fasting is not required'), a time bound and a re-plan keep the plan. The core has no
    cancelled state either, so a cancellation ('Surgery has been cancelled', 'called off', 'withdrawn', 'scrapped': the
    words of PLAN_CHANGE) and a postponement or delay are read as a test topic reads them (_test_not_upcoming): a
    negated, modal or conditional one ('has not been called off', 'may be cancelled if ...'), a new date right after a
    postponement ('postponed to Friday') and a later re-plan ('cancelled today and is rebooked for Friday') keep the
    plan; a postponement or delay without a new date does not. No core state changes.
    """
    fact = line["fact"]
    if fact.get("type") != "procedure_planned" or test_plan(fact):
        return False
    quote = norm(fact.get("quote") or "").strip(" .,;:!?")
    if not quote:
        return False
    if PLAN_CHANGE.search(quote):
        return _plan_cancelled(fact)
    text = norm(entry.get("text") or "")
    spots = [m.start() for m in re.finditer(r"(?<![a-z0-9])" + re.escape(quote) + r"(?![a-z0-9])", text)]
    if not spots:
        text, spots = quote, [0]
    # The core fills a missing when_text with the whole quote, which names no time words: then the plan's name scopes it.
    said = fact.get("when_text") or ""
    if not said or norm(said).strip(" .,;:!?") == quote:
        said = fact.get("what") or ""
    # A modal negation ('Surgery may not go ahead tomorrow') is not a change, as a test topic reads it (halted); the
    # 'not' is blanked in place, so the quote's positions in the text are kept.
    text = re.sub(r"\b(may|might|could)(\s+)not\b", lambda m: m.group(1) + m.group(2) + "   ", text)
    return _test_not_upcoming(fact) or all(_plan_negated(text, start, start + len(quote), said) for start in spots)


# The names a cancellation may use for a plan besides its own 'what' ('Surgery tomorrow morning has been cancelled' for
# 'Hip surgery'); each is read by the same reader with the same keep-rules (_test_not_upcoming).
PLAN_NOUNS = {"procedure_planned": ("surgery", "operation", "procedure"),
              "expected_discharge": ("going home", "discharge home", "discharge"),
              "follow_up": ("clinic", "appointment", "follow-up", "follow up", "review")}


def _plan_cancelled(fact: dict) -> bool:
    """A procedure, going-home or follow-up plan whose quote reports a cancellation (PLAN_CHANGE) by its own name, a
    noun in that name or the plan's usual name. A negated, modal or conditional cancellation, a rebooking after it and
    a postponement to a new date keep the plan, as for a test (_test_not_upcoming). No core state changes."""
    if fact.get("type") not in PLAN_NOUNS or not PLAN_CHANGE.search(norm(fact.get("quote") or "")):
        return False
    what = norm(fact.get("what") or "")
    names = [what, *re.findall(r"\b(?:surgery|operation|procedure|clinic|appointment|review)\b", what),
             *PLAN_NOUNS[fact["type"]]]
    return any(_test_not_upcoming({**fact, "what": name}) for name in dict.fromkeys(name for name in names if name))


def headline_line(e: dict) -> dict | None:
    """The line a rendered entry's headline tells, in the core's precedence (Episode.render): the news of the update
    (two different answers, an answer that settles them, the same answer said again), else the top line."""
    return next((x for x in e["lines"] if x.get("two_answers") or x.get("settles") or x.get("said_again")), None) or top_line(e)


def _claim_authority(entry: dict, line: dict, record: dict | None) -> str:
    if record is not None:
        return record["authority"]
    if source_authority(entry) == "family" or line.get("unconfirmed") or line.get("contradicts"):
        return "family"
    # A changed line may agree with a clinician, so unconfirmed can be false.
    quote, text = norm(line.get("quote") or "").strip(" .,;:!?"), norm(entry.get("text") or "")
    spans = Episode._line_spans(entry.get("text") or "", (entry.get("reading") or {}).get("changed_lines") or [])
    if quote and any(a < match.start() + len(quote) and match.start() < b
                     for match in re.finditer(re.escape(quote), text) for a, b in spans):
        return "family"
    return entry["authority"]


def _test_supplement(line: dict, plans: list[dict]) -> bool:
    """Fold only a test-only restatement sharing an exact source quote.

    Unknown words keep the generic event on the timeline: a fall, pain, admission
    or any other independent observation must not disappear with a test plan.
    """
    if line["type"] != "event" or not TEST_SUBJECT.search(line["fact"].get("what") or ""):
        return False
    if not any(norm(line["quote"]) == norm(plan["quote"]) for plan in plans):
        return False
    text = TEST_SUBJECT.sub(" ", norm(line["fact"].get("what") or ""))
    allowed = set("she he they her his their patient mum mom mother father is are was were will would may might must needs need needed requires require required have has had having undergo scheduled planned planning for to on at and or of a an the some further more additional medical diagnostic routine necessary tomorrow today morning afternoon evening night not no longer be been it this that".split())
    return all(word in allowed for word in re.findall(r"[a-z]+", text))


def presentation_model(ep: Episode, member: str | None, tz: str | None, now: str | None = None) -> dict:
    """New, read-only view model shared by timeline, Right now and What's next.

    Fact/source identities, core procedure state and QA remain untouched. A topic
    collects evidence within one recorded stay; None remains a separate scope.
    Each claim keeps its own calendar evidence and authority.
    """
    records = {}
    for procedure in ep.procedures.values():
        for record in [procedure, *procedure.get("history", [])]:
            fact_id = record["fact"].get("fact_id")
            alternative = (procedure.get("two_answers") or {}).get("other") or {}
            state = ("alternative" if fact_id == alternative.get("fact", {}).get("fact_id") else
                     "earlier" if record is not procedure else "completed" if procedure["status"] == "done" else "current")
            records[fact_id] = (record, procedure, state)
    topics, consumed, not_planned = {}, set(), set()
    for entry in ep.timeline(member, tz):
        not_planned.update(line["fact"]["fact_id"] for line in entry["lines"]
                           if line["fact"].get("fact_id") is not None and _procedure_not_planned(entry, line))
        plans = [line for line in entry["lines"] if test_plan(line["fact"])]
        for line in plans:
            fact = line["fact"]
            record, procedure, state = records.get(fact.get("fact_id"), (None, None, "reported"))
            stay_id = record.get("stay_id") if record is not None else None
            topic = topics.setdefault(stay_id, {"stay_id": stay_id, "claims": [], "sources": {}, "supplements": []})
            claim = {"fact_id": fact.get("fact_id"), "update_id": entry["update_id"],
                     "source_revision": entry.get("source_revision") or 1, "fact": fact, "line": line,
                     "entry": entry, "event_time": event_time(ep, entry, line),
                     "authority": _claim_authority(entry, line, record), "state": state,
                     "stay_id": stay_id, "procedure": procedure,
                     "nonspecific": bool(GENERIC_TEST.fullmatch(fact.get("what") or ""))}
            topic["claims"].append(claim)
            topic["sources"][(claim["update_id"], claim["source_revision"])] = entry
            if claim["fact_id"] is not None:
                consumed.add(claim["fact_id"])
        for line in entry["lines"]:
            if _test_supplement(line, plans):
                if line["fact"].get("fact_id") is not None:
                    consumed.add(line["fact"]["fact_id"])
                # It is still present, verbatim, in this source's details.
                for topic in topics.values():
                    if any(claim["update_id"] == entry["update_id"] for claim in topic["claims"]):
                        topic["supplements"].append(line)
    active_stay = getattr(ep, "_active_stay_id", None)
    ordered_topics = sorted(topics.values(), key=lambda topic: max(c["entry"]["seq"] for c in topic["claims"]), reverse=True)
    for index, topic in enumerate(ordered_topics, 1):
        topic["id"] = f"cr-tests-{index}"
        topic["title"] = "Tests and examinations"
        topic["source_count"] = len(topic["sources"])
        topic["new"] = any(entry.get("new") for entry in topic["sources"].values())
        topic["scope"] = ("Hospital stay not established" if topic["stay_id"] is None else
                          "Current hospital stay" if topic["stay_id"] == active_stay and "discharged" not in ep.slots else
                          "Separate hospital stay")
        candidates = [c for c in topic["claims"] if c["state"] not in {"earlier", "completed"}]
        named = [c for c in candidates if not c["nonspecific"]]
        def conflict(claim):
            return bool(claim["line"].get("contradicts") or claim["line"].get("time_uncertain")
                        or claim["state"] == "alternative" or (claim["procedure"] or {}).get("two_answers"))
        important = [c for c in candidates if conflict(c) or TEST_CHANGE.search(c["fact"]["quote"])]
        # Nonspecific mentions are evidence, not an extra scheduled examination.
        visible, signatures = [], set()
        for claim in [*(named or candidates[:1]), *important]:
            timing, line = claim["event_time"], claim["line"]
            signature = (norm(claim["fact"]["what"]), timing.get("when"), timing.get("precision"),
                         timing.get("status"), timing.get("temporal_status"), claim["authority"],
                         line.get("applied"), line.get("unconfirmed"), line.get("contradicts"),
                         line.get("late"), conflict(claim),
                         claim["fact"]["quote"] if TEST_CHANGE.search(claim["fact"]["quote"]) else None)
            if signature not in signatures:
                visible.append(claim)
                signatures.add(signature)
        topic["visible"], topic["conflict"] = visible, any(conflict(c) for c in candidates)
        topic["dated_nonspecific"] = any(c["nonspecific"] and c["event_time"]["status"] == "confirmed" for c in candidates) and bool(named)
        eligible = [c for c in topic["claims"] if c["state"] == "current" and not _test_not_upcoming(c["fact"])
                    and (active_stay is None or c["stay_id"] == active_stay)
                    and (not now or ep._utc(c["event_time"].get("when")) >= ep._utc(now))]
        topic["upcoming"] = bool(eligible)
        # This orders the topic link only; it is never a date for the topic or
        # for another claim (including a named test with no date of its own).
        topic["_sort_when"] = min((c["event_time"].get("when") for c in eligible), key=ep._utc, default=None)
    next_items = []
    def add_next(record):
        when = record["fact"].get("when")
        if now and ep._utc(when) < ep._utc(now):
            return
        two = record.get("two_answers")
        text = (f"{ep.subject(record['fact'])}: {ep.answer(two['other']['fact'], tz)} or {ep.answer(record['fact'], tz)}? (two different answers: ask which is right)"
                if two else ep.describe(record["fact"], tz=tz) + (" (reported by family, not confirmed)" if record["authority"] == "family" else ""))
        if record['fact']['type'] == 'expected_discharge' and 'discharged' in ep.slots:
            text = ('Discharge plan: confirm which admission — ' + text if two else ep.discharge_plan_text(record, tz))
        next_items.append({"text": text, "target": None, "_sort_when": when})
    # A procedure whose quote says it will not happen is not upcoming (the core keeps it planned).
    unplanned = {key for key, p in ep.procedures.items() if p["status"] == "planned" and p["fact"].get("fact_id") in not_planned}
    for key, procedure in ep.procedures.items():
        if procedure["status"] == "planned" and not test_plan(procedure["fact"]) and key not in unplanned:
            add_next(procedure)
    # A going-home or follow-up plan whose current quote reports a cancellation is not upcoming either (the core keeps it).
    discharge_plan = ep.pending_discharge_plan()
    cancelled = [r["fact"].get("fact_id") for r in [discharge_plan, *ep.follow_ups.values()] if r and _plan_cancelled(r["fact"])]
    if discharge_plan and not _plan_cancelled(discharge_plan["fact"]):
        add_next(discharge_plan)
    for follow_up in ep.follow_ups.values():
        if not _plan_cancelled(follow_up["fact"]):
            add_next(follow_up)
    next_items += [{"text": f"{topic['title']} · {topic['source_count']} source{'s' if topic['source_count'] != 1 else ''}",
                    "target": topic["id"], "_sort_when": topic["_sort_when"]} for topic in ordered_topics if topic["upcoming"]]
    next_items.sort(key=lambda item: (item['text'].startswith('Discharge plan: confirm which admission'), ep._utc(item["_sort_when"])))
    pending = [p for key, p in ep.procedures.items() if p["status"] == "planned" and key not in unplanned]
    neutral_phase = bool(pending and test_plan(pending[0]["fact"]) and "discharged" not in ep.slots)
    phase = None
    if unplanned:   # the core's own phase, read on a shallow copy without those procedures ('Waiting for ...')
        shown = copy.copy(ep)
        shown.procedures = {key: p for key, p in ep.procedures.items() if key not in unplanned}
        phase = shown.phase()
    return {"entries": event_entries(ep, member, tz, consumed), "test_topics": ordered_topics,
            "next": next_items, "test_phase": neutral_phase, "not_planned": sorted(unplanned),
            "phase": phase, "cancelled": cancelled,
            "discharge_cancelled": bool(discharge_plan and _plan_cancelled(discharge_plan["fact"]))}


def _next_html(item: dict) -> str:
    text = esc(arrows(item["text"]))
    return f'<a href="#{esc(item["target"])}">{text}</a>' if item["target"] else text


def test_topics_html(ep: Episode, topics: list[dict], tz: str | None, photo_of) -> str:
    """Undated topic summaries sit outside the event-date rail."""
    colors, output = colors_of(ep), []
    def claim_html(claim, detailed=False):
        timing, line = claim["event_time"], claim["line"]
        authority = "reported by family" if claim["authority"] == "family" else "care-team source"
        state = {"earlier": "Earlier source statement", "completed": "Plan followed by a recorded completion",
                 "reported": "Source report; not the standing plan", "alternative": "Conflicting source statement"}.get(claim["state"], "Source statement")
        body = (f'<b>{esc(claim["fact"]["what"])}</b> · {esc(event_time_text(timing, tz))} · {authority}'
                f'{line_badges(line)}')
        if detailed or TEST_CHANGE.search(claim["fact"]["quote"]):
            body += f'<div>“{esc(claim["fact"]["quote"])}”</div>'
        if detailed:
            body += f'<div class="cr-quiet">{state} · {esc(claim["entry"].get("author_name") or "")}'
            if timing.get("status") != "confirmed":
                body += f' · {esc(timing.get("reason") or "Event timing is unresolved.")}'
            body += '</div>'
        return (f'<li class="cr-claim" data-fact-id="{esc(claim["fact_id"])}" '
                f'data-update-id="{esc(claim["update_id"])}" data-source-revision="{claim["source_revision"]}">{body}</li>')
    for topic in topics:
        new = '<span class="cr-new">NEW</span>' if topic["new"] else ""
        claims = ''.join(claim_html(claim) for claim in topic["visible"])
        timing_note = ('<div class="cr-quiet">A date was also stated for an unspecified examination. The sources do not link that date to the named tests.</div>'
                       if topic["dated_nonspecific"] else '')
        conflict_note = ('<div class="cr-badge cr-badge-amber">Conflicting source statements: check with the care team</div>'
                         if topic["conflict"] else '')
        if not claims:
            claims = '<li>Earlier examination plans are kept in the source history below.</li>'
        history = ''.join(claim_html(claim, True) for claim in topic["claims"])
        sources = ''.join(f'<section><div class="cr-srcrow">{source_line(ep, entry, colors)}</div>'
                          f'{thumb(photo_of(entry), "Photo: " + (entry.get("photo_of") or "document"))}{source_details(entry)}</section>'
                          for entry in sorted(topic["sources"].values(), key=lambda entry: entry["seq"], reverse=True))
        output.append(f'<section class="cr-test-topic" id="{topic["id"]}" aria-label="Tests and examinations">'
                      f'<div class="cr-meta">{esc(topic["scope"])} {new}</div>'
                      f'<div class="cr-h3 cr-display" role="heading" aria-level="3">{topic["title"]}</div>'
                      f'{conflict_note}<ul class="cr-list">{claims}</ul>{timing_note}'
                      '<details><summary>Sources and history '
                      f'({topic["source_count"]} source{"s" if topic["source_count"] != 1 else ""})</summary>'
                      '<div class="cr-quiet">These are related source statements, not a confirmed single appointment. '
                      'Each date belongs only to its own words; checking source words is separate from confirming event timing.</div>'
                      f'<ul class="cr-list">{history}</ul>{sources}</details></section>')
    return ''.join(output)


def event_clock(e: dict, tz: str | None) -> str:
    timing = e.get("event_time") or {}
    if timing.get("time_role") == "withdrawn_target":
        return "Cancelled target: " + event_time_text({**timing, "status": "confirmed"}, tz)
    if timing.get("status") != "confirmed":
        return event_time_text(timing, tz)
    when = parse_when(timing.get("when"))
    if isinstance(when, dt.datetime):
        return f"{local(timing['when'], tz):%H:%M}"
    if timing.get("precision") == "part_of_day":
        parts = set(re.findall(r"\b(morning|afternoon|evening|night)\b", timing.get("when_text") or "", re.I))
        return next(iter(parts)).lower() if len(parts) == 1 else ""
    return ""


def top_line(e: dict) -> dict | None:
    return min(e["lines"], key=lambda x: (not x["applied"], ORDER.index(x["type"]))) if e["lines"] else None


def display_headline(e: dict) -> str:
    """The headline the timeline shows for a rendered entry (what ep.add_update returns), for a message about it such
    as the page's 'Timeline updated: ...'. A procedure its quote says will not happen or was cancelled is told in its
    own words as on its card (event_entries), and so is a test that is not upcoming (its topic shows the quote), never
    '<what> planned: <date>'; anything else keeps the core headline."""
    top = headline_line(e)
    if top is None or not (top.get("not_planned") or _procedure_not_planned(e, top) or _plan_cancelled(top["fact"])
                           or test_plan(top["fact"]) and _test_not_upcoming(top["fact"])):
        return e["headline"]
    return ("Family reports: " if e["headline"].startswith("Family reports: ") else "") + top["quote"]


def kind_of(e: dict) -> str:
    """key (a care-team event that changes the picture), reference (practical facts only) or note (everything else)."""
    if shared_plan(e):
        return "note"
    top = top_line(e)
    if top is None:
        return "note"
    if all(ln["type"] in REFERENCE_TYPES and ln["applied"] for ln in e["lines"]):   # a disputed or late one is a note
        return "reference"
    if e["authority"] == "care_team" and top["type"] in KEY_TYPES and top["applied"]:
        return "key"
    return "note"


def ward_text(ln: dict, remote: bool) -> str:
    """A line's text, escaped; visiting hours and the ward round get "(hospital's local time)" for a viewer elsewhere."""
    return esc(arrows(ln["text"])) + (" (hospital's local time)" if remote and ln["type"] in ("visiting", "rounds") else "")


def line_badges(ln: dict) -> str:
    out = ""
    if ln.get("time_uncertain"):
        out += ' <span class="cr-badge cr-badge-amber">pending confirmation: event time or order is unclear</span>'
    if ln.get("changed_from"):
        out += f' <span class="cr-was">was: {esc(arrows(ln["changed_from"]))}</span>'
    if ln.get("two_answers"):
        out += ' <span class="cr-badge cr-badge-amber">two different answers: ask which is right</span>'
    if ln.get("settles"):
        out += ' <span class="cr-badge cr-badge-gray">settled</span>'
    if ln.get("contradicts"):
        out += ' <span class="cr-badge cr-badge-red">the care team said otherwise</span>'
    elif ln.get("unconfirmed"):
        out += ' <span class="cr-badge">reported by family</span>'
    return out


FLAG = {"contradicted": ("the care team said otherwise", "cr-badge-red"), "late": ("added late; a newer update stands", "cr-badge-gray"),
        "unconfirmed": ("reported by family", ""), "two_answers": ("two different answers: ask which is right", "cr-badge-amber")}


def flag_badge(flag: str | None) -> str:
    if not flag:
        return ""
    text, cls = FLAG[flag]
    return f' <span class="cr-badge {cls}">{esc(text)}</span>'


def source_line(ep: Episode, e: dict, colors: dict) -> str:
    who = person(ep, e.get("author"), colors)
    reading = e.get("reading") or {}
    n = int(reading.get("confirmed_lines") or 0)
    checked = f", {n} line(s) with numbers or stop / continue checked" if n else ""
    if e["kind"] == "recording":
        written = f" · written out{checked}" if reading.get("method") == "asr" else ""
        if source_authority(e) == "family":
            return f"Family recording · {esc(e.get('speaker') or e.get('author_name') or 'family member')} · added by {who}{written}"
        return (f'<span class="cr-care">{icon("care", 14, 2)}{esc(e.get("speaker") or "Clinician")}</span>'
                f" · recorded by {who}{written}")
    if e["kind"] == "photo":
        read = f" · read by a vision model{checked}" if reading.get("method") == "model" else ""
        return f"Photo of {esc((e.get('photo_of') or 'a document').lower())} · added by {who}{read}"
    return f"Note from {who}" + (" · speech-to-text" if reading.get("method") == "asr" else "")


def source_details(e: dict) -> str:
    quotes = "".join(f"<li>“{esc(f['quote'])}” → {esc(f['type'].replace('_', ' '))}</li>" for f in e["facts"])
    rejected = "".join(f"<li>Not shown ({esc(r['reason'])}): "
                       f"{esc(r['fact'].get('type', 'fact') if isinstance(r['fact'], dict) else 'fact')}</li>" for r in e["rejected"])
    reading, how = e.get("reading") or {}, ""
    if reading.get("method") == "recorded":
        how = ("Text read from the photo: recorded for the demo (live, a vision model reads it and the caregiver checks it "
               "before it is added). ")
    elif reading.get("method") == "asr" and e["kind"] == "note":
        how = (f'Family words recognized by speech-to-text ({esc(reading.get("model") or "speech-to-text")}). '
               'You can correct these words using Correct an update. ')
    elif reading.get("method") in ("model", "asr"):   # a vision model read the photo, or speech-to-text the recording
        changed, what = reading.get("changed_lines") or [], "photo" if reading["method"] == "model" else "recording"
        how = ((f"Text read from the photo by {esc(reading.get('model') or 'the vision model')}; " if what == "photo" else
                f"Written out from the recording by {esc(reading.get('model') or 'speech-to-text')}; ")
               + f"{esc(reading.get('checked_by') or 'the caregiver')} ticked {int(reading.get('confirmed_lines') or 0)} line(s) "
               f"with numbers or stop / continue as checked against the {what}"
               + ("; changed by hand, so shown as reported by family: " + "; ".join(f"“{esc(c)}”" for c in changed) if changed
                  else "; no lines changed by hand") + ". ")
        if reading.get("model_text") and changed:
            how += "The model's reading: " + esc(" / ".join(ln.strip() for ln in reading["model_text"].splitlines() if ln.strip())) + ". "
    if reading.get("method") == "family_correction":
        how = "Source words corrected and checked by the family. "
    if e["method"] == "llm":
        origin = "Facts from the live model." if quotes or rejected else "The live model found no facts in it."
    else:   # the demo story's recorded extraction, or an update added with no model connected
        origin = "Facts from the recorded demo extraction." if quotes or rejected else "No facts were read from it (no model connected)."
    return (f'<details class="cr-src"><summary>Source</summary><blockquote>{lines_br(e.get("text"))}</blockquote>'
            f'<ul class="cr-list">{quotes}{rejected}</ul><div>{how}{origin}</div></details>')


def lines_br(s) -> str:
    """Escaped, one line per line: a blank line inside st.markdown's HTML would end the HTML block."""
    return "<br>".join(esc(ln) for ln in str(s or "").splitlines() if ln.strip())


def thumb(data: bytes | None, alt: str) -> str:
    if not data:
        return ""
    mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return f'<img class="cr-thumb" src="data:{mime};base64,{base64.b64encode(data).decode()}" alt="{esc(alt)}">'


def source_archive_html(ep: Episode, photo_of=lambda e: None) -> str:
    """Keep every original source available without turning upload times into events."""
    if not ep.entries:
        return ""
    colors = colors_of(ep)
    sources = "".join(f'<section><div class="cr-srcrow">{source_line(ep, e, colors)}</div>'
                      f'{thumb(photo_of(e), "Photo: " + (e.get("photo_of") or "document"))}'
                      f'{source_details(e)}</section>' for e in reversed(ep.entries))
    return ('<div class="cr"><details class="cr-source-archive"><summary>Source documents and messages</summary>'
            f'{sources}</details></div>')


def key_entry(ep: Episode, e: dict, colors: dict, tz: str | None, photo: bytes | None, remote: bool = False) -> str:
    top = top_line(e)
    changed = bool(top["changed_from"]) and top["type"] != "medication"
    dot = AMBER if changed else f"var(--cr-key,{BLUE})"   # a look may recolour key events (a token, same blue by default)
    head = esc(arrows(e["headline"]))
    body_lines = [ln for ln in e["lines"] if ln is not top and ln["text"] not in e["headline"]]
    m = re.match(r"^(.*) moved: (.*) -> (.*)$", e["headline"])
    if m:   # 'Going home moved: Fri 23 Oct -> Sat 24 Oct morning'
        head = f'{esc(m.group(1))} moved to <span class="cr-amber">{esc(m.group(3))}</span>'
        body_lines = [{"text": f'<s class="cr-quiet">{esc(m.group(2))}</s> → {esc(m.group(3))}', "_html": True}] + body_lines
    if top["type"] == "medication":
        items = []
        for ln in [x for x in e["lines"] if x["type"] == "medication"]:
            f = ln["fact"]
            body = esc(" ".join(x for x in (f["name"], f.get("dose"), f.get("frequency")) if x))
            if f["status"] == "stop":
                items.append(f'<li class="cr-quiet"><b class="cr-stop">Stopped</b> · <s>{esc(f["name"])}</s>{line_badges(ln)}</li>')
            else:
                label = {"new": "New", "continue": "Continue", "change": "Changed"}[f["status"]]
                cls = ' class="cr-quiet"' if f["status"] == "continue" else ""
                items.append(f"<li{cls}><b>{label}</b> · {body}{line_badges(ln)}</li>")
        others = "".join(f"<li>{ward_text(ln, remote)}{line_badges(ln)}</li>" for ln in e["lines"] if ln["type"] != "medication")
        details = f'<ul class="cr-list cr-meds">{"".join(items)}</ul>' + (f'<ul class="cr-list">{others}</ul>' if others else "")
    else:
        details = ('<ul class="cr-list">' + "".join(
            f"<li>{ln['text'] if ln.get('_html') else ward_text(ln, remote)}{'' if ln.get('_html') else line_badges(ln)}</li>"
            for ln in body_lines) + "</ul>") if body_lines else ""
    clock = event_clock(e, tz)
    new = '<span class="cr-new">NEW</span>' if e.get("new") else ""
    return (f'<article class="cr-ev cr-key" data-headline="{esc(e["headline"])}"><span class="cr-dot" style="background:{dot}">'
            f'{icon(ICON_OF.get(top["type"], "care"))}</span>'
            f'<div class="cr-meta"><span class="cr-time">{esc(clock)}</span>{new}'
            f'<span>{esc(CATEGORY["procedure_done"] if top.get("not_planned") and top["type"] == "procedure_planned" else CATEGORY.get(top["type"], ""))}</span>'
            f'{flag_badge(e.get("headline_flag"))}</div>'
            f'<div class="cr-h3 cr-display" role="heading" aria-level="3">{head}</div>'
            f'<div class="cr-body">{details}{thumb(photo, "Photo: " + (e.get("photo_of") or "document"))}</div>'
            f'<div class="cr-srcrow"><span>{source_line(ep, e, colors)}</span>{source_details(e)}</div></article>')


def note_text(ep: Episode, e: dict, colors: dict, ward_shown: bool = True, remote: bool = False) -> str:
    """One quiet line: who, then what the update says. Every fact of the update stays on the line with its own badge."""
    who, name = person(ep, e.get("author"), colors), ep.members.get(e.get("author"), {}).get("name") or ""
    if shared_plan(e):
        label = {"withdrawn": "Plan withdrawn", "completed": "Family report"}.get(e.get("plan_status"))
        return f'{who}: {esc(plan_headline(ep, e))}' + (f' <span class="cr-badge">{label}</span>' if label else "")
    care = f'<span class="cr-care">{icon("care", 13, 2)}{esc(e.get("speaker") or "Clinician")}</span> (recorded by {who})'
    if e["kind"] == "recording" and source_authority(e) == "family":
        care = f'{esc(e.get("speaker") or name or "Family member")} (family, recorded by {who})'
    if kind_of(e) == "reference":
        what = f"photographed the {esc((e.get('photo_of') or 'notice').lower())}" if e["kind"] == "photo" else "added"
        if not ward_shown:   # no ward section to point to (she has left): the facts themselves
            return f"{who} {what}: " + "; ".join(ward_text(ln, remote) for ln in e["lines"]) + "."
        items = [{"visiting": "visiting hours", "rounds": "the ward round"}.get(ln["type"]) or esc(ln["fact"].get("what", "a contact").lower())
                 for ln in e["lines"]]
        listed = ", ".join(items[:-1]) + (" and " if len(items) > 1 else "") + items[-1]
        return f'{who} {what}: {listed} are now under <a href="#cr-ward">Visiting the ward</a>.'
    head = e["headline"]
    if head in DEFAULT_HEADLINES or not e["lines"]:   # no facts: the words themselves, said by whoever said them
        changed = [c.strip() for c in (e.get("reading") or {}).get("changed_lines") or [] if c.strip()]
        kept = [ln.strip() for ln in (e.get("text") or "").splitlines() if ln.strip() and ln.strip() not in changed]
        text = " ".join(" ".join(kept).split())
        text = esc(text[:200] + ("…" if len(text) > 200 else ""))
        mine = (f" · changed by {who}: " + " ".join(f"“{esc(c)}”" for c in changed) + ' <span class="cr-badge">reported by family</span>'
                if changed else "")   # lines changed by hand are the family's words, not the speaker's
        said = f"“{text}”" if text else ""
        if e["kind"] == "recording":
            return f"{care}: {said}{mine}"
        if e["kind"] == "photo":
            return f"{who} added a photo of {esc((e.get('photo_of') or 'a document').lower())}: {said}{mine}"
        return f"{who}: {said}"
    top = top_line(e)
    if e["kind"] == "recording":
        out = f"{care}: {esc(arrows(head))}"
    elif name and head.startswith(name + ":"):
        out = f"{who}{esc(arrows(head[len(name):]))}"
    else:
        out = f"{who}: {esc(arrows(head))}"
    out += flag_badge(e.get("headline_flag"))
    rest = [ln for ln in e["lines"] if ln is not top and ln["text"] not in head]
    return out + "".join(f" · {ward_text(ln, remote)}{line_badges(ln)}" for ln in rest)


def note_entry(ep: Episode, e: dict, colors: dict, tz: str | None, ward_shown: bool = True, remote: bool = False) -> str:
    clock = event_clock(e, tz)
    plan = shared_plan(e)
    headline = plan_headline(ep, e) if plan else e["headline"]
    new = '<span class="cr-new">NEW</span>' if e.get("new") else ""
    cls = "cr-ref" if kind_of(e) == "reference" else "cr-note"
    return (f'<div class="cr-ev {cls}" data-headline="{esc(headline)}"><span class="cr-dot"></span><div class="cr-row">'
            f'<span class="cr-time">{esc(clock)}</span>{new}<span class="cr-rowtext">{note_text(ep, e, colors, ward_shown, remote)}</span>'
            f'{source_details(e)}</div></div>')


def remote_viewer(ep: Episode, tz: str | None) -> bool:
    """The viewer's clock is not the hospital's (ward hours and date-only plans are in the hospital's)."""
    return bool(tz) and tz != ep.patient.get("timezone")


def left_hospital(s: dict) -> bool:
    """The care team said she left (a family report of it does not hide the ward's details)."""
    return bool(s["discharged"]) and not s["discharged"]["unconfirmed"] and not any(
        (s.get(slot) or {}).get("time_uncertain") for slot in ("location", "admitted", "discharged"))


def timeline_html(ep: Episode, member: str, tz: str | None, photo_of=lambda e: None, ward_shown: bool = True,
                  presentation: dict | None = None) -> str:
    """Important events by stated event time; unresolved dates explain their status."""
    view = presentation if presentation is not None else presentation_model(ep, member, tz)
    entries = view["entries"]
    topics = test_topics_html(ep, view["test_topics"], tz, photo_of)
    colors = colors_of(ep)
    remote = remote_viewer(ep, tz)
    if not entries and not topics:
        return ('<div class="cr"><p class="cr-quiet" style="font-size:calc(16px*var(--cr-fs,1))">Nothing yet. The primary caregiver adds the first '
                'event. Original documents and messages stay available below.</p></div>')
    news = [e["new"] for e in entries]
    seen = ep.seen.get(member, 0)
    cut = news.index(False) if (seen and True in news and False in news and news == sorted(news, reverse=True)) else None
    out, day, explained_unknown = [], None, False
    for i, e in enumerate(entries):
        if i == cut:
            out.append('<div class="cr-seen" role="separator">You last looked here</div>')
        timing = e["event_time"]
        when = parse_when(timing.get("when")) if timing.get("status") == "confirmed" else None
        if isinstance(when, dt.datetime):
            when = local(timing["when"], tz)
        label = f"{when:%A %d %b %Y}" if when is not None else event_time_text(timing, tz)
        if label != day:
            out.append(f'<div class="cr-day">{esc(label)}</div>')
            day = label
        if when is None and not explained_unknown:
            out.append(f'<div class="cr-quiet">{esc(timing.get("reason") or "The event date/time could not be resolved.")} '
                       'This describes the event timing, separately from checking the source words.</div>')
            explained_unknown = True
        elif when is None and timing.get("reason") != "The source does not state an event date.":
            out.append(f'<details class="cr-src"><summary>Why this date is unclear</summary>{esc(timing.get("reason"))}</details>')
        out.append(key_entry(ep, e, colors, tz, photo_of(e), remote) if kind_of(e) == "key" else
                   note_entry(ep, e, colors, tz, ward_shown, remote))
    legend = ('<div class="cr-legend"><span><span style="width:12px;height:12px;border-radius:50%;background:var(--cr-key,#0B5CAD)"></span>Key event</span>'
              '<span><span style="width:8px;height:8px;border-radius:50%;background:var(--cr-note-dot,#9AA4B1)"></span>Note</span>'
              '<span><span style="width:12px;height:12px;border-radius:50%;background:#B45309"></span>Changed</span></div>')
    return (f'<div class="cr"><div class="cr-sec"><div class="cr-sec-title cr-display" role="heading" aria-level="2">Timeline</div>{legend}</div>'
            f'{topics}<div class="cr-rail">{"".join(out)}</div></div>')


def header_html(ep: Episode) -> str:
    p = ep.patient
    return (f'<div class="cr"><div class="cr-eyebrow">{esc(PRODUCT)} · family timeline</div>'
            f'<div class="cr-name cr-display" role="heading" aria-level="1">{esc(p["name"])}, {esc(p["age"])}</div>'
            f'<div class="cr-tagline">{esc(TAGLINE)}</div></div>')


def hero_html(ep: Episode, s: dict, tz: str | None, viewer: dict, presentation: dict | None = None) -> str:
    view = presentation if presentation is not None else presentation_model(ep, viewer.get("member_id"), tz)
    next_items = (view["next"] if view["test_topics"] or view.get("not_planned") or view.get("cancelled") else
                  [{"text": text, "target": None} for text in s["next"]])
    gone, remote = left_hospital(s), remote_viewer(ep, tz)
    loc = s["location"]
    where = (esc(loc["text"]) + (' <span class="cr-badge">reported by family</span>' if loc["unconfirmed"] else "")) if loc else ""
    uncertain = [(label, s.get(slot)) for slot, label in (("location", "Location"), ("admitted", "Admission"),
                  ("discharged", "Discharge"), ("said_by_doctor", "Diagnosis")) if (s.get(slot) or {}).get("time_uncertain")]
    if not s["discharged"]:
        uncertain += [(p["what"], {"text": (p.get("uncertainty_reason") or "Procedure timing needs confirmation.")
                                         + " Source: " + p["fact"]["quote"],
                                   "uncertain_alternatives": p.get("uncertain_alternatives", [])})
                      for p in ep.procedures.values() if p.get("time_uncertain")]
    if loc and loc.get("time_uncertain"):
        where = "Location needs confirmation: " + where
    phase = "Current state needs confirmation" if uncertain else view.get("phase") or s["phase"]
    if view["test_phase"] and not uncertain:
        phase = "Tests and examinations mentioned"
    hospital_date = "the hospital's date" if remote else ""

    def when_note(item: str) -> str:   # a plan with a clock time is in the viewer's time; a date alone is the hospital's
        return "your time" if re.search(r"\d{1,2}:\d{2}", item) else hospital_date
    facts = []
    if s["discharged"]:
        discharged = s["discharged"]
        record = ep.slots.get("discharged")
        timing = event_time(ep, record, {"fact": record["fact"]}) if record else {}
        value = event_time_text(timing, tz)
        clock_note = when_note(value) if timing.get("status") == "confirmed" else ""
        note = " · ".join(x for x in (clock_note, "reported by family, not confirmed" if discharged["unconfirmed"] else "") if x)
        facts.append(("Discharged", esc(value), note, False))
    if gone:
        facts.append(("Next", _next_html(next_items[0]) if next_items else "Nothing planned yet",
                      when_note(next_items[0]["text"]) if next_items and not next_items[0]["target"] else "", False))
    else:
        ed = s["expected_discharge"] if ep.pending_discharge_plan() and not view.get("discharge_cancelled") else None
        if ed and ed.get("other"):   # the care team gave two different answers: both, until it is settled
            facts.append(("Going home", f'{esc(ed["other"])} or {esc(ed["short"])}?',
                          " · ".join(x for x in ("Two different answers: ask which is right", hospital_date) if x), True))
        elif ed:
            value = ed["text"].removeprefix("Expected to go home: ")   # keeps a condition: "(if she is walking safely ...)"
            note = " · ".join(x for x in ((f'Changed · was <s>{esc(ed["was"])}</s>' if ed["was"] else ""),
                                          (f'Confirmed with the care team by {esc(ed["confirmed_by"])}' if ed.get("confirmed_by") else ""), hospital_date,
                                          "reported by family" if ed["unconfirmed"] else "") if x)
            if s['discharged']:
                note = 'Confirm which admission this plan concerns' + (' · ' + note if note else '')
            facts.append(("Discharge plan" if s['discharged'] else "Going home", esc(value), note, bool(ed["was"])))
        elif next_items and not s["discharged"]:
            facts.append(("Next", _next_html(next_items[0]), when_note(next_items[0]["text"]) if not next_items[0]["target"] else "Source statements; see dates and attribution", False))
        if s["doctor_in_charge"]:
            facts.append(("Doctor in charge", esc(s["doctor_in_charge"]["text"].removeprefix("Doctor in charge: ")),
                          "reported by family" if s["doctor_in_charge"]["unconfirmed"] else "", False))
    events = view["entries"]
    if events:
        latest = events[0]
        flag = FLAG[latest["headline_flag"]][0] if latest.get("headline_flag") else ""
        label = ("Plan withdrawn" if latest.get("plan_status") == "withdrawn" else "Family report" if latest.get("plan_status") == "completed"
                 else "Family plan" if shared_plan(latest) else "Planned" if latest["event_time"]["temporal_status"] == "planned"
                 and not _family_own_statement(latest) and not (headline_line(latest) or {}).get("not_planned") else "Latest event")
        facts.append((label, esc(arrows(latest["headline"])),
                      f'{esc(event_time_text(latest["event_time"], tz))} · {esc(latest["author_name"])}'
                      + (f" · {esc(flag)}" if flag else ""), False))
    cells = "".join(f'<div class="cr-fact{" cr-chg" if chg else ""}"><span class="cr-fact-label">{label}</span>'
                    f'<span class="cr-fact-value cr-display">{value}</span>'
                    f'<span class="cr-fact-note{" cr-amber" if chg else ""}">{note}</span></div>' for label, value, note, chg in facts[:3])
    uncertainty = "".join(f'<li><b>{esc(label)}:</b> {esc(slot["text"])}; '
                          + "; ".join(f'Other source: “{esc(alt["fact"]["quote"])}”' for alt in slot.get("uncertain_alternatives", []))
                          + '</li>' for label, slot in uncertain)
    pending = (f'<div class="cr-alert"><span><b>Confirm the latest state with the care team.</b> '
               f'The sources do not establish a confirmed current state.<ul>{uncertainty}</ul></span></div>') if uncertain else ""
    alert = pending + two_answers_html(s, tz) + (f'<div class="cr-alert">{icon("alert", 18, 2)}<span><b>Warning signs:</b> '
                                       f'{esc(" ".join(s["warning_signs"]))}</span></div>' if s["warning_signs"] else "")
    return (f'<div class="cr"><section class="cr-hero" aria-label="Right now"><div class="cr-hero-top"><div>'
            f'<div class="cr-eyebrow" style="color:var(--cr-now,#0B5CAD)">Right now</div>'
            f'<div class="cr-phase cr-display" role="heading" aria-level="2">{esc(phase)}</div>'
            f'<div class="cr-sub">{where}</div></div>'
            f'<span class="cr-fact-note">Times in {esc(viewer.get("city", "your"))} time</span></div>'
            f'<div class="cr-facts">{cells}</div>{alert}{info_strip_html(ep, s, viewer.get("member_id"))}</section></div>')


def info_strip_html(ep: Episode, s: dict, member: str | None) -> str:
    """The everyday things at a glance, under Right now: visiting hours and the ward's phone (while she is in hospital),
    who in the family is in the loop, and how many medicines are on the list. Each links to its section on the right."""
    chips = []
    if not left_hospital(s):
        if s["visiting"]:
            chips.append(("Visiting hours", esc(s["visiting"]["text"].removeprefix("Visiting hours ").split(";")[0]), "hospital's time", "#cr-ward"))
        phone = next((c.partition(": ") for c in s["contacts"] if re.search(r"\bward\b", c.partition(": ")[0], re.I)
                      and "phone" in c.partition(": ")[0].lower()), None)
        if phone:
            chips.append((esc(phone[0]), phone_link(phone[2]), "", ""))
    n = len(ep.members)
    if n:
        caught_up = sum(1 for m in ep.members if ep.seen.get(m, 0) >= ep.seq) if ep.seq else n
        chips.append(("Family in the loop", f"{n} {'person' if n == 1 else 'people'}",
                      f"{caught_up} of {n} read the latest" if ep.seq else "", "#cr-family"))
    if s["medicines"]:
        on = sum(1 for m in s["medicines"] if m["active"])
        stopped = len(s["medicines"]) - on
        chips.append(("Medicines", f"{on} on the list", f"{stopped} stopped" if stopped else "", "#cr-meds"))
    if not chips:
        return ""
    cells = "".join(f'<div class="cr-chip"><span class="cr-fact-label">{label}</span><span class="cr-chip-value">'
                    + (f'<a href="{href}">{value}</a>' if href else value) + "</span>"
                    + (f'<span class="cr-fact-note">{esc(note)}</span>' if note else "") + "</div>"
                    for label, value, note, href in chips)
    return f'<div class="cr-strip" aria-label="At a glance">{cells}</div>'


QA_HOW = {"llm_first_try": "{model} picked these sentences from the updates, and {product} double-checked them.",
          "refreshed_source_changed": "A source changed. {product} selected these quotes again from the current updates.",
          "llm_after_retry": "{model} picked these sentences from the updates on its second try, and {product} double-checked them.",
          "fallback": "{product} picked these sentences by matching your words (the model's pick did not pass the checks).",
          "fallback_unavailable": "{product} picked these sentences by matching your words (the model did not reply).",
          "fallback_no_model": "{product} picked these sentences by matching your words.",
          "no_updates": "There are no updates yet."}
QA_HOW_NONE = {"llm_first_try": "{model} found nothing about this in the updates, and {product} double-checked.",
               "refreshed_source_changed": "A source changed. No current update matches your question.",
               "llm_after_retry": "{model} found nothing about this in the updates, and {product} double-checked.",
               "fallback": "Nothing in the updates matches your words.", "fallback_unavailable": "Nothing in the updates matches your words.",
               "fallback_no_model": "Nothing in the updates matches your words.", "no_updates": "There are no updates yet."}


def first_name(ep: Episode) -> str:
    return (ep.patient.get("name") or "her").split()[0]


def hello_html(ep: Episode, viewer: dict, tz: str | None, now: str | None = None) -> str:
    """The greeting above the big buttons: good morning / afternoon / evening in the viewer's own time (the demo's "now"
    is the newest update), their name, and their colour."""
    t = local(now, tz) if now else None
    if t is None:
        t = dt.datetime.now(ZoneInfo(tz)) if tz else dt.datetime.now()
    part = ("Good morning" if 5 <= t.hour < 12 else "Good afternoon" if 12 <= t.hour < 18 else "Good evening" if 18 <= t.hour < 23
            else "Hello")
    name = viewer.get("name") or "there"
    color = colors_of(ep).get(viewer.get("member_id"), "#7B7365")
    return (f'<div class="cr cr-hello"><div><div class="cr-hello-hi cr-display" role="heading" aria-level="2">{part}, {esc(name)}</div>'
            f'<div class="cr-hello-sub">What would you like to do for {esc(first_name(ep))} today?</div></div>'
            f'<span class="cr-avatar" style="background:{color}" aria-hidden="true">{esc(name[:1].upper())}</span></div>')


def quote_avatar(ep: Episode, u: dict, colors: dict) -> str:
    """Who said it, at a glance: the care team's icon (a recording, or a photo of a paper), else the family member's
    initial in their colour (a note, or a line changed by hand)."""
    if not u["changed_by_hand"] and u["authority"] == "care_team" and u["kind"] in ("recording", "photo"):
        return f'<span class="cr-qa-av cr-av-care">{icon("care" if u["kind"] == "recording" else "camera", 16, 2)}</span>'
    name = ep.members.get(u["author"], {}).get("name") or u["author"] or "?"
    return f'<span class="cr-qa-av" style="background:{colors.get(u["author"], "#7B7365")}">{esc(name[:1].upper())}</span>'


def answer_html(ep: Episode, r: dict, tz: str | None, viewer: str | None = None) -> str:
    """One answer, as a short chat: the question in a bubble on the right; KindredRelay's reply on the left with the fixed
    lead and every sentence it rests on, word for word, with who said it, when (in the viewer's zone) and whether it is
    a family report or no longer current; a related leaflet (general information) below."""
    import episode_qa as Q   # here, so the timeline does not need it
    colors = colors_of(ep)
    asker = ep.members.get(r.get("asked_by"), {}).get("name")
    asked = "You asked" if r.get("asked_by") in (None, viewer) else f"{esc(asker or 'Someone')} asked"
    items = []
    for u in r["quotes"]:
        cls = "cr-qa-fam" if u["authority"] == "family" else "cr-qa-old" if u["state"] in Q.NOT_CURRENT else ""
        if u["changed_by_hand"]:
            who = f"changed by hand by {person(ep, u['author'], colors)}"
        elif u["kind"] == "recording":
            speaker = esc(u["speaker"] or (u.get("author_name") if u["authority"] == "family" else "Clinician") or "Family member")
            who = (f'{speaker} (family), recorded by {person(ep, u["author"], colors)}' if u["authority"] == "family" else
                   f'<span class="cr-care">{speaker}</span>, recorded by {person(ep, u["author"], colors)}')
        elif u["kind"] == "photo":
            who = f"Photo of {esc((u['photo_of'] or 'a document').lower())}, added by {person(ep, u['author'], colors)}"
        else:
            who = f"Note from {person(ep, u['author'], colors)}"
        label = Q.display_label(u, {}, tz)   # state/provenance, without a source-received timestamp
        badge = (f' <span class="cr-badge{" cr-badge-gray" if u["authority"] != "family" else ""}">{esc(label)}</span>' if label else "")
        li = f'<li class="{cls}">' if cls else "<li>"
        items.append(f'{li}{quote_avatar(ep, u, colors)}<div class="cr-qa-say"><div class="cr-qa-quote">“{esc(u["text"])}”</div>'
                     f'<div class="cr-qa-src">{who}{badge}</div></div></li>')
    more = ""
    if r["covered"] == "no" and r.get("method") != "no_updates":
        more = ('<div class="cr-qa-next">You can save it for the doctor below, so the family can ask it together at the next '
                'visit.</div>')
    if r.get("more_medicines"):
        more += '<div class="cr-qa-next">There are more medicines than fit here: the full list is under Medicines on this page.</div>'
    ward = r.get("ask_ward")
    if ward:
        more += f'<div class="cr-qa-src">You could also ask the ward: “{esc(ward["text"])}”</div>'
    lf = r.get("leaflet")
    if lf:
        rest = [x for x in lf["sentences"] if x not in lf["top"]]
        more += (f'<div class="cr-leaf"><div class="cr-leaf-head">📄 A helpful leaflet: {esc(lf["title"])}</div>'
                 f'<div class="cr-leaf-note">General information, not about {esc(first_name(ep))} in particular. {esc(lf.get("notice", ""))}</div>'
                 f'<ul>{"".join(f"<li>{esc(x)}</li>" for x in lf["top"])}</ul>'
                 + (f'<details><summary>Read the whole leaflet</summary><ul>{"".join(f"<li>{esc(x)}</li>" for x in rest)}</ul></details>'
                    if rest else "") + "</div>")
    how = (QA_HOW if r["quotes"] else QA_HOW_NONE).get(r.get("method"), "").format(model=esc(r.get("model") or "the model"), product=esc(PRODUCT))
    how = how[:1].upper() + how[1:]
    if r.get("chosen") is not None and {u["sid"] for u in r["quotes"]} - set(r["chosen"]):
        how += f" {esc(PRODUCT)} added the sentences that stand now or belong with them."   # the model did not pick those
    if r.get("newer"):
        how = (f"Asked before {r['newer']} newer update{'s' if r['newer'] != 1 else ''}: the labels are up to date, but ask "
               f"again to look through the newer ones. ") + how
    return (f'<div class="cr"><section class="cr-chat cr-qa" aria-label="Answer">'
            f'<div class="cr-me"><div class="cr-bubble-me">{esc(r["question"])}</div><span class="cr-me-who">{asked}</span></div>'
            f'<div class="cr-reply"><span class="cr-bot" title="{esc(PRODUCT)}">{icon("heart", 20, 2.2)}</span><div class="cr-bubble-bot">'
            f'<div class="cr-qa-a cr-display">{esc(r["answer"])}</div>'
            + (f'<ul class="cr-qa-quotes">{"".join(items)}</ul>' if items else "") + more +
            f'<div class="cr-qa-how">{how} {esc(PRODUCT)} only repeats what the updates say; it does not give medical advice.</div>'
            f'</div></div></section></div>')


def two_answers_html(s: dict, tz: str | None) -> str:
    """The care team gave two different answers about one thing: both, word for word, with who said them and when, and
    where the question went. The page does not judge which is right."""
    out = ""
    for t in s.get("two_answers", []):
        subj = "going home" if t["type"] == "expected_discharge" else t["subject"]
        said = "".join(f'<span class="cr-two">“{esc(a["quote"])}” <span class="cr-two-who">({esc(a["who"])})</span></span>' for a in t["answers"])
        out += (f'<div class="cr-alert cr-conflict" role="note">{icon("alert", 18, 2)}<span><b>Two different answers about '
                f'{esc(subj)}: ask which is right.</b>{said}<span class="cr-two cr-two-who">The question is at the top of '
                f'the list for the doctor.</span></span></div>')
    return out


def question_html(ep: Episode, q: dict, tz: str | None, hint: dict | None = None) -> str:
    """One question for the doctor, on a soft note: the words, who asked, and a later care-team sentence that may
    answer it."""
    colors = colors_of(ep)
    who = ", ".join(person(ep, m, colors) for m in q["askers"])
    if q.get("auto") == "two_answers":   # nobody typed it: the care team gave two answers
        who = "added automatically: the care team gave two different answers" + (f"; also asked by {who}" if who else "")
    found = ""
    if hint:
        src = hint["speaker"] if hint["kind"] == "recording" else f"photo of {(hint['photo_of'] or 'a document').lower()}"
        found = (f'<div class="cr-qhint">Maybe answered: “{esc(hint["text"])}” ({esc(src)})</div>')
    if q.get("invalidation_reason"):
        found = f'<div class="cr-qhint">{esc(q["invalidation_reason"])}</div>' + found
    done = (' <span class="cr-badge cr-badge-gray">answered</span>' if q["status"] == "answered" else "")
    marked = (f' · confirmed by {person(ep, q["marked_by"], colors)}: {esc(q["confirmed"])}' if q["status"] == "answered" and q.get("confirmed") and q.get("marked_by") else
              f' · marked answered by {person(ep, q["marked_by"], colors)}' if q["status"] == "answered" and q.get("marked_by") else
              " · settled by a later update from the care team" if q["status"] == "answered" and q.get("auto") and q.get("answered_by") else "")
    asked = who if q.get("auto") else f"asked by {who}"
    return (f'<div class="cr"><div class="cr-qitem"><div class="cr-qtext">{esc(q["text"])}{done}</div>'
            f'<div class="cr-qmeta">{asked}{marked}</div>{found}</div></div>')


def phone_link(value: str) -> str:
    """A tel: link only for a value that is just a phone number ("020 7946 0123", "+44 (0)20 7946 0123"); anything with
    more in it ("ext. 4521", "(24 hours)") is shown as text, so the phone does not dial extra digits."""
    v = value.replace("(0)", "")
    if not re.fullmatch(r"\+?[\d\s().-]{6,}", v.strip()):
        return esc(value)
    return f'<a href="tel:{re.sub(r"[^\d+]", "", v)}">{esc(value)}</a>'


def side_html(ep: Episode, s: dict, tz: str | None, member: str, presentation: dict | None = None) -> str:
    view = presentation if presentation is not None else presentation_model(ep, member, tz)
    next_items = (view["next"] if view["test_topics"] or view.get("not_planned") or view.get("cancelled") else
                  [{"text": text, "target": None} for text in s["next"]])
    gone = left_hospital(s)
    colors, parts = colors_of(ep), []
    if next_items:
        parts.append('<section><div class="cr-side-title cr-display" role="heading" aria-level="2">What\'s next</div>'
                     '<span class="cr-side-sub">Your time; a date without a time is the hospital\'s date</span>'
                     f'<ul>{"".join(f"<li>{_next_html(item)}</li>" for item in next_items)}</ul></section>')
    plans = ep.plans()
    if plans:
        items = "".join(f'<li><span class="cr-avatar" style="background:{colors.get(p["member_id"], "#8A94A6")}">{esc(p["name"][:1])}</span><span>'
                        f'<b>{esc(p["name"])}{" (you)" if p["member_id"] == member else ""}</b>: {esc(plan_headline(ep, p))} '
                        + (f'<span class="cr-plan-check">{icon("alert", 14, 2)} {esc(p["check"])}</span>' if p.get("check") else "")
                        + '</span></li>' for p in plans)
        parts.append('<section id="cr-plans"><div class="cr-side-title cr-display" role="heading" aria-level="2">Who\'s coming, who\'s helping</div>'
                     '<span class="cr-side-sub">Each person\'s latest plan, in their own words. Dates and parts of day stay as written.</span>'
                     f'<ul class="cr-plans">{items}</ul></section>')
    if not gone and (s["visiting"] or s["rounds"] or s["contacts"]):
        hospital_city = next((m["city"] for m in ep.members.values() if m.get("timezone") == ep.patient.get("timezone")), "")
        rows = []
        if s["visiting"]:
            rows.append(("Visiting hours", esc(s["visiting"]["text"].removeprefix("Visiting hours ")), s["visiting"]["unconfirmed"]))
        if s["rounds"]:
            rows.append(("Consultant ward round", esc(s["rounds"]["text"].removeprefix("Consultant ward round: ")), s["rounds"]["unconfirmed"]))
        for c in s["contacts"]:
            what, _, value = c.partition(": ")
            rows.append((what, phone_link(value) if "phone" in what.lower() else esc(value), False))
        family = ' <span class="cr-badge">reported by family</span>'
        dl = "".join(f'<div><dt>{esc(a)}</dt><dd>{b}{family if u else ""}</dd></div>' for a, b, u in rows)
        parts.append(f'<section id="cr-ward"><div class="cr-side-title cr-display" role="heading" aria-level="2">Visiting the ward</div>'
                     f'<span class="cr-side-sub">Hospital\'s local time{f" ({esc(hospital_city)})" if hospital_city else ""}</span>'
                     f'<dl>{dl}</dl></section>')
    if s["medicines"]:
        items = "".join((f'<li>{esc(m["text"].split(": ", 1)[-1])}' if m["active"] else
                         f'<li class="cr-quiet"><s>{esc(m["text"].removeprefix("Stopped: "))}</s> stopped')
                        + (' <span class="cr-badge">reported by family</span>' if m["unconfirmed"] else "") + "</li>"
                        for m in s["medicines"])
        parts.append('<section id="cr-meds"><div class="cr-side-title cr-display" role="heading" aria-level="2">Medicines</div>'
                     '<span class="cr-side-sub">As written on the list. Ask the doctor or pharmacist about anything.</span>'
                     f"<ul>{items}</ul></section>")
    if s["instructions"] and not gone:
        parts.append('<section><div class="cr-side-title cr-display" role="heading" aria-level="2">Instructions given</div>'
                     + "<ul>" + "".join(f'<li>{esc(i["text"])}</li>'
                                        for i in s["instructions"]) + "</ul></section>")
    fam = "".join(f'<li><span class="cr-avatar" style="background:{colors[mid]}">{esc((m.get("name") or "?")[:1])}</span>'
                  f'{esc(m.get("name"))} · {esc(m.get("relation", ""))}{" (you)" if mid == member else ""}, {esc(m.get("city", ""))}</li>'
                  for mid, m in ep.members.items())
    parts.append(f'<section id="cr-family"><div class="cr-fam-title">Family</div><ul class="cr-fam">{fam}</ul></section>')
    return f'<div class="cr"><aside class="cr-side">{"".join(parts)}</aside></div>'
