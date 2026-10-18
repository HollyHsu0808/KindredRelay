"""Offline tests of scripts/analyze_bench_agreement.py on a tiny synthetic bench run (no model, no network).

.venv/Scripts/python.exe scripts/test_analyze_bench_agreement.py
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_bench_agreement as A  # noqa: E402
import bench_tf_handover as B  # noqa: E402

MODELS, REPEATS = ["A", "B"], 3
UPDATES = ["u1", "u2", "u3", "u4", "u5", "u6"]
REFERENCE = {"u1": [("event", "Mum fell in the kitchen"), ("location", "St Mary's Hospital")],
             "u2": [("medication", "Paracetamol 1 g four times a day")],
             "u3": [("event", "Physio got her standing")],
             **{f"u{i}": [("event", f"Note number {i} was read")] for i in (4, 5, 6)}}


def case(model, u, r, facts, status="ok"):
    return {"type": "case", "model": model, "case_id": f"s/{u}", "update_id": u, "repeat": r, "status": status,
            "accepted_facts": [{"fact_id": f"{u}@{r}:f{i}", "type": t, "quote": q} for i, (t, q) in enumerate(facts, 1)]}


def synthetic_cases() -> list[dict]:
    """Hand-checked layout. u1: A gives {E, L}, {E', L}, {E, F} (E' = E with a full stop), B gives {E, L} three times.
    u2: A and B quote different medicines. u3: B's third repeat failed. u4-u6: both models quote the reference."""
    E, E2 = ("event", "Mum fell in the kitchen"), ("event", "Mum fell in the kitchen.")
    L, F = ("location", "St Mary's Hospital"), ("family", "I'm going with her")
    out = [case("A", "u1", 0, [E, L]), case("A", "u1", 1, [E2, L]), case("A", "u1", 2, [E, F])]
    out += [case("B", "u1", r, [E, L]) for r in range(3)]
    out += [case("A", "u2", r, [("medication", "Paracetamol 1 g four times a day")]) for r in range(3)]
    out += [case("B", "u2", r, [("medication", "Lansoprazole 15 mg once a day")]) for r in range(3)]
    out += [case("A", "u3", r, [("event", "Physio got her standing")]) for r in range(3)]
    out += [case("B", "u3", r, [("event", "Physio got her standing")]) for r in range(2)]
    out += [case("B", "u3", 2, [], status="failed")]
    for i in (4, 5, 6):
        out += [case(m, f"u{i}", r, [("event", f"Note number {i} was read")]) for m in MODELS for r in range(3)]
    return out


def synthetic_cases_v2() -> list[dict]:
    """synthetic_cases as a bench schema v2 run writes them (rejected_facts on every case), with four rejected proposals:
    u1: A's third repeat also proposes D (a quote no one else gives); u2: every B repeat also proposes a shorter quote
    inside its accepted Lansoprazole fact (same key: accepted and rejected); u4: the first repeat of both models proposes
    a family fact with no text quote."""
    out = []
    for c in synthetic_cases():
        rf = []
        if (c["model"], c["update_id"], c["repeat"]) == ("A", "u1", 2):
            rf = [{"type": "event", "quote": "she was dizzy yesterday", "reason": "quote not in the update"}]
        elif (c["model"], c["update_id"]) == ("B", "u2"):
            rf = [{"type": "medication", "quote": "Lansoprazole 15 mg", "reason": "missing status"}]
        elif c["update_id"] == "u4" and c["repeat"] == 0:
            rf = [{"type": "family", "quote": None, "reason": "quote is not text"}]
        out.append({**c, "rejected_facts": rf})
    return out


def references() -> dict:
    return {u: [{"type": t, "quote": q} for t, q in facts] for u, facts in REFERENCE.items()}


def run_analysis():
    return A.analyze(synthetic_cases(), references(), MODELS, UPDATES, REPEATS)


class FactKeys(unittest.TestCase):
    def test_trailing_punctuation_and_curly_apostrophe_share_a_key(self):
        keymap, rows = A.fact_keys([{"type": "family", "quote": "I'm going with her"},
                                    {"type": "family", "quote": "I’m going with her."}])
        self.assertEqual(set(keymap.values()), {("family", "i'm going with her")})
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["bridged"])

    def test_different_types_never_share_a_key(self):
        keymap, _ = A.fact_keys([{"type": "event", "quote": "St Mary's Hospital A&E"},
                                 {"type": "location", "quote": "St Mary's Hospital A&E"}])
        self.assertEqual(len(set(keymap.values())), 2)

    def test_whole_sentence_bridges_two_halves_into_one_key(self):
        halves = [{"type": "event", "quote": "Mum fell in the kitchen this morning"},
                  {"type": "event", "quote": "can't stand up"}]
        keymap, _ = A.fact_keys(halves)
        self.assertEqual(len(set(keymap.values())), 2)   # the halves alone are two facts
        keymap, rows = A.fact_keys(halves + [{"type": "event", "quote": "Mum fell in the kitchen this morning and can't stand up."}])
        self.assertEqual(set(keymap.values()), {("event", "can't stand up")})   # named by the shortest quote
        self.assertEqual([r["bridged"] for r in rows], [True])

    def test_keys_do_not_depend_on_fact_order(self):
        facts = [{"type": "event", "quote": q} for q in ("a b c d", "b c", "x y z", "a b c d e f", "y z")]
        first = A.fact_keys(facts)
        for perm in itertools.permutations(facts):
            self.assertEqual(A.fact_keys(list(perm)), first)

    def test_linked_is_the_bench_heuristic(self):
        a, b = ("event", "she is dizzy"), ("event", "she is dizzy when she stands up")
        self.assertEqual(A.linked(a, b), B.reference_match([{"type": a[0], "quote": a[1]}],
                                                           [{"type": b[0], "quote": b[1]}]) > 0)
        self.assertTrue(A.linked(a, b) and A.linked(b, a))
        self.assertFalse(A.linked(("event", ""), ("event", "")))   # an empty quote links to nothing


class SetStatistics(unittest.TestCase):
    def test_jaccard(self):
        self.assertAlmostEqual(A.jaccard({1, 2}, {2, 3}), 1 / 3)
        self.assertEqual(A.jaccard(set(), set()), 1.0)
        self.assertEqual(A.jaccard({1}, set()), 0.0)

    def test_mean_pairwise_jaccard_and_majority(self):
        sets = [{1, 2}, {1, 2}, {1, 3}]
        self.assertAlmostEqual(A.mean_pairwise_jaccard(sets), (1 + 1 / 3 + 1 / 3) / 3)
        self.assertIsNone(A.mean_pairwise_jaccard([{1}]))
        self.assertEqual(A.repeat_counts(sets), {1: 3, 2: 2, 3: 1})
        self.assertEqual(A.majority(sets), {1, 2})
        self.assertEqual(A.majority([{1, 2}, {1}, {3}]), {1})

    def test_wilson_known_values(self):
        self.assertEqual(B.wilson95(5, 10), [0.2366, 0.7634])
        self.assertEqual(B.wilson95(0, 10), [0.0, 0.2775])
        self.assertIsNone(B.wilson95(0, 0))
        self.assertEqual(A.rate_row([]), {"n": 0, "reference_matched": 0, "rate": None, "wilson95": None})

    def test_bootstrap_is_deterministic(self):
        vals = [0.5, 1.0, 1.0, 0.25, 0.75, 1.0]
        ci = B.bootstrap_ci(vals, B.mean, key="within_jaccard:A")
        self.assertEqual(ci, B.bootstrap_ci(vals, B.mean, key="within_jaccard:A"))
        self.assertTrue(min(vals) <= ci[0] <= ci[1] <= max(vals))
        self.assertIsNone(B.bootstrap_ci(vals[:4], B.mean, key="within_jaccard:A"))   # below n = 5: no interval


class Analysis(unittest.TestCase):
    def setUp(self):
        self.n = run_analysis()

    def test_within_model_jaccard_and_repeat_counts(self):
        a, b = self.n["within_model"]["A"], self.n["within_model"]["B"]
        self.assertEqual(a["per_update"]["u1"]["mean_pairwise_jaccard"], round(5 / 9, 4))   # (1 + 1/3 + 1/3) / 3
        self.assertEqual(a["mean_pairwise_jaccard"], round((5 / 9 + 5) / 6, 4))
        self.assertEqual(a["keys_by_repeat_count"], {"3": 6, "2": 1, "1": 1})
        self.assertEqual(a["share_by_repeat_count"]["3"], 0.75)
        self.assertEqual((b["n_updates"], b["mean_pairwise_jaccard"], b["ci95"]), (5, 1.0, [1.0, 1.0]))   # u3 left out
        self.assertEqual(len(a["ci95"]), 2)

    def test_incomplete_pair_is_left_out_and_listed(self):
        d = self.n["diagnostics"]
        self.assertEqual(d["incomplete_model_update_pairs"], [{"model": "B", "update_id": "u3", "completed_repeats": 2}])
        self.assertEqual(d["completed_cases_used"], 35)
        self.assertNotIn("u3", self.n["within_model"]["B"]["per_update"])
        self.assertEqual((d["keys_merging_several_quotes"], d["bridged_keys"]), (1, 0))   # "...kitchen" and "...kitchen."

    def test_cross_model_majority_jaccard(self):
        c = self.n["cross_model"]["A vs B"]
        self.assertEqual({u: r["jaccard"] for u, r in c["per_update"].items()},
                         {"u1": 1.0, "u2": 0.0, "u4": 1.0, "u5": 1.0, "u6": 1.0})
        self.assertEqual((c["n_updates"], c["mean_jaccard"]), (5, 0.8))

    def test_bucket_rates(self):
        p = self.n["confidence_signal"]["reference_agreement"]["pooled"]
        got = {k: (v["reference_matched"], v["n"]) for k, v in p["by_repeat_count"].items()}
        self.assertEqual(got, {"3": (11, 12), "2": (1, 1), "1": (0, 1), "1-2": (1, 2)})
        got = {k: (v["reference_matched"], v["n"]) for k, v in p["by_other_model"].items()}
        self.assertEqual(got, {"present": (10, 10), "absent": (1, 3)})   # A's u3 key has no complete other model
        t = p["by_repeat_count_and_other_model"]
        self.assertEqual({k: (v["reference_matched"], v["n"]) for k, v in t.items() if v["n"]},
                         {"3|present": (9, 9), "3|absent": (1, 2), "2|present": (1, 1), "1|absent": (0, 1)})
        self.assertEqual(p["by_repeat_count"]["3"]["wilson95"], B.wilson95(11, 12))
        a = self.n["confidence_signal"]["reference_agreement"]["per_model"]["A"]["by_repeat_count"]["3"]
        self.assertEqual((a["reference_matched"], a["n"]), (6, 6))

    def test_grounding_acceptance_is_marked_not_computable(self):
        g = self.n["confidence_signal"]["grounding_acceptance"]
        self.assertEqual(g["computable"], False)
        self.assertIn("rejection_reasons", g["reason"])

    def test_analysis_is_deterministic(self):
        self.assertEqual(run_analysis(), self.n)


class GroundingAcceptance(unittest.TestCase):
    """3(a) on synthetic_cases_v2, counted by hand: 17 (model, update, proposal key) units over the used pairs."""

    def setUp(self):
        self.n = A.analyze(synthetic_cases_v2(), references(), MODELS, UPDATES, REPEATS)
        self.g = self.n["confidence_signal"]["grounding_acceptance"]

    def test_sections_1_2_and_3b_do_not_change(self):
        v1 = run_analysis()
        for k in ("within_model", "cross_model", "units", "diagnostics"):
            self.assertEqual(self.n[k], v1[k], k)
        self.assertEqual(self.n["confidence_signal"]["reference_agreement"], v1["confidence_signal"]["reference_agreement"])

    def test_key_buckets(self):
        self.assertTrue(self.g["computable"])
        p = self.g["keys"]["pooled"]
        got = {k: (v["accepted"], v["n"]) for k, v in p["by_repeat_count"].items()}
        self.assertEqual(got, {"3": (11, 12), "2": (1, 1), "1": (1, 4), "1-2": (2, 5)})
        got = {k: (v["accepted"], v["n"]) for k, v in p["by_other_model"].items()}
        self.assertEqual(got, {"present": (10, 12), "absent": (2, 4)})   # A's u3 key has no complete other model
        t = p["by_repeat_count_and_other_model"]
        self.assertEqual({k: (v["accepted"], v["n"]) for k, v in t.items() if v["n"]},
                         {"3|present": (9, 9), "3|absent": (1, 2), "2|present": (1, 1), "1|present": (0, 2),
                          "1|absent": (1, 2)})
        self.assertEqual(p["by_repeat_count"]["1"]["wilson95"], B.wilson95(1, 4))
        b = self.g["keys"]["per_model"]["B"]["by_repeat_count"]["3"]
        self.assertEqual((b["accepted"], b["n"]), (5, 6))   # the Lansoprazole key: 3 accepted, 3 rejected proposals

    def test_proposal_buckets_and_diagnostics(self):
        p = self.g["proposals"]["pooled"]["by_repeat_count"]
        self.assertEqual({k: (v["accepted"], v["n"]) for k, v in p.items()},
                         {"3": (36, 39), "2": (2, 2), "1": (1, 4), "1-2": (3, 6)})
        d = self.g["diagnostics"]
        self.assertEqual((d["proposals"], d["accepted"], d["rejected"], d["keys"]), (45, 39, 6, 17))
        self.assertEqual((d["keys_with_accepted_and_rejected_proposals"], d["rejected_without_text_quote"]), (1, 2))
        self.assertEqual(d["rejection_reasons"], {"missing status": 3, "quote is not text": 2, "quote not in the update": 1})
        self.assertEqual(d["withheld_by_gate_not_included"], 0)
        lanso = next(u for u in self.g["units"] if u["model"] == "B" and u["update_id"] == "u2")
        self.assertEqual((lanso["quote"], lanso["repeat_count"], lanso["proposals"], lanso["proposals_accepted"],
                          lanso["grounding_accepted"]), ("lansoprazole 15 mg", 3, 6, 3, False))

    def test_partial_records_are_not_computable(self):
        cases = synthetic_cases_v2()
        del cases[0]["rejected_facts"]
        g = A.analyze(cases, references(), MODELS, UPDATES, REPEATS)["confidence_signal"]["grounding_acceptance"]
        self.assertEqual(g["computable"], False)
        self.assertIn("1 of the 35 completed case records lack rejected_facts", g["reason"])

    def test_no_rejection_says_so(self):
        cases = [{**c, "rejected_facts": []} for c in synthetic_cases()]
        n = A.analyze(cases, references(), MODELS, UPDATES, REPEATS)
        self.assertEqual(n["confidence_signal"]["grounding_acceptance"]["diagnostics"]["rejected"], 0)
        self.assertIn("rejected none of the", A.takeaway(n, MODELS, REPEATS))


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bench_agreement_test_"))
        self.story = self.tmp / "story.json"
        self.story.write_text(json.dumps({"updates": [{"update_id": u, "recorded_extraction": refs}
                                                      for u, refs in references().items()]}), encoding="utf-8")
        self.bench = self.tmp / "bench"
        self.bench.mkdir()
        cfg = {"story": str(self.story), "story_sha256": hashlib.sha256(self.story.read_bytes()).hexdigest(),
               "models": MODELS, "case_ids": [f"s/{u}" for u in UPDATES], "repeats": REPEATS, "dry_run": True}
        recs = [{"type": "run_start", "schema_version": B.SCHEMA_VERSION, "config": cfg, "invocation": 1},
                {"type": "invocation", "invocation": 1, "source_sha256": {}}] + synthetic_cases()
        (self.bench / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
        (self.bench / "results.json").write_text("{}\n", encoding="utf-8")

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = A.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_writes_results_and_summary(self):
        out = self.tmp / "agreement"
        code, _, err = self.run_main(self.bench, "--out", out)
        self.assertEqual(code, A.EXIT_OK, err)
        res = json.loads((out / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(res["schema_version"], A.SCHEMA_VERSION)
        for name, sub in (("records.jsonl", "records_jsonl"), ("results.json", "results_json")):
            self.assertEqual(res["inputs"][sub]["sha256"], hashlib.sha256((self.bench / name).read_bytes()).hexdigest())
        self.assertEqual(res["inputs"]["story"]["sha256"], hashlib.sha256(self.story.read_bytes()).hexdigest())
        self.assertIsNone(res["inputs"]["heuristic_source"]["matches_run"])   # the synthetic run recorded no sources
        self.assertEqual(set(res), {"schema_version", "created_utc", "inputs", "run", "definitions", "numbers", "caveats"})
        md = (out / "summary.md").read_text(encoding="utf-8")
        for text in ("## 1. Within-model repeat agreement", "## Takeaway", "## Caveats", "not clinical ground truth",
                     "not computable from these records"):
            self.assertIn(text, md)
        takeaway = md.split("## Takeaway\n\n", 1)[1].split("\n", 1)[0]
        self.assertEqual(takeaway.count(". "), 2)   # three sentences
        self.assertEqual(sum(1 for line in md.splitlines() if line.startswith("| `A`")), 1)

    def test_v2_run_reports_grounding_acceptance(self):
        lines = (self.bench / "records.jsonl").read_text(encoding="utf-8").splitlines()[:2]
        (self.bench / "records.jsonl").write_text("\n".join(lines + [json.dumps(c) for c in synthetic_cases_v2()]) + "\n",
                                                  encoding="utf-8")
        out = self.tmp / "agreement_v2"
        code, so, err = self.run_main(self.bench, "--out", out)
        self.assertEqual(code, A.EXIT_OK, err)
        self.assertIn("grounding check (3a): 6 of 45 proposals rejected", so)
        md = (out / "summary.md").read_text(encoding="utf-8")
        self.assertNotIn("not computable", md)
        self.assertIn("| Bucket | pooled keys | `A` keys | `B` keys | pooled proposals |", md)
        self.assertIn("| in 1/3 repeats | 1/4 (25.0%) " + A.ci_s(B.wilson95(1, 4)), md)
        self.assertIn("Rejection reasons: 3 x missing status; 2 x quote is not text; 1 x quote not in the update.", md)
        takeaway = md.split("## Takeaway\n\n", 1)[1].split("\n", 1)[0]
        self.assertEqual(takeaway.count(". "), 3)   # four sentences: the fourth is 3(a)
        self.assertIn("The grounding check rejected 6 of the 45 proposals", takeaway)
        res = json.loads((out / "results.json").read_text(encoding="utf-8"))
        self.assertTrue(res["numbers"]["confidence_signal"]["grounding_acceptance"]["computable"])
        self.assertIn("proposal_key", res["definitions"])

    def test_two_runs_give_the_same_numbers(self):
        r = []
        for name in ("one", "two"):
            code, _, err = self.run_main(self.bench, "--out", self.tmp / name)
            self.assertEqual(code, A.EXIT_OK, err)
            res = json.loads((self.tmp / name / "results.json").read_text(encoding="utf-8"))
            res.pop("created_utc")
            r.append(res)
        self.assertEqual(r[0], r[1])

    def test_refuses_an_existing_output_folder(self):
        out = self.tmp / "exists"
        out.mkdir()
        code, _, err = self.run_main(self.bench, "--out", out)
        self.assertEqual(code, A.EXIT_USAGE)
        self.assertIn("exists", err)

    def test_refuses_a_story_that_is_not_the_runs(self):
        self.story.write_text(self.story.read_text(encoding="utf-8") + " ", encoding="utf-8")
        out = self.tmp / "changed"
        code, _, err = self.run_main(self.bench, "--out", out)
        self.assertEqual(code, A.EXIT_USAGE)
        self.assertIn("not the story the run used", err)
        self.assertFalse(out.exists())

    def test_refuses_a_folder_without_records(self):
        code, _, err = self.run_main(self.tmp / "nothing", "--out", self.tmp / "o")
        self.assertEqual(code, A.EXIT_USAGE)
        self.assertIn("not found", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
