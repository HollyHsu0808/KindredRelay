#!/usr/bin/env python3
"""Fact stability of a finished handover benchmark (scripts/bench_tf_handover.py): how stable each model's accepted
facts are across repeats of the same story update, how far the models agree with each other, and whether a fact's
stability goes with agreement with the story's recorded extraction. Offline: it reads the run's records.jsonl (and
results.json when present) and the story the run used; no model is called.

A fact key is one connected group of the accepted facts of one update (over every model and repeat) under the bench's
own "agreement with the recorded extraction" heuristic, bench_tf_handover.reference_match (imported, not copied): two
facts are linked when they have the same type and one quote, after episode.norm, contains the other. The key is named
by its type and its shortest quote. A repeat's fact set is the set of keys of its accepted facts.

Measured over the (model, update) pairs whose every repeat completed: per model, the mean pairwise Jaccard of the repeat
fact sets (percentile bootstrap 95% CI over updates, the bench's resamples and seed) and the share of keys found in
all / some / one of the repeats; per update, the Jaccard of two models' majority-vote sets (keys in more than half of a
model's repeats); per (model, update, key), its repeat count and whether another model also produced it, against whether
the key matches a fact of the story's recorded extraction (Wilson 95% intervals). Grounding-check acceptance (3a) needs
the rejected proposals too, which case records keep since bench schema v2 (rejected_facts: type, quote, reason): proposal
keys are built the same way over every proposal, accepted and rejected, and their repeat count and cross-model presence
are set against whether the check accepted the key's proposals. On a v1 run (rejected facts kept only as reason strings)
results.json says it is not computable instead of giving a number.

Usage:
  python scripts/analyze_bench_agreement.py release/benchmarks/tf_bench_20261017T213905Z
  python scripts/analyze_bench_agreement.py BENCH_DIR --out release/benchmarks/agreement_<UTC>

Writes results.json and summary.md in a new folder (default release/benchmarks/agreement_<UTC>). Exit code 0, or 2 for
a usage problem (missing input, existing output folder, a story that is not the one the run used). Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_tf_handover as B  # noqa: E402  the run's heuristic, statistics helpers and record reader

SCHEMA_VERSION = "kindredrelay-bench-agreement-v2"   # v2: grounding_acceptance computed from rejected_facts
EXIT_OK, EXIT_USAGE = 0, 2
HEURISTIC_SOURCE = "scripts/bench_tf_handover.py"   # reference_match, wilson95, bootstrap_ci
NORM_SOURCE = "handoff_day1/agent/episode.py"   # norm, which reference_match applies to every quote
GROUNDING_NOT_COMPUTABLE = (
    "not computable from these records: a case record keeps its accepted facts (fact_id, type, quote) but a rejected "
    "fact only as a reason string (rejection_reasons), with no type or quote, and no model reply is stored, so a "
    "rejected fact cannot be given a key; every keyed fact here passed the grounding check by construction")
GROUNDING_PARTIAL = ("not computable from these records: {lacking} of the {n} completed case records lack "
                     "rejected_facts (written before bench schema v2), so their rejected proposals cannot be keyed")
GROUNDING_NOTE = ("a proposal is a fact the model proposed that the grounding check judged (episode.grounding_problem): "
                  "accepted_facts plus rejected_facts of the case record; facts the evidence gate withheld are in neither")
REFERENCE_NOTE = ("the reference is the story's recorded extraction (the fixture's curated facts for each update), "
                  "matched with the bench's heuristic (same type, one quote contains the other); it is not clinical "
                  "ground truth and not a quality score")


class UsageError(Exception):
    """A problem with the inputs or the command line; nothing was written."""


# ---------------------------------------------------------------------------------------------------------- keys
def node(fact: dict) -> tuple[str, str]:
    """A fact as (type, normalized quote): the unit the key groups."""
    return (fact.get("type") or "", B.norm(fact.get("quote") or ""))


def linked(a: tuple[str, str], b: tuple[str, str]) -> bool:
    """The bench's heuristic as a pairwise test: reference_match([a], [b]) is 1 when both quotes are non-empty, the types
    are equal and one normalized quote contains the other (symmetric in a and b)."""
    return B.reference_match([{"type": a[0], "quote": a[1]}], [{"type": b[0], "quote": b[1]}]) > 0


def fact_keys(facts) -> tuple[dict, list[dict]]:
    """Every distinct node of facts -> its key (type, shortest normalized quote of its group, ties by text). Groups are
    the connected components of `linked` (union-find), so the result does not depend on the order of facts. Also one row
    per key: its member nodes and whether it is bridged (two members not linked directly, joined through a third)."""
    nodes = sorted({node(f) for f in facts})
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in itertools.combinations(range(len(nodes)), 2):
        if linked(nodes[i], nodes[j]):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)
    groups: dict[int, list] = {}
    for i, n in enumerate(nodes):
        groups.setdefault(find(i), []).append(n)
    keymap, rows = {}, []
    for members in groups.values():   # one type per group: linked needs equal types
        key = (members[0][0], min((q for _, q in members), key=lambda q: (len(q), q)))
        for n in members:
            keymap[n] = key
        rows.append({"key": key, "members": sorted(members),
                     "bridged": any(not linked(a, b) for a, b in itertools.combinations(members, 2))})
    rows.sort(key=lambda r: r["key"])
    return keymap, rows


# ---------------------------------------------------------------------------------------------------------- set statistics
def jaccard(a: set, b: set) -> float:
    """|a & b| / |a | b|; 1.0 for two empty sets (they agree)."""
    return len(a & b) / len(a | b) if a or b else 1.0


def mean_pairwise_jaccard(sets: list[set]):
    """Mean Jaccard over every pair of sets; None for fewer than two."""
    pairs = list(itertools.combinations(sets, 2))
    return sum(jaccard(a, b) for a, b in pairs) / len(pairs) if pairs else None


def repeat_counts(sets: list[set]) -> dict:
    """Key -> in how many of the sets it is."""
    counts: dict = {}
    for s in sets:
        for k in s:
            counts[k] = counts.get(k, 0) + 1
    return counts


def majority(sets: list[set]) -> set:
    """The keys in more than half of the sets (2 of 3 repeats)."""
    return {k for k, c in repeat_counts(sets).items() if 2 * c > len(sets)}


def rate_row(units: list[dict], field: str = "reference_match", label: str = "reference_matched") -> dict:
    """Share of units whose `field` is true (by default: the key matches the recorded extraction), with its Wilson 95%
    interval (None for no unit)."""
    k = sum(1 for u in units if u[field])
    return {"n": len(units), label: k, "rate": B.rnd(k / len(units)) if units else None,
            "wilson95": B.wilson95(k, len(units))}


def bucket_rates(units: list[dict], repeats: int, field: str = "reference_match", label: str = "reference_matched") -> dict:
    """Reference agreement (or `field`) by repeat count (repeats .. 1, and 1 .. repeats-1 together), by whether another
    model also produced the key (units without a comparable other model are left out of those rows), and by both."""
    counts = range(repeats, 0, -1)
    cross = [u for u in units if u["other_model_present"] is not None]

    def row(us):
        return rate_row(us, field, label)
    out = {"by_repeat_count": {str(c): row([u for u in units if u["repeat_count"] == c]) for c in counts}}
    if repeats > 2:
        out["by_repeat_count"][f"1-{repeats - 1}"] = row([u for u in units if u["repeat_count"] < repeats])
    out["by_other_model"] = {"present": row([u for u in cross if u["other_model_present"]]),
                             "absent": row([u for u in cross if not u["other_model_present"]])}
    out["by_repeat_count_and_other_model"] = {
        f"{c}|{p}": row([u for u in cross if u["repeat_count"] == c and u["other_model_present"] == (p == "present")])
        for c in counts for p in ("present", "absent")}
    return out


# ---------------------------------------------------------------------------------------------------------- grounding (3a)
def proposals(c: dict) -> list[dict]:
    """The proposals of one case record the grounding check judged: its accepted facts and its rejected facts."""
    return ([{"type": f.get("type"), "quote": f.get("quote"), "accepted": True, "reason": None}
             for f in c.get("accepted_facts") or []]
            + [{"type": f.get("type"), "quote": f.get("quote"), "accepted": False, "reason": f.get("reason")}
               for f in c.get("rejected_facts") or []])


def grounding_acceptance(ok: dict, models: list[str], update_ids: list[str], repeats: int, used: set) -> dict:
    """3(a): per (model, update, proposal key) of the used pairs, the key's repeat count and cross-model presence among
    the model's proposals against whether the grounding check accepted every one of its proposals; also per proposal.
    Not computable when a completed case record has no rejected_facts (a run before bench schema v2)."""
    lacking = sum(1 for c in ok.values() if not isinstance(c.get("rejected_facts"), list))
    if not ok or lacking == len(ok):
        return {"computable": False, "reason": GROUNDING_NOT_COMPUTABLE}
    if lacking:
        return {"computable": False, "reason": GROUNDING_PARTIAL.format(lacking=lacking, n=len(ok))}
    keyof = {u: fact_keys(p for (_, uu, _), c in ok.items() if uu == u for p in proposals(c))[0] for u in update_ids}
    psets, members, withheld = {}, {}, 0
    for m in models:
        for u in update_ids:
            if (m, u) not in used:
                continue
            per = []
            for r in sorted(r for (mm, uu, r) in ok if mm == m and uu == u):
                c = ok[(m, u, r)]
                withheld += c.get("facts_withheld") or 0
                ps = proposals(c)
                ks = [keyof[u][node(p)] for p in ps]
                per.append(set(ks))
                for p, k in zip(ps, ks):
                    members.setdefault((m, u), {}).setdefault(k, []).append(p)
            psets[(m, u)] = per
    units = []
    for m in models:
        for u in update_ids:
            if (m, u) not in psets:
                continue
            counts = repeat_counts(psets[(m, u)])
            others = [o for o in models if o != m and (o, u) in psets]
            for k in sorted(counts):
                ps = members[(m, u)][k]
                units.append({"model": m, "update_id": u, "type": k[0], "quote": k[1], "repeat_count": counts[k],
                              "other_model_present": any(k in s for o in others for s in psets[(o, u)]) if others else None,
                              "grounding_accepted": all(p["accepted"] for p in ps), "proposals": len(ps),
                              "proposals_accepted": sum(p["accepted"] for p in ps),
                              "rejection_reasons": sorted({p["reason"] for p in ps if not p["accepted"] and p["reason"]})})
    per_proposal = [{**x, "accepted": i < x["proposals_accepted"]} for x in units for i in range(x["proposals"])]
    allp = [p for byk in members.values() for ps in byk.values() for p in ps]
    reasons: dict[str, int] = {}
    for p in allp:
        if not p["accepted"]:
            reasons[str(p["reason"])] = reasons.get(str(p["reason"]), 0) + 1
    return {"computable": True, "note": GROUNDING_NOTE,
            "keys": {"pooled": bucket_rates(units, repeats, "grounding_accepted", "accepted"),
                     "per_model": {m: bucket_rates([x for x in units if x["model"] == m], repeats, "grounding_accepted",
                                                   "accepted") for m in models}},
            "proposals": {"pooled": bucket_rates(per_proposal, repeats, "accepted", "accepted"),
                          "per_model": {m: bucket_rates([x for x in per_proposal if x["model"] == m], repeats, "accepted",
                                                        "accepted") for m in models}},
            "diagnostics": {"proposals": len(allp), "accepted": sum(p["accepted"] for p in allp),
                            "rejected": sum(not p["accepted"] for p in allp),
                            "withheld_by_gate_not_included": withheld, "keys": len(units),
                            "keys_with_accepted_and_rejected_proposals": sum(
                                0 < x["proposals_accepted"] < x["proposals"] for x in units),
                            "rejected_without_text_quote": sum(1 for p in allp if not p["accepted"]
                                                               and not (isinstance(p["quote"], str) and p["quote"].strip())),
                            "rejection_reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))},
            "units": units}


# ---------------------------------------------------------------------------------------------------------- analysis
def analyze(cases: list[dict], references: dict, models: list[str], update_ids: list[str], repeats: int) -> dict:
    """The whole analysis from the run's case records and the story's recorded extraction per update id. Only completed
    (status ok) cases count; a (model, update) pair is used when all `repeats` of it completed."""
    ok: dict = {}
    for c in cases:
        if c.get("type") != "case" or c.get("status") != "ok":
            continue
        k = (c["model"], c["update_id"], c["repeat"])
        if k in ok:
            raise UsageError(f"two completed case records for {k}")
        ok[k] = c
    keyof, keyrows = {}, {}
    for u in update_ids:
        keyof[u], keyrows[u] = fact_keys(f for (_, uu, _), c in ok.items() if uu == u for f in c.get("accepted_facts") or [])

    sets, members, incomplete, collapsed = {}, {}, [], 0
    for m in models:
        for u in update_ids:
            reps = sorted(r for (mm, uu, r) in ok if mm == m and uu == u)
            if len(reps) != repeats:
                incomplete.append({"model": m, "update_id": u, "completed_repeats": len(reps)})
                continue
            per = []
            for r in reps:
                facts = ok[(m, u, r)].get("accepted_facts") or []
                ks = [keyof[u][node(f)] for f in facts]
                collapsed += len(ks) - len(set(ks))
                per.append(set(ks))
                for f, k in zip(facts, ks):
                    members.setdefault((m, u), {}).setdefault(k, []).append(f)
            sets[(m, u)] = per

    within = {}
    for m in models:
        rows = {}
        for u in update_ids:
            if (m, u) not in sets:
                continue
            per = sets[(m, u)]
            counts = repeat_counts(per)
            rows[u] = {"keys_per_repeat": [len(s) for s in per], "keys": len(counts),
                       "mean_pairwise_jaccard": B.rnd(mean_pairwise_jaccard(per)),
                       "keys_by_repeat_count": {str(c): sum(v == c for v in counts.values()) for c in range(repeats, 0, -1)},
                       "majority_keys": len(majority(per)),
                       "empty_repeat_pairs": sum(1 for a, b in itertools.combinations(per, 2) if not a and not b)}
        vals = [mean_pairwise_jaccard(sets[(m, u)]) for u in rows]
        dist = {str(c): sum(rows[u]["keys_by_repeat_count"][str(c)] for u in rows) for c in range(repeats, 0, -1)}
        total = sum(dist.values())
        within[m] = {"n_updates": len(rows), "mean_pairwise_jaccard": B.rnd(B.mean(vals)),
                     "ci95": B.bootstrap_ci(vals, B.mean, key=f"within_jaccard:{m}"),
                     "min": B.rnd(min(vals)) if vals else None, "max": B.rnd(max(vals)) if vals else None,
                     "keys": total, "keys_by_repeat_count": dist,
                     "share_by_repeat_count": {c: B.rnd(v / total) if total else None for c, v in dist.items()},
                     "per_update": rows}

    cross = {}
    for a, b in itertools.combinations(models, 2):
        rows = {}
        for u in update_ids:
            if (a, u) in sets and (b, u) in sets:
                ma, mb = majority(sets[(a, u)]), majority(sets[(b, u)])
                rows[u] = {"majority_keys": {a: len(ma), b: len(mb)}, "shared": len(ma & mb),
                           "jaccard": B.rnd(jaccard(ma, mb)), "both_empty": not ma and not mb}
        vals = [jaccard(majority(sets[(a, u)]), majority(sets[(b, u)])) for u in rows]
        cross[f"{a} vs {b}"] = {"models": [a, b], "n_updates": len(rows), "mean_jaccard": B.rnd(B.mean(vals)),
                                "ci95": B.bootstrap_ci(vals, B.mean, key=f"cross_jaccard:{a}|{b}"),
                                "min": B.rnd(min(vals)) if vals else None, "max": B.rnd(max(vals)) if vals else None,
                                "per_update": rows}

    units = []
    for m in models:
        for u in update_ids:
            if (m, u) not in sets:
                continue
            counts = repeat_counts(sets[(m, u)])
            others = [o for o in models if o != m and (o, u) in sets]
            ref = references.get(u) or []
            for k in sorted(counts):
                units.append({"model": m, "update_id": u, "type": k[0], "quote": k[1], "repeat_count": counts[k],
                              "other_model_present": any(k in s for o in others for s in sets[(o, u)]) if others else None,
                              "reference_match": any(B.reference_match([f], ref) > 0 for f in members[(m, u)][k])})

    signal = {"grounding_acceptance": grounding_acceptance(ok, models, update_ids, repeats, set(sets)),
              "reference_agreement": {"note": REFERENCE_NOTE, "pooled": bucket_rates(units, repeats),
                                      "per_model": {m: bucket_rates([x for x in units if x["model"] == m], repeats)
                                                    for m in models}}}
    merged = [{"update_id": u, "type": r["key"][0], "key_quote": r["key"][1], "bridged": r["bridged"],
               "member_quotes": [q for _, q in r["members"]]}
              for u in update_ids for r in keyrows[u] if len(r["members"]) > 1]
    diagnostics = {"completed_cases_used": len(ok), "incomplete_model_update_pairs": incomplete,
                   "keys_per_update": {u: len(keyrows[u]) for u in update_ids},
                   "keys_merging_several_quotes": len(merged), "bridged_keys": sum(r["bridged"] for r in merged),
                   "facts_collapsed_within_a_repeat": collapsed, "merged_keys": merged}
    return {"within_model": within, "cross_model": cross, "confidence_signal": signal, "units": units,
            "diagnostics": diagnostics}


# ---------------------------------------------------------------------------------------------------------- inputs
def load_inputs(bench: Path) -> dict:
    """records.jsonl, the run's configuration and the story it used (refused when its sha256 is not the run's)."""
    rec_path = bench / "records.jsonl"
    if not rec_path.is_file():
        raise UsageError(f"{rec_path} not found")
    skipped: list[int] = []
    recs = B.read_records(rec_path, skipped)
    start = next((r for r in recs if r.get("type") == "run_start"), None)
    if start is None:
        raise UsageError("records.jsonl has no run_start record")
    cfg = start.get("config") or {}
    for k in ("story", "story_sha256", "models", "case_ids", "repeats"):
        if k not in cfg:
            raise UsageError(f"the run_start record's config lacks {k}")
    story_path = ROOT / cfg["story"]
    story_sha = B.file_sha(story_path)
    if story_sha is None:
        raise UsageError(f"the run's story {cfg['story']} cannot be read")
    if story_sha != cfg["story_sha256"]:
        raise UsageError(f"{cfg['story']} is not the story the run used (sha256 {story_sha[:12]} != "
                         f"{cfg['story_sha256'][:12]}): its recorded extraction would not be the run's reference")
    story = B.load_scenario(story_path)
    refs = {u["update_id"]: u.get("recorded_extraction") or [] for u in story.get("updates") or []}
    update_ids = [cid.rsplit("/", 1)[-1] for cid in cfg["case_ids"]]
    missing = [u for u in update_ids if u not in refs]
    if missing:
        raise UsageError(f"the story has no update {', '.join(missing)}")
    run_sources = [r.get("source_sha256") or {} for r in recs if r.get("type") == "invocation"]

    def source(relpath):
        sha = B.file_sha(ROOT / relpath)
        seen = [s[relpath] for s in run_sources if relpath in s]
        return {"path": relpath, "sha256": sha, "matches_run": all(s == sha for s in seen) if seen else None}

    res_path = bench / "results.json"
    return {"records": recs, "config": cfg, "references": refs, "update_ids": update_ids, "skipped": skipped,
            "inputs": {"bench_dir": B.rel(bench),
                       "records_jsonl": {"path": B.rel(rec_path), "sha256": B.file_sha(rec_path),
                                         "lines_skipped": skipped},
                       "results_json": ({"path": B.rel(res_path), "sha256": B.file_sha(res_path)}
                                        if res_path.is_file() else None),
                       "story": {"path": B.rel(story_path), "sha256": story_sha, "matches_run": True},
                       "heuristic_source": source(HEURISTIC_SOURCE), "norm_source": source(NORM_SOURCE)}}


DEFINITIONS = {
    "fact_key": "per update, over every model's and repeat's accepted facts: the connected components of the bench's "
                "agreement heuristic (scripts/bench_tf_handover.py reference_match: same type, and one quote contains "
                "the other after episode.norm); a key is named by its type and its shortest normalized quote; a "
                "repeat's fact set is the set of keys of its accepted facts (two facts of one repeat in one key count once)",
    "used_pairs": "a (model, update) pair is used when every repeat of it completed (status ok)",
    "within_model_jaccard": "per (model, update): the mean Jaccard over the 3 pairs of repeat fact sets; per model: the "
                            "mean over updates; Jaccard of two empty sets is 1",
    "repeat_count": "in how many of a model's repeats of an update the key was accepted (1..repeats)",
    "majority_vote_set": "the keys a model accepted in more than half of its repeats of an update (2 of 3)",
    "cross_model_jaccard": "per update: Jaccard of the two models' majority-vote sets; mean over updates",
    "other_model_present": "the other model accepted the same key in at least one of its repeats of the update",
    "reference_match": "at least one of this model's accepted facts in the key has the type of a fact of the story's "
                       "recorded extraction for that update and one quote contains the other (reference_match); "
                       + REFERENCE_NOTE,
    "unit_of_the_rates": "one (model, update, key); 'pooled' adds both models' units",
    "proposal_key": "3(a) only: as fact_key, but over every proposal of the update (accepted_facts and rejected_facts "
                    "of the completed case records); a proposal without a text quote or type keys by what it has, so "
                    "such proposals of one type share a key; sections 1, 2 and 3(b) keep the accepted-fact keys",
    "grounding_repeat_count": "3(a): in how many of a model's repeats of an update the proposal key was proposed "
                              "(accepted or rejected)",
    "grounding_other_model_present": "3(a): the other model proposed the same proposal key in at least one of its "
                                     "repeats of the update",
    "grounding_accepted": "3(a), unit (model, update, proposal key): every one of this model's proposals in the key "
                          "passed the grounding check (episode.grounding_problem); the proposal rows count each proposal "
                          "instead (accepted proposals / proposals)",
    "bootstrap": f"percentile 2.5 / 97.5 of the mean over {B.BOOTSTRAP_RESAMPLES} resamples of the updates with "
                 f"replacement, seed {B.BOOTSTRAP_SEED} with a per-statistic key (bench_tf_handover.bootstrap_ci), "
                 f"no interval below n = {B.BOOTSTRAP_MIN_N}",
    "wilson95": "Wilson score interval, z = 1.959964 (bench_tf_handover.wilson95)",
}


# ---------------------------------------------------------------------------------------------------------- output
def fmt(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def ci_s(ci, nd=2):
    return "[n/a]" if not ci else f"[{ci[0]:.{nd}f}, {ci[1]:.{nd}f}]"


def rate_s(r, label="reference_matched"):
    return f"{r[label]}/{r['n']} ({pct(r['rate'])}) {ci_s(r['wilson95'])}" if r["n"] else "0/0 (n/a)"


def overlap(a, b):
    """Whether two intervals overlap; None when either is missing."""
    if not a or not b:
        return None
    return a[0] <= b[1] and b[0] <= a[1]


def takeaway(n: dict, models: list[str], repeats: int) -> str:
    w = n["within_model"]
    parts = [f"`{m}` {fmt(w[m]['mean_pairwise_jaccard'])} {ci_s(w[m]['ci95'])}" for m in models]
    shares = " and ".join(f"{pct(w[m]['share_by_repeat_count'][str(repeats)])}" for m in models)
    s1 = (f"Across {repeats} repeats of the same update, the accepted facts were reproduced with a mean pairwise "
          f"Jaccard of {' and '.join(parts)} (95% bootstrap CI over updates), and {shares} of the respective fact keys "
          f"appeared in all {repeats} repeats.")
    pair = next(iter(n["cross_model"].values()), None)
    s2 = (f"The two models' majority-vote fact sets agreed with a mean Jaccard of {fmt(pair['mean_jaccard'])} "
          f"{ci_s(pair['ci95'])} over {pair['n_updates']} updates (per update {fmt(pair['min'])} to {fmt(pair['max'])})."
          if pair else "There is no second model to compare with.")
    p = n["confidence_signal"]["reference_agreement"]["pooled"]
    all_r, few_r = p["by_repeat_count"][str(repeats)], p["by_repeat_count"].get(f"1-{repeats - 1}")
    pres, abse = p["by_other_model"]["present"], p["by_other_model"]["absent"]

    few = few_r if few_r is not None else p["by_repeat_count"]["1"]
    splits = [overlap(all_r["wilson95"], few["wilson95"]), overlap(pres["wilson95"], abse["wilson95"])]
    lead = ("On this run, stability went with agreement with the story's recorded extraction (both splits' Wilson 95% "
            "intervals are apart)" if splits == [False, False] else
            "On this run, stability did not clearly separate agreement with the story's recorded extraction (at least "
            "one split's Wilson 95% intervals overlap or a bucket is empty)")
    g = n["confidence_signal"]["grounding_acceptance"]
    tail = ("." if g["computable"] else
            ", and grounding-check acceptance could not be tested because the records keep no rejected facts."
            if g["reason"] == GROUNDING_NOT_COMPUTABLE else
            ", and grounding-check acceptance could not be tested because some records keep no rejected facts.")
    s3 = (f"{lead}: keys seen in all {repeats} repeats matched it {pct(all_r['rate'])} of the time "
          f"({all_r['reference_matched']}/{all_r['n']}) against {pct(few['rate'])} ({few['reference_matched']}/"
          f"{few['n']}) for keys seen in fewer, and keys both models produced {pct(pres['rate'])} "
          f"({pres['reference_matched']}/{pres['n']}) against {pct(abse['rate'])} ({abse['reference_matched']}/"
          f"{abse['n']}) for keys only one model produced; but the less stable buckets are small, the "
          f"{len(n['within_model'][models[0]]['per_update'])} updates come from one fictional story, the reference is a "
          f"curated fixture rather than clinical ground truth" + tail)
    if not g["computable"]:
        return " ".join([s1, s2, s3])
    d, gk = g["diagnostics"], g["keys"]["pooled"]
    if not d["rejected"]:
        s4 = (f"The grounding check rejected none of the {d['proposals']} proposals, so on this run its acceptance "
              f"cannot separate stable from unstable proposal keys.")
        return " ".join([s1, s2, s3, s4])
    ga = gk["by_repeat_count"][str(repeats)]
    gf = gk["by_repeat_count"].get(f"1-{repeats - 1}") or gk["by_repeat_count"]["1"]
    gp, gab = gk["by_other_model"]["present"], gk["by_other_model"]["absent"]
    gsplits = [overlap(ga["wilson95"], gf["wilson95"]), overlap(gp["wilson95"], gab["wilson95"])]
    glead = ("stability went with passing it (both splits' Wilson 95% intervals are apart)" if gsplits == [False, False]
             else "stability did not clearly separate passing it (at least one split's Wilson 95% intervals overlap or a "
                  "bucket is empty)")
    s4 = (f"The grounding check rejected {d['rejected']} of the {d['proposals']} proposals; by proposal key, {glead}: "
          f"keys proposed in all {repeats} repeats had every proposal accepted {pct(ga['rate'])} of the time "
          f"({ga['accepted']}/{ga['n']}) against {pct(gf['rate'])} ({gf['accepted']}/{gf['n']}) for keys proposed in "
          f"fewer, and keys both models proposed {pct(gp['rate'])} ({gp['accepted']}/{gp['n']}) against "
          f"{pct(gab['rate'])} ({gab['accepted']}/{gab['n']}) for keys only one model proposed.")
    return " ".join([s1, s2, s3, s4])


def summary_md(res: dict) -> str:
    n, run, inp = res["numbers"], res["run"], res["inputs"]
    models, repeats, ups = run["models"], run["repeats"], run["update_ids"]
    counts = [str(c) for c in range(repeats, 0, -1)]
    L = [f"# Fact stability across repeats: {', '.join(f'`{m}`' for m in models)}", "",
         f"- Bench run: `{inp['bench_dir']}` (records.jsonl sha256 `{inp['records_jsonl']['sha256'][:16]}`; results.json "
         + (f"sha256 `{inp['results_json']['sha256'][:16]}`" if inp["results_json"] else "absent") + f"); story "
         f"`{inp['story']['path']}` (sha256 `{inp['story']['sha256'][:16]}`, the run's); {len(ups)} updates x "
         f"{repeats} repeats x {len(models)} models, {n['diagnostics']['completed_cases_used']} completed cases used.",
         f"- Fact key: {res['definitions']['fact_key']}. The heuristic is imported from `{HEURISTIC_SOURCE}` "
         f"(sha256 {'matches' if inp['heuristic_source']['matches_run'] else 'DOES NOT match' if inp['heuristic_source']['matches_run'] is False else 'not recorded for'} the run's).",
         f"- Keys: {sum(n['diagnostics']['keys_per_update'].values())} over the {len(ups)} updates; "
         f"{n['diagnostics']['keys_merging_several_quotes']} group several distinct quotes "
         f"({n['diagnostics']['bridged_keys']} bridged through a third quote); "
         f"{n['diagnostics']['facts_collapsed_within_a_repeat']} accepted fact(s) shared a key with another fact of the "
         f"same repeat. All are listed in results.json (`diagnostics.merged_keys`).", "",
         "## 1. Within-model repeat agreement", "",
         "| Model | updates | mean pairwise Jaccard [95% CI] | per-update min / max | keys | "
         + " | ".join(f"in {c}/{repeats}" for c in counts) + " |",
         "|---|---|---|---|---|" + "---|" * len(counts)]
    for m in models:
        w = n["within_model"][m]
        L.append(f"| `{m}` | {w['n_updates']} | {fmt(w['mean_pairwise_jaccard'])} {ci_s(w['ci95'])} | "
                 f"{fmt(w['min'])} / {fmt(w['max'])} | {w['keys']} | "
                 + " | ".join(f"{w['keys_by_repeat_count'][c]} ({pct(w['share_by_repeat_count'][c])})" for c in counts)
                 + " |")
    L += ["", "## 2. Per update and cross-model agreement", ""]
    pairs = list(n["cross_model"].items())
    head = (["Update"] + [f"`{m}` Jaccard" for m in models] + [f"`{m}` keys {'/'.join(counts)}" for m in models]
            + [f"majority-vote Jaccard, {name}" for name, _ in pairs])
    L += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for u in ups:
        row = [u]
        for m in models:
            pu = n["within_model"][m]["per_update"].get(u)
            row.append(fmt(pu["mean_pairwise_jaccard"]) if pu else "n/a")
        for m in models:
            pu = n["within_model"][m]["per_update"].get(u)
            row.append("/".join(str(pu["keys_by_repeat_count"][c]) for c in counts) if pu else "n/a")
        for _, c in pairs:
            pu = c["per_update"].get(u)
            row.append(f"{fmt(pu['jaccard'])} ({pu['shared']} shared of "
                       + " / ".join(str(v) for v in pu["majority_keys"].values()) + ")" if pu else "n/a")
        L.append("| " + " | ".join(row) + " |")
    L.append("")
    for name, c in pairs:
        L.append(f"- {name}: mean majority-vote Jaccard {fmt(c['mean_jaccard'])} {ci_s(c['ci95'])} (95% bootstrap CI "
                 f"over {c['n_updates']} updates), per update {fmt(c['min'])} to {fmt(c['max'])}.")
    sig = n["confidence_signal"]
    ra = sig["reference_agreement"]
    labels = [(f"in {c}/{repeats} repeats", "by_repeat_count", c) for c in counts]
    if repeats > 2:
        labels.append((f"in 1-{repeats - 1} of {repeats} repeats", "by_repeat_count", f"1-{repeats - 1}"))
    glabels = labels + [("other model also proposed it", "by_other_model", "present"),
                        ("only this model proposed it", "by_other_model", "absent")]
    labels += [("other model also produced it", "by_other_model", "present"),
               ("only this model produced it", "by_other_model", "absent")]
    L += ["", "## 3. Is stability a usable confidence signal?", ""]
    g = sig["grounding_acceptance"]
    if not g["computable"]:
        L += [f"(a) Grounding-check acceptance: {g['reason']}.", ""]
    else:
        d = g["diagnostics"]
        L += ["(a) Grounding-check acceptance, one row per bucket of (model, update, proposal key) units: a unit counts "
              "as accepted when every one of the model's proposals in the key passed the grounding check; accepted / n "
              "(rate) [Wilson 95%]. Proposal keys are built like the fact keys but over accepted and rejected proposals "
              f"together ({GROUNDING_NOTE}); the repeat count and the other model refer to proposals. The last column "
              "counts proposals instead of keys.", "",
              "| Bucket | pooled keys | " + " | ".join(f"`{m}` keys" for m in models) + " | pooled proposals |",
              "|---|---|" + "---|" * len(models) + "---|"]
        for label, group, k in glabels:
            L.append(f"| {label} | {rate_s(g['keys']['pooled'][group][k], 'accepted')} | "
                     + " | ".join(rate_s(g["keys"]["per_model"][m][group][k], "accepted") for m in models)
                     + f" | {rate_s(g['proposals']['pooled'][group][k], 'accepted')} |")
        L += ["", "Pooled keys, by repeat count and the other model:", "",
              "| Repeat count | other model also proposed it | only this model |", "|---|---|---|"]
        for c in counts:
            t = g["keys"]["pooled"]["by_repeat_count_and_other_model"]
            L.append(f"| {c}/{repeats} | {rate_s(t[f'{c}|present'], 'accepted')} | {rate_s(t[f'{c}|absent'], 'accepted')} |")
        reasons = "; ".join(f"{v} x {k}" for k, v in list(d["rejection_reasons"].items())[:6]) or "none"
        L += ["", f"Proposals in the used pairs: {d['proposals']} ({d['accepted']} accepted, {d['rejected']} rejected by "
              f"the grounding check; {d['withheld_by_gate_not_included']} withheld by the evidence gate, not included); "
              f"{d['keys']} (model, update, proposal key) units, {d['keys_with_accepted_and_rejected_proposals']} with both "
              f"accepted and rejected proposals; {d['rejected_without_text_quote']} rejected proposal(s) without a text "
              f"quote. Rejection reasons: {reasons}.", ""]
    L += ["(b) Agreement with the story's recorded extraction, one row per bucket of (model, update, key) units: matched "
          "/ n (rate) [Wilson 95%]. " + REFERENCE_NOTE[0].upper() + REFERENCE_NOTE[1:] + ".", "",
          "| Bucket | pooled | " + " | ".join(f"`{m}`" for m in models) + " |",
          "|---|---|" + "---|" * len(models)]
    for label, group, k in labels:
        L.append(f"| {label} | {rate_s(ra['pooled'][group][k])} | "
                 + " | ".join(rate_s(ra["per_model"][m][group][k]) for m in models) + " |")
    L += ["", "Pooled, by repeat count and the other model:", "",
          "| Repeat count | other model also produced it | only this model |", "|---|---|---|"]
    for c in counts:
        t = ra["pooled"]["by_repeat_count_and_other_model"]
        L.append(f"| {c}/{repeats} | {rate_s(t[f'{c}|present'])} | {rate_s(t[f'{c}|absent'])} |")
    L += ["", "## Takeaway", "", takeaway(n, models, repeats), "", "## Caveats", ""]
    L += [f"- {c}" for c in res["caveats"]]
    return "\n".join(L) + "\n"


def grounding_caveat(g: dict) -> str:
    if not g["computable"]:
        return ("Grounding-check acceptance could not be related to stability: the records keep rejected facts only as "
                "reason strings (no type, no quote, no stored reply). Every key is an accepted fact."
                if g["reason"] == GROUNDING_NOT_COMPUTABLE else
                f"Grounding-check acceptance could not be related to stability: {g['reason']}.")
    w = g["diagnostics"]["withheld_by_gate_not_included"]
    return ("Grounding-check acceptance (3a) uses proposal keys, built like the fact keys over accepted and rejected "
            "proposals together, so they can differ from the accepted-fact keys of sections 1, 2 and 3(b) (a rejected "
            "proposal can join two accepted keys or stand alone). The check is deterministic: a proposal repeated word for "
            "word gets the same verdict, so a key's repeat count measures how often the model re-proposed it, not "
            "independent re-checks. A key counts as accepted only when all of the model's proposals in it passed, so a key "
            "proposed in more repeats has more chances to fail; the proposal column counts each proposal, which treats "
            "repeats of one proposal as independent and is more optimistic still."
            + (f" {w} fact(s) withheld by the evidence gate are left out." if w else ""))


def caveats(n: dict, run: dict) -> list[str]:
    d = n["diagnostics"]
    return [
        "The reference is the story's recorded extraction (the demo fixture's curated facts), matched by the bench's "
        "heuristic (same type, one quote contains the other). It is not clinical ground truth and not a quality score: "
        "a correct fact the fixture does not list, or one the model typed differently, counts as unmatched.",
        f"n is small: {len(run['update_ids'])} updates of one fictional story, {run['repeats']} repeats, "
        f"{len(run['models'])} models. The bootstrap resamples updates; the Wilson intervals treat each (model, update, "
        "key) as independent, which keys of one update or of both models are not, so the intervals are optimistic.",
        grounding_caveat(n["confidence_signal"]["grounding_acceptance"]),
        f"Keys come from quote containment, chained through a group: {d['keys_merging_several_quotes']} key(s) group "
        f"several distinct quotes and {d['bridged_keys']} are bridged (two quotes joined only through a third, e.g. two "
        "half-sentence facts and one whole-sentence fact). A model that splits a sentence into two facts in one repeat "
        "and quotes it whole in another counts as stable; facts of different types never share a key.",
        "A key's reference match counts any of the model's member quotes, so a key seen in more repeats has slightly "
        "more chances to match.",
        "The other-model split and the reference match use the same test (same type, one quote contains the other), so "
        "a fact given an unusual type fails both: part of that split measures agreement on the type label, not only on "
        "the content.",
        "Repeat variation is what the endpoint returned under the bench's settings (see its results.json); the "
        "analysis does not know the sampling parameters.",
    ]


def write_outputs(out: Path, res: dict):
    out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(summary_md(res), encoding="utf-8")


def build(bench: Path) -> dict:
    inp = load_inputs(bench)
    cfg = inp["config"]
    numbers = analyze([r for r in inp["records"] if r.get("type") == "case"], inp["references"], list(cfg["models"]),
                      inp["update_ids"], int(cfg["repeats"]))
    run = {"bench_schema_version": next((r.get("schema_version") for r in inp["records"] if r.get("type") == "run_start"),
                                        None),
           "models": list(cfg["models"]), "case_ids": list(cfg["case_ids"]), "update_ids": inp["update_ids"],
           "repeats": int(cfg["repeats"]), "dry_run": cfg.get("dry_run")}
    return {"schema_version": SCHEMA_VERSION, "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "inputs": inp["inputs"], "run": run, "definitions": DEFINITIONS, "numbers": numbers,
            "caveats": caveats(numbers, run)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bench_dir", help="a finished bench_tf_handover.py output folder (records.jsonl)")
    ap.add_argument("--out", default=None, help="new output folder (must not exist); default "
                                                "release/benchmarks/agreement_<UTC>")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else ROOT / "release" / "benchmarks" / (
        f"agreement_{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}")
    try:
        if out.exists():
            raise UsageError(f"{out} exists: give a new --out folder")
        res = build(Path(a.bench_dir))
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    write_outputs(out, res)
    for w in ("heuristic_source", "norm_source"):
        if res["inputs"][w]["matches_run"] is False:
            print(f"warning: {res['inputs'][w]['path']} changed since the run", file=sys.stderr)
    n = res["numbers"]
    for m, w in n["within_model"].items():
        print(f"{m}: within-model mean pairwise Jaccard {fmt(w['mean_pairwise_jaccard'])} {ci_s(w['ci95'])}, "
              f"keys {w['keys']} by repeat count {w['keys_by_repeat_count']}")
    for name, c in n["cross_model"].items():
        print(f"{name}: majority-vote Jaccard {fmt(c['mean_jaccard'])} {ci_s(c['ci95'])}")
    g = n["confidence_signal"]["grounding_acceptance"]
    if g["computable"]:
        d = g["diagnostics"]
        print(f"grounding check (3a): {d['rejected']} of {d['proposals']} proposals rejected, {d['keys']} proposal-key units")
    else:
        print("grounding check (3a): not computable from these records")
    print(f"wrote {out / 'results.json'} and {out / 'summary.md'}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
