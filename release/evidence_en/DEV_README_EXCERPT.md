Excerpt of the development repository's README.md at sha256 db97e07f2a66ecb928bf93348a268e86d00bb63b6c7c9f1fff0af138bd40a246; cited lines copied verbatim
Line N of this file renders line N of the source; lines that no published citation uses are left blank. Links into local run folders (release/validation_abd/, git-ignored, not published) are kept as plain text; team members' names are replaced by their role.












**Fall model.** The CareRelay fall model v0.1 (`carerelay_fall_gru`) is MediaPipe Pose Landmarker → 12 pose features → a small GRU (4,449 parameters), trained on GMDCSA-24 (train = Subjects 1–2, validation = Subject 3; Subject 4, the test split, was never loaded).
- Preliminary, CPU: LOSO estimate over Subjects 1–3 gives AUC 0.975 ± 0.011 and balanced accuracy 0.903 ± 0.025. The prior-event v1 baseline gets 0.656.
- The recorded `s1_*` runs use Subject 1 clips, which are training clips of this model. They show the wiring, not generalisation.
- A fall result is a prompt for a caregiver to confirm (human in the loop), not an autonomous alarm or a medical decision. The MediaPipe model card says the pose model is not intended for human life-critical decisions.


**AMD.** The Case Agent's language model runs on AMD Token Factory (below). MediaPipe runs on the CPU, also on an AMD droplet: its GPU path needs OpenGL ES, and the MI300X has no graphics engine. The GRU trains in seconds on a CPU; `scripts/amd_bootstrap.sh` can also train it on an MI300X (optional). The real GPU workloads are the LLM (Case Agent / handover drafts) and Whisper ASR.



The Case Agent's language model runs on AMD. The main path is **AMD Token Factory**, the inference platform the event is hosted on (team dashboard: notebooks.amd.com/tokenfactory; API base URL from its user manual: `https://developer.amd.com.cn/radeon/api/v1`): the official event page says "The event is hosted on notebooks.amd.com/tokenfactory. There is no billing or credit card info needed." One command runs the same evaluation as our Kaggle notebook against it, from any machine with Python 3.9+:










- Why the two settings: the user manual says only MiMo-V2.6-Flash accepts strict `json_schema` (so the JSON schema goes in the prompt and every reply is parsed and checked by the same guardrails), and the gateway silently drops request fields it does not know (so no extra body is sent; Gemma does not think by default).
- Data: the service keeps prompts and outputs for about 2 days and its terms say not to send sensitive personal or health data. This evaluation sends only fictional care cases and the public PriMock57 role-play consultations; a real deployment would need a dedicated endpoint under a data-processing agreement.


- Photo of a medication list (the family timeline's photo step), same endpoint and model, 2026-10-15 (`handoff_day1/runs/amd/tf_gemma-4-31b-it_2026-10-15T0949_photo_read/`): Gemma-4-31B-IT read the fictional discharge list word for word from a phone-style photo and from a flat scan (57/57 words, every dose and day count), and the facts read from it found all 5 medicines with the right status (new / continue / stop). In the app the caregiver still checks each line against the photo before anything is added. Kaggle notebook: `handoff_day1/kaggle/carerelay_photo_read_hosted_kaggle.ipynb`.
- "Ask a question" on the family timeline (same endpoint and model): a family member's question, typed or said, is answered with the sentences of the updates that answer it, word for word, and a related leaflet; the model only chooses the sentences (it writes no answer text, so it cannot grant permission, advise or invent a date), and a question the updates do not answer goes on a shared list for the doctor. Kaggle notebook: `handoff_day1/kaggle/carerelay_episode_qa_hosted_kaggle.ipynb` (16 questions at 4 points of the demo story).
