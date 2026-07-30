# Incremental Recording Identity Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an empty-session demonstration that accepts separate short recordings, immediately
classifies each one, creates provisional participant bubbles from confidently novel recordings,
and promotes those bubbles after separately captured supporting evidence.

**Architecture:** Add an additive SQLite-backed live-session service around the existing acoustic
identity subsystem. The service owns participant labels, provisional or established state,
observation history, duplicate protection, and reinforcement decisions. The browser calls one
observation endpoint for both microphone recordings and uploaded files, then renders the returned
latest result, timeline, and participant strip in a wide desktop workspace that collapses cleanly
on phones.

**Tech Stack:** Python 3.12, SQLite, the existing CryCeleb ECAPA and MFCC87 encoders, standard-library
HTTP server, plain JavaScript, HTML, CSS, unittest, Playwright, and ffmpeg.

## Global Constraints

- Identity uses acoustics only. Time, notes, duration, outcomes, and scenario labels never decide
  who produced a recording.
- No numeric confidence, similarity, score, margin, or percentage appears in the public API or UI.
- A weak direction never reinforces a participant profile.
- An exact byte duplicate never promotes a provisional participant.
- A new session never deletes infant profiles or caregiver history.
- Keep the existing neutral dark visual language and color semantics.
- Desktop uses a real wide layout with explicit columns. It must not scale or crop a phone layout.
- Phone controls remain at least 44 pixels and use safe-area insets.
- All punctuation added by this plan is plain ASCII. Do not add em dashes.
- No UI or GitHub push occurs until the real-audio and browser release gates pass.

---

### Task 1: Session-scoped acoustic helpers

**Files:**
- Modify: `src/identity.py`
- Test: `tests/test_live_identity_sessions.py`

**Interfaces:**
- Consumes: existing encoder-specific calibration, profile enrollments, `identity.identify`
- Produces:
  - `recordings_consistent(first_audio_path: str, second_audio_path: str, kind: str, db_path=None) -> dict`
  - `public_pair_result(result: dict) -> dict`
  - `identify_within_profiles(audio_path: str, profile_ids: list[int], kind: str, db_path=None, audit: bool = True) -> dict`
  - `profile_reference_audio(profile_id: int, db_path=None) -> list[str]`

- [x] **Step 1: Write failing helper tests**

Add tests that prove:

```python
result = identity.identify_within_profiles(
    query_path,
    [session_profile["id"]],
    identity.KIND_IMITATION,
    db_path,
    audit=False,
)
self.assertNotIn(unrelated_profile["id"], [
    item["profile_id"] for item in result.get("candidates", [])
])
```

and:

```python
pair = identity.recordings_consistent(
    first_path,
    second_path,
    identity.KIND_IMITATION,
    db_path,
)
self.assertIn("consistent", pair)
self.assertNotIn("scores", identity.public_pair_result(pair))
```

- [x] **Step 2: Run the helper tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_live_identity_sessions.LiveIdentityHelperTests -v
```

Expected: failures because the public helper functions do not exist.

- [x] **Step 3: Add profile filtering without weakening existing identity attempts**

Extend the internal enrollment loader and evaluator with an optional explicit profile-id set. Keep
the existing `identify()` behavior unchanged. `identify_within_profiles()` must call the filtered
path directly and must not reinterpret the display-only `candidate_profile_ids` field used by the
existing retry lifecycle.

- [x] **Step 4: Expose pair consistency and reference audio**

Wrap the existing dual-encoder pair check in a public function. Add a public sanitizer that returns
only `consistent`, `version`, and reason codes. Query reference paths by profile id without exposing
embedding vectors.

- [x] **Step 5: Run focused identity tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_live_identity_sessions.LiveIdentityHelperTests \
  tests.test_acoustics_identity -v
```

Expected: all tests pass.

- [x] **Step 6: Commit the helper boundary**

```bash
git add interaction-memory/src/identity.py \
  interaction-memory/tests/test_live_identity_sessions.py
git commit -m "feat: add session-scoped acoustic comparison"
```

---

### Task 2: Live-session persistence and state machine

**Files:**
- Modify: `src/schema.sql`
- Create: `src/live_sessions.py`
- Test: `tests/test_live_identity_sessions.py`

**Interfaces:**
- Consumes:
  - `identity.create_profile`
  - `identity.enroll`
  - `identity.identify_within_profiles`
  - `identity.recordings_consistent`
  - `identity.profile_reference_audio`
- Produces:
  - `create(kind: str = "human_imitation", db_path=None) -> dict`
  - `get(session_id: int, db_path=None) -> dict`
  - `complete(session_id: int, db_path=None) -> dict`
  - `submit_observation(session_id: int, audio_path: str, capture_metadata: dict | None = None, db_path=None) -> dict`
  - `observation_audio_path(observation_id: int, db_path=None) -> str | None`

- [x] **Step 1: Write failing state-transition tests**

Add tests for these exact transitions:

```python
first = live_sessions.submit_observation(session["id"], first_path, db_path=db)
self.assertEqual("provisional_created", first["classification"]["status"])
self.assertEqual("Person A", first["classification"]["participant"]["display_name"])
self.assertEqual("provisional", first["classification"]["participant"]["state"])
```

```python
second = live_sessions.submit_observation(session["id"], second_path, db_path=db)
self.assertEqual("participant", second["classification"]["status"])
self.assertEqual("established", second["classification"]["participant"]["state"])
self.assertTrue(second["classification"]["reinforced"])
```

Also cover:

- a confidently different recording creates provisional Person B;
- a weak leader returns `leaning` and does not enroll;
- exact duplicate bytes return `duplicate` and do not establish;
- invalid audio changes no participant state;
- stable labels continue past Person Z;
- completing a session rejects later observations;
- creating a second session leaves infant profiles and the first session intact.

- [x] **Step 2: Run state-transition tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_live_identity_sessions.LiveIdentityStateTests -v
```

Expected: failures because the session schema and module do not exist.

- [x] **Step 3: Add additive tables**

Add:

```sql
CREATE TABLE IF NOT EXISTS live_identity_session (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS live_identity_participant (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  profile_id INTEGER NOT NULL,
  display_name TEXT NOT NULL,
  state TEXT NOT NULL,
  support_count INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  established_at TEXT,
  UNIQUE(session_id, profile_id)
);

CREATE TABLE IF NOT EXISTS live_identity_observation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  sequence INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  source_type TEXT,
  source_audio_path TEXT,
  canonical_audio_path TEXT,
  identity_audio_path TEXT NOT NULL,
  audio_sha256 TEXT NOT NULL,
  status TEXT NOT NULL,
  participant_id INTEGER,
  closest_participant_id INTEGER,
  reinforced INTEGER NOT NULL DEFAULT 0,
  reason_codes TEXT NOT NULL DEFAULT '[]',
  UNIQUE(session_id, sequence)
);
```

Add indexes for session participants and observations.

- [x] **Step 4: Implement deterministic labels and public session rendering**

Labels use spreadsheet-style letters:

```python
1 -> Person A
26 -> Person Z
27 -> Person AA
```

The public session result contains participant and observation objects, playback URLs, states, and
reason codes. It contains no score, margin, candidate list, embedding, digest, or filesystem path.

- [x] **Step 5: Implement submission decisions**

Use this order:

1. reject missing, unusable, or completed-session input;
2. detect an exact digest duplicate;
3. first valid observation creates provisional Person A;
4. with one participant, use pair consistency against its reference;
5. with two or more participants, use session-scoped identification;
6. a confirmed known result enrolls and may promote that participant;
7. an unconfirmed leader returns `leaning` without enrollment;
8. a query outside every participant creates a provisional participant only if it is inconsistent
   with all current reference recordings;
9. a result that is neither safe to reinforce nor safe to call novel returns `possible_new` or
   `leaning` without changing references.

- [x] **Step 6: Run the complete live-session unit suite**

Run:

```bash
.venv/bin/python -m unittest tests.test_live_identity_sessions -v
```

Expected: all tests pass.

- [x] **Step 7: Commit the session engine**

```bash
git add interaction-memory/src/schema.sql \
  interaction-memory/src/live_sessions.py \
  interaction-memory/tests/test_live_identity_sessions.py
git commit -m "feat: add incremental identity session engine"
```

---

### Task 3: HTTP session API and audio playback

**Files:**
- Modify: `src/http_api.py`
- Modify: `tests/test_product_http_api.py`
- Create: `tests/test_live_session_http.py`

**Interfaces:**
- Consumes: `src.live_sessions`
- Produces:
  - `POST /api/live-sessions`
  - `GET /api/live-sessions/{session_id}`
  - `POST /api/live-sessions/{session_id}/observations`
  - `POST /api/live-sessions/{session_id}/complete`
  - `GET /api/audio/live-observations/{observation_id}`

- [x] **Step 1: Write failing API contract tests**

The API test creates a session, posts audio, loads the session, and checks the response:

```python
created = product.json("POST", "/api/live-sessions", {"kind": "human_imitation"})
self.assertEqual(201, created["status"])

observed = product.request(
    "POST",
    f"/api/live-sessions/{session_id}/observations",
    audio,
    {
        "Content-Type": "audio/wav",
        "Content-Length": str(len(audio)),
        "X-Capture-Source": "upload",
    },
)
self.assertEqual(201, observed["status"])
```

Assert that the JSON has no `score`, `margin`, `similarity`, `confidence`, `embedding`, digest, or
filesystem path.

- [x] **Step 2: Run API tests and verify 404 failures**

Run:

```bash
.venv/bin/python -m unittest tests.test_live_session_http -v
```

Expected: failures because the endpoints return 404.

- [x] **Step 3: Implement the routes**

Reuse `_ingest()` for bounded upload, decoding, canonicalization, and managed storage. Pass
`source_path`, `canonical_path`, `identity_path`, capture source, device, and user agent to the
session service.

Use status codes:

- 201 for session creation and accepted observations;
- 200 for session retrieval and completion;
- 404 for missing sessions or observations;
- 409 for completed sessions;
- 422 for invalid audio.

A byte-identical submission is still an observed session event, so it returns 201 with
`classification.status="duplicate"` and does not reinforce a participant.

- [x] **Step 4: Add observation playback**

Resolve the observation's canonical managed audio path through `_safe_managed_file()`. Return audio
only from the configured managed root.

- [x] **Step 5: Run HTTP and regression tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_live_session_http \
  tests.test_product_http_api \
  tests.test_product_real_audio_api -v
```

Expected: all available tests pass.

- [x] **Step 6: Commit the API**

```bash
git add interaction-memory/src/http_api.py \
  interaction-memory/tests/test_product_http_api.py \
  interaction-memory/tests/test_live_session_http.py
git commit -m "feat: expose live identity session API"
```

---

### Task 4: Desktop workspace and phone interaction

**Files:**
- Modify: `web/index.html`
- Modify: `web/app.js`
- Modify: `web/app.css`
- Modify: `tests/test_web_client.py`
- Create: `tests/test_live_session_browser.mjs`

**Interfaces:**
- Consumes: the Task 3 live-session API
- Produces:
  - automatic submission after a microphone recording stops or a file is selected;
  - latest classification card;
  - recording timeline with playback;
  - provisional and established participant strip;
  - responsive wide desktop and single-column phone layout.

- [x] **Step 1: Add failing static web-contract tests**

Require one occurrence of:

```text
live-session-console
live-capture-panel
live-result-panel
live-session-timeline
live-participant-strip
btn-new-live-session
```

Assert that app.js calls `/api/live-sessions`, `/observations`, and renders `provisional_created`,
`participant`, `leaning`, `possible_new`, `duplicate`, and `invalid`.

Assert that CSS includes:

```css
--workspace: 1180px;
grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
```

and collapses that grid under 820px.

- [x] **Step 2: Run static tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_web_client -v
```

Expected: new live-session contract tests fail.

- [x] **Step 3: Restructure only the human-imitation screen**

Keep the baby mode controls and IDs intact. In human mode:

- hide manual profile, enrollment, blind-query, retry, guidance, outcome, and roadmap surfaces;
- show the live session workspace;
- create a session on explicit New session;
- send every completed recording or selected file to the observation endpoint;
- prevent a second submission while one is processing;
- keep the current clip available if the network request fails.

- [x] **Step 4: Render the returned session**

Latest result:

- `participant`: solid green established result;
- `provisional_created`: dotted neutral or blue provisional result;
- `leaning`: blue directional result;
- `possible_new`: neutral result;
- `duplicate`: amber instruction for a separately captured sample;
- `invalid`: red capture correction.

Participant strip:

- dotted border and `Pattern forming` for provisional;
- solid border and `Repeated pattern` for established;
- stable name and supporting-recording count.

Timeline:

- one row per observation;
- microphone or upload source;
- result shown at submission;
- playback control;
- `reinforced profile`, `direction only`, `new provisional`, or `duplicate`.

- [x] **Step 5: Implement the real desktop layout**

Set the shell to a wide maximum only for the work screen. At 900 pixels and above:

- the capture panel occupies the left column;
- latest result occupies the right column;
- timeline and participant strip span both columns;
- cards use at least 28 pixels between them;
- card content uses at least 18 pixels of internal vertical rhythm;
- no transform, zoom, fixed device width, or viewport scaling is used.

At 819 pixels and below, use one column. At 480 pixels and below, retain safe-area padding, 44 pixel
targets, and large verdict text.

Remove the disabled roadmap section from the demonstration surface. Keep its documentation in the
repo.

- [x] **Step 6: Add browser behavior coverage**

The Playwright test uses a fake route or test server response to:

1. create a session;
2. select a file;
3. render provisional Person A;
4. select another file;
5. render established Person A;
6. verify the timeline has two observations;
7. verify the participant bubble changes from dotted to solid;
8. assert no horizontal overflow at 430 by 932, 900 by 900, and 1440 by 900.

- [x] **Step 7: Run web checks**

Run:

```bash
node --check web/app.js
.venv/bin/python -m unittest tests.test_web_client -v
node tests/test_live_session_browser.mjs
```

Expected: all checks pass at all three viewports.

- [x] **Step 8: Commit the interface**

```bash
git add interaction-memory/web/index.html \
  interaction-memory/web/app.js \
  interaction-memory/web/app.css \
  interaction-memory/tests/test_web_client.py \
  interaction-memory/tests/test_live_session_browser.mjs
git commit -m "feat: build responsive live identity workspace"
```

---

### Task 5: Real-audio stress test and understandable evidence

**Files:**
- Create: `tools/live_session_eval.py`
- Create: `demo_assets/human_audio/live-session-results.json`
- Modify: `demo_assets/human_audio/README.md`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Test: `tests/test_product_real_audio_api.py`

**Interfaces:**
- Consumes: live-session HTTP API and `demo_assets/human_audio/manifest.json`
- Produces:
  - `--mode one-person`
  - `--mode alternating`
  - `--mode difficult`
  - JSON metrics for direction, established matches, wrong names, provisional creation, duplicate
    profiles, and retries.

- [x] **Step 1: Write a failing real-audio session test**

Submit the available files through the product API in a fixed chronological sequence and assert:

```python
self.assertEqual(0, summary["wrong_person"])
self.assertEqual(3, summary["represented_people"])
self.assertEqual(3, summary["participants_created"])
```

Do not require a perfect established-match rate. Preserve every unresolved or direction-only
result in the report.

- [x] **Step 2: Run the real-audio test and record the failure**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_product_real_audio_api.RealAudioProductApiTests.test_incremental_live_session -v
```

Expected: failure because the evaluator and result summary do not exist.

- [x] **Step 3: Implement the evaluator**

The expected person is read only by the evaluator after the API responds. It is never sent to the
server. Write exact per-observation output plus:

- valid observations;
- correct established assignments;
- correct directional assignments;
- wrong assignments;
- provisional participants created;
- duplicate participant profiles;
- invalid recordings;
- direction coverage.

- [x] **Step 4: Run all available session orders**

Run:

```bash
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode one-person
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode alternating
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode difficult
```

Save the machine-readable output. If any confident wrong assignment occurs, stop interface release
work and adjust the reinforcement or novelty gate before proceeding.

- [x] **Step 5: Update README with the measured result**

Explain:

- what the user clicks;
- what dotted and solid bubbles mean;
- how to run the server;
- how to reproduce the stress test;
- every measured numerator and denominator;
- that the small consented cohort is demonstration evidence, not population accuracy.

Add GitHub-rendered Mermaid diagrams for:

- phone capture or upload through HTTP ingest, canonical audio, both encoders, the live-session
  decision service, SQLite state, and the participant UI;
- baby identity through profile-scoped incident retrieval, grounded guidance, and caregiver outcome
  storage.

Add compact tables for:

- what runs on the phone and what runs on the laptop;
- module responsibilities;
- live-session API routes;
- managed audio files and SQLite tables;
- data retained at each processing stage.

- [x] **Step 6: Commit the real-audio evidence**

```bash
git add interaction-memory/tools/live_session_eval.py \
  interaction-memory/demo_assets/human_audio/live-session-results.json \
  interaction-memory/demo_assets/human_audio/README.md \
  interaction-memory/README.md \
  interaction-memory/docs/ARCHITECTURE.md \
  interaction-memory/tests/test_product_real_audio_api.py
git commit -m "test: measure incremental identity sessions"
```

---

### Task 6: Full verification, naming cleanup, and GitHub handoff

**Files:**
- Modify only as required by failed checks

**Interfaces:**
- Consumes: final backend, interface, and demo cohort
- Produces: verified local release, cleaned project-only GitHub history, updated repository About

- [x] **Step 1: Run the complete suite sequentially**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
node --check web/app.js
python3 tools/scrub_dashes.py --all
git diff --check
```

Expected: zero failures, JavaScript syntax success, no new punctuation violations, and no whitespace
errors.

- [x] **Step 2: Run real browser acceptance against the actual backend**

At 1440 by 900:

- create a session;
- submit a file that creates Person A;
- submit a second file that establishes Person A;
- submit a different person's file that creates provisional Person B;
- verify timeline playback and participant strip.

Repeat layout and core submission checks at 430 by 932.

- [x] **Step 3: Remove agent and vendor labels**

Verify tracked content and project-only history contain no agent handles, attribution trailers, or
agent and vendor names. Record the literal zero-hit audit command in the private release report
rather than in tracked project content, so the audit pattern cannot match itself.

Use neutral role or feature wording. Preserve technical model names such as CryCeleb.

- [ ] **Step 4: Create and verify the project-only public snapshot**

Export only the committed `interaction-memory` tree into a clean repository with a neutral public
release commit. Verify its content, tests, audio assets, and README. Do not include unrelated files
from the parent repository or the private development history.

- [ ] **Step 5: Publish the verified GitHub repository**

Preserve the existing development repository as a private archive. Publish the verified clean
snapshot at `Prasshanna-S/interaction-memory`, update the About description and topics, make the
repository public after the remote verification passes, and verify anonymous access to the default
branch.

- [x] **Step 6: Mark O7 complete**

Update `docs/TASKS.md` to `DONE`, append exact metrics and release commit identifiers to
`docs/MESSAGES.md`, and commit the release record.
