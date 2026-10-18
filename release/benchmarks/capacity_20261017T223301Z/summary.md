# Capacity and token model: `DeepSeek-V4-Flash` on the caregiver-update path

Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (host developer.amd.com.cn); the hardware behind the endpoint is not visible to this client, so no GPU is claimed.

A model, not a measurement: measured per-handover numbers × labelled assumptions. Created 2026-10-17T22:33:01+00:00. Capacity basis: one sequential stream (one client sending updates back to back): a per-client rate, not the endpoint's capacity, which no load test has measured yet. Tokens are the endpoint's usage field; no price is invented (price_per_million_tokens null (tokens only)).

## Measured

| Quantity | Value | Source file | JSON key |
|---|---|---|---|
| tokens per handover, mean (prompt + completion, endpoint usage) | 1,218.8 | release/benchmarks/tf_bench_20261017T213905Z/results.json | `per_model.DeepSeek-V4-Flash.tokens_per_handover.mean` |
| prompt tokens per handover, mean | 1,048.8 | release/benchmarks/tf_bench_20261017T213905Z/results.json | `per_model.DeepSeek-V4-Flash.tokens_per_handover.prompt_mean` |
| completion tokens per handover, mean | 169.9 | release/benchmarks/tf_bench_20261017T213905Z/results.json | `per_model.DeepSeek-V4-Flash.tokens_per_handover.completion_mean` |
| handovers whose usage the endpoint reported | 36 | release/benchmarks/tf_bench_20261017T213905Z/results.json | `per_model.DeepSeek-V4-Flash.tokens_per_handover.n_with_usage` |
| end-to-end latency per handover, mean (s) | 9.2848 | release/benchmarks/tf_bench_20261017T213905Z/results.json | `per_model.DeepSeek-V4-Flash.e2e_latency_s.mean` |
| end-to-end latency, p50 (s) | 6.1544 | release/benchmarks/tf_bench_20261017T213905Z/results.json | `per_model.DeepSeek-V4-Flash.e2e_latency_s.p50` |
| end-to-end latency, p95 (s) | 15.6161 | release/benchmarks/tf_bench_20261017T213905Z/results.json | `per_model.DeepSeek-V4-Flash.e2e_latency_s.p95` |
| handovers completed | 36 | release/benchmarks/tf_bench_20261017T213905Z/results.json | `per_model.DeepSeek-V4-Flash.n_completed` |
| handovers successful | 36 | release/benchmarks/tf_bench_20261017T213905Z/results.json | `per_model.DeepSeek-V4-Flash.success.count` |

Handover benchmark release/benchmarks/tf_bench_20261017T213905Z/results.json (created 2026-10-17T21:58:32.160+00:00, sha256 3b19d8822415, host developer.amd.com.cn).
Load test: not used (no live load test with per_model.DeepSeek-V4-Flash.throughput_handovers_per_s and per_model.DeepSeek-V4-Flash.concurrency under release/benchmarks/load_*/results.json: throughput is modelled for one sequential stream only).
Cross-model check: not used (no live cross-model check results under release/benchmarks/crosscheck_*/results.json: its cost is not measured).

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
| Tokens per caregiver update | 1,219 | tokens per handover (+ judge tokens per check if cross-checked) | tokens per handover; judge tokens per check | crosscheck_every_update |
| Tokens per family per day | 2,438 | tokens per update × updates per day | tokens per handover | updates_per_family_per_day, crosscheck_every_update |
| Tokens per family per month | 73,128 | × 30 days | tokens per handover | updates_per_family_per_day, crosscheck_every_update |
| Tokens per 1,000 families per day | 2,437,600 | × 1,000 | tokens per handover | updates_per_family_per_day, crosscheck_every_update |
| Seconds per update, one sequential stream | 9.28 | e2e latency mean (+ judge call p50 if cross-checked) | e2e latency mean; judge latency p50 | crosscheck_every_update |
| Handovers per stream-hour (sequential) | 387.7 | 3600 / seconds per update | e2e latency mean | crosscheck_every_update |
| Handovers per endpoint-hour at the load test's concurrency | n/a | throughput per s × 3600 | load test throughput | — |
| Busy hours per 1,000 families per day | 5.16 | 1,000 × updates per day / handovers per hour | capacity basis above | updates_per_family_per_day |
| Updates per care coordinator's caseload per day | 60 | families × updates per day | — | families_per_care_coordinator, updates_per_family_per_day |
| Tokens per care coordinator's caseload per day | 73,128 | families × tokens per family per day | tokens per handover | families_per_care_coordinator, updates_per_family_per_day |
| Busy hours per care coordinator's caseload per day | 0.15 | updates / handovers per hour | capacity basis above | families_per_care_coordinator, updates_per_family_per_day |
| Cost per family per month | n/a | tokens per month × price / 1e6 | tokens per handover | price_per_million_tokens |
| Cost per 1,000 families per day | n/a | tokens per day × price / 1e6 | tokens per handover | price_per_million_tokens |

Capacity basis for the busy-hour rows: sequential.

## Sensitivity (each assumption at -50% / base / +50%, the others at their values)

| Assumption | Setting | Value | Tokens / family / day | Tokens / family / month | Busy hours / 1,000 families / day | Tokens / coordinator / day | Cost / family / month |
|---|---|---|---|---|---|---|---|
| updates_per_family_per_day | -50% | 1.00 | 1,219 | 36,564 | 2.58 | 36,564 | n/a |
| updates_per_family_per_day | base | 2.00 | 2,438 | 73,128 | 5.16 | 73,128 | n/a |
| updates_per_family_per_day | +50% | 3.00 | 3,656 | 109,692 | 7.74 | 109,692 | n/a |
| families_per_care_coordinator | -50% | 15.00 | 2,438 | 73,128 | 5.16 | 36,564 | n/a |
| families_per_care_coordinator | base | 30.00 | 2,438 | 73,128 | 5.16 | 73,128 | n/a |
| families_per_care_coordinator | +50% | 45.00 | 2,438 | 73,128 | 5.16 | 109,692 | n/a |
| crosscheck_every_update | base | no | 2,438 | 73,128 | 5.16 | 73,128 | n/a |
| crosscheck_every_update | flipped | yes | n/a | n/a | n/a | n/a | n/a |

## Notes

- no live load test with per_model.DeepSeek-V4-Flash.throughput_handovers_per_s and per_model.DeepSeek-V4-Flash.concurrency under release/benchmarks/load_*/results.json: throughput is modelled for one sequential stream only.
- Not modelled: question answers and photo reads (not in the handover benchmark).
- Not modelled: peaks within a day and queueing: hours are busy time, not wall-clock hours.
- Not modelled: the endpoint's rate limits and other clients' load.
- Not modelled: the network path apart from the endpoint (the measured latency includes the path from the benchmark machine).
