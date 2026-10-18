#!/usr/bin/env python3
"""Deterministic HandoffReplay system evaluation. No network or trained model.

python scripts/eval_handoff_replay.py --out release/validation_abd/replay

Uses the fictional repository story and an explicitly injected response fixture.
Exit 0 only when every system assertion passes; failures are saved and exit 1.
This is not a model accuracy, calibration or clinical correctness evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "handoff_day1" / "agent"))
from episode import Episode, load_scenario
from episode_qa import episode_answerer, refresh, sentence_units
from evidence_gate import FactChecker
from episode_events import RevisionConflict


class InjectedVerifier:
    """Fixed fixture response to exercise wiring; contains no learned parameters."""
    def __init__(self, status="supported_by_model", fail=False):
        self.card = {"stage": "full", "validation_operating_point_found": True, "run_id": "injected-system-fixture-v1"}
        self.status, self.fail, self.calls = status, fail, 0

    def check(self, source, claim, question=""):
        self.calls += 1
        if self.fail:
            raise RuntimeError("injected operational failure")
        return {"status": self.status, "model_id": self.card["run_id"], "threshold": 0.8,
                "support_score": 0.99, "latency_ms": 0.0}


def evaluate():
    story = load_scenario(ROOT / "handoff_day1" / "care_cases" / "episode_hip_fracture.json")
    checks = []
    def require(name, condition):
        checks.append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)
    ep = Episode(story)
    verifier = InjectedVerifier()
    checker = FactChecker(verifier, "shadow")
    for source in story["updates"]:
        ep.add_update(source, evidence_checker=checker)
    require("full_story_has_no_rule_rejections", not any(e["rejected"] for e in ep.entries))
    require("shadow_checks_recorded", all(e["evidence_checks"] for e in ep.entries if e["facts"]))
    calls = verifier.calls
    q, _ = ep.add_question("When is the fracture clinic appointment?", "mia")
    ep.add_question(q["text"], "david")
    ep.set_answered(q["qid"], update_id="u09", by="anna")
    ep.mark_read("mia")
    answer = episode_answerer(None)(ep, "When is the fracture clinic appointment?")
    restored = Episode.from_snapshot(json.loads(json.dumps(ep.to_snapshot())))
    require("snapshot_status_equal", restored.status() == ep.status())
    require("snapshot_qa_labels_equal", sentence_units(restored) == sentence_units(ep))
    require("snapshot_manual_questions_equal", restored.questions == ep.questions)
    require("snapshot_read_state_equal", restored.seen == ep.seen and restored.seen_at == ep.seen_at)
    require("replay_does_not_call_verifier", calls == verifier.calls)
    old = ep.to_snapshot()
    try:
        ep.revise_update("u09", {"text": "New words with no extraction."}, expected_revision=0,
                         request_id="stale", facts=[])
    except RevisionConflict:
        pass
    else:
        raise AssertionError("stale revision must fail")
    require("stale_revision_rolls_back", ep.to_snapshot() == old)
    original = next(u for u in story["updates"] if u["update_id"] == "u09")
    changed = original["text"].replace("Monday 30 November", "Tuesday 1 December")
    if changed == original["text"]:
        # Explicit checked words rather than relying on a particular fixture phrase.
        changed = "The fracture clinic appointment is on Tuesday 1 December at 10:30."
    facts = [{"type": "follow_up", "what": "Fracture clinic appointment", "when_text": "Tuesday 1 December at 10:30",
              "when": "2026-12-01T10:30", "quote": "The fracture clinic appointment is on Tuesday 1 December at 10:30"}]
    # Replacing the entire source deliberately removes all prior u09 facts. The
    # command records an explicit extraction for this corrected source only.
    changed = facts[0]["quote"] + "."
    result = ep.revise_update("u09", {"text": changed}, expected_revision=1, request_id="correction",
                              facts=facts, evidence_checker=checker)
    require("correction_revision_advanced", result["source_revision"] == 2)
    require("correction_old_checks_not_current", all(c["source_revision"] == 2 for c in result["evidence_checks"]))
    require("correction_reopens_answered_question", next(x for x in ep.questions if x["qid"] == q["qid"])["status"] == "open")
    refreshed = refresh(ep, answer)
    require("correction_invalidates_qa_selection", refreshed["source_changed"])
    require("qa_never_reuses_corrected_source_sid", all(u["source_revision"] == 2 for u in refreshed["quotes"] if u["update_id"] == "u09"))
    same = ep.revise_update("u09", {"text": changed}, expected_revision=1, request_id="correction", facts=facts, evidence_checker=checker)
    require("correction_retry_idempotent", same == result and ep.source_revision("u09") == 2)
    late = Episode(story)
    late.add_update(next(u for u in story["updates"] if u["update_id"] == "u07"))
    late.add_update(next(u for u in story["updates"] if u["update_id"] == "u05"))
    require("late_arrival_keeps_newer_plan", late.slots["expected_discharge"]["fact"]["when"] == "2026-10-24")
    require("late_arrival_label", any(ln["late"] for ln in late.entries[-1]["lines"]))
    for mode in ("shadow", "gate"):
        error_ep = Episode(story)
        failed = error_ep.add_update(story["updates"][0], evidence_checker=FactChecker(InjectedVerifier(fail=True), mode))
        require(f"{mode}_inference_failure_audited", all(c["reason"] == "inference_error" for c in failed["evidence_checks"]))
        require(f"{mode}_failure_policy", bool(failed["facts"]) == (mode == "shadow"))
        require(f"{mode}_raw_source_retained", error_ep.updates[0]["text"] == story["updates"][0]["text"])
    ep.delete_update("u09", expected_revision=2, request_id="withdraw")
    require("deleted_source_absent_from_projection", not any(e["update_id"] == "u09" for e in ep.entries))
    require("deleted_source_retained_in_history", len(ep.source_history("u09")) == 3)
    require("final_snapshot_replay_equal", Episode.from_snapshot(ep.to_snapshot()).to_snapshot() == ep.to_snapshot())
    return checks, ep


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "handoff_day1" / "agent" / name for name in
               ("episode.py", "episode_events.py", "episode_qa.py", "evidence_gate.py", "kr_runtime.py")]
    report = {"evaluation": "deterministic-system-only", "trained_model_used": False,
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    try:
        checks, episode = evaluate()
        report.update(status="passed", checks=checks, executed=len(checks), passed=len(checks),
                      episode_revision=episode.state_revision)
        (out / "episode_snapshot.json").write_text(json.dumps(episode.to_snapshot(), indent=2), encoding="utf-8")
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    (out / "replay_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "executed", "passed", "error") if k in report}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
