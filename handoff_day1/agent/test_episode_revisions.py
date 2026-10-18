"""Deterministic revision/replay and verifier wiring regressions; no model calls.

Run: python agent/test_episode_revisions.py (from handoff_day1).
The injected verifier tests system decisions, never trained-model accuracy.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from episode import Episode, load_scenario, llm_extractor
from episode_events import RevisionConflict, digest
from episode_qa import episode_answerer, refresh, sentence_units, who_of
from evidence_gate import FactChecker, bind_check, check_is_fresh, checker_from_env, claim_from_fact, date_check
from kr_runtime import validate_bundle

SCENARIO = load_scenario(Path(__file__).resolve().parents[1] / "care_cases" / "episode_hip_fracture.json")


def update(uid="s1", day="Friday", at="2026-10-21T12:00:00+01:00"):
    text = f"She can go home on {day}, if she can walk safely."
    date = {"Friday": "2026-10-23", "Saturday": "2026-10-24"}[day]
    return {"update_id": uid, "kind": "recording", "at": at, "speaker": "Doctor", "author": "anna", "text": text,
            "recorded_extraction": [{"type": "expected_discharge", "quote": text, "when_text": day,
                                      "when": date, "condition": "if she can walk safely"}]}


class DeterministicVerifier:
    """Injected response fixture. Not a trained model or an accuracy baseline."""
    def __init__(self, status="supported_by_model", error=False, stage="full", useful=True):
        self.card = {"stage": stage, "validation_operating_point_found": useful, "run_id": "injected-deterministic-v1"}
        self.status, self.error, self.calls = status, error, []

    def check(self, source, claim, question=""):
        self.calls.append((source, claim, question))
        if self.error:
            raise RuntimeError("injected inference failure")
        return {"status": self.status, "model_id": self.card["run_id"], "support_score": 0.99,
                "threshold": 0.8, "latency_ms": 0.0}


def correct(ep, uid="s1", day="Saturday", request_id="correct-1", checker=None):
    replacement = update(uid, day)
    return ep.revise_update(uid, {"text": replacement["text"]}, expected_revision=ep.source_revision(uid),
                            request_id=request_id, facts=replacement["recorded_extraction"], evidence_checker=checker)


class RevisionTests(unittest.TestCase):
    def test_family_recording_cannot_replace_clinician_and_stays_family_after_correction_and_replay(self):
        ep = Episode(SCENARIO)
        ep.add_update(update())   # legacy medical recordings retain their source authority
        family = {**update("family", "Saturday"), "speaker_type": "family", "speaker": "Anna"}
        entry = ep.add_update(family)
        self.assertEqual(entry["authority"], "family")
        self.assertTrue(entry["lines"][0]["contradicts"])
        self.assertEqual(ep.slots["expected_discharge"]["fact"]["when"], "2026-10-23")
        self.assertEqual(ep.slots["expected_discharge"]["authority"], "care_team")
        self.assertEqual(ep.plans(), [])   # hospital events are not visiting/helping plans
        correct(ep, "family", "Friday")
        replay = Episode.from_snapshot(ep.to_snapshot())
        source = next(u for u in replay.updates if u["update_id"] == "family")
        self.assertEqual((source["speaker_type"], source["speaker"]), ("family", "Anna"))
        self.assertEqual(replay.slots["expected_discharge"]["update_id"], "s1")
        units = [u for u in sentence_units(replay) if u["update_id"] == "family"]
        self.assertTrue(units)
        self.assertTrue(all(u["authority"] == "family" for u in units))
        self.assertIn("family recording", who_of(units[0]))
        self.assertNotIn("care team", who_of(units[0]))

    def test_reclassifying_legacy_recording_is_explicit_and_requires_new_facts(self):
        ep = Episode(SCENARIO)
        ep.add_update({**update(), "speaker": "me"})
        self.assertEqual(ep.entries[0]["authority"], "care_team")   # never guess from the name
        before = ep.to_snapshot()
        with self.assertRaisesRegex(ValueError, "replacement facts"):
            ep.revise_update("s1", {"speaker_type": "family"}, expected_revision=1, request_id="unrefreshed")
        self.assertEqual(ep.to_snapshot(), before)
        ep.revise_update("s1", {"speaker_type": "family", "speaker": "Anna"}, expected_revision=1,
                         request_id="reclassify", facts=update()["recorded_extraction"])
        replay = Episode.from_snapshot(ep.to_snapshot())
        self.assertEqual(replay.entries[0]["authority"], "family")
        self.assertTrue(replay.status()["expected_discharge"]["unconfirmed"])

    def test_speaker_type_is_validated_before_extraction_and_binds_verification(self):
        ep, calls = Episode(SCENARIO), []
        with self.assertRaisesRegex(ValueError, "speaker_type"):
            ep.add_update({**update(), "speaker_type": "unknown"}, extractor=lambda *a: calls.append(a))
        self.assertEqual(calls, [])
        source = update()
        fact = {**source["recorded_extraction"][0], "fact_id": "s1@1:f1"}
        bound = bind_check(source, fact, {"mode": "shadow", "status": "supported_by_model"})
        self.assertTrue(check_is_fresh(source, fact, bound))
        old_context = {k: source.get(k) for k in ("at", "kind", "speaker", "photo_of", "reading", "hospital_timezone")}
        self.assertEqual(bound["source_context_sha256"], digest(old_context))
        self.assertFalse(check_is_fresh({**source, "speaker_type": "family"}, fact, bound))

    def test_family_recording_extractor_and_diagnosis_name_the_family(self):
        prompts = []
        class Model:
            def chat(self, messages, json_schema=None, schema_name=None):
                prompts.append(messages[-1]["content"])
                return {"json": {"facts": []}, "text": '{"facts": []}'}
        source = {**update(), "speaker": "Anna", "speaker_type": "family"}
        llm_extractor(Model())(source, Episode(SCENARIO))
        self.assertIn("family recording by Anna", prompts[0])
        self.assertNotIn("transcript of what", prompts[0])
        self.assertEqual(Episode.describe({"type": "diagnosis_stated", "what": "Hip fracture"}, src=source),
                         "The family says: hip fracture")

    def test_correction_replaces_projection_without_old_facts_or_extraction_replay(self):
        ep = Episode(SCENARIO)
        calls = []
        def extractor(u, context):
            calls.append(u["update_id"])
            return u["recorded_extraction"]
        ep.add_update(update(), extractor=extractor)
        ep.add_update(update("s2", at="2026-10-21T11:00:00+01:00"), extractor=extractor)
        correct(ep)
        self.assertEqual(calls, ["s1", "s2"])
        self.assertEqual(ep.slots["expected_discharge"]["fact"]["when"], "2026-10-24")
        self.assertEqual(ep.entries[0]["source_revision"], 2)
        self.assertEqual(ep.entries[0]["facts"][0]["fact_id"], "s1@2:f1")
        self.assertEqual(ep.source_history("s1")[0]["update"]["text"], update()["text"])

    def test_correction_preserves_original_source_metadata(self):
        ep = Episode(SCENARIO); ep.add_update(update())
        old = ep.updates[0].copy()
        correct(ep)
        self.assertEqual({k: old[k] for k in ("at", "kind", "author", "speaker", "update_id")},
                         {k: ep.updates[0][k] for k in ("at", "kind", "author", "speaker", "update_id")})

    def test_retry_is_idempotent_and_reused_request_conflicts(self):
        ep = Episode(SCENARIO)
        a = ep.add_update(update(), request_id="add-1")
        self.assertEqual(ep.add_update(update(), request_id="add-1"), a)
        self.assertEqual(len(ep.events), 1)
        b = correct(ep)
        replacement = update(day="Saturday")
        self.assertEqual(ep.revise_update("s1", {"text": replacement["text"]}, expected_revision=1,
                                         request_id="correct-1", facts=replacement["recorded_extraction"]), b)
        with self.assertRaises(RevisionConflict):
            ep.revise_update("s1", {"text": "different"}, expected_revision=1, request_id="correct-1", facts=[])
        with self.assertRaises(RevisionConflict):
            ep.revise_update("s1", {}, expected_revision=1, request_id="stale", facts=[])
        with self.assertRaises(ValueError):
            ep.add_update(update())

    def test_changed_source_cannot_reuse_old_recorded_extraction_implicitly(self):
        ep = Episode(SCENARIO); ep.add_update(update())
        before = ep.to_snapshot()
        with self.assertRaisesRegex(ValueError, "replacement facts"):
            ep.revise_update("s1", {"text": "The old words were wrong."}, expected_revision=1, request_id="bad")
        self.assertEqual(ep.to_snapshot(), before)

    def test_extractor_and_checker_failure_roll_back_everything(self):
        ep = Episode(SCENARIO); ep.add_update(update())
        before = ep.to_snapshot()
        def broken_extractor(u, context):
            context.patient["name"] = "MUTATED"
            raise RuntimeError("extraction failed")
        with self.assertRaises(RuntimeError):
            ep.revise_update("s1", {"text": "Changed source words."}, expected_revision=1, request_id="ex",
                             extractor=broken_extractor)
        def broken_checker(u, f):
            raise RuntimeError("checker contract failure")
        with self.assertRaises(RuntimeError):
            correct(ep, checker=broken_checker)
        self.assertEqual(ep.to_snapshot(), before)

    def test_snapshot_roundtrip_restores_qa_labels_read_and_manual_actions(self):
        ep = Episode(SCENARIO)
        for u in SCENARIO["updates"][:7]:
            ep.add_update(u)
        q, _ = ep.add_question("When is she going home?", "mia", asked_seq=2)
        ep.add_question("When is she going home?", "david")
        ep.set_answered(q["qid"], update_id="u07", by="anna")
        ep.mark_read("mia")
        snapshot = json.loads(json.dumps(ep.to_snapshot()))
        restored = Episode.from_snapshot(snapshot)
        self.assertEqual(restored.to_snapshot(), snapshot)
        self.assertEqual(restored.status(), ep.status())
        self.assertEqual(restored.timeline("mia"), ep.timeline("mia"))
        self.assertEqual(restored.questions, ep.questions)
        self.assertEqual(sentence_units(restored), sentence_units(ep))
        self.assertEqual(restored.seen_at, ep.seen_at)

    def test_snapshot_confirmation_roundtrip_and_revision_reopens(self):
        ep = Episode(SCENARIO)
        for u in SCENARIO["updates"]:
            ep.add_update(u)
            if u["update_id"] == "u07b":
                break
        pair = ep.two_answers()[0]
        ep.confirm_answer(pair["qid"], "u07", "anna")
        restored = Episode.from_snapshot(json.loads(json.dumps(ep.to_snapshot())))
        self.assertEqual(restored.status(), ep.status())
        self.assertEqual(restored.questions, ep.questions)
        source = next(u for u in ep.updates if u["update_id"] == "u07")
        ep.revise_update("u07", {"text": source["text"] + " Words checked."}, expected_revision=1,
                         request_id="correct-confirmed", facts=[])
        q = next(q for q in ep.questions if q["qid"] == pair["qid"])
        self.assertEqual(q["status"], "open")
        self.assertIn("source", q["invalidation_reason"])
        self.assertFalse(any(r.get("confirmed_by") for r in ep.slots.values()))

    def test_answered_question_reopens_after_correction_and_delete(self):
        for op in ("correct", "delete"):
            ep = Episode(SCENARIO); ep.add_update(update())
            q, _ = ep.add_question("When is she going home?", "mia")
            ep.set_answered(q["qid"], update_id="s1", by="anna")
            if op == "correct": correct(ep)
            else: ep.delete_update("s1", expected_revision=1, request_id="delete-1")
            self.assertEqual(q["status"], "open")
            self.assertIsNone(q["answered_by"])
            self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).questions, ep.questions)

    def test_joined_auto_question_keeps_identity_across_source_correction(self):
        ep = Episode(SCENARIO)
        for u in SCENARIO["updates"]:
            ep.add_update(u)
            if u["update_id"] == "u07b": break
        pair = ep.two_answers()[0]
        q = next(q for q in ep.questions if q["qid"] == pair["qid"])
        ep.add_question(q["text"], "mia")
        source = next(u for u in SCENARIO["updates"] if u["update_id"] == "u07")
        ep.revise_update("u07", {"text": source["text"] + " The source was checked."}, expected_revision=1,
                         request_id="joined-auto", facts=source["recorded_extraction"])
        q = next(q for q in ep.questions if q["qid"] == pair["qid"])
        self.assertIn("mia", q["askers"])
        self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).questions, ep.questions)

    def test_join_on_behalf_survives_next_command_and_restart(self):
        ep = Episode(SCENARIO); ep.add_update(update())
        q, _ = ep.add_question("When is she going home?", "mia")
        joined, status = ep.add_question(q["text"], "david")
        self.assertEqual(status, "joined")
        ep.mark_read("anna")
        self.assertEqual(joined["askers"], ["mia", "david"])
        self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).questions[0]["askers"], ["mia", "david"])

    def test_reasked_question_keeps_both_ids_when_old_answer_reopens(self):
        for op in ("correct", "delete"):
            ep = Episode(SCENARIO); ep.add_update(update())
            first, _ = ep.add_question("When is she going home?", "mia")
            ep.set_answered(first["qid"], update_id="s1", by="anna")
            second, _ = ep.add_question("When is she going home?", "david")
            self.assertNotEqual(first["qid"], second["qid"])
            if op == "correct": correct(ep)
            else: ep.delete_update("s1", expected_revision=1, request_id="delete-reasked")
            self.assertEqual([q["qid"] for q in ep.questions], ["q1", "q2"])
            self.assertEqual([q["askers"] for q in ep.questions], [["mia"], ["david"]])
            self.assertTrue(all(q["status"] == "open" for q in ep.questions))

    def test_confirmation_refreshes_qa_without_new_source(self):
        ep = Episode(SCENARIO)
        for u in SCENARIO["updates"]:
            ep.add_update(u)
            if u["update_id"] == "u07b": break
        answer = episode_answerer(None)(ep, "When is she going home?")
        old_seq = ep.seq
        self.assertTrue(any(q["state"] == "two_answers" for q in answer["quotes"]))
        pair = ep.two_answers()[0]
        ep.confirm_answer(pair["qid"], "u07", "anna")
        self.assertEqual(ep.seq, old_seq)
        refreshed = refresh(ep, answer)
        self.assertFalse(any(q["state"] == "two_answers" for q in refreshed["quotes"]))

    def test_deleted_source_is_tombstoned_and_retry_does_not_reapply(self):
        ep = Episode(SCENARIO); ep.add_update(update())
        expected = ep.delete_update("s1", expected_revision=1, request_id="delete-1")
        self.assertEqual(ep.entries, [])
        self.assertEqual(ep.slots, {})
        self.assertEqual(ep.source_revision("s1"), 2)
        self.assertEqual(ep.delete_update("s1", expected_revision=1, request_id="delete-1"), expected)
        self.assertEqual(len(ep.source_history("s1")), 2)
        with self.assertRaises(ValueError): ep.add_update(update())

    def test_deleting_scripted_source_does_not_offer_tombstone_again(self):
        ep = Episode(SCENARIO)
        first = ep.next_scripted()
        ep.add_update(first)
        ep.delete_update(first["update_id"], expected_revision=1, request_id="script-delete")
        self.assertNotEqual(ep.next_scripted()["update_id"], first["update_id"])
        ep.add_update(ep.next_scripted())

    def test_snapshot_tampering_and_revision_chain_fail(self):
        ep = Episode(SCENARIO); ep.add_update(update())
        snapshot = ep.to_snapshot()
        snapshot["events"][0]["update"]["text"] = "Changed behind the checksum"
        with self.assertRaisesRegex(ValueError, "checksum"): Episode.from_snapshot(snapshot)
        snapshot = ep.to_snapshot(); snapshot["events"][0]["revision"] = 3
        snapshot["sha256"] = digest({k: v for k, v in snapshot.items() if k != "sha256"})
        with self.assertRaisesRegex(ValueError, "revision chain"): Episode.from_snapshot(snapshot)

    def test_event_access_returns_copies(self):
        ep = Episode(SCENARIO); ep.add_update(update())
        event = ep.events[0]; event["update"]["text"] = "tamper"
        self.assertEqual(ep.events[0]["update"]["text"], update()["text"])

    def test_old_qa_citation_is_invalidated_not_rebound_to_corrected_sentence(self):
        ep = Episode(SCENARIO); ep.add_update(update())
        answer = episode_answerer(None)(ep, "When is she going home?")
        self.assertEqual(answer["quotes"][0]["sid"], "s1.1")
        correct(ep)
        new = refresh(ep, answer)
        self.assertTrue(new["source_changed"])
        self.assertEqual(new["method"], "refreshed_source_changed")
        self.assertTrue(all(q["source_revision"] == 2 for q in new["quotes"]))
        self.assertTrue(all(q["sid"] != "s1.1" for q in new["quotes"]))
        self.assertIn("Saturday", new["quotes"][0]["text"])

    def test_old_qa_source_removed_has_no_stale_ward_contact(self):
        ep = Episode(SCENARIO); ep.add_update(update())
        answer = episode_answerer(None)(ep, "When is she going home?")
        ep.delete_update("s1", expected_revision=1, request_id="delete")
        new = refresh(ep, answer)
        self.assertEqual(new["quotes"], [])
        self.assertEqual(new["covered"], "no")
        self.assertTrue(new["source_changed"])

    def test_qa_refresh_recomputes_coverage_when_corrected_source_now_answers(self):
        ep = Episode(SCENARIO)
        ep.add_update({**update(), "text": "The weather is sunny."}, facts=[])
        answer = episode_answerer(None)(ep, "When is she going home?")
        self.assertEqual(answer["covered"], "no")
        correct(ep)
        changed = refresh(ep, answer)
        self.assertEqual(changed["covered"], "partly")
        self.assertTrue(changed["quotes"])

    def test_late_arrival_rules_and_conditional_negation_survive_replay(self):
        ep = Episode(SCENARIO)
        ep.add_update(update("new", "Saturday", "2026-10-22T12:00:00+01:00"))
        ep.add_update(update("old", "Friday", "2026-10-21T12:00:00+01:00"))
        text = "She must not walk without a nurse beside her."
        ep.add_update({"update_id": "neg", "at": ep.latest_at(), "kind": "recording", "text": text},
                      facts=[{"type": "instruction", "what": "Walk without a nurse", "quote": text}])
        self.assertEqual(ep.slots["expected_discharge"]["fact"]["when"], "2026-10-24")
        self.assertTrue(ep.entries[1]["lines"][0]["late"])
        self.assertIn("must not", ep.entries[2]["facts"][0]["what"])
        self.assertEqual(ep.status(), Episode.from_snapshot(ep.to_snapshot()).status())


class VerifierTests(unittest.TestCase):
    def test_off_does_not_import_or_load_a_model(self):
        with patch.dict(os.environ, {"KINDRED_VERIFIER_MODE": "off"}):
            self.assertIsNone(checker_from_env())
        with patch.dict(os.environ, {"KINDRED_VERIFIER_MODE": "garbage"}):
            with self.assertRaises(ValueError): checker_from_env()

    def test_shadow_retains_and_gate_withholds_same_non_supported_fact(self):
        for mode, accepted in (("shadow", 1), ("gate", 0)):
            ep = Episode(SCENARIO); model = DeterministicVerifier(status="needs_review")
            result = ep.add_update(update(), evidence_checker=FactChecker(model, mode))
            self.assertEqual(len(result["facts"]), accepted)
            self.assertEqual(len(result["evidence_checks"]), 1)
            self.assertEqual(result["evidence_checks"][0]["withhold"], mode == "gate")
            self.assertEqual(len(model.calls), 1)
            Episode.from_snapshot(ep.to_snapshot())
            ep.mark_read("mia")
            self.assertEqual(len(model.calls), 1)

    def test_gate_inference_failure_is_visible_and_fail_closed(self):
        ep = Episode(SCENARIO)
        result = ep.add_update(update(), evidence_checker=FactChecker(DeterministicVerifier(error=True), "gate"))
        self.assertEqual(result["facts"], [])
        self.assertEqual(result["evidence_checks"][0]["reason"], "inference_error")
        self.assertEqual(result["evidence_checks"][0]["status"], "unverified")
        self.assertTrue(result["evidence_checks"][0]["withhold"])
        self.assertEqual(ep.updates[0]["text"], update()["text"])
        self.assertTrue(episode_answerer(None)(ep, "When is she going home?")["quotes"])

    def test_gate_requires_full_and_strict_useful_bool(self):
        for stage, useful in (("smoke", True), ("full", False), ("full", "true"), ("full", 1)):
            with self.assertRaises(ValueError): FactChecker(DeterministicVerifier(stage=stage, useful=useful), "gate")

    def test_complete_claim_represents_every_displayed_semantic_field(self):
        facts = [dict(type="family", who="David", what="Flying on Wednesday", quote="unused"),
                 dict(type="follow_up", what="Clinic", where="Royal Hospital", when_text="Friday", quote="unused"),
                 dict(type="expected_discharge", when_text="Friday", condition="if she can walk safely", quote="unused"),
                 dict(type="medication", name="Drug A", status="stop", dose="5 mg", frequency="twice daily", quote="unused")]
        for fact in facts:
            claim = claim_from_fact(fact)
            for key, value in fact.items():
                if key not in ("type", "quote"): self.assertIn(value, claim)

    def test_fresh_check_identity_changes_on_revision_and_model_results_not_reused(self):
        ep = Episode(SCENARIO); model = DeterministicVerifier(); checker = FactChecker(model)
        ep.add_update(update(), evidence_checker=checker)
        old = ep.entries[0]["evidence_checks"][0]
        self.assertTrue(check_is_fresh(ep.updates[0], ep.entries[0]["facts"][0], old))
        correct(ep, checker=checker)
        new = ep.entries[0]["evidence_checks"][0]
        self.assertNotEqual(old["verification_id"], new["verification_id"])
        self.assertFalse(check_is_fresh(ep.updates[0], ep.entries[0]["facts"][0], old))
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(new["claim_renderer_version"], "complete-fields-v1")
        self.assertIn("model_artifact_sha256", new)

    def test_inherited_hospital_has_separate_provenance_from_source_local_verification(self):
        ep = Episode(SCENARIO); checker = FactChecker(DeterministicVerifier())
        ep.add_update(SCENARIO["updates"][0], evidence_checker=checker)
        text = "She was moved to Ward 7 upstairs."
        result = ep.add_update({"update_id": "ward", "kind": "recording", "at": ep.latest_at(), "text": text},
                               facts=[{"type": "location", "unit": "Ward 7", "quote": text}], evidence_checker=checker)
        fact, checked = result["facts"][0], result["evidence_checks"][0]
        self.assertEqual(fact["hospital"], "St Mary's Hospital")
        self.assertEqual(fact["_derived_context"]["hospital"]["update_id"], SCENARIO["updates"][0]["update_id"])
        self.assertNotIn("St Mary's Hospital", checked["claim"])
        self.assertTrue(check_is_fresh(ep.updates[-1], fact, checked))
        self.assertEqual(Episode.from_snapshot(ep.to_snapshot()).status(), ep.status())

    def test_correction_without_checker_discards_old_model_result(self):
        ep = Episode(SCENARIO); ep.add_update(update(), evidence_checker=FactChecker(DeterministicVerifier()))
        correct(ep)
        self.assertEqual(ep.entries[0]["evidence_checks"], [])

    def test_date_policy_matches_relative_and_refuses_ambiguous_dates(self):
        u = update(); f = u["recorded_extraction"][0]
        self.assertEqual(date_check(u, f)["status"], "matched")
        self.assertEqual(date_check(u, {**f, "when": "2026-11-06"})["status"], "needs_review")
        self.assertEqual(date_check(u, {**f, "when_text": "2026-99-99"})["status"], "needs_review")
        self.assertEqual(date_check(u, {**f, "when": "2026-10-22", "when_text": "tomorrow"})["status"], "matched")
        self.assertEqual(date_check(u, {**f, "when": "2026-10-23T10:30", "when_text": "Friday at 10:30"})["status"], "matched")
        self.assertEqual(date_check(u, {**f, "when": "2026-10-23T10:30", "when_text": "Friday at 11:30"})["status"], "needs_review")

    def test_calendar_ambiguity_is_withheld_in_gate_even_if_model_supports(self):
        u = update(); u["recorded_extraction"][0]["when"] = "2026-11-06"  # another Friday, not next Friday
        ep = Episode(SCENARIO)
        result = ep.add_update(u, evidence_checker=FactChecker(DeterministicVerifier(), "gate"))
        self.assertEqual(result["facts"], [])
        self.assertEqual(result["evidence_checks"][0]["date_check"]["status"], "needs_review")

    def test_calendar_context_uses_hospital_midnight_like_extractor(self):
        # London is already Thursday while the source timestamp is Wednesday UTC.
        u = {**update(at="2026-10-21T23:30:00+00:00"), "text": "She can go home tomorrow if she can walk safely."}
        u["recorded_extraction"] = [{"type": "expected_discharge", "quote": u["text"], "when_text": "tomorrow",
                                      "when": "2026-10-23", "condition": "if she can walk safely"}]
        ep = Episode(SCENARIO)
        result = ep.add_update(u, evidence_checker=FactChecker(DeterministicVerifier(), "gate"))
        self.assertEqual(len(result["facts"]), 1)
        self.assertEqual(result["evidence_checks"][0]["date_check"]["status"], "matched")

    def test_cut_off_extractor_never_applies_even_valid_partial_json(self):
        class CutOff:
            def chat(self, *args, **kwargs):
                return {"json": {"facts": update()["recorded_extraction"]}, "finish_reason": "length"}
        ep = Episode(SCENARIO)
        result = ep.add_update(update(), extractor=llm_extractor(CutOff()))
        self.assertEqual(result["facts"], [])

    def test_bundle_manifest_rejects_escape_unlisted_corruption_and_allows_reject_all(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {"config.json": b"{}", "tokenizer_config.json": b"{}", "model.safetensors": b"fixture-only"}
            for name, content in files.items(): (root / name).write_bytes(content)
            card = {"stage": "smoke", "run_id": "fixture", "support_threshold": 1.000001, "max_length": 512,
                    "artifact_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
            def save(): (root / "verifier.json").write_text(json.dumps(card))
            save(); self.assertEqual(validate_bundle(root)["support_threshold"], 1.000001)
            (root / "extra.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "every file"): validate_bundle(root)
            (root / "extra.json").unlink()
            card["artifact_sha256"]["../escape.json"] = "0" * 64; save()
            with self.assertRaisesRegex(ValueError, "path"): validate_bundle(root)
            del card["artifact_sha256"]["../escape.json"]; save()
            (root / "config.json").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "checksum"): validate_bundle(root)


class EvaluationContractTests(unittest.TestCase):
    def test_real_qa_runner_uses_stable_milestones_and_failure_exit(self):
        import importlib.util
        path = Path(__file__).resolve().parents[1] / "scripts" / "try_episode_qa.py"
        spec = importlib.util.spec_from_file_location("qa_runner_under_test", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertEqual(list(module.POINTS), ["u03", "u05", "u07", "u10"])
        self.assertEqual(module.result_exit_code(1, {"expectations": 2, "expectations_met": 2}), 0)
        self.assertEqual(module.result_exit_code(1, {"expectations": 2, "expectations_met": 1}), 3)
        self.assertEqual(module.result_exit_code(1, {"expectations": 0, "expectations_met": 0}), 3)
        self.assertEqual(module.result_exit_code(0, {"expectations": 2, "expectations_met": 2}), 2)

    def test_replay_cli_returns_nonzero_and_writes_failure_report(self):
        import importlib.util
        path = Path(__file__).resolve().parents[2] / "scripts" / "eval_handoff_replay.py"
        spec = importlib.util.spec_from_file_location("replay_runner_under_test", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(module, "evaluate", side_effect=AssertionError("injected failed assertion")):
                self.assertEqual(module.main(["--out", directory]), 1)
            result = json.loads((Path(directory) / "replay_report.json").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertIn("injected failed assertion", result["error"])


class EventTimeMigrationTests(unittest.TestCase):
    def test_reprojection_preserves_legacy_source_question_read_state_and_identity(self):
        from episode import upgrade_episode
        ep = Episode(SCENARIO)
        raw = {"update_id": "c01", "kind": "note", "at": "2026-10-19T08:00:00+01:00",
               "author": "anna", "topic": "plan", "text": "I'll be there on 10/20 afternoon",
               "recorded_extraction": [{"type": "family", "what": "Family will be there",
                                        "quote": "I'll be there on 10/20 afternoon"}]}
        ep.add_update(raw)
        question, _ = ep.add_question("When is she going home?", "mia")
        ep.mark_read("mia")
        before, identity, seen = ep.events, id(ep), dict(ep.seen)
        ep._temporal_projection = "source-event-time-v1"
        restored = upgrade_episode(ep)
        self.assertEqual(id(restored), identity)
        self.assertEqual(restored.events, before)
        self.assertEqual(restored.seen, seen)
        self.assertIs(restored.questions[0], question)
        self.assertEqual(len(restored.entries), 1)
        self.assertEqual(restored.entries[0]["update_id"], "c01")
        self.assertEqual(restored.timeline()[0]["event_time"]["when"], "2026-10-20")
        self.assertIs(upgrade_episode(restored), restored)

    def test_corrected_plan_and_deleted_replacement_restore_only_valid_event_dates(self):
        ep = Episode(SCENARIO)
        text = "I'll be there on 10/20 afternoon"
        ep.add_update({"update_id": "p1", "kind": "note", "at": "2026-10-17T09:00:00+01:00", "author": "anna",
                       "topic": "plan", "text": text, "recorded_extraction": []})
        ep.revise_update("p1", {"text": "I'll be there on 10/21 afternoon"}, expected_revision=1,
                         request_id="correct-plan-date", facts=[])
        self.assertEqual(ep.plans()[0]["event_time"]["when"], "2026-10-21")
        self.assertNotIn("2026-10-20", json.dumps(ep.plans()))
        ep.delete_update("p1", expected_revision=2, request_id="delete-corrected-plan")
        self.assertEqual(ep.plans(), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
