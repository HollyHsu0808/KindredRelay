# Handover benchmark: `DeepSeek-V4-Flash`, `Gemma-4-31B-IT`

Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn). The hardware behind the endpoint is not visible to this client, so no specific GPU is claimed. Latency includes the network path from this machine to the endpoint.

- Created (UTC): 2026-10-17T23:28:41.272+00:00; git 0874ecde81ab (uncommitted changes in tracked files)
- What one case is: one story update added after the earlier updates were replayed from their recorded extraction (handoff_day1/care_cases/episode_hip_fracture.json); the model turns that update into facts that each quote it and the grounding check accepts or rejects every quote; the evidence verifier (KINDRED_VERIFIER_MODE off) holds facts for review only in gate mode.
- Entry point: handoff_day1/agent/episode_events.py EpisodeJournal.add_update(update, extractor=episode.llm_extractor(client), evidence_checker=evidence_gate.checker_from_env()), as ui/pages/1_Family_timeline.py get_extractor() and add_verified() call it.
- Cases (12): episode_hip_fracture/u01, episode_hip_fracture/u02, episode_hip_fracture/u03, episode_hip_fracture/u04, episode_hip_fracture/u05, episode_hip_fracture/u06, episode_hip_fracture/u07, episode_hip_fracture/u07b, episode_hip_fracture/u07c, episode_hip_fracture/u08, episode_hip_fracture/u09, episode_hip_fracture/u10; repeats 3; settings: max_tokens 2000, prompted JSON, timeout 120 s, 6 tries, extra body {}.
- HTTP calls: 83 (1 retries) over 1 invocation(s).

| Model | n | Success | e2e p50 [95% CI] | e2e p95 | e2e mean | call p50 / p95 | completion tok/s | tokens / handover | citation validity [95% CI] | gate | TTFT p50 | HTTP calls | retries |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `DeepSeek-V4-Flash` | 36/36 | 35/36 (97.2%) | 6.63 s [5.58, 7.94] | 16.53 s | 8.35 s | 6.59 s / 16.50 s | 20.0 | 1,216 | 96.3% (129/134) [0.92, 0.99] | off | 1.49 s | 41 | 0 |
| `Gemma-4-31B-IT` | 36/36 | 36/36 (100.0%) | 22.77 s [13.31, 29.08] | 82.36 s | 30.49 s | 22.75 s / 82.34 s | 8.1 | 1,331 | 83.3% (115/138) [0.78, 0.89] | off | 1.40 s | 42 | 1 |

## Per model

### `DeepSeek-V4-Flash`

- Success 35/36 (Wilson 95% [0.86, 1.00]); failures: timeout 1; aborted (not redone): 0.
- End to end (successful cases, n = 35): p50 6.63 s, p95 16.53 s, mean 8.35 s, min 3.60 s, max 29.24 s; p50 without retry waits 6.63 s. Sum of the per-case medians over the selected updates: 89.62 s.
- Tokens per handover (n = 35 with usage, 0 without): mean 1,216 (prompt 1,049, completion 166), p50 1,163. Completion tokens per second of call wall time: aggregate 20.0, per-call p50 20.6 (includes prompt processing and the network: not a decode speed).
- Facts per handover: 3.83 proposed, 3.69 accepted, 0.00 withheld by the gate; 0 handover(s) with no accepted fact. Grounding rejections: 2 x missing what; 1 x dose is not text; 1 x hospital says 'hospital', which the quote does not; 1 x missing hours.
- Agreement with the story's recorded extraction (heuristic: same type, overlapping quote; not a quality score): 88/100 (88.0%).
- TTFT (5 streaming probes, fixed short prompt): p50 1.49 s, p95 2.30 s; streaming supported: True.
- HTTP statuses: 200: 40, None: 1.

### `Gemma-4-31B-IT`

- Success 36/36 (Wilson 95% [0.90, 1.00]); failures: none; aborted (not redone): 0.
- End to end (successful cases, n = 36): p50 22.77 s, p95 82.36 s, mean 30.49 s, min 4.30 s, max 119.75 s; p50 without retry waits 22.77 s. Sum of the per-case medians over the selected updates: 340.93 s.
- Tokens per handover (n = 36 with usage, 0 without): mean 1,331 (prompt 1,086, completion 245), p50 1,288. Completion tokens per second of call wall time: aggregate 8.1, per-call p50 11.4 (includes prompt processing and the network: not a decode speed).
- Facts per handover: 3.83 proposed, 3.19 accepted, 0.00 withheld by the gate; 0 handover(s) with no accepted fact. Grounding rejections: 12 x missing what; 3 x missing hours; 3 x quote not found in the update; 3 x quote shorter than 3 words; 2 x when is not text.
- Agreement with the story's recorded extraction (heuristic: same type, overlapping quote; not a quality score): 85/102 (83.3%).
- TTFT (5 streaming probes, fixed short prompt): p50 1.40 s, p95 2.41 s; streaming supported: True.
- HTTP statuses: 200: 41, 429: 1.

## Wording for the write-up

- `DeepSeek-V4-Flash`: one caregiver update was turned into sourced facts and a timeline entry in a median of 6.6 s (p95 16.5 s, 95% CI of the median 5.6 to 7.9 s) at a mean of 1,216 tokens (prompt + completion, as reported by the endpoint), n = 35, 35/36 successful; 96.3% of proposed quotes passed the grounding check. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn).
- `Gemma-4-31B-IT`: one caregiver update was turned into sourced facts and a timeline entry in a median of 22.8 s (p95 82.4 s, 95% CI of the median 13.3 to 29.1 s) at a mean of 1,331 tokens (prompt + completion, as reported by the endpoint), n = 36, 36/36 successful; 83.3% of proposed quotes passed the grounding check. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn).

Notes: latency covers successful cases and includes retries and backoff waits; tokens are the endpoint's `usage` (n/a where it sent none, never estimated); bootstrap intervals resample completed cases (2000 resamples, seed 20261017, none below n = 5); a rate of 100% gives a bootstrap interval of [1, 1], so the Wilson interval is listed with it. The story is the fictional demo episode; the numbers are engineering measurements, not clinical validation.
