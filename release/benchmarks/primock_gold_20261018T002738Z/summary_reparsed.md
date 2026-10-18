# PriMock57 external-reference evaluation (primock_gold_v1): offline re-parse of the stored annotator replies (no model call)

Changed by the re-parse: [{"consultation": "day4_consultation08", "task": "B", "labelled_before": 0, "labelled_after": 25, "ok_before": false, "ok_after": false, "problems_after": {"unknown_ids": 0, "invalid": 0, "duplicates": 0, "missing": 1, "coerced": 0, "parsed": true, "salvaged": true}}].

Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn). The hardware behind the endpoint is not visible to this client, so no specific GPU is claimed. Latency includes the network path from this machine to the endpoint.

- Created (UTC): 2026-10-18T02:25:51.037+00:00; protocol research/primock_gold_v1/PROTOCOL.md; preregistration written 2026-10-17T23:36:28.552+00:00, first live call 2026-10-18T00:27:38.190+00:00; written before the first live call: True; subset amendment research/primock_gold_v1/preregistration_amendment_1.json (30 of 57 consultations, seeded) written 2026-10-18T00:27:31.428+00:00, before the first live call: True.
- System under test: Episode.add_update(update, extractor=episode.llm_extractor(client), evidence_checker=None) per transcript part; generator `DeepSeek-V4-Flash` (prompted JSON, max_tokens 2000, verifier off); speaker-labelled turns, at most 3000 characters per part.
- Annotator: `Qwen3.8-Flash-Next` (extra body {"chat_template_kwargs": {"enable_thinking": false}}), blind to what produced the facts; 57/60 annotation calls fully labelled; problems {"unknown_ids": 40, "invalid": 1, "duplicates": 0, "missing": 67, "coerced": 0}.
- Consultations: 30 of 30 planned (data/raw/primock57_full); skipped (unreadable data): none; HTTP calls 165 (1 retries).

| Metric (pooled over consultations, 95% cluster-bootstrap CI) | Value |
|---|---|
| Note-fact recall | 58.2% [54.0, 61.8] (513/881, n = 30) |
| Contradiction rate (of accepted facts) | 5.9% [4.2, 7.6] (56/943, n = 29) |
| Severity-weighted error score (weight per note fact) | 0.682 [0.574, 0.800] (543/796, n = 27) |
| Grounding-check pass rate (accepted / proposed) | 81.4% [78.1, 84.4] (985/1210, n = 30) |
| Safety-net note facts covered | 78.6% [57.7, 93.1] (22/28, n = 22) |
| Accepted facts not in the note (not an error) | 28.8% [25.6, 32.0] (272/943, n = 29) |

Error taxonomy (counts; weights critical 5, major 3, minor 1): negation_polarity (critical) 23, dose_number (critical) 6, attribution_speaker (major) 1, temporal (major) 9, other_contradiction (major) 16, omission_safety_net (major) 3, omission_other (minor) 311; weighted total 543.

Recall by note section: allergies 6.7% [0.0, 13.6] (1/15, n = 10); examination 0.0% (no CI: n < 5) (0/4, n = 1); family_history 53.8% [25.9, 80.7] (14/26, n = 14); history 57.4% [49.8, 64.5] (252/439, n = 30); ice 50.0% (no CI: n < 5) (2/4, n = 2); impression 60.0% [50.5, 73.1] (48/80, n = 24); medications 65.3% [47.6, 81.4] (32/49, n = 22); plan 74.0% [67.4, 80.2] (94/127, n = 25); pmh 56.2% [32.5, 73.3] (27/48, n = 24); social_history 48.3% [37.1, 59.2] (43/89, n = 21).

Extraction parts: 103 (2 failed: {"timeout": 1, "truncated": 1}); facts proposed 1210, accepted 985; note facts 881.

| Consultation | status | parts | proposed | accepted | grounding pass | note facts | covered | recall | contradicts | not in note | weighted errors |
|---|---|---|---|---|---|---|---|---|---|---|---|
| day2_consultation06 | ok | 4 | 45 | 37 | 0.8222 | 37 | 21 | 0.5676 | 1 | 14 | 19 |
| day1_consultation11 | ok | 5 | 56 | 51 | 0.9107 | 28 | 20 | 0.7143 | 4 | 18 | 24 |
| day4_consultation09 | ok | 4 | 59 | 47 | 0.7966 | 66 | 44 | 0.6667 | 1 | 19 | 25 |
| day2_consultation01 | ok | 3 | 24 | 22 | 0.9167 | 13 | 6 | 0.4615 | 3 | 6 | 17 |
| day5_consultation05 | ok | 2 | 28 | 13 | 0.4643 | 30 | 11 | 0.3667 | 1 | 5 | 23 |
| day1_consultation14 | ok | 4 | 52 | 47 | 0.9038 | 33 | 21 | 0.6364 | 2 | 18 | 20 |
| day1_consultation15 | ok | 3 | 34 | 28 | 0.8235 | 23 | 13 | 0.5652 | 2 | 6 | 21 |
| day3_consultation07 | ok | 3 | 37 | 28 | 0.7568 | 22 | 15 | 0.6818 | 0 | 9 | 7 |
| day5_consultation02 | ok | 3 | 41 | 30 | 0.7317 | 23 | 12 | 0.5217 | 3 | 12 | 21 |
| day3_consultation10 | ok | 3 | 29 | 20 | 0.6897 | 27 | 13 | 0.4815 | 3 | 7 | 28 |
| day3_consultation03 | ok | 4 | 40 | 37 | 0.925 | 21 | 10 | 0.4762 | 6 | 13 | 36 |
| day1_consultation09 | ok | 4 | 36 | 30 | 0.8333 | 28 | 19 | 0.6786 | 0 | 7 | 9 |
| day2_consultation10 | ok | 4 | 48 | 37 | 0.7708 | 37 | 20 | 0.5405 | 0 | 7 | 17 |
| day5_consultation07 | extraction_incomplete | 3 | 27 | 22 | 0.8148 | 32 | 9 | 0.2812 | 1 | 7 | 28 |
| day1_consultation05 | ok | 4 | 48 | 41 | 0.8542 | 34 | 21 | 0.6176 | 3 | 8 | 21 |
| day3_consultation01 | ok | 3 | 33 | 25 | 0.7576 | 14 | 8 | 0.5714 | 1 | 10 | 8 |
| day5_consultation06 | ok | 3 | 44 | 34 | 0.7727 | 40 | 28 | 0.7 | 2 | 8 | 16 |
| day1_consultation12 | ok | 3 | 29 | 24 | 0.8276 | 31 | 14 | 0.4516 | 1 | 8 | 19 |
| day1_consultation01 | ok | 3 | 38 | 33 | 0.8684 | 28 | 21 | 0.75 | 3 | 4 | 17 |
| day1_consultation08 | ok | 3 | 42 | 33 | 0.7857 | 26 | 17 | 0.6538 | 2 | 7 | 14 |
| day5_consultation10 | ok | 4 | 46 | 31 | 0.6739 | 32 | 16 | 0.5 | 0 | 9 | 16 |
| day5_consultation08 | ok | 3 | 45 | 31 | 0.6889 | 37 | 18 | 0.4865 | 4 | 6 | 38 |
| day4_consultation06 | ok | 4 | 50 | 47 | 0.94 | 27 | 19 | 0.7037 | 0 | 12 | 8 |
| day2_consultation03 | ok | 3 | 45 | 38 | 0.8444 | 25 | 15 | 0.6 | 3 | 10 | 19 |
| day2_consultation08 | extraction_incomplete | 4 | 39 | 34 | 0.8718 | 44 | 24 | 0.5455 | 3 | 7 | 31 |
| day3_consultation06 | ok | 2 | 21 | 16 | 0.7619 | 10 | 5 | 0.5 | 2 | 4 | 12 |
| day4_consultation08 | annotation_incomplete | 4 | 36 | 26 | 0.7222 | 29 | 18 | 0.6207 | 1 | 8 | 15 |
| day4_consultation10 | ok | 4 | 50 | 44 | 0.88 | 28 | 19 | 0.6786 | 4 | 8 | 29 |
| day5_consultation11 | annotation_incomplete | 4 | 47 | 40 | 0.8511 | 35 | 24 | 0.6857 | 0 | 0 | 11 |
| day4_consultation01 | annotation_incomplete | 3 | 41 | 39 | 0.9512 | 21 | 12 | 0.5714 | 0 | 15 | 9 |

Human agreement sample: human_review.csv, 360 rows (20% of 1799 annotator decisions, rounded up, seed 20261018); Cohen's kappa: pending until a person fills human_label (`python -I scripts/primock_gold_eval.py kappa --csv <folder>/human_review.csv`).

Deviations from the preregistration: (1) 2026-10-17T23:42Z, after the pilot: added run --deadline-utc (start no consultation that would likely end after it; stopped_reason 'deadline'). Harness only. Reason: the pilot took about 4.5 minutes per consultation with sequential calls, so a full run of 57 may not finish before the results deadline; the seeded processing order keeps a stopped run a random subset, as the protocol states. (2) 2026-10-17T23:44Z, before the full run: a consultation whose note yields no note fact or whose transcripts yield no turn (unreadable data) is skipped and listed in results.data.skipped instead of being scored as all omissions. Harness only (a data guard); it does not change any consultation that has a note and a readable transcript. (3) 2026-10-17T23:54Z, before the full run: code fix to match the preregistered PROTOCOL.md: recall and the task B rates now count the labelled items of an incomplete annotation (the code had left such consultations out); the weighted score still uses consultations with both tasks complete. No effect on the pilot (both tasks complete). (4) 2026-10-17T23:55Z, before the full run: a reply cut off at max_tokens (or not one whole JSON object) is no longer dropped whole: its complete label items are recovered (salvage_items) and count, as PROTOCOL.md says the labelled items of an incomplete annotation do; the task stays incomplete. Reason: the pilot's task B reply used 3331 of the 4096 output tokens for 52 facts, so a longer consultation would be cut off. (5) 2026-10-18T00:28Z, before any live call of the full run: the full data arrived at 00:25Z; 57 consultations at about 4 minutes each, sequential, would not finish before the 03:30Z results deadline, so a seeded random subset of 30 (the first 30 of the preregistered processing order) was fixed in preregistration_amendment_1.json (`amend`, then `run --amendment`), with a deadline stop at 03:10Z. (6) 2026-10-18T02:30Z, after the full run, offline: the reader of annotator replies missed replies PROTOCOL.md says count: one that is invalid JSON only because of a raw line break inside a string (llm_client then returned one inner item, and every id counted as missing). read_reply now salvages any reply that is not one object with a labels list (strict=False decoding, else item by item); the task stays incomplete. `report --reparse` applies it to the stored replies (no call) and writes results_reparsed.json and summary_reparsed.md beside the as-run results.json and summary.md. Items whose id key is garbled (a token glitch) are not reinterpreted: they stay unknown ids, as preregistered.

Limitations: mock consultations (actors following case cards), primary care, not post-fall home care; English only; the reference note is a clinician's summary (it can state what was never said aloud, e.g. an impression, and leaves out much that was); a model annotator (one model, temperature 0) until the human sample is labelled; one generator run per consultation; transcripts are the human reference, not ASR. Engineering measurement, not clinical validation.

Data: PriMock57 (Korfiatis et al., 2022; Babylon Health), CC BY 4.0; see ATTRIBUTION.txt.
