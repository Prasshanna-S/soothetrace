# Cry Memory

Cry Memory is a working local hackathon demonstration of interaction memory with two connected
ideas:

1. A live human cry-imitation session builds a score-free participant map from separate short
   recordings.
2. Baby mode uses a confirmed acoustic profile to retrieve only that baby's prior caregiver
   history.

It is a memory aid, not a cry translator. It does not diagnose why someone is crying.

## Clone and run on macOS

The complete phone path documented here has been exercised with a Mac laptop and an iPhone. The
localhost path may also work on Linux, but the certificate and iPhone trust instructions below are
macOS-specific.

Prerequisites:

- macOS with Command Line Tools, which supplies `git`;
- Homebrew;
- internet access for the first dependency install, public corpus clone, browser-test download,
  and acoustic-model checkpoint download;
- an iPhone and Mac on the same local network for the phone path, with client-to-client traffic
  allowed;
- free disk space for the Python environment, public corpus, model checkpoint, and managed audio.

Install the command-line dependencies. The certificate script requires OpenSSL 3 features that
the older system TLS utility may not provide, so its command below puts the Homebrew OpenSSL first
on `PATH`.

```bash
xcode-select -p
brew install uv ffmpeg openssl@3 node
uv --version
ffmpeg -version
ffprobe -version
```

If `xcode-select -p` reports that the tools are missing, run `xcode-select --install`, finish the
macOS installer, and then repeat the checks.

Clone the repository, create the required Python 3.12 environment, install dependencies, clone the
public cry corpus at the path expected by `tools/build_baseline.py`, and build the population
normalization baseline:

```bash
git clone https://github.com/Prasshanna-S/interaction-memory.git
cd interaction-memory
uv venv .venv --python 3.12
. .venv/bin/activate
uv pip install -r requirements.txt
git clone --depth 1 \
  https://github.com/gveres/donateacry-corpus.git \
  experiments/donateacry-corpus
.venv/bin/python tools/build_baseline.py
```

Do not install `librosa`. This project deliberately uses NumPy and SciPy for its local acoustic
path. The baseline command must finish with `population baseline saved`; without that baseline,
infant retrieval correctly refuses to compare raw MFCC87 vectors.

### Laptop-only server

Start the local desktop server:

```bash
.venv/bin/python -m src.http_api \
  --http \
  --host 127.0.0.1 \
  --port 8000 \
  --data-root data/audio \
  --static-root web \
  --db data/episodes.db
```

On first start, the process downloads the human acoustic checkpoint into `models/`. It warms the
required encoders before it starts serving. Wait for a line like this:

```text
Cry Memory ready at http://127.0.0.1:8000 with encoders {'ecapa-cryceleb-v1': True, 'mfcc87-v1': True}
```

Dictionary order is not significant. A `False` value means that encoder did not warm and should
be investigated before the demonstration. Once the ready line appears, open
[http://127.0.0.1:8000](http://127.0.0.1:8000) and confirm the health response:

```bash
curl http://127.0.0.1:8000/api/health
```

### iPhone over trusted local HTTPS

Plain HTTP at a LAN address is not a secure browser context and cannot be relied on for iPhone
microphone capture. Generate a certificate for the Mac's current LAN IP and fully trust its
temporary local certificate authority on the iPhone.

For Wi-Fi on the tested Mac configuration, print the address with:

```bash
ifconfig en0 | awk '/inet / {print $2}'
```

Use the non-loopback address, such as `10.21.6.4`. If `en0` has no address, find the active
interface in System Settings under Network, or inspect the `inet` lines from `ifconfig`. Do not use
`127.0.0.1`. Replace `10.21.6.4` in the commands and URLs below with the current address:

```bash
PATH="$(brew --prefix openssl@3)/bin:$PATH" \
  ./spikes/mobile_capture/make_cert.sh 10.21.6.4

.venv/bin/python spikes/mobile_capture/bootstrap.py \
  --host 0.0.0.0 \
  --port 8080 \
  --cert data/audio/mobile-capture-spike/certs/rootCA.pem
```

With the bootstrap server running, open this exact URL in Safari on the iPhone:

```text
http://10.21.6.4:8080/Interaction-Memory-Spike-CA-corrected.mobileconfig
```

Then:

1. Allow the configuration profile to download.
2. Open Settings. Select **Profile Downloaded**, or go to **General > VPN & Device Management**,
   select **Interaction Memory Local Spike CA**, and install it. Enter the device passcode and
   acknowledge the certificate warning.
3. Go to **General > About > Certificate Trust Settings**.
4. Enable full trust for **Interaction Memory Local Spike CA** and confirm.
5. Stop the bootstrap server with Control-C.

The profile contains only the public root certificate. Do not copy or serve `rootCA.key` or
`server.key`. The generated certificates expire after 30 days. If the Mac's LAN IP changes,
regenerate the certificate for the new IP and repeat installation and trust.

Start the production HTTPS service:

```bash
.venv/bin/python -m src.http_api \
  --host 0.0.0.0 \
  --port 8443 \
  --data-root data/audio \
  --static-root web \
  --db data/episodes.db \
  --cert data/audio/mobile-capture-spike/certs/server.pem \
  --key data/audio/mobile-capture-spike/certs/server.key
```

Wait for the ready line and confirm both encoder values are `True`. Open
`https://10.21.6.4:8443` on the iPhone. The page should load without a certificate warning and the
header should say `Local server ready`. Allow microphone access when prompted. A browser warning
usually means the phone does not fully trust the root, the URL uses a different IP from the
certificate, or a captive or isolated network is interfering.

The [demo operator runbook](docs/DEMO-READY.md) covers rehearsal, presentation order, fallbacks,
and certificate cleanup.

## Fastest human demonstration

1. Choose **Human cry imitation**.
2. Press **New session**.
3. Record with the microphone or select an audio file. A microphone stop or file selection
   submits one independent recording automatically.
4. The first usable recording creates dotted provisional **Person A** with one supporting
   recording.
5. A separately captured recording that passes the acoustic association gate reinforces Person A.
   The bubble becomes solid and established.
6. A safe outlier from a later person shows **Possible new person** without creating a bubble.
   A second separately captured outlier must agree with that pending acoustic pattern before the
   service creates established Person B. The same rule creates Person C and later labels.
7. Every accepted observation remains in the timeline with managed playback.
8. Pass the phone or laptop to the next participant and repeat.

Starting a new live session does not delete earlier sessions, human profiles, baby profiles, or
caregiver history. It creates a new independent session view.

### What the human statuses mean

| Public status | Interface meaning | Profile change |
|---|---|---|
| `provisional_created` | New dotted Person A pattern | Creates provisional Person A with support 1 |
| `participant` | Repeated pattern for a named participant | Reinforces an existing participant or creates a later participant from two agreeing pending recordings |
| `possible_new` | Possible new person; another independent recording is needed | No participant and no reinforcement |
| `leaning` | Direction toward a named participant, not confirmed | No reinforcement |
| `duplicate` | The managed identity-audio digest was already submitted | Timeline event remains, support does not change |
| `invalid` | Empty, unsupported, corrupt, silent, or unusable recording | No participant change |
| `session_completed` | The current session is closed | No new observation |

The public API and interface do not expose a score, margin, similarity, embedding, digest, or
filesystem path. A cosine similarity is not a probability.

## Measured live-session evidence

The current evaluator used the real HTTP routes, upload checks, ffmpeg ingest, managed files,
both human acoustic encoder views, session state machine, and SQLite persistence. Each mode used
a fresh temporary database, managed-audio root, and HTTP server. Truth labels stayed inside the
evaluator and were applied only after each response returned.

The orders are fixed synthetic arrival orders. The manifest has no global capture chronology.

| Metric | One person | Staged three person | Difficult three person |
|---|---:|---:|---:|
| Valid observations | 5/5 | 10/10 | 10/10 |
| Represented people | 1/1 | 3/3 | 3/3 |
| Participants created | 1/1 | 3/3 | 3/3 |
| Correct established assignments | 4/4 | 5/5 | 5/5 |
| Correct directional assignments | 0/0 | 2/2 | 2/2 |
| Direction coverage after a reference existed | 4/4 | 7/9 | 7/9 |
| Correct direction when shown | 4/4 | 7/7 | 7/7 |
| Wrong named directions | 0/4 | 0/7 | 0/7 |
| Known-person splits | 0 | 0 | 0 |
| Duplicate profiles | 0 | 0 | 0 |
| `possible_new` observations | 0 | 2 | 2 |
| Pending patterns at end | 0 | 1 | 1 |
| Reinforcements | 4 | 5 | 5 |
| Maximum observation latency | 3.513 s | 8.032 s | 11.525 s |

The staged and difficult release gates both passed:

```text
represented_people = 3
participants_created = 3
wrong_person = 0
duplicate_profiles = 0
known_person_split = 0
```

Perfect direction coverage is not claimed. In each three-person order, two observations remained
`possible_new`. One hard Second person recording later produced a correct direction toward
Person B but did not reinforce Person B. The pending pattern remained unresolved instead of
creating Person D.

The separate probes also passed:

| Probe | Measured result |
|---|---|
| Exact duplicate | HTTP 201 with `duplicate`; support stayed 1; both timeline rows remained |
| Corrupt bytes with `audio/wav` | HTTP 422 with `invalid`; participant state and two-row timeline stayed unchanged |

Exact per-observation public responses, reason codes, participant snapshots, truth bindings, and
nanosecond latencies are in
[`demo_assets/human_audio/live-session-results.json`](demo_assets/human_audio/live-session-results.json).

### Manual UI observation, not an automated metric

In a separate live UI check, the user reported that the female participant audio and a
phone-replayed version of the user's own cry repeatedly formed distinct session patterns. This
observation has no controlled numerator or denominator and is not included in the automated
metrics.

It demonstrates separation in that tested session under those channel conditions. It does not
demonstrate channel-invariant person recognition or estimate population performance.

### Reproduce the evidence

All ten recordings are already included. No separate audio download is needed.

```bash
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode one-person

.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode staged

.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode difficult

.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode probes
```

`--mode alternating` is an alias for the difficult order. To regenerate one gated JSON bundle:

```bash
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json \
  --mode all \
  --output demo_assets/human_audio/live-session-results.json
```

The evaluator mechanically checks all ten files for presence, supported MIME, positive duration,
byte size, unique SHA-256, and manifest agreement before it starts a session.

## Evidence limits

- The human evidence is 10 correlated recordings from 3 consenting adult cry imitators.
- Every recorded participant agreed on 2026-07-30 to public distribution of these 10 recordings.
- The cohort mixes WAV and M4A containers and capture channels.
- The two evaluation orders are synthetic, not known capture chronology.
- These counts are demonstration evidence, not population accuracy.
- Adult imitation results do not establish infant identity performance.
- A second recording adds supporting evidence. It does not prove identity.
- Measured latency depends on the laptop and concurrent CPU load. The saved maximums are evidence
  from one run, not a service-level guarantee.
- The system reports acoustic association or abstention. It does not infer a medical cause.

## Baby identity and personal care memory

Baby mode keeps acoustic identity separate from care retrieval:

1. Create at least two infant profiles.
2. Enroll independent recordings for each profile.
3. Submit a held-out recording through the same managed ingest path.
4. Compare it only with same-kind infant profiles using the local MFCC87 view and stored
   normalization baseline.
5. If the profile is confirmed, retrieve incidents only from that profile.
6. Rank those prior incidents using within-profile cry similarity plus explicit context.
7. Show a caregiver-recorded prior action and its supporting incidents.
8. Let the caregiver record what happened this time exactly once.

Time, caregiver notes, prior incidents, and context may rank care memories after identity. They
never decide acoustic identity.

Run the real baby identity and care-memory checks:

```bash
.venv/bin/python -m unittest tests.test_product_real_audio_api -v
```

## Architecture

### Human incremental identity

```mermaid
flowchart LR
    P["Phone or laptop browser"] -->|"Raw audio bytes only"| H["Local HTTP ingest"]
    H --> S["Managed source file"]
    H --> C["Managed canonical WAV at 16 kHz mono"]
    C --> N["Fixed RMS normalization"]
    N --> I["Managed identity WAV"]
    I --> E1["CryCeleb ECAPA embedding"]
    I --> E2["MFCC87 embedding with population z-score"]
    E1 --> D["Live session decision service"]
    E2 --> D
    D --> L["SQLite live session, participant, and observation rows"]
    D --> R["SQLite profile and enrollment rows"]
    L --> A["Score-free public session result"]
    A --> U["Latest result, timeline, and participant strip"]
    C --> X["Managed observation playback"]
    X --> U
```

### Baby identity and care memory

```mermaid
flowchart LR
    B["Baby cry capture or upload"] --> H["Local HTTP ingest"]
    H --> I["Managed normalized identity audio"]
    I --> M["MFCC87 with population z-score"]
    M --> P["Same-kind baby profile pool"]
    P --> G{"Confirmed profile?"}
    G -->|"No"| A["Leaning, unresolved, or invalid"]
    G -->|"Yes"| R["Retrieve only that profile's prior incidents"]
    C["Time and explicit caregiver context"] --> R
    R --> D["Grounded prior action with supporting incidents"]
    D --> O["Caregiver records what happened"]
    O --> S["SQLite episode history"]
    S --> R
```

### Phone versus laptop

| Runs in the phone or laptop browser | Runs on the laptop server |
|---|---|
| Microphone capture | Upload bounds and MIME validation |
| Audio file selection | ffmpeg decode to canonical WAV |
| New session, start, stop, and submission controls | Fixed RMS normalization |
| Latest result, timeline, playback, participant strip | MFCC87 and CryCeleb encoding |
| Same-origin HTTP requests | Live-session decisions and SQLite persistence |
| No expected-person label | Baby retrieval, guidance, and outcome storage |

### Source modules

| Module | Responsibility |
|---|---|
| `web/index.html`, `web/app.js`, `web/app.css` | Capture controls, live result, timeline, playback, and responsive participant strip |
| `src/http_api.py` | Same-origin HTTP, ingest routing, public allowlists, and playback |
| `src/audio_ingest.py` | Bounded upload, MIME validation, ffmpeg decode, canonicalization, and fixed normalization |
| `src/encoders.py` | MFCC87 and CryCeleb ECAPA adapters |
| `src/identity.py` | Profiles, enrollments, same-kind identity, scoped identity, and pair consistency |
| `src/live_sessions.py` | Session labels, pending evidence, observations, state transitions, and reinforcement |
| `src/retrieve.py` | Confirmed-profile incident ranking |
| `src/guidance.py` | Caregiver-history-grounded action selection |
| `src/careflow.py` | Identity-to-memory preview and one-time completion |
| `src/store.py` | SQLite episode and baseline persistence |

### Live-session API

| Method and route | Success | Purpose |
|---|---:|---|
| `POST /api/live-sessions` | 201 | Create an independent session |
| `GET /api/live-sessions/{session_id}` | 200 | Load participants and timeline |
| `POST /api/live-sessions/{session_id}/observations` | 201 | Ingest and classify one recording |
| `POST /api/live-sessions/{session_id}/complete` | 200 | Close a session without deleting it |
| `GET /api/audio/live-observations/{observation_id}` | 200 | Play managed canonical observation audio |

Observation upload may also return 422 for invalid audio, 409 for a completed session, or 404 for
a missing session. A byte-identical duplicate remains a 201 timeline event.

Baby and care-memory routes remain available:

```text
GET    /api/profiles
POST   /api/profiles
POST   /api/profiles/{id}/enroll
POST   /api/identity/attempts
POST   /api/identity/attempts/{id}/captures
POST   /api/identity/attempts/{id}/retry
POST   /api/incidents/{attempt_id}/preview
POST   /api/incidents/{attempt_id}/complete
GET    /api/audio/enrollments/{id}
GET    /api/audio/episodes/{id}
```

### Managed audio stages

| Stage | Managed artifact | Purpose |
|---|---|---|
| Upload accepted | `source.<ext>` | Exact received evidence |
| Decode succeeds | `canonical.wav` | Stable 16 kHz mono processing and playback source |
| Normalization succeeds | `identity.wav` and its SHA-256 | Fixed-level acoustic identity input and live-session duplicate key |
| Encoder runs | Embedding in enrollment or query state | Acoustic profile comparison |
| Observation accepted | Session result and private managed-path associations | Timeline and audit |
| Public response | Labels, states, reasons, playback URL | UI without scores, paths, digests, or embeddings |

An invalid decode may leave the managed source file even when no canonical or identity file
exists. Unsupported MIME and empty uploads are rejected before a capture directory is created.

### SQLite tables

| Table | Responsibility |
|---|---|
| `episode` | Baby incident, context, caregiver action, outcome, audio, and provenance |
| `baseline` | Population or subject normalization statistics |
| `profile` | Baby or human acoustic profile |
| `enrollment` | Profile reference recording, digest, and embedding |
| `identity_query` | Internal identity audit |
| `identity_attempt` | Legacy baby or manual-profile attempt lifecycle |
| `identity_attempt_capture` | Attempt capture evidence |
| `live_identity_session` | Incremental session lifecycle |
| `live_identity_participant` | Stable session label, state, and support count |
| `live_identity_observation` | Timeline result, private managed paths, digest, and associations |

### Retained data

| Boundary | Retained locally | Returned publicly |
|---|---|---|
| Accepted observation | Source bytes, canonical WAV, identity WAV, identity-audio SHA-256 | No filesystem path or digest |
| Identity comparison | Enrollment and query embeddings, internal acoustic audit | Ordinal status and reason codes |
| Live session | Participant mapping, support count, observation associations | Stable labels, state, support count, timeline, playback URL |
| Baby care memory | Profile-scoped incidents, context, action, outcome, provenance, audio path | Grounded prior action and supporting incident references |
| New live session | Earlier sessions, profiles, enrollments, baby incidents remain | Only the requested new session view |

Production use would need explicit retention periods, deletion controls, authentication, access
control, encryption, consent records, and a model-license review. The CryCeleb checkpoint is
CC-BY-SA-4.0 and its source dataset has additional CC-BY-NC-ND-4.0 restrictions.

## What to build next

1. Collect a verified infant-identity dataset with explicit participant and guardian consent.
2. Measure more phones, rooms, distances, microphones, speakers, and playback paths.
3. Evaluate more participants and longer sessions without tuning on this ten-file cohort.
4. Calibrate session clustering and add an explicit pending-pattern merge policy.
5. Use time, caregiver notes, prior incidents, and context only for care retrieval, never acoustic
   identity.
6. Add production retention, deletion, security, and consent controls before any real deployment.

## Verification

The evaluators use the checked-in consented adult-imitation fixtures. They exercise different
state machines and should not be treated as population-level identity measurements.

Run every current incremental HTTP evaluator mode:

```bash
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode one-person
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode staged
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode difficult
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode probes
```

Run all gated incremental modes in one process and write a disposable report:

```bash
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json \
  --mode all \
  --output /tmp/cry-memory-live-session-results.json
```

Run the earlier named-profile evaluator in each supported mode:

```bash
.venv/bin/python tools/human_session_eval.py \
  demo_assets/human_audio/manifest.json --mode demo
.venv/bin/python tools/human_session_eval.py \
  demo_assets/human_audio/manifest.json --mode loo
.venv/bin/python tools/human_session_eval.py \
  demo_assets/human_audio/manifest.json --mode discovery
```

Run the focused certificate, live-session, browser-contract, and real-audio integration suites:

```bash
.venv/bin/python -m unittest \
  tests.test_mobile_capture_spike \
  tests.test_product_real_audio_api.RealAudioProductApiTests.test_incremental_live_session \
  tests.test_live_session_http \
  tests.test_live_identity_sessions -v
```

Run the complete Python suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The browser interaction test additionally needs Playwright and its Chromium build. Install them
locally once, without creating a package manifest or lock file, then run the interaction and syntax
checks:

```bash
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node tests/test_live_session_browser.mjs
node --check web/app.js
```

The complete technical data flow and failure boundaries are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The presentation and cleanup sequence is in the
[`demo operator runbook`](docs/DEMO-READY.md).
