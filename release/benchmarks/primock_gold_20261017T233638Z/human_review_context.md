# Human review context

Fill `human_label` in human_review.csv with the labels of research/primock_gold_v1/ANNOTATION_GUIDE.md: note rows `covered` / `not_covered`, extracted rows `consistent` / `contradicts` / `not_in_note`. Hide the annotator_label column while labelling (it anchors). Then run `python -I scripts/primock_gold_eval.py kappa --csv <this folder>/human_review.csv`.

Source: PriMock57 (CC BY 4.0, see ATTRIBUTION.txt); mock consultations with actors.

## day1_consultation04

Note facts:

- N01 [history] 4/7 hx of generally unwell
- N02 [history] mainly sore throat
- N03 [history] runny nose
- N04 [history] fatigue
- N05 [history] myalgia and general joint pain
- N06 [history] Sore throat is improving
- N07 [history] Also has nasal congestion
- N08 [history] Now developed a cough -mainly dry
- N09 [history] constant
- N10 [history] Night sweats for the past 4/7
- N11 [history] Initially had fever
- N12 [history] but now settling with paracetamol/ibuprofen
- N13 [history] No chest pain
- N14 [history] Feels more SOB on exertion
- N15 [history] Associated headaches - generalized
- N16 [history] intermittent
- N17 [history] No visual sx/photophobia
- N18 [history] No nausea/vomiting
- N19 [history] No bowel or urinary sx
- N20 [history] Drinking fluids
- N21 [history] reduced appetite
- N22 [history] No rashes
- N23 [pmh] Nil
- N24 [medications] nil
- N25 [allergies] NKDA
- N26 [family_history] Grandmother - type 2 diabetes
- N27 [social_history] lives alone
- N28 [social_history] works as an accountant
- N29 [social_history] Occasional smoker/etOH
- N30 [social_history] Finding work slightly stressful
- N31 [social_history] No mood sx
- N32 [impression] viral URTI/influenza
- N33 [plan] Conservative mx - rest
- N34 [plan] push fluids
- N35 [plan] regular paracetamol/ibuprofen
- N36 [plan] monitor temp
- N37 [plan] Review in 5-7d INB (safety-net)
- N38 [plan] Discussed red flag sx (SOB, chest pain, fevers)- if present, for urgent review with Dr (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: stress is good kind | quote: "it's the good kind of stress" (said by: patient)
- E02 [event] what: night sweats make me tired and uneasy | quote: "makes me a bit tired, um makes my uneasy" (said by: patient)
- E03 [event] what: no nausea or vomiting | quote: "No, none of that" (said by: patient)
- E04 [event] what: headaches are general | quote: "Um it's sort of general" (said by: patient)
- E05 [family] what: grandma has diabetes; who: grandma | quote: "my grandma has diabetes" (said by: patient)
- E06 [event] what: occasionally smokes cigars at company parties | quote: "occasionally, you know, cigars and things on company parties" (said by: patient)
- E07 [event] what: initial fever now settled | quote: "had initial fever, but now settled" (said by: doctor)
- E08 [event] what: runny nose clearing up, nose stuffed all the time | quote: "it's uh it's clearing up . Sort of um, sort of getting my nose stuffed all the time" (said by: patient)
- E09 [instruction] what: take a day or two off work | quote: "I'd probably advise you taking a day or two off work if you can" (said by: doctor)
- E10 [diagnosis_stated] what: viral upper respiratory tract infection or early flu | quote: "I think you probably have, you know a bit of a viral, what we say viral illness, maybe a viral upper respiratory tract infection, or maybe early signs of a flu" (said by: doctor)
- E11 [event] what: patient is an accountant | quote: "I'm an, I'm an accountant" (said by: patient)
- E12 [event] what: feeling bad and tired | quote: "kind of uh bad and tired" (said by: patient)
- E13 [next_step] what: if next week you're still not better, I'd like you to come back and see me | quote: "if next week you're still not better, I'd like you to come back and see me" (said by: doctor)
- E14 [medication] name: Ibuprofen; status: continue | quote: "I've been taking some Paracetamol and Ibuprofen for that" (said by: patient)
- E15 [event] what: sore throat going into a cough | quote: "It's sort of, um, it's sort of going into a cough now" (said by: patient)
- E16 [event] what: painful to swallow for one or two days | quote: "it was quite painful to swallow, for one or two days" (said by: patient)
- E17 [event] what: feels winded on exertion | quote: "I feel a bit winded on exertion" (said by: patient)
- E18 [event] what: patient likes job | quote: "I like my job" (said by: patient)
- E19 [event] what: cough started recently, maybe yesterday | quote: "that started recently, like just uh um maybe yesterday" (said by: patient)
- E20 [event] what: started with sore throat and runny nose | quote: "it started with the um, uh sore throat and runny nose" (said by: patient)
- E21 [event] what: eating a bit less than usual | quote: "maybe a bit less than uh than what I, I would usually have" (said by: patient)
- E22 [event] what: feeling under the weather for the past four days | quote: "I've been feeling kind of uh under the weather for the past four days" (said by: patient)
- E23 [event] what: no current medications or treatments | quote: "there isn't anything that I'm taking or, I'm being treated for" (said by: patient)
- E24 [event] what: cough is constant | quote: "it's sort of constant" (said by: patient)
- E25 [instruction] what: get plenty of rest | quote: "get plenty of rest" (said by: doctor)
- E26 [event] what: cough is dry, not very painful, constant | quote: "it's dry for now, it's it's not very painful but it's sort of there, all the time" (said by: patient)
- E27 [event] what: occasionally drinks alcohol, not a big drinker | quote: "occasionally yeah I would have some. I'm, I'm not a very big drinker" (said by: patient)
- E28 [event] what: having night sweats | quote: "I'm also having uh night sweats" (said by: patient)
- E29 [event] what: patient lives alone | quote: "I live alone" (said by: patient)
- E30 [medication] name: Paracetamol; status: continue | quote: "I've been taking some Paracetamol and Ibuprofen for that" (said by: patient)
- E31 [event] what: starting to cough | quote: "I'm starting to cough" (said by: patient)
- E32 [event] what: urine OK | quote: "passing urine OK" (said by: doctor)
- E33 [event] what: drinking more than usual | quote: "I've been drinking a lot more than the usual" (said by: patient)
- E34 [event] what: bowels working OK | quote: "bowels working OK" (said by: doctor)
- E35 [medication] name: Paracetamol; status: continue | quote: "Continue with the regular Paracetamol, Ibuprofen" (said by: doctor)
- E36 [event] what: symptoms for last four days: unwell, sore throat, runny nose, dry cough, muscle pain, weakness | quote: "since the last four days you've been feeling generally quite unwell, sore throat, runny nose, bit of a dry cough, bit of muscle pain, weakness" (said by: doctor)
- E37 [medication] name: Ibuprofen; status: continue | quote: "Continue with the regular Paracetamol, Ibuprofen" (said by: doctor)
- E38 [family] what: great grandad had eczema; who: great grandad | quote: "one of my uh, great grandads had an eczema" (said by: patient)
- E39 [event] what: drinks socially with work | quote: "socially with work" (said by: doctor)
- E40 [family] what: grandma's diabetes type is type two; who: grandma | quote: "I think it's type two" (said by: patient)
- E41 [event] what: had fever in the beginning, now going down | quote: "I had some some fever in the beginning, but it's now sort of uh going down" (said by: patient)
- E42 [event] what: work has been slower | quote: "I've been a bit slower" (said by: patient)
- E43 [warning_signs] what: high fever, breathing becoming more labored, chest pain | quote: "if you have a high fever, or your breathing is becoming a bit more labored, or chest pain" (said by: doctor)
- E44 [event] what: more work than usual | quote: "it's a bit more work than usual" (said by: patient)
- E45 [event] what: sore throat going away | quote: "the sort throat is kind of going away" (said by: patient)
- E46 [instruction] what: push fluids and stay well-hydrated | quote: "Making yourself, pushing fluids and make yourself well-hydrated" (said by: doctor)
- E47 [instruction] what: come back and see me much sooner, give me a call | quote: "I'd like you to come back and see me much sooner, give me a call" (said by: doctor)
- E48 [event] what: sore throat was quite painful for a couple days then passed | quote: "it started as normal sore throat, and uh was quite painful for a couple days, but then it was past" (said by: patient)
- E49 [event] what: patient will take a couple days off | quote: "I think I'll take a couple days off, and see how it goes" (said by: patient)
- E50 [event] what: no chest pain | quote: "no pain in chest" (said by: patient)
- E51 [event] what: stressful period around end of year | quote: "it's a bit of a stressful period just around the um, end of the year" (said by: patient)
- E52 [event] what: managing to go to work | quote: "I've been actually going to work, um sort of managing" (said by: patient)
