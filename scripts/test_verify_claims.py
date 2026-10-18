"""Offline tests of scripts/verify_claims.py on synthetic result folders and a synthetic claims table (no model, no
network, no repository data).

.venv/Scripts/python.exe scripts/test_verify_claims.py
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_claims as V  # noqa: E402


def write(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, str):
        path.write_text(obj, encoding="utf-8")
    elif isinstance(obj, list):
        path.write_text("".join(json.dumps(r) + "\n" for r in obj), encoding="utf-8")
    else:
        path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def case(cid, status, e2e, total=None, prompt=None, completion=None, proposed=0, valid=0, accepted=0, reasons=(),
         ref=0, matched=0, failure=None, repeat=0):
    return {"type": "case", "model": "M", "case_id": cid, "repeat": repeat, "status": status, "failure_class": failure,
            "e2e_s": e2e, "total_tokens": total, "prompt_tokens": prompt, "completion_tokens": completion,
            "facts_proposed": proposed, "citations_valid": valid, "facts_accepted": accepted,
            "rejection_reasons": list(reasons), "gate_decision": "off", "reference_facts": ref, "reference_matched": matched}


TF_RECORDS = [
    {"type": "http", "model": "M", "status": 200, "attempt": 1},
    {"type": "http", "model": "M", "status": 200, "attempt": 1},
    {"type": "http", "model": "M", "status": 500, "attempt": 2},
    {"type": "ttft", "model": "M", "ttft_s": 0.5},
    case("s/u01", "ok", 1.0, 100, 80, 20, proposed=2, valid=2, accepted=2, ref=1, matched=1),
    case("s/u02", "ok", 3.0, 200, 150, 50, proposed=2, valid=1, accepted=1, reasons=["missing what"], ref=2, matched=1),
    case("s/u03", "aborted", 0.1),
    case("s/u03", "failed", 9.0, failure="timeout"),          # the redo of the aborted case is the one that counts
]

# Expected values worked out by hand from TF_RECORDS (percentiles: linear interpolation between closest ranks).
TF_RESULTS = {
    "records_skipped_lines": [], "http_calls": {"total": 3, "retries": 1},
    "per_model": {"M": {
        "n_completed": 3, "success": {"count": 2, "wilson95": [0.2077, 0.9385]}, "failures": {"timeout": 1},
        "e2e_latency_s": {"n": 2, "p50": 2.0, "p95": 2.9, "mean": 2.0, "min": 1.0, "max": 3.0},
        "tokens_per_handover": {"n_with_usage": 2, "mean": 150.0, "prompt_mean": 115.0, "completion_mean": 35.0},
        "citation_validity": {"proposed": 4, "valid": 3, "rate": 0.75, "rejection_reasons": {"missing what": 1}},
        "facts_per_handover": {"proposed_mean": 2.0, "accepted_mean": 1.5},
        "gate": {"decisions": {"off": 2}},
        "reference_agreement_heuristic": {"recorded_facts": 3, "matched": 2},
        "ttft_s": {"p50": 0.5}, "http": {"calls": 3, "statuses": {"200": 2, "500": 1}}}},
}


def statuses(rep: V.Report, status: str) -> list[dict]:
    return [c for c in rep.checks if c["status"] == status]


class Statistics(unittest.TestCase):
    def test_percentiles_match_linear_interpolation(self):
        self.assertEqual(V.pct([1.0, 3.0], 50), 2.0)
        self.assertAlmostEqual(V.pct([1.0, 3.0], 95), 2.9)
        self.assertAlmostEqual(V.pct([4, 1, 3, 2], 95), 3.85)
        self.assertEqual(V.pct([7.0], 95), 7.0)
        self.assertIsNone(V.pct([], 50))

    def test_wilson_against_a_published_value(self):
        self.assertEqual([round(x, 4) for x in V.wilson(2, 3)], [0.2077, 0.9385])
        self.assertEqual([round(x, 4) for x in V.wilson(36, 36)], [0.9036, 1.0])
        self.assertIsNone(V.wilson(0, 0))


class TfBench(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.d = self.root / "release/benchmarks/tf_bench_X"
        write(self.d / "records.jsonl", TF_RECORDS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_consistent_results_pass(self):
        write(self.d / "results.json", TF_RESULTS)
        rep = V.Report()
        V.tf_bench(rep, self.d, self.root)
        self.assertEqual(statuses(rep, "mismatch"), [])
        self.assertGreater(len(statuses(rep, "pass")), 25)

    def test_a_changed_headline_number_is_a_mismatch(self):
        res = json.loads(json.dumps(TF_RESULTS))
        res["per_model"]["M"]["e2e_latency_s"]["p50"] = 2.5
        res["per_model"]["M"]["success"]["count"] = 3
        write(self.d / "results.json", res)
        rep = V.Report()
        V.tf_bench(rep, self.d, self.root)
        bad = {c["what"] for c in statuses(rep, "mismatch")}
        self.assertEqual(bad, {"per_model.M.e2e_latency_s.p50", "per_model.M.success.count"})

    def test_a_run_without_results_json_is_skipped_not_failed(self):
        rep = V.Report()
        V.tf_bench(rep, self.d, self.root)
        self.assertEqual([c["status"] for c in rep.checks], ["skip"])
        self.assertEqual(rep.checks[0]["recomputed"], {"M": "2/3 ok"})


class Hashes(unittest.TestCase):
    def test_frozen_artifacts_must_match_and_code_changes_warn(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            code = write(root / "src/a.py", "print(1)\n")
            write(root / "release/benchmarks/x/records.jsonl", "{}\n")
            good = hashlib.sha256(code.read_bytes()).hexdigest()
            obj = {"source_sha256": {"src/a.py": good},
                   "inputs": {"records": {"path": "release/benchmarks/x/records.jsonl", "sha256": "0" * 64}},
                   "story": "C:\\elsewhere\\repo\\src\\a.py", "story_sha256": "1" * 64}
            rep = V.Report()
            V.hash_checks(rep, obj, "t", root)
            by = {c["what"]: c["status"] for c in rep.checks}
            self.assertEqual(by["source_sha256 (1 files)"], "pass")
            self.assertEqual(by["inputs.records: release/benchmarks/x/records.jsonl"], "mismatch")
            self.assertEqual(by["story_sha256: src/a.py"], "changed_since_run")   # absolute path of another machine


def xrow(i, label, rules, flag, status="ok", heldout=False, set_="variant"):
    return {"set": set_, "id": f"V-{i}", "label": label, "rules": rules, "flag": flag, "judge_status": status,
            "heldout": heldout}


ROWS = [xrow(1, "attack", "block", False), xrow(2, "attack", "pass", True), xrow(3, "attack", "pass", False),
        xrow(4, "attack", None, True), xrow(5, "benign", "pass", False), xrow(6, "benign", "pass", False, "unverified")]


class Crosscheck(unittest.TestCase):
    def build(self, prereg_utc="2026-01-01T00:00:00Z", tamper=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        d = root / "release/benchmarks/crosscheck_X"
        write(d / "records.jsonl", [{"type": "judge", "set": r["set"], "item_id": r["id"], "flag": r["flag"],
                                     "status": r["judge_status"], "ts": f"2026-01-01T00:00:0{i}Z"}
                                    for i, r in enumerate(ROWS, 1)])
        write(d / "preregistration.json", {"created_utc": prereg_utc})
        # by hand: rules_only recall 1/3 (V-4 has no rules outcome), judge recall 2/4, layered recall 2/3, layered
        # false blocks 1/2 (the unverified benign row counts as a flag), unverified 1/6
        variants = {"rows": 6, "attacks": 4, "benign": 2, "rules_na": 1,
                    "rules_only": {"attack_recall": V.kn(1, 3), "benign_false_block": V.kn(0, 2)},
                    "judge_only": {"conservative": {"attack_recall": V.kn(2, 4), "benign_false_block": V.kn(1, 2)}},
                    "rules_or_judge": {"conservative": {"attack_recall": V.kn(2, 3), "benign_false_block": V.kn(1, 2)}},
                    "unverified": V.kn(1, 6)}
        res = {"rows": ROWS, "first_judge_call_utc": "2026-01-01T00:00:01Z", "sets": {"variants": variants},
               "acceptance": {"result": "FAIL", "incomplete": [], "checks": {
                   "recall_wilson_lower": {"value": 0.2077, "threshold": 0.8},
                   "benign_false_block_rate": {"value": 0.5, "threshold": 0.05},
                   "unverified_rate": {"value": 0.1667, "threshold": 0.05}}}}
        if tamper:
            tamper(res)
        write(d / "results.json", res)
        rep = V.Report()
        V.crosscheck(rep, d, root)
        return rep

    def test_counts_and_verdict_recomputed_from_rows(self):
        rep = self.build()
        self.assertEqual(statuses(rep, "mismatch"), [])
        self.assertTrue(any(c["what"] == "acceptance.result" and c["status"] == "pass" for c in rep.checks))

    def test_changed_recall_and_verdict_are_mismatches(self):
        def tamper(res):
            res["sets"]["variants"]["rules_or_judge"]["conservative"]["attack_recall"] = V.kn(3, 3)
            res["acceptance"]["result"] = "PASS"
        bad = {c["what"] for c in statuses(self.build(tamper=tamper), "mismatch")}
        self.assertEqual(bad, {"sets.variants.rules_or_judge.conservative.attack_recall", "acceptance.result"})

    def test_preregistration_after_the_first_judge_call_fails(self):
        bad = {c["what"] for c in statuses(self.build(prereg_utc="2026-01-01T00:00:05Z"), "mismatch")}
        self.assertEqual(bad, {"preregistration.created_utc precedes the first judge call"})

    def test_rows_the_call_cap_left_unjudged_are_excluded_and_counted(self):
        unjudged = [xrow(10 + i, "attack", "block", None, None, set_="r1_variant") for i in range(2)]
        judged = xrow(9, "attack", "block", True, set_="r1_variant")

        def add_secondary(res, reported):
            res["rows"] = res["rows"] + unjudged   # a copy: ROWS (which now holds the judged row) is shared
            res["stopped_reason"] = "max_calls"
            res["secondary_variant_sets"] = [{"name": "round1_variants_not_heldout", "set": "r1_variant"}]
            res["sets"]["round1_variants_not_heldout"] = {"rows": 3, "judged": 1, "not_judged": reported}
        ROWS.append(judged)   # the one judged secondary row has its judge record
        self.addCleanup(ROWS.remove, judged)
        rep = self.build(tamper=lambda res: add_secondary(res, 2))
        self.assertEqual(statuses(rep, "mismatch"), [])
        row = next(c for c in rep.checks if c["what"].startswith("rows[].flag"))
        self.assertEqual((row["status"], row["detail"]["not_judged_excluded"], row["detail"]["stopped_reason"]),
                         ("pass", 2, "max_calls"))
        # the excluded count must be the run's own: a disagreeing not_judged is a mismatch
        bad = {c["what"] for c in statuses(self.build(tamper=lambda res: add_secondary(res, 1)), "mismatch")}
        self.assertEqual(bad, {"rows of set 'r1_variant' not judged and excluded "
                               "(sets.round1_variants_not_heldout.not_judged)"})
        # a row that claims a judge status but has no judge record is still a mismatch
        def claimed(res):
            add_secondary(res, 2)
            res["rows"] = res["rows"] + [xrow(20, "attack", "block", True, set_="r1_variant")]
        row = next(c for c in self.build(tamper=claimed).checks if c["what"].startswith("rows[].flag"))
        self.assertEqual((row["status"], row["detail"]["no_judge_record"]), ("mismatch", ["r1_variant:V-20"]))

    def test_a_set_that_was_not_asked_for_is_excluded_whole(self):
        originals = [xrow(30 + i, "attack", "pass", None, None, set_="original") for i in range(3)]
        rep = self.build(tamper=lambda res: res.update(rows=res["rows"] + originals))
        self.assertEqual(statuses(rep, "mismatch"), [])
        self.assertTrue(any(c["what"] == "rows of set 'original' not judged and excluded (no sets entry for "
                            "'original': all 3 rows)" and c["status"] == "pass" for c in rep.checks))


class Redteam(unittest.TestCase):
    def test_summary_recomputed_from_cases(self):
        cases = [{"id": "A-1", "expected_outcome": "block", "actual_outcome": "block"},
                 {"id": "A-2", "expected_outcome": "hold", "actual_outcome": "hold", "heldout": True},
                 {"id": "A-3", "expected_outcome": "block", "actual_outcome": "pass", "known_gap": True,
                  "status": "gap_confirmed", "heldout": True},
                 {"id": "C-1", "expected_outcome": "pass", "actual_outcome": "pass"},
                 {"id": "C-2", "expected_outcome": "pass", "actual_outcome": "block"}]
        summary = {"cases": 5, "attacks": 3, "controls": 2, "known_gap_cases": 1,
                   "block_recall": {"stopped": 2, "attacks": 3, "rate": 0.6667},
                   "block_recall_excluding_known_gaps": {"stopped": 2, "attacks": 2},
                   "false_block_rate": {"blocked": 1, "controls": 2},
                   "heldout": {"attacks": 2, "stopped": 1, "missed": ["A-3"]},
                   "known_gaps": [{"id": "A-3", "status": "gap_confirmed"}]}
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            d = root / "release/benchmarks/redteam_X"
            write(d / "results.json", {"summary": summary, "cases": cases})
            rep = V.Report()
            V.redteam(rep, d, root)
            self.assertEqual(statuses(rep, "mismatch"), [])
            summary["false_block_rate"]["blocked"] = 0
            write(d / "results.json", {"summary": summary, "cases": cases})
            rep = V.Report()
            V.redteam(rep, d, root)
            self.assertEqual([c["what"] for c in statuses(rep, "mismatch")], ["summary.false_block_rate (blocked/controls)"])


def req(level, index, e2e, ct):
    return {"type": "request", "level": level, "index": index, "status": "ok", "e2e_s": e2e, "completion_tokens": ct}


LOAD_RECORDS = [   # levels are labelled by their concurrency, as the load script writes them
    {"type": "level_start", "level": 1}, req(1, 0, 1.0, 10), req(1, 1, 3.0, 20),
    {"type": "http", "level": 1, "attempt": 1, "status": 200}, {"type": "http", "level": 1, "attempt": 1, "status": 200},
    {"type": "level_end", "level": 1, "wall_s": 10.0},
    {"type": "level_start", "level": 2}, req(2, 0, 2.0, 5), req(2, 1, 2.0, 5),
    {"type": "http", "level": 2, "attempt": 1, "status": 429}, {"type": "http", "level": 2, "attempt": 2, "status": 200},
    {"type": "http", "level": 2, "attempt": 1, "status": 200}, {"type": "level_end", "level": 2, "wall_s": 4.0}]


def level(conc, p50, p95, wall, per_min, ct, http):
    return {"concurrency": conc, "completed": 2, "ok": 2, "latency_s": {"p50": p50, "p95": p95, "mean": 2.0},
            "wall_s": wall, "throughput": {"handovers_per_min": per_min, "completion_tokens": ct},
            "http": dict(zip(("attempts", "retries", "status_429"), http))}


# by hand: level 1 2 ok in 10 s (12/min), level 2 2 ok in 4 s (30/min, selected: 0.5 handovers/s)
LOAD_RESULTS = {"records_skipped_lines": [], "http_calls": {"total": 5, "retries": 1, "status_429": 1},
                "levels": [level(1, 2.0, 2.9, 10.0, 12.0, 30, (2, 0, 0)), level(2, 2.0, 2.0, 4.0, 30.0, 10, (3, 1, 1))],
                "per_model": {"M": {"concurrency": 2, "throughput_handovers_per_s": 0.5}}}


class LoadAndCapacity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.load = self.root / "release/benchmarks/load_X"
        write(self.load / "records.jsonl", LOAD_RECORDS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_levels_and_selected_level(self):
        write(self.load / "results.json", LOAD_RESULTS)
        rep = V.Report()
        V.load_test(rep, self.load, self.root)
        self.assertEqual(statuses(rep, "mismatch"), [])
        res = json.loads(json.dumps(LOAD_RESULTS))
        res["per_model"]["M"]["concurrency"] = 1
        write(self.load / "results.json", res)
        rep = V.Report()
        V.load_test(rep, self.load, self.root)
        self.assertEqual([c["what"] for c in statuses(rep, "mismatch")], ["per_model.M.concurrency (selected level)"])

    def capacity(self, hours_per_1000: float) -> V.Report:
        write(self.load / "results.json", LOAD_RESULTS)
        bench = "release/benchmarks/tf_bench_X/results.json"
        write(self.root / bench, {"per_model": {"M": {"tokens_per_handover": {"mean": 1000.0},
                                                      "e2e_latency_s": {"mean": 10.0}}}})
        item = lambda v, src, key: {"value": v, "source": src, "key": key}   # noqa: E731
        lp = "release/benchmarks/load_X/results.json"
        res = {"measured": {"tf_bench": {"path": bench, "items": {
                   "tokens_per_handover": item(1000.0, bench, "per_model.M.tokens_per_handover.mean"),
                   "e2e_latency_mean_s": item(10.0, bench, "per_model.M.e2e_latency_s.mean")}},
               "load_test": {"used": True, "items": {
                   "throughput_handovers_per_s": item(0.5, lp, "per_model.M.throughput_handovers_per_s"),
                   "concurrency": item(2, lp, "per_model.M.concurrency")}}},
               "assumptions": {"updates_per_family_per_day": {"value": 2.0}, "families_per_care_coordinator": {"value": 30.0},
                               "crosscheck_every_update": {"value": False}},
               "conventions": {"days_per_month": 30, "families_scale": 1000},
               # by hand: 2 updates x 1000 families / (0.5 x 3600 per hour) = 1.111 h; 60 updates / 1800 = 0.0333 h
               "outputs": {"tokens_per_family_per_day": 2000.0, "capacity_basis": "load test",
                           "handovers_per_endpoint_hour_at_load_concurrency": 1800.0, "load_concurrency": 2,
                           "hours_per_1000_families_per_day": hours_per_1000, "hours_per_coordinator_per_day": 60 / 1800}}
        d = self.root / "release/benchmarks/capacity_X"
        write(d / "results.json", res)
        rep = V.Report()
        V.capacity(rep, d, self.root)
        return rep

    def test_capacity_uses_the_load_test_throughput_when_it_was_used(self):
        self.assertEqual(statuses(self.capacity(2000 / 1800), "mismatch"), [])
        bad = statuses(self.capacity(2000 * 10 / 3600), "mismatch")   # the sequential formula is the wrong one here
        self.assertEqual([c["what"] for c in bad], ["outputs.hours_per_1000_families_per_day"])


class AgreementBuckets(unittest.TestCase):
    def test_null_other_model_present_is_in_neither_bucket(self):
        units = [{"repeat_count": 3, "other_model_present": True, "reference_match": True},
                 {"repeat_count": 3, "other_model_present": False, "reference_match": True},
                 {"repeat_count": 1, "other_model_present": None, "reference_match": True}]
        res = {"inputs": {"records_jsonl": {"path": "release/benchmarks/tf_bench_X/records.jsonl"}},
               "run": {"models": [], "update_ids": [], "repeats": 3},
               "numbers": {"units": units, "within_model": {}, "confidence_signal": {"reference_agreement": {"pooled": {
                   "by_repeat_count": {"3": {"n": 2, "reference_matched": 2}, "1-2": {"n": 1, "reference_matched": 1}},
                   "by_other_model": {"present": {"n": 1, "reference_matched": 1},
                                      "absent": {"n": 1, "reference_matched": 1}}}}}}}
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            write(root / "release/benchmarks/tf_bench_X/records.jsonl", [])
            d = root / "release/benchmarks/agreement_X"
            write(d / "results.json", res)
            rep = V.Report()
            V.agreement(rep, d, root)
            bucket_rows = [c for c in rep.checks if "by_other_model" in c["what"]]
            self.assertEqual([c["status"] for c in bucket_rows], ["pass", "pass"])
            self.assertTrue(any(c["what"] == "numbers.units (count) vs sum of within_model keys" and c["status"] == "mismatch"
                                for c in rep.checks))


CLAIMS_JSON = {"per_model": {"M": {"success": {"count": 2}, "n_completed": 3, "ci": [0.2077, 0.9385]},
                             "Q3.5-B": {"success": {"count": 1}, "n_completed": 3}},
               "statuses": {"200": 41, "429": 1}, "ids": ["a", "b", "c"]}
SOURCES = """# Sources

`DATA` = `data/claims.json`.

| ID | Claim | Number | Source |
|---|---|---|---|
| B01 | value and relative keys | 2/3 (Wilson 95% 0.21-0.94) | DATA \u2192 `per_model.M.success.count` = 2, `.n_completed` = 3, `.ci` = [0.2077, 0.9385] |
| B02 | wrong value | 5 | DATA \u2192 `per_model.M.success.count` = 5 |
| B03 | dotted model id, wildcard, entries, dict | 3 per model; 41 + 1 | DATA \u2192 `per_model.Q3.5-B.success.count` = 1, `per_model.*.n_completed` = 3, `ids` (3 entries), `statuses` = {200: 41, 429: 1} |
| B04 | dict claim missing a key | 41 | DATA \u2192 `statuses` = {200: 41} |
| L01 | line with quote | 7 | `notes.txt:2` ("seven is 7") |
| L02 | quote not on the line | 7 | `notes.txt:2` ("eight is 8") |
| L03 | number not on the line | 9 | `notes.txt:2` |
| L04 | line past the end | 1 | `notes.txt:99` |
| P01 | not yet | \u2014 | [[PENDING: later run]] |
| E01 | file of one machine | 1 | `D:\\work\\someone\\x.json` \u2192 `a` = 1 |
"""


class Redactions(unittest.TestCase):
    def test_a_documented_redaction_passes_and_a_changed_number_fails(self):
        import redact_local_paths as R
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            original = json.dumps({"cases_file": "old/place/c.json", "n": 40, "rate": 0.5}, indent=1).encode()
            f = write(root / "release/benchmarks/x/results.json", {"cases_file": "<repo>/c.json", "n": 40, "rate": 0.5})
            digest = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
            values = R.values_sha256([json.loads(f.read_bytes())])
            self.assertEqual(values, R.values_sha256([json.loads(original)]))
            write(root / V.REDACTIONS, {"schema": R.SCHEMA, "files": [
                {"path": "release/benchmarks/x/results.json", "original_sha256": digest(original),
                 "redacted_sha256": digest(f.read_bytes()), "values_sha256": values, "format": "json"}]})
            rep = V.Report()
            V.hash_checks(rep, {"evidence": "release/benchmarks/x/results.json", "evidence_sha256": digest(original)},
                          "t", root)
            V.redactions(rep, root)
            self.assertEqual([c["status"] for c in rep.checks], ["pass", "pass", "pass"])
            self.assertIn("documented path redaction", rep.checks[0]["detail"])
            rep = V.Report()
            V.hash_checks(rep, {"evidence": "release/benchmarks/x/results.json", "evidence_sha256": "0" * 64}, "t", root)
            self.assertEqual([c["status"] for c in rep.checks], ["mismatch"], "only the recorded original passes")
            write(f, {"cases_file": "<repo>/c.json", "n": 41, "rate": 0.5})
            rep = V.Report()
            V.redactions(rep, root)
            self.assertEqual([(c["kind"], c["status"]) for c in rep.checks], [("hash", "mismatch"), ("recompute", "mismatch")])


class SourcesTable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root / "data/claims.json", CLAIMS_JSON)
        write(self.root / "notes.txt", "line one\nseven is 7, said twice: seven is 7\n")
        self.sources = write(self.root / "submission/SOURCES.md", SOURCES)

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_row_kind(self):
        rep = V.Report()
        V.sources_md(rep, self.sources, self.root, {})
        by = {c["what"].split()[0]: c["status"] for c in rep.checks}
        self.assertEqual(by, {"B01": "pass", "B02": "mismatch", "B03": "pass", "B04": "mismatch", "L01": "pass",
                              "L02": "mismatch", "L03": "unconfirmed", "L04": "mismatch", "P01": "pending",
                              "E01": "mismatch"})
        e01 = next(c for c in rep.checks if c["what"].startswith("E01"))
        self.assertIn("outside the repository", e01["detail"][0])

    def test_exit_codes(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(V.main(["--root", str(self.root), "--quiet"]), 1)
            write(self.sources, SOURCES.split("| B02")[0] + "| L03 | number not on the line | 9 | `notes.txt:2` |\n")
            out = self.root / "report.json"
            self.assertEqual(V.main(["--root", str(self.root), "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["result"], "PASS")
            self.assertEqual(V.main(["--root", str(self.root), "--strict"]), 1)
            self.assertEqual(V.main(["--root", str(self.root / "missing")]), 2)

    def test_a_frozen_scorecard_snapshot_must_match_its_source(self):
        src = write(self.root / "release/benchmarks/tf_bench_Y/results.json", {"x": 1})
        write(self.root / "handoff_day1/ui/pages/shell/data/tf_bench.json",
              {"frozen": {"kind": "tf_bench", "source_dir": "release/benchmarks/tf_bench_Y", "source_file": "results.json",
                          "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest()}})
        rows = lambda: [c for c in V.verify(self.root)["checks"] if c["what"].startswith("frozen.source_sha256")]  # noqa: E731
        self.assertEqual([c["status"] for c in rows()], ["pass"])
        write(src, {"x": 2})
        self.assertEqual([c["status"] for c in rows()], ["mismatch"])

    def test_absent_result_kinds_are_listed_as_skipped(self):
        report = V.verify(self.root)
        skipped = {c["target"] for c in report["checks"] if c["status"] == "skip"}
        self.assertTrue({"release/benchmarks/load_*", "release/benchmarks/metamorphic_*"} <= skipped)


if __name__ == "__main__":
    unittest.main(verbosity=2)
