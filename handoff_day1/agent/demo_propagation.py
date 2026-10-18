#!/usr/bin/env python3
"""CLI twin of the judge demo: Case C (care_cases/scenario_propagation.json) step by step, against a running mock server
or in-process, printing what the Streamlit page shows.

For every fixture step: the plain-language notice, the schedule before/after (approved | proposed | who | task | status),
the impact set, "unchanged: N (hash-verified)", the replay / refused flags and the banner cg-incoming would see on the
landing page. Every value printed is read from a response field (never computed here), so this is also the reference
for the UI: the same calls in the same order. Expected values come from the fixture; the exit code is 1 if any is not met.

Every key of the fixture's `expected.step_N` blocks is graded, the way ../agent/test_change_engine.py grades the engine,
from what the HTTP replies carry: new_pending from state.pending, superseded_old_versions from state.versions,
citation_repoints from the event, allowed_schedule_follow from the schedule rows before and after, audit_op from
state.audit (the last 20 audit rows). Both transports return copies, so a "before" snapshot never aliases the live store.

Usage:
  python demo_propagation.py                       # against http://127.0.0.1:8765 (../integration_samples/mock_services/mock_server.py)
  python demo_propagation.py --url http://host:port
  python demo_propagation.py --no-server           # in-process: the same server code (mock_server.dispatch), no socket
  python demo_propagation.py --json out.json       # also write every request and response
  python demo_propagation.py --no-server --on-behalf   # the confirmation-roles video path instead (care_cases.md
                                                   # "Confirmation roles"): steps 1-2, then rows R49a, R49b, R49d, the export,
                                                   # cg-incoming's view, R49t, through the same /v1/agent/changes door

FICTIONAL COMPOSITE engineering fixture, not clinical advice. Every time, impact set, assignee and version comes from
backend rules; a language model never decides them (with CARERELAY_AGENT_BACKEND=llm it only proposes item text, checked).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_change_engine import change_for, subset  # noqa: E402  (the fixture walker's helpers: same grading as the engine tests)

MOCK_SERVICES = HERE.parent / "integration_samples" / "mock_services"
INCOMING = "cg-incoming"


# ---------------------------------------------------------------- transports: the same (status, body) either way
class Http:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except json.JSONDecodeError:
                return e.code, {"error": raw.decode(errors="replace")}
        except urllib.error.URLError as e:
            print(f"cannot reach {self.url}: {e.reason}. Start ../integration_samples/mock_services/mock_server.py, or run with --no-server.")
            sys.exit(2)


class InProcess:
    """mock_server.dispatch without a socket: sessions, locks, snapshot/restore and the error map are the server's own."""

    def __init__(self):
        for k, v in (("CARERELAY_VIDEO_BACKEND", "fixture"), ("CARERELAY_SPEECH_BACKEND", "fixture"), ("CARERELAY_AGENT_BACKEND", "fallback")):
            os.environ.setdefault(k, v)
        sys.path.insert(0, str(MOCK_SERVICES))
        import mock_server  # noqa: E402
        self.ms = mock_server

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        code, r = self.ms.dispatch(method, path, body or {})
        return code, json.loads(json.dumps(r))   # what HTTP would carry: a copy, never the server's own objects


# ---------------------------------------------------------------- printing
def fmt(iso: str | None) -> str:
    if not iso:
        return "-"
    d = dt.datetime.fromisoformat(iso)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')} {d.strftime('%H:%M')}"


def schedule_table(rows: list[dict]) -> list[str]:
    """approved | proposed | who | task | status, one line per task; '*' marks a proposed time awaiting review."""
    out = []
    for r in rows:
        approved = fmt(r.get("due_at")) if r.get("due_at") else ("daily" if r.get("anchor") == "recurring" else "-")
        proposed = fmt(r.get("proposed_due_at")) if r.get("proposed_due_at") else "-"
        if r.get("pending_move"):
            proposed += " *"
        who = r.get("assignee") or "-"
        if r.get("pending_move") and r.get("proposed_assignee") != r.get("assignee"):
            who += f" -> {r.get('proposed_assignee')}"
        task = f"{r['item_id']} v{r.get('version')}  {(r.get('content') or '')[:46]}" + (" [process task]" if r.get("origin") == "product_rule" else "")
        status = (r.get("status") or "-") + ("" if r.get("review_status") == "approved" else f", {r.get('review_status')}")
        out.append((approved, proposed, who, task, status))
    head = ("approved", "proposed", "who", "task", "status")
    widths = [max(len(x[i]) for x in [head] + out) for i in range(5)]
    line = lambda x: "  ".join(x[i].ljust(widths[i]) for i in range(5)).rstrip()  # noqa: E731
    return [line(head), line(tuple("-" * w for w in widths))] + [line(x) for x in out]


def say(*parts: str, indent: int = 3) -> None:
    print(" " * indent + " ".join(parts))


class Checks:
    """Expected values from the fixture, graded as they are printed."""

    def __init__(self):
        self.n, self.failed = 0, []

    def eq(self, label: str, got, exp) -> None:
        self.n += 1
        if got != exp:
            self.failed.append(f"{label}: got {got!r}, expected {exp!r}")

    def sub(self, label: str, exp, got) -> None:
        self.n += 1
        d = subset(exp, got)
        if d:
            self.failed.append(f"{label}: " + "; ".join(d))


# ---------------------------------------------------------------- the walk
class Demo:
    def __init__(self, t, sc: dict, checks: Checks, log: list | None):
        self.t, self.sc, self.checks, self.log = t, sc, checks, log
        self.sid = None
        self.last_rows: list[dict] = []

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        code, r = self.t.call(method, path, body)
        if self.log is not None:
            self.log.append({"request": {"method": method, "path": path, "body": body}, "status": code, "response": r})
        return code, r

    def state(self) -> dict:
        return self.call("GET", f"/v1/agent/sessions/{self.sid}")[1]["state"]

    def banner(self) -> dict:
        return self.call("GET", f"/v1/agent/sessions/{self.sid}/changes?actor={INCOMING}")[1]["result"]

    def open_session(self) -> dict:
        code, r = self.call("POST", "/v1/agent/sessions", {"scenario": self.sc["scenario_id"]})
        if code != 200:
            sys.exit(f"cannot open a session: HTTP {code} {r}")
        st = r["state"]
        self.sid = st["session_id"]
        print(f"Session {self.sid} on {self.sc['scenario_id']} ({r.get('agent_backend')} agent, model {r.get('llm_model')}); "
              f"case version {st['case_version']}, seq {st['seq']}")
        print(f"   {self.sc['fixture_notice']}")
        self.checks.eq("start case_version", st["case_version"], self.sc["case_version_start"])
        rows = {x["item_id"]: x for x in st["schedule"]}
        for row in self.sc.get("schedule_at_start", []):
            self.checks.sub(f"start schedule {row['item_id']}", {k: v for k, v in row.items() if k != "item_id"}, rows.get(row["item_id"]))
        print("   schedule at start:")
        for line in schedule_table(st["schedule"]):
            say(line, indent=5)
        self.last_rows = st["schedule"]
        b = self.banner()
        print(f"   {INCOMING} sees: \"{b['banner']}\"")
        return st

    def show_schedule(self, st: dict, n: int) -> None:
        if st["schedule"] == self.last_rows:
            say(f"schedule: unchanged ({len(st['schedule'])} rows)")
        else:
            say(f"schedule after step {n} (* = proposed, awaiting review):")
            for line in schedule_table(st["schedule"]):
                say(line, indent=5)
        self.last_rows = st["schedule"]

    def show_event(self, ev: dict, st: dict, before: dict, exp: dict, tag: str) -> None:
        c = self.checks
        flags = []
        if ev.get("replayed"):
            flags.append(f"REPLAYED (matched_by {ev.get('matched_by')}): nothing changed")
        if ev.get("status") == "refused":
            flags.append(f"REFUSED ({ev.get('refused')}): not published, kept in the audit")
        say(f"{ev['change_id']} {ev['status']}; case version {ev['case_version_before']} -> {ev['case_version_after']}, seq {ev.get('seq')}, "
            f"awaiting review {ev.get('awaiting_review')}" + (f"; {'; '.join(flags)}" if flags else ""))
        say(f"notice: \"{ev.get('notice')}\"")
        if ev.get("impact_set") or ev.get("new_versions") or ev.get("new_items"):
            nv = ", ".join(f"{x['item_id']} v{x['version']} ({x.get('method')})" for x in ev.get("new_versions", []))
            ni = ", ".join(f"{x['item_id']} v{x['version']}" + (" [process task]" if x.get("origin") == "product_rule" else "") for x in ev.get("new_items", []))
            say(f"impact: {', '.join(ev.get('impact_set')) or 'none'}" + (f" -> new versions {nv}" if nv else "") + (f"; new items {ni}" if ni else ""))
        for ic in ev.get("instruction_changes", []):
            when = f" {ic.get('time_from')} -> {ic.get('time_to')}" if "time_to" in ic else (f" time {ic.get('time')}" if ic.get("time") else "")
            say(f"instruction {ic['instruction_id']}: {ic['change']}{when}" + (f" (overlap {ic['supersedes_overlap']})" if ic.get("supersedes_overlap") is not None else ""))
        for d in ev.get("schedule_diff", []):
            moved = f"{fmt(d['due_at_from'])} -> {fmt(d['due_at_to'])}"
            if d.get("assignee_from") != d.get("assignee_to"):
                moved += f", {d['assignee_from']} -> {d['assignee_to']}"
            if "status_to" in d:
                moved += f", {d.get('status_from')} -> {d['status_to']}"
            say(f"schedule move [{d['basis']}] {d['item_id']}: {moved} ({d.get('reason')})")
        for na in ev.get("not_applied", []):
            say(f"not applied to {na['instruction_id']}: {na['reason']} (recorded {na['recorded_at']}, current source {na['current_source']['source_id']} "
                f"recorded {na['current_source']['recorded_at']})")
        for p in ev.get("pending_changes", []):
            say(f"question {p['pending_id']} ({p['type']}): {p['status']}" + (f" about {p['about_instruction']}" if p.get("about_instruction") else ""))
        if ev.get("needs_person"):
            say("a person rewrites: " + ", ".join(x["item_id"] for x in ev["needs_person"]))
        if ev.get("reviewed"):
            say(f"reviewed: {ev['reviewed']['decision']} {', '.join(ev['reviewed']['approved'] or ev['reviewed']['rejected'])}")
        if ev.get("status") == "refused":
            say(f"discarded: \"{ev.get('discarded_content')}\"")
        untouched = ev.get("untouched_hashes") or {}
        bad = [i for i, h in untouched.items() if st["unchanged_hashes"].get(i) != h]
        say(f"unchanged: {len(untouched)} ({'hash-verified' if not bad else 'HASH MISMATCH: ' + ', '.join(bad)})")
        c.eq(f"{tag} untouched_hashes match the live state", bad, [])
        # expected values (fixture)
        for k in ("change_id", "status", "replayed", "matched_by", "refused", "seq", "impact_set", "notice", "awaiting_review", "discarded_content",
                  "citation_repoints", "needs_person"):
            if k in exp:
                c.eq(f"{tag} {k}", ev.get(k), exp[k])
        for k in ("new_items", "new_versions", "schedule_diff", "instruction_changes", "source_added", "not_applied", "pending_changes", "reviewed"):
            if k in exp:
                c.sub(f"{tag} {k}", exp[k], ev.get(k))
        if "untouched_count" in exp:
            c.eq(f"{tag} untouched_count", len(untouched), exp["untouched_count"])
        if "needs_person_ids" in exp:
            c.eq(f"{tag} needs_person", sorted(x["item_id"] for x in ev.get("needs_person", [])), exp["needs_person_ids"])
        self.grade_state(st, before, exp, tag)

    def grade_state(self, st: dict, before: dict, exp: dict, tag: str) -> None:
        c = self.checks
        if "case_version_after" in exp:
            c.eq(f"{tag} case_version", st["case_version"], exp["case_version_after"])
        if "seq_after" in exp:
            c.eq(f"{tag} seq", st["seq"], exp["seq_after"])
        rows = {x["item_id"]: x for x in st["schedule"]}
        for key in ("schedule_approved_before_review", "schedule_after_review", "schedule_after", "schedule"):
            if key in exp:
                c.eq(f"{tag} {key}", [d for i, e in exp[key].items() for d in subset(e, rows.get(i), i)], [])
        if "instruction_after" in exp:
            c.eq(f"{tag} instruction_after", [d for i, e in exp["instruction_after"].items() for d in subset(e, st["instructions"].get(i), i)], [])
        if "unchanged" in exp:
            moved = [i for i in exp["unchanged"] if before["unchanged_hashes"].get(i) != st["unchanged_hashes"].get(i)]
            c.eq(f"{tag} unchanged ids keep their hash", moved, [])
            # the proposed basis of an unchanged task moves only for the followers the fixture allows (due_with)
            was = {x["item_id"]: (x.get("proposed_due_at"), x.get("proposed_assignee")) for x in before["schedule"]}
            now = {x["item_id"]: (x.get("proposed_due_at"), x.get("proposed_assignee")) for x in st["schedule"]}
            drift = [i for i, p in was.items() if i in now and now[i] != p and i in exp["unchanged"] and i not in exp.get("allowed_schedule_follow", [])]
            c.eq(f"{tag} proposed schedule moves only for allowed_schedule_follow", drift, [])
        if "new_pending" in exp:
            c.sub(f"{tag} new_pending", exp["new_pending"], st["pending"][len(before["pending"]):])
        if "superseded_old_versions" in exp:
            got = {i: next(({k: x.get(k) for k in ("review_status", "superseded_by")} for x in st["versions"].get(i, []) if x.get("version") == v), None)
                   for i, v in exp["superseded_old_versions"].items()}
            c.eq(f"{tag} superseded_old_versions", got, {i: {"review_status": "superseded", "superseded_by": v + 1} for i, v in exp["superseded_old_versions"].items()})
        if "audit_op" in exp:
            c.eq(f"{tag} audit_op {exp['audit_op']}", any(a.get("op") == exp["audit_op"] for a in st["audit"]), True)
        for key in ("new_versions_review_status", "new_items_review_status"):
            if key in exp:
                ids = [x["item_id"] for x in exp.get(key.split("_review")[0], [])]
                c.eq(f"{tag} {key}", {i: st["items"][i]["review_status"] for i in ids}, {i: exp[key] for i in ids})
        if "must_contain" in exp:
            bad = {i: st["items"][i]["content"] for i, must in exp["must_contain"].items()
                   if not all(m.lower() in st["items"][i]["content"].lower() for m in must)
                   or any(b.lower() in st["items"][i]["content"].lower() for b in exp.get("must_not_contain", []))}
            c.eq(f"{tag} regenerated content", bad, {})
        if "task_status" in exp:
            c.eq(f"{tag} task_status", {i: (st["items"][i].get("schedule") or {}).get("status") for i in exp["task_status"]}, exp["task_status"])
        if "pending_count_after" in exp:
            c.eq(f"{tag} pending_count_after", len(st["pending"]), exp["pending_count_after"])
        if "no_new_pending" in exp:
            c.eq(f"{tag} no_new_pending", len(st["pending"]), len(before["pending"]))
        if "no_new_versions" in exp:
            c.eq(f"{tag} no_new_versions", {i: v["version"] for i, v in st["items"].items()}, {i: v["version"] for i, v in before["items"].items()})
        if "source_not_stored" in exp:
            c.eq(f"{tag} source_not_stored", exp["source_not_stored"] in [s["source_id"] for s in st["sources"]], False)
        if "superseded_on_arrival_by" in exp:
            got = {s["source_id"]: s.get("superseded_on_arrival_by") for s in st["sources"] if s["source_id"] in exp["superseded_on_arrival_by"]}
            c.eq(f"{tag} superseded_on_arrival_by", got, exp["superseded_on_arrival_by"])
        for key in ("pending_closed",):
            if key in exp:
                by_id = {p["pending_id"]: p for p in st["pending"]}
                c.eq(f"{tag} {key}", [d for e in exp[key] for d in subset(e, by_id.get(e["pending_id"]), e["pending_id"])], [])
        if "job_after" in exp:
            c.sub(f"{tag} job_after", exp["job_after"], st["jobs"].get(exp["job_after"]["job_id"]))
        if "item_unchanged" in exp:
            c.eq(f"{tag} item_unchanged", {i: st["items"][i]["version"] for i in exp["item_unchanged"]}, exp["item_unchanged"])
        if "no_pdf" in exp:
            c.eq(f"{tag} no pdf written", exp["no_pdf"] in st["items"], False)

    def show_changes(self, view: dict, exp: dict, tag: str) -> None:
        c = self.checks
        say(f"{view['actor']} last read seq {view['seen'].get('seq')} (version {view['seen'].get('case_version')}); now seq {view['seq']}, version {view['case_version']}")
        say(f"banner: \"{view['banner']}\"" + ("  [unread]" if view["unread"] else ""))
        for e in view["events"]:
            live = ", ".join(f"{a['id']} {a['review_status']}" for a in e.get("affected", []))
            say(f"card {e['change_id']} ({e['kind']}, seq {e['seq']}): {e['notice'][:96]}{'...' if len(e['notice']) > 96 else ''}")
            say(f"      unchanged {e.get('unchanged_count')} | affected (live review status): {live or 'none'}", indent=3)
        for e in view["recorded_only"]:
            say(f"note {e['change_id']} ({e['kind']}): {e['notice'][:96]}{'...' if len(e['notice']) > 96 else ''}")
        for k in ("unread", "banner"):
            if k in exp:
                c.eq(f"{tag} {k}", view.get(k), exp[k])
        if "seen" in exp:
            c.sub(f"{tag} seen", exp["seen"], view.get("seen"))
        if "events_unread" in exp:
            c.eq(f"{tag} events_unread", len(view["events"]), exp["events_unread"])
        if "events" in exp:
            c.sub(f"{tag} events", exp["events"], view["events"])
        if "recorded_only" in exp:
            c.eq(f"{tag} recorded_only", len(view["recorded_only"]), exp["recorded_only"])
        if "recorded_only_ids" in exp:
            c.eq(f"{tag} recorded_only_ids", [e["change_id"] for e in view["recorded_only"]], exp["recorded_only_ids"])
        if "cards_carry_live_review_status" in exp:
            live = [a["review_status"] for e in view["events"] for a in e["affected"]]
            c.eq(f"{tag} cards carry live review status", bool(live) and all(s == exp["cards_carry_live_review_status"] for s in live), True)

    def run_step(self, step: dict) -> None:
        n, actor, tag = step["step"], step["actor"], f"step {step['step']}"
        exp = self.sc["expected"].get(f"step_{n}", {})
        print(f"\n== Step {n} ({actor}): {step['title']}")
        before = self.state()
        if "change" in step or "replay_of_step" in step:
            change = change_for(self.sc, step)
            say(f"POST /v1/agent/changes  kind {change['kind']}, request_id {change.get('request_id')}")
            code, r = self.call("POST", "/v1/agent/changes", {"session_id": self.sid, "actor": actor, "change": change})
            self.apply_result(code, r, before, exp, tag, n)
        elif step["action"] == "export_pdf":
            say(f"POST /v1/agent/export-pdf  pdf_id {step.get('pdf_id')}")
            code, r = self.call("POST", "/v1/agent/export-pdf", {"session_id": self.sid, "actor": actor, "pdf_id": step.get("pdf_id"), "at": step.get("at")})
            if code == 409 and r.get("error") == "pending_review":
                say(f"HTTP 409 pending_review: approve {len(r['ids'])} item(s) to export: {', '.join(r['ids'])}  (UI: the Export button is grey)")
                self.checks.eq(f"{tag} export refused while pending", (exp.get("raises"), r["ids"]), ("PendingReview", exp.get("ids")))
            elif code == 200:
                rec = r["result"]
                say(f"HTTP 200: {rec['item_id']} exported at case version {rec['case_version']}, seq {rec['seq']}, generated {rec.get('generated_at')}; "
                    f"{len(rec['schedule'])} schedule rows, content hash {rec.get('content_hash')}")
                for row in rec["schedule"]:
                    say(f"{row['item_id']} v{row['version']}  {fmt(row['due_at'])}  {row['assignee']}  {row['status']}", indent=5)
                self.checks.eq(f"{tag} export allowed", "raises" in exp, False)
                if "pdf" in exp:
                    self.checks.sub(f"{tag} pdf record", exp["pdf"], rec)
                    self.checks.eq(f"{tag} pdf matches the case version", rec["case_version"], r["state"]["case_version"])
                    ok = all(m in rec["content"] for m in exp.get("content_must_contain", [])) and not any(m in rec["content"] for m in exp.get("content_must_not_contain", []))
                    self.checks.eq(f"{tag} pdf content", ok, True)
                    rows = {x["item_id"]: x for x in rec["schedule"]}
                    self.checks.eq(f"{tag} pdf schedule rows", [d for e in exp.get("schedule_rows", []) for d in subset(e, rows.get(e["item_id"]), e["item_id"])], [])
                    if exp.get("pdf_v2_unchanged"):
                        self.checks.eq(f"{tag} pdf-v2 unchanged", r["state"]["items"].get("pdf-v2"), before["items"].get("pdf-v2"))
            else:
                say(f"HTTP {code}: {r}")
                self.checks.eq(f"{tag} export", code, 200)
            if code == 200:
                self.grade_state(r["state"], before, exp, tag)
        elif step["action"] == "approve_all_pending":
            say("POST /v1/agent/approve  all: true")
            code, r = self.call("POST", "/v1/agent/approve", {"session_id": self.sid, "actor": actor, "all": True,
                                                              "request_id": step.get("request_id"), "at": step.get("at")})
            self.apply_result(code, r, before, exp, tag, n)
        elif step["action"] == "read_changes":
            say(f"GET /v1/agent/sessions/<id>/changes?actor={actor}")
            code, r = self.call("GET", f"/v1/agent/sessions/{self.sid}/changes?actor={actor}")
            self.checks.eq(f"{tag} changes HTTP", code, 200)
            if code == 200:
                self.show_changes(r["result"], exp, tag)
                if step.get("then_mark_seen_at"):
                    code, r2 = self.call("POST", "/v1/agent/seen", {"session_id": self.sid, "actor": actor, "seq": r["seq"],
                                                                    "case_version": r["case_version"], "at": step["then_mark_seen_at"]})
                    say(f"POST /v1/agent/seen (Mark as read) -> \"{r2['result']['banner']}\"")
                    for k in ("unread", "banner"):
                        if k in exp.get("after_mark_seen", {}):
                            self.checks.eq(f"{tag} after mark_seen {k}", r2["result"].get(k), exp["after_mark_seen"][k])
        elif step["action"] == "start_generation":
            say(f"POST /v1/agent/generation-jobs  item_id {step['item_id']}")
            code, r = self.call("POST", "/v1/agent/generation-jobs", {"session_id": self.sid, "item_id": step["item_id"]})
            self.checks.eq(f"{tag} job HTTP", code, 200)
            if code == 200:
                job = r["result"]
                say(f"{job['job_id']} started on {job['item_id']} at case version {job['base_case_version']} (item v{job.get('base_version')}), status {job['status']}")
                if "job" in exp:
                    self.checks.sub(f"{tag} job", exp["job"], job)
                if "then_change" in step:
                    c = step["then_change"]
                    say(f"POST /v1/agent/generation-jobs/deliver  job_id {c['job_id']}, request_id {c['request_id']}")
                    code, r = self.call("POST", "/v1/agent/generation-jobs/deliver", {"session_id": self.sid, "actor": actor, "job_id": c["job_id"],
                                                                                      "content": c["content"], "request_id": c["request_id"], "at": c.get("at")})
                    self.apply_result(code, r, before, {k: v for k, v in exp.items() if k != "job"}, tag, n)
        b = self.banner()
        say(f"{INCOMING} sees: \"{b['banner']}\"")

    def apply_result(self, code: int, r: dict, before: dict, exp: dict, tag: str, n: int) -> None:
        if code == 200 or (code == 409 and isinstance(r.get("result"), dict) and r["result"].get("status") == "refused"):
            say(f"HTTP {code}" + (f" ({r.get('error')})" if code != 200 else ""))
            self.show_event(r["result"], r["state"], before, exp, tag)
            self.show_schedule(r["state"], n)
        else:
            say(f"HTTP {code} {r.get('type') or ''}: {r.get('error')}")
            self.checks.eq(f"{tag} HTTP", code, 200)


VIDEO_PATH = ("R49a", "R49b", "R49d", "export pdf-r49d", f"read {INCOMING}", "R49t", "export pdf-r49t")


def on_behalf_path(demo: "Demo") -> None:
    """The confirmation-roles video path (care_cases.md "Confirmation roles"): fixture steps 1-2, then the graded rows in
    VIDEO_PATH through the same door the UI uses (/v1/agent/changes, /v1/agent/export-pdf, the changes view). Every value
    printed is read from a response; the rows' expectations (HTTP code, refusal reason, notice, banner, export labels) are
    graded as they are printed."""
    sc, c = demo.sc, demo.checks
    rows = {r["id"].split("-")[0]: r for r in sc["regressions"]}
    for step in sc["steps"][:2]:
        demo.run_step(step)
    for beat in VIDEO_PATH:
        if beat.startswith("export "):
            pdf_id = beat.split()[1]
            exp = rows["R49d" if pdf_id == "pdf-r49d" else "R49t"]["expect"]["export_after"]
            print(f"\n== Export {pdf_id}")
            at = "2026-10-13T16:45" if pdf_id == "pdf-r49d" else "2026-10-14T09:05"
            code, r = demo.call("POST", "/v1/agent/export-pdf", {"session_id": demo.sid, "actor": "cg-outgoing", "pdf_id": pdf_id, "at": at})
            c.eq(f"{beat} HTTP", code, 200)
            if code == 200:
                for line in r["result"]["content"].splitlines():
                    say(line)
                c.eq(f"{beat} labels", [m for m in exp.get("content_must_contain", []) if m not in r["result"]["content"]], [])
            continue
        if beat.startswith("read "):
            actor = beat.split()[1]
            print(f"\n== {actor} reads \"since you last read\"")
            code, r = demo.call("GET", f"/v1/agent/sessions/{demo.sid}/changes?actor={actor}")
            c.eq(f"{beat} HTTP", code, 200)
            view = r["result"]
            say(f"banner: \"{view['banner']}\"")
            for e in view["events"]:
                say(f"card {e['change_id']} ({e['kind']}): {e['notice'][:110]}{'...' if len(e['notice']) > 110 else ''}")
                for a in e["affected"]:
                    if a.get("confirmation"):
                        say(f"{a['id']}: {a['confirmation']}", indent=7)
            exp = rows["R49e"]["expect"]["changes_view"]
            c.eq(f"{beat} banner", view["banner"], exp["banner"])
            c.sub(f"{beat} confirmations", exp["confirmations"], view.get("confirmations", []))
            continue
        r_ = rows[beat]
        exp, change = r_["expect"], r_["change"]
        print(f"\n== {r_['id']} ({r_['actor']})")
        say(f"POST /v1/agent/changes  kind {change['kind']}" + (f", decision {change['decision']}" if change.get("decision") else "") + f", at {change.get('at')}")
        code, r = demo.call("POST", "/v1/agent/changes", {"session_id": demo.sid, "actor": r_["actor"], "change": change})
        if "raises" in exp:
            say(f"HTTP {code} {r.get('type')}: {r.get('error', '')[:300]}{'...' if len(r.get('error', '')) > 300 else ''}")
            c.eq(f"{beat} refused", (code, r.get("type")), ({"PermissionError": 403, "NotFit": 409, "ValueError": 400}[exp["raises"]], exp["raises"]))
            c.eq(f"{beat} refusal names its reasons", [m for m in exp.get("raises_contains", []) if m not in r.get("error", "")], [])
            continue
        c.eq(f"{beat} HTTP", code, 200)
        if code != 200:
            say(f"HTTP {code}: {r}")
            continue
        ev = r["result"]
        say(f"{ev['change_id']} {ev['status']}; case version {ev['case_version_after']}, seq {ev['seq']}")
        say(f"notice: \"{ev['notice']}\"")
        if "notice" in exp:
            c.eq(f"{beat} notice", ev["notice"], exp["notice"])
        if "reviewed" in exp:
            c.sub(f"{beat} reviewed", exp["reviewed"], ev.get("reviewed"))
        if ev.get("schedule_diff"):
            say("schedule now (approved | proposed | who):")
            for line in schedule_table(r["state"]["schedule"]):
                say(line, indent=5)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("CARERELAY_API", "http://127.0.0.1:8765"))
    ap.add_argument("--no-server", action="store_true", help="run the server code in-process instead of over HTTP")
    ap.add_argument("--json", help="write every request and response to this file")
    ap.add_argument("--on-behalf", action="store_true", help="walk the confirmation-roles video path instead of the 16 steps")
    args = ap.parse_args()
    t = InProcess() if args.no_server else Http(args.url)
    code, sc = t.call("GET", "/v1/care-cases/scenario_propagation")
    if code != 200:
        print(f"cannot read the fixture from the server (HTTP {code}): is mock_server.py running at {args.url}? (or use --no-server)")
        return 2
    print(f"CareRelay update propagation, Case C: {sc['title']}  [{'in-process' if args.no_server else args.url}]")
    print(f"   starts from: {sc['starts_from']}")
    checks, log = Checks(), ([] if args.json else None)
    demo = Demo(t, sc, checks, log)
    demo.open_session()
    if args.on_behalf:
        on_behalf_path(demo)
    else:
        for step in sc["steps"]:
            demo.run_step(step)
    print(f"\nExpectations from the fixture: {checks.n - len(checks.failed)}/{checks.n} met")
    for f in checks.failed:
        print("   NOT MET:", f)
    if args.json:
        Path(args.json).write_text(json.dumps({"fixture": sc["scenario_id"], "transport": "in-process" if args.no_server else args.url,
                                               "checks": {"met": checks.n - len(checks.failed), "total": checks.n, "failed": checks.failed},
                                               "calls": log}, indent=2, ensure_ascii=False))
        print(f"   wrote {args.json}")
    return 1 if checks.failed else 0


if __name__ == "__main__":
    sys.exit(main())
