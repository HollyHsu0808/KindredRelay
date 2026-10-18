"""CareRelay Case Agent: one open LLM, run in stages, with the case state held by the backend (case_store.py).

Stages (Product Difference Plan p.2): extract instructions from a transcript -> look up sources -> answer a
caregiver / propose updates -> regenerate content after a correction. Every LLM output is a PROPOSAL: the backend
validates citations, applies only allowed changes, and the guardrails check each reply before it is shown.
If a reply breaks a rule, the agent retries once with the violation as feedback; if it still fails, it shows a
deterministic safe reply built from the cited source. Reports record first-try / retry / fallback separately.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from change_engine import STOP_STEMS, canonical_time, correction_label
from guardrails import (CORRECTION_AS_ORDER_PATTERNS, EXTRA_CORRECTION_AS_ORDER_PATTERNS, GRADING_PATTERNS, added_facts,
                        check_item_content, check_reply, condition_coverage, condition_words_dropped, dose_facts, facts,
                        matches_extra, names_value, negation_count, norm, quote_negated, quote_negated_after, strip_quotes,
                        DOSE_WORDS, NUMBER_WORDS)

SYSTEM = """You are the CareRelay handover assistant. You help family caregivers who take turns caring for a resident.
Rules (follow all of them):
1. Use ONLY the case sources given below. Do not add medical advice, risk assessments or facts that are not in a source.
2. Never change, relax or grant an exception to an instruction. An observation (for example "she looks steady") does
   not change an instruction; only a clinician can. If someone asks for a change, keep the instruction, and propose a
   question for the care team (pending item type needs_clinical_confirmation).
3. When you state an instruction, quote its source sentence verbatim in double quotes and give the source id and revision.
4. If the caregiver's words leave out an instruction's condition, end your reply with exactly ONE short teach-back
   question (at most 20 words) that asks what they will do, e.g. "Before she gets out of bed, what will you do?"
5. A transcript correction means the transcript was wrong and the recording was always right. When a question is
   about a corrected time, say exactly that (name the transcript correction and the recording, state the corrected time).
   Never say that the doctor, clinic or care team changed, moved, rescheduled or updated anything because of a
   correction, and never start such an answer with "yes".
6. A family member's statement is not a clinician instruction. If it contradicts a source, do not change anything:
   propose a pending item of type conflict that names both claims and their sources.
7. Plain English, at most 90 words. Be kind and direct."""

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["reply", "citations", "situation", "pending_item", "handover_fix"],
    "properties": {
        "reply": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "required": ["source_id", "revision", "segment_id"],
                                                 "properties": {"source_id": {"type": "string"}, "revision": {"type": "string"},
                                                                "segment_id": {"type": "string"}}}},
        "situation": {"type": "string", "enum": ["question_about_instruction", "question_about_correction",
                                                 "time_changed_by_new_source", "family_claim", "other"]},
        "pending_item": {"type": "object", "additionalProperties": False, "required": ["type", "text"],
                         "properties": {"type": {"type": "string", "enum": ["none", "needs_clinical_confirmation",
                                                                            "needs_transcript_check", "conflict"]},
                                        "text": {"type": "string"}}},
        "handover_fix": {"type": "object", "additionalProperties": False, "required": ["item_id", "content"],
                         "properties": {"item_id": {"type": "string"}, "content": {"type": "string"}}},
    },
}
REWRITE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["content"],
                  "properties": {"content": {"type": "string"}}}
EXTRACT_SCHEMA = {  # supersedes: the active instruction a proposal replaces (empty if none); the backend validates it
    "type": "object", "additionalProperties": False, "required": ["instructions"],
    "properties": {"instructions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["action", "condition", "time", "quote", "segment_id", "supersedes"],
        "properties": {"action": {"type": "string"}, "condition": {"type": "string"}, "time": {"type": "string"},
                       "quote": {"type": "string"}, "segment_id": {"type": "string"}, "supersedes": {"type": "string"}}}}},
}
EXTRACT_FIELDS = ("action", "condition", "time", "quote", "segment_id")
SUPERSEDING_KINDS = ("new_clinician_source", "late_upload", "superseded_by_new_source")  # a real change of an instruction
# an instruction in force on the primary caregiver's confirmation only: a reply about it must carry these words and must
# not call it approved (a clinician has not confirmed it)
ON_BEHALF_WORDS = "on the clinician's behalf"
APPROVED_RX = re.compile(r"\b(?:has|have|had)\s+been\s+approved\b|\b(?:was|is|got)\s+approved\b|\bapproved\s+by\b", re.I)
RESTATE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["reply"], "properties": {"reply": {"type": "string"}}}


def _conjugate(action: str) -> str:
    w = action.split()
    return " ".join([w[0] + ("es" if w[0].endswith(("s", "sh", "ch")) else "s")] + w[1:]) if w else action


def segment_diff(before: str, after: str) -> dict:
    """The words that differ between two segment texts as a correction-shaped {from, to} (common leading and trailing
    words removed), for the rewrite checks when no explicit correction exists, e.g. a superseding recording."""
    a, b = before.split(), after.split()
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[-1 - j] == b[-1 - j]:
        j += 1
    frm, to = " ".join(a[i:len(a) - j]).strip(" .,;"), " ".join(b[i:len(b) - j]).strip(" .,;")
    return {"from": frm or before, "to": to or after}


TIME_WORDS = (r"\b(appointment|time|when|what time|reschedul\w*|chang\w*|mov\w*|moved|earlier|later|o'?clock|a\.m\.|p\.m\.|am|pm|"
              r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")
# words that carry no topic when matching an utterance to an instruction (the engine's stop stems plus question words)
STOP_WORDS = STOP_STEMS | {"are", "can", "did", "does", "had", "has", "have", "how", "it's", "its", "may", "not", "now", "she",
                           "that", "this", "was", "were", "what", "when", "will", "yes", "you"}


def _stems(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"[a-z']+", (text or "").lower()) if len(w) > 2 and w not in STOP_WORDS}


# What a family claim is about (CaseAgent._family_references). A claim is matched to the active instructions by its topic
# words: 4-letter stems, plus a concept tag for the usual other words for the same thing ("visit" and "check-up" are
# the appointment, "walk to the toilet alone" is getting up without help). Left out of the claim's topic words:
# who passed it on or how ("the clinic phoned", "the nurse told me"), words that only say when, and generic verbs
# ("bring", "need"), so that a claim never ties to an instruction through them.
REPORT_STEMS = {"clin", "doct", "nurs", "hosp", "phon", "call", "rang", "ring", "rung", "told", "tell", "said", "says", "sayi",
                "mess", "text", "fami", "daug", "son", "wife", "husb", "they", "them", "just", "repo", "clai", "phys",
                "rece", "offi", "spok", "spea", "talk", "conf", "upda"}
NUM_WORD = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
TIME_STEMS = {"time", "move", "chan", "resc", "canc", "post", "dela", "earl", "late", "push", "back", "forw", "brou", "tomo",
              "toni", "toda", "next", "week", "mont", "morn", "afte", "even", "noon", "midd", "midn", "nigh", "half", "past",
              "quar", "o'cl", "hour", "minu", "anot", "inst", "day", "days", "date", "sche", "from", "unti", "till", "befo",
              "sinc", "mond", "tues", "wedn", "thur", "frid", "satu", "sund", "one", "two", "thre", "four", "five", "six",
              "seve", "eigh", "nine", "ten", "elev", "twel", "twen", "thir", "fift", "fort"}
GENERIC_STEMS = {"brin", "take", "get", "gets", "gett", "need", "use", "want", "shou", "must", "have", "goin", "come", "make",
                 "give", "keep", "does", "didn", "don'", "isn'", "won'", "can'", "aren", "wasn", "coul", "woul", "any", "more",
                 "some", "anym", "long", "stil", "real", "out", "abou", "said", "fine", "okay", "allo", "goes", "thin", "know"}
# concept tags (matched on the words, for the claim and for each instruction's text alike)
CONCEPTS = {
    "#appointment": re.compile(r"\b(appointments?|visits?|check-?ups?|consult\w*|follow-?ups?|slot|booking)\b", re.I),
    "#getting-up": re.compile(r"\b(bed|get(ting|s)? up|walk\w*|stand\w*|toilet|bathroom|loo|commode|stairs?|unaided|unassisted|"
                              r"unaccompanied|independent\w*|alone|on (her|his|their) own|by (her|him|them)sel(f|ves)|"
                              r"(her|him)self|help\w*|assist\w*)\b", re.I),
}
# a claim that names a time: a clock time, a weekday or part of the day, "half past two", "it's now 2", "moved to two"
CLAIM_TIME_RX = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?|o'?clock)(?![a-z])|\b\d{1,2}:\d{2}\b|"
                           r"\b(?:at|now|to|until|till|by)\s+(?:\d{1,2}|" + NUM_WORD + r")\b(?![:\d%])|"
                           r"\b" + NUM_WORD + r"\s+o'?clock\b|\b(?:half|quarter)\s+(?:past|to)\b|"
                           r"\b(?:noon|midday|midnight|morning|afternoon|evening|tonight|tomorrow|"
                           r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
# ... or says only that something was moved ("the clinic moved it", "the visit is next week now", "it is cancelled")
CLAIM_SCHEDULE_RX = re.compile(r"\b(moved|changed|reschedul\w*|cancel+(ed|led)?|cancel\w*|postpon\w*|delayed|brought forward|"
                               r"pushed back|put back|earlier|later|another (time|day)|next week|this week|different time)\b", re.I)


def _concepts(text: str) -> set[str]:
    return {tag for tag, rx in CONCEPTS.items() if rx.search(text or "")}


def _topic(text: str) -> set[str]:
    """Topic words of an instruction's text: its stems and concept tags."""
    return _stems(text) | _concepts(text)


def _when(iso: str | None) -> str:
    """'2026-10-13T15:30' -> '13 Oct 15:30' (the recorded_at of a source, for a reply)."""
    if not iso:
        return "time not recorded"
    d = dt.datetime.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b %H:%M')}"


def _time_tokens(canon: str) -> set[str]:
    """'Wednesday 4:00 p.m.' -> {'wednesday', '4', '4:00'}: the facts a canonical time contributes to a text."""
    wd, ck = canon.split(" ", 1)
    return {wd.lower(), ck.split(":")[0], ck.split(" ")[0]}


def _shape_errors(prop) -> list[str]:
    """The answer JSON must have the schema's types (prompted-JSON mode has no schema enforcement)."""
    if not isinstance(prop, dict):
        return ["no valid JSON reply"]
    e = []
    if not isinstance(prop.get("reply"), str) or not prop.get("reply", "").strip():
        e.append("reply must be a non-empty string")
    if not isinstance(prop.get("citations", []), list) or not all(isinstance(c, dict) for c in prop.get("citations", [])):
        e.append("citations must be a list of objects")
    for k in ("pending_item", "handover_fix"):
        v = prop.get(k, {})
        if not isinstance(v, dict) or not all(isinstance(x, str) for x in v.values()):
            e.append(f"{k} must be an object with string fields")
    return e


class CaseAgent:
    def __init__(self, store, llm, resident_pronoun: str = "she"):
        self.store, self.llm, self.pron = store, llm, resident_pronoun
        self.log: list[dict] = []

    # ---------------------------------------------------------------- helpers
    def _context(self) -> str:
        s = self.store
        label = getattr(s, "confirmation_label", None)   # PropagatingStore only: how an approved version was confirmed
        items = [{"item_id": i, "kind": v[-1].get("kind"), "version": v[-1].get("version"), "review_status": v[-1].get("review_status"),
                  "content": v[-1].get("content"), "cites": v[-1].get("cites")} for i, v in s.items.items() if v[-1].get("kind") != "exported_pdf"]
        active = s.instruction_context()
        if label is not None:   # confirmed on the clinician's behalf: the model sees the label, never a bare 'approved'
            for x in items + active:
                lab = label(x.get("item_id") or x.get("instruction_id"))
                if lab:
                    x["confirmation"] = lab
        ctx = {"case_id": s.case_id, "case_version": s.case_version, "active_instructions": active,
               "items": items, "transcript_corrections": s.correction_context(),
               "open_pending_items": [p for p in s.pending if p["status"] == "open"]}
        if label is not None:
            ctx["awaiting_clinician"] = s.awaiting_clinician()
        for c in ctx["transcript_corrections"]:
            c["recording_says"] = s.recording_says(c["source_id"], c["segment_id"])
        return json.dumps(ctx, ensure_ascii=False, indent=1)

    def _source_texts(self) -> list[str]:
        return self.store.current_source_texts()

    def _call(self, stage: str, user: str, schema: dict, name: str) -> dict:
        if self.llm is None:  # no language model configured: every stage goes straight to its deterministic fallback
            return {"text": "", "json": None, "latency_s": 0.0, "json_mode": "none", "usage": None}
        r = self.llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], json_schema=schema, schema_name=name)
        self.log.append({"stage": stage, "user": user[-1500:], "text": r["text"], "json_mode": r["json_mode"],
                         "latency_s": r["latency_s"], "usage": r.get("usage")})
        return r

    @staticmethod
    def _unavailable(r: dict) -> bool:
        """The endpoint gave no reply at all (eval_care_cases.py --fail-soft hands back an empty 'unavailable' result
        after the client's own retries): nothing to check, and asking again with feedback would only repeat the wait."""
        return r.get("json_mode") == "unavailable"

    def _conditional(self) -> list[dict]:
        return [i for i in self.store.instruction_context() if i.get("condition")]

    def _corrected_values(self) -> list[str]:
        return [v for c in self.store.corrections for v in (c["from"], c["to"])]

    def _correction_scope(self, text: str) -> str | None:
        """How the correction rules (B-P10) apply to an utterance or reply. 'reply': to the whole text, when it names a
        corrected value (literally, or its bare hour: 'from 10 to 11') or asks about a time whose instruction was last
        changed by the transcript correction. 'sentences': a newer clinician source really changed the instruction
        since the correction, so the honest answer is that the time changed; then only sentences that name a corrected
        value are held to the rule ('the doctor moved it from 10 to 11' stays forbidden). None: the rules do not apply."""
        if not self.store.corrections:
            return None
        superseded = self._last_change_kind(self._relevant_instruction(text)) in SUPERSEDING_KINDS
        if names_value(text, self._corrected_values()):
            return "sentences" if superseded else "reply"
        if not re.search(TIME_WORDS, text, re.I):
            return None
        return None if superseded else "reply"

    def _about_correction(self, text: str) -> bool:
        """Is this utterance (or reply) about a corrected value? Then the correction rules apply (see _correction_scope)."""
        return self._correction_scope(text) is not None

    def _last_change_kind(self, ins: dict | None) -> str | None:
        """Kind of the change that last touched an instruction (`last_change.kind`, set by the store/engine)."""
        full = self.store.instructions.get(ins["instruction_id"]) if ins else None
        return ((full or {}).get("last_change") or {}).get("kind")

    def _superseded_by_source(self, utterance: str) -> dict | None:
        """The instruction a time question is about, if a newer clinical source changed its time (not a correction) and
        that change stands: its last change is the superseding source (a rejection resets it) and its time differs
        from the last approved one."""
        if not re.search(TIME_WORDS, utterance, re.I):
            return None
        ins = self._relevant_instruction(utterance)
        full = self.store.instructions.get(ins["instruction_id"]) if ins else None
        if full and self._last_change_kind(ins) in SUPERSEDING_KINDS and full.get("previous") and full.get("time") \
                and full.get("time") != full["previous"].get("time"):
            return ins
        return None

    def _relevant_instruction(self, utterance: str) -> dict | None:
        """The active instruction whose words overlap most with the utterance. Ties: a question about a time prefers
        a timed instruction, otherwise a conditional one. Its current and previous time count as words, so 'Is it
        still Thursday?' finds the appointment that moved."""
        ctx = self.store.instruction_context()
        if not ctx:
            return None
        words, about_time = _stems(utterance), bool(re.search(TIME_WORDS, utterance, re.I))

        def score(i):
            prev = self.store.instructions.get(i["instruction_id"], {}).get("previous") or {}
            text = " ".join([i.get("action") or "", i.get("condition") or "", i.get("time") or "", prev.get("time") or ""]
                            + [c.get("text") or "" for c in i["cites"]])
            return (len(words & _stems(text)), about_time and bool(i.get("time")), bool(i.get("condition")))
        return max(ctx, key=score)

    # ---------------------------------------------------------------- stage: answer a caregiver
    def answer(self, utterance: str, actor: str, mode: str = "question") -> dict:
        """mode 'question': a caregiver asks something. mode 'family_statement': a family member reports a claim
        (source_type family_statement); it can never change the case, at most open a conflict item."""
        s = self.store
        conditional = bool(self._conditional())
        expect_tb = mode == "question" and self._looks_like_condition_question(utterance)
        required = []
        if expect_tb:  # the reply must state the condition word for word, not a paraphrase that drops it
            required.append([c["text"] for i in self._conditional() for c in i["cites"] if c.get("text")])
        if mode == "question" and self._about_correction(utterance):
            required.append([c["to"] for c in s.corrections])
        sup = self._superseded_by_source(utterance) if mode == "question" else None
        if sup:  # a moved time: the reply must state the current time or the current source sentence
            required.append([c["text"] for c in sup["cites"] if c.get("text")] + [sup["time"]])
        on_behalf = bool(sup) and sup["instruction_id"] in (getattr(s, "awaiting_clinician", lambda: [])() or [])
        if on_behalf:   # in force on the primary caregiver's confirmation only: the reply says so, never 'approved'
            required.append([ON_BEHALF_WORDS])
        refs = self._family_references(utterance) if mode == "family_statement" else []
        if refs:  # the sentence the claim is about, word for word (the third real run quoted an unrelated instruction)
            required.append(self._ref_texts(refs))
        expected = " or ".join(self._ref_where(r) for r in refs)
        framing = (f"The caregiver ({actor}) says: \"{utterance}\"" if mode == "question" else
                   f"A family member ({actor}) reports (source_type family_statement, NOT a clinician instruction): \"{utterance}\"")
        # what the first real LLM run (Qwen3-8B) got wrong on the first try, spelled out next to the question
        guidance = []
        if mode == "family_statement":
            quote = (f"quote the current case sentence this claim is about, word for word in double quotes with its source id: "
                     f"{expected}; quote or name no other source" if refs else
                     'no case source is about this claim: say "Nothing in the case sources says this yet." and quote or name '
                     "no source")
            guidance.append("Rules for this reply: do not repeat the family member's claim as a fact; say that a report from "
                            f"family cannot change the case on its own; {quote}; say that both have been recorded for the care "
                            "team to confirm; do not say that anyone changed, moved or rescheduled anything; ask no question; "
                            "pending item type conflict.")
        elif expect_tb:
            guidance.append("Rules for this reply: quote the instruction's source sentence verbatim in double quotes with its source "
                            "id and revision; do not grant what is asked; end with exactly one short teach-back question; pending "
                            "item type needs_clinical_confirmation (a question for the care team).")
        if on_behalf:
            guidance.append("This instruction was confirmed by the primary caregiver on the clinician's behalf and the clinician has not "
                            "confirmed it yet. Say exactly that (the words \"on the clinician's behalf\" must appear); do not say it has "
                            "been approved.")
        if mode == "question" and self._correction_scope(utterance) == "reply":
            to = ", ".join(c["to"] for c in s.corrections)
            guidance.append(f"This question is about a time that was corrected in the transcript after the recording was checked "
                            f"(the recording always said {to}). Say so in plain words: mention the transcript correction and the "
                            "recording, state the corrected time, and do not say that the doctor or clinic changed anything.")
        prompt = (f"CASE SOURCES AND STATE (JSON):\n{self._context()}\n\n"
                  f"{framing}\n\n"
                  "Write the reply, list the exact citations you used (source_id, revision, segment_id), classify the "
                  "situation, propose at most one pending item (type none if not needed) and, if a handover item left out "
                  "an instruction's condition, propose corrected content for that item (item_id empty if none)."
                  + "".join("\n\n" + g for g in guidance))
        attempts, feedback, no_reply = [], "", False
        for attempt in (1, 2):
            r = self._call("answer", prompt + feedback, ANSWER_SCHEMA, "answer")
            if self._unavailable(r):
                attempts.append({"attempt": attempt, "unavailable": "no reply from the model"})
                no_reply = True
                break
            prop = r["json"]
            viol = _shape_errors(prop)
            reply = prop.get("reply", "") if not viol else ""
            if not viol:
                viol = self._check(reply, utterance, mode, expect_tb, conditional, required, citations=prop.get("citations", []))
                if on_behalf and APPROVED_RX.search(reply):
                    viol.append("calls content approved that only the primary caregiver confirmed on the clinician's behalf "
                                "(the clinician has not confirmed it)")
            attempts.append({"attempt": attempt, "violations": viol})
            if not viol:
                return self._apply_answer(prop, utterance, actor, attempts, mode,
                                          method="llm_first_try" if attempt == 1 else "llm_after_retry", expect_tb=expect_tb)
            missed = (f"\nThe reply must quote this case sentence word for word, in double quotes, and name its source id: "
                      f"{expected}" if refs else "")
            feedback = ("\n\nYOUR PREVIOUS REPLY WAS REJECTED by the safety check for these reasons:\n- " + "\n- ".join(viol) + missed
                        + f"\nPrevious reply: {reply!r}\nWrite a new reply that follows every rule. Keep the pending_item and "
                        "handover_fix you proposed unless they were a reason for the rejection.")
        fb = self._fallback_answer(utterance, expect_tb, mode)
        fb_viol = self._check(fb["reply"], utterance, mode, expect_tb, conditional, required, citations=fb["citations"])
        attempts.append({"attempt": "fallback", "violations": fb_viol})
        if fb_viol:
            # A deterministic proposal still has to pass the reply check. Do not apply rejected
            # source text: _apply_answer can create pending items and handover versions too.
            return {"reply": "I could not safely answer from the case sources. Please ask the care team.",
                    "citations": [], "dropped_citations": [], "situation": "other",
                    "pending_item": None, "pending_method": None, "handover_fix": None,
                    "handover_fix_method": None, "method": "blocked", "attempts": attempts,
                    "violations": list(fb_viol)}
        return self._apply_answer(fb, utterance, actor, attempts, mode, method="fallback_unavailable" if no_reply else "fallback",
                                  expect_tb=expect_tb)

    def _check(self, reply: str, utterance: str, mode: str, expect_tb: bool, conditional: bool, required: list,
               citations: list | None = None) -> list[str]:
        """check_reply with this case's sources. citations: the reply's own (None: not known, e.g. a test row); a quote
        and a dose are then bound to the valid ones (red team WS-02, MD-06)."""
        scope = self._correction_scope(utterance + " " + reply)
        refs = self._family_references(utterance) if mode == "family_statement" else None
        return check_reply(reply, has_conditional_instruction=conditional, has_transcript_correction=scope == "reply",
                           source_texts=self._source_texts(), expect_teach_back=expect_tb, caregiver_text=utterance,
                           required_any=required, family_statement=mode == "family_statement",
                           corrected_values=self._corrected_values() if scope == "sentences" else [],
                           correction_question=scope == "reply" and mode == "question",
                           family_reference=None if refs is None else self._ref_texts(refs),
                           family_reference_ids=self._ref_ids(refs) if refs else [],
                           other_source_ids=self._other_source_ids(refs) if refs is not None else [],
                           source_groups=self._source_groups(),
                           cited_texts=None if citations is None else self._cited_texts(citations))

    def _source_groups(self) -> dict[str, list[str]]:
        """Each source id -> the current sentences a reply may quote under it: its latest revision's segments and, for a
        transcript and the recording it transcribes, each other's (the same words; the family references own both ids)."""
        s = self.store
        own = {}
        for (sid, rev), src in s.sources.items():
            if rev == s.latest_revision(sid):
                own.setdefault(sid, []).extend(g["text"] for g in src["segments"].values() if g.get("text"))
        groups = {sid: list(t) for sid, t in own.items()}
        for (sid, rev), src in s.sources.items():
            rec = src.get("transcribes")
            if rev == s.latest_revision(sid) and rec in own:
                groups[sid] += own[rec]
                groups[rec] += own.get(sid, [])
        return groups

    def _cited_texts(self, citations: list) -> list[str]:
        """The current texts of the valid citations (latest revision, existing segment; a citation of a whole source
        stands for all its segments), with the same segment of the recording a cited transcript transcribes and of the
        transcripts of a cited recording."""
        s, out = self.store, []
        for c in citations or []:
            if not s.cite_is_valid(c):
                continue
            sid, seg = c["source_id"], c.get("segment_id")
            if not seg:
                out += [g["text"] for g in s.sources[(sid, c["revision"])]["segments"].values() if g.get("text")]
                continue
            out += [s.segment_text(sid, c["revision"], seg), s.recording_says(sid, seg)]
            out += [src["segments"].get(seg, {}).get("text") for (tid, rev), src in s.sources.items()
                    if src.get("transcribes") == sid and rev == s.latest_revision(tid)]
        return [t for t in out if t]

    @staticmethod
    def _looks_like_condition_question(u: str) -> bool:
        return bool(re.search(r"\b(can|could|may|is it ok|is it fine|allowed|on (her|his) own|by (her|him)self|alone|"
                              r"without (help|assistance)|independently)\b", u, re.I))

    def _fix_problem(self, item_id: str, content: str, cites: list[dict]) -> str | None:
        """Why a handover fix may not be applied (None = it may). A conversation may only RESTORE a condition that a
        handover item left out, using the item's own current source."""
        s = self.store
        if item_id not in s.items:
            return "unknown item"
        cur = s.latest(item_id)
        if cur.get("kind") != "handover_item":
            return "only handover items can be fixed from a conversation"
        item_sources = {c["source_id"] for c in cur.get("cites", [])}
        if not {c["source_id"] for c in cites} & item_sources:
            return "the fix does not rest on the item's own source"
        conds = [i for i in self._conditional() if {c["source_id"] for c in i["cites"]} & item_sources]
        if not conds:
            return "no conditional instruction rests on this item's source"
        if all(condition_coverage(cur.get("content", ""), i["condition"]) >= 0.6 for i in conds):
            return "the item already states the condition"
        viol = check_item_content(content, must_not_contain=[c["from"] for c in s.corrections], forbid_relaxing=True)
        if viol:
            return "; ".join(viol)
        if not all(condition_coverage(content, i["condition"]) >= 0.6 for i in conds):
            return "the fix does not restore the instruction's condition"
        for i in conds:
            lost = condition_words_dropped(content, i["condition"], " ".join(self._current_text(c) or "" for c in i["cites"]))
            if lost:   # a rejected fix falls back to the verbatim source sentence
                return f"the fix leaves out words of the condition that the source states: {', '.join(lost)}"
        cited_text = " ".join(s.segment_text(c["source_id"], s.latest_revision(c["source_id"]), c["segment_id"]) or ""
                              for c in cur.get("cites", []))
        stray = [n for n in re.findall(r"\d+(?::\d+)?", content) if n not in cited_text]
        if stray:  # e.g. a time relayed by family, or the pre-correction time
            return f"the fix states numbers that are not in the item's current source: {stray}"
        return None

    def _deterministic_fix(self, cites: list[dict]) -> dict | None:
        """Label of the handover item + the verbatim source sentence, for an item that left the condition out."""
        s = self.store
        for ins in self._conditional():
            c = ins["cites"][0]
            if cites and c["source_id"] not in {x["source_id"] for x in cites}:
                continue
            for iid, versions in s.items.items():
                cur = versions[-1]
                if cur.get("kind") == "handover_item" and any(x["source_id"] == c["source_id"] for x in cur.get("cites", [])) \
                        and condition_coverage(cur.get("content", ""), ins["condition"]) < 0.6:
                    label = cur["content"].split(":", 1)[0] if ":" in cur.get("content", "") else "Note"
                    return {"item_id": iid, "content": f"{label}: {c['text']}"}
        return None

    def _apply_answer(self, prop: dict, utterance: str, actor: str, attempts: list, mode: str, method: str,
                      expect_tb: bool = False) -> dict:
        s = self.store
        cites = [c for c in prop.get("citations", []) if s.cite_is_valid(c)]
        dropped = [c for c in prop.get("citations", []) if not s.cite_is_valid(c)]
        pending, pending_method = None, method
        p = prop.get("pending_item") or {}
        if mode == "family_statement":
            # the backend writes the conflict record from what it knows, so both claims carry their source labels; a
            # family reply may cite only the sentence the claim is about
            refs = self._family_references(utterance)
            keys = {norm(x).lower() for x in self._ref_texts(refs)}
            dropped += [c for c in cites if norm(s.segment_text(c["source_id"], c["revision"], c["segment_id"]) or "").lower() not in keys]
            cites = [c for c in cites if c not in dropped]
            said = "; ".join(f'{r["label"]} says: "{r["text"]}"' for r in refs) if refs else "no case source covers this"
            pending = s.add_pending("conflict", f'family_statement ({actor}) says: "{utterance}"; {said}',
                                    [{"source_id": r["source_id"], "revision": r["revision"]} for r in refs])
        elif p.get("type") in ("needs_clinical_confirmation", "needs_transcript_check", "conflict") and p.get("text"):
            pending = s.add_pending(p["type"], p["text"], [{"source_id": c["source_id"], "revision": c["revision"]} for c in cites])
        elif mode == "question" and expect_tb:
            # Product rule, not the model's choice (A-P4): a caregiver asking whether a condition can be dropped always
            # opens one question for the care team. In the first real run the LLM proposed it on attempt 1 and dropped
            # it when it rewrote the reply on attempt 2; the backend now writes it whenever the model did not.
            ins = self._relevant_instruction(utterance)
            if ins and ins.get("condition"):
                c = ins["cites"][0]
                already = any(q["type"] == "needs_clinical_confirmation" and q.get("status") == "open"
                              and any(x["source_id"] == c["source_id"] for x in q.get("cites", [])) for q in s.pending)
                if not already:
                    asked = " ".join(utterance.split())[:300]
                    pending = s.add_pending("needs_clinical_confirmation",
                                            f'Caregiver ({actor}) asked: "{asked}" Should this instruction be reviewed: "{c["text"]}"?',
                                            [{"source_id": c["source_id"], "revision": c["revision"]}])
                    pending_method = "backend_rule"
        fix_result, fix_method = None, None
        fx = prop.get("handover_fix") or {}
        if fx.get("item_id") and mode == "family_statement":
            fix_result = {"rejected": "a family statement cannot change case content"}
        elif fx.get("item_id"):
            why = self._fix_problem(fx["item_id"], fx.get("content", ""), cites)
            if why is None:
                cur = s.latest(fx["item_id"])
                fix_result, fix_method = s.propose_version(fx["item_id"], fx["content"], cur.get("cites"),
                                                           reason="condition restored after caregiver question"), method
            else:
                det = self._deterministic_fix(cites)
                if det and self._fix_problem(det["item_id"], det["content"], cites) is None:
                    cur = s.latest(det["item_id"])
                    fix_result = s.propose_version(det["item_id"], det["content"], cur.get("cites"),
                                                   reason="condition restored after caregiver question (verbatim source)")
                    fix_method = "fallback"
                else:
                    fix_result = {"rejected": why}
        return {"reply": prop.get("reply", ""), "citations": cites, "dropped_citations": dropped, "situation": prop.get("situation"),
                "pending_item": pending, "pending_method": pending_method if pending else None,
                "handover_fix": fix_result, "handover_fix_method": fix_method, "method": method, "attempts": attempts}

    def _current_text(self, c: dict) -> str | None:
        """The text of a cited segment in its source's latest revision (what a reply may quote)."""
        s = self.store
        rev = s.latest_revision(c["source_id"])
        return (s.segment_text(c["source_id"], rev, c["segment_id"]) if rev else None) or c.get("text")

    def _family_references(self, utterance: str) -> list[dict]:
        """The case sentences a family member's claim is about: what a family-statement reply must quote, the deterministic
        reply quotes and the conflict record names. Rule:
        1. The claim's topic words: its 4-letter stems and concept tags (CONCEPTS: "visit" or "check-up" is the
           appointment; "walk", "toilet", "alone", "help" are getting up with assistance), leaving out stop words, who
           passed the claim on (REPORT_STEMS), words that only say when (TIME_STEMS) and generic verbs (GENERIC_STEMS).
        2. Each active instruction is scored (direct, timed, condition): direct = topic words shared with its action, time,
           previous time and current source sentence; timed = the claim names a time or a move (CLAIM_TIME_RX,
           CLAIM_SCHEDULE_RX) and the instruction states a time; condition = topic words shared with its condition only.
        3. Candidates: instructions with direct > 0. A claim with no topic word left that names a time or a move ("The
           clinic phoned me, it's now two o'clock", "they moved it") is about the timed instructions (the engine files such
           a statement against the timed one too). The condition never makes a candidate; it and timed only break ties.
        4. The candidates with the highest score win (exact ties are all kept: a claim about two things may quote either).
        For each, the reference is the recording sentence when the transcript segment the instruction cites was corrected
        (the corrected transcript's current sentence is accepted too), else the cited segment in its source's latest
        revision. No candidate: [] (nothing in the case sources is about the claim; the reply must say so and quote and
        name no source)."""
        s = self.store
        u = re.sub(r"\bcare team\b", " ", utterance or "", flags=re.I)
        own = _stems(u) - REPORT_STEMS - TIME_STEMS - GENERIC_STEMS
        words = own | _concepts(u)
        names_time = bool(CLAIM_TIME_RX.search(u) or CLAIM_SCHEDULE_RX.search(u))
        scored = []
        for i in s.instruction_context():
            prev = s.instructions.get(i["instruction_id"], {}).get("previous") or {}
            texts = [self._current_text(c) or "" for c in i["cites"]]
            direct = " ".join([i.get("action") or "", i.get("time") or "", prev.get("time") or ""] + texts)
            has_time = bool(i.get("time")) or any(CLAIM_TIME_RX.search(x) for x in texts)
            key = (len(words & _topic(direct)), names_time and has_time, len(words & _topic(i.get("condition") or "")))
            if key[0] > 0 or (not words and names_time and has_time):
                scored.append((key, i))
        best = max((k for k, _ in scored), default=None)
        refs = []
        for k, i in scored:
            r = self._reference_for(i) if k == best else None
            if r and all((r["source_id"], r["segment_id"]) != (x["source_id"], x["segment_id"]) for x in refs):
                refs.append(r)
        return refs

    def _reference_for(self, ins: dict) -> dict | None:
        """The sentence an instruction rests on now: the recording's, when the transcript segment it cites was corrected
        (the recording was always right), else the cited segment in its source's latest revision. 'accept' lists the
        texts a reply may quote for it: for a recording reference also the corrected transcript's current sentence
        (the same words in Case B; 'blood-pressure diary' for the recording's 'blood pressure diary' in Case C)."""
        s = self.store
        c = ins["cites"][0] if ins.get("cites") else None
        if c is None:
            return None
        base = {"instruction_id": ins["instruction_id"], "segment_id": c["segment_id"]}
        cur = self._current_text(c)
        if any(x["source_id"] == c["source_id"] and x["segment_id"] == c["segment_id"] for x in s.corrections):
            tx = next((src for (sid, _), src in s.sources.items() if sid == c["source_id"]), {})
            rec_id, text = tx.get("transcribes"), s.recording_says(c["source_id"], c["segment_id"])
            if rec_id and text:
                alt = ({"source_id": c["source_id"], "revision": s.latest_revision(c["source_id"]), "segment_id": c["segment_id"],
                        "text": cur} if cur and norm(cur).lower() != norm(text).lower() else None)
                return {**base, "source_id": rec_id, "revision": s.latest_revision(rec_id), "label": f"{rec_id} recording",
                        "text": text, "accept": [text] + ([cur] if alt else []), "alt": alt,
                        "own_ids": [rec_id, c["source_id"]]}
        return {**base, "source_id": c["source_id"], "revision": s.latest_revision(c["source_id"]), "label": c["source_id"],
                "text": cur, "accept": [cur], "alt": None, "own_ids": [c["source_id"]]} if cur else None

    @staticmethod
    def _ref_texts(refs: list[dict]) -> list[str]:
        """Every text a family-statement reply may quote for these references (the required group)."""
        out = []
        for r in refs:
            out += [x for x in r["accept"] if x and x not in out]
        return out

    @staticmethod
    def _ref_where(r: dict) -> str:
        rec = r["label"].endswith(" recording")
        out = (f'"{r["text"]}" (source {r["source_id"]}, revision {r["revision"]}, segment {r["segment_id"]}'
               + (": the recording, which the corrected transcript was checked against)" if rec else ")"))
        a = r.get("alt")
        return out + (f' or the corrected transcript\'s "{a["text"]}" (source {a["source_id"]}, revision {a["revision"]}, '
                      f'segment {a["segment_id"]})' if a else "")

    def _ref_ids(self, refs: list[dict]) -> list[str]:
        """Source ids a family-statement reply may name: the references' own (a recording reference also owns the
        transcript it was checked against) and those whose latest revision has one of the accepted sentences."""
        s = self.store
        keys = {norm(x).lower() for x in self._ref_texts(refs)}
        mine = {sid for r in refs for sid in r["own_ids"]}
        mine |= {sid for (sid, rev), src in s.sources.items() if rev == s.latest_revision(sid)
                 and any(norm(g.get("text") or "").lower() in keys for g in src["segments"].values())}
        return sorted(mine)

    def _other_source_ids(self, refs: list[dict]) -> list[str]:
        """Source ids a family-statement reply may not name: every source of the case except _ref_ids(refs)."""
        return sorted({sid for (sid, _) in self.store.sources} - set(self._ref_ids(refs)))

    def _fallback_answer(self, utterance: str, expect_tb: bool, mode: str = "question") -> dict:
        """Deterministic safe reply built from the cited source (used after two rejected LLM replies)."""
        s = self.store
        none_fix = {"item_id": "", "content": ""}
        none_pending = {"type": "none", "text": ""}
        if mode == "family_statement":
            refs = self._family_references(utterance)
            said = " ".join(f'The recording ({r["source_id"]}) says: "{r["text"]}"' if r["label"].endswith(" recording") else
                            f'The source ({r["source_id"]}, revision {r["revision"]}) says: "{r["text"]}"'
                            for r in refs) or "Nothing in the case sources says this yet."
            how = "A phone message reported by family" if re.search(r"\b(phon|call|rang|messag|text)", utterance, re.I) else \
                "A report from family"
            reply = (f"Thank you for telling us. {how} cannot change the case on its own. "
                     f"{said} I have recorded {'both' if refs else 'it'} for the care team to confirm.")
            cites = [{k: r[k] for k in ("source_id", "revision", "segment_id")} for r in refs]
            return {"reply": reply, "citations": cites, "situation": "family_claim",
                    "pending_item": {"type": "conflict", "text": "(written by the backend)"}, "handover_fix": none_fix}
        if s.corrections and self._about_correction(utterance):
            c = s.corrections[-1]
            waiting = s.pending_review_count()
            tail = (" The updated items are waiting for review." if waiting else " The updated items have been reviewed.")
            opener = "No. " if (c["from"] in utterance or re.search(r"\b(chang|mov|reschedul)\w*", utterance, re.I)) else ""
            reply = (f"{opener}The recording has always said {c['to'].rstrip('.')}. The first transcript wrongly said {c['from']}; it was "
                     f"corrected after the recording was checked ({c['source_id']}, transcript revision {c['new_revision']}). That is a "
                     "transcript correction, not a new instruction from the clinic." + tail)
            cites = [{"source_id": c["source_id"], "revision": c["new_revision"], "segment_id": c["segment_id"]}]
            sup = self._superseded_by_source(utterance) if mode == "question" else None
            if sup is not None:   # the corrected time was later really changed by a newer clinician source: say both, in order
                sr = self._supersession_reply(sup)
                reply += " Since then, " + sr["reply"][:1].lower() + sr["reply"][1:]
                cites += sr["citations"]
            return {"reply": reply, "citations": cites, "situation": "question_about_correction",
                    "pending_item": none_pending, "handover_fix": none_fix}
        sup = self._superseded_by_source(utterance) if mode == "question" else None
        if sup is not None:
            return self._supersession_reply(sup)
        ins = self._relevant_instruction(utterance)
        if ins is None:
            return {"reply": "I could not find an active instruction about this in the case sources. Please ask the care team.",
                    "citations": [], "situation": "other", "pending_item": none_pending, "handover_fix": none_fix}
        c = ins["cites"][0]
        reply = f"The current instruction says: \"{c['text']}\" (source {c['source_id']}, revision {c['revision']})."
        pending, fix = none_pending, none_fix
        if expect_tb and ins.get("condition"):
            reply += (" Only a clinician can decide otherwise, so I have added a question for the care team."
                      f" Before {self.pron} {_conjugate(ins['action'])}, what will you do?")
            pending = {"type": "needs_clinical_confirmation", "text": f"Should this instruction be reviewed: \"{c['text']}\"?"}
            fix = self._deterministic_fix([c]) or none_fix
        return {"reply": reply, "citations": [{k: c[k] for k in ("source_id", "revision", "segment_id")}],
                "situation": "question_about_instruction", "pending_item": pending, "handover_fix": fix}

    def _supersession_reply(self, ins: dict) -> dict:
        """Deterministic reply when a newer clinician source changed an instruction's time: names the source and its
        recording time, quotes the current sentence and says whether it is still awaiting review."""
        s = self.store
        full, c = s.instructions[ins["instruction_id"]], ins["cites"][0]
        src = s.sources.get((c["source_id"], c["revision"]), {})
        what = "recording" if src.get("transcribes") or src.get("source_type") == "clinician_recording" else "instruction"
        noun = "appointment" if "appointment" in (ins.get("action") or "") else (ins.get("action") or "instruction")
        cob = full.get("confirmed_on_behalf") if full.get("derivation_status") == "approved" else None
        status = ("It is awaiting review." if full.get("derivation_status") == "pending_review"
                  else "It was confirmed by the primary caregiver on the clinician's behalf; the clinician has not confirmed it yet."
                  if cob and not full.get("clinician_confirmed") else "It has been approved.")
        reply = (f"The {noun} time was changed by a new clinician {what} ({src.get('transcribes') or c['source_id']}, recorded "
                 f"{_when(src.get('recorded_at'))}). The current instruction says: \"{c['text']}\" {status}")
        return {"reply": reply, "citations": [{k: c[k] for k in ("source_id", "revision", "segment_id")}],
                "situation": "time_changed_by_new_source", "pending_item": {"type": "none", "text": ""},
                "handover_fix": {"item_id": "", "content": ""}}

    # ---------------------------------------------------------------- stage: teach-back answer
    def teach_back_answer(self, instruction_id: str, question: str, response: str, actor: str) -> dict:
        """Store the caregiver's answer verbatim (no automatic scoring) and restate the source sentence."""
        s = self.store
        rec = s.record_teach_back(instruction_id, question, response, actor)
        ins = next(i for i in s.instruction_context() if i["instruction_id"] == instruction_id)
        src = ins["cites"][0]["text"]
        prompt = (f"Instruction source sentence (verbatim): \"{src}\"\nCondition: {ins.get('condition')}\n"
                  f"The caregiver answered the teach-back question \"{question}\" with: \"{response}\"\n"
                  "Write a short reply (at most 60 words) that quotes the source sentence verbatim in double quotes and points "
                  "out the part of the condition their answer left out, if any. Do not score, grade or praise them. No question.")
        method, reply, feedback = "fallback", "", ""
        for attempt in (1, 2):
            r = self._call("teach_back", prompt + feedback, RESTATE_SCHEMA, "restate")
            if self._unavailable(r):
                method = "fallback_unavailable"
                break
            cand = (r["json"] or {}).get("reply", "") if isinstance(r["json"], dict) else ""
            cand = cand if isinstance(cand, str) else ""
            viol = [] if cand else ["no reply"]
            if cand and norm(src).lower().rstrip(".") not in norm(cand).lower():
                viol.append("does not quote the source sentence verbatim")
            body = strip_quotes(cand, self._source_texts() + [response])
            if cand and any(re.search(p, body, re.I) for p in GRADING_PATTERNS):
                viol.append("grades or praises the caregiver (teach-back answers are recorded, never scored)")
            if cand and not self._points_out_missing(body, response, ins.get("condition")):
                viol.append("does not point out the part of the condition the caregiver's answer left out")
            viol += check_reply(cand, has_conditional_instruction=True, has_transcript_correction=False,
                                source_texts=self._source_texts(), expect_teach_back=False, caregiver_text=response) if cand else []
            if not viol:
                method, reply = ("llm_first_try" if attempt == 1 else "llm_after_retry"), cand
                break
            feedback = "\n\nYOUR PREVIOUS REPLY WAS REJECTED:\n- " + "\n- ".join(viol) + f"\nPrevious reply: {cand!r}"
        if not reply:
            reply = f"Thank you, your answer is recorded. The instruction says: \"{src}\" Please note the part about {ins.get('condition')}."
            fb_viol = check_reply(reply, has_conditional_instruction=True, has_transcript_correction=False,
                                  source_texts=self._source_texts(), expect_teach_back=False, caregiver_text=response)
            if fb_viol:
                return {"record": rec, "reply": "Your answer is recorded. I could not safely restate the instruction. Please ask the care team.",
                        "method": "blocked", "violations": list(fb_viol)}
        return {"record": rec, "reply": reply, "method": method}

    @staticmethod
    def _points_out_missing(body: str, response: str, condition: str | None) -> bool:
        """If the caregiver's answer leaves out part of the condition, the reply (outside quotes) must name it."""
        stems = lambda t: {w[:3] for w in re.findall(r"[a-z]+", (t or "").lower()) if len(w) >= 3}  # noqa: E731
        stop = {"onl", "wit", "the", "and", "for"}
        missing = stems(condition) - stems(response) - stop
        return not missing or bool(missing & stems(body))

    # ---------------------------------------------------------------- stage: regenerate content after a correction
    @staticmethod
    def _facts(text: str, exclude: str) -> set[str]:
        """Numbers (also as words), times, weekdays and months in text (outside the corrected value): must survive a
        rewrite. The same definition as guardrails.facts, so the 'lost' and the 'added' checks never disagree."""
        return facts(text, exclude)

    @staticmethod
    def _time_pair(correction: dict) -> tuple[list[str], list[str]] | None:
        """([old weekday, old clock], [new weekday, new clock]) when both sides of a correction are canonical times
        ('Thursday 11:00 a.m.' -> 'Wednesday 4:00 p.m.'), else None (a literal correction such as '10:00 a.m.')."""
        o, n = canonical_time(correction.get("from")), canonical_time(correction.get("to"))
        return (o.split(" ", 1), n.split(" ", 1)) if o and n else None

    def _rewrite_problems(self, cand: str, old: str, correction: dict, keep: list[str]) -> list[str]:
        """Why a rewrite may not be used. A literal correction must appear verbatim and the old value must be gone;
        a time pair (a superseded appointment time) must show the new weekday and clock, not the old clock (nor the
        old weekday if it differs), without requiring any particular wording. Every other fact must survive, no fact
        (time, number, weekday) may be added, and no sentence may relax an instruction."""
        pair = self._time_pair(correction)
        if pair:
            (ow, oc), (nw, nc) = pair
            must, must_not = [nw, nc] + keep, ([oc] if oc != nc else []) + ([ow] if ow != nw else [])
            drop_old, drop_new = _time_tokens(canonical_time(correction["from"])), _time_tokens(canonical_time(correction["to"]))
        else:
            must, must_not, drop_old, drop_new = [correction["to"]] + keep, [correction["from"]], set(), set()
        v = check_item_content(cand, must, must_not, forbid_relaxing=True) if cand else ["empty rewrite"]
        if cand:
            # a transcript correction is not a change by the clinic; a supersession IS one, so the wording is not forbidden there
            if correction.get("kind") != "superseded_by_new_source" and (any(re.search(p, cand, re.I) for p in CORRECTION_AS_ORDER_PATTERNS)
                                                                        or matches_extra(cand, EXTRA_CORRECTION_AS_ORDER_PATTERNS)):
                v.append("describes the correction as a change by the clinic")
            lost = (self._facts(old, correction["from"]) - drop_old) - (self._facts(cand, correction["to"]) - drop_new)
            if lost:
                v.append(f"drops or changes other facts: {sorted(lost)}")
            added = added_facts(old, cand, drop_new | facts(correction["to"]))
            if added:
                v.append(f"adds facts that are not in the item or the correction: {sorted(added)}")
            if not 0.5 <= len(cand) / max(len(old), 1) <= 2.0:
                v.append("changes the length too much (rewrite only the corrected part)")
        return v

    def regenerate_after_correction(self, correction: dict) -> dict:
        """All or nothing: if anything fails halfway (e.g. the LLM server), the case is restored as it was."""
        s = self.store
        snap = s.snapshot()
        try:
            return self._regenerate(correction)
        except Exception:
            s.restore(snap)
            raise

    def rewrite_item(self, old_item: dict, segment_before: str, segment_after: str, keep: list[str],
                     correction: dict | None = None) -> tuple[str | None, str]:
        """Ask the LLM to rewrite one stale item for the corrected (or superseding) segment: at most two attempts, each
        checked by _rewrite_problems. Returns (content, method), or (None, "fallback") when no attempt passed so the
        caller applies its deterministic substitution. `correction` is the {from, to, kind} the checks use: the
        corrected words, or (kind superseded_by_new_source) the old and new canonical time of a moved instruction;
        without one it is the words that differ between the two segments. This is also the store's `rewriter` hook
        (change_engine.PropagatingStore), which passes `correction` as a keyword argument."""
        if correction is None:
            correction = segment_diff(segment_before, segment_after)
        kind = old_item.get("kind")
        if correction.get("kind") == "superseded_by_new_source":
            head = (f"A newer clinician recording replaced the sentence this {kind} rests on: its time changed from "
                    f"\"{correction['from']}\" to \"{correction['to']}\".\nSegment before: \"{segment_before}\"\n"
                    f"Segment after (current): \"{segment_after}\"\n"
                    f"Rewrite this {kind} so it states the new time. Change only the time; keep every other fact and the same style and length.")
        else:
            head = (f"A transcript was corrected after checking the recording: \"{correction['from']}\" is now \"{correction['to']}\".\n"
                    f"Segment before: \"{segment_before}\"\nSegment after (correct): \"{segment_after}\"\n"
                    f"Rewrite this {kind} so it matches the corrected segment. Change only what the correction changes; "
                    f"keep every other fact and the same style and length.")
        prompt = head + f"\nCurrent content: \"{old_item['content']}\""
        for attempt in (1, 2):
            r = self._call("regenerate", prompt, REWRITE_SCHEMA, "rewrite")
            if self._unavailable(r):
                return None, "fallback_unavailable"
            cand = (r["json"] or {}).get("content", "") if isinstance(r["json"], dict) else ""
            cand = cand if isinstance(cand, str) else ""
            viol = self._rewrite_problems(cand, old_item["content"], correction, keep)
            if not viol:
                return cand, ("llm_first_try" if attempt == 1 else "llm_after_retry")
            prompt += f"\nYour previous answer {cand!r} was rejected: {'; '.join(viol)}."
        return None, "fallback"

    def _regenerate(self, correction: dict) -> dict:
        s = self.store
        res = s.apply_transcript_correction(correction)
        out = {"impact": res, "items": {}, "needs_person": []}
        for item_id in res["impact_set"]:
            old = s.latest(item_id)
            keep = [w for w in ("medication list",) if w in old["content"].lower()]
            content, method = self.rewrite_item(old, res["record"]["segment_before"], res["record"]["segment_after"], keep, correction=correction)
            if content is None:
                content = re.sub(re.escape(correction["from"]), correction["to"], old["content"], flags=re.I)
                if self._rewrite_problems(content, old["content"], correction, keep):
                    out["needs_person"].append(item_id)  # stays 'stale': a person rewrites it
                    out["items"][item_id] = {"version": old.get("version"), "content": old["content"], "method": "needs_person"}
                    continue
            v = s.supersede_with(item_id, content, res["new_revision"], correction["source_id"])
            out["items"][item_id] = {"version": v["version"], "content": content, "method": method}
        for iid in res["affected_instructions"]:
            ins = s.instructions[iid]
            t = ins.get("time")
            new_time = re.sub(re.escape(correction["from"]), correction["to"], t, flags=re.I) if t else t
            s.update_instruction_from_revision(iid, new_time, res["new_revision"], correction["source_id"])
        for iid in res["repointable_instructions"]:  # same segment text, so the citation may point at the new revision
            ins = s.instructions[iid]
            ins["cites"] = [{**c, "revision": res["new_revision"]} if c["source_id"] == correction["source_id"] else c for c in ins["cites"]]
        s.bump_case_version()
        label = correction_label(correction["from"], [s.instructions[i].get("action") or "" for i in res["affected_instructions"]])
        out["notice"] = (f"{label} corrected from {correction['from']} to {correction['to']} (transcript correction, checked "
                         f"against the recording). Items awaiting review: {s.pending_review_count()}.")
        if out["needs_person"]:
            out["notice"] += f" Items a person must rewrite: {', '.join(out['needs_person'])}."
        return out

    # ---------------------------------------------------------------- stage: extract instructions from a transcript
    def extract_instructions(self, segments: list[dict]) -> dict:
        """segments: [{segment_id, text}] from a transcript_result. Returns grounded proposals + rejected ones. With a
        case store, the active instructions are listed so a proposal can name the one it replaces (`supersedes`); an
        id not in the case is dropped, and the backend's own suggestion is attached for a person to tick."""
        listing = "\n".join(f"[{g['segment_id']}] {g['text']}" for g in segments)
        active = self.store.instruction_context() if self.store is not None else []
        prompt = ("Below is a clinician-caregiver conversation transcript, one segment per line with its id in brackets.\n"
                  "List every care instruction the clinician gives (medication, mobility, diet, appointments, warning signs). "
                  "For each: action, condition (empty string if none), time (empty string if none), the exact quote (copied "
                  "verbatim from ONE segment, at least 4 words), that segment_id, and supersedes: the instruction_id of the "
                  "active instruction it replaces (same action, e.g. a moved appointment), else an empty string. Do not invent "
                  "instructions.\n\n" + listing)
        if active:
            prompt += "\n\nACTIVE INSTRUCTIONS (instruction_id: action; time):\n" + "\n".join(
                f"{i['instruction_id']}: {i['action']}; {i.get('time') or 'no time'}" for i in active)
        r = self._call("extract", prompt, EXTRACT_SCHEMA, "instructions")
        props = (r["json"] or {}).get("instructions", []) if isinstance(r["json"], dict) else []
        by_id = {g["segment_id"]: g["text"] for g in segments}
        grounded, rejected = [], []
        for p in props if isinstance(props, list) else []:
            if not isinstance(p, dict) or not all(isinstance(p.get(k, ""), str) for k in EXTRACT_FIELDS + ("supersedes",)):
                rejected.append({"proposal": p, "reason": "wrong shape"})
                continue
            why = self._grounding_problem(p, by_id.get(p.get("segment_id", "")))
            if why:
                rejected.append({**p, "reason": why})
                continue
            p = {**p, "supersedes": p.get("supersedes") or ""}
            if self.store is not None:
                if p["supersedes"] and p["supersedes"] not in self.store.instructions:
                    p["supersedes_dropped"], p["supersedes"] = p["supersedes"], ""
                if hasattr(self.store, "suggest_supersedes"):   # PropagatingStore: pre-ticked in the UI, a person decides
                    p["suggested_supersedes"], p["suggested_overlap"] = self.store.suggest_supersedes(p["action"])
            grounded.append(p)
        return {"instructions": grounded, "rejected": rejected, "latency_s": r["latency_s"], "json_mode": r["json_mode"]}

    @staticmethod
    def _grounding_problem(p: dict, seg: str | None) -> str | None:
        if seg is None:
            return "unknown segment_id"
        q = norm(p.get("quote", "")).lower().strip(" .,;:!?")
        if len(q.split()) < 4:
            return "quote shorter than 4 words"
        if q not in norm(seg).lower():
            return "quote not found in the cited segment"
        # "take ibuprofen with ..." out of "Do not take ibuprofen with ..." reverses the instruction (red team PQ-03; the
        # rule is guardrails.quote_negated, the extractor's own copy of the family timeline's, read a little wider: PQ-04..07)
        es = norm(seg).lower()
        spots = [m.start() for m in re.finditer(re.escape(q), es)]
        if spots and all(quote_negated(es, i) for i in spots):
            return "the quote follows a negation (not, can't, avoid, stop, ...)"
        # ... or is negated by the rest of its clause ("Taking ibuprofen with it | is not allowed", red team HO-04)
        if spots and all(quote_negated(es, i) or quote_negated_after(es, i + len(q)) for i in spots):
            return "a negation after the quote, in its clause, reverses it (is not allowed, must be avoided, ...)"
        # ... and so does an action that drops a negation of its own quote (PQ-08), or adds one ("Take the iron tablets"
        # -> "do not take the iron tablets", metamorphic MR1); a negation of the condition it states ("Keep taking the
        # tablets even if she does not feel pain") stays with the condition, in the quote and in the action
        cond = norm(p.get("condition", "")).lower().strip(" .,;:!?")
        act = norm(p.get("action", "")).lower()
        a_neg, q_neg = negation_count(act.replace(cond, " ", 1) if cond else act), negation_count(q.replace(cond, " ", 1) if cond else q)
        if a_neg < q_neg:
            return "the action leaves out a negation its quote states (not, stop, avoid, ...)"
        if a_neg > q_neg:
            return "the action states a negation its quote does not (not, stop, avoid, ...)"
        # every number and every dose, interval or count per day of the action must be the quote's (red team MD-05); a
        # clock 'H:00' in the action is the quote's 'H a.m.' / 'H p.m.' / 'H o'clock' (third review N2); a dose word that
        # facts() does not count ('forty', 'fifteen') is its digits here too (metamorphic MR2)
        nums = lambda t: ({f for f in facts(t) if f[:1].isdigit() or f == "half"}  # noqa: E731
                          | {DOSE_WORDS[w] for w in re.findall(r"[a-z]+", t.lower()) if w in DOSE_WORDS and w not in NUMBER_WORDS})
        clock_hours = {h + ":00" for h in re.findall(r"(?<![\d:.])(\d{1,2})(?::00)?\s*(?:a\.?m\.?|p\.?m\.?|o'?clock)(?![a-z])", q)}
        stray = sorted((nums(p.get("action", "")) - nums(q) - clock_hours) | (dose_facts(p.get("action", "")) - dose_facts(q)))
        if stray:
            return f"action states numbers or doses the quote does not: {', '.join(stray)}"
        if p.get("time") and not all(d in seg for d in re.findall(r"\d+", p["time"])):
            return "time not stated in the cited segment"
        if p.get("condition") and condition_coverage(seg, p["condition"]) < 0.5:
            return "condition not stated in the cited segment"
        return None

    # ---------------------------------------------------------------- stage: family statement
    def family_statement(self, utterance: str, actor: str) -> dict:
        """A family member's claim never changes the case; a contradiction becomes a conflict pending item."""
        before = self.store.snapshot_hashes()
        res = self.answer(utterance, actor, mode="family_statement")
        changed = [k for k, v in self.store.snapshot_hashes().items() if before.get(k) != v]
        return {**res, "state_changed": changed}


def baseline_answer(llm, scenario: dict, utterance: str) -> dict:
    """The plan's comparison: same LLM, same sources, plain 'source Q&A + summary' (no state, tools or guardrails)."""
    texts = []
    for s in scenario["sources"]:
        for g in s.get("segments") or s.get("segments_spoken", []):
            texts.append(f"{s['source_id']} {s['revision']} {g['segment_id']}: {g.get('text') or g.get('audio_says')}")
    r = llm.chat([{"role": "system", "content": "You answer caregivers' questions using the sources below."},
                  {"role": "user", "content": "SOURCES:\n" + "\n".join(texts) + f"\n\nQuestion: {utterance}"}])
    return {"reply": r["text"].strip(), "latency_s": r["latency_s"]}
