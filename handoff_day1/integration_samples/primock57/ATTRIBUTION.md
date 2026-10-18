# Attribution (CC BY 4.0)

Audio clip `day1_consultation01_seg087_doctor.wav` and the transcript text in `transcript_segments.json` / `asr_sample.json` / `asr_doctor_channel.json` are derived from:

**PriMock57: A Dataset Of Primary Care Mock Consultations**, Babylon Health, https://github.com/babylonhealth/primock57, commit `cd2ac707ad03cb4d2531f4ec6b90c659bf4357c5`, licensed under **CC BY 4.0** (https://creativecommons.org/licenses/by/4.0/). Paper: Korfiatis et al., ACL 2022, arXiv:2204.00333.

**Changes made:**
- one doctor utterance was cut (397.35–406.33 s) from `audio/day1_consultation01_doctor.wav`, with no other processing;
- the TextGrid intervals were converted to JSON;
- a `text_plain` field with the markup removed was added.

The recordings are role-played (simulated) consultations: the participants are actors, not real patients. They are unrelated to the GMDCSA-24 subjects.
