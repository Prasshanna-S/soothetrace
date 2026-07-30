# SootheTrace

SootheTrace is an experimental memory aid for caregivers. It records a short crying episode, looks only at the selected profile's earlier care history after an acoustic match, and surfaces a reminder such as: "What helped before: held baby upright."

It is not a cry translator. It does not determine hunger, pain, illness, colic, safety, or the reason a baby is crying. It is not a medical device, emergency service, or unattended monitor.

## Try the hosted experience

The intended hosted architecture uses one secure same-origin link for both the phone interface and API:

`https://HOSTED_URL/`

`HOSTED_URL` is a deployment placeholder. No public hosted deployment is available yet. A production host must provide HTTPS, authentication, access control, encrypted storage, deletion controls, and a reviewed privacy program before it receives real family audio.

The current prototype can instead run locally for development. The browser and Python server are served together, so a deployed user should not need a separate app download or a manually entered API URL.

## What happens during a session

1. The browser captures complete audio segments.
2. The server validates and converts accepted audio to 16 kHz mono PCM WAV.
3. A local infant-cry presence gate decides whether there is enough infant-cry-like evidence to continue.
4. The selected infant profile is evaluated acoustically. The system can abstain instead of naming a profile.
5. Only after that profile is accepted, the app ranks that profile's earlier incidents and shows a recorded action that previously helped.
6. The caregiver can record what they tried and whether it helped, adding a new memory for future retrieval.

The suggestion is evidence-backed in a narrow sense: it is grounded in a prior recorded incident. It is not evidence that the action will work now.

## Profiles in this prototype

- **Demo Baby** is a controlled presentation profile created by `scripts/prepare_care_demo.py`. It uses demo audio and six clearly synthetic care memories. Its outputs demonstrate the retrieval flow, not real family history or clinical performance.
- **Regular Baby** means an ordinary user-created `infant` profile. It requires independent reference recordings and can remain unresolved when the available evidence is weak.
- **Human Baby** is an informal presentation label for the separate `human_imitation` path. That path uses adult participants imitating cries to exercise open-session behavior. It is not an infant profile, does not power care-memory suggestions, and does not establish infant identification performance.

## Local development setup

The supported local path is macOS or another environment with Python 3.12 and FFmpeg available on `PATH`.

```bash
git clone https://github.com/Prasshanna-S/soothetrace.git
cd soothetrace

uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

Install FFmpeg through your platform package manager. On macOS with Homebrew:

```bash
brew install uv ffmpeg
```

### Build the local MFCC87 baseline

The infant MFCC87 path deliberately refuses raw-vector comparison. It needs a population normalization baseline. The baseline build downloads the public Donate-a-Cry corpus into an ignored directory:

```bash
git clone --depth 1 \
  https://github.com/gveres/donateacry-corpus.git \
  experiments/donateacry-corpus

.venv/bin/python tools/build_baseline.py
```

This corpus groups recordings by an app-install UUID, not a verified infant identity. It is useful for prototype normalization and evaluation, not for a production identity claim.

### Start the local server

```bash
.venv/bin/python -m src.http_api \
  --http \
  --host 127.0.0.1 \
  --port 8000 \
  --data-root data/audio \
  --static-root web \
  --db data/episodes.db
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The `--http` mode is restricted to loopback hosts. A phone needs HTTPS to grant microphone access, and the current local HTTPS setup is for controlled development only. Do not expose it to the internet.

### Prepare the controlled demo

After the baseline exists, this idempotent command creates Demo Baby and Learning Baby, enrolls their controlled references, and installs synthetic Demo Baby memories:

```bash
.venv/bin/python scripts/prepare_care_demo.py
```

The committed baby demo media is under a separate data notice. The release status of all audio fixtures is still being reviewed. Do not add personal recordings to Git.

## Technical design in plain language

SootheTrace separates three questions:

- Is there enough infant-cry-like audio to continue?
- Is the audio consistent enough with the selected profile to search that profile's memory?
- Which earlier incident from that one profile is most relevant now?

Time, tags, notes, actions, and outcomes can rank prior incidents only after an acoustic profile decision. They do not identify a baby and they do not infer a cause.

The current ranker is a fixed heuristic, not a learned model and not a probability: 65% acoustic-pattern similarity, 20% time-of-day similarity, and 15% caregiver-tag overlap. Missing signals are omitted and the remaining weights are renormalized. See [Technical architecture](docs/TECHNICAL-ARCHITECTURE.md).

## Evidence and limits

The project has controlled prototype checks, not population accuracy:

- 40 of 40 checked ESC-50 baby-cry clips were accepted by the current gate and 245 sampled environmental negatives were rejected.
- A two-profile fixed-rig infant trial resolved 13 of 15 queries correctly, with 0 wrong names and 2 abstentions or retries.
- The controlled Demo Baby presentation produced 3 expected distinct history-grounded suggestions from 3 demonstration recordings.
- The separate human-imitation evaluation uses only 10 correlated recordings from 3 consenting adults. It is a small product-path check, not infant evidence and not a biometric performance claim.

Recording channel, room, distance, microphone, playback device, gain, and background sound affect the prototype. It is not validated for unconstrained homes, different devices, or unseen infants. Read [Evaluation](docs/EVALUATION.md) before relying on any measured number.

## Optional speech processing

The care-memory path works without transcription. When configured, speech processing runs on the unseparated recording mixture:

- Online mode can send audio to the configured transcription API.
- `IM_OFFLINE=1` asks for a separately installed local Whisper CLI. Whisper is not installed by `requirements.txt`.
- An optional reasoning-model step extracts only actions and outcomes with literal transcript evidence. The code validates that evidence and falls back to local pattern matching.

Speech processing does not decide infant-cry presence, acoustic profile matching, or a cry cause. If online transcription is enabled, treat it as a cloud data transfer and obtain appropriate consent.

## Run tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Some real-audio checks require locally available fixture packs and may skip in a clean checkout. Browser tests also require Playwright and a browser installation.

## Project documents

- [Technical architecture](docs/TECHNICAL-ARCHITECTURE.md)
- [Evaluation and limitations](docs/EVALUATION.md)
- [Privacy](PRIVACY.md)
- [Security](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Third-party notices](THIRD_PARTY.md)

## Licence and release status

The project source is licensed under the MIT License. Third-party dependencies, model weights, audio, and visual assets have their own terms. See [LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md). Do not assume this repository's source licence grants rights to any fixture or model.
