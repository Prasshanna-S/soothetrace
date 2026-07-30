# Identity-first hands-free cry memory demo

> **Superseded:** This proposal is retained for history. The approved, measured end-to-end design
> is `docs/superpowers/specs/2026-07-29-end-to-end-identity-memory-design.md`.

**Status:** superseded
**Date:** 2026-07-29
**Product owner:** Prasshanna
**Acoustic design and validation:** acoustics workstream
**Orchestration, continuous capture, contextual guidance, playback, and verification:** product workstream

## 1. Outcome

Build a fully functional local proof of concept that can:

1. enroll a visitor's performed cry imitation and later recognize another imitation as matching
   that visitor's enrolled profile;
2. enroll multiple known infants from recordings played through the MacBook into the phone
   microphone and identify which
   enrolled infant produced a held-out cry;
3. reject an unrecognized or ambiguous source instead of forcing a label;
4. support multiple session modes, including a continuous hands-free listening mode after one
   deliberate activation;
5. only after identity is accepted, retrieve similar prior episodes for that identity using a
   transparent combination of cry acoustics and contextual information;
6. show one large, readable suggestion for what the caregiver could try next, grounded in that
   baby's own caregiver-reported history;
7. show a carefully framed possibility for what the pattern could mean when repeated history,
   time, and caregiver notes support it;
8. keep prior-audio playback available as secondary evidence rather than the primary result.

The public claim is:

> This recording is acoustically consistent with an enrolled cry profile. Similar episodes in
> this baby's own history suggest an action that previously helped. A possible pattern is shown
> only when the available time, notes, and repeated history support it.

The public claim is not:

- a medical diagnosis;
- a determination of hunger, pain, or another cause from cry tonality alone;
- biometric proof of legal identity;
- a promise that one arbitrary cry can identify every infant;
- a probability derived from cosine similarity.

## 2. Demonstration

### 2.1 Visitor imitation

1. The operator creates a named `human_imitation` profile.
2. The visitor performs one 5-10 second cry imitation into the phone microphone.
3. The profile is provisional after the first usable enrollment.
4. The visitor performs a second, independently captured imitation.
5. The system returns one of:
   - `matches <name>'s enrolled imitation profile`;
   - `uncertain - try again`;
   - `new or unenrolled source`.
6. A successful result can play the first enrollment as supporting evidence.
7. A third imitation may be used as a clean query after the two enrollments have made the
   profile ready.

The product copy says "matches the enrolled imitation profile," not "proves this person's
identity."

### 2.2 Infant identity with blind reveal

1. The operator enrolls at least two different recordings for `Baby A`.
2. The operator enrolls at least two different recordings for `Baby B`.
3. Every recording is played from the same MacBook through the same iPhone browser microphone.
4. A held-out recording is selected without showing its infant ID in the prediction view.
5. The system predicts `Baby A`, `Baby B`, or `uncertain`.
6. The nearest supporting enrollment recording is available as supporting evidence.
7. Only after prediction is frozen does the operator reveal the dataset infant ID.

Enrollment and query recordings for an infant must be different source recordings, not
compressed or volume-adjusted copies of the same file, for the main identity proof.

### 2.3 One session type: hands-free care

1. The caregiver selects or confirms the baby's profile and taps **Start listening**.
2. The caregiver places the phone on the bed or another safe nearby surface.
3. The phone continues recording while the caregiver picks up the baby and moves around.
4. The system keeps a rolling buffer, detects usable cry events, and processes caregiver speech
   from the same raw mixed audio.
5. Stable cry events and contextual changes update the current episode memory.
6. The caregiver does not have to type, hold the phone, or repeatedly press controls.
7. The main screen shows one large guidance message readable from across the room.
8. Pause, stop, and supporting-audio controls remain small and lower on the screen.
9. The main guidance changes only when a stable new decision replaces the previous one; it does
   not flicker on every audio chunk.

The target and presentation experiences record on the phone. Existing MacBook-microphone
recordings remain useful as backend reference data, but they cannot seed the phone demo because
cross-channel matching has already failed.

### 2.4 Personalized guidance and scenario memory

After identity is accepted, the system searches only that profile's episodes. It shows:

- one primary action the caregiver could try;
- a short evidence line describing when that action previously helped;
- a possible pattern only when repeated notes/time/history support it;
- which available signals influenced its ranking;
- caregiver notes and interventions grounded in the prior transcript;
- the caregiver-reported outcome and its provenance;
- the prior recording as optional supporting evidence.

An action recommendation must come from this profile's prior transcript-grounded interventions
and caregiver-reported outcomes. It is phrased as "try" or "previously helped," never as a
guarantee.

A possibility such as "feeding-time pattern" or "possibly overtired" must come from repeated
caregiver notes/tags and contextual history. Cry acoustics may select similar episodes but cannot
create a cause label. With insufficient support, the UI says:

> No reliable pattern yet. Keep listening and add a note when you can.

### 2.5 Session framework

Hands-free care is one mode in a common session framework:

| mode | purpose | interaction |
|---|---|---|
| `identity_enrollment` | teach the system an infant or imitation profile | short guided captures |
| `identity_query` | identify a held-out or live cry | short capture, result, optional blind reveal |
| `hands_free_care` | listen while the caregiver moves with the baby | one activation, continuous event processing |
| `episode_review` | review what was heard, tried, and reported | history, notes, outcomes, optional playback |

Future modes may reuse the same event and evidence contracts without changing identity semantics.
The presentation should describe the hands-free flow as a flagship interaction, not the only way
to use the system.

## 3. Two-stage architecture

Identity and scenario retrieval are separate decisions.

```text
phone or MacBook microphone capture
          |
          v
rolling session + capture validation
          |
          v
WHO: acoustic-only profile matching
     | match                       | uncertain/invalid
     v                             v
accepted profile             stop with retry guidance
     |
     v
EVENT STREAM: usable cry windows + caregiver speech from raw mixture
     |
     v
WHAT HELPED BEFORE: rank only this profile's episodes
     cry acoustics + time + gap + duration + current notes/tags
     |
     v
large action guidance + possible pattern + reported provenance
     |
     v
optional supporting episode and audio playback
```

Time, notes, duration, outcomes, and scenario labels must never influence identity. This
prevents contextual leakage from making identity appear more accurate than it is.

## 4. Capture and normalization

### 4.1 Target hands-free path

The target wrapper runs a continuous session on the phone:

- one explicit activation starts listening;
- the phone can be placed down while the caregiver moves with the baby;
- a rolling buffer is analyzed in bounded chunks;
- cry-event detection and transcription operate on the same raw mixture;
- relevant event clips and decisions are stored with timestamps;
- non-event rolling audio is not retained after the session unless the caregiver explicitly
  saves the full session.

The session must tolerate changing source distance and level as the caregiver moves. Capture
quality is measured per event. The identity model spike must therefore test level variation and
must not select a model whose decision depends on the narrow level boundary found in round 2.

### 4.2 Mobile web presentation path

The presentation client is a mobile web app opened on the iPhone:

- the iPhone browser records;
- infant recordings are played from the MacBook;
- visitors perform imitations directly into the iPhone;
- no third device and no file handoff are required;
- browser audio is uploaded over HTTPS to the local Python server on the MacBook;
- the verified Python backend performs decoding, embeddings, retrieval, storage, and guidance;
- no fingerprint or identity algorithm is reimplemented in JavaScript.

The browser requests:

```text
echoCancellation: false
noiseSuppression: false
autoGainControl: false
```

The wrapper records the values actually applied by `MediaStreamTrack.getSettings()` because iOS
Safari may ignore a requested constraint. It feature-detects the supported `MediaRecorder` MIME
type and verifies that ffmpeg can decode the uploaded result.

Phone microphone access requires HTTPS. The offline presentation uses a locally served
certificate trusted by the iPhone; a plain LAN HTTP address is not accepted. All model weights
are cached, so the HTTPS path must work without venue internet.

Every presentation enrollment and query is captured through this same phone-browser path.
Playing and recording on the same iPhone is forbidden because iOS suppressed its own speaker
feed in the measured J4 test.

### 4.3 Backend reference rig

The already verified reference data used the MacBook microphone:

- infant recordings were played from the iPhone;
- visitors or caregiver speech were captured directly;
- no third device was required.

The verified infant playback rig is:

- capture: MacBook Pro Microphone, currently AVFoundation `:1`;
- playback: iPhone 17 Pro Max;
- playback volume: 100%;
- distance: approximately 15 cm;
- Mac input gain: 46;
- storage format: 16 kHz mono PCM WAV.

This rig remains useful for algorithm comparison and regression testing. It is not mixed into
phone-browser profiles. CLI capture validates the friendly device name rather than blindly
trusting index `:1`, because AVFoundation indices may change.

### 4.4 Capture preflight

Before enrollment, query, or a continuous session, the wrapper verifies:

- the expected phone or CLI microphone path is selected;
- HTTPS, permission, and applied browser audio settings are healthy for mobile sessions;
- captured audio is nonempty;
- duration is within the configured range;
- voiced audio exceeds the minimum required for every selected encoder;
- mean and peak levels are inside the accepted envelope;
- clipping, near-silence, and missing model weights produce an actionable retry state;
- model and fingerprint versions are recorded with the capture.

During a continuous session, the same checks run per candidate event. Invalid chunks do not erase
the last stable guidance; the status changes to `listening for a clearer cry`.

### 4.5 Raw audio integrity

- Managed event WAVs are retained for audit and optional evidence playback.
- A SHA-256 digest is stored for each managed capture.
- Enrollment and query captures are always distinct files.
- The query is excluded from its own candidate set.
- Caregiver/infant mixtures are never source-separated before episode fingerprinting or
  transcription.
- Identity demonstrations use cry-only playback or imitation captures so caregiver speech does
  not become an identity shortcut.

## 5. Identity subsystem

### 5.1 Candidate encoders

The model spike compares:

1. the existing 87-dimensional engineered fingerprint;
2. `Ubenwa/ecapa-voxceleb-ft2-cryceleb`, an ECAPA-TDNN checkpoint fine-tuned for infant cry
   speaker verification;
3. `speechbrain/spkrec-ecapa-voxceleb`, an adult speaker embedding model for visitor
   imitations;
4. a general audio representation such as BEATs only if it improves the source-type guard or
   unknown rejection;
5. calibrated ensembles of the above.

A candidate is selected by measured held-out performance and latency, not by a model card or a
single convincing pair.

All selected weights are downloaded, pinned, checksummed, and cached before presentation. The
demo must run without internet after startup.

### 5.2 Source-type guard

The source-type guard can return:

- `infant_cry`;
- `human_imitation_or_other_vocalization`;
- `uncertain`.

Its purpose is to choose the appropriate calibrated identity family and reject irrelevant audio.
It does not diagnose cause and does not identify a person or infant by itself.

If the guard is uncertain, both identity families may be evaluated, but the final result must
still satisfy the identity acceptance and runner-up margin rules.

### 5.3 Profile representation

Each usable enrollment stores:

- a managed audio path and digest;
- one embedding per selected encoder;
- optional window-level embeddings;
- source type;
- capture quality measurements;
- capture and model version metadata.

A profile is the set of its independent enrollments. It is not represented by only its most
recent clip.

### 5.4 Matching

For each candidate profile:

1. compare the query to every independent enrollment with the appropriate calibrated encoder;
2. aggregate scores robustly across enrollments so one anomalous clip cannot dominate;
3. compute the closest supporting enrollment;
4. apply an absolute acceptance threshold calibrated from same-source and impostor trials;
5. compare the top profile with the runner-up using a separately calibrated margin;
6. return a match only when both gates pass.

Exact aggregation, score normalization, thresholds, and ensemble weights are outputs of the
model spike owned by acoustics workstream. They are versioned configuration, never hard-coded presentation
magic.

### 5.5 Human-facing identity result

```text
status:       match | uncertain | invalid
profile:      profile id and display label, only when status=match
band:         strong | weak | none
source_type:  infant_cry | human_imitation_or_other_vocalization | uncertain
support:      nearest enrollment id and playable managed-audio path
reasons:      stable reason codes, not generated prose
versions:     encoder and calibration versions
```

Raw cosine values and probability-like percentages are debug-only. The wrapper renders bands and
plain-language evidence.

## 6. Contextual episode ranking and guidance

Scenario ranking runs only after identity returns `match`.

### 6.1 Inputs

- acoustic similarity to prior episodes from the accepted profile;
- cyclic time-of-day similarity;
- time since the prior/current episode;
- episode duration similarity;
- overlap with current caregiver notes or selected tags.

Prior interventions and outcomes are attached to results but do not increase a prior episode's
rank. This avoids preferentially retrieving a story merely because it had a desirable outcome.

### 6.2 Initial auditable weighting

The proof-of-concept default is:

| component | weight |
|---|---:|
| cry acoustic similarity | 0.55 |
| time of day | 0.15 |
| current notes/tags | 0.15 |
| duration | 0.10 |
| time since previous episode | 0.05 |

Missing components are omitted and the remaining weights are renormalized. These are explicit
product weights, not learned medical claims. The validation report must show how changing each
available component changes ranking.

The existing acoustic confidence band remains separate from the composite scenario rank.
Composite ranking does not turn cosine into a probability.

### 6.3 Explanation

Each scenario result includes deterministic contribution labels such as:

- `cry pattern was the strongest available signal`;
- `occurred at a similar time of day`;
- `caregiver notes shared: overtired`;
- `episode duration was similar`;
- `gap since the previous episode was similar`.

Generated prose may paraphrase these labels for presentation, but the labels and values are the
source of truth.

### 6.4 What the caregiver could try

The guidance engine derives actions only from identity-gated personal history:

1. rank the accepted profile's prior episodes;
2. consider only transcript-grounded interventions in the top relevant episodes;
3. treat the final action in a caregiver-reported resolved episode as the probable successful
   action, using the existing `worked_last` attribution;
4. prefer actions that helped repeatedly in relevant episodes;
5. display one primary action at a time;
6. attach the number and provenance of supporting episodes.

Example:

> **Try rocking and holding close**
>
> Rocking was the final reported action in 2 similar evening episodes that settled.

This is a personalized memory aid, not proof that the action will work now. When no
caregiver-reported action is sufficiently supported, the main message is:

> **No personal pattern yet**
>
> Keep listening. You can add what helped after this episode.

Existing safety guidance for prolonged or repeatedly unresolved episodes remains higher priority
than a historical action suggestion.

### 6.5 What the pattern could mean

The system may show one `possible pattern` only when it is supported by repeated, identity-gated
history:

- repeated caregiver note/tag language;
- a repeated time-of-day pattern;
- consistent episode timing or duration;
- similar acoustic episodes whose caregiver notes agree.

The displayed possibility is derived from caregiver language or explicit tags, not invented from
audio. It uses wording such as:

> **Possible feeding-time pattern**
>
> Similar cries happened near this time on 3 evenings, and 2 caregiver notes mentioned feeding.

If evidence disagrees or appears only once, no meaning label is shown. Acoustic identity and
similarity can retrieve evidence; neither is allowed to produce a medical or causal label.

## 7. Storage

### 7.1 Profile

```text
id
display_name
kind: infant | human_imitation
status: provisional | ready | archived
created_at
```

### 7.2 Enrollment

```text
id
profile_id
audio_path
audio_sha256
captured_at
duration_s
capture_device_name
capture_quality
source_type
embedding_versions
embeddings
```

### 7.3 Identity query audit

```text
id
audio_path
audio_sha256
captured_at
result_status
matched_profile_id
supporting_enrollment_id
band
reason_codes
encoder_versions
calibration_version
```

### 7.4 Dataset ground truth

Dataset infant IDs used in evaluation live in a separate evaluation manifest. They are not
available to the product matcher or prediction view. The reveal view reads the manifest only
after the prediction has been stored.

### 7.5 Session, event, and guidance audit

```text
Session
  id
  mode
  profile_id
  started_at
  stopped_at
  capture_path
  applied_audio_settings

Event
  id
  session_id
  started_at
  duration_s
  managed_audio_path
  capture_quality
  identity_result_id
  transcript
  extracted_interventions
  context

GuidanceDecision
  id
  session_id
  event_id
  created_at
  action_text
  action_support_episode_ids
  possibility_text
  possibility_support_episode_ids
  contribution_reason_codes
  safety_override
  model_and_rule_versions
```

Every displayed action or possibility can therefore be traced to the episodes and caregiver
evidence that produced it.

## 8. Service boundary for the wrapper

The domain service exposes UI-independent operations:

```text
create_profile(display_name, kind) -> Profile
capture_audio(purpose, seconds) -> ManagedCapture | CaptureError
enroll(profile_id, capture_id) -> EnrollmentResult
identify(capture_id) -> IdentityResult
start_session(mode, profile_id=None) -> Session
ingest_event(session_id, capture_id, observed_context) -> EventResult
get_current_guidance(session_id) -> GuidanceDecision
pause_session(session_id) -> Session
resume_session(session_id) -> Session
stop_session(session_id) -> SessionSummary
add_episode(profile_id, capture_id, context, caregiver_answer) -> Episode
find_scenarios(profile_id, capture_id, current_context, k) -> ScenarioResult[]
get_playback(recording_id) -> ManagedAudio
delete_profile(profile_id) -> DeletionResult
```

The CLI and later web UI must call the same domain service. The wrapper must not reimplement
matching in JavaScript or in presentation code.

Playback paths are resolved by recording ID; clients never supply arbitrary filesystem paths.

## 9. Presentation views and interaction

The minimum wrapper has five functional views:

1. **Readiness:** HTTPS, microphone permission/settings, level, model cache, and offline status.
2. **Enroll:** select infant or imitation, name the profile, capture two or more examples, and
   play each managed recording.
3. **Identify:** capture a held-out query, show match/uncertain, show the closest evidence
   recording, and play it.
4. **Hands-free care:** one start action followed by continuous listening and large stable
   guidance.
5. **Episode review:** show identity-gated episode evidence, transcript-grounded interventions,
   caregiver outcome provenance, notes, and optional audio playback.

The identity card uses:

> Matches Baby A's enrolled cry profile

or:

> Uncertain - this recording is not separated enough from the enrolled profiles. Try again.

The guidance screen uses:

> **Try rocking and holding close**
>
> Previously helped in 2 similar evening episodes.
>
> Possible pattern: overtired.

The primary action occupies most of the screen and is readable from across the room. Status and
evidence use shorter secondary text. Pause, stop, and optional supporting-audio controls stay
near the bottom inside safe-area insets.

The screen does not animate or replace the primary message for every chunk. A new decision must
remain stable across the configured evidence window before replacing the current guidance.
Listening/processing progress changes without moving the primary controls.

## 10. Validation

### 10.1 Model comparison

The spike produces, for every candidate encoder and ensemble:

- same-source and different-source score distributions;
- ROC-AUC and equal-error rate where appropriate;
- closed-set profile accuracy;
- unknown false-accept and known false-reject counts;
- confusion matrix;
- per-profile leave-one-recording-out results;
- p50 and p95 inference latency on the M2 Pro;
- model size and offline startup time.

### 10.2 Infant trials

- Use infants with at least three genuinely different recordings.
- Enroll with two recordings and hold out at least one.
- Never split or augment one file into both enrollment and query for the main result.
- Run corpus-direct, existing iPhone-to-Mac reference, and final MacBook-to-phone-browser
  evaluation separately.
- Include at least eight different-infant live impostor queries already captured in round 2.
- Report channel conditions with every live result.

### 10.3 Human-imitation trials

- Enroll at least two people who each perform independent imitations.
- Use at least two enrollment attempts and one held-out query per person.
- Include an unenrolled visitor and require `uncertain/new`, not the nearest forced label.
- Keep all presentation human trials on the same direct-to-phone capture path so identity cannot be inferred
  from different devices.

### 10.4 Stage-roster acceptance

Before visual design and polish, the exact stage roster must pass three consecutive clean runs
through the minimal phone capture interface:

- phone-web Prasshanna imitation query identifies Prasshanna's enrolled imitation profile;
- a MacBook-played Baby A held-out recording captured by the phone identifies Baby A;
- a MacBook-played Baby B held-out recording captured by the phone identifies Baby B;
- a live or recorded unknown source returns uncertain;
- every successful match plays the correct nearest supporting enrollment;
- query recordings are absent from their own reference set;
- no result uses dataset ground truth before the reveal;
- p95 post-capture identity latency is no more than five seconds;
- the full loop works with venue internet disabled after local models are cached;
- every enrollment and query in a run uses the same phone-browser capture path.

Stage-roster success is proof that the PoC demonstration is repeatable. It is not reported as
population-level identification accuracy; the broader validation metrics remain visible.

### 10.5 Scenario acceptance

- Identity filtering occurs before episode ranking.
- No episode from another identity can appear.
- With acoustics fixed, controlled time/note changes alter ranking according to documented
  weights.
- Missing context renormalizes weights and does not crash.
- The displayed prior intervention has transcript evidence.
- Caregiver outcomes display `caregiver`, `inferred`, or `seed` provenance explicitly.
- A seed outcome is never presented as caregiver-reported.

### 10.6 Mobile web acceptance

- A certificate trusted on the iPhone provides HTTPS without venue internet.
- Safari and the Add-to-Home-Screen app both obtain microphone permission.
- Requested and applied audio-processing settings are displayed in readiness diagnostics.
- A supported browser recording MIME type uploads and decodes through ffmpeg.
- The Python backend receives every uploaded event; matching is never reimplemented client-side.
- Playing and recording on the same iPhone is blocked by presentation instructions.
- All presentation profiles are re-enrolled through the phone; Mac-reference episodes are never
  mixed into phone profiles.

### 10.7 Continuous and guidance acceptance

- One activation starts a hands-free session; no further touch is required for at least one
  complete guidance cycle.
- The phone continues processing while placed down and the caregiver moves with the sound source.
- Clear cry events become managed event clips; silence and unusable chunks do not become episodes.
- Caregiver speech is transcribed from the same mixed event audio and interventions retain
  transcript evidence.
- The current guidance remains visible through invalid or ambiguous chunks.
- A replacement action appears only after its evidence is stable; the primary text does not
  flicker between recommendations.
- Every action is backed by caregiver-reported resolved episodes for the accepted profile.
- Every displayed possibility is backed by repeated caregiver notes/tags and context.
- Conflicting or one-off meaning evidence yields no possibility label.
- A prolonged/repeatedly unresolved safety message overrides ordinary historical guidance.
- Optional playback controls do not displace the primary action or require the caregiver to hold
  the phone.

## 11. Failure behavior

| condition | behavior |
|---|---|
| wrong or missing microphone | block capture and name the expected device |
| silence or too little voiced audio | discard query result and request another capture |
| clipping or excessive noise | mark invalid and show corrective guidance |
| one enrollment only | profile remains provisional; second capture is requested |
| close top profiles | return uncertain |
| no profile clears threshold | return new/unenrolled source |
| identity model unavailable | block identity claim; do not fall back to raw cosine |
| transcription/network unavailable | identity and acoustic retrieval continue locally; text fields degrade visibly |
| supporting audio missing | show integrity error; never substitute another recording |
| phone audio constraints ignored | surface applied settings and block strict demo acceptance |
| local HTTPS unavailable | block mobile capture and show certificate/network guidance |
| temporary unclear event during listening | retain prior guidance and show `listening for a clearer cry` |
| no supported personal action | show `No personal pattern yet`; do not invent advice |
| no repeated meaning evidence | omit the possibility label |
| connection to local server drops | keep the session state visible and retry queued upload without fabricating a result |

## 12. Privacy, consent, and licensing

- Audio only; never video.
- Explicit consent is required before recording a visitor.
- Managed audio, embeddings, and query audits are stored locally.
- Deleting a profile deletes its recordings, embeddings, episodes, and query links.
- Models are downloaded before the event and their licenses are recorded.
- The Ubenwa checkpoint is CC-BY-SA-4.0 and the CryCeleb dataset is
  CC-BY-NC-ND-4.0. Dataset audio is not redistributed. Before distributing a commercial
  wrapper, model share-alike obligations and dataset restrictions require a dedicated license
  review.
- SpeechBrain's adult ECAPA checkpoint is Apache-2.0.

## 13. Ownership and contract change

Proposed ownership:

- acoustics workstream: encoder adapters, embedding generation, identity score calibration, acoustic
  aggregation, identity acceptance, and acoustic validation.
- product workstream: capture orchestration, managed recording lifecycle, profiles, query audit,
  identity-result rendering, contextual feature preparation, deterministic scenario explanation,
  personalized guidance, session-mode orchestration, playback, CLI/API flow, mobile HTTPS
  verification, and end-to-end verification.

The frozen contract must be updated and acknowledged before implementation because identity
embeddings, profiles, and composite scenario queries introduce new cross-agent data shapes.

Neither agent modifies the existing episode-memory banding semantics to simulate identity.

## 14. Implementation order

1. acoustics workstream and product workstream agree on identity data shapes and file ownership.
2. Run the isolated model/dependency spike and select encoders from measured results.
3. Implement profile/enrollment storage and managed capture.
4. Implement identity matching with unknown rejection.
5. Prove phone HTTPS microphone capture, upload, and ffmpeg decoding.
6. Implement enrollment, identification, evidence playback, and blind reveal.
7. Implement the shared session framework and hands-free event ingestion.
8. Implement identity-gated contextual ranking, personalized guidance, and explanation.
9. Run stage-roster and hands-free acceptance three consecutive times offline.
10. Build the visual wrapper gradually around the proven domain service and session modes.
