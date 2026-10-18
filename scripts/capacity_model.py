#!/usr/bin/env python3
"""Capacity and token model of KindredRelay's caregiver-update path: what one family, one care coordinator's caseload
and 1,000 families would need from the inference endpoint, from measured per-handover numbers and labelled assumptions.
Offline: it reads finished benchmark results and calls no model.

Measured inputs (read from the files, never copied by hand; every number keeps its source path and JSON key):
  release/benchmarks/tf_bench_*/results.json    scripts/bench_tf_handover.py, the newest live run (dry_run false) that
                                                has the model: tokens per handover (the endpoint's usage), end-to-end
                                                latency per handover (successful cases, retries and waits included)
  release/benchmarks/load_*/results.json        optional concurrency load test, the newest live one: measured throughput
                                                (completed handovers per second over all streams) at its concurrency,
                                                read at --load-throughput-key / --load-concurrency-key; without one (or
                                                without those keys) the model is sequential only and says so
  release/benchmarks/crosscheck_*/results.json  optional, scripts/crosscheck_judge.py eval, the newest live one: judge
                                                tokens per check (tokens_per_check.mean) and judge call latency
                                                (latency_s.p50; the file has no mean), used only when every update is
                                                assumed to be cross-checked
Assumptions (defaults below, overridable by --config JSON and by flags; each one is labelled in the output):
  updates_per_family_per_day, families_per_care_coordinator, crosscheck_every_update, price_per_million_tokens (null:
  tokens only, no cost; no price is invented). A month is 30 days (a unit convention, not varied).
Outputs: tokens per family per day and per month; handovers per hour of one sequential stream (and per endpoint-hour at
the load test's concurrency when measured); stream- or endpoint-hours per 1,000 families per day; a care coordinator's
caseload per day; cost only with a supplied price; a sensitivity table (each assumption at -50% / base / +50%, the
boolean flipped). Not modelled: question answers and photo reads (not in the handover benchmark), peaks within a day,
rate limits of the endpoint.

Usage:
  python scripts/capacity_model.py                                   # writes release/benchmarks/capacity_<UTC>/
  python scripts/capacity_model.py --updates-per-family-per-day 4 --crosscheck-every-update yes --out OUT
  python scripts/capacity_model.py --config assumptions.json --price-per-million-tokens 0.5 --out OUT

Writes results.json and summary.md in a new folder (--out must not exist). Exit code 0, or 2 for a usage problem
(no usable benchmark, an existing output folder, a bad assumption). Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "kindredrelay-capacity-model-v1"
EXIT_OK, EXIT_USAGE = 0, 2
DEFAULT_MODEL = "DeepSeek-V4-Flash"
TOKEN_FACTORY_HOST = "developer.amd.com.cn"
STORY = ROOT / "handoff_day1" / "care_cases" / "episode_hip_fracture.json"
TF_GLOB, LOAD_GLOB, CROSSCHECK_GLOB = "tf_bench_*/results.json", "load_*/results.json", "crosscheck_*/results.json"
LOAD_THROUGHPUT_KEY = "per_model.{model}.throughput_handovers_per_s"
LOAD_CONCURRENCY_KEY = "per_model.{model}.concurrency"
DAYS_PER_MONTH = 30
FAMILIES = 1000
SENSITIVITY = 0.5
DEFAULT_ASSUMPTIONS = {"updates_per_family_per_day": 2.0, "families_per_care_coordinator": 30.0,
                       "crosscheck_every_update": False, "price_per_million_tokens": None}
ASSUMPTION_BASIS = {
    "updates_per_family_per_day": "illustrative pace of caregiver updates during an active care episode (not measured)",
    "families_per_care_coordinator": "illustrative caseload of one care coordinator (no source in this repository)",
    "crosscheck_every_update": "the cross-model check runs in shadow only and is not on the product path; yes adds one "
                               "judge call per update",
    "price_per_million_tokens": "no price is assumed: null reports tokens only; a supplied price is blended over prompt "
                                "and completion tokens, in the currency it is given in"}
WORDING = ("Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (host "
           f"{TOKEN_FACTORY_HOST}); the hardware behind the endpoint is not visible to this client, so no GPU is claimed.")


class UsageError(Exception):
    """A problem with the inputs or the command line; nothing was written."""


# ---------------------------------------------------------------------------------------------------------- inputs
def rel(p: Path) -> str:
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def get(doc, keys: tuple):
    """doc[k1][k2]... or None. Keys are a tuple, since a model name can hold a dot (Qwen3.8-27B)."""
    for k in keys:
        if not isinstance(doc, dict) or k not in doc:
            return None
        doc = doc[k]
    return doc


def key_path(template: str, model: str) -> tuple:
    """A dotted key template (as --load-throughput-key takes it) as a key tuple: split first, then {model} filled in."""
    return tuple(part.replace("{model}", model) for part in template.split("."))


def num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def candidates(root: Path, pattern: str) -> tuple[list, list]:
    """Readable results files under root, newest first (created_utc, then folder name), and the unreadable ones."""
    docs, skipped = [], []
    for p in sorted(root.glob(pattern)):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("not a JSON object")
            docs.append((p, doc))
        except (OSError, ValueError) as e:
            skipped.append({"path": rel(p), "reason": f"unreadable: {e}"})
    docs.sort(key=lambda pd: (str(pd[1].get("created_utc") or ""), pd[0].parent.name), reverse=True)
    return docs, skipped


def measured(path: Path, keys: tuple, doc: dict, label: str):
    v = get(doc, keys)
    return {"label": label, "value": v, "source": rel(path), "key": ".".join(keys)}


def tf_bench(root: Path, model: str) -> dict:
    """The newest live handover benchmark that measured `model`: tokens and latency per handover."""
    docs, skipped = candidates(root, TF_GLOB)
    for p, doc in docs:
        pm = ("per_model", model)
        if doc.get("dry_run") is not False:
            skipped.append({"path": rel(p), "reason": "dry run (or dry_run not false)"})
        elif num(get(doc, pm + ("tokens_per_handover", "mean"))) is None or num(get(doc, pm + ("e2e_latency_s", "mean"))) is None:
            skipped.append({"path": rel(p), "reason": f"no tokens_per_handover.mean / e2e_latency_s.mean for {model}"})
        else:
            items = {
                "tokens_per_handover": measured(p, pm + ("tokens_per_handover", "mean"), doc,
                                                "tokens per handover, mean (prompt + completion, endpoint usage)"),
                "prompt_tokens_per_handover": measured(p, pm + ("tokens_per_handover", "prompt_mean"), doc,
                                                       "prompt tokens per handover, mean"),
                "completion_tokens_per_handover": measured(p, pm + ("tokens_per_handover", "completion_mean"), doc,
                                                           "completion tokens per handover, mean"),
                "handovers_with_usage": measured(p, pm + ("tokens_per_handover", "n_with_usage"), doc,
                                                 "handovers whose usage the endpoint reported"),
                "e2e_latency_mean_s": measured(p, pm + ("e2e_latency_s", "mean"), doc,
                                               "end-to-end latency per handover, mean (s)"),
                "e2e_latency_p50_s": measured(p, pm + ("e2e_latency_s", "p50"), doc, "end-to-end latency, p50 (s)"),
                "e2e_latency_p95_s": measured(p, pm + ("e2e_latency_s", "p95"), doc, "end-to-end latency, p95 (s)"),
                "handovers_completed": measured(p, pm + ("n_completed",), doc, "handovers completed"),
                "handovers_successful": measured(p, pm + ("success", "count"), doc, "handovers successful"),
            }
            return {"path": rel(p), "sha256": sha256_file(p), "created_utc": doc.get("created_utc"),
                    "host": get(doc, ("endpoint", "host")), "model": model, "items": items, "skipped": skipped}
    raise UsageError(f"no live handover benchmark with {model} under {rel(root)}/{TF_GLOB}"
                     + (f" (skipped: {'; '.join(s['path'] + ': ' + s['reason'] for s in skipped)})" if skipped else ""))


def load_test(root: Path, model: str, throughput_key: str, concurrency_key: str) -> dict:
    """The newest live load test's measured throughput at its concurrency, or why the model stays sequential."""
    docs, skipped = candidates(root, LOAD_GLOB)
    tk, ck = key_path(throughput_key, model), key_path(concurrency_key, model)
    for p, doc in docs:
        if doc.get("dry_run") is not False:
            skipped.append({"path": rel(p), "reason": "dry run (or dry_run not false)"})
            continue
        t, c = num(get(doc, tk)), num(get(doc, ck))
        if t is None or t <= 0 or c is None or c < 1:
            skipped.append({"path": rel(p), "reason": f"no positive number at {'.'.join(tk)} and {'.'.join(ck)}"})
            continue
        return {"used": True, "path": rel(p), "sha256": sha256_file(p), "created_utc": doc.get("created_utc"),
                "host": get(doc, ("endpoint", "host")), "skipped": skipped,
                "items": {"throughput_handovers_per_s": measured(p, tk, doc, "completed handovers per second, all streams"),
                          "concurrency": measured(p, ck, doc, "concurrent streams")}}
    return {"used": False, "skipped": skipped,
            "reason": ("no live load test with " + ".".join(tk) + " and " + ".".join(ck) + f" under {rel(root)}/{LOAD_GLOB}:"
                       " throughput is modelled for one sequential stream only")}


def crosscheck(root: Path) -> dict:
    """The newest live cross-model check: judge tokens per check and judge call latency."""
    docs, skipped = candidates(root, CROSSCHECK_GLOB)
    for p, doc in docs:
        if doc.get("dry_run") is not False:
            skipped.append({"path": rel(p), "reason": "dry run (or dry_run not false)"})
        elif num(get(doc, ("tokens_per_check", "mean"))) is None or num(get(doc, ("latency_s", "p50"))) is None:
            skipped.append({"path": rel(p), "reason": "no tokens_per_check.mean / latency_s.p50"})
        else:
            return {"used": True, "path": rel(p), "sha256": sha256_file(p), "created_utc": doc.get("created_utc"),
                    "host": get(doc, ("endpoint", "host")), "judge_model": get(doc, ("judge", "model")), "skipped": skipped,
                    "items": {"judge_tokens_per_check": measured(p, ("tokens_per_check", "mean"), doc,
                                                                 "judge tokens per check, mean (endpoint usage)"),
                              "judge_latency_p50_s": measured(p, ("latency_s", "p50"), doc,
                                                              "judge call latency, p50 (s; the file has no mean)")}}
    return {"used": False, "skipped": skipped,
            "reason": f"no live cross-model check results under {rel(root)}/{CROSSCHECK_GLOB}: its cost is not measured"}


def story_pace(path: Path = STORY) -> dict | None:
    """The fictional demo story's updates per calendar day, as a reference beside the assumed pace (not a measurement)."""
    try:
        ups = json.loads(path.read_text(encoding="utf-8"))["updates"]
        days = {str(u["at"])[:10] for u in ups}
        return {"path": rel(path), "updates": len(ups), "calendar_days": len(days), "per_day": round(len(ups) / len(days), 2)}
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------------------------------------------------- model
def check_assumptions(a: dict) -> dict:
    unknown = set(a) - set(DEFAULT_ASSUMPTIONS)
    if unknown:
        raise UsageError(f"unknown assumption(s): {', '.join(sorted(unknown))} (known: {', '.join(DEFAULT_ASSUMPTIONS)})")
    for k in ("updates_per_family_per_day", "families_per_care_coordinator"):
        if num(a[k]) is None or a[k] <= 0:
            raise UsageError(f"{k} must be a positive number, not {a[k]!r}")
    if not isinstance(a["crosscheck_every_update"], bool):
        raise UsageError(f"crosscheck_every_update must be true or false, not {a['crosscheck_every_update']!r}")
    if a["price_per_million_tokens"] is not None and (num(a["price_per_million_tokens"]) is None
                                                      or a["price_per_million_tokens"] < 0):
        raise UsageError(f"price_per_million_tokens must be null or a number >= 0, not {a['price_per_million_tokens']!r}")
    return a


def value(m: dict | None, name: str):
    return None if not m or not m.get("used", True) else num(m["items"][name]["value"])


def compute(tf: dict, load: dict, cc: dict, a: dict) -> dict:
    """Every output from the measured inputs and the assumptions; None where an input it needs is not measured."""
    upd = float(a["updates_per_family_per_day"])
    extraction_tokens = value(tf, "tokens_per_handover")
    e2e_mean = value(tf, "e2e_latency_mean_s")
    judge_tokens = value(cc, "judge_tokens_per_check") if a["crosscheck_every_update"] else 0.0
    judge_s = value(cc, "judge_latency_p50_s") if a["crosscheck_every_update"] else 0.0
    per_update = None if judge_tokens is None else extraction_tokens + judge_tokens
    service_s = None if judge_s is None else e2e_mean + judge_s
    seq_per_hour = None if not service_s else 3600.0 / service_s
    load_per_hour = None
    if load.get("used") and not a["crosscheck_every_update"]:   # the load test measured handovers, not judge calls
        load_per_hour = value(load, "throughput_handovers_per_s") * 3600.0
    per_hour = load_per_hour if load_per_hour is not None else seq_per_hour

    def times(x, f):
        return None if x is None else x * f
    fam_day = times(per_update, upd)
    price = num(a["price_per_million_tokens"])
    families = float(a["families_per_care_coordinator"])
    return {
        "tokens_per_update": per_update,
        "extraction_tokens_per_family_per_day": extraction_tokens * upd,
        "tokens_per_family_per_day": fam_day,
        "tokens_per_family_per_month": times(fam_day, DAYS_PER_MONTH),
        "tokens_per_1000_families_per_day": times(fam_day, FAMILIES),
        "seconds_per_update_sequential": service_s,
        "handovers_per_stream_hour_sequential": seq_per_hour,
        "handovers_per_endpoint_hour_at_load_concurrency": load_per_hour,
        "load_concurrency": value(load, "concurrency") if load_per_hour is not None else None,
        "capacity_basis": "load test" if load_per_hour is not None else "sequential",
        "hours_per_1000_families_per_day": None if not per_hour else FAMILIES * upd / per_hour,
        "updates_per_coordinator_per_day": families * upd,
        "tokens_per_coordinator_per_day": times(fam_day, families),
        "hours_per_coordinator_per_day": None if not per_hour else families * upd / per_hour,
        "cost_per_family_per_month": None if price is None or fam_day is None else fam_day * DAYS_PER_MONTH * price / 1e6,
        "cost_per_1000_families_per_day": None if price is None or fam_day is None else fam_day * FAMILIES * price / 1e6,
    }


SENSITIVITY_OUTPUTS = ("tokens_per_family_per_day", "tokens_per_family_per_month", "hours_per_1000_families_per_day",
                       "tokens_per_coordinator_per_day", "cost_per_family_per_month")


def sensitivity(tf: dict, load: dict, cc: dict, a: dict) -> list:
    """Each assumption at -50% / base / +50% (a boolean: as set and flipped), every other assumption at its value."""
    rows = []
    for k, v in a.items():
        if isinstance(v, bool):
            settings = [("base", v), ("flipped", not v)]
        elif v is None:
            continue                                     # no price: nothing to vary
        else:
            settings = [("-50%", v * (1 - SENSITIVITY)), ("base", v), ("+50%", v * (1 + SENSITIVITY))]
        for name, x in settings:
            out = compute(tf, load, cc, {**a, k: x})
            rows.append({"assumption": k, "setting": name, "value": x, **{o: out[o] for o in SENSITIVITY_OUTPUTS}})
    return rows


# ---------------------------------------------------------------------------------------------------------- report
def build(root: Path, model: str, a: dict, throughput_key: str = LOAD_THROUGHPUT_KEY,
          concurrency_key: str = LOAD_CONCURRENCY_KEY, argv=None) -> dict:
    a = check_assumptions(dict(a))
    tf = tf_bench(root, model)
    load = load_test(root, model, throughput_key, concurrency_key)
    cc = crosscheck(root)
    notes = []
    if not load["used"]:
        notes.append(load["reason"] + ".")
    elif a["crosscheck_every_update"]:
        notes.append("The load test measured handovers without the cross-model check, so with every update cross-checked "
                     "the capacity is the sequential model's.")
    if a["crosscheck_every_update"] and not cc["used"]:
        notes.append(cc["reason"] + "; with every update cross-checked the totals that need it are n/a (the extraction "
                     "tokens alone are still given).")
    for m in (tf, load, cc):
        if m.get("used", True) and m.get("host") not in (None, TOKEN_FACTORY_HOST):
            notes.append(f"{m['path']} was measured against host {m['host']}, not the AMD Token Factory endpoint.")
    return {
        "schema_version": SCHEMA_VERSION, "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "argv": list(argv or []), "model": model, "bench_root": rel(root),
        "wording": WORDING if tf.get("host") == TOKEN_FACTORY_HOST else f"Measured against host {tf.get('host') or 'n/a'}.",
        "measured": {"tf_bench": tf, "load_test": load, "crosscheck": cc},
        "assumptions": {k: {"value": v, "basis": ASSUMPTION_BASIS[k], "default": DEFAULT_ASSUMPTIONS[k]} for k, v in a.items()},
        "conventions": {"days_per_month": DAYS_PER_MONTH, "families_scale": FAMILIES, "sensitivity": f"±{SENSITIVITY:.0%}"},
        "reference_story_pace": story_pace(),
        "outputs": compute(tf, load, cc, a),
        "sensitivity": sensitivity(tf, load, cc, a),
        "notes": notes,
        "not_modelled": ["question answers and photo reads (not in the handover benchmark)",
                         "peaks within a day and queueing: hours are busy time, not wall-clock hours",
                         "the endpoint's rate limits and other clients' load",
                         "the network path apart from the endpoint (the measured latency includes the path from the benchmark machine)"],
    }


def fmt(x, digits: int = 0) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (int, float)):
        return f"{x:,.{digits}f}"
    return str(x)


def fmt_measured(x) -> str:
    """A measured number as the source has it: an integer as is, a float to at most 4 decimals."""
    if isinstance(x, float):
        return f"{round(x, 4):,}"
    return fmt(x)


def fmt_assumed(k: str, x) -> str:
    return "null (tokens only)" if k == "price_per_million_tokens" and x is None else fmt(x, 2)


OUTPUT_ROWS = (  # key, label, digits, formula, measured inputs, assumed inputs
    ("tokens_per_update", "Tokens per caregiver update", 0, "tokens per handover (+ judge tokens per check if cross-checked)",
     "tokens per handover; judge tokens per check", "crosscheck_every_update"),
    ("tokens_per_family_per_day", "Tokens per family per day", 0, "tokens per update × updates per day",
     "tokens per handover", "updates_per_family_per_day, crosscheck_every_update"),
    ("tokens_per_family_per_month", "Tokens per family per month", 0, f"× {DAYS_PER_MONTH} days",
     "tokens per handover", "updates_per_family_per_day, crosscheck_every_update"),
    ("tokens_per_1000_families_per_day", "Tokens per 1,000 families per day", 0, f"× {FAMILIES:,}",
     "tokens per handover", "updates_per_family_per_day, crosscheck_every_update"),
    ("seconds_per_update_sequential", "Seconds per update, one sequential stream", 2,
     "e2e latency mean (+ judge call p50 if cross-checked)", "e2e latency mean; judge latency p50", "crosscheck_every_update"),
    ("handovers_per_stream_hour_sequential", "Handovers per stream-hour (sequential)", 1, "3600 / seconds per update",
     "e2e latency mean", "crosscheck_every_update"),
    ("handovers_per_endpoint_hour_at_load_concurrency", "Handovers per endpoint-hour at the load test's concurrency", 1,
     "throughput per s × 3600", "load test throughput", "—"),
    ("hours_per_1000_families_per_day", "Busy hours per 1,000 families per day", 2,
     "1,000 × updates per day / handovers per hour", "capacity basis above", "updates_per_family_per_day"),
    ("updates_per_coordinator_per_day", "Updates per care coordinator's caseload per day", 0, "families × updates per day",
     "—", "families_per_care_coordinator, updates_per_family_per_day"),
    ("tokens_per_coordinator_per_day", "Tokens per care coordinator's caseload per day", 0, "families × tokens per family per day",
     "tokens per handover", "families_per_care_coordinator, updates_per_family_per_day"),
    ("hours_per_coordinator_per_day", "Busy hours per care coordinator's caseload per day", 2, "updates / handovers per hour",
     "capacity basis above", "families_per_care_coordinator, updates_per_family_per_day"),
    ("cost_per_family_per_month", "Cost per family per month", 4, "tokens per month × price / 1e6", "tokens per handover",
     "price_per_million_tokens"),
    ("cost_per_1000_families_per_day", "Cost per 1,000 families per day", 2, "tokens per day × price / 1e6",
     "tokens per handover", "price_per_million_tokens"),
)


def summary_md(res: dict) -> str:
    tf, load, cc, o = res["measured"]["tf_bench"], res["measured"]["load_test"], res["measured"]["crosscheck"], res["outputs"]
    basis = ("the load test's measured throughput at concurrency " + fmt(o["load_concurrency"])
             if o["capacity_basis"] == "load test" else
             "one sequential stream (one client sending updates back to back): a per-client rate, not the endpoint's "
             "capacity, which no load test has measured yet")
    out = [f"# Capacity and token model: `{res['model']}` on the caregiver-update path", "", res["wording"], "",
           f"A model, not a measurement: measured per-handover numbers × labelled assumptions. Created {res['created_utc']}. "
           f"Capacity basis: {basis}. Tokens are the endpoint's usage field; no price is invented "
           f"(price_per_million_tokens {fmt_assumed('price_per_million_tokens', res['assumptions']['price_per_million_tokens']['value'])}).", "",
           "## Measured", "", "| Quantity | Value | Source file | JSON key |", "|---|---|---|---|"]
    for m in (tf, load, cc):
        if m.get("used", True):
            for item in m["items"].values():
                out.append(f"| {item['label']} | {fmt_measured(item['value'])} | {item['source']} | `{item['key']}` |")
    out += ["", f"Handover benchmark {tf['path']} (created {tf['created_utc']}, sha256 {tf['sha256'][:12]}, host "
                f"{tf['host'] or 'n/a'})."]
    out.append(f"Load test: {load['path']} (created {load['created_utc']}, sha256 {load['sha256'][:12]})." if load["used"]
               else f"Load test: not used ({load['reason']}).")
    out.append(f"Cross-model check: {cc['path']} (judge {cc['judge_model'] or 'n/a'}, created {cc['created_utc']}, sha256 "
               f"{cc['sha256'][:12]})." if cc["used"] else f"Cross-model check: not used ({cc['reason']}).")
    for m in (tf, load, cc):
        for s in m["skipped"]:
            out.append(f"- skipped {s['path']}: {s['reason']}")
    out += ["", "## Assumed", "", "| Assumption | Value | Default | Basis |", "|---|---|---|---|"]
    for k, v in res["assumptions"].items():
        out.append(f"| {k} | {fmt_assumed(k, v['value'])} | {fmt_assumed(k, v['default'])} | {v['basis']} |")
    ref = res["reference_story_pace"]
    if ref:
        out.append(f"\nReference, not a measurement: the fictional demo story ({ref['path']}) has {ref['updates']} updates "
                   f"over {ref['calendar_days']} calendar days ({ref['per_day']} per day).")
    out.append(f"Conventions: a month is {DAYS_PER_MONTH} days; scale {FAMILIES:,} families.")
    out += ["", "## Outputs", "", "| Output | Value | Formula | Measured inputs used | Assumed inputs used |",
            "|---|---|---|---|---|"]
    for key, label, digits, formula, meas, assumed in OUTPUT_ROWS:
        out.append(f"| {label} | {fmt(o[key], digits)} | {formula} | {meas} | {assumed} |")
    out += ["", f"Capacity basis for the busy-hour rows: {o['capacity_basis']}.", "",
            f"## Sensitivity (each assumption at -{SENSITIVITY:.0%} / base / +{SENSITIVITY:.0%}, the others at their values)",
            "", "| Assumption | Setting | Value | Tokens / family / day | Tokens / family / month | Busy hours / 1,000 "
            "families / day | Tokens / coordinator / day | Cost / family / month |", "|---|---|---|---|---|---|---|---|"]
    for r in res["sensitivity"]:
        out.append(f"| {r['assumption']} | {r['setting']} | {fmt(r['value'], 2)} | {fmt(r['tokens_per_family_per_day'])} | "
                   f"{fmt(r['tokens_per_family_per_month'])} | {fmt(r['hours_per_1000_families_per_day'], 2)} | "
                   f"{fmt(r['tokens_per_coordinator_per_day'])} | {fmt(r['cost_per_family_per_month'], 4)} |")
    out += ["", "## Notes", ""] + [f"- {n}" for n in res["notes"]] + [f"- Not modelled: {n}." for n in res["not_modelled"]]
    return "\n".join(out) + "\n"


def write(res: dict, out: Path) -> None:
    out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(summary_md(res), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------- CLI
def yes_no(v: str) -> bool:
    if v.lower() in ("yes", "true", "1"):
        return True
    if v.lower() in ("no", "false", "0"):
        return False
    raise argparse.ArgumentTypeError(f"yes or no, not {v!r}")


def assumptions_from(args) -> dict:
    a = dict(DEFAULT_ASSUMPTIONS)
    if args.config:
        try:
            cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise UsageError(f"--config {args.config}: {e}") from e
        if not isinstance(cfg, dict):
            raise UsageError(f"--config {args.config}: not a JSON object")
        a.update(cfg)
    for k in DEFAULT_ASSUMPTIONS:
        if getattr(args, k) is not None:
            a[k] = getattr(args, k)
    return a


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bench-root", default=str(ROOT / "release" / "benchmarks"), help="where the results folders are")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"the handover model (default {DEFAULT_MODEL})")
    ap.add_argument("--config", help="JSON object of assumption overrides (keys: " + ", ".join(DEFAULT_ASSUMPTIONS) + ")")
    ap.add_argument("--updates-per-family-per-day", dest="updates_per_family_per_day", type=float)
    ap.add_argument("--families-per-care-coordinator", dest="families_per_care_coordinator", type=float)
    ap.add_argument("--crosscheck-every-update", dest="crosscheck_every_update", type=yes_no, metavar="{yes,no}")
    ap.add_argument("--price-per-million-tokens", dest="price_per_million_tokens", type=float)
    ap.add_argument("--load-throughput-key", default=LOAD_THROUGHPUT_KEY, help=f"default {LOAD_THROUGHPUT_KEY}")
    ap.add_argument("--load-concurrency-key", default=LOAD_CONCURRENCY_KEY, help=f"default {LOAD_CONCURRENCY_KEY}")
    ap.add_argument("--out", help="new output folder (must not exist); default release/benchmarks/capacity_<UTC>")
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else (
        ROOT / "release" / "benchmarks" / f"capacity_{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}")
    try:
        if out.exists():
            raise UsageError(f"--out {out} exists; give a new folder")
        root = Path(args.bench_root)
        if not root.is_dir():
            raise UsageError(f"--bench-root {root} is not a folder")
        res = build(root, args.model, assumptions_from(args), args.load_throughput_key, args.load_concurrency_key, argv)
        write(res, out)
    except UsageError as e:
        print(f"capacity_model: {e}", file=sys.stderr)
        return EXIT_USAGE
    o = res["outputs"]
    print(f"capacity_model: wrote {rel(out)}/results.json and summary.md")
    print(f"  tokens per family per day {fmt(o['tokens_per_family_per_day'])}, per month {fmt(o['tokens_per_family_per_month'])}; "
          f"capacity basis {o['capacity_basis']}; busy hours per 1,000 families per day "
          f"{fmt(o['hours_per_1000_families_per_day'], 2)}")
    for n in res["notes"]:
        print(f"  note: {n}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
