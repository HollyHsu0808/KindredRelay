"""Offline tests of scripts/check_depth_coverage.py on a synthetic repository (no model, no network).

.venv/Scripts/python.exe scripts/test_check_depth_coverage.py
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
import check_depth_coverage as C  # noqa: E402

IDS = "D01-D03"


def body(extra: str = "", up: str = "../") -> str:
    return ("# Doc\n\n"
            f"Benchmark <!-- depth:D01 --> see `release/benchmarks/run_a/summary.md:3` and [run]({up}release/benchmarks/run_a/).\n\n"
            "Red team and metamorphic <!-- depth:D02 D03 --> `scripts/tool.py`\n" + extra)


class DepthCoverage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ("release/benchmarks/run_a", "release/benchmarks/run_b", "research/study_v1", "scripts", "submission"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        (self.root / "release/benchmarks/run_a/summary.md").write_text("x\ny\nz\n", encoding="utf-8")
        (self.root / "scripts/tool.py").write_text("print(1)\n", encoding="utf-8")
        for name in C.REQUIRED:
            self.write(name, body())

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, text: str):
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(text, encoding="utf-8")

    def run_main(self, *extra) -> tuple[int, str, dict]:
        out, err = io.StringIO(), io.StringIO()
        rep = self.root / "report.json"
        with redirect_stdout(out), redirect_stderr(err):
            code = C.main(["--root", str(self.root), "--ids", IDS, "--json", str(rep), *extra])
        report = json.loads(rep.read_text(encoding="utf-8")) if rep.is_file() else {}
        return code, out.getvalue() + err.getvalue(), report

    def test_markers_cover_every_id_and_pass(self):
        code, out, rep = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertTrue(out.strip().endswith("RESULT: PASS"), out)
        cov = rep["documents"]["submission/slides.md"]["coverage"]
        self.assertEqual(cov, {"D01": "marker", "D02": "marker", "D03": "marker"})
        self.assertEqual(rep["documents"]["submission/slides.md"]["markers"]["D02"], [5])

    def test_a_missing_id_fails_and_names_the_document(self):
        self.write("submission/SUBMISSION_TEXT.md", "Only <!-- depth:D01 --> here.\n")
        code, out, rep = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("submission/SUBMISSION_TEXT.md: D02 not covered", rep["failures"])
        self.assertIn("submission/SUBMISSION_TEXT.md: D03 not covered", rep["failures"])
        self.assertIn("RESULT: FAIL", out)

    def test_an_id_written_out_counts_but_not_inside_a_longer_token(self):
        self.write("submission/SUBMISSION_TEXT.md", "Depth items: D01, D02 (red team).\nNot D030 or XD03 or D03-x.\n")
        code, _, rep = self.run_main()
        cov = rep["documents"]["submission/SUBMISSION_TEXT.md"]["coverage"]
        self.assertEqual(cov["D01"], "id")
        self.assertEqual(cov["D02"], "id")
        self.assertEqual(cov["D03"], "missing")
        self.assertEqual(code, 1)

    def test_a_broken_link_next_to_a_marker_fails(self):
        self.write("submission/slides.md", body("\nMore <!-- depth:D01 --> [gone](../release/benchmarks/run_zz/x.md)\n"))
        code, _, rep = self.run_main()
        self.assertEqual(code, 1)
        probs = rep["documents"]["submission/slides.md"]["links"]
        self.assertTrue(any("run_zz" in p["problem"] for p in probs), probs)

    def test_links_away_from_markers_and_external_links_are_not_link_checked(self):
        extra = ("\nNo marker in this paragraph: [gone](nowhere/at/all.md) and `scripts/missing.py`.\n\n"
                 "<!-- depth:D01 --> [site](https://example.org/x) [anchor](#top) `developer.amd.com.cn/radeon/api/v1` "
                 "`per_model.DeepSeek-V4-Flash.e2e_latency_s.p50`\n")
        self.write("submission/slides.md", body(extra))
        code, out, rep = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertEqual(rep["documents"]["submission/slides.md"]["links"], [])

    def test_a_missing_backticked_path_next_to_a_marker_fails_and_line_suffixes_are_ignored(self):
        self.write("submission/slides.md", body("\n<!-- depth:D01 --> `scripts/tool.py:1-2` `scripts/nope.py:4`\n"))
        code, _, rep = self.run_main()
        probs = [p["problem"] for p in rep["documents"]["submission/slides.md"]["links"]]
        self.assertEqual(probs, ["path `scripts/nope.py:4` does not exist"])
        self.assertEqual(code, 1)

    def test_a_cited_evidence_folder_must_exist_anywhere_in_the_document(self):
        extra = ("\nFar from any marker: `release/benchmarks/run_missing/results.json`; glob `release/benchmarks/run_*/` "
                 "is fine; `release/benchmarks/redteam_<UTC>` is a placeholder; research/study_v1/PROTOCOL.md exists.\n")
        self.write("submission/JUDGES_QUICKSTART.md", body(extra))
        code, _, rep = self.run_main()
        ev = rep["documents"]["submission/JUDGES_QUICKSTART.md"]["evidence"]
        self.assertEqual([e["problem"] for e in ev], ["evidence folder release/benchmarks/run_missing does not exist"])
        self.assertEqual(code, 1)

    def test_a_glob_that_matches_nothing_fails(self):
        self.write("submission/JUDGES_QUICKSTART.md", body("\nSee `release/benchmarks/load_*/`.\n"))
        code, _, rep = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("load_*", rep["documents"]["submission/JUDGES_QUICKSTART.md"]["evidence"][0]["problem"])

    def test_placeholders_warn_and_fail_only_with_strict(self):
        self.write("submission/slides.md", body("\nResult: [[PENDING: final rerun]] at [[APP_URL]]\n"))
        code, out, rep = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertEqual([p["text"] for p in rep["documents"]["submission/slides.md"]["pending"]],
                         ["[[PENDING: final rerun]]", "[[APP_URL]]"])
        self.assertIn("PENDING submission/slides.md:7: [[PENDING: final rerun]]", out)
        code, out, rep = self.run_main("--strict")
        self.assertEqual(code, 1)
        self.assertEqual(len(rep["failures"]), 2)

    def test_readme_and_evidence_are_checked_only_when_present(self):
        code, _, rep = self.run_main()
        self.assertEqual(code, 0)
        self.assertNotIn("README.md", rep["documents"])
        self.write("README.md", "# Public readme without the ids\n")
        code, _, rep = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("README.md: D01 not covered", rep["failures"])
        self.write("EVIDENCE.md", body(up=""))
        self.write("README.md", body(up="/"))
        code, _, rep = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(list(rep["documents"])[:2], ["README.md", "EVIDENCE.md"])

    def test_a_missing_required_document_fails(self):
        (self.root / "submission/JUDGES_QUICKSTART.md").unlink()
        code, _, rep = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("submission/JUDGES_QUICKSTART.md: required document not found", rep["failures"])

    def test_files_replaces_the_default_list(self):
        self.write("other/notes.md", "D01 D02 D03\n")
        (self.root / "submission/slides.md").unlink()
        code, _, rep = self.run_main("--files", "other/notes.md")
        self.assertEqual(code, 0)
        self.assertEqual(list(rep["documents"]), ["other/notes.md"])

    def test_ids_parse_ranges_and_lists_and_reject_bad_specs(self):
        self.assertEqual(C.parse_ids("D01-D03,D07"), ["D01", "D02", "D03", "D07"])
        self.assertEqual(len(C.parse_ids("D01-D19")), 19)
        for bad in ("D3", "D05-D02", "X01", ""):
            with self.assertRaises(ValueError):
                C.parse_ids(bad)
        code, out, _ = self.run_main("--ids", "D9")
        self.assertEqual(code, 2)
        self.assertIn("--ids", out)

    def test_a_missing_root_is_a_usage_error(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = C.main(["--root", str(self.root / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("not a directory", err.getvalue())

    def test_the_coverage_table_lists_every_document_and_id(self):
        _, out, _ = self.run_main()
        self.assertIn("document", out)
        self.assertIn("D01 D02 D03", out)
        self.assertIn("submission/SUBMISSION_TEXT.md", out)


if __name__ == "__main__":
    unittest.main()
