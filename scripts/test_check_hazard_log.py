"""Offline tests of scripts/check_hazard_log.py on a synthetic repository (no model, no network).

.venv/Scripts/python.exe scripts/test_check_hazard_log.py
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_hazard_log as H  # noqa: E402

VALIDATE = '''
def source_identity():
    paths = list((ROOT / "handoff_day1/agent").glob("*.py"))

def run(output):
    commands = [x for p in sorted((ROOT / "handoff_day1/agent").glob("test_*.py"))]
    commands += [([sys.executable, "ui/" + name], ROOT / "handoff_day1", True)
                 for name in ("test_page.py",)]
    commands += [x for p in sorted((ROOT / "deploy").glob("test_*.py"))]
'''
HEADER = ("| ID | Hazard | Cause | Effect | Severity | Likelihood | Score | Controls | Verification evidence | "
          "Residual risk | Status |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
GOOD = ("| HZ-01 | h | c | e | 5 | 3 | 15 | `src/guard.py:2` (\"def stop_negation\") | "
        "`handoff_day1/agent/test_guard.py::test_blocks`; `release/r/results.json` → "
        "`summary.per_category[category=dose].stopped` = 4; `scripts/test_other.py::test_more` | S5 × L2 = 10. r | "
        "mitigated |\n")
TAIL = "\n## Tests not run by deploy/validate_abd.py\n\n- `scripts/test_other.py`\n"


class HazardLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        files = {"deploy/validate_abd.py": VALIDATE,
                 "src/guard.py": "import re\ndef stop_negation(text):\n    return 'not' in text\n",
                 "handoff_day1/agent/test_guard.py": "import unittest\nclass T(unittest.TestCase):\n    def test_blocks(self):\n        pass\n",
                 "handoff_day1/ui/test_page.py": "def test_page():\n    pass\n",
                 "scripts/test_other.py": "def test_more():\n    pass\n",
                 "scripts/test_unlisted.py": "def test_x():\n    pass\n",
                 "release/r/results.json": json.dumps({"summary": {"per_category": [
                     {"category": "quote", "stopped": 2}, {"category": "dose", "stopped": 4}]}})}
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_log(self, rows: str, tail: str = TAIL) -> dict:
        log = self.root / "submission/HAZARD_LOG.md"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("# Log\n\n" + HEADER + rows + tail, encoding="utf-8")
        return H.check(self.root, log)

    def test_selection_rule_is_read_from_validate_abd(self):
        self.assertEqual(H.validated_test_files(self.root),
                         {"handoff_day1/agent/test_guard.py", "handoff_day1/ui/test_page.py"})

    def test_a_correct_row_passes(self):
        rep = self.run_log(GOOD)
        self.assertEqual(rep["problems"], [])
        self.assertEqual(rep["result"], "PASS")
        self.assertEqual(len(rep["checks"]), 4)

    def test_a_drifted_line_reports_where_the_quote_is_now(self):
        rep = self.run_log(GOOD.replace("`src/guard.py:2`", "`src/guard.py:3`"))
        self.assertEqual(len(rep["problems"]), 1)
        self.assertIn("quote not on the cited line(s) (found at line 2)", rep["problems"][0])

    def test_missing_test_unlisted_file_and_wrong_value_fail(self):
        row = (GOOD.replace("test_blocks", "test_gone").replace("= 4", "= 5")
               .replace("scripts/test_other.py::test_more", "scripts/test_unlisted.py::test_x"))
        problems = " | ".join(self.run_log(row)["problems"])
        self.assertIn("has no test test_gone", problems)
        self.assertIn("summary.per_category[category=dose].stopped = 5", problems)
        self.assertIn("scripts/test_unlisted.py is neither run by deploy/validate_abd.py nor listed", problems)

    def test_scores_status_and_duplicate_ids(self):
        row = GOOD.replace("| 15 |", "| 14 |").replace("S5 × L2 = 10", "S5 × L2 = 9").replace(
            "mitigated |", "fixed |")
        problems = " | ".join(self.run_log(row + GOOD)["problems"])
        for text in ("score '14' != severity x likelihood", "residual must start", "status must start with one of",
                     "duplicate id"):
            self.assertIn(text, problems)

    def test_a_row_without_controls_fails(self):
        row = GOOD.replace("`src/guard.py:2` (\"def stop_negation\")", "described in prose")
        self.assertIn("no checkable citation in controls", " ".join(self.run_log(row)["problems"]))

    def test_cli_exit_codes(self):
        self.run_log(GOOD)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(H.main(["--root", str(self.root)]), 0)
            self.run_log(GOOD.replace("= 4", "= 3"))
            self.assertEqual(H.main(["--root", str(self.root)]), 1)
            self.assertEqual(H.main(["--root", str(self.root / "nowhere")]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
