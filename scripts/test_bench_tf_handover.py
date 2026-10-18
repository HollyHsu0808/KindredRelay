"""Offline tests of scripts/bench_tf_handover.py; every endpoint is a FakeTransport, nothing touches the network.

.venv/Scripts/python.exe scripts/test_bench_tf_handover.py
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_tf_handover as B  # noqa: E402

SENTINEL = "sk-SENTINEL-7f3a9c1e5b2d4f60a8e1"   # never a real key
ENV_PREFIXES = ("CARERELAY_LLM_", "CARERELAY_PHOTO_", "KINDRED_VERIFIER_", "CARERELAY_STORY")


class Base(unittest.TestCase):
    """A clean environment (no live endpoint, verifier off) and a temporary folder per test."""

    def setUp(self):
        self._env = patch.dict(os.environ)
        self._env.start()
        for k in [k for k in os.environ if k.startswith(ENV_PREFIXES)]:
            del os.environ[k]
        self.tmp = Path(tempfile.mkdtemp(prefix="bench_tf_test_"))
        self.sleeps: list[float] = []

    def tearDown(self):
        self._env.stop()

    def run_main(self, argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        kw.setdefault("sleep", self.sleeps.append)
        with redirect_stdout(out), redirect_stderr(err):
            code = B.main(argv, **kw)
        return code, out.getvalue(), err.getvalue()

    def dry(self, name, *extra, **kw):
        out = self.tmp / name
        code, so, se = self.run_main(["--dry-run", "--models", "A,B", "--cases", "5", "--out", str(out), *extra], **kw)
        return out, code, so, se

    @staticmethod
    def records(out: Path):
        return [json.loads(x) for x in (out / "records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

    @staticmethod
    def results(out: Path):
        return json.loads((out / "results.json").read_text(encoding="utf-8"))


class DryRun(Base):
    def test_dry_run_end_to_end_writes_valid_outputs(self):
        out, code, so, se = self.dry("run")
        self.assertEqual(code, B.EXIT_OK, se)
        for name in ("records.jsonl", "results.json", "summary.md", "latency.svg"):
            self.assertTrue((out / name).is_file(), name)
        recs = self.records(out)
        for r in recs:
            self.assertEqual(B.validate_record(r), [], r)
        res = self.results(out)
        self.assertEqual(B.validate_results(res), [])
        self.assertEqual(res["models"], ["A", "B"])
        self.assertEqual(res["case_ids"], [f"episode_hip_fracture/u0{i}" for i in range(1, 6)])
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["endpoint"]["host"], "developer.amd.com.cn")
        self.assertIn("head", res["git"])
        self.assertIsInstance(res["git"]["dirty"], (bool, type(None)))
        for m in ("A", "B"):
            s = res["per_model"][m]
            self.assertEqual((s["n_planned"], s["n_completed"], s["success"]["count"]), (5, 5, 5))
            self.assertEqual(s["citation_validity"]["rate"], 1.0)   # the fake returns the story's recorded facts
            self.assertGreater(s["citation_validity"]["proposed"], 0)
            self.assertEqual(s["gate"]["decisions"], {"off": 5})
            self.assertIsNotNone(s["e2e_latency_s"]["p50"])
            self.assertIsNotNone(s["e2e_latency_s"]["p50_ci95"])
            self.assertIsNotNone(s["tokens_per_handover"]["mean"])
        cases = [r for r in recs if r["type"] == "case"]
        self.assertEqual(len(cases), 10)
        self.assertEqual([c["model"] for c in cases[:4]], ["A", "B", "A", "B"])   # interleaved across models
        self.assertTrue(all(c["json_mode"] == "prompted_json" for c in cases))   # release.env.example GUIDED_JSON=0
        md = (out / "summary.md").read_text(encoding="utf-8")
        self.assertIn("DRY RUN", md)
        self.assertNotIn("MI300", md)
        self.assertNotIn("Wording for the write-up", md)   # no claim from a dry run
        root = ET.fromstring((out / "latency.svg").read_text(encoding="utf-8"))
        self.assertTrue(root.tag.endswith("svg"))

    def test_entry_point_is_the_release_page_path(self):
        page = (B.ROOT / "handoff_day1/ui/pages/1_Family_timeline.py").read_text(encoding="utf-8")
        self.assertIn(f"llm_extractor(make_client(max_tokens={B.PAGE_MAX_TOKENS}))", page)
        self.assertIn("evidence_checker=checker_from_env()", page)
        # serve.py starts the app shell, whose default page is the family timeline
        self.assertIn("shell/kindred_app.py", (B.ROOT / "deploy/serve.py").read_text(encoding="utf-8"))
        shell = (B.ROOT / "handoff_day1/ui/pages/shell/kindred_app.py").read_text(encoding="utf-8")
        self.assertIn("1_Family_timeline.py", shell)

    def test_release_defaults_and_wording(self):
        d = B.release_defaults()
        self.assertEqual(d["CARERELAY_LLM_BASE_URL"], B.FALLBACK_BASE_URL)
        self.assertEqual(d["CARERELAY_LLM_MODEL"], B.FALLBACK_MODEL)
        self.assertNotIn("CARERELAY_LLM_API_KEY", d)
        live = B.endpoint_wording("developer.amd.com.cn", dry_run=False)
        self.assertIn("Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon", live)
        for gpu in ("MI300", "MI325", "Instinct"):
            self.assertNotIn(gpu, live)
        self.assertIn("not the AMD Token Factory", B.endpoint_wording("127.0.0.1:8000", dry_run=False))

    def test_list_models_prints_ids_only(self):
        code, so, se = self.run_main(["--dry-run", "--list-models", "--models", "A,B"])
        self.assertEqual(code, B.EXIT_OK, se)
        self.assertEqual(so.splitlines(), ["A", "B"])

    def test_ttft_probe_and_unsupported_streaming(self):
        out, code, so, se = self.dry("ttft", "--ttft-probe", "2")
        self.assertEqual(code, B.EXIT_OK, se)
        probes = [r for r in self.records(out) if r["type"] == "ttft"]
        self.assertEqual(len(probes), 4)
        self.assertTrue(all(p["stream_supported"] is True and p["ttft_s"] is not None for p in probes))
        self.assertIsNotNone(self.results(out)["per_model"]["A"]["ttft_s"]["p50"])
        fake = B.FakeTransport(["A", "B"], stream_supported=False)
        out2, code, so, se = self.dry("ttft_nostream", "--ttft-probe", "1", transport=fake)
        self.assertEqual(code, B.EXIT_OK, se)
        res = self.results(out2)
        self.assertIs(res["per_model"]["A"]["ttft_s"]["stream_supported"], False)
        self.assertIsNone(res["per_model"]["A"]["ttft_s"]["p50"])
        self.assertEqual(res["per_model"]["A"]["success"]["count"], 5)   # the probe never fails the run


class Statistics(unittest.TestCase):
    def test_percentile_matches_linear_interpolation(self):
        self.assertEqual(B.percentile([1, 2, 3, 4], 50), 2.5)
        self.assertAlmostEqual(B.percentile([1, 2, 3, 4], 95), 3.85)
        self.assertEqual(B.percentile([7.0], 95), 7.0)
        self.assertIsNone(B.percentile([], 50))
        self.assertEqual(B.percentile([3, 1, 2], 0), 1)
        self.assertEqual(B.percentile([3, 1, 2], 100), 3)
        xs = [0.3, 9.1, 2.2, 4.4, 4.4, 7.5, 1.0, 5.25, 8.0, 6.6, 3.3]
        cuts = statistics.quantiles(xs, n=20, method="inclusive")   # cut k is the 5k-th percentile
        for k, cut in enumerate(cuts, 1):
            self.assertAlmostEqual(B.percentile(xs, 5 * k), cut, places=9)

    def test_bootstrap_is_deterministic_and_bounded(self):
        xs = [1.0, 1.2, 1.4, 1.5, 1.7, 2.0, 2.4, 3.1]
        a = B.bootstrap_ci(xs, B.median, key="k")
        self.assertEqual(a, B.bootstrap_ci(xs, B.median, key="k"))   # fixed seed
        self.assertNotEqual(a, B.bootstrap_ci(xs, B.median, key="other", resamples=50))
        self.assertLessEqual(a[0], B.median(xs))
        self.assertGreaterEqual(a[1], B.median(xs))
        self.assertGreaterEqual(a[0], min(xs))
        self.assertLessEqual(a[1], max(xs))
        self.assertIsNone(B.bootstrap_ci(xs[:4], B.median, key="k"))   # below min_n
        self.assertEqual(B.bootstrap_ci([2.0] * 6, B.median, key="k"), [2.0, 2.0])
        self.assertEqual(B.bootstrap_ci([1.0] * 6, B.mean, key="rate"), [1.0, 1.0])
        lo, hi = B.bootstrap_ci([1.0, 0.0] * 10, B.mean, key="half")
        self.assertTrue(lo < 0.5 < hi)
        pairs = [(1, 2), (0, 0), (3, 3), (2, 4), (0, 1)]
        self.assertAlmostEqual(B.pooled(pairs), 6 / 10)
        ci = B.bootstrap_ci(pairs, B.pooled, key="pooled")
        self.assertTrue(0 <= ci[0] <= ci[1] <= 1)

    def test_wilson(self):
        lo, hi = B.wilson95(5, 5)
        self.assertAlmostEqual(lo, 0.5655, places=3)
        self.assertEqual(hi, 1.0)
        self.assertIsNone(B.wilson95(0, 0))


class Refusals(Base):
    def test_out_exists_is_refused(self):
        out = self.tmp / "exists"
        out.mkdir()
        code, so, se = self.run_main(["--dry-run", "--models", "A", "--cases", "1", "--out", str(out)])
        self.assertEqual(code, B.EXIT_USAGE)
        self.assertIn("already exists", se)
        self.assertEqual(list(out.iterdir()), [])
        f = self.tmp / "a_file"
        f.write_text("x", encoding="utf-8")
        code, _, _ = self.run_main(["--dry-run", "--models", "A", "--cases", "1", "--out", str(f)])
        self.assertEqual(code, B.EXIT_USAGE)
        self.assertEqual(f.read_text(encoding="utf-8"), "x")
        code, _, se = self.run_main(["--dry-run", "--out", str(self.tmp / "n1"), "--resume", str(out)])
        self.assertEqual(code, B.EXIT_USAGE)

    def test_live_run_without_key_is_refused_before_any_call(self):
        out = self.tmp / "live"
        code, so, se = self.run_main(["--models", "A", "--cases", "1", "--out", str(out)], env={})
        self.assertEqual(code, B.EXIT_USAGE)
        self.assertIn("no API key", se)
        self.assertFalse(out.exists())

    def test_too_many_cases_is_refused(self):
        code, _, se = self.run_main(["--dry-run", "--models", "A", "--cases", "99", "--out", str(self.tmp / "x")])
        self.assertEqual(code, B.EXIT_USAGE)
        self.assertFalse((self.tmp / "x").exists())


class Secrets(Base):
    def key_file(self, text=SENTINEL):
        p = self.tmp / "key.txt"
        p.write_text(text, encoding="utf-8")
        return p

    def assert_clean(self, text, where):
        self.assertNotIn(SENTINEL, text, where)
        for i in range(len(SENTINEL) - 7):
            self.assertNotIn(SENTINEL[i:i + 8], text, f"{where}: 8-character piece {i} of the key")

    def test_key_never_in_outputs_or_exception_text(self):
        # model B is refused with a 401 whose body repeats the Authorization header, as some gateways do
        fake = B.FakeTransport(["A", "B"], require_key=SENTINEL, echo_auth_on_401=True, fail_models={"B"})
        out = self.tmp / "secret"
        code, so, se = self.run_main(["--dry-run", "--models", "A,B", "--cases", "2", "--ttft-probe", "1",
                                      "--api-key-file", str(self.key_file()), "--out", str(out)], transport=fake)
        self.assertEqual(code, B.EXIT_OK, se)
        self.assertGreater(fake.calls, 0)
        self.assert_clean(so, "stdout")
        self.assert_clean(se, "stderr")
        for p in out.iterdir():
            self.assert_clean(p.read_text(encoding="utf-8"), p.name)
        cases = [r for r in self.records(out) if r["type"] == "case"]
        a = [c for c in cases if c["model"] == "A"]
        b = [c for c in cases if c["model"] == "B"]
        self.assertTrue(all(c["status"] == "ok" for c in a))   # the key really was sent and accepted
        self.assertTrue(all(c["failure_class"] == "auth" for c in b))
        self.assertTrue(all("[REDACTED]" in c["error"] for c in b), b[0]["error"])
        res = self.results(out)
        self.assertEqual(res["per_model"]["B"]["failures"], {"auth": 2})
        self.assertNotIn(SENTINEL, json.dumps(res["argv"]))
        # where the key lives on this machine is not stored either
        key_path = str(self.key_file())
        self.assertEqual(res["argv"][res["argv"].index("--api-key-file") + 1], B.REDACTED_PATH)
        [inv] = [r for r in self.records(out) if r["type"] == "invocation"]
        self.assertEqual(inv["argv"], res["argv"])
        for p in out.iterdir():
            self.assertNotIn(key_path, p.read_text(encoding="utf-8"), p.name)
            self.assertNotIn(json.dumps(key_path)[1:-1], p.read_text(encoding="utf-8"), p.name)
        self.assertEqual(B.stored_argv(["--api-key-file=" + key_path, "--out", "x"], B.Redactor(None)),
                         ["--api-key-file=<redacted path>", "--out", "x"])

    def test_exception_text_and_objects_hold_no_key(self):
        fake = B.FakeTransport(["B"], echo_auth_on_401=True, fail_models={"B"})
        sess = B.Session("https://example.test/v1", SENTINEL, fake, B.CallBudget(10), timeout_s=5, max_tries=2,
                         max_wait_s=0, sleep=lambda s: None)
        chat = B.InstrumentedChat(sess, "B", guided_json=False, extra_body={})
        with self.assertRaises(RuntimeError) as cm:
            chat.chat([{"role": "user", "content": "hi"}])
        self.assert_clean(str(cm.exception), "exception")
        self.assert_clean(repr(cm.exception.__context__), "exception context")
        self.assert_clean(repr(sess), "repr(session)")
        self.assert_clean(json.dumps({k: str(v) for k, v in vars(chat).items() if k != "session"}), "vars(client)")
        partial = B.Redactor(SENTINEL)(f"Incorrect API key provided: {SENTINEL[:14]}****")
        self.assert_clean(partial, "partial echo")
        self.assertEqual(B.Redactor(None)("Authorization: Bearer abc.def"), "Authorization: [REDACTED]")

    def test_key_file_must_hold_only_the_key(self):
        bad = self.key_file("api_key = 'x'\nother = 1\n")
        code, so, se = self.run_main(["--dry-run", "--models", "A", "--cases", "1", "--api-key-file", str(bad),
                                      "--out", str(self.tmp / "o")])
        self.assertEqual(code, B.EXIT_USAGE)
        self.assertIn("must contain only the key", se)
        self.assertNotIn("api_key = ", se + so)
        self.assertEqual(B.load_api_key(str(self.key_file(f"  {SENTINEL}\n")), {}), SENTINEL)
        self.assertEqual(B.load_api_key(None, {"CARERELAY_LLM_API_KEY": " k-env "}), "k-env")


class BudgetAndResume(Base):
    def test_max_calls_cap_stops_cleanly(self):
        out, code, so, se = self.dry("capped", "--max-calls", "3")
        self.assertEqual(code, B.EXIT_PARTIAL, se)
        recs = self.records(out)
        self.assertEqual(sum(r["type"] == "http" for r in recs), 3)
        res = self.results(out)
        self.assertEqual(B.validate_results(res), [])
        self.assertEqual(res["stopped_reason"], "max_calls")
        self.assertEqual(res["http_calls"]["total"], 3)
        self.assertEqual(res["per_model"]["A"]["n_completed"], 2)
        self.assertEqual(res["per_model"]["B"]["n_completed"], 1)
        self.assertEqual(res["per_model"]["B"]["n_aborted"], 1)
        aborted = [r for r in recs if r["type"] == "case" and r["status"] == "aborted"]
        self.assertEqual([(r["model"], r["update_id"], r["failure_class"]) for r in aborted], [("B", "u02", "aborted_max_calls")])
        self.assertIn("Stopped early", (out / "summary.md").read_text(encoding="utf-8"))

    def test_resume_skips_done_work(self):
        out, code, _, _ = self.dry("resumable", "--max-calls", "3")
        self.assertEqual(code, B.EXIT_PARTIAL)
        fake = B.FakeTransport(["A", "B"])
        code, so, se = self.run_main(["--dry-run", "--resume", str(out)], transport=fake)
        self.assertEqual(code, B.EXIT_OK, se)
        self.assertEqual(fake.calls, 7)   # 10 planned, 3 done
        recs = self.records(out)
        done = [(r["model"], r["case_id"], r["repeat"]) for r in recs if r["type"] == "case" and r["status"] != "aborted"]
        self.assertEqual(len(done), 10)
        self.assertEqual(len(set(done)), 10)
        res = self.results(out)
        self.assertEqual(B.validate_results(res), [])
        self.assertIsNone(res["stopped_reason"])
        self.assertEqual([i["invocation"] for i in res["invocations"]], [1, 2])
        self.assertEqual(res["http_calls"]["by_invocation"], {"1": 3, "2": 7})
        for m in ("A", "B"):
            self.assertEqual((res["per_model"][m]["n_completed"], res["per_model"][m]["n_aborted"]), (5, 0))
        with open(out / "records.jsonl", "ab") as f:   # a write cut off by an interruption
            f.write(b'{"type": "case", "mod')
        again = B.FakeTransport(["A", "B"])
        code, _, se = self.run_main(["--dry-run", "--resume", str(out)], transport=again)
        self.assertEqual(code, B.EXIT_OK, se)
        self.assertEqual(again.calls, 0)
        res = self.results(out)
        self.assertEqual(len(res["records_skipped_lines"]), 1)
        self.assertEqual(res["per_model"]["A"]["n_completed"], 5)
        code, _, se = self.run_main(["--dry-run", "--resume", str(out), "--models", "A,C"])
        self.assertEqual(code, B.EXIT_USAGE)
        code, _, se = self.run_main(["--resume", str(out), "--api-key-file", str(self._key())])
        self.assertEqual(code, B.EXIT_USAGE)   # a dry run cannot be resumed live
        self.assertIn("cannot be mixed", se)

    def _key(self):
        p = self.tmp / "k.txt"
        p.write_text(SENTINEL, encoding="utf-8")
        return p


class RetriesAndUsage(Base):
    def test_429_backoff_is_counted(self):
        fake = B.FakeTransport(["A"], script=[429, 429])
        out = self.tmp / "r429"
        code, so, se = self.run_main(["--dry-run", "--models", "A", "--cases", "1", "--out", str(out)], transport=fake)
        self.assertEqual(code, B.EXIT_OK, se)
        self.assertEqual(self.sleeps, [2.0, 4.0])   # llm_client's 2, 4, 8, ... s
        http = [r for r in self.records(out) if r["type"] == "http"]
        self.assertEqual([(h["attempt"], h["status"], h["outcome"]) for h in http],
                         [(1, 429, "http_error"), (2, 429, "http_error"), (3, 200, "ok")])
        case = next(r for r in self.records(out) if r["type"] == "case")
        self.assertEqual((case["status"], case["retries"], case["http_attempts"], case["llm_requests"]), ("ok", 2, 3, 1))
        self.assertEqual(case["retry_wait_s"], 6.0)
        self.assertEqual(case["statuses"], {"429": 2, "200": 1})
        res = self.results(out)
        self.assertEqual((res["http_calls"]["retries"], res["per_model"]["A"]["http"]["retries"]), (2, 2))
        self.assertEqual(res["per_model"]["A"]["call_latency_s"]["n"], 1)   # only the successful attempt

    def test_retry_after_is_honoured_and_capped(self):
        fake = B.FakeTransport(["A"], script=[{"status": 503, "retry_after": "1"}, {"status": 429, "retry_after": "500"}])
        code, _, se = self.run_main(["--dry-run", "--models", "A", "--cases", "1", "--max-wait-s", "7",
                                     "--out", str(self.tmp / "ra")], transport=fake)
        self.assertEqual(code, B.EXIT_OK, se)
        self.assertEqual(self.sleeps, [1.0, 7.0])

    def test_retries_exhausted_and_non_retryable_errors_are_classified(self):
        fake = B.FakeTransport(["A"], script=[429, 429, 400])
        out = self.tmp / "exhaust"
        code, _, se = self.run_main(["--dry-run", "--models", "A", "--cases", "3", "--max-tries", "2", "--out", str(out)],
                                    transport=fake)
        self.assertEqual(code, B.EXIT_OK, se)
        cases = [r for r in self.records(out) if r["type"] == "case"]
        self.assertEqual([c["failure_class"] for c in cases], ["rate_limited", "http_4xx", None])
        self.assertEqual([c["http_attempts"] for c in cases], [2, 1, 1])
        self.assertEqual(self.sleeps, [2.0])
        res = self.results(out)
        self.assertEqual(res["per_model"]["A"]["failures"], {"rate_limited": 1, "http_4xx": 1})
        self.assertEqual(res["per_model"]["A"]["success"]["count"], 1)

    def test_timeout_is_not_retried_by_default(self):
        fake = B.FakeTransport(["A"], script=["timeout"])
        out = self.tmp / "timeout"
        code, _, se = self.run_main(["--dry-run", "--models", "A", "--cases", "1", "--out", str(out)], transport=fake)
        self.assertEqual(code, B.EXIT_OK, se)
        case = next(r for r in self.records(out) if r["type"] == "case")
        self.assertEqual((case["failure_class"], case["http_attempts"]), ("timeout", 1))

    def test_missing_usage_is_null_not_estimated(self):
        fake = B.FakeTransport(["A"], omit_usage=True)
        out = self.tmp / "nousage"
        code, so, se = self.run_main(["--dry-run", "--models", "A", "--cases", "2", "--out", str(out)], transport=fake)
        self.assertEqual(code, B.EXIT_OK, se)
        recs = self.records(out)
        for h in (r for r in recs if r["type"] == "http"):
            self.assertEqual((h["usage_present"], h["prompt_tokens"], h["completion_tokens"], h["total_tokens"]),
                             (False, None, None, None))
        for c in (r for r in recs if r["type"] == "case"):
            self.assertEqual(c["status"], "ok")
            self.assertEqual((c["prompt_tokens"], c["completion_tokens"], c["total_tokens"], c["usage_complete"]),
                             (None, None, None, False))
        s = self.results(out)["per_model"]["A"]
        self.assertEqual(B.validate_results(self.results(out)), [])
        self.assertEqual((s["tokens_per_handover"]["n_with_usage"], s["tokens_per_handover"]["n_missing_usage"]), (0, 2))
        self.assertIsNone(s["tokens_per_handover"]["mean"])
        self.assertIsNone(s["completion_tokens_per_s"]["aggregate"])
        self.assertIn("n/a", (out / "summary.md").read_text(encoding="utf-8"))

    def test_usage_fields(self):
        self.assertEqual(B.usage_fields({"prompt_tokens": 5}),
                         {"usage_present": True, "prompt_tokens": 5, "completion_tokens": None, "total_tokens": None})
        self.assertEqual(B.usage_fields({"prompt_tokens": 5, "completion_tokens": 2})["total_tokens"], 7)
        self.assertIsNone(B.usage_fields({"prompt_tokens": True, "completion_tokens": "3"})["prompt_tokens"])
        self.assertEqual(B.usage_fields(None)["usage_present"], False)


class FakeHTTPResponse:
    """What urllib.request.urlopen returns, enough for UrllibTransport: no socket."""

    def __init__(self, body=b"", lines=None, content_type="application/json"):
        self.status, self._body, self._lines = 200, body, list(lines or [])
        self.headers = {"Content-Type": content_type}
        self.length, self.closed = None, False

    def read1(self, n=-1):
        chunk, self._body = self._body, b""
        return chunk

    read = read1

    def readline(self):
        return self._lines.pop(0) if self._lines else b""

    def isclosed(self):
        return not self._body

    def close(self):
        self.closed = True


class LiveTransportOffline(Base):
    """UrllibTransport with urlopen patched: the request the live run would send, without sending it."""

    def test_request_shape_matches_the_page(self):
        seen = {}
        reply = {"choices": [{"message": {"content": '{"facts": []}'}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 11, "completion_tokens": 3}}

        def urlopen(req, timeout):
            seen.update(url=req.full_url, method=req.get_method(), auth=req.get_header("Authorization"),
                        payload=json.loads(req.data), timeout=timeout)
            return FakeHTTPResponse(json.dumps(reply).encode())
        sess = B.Session("https://example.test/v1", SENTINEL, B.UrllibTransport(), B.CallBudget(5), timeout_s=120,
                         max_tries=6, max_wait_s=60, sleep=self.sleeps.append)
        meter = sess.begin(invocation=1, model="M", case_id="c", repeat=0, purpose="extract")
        chat = B.InstrumentedChat(sess, "M", guided_json=False, extra_body={"reasoning_effort": "low"})
        with patch("urllib.request.urlopen", urlopen):
            r = chat.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                          json_schema={"type": "object"}, schema_name="facts")
        self.assertEqual((seen["url"], seen["method"], seen["timeout"]), ("https://example.test/v1/chat/completions", "POST", 120))
        self.assertEqual(seen["auth"], "Bearer " + SENTINEL)
        p = seen["payload"]
        self.assertEqual((p["model"], p["max_tokens"], p["temperature"], p["seed"], p["reasoning_effort"]),
                         ("M", B.PAGE_MAX_TOKENS, 0.0, 0, "low"))
        self.assertNotIn("response_format", p)   # prompted JSON, as the page runs on Token Factory
        self.assertIn("JSON Schema", p["messages"][-1]["content"])
        self.assertEqual((r["json"], r["json_mode"], r["usage"]["prompt_tokens"]), ({"facts": []}, "prompted_json", 11))
        self.assertEqual((meter.attempts, meter.prompt_tokens, meter.completion_tokens), (1, 11, 3))

    def test_streaming_lines_are_read(self):
        lines = [b'data: {"choices": [{"delta": {"content": "OK"}}]}\n', b"\n", b"data: [DONE]\n"]
        with patch("urllib.request.urlopen", lambda req, timeout: FakeHTTPResponse(lines=lines, content_type="text/event-stream")):
            resp = B.UrllibTransport()("POST", "https://example.test/v1/chat/completions", {}, b"{}", 10, stream=True)
        self.assertEqual(resp.headers["content-type"], "text/event-stream")
        self.assertEqual(list(resp.iter_lines()), lines)


class AddsUngroundedFacts(B.FakeTransport):
    """The fake's extraction reply plus three proposals the grounding check rejects: a quote the update does not contain
    (longer than 300 characters), a quote that is not text, and an entry that is not an object."""
    LONG = "this sentence was never said in the update " * 10

    def __call__(self, method, url, headers, body, timeout, stream=False):
        resp = super().__call__(method, url, headers, body, timeout, stream=stream)
        if stream or method != "POST":
            return resp
        out = json.loads(resp.body)
        msg = out["choices"][0]["message"]
        reply = json.loads(msg["content"])
        reply["facts"] += [{"type": "event", "what": "invented", "quote": self.LONG},
                           {"type": "event", "what": "x", "quote": ["not", "text"]}, "not an object"]
        msg["content"] = json.dumps(reply)
        return B.Response(resp.status, resp.headers, json.dumps(out).encode())


class RejectedFacts(Base):
    def test_rejected_facts_keep_type_quote_and_reason(self):
        out = self.tmp / "rejected"
        code, _, se = self.run_main(["--dry-run", "--models", "A", "--cases", "2", "--out", str(out)],
                                    transport=AddsUngroundedFacts(["A"]))
        self.assertEqual(code, B.EXIT_OK, se)
        recs = self.records(out)
        self.assertEqual(recs[0]["schema_version"], B.SCHEMA_VERSION)
        cases = [r for r in recs if r["type"] == "case"]
        self.assertEqual(len(cases), 2)
        for c in cases:
            self.assertEqual(B.validate_record(c), [])
            self.assertEqual(c["status"], "ok")
            rf = c["rejected_facts"]
            self.assertEqual(len(rf), c["facts_rejected_grounding"])
            self.assertEqual([r["reason"] for r in rf], c["rejection_reasons"])   # one to one, in the same order
            self.assertEqual(c["facts_accepted"] + len(rf) + c["facts_withheld"], c["facts_proposed"])
            self.assertEqual([(r["type"], r["quote"]) for r in rf[-3:]],
                             [("event", AddsUngroundedFacts.LONG.strip()[:300]), ("event", None), (None, None)])
            self.assertTrue(all(isinstance(r["reason"], str) and r["reason"] for r in rf))
            self.assertGreater(c["facts_accepted"], 0)   # the story's own facts still pass
        s = self.results(out)["per_model"]["A"]
        self.assertEqual(s["citation_validity"]["proposed"] - s["citation_validity"]["valid"], 6)

    def test_clean_run_records_an_empty_list(self):
        out, code, _, se = self.dry("clean")
        self.assertEqual(code, B.EXIT_OK, se)
        cases = [r for r in self.records(out) if r["type"] == "case"]
        self.assertTrue(cases and all(c["rejected_facts"] == [] for c in cases))

    def test_rejected_fact_shape(self):
        self.assertEqual(B.rejected_fact({"fact": {"type": "event", "quote": "q" * 400, "what": "w"}, "reason": "r"}),
                         {"type": "event", "quote": "q" * 300, "reason": "r"})
        self.assertEqual(B.rejected_fact({"fact": {"type": 3, "quote": 7}, "reason": "unknown fact type"}),
                         {"type": None, "quote": None, "reason": "unknown fact type"})
        self.assertEqual(B.rejected_fact({"fact": "text", "reason": "unknown fact type"}),
                         {"type": None, "quote": None, "reason": "unknown fact type"})

    def test_v1_records_and_results_are_still_read(self):
        out, code, _, se = self.dry("v1")
        self.assertEqual(code, B.EXIT_OK, se)
        res = self.results(out)
        res["schema_version"] = "kindredrelay-bench-token-factory-v1"
        self.assertEqual(B.validate_results(res), [])
        res["schema_version"] = "kindredrelay-bench-token-factory-v0"
        self.assertEqual(B.validate_results(res), ["schema_version"])
        case = next(r for r in self.records(out) if r["type"] == "case")
        v1 = {k: v for k, v in case.items() if k != "rejected_facts"}   # a v1 case record has no rejected_facts
        self.assertEqual(B.validate_record(v1), [])
        self.assertEqual(B.validate_record({**case, "rejected_facts": ["reason only"]}),
                         ["rejected_facts is not a list of {type, quote, reason}"])

    def test_a_v1_run_is_not_resumed(self):
        out, code, _, _ = self.dry("v1resume", "--max-calls", "3")
        self.assertEqual(code, B.EXIT_PARTIAL)
        path = out / "records.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        start = json.loads(lines[0])
        start["schema_version"] = "kindredrelay-bench-token-factory-v1"
        path.write_text("\n".join([json.dumps(start)] + lines[1:]) + "\n", encoding="utf-8")
        fake = B.FakeTransport(["A", "B"])
        code, _, se = self.run_main(["--dry-run", "--resume", str(out)], transport=fake)
        self.assertEqual(code, B.EXIT_USAGE)
        self.assertIn("not written by this benchmark version", se)
        self.assertEqual(fake.calls, 0)


class Gate(Base):
    def test_gate_mode_holds_unsupported_facts(self):
        def needs_review(update, fact):
            return {"status": "needs_review", "mode": "gate", "model_id": "stub", "claim": ""}
        needs_review.mode = "gate"
        out = self.tmp / "held"
        code, _, se = self.run_main(["--dry-run", "--models", "A", "--cases", "2", "--out", str(out)], checker=needs_review)
        self.assertEqual(code, B.EXIT_OK, se)
        cases = [r for r in self.records(out) if r["type"] == "case"]
        self.assertTrue(all(c["gate_decision"] == "held" and c["facts_withheld"] == c["facts_proposed"] > 0 for c in cases))
        self.assertTrue(all(c["citations_valid"] == c["facts_proposed"] for c in cases))   # withheld is not a bad quote
        s = self.results(out)["per_model"]["A"]
        self.assertEqual((s["gate"]["n_gated"], s["gate"]["pass_rate"]), (2, 0.0))

    def test_gate_mode_passes_supported_facts(self):
        def supported(update, fact):
            return {"status": "supported_by_model", "mode": "gate", "model_id": "stub", "claim": ""}
        supported.mode = "gate"
        out = self.tmp / "pass"
        code, _, se = self.run_main(["--dry-run", "--models", "A", "--cases", "1", "--out", str(out)], checker=supported)
        self.assertEqual(code, B.EXIT_OK, se)
        case = next(r for r in self.records(out) if r["type"] == "case")
        self.assertEqual((case["gate_decision"], case["facts_withheld"]), ("pass", 0))   # u01 states no dates
        self.assertEqual(self.results(out)["per_model"]["A"]["gate"]["pass_rate"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
