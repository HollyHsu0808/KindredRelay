#!/usr/bin/env python3
"""External-reference evaluation of the family timeline's extractor against clinician-written notes (PriMock57).

Protocol: research/primock_gold_v1/PROTOCOL.md; labels: research/primock_gold_v1/ANNOTATION_GUIDE.md; frozen settings
and hashes: research/primock_gold_v1/preregistration.json, written by `prereg` before any live call (a live `run`
refuses without it, or when the protocol, the guide, the annotator prompts or the analysis settings no longer hash as
preregistered). One case is one PriMock57 consultation (mock primary-care consultations, actors, CC BY 4.0):

- System under test: the production extractor, episode.llm_extractor over llm_client.OpenAIChat.chat with the release
  settings of deploy/release.env.example (DeepSeek-V4-Flash, prompted JSON, max_tokens 2000 as ui/pages/
  1_Family_timeline.py asks for, verifier off), called through scripts/bench_tf_handover.py's instrumented HTTP layer
  (Session, InstrumentedChat, Redactor: the key is redacted from every record and output). The consultation's human
  reference transcript (both channels, parsed by primock_transcript_segments.parse_textgrid) becomes speaker-labelled
  turns ("Doctor: ...", "Patient: ...", consecutive segments of one speaker joined, PriMock markup removed), cut into
  consecutive updates of at most CHUNK_CHARS characters (never inside a turn); each update is added to one Episode with
  Episode.add_update(update, extractor=llm_extractor(client)), so episode.grounding_problem accepts or rejects every
  quote. The accepted facts are what the system shows; they are what is annotated.
- Reference: the consulting clinician's note, split into atomic note facts by fixed rules (split_note).
- Annotator: a model of another family than the generator (DeepSeek) and the cross-check judge (Gemma):
  Qwen3.8-Flash-Next (thinking off) if the endpoint lists it, else MiMo-V2.6-Flash. Blind to what produced the facts
  (no system or model is named; the facts are shown in a seeded random order under neutral ids). Task A labels every
  note fact covered / not_covered by the accepted facts; task B labels every accepted fact consistent / contradicts /
  not_in_note (not in note is not wrong: the note is a summary) with an error type.
- Metrics (per consultation, pooled over consultations with a seeded cluster bootstrap): note-fact recall, contradiction
  rate, severity-weighted error score (errors per note fact), grounding-check pass rate; error taxonomy counts.
- Human agreement sample: a seeded 20% of the annotator's decisions in OUT/human_review.csv (empty human_label);
  `kappa --csv` computes Cohen's kappa and raw agreement once a person fills it.

Consultations run in a seeded random order, so a run stopped by --max-calls has done a random subset. Every HTTP
attempt counts against --max-calls; `run --resume OUT` continues. Calls wait while release/benchmarks/
.load_test_running exists. --dry-run uses a deterministic scripted transport (no network, no model; harness check only).

Usage:
  python -I scripts/primock_gold_eval.py prereg
  python -I scripts/primock_gold_eval.py split --note data/raw/primock57/notes/day1_consultation04.json
  python -I scripts/primock_gold_eval.py run --raw data/raw/primock57 --consultations day1_consultation04 \\
      --api-key-file KEYFILE --max-calls 20 --out release/benchmarks/primock_gold_<UTC>
  python -I scripts/primock_gold_eval.py run --raw data/raw/primock57_full --api-key-file KEYFILE --max-calls 360
  python -I scripts/primock_gold_eval.py run --resume OUT --api-key-file KEYFILE --max-calls 50
  python -I scripts/primock_gold_eval.py report --out OUT
  python -I scripts/primock_gold_eval.py kappa --csv OUT/human_review.csv

Exit codes: 0 complete, 3 stopped at --max-calls (resume it), 130 interrupted, 2 usage problem. Stdlib only.
"""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))   # explicit: the script also runs with python -I
import bench_tf_handover as B  # noqa: E402  (adds handoff_day1/agent to sys.path)
from episode import FACT_FIELDS, Episode, llm_extractor, norm  # noqa: E402
from primock_transcript_segments import parse_textgrid  # noqa: E402

SCHEMA_VERSION = "kindredrelay-primock-gold-v1"
PREREG_SCHEMA = "kindredrelay-primock-gold-v1-preregistration"
PROTOCOL_DIR = ROOT / "research" / "primock_gold_v1"
PREREG = PROTOCOL_DIR / "preregistration.json"
AMENDMENT = PROTOCOL_DIR / "preregistration_amendment_1.json"   # the full run's seeded subset, fixed before its calls
PROTOCOL = PROTOCOL_DIR / "PROTOCOL.md"
GUIDE = PROTOCOL_DIR / "ANNOTATION_GUIDE.md"
LOAD_TEST_FLAG = ROOT / "release" / "benchmarks" / ".load_test_running"
PILOT_CONSULTATION = "day1_consultation04"

GENERATOR_MODEL = "DeepSeek-V4-Flash"   # deploy/release.env.example CARERELAY_LLM_MODEL
GENERATOR = {"model": GENERATOR_MODEL, "max_tokens": B.PAGE_MAX_TOKENS, "guided_json": False, "extra_body": {},
             "temperature": 0.0, "seed": 0, "timeout_s": 120.0, "timeout_retries": 0,
             "evidence_verifier": "off (KINDRED_VERIFIER_MODE=off, deploy/release.env.example)"}
ANNOTATORS = (("Qwen3.8-Flash-Next", {"chat_template_kwargs": {"enable_thinking": False}}),
              ("MiMo-V2.6-Flash", {}))   # first one the endpoint lists; neither DeepSeek (generator) nor Gemma (judge)
ANNOTATOR = {"max_tokens": 4096, "guided_json": False, "temperature": 0.0, "seed": 0, "timeout_s": 240.0,
             "timeout_retries": 1}
MAX_TRIES, MAX_WAIT_S = 6, 60.0
CHUNK_CHARS = 3000
ANCHOR_AT = dt.datetime(2026, 1, 5, 9, 0, tzinfo=dt.timezone.utc)   # placeholder: a note has no date (London = UTC in Jan)
UPDATE_SPEAKER = "a doctor and a patient in a recorded primary-care consultation"
SCENARIO = {"patient": {"name": "PriMock57 mock patient (an actor)", "timezone": "Europe/London"}, "members": [],
            "updates": []}
SEVERITY = {"critical": 5, "major": 3, "minor": 1}
ERROR_CLASSES = {"negation_polarity": "critical", "dose_number": "critical", "attribution_speaker": "major",
                 "temporal": "major", "other_contradiction": "major", "omission_safety_net": "major",
                 "omission_other": "minor"}
COMMISSION = ("negation_polarity", "dose_number", "attribution_speaker", "temporal", "other_contradiction")
LABELS = {"A": ("covered", "not_covered"), "B": ("consistent", "contradicts", "not_in_note")}
ERROR_TYPES = ("none",) + COMMISSION
ORDER_SEED = SHUFFLE_SEED = HUMAN_SEED = BOOTSTRAP_SEED = 20261018
BOOTSTRAP_RESAMPLES, BOOTSTRAP_MIN_N = 2000, 5
HUMAN_FRACTION = 0.20
NOTE_SPLITTER = "primock-note-split-v1"
CALL_CAP_TOTAL = 400
EXIT_OK, EXIT_USAGE, EXIT_PARTIAL, EXIT_INTERRUPTED = 0, 2, 3, 130
DEVIATIONS = (   # changes after the preregistration (2026-10-17T23:36:28Z), with their reason; prompts and analysis unchanged
    "2026-10-17T23:42Z, after the pilot: added run --deadline-utc (start no consultation that would likely end after "
    "it; stopped_reason 'deadline'). Harness only. Reason: the pilot took about 4.5 minutes per consultation with "
    "sequential calls, so a full run of 57 may not finish before the results deadline; the seeded processing order "
    "keeps a stopped run a random subset, as the protocol states.",
    "2026-10-17T23:44Z, before the full run: a consultation whose note yields no note fact or whose transcripts yield "
    "no turn (unreadable data) is skipped and listed in results.data.skipped instead of being scored as all omissions. "
    "Harness only (a data guard); it does not change any consultation that has a note and a readable transcript.",
    "2026-10-17T23:54Z, before the full run: code fix to match the preregistered PROTOCOL.md: recall and the task B "
    "rates now count the labelled items of an incomplete annotation (the code had left such consultations out); the "
    "weighted score still uses consultations with both tasks complete. No effect on the pilot (both tasks complete).",
    "2026-10-17T23:55Z, before the full run: a reply cut off at max_tokens (or not one whole JSON object) is no longer "
    "dropped whole: its complete label items are recovered (salvage_items) and count, as PROTOCOL.md says the "
    "labelled items of an incomplete annotation do; the task stays incomplete. Reason: the pilot's task B reply used "
    "3331 of the 4096 output tokens for 52 facts, so a longer consultation would be cut off.",
    "2026-10-18T00:28Z, before any live call of the full run: the full data arrived at 00:25Z; 57 consultations at "
    "about 4 minutes each, sequential, would not finish before the 03:30Z results deadline, so a seeded random subset "
    "of 30 (the first 30 of the preregistered processing order) was fixed in preregistration_amendment_1.json "
    "(`amend`, then `run --amendment`), with a deadline stop at 03:10Z.",
    "2026-10-18T02:30Z, after the full run, offline: the reader of annotator replies missed replies PROTOCOL.md says "
    "count: one that is invalid JSON only because of a raw line break inside a string (llm_client then returned one "
    "inner item, and every id counted as missing). read_reply now salvages any reply that is not one object with a "
    "labels list (strict=False decoding, else item by item); the task stays incomplete. `report --reparse` applies it "
    "to the stored replies (no call) and writes results_reparsed.json and summary_reparsed.md beside the as-run "
    "results.json and summary.md. Items whose id key is garbled (a token glitch) are not reinterpreted: they stay "
    "unknown ids, as preregistered.",
)
SOURCES = ("handoff_day1/agent/episode.py", "handoff_day1/agent/episode_events.py", "handoff_day1/agent/llm_client.py",
           "scripts/bench_tf_handover.py", "scripts/primock_transcript_segments.py", "scripts/primock_gold_eval.py",
           "research/primock_gold_v1/PROTOCOL.md", "research/primock_gold_v1/ANNOTATION_GUIDE.md")
ATTRIBUTION = """PriMock57 - Korfiatis et al., 2022; released by Babylon Health.
Official source: https://github.com/babylonhealth/primock57
Licence: Creative Commons Attribution 4.0 International (https://creativecommons.org/licenses/by/4.0/).
Original licence: data/raw/primock57/LICENSE.md
Papers: PriMock57: A Dataset Of Primary Care Mock Consultations (ACL 2022, arXiv:2204.00333); Human Evaluation and
Correlation with Automatic Metrics in Consultation Note Generation (ACL 2022, arXiv:2204.00447).

Material derived from PriMock57 in this folder (records.jsonl, results.json, summary.md, human_review.csv,
human_review_context.md): excerpts of the consultation notes written by the consulting clinicians and of the manual
transcripts. Changes: the transcripts' PriMock markup was removed, consecutive segments of one speaker were joined into
speaker-labelled turns and cut into consecutive parts; the notes were split into atomic note facts by fixed rules
(scripts/primock_gold_eval.py split_note); facts were extracted and labelled by language models as described in
research/primock_gold_v1/PROTOCOL.md. These are simulated consultations with actors, not real patients.
"""


class UsageError(Exception):
    """A problem with the command line, the preregistration or the data; nothing was sent."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------------------- the note
HEADER_RE = re.compile(
    r"^\s*(?P<h>PC|HPC|HPI|PMHx?|PSHx?|DHx?|Meds|Medications?|Drug history|Allerg(?:y|ies)|FHx?|Family history|SHx?|"
    r"Social history|ICE|O/E|OE|Exam(?:ination)?|Obs|Ix|Investigations?|Imp(?:ression)?|Diagnosis|Dx|DDx|Assessment|"
    r"Plan|Mx|Management|Safety[- ]?net(?:ting)?|ROS|Systems review)\s*(?::|-|–)\s*", re.I)
SECTIONS = {"history": ("pc", "hpc", "hpi", "ros", "systems review"), "pmh": ("pmh", "pmhx", "psh", "pshx"),
            "medications": ("dh", "dhx", "meds", "medication", "medications", "drug history"),
            "allergies": ("allergy", "allergies"), "family_history": ("fh", "fhx", "family history"),
            "social_history": ("sh", "shx", "social history"), "ice": ("ice",),
            "examination": ("o/e", "oe", "exam", "examination", "obs"),
            "investigations": ("ix", "investigation", "investigations"),
            "impression": ("imp", "impression", "diagnosis", "dx", "ddx", "assessment"),
            "plan": ("plan", "mx", "management", "safety net", "safety-net", "safetynet", "safety netting",
                     "safety-netting", "safetynetting")}
LIST_MARK = re.compile(r"^\s*(?:\d+[.)]|[-•*–])\s*")
ALLERGY_LINE = re.compile(r"^\s*(?:NKDA|NKA|no known (?:drug )?allergies)\b", re.I)
ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "e.g", "i.e", "eg", "ie", "approx", "vs", "etc"}
CONDITIONAL = re.compile(r"\b(?:if|unless|in case|should)\b", re.I)
SAFETY_NET = re.compile(
    r"red[- ]?flag|safety[- ]?net|\bINB\b|\bif\b[^.]*?\b(?:no better|not better|not improv\w*|no improvement|worse\w*|"
    r"worsen\w*|deteriorat\w*|persist\w*|present|develop\w*|recur\w*|concern\w*)\b|\burgent\w*|\bA&E\b|\bA and E\b|"
    r"\b999\b|\b111\b|\bemergency\b|\bseek\w* (?:urgent |medical |immediate )?(?:help|advice|attention|review|care)\b|"
    r"\b(?:return|come back|call back|re-?contact|rebook|get back)\w*\b[^.]*?\bif\b", re.I)


def section_of(header: str) -> str:
    h = re.sub(r"\s+", " ", header.strip().lower())
    for name, keys in SECTIONS.items():
        if h in keys:
            return name
    return "history"


def sentences(line: str) -> list[str]:
    """Split at . ! ? ; followed by a space or the end, except after a listed abbreviation (Dr., e.g., ...)."""
    out, start = [], 0
    for m in re.finditer(r"[.!?;](?=\s|$)", line):
        prev = re.search(r"([A-Za-z.]+)$", line[start:m.start()])
        if m.group() == "." and prev and prev.group(1).lower().rstrip(".") in ABBREVIATIONS:
            continue
        out.append(line[start:m.end()])
        start = m.end()
    out.append(line[start:])
    return [s.strip() for s in out if s.strip()]


def clauses(sentence: str) -> list[str]:
    """Split at commas outside brackets (not inside a number such as 1,000); a clause with a conditional word (if,
    unless, in case, should) is joined to the next clause, or to the previous one when it is the last."""
    parts, depth, cur = [], 0, []
    for i, ch in enumerate(sentence):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if (ch == "," and depth == 0 and not (0 < i < len(sentence) - 1 and sentence[i - 1].isdigit()
                                               and sentence[i + 1].isdigit())):
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    parts = [p.strip() for p in parts if re.search(r"[A-Za-z0-9]", p)]
    out: list[str] = []
    carry = None
    for p in parts:
        if carry is not None:
            p, carry = f"{carry}, {p}", None
        if CONDITIONAL.search(p):
            carry = p
            continue
        out.append(p)
    if carry is not None:
        if out:
            out[-1] = f"{out[-1]}, {carry}"
        else:
            out.append(carry)
    return out


def tidy(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" \t.;:,-–")


def split_note(note: str) -> list[dict]:
    """The note's atomic facts, by fixed rules (NOTE_SPLITTER; PROTOCOL.md "Note facts"): a header (PMH:, DH:, FH:, SH:,
    Imp:, Plan:, ...) sets the section until the next header (before any header: history); each line is one or more
    facts; list numbering and bullets are dropped; a line splits into sentences, a sentence into comma clauses
    (clauses()). Each fact keeps the sentence it came from (context) and a safety_net flag (SAFETY_NET regex)."""
    section, facts = "history", []
    for raw in (note or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = HEADER_RE.match(line)
        if m:
            section = section_of(m.group("h"))
            line = line[m.end():].strip()
            if not line:
                continue
        line_section = "allergies" if ALLERGY_LINE.match(line) else section
        line = LIST_MARK.sub("", line, count=1).strip()
        for sent in sentences(line):
            for clause in clauses(sent):
                text = tidy(clause)
                if not re.search(r"[A-Za-z0-9]", text):
                    continue
                facts.append({"nid": f"N{len(facts) + 1:02d}", "section": line_section, "text": text,
                              "context": tidy(sent), "safety_net": bool(SAFETY_NET.search(clause))})
    return facts


# ---------------------------------------------------------------------------------------------------------- transcript
TAG = re.compile(r"</?[A-Za-z_]+/?>")


def clean_text(text: str) -> str:
    """PriMock markup removed (<UNSURE>x</UNSURE> keeps x; <INAUDIBLE_SPEECH/>, <UNIN/> go), whitespace collapsed."""
    return re.sub(r"\s+", " ", TAG.sub("", text or "")).strip()


def load_segments(raw: Path, cid: str) -> list[dict]:
    """Both channels of one consultation, chronological, with the segment ids primock_transcript_segments.py gives."""
    segs = []
    for role in ("doctor", "patient"):
        _, part = parse_textgrid(raw / "transcripts" / f"{cid}_{role}.TextGrid")
        for s in part:
            s["speaker"] = role   # the channel's filename names the role (tiers may be called "Speaker")
        segs.extend(part)
    segs.sort(key=lambda s: (s["start_s"], s["speaker"]))
    for i, s in enumerate(segs):
        s["segment_id"] = f"{cid}_seg{i:03d}"
    return segs


def build_turns(segments: list[dict]) -> list[dict]:
    """Consecutive segments of one speaker form one turn; segments with no word left after the markup is removed
    (e.g. <INAUDIBLE_SPEECH/>) are dropped."""
    turns: list[dict] = []
    for s in segments:
        text = clean_text(s.get("text", ""))
        if not re.search(r"[A-Za-z0-9]", text):
            continue
        if turns and turns[-1]["speaker"] == s["speaker"]:
            t = turns[-1]
            t["text"] = f"{t['text']} {text}"
            t["end_s"] = max(t["end_s"], s["end_s"])
            t["segment_ids"].append(s["segment_id"])
        else:
            turns.append({"speaker": s["speaker"], "start_s": s["start_s"], "end_s": s["end_s"], "text": text,
                          "segment_ids": [s["segment_id"]]})
    return turns


def turn_line(t: dict) -> str:
    return f"{t['speaker'].title()}: {t['text']}"


def chunk_turns(turns: list[dict], limit: int = CHUNK_CHARS) -> list[list[dict]]:
    """Consecutive turns, at most limit characters of text per part (lines joined by newlines); a turn is never cut, so
    one longer turn is a part of its own."""
    chunks, cur, size = [], [], 0
    for t in turns:
        n = len(turn_line(t))
        if cur and size + 1 + n > limit:
            chunks.append(cur)
            cur, size = [], 0
        size += n + (1 if cur else 0)
        cur.append(t)
    if cur:
        chunks.append(cur)
    return chunks


def make_updates(cid: str, turns: list[dict], limit: int = CHUNK_CHARS) -> list[dict]:
    out = []
    for k, part in enumerate(chunk_turns(turns, limit), 1):
        at = ANCHOR_AT + dt.timedelta(seconds=int(part[0]["start_s"]))
        out.append({"update_id": f"{cid}_part{k:02d}", "at": at.isoformat(), "kind": "recording",
                    "speaker": UPDATE_SPEAKER, "speaker_type": "care_team",
                    "text": "\n".join(turn_line(t) for t in part),
                    "segment_ids": [s for t in part for s in t["segment_ids"]],
                    "start_s": part[0]["start_s"], "end_s": max(t["end_s"] for t in part)})
    return out


def quote_speakers(quote: str, text: str) -> str:
    """Who said the words a fact quotes: the speakers of the update's lines that the quote overlaps (norm() joins lines
    with one space, as the grounding check reads the update)."""
    spans, pos, normed = [], 0, []
    for line in text.splitlines():
        n = norm(line)
        if not n:
            continue
        spans.append((pos, pos + len(n), line.split(":", 1)[0].strip().lower()))
        normed.append(n)
        pos += len(n) + 1
    joined = " ".join(normed)
    q = norm(quote or "").strip(" .,;:!?")
    found = set()
    for m in re.finditer(re.escape(q), joined) if q else ():
        found |= {sp for a, b, sp in spans if a < m.end() and m.start() < b}
    return "+".join(sorted(found)) or "unknown"


def discover(raw: Path) -> list[str]:
    notes = raw / "notes"
    if not notes.is_dir():
        raise UsageError(f"no notes folder in {raw}")
    return sorted(p.stem for p in notes.glob("*.json")
                  if (raw / "transcripts" / f"{p.stem}_doctor.TextGrid").is_file()
                  and (raw / "transcripts" / f"{p.stem}_patient.TextGrid").is_file())


def load_note(raw: Path, cid: str) -> dict:
    obj = json.loads((raw / "notes" / f"{cid}.json").read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or not isinstance(obj.get("note"), str):
        raise UsageError(f"{cid}: the note file has no note text")
    return obj


def processing_order(ids: list[str]) -> list[str]:
    order = sorted(ids)
    random.Random(f"{ORDER_SEED}:order").shuffle(order)
    return order


# ---------------------------------------------------------------------------------------------------------- annotator
ANNOTATOR_SYSTEM = (
    "You are a careful annotator. You compare two independent records of the same mock primary-care consultation "
    "(actors, not real patients): the clinician's own note, and a list of candidate facts that an unnamed process "
    "derived from the consultation's transcript. You only label; you give no medical advice and judge nothing about "
    "the patient. Follow the definitions exactly. Reply with one JSON object only.")
TASK_A = (
    "TASK A - is each NOTE FACT covered by the CANDIDATE FACTS?\n"
    "Labels (exactly one per note fact):\n"
    "- covered: one or more candidate facts, read together, state the note fact's clinical content (the same symptom, "
    "finding, negative finding, history item, impression or plan item). Wording may differ; read clinical "
    "abbreviations as clinicians do (4/7 = four days, hx = history, sx = symptoms, SOB = shortness of breath, NKDA = "
    "no known drug allergies, PMH = past medical history, DH = drug history, FH = family history, SH = social history, "
    "Imp = impression, mx = management, INB = if no better, etOH = alcohol).\n"
    "- not_covered: no candidate fact states it; or the candidate facts state only part of it and miss the clinically "
    "important part (the polarity, a number or duration that is the point of the fact, the action of a plan item, the "
    "condition of a safety-net instruction); or a candidate states it with the opposite polarity, a different number, "
    "a different time or a different person (that is not coverage).\n"
    "Judge only against the CANDIDATE FACTS, never against what was probably said in the consultation.\n"
    "For each note fact return: id; label; fact_ids (the candidate ids that cover it, [] when not_covered); why (at "
    "most 12 words).")
TASK_B = (
    "TASK B - how does each CANDIDATE FACT relate to the clinician's NOTE?\n"
    "Labels (exactly one per candidate fact):\n"
    "- consistent: the note states the same thing (wording may differ; read clinical abbreviations as clinicians do).\n"
    "- contradicts: the note states something incompatible with it: the opposite polarity (present vs absent, done vs "
    "not done, an instruction reversed), a different number, dose, frequency or duration, a different time or order "
    "of events, a different person (whose symptom or condition it is, or who said or advised it), or another "
    "incompatible detail.\n"
    "- not_in_note: the note neither states it nor states anything incompatible with it. The note is a short summary, "
    "so such a fact is usually not wrong: never label a fact contradicts only because the note leaves it out.\n"
    "error_type: for contradicts exactly one of negation_polarity (present vs absent, yes vs no, done vs not done, an "
    "instruction reversed), dose_number (a different number, dose, frequency, quantity or duration), "
    "attribution_speaker (the wrong person: a relative's condition given as the patient's, the patient's own report or "
    "idea presented as the clinician's statement or advice, or the reverse), temporal (a wrong time, date, onset or "
    "order, or past given as future or the reverse), other_contradiction (any other incompatibility). For consistent "
    "and not_in_note use none, except attribution_speaker when the content agrees with or is absent from the note but "
    "the fact gives it to the wrong person (each candidate shows who said the words it quotes).\n"
    "For each candidate fact return: id; label; error_type; note_ids (the note fact ids it agrees with or contradicts, "
    "[] for not_in_note); why (at most 12 words).")
DATE_NOTE = ("Dates in candidate facts were resolved against a placeholder consultation date, Monday 5 January 2026, "
             "09:00 (the note has no date): judge times relative to that date.")
SCHEMA_A = {"type": "object", "properties": {"labels": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "label": {"type": "string", "enum": list(LABELS["A"])},
                                     "fact_ids": {"type": "array", "items": {"type": "string"}},
                                     "why": {"type": "string"}},
    "required": ["id", "label", "fact_ids", "why"]}}}, "required": ["labels"]}
SCHEMA_B = {"type": "object", "properties": {"labels": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "label": {"type": "string", "enum": list(LABELS["B"])},
                                     "error_type": {"type": "string", "enum": list(ERROR_TYPES)},
                                     "note_ids": {"type": "array", "items": {"type": "string"}},
                                     "why": {"type": "string"}},
    "required": ["id", "label", "error_type", "note_ids", "why"]}}}, "required": ["labels"]}


def prompt_sha256() -> str:
    """The annotator's fixed prompt parts (system, both tasks, the date note, both schemas), hashed for the
    preregistration."""
    return sha256_text(json.dumps([ANNOTATOR_SYSTEM, TASK_A, TASK_B, DATE_NOTE, SCHEMA_A, SCHEMA_B], sort_keys=True,
                                  ensure_ascii=False))


def analysis_config() -> dict:
    return {"severity": SEVERITY, "error_classes": ERROR_CLASSES, "labels": LABELS, "error_types": list(ERROR_TYPES),
            "bootstrap": {"seed": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES, "min_n": BOOTSTRAP_MIN_N,
                          "unit": "consultation", "interval": "percentile 2.5 / 97.5"},
            "human_sample": {"fraction": HUMAN_FRACTION, "seed": HUMAN_SEED},
            "order_seed": ORDER_SEED, "shuffle_seed": SHUFFLE_SEED, "chunk_chars": CHUNK_CHARS,
            "note_splitter": NOTE_SPLITTER, "anchor_at": ANCHOR_AT.isoformat(), "generator": GENERATOR,
            "annotators": [[m, e] for m, e in ANNOTATORS], "annotator": ANNOTATOR}


def analysis_sha256() -> str:
    return sha256_text(json.dumps(analysis_config(), sort_keys=True, ensure_ascii=False))


def fact_fields(f: dict) -> list[tuple[str, str]]:
    req, opt = FACT_FIELDS.get(f.get("type"), ((), ()))
    keys = [k for k in (*req, *opt, "status") if isinstance(f.get(k), str) and f[k].strip()]
    return [(k, f[k].strip()) for k in dict.fromkeys(keys)]


def candidate_line(c: dict) -> str:
    fields = "; ".join(f"{k}: {v}" for k, v in c["fields"]) or "(no fields)"
    return f"{c['eid']} [{c['type']}] {fields} | quote: \"{c['quote']}\" (said by: {c['speaker']})"


def note_fact_line(n: dict) -> str:
    ctx = f' -- from: "{n["context"][:200]}"' if n["context"] != n["text"] else ""
    return f"{n['nid']} [{n['section']}] {n['text']}{ctx}"


def annotation_prompt(task: str, note: str, note_facts: list[dict], cands: list[dict]) -> str:
    items = note_facts if task == "A" else cands
    first, last = (items[0]["nid"], items[-1]["nid"]) if task == "A" else (items[0]["eid"], items[-1]["eid"])
    what = "NOTE FACT" if task == "A" else "CANDIDATE FACT"
    return "\n".join([TASK_A if task == "A" else TASK_B, "", DATE_NOTE, "",
                      "CLINICIAN'S NOTE (verbatim):", f'"""{note.strip()}"""', "",
                      "NOTE FACTS (the note split into atomic facts; id [section] fact -- from: the sentence):",
                      *[note_fact_line(n) for n in note_facts], "",
                      "CANDIDATE FACTS (random order; id [type] fields | quote (said by: speaker of the quoted words)):",
                      *([candidate_line(c) for c in cands] or ["(none)"]), "",
                      f"Label every {what}: {len(items)} items, ids {first} to {last}. "
                      'Return JSON {"labels": [...]}.'])


def salvage_items(text: str) -> dict | None:
    """The complete label items of a reply that is not one whole JSON object (cut off at max_tokens, or broken): every
    {...} that parses on its own and has an id and a label, in order. Added after the preregistration (DEVIATIONS)."""
    dec, items, i = json.JSONDecoder(strict=False), [], 0   # strict=False: a raw line break inside a string is read
    first = text.find("{")
    if first != -1:
        try:
            whole, _ = dec.raw_decode(text, first)
            if isinstance(whole, dict) and isinstance(whole.get("labels"), list):
                return whole
        except ValueError:
            pass
    while (j := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, j)
        except ValueError:
            i = j + 1
            continue
        if isinstance(obj, dict) and "id" in obj and "label" in obj:
            items.append(obj)
            i = end
        else:
            i = j + 1
    return {"labels": items} if items else None


def read_reply(task: str, text: str | None, parsed, finish_reason, expected: list[str],
               other_ids: set[str]) -> tuple[dict, dict, bool]:
    """Labels, problems and completeness of one annotator reply. parsed: llm_client's JSON of the reply. A reply that is
    not one JSON object with a labels list (cut off, broken, or read by llm_client as some inner object) is salvaged:
    its complete items count, and the task is incomplete (PROTOCOL.md "Annotation")."""
    obj = parsed if finish_reason != "length" else None
    whole = isinstance(obj, dict) and isinstance(obj.get("labels"), list)
    salvaged = not whole and bool(text)
    if salvaged:
        obj = salvage_items(text)
    labels, problems = parse_labels(task, obj, expected, other_ids)
    problems["salvaged"] = salvaged and obj is not None
    ok = problems["parsed"] and not problems["missing"] and not salvaged and finish_reason != "length"
    return labels, problems, ok


def parse_labels(task: str, obj, expected: list[str], other_ids: set[str]) -> tuple[dict, dict]:
    """Labels by id from the annotator's JSON. An item counts once (the first valid one); an id never asked about, a
    label outside the task's labels or a missing id is a problem, not a guess. Cited ids are kept only if they exist.
    Task B: an error type other than none / attribution_speaker on a label that is not contradicts is set to none
    (counted as coerced); contradicts without a valid error type becomes other_contradiction (counted)."""
    out: dict[str, dict] = {}
    problems = {"unknown_ids": [], "invalid": [], "duplicates": [], "missing": [], "coerced": [], "parsed": False}
    items = obj.get("labels") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        problems["missing"] = list(expected)
        return out, problems
    problems["parsed"] = True
    want = set(expected)
    for it in items:
        if not isinstance(it, dict):
            continue
        i = str(it.get("id", "")).strip()
        if i not in want:
            problems["unknown_ids"].append(i)
            continue
        label = str(it.get("label", "")).strip().lower()
        if label not in LABELS[task]:
            problems["invalid"].append(i)
            continue
        if i in out:
            problems["duplicates"].append(i)
            continue
        cited_key = "fact_ids" if task == "A" else "note_ids"
        cited = [str(x).strip() for x in it.get(cited_key) or [] if isinstance(x, (str, int))]
        rec = {"label": label, cited_key: [x for x in dict.fromkeys(cited) if x in other_ids],
               "why": str(it.get("why", ""))[:300], "source": "annotator"}
        if task == "B":
            et = str(it.get("error_type", "none")).strip().lower()
            if label == "contradicts" and et not in COMMISSION:
                problems["coerced"].append(i)
                et = "other_contradiction"
            elif label != "contradicts" and et not in ("none", "attribution_speaker"):
                problems["coerced"].append(i)
                et = "none"
            rec["error_type"] = et
        out[i] = rec
    problems["missing"] = [i for i in expected if i not in out]
    return out, problems


# ---------------------------------------------------------------------------------------------------------- metrics
def consultation_metrics(note_facts: list[dict], cands: list[dict], la: dict, lb: dict, proposed: int,
                         accepted: int) -> dict:
    """One consultation's counts (PROTOCOL.md "Metrics"). An omission is a note fact labelled not_covered that no
    contradicting candidate cites (a contradicted note fact is counted once, as the contradiction)."""
    covered = sum(1 for v in la.values() if v["label"] == "covered")
    counts = {k: sum(1 for v in lb.values() if v["label"] == k) for k in LABELS["B"]}
    contradicted = {n for v in lb.values() if v["label"] == "contradicts" for n in v.get("note_ids", [])}
    errors = {k: 0 for k in ERROR_CLASSES}
    for v in lb.values():
        if v["label"] == "contradicts":
            errors[v.get("error_type") if v.get("error_type") in COMMISSION else "other_contradiction"] += 1
        elif v.get("error_type") == "attribution_speaker":
            errors["attribution_speaker"] += 1
    for n in note_facts:
        v = la.get(n["nid"])
        if v and v["label"] == "not_covered" and n["nid"] not in contradicted:
            errors["omission_safety_net" if n["safety_net"] else "omission_other"] += 1
    weighted = sum(SEVERITY[ERROR_CLASSES[k]] * c for k, c in errors.items())
    sn = [n for n in note_facts if n["safety_net"] and n["nid"] in la]
    by_section: dict[str, list[int]] = {}
    for n in note_facts:
        if n["nid"] in la:
            s = by_section.setdefault(n["section"], [0, 0])
            s[0] += la[n["nid"]]["label"] == "covered"
            s[1] += 1
    return {"note_facts": len(note_facts), "note_facts_labelled": len(la), "covered": covered,
            "recall": B.rnd(covered / len(la)) if la else None,
            "candidates": len(cands), "candidates_labelled": len(lb), **counts,
            "contradiction_rate": B.rnd(counts["contradicts"] / len(lb)) if lb else None,
            "errors": errors, "weighted_error": weighted,
            "weighted_error_per_note_fact": B.rnd(weighted / len(la)) if la else None,
            "safety_net_note_facts": len(sn), "safety_net_covered": sum(la[n["nid"]]["label"] == "covered" for n in sn),
            "recall_by_section": by_section, "proposed": proposed, "accepted": accepted,
            "grounding_pass_rate": B.rnd(accepted / proposed) if proposed else None}


def ratio(pairs: list[tuple[float, float]], key: str) -> dict:
    """Pooled ratio sum(num) / sum(den) over consultations with a non-zero denominator, its cluster bootstrap 95% CI
    (consultations resampled), and the macro mean of the per-consultation ratios with its own bootstrap."""
    pairs = [(a, b) for a, b in pairs if b]
    rates = [a / b for a, b in pairs]
    return {"n_consultations": len(pairs), "num": sum(a for a, _ in pairs), "den": sum(b for _, b in pairs),
            "pooled": B.rnd(B.pooled(pairs)),
            "ci95": B.bootstrap_ci(pairs, B.pooled, key=f"{key}:pooled", resamples=BOOTSTRAP_RESAMPLES,
                                   seed=BOOTSTRAP_SEED, min_n=BOOTSTRAP_MIN_N),
            "macro": B.rnd(B.mean(rates)),
            "macro_ci95": B.bootstrap_ci(rates, B.mean, key=f"{key}:macro", resamples=BOOTSTRAP_RESAMPLES,
                                         seed=BOOTSTRAP_SEED, min_n=BOOTSTRAP_MIN_N)}


def aggregate(cons: list[dict]) -> dict:
    """PROTOCOL.md "Metrics": recall and the task B rates count every labelled item, also of an incomplete annotation
    (ratio() leaves out a consultation with nothing labelled); the weighted score and the error counts use the
    consultations whose both tasks are complete."""
    a_ok = [c for c in cons if c["annotation_ok"]["A"]]
    b_ok = [c for c in cons if c["annotation_ok"]["B"]]
    both = [c for c in cons if c["annotation_ok"]["A"] and c["annotation_ok"]["B"]]
    m = lambda c: c["metrics"]   # noqa: E731
    sections: dict[str, list] = {}
    for c in cons:
        for s, (k, n) in m(c)["recall_by_section"].items():
            sections.setdefault(s, []).append((k, n))
    errors = {k: sum(m(c)["errors"][k] for c in both) for k in ERROR_CLASSES}
    return {
        "n_consultations": len(cons), "n_annotated_A": len(a_ok), "n_annotated_B": len(b_ok), "n_both": len(both),
        "note_fact_recall": ratio([(m(c)["covered"], m(c)["note_facts_labelled"]) for c in cons], "recall"),
        "contradiction_rate": ratio([(m(c)["contradicts"], m(c)["candidates_labelled"]) for c in cons], "contradiction"),
        "not_in_note_rate": ratio([(m(c)["not_in_note"], m(c)["candidates_labelled"]) for c in cons], "not_in_note"),
        "consistent_rate": ratio([(m(c)["consistent"], m(c)["candidates_labelled"]) for c in cons], "consistent"),
        "weighted_error_per_note_fact": ratio([(m(c)["weighted_error"], m(c)["note_facts_labelled"]) for c in both],
                                              "weighted"),
        "grounding_pass_rate": ratio([(m(c)["accepted"], m(c)["proposed"]) for c in cons], "grounding"),
        "safety_net_recall": ratio([(m(c)["safety_net_covered"], m(c)["safety_net_note_facts"]) for c in cons],
                                   "safety_net"),
        "recall_by_section": {s: ratio(v, f"section:{s}") for s, v in sorted(sections.items())},
        "error_counts": errors,
        "error_counts_by_severity": {sev: sum(n for k, n in errors.items() if ERROR_CLASSES[k] == sev)
                                     for sev in SEVERITY},
        "weighted_error_total": sum(SEVERITY[ERROR_CLASSES[k]] * n for k, n in errors.items()),
        "facts": {"note_facts": sum(m(c)["note_facts"] for c in cons), "proposed": sum(m(c)["proposed"] for c in cons),
                  "accepted": sum(m(c)["accepted"] for c in cons)},
        "extraction_parts": {"total": sum(c["parts"]["total"] for c in cons),
                             "failed": sum(c["parts"]["failed"] for c in cons),
                             "failure_classes": dict(sorted(_count(f for c in cons for f in c["parts"]["failure_classes"]).items()))},
    }


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


# ---------------------------------------------------------------------------------------------------------- human review
def decisions(cons: list[dict]) -> list[dict]:
    """Every label the annotator gave (not the rule labels of a consultation without candidate facts)."""
    out = []
    for c in cons:
        cands = {x["eid"]: x for x in c["candidates"]}
        notes = {n["nid"]: n for n in c["note_facts"]}
        for nid, v in c["labels"]["A"].items():
            if v.get("source") != "annotator":
                continue
            n = notes[nid]
            cited = "; ".join(f'{e} "{cands[e]["quote"]}"' for e in v.get("fact_ids", []) if e in cands)
            out.append({"id": f"{c['consultation']}|note|{nid}", "fact": f"[note, {n['section']}] {n['text']}",
                        "context_quote": f'note sentence: "{n["context"]}"' + (f"; annotator cited: {cited}" if cited else ""),
                        "annotator_label": v["label"]})
        for eid, v in c["labels"]["B"].items():
            if v.get("source") != "annotator":
                continue
            x = cands[eid]
            fields = "; ".join(f"{k}: {val}" for k, val in x["fields"])
            cited = "; ".join(f'{n} "{notes[n]["text"]}"' for n in v.get("note_ids", []) if n in notes)
            out.append({"id": f"{c['consultation']}|extracted|{eid}", "fact": f"[extracted, {x['type']}] {fields}",
                        "context_quote": f'transcript quote ({x["speaker"]}): "{x["quote"]}"'
                                         + (f"; annotator cited: {cited}" if cited else ""),
                        "annotator_label": v["label"]})
    return out


def human_sample(rows: list[dict]) -> list[dict]:
    ids = sorted(r["id"] for r in rows)
    k = math.ceil(HUMAN_FRACTION * len(ids)) if ids else 0
    pick = set(random.Random(f"{HUMAN_SEED}:human_review").sample(ids, k))
    return sorted((r for r in rows if r["id"] in pick), key=lambda r: r["id"])


HUMAN_COLUMNS = ("id", "fact", "context_quote", "annotator_label", "human_label")


def write_human_review(out: Path, cons: list[dict]) -> dict:
    """OUT/human_review.csv (never overwritten: a person may already have filled it) and human_review_context.md (the
    full note facts and candidate facts of each sampled consultation, which a reviewer needs for 'not covered')."""
    path = out / "human_review.csv"
    rows = human_sample(decisions(cons))
    if path.exists():
        with open(path, encoding="utf-8-sig", newline="") as f:
            kept = list(csv.DictReader(f))
        return {"path": path.name, "written": False, "rows": len(kept), "decisions_total": len(decisions(cons)),
                "human_labels_filled": sum(1 for r in kept if (r.get("human_label") or "").strip()),
                "reason": "exists; not overwritten"}
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HUMAN_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({**r, "human_label": ""})
    path.write_text(buf.getvalue(), encoding="utf-8-sig")
    sampled = sorted({r["id"].split("|")[0] for r in rows})
    lines = ["# Human review context", "",
             "Fill `human_label` in human_review.csv with the labels of research/primock_gold_v1/ANNOTATION_GUIDE.md: "
             "note rows `covered` / `not_covered`, extracted rows `consistent` / `contradicts` / `not_in_note`. "
             "Hide the annotator_label column while labelling (it anchors). Then run "
             "`python -I scripts/primock_gold_eval.py kappa --csv <this folder>/human_review.csv`.", "",
             "Source: PriMock57 (CC BY 4.0, see ATTRIBUTION.txt); mock consultations with actors.", ""]
    for c in cons:
        if c["consultation"] not in sampled:
            continue
        lines += [f"## {c['consultation']}", "", "Note facts:", ""]
        lines += [f"- {n['nid']} [{n['section']}] {n['text']}" + (" (safety-net)" if n["safety_net"] else "")
                  for n in c["note_facts"]]
        lines += ["", "Candidate facts (extracted, accepted by the grounding check):", ""]
        lines += [f"- {candidate_line(x)}" for x in c["candidates"]] or ["- (none)"]
        lines.append("")
    (out / "human_review_context.md").write_text("\n".join(lines), encoding="utf-8")
    return {"path": path.name, "written": True, "rows": len(rows), "decisions_total": len(decisions(cons)),
            "fraction": HUMAN_FRACTION, "seed": HUMAN_SEED}


LABEL_ALIASES = {"contradict": "contradicts", "contradicted": "contradicts", "uncovered": "not_covered",
                 "notcovered": "not_covered", "notinnote": "not_in_note", "not_in_the_note": "not_in_note"}


def norm_label(s: str) -> str:
    s = re.sub(r"[\s\-]+", "_", (s or "").strip().lower())
    return LABEL_ALIASES.get(s, s)


def cohen_kappa(pairs: list[tuple[str, str]]) -> dict:
    n = len(pairs)
    if not n:
        return {"n": 0, "raw_agreement": None, "kappa": None, "confusion": {}}
    cats = sorted({x for p in pairs for x in p})
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == k for a, _ in pairs) / n) * (sum(b == k for _, b in pairs) / n) for k in cats)
    confusion = {f"{a} -> {b}": sum(1 for p in pairs if p == (a, b)) for a in cats for b in cats}
    return {"n": n, "raw_agreement": B.rnd(po), "expected_agreement": B.rnd(pe),
            "kappa": B.rnd((po - pe) / (1 - pe)) if pe < 1 else None,
            "kappa_note": None if pe < 1 else "undefined: both raters used one and the same label",
            "confusion": {k: v for k, v in confusion.items() if v}}


def kappa_report(csv_path: Path) -> dict:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    missing = [c for c in HUMAN_COLUMNS if rows and c not in rows[0]]
    if missing:
        raise UsageError(f"{csv_path}: columns missing: {', '.join(missing)}")
    by_kind: dict[str, list] = {"note": [], "extracted": []}
    invalid, unlabelled = [], 0
    for r in rows:
        h = norm_label(r.get("human_label", ""))
        if not h:
            unlabelled += 1
            continue
        kind = (r.get("id") or "").split("|")[1] if (r.get("id") or "").count("|") == 2 else None
        allowed = LABELS["A"] if kind == "note" else LABELS["B"] if kind == "extracted" else ()
        a = norm_label(r.get("annotator_label", ""))
        if h not in allowed or a not in allowed:
            invalid.append(r.get("id"))
            continue
        by_kind[kind].append((a, h))
    allp = by_kind["note"] + by_kind["extracted"]

    def with_ci(pairs, key):
        k = cohen_kappa(pairs)
        k["kappa_ci95"] = B.bootstrap_ci(pairs, lambda ps: cohen_kappa(ps)["kappa"], key=f"kappa:{key}",
                                         resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED, min_n=BOOTSTRAP_MIN_N)
        return k
    return {"csv": str(csv_path), "rows": len(rows), "labelled": len(allp), "unlabelled": unlabelled,
            "invalid_labels": invalid, "status": "pending: no human_label filled yet" if not allp else "computed",
            "overall": with_ci(allp, "overall"), "note_facts": with_ci(by_kind["note"], "note"),
            "extracted_facts": with_ci(by_kind["extracted"], "extracted"),
            "method": "Cohen's kappa between annotator_label and human_label per row; overall pools both label sets; "
                      f"bootstrap over rows ({BOOTSTRAP_RESAMPLES} resamples, seed {BOOTSTRAP_SEED}, none below "
                      f"n = {BOOTSTRAP_MIN_N})"}


# ---------------------------------------------------------------------------------------------------------- transport
class PausingTransport:
    """Waits before each attempt while release/benchmarks/.load_test_running exists (another run is load testing the
    endpoint), then sends."""

    def __init__(self, inner, flag: Path | None = None, sleep=time.sleep, poll_s: float = 15.0, echo=print):
        self.inner, self.sleep, self.poll_s, self.echo = inner, sleep, poll_s, echo
        self.flag = Path(flag) if flag is not None else LOAD_TEST_FLAG
        self.name = getattr(inner, "name", type(inner).__name__)
        self.paused_s = 0.0

    def __call__(self, *a, **kw):
        told = False
        while self.flag.exists():
            if not told:
                self.echo(f"paused: {self.flag.name} exists (a load test is running); waiting")
                told = True
            self.sleep(self.poll_s)
            self.paused_s += self.poll_s
        return self.inner(*a, **kw)


class DryTransport:
    """A deterministic OpenAI-compatible stand-in for --dry-run and tests, not a model. Extraction: one 'event' fact per
    line of the update (its first six words, quoted) and one fact whose quote is not in the update (the grounding check
    must reject it). Task A: odd note facts covered, even not covered. Task B: every fifth candidate contradicts
    (negation_polarity), the rest alternate consistent / not_in_note."""
    name = "dry"

    def __init__(self, models=(GENERATOR_MODEL, ANNOTATORS[0][0])):
        self.models, self.calls = list(models), 0

    def __call__(self, method, url, headers, body, timeout, stream=False):
        self.calls += 1
        if method == "GET":
            return B.Response(200, {"Content-Type": "application/json"},
                              json.dumps({"data": [{"id": m} for m in self.models]}).encode())
        payload = json.loads(body)
        text = payload["messages"][-1]["content"]
        if "List every fact this update states" in text:
            update = text.split('"""', 2)[1]
            facts = []
            for line in update.splitlines():
                content = line.split(":", 1)[1].split() if ":" in line else line.split()
                if len(content) >= 4:
                    q = " ".join(content[:6])
                    facts.append({"type": "event", "what": q, "quote": q})
            facts = facts[:4] + [{"type": "event", "what": "never said", "quote": "this sentence was never said here"}]
            reply = {"facts": facts}
        elif text.startswith("TASK A"):
            ids = re.findall(r"^(N\d{2,})\s", text, re.M)
            eids = re.findall(r"^(E\d{2,})\s", text, re.M)
            reply = {"labels": [{"id": i, "label": "covered" if int(i[1:]) % 2 else "not_covered",
                                 "fact_ids": eids[:1] if int(i[1:]) % 2 else [], "why": "dry run"} for i in ids]}
        elif text.startswith("TASK B"):
            ids = re.findall(r"^(E\d{2,})\s", text, re.M)
            reply = {"labels": [{"id": i, "label": "contradicts" if int(i[1:]) % 5 == 0 else
                                 ("consistent" if int(i[1:]) % 2 else "not_in_note"),
                                 "error_type": "negation_polarity" if int(i[1:]) % 5 == 0 else "none",
                                 "note_ids": ["N01"] if int(i[1:]) % 2 or int(i[1:]) % 5 == 0 else [],
                                 "why": "dry run"} for i in ids]}
        else:
            reply = {}
        content = json.dumps(reply)
        out = {"id": "dry", "object": "chat.completion", "model": payload.get("model"),
               "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": len(body) // 4, "completion_tokens": max(1, len(content) // 4)}}
        return B.Response(200, {"Content-Type": "application/json"}, json.dumps(out).encode())


# ---------------------------------------------------------------------------------------------------------- the run
def parse_deadline(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise UsageError(f"--deadline-utc {value!r} is not an ISO date-time") from None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


class Run:
    def __init__(self, cfg: dict, out: Path, *, transport, api_key: str | None, invocation: int, sleep=time.sleep,
                 echo=print):
        self.cfg, self.out, self.invocation, self.echo = cfg, Path(out), invocation, echo
        self.redact = B.Redactor(api_key)
        self.writer = B.RecordWriter(self.out / "records.jsonl", self.redact)
        self.budget = B.CallBudget(cfg["max_calls"])
        base = cfg["base_url"]

        def session(spec):
            return B.Session(base, api_key, transport, self.budget, timeout_s=spec["timeout_s"], max_tries=MAX_TRIES,
                             max_wait_s=MAX_WAIT_S, timeout_retries=spec["timeout_retries"], sleep=sleep,
                             sink=self.writer.write, redact=self.redact)
        self.gen_session, self.ann_session = session(GENERATOR), session(ANNOTATOR)
        self.generator = B.InstrumentedChat(self.gen_session, GENERATOR["model"], guided_json=GENERATOR["guided_json"],
                                            extra_body=GENERATOR["extra_body"], max_tokens=GENERATOR["max_tokens"])
        self.annotator = None
        if cfg.get("annotator_model"):
            self.annotator = B.InstrumentedChat(self.ann_session, cfg["annotator_model"],
                                                guided_json=ANNOTATOR["guided_json"],
                                                extra_body=cfg["annotator_extra_body"],
                                                max_tokens=ANNOTATOR["max_tokens"])

    def write(self, rec: dict):
        self.writer.write({"ts": utc_now(), "invocation": self.invocation, **rec})

    def choose_annotator(self) -> None:
        """GET /models once; the first preregistered annotator the endpoint lists (and the generator must be listed)."""
        if self.annotator is not None:
            return
        self.ann_session.begin(invocation=self.invocation, consultation=None, purpose="models", model=None)
        resp, rec = self.ann_session.send("GET", "/models")
        self.ann_session.log(rec)
        ids = [m.get("id") for m in (json.loads(resp.body).get("data") or []) if isinstance(m, dict)]
        pick = next(((m, e) for m, e in ANNOTATORS if m in ids), None)
        self.write({"type": "models", "listed": ids, "generator_listed": GENERATOR_MODEL in ids,
                    "annotator": pick[0] if pick else None})
        if GENERATOR_MODEL not in ids or pick is None:
            raise UsageError(f"the endpoint lists {'no preregistered annotator' if pick is None else 'no ' + GENERATOR_MODEL}"
                             f" (listed: {', '.join(map(str, ids))})")
        self.cfg["annotator_model"], self.cfg["annotator_extra_body"] = pick[0], copy.deepcopy(pick[1])
        self.annotator = B.InstrumentedChat(self.ann_session, pick[0], guided_json=ANNOTATOR["guided_json"],
                                            extra_body=pick[1], max_tokens=ANNOTATOR["max_tokens"])

    def done(self) -> set[str]:
        return {r["consultation"] for r in B.read_records(self.out / "records.jsonl")
                if r.get("type") in ("consultation", "skipped")}

    def run(self) -> str | None:
        done = self.done()
        todo = [c for c in self.cfg["order"] if c not in done]
        self.echo(f"{len(done)} of {len(self.cfg['order'])} consultations done; {len(todo)} to run; at most "
                  f"{self.cfg['max_calls']} HTTP calls in this invocation")
        deadline = parse_deadline(self.cfg.get("deadline_utc"))
        took: list[float] = []
        try:
            self.choose_annotator()
            for i, cid in enumerate(todo, 1):
                # added after the preregistration (harness, recorded as script drift): stop between consultations when
                # the next one would likely end after --deadline-utc (estimate: the slowest one so far, else 300 s)
                if deadline and self.now() + dt.timedelta(seconds=max(took, default=300.0)) > deadline:
                    self.echo(f"stopped: the next consultation would likely end after --deadline-utc "
                              f"{deadline.isoformat()}; continue with --resume {self.out}")
                    return "deadline"
                t0 = time.perf_counter()
                rec = self.run_consultation(cid)
                took.append(time.perf_counter() - t0)
                if rec is None:
                    self.echo(f"[{i}/{len(todo)}] {cid}: skipped (unreadable note or transcript; see records)")
                    continue
                mm = rec["metrics"]
                self.echo(f"[{i}/{len(todo)}] {cid}: {rec['parts']['total']} parts ({rec['parts']['failed']} failed), "
                          f"{mm['accepted']}/{mm['proposed']} facts accepted, recall {mm['recall']}, contradicts "
                          f"{mm['contradicts']}, weighted errors {mm['weighted_error']}; calls so far {self.budget.used}")
        except B.CallBudgetExhausted:
            self.echo(f"stopped: --max-calls {self.cfg['max_calls']} reached; continue with --resume {self.out}")
            return "max_calls"
        return None

    @staticmethod
    def now() -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)

    def extract(self, cid: str, updates: list[dict]) -> tuple[list[dict], list[dict], dict]:
        ep = Episode(SCENARIO)
        accepted, rejected, parts = [], [], {"total": len(updates), "failed": 0, "failure_classes": []}
        for u in updates:
            meter = self.gen_session.begin(invocation=self.invocation, consultation=cid, purpose="extract",
                                           model=GENERATOR_MODEL, update_id=u["update_id"])
            extractor = llm_extractor(self.generator)
            update = {k: u[k] for k in ("update_id", "at", "kind", "speaker", "speaker_type", "text")}
            entry, exc = None, None
            t0 = time.perf_counter()
            try:
                entry = ep.add_update(update, extractor=extractor, evidence_checker=None)
            except B.CallBudgetExhausted:
                raise
            except Exception as e:  # noqa: BLE001 - a model, network or pipeline problem is a measured failure
                exc = e
            log = extractor.log[-1] if extractor.log else {}
            fclass = B.failure_class(exc, meter, log)
            acc = [f for f in (entry or {}).get("facts") or []]
            rej = [r for r in (entry or {}).get("rejected") or [] if "verification" not in r]
            for f in acc:
                accepted.append({"fact": {k: v for k, v in f.items() if not k.startswith("_")}, "update_id": u["update_id"],
                                 "speaker": quote_speakers(f.get("quote", ""), u["text"])})
            rejected += [{**B.rejected_fact(r), "update_id": u["update_id"]} for r in rej]
            if fclass:
                parts["failed"] += 1
                parts["failure_classes"].append(fclass)
            complete = meter.ok_calls > 0 and meter.usage_missing == 0
            self.write({"type": "part", "consultation": cid, "update_id": u["update_id"], "chars": len(u["text"]),
                        "segments": len(u["segment_ids"]), "start_s": u["start_s"], "end_s": u["end_s"],
                        "status": "failed" if fclass else "ok", "failure_class": fclass,
                        "error": self.redact(f"{type(exc).__name__}: {exc}")[:500] if exc is not None else None,
                        "e2e_s": round(time.perf_counter() - t0, 4), "http_attempts": meter.attempts,
                        "retries": meter.retries, "json_mode": log.get("json_mode"),
                        "finish_reason": log.get("finish_reason"), "reply_parsed": log.get("parsed"),
                        "prompt_tokens": meter.prompt_tokens if complete else None,
                        "completion_tokens": meter.completion_tokens if complete else None,
                        "proposed": len(acc) + len(rej), "accepted": len(acc), "rejected": len(rej),
                        "accepted_facts": [{k: v for k, v in f.items() if not k.startswith("_")} for f in acc],
                        "rejected_facts": [B.rejected_fact(r) for r in rej]})
        return accepted, rejected, parts

    def annotate(self, cid: str, task: str, note: str, note_facts: list[dict], cands: list[dict]) -> tuple[dict, bool]:
        expected = [n["nid"] for n in note_facts] if task == "A" else [c["eid"] for c in cands]
        other = {c["eid"] for c in cands} if task == "A" else {n["nid"] for n in note_facts}
        prompt = annotation_prompt(task, note, note_facts, cands)
        meter = self.ann_session.begin(invocation=self.invocation, consultation=cid, purpose=f"annotate_{task}",
                                       model=self.annotator.model)
        r, err = {}, None
        try:
            r = self.annotator.chat([{"role": "system", "content": ANNOTATOR_SYSTEM}, {"role": "user", "content": prompt}],
                                    json_schema=SCHEMA_A if task == "A" else SCHEMA_B, schema_name=f"task_{task}")
        except B.CallBudgetExhausted:
            raise
        except Exception as e:  # noqa: BLE001 - recorded; the consultation's other task still runs
            err = self.redact(f"{type(e).__name__}: {e}")[:500]
        labels, problems, ok = read_reply(task, r.get("text"), r.get("json"), r.get("finish_reason"), expected, other)
        self.write({"type": "annotation", "consultation": cid, "task": task, "model": self.annotator.model,
                    "extra_body": self.annotator.extra_body, "prompt_sha256": sha256_text(prompt),
                    "fixed_prompt_sha256": prompt_sha256(), "expected": len(expected), "labelled": len(labels),
                    "ok": ok, "problems": problems, "error": err, "finish_reason": r.get("finish_reason"),
                    "json_mode": r.get("json_mode"), "latency_s": r.get("latency_s"), "http_attempts": meter.attempts,
                    "prompt_tokens": meter.prompt_tokens, "completion_tokens": meter.completion_tokens,
                    "labels": labels, "prompt": prompt, "reply_text": r.get("text")})
        return labels, ok

    def run_consultation(self, cid: str) -> dict | None:
        raw = ROOT / self.cfg["raw"] if not Path(self.cfg["raw"]).is_absolute() else Path(self.cfg["raw"])
        # data guard (added after the preregistration, see DEVIATIONS): a note without text or facts, or transcripts
        # that yield no turn (e.g. an encoding the TextGrid parser cannot read), is skipped and listed, not scored
        try:
            note_obj = load_note(raw, cid)
            note_facts = split_note(note_obj["note"])
            turns = build_turns(load_segments(raw, cid))
        except (UsageError, OSError, ValueError) as e:
            self.write({"type": "skipped", "consultation": cid, "reason": f"{type(e).__name__}: {e}"[:300]})
            return None
        if not note_facts or not turns:
            self.write({"type": "skipped", "consultation": cid,
                        "reason": "no note facts" if not note_facts else "no transcript turn"})
            return None
        updates = make_updates(cid, turns, CHUNK_CHARS)
        accepted, rejected, parts = self.extract(cid, updates)
        order = list(range(len(accepted)))
        random.Random(f"{SHUFFLE_SEED}:{cid}").shuffle(order)
        cands = []
        for k, i in enumerate(order, 1):
            a = accepted[i]
            f = a["fact"]
            cands.append({"eid": f"E{k:02d}", "fact_id": f.get("fact_id"), "type": f.get("type"), "fields": fact_fields(f),
                          "quote": f.get("quote", ""), "speaker": a["speaker"], "update_id": a["update_id"]})
        labels, ok = {"A": {}, "B": {}}, {"A": False, "B": False}
        if not cands:   # nothing to compare: every note fact is not covered, by rule (no annotator call)
            labels["A"] = {n["nid"]: {"label": "not_covered", "fact_ids": [], "why": "no candidate facts",
                                      "source": "rule"} for n in note_facts}
            ok = {"A": True, "B": True}
        else:
            if note_facts:
                labels["A"], ok["A"] = self.annotate(cid, "A", note_obj["note"], note_facts, cands)
            else:
                ok["A"] = True
            labels["B"], ok["B"] = self.annotate(cid, "B", note_obj["note"], note_facts, cands)
        metrics = consultation_metrics(note_facts, cands, labels["A"], labels["B"], len(accepted) + len(rejected),
                                       len(accepted))
        rec = {"type": "consultation", "consultation": cid, "status": "ok" if ok["A"] and ok["B"] and not parts["failed"]
               else "extraction_incomplete" if parts["failed"] else "annotation_incomplete",
               "turns": len(turns), "transcript_chars": sum(len(turn_line(t)) + 1 for t in turns), "parts": parts,
               "note_sha256": sha256_text(note_obj["note"]), "presenting_complaint": note_obj.get("presenting_complaint"),
               "note": note_obj["note"], "note_facts": note_facts, "candidates": cands, "rejected": rejected,
               "labels": labels, "annotation_ok": ok, "metrics": metrics}
        self.write(rec)
        return rec


# ---------------------------------------------------------------------------------------------------------- outputs
def reparse(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Offline re-analysis (DEVIATIONS): every stored annotator reply is read again with read_reply (llm_client's
    extract_json on the stored reply text, as at run time) and each consultation's labels and metrics are recomputed.
    No call is made. Returns the records with the consultation records replaced, and what changed."""
    from llm_client import extract_json
    last_ann = {}
    for r in records:
        if r["type"] == "annotation":
            last_ann[(r["consultation"], r["task"])] = r
    out, changed = [], []
    for r in records:
        if r["type"] != "consultation":
            out.append(r)
            continue
        c = copy.deepcopy(r)
        for task in ("A", "B"):
            a = last_ann.get((c["consultation"], task))
            if a is None:
                continue
            expected = [n["nid"] for n in c["note_facts"]] if task == "A" else [x["eid"] for x in c["candidates"]]
            other = {x["eid"] for x in c["candidates"]} if task == "A" else {n["nid"] for n in c["note_facts"]}
            text = a.get("reply_text")
            labels, problems, ok = read_reply(task, text, extract_json(text) if text else None, a.get("finish_reason"),
                                              expected, other)
            if labels != c["labels"][task] or ok != c["annotation_ok"][task]:
                changed.append({"consultation": c["consultation"], "task": task,
                                "labelled_before": len(c["labels"][task]), "labelled_after": len(labels),
                                "ok_before": c["annotation_ok"][task], "ok_after": ok,
                                "problems_after": {k: (len(v) if isinstance(v, list) else v) for k, v in problems.items()}})
            c["labels"][task], c["annotation_ok"][task] = labels, ok
        c["metrics"] = consultation_metrics(c["note_facts"], c["candidates"], c["labels"]["A"], c["labels"]["B"],
                                            c["metrics"]["proposed"], c["metrics"]["accepted"])
        c["status"] = ("ok" if c["annotation_ok"]["A"] and c["annotation_ok"]["B"] and not c["parts"]["failed"]
                       else "extraction_incomplete" if c["parts"]["failed"] else "annotation_incomplete")
        out.append(c)
    return out, changed


def build_results(records: list[dict], argv: list[str], stopped: str | None) -> dict:
    start = next(r for r in records if r["type"] == "run_start")
    cfg = start["config"]
    invs = [r for r in records if r["type"] == "invocation"]
    https = [r for r in records if r["type"] == "http"]
    cons = {}
    for r in records:
        if r["type"] == "consultation":
            cons[r["consultation"]] = r   # the last record of a consultation counts
    cons_list = [cons[c] for c in cfg["order"] if c in cons]
    anns = [r for r in records if r["type"] == "annotation"]
    models = next((r for r in reversed(records) if r["type"] == "models"), None)
    annotator_model = (models or {}).get("annotator") or cfg.get("annotator_model")
    live = [h for h in https if not cfg["dry_run"]]
    prereg = start.get("preregistration") or {}
    first_live = min((h["ts"] for h in live), default=None)
    usage = {p: {"calls": sum(1 for h in https if h.get("purpose") == p),
                 "prompt_tokens": sum(h.get("prompt_tokens") or 0 for h in https if h.get("purpose") == p),
                 "completion_tokens": sum(h.get("completion_tokens") or 0 for h in https if h.get("purpose") == p)}
             for p in ("models", "extract", "annotate_A", "annotate_B")}
    return {
        "schema_version": SCHEMA_VERSION, "created_utc": utc_now(), "dry_run": cfg["dry_run"], "argv": argv,
        "endpoint": {"host": B.endpoint_host(cfg["base_url"]),
                     "is_token_factory_default": B.endpoint_host(cfg["base_url"]) == B.TOKEN_FACTORY_HOST},
        "git": (invs[-1].get("git") if invs else None), "stopped_reason": stopped,
        "preregistration": {"path": "research/primock_gold_v1/preregistration.json",
                            "created_utc": prereg.get("created_utc"), "sha256": prereg.get("sha256"),
                            "first_live_call_utc": first_live,
                            "written_before_first_live_call": (prereg.get("created_utc") < first_live)
                            if prereg.get("created_utc") and first_live else None,
                            "script_sha256_at_prereg": prereg.get("script_sha256"),
                            "amendment": cfg.get("amendment"),
                            "amendment_written_before_first_live_call": (cfg["amendment"]["created_utc"] < first_live)
                            if cfg.get("amendment") and first_live else None,
                            "script_sha256_at_run": sorted({(i.get("source_sha256") or {}).get("scripts/primock_gold_eval.py")
                                                            for i in invs} - {None})},
        "data": {"raw": cfg["raw"], "consultations_planned": len(cfg["order"]), "consultations_done": len(cons_list),
                 "skipped": [{"consultation": r["consultation"], "reason": r["reason"]} for r in records
                             if r["type"] == "skipped"],
                 "order": cfg["order"], "order_seed": ORDER_SEED},
        "system_under_test": {"generator": GENERATOR, "entry_point": "Episode.add_update(update, extractor="
                              "episode.llm_extractor(client), evidence_checker=None) per transcript part",
                              "parts": f"speaker-labelled turns, at most {CHUNK_CHARS} characters per part"},
        "annotator": {"model": annotator_model, "extra_body": dict(ANNOTATORS).get(annotator_model), **ANNOTATOR, "fixed_prompt_sha256": prompt_sha256(),
                      "calls_ok": sum(1 for a in anns if a["ok"]), "calls": len(anns),
                      "problems": {k: sum(len(a["problems"][k]) for a in anns)
                                   for k in ("unknown_ids", "invalid", "duplicates", "missing", "coerced")}},
        "http_calls": {"total": len(https), "retries": sum(1 for h in https if h.get("attempt", 1) > 1),
                       "statuses": _count(str(h.get("status")) for h in https), "by_purpose": usage,
                       "by_invocation": {str(i["invocation"]): sum(1 for h in https if h.get("invocation") == i["invocation"])
                                         for i in invs}},
        "aggregate": aggregate(cons_list) if cons_list else None,
        "per_consultation": [{"consultation": c["consultation"], "status": c["status"], "parts": c["parts"]["total"],
                              "parts_failed": c["parts"]["failed"], "turns": c["turns"], **{k: v for k, v in c["metrics"].items()
                                                                                           if k != "recall_by_section"}}
                             for c in cons_list],
        "analysis": analysis_config(),
        "deviations_from_preregistration": list(DEVIATIONS),
    }


def endpoint_wording(host: str, dry: bool) -> str:
    if dry:
        return ("DRY RUN: no model was called. Replies came from this script's scripted DryTransport; every number below "
                "exercises the harness only and is not a measurement of any model, endpoint or annotator.")
    return B.endpoint_wording(host, dry)


def fmt_ratio(r: dict | None, pct=True) -> str:
    if not r or r.get("pooled") is None:
        return "n/a"
    v, ci = r["pooled"], r.get("ci95")
    s = f"{100 * v:.1f}%" if pct else f"{v:.3f}"
    if ci:
        s += f" [{100 * ci[0]:.1f}, {100 * ci[1]:.1f}]" if pct else f" [{ci[0]:.3f}, {ci[1]:.3f}]"
    else:
        s += " (no CI: n < 5)"
    return f"{s} ({r['num']}/{r['den']}, n = {r['n_consultations']})"


def summary_md(res: dict, human: dict | None) -> str:
    agg, host, dry = res["aggregate"], res["endpoint"]["host"], res["dry_run"]
    p = res["preregistration"]
    lines = ["# PriMock57 external-reference evaluation (primock_gold_v1)", "",
             endpoint_wording(host, dry), "",
             f"- Created (UTC): {res['created_utc']}; protocol research/primock_gold_v1/PROTOCOL.md; preregistration "
             f"written {p['created_utc'] or 'n/a (not required for a dry run)'}, first live call "
             f"{p['first_live_call_utc'] or 'none (dry run)'}"
             + (f"; written before the first live call: {p['written_before_first_live_call']}" if not dry else "")
             + (f"; subset amendment {p['amendment']['path']} ({p['amendment']['subset']} of {p['amendment']['available']} "
                f"consultations, seeded) written {p['amendment']['created_utc']}, before the first live call: "
                f"{p['amendment_written_before_first_live_call']}" if p.get("amendment") else "") + ".",
             f"- System under test: {res['system_under_test']['entry_point']}; generator `{GENERATOR_MODEL}` (prompted JSON, "
             f"max_tokens {GENERATOR['max_tokens']}, verifier off); {res['system_under_test']['parts']}.",
             f"- Annotator: `{res['annotator']['model']}` (extra body {json.dumps(res['annotator']['extra_body'])}), blind "
             f"to what produced the facts; {res['annotator']['calls_ok']}/{res['annotator']['calls']} annotation calls "
             f"fully labelled; problems {json.dumps(res['annotator']['problems'])}.",
             f"- Consultations: {res['data']['consultations_done']} of {res['data']['consultations_planned']} planned "
             f"({res['data']['raw']}); skipped (unreadable data): "
             f"{', '.join(x['consultation'] + ' (' + x['reason'] + ')' for x in res['data']['skipped']) or 'none'}; "
             f"HTTP calls {res['http_calls']['total']} ({res['http_calls']['retries']} retries)."
             + (f" **Stopped early: {res['stopped_reason']}; the numbers cover the completed consultations only.**"
                if res["stopped_reason"] else ""), ""]
    if agg:
        e = agg["error_counts"]
        lines += ["| Metric (pooled over consultations, 95% cluster-bootstrap CI) | Value |", "|---|---|",
                  f"| Note-fact recall | {fmt_ratio(agg['note_fact_recall'])} |",
                  f"| Contradiction rate (of accepted facts) | {fmt_ratio(agg['contradiction_rate'])} |",
                  f"| Severity-weighted error score (weight per note fact) | {fmt_ratio(agg['weighted_error_per_note_fact'], pct=False)} |",
                  f"| Grounding-check pass rate (accepted / proposed) | {fmt_ratio(agg['grounding_pass_rate'])} |",
                  f"| Safety-net note facts covered | {fmt_ratio(agg['safety_net_recall'])} |",
                  f"| Accepted facts not in the note (not an error) | {fmt_ratio(agg['not_in_note_rate'])} |", "",
                  "Error taxonomy (counts; weights critical 5, major 3, minor 1): "
                  + ", ".join(f"{k} ({ERROR_CLASSES[k]}) {e[k]}" for k in ERROR_CLASSES)
                  + f"; weighted total {agg['weighted_error_total']}.", "",
                  "Recall by note section: " + "; ".join(f"{s} {fmt_ratio(r)}" for s, r in agg["recall_by_section"].items())
                  + ".", "",
                  f"Extraction parts: {agg['extraction_parts']['total']} ({agg['extraction_parts']['failed']} failed: "
                  f"{json.dumps(agg['extraction_parts']['failure_classes'])}); facts proposed {agg['facts']['proposed']}, "
                  f"accepted {agg['facts']['accepted']}; note facts {agg['facts']['note_facts']}.", "",
                  "| Consultation | status | parts | proposed | accepted | grounding pass | note facts | covered | recall | "
                  "contradicts | not in note | weighted errors |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for c in res["per_consultation"]:
            lines.append(f"| {c['consultation']} | {c['status']} | {c['parts']} | {c['proposed']} | {c['accepted']} | "
                         f"{c['grounding_pass_rate']} | {c['note_facts']} | {c['covered']} | {c['recall']} | "
                         f"{c['contradicts']} | {c['not_in_note']} | {c['weighted_error']} |")
        lines.append("")
    if human:
        lines += [f"Human agreement sample: {human.get('path')}"
                  + (f", {human['rows']} rows ({int(100 * HUMAN_FRACTION)}% of {human['decisions_total']} annotator "
                     f"decisions, rounded up, seed {HUMAN_SEED})" if human.get("rows") is not None else "")
                  + (f" ({human['human_labels_filled']} human labels filled)" if human.get("human_labels_filled") else "")
                  + "; Cohen's kappa: pending until a person fills human_label "
                  "(`python -I scripts/primock_gold_eval.py kappa --csv <folder>/human_review.csv`).", ""]
    lines += ["Deviations from the preregistration: " + " ".join(f"({i}) {d}" for i, d in
                                                            enumerate(res.get("deviations_from_preregistration") or [], 1)), ""]
    lines += ["Limitations: mock consultations (actors following case cards), primary care, not post-fall home care; "
              "English only; the reference note is a clinician's summary (it can state what was never said aloud, e.g. "
              "an impression, and leaves out much that was); a model annotator (one model, temperature 0) until the "
              "human sample is labelled; one generator run per consultation; transcripts are the human reference, "
              "not ASR. Engineering measurement, not clinical validation.", "",
              "Data: PriMock57 (Korfiatis et al., 2022; Babylon Health), CC BY 4.0; see ATTRIBUTION.txt.", ""]
    return "\n".join(lines)


def write_outputs(out: Path, redact, argv: list[str], stopped: str | None, *, human: bool) -> dict:
    records = B.read_records(out / "records.jsonl")
    res = build_results(records, argv, stopped)
    cons = {}
    for r in records:
        if r["type"] == "consultation":
            cons[r["consultation"]] = r
    hr = None
    if human and cons:
        hr = write_human_review(out, [cons[c] for c in res["data"]["order"] if c in cons])
    elif (out / "human_review.csv").exists():
        hr = write_human_review(out, [cons[c] for c in res["data"]["order"] if c in cons])   # reads, never rewrites
    res["human_review"] = hr
    (out / "results.json").write_text(redact(json.dumps(res, indent=2, ensure_ascii=False) + "\n"), encoding="utf-8")
    (out / "summary.md").write_text(redact(summary_md(res, hr)), encoding="utf-8")
    (out / "ATTRIBUTION.txt").write_text(ATTRIBUTION, encoding="utf-8")
    B.scrub_outputs(out, redact)
    return res


# ---------------------------------------------------------------------------------------------------------- prereg
def source_shas() -> dict:
    return {s: B.file_sha(ROOT / s) for s in SOURCES}


def make_prereg() -> dict:
    for p in (PROTOCOL, GUIDE):
        if not p.is_file():
            raise UsageError(f"{p} is missing: write the protocol and the guide first")
    return {"schema_version": PREREG_SCHEMA, "created_utc": utc_now(), "written_before_any_live_call": True,
            "protocol_sha256": B.file_sha(PROTOCOL), "annotation_guide_sha256": B.file_sha(GUIDE),
            "script_sha256": B.file_sha(ROOT / "scripts/primock_gold_eval.py"),
            "annotator_fixed_prompt_sha256": prompt_sha256(), "analysis_sha256": analysis_sha256(),
            "analysis": analysis_config(), "source_sha256": source_shas(),
            "annotator_prompt": {"system": ANNOTATOR_SYSTEM, "task_a": TASK_A, "task_b": TASK_B, "date_note": DATE_NOTE},
            "unit": "one PriMock57 consultation",
            "pilot": {"consultation": PILOT_CONSULTATION, "raw": "data/raw/primock57",
                      "role": "harness check; included again in the full run"},
            "full_run": {"raw": "data/raw/primock57_full", "consultations": "every consultation with a note and both "
                         "TextGrids, in the seeded processing order; a call cap stop leaves a random subset"},
            "call_cap_total": CALL_CAP_TOTAL,
            "primary_metrics": ["note_fact_recall (pooled)", "contradiction_rate (pooled)",
                                "weighted_error_per_note_fact (pooled)", "grounding_pass_rate (pooled)"],
            "secondary_metrics": ["macro means of the same", "safety_net_recall", "recall_by_section",
                                  "not_in_note_rate", "consistent_rate", "error_counts"],
            "human_check": "seeded 20% sample of annotator decisions in OUT/human_review.csv; Cohen's kappa via `kappa`"}


def check_prereg() -> dict:
    """The preregistration a live run needs: present, and the protocol, the guide, the annotator prompts and the
    analysis settings hash as recorded. The script's own hash may differ (recorded in the results as drift)."""
    if not PREREG.is_file():
        raise UsageError(f"{rel(PREREG)} is missing: run `prereg` before any live call")
    pr = json.loads(PREREG.read_text(encoding="utf-8"))
    checks = {"protocol_sha256": B.file_sha(PROTOCOL), "annotation_guide_sha256": B.file_sha(GUIDE),
              "annotator_fixed_prompt_sha256": prompt_sha256(), "analysis_sha256": analysis_sha256()}
    bad = [k for k, v in checks.items() if pr.get(k) != v]
    if bad:
        raise UsageError(f"the preregistration no longer matches: {', '.join(bad)} changed since {pr.get('created_utc')}")
    return {"created_utc": pr["created_utc"], "sha256": B.file_sha(PREREG), "script_sha256": pr.get("script_sha256")}


# ---------------------------------------------------------------------------------------------------------- CLI
def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prereg", help="write research/primock_gold_v1/preregistration.json (refuses to overwrite)")
    ap_ = sub.add_parser("amend", help="write preregistration_amendment_1.json: the seeded subset of a data folder")
    ap_.add_argument("--raw", required=True)
    ap_.add_argument("--subset", required=True, type=int, help="the first N consultations of the seeded order")
    ap_.add_argument("--deadline-utc", required=True, help="the stop time the run will use")
    ap_.add_argument("--reason", required=True)
    sp = sub.add_parser("split", help="print a note's atomic facts")
    sp.add_argument("--note", required=True, type=Path)
    rp = sub.add_parser("run", help="extraction + annotation")
    rp.add_argument("--raw", default=None, help="PriMock57 folder with notes/ and transcripts/")
    rp.add_argument("--consultations", default="all", help="comma-separated ids, or all")
    rp.add_argument("--out", default=None, help="new output folder (default release/benchmarks/primock_gold_<UTC>)")
    rp.add_argument("--resume", default=None, metavar="DIR")
    rp.add_argument("--api-key-file", default=None, help="file holding only the API key (else CARERELAY_LLM_API_KEY)")
    rp.add_argument("--base-url", default=None)
    rp.add_argument("--max-calls", type=int, default=CALL_CAP_TOTAL, help="cap on HTTP attempts in this invocation")
    rp.add_argument("--dry-run", action="store_true", help="no network: a scripted fake endpoint (harness check)")
    rp.add_argument("--amendment", default=None, help="run the seeded subset an `amend` file fixed (in its order)")
    rp.add_argument("--deadline-utc", default=None, help="ISO time (UTC): start no consultation that would likely end "
                                                       "after it (stopped_reason deadline; --resume continues)")
    gp = sub.add_parser("report", help="rebuild results.json, summary.md (and human_review.csv if absent)")
    gp.add_argument("--out", required=True, type=Path)
    gp.add_argument("--reparse", action="store_true", help="also write results_reparsed.json / summary_reparsed.md: "
                                                           "the stored annotator replies read again (no call)")
    kp = sub.add_parser("kappa", help="Cohen's kappa + raw agreement of a filled human_review.csv")
    kp.add_argument("--csv", required=True, type=Path)
    kp.add_argument("--json-out", default=None, type=Path)
    return ap.parse_args(argv)


def rel(p: Path) -> str:
    return B.rel(p)


def main(argv=None, *, transport=None, sleep=time.sleep, env=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    stdout, stderr = sys.stdout, sys.stderr
    redact = B.Redactor(None)
    try:
        args = parse_args(argv)
        if args.cmd == "prereg":
            if PREREG.exists():
                raise UsageError(f"{rel(PREREG)} exists; a preregistration is never overwritten")
            pr = make_prereg()
            PREREG.write_text(json.dumps(pr, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"wrote {PREREG.relative_to(ROOT).as_posix()} at {pr['created_utc']}; sha256 {B.file_sha(PREREG)}")
            return EXIT_OK
        if args.cmd == "amend":
            if AMENDMENT.exists():
                raise UsageError(f"{rel(AMENDMENT)} exists; an amendment is never overwritten")
            check_prereg()
            parse_deadline(args.deadline_utc)
            raw = Path(args.raw)
            raw = raw if raw.is_absolute() else (Path.cwd() / raw).resolve()
            ids = discover(raw)
            if not 1 <= args.subset <= len(ids):
                raise UsageError(f"--subset must be between 1 and {len(ids)}")
            order = processing_order(ids)
            am = {"schema_version": PREREG_SCHEMA + "-amendment", "created_utc": utc_now(),
                  "written_before_any_live_call_of_the_full_run": True, "amends": rel(PREREG),
                  "preregistration_sha256": B.file_sha(PREREG), "reason": args.reason, "raw": rel(raw),
                  "available": len(ids), "available_sha256": sha256_text(json.dumps(ids)),
                  "rule": f"the first {args.subset} consultations of processing_order(all available ids): sorted ids "
                          f"shuffled by random.Random('{ORDER_SEED}:order'); run in that order; a stop at the deadline "
                          "or the call cap leaves a prefix of it (still a seeded random subset)",
                  "subset": order[:args.subset], "pilot_in_subset": PILOT_CONSULTATION in order[:args.subset],
                  "deadline_utc": args.deadline_utc, "script_sha256": B.file_sha(ROOT / "scripts/primock_gold_eval.py"),
                  "deviations_so_far": list(DEVIATIONS), "analysis_sha256": analysis_sha256(),
                  "annotator_fixed_prompt_sha256": prompt_sha256()}
            AMENDMENT.write_text(json.dumps(am, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"wrote {rel(AMENDMENT)} at {am['created_utc']}; sha256 {B.file_sha(AMENDMENT)}; subset "
                  f"{args.subset} of {len(ids)}: {', '.join(am['subset'])}")
            return EXIT_OK
        if args.cmd == "split":
            obj = json.loads(args.note.read_text(encoding="utf-8"))
            for f in split_note(obj["note"] if isinstance(obj, dict) else str(obj)):
                print(json.dumps(f, ensure_ascii=False))
            return EXIT_OK
        if args.cmd == "kappa":
            rep = kappa_report(args.csv)
            text = json.dumps(rep, indent=2, ensure_ascii=False)
            if args.json_out:
                args.json_out.write_text(text + "\n", encoding="utf-8")
            print(text)
            return EXIT_OK
        if args.cmd == "report":
            records = B.read_records(args.out / "records.jsonl")
            end = next((r for r in reversed(records) if r.get("type") == "invocation_end"), {})
            last = next((r for r in reversed(records) if r.get("type") == "invocation"), {})
            res = write_outputs(args.out, redact, last.get("argv") or argv, end.get("stopped_reason"), human=True)
            if args.reparse:
                recs2, changed = reparse(records)
                res2 = build_results(recs2, last.get("argv") or argv, end.get("stopped_reason"))
                res2["reparse"] = {"what": "offline re-analysis: every stored annotator reply read again with read_reply "
                                           "(no model call); see deviations", "changed": changed}
                res2["human_review"] = res["human_review"]
                (args.out / "results_reparsed.json").write_text(
                    redact(json.dumps(res2, indent=2, ensure_ascii=False) + "\n"), encoding="utf-8")
                head = ("# PriMock57 external-reference evaluation (primock_gold_v1): offline re-parse of the stored "
                        "annotator replies (no model call)\n\nChanged by the re-parse: "
                        + (json.dumps(changed) if changed else "nothing") + ".")
                (args.out / "summary_reparsed.md").write_text(redact(summary_md(res2, res["human_review"]).replace(
                    "# PriMock57 external-reference evaluation (primock_gold_v1)", head, 1)), encoding="utf-8")
                print(f"wrote {args.out / 'results_reparsed.json'}, summary_reparsed.md; changed: {json.dumps(changed)}")
            print(f"wrote {args.out / 'results.json'}, summary.md; human review: {json.dumps(res['human_review'])}")
            return EXIT_OK
        key = B.load_api_key(args.api_key_file, env)
        redact = B.Redactor(key)
        sys.stdout, sys.stderr = B.RedactingStream(stdout, redact), B.RedactingStream(stderr, redact)
        if not args.dry_run and not key:
            raise UsageError("no API key: pass --api-key-file FILE (only the key in it) or set CARERELAY_LLM_API_KEY")
        if args.max_calls < 1:
            raise UsageError("--max-calls must be at least 1")
        if args.out and args.resume:
            raise UsageError("give --out DIR (a new run) or --resume DIR, not both")
        defaults = B.release_defaults()
        if args.resume:
            out = Path(args.resume)
            records = B.read_records(out / "records.jsonl") if (out / "records.jsonl").is_file() else []
            start = next((r for r in records if r.get("type") == "run_start"), None)
            if start is None or start.get("schema_version") != SCHEMA_VERSION:
                raise UsageError(f"--resume: {out} holds no run of this evaluation")
            cfg = dict(start["config"])
            if bool(args.dry_run) != cfg["dry_run"]:
                raise UsageError("--resume: a dry run and a live run cannot be mixed")
            models = next((r for r in reversed(records) if r.get("type") == "models"), None)
            if models and models.get("annotator"):
                cfg["annotator_model"] = models["annotator"]
                cfg["annotator_extra_body"] = dict(ANNOTATORS)[models["annotator"]]
            invocation = 1 + max((r["invocation"] for r in records if r.get("type") == "invocation"), default=0)
            prereg = start.get("preregistration")
            if not cfg["dry_run"]:
                check_prereg()
        else:
            if not args.raw:
                raise UsageError("--raw is required for a new run")
            raw = Path(args.raw)
            raw = raw if raw.is_absolute() else (Path.cwd() / raw).resolve()
            ids = discover(raw)
            amendment = None
            if args.amendment:
                am_path = Path(args.amendment)
                am = json.loads(am_path.read_text(encoding="utf-8"))
                if am.get("raw") != rel(raw) or not isinstance(am.get("subset"), list):
                    raise UsageError(f"the amendment is for {am.get('raw')}, not {rel(raw)}")
                if am.get("preregistration_sha256") != B.file_sha(PREREG):
                    raise UsageError("the amendment does not amend the current preregistration")
                gone = [c for c in am["subset"] if c not in ids]
                if gone:
                    raise UsageError(f"amendment consultations not found in {raw}: {', '.join(gone)}")
                amendment = {"path": rel(am_path), "created_utc": am["created_utc"], "sha256": B.file_sha(am_path),
                             "subset": len(am["subset"]), "available": am.get("available")}
            if args.amendment and args.consultations != "all":
                raise UsageError("give --amendment or --consultations, not both")
            if args.consultations != "all":
                want = [c.strip() for c in args.consultations.split(",") if c.strip()]
                missing = [c for c in want if c not in ids]
                if missing:
                    raise UsageError(f"not found in {raw} (note + both TextGrids): {', '.join(missing)}")
                ids = want
            if not ids:
                raise UsageError(f"no consultation with a note and both TextGrids in {raw}")
            prereg = None if args.dry_run else check_prereg()
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out = Path(args.out) if args.out else ROOT / "release" / "benchmarks" / f"primock_gold_{stamp}"
            if out.exists():
                raise UsageError(f"--out {out} already exists; choose a new folder (or --resume it)")
            if "token" in str(out).lower():
                raise UsageError("the output path must not contain 'token'")
            base = B.check_base_url(args.base_url or env.get("CARERELAY_LLM_BASE_URL")
                                    or defaults.get("CARERELAY_LLM_BASE_URL") or B.FALLBACK_BASE_URL)
            cfg = {"dry_run": bool(args.dry_run), "base_url": base, "raw": rel(raw),
                   "order": list(am["subset"]) if amendment else processing_order(ids), "amendment": amendment}
            invocation = 1
        cfg["max_calls"] = args.max_calls
        parse_deadline(args.deadline_utc)   # a usage problem before anything is sent
        cfg["deadline_utc"] = args.deadline_utc
        inner = transport or (DryTransport() if cfg["dry_run"] else B.UrllibTransport())
        tr = PausingTransport(inner, sleep=sleep) if not cfg["dry_run"] else inner   # a dry run sends nothing
        tr.paused_s = getattr(tr, "paused_s", 0.0)
        if not args.resume:
            out.mkdir(parents=True)
        writer = B.RecordWriter(out / "records.jsonl", redact)
        if invocation == 1:
            writer.write({"type": "run_start", "ts": utc_now(), "schema_version": SCHEMA_VERSION, "invocation": 1,
                          "config": {k: v for k, v in cfg.items() if k != "max_calls"}, "preregistration": prereg})
        writer.write({"type": "invocation", "ts": utc_now(), "invocation": invocation,
                      "argv": B.stored_argv(argv, redact), "created_utc": utc_now(), "git": B.git_info(),
                      "source_sha256": source_shas(), "max_calls": cfg["max_calls"], "transport": tr.name,
                      "deadline_utc": cfg["deadline_utc"],
                      "python": sys.version.split()[0]})
        print(endpoint_wording(B.endpoint_host(cfg["base_url"]), cfg["dry_run"]).split(". ")[0] + ".")
        run = Run(cfg, out, transport=tr, api_key=key, invocation=invocation, sleep=sleep)
        stopped, code = None, EXIT_OK
        try:
            stopped = run.run()
            code = EXIT_PARTIAL if stopped else EXIT_OK
        except KeyboardInterrupt:
            stopped, code = "interrupted", EXIT_INTERRUPTED
            print(f"interrupted; continue with --resume {out}")
        writer.write({"type": "invocation_end", "ts": utc_now(), "invocation": invocation, "stopped_reason": stopped,
                      "http_calls": run.budget.used, "paused_s": tr.paused_s})
        res = write_outputs(out, redact, B.stored_argv(argv, redact), stopped, human=stopped is None)
        agg = res["aggregate"] or {}
        print(f"{res['data']['consultations_done']}/{res['data']['consultations_planned']} consultations; recall "
              f"{fmt_ratio(agg.get('note_fact_recall'))}; contradiction rate {fmt_ratio(agg.get('contradiction_rate'))}; "
              f"weighted errors/note fact {fmt_ratio(agg.get('weighted_error_per_note_fact'), pct=False)}; grounding "
              f"pass {fmt_ratio(agg.get('grounding_pass_rate'))}; HTTP calls this invocation {run.budget.used}")
        print(f"wrote {out / 'records.jsonl'}, results.json, summary.md; human review: {json.dumps(res['human_review'])}")
        return code
    except UsageError as e:
        print(f"primock_gold_eval: {redact(str(e))}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        sys.stdout, sys.stderr = stdout, stderr


if __name__ == "__main__":
    sys.exit(main())
