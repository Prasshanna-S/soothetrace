# Hosted SootheTrace Release Implementation Plan

> **Execution note:** Work through these tasks in order where dependencies exist.
> Independent hosting, frontend, and documentation tasks may run in parallel.

**Goal:** Publish one self-running HTTPS SootheTrace service with a complete
infant experience, a small Human Baby profile, temporary visitor data, a clean
public repository, and evidence-backed verification.

**Architecture:** A single Python HTTP service serves the browser app and API
inside one Docker container. Render terminates HTTPS. Curated Demo Baby data and
model caches use a persistent disk. Anonymous visitor sessions use scoped
records and managed audio that expire after one hour. Infant and Human Baby
classification remain separate backend domains.

**Stack:** Python 3.12, `http.server`, SQLite, NumPy, SciPy, FFmpeg, PyTorch,
SpeechBrain, Hugging Face Transformers, browser MediaRecorder, vanilla
JavaScript, CSS, Docker, Render.

---

## Task 1: Establish a fresh green baseline

**Files:**

- Inspect: `requirements.txt`
- Inspect: `tests/`
- Inspect: `src/`
- Inspect: `web/`

**Step 1: Record the branch and worktree state**

Run:

```bash
git status --short --branch
git log --oneline --decorate -8
```

Expected: only the approved design and plan commits are new.

**Step 2: Run the complete existing test suite**

Run:

```bash
python -m unittest discover -s tests
```

Expected: all existing tests pass before product changes.

**Step 3: Record optional dependency availability**

Run:

```bash
python -m src.http_api --help
ffmpeg -version
```

Expected: server help succeeds and FFmpeg is available.

## Task 2: Unify runtime configuration and SQLite behavior

**Files:**

- Modify: `src/config.py`
- Modify: `src/store.py`
- Modify: `src/care_sessions.py`
- Modify: `src/live_sessions.py`
- Modify: `src/schema.sql`
- Create: `src/database.py`
- Test: `tests/test_runtime_config.py`
- Test: `tests/test_product_store.py`

**Step 1: Write failing configuration tests**

Cover:

- `IM_DATA_ROOT`, `IM_DB_PATH`, `IM_AUDIO_DIR`, and `IM_MODEL_DIR`;
- repository-relative defaults for local development;
- no hard-coded personal `.env` path; and
- explicit environment selection for an optional secret file.

**Step 2: Write failing SQLite tests**

Assert every application connection enables:

- `PRAGMA foreign_keys=ON`;
- WAL journal mode for file databases; and
- a nonzero busy timeout.

**Step 3: Add one shared connection helper**

Implement `src/database.py`. Replace private connection factories where doing
so does not alter domain behavior.

**Step 4: Implement environment-backed paths**

Ensure model download paths, ingestion paths, schema paths, database paths, and
cleanup paths use the same configuration source.

**Step 5: Run focused and complete tests**

Run:

```bash
python -m unittest tests.test_runtime_config tests.test_product_store
python -m unittest discover -s tests
```

## Task 3: Add hosted runtime and deployment assets

**Files:**

- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `render.yaml`
- Create: `.env.example`
- Create: `scripts/hosted_bootstrap.py`
- Modify: `src/http_api.py`
- Test: `tests/test_hosted_runtime.py`
- Test: `tests/test_product_cli.py`
- Test: `tests/test_product_http_api.py`

**Step 1: Write failing hosted CLI tests**

Cover:

- `$PORT` as the default hosted port;
- a `--behind-tls-proxy` mode that permits container HTTP on `0.0.0.0`;
- continued rejection of accidental public plain HTTP without that flag;
- graceful process shutdown; and
- deterministic data paths.

**Step 2: Write failing liveness and readiness tests**

Add:

- `GET /livez`, always 200 once the process serves;
- `GET /readyz`, 503 until database, FFmpeg, baseline, infant encoder,
  human encoder, and cry gate meet the configured release profile;
- `GET /api/health`, detailed but path-free diagnostic state.

**Step 3: Add the bootstrap**

Create directories, initialize the schema, verify the population baseline,
prepare curated Demo Baby memory, warm required models, and fail clearly when
the selected release profile is unavailable.

**Step 4: Add a multi-stage Docker build**

Use Python 3.12 slim, install FFmpeg, run as a non-root user, copy only release
files, expose the host port, and start the proxy-aware server.

**Step 5: Add the Render blueprint**

Use one Docker web service, one instance, a persistent `/var/data` disk,
`/readyz` as health check, and explicit environment paths.

**Step 6: Verify locally**

Run:

```bash
docker build -t soothetrace:local .
docker run --rm -p 8010:10000 soothetrace:local
curl --fail http://127.0.0.1:8010/livez
curl --fail http://127.0.0.1:8010/readyz
```

## Task 4: Add anonymous visitor sessions and retention

**Files:**

- Modify: `src/schema.sql`
- Create: `src/visitor_sessions.py`
- Modify: `src/http_api.py`
- Modify: `src/identity.py`
- Modify: `src/care_sessions.py`
- Modify: `src/live_sessions.py`
- Test: `tests/test_visitor_sessions.py`
- Test: `tests/test_hosted_access_http.py`

**Step 1: Write failing lifecycle tests**

Cover:

- opaque random browser token;
- only a token hash stored in SQLite;
- one-hour expiry;
- last-seen refresh does not extend past configured retention when disabled;
- immediate delete;
- expired session cleanup removes managed visitor audio and derived rows; and
- curated demo records remain.

**Step 2: Write failing isolation tests**

Create two browser cookie jars. Assert:

- visitor A cannot list or load visitor B's profile;
- visitor A cannot load visitor B's care or Human Baby session;
- visitor A cannot play visitor B's audio;
- both can see only the curated Demo Baby profile; and
- filesystem paths never appear in public payloads.

**Step 3: Add consent and session endpoints**

Implement:

- `GET /api/visitor-session`;
- `POST /api/visitor-session/consent`; and
- `DELETE /api/visitor-session`.

Use `HttpOnly`, `SameSite=Lax`, `Secure` when behind HTTPS, and a narrow cookie
path.

**Step 4: Scope created records**

Add owner hashes to visitor-created profiles and live sessions. Derive care and
episode authorization through the owned profile. Treat curated profile rows as
explicitly public demo data, not as unowned visitor data.

**Step 5: Add request controls**

Implement same-origin mutation checks, per-session request limits, maximum
active sessions, maximum stored duration, and cleanup of failed uploads.

**Step 6: Run security-focused tests**

Run:

```bash
python -m unittest tests.test_visitor_sessions tests.test_hosted_access_http
```

## Task 5: Complete profile, History, and Baby APIs

**Files:**

- Create: `src/profile_views.py`
- Modify: `src/http_api.py`
- Modify: `src/store.py`
- Test: `tests/test_profile_views.py`
- Test: `tests/test_profile_http.py`

**Step 1: Write failing domain tests**

Cover profile summary, enrollment count, memory count, latest memory, paginated
incidents, incident detail, transcript excerpts, tags, interventions, outcomes,
supporting incident references, and unavailable audio.

**Step 2: Add safe domain projections**

Return allowlisted fields only. Do not expose raw embeddings, scores, margins,
database paths, model cache paths, or internal prompts.

**Step 3: Add HTTP routes**

Implement:

- `GET /api/profiles/{profile_id}`;
- `GET /api/profiles/{profile_id}/incidents`;
- `GET /api/profiles/{profile_id}/incidents/{incident_id}`; and
- existing profile-scoped incident audio with visitor authorization.

**Step 4: Run focused tests**

Run:

```bash
python -m unittest tests.test_profile_views tests.test_profile_http
```

## Task 6: Make infant confirmation observable and duplicate aware

**Files:**

- Modify: `src/schema.sql`
- Modify: `src/care_sessions.py`
- Modify: `src/http_api.py`
- Create: `src/audio_duplicate.py`
- Test: `tests/test_care_sessions.py`
- Test: `tests/test_care_diagnostics_http.py`

**Step 1: Write failing exact-duplicate tests**

Assert:

- four distinct qualifying segments latch;
- the same bytes on four different sequences do not latch;
- retrying the same sequence returns the original response; and
- a repeated source returns `repeated_source_not_confirmation`.

**Step 2: Write failing canonical and near-duplicate tests**

Create test WAVs with container and level changes. Assert canonical equivalence
or high acoustic duplicate similarity does not increment confirmation.

**Step 3: Persist public-safe diagnostics**

Store canonical digest, acoustic duplicate signature/version, candidate token,
progress, server latch time, and reason codes. Keep raw scores private.

**Step 4: Remove the client reveal delay**

Set server latch as the source of truth. Display a returned decision immediately
while keeping the visible cry-detection state responsive on preceding segments.

**Step 5: Add session diagnostics**

Expose only the current visitor's care session timeline with per-segment status,
progress, and timestamps. Keep audio paths and model scores private.

**Step 6: Run regression tests**

Run:

```bash
python -m unittest tests.test_care_sessions tests.test_care_diagnostics_http
```

## Task 7: Refactor the browser app without changing its visual language

**Files:**

- Modify: `web/index.html`
- Modify: `web/app.css`
- Replace: `web/app.js`
- Create: `web/app/api.js`
- Create: `web/app/state.js`
- Create: `web/app/router.js`
- Create: `web/app/orb.js`
- Create: `web/app/listen.js`
- Create: `web/app/history.js`
- Create: `web/app/baby.js`
- Create: `web/app/human-baby.js`
- Create: `web/app/icons.js`
- Test: `tests/test_web_client.py`
- Test: `tests/test_app_browser.mjs`

**Step 1: Write failing structural tests**

Assert one module owns each behavior, all static module paths are served, and
the app exposes no placeholder History or Baby copy.

**Step 2: Extract the current working Listen behavior**

Preserve capture rotation, upload retry, screen wake lock, interruption
handling, orb renderer, landscape composition, and outcome completion.

**Step 3: Implement History**

Add paginated incident cards, detail view, transcript excerpts, context chips,
audio playback, evidence links, and explicit loading, empty, and error states.

**Step 4: Implement Baby**

Add profile summary, memory readiness, enrollment count, latest activity,
explanation of contributing evidence, and visitor-data deletion.

**Step 5: Implement the small Human Baby mode**

Use the existing live-session routes. Provide microphone capture, upload, one
classification result at a time, participant bubbles, a compact timeline,
finish, and reset. Do not add care guidance or infant latching.

**Step 6: Add consent**

Before first recording, show concise recording and one-hour retention copy.
Record consent through the visitor-session endpoint.

**Step 7: Fix visible state replacement**

Ensure Listening, checking, cry state, comparison, progress, and suggestion use
one live region and replace previous text rather than overlapping.

**Step 8: Verify responsive layout**

Test iPhone portrait, short iPhone landscape, desktop, full-screen installed
PWA mode, keyboard navigation, reduced motion, and large readable suggestion
text.

## Task 8: Curate a reproducible audio acceptance pack

**Files:**

- Modify: `demo_assets/baby_audio/manifest.json`
- Modify: `demo_assets/baby_audio/README.md`
- Modify: `demo_assets/human_audio/manifest.json`
- Modify: `demo_assets/human_audio/README.md`
- Create: `demo_assets/ASSET-PROVENANCE.md`
- Create: `tools/release_audio_eval.py`
- Test: `tests/test_release_audio_pack.py`

**Step 1: Inventory every tracked clip**

Record origin, permission or licence, subject grouping claim, channel, format,
duration, checksum, and permitted purpose.

**Step 2: Remove unsupported claims**

Do not describe UUID corpus groups as verified biological identity unless the
source establishes that fact. Do not call a channel-sensitive result general
accuracy.

**Step 3: Build one release evaluator**

Report infant gate acceptance, negative-audio false acceptance, profile
direction, Human Baby coverage, answered precision, overall rank-one result,
unresolved count, and per-file status.

**Step 4: Run the complete releasable pack**

Run:

```bash
python tools/release_audio_eval.py --json artifacts/release-audio-eval.json
```

Keep private local acceptance files optional and ignored.

## Task 9: Clean and explain the public repository

**Files:**

- Rewrite: `README.md`
- Create: `docs/TECHNICAL-ARCHITECTURE.md`
- Create: `docs/EVALUATION.md`
- Create: `PRIVACY.md`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `THIRD_PARTY.md`
- Create: `LICENSE`
- Modify: `.gitignore`
- Remove from public head: internal coordination and raw experiment documents

**Step 1: Preserve local working history**

Copy internal notes, raw reports, private fixtures, and calibration material to
ignored `work/private/` before removing them from the public head.

**Step 2: Rewrite the README**

Lead with SootheTrace, the hosted link, product story, what users can try,
architecture, measured evidence, limitations, local run, Docker run, tests, and
licence notices. Use the current repository URL.

**Step 3: Add the technical diagram**

Clearly label:

- custom SootheTrace MFCC87 and orchestration;
- third-party AudioSet AST, CryCeleb ECAPA, FFmpeg, SQLite, and optional
  Whisper/API transcription;
- profile-scoped retrieval;
- acoustic, time, tags, notes, and outcome inputs; and
- persistent demo data versus temporary visitor data.

**Step 4: Add public project policies**

Document prototype privacy, security reporting, contribution steps, third-party
models/assets, and the chosen source licence.

**Step 5: Verify a clean clone path**

Run the documented setup and tests from a fresh temporary clone.

## Task 10: Full release verification

**Files:**

- Create: `docs/RELEASE-VERIFICATION.md`
- Create: `artifacts/` as an ignored local output directory

**Step 1: Run all Python tests**

```bash
python -m unittest discover -s tests
```

**Step 2: Run all browser tests**

```bash
node --test tests/test_app_browser.mjs tests/test_live_session_browser.mjs
```

**Step 3: Run the release audio evaluation**

```bash
python tools/release_audio_eval.py --json artifacts/release-audio-eval.json
```

**Step 4: Build and smoke-test Docker**

```bash
docker build -t soothetrace:release .
docker run --rm -p 8010:10000 soothetrace:release
```

Verify `/livez`, `/readyz`, static assets, profile APIs, care capture, History,
Baby, Human Baby, session isolation, deletion, and restart persistence.

**Step 5: Inspect for accidental disclosure**

Search tracked files for personal absolute paths, secret filenames, API keys,
internal agent instructions, raw model scores, and unsupported accuracy claims.

**Step 6: Perform physical phone acceptance**

Use the hosted HTTPS URL on the iPhone. Test portrait, landscape, screen lock,
microphone permission, continuous capture, three infant demonstration clips,
Human Baby capture, History playback, and data deletion.

## Task 11: Publish and deploy

**Files:**

- Update: `README.md` with the final public URL
- Update: `docs/RELEASE-VERIFICATION.md` with exact verified commit

**Step 1: Review the final diff**

Confirm only intended release files are tracked.

**Step 2: Commit coherent release checkpoints**

Commit hosting, privacy/backend, frontend, evaluation, and documentation as
separate reviewable changes.

**Step 3: Push the release branch**

Push to `Prasshanna-S/soothetrace`.

**Step 4: Deploy the saved commit**

Create or update the Render service, attach the persistent disk, configure
environment variables, and wait for `/readyz`.

**Step 5: Verify the public link**

Run a public smoke test without local cookies, then a two-browser isolation
test. Add the verified URL to the README and push that final documentation
commit.
