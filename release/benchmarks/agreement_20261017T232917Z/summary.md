# Fact stability across repeats: `DeepSeek-V4-Flash`, `Gemma-4-31B-IT`

- Bench run: `release/benchmarks/tf_bench_20261017T230311Z` (records.jsonl sha256 `4bd833d2fb8710a4`; results.json sha256 `05af8036a9ef51e8`); story `handoff_day1/care_cases/episode_hip_fracture.json` (sha256 `b2532dd3164b8085`, the run's); 12 updates x 3 repeats x 2 models, 71 completed cases used.
- Fact key: per update, over every model's and repeat's accepted facts: the connected components of the bench's agreement heuristic (scripts/bench_tf_handover.py reference_match: same type, and one quote contains the other after episode.norm); a key is named by its type and its shortest normalized quote; a repeat's fact set is the set of keys of its accepted facts (two facts of one repeat in one key count once). The heuristic is imported from `scripts/bench_tf_handover.py` (sha256 matches the run's).
- Keys: 51 over the 12 updates; 15 group several distinct quotes (3 bridged through a third quote); 11 accepted fact(s) shared a key with another fact of the same repeat. All are listed in results.json (`diagnostics.merged_keys`).

## 1. Within-model repeat agreement

| Model | updates | mean pairwise Jaccard [95% CI] | per-update min / max | keys | in 3/3 | in 2/3 | in 1/3 |
|---|---|---|---|---|---|---|---|
| `DeepSeek-V4-Flash` | 11 | 0.854 [0.74, 0.95] | 0.417 / 1.000 | 44 | 34 (77.3%) | 6 (13.6%) | 4 (9.1%) |
| `Gemma-4-31B-IT` | 12 | 0.989 [0.97, 1.00] | 0.867 / 1.000 | 37 | 36 (97.3%) | 0 (0.0%) | 1 (2.7%) |

## 2. Per update and cross-model agreement

| Update | `DeepSeek-V4-Flash` Jaccard | `Gemma-4-31B-IT` Jaccard | `DeepSeek-V4-Flash` keys 3/2/1 | `Gemma-4-31B-IT` keys 3/2/1 | majority-vote Jaccard, DeepSeek-V4-Flash vs Gemma-4-31B-IT |
|---|---|---|---|---|---|
| u01 | 1.000 | 1.000 | 4/0/0 | 3/0/0 | 0.400 (2 shared of 4 / 3) |
| u02 | 0.889 | 1.000 | 5/1/0 | 5/0/0 | 0.833 (5 shared of 6 / 5) |
| u03 | 0.667 | 1.000 | 2/2/0 | 4/0/0 | 1.000 (4 shared of 4 / 4) |
| u04 | 0.417 | 1.000 | 1/1/2 | 1/0/0 | 0.500 (1 shared of 2 / 1) |
| u05 | 1.000 | 1.000 | 3/0/0 | 3/0/0 | 1.000 (3 shared of 3 / 3) |
| u06 | 1.000 | 1.000 | 2/0/0 | 2/0/0 | 1.000 (2 shared of 2 / 2) |
| u07 | n/a | 1.000 | n/a | 3/0/0 | n/a |
| u07b | 1.000 | 1.000 | 3/0/0 | 2/0/0 | 0.667 (2 shared of 3 / 2) |
| u07c | 0.778 | 1.000 | 2/0/1 | 3/0/0 | 0.667 (2 shared of 2 / 3) |
| u08 | 0.867 | 1.000 | 4/1/0 | 5/0/0 | 1.000 (5 shared of 5 / 5) |
| u09 | 0.778 | 0.867 | 4/1/1 | 4/0/1 | 0.500 (3 shared of 5 / 4) |
| u10 | 1.000 | 1.000 | 4/0/0 | 1/0/0 | 0.000 (0 shared of 4 / 1) |

- DeepSeek-V4-Flash vs Gemma-4-31B-IT: mean majority-vote Jaccard 0.688 [0.51, 0.85] (95% bootstrap CI over 11 updates), per update 0.000 to 1.000.

## 3. Is stability a usable confidence signal?

(a) Grounding-check acceptance, one row per bucket of (model, update, proposal key) units: a unit counts as accepted when every one of the model's proposals in the key passed the grounding check; accepted / n (rate) [Wilson 95%]. Proposal keys are built like the fact keys but over accepted and rejected proposals together (a proposal is a fact the model proposed that the grounding check judged (episode.grounding_problem): accepted_facts plus rejected_facts of the case record; facts the evidence gate withheld are in neither); the repeat count and the other model refer to proposals. The last column counts proposals instead of keys.

| Bucket | pooled keys | `DeepSeek-V4-Flash` keys | `Gemma-4-31B-IT` keys | pooled proposals |
|---|---|---|---|---|
| in 3/3 repeats | 68/80 (85.0%) [0.76, 0.91] | 33/37 (89.2%) [0.75, 0.96] | 35/43 (81.4%) [0.67, 0.90] | 228/255 (89.4%) [0.85, 0.93] |
| in 2/3 repeats | 3/4 (75.0%) [0.30, 0.95] | 3/4 (75.0%) [0.30, 0.95] | 0/0 (n/a) | 7/8 (87.5%) [0.53, 0.98] |
| in 1/3 repeats | 3/3 (100.0%) [0.44, 1.00] | 3/3 (100.0%) [0.44, 1.00] | 0/0 (n/a) | 3/3 (100.0%) [0.44, 1.00] |
| in 1-2 of 3 repeats | 6/7 (85.7%) [0.49, 0.97] | 6/7 (85.7%) [0.49, 0.97] | 0/0 (n/a) | 10/11 (90.9%) [0.62, 0.98] |
| other model also proposed it | 59/70 (84.3%) [0.74, 0.91] | 30/35 (85.7%) [0.71, 0.94] | 29/35 (82.9%) [0.67, 0.92] | 198/220 (90.0%) [0.85, 0.93] |
| only this model proposed it | 12/14 (85.7%) [0.60, 0.96] | 9/9 (100.0%) [0.70, 1.00] | 3/5 (60.0%) [0.23, 0.88] | 31/37 (83.8%) [0.69, 0.92] |

Pooled keys, by repeat count and the other model:

| Repeat count | other model also proposed it | only this model |
|---|---|---|
| 3/3 | 56/66 (84.9%) [0.74, 0.92] | 9/11 (81.8%) [0.52, 0.95] |
| 2/3 | 2/3 (66.7%) [0.21, 0.94] | 1/1 (100.0%) [0.21, 1.00] |
| 1/3 | 1/1 (100.0%) [0.21, 1.00] | 2/2 (100.0%) [0.34, 1.00] |

Proposals in the used pairs: 266 (238 accepted, 28 rejected by the grounding check; 0 withheld by the evidence gate, not included); 87 (model, update, proposal key) units, 7 with both accepted and rejected proposals; 0 rejected proposal(s) without a text quote. Rejection reasons: 14 x missing what; 4 x missing hours; 3 x quote not found in the update; 3 x quote shorter than 3 words; 2 x when is not text; 1 x dose is not text.

(b) Agreement with the story's recorded extraction, one row per bucket of (model, update, key) units: matched / n (rate) [Wilson 95%]. The reference is the story's recorded extraction (the fixture's curated facts for each update), matched with the bench's heuristic (same type, one quote contains the other); it is not clinical ground truth and not a quality score.

| Bucket | pooled | `DeepSeek-V4-Flash` | `Gemma-4-31B-IT` |
|---|---|---|---|
| in 3/3 repeats | 57/70 (81.4%) [0.71, 0.89] | 29/34 (85.3%) [0.70, 0.94] | 28/36 (77.8%) [0.62, 0.88] |
| in 2/3 repeats | 3/6 (50.0%) [0.19, 0.81] | 3/6 (50.0%) [0.19, 0.81] | 0/0 (n/a) |
| in 1/3 repeats | 2/5 (40.0%) [0.12, 0.77] | 1/4 (25.0%) [0.05, 0.70] | 1/1 (100.0%) [0.21, 1.00] |
| in 1-2 of 3 repeats | 5/11 (45.5%) [0.21, 0.72] | 4/10 (40.0%) [0.17, 0.69] | 1/1 (100.0%) [0.21, 1.00] |
| other model also produced it | 52/62 (83.9%) [0.73, 0.91] | 26/31 (83.9%) [0.67, 0.93] | 26/31 (83.9%) [0.67, 0.93] |
| only this model produced it | 8/16 (50.0%) [0.28, 0.72] | 7/13 (53.8%) [0.29, 0.77] | 1/3 (33.3%) [0.06, 0.79] |

Pooled, by repeat count and the other model:

| Repeat count | other model also produced it | only this model |
|---|---|---|
| 3/3 | 48/55 (87.3%) [0.76, 0.94] | 7/12 (58.3%) [0.32, 0.81] |
| 2/3 | 3/5 (60.0%) [0.23, 0.88] | 0/1 (0.0%) [0.00, 0.79] |
| 1/3 | 1/2 (50.0%) [0.09, 0.91] | 1/3 (33.3%) [0.06, 0.79] |

## Takeaway

Across 3 repeats of the same update, the accepted facts were reproduced with a mean pairwise Jaccard of `DeepSeek-V4-Flash` 0.854 [0.74, 0.95] and `Gemma-4-31B-IT` 0.989 [0.97, 1.00] (95% bootstrap CI over updates), and 77.3% and 97.3% of the respective fact keys appeared in all 3 repeats. The two models' majority-vote fact sets agreed with a mean Jaccard of 0.688 [0.51, 0.85] over 11 updates (per update 0.000 to 1.000). On this run, stability did not clearly separate agreement with the story's recorded extraction (at least one split's Wilson 95% intervals overlap or a bucket is empty): keys seen in all 3 repeats matched it 81.4% of the time (57/70) against 45.5% (5/11) for keys seen in fewer, and keys both models produced 83.9% (52/62) against 50.0% (8/16) for keys only one model produced; but the less stable buckets are small, the 11 updates come from one fictional story, the reference is a curated fixture rather than clinical ground truth. The grounding check rejected 28 of the 266 proposals; by proposal key, stability did not clearly separate passing it (at least one split's Wilson 95% intervals overlap or a bucket is empty): keys proposed in all 3 repeats had every proposal accepted 85.0% of the time (68/80) against 85.7% (6/7) for keys proposed in fewer, and keys both models proposed 84.3% (59/70) against 85.7% (12/14) for keys only one model proposed.

## Caveats

- The reference is the story's recorded extraction (the demo fixture's curated facts), matched by the bench's heuristic (same type, one quote contains the other). It is not clinical ground truth and not a quality score: a correct fact the fixture does not list, or one the model typed differently, counts as unmatched.
- n is small: 12 updates of one fictional story, 3 repeats, 2 models. The bootstrap resamples updates; the Wilson intervals treat each (model, update, key) as independent, which keys of one update or of both models are not, so the intervals are optimistic.
- Grounding-check acceptance (3a) uses proposal keys, built like the fact keys over accepted and rejected proposals together, so they can differ from the accepted-fact keys of sections 1, 2 and 3(b) (a rejected proposal can join two accepted keys or stand alone). The check is deterministic: a proposal repeated word for word gets the same verdict, so a key's repeat count measures how often the model re-proposed it, not independent re-checks. A key counts as accepted only when all of the model's proposals in it passed, so a key proposed in more repeats has more chances to fail; the proposal column counts each proposal, which treats repeats of one proposal as independent and is more optimistic still.
- Keys come from quote containment, chained through a group: 15 key(s) group several distinct quotes and 3 are bridged (two quotes joined only through a third, e.g. two half-sentence facts and one whole-sentence fact). A model that splits a sentence into two facts in one repeat and quotes it whole in another counts as stable; facts of different types never share a key.
- A key's reference match counts any of the model's member quotes, so a key seen in more repeats has slightly more chances to match.
- The other-model split and the reference match use the same test (same type, one quote contains the other), so a fact given an unusual type fails both: part of that split measures agreement on the type label, not only on the content.
- Repeat variation is what the endpoint returned under the bench's settings (see its results.json); the analysis does not know the sampling parameters.
