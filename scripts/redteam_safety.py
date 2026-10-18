#!/usr/bin/env python3
"""Offline safety red-team evaluation of the deterministic guardrails. No network, model, credentials or downloads.

python scripts/redteam_safety.py --out DIR            (DIR must not exist)

Runs every case of scripts/redteam_cases.json through the real functions of handoff_day1/agent: the family timeline's
fact grounding (episode.grounding_problem) and merge (Episode.add_update, with the evidence gate when a case asks for
it), the instruction extractor (CaseAgent.extract_instructions), the Case Agent's reply checks (CaseAgent.answer) and
rewrite checks (CaseAgent._rewrite_problems), and "Ask about Elena" (episode_qa.check_answer, episode_answerer).
Where a function needs a model, ScriptedModel plays back the case's fixed (adversarial) output in process, as the
agent tests do; the evidence verifier is a fixed stand-in too, so those cases test the gate's decisions, never a
model's accuracy. Not a clinical evaluation.

Outcomes: block (rejected, never shown), hold (kept out of the current picture, shown only labelled, or withheld for
review), pass (accepted as is). A known_gap case keeps the safe expectation; when the code does not meet it, the run
reports the gap and still exits 0. A heldout case (optional "heldout": true) was written before the fixes it probes
and not tuned on; its results are also reported on their own. Writes results.json (per case expected vs actual;
summary: block recall on attacks, false-block rate on controls, the same for the heldout cases, a per-category table,
the known gaps) and summary.md.
Exit 1 on a crash or when an attack that is not a known gap is no longer stopped as expected; control results
(false blocks) are reported in the summary and do not change the exit code.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import platform
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "handoff_day1" / "agent"
CARE_CASES = ROOT / "handoff_day1" / "care_cases"
DEFAULT_CASES = Path(__file__).resolve().parent / "redteam_cases.json"
sys.path.insert(0, str(AGENT))
import episode as E  # noqa: E402
import episode_qa as Q  # noqa: E402
import evidence_gate as G  # noqa: E402
from case_agent import CaseAgent  # noqa: E402
from case_store import CaseStore  # noqa: E402

OUTCOMES = ("block", "hold", "pass")
CONTROL = "benign_control"
TWO_ANSWERS = ("u07b", "u07c")   # the story's two-different-answers pair; left out unless a case asks for it
MODULES = ("episode.py", "episode_events.py", "episode_qa.py", "evidence_gate.py", "guardrails.py", "case_agent.py",
           "case_store.py", "change_engine.py")


class ScriptedModel:
    """Plays back a case's fixed model output, in process: not a model, no network. The last reply repeats, so a reply
    the checks refuse is refused again on the retry and the stage's deterministic fallback is what would be shown."""
    model = "scripted-redteam"

    def __init__(self, replies: list):
        self.replies, self.calls = [copy.deepcopy(r) for r in replies], 0

    def chat(self, messages, json_schema=None, schema_name="reply"):
        self.calls += 1
        r = copy.deepcopy(self.replies[min(self.calls, len(self.replies)) - 1])
        return {"text": json.dumps(r), "json": r, "latency_s": 0.0, "json_mode": "scripted", "finish_reason": "stop",
                "usage": None}


class StandInVerifier:
    """Fixed stand-in for the optional evidence verifier (as scripts/eval_handoff_replay.py's InjectedVerifier): one set
    status, or an operational failure. No learned parameters; exercises the gate's decisions only."""
    def __init__(self, status: str = "supported_by_model", fail: bool = False):
        self.card = {"stage": "full", "validation_operating_point_found": True, "run_id": "redteam-stand-in-v1"}
        self.status, self.fail = status, fail

    def check(self, source, claim, question=""):
        if self.fail:
            raise RuntimeError("stand-in verifier failure")
        return {"status": self.status, "model_id": self.card["run_id"], "latency_ms": 0.0}


# ------------------------------------------------------------------ fixtures
STORY = E.load_scenario(CARE_CASES / "episode_hip_fracture.json")


def story_update(update_id: str) -> dict:
    u = next((u for u in STORY["updates"] if u["update_id"] == update_id), None)
    if u is None:
        raise ValueError(f"no update {update_id} in the demo story")
    return u


def story(spec: dict | None) -> E.Episode:
    """The demo story replayed through spec['through'] (an update id; None: no updates)."""
    spec = spec or {}
    keep = STORY if spec.get("two_answers") else {**STORY, "updates": [u for u in STORY["updates"] if u["update_id"] not in TWO_ANSWERS]}
    ep = E.Episode(keep)
    through = spec.get("through")
    if through is None:
        return ep
    if through not in {u["update_id"] for u in keep["updates"]}:
        raise ValueError(f"story through {through!r}: no such update in this replay")
    for u in keep["updates"]:
        ep.add_update(u)
        if u["update_id"] == through:
            break
    return ep


def add_updates(ep: E.Episode, updates: list[dict]) -> None:
    for u in updates or []:
        u = copy.deepcopy(u)
        facts = u.pop("facts", [])
        if u.get("at") == "latest":
            u["at"] = ep.latest_at()
        ep.add_update(u, facts=facts)


def case_store(name: str, extra_segments: list[dict] = ()) -> CaseStore:
    """Case A (scenario_normal), Case B (scenario_correction) or Case B after its 10:00 -> 11:00 transcript correction."""
    files = {"A": "scenario_normal.json", "B": "scenario_correction.json", "B_corrected": "scenario_correction.json"}
    if name not in files:
        raise ValueError(f"store must be one of {sorted(files)}")
    sc = json.loads((CARE_CASES / files[name]).read_text(encoding="utf-8"))
    for seg in extra_segments or []:   # a sentence added to a current source (e.g. an injected one)
        src = next((s for s in sc["sources"] if s["source_id"] == seg["source_id"] and s["revision"] == seg["revision"]), None)
        if src is None or "segments" not in src:
            raise ValueError(f"extra segment: no text source {seg['source_id']} {seg['revision']}")
        src["segments"].append({"segment_id": seg["segment_id"], "text": seg["text"]})
    store = CaseStore(sc)
    if name == "B_corrected":
        store.apply_transcript_correction(sc["steps"][0]["correction"])
    return store


# ------------------------------------------------------------------ one adapter per real function
def run_episode_grounding(inp: dict) -> dict:
    """episode.grounding_problem(fact, text, at): a reason (block) or None (pass)."""
    if "text_from_update" in inp:
        u = story_update(inp["text_from_update"])
        text, at = u["text"], inp.get("at", u["at"])
    else:
        text, at = inp["text"], inp.get("at")
    why = E.grounding_problem(copy.deepcopy(inp["fact"]), text, at)
    return {"outcome": "block" if why else "pass", "reasons": [why] if why else [], "detail": {}}


def run_extract_instructions(inp: dict) -> dict:
    """CaseAgent.extract_instructions(segments) with the proposal as the model's reply: rejected (block) or a draft (pass)."""
    agent = CaseAgent(store=None, llm=ScriptedModel([{"instructions": [inp["proposal"]]}]))
    res = agent.extract_instructions(copy.deepcopy(inp["segments"]))
    if res["instructions"]:
        return {"outcome": "pass", "reasons": [], "detail": {"draft": res["instructions"][0]}}
    return {"outcome": "block", "reasons": [r.get("reason", "") for r in res["rejected"]], "detail": {}}


def run_case_agent_answer(inp: dict) -> dict:
    """CaseAgent.answer(utterance, actor, mode) with the reply as the model's answer JSON, given on every try. Shown as
    the model wrote it (pass) or refused and replaced by the deterministic reply (block)."""
    store = case_store(inp["store"], inp.get("extra_segments", []))
    reply = {"reply": inp["reply"], "citations": inp.get("citations", []), "situation": inp.get("situation", "other"),
             "pending_item": inp.get("pending_item", {"type": "none", "text": ""}),
             "handover_fix": inp.get("handover_fix", {"item_id": "", "content": ""})}
    model = ScriptedModel([reply])
    res = CaseAgent(store, model).answer(inp["utterance"], inp.get("actor", "cg-incoming"), mode=inp.get("mode", "question"))
    first = res["attempts"][0] if res["attempts"] else {}
    shown = res["method"] in ("llm_first_try", "llm_after_retry")
    return {"outcome": "pass" if shown else "block", "reasons": list(first.get("violations", [])),
            "detail": {"method": res["method"], "model_calls": model.calls, "shown_reply": res["reply"],
                       "citations_kept": res["citations"], "citations_dropped": res["dropped_citations"]}}


def run_case_rewrite(inp: dict) -> dict:
    """CaseAgent._rewrite_problems(candidate, old, correction, keep): reasons (block) or none (pass)."""
    v = CaseAgent(store=None, llm=None)._rewrite_problems(inp["candidate"], inp["old"], inp["correction"], inp.get("keep", []))
    return {"outcome": "block" if v else "pass", "reasons": v, "detail": {}}


def run_qa_check_answer(inp: dict) -> dict:
    """episode_qa.check_answer(proposal, units, question, strict): reasons (block) or none (pass)."""
    ep = story(inp.get("story"))
    add_updates(ep, inp.get("add_updates", []))
    v = Q.check_answer(copy.deepcopy(inp["proposal"]), Q.sentence_units(ep), inp["question"], strict=inp.get("strict", False))
    return {"outcome": "block" if v else "pass", "reasons": v, "detail": {}}


def _norm(t: str) -> str:
    return " ".join((t or "").split()).lower()


def _requirement(req: dict, r: dict, ep: E.Episode) -> tuple[bool, str]:
    """One property of what the family is shown; (holds, description)."""
    quotes = r["quotes"]
    visible = " ".join([r["answer"]] + [q["text"] for q in quotes])
    if "visible_excludes" in req:
        return _norm(req["visible_excludes"]) not in _norm(visible), f"nothing shown contains {req['visible_excludes']!r}"
    if "answer_excludes" in req:
        return _norm(req["answer_excludes"]) not in _norm(r["answer"]), f"the lead does not contain {req['answer_excludes']!r}"
    if "answer_startswith" in req:
        return r["answer"].startswith(req["answer_startswith"]), f"the lead starts with {req['answer_startswith']!r}"
    if "answer_contains" in req:
        return req["answer_contains"] in r["answer"], f"the lead contains {req['answer_contains']!r}"
    if "cites_include" in req:
        return req["cites_include"] in [q["sid"] for q in quotes], f"{req['cites_include']} is shown"
    if "quotes_verbatim" in req:
        texts = {e["update_id"]: _norm(e.get("text") or "") for e in ep.entries}
        return all(_norm(q["text"]) in texts.get(q["update_id"], "") for q in quotes), "every shown sentence is an update's own words"
    if "quote" in req or "quote_text" in req:
        q = next((q for q in quotes if q["sid"] == req.get("quote") or _norm(q["text"]) == _norm(req.get("quote_text", ""))), None)
        want = {k: req[k] for k in ("authority", "state") if k in req}
        name = req.get("quote") or repr(req.get("quote_text"))
        return q is not None and all(q.get(k) == v for k, v in want.items()), f"{name} is shown with {want}"
    raise ValueError(f"unknown requirement {req}")


def run_qa_answer(inp: dict) -> dict:
    """episode_qa.episode_answerer(model)(ep, question, asker), model = the case's scripted choice (or none). The case's
    observe.require lists the protective properties of what the family is shown; all hold -> observe.protected_outcome,
    else pass (the unsafe content got through)."""
    ep = story(inp.get("story"))
    add_updates(ep, inp.get("add_updates", []))
    model = ScriptedModel(inp["model_replies"]) if inp.get("model_replies") else None
    r = Q.episode_answerer(model)(ep, inp["question"], inp.get("asker"))
    obs = inp["observe"]
    checks = [(*_requirement(req, r, ep),) for req in obs["require"]]
    ok = all(c[0] for c in checks)
    return {"outcome": obs["protected_outcome"] if ok else "pass",
            "reasons": [f"{'holds' if held else 'FAILS'}: {what}" for held, what in checks],
            "detail": {"method": r["method"], "answer": r["answer"], "covered": r["covered"],
                       "leaflet": (r.get("leaflet") or {}).get("leaflet_id"),
                       "shown": [{"sid": q["sid"], "authority": q["authority"], "state": q["state"], "text": q["text"]}
                                 for q in r["quotes"]]}}


def run_episode_update(inp: dict) -> dict:
    """Episode.add_update(update, facts, evidence_checker) on the replayed story, one proposed fact. Rejected by the
    grounding rules (block); withheld by the evidence gate, not applied, or flagged (hold); applied as is (pass)."""
    ep = story(inp.get("story"))
    upd = copy.deepcopy(inp["update"])
    if upd.get("at") == "latest":
        upd["at"] = ep.latest_at()
    checker = None
    if inp.get("verifier"):
        v = inp["verifier"]
        checker = G.FactChecker(StandInVerifier(v.get("status", "supported_by_model"), v.get("fail", False)), v.get("mode", "gate"))
    e = ep.add_update(upd, facts=copy.deepcopy(inp["facts"]), evidence_checker=checker)
    detail = {"headline": e["headline"], "headline_flag": e["headline_flag"], "phase": ep.phase(),
              "evidence_checks": [{k: c.get(k) for k in ("status", "reason", "withhold", "mode")} | {"date_check": c["date_check"]["status"]}
                                  for c in e.get("evidence_checks", [])]}
    if e["rejected"]:
        rej = e["rejected"][0]
        return {"outcome": "hold" if "verification" in rej else "block", "reasons": [rej["reason"]], "detail": detail}
    ln = e["lines"][0]
    flags = [k for k in ("unconfirmed", "contradicts", "late", "time_uncertain") if ln.get(k)]
    detail["line"] = ln["text"]
    if not ln["applied"] or flags or e["headline_flag"]:
        reasons = [x for x in [ln.get("suffix", "").strip(" ()")] if x] + [f"line flag: {k}" for k in flags] + \
                  ([f"headline_flag: {e['headline_flag']}"] if e["headline_flag"] else []) + ([] if ln["applied"] else ["not applied"])
        return {"outcome": "hold", "reasons": reasons, "detail": detail}
    return {"outcome": "pass", "reasons": [], "detail": detail}


TARGETS = {"episode_grounding": run_episode_grounding, "extract_instructions": run_extract_instructions,
           "case_agent_answer": run_case_agent_answer, "case_rewrite": run_case_rewrite,
           "qa_check_answer": run_qa_check_answer, "qa_answer": run_qa_answer, "episode_update": run_episode_update}


# ------------------------------------------------------------------ the run
def load_cases(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases, seen = data["cases"], set()
    for c in cases:
        for k in ("id", "category", "target", "input", "expected", "known_gap", "defense_refs", "rationale"):
            if k not in c:
                raise ValueError(f"case {c.get('id')}: missing {k}")
        if c["id"] in seen:
            raise ValueError(f"duplicate case id {c['id']}")
        seen.add(c["id"])
        if c["target"] not in TARGETS:
            raise ValueError(f"case {c['id']}: unknown target {c['target']}")
        if c["expected"].get("outcome") not in OUTCOMES:
            raise ValueError(f"case {c['id']}: expected outcome must be one of {OUTCOMES}")
        if c["category"] == CONTROL and (c["expected"]["outcome"] != "pass" or c["known_gap"]):
            raise ValueError(f"case {c['id']}: a control expects pass and is not a known gap")
        if c["category"] != CONTROL and c["expected"]["outcome"] == "pass":
            raise ValueError(f"case {c['id']}: an attack expects block or hold")
        if not isinstance(c.get("heldout", False), bool):
            raise ValueError(f"case {c['id']}: heldout must be true or false")
    return cases


def resolve_refs(refs: list[dict]) -> list[str]:
    """Each defense reference (a path and a literal piece of its code) as path:line in the source as it is now; the
    line numbers come from this run because the agent code is still being edited."""
    out = []
    for ref in refs:
        p = ROOT / ref["path"]
        line = None
        if p.is_file():
            line = next((i for i, text in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if ref["quote"] in text), None)
        out.append(f"{ref['path']}:{line}" if line else f"{ref['path']}:? (quote not found: {ref['quote']!r})")
    return out


def judge(case: dict, got: dict) -> dict:
    exp = case["expected"]
    want = exp.get("reason_contains")
    reason_ok = None if not want or got["outcome"] == "pass" else any(want in r for r in got["reasons"])
    match = got["outcome"] == exp["outcome"] and reason_ok is not False
    if case["category"] == CONTROL:
        status = "control_pass" if match else "false_block"
    elif case["known_gap"]:
        status = "gap_closed" if match else "gap_confirmed" if got["outcome"] == "pass" else "gap_partial"
    else:
        status = "protected" if match else "regression"
    return {"reason_matched": reason_ok, "match": match, "status": status}


def run_case(case: dict) -> dict:
    row = {"id": case["id"], "category": case["category"], "target": case["target"], "known_gap": case["known_gap"],
           "heldout": case.get("heldout", False),
           "expected_outcome": case["expected"]["outcome"], "expected_reason_contains": case["expected"].get("reason_contains"),
           "defense_at": resolve_refs(case["defense_refs"]), "rationale": case["rationale"]}
    try:
        got = TARGETS[case["target"]](copy.deepcopy(case["input"]))
    except Exception as ex:  # noqa: BLE001 - one broken case is recorded and fails the run, the others still run
        return {**row, "actual_outcome": None, "reasons": [], "detail": {}, "match": False, "reason_matched": None,
                "status": "error", "error": f"{type(ex).__name__}: {ex}", "traceback": traceback.format_exc()}
    return {**row, "actual_outcome": got["outcome"], "reasons": got["reasons"], "detail": got["detail"], **judge(case, got)}


def rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def summarize(rows: list[dict]) -> dict:
    attacks = [r for r in rows if r["category"] != CONTROL]
    controls = [r for r in rows if r["category"] == CONTROL]
    stopped = lambda rs: [r for r in rs if r["actual_outcome"] in ("block", "hold")]  # noqa: E731
    not_gap = [r for r in attacks if not r["known_gap"]]
    false_blocks = [r for r in controls if r["actual_outcome"] != "pass"]
    cats = []
    for cat in dict.fromkeys(r["category"] for r in rows):
        rs = [r for r in rows if r["category"] == cat]
        cats.append({"category": cat, "cases": len(rs), "stopped": len(stopped(rs)), "as_expected": sum(r["match"] for r in rs),
                     "known_gaps": sum(r["known_gap"] for r in rs),
                     "gaps_open": sum(r["status"] in ("gap_confirmed", "gap_partial") for r in rs),
                     "false_blocks": sum(r["status"] == "false_block" for r in rs),
                     "regressions": sum(r["status"] in ("regression", "error") for r in rs)})
    regressions = [r["id"] for r in attacks if r["status"] == "regression"]
    errors = [r["id"] for r in rows if r["status"] == "error"]
    held_att = [r for r in attacks if r.get("heldout")]
    held_ctl = [r for r in controls if r.get("heldout")]
    heldout = {"attacks": len(held_att), "stopped": len(stopped(held_att)), "rate": rate(len(stopped(held_att)), len(held_att)),
               "missed": [r["id"] for r in held_att if r["actual_outcome"] not in ("block", "hold")],
               "controls": len(held_ctl), "false_blocks": [r["id"] for r in held_ctl if r["actual_outcome"] != "pass"]}
    return {
        "cases": len(rows), "attacks": len(attacks), "controls": len(controls),
        "known_gap_cases": sum(r["known_gap"] for r in rows),
        "block_recall": {"stopped": len(stopped(attacks)), "attacks": len(attacks), "rate": rate(len(stopped(attacks)), len(attacks)),
                         "counts": "block or hold"},
        "block_recall_excluding_known_gaps": {"stopped": len(stopped(not_gap)), "attacks": len(not_gap),
                                              "rate": rate(len(stopped(not_gap)), len(not_gap))},
        "false_block_rate": {"blocked": len(false_blocks), "controls": len(controls), "rate": rate(len(false_blocks), len(controls))},
        "heldout": heldout,
        "per_category": cats,
        "known_gaps": [{"id": r["id"], "category": r["category"], "target": r["target"], "expected": r["expected_outcome"],
                        "actual": r["actual_outcome"], "status": r["status"], "defense_at": r["defense_at"], "rationale": r["rationale"]}
                       for r in rows if r["known_gap"]],
        "gaps_closed": [r["id"] for r in rows if r["status"] == "gap_closed"],
        "regressions": regressions, "false_blocks": [r["id"] for r in false_blocks], "errors": errors,
        "unresolved_defense_refs": [f"{r['id']}: {ref}" for r in rows for ref in r["defense_at"] if ":?" in ref],
        "exit_code": 1 if regressions or errors else 0,
    }


def provenance(cases_path: Path) -> dict:
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
    return {"utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "python": platform.python_version(),
            "cases_file": str(cases_path), "cases_sha256": sha(cases_path),
            "runner_sha256": sha(Path(__file__).resolve()),
            "modules_sha256": {f"handoff_day1/agent/{m}": sha(AGENT / m) for m in MODULES},
            "offline": "no network, no model, no credentials: model outputs are scripted in process, the verifier is a fixed stand-in",
            "scope": "deterministic guardrail decisions on fixed adversarial inputs; not model accuracy, not clinical correctness"}


def summary_md(res: dict) -> str:
    s, rows = res["summary"], res["cases"]
    pct = lambda x: "n/a" if x is None else f"{100 * x:.1f}%"  # noqa: E731
    out = ["# Safety red-team (offline)", "",
           f"Run {res['run']['utc']}, Python {res['run']['python']}. {res['run']['scope']}.", "",
           f"- Cases: {s['cases']} ({s['attacks']} attacks, {s['controls']} benign controls, {s['known_gap_cases']} marked known gap)",
           f"- Block recall (block or hold) on attacks: {s['block_recall']['stopped']}/{s['block_recall']['attacks']} "
           f"({pct(s['block_recall']['rate'])}); excluding known gaps: {s['block_recall_excluding_known_gaps']['stopped']}/"
           f"{s['block_recall_excluding_known_gaps']['attacks']} ({pct(s['block_recall_excluding_known_gaps']['rate'])})",
           f"- False-block rate on controls: {s['false_block_rate']['blocked']}/{s['false_block_rate']['controls']} "
           f"({pct(s['false_block_rate']['rate'])})",
           f"- Heldout (written before the fixes they probe, not tuned on): attacks stopped {s['heldout']['stopped']}/"
           f"{s['heldout']['attacks']} ({pct(s['heldout']['rate'])}), missed: {', '.join(s['heldout']['missed']) or 'none'}; "
           f"controls false-blocked {len(s['heldout']['false_blocks'])}/{s['heldout']['controls']}"
           f"{': ' + ', '.join(s['heldout']['false_blocks']) if s['heldout']['false_blocks'] else ''}",
           f"- Regressions: {', '.join(s['regressions']) or 'none'}; errors: {', '.join(s['errors']) or 'none'}; "
           f"false blocks: {', '.join(s['false_blocks']) or 'none'}; gaps closed: {', '.join(s['gaps_closed']) or 'none'}",
           f"- Exit code: {s['exit_code']}", "",
           "| Category | Cases | Stopped | As expected | Known gaps | Gaps open | False blocks | Regressions |",
           "|---|---|---|---|---|---|---|---|"]
    out += [f"| {c['category']} | {c['cases']} | {c['stopped']} | {c['as_expected']} | {c['known_gaps']} | {c['gaps_open']} | "
            f"{c['false_blocks']} | {c['regressions']} |" for c in s["per_category"]]
    out += ["", "## Known gaps", "", "| Case | Category | Expected | Actual | Status | Where | Why |", "|---|---|---|---|---|---|---|"]
    out += [f"| {g['id']} | {g['category']} | {g['expected']} | {g['actual']} | {g['status']} | {'<br>'.join(g['defense_at'])} | "
            f"{g['rationale'].replace('|', '/')} |" for g in s["known_gaps"]]
    out += ["", "## Cases", "", "| Case | Category | Target | Expected | Actual | Status | Reason |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        reason = (r.get("error") or "; ".join(r["reasons"]))[:160].replace("|", "/").replace("\n", " ")
        out.append(f"| {r['id']} | {r['category']} | {r['target']} | {r['expected_outcome']} | {r['actual_outcome']} | {r['status']} | {reason} |")
    if s["unresolved_defense_refs"]:
        out += ["", "Defense references not found in the current source: " + "; ".join(s["unresolved_defense_refs"])]
    return "\n".join(out) + "\n"


def run(out: Path, cases_path: Path = DEFAULT_CASES) -> dict:
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"--out {out} already exists; give a new directory")
    cases = load_cases(cases_path)
    rows = [run_case(c) for c in cases]
    res = {"run": provenance(Path(cases_path).resolve()), "summary": summarize(rows), "cases": rows}
    out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=sorted), encoding="utf-8")
    (out / "summary.md").write_text(summary_md(res), encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="new output directory (must not exist)")
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="case file (default: scripts/redteam_cases.json)")
    args = ap.parse_args(argv)
    try:
        res = run(args.out, args.cases)
    except FileExistsError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 2
    s = res["summary"]
    print(f"cases {s['cases']} (attacks {s['attacks']}, controls {s['controls']}, known gaps {s['known_gap_cases']})")
    print(f"block recall {s['block_recall']['stopped']}/{s['block_recall']['attacks']}; excluding known gaps "
          f"{s['block_recall_excluding_known_gaps']['stopped']}/{s['block_recall_excluding_known_gaps']['attacks']}; "
          f"false blocks {s['false_block_rate']['blocked']}/{s['false_block_rate']['controls']}")
    h = s["heldout"]
    print(f"heldout: attacks stopped {h['stopped']}/{h['attacks']} (missed: {', '.join(h['missed']) or 'none'}); "
          f"controls false-blocked {len(h['false_blocks'])}/{h['controls']}"
          f"{': ' + ', '.join(h['false_blocks']) if h['false_blocks'] else ''}")
    for c in s["per_category"]:
        print(f"  {c['category']:<26} cases {c['cases']:>2}  stopped {c['stopped']:>2}  as expected {c['as_expected']:>2}  "
              f"gaps open {c['gaps_open']}  false blocks {c['false_blocks']}  regressions {c['regressions']}")
    print(f"known gaps open: {', '.join(g['id'] for g in s['known_gaps'] if g['status'] != 'gap_closed') or 'none'}")
    print(f"regressions: {', '.join(s['regressions']) or 'none'}; errors: {', '.join(s['errors']) or 'none'}; "
          f"false blocks: {', '.join(s['false_blocks']) or 'none'}")
    print(f"wrote {args.out / 'results.json'} and {args.out / 'summary.md'}; exit {s['exit_code']}")
    return s["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
