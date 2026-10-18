# primock_gold_v1: external-reference evaluation against clinician-written notes (PriMock57)

Status: protocol fixed before any live call. `preregistration.json` (same folder) records the time it was written and
the SHA-256 of this file, of `ANNOTATION_GUIDE.md`, of the annotator's fixed prompt parts and of the analysis settings;
`scripts/primock_gold_eval.py run` refuses a live call when any of them no longer matches. A change after the
preregistration is a deviation: it is listed in the results with its reason, never silently applied.

## Why

Every correctness number KindredRelay had so far is self-referential: the team wrote the story, the expected
extraction, the attacks and the judge prompt. This evaluation measures the extractor against a reference the team did
not write: the notes that the consulting clinicians wrote for the PriMock57 mock consultations.

## Data

- PriMock57 (Korfiatis et al., 2022; Babylon Health; https://github.com/babylonhealth/primock57; CC BY 4.0, licence in
  `data/raw/primock57/LICENSE.md`). 57 mock primary-care consultations: clinicians and actors following case cards.
  Per consultation: manual utterance-level transcripts of both channels (Praat TextGrids) and the consulting
  clinician's note (`notes/<id>.json`, field `note`).
- Pilot: `day1_consultation04` from `data/raw/primock57/` (the one consultation present locally).
- Full run: every consultation in `data/raw/primock57_full/` that has a note and both TextGrids (fetched by the user;
  agents never download data).
- Attribution: every output folder carries `ATTRIBUTION.txt` (source, licence, the changes made). Derived excerpts
  (note facts, transcript quotes) appear in the records, the human review sheet and the context file.

## Unit and system under test

- Unit: one consultation.
- System under test: the production extractor, unchanged and imported: `episode.llm_extractor(client)` called by
  `Episode.add_update(update, extractor=..., evidence_checker=None)`, with `llm_client.OpenAIChat.chat` over the
  instrumented HTTP layer of `scripts/bench_tf_handover.py` (`Session`, `InstrumentedChat`, key redaction). Settings
  are the release settings of `deploy/release.env.example` and the timeline page: model `DeepSeek-V4-Flash`,
  prompted JSON (`CARERELAY_LLM_GUIDED_JSON=0`), `max_tokens` 2000, temperature 0, seed 0, timeout 120 s, evidence
  verifier off (`KINDRED_VERIFIER_MODE=off`). Inference via the AMD Token Factory endpoint provided for the AMD
  Developer Hackathon.
- How a consultation becomes updates (decided here; the earlier PriMock runs fed the doctor channel only to the
  instruction extractor `extract_instructions.py`, a different path, and would miss the history the patient states):
  1. Both channels are parsed with `primock_transcript_segments.parse_textgrid` (role from the file name), sorted by
     start time; segment ids as `primock_transcript_segments.py` gives them.
  2. PriMock markup is removed (`<UNSURE>x</UNSURE>` keeps x; `<INAUDIBLE_SPEECH/>`, `<UNIN/>` go); a segment with no
     word left is dropped; consecutive segments of one speaker are joined into one turn.
  3. Each turn is one line, `Doctor: ...` or `Patient: ...`.
  4. Consecutive lines are cut into parts of at most 3000 characters (`CHUNK_CHARS`); a turn is never cut (a longer
     turn is a part of its own). Reason: one call per whole consultation risks the 2000-token output cap; much smaller
     parts would exceed the 400-call budget.
  5. Each part is one update: kind `recording`, speaker "a doctor and a patient in a recorded primary-care
     consultation", speaker type `care_team`, received at a placeholder time (Monday 5 January 2026 09:00 UTC plus the
     part's start offset; the notes carry no date). All parts of a consultation go into one Episode in order.
  6. The system's output is the facts `episode.grounding_problem` accepted (what the page would show). Facts it
     rejected count only for the grounding pass rate.
- A part whose call fails (HTTP failure after retries, unparsed or truncated reply, pipeline error) contributes no
  facts; the consultation is still annotated and the failure is counted (`extraction_parts.failed`). This is the
  system's behaviour and stays in the primary metrics.

## Reference: note facts

The note is split into atomic note facts by fixed rules (`split_note`, version `primock-note-split-v1`), no model:

1. A header at the start of a line (`PC`, `HPC`, `PMH`, `DH`, `Allergies`, `FH`, `SH`, `ICE`, `O/E`, `Ix`, `Imp`,
   `Dx`, `Plan`, `Mx`, `Safety net`, ... followed by `:` or `-`) sets the section until the next header; before any
   header the section is `history`. A line starting `NKDA` / `NKA` / `no known allergies` is section `allergies`.
2. Each non-empty line is split separately; list numbering (`1.`, `2)`) and bullets (`-`, `*`) are dropped.
3. A line splits into sentences at `.`, `!`, `?`, `;` followed by a space or the end, except after `Dr`, `Mr`, `Mrs`,
   `Ms`, `e.g`, `i.e`, `eg`, `ie`, `approx`, `vs`, `etc`.
4. A sentence splits into clauses at commas outside brackets and not inside a number (`1,000`). A clause containing
   `if`, `unless`, `in case` or `should` is joined to the next clause (to the previous one when it is the last), so a
   condition stays with its action ("if present, for urgent review").
5. Leading/trailing spaces and `. ; : , -` are trimmed; a clause with no letter or digit is dropped.
6. Each fact keeps its section, its source sentence (context) and a `safety_net` flag: the clause matches the
   `SAFETY_NET` regex (red flag, safety net, INB, "if ... no better / worse / persists / present / develops", urgent,
   A&E, 999, 111, emergency, "seek help/advice/review", "return/come back/call back ... if").

Example (pilot): "Initially had fever, but now settling with paracetamol/ibuprofen." gives two facts; "Discussed red
flag sx (SOB, chest pain, fevers)- if present, for urgent review with Dr" stays one fact, flagged safety-net. The pilot
note gives 38 note facts, 2 flagged safety-net.

## Annotation

- Annotator: a model of another family than the generator (DeepSeek) and the cross-check judge (Gemma-4-31B-IT):
  `Qwen3.8-Flash-Next` with `{"chat_template_kwargs": {"enable_thinking": false}}` if the endpoint lists it at the run's
  start (`GET /models`, one call), else `MiMo-V2.6-Flash` with no extra body. Temperature 0, seed 0, prompted JSON,
  `max_tokens` 4096, timeout 240 s. The model that ran is recorded and named wherever results are cited.
- Blinding: the prompts name no system, model or product; the accepted facts are "candidate facts that an unnamed
  process derived from the consultation's transcript", shown in a seeded random order (seed 20261018, keyed by the
  consultation) under neutral ids E01, E02, ...; note facts are N01, N02, ... in note order. Each candidate shows its
  type, fields, quote and who said the quoted words (the speaker of the transcript lines the quote overlaps,
  computed, not judged).
- Two calls per consultation, labels and definitions in `ANNOTATION_GUIDE.md` (the prompt carries the same
  definitions):
  - Task A, per note fact: `covered` / `not_covered` by the candidate facts (+ the covering candidate ids).
  - Task B, per candidate fact: `consistent` / `contradicts` / `not_in_note` with the note, an `error_type`, and the
    note fact ids it agrees with or contradicts. `not_in_note` is not an error: the note is a summary.
- The note is shown verbatim to both tasks; the transcript is not shown (coverage is judged against the candidate
  facts only).
- Parsing: an item counts once (the first valid one); unknown ids, labels outside the task's set, duplicates and
  missing ids are counted as problems, never guessed. A task whose reply is not JSON, truncated (`finish_reason`
  length) or misses any id is an incomplete annotation: its labelled items still count; the consultation's status says
  `annotation_incomplete`. Task B: `contradicts` without a valid error type becomes `other_contradiction`; an error
  type other than `none` / `attribution_speaker` on another label becomes `none` (both counted as coerced).
- A consultation with no accepted fact gets no annotator call: every note fact is `not_covered` by rule (those rule
  labels are not annotator decisions and are not sampled for human review).

## Error taxonomy and severity (fixed here)

| Error class | Severity | Weight | Source |
|---|---|---|---|
| negation_polarity (present vs absent, yes vs no, done vs not done, instruction reversed) | critical | 5 | task B, contradicts |
| dose_number (number, dose, frequency, quantity, duration) | critical | 5 | task B, contradicts |
| attribution_speaker (wrong person: whose symptom/condition, who said or advised it) | major | 3 | task B, contradicts, or a consistent / not_in_note fact flagged attribution_speaker |
| temporal (time, date, onset, order, past vs future) | major | 3 | task B, contradicts |
| other_contradiction (any other incompatibility; added so every contradiction has a class) | major | 3 | task B, contradicts |
| omission_safety_net (a safety-net / red-flag note fact not covered) | major | 3 | task A, not_covered, safety_net flag |
| omission_other (any other note fact not covered) | minor | 1 | task A, not_covered |

A note fact that a contradicting candidate cites (task B `note_ids`) is counted once, as the contradiction, not also
as an omission. Weights are a fixed convention for ranking errors, not a clinical risk model; unweighted counts per
class are always reported next to the score.

## Metrics

Per consultation, and over consultations as the pooled ratio (sum of numerators / sum of denominators) with a 95%
percentile cluster bootstrap (consultations resampled with replacement, 2000 resamples, seed 20261018; no interval
below 5 consultations). The macro mean of the per-consultation ratios, with its own bootstrap, is reported beside it.

Primary:
1. Note-fact recall = note facts labelled covered / note facts labelled (task A).
2. Contradiction rate = accepted facts labelled contradicts / accepted facts labelled (task B).
3. Severity-weighted error score = sum of the weights of all errors / note facts labelled (consultations with both
   tasks complete).
4. Grounding-check pass rate on this external data = facts accepted by `episode.grounding_problem` / facts proposed.

Secondary: macro means; safety-net recall; recall by note section; not_in_note and consistent rates; error counts by
class and severity; extraction part failures; calls, retries and tokens as the endpoint reports them.

No acceptance threshold is set: this is a measurement, reported whatever it shows.

## Human agreement sample (the independent check)

- A seeded random 20% (rounded up; seed 20261018) of all annotator decisions (task A and task B items, pooled over the
  completed consultations) goes to `OUT/human_review.csv`, columns `id, fact, context_quote, annotator_label,
  human_label` (`human_label` empty). `id` is `<consultation>|note|Nxx` or `<consultation>|extracted|Exx`.
  `human_review_context.md` lists every note fact and candidate fact of the sampled consultations (a reviewer needs the
  whole candidate list to judge "not covered"). The sheet is written once and never overwritten.
- A person (the user or a teammate) fills `human_label` with the guide's labels, ideally with the annotator_label
  column hidden. `python -I scripts/primock_gold_eval.py kappa --csv OUT/human_review.csv` then reports Cohen's kappa
  and raw agreement, for note rows, extracted rows and both pooled, with a row bootstrap interval. Until then kappa is
  reported as pending.

## Run rules

- Live calls only through `scripts/primock_gold_eval.py run`, sequential, one process; the key only via
  `--api-key-file` (redacted from every record and output); every HTTP attempt counts against `--max-calls`; the total
  over the pilot and the full run stays at or below 400. Calls wait while `release/benchmarks/.load_test_running`
  exists.
- Consultations run in a seeded random order (seed 20261018), so a run stopped by the call cap or the clock has done a
  random subset; the results state how many consultations they cover. `--resume` continues a stopped run.
- The pilot (`day1_consultation04`) is a harness check run first with the same frozen prompts; it is included again in
  the full run. A harness fix after the pilot is recorded as a deviation (the script's hash at the run differs from the
  preregistered one; the prompts and the analysis settings must still match or the run refuses).
- Output: `release/benchmarks/primock_gold_<UTC>/` with `records.jsonl` (every HTTP attempt, part, annotation and
  consultation, including the prompts and replies), `results.json`, `summary.md`, `human_review.csv`,
  `human_review_context.md`, `ATTRIBUTION.txt`.

## Limitations (stated with every result)

- Mock consultations: actors following case cards, not real patients; primary care, not post-fall home care, which is
  KindredRelay's setting; English only.
- The reference is a clinician's summary: it leaves out much that was said (hence not_in_note is not an error) and can
  state what was never said aloud (an impression, a plan written afterwards), which caps recall below 1.
- The annotator is one model at temperature 0; its labels are a measurement with unknown error until the human sample
  is labelled. Kappa is pending until then.
- One generator run per consultation (no repeats); transcripts are the human reference, not ASR output; the
  placeholder date can make resolved dates look odd (the annotator is told about it).
- The note splitter is rule-based: some note facts are fragments ("constant") that only make sense with their source
  sentence, which the annotator sees.
