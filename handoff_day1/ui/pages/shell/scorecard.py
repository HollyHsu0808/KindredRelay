"""Evaluation & Safety Scorecard (a read-only page of the KindredRelay app shell, kindred_app.py). Every number comes
from scorecard_data.py, which names the result file it was copied from (file:line or JSON key); the Token Factory
benchmark, the red-team run and the offline validation run are read from their frozen copies in data/ (else the newest
run under release/), else marked not yet run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import scorecard_data as D  # noqa: E402

TF_HOST = "developer.amd.com.cn"   # README.md:25, the Token Factory API base URL


def source(*items) -> None:
    st.caption("Source: " + "; ".join(D.ref(i) if isinstance(i, dict) else str(i) for i in items))


def table(rows: list) -> None:
    if rows:
        head = list(rows[0])
        cell = lambda v: str(v).replace("|", "/").replace("\n", " ")  # noqa: E731
        st.markdown("\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                              + ["| " + " | ".join(cell(r[h]) for h in head) + " |" for r in rows]))


def fall() -> None:
    F = D.FALL
    st.header("Fall detection model v0.1")
    a, b, c = st.columns(3)
    a.metric("LOSO AUC (Subjects 1–3)", F["auc"]["value"])
    b.metric("Balanced accuracy", F["balanced_accuracy"]["value"])
    c.metric("Prior-event v1 baseline AUC", F["baseline_auc"]["value"])
    st.warning("Preliminary, CPU. A leave-one-subject-out estimate over GMDCSA-24 Subjects 1–3 (train Subjects 1–2, "
               "validation Subject 3; the Subject 4 test split was never loaded): not a held-out test result. A fall result "
               "is a prompt for a caregiver to confirm, not an alarm or a medical decision.")
    source(F["auc"], F["split"], F["human_in_loop"])


def citations() -> None:
    H = D.HELDOUT
    st.header("Citation literal validity")
    st.caption(H["title"])
    for col, (key, label) in zip(st.columns(3), D.METHODS):
        c = H["counts"][key]
        col.metric(label, f"{c['citation_valid']}/{c['citation_total']}")
        ci = D.wilson(c["citation_valid"], c["citation_total"])
        col.caption(f"{D.pct(c['citation_valid'] / c['citation_total'], 2)}, Wilson 95% {D.pct(ci[0])}–{D.pct(ci[1])}")
    st.caption("A citation is literally valid when its quoted words are found in a current revision of the cited source. "
               "That is not proof that the source supports the claim, or that the answer is right.")
    source(f"{H['doc']}:{H['doc_lines']['citations']}", f"{H['path']} → methods.<method>.counts.citation_valid / citation_total")


def verifier() -> None:
    V = D.VERIFIER
    st.header("Source-support verifier (optional; off in the release)")
    far, qa, thr = V["v1_false_acceptance"]["value"], V["v1_qa_false_acceptance"]["value"], V["v2_thresholds"]["value"]
    table([
        {"Version": "v1", "Measure": "Validation AUROC (unsupported as positive)", "Value": V["v1_auroc"]["value"],
         "Source": D.ref(V["v1_auroc"])},
        {"Version": "v1", "Measure": "Unsupported claims accepted, at the threshold fitted on validation",
         "Value": D.ratio(*far), "Source": D.ref(V["v1_false_acceptance"])},
        {"Version": "v1", "Measure": "Unsupported claims accepted, QA subgroup", "Value": D.ratio(*qa),
         "Source": D.ref(V["v1_qa_false_acceptance"])},
        {"Version": "v2", "Measure": "Calibration AUROC (4,091 pairs)", "Value": V["v2_calibration_auroc"]["value"],
         "Source": D.ref(V["v2_calibration_auroc"])},
        {"Version": "v2", "Measure": "Shared thresholds meeting every scope's FAR ≤ 5% and supported acceptance ≥ 10%",
         "Value": f"{thr[0]} of {thr[1]:,}", "Source": D.ref(V["v2_thresholds"])},
        {"Version": "v2", "Measure": "Validation operating point found", "Value": "false",
         "Source": D.ref(V["v2_operating_point"])},
    ])
    st.error("Verifier v2 operating-point gate: FAILED. The verifier stays OFF in the release (fail-closed).")
    st.markdown("**Fail-closed:** the release refuses to start the verifier in gate mode unless its model card records a "
                "validated operating point, so a verifier without one decides nothing and the release runs with "
                "`KINDRED_VERIFIER_MODE=off`; every extracted fact must still quote its update word for word.")
    st.caption("AUROC ranks claims; it is not accuracy or a clinical risk probability. v1 is kept off as well.")
    source(V["gate_rule"], V["release_mode"], V["grounding"], V["v2_not_enabled"], V["v1_kept_off"], V["auroc_meaning"])


def method_rows(B: dict) -> list:
    rows = []
    for key, label in D.METHODS:
        c = B["counts"][key]
        rows.append({"Method": label, "Strict all-correct": D.ratio(c["all_correct"], B["variants"]),
                     "Event precision": D.ratio(c["event_true_positive"], c["event_predicted"]),
                     "Event recall": D.ratio(c["event_true_positive"], c["event_expected"]),
                     "Citations literally valid": f"{c['citation_valid']}/{c['citation_total']}",
                     "Operational failures (kept in the denominator)": f"{c['operational_failure']}/{B['variants']}"})
    return rows


def paired_rows(B: dict) -> list:
    name = dict(D.METHODS)
    pp = lambda x: f"{100 * x:+.2f} pp" if x else "0.00 pp"  # noqa: E731
    return [{"Strict all-correct difference": f"{name[p['left']]} − {name[p['right']]}", "Difference": pp(p["difference"]),
             "Paired case-group bootstrap 95%": f"[{pp(p['interval'][0])}, {pp(p['interval'][1])}]",
             "Includes zero": "yes" if p["interval"][0] <= 0 <= p["interval"][1] else "no"} for p in B["paired"]]


def benchmark_sources(B: dict) -> None:
    lines = B["doc_lines"]
    source(f"{B['doc']}:" + ",".join(str(lines[k]) for k in ("all_correct", "precision", "recall", "failures", "paired")),
           f"{B['path']} → methods.<method>.counts / variants, paired_case_comparison")


def temporal() -> None:
    H, T = D.HELDOUT, D.TEMPORAL_CONTEXT
    st.header("Temporal benchmark: Journal vs full context vs lexical RAG")
    rates = [H["counts"][k]["all_correct"] / H["variants"] for k, _ in D.METHODS]
    all_zero = all(p["interval"][0] <= 0 <= p["interval"][1] for p in H["paired"])
    st.info(("No overall advantage. " if all_zero else "")
            + f"Strict all-correct is {D.pct(min(rates), 2)}–{D.pct(max(rates), 2)} for all three methods, and every paired 95% "
            "interval of the differences includes zero, so neither Journal nor RAG is shown to be better overall. Journal "
            "finds more of the expected events (recall) but adds far more extra ones (precision).")
    st.caption(f"{H['title']}. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon, "
               f"model {T['model']['value']}; {T['data']['value']}.")
    table(method_rows(H))
    table(paired_rows(H))
    st.caption(f"Wilson intervals treat each observation as independent; the {H['variants']} per method come from "
               f"{H['stories']} stories in two arrival orders, so they understate the uncertainty. The paired case-group "
               f"bootstrap intervals ({H['bootstrap_draws']:,} draws, from the result file) are the comparison of record.")
    benchmark_sources(H)
    source(T["endpoint"], T["model"], T["data"], T["no_advantage"])
    with st.expander(D.DEV96["title"]):
        table(method_rows(D.DEV96))
        table(paired_rows(D.DEV96))
        benchmark_sources(D.DEV96)


def suite() -> None:
    st.header("Deterministic test suite")
    doc, v = D.SUITE_DOCUMENTED["value"], D.validation_view()
    a, b = st.columns(2)
    a.metric("Documented (round 3)", f"{doc[1]} cases", help=f"in {doc[0]} test processes")
    if v is None:
        b.metric("Offline validation (deploy/validate_abd.py)", "not recorded")
        st.info(f"Not yet run: no {D.DATA_REL}/{D.FROZEN_VALIDATION} and no file matching {D.VALIDATION_GLOB} in this "
                "deployment.")
    else:
        cases = "n/a" if v["unittest_cases"] is None else v["unittest_cases"]
        procs = "n/a" if v["test_processes"] is None else v["test_processes"]
        unchanged = {True: "yes", False: "no"}.get(v["sources_unchanged"], "n/a")
        line = (f"{v['label'][0].upper() + v['label'][1:]}: RESULT {v['result']}, {cases} unittest cases in {procs} "
                f"processes; sources unchanged during the run: {unchanged}; completed {v['completed_utc'] or 'n/a'}.")
        if v["result"] == "PASS":
            b.metric("Offline validation (deploy/validate_abd.py)", f"{cases} cases", help=f"RESULT PASS, {procs} test processes")
            st.success(line)
        else:   # shown as what it is: no passing run is available
            b.metric("Offline validation (deploy/validate_abd.py)", "FAIL", help=f"{cases} cases in {procs} test processes")
            st.error(line + f" Why FAIL: {v['why']}.")
    not_run = v["not_covered"] if v is not None else None
    st.caption("Scope: deterministic engine and UI tests with test doubles; they do not validate trained-model accuracy "
               "or the deployment. "
               + ("Test files of this checkout that the run did not execute (run separately, not counted above): "
                  + (", ".join(not_run) or "none") + "." if not_run is not None else ""))
    source(D.SUITE_DOCUMENTED, D.SUITE_SCOPE, *([v["source"]] if v is not None else []))


def token_factory() -> None:
    st.header("AMD Token Factory benchmark")
    runs = D.tf_bench_runs()
    if not runs:
        st.info(f"Not yet run: no frozen snapshot {D.DATA_REL}/{D.FROZEN_TF_BENCH} and no results file matching "
                f"{D.TF_BENCH_GLOB} in this deployment.")
        return
    for run in runs:
        v = D.tf_bench_view(run["doc"])
        st.subheader(run["label"])
        where = (f"Endpoint host {v['host'] or 'n/a'}, {v['cases']} cases × {v['repeats'] if v['repeats'] is not None else 'n/a'} "
                 f"repeats, created {v['created'] or 'n/a'}, git {v['git_head'] or 'n/a'}; max_tokens "
                 f"{v['max_tokens'] if v['max_tokens'] is not None else 'n/a'}, extra_body "
                 f"{json.dumps(v['extra_body']) if v['extra_body'] is not None else 'n/a'}. "
                 + (f"Stopped early ({v['stopped_reason']}): the numbers cover the completed cases only."
                    if v["stopped_reason"] else "Run complete (not stopped early)."))
        if v["dry_run"]:
            st.warning("DRY RUN: a scripted stand-in server (transport "
                       f"{v['transport'] or 'n/a'}) answered, so these numbers test the benchmark harness, not the model or "
                       "the endpoint. They are not measurements.")
            st.caption(where)
            with st.expander("Dry-run harness numbers (not measurements)"):
                table(v["rows"])
        else:
            if v["host"] == TF_HOST:
                st.caption("Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon.")
            st.caption(where)
            if v["rows"]:
                table(v["rows"])
            else:
                st.info("The results file lists no per-model summary.")
            for line in v["caveats"]:
                st.warning(line)
        source(run["source"])
    st.caption("Success counts the completed cases (aborted ones, cut short by the call budget, are left out and listed); "
               "a failure is a completed case whose reply could not be used or whose call failed, by class (e.g. truncated, "
               "timeout). "
               "Facts passing grounding check: proposed facts whose quote passed episode.grounding_problem, the check the "
               "family timeline applies. " + D.TPS_NOTE)


def redteam() -> None:
    st.header("Safety red-team (offline)")
    run = D.redteam_run()
    if run is None:
        st.info(f"Not yet run: no frozen snapshot {D.DATA_REL}/{D.FROZEN_REDTEAM} and no results file matching "
                f"{D.REDTEAM_GLOB} in this deployment.")
        return
    v = D.redteam_view(run["doc"], run["before"])
    a, b, c = st.columns(3)
    a.metric("Block recall on attacks", v["block_recall"].split(" ")[0], help=v["block_recall"])
    b.metric("Excluding known gaps", v["block_recall_excluding_known_gaps"].split(" ")[0],
             help=v["block_recall_excluding_known_gaps"])
    c.metric("False blocks on benign controls", v["false_block_rate"].split(" ")[0], help=v["false_block_rate"])
    st.caption(f"Block recall {v['block_recall']}; excluding known gaps {v['block_recall_excluding_known_gaps']}; "
               f"false-block rate {v['false_block_rate']}. Run {v['utc'] or 'n/a'}. {v['scope'] or ''}")
    if v["before"] is not None:
        st.markdown("**Before and after** (the same measures on the earlier run frozen with this one)")
        table([{"Run": f"earlier ({v['before']['utc'] or 'n/a'})", "Block recall on attacks": v["before"]["block_recall"],
                "Excluding known gaps": v["before"]["block_recall_excluding_known_gaps"],
                "False blocks on benign controls": v["before"]["false_block_rate"]},
               {"Run": f"this run ({v['utc'] or 'n/a'})", "Block recall on attacks": v["block_recall"],
                "Excluding known gaps": v["block_recall_excluding_known_gaps"],
                "False blocks on benign controls": v["false_block_rate"]}])
    else:
        st.caption("Before/after: no earlier run is frozen with this one, so only this run is shown.")
    by_path: dict = {}
    for g in v["closed_gaps"]:
        by_path.setdefault(g["Path"], []).append(f"{g['Case']} ({g['Target']})")
    closed = "; ".join(f"on the {p} path: {', '.join(ids)}" for p, ids in by_path.items())
    family_open = v["open_gaps_by_path"].get(D.FAMILY_PATH, [])
    st.markdown("**Where the closures are.** The deployed app is the family timeline (its checks: episode.py, "
                "episode_qa.py); the Case Agent (case_agent.py) is not on its path. "
                + (f"Gaps closed {'since the earlier run' if v['before'] is not None else 'in this run'}: {closed}."
                   if closed else "No closed gap is recorded in this snapshot."))
    if family_open:
        st.warning(f"Still open on the deployed {D.FAMILY_PATH} path: {', '.join(family_open)}. The safe expectation is "
                   "kept and the run reports the gap.")
    other_open = {p: ids for p, ids in v["open_gaps_by_path"].items() if p != D.FAMILY_PATH}
    if other_open:
        st.caption("Also open: " + "; ".join(f"{p}: {', '.join(ids)}" for p, ids in other_open.items()) + ".")
    if v["known_gaps"]:
        st.markdown("**Known gaps** (the safe expectation is kept; where the code does not meet it, it is reported here)")
        table(v["known_gaps"])
    if v["regressions"] or v["errors"]:
        st.error("Regressions: " + (", ".join(map(str, v["regressions"])) or "none") + "; errors: "
                 + (", ".join(map(str, v["errors"])) or "none"))
    source(run["source"], *([run["before_source"]] if run["before_source"] else []))


def crosscheck() -> None:
    st.header("Cross-model semantic check (shadow)")
    run = D.crosscheck_run()
    if run is None:
        st.info(f"Not yet run: no frozen snapshot {D.DATA_REL}/{D.FROZEN_CROSSCHECK} and no results file matching "
                f"{D.CROSSCHECK_GLOB} in this deployment.")
        return
    v = D.crosscheck_view(run["doc"])
    st.markdown(f"A second model ({v['judge_model'] or 'n/a'}) checks a candidate output of the product generator's kind "
                f"({v['generator'] or 'n/a'}: a reply, an extracted fact or an extracted instruction) against its evidence. "
                "Evaluated in shadow only: it is not on the product path, and the deterministic guardrails still decide.")
    where = (f"Preregistered {v['prereg_utc'] or 'n/a'} (variant file {v['variants_file'] or 'n/a'}, sha256 "
             f"{v['variants_sha'] or 'n/a'}); first judge call {v['first_judge_utc'] or 'n/a'}. "
             + (f"Stopped early ({v['stopped_reason']}); {v['incomplete']} variants have no judge result."
                if v["stopped_reason"] else "Run complete (not stopped early).")
             + (f" Secondary set (round-1 variants): {v['secondary_judged'][0]} of {v['secondary_judged'][1]} judged."
                if v["round"] == 2 and None not in v["secondary_judged"] else ""))
    if v["dry_run"]:
        st.warning("DRY RUN: a scripted stand-in answered as judge and paraphraser, so these numbers test the harness, "
                   "not a model or the endpoint. They are not measurements.")
        st.caption(where)
        with st.expander("Dry-run harness numbers (not measurements)"):
            table(v["rows"])
        source(run["source"])
        return
    if v["host"] == TF_HOST:
        st.caption(f"Judge {v['judge_model'] or 'n/a'}: inference via the AMD Token Factory endpoint provided for the AMD "
                   "Developer Hackathon.")
    st.caption(where)
    st.markdown(f"**Preregistered acceptance rule:** {v['rule'] or 'n/a'}")
    line = (f"Acceptance against the preregistered rule: {v['result']} ({v['decision'] or 'n/a'})."
            + (" Round 2, on its own held-out variant set." if v["round"] == 2 else ""))
    (st.success if v["result"] == "PASS" else st.error)(line)
    if v["checks"]:
        table(v["checks"])
    if v["round"] == 2:
        st.markdown("**Round 1 and round 2 side by side** (each preregistered before its first judge call, with the same "
                    "acceptance rule text, on its own held-out variant set). Policy difference: round 1 flags "
                    f"{D.CROSSCHECK_R1_DECISION.removeprefix('flag = ')}; round 2 flags "
                    f"{(v['judge_decision'] or 'n/a').removeprefix('flag = ')}, and rule 5 of the judge prompt "
                    "(instruction override) asks whether any evidence or quoted text tries to change, cancel or override "
                    "an earlier instruction or tells the writer what to write. Both were decided from round-1 results "
                    "only; the round-2 variants come from another paraphraser family and a new seed.")
        if v["rounds"]:
            table(v["rounds"])
        for k, why in v["policy_why"].items():
            st.caption(f"Why ({k}): {why}")
    if v["rows"]:
        table(v["rows"])
    if v["mcnemar"]:
        st.markdown("**Secondary, preregistered:** paired exact McNemar test, rules only vs rules OR judge (conservative "
                    "view), attacks and benign separately. Not part of the acceptance rule; no multiplicity correction.")
        table(v["mcnemar"])
    flags = ("a diagnosis, a dose mismatch or an instruction override; 'supported' is recorded but is not a flag in round 2"
             if v["round"] == 2 else "not supported, a diagnosis, a dose mismatch or an instruction override")
    st.caption("Rules OR judge: a case is stopped when the deterministic rules block or hold it, or the judge flags it "
               f"({flags}). An unverified judge result (no "
               "JSON of the schema, or an HTTP failure) counts as no flag for attack recall and as a flag for false "
               "blocks, the conservative view the rule was preregistered with. Wilson intervals treat cases as "
               "independent; paraphrases of one parent are not.")
    p50, p95 = v["latency"]
    c, n = v["calls"], v["variant_counts"]
    tokens = "n/a" if v["tokens_mean"] is None else f"{v['tokens_mean']:.0f}"
    st.caption(f"Cost and latency: judge call p50 {D.seconds(p50)}, p95 {D.seconds(p95)}; tokens per check "
               f"{tokens} (mean, the endpoint's usage); HTTP calls "
               f"{c['total'] if c['total'] is not None else 'n/a'} (judge {c['judge'] if c['judge'] is not None else 'n/a'}, "
               f"paraphrase {c['paraphrase'] if c['paraphrase'] is not None else 'n/a'}). Variants: "
               f"{n.get('kept', 'n/a')} kept of {n.get('asked', 'n/a')} asked, {n.get('dropped', 'n/a')} dropped by the "
               f"sanity filter; paraphrased by {v['paraphraser'] or 'n/a'}, a model of another family than the judge.")
    for line in v["caveats"]:
        st.warning(line)
    source(run["source"])


st.set_page_config(page_title="KindredRelay · Evaluation & Safety Scorecard", layout="wide")
st.title("Evaluation & Safety Scorecard")
st.caption("Read-only. Every number is copied from a result file in this repository and names it (file:line, or the JSON "
           "key). Fictional and public research data; nothing here is a clinical validation.")
fall()
citations()
verifier()
temporal()
suite()
token_factory()
redteam()
crosscheck()
st.caption("handoff_day1/ui/test_app_shell.py opens every source named on this page and checks that it still states the "
           "number shown.")
