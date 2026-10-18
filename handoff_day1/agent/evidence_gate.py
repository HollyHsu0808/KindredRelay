"""Optional verification of extracted facts. Raw-source extractive QA is separate.

off preserves the original rules; shadow records decisions; gate withholds any
non-supported or operationally unverifiable fact. Scores are not clinical truth.
"""
from __future__ import annotations

import datetime as dt
import functools
import hashlib
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from episode_events import digest

CLAIM_RENDERER_VERSION = "complete-fields-v1"
CHECK_VERSION = "source-fact-verification-v1"


def claim_from_fact(f):
    """Every declared non-calendar field is represented, including family.who.

    Absolute dates resolved from relative wording are checked separately rather
    than pretending the model saw that calendar date in its source.
    """
    from episode import FACT_FIELDS
    f = f.get("_source_fact", f)
    t = f.get("type")
    if t not in FACT_FIELDS:
        return ""
    req, opt = FACT_FIELDS[t]
    names = {"what": "statement", "who": "person", "when_text": "stated time",
             "status": "medication action", "condition": "condition"}
    fields = [f"{names.get(k, k)}: {f[k]}" for k in (*req, *opt) if k != "when" and f.get(k)]
    return t.replace("_", " ") + "; " + "; ".join(fields)


def date_check(update, fact):
    """Conservative deterministic date check; ambiguous wording stays unverified.

    Covers an explicit ISO date, today/yesterday/tomorrow and the next named
    weekday. Does not claim arbitrary natural-language date understanding.
    """
    from episode import CLOCK, WEEKDAYS, norm, parse_when
    value = fact.get("when")
    if not value:
        return {"status": "not_applicable"}
    parsed, at = parse_when(value), parse_when(update.get("at"))
    if parsed is None or not isinstance(at, dt.datetime):
        return {"status": "needs_review", "reason": "invalid_date"}
    if update.get("hospital_timezone"):
        at = at.astimezone(ZoneInfo(update["hospital_timezone"]))
    day = parsed.date() if isinstance(parsed, dt.datetime) else parsed
    phrase = norm(fact.get("when_text") or fact.get("quote") or "")
    expected = None
    explicit = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", phrase)
    if len(set(explicit)) == 1:
        try:
            expected = dt.date.fromisoformat(explicit[0])
        except ValueError:
            return {"status": "needs_review", "reason": "invalid_source_date", "resolved": value}
    else:
        relative = [(word, offset) for word, offset in (("today", 0), ("yesterday", -1), ("tomorrow", 1))
                    if re.search(rf"\b{word}\b", phrase)]
        named = [i for i, word in enumerate(WEEKDAYS) if re.search(rf"\b{word}\b", phrase)]
        if len(relative) == 1:
            expected = at.date() + dt.timedelta(days=relative[0][1])
        elif len(named) == 1 and not re.search(r"\b(last|previous|ago|next week)\b", phrase):
            expected = at.date() + dt.timedelta(days=(named[0] - at.weekday()) % 7)
    if expected != day:
        return {"status": "needs_review", "reason": "ambiguous_or_mismatched_calendar_date", "resolved": value}
    if isinstance(parsed, dt.datetime):
        # A clock requires a matching explicit HH:MM or h a.m./p.m. token.
        clocks = []
        for h, m, ampm in re.findall(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b", phrase):
            if not m and not ampm:
                continue
            hour = int(h)
            if ampm:
                hour = hour % 12 + (12 if ampm.startswith("p") else 0)
            clocks.append((hour, int(m or 0)))
        if (parsed.hour, parsed.minute) not in clocks:
            return {"status": "needs_review", "reason": "clock_not_deterministically_matched", "resolved": value}
    return {"status": "matched", "resolved": value, "policy": "explicit-iso-relative-next-weekday-v1"}


def _identity(update, fact):
    claim = claim_from_fact(fact)
    source_fact = fact.get("_source_fact", fact)
    context = {k: update.get(k) for k in ("at", "kind", "speaker", "photo_of", "reading", "hospital_timezone")}
    # Keep existing journals verifiable; explicit speaker classifications bind new checks.
    if update.get("speaker_type") is not None:
        context["speaker_type"] = update["speaker_type"]
    return {"check_version": CHECK_VERSION, "claim_renderer_version": CLAIM_RENDERER_VERSION,
            "update_id": update["update_id"], "source_revision": update.get("source_revision", 1),
            "source_sha256": hashlib.sha256((update.get("text") or "").encode("utf-8")).hexdigest(),
            "source_context_sha256": digest(context),
            "claim_sha256": hashlib.sha256(claim.encode("utf-8")).hexdigest(),
            "question_sha256": hashlib.sha256(b"").hexdigest(),
            "fact_id": fact["fact_id"], "fact_sha256": digest(source_fact), "claim": claim,
            "scope": "source_local_fields; inherited context has separate evidence"}


def bind_check(update, fact, result):
    if result.get("status") not in ("supported_by_model", "needs_review", "unverified"):
        raise ValueError("unknown evidence verification status")
    result = {**result, **_identity(update, fact), "date_check": date_check(update, fact),
              "quote": fact.get("quote", ""), "fact_type": fact["type"]}
    result["withhold"] = result["mode"] == "gate" and (
        result["status"] != "supported_by_model" or result["date_check"]["status"] == "needs_review")
    result["verification_id"] = digest({k: v for k, v in result.items() if k not in ("latency_ms", "verification_id")})
    return result


def check_is_fresh(update, fact, result):
    expected = _identity(update, fact)
    return (all(result.get(k) == v for k, v in expected.items())
            and result.get("verification_id") == digest({k: v for k, v in result.items()
                                                         if k not in ("latency_ms", "verification_id")}))


class FactChecker:
    def __init__(self, verifier, mode="shadow"):
        if mode not in ("shadow", "gate"):
            raise ValueError("mode must be shadow or gate")
        if mode == "gate" and (verifier.card.get("stage") != "full"
                               or verifier.card.get("validation_operating_point_found") is not True):
            raise ValueError("Gate requires a full model with a useful validation operating point. Use shadow first.")
        self.verifier, self.mode = verifier, mode

    def __call__(self, update, fact):
        claim = claim_from_fact(fact)
        try:
            result = self.verifier.check(update.get("text", ""), claim)
        except Exception as exc:
            result = {"status": "unverified", "reason": "inference_error", "error_type": type(exc).__name__}
        return {**result, "mode": self.mode,
                "model_id": result.get("model_id", self.verifier.card.get("run_id", "unknown")),
                "model_artifact_sha256": digest(self.verifier.card), "claim": claim}


@functools.lru_cache(maxsize=2)
def _load(bundle, mode, threads):
    from kr_runtime import EvidenceVerifier
    return FactChecker(EvidenceVerifier(bundle, device="cpu", threads=threads), mode)


def checker_from_env():
    mode = os.getenv("KINDRED_VERIFIER_MODE", "off").lower()
    if mode == "off":
        return None
    if mode not in ("shadow", "gate"):
        raise ValueError("KINDRED_VERIFIER_MODE must be off, shadow or gate")
    bundle = os.getenv("KINDRED_VERIFIER_DIR", "").strip()
    if not bundle:
        raise ValueError("Set KINDRED_VERIFIER_DIR to the offline model folder")
    threads = int(os.getenv("KINDRED_VERIFIER_THREADS", "2"))
    if threads < 1:
        raise ValueError("KINDRED_VERIFIER_THREADS must be positive")
    return _load(str(Path(bundle).resolve()), mode, threads)


def render_audit_panel(st, episode):
    if os.getenv("KINDRED_VERIFIER_MODE", "off").lower() == "off":
        return
    with st.expander("Evidence verification · experimental", expanded=False):
        st.caption("Checks extracted facts against their source. Raw-source answers use separate quote checks. Scores are model outputs, not probabilities of medical correctness.")
        st.caption("A hospital name inherited from an earlier location keeps that earlier source as its evidence; it is not a new assertion by this update.")
        entries = [e for e in episode.entries if e.get("evidence_checks")]
        if not entries:
            st.info("Add an update to run verification. Earlier updates are not retroactively checked.")
            return
        entry = max(entries, key=lambda e: e["seq"])
        for result in entry["evidence_checks"]:
            st.write(result["claim"])
            st.caption(f"{result['status']} · {result['mode']} · {result.get('model_id', 'model unavailable')}")
            if result.get("reason") == "inference_error":
                st.warning(f"Verification unavailable ({result.get('error_type', 'unknown error')}).")
            if result.get("withhold"):
                st.warning("This extracted statement is held for review. The original source remains available.")
            if result["date_check"]["status"] == "needs_review":
                st.caption("The resolved calendar date needs checking against the source wording.")
