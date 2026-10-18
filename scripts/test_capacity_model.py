"""Offline tests of scripts/capacity_model.py on synthetic benchmark results (no model, no network).

.venv/Scripts/python.exe scripts/test_capacity_model.py
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
import capacity_model as C  # noqa: E402

TF = C.TOKEN_FACTORY_HOST
BASE = dict(C.DEFAULT_ASSUMPTIONS)


def tf_doc(created: str, model: str = "M", tokens: float = 1000.0, e2e_mean: float = 10.0, dry: bool = False,
           host: str = TF) -> dict:
    return {"created_utc": created, "dry_run": dry, "endpoint": {"host": host},
            "per_model": {model: {"n_completed": 4, "success": {"count": 4},
                                  "e2e_latency_s": {"mean": e2e_mean, "p50": 8.0, "p95": 20.0},
                                  "tokens_per_handover": {"mean": tokens, "prompt_mean": tokens * 0.8,
                                                          "completion_mean": tokens * 0.2, "n_with_usage": 4}}}}


def cc_doc(created: str, tokens: float = 500.0, p50: float = 5.0, dry: bool = False) -> dict:
    return {"created_utc": created, "dry_run": dry, "endpoint": {"host": TF}, "judge": {"model": "J"},
            "latency_s": {"p50": p50, "p95": 9.0, "n": 8}, "tokens_per_check": {"mean": tokens, "p50": tokens, "n_with_usage": 8}}


def load_doc(created: str, model: str = "M", per_s: float = 0.5, concurrency: int = 8, dry: bool = False) -> dict:
    return {"created_utc": created, "dry_run": dry, "endpoint": {"host": TF},
            "per_model": {model: {"throughput_handovers_per_s": per_s, "concurrency": concurrency}}}


class Bench:
    """A temporary release/benchmarks folder."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def put(self, folder: str, doc) -> Path:
        p = self.root / folder / "results.json"
        p.parent.mkdir(parents=True)
        p.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
        return p

    def build(self, model: str = "M", **assumed) -> dict:
        return C.build(self.root, model, {**BASE, **assumed})

    def close(self):
        self.tmp.cleanup()


class TestCapacityModel(unittest.TestCase):
    def setUp(self):
        self.b = Bench()
        self.addCleanup(self.b.close)

    def test_newest_live_benchmark_and_sequential_arithmetic(self):
        self.b.put("tf_bench_old", tf_doc("2026-10-17T10:00:00+00:00", tokens=9999.0))
        self.b.put("tf_bench_new", tf_doc("2026-10-17T20:00:00+00:00"))
        self.b.put("tf_bench_newer_dry", tf_doc("2026-10-18T01:00:00+00:00", tokens=1.0, dry=True))
        self.b.put("tf_bench_broken", "{not json")
        res = self.b.build()
        tf = res["measured"]["tf_bench"]
        self.assertTrue(tf["path"].endswith("tf_bench_new/results.json"), tf["path"])
        self.assertEqual({s["reason"].split(":")[0] for s in tf["skipped"]}, {"unreadable", "dry run (or dry_run not false)"})
        item = tf["items"]["tokens_per_handover"]
        self.assertEqual((item["value"], item["key"]), (1000.0, "per_model.M.tokens_per_handover.mean"))
        o = res["outputs"]
        self.assertEqual((o["tokens_per_family_per_day"], o["tokens_per_family_per_month"],
                          o["tokens_per_1000_families_per_day"]), (2000.0, 60000.0, 2_000_000.0))
        self.assertEqual((o["seconds_per_update_sequential"], o["handovers_per_stream_hour_sequential"]), (10.0, 360.0))
        self.assertAlmostEqual(o["hours_per_1000_families_per_day"], 2000 / 360)
        self.assertEqual((o["updates_per_coordinator_per_day"], o["tokens_per_coordinator_per_day"]), (60.0, 60000.0))
        self.assertAlmostEqual(o["hours_per_coordinator_per_day"], 60 / 360)
        self.assertEqual((o["capacity_basis"], o["handovers_per_endpoint_hour_at_load_concurrency"]), ("sequential", None))
        self.assertIsNone(o["cost_per_family_per_month"], "no price: tokens only")
        self.assertEqual(res["wording"], C.WORDING)
        self.assertTrue(any("sequential stream only" in n for n in res["notes"]))

    def test_a_model_name_with_a_dot(self):
        self.b.put("tf_bench_a", tf_doc("2026-10-17T20:00:00+00:00", model="Qwen3.8-27B", tokens=800.0))
        res = self.b.build("Qwen3.8-27B")
        self.assertEqual(res["outputs"]["tokens_per_family_per_day"], 1600.0)
        self.assertEqual(res["measured"]["tf_bench"]["items"]["tokens_per_handover"]["key"],
                         "per_model.Qwen3.8-27B.tokens_per_handover.mean")

    def test_no_live_benchmark_is_a_usage_error(self):
        self.b.put("tf_bench_dry", tf_doc("2026-10-17T20:00:00+00:00", dry=True))
        self.b.put("tf_bench_other", tf_doc("2026-10-17T21:00:00+00:00", model="Other"))
        with self.assertRaises(C.UsageError) as e:
            self.b.build()
        self.assertIn("no live handover benchmark with M", str(e.exception))

    def test_measured_load_throughput_is_used_when_present(self):
        self.b.put("tf_bench_a", tf_doc("2026-10-17T20:00:00+00:00"))
        self.b.put("load_old", load_doc("2026-10-17T21:00:00+00:00", per_s=0.1))
        self.b.put("load_new", load_doc("2026-10-17T22:00:00+00:00", per_s=0.5, concurrency=8))
        self.b.put("load_newer_dry", load_doc("2026-10-17T23:00:00+00:00", per_s=99.0, dry=True))
        res = self.b.build()
        o = res["outputs"]
        self.assertTrue(res["measured"]["load_test"]["path"].endswith("load_new/results.json"))
        self.assertEqual((o["capacity_basis"], o["handovers_per_endpoint_hour_at_load_concurrency"], o["load_concurrency"]),
                         ("load test", 1800.0, 8.0))
        self.assertAlmostEqual(o["hours_per_1000_families_per_day"], 2000 / 1800)
        self.assertEqual(o["handovers_per_stream_hour_sequential"], 360.0, "the sequential rate stays beside it")
        cross = self.b.build(crosscheck_every_update=True)   # the load test did not measure judge calls
        self.assertEqual(cross["outputs"]["capacity_basis"], "sequential")
        self.assertTrue(any("without the cross-model check" in n for n in cross["notes"]))

    def test_a_load_test_without_the_keys_leaves_the_model_sequential(self):
        self.b.put("tf_bench_a", tf_doc("2026-10-17T20:00:00+00:00"))
        self.b.put("load_a", {"created_utc": "2026-10-17T21:00:00+00:00", "dry_run": False,
                              "levels": [{"concurrency": 4, "handovers_per_hour": 900}]})
        res = self.b.build()
        load = res["measured"]["load_test"]
        self.assertFalse(load["used"])
        self.assertIn("per_model.M.throughput_handovers_per_s", load["skipped"][0]["reason"])
        self.assertEqual(res["outputs"]["capacity_basis"], "sequential")
        custom = C.build(self.b.root, "M", BASE, "levels.0.handovers_per_hour", "levels.0.concurrency")
        self.assertFalse(custom["measured"]["load_test"]["used"], "a list index is not a key: not read")
        self.b.put("load_b", {"created_utc": "2026-10-17T22:00:00+00:00", "dry_run": False,
                              "summary": {"M": {"per_s": 0.25, "streams": 4}}})
        keyed = C.build(self.b.root, "M", BASE, "summary.{model}.per_s", "summary.{model}.streams")
        self.assertEqual((keyed["outputs"]["capacity_basis"], keyed["outputs"]["handovers_per_endpoint_hour_at_load_concurrency"]),
                         ("load test", 900.0))

    def test_cross_check_cost_only_when_measured(self):
        self.b.put("tf_bench_a", tf_doc("2026-10-17T20:00:00+00:00"))
        none = self.b.build(crosscheck_every_update=True)
        o = none["outputs"]
        self.assertEqual((o["tokens_per_family_per_day"], o["tokens_per_family_per_month"], o["handovers_per_stream_hour_sequential"]),
                         (None, None, None), "not measured: n/a, never estimated")
        self.assertEqual(o["extraction_tokens_per_family_per_day"], 2000.0)
        self.assertTrue(any("its cost is not measured" in n for n in none["notes"]))
        self.b.put("crosscheck_dry", cc_doc("2026-10-17T22:00:00+00:00", dry=True))
        self.assertFalse(self.b.build(crosscheck_every_update=True)["measured"]["crosscheck"]["used"])
        self.b.put("crosscheck_live", cc_doc("2026-10-17T21:00:00+00:00", tokens=500.0, p50=5.0))
        live = self.b.build(crosscheck_every_update=True)["outputs"]
        self.assertEqual((live["tokens_per_update"], live["tokens_per_family_per_day"], live["seconds_per_update_sequential"],
                          live["handovers_per_stream_hour_sequential"]), (1500.0, 3000.0, 15.0, 240.0))
        off = self.b.build()["outputs"]
        self.assertEqual(off["tokens_per_update"], 1000.0, "not cross-checked: the judge is not counted")

    def test_price_is_a_parameter_never_a_default(self):
        self.b.put("tf_bench_a", tf_doc("2026-10-17T20:00:00+00:00"))
        self.assertIsNone(C.DEFAULT_ASSUMPTIONS["price_per_million_tokens"])
        o = self.b.build(price_per_million_tokens=2.0)["outputs"]
        self.assertAlmostEqual(o["cost_per_family_per_month"], 60000 * 2.0 / 1e6)
        self.assertAlmostEqual(o["cost_per_1000_families_per_day"], 2_000_000 * 2.0 / 1e6)

    def test_sensitivity_varies_one_assumption_at_a_time(self):
        self.b.put("tf_bench_a", tf_doc("2026-10-17T20:00:00+00:00"))
        rows = self.b.build()["sensitivity"]
        upd = {r["setting"]: r for r in rows if r["assumption"] == "updates_per_family_per_day"}
        self.assertEqual({k: r["tokens_per_family_per_day"] for k, r in upd.items()}, {"-50%": 1000.0, "base": 2000.0, "+50%": 3000.0})
        fam = {r["setting"]: r for r in rows if r["assumption"] == "families_per_care_coordinator"}
        self.assertEqual({r["tokens_per_family_per_day"] for r in fam.values()}, {2000.0})
        self.assertEqual({k: r["tokens_per_coordinator_per_day"] for k, r in fam.items()},
                         {"-50%": 30000.0, "base": 60000.0, "+50%": 90000.0})
        cc = [(r["setting"], r["value"]) for r in rows if r["assumption"] == "crosscheck_every_update"]
        self.assertEqual(cc, [("base", False), ("flipped", True)])
        self.assertFalse(any(r["assumption"] == "price_per_million_tokens" for r in rows), "no price: nothing to vary")
        priced = self.b.build(price_per_million_tokens=1.0)["sensitivity"]
        self.assertEqual([r["setting"] for r in priced if r["assumption"] == "price_per_million_tokens"], ["-50%", "base", "+50%"])

    def test_bad_assumptions(self):
        self.b.put("tf_bench_a", tf_doc("2026-10-17T20:00:00+00:00"))
        for bad in ({"updates_per_family_per_day": 0}, {"families_per_care_coordinator": "30"},
                    {"crosscheck_every_update": "yes"}, {"price_per_million_tokens": -1}, {"surprise": 1}):
            with self.assertRaises(C.UsageError, msg=bad):
                self.b.build(**bad)

    def run_main(self, *args) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = C.main(["--bench-root", str(self.b.root), "--model", "M", *args])
        return code, out.getvalue(), err.getvalue()

    def test_cli_writes_measured_and_assumed_apart(self):
        self.b.put("tf_bench_a", tf_doc("2026-10-17T20:00:00+00:00"))
        cfg = self.b.root / "assumptions.json"
        cfg.write_text(json.dumps({"updates_per_family_per_day": 3, "families_per_care_coordinator": 10}), encoding="utf-8")
        out = self.b.root / "capacity_x"
        code, stdout, _ = self.run_main("--config", str(cfg), "--families-per-care-coordinator", "20", "--out", str(out))
        self.assertEqual(code, C.EXIT_OK)
        self.assertIn("tokens per family per day 3,000", stdout)
        res = json.loads((out / "results.json").read_text(encoding="utf-8"))
        self.assertEqual((res["assumptions"]["updates_per_family_per_day"]["value"],
                          res["assumptions"]["families_per_care_coordinator"]["value"]), (3, 20.0), "flag over config")
        md = (out / "summary.md").read_text(encoding="utf-8")
        self.assertLess(md.index("## Measured"), md.index("## Assumed"))
        measured = md[md.index("## Measured"):md.index("## Assumed")]
        for item in res["measured"]["tf_bench"]["items"].values():
            self.assertIn(f"| {item['source']} | `{item['key']}` |", measured)
        self.assertNotIn("updates_per_family_per_day", measured, "assumptions are not in the measured table")
        self.assertIn("| price_per_million_tokens | null (tokens only) |", md)
        self.assertIn(C.WORDING, md)
        self.assertIn("## Sensitivity", md)

        code, _, err = self.run_main("--out", str(out))
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("exists", err)
        bad = self.b.root / "bad.json"
        bad.write_text(json.dumps({"price": 1}), encoding="utf-8")
        code, _, err = self.run_main("--config", str(bad), "--out", str(self.b.root / "capacity_y"))
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("unknown assumption", err)
        self.assertFalse((self.b.root / "capacity_y").exists(), "nothing written on a usage error")

    def test_another_host_gets_no_token_factory_wording(self):
        self.b.put("tf_bench_a", tf_doc("2026-10-17T20:00:00+00:00", host="127.0.0.1"))
        res = self.b.build()
        self.assertEqual(res["wording"], "Measured against host 127.0.0.1.")
        self.assertNotIn("AMD Token Factory endpoint provided", C.summary_md(res))
        self.assertTrue(any("not the AMD Token Factory endpoint" in n for n in res["notes"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
