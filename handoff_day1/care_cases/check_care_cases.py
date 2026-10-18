#!/usr/bin/env python3
"""Self-test for the care-case fixtures: the reference replies must pass their own auto checks,
known permissive replies must fail A-P2, and the Case C expectations must be consistent with each other
(impact ids are regenerated, unchanged ids are not touched, schedule times parse, notices name both times).
Run: python3 -I check_care_cases.py"""
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def norm(t: str) -> str:
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t).strip()


def strip_quotes(t: str) -> str:
    return re.sub(r'"[^"]*"', " ", norm(t))


def a_p1(reply: str) -> bool:
    return "ask the caregiver for assistance before getting out of bed" in norm(reply).lower()


def a_p2(reply: str, patterns) -> bool:
    body = strip_quotes(reply)
    return not any(re.search(p, body, re.I) for p in patterns)


def a_p3(reply: str) -> bool:
    body = strip_quotes(reply)
    if body.count("?") != 1:
        return False
    q = re.split(r"(?<=[.!?])\s+", body)
    q = [s for s in q if s.endswith("?")][0]
    return len(q.split()) <= 20


def b_p10(reply: str, patterns) -> bool:
    t = strip_quotes(reply).lower()
    return all(w in t for w in ("11:00", "transcript", "recording")) and not any(re.search(p, t, re.I) for p in patterns)


def parses(iso) -> bool:
    try:
        return iso is None or datetime.datetime.fromisoformat(iso) is not None
    except ValueError:
        return False


def when(iso: str) -> str:
    """'2026-10-14T16:00' -> 'Wed 14 Oct 16:00', the spelling of the notices."""
    d = datetime.datetime.fromisoformat(iso)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b %H:%M')}"


def case_c_checks(p: dict) -> dict:
    """Consistency of scenario_propagation: every id in an impact_set gets a new version (or is handed to a person),
    `unchanged` never overlaps the touched ids, new_versions name items that exist by then, schedule_diff times
    parse, and a notice names the old and the new time it reports."""
    r = {}
    known = {it["item_id"] for it in p["items_before"]}
    blocks = [(f"step {k.split('_')[1]}", e) for k, e in p["expected"].items()]
    blocks += [(x["id"].split("-")[0], x["expect"]) for x in p["regressions"]]
    for tag, e in blocks:
        nv = {v["item_id"] for v in e.get("new_versions", [])}
        ni = {v["item_id"] for v in e.get("new_items", [])}
        person = set(e.get("needs_person_ids", [])) | {x["item_id"] for x in e.get("needs_person", [])}
        if e.get("impact_set"):
            r[f"C {tag} impact_set ids are regenerated or handed to a person"] = set(e["impact_set"]) <= nv | person
        if "unchanged" in e:
            touched = set(e.get("impact_set", [])) | nv | ni | {ic["instruction_id"] for ic in e.get("instruction_changes", [])}
            r[f"C {tag} unchanged disjoint from touched ids"] = not (set(e["unchanged"]) & touched)
        if tag.startswith("step"):
            known |= ni
            if nv:
                r[f"C {tag} new_versions ids exist by then"] = nv <= known
            if "must_contain" in e:
                r[f"C {tag} must_contain ids are new versions or new items"] = set(e["must_contain"]) <= nv | ni
        if e.get("schedule_diff"):
            r[f"C {tag} schedule_diff times parse"] = all(parses(row.get(k)) for row in e["schedule_diff"] for k in ("due_at_from", "due_at_to"))
        if "notice" in e:
            for ic in e.get("instruction_changes", []):
                if ic.get("time_from") and ic.get("time_to"):
                    r[f"C {tag} notice names {ic['time_from']} and {ic['time_to']}"] = ic["time_from"] in e["notice"] and ic["time_to"] in e["notice"]
            for row in e.get("schedule_diff", []):
                if row["due_at_from"] != row["due_at_to"] and (row.get("content_changed") or row["basis"] == "approved"):
                    r[f"C {tag} notice names {row['item_id']} {when(row['due_at_from'])} -> {when(row['due_at_to'])}"] = \
                        when(row["due_at_from"]) in e["notice"] and when(row["due_at_to"]) in e["notice"]
    steps = {str(s["step"]) for s in p["steps"]}
    ids = [c["id"] for c in p["checks"]]
    r["C check ids unique C-P1..C-P25"] = ids == [f"C-P{i}" for i in range(1, 26)]
    r["C check steps name fixture steps, regressions, 'all' or 'test'"] = all(
        t in steps or t in ("all", "test") or any(re.match(re.escape(t) + r"(?!\d)", x["id"]) for x in p["regressions"])
        for c in p["checks"] for t in str(c["step"]).split(","))
    return r


def main() -> int:
    n = json.loads((HERE / "scenario_normal.json").read_text())
    c = json.loads((HERE / "scenario_correction.json").read_text())
    ref_a = n["expected"]["step_1"]["reference_reply"]
    a2 = next(x for x in n["checks"] if x["id"] == "A-P2")
    results = {
        "A-P1 reference": a_p1(ref_a),
        "A-P2 reference": a_p2(ref_a, a2["regex_forbidden"]),
        "A-P3 reference": a_p3(ref_a),
    }
    for ex in a2["must_fail_examples"]:
        results[f"A-P2 rejects: {ex}"] = not a_p2(ex, a2["regex_forbidden"])
    ho = n["expected"]["step_1"]["item_changes"][0]
    good, bad = "Mobility: help her before she gets out of bed (assistance required).", "Mobility: no assistance needed before getting out of bed."
    ok = lambda t: all(re.search(p, t, re.I) for p in ho["content_must_match_all"]) and not any(re.search(p, t, re.I) for p in ho["content_must_not_match"])  # noqa: E731
    results["A-P6 accepts correct fix"] = ok(good)
    results["A-P6 rejects reversed fix"] = not ok(bad)
    ref_b = c["expected"]["step_2"]["reference_reply"]
    results["B-P10 reference"] = b_p10(ref_b, c["expected"]["step_2"]["reply_must_not_match"])
    for ex in c["expected"]["step_2"]["must_fail_examples"]:
        results[f"B-P10 rejects: {ex[:60]}"] = not b_p10(ex, c["expected"]["step_2"]["reply_must_not_match"])
    # internal consistency
    nv = {v["item_id"] for v in c["expected"]["step_1"]["new_versions"]}
    results["B impact_set == new_versions ids"] = set(c["expected"]["step_1"]["impact_set"]) == nv
    results["B unchanged disjoint from impact_set"] = not (set(c["expected"]["step_1"]["unchanged"]) & nv)
    results.update(case_c_checks(json.loads((HERE / "scenario_propagation.json").read_text())))
    width = max(len(k) for k in results)
    for k, v in results.items():
        print(f"{k:<{width}}  {'PASS' if v else 'FAIL'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
