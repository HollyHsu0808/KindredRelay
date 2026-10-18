English rendition of release/KAGGLE_RESULT_zh-TW.md at sha256 4e78f8a86e0da627e4beb1eb56cd89fb9d535a1d613c7e1f179ad9aea14de8df; numbers copied verbatim
Line N of this file renders line N of the source; lines that no published citation uses are left blank. Links into local run folders (release/validation_abd/, git-ignored, not published) are kept as plain text; team members' names are replaced by their role.








| Validation metric | Result |
|---|---:|
| Samples | 3644 |
| AUROC (unsupported) | 0.9800 |
| Selected support threshold | 0.9138681 |
| Overall unsupported false acceptance | 29/1648, 1.76% |
| Overall coverage | 42.12% |
| QA subgroup false acceptance | 9/131, 6.87% |


Threshold fitted on validation. The 5% false-acceptance target used to select the threshold applies per dataset/domain and was not constrained per task; the QA subgroup's false-acceptance rate is 6.87%, so the dataset-wide guarantee cannot be carried over to it. RAGTruth's false-acceptance Wilson 95% upper bound is 9.13%; Summary coverage is low. The overall result cannot replace per-task acceptance. The raw data is in the extracted package at `reports/validation_selection.json`; the externally downloaded report of the same name has the same content.













Therefore the site's verifier stays `off`; a shadow evaluation is possible, but enabling the gate is not yet appropriate. Next: first freeze the threshold, add an independent test from existing labelled datasets, check the product's claim format with fixed software cases, and then decide whether to adjust the training mix / task balance or retrain. This adds no custom clinical or event training labels, and the test must not be used to select thresholds repeatedly.
