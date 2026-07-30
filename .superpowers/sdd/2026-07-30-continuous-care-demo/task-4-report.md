# Task 4 Report: Structured Completion and Exactly-Once Incident Save

Date: 2026-07-30

## Implementation

- Added deterministic structured episode completion with required trimmed action, exact
  `bool | None` settled validation, note limits, literal caregiver evidence, and stable automatic
  transcript and typed follow-up labels.
- Kept automatically extracted recording actions ahead of the typed final action, removed only
  exact action/evidence duplicates, and renumbered the stored order.
- Derived `worked` and the caregiver-sourced outcome directly from the submitted settled state and
  literal trimmed notes. No model can rewrite those values.
- Selected `selected_chunk_id` when present and otherwise `latest_matched_chunk_id`. Completion
  reads only that matched chunk's canonical managed audio and its pre-inference `created_at`.
- Used the representative chunk time for both episode `started_at` and the existing safe current
  context collector. Session tags and completion tags are normalized together before collecting
  supported care-event context.
- Persisted `care_session_id`, representative `selected_chunk_id`, and `profile_id` in the initial
  episode insert.
- Added a per-database, per-session process mutation lock shared by completion and discard.
  Transcription, fingerprinting, context collection, and episode saving do not run inside a
  SQLite transaction.
- Added persistent exactly-once recovery by checking the attached episode ID, scanning profile
  episodes for `context.care_session_id`, claiming the process lock, repeating both checks, saving,
  attaching through a state and null-episode compare-and-swap, and scanning context again after an
  attach failure.
- Froze the safe completion result to `{"session": ..., "incident": {"id": ...,
  "detail_url": ...}}`. The detail URL is profile-scoped and internal episode data is not returned.
- Did not edit `web/`, schema, thresholds, identity behavior, or HTTP routes.

## TDD Evidence

### Structured Finish RED

The focused structured-finish command ran seven tests and failed on the missing interface:

```text
AttributeError: module 'src.session' has no attribute 'finish_structured'
Ran 7 tests
FAILED (errors=22)
```

The subtest errors covered missing behavior for invalid action, invalid settled values, all three
valid settled values, note validation, transcript provenance, literal evidence, selected time and
context, no automatic transcript, and save failure.

### Structured Finish GREEN

After the minimum implementation:

```text
Ran 7 tests in 3.271s
OK
```

### Care-Session Completion RED

Six focused completion and concurrency tests failed before production implementation:

```text
AttributeError: module 'src.care_sessions' has no attribute 'complete'
AttributeError: module 'src.care_sessions' has no attribute 'context'
AttributeError: module 'src.care_sessions' has no attribute 'session'
Ran 6 tests
FAILED (errors=6)
```

### Care-Session Completion GREEN

The same six tests passed after the claimed save and recovery path was implemented:

```text
Ran 6 tests in 0.536s
OK
```

They proved selected-chunk priority, latest-match fallback, safe result shape, one-row idempotency,
transient attach recovery, one transcription and one episode under concurrent completion, and
discard exclusion while completion transcribes.

### Error Boundary RED and GREEN

One final TDD cycle forced the context collector to raise. Before the fix, the exception escaped.
After the completion boundary returned `care_session_storage_error`, the same session completed on
a clean retry and proved that the process claim was released.

## Verification

- Final focused Task 4 modules: 54 passed.
- Relevant store, context, careflow, HTTP, live-session, ingest, and Windows regressions:
  88 passed with 1 dedicated Windows-lane skip.
- The first relevant HTTP run inside the restricted sandbox produced 25 loopback bind errors.
  The authorized loopback rerun passed.
- Full unittest discovery with loopback permission: 406 passed with 8 documented model, fixture,
  or dedicated Windows-lane skips.
- Python compilation completed with exit 0.
- Diff whitespace and changed-file scope checks completed with exit 0.
- Existing recursive public privacy tests passed, and completion's incident object has exactly
  `id` and `detail_url`.
- The forbidden em dash and en dash scan found no matches in Task 4 source or tests.

## Self-Review

- `0`, `1`, strings, lists, and dictionaries cannot pass settled validation through Python truth
  coercion.
- A missing automatic transcript stores only the explicitly labeled typed follow-up and does not
  invent recording speech.
- Only canonical audio is selected. Source and identity paths are never fallback completion input.
- The representative chunk timestamp is captured before Task 3 inference and is reused without
  calling the clock during incident construction.
- The initial episode insert already carries all recovery keys, so an attach failure cannot force
  a second save.
- Completion and discard use the same process lock. The existing SQLite discard claim remains in
  place for filesystem cleanup and state sealing.
- Repeated completion returns the original incident ID and the same allowlisted result shape even
  when later submitted values are invalid or different.
- No SQLite write transaction spans transcription or other model work.

## Concern

Exactly-once coordination is process-local plus persistent recovery. It is correct for the current
single-process threaded server. A future multi-process deployment requires a schema uniqueness
constraint or another cross-process claim keyed by care session.

## Review Round 1

### Important Finding

The first implementation skipped appending the structured caregiver pair when an identical
action/evidence pair already appeared among automatically extracted actions. If that duplicate
occurred before another extracted action, the later automatic action incorrectly remained final.
The original test placed the duplicate last and did not distinguish deduplication from final
position.

### RED

An adversarial regression supplied the structured pair first, followed by two different extracted
actions. Before the fix, the stored order began with the typed pair and ended with the later
automatic action:

```text
FAIL: test_structured_finish_moves_an_earlier_exact_duplicate_to_the_end
Ran 1 test in 1.125s
FAILED (failures=1)
```

### GREEN

Structured completion now removes every extracted exact duplicate of the typed pair, preserves the
stable order of all other unique extracted pairs, and appends the literal typed pair exactly once
at the end.

```text
Ran 8 structured-finish tests in 0.798s
OK
```

The bounded review verification passed 87 Task 4, speech, careflow, context, and store tests.
