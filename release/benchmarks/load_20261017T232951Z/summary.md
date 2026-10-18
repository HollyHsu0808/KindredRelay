# Endpoint load test: `DeepSeek-V4-Flash` at concurrency 1, 2, 4, 8

Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn). The hardware behind the endpoint is not visible to this client, so no specific GPU is claimed. Latency includes the network path from this machine to the endpoint.

- Created (UTC): 2026-10-17T23:36:54.661+00:00; git 0874ecde81ab (uncommitted changes in tracked files)
- One request: one handover as scripts/bench_tf_handover.py runs a case: one story update added after the earlier updates were replayed from their recorded extraction; episode.llm_extractor over llm_client.OpenAIChat.chat with the bench's instrumented HTTP layer. Updates cycled: u01, u02, u03, u04 (handoff_day1/care_cases/episode_hip_fracture.json); 16 requests per level, 10 s pause between levels; settings: max_tokens 2000, prompted JSON, timeout 120 s, 6 tries (llm_client's backoff), extra body {}, evidence verifier off.
- HTTP calls: 85 (21 retries, 21 answered 429) of at most 120.

| Concurrency | ok / requests | level wall | max in flight | handovers / min | x first level | completion tok/s | latency p50 [95% CI] | latency p95 [95% CI] | errors [Wilson 95%] | 429s / attempts [Wilson 95%] | retries |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 16/16 | 153.5 s | 1 | 6.25 | 1.00x | 19.2 | 7.23 s [5.96, 14.20] | 16.34 s [14.20, 18.58] | 0/16 [0.00, 0.19] | 0/16 [0.00, 0.19] | 0 |
| 2 | 16/16 | 80.3 s | 2 | 11.95 | 1.91x | 34.7 | 6.54 s [5.84, 9.77] | 18.05 s [10.10, 33.73] | 0/16 [0.00, 0.19] | 0/16 [0.00, 0.19] | 0 |
| 4 | 16/16 | 57.0 s | 4 | 16.84 | 2.69x | 50.6 | 9.63 s [6.28, 14.63] | 34.93 s [16.66, 37.89] | 0/16 [0.00, 0.19] | 1/17 [0.01, 0.27] | 1 |
| 8 | 16/16 | 101.1 s | 8 | 9.49 | 1.52x | 27.0 | 10.10 s [6.77, 26.22] | 92.86 s [29.26, 96.29] | 0/16 [0.00, 0.19] | 20/36 [0.40, 0.70] | 20 |

## What the curve shows

Successful handovers per minute went from 6.25 at concurrency 1 to 9.49 at concurrency 8 (1.52x for 8x the concurrent requests). The endpoint answered HTTP 429 (rate limited) at concurrency 4, 8: throughput there is bounded by the rate limit applied to this API key and by the client's backoff (2, 4, 8, ... s or Retry-After), not by the speed of the serving hardware, which this client cannot see. Throughput stopped rising (less than +10% over the previous level) at concurrency 8; it coincides with HTTP 429 responses, so it is read as rate limiting.

Highest throughput: 0.2807 successful handovers/s at concurrency 4 (with HTTP 429 at that level) (results.json `per_model`, read by scripts/capacity_model.py).

## Per level

- Concurrency 1: latency mean 9.58 s, min 4.85 s, max 18.58 s, p50 without retry waits 7.23 s; successful call p50 / p95 7.22 s / 16.33 s; tokens per handover: prompt 1,049, completion 184; failures: none; aborted 0, not run 0; HTTP statuses 200: 16; retry waits 0.0 s.
- Concurrency 2: latency mean 9.12 s, min 4.66 s, max 33.73 s, p50 without retry waits 6.54 s; successful call p50 / p95 6.52 s / 18.03 s; tokens per handover: prompt 1,049, completion 174; failures: none; aborted 0, not run 0; HTTP statuses 200: 16; retry waits 0.0 s.
- Concurrency 4: latency mean 13.59 s, min 4.67 s, max 37.89 s, p50 without retry waits 9.63 s; successful call p50 / p95 9.61 s / 34.92 s; tokens per handover: prompt 1,049, completion 180; failures: none; aborted 0, not run 0; HTTP statuses 200: 16, 429: 1; retry waits 1.0 s.
- Concurrency 8: latency mean 26.80 s, min 4.78 s, max 96.29 s, p50 without retry waits 9.06 s; successful call p50 / p95 8.45 s / 11.36 s; tokens per handover: prompt 1,049, completion 171; failures: none; aborted 0, not run 0; HTTP statuses 200: 16, 429: 20; retry waits 281.0 s.

Notes: throughput is per level wall time (first submission to last end), so it includes retries and backoff waits; completion tokens are the endpoint's `usage` (n/a where a successful request had none, never estimated); latency covers successful requests. With 16 requests per level the p95 is close to the slowest request and its interval is wide. Each attempt opens its own HTTPS connection, as the bench's transport does. The same few prompts are repeated, so any prompt caching on the endpoint (not visible to this client) helps every level alike. Other clients of this API key were asked to pause while the marker file `release/benchmarks/.load_test_running` existed (2026-10-17T23:29:52.417+00:00 to 2026-10-17T23:36:54.484+00:00); that is a request, not an enforced lock. Outside that window other clients may share the key, and other users may share the endpoint at any time; 429s and latencies are the endpoint and key as seen during the run. The story is the fictional demo episode; these are engineering measurements, not clinical validation.
