#!/usr/bin/env python3
"""Tests of the offline safety red-team runner (scripts/redteam_safety.py) and its case set (scripts/redteam_cases.json).
Stdlib unittest; no network (sockets are blocked during the run), no model, no credentials:
  python scripts/test_redteam_safety.py
Every case that is not a known gap must meet its expectation; a known gap must be reported, open or closed.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import redteam_safety as R  # noqa: E402

OUTCOMES = {"block", "hold", "pass"}
ATTACK_CATEGORIES = {"fabricated_quote", "wrong_source_citation", "partial_quote", "medication_dose", "autonomous_diagnosis",
                     "prompt_injection", "contradiction_superseded", "evidence_gate"}
ROW_KEYS = {"id", "category", "target", "known_gap", "heldout", "expected_outcome", "expected_reason_contains", "defense_at",
            "rationale", "actual_outcome", "reasons", "detail", "match", "reason_matched", "status"}
CASE_COUNT = range(25, 101)   # the third review (2026-10-18) added 33 cases to the 40


class NetworkBlocked:
    """Every way out of the process raises, and each attempt is counted."""
    def __init__(self):
        self.attempts = []

    def __call__(self, *args, **kwargs):
        self.attempts.append(repr(args)[:120])
        raise OSError("network blocked by test_redteam_safety")

    def patches(self):
        return [patch.object(socket.socket, "connect", self), patch.object(socket.socket, "connect_ex", self),
                patch.object(socket, "create_connection", self), patch.object(socket, "getaddrinfo", self)]


class TestRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "run"
        cls.net = NetworkBlocked()
        ps = cls.net.patches()
        for p in ps:
            p.start()
        try:
            cls.res = R.run(cls.out)
        finally:
            for p in ps:
                p.stop()
        cls.rows = {r["id"]: r for r in cls.res["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_offline(self):
        self.assertEqual(self.net.attempts, [])
        self.assertEqual(self.res["summary"]["errors"], [])

    def test_outputs_are_well_formed(self):
        on_disk = json.loads((self.out / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["summary"], json.loads(json.dumps(self.res["summary"], default=sorted)))
        s = on_disk["summary"]
        self.assertIn(s["cases"], CASE_COUNT)
        self.assertEqual(s["cases"], s["attacks"] + s["controls"])
        self.assertEqual(len(on_disk["cases"]), s["cases"])
        for row in on_disk["cases"]:
            with self.subTest(case=row["id"]):
                self.assertLessEqual(ROW_KEYS, set(row))
                self.assertIn(row["expected_outcome"], OUTCOMES)
                self.assertIn(row["actual_outcome"], OUTCOMES)
        for name, part, whole in (("block_recall", "stopped", "attacks"), ("block_recall_excluding_known_gaps", "stopped", "attacks"),
                                  ("false_block_rate", "blocked", "controls")):
            r = s[name]
            self.assertTrue(0 <= r[part] <= r[whole])
            self.assertAlmostEqual(r["rate"], round(r[part] / r[whole], 4))
        self.assertEqual(sum(c["cases"] for c in s["per_category"]), s["cases"])
        self.assertLessEqual(ATTACK_CATEGORIES | {R.CONTROL}, {c["category"] for c in s["per_category"]})
        self.assertEqual(s["exit_code"], 0)
        md = (self.out / "summary.md").read_text(encoding="utf-8")
        self.assertIn("| Category | Cases | Stopped |", md)
        self.assertIn("## Known gaps", md)
        for row in on_disk["cases"]:
            self.assertIn(f"| {row['id']} |", md)

    def test_every_case_that_is_not_a_known_gap_meets_its_expectation(self):
        for row in self.rows.values():
            if row["known_gap"]:
                continue
            with self.subTest(case=row["id"], reasons=row["reasons"]):
                self.assertTrue(row["match"])
                self.assertEqual(row["actual_outcome"], row["expected_outcome"])
                self.assertIn(row["status"], ("protected", "control_pass"))
                if row["expected_reason_contains"] and row["actual_outcome"] != "pass":
                    self.assertTrue(row["reason_matched"])
        self.assertEqual(self.res["summary"]["regressions"], [])
        self.assertEqual(self.res["summary"]["false_blocks"], [])

    def test_known_gaps_are_reported_not_hidden(self):
        s = self.res["summary"]
        gaps = [r for r in self.rows.values() if r["known_gap"]]
        self.assertTrue(gaps)
        self.assertEqual([g["id"] for g in s["known_gaps"]], [g["id"] for g in gaps])
        for g in gaps:
            with self.subTest(case=g["id"]):
                self.assertIn(g["expected_outcome"], ("block", "hold"))   # the safe expectation is kept
                self.assertIn(g["status"], ("gap_confirmed", "gap_partial", "gap_closed"))
        self.assertEqual(s["gaps_closed"], [g["id"] for g in gaps if g["status"] == "gap_closed"])

    def test_model_output_never_reaches_the_family_as_text(self):
        r = self.rows["DX-03"]   # a scripted model "answer" with a diagnosis: the lead is fixed text
        self.assertEqual(r["detail"]["method"], "llm_first_try")
        self.assertNotIn("stroke", r["detail"]["answer"].lower())
        r = self.rows["FQ-02"]   # a refused Case Agent reply: the deterministic reply is what is shown
        self.assertEqual(r["detail"]["method"], "fallback")
        self.assertNotIn("blood thinner", r["detail"]["shown_reply"])

    def test_heldout_cases_are_reported_on_their_own(self):
        h = self.res["summary"]["heldout"]
        held = [r for r in self.rows.values() if r["heldout"]]
        attacks = [r for r in held if r["category"] != R.CONTROL]
        self.assertTrue(attacks and len(held) > len(attacks))   # heldout attacks and heldout controls
        self.assertEqual((h["attacks"], h["controls"]), (len(attacks), len(held) - len(attacks)))
        self.assertEqual(h["missed"], [r["id"] for r in attacks if r["actual_outcome"] == "pass"])
        self.assertEqual(h["stopped"], len(attacks) - len(h["missed"]))
        for r in attacks:   # a missed heldout attack is reported as a known gap, never hidden
            if r["actual_outcome"] == "pass":
                self.assertTrue(r["known_gap"], r["id"])

    def test_defense_references_resolve_to_current_lines(self):
        self.assertEqual(self.res["summary"]["unresolved_defense_refs"], [])
        for row in self.rows.values():
            for ref in row["defense_at"]:
                path, line = ref.rsplit(":", 1)
                self.assertTrue((R.ROOT / path).is_file(), ref)
                self.assertTrue(line.isdigit(), ref)


class TestCaseFile(unittest.TestCase):
    def test_shape(self):
        cases = R.load_cases(R.DEFAULT_CASES)
        self.assertIn(len(cases), CASE_COUNT)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        self.assertLessEqual(ATTACK_CATEGORIES | {R.CONTROL}, {c["category"] for c in cases})
        for c in cases:
            with self.subTest(case=c["id"]):
                self.assertTrue(c["rationale"].strip())
                self.assertTrue(c["defense_refs"])
                self.assertIn(c["target"], R.TARGETS)

    def test_rejects_a_bad_case_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cases.json"
            good = json.loads(R.DEFAULT_CASES.read_text(encoding="utf-8"))["cases"][0]
            for bad in ([good, good], [{**good, "expected": {"outcome": "pass"}}], [{**good, "target": "nope"}],
                        [{**good, "category": R.CONTROL}]):
                p.write_text(json.dumps({"cases": bad}), encoding="utf-8")
                with self.subTest(bad=[(c["id"], c["category"], c["target"], c["expected"]) for c in bad]):
                    with self.assertRaises(ValueError):
                        R.load_cases(p)


class TestExitCode(unittest.TestCase):
    def _main(self, cases: list[dict], tmp: Path) -> tuple[int, dict]:
        p = tmp / "cases.json"
        p.write_text(json.dumps({"cases": cases}), encoding="utf-8")
        out = tmp / "out"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = R.main(["--out", str(out), "--cases", str(p)])
        return code, json.loads((out / "results.json").read_text(encoding="utf-8"))["summary"]

    def setUp(self):
        self.cases = {c["id"]: c for c in R.load_cases(R.DEFAULT_CASES)}

    def test_a_regression_of_a_protected_attack_fails_the_run(self):
        # the control's faithful fact, presented as an attack the code must block: it passes, so this is a regression
        broken = {**self.cases["BC-01"], "id": "X-01", "category": "medication_dose",
                  "expected": {"outcome": "block", "reason_contains": None}}
        with tempfile.TemporaryDirectory() as tmp:
            code, s = self._main([broken], Path(tmp))
        self.assertEqual((code, s["regressions"]), (1, ["X-01"]))

    def test_open_gaps_and_false_blocks_do_not_fail_the_run(self):
        gap = self.cases["HO-01"]   # still open (held-out diagnosis phrasing); DX-05 and MD-06, earlier examples, are closed
        false_block = {**self.cases["MD-01"], "id": "X-02", "category": R.CONTROL, "expected": {"outcome": "pass", "reason_contains": None}}
        with tempfile.TemporaryDirectory() as tmp:
            code, s = self._main([gap, false_block], Path(tmp))
        self.assertEqual(code, 0)
        self.assertEqual(s["false_blocks"], ["X-02"])
        self.assertEqual([g["id"] for g in s["known_gaps"]], ["HO-01"])

    def test_a_crash_fails_the_run(self):
        crash = {**self.cases["BC-01"], "id": "X-03", "input": {"text_from_update": "u99", "fact": {}}}
        with tempfile.TemporaryDirectory() as tmp:
            code, s = self._main([crash], Path(tmp))
        self.assertEqual((code, s["errors"]), (1, ["X-03"]))

    def test_cli_refuses_an_existing_out_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "keep.txt").write_text("x", encoding="utf-8")
            p = subprocess.run([sys.executable, str(HERE / "redteam_safety.py"), "--out", str(out)], capture_output=True, text=True,
                               timeout=300)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("already exists", p.stderr)
            self.assertEqual(sorted(x.name for x in out.iterdir()), ["keep.txt"])

    def test_cli_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            p = subprocess.run([sys.executable, str(HERE / "redteam_safety.py"), "--out", str(out)], capture_output=True, text=True,
                               timeout=300)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("regressions: none; errors: none", p.stdout)
            self.assertTrue((out / "results.json").is_file() and (out / "summary.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
