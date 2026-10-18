#!/usr/bin/env python3
"""Concurrency load test of the family timeline's handover call on an OpenAI-compatible endpoint (by default the AMD
Token Factory endpoint of deploy/release.env.example) with the production generator model (DeepSeek-V4-Flash, the
release model): 1, 2, 4 and 8 concurrent requests, N requests per level.

One request is one handover exactly as scripts/bench_tf_handover.py runs a case, imported and not copied: a story update
added to the episode replayed up to it (no model), through episode.llm_extractor over llm_client.OpenAIChat.chat with
the bench's instrumented HTTP layer (bench Session: llm_client's retry and backoff rules, one record per HTTP attempt,
usage as the endpoint returns it) and the bench's settings (bench_tf_handover.new_config: max_tokens 2000, prompted JSON,
timeout, tries). The requests cycle through a fixed small set of story updates (the first --cases, default 4), so every
level sends the same mix. A level runs its N requests on a pool of `concurrency` threads; its wall time runs from the
submission of the first request to the end of the last. Levels run one after another with a pause between them. The
evidence verifier is off (the release setting).

Per request: end-to-end wall time (including retries and backoff waits), HTTP attempts, retries, statuses, 429s, usage
tokens (null when absent, never estimated), success or failure class. Per level: throughput (successful handovers per
minute of level wall time; completion tokens per second of level wall time), latency p50 / p95 with percentile bootstrap
95% intervals (the bench's resamples and seed), error rate and 429 rate with Wilson intervals, and the most requests in
flight at once. The summary says plainly when throughput stops rising and whether the endpoint answered 429 (rate
limited): nothing here measures, or is attributed to, the hardware behind the endpoint, which this client cannot see.

--max-calls (default and ceiling 120) caps the HTTP attempts of the whole run, retries included; when it is reached the
run stops cleanly and writes what it has. The API key is handled as in the bench: it is sent only in the Authorization
header and redacted from every record, output file and printed line; the --api-key-file path is stored as <redacted path>.

Usage:
  python scripts/load_tf_endpoint.py --dry-run --out OUT                        # no network: the bench's scripted fake
  python scripts/load_tf_endpoint.py --api-key-file KEYFILE --out release/benchmarks/load_<UTC>
  python scripts/load_tf_endpoint.py --rate-limit-breakdown DIR    # offline: 429s by code, from DIR/records.jsonl

Writes records.jsonl (appended as it happens), results.json, summary.md and throughput.svg in OUT (which must not
exist). Exit code 0 when every level ran, 3 when it stopped at --max-calls, 130 when interrupted, 2 for a usage problem.
Stdlib only.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import copy
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from xml.sax.saxutils import escape as xml_escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_tf_handover as B  # noqa: E402  the handover call, HTTP layer, settings, redaction, statistics
from episode import Episode, llm_extractor  # noqa: E402  (bench_tf_handover put handoff_day1/agent on sys.path)

SCHEMA_VERSION = "kindredrelay-load-token-factory-v1"
DEFAULT_LEVELS = "1,2,4,8"
DEFAULT_REQUESTS = 16
DEFAULT_CASES = 4
MAX_CALLS_CEILING = 120
DEFAULT_PAUSE_S = 10.0
PLATEAU_GAIN = 1.10   # a step up in concurrency that adds less than 10% throughput: the throughput has stopped rising
SOURCES = B.SOURCES + ("scripts/load_tf_endpoint.py",)
EXIT_OK, EXIT_USAGE, EXIT_PARTIAL, EXIT_INTERRUPTED = B.EXIT_OK, B.EXIT_USAGE, B.EXIT_PARTIAL, B.EXIT_INTERRUPTED


class SharedBudget(B.CallBudget):
    """The bench's call budget, shared by the request threads."""

    def __init__(self, max_calls: int):
        super().__init__(max_calls)
        self._lock = threading.Lock()

    def take(self):
        with self._lock:
            super().take()


class SharedWriter(B.RecordWriter):
    """The bench's records.jsonl writer, one line at a time from any thread."""

    def __init__(self, path: Path, redact):
        super().__init__(path, redact)
        self._lock = threading.Lock()

    def write(self, rec: dict):
        with self._lock:
            super().write(rec)


# ---------------------------------------------------------------------------------------------------------- the run
class LoadTest:
    def __init__(self, cfg: dict, out: Path, *, transport, api_key: str | None, sleep=time.sleep, echo=print,
                 clock=time.perf_counter):
        self.cfg, self.out, self.echo, self.sleep, self.clock = cfg, Path(out), echo, sleep, clock
        self.redact = B.Redactor(api_key)
        self.writer = SharedWriter(self.out / "records.jsonl", self.redact)
        self.budget = SharedBudget(cfg["max_calls"])
        self.stop = threading.Event()
        scenario = B.load_scenario(B.ROOT / cfg["story"])
        self.cases = B.select_cases(scenario, Path(cfg["story"]).stem, len(cfg["case_ids"]))
        if [c["case_id"] for c in self.cases] != cfg["case_ids"]:
            raise B.UsageError("the story's updates do not match the case ids")
        self.contexts = {}
        for c in self.cases:   # the episode before each update, replayed from the recorded extraction (no model)
            ep = Episode(scenario)
            for u in scenario["updates"][:c["index"]]:
                ep.add_update(u, evidence_checker=None)
            self.contexts[c["index"]] = ep

        def session(**ctx):   # the key lives in this closure and the Session, never on this object
            s = B.Session(cfg["base_url"], api_key, transport, self.budget, timeout_s=cfg["timeout_s"],
                          max_tries=cfg["max_tries"], max_wait_s=cfg["max_wait_s"], timeout_retries=cfg["timeout_retries"],
                          backoff_base_s=cfg["backoff_base_s"], sleep=sleep, sink=self.writer.write, redact=self.redact)
            return s, s.begin(**ctx)
        self._session = session

    def __repr__(self):
        return f"LoadTest(host={B.endpoint_host(self.cfg['base_url'])!r})"

    def run_request(self, level: int, index: int, case: dict, ep: Episode, t0: float) -> dict:
        model = self.cfg["model"]
        base = {"type": "request", "model": model, "level": level, "index": index, "case_id": case["case_id"],
                "update_id": case["update"]["update_id"]}
        if self.stop.is_set():   # the budget ran out (or an interruption) before this request started
            rec = {**base, "ts": B.utc_now(), "status": "not_run", "failure_class": None, "start_s": None, "end_s": None,
                   "e2e_s": None, "http_attempts": 0, "retries": 0, "status_429": 0}
            self.writer.write(rec)
            return rec
        sess, meter = self._session(invocation=1, model=model, case_id=case["case_id"], repeat=None, purpose="load",
                                    level=level, request_index=index)
        chat = B.InstrumentedChat(sess, model, guided_json=self.cfg["guided_json"], extra_body=self.cfg["extra_body"])
        update = {k: v for k, v in case["update"].items() if k != "recorded_extraction"}   # the model reads it live
        extractor = llm_extractor(chat)
        entry, exc = None, None
        start = self.clock()
        try:
            entry = ep.add_update(update, extractor=extractor, evidence_checker=None)
        except Exception as e:  # noqa: BLE001 - a model, network or pipeline problem is a measured failure, not a crash
            exc = e
        end = self.clock()
        if isinstance(exc, B.CallBudgetExhausted):
            self.stop.set()
        log = extractor.log[-1] if extractor.log else {}
        fclass = B.failure_class(exc, meter, log)
        status = "aborted" if fclass == "aborted_max_calls" else "failed" if fclass else "ok"
        complete = meter.ok_calls > 0 and meter.usage_missing == 0
        accepted = (entry or {}).get("facts") or []
        rejected = (entry or {}).get("rejected") or []
        rec = {**base, "ts": B.utc_now(), "status": status, "failure_class": fclass,
               "error": self.redact(f"{type(exc).__name__}: {exc}")[:500] if exc is not None else None,
               "start_s": round(start - t0, 4), "end_s": round(end - t0, 4), "e2e_s": round(end - start, 4),
               "e2e_excl_wait_s": round(max(0.0, end - start - meter.wait_s), 4),
               "http_attempts": meter.attempts, "retries": meter.retries, "retry_wait_s": round(meter.wait_s, 3),
               "statuses": meter.statuses, "status_429": meter.statuses.get("429", 0),
               "prompt_tokens": meter.prompt_tokens if complete else None,
               "completion_tokens": meter.completion_tokens if complete else None,
               "total_tokens": meter.prompt_tokens + meter.completion_tokens if complete else None,
               "usage_complete": complete, "reply_parsed": log.get("parsed"), "finish_reason": log.get("finish_reason"),
               "facts_proposed": len(accepted) + len(rejected) if entry is not None else 0,
               "facts_accepted": len(accepted)}
        self.writer.write(rec)
        return rec

    def run_level(self, level: int) -> list[dict]:
        n = self.cfg["requests_per_level"]
        plan = [(i, self.cases[i % len(self.cases)]) for i in range(n)]
        eps = [copy.deepcopy(self.contexts[c["index"]]) for _, c in plan]   # copied before the clock starts
        self.writer.write({"type": "level_start", "ts": B.utc_now(), "level": level, "requests": n})
        t0 = self.clock()
        pool = cf.ThreadPoolExecutor(max_workers=level, thread_name_prefix=f"load{level}")
        try:
            futs = [pool.submit(self.run_request, level, i, c, ep, t0) for (i, c), ep in zip(plan, eps)]
            recs = [f.result() for f in futs]
        except KeyboardInterrupt:
            self.stop.set()   # requests not yet started are recorded as not_run; running ones finish
            raise
        finally:
            pool.shutdown(wait=True)
            wall = self.clock() - t0
            self.writer.write({"type": "level_end", "ts": B.utc_now(), "level": level, "wall_s": round(wall, 4),
                               "http_calls_so_far": self.budget.used})
        return recs

    def run(self) -> str | None:
        levels = self.cfg["levels"]
        self.echo(f"{len(levels)} levels x {self.cfg['requests_per_level']} requests of {self.cfg['model']}; "
                  f"at most {self.cfg['max_calls']} HTTP calls")
        for k, level in enumerate(levels):
            if self.stop.is_set():
                break
            if k and self.cfg["pause_s"]:
                self.sleep(self.cfg["pause_s"])
            recs = self.run_level(level)
            ok = [r for r in recs if r["status"] == "ok"]
            n429 = sum(r["status_429"] for r in recs)
            p50 = B.median([r["e2e_s"] for r in ok])
            self.echo(f"concurrency {level}: {len(ok)}/{len(recs)} ok, p50 {B.fmt(B.rnd(p50), ' s')}, "
                      f"{sum(r['retries'] for r in recs)} retries, {n429} x 429")
        if self.stop.is_set():
            self.echo(f"stopped: --max-calls {self.cfg['max_calls']} reached")
            return "max_calls"
        return None


# ---------------------------------------------------------------------------------------------------------- summary
def max_in_flight(recs: list[dict]) -> int:
    """The most requests running at the same moment (start and end offsets; an end before a start at the same time)."""
    events = sorted([(r["start_s"], 1) for r in recs if r.get("start_s") is not None]
                    + [(r["end_s"], -1) for r in recs if r.get("end_s") is not None])
    now = top = 0
    for _, d in events:
        now += d
        top = max(top, now)
    return top


def p95(xs):
    return B.percentile(xs, 95)


def summarize_level(level: int, reqs: list[dict], https: list[dict], wall_s: float | None) -> dict:
    done = [r for r in reqs if r["status"] in ("ok", "failed")]
    ok = [r for r in reqs if r["status"] == "ok"]
    failed = [r for r in reqs if r["status"] == "failed"]
    lat = [r["e2e_s"] for r in ok]
    with_usage = [r for r in ok if isinstance(r.get("completion_tokens"), int)]
    ct = sum(r["completion_tokens"] for r in with_usage)
    failures: dict[str, int] = {}
    for r in failed:
        failures[r["failure_class"]] = failures.get(r["failure_class"], 0) + 1
    statuses: dict[str, int] = {}
    for h in https:
        statuses[str(h.get("status"))] = statuses.get(str(h.get("status")), 0) + 1
    n429 = sum(1 for h in https if h.get("status") == 429)
    calls = [h["wall_s"] for h in https if h.get("outcome") == "ok"]
    usage_ok = bool(ok) and len(with_usage) == len(ok)
    return {
        "concurrency": level, "requests": len(reqs), "completed": len(done), "ok": len(ok), "failed": len(failed),
        "aborted": sum(1 for r in reqs if r["status"] == "aborted"),
        "not_run": sum(1 for r in reqs if r["status"] == "not_run"),
        "wall_s": B.rnd(wall_s), "max_in_flight": max_in_flight(reqs),
        "throughput": {"handovers_per_min": B.rnd(len(ok) / wall_s * 60, 3) if wall_s else None,
                       "completion_tokens_per_s": B.rnd(ct / wall_s, 2) if wall_s and usage_ok else None,
                       "completion_tokens": ct if usage_ok else None, "ok_without_usage": len(ok) - len(with_usage)},
        "latency_s": {"n": len(lat), "p50": B.rnd(B.median(lat)), "p95": B.rnd(p95(lat)), "mean": B.rnd(B.mean(lat)),
                      "min": B.rnd(min(lat)) if lat else None, "max": B.rnd(max(lat)) if lat else None,
                      "p50_ci95": B.bootstrap_ci(lat, B.median, key=f"load:{level}:p50"),
                      "p95_ci95": B.bootstrap_ci(lat, p95, key=f"load:{level}:p95"),
                      "p50_excluding_retry_waits": B.rnd(B.median([r.get("e2e_excl_wait_s") for r in ok]))},
        "call_latency_s": {"n": len(calls), "p50": B.rnd(B.median(calls)), "p95": B.rnd(p95(calls))},
        "tokens_per_handover": {"prompt_mean": B.rnd(B.mean([r["prompt_tokens"] for r in with_usage]), 1),
                                "completion_mean": B.rnd(B.mean([r["completion_tokens"] for r in with_usage]), 1)},
        "errors": {"count": len(failed), "rate": B.rnd(len(failed) / len(done)) if done else None,
                   "wilson95": B.wilson95(len(failed), len(done)), "failures": failures},
        "http": {"attempts": len(https), "retries": sum(1 for h in https if h["attempt"] > 1), "statuses": statuses,
                 "status_429": n429, "rate_429": B.rnd(n429 / len(https)) if https else None,
                 "wilson95_429": B.wilson95(n429, len(https)),
                 "retry_wait_s": B.rnd(sum(h.get("wait_s") or 0.0 for h in https), 3)},
    }


def capacity_note(levels: list[dict], dry_run: bool) -> str:
    """What the throughput curve does and does not show, in plain words."""
    if dry_run:
        return ("Dry run: the replies came from a scripted fake transport, so the curve exercises the harness only and "
                "says nothing about any endpoint's capacity.")
    thr = [(lv["concurrency"], lv["throughput"]["handovers_per_min"]) for lv in levels]
    if not thr or any(t is None for _, t in thr):
        return "At least one level has no throughput (no successful handover or no wall time): no capacity statement."
    limited = [lv["concurrency"] for lv in levels if lv["http"]["status_429"]]
    flat = [c2 for (c1, t1), (c2, t2) in zip(thr, thr[1:]) if t2 < PLATEAU_GAIN * t1]
    gain = thr[-1][1] / thr[0][1] if thr[0][1] else None
    out = []
    if gain is not None:
        out.append(f"Successful handovers per minute went from {thr[0][1]:.2f} at concurrency {thr[0][0]} to "
                   f"{thr[-1][1]:.2f} at concurrency {thr[-1][0]} ({gain:.2f}x for {thr[-1][0] / thr[0][0]:g}x the "
                   "concurrent requests).")
    if limited:
        out.append(f"The endpoint answered HTTP 429 (rate limited) at concurrency {', '.join(map(str, limited))}: "
                   "throughput there is bounded by the rate limit applied to this API key and by the client's backoff "
                   "(2, 4, 8, ... s or Retry-After), not by the speed of the serving hardware, which this client cannot see.")
    if flat:
        cause = ("it coincides with HTTP 429 responses, so it is read as rate limiting"
                 if any(c in limited for c in flat) else
                 "no HTTP 429 was returned there; the cause is not visible from this client (server-side queueing or "
                 "limits, batching, or the network path) and no hardware capacity is inferred from it")
        out.append(f"Throughput stopped rising (less than +{(PLATEAU_GAIN - 1) * 100:.0f}% over the previous level) at "
                   f"concurrency {', '.join(map(str, flat))}; {cause}.")
    else:
        out.append(f"Throughput rose at every step up to concurrency {thr[-1][0]}: the endpoint's limit for this request "
                   "shape was not reached at these levels.")
    return " ".join(out)


def best_level(levels: list[dict]) -> dict:
    """The level with the most successful handovers per second of level wall time (ties: the lower concurrency), as
    scripts/capacity_model.py reads it; null values when no level had a successful handover."""
    rated = [lv for lv in levels if lv["throughput"]["handovers_per_min"]]
    best = max(rated, key=lambda lv: (lv["throughput"]["handovers_per_min"], -lv["concurrency"]), default=None)
    return {"throughput_handovers_per_s": B.rnd(best["throughput"]["handovers_per_min"] / 60, 5) if best else None,
            "concurrency": best["concurrency"] if best else None,
            "selected_by": "the level with the most successful handovers per second of level wall time (ties: the "
                           "lower concurrency); throughput counts successful handovers over all concurrent streams",
            "rate_limited_at_selected_level": bool(best["http"]["status_429"]) if best else None,
            "levels": levels}


def build_results(records: list[dict], argv: list[str], stopped_reason: str | None) -> dict:
    start = next(r for r in records if r["type"] == "run_start")
    cfg = start["config"]
    inv = next((r for r in records if r["type"] == "invocation"), {})
    https = [r for r in records if r["type"] == "http"]
    ends = {r["level"]: r["wall_s"] for r in records if r["type"] == "level_end"}
    levels = []
    for level in cfg["levels"]:
        reqs = [r for r in records if r["type"] == "request" and r["level"] == level]
        if not reqs:
            continue
        levels.append(summarize_level(level, reqs, [h for h in https if h.get("level") == level], ends.get(level)))
    base = levels[0]["throughput"]["handovers_per_min"] if levels else None
    for lv in levels:
        t = lv["throughput"]["handovers_per_min"]
        lv["throughput"]["speedup_vs_first_level"] = B.rnd(t / base, 3) if base and t is not None else None
    return {
        # scripts/capacity_model.py reads per_model.<model>.throughput_handovers_per_s and .concurrency
        "per_model": {cfg["model"]: best_level(levels)},
        "schema_version": SCHEMA_VERSION, "created_utc": B.utc_now(), "git": inv.get("git"), "argv": argv,
        "dry_run": cfg["dry_run"], "model": cfg["model"],
        "endpoint": {"host": B.endpoint_host(cfg["base_url"]), "transport": cfg["transport"],
                     "is_token_factory_default": B.endpoint_host(cfg["base_url"]) == B.TOKEN_FACTORY_HOST},
        "pipeline": {
            "request_unit": "one handover as scripts/bench_tf_handover.py runs a case: one story update added after the "
                            "earlier updates were replayed from their recorded extraction; episode.llm_extractor over "
                            "llm_client.OpenAIChat.chat with the bench's instrumented HTTP layer",
            "story": cfg["story"], "story_sha256": cfg["story_sha256"], "update_cycle": cfg["case_ids"],
            "max_tokens": cfg["max_tokens"], "guided_json": cfg["guided_json"], "timeout_s": cfg["timeout_s"],
            "max_tries": cfg["max_tries"], "max_wait_s": cfg["max_wait_s"], "timeout_retries": cfg["timeout_retries"],
            "backoff_base_s": cfg["backoff_base_s"], "extra_body": cfg["extra_body"], "verifier": "off",
            "connection": "one HTTPS connection per attempt (urllib), as the bench's transport"},
        "design": {"levels": cfg["levels"], "requests_per_level": cfg["requests_per_level"], "pause_s": cfg["pause_s"],
                   "max_calls": cfg["max_calls"], "marker": cfg.get("marker"),
                   "marker_window_utc": [r["ts"] for r in records if r["type"] == "marker"],
                   "level_wall": "from the submission of the level's first request to the end of its last",
                   "throughput": "successful handovers / level wall time; completion tokens (usage, successful "
                                 "requests) / level wall time, null when a successful request has no usage"},
        "stopped_reason": stopped_reason,
        "http_calls": {"total": len(https), "retries": sum(1 for h in https if h["attempt"] > 1),
                       "status_429": sum(1 for h in https if h.get("status") == 429)},
        "levels": levels, "capacity_note": capacity_note(levels, cfg["dry_run"]),
        "source_sha256": inv.get("source_sha256"),
        "statistics": {"percentile": "linear interpolation between closest ranks",
                       "bootstrap": {"resamples": B.BOOTSTRAP_RESAMPLES, "seed": B.BOOTSTRAP_SEED, "min_n": B.BOOTSTRAP_MIN_N,
                                     "interval": "percentile 2.5 / 97.5", "unit": "successful request of the level"},
                       "wilson": "z = 1.959964; error rate over completed requests, 429 rate over HTTP attempts",
                       "latency_population": "successful requests; e2e includes retries and backoff waits",
                       "tokens": "as returned in usage; null when absent, never estimated"},
    }


def validate_results(obj) -> list[str]:
    errs: list[str] = []
    if not isinstance(obj, dict):
        return ["results is not an object"]
    if obj.get("schema_version") != SCHEMA_VERSION:
        errs.append("schema_version")
    for k, t in (("argv", list), ("dry_run", bool), ("endpoint", dict), ("levels", list), ("http_calls", dict),
                 ("capacity_note", str), ("model", str)):
        if not isinstance(obj.get(k), t):
            errs.append(f"{k} missing or not {t.__name__}")
    if errs:
        return errs
    if "://" in obj["endpoint"].get("host", "") or "/" in obj["endpoint"].get("host", ""):
        errs.append("endpoint is not host only")
    pm = (obj.get("per_model") or {}).get(obj["model"])
    if not isinstance(pm, dict) or not {"throughput_handovers_per_s", "concurrency"} <= set(pm):
        errs.append("per_model.<model> lacks throughput_handovers_per_s / concurrency")
    for lv in obj["levels"]:
        p = f"level {lv.get('concurrency')}"
        if lv["ok"] + lv["failed"] != lv["completed"] or lv["completed"] + lv["aborted"] + lv["not_run"] != lv["requests"]:
            errs.append(f"{p}: request counts do not add up")
        lat = lv["latency_s"]
        if lat["p50"] is not None and lat["p95"] < lat["p50"]:
            errs.append(f"{p}: p95 < p50")
        for name in ("p50_ci95", "p95_ci95"):
            ci = lat[name]
            if ci is not None and not (isinstance(ci, list) and len(ci) == 2 and ci[0] <= ci[1]):
                errs.append(f"{p}: {name}")
        if lv["max_in_flight"] > lv["concurrency"]:
            errs.append(f"{p}: more requests in flight than threads")
    return errs


# ---------------------------------------------------------------------------------------------------------- reports
def summary_md(res: dict) -> str:
    host, dry = res["endpoint"]["host"], res["dry_run"]
    git, pl, de = res.get("git") or {}, res["pipeline"], res["design"]
    L = [f"# Endpoint load test: `{res['model']}` at concurrency {', '.join(map(str, de['levels']))}", "",
         B.endpoint_wording(host, dry), "",
         f"- Created (UTC): {res['created_utc']}; git {str(git.get('head'))[:12]}"
         + (" (uncommitted changes in tracked files)" if git.get("dirty") else ""),
         f"- One request: {pl['request_unit']}. Updates cycled: {', '.join(c.rsplit('/', 1)[-1] for c in pl['update_cycle'])} "
         f"({pl['story']}); {de['requests_per_level']} requests per level, {de['pause_s']:g} s pause between levels; "
         f"settings: max_tokens {pl['max_tokens']}, {'guided' if pl['guided_json'] else 'prompted'} JSON, timeout "
         f"{pl['timeout_s']:g} s, {pl['max_tries']} tries (llm_client's backoff), extra body {json.dumps(pl['extra_body'])}, "
         f"evidence verifier off.",
         f"- HTTP calls: {res['http_calls']['total']} ({res['http_calls']['retries']} retries, "
         f"{res['http_calls']['status_429']} answered 429) of at most {de['max_calls']}."
         + (f" **Stopped early: {res['stopped_reason']}; later levels did not run.**" if res["stopped_reason"] else ""), "",
         "| Concurrency | ok / requests | level wall | max in flight | handovers / min | x first level | "
         "completion tok/s | latency p50 [95% CI] | latency p95 [95% CI] | errors [Wilson 95%] | 429s / attempts "
         "[Wilson 95%] | retries |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for lv in res["levels"]:
        t, lat, e, h = lv["throughput"], lv["latency_s"], lv["errors"], lv["http"]
        L.append(f"| {lv['concurrency']} | {lv['ok']}/{lv['requests']} | {B.fmt(lv['wall_s'], ' s', 1)} | "
                 f"{lv['max_in_flight']} | {B.fmt(t['handovers_per_min'])} | {B.fmt(t['speedup_vs_first_level'], 'x')} | "
                 f"{B.fmt(t['completion_tokens_per_s'], '', 1)} | {B.fmt(lat['p50'], ' s')}{B.fmt_ci(lat['p50_ci95'])} | "
                 f"{B.fmt(lat['p95'], ' s')}{B.fmt_ci(lat['p95_ci95'])} | {e['count']}/{lv['completed']}"
                 f"{B.fmt_ci(e['wilson95'])} | {h['status_429']}/{h['attempts']}{B.fmt_ci(h['wilson95_429'])} | "
                 f"{h['retries']} |")
    best = res["per_model"][res["model"]]
    L += ["", "## What the curve shows", "", res["capacity_note"], "",
          f"Highest throughput: {B.fmt(best['throughput_handovers_per_s'], ' successful handovers/s', 4)} at concurrency "
          f"{B.fmt(best['concurrency'])}" + (" (with HTTP 429 at that level)" if best["rate_limited_at_selected_level"] else "")
          + " (results.json `per_model`, read by scripts/capacity_model.py).", "", "## Per level", ""]
    for lv in res["levels"]:
        fails = ", ".join(f"{k} {v}" for k, v in lv["errors"]["failures"].items()) or "none"
        L.append(f"- Concurrency {lv['concurrency']}: latency mean {B.fmt(lv['latency_s']['mean'], ' s')}, min "
                 f"{B.fmt(lv['latency_s']['min'], ' s')}, max {B.fmt(lv['latency_s']['max'], ' s')}, p50 without retry "
                 f"waits {B.fmt(lv['latency_s']['p50_excluding_retry_waits'], ' s')}; successful call p50 / p95 "
                 f"{B.fmt(lv['call_latency_s']['p50'], ' s')} / {B.fmt(lv['call_latency_s']['p95'], ' s')}; tokens per "
                 f"handover: prompt {B.fmt(lv['tokens_per_handover']['prompt_mean'], '', 0)}, completion "
                 f"{B.fmt(lv['tokens_per_handover']['completion_mean'], '', 0)}; failures: {fails}; aborted "
                 f"{lv['aborted']}, not run {lv['not_run']}; HTTP statuses "
                 f"{', '.join(f'{k}: {v}' for k, v in lv['http']['statuses'].items()) or 'none'}; retry waits "
                 f"{B.fmt(lv['http']['retry_wait_s'], ' s', 1)}.")
    L += ["", "Notes: throughput is per level wall time (first submission to last end), so it includes retries and "
          "backoff waits; completion tokens are the endpoint's `usage` (n/a where a successful request had none, never "
          "estimated); latency covers successful requests. With "
          f"{de['requests_per_level']} requests per level the p95 is close to the slowest request and its interval is "
          "wide. Each attempt opens its own HTTPS connection, as the bench's transport does. The same few prompts are "
          "repeated, so any prompt caching on the endpoint (not visible to this client) helps every level alike. "
          + (f"Other clients of this API key were asked to pause while the marker file `{de['marker']}` existed "
             f"({' to '.join(de['marker_window_utc']) or 'never created'}); that is a request, not an enforced lock. Outside "
             "that window other clients may share the key, and other users may share the endpoint at any time; "
             if de.get("marker") else
             "The API key may be in use by other clients at the same time, and other users may share the endpoint; ")
          + "429s and latencies are the endpoint and key as seen during the run. The story is the fictional demo "
          "episode; these are engineering measurements, not clinical validation.", ""]
    return "\n".join(L)


def throughput_svg(res: dict) -> str:
    levels = res["levels"]
    width, height, top, bottom = 980, 400, 70, 330
    panels = [(70, 450, "successful handovers / min (dashed: first level x concurrency)"),
              (560, 940, "latency, s (dot p50 with 95% CI, tick p95)")]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
           'font-family="Helvetica, Arial, sans-serif" font-size="12">',
           f'<rect width="{width}" height="{height}" fill="white"/>',
           f'<text x="20" y="24" font-size="15" font-weight="bold">{xml_escape("Handover requests at increasing concurrency: " + res["model"])}</text>',
           f'<text x="20" y="44" fill="#555">{xml_escape(("DRY RUN, fake transport: not a measurement. " if res["dry_run"] else "") + "Endpoint " + res["endpoint"]["host"] + "; red = the endpoint answered HTTP 429 at that level")}</text>']
    if not levels:
        out.append('<text x="20" y="80">no level ran</text></svg>')
        return "\n".join(out) + "\n"
    n = len(levels)

    def xs(x0, x1):
        return [x0 + (x1 - x0) * (i + 0.5) / n for i in range(n)]

    def axis(x0, x1, vmax, label):
        vmax = vmax if vmax > 0 else 1.0
        out.append(f'<text x="{x0}" y="{top - 12}" fill="#555">{xml_escape(label)}</text>')
        for k in range(5):
            v = vmax * k / 4
            y = bottom - (bottom - top) * k / 4
            out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="#eee"/>')
            out.append(f'<text x="{x0 - 6}" y="{y + 4:.1f}" text-anchor="end" fill="#555">{v:.3g}</text>')
        out.append(f'<line x1="{x0}" y1="{bottom}" x2="{x1}" y2="{bottom}" stroke="#333"/>')
        for x, lv in zip(xs(x0, x1), levels):
            out.append(f'<text x="{x:.1f}" y="{bottom + 16}" text-anchor="middle">{lv["concurrency"]}</text>')
        out.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{bottom + 34}" text-anchor="middle">concurrent requests</text>')
        return lambda v: bottom - (bottom - top) * (v / vmax)

    (a0, a1, la), (b0, b1, lb) = panels
    thr = [lv["throughput"]["handovers_per_min"] for lv in levels]
    first = thr[0]
    ideal = [first * lv["concurrency"] / levels[0]["concurrency"] if first else None for lv in levels]
    y = axis(a0, a1, max([t for t in thr + ideal if t] + [0.0]) * 1.1, la)
    pts = [(x, t, lv) for x, t, lv in zip(xs(a0, a1), thr, levels) if t is not None]
    ipts = [(x, v) for x, v in zip(xs(a0, a1), ideal) if v is not None]
    if len(ipts) > 1:
        out.append('<polyline fill="none" stroke="#999" stroke-dasharray="5,4" points="'
                   + " ".join(f"{x:.1f},{y(v):.1f}" for x, v in ipts) + '"/>')
    if len(pts) > 1:
        out.append('<polyline fill="none" stroke="#4a78b0" stroke-width="2" points="'
                   + " ".join(f"{x:.1f},{y(t):.1f}" for x, t, _ in pts) + '"/>')
    for x, t, lv in pts:
        colour = "#b04a4a" if lv["http"]["status_429"] else "#1f3f6b"
        out.append(f'<circle cx="{x:.1f}" cy="{y(t):.1f}" r="5" fill="{colour}"/>')
        out.append(f'<text x="{x:.1f}" y="{y(t) - 10:.1f}" text-anchor="middle">{t:.2f}</text>')
    lat = [lv["latency_s"] for lv in levels]
    vmax = max([v for s in lat for v in [s["p95"], *(s["p50_ci95"] or [])] if v is not None] + [0.0]) * 1.1
    y = axis(b0, b1, vmax, lb)
    for x, s, lv in zip(xs(b0, b1), lat, levels):
        if s["p50"] is None:
            continue
        colour = "#b04a4a" if lv["http"]["status_429"] else "#1f3f6b"
        if s["p50_ci95"]:
            lo, hi = s["p50_ci95"]
            out.append(f'<line x1="{x:.1f}" y1="{y(lo):.1f}" x2="{x:.1f}" y2="{y(hi):.1f}" stroke="{colour}" stroke-width="2"/>')
        out.append(f'<circle cx="{x:.1f}" cy="{y(s["p50"]):.1f}" r="5" fill="{colour}"/>')
        out.append(f'<line x1="{x - 10:.1f}" y1="{y(s["p95"]):.1f}" x2="{x + 10:.1f}" y2="{y(s["p95"]):.1f}" '
                   'stroke="#b04a4a" stroke-width="2"/>')
        out.append(f'<text x="{x + 12:.1f}" y="{y(s["p50"]) + 4:.1f}" fill="#555">{s["p50"]:.1f}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_outputs(out: Path, redact, argv: list[str], stopped_reason: str | None) -> dict:
    skipped: list[int] = []
    records = B.read_records(out / "records.jsonl", skipped)
    res = build_results(records, argv, stopped_reason)
    res["records_skipped_lines"] = skipped
    errs = validate_results(res)
    if errs:
        raise ValueError("results.json would not be valid: " + "; ".join(errs))
    for name, text in (("results.json", json.dumps(res, indent=2, ensure_ascii=False) + "\n"),
                       ("summary.md", summary_md(res)), ("throughput.svg", throughput_svg(res))):
        (out / name).write_text(redact(text), encoding="utf-8")
    B.scrub_outputs(out, redact)
    return res


# ---------------------------------------------------------------------------------------------------------- 429 breakdown
BREAKDOWN_SCHEMA = "kindredrelay-load-rate-limit-breakdown-v1"
BREAKDOWN_FILES = ("rate_limit_breakdown.json", "rate_limit_breakdown.md")
CODE_RE = re.compile(r'"code"\s*:\s*"([^"]+)"')
MESSAGE_RE = re.compile(r'"message"\s*:\s*"([^"]+)"')


def rate_limit_reason(body) -> tuple[str, str | None]:
    """The error code and message of a 429 reply body as the record keeps it (redacted, at most 300 characters):
    error.code / detail.error.code when the body parses, else the first "code" / "message" in the text."""
    text = body if isinstance(body, str) else ""
    try:
        obj = json.loads(text)
    except ValueError:
        obj = None
    err = None
    if isinstance(obj, dict):
        detail = obj.get("detail")
        err = obj.get("error") or (detail.get("error") if isinstance(detail, dict) else None)
    if isinstance(err, dict) and (err.get("code") or err.get("message")):
        return str(err.get("code") or "no code"), err.get("message")
    code, msg = CODE_RE.search(text), MESSAGE_RE.search(text)
    return (code.group(1) if code else "no code"), (msg.group(1) if msg else (text[:120] or None))


def rate_limit_breakdown(folder: Path) -> dict:
    """Per level, the HTTP 429 attempts of a finished load run by error code and message, with their times, from its
    records.jsonl only (no call, nothing else read or rewritten)."""
    path = folder / "records.jsonl"
    if not path.is_file():
        raise B.UsageError(f"{path} not found")
    skipped: list[int] = []
    records = B.read_records(path, skipped)
    start = next((r for r in records if r.get("type") == "run_start"), None)
    if start is None or start.get("schema_version") != SCHEMA_VERSION:
        raise B.UsageError(f"{path} was not written by scripts/load_tf_endpoint.py")
    cfg = start["config"]
    https = [r for r in records if r.get("type") == "http"]
    windows = {(r["type"], r["level"]): r["ts"] for r in records if r.get("type") in ("level_start", "level_end")}
    levels = []
    for level in cfg["levels"]:
        att = [h for h in https if h.get("level") == level]
        hits = [h for h in att if h.get("status") == 429]
        codes: dict[str, dict] = {}
        for h in hits:
            code, msg = rate_limit_reason(h.get("body"))
            c = codes.setdefault(code, {"count": 0, "messages": {}, "first_ts": h["ts"], "last_ts": h["ts"]})
            c["count"] += 1
            c["messages"][str(msg)] = c["messages"].get(str(msg), 0) + 1
            c["first_ts"], c["last_ts"] = min(c["first_ts"], h["ts"]), max(c["last_ts"], h["ts"])
        levels.append({
            "concurrency": level, "level_start_utc": windows.get(("level_start", level)),
            "level_end_utc": windows.get(("level_end", level)), "attempts": len(att), "status_429": len(hits),
            "by_code": dict(sorted(codes.items(), key=lambda kv: (-kv[1]["count"], kv[0]))),
            "events": [{"ts": h["ts"], "request_index": h.get("request_index"), "attempt": h.get("attempt"),
                        "code": rate_limit_reason(h.get("body"))[0], "retry_after": h.get("retry_after"),
                        "wait_s": h.get("wait_s")} for h in sorted(hits, key=lambda h: h["ts"])]})
    totals: dict[str, int] = {}
    for lv in levels:
        for code, c in lv["by_code"].items():
            totals[code] = totals.get(code, 0) + c["count"]
    return {"schema_version": BREAKDOWN_SCHEMA, "derived_utc": B.utc_now(), "derived_after_run": True,
            "note": "derived after the run from records.jsonl alone (the HTTP records' redacted 429 bodies, at most 300 "
                    "characters each); no model or endpoint was called and results.json / summary.md were not changed",
            "source": {"records_jsonl": B.rel(path), "sha256": B.file_sha(path), "lines_skipped": skipped},
            "run": {"model": cfg.get("model"), "dry_run": cfg.get("dry_run"), "run_start_utc": start.get("ts"),
                    "host": B.endpoint_host(cfg["base_url"])},
            "totals": {"attempts": len(https), "status_429": sum(lv["status_429"] for lv in levels),
                       "by_code": dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))},
            "levels": levels}


def breakdown_md(bd: dict) -> str:
    L = [f"# HTTP 429 breakdown: `{bd['run']['model']}` load run", "",
         f"Derived after the run ({bd['derived_utc']}) from `{bd['source']['records_jsonl']}` (sha256 "
         f"`{bd['source']['sha256']}`) only: {bd['note']}."
         + (" DRY RUN: the replies came from a scripted fake transport." if bd["run"]["dry_run"] else ""), "",
         f"- Run started (UTC) {bd['run']['run_start_utc']}, endpoint host {bd['run']['host']}; "
         f"{bd['totals']['status_429']} of {bd['totals']['attempts']} HTTP attempts answered 429: "
         + (", ".join(f"{v} x `{k}`" for k, v in bd["totals"]["by_code"].items()) or "none") + ".", "",
         "| Concurrency | level window (UTC) | 429s / attempts | by code (message) | first / last 429 (UTC) |",
         "|---|---|---|---|---|"]
    for lv in bd["levels"]:
        codes = "; ".join(f"{c['count']} x `{k}` ("
                          + ", ".join(f"{m}" + (f" x{n}" if len(c["messages"]) > 1 else "") for m, n in c["messages"].items())
                          + ")" for k, c in lv["by_code"].items()) or "none"
        ev = lv["events"]
        L.append(f"| {lv['concurrency']} | {lv['level_start_utc']} to {lv['level_end_utc']} | {lv['status_429']}/"
                 f"{lv['attempts']} | {codes} | " + (f"{ev[0]['ts']} / {ev[-1]['ts']}" if ev else "n/a") + " |")
    L += ["", "Every 429 (time, request, attempt, code, Retry-After, wait before the retry):", ""]
    for lv in bd["levels"]:
        for e in lv["events"]:
            L.append(f"- concurrency {lv['concurrency']}: {e['ts']} request {e['request_index']} attempt {e['attempt']} "
                     f"`{e['code']}` Retry-After {e['retry_after']} wait {e['wait_s']} s")
    if not any(lv["events"] for lv in bd["levels"]):
        L.append("- none")
    return "\n".join(L) + "\n"


def write_breakdown(folder: Path) -> dict:
    """rate_limit_breakdown.json and .md next to the run's outputs; refused when either exists (never rewritten)."""
    folder = Path(folder)
    for name in BREAKDOWN_FILES:
        if (folder / name).exists():
            raise B.UsageError(f"{folder / name} exists; it is not rewritten")
    bd = rate_limit_breakdown(folder)
    redact = B.Redactor(None)
    (folder / BREAKDOWN_FILES[0]).write_text(redact(json.dumps(bd, indent=2, ensure_ascii=False) + "\n"), encoding="utf-8")
    (folder / BREAKDOWN_FILES[1]).write_text(redact(breakdown_md(bd)), encoding="utf-8")
    return bd


# ---------------------------------------------------------------------------------------------------------- CLI
def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None, help="new output folder (must not exist)")
    ap.add_argument("--rate-limit-breakdown", default=None, metavar="DIR",
                    help="no run: write rate_limit_breakdown.json / .md in a finished load folder from its records.jsonl")
    ap.add_argument("--model", default=None, help="model id (default: the release model of deploy/release.env.example)")
    ap.add_argument("--levels", default=DEFAULT_LEVELS, help=f"comma-separated concurrency levels (default {DEFAULT_LEVELS})")
    ap.add_argument("--requests-per-level", type=int, default=DEFAULT_REQUESTS,
                    help=f"handover requests per level (default {DEFAULT_REQUESTS})")
    ap.add_argument("--cases", type=int, default=DEFAULT_CASES, help="cycle through the story's first N updates "
                                                                     f"(default {DEFAULT_CASES})")
    ap.add_argument("--max-calls", type=int, default=MAX_CALLS_CEILING,
                    help=f"hard cap on HTTP calls of the run, retries included (default and ceiling {MAX_CALLS_CEILING})")
    ap.add_argument("--pause-s", type=float, default=DEFAULT_PAUSE_S, help="pause between levels (default 10)")
    ap.add_argument("--api-key-file", default=None, help="file holding only the API key (else CARERELAY_LLM_API_KEY)")
    ap.add_argument("--base-url", default=None, help="OpenAI-compatible base URL ending in /v1 (default: "
                                                     "CARERELAY_LLM_BASE_URL, else deploy/release.env.example)")
    ap.add_argument("--marker", default=None, metavar="FILE",
                    help="an empty file created just before the first level and removed when the run ends (also on an "
                         "error or an interruption), so other clients of the same key can pause meanwhile; refused if it "
                         "exists")
    ap.add_argument("--dry-run", action="store_true", help="no network: the bench's deterministic scripted fake")
    ap.add_argument("--story", default=None, help="episode story JSON (default: CARERELAY_STORY, else the demo story)")
    ap.add_argument("--max-tries", type=int, default=None, help="tries per request (default CARERELAY_LLM_MAX_TRIES or 6)")
    ap.add_argument("--max-wait-s", type=float, default=None, help="cap of one backoff wait (default 60)")
    ap.add_argument("--timeout-s", type=float, default=None, help="per-attempt timeout (default: as the bench)")
    return ap.parse_args(argv)


def new_config(args, env, defaults, transport_name: str) -> dict:
    try:
        levels = [int(x) for x in args.levels.split(",") if x.strip()]
    except ValueError:
        raise B.UsageError("--levels must be comma-separated whole numbers") from None
    if not levels or any(c < 1 for c in levels) or len(set(levels)) != len(levels):
        raise B.UsageError("--levels must name distinct concurrency levels of at least 1")
    if args.requests_per_level < 1:
        raise B.UsageError("--requests-per-level must be at least 1")
    if not 1 <= args.max_calls <= MAX_CALLS_CEILING:
        raise B.UsageError(f"--max-calls must be between 1 and {MAX_CALLS_CEILING}")
    planned = len(levels) * args.requests_per_level
    if planned > args.max_calls:
        raise B.UsageError(f"{len(levels)} levels x {args.requests_per_level} requests = {planned} requests do not fit in "
                           f"--max-calls {args.max_calls}")
    if args.pause_s < 0:
        raise B.UsageError("--pause-s must be at least 0")
    model = args.model or defaults.get("CARERELAY_LLM_MODEL") or B.FALLBACK_MODEL
    bench_args = argparse.Namespace(models=model, repeats=1, ttft_probe=0, max_calls=args.max_calls, story=args.story,
                                    cases=args.cases, dry_run=args.dry_run, base_url=args.base_url,
                                    timeout_s=args.timeout_s, max_tries=args.max_tries, max_wait_s=args.max_wait_s)
    cfg = B.new_config(bench_args, env, defaults, transport_name)   # the bench's settings, read the bench's way
    for k in ("models", "repeats", "ttft_probe"):
        cfg.pop(k)
    return {**cfg, "model": model, "levels": levels, "requests_per_level": args.requests_per_level,
            "pause_s": args.pause_s}


def main(argv=None, *, transport=None, sleep=time.sleep, env=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    stdout, stderr = sys.stdout, sys.stderr
    redact = B.Redactor(None)
    try:
        args = parse_args(argv)
        if args.rate_limit_breakdown:   # offline, from the folder's records.jsonl; no key is read
            if args.out:
                raise B.UsageError("--rate-limit-breakdown runs nothing: drop --out")
            bd = write_breakdown(Path(args.rate_limit_breakdown))
            print(f"{bd['totals']['status_429']} of {bd['totals']['attempts']} attempts answered 429: "
                  + (", ".join(f"{v} x {k}" for k, v in bd["totals"]["by_code"].items()) or "none"))
            print(f"wrote {Path(args.rate_limit_breakdown) / BREAKDOWN_FILES[0]} and {BREAKDOWN_FILES[1]}")
            return EXIT_OK
        if not args.out:
            raise B.UsageError("--out DIR is required (a new folder)")
        key = B.load_api_key(args.api_key_file, env)
        redact = B.Redactor(key)
        sys.stdout, sys.stderr = B.RedactingStream(stdout, redact), B.RedactingStream(stderr, redact)
        if not args.dry_run and not key:
            raise B.UsageError("no API key: pass --api-key-file FILE (only the key in it) or set CARERELAY_LLM_API_KEY")
        out = Path(args.out)
        if out.exists():
            raise B.UsageError(f"--out {out} already exists; choose a new folder")
        marker = Path(args.marker) if args.marker else None
        if marker is not None and marker.exists():
            raise B.UsageError(f"--marker {marker} exists: another load run may be in progress (or a stale marker)")
        cfg = new_config(args, env, B.release_defaults(), "fake" if args.dry_run else "urllib")
        cfg["marker"] = B.rel(marker) if marker is not None else None
        tr = transport or (B.FakeTransport([cfg["model"]]) if args.dry_run else B.UrllibTransport())
        cfg["transport"] = getattr(tr, "name", type(tr).__name__)
        try:
            test = LoadTest(cfg, out, transport=tr, api_key=key, sleep=sleep)
        except json.JSONDecodeError:
            raise B.UsageError("CARERELAY_LLM_EXTRA_BODY is not JSON") from None
        out.mkdir(parents=True)
        test.writer.write({"type": "run_start", "ts": B.utc_now(), "schema_version": SCHEMA_VERSION,
                           "config": {k: v for k, v in cfg.items()}})
        test.writer.write({"type": "invocation", "ts": B.utc_now(), "invocation": 1, "argv": B.stored_argv(argv, redact),
                           "created_utc": B.utc_now(), "git": B.git_info(),
                           "source_sha256": {s: B.file_sha(B.ROOT / s) for s in SOURCES}, "max_calls": cfg["max_calls"],
                           "python": sys.version.split()[0]})
        print(B.endpoint_wording(B.endpoint_host(cfg["base_url"]), cfg["dry_run"]).split(". ")[0] + ".")
        stopped, code = None, EXIT_OK
        try:
            if marker is not None:
                marker.open("x").close()   # the window in which other clients of the key were asked to pause
                test.writer.write({"type": "marker", "ts": B.utc_now(), "event": "created", "path": cfg["marker"]})
            stopped = test.run()
            code = EXIT_PARTIAL if stopped else EXIT_OK
        except KeyboardInterrupt:
            stopped, code = "interrupted", EXIT_INTERRUPTED
            print("interrupted; writing what was measured")
        finally:
            if marker is not None:
                marker.unlink(missing_ok=True)
                test.writer.write({"type": "marker", "ts": B.utc_now(), "event": "removed", "path": cfg["marker"]})
        test.writer.write({"type": "invocation_end", "ts": B.utc_now(), "invocation": 1, "stopped_reason": stopped,
                           "http_calls": test.budget.used})
        res = write_outputs(out, redact, B.stored_argv(argv, redact), stopped)
        for lv in res["levels"]:
            print(f"concurrency {lv['concurrency']}: {B.fmt(lv['throughput']['handovers_per_min'])} handovers/min, "
                  f"{B.fmt(lv['throughput']['completion_tokens_per_s'], '', 1)} completion tok/s, p50 "
                  f"{B.fmt(lv['latency_s']['p50'], ' s')}, p95 {B.fmt(lv['latency_s']['p95'], ' s')}, "
                  f"{lv['http']['status_429']} x 429")
        print(res["capacity_note"])
        print(f"wrote {out / 'records.jsonl'}, results.json, summary.md, throughput.svg")
        return code
    except B.UsageError as e:
        print(f"load_tf_endpoint: {redact(str(e))}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        sys.stdout, sys.stderr = stdout, stderr


if __name__ == "__main__":
    sys.exit(main())
