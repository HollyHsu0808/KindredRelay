"""Offline tests of scripts/load_tf_endpoint.py; every endpoint is the bench's FakeTransport, nothing touches the network.

.venv/Scripts/python.exe scripts/test_load_tf_endpoint.py
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_tf_handover as B  # noqa: E402
import load_tf_endpoint as L  # noqa: E402

SENTINEL = "sk-SENTINEL-7f3a9c1e5b2d4f60a8e1"   # never a real key
ENV_PREFIXES = ("CARERELAY_LLM_", "CARERELAY_PHOTO_", "KINDRED_VERIFIER_", "CARERELAY_STORY")
MODEL = "DeepSeek-V4-Flash"


class Recording(B.FakeTransport):
    """The bench's fake, keeping every chat payload it was sent (thread-safe) and holding each reply a little, so that
    concurrent requests overlap."""

    def __init__(self, *a, hold_s=0.03, **kw):
        super().__init__(*a, delay_s=hold_s, **kw)
        self.payloads, self._lock = [], threading.Lock()

    def __call__(self, method, url, headers, body, timeout, stream=False):
        with self._lock:
            if body:
                self.payloads.append(json.loads(body))
        return super().__call__(method, url, headers, body, timeout, stream=stream)


class Base(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ)
        self._env.start()
        for k in [k for k in os.environ if k.startswith(ENV_PREFIXES)]:
            del os.environ[k]
        self.tmp = Path(tempfile.mkdtemp(prefix="load_tf_test_"))
        self.sleeps: list[float] = []

    def tearDown(self):
        self._env.stop()

    def run_main(self, argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        kw.setdefault("sleep", self.sleeps.append)
        with redirect_stdout(out), redirect_stderr(err):
            code = L.main(argv, **kw)
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def records(out: Path):
        return [json.loads(x) for x in (out / "records.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

    @staticmethod
    def results(out: Path):
        return json.loads((out / "results.json").read_text(encoding="utf-8"))

    def key_file(self, text=SENTINEL):
        p = self.tmp / "key.txt"
        p.write_text(text, encoding="utf-8")
        return p


class DryRun(Base):
    def test_default_dry_run_writes_valid_outputs(self):
        fake = Recording([MODEL])
        out = self.tmp / "run"
        code, so, se = self.run_main(["--dry-run", "--out", str(out)], transport=fake)
        self.assertEqual(code, L.EXIT_OK, se)
        for name in ("records.jsonl", "results.json", "summary.md", "throughput.svg"):
            self.assertTrue((out / name).is_file(), name)
        res = self.results(out)
        self.assertEqual(L.validate_results(res), [])
        self.assertEqual((res["model"], res["dry_run"], res["endpoint"]["host"]), (MODEL, True, "developer.amd.com.cn"))
        self.assertEqual([lv["concurrency"] for lv in res["levels"]], [1, 2, 4, 8])
        self.assertEqual(res["http_calls"]["total"], 64)   # 4 levels x 16 requests, no retry
        self.assertLessEqual(res["http_calls"]["total"], L.MAX_CALLS_CEILING)
        self.assertEqual(self.sleeps, [10.0, 10.0, 10.0])   # the pause between levels
        for lv in res["levels"]:
            self.assertEqual((lv["requests"], lv["ok"], lv["failed"], lv["not_run"]), (16, 16, 0, 0))
            self.assertIsNotNone(lv["throughput"]["handovers_per_min"])
            self.assertIsNotNone(lv["throughput"]["completion_tokens_per_s"])
            self.assertIsNotNone(lv["latency_s"]["p50_ci95"])
            self.assertIsNotNone(lv["latency_s"]["p95_ci95"])
            self.assertEqual(lv["http"]["status_429"], 0)
        flights = {lv["concurrency"]: lv["max_in_flight"] for lv in res["levels"]}
        self.assertEqual(flights[1], 1)
        self.assertGreater(flights[8], 1)   # the threads really overlapped
        self.assertTrue(all(flights[c] <= c for c in flights))
        best = max(res["levels"], key=lambda lv: (lv["throughput"]["handovers_per_min"], -lv["concurrency"]))
        pm = res["per_model"][MODEL]
        self.assertEqual((pm["concurrency"], pm["throughput_handovers_per_s"]),
                         (best["concurrency"], round(best["throughput"]["handovers_per_min"] / 60, 5)))
        self.assertEqual(pm["levels"], res["levels"])
        reqs = [r for r in self.records(out) if r["type"] == "request"]
        self.assertEqual(sorted({r["update_id"] for r in reqs}), ["u01", "u02", "u03", "u04"])   # the fixed cycle
        md = (out / "summary.md").read_text(encoding="utf-8")
        self.assertIn("DRY RUN", md)
        self.assertIn("Dry run: the replies came from a scripted fake transport", md)
        for gpu in ("MI300", "MI325", "Instinct"):
            self.assertNotIn(gpu, md)
        self.assertTrue(ET.fromstring((out / "throughput.svg").read_text(encoding="utf-8")).tag.endswith("svg"))

    def test_request_is_the_bench_handover_call(self):
        fake = Recording([MODEL])
        out = self.tmp / "shape"
        code, _, se = self.run_main(["--dry-run", "--levels", "1", "--requests-per-level", "2", "--out", str(out)],
                                    transport=fake)
        self.assertEqual(code, L.EXIT_OK, se)
        self.assertEqual(len(fake.payloads), 2)
        for p in fake.payloads:
            self.assertEqual((p["model"], p["max_tokens"], p["temperature"]), (MODEL, B.PAGE_MAX_TOKENS, 0.0))
            self.assertNotIn("response_format", p)   # prompted JSON (CARERELAY_LLM_GUIDED_JSON=0 in the release settings)
            self.assertIn("List every fact this update states", p["messages"][-1]["content"])
        res = self.results(out)
        self.assertEqual((res["pipeline"]["guided_json"], res["pipeline"]["timeout_s"]), (False, 120.0))
        reqs = [r for r in self.records(out) if r["type"] == "request"]
        self.assertTrue(all(r["facts_accepted"] > 0 and r["reply_parsed"] for r in reqs))   # a real handover ran


class Refusals(Base):
    def test_out_exists_is_refused(self):
        out = self.tmp / "exists"
        out.mkdir()
        code, _, se = self.run_main(["--dry-run", "--out", str(out)])
        self.assertEqual(code, L.EXIT_USAGE)
        self.assertIn("already exists", se)
        self.assertEqual(list(out.iterdir()), [])
        f = self.tmp / "a_file"
        f.write_text("x", encoding="utf-8")
        code, _, _ = self.run_main(["--dry-run", "--out", str(f)])
        self.assertEqual(code, L.EXIT_USAGE)
        self.assertEqual(f.read_text(encoding="utf-8"), "x")

    def test_call_cap_is_enforced_before_any_call(self):
        for extra, msg in ((["--max-calls", "121"], "between 1 and 120"),
                           (["--requests-per-level", "31"], "do not fit"),
                           (["--levels", "1,1"], "distinct"), (["--levels", "0,2"], "at least 1"),
                           (["--levels", "a"], "whole numbers")):
            fake = B.FakeTransport([MODEL])
            out = self.tmp / f"cap_{len(msg)}"
            code, _, se = self.run_main(["--dry-run", "--out", str(out), *extra], transport=fake)
            self.assertEqual(code, L.EXIT_USAGE, extra)
            self.assertIn(msg, se)
            self.assertEqual(fake.calls, 0)
            self.assertFalse(out.exists())

    def test_live_run_without_key_is_refused(self):
        out = self.tmp / "live"
        code, _, se = self.run_main(["--out", str(out)], env={})
        self.assertEqual(code, L.EXIT_USAGE)
        self.assertIn("no API key", se)
        self.assertFalse(out.exists())


class BudgetAndRetries(Base):
    def test_max_calls_stops_cleanly(self):
        fake = B.FakeTransport([MODEL], script=[429])   # the first attempt is rate limited and retried
        out = self.tmp / "capped"
        code, so, se = self.run_main(["--dry-run", "--levels", "1,2", "--requests-per-level", "3", "--max-calls", "6",
                                      "--out", str(out)], transport=fake)
        self.assertEqual(code, L.EXIT_PARTIAL, se)
        recs = self.records(out)
        self.assertEqual(sum(r["type"] == "http" for r in recs), 6)
        res = self.results(out)
        self.assertEqual(L.validate_results(res), [])
        self.assertEqual((res["stopped_reason"], res["http_calls"]["total"], res["http_calls"]["status_429"]),
                         ("max_calls", 6, 1))
        last = res["levels"][-1]
        self.assertEqual(last["concurrency"], 2)
        self.assertEqual(last["ok"] + last["aborted"] + last["not_run"], 3)
        self.assertGreaterEqual(last["aborted"] + last["not_run"], 1)
        self.assertIn("Stopped early", (out / "summary.md").read_text(encoding="utf-8"))

    def test_429_is_counted_and_backed_off(self):
        fake = B.FakeTransport([MODEL], script=[429, {"status": 429, "retry_after": "3"}])
        out = self.tmp / "r429"
        code, _, se = self.run_main(["--dry-run", "--levels", "1", "--requests-per-level", "2", "--out", str(out)],
                                    transport=fake)
        self.assertEqual(code, L.EXIT_OK, se)
        self.assertEqual(self.sleeps, [2.0, 3.0])   # llm_client's 2 s, then the server's Retry-After
        lv = self.results(out)["levels"][0]
        self.assertEqual((lv["ok"], lv["http"]["attempts"], lv["http"]["retries"], lv["http"]["status_429"]), (2, 4, 2, 2))
        self.assertEqual(lv["http"]["rate_429"], 0.5)
        self.assertEqual(lv["http"]["wilson95_429"], B.wilson95(2, 4))
        self.assertEqual(lv["http"]["retry_wait_s"], 5.0)
        first = next(r for r in self.records(out) if r["type"] == "request" and r["index"] == 0)
        self.assertEqual((first["retries"], first["status_429"], first["statuses"]), (2, 2, {"429": 2, "200": 1}))

    def test_missing_usage_is_null_not_estimated(self):
        fake = B.FakeTransport([MODEL], omit_usage=True)
        out = self.tmp / "nousage"
        code, _, se = self.run_main(["--dry-run", "--levels", "1,2", "--requests-per-level", "2", "--out", str(out)],
                                    transport=fake)
        self.assertEqual(code, L.EXIT_OK, se)
        for lv in self.results(out)["levels"]:
            self.assertIsNone(lv["throughput"]["completion_tokens_per_s"])
            self.assertEqual(lv["throughput"]["ok_without_usage"], 2)
            self.assertIsNotNone(lv["throughput"]["handovers_per_min"])


class Secrets(Base):
    def assert_clean(self, text, where):
        self.assertNotIn(SENTINEL, text, where)
        for i in range(len(SENTINEL) - 7):
            self.assertNotIn(SENTINEL[i:i + 8], text, f"{where}: 8-character piece {i} of the key")

    def test_key_never_in_outputs(self):
        # every request is refused with a 401 whose body repeats the Authorization header, as some gateways do
        fake = B.FakeTransport([MODEL], echo_auth_on_401=True, fail_models={MODEL})
        out = self.tmp / "secret"
        code, so, se = self.run_main(["--levels", "1,2", "--requests-per-level", "2", "--api-key-file",
                                      str(self.key_file()), "--out", str(out)], transport=fake)
        self.assertEqual(code, L.EXIT_OK, se)
        self.assertGreater(fake.calls, 0)
        self.assert_clean(so, "stdout")
        self.assert_clean(se, "stderr")
        for p in out.iterdir():
            self.assert_clean(p.read_text(encoding="utf-8"), p.name)
        reqs = [r for r in self.records(out) if r["type"] == "request"]
        self.assertTrue(reqs and all(r["failure_class"] == "auth" for r in reqs))
        self.assertTrue(all("[REDACTED]" in r["error"] for r in reqs), reqs[0]["error"])
        res = self.results(out)
        self.assertEqual(res["argv"][res["argv"].index("--api-key-file") + 1], B.REDACTED_PATH)
        key_path = str(self.key_file())
        for p in out.iterdir():
            self.assertNotIn(key_path, p.read_text(encoding="utf-8"), p.name)
            self.assertNotIn(json.dumps(key_path)[1:-1], p.read_text(encoding="utf-8"), p.name)

    def test_key_is_sent_and_not_held_on_the_runner(self):
        fake = B.FakeTransport([MODEL], require_key=SENTINEL)
        out = self.tmp / "sent"
        code, so, se = self.run_main(["--levels", "2", "--requests-per-level", "2", "--api-key-file",
                                      str(self.key_file()), "--out", str(out)], transport=fake)
        self.assertEqual(code, L.EXIT_OK, se)
        self.assertEqual(self.results(out)["levels"][0]["ok"], 2)   # accepted: the key really was sent
        cfg = L.new_config(L.parse_args(["--dry-run", "--out", "x"]), {}, B.release_defaults(), "fake")
        test = L.LoadTest(cfg, self.tmp / "unused", transport=fake, api_key=SENTINEL)
        self.assert_clean(repr(test), "repr")
        self.assert_clean(json.dumps({k: str(v) for k, v in vars(test).items()}), "vars(LoadTest)")


class Marker(Base):
    def test_marker_exists_only_while_the_levels_run(self):
        marker = self.tmp / ".load_test_running"
        seen = []

        class Watch(B.FakeTransport):
            def __call__(self, *a, **kw):
                seen.append(marker.exists())
                return super().__call__(*a, **kw)
        out = self.tmp / "marked"
        code, _, se = self.run_main(["--dry-run", "--levels", "1,2", "--requests-per-level", "2", "--marker", str(marker),
                                     "--out", str(out)], transport=Watch([MODEL]))
        self.assertEqual(code, L.EXIT_OK, se)
        self.assertTrue(seen and all(seen))   # present during every call
        self.assertFalse(marker.exists())   # removed at the end
        res = self.results(out)
        self.assertEqual(len(res["design"]["marker_window_utc"]), 2)
        self.assertIn("were asked to pause while the marker file", (out / "summary.md").read_text(encoding="utf-8"))

    def test_marker_is_removed_on_an_interruption_and_an_existing_one_is_refused(self):
        marker = self.tmp / ".load_test_running"

        class Interrupt(B.FakeTransport):
            def __call__(self, *a, **kw):
                raise KeyboardInterrupt
        out = self.tmp / "interrupted"
        code, so, se = self.run_main(["--dry-run", "--levels", "1", "--requests-per-level", "2", "--marker", str(marker),
                                      "--out", str(out)], transport=Interrupt([MODEL]))
        self.assertEqual(code, L.EXIT_INTERRUPTED, se)
        self.assertFalse(marker.exists())
        self.assertEqual(self.results(out)["stopped_reason"], "interrupted")
        marker.write_text("", encoding="utf-8")
        fake = B.FakeTransport([MODEL])
        code, _, se = self.run_main(["--dry-run", "--marker", str(marker), "--out", str(self.tmp / "o2")], transport=fake)
        self.assertEqual(code, L.EXIT_USAGE)
        self.assertIn("another load run may be in progress", se)
        self.assertEqual(fake.calls, 0)
        self.assertTrue(marker.exists())   # not ours: left alone


class RateLimitBreakdown(Base):
    RPM = b'{"error":{"message":"Rate limit exceeded: maximum 20 requests per minute for this OneClick user.","type":"rate_limit_error","param":null,"code":"rate_limit_exceeded"}}'
    TOK = b'{"detail":{"error":{"message":"Model API rate limit exceeded; please retry later","type":"rate_limit_error","code":"token_rate_limit_exceeded"}}}'

    def test_breakdown_from_records_only(self):
        bodies = [self.RPM, self.TOK, self.RPM]

        class Limited(B.FakeTransport):   # the first three attempts answer 429 with the endpoint's two body shapes
            def __call__(self, method, url, *a, **kw):
                if bodies:
                    raise B._http_error(url, 429, bodies.pop(0), "1")
                return super().__call__(method, url, *a, **kw)
        out = self.tmp / "limited"
        code, _, se = self.run_main(["--dry-run", "--levels", "1,2", "--requests-per-level", "2", "--out", str(out)],
                                    transport=Limited([MODEL]))
        self.assertEqual(code, L.EXIT_OK, se)
        before = {n: (out / n).read_bytes() for n in ("records.jsonl", "results.json", "summary.md", "throughput.svg")}
        code, so, se = self.run_main(["--rate-limit-breakdown", str(out)])
        self.assertEqual(code, L.EXIT_OK, se)
        self.assertIn("3 of 7 attempts answered 429: 2 x rate_limit_exceeded, 1 x token_rate_limit_exceeded", so)
        self.assertEqual({n: (out / n).read_bytes() for n in before}, before)   # nothing of the run is rewritten
        bd = json.loads((out / "rate_limit_breakdown.json").read_text(encoding="utf-8"))
        self.assertTrue(bd["derived_after_run"])
        self.assertEqual(bd["source"]["sha256"], B.file_sha(out / "records.jsonl"))
        lv1 = bd["levels"][0]
        self.assertEqual((lv1["concurrency"], lv1["status_429"], lv1["attempts"]), (1, 3, 5))
        self.assertEqual({k: v["count"] for k, v in lv1["by_code"].items()},
                         {"rate_limit_exceeded": 2, "token_rate_limit_exceeded": 1})
        self.assertEqual([e["code"] for e in lv1["events"]],
                         ["rate_limit_exceeded", "token_rate_limit_exceeded", "rate_limit_exceeded"])
        self.assertEqual(bd["levels"][1]["status_429"], 0)
        self.assertIn("maximum 20 requests per minute", (out / "rate_limit_breakdown.md").read_text(encoding="utf-8"))
        code, _, se = self.run_main(["--rate-limit-breakdown", str(out)])   # never rewritten
        self.assertEqual(code, L.EXIT_USAGE)
        self.assertIn("is not rewritten", se)

    def test_reason_parsing(self):
        self.assertEqual(L.rate_limit_reason(self.TOK.decode()),
                         ("token_rate_limit_exceeded", "Model API rate limit exceeded; please retry later"))
        cut = self.RPM.decode()[:140]   # a body cut at the record's 300 characters is no longer JSON
        self.assertEqual(L.rate_limit_reason(cut)[0], "no code")
        self.assertEqual(L.rate_limit_reason('{"detail": "busy"}'), ("no code", '{"detail": "busy"}'))
        self.assertEqual(L.rate_limit_reason(None), ("no code", None))


class CapacityModelContract(Base):
    def test_capacity_model_reads_the_throughput_and_concurrency(self):
        import capacity_model as C   # scripts/capacity_model.py: its own key templates and lookup
        out = self.tmp / "contract"
        code, _, se = self.run_main(["--dry-run", "--levels", "1,2", "--requests-per-level", "2", "--out", str(out)],
                                    transport=Recording([MODEL], hold_s=0.01))
        self.assertEqual(code, L.EXIT_OK, se)
        doc = self.results(out)
        t = C.num(C.get(doc, C.key_path(C.LOAD_THROUGHPUT_KEY, MODEL)))
        c = C.num(C.get(doc, C.key_path(C.LOAD_CONCURRENCY_KEY, MODEL)))
        self.assertTrue(t is not None and t > 0 and c in (1.0, 2.0), (t, c))
        self.assertIs(doc["dry_run"], True)   # capacity_model skips it: only a live run is a measurement


class CapacityNote(unittest.TestCase):
    @staticmethod
    def level(c, thr, n429=0):
        return {"concurrency": c, "throughput": {"handovers_per_min": thr}, "http": {"status_429": n429}}

    def test_rate_limit_is_named_not_hardware(self):
        note = L.capacity_note([self.level(1, 6.0), self.level(2, 11.0), self.level(4, 12.0, n429=3),
                                self.level(8, 12.1, n429=9)], dry_run=False)
        self.assertIn("HTTP 429 (rate limited) at concurrency 4, 8", note)
        self.assertIn("not by the speed of the serving hardware", note)
        self.assertIn("stopped rising", note)
        self.assertIn("read as rate limiting", note)
        for gpu in ("MI300", "GPU", "Instinct"):
            self.assertNotIn(gpu, note)

    def test_plateau_without_429_claims_no_cause(self):
        note = L.capacity_note([self.level(1, 6.0), self.level(2, 6.2)], dry_run=False)
        self.assertIn("no HTTP 429 was returned there", note)
        self.assertIn("no hardware capacity is inferred", note)

    def test_rising_curve_and_dry_run(self):
        note = L.capacity_note([self.level(1, 6.0), self.level(2, 11.5), self.level(4, 21.0)], dry_run=False)
        self.assertIn("rose at every step up to concurrency 4", note)
        self.assertIn("3.50x for 4x", note)
        self.assertIn("says nothing about any endpoint", L.capacity_note([self.level(1, 6.0)], dry_run=True))

    def test_max_in_flight(self):
        recs = [{"start_s": 0.0, "end_s": 1.0}, {"start_s": 0.5, "end_s": 2.0}, {"start_s": 1.0, "end_s": 1.5},
                {"start_s": None, "end_s": None}]
        self.assertEqual(L.max_in_flight(recs), 2)   # the third starts as the first ends


if __name__ == "__main__":
    unittest.main(verbosity=2)
