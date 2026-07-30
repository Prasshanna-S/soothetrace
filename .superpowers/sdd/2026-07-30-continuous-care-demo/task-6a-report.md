# Task 6A Report: Minimum Phone-Testable Care HTTP Surface

Date: 2026-07-30

## Implementation

- Added the minimum Listen-page HTTP routes for care-session create, read, ordered raw chunk
  upload, pause, resume, stop, structured completion, and discard.
- Added score-free care readiness using the startup-prewarmed cry-detector boolean. Health never
  warms or downloads the detector, and the existing human dashboard health fields are unchanged.
- Warmed the cry detector once in production startup and passed its boolean into
  `build_http_server` as the final additive argument.
- Accepted raw Safari MP4 bodies with a required positive `X-Capture-Sequence`, reused managed
  audio ingest, and returned processed invalid audio as a structured 422 that advances sequence.
- Removed redundant managed capture directories for duplicate replay, conflict, gap, and
  unexpected unsaved failures while preserving the upload actually owned by the saved chunk.
- Added independent recursive HTTP allowlists for care profiles, sessions, decisions, guidance,
  scenarios, interventions, cry presence, chunks, and completion references.
- Kept the HTTP inference lock around care chunk analysis and completion. Read, create, state
  transitions, discard, health, and playback do not take it.
- Added profile-scoped representative incident audio with profile ownership, managed-root
  containment, and content-validated mono 16 kHz PCM WAV checks regardless of filename.
- Did not add history/detail JSON, Baby-detail, or care-event routes and did not edit `web/`.

## TDD Evidence

The first route tests failed before production changes because `build_http_server` did not accept
`cry_detector_status`. After readiness and basic session routes were implemented, 4 focused tests
passed.

The second RED run kept those 4 green while 6 new chunk, completion, cleanup, and scoped-audio
tests failed with 404 on the missing routes. After the minimum implementation, the complete
focused route class passed 10 of 10.

## Accelerated Verification

The owner approved accelerated test-build mode for an immediate controlled phone demo.

- Final bounded HTTP, startup, end-to-end, and real-audio selection: 12 passed, 1 fixed-rig
  fixture skip.
- Minimum route class alone: 10 passed.
- Existing recursive care-session privacy regression: 1 passed.
- Python compilation of all changed Python files: exit 0.
- `git diff --check`: exit 0.
- Changed-file scope: only `src/http_api.py`, the three requested product API test files,
  this report, and `docs/MESSAGES.md`.
- Forbidden em dash and en dash scan of changed source and tests: no matches.

Full unittest discovery is intentionally deferred to the background release review under the
owner-approved accelerated mode. The real fixed-rig care-route test is present but skipped in
this worktree because its private fixture directory is unavailable.

## Remaining Scope

History list, incident detail JSON, Baby detail, and care-event routes remain pending Task 5 and
the full Task 6. UI import and Windows work were not started.
