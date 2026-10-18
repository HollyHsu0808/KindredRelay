# primock_gold_v1 annotation guide

For the model annotator (the prompt in `scripts/primock_gold_eval.py` carries the same definitions, condensed:
`TASK_A`, `TASK_B`, `DATE_NOTE`) and for the person who fills `human_label` in `human_review.csv`. Protocol: `PROTOCOL.md`.

You compare two independent records of one mock primary-care consultation (actors, not real patients):

- the **clinician's note** (written by the consulting clinician), split into **note facts** `N01, N02, ...`, each with
  its section (`history`, `pmh`, `medications`, `allergies`, `family_history`, `social_history`, `impression`, `plan`,
  ...) and the note sentence it came from;
- the **candidate facts** `E01, E02, ...` that an unnamed process derived from the transcript, each with a type
  (`event`, `instruction`, `medication`, `diagnosis_stated`, `follow_up`, `warning_signs`, ...), its fields, the
  transcript words it quotes, and who said those words (doctor, patient, or both when the quote spans two turns).

You only label. You give no medical advice and judge nothing about the patient. Read clinical abbreviations as
clinicians do: 4/7 = four days, 2/52 = two weeks, hx = history, sx = symptoms, SOB = shortness of breath, NKDA = no
known drug allergies, PMH / DH / FH / SH = past medical / drug / family / social history, Imp = impression,
mx = management, INB = if no better, etOH = alcohol, URTI = upper respiratory tract infection.

Dates in candidate facts were resolved against a placeholder consultation date, Monday 5 January 2026, 09:00 (the
notes have no date): judge times relative to that date.

## Task A: is each note fact covered by the candidate facts?

| Label | Definition |
|---|---|
| `covered` | One or more candidate facts, read together, state the note fact's clinical content: the same symptom, finding, negative finding, history item, impression or plan item. Wording may differ. |
| `not_covered` | No candidate fact states it; or the candidates state only part of it and miss the clinically important part (the polarity, a number or duration that is the point of the fact, the action of a plan item, the condition of a safety-net instruction); or a candidate states it with the opposite polarity, a different number, a different time or a different person. |

Judge only against the candidate facts, never against what was probably said in the consultation. Give the ids of the
covering candidates (none for `not_covered`).

Examples (note facts of the pilot note, invented candidates):

- N13 `[history] No chest pain`; candidate `[event] what: no pain in chest | quote: "no pain in chest" (patient)` ->
  **covered**.
- N13 `No chest pain`; candidate `[event] what: chest pain | quote: "some chest pain" (patient)` -> **not_covered**
  (opposite polarity; in task B that candidate is `contradicts`, negation_polarity).
- N10 `[history] Night sweats for the past 4/7`; candidate `[event] what: night sweats | quote: "sweating at night"`
  -> **covered** (the core content is the symptom; the duration is not the point here). If the note fact were
  `Night sweats for 2/52` and the candidate said "for the last four days", that is **not_covered** (the duration
  differs).
- N09 `[history] constant` (from "Now developed a cough -mainly dry, constant") -> **covered** only if a candidate
  says the cough is constant / there all the time.
- N26 `[family_history] Grandmother - type 2 diabetes`; candidate `[event] what: patient has type 2 diabetes` ->
  **not_covered** (different person).
- N37 `[plan] Review in 5-7d INB` (a safety-net item); candidate `[follow_up] what: review | when_text: in a week` ->
  **not_covered** if nothing says "if no better" (the condition is the point of a safety-net instruction); a candidate
  "come back if it's not better in five to seven days" -> **covered**.
- N32 `[impression] viral URTI/influenza`; candidate `[diagnosis_stated] what: viral infection, likely flu` ->
  **covered**.

## Task B: how does each candidate fact relate to the note?

| Label | Definition |
|---|---|
| `consistent` | The note states the same thing (wording may differ). |
| `contradicts` | The note states something incompatible with it: the opposite polarity (present vs absent, done vs not done, an instruction reversed), a different number, dose, frequency or duration, a different time or order of events, a different person (whose symptom or condition it is, or who said or advised it), or another incompatible detail. |
| `not_in_note` | The note neither states it nor states anything incompatible with it. The note is a short summary, so such a fact is usually not wrong: never label a fact `contradicts` only because the note leaves it out. |

Error type (one per candidate):

| error_type | When |
|---|---|
| `negation_polarity` | contradicts: present vs absent, yes vs no, done vs not done, an instruction reversed |
| `dose_number` | contradicts: a different number, dose, frequency, quantity or duration |
| `attribution_speaker` | contradicts: the wrong person (a relative's condition given as the patient's; the patient's own report or idea presented as the clinician's statement or advice; or the reverse). Also allowed on `consistent` / `not_in_note` when the content agrees with or is absent from the note but the fact gives it to the wrong person (use the "said by" speaker) |
| `temporal` | contradicts: a wrong time, date, onset or order, or past given as future or the reverse |
| `other_contradiction` | contradicts: any other incompatibility |
| `none` | `consistent` or `not_in_note` without an attribution problem |

Give the ids of the note facts the candidate agrees with or contradicts (none for `not_in_note`).

Examples:

- `[event] what: sore throat getting better | quote: "my throat's a bit better now" (patient)` vs N06 `Sore throat is
  improving` -> **consistent**, none, [N06].
- `[event] what: no fever | quote: "I haven't had a fever" (patient)` vs N11 `Initially had fever` ->
  **contradicts**, negation_polarity, [N11].
- `[medication] name: ibuprofen; dose: 800 mg` vs a note saying `ibuprofen 400mg` -> **contradicts**, dose_number.
- `[event] what: symptoms for two weeks` vs N01 `4/7 hx of generally unwell` -> **contradicts**, dose_number
  (a duration); a candidate saying the cough started before the sore throat when the note says it came after ->
  temporal.
- `[diagnosis_stated] what: type 2 diabetes | quote: "my grandma has diabetes" (patient)` vs N26 `Grandmother - type 2
  diabetes` and N23 `[pmh] Nil` -> **contradicts**, attribution_speaker, [N26, N23].
- `[instruction] what: take vitamin C | quote: "I've been taking vitamin C" (patient)` and the note says nothing
  about vitamin C -> **not_in_note**, attribution_speaker (the patient's own action shown as an instruction).
- `[event] what: works from home on Fridays` and the note says nothing about it -> **not_in_note**, none.

## For the human reviewer

- Open `human_review.csv` (UTF-8) and `human_review_context.md` side by side; hide the `annotator_label` column while
  you label, so it does not anchor you.
- Rows `...|note|Nxx`: write `covered` or `not_covered` in `human_label`, judging against all candidate facts of that
  consultation (listed in the context file), not only the ones in `context_quote`.
- Rows `...|extracted|Exx`: write `consistent`, `contradicts` or `not_in_note`, judging against the whole note.
- Leave a row empty if you cannot decide; it is left out of the agreement. Then run
  `python -I scripts/primock_gold_eval.py kappa --csv <folder>/human_review.csv`.
