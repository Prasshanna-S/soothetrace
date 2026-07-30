# Task 2 Report: Persistent Care Sessions

Date: 2026-07-30

## Implementation

- Added additive `care_session`, `care_session_chunk`, and `care_event` tables with every field
  specified by the approved design.
- Added the required unique chunk sequence constraint and indexes for session status, chunk order,
  care-event history, and profile incident history.
- Added the persistent infant-only care-session facade with create, read, pause, resume, Stop, and
  discard operations.
- Restricted creation to non-archived infant profiles returned by `identity.get_profile`.
- Normalized tags by trimming, Unicode case folding, empty-value removal, stable deduplication, and
  a 20-tag cap.
- Implemented the exact allowed transition table, idempotent Stop while awaiting an outcome, and
  immutable complete and discarded states.
- Added an allowlisted public profile and session renderer. Stored decision JSON is rebuilt from
  the exact recursive public contract for the decision, profile, guidance, scenarios,
  interventions, string lists, incident IDs, and episode audio URLs. Unknown or incorrectly typed
  fields never cross the rendering boundary.
- Added discard cleanup that resolves the managed root and every stored source, canonical, and
  identity path before deleting. It refuses siblings, outside paths, terminal sessions, and any
  session that already references a saved episode.
- Did not edit `web/`, cry-gate thresholds, identity model behavior, or any existing public API.

## TDD Evidence

### RED

Command:

```text
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_care_sessions -v
```

Observed before production implementation:

```text
ImportError: cannot import name 'care_sessions' from 'src'
Ran 1 test in 0.002s
FAILED (errors=1)
```

The failure matched the expected missing Task 2 module and was not caused by a test typo.

### GREEN

The same focused command passed all 14 Task 2 tests after the minimum schema and state facade were
implemented:

```text
Ran 14 tests in 0.898s
OK
```

The test-only clarity refactor was followed by another focused pass.

### Round 1 Review RED

Four independent reviewer findings were reproduced before their production fixes:

1. The discard and completion race expected completion to update zero rows, but observed one. The
   final row was complete after its selected audio had been removed.
2. The decision contract test observed unknown `artifact`, `cosine`, `candidate_profiles`, hash,
   path, embedding, and underscore-prefixed fields in the public snapshot.
3. A patched `Path.unlink` `PermissionError` expected `care_session_cleanup_failed`, but discard
   returned a public discarded snapshot.
4. Two Stop calls forced to read `listening` concurrently returned one awaiting-outcome snapshot
   and one `invalid_care_session_transition` error.

A fifth RED regression covered multi-file cleanup. After the first unlink succeeded and the second
raised `PermissionError`, the session remained listening even though one chunk file was already
missing.

### Round 1 Review GREEN

- Discard now starts `BEGIN IMMEDIATE` before reading state or touching files. Completion and other
  writers cannot attach an episode while managed cleanup is in progress.
- A cleanup failure before any removal rolls back and returns
  `care_session_cleanup_failed`, preserving the original state and file.
- A cleanup failure after one or more removals seals the locked session as discarded, returns the
  stable error, and permits an idempotent discard retry for remaining managed paths. It never
  presents a partially missing session as resumable or completable.
- Decision rendering now uses explicit recursive field and type allowlists from the approved
  public contract. It does not infer safety from key names.
- A losing concurrent Stop CAS rolls back, re-reads, and returns the winning awaiting-outcome
  snapshot with the stored timestamp.

The focused suite passed all 18 tests after these fixes.

## Verification

- Focused Task 2 tests: 18 passed.
- Relevant store, identity, live-session, and Windows portability regressions: 94 passed before
  the final multi-file cleanup regression and remained covered by full discovery.
- Full unittest discovery with loopback permission: 377 passed, 8 documented fixture or
  platform-specific skips.
- The first full discovery attempt inside the restricted sandbox produced 32 setup errors because
  local test servers could not bind loopback sockets. The authorized rerun passed all tests.
- Python compilation completed with exit 0.
- Diff whitespace and changed-file scope checks completed with exit 0.
- The forbidden em dash and en dash scan found no matches in the Task 2 commit set.

## Self-Review

- Schema changes are additive and leave all existing tables and APIs intact.
- Every transition update is conditional on the previously read state, so a concurrent state
  change cannot silently overwrite a terminal state.
- Stop does not refresh its timestamp when repeated, including a concurrent losing request.
- Public output is constructed from explicit fields. It never serializes a database row directly.
- Managed-root validation uses resolved path ancestry, not string-prefix comparison. This prevents
  a sibling such as `managed-other` from passing a `managed` root check.
- Discard owns the SQLite write transaction before cleanup. Completed sessions and sessions with
  an episode reference are rejected before filesystem work.
- Zero-removal cleanup errors preserve the original session. Partial cleanup errors seal the
  session terminally and can retry remaining paths without exposing a false success response.
- Task 3 chunk analysis, Task 4 completion, and later HTTP integration were not started.

## Concerns

- SQLite cannot roll back an operating-system file unlink after process termination. During a live
  process, the write transaction and partial-cleanup policy prevent completion from winning after
  removal, and a repeat discard removes any retained managed paths.
- Real model and fixed-rig tests remain skipped unless their explicit environment flags and
  fixtures are available. This task does not change model behavior.
