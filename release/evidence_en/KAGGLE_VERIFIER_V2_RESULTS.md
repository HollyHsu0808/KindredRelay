English rendition of release/KAGGLE_VERIFIER_V2_RESULTS_zh-TW.md at sha256 e8da1b98c52618e00a1d30f8c83b46af5f6121ec5a1c27fd337a2c97e431645f; numbers copied verbatim
Line N of this file renders line N of the source; lines that no published citation uses are left blank. Links into local run folders (release/validation_abd/, git-ignored, not published) are kept as plain text; team members' names are replaced by their role.
**Verified:** the full training artifacts of `v2_20261017_retry01` were downloaded and their integrity was checked locally. They provide an independently trained candidate module for "does the source support the claim", but calibration found no threshold that meets the preset criteria: **deployment acceptance did not pass; the v2 gate is not enabled in this round**. This result cannot be used as evidence that the timeline, latest status, speech recognition, photo reading or clinical safety have passed. This round did not start the verifier's one-shot heldout test, and did not inspect or change the verifier setting of the running site.


















**Verified:** the overall AUROC of the independent calibration is **0.961569**, but performance differs widely between data sources. AUROC in the table below treats unsupported as the positive class; AUROC must not be read as accuracy or as a clinical risk probability.

| Calibration scope | pairs | supported / unsupported | AUROC |
| --- | ---: | ---: | ---: |
| All | 4,091 | 2,231 / 1,860 | 0.961569 |
| MedHallu | 3,227 | 1,613 / 1,614 | 0.981224 |
| RAGTruth | 864 | 618 / 246 | 0.753065 |
| MedHallu / pqa_artificial | 2,891 | 1,445 / 1,446 | 0.981746 |
| MedHallu / pqa_labeled | 336 | 168 / 168 | 0.977360 |
| RAGTruth / QA | 635 | 456 / 179 | 0.778300 |
| RAGTruth / Summary | 228 | 162 / 66 | 0.673214 |






1. Among the scopes that have at least 50 supported and 50 unsupported examples, there is still no shared threshold that meets every scope's FAR ≤ 5% and supported acceptance ≥ 10% at the same time. Recomputing all **4,048 candidate thresholds**, the number of valid shared thresholds is **0**; `candidate_operating_point_found=false`.
2. The Data2txt calibration has only one unsupported example and also fails the preset sample-sufficiency requirement. Therefore `validation_operating_point_found=false`; the task must not be deleted, nor the rules relaxed after the fact, to rewrite this round as a success.


































The next step is to turn this failure diagnosis into a new experiment that can be preregistered, not to rerun the same training and expect the numbers to improve on their own:

- **The v2 gate is not enabled in this round.** If a shadow study is needed later, store the score, source identity, the original judgement and human-checkable failure samples separately, and state plainly that it has no usable enabling threshold; this report did not perform that site wiring, and does not presume that the current site has loaded this model.
- **Close the Summary and long-input coverage gaps in a new version.** Hypothesis not yet tested: while keeping the source-grouped leakage protection, examine hard cases, negation / number / cross-sentence evidence, and compare weighting, training objectives and full-evidence length strategies in advance. The 512-token full-input filter has left Data2txt with almost no eligible data; truncating sources while inheriting the original labels, or deleting a scope after the fact, must not be used to pass this round. The new task scope and acceptance criteria must be defined explicitly before the new experiment.
- **Start the one-shot heldout test only when needed.** First decide whether to include a trusted v1 baseline, and verify its own original fixed threshold and the same full-input eligible population; the baseline must not be run only after seeing the v2 test. The test does not retrain or reset thresholds, and once `<run>/test/` is created one chance is consumed, including an interruption. The contract is in train_verifier.py:55 (`training/verifier_v2/train_verifier.py`) and its README (`training/verifier_v2/README_zh-TW.md`). This round keeps the test and does not consume it for tuning.
