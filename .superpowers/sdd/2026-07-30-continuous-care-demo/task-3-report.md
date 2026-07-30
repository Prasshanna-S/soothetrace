# Task 3 Report: Rolling Infant Cry Chunk Analysis

Date: 2026-07-30

## Implementation

- Added a profile-based incident preview that does not require or read an identity-attempt row.
  It accepts only an existing infant profile, fingerprints canonical raw audio, builds context at
  the supplied time, searches only `profile-{profile_id}`, and never writes an episode.
- Added monotonic chunk submission with sequence 1 as the first accepted sequence, stable gap and
  conflict errors, and digest-based replay of the original stored result.
- Stamped chunk capture time at submit entry, before model inference, and passed that exact time to
  profile preview for deterministic context and future Task 4 incident timing.
- Ran the local cry-presence gate before identity. Negative, uncertain, invalid, and unavailable
  gate states fail closed without identity or history access.
- Used only `identity.identify(..., kind="infant", audit=True)` for cry-positive chunks. Rolling
  chunks never create profiles, enroll audio, reinforce profiles, or use the identity-attempt
  lifecycle.
- Allowed history access only after identity matched the session's selected infant. Matches to
  another profile and uncertain identity results remain history-free.
- Persisted source-derived SHA-256, quality, capture metadata, score-free cry presence, identity
  audit outcome, reason codes, and the original public result.
- Kept all gate, identity, fingerprint, retrieval, and guidance work outside SQLite write
  transactions. The final short `BEGIN IMMEDIATE` transaction rechecks state and sequence, inserts
  the chunk, advances the session with a compare-and-swap condition, and stores the replay result.
- Added an in-process inference claim keyed by resolved database, session, and sequence. Only the
  owner can run cry, identity, or history inference; concurrent losers wait and then resolve to
  stored replay or `sequence_conflict`. Claims for unrelated sessions remain independent.
- Advanced `latest_matched_chunk_id` for every selected-profile match. The first grounded result
  alone sets `selected_chunk_id` and `decision_json`; later grounded results cannot replace it.
- Added recursive allowlists for chunk replay, cry presence, guidance, scenarios, interventions,
  supporting incident IDs, and session decisions. Public results contain no scores, margins,
  paths, digests, embeddings, candidates, or underscore-prefixed diagnostics.
- Derived supporting audio URLs in the future profile-scoped form
  `/api/profiles/{profile_id}/incidents/{episode_id}/audio`. Task 5 will add that route.
- Did not edit `web/`, cry-gate thresholds, identity thresholds, contracts, or Windows behavior.

## TDD Evidence

### Profile Preview RED

Command:

```text
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_product_careflow.ProfilePreviewTests -v
```

Observed before production implementation:

```text
AttributeError: module 'src.careflow' has no attribute 'preview_profile_incident'
Ran 3 tests in 2.761s
FAILED (errors=3)
```

The failures matched the missing Task 3 interface.

### Profile Preview GREEN

The same command passed all three tests after the shared preview pipeline was factored:

```text
Ran 3 tests in 0.566s
OK
```

### Chunk Pipeline RED

Command:

```text
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_care_sessions tests.test_product_careflow -v
```

Observed before chunk implementation:

```text
AttributeError: module 'src.care_sessions' has no attribute 'submit_chunk'
```

Twelve chunk assertions errored on the missing interface and the profile-scoped decision URL
assertion failed against the old allowlist. The failures covered ordering, replay, conflicts,
non-listening states, invalid ingest, cry-gate isolation, selected-profile isolation, no
enrollment, metadata persistence, timestamp ordering, first guidance latch, and recursive privacy.

### Chunk Pipeline GREEN

After the minimum chunk implementation:

```text
Ran 37 tests in 1.327s
OK
```

### Scoped Audio Compatibility RED and GREEN

Self-review found that real retrieval scenarios do not yet carry the future profile-scoped audio
URL. A focused regression first failed when the stored scenario contained the legacy unscoped URL.
After deriving the URL from the selected profile and already isolated incident ID, the focused
test passed and the combined suite remained green:

```text
Ran 38 tests in 1.083s
OK
```

The count is 38 because the explicit scoped-URL test was named once directly and then encountered
again in the two-module suite.

## Verification

- Focused Task 3 care-session and careflow tests: 37 passed.
- Final combined focused run with the repeated scoped-URL regression: 38 passed.
- Relevant identity, two-profile, live-session, audio-ingest, cry-gate, and Windows portability
  regressions: 117 passed, 1 dedicated Windows-lane skip.
- Full unittest discovery with local loopback permission: 389 passed, 8 documented model,
  fixed-rig fixture, or dedicated Windows-lane skips.
- Python compilation completed with exit 0.
- Diff whitespace and changed-file scope checks completed with exit 0.
- Recursive public privacy assertions passed.
- The forbidden em dash and en dash scan found no matches in Task 3 files.

## Self-Review

- Sequence and session state are checked before inference and checked again under the final short
  write lock. A concurrent Stop, pause, discard, or competing chunk cannot be silently overwritten.
- An identical digest replay is resolved before inference and returns the original stored session
  and chunk snapshot even after a later chunk changes the current session.
- The digest is recomputed from the managed source file and never trusted from caller metadata.
- The gate is the only entry to identity. Only a selected-profile match is the entry to careflow.
- Profile preview searches, counts, and tallies only `profile-{profile_id}` and writes no episode.
- The first grounded decision is stored with its true capture time, safe supporting incidents, and
  profile-scoped audio URLs. Later matches advance audit state but cannot replace it.
- `selected_chunk_id` identifies the latched chunk. `latest_matched_chunk_id` identifies the most
  recent selected-profile match, including later matches after latching.
- Model inference never runs while a SQLite write transaction is held, preserving threaded HTTP
  behavior and avoiding identity-audit write contention.
- Every inference claim is released in a `finally` block, including unexpected exceptions. A
  failed owner leaves the sequence available for one later request to claim and process.
- Existing Task 2 Stop and discard race, partial cleanup, immutable state, and recursive decision
  tests remain green.
- Task 4 and later HTTP or browser work were not started.

## Concerns

- HTTP ingest occurs before domain-level sequence deduplication. A duplicate, conflicting,
  out-of-order, or non-listening upload is not inserted as a new chunk, so its newly ingested
  managed files are not discoverable through this session's cleanup rows. Task 5 should remove
  rejected upload artifacts or perform a read-only sequence preflight before ingest.
- Inference ownership is process-local. The current threaded single-process HTTP server is covered;
  a future multi-process deployment would need a cross-process claim before inference.
- Profile-scoped supporting audio URLs intentionally target the Task 5 route and are not served by
  Task 3 alone.
- Real AST, fixed-rig, and native Windows smoke tests remain behind their documented environment
  flags and fixture availability. No threshold or portability behavior changed here.

## Review Round 1

### Important Finding

The reviewer reproduced two concurrent requests for the same new sequence crossing read-only
preflight and both calling `identity.identify(..., audit=True)` before either reached the final
database compare-and-swap. Public replay was correct, but identity audit and history inference ran
twice.

### RED

Two deterministic races synchronized both requests immediately after read-only preflight. One used
identical source bytes and one used conflicting source bytes. Before the fix:

```text
AssertionError: 1 != 2
```

Both tests observed two cry-gate calls instead of one. Because each cry-positive path continued,
identity audit and history preview also ran twice.

A third cleanup regression forced an unexpected profile-read exception. Before the fix it escaped
from `submit_chunk`, proving there was no claim cleanup or structured failure boundary.

### GREEN

The per-key inference claim made one request the owner before any cry, identity, or history work.
Losers wait without inference, then repeat read-only sequence resolution:

```text
Ran 3 tests in 0.106s
OK
```

- Identical digest: both callers received the exact stored public result.
- Conflicting digest: the loser returned `sequence_conflict`.
- Both races performed exactly one cry-gate call, one audited identity call, and one history
  preview.
- An unexpected owner exception returned `care_session_storage_error`, released the claim, and a
  later retry processed successfully.

### Review Verification

- Focused care-session and careflow suite: 40 passed.
- Full unittest discovery with local loopback permission: 392 passed, 8 documented skips.
- Inference remains outside SQLite write transactions.
- Claims are keyed by resolved database, session, and sequence, so unrelated sessions are not
  serialized.
