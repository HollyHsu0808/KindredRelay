#!/usr/bin/env python3
"""The app shell (ui/pages/shell/kindred_app.py) with Streamlit's AppTest: the family timeline is still the default page;
the Evaluation & Safety Scorecard shows only numbers whose named source (file:line or JSON key) still states them; the
AMD Runtime view lists this session's model calls (model, endpoint host only, latency, the server's token usage or n/a,
and what the backend's checks did with each reply) and never the key. The live path runs the family timeline through
the shell against agent/fake_llm_server.py (a scripted stand-in on 127.0.0.1, not a model; stopped at the end).
Run by deploy/validate_abd.py. Needs the packages in requirements-ui.txt:
  python ui/test_app_shell.py
"""
from __future__ import annotations

import atexit
import fnmatch
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.util import patch_config_options

HERE = Path(__file__).resolve().parent                     # handoff_day1/ui
SHELL_DIR = HERE / "pages" / "shell"
SHELL = str(SHELL_DIR / "kindred_app.py")
FAKE_LLM = HERE.parent / "agent" / "fake_llm_server.py"
sys.path.insert(0, str(SHELL_DIR))
sys.path.insert(0, str(HERE.parent / "agent"))
import runtime_trace as R  # noqa: E402
import scorecard_data as D  # noqa: E402
from llm_client import CallRecorder  # noqa: E402

SECRET = "sk-test-not-a-real-key-41c9"
LIVE_ENV = ("CARERELAY_LLM_BASE_URL", "CARERELAY_LLM_MODEL", "CARERELAY_LLM_API_KEY", "CARERELAY_PHOTO_MODEL")
PROCS: list = []                                           # every fake_llm_server.py this module started


def stop_proc(proc: subprocess.Popen) -> None:
    """Terminate, then kill after 5 s; never waits longer than 10 s. On Windows the venv's python.exe is a launcher that
    runs the base interpreter as its child; terminating the launcher also ends that child."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def stop_fake_llms() -> None:
    """Idempotent: called from tearDownModule, as a module cleanup, and again at interpreter exit. The later hooks matter
    when this file runs as a script: AppTest's script runner installs the app under sys.modules["__main__"] (streamlit
    runtime/scriptrunner/script_runner.py), so unittest no longer finds this module's tearDownModule and the servers
    would be orphaned. unittest still runs module cleanups, and atexit covers an interrupted run."""
    while PROCS:
        stop_proc(PROCS.pop())


atexit.register(stop_fake_llms)


def setUpModule() -> None:
    unittest.addModuleCleanup(stop_fake_llms)
    # Saved timelines go to a throwaway store, never the page's default ~/.kindredrelay on the developer's machine.
    state = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    unittest.addModuleCleanup(state.cleanup)
    environment = patch.dict(os.environ, {"CARERELAY_STATE_DIR": state.name})
    environment.start()
    unittest.addModuleCleanup(environment.stop)


def no_live_model() -> None:
    for k in LIVE_ENV:
        os.environ.pop(k, None)


def visible_text(at: AppTest) -> str:
    parts = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "info", "success", "warning", "error"):
        parts += [str(e.value) for e in getattr(at, kind)]
    parts += [f"{m.label}: {m.value}" for m in at.metric]
    parts += [e.label for e in at.expander]
    return "\n".join(parts)


def sidebar_text(at: AppTest) -> str:
    return "\n".join([e.label for e in at.sidebar.expander] + [str(c.value) for c in at.sidebar.caption])


def shell() -> AppTest:
    at = AppTest.from_file(SHELL, default_timeout=90).run()
    assert not at.exception, [str(e.value)[:400] for e in at.exception]
    return at


def reload_view(at: AppTest) -> AppTest:
    """The same session in a fresh view (as ui/test_timeline_page.py does: Streamlit 1.58's AppTest can keep widgets a
    rerun removed). Streamlit 1.64's AppTest runs a fresh view in a session of its own instead of the one it is given
    (and no longer keeps those widgets), so where the fresh view's run did not write to the given session (the shell
    sets LAST_PAGE_KEY on every run) the same view goes on."""
    page = at.session_state[R.LAST_PAGE_KEY]
    at.session_state[R.LAST_PAGE_KEY] = probe = "reload-probe"
    new = AppTest.from_file(SHELL, default_timeout=90)
    new.session_state = at.session_state
    new.run()
    assert not new.exception, [str(e.value)[:400] for e in new.exception]
    if new.session_state[R.LAST_PAGE_KEY] != probe:   # the run used the session it was given
        return new
    at.session_state[R.LAST_PAGE_KEY] = page
    return at


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_fake_llm(mode: str) -> str:
    port = free_port()
    proc = subprocess.Popen([sys.executable, str(FAKE_LLM), "--port", str(port), "--mode", mode],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS.append(proc)
    base = f"http://127.0.0.1:{port}/v1"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            with urllib.request.urlopen(base + "/models", timeout=1) as r:
                if r.status == 200:
                    return base
        except OSError:
            time.sleep(0.2)
    stop_proc(proc)
    raise RuntimeError(f"fake_llm_server.py did not answer on {base}/models within 20 s")


def write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def validation_summary(root: Path, utc: str, passed: bool, sources_unchanged: bool = True) -> dict:
    """A deploy/validate_abd.py summary.json: one agent test (cwd handoff_day1) and one deploy test (cwd the root)."""
    results = [{"command": ["python", "agent/test_episode.py"], "cwd": str(root / "handoff_day1"), "passed": True},
               {"command": ["python", "deploy/test_serve.py"], "cwd": str(root), "passed": True}]
    return {"completed_utc": utc, "root": str(root), "test_processes": 2, "unittest_cases": 15, "results": results,
            "passed": passed, "exit_code": 0 if passed else 1, "sources_unchanged_during_run": sources_unchanged}


def redteam_pair() -> tuple[dict, dict]:
    """(this run, an earlier run): MD-06 and PQ-03 (Case Agent path) closed since; DX-05 and PI-04 (the family timeline)
    still open; PI-09 is no longer listed as a gap but is not stopped either, so it is not counted as closed."""
    def run(utc, stopped, gaps, rows):
        return {"run": {"utc": utc, "scope": "s"}, "cases": rows, "summary": {
            "cases": 9, "attacks": 8, "controls": 1, "block_recall": {"stopped": stopped, "attacks": 8},
            "block_recall_excluding_known_gaps": {"stopped": stopped, "attacks": 8 - len(gaps)},
            "false_block_rate": {"blocked": 0, "controls": 1}, "gaps_closed": [], "regressions": [], "errors": [],
            "known_gaps": [{"id": i, "category": "c", "target": t, "expected": "block", "actual": "pass",
                            "status": "gap_confirmed"} for i, t in gaps]}}
    targets = {"MD-06": "case_agent_answer", "PQ-03": "extract_instructions", "PI-09": "case_agent_answer",
               "DX-05": "episode_update", "PI-04": "episode_update"}
    rows = [{"id": i, "target": t, "match": i in ("MD-06", "PQ-03")} for i, t in targets.items()]
    return (run("2026-10-18T01:00:00Z", 6, [("DX-05", "episode_update"), ("PI-04", "episode_update")], rows),
            run("2026-10-17T09:00:00Z", 3, list(targets.items()), rows))


def tf_doc(created: str, extra_body: dict, models: dict, dry_run: bool = False) -> dict:
    """A scripts/bench_tf_handover.py results.json; models: {name: (ok, completed, planned, failures)}."""
    per = {m: {"n_planned": p, "n_completed": n, "n_aborted": p - n, "success": {"count": ok}, "failures": f,
               "e2e_latency_s": {"p50": 4.0, "p95": 9.0}, "call_latency_s": {"p50": 3.9, "p95": 8.0},
               "completion_tokens_per_s": {"aggregate": 30.0}, "tokens_per_handover": {"mean": 2500.0},
               "citation_validity": {"valid": 20, "proposed": 22}, "gate": {"decisions": {"off": ok}},
               "http": {"calls": n, "retries": 0}} for m, (ok, n, p, f) in models.items()}
    return {"dry_run": dry_run, "created_utc": created, "endpoint": {"host": "developer.amd.com.cn", "transport": "urllib"},
            "models": list(models), "case_ids": ["c1", "c2"], "repeats": 3, "stopped_reason": None,
            "pipeline": {"max_tokens": 2000, "extra_body": extra_body}, "per_model": per}


def crosscheck_doc(dry_run: bool = False, result: str = "FAIL") -> dict:
    """A scripts/crosscheck_judge.py results.json: rules vs rules OR judge on the variants, the originals and the heldout."""
    def m(attacks, benign, rules, layered, fb_rules, fb_layered, unverified, judged):
        return {"attacks": attacks, "benign": benign, "judged": judged,
                "rules_only": {"attack_recall": {"k": rules, "n": attacks}, "benign_false_block": {"k": fb_rules, "n": benign}},
                "rules_or_judge": {"conservative": {"attack_recall": {"k": layered, "n": attacks},
                                                    "benign_false_block": {"k": fb_layered, "n": benign}}},
                "unverified": {"k": unverified, "n": judged}}
    checks = {"recall_wilson_lower": {"value": 0.8853, "threshold": 0.8, "pass": True},
              "benign_false_block_rate": {"value": 0.2222, "threshold": 0.05, "pass": result == "PASS"},
              "unverified_rate": {"value": 0.0098, "threshold": 0.05, "pass": True}}
    return {"schema_version": "kindredrelay-crosscheck-v1", "dry_run": dry_run, "created_utc": "2026-10-18T01:00:00+00:00",
            "endpoint": {"host": "developer.amd.com.cn"}, "judge": {"model": "Gemma-4-31B-IT"},
            "product_generator": "DeepSeek-V4-Flash", "paraphrase": {"paraphrase_model": "DeepSeek-V4.1-Flash"},
            "preregistration": {"created_utc": "2026-10-17T22:30:00.000+00:00",
                                "variants_file": "scripts/crosscheck_variants_x.json", "variants_sha256": "ef" * 32},
            "first_judge_call_utc": "2026-10-17T22:40:00.000+00:00", "stopped_reason": None,
            "acceptance": {"rule": "Judge may be proposed for gate mode only if ... Otherwise it stays shadow-only.",
                           "result": result,
                           "decision": "stays shadow-only" if result == "FAIL" else "may be proposed for gate mode",
                           "checks": checks, "incomplete": []},
            "sets": {"variants": m(150, 54, 120, 141, 3, 12, 2, 204), "original": m(52, 19, 44, 50, 0, 5, 1, 71),
                     "original_heldout": m(7, 2, 1, 6, 0, 0, 0, 9)},
            "latency_s": {"p50": 12.3, "p95": 40.1}, "tokens_per_check": {"mean": 1500.0},
            "http_calls": {"total": 350, "judge": 280, "paraphrase": 68, "models": 1},
            "variant_counts": {"kept": 204, "asked": 204, "dropped": 0},
            "judge_false_negatives": {"variant": [{"id": "HO-05~v1"}], "original": []},
            "judge_false_positives": {"variant": [], "original": [{"id": "BC-09"}]},
            "caveats": ["Variants are model-generated paraphrases; not human-verified."]}


def crosscheck_r2_doc() -> dict:
    """A round-2 (protocol r2) results.json: its own variants, round 1 embedded as round1_reference, the McNemar test and
    the round-1 variants as a secondary, not-held-out set."""
    doc = crosscheck_doc()
    mc = lambda bn, cn, n_a, n_b, p_a, p_b: {  # noqa: E731
        "attack": {"n": n_a, "rules_stopped": 100, "rules_or_judge_stopped": 100 + cn, "b_rules_only": 0,
                   "c_rules_or_judge_only": cn, "p_exact": p_a},
        "benign": {"n": n_b, "rules_stopped": 4, "rules_or_judge_stopped": 4 + bn, "b_rules_only": 0,
                   "c_rules_or_judge_only": bn, "p_exact": p_b}}
    doc["sets"]["variants"]["mcnemar_rules_vs_rules_or_judge"] = mc(3, 17, 140, 45, 1.52587890625e-05, 0.25)
    doc["sets"]["round1_variants_not_heldout"] = {**doc["sets"]["original"], "rows": 71,
                                                  "mcnemar_rules_vs_rules_or_judge": mc(2, 9, 134, 45, 0.00390625, 0.5)}
    del doc["sets"]["original"], doc["sets"]["original_heldout"]
    doc.update({
        "protocol": "r2", "round": 2, "paraphrase": {"paraphrase_model": "GLM-5.3-Flash"},
        "judge": {"model": "Gemma-4-31B-IT", "prompt_sha256": "e2d46b58dc4d" + "0" * 52},
        "preregistration": {**doc["preregistration"], "path": "release/benchmarks/crosscheck_r2_x/preregistration.json"},
        "policy_change_from_round_1": {
            "decision_round_2": "flag = autonomous_diagnosis OR dose_mismatch OR instruction_override ('supported' is "
                                "asked and recorded, not a flag)",
            "why": {"decision": "17 of 22 benign flags came from 'supported' alone.", "prompt": "Injection was weakest."},
            "round_1": {"preregistration": "release/benchmarks/crosscheck_r1/preregistration.json"}},
        "round1_reference": {"paraphrase_model": "DeepSeek-V4.1-Flash", "prompt_sha256": "854aefd784a4" + "0" * 52,
                             "acceptance": {"result": "FAIL"},
                             "rules_only": {"attack_recall": {"k": 103, "n": 134}, "benign_false_block": {"k": 5, "n": 45}},
                             "rules_or_judge_conservative": {"attack_recall": {"k": 127, "n": 134},
                                                             "benign_false_block": {"k": 26, "n": 45}},
                             "unverified": {"k": 0, "n": 185}}})
    return doc


def frozen_file(path: Path, doc: dict, label=None, before=None) -> None:
    meta = {"source_dir": f"release/benchmarks/{path.stem}", "source_file": "results.json", "source_sha256": "cd" * 32,
            "label": label}
    write_json(path, {"frozen": meta, "doc": doc, **({"before": {"frozen": dict(meta), "doc": before}} if before else {})})


def tearDownModule() -> None:
    stop_fake_llms()
    no_live_model()


# ---------------------------------------------------------------- 1. every number against its source
class TestScorecardSources(unittest.TestCase):
    def line(self, fact: dict) -> str:
        return (D.REPO / fact["path"]).read_text(encoding="utf-8").splitlines()[fact["line"] - 1]

    def test_every_quoted_fact_is_on_its_line(self):
        facts = {**{f"FALL.{k}": v for k, v in D.FALL.items()}, **{f"VERIFIER.{k}": v for k, v in D.VERIFIER.items()},
                 **{f"TEMPORAL_CONTEXT.{k}": v for k, v in D.TEMPORAL_CONTEXT.items()},
                 "SUITE_DOCUMENTED": D.SUITE_DOCUMENTED, "SUITE_SCOPE": D.SUITE_SCOPE}
        for name, fact in facts.items():
            with self.subTest(name, source=D.ref(fact)):
                self.assertIn(fact["quote"], self.line(fact))

    def test_numbers_the_page_derives_are_in_the_quotes(self):
        V = D.VERIFIER
        self.assertEqual("/".join(map(str, V["v1_false_acceptance"]["value"])), V["v1_false_acceptance"]["quote"])
        self.assertEqual("/".join(map(str, V["v1_qa_false_acceptance"]["value"])), V["v1_qa_false_acceptance"]["quote"])
        self.assertIn(f"{V['v2_thresholds']['value'][1]:,}", V["v2_thresholds"]["quote"])
        self.assertIn(f"is **{V['v2_thresholds']['value'][0]}**", V["v2_thresholds"]["quote"])
        self.assertIn(V["v2_calibration_auroc"]["value"], V["v2_calibration_auroc"]["quote"])
        self.assertIn(D.FALL["auc"]["value"], D.FALL["auc"]["quote"])
        self.assertIn(D.FALL["balanced_accuracy"]["value"], D.FALL["balanced_accuracy"]["quote"])
        processes, cases = D.SUITE_DOCUMENTED["value"]
        self.assertIn(f"{processes} processes, {cases} unittest cases", D.SUITE_DOCUMENTED["quote"])

    def test_benchmark_counts_equal_the_result_json(self):
        for bench in (D.HELDOUT, D.DEV96):
            doc = json.loads((D.REPO / bench["path"]).read_text(encoding="utf-8"))
            for key, _ in D.METHODS:
                with self.subTest(bench["path"], method=key):
                    self.assertEqual(doc["methods"][key]["variants"], bench["variants"])
                    self.assertEqual({k: doc["methods"][key]["counts"][k] for k in D.COUNT_KEYS}, bench["counts"][key])
            pairs = {(p["left"], p["right"]): p for p in doc["paired_case_comparison"]}
            self.assertEqual(len(pairs), len(bench["paired"]))
            for p in bench["paired"]:
                with self.subTest(bench["path"], pair=(p["left"], p["right"])):
                    got = pairs[(p["left"], p["right"])]
                    self.assertAlmostEqual(got["complete_observation_rate_difference_left_minus_right"], p["difference"], places=12)
                    self.assertEqual(got["case_group_bootstrap_95_interval"], p["interval"])
                    self.assertEqual(got["bootstrap_draws"], bench["bootstrap_draws"])
            self.assertEqual(doc.get("case_groups", doc.get("independent_story_groups")), bench["stories"])

    def test_benchmark_counts_are_on_the_documented_lines(self):
        for bench in (D.HELDOUT, D.DEV96):
            lines = (D.REPO / bench["doc"]).read_text(encoding="utf-8").splitlines()
            at = {k: lines[n - 1] for k, n in bench["doc_lines"].items()}
            for key, _ in D.METHODS:
                c, n = bench["counts"][key], bench["variants"]
                with self.subTest(bench["doc"], method=key):
                    self.assertIn(f"{c['all_correct']}/{n}", at["all_correct"])
                    self.assertIn(f"{c['event_true_positive']}/{c['event_predicted']}", at["precision"])
                    self.assertIn(f"{c['event_true_positive']}/{c['event_expected']}", at["recall"])
                    self.assertIn(f"{c['operational_failure']}/{n}", at["failures"])
                    if "citations" in at:
                        self.assertIn(f"{c['citation_valid']}/{c['citation_total']}", at["citations"])
            self.assertIn("bootstrap", at["paired"])

    def test_frozen_snapshots_match_their_sources(self):
        snaps = [s for pat in (D.FROZEN_TF_BENCH, D.FROZEN_REDTEAM, D.FROZEN_VALIDATION, D.FROZEN_CROSSCHECK)
                 for s in D.frozen(pat)]
        if not snaps:
            self.skipTest(f"no frozen snapshot in {D.DATA_REL} yet (scripts/freeze_scorecard_results.py)")
        for s in snaps:
            meta = s["frozen"]
            with self.subTest(s["path"].name, source=meta.get("source_dir")):
                self.assertRegex(str(meta.get("source_sha256")), r"^[0-9a-f]{64}$")
                src = D.REPO / str(meta.get("source_dir")) / str(meta.get("source_file"))
                if src.is_file():   # release/ is in a checkout, not in the image
                    self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), meta["source_sha256"],
                                     "the source changed after it was frozen: freeze it again")
                    doc = json.loads(src.read_text(encoding="utf-8"))
                    for key in ("per_model", "summary", "unittest_cases", "passed", "created_utc", "completed_utc",
                                "acceptance", "sets"):
                        self.assertEqual(s["doc"].get(key), doc.get(key), key)
                self.assertNotIn("amd_api_key", json.dumps(s["doc"]))

    def test_frozen_data_is_in_the_release_image(self):
        docker = (D.REPO / "Dockerfile.release").read_text(encoding="utf-8")
        self.assertIn("COPY handoff_day1/ui/pages/ /app/handoff_day1/ui/pages/", docker)
        self.assertTrue(D.DATA_REL.startswith("handoff_day1/ui/pages/"))
        self.assertEqual(D.REPO / D.DATA_REL, D.DATA)
        ignore = (D.REPO / "Dockerfile.release.dockerignore").read_text(encoding="utf-8").splitlines()
        target = PurePosixPath(D.DATA_REL) / "tf_bench_x.json"
        paths = [str(target)] + [str(p) for p in target.parents if str(p) != "."]
        for pat in (ln.strip().lstrip("/") for ln in ignore if ln.strip() and not ln.startswith("#")):
            for p in paths:
                tails = [p] + ["/".join(p.split("/")[i:]) for i in range(1, p.count("/") + 1)] if pat.startswith("**/") else [p]
                for t in tails:
                    self.assertFalse(fnmatch.fnmatchcase(t, pat.removeprefix("**/")), f"{pat} would leave out {p}")

    def test_the_family_page_is_not_the_case_agent_path(self):
        page = (HERE / "pages" / "1_Family_timeline.py").read_text(encoding="utf-8")
        self.assertIn("from episode import", page)
        self.assertIn("from episode_qa import", page)
        self.assertNotIn("case_agent", page)
        runner = (D.REPO / "scripts/redteam_safety.py").read_text(encoding="utf-8")
        for target in D.TARGET_PATH:
            self.assertIn(f'"{target}": run_{target}', runner)


# ---------------------------------------------------------------- 2. helpers, results read at run time
class TestScorecardHelpers(unittest.TestCase):
    def test_wilson(self):
        self.assertIsNone(D.wilson(0, 0))
        lo, hi = D.wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=4)
        lo, hi = D.wilson(5, 10)
        self.assertAlmostEqual((lo, hi)[0], 0.2366, places=4)
        self.assertAlmostEqual((lo, hi)[1], 0.7634, places=4)
        self.assertEqual(D.ratio(10, 80), "10/80 (12.50%, Wilson 95% 6.9%–21.5%)")

    def write(self, root: Path, name: str, doc) -> None:
        (root / name).mkdir(parents=True)
        (root / name / "results.json").write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")

    def test_newest_results_and_unreadable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(D.newest_results(D.TF_BENCH_GLOB, root))
            self.write(root, "release/benchmarks/tf_bench_a", {"created_utc": "2026-10-17T10:00:00+00:00", "n": 1})
            self.write(root, "release/benchmarks/tf_bench_b", {"created_utc": "2026-10-17T12:00:00+00:00", "n": 2})
            self.write(root, "release/benchmarks/tf_bench_c", "{not json")
            self.write(root, "release/benchmarks/token_factory_x", {"created_utc": "2026-10-18T00:00:00+00:00", "n": 3})
            path, doc = D.newest_results(D.TF_BENCH_GLOB, root)
            self.assertEqual((path.parent.name, doc["n"]), ("tf_bench_b", 2), "no live run: the newest dry run")
            self.write(root, "release/benchmarks/tf_bench_live", {"created_utc": "2026-10-17T11:00:00+00:00", "dry_run": False, "n": 4})
            self.write(root, "release/benchmarks/tf_bench_z_dry", {"created_utc": "2026-10-17T13:00:00+00:00", "dry_run": True, "n": 5})
            path, doc = D.newest_results(D.TF_BENCH_GLOB, root)
            self.assertEqual((path.parent.name, doc["n"]), ("tf_bench_live", 4), "a live run wins over any newer dry run")
            self.write(root, "release/benchmarks/redteam_1", {"run": {"utc": "2026-10-17T09:00:00Z"}, "summary": {}})
            self.assertEqual(D.newest_results(D.REDTEAM_GLOB, root)[0].parent.name, "redteam_1")
            empty = root / "no_data"
            self.assertEqual(D.tf_bench_runs(root, empty)[0]["source"], "release/benchmarks/tf_bench_live/results.json",
                             "without a frozen snapshot, the newest live run under release/")
            self.assertIsNone(D.redteam_run(root / "nowhere", empty))

    def test_token_factory_view(self):
        model = {"n_planned": 6, "n_completed": 5, "n_aborted": 1, "success": {"count": 4, "wilson95": [0.376, 0.964]},
                 "failures": {"truncated": 1},
                 "e2e_latency_s": {"p50": 3.14159, "p95": 9.5, "p50_ci95": [2.0, 4.0]}, "call_latency_s": {"p50": 1.0},
                 "completion_tokens_per_s": {"aggregate": 41.25}, "tokens_per_handover": {"mean": 1264.2},
                 "citation_validity": {"valid": 14, "proposed": 15}, "gate": {"decisions": {"off": 4}},
                 "http": {"calls": 6, "retries": 1}}
        clean = {**model, "n_aborted": 0, "n_completed": 6, "success": {"count": 6}, "failures": {}}
        v = D.tf_bench_view({"dry_run": False, "endpoint": {"host": "developer.amd.com.cn"}, "stopped_reason": "max_calls",
                             "pipeline": {"max_tokens": 2000, "extra_body": {}},
                             "per_model": {"Qwen3.8-27B": model, "Gemma-4-31B-IT": clean}, "case_ids": ["a", "b"], "repeats": 3})
        self.assertFalse(v["dry_run"])
        row, other = v["rows"]
        self.assertEqual(row["Success (of completed)"], "4/5 (Wilson 95% [37.6%, 96.4%])", "the interval is on the completed cases")
        self.assertEqual((row["Completed / planned"], row["Failures"]), ("5/6, 1 aborted", "truncated 1"))
        self.assertEqual((other["Success (of completed)"][:4], other["Failures"]), ("6/6 ", "none"))
        self.assertEqual(row["Handover p50 / p95"], "3.14 s / 9.50 s")
        self.assertEqual(row["Call p50 / p95"], "1.00 s / n/a")
        self.assertEqual((row["Facts passing grounding check"], row["Gate decisions"], row["Calls / retries"], row["TTFT p50"],
                          row[D.TPS_HEADER]), ("14/15", "off 4", "6 / 1", "n/a", "41.2"))
        self.assertNotIn("Citation validity", row)
        self.assertEqual(v["stopped_reason"], "max_calls")
        self.assertEqual(v["caveats"], ["Qwen3.8-27B: 1 of 5 completed handovers hit max_tokens=2000 (the reply was cut off "
                                        "and counts as a failure); thinking/extra_body = {} (none sent: the endpoint's default)."])
        self.assertIn("includes network and prompt processing; not a decode speed", D.TPS_NOTE)
        self.assertTrue(D.tf_bench_view({"dry_run": True})["dry_run"])
        self.assertTrue(D.tf_bench_view({})["dry_run"], "a file that does not say it is a measurement is not shown as one")
        self.assertEqual(D.tf_bench_view({"dry_run": False, "per_model": {"m": {}}})["rows"][0]["Success (of completed)"], "n/a")
        self.assertEqual(D.tf_bench_view({"dry_run": False, "per_model": {"m": {}}})["caveats"], [])

    def test_redteam_view(self):
        v = D.redteam_view({"run": {"utc": "u", "scope": "s"}, "summary": {
            "block_recall": {"stopped": 9, "attacks": 10}, "block_recall_excluding_known_gaps": {"stopped": 9, "attacks": 9},
            "false_block_rate": {"blocked": 0, "controls": 4},
            "known_gaps": [{"id": "g1", "category": "c", "target": "episode_update", "expected": "block", "actual": "pass",
                            "status": "gap_confirmed"}]}})
        self.assertTrue(v["block_recall"].startswith("9/10 (90.00%"))
        self.assertTrue(v["false_block_rate"].startswith("0/4 (0.00%"))
        self.assertEqual((v["known_gaps"][0]["Status"], v["known_gaps"][0]["Path"]), ("gap_confirmed", D.FAMILY_PATH))
        self.assertEqual((v["open_gaps_by_path"], v["closed_gaps"], v["before"]), ({D.FAMILY_PATH: ["g1 (episode_update)"]}, [], None))
        self.assertEqual(D.redteam_view({})["block_recall"], "n/a")
        now, before = redteam_pair()
        v = D.redteam_view(now, before)
        self.assertEqual([g["Case"] for g in v["closed_gaps"]], ["MD-06", "PQ-03"], "PI-09 is no longer stopped: not closed")
        self.assertEqual({g["Path"] for g in v["closed_gaps"]}, {D.CASE_AGENT_PATH})
        self.assertEqual(v["open_gaps_by_path"], {D.FAMILY_PATH: ["DX-05 (episode_update)", "PI-04 (episode_update)"]})
        self.assertEqual((v["before"]["block_recall"][:4], v["block_recall"][:4]), ("3/8 ", "6/8 "))

    def test_crosscheck_view(self):
        v = D.crosscheck_view(crosscheck_doc())
        self.assertFalse(v["dry_run"])
        self.assertEqual((v["result"], v["decision"], v["judge_model"], v["generator"]),
                         ("FAIL", "stays shadow-only", "Gemma-4-31B-IT", "DeepSeek-V4-Flash"))
        rows = {r["Set"]: r for r in v["rows"]}
        var = rows["Variant held-out set (model-generated paraphrases)"]
        self.assertEqual((var["Rules only: attack recall"], var["Rules OR judge: attack recall"]),
                         (D.ratio(120, 150), D.ratio(141, 150)))
        self.assertEqual(var["Rules OR judge: benign false blocks"], D.ratio(12, 54))
        self.assertEqual(rows["Original heldout cases (HO-*)"]["Rules OR judge: attack recall"], D.ratio(6, 7))
        self.assertEqual([c["Met"] for c in v["checks"]], ["yes", "no", "yes"])
        self.assertEqual((v["judge_misses"], v["judge_false_flags"]),
                         ({"variant": 1, "original": 0}, {"variant": 0, "original": 1}))
        self.assertTrue(D.crosscheck_view({})["dry_run"], "a file that does not say it is a measurement is not shown as one")
        self.assertEqual(D.crosscheck_view({"dry_run": False, "acceptance": {"result": "MAYBE"}})["result"], "n/a")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write(root, "release/benchmarks/crosscheck_live", crosscheck_doc())
            self.write(root, "release/benchmarks/crosscheck_z_dry",
                       {**crosscheck_doc(dry_run=True), "created_utc": "2026-10-19T00:00:00+00:00"})
            self.assertEqual(D.crosscheck_run(root, root / "no_data")["source"],
                             "release/benchmarks/crosscheck_live/results.json", "a live run wins over a newer dry run")
            self.assertIsNone(D.crosscheck_run(root / "nowhere", root / "no_data"))

    def test_crosscheck_view_round_2_side_by_side(self):
        self.assertEqual((D.crosscheck_view(crosscheck_doc())["round"], D.crosscheck_view(crosscheck_doc())["rounds"],
                          D.crosscheck_view(crosscheck_doc())["mcnemar"]), (1, [], []), "a round-1 file shows one round")
        v = D.crosscheck_view(crosscheck_r2_doc())
        self.assertEqual(v["round"], 2)
        r1, r2 = v["rounds"]
        self.assertEqual((r1["Round"], r1["Paraphraser (variants)"], r1["Acceptance"]), ("1", "DeepSeek-V4.1-Flash", "FAIL"))
        self.assertEqual((r1["Rules OR judge: attack recall"], r1["Rules OR judge: benign false blocks"]),
                         (D.ratio(127, 134), D.ratio(26, 45)))
        self.assertEqual(r1["Judge decision"], D.CROSSCHECK_R1_DECISION)
        self.assertEqual((r2["Round"], r2["Paraphraser (variants)"], r2["Prompt sha256"]), ("2", "GLM-5.3-Flash", "e2d46b58dc4d"))
        self.assertEqual(r2["Rules OR judge: attack recall"], D.ratio(141, 150))
        self.assertIn("'supported' is asked and recorded, not a flag", r2["Judge decision"])
        self.assertEqual(len(v["mcnemar"]), 4)
        first = v["mcnemar"][0]
        self.assertEqual((first["Cases"], first["Discordant c (rules OR judge only)"], first["Exact McNemar p"]),
                         ("attack", "17", "1.53e-05"))
        self.assertIn("NOT held out", v["mcnemar"][2]["Set"])
        self.assertIn("Round-1 variants under the round-2 policy (NOT held out; secondary)", {r["Set"] for r in v["rows"]})
        self.assertEqual(set(v["policy_why"]), {"decision", "prompt"})

    def test_validation_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, empty = Path(tmp), Path(tmp) / "no_data"
            for t in ("handoff_day1/ui/test_timeline_storage.py", "handoff_day1/agent/test_episode.py"):
                write_json(root / t, {})   # this checkout's tests (no git here: found by a folder walk)
            self.assertIsNone(D.validation_view(root, empty))
            fail = validation_summary(root, "2026-10-18T02:00:00+00:00", passed=False, sources_unchanged=False)
            write_json(root / "release/validation_abd/late_fail/summary.json", fail)
            v = D.validation_view(root, empty)
            self.assertEqual((v["result"], v["label"]), ("FAIL", "offline validation run release/validation_abd/late_fail"),
                             "only a failed run: shown as FAIL")
            self.assertIn("tracked source files changed while it ran", v["why"])
            write_json(root / "release/validation_abd/early_pass/summary.json",
                       validation_summary(root, "2026-10-18T01:00:00+00:00", passed=True))
            v = D.validation_view(root, empty)
            self.assertEqual((v["result"], v["run_dir"], v["unittest_cases"], v["test_processes"], v["git_head"]),
                             ("PASS", "release/validation_abd/early_pass", 15, 2, None), "a newer FAIL never headlines")
            self.assertEqual(v["not_covered"], ["handoff_day1/ui/test_timeline_storage.py"], "derived from what the run ran")
            write_json(empty / "validation.json", {"frozen": {"source_dir": "release/validation_abd/x", "source_file": "summary.json",
                                                              "source_sha256": "ab" * 32, "git_head": "0123456789abcdef0123",
                                                              "not_covered": ["scripts/test_a.py"]}, "doc": fail})
            v = D.validation_view(root, empty)
            self.assertEqual((v["result"], v["label"], v["not_covered"]),
                             ("FAIL", "offline validation of commit 0123456789ab", ["scripts/test_a.py"]),
                             "the frozen snapshot is what the page shows, and its commit is named because it was recorded")
            self.assertIn("frozen copy of release/validation_abd/x/summary.json, sha256 abababababab", v["source"])
            ran = D.tests_run_by(validation_summary(Path(r"C:\repo"), "t", passed=True))
            self.assertEqual(ran, {"handoff_day1/agent/test_episode.py", "deploy/test_serve.py"})

    def test_test_inventory_under_an_ignored_parent_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            try:
                git = subprocess.run(["git", "init", "--quiet", str(parent)], capture_output=True, timeout=30)
            except FileNotFoundError:
                self.skipTest("git not installed; no parent checkout to reproduce")
            self.assertEqual(git.returncode, 0, git.stderr)
            (parent / ".gitignore").write_text("export/\n", encoding="utf-8")
            root = parent / "export"
            expected = ["handoff_day1/agent/test_episode.py", "handoff_day1/ui/test_timeline_storage.py"]
            for path in expected:
                write_json(root / path, {})
            self.assertEqual(D.repo_tests(str(root)), tuple(expected), "an ancestor's empty git inventory is not this tree")
            self.assertEqual(D.tests_not_run(validation_summary(root, "t", passed=True), root), [expected[1]])

    def test_test_inventory_at_its_own_git_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                git = subprocess.run(["git", "init", "--quiet", str(root)], capture_output=True, timeout=30)
            except FileNotFoundError:
                self.skipTest("git not installed; own-root git inventory unavailable")
            self.assertEqual(git.returncode, 0, git.stderr)
            (root / ".gitignore").write_text("handoff_day1/ui/test_ignored.py\n", encoding="utf-8")
            write_json(root / "handoff_day1/ui/test_real.py", {})
            write_json(root / "handoff_day1/ui/test_ignored.py", {})
            self.assertEqual(D.repo_tests(str(root)), ("handoff_day1/ui/test_real.py",), "own-root git ignore rules still apply")

    def test_test_inventory_without_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in ("handoff_day1/ui/test_real.py", "handoff_day1/ui/.venv/test_dependency.py",
                         "handoff_day1/ui/__pycache__/test_cached.py", "unrelated/test_other.py"):
                write_json(root / path, {})
            with patch.object(D.subprocess, "run", side_effect=FileNotFoundError("no git")):
                self.assertEqual(D.repo_tests(str(root)), ("handoff_day1/ui/test_real.py",))

    def test_unknown_test_inventory_is_not_no_missing_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(D.subprocess, "run", side_effect=FileNotFoundError("no git")), \
                    patch.object(D.os, "walk", side_effect=PermissionError("inventory unreadable")):
                self.assertIsNone(D.repo_tests(str(root)))
                self.assertIsNone(D.tests_not_run(validation_summary(root, "t", passed=True), root))
                write_json(root / "release/validation_abd/run/summary.json", validation_summary(root, "t", passed=True))
                self.assertIsNone(D.validation_view(root, root / "no_data")["not_covered"])
            self.assertIsNone(D.repo_tests(str(root / "missing")))


# ---------------------------------------------------------------- 3. the runtime view's pieces
class FakeQuery(dict):
    def to_dict(self):
        return dict(self)


class TestRuntimeTrace(unittest.TestCase):
    def test_endpoint_status(self):
        self.assertFalse(R.endpoint_status({})["configured"])
        tf = R.endpoint_status({"CARERELAY_LLM_BASE_URL": "https://developer.amd.com.cn/radeon/api/v1",
                                "CARERELAY_LLM_MODEL": "Gemma-4-31B-IT", "CARERELAY_LLM_API_KEY": SECRET})
        self.assertEqual((tf["token_factory"], tf["label"]), (True, "Inference: AMD Token Factory endpoint (AMD Developer Hackathon)"))
        local = R.endpoint_status({"CARERELAY_LLM_BASE_URL": "http://user:pw@127.0.0.1:8011/v1", "CARERELAY_LLM_MODEL": "m"})
        self.assertEqual(local["label"], "Inference endpoint: 127.0.0.1 (not the AMD Token Factory endpoint)")
        self.assertNotIn(SECRET, json.dumps(tf))
        self.assertNotIn("pw", json.dumps(local))

    def test_rows_join_the_checks_and_never_estimate_tokens(self):
        sha = R._sha
        extractor = SimpleNamespace(log=[{"update_id": "u9", "text": "FACTS", "parsed": True},
                                         {"update_id": "u10", "text": "CUT", "parsed": False}])
        answerer = SimpleNamespace(log=[{"text": "A1", "violations": ["unknown id [u99.9]"]}, {"text": "A2", "violations": []}])
        episode = SimpleNamespace(entries=[{"seq": 3, "update_id": "u9", "facts": [{}], "rejected": [
            {"reason": "the quote is not in the update"}, {"reason": R.HELD_REASON}]}])
        checks = R.output_checks({"extractor": extractor, "answerer": answerer, "episode": episode})
        self.assertEqual(checks[sha("FACTS")], "1 fact kept, 1 rejected by the grounding check, 1 held by the evidence verifier")
        self.assertEqual(checks[sha("CUT")], "reply could not be read: no facts were taken from it")
        self.assertTrue(checks[sha("A1")].startswith("rejected by the answer check (1 reason)"))
        self.assertEqual(checks[sha("A2")], "passed the answer check")
        calls = [{"seq": 1, "ok": True, "schema": "facts", "model": "m", "host": "developer.amd.com.cn", "latency_s": 2.5,
                  "wait_s": 2.0, "prompt_tokens": None, "completion_tokens": None, "output_sha256": sha("FACTS"), "utc": "2026-10-17T12:00:01+00:00"},
                 {"seq": 2, "ok": True, "images": 1, "model": "v", "host": "h", "latency_s": 1.0, "prompt_tokens": 9, "completion_tokens": 3},
                 {"seq": 3, "ok": False, "schema": "episode_answer", "error": "HTTP 429", "elapsed_s": 0.4}]
        rows = R.call_rows(calls, checks)
        self.assertEqual([r["#"] for r in rows], ["3", "2", "1"])
        first = rows[2]
        self.assertEqual((first["Prompt tokens"], first["Completion tokens"]), ("n/a", "n/a"))
        self.assertEqual(first["Latency"], "2.50 s (+2.0 s retry wait)")
        self.assertEqual(first["Endpoint host"], "developer.amd.com.cn (AMD Token Factory)")
        self.assertEqual(first["Output check"], checks[sha("FACTS")])
        self.assertEqual(rows[1]["Output check"], R.PHOTO_CHECK)
        self.assertEqual((rows[0]["Result"], rows[0]["Output check"]), ("error: HTTP 429", "no reply"))
        s = R.summary(calls)
        self.assertEqual((s["calls"], s["ok"], s["with_usage"], s["prompt_tokens"], s["median_latency_s"]), (3, 2, 1, 9, 1.75))

    def test_family_params_come_back_after_another_page(self):
        st = SimpleNamespace(session_state={}, query_params=FakeQuery(family="abc", **{"as": "mia"}))
        R.remember_page(st, True)
        st.query_params = FakeQuery()                     # navigating cleared the address
        R.remember_page(st, False)
        R.restore_family_params(st, True)
        self.assertEqual(st.query_params, {"family": "abc", "as": "mia"})
        st.query_params = FakeQuery()                     # left the space on the family page itself: nothing comes back
        R.remember_page(st, True)
        R.remember_page(st, False)
        R.restore_family_params(st, True)
        self.assertEqual(st.query_params, {})


# ---------------------------------------------------------------- 4. the pages, headless
class TestShellPages(unittest.TestCase):
    def setUp(self):
        no_live_model()

    def test_family_timeline_is_the_default_page(self):
        at = shell()
        self.assertTrue(any("Viewing as" == s.label for s in at.selectbox), "the family timeline's own controls")
        self.assertIn("AMD Runtime · 0 model calls", sidebar_text(at))
        self.assertIn("No live model is configured", sidebar_text(at))

    def test_scorecard(self):
        at = shell()
        at.switch_page("scorecard.py").run()
        self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])
        text = visible_text(at)
        for needle in ("0.975 ± 0.011", "0.903 ± 0.025", "DEV_README_EXCERPT.md:16", "430/430", "247/253", "233/235", "0.9800",
                       "29/1648", "0.961569", "0 of 4,048", "FAILED", "KINDRED_VERIFIER_MODE=off", "Fail-closed",
                       "10/80 (12.50%", "11/80 (13.75%", "13/80 (16.25%", "73/315", "57/117", "73/150",
                       "No overall advantage", "[-16.25 pp, +10.00 pp]", "556 cases",
                       "research/temporal_benchmark/results/round3_heldout_20261017.json",
                       "release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md:39", D.ref(D.VERIFIER["release_mode"]), "deploy/serve.py:42"):
            self.assertIn(needle, text)
        v = D.validation_view()
        if v is None:
            self.assertIn(f"no {D.DATA_REL}/{D.FROZEN_VALIDATION} and no file matching {D.VALIDATION_GLOB}", text)
        else:
            self.assertIn(f"RESULT {v['result']}, {v['unittest_cases']} unittest cases", text)
            self.assertIn(v["label"][1:], text)
            if v["not_covered"] is not None:
                self.assertIn(", ".join(v["not_covered"]), text)
        if not D.tf_bench_runs():
            self.assertIn(f"Not yet run: no frozen snapshot {D.DATA_REL}/{D.FROZEN_TF_BENCH} and no results file matching "
                          f"{D.TF_BENCH_GLOB}", text)
        if D.redteam_run() is None:
            self.assertIn(f"Not yet run: no frozen snapshot {D.DATA_REL}/{D.FROZEN_REDTEAM} and no results file matching "
                          f"{D.REDTEAM_GLOB}", text)
        self.assertIn("Cross-model semantic check (shadow)", text)
        cc = D.crosscheck_run()
        if cc is None:
            self.assertIn(f"Not yet run: no frozen snapshot {D.DATA_REL}/{D.FROZEN_CROSSCHECK} and no results file "
                          f"matching {D.CROSSCHECK_GLOB}", text)
        elif D.crosscheck_view(cc["doc"])["dry_run"]:
            self.assertIn("DRY RUN: a scripted stand-in answered as judge and paraphraser", text)
            self.assertNotIn("Acceptance against the preregistered rule", text)
        else:
            self.assertIn(f"Acceptance against the preregistered rule: {D.crosscheck_view(cc['doc'])['result']}", text)
            self.assertIn("Preregistered acceptance rule:", text)

    def test_scorecard_reads_the_frozen_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            frozen_file(data / "tf_bench_main.json", tf_doc("2026-10-17T12:40:40+00:00", {}, {
                "Gemma-4-31B-IT": (35, 36, 36, {"timeout": 1}), "Qwen3.8-27B": (24, 36, 36, {"truncated": 12})}), "Main run")
            frozen_file(data / "tf_bench_qwen_off.json", tf_doc("2026-10-18T02:00:00+00:00",
                        {"chat_template_kwargs": {"enable_thinking": False}}, {"Qwen3.8-27B": (36, 36, 36, {})}))
            frozen_file(data / "tf_bench_dry.json", tf_doc("2026-10-18T03:00:00+00:00", {}, {"A": (2, 2, 2, {})}, dry_run=True))
            now, before = redteam_pair()
            frozen_file(data / "redteam.json", now, before=before)
            frozen_file(data / "validation.json", validation_summary(D.REPO, "2026-10-18T04:00:00+00:00", passed=False,
                                                                    sources_unchanged=False))
            frozen_file(data / "crosscheck.json", crosscheck_doc())
            with patch.object(D, "DATA", data):
                at = shell()
                at.switch_page("scorecard.py").run()
                self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])
                text = visible_text(at)
        for needle in ("Main run", 'extra_body {"chat_template_kwargs": {"enable_thinking": false}}', "DRY RUN, run of",
                       "35/36 (Wilson 95% [85.8%, 99.5%])", "24/36 (Wilson 95% [", "timeout 1", "truncated 12",
                       "36/36, 0 aborted", "Facts passing grounding check", "20/22",
                       "Qwen3.8-27B: 12 of 36 completed handovers hit max_tokens=2000 (the reply was cut off and counts as "
                       "a failure); thinking/extra_body = {} (none sent: the endpoint's default).",
                       "includes network and prompt processing; not a decode speed", "Run complete (not stopped early).",
                       "tf_bench_main.json (frozen copy of release/benchmarks/tf_bench_main/results.json, sha256 cdcdcdcdcdcd)",
                       "Offline validation (deploy/validate_abd.py): FAIL", "RESULT FAIL, 15 unittest cases in 2 processes",
                       "tracked source files changed while it ran",
                       "Before and after", "3/8 (37.50%", "6/8 (75.00%",
                       "Gaps closed since the earlier run: on the Case Agent / instruction extractor path: MD-06 (case_agent_answer), "
                       "PQ-03 (extract_instructions).",
                       "Still open on the deployed family timeline path: DX-05 (episode_update), PI-04 (episode_update).",
                       "the Case Agent (case_agent.py) is not on its path",
                       "Cross-model semantic check (shadow)", "Preregistered acceptance rule:",
                       "Acceptance against the preregistered rule: FAIL (stays shadow-only).",
                       "Judge Gemma-4-31B-IT: inference via the AMD Token Factory endpoint provided for the AMD Developer "
                       "Hackathon.", D.ratio(141, 150), D.ratio(6, 7), "judge call p50 12.30 s, p95 40.10 s",
                       "tokens per check 1500", "crosscheck.json (frozen copy of release/benchmarks/crosscheck/results.json",
                       "Variants are model-generated paraphrases; not human-verified.", "not on the product path"):
            self.assertIn(needle, text)
        self.assertNotIn("Citation validity", text)
        self.assertNotIn("Not yet run", text)
        self.assertLess(text.index("Main run"), text.index("DRY RUN, run of"), "live runs before dry runs")

    def test_scorecard_never_shows_a_dry_crosscheck_as_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            frozen_file(data / "crosscheck.json", crosscheck_doc(dry_run=True, result="PASS"))
            with patch.object(D, "DATA", data):
                at = shell()
                at.switch_page("scorecard.py").run()
                self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])
                text = visible_text(at)
        self.assertIn("Cross-model semantic check (shadow)", text)
        self.assertIn("DRY RUN: a scripted stand-in answered as judge and paraphraser", text)
        self.assertIn("Dry-run harness numbers (not measurements)", text)
        for shown_only_when_measured in ("Acceptance against the preregistered rule", "Preregistered acceptance rule:",
                                         "Judge Gemma-4-31B-IT: inference via"):
            self.assertNotIn(shown_only_when_measured, text)

    def test_scorecard_shows_round_1_and_round_2_side_by_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            frozen_file(data / "crosscheck.json", crosscheck_r2_doc())
            with patch.object(D, "DATA", data):
                at = shell()
                at.switch_page("scorecard.py").run()
                self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])
                text = visible_text(at)
        for needle in ("Round 1 and round 2 side by side", "Policy difference: round 1 flags not supported OR",
                       "round 2 flags autonomous_diagnosis OR dose_mismatch OR instruction_override",
                       "Acceptance against the preregistered rule: FAIL (stays shadow-only). Round 2",
                       "DeepSeek-V4.1-Flash", "GLM-5.3-Flash", D.ratio(127, 134), D.ratio(26, 45), D.ratio(141, 150),
                       "Secondary, preregistered:", "paired exact McNemar test", "1.53e-05", "0.0039",
                       "Round-1 variants under the round-2 policy (NOT held out; secondary)",
                       "Why (decision): 17 of 22 benign flags came from 'supported' alone.",
                       "'supported' is recorded but is not a flag in round 2",
                       "Secondary set (round-1 variants): 71 of 71 judged."):
            self.assertIn(needle, text)

    def test_runtime_page_without_calls(self):
        at = shell()
        at.switch_page("amd_runtime.py").run()
        self.assertFalse(at.exception)
        self.assertIn("No model call yet in this browser session", visible_text(at))
        self.assertEqual([e.label for e in at.sidebar.expander if e.label.startswith("AMD Runtime")], [],
                         "no duplicate panel on the runtime page itself")

    def test_back_to_the_family_timeline(self):
        at = shell()
        at.switch_page("scorecard.py").run()
        at.switch_page("../1_Family_timeline.py").run()
        self.assertFalse(at.exception)
        self.assertTrue(any("Viewing as" == s.label for s in at.selectbox))

    def test_saved_timelines_go_to_a_temporary_store_not_the_home_store(self):
        state = os.environ.get("CARERELAY_STATE_DIR")
        self.assertTrue(state, "the family timeline must not fall back to the developer's ~/.kindredrelay store")
        self.assertNotEqual(Path(state).resolve(), (Path.home() / ".kindredrelay").resolve())
        path = shell().session_state["persistent_private"].store.path
        self.assertTrue(path.is_relative_to(Path(state).resolve()), path)
        self.assertTrue(path.is_file())


# ---------------------------------------------------------------- 5. live calls through the shell (scripted stand-in)
class TestLiveCallsThroughTheShell(unittest.TestCase):
    def tearDown(self):
        no_live_model()

    def live(self, mode: str) -> AppTest:
        no_live_model()
        at = shell()
        for _ in range(7):                                # the demo story, replayed (no model call)
            next(b for b in at.button if b.label == "Add this update").click().run()
            self.assertFalse(at.exception)
        os.environ.update(CARERELAY_LLM_BASE_URL=start_fake_llm(mode), CARERELAY_LLM_MODEL=f"fake-carerelay-{mode}",
                          CARERELAY_LLM_API_KEY=SECRET)
        at.run()
        return at

    def ask(self, at: AppTest, question: str) -> None:
        at.button(key="add_ask").click().run()
        at.text_input(key="qa_text").set_value(question).run()
        next(b for b in at.button if b.label == "Find out").click().run()
        self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])

    def calls(self, at: AppTest) -> list:
        return at.session_state[R.RECORDER_KEY].calls()

    def test_recording_and_question_are_listed_with_their_checks(self):
        at = self.live("good")
        at.session_state["rec_speaker_type"] = "Doctor / nurse"   # a typed recording of what the nurse said
        at.session_state["rec_speaker"] = "Ward nurse"
        at.button(key="add_recording").click().run()
        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
        at.text_area(key="rec_text").set_value("Keep her nil by mouth from midnight tonight please.").run()
        at.button(key="rec_add").click().run()
        self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])
        [facts_call] = self.calls(at)
        self.assertEqual((facts_call["schema"], facts_call["host"], facts_call["model"], facts_call["ok"]),
                         ("facts", "127.0.0.1", "fake-carerelay-good", True))
        self.assertIsInstance(facts_call["prompt_tokens"], int)
        self.assertIsInstance(facts_call["completion_tokens"], int)
        self.assertEqual(facts_call["output_sha256"], R._sha(at.session_state["extractor"].log[-1]["text"]))
        entry = at.session_state["episode"].entries[-1]
        self.assertIn("AMD Runtime · 1 model call", sidebar_text(at))
        self.assertIn("Inference endpoint: 127.0.0.1 (not the AMD Token Factory endpoint)", sidebar_text(at))

        at = reload_view(at)
        self.ask(at, "When is she going home?")
        qa = self.calls(at)[-1]
        self.assertEqual((qa["schema"], qa["ok"]), ("episode_answer", True))
        log = at.session_state["answerer"].log[-1]
        self.assertEqual(qa["output_sha256"], R._sha(log["text"]))

        at.switch_page("amd_runtime.py").run()
        self.assertFalse(at.exception)
        text = visible_text(at)
        verdict_qa = "passed the answer check" if not log["violations"] else "rejected by the answer check"
        n_kept, n_rejected = len(entry["facts"]), len(entry["rejected"])
        verdict_facts = f"{n_kept} fact{'' if n_kept == 1 else 's'} kept, {n_rejected} rejected by the grounding check"
        for needle in ("Question answer (sentence choice)", "Fact extraction", "fake-carerelay-good", "127.0.0.1",
                       verdict_qa, verdict_facts, "Model calls this session: 2"):
            self.assertIn(needle, text)
        everything = text + json.dumps(self.calls(at)) + sidebar_text(at)
        for private in (SECRET, "nil by mouth", "When is she going home"):
            self.assertNotIn(private, everything)

    def test_rejected_answers_are_said(self):
        at = self.live("bad")                             # first reply cites an id that does not exist, the retry says "no"
        self.ask(at, "When is she going home?")
        rows = self.calls(at)
        self.assertEqual([r["schema"] for r in rows], ["episode_answer", "episode_answer"])
        at.switch_page("amd_runtime.py").run()
        self.assertEqual(visible_text(at).count("rejected by the answer check"), 2)


# ---------------------------------------------------------------- 6. the AMD Runtime session summary
TF = R.TOKEN_FACTORY_HOST


def session_calls() -> list:
    """Recorder rows as llm_client's OpenAIChat._trace writes them (no network): two stages of one text model and a photo
    read on the AMD Token Factory endpoint, one failed call to another host."""
    return [{"utc": "2026-10-18T01:00:01+00:00", "model": "DeepSeek-V4-Flash", "host": TF, "schema": "facts", "images": 0,
             "ok": True, "latency_s": 6.0, "prompt_tokens": 1000, "completion_tokens": 170, "output_sha256": "a"},
            {"utc": "2026-10-18T01:00:09+00:00", "model": "DeepSeek-V4-Flash", "host": TF, "schema": "episode_answer",
             "images": 0, "ok": True, "latency_s": 2.0, "prompt_tokens": None, "completion_tokens": None},
            {"utc": "2026-10-18T01:00:20+00:00", "model": "Gemma-4-31B-IT", "host": TF, "schema": None, "images": 1,
             "ok": True, "latency_s": 9.0, "prompt_tokens": 800, "completion_tokens": 200},
            {"utc": "2026-10-18T01:00:30+00:00", "model": "local-model", "host": "127.0.0.1", "schema": "facts", "images": 0,
             "ok": False, "error": "HTTP 500", "elapsed_s": 0.3}]


class TestRuntimeSessionSummary(unittest.TestCase):
    def tearDown(self):
        no_live_model()

    def test_summary_by_endpoint_and_model_never_estimates_tokens(self):
        s = R.session_summary(session_calls())
        self.assertEqual((s["calls"], s["amd_calls"], s["other_calls"], s["other_hosts"], s["amd_share"]),
                         (4, 3, 1, ["127.0.0.1"], 0.75))
        self.assertEqual((s["with_usage"], s["prompt_tokens"], s["completion_tokens"], s["median_latency_s"]), (2, 1800, 370, 6.0))
        self.assertEqual(R.endpoint_share(s), f"3 of 4 calls (75%) went to the AMD Token Factory endpoint ({TF}); 1 to other "
                                              "hosts: 127.0.0.1.")
        self.assertEqual([(m["model"], m["roles"]) for m in s["per_model"]],
                         [("DeepSeek-V4-Flash", ["Fact extraction", "Question answer (sentence choice)"]),
                          ("Gemma-4-31B-IT", ["Photo reading"]), ("local-model", ["Fact extraction"])],
                         "roles are the stages of each model's own calls, in first-call order")
        deepseek, gemma, local = R.model_rows(s)
        self.assertEqual((deepseek["Calls"], deepseek["p50 latency"], deepseek["Endpoint host"]),
                         ("2", "4.00 s", f"{TF} (AMD Token Factory)"))
        self.assertEqual(deepseek["Tokens (prompt / completion)"], "1000 / 170 (usage on 1 of 2 answered calls)")
        self.assertEqual(gemma["Tokens (prompt / completion)"], "800 / 200")
        self.assertEqual((local["Answered"], local["p50 latency"], local["Tokens (prompt / completion)"], local["Endpoint host"]),
                         ("0", "n/a", "n/a", "127.0.0.1"))
        none = R.session_summary(session_calls()[3:])
        self.assertEqual(R.endpoint_share(none), f"No call went to the AMD Token Factory endpoint ({TF}): 1 call to 127.0.0.1.")
        self.assertEqual(R.endpoint_share(R.session_summary([])), "No model call yet in this session.")
        self.assertIsNone(R.session_summary([])["amd_share"])

    def test_configured_models_without_calls_get_a_configured_role(self):
        status = R.endpoint_status({"CARERELAY_LLM_BASE_URL": f"https://{TF}/radeon/api/v1", "CARERELAY_LLM_MODEL": "Text-M",
                                    "CARERELAY_PHOTO_MODEL": "Vision-M"})
        self.assertEqual(R.configured_roles(status, R.session_summary([])),
                         ["Text-M: fact extraction, question answers (configured role; not called yet this session)",
                          "Vision-M: photo reading (configured role; not called yet this session)"])
        called = R.session_summary([{"model": "Vision-M", "host": TF, "images": 1, "ok": True, "latency_s": 1.0}])
        self.assertEqual(R.configured_roles(status, called),
                         ["Text-M: fact extraction, question answers (configured role; not called yet this session)"])
        same = R.endpoint_status({"CARERELAY_LLM_BASE_URL": "http://127.0.0.1:8011/v1", "CARERELAY_LLM_MODEL": "Text-M"})
        self.assertEqual(R.configured_roles(same, R.session_summary([])),
                         ["Text-M: fact extraction, question answers, photo reading (configured role; not called yet this "
                          "session)"], "without CARERELAY_PHOTO_MODEL the text model reads photos (make_photo_client)")

    def test_page_and_sidebar_show_the_summary(self):
        no_live_model()
        at = shell()
        rec = CallRecorder(R.MAX_CALLS)
        for row in session_calls():
            rec.record(row)
        at.session_state[R.RECORDER_KEY] = rec
        at.run()                                          # the family timeline: the sidebar panel
        self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])
        side = sidebar_text(at)
        for needle in ("AMD Runtime · 4 model calls",
                       f"3 of 4 calls (75%) went to the AMD Token Factory endpoint ({TF}); 1 to other hosts: 127.0.0.1.",
                       "Tokens (prompt / completion) 1800 / 370 (usage on 2 of 3 answered calls) · p50 latency 6.00 s",
                       "DeepSeek-V4-Flash: Fact extraction, Question answer (sentence choice) · 2 calls",
                       "Gemma-4-31B-IT: Photo reading · 1 call", "local-model: Fact extraction · 1 call"):
            self.assertIn(needle, side)
        os.environ.update(CARERELAY_LLM_BASE_URL=f"https://{TF}/radeon/api/v1", CARERELAY_LLM_MODEL="DeepSeek-V4-Flash",
                          CARERELAY_PHOTO_MODEL="Gemma-4-31B-IT", CARERELAY_LLM_API_KEY=SECRET)
        at.switch_page("amd_runtime.py").run()            # makes no model call: it reads the recorder
        self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])
        self.assertEqual(rec.total, 4)
        text = visible_text(at)
        for needle in ("This session", "Model calls this session: 4", "To the AMD Token Factory endpoint: 3 of 4 (75%)",
                       "Median latency (p50): 6.00 s", "Tokens (prompt / completion): 1800 / 370",
                       f"3 of 4 calls (75%) went to the AMD Token Factory endpoint ({TF}); 1 to other hosts: 127.0.0.1.",
                       "| DeepSeek-V4-Flash | Fact extraction, Question answer (sentence choice) | 2 | 2 | "
                       f"{TF} (AMD Token Factory) | 4.00 s | 1000 / 170 (usage on 1 of 2 answered calls) |",
                       f"| Gemma-4-31B-IT | Photo reading | 1 | 1 | {TF} (AMD Token Factory) | 9.00 s | 800 / 200 |",
                       "| local-model | Fact extraction | 1 | 0 | 127.0.0.1 | n/a | n/a |",
                       R.TOKEN_FACTORY_LABEL, "Each call, newest first"):
            self.assertIn(needle, text)
        self.assertNotIn("Configured, no call yet", text, "both configured models were called")
        self.assertEqual([h.value for h in at.subheader], ["This session", "Each call, newest first"],
                         "the summary is above the call list")
        self.assertNotIn(SECRET, text + json.dumps(rec.calls()))

    def test_live_calls_to_another_host_are_counted_as_not_amd(self):
        no_live_model()
        at = shell()
        for _ in range(7):                                # the demo story, replayed (no model call)
            next(b for b in at.button if b.label == "Add this update").click().run()
        os.environ.update(CARERELAY_LLM_BASE_URL=start_fake_llm("good"), CARERELAY_LLM_MODEL="fake-carerelay-good",
                          CARERELAY_LLM_API_KEY=SECRET)
        at.run()
        at.session_state["rec_speaker_type"] = "Doctor / nurse"   # a typed recording, as in the live test above
        at.session_state["rec_speaker"] = "Ward nurse"
        at.button(key="add_recording").click().run()
        at.text_input(key="rec_speaker").set_value("Ward nurse").run()
        at.text_area(key="rec_text").set_value("Keep her nil by mouth from midnight tonight please.").run()
        at.button(key="rec_add").click().run()
        at = reload_view(at)
        at.button(key="add_ask").click().run()
        at.text_input(key="qa_text").set_value("When is she going home?").run()
        next(b for b in at.button if b.label == "Find out").click().run()
        self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])
        calls = at.session_state[R.RECORDER_KEY].calls()
        self.assertEqual([(c["schema"], c["host"], c["ok"]) for c in calls],
                         [("facts", "127.0.0.1", True), ("episode_answer", "127.0.0.1", True)])
        share = f"No call went to the AMD Token Factory endpoint ({TF}): 2 calls to 127.0.0.1."
        role = "fake-carerelay-good: Fact extraction, Question answer (sentence choice) · 2 calls"
        at.run()
        self.assertIn(share, sidebar_text(at))
        self.assertIn(role, sidebar_text(at))
        at.switch_page("amd_runtime.py").run()
        self.assertFalse(at.exception, [str(e.value)[:400] for e in at.exception])
        text = visible_text(at)
        tokens = f"{sum(c['prompt_tokens'] for c in calls)} / {sum(c['completion_tokens'] for c in calls)}"
        for needle in (share, "To the AMD Token Factory endpoint: 0 of 2 (0%)", f"Tokens (prompt / completion): {tokens}",
                       "| fake-carerelay-good | Fact extraction, Question answer (sentence choice) | 2 | 2 | 127.0.0.1 |"):
            self.assertIn(needle, text)
        self.assertNotIn(R.TOKEN_FACTORY_LABEL, text, "the Token Factory label only for its host")
        self.assertNotIn("(AMD Token Factory)", text)
        for private in (SECRET, "nil by mouth", "When is she going home"):
            self.assertNotIn(private, text + sidebar_text(at))


if __name__ == "__main__":
    # Keep workstation credentials (e.g. a repo-root .streamlit/secrets.toml) out of every AppTest run.
    with patch_config_options({"secrets.files": []}):
        unittest.main(verbosity=2)
