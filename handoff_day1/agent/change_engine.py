"""Update propagation for the CareRelay case state: PropagatingStore(CaseStore), deterministic backend logic.

New information enters through one door, apply_change(change, actor): a new clinician recording, a late upload, a
family statement, a confirmed or re-judged fall event, a transcript correction, a late generation job or a review.
The backend then computes the exact impact set (segment-level), regenerates the affected items, recomputes the
dual-basis schedule (the approved due time and assignee stay in force until a person approves; the proposed basis
shows where things move), creates pending versions and publishes one new case_version atomically.

Deterministic, never decided by a language model: time parsing (canonical_time, due_at_from_phrase), the rota lookup
(assignee_for), impact sets, which instruction a proposal supersedes (a person ticks `supersedes`; the backend only
validates the word-stem overlap), versions, case_version and seq, idempotency (request_id + payload hash, and
content_sha256 for uploads), publish, the notice strings, the review and export gates, and every error.
The LLM may only propose nicer prose for a regenerated item through the optional `rewriter` callback on the store
(rewriter(old_item, segment_before, segment_after, keep, correction=None) -> (content | None, method)); `correction`
is the {from, to, kind} pair the backend derived (the corrected words, or the old and new canonical time of a
superseded instruction) so the rewriter checks the same thing the backend checks. Its output is checked with
check_item_content (new time present, old time absent, no relaxing sentence), added_facts (no time, number or weekday
the item did not already state; a number written as a word counts) and the kept facts (none of the item's facts dropped
other than the superseded or corrected one), and the deterministic substitution is used when it is missing or fails.
A text a person or a late job delivers, and an approved version a rejection brings back, pass the same checks against
the case as it is now (_change_generation_delivery, _restore_problems); what fails stays stale for a person. For a
delivered text the kept facts are those its current sources still state, so a person can drop what the change removed
(an old condition, an earlier time) but not a dose the source still states.
One fit check, PropagatingStore.fit_problems(version), judges a version against the case AS IT IS NOW (every instruction
it rests on: active, its current time and never an earlier one (a clock only in its own half of the day), the condition a
change introduced, the numbers and negation of its current action, its current cite; cites on the latest revision and
never of a sentence an instruction moved away from; no corrected-away value; no ungrounded fact); instruction_problems
judges an instruction (its action's numbers and negation are in the sentence it cites). It is applied to a regenerated text, a
delivered text, a version a rejection brings back, an approval (named ids that fail are refused, NotFit; approve-all
approves the rest and lists the others in reviewed.refused) and the export (an approved item that fails blocks it,
ExportBlocked), so nothing contradicting the current instructions is approved or exported even if a path above missed it.
Confirmation roles (care_cases.md "Confirmation roles"): a clinician (role care_team) approves; the case's one primary
caregiver (case_settings.primary_caregiver) may confirm pending versions on the clinician's behalf (review decision
confirm_on_behalf) once a version has waited longer than case_settings.on_behalf_after_hours since its change's
`effective_at` (never earlier than the latest `at` already accepted) or the clinician was marked unreachable (change kind
clinician_unreachable, with a reason) at or after that change, never a clinician-only change and only through the same fit
gate as an approval. The exclusion rule fails closed (on_behalf_exclusions): an instruction is confirmable only when its
action, now and approved, is one of two non-medication templates (attend an appointment; bring a document or an aid) with a
condition of appointment words only, and the change is a new such instruction or a time-only move; an item version only
when every instruction it rests on is, its numbers (in order), negating and stop words are unchanged, no changed sentence
names a medication or a verb that gives one, and every word it adds is grounded in its approved text or those
instructions. The version is in force and labelled (confirmed_on_behalf) until a clinician confirms it (approve:
clinician_confirmed) or rejects it (the normal reject path, which steps back through on-behalf states to the clinician's own
approved state, never withdrawing what a clinician approved); a clinician's action clears the unreachable mark.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import unicodedata

from case_store import CaseStore, content_hash
from guardrails import FACT_RX, NUMBER_WORDS, added_facts, check_item_content, condition_coverage, facts, norm

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
CLOCK_RX = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
WEEKDAY_RX = re.compile(r"\b(" + "|".join(WEEKDAYS) + r")\b", re.I)
SENTENCE_SPLIT_RX = re.compile(r"((?<![ap]\.m)[.;!?](?:\s+|$))", re.I)   # sentence ends of a source segment; 'a.m. on Thursday' stays whole
CLAUSE_SPLIT_RX = re.compile(r"((?<=[ap]\.m\.)\s+|(?<![ap]\.m)[.;:!?](?:\s+|$))", re.I)   # clause ends; '11:00' and 'a.m.' stay whole
# \Z, not $: '$' also matches before a trailing newline, so 'cg-incoming\n' would pass as a one-line label
REVISION_RX = re.compile(r"^r[1-9]\d*\Z")
LABEL_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _@()-]{0,63}\Z")   # an actor label: one line, at most 64 characters (same rule as the HTTP layer)
TOKEN_RX = re.compile(r"^[\w][\w.:/@+-]{0,79}\Z")            # an id such as 'gmdcsa24:s1_fall_01' or 'run-2026...': no spaces
CLINICAL_SOURCE_TYPES = ("clinician_recording", "clinician_instruction_text")
STOP_STEMS = {"the", "and", "for", "with", "your", "her", "his", "please", "also", "then"}
SUPERSEDES_MIN_OVERLAP = 0.5
CONDITION_MIN_COVERAGE = 0.5
MAX_UTTERANCE = 500
CONTENT_KINDS = ("handover_item", "sheet_section", "task")   # what an export prints and a generation job may rewrite
# words that carry no condition of their own ('with your glasses' is about 'glasses'); stems are 3 letters, as in
# guardrails.condition_coverage
CONDITION_STOP = {"only", "with", "the", "and", "for", "to", "of", "a", "an", "be", "is", "up", "her", "his", "on", "at", "your",
                  "you", "she", "him", "they", "them", "their", "this", "that", "please", "also", "then", "its", "our", "any", "all",
                  "has", "have", "are", "was", "will", "can", "may", "into", "from"}
NEGATION_RX = re.compile(r"\b(not|no|never|none|stop|avoid|without|don'?t|doesn'?t|mustn'?t|cannot|can'?t)\b|n't\b", re.I)
# confirmation roles (care_cases.md "Confirmation roles"): a clinician (role care_team) approves; the case's one primary
# family caregiver may confirm on the clinician's behalf after the case's time limit or once the clinician is marked
# unreachable, always labelled, never a medication or dose change nor a relaxed condition
CLINICIAN_ROLE = "care_team"
ON_BEHALF_DEFAULT_HOURS = 24
ON_BEHALF_MAX_HOURS = 720
MAX_REASON = 200
ON_BEHALF_LABEL = "confirmed by the primary caregiver on the clinician's behalf"
LABEL_KEYS = ("confirmed_on_behalf", "clinician_confirmed")
# The exclusion rule fails closed (care_cases.md "Confirmation roles"): an instruction may be confirmed on the
# clinician's behalf only when its action, now and in its last approved state, is one of two non-medication templates
# (attend an appointment; bring a document or an aid), every word of its condition is appointment vocabulary, and the
# change is a new such instruction or a time-only move. Everything else is clinician-only. The word lists below are
# defence in depth on top of that allow-list (and the rule for item texts and event items).
ON_BEHALF_FILLER = {"the", "a", "an", "her", "his", "your", "their", "our", "to", "for", "of", "on", "at", "in", "with", "and", "next",
                    "current", "latest", "new", "this", "that"}
APPOINTMENT_WORDS = {"follow", "up", "followup", "appointment", "appointments", "visit", "clinic", "check", "checkup", "doctor",
                     "doctors", "gp", "hospital", "outpatient", "outpatients", "nurse", "physio", "physiotherapy"}
APPOINTMENT_HEADS = {"appointment", "appointments", "visit", "check", "checkup"}
APPOINTMENT_VERBS = {"attend", "keep", "go"}
BRING_WORDS = {"blood", "pressure", "diary", "medication_list", "list", "walking", "frame", "stick", "cane", "glasses", "hearing",
               "aid", "aids", "letter", "appointment", "card", "insurance", "notebook", "questions", "referral", "notes"}
CONDITION_WORDS = APPOINTMENT_WORDS | {"morning", "afternoon", "evening"}
# a word that names a medication, a unit or how it is given; 'medication list' / 'medicine list' name a document to bring,
# not a medication (the follow-up item 'bring medication list' is not a medication change). No leading \b: '500mg', '5ml'
MEDICATION_RX = re.compile(r"(?<![a-z])(medications?|medicines?|meds|tablets?|pills?|capsules?|doses?|dosage|dosing|mg|mcg|milligram(?:me)?s?|"
                           r"microgram(?:me)?s?|ml|mls|millilit(?:re|er)s?|units?|inhalers?|puffs?|insulin|injections?|inject|drops|patch(?:es)?|"
                           r"prescriptions?|prescribed|antibiotics?|painkillers?|paracetamol|acetaminophen|ibuprofen|aspirin|warfarin|metformin|"
                           r"syrup|sachets?|suppositor(?:y|ies)|creams?|ointments?)\b(?!\s+lists?\b)", re.I)
# a verb that gives or changes a medication: a changed sentence with one of them is clinician-only
MED_VERB_RX = re.compile(r"\b(give[sn]?|giving|take[sn]?|taking|took|start(?:s|ed|ing)?|increas\w*|reduc\w*|decreas\w*|doubl\w*|halv\w*|"
                         r"appl(?:y|ies|ied|ying)|inject\w*|swallow\w*|administer\w*|titrat\w*)\b", re.I)
# stopping, skipping or holding something: a stop as much as 'do not' is (only in the on-behalf rule, not the fit check)
STOP_RX = re.compile(r"\b(stop\w*|discontinu\w*|skip\w*|hold|holding|held|omit\w*|paus\w*|ceas\w*|withh(?:o|e)ld\w*|halt\w*|cancel\w*|"
                     r"no\s+more|no\s+longer)\b", re.I)
# words that put an exception or independence into a condition ('unless she feels steady', 'alone', 'only on bad days')
EXCEPTION_RX = re.compile(r"\b(unless|except\w*|or|but|if|optional\w*|alone|unaided|unassisted|independently|on\s+(?:her|his|their)\s+own|"
                          r"by\s+(?:her|him|them)sel(?:f|ves)|only\s+(?:on|for|during|at|in|after|before|until|when)|first\s+week|bad\s+days?|"
                          r"as\s+needed|when\s+needed|prn)\b", re.I)
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|(?-i:May)|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
          r"nov(?:ember)?|dec(?:ember)?)\.?(?![a-z])")
# a date, day-first ('13 Oct', '14th October 2026') or month-first ('October 14', 'Oct 14th, 2026'); 'May' only capitalised,
# so 'may 2 tablets' keeps its number
DATE_RX = re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH + r"(?:,?\s+\d{4}\b)?|\b" + _MONTH + r"\s*\d{1,2}(?:st|nd|rd|th)?\b(?:,?\s+\d{4}\b)?", re.I)
H24_RX = re.compile(r"\b\d{1,2}:\d{2}\b")
# every number a dose or a count may be written with: digits (also glued to a unit, '500mg'), number words, multipliers
DOSE_WORDS = {**NUMBER_WORDS, "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
              "nineteen": "19", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
              "hundred": "100", "thousand": "1000", "dozen": "12", "quarter": "quarter", "double": "x2", "twice": "x2", "triple": "x3",
              "thrice": "x3", "once": "x1", "single": "x1"}
DOSE_NUMBER_RX = re.compile(r"\d+(?:[.,]\d+)?|\b(?:" + "|".join(sorted(DOSE_WORDS, key=len, reverse=True)) + r")\b", re.I)
# words a rewrite may add to an item without changing what it says (an item text is grounded in its approved text and
# the instructions it rests on; any other added word makes the change clinician-only)
TEXT_FILLER = ON_BEHALF_FILLER | {"is", "are", "be", "been", "was", "were", "will", "now", "by", "from", "she", "he", "it", "its", "please",
                                  "also", "then", "has", "have", "time", "moved", "changed", "upcoming", "until", "am", "pm", "o", "clock"}


class ConflictError(Exception):
    """The request contradicts the case as it is now (HTTP 409)."""


class StaleBase(ConflictError):
    """A base_revision that is no longer the latest (HTTP 409). A stale base_case_version of a generation_delivery is
    not an exception: the event comes back with status 'refused' / refused 'stale_generation' and no seq."""


class PendingReview(ConflictError):
    """An export was asked for while items are stale or pending review (HTTP 409); .ids names them."""

    def __init__(self, ids: list[str]):
        super().__init__(f"awaiting review: {', '.join(ids)}")
        self.ids = list(ids)


class NotFit(ConflictError):
    """An approval of a version that no longer fits the case as it is now (HTTP 409); nothing was approved.
    .ids names the versions, .problems maps each id to its reasons (PropagatingStore.fit_problems)."""

    def __init__(self, problems: dict[str, list[str]]):
        super().__init__("no longer fits the case, not approved: " + "; ".join(f"{i} ({', '.join(p)})" for i, p in sorted(problems.items())))
        self.ids = sorted(problems)
        self.problems = {i: list(p) for i, p in problems.items()}


class ExportBlocked(PendingReview):
    """An export was asked for while an APPROVED item no longer fits the case (HTTP 409, a PendingReview): .ids names the
    items, .problems maps each id to its reasons. A person rewrites the item (a generation job) and approves the rewrite."""

    def __init__(self, problems: dict[str, list[str]]):
        super().__init__(sorted(problems))
        self.args = ("approved content no longer fits the case: " + "; ".join(f"{i} ({', '.join(p)})" for i, p in sorted(problems.items())),)
        self.problems = {i: list(p) for i, p in problems.items()}


class NotInCase(LookupError):
    """A source, instruction, item or job id that does not belong to this case (HTTP 404)."""


# ---------------------------------------------------------------- pure functions (time, rota, text)
def canonical_time(phrase: str | None) -> str | None:
    """'Wednesday at 4 p.m.' -> 'Wednesday 4:00 p.m.': the one spelling stored, substituted and parsed.
    Only '<Weekday> <h[:mm]> a.m./p.m.' is understood; anything else returns None (never guessed)."""
    wd, ck = WEEKDAY_RX.search(phrase or ""), CLOCK_RX.search(phrase or "")
    if not wd or not ck:
        return None
    h, m, ap = int(ck.group(1)), int(ck.group(2) or 0), ck.group(3).lower()[0]
    if not 1 <= h <= 12 or not 0 <= m <= 59:
        return None
    return f"{wd.group(1).capitalize()} {h}:{m:02d} {ap}.m."


def due_at_from_phrase(phrase: str | None, week_anchor: str) -> str | None:
    """'Thursday 11:00 a.m.' + week anchor 2026-10-12 (a Monday) -> '2026-10-15T11:00' (naive local demo time).
    The weekday is placed in the FIXED week that starts at week_anchor (Monday .. Sunday of that week), never relative
    to the wall clock or to the source's recorded_at: the fixture is a frozen demo week, so 'Monday 9:00 a.m.' read on
    the Tuesday of that week gives the anchor week's Monday. A production backend anchors to the recording date."""
    c = canonical_time(phrase)
    if not c:
        return None
    wd, ck = WEEKDAY_RX.search(c), CLOCK_RX.search(c)
    h, m, ap = int(ck.group(1)), int(ck.group(2) or 0), ck.group(3)[0].lower()
    h = h % 12 + (12 if ap == "p" else 0)
    anchor = dt.date.fromisoformat(week_anchor)
    day = anchor + dt.timedelta(days=(WEEKDAYS.index(wd.group(1).lower()) - anchor.weekday()) % 7)
    return f"{day.isoformat()}T{h:02d}:{m:02d}"


def _dt(iso: str | None) -> dt.datetime | None:
    """A naive ISO local time as a datetime; None when missing or unreadable (callers never compare strings)."""
    try:
        return dt.datetime.fromisoformat(iso) if isinstance(iso, str) else None
    except ValueError:
        return None


def assignee_for(rota: list[dict], due_at: str | None) -> str | None:
    """The caregiver on duty at due_at; a shift owns its start minute (20:00 belongs to the shift that starts then).
    Times are compared as datetimes, so a rota written with seconds ('2026-10-14T20:00:00') keeps its boundary."""
    due = _dt(due_at)
    if due is None:
        return None
    return next((r["caregiver"] for r in rota if _dt(r.get("from")) is not None and _dt(r.get("to")) is not None
                 and _dt(r["from"]) <= due < _dt(r["to"])), None)


def _time_rx(canon: str) -> tuple[re.Pattern, re.Pattern]:
    """(weekday regex, clock regex) of a canonical time; the clock also matches '11 a.m.' / '11am' / '11 AM' for ':00',
    and only in its own half of the day: '8:00 a.m.' never matches '8:00 p.m.' (every caller: the fit check's current
    and earlier times, states_time, substitute_time, a corrected clock)."""
    ow, oc = WEEKDAY_RX.search(canon).group(1), CLOCK_RX.search(canon)
    minutes = oc.group(2) or "00"
    return (re.compile(r"\b" + ow + r"\b", re.I),
            re.compile(r"\b" + oc.group(1) + (r"(?::" + minutes + ")?" if minutes == "00" else ":" + minutes)
                       + r"\s*" + oc.group(3)[0].lower() + r"\.?m\.?(?![a-z])", re.I))


def states_time(content: str, phrase: str | None) -> bool:
    """True when one clause of content names both the weekday and the clock of phrase (how substitute_time finds it)."""
    c = canonical_time(phrase)
    if not c:
        return False
    ow_rx, oc_rx = _time_rx(c)
    return any(ow_rx.search(part) and oc_rx.search(part) for part in CLAUSE_SPLIT_RX.split(content or ""))


def substitute_time(content: str, old_phrase: str | None, new_phrase: str | None) -> str:
    """Replace the weekday and the clock of old_phrase inside content, each on its own, so 'on Thursday at 11:00 a.m.'
    and 'Thursday 11:00 a.m.' both become the new time. Only the ONE clause (text between '.', ';', ':', '!' or '?')
    that names both the old weekday and the old clock is touched, and only its first occurrence of each: a physio day
    or a tablet time in the same item is never moved with the appointment. Content is returned unchanged if either
    phrase is unreadable, if no clause names both, or if more than one clause (or occurrence) does; the caller's
    check then hands the item to a person."""
    o, n = canonical_time(old_phrase), canonical_time(new_phrase)
    if not o or not n:
        return content
    nw, nc = WEEKDAY_RX.search(n).group(1), CLOCK_RX.search(n).group(0)
    ow_rx, oc_rx = _time_rx(o)
    parts = CLAUSE_SPLIT_RX.split(content)
    hits = [i for i, part in enumerate(parts) if ow_rx.search(part) and oc_rx.search(part)]
    if len(hits) != 1 or len(ow_rx.findall(parts[hits[0]])) > 1 or len(oc_rx.findall(parts[hits[0]])) > 1:
        return content
    parts[hits[0]] = oc_rx.sub(nc, ow_rx.sub(nw, parts[hits[0]], count=1), count=1)
    return "".join(parts)


def _local_iso(value, what: str) -> str:
    """A client timestamp must be a naive ISO local time ('2026-10-13T15:30'): it is parsed, compared and printed
    as a datetime. A timezone suffix or any other text is refused rather than compared as a string."""
    if not isinstance(value, str) or len(value) < 16 or _dt(value) is None or _dt(value).tzinfo is not None:
        raise ValueError(f"{what} must be an ISO local time such as 2026-10-13T15:30 (no timezone suffix), got {value!r}")
    return value


def _label(value, what: str, rx: re.Pattern = TOKEN_RX) -> str | None:
    """A client id or label that is printed into a template must be one short line of id characters (TOKEN_RX)
    or label characters (LABEL_RX); None is allowed and stays None. Anything else is refused: template text is
    shown to caregivers without a guardrail pass."""
    if value is None:
        return None
    if not isinstance(value, str) or not rx.match(value):
        raise ValueError(f"{what} must be a short single-line id or label, got {value!r}")
    return value


def _score(value, what: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{what} must be a number between 0 and 1, got {value!r}")
    return value


def _text_key(t: str | None) -> str:
    """Case, curly quotes, whitespace runs and outer punctuation never make two texts different (care_cases.md §0)."""
    return norm(t or "").lower().strip(" .,;:!?")


def _segment_facts(text: str | None) -> set[str]:
    """facts() of a source sentence plus the canonical spelling of each clock in it ('4 p.m.' also grounds '4:00')."""
    out = facts(text or "")
    for m in CLOCK_RX.finditer(text or ""):
        out.add(f"{int(m.group(1))}:{int(m.group(2) or 0):02d}")
    return out


def _stems(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) > 2 and w not in STOP_STEMS}


def _negations(text: str) -> set[str]:
    """The negating words of a text ('not', 'never', 'stop', "don't", ...): 'do not take' and 'take' are opposite actions."""
    return {m.group(0).lower().replace("'", "") for m in NEGATION_RX.finditer(text or "")}


def _clock_canon(value: str | None) -> str | None:
    """'4 p.m.' / '4:00 pm' -> '4:00 p.m.' when the whole value is one bare clock (a transcript correction of a time is
    written the transcript's way); None for anything else, a weekday included."""
    m = CLOCK_RX.fullmatch(norm(value or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not 1 <= h <= 12 or not 0 <= mi <= 59:
        return None
    return f"{h}:{mi:02d} {m.group(3).lower()[0]}.m."


def _clock_rx(canon_clock: str) -> re.Pattern:
    """The clock regex of a canonical clock ('4:00 p.m.' also matches '4 p.m.' and '4pm')."""
    return _time_rx("Monday " + canon_clock)[1]


def _mentions(text: str | None, value: str) -> bool:
    """Does text state value? A bare clock in either spelling, a canonical time as one clause, else the words."""
    if _clock_canon(value):
        return bool(_clock_rx(_clock_canon(value)).search(text or ""))
    if canonical_time(value) and canonical_time(value).lower() == norm(value).lower():
        return states_time(text or "", value)
    return norm(value).lower() in norm(text or "").lower()


def _time_clauses(text: str, canon: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence of a source segment (SENTENCE_SPLIT_RX: '11:00 a.m. on Thursday' stays one) that names
    both the weekday and the clock of the canonical time `canon`: from the first of the two to the end of the other."""
    ow_rx, oc_rx = _time_rx(canon)
    out, pos = [], 0
    for part in SENTENCE_SPLIT_RX.split(text or ""):
        w, c = ow_rx.search(part), oc_rx.search(part)
        if w and c:
            out.append((pos + min(w.start(), c.start()), pos + max(w.end(), c.end())))
        pos += len(part)
    return out


def _changed_words(frm: str, to: str) -> tuple[int, int, str]:
    """The part of a correction that really changes: (start, end) in `frm` and the text that replaces it, once the words
    `frm` and `to` share at the start and at the end are set aside ('Wednesday at 4 p.m.' -> 'Wednesday at 5 p.m.'
    changes '4' to '5'; 'We have moved' -> 'After Monday's call we have moved' changes 'We' only)."""
    fw, tw = list(re.finditer(r"\S+", frm)), list(re.finditer(r"\S+", to))
    i = 0
    while i < len(fw) and i < len(tw) and fw[i].group() == tw[i].group():
        i += 1
    j = 0
    while j < len(fw) - i and j < len(tw) - i and fw[-1 - j].group() == tw[-1 - j].group():
        j += 1
    fs = fw[i].start() if i < len(fw) else len(frm)
    fe = fw[len(fw) - 1 - j].end() if len(fw) - j > i else fs
    ts = tw[i].start() if i < len(tw) else len(to)
    te = tw[len(tw) - 1 - j].end() if len(tw) - j > i else ts
    if fe == fs and te == ts:   # differ only in spacing or case outside words: the whole value changes
        return 0, len(frm), to
    return fs, fe, to[ts:te]


def corrected_time(t: str | None, corr: dict) -> str | None:
    """An instruction time after a transcript correction {from, to, segment_before} of a sentence it rests on.
    - A time nobody could read ('Wed 4 p.m.'): the corrected words applied to it (a bare clock in either spelling), so a
      correction may make it readable.
    - A readable time: the clause of the sentence that stated it (weekday and clock in one clause) is found; if the words
      the correction really changes (_changed_words) fall inside that clause, the clause as corrected states the new time:
      exactly one weekday and one readable clock give it in canonical spelling; a clause left without a readable weekday or
      clock ('Thursday morning', '4.30 p.m.', 'half past four') gives those words verbatim, an unreadable time that is never
      guessed (needs_time_review, a needs_transcript_check question); two weekdays or clocks are refused (ValueError).
      A correction outside that clause ('We have moved' -> "After Monday's call we have moved") leaves the time as it is.
    - A sentence that never stated the time in one clause: the corrected words applied to the time itself (as for an
      unreadable one), never the first weekday and clock of the corrected sentence."""
    if not t:
        return t
    frm, to, before = corr["from"], corr["to"], corr.get("segment_before") or ""
    cf, ct = _clock_canon(frm), _clock_canon(to)
    cur = canonical_time(t)
    if cur is None:
        t2 = _clock_rx(cf).sub(lambda m: ct, t) if cf and ct else re.sub(re.escape(frm), lambda m: to, t, flags=re.I)
        return canonical_time(t2) or t2
    clauses = _time_clauses(before, cur)
    if not clauses:   # the corrected words applied to the time itself, a bare clock in either spelling
        t2 = _clock_rx(cf).sub(lambda m: ct, t) if cf and ct else re.sub(re.escape(frm), lambda m: to, t, flags=re.I)
        return canonical_time(t2) or t2
    fs, fe, repl = _changed_words(frm, to)
    news = []
    for m in re.finditer(re.escape(frm), before):   # every occurrence the correction replaces (str.replace)
        cs, cend = m.start() + fs, m.start() + fe
        for a, b in clauses:
            if not ((cs < b and cend > a) if cend > cs else a < cs < b):
                continue
            lo, hi = min(a, cs), max(b, cend)
            news.append(" ".join((before[lo:cs] + repl + before[cend:hi]).split()))
    if not news:
        return t
    out = set()
    for w in news:
        wds = {x.lower() for x in WEEKDAY_RX.findall(w)}
        cks = {c for c in (_clock_canon(m.group(0)) for m in CLOCK_RX.finditer(w)) if c}
        if len(wds) > 1 or len(cks) > 1:
            raise ValueError(f"the corrected words {w!r} state more than one weekday or clock where the sentence stated {cur}: "
                             "correct one time at a time")
        out.add(f"{wds.pop().capitalize()} {cks.pop()}" if wds and cks else w.strip(" ,;:"))
    if len(out) > 1:
        raise ValueError(f"the correction changes {cur} in two places to different times ({', '.join(sorted(out))}): correct one at a time")
    return out.pop()


MONTH_RX = re.compile(r"\b(january|february|march|april|(?-i:May)|june|july|august|september|october|november|december)\b", re.I)
WORD_OF = {v: k for k, v in NUMBER_WORDS.items()}


def _numeric_facts(text: str | None) -> set[str]:
    """The numbers of a text (a dose or a count; digits and number words alike, 'two' == '2'), not its clocks or days."""
    return {f for f in facts(text or "") if f.isdigit() or f == "half"}


def _action_core(action: str | None, times=()) -> str:
    """An action without the weekday and the clock (either spelling) of each given time, and without month names: what
    is left is what the action says to do ('attend follow-up appointment on Wednesday' at 'Wednesday 4:00 p.m.' is the
    appointment, not a changed action)."""
    out = action or ""
    for t in times:
        c = canonical_time(t)
        if c:
            w_rx, c_rx = _time_rx(c)
            out = c_rx.sub(" ", w_rx.sub(" ", out))
    return " ".join(MONTH_RX.sub(" ", out).split())


def _action_key(action: str | None, times=()) -> tuple:
    """(facts, negations) of an action's core: two actions with the same key say the same dose, count and negation."""
    core = _action_core(action, times)
    return (frozenset(facts(core)), frozenset(_negations(core)))


def corrected_action(action: str | None, corr: dict) -> str | None:
    """An instruction's action after a transcript correction of the sentence it rests on, changed only when the correction
    changes a dose, count or negation the action states (a wording correction leaves the action's own words alone):
    the corrected words applied to the action, or, when the action writes that number its own way ('two' for a '2' the
    correction changed), the one number the correction removed replaced by the one it added. A changed number or negation
    the action states but the correction cannot be applied to is refused (ValueError): nothing guesses the new action."""
    if not action:
        return action
    frm, to = corr["from"], corr["to"]
    before, after = corr.get("segment_before") or "", corr.get("segment_after") or ""
    a2 = re.sub(re.escape(frm), lambda m: to, action, flags=re.I)
    if a2 != action:
        return a2 if _action_key(a2) != _action_key(action) else action
    gone, new = _numeric_facts(before) - _numeric_facts(after), _numeric_facts(after) - _numeric_facts(before)
    hits = _numeric_facts(action) & gone
    if hits:
        if len(hits) != 1 or len(new) != 1:
            raise ValueError(f"the correction changes {sorted(gone)} to {sorted(new)} in a sentence whose action {action!r} states "
                             f"{sorted(hits)}, and which number replaces which cannot be told: correct one number at a time")
        old_f, new_f = hits.pop(), new.pop()
        tok = next(m for m in FACT_RX.finditer(action) if NUMBER_WORDS.get(m.group(0).lower(), m.group(0).lower()) == old_f)
        word = not tok.group(0).isdigit() and new_f in WORD_OF
        return action[:tok.start()] + (WORD_OF[new_f] if word else new_f) + action[tok.end():]
    if _negations(before) != _negations(after):
        raise ValueError(f"the correction adds or removes a negation in a sentence whose action {action!r} is written in other "
                         "words, so the changed action cannot be derived from it: correct the words the action states, or a clinician "
                         "source states the changed action")
    return action


def corrected_words(text: str | None, corr: dict) -> str | None:
    """A condition after a transcript correction of the sentence it rests on: the corrected words applied to it (a bare
    clock in either spelling); unchanged when it does not contain them."""
    if not text:
        return text
    cf, ct = _clock_canon(corr["from"]), _clock_canon(corr["to"])
    if cf and ct:
        return _clock_rx(cf).sub(lambda m: ct, text)
    return re.sub(re.escape(corr["from"]), lambda m: corr["to"], text, flags=re.I)


def _cond_stems(text: str | None) -> set[str]:
    return {w[:3] for w in re.findall(r"[a-z]+", (text or "").lower()) if len(w) >= 3 and w not in CONDITION_STOP}


def _states_clock_or_weekday(text: str | None) -> bool:
    return bool(CLOCK_RX.search(text or "") or WEEKDAY_RX.search(text or ""))


def _time_parts(phrase: str | None) -> tuple[str | None, str | None]:
    """(weekday, clock) of an instruction time in canonical spelling: those of canonical_time, or for a time nobody could
    read ('Wed 4 p.m.', 'Wednesday at 4.30 p.m.', 'Thursday morning') the weekday it names (also abbreviated) and its readable
    clock if any, so an earlier time that is the same weekday or
    clock is not forbidden in a rewrite of it (the time is never guessed: nothing is required from an unreadable one)."""
    c = canonical_time(phrase)
    if c:
        wd, ck = c.split(" ", 1)
        return wd, ck
    ck = next((c for c in (_clock_canon(m.group(0)) for m in CLOCK_RX.finditer(phrase or "")) if c), None)
    full = WEEKDAY_RX.search(phrase or "")
    wd = full.group(1).capitalize() if full else next((w.capitalize() for w in WEEKDAYS if re.search(r"\b" + w[:3] + r"(?![a-z])", (phrase or "").lower())), None)
    return wd, ck


def action_overlap(a: str, b: str) -> float:
    """Share of 4-letter word stems two actions have in common (Jaccard). Used only to VALIDATE a supersedes target a
    person chose, or to suggest one; it never decides on its own."""
    sa, sb = _stems(a), _stems(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def action_label(action: str) -> str:
    """Plain-language label of an instruction for notices ('attend follow-up appointment' -> 'Follow-up')."""
    if "follow-up" in (action or "").lower():
        return "Follow-up"
    return (action or "instruction")[:1].upper() + (action or "instruction")[1:]


def correction_label(from_text: str, affected_actions: list[str]) -> str:
    """Label of a transcript-correction notice: 'Follow-up time', 'Time' or 'Transcript text' (B-P7 wording)."""
    is_time = bool(re.search(r"\d{1,2}(:\d{2})?\s*(a\.?m\.?|p\.?m\.?)?", from_text))
    follow_up = any("follow-up" in (a or "") for a in affected_actions)
    return "Follow-up time" if is_time and follow_up else ("Time" if is_time else "Transcript text")


def payload_hash(change: dict) -> str:
    """sha256 of the canonical JSON of a change without its request_id (the idempotency key's second half)."""
    body = json.dumps({k: v for k, v in change.items() if k != "request_id"}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


def unchanged_hash(obj: dict) -> str:
    """Hash used by the 'unchanged' checks. An item: every field of its latest version except `cites`, with a task's
    `schedule` reduced to the APPROVED basis (due_at/assignee/status; an exported PDF keeps its schedule rows whole). An
    instruction: every field except `cites`. So content, review_status, version, origin, derivation and the change that
    produced the version all count; cites and the proposed basis do not (a citation may re-point to a new revision with
    byte-equal text; a follower's proposed time may move without its content changing). It is an opaque server-side
    token (16 hex characters of sha256 over canonical JSON), compared only with values from the same server."""
    if "item_id" in obj:
        core = {k: v for k, v in obj.items() if k != "cites"}
        sch = obj.get("schedule")
        if isinstance(sch, dict):   # a task's schedule; an exported PDF keeps its schedule rows whole
            core["schedule"] = {k: sch.get(k) for k in ("due_at", "assignee", "status")}
        return content_hash(core)
    return content_hash({k: v for k, v in obj.items() if k != "cites"})


def _hm(iso: str) -> str:
    return iso[11:16]


def _dm(iso: str) -> str:
    d = dt.datetime.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def _fmt(iso: str | None, weekday: bool = False) -> str:
    """'2026-10-14T16:00' -> '14 Oct 16:00' or 'Wed 14 Oct 16:00'."""
    if not iso:
        return "no time"
    d = dt.datetime.fromisoformat(iso)
    return f"{d.strftime('%a') + ' ' if weekday else ''}{d.day} {d.strftime('%b')} {d.strftime('%H:%M')}"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


# ---------------------------------------------------------------- confirmation roles: the exclusion rule (pure functions)
def _nfkc(text: str | None) -> str:
    """NFKC form of a text (full-width letters, ligatures and compatibility digits become plain ones) before any rule reads it."""
    return unicodedata.normalize("NFKC", text or "")


def _odd_letters(text: str | None) -> list[str]:
    """The letters of a text (after NFKC) outside plain ASCII: a Cyrillic 'а' in 'tаblets' reads like a Latin 'a' to a person
    but matches no word rule, so the engine cannot read such a text and treats it as clinician-only."""
    return sorted({ch for ch in _nfkc(text) if ord(ch) > 127 and unicodedata.category(ch).startswith("L")})


def _strip_times(text: str | None) -> str:
    """A text with every clock (either spelling, also a 24-hour '14:05') and every date (day-first or month-first) set aside."""
    return DATE_RX.sub(" ", H24_RX.sub(" ", CLOCK_RX.sub(" ", _nfkc(text))))


def _dose_sequence(text: str | None) -> list[str]:
    """The numbers of a text that may be a dose or a count, IN ORDER: digits (also glued to a unit, '500mg' -> '500'),
    number words ('two' == '2', 'forty' == '40', 'hundred') and multipliers ('twice', 'double' -> 'x2', 'once' -> 'x1',
    'half'), with every clock and date set aside (_strip_times): a moved appointment is not a changed number. Compared as
    a sequence, so '1 Keppra in the morning and 2 at night' -> '2 ... and 1 ...' is a changed dose."""
    return [m.group(0).replace(",", ".") if m.group(0)[0].isdigit() else DOSE_WORDS[m.group(0).lower()]
            for m in DOSE_NUMBER_RX.finditer(_strip_times(text))]


def _dose_numbers(text: str | None) -> set[str]:
    """The set of _dose_sequence (kept for callers that compare sets)."""
    return set(_dose_sequence(text))


def _stop_words(text: str | None) -> set[str]:
    """The negating words of a text plus stop words (discontinue, skip, hold, omit, pause, cease, withhold, halt, cancel,
    'no more', 'no longer'): 'skip the evening dose' stops a medication as much as 'do not take' does."""
    t = norm(_nfkc(text))
    return _negations(t) | {" ".join(m.group(0).lower().split()) for m in STOP_RX.finditer(t)}


def _words(text: str | None) -> list[str]:
    """Lower-case ASCII words of a text after NFKC, 'medication list' / 'medicine list' as one word (a document), a
    possessive "'s" dropped, hyphenated words split ('follow-up' -> 'follow', 'up')."""
    t = re.sub(r"\b(?:medication|medicine)\s+lists?\b", "medication_list", norm(_nfkc(text)).lower())
    return re.findall(r"[a-z_]+|\d+", re.sub(r"['’]s\b", "", t))


def _template_words(text: str | None, times=()) -> list[str]:
    """The words of an action or condition the allow-list reads: weekdays, months, clocks and dates (also those of `times`)
    and filler words set aside. Digits stay (a number is never part of an allowed template)."""
    core = _strip_times(_action_core(_nfkc(text), times))
    return [w for w in _words(core) if w not in ON_BEHALF_FILLER and w not in WEEKDAYS and not MONTH_RX.fullmatch(w)
            and not re.fullmatch(r"[ap]|[ap]m", w)]


def allowed_action(action: str | None, times=()) -> bool:
    """Is the action one of the two templates the primary caregiver may confirm on the clinician's behalf? (a) attend /
    keep / go to an appointment ('attend follow-up appointment'): the verb, then appointment words only, one of them
    appointment, visit or check-up; (b) bring a document or an aid ('bring blood pressure diary', 'bring current
    medication list', 'bring the walking frame'): 'bring', then those object words only. Anything else, a medication or
    brand name the engine has never heard of included, is not on the list."""
    w = _template_words(action, times)
    if len(w) < 2 or _odd_letters(action):
        return False
    head, rest = w[0], w[1:]
    if head in APPOINTMENT_VERBS:
        return set(rest) <= APPOINTMENT_WORDS and bool(set(rest) & APPOINTMENT_HEADS)
    if head == "bring":
        return set(rest) <= BRING_WORDS
    return False


def allowed_condition(condition: str | None, times=()) -> bool:
    """Every word of the condition (weekdays, months, clocks, dates and fillers aside) is appointment vocabulary ('to the
    follow-up appointment', 'at the clinic on Wednesday'); no number, no other word."""
    if _odd_letters(condition):
        return False
    return set(_template_words(condition, times)) <= CONDITION_WORDS


def instruction_kind_exclusions(state: dict | None) -> list[str]:
    """Why an instruction state (action, condition, time) is never confirmable on the clinician's behalf whatever its
    change: letters the engine cannot read, an action outside the two templates (allowed_action), a condition outside
    appointment vocabulary (allowed_condition). Empty for an allowed one or None."""
    if not state:
        return []
    act, cond, times, out = state.get("action") or "", state.get("condition") or "", [state.get("time")], []
    odd = _odd_letters(f"{act} {cond}")
    if odd:
        out.append(f"its words contain letters outside plain English ({''.join(odd)}): the engine cannot read them, so it cannot tell "
                   "this is not a medication or dose instruction")
    if not allowed_action(act, times):
        out.append(f"its action {act!r} is not one the engine knows is safe to confirm on the clinician's behalf (only: attend an "
                   "appointment; bring a document or an aid to it): the engine cannot tell it is not a medication, dose or condition "
                   "instruction")
    if cond and not allowed_condition(cond, times):
        out.append(f"its condition {cond!r} is not only about the appointment it goes with: the engine cannot tell it is not a "
                   "medication, dose or care condition")
    return out


def _clauses(text: str | None) -> set[str]:
    """The clauses of a text (CLAUSE_SPLIT_RX: '11:00' and 'a.m.' stay whole), as comparison keys (_text_key)."""
    return {k for k in (_text_key(p) for p in CLAUSE_SPLIT_RX.split(_nfkc(text))) if k}


def _relax_stems(text: str | None) -> set[str]:
    """The 3-letter stems of a condition (_cond_stems) plus 'only', which _cond_stems sets aside but which is what makes
    'only when someone is there' stricter than 'when someone is there'."""
    return _cond_stems(text) | ({"only"} if re.search(r"\bonly\b", text or "", re.I) else set())


def _stem_words(text: str | None, stems: set[str]) -> list[str]:
    """The words of `text` whose stem is in `stems` (to name dropped condition words in plain words)."""
    return list(dict.fromkeys(w for w in re.findall(r"[a-z]+", (text or "").lower())
                              if (w == "only" and "only" in stems) or (len(w) >= 3 and w not in CONDITION_STOP and w[:3] in stems)))


def condition_relaxation(old: str | None, new: str | None) -> list[str]:
    """Why changing an instruction's condition from `old` to `new` may relax it (empty: it does not). Fail closed:
      - the new condition reads as a relaxation (the forbid_relaxing patterns);
      - an approved condition is removed, loses a word (3-letter stem, 'only' included), or changes in any other way
        (words added included: 'unless she feels steady', 'or alone in the afternoon' and 'at most 10 glasses' keep
        every old word; the engine cannot tell a stricter wording from a looser one);
      - a condition where there was none states an exception or independence word ('unless', 'except', 'or', 'only on',
        'alone', 'bad days', ...), a number (a dose or a count) or a negating or stop word.
    Only case, whitespace and outer punctuation never count (_text_key)."""
    old, new = " ".join((old or "").split()), " ".join((new or "").split())
    out = []
    if new and check_item_content(new, forbid_relaxing=True):
        out.append(f"the condition {new!r} reads as a relaxation")
    if old and not new:
        out.append(f"the condition {old!r} is removed")
    elif old and _text_key(_nfkc(old)) != _text_key(_nfkc(new)):
        gone = _relax_stems(old) - _relax_stems(new)
        if gone:
            out.append(f"the condition {old!r} loses {', '.join(repr(w) for w in _stem_words(old, gone))} in {new!r} (removed or loosened)")
        else:
            out.append(f"the condition {old!r} changes to {new!r}: any change of an approved condition is the clinician's (the engine "
                       "cannot tell a stricter wording from a looser one)")
    elif new and not old:
        marks = list(dict.fromkeys(" ".join(m.group(0).lower().split()) for m in EXCEPTION_RX.finditer(_nfkc(new))))
        if marks:
            out.append(f"the condition {new!r} states an exception or independence ({', '.join(repr(m) for m in marks)}): it may loosen "
                       "the instruction")
        nums = _dose_sequence(new)
        if nums:
            out.append(f"the condition {new!r} states a number ({', '.join(nums)}): a dose or a count")
        stops = sorted(_stop_words(new))
        if stops:
            out.append(f"the condition {new!r} states a negating or stop word ({', '.join(stops)})")
    return out


def instruction_change_exclusions(prev: dict | None, cur: dict) -> list[str]:
    """Why an instruction's pending change is clinician-only (empty: the primary caregiver may confirm it on the
    clinician's behalf). `prev` is its last approved state (time, condition, action), None for a new instruction. Fail
    closed: allowed only when the action and condition, now and approved, pass instruction_kind_exclusions (the two
    templates) AND the change is a new instruction whose action states no number and no negating or stop word and whose
    condition passes condition_relaxation, or a time-only move (same action, same condition). Reasons, in this order:
      - a medication instruction (its action or condition, now or approved, names a medication word): any change;
      - instruction_kind_exclusions of the current and of the approved state;
      - a new instruction whose action states a number or a negating or stop word (a dose, a count or a stop);
      - an action that differs from the approved one at all (a changed dose, count, a stop or a negation);
      - a condition that changes in any way (condition_relaxation), or is added to an approved instruction."""
    out = []
    words = _nfkc(" ".join(x for x in (cur.get("action"), cur.get("condition"), (prev or {}).get("action"), (prev or {}).get("condition")) if x))
    meds = list(dict.fromkeys(m.group(0).lower() for m in MEDICATION_RX.finditer(words)))
    if meds:
        out.append(f"a medication instruction ({', '.join(meds)}): every change of it is the clinician's")
    out += instruction_kind_exclusions(cur)
    if prev is not None and _text_key(prev.get("action")) != _text_key(cur.get("action")):
        out += [f"{x} (in its approved state)" for x in instruction_kind_exclusions(prev)]
    if prev is None:
        core = _action_core(_nfkc(cur.get("action")), [cur.get("time")])
        said = list(dict.fromkeys(_dose_sequence(core) + sorted(_stop_words(core))))
        if said:
            out.append(f"a new instruction whose action states {', '.join(repr(s) for s in said)} (a dose, a count or a stop)")
        out += condition_relaxation(None, cur.get("condition"))
    else:
        if _text_key(_nfkc(prev.get("action"))) != _text_key(_nfkc(cur.get("action"))):
            out.append(f"its action changes from {prev.get('action')!r} to {cur.get('action')!r} (a dose, a count, a stop or a negation)")
        if not (prev.get("condition") or "").strip() and (cur.get("condition") or "").strip():
            out.append(f"a condition {cur.get('condition')!r} is added to an approved instruction: a new condition is the clinician's")
        else:
            out += condition_relaxation(prev.get("condition"), cur.get("condition"))
    return list(dict.fromkeys(out))


def _ground_key(w: str) -> str:
    """A word as the grounding test compares it: a plural 's' set aside ('diaries' and 'diary' are not merged; 'lists' and 'list' are)."""
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def _ground_words(texts) -> set[str]:
    """The words the given texts state (clocks and dates aside), as _ground_key compares them."""
    return {_ground_key(w) for t in texts if t for w in _words(_strip_times(t))}


def text_change_exclusions(old: str | None, new: str | None, grounded=frozenset(), grounding=None) -> list[str]:
    """Why an item text change from `old` (its last approved version; None or '' for a new item) to `new` is
    clinician-only (empty: it is not):
      - its dose or count numbers differ as an ORDERED sequence (_dose_sequence: clocks and dates set aside, digits glued
        to a unit and number words counted; `grounded` are numbers a cited event record states, a clip id or a model
        score, which are not doses);
      - its negating or stop words differ (_stop_words);
      - a clause that changed (present in one text only) names a medication word, or a verb that gives or changes one
        (give, take, start, increase, reduce, double, ...);
      - it contains letters outside plain ASCII (_odd_letters);
      - it reads as a relaxation (the forbid_relaxing patterns);
      - `grounding` (texts: the approved text and the actions and conditions of the instructions the item rests on; None:
        not checked) does not state every word the new text has, fillers, weekdays, months and clocks aside: a word
        nothing grounds ('unless', 'Lantus', 'bad days') is a change the engine cannot judge."""
    out = []
    a = [x for x in _dose_sequence(old) if x not in grounded]
    b = [x for x in _dose_sequence(new) if x not in grounded]
    if a != b:
        out.append(f"its numbers change ({', '.join(a) or 'none'} -> {', '.join(b) or 'none'}): a dose or a count")
    na, nb = _stop_words(old), _stop_words(new)
    if na != nb:
        out.append(f"its negating words change ({', '.join(sorted(na)) or 'none'} -> {', '.join(sorted(nb)) or 'none'}): a stop or a negation")
    changed = sorted(_clauses(old) ^ _clauses(new))
    meds = list(dict.fromkeys(m.group(0).lower() for c in changed for m in MEDICATION_RX.finditer(c)))
    if meds:
        out.append(f"a changed sentence names a medication ({', '.join(meds)})")
    verbs = list(dict.fromkeys(m.group(0).lower() for c in changed for m in MED_VERB_RX.finditer(c)))
    if verbs:
        out.append(f"a changed sentence says to give, take or change something ({', '.join(verbs)}): the engine cannot rule out a medication")
    odd = _odd_letters(new)
    if odd:
        out.append(f"its text contains letters outside plain English ({''.join(odd)}): the engine cannot read it")
    if check_item_content(_nfkc(new), forbid_relaxing=True):
        out.append("it reads as a relaxation")
    if grounding is not None:
        known = _ground_words([old] + list(grounding)) | {_ground_key(w) for w in TEXT_FILLER | set(WEEKDAYS)}
        extra = sorted({w for w in _words(_strip_times(new)) if _ground_key(w) not in known and w not in TEXT_FILLER and not w.isdigit()
                        and not MONTH_RX.fullmatch(w) and not re.fullmatch(r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)", w)})
        if extra:
            out.append(f"it adds words that neither its approved text nor the instructions it rests on state ({', '.join(extra)}): the "
                       "engine cannot tell what they change")
    return out


def _duration(minutes: int) -> str:
    """75 -> '1 h 15 min', 38 -> '38 min', 1440 -> '24 h'."""
    h, m = divmod(max(0, int(minutes)), 60)
    return " ".join(x for x in ((f"{h} h" if h else ""), (f"{m} min" if m or not h else "")) if x)


def _reason_text(value, what: str) -> str:
    """A free-text reason printed into labels, notices and the exported PDF: one line (whitespace runs collapsed), not
    empty, at most MAX_REASON characters, no double quote (the label quotes it), plain ASCII letters, never a relaxing
    sentence, and only why the clinician cannot be reached: no medication word, no verb that gives or changes one, no stop
    word and no number other than a clock, a weekday or a date ('closed until Monday', 'back at 9 a.m.' pass; 'nurse said
    stop the furosemide and give forty units' does not)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} needs a non-empty 'reason' (why the clinician cannot be reached)")
    text = " ".join(value.split())
    if len(text) > MAX_REASON:
        raise ValueError(f"{what}: 'reason' has at most {MAX_REASON} characters")
    if '"' in text:
        raise ValueError(f"{what}: 'reason' may not contain a double quote (it is quoted in the label)")
    if check_item_content(text, forbid_relaxing=True):
        raise ValueError(f"{what}: 'reason' reads as a relaxation of an instruction; it is printed next to the care content, so state "
                         "only why the clinician cannot be reached")
    # 'on hold' and 'cancelled' are how a clinic is unreachable, not a stop of care: only the other stop words count here
    stops = [m.group(0) for m in STOP_RX.finditer(_nfkc(text)) if not re.fullmatch(r"hold|holding|held|cancel\w*", m.group(0), re.I)]
    care = [m.group(0) for rx in (MEDICATION_RX, MED_VERB_RX) for m in rx.finditer(_nfkc(text))] + stops + _dose_sequence(text) \
        + _odd_letters(text)
    if care:
        raise ValueError(f"{what}: 'reason' may only say why the clinician cannot be reached (it is printed next to the care content); "
                         f"it states {', '.join(repr(c) for c in dict.fromkeys(care))}, which reads as care content (a medication, a "
                         "dose, a number or a stop)")
    return text


# ---------------------------------------------------------------- the store extension
class PropagatingStore(CaseStore):
    """CaseStore plus update propagation. Existing CaseStore methods keep their behaviour; everything added here is
    deterministic. `rewriter` (optional, set by the server) is the only place an LLM may propose text."""

    def __init__(self, scenario: dict):
        super().__init__(scenario)
        self.case_version = scenario.get("case_version_start", 1)
        self.week_anchor = scenario.get("week_anchor", "2026-10-12")
        self.rota = copy.deepcopy(scenario.get("rota", []))
        self.roles = dict(scenario.get("roles", {}))
        self.seq = 0                                   # log position: +1 per accepted event (reviews included)
        self.change_events: list[dict] = []
        self.requests: dict[str, dict] = {}            # request_id -> {change_id, payload_hash}
        self.uploads_by_sha: dict[str, str] = {}       # content_sha256 -> change_id
        self.seen: dict[str, dict] = copy.deepcopy(scenario.get("seen_start", {}))
        self.jobs: dict[str, dict] = {}
        self.rewriter = None
        # confirmation roles: the case's one primary family caregiver (set at case creation or by a clinician), the time
        # limit after which that caregiver may confirm a pending change on the clinician's behalf, and the
        # clinician-unreachable mark ({by, reason, at, change_id}; cleared when a clinician acts)
        self.primary_caregiver: str | None = None
        self.on_behalf_after_hours: int = ON_BEHALF_DEFAULT_HOURS
        self.clinician_unreachable: dict | None = None
        # the latest `at` of an accepted change (a high-water mark): a change's `effective_at` is never earlier, so a
        # backdated `at` cannot make a pending change look older than the last activity in the case (_pending_since)
        self.clock_high: str | None = None
        settings = scenario.get("case_settings") or {}
        if not isinstance(settings, dict):
            raise ValueError("case_settings is an object {primary_caregiver, on_behalf_after_hours}")
        self._apply_settings(settings, "case_settings")
        for versions in self.items.values():
            self.recompute_schedule(versions[-1])

    # the rewriter is a live callback (often a bound method of the agent): never copied into a snapshot
    def snapshot(self) -> dict:
        rw, self.rewriter = self.rewriter, None
        try:
            return super().snapshot()
        finally:
            self.rewriter = rw

    def restore(self, snap: dict) -> None:
        rw = self.rewriter
        super().restore(snap)
        self.rewriter = rw

    def update_instruction_from_revision(self, instruction_id: str, new_time: str | None, new_rev: str, source_id: str) -> dict:
        """CaseStore's update (a transcript correction), plus: an on-behalf label of the approved state moves into
        `previous` with that state (a rejection brings it back with it), never stays on the pending one; and when that
        state was approved only on the clinician's behalf, the clinician's own last approved state is kept under it
        (`clinician_previous`), so a clinician's later rejections reach it."""
        ins = self.instructions[instruction_id]
        fresh = ins.get("derivation_status") != "pending_review" or not ins.get("previous")
        labels = self._pop_labels(ins)
        basis = self._clinician_basis(ins.get("previous")) if fresh and self._on_behalf_only(labels) else None
        out = super().update_instruction_from_revision(instruction_id, new_time, new_rev, source_id)
        if fresh and labels:
            ins["previous"].update(labels)
        if basis:
            ins["previous"]["clinician_previous"] = basis
        return out

    # ---------------------------------------------------------------- confirmation roles: settings, labels, the exclusion rule
    @staticmethod
    def _pop_labels(obj: dict) -> dict:
        return {k: obj.pop(k) for k in LABEL_KEYS if k in obj}

    @staticmethod
    def _carry_labels(v: dict, src: dict) -> None:
        """A version restored from `src` keeps how `src` was confirmed (on the clinician's behalf, clinician-confirmed)."""
        for k in LABEL_KEYS:
            if k in src:
                v[k] = copy.deepcopy(src[k])

    @staticmethod
    def _on_behalf_only(state: dict | None) -> bool:
        """Confirmed by the primary caregiver on the clinician's behalf and not (yet) by a clinician."""
        return bool(state and state.get("confirmed_on_behalf") and not state.get("clinician_confirmed"))

    def _clinician_basis(self, state: dict | None) -> dict | None:
        """The newest state a clinician approved at or under an instruction's `previous`: the state itself when a clinician
        approved it, else (approved only on the clinician's behalf) its `clinician_previous`. None for a state nobody
        approved (was_approved False) or when no clinician-approved state is known."""
        while state:
            if not state.get("was_approved", True):
                return None
            if not self._on_behalf_only(state):
                return {k: copy.deepcopy(v) for k, v in state.items() if k != "clinician_previous"}
            state = state.get("clinician_previous")
        return None

    def _apply_settings(self, settings: dict, what: str) -> dict:
        """Validate and apply case settings; returns {field: {from, to}} for every field that changed. primary_caregiver is
        one actor label whose role is caregiver (never a clinician); on_behalf_after_hours an integer number of hours."""
        unknown = sorted(set(settings) - {"primary_caregiver", "on_behalf_after_hours"})
        if unknown:
            raise ValueError(f"{what}: unknown setting(s) {', '.join(unknown)} (known: primary_caregiver, on_behalf_after_hours)")
        diff = {}
        if "primary_caregiver" in settings:
            p = settings["primary_caregiver"]
            if not isinstance(p, str) or not LABEL_RX.match(p):
                raise ValueError(f"{what}: 'primary_caregiver' is one caregiver's actor label (letters, digits, space, _ @ ( ) -; at most 64 characters)")
            if (self.roles.get(p) or "caregiver") != "caregiver":
                raise ValueError(f"{what}: 'primary_caregiver' must be a family caregiver; {p} is {self.roles.get(p)}")
            if p != self.primary_caregiver:
                diff["primary_caregiver"] = {"from": self.primary_caregiver, "to": p}
            self.primary_caregiver = p
        if "on_behalf_after_hours" in settings:
            h = settings["on_behalf_after_hours"]
            if isinstance(h, bool) or not isinstance(h, int) or not 1 <= h <= ON_BEHALF_MAX_HOURS:
                raise ValueError(f"{what}: 'on_behalf_after_hours' is a whole number of hours from 1 to {ON_BEHALF_MAX_HOURS}, got {h!r}")
            if h != self.on_behalf_after_hours:
                diff["on_behalf_after_hours"] = {"from": self.on_behalf_after_hours, "to": h}
            self.on_behalf_after_hours = h
        return diff

    def confirmation_settings(self) -> dict:
        """The confirmation-role state as the UI shows it: the primary caregiver, the time limit, the unreachable mark,
        every current version or instruction that was confirmed on the clinician's behalf and awaits the clinician
        (`awaiting_clinician`, what a clinician's approve confirms), and every id whose newer change is pending while the
        version in force under it was confirmed on the clinician's behalf (`in_force_awaiting_clinician`, display only)."""
        return {"primary_caregiver": self.primary_caregiver, "on_behalf_after_hours": self.on_behalf_after_hours,
                "clinician_unreachable": copy.deepcopy(self.clinician_unreachable), "awaiting_clinician": self.awaiting_clinician(),
                "in_force_awaiting_clinician": sorted(i for i in list(self.items) + list(self.instructions) if self._in_force_on_behalf(i))}

    def _current(self, iid: str) -> dict:
        return self.latest(iid) if iid in self.items else self.instructions[iid]

    def _awaiting_clinician(self, iid: str) -> bool:
        """In force (approved) on the primary caregiver's on-behalf confirmation, and not yet confirmed by a clinician."""
        if iid not in self.items and iid not in self.instructions:
            return False
        cur = self._current(iid)
        status = cur.get("review_status") if iid in self.items else cur.get("derivation_status")
        return status == "approved" and bool(cur.get("confirmed_on_behalf")) and not cur.get("clinician_confirmed")

    def awaiting_clinician(self) -> list[str]:
        return sorted(i for i in list(self.items) + list(self.instructions) if self._awaiting_clinician(i))

    @staticmethod
    def _label_of(state: dict | None) -> str | None:
        """The visible label of a version or instruction state confirmed on the clinician's behalf: 'confirmed by the
        primary caregiver on the clinician's behalf (cg-outgoing, 13 Oct 16:40; clinician unreachable since 13 Oct 16:35:
        "...")', later 'clinician-confirmed (reviewer, 14 Oct 09:00); earlier confirmed by ...'. None without one."""
        cob, cc = (state or {}).get("confirmed_on_behalf"), (state or {}).get("clinician_confirmed")
        if not cob:
            return None
        if cob.get("trigger") == "time_limit":
            trig = f"time limit: {cob['reason']}"
        else:
            trig = "clinician unreachable" + (f" since {_fmt(cob['marked_at'])}" if _dt(cob.get("marked_at")) else "") + f": \"{cob.get('reason')}\""
        head = f"{ON_BEHALF_LABEL} ({cob['by']}, {_fmt(cob.get('at'))}; {trig})"
        if cc:
            return f"clinician-confirmed ({cc['by']}" + (f", {_fmt(cc['at'])}" if cc.get("at") else "") + f"); earlier {head}"
        return head

    def confirmation_label(self, iid: str) -> str | None:
        """The visible label of how the current version (or instruction) was confirmed, when it is approved and the
        primary caregiver confirmed it on the clinician's behalf (_label_of). None for anything else (a clinician's own
        approval needs no label)."""
        if iid not in self.items and iid not in self.instructions:
            return None
        cur = self._current(iid)
        status = cur.get("review_status") if iid in self.items else cur.get("derivation_status")
        return self._label_of(cur) if status == "approved" else None

    def _in_force_on_behalf(self, iid: str) -> dict | None:
        """While a newer change of `iid` is pending (or the item is stale for a rewrite), the version or state still in force
        under it, when that one was approved only on the clinician's behalf: an item's last approved version, an
        instruction's `previous`. None otherwise. Display only: approve never confirms a superseded version in place."""
        if iid in self.items:
            cur = self.latest(iid)
            if cur.get("review_status") not in ("pending_review", "stale"):
                return None
            la = cur if self.was_approved(cur) and cur.get("review_status") == "stale" else self.last_approved(iid)
            return la if self._on_behalf_only(la) else None
        ins = self.instructions.get(iid) or {}
        prev = ins.get("previous")
        if ins.get("derivation_status") == "pending_review" and prev and prev.get("was_approved", True) and self._on_behalf_only(prev):
            return prev
        return None

    def in_force_label(self, iid: str) -> str | None:
        """'in force: <label>' for the on-behalf version or state still in force under a pending change (_in_force_on_behalf)."""
        st = self._in_force_on_behalf(iid)
        return f"in force: {self._label_of(st)}" if st else None

    def _labels_view(self) -> list[dict]:
        """Every version or instruction in force with an on-behalf label, for the handover view and the export: the current
        approved ones (basis 'current') and, while a newer change is pending, the on-behalf version or state still in force
        under it (basis 'in_force_while_change_pending', always awaiting the clinician)."""
        out = []
        for iid in sorted(list(self.items) + list(self.instructions)):
            label = self.confirmation_label(iid)
            if label:
                out.append({"id": iid, "version": self.latest(iid).get("version") if iid in self.items else None, "label": label,
                            "basis": "current", "awaiting_clinician": self._awaiting_clinician(iid),
                            **{k: copy.deepcopy(self._current(iid)[k]) for k in LABEL_KEYS if k in self._current(iid)}})
                continue
            st = self._in_force_on_behalf(iid)
            if st:
                out.append({"id": iid, "version": st.get("version") if iid in self.items else None, "label": self._label_of(st),
                            "basis": "in_force_while_change_pending", "awaiting_clinician": True,
                            **{k: copy.deepcopy(st[k]) for k in LABEL_KEYS if k in st}})
        return out

    def _last_approved_state(self, ins: dict) -> dict | None:
        """The last approved state of a pending instruction ({time, condition, action, cites}); None for one nobody
        approved yet (a new instruction)."""
        prev = ins.get("previous")
        return prev if prev and prev.get("was_approved", True) else None

    def _instruction_exclusions(self, j: str) -> list[str]:
        """Why instruction `j` is clinician-only as it stands: its pending change (instruction_change_exclusions against its
        last approved state), or, when it is not pending, its kind (a medication word, instruction_kind_exclusions)."""
        ins = self.instructions[j]
        if ins.get("derivation_status") == "pending_review":
            return instruction_change_exclusions(self._last_approved_state(ins), ins)
        words = _nfkc(" ".join(x for x in (ins.get("action"), ins.get("condition")) if x))
        meds = list(dict.fromkeys(m.group(0).lower() for m in MEDICATION_RX.finditer(words)))
        return ([f"a medication instruction ({', '.join(meds)})"] if meds else []) + instruction_kind_exclusions(ins)

    def _event_numbers(self, cites: list[dict]) -> set[str]:
        """The numbers a cited event record states (its sentence, clip id, model score and confirming actor, as
        _dose_sequence reads them): a fall note restating them states no dose."""
        out = set()
        for c in cites:
            rev = self.latest_revision(c["source_id"]) or c.get("revision")
            src = self.sources.get((c["source_id"], rev)) or {}
            if src.get("source_type") == "event_confirmation":
                text = " ".join(str(x) for x in (self.segment_text(c["source_id"], rev, c.get("segment_id")), src.get("input_id"),
                                                 src.get("model_score"), src.get("confirmed_by"), src.get("rejudged_by")) if x is not None)
                out |= set(_dose_sequence(text))
        return out

    def on_behalf_exclusions(self, iid: str) -> list[str]:
        """Why the pending version (or instruction change) `iid` is clinician-only: never confirmable on the clinician's
        behalf (empty: it may be). Fail closed: when the engine cannot tell, the answer is clinician-only.
        An instruction: instruction_change_exclusions against its last approved state (the two-template allow-list, then
        a new such instruction or a time-only move).
        An item version, against the item's last approved version (none: the whole text is new):
          - it rests on an instruction (now or in its approved version) that is clinician-only as it stands: a pending change
            that is clinician-only, or an instruction outside the allow-list (a medication, a mobility rule, ...);
          - it cites a clinical source but rests on no instruction (the engine cannot tell what it restates);
          - text_change_exclusions: numbers as an ordered sequence, negating and stop words, a medication word or a verb that
            gives one in a changed clause, unreadable letters, a relaxing sentence, and (for an item that rests on
            instructions) any word that neither its approved text nor those instructions state; numbers a cited event
            record states are not doses;
          - it drops a word of the condition of an instruction it rests on (now or before) that the approved text stated;
          - it cancels a task (a care action removed).
        An event item (a fall note, its process task) rests on no instruction: the text rules above apply without the
        grounding test."""
        if iid in self.instructions:
            ins = self.instructions[iid]
            return instruction_change_exclusions(self._last_approved_state(ins), ins)
        v, out = self.latest(iid), []
        old = self.last_approved(iid)
        ins_ids = self._active(self.rests_on(v) + (self.rests_on(old) if old else []))
        for j in ins_ids:
            ex = self._instruction_exclusions(j)
            if ex:
                pending = self.instructions[j].get("derivation_status") == "pending_review"
                out.append(f"it rests on {j}, " + ("whose pending change is clinician-only" if pending else "which only a clinician may confirm")
                           + f" ({ex[0]})")
        cites = list(v.get("cites") or []) + list((old or {}).get("cites") or [])
        types = {(self.sources.get((c["source_id"], self.latest_revision(c["source_id"]) or c.get("revision"))) or {}).get("source_type")
                 for c in cites}
        if not ins_ids and types - {"event_confirmation"}:
            out.append("it cites a clinical source but rests on no instruction of the case, so the engine cannot tell what it states")
        old_text, new_text = (old or {}).get("content") or "", v.get("content") or ""
        grounding = None
        if ins_ids:
            grounding = [x for j in ins_ids for st in (self.instructions[j], self._last_approved_state(self.instructions[j]) or {})
                         for x in (st.get("action"), st.get("condition")) if x]
        out += text_change_exclusions(old_text, new_text, self._event_numbers(cites), grounding)
        have_old, have_new = _relax_stems(old_text), _relax_stems(new_text)
        for j in ins_ids:
            ins = self.instructions[j]
            conds = [ins.get("condition"), (ins.get("previous") or {}).get("condition")] + \
                [c for h in ins.get("history") or [] for c in (h.get("condition"), h.get("to_condition"))]
            stems = set().union(*[_relax_stems(c) for c in conds if c] or [set()])
            gone = (stems & have_old) - have_new
            if gone:
                out.append(f"it drops {', '.join(repr(w) for w in _stem_words(old_text, gone))} of {j}'s condition, which the approved text stated")
        if v.get("kind") == "task" and (v.get("schedule") or {}).get("status") == "cancelled" \
                and ((old or {}).get("schedule") or {}).get("status") != "cancelled":
            out.append("it cancels a task (a care action is removed)")
        return list(dict.fromkeys(out))

    def _pending_since(self, iid: str) -> str | None:
        """When the pending version (or instruction change) became pending: the `effective_at` of the change that produced
        it (its `at`, never earlier than the latest `at` the case had accepted before it, so a backdated `at` cannot open
        the time limit). Never the source's uploaded_at (a client field). None when the change carried no `at` (or a time
        with a timezone, from a state stored before that was refused): the time limit cannot be checked, only the
        unreachable mark can be used."""
        chg = (self.instructions[iid].get("last_change") or {}).get("change_id") if iid in self.instructions else self.latest(iid).get("change_id")
        ev = next((e for e in self.change_events if e["change_id"] == chg), None) if chg else None
        if ev is None:
            return None
        at = ev.get("effective_at", ev.get("at"))
        d = _dt(at)
        return at if d is not None and d.tzinfo is None else None

    def _trigger(self, iid: str, at: str) -> tuple[dict | None, str | None]:
        """(trigger, None) when the primary caregiver may confirm `iid` on the clinician's behalf at `at`, else (None, why).
        The time limit (it has waited longer than on_behalf_after_hours since it became pending) is used when it holds,
        else the clinician-unreachable mark: set at or before `at`, and not before the change became pending (a mark
        from before the change was not about it: the primary caregiver marks again). Either one suffices."""
        since, limit, now = self._pending_since(iid), self.on_behalf_after_hours, _dt(at)
        d_since = _dt(since)
        waited = int((now - d_since).total_seconds() // 60) if d_since is not None and now is not None and now.tzinfo is None else None
        if waited is not None and waited > limit * 60:
            return {"trigger": "time_limit", "reason": f"pending {_duration(waited)} since {_fmt(since)}, longer than the case's time limit of {limit} h",
                    "pending_since": since, "limit_hours": limit}, None
        mark = self.clinician_unreachable
        m_at = _dt((mark or {}).get("at"))
        stale_mark = bool(mark and m_at is not None and d_since is not None and m_at < d_since)
        if mark and m_at is not None and now is not None and m_at <= now and not stale_mark:
            return {"trigger": "clinician_unreachable", "reason": mark["reason"], "marked_by": mark["by"], "marked_at": mark["at"],
                    "pending_since": since}, None
        why = (f"pending {_duration(waited)} since {_fmt(since)}, not longer than the case's time limit of {limit} h" if waited is not None and waited >= 0
               else f"it became pending at {_fmt(since)}, after {_fmt(at)}" if since
               else "when it became pending is not recorded, so the time limit cannot be checked")
        if stale_mark:
            return None, why + (f", and the clinician-unreachable mark ({_fmt(mark['at'])}) is older than this change: mark the clinician "
                                "unreachable again if they still cannot be reached")
        return None, why + ", and the clinician is not marked unreachable"

    def _require_primary(self, actor: str, role: str, what: str) -> None:
        if role != "caregiver":
            raise PermissionError(f"{what} is for the case's primary family caregiver; {actor} is {role}"
                                  + (" (a clinician approves or rejects instead)" if role == CLINICIAN_ROLE else ""))
        if self.primary_caregiver is None:
            raise PermissionError(f"{what}: this case has no primary caregiver; a clinician sets one (case_settings)")
        if actor != self.primary_caregiver:
            raise PermissionError(f"{what} is for the case's primary caregiver ({self.primary_caregiver}); {actor} is not")

    def on_behalf_check(self, actor: str, at: str, ids: list[str] | None = None) -> dict:
        """Read-only: what `actor` (the primary caregiver) may confirm on the clinician's behalf at `at` (the server's
        clock), per pending id (default: everything pending review): allowed with its trigger, or refused with every
        reason (no trigger, clinician-only, no longer fits the case). Raises PermissionError when `actor` is not the
        primary caregiver. What the UI shows before the caregiver presses the button."""
        at = _local_iso(at, "an on-behalf confirmation's 'at' (the time it is confirmed)")
        self._require_primary(actor, self.roles.get(actor) or "caregiver", "confirming on the clinician's behalf")
        if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)):
            raise ValueError("'ids' must be a list of item or instruction ids")
        unknown = [i for i in ids or [] if i not in self.items and i not in self.instructions]
        if unknown:
            raise NotInCase(f"not in this case: {', '.join(unknown)}")
        allowed, refused = [], []
        for i in (self._pending_ids() if ids is None else list(dict.fromkeys(ids))):
            status = self.latest(i).get("review_status") if i in self.items else self.instructions[i].get("derivation_status")
            if status != "pending_review":
                refused.append({"item_id": i, "why": [f"not pending review ({status})"]})
                continue
            trig, reasons = self._on_behalf_judge(i, at)
            if reasons:
                refused.append({"item_id": i, "why": reasons})
            else:
                allowed.append({"item_id": i, **trig})
        return {"actor": actor, "at": at, "primary_caregiver": self.primary_caregiver, "on_behalf_after_hours": self.on_behalf_after_hours,
                "clinician_unreachable": copy.deepcopy(self.clinician_unreachable), "allowed": allowed, "refused": refused}

    def _on_behalf_judge(self, iid: str, at: str) -> tuple[dict | None, list[str]]:
        """(trigger, reasons) for one pending id; reasons empty means it may be confirmed on the clinician's behalf."""
        trig, why = self._trigger(iid, at)
        reasons = [f"no trigger: {why}"] if trig is None else []
        reasons += [f"clinician-only: {x}" for x in self.on_behalf_exclusions(iid)]
        fit = self.fit_problems(self.latest(iid)) if iid in self.items else self.instruction_problems(iid)
        reasons += [f"no longer fits the case: {p}" for p in fit]
        return trig, reasons

    # ---------------------------------------------------------------- schedule (dual basis)
    def instructions_for_item(self, item: dict) -> list[str]:
        if item.get("derived_from"):
            return [i for i in item["derived_from"] if i in self.instructions]
        keys = {(c["source_id"], c["segment_id"]) for c in item.get("cites", [])}
        return [i for i, ins in self.instructions.items() if ins.get("status") == "active"
                and keys & {(c["source_id"], c["segment_id"]) for c in ins["cites"]}]

    @staticmethod
    def _instruction_time(ins: dict, basis: str) -> str | None:
        prev = ins.get("previous")
        if basis == "approved" and ins.get("derivation_status") == "pending_review" and prev and prev.get("was_approved", True):
            return prev.get("time")      # the last approved time stays official until a person approves
        return ins.get("time")

    # ---------------------------------------------------------------- the fit check (one rule set, used everywhere)
    def rests_on(self, v: dict) -> list[str]:
        """Every instruction a version rests on: its `derived_from` (whatever their status), every active instruction
        whose current cite it cites (when the version has a derived_from, only one it is derived from or whose words or time
        its text restates: one sentence may ground two instructions), and every active instruction that moved away from a
        sentence it cites (a superseded,
        rejected or earlier cite) when no active instruction rests on that sentence any more. Unlike instructions_for_item,
        the cites count even when derived_from is set, so an item that rests on two instructions is judged against both,
        and an item that still cites an instruction's old or rejected sentence is judged against that instruction."""
        keys = {(c.get("source_id"), c.get("segment_id")) for c in v.get("cites", [])}
        active = {i: ins for i, ins in self.instructions.items() if ins.get("status") == "active"}
        now = {i: {(c["source_id"], c["segment_id"]) for c in ins.get("cites", [])} for i, ins in active.items()}
        held = set().union(*now.values()) if now else set()
        derived, content = v.get("derived_from") or [], v.get("content") or ""
        ids = [i for i in derived if i in self.instructions]
        # an instruction reached through a sentence it shares with another (one sentence grounding two instructions) belongs
        # to the version only when the version is about it: no derived_from, derived from it, or its text restates it
        ids += [i for i in active if keys & now[i] and (not derived or i in derived or self._restates(content, active[i]))]
        ids += [i for i, ins in active.items() if keys & ({(c["source_id"], c["segment_id"]) for c in self._earlier_cites(ins)} - held)]
        return list(dict.fromkeys(ids))

    def _active(self, ids) -> list[str]:
        return [i for i in dict.fromkeys(ids) if i in self.instructions and self.instructions[i].get("status") == "active"]

    @staticmethod
    def _earlier_times(ins: dict) -> list[str]:
        """Every earlier canonical time of an instruction that differs from its current one: the last approved time
        (`previous`), a rejected proposal (`rejected_change`) and every time it moved away from (`history`)."""
        cur = canonical_time(ins.get("time"))
        olds = [(ins.get("previous") or {}).get("time"), (ins.get("rejected_change") or {}).get("time")] + \
            [h.get("time") for h in ins.get("history") or []]
        return [o for o in dict.fromkeys(canonical_time(t) for t in olds) if o and o != cur]

    @staticmethod
    def _earlier_time_words(ins: dict) -> list[str]:
        """Every earlier time of an instruction as it was written (a readable one or words nobody could read)."""
        olds = [(ins.get("previous") or {}).get("time"), (ins.get("rejected_change") or {}).get("time")] + \
            [h.get("time") for h in ins.get("history") or []]
        return [o for o in dict.fromkeys(olds) if o and o != ins.get("time")]

    @staticmethod
    def _earlier_cites(ins: dict) -> list[dict]:
        """Every cite an instruction rested on before its current one (newest first is not needed: they are only matched)."""
        out = [ins.get("superseded_source")] + list((ins.get("previous") or {}).get("cites") or []) \
            + list((ins.get("rejected_change") or {}).get("cites") or []) + [c for h in ins.get("history") or [] for c in h.get("cites") or []]
        return [c for c in out if c]

    @staticmethod
    def _restates(content: str, ins: dict) -> bool:
        """Does the text restate the instruction (so it must state its current condition)? A timed instruction: the text
        states a time or a weekday; any instruction: the text has at least half of the action's word stems."""
        if canonical_time(ins.get("time")) and _states_clock_or_weekday(content):
            return True
        need = _stems(ins.get("action") or "")
        return bool(need) and len(need & _stems(content)) / len(need) >= CONDITION_MIN_COVERAGE

    def _condition_need(self, ins: dict) -> tuple[set[str], str | None]:
        """(stems a text restating the instruction must state, the condition they come from): the words the latest
        clinician change of the condition added to the one it replaced, followed through the transcript corrections made
        since (a correction that replaces such a word, 'your glasses' -> 'your hearing aid', requires the new word in its
        place; one that corrects other words of the condition, 'follow-up appointment' -> 'follow-up visit', adds no
        requirement). Nothing for a condition no change introduced, or one a rejection put back."""
        cond, hist = ins.get("condition"), ins.get("history") or []
        for k in range(len(hist) - 1, -1, -1):
            h = hist[k]
            if h.get("rejected") or h.get("corrected") or _text_key(h.get("to_condition")) == _text_key(h.get("condition")):
                continue
            c, need = h.get("to_condition"), _cond_stems(h.get("to_condition")) - _cond_stems(h.get("condition"))
            for g in hist[k + 1:]:
                if g.get("corrected") and not g.get("rejected") and _text_key(g.get("condition")) == _text_key(c) \
                        and _text_key(g.get("to_condition")) != _text_key(c):
                    removed = _cond_stems(g.get("condition")) - _cond_stems(g.get("to_condition"))
                    if need & removed:
                        need = (need - removed) | (_cond_stems(g.get("to_condition")) - _cond_stems(g.get("condition")))
                    c = g.get("to_condition")
            if _text_key(c) == _text_key(cond):
                return need, cond
        return set(), None

    def _condition_problems(self, content: str, iid: str) -> list[str]:
        """A text that restates the instruction states its current condition when a change introduced it (the words the
        new condition adds to the one it replaced, _condition_need), never the words a rejected condition would have added,
        and never words a transcript correction removed from the condition that no current source states any more."""
        ins = self.instructions[iid]
        if not self._restates(content, ins):
            return []
        cond, have, probs = ins.get("condition"), _cond_stems(content), []
        # words a transcript correction removed from the sentence the instruction rests on now are never required (the
        # condition may paraphrase the sentence, so its words were not corrected with it): the two rules never contradict
        now = {(c["source_id"], c["segment_id"]) for c in ins.get("cites") or []}
        gone = set().union(*[_cond_stems(r["from"]) - _cond_stems(r["to"]) for r in self.corrections if (r["source_id"], r["segment_id"]) in now] or [set()])
        need, _ = self._condition_need(ins)
        need -= gone
        if cond and need and len(need & have) / len(need) < CONDITION_MIN_COVERAGE:
            probs.append(f"does not state {iid}'s condition {cond!r}")
        hist = ins.get("history") or []
        rejected = [(ins.get("rejected_change") or {}).get("condition")] + [h.get("condition") for h in hist if h.get("rejected")]
        corrected = [h.get("condition") for h in hist if h.get("corrected") and _text_key(h.get("condition")) != _text_key(h.get("to_condition"))]
        grounded = set().union(*[_cond_stems(t) for t in self.current_source_texts()] or [set()])
        for what, olds, keep in (("rejected", rejected, set()), ("corrected-away", corrected, grounded)):
            for rej in dict.fromkeys(r for r in olds if r and _text_key(r) != _text_key(cond)):
                bad = _cond_stems(rej) - _cond_stems(cond) - keep
                if bad and len(bad & have) / len(bad) >= CONDITION_MIN_COVERAGE:
                    probs.append(f"states {iid}'s {what} condition {rej!r}")
        return probs

    def _action_problems(self, content: str, iid: str) -> list[str]:
        """A text that restates the instruction's action (half of its word stems, the weekday and clock of its times set
        aside) states the numbers (dose, count) and a negation the action states now, never a negating word that neither
        the action, its condition nor its cited sentence states ('do not take' for 'take'), and never a number or negation
        of an action it had before (a changed action, a rejected one, one a transcript correction removed)."""
        ins = self.instructions[iid]
        act = ins.get("action") or ""
        times = [ins.get("time")] + self._earlier_times(ins)
        need = _stems(_action_core(act, times))
        if not need or len(need & _stems(content)) / len(need) < CONDITION_MIN_COVERAGE:
            return []
        core = _action_core(act, times)
        cur_f, cur_n, have_f, have_n = _numeric_facts(core), _negations(core), _numeric_facts(content), _negations(content)
        probs = [f"does not state {iid}'s dose or count '{f}' ({act!r})" for f in sorted(cur_f - have_f)]
        if cur_n and not have_n:
            probs.append(f"does not state the negation of {iid}'s action {act!r}")
        if not cur_n:   # a negation nothing the instruction rests on states ('do not take' for 'take') turns the action around
            said = _negations(ins.get("condition") or "") | set().union(*[_negations(norm(self.segment_text(c["source_id"], self._follow_latest(c)["revision"], c["segment_id"]) or ""))
                                                                          for c in ins.get("cites") or []] or [set()])
            if have_n - said:
                probs.append(f"states a negation ({', '.join(sorted(have_n - said))}) that {iid}'s action {act!r}, its condition and its sentence do not")
        hist = ins.get("history") or []
        olds = [(ins.get("previous") or {}).get("action"), (ins.get("rejected_change") or {}).get("action")] + [h.get("action") for h in hist] \
            + [h.get("to_action") for h in hist]
        for o in dict.fromkeys(x for x in olds if x and _text_key(x) != _text_key(act)):
            oc = _action_core(o, times)
            probs += [f"still states '{f}' ({iid}'s action was {o!r})" for f in sorted((_numeric_facts(oc) - cur_f) & have_f)]
            if _negations(oc) and not cur_n and have_n:
                probs.append(f"states the negation of {iid}'s earlier action {o!r}")
        return probs

    def fit_problems(self, v: dict, also=(), waits=()) -> list[str]:
        """Why version `v` does not fit the case AS IT IS NOW (empty: it fits). The one rule set behind every gate: the
        restore after a rejection, a delivered text, a regenerated text, an approval and an export.
        For every instruction the version rests on (rests_on, plus `also` and `waits`):
          - the instruction is active (a withdrawn instruction carries nothing);
          - when the text states a clock or a weekday (or the item waits for a person's rewrite for it: `waits`), it
            states the instruction's current time (a readable one), and never one of its earlier times (`previous`,
            `rejected_change`, `history`): neither that clock nor, when it differs from the current one, that weekday;
            a clock matches only in its own half of the day (_time_rx);
          - a text that restates the instruction states the condition a change introduced (_condition_need), never a
            rejected condition, never words a transcript correction removed from it that no current source states;
          - a text that restates the action states its current numbers and negation, never an earlier action's;
          - its cites include the instruction's current source segment.
        And for the version itself: every cite is on the latest revision of its source; no cite of a sentence an active
        instruction moved away from that no active instruction holds; no value a transcript correction removed (unless a
        segment it cites states that value again on its latest revision); no fact (time, number, weekday) outside its
        cited segments (an event's record grounds its clip id and score) and the current time and sentence of those
        instructions."""
        if v.get("kind") not in CONTENT_KINDS:
            return []
        content, probs = v.get("content") or "", []
        waits = self._active(waits)   # a withdrawn instruction is nothing to wait for
        ids = list(dict.fromkeys(self.rests_on(v) + self._active(list(also)) + waits))
        keys = {(c.get("source_id"), c.get("segment_id")) for c in v.get("cites", [])}
        for c in v.get("cites", []):
            latest = self.latest_revision(c.get("source_id", ""))
            if latest and c.get("revision") != latest:
                same = self.segment_text(c["source_id"], latest, c.get("segment_id")) == self.segment_text(c["source_id"], c.get("revision"), c.get("segment_id"))
                probs.append(f"cites {c['source_id']} {c.get('revision')} {c.get('segment_id')}, "
                             + ("not the latest revision" if same else "corrected since") + f" in {latest}")
        stated = _states_clock_or_weekday(content)
        for iid in ids:
            ins = self.instructions[iid]
            if ins.get("status") != "active":
                probs.append(f"rests on {iid}, which was withdrawn ({ins.get('status')})")
                continue
            now = (ins.get("cites") or [None])[0]
            if now and (now["source_id"], now["segment_id"]) not in keys:
                probs.append(f"{iid} now rests on {now['source_id']} {now['revision']} {now['segment_id']}, which v{v.get('version')} does not cite")
            cur = canonical_time(ins.get("time"))
            nw, nc = _time_parts(ins.get("time"))
            if cur and (stated or iid in waits):
                w_rx, c_rx = _time_rx(cur)
                probs += [f"missing '{x}'" for x, rx in zip(cur.split(" ", 1), (w_rx, c_rx)) if not rx.search(content)]
            for o in self._earlier_times(ins):
                ow, oc = o.split(" ", 1)
                ow_rx, oc_rx = _time_rx(o)
                if oc != nc and oc_rx.search(content):
                    probs.append(f"still contains '{oc}' ({iid} was at {o})")
                if ow != nw and ow_rx.search(content):
                    probs.append(f"still contains '{ow}' ({iid} was at {o})")
            probs += self._condition_problems(content, iid)
            probs += self._action_problems(content, iid)
        # a sentence an instruction moved away from (superseded, rejected, an earlier state) that no active instruction rests on
        # any more is never cited: the version would rest on a sentence that states something else
        held = {(c["source_id"], c["segment_id"]) for ins in self.instructions.values() if ins.get("status") == "active" for c in ins.get("cites") or []}
        for c in v.get("cites", []):
            k = (c.get("source_id"), c.get("segment_id"))
            movers = [i for i, ins in sorted(self.instructions.items()) if ins.get("status") == "active" and k not in held
                      and k in {(e["source_id"], e["segment_id"]) for e in self._earlier_cites(ins)}]
            if movers:
                probs.append(f"cites {k[0]} {k[1]}, which {', '.join(movers)} no longer rests on")
        # the time of a withdrawn instruction (rejected and never approved by a clinician) whose sentence the version cites is
        # never stated, unless an instruction the version rests on is at that time: one sentence may ground two instructions,
        # and rejecting one of them must not leave its time in an approved text
        own = {canonical_time(self.instructions[i].get("time")) for i in self._active(ids)}
        for wid, w in sorted(self.instructions.items()):
            wt = canonical_time(w.get("time"))
            if w.get("status") == "active" or not wt or wt in own or not states_time(content, wt):
                continue
            if keys & {(c["source_id"], c["segment_id"]) for c in (w.get("cites") or []) + self._earlier_cites(w)}:
                probs.append(f"states {wt}, the time of {wid}, which was withdrawn ({w.get('status')})")
        probs += [f"still contains '{x}' (a transcript correction removed it)" for x in self._corrected_values(v, ids) if _mentions(content, x)]
        extra = facts(content) - self._grounded_facts(v, self._active(ids))
        if extra:
            probs.append(f"states facts no current source states: {sorted(extra)}")
        return list(dict.fromkeys(probs))

    def instruction_problems(self, iid: str) -> list[str]:
        """Why an active instruction does not fit its own source as it is now (empty: it fits): the numbers (dose, count)
        and negations of its action, the weekday and clock of its time set aside, are stated in the sentences it cites, on
        their latest revision. Applied at approval and export, like fit_problems for a version."""
        ins = self.instructions.get(iid) or {}
        if ins.get("status") != "active":
            return []
        core = _action_core(ins.get("action"), [ins.get("time")])
        seg = " ".join(t for t in (self.segment_text(c["source_id"], self._follow_latest(c)["revision"], c["segment_id"])
                                   for c in ins.get("cites") or []) if t)
        missing = sorted(_numeric_facts(core) - _numeric_facts(seg)) + sorted(_negations(core) - _negations(norm(seg)))
        return [f"its action {ins.get('action')!r} states {missing}, which the sentence it cites does not"] if missing else []

    def recompute_schedule(self, item: dict) -> dict | None:
        """Both bases of a task's schedule from the instruction time (or the task it is due with). Only tasks that
        carry a `schedule` are scheduled; the status needs_time_review marks a time nobody could read."""
        if item.get("kind") != "task" or item.get("schedule") is None:
            return None
        sch = dict(item["schedule"])
        anchor = sch.setdefault("anchor", "instruction_time")
        unreadable = False
        for basis, due_key, who_key in (("approved", "due_at", "assignee"), ("proposed", "proposed_due_at", "proposed_assignee")):
            if anchor == "fixed":
                due = sch.get("due_at")
            elif anchor == "recurring":
                due = None
            elif anchor == "due_with":
                other = self.items.get(sch.get("due_with"))
                due = ((other[-1].get("schedule") or {}).get(due_key)) if other else None
            else:
                timed = [self.instructions[i] for i in self.instructions_for_item(item)
                         if self.instructions[i].get("time") or (self.instructions[i].get("previous") or {}).get("time")]
                phrase = self._instruction_time(timed[0], basis) if timed else None
                due = due_at_from_phrase(phrase, self.week_anchor)
                unreadable = unreadable or bool(phrase and due is None)
            sch[due_key] = due
            sch[who_key] = assignee_for(self.rota, due) or sch.get("assignee_default", "on-duty caregiver")
        status = sch.get("status", "planned")
        if unreadable and status in ("planned", "needs_time_review"):
            status = "needs_time_review"
        elif not unreadable and status == "needs_time_review":
            status = "planned"
        sch["status"] = status
        sch["pending_move"] = sch.get("proposed_due_at") != sch.get("due_at")
        item["schedule"] = sch
        return sch

    def schedule(self) -> list[dict]:
        """One row per task; `confirmation` (only when there is one) is the on-behalf label of what puts the row's approved
        basis in force: the task's own approved version, the version in force under its pending one, or the timed
        instruction (or its in-force state) its due time comes from."""
        rows = []
        for iid, v in self.items.items():
            cur = v[-1]
            if cur.get("kind") != "task":
                continue
            sch = cur.get("schedule") or {}
            row = {"item_id": iid, "version": cur.get("version"), "review_status": cur.get("review_status"),
                   "origin": cur.get("origin", "instruction"), "content": cur["content"],
                   **{k: sch.get(k) for k in ("due_at", "assignee", "proposed_due_at", "proposed_assignee", "pending_move",
                                              "status", "anchor", "due_with")}}
            anchor = sch.get("anchor", "instruction_time")
            src = [iid] + ([i for i in self.instructions_for_item(cur) if self.instructions[i].get("time")] if anchor == "instruction_time" else []) \
                + ([sch["due_with"]] if anchor == "due_with" and sch.get("due_with") in self.items else [])
            label = next((x for i in src for x in (self.confirmation_label(i), self.in_force_label(i)) if x), None)
            if label:
                row["confirmation"] = label
            rows.append(row)
        return sorted(rows, key=lambda r: (r.get("due_at") or r.get("proposed_due_at") or "9999", r["item_id"]))

    def _schedules_now(self) -> dict[str, dict]:
        return {iid: dict(v[-1]["schedule"]) for iid, v in self.items.items()
                if v[-1].get("kind") == "task" and v[-1].get("schedule") is not None}

    def _recompute_all_schedules(self, ev: dict, before: dict[str, dict]) -> None:
        """Derived state after a change: every task's two bases, followers (due_with) after the tasks they follow.
        Each move is written to the event's schedule_diff with its basis, so the UI shows 'Thu 11:00 -> Wed 16:00
        (pending review)' without the approved column moving before a review."""
        tasks = [(iid, v[-1]) for iid, v in sorted(self.items.items())
                 if v[-1].get("kind") == "task" and v[-1].get("schedule") is not None]
        for iid, cur in sorted(tasks, key=lambda t: (t[1]["schedule"].get("anchor") == "due_with", t[0])):
            self.recompute_schedule(cur)
        new_ids = {n["item_id"] for n in ev["new_items"]}
        versioned = {n["item_id"] for n in ev["new_versions"]}
        for iid, cur in tasks:
            if iid in new_ids:
                continue
            b, a = before.get(iid, {}), cur["schedule"]
            for basis, due_key, who_key in (("approved", "due_at", "assignee"), ("proposed", "proposed_due_at", "proposed_assignee")):
                keys = (due_key, who_key) + (("status",) if basis == "approved" else ())
                if all(b.get(k) == a.get(k) for k in keys):
                    continue
                row = {"item_id": iid, "basis": basis, "due_at_from": b.get(due_key), "due_at_to": a.get(due_key),
                       "assignee_from": b.get(who_key), "assignee_to": a.get(who_key), "content_changed": iid in versioned,
                       "reason": self._move_reason(iid, cur, ev)}
                if basis == "approved" and b.get("status") != a.get("status"):
                    row["status_from"], row["status_to"] = b.get("status"), a.get("status")
                ev["schedule_diff"].append(row)

    def _move_reason(self, iid: str, cur: dict, ev: dict) -> str:
        sch = cur["schedule"]
        if sch.get("anchor") == "due_with":
            return f"follows {sch['due_with']}"
        if ev["kind"] == "review":
            if ev["reviewed"]["decision"] == "confirm_on_behalf":
                return f"{ON_BEHALF_LABEL}: the proposed time is now in force (labelled until the clinician confirms or rejects it)"
            if ev["reviewed"].get("on_behalf_rejected"):
                return "rejected by the clinician after an on-behalf confirmation: the last approved time is back in force"
            return "approved: the proposed time is now in force" if ev["reviewed"]["decision"] == "approve" else "rejected: the approved time stays in force"
        for ic in ev["instruction_changes"]:
            if ic["instruction_id"] in self.instructions_for_item(cur):
                src = ev.get("source_added") or {}
                by = f"{src.get('transcript') or src.get('source_id')} {src.get('revision')}" if src else "a transcript correction"
                return f"{ic['instruction_id']} time changed by {by} (pending review)"
        return cur.get("reason") or "schedule recomputed"

    # ---------------------------------------------------------------- the one door: apply_change
    def apply_change(self, change: dict, actor: str, role: str | None = None) -> dict:
        """Idempotent, validated, all-or-nothing. Returns the change_event (a deep copy)."""
        if not isinstance(change, dict) or not isinstance(change.get("kind"), str):
            raise ValueError("a change is an object with a string 'kind'")
        handler = getattr(self, f"_change_{change['kind']}", None)
        if handler is None:
            raise ValueError(f"unknown change kind '{change['kind']}'")
        if not isinstance(actor, str) or not LABEL_RX.match(actor):
            raise ValueError("'actor' must be a short single-line label (letters, digits, space, _ @ ( ) -; at most 64 characters)")
        if change.get("at") is not None:   # every change's time is a naive local minute: compared as a datetime, never a string
            _local_iso(change["at"], f"a change's 'at' ({change['kind']})")
        rid, h = change.get("request_id"), payload_hash(change)
        if rid is not None:
            prev = self.requests.get(rid)
            if prev is not None:
                if prev["payload_hash"] != h:
                    raise ConflictError("request_id reused with a different payload")
                return self._replay(prev["change_id"], "request_id")
        sha = (change.get("source") or {}).get("content_sha256") if isinstance(change.get("source"), dict) else None
        proposals = payload_hash({"instructions": change.get("instructions") or []})
        if sha and sha in self.uploads_by_sha:
            first = next(e for e in self.change_events if e["change_id"] == self.uploads_by_sha[sha])
            if (change.get("instructions") or []) and proposals != first.get("proposals_hash"):
                # the recording is already in the case; different proposals must not vanish into a silent replay
                raise ConflictError(f"this recording is already in the case as {first['source_added']['source_id']} ({first['change_id']}); a "
                                    "duplicate upload cannot carry different proposals, so nothing was applied. Retry the original "
                                    "upload unchanged to replay it")
            return self._replay(self.uploads_by_sha[sha], "content_sha256")
        role = role or self.roles.get(actor) or "caregiver"
        snap = self.snapshot()
        try:
            ev = {"change_id": f"chg-{len(self.change_events) + 1:03d}", "seq": None, "kind": change["kind"], "request_id": rid,
                  "payload_hash": h, "proposals_hash": proposals, "actor": actor, "role": role, "at": change.get("at"),
                  "case_version_before": self.case_version, "case_version_after": self.case_version, "status": "received",
                  "impact_set": [], "new_versions": [], "new_items": [], "instruction_changes": [], "schedule_diff": [],
                  "pending_changes": [], "not_applied": [], "needs_person": []}
            before = self._schedules_now()
            # the time this change counts from for the on-behalf time limit: its `at`, never earlier than the latest `at`
            # already accepted (a backdated `at` cannot make it look older); no `at`, no time (the limit cannot be checked)
            at = change.get("at")
            ev["effective_at"] = (max(at, self.clock_high, key=_dt) if self.clock_high else at) if at else None
            handler(change, ev)
            if at and ev["status"] != "refused":
                self.clock_high = ev["effective_at"]
            if role == CLINICIAN_ROLE and self.clinician_unreachable and ev["status"] != "refused":
                # the clinician acted, so the clinician is reachable again: the mark goes (kept on the event)
                ev["clinician_unreachable_cleared"] = {**self.clinician_unreachable, "cleared_by": actor, "cleared_at": change.get("at")}
                self.clinician_unreachable = None
            self._recompute_all_schedules(ev, before)
            self._publish(ev, sha)
        except Exception:
            self.restore(snap)
            raise
        return copy.deepcopy(ev)

    def _replay(self, change_id: str, matched_by: str) -> dict:
        ev = next(e for e in self.change_events if e["change_id"] == change_id)
        return {**copy.deepcopy(ev), "replayed": True, "matched_by": matched_by}

    def _publish(self, ev: dict, sha: str | None) -> None:
        """Mark -> new versions -> publish: case_version bumps exactly once and only when content changed; seq counts
        every accepted event; untouched items are hashed so the diff can prove what did not move."""
        if ev["status"] == "refused":
            ev["seq"] = None
        else:
            content_changed = bool(ev["new_versions"] or ev["new_items"]
                                   or any(ic.get("content_changed", True) for ic in ev["instruction_changes"]))
            if ev["kind"] == "review":
                ev["status"] = "review"
            elif content_changed:
                self.bump_case_version()
                ev["status"] = "published"
            else:
                ev["status"] = "recorded_no_change"
            ev["case_version_after"] = self.case_version
            self.seq += 1
            ev["seq"] = self.seq
        ev["awaiting_review"] = self.pending_review_count()
        ev["untouched_hashes"] = self._untouched_hashes(ev)
        ev["impact_set"] = sorted(ev["impact_set"])
        ev["notice"] = self._notice(ev)
        if ev["kind"] == "event_confirmation":   # the one notice built from free client strings: never a relaxing sentence
            viol = check_item_content(ev["notice"], forbid_relaxing=True)
            if viol:
                raise ValueError("event notice rejected: " + "; ".join(viol))
        self.change_events.append(ev)
        if ev.get("request_id") is not None:
            self.requests[ev["request_id"]] = {"change_id": ev["change_id"], "payload_hash": ev["payload_hash"]}
        if sha and ev["status"] != "refused":
            self.uploads_by_sha[sha] = ev["change_id"]
        self.audit.append({"op": "change_event", "change_id": ev["change_id"], "kind": ev["kind"], "status": ev["status"], "seq": ev["seq"]})

    def _untouched_hashes(self, ev: dict) -> dict[str, str]:
        touched = set(ev["impact_set"]) | {n["item_id"] for n in ev["new_items"]} | {n["item_id"] for n in ev["new_versions"]}
        touched |= {ic["instruction_id"] for ic in ev["instruction_changes"]} | {n["item_id"] for n in ev["needs_person"]}
        touched |= set((ev.get("reviewed") or {}).get("approved", [])) | set((ev.get("reviewed") or {}).get("rejected", []))
        touched |= set((ev.get("reviewed") or {}).get("clinician_confirmed", []))
        h = {iid: unchanged_hash(v[-1]) for iid, v in self.items.items() if iid not in touched}
        h.update({iid: unchanged_hash(ins) for iid, ins in self.instructions.items() if iid not in touched})
        return h

    # ---------------------------------------------------------------- impact + versions (shared by all kinds)
    def items_citing(self, source_id: str, segment_ids: set[str] | None = None) -> list[str]:
        """Latest version of every non-PDF, non-superseded item that cites the source (optionally: these segments)."""
        out = []
        for iid, versions in self.items.items():
            cur = versions[-1]
            if cur.get("kind") == "exported_pdf" or cur.get("review_status") in ("superseded", "rejected"):
                continue
            if any(c["source_id"] == source_id and (segment_ids is None or c["segment_id"] in segment_ids) for c in cur.get("cites", [])):
                out.append(iid)
        return sorted(out)

    @staticmethod
    def _retire(v: dict, status: str) -> None:
        """A version leaves 'approved' (to stale or superseded): remember that a person once approved it, so only such
        a version can ever be restored by a rejection. A rejected version keeps its status (and its reject_reason)."""
        if v.get("review_status") == "approved":
            v["approved_before"] = True
        if v.get("review_status") != "rejected":
            v["review_status"] = status

    @staticmethod
    def was_approved(v: dict) -> bool:
        return v.get("review_status") == "approved" or v.get("approved_before") is True

    def last_approved(self, item_id: str, before: int | None = None) -> dict | None:
        """The newest earlier version of an item that a person really approved (never a pending version that was merely
        superseded before review); None when no version was ever approved. `before`: only versions numbered below it."""
        return next((v for v in reversed(self.items[item_id][:-1]) if self.was_approved(v)
                     and (before is None or (v.get("version") or 0) < before)), None)

    def _mark_stale(self, ids: list[str], ev: dict) -> None:
        for iid in ids:
            self._retire(self.latest(iid), "stale")
        ev["impact_set"] = sorted(set(ev["impact_set"]) | set(ids))

    def _new_version(self, item_id: str, content: str, cites: list[dict], reason: str, ev: dict, method: str = "fallback",
                     schedule_patch: dict | None = None, derived_from: list[str] | None = None) -> dict:
        old = self.latest(item_id)
        v = self.propose_version(item_id, content, cites, reason=reason)
        if old.get("review_status") != "superseded":
            self._retire(old, "superseded")
            old["superseded_by"] = v["version"]
        for k in ("schedule", "origin", "derived_from"):
            if k in old:
                v[k] = copy.deepcopy(old[k])
        if derived_from:
            v["derived_from"] = list(derived_from)
        if schedule_patch:
            v["schedule"] = {**(v.get("schedule") or {}), **schedule_patch}
        v["method"], v["change_id"] = method, ev["change_id"]   # which change produced this version (a rejection withdraws them)
        self.recompute_schedule(v)
        ev["new_versions"].append({"item_id": item_id, "version": v["version"], "method": method, "content": content})
        return v

    def _new_item(self, item_id: str, kind: str, content: str, cites: list[dict], ev: dict, origin: str = "instruction",
                  derived_from: list[str] | None = None, schedule: dict | None = None) -> dict:
        """A new item whose id is derived from its source. If the id already exists the item gets a new version
        instead: history is never overwritten."""
        if item_id in self.items:
            return self._new_version(item_id, content, cites, f"created again by {ev['change_id']} ({ev['kind']})", ev,
                                     schedule_patch=schedule, derived_from=derived_from)
        it = {"item_id": item_id, "kind": kind, "version": 1, "review_status": "pending_review", "content": content, "cites": cites,
              "origin": origin, "reason": f"created by {ev['change_id']} ({ev['kind']})", "created_by": ev["change_id"], "change_id": ev["change_id"]}
        if derived_from:
            it["derived_from"] = list(derived_from)
        if kind == "task":
            it["schedule"] = {"status": "planned", **(schedule or {})}
        self.items[item_id] = [it]
        self.recompute_schedule(it)
        self.audit.append({"op": "new_item", "item_id": item_id, "change_id": ev["change_id"]})
        ev["new_items"].append({"item_id": item_id, "version": 1, "content": content, "origin": origin, "schedule": it.get("schedule")})
        return it

    @staticmethod
    def text_problems(cand: str, old: str, must_contain: list[str], must_not_contain: list[str], allowed_facts=(),
                      keep_facts: bool = True, keep_within=None) -> list[str]:
        """Why a rewritten or delivered text may not replace `old`: a required token is missing, a forbidden one (the
        superseded clock or weekday, a corrected value) is present, it relaxes an instruction (A-P2 patterns), it
        states a time, number or weekday that neither the old text nor the change grounds (`allowed_facts`), or
        (`keep_facts`) it drops or changes one the old text stated other than those the change removes on purpose (the
        facts of `must_not_contain`, a clock also as its bare hour). Numbers written as words count as numbers
        (guardrails.facts: 'two' == '2'). `keep_within` (a set of facts) limits the kept facts to those still in it: a
        text a person or a late job delivers keeps the item's facts its current sources still state, so a fact the
        change removed (an old condition's '3 glasses', an earlier time the engine could not read) may go while a dose
        the source still states may not. A restored version is checked with keep_facts=False: going back to it drops
        what the rejected version said on purpose."""
        v = check_item_content(cand, must_contain, must_not_contain, forbid_relaxing=True)
        extra = added_facts(old, cand, allowed_facts)
        if extra:
            v.append(f"adds facts the item did not state: {sorted(extra)}")
        if keep_facts:
            dropped = set()
            for m in must_not_contain:
                f = facts(m)
                dropped |= f | {x.split(":")[0] for x in f}
            have = facts(cand)
            have |= {x.split(":")[0] for x in have if ":" in x}   # '11:00' also states the hour an 'eleven o'clock' stated
            lost = facts(old) - have - dropped
            if keep_within is not None:
                lost &= set(keep_within)
            if lost:
                v.append(f"drops or changes facts the item stated: {sorted(lost)}")
        return v

    def _regenerate_text(self, item: dict, seg_before: str, seg_after: str, keep: list[str], fallback: str,
                         must_contain: list[str], must_not_contain: list[str], correction: dict | None = None,
                         fits=None) -> tuple[str | None, str]:
        """The optional LLM rewrite first (checked), else the deterministic substitution (checked). None = a person
        must rewrite the item (it stays stale). `correction` ({from, to, kind}) tells the rewriter what changed; its
        `to` value is the only new fact a rewrite may introduce. `fits(content) -> problems` is the fit check of the
        version the text would become (fit_problems); a text that fails it is never used."""
        allowed = facts(correction["to"]) if correction else set()
        fits = fits or (lambda content: [])
        fb_method = "fallback"
        if self.rewriter is not None:
            cand, method = self.rewriter(item, seg_before, seg_after, keep, correction=correction)
            if cand and not self.text_problems(cand, item["content"], must_contain, must_not_contain, allowed) and not fits(cand):
                return cand, method
            if method == "fallback_unavailable":   # the model gave no reply at all (eval --fail-soft), not a rejected one
                fb_method = method
        if self.text_problems(fallback, item["content"], must_contain, must_not_contain, allowed) or fits(fallback):
            return None, "needs_person"
        return fallback, fb_method

    @staticmethod
    def _keep_words(content: str) -> list[str]:
        return [w for w in ("medication list",) if w in content.lower()]

    # ---------------------------------------------------------------- sources
    def _add_source(self, src: dict, ev: dict) -> tuple[str, str]:
        """Store a clinical source; a recording is stored as recording + '<id>-tx' transcript (what items cite)."""
        sid, rev = src["source_id"], src.get("revision", "r1")
        if not isinstance(rev, str) or not REVISION_RX.match(rev):
            raise ValueError(f"a source revision is 'r1', 'r2', ... (got {rev!r})")
        if self.latest_revision(sid) is not None:
            raise ValueError(f"source {sid} already exists (retry the same upload with its request_id)")
        if not all(isinstance(g, dict) and isinstance(g.get("segment_id"), str) and isinstance(g.get("text"), str) for g in src["segments"]):
            raise ValueError("each segment is an object with a string 'segment_id' and 'text'")
        segs = {g["segment_id"]: dict(g) for g in src["segments"]}
        base = {k: v for k, v in src.items() if k != "segments"}
        if src["source_type"] == "clinician_recording":
            self.sources[(sid, rev)] = {**base, "revision": rev, "authoritative": True, "segments": segs}
            tx = f"{sid}-tx"
            self.sources[(tx, rev)] = {**base, "source_id": tx, "revision": rev, "source_type": "transcript", "transcribes": sid,
                                       "review_status": src.get("review_status", "unverified"), "segments": copy.deepcopy(segs)}
        else:
            tx = sid
            self.sources[(sid, rev)] = {**base, "revision": rev, "segments": segs}
        ev["source_added"] = {"source_id": sid, "transcript": tx, "revision": rev, "source_type": src["source_type"],
                              "recorded_at": src.get("recorded_at"), "uploaded_at": src.get("uploaded_at"),
                              "content_sha256": src.get("content_sha256")}
        self.audit.append({"op": "add_source", "source_id": sid, "revision": rev, "change_id": ev["change_id"]})
        return tx, rev

    def _source_recorded_at(self, source_id: str, revision: str) -> str:
        return self.sources.get((source_id, revision), {}).get("recorded_at") or ""

    def _current_source(self, ins: dict) -> dict:
        """The cite whose recording decides precedence for an instruction: the source it cites, or a later recording
        that re-confirmed the same time (reaffirmed_by with that time). An older recording that arrives later than
        either is history (engineering case 5)."""
        best = ins["cites"][0]
        for c in ins.get("reaffirmed_by") or []:
            if c.get("time") == ins.get("time") and (_dt(c.get("recorded_at")) or dt.datetime.min) > \
                    (_dt(self._source_recorded_at(best["source_id"], best["revision"])) or dt.datetime.min):
                best = c
        return {k: best[k] for k in ("source_id", "revision", "segment_id")}

    def _verified_segment(self, tx: str, rev: str, seg: str, quote: str) -> dict:
        """The cited segment, if the proposal quotes it and a person verified it. A transcript segment needs its own
        tick (verified_by); only a clinician's own written text may rest on the source-level review_status approved."""
        src = self.sources[(tx, rev)]
        g = src["segments"].get(seg)
        if g is None:
            raise ValueError(f"unknown segment_id {seg} in {tx} {rev}")
        key = _text_key(quote)   # whitespace runs, line breaks and curly quotes do not refuse a verbatim quote
        if not key or key not in _text_key(g.get("text")):   # an empty key (a quote of punctuation only) is in every text
            raise ValueError(f"proposal quote {(quote or '')[:80]!r} not in {tx} {rev} {seg}")
        text_approved = src.get("source_type") == "clinician_instruction_text" and src.get("review_status") == "approved"
        if not g.get("verified_by") and not text_approved:
            raise ValueError(f"{tx} {rev} {seg} is not verified against the recording: a person ticks it first")
        return g

    def _condition_change(self, old: dict, p: dict, seg_text: str, where: str) -> tuple[str | None, str] | None:
        """(condition_from, condition_to) when a superseding proposal changes the instruction's condition. The new
        condition must be grounded in the cited verified sentence (condition_coverage) and may not read as a relaxation
        (forbid_relaxing, applied to the raw text: fail-closed); an empty condition, or one that differs from the
        current one only in case, whitespace or outer punctuation, keeps the old one. Refused, never silently applied."""
        new = (p.get("condition") or "").strip() or None
        if new is None or _text_key(new) == _text_key(old.get("condition")):
            return None
        if condition_coverage(seg_text, new) < CONDITION_MIN_COVERAGE:
            raise ValueError(f"condition {new!r} is not stated in {where}: an instruction's condition changes only on the clinician's own sentence")
        if check_item_content(new, forbid_relaxing=True):
            raise ValueError(f"condition {new!r} may relax the instruction (it matches a relaxing pattern): a change that reads as a "
                             "relaxation is not applied through a proposal; state the condition positively (e.g. 'only with help from "
                             "the caregiver') or a person enters it")
        return old.get("condition"), new

    @staticmethod
    def _action_change(old: dict, p: dict, seg_text: str, times, where: str) -> tuple[str, str] | None:
        """(action_from, action_to) when a superseding proposal states another number (dose, count) or negation in the action
        than the instruction (_action_key, with the weekday and clock of both times set aside). The new action's numbers and
        negations must be stated in the cited verified sentence; refused, never silently applied."""
        new = " ".join(p["action"].split())
        if _action_key(new, times) == _action_key(old["action"], times):
            return None
        core, seg = _action_core(new, times), norm(seg_text)
        missing = sorted(_numeric_facts(core) - _numeric_facts(seg)) + sorted(_negations(core) - _negations(seg))
        if missing:
            raise ValueError(f"the changed action {new!r} states {missing}, which {where} does not: an instruction's action changes only "
                             "on the clinician's own sentence")
        return old["action"], new

    def suggest_supersedes(self, action: str) -> tuple[str | None, float]:
        """The active instruction a proposal most likely replaces (shown pre-ticked in the UI; a person decides)."""
        best = min(((-action_overlap(action, ins["action"]), iid) for iid, ins in self.instructions.items()
                    if ins.get("status") == "active"), default=None)   # ties: the lowest instruction id
        if best and -best[0] >= SUPERSEDES_MIN_OVERLAP:
            return best[1], round(-best[0], 3)
        return None, round(-best[0], 3) if best else 0.0

    def _resolve_target(self, p: dict) -> tuple[str | None, float | None]:
        """Which instruction a proposal replaces: the one a person ticked (validated by stem overlap), else an exact
        action match, else none (a new instruction). Fuzzy matching never decides."""
        target = p.get("supersedes")
        if target:
            if target not in self.instructions:
                raise NotInCase(f"supersedes names an instruction not in this case: {target}")
            if self.instructions[target].get("status") != "active":
                raise ValueError(f"supersedes names {target}, which was withdrawn ({self.instructions[target].get('status')}): a proposal "
                                 "cannot bring a withdrawn instruction back; leave supersedes empty to propose a new instruction")
            ov = round(action_overlap(p["action"], self.instructions[target]["action"]), 3)
            if ov < SUPERSEDES_MIN_OVERLAP:
                raise ValueError(f"supersedes {target}: action overlap {ov} is below {SUPERSEDES_MIN_OVERLAP}")
            return target, ov
        exact = next((i for i, ins in self.instructions.items() if ins.get("status") == "active"
                      and ins["action"].strip().lower() == p["action"].strip().lower()), None)
        return exact, (1.0 if exact else None)

    def _new_ids(self, sid: str) -> tuple[str, str]:
        pfx = sid.split("-")[1] if sid.count("-") >= 2 else sid
        n = 1
        while f"ins-{pfx}-{n:03d}" in self.instructions:
            n += 1
        m = 1
        while f"task-{pfx}-{m:02d}" in self.items:
            m += 1
        return f"ins-{pfx}-{n:03d}", f"task-{pfx}-{m:02d}"

    def _timed_task(self) -> str | None:
        return next((i for i, v in sorted(self.items.items()) if v[-1].get("kind") == "task"
                     and (v[-1].get("schedule") or {}).get("proposed_due_at")), None)

    def _task_of(self, instruction_id: str) -> str | None:
        return next((i for i, v in sorted(self.items.items()) if v[-1].get("kind") == "task"
                     and v[-1].get("review_status") != "superseded" and instruction_id in self.instructions_for_item(v[-1])), None)

    # ---------------------------------------------------------------- kind: new_clinician_source / late_upload
    def _change_new_clinician_source(self, change: dict, ev: dict) -> None:
        src = change.get("source")
        if not isinstance(src, dict) or not isinstance(src.get("source_id"), str) or not isinstance(src.get("segments"), list):
            raise ValueError("a clinical source needs 'source_id' and a list of 'segments'")
        if src.get("source_type") not in CLINICAL_SOURCE_TYPES:
            raise ValueError("only a clinical source can change an instruction")
        _local_iso(src.get("recorded_at"), "a clinical source's 'recorded_at' (it decides precedence, uploaded_at never does)")
        tx, rev = self._add_source(src, ev)
        superseded_here: list[str] = []
        for p in change.get("instructions") or []:   # proposals: fixture (person-checked) or the LLM extractor, both grounded
            if not isinstance(p, dict) or not isinstance(p.get("action"), str) or not p["action"].strip():
                raise ValueError("each proposal needs a non-empty 'action'")
            if not all(isinstance(p.get(k, ""), str) for k in ("segment_id", "quote", "time", "condition", "supersedes")):
                raise ValueError("a proposal's 'segment_id', 'quote', 'time', 'condition' and 'supersedes' are strings")
            g = self._verified_segment(tx, rev, p.get("segment_id", ""), p.get("quote", ""))
            cite = {"source_id": tx, "revision": rev, "segment_id": p["segment_id"]}
            raw_time = (p.get("time") or "").strip()
            new_time = canonical_time(raw_time) if raw_time else None
            if raw_time and new_time is None:   # a time nobody can read: kept verbatim, flagged, never guessed
                new_time = raw_time
                q = self.add_pending("needs_transcript_check", f"The time \"{raw_time}\" in {tx} {rev} ({p['segment_id']}) could not be read as "
                                     "'<Weekday> h:mm a.m./p.m.'. A person checks the recording and enters the time.", [cite])
                q.setdefault("opened_by", ev["change_id"])
                ev["pending_changes"].append({"pending_id": q["pending_id"], "type": q["type"], "status": "open"})
            old_id, overlap = self._resolve_target(p)
            if old_id is None:
                self._add_instruction(p, new_time, cite, src, ev, superseded_here)
                continue
            old = self.instructions[old_id]
            cur_src = self._current_source(old)
            if (_dt(self._source_recorded_at(cur_src["source_id"], cur_src["revision"])) or dt.datetime.min) > _dt(src["recorded_at"]):
                # recorded earlier than the source of the current instruction: history only (engineering case 5)
                for key in ((src["source_id"], rev), (tx, rev)):
                    self.sources[key]["superseded_on_arrival_by"] = cur_src["source_id"]
                ev["not_applied"].append({"instruction_id": old_id, "reason": "recorded earlier than the source of the current instruction",
                                          "recorded_at": src["recorded_at"],
                                          "current_source": {"source_id": cur_src["source_id"], "revision": cur_src["revision"],
                                                             "recorded_at": self._source_recorded_at(cur_src["source_id"], cur_src["revision"])}})
                continue
            # the action is kept unless the proposal states another number or negation in it (the weekday and clock of either
            # time and month names set aside: 'attend follow-up appointment on Wednesday' at Wednesday 4:00 p.m. is a move): a
            # changed dose, count or negation is applied as a pending change of the action that a person reviews (every item
            # resting on it is left for a person's rewrite, a question is opened, a rejection restores the old action), never
            # recorded as a confirmation; it must be stated in the cited verified sentence
            times = [new_time, old.get("time")]
            act_change = self._action_change(old, p, g.get("text") or "", times, f"{tx} {rev} {p['segment_id']}")
            cond_change = self._condition_change(old, p, g.get("text") or "", f"{tx} {rev} {p['segment_id']}")
            keep_time = new_time is None or new_time == old.get("time")
            if keep_time and cond_change is None and act_change is None and _stems(_action_core(p["action"], times)) != _stems(_action_core(old["action"], times)):
                raise ValueError(f"supersedes {old_id}: the proposal changes neither the time, the condition nor a number or negation of the "
                                 f"action, but words the action differently ({p['action']!r} for {old['action']!r}); it is not recorded as a "
                                 "confirmation. Propose the action as the instruction states it")
            if keep_time and cond_change is None and act_change is None:
                reaff = {**cite, "recorded_at": src["recorded_at"], "time": new_time}
                old.setdefault("reaffirmed_by", []).append(reaff)
                if new_time is None and old.get("time"):
                    # the source names the instruction but gives no time: keep the time, ask instead of guessing
                    q = self.add_pending("needs_clinical_confirmation", f"{tx} {rev} ({p['segment_id']}) mentions '{old['action']}' but gives no "
                                         f"time. Has the time ({old['time']}) changed?", [cite])
                    q.setdefault("opened_by", ev["change_id"])
                    ev["pending_changes"].append({"pending_id": q["pending_id"], "type": q["type"], "status": "open"})
                    ev["instruction_changes"].append({"instruction_id": old_id, "change": "reaffirmed_no_time", "time": old["time"],
                                                      "supersedes_overlap": overlap, "content_changed": False})
                    continue
                # the same time (or no time at all) and no new condition: nothing changed; the newer recording confirms the
                # arrangement (it now decides precedence) and settles an open conflict, but no item or instruction moves
                ev["instruction_changes"].append({"instruction_id": old_id, "change": "reaffirmed_same_time", "time": old.get("time"),
                                                  "supersedes_overlap": overlap, "content_changed": False})
                self._resolve_conflicts(old_id, ev)
                continue
            self._supersede_instruction(old_id, p, old["time"] if keep_time else new_time, cite, src, tx, rev, overlap, ev, cond_change, act_change)
            superseded_here.append(old_id)

    _change_late_upload = _change_new_clinician_source   # same door; recorded_at decides, uploaded_at never does

    def _resolve_conflicts(self, instruction_id: str, ev: dict) -> None:
        """A clinical source settles an open family-statement conflict about this instruction."""
        for q in self.pending:
            if q["status"] == "open" and q["type"] == "conflict" and q.get("about_instruction") == instruction_id:
                q["status"], q["resolved_by"] = "resolved", ev["change_id"]
                ev["pending_changes"].append({"pending_id": q["pending_id"], "type": "conflict", "status": "resolved"})

    def _add_instruction(self, p: dict, new_time: str | None, cite: dict, src: dict, ev: dict, superseded_here: list[str]) -> None:
        new_id, tid = self._new_ids(src["source_id"])
        self.instructions[new_id] = {"instruction_id": new_id, "action": p["action"].strip(), "condition": (p.get("condition") or "").strip() or None,
                                     "time": new_time, "cites": [cite], "status": "active", "derivation_status": "pending_review",
                                     "recorded_at": src.get("recorded_at"), "last_change": {"kind": ev["kind"], "change_id": ev["change_id"]}}
        ev["instruction_changes"].append({"instruction_id": new_id, "change": "new", "time": new_time, "content_changed": True})
        ins = self.instructions[new_id]
        content = ins["action"][:1].upper() + ins["action"][1:] + (f" ({ins['condition']})" if ins["condition"] else "")
        if canonical_time(new_time) and _states_clock_or_weekday(ins["action"]) and not states_time(content, new_time):
            # the action names a weekday or a clock: the template states the instruction's whole time, which a text that
            # states a time must (fit_problems), so the engine's own template is never refused at approve
            content += f" ({canonical_time(new_time)})"
        # a template task: at the instruction's own time, else due with the task of the instruction this same source
        # replaced (e.g. 'bring the diary' goes with the appointment), else with the case's timed task
        if new_time:
            schedule = {"anchor": "instruction_time"}
        else:
            follow = next((self._task_of(i) for i in superseded_here if self._task_of(i)), None) or self._timed_task()
            schedule = {"anchor": "due_with", "due_with": follow} if follow else {"anchor": "instruction_time"}
        self._new_item(tid, "task", content, [cite], ev, origin="instruction", derived_from=[new_id], schedule=schedule)

    def _supersede_instruction(self, old_id: str, p: dict, new_time: str | None, cite: dict, src: dict, tx: str, rev: str,
                               overlap: float | None, ev: dict, cond_change: tuple | None = None, act_change: tuple | None = None) -> None:
        old = self.instructions[old_id]
        old_src, old_time = old["cites"][0], old.get("time")
        labels = self._pop_labels(old)   # an on-behalf label belongs to the approved state, never to the pending one
        if old.get("derivation_status") != "pending_review" or not old.get("previous"):
            # `previous` is the last APPROVED state: a second change before any review replaces the pending one. A new
            # instruction nobody approved yet gets one too (the schedule's approved basis), marked was_approved False, so a
            # rejection withdraws it instead of presenting its unapproved state as approved. A state approved only on the
            # clinician's behalf keeps the clinician's own last approved state under it (`clinician_previous`): a clinician's
            # rejections step back through the on-behalf state to it, never withdraw an instruction a clinician approved
            basis = self._clinician_basis(old.get("previous")) if self._on_behalf_only(labels) else None
            old["previous"] = {**{k: copy.deepcopy(old.get(k)) for k in ("time", "condition", "action", "cites")},
                               "was_approved": old.get("derivation_status") not in ("pending_review", "rejected"), **labels,
                               **({"clinician_previous": basis} if basis else {})}
        # every state it moves away from (time, condition, cites): no replacement text restates an earlier time, a
        # rewrite after a restore finds the cite to replace, and a condition a change introduced stays required
        old.setdefault("history", []).append({"time": old_time, "condition": old.get("condition"), "action": old.get("action"),
                                               "cites": copy.deepcopy(old["cites"]), "to_time": new_time,
                                               "to_condition": cond_change[1] if cond_change else old.get("condition"),
                                               "to_action": act_change[1] if act_change else old.get("action"), "change_id": ev["change_id"]})
        old["time"], old["cites"], old["derivation_status"] = new_time, [cite], "pending_review"
        if cond_change is not None:
            old["condition"] = cond_change[1]
        if act_change is not None:
            old["action"] = act_change[1]
            q = self.add_pending("needs_clinical_confirmation", f"{tx} {rev} ({cite['segment_id']}) changes the dose, count or negation of {old_id}: "
                                 f"'{act_change[0]}' is now '{act_change[1]}'. Every item resting on it waits for a person's rewrite; does the "
                                 "care team confirm the changed action?", [cite])
            q.setdefault("opened_by", ev["change_id"])
            ev["pending_changes"].append({"pending_id": q["pending_id"], "type": q["type"], "status": "open"})
        old["superseded_source"] = old_src
        old["last_change"] = {"kind": ev["kind"], "change_id": ev["change_id"]}
        self.audit.append({"op": "supersede_instruction", "instruction_id": old_id, "change_id": ev["change_id"]})
        ic = {"instruction_id": old_id, "change": "superseded_by_new_source", "time_from": old_time, "time_to": new_time, "cites": [cite],
              "supersedes_overlap": overlap, "content_changed": True}
        if cond_change is not None:
            ic["condition_from"], ic["condition_to"] = cond_change
        if act_change is not None:
            ic["action_from"], ic["action_to"] = act_change
        ev["instruction_changes"].append(ic)
        self._resolve_conflicts(old_id, ev)
        impact = self.items_citing(old_src["source_id"], {old_src["segment_id"]})
        # items left for a person's rewrite by an earlier change of this instruction still cite the segment it moved away
        # from, so the segment does not find them: they are reached through `rewrite_for` and their own text's time
        waiting = [i for i, v in sorted(self.items.items()) if i not in impact and v[-1].get("review_status") == "stale"
                   and old_id in (v[-1].get("rewrite_for") or {})]
        self._mark_stale(impact + waiting, ev)
        seg_after = self.segment_text(tx, rev, p["segment_id"]) or ""
        # the instruction's other known times: its last approved one and a rejected proposal (with the new one, the
        # candidates for the time an item's text states when the earlier time could not be read)
        known = [(old.get("previous") or {}).get("time"), (old.get("rejected_change") or {}).get("time"), new_time]
        for iid in impact + waiting:
            cur = self.latest(iid)
            waits = cur.get("rewrite_for") or {}
            mine = waits.get(old_id) or {}
            from_time = mine["from_time"] if "from_time" in mine else old_time   # the time the item's text states
            if not canonical_time(from_time):
                # an earlier time nobody could read ('Wed 4 p.m.'): an item a person rewrote states a time of its own;
                # when that is one of the instruction's known times, it is the time to move from (or already the new one)
                from_time = next((t for t in known if states_time(cur["content"], t)), from_time)
            from_cite = mine.get("from_cite") or old_src
            cond_to = cond_change[1] if cond_change is not None else mine.get("condition_to")
            cond_waits = bool(cond_to) and _text_key(cond_to) == _text_key(old.get("condition"))
            act_to = act_change[1] if act_change is not None else mine.get("action_to")
            act_waits = bool(act_to) and _text_key(act_to) == _text_key(old.get("action"))

            def leave(why: list[str], cur=cur, iid=iid, from_time=from_time, from_cite=from_cite, cond_to=cond_to, cond_waits=cond_waits,
                      act_to=act_to, act_waits=act_waits) -> None:
                # stays stale for a person; remember what it waits for, so a delivered rewrite is judged against this
                # instruction (its current time, condition, action and cite) and a later readable time can still reach it
                entry = {"from_time": canonical_time(from_time) or from_time, "from_cite": dict(from_cite),
                         "to_time": new_time, "to_cite": dict(cite), "change_id": ev["change_id"]}
                if cond_waits:
                    entry["condition_to"] = cond_to
                if act_waits:
                    entry["action_to"] = act_to
                cur.setdefault("rewrite_for", {})[old_id] = entry
                ev["needs_person"].append({"item_id": iid, "why": why})
            other = sorted(k for k in waits if k != old_id)
            if other:   # already waits for a person's rewrite for another instruction: never regenerated over it
                leave([f"already waits for a person's rewrite ({', '.join(other)}): no deterministic substitution"])
                continue
            if act_change is not None:   # a changed dose, count or negation has no deterministic substitution: a person rewrites
                leave([f"action changed from {act_change[0]!r} to {act_change[1]!r}: a person rewrites the item"])
                continue
            if cond_change is not None:   # a changed condition has no deterministic substitution: a person rewrites the item
                leave([f"condition changed from {cond_change[0]!r} to {cond_change[1]!r}: a person rewrites the item"])
                continue
            if act_waits:   # waits for a person to write the changed action: a later time never discharges it
                leave([f"waits for a person's rewrite stating the action {act_to!r} ({old_id}): no deterministic substitution"])
                continue
            if cond_waits:   # waits for a person to write the condition a change introduced: a later time never discharges it
                leave([f"waits for a person's rewrite stating the condition {cond_to!r} ({old_id}): no deterministic substitution"])
                continue
            derived = list(dict.fromkeys(self._active(self.rests_on(cur)) + [old_id]))   # every instruction it rests on, not only this one
            if not (canonical_time(from_time) and canonical_time(new_time)):   # no deterministic substitution exists
                why = ([] if from_time else ["the instruction had no earlier time"]) \
                    + ([f"the earlier time {from_time!r} is not '<Weekday> h:mm a.m./p.m.' and the item's text states none of the "
                        "instruction's readable times"] if from_time and not canonical_time(from_time) else []) \
                    + ([f"the new time {new_time!r} is not '<Weekday> h:mm a.m./p.m.'"] if not canonical_time(new_time) else [])
                leave([f"time not readable ({'; '.join(why)}): no deterministic substitution"])
                continue
            cites = self._dedupe([dict(cite) if (c["source_id"], c["segment_id"]) == (from_cite["source_id"], from_cite["segment_id"]) else c
                                  for c in cur["cites"]])
            if canonical_time(from_time) == canonical_time(new_time):
                # the item's text already states the new time (states_time, also as '4 p.m.'): nothing to rewrite, only the
                # cite moves to the new source; it must fit the case like any other text (earlier times, corrections, ...)
                probs = self.fit_problems({**cur, "cites": cites, "derived_from": derived}, also=[old_id])
                if probs:
                    leave(probs)
                    continue
                self._new_version(iid, cur["content"], cites, f"re-cited: {old_id} superseded by {tx} {rev}; the text already states "
                                  f"{canonical_time(new_time)}", ev, method="fallback", derived_from=derived)
                continue
            nw, nc = canonical_time(new_time).split(" ", 1)
            ow, oc = canonical_time(from_time).split(" ", 1)
            must_not = ([oc] if oc != nc else []) + ([ow] if ow != nw else [])
            pair = {"from": canonical_time(from_time), "to": canonical_time(new_time), "kind": "superseded_by_new_source"}
            seg_before = self.segment_text(from_cite["source_id"], from_cite["revision"], from_cite["segment_id"]) or ""
            fallback = substitute_time(cur["content"], from_time, new_time)

            def fits(text, cur=cur, cites=cites, derived=derived):   # the version it would become fits the case as it is now
                return self.fit_problems({**cur, "content": text, "cites": cites, "derived_from": derived}, also=[old_id])
            content, method = self._regenerate_text(cur, seg_before, seg_after, self._keep_words(cur["content"]), fallback, [nw, nc], must_not, pair, fits)
            if content is None:   # stays stale: a person rewrites it (why: the substitution's text problems, else its fit problems)
                leave(self.text_problems(fallback, cur["content"], [nw, nc], must_not, facts(pair["to"])) or fits(fallback))
                continue
            self._new_version(iid, content, cites, f"regenerated: {old_id} superseded by {tx} {rev}", ev, method=method, derived_from=derived)

    # ---------------------------------------------------------------- kind: transcript_correction (Case B through the same door)
    def _change_transcript_correction(self, change: dict, ev: dict) -> None:
        corr = change.get("correction")
        if not isinstance(corr, dict):
            raise ValueError("a transcript_correction carries a 'correction' object")
        sid = corr.get("source_id")
        if isinstance(sid, str) and self.latest_revision(sid) is None:
            raise NotInCase(f"source not in case: {sid}")
        if isinstance(sid, str) and corr.get("base_revision") != self.latest_revision(sid):
            raise StaleBase(f"base_revision {corr.get('base_revision')} is not the latest revision of {sid} ({self.latest_revision(sid)})")
        res = self.apply_transcript_correction(corr)   # validates, creates the revision, marks stale (no new instruction)
        ev["source_added"] = {"source_id": sid, "revision": res["new_revision"], "corrected_from": corr["base_revision"]}
        ev["impact_set"] = sorted(res["impact_set"])
        rec = res["record"]
        # a corrected clock is written the transcript's way ('4 p.m.' -> '5 p.m.'); items and instructions use the
        # canonical spelling ('4:00 p.m.'), so a bare-clock correction substitutes the clock in either spelling
        cf, ct = _clock_canon(corr["from"]), _clock_canon(corr["to"])
        clock = _clock_rx(cf) if cf and ct else None
        to_v = ct if clock else corr["to"]
        not_v = list(dict.fromkeys([corr["from"]] + ([cf] if clock else [])))
        pair = {"from": cf if clock else corr["from"], "to": to_v, "kind": "transcript_correction"}

        def subst(text: str) -> str:
            return clock.sub(lambda m: ct, text) if clock else re.sub(re.escape(corr["from"]), lambda m: corr["to"], text, flags=re.I)
        # the instructions first, so a regenerated item is judged against the instruction as the correction left it: its
        # time (read from the corrected clause that stated it), its condition (the corrected words) and its action (only a
        # changed dose, count or negation it states) follow the corrected transcript, so nothing it rests on contradicts it
        for iid in res["affected_instructions"]:
            ins = self.instructions[iid]
            t, cond, act, before_cites = ins.get("time"), ins.get("condition"), ins.get("action"), copy.deepcopy(ins.get("cites"))
            t2, c2, a2 = self._corrected_fields(t, cond, act, rec)
            self.update_instruction_from_revision(iid, t2, res["new_revision"], sid)
            ins["condition"], ins["action"] = c2, a2
            ic = {"instruction_id": iid, "change": "time_from_corrected_transcript", "time_from": t, "time_to": ins.get("time"), "content_changed": True}
            if (t2, c2, a2) != (t, cond, act):
                ins.setdefault("history", []).append({"time": t, "condition": cond, "action": act, "cites": before_cites, "to_time": ins.get("time"),
                                                      "to_condition": c2, "to_action": a2, "corrected": True, "change_id": ev["change_id"]})
            if c2 != cond:
                ic["condition_from"], ic["condition_to"] = cond, c2
                for v in self.items.values():   # an item waiting to state the condition now waits for the corrected words
                    w = (v[-1].get("rewrite_for") or {}).get(iid)
                    if w and _text_key(w.get("condition_to")) == _text_key(cond):
                        w["condition_to"] = c2
            if a2 != act:
                ic["action_from"], ic["action_to"] = act, a2
                for v in self.items.values():
                    w = (v[-1].get("rewrite_for") or {}).get(iid)
                    if w and _text_key(w.get("action_to")) == _text_key(act):
                        w["action_to"] = a2
                q = self.add_pending("needs_clinical_confirmation", f"The transcript correction of {sid} ({corr['segment_id']}: '{corr['from']}' -> "
                                     f"'{corr['to']}', {res['new_revision']}) changes the dose, count or negation {iid} states: '{act}' is now "
                                     f"'{a2}'. Does the care team confirm the corrected action?", [{"source_id": sid, "revision": res["new_revision"],
                                                                                                  "segment_id": corr["segment_id"]}])
                q.setdefault("opened_by", ev["change_id"])
                ev["pending_changes"].append({"pending_id": q["pending_id"], "type": q["type"], "status": "open"})
            if t2 and t2 != t and not canonical_time(t2):   # the corrected clause states no readable time: never guessed
                q = self.add_pending("needs_transcript_check", f"The corrected time \"{t2}\" in {sid} {res['new_revision']} ({corr['segment_id']}) "
                                     "could not be read as '<Weekday> h:mm a.m./p.m.'. A person checks the recording and enters the time (a "
                                     "transcript correction to that form, e.g. 'Wednesday at 4:30 p.m.', or a clinician source).",
                                     [{"source_id": sid, "revision": res["new_revision"], "segment_id": corr["segment_id"]}])
                q.setdefault("opened_by", ev["change_id"])
                ev["pending_changes"].append({"pending_id": q["pending_id"], "type": q["type"], "status": "open"})
            ins["last_change"] = {"kind": ev["kind"], "change_id": ev["change_id"]}
            ev["instruction_changes"].append(ic)
        for iid in res["repointable_instructions"]:   # same segment text, so the citation may point at the new revision
            ins = self.instructions[iid]
            ins["cites"] = [{**c, "revision": res["new_revision"]} if c["source_id"] == sid else c for c in ins["cites"]]
        for iid in res["impact_set"]:
            cur = self.latest(iid)
            if cur.get("rewrite_for"):   # waits for a person's rewrite: a correction never writes over that
                ev["needs_person"].append({"item_id": iid, "why": [f"waits for a person's rewrite ({', '.join(sorted(cur['rewrite_for']))}): "
                                                                   "a transcript correction does not regenerate it"]})
                continue
            fallback = subst(cur["content"])
            keep = self._keep_words(cur["content"])
            cites = [{**c, "revision": res["new_revision"]} if c["source_id"] == sid else c for c in cur["cites"]]

            def fits(text, cur=cur, cites=cites):   # the version it would become fits the case as it is now
                return self.fit_problems({**cur, "content": text, "cites": cites})
            content, method = self._regenerate_text(cur, rec["segment_before"], rec["segment_after"], keep, fallback, [to_v] + keep, not_v, pair, fits)
            if content is None:
                ev["needs_person"].append({"item_id": iid, "why": check_item_content(fallback, [to_v] + keep, not_v) or fits(fallback)})
                continue
            self._new_version(iid, content, cites, "regenerated after transcript correction", ev, method=method)
        changed = set(res["changed_segments"])
        repointed = []
        for iid in self.items_citing(sid):   # items citing only unchanged segments: same text, citation follows the revision
            cur = self.latest(iid)
            if iid not in res["impact_set"] and not any(c["source_id"] == sid and c["segment_id"] in changed for c in cur["cites"]):
                cur["cites"] = [{**c, "revision": res["new_revision"]} if c["source_id"] == sid else c for c in cur["cites"]]
                repointed.append(iid)
        ev["citation_repoints"] = sorted(repointed) + sorted(res["repointable_instructions"])
        ev["correction"] = {k: rec[k] for k in ("from", "to", "segment_id", "segment_before", "segment_after", "new_revision")}

    # ---------------------------------------------------------------- kind: family_statement (a conflict, never a change)
    def _change_family_statement(self, change: dict, ev: dict) -> None:
        if any(k in change for k in ("instructions", "supersedes", "source")):
            raise ValueError("a family statement cannot carry instructions: only a clinical source can change an instruction")
        utt = change.get("utterance")
        if not isinstance(utt, str) or not utt.strip():
            raise ValueError("a family statement needs an 'utterance'")
        utt = " ".join(utt.split())   # one line; it is quoted, attributed, inside the conflict record
        if len(utt) > MAX_UTTERANCE:
            raise ValueError(f"an utterance has at most {MAX_UTTERANCE} characters")
        about = change.get("about_instruction")
        if about is not None and about not in self.instructions:
            raise NotInCase(f"about_instruction not in this case: {about}")
        if about is None:
            # the active instruction whose words overlap most with the statement (ties: first id); a statement that shares
            # no word with any instruction is filed against the first timed one (a time claim, as in the fixture's step 6)
            active = sorted(i for i, ins in self.instructions.items() if ins.get("status") == "active")
            best = min(active, key=lambda i: (-action_overlap(utt, self.instructions[i]["action"]), i), default=None)
            if best is not None and action_overlap(utt, self.instructions[best]["action"]) > 0:
                about = best
            else:
                about = next((i for i in active if self.instructions[i].get("time")), None)
        ref = self.instructions[about]["cites"][0] if about else None
        said = self.segment_text(ref["source_id"], ref["revision"], ref["segment_id"]) if ref else "no matching source"
        label = f"{ref['source_id']} {ref['revision']}" if ref else "the case sources"
        q = self.add_pending("conflict", f'family_statement ({ev["actor"]}) says: "{utt}"; {label} says: "{said}"',
                             [{"source_id": ref["source_id"], "revision": ref["revision"]}] if ref else [])
        q.setdefault("about_instruction", about)
        q.setdefault("opened_by", ev["change_id"])
        q.setdefault("resolved_by", None)
        ev["pending_changes"].append({"pending_id": q["pending_id"], "type": "conflict", "status": q["status"], "about_instruction": about})

    # ---------------------------------------------------------------- kind: event_confirmation (first confirmation or re-judge)
    def _change_event_confirmation(self, change: dict, ev: dict) -> None:
        e = change.get("event")
        if not isinstance(e, dict) or not isinstance(e.get("source_id"), str) or e.get("human_label") not in ("fall", "no_fall"):
            raise ValueError("an event needs 'source_id', 'human_label' (fall | no_fall) and 'occurred_at' (ISO local time)")
        _local_iso(e.get("occurred_at"), "an event's 'occurred_at'")
        # the ids and the score are printed into the fall note, the process task and the notice: short tokens, a number
        for k in ("input_id", "model_label", "run_id", "score_type"):
            _label(e.get(k), f"event '{k}'")
        _score(e.get("model_score"), "event 'model_score'")
        sid, when, day = e["source_id"], _hm(e["occurred_at"]), _dm(e["occurred_at"])
        prev_rev = self.latest_revision(sid)
        if prev_rev is None:
            if e.get("base_revision"):
                raise NotInCase(f"source not in case: {sid}")
            text = (f"{'Fall' if e['human_label'] == 'fall' else 'No fall'} at {when} on {day} confirmed by {ev['actor']} "
                    f"(clip {e.get('input_id')}; model said {e.get('model_label')}, score {e.get('model_score')}, uncalibrated)")
            self.sources[(sid, "r1")] = {"source_id": sid, "revision": "r1", "source_type": "event_confirmation", "run_id": e.get("run_id"),
                                         "input_id": e.get("input_id"), "model_label": e.get("model_label"), "model_score": e.get("model_score"),
                                         "score_type": e.get("score_type"), "human_label": e["human_label"], "occurred_at": e["occurred_at"],
                                         "confirmed_by": ev["actor"], "note": e.get("note"), "review_status": "approved",
                                         "segments": {"e1": {"segment_id": "e1", "text": text}}}
            ev["source_added"] = {"source_id": sid, "revision": "r1", "source_type": "event_confirmation", "human_label": e["human_label"]}
            ev["event"] = {"source_id": sid, "revision": "r1", "human_label": e["human_label"], "occurred_at": e["occurred_at"]}
            if e["human_label"] == "fall":
                self._fall_items(sid, "r1", ev)
            return
        if e.get("base_revision") != prev_rev:
            raise StaleBase(f"base_revision {e.get('base_revision')} is not the latest revision of {sid} ({prev_rev})")
        old = self.sources[(sid, prev_rev)]
        new_rev = f"r{int(prev_rev[1:]) + 1}"
        text = f"Re-judged by {ev['actor']}: {e['human_label'].replace('_', ' ')} at {when} on {day} (was {old['human_label'].replace('_', ' ')})"
        self.sources[(sid, new_rev)] = {**old, "revision": new_rev, "human_label": e["human_label"], "note": e.get("note"),
                                        "rejudged_from": prev_rev, "rejudged_by": ev["actor"], "segments": {"e1": {"segment_id": "e1", "text": text}}}
        ev["source_added"] = {"source_id": sid, "revision": new_rev, "source_type": "event_confirmation",
                              "human_label_from": old["human_label"], "human_label_to": e["human_label"]}
        ev["event"] = {"source_id": sid, "revision": new_rev, "human_label": e["human_label"], "occurred_at": e["occurred_at"],
                       "rejudged_from": prev_rev}
        impact = self.items_citing(sid)   # event-derived items only; clinician instructions are a different source
        self._mark_stale(impact, ev)
        cite = [{"source_id": sid, "revision": new_rev, "segment_id": "e1"}]
        withdrawn = e["human_label"] != "fall"
        for iid in impact:
            cur = self.latest(iid)
            patch = ({"status": "cancelled"} if withdrawn else {"status": "planned"}) if cur.get("kind") == "task" else None
            self._new_version(iid, f"{'Withdrawn' if withdrawn else 'Re-confirmed'}: {text}.", cite,
                              f"event re-judged ({prev_rev} -> {new_rev})", ev, schedule_patch=patch)
        for q in self.pending:
            if q["status"] == "open" and any(c.get("source_id") == sid for c in q.get("cites", [])):
                q["status"], q["closed_reason"] = "closed", f"event re-judged as {e['human_label'].replace('_', ' ')} ({ev['change_id']})"
                ev["pending_changes"].append({"pending_id": q["pending_id"], "type": q["type"], "status": "closed"})
        if not withdrawn:
            # re-judged AS a fall: the note and the process task exist (re-confirmed above) or, after a first 'no fall',
            # are created now exactly as a first confirmation would; the care-team question is asked again
            if not impact:
                self._fall_items(sid, new_rev, ev)
            else:
                self._fall_question(sid, new_rev, ev)

    def _fall_items(self, sid: str, rev: str, ev: dict) -> None:
        """What a confirmed fall produces (product rule): the handover note, the 'tell the care team' task due 20:00
        that day, and one question for the care team. The texts are templates filled from the stored event record and
        checked like any item text before they are stored."""
        src, cite = self.sources[(sid, rev)], [{"source_id": sid, "revision": rev, "segment_id": "e1"}]
        when, day = _hm(src["occurred_at"]), _dm(src["occurred_at"])
        note = (f"Event: fall at {when} on {day} confirmed by {ev['actor']} (clip {src.get('input_id')}; model score {src.get('model_score')}, "
                "uncalibrated). Tell the care team.")
        task = f"Tell the care team about the fall at {when}"
        for text in (note, task):
            viol = check_item_content(text, forbid_relaxing=True)
            if viol:
                raise ValueError("event text rejected: " + "; ".join(viol))
        self._new_item(f"ho-{sid}", "handover_item", note, cite, ev, origin="product_rule")
        self._new_item(f"task-{sid}-01", "task", task, cite, ev, origin="product_rule",
                       schedule={"anchor": "fixed", "due_at": src["occurred_at"][:11] + "20:00", "status": "planned"})
        self._fall_question(sid, rev, ev)

    def _fall_question(self, sid: str, rev: str, ev: dict) -> None:
        when = _hm(self.sources[(sid, rev)]["occurred_at"])
        q = self.add_pending("needs_clinical_confirmation", f"After the fall at {when}, does the care team want to review any instruction?",
                             [{"source_id": sid, "revision": rev, "segment_id": "e1"}])
        q.setdefault("opened_by", ev["change_id"])
        ev["pending_changes"].append({"pending_id": q["pending_id"], "type": q["type"], "status": "open"})

    # ---------------------------------------------------------------- kind: generation_delivery (late job, base-version check)
    def start_generation(self, item_id: str, method: str = "llm") -> dict:
        """A job that will deliver a replacement text for the item. `base_cites` are the cites that text will rest on:
        the item's own, or for a stale item the current ones (see _rewrite_cites), so a job started on an item left for
        a person's rewrite is not refused as stale for cites that were already outdated when it started."""
        if item_id not in self.items:
            raise NotInCase(f"item not in case: {item_id}")
        cur = self.latest(item_id)
        if cur.get("kind") not in CONTENT_KINDS:   # an archived export is never regenerated (nor overwritten)
            raise ConflictError(f"{item_id} is " + ("an archived export: it is never regenerated" if cur.get("kind") == "exported_pdf"
                                                    else f"a {cur.get('kind')}, not a task, handover item or sheet section") + "; nothing was started")
        gone = [i for i in cur.get("derived_from") or [] if (self.instructions.get(i) or {}).get("status") != "active"]
        if gone:
            raise ConflictError(f"{item_id} rests on {', '.join(gone)}, which was withdrawn: there is nothing to rewrite; nothing was started")
        job = {"job_id": f"job-{len(self.jobs) + 1:03d}", "item_id": item_id, "base_case_version": self.case_version,
               "base_cites": self._rewrite_cites(cur), "base_version": cur.get("version"), "base_status": cur.get("review_status"),
               "method": method, "status": "running"}
        self.jobs[job["job_id"]] = job
        self.audit.append({"op": "start_generation", "job_id": job["job_id"], "item_id": item_id, "base_case_version": self.case_version})
        return copy.deepcopy(job)

    def _change_generation_delivery(self, change: dict, ev: dict) -> None:
        job = self.jobs.get(change.get("job_id"))
        if job is None:
            raise NotInCase(f"job not in case: {change.get('job_id')}")
        content = change.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("a generation delivery needs non-empty 'content'")
        if job["status"] != "running":
            raise ConflictError(f"job {job['job_id']} already {job['status']}")
        latest = self.latest(job["item_id"])
        # stale: the case moved on (case_version), a cite it rests on was corrected, the item has a newer version, or a
        # review withdrew it since (a rejection creates no version and does not bump case_version) or withdrew an
        # instruction it rests on
        stale = job["base_case_version"] != self.case_version or any(not self.cite_is_valid(c) for c in job["base_cites"]) \
            or latest.get("version") != job.get("base_version") \
            or (latest.get("review_status") == "rejected" and job.get("base_status") != "rejected") \
            or any((self.instructions.get(i) or {}).get("status") != "active" for i in latest.get("derived_from") or [])
        ev["job"] = {k: job[k] for k in ("job_id", "item_id", "base_case_version")}
        if stale:   # a late result never overwrites the newer case: refused, kept in the audit, not published
            job["status"], job["discarded_content"] = "refused_stale", content
            self.audit.append({"op": "refuse_stale_generation", "job_id": job["job_id"], "base": job["base_case_version"], "now": self.case_version})
            ev["status"], ev["refused"] = "refused", "stale_generation"
            ev["discarded_content"] = content
            return
        cur = self.latest(job["item_id"])
        view = {**cur, "cites": job["base_cites"]}   # the delivered text is judged against the sources it will cite
        bound = list(cur.get("rewrite_for") or {})
        ids = self._gate_ids(cur, view, bound=bound)
        must, must_not = self._time_guards(cur, ids, bound)
        grounded = self._grounded_facts(view, ids)
        # facts it may add and facts it must keep: both judged against the sources it will cite, so a dose the source
        # still states cannot be dropped, while a fact the change removed (an old condition, an earlier time) may go
        new = {**cur, "content": content, "cites": job["base_cites"]}
        also = self._active(self.rests_on(cur))
        # the facts of a time an instruction moved away from (also one nobody could read, 'eleven o'clock') may be dropped
        moved = set().union(*[facts(t) for i in self._active(ids + also + bound) for t in self._earlier_time_words(self.instructions[i])] or [set()])
        moved -= set().union(*[facts(canonical_time(self.instructions[i].get("time")) or self.instructions[i].get("time") or "")
                               for i in self._active(ids + also + bound)] or [set()])
        viol = self.text_problems(content, cur["content"], must, must_not + self._corrected_values(new, also + bound), grounded,
                                  keep_within=grounded - moved)
        # and it must fit the case as it is now, judged against every instruction the item rests on or waits for
        viol += self.fit_problems(new, also=also, waits=bound)
        if viol:   # one line per problem: a fit reason that repeats a text check ('still contains X (why)') is dropped
            out = {}
            for m in viol:
                out.setdefault(m.split(" (")[0], m)
            raise ValueError("delivered content rejected: " + "; ".join(out.values()))
        v = self._new_version(job["item_id"], content, copy.deepcopy(job["base_cites"]), f"generation {job['job_id']}", ev, method=job.get("method", "llm"))
        job["status"], job["published_version"] = "published", v["version"]

    # ---------------------------------------------------------------- the replacement-text gate (delivery and restore)
    @staticmethod
    def _dedupe(cites: list[dict]) -> list[dict]:
        seen, out = set(), []
        for c in cites:
            k = (c.get("source_id"), c.get("revision"), c.get("segment_id"))
            if k not in seen:
                seen.add(k)
                out.append(c)
        return out

    def _follow_latest(self, c: dict) -> dict:
        """A copy of cite c on the latest revision of its source when the segment exists there (a transcript was
        corrected since), else unchanged."""
        c = copy.deepcopy(c)
        latest = self.latest_revision(c["source_id"])
        if latest and latest != c.get("revision") and self.segment_text(c["source_id"], latest, c["segment_id"]) is not None:
            c["revision"] = latest
        return c

    def _rewrite_cites(self, item: dict) -> list[dict]:
        """The cites a replacement of this item rests on: a cite of an earlier revision follows to the latest revision of
        its source when the segment exists there (a transcript was corrected while the item waited), and the segment an
        instruction moved away from (`rewrite_for`: the item waits for a person's rewrite for that instruction) is
        replaced by the instruction's current cite, which follows to the latest revision the same way (after a rejected
        instruction change that came from a transcript correction, the instruction cites the corrected-away revision
        again; a rewrite cites the corrected one). The item's own cites when they are current."""
        out = [self._follow_latest(c) for c in item.get("cites", [])]
        waits = item.get("rewrite_for") or {}
        ids = self._active(list(waits) + self.rests_on(item))
        for iid in ids:
            ins = self.instructions[iid]
            if not ins.get("cites"):
                continue
            now = self._follow_latest(ins["cites"][0])
            key = lambda c: (c["source_id"], c["segment_id"])  # noqa: E731
            # the cites this instruction moved away from (the one the item waits on, its superseded or rejected cites, its
            # history) are replaced by its current one, unless another active instruction still rests on them, also when the
            # current one is already there (one new sentence may ground two instruction changes); an item that cites none
            # of them gets the current cite added, so its rewrite can rest on that sentence
            earlier = {key(c) for c in [(waits.get(iid) or {}).get("from_cite")] + self._earlier_cites(ins) if c}
            kept = {key(c) for j, other in self.instructions.items() if j != iid and other.get("status") == "active" for c in other.get("cites", [])}
            gone = earlier - kept - {key(now)}
            if key(now) in {key(c) for c in out}:
                out = [c for c in out if key(c) not in gone]
                continue
            hit = next((n for n, c in enumerate(out) if key(c) in gone), None)
            if hit is None:
                out.append(now)
            else:
                out = [now if n == hit else c for n, c in enumerate(out) if n == hit or key(c) not in gone]
        return self._dedupe(out)

    def _gate_ids(self, *versions: dict, bound=()) -> list[str]:
        """The active instructions a replacement text is judged against: those each given version rests on (the current
        version, the cites the replacement will carry) and `bound` (instructions the item waits on for a person)."""
        ids = [i for v in versions for i in self.instructions_for_item(v)] + list(bound)
        return [i for i in dict.fromkeys(ids) if i in self.instructions and self.instructions[i].get("status") == "active"]

    def _corrected_values(self, view: dict | None = None, ids=()) -> list[str]:
        """Values a transcript correction removed (a corrected clock also in its canonical spelling, '4 p.m.' ->
        '4:00 p.m.'): never in a replacement text, delivered, regenerated or restored. With `view` (the version being
        judged) only the corrections of a segment it cites, or that one of its instructions (rests_on, `ids`) rests on,
        count, and a value one of its cited segments states again on its latest revision (a counter-correction, or a
        later recording back at that time) is grounded there and no longer forbidden; the corrected-away revision never
        grounds it, since only the latest revision is read."""
        def spellings(c):
            return [x for x in (c["from"], _clock_canon(c["from"]), canonical_time(c["from"])) if x]
        if view is None:
            return list(dict.fromkeys(x for c in self.corrections for x in spellings(c)))
        keys = {(c.get("source_id"), c.get("segment_id")) for c in view.get("cites", [])}
        for i in self._active(self.rests_on(view) + list(ids)):
            keys |= {(c["source_id"], c["segment_id"]) for c in self.instructions[i].get("cites", [])}
        vals = list(dict.fromkeys(x for c in self.corrections if (c["source_id"], c["segment_id"]) in keys for x in spellings(c)))
        texts = [self.segment_text(c["source_id"], self.latest_revision(c["source_id"]) or c.get("revision"), c.get("segment_id"))
                 for c in view.get("cites", [])]
        return [x for x in vals if not any(_mentions(t, x) for t in texts if t)]

    def _time_guards(self, item: dict, ids: list[str] | None = None, bound=()) -> tuple[list[str], list[str]]:
        """must_contain / must_not_contain for a text that replaces this item: the current canonical weekday and clock
        of each timed instruction it rests on (`ids`, default instructions_for_item), required when the item's current
        text states that clock or an earlier clock of the instruction, or when the item waits for a person's rewrite for
        it (`bound`); and the clock and weekday of every earlier time of those instructions (_earlier_times: the last
        approved time, every rejected proposal, every time it moved away from) that differ from the current one, so a
        late, hand-written or restored text can never restate an old time."""
        must, must_not = [], []
        text = item["content"].lower()
        for iid in (self.instructions_for_item(item) if ids is None else ids):
            ins = self.instructions[iid]
            cur = canonical_time(ins.get("time"))
            nw, nc = _time_parts(ins.get("time"))
            olds = []
            for o in self._earlier_times(ins):
                olds.append(o.split(" ", 1))
            if cur and (iid in bound or nc.lower() in text or any(oc.lower() in text for _, oc in olds)):
                must += [nw, nc]
            for ow, oc in olds:   # a weekday-only move keeps the clock: only what differs is forbidden
                must_not += ([oc] if oc != nc else []) + ([ow] if ow != nw else [])
        return must, must_not

    def _grounded_facts(self, item: dict, ids: list[str] | None = None) -> set[str]:
        """Facts (times, numbers, weekdays) a replacement text may state besides the item's own: those in the current
        text of the segments it cites, and the current time and the currently cited sentence of its instructions (`ids`,
        default instructions_for_item); a clock in a sentence also grounds its canonical spelling ('4 p.m.' -> '4:00')."""
        out = set()
        for c in item.get("cites", []):
            out |= self._cite_facts(c)
        for iid in (self.instructions_for_item(item) if ids is None else ids):
            ins = self.instructions[iid]
            out |= facts(canonical_time(ins.get("time")) or "")
            for c in ins.get("cites", []):
                out |= self._cite_facts(c)
        return out

    def _cite_facts(self, c: dict) -> set[str]:
        """Facts the latest revision of a cited segment states; a confirmed event's record also states its clip id and model
        score (a re-judged revision keeps them from the first one, though its sentence does not repeat them)."""
        rev = self.latest_revision(c["source_id"]) or c.get("revision")
        out = _segment_facts(self.segment_text(c["source_id"], rev, c.get("segment_id")))
        src = self.sources.get((c["source_id"], rev)) or {}
        if src.get("source_type") == "event_confirmation":
            out |= facts(f"{src.get('input_id') or ''} {src.get('model_score') if src.get('model_score') is not None else ''}")
        return out

    def _restore_problems(self, cur: dict, old: dict, also=()) -> tuple[list[dict], list[str]]:
        """May `old` (a version a person approved) come back as the APPROVED content in place of `cur`? Only if it fits the
        case as it is now (fit_problems), judged against every instruction either version rests on and `also` (e.g. the
        instruction whose change was just rejected): their current time and condition, no earlier or rejected time, no
        corrected value, no ungrounded fact, the current cite of each instruction; plus no relaxing sentence. Its cites
        are re-pointed to the latest revision when the segment text is byte-equal there. Returns (cites, problems)."""
        cites = []
        for c in copy.deepcopy(old.get("cites", [])):
            latest = self.latest_revision(c["source_id"])
            if latest and c.get("revision") != latest and \
                    self.segment_text(c["source_id"], latest, c["segment_id"]) == self.segment_text(c["source_id"], c["revision"], c["segment_id"]):
                c["revision"] = latest
            cites.append(c)
        view = {**old, "cites": cites}
        probs = self.fit_problems(view, also=self._active(self.rests_on(cur)) + list(also), waits=list(cur.get("rewrite_for") or {}))
        probs += check_item_content(old["content"], forbid_relaxing=True)
        return cites, probs

    def _waits_after_restore(self, cur: dict, old: dict, cites: list[dict], ev: dict, also=()) -> dict:
        """`rewrite_for` of a restored version that came back stale: per instruction `cur` rested on, the time the restored
        text states (an earlier or the current time of the instruction) and the cite it moved away from, so the person's
        rewrite is judged against that instruction and a later readable time reaches the item."""
        out = {}
        for iid in self._active(list(cur.get("rewrite_for") or {}) + self.rests_on(cur) + list(also)):
            ins, prior = self.instructions[iid], (cur.get("rewrite_for") or {}).get(iid) or {}
            times = [prior.get("from_time"), ins.get("time")] + self._earlier_times(ins)
            earlier = [prior.get("from_cite")] + self._earlier_cites(ins)
            now = (ins.get("cites") or [None])[0]
            fc = next((c for c in cites if any(e and (e["source_id"], e["segment_id"]) == (c["source_id"], c["segment_id"]) for e in earlier)), None)
            out[iid] = {"from_time": next((canonical_time(t) for t in times if states_time(old["content"], t)), None),
                        "from_cite": dict(fc) if fc else None, "to_time": ins.get("time"),
                        "to_cite": copy.deepcopy(now), "change_id": ev["change_id"]}
            # a condition a change introduced and the restored text does not state: the person's rewrite states it, and a
            # later time-only change never substitutes the time into the text instead (see _supersede_instruction)
            cond_to = prior.get("condition_to")
            if (cond_to and _text_key(cond_to) == _text_key(ins.get("condition"))) or any("condition" in p for p in self._condition_problems(old["content"], iid)):
                out[iid]["condition_to"] = ins.get("condition")
        return out

    # ---------------------------------------------------------------- kind: review (approve / reject; never bumps case_version)
    def _change_review(self, change: dict, ev: dict) -> None:
        decision = change.get("decision", "approve")
        if decision == "confirm_on_behalf":   # the primary caregiver's fallback (care_cases.md "Confirmation roles")
            self._confirm_on_behalf(change, ev)
            return
        if ev["role"] != CLINICIAN_ROLE:
            raise PermissionError(f"review needs role care_team; {ev['actor']} is {ev['role']}")
        if decision == "approve":
            # a version or instruction in force on the primary caregiver's on-behalf confirmation is confirmed by the clinician
            # the same way (approve, named or all): it gets clinician_confirmed and its label says so
            ids = self._pending_ids() + self.awaiting_clinician() if change.get("all") else change.get("ids")
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                raise ValueError("'ids' must be a list of item or instruction ids (or 'all': true)")
            unknown = [i for i in ids if i not in self.items and i not in self.instructions]
            if unknown:
                raise NotInCase(f"not in this case: {', '.join(unknown)}")
            upgrades = [i for i in ids if self._awaiting_clinician(i)]
            not_pending = [i for i in ids if i not in upgrades and (self.latest(i).get("review_status") if i in self.items
                                                                     else self.instructions[i].get("derivation_status")) != "pending_review"]
            if not_pending:   # a stale item is rewritten by a person first; an approved one is not approved twice
                raise ConflictError(f"not pending review: {', '.join(not_pending)}")
            # nothing that contradicts the case as it is now is approved (fit_problems). Named ids are refused as a whole
            # (NotFit, nothing changes); approve-all approves the rest and lists the others in reviewed.refused, still
            # pending: a person rejects them (their approved text comes back if it fits) or delivers a rewrite
            unfit = {i: p for i in ids for p in [self.fit_problems(self.latest(i)) if i in self.items else self.instruction_problems(i)] if p}
            if unfit and not change.get("all"):
                raise NotFit(unfit)
            ok = [i for i in ids if i not in unfit and i not in upgrades]
            confirmed = [i for i in upgrades if i not in unfit]
            super().approve(ok)
            for i in ok:
                if i in self.items:
                    self.latest(i)["approved_by"] = ev["actor"]
            for i in confirmed:
                self._current(i)["clinician_confirmed"] = {"by": ev["actor"], "at": change.get("at"), "change_id": ev["change_id"]}
            ev["reviewed"] = {"decision": "approve", "approved": sorted(ok), "rejected": []}
            if confirmed:
                ev["reviewed"]["clinician_confirmed"] = sorted(confirmed)
            if unfit:   # only approve-all gets here with refusals: they stay pending_review, listed with their reasons
                ev["reviewed"]["refused"] = [{"item_id": i, "why": unfit[i]} for i in sorted(unfit)]
            for i in sorted(unfit):
                ev["needs_person"].append({"item_id": i, "why": ["not approved: it no longer fits the case (reject it, or deliver a rewrite)"] + unfit[i]})
            return
        if decision != "reject":
            raise ValueError("decision must be 'approve' or 'reject'")
        iid, reason = change.get("id"), change.get("reason")
        if not isinstance(iid, str):
            raise ValueError("'id' must be an item or instruction id")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("a rejection needs a 'reason'")
        # restored: back to the last approved version / state; restored_stale: the last approved version came back but no
        # longer fits the case, so it is stale for a person to rewrite; withdrawn: nothing approved to fall back to
        ev["reviewed"] = {"decision": "reject", "approved": [], "rejected": [iid], "reason": reason, "restored": [], "restored_stale": [],
                          "withdrawn": []}
        # a version or instruction in force on the primary caregiver's on-behalf confirmation is rejected by the clinician
        # on the normal path, as if it were still pending: the last approved state comes back if it fits
        on_behalf = self._awaiting_clinician(iid)
        if on_behalf:
            ev["reviewed"]["on_behalf_rejected"] = [iid]
        if iid in self.items:
            if on_behalf:
                self.latest(iid)["review_status"] = "pending_review"   # the label stays on the rejected version, as history
            if self.latest(iid).get("review_status") != "pending_review":
                raise ConflictError(f"{iid} v{self.latest(iid).get('version')} is {self.latest(iid).get('review_status')}, not pending_review")
            self._withdraw_version(iid, reason, ev, on_behalf=on_behalf)
        elif iid in self.instructions:
            labels = {}
            if on_behalf:
                labels = self._pop_labels(self.instructions[iid])
                self.instructions[iid]["derivation_status"] = "pending_review"
            self._reject_instruction(iid, reason, ev)
            if labels:   # the rejected state keeps how it had been confirmed
                self.instructions[iid]["rejected_change"].update(labels)
        else:
            raise NotInCase(f"not in this case: {iid}")

    def _reject_instruction(self, iid: str, reason: str, ev: dict) -> None:
        """Reject an instruction's pending change. The instruction goes back to its last APPROVED state (never an
        unapproved intermediate one; a never-approved instruction is withdrawn). A transcript correction made since that
        state is never undone by a rejection: when it changed the time the state states, the state comes back with the
        correction applied (pending review: that time was never approved), and when the rejected change IS that
        correction, the rejection is refused (ConflictError: no rewrite of its items could fit both the transcript and
        the restored time; a counter-correction or a clinician source is the way). Then every current version that rests
        on the instruction or cites the rejected change's sentence is judged against the restored case: a pending one the
        change wrote, or one that no longer fits, is rejected and its approved text restored if that fits (else stale or
        withdrawn); an approved one that no longer fits goes back to its last approved text that fits, else stale for a
        person; a stale one gets its last approved text back if that fits now."""
        ins = self.instructions[iid]
        if ins.get("derivation_status") != "pending_review":
            raise ConflictError(f"{iid} is {ins.get('derivation_status')}, not pending_review")
        chg = (ins.get("last_change") or {}).get("change_id")
        rej_keys = {(c["source_id"], c["segment_id"]) for c in ins.get("cites") or []}
        # found before its cites are restored: not only the versions the change wrote, also a delivery or a person's
        # rewrite made for it (they rest on the instruction or cite the rejected sentence)
        touched = [i for i, vs in sorted(self.items.items()) if vs[-1].get("kind") in CONTENT_KINDS
                   and vs[-1].get("review_status") in ("pending_review", "approved", "stale")
                   and (iid in self.rests_on(vs[-1]) or rej_keys & {(c["source_id"], c["segment_id"]) for c in vs[-1].get("cites", [])})]
        produced = {i for i in touched if self.latest(i).get("review_status") == "pending_review" and self.latest(i).get("change_id") == chg}
        prev = ins.get("previous")
        state = {k: copy.deepcopy(prev[k]) for k in ("time", "condition", "action", "cites") if k in prev} if prev and prev.get("was_approved", True) else None
        if state is not None and "condition" not in state:
            # a `previous` stored before it kept the condition: the condition the instruction had when it left that state
            # (the newest change that left its time and cites), never the condition the rejected change brought
            left = next((h for h in reversed(ins.get("history") or []) if not h.get("rejected") and h.get("time") == state.get("time")
                         and [(c["source_id"], c["segment_id"]) for c in h.get("cites") or []] == [(c["source_id"], c["segment_id"]) for c in state.get("cites") or []]), None)
            if left is not None:
                state["condition"] = left.get("condition")
        corrected = self._reapply_corrections(state) if state else None
        if corrected is not None and self._same_state(corrected, ins):
            corr = corrected["_corrections"][-1]
            back = [f"{k} {state.get(k)!r}" for k in ("time", "condition", "action") if k in state and corrected.get(k) != state.get(k)]
            raise ConflictError(f"{iid}'s pending change is the transcript correction {corr['source_id']} {corr['base_revision']} -> {corr['new_revision']} "
                                f"('{corr['from']}' -> '{corr['to']}'): rejecting it would put {iid} back to its {', '.join(back) or 'earlier state'}, "
                                "which the corrected transcript no longer states, and no rewrite of its items could fit both. Correct the transcript "
                                "back (a transcript correction of the latest revision) or record a clinician source; nothing was changed")
        ins["rejected_change"] = {"time": ins.get("time"), "condition": ins.get("condition"), "action": ins.get("action"), "cites": ins.get("cites"),
                                  "reason": reason, "by": ev["actor"]}
        # every rejected state stays known (a later rejection replaces rejected_change): its time, condition, action and cite
        # are never restated or cited by a replacement text
        ins.setdefault("history", []).append({"time": ins.get("time"), "condition": ins.get("condition"), "action": ins.get("action"),
                                               "cites": copy.deepcopy(ins.get("cites")), "rejected": True, "change_id": chg})
        if state is None:      # a new instruction nobody approved: it leaves the case's active instructions
            ins.pop("previous", None)
            ins["derivation_status"], ins["status"] = "rejected", "rejected"
            change = "rejected_withdrawn"
            ev["reviewed"]["withdrawn"].append(iid)
        elif corrected is not None:   # back to the approved state, with the transcript correction made since applied
            for k in ("time", "condition", "action", "cites"):
                if k in corrected:
                    ins[k] = corrected[k]
            ins["derivation_status"] = "pending_review"   # that corrected time was never approved; `previous` stays the approved basis
            change = "rejected_restored_corrected"
        else:                  # back to the last approved state
            # a state approved only on the clinician's behalf comes back labelled, with the clinician's own last approved
            # state as its `previous`: a clinician who rejects it in turn reaches that state (never a withdrawal)
            nxt = prev.get("clinician_previous") if self._on_behalf_only(prev) else None
            ins.pop("previous", None)
            if nxt:
                ins["previous"] = {**copy.deepcopy(nxt), "was_approved": True}
            for k in ("time", "condition", "action", "cites"):
                if k in state:
                    ins[k] = state[k]
            ins.update({k: copy.deepcopy(prev[k]) for k in LABEL_KEYS if k in prev})   # with how that state was confirmed
            ins["derivation_status"] = "approved"
            change = "rejected_restored_previous"
            ev["reviewed"]["restored"].append(iid)
            if self._on_behalf_only(ins):
                ev["reviewed"].setdefault("restored_on_behalf", []).append(iid)
        ins["last_change"] = {"kind": "review", "decision": "reject", "change_id": ev["change_id"]}
        ic = {"instruction_id": iid, "change": change, "time": ins.get("time"), "content_changed": True}
        if corrected is not None:
            ic["corrected_by"] = [{k: c[k] for k in ("source_id", "base_revision", "new_revision", "from", "to")} for c in corrected["_corrections"]]
        ev["instruction_changes"].append(ic)
        ev["needs_person"].append({"item_id": iid, "why": [f"rejected: {reason}"]})
        withdrawn = ins.get("status") != "active"
        held_other = {(c["source_id"], c["segment_id"]) for j, o in self.instructions.items() if j != iid and o.get("status") == "active"
                      for c in o.get("cites") or []}

        def also_for(cur: dict) -> list[str]:
            # a version is judged against the restored instruction when it rests on it, waits for it, restates it (its words,
            # or for a timed instruction any clock or weekday: never the rejected time), or cites the rejected sentence while
            # no other active instruction rests on that sentence; one that reached the list only through a sentence another
            # instruction still holds (one sentence grounding two changes) and does not restate it is judged without it
            keys = {(c["source_id"], c["segment_id"]) for c in cur.get("cites", [])}
            mine = iid in self.rests_on(cur) or iid in (cur.get("rewrite_for") or {}) or bool((rej_keys & keys) - held_other) \
                or self._restates(cur.get("content") or "", ins)
            return [iid] if mine and not withdrawn else []
        handled = set()
        # a clinician rejected a state in force on the primary caregiver's confirmation: the items step back to the newest
        # approved version that fits the restored state, also past the on-behalf versions in between (deep)
        deep = bool(ev["reviewed"].get("on_behalf_rejected"))
        if withdrawn:   # nothing rests on a withdrawn instruction any more
            for i, vs in sorted(self.items.items()):
                cur = vs[-1]
                if cur.get("kind") not in CONTENT_KINDS or cur.get("review_status") in ("rejected", "superseded") or iid not in (cur.get("derived_from") or []):
                    continue
                rest = [x for x in cur["derived_from"] if x != iid]
                if rest:   # it still rests on its other instructions
                    cur["derived_from"] = rest
                elif cur.get("review_status") != "pending_review":   # it existed for that instruction only: withdrawn with it
                    # (a pending one is rejected below, and _withdraw_version restores nothing that rests on withdrawn ones only)
                    cur["review_status"], cur["reject_reason"], cur["rejected_by"] = "rejected", f"{iid} withdrawn: {reason}", ev["actor"]
                    ev["reviewed"]["withdrawn"].append(i)
                    ev["needs_person"].append({"item_id": i, "why": [f"{iid} withdrawn: {reason}"]})
                    handled.add(i)
        for i in touched:
            if i in handled:
                continue
            cur = self.latest(i)
            st, also = cur.get("review_status"), also_for(cur)
            if st == "pending_review" and (i in produced or self.fit_problems(cur, also=also)):
                # the content written for the rejected change goes with it: back to its approved version, or withdrawn
                self._withdraw_version(i, f"{iid} change rejected: {reason}", ev, also=also)
                handled.add(i)
            elif st == "approved":
                probs = self.fit_problems(cur, also=also)
                if probs:
                    self._send_back(i, iid, reason, probs, ev, also=also, deep=deep)
                    handled.add(i)
        for i, vs in sorted(self.items.items()):
            # an item stale for this instruction (left for a person's rewrite by the change, a restored version that did not
            # fit it, or stale while resting on it) may fit the restored instruction again: its last approved text comes
            # back approved if it fits, else it keeps waiting
            cur = vs[-1]
            waits = cur.get("rewrite_for") or {}
            if i in handled or cur.get("review_status") != "stale" or not (iid in waits or i in touched):
                continue
            if withdrawn and iid in waits:   # nothing to wait for any more
                waits.pop(iid)
                if not waits:
                    cur.pop("rewrite_for")
            cands = self._restore_candidates(i, cur, deep)
            if not cands:
                if withdrawn:   # never approved, and its instruction is withdrawn: withdrawn with it
                    cur["review_status"], cur["reject_reason"], cur["rejected_by"] = "rejected", f"{iid} withdrawn: {reason}", ev["actor"]
                    ev["reviewed"]["withdrawn"].append(i)
                    ev["needs_person"].append({"item_id": i, "why": [f"{iid} withdrawn: {reason}"]})
                continue
            src, cites, probs = self._first_fitting(cur, cands, also_for(cur))
            if probs:
                ev["needs_person"].append({"item_id": i, "why": [f"still waits for a person's rewrite after {iid} was rejected"] + probs})
                continue
            v = self._new_version(i, src["content"], cites, f"restored v{src.get('version')}: {iid} change rejected ({reason})", ev, method="restored")
            v["review_status"], v["restored_from"] = "approved", src.get("version")
            self._carry_labels(v, src)
            self.recompute_schedule(v)
            ev["reviewed"]["restored"].append(i)
            if self._on_behalf_only(v):
                ev["reviewed"].setdefault("restored_on_behalf", []).append(i)
        if not withdrawn:   # an item still waiting for this instruction waits for the condition and action it has now
            for vs in self.items.values():
                w = (vs[-1].get("rewrite_for") or {}).get(iid)
                for k, field in (("condition_to", "condition"), ("action_to", "action")):
                    if w and k in w and _text_key(w[k]) != _text_key(ins.get(field)):
                        w.pop(k)

    @staticmethod
    def _corrected_fields(t: str | None, cond: str | None, act: str | None, corr: dict) -> tuple:
        """(time, condition, action) of an instruction after a transcript correction of a sentence it rests on."""
        return corrected_time(t, corr), corrected_words(cond, corr), corrected_action(act, corr)

    @staticmethod
    def _corrected_time(t: str | None, corr: dict) -> str | None:
        """An instruction time as a transcript correction changed it (corrected_time): read from the corrected words of
        the clause that stated it, never from the first weekday and clock of the whole sentence."""
        return corrected_time(t, corr)

    def _reapply_corrections(self, state: dict) -> dict | None:
        """An instruction state (time, condition, action, cites) with the transcript corrections made since its cited
        revisions applied (corrected_time, corrected_words, corrected_action): when one of them changed what the state
        states, the state on the latest revision as corrected (with `_corrections`, the records applied); None when no
        correction since changed it (a wording correction leaves the state as it is: its items come back stale for a
        person, see README). A correction that cannot be applied to the state is left out (the fit check judges the result)."""
        fields = [k for k in ("time", "condition", "action") if k in state]
        vals, cites, used = {k: state.get(k) for k in fields}, [], []
        for c in state.get("cites") or []:
            latest = self.latest_revision(c["source_id"])
            later = [r for r in self.corrections if r["source_id"] == c["source_id"] and r["segment_id"] == c["segment_id"]
                     and REVISION_RX.match(str(c.get("revision"))) and int(r["base_revision"][1:]) >= int(c["revision"][1:])]
            now = dict(vals)
            for r in later:
                try:
                    t2, c2, a2 = self._corrected_fields(now.get("time"), now.get("condition"), now.get("action"), r)
                except ValueError:
                    continue
                now.update({k: x for k, x in (("time", t2), ("condition", c2), ("action", a2)) if k in fields})
            if later and now != vals and latest and self.segment_text(c["source_id"], latest, c["segment_id"]) is not None:
                vals, used = now, used + later
                cites.append({**c, "revision": latest})
            else:
                cites.append(c)
        return {**state, **vals, "cites": cites, "_corrections": used} if used else None

    @staticmethod
    def _same_state(a: dict, ins: dict) -> bool:
        key = lambda cs: [(c["source_id"], c.get("revision"), c["segment_id"]) for c in cs or []]  # noqa: E731
        same_time = canonical_time(a.get("time")) == canonical_time(ins.get("time")) if canonical_time(a.get("time")) else a.get("time") == ins.get("time")
        same_words = all(_text_key(a.get(k)) == _text_key(ins.get(k)) for k in ("condition", "action") if k in a)
        return same_time and same_words and key(a.get("cites")) == key(ins.get("cites"))

    def _restore_candidates(self, i: str, cur: dict, deep: bool = False) -> list[dict]:
        """The approved versions a rejection may bring back for item `i`, in the order they are tried: the current one when
        it was approved (stale where it is), else the last approved one. `deep` (a clinician rejected a state that was in
        force on the primary caregiver's confirmation): also the version a stale restored copy was restored from, then every
        earlier approved version newest first, so the clinician's own approved text is reached past the on-behalf ones."""
        if not deep:
            src = cur if self.was_approved(cur) else self.last_approved(i)
            return [src] if src is not None else []
        vs = {v.get("version"): v for v in self.items[i]}
        out = [cur] if self.was_approved(cur) else []
        rf = vs.get(cur.get("restored_from")) if cur.get("restored_from") else None
        out += [rf] if rf is not None and self.was_approved(rf) else []
        out += [v for v in reversed(self.items[i][:-1]) if self.was_approved(v)]
        seen, uniq = set(), []
        for v in out:
            if v.get("version") not in seen:
                seen.add(v.get("version"))
                uniq.append(v)
        return uniq

    def _first_fitting(self, cur: dict, cands: list[dict], also=()) -> tuple[dict, list[dict], list[str]]:
        """(version, cites, problems) of the first candidate that fits the case as it is now (_restore_problems); when none
        fits, the first candidate with its problems."""
        first = None
        for src in cands:
            cites, probs = self._restore_problems(cur, src, also=also)
            if not probs:
                return src, cites, []
            first = first or (src, cites, probs)
        return first

    def _send_back(self, i: str, iid: str, reason: str, probs: list[str], ev: dict, also=(), deep: bool = False) -> None:
        """An APPROVED version that no longer fits after `iid`'s change was rejected: its last approved text comes back
        approved when that fits (restored), else it goes stale where it is, for a person (restored_stale, with
        restore_problems and rewrite_for), so the export stays blocked until it is rewritten. `deep`: see
        _restore_candidates (every earlier approved version is tried, newest first)."""
        cur = self.latest(i)
        why = [f"v{cur.get('version')} no longer fits after {iid} was rejected: {p}" for p in probs]
        cands = [v for v in self._restore_candidates(i, cur, deep) if v is not cur] if deep else \
            [x for x in [self.last_approved(i)] if x is not None]
        last_ok = None
        if cands:
            last_ok, cites, p2 = self._first_fitting(cur, cands, also)
        if last_ok is not None:
            if not p2:
                v = self._new_version(i, last_ok["content"], cites, f"restored v{last_ok.get('version')}: v{cur.get('version')} no longer fits "
                                      f"({iid} change rejected: {reason})", ev, method="restored")
                v["review_status"], v["restored_from"] = "approved", last_ok.get("version")
                self._carry_labels(v, last_ok)
                self.recompute_schedule(v)
                ev["reviewed"]["restored"].append(i)
                if self._on_behalf_only(v):
                    ev["reviewed"].setdefault("restored_on_behalf", []).append(i)
                ev["needs_person"].append({"item_id": i, "why": why})
                return
        self._retire(cur, "stale")
        cur["restore_problems"] = list(probs)
        waits = self._waits_after_restore(cur, cur, cur.get("cites", []), ev, also=also)
        if waits:
            cur["rewrite_for"] = waits
        ev["reviewed"]["restored_stale"].append(i)
        ev["needs_person"].append({"item_id": i, "why": why})

    def _restore_bound(self, iid: str, v: dict) -> int:
        """The lowest version a rejected version's restored_from chain reaches (its own version without one): a clinician
        who rejects a version in force on the primary caregiver's confirmation goes back to an approved version older than
        it AND than the version it was restored from, so rejecting a restored on-behalf copy never brings the same content
        back again (no loop) and the clinician's own approved version is reached."""
        bound, seen, x = v.get("version", 0), set(), v
        while x and x.get("restored_from") and x["restored_from"] not in seen:
            seen.add(x["restored_from"])
            bound = min(bound, x["restored_from"])
            x = next((y for y in self.items[iid] if y.get("version") == x["restored_from"]), None)
        return bound

    def _withdraw_version(self, iid: str, reason: str, ev: dict, also=(), on_behalf: bool = False) -> None:
        """Reject an item's current version. The newest version a person really approved comes back as a new version:
        approved (restored) only when it fits the case as it is now (_restore_problems: fit_problems against the
        instructions both versions rest on and `also`), else stale (restored_stale) with `restore_problems` and
        `rewrite_for`, so it blocks the export until a person rewrites it. Without an approved version the item has no
        current content (rejected, withdrawn). Every rejected item is listed for a person. `on_behalf`: the rejected
        version was in force on the primary caregiver's confirmation; the version that comes back is older than it and
        than the version it was restored from (_restore_bound), so a clinician's rejections step back and end at the
        clinician's own approved version, never in a loop."""
        cur = self.latest(iid)
        bound = self._restore_bound(iid, cur) if on_behalf else None
        cur["review_status"], cur["reject_reason"], cur["rejected_by"] = "rejected", reason, ev["actor"]
        last_ok = self.last_approved(iid, before=bound)
        if last_ok is not None and last_ok.get("derived_from") and not self._active(last_ok["derived_from"]):
            last_ok = None   # it rests only on withdrawn instructions: nothing comes back, the item is withdrawn
        why = [f"rejected: {reason}"]
        if last_ok is not None:   # the previously approved content comes back as a new version with its own history line
            cites, probs = self._restore_problems(cur, last_ok, also=also)
            v = self._new_version(iid, last_ok["content"], cites, f"restored v{last_ok.get('version')}: v{cur.get('version')} rejected ({reason})",
                                  ev, method="restored")
            v["restored_from"] = last_ok.get("version")
            if probs:   # never approved with content that contradicts the case: a person rewrites it
                v["review_status"], v["restore_problems"] = "stale", list(probs)
                waits = self._waits_after_restore(cur, last_ok, cites, ev, also=also)
                if waits:
                    v["rewrite_for"] = waits
                ev["reviewed"]["restored_stale"].append(iid)
                why += [f"v{last_ok.get('version')} no longer fits the case: {p}" for p in probs]
            else:
                v["review_status"] = "approved"
                self._carry_labels(v, last_ok)
                ev["reviewed"]["restored"].append(iid)
                if self._on_behalf_only(v):
                    ev["reviewed"].setdefault("restored_on_behalf", []).append(iid)
            self.recompute_schedule(v)
        else:
            ev["reviewed"]["withdrawn"].append(iid)
        ev["needs_person"].append({"item_id": iid, "why": why})

    def _pending_ids(self) -> list[str]:
        ids = [i for i, v in self.items.items() if v[-1].get("review_status") == "pending_review"]
        return ids + [i for i, ins in self.instructions.items() if ins.get("derivation_status") == "pending_review"]

    def approve(self, ids: list[str], actor: str | None = None, at: str | None = None, request_id: str | None = None) -> dict | None:
        """With an actor: a review change_event (role care_team, approved-basis schedule moves, no case_version bump).
        Without one: the plain CaseStore.approve (unchanged behaviour)."""
        if actor is None:
            return super().approve(ids)
        return self.apply_change({"kind": "review", "decision": "approve", "ids": list(ids), "request_id": request_id, "at": at}, actor)

    def approve_all_pending(self, actor: str, at: str | None = None, request_id: str | None = None) -> dict:
        return self.apply_change({"kind": "review", "decision": "approve", "all": True, "request_id": request_id, "at": at}, actor)

    def reject(self, item_id: str, reason: str, actor: str, at: str | None = None, request_id: str | None = None) -> dict:
        return self.apply_change({"kind": "review", "decision": "reject", "id": item_id, "reason": reason, "request_id": request_id, "at": at}, actor)

    # ---------------------------------------------------------------- confirmation roles: the primary caregiver's fallback
    def confirm_on_behalf(self, ids: list[str], actor: str, at: str, request_id: str | None = None) -> dict:
        return self.apply_change({"kind": "review", "decision": "confirm_on_behalf", "ids": list(ids), "request_id": request_id, "at": at}, actor)

    def confirm_all_on_behalf(self, actor: str, at: str, request_id: str | None = None) -> dict:
        return self.apply_change({"kind": "review", "decision": "confirm_on_behalf", "all": True, "request_id": request_id, "at": at}, actor)

    def mark_clinician_unreachable(self, actor: str, reason: str, at: str, request_id: str | None = None) -> dict:
        return self.apply_change({"kind": "clinician_unreachable", "reason": reason, "request_id": request_id, "at": at}, actor)

    def clear_clinician_unreachable(self, actor: str, at: str | None = None, request_id: str | None = None) -> dict:
        return self.apply_change({"kind": "clinician_unreachable", "clear": True, "request_id": request_id, "at": at}, actor)

    def set_case_settings(self, actor: str, at: str | None = None, request_id: str | None = None, **settings) -> dict:
        return self.apply_change({"kind": "case_settings", **settings, "request_id": request_id, "at": at}, actor)

    def _confirm_on_behalf(self, change: dict, ev: dict) -> None:
        """The primary caregiver confirms pending versions on the clinician's behalf (review decision confirm_on_behalf).
        Each id needs a trigger (it waited longer than on_behalf_after_hours, or the clinician is marked unreachable), may
        not be clinician-only (on_behalf_exclusions) and must fit the case as it is now (the approve gate). Named ids are
        refused as a whole (PermissionError, or NotFit when every reason is the fit check; `.ids`, `.problems`), nothing
        changes; with 'all' the allowed ones are confirmed and the others listed in reviewed.refused, each version on its
        own, and nothing allowed at all is refused like named ids. A confirmed version is approved (in force: the approved
        schedule basis moves) and carries confirmed_on_behalf {by, trigger, reason, at, change_id, ...}: the label of the
        item's state, the change log, the handover view and the export. A clinician later confirms it (approve) or rejects it
        (reject, the normal path); a clinician's action also clears the unreachable mark."""
        at = _local_iso(change.get("at"), "an on-behalf confirmation's 'at' (the time it is confirmed; the server's clock)")
        self._require_primary(ev["actor"], ev["role"], "confirming on the clinician's behalf")
        if change.get("all") is not None and not isinstance(change.get("all"), bool):
            raise ValueError("'all' must be true or false")
        if change.get("all"):
            ids = self._pending_ids()
            if not ids:
                raise ConflictError("nothing is pending review: there is nothing to confirm on the clinician's behalf")
        else:
            ids = change.get("ids")
            if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
                raise ValueError("'ids' must be a non-empty list of item or instruction ids (or 'all': true)")
            unknown = [i for i in ids if i not in self.items and i not in self.instructions]
            if unknown:
                raise NotInCase(f"not in this case: {', '.join(unknown)}")
            not_pending = [i for i in ids if (self.latest(i).get("review_status") if i in self.items
                                              else self.instructions[i].get("derivation_status")) != "pending_review"]
            if not_pending:
                raise ConflictError(f"not pending review: {', '.join(not_pending)}")
        ids = list(dict.fromkeys(ids))
        judged = {i: self._on_behalf_judge(i, at) for i in ids}
        refused = {i: r for i, (_, r) in judged.items() if r}
        ok = [i for i in ids if i not in refused]
        if refused and (not change.get("all") or not ok):
            if all(x.startswith("no longer fits the case: ") for r in refused.values() for x in r):
                raise NotFit({i: [x[len("no longer fits the case: "):] for x in r] for i, r in refused.items()})
            err = PermissionError("not confirmed on the clinician's behalf, nothing changed: "
                                  + "; ".join(f"{i} ({', '.join(r)})" for i, r in sorted(refused.items())))
            err.ids, err.problems = sorted(refused), {i: list(r) for i, r in refused.items()}
            raise err
        super().approve(ok)
        confirmed = []
        for i in ok:
            trig = judged[i][0]
            cob = {"by": ev["actor"], "trigger": trig["trigger"], "reason": trig["reason"], "at": at, "change_id": ev["change_id"],
                   **{k: trig[k] for k in ("pending_since", "limit_hours", "marked_by", "marked_at") if k in trig}}
            cur = self._current(i)
            cur["confirmed_on_behalf"] = cob
            if i in self.items:
                cur["approved_by"] = ev["actor"]
            confirmed.append({"id": i, "trigger": cob["trigger"], "reason": cob["reason"]})
        ev["reviewed"] = {"decision": "confirm_on_behalf", "approved": sorted(ok), "rejected": [], "on_behalf": sorted(confirmed, key=lambda x: x["id"])}
        if refused:   # only 'all' gets here with refusals: they stay pending_review for the clinician, listed with their reasons
            ev["reviewed"]["refused"] = [{"item_id": i, "why": refused[i]} for i in sorted(refused)]

    def _change_clinician_unreachable(self, change: dict, ev: dict) -> None:
        """The primary caregiver marks the clinician unreachable, with a reason (required, one line, at most MAX_REASON
        characters, never a relaxing sentence), or clears the mark ('clear': true). While the mark stands, the primary
        caregiver may confirm pending changes on the clinician's behalf (labelled with the reason). A clinician's action
        clears it (apply_change); recorded only, no content changes."""
        clear = change.get("clear", False)
        if not isinstance(clear, bool):
            raise ValueError("'clear' must be true or false")
        if clear:
            if ev["role"] != CLINICIAN_ROLE:
                self._require_primary(ev["actor"], ev["role"], "clearing the clinician-unreachable mark")
            if not self.clinician_unreachable:
                raise ConflictError("the clinician is not marked unreachable")
            ev["clinician_unreachable"] = {"cleared": copy.deepcopy(self.clinician_unreachable), "by": ev["actor"], "at": change.get("at")}
            self.clinician_unreachable = None
            return
        self._require_primary(ev["actor"], ev["role"], "marking the clinician unreachable")
        at = _local_iso(change.get("at"), "a clinician-unreachable mark's 'at'")
        reason = _reason_text(change.get("reason"), "a clinician-unreachable mark")
        mark = {"by": ev["actor"], "reason": reason, "at": at, "change_id": ev["change_id"]}
        ev["clinician_unreachable"] = {"marked": mark, **({"replaces": copy.deepcopy(self.clinician_unreachable)} if self.clinician_unreachable else {})}
        self.clinician_unreachable = mark

    def _change_case_settings(self, change: dict, ev: dict) -> None:
        """A clinician sets the case's primary caregiver and/or the on-behalf time limit (on_behalf_after_hours). Recorded
        only, no content changes; changing them is clinician-only (PermissionError)."""
        if ev["role"] != CLINICIAN_ROLE:
            raise PermissionError(f"case settings (the primary caregiver, the on-behalf time limit) are set by a clinician; {ev['actor']} is {ev['role']}")
        if change.get("at") is not None:
            _local_iso(change.get("at"), "a case settings change's 'at'")
        fields = {k: v for k, v in change.items() if k not in ("kind", "request_id", "at")}
        if not fields:
            raise ValueError("a case_settings change names primary_caregiver and/or on_behalf_after_hours")
        ev["settings"] = self._apply_settings(fields, "case_settings")

    # ---------------------------------------------------------------- export (gate: nothing stale or pending)
    def export_pdf(self, pdf_id: str | None = None, at: str | None = None) -> dict:
        """The export gate. `pdf_id` is 'pdf-<label>' and new: an id that already exists (an item, or an earlier export
        that must stay byte-equal) is refused, never appended to."""
        if pdf_id is not None and not isinstance(pdf_id, str):
            raise ValueError("pdf_id must be a string such as 'pdf-v5'")
        pdf_id = pdf_id or f"pdf-v{self.case_version}"
        if pdf_id in self.items or pdf_id in self.instructions:
            kind = self.latest(pdf_id).get("kind") if pdf_id in self.items else "instruction"
            raise ConflictError(f"{pdf_id} already exists in this case ({kind.replace('_', ' ')}): choose another pdf_id"
                                + (" (an archived export is never overwritten)" if kind == "exported_pdf" else ""))
        if not re.fullmatch(r"pdf-[\w.-]{1,40}", pdf_id):
            raise ValueError("pdf_id must look like 'pdf-v5' (letters, digits, '.', '_' or '-' after 'pdf-')")
        blocking = [i for i, v in self.items.items() if v[-1].get("review_status") in ("stale", "pending_review")]
        blocking += [i for i, ins in self.instructions.items() if ins.get("derivation_status") == "pending_review"]
        if blocking:
            raise PendingReview(sorted(blocking))
        # defence in depth: an approved item that no longer fits the case as it is now is never exported
        unfit = {i: p for i, v in sorted(self.items.items()) if v[-1].get("kind") in CONTENT_KINDS and v[-1].get("review_status") == "approved"
                 for p in [self.fit_problems(v[-1])] if p}
        unfit.update({i: p for i in sorted(self.instructions) for p in [self.instruction_problems(i)] if p})
        if unfit:
            raise ExportBlocked(unfit)
        rec = self.export_pdf_record(pdf_id)
        rec["generated_at"], rec["seq"] = at, self.seq
        rec["schedule"] = [{k: r.get(k) for k in ("item_id", "version", "due_at", "assignee", "status", "content")}
                           for r in self.schedule() if r["review_status"] == "approved"]
        labels = [x for x in self._labels_view() if x["basis"] == "current"]
        if labels:   # confirmed on the clinician's behalf: the label is printed with the item and kept on the record
            by_id = {x["id"]: x["label"] for x in labels}
            for row in rec["schedule"]:
                if row["item_id"] in by_id:
                    row["confirmation"] = by_id[row["item_id"]]
            rec["confirmations"] = labels
        rec["content_hash"] = content_hash({"content": rec["content"], "schedule": rec["schedule"]})
        return rec

    def export_pdf_record(self, pdf_id: str) -> dict:
        """CaseStore's record, plus the visible label of every approved item (and instruction) confirmed by the primary
        caregiver on the clinician's behalf: '<item text> [confirmed by the primary caregiver on the clinician's behalf
        (...)]', and one line per such instruction. Without any on-behalf confirmation the content is CaseStore's."""
        rec = super().export_pdf_record(pdf_id)
        labels = {x["id"]: x["label"] for x in self._labels_view() if x["basis"] == "current"}
        if labels:
            lines = [self.latest(i)["content"] + (f" [{labels[i]}]" if i in labels else "") for i in self.items
                     if self.latest(i).get("kind") in CONTENT_KINDS and self.latest(i).get("review_status") == "approved"]
            for iid, ins in sorted(self.instructions.items()):
                if iid in labels:
                    what = "; ".join(x for x in (ins.get("action"), canonical_time(ins.get("time")) or ins.get("time"), ins.get("condition")) if x)
                    lines.append(f"Instruction {iid} ({what}) [{labels[iid]}]")
            rec["content"] = "\n".join(lines)
        return rec

    # ---------------------------------------------------------------- caregiver seen-state
    def mark_seen(self, actor: str, seq: int, case_version: int, at: str | None = None) -> dict:
        """Record how far a caregiver has read. seq and case_version are the values of the view they read: plain
        integers no further than the log (a value ahead of it would hide every later change from that caregiver)."""
        if not isinstance(actor, str) or not LABEL_RX.match(actor):
            raise ValueError("'actor' must be a short single-line label (at most 64 characters)")
        for name, value, now in (("seq", seq, self.seq), ("case_version", case_version, self.case_version)):
            if type(value) is not int or value < 0:
                raise ValueError(f"'{name}' must be a non-negative integer")
            if value > now:
                raise ValueError(f"'{name}' {value} is ahead of this case's log ({name} is {now} now)")
        self.seen[actor] = {"seq": seq, "case_version": case_version, "at": at}
        return dict(self.seen[actor])

    def changes_for(self, actor: str) -> dict:
        seen = self.seen.get(actor) or {"seq": 0, "case_version": 0, "at": None}
        cards = [e for e in self.change_events if e["seq"] is not None and e["seq"] > seen["seq"] and e["status"] in ("published", "review")]
        notes = [e for e in self.change_events if e["seq"] is not None and e["seq"] > seen["seq"] and e["status"] == "recorded_no_change"]
        if cards:
            banner = f"New changes to read: {len(cards)} update(s) since you last read (version {seen['case_version']})."
        else:
            banner = "You are up to date."
        if notes:
            banner += f" {_plural(len(notes), 'note')} recorded."
        labels = self._labels_view()
        waiting = [x["id"] for x in labels if x["awaiting_clinician"]]
        if waiting:   # in force on the primary caregiver's confirmation (also under a newer pending change): told every time
            banner += f" {_plural(len(waiting), 'item')} {ON_BEHALF_LABEL}, awaiting the clinician: {', '.join(waiting)}."

        def card(e):
            rv = e.get("reviewed") or {}
            # a rejection's card also lists what came back (restored, restored_stale) or went (withdrawn), with its label
            ids = sorted(set(e["impact_set"]) | {n["item_id"] for n in e["new_items"]} | set(rv.get("approved", [])) | set(rv.get("clinician_confirmed", []))
                         | set(rv.get("restored", [])) | set(rv.get("restored_stale", [])) | set(rv.get("withdrawn", [])))
            affected = [{"id": i, "review_status": (self.latest(i).get("review_status") if i in self.items else self.instructions[i].get("derivation_status")),
                         "version": self.latest(i).get("version") if i in self.items else None,
                         **({"confirmation": self.confirmation_label(i)} if self.confirmation_label(i) else {}),
                         **({"in_force_confirmation": self.in_force_label(i)} if self.in_force_label(i) else {})}
                        for i in ids if i in self.items or i in self.instructions]
            return {**{k: e.get(k) for k in ("change_id", "seq", "kind", "status", "notice", "impact_set", "schedule_diff", "new_items",
                                            "instruction_changes", "case_version_after", "source_added", "actor", "at")},
                    "unchanged_count": len(e.get("untouched_hashes") or {}), "affected": affected}
        out = {"actor": actor, "seen": dict(seen), "seq": self.seq, "case_version": self.case_version, "unread": bool(cards), "banner": banner,
               "events": [card(e) for e in cards],
               "recorded_only": [{k: e.get(k) for k in ("change_id", "seq", "kind", "status", "notice", "not_applied", "pending_changes")} for e in notes]}
        if labels:
            out["confirmations"] = labels
        return out

    # ---------------------------------------------------------------- plain-language notice (deterministic template)
    def _notice(self, ev: dict) -> str:
        """The notice body, then (only when it happened) the clinician-unreachable mark a clinician's action cleared."""
        out = self._notice_body(ev)
        m = ev.get("clinician_unreachable_cleared")
        if m:
            out += f" The clinician-unreachable mark ({m['by']}, {_fmt(m['at'])}) is cleared: a clinician acted."
        return out

    def _notice_body(self, ev: dict) -> str:
        kind, n = ev["kind"], ev["awaiting_review"]
        waiting = self.awaiting_clinician()
        tail = f" Items awaiting review: {n}." + (f" Confirmed on the clinician's behalf, awaiting the clinician: {len(waiting)}." if waiting else "")
        person = f" Items a person must rewrite: {', '.join(x['item_id'] for x in ev['needs_person'])}." if ev["needs_person"] else ""
        if ev["status"] == "refused":
            return (f"Generation started at case v{ev['job']['base_case_version']} arrived after v{ev['case_version_before']}: "
                    f"discarded, not published.")
        if kind in ("new_clinician_source", "late_upload"):
            return self._notice_source(ev) + person
        if kind == "transcript_correction":
            c = ev["correction"]
            actions = [self.instructions[ic["instruction_id"]].get("action") for ic in ev["instruction_changes"]]
            return (f"{correction_label(c['from'], actions)} corrected from {c['from']} to {c['to']} (transcript correction, checked "
                    f"against the recording).{tail}{person}")
        if kind == "family_statement":
            about = ev["pending_changes"][0].get("about_instruction")
            what = f" about {about} ({self.instructions[about]['action']})" if about else ""
            return (f"A family statement by {ev['actor']} was recorded as a conflict{what} for the care team. "
                    "No instruction, task or schedule changed.")
        if kind == "event_confirmation":
            e = ev["event"]
            when, day = _hm(e["occurred_at"]), _dm(e["occurred_at"])
            task = next((x for x in ev["new_items"] if x["item_id"].startswith("task-")), None)
            due = task["schedule"] if task else {}
            proposed = (f"1 handover note and 1 process task proposed (due {_fmt(due.get('due_at'))}, {due.get('assignee')}), "
                        f"1 question for the care team. Clinician instructions unchanged.{tail}")
            if "rejudged_from" in e:
                head = f"The {when} event on {day} was re-judged as {e['human_label'].replace('_', ' ')} by {ev['actor']}: "
                if e["human_label"] != "fall":
                    return head + f"the fall note and the process task are withdrawn (awaiting review). Clinician instructions unchanged.{tail}"
                if task:
                    return head + proposed
                return head + f"the fall note and the process task are re-confirmed (awaiting review), 1 question for the care team. Clinician instructions unchanged.{tail}"
            if e["human_label"] != "fall":
                return f"No fall at {when} on {day} confirmed by {ev['actor']}: recorded, nothing changed."
            return f"Fall at {when} on {day} confirmed by {ev['actor']} (clip {self.sources[(e['source_id'], 'r1')].get('input_id')}): " + proposed
        if kind == "generation_delivery":
            nv = ev["new_versions"][0]
            return (f"Late generation job {ev['job']['job_id']} for {nv['item_id']} published as version {nv['version']} "
                    f"(started at case version {ev['job']['base_case_version']}, still current).{tail}")
        if kind == "clinician_unreachable":
            c = ev["clinician_unreachable"]
            if "cleared" in c:
                return (f"The clinician-unreachable mark ({c['cleared']['by']}, {_fmt(c['cleared']['at'])}) was cleared by {ev['actor']}. "
                        "Nothing else changed.")
            mk = c["marked"]
            return (f"{mk['by']} (primary caregiver) marked the clinician unreachable at {_fmt(mk['at'])}: \"{mk['reason']}\". Changes already pending "
                    f"at {_fmt(mk['at'])} may now be {ON_BEHALF_LABEL}, labelled: an appointment move, a new instruction to attend an appointment or to "
                    "bring a document or an aid, their items and the fall note; medications, doses and conditions stay with the clinician. "
                    "Nothing else changed.")
        if kind == "case_settings":
            st = ev["settings"]
            bits = ([f"primary caregiver {st['primary_caregiver']['to']} (was {st['primary_caregiver']['from'] or 'none'})"] if "primary_caregiver" in st else []) + \
                   ([f"on-behalf time limit {st['on_behalf_after_hours']['to']} h (was {st['on_behalf_after_hours']['from']} h)"] if "on_behalf_after_hours" in st else [])
            return f"Case settings changed by {ev['actor']}: {'; '.join(bits)}." if bits else f"Case settings confirmed by {ev['actor']}: nothing changed."
        if kind == "review":
            r = ev["reviewed"]
            moves = [f"{d['item_id']} {_fmt(d['due_at_to'], True)} ({d['assignee_to']}; was {_fmt(d['due_at_from'], True)}, {d['assignee_from']})"
                     for d in ev["schedule_diff"] if d["basis"] == "approved"]
            now = f" Now in force: {'; '.join(moves)}." if moves else ""
            if r["decision"] == "confirm_on_behalf":
                groups: dict[str, list[str]] = {}
                for x in r["on_behalf"]:
                    why = f"time limit: pending longer than {self.on_behalf_after_hours} h" if x["trigger"] == "time_limit" else f"clinician unreachable: \"{x['reason']}\""
                    groups.setdefault(why, []).append(x["id"])
                left = (f" Left for the clinician: {', '.join(x['item_id'] + ' (' + self._refusal_kind(x['why']) + ')' for x in r['refused'])}."
                        if r.get("refused") else "")
                if len(groups) == 1:
                    (why, ids), = groups.items()
                    head = f"{ON_BEHALF_LABEL[:1].upper()}{ON_BEHALF_LABEL[1:]} ({ev['actor']}; {why}): {len(ids)} item(s) ({', '.join(ids)})."
                else:
                    head = (f"{ON_BEHALF_LABEL[:1].upper()}{ON_BEHALF_LABEL[1:]} ({ev['actor']}): {len(r['approved'])} item(s); "
                            + "; ".join(f"{why}: {', '.join(ids)}" for why, ids in groups.items()) + ".")
                return f"{head} Each is labelled until a clinician confirms or rejects it.{now}{left}{tail}"
            if r["decision"] == "reject":
                ob = r.get("restored_on_behalf") or []
                plain = [x for x in r.get("restored") or [] if x not in ob]
                fixed = [ic for ic in ev["instruction_changes"] if ic["change"] == "rejected_restored_corrected"]
                outcome = "".join(f" {ic['instruction_id']} is back on its approved source with the transcript correction "
                                  f"{', '.join(c['new_revision'] for c in ic['corrected_by'])} applied ({ic['time']}), awaiting review."
                                  for ic in fixed) + \
                          (f" Back to the approved version: {', '.join(plain)}." if plain else "") + \
                          (f" Back to the version {ON_BEHALF_LABEL} (not by a clinician; still awaiting the clinician): "
                           f"{', '.join(ob)}." if ob else "") + \
                          (f" Back to the last approved text, which no longer fits the case (stale): a person must rewrite "
                           f"{', '.join(r['restored_stale'])}." if r.get("restored_stale") else "") + \
                          (f" Withdrawn, {'no earlier approved version to go back to' if r.get('on_behalf_rejected') else 'never approved'}: "
                           f"{', '.join(r['withdrawn'])}." if r.get("withdrawn") else "")
                was = f" It had been {ON_BEHALF_LABEL}." if r.get("on_behalf_rejected") else ""
                return f"Rejected by {ev['actor']}: {r['rejected'][0]} ({r['reason']}).{was}{outcome}{tail}"
            refused = (f" Not approved, no longer fits the case (reject it or deliver a rewrite): {', '.join(x['item_id'] for x in r['refused'])}."
                       if r.get("refused") else "")
            cc = r.get("clinician_confirmed") or []
            if cc and not r["approved"]:
                return (f"Clinician-confirmed by {ev['actor']}: {len(cc)} item(s) ({', '.join(cc)}), earlier {ON_BEHALF_LABEL}.{now}{refused}{tail}")
            upgraded = f" Clinician-confirmed, earlier {ON_BEHALF_LABEL}: {', '.join(cc)}." if cc else ""
            return f"Approved by {ev['actor']}: {len(r['approved'])} item(s) ({', '.join(r['approved'])}).{upgraded}{now}{refused}{tail}"
        return f"Change {ev['change_id']} ({kind}) recorded.{tail}"

    @staticmethod
    def _refusal_kind(why: list[str]) -> str:
        """A short word for why an on-behalf confirmation was refused (the full reasons are in reviewed.refused)."""
        kinds = [k for k, p in (("clinician-only", "clinician-only: "), ("no trigger yet", "no trigger: "), ("no longer fits", "no longer fits the case: "))
                 if any(w.startswith(p) for w in why)]
        return ", ".join(kinds) or "refused"

    def _notice_source(self, ev: dict) -> str:
        """'<Label> moved from A to B (source, recorded, verified). Also new: ... The appointment is now on X's shift
        (...). Items awaiting review: N.' Sentences come from the event's own fields, in a fixed order."""
        src, n = ev["source_added"], ev["awaiting_review"]
        moved, shifts, kept = [], [], []
        what = "new clinician recording" if src["source_type"] == "clinician_recording" else "new clinician text"
        for ic in ev["instruction_changes"]:
            ins = self.instructions[ic["instruction_id"]]
            if ic["change"] == "superseded_by_new_source":
                seg = self.sources[(src["transcript"], src["revision"])]["segments"][ic["cites"][0]["segment_id"]]
                by = f"verified by {seg['verified_by']}" if seg.get("verified_by") else "the clinician's own text"
                origin = f"({what} {src['source_id']}, recorded {_fmt(src['recorded_at'])}; sentence {by})."
                if ic["time_from"] != ic["time_to"]:
                    # the time it moves from was in force on the primary caregiver's confirmation only: said, not hidden
                    ob = f" ({ON_BEHALF_LABEL}, not yet by the clinician)" if self._on_behalf_only(ins.get("previous")) \
                        and ins["previous"].get("time") == ic["time_from"] else ""
                    moved.append(f"{action_label(ins['action'])} moved from {ic['time_from']}{ob} to {ic['time_to']} {origin}")
                if "condition_to" in ic:
                    moved.append(f"{action_label(ins['action'])} condition changed from '{ic['condition_from'] or 'none'}' to '{ic['condition_to']}' {origin}")
                if "action_to" in ic:
                    moved.append(f"Action of {ic['instruction_id']} changed from '{ic['action_from']}' to '{ic['action_to']}' {origin} A person "
                                 "rewrites every item resting on it.")
                task = self._task_of(ic["instruction_id"])
                d = next((x for x in ev["schedule_diff"] if x["item_id"] == task and x["basis"] == "proposed"), None)
                noun = "appointment" if "appointment" in ins["action"] else "task"
                if d and d["assignee_from"] != d["assignee_to"]:
                    shifts.append(f"The {noun} is now on {d['assignee_to']}'s shift ({_fmt(d['due_at_to'], True)}; was "
                                  f"{_fmt(d['due_at_from'], True)}, {d['assignee_from']}).")
                elif d:
                    shifts.append(f"The {noun} stays on {d['assignee_to']}'s shift ({_fmt(d['due_at_to'], True)}; was {_fmt(d['due_at_from'], True)}).")
            elif ic["change"] == "reaffirmed_no_time":
                kept.append(f"{src['source_id']} mentions '{ins['action']}' but gives no time: the time {ic['time']} is kept and a question "
                            "was opened for the care team.")
            elif ic["change"] == "reaffirmed_same_time":
                settled = [p["pending_id"] for p in ev["pending_changes"] if p.get("status") == "resolved"]
                kept.append(f"{src['source_id']} confirms '{ins['action']}'" + (f" at {ic['time']}" if ic["time"] else "") + ": nothing changed"
                            + (f"; the open conflict {', '.join(settled)} is resolved." if settled else "."))
        new = [self.instructions[ic["instruction_id"]]["action"] for ic in ev["instruction_changes"] if ic["change"] == "new"]
        parts = moved + ([f"Also new: {', '.join(new)}."] if new else []) + shifts + kept
        for na in ev["not_applied"]:
            parts.append(f"{src['source_id']} was recorded earlier ({_fmt(na['recorded_at'])}) than the source of the current arrangement "
                         f"({_fmt(na['current_source']['recorded_at'])}): kept as history, nothing changed.")
        if not parts:
            parts.append(f"{src['source_id']} was stored; no instruction changed.")
        return " ".join(parts) + (f" Items awaiting review: {n}." if ev["status"] == "published" else "")
