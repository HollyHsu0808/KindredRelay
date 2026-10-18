English rendition of release/TEMPORAL_EXPERIMENT_ROUND1_zh-TW.md at sha256 78bebebb62517306837eb43ca52421b41050db67abd26e4dacb51962a9738eec; numbers copied verbatim
Line N of this file renders line N of the source; lines that no published citation uses are left blank. Links into local run folders (release/validation_abd/, git-ignored, not published) are kept as plain text; team members' names are replaced by their role.
























| Metric | Journal | Full context | Lexical RAG |
| --- | ---: | ---: | ---: |
| All correct | 6/32, 18.75% | 7/32, 21.88% | 8/32, 25.00% |
| Current phase label correct | 26/32, 81.25% | 20/32, 62.50% | 21/32, 65.63% |
| Event precision | 34/108, 31.48% | 24/47, 51.06% | 23/47, 48.94% |
| Event recall | 34/60, 56.67% | 24/60, 40.00% | 23/60, 38.33% |
| Event / family arrangement time correct | 42/74, 56.76% | 30/74, 40.54% | 29/74, 39.19% |
| Equivalent-order endpoints agree | 16/16, 100% | 4/16, 25% | 4/16, 25% |
| Execution failures | 0/32 | 3/32 | 4/32 |

The full raw-derived metrics, group comparisons, source hashes, trusted seal fingerprints and execution receipt metrics are kept in the [machine-readable result](../../research/temporal_benchmark/results/round1_dev_20261017.json). The raw scores are in scores.json (`release/validation_abd/temporal_round1_20261017/dev_score/scores.json`, local run folder).

The main accuracy difference between Journal and RAG is **−6.25 percentage points**, with an exploratory 95% interval from a paired bootstrap grouped by original story of **[−37.5, 25.0] percentage points**; full context minus Journal is **3.125 percentage points**, interval **[−28.125, 31.25]**. The sample is small and the intervals wide: no significance or clinical conclusion is drawn, still less a claim of overall victory by picking phase or the agreement rate alone.
