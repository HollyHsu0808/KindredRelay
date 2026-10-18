"""Offline tests of scripts/freeze_scorecard_results.py: snapshots of a dry benchmark run, a red-team result and a
validation summary are frozen into a temporary data folder and read back the way the scorecard reads them. No network.

.venv/Scripts/python.exe scripts/test_freeze_scorecard_results.py
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_tf_handover as B  # noqa: E402
import freeze_scorecard_results as F  # noqa: E402

D = F.D   # handoff_day1/ui/pages/shell/scorecard_data.py, as the freeze script and the page import it
ENV_PREFIXES = ("CARERELAY_LLM_", "CARERELAY_PHOTO_", "KINDRED_VERIFIER_", "CARERELAY_STORY")
NAMED_NOT_RUN = ("scripts/test_bench_tf_handover.py", "scripts/test_redteam_safety.py",
                 "handoff_day1/ui/test_timeline_storage.py", "scripts/test_stage3_bounded.py")


def redteam_doc(utc: str, stopped: int, gaps: list[dict], cases: list[dict], closed=()) -> dict:
    return {"run": {"utc": utc, "scope": "s", "cases_file": "scripts/redteam_cases.json"}, "cases": cases,
            "summary": {"cases": len(cases), "attacks": 4, "controls": 1,
                        "block_recall": {"stopped": stopped, "attacks": 4},
                        "block_recall_excluding_known_gaps": {"stopped": stopped, "attacks": 4 - len(gaps)},
                        "false_block_rate": {"blocked": 0, "controls": 1}, "known_gaps": gaps,
                        "gaps_closed": list(closed), "regressions": [], "errors": []}}


def gap(gid: str, target: str, status: str = "gap_confirmed") -> dict:
    return {"id": gid, "category": "c", "target": target, "expected": "block", "actual": "pass", "status": status}


class Freeze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="freeze_scorecard_test_"))
        cls.key = cls.tmp / "private" / "amd_api_key.txt"
        cls.key.parent.mkdir()
        cls.key.write_text("sk-FREEZE-TEST-0000-not-a-key", encoding="utf-8")
        env = patch.dict(os.environ)
        env.start()
        for k in [k for k in os.environ if k.startswith(ENV_PREFIXES)]:
            del os.environ[k]
        try:
            cls.tf_a = cls.tmp / "tf_bench_dryA"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = B.main(["--dry-run", "--models", "A,B", "--cases", "2", "--api-key-file", str(cls.key),
                               "--out", str(cls.tf_a)], sleep=lambda s: None)
            assert code == B.EXIT_OK, code
        finally:
            env.stop()
        # an older run: results.json as the bench wrote it before it redacted the key file's path, one model truncated
        legacy = json.loads((cls.tf_a / "results.json").read_text(encoding="utf-8"))
        legacy["argv"] = ["--models", "A,B", "--api-key-file", str(cls.key), "--out", "release/benchmarks/tf_bench_legacy"]
        legacy["dry_run"] = False
        legacy["pipeline"]["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        a = legacy["per_model"]["A"]
        a["failures"], a["success"]["count"] = {"truncated": 1}, a["n_completed"] - 1
        cls.tf_legacy = cls.tmp / "tf_bench_legacy"
        cls.tf_legacy.mkdir()
        (cls.tf_legacy / "results.json").write_text(json.dumps(legacy, indent=2), encoding="utf-8")
        cases = [{"id": "WS-02", "target": "case_agent_answer", "match": True},
                 {"id": "DX-05", "target": "episode_update", "match": False}]
        cls.rt_before = cls.write_json(cls.tmp / "redteam_before", "results.json", redteam_doc(
            "2026-10-17T09:00:00Z", 2, [gap("WS-02", "case_agent_answer"), gap("DX-05", "episode_update")], cases))
        cls.rt = cls.write_json(cls.tmp / "redteam_now", "results.json", redteam_doc(
            "2026-10-18T01:00:00Z", 3, [gap("DX-05", "episode_update")], cases))
        root = str(D.REPO)
        ran = sorted(p.name for p in (D.REPO / "handoff_day1/agent").glob("test_*.py"))[:3]
        cls.ran = [f"handoff_day1/agent/{n}" for n in ran]
        results = [{"command": [sys.executable, "agent/" + n], "cwd": str(D.REPO / "handoff_day1"), "passed": True,
                    "unittest_cases": 5} for n in ran]
        results.append({"command": [sys.executable, "scripts/eval_handoff_replay.py", "--out", str(cls.tmp / "v" / "replay")],
                        "cwd": root, "passed": True, "unittest_cases": None})
        summary = {"completed_utc": "2026-10-18T01:30:00+00:00", "root": root, "test_processes": len(results),
                   "unittest_cases": 15, "results": results, "passed": True, "exit_code": 0,
                   "sources_unchanged_during_run": True}
        cls.val = cls.write_json(cls.tmp / "validation_ok", "summary.json", summary)
        cls.val_fail = cls.write_json(cls.tmp / "validation_fail", "summary.json",
                                      {**summary, "passed": False, "exit_code": 1, "sources_unchanged_during_run": False})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def write_json(folder: Path, name: str, doc: dict) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return folder

    def freeze(self, data: Path, *extra, tf=None, val=None) -> tuple[int, str, str]:
        argv = [x for d in (tf or (self.tf_a, self.tf_legacy)) for x in ("--tf-bench", str(d))]
        argv += [*extra, "--redteam", str(self.rt), "--validation", str(val or self.val)]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = F.main(argv, data=data)
        return code, out.getvalue(), err.getvalue()

    def test_snapshots_are_copies_with_the_key_path_redacted(self):
        data = self.tmp / "data1"
        code, so, se = self.freeze(data, "--tf-label", "Main run", "--redteam-before", str(self.rt_before))
        self.assertEqual(code, F.EXIT_OK, se)
        self.assertEqual(sorted(p.name for p in data.iterdir()),
                         ["redteam.json", "tf_bench_dryA.json", "tf_bench_legacy.json", "validation.json"])
        for p in data.iterdir():
            text = p.read_text(encoding="utf-8")
            self.assertNotIn(str(self.key), text, p.name)
            self.assertNotIn(json.dumps(str(self.key))[1:-1], text, p.name)
            self.assertNotIn("sk-FREEZE-TEST", text, p.name)
        for name, src, label in (("tf_bench_dryA.json", self.tf_a, "Main run"), ("tf_bench_legacy.json", self.tf_legacy, None)):
            snap = json.loads((data / name).read_text(encoding="utf-8"))
            raw = (src / "results.json").read_bytes()
            meta, doc = snap["frozen"], snap["doc"]
            self.assertEqual((meta["source_sha256"], meta["source_file"], meta["label"]),
                             (hashlib.sha256(raw).hexdigest(), "results.json", label))
            self.assertEqual(Path(meta["source_dir"]).name, src.name)
            original = json.loads(raw)
            i = original["argv"].index("--api-key-file")
            self.assertEqual(doc["argv"][i + 1], F.REDACTED)
            original["argv"][i + 1] = F.REDACTED
            self.assertEqual(doc, F.R.Redactor().obj(original), "nothing but the key file's path and local paths change")
        self.assertEqual(json.loads((data / "tf_bench_dryA.json").read_text(encoding="utf-8"))["frozen"]["redacted_entries"], 0,
                         "the bench already stores <redacted path> (N7)")
        self.assertEqual(json.loads((data / "tf_bench_legacy.json").read_text(encoding="utf-8"))["frozen"]["redacted_entries"], 1)
        val = json.loads((data / "validation.json").read_text(encoding="utf-8"))["frozen"]
        self.assertIsNone(val["git_head"], "validate_abd.py records no commit, so none is claimed")
        self.assertEqual(val["tests_run"], sorted(self.ran + ["scripts/eval_handoff_replay.py"]))
        for t in NAMED_NOT_RUN:
            self.assertIn(t, val["not_covered"])
        for t in self.ran:
            self.assertNotIn(t, val["not_covered"])
        self.assertIn("note: the validation summary records no git commit", so)

        # read back as the page reads it
        runs = D.tf_bench_runs(data=data)
        self.assertEqual(len(runs), 2)
        self.assertFalse(runs[0]["doc"]["dry_run"], "live runs are listed first")
        self.assertIn("tf_bench_legacy.json (frozen copy of", runs[0]["source"])
        self.assertTrue(runs[1]["label"].startswith("Main run"))
        v = D.tf_bench_view(runs[0]["doc"])
        self.assertEqual(len(v["caveats"]), 1)
        self.assertIn('hit max_tokens=2000', v["caveats"][0])
        self.assertIn('thinking/extra_body = {"chat_template_kwargs": {"enable_thinking": false}}', v["caveats"][0])
        rt = D.redteam_run(data=data)
        rv = D.redteam_view(rt["doc"], rt["before"])
        self.assertEqual(rv["closed_gaps"], [{"Case": "WS-02", "Target": "case_agent_answer", "Path": D.CASE_AGENT_PATH}])
        self.assertEqual(rv["open_gaps_by_path"], {D.FAMILY_PATH: ["DX-05 (episode_update)"]})
        self.assertTrue(rv["before"]["block_recall"].startswith("2/4"))
        self.assertTrue(rv["block_recall"].startswith("3/4"))
        self.assertIn("→ before (frozen copy of", rt["before_source"])
        vv = D.validation_view(data=data)
        self.assertEqual((vv["result"], vv["unittest_cases"], vv["candidates"]), ("PASS", 15, 1))
        self.assertTrue(vv["label"].startswith("offline validation run ") and vv["label"].endswith("validation_ok"))

    def test_refreeze_replaces_the_set_and_a_failed_run_is_flagged(self):
        data = self.tmp / "data2"
        self.assertEqual(self.freeze(data)[0], F.EXIT_OK)
        code, so, se = self.freeze(data, tf=(self.tf_a,), val=self.val_fail)
        self.assertEqual(code, F.EXIT_OK, se)
        self.assertEqual(sorted(p.name for p in data.iterdir()), ["redteam.json", "tf_bench_dryA.json", "validation.json"])
        self.assertIn("removed", so)
        self.assertIn("RESULT FAIL", se)
        vv = D.validation_view(data=data)
        self.assertEqual(vv["result"], "FAIL", "a failed run is never shown as a pass")
        self.assertIn("tracked source files changed while it ran", vv["why"])

    def test_bad_inputs_write_nothing(self):
        data = self.tmp / "data3"
        bad = self.write_json(self.tmp / "tf_bench_bad", "results.json", {"schema_version": "x"})
        tokenish = self.tmp / "tf_bench_tokens"
        shutil.copytree(self.tf_a, tokenish)
        cases = [((bad,), ()), ((self.tmp / "missing",), ()), ((tokenish,), ()), ((self.tf_a, self.tf_a), ()),
                 ((self.tf_a,), ("--tf-label", "x", "--tf-label", "y"))]
        for tf, extra in cases:
            with self.subTest(tf=[p.name for p in tf], extra=extra):
                code, so, se = self.freeze(data, *extra, tf=tf)
                self.assertEqual(code, F.EXIT_USAGE)
                self.assertIn("freeze_scorecard_results:", se)
                self.assertFalse(data.exists() and any(data.iterdir()))
        busy = self.tmp / "tf_bench_busy"
        shutil.copytree(self.tf_a, busy)
        later = time.time() + 5
        os.utime(busy / "records.jsonl", (later, later))
        code, _, se = self.freeze(data, tf=(busy,))
        self.assertEqual(code, F.EXIT_USAGE)
        self.assertIn("newer than its results.json", se)

    def test_crosscheck_snapshot(self):
        doc = {"schema_version": "kindredrelay-crosscheck-v1", "dry_run": False, "created_utc": "2026-10-18T01:00:00+00:00",
               "argv": ["eval", "--out", "release/benchmarks/crosscheck_x", "--api-key-file", str(self.key)],
               "acceptance": {"result": "FAIL", "decision": "stays shadow-only", "checks": {}, "incomplete": []},
               "sets": {"variants": {"attacks": 3, "benign": 1}}, "judge": {"model": "Gemma-4-31B-IT"}}
        cc = self.write_json(self.tmp / "crosscheck_x", "results.json", doc)
        data = self.tmp / "data4"
        code, so, se = self.freeze(data, "--crosscheck", str(cc))
        self.assertEqual(code, F.EXIT_OK, se)
        self.assertIn("crosscheck.json", sorted(p.name for p in data.iterdir()))
        text = (data / "crosscheck.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.key), text)
        self.assertNotIn(json.dumps(str(self.key))[1:-1], text)
        snap = json.loads(text)
        self.assertEqual(snap["frozen"]["source_sha256"], hashlib.sha256((cc / "results.json").read_bytes()).hexdigest())
        self.assertEqual(snap["frozen"]["redacted_entries"], 1)
        run = D.crosscheck_run(data=data)
        self.assertIn("crosscheck.json (frozen copy of", run["source"])
        v = D.crosscheck_view(run["doc"])
        self.assertEqual((v["dry_run"], v["result"], v["judge_model"]), (False, "FAIL", "Gemma-4-31B-IT"))
        code, so, _ = self.freeze(data)
        self.assertEqual(code, F.EXIT_OK)
        self.assertNotIn("crosscheck.json", [p.name for p in data.iterdir()], "a freeze without --crosscheck removes it")
        self.assertIn("removed", so)
        bad = self.write_json(self.tmp / "crosscheck_bad", "results.json", {"schema_version": "x"})
        code, _, se = self.freeze(self.tmp / "data5", "--crosscheck", str(bad))
        self.assertEqual(code, F.EXIT_USAGE)
        self.assertIn("is not a scripts/crosscheck_judge.py results.json", se)
        self.assertFalse((self.tmp / "data5").exists())
        (cc / "records.jsonl").write_text("{}\n", encoding="utf-8")
        later = time.time() + 5
        os.utime(cc / "records.jsonl", (later, later))
        code, _, se = self.freeze(self.tmp / "data6", "--crosscheck", str(cc))
        self.assertEqual(code, F.EXIT_USAGE)
        self.assertIn("newer than its results.json", se)

    def test_local_paths_are_redacted_and_numbers_kept(self):
        home = str(Path.home())
        doc = {"schema_version": "kindredrelay-crosscheck-v1", "dry_run": True, "created_utc": "2026-10-18T01:00:00+00:00",
               "cases_file": str(F.ROOT / "scripts" / "redteam_cases.json"), "log": str(Path(home) / "AppData" / "x.log"),
               "acceptance": {"result": "PASS", "checks": {"recall": 0.9375, "n": 32}}, "sets": {"variants": {"attacks": 3}}}
        cc = self.write_json(self.tmp / "crosscheck_local", "results.json", doc)
        data = self.tmp / "data7"
        code, so, se = self.freeze(data, "--crosscheck", str(cc))
        self.assertEqual(code, F.EXIT_OK, se)
        self.assertIn("local paths redacted", so)
        text = (data / "crosscheck.json").read_text(encoding="utf-8")
        snap = json.loads(text)
        self.assertNotIn(home, text)
        self.assertNotIn(json.dumps(home)[1:-1], text)
        self.assertEqual(snap["doc"]["cases_file"], "<repo>/scripts/redteam_cases.json")
        self.assertEqual(snap["doc"]["log"], "<local>/…/x.log")
        self.assertEqual(snap["doc"]["acceptance"], doc["acceptance"])
        self.assertEqual(snap["frozen"]["local_paths_redacted"], 2)
        self.assertIn("redact_local_paths.py", snap["frozen"]["local_path_rule"])
        self.assertEqual(snap["frozen"]["source_sha256"], hashlib.sha256((cc / "results.json").read_bytes()).hexdigest())

    def test_redact_argv(self):
        argv = ["--api-key-file", r"C:\keys\k.txt", "--api-key-file=/srv/u/k", "--out", "release/benchmarks/tf_bench_x",
                "/srv/u/.streamlit/secrets.toml", "D:\\work\\u\\.kindredrelay-private\\x.txt", "--models", "A,B",
                "--api-key-file", F.REDACTED]
        clean, removed = F.redact_argv(argv)
        self.assertEqual(clean, [*["--api-key-file", F.REDACTED, f"--api-key-file={F.REDACTED}", "--out",
                                   "release/benchmarks/tf_bench_x", F.REDACTED, F.REDACTED, "--models", "A,B",
                                   "--api-key-file", F.REDACTED]])
        self.assertEqual(len(removed), 4)
        nested, gone = {"results": [{"command": ["python", "--api-key-file", "k"]}]}, []
        self.assertEqual(F.scrub(nested, gone), {"results": [{"command": ["python", "--api-key-file", F.REDACTED]}]})
        self.assertEqual(gone, ["k"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
