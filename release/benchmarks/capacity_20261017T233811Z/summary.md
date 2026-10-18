# Capacity and token model: `DeepSeek-V4-Flash` on the caregiver-update path

Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (host developer.amd.com.cn); the hardware behind the endpoint is not visible to this client, so no GPU is claimed.

A model, not a measurement: measured per-handover numbers × labelled assumptions. Created 2026-10-17T23:38:11+00:00. Capacity basis: the load test's measured throughput at concurrency 4. Tokens are the endpoint's usage field; no price is invented (price_per_million_tokens null (tokens only)).

## Measured

| Quantity | Value | Source file | JSON key |
|---|---|---|---|
| tokens per handover, mean (prompt + completion, endpoint usage) | 1,215.5 | release/benchmarks/tf_bench_20261017T230311Z/results.json | `per_model.DeepSeek-V4-Flash.tokens_per_handover.mean` |
| prompt tokens per handover, mean | 1,049.3 | release/benchmarks/tf_bench_20261017T230311Z/results.json | `per_model.DeepSeek-V4-Flash.tokens_per_handover.prompt_mean` |
| completion tokens per handover, mean | 166.2 | release/benchmarks/tf_bench_20261017T230311Z/results.json | `per_model.DeepSeek-V4-Flash.tokens_per_handover.completion_mean` |
| handovers whose usage the endpoint reported | 35 | release/benchmarks/tf_bench_20261017T230311Z/results.json | `per_model.DeepSeek-V4-Flash.tokens_per_handover.n_with_usage` |
| end-to-end latency per handover, mean (s) | 8.3511 | release/benchmarks/tf_bench_20261017T230311Z/results.json | `per_model.DeepSeek-V4-Flash.e2e_latency_s.mean` |
| end-to-end latency, p50 (s) | 6.6325 | release/benchmarks/tf_bench_20261017T230311Z/results.json | `per_model.DeepSeek-V4-Flash.e2e_latency_s.p50` |
| end-to-end latency, p95 (s) | 16.5276 | release/benchmarks/tf_bench_20261017T230311Z/results.json | `per_model.DeepSeek-V4-Flash.e2e_latency_s.p95` |
| handovers completed | 36 | release/benchmarks/tf_bench_20261017T230311Z/results.json | `per_model.DeepSeek-V4-Flash.n_completed` |
| handovers successful | 35 | release/benchmarks/tf_bench_20261017T230311Z/results.json | `per_model.DeepSeek-V4-Flash.success.count` |
| completed handovers per second, all streams | 0.2807 | release/benchmarks/load_20261017T232951Z/results.json | `per_model.DeepSeek-V4-Flash.throughput_handovers_per_s` |
| concurrent streams | 4 | release/benchmarks/load_20261017T232951Z/results.json | `per_model.DeepSeek-V4-Flash.concurrency` |
| judge tokens per check, mean (endpoint usage) | 1,051.3 | release/benchmarks/crosscheck_20261017T221103Z/results.json | `tokens_per_check.mean` |
| judge call latency, p50 (s; the file has no mean) | 7.704 | release/benchmarks/crosscheck_20261017T221103Z/results.json | `latency_s.p50` |

Handover benchmark release/benchmarks/tf_bench_20261017T230311Z/results.json (created 2026-10-17T23:28:41.272+00:00, sha256 05af8036a9ef, host developer.amd.com.cn).
Load test: release/benchmarks/load_20261017T232951Z/results.json (created 2026-10-17T23:36:54.661+00:00, sha256 9139a5aacf06).
Cross-model check: release/benchmarks/crosscheck_20261017T221103Z/results.json (judge Gemma-4-31B-IT, created 2026-10-17T23:02:44.328+00:00, sha256 60c762dcea8e).

## Assumed

| Assumption | Value | Default | Basis |
|---|---|---|---|
| updates_per_family_per_day | 2.00 | 2.00 | illustrative pace of caregiver updates during an active care episode (not measured) |
| families_per_care_coordinator | 30.00 | 30.00 | illustrative caseload of one care coordinator (no source in this repository) |
| crosscheck_every_update | no | no | the cross-model check runs in shadow only and is not on the product path; yes adds one judge call per update |
| price_per_million_tokens | null (tokens only) | null (tokens only) | no price is assumed: null reports tokens only; a supplied price is blended over prompt and completion tokens, in the currency it is given in |

Reference, not a measurement: the fictional demo story (handoff_day1/care_cases/episode_hip_fracture.json) has 12 updates over 6 calendar days (2.0 per day).
Conventions: a month is 30 days; scale 1,000 families.

## Outputs

| Output | Value | Formula | Measured inputs used | Assumed inputs used |
|---|---|---|---|---|
| Tokens per caregiver update | 1,216 | tokens per handover (+ judge tokens per check if cross-checked) | tokens per handover; judge tokens per check | crosscheck_every_update |
| Tokens per family per day | 2,431 | tokens per update × updates per day | tokens per handover | updates_per_family_per_day, crosscheck_every_update |
| Tokens per family per month | 72,930 | × 30 days | tokens per handover | updates_per_family_per_day, crosscheck_every_update |
| Tokens per 1,000 families per day | 2,431,000 | × 1,000 | tokens per handover | updates_per_family_per_day, crosscheck_every_update |
| Seconds per update, one sequential stream | 8.35 | e2e latency mean (+ judge call p50 if cross-checked) | e2e latency mean; judge latency p50 | crosscheck_every_update |
| Handovers per stream-hour (sequential) | 431.1 | 3600 / seconds per update | e2e latency mean | crosscheck_every_update |
| Handovers per endpoint-hour at the load test's concurrency | 1,010.4 | throughput per s × 3600 | load test throughput | — |
| Busy hours per 1,000 families per day | 1.98 | 1,000 × updates per day / handovers per hour | capacity basis above | updates_per_family_per_day |
| Updates per care coordinator's caseload per day | 60 | families × updates per day | — | families_per_care_coordinator, updates_per_family_per_day |
| Tokens per care coordinator's caseload per day | 72,930 | families × tokens per family per day | tokens per handover | families_per_care_coordinator, updates_per_family_per_day |
| Busy hours per care coordinator's caseload per day | 0.06 | updates / handovers per hour | capacity basis above | families_per_care_coordinator, updates_per_family_per_day |
| Cost per family per month | n/a | tokens per month × price / 1e6 | tokens per handover | price_per_million_tokens |
| Cost per 1,000 families per day | n/a | tokens per day × price / 1e6 | tokens per handover | price_per_million_tokens |

Capacity basis for the busy-hour rows: load test.

## Sensitivity (each assumption at -50% / base / +50%, the others at their values)

| Assumption | Setting | Value | Tokens / family / day | Tokens / family / month | Busy hours / 1,000 families / day | Tokens / coordinator / day | Cost / family / month |
|---|---|---|---|---|---|---|---|
| updates_per_family_per_day | -50% | 1.00 | 1,216 | 36,465 | 0.99 | 36,465 | n/a |
| updates_per_family_per_day | base | 2.00 | 2,431 | 72,930 | 1.98 | 72,930 | n/a |
| updates_per_family_per_day | +50% | 3.00 | 3,646 | 109,395 | 2.97 | 109,395 | n/a |
| families_per_care_coordinator | -50% | 15.00 | 2,431 | 72,930 | 1.98 | 36,465 | n/a |
| families_per_care_coordinator | base | 30.00 | 2,431 | 72,930 | 1.98 | 72,930 | n/a |
| families_per_care_coordinator | +50% | 45.00 | 2,431 | 72,930 | 1.98 | 109,395 | n/a |
| crosscheck_every_update | base | no | 2,431 | 72,930 | 1.98 | 72,930 | n/a |
| crosscheck_every_update | flipped | yes | 4,534 | 136,008 | 8.92 | 136,008 | n/a |

## Notes

- Not modelled: question answers and photo reads (not in the handover benchmark).
- Not modelled: peaks within a day and queueing: hours are busy time, not wall-clock hours.
- Not modelled: the endpoint's rate limits and other clients' load.
- Not modelled: the network path apart from the endpoint (the measured latency includes the path from the benchmark machine).
