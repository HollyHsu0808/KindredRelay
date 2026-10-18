# Verify KindredRelay's results yourself

Every number we publish should be checkable by someone who is not on the team and does not trust our scripts or our AI assistant. This page says how, what each check proves, and what cannot be checked from outside.

You need a clone of the repository (https://github.com/HollyHsu0808/KindredRelay) and Python 3.13. **No API key, no model, no GPU and no network** are needed for sections 1–4.

## 1. Third-party execution: CI

**CI run: [[CI_URL]]**: GitHub Actions, `ubuntu-latest`, no secrets. The workflow is `.github/workflows/validate.yml`. **Status at writing: not yet run on GitHub.** The repository had no remote yet; the steps were run locally instead (see the end of this section).

On every push and pull request it:

1. installs the release lock `deploy/requirements-release.lock` minus the speech and torch stack (torch, triton, openai-whisper, numba, llvmlite, tiktoken, more-itertools, sympy, mpmath, networkx), because no offline test imports them, then runs `pip check`;
2. runs `python deploy/validate_abd.py --out release/validation_abd/ci-<run id>`: the deterministic engine/UI suite. Its verdict is the last line, `RESULT: PASS|FAIL`, and the exit code;
3. runs `python scripts/redteam_safety.py`: the offline red team on the current code (no model);
4. runs `python scripts/bench_tf_handover.py --dry-run ...`: the benchmark harness against its scripted fake endpoint (this proves the harness runs; it is **not** a measurement);
5. runs `python scripts/verify_claims.py` (section 2) and `python scripts/check_hazard_log.py` (section 3);
6. runs the tests that `validate_abd.py` does not run: `scripts/test_verify_claims.py`, `scripts/test_check_hazard_log.py`, `scripts/test_redteam_safety.py`;
7. uploads every output as the artifact `offline-validation-<run id>`.

Local simulation, 2026-10-17 at about 23:40 UTC, Windows, the project's Python 3.13.6 `.venv`: steps 3–6 ran and exited 0, except `verify_claims.py`, which exited 1 on the two SOURCES.md findings listed in section 2. `verify_claims.py`, `check_hazard_log.py` and their tests were run with `python -I -S` (no site-packages), which shows they need nothing outside the standard library. Not simulated: the dependency install (installing packages was out of scope for that session) and step 2 (run separately by the team).

## 2. Recompute the published numbers from the raw records

```bash
python scripts/verify_claims.py --out verify_claims.json      # exit 0 = no mismatch; add --strict to fail on warnings
```

It reads every result folder under `release/benchmarks/` and the Scorecard snapshot `handoff_day1/ui/pages/shell/data/validation.json`, and writes one row per check:

| Check | What it proves | Fails on |
|---|---|---|
| `hash` | the input or artifact a result names (records, results, preregistration, variant file, story, cases) is byte-for-byte the file in the repository | a frozen artifact (anything under `release/`, or a dated variant file) that changed. A code file changed since the run is reported as `changed_since_run`, a warning: the result describes the code as it was then |
| `recompute` | the headline numbers of each `results.json`, recomputed from that run's own `records.jsonl` (or per-case rows) with **its own small aggregation**, not the producing script's summary code: success counts, failure classes, latency p50/p95/mean/min/max, tokens, grounding (citation) counts and rejection reasons, gate decisions, HTTP calls and retries, red-team block/false-block/held-out counts, cross-check recall, false blocks, unverified rate and the acceptance verdict, agreement Jaccards (own fact grouping), capacity outputs, load-test levels and throughput, the validation snapshot's totals | any recorded value that differs from the recomputation. Bootstrap intervals are not recomputed (they depend on the producer's resampling) |
| `claim` | each row of `submission/SOURCES.md` against the file it cites: `key` = value must equal the JSON value; a cited `path:line` must exist and hold the quoted words and the row's numbers | a value that differs, a missing file, key or line, a quotation that is not verbatim, or a cited file outside the repository. A number that no cited source holds is `unconfirmed` (a warning) |

Folders that are not there yet, or still being written (no `results.json`), are listed as `skip` with a reason; they are never counted as a pass.

**Result on the team's machine (2026-10-17, about 23:45 UTC; SOURCES.md Q01).** No recomputation mismatch. Two `claim` mismatches in `SOURCES.md`. **C01** puts "rules OR Gemma judge" in quotation marks where `scripts/crosscheck_judge.py:8` says "rules OR judge". **R08** cites a raw file in a session scratchpad outside the repository; the same bytes are now in `release/benchmarks/redteam_before_20261017T122640Z/results.json` (SOURCES.md R10). There were also warnings: `unconfirmed` rows, whose numbers are derived (e.g. 17 falls = 12 flagged + 5 missed) or come from a key the row does not cite, and code files `changed_since_run`. The CI artifact is authoritative for the commit it ran on.

**Check it without our script.** These standard-library lines recompute the published benchmark figures (SOURCES.md B04–B15) from the raw records:

```python
import json, statistics
path = "release/benchmarks/tf_bench_20261017T213905Z/records.jsonl"
final = {}
for line in open(path, encoding="utf-8"):
    r = json.loads(line)
    if r.get("type") == "case" and r["status"] != "aborted":
        final[(r["model"], r["case_id"], r["repeat"])] = r      # the last completed record of each case counts
for model in sorted({m for m, _, _ in final}):
    done = [r for (m, _, _), r in final.items() if m == model]
    ok = [r for r in done if r["status"] == "ok"]
    q = statistics.quantiles([r["e2e_s"] for r in ok], n=100, method="inclusive")
    valid = sum(r["citations_valid"] for r in ok if r["facts_proposed"])
    proposed = sum(r["facts_proposed"] for r in ok)
    print(f"{model}: {len(ok)}/{len(done)} ok, p50 {q[49]:.4f} s, p95 {q[94]:.4f} s, grounding {valid}/{proposed}")
```

Output when we ran it: `DeepSeek-V4-Flash: 36/36 ok, p50 6.1544 s, p95 15.6161 s, grounding 135/141` and `Gemma-4-31B-IT: 36/36 ok, p50 16.6555 s, p95 51.4022 s, grounding 117/136`.

## 3. Re-run the deterministic checks yourself

```bash
pip install -r requirements.txt                                   # the page's own four pins; or the CI's filtered lock
python deploy/validate_abd.py --out release/validation_abd/mine   # --out must not exist; last line RESULT: PASS|FAIL
python scripts/redteam_safety.py --out redteam_mine               # offline red team on the code you have
python scripts/check_hazard_log.py                                # every citation in submission/HAZARD_LOG.md resolves
python scripts/bench_tf_handover.py --dry-run --models A,B --cases 3 --out dry_mine   # harness only, fake endpoint
```

`redteam_safety.py` runs the guardrails on the code in your checkout, so its numbers can differ from the published run (`release/benchmarks/redteam_20261017T140024Z/`) if the code changed since. Its `results.json` records the sha256 of each guardrail module, and `verify_claims.py` reports which ones changed (`changed_since_run`).

## 4. Was the acceptance rule written before the results?

The cross-model check (`release/benchmarks/crosscheck_20261017T221103Z/`) wrote its acceptance rule to `preregistration.json` before any judge call:

- `preregistration.json` → `created_utc` = 2026-10-17T22:25:08.544Z. It also holds the sha256 of the paraphrased variant file it froze (`scripts/crosscheck_variants_20261017T222507Z.json`, `efffedaa…`).
- `records.jsonl`: the judge invocation started at 22:25:27.979Z; the first judge HTTP request (`type` http, `purpose` judge) at 22:25:28.710Z; the last at about 23:02:42Z.
- `results.json` records the preregistration's own sha256 and the variant file's. `verify_claims.py` checks both against the files, and checks that `created_utc` precedes the earliest judge request.
- The rule then **failed**: `acceptance.result` = FAIL (benign false-block rate 0.5778 against a 0.05 limit), so the judge stays shadow-only. A preregistration that its own result fails is some evidence that the rule was not fitted after the fact, but not proof.

**Limits.** These timestamps are written by our own scripts on our own machine. They show the files are consistent with each other, not that nobody edited them. Git cannot help for this run: the preregistration and the results enter the repository in the same commit, after the run, so commit order bounds them only from above. Once pushed, GitHub's push time shows the latest moment they existed. For a stronger guarantee in later runs, commit and push the preregistration (or publish its sha256) before the first model call. The held-out red-team cases ("written before the fixes they probe, not tuned on") are our own statement. The earlier run `redteam_before_20261017T122640Z` (40 cases) predates them, but these files do not prove when the HO-* cases were written.

## 5. The AMD Runtime page in the live app

In the live app ([[APP_URL]]), add an update on the family timeline (type a short note), then open the **AMD Runtime** page (`handoff_day1/ui/pages/shell/runtime_trace.py`). It shows:

- the configured endpoint host;
- a **This session** summary: calls per model and role, tokens (prompt / completion) and p50 latency, read from each call the app made for you;
- an **Each call, newest first** table: stage, model, host and the latency of the try that succeeded.

These are your own calls, recorded in memory for your session only. The page makes no GPU, precision or cost claim (SOURCES.md M09). It shows that the product calls the AMD Token Factory endpoint live. It does not show what hardware answered.

## 6. What cannot be verified independently

- **The hardware behind AMD Token Factory.** The endpoint does not reveal it; we claim no GPU model, precision or cost.
- **That the recorded live calls happened exactly as recorded.** `records.jsonl` files are written by our scripts; the provider gives no signed receipt. You can re-run the live benchmark with your own Token Factory key (`scripts/bench_tf_handover.py` without `--dry-run`; it makes paid calls). Expect different numbers: model outputs and network paths vary.
- **Model accuracy beyond these sets.** One fictional story with 12 updates; red-team cases written by us; cross-check variants written by a model; the "reference" extraction is a curated fixture, not clinical ground truth. Nothing here measures clinical correctness.
- **Clinical safety.** `submission/HAZARD_LOG.md` is modelled on ISO 14971 / DCB0129 practice but is not certified or reviewed by a clinical safety officer. Its severity and likelihood scores are our judgement.
- **Runs whose raw output is not in the repository.** The validation summary behind the Scorecard snapshot is under the git-ignored `release/validation_abd/`. `verify_claims.py` recomputes the snapshot's own totals but cannot check its source file's sha256 (reported as `skip`). The Kaggle verifier runs and the fall model's sealed test are reported in `release/KAGGLE_*.md` and `handoff_day1/logs/test_split_record.json` only.
