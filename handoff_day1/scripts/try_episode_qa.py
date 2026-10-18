#!/usr/bin/env python3
"""Ask a question, on a real model: the family timeline's question answering (agent/episode_qa.py) against an
OpenAI-compatible endpoint (AMD Token Factory: Gemma-4-31B-IT).

Replays the fictional demo story (care_cases/episode_hip_fracture.json) to four points (after the ward notice, after the
operation, after going home moved to Saturday, after she went home) and asks a fixed set of family questions at each.
The model chooses the sentences that answer each question (it writes no answer text; the line above the sentences is
fixed text). Its choice is checked as on the page (real sentence ids, "no" with nothing cited) and completed (a
replaced sentence brings the one that stands now); a refused choice is sent back once with the reasons, then the
deterministic choice is used. The run records how each answer ended (the model's first try, after one correction, or
the fallback) and whether the shown sentences include the one the question needs.

  export CARERELAY_LLM_BASE_URL=https://.../v1 CARERELAY_LLM_MODEL=Gemma-4-31B-IT CARERELAY_LLM_API_KEY=...
  python scripts/try_episode_qa.py --out outputs/episode_qa

Writes <out>/episode_qa.json (every question, answer, cited sentence and model call) and <out>/summary.md. The key is
never written; the endpoint is recorded as scheme and host only. Stdlib only. Exit code 0 when at least one model call
came back and every nonzero intended expectation passed; 3 when an expectation failed; 2 when every model call failed; 1 (or
argparse's 2 for a bad option) for a usage problem.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
import episode_qa as Q  # noqa: E402
from episode import Episode, load_scenario  # noqa: E402
from llm_client import make_client  # noqa: E402

# Stable story milestones (inserting an update must not move the discharge test).
POINTS = {
    "u03": [("What is the ward phone number?", "david", {"cite_any": ["u03.5"]}),
        ("Can she eat before the operation?", "mia", {"cite_any": ["u02.4"]}),
        ("When are visiting hours?", "joy", {"cite_any": ["u03.2"]}),
        ("When is she going home?", "mia", {"covered": "no"})],
    "u05": [("Did the operation go well?", "mia", {"cite_any": ["u05.1", "u05.2"]}),
        ("When is she going home?", "david", {"cite_any": ["u05.4"]}),
        ("Who is the doctor in charge?", "mia", {"cite_any": ["u02.5"]})],
    "u07": [("When is she going home?", "mia", {"cite_any": ["u07.2"]}),
        ("Can she get out of bed on her own?", "david", {"cite_any": ["u05.3", "u06.1", "u07.1"]}),
        ("Is she walking yet?", "mia", {"cite_any": ["u05.3", "u06.1", "u07.1"]}),
        ("Does she have dementia?", "mia", {"covered": "no"})],
    "u10": [("Which medicines did they stop?", "mia", {"cite_any": ["u08.7"]}),
         ("What should we watch for at home?", "joy", {"cite_any": ["u09.5"]}),
         ("When is the fracture clinic appointment?", "david", {"cite_any": ["u09.4"]}),
         ("Is she still on the ward?", "mia", {"cite_any": ["u09.1"]}),
         ("Can she have a bath at home?", "joy", {})],
}


def met(expect: dict, r: dict) -> bool | None:
    """Whether the shown sentences include the one the question needs; None when the question sets no expectation."""
    if not expect:
        return None
    cited = [u["sid"] for u in r["quotes"]]
    return ((not expect.get("cite_any") or any(s in cited for s in expect["cite_any"]))
            and (not expect.get("covered") or r["covered"] == expect["covered"]))


def result_exit_code(successful_calls: int, totals: dict) -> int:
    if successful_calls == 0:
        return 2
    return 0 if totals["expectations"] > 0 and totals["expectations_met"] == totals["expectations"] else 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output folder (created)")
    args = ap.parse_args()
    if not os.environ.get("CARERELAY_LLM_BASE_URL") or not os.environ.get("CARERELAY_LLM_MODEL"):
        print("set CARERELAY_LLM_BASE_URL (ending in /v1), CARERELAY_LLM_MODEL and CARERELAY_LLM_API_KEY", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    llm = make_client(max_tokens=600)
    if llm is None:
        print("this run needs a model: unset CARERELAY_LLM_BACKEND=none", file=sys.stderr)
        return 1
    answer = Q.episode_answerer(llm)
    base = urlsplit(os.environ["CARERELAY_LLM_BASE_URL"])
    sc = load_scenario(ROOT / "care_cases" / "episode_hip_fracture.json")
    result = {"created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "endpoint": f"{base.scheme}://{base.hostname}" + (f":{base.port}" if base.port else ""), "model": llm.model,
              "json_mode": "prompted" if os.environ.get("CARERELAY_LLM_GUIDED_JSON") == "0" else "guided when offered",
              "note": "fictional demo story; the model chooses the sentences, the lead is fixed text; every shown choice passed "
                      "agent/episode_qa.py's checks (the model's, or the deterministic fallback's)", "questions": []}
    t0 = time.monotonic()
    for milestone, asks in POINTS.items():
        n = next(i for i, u in enumerate(sc["updates"], 1) if u["update_id"] == milestone)
        ep = Episode(sc)
        for u in sc["updates"][:n]:
            ep.add_update(u)
        for question, asker, expect in asks:
            calls = len(answer.log)
            r = answer(ep, question, asker)
            row = {"after_updates": n, "latest_update": sc["updates"][n - 1]["update_id"], "question": question, "asked_by": asker,
                   "method": r["method"], "answer": r["answer"], "covered": r["covered"],
                   "cited": [{"sid": u["sid"], "text": u["text"], "state": u["state"], "authority": u["authority"]} for u in r["quotes"]],
                   "ask_ward": r["ask_ward"]["text"] if r["ask_ward"] else None, "attempts": r["attempts"], "error": r["error"],
                   "expect": expect, "expectation_met": met(expect, r), "model_calls": answer.log[calls:]}
            result["questions"].append(row)
            print(f"[after {row['latest_update']}] {question}\n  {r['method']}: {r['answer']}\n  cited {[c['sid'] for c in row['cited']]}"
                  f"{'' if row['expectation_met'] in (True, None) else '  (EXPECTED ' + json.dumps(expect) + ')'}"
                  + "".join(f"\n  attempt {a['attempt']} refused: {'; '.join(a['violations'])[:300]}" for a in r["attempts"] if a["violations"]),
                  flush=True)
    calls = [c for q in result["questions"] for c in q["model_calls"]]
    ok_calls = [c for c in calls if "error" not in c]
    lat = sorted(c["latency_s"] for c in ok_calls if c.get("latency_s") is not None)
    result["totals"] = {
        "questions": len(result["questions"]), "methods": dict(collections.Counter(q["method"] for q in result["questions"])),
        "expectations_met": sum(1 for q in result["questions"] if q["expectation_met"]),
        "expectations": sum(1 for q in result["questions"] if q["expectation_met"] is not None), "model_calls": len(calls),
        "model_calls_failed": len(calls) - len(ok_calls),
        "latency_s_p50": lat[len(lat) // 2] if lat else None, "latency_s_max": lat[-1] if lat else None,
        "wall_s": round(time.monotonic() - t0, 1),
        "fallback_off_topic": sum(1 for q in result["questions"] for a in q["attempts"] if a["attempt"] == "fallback" and a["violations"]),
    }
    (out / "episode_qa.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.md").write_text(summary(result), encoding="utf-8")
    print(f"wrote {out / 'episode_qa.json'} and {out / 'summary.md'}\n{json.dumps(result['totals'])}")
    return result_exit_code(len(ok_calls), result["totals"])


def summary(result: dict) -> str:
    t = result["totals"]

    def cell(text) -> str:   # one table cell: one line, no pipes, no raw HTML
        return " ".join(str(text).split())[:160].replace("|", "\\|").replace("<", "&lt;")
    m = t["methods"]
    lines = [f"# Ask a question: `{result['model']}` ({result['endpoint']})", "",
             f"Date (UTC): {result['created_utc']}. Fictional demo story, replayed to four points; {t['questions']} family "
             "questions. The model chooses the sentences (it writes no answer text); a refused choice was sent back once with "
             "the reasons, then the deterministic choice was shown. Every shown choice passed the checks of `agent/episode_qa.py`.", "",
             "| What | Result |", "|---|---|",
             f"| The model's choice of sentences shown | {m.get('llm_first_try', 0)} first try, {m.get('llm_after_retry', 0)} after one correction |",
             f"| Deterministic choice shown | {m.get('fallback', 0)} after two refused choices, {m.get('fallback_unavailable', 0)} with no reply |",
             f"| Shown sentences include the one the question needs | {t['expectations_met']}/{t['expectations']} "
             f"(questions with an expected sentence) |",
             f"| Model calls | {t['model_calls']} ({t['model_calls_failed']} failed); latency p50 {t['latency_s_p50']} s, max {t['latency_s_max']} s |",
             f"| Wall time | {t['wall_s']} s |",
             f"| Deterministic choices off the question's topic, shown as \"The updates don't say.\" | {t['fallback_off_topic']} |", "",
             "| After | Question | How it ended | Answer | Cited | Expected? |", "|---|---|---|---|---|---|"]
    for q in result["questions"]:
        cited = "; ".join(f"{c['sid']} ({c['state']}{', family' if c['authority'] == 'family' else ''})" for c in q["cited"])
        lines.append(f"| {q['latest_update']} | {cell(q['question'])} | {q['method']} | {cell(q['answer'])} | {cell(cited) or '-'} | "
                     f"{'-' if q['expectation_met'] is None else 'yes' if q['expectation_met'] else 'no: ' + cell(json.dumps(q['expect']))} |")
    refused = [(q, a) for q in result["questions"] for a in q["attempts"] if a["attempt"] != "fallback" and a["violations"]]
    if refused:
        lines += ["", "## Model choices the checks refused", ""]
        lines += [f"- after {q['latest_update']}, \"{cell(q['question'])}\", attempt {a['attempt']}: {cell('; '.join(a['violations']))}"
                  for q, a in refused]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
