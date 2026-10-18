# Submission text (lablab.ai form)

Paste-ready text is in the fenced blocks. Under each block, a **Sources** list gives the file for every number in it (IDs refer to `SOURCES.md`). Placeholders `[[...]]` are filled before submission (their list is in the private development repository). AMD wording rule: always "inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon"; never name a GPU.

## 1. Project title (≤ 60 characters)

| Option | Characters |
|---|---|
| KindredRelay: one sourced timeline for the whole family | 55 |
| KindredRelay: after a fall, one shared family timeline | 54 |
| KindredRelay: family updates that quote the care team | 53 |

Recommended: the first one.

## 2. Short description (≤ 255 characters)

```text
After a fall, KindredRelay turns what the care team said and photos of hospital papers into one family timeline. Every fact quotes its source; it never diagnoses. Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon.
```

249 characters (counted with Python `len`). No numbers.

## 3. Long description (485 words)

```text
When an older parent falls and ends up in hospital, one family member is usually at the bedside, listening to doctors and nurses, while everyone else calls for news. Updates arrive as hallway conversations, photos of discharge papers and messages; plans change, and the old plan lives on in someone's chat. A single misheard word matters: in our own speech-to-text test, "two tablets" came out as "a few tablets".

KindredRelay gives the family one shared timeline built from what the caregiver records, types and photographs. Speech is written out by Whisper on the app server; a vision model copies a photographed medication list. Both are drafts: the caregiver corrects them and ticks every line with a number, a time, stop or continue before anything is added.

A language model proposes each update's facts, each with a quote. Deterministic code keeps a fact only if its quote is in the update word for word (at least three words, not after a negation) and its numbers come from that quote. Relatives in other cities see a newest-first timeline in their own time zone. When they ask "When is Elena going home?", the model only chooses sentences from the updates; "Can she get out of bed on her own?" always gets "Only the care team can decide…". Unanswered questions go on a shared list for the doctor. KindredRelay never diagnoses or gives advice.

AMD is at the core: inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon. DeepSeek-V4-Flash extracts facts and chooses answer sentences; Gemma-4-31B-IT reads photographed papers. An AMD Runtime page shows every model call: model, endpoint host, latency and tokens.

We measured it. In two benchmark runs of the app's real code path, DeepSeek-V4-Flash turned an update into sourced facts in a median 6.15 s and 6.63 s, and 95.7% and 96.3% of its proposed facts passed the grounding check (Gemma-4-31B-IT: 16.66 s and 22.77 s; 86.0% and 83.3%). An offline red team stopped 46 of 54 attacks with 0 of 19 false blocks, but only 1 of 7 held-out attacks.

Engineering depth: our judge and external-reference evaluations were preregistered, with acceptance rules written to a file before the first model call. A second-model judge added attack recall in a paired McNemar test (29 attacks gained, none lost) but blocked too many normal updates, failing its own rule in two rounds, so it stays shadow-only; our evidence verifier also failed its gate and ships off. Metamorphic testing (6 relations, 200 cases each) found real negation bugs, now fixed with tests. An external clinician-note reference, PriMock57, measures the extractor against notes we did not write (58.2% note-fact recall [54.0, 61.8]). A standard-library script recomputes every published number from the raw records, CI reruns the offline checks, and a hazard log and a privacy threat model document the open risks.

Everything runs on fictional data; this is an engineering prototype, not a clinically validated product.
```

485 words, 2974 characters (Python `len(text.split())`, `len(text)`); the `[[PENDING ...]]` placeholder is counted as its 4 words: keep its filled value to 15 words or fewer to stay within 500.

Sources: misheard dose M05; Whisper on CPU M04; grounding rule `handoff_day1/agent/episode.py` (`grounding_problem`); sentence choice and fixed first line M08, `handoff_day1/agent/episode_qa.py:690`; models M01, M02; AMD Runtime M09 and `handoff_day1/ui/pages/shell/runtime_trace.py:243-262`; run 1: 6.15 s B05, 95.7% B09, 16.66 s B12, 86.0% B15; run 2: 6.63 s B25, 96.3% B26, 22.77 s B27, 83.3% B28; 46/54 R02; 0/19 R04; 1/7 R05; preregistration C05, C11, G02; McNemar 29 gained, none lost C10; judge FAIL in two rounds C07, C08; verifier gate V06–V08; metamorphic 6 × 200 and fixed bugs MT01, MT03, MT05; PriMock57 G01 (pending); recomputation Q01; CI Q03; hazard log H01, H02; threat model PV01–PV27; fictional data T05 and `handoff_day1/care_cases/episode_hip_fracture.json` → `notice`/`title`.

Engineering-depth items in this text (IDs as in `slides.md`, index at its end): D01 benchmark, two runs; D05 AMD Runtime; D06 red team; D07 test-first fixes; D08 cross-model judge and McNemar; D09 metamorphic testing; D10 PriMock57; D11 recomputation; D12 CI; D13 hazard log; D14 threat model; D15 fail-closed verifier; D19 preregistration. The others are in section 6 and 6a. `release/benchmarks/tf_bench_20261017T230311Z/summary.md` `release/benchmarks/crosscheck_r2_20261017T235438Z/summary.md` `release/benchmarks/metamorphic_20261017T233944Z/summary.md` `research/primock_gold_v1/PROTOCOL.md` <!-- depth:D01 D05 D06 D07 D08 D09 D10 D11 D12 D13 D14 D15 D19 -->

## 4. Problem and intended user

```text
User: the family caregiver of an older person after a fall and during the hospital stay and discharge: the one person at the bedside who hears the doctors and nurses and must relay everything; and the relatives in other cities and time zones who want to help.

Problem: care-team information reaches the family as spoken words, photographed papers and second-hand messages. Plans change, earlier versions keep circulating, and a misheard number can change a dose. Summaries that rewrite what was said cannot show who said what. The caregiver spends the day repeating updates, and relatives cannot tell what is current.

What KindredRelay does about it: one shared timeline where every fact quotes its source word for word, changes are shown as changes, family reports are labelled as such, questions are answered only with the care team's own sentences, and anything unanswered is collected for the doctor. It does not diagnose, advise or decide; a person confirms every draft.
```

Sources: user and roles from the demo story P02; misheard dose M05; design rules as in section 3.

## 5. Technology and category tags

AMD Token Factory · DeepSeek-V4-Flash · Gemma-4-31B-IT · OpenAI-compatible API · Python · Streamlit · OpenAI Whisper (base.en, CPU) · MediaPipe Pose · PyTorch (GRU) · Docker · Human-in-the-loop · Grounded extraction · LLM evaluation · Red teaming · Healthcare · Caregiving · Health and Wellbeing

Sources: models M01, M02; Streamlit 1.64.0 and openai-whisper 20250625 `deploy/requirements-release.lock:24,40`; MediaPipe and GRU F01 (fall module, outside the release image); Docker `Dockerfile.release`.

## 6. AMD at the core

```text
Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon. Every model call in the working product goes to that endpoint (OpenAI-compatible, host developer.amd.com.cn), and the app's AMD Runtime page lists each call with its model, endpoint host, latency and token usage. We picked each model's role from our own measurements on that endpoint:

- Generator: DeepSeek-V4-Flash turns a checked caregiver update into facts with quotes, and chooses the sentences that answer a family question. In two benchmark runs of the app's real code path (12 story updates x 3 repeats per model each) it was faster than Gemma-4-31B-IT (median 6.15 s vs 16.66 s, then 6.63 s vs 22.77 s per update) and more of its proposed facts passed the grounding check (95.7% vs 86.0%, then 96.3% vs 83.3%).
- Photo reader: Gemma-4-31B-IT copies the words of a photographed medication list or letter as a draft the caregiver checks line by line; it is called through the same endpoint and client as the text model. In an earlier run on the fictional discharge list it read 57 of 57 words.
- Second-opinion judge (evaluation, shadow): Gemma-4-31B-IT, a different model family from the generator, judges candidate outputs on paraphrased red-team attacks for unsupported content, diagnosis, dose errors or instruction overrides, against an acceptance rule written before the first call. It failed that rule in both rounds: round 2 stopped 141 of 143 paraphrased attacks (rules alone 112 of 143; paired exact McNemar p = 3.73e-09) but wrongly blocked 14 of 52 normal updates, against a limit of 5%. It stays shadow-only and is not wired into the product.

Stability: repeating each update three times, DeepSeek-V4-Flash returned the same accepted facts with a mean Jaccard of 0.900, then 0.854 in the second run (Gemma-4-31B-IT 1.000, then 0.989). In the first run, facts that came back in all three repeats matched the story's curated reference more often (79.2% vs 28.6%); the second run did not clearly replicate this (81.4% vs 45.5%, overlapping intervals), and stability did not predict passing the grounding check (85.0% vs 85.7%). We do not use stability as a confidence signal.

Load: one key reached 16.84 updates per minute at 4 concurrent requests; at 8, 20 of 36 attempts were answered with HTTP 429 (the replies state a limit of 20 requests per minute per user) and throughput fell to 9.49. Capacity model (measured tokens and throughput, labelled assumptions, no price): about 2,431 tokens per family per day at an assumed 2 updates a day, and 1.98 busy endpoint-hours per 1,000 families per day.

The hardware behind the endpoint is not visible to our client, so we name no GPU. Whisper speech-to-text runs on the app server's CPU, not on AMD.
```

Sources: endpoint M03, B01; AMD Runtime M09; 6.15 vs 16.66 s B05, B12; 95.7% vs 86.0% B09, B15; run 2 B25–B28; photo model and same endpoint M02 and `handoff_day1/agent/llm_client.py:287,502-506`; 57/57 words M06; judge C01–C03, C07–C10; 0.900, 1.000 A01–A02; 79.2% vs 28.6% A04–A05; run 2 stability A09, A11; load L03–L05; capacity L06, L07; no GPU B21; Whisper CPU M04. `release/benchmarks/agreement_20261017T232917Z/summary.md:77` `release/benchmarks/load_20261017T232951Z/rate_limit_breakdown.md:12` `release/benchmarks/capacity_20261017T233811Z/summary.md` <!-- depth:D01 D02 D03 D04 D05 D08 -->

**Discrepancy to note:** the brief describes "three AMD Token Factory-served models". In the release settings the photo model is `Gemma-4-31B-IT` (`deploy/release.env.example:4`), the same model as the judge, so the product uses **two models in three roles**. A third model family (DeepSeek-V4.1-Flash, else GLM-5.3-Flash, in round 1; MiMo-V2.6-Flash in round 2, `release/benchmarks/crosscheck_r2_20261017T235438Z/summary.md:5`) only writes paraphrased test attacks for the cross-check (`scripts/crosscheck_judge.py:12-13`), on the same endpoint (`scripts/crosscheck_judge.py:608-609`). The text above is written to match the files.

## 6a. Engineering depth (optional field, or the first answer to "how do you know it works")

```text
How we know it works, and where it does not. Each item has a command or a file in the repository; none needs an API key.
- Model roles by measurement: two benchmark runs of the app's real code path on AMD Token Factory (DeepSeek-V4-Flash median 6.15 s / 6.63 s per update, 95.7% / 96.3% of facts grounded; Gemma-4-31B-IT 16.66 s / 22.77 s, 86.0% / 83.3%).
- A hypothesis we dropped: fact stability looked like a confidence signal in run 1 and did not replicate in run 2.
- Load and capacity: 16.84 updates per minute at 4 concurrent requests; at 8 the per-user rate limit (20 requests per minute) cut it to 9.49; about 2,431 tokens per family per day under labelled assumptions, no price invented.
- AMD Runtime page: every model call of the session with model, endpoint host, latency and tokens.
- Red team: of the same 32 attacks, 23 stopped before our fixes and 30 after; 46 of 54 in the full set, 0 of 19 false blocks, but 1 of 7 held-out.
- Test-first fixes, and metamorphic testing: 6 relations x 200 seeded cases; renaming changes no decision (0/200); 7 bug patterns fixed; a live run found a negated going-home plan shown as a move, now fixed with a regression test.
- Second-model judge, two preregistered rounds: more attacks caught (paired exact McNemar p = 3.73e-09) but 14 of 52 normal updates blocked, so it failed its own rule and stays shadow-only.
- External reference: PriMock57 clinician notes, protocol fixed before the first call (58.2% note-fact recall [54.0, 61.8], 6.0% contradictions, 30 of 57 consultations).
- Independent verification: a standard-library script recomputes every published number from raw records; a CI workflow reruns the offline checks; preregistration files are timestamped before the first judge call in both rounds.
- Safety and privacy: a hazard log of 12 hazards (2 open; every citation checked: `RESULT: PASS`) and a privacy threat model listing exactly which fields leave the app; API-key redaction tested with a planted sentinel key.
- Kept off because unproven: the evidence verifier (failed its gate) and the fall detector (preliminary leave-one-subject-out AUC 0.975 +/- 0.011, not in the deployed app).
- Offline test suite: final run PASS: 832 unittest cases in 41 test processes.
```

Sources: B05, B09, B12, B15, B25–B28; A04, A05, A11; L03–L07; M09; R02, R04, R05, R08, R09; MT01–MT05; C08, C10, C11; G01, G02; Q01, Q03, C05, C06; H01, H02, PV01–PV27, K01; V06–V08; F03, F07; S01, S03. Items (index at the end of `slides.md`): D01, D02, D03, D04, D05, D06, D07, D08, D09, D10, D11, D12, D13, D14, D15, D16, D17, D18, D19. `release/benchmarks/redteam_before_20261017T122640Z/results.json` `release/benchmarks/metamorphic_20261017T233944Z/summary.md` `handoff_day1/agent/test_plan_negation.py` `scripts/verify_claims.py` `.github/workflows/validate.yml` `submission/HAZARD_LOG.md` `submission/PRIVACY_THREAT_MODEL.md` `scripts/test_bench_tf_handover.py:22` `handoff_day1/logs/test_split_record.json` `deploy/validate_abd.py` <!-- depth:D01 D02 D03 D04 D05 D06 D07 D08 D09 D10 D11 D12 D13 D14 D15 D16 D17 D18 D19 -->

## 7. AMD usage paragraph (short form, for a single field)

```text
Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon. In the live app, DeepSeek-V4-Flash extracts sourced facts from each caregiver update and chooses the sentences that answer family questions, and Gemma-4-31B-IT reads photographed hospital papers; an AMD Runtime page shows each call's model, endpoint host, latency and tokens. Measured through the app's real code path: a median 6.15 s and about 1,219 tokens per update, 36/36 updates processed. We name no GPU because the endpoint's hardware is not visible to us; speech-to-text runs on CPU.
```

Sources: M01, M02, M09, B05, B08, B04, B21, M04.

## 8. Track choice: Health and Wellbeing

```text
The track asks teams to "make a part of the patient journey safer, clearer, or easier". KindredRelay works on the part of the journey between a fall, the hospital stay and going home, where the family relies on second-hand information. It makes that part clearer (one current timeline, changes shown as changes, every fact traceable to the care team's own words) and safer (no diagnosis or advice, a person confirms every transcript and photo reading, uncertain or family-reported facts are labelled, and a verifier that did not pass its own validation gate ships switched off).
```

Sources: track line P03; design rules as in section 3; verifier V06–V08. The Health track's full brief (no autonomous diagnosis, visible uncertainty, human confirmation) was not readable on the saved official page; we follow it as relayed (`release/evidence_en/HACKATHON_RULES_BRIEFING.md:36`).

## 9. Links

- Public GitHub repository: https://github.com/HollyHsu0808/KindredRelay
- Application URL: [[APP_URL]]
- Demo video: [[VIDEO_URL]]
- Slides: `submission/slides.html` (print to PDF) / the PowerPoint built from `submission/slides.md`
- Cover image: `submission/cover.svg` → PNG
