English rendition of release/ROUND3_ENGINEERING_AND_EVALUATION_zh-TW.md at sha256 1442d77fc229d75379601434529928f40c2e83bff92835437f3874189265542c; numbers copied verbatim
Line N of this file renders line N of the source; lines that no published citation uses are left blank. Links into local run folders (release/validation_abd/, git-ignored, not published) are kept as plain text; team members' names are replaced by their role.







| Live deterministic validation | VERIFIED: 18 processes, 556 unittest cases, exit 0; the 88 tracked-by-runner sources were the same before and after | summary, runner log and exit receipt in `release/validation_abd/depth_round3_20261017/` (local run folder) |





| 40 heldout × 2 orders × 3 methods | VERIFIED: 240 fixed predictions completed, 24 failures kept; gold scoring opened only after the seal, score exit 0; the held-out set is consumed | [heldout result JSON](../../research/temporal_benchmark/results/round3_heldout_20261017.json); seal, pre-score check and score exit receipt in `release/validation_abd/depth_round3_20261017/model_round3/` (local run folder) |




































































The real dev and heldout inference on the existing free AMD Token Factory was completed, sealed and scored. 7 dev and 24 heldout failures are kept in the denominators, so both prediction runners exited 1 and both score runners exited 0; this must not be reported as every model request succeeding. The data is fictional English media already converted to text, not ASR/OCR, real patients or clinical validation. There was no tuning, and no rerun of this version's held-out set, after dev or after heldout scoring.







| Same-method conditions | `DeepSeek-V4-Flash` alias; temperature 0 / seed 0, 4000 output tokens, 60 seconds, no retry, guided JSON / verifier off |









































Resources: 113 physical / 160 logical calls, 47 Journal cache hits; physical accounted tokens were 237,939, including a conservative reserve for 3 unknown-usage requests, not exact billed tokens. USD is **UNPRICED**: a provider cost in an unknown currency cannot be treated as USD; the user stated explicitly that the existing service is free, but a 0 unit price is not treated as a verified paid bill. Journal cached wall time cannot be used as a fair uncached speed comparison, and is not AMD GPU performance evidence.









**VERIFIED / 40 independent stories, each in two valid orders, 80 per method, 240 in all.** The prediction summary records completion at `09:52:11 UTC`; the actual seal is at `09:52:13.874281 UTC`; the two times must not be merged. At `09:52:53 UTC` the pre-score check confirmed that everything was sealed and the failures were kept, and only then, at `09:52:57 UTC`, did gold scoring start; the score receipt is exit0. The prediction exit receipt is exit1 because of 24 operational failures. (Prediction summary, seal, pre-score check and receipts: `release/validation_abd/depth_round3_20261017/model_round3/`, local run folder.)



| Metric | Journal | Full context | Lexical RAG |
| --- | ---: | ---: | ---: |
| Strict all correct | 10/80, 12.50% | 11/80, 13.75% | 13/80, 16.25% |
| Phase correct | 54/80 | 44/80 | 51/80 |
| Family arrangements all correct | 59/80 | 46/80 | 50/80 |
| Event precision | 73/315, 23.17% | 47/125, 37.60% | 57/117, 48.72% |
| Event recall | 73/150, 48.67% | 47/150, 31.33% | 57/150, 38.00% |
| Time correct | 91/186 | 55/186 | 65/186 |
| Wrong definite phase, including a missing required supporting citation | 19/80 | 18/80 | 17/80 |
| Wrong definite time / output definite times, including unmatched extra events | 84/169 | 87/140 | 65/128 |
| Citations literally valid | 430/430 | 247/253 | 233/235 |
| Coverage of answerable questions | 69.23% | 84.62% | 88.46% |
| Equivalent-order endpoints agree | 35/40 | 8/40 | 18/40 |
| Operational failures, kept in the denominator | 1/80 | 13/80 | 10/80 |

The Journal−RAG strict difference is −3.75 percentage points, story-group bootstrap 95% interval `[−16.25,10.00]`; full context−Journal is 1.25 percentage points, interval `[−11.25,13.75]`. All paired intervals include 0: **no overall advantage of the Journal is established, and RAG is not claimed to be significantly better either**. In this batch the Journal is better on phase / time / recall / order agreement, but worse on precision and answerable coverage, so it cannot be called more accurate or safer overall.





Resources were 294 physical / 426 logical calls, 132 Journal cache hits; physical accounted tokens 678,294 include a reserve for 12 unknown-usage requests, not exact billed tokens. USD is UNPRICED and the provider currency is unknown; free as stated explicitly by the user; cached wall time is not a fair uncached architecture or AMD GPU performance comparison. The service alias, the underlying weights and an AMD GPU model still cannot be equated.






Limitations still include fictional English data written by an LLM author, no human clinical review, known differences in family-note permissions and some v1 labels, short stories / weak lexical RAG, and different inference workloads and caching. No gold was changed afterwards, no scope deleted and no cases picked. This data does not prove real recordings, vision, phones or clinical safety.
