#!/usr/bin/env python3
"""Regression tests for the metamorphic relations of scripts/metamorphic_eval.py (stdlib unittest, offline: no network,
model or credentials; fixed seed, well under a minute).

Every relation runs on the real functions with the fixed seed; a violation whose signature is not a documented known gap
(metamorphic_eval.KNOWN_GAPS, each with the file that owns its fix) fails, and the signatures this change closed
(metamorphic_eval.FIXED) must stay closed. Planted bugs prove the relations have teeth: with the extractor's negation
reader switched off MR1 fails, with the reply's diagnosis check switched off MR5 fails everywhere, and with the
timeline's normalisation made case-sensitive MR3 fails. The live layer's scoring runs on the bench's scripted fake.

python scripts/test_metamorphic.py
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metamorphic_eval as M  # noqa: E402

N = 120   # instances per relation in these tests (the release run uses 200)


class RelationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = M.run_offline(N, M.SEED)

    def test_every_relation_runs_n_instances(self):
        self.assertEqual(set(self.res), set(M.RELATIONS))
        for rel, s in self.res.items():
            self.assertEqual(s["instances"], N, rel)
            self.assertEqual(len(s["_instances"]), N, rel)

    def test_no_violation_outside_the_known_gaps(self):
        for rel, s in self.res.items():
            unknown = [ex for ex in s["examples"] if not ex["known_gap"]]
            self.assertEqual(s["unknown_signatures"], [], f"{rel}: " + json.dumps(
                [{"signature": ex["signature"], "count": ex["count"], "inputs": ex["minimal_example"]["inputs"],
                  "expected": ex["minimal_example"]["expected"], "got": ex["minimal_example"]["got"]} for ex in unknown])[:3000])

    def test_fixed_signatures_stay_closed(self):
        seen = {sig: n for s in self.res.values() for sig, n in s["signatures"].items()}
        for sig in M.FIXED:
            self.assertNotIn(sig, seen, f"{sig} is open again: {M.FIXED[sig]}")

    def test_known_gaps_and_fixes_are_documented_and_disjoint(self):
        for sig, (owner, why) in {**M.KNOWN_GAPS, **M.FIXED}.items():
            self.assertTrue(sig.startswith(tuple(M.RELATIONS)) and owner and len(why) >= 10, sig)
        self.assertFalse(set(M.KNOWN_GAPS) & set(M.FIXED))

    def test_the_safety_relations_hold_where_this_change_owns_the_code(self):
        # the extractor never accepts a reversed instruction or an ungrounded dose; the reply never quotes a fragment
        # without its negation; no decision depends on names, ids, order, whitespace, quotes or case
        by = {(rel, t): v for rel, s in self.res.items() for t, v in s["by_target"].items()}
        for key in (("MR1", "extractor"), ("MR2", "extractor"), ("MR2", "reply"), ("MR3", "story"), ("MR3", "extractor"),
                    ("MR3", "grounding"), ("MR3", "answer"), ("MR3", "rows"), ("MR6", "extractor")):
            self.assertEqual(by[key]["violations"], 0, f"{key}: {by[key]}")
        frag = [x for x in self.res["MR1"]["_instances"] if x["target"] == "reply" and x["inputs"]["style"] == "fragment"]
        self.assertTrue(frag)
        self.assertFalse([x for x in frag if x["violation"]])
        self.assertFalse([x for x in self.res["MR4"]["_instances"]
                          if x["target"] == "reply" and x["inputs"]["kind"] == "negation" and x["violation"]])

    def test_the_seed_makes_the_run_reproducible(self):
        a = M.mr1(random.Random(f"{M.SEED}:MR1"), 30)
        b = M.mr1(random.Random(f"{M.SEED}:MR1"), 30)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        c = M.mr1(random.Random(f"{M.SEED + 1}:MR1"), 30)
        self.assertNotEqual(json.dumps(a, sort_keys=True), json.dumps(c, sort_keys=True))

    def test_examples_are_the_shortest_instance_of_their_signature(self):
        for s in self.res.values():
            for ex in s["examples"]:
                same = [x for x in s["_instances"] if x["violation"] and x["signature"] == ex["signature"]]
                self.assertEqual(len(same), ex["count"])
                self.assertEqual(M._size(ex["minimal_example"]), min(M._size(x) for x in same))


class TransformTests(unittest.TestCase):
    def test_transforms_change_the_text_but_not_its_normal_form(self):
        rng = random.Random(1)
        s = 'She said: "Don\'t let her get up alone." Ask the caregiver first.'
        for name, t in M.TEXT_TRANSFORMS.items():
            out = t(rng, s)
            self.assertNotEqual(out, s, name)
            self.assertEqual(M.GR.norm(out).lower(), M.GR.norm(s).lower(), name)

    def test_case_transform_never_makes_a_case_sensitive_word(self):
        rng = random.Random(2)
        for _ in range(200):
            out = M.t_case(rng, "She is with Tia today and may get up with help in May.")
            self.assertNotIn("TIA", out)
            self.assertIn(" may ", out)
            self.assertIn("May.", out)

    def test_names_are_swapped_whole_words_only(self):
        self.assertEqual(M._names("Elena Novak and Mr Okafor; Annabel stays."), "Maria Kowalski and Mr Adeyemi; Annabel stays.")


class PlantedBugTests(unittest.TestCase):
    """Each relation must catch a deliberately broken check (mutation testing of the harness itself)."""

    def test_mr1_catches_a_negation_reader_that_reads_nothing(self):
        import case_agent
        with mock.patch.object(case_agent, "quote_negated", lambda text, start: False), \
                mock.patch.object(case_agent, "quote_negated_after", lambda text, end: False):
            inst = M.mr1(random.Random(f"{M.SEED}:MR1"), 60)
        self.assertTrue([x for x in inst if x["target"] == "extractor" and x["violation"]
                         and x["signature"] not in M.KNOWN_GAPS])

    def test_mr5_catches_a_reply_check_without_the_diagnosis_rule(self):
        import guardrails
        with mock.patch.object(guardrails, "diagnoses", lambda body: []):
            inst = M.mr5(random.Random(f"{M.SEED}:MR5"), 40)
        self.assertEqual(sum(x["violation"] for x in inst), 40)

    def test_mr3_catches_a_case_sensitive_timeline(self):
        import episode
        real = episode.norm
        with mock.patch.object(episode, "norm", lambda s: real(s) if s == (s or "").lower() else
                               __import__("re").sub(r"\s+", " ", (s or "").replace("’", "'")).strip()):
            sc = M._transform_story(random.Random(3), ["case"])
            changed = M._story_decisions(sc) != M._story_decisions(M.STORY)
        self.assertTrue(changed)


class LiveScoringTests(unittest.TestCase):
    def test_polarity_and_touch(self):
        text = "She must not eat anything after midnight. She can walk with the frame."
        bad = {"type": "instruction", "what": "Eat anything after midnight", "quote": "eat anything after midnight"}
        good = {"type": "instruction", "what": "She must not eat anything after midnight", "quote": "She must not eat anything after midnight"}
        other = {"type": "instruction", "what": "Walk with the frame", "quote": "She can walk with the frame"}
        sent = "She must not eat anything after midnight."
        self.assertTrue(M._touches(bad, text, sent, {"eat"}))
        self.assertFalse(M._touches(other, text, sent, {"eat"}))
        self.assertEqual((M._polarity(bad), M._polarity(good)), ("pos", "neg"))
        self.assertEqual(M._polarity({"type": "medication", "name": "Ibuprofen", "status": "stop", "quote": "STOP taking Ibuprofen"}), "neg")
        self.assertEqual(M._polarity({"type": "expected_discharge", "when_text": "Saturday", "quote": "not planned for Saturday"}), "pos")

    def test_every_flip_sentence_is_in_its_story_update(self):
        for uid, (old, new, pol, keys) in M.NEG_FLIPS.items():
            text = next(u["text"] for u in M.STORY["updates"] if u["update_id"] == uid)
            self.assertIn(old, text, uid)
            self.assertNotEqual(M.GR.negation_count(old) > 0, M.GR.negation_count(new) > 0, uid)
            self.assertEqual(pol, "neg" if M.GR.negation_count(old) or "stop" in old.lower() else "pos", uid)

    def test_live_layer_on_the_scripted_fake(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = M.run_live(Path(tmp), api_key_file=None, dry_run=True, model="fake-model", max_calls=150, echo=lambda *a: None)
            recs = (Path(tmp) / "live_records.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(live["cases"]), 4 * len(M.LIVE_UPDATES))
        self.assertEqual(live["http_calls"], 4 * len(M.LIVE_UPDATES))
        self.assertEqual(sum(json.loads(r)["type"] == "case" for r in recs), 4 * len(M.LIVE_UPDATES))
        s = M.score_live(live)
        # the fake replays the story's recorded facts: the original and its repeat agree, and no recorded fact has the
        # wrong polarity on its clause
        self.assertEqual(s["repeat_baseline"]["fact_set_differs"], 0)
        self.assertEqual(s["negation_polarity"]["violations"], 0)
        self.assertGreater(s["negation_polarity"]["facts_checked"], 0)

    def test_live_layer_stops_at_the_call_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = M.run_live(Path(tmp), api_key_file=None, dry_run=True, model="fake-model", max_calls=5, echo=lambda *a: None)
        self.assertEqual(live["http_calls"], 5)
        self.assertEqual(live["stopped"], "max_calls")


if __name__ == "__main__":
    unittest.main()
