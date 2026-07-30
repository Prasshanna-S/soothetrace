# Continuous Care Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local infant-care demo that continuously accepts independent phone audio segments, rejects non-cry audio, identifies the selected enrolled infant, latches one history-grounded suggestion, saves one structured incident, and exposes transcript-rich profile history.

**Architecture:** The browser keeps one microphone stream while rotating finalized 12-second blobs over ordinary HTTP requests. A new persistent `care_sessions` facade owns sequence idempotency and session state without enrolling correlated chunks. Each usable chunk passes managed ingest, a local AudioSet infant-cry gate, non-enrolling identity against the full infant pool, profile-isolated retrieval, and a first-guidance latch. Existing episodes remain the source of care memory, while additive profile, history, detail, scoped-audio, and care-event APIs expose only allowlisted facts.

**Tech Stack:** Python 3.12, standard-library HTTP server and SQLite, numpy, scipy, soundfile, FFmpeg, PyTorch 2.6, Transformers 4.48.3, MIT Audio Spectrogram Transformer, vanilla HTML/CSS/JavaScript, Node browser tests, GitHub Actions on Windows.

## Global Constraints

- Use Python 3.12. Do not add `librosa`.
- Keep infant cry and caregiver speech in the same canonical raw mixture.
- Never use a generative model in cry detection.
- The cry gate detects infant-cry presence only. It never names a cause, emotion, urgency, or diagnosis.
- Adult cry imitation remains a separate mode and is negative in an infant care session.
- Never enroll or reinforce a profile from continuous care chunks.
- Run infant identity against the full active infant pool only after the cry gate passes.
- Context may rank accepted-profile history but may never affect identity.
- Latch the first nonempty `grounded` recommendation until Stop.
- No raw cry probability, cosine score, margin, digest, path, embedding, or hidden profile reaches a public payload.
- Never display cosine or model output as percentage confidence.
- Completing one care session saves exactly one episode and is idempotent after partial failures.
- Full transcript text appears only after opening one incident.
- Do not imply word-level or sentence-level audio timestamps.
- Claude owns `web/`. Backend workers do not edit browser files while Claude is working.
- Preserve macOS and Windows support.
- Use `apply_patch` for repository edits.
- Write tests first and observe the expected failure before production code.
- Commit messages begin with `product workstream:`.
- Do not use em dash or en dash characters in code, copy, docs, tests, or commit messages.

---

### Task 1: Local infant-cry presence gate

**Files:**
- Create: `src/cry_gate.py`
- Create: `tests/test_cry_gate.py`
- Create: `tests/test_cry_gate_real_audio.py`
- Modify: `src/config.py`
- Modify: `requirements.txt`
- Modify: `tools/doctor.py`
- Modify: `tests/test_windows_portability.py`

**Interfaces:**
- Consumes: canonical 16 kHz mono WAV produced by `audio_ingest.ingest_audio`.
- Produces: `cry_gate.warm() -> bool`.
- Produces: `cry_gate.readiness() -> dict[str, object]`.
- Produces: `cry_gate.classify(audio_path: str) -> dict[str, object]`.
- Public status values: `infant_cry_detected`, `cry_uncertain`, `no_cry_detected`, `invalid_audio`, `gate_unavailable`.
- Internal-only keys: `_infant_score` and `_generic_cry_score`, floats used by the evaluator and removed by every public serializer.
- Frozen provisional strong rule: infant score at least `0.040` and at least `1.20` times the generic `Crying, sobbing` score.
- Frozen provisional borderline rule: not strong and infant score at least `0.025`.
- Model: `MIT/ast-finetuned-audioset-10-10-0.4593`.
- Target label: `Baby cry, infant cry`.
- Model version: `ast-audioset-baby-cry-v1`.

- [ ] **Step 1: Write failing adapter and threshold tests**

Add tests that patch the model-scoring seam instead of downloading weights:

```python
class CryGateDecisionTests(unittest.TestCase):
    def test_strong_rule_requires_absolute_and_relative_evidence(self):
        with patch.object(cry_gate, "_event_scores", return_value=(0.04, 0.03)):
            result = cry_gate.classify(self.wav_path)
        self.assertEqual("infant_cry_detected", result["status"])
        self.assertEqual(["infant_cry_evidence_strong"], result["reason_codes"])

    def test_middle_band_abstains(self):
        with patch.object(cry_gate, "_event_scores", return_value=(0.03, 0.01)):
            result = cry_gate.classify(self.wav_path)
        self.assertEqual("cry_uncertain", result["status"])
        self.assertEqual(["infant_cry_evidence_borderline"], result["reason_codes"])

    def test_low_score_is_not_detected(self):
        with patch.object(cry_gate, "_event_scores", return_value=(0.024, 0.001)):
            result = cry_gate.classify(self.wav_path)
        self.assertEqual("no_cry_detected", result["status"])
        self.assertEqual(["infant_cry_evidence_low"], result["reason_codes"])

    def test_generic_cry_dominance_abstains(self):
        with patch.object(cry_gate, "_event_scores", return_value=(0.08, 0.08)):
            result = cry_gate.classify(self.wav_path)
        self.assertEqual("cry_uncertain", result["status"])
        self.assertEqual(["generic_cry_not_infant_specific"], result["reason_codes"])

    def test_model_failure_is_fail_closed(self):
        with patch.object(cry_gate, "_event_scores", side_effect=RuntimeError("boom")):
            result = cry_gate.classify(self.wav_path)
        self.assertEqual("gate_unavailable", result["status"])
        self.assertEqual(["cry_gate_model_unavailable"], result["reason_codes"])
```

Also assert that missing files, non-WAV input, empty audio, wrong sample rate, and stereo audio do not call `_event_scores`.

- [ ] **Step 2: Run the focused tests and observe the missing-module failure**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_cry_gate -v
```

Expected: FAIL because `src.cry_gate` does not exist.

- [ ] **Step 3: Add the model configuration and dependency**

Add these constants to `src/config.py`:

```python
MODEL_DIR = _p("models")
CRY_GATE_MODEL_ID = "MIT/ast-finetuned-audioset-10-10-0.4593"
CRY_GATE_MODEL_VERSION = "ast-audioset-baby-cry-v1"
```

Add `transformers==4.48.3` to `requirements.txt`. Keep the existing Torch and TorchAudio pins.

- [ ] **Step 4: Implement one-view AST inference and score-free decisions**

`src/cry_gate.py` must:

1. Read canonical WAV with `soundfile`.
2. Require mono 16 kHz audio.
3. Select one centered view of at most 160,000 samples.
4. Load `AutoFeatureExtractor` and `AutoModelForAudioClassification` once under a module lock.
5. Call the model under `torch.inference_mode()`.
6. Apply sigmoid because AudioSet is multi-label.
7. Find `Baby cry, infant cry` and `Crying, sobbing` from `model.config.id2label`.
8. Return the two underscore-prefixed diagnostic scores internally, plus `status`, `label`, `reason_codes`, `analyzed_duration_s`, `analysis_view_count=1`, and `model_version`.

Do not add max-over-window aggregation. The measured spike made 4 to 5 of 10 adult imitations look infant-like under 3-second and 5-second max windows.

The public decision skeleton is:

```python
def _decision(status, reason_code, infant_score, generic_score, duration_s):
    return {
        "status": status,
        "label": (
            "Infant-cry-like sound detected"
            if status == "infant_cry_detected"
            else None
        ),
        "reason_codes": [reason_code],
        "analyzed_duration_s": round(duration_s, 3),
        "analysis_view_count": 1,
        "model_version": config.CRY_GATE_MODEL_VERSION,
        "_infant_score": infant_score,
        "_generic_cry_score": generic_score,
    }
```

- [ ] **Step 5: Run unit tests and observe green**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_cry_gate -v
```

Expected: PASS.

- [ ] **Step 6: Add optional real-model tests over checked-in fixtures**

`tests/test_cry_gate_real_audio.py` must skip unless `IM_RUN_CRY_MODEL_TESTS=1`. When enabled, it warms the cached model and asserts:

```python
self.assertEqual("infant_cry_detected", classify(planned_baby_query)["status"])
self.assertNotEqual("infant_cry_detected", classify(adult_imitation)["status"])
```

Iterate all 18 infant assets and all 10 adult imitation assets, print a confusion table only on failure, and assert at least 14 of 18 strong infant accepts and 0 of 10 strong adult accepts. When the separately downloaded ESC-50 slice is available, assert 40 of 40 `crying_baby` accepts and 0 of 245 sampled environmental accepts.

- [ ] **Step 7: Extend doctor and Windows portability checks**

`tools/doctor.py` must show:

- model cached and runnable;
- target label present;
- model version;
- a blocking failure when the user requests infant care but the gate is unavailable.

Add a Windows test proving the cache path lives beneath `config.MODEL_DIR`, contains no hard-coded slash, and does not require privileged symlink creation.

- [ ] **Step 8: Run cry-gate and portability tests**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_cry_gate \
  tests.test_windows_portability -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/cry_gate.py src/config.py requirements.txt tools/doctor.py \
  tests/test_cry_gate.py tests/test_cry_gate_real_audio.py \
  tests/test_windows_portability.py
git commit -m "product workstream: add local infant cry gate"
```

---

### Task 2: Persistent care-session state machine

**Files:**
- Create: `src/care_sessions.py`
- Create: `tests/test_care_sessions.py`
- Modify: `src/schema.sql`

**Interfaces:**
- Consumes: active infant profiles from `identity.get_profile`.
- Produces: `care_sessions.create(profile_id: int, tags: list[str] | None = None, db_path: str | None = None) -> dict`.
- Produces: `care_sessions.get(session_id: int, db_path: str | None = None) -> dict`.
- Produces: `care_sessions.pause(session_id: int, db_path: str | None = None) -> dict`.
- Produces: `care_sessions.resume(session_id: int, db_path: str | None = None) -> dict`.
- Produces: `care_sessions.stop(session_id: int, db_path: str | None = None) -> dict`.
- Produces: `care_sessions.discard(session_id: int, audio_root: str | Path, db_path: str | None = None) -> dict`.
- Server states: `listening`, `paused`, `awaiting_outcome`, `complete`, `discarded`.
- Domain errors use `{"status":"error","reason":"stable_reason_code"}`.
- Public session snapshots contain no paths, digests, raw scores, or embeddings.

- [ ] **Step 1: Write failing schema and transition tests**

Cover:

- only active infant profiles can create a care session;
- tags are trimmed, case-folded, deduplicated, and capped at 20;
- create starts at `listening` with `last_sequence=0`;
- pause and resume follow the state table;
- stop from listening or paused enters `awaiting_outcome`;
- stop is idempotent;
- complete and discarded sessions are immutable;
- invalid transitions return `invalid_care_session_transition`;
- discard deletes only unsaved files beneath the provided managed audio root;
- returned snapshots expose no path-like or metric fields.

Example:

```python
def test_first_grounded_decision_field_starts_empty(self):
    profile = identity.create_profile("Baby A", identity.KIND_INFANT, self.db)
    session = care_sessions.create(profile["id"], [" Evening ", "evening"], self.db)
    self.assertEqual("listening", session["status"])
    self.assertEqual(["evening"], session["tags"])
    self.assertIsNone(session["decision"])
```

- [ ] **Step 2: Run the focused tests and observe failure**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_care_sessions -v
```

Expected: FAIL because the new tables and module do not exist.

- [ ] **Step 3: Add the additive tables**

Add `care_session`, `care_session_chunk`, and `care_event` exactly as defined in the design spec. Include:

```sql
UNIQUE(session_id, sequence)
```

and these JSON text columns:

```text
care_session.tags_json
care_session.decision_json
care_session_chunk.capture_metadata_json
care_session_chunk.quality_json
care_session_chunk.cry_reason_codes
care_session_chunk.reason_codes
care_session_chunk.result_json
care_event.details
```

Create indexes for session status, chunk order, care-event profile/time, and profile incident history.

- [ ] **Step 4: Implement validation, rendering, and transitions**

Follow the existing `live_sessions.py` connection pattern, but do not call enrollment functions.

Use these transition sets:

```python
_ALLOWED = {
    ("listening", "pause"): "paused",
    ("paused", "resume"): "listening",
    ("listening", "stop"): "awaiting_outcome",
    ("paused", "stop"): "awaiting_outcome",
}
```

The renderer must return:

```python
{
    "id": row["id"],
    "status": row["status"],
    "profile": public_profile,
    "started_at": row["created_at"],
    "paused_at": row["paused_at"],
    "stopped_at": row["stopped_at"],
    "completed_at": row["completed_at"],
    "last_sequence": row["last_sequence"],
    "tags": decoded_tags,
    "decision": decoded_safe_decision,
}
```

- [ ] **Step 5: Implement bounded discard cleanup**

Resolve both the configured audio root and each stored path. Delete only files whose resolved path is a descendant of the root. Mark the row discarded after cleanup. Do not delete a completed episode or its audio.

- [ ] **Step 6: Run state-machine tests**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_care_sessions -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/schema.sql src/care_sessions.py tests/test_care_sessions.py
git commit -m "product workstream: persist infant care sessions"
```

---

### Task 3: Chunk sequencing, cry gating, identity isolation, and guidance latch

**Files:**
- Modify: `src/care_sessions.py`
- Modify: `src/careflow.py`
- Modify: `tests/test_care_sessions.py`
- Modify: `tests/test_product_careflow.py`

**Interfaces:**
- Produces: `careflow.preview_profile_incident(profile_id: int, canonical_audio: str, explicit_tags: list[str] | None = None, now: str | None = None, db_path: str | None = None) -> dict`.
- Produces: `care_sessions.submit_chunk(session_id: int, sequence: int, ingested: dict, db_path: str | None = None) -> dict`.
- `submit_chunk` calls `cry_gate.classify`, then `identity.identify(..., kind="infant", audit=True)`, then `careflow.preview_profile_incident` only for a selected-profile match.
- Public chunk status values: `invalid`, `no_cry_detected`, `cry_uncertain`, `not_selected_profile`, `matched_no_guidance`, `guidance_latched`, `matched_guidance_already_latched`.
- An identical repeated `(session_id, sequence, digest)` returns stored `result_json`.
- A repeated sequence with different bytes returns `sequence_conflict`.
- A gap returns `out_of_order_chunk`.

- [ ] **Step 1: Write failing profile-preview tests**

Prove `preview_profile_incident`:

- accepts a profile and canonical audio without an identity-attempt row;
- searches only `subject_id="profile-{profile_id}"`;
- uses the supplied `now` for deterministic time context;
- writes no episode;
- returns safe guidance and scenarios;
- fails when the profile is absent, non-infant, or audio is unusable.

- [ ] **Step 2: Run the careflow tests and observe failure**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_product_careflow.ProfilePreviewTests -v
```

Expected: FAIL because `preview_profile_incident` is missing.

- [ ] **Step 3: Factor the existing preview pipeline**

Extract the shared fingerprint, context, retrieval, tally, and guidance work from `_incident_view` without changing the existing attempt-based endpoints. Ensure the new function returns an internal preview with:

```python
{
    "status": "preview",
    "identity": {"profile_id": profile_id, "display_name": name, "kind": "infant"},
    "scenarios": scenarios,
    "guidance": guidance_payload,
    "_canonical_audio": canonical_audio,
    "_current_context": current_context,
}
```

- [ ] **Step 4: Write failing chunk-order and idempotency tests**

Add tests for:

- first accepted sequence is 1;
- sequence 3 before 2 returns `out_of_order_chunk`;
- identical repeated sequence returns the original response after a later chunk changes session state;
- conflicting bytes return `sequence_conflict`;
- chunks are rejected while paused, awaiting outcome, complete, or discarded.

- [ ] **Step 5: Write failing gate-isolation tests**

Patch collaborators and prove:

```python
cry_gate.classify -> no_cry_detected
identity.identify.assert_not_called()
careflow.preview_profile_incident.assert_not_called()
```

Repeat for `cry_uncertain` and `gate_unavailable`. Also prove:

- an `infant_cry_detected` result that matches another profile does not call careflow;
- an identity uncertainty does not call careflow;
- only the selected-profile match can read history;
- no chunk path enrolls or reinforces any profile.

- [ ] **Step 6: Write failing first-guidance-latch tests**

Submit three matched chunks:

1. no guidance;
2. grounded action A;
3. grounded action B.

Assert chunk 2 returns `guidance_latched`, chunk 3 returns `matched_guidance_already_latched`, and the session decision still contains action A and chunk 2's safe supporting incidents.

- [ ] **Step 7: Run the focused tests and observe failures**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_care_sessions \
  tests.test_product_careflow -v
```

Expected: FAIL on missing chunk behavior.

- [ ] **Step 8: Implement transactional chunk persistence**

Within `submit_chunk`:

1. Validate the session and sequence.
2. Compute digest from the managed source file.
3. Resolve repeat or conflict before inference.
4. Persist the quality and capture metadata.
5. Fail closed on invalid ingest or cry-gate unavailability.
6. Persist a score-free `cry_presence` object without underscore-prefixed diagnostic scores.
7. Run identity only for `infant_cry_detected`.
8. Run profile preview only for a selected-profile match.
9. Store only allowlisted scenarios and guidance in `result_json`.
10. Atomically advance `last_sequence`, `latest_matched_chunk_id`, and the first `decision_json`.

The score-free cry object is:

```python
{
    key: value
    for key, value in cry_result.items()
    if key in {
        "status", "label", "reason_codes", "analyzed_duration_s",
        "analysis_view_count", "model_version",
    }
}
```

- [ ] **Step 9: Run focused and leakage tests**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_care_sessions \
  tests.test_product_careflow -v
```

Expected: PASS, including recursive assertions that public results contain none of:

```text
score margin digest path embedding candidates _score _infant_score _generic_cry_score
```

- [ ] **Step 10: Commit**

```bash
git add src/care_sessions.py src/careflow.py \
  tests/test_care_sessions.py tests/test_product_careflow.py
git commit -m "product workstream: analyse rolling infant cry chunks"
```

---

### Task 4: Structured completion and exactly-once incident save

**Files:**
- Modify: `src/session.py`
- Modify: `src/care_sessions.py`
- Modify: `tests/test_product_session.py`
- Modify: `tests/test_care_sessions.py`

**Interfaces:**
- Produces: `session.finish_structured(subject_id: str, audio_path: str, action: str, settled: bool | None, notes: str | None, *, started_at: str, db_path: str | None = None, context_override: dict | None = None) -> dict`.
- Produces: `care_sessions.complete(session_id: int, action: str, settled: bool | None, notes: str | None = None, tags: list[str] | None = None, db_path: str | None = None) -> dict`.
- Completion uses the latched chunk when one exists, otherwise the latest selected-profile matched chunk.
- Completion is idempotent and returns the original episode after success.

- [ ] **Step 1: Write failing structured-finish tests**

Cover:

- action required, trimmed, maximum 500 characters;
- settled only `True`, `False`, or `None`;
- notes maximum 1000 characters;
- selected chunk timestamp becomes episode `started_at`;
- automatic transcript and typed follow-up retain stable source labels;
- typed action is the final intervention and literal evidence;
- settled true, false, and unknown map to `worked` without truthiness bugs;
- no transcript produces no invented speech;
- save failure returns no episode ID.

Expected transcript shape:

```text
Audio transcript: I picked her up.
Typed caregiver follow-up: Action: Held baby upright. Settled: yes. Notes: Settled in two minutes.
```

- [ ] **Step 2: Run session tests and observe failure**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_product_session.StructuredFinishTests -v
```

Expected: FAIL because `finish_structured` is missing.

- [ ] **Step 3: Implement deterministic structured completion**

Call `speech.transcribe` once on the representative canonical segment. Build the intervention and outcome deterministically from submitted fields. The LLM may not rewrite the action, settled state, or notes.

Use:

```python
outcome_prefix = {
    True: "The baby settled.",
    False: "The baby did not settle.",
    None: "Whether the baby settled was not recorded.",
}[settled]
```

Append trimmed notes verbatim. Keep extracted recording actions before the structured final action, deduplicating exact action/evidence pairs.

- [ ] **Step 4: Write failing care-session completion tests**

Prove:

- complete before Stop returns `invalid_care_session_transition`;
- complete without a matched chunk returns `no_matched_chunk`;
- one completion writes one episode;
- repeated completion returns the same episode ID;
- an update failure after episode save is recovered by locating `context.care_session_id`;
- concurrent completion calls do not create two episodes;
- episode context contains care-session and selected-chunk IDs internally;
- public serializers later filter those IDs.

- [ ] **Step 5: Run care-session tests and observe failure**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_care_sessions -v
```

Expected: FAIL on missing completion behavior.

- [ ] **Step 6: Implement the completion claim and recovery path**

Use a process lock plus persistent recovery:

1. Check for an existing `episode_id`.
2. Search profile episodes for `context.care_session_id == session_id`.
3. Claim the session in an in-process set.
4. Recheck steps 1 and 2.
5. Call `finish_structured`.
6. Attach the episode ID and mark the session complete.
7. On a repeat after step 5 succeeded but step 6 failed, recover the existing episode instead of saving again.

- [ ] **Step 7: Run focused tests**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_product_session \
  tests.test_care_sessions -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/session.py src/care_sessions.py \
  tests/test_product_session.py tests/test_care_sessions.py
git commit -m "product workstream: save structured care outcomes once"
```

---

### Task 5: Baby details, chronological history, incident detail, and care events

**Files:**
- Create: `src/care_history.py`
- Create: `tests/test_care_history.py`
- Modify: `src/store.py`
- Modify: `src/context.py`
- Modify: `tests/test_product_store.py`
- Modify: `tests/test_product_context.py`

**Interfaces:**
- Produces: `store.save_care_event(profile_id: int, event_type: str, occurred_at: str, details: dict | None = None, path: str | None = None) -> dict`.
- Produces: `store.list_care_events(profile_id: int, since: str | None = None, path: str | None = None) -> list[dict]`.
- Produces: `care_history.profile_detail(profile_id: int, db_path: str | None = None) -> dict`.
- Produces: `care_history.list_incidents(profile_id: int, limit: int = 25, cursor: str | None = None, db_path: str | None = None) -> dict`.
- Produces: `care_history.incident_detail(profile_id: int, incident_id: int, db_path: str | None = None) -> dict`.
- Produces: `care_history.incident_audio_path(profile_id: int, incident_id: int, db_path: str | None = None) -> str | None`.
- Allowed care-event types: `feeding`, `sleep`, `diaper`, `soothing`, `note`.
- History cursor is opaque base64url JSON containing `started_at` and `id`.

- [ ] **Step 1: Write failing care-event tests**

Cover timezone-aware timestamps, type allowlist, detail-object validation, profile existence, newest-first order, `since`, and database failures. Assert that context derives only the existing deterministic feeding, sleep-end, and recent-diaper tags.

- [ ] **Step 2: Run store and context tests and observe failure**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_product_store \
  tests.test_product_context -v
```

Expected: FAIL because care-event storage is missing.

- [ ] **Step 3: Implement care-event storage**

Store exact caregiver facts. Do not generate cause tags. Return decoded details, and treat malformed stored details as `{}`.

- [ ] **Step 4: Write failing profile and history tests**

Cover:

- profile detail includes exact enrollment count, memory count, created time, training clip IDs, captured time, duration, and scoped playback URLs;
- only infant profile incidents with subject `profile-{id}` appear;
- list order is newest first with deterministic tied-time pagination;
- invalid cursors are errors, not empty history;
- transcript list excerpt is at most 160 characters;
- full detail parses `Audio transcript:` and `Typed caregiver follow-up:` into separate segments;
- legacy unlabeled and synthetic seed transcripts keep explicit source labels;
- literal evidence source is assigned only when it appears in exactly one segment;
- no transcript returns `not_available`, never `no speech`;
- public context uses the allowlist;
- wrong-profile incident and audio lookup return not found;
- missing audio keeps incident detail available with `audio.status="unavailable"`.

- [ ] **Step 5: Run history tests and observe failure**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_care_history -v
```

Expected: FAIL because `src.care_history` is missing.

- [ ] **Step 6: Implement transcript parsing and public views**

Use `text.partition` and exact stable prefixes, not free-form guessing. Escape nothing in Python because JSON carries plain strings and the browser will use `textContent`.

Public outcome shape:

```python
{
    "text": episode.get("outcome"),
    "source": episode.get("outcome_src"),
    "settled": episode.get("worked"),
}
```

Public audio shape:

```python
{
    "status": "available" if safe_audio else "unavailable",
    "url": scoped_url if safe_audio else None,
    "role": "representative cry segment",
}
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_care_history \
  tests.test_product_store \
  tests.test_product_context -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/care_history.py src/store.py src/context.py \
  tests/test_care_history.py tests/test_product_store.py \
  tests/test_product_context.py
git commit -m "product workstream: expose profile care history"
```

---

### Task 6: Complete local HTTP API and readiness surface

**Files:**
- Modify: `src/http_api.py`
- Modify: `tests/test_product_http_api.py`
- Modify: `tests/test_product_e2e.py`
- Modify: `tests/test_product_real_audio_api.py`

**Interfaces:**
- Adds all routes listed in `docs/CLAUDE-FRONTEND-HANDOFF-CARE-DEMO.md`.
- `build_http_server` accepts additive `cry_detector_status: bool | None = None`.
- `GET /api/health` adds `care.ready` and score-free cry detector version.
- `POST /api/care-sessions/{id}/chunks` requires positive `X-Capture-Sequence`.
- The HTTP layer is the final allowlist boundary for every care-session payload.

- [ ] **Step 1: Write failing health and creation tests**

Prove:

- health reports `care.ready` only when the infant encoder, required baseline, FFmpeg, database, and cry gate are ready;
- missing cry gate keeps existing human mode health fields intact;
- care-session creation returns 503 `cry_detector_unavailable` when the gate is unavailable;
- valid creation returns the exact public session shape.

- [ ] **Step 2: Write failing GET route tests**

Cover:

```text
GET /api/profiles/{profile_id}
GET /api/profiles/{profile_id}/incidents
GET /api/profiles/{profile_id}/incidents/{incident_id}
GET /api/profiles/{profile_id}/incidents/{incident_id}/audio
GET /api/profiles/{profile_id}/care-events
GET /api/care-sessions/{session_id}
```

Assert wrong-profile detail and audio both return 404 and do not reveal ownership.

- [ ] **Step 3: Write failing POST and DELETE route tests**

Cover:

```text
POST   /api/profiles/{profile_id}/care-events
POST   /api/care-sessions
POST   /api/care-sessions/{session_id}/chunks
POST   /api/care-sessions/{session_id}/pause
POST   /api/care-sessions/{session_id}/resume
POST   /api/care-sessions/{session_id}/stop
POST   /api/care-sessions/{session_id}/complete
DELETE /api/care-sessions/{session_id}
```

Test missing, non-integer, zero, repeated, and gapped sequence headers. Test action, settled, notes, and tag validation limits.

- [ ] **Step 4: Run HTTP tests and observe failures**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_product_http_api -v
```

Expected: FAIL on missing routes.

- [ ] **Step 5: Add serializers before handlers**

Implement `_public_care_session`, `_public_care_chunk`, and recursive forbidden-key tests. The chunk serializer must remove every underscore-prefixed diagnostic score even if a mocked domain result includes it.

The forbidden recursive key set is:

```python
{
    "_score", "_infant_score", "_generic_cry_score",
    "score", "margin", "digest", "audio_sha256",
    "source_path", "canonical_path", "identity_path",
    "source_audio_path", "canonical_audio_path", "identity_audio_path",
    "embedding", "candidates",
}
```

- [ ] **Step 6: Implement route parsing and status mapping**

Use stable mappings:

```text
not found                         -> 404
cry_detector_unavailable          -> 503
invalid body/header               -> 400
invalid transition/sequence       -> 409
invalid or undecodable audio      -> 422
created session/event/chunk       -> 201
read/pause/resume/stop/complete   -> 200
discard                           -> 200
unexpected persistence failure    -> 500
```

Keep `_INFERENCE_LOCK` around chunk analysis and completion, not around static or history GETs.

- [ ] **Step 7: Add profile-scoped audio serving**

Do not route History through `/api/audio/episodes/{id}`. Resolve the profile-scoped path through `care_history.incident_audio_path`, then apply the existing managed-root check and canonical-WAV requirement.

- [ ] **Step 8: Run HTTP and end-to-end tests**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_product_http_api \
  tests.test_product_e2e \
  tests.test_product_real_audio_api -v
```

Expected: PASS.

- [ ] **Step 9: Mark routes green for Claude**

Append one entry to `docs/MESSAGES.md` containing:

```text
O9 backend routes green
```

List the exact test command and count. Tell Claude it may replace static fixtures with same-origin API calls without changing backend field names.

- [ ] **Step 10: Commit**

```bash
git add src/http_api.py tests/test_product_http_api.py \
  tests/test_product_e2e.py tests/test_product_real_audio_api.py \
  docs/MESSAGES.md
git commit -m "product workstream: serve continuous care APIs"
```

---

### Task 7: Deterministic demo preparation and evaluator

**Files:**
- Create: `scripts/prepare_care_demo.py`
- Create: `tools/care_demo_eval.py`
- Create: `tests/test_prepare_care_demo.py`
- Create: `tests/test_care_demo_eval.py`
- Create: `docs/CARE-DEMO-RUNBOOK.md`
- Modify: `scripts/seed_demo_memory.py`
- Modify: `docs/MESSAGES.md`

**Interfaces:**
- Produces: `prepare_care_demo.prepare(stage: str, db_path: str, data_root: str) -> dict`.
- Allowed stages: `early`, `mature`.
- Early snapshot: exactly five usable Baby 1 memories.
- Mature snapshot: exactly six usable Baby 1 memories.
- Produces CLI: `python tools/care_demo_eval.py --db PATH --positive-dir PATH --negative-dir PATH --runs 5`.
- Evaluator exits 0 only when every gate in design section 13 passes.

- [ ] **Step 1: Write failing preparation tests**

Create three ready infant profiles in a temporary database with three managed canonical enrollments each. Assert:

- early creates exactly five Baby 1 episodes;
- two pattern A rows share one helpful action;
- two pattern B rows share another helpful action;
- the neutral row is unsuccessful;
- times and tags cannot decide between patterns during acoustic rehearsal;
- all seed rows say `seed` and carry visible synthetic provenance;
- rerunning is idempotent;
- mature creates exactly one sixth episode without deleting real rows.

- [ ] **Step 2: Run preparation tests and observe failure**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_prepare_care_demo -v
```

Expected: FAIL because the staged preparer does not exist.

- [ ] **Step 3: Implement staged preparation**

Use the candidate choreography:

```text
five-memory query: Baby 1 clip 02
pattern A query:    Baby 1 clip 06
pattern B query:    Baby 1 clip 04
reserved retry:     Baby 1 clip 05
```

Treat this as a candidate until fixed-rig evaluation passes. Copy only managed canonical WAV files into demo-memory storage. Do not treat raw 8 kHz corpus files as live identity evidence.

- [ ] **Step 4: Write failing evaluator tests**

Use mocked HTTP/domain responses to test every failure independently:

- cry-negative leaked to identity;
- wrong selected profile;
- early recommendation appeared;
- preview wrote an episode;
- completion wrote zero or two episodes;
- mature guidance missing;
- same action for both patterns;
- overlapping incident sets;
- cross-profile incident;
- missing audio;
- hidden score leaked;
- synthetic label missing;
- history detail crossed profile;
- fewer than five consecutive runs.

- [ ] **Step 5: Run evaluator tests and observe failure**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_care_demo_eval -v
```

Expected: FAIL because the evaluator is missing.

- [ ] **Step 6: Implement JSON and human-readable reports**

Print:

- cry-gate positive recall count;
- negative rejection count;
- confusion matrix;
- identity match count;
- early abstention;
- exactly-once completion;
- pattern A and B recommendation text;
- support incident sets;
- profile isolation;
- audio HTTP status;
- provenance;
- run-by-run result.

Never label AST or cosine values as confidence. Raw diagnostic values may appear only in a local evaluator file explicitly headed `diagnostic, not a probability`.

- [ ] **Step 7: Write the exact operator runbook**

Document:

1. fixed speaker, volume, distance, orientation, room, microphone, and browser;
2. enrollment of Baby 1, Baby 2, and Baby 3 with clips 01 to 03;
3. early snapshot;
4. non-cry checks;
5. no-suggestion capture;
6. follow-up to create memory six;
7. pattern A and B captures;
8. five complete consecutive rehearsals;
9. retry and stop rules;
10. restore procedure.

- [ ] **Step 8: Run preparation and evaluator tests**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_prepare_care_demo \
  tests.test_care_demo_eval -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/prepare_care_demo.py scripts/seed_demo_memory.py \
  tools/care_demo_eval.py tests/test_prepare_care_demo.py \
  tests/test_care_demo_eval.py docs/CARE-DEMO-RUNBOOK.md docs/MESSAGES.md
git commit -m "product workstream: add repeatable care demo gate"
```

---

### Task 8: Claude browser integration and responsive acceptance

**Files:**
- Modify by Claude only: `web/index.html`
- Modify by Claude only: `web/app.css`
- Modify by Claude only: `web/app.js`
- Modify by Claude only: `web/manifest.webmanifest`
- Modify by Claude or coordinated reviewer: `tests/test_web_client.py`
- Modify by Claude or coordinated reviewer: `tests/test_live_session_browser.mjs`

**Interfaces:**
- Consumes: every exact route and response in `docs/CLAUDE-FRONTEND-HANDOFF-CARE-DEMO.md`.
- Produces: one single-document application with Listen, History, and Baby destinations.
- Client constant: `CARE_SEGMENT_MS = 12000`.
- Client constant: `MAX_PENDING_SEGMENTS = 1`.
- The browser never composes care advice or a cause.

- [ ] **Step 1: Review Claude's static implementation against the handoff**

Before API wiring, verify all static states exist:

- ready, requesting permission, listening, paused, interrupted, connection lost, and stopped;
- no infant cry detected and cry uncertain;
- no suggestion and latched suggestion;
- structured follow-up;
- empty, loading, error, and populated History;
- full incident Overview, What was said, Context, and Evidence tabs;
- empty, loading, error, and populated Baby;
- portrait, short landscape, and desktop.

- [ ] **Step 2: Write failing browser behavior tests**

Add tests that prove:

- page navigation does not reload the document;
- one `MediaStream` survives view changes;
- each rotated blob is independently finalized before upload;
- sequence begins at 1 and increments once per accepted blob;
- only one completed blob may wait behind the in-flight request;
- elapsed time uses wall clock;
- playback is blocked while the mic is live;
- `no_cry_detected` never renders an identity, suggestion, or history card;
- the first latched recommendation never changes;
- Stop drains in-flight and one queued blob;
- incident detail keeps recorded transcript and typed follow-up separate;
- no transcript has an honest empty state.

- [ ] **Step 3: Run browser tests and observe failures**

Run:

```bash
node --check web/app.js
/private/tmp/cry-memory-py26-venv/bin/python -m unittest tests.test_web_client -v
node tests/test_live_session_browser.mjs
```

Expected: at least the new continuous-care assertions fail before integration.

- [ ] **Step 4: Wire same-origin API calls**

Use the existing `apiJson`, `apiAudio`, MIME selection, applied-setting readback, wake lock, track lifecycle, safe text rendering, playback lock, and status helpers.

Recorder rotation must:

1. retain the live stream;
2. stop the current recorder and wait for a complete blob;
3. immediately start the next recorder;
4. upload the completed blob;
5. retain at most the newest one waiting blob;
6. never use `MediaRecorder.start(timeslice)` fragments as independent files.

- [ ] **Step 5: Implement state rendering without client-authored guidance**

Render only these server fields for guidance:

```text
headline
interpretation
recommendation
evidence_summary
support_count
basis
scenarios
```

Use `textContent`. Do not paraphrase.

- [ ] **Step 6: Run responsive browser acceptance**

Run browser checks at:

```text
430 by 932
932 by 430
1440 by 900
```

Assert no horizontal overflow, visible mic state, reachable Pause or Resume and Stop, stable suggestion, navigable incident tabs, and no document reload.

- [ ] **Step 7: Commit Claude's browser work after review**

```bash
git add web/index.html web/app.css web/app.js web/manifest.webmanifest \
  tests/test_web_client.py tests/test_live_session_browser.mjs
git commit -m "product workstream: integrate continuous care browser"
```

---

### Task 9: Full verification, Windows gate, documentation, and release

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/SYSTEM-FLOW.md`
- Modify: `docs/ACCURACY-STATUS.md`
- Modify: `docs/DEMO.md`
- Modify: `docs/TASKS.md`
- Modify: `docs/MESSAGES.md`
- Modify if required: `.github/workflows/windows-backend.yml`

**Interfaces:**
- Consumes: completed Tasks 1 through 8.
- Produces: one green release commit and pushed branch.

- [ ] **Step 1: Run focused backend suites**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_cry_gate \
  tests.test_care_sessions \
  tests.test_care_history \
  tests.test_product_careflow \
  tests.test_product_session \
  tests.test_product_http_api \
  tests.test_product_e2e \
  tests.test_product_real_audio_api -v
```

Expected: PASS.

- [ ] **Step 2: Run the full Python suite**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m unittest discover -s tests
```

Expected: all tests pass, with only documented optional real-model or Windows-only skips.

- [ ] **Step 3: Run syntax and browser suites**

Run:

```bash
/private/tmp/cry-memory-py26-venv/bin/python -m compileall -q src scripts tools tests
node --check web/app.js
node tests/test_live_session_browser.mjs
```

Expected: PASS.

- [ ] **Step 4: Run the real cry-gate corpus**

Run:

```bash
IM_RUN_CRY_MODEL_TESTS=1 \
  /private/tmp/cry-memory-py26-venv/bin/python -m unittest \
  tests.test_cry_gate_real_audio -v
```

Expected: pass the frozen spike minimums and planned demo clips.

- [ ] **Step 5: Perform actual iPhone segment decode and foreground test**

On trusted HTTPS:

1. run at least three minutes;
2. collect every 12-second upload;
3. decode every blob independently with FFmpeg;
4. verify no unbounded queue;
5. verify a non-cry segment calls neither identity nor history;
6. verify Stop drains the bounded queue.

Record device, iOS, browser, room, distance, volume, segment count, decode count, and latency.

- [ ] **Step 6: Run five fixed-rig demo rehearsals**

Use `docs/CARE-DEMO-RUNBOOK.md`. Do not lower a threshold or change the rig between runs. Record the evaluator report for every run.

- [ ] **Step 7: Update architecture and accuracy documentation**

README and architecture docs must explain:

- phone to laptop data flow;
- cry gate before identity;
- identity before profile history;
- cry, time, tags, care events, caregiver speech, action, and outcome roles;
- first suggestion latch;
- transcript detail and scoped playback;
- exact automated, corpus, fixed-rig, and unproven evidence;
- conservative accuracy language;
- Windows and macOS setup;
- model download size and offline reuse.

- [ ] **Step 8: Run release hygiene checks**

Run:

```bash
git diff --check
python -c "from pathlib import Path; roots=('README.md','docs','src','tests','scripts','tools','web','.github'); files=[Path(r)] if False else []; bad=[]; [bad.append(str(p)) for r in roots for p in ([Path(r)] if Path(r).is_file() else Path(r).rglob('*')) if p.is_file() and any(c in p.read_text(encoding='utf-8', errors='ignore') for c in ('\\N{EM DASH}','\\N{EN DASH}'))]; print('\\n'.join(bad)); raise SystemExit(bool(bad))"
rg -n 'confidence|diagnos|cause|probability|score|margin' web
```

Expected: no forbidden dash characters, no client-authored cause, no confidence percentage, and no leaked diagnostic metric.

- [ ] **Step 9: Push and require Windows GitHub Actions**

Run:

```bash
git pull --rebase origin main
git push -u origin codex/continuous-care-demo
```

Require the Windows workflow to install the pinned Transformer runtime, warm or validate the cry-gate adapter without privileged symlinks, start the server, check `care.ready`, and complete a real HTTP smoke request.

- [ ] **Step 10: Mark O9 done only after evidence exists**

Set O9 to `DONE` only after:

- backend, browser, and full suites pass;
- actual iPhone blobs decode;
- five fixed-rig rehearsals pass;
- Windows Actions passes;
- Claude's UI is reviewed against every handoff state.

- [ ] **Step 11: Commit release documentation**

```bash
git add README.md docs .github/workflows/windows-backend.yml
git commit -m "product workstream: document continuous care release"
```
