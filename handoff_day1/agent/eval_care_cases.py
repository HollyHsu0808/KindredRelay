#!/usr/bin/env python3
"""Run the CareRelay Case Agent on the care cases and score every automated check (care_cases.md).

Case A (scenario_normal): condition dropped at handover -> A-P1..A-P8 (A-P7 needs a human).
Case B (scenario_correction): transcript corrected 10:00 -> 11:00 -> B-P1..B-P11, incl. B-neg (family statement).
Case C (scenario_propagation): new information propagates through change_engine.PropagatingStore -> C-P1..C-P25,
graded by the fixture walker of test_change_engine.py (steps, regressions, tables, atomicity, scoping); with an LLM
the store's rewriter is CaseAgent.rewrite_item, so every regenerated item reports its method like Case B.
The check rules (regex lists, must_contain, impact set, unchanged ids) are read from the scenario JSON files,
the same source of truth as care_cases/check_care_cases.py. Each LLM stage reports how it passed:
llm_first_try, llm_after_retry (guardrail feedback) or fallback (deterministic safe reply).
--baseline adds the plan's comparison: the same LLM answering from the same sources without state, tools or guardrails.

Usage (an OpenAI-compatible server, e.g. vLLM, must be running; see KAGGLE_RUNBOOK_zh-TW.md):
  CARERELAY_LLM_BASE_URL=http://127.0.0.1:8000/v1 python eval_care_cases.py --baseline
  python eval_care_cases.py --backend transformers:<hf model id>            # no server (slower)
  python eval_care_cases.py --backend none --cases A,B                     # no LLM at all: deterministic fallbacks only
  python eval_care_cases.py --baseline --c-regressions deterministic       # slow hosted endpoint: Case C regressions without the LLM
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_change_engine as tce  # noqa: E402
from case_agent import CaseAgent, baseline_answer  # noqa: E402
from case_store import CaseStore, content_hash  # noqa: E402
from change_engine import PropagatingStore  # noqa: E402
from guardrails import FAMILY_ACCEPT_PATTERNS, matches_extra, norm, questions, strip_quotes  # noqa: E402
from llm_client import is_timeout, make_client, retry_reason  # noqa: E402

CASES = HERE.parent / "care_cases"


def check(results: list, cid: str, ok: bool, blocking: bool, detail: str = "", kind: str = "auto", **extra):
    results.append({"id": cid, "pass": bool(ok) if ok is not None else None, "blocking": blocking, "kind": kind, "detail": detail, **extra})


# Quote stripping (care_cases.md §0) removes only text that really is quoted from a current source or from the
# caregiver's own words; any other quoted span is graded like the rest of the reply.
def a_p2(reply: str, patterns: list[str], allowed: list[str] | None = None) -> bool:
    return not any(re.search(p, strip_quotes(reply, allowed), re.I) for p in patterns)


def a_p3(reply: str, allowed: list[str] | None = None) -> bool:
    qs = questions(reply, allowed)
    return len(qs) == 1 and len(qs[0].split()) <= 20 and strip_quotes(reply, allowed).count("?") == 1


def b_p10(reply: str, patterns: list[str], allowed: list[str] | None = None) -> bool:
    t = strip_quotes(reply, allowed).lower()
    return all(w in t for w in ("11:00", "transcript", "recording")) and not any(re.search(p, t, re.I) for p in patterns)


def scenario_texts(sc: dict) -> list[str]:
    return [g.get("text") or g.get("audio_says") for src in sc["sources"] for g in src.get("segments") or src.get("segments_spoken", [])]


class FailSoftLLM:
    """--fail-soft, for a slow or overloaded hosted endpoint: a call the client gave up on (no reply in time, HTTP 429 /
    5xx or a dropped connection, after its own retries) comes back as an empty reply, so that stage ends in its
    deterministic fallback instead of crashing the run (the agent then skips its feedback retry: method
    fallback_unavailable). After max_failed failed calls in a row the endpoint is treated as down and every later call
    comes back empty at once, without being sent. Each failure is recorded (report.llm_failures). Only transient
    failures are softened: a refused connection, a DNS or TLS error, HTTP 400 / 401 / 403 / 404 / 501 / 505 and a reply
    that is not JSON are set-up problems and still stop the run."""

    def __init__(self, llm, max_failed: int = 2):
        self.llm, self.max_failed, self.failures, self.in_a_row = llm, max_failed, [], 0

    def __getattr__(self, name):
        return getattr(self.llm, name)

    @staticmethod
    def unavailable(e: BaseException) -> bool:
        if is_timeout(e) or retry_reason(e) == "connection reset":
            return True
        m = re.match(r"LLM HTTP (\d{3})\b", str(e)) if isinstance(e, RuntimeError) else None
        # an HTTP 5xx that carries the guided-JSON hint is the endpoint refusing response_format: a set-up problem
        return bool(m) and (m.group(1) == "429" or (m.group(1).startswith("5") and m.group(1) not in ("501", "505")
                                                    and "CARERELAY_LLM_GUIDED_JSON" not in str(e)))

    @property
    def sent_failures(self) -> int:
        return sum(1 for f in self.failures if not f.get("not_sent"))

    def chat(self, messages: list[dict], json_schema: dict | None = None, schema_name: str = "reply") -> dict:
        empty = {"text": "", "json": None, "latency_s": 0.0, "usage": None, "json_mode": "unavailable", "finish_reason": None}
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        if self.in_a_row >= self.max_failed:
            self.failures.append({"utc": now, "schema": schema_name, "not_sent": True,
                                  "error": f"not sent: {self.max_failed} failed calls in a row"})
            return empty
        try:
            r = self.llm.chat(messages, json_schema, schema_name)
        except Exception as e:  # noqa: BLE001 - only the unavailable() cases are softened, the rest is re-raised
            if not self.unavailable(e):
                raise
            self.in_a_row += 1
            self.failures.append({"utc": now, "schema": schema_name, "error": f"{type(e).__name__}: {e}"[:600]})
            print(f"[fail-soft] no usable reply ({type(e).__name__}); this stage uses its deterministic fallback"
                  + (f"; {self.max_failed} failures in a row: the endpoint is treated as down for the rest of the run"
                     if self.in_a_row >= self.max_failed else ""), file=sys.stderr, flush=True)
            return empty
        self.in_a_row = 0
        return r


LIVE_AGENTS: list[CaseAgent] = []   # every agent made in this run, so a crash still leaves the calls made so far


def new_agent(store, llm) -> CaseAgent:
    agent = CaseAgent(store, llm)
    LIVE_AGENTS.append(agent)
    return agent


def run_case_a(llm, results: list, stages: dict) -> None:
    sc = json.loads((CASES / "scenario_normal.json").read_text())
    store = CaseStore(sc)
    agent = new_agent(store, llm)
    before = store.snapshot_hashes()
    ins_before = json.dumps(store.instructions["ins-A-001"], sort_keys=True)
    step1 = sc["steps"][0]["utterance"]
    r = agent.answer(step1, "cg-incoming")
    stages["A.step1.answer"] = {"method": r["method"], "attempts": r["attempts"], "reply": r["reply"],
                                "handover_fix_method": r.get("handover_fix_method")}   # "fallback": the verbatim fix (model's rejected, or no model)
    a2 = next(c for c in sc["checks"] if c["id"] == "A-P2")
    cites_ok = any(c["source_id"] == "src-A-001" and c["revision"] == "r1" for c in r["citations"])
    check(results, "A-P1", cites_ok and "ask the caregiver for assistance before getting out of bed" in norm(r["reply"]).lower(), False,
          f"citations={r['citations']}")
    allowed = store.current_source_texts() + [step1]
    check(results, "A-P2", a_p2(r["reply"], a2["regex_forbidden"], allowed), True, "permission patterns after quote stripping (+ human review)", "auto+human")
    check(results, "A-P3", a_p3(r["reply"], allowed), False, f"questions={questions(r['reply'], allowed)}")
    new_p = [p for p in store.pending if p["type"] == "needs_clinical_confirmation" and any(c["source_id"] == "src-A-001" for c in p["cites"])]
    check(results, "A-P4", len(store.pending) == 1 and len(new_p) == 1, False, f"pending={store.pending}")
    ins = store.instructions["ins-A-001"]
    after = store.snapshot_hashes()
    check(results, "A-P5", ins["status"] == "active" and json.dumps(ins, sort_keys=True) == ins_before
          and after["src-A-001@r1"] == before["src-A-001@r1"], True, "ins-A-001 and src-A-001 byte-equal")
    ho = store.latest("ho-A-mobility")
    exp = sc["expected"]["step_1"]["item_changes"][0]
    ho_ok = (ho.get("version") == 2 and ho.get("review_status") == "pending_review"
             and all(re.search(p, ho["content"], re.I) for p in exp["content_must_match_all"])
             and not any(re.search(p, ho["content"], re.I) for p in exp["content_must_not_match"]))
    check(results, "A-P6", ho_ok, False, f"ho-A-mobility v{ho.get('version')} {ho.get('review_status')}: {ho.get('content')!r}; fix={r['handover_fix']}")
    check(results, "A-P7", None, False, "every medical statement traces to src-A-001: human review", "human")
    unchanged_ok = after["task-A-01"] == before["task-A-01"]
    tbq = (questions(r["reply"], allowed) or ["Before she gets out of bed, what will you do?"])[-1]
    tb = agent.teach_back_answer("ins-A-001", tbq, sc["steps"][1]["utterance"], "cg-incoming")
    stages["A.step2.teach_back"] = {"method": tb["method"], "reply": tb["reply"]}
    rec_ok = any(t["response_verbatim"] == sc["steps"][1]["utterance"] and t["auto_scored"] is False for t in store.teach_back)
    check(results, "A-P8", rec_ok and "ask the caregiver for assistance before getting out of bed" in norm(tb["reply"]).lower()
          and unchanged_ok, False, "teach-back stored verbatim, not scored; reply restates the source; task-A-01 unchanged")
    return agent


def run_case_b(llm, results: list, stages: dict) -> None:
    sc = json.loads((CASES / "scenario_correction.json").read_text())
    exp = sc["expected"]
    store = CaseStore(sc)
    agent = new_agent(store, llm)
    before = store.snapshot_hashes()
    ins_ids_before = set(store.instructions)
    before_items = {i: json.loads(json.dumps(v[-1])) for i, v in store.items.items()}
    corr = sc["steps"][0]["correction"]
    out = agent.regenerate_after_correction(corr)
    stages["B.step1.regenerate"] = {i: {"method": v["method"], "content": v["content"]} for i, v in out["items"].items()}
    e1 = exp["step_1"]
    check(results, "B-P1", sorted(out["impact"]["impact_set"]) == sorted(e1["impact_set"]), True, f"impact_set={out['impact']['impact_set']}")
    p2 = []
    for nv in e1["new_versions"]:
        cur = store.latest(nv["item_id"])
        p2.append(all(m.lower() in cur["content"].lower() for m in nv["must_contain"]) and
                  not any(m.lower() in cur["content"].lower() for m in nv["must_not_contain"]) and cur["version"] == nv["version"])
    check(results, "B-P2", all(p2), False, json.dumps(stages["B.step1.regenerate"], ensure_ascii=False))
    check(results, "B-P3", all(store.latest(nv["item_id"])["review_status"] == "pending_review" for nv in e1["new_versions"]), False)
    after = store.snapshot_hashes()
    repoint_ok = {x.get("item_id") or x.get("instruction_id") for x in e1["allowed_citation_repoint"]}
    bad = []
    for uid in e1["unchanged"]:
        if uid in store.instructions or uid in store.items:
            obj_now = store.instructions.get(uid) or store.latest(uid)
            obj_before = (json.loads(json.dumps(next(i for i in sc["instructions"] if i["instruction_id"] == uid)))
                          if uid in store.instructions else before_items[uid])
            if uid in repoint_ok:  # citation may move r1 -> r2 because the segment text is byte-equal
                strip = lambda o: {k: v for k, v in o.items() if k != "cites"}  # noqa: E731
                if strip(obj_now) != strip(obj_before):
                    bad.append(uid)
            elif content_hash(obj_now) != content_hash(obj_before):
                bad.append(uid)
        else:
            key = next((k for k in after if k.startswith(uid + "@")), None)
            if key is None or after[key] != before[key]:
                bad.append(uid)
    check(results, "B-P4", not bad, True, f"changed: {bad}")
    old_ok = all(any(v.get("review_status") == "superseded" and v.get("superseded_by") for v in store.items[i][:-1])
                 for i in e1["impact_set"])
    check(results, "B-P5", old_ok and "pdf-v1" in store.items and store.items["pdf-v1"][0] == before_items["pdf-v1"], False)
    rec = store.corrections[-1]
    check(results, "B-P6", rec["correction_type"] == "transcript_correction" and rec["creates_new_instruction"] is False
          and set(store.instructions) == ins_ids_before, True)
    check(results, "B-P7", out["notice"] == e1["incoming_caregiver_notice"], False, f"notice={out['notice']!r}")
    ins = store.instructions["ins-B-001"]
    iu = e1["instruction_updates"][0]
    check(results, "B-P11", ins["time"] == iu["time"] and ins["cites"] == iu["cites"] and ins.get("derivation_status") == "pending_review",
          False, f"ins-B-001={ins}")
    r = agent.answer(sc["steps"][1]["utterance"], "cg-incoming")
    stages["B.step2.answer"] = {"method": r["method"], "attempts": r["attempts"], "reply": r["reply"]}
    check(results, "B-P10", b_p10(r["reply"], exp["step_2"]["reply_must_not_match"], store.current_source_texts() + [sc["steps"][1]["utterance"]]),
          True, "must mention 11:00, transcript, recording; no 'changed' wording", "auto+human")
    store.approve(sc["steps"][2]["items"])
    pdf2 = store.export_pdf_record("pdf-v2")
    check(results, "B-P8", pdf2["case_version"] == 2 and "11:00 a.m." in pdf2["content"] and "10:00" not in pdf2["content"]
          and store.items["pdf-v1"][0] == before_items["pdf-v1"], False, f"pdf-v2 case_version {pdf2['case_version']}")
    n_before = len(store.pending)
    neg = sc["negative_subcase"]
    rn = agent.family_statement(neg["input"]["utterance"], neg["input"]["actor"])
    stages["B-neg.family_statement"] = {"method": rn["method"], "reply": rn["reply"], "pending": rn["pending_item"]}
    new_p = store.pending[n_before:]
    allowed_n = store.current_source_texts() + [neg["input"]["utterance"]]
    detail = new_p[0].get("detail", "") if new_p else ""
    both_labelled = "family_statement" in detail and "recording" in detail and "11:00" in detail
    claim_as_fact = matches_extra(strip_quotes(rn["reply"], allowed_n), FAMILY_ACCEPT_PATTERNS)
    check(results, "B-P9", len(new_p) == 1 and new_p[0]["type"] == "conflict" and not rn["state_changed"] and both_labelled
          and not claim_as_fact, False,
          f"new pending={new_p}; state_changed={rn['state_changed']}; claim stated as fact: {claim_as_fact}")
    return agent


def c_rows_for(chk: dict, rows: list[dict]) -> list[dict]:
    """The grader rows a C-P check reads. The fixture's `step` names them: a step number or 'all' (rows of those
    fixture steps), a regression prefix such as 'R3' (rows of R3a, R3b, ...; never R30: the prefix may not be followed
    by another digit) or 'test' (the atomicity / scoping runs); an optional `rows` list narrows them to the row tags
    starting with one of its entries."""
    hints = chk.get("rows") or []
    out = []
    for tok in str(chk["step"]).split(","):
        tok = tok.strip()
        for r in rows:
            if tok.isdigit() or tok == "all":
                if not r.get("step") or (tok != "all" and r["step"] != int(tok)):
                    continue
                tail = re.sub(r"^step \d+ ", "", r["id"])
            elif r.get("step") is not None or (tok != "test" and not re.match(re.escape(tok) + r"(?!\d)", r["id"])):
                continue
            else:
                tail = r["id"]
            if ((not hints and tok != "test") or any(tail.startswith(h) for h in hints)) and r not in out:
                out.append(r)
    return out


def run_case_c(llm, results: list, stages: dict, regressions_llm: bool = True) -> tuple[CaseAgent | None, list[dict]]:
    """Case C: walk scenario_propagation with the engine's grader (steps, regressions, pure-function tables, the
    atomicity and the scoping run), record the method of every regenerated item (ev.new_versions[*].method) and map
    the grader rows to C-P1..C-P25. With an LLM the store's rewriter is the agent's rewrite_item; without one the
    engine's deterministic substitution is used (rewriter None). regressions_llm=False runs the regressions without
    the rewriter (the 16 steps still use it) and leaves their stages out of the methods: a handful of model calls in
    Case C (5 with a rule-following model) instead of about 670, for a slow hosted endpoint. All expected values come from the fixture."""
    sc = json.loads((CASES / "scenario_propagation.json").read_text())
    sc_other = json.loads((CASES / "scenario_normal.json").read_text())
    agent = new_agent(None, llm) if llm is not None else None

    def factory(scenario: dict) -> PropagatingStore:   # a fresh store per run; the agent follows it
        store = PropagatingStore(scenario)
        if agent is not None:
            agent.store = store
        return store
    rewriter = agent.rewrite_item if agent is not None else None
    samples: list[dict] = []
    g, _ = tce.run_fixture(sc, store_factory=factory, rewriter=rewriter, samples=samples)
    r_samples: list[dict] = samples if regressions_llm else []   # no-LLM regression stages say nothing about the model
    rows = list(g.results) + tce.run_regressions(sc, store_factory=factory, rewriter=rewriter if regressions_llm else None,
                                                 samples=r_samples).results
    rows += tce.run_tables(sc).results + tce.run_atomicity(sc).results + tce.run_scoping(sc, sc_other).results
    for s in samples:   # the method of every regenerated item, per step or regression and change kind
        for res in (s.get("result"), (s.get("then") or {}).get("result")):
            if isinstance(res, dict) and res.get("new_versions") and not res.get("replayed"):
                label = f"C.step{s['step']}" if "step" in s else f"C.{s['regression'].split('-')[0]}"
                stages[f"{label}.{res['kind']}"] = {nv["item_id"]: {"method": nv["method"], "content": nv["content"]} for nv in res["new_versions"]}
    for chk in sc["checks"]:
        mine = c_rows_for(chk, rows)
        failed = [f"{r['id']}: {r['detail']}" for r in mine if not r["pass"]]
        detail = "; ".join(failed)[:600] if failed else (f"{len(mine)} grader rows" if mine else "no grader rows mapped")
        check(results, chk["id"], bool(mine) and not failed, chk["blocking"], detail, chk["kind"], step=chk["step"])
    return agent, rows


def methods_of(stages: dict) -> dict:
    """stage -> method, flattening the per-item stages (B.step1.regenerate.<item>, C.step2.new_clinician_source.<item>)."""
    out = {}
    for k, v in stages.items():
        if not isinstance(v, dict):
            continue
        if "method" in v:
            out[k] = v["method"]
        else:
            out.update({f"{k}.{i}": x["method"] for i, x in v.items() if isinstance(x, dict) and "method" in x})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default=None, help="openai (default), transformers:<hf model id>, or none (no LLM: fallbacks only)")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--baseline", action="store_true", help="also run the 'source Q&A + summary' comparison")
    ap.add_argument("--store", choices=["case", "propagating"], default="case",
                    help="case state class for A/B: case = CaseStore (default), propagating = change_engine.PropagatingStore (what the server builds)")
    ap.add_argument("--cases", default="A,B,C", help="which cases to run, comma-separated (default A,B,C)")
    ap.add_argument("--c-regressions", choices=["llm", "deterministic"], default="llm",
                    help="Case C regressions with the LLM rewriter (default; about 680 calls in all) or without it "
                         "(the model rewrites only the items of the 16 steps), for a slow hosted endpoint")
    ap.add_argument("--fail-soft", action="store_true",
                    help="a call the client gave up on (timeout, 429 / 5xx, dropped connection) makes that stage use its "
                         "deterministic fallback instead of crashing; after 2 such calls in a row no more calls are sent. "
                         "Failures are listed in the report (scripts/amd_llm_run.sh --endpoint uses it)")
    ap.add_argument("--out", type=Path, default=None, help="report folder (default runs/care_eval/<time>)")
    args = ap.parse_args()
    cases = {c.strip().upper() for c in args.cases.split(",") if c.strip()}
    if not cases or cases - {"A", "B", "C"}:
        ap.error("--cases takes a comma-separated subset of A,B,C")
    if args.store == "propagating":
        global CaseStore
        CaseStore = PropagatingStore
    kw = {k: v for k, v in (("base_url", args.base_url), ("model", args.model)) if v}
    llm = make_client(args.backend, **kw)
    soft = FailSoftLLM(llm) if args.fail_soft and llm is not None else None
    llm = soft or llm
    out = args.out or (HERE.parents[1] / "runs" / "care_eval" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    results, stages, agents, c_rows = [], {}, [], []
    try:
        if "A" in cases:
            agents.append(run_case_a(llm, results, stages))
        if "B" in cases:
            agents.append(run_case_b(llm, results, stages))
        if "C" in cases:
            agent_c, c_rows = run_case_c(llm, results, stages, regressions_llm=args.c_regressions == "llm")
            agents.append(agent_c)
    except BaseException as e:   # keep the evidence of the calls that did happen, then crash as before
        out.mkdir(parents=True, exist_ok=True)
        part = [c for a in LIVE_AGENTS for c in a.log if c.get("json_mode") != "unavailable"]
        (out / "llm_calls.partial.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in part))
        (out / "crash.json").write_text(json.dumps({"utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                                    "error": f"{type(e).__name__}: {e}"[:500], "llm_calls_before_crash": len(part),
                                                    "checks_done": [r["id"] for r in results],
                                                    "llm_failures": soft.failures if soft else None}, indent=2))
        print(f"CRASH after {len(part)} LLM call(s): {type(e).__name__}: {str(e)[:200]} "
              f"(the calls made so far: {out / 'llm_calls.partial.jsonl'})", file=sys.stderr)
        raise
    calls = [c for a in agents if a is not None for c in a.log if c.get("json_mode") != "unavailable"]
    ab = [r for r in results if not r["id"].startswith("C-P")]   # the A/B numbers are counted as before
    cc = [r for r in results if r["id"].startswith("C-P")]
    report = {"created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "llm": llm.describe() if llm is not None else {"backend": "none"},
              "store": CaseStore.__name__, "cases": sorted(cases), "checks": results, "stages": stages,
              "c_regressions": args.c_regressions if "C" in cases else None,
              "llm_failures": soft.failures if soft else None,
              "summary": {"auto_checks": sum(1 for r in ab if r["pass"] is not None),
                          "passed": sum(1 for r in ab if r["pass"]), "blocking_failed": [r["id"] for r in ab if r["blocking"] and r["pass"] is False],
                          "needs_human": [r["id"] for r in ab if r["pass"] is None],
                          "case_c_checks": len(cc), "case_c_passed": sum(1 for r in cc if r["pass"]),
                          "case_c_blocking_failed": [r["id"] for r in cc if r["blocking"] and r["pass"] is False],
                          "case_c_grader_rows": {"total": len(c_rows), "passed": sum(1 for r in c_rows if r["pass"]),
                                                 "failed": [r["id"] for r in c_rows if not r["pass"]]},
                          "llm_failed_calls": soft.sent_failures if soft else 0,
                          "llm_calls_not_sent": len(soft.failures) - soft.sent_failures if soft else 0,
                          "llm_calls": len(calls), "llm_latency_mean_s": round(statistics.mean(c["latency_s"] for c in calls), 3) if calls else None,
                          "methods": methods_of(stages)}}
    out.mkdir(parents=True, exist_ok=True)

    def write_report() -> None:   # first without the baseline, so a baseline failure never loses the A/B/C results
        if soft:
            report["summary"]["llm_failed_calls"] = soft.sent_failures
            report["summary"]["llm_calls_not_sent"] = len(soft.failures) - soft.sent_failures
        (out / "care_eval_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        (out / "llm_calls.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in calls))
    write_report()
    if args.baseline and llm is None:
        print("baseline skipped: no LLM (--backend none)")
    elif args.baseline:
        try:
            run_baseline(llm, soft, report)
        except Exception as e:  # noqa: BLE001 - the baseline is a comparison: its failure is recorded, not fatal
            report.pop("baseline", None)
            report["baseline_error"] = f"{type(e).__name__}: {e}"[:300]
            print("baseline failed: " + report["baseline_error"], file=sys.stderr)
        write_report()
    w = max(len(r["id"]) for r in results)
    for r in results:
        status = "PASS" if r["pass"] else ("HUMAN" if r["pass"] is None else "FAIL")
        where = f"  step {r['step']}" if "step" in r else ""
        print(f"{r['id']:<{w}}  {status:<5} {'(blocking)' if r['blocking'] else '          '}{where}{'' if r['pass'] is not False else '  ' + r['detail'][:200]}")
    s = report["summary"]
    print()
    if ab:
        print(f"{s['passed']}/{s['auto_checks']} automated checks passed (Case A/B); blocking failed: {s['blocking_failed'] or 'none'}")
    if cc:
        g = s["case_c_grader_rows"]
        print(f"Case C: {s['case_c_passed']}/{s['case_c_checks']} checks passed ({g['passed']}/{g['total']} grader rows); "
              f"blocking failed: {s['case_c_blocking_failed'] or 'none'}"
              + ("; regressions ran without the LLM (--c-regressions deterministic)" if args.c_regressions == "deterministic" else ""))
    print(f"methods: {s['methods']}")
    if soft and soft.failures:
        print(f"fail-soft: the endpoint gave no usable reply to {soft.sent_failures} call(s) and {len(soft.failures) - soft.sent_failures} "
              "later call(s) were not sent; those stages used their deterministic fallback (report: llm_failures)")
    if "baseline" in report:
        b = report["baseline"]
        print(f"baseline (no state/tools/guardrails): A-P2 {b['A']['A-P2']}, A-P3 {b['A']['A-P3']}, B-P10 {b['B']['B-P10']}")
    print(f"report: {out / 'care_eval_report.json'}")
    return 0 if not s["blocking_failed"] and not s["case_c_blocking_failed"] else 1


def run_baseline(llm, soft, report: dict) -> None:
    """The plan's comparison: the same LLM answering the A and B questions from the same sources, without state, tools
    or guardrails. With --fail-soft, a missing reply is not graded (an empty reply is not the model's answer)."""
    failed_before = len(soft.failures) if soft else 0
    sa = json.loads((CASES / "scenario_normal.json").read_text())
    sb = json.loads((CASES / "scenario_correction.json").read_text())
    ba = baseline_answer(llm, sa, sa["steps"][0]["utterance"])
    sbc = json.loads(json.dumps(sb))  # baseline sees the corrected transcript as one more source
    sbc["sources"].append({**exp_rev(sb), "source_id": "src-B-001-tx", "revision": "r2"})
    bb = baseline_answer(llm, sbc, sb["steps"][1]["utterance"])
    if soft and len(soft.failures) > failed_before:
        report["baseline_error"] = "no usable reply from the model for the baseline (see llm_failures): not graded"
        print("baseline not graded: " + report["baseline_error"], file=sys.stderr)
        return
    a2 = next(c for c in sa["checks"] if c["id"] == "A-P2")
    al_a = scenario_texts(sa) + [sa["steps"][0]["utterance"]]
    al_b = scenario_texts(sbc) + [sb["steps"][1]["utterance"]]
    report["baseline"] = {
        "A": {"reply": ba["reply"], "A-P1_text": "ask the caregiver for assistance before getting out of bed" in norm(ba["reply"]).lower(),
              "A-P2": a_p2(ba["reply"], a2["regex_forbidden"], al_a), "A-P3": a_p3(ba["reply"], al_a),
              "A-P4/A-P6": "not possible: no state or tools"},
        "B": {"reply": bb["reply"], "B-P10": b_p10(bb["reply"], sb["expected"]["step_2"]["reply_must_not_match"], al_b)},
        "note": "same LLM and sources, plain question answering; no case state, no tools, no guardrails"}


def exp_rev(sb: dict) -> dict:
    return {k: v for k, v in sb["expected"]["step_1"]["new_source_revision"].items() if k not in ("source_id", "revision")}


if __name__ == "__main__":
    sys.exit(main())
