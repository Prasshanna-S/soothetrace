# End-to-end Identity Memory POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a local, phone-operated proof of concept that enrolls infant and human-imitation
profiles, identifies a held-out cry with at most one retry, searches only the accepted profile's
incident history, and presents evidence-grounded guidance and playback without upstream internet.

**Architecture:** Preserve the measured Python acoustic path and place a small standard-library
HTTPS service in front of it. Identity remains acoustic-only and per-kind; a separate care-flow
orchestrator turns an accepted identity into profile-isolated scenario retrieval, deterministic
offline evidence extraction, and template-backed guidance. The iPhone client is a thin capture and
presentation layer and never computes embeddings or similarity.

**Tech Stack:** Python 3.12, SQLite, NumPy/SciPy, ffmpeg, local Whisper CLI, Python
`ThreadingHTTPServer`, iPhone Safari `MediaRecorder`, plain HTML/CSS/JavaScript, `unittest`.

## Global Constraints

- Use `mfcc87-v1` for fixed-rig infant identity and `ecapa-cryceleb-v1` for human imitation.
- Never compare or average scores from different encoder spaces.
- Normalize identity audio with one constant gain to exactly -24.00 dB RMS; reject predicted peaks
  above -1.0 dBFS.
- Identity may use acoustics only. Time, notes, outcomes, and care events never name a profile.
- A profile name appears only for `status="match"`; an uncertain result may receive one retry.
- A retry stays inside its original identity attempt and never creates a profile.
- Enrollment and query recordings must be independent; reject duplicate SHA-256 digests.
- Scenario retrieval runs only after a match and only inside the matched profile's history.
- Never separate caregiver and infant audio before fingerprinting or transcription.
- Never display cosine similarity as confidence or a percentage.
- Interventions and inferred outcomes require literal transcript evidence.
- Offline incident saving and basic guidance must work with `IM_OFFLINE=1` and no internet.
- Guidance may repeat prior recorded actions; it may not diagnose or invent a recommendation.
- Preserve raw source audio, canonical 16 kHz mono WAV, measurements, and model/config versions.
- Existing owned-file boundaries in `AGENTS.md` and `docs/TASKS.md` apply.
- Every task uses tests first, makes a scoped commit, and leaves the full suite passing.

---

## File map

### product workstream-owned additions

- `src/audio_ingest.py`: safe upload persistence, ffmpeg canonicalization, exact linear
  normalization, measurements, and stable reason codes.
- `src/guidance.py`: pure evidence selection and structured guidance payloads.
- `src/careflow.py`: matched-profile incident finalization and profile-isolated retrieval.
- `src/http_api.py`: local product HTTP service and JSON/raw-audio endpoints.
- `src/preflight.py`: deterministic demo-readiness checks and command-line exit status.
- `tests/test_product_audio_ingest.py`: ingest and normalization contracts.
- `tests/test_product_guidance.py`: evidence and non-invention contracts.
- `tests/test_product_careflow.py`: identity gate and profile isolation.
- `tests/test_product_http_api.py`: endpoint, upload, traversal, retry, and playback tests.
- `tests/test_product_e2e.py`: offline product-path acceptance with controlled fakes.

### product workstream-owned modifications

- `src/speech.py`: deterministic offline intervention and outcome extraction.
- `src/render.py`: readable identity/guidance states without numeric confidence.
- `tests/test_product_speech.py`: offline extraction coverage.
- `tests/test_product_render.py`: guidance rendering and provenance coverage.
- `docs/TASKS.md`: product workstream task claims and statuses only.
- `docs/MESSAGES.md`: append-only coordination and API handoff.

### acoustics workstream-owned work requested through `docs/MESSAGES.md`

- `src/identity.py`: adversarial fixes and frozen multi-view scorer after reference-only selection.
- `src/schema.sql`: additive `identity_attempt`, `identity_attempt_capture`, and `care_event` tables.
- `src/store.py`: care-event persistence only if the agreed boundary places it there.
- `tools/multiview_trial.py`: reference-only aggregation selection and immutable result report.
- `web/index.html`, `web/app.css`, `web/app.js`, `web/manifest.webmanifest`: phone client after the
  HTTP API stub lands.
- `tests/test_acoustics_identity.py`: identity storage/scoring regressions.

### Shared contract change requiring ACK

- `docs/CONTRACTS.md`: add identity-attempt and care-event interfaces only after both agents record
  agreement in `docs/MESSAGES.md`.

---

### Task 1: Freeze the baseline and claim implementation rows

**Files:**
- Modify: `docs/TASKS.md`
- Modify: `docs/MESSAGES.md`

**Interfaces:**
- Consumes: current 89-test repository baseline.
- Produces: non-overlapping ownership for Tasks 2-11 and a reproducible starting commit.

- [x] **Step 1: Verify the shared baseline**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
```

Expected: `Ran 89 tests` and `OK` before new tests are added.

- [x] **Step 2: Add and claim product workstream rows**

Add these rows beneath "Identity-first demo wrapper":

```markdown
| O4 | Exact managed-audio ingest and normalization | product workstream | IN_PROGRESS product workstream |
```

Add and claim later rows only when their implementation begins. Do not alter acoustics workstream-owned task
statuses.

- [x] **Step 3: Record the baseline and ownership in the inter-agent log**

Append the passing command, test count, claimed rows, and exact files product workstream will edit to
`docs/MESSAGES.md`.

- [x] **Step 4: Commit coordination state**

```bash
git add interaction-memory/docs/TASKS.md interaction-memory/docs/MESSAGES.md
git commit -m "product workstream: claim end-to-end implementation work"
```

---

### Task 2: Canonical audio ingest and exact normalization

**Files:**
- Create: `src/audio_ingest.py`
- Create: `tests/test_product_audio_ingest.py`

**Interfaces:**
- Consumes: browser-upload bytes, declared MIME, `config.AUDIO_DIR`, ffmpeg.
- Produces:
  `ingest_audio(payload: bytes, mime: str, capture_metadata: dict | None = None,
  upload_id: str | None = None) -> dict`.

The success result is:

```python
{
    "status": "ready",
    "source_path": str,
    "canonical_path": str,
    "identity_path": str,
    "sha256": str,
    "quality": {
        "duration_s": float,
        "mean_db": float,
        "peak_db": float,
        "voiced_fraction": float,
        "gain_db": float,
    },
    "capture": dict,
    "versions": {"decode": "ffmpeg-pcm16-v1", "normalization": "rms-24db-v1"},
}
```

Failure returns `{"status":"invalid","reason":<stable code>}` and never raises.

- [x] **Step 1: Write failing normalization and safety tests**

Cover:

```python
def test_ingest_normalizes_to_minus_24_db_without_changing_wave_shape(): ...
def test_ingest_rejects_normalization_that_would_peak_above_minus_1_dbfs(): ...
def test_ingest_rejects_empty_and_oversize_payloads(): ...
def test_ingest_preserves_source_and_canonical_raw_audio(): ...
def test_ingest_uses_safe_generated_names_not_client_paths(): ...
def test_ingest_returns_stable_decode_failure_reason(): ...
```

Generate short WAV fixtures with `wave` and NumPy. Patch the ffmpeg command only for decode-failure
tests; use real ffmpeg for the success contract.

- [x] **Step 2: Run the new test module and confirm failure**

```bash
.venv/bin/python -m unittest tests.test_product_audio_ingest -v
```

Expected: import failure for `src.audio_ingest`.

- [x] **Step 3: Implement safe source persistence and decode**

Use a UUID filename and a fixed MIME-to-extension allowlist. Enforce a 64 MiB maximum. Decode with:

```python
[
    "ffmpeg", "-v", "error", "-y", "-i", str(source),
    "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(canonical),
]
```

Store uploads under `config.AUDIO_DIR/managed/<uuid>/`. Do not use a client-supplied filename.

- [x] **Step 4: Implement exact one-gain normalization**

Compute:

```python
target_rms = 10.0 ** (-24.0 / 20.0)
gain = target_rms / measured_rms
predicted_peak = measured_peak * gain
```

Reject with `unsafe_normalization_headroom` when
`20 * log10(predicted_peak) > -1.0`. Otherwise multiply every sample by the same gain and write
PCM16 to `identity.wav`. Do not compress, limit, filter, or pitch-shift.

- [x] **Step 5: Run ingest tests and full regression suite**

```bash
.venv/bin/python -m unittest tests.test_product_audio_ingest -v
.venv/bin/python -m unittest discover -s tests
```

Expected: all pass.

- [x] **Step 6: Commit**

```bash
git add interaction-memory/src/audio_ingest.py interaction-memory/tests/test_product_audio_ingest.py
git commit -m "product workstream: add managed audio normalization"
```

---

### Task 3: Deterministic offline evidence extraction

**Files:**
- Modify: `src/speech.py`
- Modify: `tests/test_product_speech.py`

**Interfaces:**
- Consumes: literal Whisper transcript and `config.OFFLINE`.
- Produces the existing frozen interfaces:
  `extract_interventions(transcript: str) -> list[dict]` and
  `infer_outcome(transcript: str, interventions: list[dict]) -> dict | None`.

- [x] **Step 1: Write failing offline extraction tests**

Add:

```python
def test_offline_extracts_ordered_literal_intervention_spans(): ...
def test_offline_does_not_call_reasoning_client(): ...
def test_offline_omits_unsupported_actions(): ...
def test_offline_deduplicates_overlapping_action_matches(): ...
def test_offline_infers_positive_outcome_from_literal_span(): ...
def test_offline_negative_outcome_wins_over_positive_word_overlap(): ...
def test_offline_ambiguous_outcome_returns_none(): ...
```

Use transcripts including:

```text
"I checked her diaper, then walked with her, and she settled down."
"The bottle did not work; she is still crying."
"I wondered whether she was hungry."  # no intervention and no outcome
```

- [x] **Step 2: Verify the new tests fail**

```bash
.venv/bin/python -m unittest tests.test_product_speech -v
```

Expected: offline tests fail because extraction currently calls `_reason_json`.

- [x] **Step 3: Implement the controlled intervention vocabulary**

Define ordered regex entries for:

```python
(
    ("checked diaper", r"\b(?:checked|check|changed|change)(?:\s+\w+){0,3}\s+diaper\b"),
    ("offered feeding", r"\b(?:fed|feed|feeding|offered|gave)(?:\s+\w+){0,4}\s+(?:bottle|breast|milk)\b"),
    ("burped", r"\b(?:burped|burping|tried to burp)\b"),
    ("held", r"\b(?:held|holding|picked (?:him|her|them) up)\b"),
    ("rocked", r"\b(?:rocked|rocking)\b"),
    ("walked", r"\b(?:walked|walking)(?:\s+with)?\b"),
    ("offered pacifier", r"\b(?:pacifier|dummy|soother)\b"),
    ("swaddled", r"\b(?:swaddled|swaddling)\b"),
    ("changed environment", r"\b(?:went|moved|took)(?:\s+\w+){0,5}\s+(?:outside|room|quiet place)\b"),
)
```

Each result's `evidence` is `match.group(0)` from the original transcript. Sort by match start and
renumber from one. Reject matches inside obvious negation such as "did not try" or "never used".

- [x] **Step 4: Implement deterministic outcome fallback**

Search negative phrases before positive phrases. Return only the literal matching span:

```python
negative = r"\b(?:did not work|didn't work|still crying|still upset|nothing worked)\b"
positive = r"\b(?:settled down|stopped crying|calmed down|fell asleep|that worked)\b"
```

When both categories appear, use the last explicit outcome only if it occurs after the final
intervention evidence; otherwise return `None`.

- [x] **Step 5: Route offline mode without network**

`extract_interventions` and `infer_outcome` must call the deterministic path immediately when
`config.OFFLINE` is true. In online mode, retain the evidence-validated model path and use the
deterministic extractor only when the provider returns no valid structured evidence.

- [x] **Step 6: Run focused and full tests**

```bash
.venv/bin/python -m unittest tests.test_product_speech -v
.venv/bin/python -m unittest discover -s tests
```

- [x] **Step 7: Commit**

```bash
git add interaction-memory/src/speech.py interaction-memory/tests/test_product_speech.py
git commit -m "product workstream: add offline grounded evidence extraction"
```

---

### Task 4: Structured history-grounded guidance

**Files:**
- Create: `src/guidance.py`
- Create: `tests/test_product_guidance.py`
- Modify: `src/render.py`
- Modify: `tests/test_product_render.py`

**Interfaces:**
- Consumes: one accepted profile's `find_scenarios` results and `intervention_tally`.
- Produces:
  `build_guidance(profile_id: int, scenarios: list[dict], tally: list[dict],
  history_count: int, current_context: dict | None = None) -> dict` and
  `render.guidance_card(payload: dict) -> str`.

- [x] **Step 1: Write failing evidence-boundary tests**

Cover:

```python
def test_guidance_selects_only_final_action_from_resolved_scenarios(): ...
def test_guidance_never_uses_an_action_absent_from_history(): ...
def test_guidance_reports_support_count_and_incident_ids(): ...
def test_guidance_requires_two_supporting_incidents_for_a_pattern(): ...
def test_guidance_returns_insufficient_history_without_six_incidents(): ...
def test_guidance_does_not_turn_context_into_a_diagnosis(): ...
def test_guidance_card_omits_scores_and_percentages(): ...
```

- [x] **Step 2: Verify failure**

```bash
.venv/bin/python -m unittest tests.test_product_guidance tests.test_product_render -v
```

- [x] **Step 3: Implement pure evidence selection**

For the top three scenarios:

1. retain only `worked is True`;
2. take only the final intervention by highest integer `order`;
3. group normalized action strings;
4. rank by supporting scenario count, then `worked_last` from the tally, then first appearance;
5. require at least one supporting resolved incident;
6. include exact incident IDs and outcome provenance.

Return one of:

```python
{"status": "insufficient_history", "headline": "Not enough history yet", ...}
{"status": "no_helpful_history", "headline": "No recorded action to repeat yet", ...}
{
    "status": "grounded",
    "headline": "What helped before",
    "action": "walked",
    "support_count": 2,
    "incident_ids": [11, 7],
    "outcomes": [{"text": "she settled", "source": "caregiver"}],
    "pattern": "similar early-morning timing",  # or None
}
```

Never synthesize a new action. A time/tag pattern needs at least two supporting incidents and is
worded as a possible repeated context, not a cause.

- [x] **Step 4: Implement large-text rendering**

`guidance_card` uses only the structured payload. It prints the action, support count, outcome
source, and optional possible pattern. It never prints `similarity`, `rank_score`, or `%`.

- [x] **Step 5: Run focused and full tests**

```bash
.venv/bin/python -m unittest tests.test_product_guidance tests.test_product_render -v
.venv/bin/python -m unittest discover -s tests
```

- [x] **Step 6: Commit**

```bash
git add interaction-memory/src/guidance.py interaction-memory/src/render.py \
  interaction-memory/tests/test_product_guidance.py interaction-memory/tests/test_product_render.py
git commit -m "product workstream: add grounded personalized guidance"
```

---

### Task 5: Agree and land identity-attempt persistence

**Files:**
- Modify: `docs/MESSAGES.md`
- Modify after ACK: `docs/CONTRACTS.md`
- acoustics workstream modifies: `src/schema.sql`, `src/identity.py`, `tests/test_acoustics_identity.py`

**Interfaces:**
- Consumes: `identity.identify(audio_path, kind=None, db_path=None, audit=True) -> dict`.
- Produces:

```python
begin_identity_attempt(kind: str, candidate_profile_ids: list[int] | None = None,
                       db_path: str | None = None) -> dict
add_identity_capture(attempt_id: int, audio_path: str,
                     capture_metadata: dict | None = None,
                     db_path: str | None = None) -> dict
retry_identity_attempt(attempt_id: int, audio_path: str,
                       capture_metadata: dict | None = None,
                       db_path: str | None = None) -> dict
resolve_identity_attempt(attempt_id: int, confirmed_profile_id: int | None = None,
                         db_path: str | None = None) -> dict
get_identity_attempt(attempt_id: int, db_path: str | None = None) -> dict
session.finish(subject_id: str, audio_path: str, caregiver_answer: str | None,
               *, db_path: str | None = None) -> dict
```

- [x] **Step 1: Propose the exact additive contract**

Append the signatures above and these invariants to `docs/MESSAGES.md`:

- at most two captures;
- retry only after first `uncertain`;
- invalid capture does not consume the one retry;
- matched attempt is immutable;
- a retry reruns the frozen multi-view rule across both independent capture view sets;
- explicit confirmation may link an unresolved incident but never auto-enrolls it;
- every capture stores digest, paths, quality, ranked candidates, reason codes, and versions.
- the optional keyword-only `session.finish(..., db_path=...)` preserves the existing three
  positional arguments and makes isolated attempt/care-flow tests use one database consistently.

- [ ] **Step 2: Wait for acoustics workstream ACK before editing the frozen contract**

Expected log entry: an explicit `ACK` naming the signatures or a concrete counter-proposal.

- [ ] **Step 3: Update `docs/CONTRACTS.md` after agreement**

Bump the contract version and copy the agreed signatures and state invariants verbatim.

- [ ] **Step 4: Review acoustics workstream's schema and identity tests**

Require tables:

```sql
identity_attempt(
  id, kind, status, started_at, resolved_profile_id, resolved_at, candidate_profile_ids
)
identity_attempt_capture(
  id, attempt_id, source_audio_path, canonical_audio_path, identity_audio_path,
  audio_sha256, captured_at, capture_metadata,
  quality, result_status, ranked_candidates, reason_codes,
  encoder_version, normalization_version, calibration_version, aggregation_version
)
```

Reject the change if it overwrites an earlier capture or stores one encoder constant for every
kind. `add_identity_capture` calls identity on `identity_audio_path`; care-flow evidence and
transcription use `canonical_audio_path`.

- [ ] **Step 5: Run identity and full tests**

```bash
.venv/bin/python -m unittest tests.test_acoustics_identity -v
.venv/bin/python -m unittest discover -s tests
```

- [ ] **Step 6: Commit only product workstream-owned contract/log changes**

```bash
git add interaction-memory/docs/CONTRACTS.md interaction-memory/docs/MESSAGES.md
git commit -m "product workstream: accept identity attempt contract"
```

---

### Task 6: Care-event persistence and current context

**Files:**
- Modify: `docs/MESSAGES.md`
- Modify after ACK: `docs/CONTRACTS.md`
- acoustics workstream modifies: `src/schema.sql`, `src/store.py`, `tests/test_acoustics_core.py`
- Create: `src/context.py`
- Create: `tests/test_product_context.py`

**Interfaces:**
- Produces:

```python
store.save_care_event(profile_id: int, event_type: str, occurred_at: str,
                      details: dict | None = None, path: str | None = None) -> dict
store.list_care_events(profile_id: int, since: str | None = None,
                       path: str | None = None) -> list[dict]
context.build_current_context(profile_id: int, now: str | None = None,
                              transcript: str | None = None,
                              tags: list[str] | None = None,
                              db_path: str | None = None) -> dict
```

- [ ] **Step 1: Propose and ACK the storage signatures**

Only allow event types `feeding`, `sleep`, `diaper`, `soothing`, and `note`. Store timezone-aware
ISO timestamps and JSON details. Invalid events return `{}`.

- [ ] **Step 2: Write failing context tests**

Cover cyclic hour, feeding recency buckets, awake-time buckets, recent diaper tags, explicit input
tag deduplication, and strict profile isolation.

- [ ] **Step 3: Implement deterministic context building**

Map recency to stable tags:

```python
feeding: <2h -> "last_feed_under_2h"; 2-4h -> "last_feed_2_to_4h"; >4h -> "last_feed_over_4h"
sleep end: <2h -> "awake_under_2h"; 2-4h -> "awake_2_to_4h"; >4h -> "awake_over_4h"
diaper: <2h -> "recent_diaper"; otherwise no diaper tag
```

Return `{"hour_local": int, "tags": list[str], "care_event_ids": list[int]}`. Do not infer causes.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m unittest tests.test_product_context tests.test_acoustics_core -v
.venv/bin/python -m unittest discover -s tests
```

- [ ] **Step 5: Commit**

```bash
git add interaction-memory/src/context.py interaction-memory/tests/test_product_context.py \
  interaction-memory/docs/CONTRACTS.md interaction-memory/docs/MESSAGES.md
git commit -m "product workstream: add deterministic care context"
```

---

### Task 7: Identity-gated incident care flow

**Files:**
- Create: `src/careflow.py`
- Create: `tests/test_product_careflow.py`
- Modify: `src/session.py`
- Modify: `tests/test_product_session.py`

**Interfaces:**
- Consumes: a persisted matched identity attempt, canonical raw audio, context, `session.finish`,
  `retrieve.find_scenarios`, `retrieve.intervention_tally`, and `guidance.build_guidance`.
- Produces:

```python
complete_incident(attempt_id: int, caregiver_answer: str | None,
                  explicit_tags: list[str] | None = None,
                  db_path: str | None = None) -> dict
```

The additive session signature is:

```python
session.finish(subject_id: str, audio_path: str, caregiver_answer: str | None,
               *, db_path: str | None = None) -> dict
```

- [ ] **Step 1: Write failing identity-gate tests**

Cover:

```python
def test_unmatched_attempt_never_calls_retrieval_or_session_finish(): ...
def test_matched_attempt_uses_only_resolved_profile_subject_key(): ...
def test_scenarios_are_read_before_current_incident_is_saved(): ...
def test_saved_episode_retains_identity_attempt_and_context_provenance(): ...
def test_guidance_uses_only_same_profile_scenarios(): ...
def test_failure_returns_structured_state_without_raising(): ...
```

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/python -m unittest tests.test_product_careflow -v
```

- [ ] **Step 3: Implement the orchestration**

Use `subject_id = f"profile-{profile_id}"`. Fetch the matched attempt and its latest canonical raw
audio. Build the state fingerprint and current context. Retrieve prior scenarios before calling
`session.finish`, so the current incident cannot match itself. Build guidance from prior evidence,
passing `retrieve.episode_count(subject_id, db_path)` as `history_count`. Save the current incident,
then patch its context with:

```python
{
    **current_context,
    "identity_attempt_id": attempt_id,
    "profile_id": profile_id,
}
```

Return:

```python
{
    "status": "complete",
    "identity": {"profile_id": int, "display_name": str, "kind": str},
    "episode": dict,
    "scenarios": list,
    "guidance": dict,
}
```

- [ ] **Step 4: Run focused and full tests**

```bash
.venv/bin/python -m unittest tests.test_product_careflow -v
.venv/bin/python -m unittest discover -s tests
```

- [ ] **Step 5: Commit**

```bash
git add interaction-memory/src/careflow.py interaction-memory/src/session.py \
  interaction-memory/tests/test_product_careflow.py interaction-memory/tests/test_product_session.py
git commit -m "product workstream: add identity gated care flow"
```

---

### Task 8: Local HTTP API stub and product endpoints

**Files:**
- Create: `src/http_api.py`
- Create: `tests/test_product_http_api.py`
- Modify: `docs/MESSAGES.md`

**Interfaces:**
- Consumes: `audio_ingest`, `identity`, `careflow`, `store`, and static assets under `web/`.
- Produces: `build_http_server(address, data_root, static_root, db_path=None)` and these endpoints:

```text
GET  /api/health
GET  /api/profiles
POST /api/profiles
POST /api/profiles/{id}/enroll
POST /api/identity/attempts
POST /api/identity/attempts/{id}/captures
POST /api/identity/attempts/{id}/retry
POST /api/incidents/{attempt_id}/complete
POST /api/care-events
GET  /api/audio/enrollments/{id}
GET  /api/audio/episodes/{id}
DELETE /api/profiles/{id}
DELETE /api/episodes/{id}
```

Audio upload endpoints receive the raw blob body with `Content-Type` set to its MIME. JSON
endpoints use UTF-8 JSON. Every response is JSON except safe audio playback.

- [ ] **Step 1: Write failing HTTP contract tests**

Use an ephemeral loopback server and cover:

- content-length and 64 MiB enforcement;
- unsupported MIME;
- malformed JSON;
- no path traversal or client filename use;
- profile creation validation;
- enrollment calls managed ingest before identity enrollment;
- first uncertain capture permits retry;
- second uncertain capture returns unresolved;
- matched capture exposes a profile but no raw score;
- incident completion is blocked for unmatched attempts;
- playback can access only database-owned managed files;
- profile and episode deletion remove database rows and managed audio without touching source files
  outside the managed root;
- CSP, `Cache-Control:no-store`, `nosniff`, and no permissive CORS.

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/python -m unittest tests.test_product_http_api -v
```

- [ ] **Step 3: Implement product storage and routing**

Reuse the tested request-size and safe-static-serving patterns from
`spikes/mobile_capture/server.py`, but do not import spike state. Serialize inference with one
process-local lock. Never trust a path or profile label from an audio request.

- [ ] **Step 4: Add the health payload**

Return:

```python
{
    "status": "ready" | "degraded",
    "offline": bool,
    "ffmpeg": bool,
    "whisper": bool,
    "database": bool,
    "population_baseline": bool,
    "encoders": {"infant": bool, "human_imitation": bool},
    "capture": {"https_required": True, "max_upload_bytes": 67108864},
}
```

- [ ] **Step 5: Publish the exact API to acoustics workstream**

Append endpoint request/response examples and the API stub commit hash to `docs/MESSAGES.md`.
Explicitly hand off `web/` to acoustics workstream at this point.

- [ ] **Step 6: Run focused and full tests**

```bash
.venv/bin/python -m unittest tests.test_product_http_api -v
.venv/bin/python -m unittest discover -s tests
```

- [ ] **Step 7: Commit**

```bash
git add interaction-memory/src/http_api.py interaction-memory/tests/test_product_http_api.py \
  interaction-memory/docs/MESSAGES.md
git commit -m "product workstream: add local product API"
```

---

### Task 9: Phone client and hands-free states

**Files (acoustics workstream-owned):**
- Create: `web/index.html`
- Create: `web/app.css`
- Create: `web/app.js`
- Create: `web/manifest.webmanifest`
- Create: `tests/test_web_client.py`

**Interfaces:**
- Consumes: Task 8 endpoints exactly.
- Produces: iPhone Safari enrollment, query/retry, matched-care, playback, and failure states.

- [ ] **Step 1: Write static client contract tests**

Require:

- `viewport-fit=cover`;
- `apple-mobile-web-app-capable`;
- standalone manifest;
- 44 px minimum targets;
- `role=status` and `aria-live`;
- mic constraints disabling echo cancellation, noise suppression, and AGC;
- MIME probing with MP4/AAC first;
- no similarity/percentage rendering;
- state copy for listening, processing, matched, retry, unresolved, invalid, and offline;
- only one retry button;
- visible consent before first capture.

- [ ] **Step 2: Implement the state machine**

Use explicit states:

```javascript
const STATES = Object.freeze({
  HOME: "home", ENROLL: "enroll", LISTENING: "listening",
  PROCESSING: "processing", MATCHED: "matched", RETRY: "retry",
  UNRESOLVED: "unresolved", CARE: "care", COMPLETE: "complete", ERROR: "error"
});
```

One recording action produces one blob. The phone records; playback sources come from a different
device during identity trials.

- [ ] **Step 3: Implement stable long-distance care display**

The main result text remains large and stable. Put pause/stop/playback controls below it. Do not
replace the result on every recorder event or timer tick.

- [ ] **Step 4: Run static and Safari smoke tests**

```bash
.venv/bin/python -m unittest tests.test_web_client -v
```

Then run one real iPhone enrollment and one real identity query over trusted HTTPS.

- [ ] **Step 5: acoustics workstream commits and reports the hash**

Commit message:

```text
acoustics workstream: build phone identity and care client
```

product workstream reviews the result against API and accessibility tests before accepting.

---

### Task 10: Offline end-to-end acceptance harness

**Files:**
- Create: `tests/test_product_e2e.py`
- Create: `src/preflight.py`
- Create: `docs/END-TO-END-RESULTS-2026-07-29.md`

**Interfaces:**
- Consumes: all product modules and HTTP endpoints.
- Produces: one command that proves the provisioned demo can run without upstream internet.

- [ ] **Step 1: Write the failing acceptance test**

The test must:

1. create two infant profiles and two imitation profiles;
2. enroll independent controlled fixtures;
3. start an identity attempt;
4. return match or one retry, never the wrong profile;
5. seed six prior incidents for the accepted infant;
6. complete a matched incident;
7. assert scenario IDs belong only to that profile;
8. assert guidance action and provenance exist in stored history;
9. fetch supporting audio;
10. patch all network-capable clients to raise and keep the path passing.

Acoustic encoders may be controlled fakes in this contract test; separate measured trials validate
the real models.

- [ ] **Step 2: Verify failure**

```bash
IM_OFFLINE=1 .venv/bin/python -m unittest tests.test_product_e2e -v
```

- [ ] **Step 3: Implement preflight checks**

`src.preflight` reports pass/fail for:

- Python 3.12 virtual environment;
- ffmpeg;
- local Whisper executable and provisioned `base.en` model;
- database writable and backed up;
- population baseline;
- both identity encoders load;
- TLS cert/key exist and are not expired;
- phone and server clock skew under two minutes when a phone heartbeat exists;
- at least two ready presentation profiles;
- at least six usable incidents for the care-demo infant;
- no mixed encoder versions within a profile;
- no duplicate enrollment digests;
- `IM_OFFLINE=1`.

Exit nonzero on a load-bearing failure.

- [ ] **Step 4: Run with network denied**

Run:

```bash
IM_OFFLINE=1 .venv/bin/python -m unittest tests.test_product_e2e -v
IM_OFFLINE=1 .venv/bin/python -m src.preflight
```

Also disable Wi-Fi/upstream connectivity for the real-phone pass while retaining the local
phone-to-laptop network.

- [ ] **Step 5: Record actual results**

Write exact commands, timestamps, device path, duration, identity outcome, retry outcome, incident
IDs, transcript runtime, total runtime, and failures to
`docs/END-TO-END-RESULTS-2026-07-29.md`. Do not report a controlled-fake result as model accuracy.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/python -m unittest discover -s tests
git add interaction-memory/tests/test_product_e2e.py interaction-memory/src/preflight.py \
  interaction-memory/docs/END-TO-END-RESULTS-2026-07-29.md
git commit -m "product workstream: verify offline end-to-end demo"
```

---

### Task 11: Real acoustic controls, demo pack, and final adversarial review

**Files:**
- Modify: `docs/END-TO-END-RESULTS-2026-07-29.md`
- Create: `docs/DEMO-RUNBOOK.md`
- Modify: `docs/MESSAGES.md`

**Interfaces:**
- Consumes: frozen models, aggregation, thresholds, presentation phone path, replay master, and
  completed app.
- Produces: a reproducible presentation database, runbook, and honest claim ledger.

- [ ] **Step 1: Complete the matched replay-master control**

Run the rig check, play `data/audio/replay_master/REPLAY-MASTER.wav` once from the fixed MacBook
speaker, record the whole take on the presentation phone, split by the frozen manifest, and run:

```bash
.venv/bin/python tools/imitation_trial.py analyse
```

Do not write calibration on the first run.

- [ ] **Step 2: Run prospective real queries**

After every rule is frozen, run held-out infant and human-imitation queries. Reveal labels only
after the result is persisted. Record correct, wrong, uncertain, invalid, and retry separately.
The acceptance target is zero wrong profile names.

- [ ] **Step 3: Seed and back up the presentation state**

Enroll every presentation profile through the phone path. Seed at least six independent incidents
for the care-demo infant. Back up `data/episodes.db` and the managed audio tree to a timestamped
demo-backup directory; validate restore into a temporary path.

- [ ] **Step 4: Write the runbook**

Include:

- launch command and HTTPS URL;
- certificate and hotspot checks;
- offline model check;
- exact speaker location, distance, and volume;
- enrollment script;
- visitor-imitation script;
- infant recognition script;
- personalized care-memory script;
- recovery for quiet audio, retry, server disconnect, and unresolved identity;
- explicit claims and non-claims;
- database reset and restore.

- [ ] **Step 5: Request acoustics workstream's adversarial semantic review**

acoustics workstream reviews every `DONE` row for:

- a wrong name hidden behind a "weak" band;
- cross-profile history leakage;
- ungrounded intervention or outcome;
- network dependence;
- self-match or duplicate audio;
- UI copy implying diagnosis or probability;
- an untested fixed-rig assumption presented as general accuracy.

- [ ] **Step 6: Fix every reproducible issue and rerun verification**

```bash
IM_OFFLINE=1 .venv/bin/python -m unittest discover -s tests
IM_OFFLINE=1 .venv/bin/python -m src.preflight
```

- [ ] **Step 7: Commit the verified demo pack**

```bash
git add interaction-memory/docs/DEMO-RUNBOOK.md \
  interaction-memory/docs/END-TO-END-RESULTS-2026-07-29.md \
  interaction-memory/docs/MESSAGES.md interaction-memory/docs/TASKS.md
git commit -m "product workstream: finalize verified identity memory demo"
```

---

## Completion gate

Do not call the POC complete until all of the following are simultaneously true:

- the full automated suite passes from a clean process;
- offline extraction makes no network call;
- phone capture, upload, decode, identity, retry, scenario retrieval, incident saving, guidance,
  and playback have one real end-to-end pass;
- all rules were frozen before prospective labels were revealed;
- every named match is correct in the frozen acceptance run;
- unresolved audio creates neither a name nor a profile;
- guidance cites stored incident IDs and contains no unsupported action;
- the presentation database can be restored from its backup;
- acoustics workstream's adversarial review has no open load-bearing defect.
