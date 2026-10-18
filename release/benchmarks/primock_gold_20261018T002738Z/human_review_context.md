# Human review context

Fill `human_label` in human_review.csv with the labels of research/primock_gold_v1/ANNOTATION_GUIDE.md: note rows `covered` / `not_covered`, extracted rows `consistent` / `contradicts` / `not_in_note`. Hide the annotator_label column while labelling (it anchors). Then run `python -I scripts/primock_gold_eval.py kappa --csv <this folder>/human_review.csv`.

Source: PriMock57 (CC BY 4.0, see ATTRIBUTION.txt); mock consultations with actors.

## day2_consultation06

Note facts:

- N01 [history] Worried about difficulty breathing and lip swelling
- N02 [history] also localized rash
- N03 [history] No PMHx of anaphylaxis
- N04 [history] no use of epipen in past
- N05 [history] Has had anxiety in past- felt panicked now
- N06 [history] No Fh of note
- N07 [social_history] software engineer
- N08 [social_history] has cat at home
- N09 [social_history] Ex: Now: no lip swelling seen
- N10 [social_history] speaking normally
- N11 [social_history] no airways compromise
- N12 [social_history] No rash seen on arm
- N13 [impression] localized inflammatory reaction to insect bite
- N14 [impression] no evidence of acute anaphylactic reaction or cellulitis
- N15 [plan] for OTC antihistamines
- N16 [plan] Warned re red flags sings/ symptoms- if these occur to get urgent medical review (safety-net)
- N17 [plan] No need for allergy testing on a one-off episode
- N18 [plan] To ring back if any concerns/ anxiety- may need more reassurance (safety-net)
- N19 [plan] Pt has had a bee/wasp bite a few minutes prior to appointment
- N20 [plan] Worried about difficulty breathing and lip swelling
- N21 [plan] also localized rash
- N22 [plan] No PMHx of anaphylaxis
- N23 [plan] no use of epipen in past
- N24 [plan] Has had anxiety in past- felt panicked now
- N25 [plan] No Fh of note
- N26 [social_history] software engineer
- N27 [social_history] has cat at home
- N28 [social_history] Ex: Now: no lip swelling seen
- N29 [social_history] speaking normally
- N30 [social_history] no airways compromise
- N31 [social_history] No rash seen on arm
- N32 [impression] localized inflammatory reaction to insect bite
- N33 [impression] no evidence of acute anaphylactic reaction or cellulitis
- N34 [plan] for OTC antihistamines
- N35 [plan] Warned re red flags sings/ symptoms- if these occur to get urgent medical review (safety-net)
- N36 [plan] No need for allergy testing on a one-off episode
- N37 [plan] To ring back if any concerns/ anxiety- may need more reassurance (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [warning_signs] what: swelling of lips, difficulty breathing, stridor | quote: "You would have, swelling of the lips, difficulty breathing. You might have something called stridor, which is an inspiratory sound that you, when you're trying, trying to breathe. It makes like a rasping sound, like this." (said by: doctor)
- E02 [event] what: stung a few minutes ago | quote: "it was, just a few minutes ago." (said by: patient)
- E03 [next_step] what: make an appointment or go to A and E if deteriorates | quote: "if anything changes, if anything deteriorates. Either make an appointment with us, or go straight to A and E." (said by: doctor)
- E04 [event] what: wasp sting on arm | quote: "it was on my arm" (said by: patient)
- E05 [warning_signs] what: deterioration in breathing is urgent | quote: "if anything deteriorates, in terms of your breathing, that's urgent and we need to process that, , action needs to be taken urgently." (said by: doctor)
- E06 [instruction] what: have a lower threshold for chatting with us if worried | quote: "If you're feeling worried, just have a lower threshold for , having a chat with us" (said by: doctor)
- E07 [instruction] what: consider other treatments like an antibiotic if infection signs appear | quote: "We may need to think about other treatments, like an antibiotic." (said by: doctor)
- E08 [warning_signs] what: redness in arm spreads, feels hot, or signs of localised infection | quote: "if, the redness in your arm spreads, and you, it feels hot, or you, you know, you have signs of any localised infection." (said by: doctor)
- E09 [instruction] what: take the one-a-day antihistamine to control the reaction | quote: "That should be enough to control this." (said by: doctor)
- E10 [instruction] what: take antihistamines | quote: "What I'd like you to do now, is I'd like you to try and take some antihistamines." (said by: doctor)
- E11 [diagnosis_stated] what: straightforward localised reaction to an insect bite | quote: "I think this is just a , a straightforward localised reaction to a, an insect bite." (said by: doctor)
- E12 [diagnosis_stated] what: puncture mark from wasp sting | quote: "The puncture mark, yeah, OK, all right" (said by: doctor)
- E13 [diagnosis_stated] what: difficulty breathing | quote: "I've got this difficulty breathing" (said by: patient)
- E14 [diagnosis_stated] what: blotchy rash, not particularly swollen | quote: "Not particularly. I, I guess it's just a bit kind of blotchy, uh, and a bit of a rash. It doesn't feel like, particularly swollen" (said by: patient)
- E15 [instruction] what: I don't think you need any allergy testing | quote: "I don't think you need any allergy testing." (said by: doctor)
- E16 [diagnosis_stated] what: feeling anxious | quote: "I'm feeling like slightly anxious" (said by: patient)
- E17 [diagnosis_stated] what: swelling in lips | quote: "there's a bit of swelling in my lips" (said by: patient)
- E18 [diagnosis_stated] what: allergy to penicillin | quote: "I'm allergic to penicillin" (said by: patient)
- E19 [event] what: patient name is John Doe | quote: "my name is John Doe" (said by: patient)
- E20 [next_step] what: come back if further issues | quote: "come back to us if you have any further issues." (said by: doctor)
- E21 [event] what: has a cat at home | quote: "I have a cat, at home" (said by: patient)
- E22 [diagnosis_stated] what: slightly red rash with a hole at sting site | quote: "it's slightly red, yeah and, and kind of there's, a bit of a, like a hole there, where I think that the wasp, stung me" (said by: patient)
- E23 [instruction] what: read information about anaphylactic reactions | quote: "I'm gonna leave a link to some information about anaphylactic reactions, just for you to read about it." (said by: doctor)
- E24 [instruction] what: Yeah, that's, that's over the, yeah , over the counter. You don't need to, any chemist, will have it, you don't need a prescription for that | quote: "Yeah, that's, that's over the, yeah , over the counter. You don't need to, any chemist, will have it, you don't need a prescription for that." (said by: doctor)
- E25 [diagnosis_stated] what: tongue feels weird | quote: "My tongue feels a bit weird" (said by: patient)
- E26 [event] what: works as computer scientist | quote: "I am a, uh, computer scientist" (said by: patient)
- E27 [diagnosis_stated] what: rash on arm where stung | quote: "I've got a bit of a, a rash on my arm where, i got stung" (said by: patient)
- E28 [diagnosis_stated] what: localised allergic reaction | quote: "It seems to me like this is a localised allergic reaction." (said by: doctor)
- E29 [event] what: stung by a wasp | quote: "I got stung by a wasp, um, recently." (said by: patient)
- E30 [instruction] what: get back to us if anaphylactic symptoms happen | quote: "If those kind of things happen, get back to us." (said by: doctor)
- E31 [diagnosis_stated] what: history of eczema | quote: "I've, I've had eczema before" (said by: patient)
- E32 [instruction] what: buying over the counter is cheaper than prescription | quote: "it's probably cheaper to buy it over the counter actually, than to get it via prescription." (said by: doctor)
- E33 [attending] who: Doctor Deen Mirza | quote: "I'm Doctor Deen Mirza from Babylon" (said by: doctor)
- E34 [diagnosis_stated] what: occasional anxiety or panic attacks | quote: "Uh, yeah, uh, sometimes, occasionally" (said by: patient)
- E35 [instruction] what: consider blood testing if reactions become regular or non-specific rashes occur | quote: "if it was to happen that, you know, this, you're, you're having these kind of reactions on a regular basis or other, , non-specific rashes. We might need to think about blood testing" (said by: doctor)
- E36 [next_step] what: go straight to A and E if progressing rapidly | quote: "if it's, if it's, uh, progressing rapidly, it's better to go straight to A and E, rather than to, wait for a booked appointment with us" (said by: doctor)
- E37 [medication] name: Piriton or Chlorphenamine; status: new; dose: one tablet, four milligrams; frequency: up to about six times a day | quote: "You can get Piriton or Chlorphenamine, and you can take one tablet, four milligrams, um, up to about six times a day." (said by: doctor)

## day1_consultation11

Note facts:

- N01 [history] 3/7 hx of diarrhea - watery stools
- N02 [history] opening bowels every hour
- N03 [history] No blood in stools
- N04 [history] Assoc crampy abdo pain - central
- N05 [history] intermittent
- N06 [history] severity 6/10
- N07 [history] Feels nauseous
- N08 [history] has vomited occasionally
- N09 [history] Feeling feverish
- N10 [history] hot/cold
- N11 [history] Nil urinary sx - passing less urine
- N12 [history] no weight loss
- N13 [history] Brother also had similar sx - improving
- N14 [history] Tolerating oral intake
- N15 [pmh] nil
- N16 [medications] nil regular
- N17 [allergies] NKDA
- N18 [family_history] father - colon Ca
- N19 [social_history] lives with sister and mum
- N20 [social_history] Works in office
- N21 [social_history] Smokes socially
- N22 [social_history] EtOH - socially
- N23 [impression] gastroenteritis
- N24 [plan] Push fluids
- N25 [plan] OTC diarolyte
- N26 [plan] Encourage soft diet
- N27 [plan] Regular paracetamol
- N28 [plan] Review in 48 hours, or earlier if worsening sx (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [medication] name: Paracetamols; status: continue | quote: "I've been taking some like Paracetamols and stuff like that lately" (said by: patient)
- E02 [event] what: brother said he has had something for a little while | quote: "he said he had, he's had something for a little while as well" (said by: patient)
- E03 [event] what: diarrhoea with large volume | quote: "I think it's diarrhoea. And it's like just coming out, like loads of it." (said by: patient)
- E04 [instruction] what: take regular Paracetamol if feeling feverish | quote: "you can try just you know regular Paracetamol if you are feeling feverish." (said by: doctor)
- E05 [medication] name: Diarolyte; status: new | quote: "you can get things like Diarolyte" (said by: doctor)
- E06 [warning_signs] what: feels like burning up | quote: "I'm pretty sure I'm burning up" (said by: patient)
- E07 [warning_signs] what: urinating less frequently | quote: "I guess less frequently maybe" (said by: patient)
- E08 [event] what: watery stools | quote: "I go to the toilet and it's just super watery" (said by: patient)
- E09 [event] what: brother has had similar symptoms for five days | quote: "my brother has had, actually had something like this for um he has it as well for five days" (said by: patient)
- E10 [diagnosis_stated] what: diarrhoea | quote: "I think it's diarrhoea" (said by: patient)
- E11 [event] what: pain in the middle, not on any side | quote: "it feels pretty , like in the middle, to me. Not on any side, left or right." (said by: patient)
- E12 [family] what: colon cancer; who: dad | quote: "my dad actually has um colon cancer at the moment" (said by: patient)
- E13 [event] what: patient works in government | quote: "I work in government." (said by: patient)
- E14 [warning_signs] what: vomited completely after milk | quote: "one time I just like had some milk, and I just completely vomited it" (said by: patient)
- E15 [family] what: has had similar symptoms for five days; who: brother | quote: "my brother has had, actually had something like this for um he has it as well for five days" (said by: patient)
- E16 [event] what: patient has more alcohol on Fridays | quote: "On Fridays I have more um alcohol" (said by: patient)
- E17 [event] what: symptoms started three days ago | quote: "three days ago was when it all kicked off" (said by: doctor)
- E18 [event] what: crampy pain at the bottom of tummy | quote: "It's kind of, . If I think about it, it's like, it's like at the bottom." (said by: patient)
- E19 [event] what: the vomiting is not as, uh, prominent as the diarrhea | quote: "the vomiting is not as, uh, prominent as the diarrhea" (said by: doctor)
- E20 [event] what: patient smokes socially, not regularly | quote: "I smoke um, I smoke uh, uh for like socially, but not like regularly." (said by: patient)
- E21 [instruction] what: avoid alcohol | quote: "Try and avoid alcohol if you can." (said by: doctor)
- E22 [instruction] what: clear fluids, soft diet, gradually build up, stay well-hydrated | quote: "clear fluids. You can use soft diet, things like soup, mash. And then gradually build up, um as much as your body can tolerate. Um, but let's try and keep yourself well-hydrated first, OK?" (said by: doctor)
- E23 [event] what: cramp before needing to go | quote: "I feel a cramp. and then, and then I know it's time to go right?" (said by: patient)
- E24 [family] what: may be getting better but not sure; who: brother | quote: "I think he's getting better, but I'm not, I'm not really sure" (said by: patient)
- E25 [event] what: trying to drink a lot of water | quote: "I'm trying to drink a lot of water" (said by: patient)
- E26 [event] what: going to toilet almost every hour when awake | quote: "I feel like it's like almost every hour, when I'm awake." (said by: patient)
- E27 [event] what: patient goes out with friends and drinks a lot once or twice a month | quote: "once or twice a month, that yeah, I'll go out with my friends and drink a lot" (said by: patient)
- E28 [warning_signs] what: feeling hot all the time | quote: "I feel kind of really hot all the time" (said by: patient)
- E29 [medication] name: Paracetamol; status: continue | quote: "Absolutely. If you are having, if you've got a bit of tummy pain, if you're feeling feverish, then I think Paracetamol is very sensible." (said by: doctor)
- E30 [event] what: pain comes and goes | quote: "it comes and goes" (said by: patient)
- E31 [instruction] what: get Diarolyte from the pharmacy | quote: "you can get things like Diarolyte, which is um, a fluid replacement you can get from the pharmacy." (said by: doctor)
- E32 [warning_signs] what: nausea | quote: "I definitely feel kind of nauseous" (said by: patient)
- E33 [event] what: not getting better | quote: "it just kind of hasn't, doesn't feel like it's getting better" (said by: patient)
- E34 [warning_signs] what: I haven't actually done any temperature reading | quote: "I haven't actually done any temperature reading" (said by: patient)
- E35 [diagnosis_stated] what: gastroenteritis | quote: "I think your symptoms are suggestive of something called gastroenteritis." (said by: doctor)
- E36 [event] what: cramp around every hour | quote: "around every hour I just feel something come up" (said by: patient)
- E37 [warning_signs] what: urination seems OK | quote: "it seems to be OK" (said by: patient)
- E38 [warning_signs] what: I'm not a, like not a normal temperature | quote: "I'm not a, like not a normal temperature" (said by: patient)
- E39 [instruction] what: drink plenty of fluids | quote: "Drink, make sure you drink plenty of fluids, OK?" (said by: doctor)
- E40 [event] what: pain rated as six or seven out of ten | quote: "maybe is that like a six, or a seven" (said by: patient)
- E41 [warning_signs] what: vomiting | quote: "I've have vomited" (said by: patient)
- E42 [medication] name: Paracetamol; status: new | quote: "regular Paracetamol if you are feeling feverish" (said by: doctor)
- E43 [family] what: lives with sister and mum; who: sister and mum | quote: "I live with my, um sister and my mum" (said by: patient)
- E44 [family] what: third stage of colon cancer; who: dad | quote: "he's sort of in his third stage" (said by: patient)
- E45 [warning_signs] what: vomiting triggered by milk | quote: "whenever I have like milk or something like that, I just feel like I want to vomit" (said by: patient)
- E46 [event] what: stools pouring from bum | quote: "it's just pouring straight from my bum" (said by: patient)
- E47 [event] what: symptoms for about three days | quote: "I think it was about three, it's been about three days now." (said by: patient)
- E48 [event] what: brother has been ill for five days | quote: "he's been like this for five days" (said by: patient)
- E49 [event] what: had lunch | quote: "I had some lunch today" (said by: patient)
- E50 [event] what: I can still sit down and Uh I can still like cover it up, and people don't really notice | quote: "I can still sit down and Uh I can still like cover it up, and people don't really notice" (said by: patient)
- E51 [event] what: patient might have a beer during weekdays | quote: "I might have a a beer during the weekdays" (said by: patient)

## day4_consultation09

Note facts:

- N01 [history] Confirmed name
- N02 [history] DOB
- N03 [history] Tight chest
- N04 [history] 3 hours
- N05 [history] Slight SOB
- N06 [history] Slight wheezy
- N07 [history] Slight cough
- N08 [history] Slight cold last week
- N09 [history] Still symotoms of cold and cough has stayed
- N10 [history] Non productive
- N11 [history] Cough - worse at night
- N12 [history] When young - asthma exacerbation aged 16yrs
- N13 [pmh] Asthma
- N14 [pmh] Hayfever
- N15 [pmh] Dust allergy
- N16 [pmh] Medications
- N17 [pmh] Ventolin
- N18 [pmh] Clenil modulate
- N19 [allergies] NKDA
- N20 [family_history] Mother - Excema
- N21 [family_history] Father Asthma
- N22 [ice] Inhalers
- N23 [impression] Asthma exacerbation
- N24 [impression] Plan
- N25 [impression] Further salbutamol
- N26 [impression] Clinil
- N27 [impression] With spacer
- N28 [impression] Read label - S/e warned
- N29 [impression] Pred - 40mg 5 days
- N30 [impression] S/e warned mood changes
- N31 [impression] hyperglycemia
- N32 [impression] nausea
- N33 [impression] Safety netted - If worsening SOB or concerns seek further medical attention (safety-net)
- N34 [impression] Confirmed name
- N35 [impression] DOB
- N36 [impression] Tight chest
- N37 [impression] 3 hours
- N38 [impression] Slight SOB
- N39 [impression] Slight wheezy
- N40 [impression] Slight cough
- N41 [impression] Slight cold last week
- N42 [impression] Still symotoms of cold and cough has stayed
- N43 [impression] Non productive
- N44 [impression] Cough - worse at night
- N45 [impression] When young - asthma exacerbation aged 16yrs
- N46 [pmh] Asthma
- N47 [pmh] Hayfever
- N48 [pmh] Dust allergy
- N49 [pmh] Medications
- N50 [pmh] Ventolin
- N51 [pmh] Clenil modulate
- N52 [allergies] NKDA
- N53 [family_history] Mother - Excema
- N54 [family_history] Father Asthma
- N55 [ice] Inhalers
- N56 [impression] Asthma exacerbation
- N57 [impression] Plan
- N58 [impression] Further salbutamol
- N59 [impression] Clinil
- N60 [impression] With spacer
- N61 [impression] Read label - S/e warned
- N62 [impression] Pred - 40mg 5 days
- N63 [impression] S/e warned mood changes
- N64 [impression] hyperglycemia
- N65 [impression] nausea
- N66 [impression] Safety netted - If worsening SOB or concerns seek further medical attention (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [medication] name: Ventolin; status: new | quote: "I would quite like to, uh, certainly get you some, uh, Ventolin, Clenil Modulite" (said by: doctor)
- E02 [event] what: cough | quote: "Kind of cough , coughing, yeah" (said by: patient)
- E03 [instruction] what: Rest until feeling better | quote: "I think I would advise you just to, rest a little bit until you're feeling a bit better" (said by: doctor)
- E04 [medication] name: Clenil; status: continue | quote: "just on the Clenil, and the Salbutamol" (said by: patient)
- E05 [medication] name: hayfever and dust allergies; status: continue | quote: "I have like, a hayfever, you know, and some allergies just to dust" (said by: patient)
- E06 [family] what: eczema; who: mum | quote: "my mum has eczema, and my dad has asthma" (said by: patient)
- E07 [diagnosis_stated] what: tight chest | quote: "you've got this tight, tight chest" (said by: doctor)
- E08 [event] what: had a cold last week | quote: "I had a cold last week" (said by: patient)
- E09 [event] what: had tube put down throat in high school | quote: "when I was in high school, I had to have a tube put down my throat" (said by: patient)
- E10 [medication] name: Clenil Modulite; status: continue; frequency: in the morning | quote: "use the Clenil Modulite in the morning, with Ventolin as a PRN" (said by: doctor)
- E11 [instruction] what: Time off work, self-certify first seven days | quote: "I might give you some time off work as well. You can self-certify first seven days" (said by: doctor)
- E12 [event] what: confirmed hospital stay for asthma | quote: "Yeah I did, yeah" (said by: patient)
- E13 [medication] name: Ventolin; status: continue; frequency: as a PRN | quote: "use the Clenil Modulite in the morning, with Ventolin as a PRN" (said by: doctor)
- E14 [event] what: chest tightness | quote: "my chest has been feeling really tight" (said by: patient)
- E15 [event] what: can't get full breath in sometimes | quote: "It just feels like sometimes, I can't get a full breath in" (said by: patient)
- E16 [event] what: forgot to bring inhalers | quote: "I forgot to bring it with me" (said by: patient)
- E17 [event] what: inhalers ran out about a week ago | quote: "About a week ago" (said by: patient)
- E18 [medication] name: Ventolin; status: continue | quote: "currently you're just on Ventolin and Clenil" (said by: doctor)
- E19 [event] what: asthma exacerbations in past | quote: "Have you had asthma exacerbations in the past?" (said by: doctor)
- E20 [event] what: had eczema in youth | quote: "when I was young, I also had eczema" (said by: patient)
- E21 [event] what: cough persists | quote: "the cough's kind of stuck around" (said by: patient)
- E22 [diagnosis_stated] what: asthmatic response | quote: "dampen down your asthmatic response" (said by: doctor)
- E23 [event] what: Not in a long time. When I was young, a little bit, more like, back in high school | quote: "Not in a long time. When I was young, a little bit, more like, back in high school" (said by: patient)
- E24 [event] what: was away at university last week | quote: "I was away at uni last week" (said by: patient)
- E25 [event] what: cough slightly worse at night, consistent, not gone | quote: "it gets a little bit worse at night but, basically, just pretty consistent, and it hasn't gone away" (said by: patient)
- E26 [medication] name: steroids; status: new; dose: two tablets in the morning; frequency: for five days | quote: "give you a, dose of steroids. So this is, these are tablets which, um, you can take for five days. Uh, two tablets in the morning" (said by: doctor)
- E27 [medication] name: Clenil; status: continue | quote: "currently you're just on Ventolin and Clenil" (said by: doctor)
- E28 [event] what: has been good at taking inhalers | quote: "I've been pretty good at taking my , my inhalers" (said by: patient)
- E29 [event] what: wheezing | quote: "I'm feeling a bit wheezy, as well" (said by: patient)
- E30 [instruction] what: seek medical attention if using Ventolin more than every three hours | quote: "If you should start to use the Ventolin more than, uh, every three hours. Uh, at, at anytime, it's a good idea to seek medical attention" (said by: doctor)
- E31 [medication] name: Clenil Modulite; status: new | quote: "I would quite like to, uh, certainly get you some, uh, Ventolin, Clenil Modulite" (said by: doctor)
- E32 [warning_signs] what: Worsening shortness of breath, chest tightness, feeling light-headed, or generally concerning symptoms | quote: "Any deterioration in your symptoms, like worsening shortness of breath. Um, or just generally concerning symptoms, uh, pain in your chest tightness, uh, feeling light-headed" (said by: doctor)
- E33 [diagnosis_stated] what: non-productive cough and shortness of breath | quote: "it's non-productive cough, and you're short of breath" (said by: doctor)
- E34 [procedure_planned] what: send a spacer | quote: "the other thing I'd like to send you is a spacer" (said by: doctor)
- E35 [event] what: more short of breath than normal when walking up stairs | quote: "It does when I'm walking up stairs, I do feel like, I have a little bit, more short of breath than I would normally be" (said by: patient)
- E36 [medication] name: Salbutamol; status: continue | quote: "just on the Clenil, and the Salbutamol" (said by: patient)
- E37 [family] what: asthma; who: dad | quote: "my dad has asthma" (said by: patient)
- E38 [event] what: duration of chest tightness | quote: "for about. Three hours now" (said by: patient)
- E39 [event] what: stayed in hospital for a few days with asthma exacerbation | quote: "you stayed in hospital for a few days did you, with an asthma exacerbation?" (said by: doctor)
- E40 [diagnosis_stated] what: cold with wheezy cough | quote: "it certainly sounds like uh, you've, you've had this cold, so you've got wheezy with a cough" (said by: doctor)
- E41 [medication] name: inhalers; status: continue | quote: "give you a prescription for, uh, some more of the inhalers" (said by: doctor)
- E42 [event] what: sore throat and runny nose | quote: "I had a sore throat, I had a runny nose" (said by: patient)
- E43 [medication] name: asthma; status: continue | quote: "I have asthma, I've had it for a while now" (said by: patient)
- E44 [event] what: patient is not short of breath at rest at the moment | quote: "you're not short of breath at rest at the moment" (said by: doctor)
- E45 [event] what: not short of breath at rest | quote: "I'm definitely not short of breath at rest" (said by: patient)
- E46 [event] what: the runny nose isn't as bad any more | quote: "the runny nose isn't as bad any more" (said by: patient)
- E47 [event] what: had milk protein allergy in youth | quote: "I had a milk protein allergy, when I was young too" (said by: patient)

## day2_consultation01

Note facts:

- N01 [history] History
- N02 [history] Hx of difficulty hearing left ear for 6 weeks with tinnitus and slight nausea/ dizziness
- N03 [history] One previous similar episode in the past- resolved spontaneously
- N04 [history] No discharge/ fever/ itchiness/ pain
- N05 [history] Doesn't use cotton wool buds
- N06 [history] No Pmhx of note
- N07 [history] Ex: Looks well
- N08 [history] not in pain
- N09 [impression] need to exclude impacted wax in ear canal first
- N10 [impression] Pln: for face to face GP appointment in 5 days to examine ear
- N11 [impression] Pt to read about tinnitus in the meantime via following link: www.patient.co.uk/tinnitus
- N12 [impression] If any problems in interim to ring us back
- N13 [impression] Pt happy with and understands plan

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: ringing triggered by TV or music | quote: "if I'm watching TV or listen to music or something that'll solve the ringing in the ear" (said by: patient)
- E02 [next_step] what: have someone look inside ear | quote: "the first thing that we need to do is we need to get someone to have a look inside your ear" (said by: doctor)
- E03 [event] what: I just feel I can't really hear as well as I used to, like my hearing is kind of deteriorating in some way | quote: "I just feel I can't really hear as well as I used to, like my hearing is kind of deteriorating in some way." (said by: patient)
- E04 [event] what: feeling sick or dizzy | quote: "there's actually been a few times when I felt kind of a bit sick or a bit dizzy as well" (said by: patient)
- E05 [instruction] what: number left in notes | quote: "I'll leave the number in the notes for this appointment" (said by: doctor)
- E06 [event] what: no fever apart from dizziness | quote: "not specifically apart from the dizziness so much" (said by: patient)
- E07 [next_step] what: exclude simple things like wax | quote: "I'm just exclude the simple things. Simple things might be wax." (said by: doctor)
- E08 [event] what: ringing in left ear | quote: "I occasionally get like a ringing in my left ear" (said by: patient)
- E09 [instruction] what: book another appointment and speak over video if any issues | quote: "If there's any problem, any issues between now and when the clinic appointment is, just book another appointment and you can speak to one of us over video" (said by: doctor)
- E10 [diagnosis_stated] what: Tinnitus | quote: "The ringing that you got, that you've got, it's something called Tinnitus." (said by: doctor)
- E11 [instruction] what: you shouldn't be doing that. Doesn't clean up wax, it pushes it back in | quote: "you shouldn't be doing that. Doesn't clean up wax, it pushes it back in." (said by: doctor)
- E12 [event] what: previous brief hearing problem | quote: "I had something maybe, about a year ago, but it only lasted a couple of days" (said by: patient)
- E13 [next_step] what: have a look inside the ear drum to exclude physical blockage | quote: "one of the GPs will just have a quick look in the ear and figure out whether there's physical blockage or whether there's something else going on" (said by: doctor)
- E14 [event] what: no ear discharge | quote: "Any discharge coming out of the ear? No, OK." (said by: doctor)
- E15 [follow_up] what: another GP | quote: "It won't be with me, it'll be another GP" (said by: doctor)
- E16 [event] what: hearing problem duration | quote: "about six weeks" (said by: patient)
- E17 [event] what: no ear pain | quote: "Uh no my left ear" (said by: patient)
- E18 [instruction] what: read a leaflet about Tinnitus | quote: "I'm going to, uh, put paste the link for a leaflet about Tinnitus, um, in the notes for this appointment. I'd really appreciate it if you could start reading about it." (said by: doctor)
- E19 [event] what: symptoms on and off | quote: "it's kind of on and off" (said by: patient)
- E20 [event] what: hearing difficulty in left ear | quote: "just the left ear" (said by: doctor+patient)
- E21 [instruction] what: ring the support team after five minutes | quote: "bear with me five minutes and then you can ring the support team" (said by: doctor)
- E22 [procedure_planned] what: face-to-face appointment in one of our clinics; when_text: within the next four, five days or so | quote: "book you in for a face-to-face appointment in one of our clinics. It's not an emergency. It can be done within the next four, five days or so" (said by: doctor)

## day5_consultation05

Note facts:

- N01 [history] Abdo pain
- N02 [history] 2/7 hx lower abdominal pain
- N03 [history] central location
- N04 [history] Has noticed some blood in the urine
- N05 [history] Has check temp - 37
- N06 [history] No back pain
- N07 [history] Feels sweaty
- N08 [history] More thirsty than normal
- N09 [history] drinking well
- N10 [history] No dysuria/freq
- N11 [history] Constipated last week
- N12 [history] now BO normally
- N13 [history] No blood in stool
- N14 [history] Last BO 2 hrs ago
- N15 [history] No N&V
- N16 [history] no dyspepsia
- N17 [pmh] Nil
- N18 [medications] Nil
- N19 [medications] Allergic to amoxicillin
- N20 [medications] FMH: Mum had breast cancer
- N21 [medications] now in remission
- N22 [social_history] Lives with parents
- N23 [social_history] Non smoker
- N24 [social_history] No drugs
- N25 [social_history] Drinks 1 beer x 4/week
- N26 [impression] UTI
- N27 [plan] Advised 3/7 course Abx
- N28 [plan] Will pick up from pharmacy
- N29 [plan] To start asap
- N30 [plan] If develops temperature/persistent/worsening pain to call back or if recurrent similar sx (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: slight blood in urine, pink | quote: "there was some, like, slight, uh, blood in the urine, but, like, it was a little bit pink" (said by: patient)
- E02 [event] what: constipated last week, now fine | quote: "I had been constipated in, like, in the last, um, last week, but now it's fine" (said by: patient)
- E03 [next_step] what: if the pain is getting worse, or you have a high temperature or back pain or develop any new symptoms, we feel like it's not getting better, then, um, we should speak to you again, because we might need to see you face-to-face for an examination | quote: "if the pain is getting worse, or you have a high temperature or back pain or develop any new symptoms, we feel like it's not getting better, then, um, we should speak to you again, because we might need to see you face-to-face for an examination." (said by: doctor)
- E04 [event] what: nausea but no vomiting | quote: "I'm just a bit nausea but no vomiting" (said by: patient)
- E05 [family] what: breast cancer; who: mom | quote: "my mom had the breast cancer" (said by: patient)
- E06 [event] what: no similar problems before | quote: "no similar problems to this before" (said by: doctor)
- E07 [diagnosis_stated] what: possible infection in the urine | quote: "it may be possible that you might be having an infection in the urine." (said by: doctor)
- E08 [medication] name: beer; status: continue; dose: a beer | quote: "a beer like, per time" (said by: patient)
- E09 [medication] name: contraceptive implant; status: continue | quote: "I have had the just, the, uh, internal uh, contraceptive implant, but like, for one year, now, no more." (said by: patient)
- E10 [event] what: pain in lower tummy for last two days | quote: "I have had a pain in my lower tummy the last two days" (said by: patient)
- E11 [instruction] what: start taking antibiotics as soon as you get them, twice a day for three days | quote: "Start taking them as soon as you get them, it's just twice a day for three days." (said by: doctor)
- E12 [event] what: feeling hot and sweaty | quote: "I feel kind of hot and sweaty" (said by: patient)
- E13 [warning_signs] what: pain getting worse, high temperature, back pain, or new symptoms | quote: "if the pain is getting worse, or you have a high temperature or back pain or develop any new symptoms" (said by: doctor)

## day1_consultation14

Note facts:

- N01 [history] 5/7 hx of cough and runny nose
- N02 [history] Dry cough
- N03 [history] keeps pt up at night
- N04 [history] Runny nose
- N05 [history] no ear pain
- N06 [history] no sore throat
- N07 [history] No SOB/chest pain
- N08 [history] Feeling tired
- N09 [history] weak and myalgia
- N10 [history] Feeling shivery
- N11 [history] hot/cold
- N12 [history] ?fever
- N13 [history] No nausea/vomiting
- N14 [history] Appetite maintained
- N15 [history] Initial diarrhea - but now resolved
- N16 [history] Nil urinary symptoms
- N17 [history] No rashes
- N18 [pmh] Type 2 diabetes
- N19 [pmh] HTN
- N20 [medications] metformin
- N21 [medications] lisinopril
- N22 [allergies] NKDA
- N23 [family_history] Father - type 2 diabetes
- N24 [social_history] lives with partner
- N25 [social_history] works IT
- N26 [social_history] denies stress
- N27 [social_history] Ex-smoker - stopped 6/12 ago
- N28 [social_history] Social EtOH <14 units/week
- N29 [impression] viral URTI
- N30 [plan] Supportive mx - bed rest
- N31 [plan] fluids
- N32 [plan] regular paracetamol
- N33 [plan] Review 5/7 if no better, or earlier if worsening sx (fever, SOB, chest pain) (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [medication] name: Paracetamol; status: continue; dose: regular; frequency: regular | quote: "You can take regular Paracetamol." (said by: doctor)
- E02 [event] what: took a day off to recover | quote: "I've been able to take a day off to try and recover" (said by: patient)
- E03 [event] what: partner has no symptoms | quote: "he has none of this" (said by: patient)
- E04 [event] what: working | quote: "I am working" (said by: patient)
- E05 [warning_signs] what: if your cough isn't getting any better, or your breathing is getting worse, I want you to come back and see me sooner | quote: "if your cough isn't getting any better, or your breathing is getting worse, I want you to come back and see me sooner." (said by: doctor)
- E06 [event] what: feeling like lying in bed | quote: "all I feel like doing is just lying in bed" (said by: patient)
- E07 [next_step] what: If you feel like you're still not getting any better in two to three days, it's probably worth coming back to see me again | quote: "If you feel like you're still not getting any better in two to three days, it's probably worth coming back to see me again." (said by: doctor)
- E08 [event] what: muscle pain | quote: "My muscle was really hurting" (said by: patient)
- E09 [event] what: has been going to work | quote: "I've been going in" (said by: patient)
- E10 [event] what: cough and runny nose | quote: "I've just been having this like, cough, for quite a few days. And my nose is running." (said by: patient)
- E11 [event] what: expected duration of illness | quote: "It normally lasts for about a week to ten days." (said by: doctor)
- E12 [event] what: lives with partner | quote: "it's just me and my partner" (said by: patient)
- E13 [event] what: drinks two or three glasses on drinking nights | quote: "maybe two or three glasses" (said by: patient)
- E14 [event] what: shivers in bed | quote: "I've been having like, like shivers, even when I'm in, when I'm in bed." (said by: patient)
- E15 [event] what: works in IT | quote: "work in IT" (said by: patient)
- E16 [event] what: current muscle pain | quote: "it's hurting me so much at the moment" (said by: patient)
- E17 [event] what: does not think illness related to stress | quote: "I don't think it's related to stress" (said by: patient)
- E18 [instruction] what: rest, drink fluids, stay hydrated | quote: "get some nice, good rest. Drink plenty of fluids. Keep yourself well-hydrated." (said by: doctor)
- E19 [event] what: diarrhea stopped | quote: "And then it stopped" (said by: patient)
- E20 [instruction] what: try to cut down alcohol altogether if coping | quote: "if you are coping OK, then you can maybe try and cut down altogether" (said by: doctor)
- E21 [event] what: job not too active | quote: "not too active a job" (said by: patient)
- E22 [event] what: job is developer | quote: "I am a developer" (said by: patient)
- E23 [event] what: diabetes and blood pressure under control | quote: "I have it under control" (said by: patient)
- E24 [diagnosis_stated] what: high blood pressure | quote: "I have quite high blood pressure" (said by: patient)
- E25 [medication] name: Lisinopril; status: continue | quote: "I take Lisinopril for the high blood pressure." (said by: patient)
- E26 [event] what: rarely gets properly drunk | quote: "I rarely get like properly drunk" (said by: patient)
- E27 [event] what: I was next to my boyfriend. And he was completely warm and totally fine. And I just like couldn't stop shivering. And kept adding more sweaters on, and I was still cold | quote: "I was next to my boyfriend. And he was completely warm and totally fine. And I just like couldn't stop shivering. And kept adding more sweaters on, and I was still cold." (said by: patient)
- E28 [event] what: duration of symptoms | quote: "It's been five days." (said by: doctor)
- E29 [event] what: regular doctor visits for diabetes and blood pressure | quote: "I just regularly go see a doctor" (said by: patient)
- E30 [event] what: dry cough all day and at night | quote: "It's quite dry. And it's just all day, it like keeps me up at night as well" (said by: patient)
- E31 [event] what: diarrhea started with cough | quote: "it started at the same time as the cough started" (said by: patient)
- E32 [event] what: stopped smoking six months ago | quote: "I used to, but I've stopped for about six months now" (said by: patient)
- E33 [event] what: lethargy and weakness | quote: "quite lethargic and weak" (said by: doctor)
- E34 [event] what: skipped first day of work | quote: "the first day I skipped" (said by: patient)
- E35 [event] what: I don't drink more than like, like, let's say three evenings a week | quote: "I don't drink more than like, like, let's say three evenings a week" (said by: patient)
- E36 [event] what: symptoms started | quote: "I think it started like maybe, a bit less than a week ago. Like maybe, maybe five or six days ago." (said by: patient)
- E37 [medication] name: Metformin; status: continue | quote: "I take Metformin for the diabetes." (said by: patient)
- E38 [diagnosis_stated] what: viral illness | quote: "you're going through a bit of a bit of a viral illness" (said by: doctor)
- E39 [event] what: diarrhea | quote: "I had a little bit of diarrhea" (said by: patient)
- E40 [event] what: pain in arms, legs, everywhere | quote: "especially like in my arms, my legs, like just everywhere basically" (said by: patient)
- E41 [event] what: does not think drinks much | quote: "I don't think I drank that much" (said by: patient)
- E42 [event] what: sore throat from coughing | quote: "the coughing is giving me a sore throat" (said by: patient)
- E43 [event] what: cough continued | quote: "the cough just kept going" (said by: patient)
- E44 [event] what: worried about passing illness to partner | quote: "I was a bit worried that I would pass it to him" (said by: patient)
- E45 [event] what: chills and feeling cold | quote: "I had chills, and I was really cold" (said by: patient)
- E46 [diagnosis_stated] what: cough, runny nose, weakness, lethargy | quote: "You know you've had a bit of a cough, bit of a runny nose, feeling quite weak and lethargic." (said by: doctor)
- E47 [instruction] what: take a day or two off work and get bed rest | quote: "I would say maybe take a day or two off work, if you can. Uh and get some good bed rest." (said by: doctor)

## day1_consultation15

Note facts:

- N01 [history] 3-4/12 hx of sore and cracked skin on my hands - mainly palms
- N02 [history] Occasionally itchy and bleeding on scratching
- N03 [history] No pain
- N04 [history] Works as a cleaner and does not always wear gloves - possible trigger
- N05 [history] No fever
- N06 [history] No bowel/urinary sx
- N07 [history] Appetite maintained
- N08 [pmh] Type 2 diabetes
- N09 [medications] metformin
- N10 [allergies] NKDA
- N11 [family_history] Type 2 diabetes
- N12 [social_history] works as a housekeeper
- N13 [social_history] recently changed jobs 4/12 ago
- N14 [social_history] works in a hotel
- N15 [social_history] Nil smoking
- N16 [social_history] Minimal etOH
- N17 [social_history] Has tried E45 cream and antihistamines with minimal relief
- N18 [impression] contact dermatitis
- N19 [plan] Steroid cream BD
- N20 [plan] Emollients - regular use
- N21 [plan] Avoid trigger
- N22 [plan] wear cleaning gloves
- N23 [plan] Review in 10-14d INB, or earlier if worsening sx (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: cleans bedrooms and bathrooms at a hotel | quote: "I have to do the whole thing like bedrooms, bathrooms." (said by: patient)
- E02 [event] what: it's itchy. Not all the time, but yeah, it does get itchy | quote: "it's itchy. Not all the time, but yeah, it does get itchy." (said by: patient)
- E03 [event] what: dryness in legs described as grinding | quote: "it's just like literally grinding my legs." (said by: patient)
- E04 [event] what: does not hydrate much | quote: "I don't hydrate very much." (said by: patient)
- E05 [instruction] what: wear gloves when cleaning at all times | quote: "I strongly recommend that you wear gloves when cleaning at all times" (said by: doctor)
- E06 [diagnosis_stated] what: dermatitis or contact dermatitis | quote: "I think you might have something called dermatitis or contact dermatitis" (said by: doctor)
- E07 [event] what: not always good at wearing gloves | quote: "you're not always very good at wearing gloves." (said by: doctor)
- E08 [event] what: not always good about wearing gloves | quote: "I'm not always very good about wearing gloves." (said by: patient)
- E09 [event] what: bleeding when scratched | quote: "when I scratched it, yes it has bled sometimes" (said by: patient)
- E10 [medication] name: steroid creams; status: new | quote: "we can try some steroid creams to help with the inflammation" (said by: doctor)
- E11 [event] what: it's gotten to a point where, where it hurts a lot. And I can't really do my job | quote: "it's gotten to a point where, where it hurts a lot. And I can't really do my job." (said by: patient)
- E12 [event] what: the palm. I don't get, yeah | quote: "the palm. I don't get, yeah." (said by: patient)
- E13 [event] what: I haven't been able to go to work | quote: "I haven't been able to go to work." (said by: patient)
- E14 [event] what: recently changed jobs | quote: "you've recently changed jobs." (said by: doctor)
- E15 [event] what: works at a hotel | quote: "At a hotel." (said by: patient)
- E16 [event] what: symptoms started three to four months ago | quote: "I got it three, four months ago." (said by: patient)
- E17 [event] what: works as housekeeper | quote: "I do work as a housekeeper" (said by: patient)
- E18 [event] what: dryness in legs | quote: "I have dryness, like you know, in other parts, like my legs." (said by: patient)
- E19 [event] what: drinks a couple of pints of alcohol a week | quote: "a couple of pints a week." (said by: patient)
- E20 [event] what: like the past three days, I haven't been able to go to work | quote: "like the past three days, I haven't been able to go to work." (said by: patient)
- E21 [diagnosis_stated] what: diabetes | quote: "I have diabetes." (said by: patient)
- E22 [event] what: soreness in fingers and cracked skin on hands | quote: "I have uh soreness in my fingers, my finger, like, the skin on my hands is kind of cracked." (said by: patient)
- E23 [event] what: switched jobs four months ago | quote: "I switched jobs, uh four months ago." (said by: patient)
- E24 [instruction] what: prescription sent to pharmacy | quote: "I'll I'll I'll do a prescription for you now, and send it over to your pharmacy" (said by: doctor)
- E25 [medication] name: Metformin; status: continue | quote: "Which medications do you take? Metformin, OK." (said by: doctor)
- E26 [medication] name: stronger emollients; status: new; frequency: three four times a day | quote: "some stronger emollients, um which you really need to kind of coat on, three four times a day, for the next couple of weeks" (said by: doctor)
- E27 [event] what: works as a housekeeper | quote: "you work as a housekeeper." (said by: doctor)
- E28 [event] what: skin is quite cracked | quote: "skin is quite cracked as well." (said by: doctor)

## day3_consultation07

Note facts:

- N01 [history] History
- N02 [history] Red sore rash for the past few days
- N03 [history] All over the chest hands and arms
- N04 [history] Worse especially in the inside of the arms
- N05 [history] There is no scratch marks
- N06 [history] No thickened skin
- N07 [history] Rash is dry and itchy
- N08 [history] No fever and joint pains
- N09 [history] Used hydrocortisone and cetirizine not better
- N10 [pmh] asthma
- N11 [pmh] eczema
- N12 [medications] diprobase
- N13 [medications] dermol
- N14 [medications] hydrocortisone
- N15 [medications] salbutamol
- N16 [medications] FH Hypothyroidism
- N17 [medications] No allergies
- N18 [plan] advised will prescribe fexofenatidine and Betnovate for eczema
- N19 [plan] Need to use steroid cream sparingly
- N20 [plan] Explained one finger tip enough to cover the palms and back of your hands
- N21 [plan] If your symptoms are getting worse or there is an allergic reaction please speak with doctor urgently (safety-net)
- N22 [plan] If your symptoms are not better in the next 2 weeks please book another appointment with the doctor (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [instruction] what: use a fingertip amount of Betnovate to cover palms and back of hands | quote: "it's like one fingertip. Yeah. This much is, is enough to cover your palms. And your - back of your hands" (said by: doctor)
- E02 [medication] name: diprovate; status: continue | quote: "as well as the, diprovate" (said by: doctor)
- E03 [medication] name: blue inhaler; status: continue; frequency: on and off | quote: "The blue inhaler? So you don't, you don't use it everyday, so you just use it on and off" (said by: doctor)
- E04 [medication] name: Betnovate; status: new | quote: "we'll try with some Betnovate first" (said by: doctor)
- E05 [diagnosis_stated] what: extensive eczema | quote: "you've got , as I've mentioned. So, extensive eczema." (said by: doctor)
- E06 [event] what: itchy when scratching but no scratch marks | quote: "it's very itchy if I scratch myself, but there's no scratch mark" (said by: patient)
- E07 [medication] name: asthma; status: continue | quote: "you have asthma" (said by: doctor)
- E08 [instruction] what: wait for two weeks, take medication and cream | quote: "Otherwise, wait for two weeks, take the medication and the cream" (said by: doctor)
- E09 [medication] name: Fexofenadine; status: new | quote: "the antihistamine is called Fexofenadine" (said by: doctor)
- E10 [event] what: breathing issue only when having a flare | quote: "It's only when I have a flare." (said by: patient)
- E11 [instruction] what: If, if there's no improvement, you need to get back to us | quote: "If, if there's no improvement, you need to get back to us" (said by: doctor)
- E12 [medication] name: diprobase; status: continue | quote: "usually I use a a a cream called diprobase" (said by: patient)
- E13 [instruction] what: call if things get worse in the next two weeks | quote: "If things are getting worse in the next two weeks, call us before hand" (said by: doctor)
- E14 [instruction] what: use Betnovate twice a day for the next couple of weeks | quote: "use that. You, you have to use it twice a day, for the next couple of weeks" (said by: doctor)
- E15 [medication] name: Hydrocortisone; status: continue | quote: "So you're using the Hydrocortisone, yeah?" (said by: doctor)
- E16 [family] what: migraine; who: mother | quote: "my mother has migraine" (said by: patient)
- E17 [event] what: not the areas that are cracked | quote: "not the areas that are cracked" (said by: patient)
- E18 [event] what: skin sore and red on chest, hands, arms, inside of elbows | quote: "it's uh, all over my chest, my hands and arms, and especially inside of the elbows" (said by: patient)
- E19 [instruction] what: prescription sent to Boots pharmacy | quote: "we're going to send off the prescription to your pharmacy. It looks like Boots on the systems" (said by: doctor)
- E20 [medication] name: steroids; status: continue | quote: "You've used steroids before?" (said by: doctor)
- E21 [medication] name: antihistamines; status: new | quote: "you would probably need some antihistamines, which I'm going to prescribe" (said by: doctor)
- E22 [event] what: skin condition getting worse | quote: "it's getting worse, like, the past few days. Way worse" (said by: patient)
- E23 [event] what: skin sore and red | quote: "over the past few days I had uh, I've noticed my skin is uh, sore and red" (said by: patient)
- E24 [diagnosis_stated] what: widespread eczema | quote: "it is quite widespread, your eczema" (said by: doctor)
- E25 [medication] name: dermal; status: continue | quote: "in the shower I use something called dermal" (said by: patient)
- E26 [medication] name: emollients (dermal soap); status: continue | quote: "You still need to continue on your, emollients like the dermal soap" (said by: doctor)
- E27 [warning_signs] what: adverse reaction or allergic reaction | quote: "if you have any kind of adverse reaction, like an allergic reaction, which is unlikely, but if it still happens you need to get in touch with us" (said by: doctor)
- E28 [event] what: skin itchy and dry all over body | quote: "It's very itchy and, uh, dry, all over my body" (said by: patient)

## day5_consultation02

Note facts:

- N01 [history] Dysuria
- N02 [history] 6/7 hx dysuria
- N03 [history] burning stinging sensation when PUs
- N04 [history] No problem with actually passing urine
- N05 [history] Strong odour
- N06 [history] E&D normally
- N07 [history] No new PV discharge
- N08 [history] No back/loin pain
- N09 [history] Not feverish but not checked temp.No obvious trigger
- N10 [history] no hx dehydration/frequent SI
- N11 [history] No PHx urine infections/similar sx
- N12 [history] No recent change in BH/blood in stool
- N13 [pmh] IBS
- N14 [family_history] Nil
- N15 [medications] Mebeverine 200mg TDS
- N16 [medications] NKDA
- N17 [social_history] Lives with friends
- N18 [social_history] Works as support worker
- N19 [social_history] Non smoker
- N20 [social_history] Drinks 1 unit/week
- N21 [impression] Likely UTI
- N22 [plan] Nitrofurantoin 3/7 course
- N23 [plan] Advised patient to contact us if fever/back pain/persistent symptoms or if recurrent episodes of similar symptoms occurs (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [warning_signs] what: if you feel like your pain is getting worse or not settling, you get lower back pain, um, or you're getting a high temperature, or you have any problems actually passing urine | quote: "if you feel like your pain is getting worse or not settling, you get lower back pain, um, or you're getting a high temperature, or you have any problems actually passing urine" (said by: doctor)
- E02 [instruction] what: get a thermometer and check temperature | quote: "It would be helpful if you could get a thermometer from the pharmacy and, do check your temperature" (said by: doctor)
- E03 [event] what: no fever or temperature | quote: "No, not at all." (said by: patient)
- E04 [event] what: regular periods | quote: "Yes I do." (said by: patient)
- E05 [event] what: blood spots in urine | quote: "I've had spotted, uh, blood in my urine. Spots." (said by: patient)
- E06 [attending] who: Doctor Smith | quote: "I'm Doctor Smith from Babylon." (said by: doctor)
- E07 [instruction] what: Wait about an hour before picking up the prescription | quote: "Give it a, an hour or so." (said by: doctor)
- E08 [event] what: pain when urinating | quote: "It hurts when I pee." (said by: patient)
- E09 [event] what: lower abdominal pain location | quote: "In my lower tummy." (said by: patient)
- E10 [event] what: unpleasant smell when urinating | quote: "I've got this very unpleasant smell that comes out." (said by: patient)
- E11 [instruction] what: take sachets to change urine acidity | quote: "some sachets which just help change the acidity of your urine" (said by: doctor)
- E12 [event] what: abdominal pain in the middle | quote: "In the middle." (said by: doctor+patient)
- E13 [medication] name: Mebeverine; status: continue | quote: "I've had Mebeverine, Mebeverine. I've had Mebeverine." (said by: patient)
- E14 [next_step] what: prescription sent to pharmacy | quote: "I can send a prescription through to your requested pharmacy" (said by: doctor)
- E15 [event] what: lives with friends | quote: "I live with friends." (said by: patient)
- E16 [event] what: no past medical problems | quote: "No medical, no." (said by: patient)
- E17 [event] what: history of IBS | quote: "I had IBS before." (said by: patient)
- E18 [diagnosis_stated] what: urine infection | quote: "it sounds very much like you, might have an infection in your urine." (said by: doctor)
- E19 [instruction] what: drink cranberry juice | quote: "you can get some cranberry juice and take, drink that as well" (said by: doctor)
- E20 [event] what: job is support worker | quote: "I'm a support worker." (said by: patient)
- E21 [instruction] what: drink two and a half to three litres of water a day | quote: "drink, lots of water. So, two and a half to three litres a day." (said by: doctor)
- E22 [event] what: abdominal pain | quote: "I've got, pain in my tummy." (said by: patient)
- E23 [event] what: pain is intermittent | quote: "Comes and goes." (said by: patient)
- E24 [medication] name: antibiotics; status: new | quote: "the antibiotics, that I'm gonna prescribe, um, will go through to that, pharmacy" (said by: doctor)
- E25 [warning_signs] what: recurrent problem | quote: "if it becomes a, common, thing or a recurrent problem" (said by: doctor)
- E26 [event] what: no vaginal discharge | quote: "No, just the blood spot, in my." (said by: patient)
- E27 [event] what: drinks one glass of wine a week | quote: "One glass of wine a week." (said by: patient)
- E28 [event] what: no loin pain | quote: "No, I've got. Um, and no loin pain as well." (said by: patient)
- E29 [event] what: blood in urine over last six days | quote: "Yes, but I've had spotted, uh, blood in my urine. Spots." (said by: patient)
- E30 [event] what: no fever | quote: "No fever at all." (said by: patient)

## day3_consultation10

Note facts:

- N01 [history] Diarrhoea for 3 days
- N02 [history] Also associated abdominal pain
- N03 [history] No mucous
- N04 [history] no blood
- N05 [history] Vomiting once
- N06 [history] Still eating and drinking
- N07 [history] Diarrhea like water 4-5 times a day
- N08 [history] No fever
- N09 [history] Loss od appetite
- N10 [history] Did not eat out
- N11 [history] No foreign travel
- N12 [history] No dehydration on examination
- N13 [pmh] asthma
- N14 [family_history] Dad died of bowel cancer 10 years
- N15 [family_history] HTN
- N16 [family_history] Medication ?
- N17 [family_history] Lapriso
- N18 [family_history] No allergies
- N19 [impression] Gastroenteritis
- N20 [plan] advised soft diet
- N21 [plan] drink plenty
- N22 [plan] Start with crackers
- N23 [plan] soups and mash
- N24 [plan] Then can build on with mash and vegetable
- N25 [plan] Can use yoghurts as probiotics and will help build the gut
- N26 [plan] If the diarhoea goes on for more than a week or there is blood, we would need a stool sample
- N27 [plan] If there is diarrhea more than 8 episodes, you may get dehydrated please book an appointment

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: going to the toilet four to five times a day | quote: "four to five" (said by: doctor+patient)
- E02 [event] what: dry and red (likely skin or mouth) | quote: "Mostly it's been dry and red" (said by: patient)
- E03 [instruction] what: drink plenty of water | quote: "You still need to drink plenty of water because you're losing a lot of fluids." (said by: doctor)
- E04 [instruction] what: after diarrhea improves, start with boiled vegetables and mash | quote: "Once you are able to, you know keep most of it in, you can start off with some just boiled vegetables and mash." (said by: doctor)
- E05 [event] what: possible slight fever | quote: "maybe a little bit" (said by: patient)
- E06 [warning_signs] what: going six to eight times a day indicates dehydration and possible need for hospital | quote: "if you're going about six to eight times a day, that means there's a high chance that, uh, you are, having dehydration and you might need to go into hospital" (said by: doctor)
- E07 [instruction] what: eat yoghurts as probiotics to rebuild gut bacteria | quote: "yoghurts are a good idea because they are probiotics, it help to build up the normal, um gut, gut bacteria back" (said by: doctor)
- E08 [instruction] what: soft diet avoiding dairy, fish, meat, eggs | quote: "things that one would advise is a soft diet. So avoid dairy, fish, meat, eggs, while you're having the diarrhea." (said by: doctor)
- E09 [event] what: vomited once | quote: "I threw up once" (said by: patient)
- E10 [diagnosis_stated] what: diarrhea | quote: "you just have diarrhea it's about four to five times a day" (said by: doctor)
- E11 [event] what: diarrhea for three days | quote: "it's been happening for about, three days now" (said by: patient)
- E12 [medication] name: Dioralyte; status: new | quote: "you could get something called Dioralyte over the counter. So, it helps to uh, replenish your, the salts that you've been, that's lost through going to the toilet." (said by: doctor)
- E13 [warning_signs] what: diarrhea more than eight times a day is concerning | quote: "when we start worrying about diarrhea is if you're going more than eight times a day" (said by: doctor)
- E14 [instruction] what: details are recorded in the patient's app for reference | quote: "all this is all recorded in your app. So you can go back. I'll put that all in detail" (said by: doctor)
- E15 [event] what: no mucus in stool | quote: "No, so no mucus" (said by: doctor)
- E16 [instruction] what: soft diet includes crackers, toast, jam | quote: "that will be like crackers, toast, jam, those kind of things that's easily digested" (said by: doctor)
- E17 [instruction] what: Forty-eight hours you're not having any diarrhea, you're fine then you can go and start having meat, egg, fish and all | quote: "Forty-eight hours you're not having any diarrhea, you're fine then you can go and start having meat, egg, fish and all." (said by: doctor)
- E18 [event] what: appetite loss worse than normal | quote: "Appetite loss I guess worse than normal" (said by: patient)
- E19 [instruction] what: contact the doctor if going six to eight times a day | quote: "If that happens you get in touch with us again" (said by: doctor)
- E20 [warning_signs] what: if your diarrhoea doesn't go away in a week's time, or if you're passing blood, we need a stool sample | quote: "if your diarrhoea doesn't go away in a week's time, or if you're passing blood, we need a stool sample" (said by: doctor)

## day3_consultation03

Note facts:

- N01 [history] History : having lack of energy for the past 3 months
- N02 [history] You are also having loss of appetite
- N03 [history] You are lacking motivation
- N04 [history] You are complaining of breathlessness and some times associated with palpitations
- N05 [history] There is no chest pain
- N06 [history] You are not depressed or stressed
- N07 [history] Your bowels are normal
- N08 [history] You feel nauseous most of the time
- N09 [history] There is no vomiting
- N10 [history] You are also experiencing some weight loss in the past 6 months about a stone
- N11 [history] There is no history of acid reflux
- N12 [history] Past medical history: you suffer from underactive thyroid
- N13 [medications] you have not been using the thyroxine for a while since you changed practice
- N14 [medications] You do not remember the last time you had your last set of bloods
- N15 [plan] you have been advised to contact support to help you to organize your blood test
- N16 [plan] This will look at aneamia
- N17 [plan] thyoids
- N18 [plan] liver
- N19 [plan] kidney and vitamin levels
- N20 [plan] You will need to book in for another appointment after you receive a text message from Babylon
- N21 [plan] If you develop chest pain with the palpitations, change in bowel habits you will need to contact us urgently (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: nausea every now and again | quote: "I feel nauseous every now and again" (said by: patient)
- E02 [warning_signs] what: palpitations or chest pain require going to A and E | quote: "with palpitations or chest pain, if you get that's more of a medical emergency. You need to go to A and E for that" (said by: doctor)
- E03 [event] what: no diarrhoea | quote: "no. No diarrhoea" (said by: patient)
- E04 [next_step] what: receive text message to book appointment after blood test result | quote: "when you get the result, you will receive a text message through your phone to tell you to book an appointment" (said by: doctor)
- E05 [event] what: weight loss amount less than a stone | quote: "less than a storm, something like that" (said by: patient)
- E06 [event] what: symptoms started three and a half months ago | quote: "Three months ago, three and a half months ago, that was" (said by: patient)
- E07 [procedure_planned] what: general set of bloods | quote: "a general set of bloods is a good , good start" (said by: doctor)
- E08 [family] what: wife complaining about nightly activities; who: wife | quote: "my, my, my wife was starting to complain as well, uh in, in nightly activities" (said by: patient)
- E09 [instruction] what: call support to arrange blood test | quote: "you need to ring up support" (said by: doctor)
- E10 [event] what: feeling down and lacking energy | quote: "Started long, long ago now" (said by: patient)
- E11 [event] what: can walk about a mile without shortness of breath | quote: "you can walk about a mile and you don't feel short of breath at all" (said by: doctor)
- E12 [next_step] what: blood tests | quote: "let's do all the blood tests first" (said by: doctor)
- E13 [instruction] what: contact the clinic if chest pains or change in bowel habits occur | quote: "if you have any chest pains, or change in bowel habits, do get in touch with us" (said by: doctor)
- E14 [event] what: symptoms started when changed to new law firm | quote: "It must have started when I When I changed over to the new law firm" (said by: patient)
- E15 [event] what: weight loss started earlier than a half months ago | quote: "It started a little bit earlier than that" (said by: patient)
- E16 [event] what: weight loss duration at least six months | quote: "at least six months, would you say?" (said by: doctor)
- E17 [event] what: trouble at work with headaches and nausea | quote: "I have trouble at work sometimes, having headaches, feeling nauseous" (said by: patient)
- E18 [event] what: patient has not been feeling good enough | quote: "I haven't been feeling good enough for a good at all" (said by: patient)
- E19 [diagnosis_stated] what: underactive thyroid | quote: "I had too little activity of my thyroid" (said by: patient)
- E20 [attending] who: Dr. Jacob | quote: "I'm Dr. Jacob" (said by: doctor)
- E21 [event] what: loss of appetite and not eating much | quote: "I'm having a loss of appetite, I'm, uh, yeah I'm not eating very much" (said by: patient)
- E22 [event] what: trying to eat something, but don't really want to | quote: "trying to eat something, but don't really want to" (said by: patient)
- E23 [procedure_planned] what: physical examination | quote: "we would need to do a physical examination" (said by: doctor)
- E24 [event] what: shortness of breath and out of energy | quote: "I'm feeling short of breath, breath it's like always yeah, out of energy" (said by: patient)
- E25 [event] what: no problems with toilet, painless | quote: "I don't really have problems when going to the toilet, it's just painless" (said by: patient)
- E26 [instruction] what: call the number on the app | quote: "there's a number on your app" (said by: doctor)
- E27 [event] what: no acid reflux | quote: "I do not, no" (said by: patient)
- E28 [event] what: no shortness of breath when walking | quote: "No, actually not" (said by: patient)
- E29 [next_step] what: blood test first, then decide | quote: "start off with a blood test, and then take it from there" (said by: doctor)
- E30 [event] what: my heart starts beating and I can't really breath | quote: "my heart starts beating and I can't really breath" (said by: patient)
- E31 [event] what: I'm feeling not well, uh, in the, in the, in the bowel region | quote: "I'm feeling not well, uh, in the, in the, in the bowel region" (said by: patient)
- E32 [event] what: lost a little weight | quote: "I have, a little bit, yes" (said by: patient)
- E33 [event] what: no blood in poo, no mucus | quote: "no, no, nothing" (said by: patient)
- E34 [event] what: patient has not been walking lately | quote: "I haven't been walking lately at all" (said by: patient)
- E35 [warning_signs] what: bowel changes or being sick again require contacting the clinic | quote: "if your, you know, bowels change or you're being sick again, you need to get in touch with us" (said by: doctor)
- E36 [event] what: shortness of breath significantly in lift | quote: "It happens very significantly in, in the lift" (said by: patient)
- E37 [event] what: weight loss duration | quote: "weight loss is much longer than that" (said by: doctor)

## day1_consultation09

Note facts:

- N01 [history] 3/7 hx of dysuria and suprapubic pain
- N02 [history] Nil frequency
- N03 [history] Brief episode of haematuria
- N04 [history] now resolved
- N05 [history] Foul smelling
- N06 [history] Abdo pain - cramping
- N07 [history] nil radiating
- N08 [history] Nil nausea/vomiting
- N09 [history] Nil fever
- N10 [history] Nil bowel sx
- N11 [history] Currently sexually active - with regular partner for 2/12
- N12 [history] No previous STD screen
- N13 [history] Nil PV discharge
- N14 [history] LMP 2/52 ago
- N15 [pmh] IBS
- N16 [medications] Nil regular
- N17 [medications] Allergic to clindamycin
- N18 [family_history] Nil regular
- N19 [social_history] lives in a flat with friends
- N20 [social_history] student in Biology
- N21 [social_history] nil smoking
- N22 [social_history] social EtOH at weekends
- N23 [impression] UTI/cystitis
- N24 [plan] Nitrofurantoin abx for 3/7
- N25 [plan] Push fluids
- N26 [plan] Trial cranberry juice
- N27 [plan] Pregnancy test to exclude pregnancy
- N28 [plan] Review in 3d if no better, or earlier if worsening sx (fevers, back pain, vomiting, more unwell) (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: sexually active | quote: "are you currently sexually active?" (said by: doctor)
- E02 [event] what: never had an STD screen | quote: "Don't think I've ever, I don't think I've ever had one." (said by: patient)
- E03 [event] what: last period was a couple of weeks ago | quote: "couple of weeks ago" (said by: patient)
- E04 [event] what: tried over-the-counter bicarbonate for pain, not helpful | quote: "try some uh, over the counter bicarbonate, to try and help with the pain but it wasn't, it wasn't really helping" (said by: patient)
- E05 [event] what: no discharge noticed | quote: "I haven't noticed anything." (said by: patient)
- E06 [instruction] what: avoid sex while symptoms clear up, continue using barrier contraception | quote: "if you can try and avoid it, I think that'd be sensible. Um, uh, it's great that you're using barrier contraception. I would recommend you to continue using barrier contraception, but if you can avoid it while your symptoms clear up." (said by: doctor)
- E07 [event] what: lower tummy pain when using bathroom | quote: "I also maybe sometimes get some like, pain kind of lower down in my tummy, when I, when I go to the bathroom" (said by: patient)
- E08 [event] what: allergy causes swelling | quote: "I get some like a, a, a swelling, basically" (said by: patient)
- E09 [event] what: symptoms for a few days | quote: "it's been going on for a few days" (said by: patient)
- E10 [diagnosis_stated] what: simple UTI or urinary tract infection, bladder infection | quote: "I think probably do have what we call a simple UTI or urinary tract infection, bladder infection" (said by: doctor)
- E11 [warning_signs] what: high temperatures, back pain, generally feeling more unwell, possible infection spreading to kidneys | quote: "if you are having kind of, high temperatures, a back pain, um just , generally feeling more unwell. Uh, you know, I do want you give me a call back, 'cause then we do worry whether your infection may be spreading up towards your kidneys" (said by: doctor)
- E12 [follow_up] what: call or come back if not better; when_text: by the end of this week | quote: "if you're still not better, by the end of this week, I want you to give me a call or come back and see me" (said by: doctor)
- E13 [event] what: uses condoms as contraception | quote: "we use condoms" (said by: patient)
- E14 [event] what: cramping tummy pain | quote: "sort of, sort of cramping" (said by: patient)
- E15 [event] what: pain does not move to back or sides | quote: "No, not really, no" (said by: patient)
- E16 [event] what: is a student | quote: "I'm a student" (said by: patient)
- E17 [event] what: has history of IBS | quote: "in the past I've had some uh, some IBS" (said by: patient)
- E18 [event] what: lives in a flat near college with friends | quote: "I live in a, live in a flat near my college, with a, a couple of like friends of mine" (said by: patient)
- E19 [event] what: blood in urine earlier today | quote: "there was a little bit of blood earlier today" (said by: patient)
- E20 [event] what: has a boyfriend for a couple of months | quote: "I've had a boyfriend for about a, a couple of months now" (said by: patient)
- E21 [event] what: no diarrhoea or loose stool | quote: "no, not that I've, not that I've noticed at all" (said by: patient)
- E22 [event] what: bowels working OK | quote: "I think so, yeah, it seems" (said by: patient)
- E23 [instruction] what: drink plenty of fluids | quote: "I also advise you to drink plenty of fluids." (said by: doctor)
- E24 [event] what: feels OK otherwise | quote: "I'm feeling OK, otherwise" (said by: patient)
- E25 [event] what: no fever | quote: "No, no, no fever, no" (said by: patient)
- E26 [instruction] what: try cranberry juice | quote: "you can try, cranberry juice, that can sometimes help with your symptoms" (said by: doctor)
- E27 [event] what: does not think she is pregnant | quote: "I don't think so, I don't." (said by: patient)
- E28 [attending] who: Doctor | quote: "Doctor: Hello? Hello? I can hear you, can you hear me?" (said by: doctor)
- E29 [event] what: no nausea or vomiting | quote: "no, not , not at all" (said by: patient)
- E30 [event] what: allergic to Clindamycin | quote: "I'm allergic to, Clindamycin" (said by: patient)

## day2_consultation10

Note facts:

- N01 [history] Hx: Has had headache upon waking from this morning on left side head- pain woke pt up at 530am
- N02 [history] Headache still present now
- N03 [history] Has had hx of headaches less severe and in front of the head in past
- N04 [history] No neck stiffness
- N05 [history] no fever
- N06 [history] Some sensitivity to bright lights now
- N07 [history] no nausea now
- N08 [history] Felt dizzy this morning
- N09 [history] but not now
- N10 [history] No FH of migraines
- N11 [history] Work is stressful
- N12 [history] late nights at work- ongoing for a few months
- N13 [history] Mood is stable- pmhx of anxiety for 2 years
- N14 [history] on sertraline
- N15 [history] Doesn't feel anxious right now- gets this at work at times
- N16 [history] No thoughts about self harm
- N17 [history] Headache is better when lying down
- N18 [history] Pt has taken paracetamol- not helped
- N19 [pmh] nil
- N20 [pmh] has not had BP checked
- N21 [family_history] mother has anxiety
- N22 [medications] sertraline
- N23 [allergies] Nkda
- N24 [social_history] live with partner
- N25 [social_history] Non smoker
- N26 [social_history] Hss cat
- N27 [social_history] Good exercise
- N28 [social_history] reasonable diet
- N29 [impression] tension type headache +/- migraine
- N30 [plan] for ibuprofen first line as per SIGN 2018 migraine guidelines
- N31 [plan] 5-2 litres water hydration daily
- N32 [plan] To sleep 7-8 hours minimum daily
- N33 [plan] Consider time off- to self certify for a few days to see if this helps
- N34 [plan] Self referral to IAPTs
- N35 [plan] Review in a week
- N36 [plan] If any red flag symptoms as per www.patient.co.uk/ headache, to ring back sooner (safety-net)
- N37 [plan] Patient understands and is happy with plan

Candidate facts (extracted, accepted by the grounding check):

- E01 [diagnosis_stated] what: migraine | quote: "The other possibility is, um, migraine as well." (said by: doctor)
- E02 [event] what: not so much on the one side, it tends to be, a bit of a cluster at the front of my head in a way | quote: "not so much on the one side, it tends to be, a bit of a cluster at the front of my head in a way" (said by: patient)
- E03 [event] what: work is stressful at the moment | quote: "work's kind of, um, a bit stressful at the moment. I've got a lot going on" (said by: patient)
- E04 [family] what: history of anxiety; who: mum | quote: "my mum's had a history of anxiety as well" (said by: patient)
- E05 [attending] who: Doctor from GP at Hand | quote: "This is Doctor , from GP at Hand" (said by: doctor)
- E06 [medication] name: Ibuprofen; status: new | quote: "the things that we'd start off first line, if someone had migraine was to, would be to start Ibuprofen." (said by: doctor)
- E07 [next_step] what: book an appointment in that time | quote: "I'll book an appointment, in, um, yeah, in that time" (said by: patient)
- E08 [event] what: patient's full name is Ayrton Warren | quote: "it's Ayrton Warren" (said by: patient)
- E09 [event] what: doing a lot of late nights | quote: "I've kind of, been, doing a lot of late nights as well" (said by: patient)
- E10 [warning_signs] what: danger signs of headache symptoms | quote: "some of the danger signs of symptoms of headaches" (said by: doctor)
- E11 [event] what: I'm a little bit sensitive it just, it kind of, makes my eyes a little bit sore, but nothing that I can't really handle | quote: "I'm a little bit sensitive it just, it kind of, makes my eyes a little bit sore, but nothing that I can't really handle" (said by: patient)
- E12 [instruction] what: explore counselling options | quote: "I'd also like you to explore, counselling options as well" (said by: doctor)
- E13 [event] what: woke up with horrible pain on left side of head | quote: "I kind of woke up this morning, um, and I've just got this, really horrible pain on the left side of my head" (said by: patient)
- E14 [next_step] what: ring back if anything changes, worried, or things get worse | quote: "if anything changes in the meantime, or you get worried or things get worse. Feel free, have a lower threshold for ringing us back" (said by: doctor)
- E15 [event] what: has a cat | quote: "I have a cat." (said by: patient)
- E16 [event] what: lives with partner | quote: "I live with my partner." (said by: patient)
- E17 [next_step] what: try that in the first instance | quote: "we'll try that in the first instance" (said by: doctor)
- E18 [diagnosis_stated] what: tension headache | quote: "it sounds like it might be one of two things. It could be an element of what we call tension headache." (said by: doctor)
- E19 [next_step] what: book an appointment and reassess the situation | quote: "we can book you an appointment, and we can reassess the situation" (said by: doctor)
- E20 [instruction] what: read the link about danger signs of headache symptoms | quote: "I'll also leave a link, to some of the danger signs of symptoms of headaches, in the notes" (said by: doctor)
- E21 [instruction] what: having a week off if you self-certify | quote: "maybe having a week off if you self-certify" (said by: doctor)
- E22 [instruction] what: minimum of seven, eight hours sleep at night, every night | quote: "try and ensure that you're having a minimum of seven, eight hours sleep at night, every night" (said by: doctor)
- E23 [medication] name: Paracetamol; status: continue | quote: "I've taken some Paracetamol." (said by: patient)
- E24 [instruction] what: you're drinking a minimum of, um, one point five to two litres uh, of water or fluids a day, and that's not including coffee or tea | quote: "you're drinking a minimum of, um, one point five to two litres uh, of water or fluids a day, and that's not including coffee or tea" (said by: doctor)
- E25 [event] what: felt dizzy on first getting up, now subsided | quote: "When I first got up this morning, my head felt a bit dizzy, but that's kind of subsided now" (said by: patient)
- E26 [follow_up] what: follow-up; when_text: in a week's time | quote: "we'll have a follow-up in a week's time" (said by: doctor)
- E27 [event] what: pain woke patient up | quote: "it woke me up, um, quite early this morning" (said by: patient)
- E28 [event] what: this time it's just kind of more prominent on the left side which, I've never really had it, normally they kind of spread across the front of my head | quote: "this time it's just kind of more prominent on the left side which, I've never really had it, normally they kind of spread across the front of my head" (said by: patient)
- E29 [medication] name: Paracetamol; status: continue | quote: "You can keep on taking Paracetamol as well if you like" (said by: doctor)
- E30 [medication] name: Sertraline; status: continue | quote: "I've been on, uh, Sertraline for, a while." (said by: patient)
- E31 [event] what: stress and late nights have been going on for about a couple of months | quote: "Uh, for probably about a couple of months now" (said by: patient)
- E32 [follow_up] what: follow-up appointment | quote: "let's have a follow-up appointment" (said by: doctor)
- E33 [event] what: has a lot of backlog of work | quote: "I've got a lot going on. Um, yeah, I just seem to have like, a lot of, kind of, a backlog of work that I need to go through at the moment" (said by: patient)
- E34 [event] what: patient's name is Atan | quote: "My name's Atan" (said by: patient)
- E35 [instruction] what: consider taking time off work | quote: "maybe consider taking some time off work" (said by: doctor)
- E36 [event] what: history of headaches but not as severe | quote: "I've, had a bit of a history with headaches, but nothing as severe as this before" (said by: patient)
- E37 [diagnosis_stated] what: anxiety | quote: "I had, like anxiety for about, two years now" (said by: patient)

## day5_consultation07

Note facts:

- N01 [history] Cough and cold
- N02 [history] 4-5 day hx runny nose
- N03 [history] dry cough
- N04 [history] No sputum/haemoptysis
- N05 [history] No epistaxis/sinus pain
- N06 [history] Feels hot
- N07 [history] hasn't measured temperature
- N08 [history] No SOB/inspiratory pain/wheeze
- N09 [history] Aches and pains
- N10 [history] No vomiting
- N11 [history] E&D ok
- N12 [history] PUing ok
- N13 [history] No hx chest problems/recurrent chest infections/wt loss
- N14 [history] Thinks last BP was fine
- N15 [history] can't remember when last BP/DM check up was
- N16 [history] Doesn't check blood sugars/urine at home
- N17 [history] No increased thirst/urinary freq
- N18 [history] Taking 2-3 lemsips a day which eases sx
- N19 [pmh] Hypertension
- N20 [pmh] T2 DM
- N21 [medications] Lisinopril
- N22 [medications] Metformin
- N23 [medications] Height- 5ft 5in
- N24 [medications] Weight - 65kg
- N25 [social_history] Non smoker
- N26 [social_history] odd sherry
- N27 [social_history] Lives with partner and dog
- N28 [social_history] Office manager
- N29 [impression] Viral bronchitis
- N30 [plan] Advised continue lemsips but no other paracetamol containing products
- N31 [plan] Avoid cough syrup but can take if unable to sleep at night
- N32 [plan] May take 1-2 weeks to settle and cough can persist for up to a month but to contact us if symptoms not worse/fever persists - check with thermometer/coughing up phlegm/blood in sputum/nose bleeds (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [instruction] what: take your temperature | quote: "the important thing to do would be to take your temperature" (said by: doctor)
- E02 [instruction] what: get a thermometer and check temperature | quote: "it's definitely worth getting a thermometer and checking your temperature" (said by: doctor)
- E03 [event] what: lives with partner and dog | quote: "my partner and my dog" (said by: patient)
- E04 [event] what: drinks alcohol (odd cherry) | quote: "Yes, the odd cherry" (said by: patient)
- E05 [event] what: blood test was normal around three weeks ago | quote: "it was normal. It was around three weeks ago" (said by: patient)
- E06 [diagnosis_stated] what: With the diabetes you are a bit more likely to get a bacterial infection than if you didn't have the diabetes | quote: "With the diabetes you are a bit more likely to get a bacterial infection than if you didn't have the diabetes" (said by: doctor)
- E07 [event] what: takes two or three lemon sips daily, at start and end of day | quote: "maybe two or three. Maybe, like, at the start of the day and at the end of the day" (said by: patient)
- E08 [instruction] what: continue taking Lemsip | quote: "It's fine to carry on what you're doing at the moment, with the lemsip" (said by: doctor)
- E09 [event] what: suffers from hay fever | quote: "I sometimes suffer from some, like, hay fever" (said by: patient)
- E10 [event] what: works as office manager | quote: "I'm an office manager" (said by: patient)
- E11 [event] what: takes lemon sips | quote: "a quite a few lemon sips" (said by: patient)
- E12 [warning_signs] what: cough getting worse, coughing up lots of nasty phlegm, coughing up blood, or blood coming out of nose | quote: "your cough's getting worse, you're coughing up lots of nasty phlegm or you cough up any blood or get blood coming out your nose" (said by: doctor)
- E13 [warning_signs] what: if the temperature's ongoing, above thirty seven point five, thirty eight, um, and you keep spiking temperatures and that's not settling down | quote: "if the temperature's ongoing, above thirty seven point five, thirty eight, um, and you keep spiking temperatures and that's not settling down" (said by: doctor)
- E14 [instruction] what: if you're kept up all night and you can't sleep at all, then it, it's OK to have a little bit of cough syrup, just to settle that down | quote: "if you're kept up all night and you can't sleep at all, then it, it's OK to have a little bit of cough syrup, just to settle that down" (said by: doctor)
- E15 [diagnosis_stated] what: chest infection | quote: "it sounds like you, you probably have got an infection in the chest" (said by: doctor)
- E16 [medication] name: metformin; status: continue | quote: "something called metformin, and lisinopril I think is the other one" (said by: patient)
- E17 [instruction] what: have regular diabetes and blood pressure checkups as GP asked | quote: "if you make sure that you have the regular diabetes and blood pressure checkups that your GP has asked you for" (said by: doctor)
- E18 [instruction] what: the cough syrup isn't advisable in the daytime because it's best for your body if you just keep coughing | quote: "the cough syrup isn't advisable in the daytime because it's best for your body if you just keep coughing" (said by: doctor)
- E19 [event] what: lemon sips soothe throat before sleep | quote: "It tends to soothe my throat a bit for when I'm going to sleep" (said by: patient)
- E20 [warning_signs] what: shortness of breath or chest pain | quote: "any shortness of breath, chest pain" (said by: doctor)
- E21 [event] what: height is five foot five, weight is sixty five kilograms | quote: "my height is five foot five, and my weight is sixty five kilograms" (said by: patient)
- E22 [diagnosis_stated] what: infections are usually caused by viruses | quote: "most of the time, these infections are caused by viruses" (said by: doctor)

## day1_consultation05

Note facts:

- N01 [history] 2/7 ago developed lower abdo pain/suprapubic pain
- N02 [history] gradual onset
- N03 [history] burning pain
- N04 [history] constant
- N05 [history] progressively worsening
- N06 [history] No bowel sx
- N07 [history] Urinary sx - noticed some pink coloured urine
- N08 [history] no frank haematuria
- N09 [history] nil dysuria
- N10 [history] Some nausea
- N11 [history] no vomiting
- N12 [history] Feeling hot and sweaty
- N13 [history] Currently sexually active with regular partner
- N14 [history] Last STD 6/12 ago
- N15 [history] Unprotected SI 2/7 ago
- N16 [history] LMP 2/52 ago
- N17 [history] No chest pain/SOB/palpitations
- N18 [history] No headches/visual sx
- N19 [pmh] nil
- N20 [pmh] nil
- N21 [medications] implanon
- N22 [medications] otherwise nil
- N23 [family_history] nil
- N24 [social_history] roomshare with 2 flatmates
- N25 [social_history] works as an accountant
- N26 [social_history] Nil smoking
- N27 [social_history] social EtOH
- N28 [impression] ?UTI
- N29 [impression] also need to exclude pregnancy
- N30 [plan] Pregnancy test
- N31 [plan] Urine dip and MSU
- N32 [plan] Rx empirically with Abx for UTI
- N33 [plan] Regular paracetamol for pain
- N34 [plan] Review in 24-48 hours if sx not improving, or earlier if worsening sx (fever, abdo pain, vomiting) (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [family] what: no relevant family history | quote: "No, not that , not that I'm aware of, no." (said by: patient)
- E02 [medication] name: Trimethoprim; status: new | quote: "start the antibiotics today, something called Trimethoprim" (said by: doctor)
- E03 [event] what: no surgical history | quote: "I haven't had any operations before" (said by: patient)
- E04 [event] what: tummy pain, burning, getting worse | quote: "it's tummy pain that's really affected you, mainly lower down towards your belly button. It's quite burning, you said. It's getting worse." (said by: doctor)
- E05 [event] what: urine was a little pink | quote: "the urine was a little pink, in colour" (said by: patient)
- E06 [next_step] what: prescription sent to pharmacy | quote: "if I send it straight to your pharmacy" (said by: doctor)
- E07 [event] what: nausea | quote: "You've felt a little bit nauseous" (said by: doctor)
- E08 [event] what: pain is constant and getting worse | quote: "It's pretty constant, it's like getting worse" (said by: patient)
- E09 [event] what: bowels working OK | quote: "Your bowels are working OK" (said by: doctor)
- E10 [medication] name: antibiotics; status: new | quote: "covering you with some antibiotics today" (said by: doctor)
- E11 [medication] name: Implanon; status: continue | quote: "I'm not on any other medication, I just have the Implanon" (said by: patient)
- E12 [event] what: had constipation but better now | quote: "I had a bit of constipation, but that's better, now" (said by: patient)
- E13 [event] what: tummy pain has been going on for the last couple of days | quote: "it's been going on for the last couple of days" (said by: doctor)
- E14 [event] what: last sexual activity | quote: "we were last sexually active about four days ago" (said by: patient)
- E15 [instruction] what: drink plenty of fluids | quote: "make sure you drink plenty of fluids" (said by: doctor)
- E16 [follow_up] what: come back and see me in a few days time if symptoms not better or worse; when_text: in a few days time | quote: "come back and see me in a few days time, if your symptoms are not getting any better, or indeed if they're getting worse" (said by: doctor)
- E17 [event] what: burning pain | quote: "it's kind of like a, a, I guess a burning pain" (said by: patient)
- E18 [event] what: a little nauseous but no vomiting | quote: "Just a little nauseous, um, but no vomiting" (said by: patient)
- E19 [event] what: last period | quote: "my last period was about, three weeks ago. I mean, two weeks ago." (said by: patient)
- E20 [event] what: no burning or stinging pain when passing urine | quote: "no burning or stinging pain when you pass urine" (said by: doctor)
- E21 [event] what: pink urine | quote: "you noticed some pink urine" (said by: doctor)
- E22 [event] what: last STD screen was normal | quote: "my last STD screen was normal, which was about six months ago" (said by: patient)
- E23 [instruction] what: take the antibiotics | quote: "take the antibiotics" (said by: doctor)
- E24 [event] what: feeling hot and sweaty | quote: "feeling hot and sweaty" (said by: doctor)
- E25 [instruction] what: call if worried about anything else | quote: "give me a call, you know, if you are worried about anything else" (said by: doctor)
- E26 [instruction] what: have a pregnancy test done to make sure we're not missing anything else here | quote: "have a pregnancy test done to make sure we're not missing anything else here" (said by: doctor)
- E27 [event] what: patient reports no palpitations | quote: "Not that it, no." (said by: patient)
- E28 [event] what: lives in share house with two room-mates | quote: "I live in a share house, and with two other, two other room-mates." (said by: patient)
- E29 [event] what: symptoms started about two days ago | quote: "About two days ago" (said by: patient)
- E30 [event] what: patient is an accountant | quote: "I am an accountant." (said by: patient)
- E31 [event] what: patient has tummy pain | quote: "you've got some tummy pain" (said by: doctor)
- E32 [instruction] what: try cranberry juice for urine symptoms | quote: "You can try some cranberry juice as well, which uh, can sometimes help with your urine symptoms" (said by: doctor)
- E33 [warning_signs] what: worsening tummy pain, um, if you're feeling really hot or sweaty, your temperature's not coming down um, vomiting et cetera | quote: "worsening tummy pain, um, if you're feeling really hot or sweaty, your temperature's not coming down um, vomiting et cetera" (said by: doctor)
- E34 [event] what: patient reports no shortness of breath, no cough, no problems | quote: "I don't feel short of breath uh, or, I'm not having any problems, or I don't have a cough or anything that's , worrying me." (said by: patient)
- E35 [event] what: drinking lots of fluids | quote: "I have been drinking lots of fluids" (said by: patient)
- E36 [event] what: peeing more regularly | quote: "I was peeing more, regularly" (said by: patient)
- E37 [medication] name: Implanon; status: continue | quote: "I'm, on the Implanon. I had the Implanon inserted about a year ago." (said by: patient)
- E38 [next_step] what: collect prescription at pharmacy | quote: "should I just collect the script at my pharmacy?" (said by: patient)
- E39 [event] what: feeling hot and sweaty | quote: "I've just been feeling, quite, hot and sweaty" (said by: patient)
- E40 [instruction] what: take Paracetamol as regular painkiller | quote: "you can try just regular painkillers, uh, Paracetamol would be advisable" (said by: doctor)
- E41 [event] what: pain in lower tummy | quote: "I'm Having some, some pain, uh, in my tummy, like the lower part of my tummy" (said by: patient)

## day3_consultation01

Note facts:

- N01 [history] History: you are having lip swelling for the past 1 hr
- N02 [history] It started after eating a prawn soup
- N03 [history] You initially had some weird feeling around your lips
- N04 [history] The swelling started after half an hour
- N05 [history] Now you are complaining of your throat closing
- N06 [history] Your chest is tight at the moment with difficulty breathing
- N07 [examination] during the consultation
- N08 [examination] it looked like you were having some problems breathing and your lips appeared to be increasingly swelling
- N09 [examination] Past medical history : you suffer from asthma
- N10 [examination] You have had an injection as a child for a peanut allergy
- N11 [medications] you are currently on salbutamol inhalers
- N12 [medications] Treatment: your Mom was around and I have advised that you use an antihistamine straight away
- N13 [medications] I have advised Mom to call the ambulance as a 999 call as we are suspecting an anaphylactic reaction (safety-net)
- N14 [medications] After discharge from hospital please book a review with the doctor to consider prescribing an epipen

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: patient was out with friends about a year ago | quote: "I remember like a year ago. A year ago I was, out with my friends." (said by: patient)
- E02 [follow_up] what: ring back after coming out from the hospital to sort out injections and things; when_text: after you come out from the hospital | quote: "after you come out from the hospital do give us a ring back we might need to sort you out, um, with your injections and things like that" (said by: doctor)
- E03 [event] what: woke up swollen, felt bad, and had difficulty breathing | quote: "I've woke up the next morning quite swollen up and had also I, felt really bad and quite difficult breathing" (said by: patient)
- E04 [event] what: feeling weird | quote: "I feel a little weird today" (said by: patient)
- E05 [event] what: I feel like I can't breathe that well right now | quote: "I feel like I can't breathe that well right now" (said by: patient)
- E06 [event] what: somebody just came yes, I'm not alone any more | quote: "somebody just came yes, I'm not alone any more" (said by: patient)
- E07 [diagnosis_stated] what: anaphylactic reaction | quote: "It sounds like you could be going into what we say an a, an anaphylactic reaction." (said by: doctor)
- E08 [event] what: patient had a severe allergic reaction at age six | quote: "I was like six or something I, I, I think. Ohh sorry, the swelling is getting, ohh my god ohh, yeah I think when I was six." (said by: patient)
- E09 [instruction] what: go straight away to the hospital | quote: "you need go straight away" (said by: doctor)
- E10 [instruction] what: take antihistamines straight away and have mum call | quote: "Do that straight away and if mum can call" (said by: doctor)
- E11 [attending] who: Doctor Jacob | quote: "I'm Doctor Jacob" (said by: doctor)
- E12 [event] what: patient feels dizzy | quote: "I feel a little dizzy right now to be honest" (said by: patient)
- E13 [instruction] what: ask if there are antihistamines around in the interim | quote: "ask the person whether they have any antihistamines around, in the interim" (said by: doctor)
- E14 [event] what: swelling feels like pumping blood and getting worse | quote: "it still feel it like, really pumping blood and it's kinda getting bigger it feels like it's getting worse" (said by: patient)
- E15 [medication] name: peanut allergy; status: continue | quote: "I have a peanut allergy as well, like always had it." (said by: patient)
- E16 [event] what: it must have been like, must have been like, I don't know half an hour maybe | quote: "it must have been like, must have been like, I don't know half an hour maybe" (said by: patient)
- E17 [contact] what: email; value: M Traba at Gmail dot com | quote: "M Traba at Gmail dot com" (said by: patient)
- E18 [instruction] what: call the ambulance and keep the person with you until it arrives | quote: "call the ambulance make sure that person's with you till the ambulance comes" (said by: doctor)
- E19 [next_step] what: call an ambulance | quote: "I think we need to call an ambulance" (said by: doctor)
- E20 [diagnosis_stated] what: suspected anaphylactic reaction | quote: "we are worried about an anaphylactic reaction" (said by: doctor)
- E21 [event] what: lips started feeling weird on left corner | quote: "my lips started feeling a little weird just in the in the corner sort of on the left first" (said by: patient)
- E22 [event] what: it just generally feels a little difficult, but yeah it might be, I'm not sure | quote: "it just generally feels a little difficult, but yeah it might be, I'm not sure" (said by: patient)
- E23 [medication] name: Salbutamol; status: continue | quote: "I took I, I take, ohh what's it called? Salbutamol inhalers?" (said by: patient)
- E24 [event] what: ordered and ate prawn soup | quote: "I ordered a prawn soup" (said by: patient)
- E25 [medication] name: antihistamines; status: continue | quote: "I, think I do get antihistamines for that but I'm not sure which ones." (said by: patient)

## day5_consultation06

Note facts:

- N01 [history] Diarrhoea
- N02 [history] 3/7 hx diarrhoea
- N03 [history] Watery stools
- N04 [history] Urgency
- N05 [history] No blood in stool
- N06 [history] Periumbilical cramps
- N07 [history] comes in waves
- N08 [history] Worse when needs to open bowels
- N09 [history] Very regular BO
- N10 [history] today already 4 x by midday
- N11 [history] Vomiting
- N12 [history] last vomited 1 hr ago
- N13 [history] Doesn't feel like she is holding down fluid
- N14 [history] Still PUing ok
- N15 [history] Last 1 hr ago
- N16 [history] Not sure of colour
- N17 [history] BH normally regular
- N18 [history] 1 x day
- N19 [history] No foreign travel
- N20 [history] Has been taking ORT regularly
- N21 [history] difficulty keeping down
- N22 [history] No rash
- N23 [history] Feels hot but hasn't checked temperature
- N24 [history] LMP 2/52 ago
- N25 [history] No regular SI
- N26 [history] Not using contraception
- N27 [history] Has been at work til today
- N28 [history] Now working from home
- N29 [pmh] Nil
- N30 [pmh] DH: Vitamins
- N31 [social_history] Lives with brother and mother
- N32 [social_history] Non smoker
- N33 [social_history] Drinks 1 pint a week
- N34 [social_history] Works as graphic designer
- N35 [impression] Gastroenteritis ?Viral/?food poisoning
- N36 [plan] As ongoing
- N37 [plan] fever needs stool culture sent to exclude bacterial origin
- N38 [plan] Advised to continue taking small sips ORT constantly
- N39 [plan] Booked for urgent appointment to assess hydration status (safety-net)
- N40 [plan] If feels worse in meantime, abdo pain, unwell to contact us to arrange urgent A&E assessment (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [diagnosis_stated] what: infectious gastroenteritis | quote: "it sounds like it might be some, an infectious gastroenteritis that you've got, which is usually caused by a virus" (said by: doctor)
- E02 [next_step] what: call back if feeling more unwell | quote: "you can call us back in the meantime" (said by: doctor)
- E03 [instruction] what: avoid fruit, vegetables, milk | quote: "Avoid, um, fruit, vegetables, uh, milk, anything like that, which might just make it worse" (said by: doctor)
- E04 [event] what: urinating OK | quote: "Yeah, I've been, I've been, yeah, urinating OK." (said by: patient)
- E05 [medication] name: ibuprofen; status: continue; frequency: when they come | quote: "for my menstrual cramps, when they come, maybe I might take a, a, an ibuprofen just to ease the pain" (said by: patient)
- E06 [event] what: I've had to actually work from home today. I'm working from home today because I can't, I can't be out for work | quote: "I've had to actually work from home today. I'm working from home today because I can't, I can't be out for work." (said by: patient)
- E07 [event] what: normal diet | quote: "I eat well, normally." (said by: patient)
- E08 [event] what: diarrhoea started three days ago | quote: "It was three days ago." (said by: patient)
- E09 [event] what: abdominal pains | quote: "this one is giving me abdominal pains" (said by: patient)
- E10 [event] what: pain comes and goes with urge to go to the loo | quote: "Yes, it does come. When it comes, I feel this strong urge to go to the, to the loo, and then and sort of like comes again, it comes and." (said by: patient)
- E11 [event] what: last passed urine an hour ago | quote: "Um. an hour ago." (said by: patient)
- E12 [event] what: taken ORS three times a day for past two days | quote: "I've taken that, I've taken that, like, um, three times a day for the past two days." (said by: patient)
- E13 [event] what: no rash | quote: "No, no rash, no, nothing that, um." (said by: patient)
- E14 [event] what: stool is very loose, started watery | quote: "It's, it's, it's very loose but it started as being very watery." (said by: patient)
- E15 [event] what: lives with brother and mum | quote: "I live with my brother and my mum." (said by: patient)
- E16 [instruction] what: eat simple food like toast or biscuit | quote: "just have very simple food, if you're gonna have anything, like toast or biscuit or something really light like that" (said by: doctor)
- E17 [event] what: passed urine an hour ago | quote: "you passed urine an hour ago" (said by: doctor)
- E18 [procedure_planned] what: clinic appointment to check hydration and send stool sample; when_text: as soon as possible | quote: "we should see you so that we can check your hydration and, um, get that sample sent off as soon as possible" (said by: doctor)
- E19 [instruction] what: continue rehydration salts in very small amounts | quote: "you need to carry on with your rehydration salts, and just have very small amounts" (said by: doctor)
- E20 [instruction] what: Just tiny sips constantly, to so that your stomach doesn't get overfilled and, and you vomit, so just tiny, tiny sips but just keep going with it | quote: "Just tiny sips constantly, to so that your stomach doesn't get overfilled and, and you vomit, so just tiny, tiny sips but just keep going with it" (said by: doctor)
- E21 [event] what: running a serious temperature | quote: "I've been running a serious temperature. I'm literally boiling." (said by: patient)
- E22 [attending] who: Doctor Smith | quote: "it's Doctor Smith from Babylon." (said by: doctor)
- E23 [event] what: job is graphics designer | quote: "A graphics designer." (said by: patient)
- E24 [event] what: throwing up everything, cannot keep anything down | quote: "I've been throwing up. I can't keep to, uh, I can't seem to be able to keep anything in me. Not even water, not even my tea, not even any liquid stuff. I've just been throwing up everything." (said by: patient)
- E25 [event] what: it's kind of like towards my navel area, like I can't touch my navel area. It's just so sore. And it gets, yeah, it's almost like the center of my navel | quote: "it's kind of like towards my navel area, like I can't touch my navel area. It's just so sore. And it gets, yeah, it's almost like the center of my navel." (said by: patient)
- E26 [medication] name: vitamin D; status: continue; frequency: every day | quote: "I take my, my vitamins, vitamin D, every day" (said by: patient)
- E27 [event] what: No, but then, um, my, um my brother, um, has actually been having similar symptoms, um, for the past, um, few days as well, and he does say like everyone in school's got this so, I, I don't know, that might, that might be something | quote: "No, but then, um, my, um my brother, um, has actually been having similar symptoms, um, for the past, um, few days as well, and he does say like everyone in school's got this so, I, I don't know, that might, that might be something." (said by: patient)
- E28 [event] what: bowels normally fine, daily morning bowel movement | quote: "I would normally go to the toilet every day. You know, in the morning, just once, yeah, and that's fine." (said by: patient)
- E29 [event] what: serious diarrhoea | quote: "I've been having this serious diarrhoea and this really, Giving me trouble." (said by: patient)
- E30 [warning_signs] what: feeling more unwell | quote: "if, in the meantime, you're feeling more unwell, then we would get you seen urgently in A and E" (said by: doctor)
- E31 [event] what: does not smoke, drinks a pint from time to time | quote: "I don't smoke, but, you know, I have a pint from time to time." (said by: patient)
- E32 [event] what: went to toilet at least four times today | quote: "Today alone, I've been at least four time." (said by: patient)
- E33 [event] what: last sick about two hours ago after breakfast | quote: "I was sick just after trying, uh, trying to have breakfast this morning, so maybe about two hours ago." (said by: patient)
- E34 [event] what: vomiting everything taken | quote: "I've been vomiting literally everything I take" (said by: patient)

## day1_consultation12

Note facts:

- N01 [history] 3/7 hx ago developed vomiting
- N02 [history] Has now developed diarrhea - 5-6x/day
- N03 [history] Watery/loose stools
- N04 [history] No blood in stools
- N05 [history] No abdo pain
- N06 [history] Reduced oral intake
- N07 [history] Not drinking sufficient fluids
- N08 [history] Feels dehydrated
- N09 [history] Appetite reduced
- N10 [history] No fever/temp
- N11 [history] but feels warm
- N12 [history] Feels weak
- N13 [history] No headaches/muscle pain
- N14 [history] Unaware of triggers
- N15 [history] No unwell contacts
- N16 [pmh] asthma
- N17 [medications] salbutamol PRN
- N18 [allergies] NKDA
- N19 [family_history] father - HTN
- N20 [family_history] died of bowel Ca
- N21 [family_history] mother - diabetes Type 2
- N22 [social_history] lives alone
- N23 [social_history] software engineer
- N24 [social_history] Nil smoking
- N25 [social_history] social EtOH
- N26 [impression] gastroenteritis
- N27 [plan] Supportive mx - rest
- N28 [plan] fluids
- N29 [plan] OTC diarolyte
- N30 [plan] Regular paracetamol
- N31 [plan] Review in 3-5d INB, or earlier if worsening sx (diarrhea, vomiting, abdo pain, reduced oral intake) (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: software engineer | quote: "I'm a software engineer" (said by: patient)
- E02 [event] what: feels very weak | quote: "I feel very weak though." (said by: patient)
- E03 [event] what: I haven't been able to work in the past few days | quote: "I haven't been able to work in the past few days" (said by: patient)
- E04 [instruction] what: get Dioralyte from pharmacy | quote: "you can get things from the pharmacy, which is called Dioralyte" (said by: doctor)
- E05 [event] what: no blood in stools | quote: "No, not that I could see." (said by: patient)
- E06 [event] what: feels very dehydrated | quote: "I feel very dehydrated." (said by: patient)
- E07 [event] what: watery loose stools | quote: "it's definitely, definitely watery, uh, loose stools, yeah." (said by: patient)
- E08 [diagnosis_stated] what: gastroenteritis | quote: "I think you're probably suffering from what we call gastroenteritis" (said by: doctor)
- E09 [event] what: symptoms started at home while working on computer, felt nausea, vomited, then diarrhoea | quote: "I was at home I was working, on my computer and. Yeah, just felt, like some nausea and I had to, to vomit, and then I had some diarrhoea, straight after that." (said by: patient)
- E10 [medication] name: Paracetamol; status: new | quote: "you can take some Paracetamol if you're feeling feverish and weak" (said by: doctor)
- E11 [instruction] what: continue taking time off work for next day or two | quote: "I would probably advise you to continue taking time off work for next day or two, until you get better." (said by: doctor)
- E12 [instruction] what: drink plenty of fluid | quote: "drink plenty of fluid" (said by: patient)
- E13 [event] what: these last three days I've been feeling, really unwell, so I couldn't work | quote: "these last three days I've been feeling, really unwell, so I couldn't work" (said by: patient)
- E14 [follow_up] what: come back and see me; when_text: next week | quote: "if you're still not better next week, I want you to come back and see me." (said by: doctor)
- E15 [family] what: father had high blood pressure and died of bowel cancer ten years ago; who: father | quote: "my father has, high uh, well used to have high blood pressure. He actually, so he actually died, of, bowel cancer, like ten years ago" (said by: patient)
- E16 [event] what: going to toilet five to six times a day | quote: "around, five to six times a day" (said by: patient)
- E17 [event] what: vomiting started then went away, now just diarrhoea | quote: "it started with vomiting, so I vomited a couple of times. Uh, but then, that went away, and, uh, yeah it's just diarrhoea now." (said by: patient)
- E18 [instruction] what: drink plenty of fluids | quote: "you can drink plenty of fluids" (said by: doctor)
- E19 [event] what: patient is forty eight years old | quote: "I'm forty eight." (said by: patient)
- E20 [event] what: lives alone | quote: "I live alone" (said by: patient)
- E21 [event] what: patient name is Robert | quote: "my name is Robert." (said by: patient)
- E22 [next_step] what: if it doesn't I'll uh, I'll call, I'll call back | quote: "if it doesn't I'll uh, I'll call, I'll call back." (said by: patient)
- E23 [instruction] what: be diarrhea-free for about twenty four to forty eight hours before returning to work | quote: "normally you have to be diarrhea-free for about twenty four to forty eight hours, before you return back to work." (said by: doctor)
- E24 [event] what: diarrhoea for past three days | quote: "I've been having, uh, diarrhoea, for like, let's say past three days, more or less." (said by: patient)

## day1_consultation01

Note facts:

- N01 [history] 3/7 hx of diarrhea
- N02 [history] mainly watery
- N03 [history] No blood in stool
- N04 [history] Opening bowels x6/day
- N05 [history] Associated LLQ pain - crampy
- N06 [history] intermittent
- N07 [history] nil radiation
- N08 [history] Also vomiting - mainly bilous
- N09 [history] No blood in vomit
- N10 [history] Fever on first day
- N11 [history] nil since
- N12 [history] Has been feeling lethargic and weak since
- N13 [history] Takeaway 4/7 ago - Chinese restaurant
- N14 [history] Wife and children also unwell with vomiting
- N15 [history] but no diarrhea
- N16 [history] No other unwell contacts
- N17 [pmh] Asthma
- N18 [medications] Inhalers
- N19 [social_history] works as an accountant
- N20 [social_history] Lives with wife and children
- N21 [social_history] Affecting his ADLs as has to be near toilet often
- N22 [social_history] Nil smoking/etOH hx
- N23 [impression] gastroenteritis
- N24 [plan] Conservative management - rest
- N25 [plan] push fluids, paracetamol if feverish
- N26 [plan] Recommend OTC diarolyte
- N27 [plan] To review in 3-5d if symptoms not improving (safety-net)
- N28 [plan] To see earlier if feeling more unwell

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: loose stool, diarrhea, a bit of tummy pain mainly on the left-hand side, vomiting and fever and quite weak and lethargic | quote: "for the last three days you've been having loose stool, diarrhea, a bit of tummy pain uh mainly on the left-hand side, um and vomiting and fever and you're quite weak and lethargic" (said by: doctor)
- E02 [event] what: pain feels like a cramp | quote: "it feels, um, like a cramp, like a muscular cramp" (said by: patient)
- E03 [event] what: needs to stay close to toilet | quote: "it's been affecting me I need to stay close to the toilet" (said by: patient)
- E04 [event] what: loose and watery stool, going often | quote: "loose and watery stool, going to the toilet quite often" (said by: patient)
- E05 [event] what: no blood in stool | quote: "No, no blood, yeah, just watery and loose stool" (said by: patient)
- E06 [event] what: ate at a Chinese restaurant with friends | quote: "I ate at a Chinese restaurant with friends" (said by: patient)
- E07 [instruction] what: drinking fluids to stay well hydrated | quote: "making sure you're well hydrated, so drinking fluids" (said by: doctor)
- E08 [instruction] what: take time off work for the next two to three days and rest | quote: "I would say the next two, two to three days as the infection clears from your system to take some time off and rest" (said by: doctor)
- E09 [follow_up] what: come and see you again if symptoms haven't got better in three to four days; when_text: in three to four days | quote: "I'll admit if your symptoms haven't got better, you know, in in three to four days, I'd like to come and see you again" (said by: doctor)
- E10 [diagnosis_stated] what: gastroenteritis | quote: "it seems like you may have something, uh, called gastroenteritis, which essentially just a tummy bug or infection of your uh of your tummy" (said by: doctor)
- E11 [event] what: feels weak and shaky | quote: "i feel a bit uh weak and shaky" (said by: patient)
- E12 [medication] name: Dioralyte; status: new | quote: "there are things like Dioralyte you can get from the pharmacy, which uh it's um it helps helps replenish your minerals and vitamins" (said by: doctor)
- E13 [event] what: affecting day-to-day activities | quote: "it's been affecting my day-to-day activities" (said by: patient)
- E14 [event] what: I haven't had a fever, um, at the moment, but I did notice um a temperature when the symptoms started | quote: "I haven't had a fever, um, at the moment, but I did notice um a temperature when the symptoms started" (said by: patient)
- E15 [event] what: had takeaway about four days ago | quote: "I had takeaway about four days ago" (said by: patient)
- E16 [event] what: vomit normal, no blood | quote: "just normal vomit, yeah. No no blood, no" (said by: patient)
- E17 [event] what: going to toilet six or seven times a day | quote: "probably like six or seven times a day" (said by: patient)
- E18 [event] what: one child was vomiting, no diarrhea | quote: "one, um, child was vomiting, but they haven't got diarrhea" (said by: patient)
- E19 [event] what: temperature noticed three or four days ago | quote: "around about three or four days ago" (said by: patient)
- E20 [event] what: diarrhea for three days | quote: "I've just had some diarrhea for the last three days" (said by: patient)
- E21 [medication] name: paracetamol; status: new; dose: two tablets; frequency: up to four times a day for the first few days | quote: "taking some paracetamol, uh, two tablets up to four times a day for the first few days can also help" (said by: doctor)
- E22 [event] what: pain in lower abdomen on one side | quote: "in my lower abdomen, so, uh, like, um...yeah, just to one side" (said by: patient)
- E23 [event] what: had a Chinese takeaway as little as three days ago | quote: "you mentioned you had this Chinese takeaway as little as three days ago" (said by: doctor)
- E24 [event] what: pain comes and goes | quote: "it comes and goes" (said by: patient)
- E25 [event] what: I had a loss of appetite, um, so I haven't been eating as much, but I've been able to hold down fluids | quote: "I had a loss of appetite, um, so I haven't been eating as much, but I've been able to hold down fluids." (said by: patient)
- E26 [medication] name: inhaler; status: continue | quote: "I use an inhaler" (said by: patient)
- E27 [event] what: pain on left side | quote: "On the left side" (said by: patient)
- E28 [event] what: pain in lower stomach | quote: "some pain in my, like, lower stomach" (said by: patient)
- E29 [event] what: vomited at start, now stopped | quote: "I vomited at the start of the symptoms but now um I've stopped vomiting" (said by: patient)
- E30 [event] what: symptoms started three days ago | quote: "these started three days ago the symptoms" (said by: doctor)
- E31 [event] what: going to work, difficult | quote: "I've been going to work. Yeah. Yeah, it's been quite difficult." (said by: patient)
- E32 [event] what: pain does not move to back | quote: "no, just maybe my stomach" (said by: patient)
- E33 [event] what: frequent toilet use during past three days | quote: "I need to stay close to the toilet 'cause I go quite frequently during the these past three days" (said by: patient)

## day1_consultation08

Note facts:

- N01 [history] 3/7 hx of dry itchy skin
- N02 [history] mainly on the hands and palms
- N03 [history] No spread elsewhere
- N04 [history] No bleeding/discharge
- N05 [history] No cracked skin
- N06 [history] Sx started after going swimming
- N07 [history] No prev skin problems
- N08 [history] No fevers
- N09 [history] No vomiting
- N10 [history] Appetite maintained
- N11 [history] nil nausea/vomiting
- N12 [history] Nil bowel/urinary sx
- N13 [pmh] Lactose intolerance
- N14 [medications] microgynon
- N15 [allergies] NKDA
- N16 [family_history] Father - asthma
- N17 [family_history] Mother - hayfever
- N18 [social_history] lives alone
- N19 [social_history] nil smoker/etOH/recreational drugs
- N20 [social_history] works as primary school teacher
- N21 [social_history] Recent stress ++
- N22 [impression] dermatitis
- N23 [plan] Steroid cream BD
- N24 [plan] Emollients - regular use QDS
- N25 [plan] Antihistamines
- N26 [plan] Review sx in 1/52, or earlier if worsening sx/any concerns (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: no spots, no fever, not sweating | quote: "I don't have any spots, and no fever , and I'm not sweating either" (said by: patient)
- E02 [event] what: skin symptoms started a few days ago | quote: "I think it started a few days ago" (said by: patient)
- E03 [event] what: working long hours | quote: "I've been working really long hours" (said by: patient)
- E04 [event] what: works as a teacher | quote: "I work as a teacher" (said by: patient)
- E05 [family] what: asthma; who: dad | quote: "my dad has asthma" (said by: patient)
- E06 [event] what: coconut butter hasn't helped with itch | quote: "the coconut butter hasn't helped, with the itch" (said by: doctor)
- E07 [event] what: symptoms started after swimming | quote: "did your symptoms start after you went swimming?" (said by: doctor)
- E08 [event] what: rash on arms started after swimming a few days ago | quote: "your arms which started, perhaps after swimming a few days ago" (said by: doctor)
- E09 [event] what: kids have been annoying | quote: "I think the kids have been really annoying these days" (said by: patient)
- E10 [event] what: lives alone | quote: "it's just me" (said by: patient)
- E11 [event] what: feeling tired | quote: "I think I have been, quite tired" (said by: patient)
- E12 [family] what: hayfever; who: mum | quote: "my mum has hayfever" (said by: patient)
- E13 [event] what: lactose intolerant | quote: "I might be lactose intolerant" (said by: patient)
- E14 [medication] name: antihistamines (Piriton, Loratadine); status: new | quote: "you can also try antihistamines, so you can get things over the counter, Piriton, Loratadine" (said by: doctor)
- E15 [event] what: no fevers, no bleeding or discharge from skin | quote: "no fevers, no bleeding or discharge from skin" (said by: doctor)
- E16 [event] what: stress at work | quote: "I've been really stressed at work for the past few days" (said by: patient)
- E17 [event] what: dry itchy skin | quote: "I've realised that I've got, really dry itchy skin" (said by: patient)
- E18 [diagnosis_stated] what: dermatitis | quote: "I wonder whether you may have something called dermatitis" (said by: doctor)
- E19 [next_step] what: if it's still not getting better, come back and see me next week | quote: "if it's still not getting better, come back and see me next week" (said by: doctor)
- E20 [event] what: eating and drinking normally | quote: "I've been drinking, and eating as normal" (said by: patient)
- E21 [event] what: using coconut butter | quote: "I'm using coconut butter for the past few days" (said by: patient)
- E22 [medication] name: steroid creams; status: new | quote: "we have steroid creams I can give you" (said by: doctor)
- E23 [event] what: works as a primary school teacher | quote: "you work as a primary school teacher" (said by: doctor)
- E24 [event] what: does not smoke | quote: "no, I don't smoke" (said by: patient)
- E25 [instruction] what: apply emollients to skin throughout the day for the next few days | quote: "that's something you just need to kind of paste on, uh, on to your skin, uh, , throughout the day for the next few days" (said by: doctor)
- E26 [event] what: went swimming a few days ago | quote: "I went swimming a few days ago" (said by: patient)
- E27 [medication] name: emollients; status: new | quote: "something called emollients, which can help with the dry, dry skin" (said by: doctor)
- E28 [event] what: appetite and bowels fine | quote: "Your appetite's fine is it? OK. And your bowels, are your bowels working OK?" (said by: doctor)
- E29 [event] what: dry itchy skin on arms and hands | quote: "All over my arms, um, and my hands mainly" (said by: patient)
- E30 [event] what: dry itchy rash on hands | quote: "you've got a dry itchy rash on your, mainly your hands" (said by: doctor)
- E31 [instruction] what: Paracetamol on this occasion, wouldn't be helpful | quote: "Paracetamol on this occasion, wouldn't be helpful" (said by: doctor)
- E32 [event] what: skin is red | quote: "my skin's quite red" (said by: patient)
- E33 [follow_up] what: return for another look at symptoms; when_text: next week | quote: "if it's still not getting better, come back and see me next week" (said by: doctor)

## day5_consultation10

Note facts:

- N01 [history] Headache
- N02 [history] 3/7 hx headache
- N03 [history] Starts on waking up
- N04 [history] Over right eye
- N05 [history] Seeing lights in front of eyes
- N06 [history] Can be worse when stands up not when bends over/cough/sneeze
- N07 [history] Vision not disturbed
- N08 [history] No nausea/vomiting
- N09 [history] No altered taste/smell
- N10 [history] Worse in the light
- N11 [history] No rash
- N12 [history] No fever
- N13 [history] No coryzal symptoms
- N14 [history] Not woken up in the night
- N15 [history] No tingling/numbness/weakness
- N16 [history] Well before this episode
- N17 [history] Has been lacking in energy but no wt loss
- N18 [history] Severity 5-8/10
- N19 [history] Taking ibuprofen
- N20 [history] eases slightly but not resolving
- N21 [history] Has had some generalised headaches before but not bad and associated symptoms/altered vision
- N22 [pmh] Nil
- N23 [medications] Mercilon
- N24 [medications] BP last checked 1 yr ago was normal
- N25 [medications] FMHx: Mum has migraine
- N26 [social_history] Non smoker
- N27 [social_history] No illicit drugs
- N28 [social_history] 3 beers/week
- N29 [social_history] Works from home
- N30 [impression] Likely migraine but as ongoing and persistent needs neurological examination to exclude other pathology
- N31 [impression] Advised regular paracetamol and naproxen with food (will prescribe)
- N32 [impression] If gets worse in meantime contact us straightaway or go to A&E is severe/unrelenting (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [medication] name: the pill; status: continue | quote: "just the pill" (said by: patient)
- E02 [event] what: blood pressure checked in pharmacy when got the pill, was normal | quote: "I had it checked in the pharmacy when I got the pill, and they say it was normal." (said by: patient)
- E03 [family] what: mother has migraines; who: mother | quote: "my mum, suffers from, like she has migraines" (said by: patient)
- E04 [event] what: altered light in front of eyes | quote: "you'd had some altered light in front of your eyes as well" (said by: doctor)
- E05 [event] what: stabbing pain when standing up quickly or throwing head, feeling of something moving inside | quote: "Sometimes when I stand up, quickly I get a bit of a, stabbing pain. Um, or if I throw my head like, it I kind of feel like something is moving inside." (said by: patient)
- E06 [next_step] what: book appointment with support line for full examination | quote: "book a, , appointment with us, with the support line, for us to do a full examination" (said by: doctor)
- E07 [event] what: headache is OK at bedtime and not waking at night | quote: "when you go to bed your headache's, OK, and not waking you up in the night-time" (said by: doctor)
- E08 [next_step] what: call for further advice if headache worsens | quote: "you can call us for further advice on that" (said by: doctor)
- E09 [diagnosis_stated] what: possibly a migraine type headache | quote: "it could possibly be a migraine type headache" (said by: doctor)
- E10 [family] what: mother has bad migraines with vomiting; who: mother | quote: "she has quite bad migraines, she's like, has the vomiting and everything" (said by: patient)
- E11 [instruction] what: take the prescribed medication with food | quote: "take it with food" (said by: doctor)
- E12 [event] what: headache ongoing for three days | quote: "the fact it's still ongoing for three days" (said by: doctor)
- E13 [event] what: works from home | quote: "I work from home" (said by: patient)
- E14 [event] what: headache started suddenly three days ago | quote: "I woke up one morning with a headache, and that was three days ago" (said by: patient)
- E15 [event] what: First day I worked from home and then, um, the second I just took the whole day off. And, today I just tried to work from home the first half of the day but, I, I just stopped in the morning 'cause, I couldn't focus | quote: "First day I worked from home and then, um, the second I just took the whole day off. And, today I just tried to work from home the first half of the day but, I, I just stopped in the morning 'cause, I couldn't focus." (said by: patient)
- E16 [event] what: blood pressure checked when got the pill | quote: "I had it checked in the pharmacy when I got the pill, and they say it was normal." (said by: patient)
- E17 [event] what: previous headache lasting two days that went away with Ibuprofen | quote: "I recently had a, a one for like two days, um, but it just went away with Ibuprofen" (said by: patient)
- E18 [event] what: current headache does not go away with Ibuprofen, only gets a little better | quote: "Doesn't really go away with Ibuprofen either, I try that, but it just. It gets a little bit better but like, doesn't go away." (said by: patient)
- E19 [event] what: pain is all over but stronger over right eye | quote: "it's kind of all over but, I feel like over my right eye, it's um bit, stronger." (said by: patient)
- E20 [event] what: had a pain when younger with no cause found, which went away | quote: "I think I only had a, a pain, um, when I was younger but, no causes found and that went away" (said by: patient)
- E21 [event] what: constant headache making daily activities difficult | quote: "I'm just having these headaches. so I'm find it quite difficult to go through my daily activities" (said by: patient)
- E22 [event] what: shooting light in vision | quote: "I get this, shooting light sometimes" (said by: patient)
- E23 [event] what: lives alone | quote: "just by myself" (said by: patient)
- E24 [event] what: first time having such a bad headache | quote: "it's obviously the first time you've had such a bad headache" (said by: doctor)
- E25 [event] what: blinding headache for a few days | quote: "I've been having this, blinding headache for a few days." (said by: patient)
- E26 [next_step] what: book an appointment with the support team for a full examination | quote: "if you book an appointment with the support team, then we can do a full examination then" (said by: doctor)
- E27 [warning_signs] what: go to A and E if headache becomes unbearable, worse, or changing | quote: "if in the meantime before your appointment your, headache is getting unbearable, getting worse or changing. Then , um, if it's that bad, then you should go to A and E and have an examination" (said by: doctor)
- E28 [event] what: blood pressure checked a year ago | quote: "a year ago" (said by: patient)
- E29 [event] what: no high temperature | quote: "you haven't had a high temperature" (said by: doctor)
- E30 [event] what: wakes up with headache in the morning | quote: "I can wake up with it in the morning" (said by: patient)
- E31 [event] what: sensitivity to light | quote: "lights definitely make me more sensitive" (said by: patient)

## day5_consultation08

Note facts:

- N01 [history] Wheeze
- N02 [history] 2-3 hx wheeze
- N03 [history] No fever
- N04 [history] has checked temp - 37
- N05 [history] Cold symptoms
- N06 [history] Not coughing up sputum
- N07 [history] no haemoptysis/CP
- N08 [history] Not night time waking
- N09 [history] Not exercising at the moment
- N10 [history] Sometimes can't complete sentences but no SOB at rest
- N11 [history] no problems walking upstairs
- N12 [history] More wheezy walking to work
- N13 [history] Doesn't have peak flow meter at home
- N14 [history] Has missed a few days of work
- N15 [history] Hx asthma as a child
- N16 [history] took inhalers ?
- N17 [history] what
- N18 [history] Had hospital admissions and missed school
- N19 [history] No ITU
- N20 [history] Stopped medication 3-4 years ago but sometimes takes salbutamol still every few weeks
- N21 [history] Needs salbutamol when exercises
- N22 [history] PMH Asthma
- N23 [history] Hayfever
- N24 [history] DH Salbutamol NKDA
- N25 [social_history] Non smoker
- N26 [social_history] 1U alcohol every 2-3 days
- N27 [social_history] Lives with partner
- N28 [social_history] Works as engineer
- N29 [impression] Exacerbation asthma
- N30 [plan] Continue to monitor temperature and speak to us if spiking temperatures
- N31 [plan] Collect prescription of peak flow meter and spacer
- N32 [plan] Pharmacist can advise on usage
- N33 [plan] Record PEFR twice daily
- N34 [plan] first on waking and at night
- N35 [plan] Increase salbutamol with spacer to 2-4 puffs 4hrly and arrange a review with us next week
- N36 [plan] May need to add in another inhaler
- N37 [plan] If wheeze not settling/getting worse in meantime if feels unwell for urgent appointment (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [diagnosis_stated] what: asthma in childhood | quote: "Uh, yes, I had asthma." (said by: patient)
- E02 [event] what: fever | quote: "I have fever ." (said by: patient)
- E03 [medication] name: salbutamol; status: continue | quote: "I took salbutamol? Salbutamol? Yeah." (said by: patient)
- E04 [medication] name: antihistamine; status: new; frequency: regular | quote: "the other thing to do would be to take a regular antihistamine" (said by: doctor)
- E05 [diagnosis_stated] what: hay fever and eczema | quote: "I also had, uh, hay fever and eczema , sorry." (said by: patient)
- E06 [instruction] what: prescribe a peak flow meter and a spacer | quote: "I can prescribe you a peak flow meter so we can check your breathing level and a spacer to use your inhaler a bit more efficiently" (said by: doctor)
- E07 [event] what: cough and fever | quote: "I have cough and cough a lot, and I have a fever." (said by: patient)
- E08 [event] what: lives with partner | quote: "I live with my partner." (said by: patient)
- E09 [diagnosis_stated] what: flare up of asthma | quote: "it sounds like you've had a flare up of your asthma." (said by: doctor)
- E10 [event] what: no chest pain | quote: "No chest pain, no." (said by: patient)
- E11 [event] what: No, just daytime working, yeah | quote: "No, just daytime working, yeah." (said by: patient)
- E12 [event] what: drinks wine every two or three days | quote: "Every two or three days? Depends, yeah." (said by: patient)
- E13 [instruction] what: increase inhaler to two to four puffs every four hours | quote: "if you increase it so you're taking it two to four puffs, like, every four hours?" (said by: doctor)
- E14 [event] what: fever | quote: "I checked, I have fever ." (said by: patient)
- E15 [event] what: childhood asthma was quite bad | quote: "Uh, it's quite bad." (said by: patient)
- E16 [instruction] what: record peak flow value first thing when waking up | quote: "if you can record a value first thing when you wake up" (said by: doctor)
- E17 [event] what: fever | quote: "I have fever ." (said by: patient)
- E18 [warning_signs] what: high temperature or worsening wheezing | quote: "if you get a high temperature or your wheezing is getting worse, you need to call us back straightaway" (said by: doctor)
- E19 [event] what: missed school due to asthma | quote: "Uh, yeah, occasionally." (said by: patient)
- E20 [event] what: not woken at night | quote: "No, just daytime working, yeah." (said by: patient)
- E21 [event] what: symptoms duration of two to three days | quote: "two, three days. Yeah, quite recently." (said by: patient)
- E22 [event] what: feeling well | quote: "I feel well." (said by: patient)
- E23 [medication] name: asthma inhaler; status: continue | quote: "Yeah, I take the asthma inhaler." (said by: patient)
- E24 [event] what: wheezing and shortness of breath | quote: "recently I'm wheezy. Uh, I have feel like kind of short of breath." (said by: patient)
- E25 [instruction] what: take inhaler more regularly | quote: "what I would suggest is you take it more regularly than you are doing at the moment." (said by: doctor)
- E26 [event] what: No, I can't | quote: "No, I can't." (said by: patient)
- E27 [event] what: hay fever | quote: "I have, uh, hay fever as well." (said by: patient)
- E28 [event] what: I also used to walk to work but recently I can't because it's, I, I feel like very short of breath and sometimes I feel like I can't even finish sentence is quite difficult to, to complete the, the the talking sometimes, yeah | quote: "I also used to walk to work but recently I can't because it's, I, I feel like very short of breath and sometimes I feel like I can't even finish sentence is quite difficult to, to complete the, the the talking sometimes, yeah." (said by: patient)
- E29 [event] what: no blood in cough | quote: "No, I don't think so." (said by: patient)
- E30 [event] what: drinks wine | quote: "one glass of wine." (said by: patient)
- E31 [instruction] what: record peak flow value in the evening over the next week | quote: "And in the evening over the next week" (said by: doctor)

## day4_consultation06

Note facts:

- N01 [history] Name and DOB confirmed
- N02 [history] presenting with headache - significant
- N03 [history] Sx
- N04 [history] started this morning
- N05 [history] Associated symptoms - dizzy / blurry vision - sudden onset headache - severity score - 6/10
- N06 [history] New headache
- N07 [history] Headache over left side of head
- N08 [history] Vision blurry - funny lines
- N09 [history] Has tried paracetamol 3 hours ago- no improvement
- N10 [history] Still having visual problems - some improvement
- N11 [history] Looking at screens making sx
- N12 [history] Worse
- N13 [history] When moving sx
- N14 [history] Worse
- N15 [history] Has felt nauseous - and vomited x2
- N16 [history] No neurological symptoms
- N17 [history] Unlikely to be pregnant
- N18 [history] Worried re: brain cancer or a stroke - wondering if needs to go to a&e (safety-net)
- N19 [pmh] renal stones
- N20 [medications] nil regular
- N21 [allergies] NKDA
- N22 [family_history] mother - migraines
- N23 [family_history] Hypothyroidism
- N24 [family_history] Video assessment - appeared well - in a brightly lit environment - does not appear photophobic
- N25 [plan] ibuprofen + sugary drink + anti sickness to try until appointment
- N26 [plan] Likely migraine however need to consider more serious differentials
- N27 [plan] For review face to face as 1st onset of headache - to be seen today at earliest - earliest appointment available - will need neurological assessment - also to assess for neck stiffness and fever and rash

Candidate facts (extracted, accepted by the grounding check):

- E01 [family] what: mother has migraines; who: mother | quote: "my mother has migraines" (said by: patient)
- E02 [event] what: dizziness | quote: "you feeling dizzy as well" (said by: doctor)
- E03 [event] what: Like this, I, yeah, like this, no, definitely. It's something new | quote: "Like this, I, yeah, like this, no, definitely. It's something new." (said by: patient)
- E04 [event] what: kidney stone pain rated ten | quote: "I had the kidney stone, so let's say that that's ten" (said by: patient)
- E05 [medication] name: ibuprofen; status: new | quote: "if you take some medications, maybe something like ibuprofen?" (said by: doctor)
- E06 [event] what: I tried Paracetemol, but uh, didn't work | quote: "I tried Paracetemol, but uh, didn't work" (said by: patient)
- E07 [next_step] what: if that doesn't work, we would want to see you, um, as soon as possible, to do like a full neurological exam | quote: "if that doesn't work, we would want to see you, um, as soon as possible, to do like a full neurological exam" (said by: doctor)
- E08 [event] what: headache came suddenly | quote: "it came like, kind of suddenly" (said by: patient)
- E09 [next_step] what: assessment | quote: "we can see you today at some point" (said by: doctor)
- E10 [warning_signs] what: strong headache | quote: "really, really strong headache" (said by: patient)
- E11 [family] what: hypothyroidism in family | quote: "I have hypothyroidism in the family" (said by: patient)
- E12 [event] what: pain rated six out of ten | quote: "I have now, , maybe five, well, six, six probably" (said by: patient)
- E13 [warning_signs] what: zigzag lines in vision | quote: "some zigzag lines" (said by: patient)
- E14 [medication] name: no regular medications; status: continue | quote: "do you take any regular medications? Patient: Uh, no." (said by: doctor+patient)
- E15 [event] what: headache started four hours ago | quote: "the headache started like four year, four hours ago" (said by: patient)
- E16 [event] what: blurry vision, funny lines, nausea, vomiting twice | quote: "you've noticed that your vision is blurry, there's funny lines, you feel a bit nauseous, you vomited twice" (said by: doctor)
- E17 [event] what: vomited twice | quote: "I vomit twice" (said by: patient)
- E18 [instruction] what: drink sugary and carbonated drinks like Coke | quote: "you also to drink, uh, sugary and carbonated drinks, something like Coke" (said by: doctor)
- E19 [medication] name: specific migraine relief medication; status: new | quote: "a good sort of cocktail to start them, then we can go up the treatment ladder, you can get specific migraine relief medication" (said by: doctor)
- E20 [event] what: patient is a little hypochondriac | quote: "I'm a little bit hypochondriac" (said by: patient)
- E21 [family] what: mother has hypothyroidism; who: mother | quote: "She also has Hypothyroidism" (said by: patient)
- E22 [warning_signs] what: worse with movement | quote: "if I leave bed, I start to feel like, even worse if I move" (said by: patient)
- E23 [instruction] what: take ibuprofen with an anti-sickness | quote: "it can be ibuprofen with an anti-sickness" (said by: doctor)
- E24 [event] what: pain behind the eye | quote: "Is it behind the eye? Is that where the pain is?" (said by: doctor)
- E25 [event] what: still feels nausea | quote: "I still feel nausea" (said by: patient)
- E26 [event] what: about to vomit soon | quote: "I'm about to vomit, very soon, I think" (said by: patient)
- E27 [event] what: patient worries about stroke | quote: "or maybe a stroke" (said by: patient)
- E28 [instruction] what: if you do take these medications and, you know, by the time your appointment time comes in and you feel much better in yourself, you can cancel it, um, you can give us a call and cancel it | quote: "if you do take these medications and, you know, by the time your appointment time comes in and you feel much better in yourself, you can cancel it, um, you can give us a call and cancel it" (said by: doctor)
- E29 [event] what: headache developed about four hours ago this morning | quote: "This morning, uh, you woke up and then later on in the, in the morning, about four hours ago, you've developed a headache" (said by: doctor)
- E30 [instruction] what: let us know about further problems | quote: "any, any further problems between now and your appointment, please do let us know" (said by: doctor)
- E31 [event] what: maybe three hours ago, because I couldn't stand it | quote: "maybe three hours ago, because I couldn't stand it" (said by: patient)
- E32 [warning_signs] what: blurred vision | quote: "my vision is a little bit blurred" (said by: patient)
- E33 [event] what: headache on one side | quote: "it's on one side of the head" (said by: doctor)
- E34 [event] what: headache on left side of head | quote: "on the left side of the head" (said by: doctor)
- E35 [event] what: headache started | quote: "it started in the morning" (said by: patient)
- E36 [warning_signs] what: headache on left side | quote: "It's in uh, one side, uh, the left side, only" (said by: patient)
- E37 [attending] who: Doctor Kumar | quote: "my name is Doctor Kumar" (said by: doctor)
- E38 [warning_signs] what: dizziness | quote: "I feel like um, uh, dizzy" (said by: patient)
- E39 [event] what: vomited when headache started | quote: "as soon as the, the headache started, I also vomited" (said by: patient)
- E40 [family] what: mother has migraine; who: mother | quote: "my mother has it" (said by: patient)
- E41 [diagnosis_stated] what: migraine | quote: "it sounds like what you're suffering from is what's known as a migraine" (said by: doctor)
- E42 [event] what: no weakness in arms or legs | quote: "have you noticed any weakness in your arms or legs, anything like that? Patient: No, no , no, no." (said by: doctor+patient)
- E43 [event] what: patient worries about brain tumour | quote: "I feel that this can be some kind of brain tumour, tumour or something" (said by: patient)
- E44 [event] what: when you're walking, you're able to walk fine in a straight line or is your, your uh walk, are you walking a bit funny? Patient: Uh, not really | quote: "when you're walking, you're able to walk fine in a straight line or is your, your uh walk, are you walking a bit funny? Patient: Uh, not really." (said by: doctor+patient)
- E45 [event] what: walking fine | quote: "you're walking fine" (said by: doctor)
- E46 [event] what: patient doubts pregnancy | quote: "Is there any chance you could be pregnant? Patient: Uh, I really doubt it." (said by: doctor+patient)
- E47 [medication] name: medications; status: continue | quote: "whatever medications they take the migraine doesn't improve" (said by: doctor)

## day2_consultation03

Note facts:

- N01 [history] Hx: 1 week history of left side difficulty hearing and facial numbness
- N02 [history] No dysphagia
- N03 [history] dysarthria
- N04 [history] no unilateral weakness/numbness in the rest of the body
- N05 [history] no visual disturbances
- N06 [history] No ear pain
- N07 [history] ear discharge
- N08 [history] fever
- N09 [history] itchiness or cotton bud use
- N10 [history] Slight tinnitus at times in this period- not continuous
- N11 [history] Numbness and difficulty hearing present now
- N12 [pmh] labyrinthitis
- N13 [pmh] heart burn
- N14 [pmh] nasal polyps
- N15 [medications] Rennies PRN OTC
- N16 [medications] nasal spray PRN (pt not sure of name)
- N17 [allergies] latex allergy
- N18 [allergies] No FH of note
- N19 [allergies] Ex: no facial asymmetry
- N20 [allergies] looks well
- N21 [allergies] normal facial expressions and movements
- N22 [impression] Bell's Palsy- need to rule out any other focal neurology
- N23 [plan] for face to face review today for neurological examination and ear examination
- N24 [plan] Pt to ring support line for GP F2f slot
- N25 [plan] Pt understands and is happy with plan

Candidate facts (extracted, accepted by the grounding check):

- E01 [medication] name: Rennie's; status: continue; frequency: if I need to | quote: "I take a Rennie's if I need to" (said by: patient)
- E02 [event] what: occupation is jockey | quote: "I'm a, I'm a jockey" (said by: patient)
- E03 [event] what: no ear discharge | quote: "No, nothing, nothing coming out." (said by: patient)
- E04 [event] what: no weakness or numbness in rest of body | quote: "No, no, no, no, nothing like that" (said by: patient)
- E05 [medication] name: Rennies; status: continue; frequency: sometimes | quote: "sometimes take like Rennies, but I just get that from the chemist" (said by: patient)
- E06 [event] what: reduced training due to symptoms | quote: "I've just had to do far less training" (said by: patient)
- E07 [instruction] what: book a face-to-face appointment in one of our clinics | quote: "I'm gonna send a message to our admin team, I'll ask them, to book you in for a face-to-face appointment in one of our clinics" (said by: doctor)
- E08 [instruction] what: ring the support team number | quote: "you can ring the , the support team number, I'll leave that number in your notes" (said by: doctor)
- E09 [medication] name: nose spray; status: continue; frequency: if my nose polyps are playing up | quote: "if my nose polyps are playing up I've got a spray" (said by: patient)
- E10 [event] what: hearing loss on left side | quote: "Just one side, just on my left side, I've noticed that the hearing's kind of gone down a bit" (said by: patient)
- E11 [family] what: Neurofibromatosis; who: brother | quote: "My brother had, Neurofibromatosis, I think it is" (said by: patient)
- E12 [event] what: no vision problems | quote: "No, that's all good." (said by: patient)
- E13 [event] what: occasional ringing and dizziness | quote: "the ringing um, occasionally and, when I get that I can sometimes feel a bit dizzy" (said by: patient)
- E14 [event] what: symptoms impacting work | quote: "impacting work, um, a little bit now" (said by: patient)
- E15 [procedure_planned] what: GP assessment | quote: "I would like a GP to assess you" (said by: doctor)
- E16 [diagnosis_stated] what: nasal polyps | quote: "I've got kind of, been told I have polyps in my nose in the past" (said by: patient)
- E17 [event] what: numbness on left side around ear and jawline | quote: "it's the left side, it's kind of like around my left ear, and kind of, along here. So like, my jawline's just all feeling a bit numb round here" (said by: patient)
- E18 [diagnosis_stated] what: I had something called, can't quite remember but, labyrinthitis | quote: "I had something called, can't quite remember but, labyrinthitis" (said by: patient)
- E19 [event] what: duration of symptoms | quote: "it's been a few weeks now. Um, been about three weeks or something" (said by: patient)
- E20 [instruction] what: ring them after five minutes | quote: "you can ring them after five minutes" (said by: doctor)
- E21 [event] what: it kind of, kind of, there quite often, so, all the time. So yeah, right now it feels very, doesn't feel like when I touch this side of my face | quote: "it kind of, kind of, there quite often, so, all the time. So yeah, right now it feels very, doesn't feel like when I touch this side of my face" (said by: patient)
- E22 [procedure_planned] what: assessment in a clinic; when: 2026-01-05; when_text: today | quote: "I would like you to be assessed in a clinic today" (said by: doctor)
- E23 [event] what: lack of hearing and numbness | quote: "the main thing is really the, lack of hearing, and the numbness" (said by: patient)
- E24 [event] what: no fever | quote: "No, nothing like that." (said by: patient)
- E25 [location] hospital: Central London | quote: "within Central London" (said by: doctor)
- E26 [event] what: no ear pain | quote: "Uh, no, don't think so." (said by: patient)
- E27 [event] what: ringing in ear | quote: "occasionally noticed a, ringing in my ear" (said by: patient)
- E28 [event] what: no use of cotton buds | quote: "Pardon? Ohh, no, no, no, don't use cottons buds, like that." (said by: patient)
- E29 [procedure_planned] what: neurological examination | quote: "we can do a, a what we call a, a neurological examination" (said by: doctor)
- E30 [instruction] what: make sure the appointment gets done today | quote: "please make sure the appointment gets done today" (said by: doctor)
- E31 [event] what: just been having some, um, problems with my hearing, I can't really hear very well | quote: "just been having some, um, problems with my hearing, I can't really hear very well" (said by: patient)
- E32 [event] what: face numbness | quote: "my face has been feeling a bit numb recently" (said by: patient)
- E33 [event] what: no just Latex | quote: "no just Latex" (said by: patient)
- E34 [diagnosis_stated] what: Bell's Palsy | quote: "what you're, what you're describing might be something called Bell's Palsy" (said by: doctor)
- E35 [event] what: lives with partner | quote: "I, uh, live with my partner" (said by: patient)
- E36 [event] what: no pets | quote: "No, no pets" (said by: patient)
- E37 [event] what: ringing and dizziness symptoms | quote: "because of all the kind of, these symptoms I've been getting, especially sometimes when I get a ringing, I can feel a bit dizzy" (said by: patient)
- E38 [procedure_planned] what: look inside the ear | quote: "Have a look, have a look inside the ear" (said by: doctor)

## day2_consultation08

Note facts:

- N01 [history] Hx of fever for a week with associated sweatiness
- N02 [history] body/muscle aches
- N03 [history] nausea
- N04 [history] fatigue
- N05 [history] night sweats
- N06 [history] hot/cold episodes
- N07 [history] Drinking less cf normal
- N08 [history] Taking ibuprofen and paracetamol otc- not helping
- N09 [history] helps with temp slightly
- N10 [history] No cough
- N11 [history] sore throat
- N12 [history] runny nose
- N13 [history] ear pain
- N14 [history] No diarrhea
- N15 [history] no neck stiffness
- N16 [history] no headache (no more than usual- normal headache on top of head through looking at screen)
- N17 [history] No rash
- N18 [history] no joint swelling (ongoing back pain)
- N19 [history] no dysuria or frequency
- N20 [history] Recent foreign travel- returned from Vietnam
- N21 [history] took malaria prevention daily- cant remember medication
- N22 [history] present there for a few weeks
- N23 [history] rural and urban tourism
- N24 [history] trekking and cycling
- N25 [pmh] nil of note
- N26 [pmh] back pain- under physiotherapy
- N27 [pmh] working diagnosis ?
- N28 [pmh] muscular/ posture
- N29 [family_history] father has MI at age 68
- N30 [medications] on cerazette
- N31 [medications] Nil allergies
- N32 [medications] hayfever
- N33 [social_history] works as a nurse
- N34 [social_history] UTD with hep B etc
- N35 [social_history] non smoker
- N36 [social_history] moderate alcohol intake
- N37 [social_history] moderate physical exercise
- N38 [impression] PUO
- N39 [impression] need to exclude malaria
- N40 [plan] for f2f appointment with GP today
- N41 [plan] Thereafter
- N42 [plan] for blood tests including crp
- N43 [plan] esr
- N44 [plan] thick and thin blood films (possibly routine, possibly via a/e- depending on second GP's assessment)

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: toured several parts of Vietnam including countryside and cities | quote: "we toured to, uh, several different parts of the country, and uh, the countryside and some cities as well." (said by: patient)
- E02 [event] what: main symptoms: sweating, nausea, aching muscles | quote: "mainly just the sweating, really, and the and the nausea, uh, that's overtaking all all day and, uh, the aching muscles all over" (said by: patient)
- E03 [location] hospital: local A and E | quote: "you could actually just attend a local A and E" (said by: doctor)
- E04 [diagnosis_stated] what: migraines and headaches | quote: "sometimes I struggle with migraines, and headaches." (said by: patient)
- E05 [event] what: tired and unwell | quote: "just generally quite tired and unwell" (said by: patient)
- E06 [procedure_planned] what: thick and thin blood films to check for malaria | quote: "I'll be asking for something called thick and thin blood films, to check for malaria" (said by: doctor)
- E07 [event] what: temperature reduced slightly but symptoms persist | quote: "Perhaps slightly, yes, but I'm still experiencing these symptoms" (said by: patient)
- E08 [event] what: fever for the past week | quote: "I've been struggling with fever for the past week" (said by: patient)
- E09 [event] what: aching all over, muscle aches | quote: "I'm aching all over really, my muscles are really aching" (said by: patient)
- E10 [event] what: no unusual headache, no migraines | quote: "Not more than usual, no. Just like the, general headaches but not, just from staring at the screen. No migraines, or anything." (said by: patient)
- E11 [event] what: interchangeable hot and cold periods | quote: "having periods of when you're feeling hot, and also periods when you're feeling cold as well" (said by: doctor)
- E12 [diagnosis_stated] what: headaches related to screen use and weather changes | quote: "It's something that I've struggled with through, years really, just related to a screen use, or, uum, like changes in weather patterns." (said by: patient)
- E13 [diagnosis_stated] what: back pain | quote: "I often have problems with back pain" (said by: patient)
- E14 [procedure_planned] what: blood tests | quote: "you're probably gonna need some blood tests" (said by: doctor)
- E15 [event] what: drinking small amount | quote: "I have been drinking but it's been quite a small amount" (said by: patient)
- E16 [instruction] what: sort this out sooner rather than later | quote: "we need to sort this out sooner rather than later" (said by: doctor)
- E17 [next_step] what: patient to ring number in consultation notes after a few minutes to be slotted in | quote: "if you can ring the number that I leave in your consultation notes, after a few minutes, and then they'll slot you in" (said by: doctor)
- E18 [event] what: exposure to rural areas | quote: "you've had exposure to rural areas" (said by: doctor)
- E19 [event] what: returned from Vietnam | quote: "I came back four weeks ago now." (said by: patient)
- E20 [event] what: nausea | quote: "I'm feeling quite nauseous" (said by: patient)
- E21 [event] what: no ear pain | quote: "no, my ears are fine, actually" (said by: patient)
- E22 [event] what: trekking and cycling through farmland | quote: "We were sort of trekking and, um, cycling, uh, through the farmland" (said by: patient)
- E23 [event] what: medication not really helping | quote: "it's not really helping, just been taking the recommended dose every day of those" (said by: patient)
- E24 [instruction] what: I don't think you can go into work, uh, until we've sorted this out | quote: "I don't think you can go into work, uh, until we've sorted this out" (said by: doctor)
- E25 [next_step] what: admin team will book patient in | quote: "I will send a message to one of our admin team members asking them to book you in" (said by: doctor)
- E26 [procedure_planned] what: inflammatory markers | quote: "And inflammatory markers and things like those" (said by: doctor)
- E27 [event] what: travel to Vietnam | quote: "I went to Vietnam. Uh, I came back four weeks ago now." (said by: patient)
- E28 [event] what: no neck stiffness | quote: "Um, no. My neck's, my neck's been fine" (said by: patient)
- E29 [event] what: no cough, cold, or sore throat | quote: "not those sort of symptoms, really" (said by: patient)
- E30 [event] what: night sweating and feeling cold | quote: "I'm sweating during the the the night, I'm quite cold" (said by: patient)
- E31 [event] what: I've not been able to eat very much | quote: "I've not been able to eat very much" (said by: patient)
- E32 [diagnosis_stated] what: headache centralized over the head | quote: "it's quite centralized over, over the head." (said by: patient)
- E33 [event] what: no diarrhoea | quote: "And not, not really no, not that I can find" (said by: patient)
- E34 [event] what: back pain for quite a while | quote: "I've been struggling with back pain for quite a while" (said by: patient)

## day3_consultation06

Note facts:

- N01 [history] History : breathing difficulty for past 20 minutes after being bitten by wasp
- N02 [history] There is some blotching rash seen
- N03 [history] tingling feeling around your lips
- N04 [history] no closing of the throat feeling
- N05 [history] no previous similar history
- N06 [history] Past medical history
- N07 [history] Eczema
- N08 [history] Allergic to penicillin
- N09 [plan] advised to start on antihistamines straight away
- N10 [plan] It might be just urticaria ( Hives)Call the ambulance to r/o possible anaphylactic reaction

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: stung by wasp | quote: "I was stung by wasp" (said by: patient)
- E02 [event] what: shallow breath | quote: "I'm having quite shallow breath" (said by: patient)
- E03 [instruction] what: go to hospital | quote: "take yourself to hospital" (said by: doctor)
- E04 [attending] who: Doctor Jacob | quote: "I'm Doctor Jacob" (said by: doctor)
- E05 [diagnosis_stated] what: risk of anaphylactic reaction | quote: "in case you develop an anaphylactic reaction" (said by: doctor)
- E06 [event] what: gardening | quote: "I was gardening" (said by: patient)
- E07 [event] what: tingling in lips | quote: "I can definitely feel something in the lips" (said by: patient)
- E08 [medication] name: antihistamine; status: new | quote: "I'll ask her to give you the, um, antihistamine" (said by: doctor)
- E09 [event] what: rash/blotching on body | quote: "there's a bit of blotching" (said by: patient)
- E10 [diagnosis_stated] what: needs immediate medical attention | quote: "you do need to have medical attention straight away" (said by: doctor)
- E11 [event] what: chest tightness | quote: "a bit of tightness" (said by: patient)
- E12 [instruction] what: call the ambulance | quote: "call the ambulance because, you know, so that you will be sorted out quickly" (said by: doctor)
- E13 [location] hospital: sixty two Lewin Road Streatham SW sixteen six JT | quote: "sixty two Lewin Road Streatham SW sixteen six JT" (said by: patient)
- E14 [warning_signs] what: breathing difficulties | quote: "because you're complaining of breathing difficulties, it is quite important that you go to hospital straight away" (said by: doctor)
- E15 [instruction] what: take antihistamine while waiting for ambulance | quote: "I'll ask her to give you the, um, antihistamine, in the meantime while the ambulance is coming." (said by: doctor)
- E16 [event] what: patient started speaking | quote: "I have been" (said by: patient)

## day4_consultation08

Note facts:

- N01 [history] Confirmed name
- N02 [history] DOB confrimed
- N03 [history] 8 weeks
- N04 [history] Not able to get up in the morning
- N05 [history] No energy during the day
- N06 [history] Not eating
- N07 [history] Difficulty sleeping
- N08 [history] Mood is Distracted difficulty focusing
- N09 [history] Lower mood recently
- N10 [history] Decreased sex drive
- N11 [history] No suicidal ideation
- N12 [history] New job - 2 months ago
- N13 [ice] would like to get back to how he was
- N14 [ice] Married
- N15 [pmh] Hypothyroidism
- N16 [medications] Thyroxine
- N17 [allergies] NKDA
- N18 [social_history] Fhx
- N19 [social_history] Father - suicide
- N20 [social_history] Mother well
- N21 [social_history] No brothers or sisters
- N22 [impression] depression
- N23 [impression] Hypothyroidism
- N24 [impression] (Low T3/4)
- N25 [impression] Plan
- N26 [impression] TSH
- N27 [impression] FBC
- N28 [impression] Examination
- N29 [impression] GP review

Candidate facts (extracted, accepted by the grounding check):

- E01 [family] what: father committed suicide about fifteen years ago; who: father | quote: "my father has commited suicide, um, about fifteen years ago." (said by: patient)
- E02 [event] what: started a new job recently | quote: "I also started a new job, um, slightly recently" (said by: patient)
- E03 [event] what: sex drive decreased over the past few months | quote: "my sex drive has kind of decreased, um, a bit over the, the past few months" (said by: patient)
- E04 [next_step] what: see patient in person, do an examination, and do blood tests | quote: "I would like to, probably see you in person, and do an examination. And, and also, we would probably like to do some blood tests" (said by: doctor)
- E05 [event] what: symptoms have been going on for about six weeks | quote: "this has been going on perhaps for um, sort of, six weeks or so" (said by: doctor)
- E06 [event] what: feeling unwell with not a lot of energy, difficult waking up in the mornings | quote: "feeling unwell with not a lot of energy, difficult waking up in the mornings" (said by: doctor)
- E07 [event] what: having trouble sleeping at all | quote: "having trouble sleeping at all" (said by: patient)
- E08 [event] what: more fatigue and more shortness of breath over the last few months | quote: "more fatigue, more shortness of breath, um, over the last few months?" (said by: doctor)
- E09 [family] what: Yeah she's fine, um, and no, I'm an only child; who: mother | quote: "Yeah she's fine, um, and no, I'm an only child." (said by: patient)
- E10 [event] what: difficulty focusing | quote: "finding it really hard to, quite, difficult to keep focusing" (said by: patient)
- E11 [event] what: asked about thoughts of harming self or others | quote: "Have you had any thoughts of harming yourself or harming anyone else?" (said by: doctor)
- E12 [event] what: mood is a bit lower recently | quote: "mood is a bit lower recently" (said by: patient)
- E13 [event] what: shortness of breath when doing sports compared to a couple of months ago | quote: "I find sometimes it's quite difficult to breathe, um. So, I have some kind of like, shortness of breath um, when doing, sports, compared to maybe a couple of months ago." (said by: patient)
- E14 [diagnosis_stated] what: tiredness and other symptoms | quote: "some your tiredness, and your other symptoms" (said by: doctor)
- E15 [attending] who: Joe | quote: "my name's Joe. I'm one of the doctors at Babylon" (said by: doctor)
- E16 [event] what: more short of breath over the last few months | quote: "you've become more short of breath over the last few months." (said by: doctor)
- E17 [event] what: symptoms may have coincided with starting the new job a couple of months ago | quote: "it might of even coincided, coincided with uh, with that, job, a couple of months ago" (said by: patient)
- E18 [event] what: doing most things that were normally easy has become difficult | quote: "doing most things that I would normally find, easy , is become quite difficult" (said by: patient)
- E19 [event] what: symptoms have been going on for about two months | quote: "More like, , two months, I would say, yeah" (said by: patient)
- E20 [event] what: I don't have much energy at all, during the day | quote: "I don't have much energy at all, during the day" (said by: patient)
- E21 [next_step] what: book an appointment with GP in the next few days | quote: "book an appointment in the next few days uh, with your GP" (said by: doctor)
- E22 [event] what: low sex drive | quote: "low sex drive" (said by: doctor)
- E23 [medication] name: Thyroxine; status: continue | quote: "I had a, a, drug history of Thyroxine." (said by: patient)
- E24 [diagnosis_stated] what: low mood | quote: "you have a low mood" (said by: doctor)
- E25 [diagnosis_stated] what: history of hypothyroidism | quote: "I have a, a history of, hypothyroidism" (said by: patient)
- E26 [event] what: I don't really feel like um, like, getting up in the morning's really difficult | quote: "I don't really feel like um, like, getting up in the morning's really difficult" (said by: patient)

## day4_consultation10

Note facts:

- N01 [history] Name confirmed
- N02 [history] 2 days
- N03 [history] Feeling sick
- N04 [history] No vomiting
- N05 [history] Ache - Lower tummy
- N06 [history] Hot and sweaty
- N07 [history] Drinks lots of water - Polyuria
- N08 [history] No urgency
- N09 [history] No dysuria
- N10 [history] Constipated 1 weeks
- N11 [history] Pain described as - Lower abdo
- N12 [history] aching
- N13 [history] Constant
- N14 [history] Sexually active - Implant
- N15 [history] Spotting
- N16 [history] LMP 3.5 weeks ago
- N17 [history] Regulalr boyfriend
- N18 [pmh] Amox
- N19 [pmh] Nil Meds
- N20 [social_history] Non smoker
- N21 [family_history] Brther Type 1 dm
- N22 [impression] Simple constipation
- N23 [impression] PID
- N24 [impression] STI
- N25 [impression] UTI
- N26 [plan] Needs further examination and Ix
- N27 [plan] Pregnancy test
- N28 [plan] U+E

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: dull ache | quote: "a dull ache" (said by: patient)
- E02 [event] what: last menstrual period around three and a bit weeks ago | quote: "around a month ago, yeah, three and a, three and a bit weeks ago" (said by: patient)
- E03 [event] what: no urgency to urinate | quote: "No, there's no urgency" (said by: patient)
- E04 [event] what: I was a little bit like um, uh, I don't know constipated I guess, uh. About a week ago, but I'm OK now | quote: "I was a little bit like um, uh, I don't know constipated I guess, uh. About a week ago, but I'm OK now" (said by: patient)
- E05 [family] what: type one diabetic; who: brother | quote: "my brother is a type one diabetic." (said by: patient)
- E06 [event] what: ache in lower tummy | quote: "it's more of an ache. So, like an ache in my lower tummy" (said by: patient)
- E07 [procedure_planned] what: examination and tests | quote: "I would quite like to, uh, see you to do some further, to do an examination, and to do some, some tests as well." (said by: doctor)
- E08 [event] what: symptoms for a couple of days | quote: "it's only been for a couple of days" (said by: patient)
- E09 [event] what: pain below belly button | quote: "it's like below my belly button" (said by: patient)
- E10 [procedure_planned] what: rule out pregnancy | quote: "we need to definitely rule out pregnancy, with you." (said by: doctor)
- E11 [event] what: constipation, but had a bowel movement yesterday | quote: "you mentioned that you were bunged up, but you did go yesterday" (said by: doctor)
- E12 [event] what: going to the toilet more | quote: "I'm going to the toilet, more" (said by: patient)
- E13 [event] what: pee slightly pink or red | quote: "your pee is slightly red? Or slightly pink?" (said by: doctor)
- E14 [event] what: using arm implants for contraception | quote: "I've got the arm, the implants" (said by: patient)
- E15 [event] what: peeing frequently but normal | quote: "peeing quite frequently, but it's all seeming normal" (said by: patient)
- E16 [event] what: constipation about a week ago, cleared up now | quote: "about a week ago, but I'm OK, OK now, the last few days" (said by: patient)
- E17 [event] what: feeling hot, sweaty, unwell for three days | quote: "feeling, hot, sweaty, unwell, for three days" (said by: doctor)
- E18 [event] what: I did notice a bit of, um. I don't know it's like , not necessarily like spotting, but in like, in my, my pee is like a little, I suppose | quote: "I did notice a bit of, um. I don't know it's like , not necessarily like spotting, but in like, in my, my pee is like a little, I suppose" (said by: patient)
- E19 [next_step] what: See the patient again to take things further. | quote: "we can , um, sort of see you again, to take this a little bit further." (said by: doctor)
- E20 [instruction] what: The doctor would like to see the patient for more examination and investigations. | quote: "I'd really like to see you, uh, for some more, uh, examination, investigations." (said by: doctor)
- E21 [event] what: no pain or urgency | quote: "no pain or urgency" (said by: patient)
- E22 [event] what: feeling sick, nausea, with an ache in lower tummy | quote: "feeling sick, nausea, um, with an ache in your lower tummy" (said by: doctor)
- E23 [event] what: feeling bunged up | quote: "you've been feeling bunged up" (said by: doctor)
- E24 [event] what: symptoms for the last couple of days | quote: "the last couple of days" (said by: patient)
- E25 [event] what: nausea, hot, sweaty feeling | quote: "I'm nauseous, hot, sweaty, feeling" (said by: patient)
- E26 [event] what: constant pain over last couple of days | quote: "feeling pretty constant, over the last couple of day" (said by: patient)
- E27 [event] what: one regular sexual partner | quote: "one sexual partner? Um, a regular, regular boyfriend or?" (said by: doctor)
- E28 [event] what: feeling sick | quote: "the main symptom is feeling sick, uh with this" (said by: doctor)
- E29 [event] what: pain in tummy | quote: "pain in your tummy" (said by: doctor)
- E30 [event] what: tummy pain for last two days | quote: "it's only been for the last two days" (said by: patient)
- E31 [event] what: expecting period soon | quote: "but you're expecting your period soon?" (said by: doctor)
- E32 [event] what: tummy pain came on gradually | quote: "it's come on gradually" (said by: doctor)
- E33 [event] what: going to the loo more often than usual | quote: "I'm going to the loo a little bit more often than usual" (said by: patient)
- E34 [event] what: The consultation is running out of time. | quote: "we're just sort of, timing out, running out of time a little bit" (said by: doctor)
- E35 [event] what: feeling hot and sweaty | quote: "you're feeling hot, hot and, sweaty" (said by: doctor)
- E36 [next_step] what: see a GP face-to-face today | quote: "would you be happy to actually see a GP face-to-face, um, soon? Today, ideally." (said by: doctor)
- E37 [event] what: nauseous, no vomiting yet | quote: "no just nauseous, no vomiting yet" (said by: patient)
- E38 [instruction] what: If you feel worse, get light-headed, or develop concerning symptoms, take them seriously and see somebody more urgently. | quote: "if in the meantime um, between now and, and me, sort or a GP seeing you, you feel worse in any way, you get light-headed. Um, you, uh, uh you have, you develop any symptoms which are concerning to you. Um, then I think you should take them quite seriously, and, and see somebody more urgently if possible." (said by: doctor)
- E39 [event] what: feeling sick in lower tummy | quote: "for the last couple of days, um, I've been, feeling, um, really sick in my, lower tummy" (said by: patient)
- E40 [event] what: drinking lots of water, going to the toilet more often | quote: "I drink lots of water, but it does feel like more often" (said by: patient)
- E41 [event] what: spotting in last couple of days | quote: "the last kind of week or so, yeah, the last couple of days really" (said by: patient)
- E42 [event] what: had a bit of a temperature, feeling hot and sweaty | quote: "I've had a bit of a temperature, so feeling quite like hot and sweaty" (said by: patient)
- E43 [event] what: nausea | quote: "it does make me feel nauseous" (said by: patient)
- E44 [event] what: no foul smelling urine | quote: "no foul smelling urine" (said by: doctor)

## day5_consultation11

Note facts:

- N01 [history] R knee pain
- N02 [history] 2/52 R knee pain
- N03 [history] Training for marathon
- N04 [history] Currently up to 7-8 miles few times a week
- N05 [history] Gym few x week
- N06 [history] Had to stop running at 20 min point due to pain this week
- N07 [history] Pain in front of knee and right side
- N08 [history] No specific area tenderness
- N09 [history] Has noticed puffiness of knee after exercise
- N10 [history] used ice and this settled completely
- N11 [history] No giving way/locking
- N12 [history] No problems going up/downstairs or on normal walking
- N13 [history] FROM
- N14 [history] Generally feels pain is getting worse
- N15 [history] Has had previous ice hockey injury and bruising afterwards
- N16 [history] No other jt pains
- N17 [history] no general unwell/fever
- N18 [history] Has had tingling R side forefoot which settled down
- N19 [history] Slight ankle swelling
- N20 [history] indentation socks
- N21 [history] No change in temp/colour
- N22 [history] No problems walking hard floors/pain in sole
- N23 [pmh] LASIK
- N24 [pmh] kidney stones
- N25 [medications] Vit D
- N26 [medications] melatonin
- N27 [medications] ibuprofen
- N28 [medications] Xanax sometimes
- N29 [social_history] Has occ joint
- N30 [plan] Advised replace ibuprofen with naproxen which I will prescribe
- N31 [plan] Continue using ice as much as possible and reduce exercise
- N32 [plan] Do not continue to run with pain
- N33 [plan] No hx GI sx/asthma
- N34 [plan] Advise I will refer for physio for assessment and ongoing Rx
- N35 [plan] If persistent swelling/heat/redness/locking to see Dr asap (safety-net)

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: I can't run very far, um, any more without just feeling, pain in my knees | quote: "I can't run very far, um, any more without just feeling, pain in my knees" (said by: patient)
- E02 [event] what: right knee hurts | quote: "it's actually my right knee that hurts." (said by: patient)
- E03 [medication] name: Ibuprofen; status: continue | quote: "It's fine to take the Ibuprofen" (said by: doctor)
- E04 [event] what: knee not swollen and not hurting currently | quote: "right now it's not swollen, and right now it doesn't hurt" (said by: patient)
- E05 [event] what: training for a marathon in June | quote: "I'm currently training for a marathon, um, that's gonna happen in, June" (said by: patient)
- E06 [medication] name: vitamin D; status: continue | quote: "I take vitamin D." (said by: patient)
- E07 [event] what: noticed indentation from socks | quote: "I noticed it because of my socks, I'll just kind of, notice this indentation." (said by: patient)
- E08 [event] what: tingling in toes | quote: "sometimes I also get this weird tingling in my toes" (said by: patient)
- E09 [medication] name: melatonin; status: continue | quote: "I take melatonin." (said by: patient)
- E10 [event] what: goes to gym a few times a week | quote: "I go to the gym like few times a week" (said by: patient)
- E11 [warning_signs] what: if in the meantime you develop like persistant swelling, heat, redness, um, of the knee, or high temperature, feel unwell, or it completely locks up and you can't bend and stretch it | quote: "if in the meantime you develop like persistant swelling, heat, redness, um, of the knee, or high temperature, feel unwell, or it completely locks up and you can't bend and stretch it" (said by: doctor)
- E12 [event] what: GP called ER to tell them not to give Morphine | quote: "if my GP didn't call them, tell them, that you know, they don't need to give me Morphine." (said by: patient)
- E13 [instruction] what: carry on with ice therapy | quote: "definitely carrying on with the ice therapy that you've been using" (said by: doctor)
- E14 [instruction] what: if it's painful enough that you're, having to stop running, then it's not a good idea, to do that | quote: "if it's painful enough that you're, having to stop running, then it's not a good idea, to do that" (said by: doctor)
- E15 [instruction] what: take the stronger anti-inflammatory with food | quote: "make sure that with food" (said by: doctor)
- E16 [event] what: tingling in right toes after a run | quote: "there was this tingling in my toes, like uh, um, after the run. There was tingling in my toes like on my, you know my right toes" (said by: patient)
- E17 [location] hospital: sixty Sloane Avenue, London | quote: "sixty Sloane Avenue, London" (said by: patient)
- E18 [event] what: patient thinks there is some fluid in knee | quote: "I have, probably some fluid. I googled it, and you know it says that sometimes fluid accumulates" (said by: patient)
- E19 [next_step] what: get appointment with physiotherapist for assessment and examination of knee | quote: "getting a appointment with the physiotherapist first, who can do like a long, assessment, and examination of the knee" (said by: doctor)
- E20 [event] what: started training about a month ago | quote: "I started about uh, maybe a month ago" (said by: patient)
- E21 [event] what: pain starts after about twenty minutes of running | quote: "probably starts off like after, uh, maybe, twenty minutes or so" (said by: patient)
- E22 [event] what: clicking in knees when doing abs and moving from flex to straight legs | quote: "when I start doing my abs, that's, you know when I do my abs. It's kind of requiring me to move my you know, um, to kind of go from the flex position on my knees, and straighten my legs, then I feel all this clicking." (said by: patient)
- E23 [medication] name: stronger anti-inflammatory; status: new | quote: "I can prescribe you a slightly stronger, anti-inflammatory that you can take regularly instead of the Ibuprofen, but not with the Ibuprofen" (said by: doctor)
- E24 [event] what: symptoms started about two weeks ago | quote: "it's been about two weeks" (said by: patient)
- E25 [medication] name: Melatonin; status: continue | quote: "I prefer Melatonin, it's just sometimes Melatonin doesn't work." (said by: patient)
- E26 [event] what: fell on ice and had a huge bruise a few months ago | quote: "I had this injury a few months ago. You know I just like, fell on the ice and, and, you know had a, huge bruise" (said by: patient)
- E27 [event] what: pain in middle of knee moving to the right | quote: "I feel it in the middle, but I almost feel like maybe it kind of uh, um, moves to the right, to the right of my knee a little bit." (said by: patient)
- E28 [event] what: no clicking now, but pain occurs in gym and when running | quote: "when I flex and extend my leg, it, there's no clicking but, I'll notice it in the gym and then, you know, when I run it'll start hurting." (said by: patient)
- E29 [attending] who: Doctor Smith | quote: "It's Doctor Smith from Babylon" (said by: doctor)
- E30 [medication] name: ibuprofen; status: continue; frequency: sometimes for cramps | quote: "Sometimes, you know, just for cramps, I'll take, like, uh, um, ibuprofen" (said by: patient)
- E31 [event] what: patient stopped running because it feels worse | quote: "the last time I actually stopped, I mean I ran a little bit longer, but then I stopped, because it was um, I, I feel like it's getting worse." (said by: patient)
- E32 [event] what: knee starts hurting | quote: "it just kinda starts hurting, you know" (said by: patient)
- E33 [next_step] what: send referral to physiotherapist | quote: "we can do a referral before that" (said by: doctor)
- E34 [instruction] what: call back urgently if warning signs develop | quote: "you'd need to see a doctor urgently, so call us back in that, case" (said by: doctor)
- E35 [event] what: legs swell up after standing for a long time | quote: "I have sometimes, you know how sometimes like if you stand for a long time, your feet will kinda, or your legs will swell up." (said by: patient)
- E36 [instruction] what: ease up on running | quote: "try and ease up on the running, if you can" (said by: doctor)
- E37 [event] what: had a bad UTI and was in ER | quote: "once I had this really bad UTI, they thought it was kidney stones, and so they had me actually in ER." (said by: patient)
- E38 [event] what: ran four or five miles and a couple of seven mile runs | quote: "I've done like, you know, four or five miles, and I've just done like a couple of seven, mile runs" (said by: patient)
- E39 [event] what: had Lasik surgery | quote: "I had uh, I had Lasik surgery." (said by: patient)
- E40 [event] what: knee was swollen after first run, ice reduced swelling | quote: "the first time I ran, it was a little bit swollen, but then I just put some like ice on it, and it went away." (said by: patient)

## day4_consultation01

Note facts:

- N01 [history] acute onset left sided chest discomfort / pressure
- N02 [history] feels like someone sitting on his chest 7/10
- N03 [history] radiating to the left shoulder and arm
- N04 [history] 1-2 hours in duration
- N05 [history] acute onset
- N06 [history] 1st presentation started while gardening
- N07 [history] No radiation to the head
- N08 [history] ℅ nausea no vomiting since presentation
- N09 [history] SOBAR
- N10 [history] HPC
- N11 [history] longer term hx of reduced ADLs due to SOBOE
- N12 [history] walking up hills / stairs with no chest discomfort
- N13 [pmh] high cholesterol and high blood pressure
- N14 [medications] allergies aspirin
- N15 [social_history] lives with wife at home
- N16 [social_history] able to walk up stairs until previously
- N17 [impression] MI
- N18 [impression] PE
- N19 [impression] GORD
- N20 [plan] called ambulance ??
- N21 [plan] MI for further investigation and assessment

Candidate facts (extracted, accepted by the grounding check):

- E01 [event] what: relaxing and watching Jeremy Kyle with wife before event | quote: "I was, relaxing. My wife, and, we're watching Jeremy Kyle" (said by: patient)
- E02 [event] what: I try to limit my daily activity to just moving around the house, nothing too strenuous | quote: "I try to limit my daily activity to just moving around the house, nothing too strenuous" (said by: patient)
- E03 [event] what: chest discomfort rated seven out of ten at onset | quote: "Say about, say, seven out of ten" (said by: patient)
- E04 [instruction] what: Don't take any of those medications | quote: "Don't take any of those medications." (said by: doctor)
- E05 [diagnosis_stated] what: high blood pressure, high cholesterol, chest pain, worry about heart | quote: "given that you've got high blood pressure and high cholesterol, and you've got some chest pain. I'm always worried about the heart first" (said by: doctor)
- E06 [event] what: nausea without vomiting | quote: "I've noticed nausea, but no vomiting, yet" (said by: patient)
- E07 [medication] name: no medicine; status: continue | quote: "No, I don't take any medicine." (said by: patient)
- E08 [event] what: difficulty climbing stairs | quote: "I've had, some difficulty climbing the stairs" (said by: patient)
- E09 [family] what: lives at home with wife; who: wife | quote: "do you live at home with your wife at the moment?" (said by: doctor)
- E10 [event] what: paramedics should be with you, very shortly | quote: "the paramedics should be with you, very shortly." (said by: doctor)
- E11 [event] what: chest discomfort feels like someone sitting on chest | quote: "it's like someone's sitting on my chest" (said by: patient)
- E12 [instruction] what: go to hospital as soon as possible | quote: "get you to the hospital as soon as possible" (said by: doctor)
- E13 [event] what: they will give you lots of things to breathe through, and attach things to your arms | quote: "they will give you lots of things to breathe through, and attach things to your arms." (said by: doctor)
- E14 [event] what: digging in the garden | quote: "I was, digging in the garden" (said by: patient)
- E15 [diagnosis_stated] what: high cholesterol and hypertension | quote: "high cholesterol, and, I've had hypertension, hypertension" (said by: patient)
- E16 [event] what: chest discomfort still the same now | quote: "it's still the same" (said by: patient)
- E17 [event] what: pain in left shoulder and arm | quote: "There is some pain in my left shoulder and arm" (said by: patient)
- E18 [instruction] what: stay calm, and have some water if you need to | quote: "I would suggest that you stay calm, and have some water if you need to." (said by: doctor)
- E19 [event] what: chest discomfort feels like pressure | quote: "it feels like it's pressure, discomfort, than more, than a pain" (said by: patient)
- E20 [diagnosis_stated] what: concern it might be something to do with the heart | quote: "my concern is, it might be something to do with your heart" (said by: doctor)
- E21 [attending] who: Doctor Gohill | quote: "Hi, my name is Doctor Gohill" (said by: doctor)
- E22 [instruction] what: stay on the phone | quote: "I think we should stay on the phone" (said by: doctor)
- E23 [event] what: still feeling nauseous at the moment | quote: "I have, yeah. I am, yeah." (said by: patient)
- E24 [event] what: chest discomfort | quote: "I'm experiencing discomfort in my chest." (said by: patient)
- E25 [event] what: chest discomfort located in the middle of the chest | quote: "it's somewhere in the middle of my chest" (said by: patient)
- E26 [event] what: the consultant would normally call me within a couple of minutes | quote: "the consultant would normally call me within a couple of minutes, to let me know how everything's going." (said by: doctor)
- E27 [event] what: problems performing daily activities | quote: "there's some problems just, performing daily activities" (said by: patient)
- E28 [event] what: chest discomfort ongoing for a couple of hours | quote: "it's been ongoing for, a couple of hours now" (said by: patient)
- E29 [instruction] what: call an ambulance | quote: "I think it might be worth, you calling an ambulance" (said by: doctor)
- E30 [event] what: chest discomfort came on suddenly | quote: "it's come on, quite suddenly" (said by: patient)
- E31 [event] what: light-headedness | quote: "I feel slightly, light-headed" (said by: patient)
- E32 [event] what: you'll be seen by a consultant, pretty, pretty much immediately | quote: "you'll be seen by a consultant, pretty, pretty much immediately." (said by: doctor)
- E33 [event] what: shortness of breath | quote: "I've got shortness of breath" (said by: patient)
- E34 [event] what: challenge walking uphill | quote: "if I have to sort of walk uphill, there's that sort of challenge as well" (said by: patient)
- E35 [event] what: normally fit and well apart from the two things told, but problems with daily activities | quote: "Um. Yes, however, there's some problems just, performing daily activities" (said by: patient)
- E36 [event] what: no problems going to the loo | quote: "Uh, no problems going to the loo." (said by: patient)
- E37 [next_step] what: book another appointment, to see you soon | quote: "I'll um, book another appointment, to see you soon." (said by: doctor)
- E38 [event] what: calf pain and leg swellings | quote: "there's often calf pain and, leg swellings" (said by: patient)
- E39 [event] what: ambulance should be there very soon | quote: "The ambulance should be there very soon." (said by: doctor)
