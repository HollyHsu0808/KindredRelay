# Handover benchmark: `DeepSeek-V4-Flash`, `Gemma-4-31B-IT`

Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn). The hardware behind the endpoint is not visible to this client, so no specific GPU is claimed. Latency includes the network path from this machine to the endpoint.

- Created (UTC): 2026-10-17T21:58:32.160+00:00; git 07b8008fa24f (uncommitted changes in tracked files); this harness is not committed yet
- What one case is: one story update added after the earlier updates were replayed from their recorded extraction (handoff_day1/care_cases/episode_hip_fracture.json); the model turns that update into facts that each quote it and the grounding check accepts or rejects every quote; the evidence verifier (KINDRED_VERIFIER_MODE off) holds facts for review only in gate mode.
- Entry point: handoff_day1/agent/episode_events.py EpisodeJournal.add_update(update, extractor=episode.llm_extractor(client), evidence_checker=evidence_gate.checker_from_env()), as ui/pages/1_Family_timeline.py get_extractor() and add_verified() call it.
- Cases (12): episode_hip_fracture/u01, episode_hip_fracture/u02, episode_hip_fracture/u03, episode_hip_fracture/u04, episode_hip_fracture/u05, episode_hip_fracture/u06, episode_hip_fracture/u07, episode_hip_fracture/u07b, episode_hip_fracture/u07c, episode_hip_fracture/u08, episode_hip_fracture/u09, episode_hip_fracture/u10; repeats 3; settings: max_tokens 2000, prompted JSON, timeout 120 s, 6 tries, extra body {}.
- HTTP calls: 83 (1 retries) over 1 invocation(s).

| Model | n | Success | e2e p50 [95% CI] | e2e p95 | e2e mean | call p50 / p95 | completion tok/s | tokens / handover | citation validity [95% CI] | gate | TTFT p50 | HTTP calls | retries |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `DeepSeek-V4-Flash` | 36/36 | 36/36 (100.0%) | 6.15 s [5.73, 9.06] | 15.62 s | 9.28 s | 6.12 s / 15.59 s | 18.4 | 1,219 | 95.7% (135/141) [0.92, 0.99] | off | 1.51 s | 42 | 1 |
| `Gemma-4-31B-IT` | 36/36 | 36/36 (100.0%) | 16.66 s [14.34, 23.25] | 51.40 s | 22.62 s | 16.64 s / 51.38 s | 10.8 | 1,330 | 86.0% (117/136) [0.80, 0.91] | off | 1.47 s | 41 | 0 |

## Per model

### `DeepSeek-V4-Flash`

- Success 36/36 (Wilson 95% [0.90, 1.00]); failures: none; aborted (not redone): 0.
- End to end (successful cases, n = 36): p50 6.15 s, p95 15.62 s, mean 9.28 s, min 2.80 s, max 53.34 s; p50 without retry waits 6.15 s. Sum of the per-case medians over the selected updates: 100.66 s.
- Tokens per handover (n = 36 with usage, 0 without): mean 1,219 (prompt 1,049, completion 170), p50 1,167. Completion tokens per second of call wall time: aggregate 18.4, per-call p50 21.4 (includes prompt processing and the network: not a decode speed).
- Facts per handover: 3.92 proposed, 3.75 accepted, 0.00 withheld by the gate; 0 handover(s) with no accepted fact. Grounding rejections: 4 x quote shorter than 3 words; 1 x condition says 'be', which the quote does not; 1 x missing hours.
- Agreement with the story's recorded extraction (heuristic: same type, overlapping quote; not a quality score): 91/102 (89.2%).
- TTFT (5 streaming probes, fixed short prompt): p50 1.51 s, p95 1.85 s; streaming supported: True.
- HTTP statuses: 200: 41, 429: 1.

### `Gemma-4-31B-IT`

- Success 36/36 (Wilson 95% [0.90, 1.00]); failures: none; aborted (not redone): 0.
- End to end (successful cases, n = 36): p50 16.66 s, p95 51.40 s, mean 22.62 s, min 8.61 s, max 70.44 s; p50 without retry waits 16.66 s. Sum of the per-case medians over the selected updates: 253.39 s.
- Tokens per handover (n = 36 with usage, 0 without): mean 1,330 (prompt 1,086, completion 244), p50 1,284. Completion tokens per second of call wall time: aggregate 10.8, per-call p50 12.1 (includes prompt processing and the network: not a decode speed).
- Facts per handover: 3.78 proposed, 3.25 accepted, 0.00 withheld by the gate; 0 handover(s) with no accepted fact. Grounding rejections: 12 x missing what; 3 x missing hours; 3 x quote shorter than 3 words; 1 x quote not found in the update.
- Agreement with the story's recorded extraction (heuristic: same type, overlapping quote; not a quality score): 87/102 (85.3%).
- TTFT (5 streaming probes, fixed short prompt): p50 1.47 s, p95 1.57 s; streaming supported: True.
- HTTP statuses: 200: 41.

## Wording for the write-up

- `DeepSeek-V4-Flash`: one caregiver update was turned into sourced facts and a timeline entry in a median of 6.2 s (p95 15.6 s, 95% CI of the median 5.7 to 9.1 s) at a mean of 1,219 tokens (prompt + completion, as reported by the endpoint), n = 36, 36/36 successful; 95.7% of proposed quotes passed the grounding check. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn).
- `Gemma-4-31B-IT`: one caregiver update was turned into sourced facts and a timeline entry in a median of 16.7 s (p95 51.4 s, 95% CI of the median 14.3 to 23.2 s) at a mean of 1,330 tokens (prompt + completion, as reported by the endpoint), n = 36, 36/36 successful; 86.0% of proposed quotes passed the grounding check. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn).

Notes: latency covers successful cases and includes retries and backoff waits; tokens are the endpoint's `usage` (n/a where it sent none, never estimated); bootstrap intervals resample completed cases (2000 resamples, seed 20261017, none below n = 5); a rate of 100% gives a bootstrap interval of [1, 1], so the Wilson interval is listed with it. The story is the fictional demo episode; the numbers are engineering measurements, not clinical validation.
