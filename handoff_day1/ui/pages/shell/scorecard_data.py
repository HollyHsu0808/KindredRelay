"""The numbers on the Evaluation & Safety Scorecard, each with the file it was copied from: `path` + `line` + a `quote`
that line must contain, or `path` + a JSON `key` whose value it must equal. ../../test_app_shell.py opens every source
and checks it, so a changed result file fails the test instead of leaving a stale number on the page. Four results
are read at run time: the Token Factory benchmark, the red-team run, the cross-model semantic check (shadow) and the
offline validation run. They come from
the frozen copies in data/ (scripts/freeze_scorecard_results.py; Dockerfile.release copies ui/pages/ but not
release/), else from the newest run under release/ (a checkout), else the page says not yet run.

Stdlib only; no Streamlit here (the page is scorecard.py).
"""
from __future__ import annotations

import functools
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess

REPO = Path(__file__).resolve().parents[4]   # handoff_day1/ui/pages/shell -> the repository root
DATA = Path(__file__).resolve().parent / "data"   # frozen snapshots, inside the release image
Z95 = 1.959963984540054


def ref(fact: dict) -> str:
    """How the page names a source: path:line, or path -> JSON key."""
    return f"{fact['path']}:{fact['line']}" if "line" in fact else f"{fact['path']} → {fact['key']}"


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for k successes out of n (None when n is 0)."""
    if n <= 0:
        return None
    p, z2 = k / n, z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def ratio(k: int, n: int) -> str:
    """'10/80 (12.50%, Wilson 95% 6.9–21.5%)': the rate as the result documents write it, the interval to 0.1 point."""
    ci = wilson(k, n)
    return f"{k}/{n}" if ci is None else f"{k}/{n} ({pct(k / n, 2)}, Wilson 95% {pct(ci[0])}–{pct(ci[1])})"


# ------------------------------------------------------------------ fall model (README.md)
FALL = {
    "auc": {"value": "0.975 ± 0.011", "path": "release/evidence_en/DEV_README_EXCERPT.md", "line": 16, "quote": "AUC 0.975 ± 0.011"},
    "balanced_accuracy": {"value": "0.903 ± 0.025", "path": "release/evidence_en/DEV_README_EXCERPT.md", "line": 16,
                          "quote": "balanced accuracy 0.903 ± 0.025"},
    "baseline_auc": {"value": "0.656", "path": "release/evidence_en/DEV_README_EXCERPT.md", "line": 16, "quote": "The prior-event v1 baseline gets 0.656"},
    "preliminary": {"value": "Preliminary, CPU; LOSO over Subjects 1–3", "path": "release/evidence_en/DEV_README_EXCERPT.md", "line": 16,
                    "quote": "Preliminary, CPU: LOSO estimate over Subjects 1–3"},
    "split": {"value": "train Subjects 1–2, validation Subject 3, test Subject 4 never loaded", "path": "release/evidence_en/DEV_README_EXCERPT.md",
              "line": 15, "quote": "train = Subjects 1–2, validation = Subject 3; Subject 4, the test split, was never loaded"},
    "human_in_loop": {"value": "a prompt for a caregiver to confirm", "path": "release/evidence_en/DEV_README_EXCERPT.md", "line": 18,
                      "quote": "A fall result is a prompt for a caregiver to confirm (human in the loop)"},
}

# ------------------------------------------------------------------ source-support verifier
VERIFIER = {
    "v1_auroc": {"value": "0.9800", "path": "release/evidence_en/KAGGLE_RESULT.md", "line": 14, "quote": "0.9800"},
    "v1_false_acceptance": {"value": (29, 1648), "path": "release/evidence_en/KAGGLE_RESULT.md", "line": 16, "quote": "29/1648"},
    "v1_qa_false_acceptance": {"value": (9, 131), "path": "release/evidence_en/KAGGLE_RESULT.md", "line": 18, "quote": "9/131"},
    "v1_threshold_fit": {"value": "threshold fitted on validation", "path": "release/evidence_en/KAGGLE_RESULT.md", "line": 21,
                         "quote": "Threshold fitted on validation"},
    "v1_kept_off": {"value": "kept off", "path": "release/evidence_en/KAGGLE_RESULT.md", "line": 35, "quote": "verifier stays `off`"},
    "auroc_meaning": {"value": "AUROC is not accuracy or a clinical risk probability",
                      "path": "release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md", "line": 22,
                      "quote": "AUROC must not be read as accuracy or as a clinical risk probability"},
    "v2_calibration_auroc": {"value": "0.961569", "path": "release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md", "line": 26,
                             "quote": "| All | 4,091 | 2,231 / 1,860 | 0.961569 |"},
    "v2_thresholds": {"value": (0, 4048), "path": "release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md", "line": 39,
                      "quote": "**4,048 candidate thresholds**, the number of valid shared thresholds is **0**"},
    "v2_criteria": {"value": "every scope FAR ≤ 5% and supported acceptance ≥ 10%",
                    "path": "release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md", "line": 39,
                    "quote": "FAR ≤ 5% and supported acceptance ≥ 10%"},
    "v2_operating_point": {"value": "validation_operating_point_found=false", "path": "release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md",
                           "line": 40, "quote": "`validation_operating_point_found=false`"},
    "v2_not_enabled": {"value": "gate not enabled", "path": "release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md", "line": 3,
                       "quote": "deployment acceptance did not pass; the v2 gate is not enabled in this round"},
    "release_mode": {"value": "KINDRED_VERIFIER_MODE=off", "path": "Dockerfile.release", "line": 14,
                     "quote": "KINDRED_VERIFIER_MODE=off"},
    "gate_rule": {"value": "gate needs validation_operating_point_found true", "path": "deploy/serve.py", "line": 42,
                  "quote": 'card.get("validation_operating_point_found") is not True'},
    "grounding": {"value": "facts must quote the update word for word", "path": "handoff_day1/agent/README.md", "line": 29,
                  "quote": "Facts must quote the update word for word"},
}

# ------------------------------------------------------------------ temporal benchmark (Journal vs full context vs RAG)
METHODS = (("journal", "Journal"), ("full_context", "Full context"), ("rag", "Lexical RAG"))
COUNT_KEYS = ("all_correct", "event_true_positive", "event_predicted", "event_expected", "citation_valid",
              "citation_total", "operational_failure")


def _benchmark(path: str, doc: str, doc_lines: dict, counts: dict, variants: int, paired: list) -> dict:
    return {"path": path, "doc": doc, "doc_lines": doc_lines, "variants": variants, "counts": counts, "paired": paired}


HELDOUT = _benchmark(
    "research/temporal_benchmark/results/round3_heldout_20261017.json", "release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md",
    {"all_correct": 151, "precision": 154, "recall": 155, "citations": 159, "failures": 162, "paired": 164},
    {"journal": dict(zip(COUNT_KEYS, (10, 73, 315, 150, 430, 430, 1))),
     "full_context": dict(zip(COUNT_KEYS, (11, 47, 125, 150, 247, 253, 13))),
     "rag": dict(zip(COUNT_KEYS, (13, 57, 117, 150, 233, 235, 10)))},
    80,
    [{"left": "journal", "right": "rag", "difference": -0.0375, "interval": [-0.1625, 0.1]},
     {"left": "full_context", "right": "journal", "difference": 0.0125, "interval": [-0.1125, 0.1375]},
     {"left": "full_context", "right": "rag", "difference": -0.025, "interval": [-0.0625, 0.0]}])
HELDOUT.update(stories=40, bootstrap_draws=5000, title="Heldout 240: 40 stories × 2 arrival orders × 3 methods (final, one-shot)")
TEMPORAL_CONTEXT = {
    "endpoint": {"value": "AMD Token Factory", "path": "release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md", "line": 85,
                 "quote": "real dev and heldout inference on the existing free AMD Token Factory was completed, sealed and scored"},
    "model": {"value": "DeepSeek-V4-Flash (service alias)", "path": "release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md",
              "line": 93, "quote": "`DeepSeek-V4-Flash` alias"},
    "data": {"value": "fictional English stories written by an LLM, no clinical review",
             "path": "release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md", "line": 177,
             "quote": "fictional English data written by an LLM author, no human clinical review"},
    "no_advantage": {"value": "no overall advantage", "path": "release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md",
                     "line": 164, "quote": "All paired intervals include 0: **no overall advantage of the Journal is established, and RAG is not claimed to be significantly better either**"},
}

DEV96 = _benchmark(
    "research/temporal_benchmark/results/round1_dev_20261017.json", "release/evidence_en/TEMPORAL_EXPERIMENT_ROUND1.md",
    {"all_correct": 29, "precision": 31, "recall": 32, "failures": 35, "paired": 39},
    {"journal": dict(zip(COUNT_KEYS, (6, 34, 108, 60, 158, 158, 0))),
     "full_context": dict(zip(COUNT_KEYS, (7, 24, 47, 60, 98, 98, 3))),
     "rag": dict(zip(COUNT_KEYS, (8, 23, 47, 60, 92, 92, 4)))},
    32,
    [{"left": "journal", "right": "rag", "difference": -0.0625, "interval": [-0.375, 0.25]},
     {"left": "full_context", "right": "journal", "difference": 0.03125, "interval": [-0.28125, 0.3125]},
     {"left": "full_context", "right": "rag", "difference": -0.03125, "interval": [-0.125, 0.0625]}])
DEV96.update(stories=16, bootstrap_draws=5000, title="Development round 1: 16 stories × 2 arrival orders × 3 methods (exploratory)")

# ------------------------------------------------------------------ deterministic test suite
SUITE_DOCUMENTED = {"value": (18, 556), "path": "release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md", "line": 10,
                    "quote": "18 processes, 556 unittest cases"}
SUITE_SCOPE = {"value": "deterministic engine/UI tests", "path": "deploy/validate_abd.py", "line": 104,
               "quote": "Deterministic engine/UI tests. Doubles do not validate trained-model accuracy or deployment."}
# The tests of this repository: test_*.py under these folders (KindredRelay_Research_20261017/ holds an audit copy of
# another branch, not tests of this tree). Which of them a validation run executed is read from its summary.json.
TEST_ROOTS = ("deploy", "handoff_day1", "research", "scripts", "training")

# ------------------------------------------------------------------ results read at run time
DATA_REL = "handoff_day1/ui/pages/shell/data"
FROZEN_TF_BENCH = "tf_bench_*.json"      # one per frozen benchmark run
FROZEN_REDTEAM = "redteam.json"
FROZEN_VALIDATION = "validation.json"
FROZEN_CROSSCHECK = "crosscheck.json"
TF_BENCH_GLOB = "release/benchmarks/tf_bench_*/results.json"     # scripts/bench_tf_handover.py
REDTEAM_GLOB = "release/benchmarks/redteam_*/results.json"       # scripts/redteam_safety.py
VALIDATION_GLOB = "release/validation_abd/*/summary.json"        # deploy/validate_abd.py --out DIR
CROSSCHECK_GLOB = "release/benchmarks/crosscheck_*/results.json"  # scripts/crosscheck_judge.py eval
# Which product path each red-team target exercises (scripts/redteam_safety.py TARGETS). The deployed app is the family
# timeline (ui/pages/1_Family_timeline.py: episode.py and episode_qa.py); the Case Agent (case_agent.py) is not on it.
FAMILY_PATH = "family timeline"
CASE_AGENT_PATH = "Case Agent / instruction extractor"
TARGET_PATH = {"episode_grounding": FAMILY_PATH, "episode_update": FAMILY_PATH, "qa_check_answer": FAMILY_PATH,
               "qa_answer": FAMILY_PATH, "extract_instructions": CASE_AGENT_PATH, "case_agent_answer": CASE_AGENT_PATH,
               "case_rewrite": CASE_AGENT_PATH}
OPEN_GAP = ("gap_confirmed", "gap_partial")


def get(d, *keys):
    """d[k1][k2]... or None when any step is missing or of the wrong kind."""
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        elif isinstance(d, list) and isinstance(k, int) and -len(d) <= k < len(d):
            d = d[k]
        else:
            return None
    return d


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _int(x) -> int | None:
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def read_json(p: Path) -> dict | None:
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def display_path(p: Path, root: Path = REPO) -> str:
    try:
        return Path(p).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(p).as_posix()


def newest_results(pattern: str, root: Path = REPO) -> tuple[Path, dict] | None:
    """The newest readable results.json matching pattern under root (its own created time, else its folder name). A
    file that does not say dry_run false (a dry run) is chosen only when no live run is there."""
    found = []
    for p in root.glob(pattern):
        doc = read_json(p)
        if doc is not None:
            stamp = doc.get("created_utc") or get(doc, "run", "utc") or ""
            found.append((str(stamp), p.parent.name, p, doc))
    live = [f for f in found if f[3].get("dry_run") is False]
    if not found:
        return None
    _, _, path, doc = max(live or found, key=lambda t: (t[0], t[1]))
    return path, doc


def frozen(pattern: str, data: Path | None = None) -> list[dict]:
    """The snapshots scripts/freeze_scorecard_results.py wrote in data/: {"frozen": {source_dir, source_file,
    source_sha256, ...}, "doc": the result file as it was, "before": optional earlier run}."""
    out = []
    for p in sorted(Path(DATA if data is None else data).glob(pattern)):
        snap = read_json(p)
        if snap is not None and isinstance(snap.get("frozen"), dict) and isinstance(snap.get("doc"), dict):
            out.append({"path": p, "frozen": snap["frozen"], "doc": snap["doc"],
                        "before": snap["before"] if isinstance(snap.get("before"), dict) else None})
    return out


def frozen_source(path: Path, meta: dict, root: Path = REPO) -> str:
    sha = str(meta.get("source_sha256") or "")[:12] or "n/a"
    return (f"{display_path(path, root)} (frozen copy of {meta.get('source_dir') or 'n/a'}/{meta.get('source_file') or ''}, "
            f"sha256 {sha})")


def run_label(doc: dict) -> str:
    """A benchmark run named by what it ran: created time, models, the extra request body (e.g. thinking off)."""
    pipe = doc.get("pipeline") or {}
    extra = pipe.get("extra_body")
    models = ", ".join(map(str, doc.get("models") or [])) or "n/a"
    return (("DRY RUN, " if doc.get("dry_run") is not False else "") + f"run of {str(doc.get('created_utc') or 'n/a')[:16]} UTC: "
            f"{models}; extra_body {json.dumps(extra) if isinstance(extra, dict) else 'n/a'}")


def tf_bench_runs(root: Path = REPO, data: Path | None = None) -> list[dict]:
    """Every frozen Token Factory benchmark snapshot (live runs first, then oldest first), each with its label; without
    one, the newest results.json under release/benchmarks/ (newest_results). [] when there is neither."""
    snaps = frozen(FROZEN_TF_BENCH, data)
    if snaps:
        snaps.sort(key=lambda s: (s["doc"].get("dry_run") is not False, str(s["doc"].get("created_utc") or ""), s["path"].name))
        return [{"doc": s["doc"], "label": str(s["frozen"].get("label") or run_label(s["doc"])),
                 "source": frozen_source(s["path"], s["frozen"], root)} for s in snaps]
    found = newest_results(TF_BENCH_GLOB, root)
    if found is None:
        return []
    return [{"doc": found[1], "label": run_label(found[1]), "source": display_path(found[0], root)}]


def redteam_run(root: Path = REPO, data: Path | None = None) -> dict | None:
    """The frozen red-team snapshot (with its earlier run, when one was frozen beside it), else the newest results.json
    under release/benchmarks/."""
    snaps = frozen(FROZEN_REDTEAM, data)
    if snaps:
        s, before = snaps[0], snaps[0]["before"] or {}
        has_before = isinstance(before.get("doc"), dict)
        return {"doc": s["doc"], "source": frozen_source(s["path"], s["frozen"], root),
                "before": before["doc"] if has_before else None,
                "before_source": f"{display_path(s['path'], root)} → before (frozen copy of "
                                 f"{get(before, 'frozen', 'source_dir') or 'n/a'}/{get(before, 'frozen', 'source_file') or ''}, "
                                 f"sha256 {str(get(before, 'frozen', 'source_sha256') or '')[:12] or 'n/a'})" if has_before else None}
    found = newest_results(REDTEAM_GLOB, root)
    if found is None:
        return None
    return {"doc": found[1], "source": display_path(found[0], root), "before": None, "before_source": None}


def crosscheck_run(root: Path = REPO, data: Path | None = None) -> dict | None:
    """The frozen cross-model check snapshot, else the newest results.json of scripts/crosscheck_judge.py under
    release/benchmarks/ (a live run before any dry run)."""
    snaps = frozen(FROZEN_CROSSCHECK, data)
    if snaps:
        return {"doc": snaps[0]["doc"], "source": frozen_source(snaps[0]["path"], snaps[0]["frozen"], root)}
    found = newest_results(CROSSCHECK_GLOB, root)
    if found is None:
        return None
    return {"doc": found[1], "source": display_path(found[0], root)}


CROSSCHECK_SETS = (("variants", "Variant held-out set (model-generated paraphrases)"),
                   ("round1_variants_not_heldout", "Round-1 variants under the round-2 policy (NOT held out; secondary)"),
                   ("original", "Original red-team cases"),
                   ("original_heldout", "Original heldout cases (HO-*)"))
CROSSCHECK_R1_DECISION = "flag = not supported OR autonomous_diagnosis OR dose_mismatch OR instruction_override"


def _crosscheck_round(n, paraphraser, decision, prompt_sha, prereg, rules, layered, unverified, result) -> dict:
    def frac(m, key):
        k, n_ = _int(get(m, key, "k")), _int(get(m, key, "n"))
        return ratio(k, n_) if k is not None and n_ else "n/a"
    return {"Round": str(n), "Paraphraser (variants)": paraphraser or "n/a", "Judge decision": decision or "n/a",
            "Prompt sha256": (str(prompt_sha or "")[:12] or "n/a"), "Preregistered": prereg or "n/a",
            "Rules only: attack recall": frac(rules, "attack_recall"),
            "Rules OR judge: attack recall": frac(layered, "attack_recall"),
            "Rules only: benign false blocks": frac(rules, "benign_false_block"),
            "Rules OR judge: benign false blocks": frac(layered, "benign_false_block"),
            "Judge unverified": ratio(_int(unverified.get("k")), _int(unverified.get("n")))
            if isinstance(unverified, dict) and _int(unverified.get("k")) is not None and _int(unverified.get("n")) else "n/a",
            "Acceptance": result if result in ("PASS", "FAIL") else "n/a"}


def crosscheck_rounds(doc: dict) -> list[dict]:
    """Round 1 and round 2 side by side, each on its own preregistered held-out variant set: round 1 from the round-2
    file's round1_reference (round 1's results.json as it was, with its sha256), round 2 from the file itself. [] for a
    round-1 file."""
    if doc.get("protocol") in (None, "r1"):
        return []
    ref, pc = doc.get("round1_reference") or {}, doc.get("policy_change_from_round_1") or {}
    v = get(doc, "sets", "variants") or {}
    rows = []
    if ref:
        rows.append(_crosscheck_round(1, ref.get("paraphrase_model"), ref.get("decision") or CROSSCHECK_R1_DECISION,
                                      ref.get("prompt_sha256"), get(pc, "round_1", "preregistration"),
                                      ref.get("rules_only") or {}, ref.get("rules_or_judge_conservative") or {},
                                      ref.get("unverified") or {}, get(ref, "acceptance", "result")))
    rows.append(_crosscheck_round(2, get(doc, "paraphrase", "paraphrase_model"), pc.get("decision_round_2"),
                                  get(doc, "judge", "prompt_sha256"), get(doc, "preregistration", "path"),
                                  v.get("rules_only") or {}, get(v, "rules_or_judge", "conservative") or {},
                                  v.get("unverified") or {}, get(doc, "acceptance", "result")))
    return rows


def crosscheck_mcnemar(doc: dict) -> list[dict]:
    """The preregistered secondary analysis of a round-2 file: exact McNemar, rules only vs rules OR judge, per set and
    label; the p-value as the file states it (unrounded), shown to 3 significant digits."""
    out = []
    for key, label in CROSSCHECK_SETS[:2]:
        mc = get(doc, "sets", key, "mcnemar_rules_vs_rules_or_judge")
        if not isinstance(mc, dict) or doc.get("protocol") in (None, "r1"):
            continue
        for lab in ("attack", "benign"):
            x = mc.get(lab) or {}
            p = _num(x.get("p_exact"))
            out.append({"Set": label, "Cases": lab, "Pairs": str(x.get("n", "n/a")),
                        "Rules only stop": str(x.get("rules_stopped", "n/a")),
                        "Rules OR judge stop": str(x.get("rules_or_judge_stopped", "n/a")),
                        "Discordant b (rules only)": str(x.get("b_rules_only", "n/a")),
                        "Discordant c (rules OR judge only)": str(x.get("c_rules_or_judge_only", "n/a")),
                        "Exact McNemar p": "n/a" if p is None else f"{p:.3g}"})
    return out


def crosscheck_view(doc: dict) -> dict:
    """scripts/crosscheck_judge.py's results.json as display values; missing keys read n/a. The acceptance result is the
    file's own (PASS / FAIL against the rule it preregistered), never recomputed here; a file that does not say
    dry_run false is a dry run, so its numbers are never shown as measurements."""
    acc, sets = doc.get("acceptance") or {}, doc.get("sets") or {}

    def frac(m, *where):
        k, n = _int(get(m, *where, "k")), _int(get(m, *where, "n"))
        return ratio(k, n) if k is not None and n else "n/a"
    rows = []
    for key, label in CROSSCHECK_SETS:
        m = sets.get(key)
        if not isinstance(m, dict):
            continue
        rows.append({"Set": label, "Attacks / benign": f"{m.get('attacks', 'n/a')} / {m.get('benign', 'n/a')}",
                     "Rules only: attack recall": frac(m, "rules_only", "attack_recall"),
                     "Rules OR judge: attack recall": frac(m, "rules_or_judge", "conservative", "attack_recall"),
                     "Rules only: benign false blocks": frac(m, "rules_only", "benign_false_block"),
                     "Rules OR judge: benign false blocks": frac(m, "rules_or_judge", "conservative", "benign_false_block"),
                     "Judge unverified": frac(m, "unverified")})
    checks = [{"Criterion": str(k).replace("_", " "), "Value": "n/a" if _num(c.get("value")) is None else f"{c['value']:.4f}",
               "Threshold": str(c.get("threshold", "n/a")), "Met": "yes" if c.get("pass") is True else "no"}
              for k, c in (acc.get("checks") or {}).items() if isinstance(c, dict)]
    fn, fp = doc.get("judge_false_negatives") or {}, doc.get("judge_false_positives") or {}
    calls = doc.get("http_calls") or {}
    return {"dry_run": doc.get("dry_run") is not False, "created": doc.get("created_utc"),
            "host": get(doc, "endpoint", "host"), "judge_model": get(doc, "judge", "model"),
            "generator": doc.get("product_generator"), "paraphraser": get(doc, "paraphrase", "paraphrase_model"),
            "prereg_utc": get(doc, "preregistration", "created_utc"), "first_judge_utc": doc.get("first_judge_call_utc"),
            "variants_file": get(doc, "preregistration", "variants_file"),
            "variants_sha": (get(doc, "preregistration", "variants_sha256") or "")[:12] or None,
            "rule": acc.get("rule"), "result": acc.get("result") if acc.get("result") in ("PASS", "FAIL") else "n/a",
            "decision": acc.get("decision"), "incomplete": len(acc.get("incomplete") or []), "checks": checks, "rows": rows,
            "latency": (get(doc, "latency_s", "p50"), get(doc, "latency_s", "p95")),
            "tokens_mean": _num(get(doc, "tokens_per_check", "mean")),
            "calls": {k: _int(calls.get(k)) for k in ("total", "judge", "paraphrase", "models")},
            "variant_counts": doc.get("variant_counts") or {},
            "judge_misses": {k: len(v) for k, v in fn.items() if isinstance(v, list)},
            "judge_false_flags": {k: len(v) for k, v in fp.items() if isinstance(v, list)},
            "stopped_reason": doc.get("stopped_reason"), "caveats": [str(c) for c in doc.get("caveats") or []],
            "round": 1 if doc.get("protocol") in (None, "r1") else 2,
            "judge_decision": get(doc, "policy_change_from_round_1", "decision_round_2") or get(doc, "judge", "decision"),
            "policy_why": {str(k): str(w) for k, w in (get(doc, "policy_change_from_round_1", "why") or {}).items()},
            "rounds": crosscheck_rounds(doc), "mcnemar": crosscheck_mcnemar(doc),
            "secondary_judged": (_int(get(doc, "sets", "round1_variants_not_heldout", "judged")),
                                 _int(get(doc, "sets", "round1_variants_not_heldout", "rows")))}


# ------------------------------------------------------------------ the offline validation run
@functools.lru_cache(maxsize=4)
def repo_tests(root: str) -> tuple[str, ...] | None:
    """Test files of this root: its own git inventory, else its folders; None if the inventory cannot be read.

    An exported tree may live inside another checkout's ignored directory. A successful git command there inventories
    the ancestor checkout, not the exported tree, and can silently omit every test in it.
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        return None
    files = None
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root_path,
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if top.returncode == 0 and Path(top.stdout.strip()).resolve() == root_path:
            r = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "--", *TEST_ROOTS], cwd=root_path,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            if r.returncode == 0:
                files = r.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        pass
    if files is None:
        def unreadable(error: OSError) -> None:
            raise error

        files = []
        try:
            for folder, dirs, names in os.walk(root_path, onerror=unreadable):
                base = Path(folder)
                dirs[:] = [d for d in dirs if d not in {".venv", "__pycache__"}
                           and (base != root_path or d in TEST_ROOTS)]
                if base != root_path:
                    files.extend((base / name).relative_to(root_path).as_posix() for name in names)
        except OSError:
            return None
    return tuple(sorted({f for f in files if PurePosixPath(f).name.startswith("test_") and f.endswith(".py")}))


def tests_run_by(summary: dict) -> set[str] | None:
    """The repository-relative scripts a deploy/validate_abd.py summary.json ran (results[].command[1] in its cwd);
    None when the summary does not say where it ran."""
    root = summary.get("root")
    if not isinstance(root, str) or not root:
        return None
    P = PureWindowsPath if re.match(r"^[A-Za-z]:[\\/]", root) else PurePosixPath
    out = set()
    for r in summary.get("results") or []:
        cmd, cwd = (r.get("command"), r.get("cwd")) if isinstance(r, dict) else (None, None)
        if isinstance(cmd, list) and len(cmd) > 1 and isinstance(cmd[1], str) and isinstance(cwd, str):
            try:
                out.add((P(cwd) / cmd[1]).relative_to(P(root)).as_posix())
            except ValueError:
                continue
    return out


def tests_not_run(summary: dict, root: Path = REPO) -> list[str] | None:
    """Test files not executed by the run; None when the run or this tree's inventory cannot be determined."""
    ran = tests_run_by(summary)
    inventory = repo_tests(str(root)) if ran is not None else None
    return None if inventory is None else [t for t in inventory if t not in ran]


def suite_passed(doc: dict) -> bool:
    return doc.get("passed") is True and doc.get("exit_code") == 0


def validation_view(root: Path = REPO, data: Path | None = None) -> dict | None:
    """The offline validation run for the page: the frozen data/validation.json, else the newest run under
    release/validation_abd/ that passed (the newest failed one only when none passed). A failed run is reported as
    FAIL, never as a pass. The commit is named only when the run recorded one."""
    snaps = frozen(FROZEN_VALIDATION, data)
    if snaps:
        s = snaps[0]
        cands = [{"doc": s["doc"], "meta": s["frozen"], "source": frozen_source(s["path"], s["frozen"], root),
                  "run_dir": str(s["frozen"].get("source_dir") or "n/a")}]
    else:
        cands = [{"doc": d, "meta": {}, "source": display_path(p, root), "run_dir": display_path(p.parent, root)}
                 for p in Path(root).glob(VALIDATION_GLOB) if (d := read_json(p)) is not None and isinstance(d.get("results"), list)]
    if not cands:
        return None
    passed = [c for c in cands if suite_passed(c["doc"])]
    pick = max(passed or cands, key=lambda c: (str(c["doc"].get("completed_utc") or ""), c["run_dir"]))
    doc, meta = pick["doc"], pick["meta"]
    head = meta.get("git_head") or get(doc, "git", "head") or doc.get("git_head")
    head = head if isinstance(head, str) and re.fullmatch(r"[0-9a-f]{7,40}", head) else None
    results = [r for r in doc.get("results") or [] if isinstance(r, dict)]
    failed = [PurePosixPath(str(get(r, "command", 1) or "?").replace("\\", "/")).name for r in results if r.get("passed") is not True]
    not_run = meta["not_covered"] if isinstance(meta.get("not_covered"), list) else tests_not_run(doc, root)
    ok = suite_passed(doc)
    why = None if ok else (
        "every test process passed; the run is marked FAIL because tracked source files changed while it ran"
        if not failed and doc.get("sources_unchanged_during_run") is False else
        f"failed: {', '.join(failed)}" if failed else "the run did not record a pass")
    return {"result": "PASS" if ok else "FAIL", "git_head": head, "run_dir": pick["run_dir"],
            "label": f"offline validation of commit {head[:12]}" if head else f"offline validation run {pick['run_dir']}",
            "unittest_cases": _int(doc.get("unittest_cases")), "test_processes": _int(doc.get("test_processes")),
            "sources_unchanged": doc.get("sources_unchanged_during_run"), "completed_utc": doc.get("completed_utc"),
            "why": why, "not_covered": not_run, "source": pick["source"], "candidates": len(cands)}


def seconds(x) -> str:
    v = _num(x)
    return "n/a" if v is None else f"{v:.2f} s"


def interval(x, fmt=seconds) -> str:
    return f"[{fmt(x[0])}, {fmt(x[1])}]" if isinstance(x, list) and len(x) == 2 and all(_num(v) is not None for v in x) else "n/a"


TPS_HEADER = "Completion tokens/s*"
TPS_NOTE = ("* Completion tokens per second of HTTP call wall time: includes network and prompt processing; not a decode "
            "speed.")


def success_cell(ok: int | None, n: int | None) -> str:
    """'4/5 (Wilson 95% [37.6%, 96.4%])': successes of the completed cases, the interval on that same denominator."""
    ci = wilson(ok, n) if ok is not None and n else None
    return "n/a" if ci is None else f"{ok}/{n} (Wilson 95% [{pct(ci[0])}, {pct(ci[1])}])"


def tf_bench_view(doc: dict) -> dict:
    """The Token Factory benchmark's results.json (scripts/bench_tf_handover.py) as display rows. Any missing key reads
    n/a; a dry run is flagged so its numbers are never shown as measurements. caveats: one line per model whose replies
    were cut off at max_tokens (failure class truncated), with the run's max_tokens and extra request body."""
    rows, caveats = [], []
    max_tokens, extra = _int(get(doc, "pipeline", "max_tokens")), get(doc, "pipeline", "extra_body")
    for model, m in (doc.get("per_model") or {}).items():
        if not isinstance(m, dict):
            continue
        ok, done = _int(get(m, "success", "count")), _int(m.get("n_completed"))
        planned, aborted = _int(m.get("n_planned")), _int(m.get("n_aborted"))
        fails = {str(k): v for k, v in m["failures"].items() if _int(v)} if isinstance(m.get("failures"), dict) else None
        valid, proposed = _int(get(m, "citation_validity", "valid")), _int(get(m, "citation_validity", "proposed"))
        decisions = get(m, "gate", "decisions")
        tps = _num(get(m, "completion_tokens_per_s", "aggregate"))
        tph = _num(get(m, "tokens_per_handover", "mean"))
        rows.append({
            "Model": str(model),
            "Success (of completed)": success_cell(ok, done),
            "Completed / planned": (f"{done}/{planned}" if done is not None and planned is not None else "n/a")
                                   + (f", {aborted} aborted" if aborted is not None else ", aborted n/a"),
            "Failures": "n/a" if fails is None else ", ".join(f"{k} {v}" for k, v in sorted(fails.items())) or "none",
            "Handover p50 / p95": f"{seconds(get(m, 'e2e_latency_s', 'p50'))} / {seconds(get(m, 'e2e_latency_s', 'p95'))}",
            "p50 95% CI": interval(get(m, "e2e_latency_s", "p50_ci95")),
            "Call p50 / p95": f"{seconds(get(m, 'call_latency_s', 'p50'))} / {seconds(get(m, 'call_latency_s', 'p95'))}",
            TPS_HEADER: "n/a" if tps is None else f"{tps:.1f}",
            "Tokens per handover": "n/a" if tph is None else f"{tph:.0f}",
            "Facts passing grounding check": f"{valid}/{proposed}" if valid is not None and proposed else "n/a",
            "Gate decisions": ", ".join(f"{k} {v}" for k, v in decisions.items()) if isinstance(decisions, dict) and decisions else "n/a",
            "TTFT p50": seconds(get(m, "ttft_s", "p50")),
            "Calls / retries": f"{get(m, 'http', 'calls') if _int(get(m, 'http', 'calls')) is not None else 'n/a'} / "
                               f"{get(m, 'http', 'retries') if _int(get(m, 'http', 'retries')) is not None else 'n/a'}",
        })
        cut = _int((fails or {}).get("truncated")) or 0
        if cut:
            body = json.dumps(extra) if isinstance(extra, dict) else "n/a"
            caveats.append(f"{model}: {cut} of {done if done is not None else 'n/a'} completed handovers hit "
                           f"max_tokens={max_tokens if max_tokens is not None else 'n/a'} (the reply was cut off and counts "
                           f"as a failure); thinking/extra_body = {body}"
                           + (" (none sent: the endpoint's default)." if extra == {} else "."))
    stopped = doc.get("stopped_reason")
    return {"dry_run": doc.get("dry_run") is not False, "created": doc.get("created_utc"),
            "host": get(doc, "endpoint", "host"), "transport": get(doc, "endpoint", "transport"),
            "git_head": (get(doc, "git", "head") or "")[:12] or None, "cases": len(doc.get("case_ids") or []),
            "repeats": doc.get("repeats"), "schema_version": doc.get("schema_version"),
            "stopped_reason": str(stopped) if stopped else None, "max_tokens": max_tokens,
            "extra_body": extra if isinstance(extra, dict) else None, "rows": rows, "caveats": caveats}


def redteam_view(doc: dict, before: dict | None = None) -> dict:
    """The red-team results.json (scripts/redteam_safety.py) as display values; missing keys read n/a. Each gap is
    placed on its product path (TARGET_PATH). closed_gaps: the run's gaps_closed, plus, when an earlier run is given,
    its open gaps that this run now stops as expected."""
    s = doc.get("summary") or {}

    def frac(summary, k_key, n_key, *where):
        k, n = _int(get(summary, *where, k_key)), _int(get(summary, *where, n_key))
        return ratio(k, n) if k is not None and n else "n/a"

    def recall(summary) -> dict:
        return {"block_recall": frac(summary, "stopped", "attacks", "block_recall"),
                "block_recall_excluding_known_gaps": frac(summary, "stopped", "attacks", "block_recall_excluding_known_gaps"),
                "false_block_rate": frac(summary, "blocked", "controls", "false_block_rate")}
    gaps = [g for g in (s.get("known_gaps") or []) if isinstance(g, dict)]
    rows = {str(r.get("id")): r for r in (doc.get("cases") or []) if isinstance(r, dict)}
    open_ids = {str(g.get("id")) for g in gaps if g.get("status") in OPEN_GAP}
    closed = {str(i): get(rows, str(i), "target") for i in (s.get("gaps_closed") or [])}
    bs = (before or {}).get("summary") or {}
    for g in (bs.get("known_gaps") or []) if before else []:
        gid = str(g.get("id")) if isinstance(g, dict) else None
        if gid and g.get("status") in OPEN_GAP and gid not in open_ids and get(rows, gid, "match") is True:
            closed[gid] = g.get("target") or get(rows, gid, "target")
    open_by_path: dict[str, list[str]] = {}
    for g in gaps:
        if g.get("status") in OPEN_GAP:
            open_by_path.setdefault(TARGET_PATH.get(g.get("target"), "other"), []).append(f"{g.get('id')} ({g.get('target')})")
    return {"utc": get(doc, "run", "utc"), "scope": get(doc, "run", "scope"),
            "cases": s.get("cases"), "attacks": s.get("attacks"), "controls": s.get("controls"), **recall(s),
            "known_gaps": [{"Case": str(g.get("id")), "Category": str(g.get("category")), "Target": str(g.get("target")),
                            "Path": TARGET_PATH.get(g.get("target"), "other"), "Expected": str(g.get("expected")),
                            "Actual": str(g.get("actual")), "Status": str(g.get("status"))} for g in gaps],
            "closed_gaps": [{"Case": i, "Target": str(t), "Path": TARGET_PATH.get(t, "other")} for i, t in sorted(closed.items())],
            "open_gaps_by_path": open_by_path,
            "before": None if before is None else {"utc": get(before, "run", "utc"), **recall(bs)},
            "regressions": list(s.get("regressions") or []), "errors": list(s.get("errors") or [])}
