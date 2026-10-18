# Deploying KindredRelay

This guide is for the person who deploys the family site. You deploy the repository as it is: nothing has to be
changed, integrated or trained.

## What gets deployed

- Image: [`Dockerfile.release`](Dockerfile.release) at the repository root (build context: the repository root, with
  [`Dockerfile.release.dockerignore`](Dockerfile.release.dockerignore)). It is based on `python:3.12-slim`, installs
  `ffmpeg`, the CPU build of PyTorch and the pinned [`deploy/requirements-release.lock`](deploy/requirements-release.lock),
  and bakes the official Whisper `base.en` weights into the image at build time, so the first visitor does not
  trigger a model download.
- Entry point: `CMD python deploy/serve.py` ([`deploy/serve.py`](deploy/serve.py)). It checks the configuration and
  then starts the Streamlit app shell [`handoff_day1/ui/pages/shell/kindred_app.py`](handoff_day1/ui/pages/shell/kindred_app.py):
  the family timeline (default page), the Evaluation & Safety Scorecard and the AMD Runtime page.
- Text and photo inference go to the AMD Token Factory endpoint provided for the AMD Developer Hackathon; speech
  recognition (Whisper `base.en`) runs on the app server's CPU, inside the container.
- Not in the image: the fall-detection model under `handoff_day1/model/` is a separate prototype that
  `Dockerfile.release` does not copy.
- The container runs as the unprivileged user `carerelay` (uid 1000), listens on `PORT` (default 8501) and has a
  health check at `/_stcore/health`.

## Render (default path)

1. Connect Render to the GitHub repository **`HollyHsu0808/KindredRelay`** (branch `main`). Do not connect any other
   repository.
2. Create the service with these settings:

| Setting | Value |
|---|---|
| Service type | Web Service |
| Language / Runtime | Docker |
| Root Directory | leave empty (repository root) |
| Dockerfile Path | `./Dockerfile.release` |
| Docker Build Context | `.` |
| Docker Command | leave empty (the image's `CMD` is used) |
| Health Check Path | `/_stcore/health` |
| Instances | 1 |
| Compute | an always-on CPU service; start from 4 GB RAM (a capacity reserve, not the result of a load test) |
| Persistent disk | mount path `/var/lib/kindredrelay` (see "Saved timelines" below) |
| Auto Deploy | off after the first accepted deploy, so judges always see the accepted version |

3. Set the environment variables below in Render's Environment settings. Put `CARERELAY_LLM_API_KEY` **only in the
   platform's secret store**: never in the repository, an issue, a log or a screenshot.
4. Deploy, then run the acceptance checks at the end of this guide on the HTTPS address Render gives you (a custom
   domain can point at the same service).

## Environment variables

The template with every name is [`deploy/release.env.example`](deploy/release.env.example) (names and defaults only,
no secret values).

| Variable | Value | Notes |
|---|---|---|
| `CARERELAY_LLM_BASE_URL` | `https://developer.amd.com.cn/radeon/api/v1` | AMD Token Factory API base URL |
| `CARERELAY_LLM_MODEL` | `DeepSeek-V4-Flash` | text model (fact reading, answers) |
| `CARERELAY_PHOTO_MODEL` | `Gemma-4-31B-IT` | photo reading model; every line is still checked by a person |
| `CARERELAY_LLM_API_KEY` | the team's Token Factory key | **secret store only** |
| `CARERELAY_LLM_GUIDED_JSON` | `0` | the gateway does not accept guided JSON for these models |
| `CARERELAY_LLM_TIMEOUT_S` | `120` | per-request timeout in seconds |
| `CARERELAY_ASR_MODEL` | `base.en` | the Whisper model baked into the image |
| `CARERELAY_STATE_DIR` | `/var/lib/kindredrelay` | must be the persistent disk's mount path |
| `PORT` | `8501` | Render may set its own; `serve.py` accepts 1-65535 |
| `KINDRED_VERIFIER_MODE` | `off` | keep `off`: the optional verifier did not pass its acceptance |
| `KINDRED_VERIFIER_DIR` | empty | only used when the verifier is enabled |
| `KINDRED_VERIFIER_THREADS` | `2` | only used when the verifier is enabled |

`deploy/serve.py` refuses to start (exit code 2, the missing names printed, never their values) when
`CARERELAY_LLM_BASE_URL`, `CARERELAY_LLM_MODEL`, `CARERELAY_PHOTO_MODEL` or `CARERELAY_LLM_API_KEY` is empty, so a
site without a connected model is never mistaken for the live version. It also stops when the speech dependencies are
missing (build with `Dockerfile.release`) and when `KINDRED_VERIFIER_MODE` is not `off`, `shadow` or `gate`; `gate`
additionally requires a full verifier model with a validation operating point, which the current verifier does not
have. The image sets `CARERELAY_REQUIRE_LIVE=1` and `CARERELAY_REQUIRE_ASR=1`; leave them.

## Saved timelines (persistent disk)

The family timeline stores its timelines in SQLite under `CARERELAY_STATE_DIR` (file `timelines.sqlite3`); see
[`handoff_day1/ui/PERSISTENCE.md`](handoff_day1/ui/PERSISTENCE.md). A container's own filesystem is not durable, so:

- attach a persistent disk mounted at `/var/lib/kindredrelay` and keep `CARERELAY_STATE_DIR=/var/lib/kindredrelay`;
- the directory must be writable by uid 1000 (the image creates it with that owner; check it again on the mounted
  disk with acceptance step 6);
- run a single instance with one SQLite store; several instances or a shared network filesystem have not been tested.

Private and family links carry a random capability that grants read and write access to that timeline. The identity
selector is a display identity, not authentication. Use fictional data only and share complete links only with
trusted people.

## Alternative: your own VM with Docker

From the repository root, write the variables above into a private `release.env` on the host (never commit it), then:

```bash
docker build -f Dockerfile.release -t kindredrelay .
docker volume create kindredrelay-state
docker run -d --name kindredrelay --restart unless-stopped \
  --env-file release.env -v kindredrelay-state:/var/lib/kindredrelay \
  -p 127.0.0.1:8501:8501 kindredrelay
```

Point an HTTPS reverse proxy at `127.0.0.1:8501` (the phone microphone and camera need HTTPS). Keep the previous
image so you can roll back.

## Before deploying: the offline check

Anyone can run the deterministic test suite without credentials, network or models (Python 3.13 with the
dependencies of the release lock):

```bash
python deploy/validate_abd.py --out release/validation_abd/my-run   # the --out folder must not exist yet
```

The verdict is the last line, `RESULT: PASS` or `RESULT: FAIL`, and the exit code. The same commands run in
[`.github/workflows/validate.yml`](.github/workflows/validate.yml). The team's final run passed with 832 unittest
cases in 41 test processes, sources unchanged during the run; its local folder under `release/validation_abd/` is
not published, the frozen summary is ([`validation.json`](handoff_day1/ui/pages/shell/data/validation.json)).

## Acceptance checks on the deployed site

Run these on the public HTTPS address with new fictional inputs (not only the built-in demo):

1. The text model, the photo model and speech recognition are connected: record a short new English message about an
   arrival arrangement, check the transcript and add it.
2. Photograph or pick a new fictional discharge or medication sheet; the text can be edited, and medicine names,
   doses and event dates match the picture before it is added.
3. As Anna, arrange 20 Oct afternoon, change it to 21 Oct morning, then cancel it: only the latest valid arrangement
   remains, and the cancellation is not dated as the cancelled day. Repeat with a date that includes the year.
4. Add a "discharged, at home" message, then a later readmission notice: "Right now" updates and the discharge stays
   in the history; upload time is never shown as event time.
5. As David, in another browser, add a different arrangement: Anna's view receives the update.
6. Keep the complete private or family address, refresh, then restart the service and redeploy: the timeline and the
   committed photos are still there on the same persistent disk. A bare address opens a different private timeline,
   so it does not show that data was lost.
7. Record the public address, the commit deployed and each result with screenshots (no key in any screenshot). If an
   API call fails or a transcript or photo reading is wrong, keep the raw result; an HTTP 200 health check is not a
   content-quality pass.

Not yet verified by the team: the image has not been built on the team's own machine (no Docker there), so the first
Render build is the first build of `Dockerfile.release` with its Python 3.12 pins
([English rendition of the deployment notes, line 25](release/evidence_en/DEPLOY_RC_20261018.md)). The offline suite
ran on Python 3.13.

## Data and service terms

Only fictional stories and the public, role-played PriMock57 consultations are sent to the endpoint. The team-relayed
Token Factory terms say the service is for trial and development, keeps prompts and outputs for about 2 days, and
must not receive sensitive personal, health or financial data
([English rendition, line 30](release/evidence_en/HACKATHON_RULES_BRIEFING.md)). A real deployment would need a
dedicated endpoint under a data-processing agreement.

References: [Render Docker](https://render.com/docs/docker), [Render web services](https://render.com/docs/web-services),
[Render deploys](https://render.com/docs/deploys), [Whisper](https://github.com/openai/whisper).
