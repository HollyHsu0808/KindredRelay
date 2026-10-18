# Sources for every number in `submission/`

Every number in the submission files is listed here with the file it was copied from (path:line, or path → JSON key). Rows marked **derived** were computed from the named file with the command shown; rows marked **secondary** are external figures as summarised in our own research note and not re-checked against the primary source by us (see the submission to-do list, in the private development repository). Anything not in this table must not be added to the submission.

Paths are relative to the repository root. `BENCH` = `release/benchmarks/tf_bench_20261017T213905Z/results.json` (created 2026-10-17T21:58:32Z; `git.head` 07b8008, `git.dirty` true). `REDTEAM` = `release/benchmarks/redteam_20261017T140024Z/results.json` (run 2026-10-17T14:00:26Z).

**Line numbers** were checked against the files as they stood at about 22:35 UTC on 2026-10-17. Other sessions were editing `handoff_day1/ui/pages/1_Family_timeline.py`, `handoff_day1/ui/pages/shell/{runtime_trace,scorecard,scorecard_data}.py`, `deploy/validate_abd.py`, `scripts/bench_tf_handover.py` and `scripts/crosscheck_judge.py` while this was written; re-check `path:line` citations into those files before the final submission.

## AMD Token Factory handover benchmark (12 story updates × 3 repeats per model)

| ID | Claim | Number | Source |
|---|---|---|---|
| B01 | Endpoint host of the benchmark | developer.amd.com.cn | BENCH → `endpoint.host` |
| B02 | Cases and repeats | 12 updates of one story × 3 repeats = 36 per model | BENCH → `case_ids` (12 entries), `repeats` = 3, `per_model.*.n_planned` = 36 |
| B03 | What one case is | one story update added through the page's real pipeline | BENCH → `pipeline.case_unit`, `pipeline.entry_point` |
| B04 | DeepSeek-V4-Flash success | 36/36 (Wilson 95% 0.90–1.00) | BENCH → `per_model.DeepSeek-V4-Flash.success.count` = 36, `.n_completed` = 36, `.success.wilson95` = [0.9036, 1.0] |
| B05 | DeepSeek-V4-Flash end-to-end median per update | 6.15 s (95% CI 5.73–9.06 s) | BENCH → `per_model.DeepSeek-V4-Flash.e2e_latency_s.p50` = 6.1544, `.p50_ci95` = [5.7299, 9.0628] |
| B06 | DeepSeek-V4-Flash p95 | 15.62 s | BENCH → `per_model.DeepSeek-V4-Flash.e2e_latency_s.p95` = 15.6161 |
| B07 | DeepSeek-V4-Flash slowest case | 53.34 s | BENCH → `per_model.DeepSeek-V4-Flash.e2e_latency_s.max` = 53.3436 |
| B08 | DeepSeek-V4-Flash tokens per handover (prompt + completion, endpoint `usage`) | mean 1,219 (prompt 1,049, completion 170) | BENCH → `per_model.DeepSeek-V4-Flash.tokens_per_handover.mean` = 1218.8, `.prompt_mean` = 1048.8, `.completion_mean` = 169.9 |
| B09 | DeepSeek-V4-Flash proposed facts passing the grounding check | 135/141 = 95.7% (95% CI 91.6–99.3%) | BENCH → `per_model.DeepSeek-V4-Flash.citation_validity.valid` = 135, `.proposed` = 141, `.rate` = 0.9574, `.ci95` = [0.9156, 0.9928] |
| B10 | DeepSeek-V4-Flash grounding rejections | 4 quote < 3 words; 1 condition word not in quote; 1 missing hours | BENCH → `per_model.DeepSeek-V4-Flash.citation_validity.rejection_reasons` |
| B11 | Gemma-4-31B-IT success | 36/36 | BENCH → `per_model.Gemma-4-31B-IT.success.count` = 36, `.n_completed` = 36 |
| B12 | Gemma-4-31B-IT end-to-end median | 16.66 s (95% CI 14.34–23.25 s) | BENCH → `per_model.Gemma-4-31B-IT.e2e_latency_s.p50` = 16.6555, `.p50_ci95` = [14.3439, 23.2471] |
| B13 | Gemma-4-31B-IT p95 | 51.40 s | BENCH → `per_model.Gemma-4-31B-IT.e2e_latency_s.p95` = 51.4022 |
| B14 | Gemma-4-31B-IT tokens per handover | mean 1,330 | BENCH → `per_model.Gemma-4-31B-IT.tokens_per_handover.mean` = 1329.6 |
| B15 | Gemma-4-31B-IT proposed facts passing the grounding check | 117/136 = 86.0% (95% CI 80.3–91.1%) | BENCH → `per_model.Gemma-4-31B-IT.citation_validity.valid` = 117, `.proposed` = 136, `.rate` = 0.8603, `.ci95` = [0.8027, 0.9113] |
| B16 | Gemma-4-31B-IT top grounding rejection | 12 × "missing what" | BENCH → `per_model.Gemma-4-31B-IT.citation_validity.rejection_reasons` |
| B17 | Time to first token (5 streaming probes, short prompt) | DeepSeek 1.51 s, Gemma 1.47 s | BENCH → `per_model.DeepSeek-V4-Flash.ttft_s.p50` = 1.5051, `per_model.Gemma-4-31B-IT.ttft_s.p50` = 1.4735 |
| B18 | HTTP calls and retries | 83 calls, 1 retry (one HTTP 429) | BENCH → `http_calls.total` = 83, `http_calls.retries` = 1, `per_model.DeepSeek-V4-Flash.http.statuses` = {200: 41, 429: 1} |
| B19 | Evidence verifier during the benchmark | off for all 36 + 36 cases | BENCH → `per_model.*.gate.decisions` = {off: 36} |
| B20 | Accepted facts per handover | DeepSeek 3.75, Gemma 3.25 | BENCH → `per_model.DeepSeek-V4-Flash.facts_per_handover.accepted_mean` = 3.75, `per_model.Gemma-4-31B-IT.facts_per_handover.accepted_mean` = 3.25 |
| B21 | Required AMD wording and no-GPU statement | "Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon … no specific GPU is claimed" | `release/benchmarks/tf_bench_20261017T213905Z/summary.md:3` |
| B22 | Latency caveat | latency includes the network path from the client machine to the endpoint | `release/benchmarks/tf_bench_20261017T213905Z/summary.md:3` |
| B23 | Earlier three-model run (same harness) | Gemma 34/36 (2 timeouts); Qwen3.8-27B 3/36 (16 timeouts, 17 cut off at max_tokens) | `release/benchmarks/tf_bench_20261017T124039Z/results.json` → `per_model.Gemma-4-31B-IT.failures` = {timeout: 2}, `per_model.Qwen3.8-27B.success.count` = 3, `.failures` = {timeout: 16, truncated: 17} |

## Fact stability across repeats (offline analysis of the benchmark above; no model calls)

`AGREE` = `release/benchmarks/agreement_20261017T221124Z/` (analysis of `tf_bench_20261017T213905Z`, 72 completed cases; script `scripts/analyze_bench_agreement.py`). The reference is the demo story's recorded extraction (a curated fixture), not clinical ground truth.

| ID | Claim | Number | Source |
|---|---|---|---|
| A01 | DeepSeek-V4-Flash: same facts back across 3 repeats of one update (mean pairwise Jaccard) | 0.900 [95% CI 0.79, 1.00] over 12 updates; 40 of 47 fact keys (85.1%) in all 3 repeats | AGREE `summary.md:11`; `results.json` → `numbers.within_model.DeepSeek-V4-Flash.mean_pairwise_jaccard` = 0.9005, `.keys_by_repeat_count.3` = 40 |
| A02 | Gemma-4-31B-IT: same measure | 1.000 [1.00, 1.00]; 37 of 37 keys in all 3 repeats | AGREE `summary.md:12`; `results.json` → `numbers.within_model.Gemma-4-31B-IT.mean_pairwise_jaccard` = 1.0 |
| A03 | DeepSeek vs Gemma majority-vote fact sets (mean Jaccard over 12 updates) | 0.756 [0.58, 0.92]; per update 0.000 to 1.000 | AGREE `summary.md:31`; `results.json` → `numbers.cross_model["DeepSeek-V4-Flash vs Gemma-4-31B-IT"].mean_jaccard` = 0.7556 |
| A04 | Facts seen in all 3 repeats that match the recorded extraction | 61/77 (79.2%) [Wilson 0.69, 0.87] | AGREE `summary.md:41` |
| A05 | Facts seen in only 1–2 of 3 repeats that match it | 2/7 (28.6%) [0.08, 0.64] | AGREE `summary.md:44` |
| A06 | Facts both models produced that match it, vs facts only one model produced | 56/68 (82.3%) [0.72, 0.90] vs 7/16 (43.8%) [0.23, 0.67] | AGREE `summary.md:45-46` |
| A07 | Caveats | one fictional story, 12 updates; the less stable buckets are small; grounding-check acceptance could not be related to stability (rejected facts not recorded) | AGREE `summary.md:58`, `## Caveats` section |
| A08 | Rerun with rejected facts recorded | — | [[PENDING: agreement rerun — new `release/benchmarks/agreement_*` directory]] |

## Cross-model semantic check (shadow, evaluation only)

| ID | Claim | Number | Source |
|---|---|---|---|
| C01 | What it measures | whether "rules OR judge" (judge = Gemma-4-31B-IT) stops more paraphrased red-team attacks than the rules alone, against an acceptance rule written before the first judge call; not wired into the product | `scripts/crosscheck_judge.py:2-9` |
| C02 | Judge and endpoint | Gemma-4-31B-IT, inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon | `scripts/crosscheck_judge.py:2-3` |
| C03 | Paraphrase generator (a model of another family than the judge) | DeepSeek-V4.1-Flash, else GLM-5.3-Flash | `scripts/crosscheck_judge.py:12-13` |
| C04 | Results | — | [[PENDING: crosscheck — `release/benchmarks/crosscheck_20261017T221103Z/` had only `records.jsonl` (in progress) at writing time]] |
| C05 | Preregistration written before the judge run (used in `VERIFY_INDEPENDENTLY.md` §4) | 22:25:08.544 UTC on 2026-10-17 | `release/benchmarks/crosscheck_20261017T221103Z/preregistration.json` → `created_utc` = 2026-10-17T22:25:08.544+00:00, `written_before_any_judge_call` = true, `variants_sha256` = efffedaab4b9dc79327404aa09f6c3cb00b72ac46810299c9f9db2f03db4c514 |
| C06 | First judge HTTP request, judge invocation start, last judge call (`VERIFY_INDEPENDENTLY.md` §4) | 22:25:28.710Z; 22:25:27.979Z; about 23:02:42Z | **derived** from `release/benchmarks/crosscheck_20261017T221103Z/records.jsonl`: earliest `ts` of the records with `type` http and `purpose` judge; `ts` of the second `invocation` record; `results.json` → `last_judge_call_utc`. The ordering against C05 is recomputed by `scripts/verify_claims.py` (check "preregistration.created_utc precedes the first judge call") |
| C07 | The judge against its preregistered rule (`HAZARD_LOG.md` HZ-11, `VERIFY_INDEPENDENTLY.md` §4) | FAIL: benign false-block rate 0.5778 against a limit of 0.05 (recall Wilson lower bound 0.8961 against 0.80 passed); stays shadow-only | `release/benchmarks/crosscheck_20261017T221103Z/results.json` → `acceptance.result` = FAIL, `acceptance.checks.benign_false_block_rate.value` = 0.5778, `.threshold` = 0.05, `acceptance.checks.recall_wilson_lower.value` = 0.8961, `.threshold` = 0.8, `acceptance.decision` = stays shadow-only |

## Capacity and load (not yet run)

| ID | Claim | Number | Source |
|---|---|---|---|
| L01 | Capacity and cost model | — | [[PENDING: capacity — `release/benchmarks/capacity_*`]] |
| L02 | Concurrency load test | — | [[PENDING: load — `release/benchmarks/load_*`]] |

## Safety red team (offline, deterministic, no model)

| ID | Claim | Number | Source |
|---|---|---|---|
| R01 | Cases | 73 (54 attacks, 19 benign controls, 8 marked known gap) | REDTEAM → `summary.cases` = 73, `.attacks` = 54, `.controls` = 19, `.known_gap_cases` = 8; `release/benchmarks/redteam_20261017T140024Z/summary.md:5` |
| R02 | Attacks stopped (block or hold) | 46/54 = 85.2% | REDTEAM → `summary.block_recall` = {stopped 46, attacks 54, rate 0.8519} |
| R03 | Attacks stopped, excluding the 8 documented known gaps | 46/46 | REDTEAM → `summary.block_recall_excluding_known_gaps` |
| R04 | Benign controls wrongly blocked | 0/19 | REDTEAM → `summary.false_block_rate` = {blocked 0, controls 19} |
| R05 | Held-out attacks (written before the fixes, never tuned on) stopped | 1/7 = 14.3% | REDTEAM → `summary.heldout` = {attacks 7, stopped 1, rate 0.1429}; `summary.md:8` |
| R06 | Open gaps on the deployed family-timeline path | DX-05 (a diagnosis label paraphrasing a real symptom quote), PI-04 (an instruction injected inside a recording) | `release/benchmarks/redteam_20261017T140024Z/summary.md:28-29`; path mapping `handoff_day1/ui/pages/shell/scorecard_data.py:163-165` (`episode_update` → family timeline) |
| R07 | Run scope | "deterministic guardrail decisions on fixed adversarial inputs; not model accuracy, not clinical correctness" | REDTEAM → `run.scope` |
| R08 | Before the guardrail fixes | 23/32 attacks stopped (first 40-case set: 32 attacks, 8 controls) | `release/benchmarks/redteam_before_20261017T122640Z/results.json` → `summary.block_recall` = {stopped 23, attacks 32}, run 2026-10-17T12:26:40Z (see R10 for provenance) |
| R09 | After the fixes, on the same 32 attacks | 30/32 (open: DX-05, PI-04); the same 8 controls 0/8 blocked | **derived** from REDTEAM → `cases[]` (`actual_outcome` in block/hold) restricted to the 32 attack ids of the R08 run. Command: `.venv/Scripts/python.exe -c` reading both `results.json` files, set of `id` where `category != "benign_control"` in the R08 file, counted in REDTEAM where `actual_outcome in ("block","hold")` → 30; not stopped: DX-05, PI-04 (run this session) |
| R10 | The R08 raw run, now in the repository | 40 cases, 32 attacks, 8 controls; 23/32 stopped; the same bytes as the scratchpad file R08 cites | `release/benchmarks/redteam_before_20261017T122640Z/results.json` → `summary.cases` = 40, `.attacks` = 32, `.controls` = 8, `summary.block_recall` = {stopped 23, attacks 32}; both files had sha256 3d92ee55466bbc1b7ebb669bd5190369afa8b6aa2158e9c489980fa6f9489692 (`sha256sum`, 2026-10-17 about 23:20 UTC); on 2026-10-18 `scripts/redact_local_paths.py` replaced its local path (`run.cases_file`) and the file now has sha256 fad1b5202d3c34d4a5e11afda5db6a677e82a6da04b1998e55f176784b276ffc, the pair recorded in `release/REDACTIONS.json` (numbers unchanged: values_sha256, checked by `scripts/verify_claims.py`). R09 is recomputed from this file and REDTEAM by `scripts/verify_claims.py` |

## Source-support verifier (why it is off)

| ID | Claim | Number | Source |
|---|---|---|---|
| V01 | Verifier v1 validation AUROC (unsupported as positive) | 0.9800 | `release/evidence_en/KAGGLE_RESULT.md:14` |
| V02 | Verifier v1 false acceptance on the QA subgroup | 9/131 = 6.87% (above the 5% target) | `release/evidence_en/KAGGLE_RESULT.md:18,21` |
| V03 | Verifier v1 kept off on the site | off | `release/evidence_en/KAGGLE_RESULT.md:35` |
| V04 | Verifier v2 calibration AUROC | 0.961569 (4,091 pairs) | `release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md:26` |
| V05 | Verifier v2 weakest scope | RAGTruth / Summary AUROC 0.673214 | `release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md:32` |
| V06 | Verifier v2 operating-point gate | 0 of 4,048 candidate thresholds meet every scope's FAR ≤ 5% and supported acceptance ≥ 10% | `release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md:39` |
| V07 | Verifier v2 not enabled | "deployment acceptance did not pass; the v2 gate is not enabled in this round" | `release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md:3` |
| V08 | Release setting | `KINDRED_VERIFIER_MODE=off` | `Dockerfile.release:14`; `deploy/release.env.example:14` |
| V09 | Gate refused without a validated operating point | `validation_operating_point_found` must be `True` | `deploy/serve.py:42-43`; `handoff_day1/agent/evidence_gate.py:128-130` |
| V10 | AUROC is not accuracy or a clinical risk probability | — | `release/evidence_en/KAGGLE_VERIFIER_V2_RESULTS.md:22` |

## Fall detection model (separate module, not in the release image)

| ID | Claim | Number | Source |
|---|---|---|---|
| F01 | Pipeline and size | MediaPipe Pose → 12 pose features → GRU, 4,449 parameters | `release/evidence_en/DEV_README_EXCERPT.md:15` |
| F02 | Training split | GMDCSA-24: train Subjects 1–2, validation Subject 3; Subject 4 (test) not loaded in training | `release/evidence_en/DEV_README_EXCERPT.md:15` |
| F03 | Preliminary leave-one-subject-out estimate (CPU) | AUC 0.975 ± 0.011; balanced accuracy 0.903 ± 0.025; prior-event v1 baseline 0.656 | `release/evidence_en/DEV_README_EXCERPT.md:16`; also `handoff_day1/ui/pages/shell/scorecard_data.py:53-58` |
| F04 | A fall result is a prompt to confirm | "a prompt for a caregiver to confirm (human in the loop), not an autonomous alarm or a medical decision" | `release/evidence_en/DEV_README_EXCERPT.md:18` |
| F05 | Sealed test, opened once (GMDCSA-24 Subject 4, 2026-10-14), v0.2.0 | AUC 0.85; balanced accuracy 0.728; 12 of 17 falls flagged; 5 of 20 non-falls flagged | `handoff_day1/logs/test_split_record.json` → `runs[0].test.auc` = 0.85, `.at_model_threshold.balanced_acc` = 0.7279, `.tp` = 12, `.fn` = 5, `.fp` = 5, `.tn` = 15 |
| F06 | Same sealed test, v0.1.0 (the runner's default model) | AUC 0.95; balanced accuracy 0.677; 6 of 17 falls flagged; 0 of 20 non-falls flagged | `handoff_day1/logs/test_split_record.json` → `runs[1].test.auc` = 0.95, `.at_model_threshold.balanced_acc` = 0.6765, `.tp` = 6, `.fn` = 11, `.fp` = 0, `.tn` = 20; default model `handoff_day1/model/predict_fall.py:5` |
| F07 | Not packaged in the release image | no `handoff_day1/model/` COPY | `Dockerfile.release:35-41` |

## Temporal reasoning benchmark (journal vs full context vs lexical RAG)

| ID | Claim | Number | Source |
|---|---|---|---|
| T01 | Held-out strict all-correct | Journal 10/80, full context 11/80, lexical RAG 13/80 | `release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md:151` |
| T02 | No overall advantage | all paired story-bootstrap intervals include 0 | `release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md:164` |
| T03 | Journal event precision | 73/315 = 23.17% | `release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md:154` |
| T04 | Model and endpoint of that experiment | DeepSeek-V4-Flash alias on AMD Token Factory | `release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md:85,93` |
| T05 | Data | fictional English stories written by an LLM, no clinical review | `release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md:177` |
| T06 | Held-out size | 40 stories × 2 arrival orders × 3 methods = 240 | `release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md:16,145` |

## Deterministic test suite

| ID | Claim | Number | Source |
|---|---|---|---|
| S01 | Frozen offline validation run used by the Scorecard | PASS: 832 unittest cases in 41 test processes, exit 0, sources unchanged during the run | `handoff_day1/ui/pages/shell/data/validation.json` → `doc.passed` = true, `doc.exit_code` = 0, `doc.unittest_cases` = 832, `doc.test_processes` = 41, `doc.sources_unchanged_during_run` = true (frozen copy of `release/validation_abd/final2-20261018T024113Z/summary.json`, a git-ignored local run folder in the private development repository); also `release/evidence_en/DEPLOY_RC_20261018.md:3` |
| S02 | Scope of that suite | deterministic engine/UI tests with test doubles; not model accuracy or deployment | `deploy/validate_abd.py:104` |

## Speech, photo and models in the release

| ID | Claim | Number / value | Source |
|---|---|---|---|
| M01 | Text model | DeepSeek-V4-Flash | `deploy/release.env.example:2` |
| M02 | Photo model | Gemma-4-31B-IT | `deploy/release.env.example:4` |
| M03 | Endpoint base URL | `https://developer.amd.com.cn/radeon/api/v1` | `deploy/release.env.example:1`; `release/evidence_en/DEV_README_EXCERPT.md:25` |
| M04 | Speech model and where it runs | Whisper base.en on the app server CPU | `deploy/release.env.example:9`; `Dockerfile.release:34`; `deploy/serve.py:3` |
| M05 | Whisper smoke test misheard a dose | "two tablets" came out as "a few tablets" (8.98 s PriMock57 clip) | `release/evidence_en/ASR_SMOKE.md:5,9` |
| M06 | Photo reading run on Token Factory (2026-10-15, Gemma-4-31B-IT, fictional discharge list) | 57/57 words; all 5 medicines with the right status | `release/evidence_en/DEV_README_EXCERPT.md:40` |
| M07 | Token Factory data handling | prompts and outputs kept about 2 days; terms say not to send sensitive personal or health data; only fictional cases and public PriMock57 were sent | `release/evidence_en/DEV_README_EXCERPT.md:37` |
| M08 | Questions are answered by sentence choice only | the model chooses sentences, writes no answer text | `release/evidence_en/DEV_README_EXCERPT.md:41`; `handoff_day1/agent/README.md:32` |
| M09 | The AMD Runtime page makes no GPU, precision or cost claim | — | `handoff_day1/ui/pages/shell/runtime_trace.py:250` |

## Product, demo story and hackathon facts

| ID | Claim | Value | Source |
|---|---|---|---|
| P01 | Product name and tagline | KindredRelay — "One place to understand what's happening, and be there for each other." | `handoff_day1/agent/timeline_html.py:21-22` |
| P02 | Demo story | "Elena's fall and hip fracture": Elena Novak, 82 (fictional); Anna (daughter, primary caregiver, London), David (son, Toronto), Mia (granddaughter, Melbourne); 12 updates | `handoff_day1/care_cases/episode_hip_fracture.json` → `title`, `patient`, `members`, `updates` (12 entries) |
| P03 | Health & Wellbeing track one-liner | "Make a part of the patient journey safer, clearer, or easier." | `release/evidence_en/HACKATHON_RULES_BRIEFING.md:35` |
| P04 | AMD rule | "The AMD component must be part of the working product shown to the judges." | `release/evidence_en/HACKATHON_RULES_BRIEFING.md:26` |
| P05 | Judging criteria (no weights published) | Application of Technology, Presentation, Business Value, Originality | `release/evidence_en/HACKATHON_RULES_BRIEFING.md:49-53` |
| P06 | Submission items | title, short/long description, tags, cover image, video, slides, public GitHub repo, demo platform, application URL; "Clear explanation of the problem and intended user" | `release/evidence_en/HACKATHON_RULES_BRIEFING.md:40-44` |

## Business context (secondary: research-agent summary, not re-checked by us)

| ID | Claim | Number | Source |
|---|---|---|---|
| X01 | CARE Act: hospitals must notify and instruct family caregivers before discharge | 43 states + Washington DC (2023) | `release/evidence_en/RESEARCH_NOTES_20261016.md:56` (primary URL listed there) |
| X02 | Involving family in discharge planning and 90-day readmissions | −25% (meta-analysis of 15 randomised trials) | `release/evidence_en/RESEARCH_NOTES_20261016.md:58` |
| X03 | Inpatients who report receiving conflicting information at least sometimes | 23% (J Gen Intern Med 2023, 172 patients) | `release/evidence_en/RESEARCH_NOTES_20261016.md:49` |
| X04 | Patient-experience survey item on planning discharge with family | added from 2025 | `release/evidence_en/RESEARCH_NOTES_20261016.md:57` |
| X05 | Existing consumer apps in this space charge families | e.g. Family Care Relay, US$6.99 per month (US App Store) | `release/evidence_en/RESEARCH_NOTES_20261016.md:28` |
| X06 | The research note itself asks for re-checking | "the 23%, 47% and 31% for the video should be re-checked in person" | `release/evidence_en/RESEARCH_NOTES_20261016.md:63` |

## Independent verification and hazard log (`VERIFY_INDEPENDENTLY.md`, `HAZARD_LOG.md`)

| ID | Claim | Number | Source |
|---|---|---|---|
| Q01 | Recomputation on the team's machine (2026-10-17, about 23:45 UTC) | no recomputation mismatch; 2 claim mismatches in this file (C01, R08) | **derived**: output of `python scripts/verify_claims.py --out <file>` at that time; rerun it, or read the CI artifact `verify_claims.json` |
| Q02 | Hand recomputation of B04–B15 (`VERIFY_INDEPENDENTLY.md` §2) | DeepSeek 36/36, p50 6.1544 s, p95 15.6161 s, grounding 135/141; Gemma 36/36, p50 16.6555 s, p95 51.4022 s, grounding 117/136 | BENCH → `per_model.DeepSeek-V4-Flash.success.count` = 36, `.e2e_latency_s.p50` = 6.1544, `.e2e_latency_s.p95` = 15.6161, `.citation_validity.valid` = 135, `.citation_validity.proposed` = 141, `per_model.Gemma-4-31B-IT.success.count` = 36, `.e2e_latency_s.p50` = 16.6555, `.e2e_latency_s.p95` = 51.4022, `.citation_validity.valid` = 117, `.citation_validity.proposed` = 136 |
| H01 | Every figure in the hazard log | — | cited inline in `submission/HAZARD_LOG.md` (a line with its quoted words, a test name in its file, or a result key with its value); all checked by `python scripts/check_hazard_log.py` |

## Numbers deliberately not used

- The US$ cost of 18 Q&A calls in `handoff_day1/START_HERE.md:55` (in the private development repository): later records say the provider's cost unit is unknown and USD is "UNPRICED" (`release/evidence_en/ROUND3_ENGINEERING_AND_EVALUATION.md:135,170`; `release/evidence_en/KINDREDRELAY_COMPLETE_HANDOFF_20261017.md:147`). No cost figure is used anywhere in `submission/`.
- Any time saved for caregivers or clinicians: not measured. Where the submission talks about saved time it is labelled a hypothesis.
- Any GPU model name: the hardware behind the endpoint is not visible to the client (`release/benchmarks/tf_bench_20261017T213905Z/summary.md:3`).

## Privacy data flow and threat model (`PRIVACY_THREAT_MODEL.md`)

Line numbers checked at about 00:45 UTC on 2026-10-18. Citations into `handoff_day1/agent/episode.py` are kept out of this table because another session was editing that file (its lines moved twice in ten minutes); the threat model cites them by function name. Team-relayed terms (PV02, PV04) were not independently verified.

| ID | Claim | Number | Source |
|---|---|---|---|
| PV01 | Endpoint that receives patient text and photos | developer.amd.com.cn | `deploy/release.env.example:1` ("CARERELAY_LLM_BASE_URL=https://developer.amd.com.cn/radeon/api/v1") |
| PV02 | Token Factory terms (team-relayed): retention and allowed data | prompts and outputs kept about 2 days; trial and development only; no sensitive personal, health or financial data | `release/evidence_en/HACKATHON_RULES_BRIEFING.md:30` ("prompts and outputs are kept about 2 days") |
| PV03 | README: same retention, and only fictional or public data sent | about 2 days; fictional care cases and public PriMock57 only | `release/evidence_en/DEV_README_EXCERPT.md:37` ("the service keeps prompts and outputs for about 2 days") |
| PV04 | Organisers' answer that Token Factory meets the AMD rule (team-relayed, screenshot held by the team) | — | `release/evidence_en/HACKATHON_RULES_BRIEFING.md:29` ("using Token Factory meets the AMD prize eligibility") |
| PV05 | The call recorder keeps metadata only | no prompt, reply, image or key | `handoff_day1/agent/llm_client.py:25` ("Never the prompt, the reply, an image, the API key or the URL beyond its host.") |
| PV06 | Recorder size per browser session | newest 100 calls | `handoff_day1/ui/pages/shell/runtime_trace.py:23` ("MAX_CALLS = 100") |
| PV07 | Link token: random, stored only as a SHA-256 | 32 random bytes (256 bits) | `handoff_day1/ui/timeline_storage.py:164` ("secrets.token_urlsafe(32)"); `handoff_day1/ui/timeline_storage.py:37` ("hashlib.sha256(token.encode") |
| PV08 | No authentication, revocation or encryption at rest | none | `handoff_day1/ui/PERSISTENCE.md:25` ("There is no new account authentication, revocation screen or encrypted storage.") |
| PV09 | No retention limit on saved timelines | none | `handoff_day1/ui/PERSISTENCE.md:32-33` ("there is no automatic retention deletion policy") |
| PV10 | A family link is full access, and the identity is self-selected | — | `handoff_day1/ui/PERSISTENCE.md:22-24` ("Anyone with a family link can select another identity, issue invitations and restart the shared story.") |
| PV11 | Original audio and drafts are not saved | — | `handoff_day1/ui/PERSISTENCE.md:28-29` ("Drafts, original audio, model clients, callables and environment configuration are excluded.") |
| PV12 | Photos stay after their update is deleted | — | `handoff_day1/ui/PERSISTENCE.md:29-30` ("Original checked photos remain attached to source history even after a source is tombstoned.") |
| PV13 | Streamlit usage statistics off; upload size cap | 25 MB | `deploy/serve.py:61-62` ("gatherUsageStats") |
| PV14 | Observed Token Factory rate limit | 20 requests per minute; 20 of 36 attempts rejected at concurrency 8 | `release/benchmarks/load_20261017T232951Z/rate_limit_breakdown.md:12` ("maximum 20 requests per minute for this OneClick user") |
| PV15 | Name-swap metamorphic relation, live (acceptance check for planned pseudonymisation) | 4 of 10 updates (40.0%) changed vs 2 of 10 (20.0%) for a plain repeat | `release/benchmarks/metamorphic_20261017T233944Z/summary.md:130-131` ("Name swap: accepted fact set differs") |
| PV16 | Release state directory | /var/lib/kindredrelay | `Dockerfile.release:12` ("CARERELAY_STATE_DIR=/var/lib/kindredrelay") |
| PV17 | Speech recognition runs in the container, with the weights baked in | Whisper base.en on CPU | `Dockerfile.release:34` ("whisper.load_model('base.en', device='cpu'") |
| PV18 | In-app notice before a photo is sent | about 2 days; fictional papers only | `handoff_day1/ui/pages/1_Family_timeline.py:1333` ("The photo is sent to {host} to be read") |
| PV19 | In-app notice before a question is sent | — | `handoff_day1/ui/pages/1_Family_timeline.py:1137` ("Your question and the updates are sent to {host} to be answered") |
| PV20 | Lines removed from a photo draft are still saved | — | `handoff_day1/ui/pages/1_Family_timeline.py:1453-1454` ("removed_lines") |
| PV21 | Question prompt includes the asker's name and relation | — | `handoff_day1/agent/episode_qa.py:572` ("from {asker.get('name')}") |
| PV22 | Question length cap | 500 characters | `handoff_day1/agent/episode_qa.py:880` ("[:500]") |
| PV23 | Deleting an update appends a tombstone event; the original stays in the journal | — | `handoff_day1/agent/episode_events.py:140-146` ("def delete_update") |
| PV24 | The hazard log puts data protection out of scope | — | `submission/HAZARD_LOG.md:37` ("handled by policy") |
| PV25 | Relayed Health-track rules include sensitive-data handling (not checked on the official page) | — | `release/evidence_en/HACKATHON_RULES_BRIEFING.md:36` ("sensitive-data handling") |
| PV26 | Restart leaves the replaced text and photo bytes in the SQLite file; the raw token is not stored | old text: True; old photo: True; token in clear: False | **derived**: `.venv/Scripts/python.exe -I -S <scratchpad>/privacy/sqlite_residue.py <repo>` (2026-10-18 about 00:42 UTC, real `handoff_day1/ui/timeline_storage.py` on a temporary database; script in the session scratchpad). Superseded: re-run about 02:06 UTC after `PRAGMA secure_delete = ON` (`handoff_day1/ui/timeline_storage.py:75`): old text False, old photo False, token in clear False; test `handoff_day1/ui/test_timeline_storage_residue.py` |
| PV27 | Photo shrink removes EXIF, including GPS | output EXIF tags: none | **derived**: `.venv/Scripts/python.exe -I <scratchpad>/privacy/exif_check.py` (verbatim copy of `shrink()` from `handoff_day1/ui/pages/1_Family_timeline.py:926-939`, Pillow 12.3.0) |

## Engineering-depth items D01 to D19 (added 2026-10-18 about 01:30 UTC)

Rows for the numbers that `slides.md`, `SUBMISSION_TEXT.md` sections 3, 6 and 6a, and `JUDGES_QUICKSTART.md` section 0 added for the engineering-depth items (index of D01 to D19 at the end of `slides.md`). Line numbers checked at about 01:30 UTC on 2026-10-18. `[[PENDING ...]]` rows are filled before submission.

| ID | Claim | Number | Source |
|---|---|---|---|
| B24 | Second benchmark run (same harness and settings, created 2026-10-17T23:28:41Z): DeepSeek-V4-Flash success | 35/36 (1 timeout) | `release/benchmarks/tf_bench_20261017T230311Z/results.json` → `per_model.DeepSeek-V4-Flash.success.count` = 35, `per_model.DeepSeek-V4-Flash.n_completed` = 36, `per_model.DeepSeek-V4-Flash.failures` = {timeout: 1} |
| B25 | Run 2: DeepSeek-V4-Flash end-to-end median per update | 6.63 s (95% CI 5.58–7.94 s) | `release/benchmarks/tf_bench_20261017T230311Z/results.json` → `per_model.DeepSeek-V4-Flash.e2e_latency_s.p50` = 6.6325, `per_model.DeepSeek-V4-Flash.e2e_latency_s.p50_ci95` = [5.5819, 7.936] |
| B26 | Run 2: DeepSeek-V4-Flash proposed facts passing the grounding check | 129/134 = 96.3% | `release/benchmarks/tf_bench_20261017T230311Z/results.json` → `per_model.DeepSeek-V4-Flash.citation_validity.valid` = 129, `per_model.DeepSeek-V4-Flash.citation_validity.proposed` = 134, `per_model.DeepSeek-V4-Flash.citation_validity.rate` = 0.9627 |
| B27 | Run 2: Gemma-4-31B-IT success and end-to-end median | 36/36; 22.77 s (95% CI 13.31–29.08 s) | `release/benchmarks/tf_bench_20261017T230311Z/results.json` → `per_model.Gemma-4-31B-IT.success.count` = 36, `per_model.Gemma-4-31B-IT.e2e_latency_s.p50` = 22.7673, `per_model.Gemma-4-31B-IT.e2e_latency_s.p50_ci95` = [13.3098, 29.0771] |
| B28 | Run 2: Gemma-4-31B-IT proposed facts passing the grounding check | 115/138 = 83.3% | `release/benchmarks/tf_bench_20261017T230311Z/results.json` → `per_model.Gemma-4-31B-IT.citation_validity.valid` = 115, `per_model.Gemma-4-31B-IT.citation_validity.proposed` = 138, `per_model.Gemma-4-31B-IT.citation_validity.rate` = 0.8333 |
| B29 | Run 2: p95 per update and mean tokens per update (endpoint usage) | DeepSeek 16.53 s and 1,216 tokens; Gemma 82.36 s and 1,331 tokens | `release/benchmarks/tf_bench_20261017T230311Z/results.json` → `per_model.DeepSeek-V4-Flash.e2e_latency_s.p95` = 16.5276, `per_model.DeepSeek-V4-Flash.tokens_per_handover.mean` = 1215.5, `per_model.Gemma-4-31B-IT.e2e_latency_s.p95` = 82.3553, `per_model.Gemma-4-31B-IT.tokens_per_handover.mean` = 1331.1 |
| A09 | Run 2 (analysis of the second benchmark run): same accepted facts across 3 repeats, mean pairwise Jaccard | DeepSeek 0.854 [0.74, 0.95] over 11 updates; Gemma 0.989 [0.97, 1.00] over 12 | `release/benchmarks/agreement_20261017T232917Z/summary.md:11-12` |
| A10 | Run 2: the two models' majority-vote fact sets | 0.688 [0.51, 0.85] over 11 updates | `release/benchmarks/agreement_20261017T232917Z/summary.md:31` |
| A11 | Run 2: stability as a confidence signal (the run-1 split of A04 and A05 did not clearly replicate) | grounding check passed by every proposal of a key: 68/80 (85.0%) for keys in 3/3 repeats vs 6/7 (85.7%) in 1–2; recorded-reference match 57/70 (81.4%) vs 5/11 (45.5%) | `release/benchmarks/agreement_20261017T232917Z/summary.md:39-42,60-63` |
| L03 | Load test (DeepSeek-V4-Flash, 16 requests per level): highest throughput | 16.84 handovers per minute at concurrency 4 (16/16 succeeded) | `release/benchmarks/load_20261017T232951Z/summary.md:13` |
| L04 | Load test at concurrency 8 | 9.49 handovers per minute; 20/36 attempts rate-limited | `release/benchmarks/load_20261017T232951Z/summary.md:14` |
| L05 | Per-user rate limit stated in the endpoint's HTTP 429 replies | 20 requests per minute | `release/benchmarks/load_20261017T232951Z/rate_limit_breakdown.md:12` ("maximum 20 requests per minute for this OneClick user") |
| L06 | Capacity model (a model, not a measurement): tokens per family per day | 2,431 at an assumed 2 updates per family per day; tokens only, no price | `release/benchmarks/capacity_20261017T233811Z/summary.md:33,36,46` |
| L07 | Capacity model: busy endpoint-hours per 1,000 families per day | 1.98 (basis: the load test's 0.2807 handovers per second at concurrency 4) | `release/benchmarks/capacity_20261017T233811Z/summary.md:20-21,52` |
| C08 | Round 2 of the cross-model check against its preregistered rule (same rule text as round 1) | FAIL: benign false blocks 14/52 = 0.2692 against 0.05; recall Wilson lower bound 0.9504 against 0.80 passed; unverified 0.0; stays shadow-only | `release/benchmarks/crosscheck_r2_20261017T235438Z/results.json` → `acceptance.result` = FAIL, `acceptance.checks.benign_false_block_rate.value` = 0.2692, `acceptance.checks.benign_false_block_rate.threshold` = 0.05, `acceptance.checks.recall_wilson_lower.value` = 0.9504, `acceptance.checks.recall_wilson_lower.threshold` = 0.8, `acceptance.checks.unverified_rate.value` = 0.0, `sets.variants.rules_or_judge.conservative.benign_false_block` |
| C09 | Round 2, held-out variants, conservative view: layered and rules-only results | rules OR judge 141/143 (98.6%); rules alone 112/143 (78.3%) with false blocks 9/52 (17.3%) | `release/benchmarks/crosscheck_r2_20261017T235438Z/results.json` → `sets.variants.rules_or_judge.conservative.attack_recall`, `sets.variants.rules_only.attack_recall`, `sets.variants.rules_only.benign_false_block` |
| C10 | Round 2 paired exact McNemar, rules alone vs rules OR judge (preregistered secondary analysis) | attacks: n 143, b 0, c 29, `p = 3.73e-09`; benign: n 52, b 0, c 5, p 0.0625 | `release/benchmarks/crosscheck_r2_20261017T235438Z/results.json` → `sets.variants.mcnemar_rules_vs_rules_or_judge` |
| C11 | Round 2 preregistration written before the first judge call | before the first judge HTTP request and the first judge call | `release/benchmarks/crosscheck_r2_20261017T235438Z/preregistration.json` → `created_utc` = 2026-10-18T00:19:58.999+00:00, `written_before_any_judge_call` = true; `release/benchmarks/crosscheck_r2_20261017T235438Z/results.json` → `first_judge_http_request_utc` = 2026-10-18T00:20:06.623+00:00, `first_judge_call_utc` = 2026-10-18T00:20:13.869+00:00 |
| C12 | What changed from round 1 to round 2, decided from round-1 results only, before any round-2 judge call | 'supported' no longer a flag; judge prompt rule 5 (instruction override) rewritten; a paraphraser of another family and a new seed | `release/benchmarks/crosscheck_r2_20261017T235438Z/summary.md:5,9` |
| MT01 | Metamorphic testing of the guardrails: relations, instances, seed; the invariance relation (MR3) | 6 relations × 200 instances, seed 20261018; invariance 0/200 violations | `release/benchmarks/metamorphic_20261017T233944Z/summary.md:3,9,12` |
| MT02 | Metamorphic violations before → after the guardrail fixes, same harness and seed | negation relation 132 → 62; quote-fragment relation 152 → 122 | `release/benchmarks/metamorphic_20261017T233944Z/summary.md:63,66` |
| MT03 | Guardrail bug signatures closed by the fixes | 7 (of the 8 closed-signature rows, those with Before above 0 and After 0) | **derived**: count of the rows of the "Signature closed" table, `release/benchmarks/metamorphic_20261017T233944Z/summary.md:72-79`, whose Before cell is above 0 (MR1/extractor/fragment-post-negation reads 0 → 0) |
| MT04 | Metamorphic live layer on DeepSeek-V4-Flash: negation polarity of accepted facts on the flipped clause | 2 of 20 facts (10.0%) | `release/benchmarks/metamorphic_20261017T233944Z/summary.md:129` |
| MT05 | A negated going-home plan was accepted (signature MR1/episode/plan-negated) in the published run; fixed afterwards with a regression test of 11 cases that passed this session | 40 instances in the published run; fixed afterwards, with a regression test | `release/benchmarks/metamorphic_20261017T233944Z/summary.md:39`; `handoff_day1/agent/test_plan_negation.py:36` ("def test_negated_plans_are_refused") |
| MT06 | Final metamorphic rerun on the shipped code (same harness and seed as MT01): violations of 200 per relation | negation 38 (62 in the published run); dose 0 (40 in the published run); invariance 0; quote fragment 122; diagnosis 48; override 47 | `release/benchmarks/metamorphic_final_20261018T024113Z/results.json` → `seed` = 20261018, `n` = 200, `relations.MR1.violations` = 38, `relations.MR2.violations` = 0, `relations.MR3.violations` = 0, `relations.MR4.violations` = 122, `relations.MR5.violations` = 48, `relations.MR6.violations` = 47; published run `release/benchmarks/metamorphic_20261017T233944Z/results.json` → `relations.MR1.violations` = 62, `relations.MR2.violations` = 40 |
| DF01 | Display fixes after the final review: a negated or a cancelled procedure is never shown as planned on any surface; the message about a new update uses its timeline card's headline; a negated going-home plan is refused | 7, 7, 2 and 11 tests, all passing | **derived**: run 2026-10-18 about 01:57 UTC, each "OK": `.venv/Scripts/python.exe -I handoff_day1/agent/test_procedure_negation_display.py` ("Ran 7 tests"), `handoff_day1/agent/test_display_cancel_toast.py` ("Ran 7 tests"), `handoff_day1/ui/test_toast_headline.py` from `handoff_day1/ui` ("Ran 2 tests"), `handoff_day1/agent/test_plan_negation.py` ("Ran 11 tests") |
| G01 | PriMock57 external reference: final results | 30/30 consultations; recall 58.2% [54.0, 61.8] (513/881); contradiction rate 6.0% [4.3, 7.8] (55/918); weighted errors 0.682 [0.574, 0.800]; grounding pass 81.4% [78.1, 84.4] | `release/benchmarks/primock_gold_20261018T002738Z/summary.md` (final line of the run; as-run results kept beside `summary_reparsed.md`); preregistration `research/primock_gold_v1/preregistration.json` + `preregistration_amendment_1.json` (subset written before the first live call) |
| G02k | PriMock57 human-vs-model agreement | Cohen's kappa 0.797 [0.747, 0.845]; raw agreement 84.8%; n = 349 labelled of 360 (11 left blank); note facts 0.747, extracted facts 0.641 | `release/benchmarks/primock_gold_20261018T002738Z/kappa.json` → `overall.kappa`, `overall.raw_agreement`, `overall.n`; labels `release/benchmarks/primock_gold_20261018T002738Z/human_review_filled.csv` (fully human labelling by a team member; the original blank sheet `human_review.csv` is unchanged) |
| G02 | PriMock57 protocol fixed and hashed before any live call; the protocol file still matches its preregistered hash (checked this session) | written before any live call | `research/primock_gold_v1/preregistration.json` → `written_before_any_live_call` = true, `protocol_sha256` |
| K01 | API-key redaction tests (offline): a planted sentinel key must not appear, even as an 8-character piece, in any output file, error text or argv | sentinel key, 8-character pieces | `scripts/test_bench_tf_handover.py:22` ("never a real key"); `scripts/test_bench_tf_handover.py:215-216` ("8-character piece"); `scripts/test_load_tf_endpoint.py:220` ("def test_key_never_in_outputs"); `scripts/test_crosscheck_judge.py:409` ("def test_the_key_never_reaches_an_output") |
| K02 | Scan of every blob reachable from all refs for keys: this repository and a mirror of the earlier public CareRelay repository, with an exact check for the real key | no exact-key hit in either; 704 and 862 blobs; 4 pattern hits, all planted test sentinels, in this repository and none in CareRelay | `release/benchmarks/secret_scan_20261018T020029Z/local_history.txt:1` ("blobs scanned: 704; exact-key check: on"); `release/benchmarks/secret_scan_20261018T020029Z/carerelay_history.txt:1-3` ("blobs scanned: 862; exact-key check: on"); the 4 hits `release/benchmarks/secret_scan_20261018T020029Z/README.md:24` ("The 4 local pattern hits"); scope, patterns and limits in the same README; script `scripts/scan_history_secrets.py`, tests `scripts/test_scan_history_secrets.py` |
| Q03 | CI workflow status at writing | not yet run on GitHub | `.github/workflows/validate.yml:3` ("STATUS: NOT YET RUN ON GITHUB.") |
| H02 | Hazard log: hazards and open hazards | 12 hazards; 2 open (HZ-09, HZ-11); HZ-03 and HZ-04 mitigated after the DX-05 and PI-04 fixes | **derived**: rows HZ-01 to HZ-12 of `submission/HAZARD_LOG.md` whose Status cell starts with "open" (read 2026-10-18 about 01:57 UTC; 4 open, HZ-03, HZ-04, HZ-09, HZ-11, before the fixes) |
| H03 | Hazard-log citation check after the final fixes | RESULT: PASS; 12 hazards, 87 citations, 33 cited tests | **derived**: `.venv/Scripts/python.exe -I -S scripts/check_hazard_log.py` (2026-10-18 about 02:08 UTC: "hazards=12; citations checked=87; tests cited=33 (run by validate_abd: 30)", "RESULT: PASS") |
| S03 | Final offline validation run | PASS: 832 unittest cases in 41 test processes, sources unchanged | `handoff_day1/ui/pages/shell/data/validation.json` → `doc.unittest_cases` = 832, `doc.test_processes` = 41, `doc.passed` = true (frozen copy of `release/validation_abd/final2-20261018T024113Z/summary.json`; that folder is git-ignored and stays in the private development repository) |
| R11 | Final red-team rerun on the shipped code (after the DX-05 and PI-04 fixes; same cases file as REDTEAM) | 73 cases (54 attacks, 19 controls, 6 marked known gap); 49/54 = 90.7% stopped; 48/48 excluding known gaps; 0/19 controls blocked | `release/benchmarks/redteam_final_20261018T024113Z/results.json` → `summary.cases` = 73, `.attacks` = 54, `.controls` = 19, `.known_gap_cases` = 6, `summary.block_recall` = {stopped 49, attacks 54, rate 0.9074}, `summary.block_recall_excluding_known_gaps` = {stopped 48, attacks 48}, `summary.false_block_rate` = {blocked 0, controls 19}; `release/benchmarks/redteam_final_20261018T024113Z/summary.md:5-7` |
| R12 | Final rerun: attacks still not stopped (all on the Case Agent answer path, none on the deployed family timeline); DX-05 and PI-04 are stopped there now and HO-04 is closed | 5 held-out attacks: HO-01, HO-02, HO-05, HO-06, HO-07; held-out stopped 2/7 | `release/benchmarks/redteam_final_20261018T024113Z/results.json` → `summary.heldout.missed` (5 entries), `summary.heldout` = {attacks 7, stopped 2, rate 0.2857}; `release/benchmarks/redteam_final_20261018T024113Z/summary.md:8-9` |
| R13 | Tests of the DX-05, MR2 and PI-04 fixes on the family timeline | 13 tests, all passing | **derived**: `.venv/Scripts/python.exe -I handoff_day1/agent/test_episode_safety_gaps.py` (2026-10-18 about 01:57 UTC: "Ran 13 tests", "OK"); also run by `deploy/validate_abd.py` (`handoff_day1/agent/test_*.py`) |
