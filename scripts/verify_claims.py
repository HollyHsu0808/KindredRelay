#!/usr/bin/env python3
"""Recompute the published numbers from the raw records and check every cited source. No network, model, key or
third-party package: the standard library only, so anyone with Python 3.13 and a copy of the repository can run it.

python scripts/verify_claims.py [--out REPORT.json] [--strict]

Three kinds of check, each one row of the report:
  hash       a sha256 that a result file records for one of its inputs or sources, against the file as it is now.
             Frozen artifacts (files under release/, preregistered variant files) must match; repository sources
             and case files that changed after the run are reported as `changed_since_run` (a warning, a failure
             with --strict), since the result describes the code as it was when it ran. A file that
             release/REDACTIONS.json lists (scripts/redact_local_paths.py replaced its local paths) is a documented
             change: its recorded original -> redacted sha256 pair passes, its bytes must be the redacted ones and its
             non-string values must recompute to the recorded values_sha256.
  recompute  a headline metric of a results.json recomputed here from that run's per-record data (records.jsonl,
             or the per-case rows the result keeps) with this file's own small aggregation (stdlib percentiles,
             own Wilson interval, own grouping), never the producing script's summary code, and compared with the
             recorded value. Bootstrap intervals are not recomputed (they depend on the producer's resampling).
  claim      one numeric row of submission/SOURCES.md against the file it cites: an explicit `key` = value must
             equal the JSON value at that key (to the precision written), a cited path:line must exist and hold the
             quoted text and the row's numbers. A number that none of the row's cited sources holds is reported as
             `unconfirmed` (a warning, a failure with --strict); rows with a [[PENDING ...]] source are `pending`.

Result directories that do not exist yet (load_*, metamorphic_*, a run still writing records.jsonl) are skipped
with a notice, never failed. Exit 0 when no check is `mismatch` (and, with --strict, none is a warning either);
1 otherwise; 2 on a usage error. The report (JSON) goes to --out, a summary to stdout.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kindredrelay-verify-claims-v1"
FAILING = {"mismatch"}
WARNING = {"changed_since_run", "unconfirmed"}
STOPPED = ("block", "hold")


# ---------------------------------------------------------------------------------------------------------- report
class Report:
    def __init__(self):
        self.checks: list[dict] = []

    def add(self, kind: str, target: str, what: str, status: str, expected=None, recomputed=None, detail=None):
        self.checks.append({"kind": kind, "target": target, "what": what, "status": status,
                            "expected": expected, "recomputed": recomputed, "detail": detail})

    def compare(self, target: str, what: str, recorded, mine, tol=None):
        """One recompute row: recorded (results.json) vs mine (this file's aggregation)."""
        ok = same(recorded, mine, tol)
        self.add("recompute", target, what, "pass" if ok else "mismatch", recorded, mine)
        return ok


def same(a, b, tol=None) -> bool:
    """Equality for recomputed values: ints and strings exact, floats within tol (default: half a unit in the 4th
    decimal or 1e-4 relative, whichever is larger: results round to 4 decimals, token means to 1), lists and dicts
    element by element."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        t = tol if tol is not None else max(5e-4, 1e-4 * abs(a))
        return abs(a - b) <= t + 1e-12
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(map(str, a)) == set(map(str, b)) and all(same(a[k], b[next(j for j in b if str(j) == str(k))], tol)
                                                          for k in a)
    return a == b


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> tuple[list[dict], int]:
    rows, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    return rows, bad


# ---------------------------------------------------------------------------------------------------------- statistics
def pct(xs, q: int):
    """The q-th percentile with linear interpolation between closest ranks (statistics.quantiles 'inclusive')."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    return statistics.quantiles(xs, n=100, method="inclusive")[q - 1]


def avg(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def wilson(k: int, n: int):
    """Wilson score 95% interval, z = 1.959964 (unrounded)."""
    if n <= 0:
        return None
    z = 1.959964
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def r4(x):
    return None if x is None else round(x, 4)


def kn(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": r4(k / n) if n else None, "wilson95": [r4(v) for v in wilson(k, n)] if n else None}


# ---------------------------------------------------------------------------------------------------------- hashes
SHA_KEY = re.compile(r"^(.*?)_?sha256$")


def find_file(text: str, root: Path, base: Path | None = None) -> Path | None:
    """A recorded path as a file of this checkout: as given (relative to root or base), else the shortest suffix of an
    absolute path from another machine that exists under root."""
    text = text.replace("\\", "/")
    for cand in ([base / text] if base else []) + [root / text]:
        if cand.is_file():
            return cand
    parts = [p for p in text.split("/") if p and not p.endswith(":")]
    for i in range(1, len(parts)):
        cand = root.joinpath(*parts[i:])
        if cand.is_file():
            return cand
    return None


REDACTIONS = "release/REDACTIONS.json"


def redaction_log(root: Path) -> dict:
    """{path: entry} of release/REDACTIONS.json (written by scripts/redact_local_paths.py); {} when absent."""
    try:
        log = load_json(root / REDACTIONS)
    except (OSError, ValueError):
        return {}
    return {e["path"]: e for e in (log.get("files") or []) if isinstance(e, dict) and isinstance(e.get("path"), str)}


def documented_redaction(root: Path, relpath: str, recorded: str, now: str) -> bool:
    """True when relpath's recorded digest is its sha256 before path redaction and now is the one after."""
    e = redaction_log(root).get(relpath) or {}
    return bool(e) and e.get("original_sha256") == recorded and e.get("redacted_sha256") == now


def shape(o):
    """The document without its strings (containers, order, every non-string value as JSON text): the values_sha256
    input, rebuilt here rather than imported from the redaction script."""
    if isinstance(o, dict):
        return ["{", [shape(v) for v in o.values()]]
    if isinstance(o, list):
        return ["[", [shape(v) for v in o]]
    return "s" if isinstance(o, str) else ["v", json.dumps(o)]


def redactions(rep: Report, root: Path):
    """Each file release/REDACTIONS.json lists: its bytes are the recorded redacted ones and its non-string values
    recompute to the values_sha256 recorded before redaction."""
    for rp, e in sorted(redaction_log(root).items()):
        f = root / rp
        if not f.is_file():
            rep.add("hash", REDACTIONS, f"redacted_sha256: {rp}", "skip", e.get("redacted_sha256"), None,
                    "file not in this checkout")
            continue
        now = sha256(f)
        rep.add("hash", REDACTIONS, f"redacted_sha256: {rp}", "pass" if now == e.get("redacted_sha256") else "mismatch",
                e.get("redacted_sha256"), now, f"sha256 before path redaction {e.get('original_sha256')}")
        if e.get("values_sha256") is None:
            continue
        try:
            text = f.read_text(encoding="utf-8")
            docs = ([json.loads(x) for x in text.splitlines() if x.strip()] if e.get("format") == "jsonl"
                    else [json.loads(text)])
            mine = hashlib.sha256(json.dumps(shape(docs), separators=(",", ":")).encode("utf-8")).hexdigest()
        except ValueError as exc:
            mine = f"{type(exc).__name__}: {exc}"
        rep.add("recompute", REDACTIONS, f"values_sha256 (numbers unchanged by path redaction): {rp}",
                "pass" if mine == e["values_sha256"] else "mismatch", e["values_sha256"], mine)


def frozen_artifact(relpath: str) -> bool:
    """Files that must never change after a run: anything under release/, and dated preregistered variant files."""
    return relpath.startswith("release/") or bool(re.search(r"_\d{8}T\d{6}Z\.json$", relpath))


def hash_checks(rep: Report, obj, target: str, root: Path, strict_paths=()):
    """Every sha256 the result records with a resolvable path: {"path", "sha256"} objects, `<x>` + `<x>_sha256`
    sibling pairs, and {path: sha256} maps (source_sha256, modules_sha256)."""
    seen = set()

    def one(path_text, digest, where):
        if not isinstance(path_text, str) or not isinstance(digest, str) or (path_text, digest) in seen:
            return
        seen.add((path_text, digest))
        f = find_file(path_text, root)
        if f is None:
            rep.add("hash", target, f"{where}: {path_text}", "skip", digest, None,
                    "file not in this checkout (git-ignored or from another machine)")
            return
        now, rp = sha256(f), rel(f, root)
        if now == digest:
            rep.add("hash", target, f"{where}: {rp}", "pass", digest, now)
        elif documented_redaction(root, rp, digest, now):
            rep.add("hash", target, f"{where}: {rp}", "pass", digest, now, f"documented path redaction ({REDACTIONS})")
        else:
            strict = frozen_artifact(rp) or rp in strict_paths
            rep.add("hash", target, f"{where}: {rp}", "mismatch" if strict else "changed_since_run", digest, now,
                    "frozen artifact changed" if strict else "the file changed after the run (expected for code)")

    def walk(o, where):
        if isinstance(o, dict):
            if isinstance(o.get("path"), str) and isinstance(o.get("sha256"), str):
                one(o["path"], o["sha256"], where or "path")
            for k, v in o.items():
                m = SHA_KEY.match(k) if isinstance(k, str) else None
                if m and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v):
                    stem = m.group(1)
                    for pk in (stem, stem + "_file", stem + "_path"):
                        if isinstance(o.get(pk), str):
                            one(o[pk], v, f"{where}.{k}".strip("."))
                            break
                elif m and isinstance(v, dict) and v and all(isinstance(x, str) for x in v.values()):
                    sources_map(v, f"{where}.{k}".strip("."))
                elif isinstance(v, (dict, list)):
                    walk(v, f"{where}.{k}".strip("."))
        elif isinstance(o, list):
            for i, v in enumerate(o[:50]):
                walk(v, f"{where}[{i}]")

    def sources_map(mapping: dict, where):
        match, changed, missing = [], [], []
        for p, digest in mapping.items():
            f = find_file(p, root)
            if f is None:
                missing.append(p)
            elif sha256(f) == digest or documented_redaction(root, rel(f, root), digest, sha256(f)):
                match.append(p)
            else:
                changed.append(rel(f, root))
        frozen = [p for p in changed if frozen_artifact(p) or p in strict_paths]
        status = "mismatch" if frozen else "changed_since_run" if changed else "pass" if match else "skip"
        rep.add("hash", target, f"{where} ({len(mapping)} files)", status, len(mapping), len(match),
                {"unchanged": len(match), "changed_since_run": changed, "not_in_checkout": missing})

    walk(obj, "")


# ---------------------------------------------------------------------------------------------------------- tf_bench
def final_cases(records: list[dict]) -> dict:
    """(model, case_id, repeat) -> the last case record that is not an abort (a resumed run redoes aborted ones)."""
    out = {}
    for r in records:
        if r.get("type") == "case" and r.get("status") != "aborted":
            out[(r.get("model"), r.get("case_id"), r.get("repeat"))] = r
    return out


def tf_bench(rep: Report, d: Path, root: Path):
    target = rel(d, root)
    recs_path, res_path = d / "records.jsonl", d / "results.json"
    if not recs_path.is_file():
        rep.add("recompute", target, "records.jsonl", "skip", detail="no records.jsonl")
        return
    records, bad = read_jsonl(recs_path)
    final = final_cases(records)
    models = sorted({m for m, _, _ in final})
    if not res_path.is_file():
        info = {m: f"{sum(1 for (mm, _, _), c in final.items() if mm == m and c.get('status') == 'ok')}/"
                   f"{sum(1 for (mm, _, _) in final if mm == m)} ok" for m in models}
        rep.add("recompute", target, "results.json", "skip", None, info,
                "no results.json yet (run in progress or stopped); per-model counts so far shown as recomputed")
        return
    res = load_json(res_path)
    hash_checks(rep, res, target, root)
    rep.compare(target, "records.jsonl lines that are not JSON objects", len(res.get("records_skipped_lines") or []), bad)
    https = [r for r in records if r.get("type") == "http"]
    rep.compare(target, "http_calls.total", (res.get("http_calls") or {}).get("total"), len(https))
    rep.compare(target, "http_calls.retries", (res.get("http_calls") or {}).get("retries"),
                sum(1 for h in https if (h.get("attempt") or 1) > 1))
    for m, s in (res.get("per_model") or {}).items():
        p = f"per_model.{m}"
        done = [c for (mm, _, _), c in final.items() if mm == m]
        ok = [c for c in done if c.get("status") == "ok"]
        rep.compare(target, f"{p}.n_completed", s.get("n_completed"), len(done))
        rep.compare(target, f"{p}.success.count", s["success"]["count"], len(ok))
        rep.compare(target, f"{p}.success.wilson95", s["success"]["wilson95"],
                    [r4(v) for v in wilson(len(ok), len(done))] if done else None)
        fails: dict = {}
        for c in done:
            if c.get("failure_class"):
                fails[c["failure_class"]] = fails.get(c["failure_class"], 0) + 1
        rep.compare(target, f"{p}.failures", s.get("failures"), fails)
        e2e = [c["e2e_s"] for c in ok]
        e = s["e2e_latency_s"]
        rep.compare(target, f"{p}.e2e_latency_s.n", e["n"], len(e2e))
        for key, val in (("p50", pct(e2e, 50)), ("p95", pct(e2e, 95)), ("mean", avg(e2e)),
                         ("min", min(e2e) if e2e else None), ("max", max(e2e) if e2e else None)):
            rep.compare(target, f"{p}.e2e_latency_s.{key}", e[key], r4(val))
        tok = [c for c in ok if c.get("total_tokens") is not None]
        t = s["tokens_per_handover"]
        rep.compare(target, f"{p}.tokens_per_handover.n_with_usage", t["n_with_usage"], len(tok))
        for key, field in (("mean", "total_tokens"), ("prompt_mean", "prompt_tokens"), ("completion_mean", "completion_tokens")):
            v = avg([c.get(field) for c in tok])
            rep.compare(target, f"{p}.tokens_per_handover.{key}", t[key], None if v is None else round(v, 1), tol=0.05)
        cv = s["citation_validity"]
        proposed = sum(c.get("facts_proposed") or 0 for c in ok)
        valid = sum(c.get("citations_valid") or 0 for c in ok if c.get("facts_proposed"))
        rep.compare(target, f"{p}.citation_validity.proposed", cv["proposed"], proposed)
        rep.compare(target, f"{p}.citation_validity.valid", cv["valid"], valid)
        rep.compare(target, f"{p}.citation_validity.rate", cv["rate"], r4(valid / proposed) if proposed else None)
        reasons: dict = {}
        for c in ok:
            for reason in c.get("rejection_reasons") or []:
                reasons[reason] = reasons.get(reason, 0) + 1
        rep.compare(target, f"{p}.citation_validity.rejection_reasons", cv["rejection_reasons"], reasons)
        fp = s["facts_per_handover"]
        for key, field in (("proposed_mean", "facts_proposed"), ("accepted_mean", "facts_accepted")):
            v = avg([c.get(field) for c in ok])
            rep.compare(target, f"{p}.facts_per_handover.{key}", fp[key], None if v is None else round(v, 2), tol=0.005)
        decisions: dict = {}
        for c in ok:
            decisions[str(c.get("gate_decision"))] = decisions.get(str(c.get("gate_decision")), 0) + 1
        rep.compare(target, f"{p}.gate.decisions", s["gate"]["decisions"], decisions)
        ref_f = sum(c.get("reference_facts") or 0 for c in ok)
        ref_m = sum(c.get("reference_matched") or 0 for c in ok if c.get("reference_facts"))
        rep.compare(target, f"{p}.reference_agreement_heuristic.matched", s["reference_agreement_heuristic"]["matched"], ref_m)
        rep.compare(target, f"{p}.reference_agreement_heuristic.recorded_facts",
                    s["reference_agreement_heuristic"]["recorded_facts"], ref_f)
        tt = [r["ttft_s"] for r in records if r.get("type") == "ttft" and r.get("model") == m and r.get("ttft_s") is not None]
        rep.compare(target, f"{p}.ttft_s.p50", s["ttft_s"]["p50"], r4(pct(tt, 50)))
        mh = [h for h in https if h.get("model") == m]
        statuses: dict = {}
        for h in mh:
            statuses[str(h.get("status"))] = statuses.get(str(h.get("status")), 0) + 1
        rep.compare(target, f"{p}.http.calls", s["http"]["calls"], len(mh))
        rep.compare(target, f"{p}.http.statuses", s["http"]["statuses"], statuses)
        rep.add("recompute", target, f"{p}.*ci95 (bootstrap)", "skip", detail="bootstrap intervals are not recomputed")


# ---------------------------------------------------------------------------------------------------------- crosscheck
def crosscheck(rep: Report, d: Path, root: Path):
    target = rel(d, root)
    res_path = d / "results.json"
    if not res_path.is_file():
        rep.add("recompute", target, "results.json", "skip", detail="no results.json yet (run in progress?)")
        return
    res = load_json(res_path)
    hash_checks(rep, res, target, root)
    rows = res.get("rows") or []
    records, _ = read_jsonl(d / "records.jsonl") if (d / "records.jsonl").is_file() else ([], 0)
    judged = {}
    for r in records:
        if r.get("type") == "judge":
            judged[(r.get("set"), r.get("item_id"))] = r
    if records:
        disagree = [f"{x['set']}:{x['id']}" for x in rows
                    if (j := judged.get((x["set"], x["id"]))) is not None
                    and (bool(j.get("flag")) != bool(x.get("flag")) or j.get("status") != x.get("judge_status"))]
        # a row the run marks as never judged (judge_status null: the call cap stopped the run before it, or its set
        # was not asked for) has no judge record by design: excluded here, and per set the excluded count must be the
        # run's own sets.<name>.not_judged (a set with no sets entry is one none of whose rows was judged)
        not_judged = [x for x in rows if x.get("judge_status") is None and (x["set"], x["id"]) not in judged]
        missing = [f"{x['set']}:{x['id']}" for x in rows
                   if (x["set"], x["id"]) not in judged and x.get("judge_status") is not None]
        rep.add("recompute", target, "rows[].flag / judge_status vs records.jsonl judge records",
                "pass" if not disagree and not missing else "mismatch", len(rows) - len(not_judged),
                len(rows) - len(not_judged) - len(disagree) - len(missing),
                {"disagree": disagree[:20], "no_judge_record": missing[:20], "not_judged_excluded": len(not_judged),
                 "stopped_reason": res.get("stopped_reason")})
        names = {"variant": "variants", "original": "original",
                 **{s.get("set"): s.get("name") for s in res.get("secondary_variant_sets") or [] if s.get("set")}}
        for s in sorted({x["set"] for x in rows}):
            rec = (res.get("sets") or {}).get(names.get(s, s))
            n_set = sum(1 for x in rows if x["set"] == s)
            reported = rec.get("not_judged", 0) if rec else n_set
            where = f"sets.{names.get(s, s)}.not_judged" if rec else f"no sets entry for {s!r}: all {n_set} rows"
            rep.compare(target, f"rows of set {s!r} not judged and excluded ({where})", reported,
                        sum(1 for x in not_judged if x["set"] == s))
        first = min((r["ts"] for r in records if r.get("type") == "judge" and r.get("ts")), default=None)
        rep.compare(target, "first_judge_call_utc (earliest judge record)", res.get("first_judge_call_utc"), first)
        pre = d / "preregistration.json"
        # an http record's ts is when the request started; a judge record is written after its call returned
        starts = [r["ts"] for r in records if r.get("type") == "http" and r.get("purpose") == "judge" and r.get("ts")]
        earliest = min(starts + ([first] if first else []), default=None)
        if pre.is_file() and earliest:
            p = load_json(pre)
            ordered = str(p.get("created_utc")) < str(earliest)
            rep.add("recompute", target, "preregistration.created_utc precedes the first judge call",
                    "pass" if ordered else "mismatch", p.get("created_utc"), earliest)
    views = {"variants": [x for x in rows if x["set"] == "variant"],
             "original": [x for x in rows if x["set"] == "original"],
             "original_heldout": [x for x in rows if x["set"] == "original" and x.get("heldout")],
             "variants_of_heldout_parents": [x for x in rows if x["set"] == "variant" and x.get("heldout")]}
    for name, rs in views.items():
        rec = (res.get("sets") or {}).get(name)
        if rec is None:
            continue
        p = f"sets.{name}"
        att = [x for x in rs if x["label"] == "attack"]
        ben = [x for x in rs if x["label"] != "attack"]
        unv = [x for x in rs if x.get("judge_status") != "ok"]
        with_rules = [x for x in rs if x.get("rules") is not None]
        flag = lambda x: x.get("judge_status") == "ok" and bool(x.get("flag"))              # noqa: E731
        flag_c = lambda x: x.get("judge_status") != "ok" or bool(x.get("flag"))            # noqa: E731
        rules = lambda x: x.get("rules") in STOPPED                                          # noqa: E731
        ra = [x for x in att if x.get("rules") is not None]
        rb = [x for x in ben if x.get("rules") is not None]
        rep.compare(target, f"{p}.rows/attacks/benign/rules_na",
                    [rec["rows"], rec["attacks"], rec["benign"], rec["rules_na"]],
                    [len(rs), len(att), len(ben), len(rs) - len(with_rules)])
        rep.compare(target, f"{p}.rules_only.attack_recall", rec["rules_only"]["attack_recall"],
                    kn(sum(map(rules, ra)), len(ra)))
        rep.compare(target, f"{p}.rules_only.benign_false_block", rec["rules_only"]["benign_false_block"],
                    kn(sum(map(rules, rb)), len(rb)))
        rep.compare(target, f"{p}.judge_only.conservative.attack_recall",
                    rec["judge_only"]["conservative"]["attack_recall"], kn(sum(map(flag, att)), len(att)))
        rep.compare(target, f"{p}.judge_only.conservative.benign_false_block",
                    rec["judge_only"]["conservative"]["benign_false_block"], kn(sum(map(flag_c, ben)), len(ben)))
        rep.compare(target, f"{p}.rules_or_judge.conservative.attack_recall",
                    rec["rules_or_judge"]["conservative"]["attack_recall"],
                    kn(sum(1 for x in ra if rules(x) or flag(x)), len(ra)))
        rep.compare(target, f"{p}.rules_or_judge.conservative.benign_false_block",
                    rec["rules_or_judge"]["conservative"]["benign_false_block"],
                    kn(sum(1 for x in rb if rules(x) or flag_c(x)), len(rb)))
        rep.compare(target, f"{p}.unverified", rec["unverified"], kn(len(unv), len(rs)))
        if name == "variants" and res.get("acceptance"):
            k = sum(1 for x in ra if rules(x) or flag(x))
            fb = sum(1 for x in rb if rules(x) or flag_c(x))
            low = wilson(k, len(ra))[0] if ra else None
            fbr = fb / len(rb) if rb else None
            ur = len(unv) / len(rs) if rs else None
            ch = res["acceptance"]["checks"]
            rep.compare(target, "acceptance.checks.recall_wilson_lower.value", ch["recall_wilson_lower"]["value"], r4(low))
            rep.compare(target, "acceptance.checks.benign_false_block_rate.value", ch["benign_false_block_rate"]["value"], r4(fbr))
            rep.compare(target, "acceptance.checks.unverified_rate.value", ch["unverified_rate"]["value"], r4(ur))
            verdict = "PASS" if (low is not None and low >= ch["recall_wilson_lower"]["threshold"]
                                 and fbr is not None and fbr <= ch["benign_false_block_rate"]["threshold"]
                                 and ur is not None and ur <= ch["unverified_rate"]["threshold"]
                                 and not res["acceptance"].get("incomplete")) else "FAIL"
            rep.compare(target, "acceptance.result", res["acceptance"]["result"], verdict)


# ---------------------------------------------------------------------------------------------------------- red team
def redteam_counts(cases: list[dict]) -> dict:
    att = [c for c in cases if c.get("expected_outcome") in STOPPED]
    ctl = [c for c in cases if c.get("expected_outcome") not in STOPPED]
    stop = [c for c in att if c.get("actual_outcome") in STOPPED]
    gaps = [c for c in att if c.get("known_gap")]
    h_att = [c for c in att if c.get("heldout")]
    return {"cases": len(cases), "attacks": len(att), "controls": len(ctl), "known_gap_cases": sum(bool(c.get("known_gap")) for c in cases),
            "stopped": len(stop), "stopped_excl_gaps": sum(1 for c in stop if not c.get("known_gap")),
            "attacks_excl_gaps": len(att) - len(gaps),
            "false_blocks": sum(1 for c in ctl if c.get("actual_outcome") in STOPPED),
            "heldout_attacks": len(h_att), "heldout_stopped": sum(1 for c in h_att if c.get("actual_outcome") in STOPPED),
            "heldout_missed": sorted(c["id"] for c in h_att if c.get("actual_outcome") not in STOPPED),
            "known_gap_ids": sorted(c["id"] for c in cases if c.get("known_gap") and c.get("status") == "gap_confirmed")}


def redteam(rep: Report, d: Path, root: Path):
    target = rel(d, root)
    if not (d / "results.json").is_file():
        rep.add("recompute", target, "results.json", "skip", detail="no results.json")
        return
    res = load_json(d / "results.json")
    hash_checks(rep, res, target, root)
    s, mine = res["summary"], redteam_counts(res.get("cases") or [])
    for key in ("cases", "attacks", "controls", "known_gap_cases"):
        rep.compare(target, f"summary.{key}", s[key], mine[key])
    rep.compare(target, "summary.block_recall (stopped/attacks)", [s["block_recall"]["stopped"], s["block_recall"]["attacks"]],
                [mine["stopped"], mine["attacks"]])
    rep.compare(target, "summary.block_recall.rate", s["block_recall"]["rate"], r4(mine["stopped"] / mine["attacks"]))
    ex = s["block_recall_excluding_known_gaps"]
    rep.compare(target, "summary.block_recall_excluding_known_gaps (stopped/attacks)", [ex["stopped"], ex["attacks"]],
                [mine["stopped_excl_gaps"], mine["attacks_excl_gaps"]])
    rep.compare(target, "summary.false_block_rate (blocked/controls)",
                [s["false_block_rate"]["blocked"], s["false_block_rate"]["controls"]], [mine["false_blocks"], mine["controls"]])
    if "heldout" in s:
        rep.compare(target, "summary.heldout (attacks/stopped/missed)",
                    [s["heldout"]["attacks"], s["heldout"]["stopped"], sorted(s["heldout"]["missed"])],
                    [mine["heldout_attacks"], mine["heldout_stopped"], mine["heldout_missed"]])
    if "known_gaps" in s:
        rep.compare(target, "summary.known_gaps[].id (status gap_confirmed)",
                    sorted(g["id"] for g in s["known_gaps"] if g.get("status") == "gap_confirmed"), mine["known_gap_ids"])


def redteam_before_after(rep: Report, before: Path, after: Path, root: Path) -> dict | None:
    """The fixed run's outcome on the attack ids of the earlier run (the R09 derivation in submission/SOURCES.md)."""
    b, a = load_json(before / "results.json"), load_json(after / "results.json")
    ids = {c["id"] for c in b["cases"] if c.get("expected_outcome") in STOPPED}
    ctl = {c["id"] for c in b["cases"] if c.get("expected_outcome") not in STOPPED}
    by = {c["id"]: c for c in a["cases"]}
    out = {"before_stopped": sum(1 for c in b["cases"] if c["id"] in ids and c.get("actual_outcome") in STOPPED),
           "attacks": len(ids), "after_stopped": sum(1 for i in ids if by.get(i, {}).get("actual_outcome") in STOPPED),
           "after_not_stopped": sorted(i for i in ids if by.get(i, {}).get("actual_outcome") not in STOPPED),
           "controls": len(ctl), "after_control_blocks": sum(1 for i in ctl if by.get(i, {}).get("actual_outcome") in STOPPED),
           "ids_missing_after": sorted(i for i in ids | ctl if i not in by)}
    rep.add("recompute", f"{rel(before, root)} -> {rel(after, root)}", "same attack ids before vs after the fixes",
            "pass" if not out["ids_missing_after"] else "mismatch", None, out)
    return out


# ---------------------------------------------------------------------------------------------------------- agreement
def norm(s: str) -> str:
    """Quote normalization of the agreement definition: curly quotes straightened, whitespace collapsed, lower case."""
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def fact_groups(nodes: set) -> dict:
    """Connected components of 'same type and one normalized quote contains the other'; node -> component id."""
    nodes = sorted(nodes)
    comp = {n: i for i, n in enumerate(nodes)}
    for a, b in itertools.combinations(nodes, 2):
        if a[0] == b[0] and a[1] and b[1] and (a[1] in b[1] or b[1] in a[1]) and comp[a] != comp[b]:
            old, new = max(comp[a], comp[b]), min(comp[a], comp[b])
            for n in comp:
                if comp[n] == old:
                    comp[n] = new
    return comp


def jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def agreement(rep: Report, d: Path, root: Path):
    target = rel(d, root)
    if not (d / "results.json").is_file():
        rep.add("recompute", target, "results.json", "skip", detail="no results.json")
        return
    res = load_json(d / "results.json")
    hash_checks(rep, res, target, root)
    inp = (res.get("inputs") or {}).get("records_jsonl") or {}
    src = find_file(inp.get("path", ""), root)
    if src is None:
        rep.add("recompute", target, "bench records", "skip", detail="the analysed records.jsonl is not in this checkout")
        return
    records, _ = read_jsonl(src)
    ok = {}
    for c in records:
        if c.get("type") == "case" and c.get("status") == "ok":
            ok[(c["model"], c["update_id"], c["repeat"])] = c
    run = res.get("run") or {}
    models, updates, repeats = run.get("models") or [], run.get("update_ids") or [], run.get("repeats") or 3
    sets = {}
    for u in updates:
        comp = fact_groups({((f.get("type") or ""), norm(f.get("quote") or ""))
                            for (_, uu, _), c in ok.items() if uu == u for f in c.get("accepted_facts") or []})
        for m in models:
            reps = sorted(r for (mm, uu, r) in ok if mm == m and uu == u)
            if len(reps) == repeats:
                sets[(m, u)] = [{comp[((f.get("type") or ""), norm(f.get("quote") or ""))]
                                 for f in ok[(m, u, r)].get("accepted_facts") or []} for r in reps]
    nums = res.get("numbers") or {}
    majority = {}
    for m in models:
        rec = (nums.get("within_model") or {}).get(m)
        if rec is None:
            continue
        vals, dist = [], {str(c): 0 for c in range(repeats, 0, -1)}
        for u in updates:
            if (m, u) not in sets:
                continue
            per = sets[(m, u)]
            vals.append(statistics.fmean(jac(a, b) for a, b in itertools.combinations(per, 2)))
            counts: dict = {}
            for s_ in per:
                for k in s_:
                    counts[k] = counts.get(k, 0) + 1
            for v in counts.values():
                dist[str(v)] += 1
            majority[(m, u)] = {k for k, v in counts.items() if 2 * v > len(per)}
        p = f"numbers.within_model.{m}"
        rep.compare(target, f"{p}.n_updates", rec["n_updates"], len(vals))
        rep.compare(target, f"{p}.mean_pairwise_jaccard", rec["mean_pairwise_jaccard"], r4(avg(vals)))
        rep.compare(target, f"{p}.keys", rec["keys"], sum(dist.values()))
        rep.compare(target, f"{p}.keys_by_repeat_count", rec["keys_by_repeat_count"], dist)
    for name, rec in (nums.get("cross_model") or {}).items():
        a, b = rec["models"]
        vals = [jac(majority[(a, u)], majority[(b, u)]) for u in updates if (a, u) in majority and (b, u) in majority]
        p = f'numbers.cross_model["{name}"]'
        rep.compare(target, f"{p}.mean_jaccard", rec["mean_jaccard"], r4(avg(vals)))
        rep.compare(target, f"{p}.min/max", [rec["min"], rec["max"]], [r4(min(vals)), r4(max(vals))] if vals else [None, None])
    units = nums.get("units") or []
    pooled = ((nums.get("confidence_signal") or {}).get("reference_agreement") or {}).get("pooled") or {}

    def bucket(us):
        return {"n": len(us), "reference_matched": sum(bool(x.get("reference_match")) for x in us)}

    for key, us in (("3", [x for x in units if x.get("repeat_count") == repeats]),
                    ("1-2", [x for x in units if x.get("repeat_count", 0) < repeats])):
        rec = (pooled.get("by_repeat_count") or {}).get(key)
        if rec:
            rep.compare(target, f"reference_agreement.pooled.by_repeat_count.{key} (n/matched)",
                        [rec["n"], rec["reference_matched"]], [bucket(us)["n"], bucket(us)["reference_matched"]])
    for key, flag in (("present", True), ("absent", False)):
        rec = (pooled.get("by_other_model") or {}).get(key)
        if rec:   # null other_model_present (the other model's update not complete) is in neither bucket
            us = [x for x in units if x.get("other_model_present") is flag]
            rep.compare(target, f"reference_agreement.pooled.by_other_model.{key} (n/matched)",
                        [rec["n"], rec["reference_matched"]], [bucket(us)["n"], bucket(us)["reference_matched"]])
    rep.compare(target, "numbers.units (count) vs sum of within_model keys",
                len(units), sum((nums.get("within_model") or {}).get(m, {}).get("keys", 0) for m in models))


# ---------------------------------------------------------------------------------------------------------- capacity
def lookup(obj, path: str):
    """A dotted key path into JSON (dict keys may contain dots: the longest matching key wins)."""
    vals = resolve(obj, path)
    if len(vals) != 1:
        raise KeyError(path)
    return vals[0]


def capacity(rep: Report, d: Path, root: Path):
    target = rel(d, root)
    if not (d / "results.json").is_file():
        rep.add("recompute", target, "results.json", "skip", detail="no results.json")
        return
    res = load_json(d / "results.json")
    hash_checks(rep, res, target, root)
    measured = res.get("measured") or {}
    for section, m in measured.items():   # every measured input against the result file and key it names
        if not isinstance(m, dict) or not m.get("items"):
            continue
        for name, it in m["items"].items():
            src = find_file(it.get("source") or m.get("path") or "", root)
            if src is None:
                rep.add("recompute", target, f"measured.{section}.items.{name}", "skip", it.get("value"), None,
                        f"{it.get('source')} not in this checkout")
                continue
            try:
                val = lookup(load_json(src), it["key"])
            except (KeyError, TypeError):
                rep.add("recompute", target, f"measured.{section}.items.{name}", "mismatch", it.get("value"), None,
                        f"key {it.get('key')} not in {it.get('source')}")
                continue
            rep.compare(target, f"measured.{section}.items.{name} vs {it['key']}", it.get("value"), val)
    items = {k: v.get("value") for k, v in ((measured.get("tf_bench") or {}).get("items") or {}).items()}
    load = {k: v.get("value") for k, v in ((measured.get("load_test") or {}).get("items") or {}).items()}
    a = {k: (v or {}).get("value") for k, v in (res.get("assumptions") or {}).items()}
    o = res.get("outputs") or {}
    conv = res.get("conventions") or {}
    days, scale = conv.get("days_per_month", 30), conv.get("families_scale", 1000)
    tok, secs, upd = items.get("tokens_per_handover"), items.get("e2e_latency_mean_s"), a.get("updates_per_family_per_day")
    if None in (tok, secs, upd) or a.get("crosscheck_every_update"):
        rep.add("recompute", target, "outputs", "skip", detail="inputs missing or crosscheck cost included (not modelled here)")
        return
    fam = a.get("families_per_care_coordinator")
    # handovers per hour: the load test's measured throughput when the result used it, else one sequential stream
    use_load = (measured.get("load_test") or {}).get("used") and load.get("throughput_handovers_per_s")
    per_hour = load["throughput_handovers_per_s"] * 3600 if use_load else 3600 / secs
    mine = {"tokens_per_update": tok, "tokens_per_family_per_day": tok * upd, "tokens_per_family_per_month": tok * upd * days,
            "tokens_per_1000_families_per_day": tok * upd * scale, "seconds_per_update_sequential": secs,
            "handovers_per_stream_hour_sequential": 3600 / secs, "hours_per_1000_families_per_day": scale * upd / per_hour,
            "updates_per_coordinator_per_day": upd * fam, "tokens_per_coordinator_per_day": tok * upd * fam,
            "hours_per_coordinator_per_day": upd * fam / per_hour}
    if use_load:
        mine["handovers_per_endpoint_hour_at_load_concurrency"] = per_hour
        mine["load_concurrency"] = load.get("concurrency")
    rep.compare(target, "outputs.capacity_basis", o.get("capacity_basis"), "load test" if use_load else "sequential")
    for k, v in mine.items():
        if k in o:
            rep.compare(target, f"outputs.{k}", o[k], v, tol=max(1e-6, 1e-6 * abs(v)))


# ---------------------------------------------------------------------------------------------------------- load test
def load_test(rep: Report, d: Path, root: Path):
    """Per concurrency level from the request and http records: counts, latency percentiles, wall time, throughput;
    then the selected level (most successful handovers per second of wall time, ties to the lower concurrency)."""
    target = rel(d, root)
    if not (d / "results.json").is_file() or not (d / "records.jsonl").is_file():
        rep.add("recompute", target, "results.json", "skip", detail="no results.json or records.jsonl yet (in progress?)")
        return
    res = load_json(d / "results.json")
    hash_checks(rep, res, target, root)
    records, bad = read_jsonl(d / "records.jsonl")
    rep.compare(target, "records.jsonl lines that are not JSON objects", len(res.get("records_skipped_lines") or []), bad)
    https = [r for r in records if r.get("type") == "http"]
    hc = res.get("http_calls") or {}
    rep.compare(target, "http_calls (total/retries/status_429)", [hc.get("total"), hc.get("retries"), hc.get("status_429")],
                [len(https), sum(1 for h in https if (h.get("attempt") or 1) > 1), sum(1 for h in https if h.get("status") == 429)])
    walls = {r.get("level"): r.get("wall_s") for r in records if r.get("type") == "level_end"}
    # a record names its level by the label of its level_start record; the k-th level_start is results levels[k]
    labels = list(dict.fromkeys(r.get("level") for r in records if r.get("type") == "level_start"))
    best = None
    for k, lv in enumerate(res.get("levels") or []):
        i = labels[k] if k < len(labels) else None
        p = f"levels[{k}] (concurrency {lv.get('concurrency')})"
        reqs = {}
        for r in records:   # the last record of each request index of this level
            if r.get("type") == "request" and r.get("level") == i:
                reqs[r.get("index")] = r
        ok = [r for r in reqs.values() if r.get("status") == "ok"]
        rep.compare(target, f"{p}.completed/ok", [lv.get("completed"), lv.get("ok")], [len(reqs), len(ok)])
        e2e = [r["e2e_s"] for r in ok]
        lat = lv.get("latency_s") or {}
        for key, val in (("p50", pct(e2e, 50)), ("p95", pct(e2e, 95)), ("mean", avg(e2e))):
            rep.compare(target, f"{p}.latency_s.{key}", lat.get(key), r4(val))
        wall = walls.get(i)
        rep.compare(target, f"{p}.wall_s vs level_end record", lv.get("wall_s"), wall)
        th = lv.get("throughput") or {}
        if wall:
            rep.compare(target, f"{p}.throughput.handovers_per_min", th.get("handovers_per_min"), round(60 * len(ok) / wall, 3),
                        tol=0.0006)
            ct = [r.get("completion_tokens") for r in ok]
            if all(isinstance(x, int) for x in ct) and ct:
                rep.compare(target, f"{p}.throughput.completion_tokens", th.get("completion_tokens"), sum(ct))
            rate = len(ok) / wall
            if best is None or rate > best[0] + 1e-12:
                best = (rate, lv.get("concurrency"))
        lh = [h for h in https if h.get("level") == i]
        rep.compare(target, f"{p}.http (attempts/retries/status_429)",
                    [(lv.get("http") or {}).get(k) for k in ("attempts", "retries", "status_429")],
                    [len(lh), sum(1 for h in lh if (h.get("attempt") or 1) > 1), sum(1 for h in lh if h.get("status") == 429)])
    for m, s in (res.get("per_model") or {}).items():
        if best is not None:
            rep.compare(target, f"per_model.{m}.concurrency (selected level)", s.get("concurrency"), best[1])
            rep.compare(target, f"per_model.{m}.throughput_handovers_per_s", s.get("throughput_handovers_per_s"),
                        best[0], tol=1e-5)


# ---------------------------------------------------------------------------------------------------------- scorecard
def scorecard(rep: Report, f: Path, root: Path):
    target = rel(f, root)
    snap = load_json(f)
    doc, frozen = snap.get("doc") or {}, snap.get("frozen") or {}
    results = doc.get("results") or []
    rep.compare(target, "doc.test_processes", doc.get("test_processes"), len(results))
    rep.compare(target, "doc.unittest_cases", doc.get("unittest_cases"), sum(r.get("unittest_cases") or 0 for r in results))
    passed = bool(doc.get("sources_unchanged_during_run")) and all(r.get("passed") for r in results)
    rep.compare(target, "doc.passed", doc.get("passed"), passed)
    rep.compare(target, "doc.exit_code", doc.get("exit_code"), 0 if passed else 1)
    each = [r for r in results if r.get("passed") != (r.get("exit_code") == 0 and (not r.get("requires_unittest_count")
                                                                                  or (r.get("unittest_cases") or 0) > 0))]
    rep.add("recompute", target, "doc.results[].passed from exit_code and unittest count",
            "pass" if not each else "mismatch", len(results), len(results) - len(each), [r.get("command") for r in each][:10])
    if frozen.get("source_dir") and frozen.get("source_file") and frozen.get("source_sha256"):
        src = find_file(f"{frozen['source_dir']}/{frozen['source_file']}", root)
        if src is None:
            rep.add("hash", target, "frozen.source_sha256", "skip", frozen["source_sha256"], None,
                    "the frozen source summary is git-ignored (release/validation_abd/); not in this checkout")
        else:
            now, was = sha256(src), frozen["source_sha256"]
            rep.add("hash", target, f"frozen.source_sha256: {rel(src, root)}",
                    "pass" if now == was or documented_redaction(root, rel(src, root), was, now) else "mismatch", was, now)
    hash_checks(rep, {"doc.source_sha256": doc.get("source_sha256") or {}}, target, root)


# ---------------------------------------------------------------------------------------------------------- SOURCES.md
NUM = re.compile(r"(?<![A-Za-z0-9_\-.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![A-Za-z0-9_])")
POOL_NUM = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?")
LINE_CITE = re.compile(r"^(?P<path>[^`:\s][^`:]*\.[A-Za-z0-9]+):(?P<lines>\d+(?:\s*[-,]\s*\d+)*)$")


def numbers_in(text: str) -> list[str]:
    """Number tokens as written (thousands commas removed), leaving out confidence-level labels such as '95% CI'."""
    text = re.sub(r"(?i)(wilson[- ]?95\s*%?|95\s*%\s*(?:ci|interval)|ci95|wilson95)", " ", text)
    return [m.group(1).replace(",", "") + (m.group(2) or "") for m in NUM.finditer(text)]


def leaves(o) -> list:
    if isinstance(o, dict):
        return [x for v in o.values() for x in leaves(v)] + [k for k in o if isinstance(k, str)]
    if isinstance(o, list):
        return [x for v in o for x in leaves(v)]
    return [o]


def number_found(tok: str, pool_nums: list[float], fracs: list[tuple[int, int]]) -> bool:
    """tok as written matches a value of the pool (equal, or that value rounded to tok's decimals, or as a percent),
    or is the percent of a k/n written in the same cell."""
    dp = len(tok.split(".")[1]) if "." in tok else 0
    v = float(tok)
    unit = 0.5 * 10 ** -dp + 1e-9
    for x in pool_nums:
        if abs(x - v) <= unit or abs(x * 100 - v) <= unit:
            return True
    return any(n and abs(100 * k / n - v) <= unit for k, n in fracs)


def parse_value(text: str):
    """The value after `key` = in a SOURCES row: a number, true/false/null, [a, b], or {k: v, ...} / {k v, ...}."""
    t = text.strip().rstrip(",").strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", t):
        return float(t)
    if t.lower() in ("true", "false"):
        return t.lower() == "true"
    if t.lower() in ("null", "none"):
        return None
    if t.startswith("[") and t.endswith("]"):
        return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", t)]
    if t.startswith("{") and t.endswith("}"):
        pairs = re.findall(r"([A-Za-z_][\w\-]*|\d+)\s*:?\s+(-?\d+(?:\.\d+)?)", t[1:-1].replace(":", ": "))
        return {"__exact__": ":" in t, **{k: float(v) for k, v in pairs}}
    return t


def value_matches(claim, actual) -> tuple[bool, str]:
    def num_eq(c: float, a, written: str | None = None) -> bool:
        if isinstance(a, bool) or not isinstance(a, (int, float)):
            return False
        return abs(a - c) <= 0.5 * 10 ** -(len(written.split(".")[1]) if written and "." in written else 0) + 1e-9 \
            if written else abs(a - c) <= 5e-5 + 1e-9
    if isinstance(claim, bool) or claim is None:
        return (actual is claim), f"actual {actual!r}"
    if isinstance(claim, float):
        return (isinstance(actual, (int, float)) and not isinstance(actual, bool) and abs(actual - claim) <= 5e-5), \
            f"actual {actual!r}"
    if isinstance(claim, list):
        ok = isinstance(actual, list) and len(actual) == len(claim) and all(num_eq(c, a) for c, a in zip(claim, actual))
        return ok, f"actual {actual!r}"
    if isinstance(claim, dict):
        if not isinstance(actual, dict):
            return False, f"actual {actual!r}"
        exact = claim.pop("__exact__", False)
        ak = {str(k): v for k, v in actual.items()}
        bad = [k for k, v in claim.items() if k not in ak or not num_eq(v, ak[k])]
        extra = [k for k, v in ak.items() if exact and k not in claim and isinstance(v, (int, float))
                 and not isinstance(v, bool)]
        return not bad and not extra, f"actual {actual!r}" + (f"; keys not in the claim {extra}" if extra else "")
    return (str(actual) == claim), f"actual {actual!r}"


def resolve(obj, path: str) -> list:
    """Values at a key path: dotted keys (longest dict key first, so 'Qwen3.8-27B' works), [n], ["key"], * wildcard."""
    path = path.strip()
    if path.startswith("."):
        path = path[1:]
    if not path:
        return [obj]
    m = re.match(r'\[(\d+)\]|\["([^"]+)"\]', path)
    if m:
        rest = path[m.end():]
        if m.group(1) is not None and isinstance(obj, list) and int(m.group(1)) < len(obj):
            return resolve(obj[int(m.group(1))], rest)
        if m.group(2) is not None and isinstance(obj, dict) and m.group(2) in obj:
            return resolve(obj[m.group(2)], rest)
        raise KeyError(path)
    if path.startswith("*"):
        items = obj.values() if isinstance(obj, dict) else obj if isinstance(obj, list) else []
        out = []
        for v in items:
            try:
                out += resolve(v, path[1:])
            except KeyError:
                pass
        if not out:
            raise KeyError(path)
        return out
    if isinstance(obj, dict):
        for k in sorted(map(str, obj), key=len, reverse=True):
            if path == k or path.startswith(k + ".") or path.startswith(k + "["):
                try:
                    return resolve(obj[k], path[len(k):])
                except KeyError:
                    continue
    if isinstance(obj, list):
        m = re.match(r"(\d+)", path)
        if m and int(m.group(1)) < len(obj):
            return resolve(obj[int(m.group(1))], path[m.end():])
    raise KeyError(path)


def resolve_relative(obj, anchor: str, key: str) -> tuple[str, list]:
    """A `.key` written after an absolute key: tried under the anchor's parents, nearest first."""
    parts = anchor.split(".")
    for i in range(len(parts) - 1, -1, -1):
        cand = ".".join(parts[:i]) + key if i else key[1:]
        try:
            return cand, resolve(obj, cand)
        except KeyError:
            continue
    raise KeyError(key)


def table_rows(text: str):
    """(line number, id, cells) of every claim row: a table row whose first cell is an id such as B04."""
    for i, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and re.fullmatch(r"[A-Z]{1,2}\d{2}", cells[0]):
            yield i, cells[0], cells


def split_outside_backticks(s: str, sep: str) -> list[str]:
    out, cur, tick = [], "", False
    for ch in s:
        if ch == "`":
            tick = not tick
        if ch == sep and not tick:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def quotes_in(text: str) -> list[str]:
    qs = re.findall(r'"([^"]{4,})"', text) + re.findall(r"“([^”]{4,})”", text)
    return [q for q in qs if not re.fullmatch(r"[\w\- ]+", q) or len(q.split()) > 2]


def squash(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("&#x27;", "'").replace("&#39;", "'").replace("&quot;", '"').replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def parse_lines(spec: str) -> list[int]:
    out = []
    for part in re.split(r"\s*,\s*", spec):
        if "-" in part:
            a, b = (int(x) for x in part.split("-"))
            out += list(range(a, b + 1))
        elif part:
            out.append(int(part))
    return out


def sources_md(rep: Report, path: Path, root: Path, derived: dict):
    target = rel(path, root)
    if not path.is_file():
        rep.add("claim", target, "SOURCES.md", "skip", detail="no submission/SOURCES.md")
        return
    text = path.read_text(encoding="utf-8")
    aliases = {a: p for a, p in re.findall(r"`([A-Z]{3,})` = `([^`]+)`", text)}
    for lineno, rid, cells in table_rows(text):
        claim_cell, number_cell, source = cells[1], cells[2], cells[-1]
        what = f"{rid} (SOURCES.md:{lineno})"
        if "[[PENDING" in source or "[[PENDING" in number_cell:
            rep.add("claim", target, what, "pending", detail=re.search(r"\[\[([^\]]*)\]\]", source + number_cell).group(1)[:160])
            continue
        if "**derived**" in source:
            if "REDTEAM" in source and "cases[]" in source:
                claim_derived(rep, target, what, number_cell, derived)
            else:
                rep.add("claim", target, what, "skip", number_cell, None,
                        "derived row: no recomputation for it here; run the command its source cell gives")
            continue
        problems, notes, pool_text, pool_vals = [], [], [], []
        alias_dir = None
        for seg in split_outside_backticks(source, ";"):
            seg = seg.strip()
            base = None
            am = re.match(r"([A-Z]{3,})\b", seg)
            if am and am.group(1) in aliases:
                apath = root / aliases[am.group(1)]
                if apath.is_dir():
                    alias_dir = apath
                else:
                    base, alias_dir = apath, apath.parent
            fm = re.search(r"`([^`]+\.json)`\s*→", seg) or re.search(r"(\S+\.json)\s*→", seg)
            if fm:
                cand = fm.group(1)
                if re.match(r"^([A-Za-z]:[\\/]|/|\\\\)", cand):   # a path of one machine: no one else can open it
                    problems.append(f"cited file is outside the repository (not checkable by a third party): {cand}")
                    continue
                f = (root / cand) if (root / cand).is_file() else (alias_dir / cand if alias_dir and (alias_dir / cand).is_file() else None)
                if f is None:
                    problems.append(f"cited file {cand} is not in the repository")
                    continue
                base = f
            # path:line citations
            for tok in re.findall(r"`([^`]+)`", seg):
                lm = LINE_CITE.match(tok.strip())
                if not lm:
                    continue
                f = root / lm.group("path")
                if not f.is_file() and alias_dir is not None:
                    f = alias_dir / lm.group("path")
                if not f.is_file():
                    problems.append(f"{tok}: file not found")
                    continue
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
                want = parse_lines(lm.group("lines"))
                if max(want) > len(lines):
                    problems.append(f"{tok}: the file has {len(lines)} lines")
                    continue
                cited = squash(" ".join(lines[n - 1] for n in want))
                pool_text.append(cited)
                after = seg.split(f"`{tok}`", 1)[1]
                qm = re.match(r"\s*\(\s*([\"“])(.+?)[\"”]\s*\)", after)
                if qm and squash(qm.group(2)) not in cited:
                    problems.append(f"{tok}: quoted text not on the cited line(s)")
            if base is None:
                continue
            try:
                doc = load_json(base)
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{rel(base, root)}: {exc}")
                continue
            anchor = None
            part = seg.split("→", 1)[1] if "→" in seg else ""
            for km in re.finditer(r"`([^`]+)`(\s*\((\d+) entries\))?(\s*=\s*(\{[^}]*\}|\[[^\]]*\]|[^,`;(]+))?", part):
                key, n_entries, value = km.group(1), km.group(3), km.group(5)
                if LINE_CITE.match(key) or "/" in key or re.search(r"\.(md|json|jsonl|py|txt|lock|svg|html|toml|ya?ml|example)$", key):
                    continue
                try:
                    if key.startswith(".") and anchor:
                        full, vals = resolve_relative(doc, anchor, key)
                    else:
                        full, vals = key, resolve(doc, key)
                    anchor = full
                except KeyError:
                    problems.append(f"{rel(base, root)} → {key}: key not found")
                    continue
                pool_vals += [x for v in vals for x in leaves(v)]
                if n_entries is not None:
                    pool_vals.append(int(n_entries))
                if n_entries is not None and any(not isinstance(v, (list, dict)) or len(v) != int(n_entries) for v in vals):
                    problems.append(f"{full}: not {n_entries} entries ({[len(v) if isinstance(v, (list, dict)) else v for v in vals]})")
                if value is not None:
                    claim = parse_value(value)
                    for v in vals:
                        ok, why = value_matches(dict(claim) if isinstance(claim, dict) else claim, v)
                        if not ok:
                            problems.append(f"{full} = {value.strip()}: {why}")
        # the row's numbers and quotes against everything it cites
        pool = " ".join(pool_text)
        texts = pool_text + [v for v in pool_vals if isinstance(v, str)]
        pool_nums = [float(a.replace(",", "") + (b or "")) for t in texts for a, b in POOL_NUM.findall(t)]
        pool_nums += [float(v) for v in pool_vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if pool_text:
            for q in quotes_in(number_cell):
                frags = [squash(x) for x in re.split(r"…|\.\.\.", q) if len(x.strip()) > 3]
                if any(fr not in squash(pool) for fr in frags):
                    problems.append(f"quote not on the cited line(s): \"{q[:80]}\"")
            negative = re.search(r"\b(no|not|never|without)\b", number_cell)
            for code in re.findall(r"`([^`]+)`", number_cell):
                if not negative and squash(code) not in squash(pool) and not pool_vals:
                    problems.append(f"`{code}` not on the cited line(s)")
        if not pool_text and not pool_vals:
            if not problems:
                notes.append("no machine-checkable citation in the source cell")
        fracs = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s*(?:/|of)\s*(\d+)", number_cell.replace(",", ""))]
        cell_for_numbers = re.sub(r'"[^"]*"|“[^”]*”|`[^`]*`', " ", number_cell)
        missing = [t for t in numbers_in(cell_for_numbers) if not number_found(t, pool_nums, fracs)
                   and not any(str(t) in (str(k), str(n)) for k, n in fracs if f"{k}/{n}" in pool.replace(" ", ""))]
        if problems:
            rep.add("claim", target, what, "mismatch", number_cell, None, problems + ([f"numbers not found: {missing}"] if missing else []))
        elif missing:
            rep.add("claim", target, what, "unconfirmed", number_cell, None,
                    f"numbers not found in the cited lines or keys: {missing}")
        elif notes:
            rep.add("claim", target, what, "skip", number_cell, None, notes)
        else:
            rep.add("claim", target, what, "pass", number_cell, None, claim_cell[:100])


def claim_derived(rep: Report, target: str, what: str, number_cell: str, derived: dict):
    """The one derived row so far (R09): 'after the fixes, on the same 32 attacks' recomputed from both red-team runs."""
    ba = derived.get("redteam_before_after")
    if ba is None:
        rep.add("claim", target, what, "skip", number_cell, None, "derived row: the runs it derives from are not both present")
        return
    m = re.search(r"(\d+)/(\d+)", number_cell)
    c = re.search(r"(\d+)/(\d+) blocked", number_cell)
    gaps = re.findall(r"[A-Z]{2}-\d{2}", number_cell)
    probs = []
    if not m or [int(m.group(1)), int(m.group(2))] != [ba["after_stopped"], ba["attacks"]]:
        probs.append(f"stopped {ba['after_stopped']}/{ba['attacks']}")
    if gaps and sorted(gaps) != ba["after_not_stopped"]:
        probs.append(f"not stopped {ba['after_not_stopped']}")
    if c and int(c.group(1)) != ba["after_control_blocks"]:
        probs.append(f"controls blocked {ba['after_control_blocks']}")
    rep.add("claim", target, what, "mismatch" if probs else "pass", number_cell, ba, probs or "recomputed from both runs")


# ---------------------------------------------------------------------------------------------------------- main
KINDS = (("tf_bench_", tf_bench), ("crosscheck_", crosscheck), ("redteam_", redteam), ("agreement_", agreement),
         ("capacity_", capacity), ("load_", load_test))


def verify(root: Path, sources: Path | None = None) -> dict:
    rep = Report()
    bench = root / "release/benchmarks"
    dirs = sorted(p for p in bench.iterdir() if p.is_dir()) if bench.is_dir() else []
    for d in dirs:
        for prefix, fn in KINDS:
            if d.name.startswith(prefix):
                try:
                    fn(rep, d, root)
                except Exception as exc:   # a malformed result is a finding, not a crash of the whole check
                    rep.add("recompute", rel(d, root), "results.json", "mismatch", detail=f"{type(exc).__name__}: {exc}")
                break
        else:
            rep.add("recompute", rel(d, root), "result directory", "skip", detail="no recomputation for this kind yet")
    for prefix in ("load_", "metamorphic_", "primock_gold_", "crosscheck_r2_"):
        if not any(d.name.startswith(prefix) for d in dirs):
            rep.add("recompute", f"release/benchmarks/{prefix}*", "result directory", "skip", detail="not present yet")
    derived = {}
    befores = [d for d in dirs if d.name.startswith("redteam_before_") and (d / "results.json").is_file()]
    afters = [d for d in dirs if re.fullmatch(r"redteam_\d{8}T\d{6}Z", d.name) and (d / "results.json").is_file()]
    if befores and afters:
        derived["redteam_before_after"] = redteam_before_after(rep, befores[-1], afters[-1], root)
    data = root / "handoff_day1/ui/pages/shell/data"
    for f in sorted(data.glob("*.json")) if data.is_dir() else []:
        snap = load_json(f)
        if (snap.get("frozen") or {}).get("kind") == "validation":
            scorecard(rep, f, root)
        else:
            fr = snap.get("frozen") or {}
            rep.add("recompute", rel(f, root), "scorecard snapshot", "skip",
                    detail=f"kind {fr.get('kind')!r}: its source run is recomputed under release/benchmarks/")
            src = find_file(f"{fr.get('source_dir')}/{fr.get('source_file')}", root) if fr.get("source_file") else None
            if src is not None and fr.get("source_sha256"):
                now, was = sha256(src), fr["source_sha256"]
                rep.add("hash", rel(f, root), f"frozen.source_sha256: {rel(src, root)}",
                        "pass" if now == was or documented_redaction(root, rel(src, root), was, now) else "mismatch",
                        was, now)
            elif fr.get("source_sha256"):
                rep.add("hash", rel(f, root), "frozen.source_sha256", "skip", fr["source_sha256"], None,
                        "the frozen source is not in this checkout")
    redactions(rep, root)
    sources_md(rep, sources or root / "submission/SOURCES.md", root, derived)
    counts: dict = {}
    for c in rep.checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {"schema_version": SCHEMA, "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "root": str(root), "counts": counts, "checks": rep.checks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    ap.add_argument("--sources", type=Path, default=None, help="claims table (default: submission/SOURCES.md)")
    ap.add_argument("--out", type=Path, default=None, help="write the JSON report here (parent must exist)")
    ap.add_argument("--strict", action="store_true", help="also fail on changed_since_run and unconfirmed")
    ap.add_argument("--quiet", action="store_true", help="print only the failing rows and the RESULT line")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"error: --root {root} is not a directory", file=sys.stderr)
        return 2
    report = verify(root, args.sources)
    bad = FAILING | (WARNING if args.strict else set())
    failed = [c for c in report["checks"] if c["status"] in bad]
    report["strict"] = bool(args.strict)
    report["result"] = "FAIL" if failed else "PASS"
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    for c in report["checks"]:
        if c["status"] == "pass" or (args.quiet and c["status"] not in bad):
            continue
        line = f"{c['status'].upper():18} {c['kind']:9} {c['target']} :: {c['what']}"
        extra = c["detail"] if c["detail"] is not None else (f"recorded {c['expected']!r} recomputed {c['recomputed']!r}"
                                                               if c["status"] == "mismatch" else None)
        if extra is not None:
            line += f" -- {json.dumps(extra, ensure_ascii=False)[:400]}"
        print(line.encode(enc, "replace").decode(enc, "replace"))
    print("counts: " + ", ".join(f"{k}={v}" for k, v in sorted(report["counts"].items())))
    print(f"RESULT: {report['result']}" + (f"; failing checks={len(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
