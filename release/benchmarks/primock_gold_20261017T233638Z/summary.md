# PriMock57 external-reference evaluation (primock_gold_v1)

Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible API, host developer.amd.com.cn). The hardware behind the endpoint is not visible to this client, so no specific GPU is claimed. Latency includes the network path from this machine to the endpoint.

- Created (UTC): 2026-10-18T02:25:51.876+00:00; protocol research/primock_gold_v1/PROTOCOL.md; preregistration written 2026-10-17T23:36:28.552+00:00, first live call 2026-10-17T23:36:38.427+00:00; written before the first live call: True.
- System under test: Episode.add_update(update, extractor=episode.llm_extractor(client), evidence_checker=None) per transcript part; generator `DeepSeek-V4-Flash` (prompted JSON, max_tokens 2000, verifier off); speaker-labelled turns, at most 3000 characters per part.
- Annotator: `Qwen3.8-Flash-Next` (extra body {"chat_template_kwargs": {"enable_thinking": false}}), blind to what produced the facts; 2/2 annotation calls fully labelled; problems {"unknown_ids": 0, "invalid": 0, "duplicates": 0, "missing": 0, "coerced": 0}.
- Consultations: 1 of 1 planned (data/raw/primock57); skipped (unreadable data): none; HTTP calls 7 (0 retries).

| Metric (pooled over consultations, 95% cluster-bootstrap CI) | Value |
|---|---|
| Note-fact recall | 84.2% (no CI: n < 5) (32/38, n = 1) |
| Contradiction rate (of accepted facts) | 0.0% (no CI: n < 5) (0/52, n = 1) |
| Severity-weighted error score (weight per note fact) | 0.158 (no CI: n < 5) (6/38, n = 1) |
| Grounding-check pass rate (accepted / proposed) | 86.7% (no CI: n < 5) (52/60, n = 1) |
| Safety-net note facts covered | 100.0% (no CI: n < 5) (2/2, n = 1) |
| Accepted facts not in the note (not an error) | 26.9% (no CI: n < 5) (14/52, n = 1) |

Error taxonomy (counts; weights critical 5, major 3, minor 1): negation_polarity (critical) 0, dose_number (critical) 0, attribution_speaker (major) 0, temporal (major) 0, other_contradiction (major) 0, omission_safety_net (major) 0, omission_other (minor) 6; weighted total 6.

Recall by note section: allergies 0.0% (no CI: n < 5) (0/1, n = 1); family_history 100.0% (no CI: n < 5) (1/1, n = 1); history 86.4% (no CI: n < 5) (19/22, n = 1); impression 100.0% (no CI: n < 5) (1/1, n = 1); medications 100.0% (no CI: n < 5) (1/1, n = 1); plan 83.3% (no CI: n < 5) (5/6, n = 1); pmh 100.0% (no CI: n < 5) (1/1, n = 1); social_history 80.0% (no CI: n < 5) (4/5, n = 1).

Extraction parts: 4 (0 failed: {}); facts proposed 60, accepted 52; note facts 38.

| Consultation | status | parts | proposed | accepted | grounding pass | note facts | covered | recall | contradicts | not in note | weighted errors |
|---|---|---|---|---|---|---|---|---|---|---|---|
| day1_consultation04 | ok | 4 | 60 | 52 | 0.8667 | 38 | 32 | 0.8421 | 0 | 14 | 6 |

Human agreement sample: human_review.csv, 18 rows (20% of 90 annotator decisions, rounded up, seed 20261018); Cohen's kappa: pending until a person fills human_label (`python -I scripts/primock_gold_eval.py kappa --csv <folder>/human_review.csv`).

Deviations from the preregistration: (1) 2026-10-17T23:42Z, after the pilot: added run --deadline-utc (start no consultation that would likely end after it; stopped_reason 'deadline'). Harness only. Reason: the pilot took about 4.5 minutes per consultation with sequential calls, so a full run of 57 may not finish before the results deadline; the seeded processing order keeps a stopped run a random subset, as the protocol states. (2) 2026-10-17T23:44Z, before the full run: a consultation whose note yields no note fact or whose transcripts yield no turn (unreadable data) is skipped and listed in results.data.skipped instead of being scored as all omissions. Harness only (a data guard); it does not change any consultation that has a note and a readable transcript. (3) 2026-10-17T23:54Z, before the full run: code fix to match the preregistered PROTOCOL.md: recall and the task B rates now count the labelled items of an incomplete annotation (the code had left such consultations out); the weighted score still uses consultations with both tasks complete. No effect on the pilot (both tasks complete). (4) 2026-10-17T23:55Z, before the full run: a reply cut off at max_tokens (or not one whole JSON object) is no longer dropped whole: its complete label items are recovered (salvage_items) and count, as PROTOCOL.md says the labelled items of an incomplete annotation do; the task stays incomplete. Reason: the pilot's task B reply used 3331 of the 4096 output tokens for 52 facts, so a longer consultation would be cut off. (5) 2026-10-18T00:28Z, before any live call of the full run: the full data arrived at 00:25Z; 57 consultations at about 4 minutes each, sequential, would not finish before the 03:30Z results deadline, so a seeded random subset of 30 (the first 30 of the preregistered processing order) was fixed in preregistration_amendment_1.json (`amend`, then `run --amendment`), with a deadline stop at 03:10Z. (6) 2026-10-18T02:30Z, after the full run, offline: the reader of annotator replies missed replies PROTOCOL.md says count: one that is invalid JSON only because of a raw line break inside a string (llm_client then returned one inner item, and every id counted as missing). read_reply now salvages any reply that is not one object with a labels list (strict=False decoding, else item by item); the task stays incomplete. `report --reparse` applies it to the stored replies (no call) and writes results_reparsed.json and summary_reparsed.md beside the as-run results.json and summary.md. Items whose id key is garbled (a token glitch) are not reinterpreted: they stay unknown ids, as preregistered.

Limitations: mock consultations (actors following case cards), primary care, not post-fall home care; English only; the reference note is a clinician's summary (it can state what was never said aloud, e.g. an impression, and leaves out much that was); a model annotator (one model, temperature 0) until the human sample is labelled; one generator run per consultation; transcripts are the human reference, not ASR. Engineering measurement, not clinical validation.

Data: PriMock57 (Korfiatis et al., 2022; Babylon Health), CC BY 4.0; see ATTRIBUTION.txt.
