# Handover benchmark: `DeepSeek-V4-Flash`, `Gemma-4-31B-IT`, `Qwen3.8-27B`

Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn). The hardware behind the endpoint is not visible to this client, so no specific GPU is claimed. Latency includes the network path from this machine to the endpoint.

- Created (UTC): 2026-10-17T14:19:45.904+00:00; git 07b8008fa24f; this harness is not committed yet
- What one case is: one story update added after the earlier updates were replayed from their recorded extraction (handoff_day1/care_cases/episode_hip_fracture.json); the model turns that update into facts that each quote it and the grounding check accepts or rejects every quote; the evidence verifier (KINDRED_VERIFIER_MODE off) holds facts for review only in gate mode.
- Entry point: handoff_day1/agent/episode_events.py EpisodeJournal.add_update(update, extractor=episode.llm_extractor(client), evidence_checker=evidence_gate.checker_from_env()), as ui/pages/1_Family_timeline.py get_extractor() and add_verified() call it.
- Cases (12): episode_hip_fracture/u01, episode_hip_fracture/u02, episode_hip_fracture/u03, episode_hip_fracture/u04, episode_hip_fracture/u05, episode_hip_fracture/u06, episode_hip_fracture/u07, episode_hip_fracture/u07b, episode_hip_fracture/u07c, episode_hip_fracture/u08, episode_hip_fracture/u09, episode_hip_fracture/u10; repeats 3; settings: max_tokens 2000, prompted JSON, timeout 120 s, 6 tries, extra body {}.
- HTTP calls: 127 (4 retries) over 1 invocation(s).

| Model | n | Success | e2e p50 [95% CI] | e2e p95 | e2e mean | call p50 / p95 | completion tok/s | tokens / handover | citation validity [95% CI] | gate | TTFT p50 | HTTP calls | retries |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `DeepSeek-V4-Flash` | 36/36 | 36/36 (100.0%) | 9.95 s [7.92, 20.75] | 101.63 s | 27.66 s | 9.55 s / 69.03 s | 8.1 | 1,214 | 93.6% (132/141) [0.89, 0.98] | off | 2.10 s | 45 | 4 |
| `Gemma-4-31B-IT` | 36/36 | 34/36 (94.4%) | 20.19 s [13.32, 34.11] | 65.35 s | 28.18 s | 20.17 s / 65.32 s | 8.3 | 1,317 | 84.1% (106/126) [0.78, 0.90] | off | 1.91 s | 41 | 0 |
| `Qwen3.8-27B` | 36/36 | 3/36 (8.3%) | 90.76 s | 95.15 s | 77.52 s | 91.44 s / 111.61 s | 21.9 | 2,623 | 100.0% (9/9) | off | 2.49 s | 41 | 0 |

## Per model

### `DeepSeek-V4-Flash`

- Success 36/36 (Wilson 95% [0.90, 1.00]); failures: none; aborted (not redone): 0.
- End to end (successful cases, n = 36): p50 9.95 s, p95 101.63 s, mean 27.66 s, min 4.03 s, max 145.96 s; p50 without retry waits 9.95 s. Sum of the per-case medians over the selected updates: 299.64 s.
- Tokens per handover (n = 36 with usage, 0 without): mean 1,214 (prompt 1,049, completion 165), p50 1,164. Completion tokens per second of call wall time: aggregate 8.1, per-call p50 14.2 (includes prompt processing and the network: not a decode speed).
- Facts per handover: 3.92 proposed, 3.67 accepted, 0.00 withheld by the gate; 0 handover(s) with no accepted fact. Grounding rejections: 3 x missing hours; 3 x missing what; 2 x quote shorter than 3 words; 1 x hospital says 'hospital', which the quote does not.
- Agreement with the story's recorded extraction (heuristic: same type, overlapping quote; not a quality score): 89/102 (87.2%).
- TTFT (5 streaming probes, fixed short prompt): p50 2.10 s, p95 12.14 s; streaming supported: True.
- HTTP statuses: 200: 41, 500: 4.

### `Gemma-4-31B-IT`

- Success 34/36 (Wilson 95% [0.82, 0.98]); failures: timeout 2; aborted (not redone): 0.
- End to end (successful cases, n = 34): p50 20.19 s, p95 65.35 s, mean 28.18 s, min 5.49 s, max 113.32 s; p50 without retry waits 20.19 s. Sum of the per-case medians over the selected updates: 334.88 s.
- Tokens per handover (n = 34 with usage, 0 without): mean 1,317 (prompt 1,083, completion 234), p50 1,240. Completion tokens per second of call wall time: aggregate 8.3, per-call p50 10.4 (includes prompt processing and the network: not a decode speed).
- Facts per handover: 3.71 proposed, 3.12 accepted, 0.00 withheld by the gate; 0 handover(s) with no accepted fact. Grounding rejections: 11 x missing what; 3 x missing hours; 2 x quote not found in the update; 2 x quote shorter than 3 words; 2 x when is not text.
- Agreement with the story's recorded extraction (heuristic: same type, overlapping quote; not a quality score): 77/92 (83.7%).
- TTFT (5 streaming probes, fixed short prompt): p50 1.91 s, p95 10.01 s; streaming supported: True.
- HTTP statuses: 200: 39, None: 2.

### `Qwen3.8-27B`

- Success 3/36 (Wilson 95% [0.03, 0.22]); failures: timeout 16, truncated 17; aborted (not redone): 0.
- End to end (successful cases, n = 3): p50 90.76 s, p95 95.15 s, mean 77.52 s, min 46.17 s, max 95.63 s; p50 without retry waits 90.76 s. Sum of the per-case medians over the selected updates: n/a.
- Tokens per handover (n = 3 with usage, 0 without): mean 2,623 (prompt 1,100, completion 1,523), p50 2,806. Completion tokens per second of call wall time: aggregate 21.9, per-call p50 21.5 (includes prompt processing and the network: not a decode speed).
- Facts per handover: 3.00 proposed, 3.00 accepted, 0.00 withheld by the gate; 0 handover(s) with no accepted fact. Grounding rejections: none.
- Agreement with the story's recorded extraction (heuristic: same type, overlapping quote; not a quality score): 6/6 (100.0%).
- TTFT (5 streaming probes, fixed short prompt): p50 2.49 s, p95 4.09 s; streaming supported: True.
- HTTP statuses: 200: 25, None: 16.

## Wording for the write-up

- `DeepSeek-V4-Flash`: one caregiver update was turned into sourced facts and a timeline entry in a median of 10.0 s (p95 101.6 s, 95% CI of the median 7.9 to 20.8 s) at a mean of 1,214 tokens (prompt + completion, as reported by the endpoint), n = 36, 36/36 successful; 93.6% of proposed quotes passed the grounding check. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn).
- `Gemma-4-31B-IT`: one caregiver update was turned into sourced facts and a timeline entry in a median of 20.2 s (p95 65.3 s, 95% CI of the median 13.3 to 34.1 s) at a mean of 1,317 tokens (prompt + completion, as reported by the endpoint), n = 34, 34/36 successful; 84.1% of proposed quotes passed the grounding check. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn).
- `Qwen3.8-27B`: one caregiver update was turned into sourced facts and a timeline entry in a median of 90.8 s (p95 95.1 s) at a mean of 2,623 tokens (prompt + completion, as reported by the endpoint), n = 3, 3/36 successful; 100.0% of proposed quotes passed the grounding check. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn).

Notes: latency covers successful cases and includes retries and backoff waits; tokens are the endpoint's `usage` (n/a where it sent none, never estimated); bootstrap intervals resample completed cases (2000 resamples, seed 20261017, none below n = 5); a rate of 100% gives a bootstrap interval of [1, 1], so the Wilson interval is listed with it. The story is the fictional demo episode; the numbers are engineering measurements, not clinical validation.
