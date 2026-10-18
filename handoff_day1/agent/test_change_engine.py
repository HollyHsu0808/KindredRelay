#!/usr/bin/env python3
"""Regression tests for the update-propagation engine (stdlib unittest, no LLM).

The Case C fixture (care_cases/scenario_propagation.json) is walked step by step and every step is graded against its
`expected` block; the `regressions` block turns the probes that found the prototype's defects into fixed checks. All
expected values live in the JSON, none in this file. The fixture walker (run_fixture, run_regressions, run_tables) is
importable so the eval and the prototype harness grade with the same code.

Usage: python test_change_engine.py      (exit code 1 on any failure)
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import change_engine as ce  # noqa: E402
from change_engine import PropagatingStore, unchanged_hash  # noqa: E402
from case_store import CaseStore  # noqa: E402

CASES = HERE.parent / "care_cases"
FIXTURE = CASES / "scenario_propagation.json"


# ---------------------------------------------------------------- grading helpers
def subset(exp, act, path: str = "") -> list[str]:
    """Differences between an expected value and the actual one: dict keys present in `exp` must match, lists must
    have the same length and match element-wise, scalars must be equal."""
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            return [f"{path or '.'}: expected an object, got {act!r}"]
        return [d for k, v in exp.items() for d in (subset(v, act[k], f"{path}.{k}") if k in act else [f"{path}.{k}: missing"])]
    if isinstance(exp, list):
        if not isinstance(act, list) or len(act) != len(exp):
            return [f"{path}: expected {len(exp)} entries, got {act!r}"]
        return [d for i, (e, a) in enumerate(zip(exp, act)) for d in subset(e, a, f"{path}[{i}]")]
    return [] if exp == act else [f"{path}: expected {exp!r}, got {act!r}"]


def version_of(store, item_id: str, version: int) -> dict:
    return next((v for v in store.items.get(item_id, []) if v.get("version") == version), {})


def hashes(store) -> dict[str, str]:
    h = {i: unchanged_hash(store.latest(i)) for i in store.items}
    h.update({i: unchanged_hash(ins) for i, ins in store.instructions.items()})
    return h


def proposed(store) -> dict[str, tuple]:
    return {i: ((v[-1].get("schedule") or {}).get("proposed_due_at"), (v[-1].get("schedule") or {}).get("proposed_assignee"))
            for i, v in store.items.items() if v[-1].get("kind") == "task"}


def merge(base, override):
    """Deep merge for fixture overrides: objects merge key by key, lists and scalars are replaced."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = merge(base.get(k), v) if k in base else v
        return out
    return copy.deepcopy(override)


def change_for(sc: dict, step: dict) -> dict:
    """The change a step sends: its own, or another step's (replay / variant) or a regression's with an override applied."""
    if "change_from_regression" in step:
        base = next(r for r in sc["regressions"] if r["id"] == step["change_from_regression"])["change"]
        return merge(base, step.get("override", {}))
    ref = step.get("replay_of_step", step.get("change_from_step"))
    if ref is None:
        return copy.deepcopy(step["change"])
    base = next(s for s in sc["steps"] if s["step"] == ref)["change"]
    return merge(base, step.get("override", {}))


class Grader:
    def __init__(self):
        self.results: list[dict] = []

    def check(self, cid: str, ok, detail: str = "", step=None) -> None:
        self.results.append({"id": cid, "pass": bool(ok), "detail": "" if ok else str(detail)[:600], "step": step})

    def sub(self, cid: str, exp, act, step=None) -> None:
        d = subset(exp, act)
        self.check(cid, not d, "; ".join(d), step)

    def grade_event(self, tag: str, store, ev: dict, exp: dict, before: dict, step=None) -> None:
        """Grade a change_event (and the store after it) against an expected block. `before` holds the hashes,
        proposed schedules, pending count and version count taken before the step."""
        for k in ("change_id", "status", "awaiting_review", "replayed", "matched_by", "refused", "seq", "discarded_content", "impact_set",
                  "citation_repoints", "needs_person"):
            if k in exp:
                self.check(f"{tag} {k}", ev.get(k) == exp[k], f"{ev.get(k)!r} != {exp[k]!r}", step)
        for k in ("instruction_changes", "schedule_diff", "new_items", "new_versions", "source_added", "not_applied", "pending_changes", "reviewed", "job"):
            if k in exp:
                self.sub(f"{tag} {k}", exp[k], ev.get(k), step)
        if "needs_person_ids" in exp:
            self.check(f"{tag} needs_person", sorted(x["item_id"] for x in ev["needs_person"]) == exp["needs_person_ids"], ev["needs_person"], step)
        if "notice" in exp:
            self.check(f"{tag} notice verbatim", ev.get("notice") == exp["notice"], f"got {ev.get('notice')!r}", step)
        self.grade_state(tag, store, exp, before, step)
        if "untouched_hashes" in ev and "unchanged" in exp:
            after = hashes(store)
            bad = [i for i, h in ev["untouched_hashes"].items() if after.get(i) != h]
            self.check(f"{tag} untouched_hashes match the state after the event", not bad, bad, step)
            touched = set(ev["impact_set"]) | {n["item_id"] for n in ev["new_items"]} | {n["item_id"] for n in ev["new_versions"]} \
                | {ic["instruction_id"] for ic in ev["instruction_changes"]}
            self.check(f"{tag} untouched_hashes exclude touched ids", not (touched & set(ev["untouched_hashes"])), touched & set(ev["untouched_hashes"]), step)
        if "untouched_count" in exp:
            self.check(f"{tag} untouched_count", len(ev.get("untouched_hashes") or {}) == exp["untouched_count"], len(ev.get("untouched_hashes") or {}), step)

    def grade_state(self, tag: str, store, exp: dict, before: dict, step=None) -> None:
        if "case_version_after" in exp:
            self.check(f"{tag} case_version", store.case_version == exp["case_version_after"], store.case_version, step)
        if "seq_after" in exp:
            self.check(f"{tag} seq", store.seq == exp["seq_after"], store.seq, step)
        for key in ("new_versions_review_status", "new_items_review_status"):
            if key in exp:
                ids = [x["item_id"] for x in exp.get(key.split("_review")[0], [])]
                got = {i: store.latest(i)["review_status"] if i in store.items else "missing" for i in ids}
                self.check(f"{tag} {key}", all(s == exp[key] for s in got.values()), got, step)
        if "must_contain" in exp:
            bad = {}
            for i, must in exp["must_contain"].items():
                c = store.latest(i)["content"] if i in store.items else ""   # a missing item fails its content check
                if not all(m.lower() in c.lower() for m in must) or any(b.lower() in c.lower() for b in exp.get("must_not_contain", [])):
                    bad[i] = c or "missing"
            self.check(f"{tag} regenerated content", not bad, bad, step)
        if "instruction_after" in exp:
            d = [x for i, e in exp["instruction_after"].items() for x in subset(e, store.instructions.get(i), i)]
            self.check(f"{tag} instruction_after", not d, d, step)
        for key in ("schedule_approved_before_review", "schedule_after_review", "schedule_after", "schedule"):
            if key in exp:
                d = [x for i, e in exp[key].items() for x in subset(e, store.latest(i).get("schedule"), i)]
                self.check(f"{tag} {key}", not d, d, step)
        if "task_status" in exp:
            d = {i: store.latest(i)["schedule"].get("status") for i, s in exp["task_status"].items() if store.latest(i)["schedule"].get("status") != s}
            self.check(f"{tag} task_status", not d, d, step)
        if "review_status" in exp:
            d = {i: store.latest(i)["review_status"] for i, s in exp["review_status"].items() if store.latest(i)["review_status"] != s}
            self.check(f"{tag} review_status", not d, d, step)
        if "stale_items" in exp:
            self.check(f"{tag} stale_items", all(store.latest(i)["review_status"] == "stale" for i in exp["stale_items"]),
                       {i: store.latest(i)["review_status"] for i in exp["stale_items"]}, step)
        if "new_pending" in exp:
            new_p = store.pending[before["pending"]:]
            self.sub(f"{tag} new_pending", exp["new_pending"], new_p, step)
        if "no_new_pending" in exp:
            self.check(f"{tag} no_new_pending", len(store.pending) == before["pending"], len(store.pending), step)
        if "pending_count" in exp:
            self.check(f"{tag} pending_count", len(store.pending) == exp["pending_count"], len(store.pending), step)
        if "pending_count_after" in exp:
            self.check(f"{tag} pending_count_after", len(store.pending) == exp["pending_count_after"], len(store.pending), step)
        for key in ("pending_closed", "pending_after"):
            if key in exp:
                by_id = {p["pending_id"]: p for p in store.pending}
                items = exp[key] if isinstance(exp[key], list) else [{"pending_id": k, **v} for k, v in exp[key].items()]
                d = [x for e in items for x in subset(e, by_id.get(e["pending_id"]), e["pending_id"])]
                self.check(f"{tag} {key}", not d, d, step)
        if "unchanged" in exp:
            after = hashes(store)
            bad = [i for i in exp["unchanged"] if before["hashes"].get(i) != after.get(i)]
            self.check(f"{tag} unchanged ids keep their hash (incl. approved schedule)", not bad, bad, step)
            prop = proposed(store)
            moved = [i for i, p in before["proposed"].items() if i in prop and prop[i] != p and i not in exp.get("allowed_schedule_follow", [])
                     and i in exp["unchanged"]]
            self.check(f"{tag} proposed schedule moves only for allowed_schedule_follow", not moved, moved, step)
        if "superseded_old_versions" in exp:
            bad = {i: version_of(store, i, v) for i, v in exp["superseded_old_versions"].items()
                   if version_of(store, i, v).get("review_status") != "superseded" or version_of(store, i, v).get("superseded_by") != v + 1}
            self.check(f"{tag} old versions superseded with superseded_by", not bad, bad, step)
        if "no_new_versions" in exp:
            n = sum(len(v) for v in store.items.values())
            self.check(f"{tag} no_new_versions", n == before["versions"], n, step)
        if "source_not_stored" in exp:
            self.check(f"{tag} source_not_stored", store.latest_revision(exp["source_not_stored"]) is None, exp["source_not_stored"], step)
        if "superseded_on_arrival_by" in exp:
            d = {s: store.sources.get((s, "r1"), {}).get("superseded_on_arrival_by") for s, v in exp["superseded_on_arrival_by"].items()
                 if store.sources.get((s, "r1"), {}).get("superseded_on_arrival_by") != v}
            self.check(f"{tag} superseded_on_arrival_by", not d, d, step)
        if "job_after" in exp:
            self.sub(f"{tag} job_after", exp["job_after"], store.jobs.get(exp["job_after"]["job_id"]), step)
        if "item_unchanged" in exp:
            d = {i: store.latest(i).get("version") for i, v in exp["item_unchanged"].items() if store.latest(i).get("version") != v}
            self.check(f"{tag} item_unchanged", not d, d, step)
        if "audit_op" in exp:
            self.check(f"{tag} audit_op", any(a.get("op") == exp["audit_op"] for a in store.audit), exp["audit_op"], step)
        if "versions" in exp:   # latest version number of each item
            d = {i: store.latest(i).get("version") for i, n in exp["versions"].items() if i not in store.items or store.latest(i).get("version") != n}
            self.check(f"{tag} versions", not d, d, step)
        if "old_version_superseded" in exp:
            d = {i: version_of(store, i, v).get("review_status") for i, v in exp["old_version_superseded"].items()
                 if version_of(store, i, v).get("review_status") != "superseded"}
            self.check(f"{tag} old_version_superseded", not d, d, step)
        if "latest_fields" in exp:   # {item: {field: value}}: fields of the latest version (subset match), e.g. cites, restored_from
            d = [x for i, e in exp["latest_fields"].items() for x in subset(e, store.latest(i) if i in store.items else None, i)]
            self.check(f"{tag} latest_fields", not d, d, step)
        if "version_review_status" in exp:   # {item: {"3": "rejected", "4": "approved"}}: the status of each listed version
            d = {f"{i} v{v}": version_of(store, i, int(v)).get("review_status") for i, vs in exp["version_review_status"].items()
                 for v, s in vs.items() if version_of(store, i, int(v)).get("review_status") != s}
            self.check(f"{tag} version_review_status", not d, d, step)
        if "instruction_ids" in exp:
            self.check(f"{tag} instruction_ids", sorted(store.instructions) == exp["instruction_ids"], sorted(store.instructions), step)
        if "task_ids_not_created" in exp:
            self.check(f"{tag} task_ids_not_created", not any(i in store.items for i in exp["task_ids_not_created"]), exp["task_ids_not_created"], step)
        if "change_events_with_kind" in exp:
            d = {k: sum(1 for e in store.change_events if e["kind"] == k) for k in exp["change_events_with_kind"]}
            self.check(f"{tag} change_events_with_kind", d == exp["change_events_with_kind"], d, step)
        if "published_generation_events" in exp:
            n = sum(1 for e in store.change_events if e["kind"] == "generation_delivery" and e["status"] == "published")
            self.check(f"{tag} published_generation_events", n == exp["published_generation_events"], n, step)
        if "refused_generation_events" in exp:
            n = sum(1 for e in store.change_events if e["kind"] == "generation_delivery" and e["status"] == "refused" and e["seq"] is None)
            self.check(f"{tag} refused_generation_events", n == exp["refused_generation_events"], n, step)
        if "suggest_supersedes" in exp:
            s = exp["suggest_supersedes"]
            got = store.suggest_supersedes(s["action"])
            self.check(f"{tag} suggest_supersedes", got == (s["instruction_id"], s["overlap"]), got, step)
        if "confirmation_settings" in exp:   # primary caregiver, time limit, unreachable mark, what awaits the clinician
            self.sub(f"{tag} confirmation_settings", exp["confirmation_settings"], store.confirmation_settings(), step)
        if "confirmation_labels" in exp:   # {id: text the visible label contains, or null for no label}
            d = {i: store.confirmation_label(i) for i, want in exp["confirmation_labels"].items()
                 if (want is None) != (store.confirmation_label(i) is None) or (want is not None and want not in store.confirmation_label(i))}
            self.check(f"{tag} confirmation_labels", not d, d, step)
        if exp.get("no_approved_instruction_time_other_than_previous"):
            pend = [i for i in store.instructions.values() if i.get("derivation_status") == "pending_review" and i.get("previous")]
            ok = bool(pend) and all(PropagatingStore._instruction_time(i, "approved") == i["previous"]["time"] != i["time"] for i in pend)
            self.check(f"{tag} approved basis is the previous time while pending", ok, [(i["instruction_id"], i.get("time"), i.get("previous")) for i in pend], step)

    def grade_changes_view(self, tag: str, store, ch: dict, exp: dict, step=None) -> None:
        for k in ("unread", "banner"):
            if k in exp:
                self.check(f"{tag} {k}", ch.get(k) == exp[k], f"got {ch.get(k)!r}", step)
        if "seen" in exp:
            self.sub(f"{tag} seen", exp["seen"], ch.get("seen"), step)
        if "events_unread" in exp:
            self.check(f"{tag} events_unread", len(ch["events"]) == exp["events_unread"], [e["change_id"] for e in ch["events"]], step)
        if "events" in exp:
            self.sub(f"{tag} events", exp["events"], ch["events"], step)
        if "recorded_only" in exp:
            self.check(f"{tag} recorded_only", len(ch["recorded_only"]) == exp["recorded_only"], [e["change_id"] for e in ch["recorded_only"]], step)
        if "recorded_only_ids" in exp:
            self.check(f"{tag} recorded_only_ids", [e["change_id"] for e in ch["recorded_only"]] == exp["recorded_only_ids"], ch["recorded_only"], step)
        if "cards_carry_live_review_status" in exp:
            live = [a["review_status"] for e in ch["events"] for a in e["affected"]]
            self.check(f"{tag} cards carry live review_status", live and all(s == exp["cards_carry_live_review_status"] for s in live), live, step)
        if "banner_contains" in exp:
            self.check(f"{tag} banner_contains", all(x in ch.get("banner", "") for x in exp["banner_contains"]), f"got {ch.get('banner')!r}", step)
        if "confirmations" in exp:   # every version or instruction in force with an on-behalf label (the handover view)
            self.sub(f"{tag} confirmations", exp["confirmations"], ch.get("confirmations", []), step)


def snapshot_before(store) -> dict:
    return {"hashes": hashes(store), "proposed": proposed(store), "pending": len(store.pending),
            "versions": sum(len(v) for v in store.items.values())}


def expected_with(exp: dict, rewriter) -> dict:
    """The fixture states the deterministic run (every regenerated item `method: fallback`). With a rewriter wired, a
    regenerated item may come back llm_first_try / llm_after_retry, so those method expectations are not graded;
    everything else (content, cites, versions, notice) is graded unchanged."""
    if rewriter is None or "new_versions" not in exp:
        return exp
    return {**exp, "new_versions": [{k: v for k, v in nv.items() if not (k == "method" and v == "fallback")} for nv in exp["new_versions"]]}


def run_fixture(sc: dict, store_factory=PropagatingStore, rewriter=None, samples: list | None = None) -> tuple[Grader, PropagatingStore]:
    """Walk every step of the fixture on a fresh store and grade it. `samples` (optional list) collects the request
    and result of each step for api_samples.json."""
    g, store = Grader(), store_factory(copy.deepcopy(sc))
    store.rewriter = rewriter
    pdf_v2_at_start = copy.deepcopy(store.items.get("pdf-v2"))
    g.check("start case_version", store.case_version == sc["case_version_start"], store.case_version, 0)
    for row in sc.get("schedule_at_start", []):
        g.sub(f"start schedule {row['item_id']}", {k: v for k, v in row.items() if k != "item_id"}, store.latest(row["item_id"]).get("schedule"), 0)
    for step in sc["steps"]:
        n, tag, actor = step["step"], f"step {step['step']}", step["actor"]
        exp = expected_with(sc["expected"].get(f"step_{n}", {}), rewriter)
        before = snapshot_before(store)
        sample = {"step": n, "title": step.get("title"), "actor": actor}
        if "change" in step or "replay_of_step" in step:
            change = change_for(sc, step)
            sample["request"] = {"kind": change["kind"], "actor": actor, "change": change}
            ev = store.apply_change(change, actor)
            sample["result"] = ev
            g.grade_event(tag, store, ev, exp, before, n)
        elif step["action"] == "export_pdf":
            sample["request"] = {"action": "export_pdf", "actor": actor, "pdf_id": step.get("pdf_id"), "at": step.get("at")}
            try:
                rec = store.export_pdf(step.get("pdf_id"), step.get("at"))
                sample["result"] = rec
                g.check(f"{tag} export allowed", "raises" not in exp, "expected a refusal", n)
                if "pdf" in exp:
                    g.sub(f"{tag} pdf record", exp["pdf"], rec, n)
                    ok = all(m in rec["content"] for m in exp.get("content_must_contain", [])) and \
                        not any(m in rec["content"] for m in exp.get("content_must_not_contain", []))
                    g.check(f"{tag} pdf content", ok, rec["content"], n)
                    rows = {r["item_id"]: r for r in rec["schedule"]}
                    d = [x for e in exp.get("schedule_rows", []) for x in subset(e, rows.get(e["item_id"]), e["item_id"])]
                    g.check(f"{tag} pdf schedule rows", not d, d, n)
                    if exp.get("pdf_v2_unchanged"):
                        g.check(f"{tag} pdf-v2 byte-equal", store.items.get("pdf-v2") == pdf_v2_at_start, "", n)
            except ce.PendingReview as e:
                sample["result"] = {"error": "pending_review", "ids": e.ids}
                g.check(f"{tag} export refused while pending", exp.get("raises") == "PendingReview" and e.ids == exp.get("ids"), e.ids, n)
                if "no_pdf" in exp:
                    g.check(f"{tag} no pdf written", exp["no_pdf"] not in store.items, "", n)
        elif step["action"] == "approve_all_pending":
            sample["request"] = {"kind": "review", "actor": actor, "all": True, "request_id": step.get("request_id"), "at": step.get("at")}
            ev = store.approve_all_pending(actor, step.get("at"), step.get("request_id"))
            sample["result"] = ev
            g.grade_event(tag, store, ev, exp, before, n)
        elif step["action"] == "read_changes":
            ch = store.changes_for(actor)
            sample["request"], sample["result"] = {"action": "changes_for", "actor": actor}, ch
            g.grade_changes_view(tag, store, ch, exp, n)
            if step.get("then_mark_seen_at"):
                store.mark_seen(actor, store.seq, store.case_version, step["then_mark_seen_at"])
                sample["then"] = {"action": "mark_seen", "seq": store.seq, "case_version": store.case_version, "result": store.changes_for(actor)}
                g.grade_changes_view(f"{tag} after mark_seen", store, store.changes_for(actor), exp.get("after_mark_seen", {}), n)
        elif step["action"] == "start_generation":
            job = store.start_generation(step["item_id"])
            sample["request"], sample["result"] = {"action": "start_generation", "item_id": step["item_id"]}, job
            if "job" in exp:
                g.sub(f"{tag} job", exp["job"], job, n)
            if "then_change" in step:
                change = copy.deepcopy(step["then_change"])
                ev = store.apply_change(change, actor)
                sample["then"] = {"request": {"kind": change["kind"], "actor": actor, "change": change}, "result": ev}
                g.grade_event(tag, store, ev, {k: v for k, v in exp.items() if k != "job"}, before, n)
        if samples is not None:
            samples.append(sample)
    return g, store


def run_regressions(sc: dict, store_factory=PropagatingStore, rewriter=None, samples: list | None = None) -> Grader:
    """Each regression: a fresh store, the fixture steps up to `after_step`, then its optional `setup` steps (step-shaped,
    not graded: e.g. a second upload or a started job), then its own change (or a variant of a fixture step) graded
    against `expect`; a `raises` expectation also checks that nothing moved. `export_after` ({pdf_id, raises, ids})
    then asks for an export and grades the refusal (or, without `raises`, that it is allowed)."""
    g = Grader()
    for r in sc.get("regressions", []):
        store = store_factory(copy.deepcopy(sc))
        # "rewriter": "none" pins a row to the deterministic path: its situation (e.g. an item a transcript correction
        # leaves stale) only exists when no LLM rewrites the item first.
        rw = None if r.get("rewriter") == "none" else rewriter
        store.rewriter = rw
        for step in sc["steps"]:
            if step["step"] > r["after_step"]:
                break
            replay_step(store, sc, step)
        tag, exp = r["id"], expected_with(r["expect"], rw)
        try:
            for step in r.get("setup", []):
                replay_step(store, sc, step)
        except Exception as e:  # noqa: BLE001 - a refused setup step (e.g. a person's rewrite) is a failed row, not a crash
            g.check(f"{tag} setup", False, f"{type(e).__name__}: {e}")
            continue
        before = snapshot_before(store)
        if r.get("action") == "start_generation":   # a job start (not a change): refused, or the job it returns
            try:
                job = store.start_generation(r["item_id"])
                g.check(f"{tag} start_generation", "raises" not in exp, f"started {job['job_id']} although it should be refused")
                if "job" in exp:
                    g.sub(f"{tag} job", exp["job"], job)
            except Exception as e:  # noqa: BLE001 - the type is the assertion
                g.check(f"{tag} start_generation raises {exp.get('raises')}", type(e).__name__ == exp.get("raises"), f"{type(e).__name__}: {e}")
                g.check(f"{tag} nothing changed after the refused start", hashes(store) == before["hashes"] and not any(
                    j["item_id"] == r["item_id"] for j in store.jobs.values() if j["status"] == "running"), "")
            g.grade_state(tag, store, exp, before)
            continue
        if "change" not in r and "change_from_step" not in r:
            g.grade_state(tag, store, exp, before)
            if "changes_view" in exp:
                g.grade_changes_view(f"{tag} changes_view", store, store.changes_for(exp["changes_view"]["actor"]), exp["changes_view"])
            continue
        change = change_for(sc, r)
        sample = {"regression": r["id"], "defect": r.get("defect"), "request": {"kind": change["kind"], "actor": r["actor"], "change": change}}
        if "raises" in exp:
            try:
                ev = store.apply_change(change, r["actor"])
                g.check(f"{tag} raises {exp['raises']}", False, f"no error; event {ev['change_id']} {ev['status']}")
                sample["result"] = ev
            except Exception as e:  # noqa: BLE001 - the type is the assertion
                g.check(f"{tag} raises {exp['raises']}", type(e).__name__ == exp["raises"], f"{type(e).__name__}: {e}")
                sample["result"] = {"error": type(e).__name__, "message": str(e)}
                if "raises_contains" in exp or "raises_not_contains" in exp:   # why it was refused, not only that it was
                    g.check(f"{tag} refusal names its reasons", all(x in str(e) for x in exp.get("raises_contains", []))
                            and not any(x in str(e) for x in exp.get("raises_not_contains", [])), str(e))
            g.check(f"{tag} nothing changed after the refused request", hashes(store) == before["hashes"] and len(store.pending) == before["pending"], "")
            g.grade_state(tag, store, exp, before)
        else:
            try:
                ev = store.apply_change(change, r["actor"])
            except Exception as e:  # noqa: BLE001 - an unexpected refusal is a failed row, not a crash of the whole table
                g.check(f"{tag} accepted", False, f"{type(e).__name__}: {e}")
                continue
            sample["result"] = ev
            g.grade_event(tag, store, ev, exp, before)
        if "changes_view" in exp:   # what the next caregiver reads afterwards ("since you last read")
            g.grade_changes_view(f"{tag} changes_view", store, store.changes_for(exp["changes_view"]["actor"]), exp["changes_view"])
        if "export_after" in exp:
            xa = exp["export_after"]
            try:
                rec = store.export_pdf(xa.get("pdf_id"), "2026-10-13T18:00")
                g.check(f"{tag} export_after", "raises" not in xa, "exported although it should be refused")
                ok = all(m in rec["content"] for m in xa.get("content_must_contain", [])) and \
                    not any(m in rec["content"] for m in xa.get("content_must_not_contain", []))
                g.check(f"{tag} export_after content", ok, rec["content"])
            except ce.PendingReview as e:   # also ExportBlocked: an approved item that no longer fits the case
                g.check(f"{tag} export_after", xa.get("raises") in ("PendingReview", type(e).__name__) and e.ids == xa.get("ids"),
                        f"{type(e).__name__} {e.ids}: {e}")
        if samples is not None:
            samples.append(sample)
    return g


def replay_step(store, sc: dict, step: dict) -> None:
    """Apply one fixture step (or a regression's setup step) without grading, to reach a regression's starting state."""
    if any(k in step for k in ("change", "replay_of_step", "change_from_step", "change_from_regression")):
        store.apply_change(change_for(sc, step), step["actor"])
    elif step["action"] == "export_pdf":
        try:
            store.export_pdf(step.get("pdf_id"), step.get("at"))
        except ce.PendingReview:
            pass
    elif step["action"] == "approve_all_pending":
        store.approve_all_pending(step["actor"], step.get("at"), step.get("request_id"))
    elif step["action"] == "read_changes":
        if step.get("then_mark_seen_at"):
            store.mark_seen(step["actor"], store.seq, store.case_version, step["then_mark_seen_at"])
    elif step["action"] == "start_generation":
        store.start_generation(step["item_id"])
        if "then_change" in step:
            store.apply_change(copy.deepcopy(step["then_change"]), step["actor"])
    elif step["action"] == "legacy_version":
        # a version an older engine wrote, appended as it was stored (a persisted state from before a fix): unchecked, so
        # the approve and export gates can be shown to judge it against the case as it is now
        old = store.latest(step["item_id"])
        v = {**{k: copy.deepcopy(x) for k, x in old.items() if k not in ("rewrite_for", "restore_problems", "restored_from", "approved_before",
                                                                         "superseded_by", "reject_reason", "rejected_by", "confirmed_on_behalf",
                                                                         "clinician_confirmed")},
             **copy.deepcopy(step["version"]), "version": old.get("version", 1) + 1, "previous_version": old.get("version", 1)}
        if old.get("review_status") == "approved":
            old["approved_before"] = True
        old["review_status"], old["superseded_by"] = "superseded", v["version"]
        store.items[step["item_id"]].append(v)
        store.recompute_schedule(v)


def run_tables(sc: dict) -> Grader:
    """Table tests of the pure functions and the rota boundary, values from the fixture."""
    g, t = Grader(), sc["time_table"]
    for row in t["canonical"]:
        g.check(f"canonical_time {row['phrase']!r}", ce.canonical_time(row["phrase"]) == row["canonical"], ce.canonical_time(row["phrase"]))
        g.check(f"due_at_from_phrase {row['phrase']!r}", ce.due_at_from_phrase(row["phrase"], sc["week_anchor"]) == row["due_at"],
                ce.due_at_from_phrase(row["phrase"], sc["week_anchor"]))
    for phrase in t["unreadable"]:
        g.check(f"unreadable {phrase!r} -> None", ce.canonical_time(phrase) is None and ce.due_at_from_phrase(phrase, sc["week_anchor"]) is None,
                ce.canonical_time(phrase))
    for row in t["substitute"]:
        got = ce.substitute_time(row["content"], row["old"], row["new"])
        g.check(f"substitute_time {row['old']} -> {row['new']} in {row['content'][:30]!r}", got == row["result"], got)
    for row in t["overlap"]:
        ov = ce.action_overlap(row["a"], row["b"])
        ok = (ov == row["overlap"]) if "overlap" in row else (ov >= row.get("min", 0.0) and ov <= row.get("max", 1.0))
        g.check(f"action_overlap {row['a']!r} ~ {row['b']!r}", ok, ov)
    for row in t["correction_label"]:
        g.check(f"correction_label {row['from']!r}", ce.correction_label(row["from"], row["actions"]) == row["label"], ce.correction_label(row["from"], row["actions"]))
    for row in sc["rota_boundary"]:   # a row may bring its own rota (e.g. one written with seconds)
        rota = row.get("rota", sc["rota"])
        g.check(f"assignee_for {row['due_at']}{' (rota with seconds)' if 'rota' in row else ''}", ce.assignee_for(rota, row["due_at"]) == row["assignee"],
                ce.assignee_for(rota, row["due_at"]))
    # an unreadable instruction time in a task's schedule -> needs_time_review, never a guessed due_at
    store = PropagatingStore(copy.deepcopy(sc))
    for phrase in t["unreadable"]:
        store.instructions["ins-B-001"]["time"] = phrase
        sch = store.recompute_schedule(store.latest("task-B-01"))
        g.check(f"schedule status needs_time_review for {phrase!r}", sch["status"] == "needs_time_review" and sch["due_at"] is None, sch)
    # the on-behalf exclusion rule (care_cases.md "Confirmation roles"), values from the fixture's on_behalf_table
    ob = sc.get("on_behalf_table", {})
    for row in ob.get("text", []):   # "grounding": the texts an item's words must come from (its instructions), when the row tests that rule
        got = ce.text_change_exclusions(row["old"], row["new"], grounding=row.get("grounding"))
        g.check(f"on-behalf rule text {row['old'][:28]!r} -> {row['new'][:28]!r}: {'clinician-only' if row['clinician_only'] else 'confirmable'}",
                bool(got) == row["clinician_only"], got)
    for row in ob.get("condition", []):
        got = ce.condition_relaxation(row["old"], row["new"])
        g.check(f"on-behalf rule condition {row['old']!r} -> {row['new']!r}: {'relaxed' if row['relaxed'] else 'not relaxed'}", bool(got) == row["relaxed"], got)
    for row in ob.get("instruction", []):
        got = ce.instruction_change_exclusions(row["prev"], row["cur"])
        g.check(f"on-behalf rule instruction {(row['prev'] or {}).get('action')!r} -> {row['cur'].get('action')!r} "
                f"({row.get('note', '')}): {'clinician-only' if row['clinician_only'] else 'confirmable'}", bool(got) == row["clinician_only"], got)
    # store guards with fixture values (`guards`): changes, export ids and seen-state values that must be refused
    guards = sc.get("guards", {})

    def walked(n: int) -> PropagatingStore:
        st = PropagatingStore(copy.deepcopy(sc))
        for step in sc["steps"]:
            if step["step"] > n:
                break
            replay_step(st, sc, step)
        return st
    for row in guards.get("changes_refused", []):
        store = walked(row["after_step"])
        before = (hashes(store), len(store.pending), store.case_version, store.seq)
        try:
            ev = store.apply_change(change_for(sc, row), row["actor"])
            g.check(f"guard change: {row['name']} ({row['raises']})", False, f"accepted: {ev['change_id']} {ev['status']}")
        except Exception as e:  # noqa: BLE001 - the type is the assertion
            g.check(f"guard change: {row['name']} ({row['raises']})", type(e).__name__ == row["raises"], f"{type(e).__name__}: {e}")
        g.check(f"guard change: {row['name']} left the case unchanged", before == (hashes(store), len(store.pending), store.case_version, store.seq), "")
    store = walked(guards.get("after_step", 0))
    before = hashes(store)
    for row in guards.get("export_pdf_refused", []):
        try:
            store.export_pdf(row["pdf_id"], "2026-10-13T18:00")
            g.check(f"guard export_pdf {row['pdf_id']!r} refused ({row['raises']})", False, "exported")
        except Exception as e:  # noqa: BLE001 - the type is the assertion
            g.check(f"guard export_pdf {row['pdf_id']!r} refused ({row['raises']})", type(e).__name__ == row["raises"], f"{type(e).__name__}: {e}")
    g.check("guard export_pdf refused ids leave every item and instruction unchanged", hashes(store) == before, "")
    for row in guards.get("mark_seen_refused", []):
        try:
            store.mark_seen(row.get("actor", "cg-incoming"), row["seq"], row["case_version"], "2026-10-13T18:00")
            g.check(f"guard mark_seen seq={row['seq']!r} case_version={row['case_version']!r} refused", False, "accepted")
        except ValueError as e:
            g.check(f"guard mark_seen seq={row['seq']!r} case_version={row['case_version']!r} refused", True, str(e))
    if guards.get("mark_seen_refused"):
        g.check("guard mark_seen refused values leave the seen-state unchanged", store.seen == PropagatingStore(copy.deepcopy(sc)).seen, store.seen)
    return g


def run_atomicity(sc: dict) -> Grader:
    """An exception injected into a handler after it has mutated state leaves everything as it was (C-P22)."""
    g = Grader()
    store = PropagatingStore(copy.deepcopy(sc))
    replay_step(store, sc, sc["steps"][0])
    before = (store.snapshot_hashes(), store.case_version, store.seq, copy.deepcopy(store.requests), len(store.change_events), len(store.pending))

    def exploding(change, ev):
        store.add_pending("conflict", "half-written conflict", [])
        store.instructions["ins-B-001"]["time"] = "Friday 9:00 a.m."
        raise RuntimeError("injected failure")
    store._change_family_statement = exploding
    try:
        store.apply_change({"kind": "family_statement", "request_id": "req-atomic", "utterance": "x"}, "cg-outgoing")
        g.check("atomicity: injected failure re-raised", False, "no error")
    except RuntimeError:
        g.check("atomicity: injected failure re-raised", True)
    after = (store.snapshot_hashes(), store.case_version, store.seq, store.requests, len(store.change_events), len(store.pending))
    g.check("atomicity: snapshot_hashes, case_version, seq, requests, events and pending unchanged", before == after,
            {"before": before[1:], "after": after[1:]})
    g.check("atomicity: request_id not recorded", "req-atomic" not in store.requests)
    return g


def run_scoping(sc: dict, sc_other: dict) -> Grader:
    """A second store (another scenario) is untouched by every Case C step; foreign ids raise NotInCase (C-P23)."""
    g = Grader()
    other = PropagatingStore(copy.deepcopy(sc_other))
    other_hashes = other.snapshot_hashes()
    store = PropagatingStore(copy.deepcopy(sc))
    for step in sc["steps"]:
        replay_step(store, sc, step)
        g.check(f"scoping: other store unchanged after step {step['step']}", other.snapshot_hashes() == other_hashes)
    for name, change in (("source", {"kind": "transcript_correction", "request_id": "req-sc1",
                                     "correction": {"source_id": next(iter({s["source_id"] for s in sc_other["sources"]} - {s["source_id"] for s in sc["sources"]}), "src-other"),
                                                    "base_revision": "r1", "segment_id": "s1", "from": "a", "to": "b"}}),
                         ("event", {"kind": "event_confirmation", "request_id": "req-sc2",
                                    "event": {"source_id": "evt-other", "base_revision": "r1", "human_label": "no_fall", "occurred_at": "2026-10-13T14:05"}})):
        try:
            store.apply_change(change, "cg-outgoing")
            g.check(f"scoping: foreign {name} id -> NotInCase", False, "no error")
        except ce.NotInCase:
            g.check(f"scoping: foreign {name} id -> NotInCase", True)
        except Exception as e:  # noqa: BLE001
            g.check(f"scoping: foreign {name} id -> NotInCase", False, f"{type(e).__name__}: {e}")
    return g


def run_all(sc: dict, sc_other: dict, samples: list | None = None) -> list[dict]:
    g, _ = run_fixture(sc, samples=samples)
    results = list(g.results)
    results += run_regressions(sc, samples=samples).results
    results += run_tables(sc).results
    results += run_atomicity(sc).results
    results += run_scoping(sc, sc_other).results
    return results


# ---------------------------------------------------------------- unittest front-end
class ChangeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = json.loads(FIXTURE.read_text())
        cls.sc_normal = json.loads((CASES / "scenario_normal.json").read_text())

    def _assert_all(self, results: list[dict]) -> None:
        fails = [f"{r['id']}: {r['detail']}" for r in results if not r["pass"]]
        self.assertFalse(fails, "\n".join(fails))
        self.assertTrue(results)

    def test_fixture_steps(self):
        g, store = run_fixture(self.sc)
        self._assert_all(g.results)
        self.assertEqual(store.case_version, self.sc["expected"]["step_15"]["case_version_after"])

    def test_regressions_for_the_eight_defects(self):
        self._assert_all(run_regressions(self.sc).results)

    def test_pure_function_tables_and_rota_boundary(self):
        self._assert_all(run_tables(self.sc).results)

    def test_atomicity(self):
        self._assert_all(run_atomicity(self.sc).results)

    def test_scoping(self):
        self._assert_all(run_scoping(self.sc, self.sc_normal).results)

    def test_other_scenarios_load_and_case_store_behaviour_is_kept(self):
        """PropagatingStore on scenario_normal / scenario_correction: same state as CaseStore (plus schedule fields)."""
        for name in ("scenario_normal", "scenario_correction"):
            sc = json.loads((CASES / f"{name}.json").read_text())
            a, b = CaseStore(sc), PropagatingStore(sc)
            self.assertEqual(a.snapshot_hashes(), b.snapshot_hashes(), name)
            self.assertEqual(b.case_version, 1)
            b.approve(["task-A-01"])   # the plain CaseStore.approve path (no actor) stays available
            self.assertEqual(b.seq, 0)

    def test_case_b_correction_through_apply_change(self):
        """Case B sent through the engine's door gives the fixture's notice (B-P7), impact set (B-P1), instruction
        update (B-P11) and unchanged ids (B-P4); the approved-basis due time waits for the review."""
        sc = json.loads((CASES / "scenario_correction.json").read_text())
        e1 = sc["expected"]["step_1"]
        store = PropagatingStore(sc)
        for i in ("task-B-01", "task-B-02"):   # Case B's fixture has no schedule block; give the tasks one
            store.latest(i)["schedule"] = {"anchor": "due_with", "due_with": "task-B-01"} if i == "task-B-02" else {"anchor": "instruction_time"}
            store.recompute_schedule(store.latest(i))
        self.assertEqual(store.latest("task-B-01")["schedule"]["due_at"], "2026-10-15T10:00")
        before = hashes(store)
        ev = store.apply_change({"kind": "transcript_correction", "request_id": "req-b1", "correction": sc["steps"][0]["correction"]}, "cg-outgoing")
        self.assertEqual(ev["notice"], e1["incoming_caregiver_notice"])
        self.assertEqual(ev["impact_set"], sorted(e1["impact_set"]))
        self.assertEqual(store.case_version, e1["case_version_after_step_1"])
        ins, iu = store.instructions["ins-B-001"], e1["instruction_updates"][0]
        self.assertEqual((ins["time"], ins["cites"], ins["derivation_status"]), (iu["time"], iu["cites"], "pending_review"))
        after = hashes(store)
        self.assertEqual([i for i in e1["unchanged"] if i in after and before[i] != after[i]], [])
        sch = store.latest("task-B-01")["schedule"]
        self.assertEqual((sch["due_at"], sch["proposed_due_at"], sch["pending_move"]), ("2026-10-15T10:00", "2026-10-15T11:00", True))
        rev = store.apply_change({"kind": "review", "decision": "approve", "ids": sc["steps"][2]["items"]}, "reviewer", role="care_team")
        self.assertEqual((rev["status"], store.case_version), ("review", 2))
        self.assertEqual(store.latest("task-B-01")["schedule"]["due_at"], "2026-10-15T11:00")
        pdf = store.export_pdf("pdf-v2", "2026-10-13T12:00")
        self.assertTrue(pdf["case_version"] == 2 and "11:00 a.m." in pdf["content"] and "10:00" not in pdf["content"])

    def test_rewriter_hook_is_checked_and_falls_back(self):
        """A rewriter that drops the new time is rejected (fallback used); a correct one is accepted with its method
        and receives the time pair the backend derived; a failing one leaves the case untouched."""
        sc = self.sc

        def after_step_1():
            st = PropagatingStore(copy.deepcopy(sc))
            replay_step(st, sc, sc["steps"][0])
            return st
        store = after_step_1()
        store.rewriter = lambda item, before, after, keep, correction=None: ("Follow-up appointment Thursday 11:00 a.m. (unchanged by a careless rewrite)", "llm_first_try")
        ev = store.apply_change(change_for(sc, sc["steps"][1]), "cg-outgoing")
        self.assertTrue(all(v["method"] == "fallback" for v in ev["new_versions"]), ev["new_versions"])
        self.assertEqual(ev["notice"], sc["expected"]["step_2"]["notice"])
        store2, pairs = after_step_1(), []

        def good(item, before, after, keep, correction=None):
            pairs.append(correction)
            return ce.substitute_time(item["content"], correction["from"], correction["to"]), "llm_first_try"
        store2.rewriter = good
        ev2 = store2.apply_change(change_for(sc, sc["steps"][1]), "cg-outgoing")
        self.assertTrue(all(v["method"] == "llm_first_try" for v in ev2["new_versions"]), ev2["new_versions"])
        self.assertEqual(ev2["notice"], sc["expected"]["step_2"]["notice"])
        ic = sc["expected"]["step_2"]["instruction_changes"][0]
        self.assertEqual(pairs, [{"from": ic["time_from"], "to": ic["time_to"], "kind": "superseded_by_new_source"}] * len(ev2["new_versions"]))
        store3 = after_step_1()

        def broken(item, before, after, keep, correction=None):
            raise ConnectionError("LLM server down")
        store3.rewriter = broken
        h = store3.snapshot_hashes()
        with self.assertRaises(ConnectionError):
            store3.apply_change(change_for(sc, sc["steps"][1]), "cg-outgoing")
        self.assertEqual(store3.snapshot_hashes(), h)
        self.assertIs(store3.rewriter, broken)
        # a rewrite with the right time but an added sentence that relaxes an instruction, or an added time, is rejected
        for extra in (" She can now get up on her own without help.", " No need to wait for help when she gets up.", " Or Friday 9:00 a.m. if that suits."):
            store4 = after_step_1()
            store4.rewriter = lambda item, b, a, keep, correction=None, x=extra: (ce.substitute_time(item["content"], correction["from"], correction["to"]) + x, "llm_first_try")
            ev4 = store4.apply_change(change_for(sc, sc["steps"][1]), "cg-outgoing")
            self.assertTrue(all(v["method"] == "fallback" for v in ev4["new_versions"]), (extra, ev4["new_versions"]))
            self.assertFalse(any(extra.strip() in v["content"] for v in ev4["new_versions"]), extra)
            self.assertEqual(ev4["notice"], sc["expected"]["step_2"]["notice"])
        # the same rules for a transcript correction: the rewrite may introduce the corrected value only
        scb = json.loads((CASES / "scenario_correction.json").read_text())
        store5 = PropagatingStore(scb)
        store5.rewriter = lambda item, b, a, keep, correction=None: (item["content"].replace("10:00", "11:00") + " Take 2 tablets first.", "llm_first_try")
        ev5 = store5.apply_change({"kind": "transcript_correction", "request_id": "req-b1", "correction": scb["steps"][0]["correction"]}, "cg-outgoing")
        self.assertTrue(ev5["new_versions"] and all(v["method"] == "fallback" and "tablets" not in v["content"] for v in ev5["new_versions"]), ev5["new_versions"])


def main() -> int:
    sc = json.loads(FIXTURE.read_text())
    sc_normal = json.loads((CASES / "scenario_normal.json").read_text())
    results = run_all(sc, sc_normal)
    w = max(len(r["id"]) for r in results)
    for r in results:
        print(f"{r['id']:<{w}}  {'PASS' if r['pass'] else 'FAIL'}  {'' if r['pass'] else r['detail']}")
    n_ok = sum(r["pass"] for r in results)
    print(f"\n{n_ok}/{len(results)} checks passed")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    if "--table" in sys.argv:
        sys.exit(main())
    unittest.main()
