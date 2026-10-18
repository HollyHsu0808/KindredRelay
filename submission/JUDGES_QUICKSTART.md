# Judges' quickstart

KindredRelay turns a family caregiver's recordings, typed notes and photos of hospital papers into one shared family timeline where every fact quotes its source. It never diagnoses. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon. Everything below uses fictional data.

## 0. Verify it yourself in 5 minutes (offline, no key)

Each row is one engineering-depth item (IDs D01 to D19, index at the end of `submission/slides.md`). Every command runs from the repository root with the standard library or the pinned packages only: no network, no model call, no API key. On Windows use `.venv/Scripts/python.exe` in place of `python`. Commands with `--out` need a folder that does not exist yet. The expected outputs were produced on the team's machine on 2026-10-18 between 01:15 and 01:30 UTC unless the cell says otherwise.

| ID | What you check | Command | Expected output | Evidence <!-- depth:D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 D11 D12 D13 D14 D15 D16 D17 D18 D19 --> |
|---|---|---|---|---|
| D11 | Every published number, recomputed from the raw records and checked against the file it cites | `python -I -S scripts/verify_claims.py --quiet --out verify_claims.json` | last line `RESULT: PASS` (final pre-submission run: 578 checks pass, 0 mismatches, `RESULT: PASS`) | `submission/SOURCES.md`, `scripts/verify_claims.py` |
| D01 | The second benchmark run, straight from its results file | `python -c "import json;d=json.load(open('release/benchmarks/tf_bench_20261017T230311Z/results.json',encoding='utf-8'))['per_model'];print({m:(v['e2e_latency_s']['p50'],v['citation_validity']['rate']) for m,v in d.items()})"` | `{'DeepSeek-V4-Flash': (6.6325, 0.9627), 'Gemma-4-31B-IT': (22.7673, 0.8333)}` (median seconds, share of facts grounded) | `release/benchmarks/tf_bench_20261017T230311Z/` |
| D02 | Fact stability of run 2, recomputed from its records | `python scripts/analyze_bench_agreement.py release/benchmarks/tf_bench_20261017T230311Z --out agreement_check` | `majority-vote Jaccard 0.688 [0.51, 0.85]`; in `agreement_check/summary.md` Jaccard 0.854 (DeepSeek-V4-Flash) and 0.989 (Gemma-4-31B-IT); under a second | `release/benchmarks/agreement_20261017T232917Z/` |
| D03 | The rate limit, in the endpoint's own words | `python -c "import re;t=open('release/benchmarks/load_20261017T232951Z/rate_limit_breakdown.md',encoding='utf-8').read();print(re.search(r'maximum \d+ requests per minute[^.]*',t).group(0))"` | `maximum 20 requests per minute for this OneClick user` | `release/benchmarks/load_20261017T232951Z/` |
| D04 | The capacity model, rebuilt from the measured runs | `python scripts/capacity_model.py --out capacity_check` | `tokens per family per day 2,431, per month 72,930; capacity basis load test; busy hours per 1,000 families per day 1.98` (it reads the newest benchmark and load runs) | `release/benchmarks/capacity_20261017T233811Z/` |
| D05 | The AMD Runtime page | open the app, page **AMD Runtime** (without a key the app runs in replay mode and makes no model call, see section 2A, so there is nothing to list; the live app at [[APP_URL]] shows the calls) | per call: model, endpoint host `developer.amd.com.cn (AMD Token Factory)`, latency, tokens | `handoff_day1/ui/pages/shell/runtime_trace.py` |
| D06 | The red team (fixed attacks, deterministic guardrails) | `python scripts/redteam_safety.py --out redteam_check` | in `redteam_check/summary.md`: attacks stopped `49/54 (90.7%); excluding known gaps: 48/48`, false blocks `0/19`, held-out `2/7` (the final rerun of the shipped code; the published run of the 14:00 UTC code had 46/54, 0/19, held-out 1/7) | `release/benchmarks/redteam_final_20261018T024113Z/`, `release/benchmarks/redteam_20261017T140024Z/`, `release/benchmarks/redteam_before_20261017T122640Z/` |
| D07 | A fixed bug stays fixed (test written from the failing case) | `python handoff_day1/agent/test_plan_negation.py` | `Ran 11 tests` … `OK` | `handoff_day1/agent/test_plan_negation.py` |
| D09 | Metamorphic relations (no answer key needed) | `python scripts/metamorphic_eval.py --n 200 --out metamorphic_check` | `MR3: 0/200 violations` and `unknown signatures: none`, exit 0, about 10 s. MR1 depends on the code version: 62/200 in the published run, 38/200 after the plan-negation fix | `release/benchmarks/metamorphic_20261017T233944Z/` |
| D08 | The judge's paired McNemar p, recomputed from its discordant pairs | `python -c "import json;m=json.load(open('release/benchmarks/crosscheck_r2_20261017T235438Z/results.json',encoding='utf-8'))['sets']['variants']['mcnemar_rules_vs_rules_or_judge']['attack'];b,c=m['b_rules_only'],m['c_rules_or_judge_only'];print(b,c,m['p_exact'],2*0.5**(b+c))"` | `0 29 3.725290298461914e-09 3.725290298461914e-09` | `release/benchmarks/crosscheck_r2_20261017T235438Z/`, `release/benchmarks/crosscheck_20261017T221103Z/` |
| D19 | The acceptance rule was written before the first judge call | `python -c "import json;d='release/benchmarks/crosscheck_r2_20261017T235438Z/';print(json.load(open(d+'preregistration.json',encoding='utf-8'))['created_utc'],json.load(open(d+'results.json',encoding='utf-8'))['first_judge_http_request_utc'])"` | `2026-10-18T00:19:58.999+00:00 2026-10-18T00:20:06.623+00:00` (round 1: 22:25:08.544 before 22:25:28.710, SOURCES.md C05, C06) | `release/benchmarks/crosscheck_r2_20261017T235438Z/preregistration.json` |
| D10 | The PriMock57 protocol is the one preregistered | `python -c "import hashlib,json;p='research/primock_gold_v1/';print(json.load(open(p+'preregistration.json',encoding='utf-8'))['protocol_sha256']==hashlib.sha256(open(p+'PROTOCOL.md','rb').read()).hexdigest())"` | `True`; results: [[PENDING: PriMock57 final run folder and headline]] | `research/primock_gold_v1/` |
| D13 | Every hazard-log citation still points at its line | `python -I -S scripts/check_hazard_log.py --out hazard_check.json` | last line `RESULT: PASS` (after the DX-05 and PI-04 fixes: `hazards=12; citations checked=87`) | `submission/HAZARD_LOG.md` |
| D14 | What leaves the app, and the known privacy gaps | read section 0 of `submission/PRIVACY_THREAT_MODEL.md` | the fields sent to the endpoint and the open gaps, each with a file and line | `submission/PRIVACY_THREAT_MODEL.md` |
| D15 | The evidence verifier is off in the release image | `python -c "print([l.strip() for l in open('Dockerfile.release',encoding='utf-8') if 'VERIFIER_MODE' in l])"` | `['KINDRED_VERIFIER_MODE=off \\']` | `Dockerfile.release`, `deploy/serve.py` |
| D16 | The fall model's sealed test (not deployed) | `python -c "import json;r=json.load(open('handoff_day1/logs/test_split_record.json',encoding='utf-8'))['runs'];print([(x['test']['auc'],x['test']['at_model_threshold']['tp'],x['test']['at_model_threshold']['fn']) for x in r])"` | `[(0.85, 12, 5), (0.95, 6, 11)]` (v0.2, v0.1: AUC, falls flagged, falls missed) | `handoff_day1/logs/test_split_record.json` |
| D17 | The authoritative offline suite (longer than 5 minutes) | `python deploy/validate_abd.py --out release/validation_abd/<new-dir>` | last line `RESULT: PASS; unittest_cases=832; sources_unchanged=True` (41 test processes; final pre-submission run) | `handoff_day1/ui/pages/shell/data/validation.json` |
| D18 | A planted key never reaches an output, error text or argv | `python scripts/test_bench_tf_handover.py` | `Ran 31 tests` … `OK`, about 10 s | `scripts/test_bench_tf_handover.py:22` |
| D12 | The same checks in CI | read `.github/workflows/validate.yml` | steps: validate_abd, red team, benchmark dry run, verify_claims, check_hazard_log; run: [[CI_URL]] (not yet run on GitHub) | `.github/workflows/validate.yml` |

Coverage of these documents: `python scripts/check_depth_coverage.py --files submission/slides.md submission/SUBMISSION_TEXT.md submission/JUDGES_QUICKSTART.md` lists every ID per document and ends in `RESULT: PASS` (placeholders are listed as warnings). <!-- depth:D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 D11 D12 D13 D14 D15 D16 D17 D18 D19 -->

## 1. Open the app (2 minutes)

Live app: **[[APP_URL]]**. Three pages in the left navigation (`handoff_day1/ui/pages/shell/kindred_app.py:27-30`):

1. **Family timeline** (default). In the sidebar, press **Add this update** a few times to play the demo story (Elena, 82, fictional, after a fall and a hip fracture). Switch **Viewing as** to Mia (Melbourne) or David (Toronto) to see the same timeline in their time zone. Try the tiles:
   - **Ask about Elena** → tap *When is Elena going home?*, or type *Can she get out of bed on her own?* (the first line is always "Only the care team can decide…", followed by the care team's own sentences).
   - **Share news from the hospital** → type or record what a nurse said, or **📷 Photograph a paper** → **Use the sample photo**, read it, check each line, then **Add to the timeline**.
2. **AMD Runtime**: every model call your browser session made: stage, model, endpoint host (developer.amd.com.cn, marked "AMD Token Factory"), latency, prompt and completion tokens as the server reported them, and what our checks did with the reply. No GPU is claimed: the endpoint's hardware is not visible to the client.
3. **Evaluation & Safety Scorecard**: the evaluation results, each number with the file it came from.

Please use fictional content only: the Token Factory service keeps prompts and outputs for about 2 days and its terms say not to send personal health data (`release/evidence_en/DEV_README_EXCERPT.md:37`).

## 2. Run it locally

Requirements: Python 3.12 or 3.13, `ffmpeg` on PATH (for speech), the packages pinned in `requirements.txt` / `deploy/requirements-release.lock` (Streamlit 1.64.0, openai-whisper 20250625, CPU torch).

**A. Without any API key (replay mode).** The demo story's facts are replayed from their recorded extraction; questions use the deterministic answerer; the Scorecard reads the result files in `release/`.

```bash
streamlit run handoff_day1/ui/pages/shell/kindred_app.py
```

(`handoff_day1/ui/pages/shell/kindred_app.py:10`; with `CARERELAY_LLM_BASE_URL` and `CARERELAY_LLM_MODEL` unset the page runs without a model, `handoff_day1/ui/pages/1_Family_timeline.py:772-773`.)

**B. Live, on AMD Token Factory** (needs a Token Factory API key, kept in the environment only, never in a file):

```bash
export CARERELAY_LLM_BASE_URL=https://developer.amd.com.cn/radeon/api/v1
export CARERELAY_LLM_MODEL=DeepSeek-V4-Flash
export CARERELAY_PHOTO_MODEL=Gemma-4-31B-IT
export CARERELAY_LLM_GUIDED_JSON=0
read -rsp 'Token Factory API key: ' CARERELAY_LLM_API_KEY; echo; export CARERELAY_LLM_API_KEY
python deploy/serve.py        # validates the settings, then starts the three-page app on port 8501
```

Values from `deploy/release.env.example:1-9`; `deploy/serve.py:51-55` refuses to start without the four live settings and `:68-73` without Whisper and ffmpeg (set `CARERELAY_REQUIRE_ASR=0` to skip speech). Set `CARERELAY_PHOTO_MODEL` explicitly: `deploy/run_local.py:32-33` would default it to a different model.

**C. Container (as deployed):** `docker build -f Dockerfile.release -t kindredrelay .` from the repository root, then run it with the variables of `deploy/release.env.example` and `-p 8501:8501`. The image bakes in Whisper base.en on CPU and keeps the evidence verifier off (`Dockerfile.release:11-14,34`). We have not built this image on our own development machine (`release/evidence_en/DEPLOY_RC_20261018.md:25`); the hosted app at [[APP_URL]] is [[PENDING: deployment confirmation — host and build of the live app]].

## 3. Reproduce the evidence

Run from the repository root. Each command writes to a **new** folder (it refuses an existing one). On Windows use `.venv/Scripts/python.exe` in place of `python`.

| What | Command | Network / key | Checked this session |
|---|---|---|---|
| Offline unit suites (the repository's authoritative check) | `python deploy/validate_abd.py --out release/validation_abd/<new-dir>`; verdict = last line `RESULT: PASS\|FAIL` and the exit code | none | Not re-run; the recorded run is PASS, 699 tests in 29 processes (SOURCES.md S01) |
| Safety red team (73 fixed cases, deterministic) | `python scripts/redteam_safety.py --out release/benchmarks/redteam_<UTC>` | none | Yes: exit 0; 49/54 attacks stopped, 48/48 excluding known gaps, 0/19 false blocks, held-out 2/7, identical to the final recorded run `release/benchmarks/redteam_final_20261018T024113Z/` (the 14:00 UTC run, before the DX-05 and PI-04 fixes, had 46/54, 46/46, 0/19, 1/7) |
| Handover benchmark, plumbing only (scripted fake endpoint) | `python scripts/bench_tf_handover.py --dry-run --models DeepSeek-V4-Flash,Gemma-4-31B-IT --cases 3 --repeats 1 --out release/benchmarks/tf_bench_dryrun_<UTC>` | none | Yes: exit 0, 6/6 cases (dry-run numbers are not measurements) |
| Handover benchmark, live (the recorded run's settings) | `python scripts/bench_tf_handover.py --models DeepSeek-V4-Flash,Gemma-4-31B-IT --cases 12 --repeats 3 --ttft-probe 5 --max-calls 400 --api-key-file <file holding only the key> --out release/benchmarks/tf_bench_<UTC>` | AMD Token Factory, key | Not re-run (about 83 calls); argv from `release/benchmarks/tf_bench_20261017T213905Z/results.json` → `argv` |
| Fact stability of a benchmark run | `python scripts/analyze_bench_agreement.py release/benchmarks/tf_bench_20261017T213905Z --out release/benchmarks/agreement_<UTC>` | none | Yes: exit 0; majority-vote Jaccard 0.756 [0.58, 0.92], as recorded |
| Cross-model judge, plumbing only | `python scripts/crosscheck_judge.py generate --dry-run --out <OUT>` then `python scripts/crosscheck_judge.py eval --dry-run --out <OUT>` | none | Not run (documented in `scripts/crosscheck_judge.py:30`) |

## 4. Where each number lives

| Claim in the submission | Number | File (→ JSON key or line) |
|---|---|---|
| Updates processed, DeepSeek-V4-Flash / Gemma-4-31B-IT | 36/36 / 36/36 | `release/benchmarks/tf_bench_20261017T213905Z/results.json` → `per_model.<model>.success.count` |
| Median time per update [95% CI] | 6.15 s [5.73, 9.06] / 16.66 s [14.34, 23.25] | same → `per_model.<model>.e2e_latency_s.p50`, `.p50_ci95` |
| p95 time per update | 15.62 s / 51.40 s | same → `per_model.<model>.e2e_latency_s.p95` |
| Tokens per update (mean) | 1,219 / 1,330 | same → `per_model.<model>.tokens_per_handover.mean` |
| Proposed facts passing the grounding check | 135/141 (95.7%) / 117/136 (86.0%) | same → `per_model.<model>.citation_validity` |
| Same facts across 3 repeats (mean Jaccard) | 0.900 / 1.000; cross-model 0.756 | `release/benchmarks/agreement_20261017T221124Z/summary.md:11-12,31` |
| Red team: attacks stopped; excluding known gaps; false blocks; held-out | 49/54; 48/48; 0/19; 2/7 | `release/benchmarks/redteam_final_20261018T024113Z/results.json` → `summary.block_recall`, `.block_recall_excluding_known_gaps`, `.false_block_rate`, `.heldout` |
| Red team before → after fixes, same 32 attacks | 23/32 → 30/32 | `release/evidence_en/OVERNIGHT_REPORT_20261018.md:59`; derivation in `submission/SOURCES.md` R08–R09 |
| Verifier v2 gate | 0 of 4,048 thresholds valid → off | `release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md:39`; `Dockerfile.release:14` |
| Fall model, preliminary LOSO | AUC 0.975 ± 0.011 | `release/evidence_en/DEV_README_EXCERPT.md:16` |
| Temporal benchmark, held-out strict | 10/80, 11/80, 13/80 | `release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md:151` |
| Cross-model judge, rounds 1 and 2 (preregistered rule: recall Wilson lower ≥ 0.80, benign false blocks ≤ 5%, unverified ≤ 5%) | round 1: 127/134 attacks, 26/45 false blocks, FAIL; round 2: 141/143 (Wilson lower 0.9504), 14/52 false blocks vs 9/52 for rules alone, FAIL; McNemar attacks b 0, c 29, p 3.73e-09 | `release/benchmarks/crosscheck_20261017T221103Z/results.json` → `acceptance`; `release/benchmarks/crosscheck_r2_20261017T235438Z/results.json` → `acceptance`, `sets.variants.mcnemar_rules_vs_rules_or_judge` |
| Benchmark run 2 | DeepSeek-V4-Flash 35/36, 6.63 s, 96.3%; Gemma-4-31B-IT 36/36, 22.77 s, 83.3% | `release/benchmarks/tf_bench_20261017T230311Z/results.json` → `per_model.<model>.success.count`, `.e2e_latency_s.p50`, `.citation_validity.rate` |
| Fact stability, run 2 | Jaccard 0.854 / 0.989; cross-model 0.688; grounding acceptance 85.0% (stable) vs 85.7% (less stable) | `release/benchmarks/agreement_20261017T232917Z/summary.md:11-12,31,39-42` |
| Metamorphic testing | 6 relations × 200; invariance 0/200; 7 signatures closed; live polarity 2/20 | `release/benchmarks/metamorphic_20261017T233944Z/summary.md:5-12,69-78,129` |
| Capacity / load | 2,431 tokens per family per day, 1.98 busy hours per 1,000 families per day (assumptions labelled, no price) / 16.84 updates per minute at concurrency 4 (1 of 17 attempts rate-limited); 9.49 at concurrency 8 with 20 of 36 attempts rate-limited (20 requests per minute per user) | `release/benchmarks/capacity_20261017T233811Z/summary.md:46,52`; `release/benchmarks/load_20261017T232951Z/summary.md:13-14`, `rate_limit_breakdown.md:12` |
| PriMock57 external reference | recall 58.2% [54.0, 61.8], contradictions 6.0% [4.3, 7.8], weighted errors 0.682/note fact; kappa pending | `research/primock_gold_v1/`; final run folder `release/benchmarks/primock_gold_20261018T002738Z/` |

The full list, with every other number used: `submission/SOURCES.md`. Architecture with file references for every box: `submission/architecture.md`.

## 5. Limitations (read before judging)

- **Fictional data only; no clinical validation.** The demo story and the benchmark story are fictional; the temporal benchmark used LLM-written stories with no clinical review (`release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md:177`).
- **The evidence verifier is off.** v2 found no threshold meeting every scope's false-acceptance ≤ 5% with ≥ 10% acceptance; v1 (AUROC 0.9800) let 9/131 unsupported QA claims through. The release refuses gate mode without a validated operating point.
- **Rule-based guardrails generalise poorly**: 2/7 held-out attacks stopped; the 5 misses (HO-01, HO-02, HO-05, HO-06, HO-07) are on the Case Agent answer path. DX-05 (a diagnosis label paraphrasing a real symptom quote) and PI-04 (an instruction injected inside a recording), open on the deployed family-timeline path in the 14:00 UTC run, are closed in the final rerun; a condition outside the diagnosis list and an imperative the patterns do not know can still pass (`submission/HAZARD_LOG.md` HZ-03, HZ-04).
- **Timeline reasoning shows no advantage** over full-context or lexical-RAG baselines on 240 held-out runs (all intervals include 0); event precision of the journal method was 23%.
- **The fall detector is a separate prototype**, not in the deployed app; on the sealed test v0.1 flagged 6/17 falls and v0.2 12/17 with 5/20 false prompts (`handoff_day1/logs/test_split_record.json`). A fall result is only ever a prompt to confirm.
- **Speech and photo reading make mistakes** (a smoke test turned "two tablets" into "a few tablets"), which is why a person ticks every line with a number before it is added.
- **Latency and availability depend on the shared endpoint**: Gemma-4-31B-IT p95 51.40 s; an earlier run had 2/36 Gemma timeouts and a third model (Qwen3.8-27B) completed only 3/36.
- **Data handling**: a real deployment needs a dedicated endpoint under a data-processing agreement (`release/evidence_en/DEV_README_EXCERPT.md:37`).
- Numbers are engineering measurements on one story (12 updates × 3 repeats per model); latency includes the network from our machine to the endpoint.
