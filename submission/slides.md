# KindredRelay pitch deck: content and speaker notes

Source material for the PowerPoint. One section per slide, in the same order as `slides.html` (generated from this file). Each slide has:

- **Title**: paste into the slide title.
- **On the slide**: paste as the body (bullets are short on purpose).
- **Visual**: what to put on the slide.
- **Sources**: the small grey line at the bottom of the slide (IDs refer to `SOURCES.md`).
- **Speaker notes**: paste into the PowerPoint notes pane.

Rules that apply to every slide: whenever AMD is mentioned, use the exact wording "Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon"; never name a GPU; never say KindredRelay diagnoses; keep `[[...]]` placeholders visible until they are filled before submission. 16:9, light background; suggested palette: background #FBFAF7, text #1F2328, AMD orange #D9480F, check green #2B7A4B, person blue #3657A8.

**Engineering-depth items** have the IDs D01 to D19 (index at the end of this file). A marker such as `<!-- depth:D08 -->` at the end of a slide's Sources line says which items that slide carries; it is an HTML comment and does not appear on the slide. `scripts/check_depth_coverage.py` checks that every ID appears in this file, `SUBMISSION_TEXT.md` and `JUDGES_QUICKSTART.md`, and that the paths next to each marker exist.

---

## Slide 1: Title and hook

**Title:** KindredRelay

**On the slide:**
- After a fall, the whole family needs the same story: what the care team actually said, in their words.
- One shared family timeline built from what the caregiver records, types and photographs.
- Every fact quotes its source word for word. It never diagnoses.
- Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon
- DeepSeek-V4-Flash · Gemma-4-31B-IT
- AMD Developer Hackathon ACT III · Health & Wellbeing track · https://github.com/HollyHsu0808/KindredRelay · [[APP_URL]]

**Visual:** `cover.svg` as the background, or the product's tagline "One place to understand what's happening, and be there for each other." under the title.

**Sources:** tagline P01; models M01, M02; AMD wording B21.

**Speaker notes:** Mum fell. One daughter is at the hospital; the rest of the family is in other cities. KindredRelay turns what the nurse says, a photo of the discharge list and the caregiver's own notes into one timeline the whole family shares. Every fact quotes where it came from. It never diagnoses and never gives advice.

---

## Slide 2: Problem and user

**Title:** The problem, and who we built it for

**On the slide:**
- **User:** the family caregiver after a fall and a hospital stay: at the bedside, hearing doctors and nurses, then repeating it all on the phone.
- **Also:** relatives in other cities and time zones who want to help and keep asking the same questions.
- Updates arrive as hallway conversations, photos of papers, phone calls.
- Plans change: "going home" moves from Friday to Saturday; the old plan lives on in someone's chat.
- One misheard word matters: our own speech-to-text test turned "two tablets" into "a few tablets".
- A summary that rewrites what was said cannot show who said what.
- Context (secondary): 23% of inpatients in one study said they at least sometimes got conflicting information; 43 US states + DC require hospitals to instruct family caregivers before discharge (CARE Act).

**Visual:** the demo family on a map: Anna (London, at the hospital), David (Toronto), Mia (Melbourne), around Elena, 82 (fictional).

**Sources:** demo story P02; misheard dose M05; 23% X03 (secondary); CARE Act X01 (secondary).

**Speaker notes:** Our user is the family caregiver after a fall, around the hospital stay and discharge, plus the relatives far away. The misheard-dose example is from our own Whisper smoke test, and it is the reason every number in KindredRelay is checked by a person before it is added. The two context figures come from our research note; we label them secondary until we re-check the primary papers.

---

## Slide 3: What the family does with it

**Title:** What the family does with it

**On the slide:**
1. **Record what the nurse said** (after the speaker agrees). Whisper writes it out; the caregiver corrects it and ticks every line with a number, a time, stop or continue.
2. **Facts with quotes.** The model proposes facts; code keeps only those whose quote is in the update word for word. The timeline shows "Going home moved", the old plan crossed out.
3. **Photograph the discharge medication list.** A vision model copies the words as a draft; the caregiver checks each line against the photo.
4. **Every relative sees it** in their own time zone, with what changed since they last looked.
5. **Ask a question.** "When is Elena going home?" → the care team's own sentences, who said them, when. "Can she get out of bed on her own?" → "Only the care team can decide…" plus what they said.
6. **Not in the updates?** It goes on a shared "Questions for the doctor" list.

**Visual:** 3–4 screenshots from the demo recording: the transcript with tick boxes, the timeline with "Going home moved", the answer card, the "Questions for the doctor" list. [[PENDING: screenshots from the demo recording]]

**Sources:** flow `release/evidence_en/DEMO_RECORDING.md:104-118`; labels `handoff_day1/ui/pages/1_Family_timeline.py:1089,1550,1711`; fixed first line `handoff_day1/agent/episode_qa.py:690`.

**Speaker notes:** This is the demo order. The point to stress: for a family question the model never writes the answer. It only picks sentences from the updates, and the first line is fixed text written by our code. That is how we keep "can she…?" questions with the care team.

---

## Slide 4: AMD at the core

**Title:** AMD at the core: two models, three roles, chosen by measurement

**On the slide:**
- Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon (OpenAI-compatible, host developer.amd.com.cn).
- **Generator: DeepSeek-V4-Flash** turns each checked update into facts with quotes, and chooses the sentences that answer family questions.
  - Chosen by data, in two benchmark runs: median 6.15 s / 6.63 s per update vs 16.66 s / 22.77 s for Gemma-4-31B-IT; 95.7% / 96.3% vs 86.0% / 83.3% of proposed facts pass the grounding check.
- **Photo reader: Gemma-4-31B-IT** copies a photographed medication list or letter as a draft for the caregiver to check (57/57 words on our fictional discharge list). Same endpoint, same client.
- **Second-opinion judge: Gemma-4-31B-IT** (evaluation, shadow): a different model family checks paraphrased attacks. It failed its preregistered rule in both rounds, so it stays off the product path (slide 9).
- **AMD Runtime page**: every model call of the session with model, endpoint host, latency, tokens and what our checks did with the reply.
- **Load and capacity:** peak 16.84 updates per minute at 4 concurrent requests; at 8, 20 of 36 attempts were rate-limited (HTTP 429; the replies state 20 requests per minute per user). Model: about 2,431 tokens per family per day; 1.98 busy endpoint-hours per 1,000 families per day (assumptions labelled, no price).
- Not on AMD, not claimed: Whisper runs on the app server's CPU. No GPU is named: the endpoint's hardware is not visible to us.

**Visual:** three orange role cards (Generator, Photo reader, Judge) around the Token Factory endpoint; a small screenshot of the AMD Runtime page. [[PENDING: AMD Runtime session-summary screenshot]]

**Sources:** endpoint M03, B01; run 1 B05, B12, B09, B15; run 2 B25–B28; photo model M02; 57/57 M06; judge C01–C03, C07, C08; AMD Runtime M09 and `handoff_day1/ui/pages/shell/runtime_trace.py:243-262`; load L03–L05; capacity L06, L07; no GPU B21; Whisper CPU M04. `release/benchmarks/load_20261017T232951Z/summary.md:13` `release/benchmarks/capacity_20261017T233811Z/summary.md:46,52` <!-- depth:D01 D03 D04 D05 -->

**Speaker notes:** Read the AMD sentence exactly. Every model call in the product the judges use goes to Token Factory, and you can watch them on the AMD Runtime page. We did not pick models by reputation: we ran the app's own code path on the endpoint twice, 12 updates times 3 repeats per model each time. In both runs DeepSeek-V4-Flash was faster and more of its facts survived our grounding check, so it is the generator. Gemma-4-31B-IT reads photos, and because it is a different model family it was our second-opinion judge in evaluation; it did not pass its own rule, so it is not in the product. Two models, three roles. The load test shows where the shared endpoint stops scaling for one key: the per-user rate limit, not hardware we can see. The capacity numbers are a model with labelled assumptions; we do not invent a price. Never name a GPU.

---

## Slide 5: Architecture

**Title:** How one update becomes a sourced family timeline

**On the slide:** the diagram only.

**Visual:** insert `architecture.svg` full-bleed (PowerPoint: Insert → Pictures → the SVG; or its PNG export). Legend is in the diagram: orange = AMD Token Factory, green = deterministic check, blue = a person checks, dashed = in the repo, not in the app path.

**Sources:** every box with path:line in `architecture.md`.

**Speaker notes:** Follow one update left to right. Speech to text on the app server's CPU; a person checks the draft; DeepSeek on Token Factory proposes facts; our code checks every quote; the evidence verifier is switched off in the release because it did not pass its own gate; then the timeline. The second row is a family question: the model only picks sentences, code checks them and writes the first line. Dashed boxes are in the repository but not in the deployed app, including the fall-detection prototype and the evaluation tools.

---

## Slide 6: Safety by design

**Title:** Safety by design: the model proposes, code and people decide

**On the slide:**
- **Every fact quotes its source.** Shown only if its quote is in the update word for word (≥ 3 words, not after a negation) and its numbers and dates come from that quote. No model in this check.
- **No diagnosis, no advice.** For questions the model only picks sentence ids; it writes no answer text. The first line is fixed: "Only the care team can decide what Elena may do."
- **A person checks every draft.** Transcripts and photo text are drafts; lines with a number, a time, stop or continue must be ticked. Edited lines are labelled as family words.
- **Fail-closed where not proven.** The evidence verifier stays off unless it has a validated operating point; v2 found none (0 of 4,048 thresholds), v1 let 9/131 unsupported QA claims through. The release refuses gate mode without one. Family notes never override the care team.

**Visual:** four cards (green, green, blue, green).

**Sources:** `handoff_day1/agent/episode.py`; `handoff_day1/agent/episode_qa.py:686-690`; `handoff_day1/ui/pages/1_Family_timeline.py`; V02, V06, V08, V09; `deploy/serve.py:42-43`; `Dockerfile.release:14`; `handoff_day1/agent/README.md:29`. <!-- depth:D15 -->

**Speaker notes:** Four rules. The important one: the model can propose but cannot publish. The verifier is off because it failed its own preregistered gate, not because we forgot it; we would rather ship it switched off than pretend. The server refuses to start in gate mode without a validated operating point, so it cannot be switched on by accident.

---

## Slide 7: How we know it works (1/6): the handover step, measured twice

**Title:** How we know it works (and where it doesn't): the handover step, measured twice

**On the slide (table):**

| | DeepSeek-V4-Flash (default), run 1 / run 2 | Gemma-4-31B-IT, run 1 / run 2 |
|---|---|---|
| Updates processed | 36/36 / 35/36 (1 timeout) | 36/36 / 36/36 |
| Median time per update | 6.15 s / 6.63 s | 16.66 s / 22.77 s |
| p95 time per update | 15.62 s / 16.53 s | 51.40 s / 82.36 s |
| Tokens per update (mean) | 1,219 / 1,216 | 1,330 / 1,331 |
| Proposed facts passing the grounding check | 95.7% / 96.3% | 86.0% / 83.3% |
| Same facts across 3 repeats (mean Jaccard) | 0.900 / 0.854 | 1.000 / 0.989 |

- **Roles follow the data:** in both runs DeepSeek-V4-Flash was faster and more of its facts were grounded.
- **A hypothesis that did not replicate:** run 1 suggested stable facts match the reference more often (79.2% vs 28.6%); in run 2 the gap shrank (81.4% vs 45.5%, overlapping intervals), and stability did not predict passing the grounding check (85.0% vs 85.7%). We do not use stability as a confidence signal.
- **Under load:** 16.84 updates per minute at 4 concurrent requests; at 8, throughput fell to 9.49 as 20 of 36 attempts were rate-limited (20 requests per minute per user).

Footnote on the slide: One update = the app's real path (extraction → grounding check → gate) called by `scripts/bench_tf_handover.py`; 12 updates of one fictional story × 3 repeats per model per run; verifier off. Latency includes the network from our machine. Engineering measurement, not clinical validation.

**Visual:** the table; optionally `release/benchmarks/tf_bench_20261017T230311Z/latency.svg` and `release/benchmarks/load_20261017T232951Z/throughput.svg`.

**Sources:** run 1 B02–B19, A01–A05; run 2 B24–B29, A09–A11; load L03–L05. `release/benchmarks/tf_bench_20261017T213905Z/results.json` `release/benchmarks/tf_bench_20261017T230311Z/results.json` `release/benchmarks/agreement_20261017T221124Z/summary.md` `release/benchmarks/agreement_20261017T232917Z/summary.md:39-42` `release/benchmarks/load_20261017T232951Z/rate_limit_breakdown.md:12` <!-- depth:D01 D02 D03 D04 -->

**Speaker notes:** We ran the same benchmark twice, an hour and a half apart. The ranking held: DeepSeek is faster and more of its proposed facts pass the grounding check, so it stays the default. Run 2 also tested an idea from run 1, that facts which come back in every repeat are more trustworthy. It did not hold up clearly, so we dropped it rather than ship a confidence badge we cannot defend. Under load the limit we hit was the endpoint's per-user rate limit, which the 429 replies state.

---

## Slide 8: How we know it works (2/6): red team and metamorphic testing

**Title:** How we know it works: a red team, and metamorphic tests that need no answer key

**On the slide:**
- **Red team** (offline, deterministic, no model): the same 32 attacks **23/32 → 30/32** stopped before → after our fixes; **46/54** in the full 73-case set; **0/19** benign controls blocked; **1/7** held-out attacks. Final rerun on the shipped code (after the DX-05 and PI-04 fixes): **49/54** stopped, **48/48** excluding the documented known gaps, **0/19** controls blocked, held-out **2/7**; the 5 attacks that still pass are all on the Case Agent answer path, none on the deployed family timeline (SOURCES R11, R12).
- **Test-first fixes:** the failing run is recorded before the fix (red team 12:26 UTC before, 14:00 UTC after; metamorphic before_fix run on the same seed), and the test suite fails on any new violation signature.
- **Metamorphic testing:** 6 relations × 200 seeded instances, e.g. "adding a negation must flip acceptance", "renaming people must change nothing". Invariance: **0/200** violations. **7** guardrail bug signatures closed (negation relation 132 → 62 violations; 38 in the final run after the plan-negation fix, and the dose relation 40 → 0); the rest are listed as known gaps.
- **Live, on DeepSeek-V4-Flash:** 2 of 20 accepted facts had the wrong negation polarity on a flipped clause.
- **A real bug found:** "Going home is not planned for Saturday" was shown as "Going home moved". Fixed, with a regression test. Negated-procedure display: "The surgeon will not operate tomorrow morning" and "Surgery has been cancelled" are no longer shown as a planned operation anywhere; the card shows the source's own words (7 + 7 regression tests, SOURCES DF01).

**Visual:** left: the four red-team numbers (held-out 2/7 in amber); right: a small before → after bar per metamorphic relation.

**Sources:** R01–R10, R11; MT01–MT05. `release/benchmarks/redteam_before_20261017T122640Z/results.json` `release/benchmarks/redteam_20261017T140024Z/results.json` `release/benchmarks/metamorphic_20261017T233944Z/summary.md:5-12,60-78,117,129` `release/benchmarks/metamorphic_20261017T233944Z/before_fix/` `handoff_day1/agent/test_plan_negation.py` <!-- depth:D06 D07 D09 -->

**Speaker notes:** Two ways of attacking our own rules. The red team is a fixed list of attacks; be upfront that only 1 of 7 held-out attacks was stopped. Metamorphic testing does not need a correct answer for each input: it needs a relation that must hold, such as "adding not must flip the decision". We generated 200 cases per relation, fixed seven bug patterns, and kept the remaining ones on a visible known-gap list. The same method, run live against the model, found a real display bug in going-home plans, which we fixed with a regression test.

---

## Slide 9: How we know it works (3/6): a second model as judge

**Title:** How we know it works: a second model as judge, two preregistered rounds, two honest FAILs

**On the slide:**
- **Question:** does "rules OR judge" (judge = Gemma-4-31B-IT) stop more paraphrased attacks than the rules alone, without blocking normal updates?
- **Rule written before the first judge call:** attack recall Wilson lower bound ≥ 0.80 AND benign false blocks ≤ 5% AND unverified ≤ 5%.
- **Round 1** (paraphrases by DeepSeek-V4.1-Flash): rules OR judge stopped 127/134 attacks but blocked 26/45 benign updates → **FAIL**.
- **Change decided from round 1 only:** "not supported" is no longer a flag; one prompt rule (instruction override) rewritten.
- **Round 2** (new held-out paraphrases by MiMo-V2.6-Flash): **141/143** attacks (Wilson lower 0.9504); benign false blocks **14/52** (26.9%) vs 9/52 (17.3%) for the rules alone → **FAIL**.
- **Paired exact McNemar** (preregistered, secondary): attacks b = 0, c = 29, p = 3.73e-09; benign b = 0, c = 5, p = 0.0625.
- **Verdict:** the judge catches attacks the rules miss, but blocks too many normal updates. It stays shadow-only.

**Visual:** a two-row table, round 1 vs round 2: recall, false blocks, verdict (both FAIL in red).

**Sources:** C01–C03, C05–C12. `release/benchmarks/crosscheck_20261017T221103Z/results.json` `release/benchmarks/crosscheck_r2_20261017T235438Z/summary.md:9,14-33,39-40` `release/benchmarks/crosscheck_r2_20261017T235438Z/preregistration.json` <!-- depth:D08 D19 -->

**Speaker notes:** This is the experiment we are proudest of, because it failed twice in public. Each round wrote its acceptance rule and its paraphrased attacks to a file before the first judge call, and the timestamps prove it. Round 2 changed only what round 1's data justified. The judge clearly adds attack recall: in the paired test it never lost an attack the rules caught and gained 29. But a judge that blocks a quarter of normal updates would bury the family in false alarms, so by our own rule it stays out of the product.

---

## Slide 10: How we know it works (4/6): an external reference

**Title:** How we know it works: an external reference the team did not write (PriMock57 clinician notes)

**On the slide:**
- **Why:** every other correctness number is self-referential: we wrote the story, the reference facts, the attacks and the judge prompt.
- **Data:** PriMock57, 57 public mock primary-care consultations (CC BY 4.0) with the consulting clinician's own note.
- **Method, fixed before any live call:** each transcript goes through the product's unchanged extractor on DeepSeek-V4-Flash; a blind annotator model matches accepted facts to the clinician's note; a person re-labels a 20% sample for Cohen's kappa.
- **Metrics:** note-fact recall, contradiction rate, severity-weighted errors (negation and dose errors weigh most), grounding pass rate.
- **Result:** 30 of 57 PriMock57 consultations (preregistered seeded subset): note-fact recall 58.2% [54.0, 61.8], contradiction rate 6.0% [4.3, 7.8], severity-weighted errors 0.682 per note fact [0.574, 0.800] (critical: 23 negation, 6 dose), safety-net facts covered 22/28; model annotator (Qwen3.8-Flash-Next), Cohen's kappa pending a 360-row human sample (`release/benchmarks/primock_gold_20261018T002738Z/human_review.csv`)
- **Limits:** role-played consultations, not patients; the annotator is a model until the human sample is labelled; a note is one clinician's summary, not ground truth.

**Visual:** one big recall number with its interval, and the error-type bar (placeholder until the run lands).

**Sources:** G01, G02. `research/primock_gold_v1/PROTOCOL.md` `research/primock_gold_v1/preregistration.json` `research/primock_gold_v1/ANNOTATION_GUIDE.md` <!-- depth:D10 -->

**Speaker notes:** Everything else we measured, we also designed. So we took a public dataset of mock consultations where the clinicians wrote their own notes, and asked: how many of the clinician's facts does our extractor recover, and does it ever contradict the note? The protocol and analysis were fixed and hashed before the first call. Read the final numbers from the result box; do not round them up.

---

## Slide 11: How we know it works (5/6): anyone can check our numbers

**Title:** How we know it works: anyone can recompute our numbers, without a key

**On the slide:**
- **Recompute:** `scripts/verify_claims.py` (Python standard library only) recomputes the headline metrics from the raw records and checks every row of `SOURCES.md` against the file it cites. Final result: (final pre-submission run: 578 checks pass, 0 mismatches, `RESULT: PASS`)
- **Preregistration ordering:** in both judge rounds the preregistration file was written before the first judge call (round 1: 22:25:08.544 vs 22:25:28.710 UTC; round 2: 00:19:58.999 vs 00:20:06.623 UTC); `verify_claims.py` re-checks it.
- **Offline test suite:** `deploy/validate_abd.py`, final run PASS: 832 unittest cases in 41 test processes, sources unchanged during the run.
- **CI:** `.github/workflows/validate.yml` runs the offline suites and both checkers on GitHub with no secrets: [[CI_URL]] (not yet run; the repository is pushed at submission).
- **Coverage of this deck:** `scripts/check_depth_coverage.py` checks that every engineering-depth item appears in the public documents and that the paths next to it exist.

**Visual:** a terminal screenshot of `verify_claims.py --quiet` ending in its RESULT line.

**Sources:** Q01, Q03, C05, C06, C11, S01, S03. `scripts/verify_claims.py` `.github/workflows/validate.yml:3` `release/benchmarks/crosscheck_20261017T221103Z/preregistration.json` `release/benchmarks/crosscheck_r2_20261017T235438Z/preregistration.json` `handoff_day1/ui/pages/shell/data/validation.json` `scripts/check_depth_coverage.py` <!-- depth:D11 D12 D17 D19 -->

**Speaker notes:** Do not trust our slides; run our checker. It needs no key and no network, and it reads the raw records, not our summaries. The preregistration timestamps are in the files, so anyone can confirm the rules came before the results. The CI workflow will run the same checks on GitHub once the repository is public.

---

## Slide 12: How we know it works (6/6): safety and privacy, written down

**Title:** How we know it works: a hazard log and a privacy threat model, every line cited

**On the slide:**
- **Hazard log:** 12 hazards scored severity × likelihood, each control and test cited to a line of code; **2 open** (speech mis-transcription not measured, no semantic check active); the diagnosis-label and recording-instruction hazards were closed by the DX-05 and PI-04 fixes and are mitigated, with tests. `scripts/check_hazard_log.py` checks every citation: `RESULT: PASS`, 87 citations (SOURCES H02, H03).
- **Privacy threat model:** exactly which fields leave the app (update text, photos, and questions with the asker's name and relation go to the Token Factory endpoint), what is stored, STRIDE and LINDDUN per trust boundary. Gaps written down: a family link is full access, no encryption at rest, no retention limit, photos stay after an update is deleted.
- **Secret hygiene:** the API key comes only from the environment; tests plant a sentinel key and assert it never reaches any output file, error text or argv; history scan of every blob of every branch, here and in the earlier public CareRelay repository: the real key is in no committed version of any file, and the only key-shaped strings are the 4 planted test sentinels (`release/benchmarks/secret_scan_20261018T020029Z/`, SOURCES K02).

**Visual:** left: the hazard table's status column (10 mitigated, 2 open in amber); right: the data-flow diagram from the threat model, the Token Factory boundary highlighted.

**Sources:** H01, H02; PV01, PV08–PV12, PV19, PV21; K01, K02. `submission/HAZARD_LOG.md` `scripts/check_hazard_log.py` `submission/PRIVACY_THREAT_MODEL.md` `scripts/test_bench_tf_handover.py:22` <!-- depth:D13 D14 D18 -->

**Speaker notes:** A hackathon prototype is not cleared for patient data, and we say so in writing. The hazard log is the list of ways this could hurt a family, each with the control, the test and an honest status; four are open. The threat model lists every field that leaves the app and every gap we know about. Both are checked by scripts, so the citations cannot drift silently.

---

## Slide 13: Honest failures

**Title:** Honest failures: what failed, and what we kept off

**On the slide:**
- **Evidence verifier v2 failed its gate:** 0 of 4,048 thresholds met false-acceptance ≤ 5% with ≥ 10% acceptance in every scope (weakest scope AUROC 0.673). Kept off; v1 (AUROC 0.9800) also off: 9/131 false acceptances on QA.
- **Cross-model judge failed its own rule twice:** benign false blocks 26/45, then 14/52. Shadow only.
- **Guardrails generalise poorly:** 2/7 held-out attacks stopped (the 5 misses are on the Case Agent answer path; DX-05 and PI-04 on the deployed path are closed); own-words diagnoses (48/200) and unknown override phrasings (47/200) pass the pattern lists.
- **Stability as a confidence signal did not replicate** across two benchmark runs.
- **Timeline reasoning is not better than baselines:** held-out strict all-correct 10/80 (journal), 11/80 (full context), 13/80 (lexical RAG); all paired intervals include 0.
- **The fall detector is a separate prototype**, not in the deployed app: preliminary leave-one-subject-out AUC 0.975 ± 0.011, but on the sealed test v0.1 flagged 6/17 falls and v0.2 12/17 (5/20 false prompts). A prompt to confirm, never an alarm.
- **Fictional data only; no clinical validation.** Token Factory keeps prompts about 2 days and its terms say not to send health data: production needs a dedicated endpoint under a data-processing agreement.

**Visual:** plain list; each line with its number in bold.

**Sources:** V01–V07; C07, C08; R05, R06; MT01; A11; T01–T03, T05; F03, F05, F06, F07; M07. `release/benchmarks/metamorphic_20261017T233944Z/summary.md:11-12` `handoff_day1/logs/test_split_record.json` `release/evidence_en/DEV_README_EXCERPT.md:16` <!-- depth:D02 D08 D15 D16 -->

**Speaker notes:** This is the credibility slide. Every failure has a number and a file. We kept the failing parts switched off instead of shipping them, and we report the hypotheses that did not survive a second run.

---

## Slide 14: Business value, team and next steps

**Title:** Business value, team and next steps

**On the slide:**
- **Who could pay (hypotheses to test, secondary figures):** hospitals and discharge teams (the CARE Act requires hospitals to instruct family caregivers before discharge in 43 states + DC; a meta-analysis links family involvement in discharge planning to 25% fewer 90-day readmissions); families directly (consumer care-coordination apps charge, e.g. US$6.99 per month).
- **Measured:** one caregiver update becomes sourced timeline facts in a median 6.15–6.63 s at about 1,216–1,219 tokens (DeepSeek-V4-Flash on AMD Token Factory).
- **Modelled, not measured:** about 2,431 tokens per family per day at an assumed 2 updates a day; 1.98 busy endpoint-hours per 1,000 families per day. No price assumed.
- **Not measured (hypothesis):** caregiver time saved; fewer repeat questions to ward staff. Pilot metric: caregiver minutes per day spent relaying updates, before vs after.
- **Team:** [[TEAM_NAMES_AND_ROLES]] · code https://github.com/HollyHsu0808/KindredRelay · app [[APP_URL]] · video [[VIDEO_URL]]
- **Next:** close the held-out misses on the Case Agent path; retrain the verifier against a preregistered gate; a dedicated endpoint under a data-processing agreement; a pilot with one discharge team.
- Inference via the AMD Token Factory endpoint provided for the AMD Developer Hackathon.

**Visual:** two columns: "Who pays (hypotheses)" and "Measured / modelled / will measure"; QR codes for the repo and app (generate after the URLs are final).

**Sources:** X01, X02, X04, X05, X06 (secondary); B05, B08, B25, L06, L07; open gaps R06; verifier V06–V07; data handling M07. `release/benchmarks/capacity_20261017T233811Z/summary.md:33-36,46,52` <!-- depth:D04 -->

**Speaker notes:** We do not claim time saved: we have not measured it. The buyer is a hypothesis backed by the regulatory and survey context, and we propose the metric a pilot would measure. The token figures are a capacity model built on measured tokens per update with the assumptions printed next to them; no currency is quoted because the endpoint publishes none to us. Roles from the handoff (to confirm): Holly owns data, models, experiments and care content; Leo owns backend, integration and deployment (the team handoff notes, in the private development repository).

---

## Engineering-depth index (not a slide)

| ID | Item | Slide | Evidence |
|---|---|---|---|
| D01 | Token Factory benchmark, two runs → model roles | 4, 7 | `release/benchmarks/tf_bench_20261017T213905Z/`, `release/benchmarks/tf_bench_20261017T230311Z/` |
| D02 | Fact stability, and its non-replication | 7, 13 | `release/benchmarks/agreement_20261017T221124Z/`, `release/benchmarks/agreement_20261017T232917Z/` |
| D03 | Endpoint load test and rate limit | 4, 7 | `release/benchmarks/load_20261017T232951Z/` |
| D04 | Capacity and token model (assumptions labelled, no price) | 4, 7, 14 | `release/benchmarks/capacity_20261017T233811Z/` |
| D05 | AMD Runtime page | 4 | `handoff_day1/ui/pages/shell/runtime_trace.py` |
| D06 | Safety red team before / after, held-out set | 8 | `release/benchmarks/redteam_before_20261017T122640Z/`, `release/benchmarks/redteam_20261017T140024Z/` |
| D07 | Test-first guardrail fixes | 8 | `release/benchmarks/metamorphic_20261017T233944Z/before_fix/` |
| D08 | Cross-model judge, rounds 1 and 2, McNemar | 9, 13 | `release/benchmarks/crosscheck_20261017T221103Z/`, `release/benchmarks/crosscheck_r2_20261017T235438Z/` |
| D09 | Metamorphic testing | 8 | `release/benchmarks/metamorphic_20261017T233944Z/` |
| D10 | PriMock57 external reference | 10 | `research/primock_gold_v1/` |
| D11 | Recomputation of every published number | 11 | `scripts/verify_claims.py` |
| D12 | CI workflow | 11 | `.github/workflows/validate.yml` |
| D13 | Hazard log | 12 | `submission/HAZARD_LOG.md` |
| D14 | Privacy threat model | 12 | `submission/PRIVACY_THREAT_MODEL.md` |
| D15 | Fail-closed evidence verifier (v1, v2 off) | 6, 13 | `Dockerfile.release`, `deploy/serve.py` |
| D16 | Fall model (separate prototype, not deployed) | 13 | `handoff_day1/logs/test_split_record.json` |
| D17 | Offline validation suite | 11 | `deploy/validate_abd.py` |
| D18 | Secret hygiene | 12 | `scripts/test_bench_tf_handover.py` |
| D19 | Preregistration precedes the first judge call | 9, 11 | `release/benchmarks/crosscheck_r2_20261017T235438Z/preregistration.json` |
