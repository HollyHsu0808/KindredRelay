# Fact stability across repeats: `DeepSeek-V4-Flash`, `Gemma-4-31B-IT`

- Bench run: `release/benchmarks/tf_bench_20261017T213905Z` (records.jsonl sha256 `07043f944220b658`; results.json sha256 `3b19d88224156564`); story `handoff_day1/care_cases/episode_hip_fracture.json` (sha256 `b2532dd3164b8085`, the run's); 12 updates x 3 repeats x 2 models, 72 completed cases used.
- Fact key: per update, over every model's and repeat's accepted facts: the connected components of the bench's agreement heuristic (scripts/bench_tf_handover.py reference_match: same type, and one quote contains the other after episode.norm); a key is named by its type and its shortest normalized quote; a repeat's fact set is the set of keys of its accepted facts (two facts of one repeat in one key count once). The heuristic is imported from `scripts/bench_tf_handover.py` (sha256 matches the run's).
- Keys: 50 over the 12 updates; 14 group several distinct quotes (3 bridged through a third quote); 10 accepted fact(s) shared a key with another fact of the same repeat. All are listed in results.json (`diagnostics.merged_keys`).

## 1. Within-model repeat agreement

| Model | updates | mean pairwise Jaccard [95% CI] | per-update min / max | keys | in 3/3 | in 2/3 | in 1/3 |
|---|---|---|---|---|---|---|---|
| `DeepSeek-V4-Flash` | 12 | 0.900 [0.79, 1.00] | 0.472 / 1.000 | 47 | 40 (85.1%) | 4 (8.5%) | 3 (6.4%) |
| `Gemma-4-31B-IT` | 12 | 1.000 [1.00, 1.00] | 1.000 / 1.000 | 37 | 37 (100.0%) | 0 (0.0%) | 0 (0.0%) |

## 2. Per update and cross-model agreement

| Update | `DeepSeek-V4-Flash` Jaccard | `Gemma-4-31B-IT` Jaccard | `DeepSeek-V4-Flash` keys 3/2/1 | `Gemma-4-31B-IT` keys 3/2/1 | majority-vote Jaccard, DeepSeek-V4-Flash vs Gemma-4-31B-IT |
|---|---|---|---|---|---|
| u01 | 1.000 | 1.000 | 4/0/0 | 3/0/0 | 0.400 (2 shared of 4 / 3) |
| u02 | 1.000 | 1.000 | 6/0/0 | 5/0/0 | 0.833 (5 shared of 6 / 5) |
| u03 | 1.000 | 1.000 | 4/0/0 | 4/0/0 | 1.000 (4 shared of 4 / 4) |
| u04 | 0.556 | 1.000 | 1/1/1 | 1/0/0 | 0.500 (1 shared of 2 / 1) |
| u05 | 1.000 | 1.000 | 3/0/0 | 3/0/0 | 1.000 (3 shared of 3 / 3) |
| u06 | 1.000 | 1.000 | 2/0/0 | 2/0/0 | 1.000 (2 shared of 2 / 2) |
| u07 | 0.472 | 1.000 | 1/2/1 | 3/0/0 | 1.000 (3 shared of 3 / 3) |
| u07b | 1.000 | 1.000 | 3/0/0 | 2/0/0 | 0.667 (2 shared of 3 / 2) |
| u07c | 1.000 | 1.000 | 3/0/0 | 3/0/0 | 1.000 (3 shared of 3 / 3) |
| u08 | 1.000 | 1.000 | 5/0/0 | 5/0/0 | 1.000 (5 shared of 5 / 5) |
| u09 | 0.778 | 1.000 | 4/1/1 | 5/0/0 | 0.667 (4 shared of 5 / 5) |
| u10 | 1.000 | 1.000 | 4/0/0 | 1/0/0 | 0.000 (0 shared of 4 / 1) |

- DeepSeek-V4-Flash vs Gemma-4-31B-IT: mean majority-vote Jaccard 0.756 [0.58, 0.92] (95% bootstrap CI over 12 updates), per update 0.000 to 1.000.

## 3. Is stability a usable confidence signal?

(a) Grounding-check acceptance: not computable from these records: a case record keeps its accepted facts (fact_id, type, quote) but a rejected fact only as a reason string (rejection_reasons), with no type or quote, and no model reply is stored, so a rejected fact cannot be given a key; every keyed fact here passed the grounding check by construction.

(b) Agreement with the story's recorded extraction, one row per bucket of (model, update, key) units: matched / n (rate) [Wilson 95%]. The reference is the story's recorded extraction (the fixture's curated facts for each update), matched with the bench's heuristic (same type, one quote contains the other); it is not clinical ground truth and not a quality score.

| Bucket | pooled | `DeepSeek-V4-Flash` | `Gemma-4-31B-IT` |
|---|---|---|---|
| in 3/3 repeats | 61/77 (79.2%) [0.69, 0.87] | 32/40 (80.0%) [0.65, 0.90] | 29/37 (78.4%) [0.63, 0.89] |
| in 2/3 repeats | 2/4 (50.0%) [0.15, 0.85] | 2/4 (50.0%) [0.15, 0.85] | 0/0 (n/a) |
| in 1/3 repeats | 0/3 (0.0%) [0.00, 0.56] | 0/3 (0.0%) [0.00, 0.56] | 0/0 (n/a) |
| in 1-2 of 3 repeats | 2/7 (28.6%) [0.08, 0.64] | 2/7 (28.6%) [0.08, 0.64] | 0/0 (n/a) |
| other model also produced it | 56/68 (82.3%) [0.72, 0.90] | 28/34 (82.3%) [0.66, 0.92] | 28/34 (82.3%) [0.66, 0.92] |
| only this model produced it | 7/16 (43.8%) [0.23, 0.67] | 6/13 (46.2%) [0.23, 0.71] | 1/3 (33.3%) [0.06, 0.79] |

Pooled, by repeat count and the other model:

| Repeat count | other model also produced it | only this model |
|---|---|---|
| 3/3 | 54/65 (83.1%) [0.72, 0.90] | 7/12 (58.3%) [0.32, 0.81] |
| 2/3 | 2/3 (66.7%) [0.21, 0.94] | 0/1 (0.0%) [0.00, 0.79] |
| 1/3 | 0/0 (n/a) | 0/3 (0.0%) [0.00, 0.56] |

## Takeaway

Across 3 repeats of the same update, the accepted facts were reproduced with a mean pairwise Jaccard of `DeepSeek-V4-Flash` 0.900 [0.79, 1.00] and `Gemma-4-31B-IT` 1.000 [1.00, 1.00] (95% bootstrap CI over updates), and 85.1% and 100.0% of the respective fact keys appeared in all 3 repeats. The two models' majority-vote fact sets agreed with a mean Jaccard of 0.756 [0.58, 0.92] over 12 updates (per update 0.000 to 1.000). On this run, stability went with agreement with the story's recorded extraction (both splits' Wilson 95% intervals are apart): keys seen in all 3 repeats matched it 79.2% of the time (61/77) against 28.6% (2/7) for keys seen in fewer, and keys both models produced 82.3% (56/68) against 43.8% (7/16) for keys only one model produced; but the less stable buckets are small, the 12 updates come from one fictional story, the reference is a curated fixture rather than clinical ground truth, and grounding-check acceptance could not be tested because the records keep no rejected facts.

## Caveats

- The reference is the story's recorded extraction (the demo fixture's curated facts), matched by the bench's heuristic (same type, one quote contains the other). It is not clinical ground truth and not a quality score: a correct fact the fixture does not list, or one the model typed differently, counts as unmatched.
- n is small: 12 updates of one fictional story, 3 repeats, 2 models. The bootstrap resamples updates; the Wilson intervals treat each (model, update, key) as independent, which keys of one update or of both models are not, so the intervals are optimistic.
- Grounding-check acceptance could not be related to stability: the records keep rejected facts only as reason strings (no type, no quote, no stored reply). Every key is an accepted fact.
- Keys come from quote containment, chained through a group: 14 key(s) group several distinct quotes and 3 are bridged (two quotes joined only through a third, e.g. two half-sentence facts and one whole-sentence fact). A model that splits a sentence into two facts in one repeat and quotes it whole in another counts as stable; facts of different types never share a key.
- A key's reference match counts any of the model's member quotes, so a key seen in more repeats has slightly more chances to match.
- The other-model split and the reference match use the same test (same type, one quote contains the other), so a fact given an unusual type fails both: part of that split measures agreement on the type label, not only on the content.
- Repeat variation is what the endpoint returned under the bench's settings (see its results.json); the analysis does not know the sampling parameters.
