# End-to-end enrolled-identity and personalized cry-memory proof of concept

**Status:** approved in conversation; written review pending  
**Date:** 2026-07-29  
**Product owner:** Prasshanna  
**Acoustic/model validation:** acoustics workstream  
**End-to-end architecture, mobile capture, orchestration, offline speech, and verification:** product workstream  
**Supersedes:** `2026-07-29-identity-context-demo-design.md`

## 1. Product decision

Build a functional, offline-capable proof of concept with one primary claim:

> The system recognizes which enrolled cry profile produced a recording, with at most one retry,
> then searches only that profile's prior incidents and reports what previously helped in similar
> circumstances.

The proof of concept is **enrolled-profile recognition**, not universal biometric identification.
The household or operator creates the relevant infant and human-imitation profiles before query.
An unknown or ambiguous recording is allowed to remain unresolved.

The system must never:

- create a new person or baby because one query is uncertain;
- use time, notes, interventions, or outcomes to decide identity;
- treat a cosine score as a probability;
- diagnose hunger, pain, illness, or another cause from cry acoustics;
- invent an intervention when the accepted profile has no supporting history;
- tune a threshold after a blind label is revealed;
- compare a recording with itself or enroll duplicate audio;
- claim general cross-device accuracy from a fixed-rig demonstration.

## 2. Measured facts that constrain the design

These results are the design inputs, not marketing claims.

### 2.1 Mobile capture

- Trusted local HTTPS works on the iPhone.
- One uninterrupted iPhone Safari `MediaRecorder` survived a locked screen for 180.19 seconds.
- The microphone track stayed live and the complete MP4/AAC blob uploaded while the page remained
  hidden.
- iPhone Safari produced `audio/mp4; codecs=mp4a.40.2`; ffmpeg decoded it to canonical 16 kHz mono
  PCM.
- Safari exposed `echoCancellation:false` but did not expose applied AGC or noise-suppression
  settings.
- An audible phone capture was initially below the fixed voiced-level gate. Deterministic level
  normalization recovered the full fingerprint.

### 2.2 Offline speech

- A provisioned local Whisper `base.en` model transcribed the real 40.66-second iPhone mixture in
  5.592 seconds with one minor wording error.
- The isolated full episode-finalization loop completed in 7.641 seconds and saved the transcript,
  87-dimensional fingerprint, explicit caregiver outcome, and `worked=true`.
- Automatic intervention extraction is not yet wholly offline. Without the online reasoning
  client it safely returns an empty list.

### 2.3 Infant identity

- On the measured fixed infant replay rig, `mfcc87-v1` produced 13/15 correct resolved trials with
  zero wrong identity claims.
- It beat the tested CryCeleb and adult VoxCeleb ECAPA checkpoints on that fixed-rig infant set.
- MFCC87 is channel-sensitive. That sensitivity is useful only while enrollment and query share
  the same verified capture path.

### 2.4 Human imitation identity

On three Prasshanna references, two references from one other adult, and two blinded Prasshanna
queries:

| encoder | reference leave-one-out | blind rankings | notable result |
|---|---:|---:|---|
| `mfcc87-v1` | 5/5 | 2/2 | weak blind margins; channel fragile |
| `ecapa-cryceleb-v1` | 5/5 | 2/2 | materially stronger separation |
| `ecapa-voxceleb-v1` | 4/5 | 2/2 | one reference error |

Exact RMS normalization removed the level difference without removing identity separation.

A nine-condition channel perturbation falsification test produced:

- MFCC87 fully correct in 4/9 conditions;
- CryCeleb-ECAPA fully correct in 9/9 conditions;
- CryCeleb margins remained approximately 0.14-0.26.

Therefore the POC uses **per-kind encoder selection**, not raw-score fusion:

```text
infant, fixed verified rig  -> mfcc87-v1
human imitation            -> ecapa-cryceleb-v1
```

Adult VoxCeleb-ECAPA is excluded from the POC identity decision. CMN64 and other channel features
remain diagnostics, not identity votes.

### 2.5 Scenario retrieval

- The existing episode fingerprint achieved AUC 0.70 for within-subject episode discrimination.
- Episode-level top-1 retrieval was 30.5% against 0.7% chance across 421 episodes / 207 subjects.
- The measured minimum useful history is six usable prior episodes.
- Current auditable scenario ranking uses acoustic similarity 0.65, cyclic time-of-day 0.20, and
  caregiver tag overlap 0.15. Missing inputs renormalize the active weights.

## 3. Claims and demonstration boundaries

### 3.1 What the demonstration proves

The presentation may claim:

- the system distinguishes enrolled infant profiles under the verified demo capture path;
- the system distinguishes enrolled adult cry-imitation profiles using the learned CryCeleb
  representation;
- one ambiguous capture can request one independent retry;
- retries remain part of one pending identity attempt rather than creating duplicate people;
- after identity resolves, retrieval is restricted to that profile's history;
- displayed guidance is grounded in caregiver-recorded incidents and outcomes;
- the phone capture and core models operate locally after setup.

### 3.2 What remains outside the claim

- universal unknown-person recognition;
- medical diagnosis or universal cry-cause classification;
- generalization to every phone, room, codec, age, or culture;
- production-grade biometric security;
- causal proof that an intervention resolved an episode;
- a learned human-imitation threshold calibrated from only two people.

## 4. End-to-end demonstration

### 4.1 Infant recognition

1. Create `Baby A` and `Baby B` as `infant` profiles.
2. Enroll each profile with at least three independent source recordings.
3. Capture every enrollment and query through the same iPhone browser microphone path.
4. Play a held-out Baby A recording from the MacBook and freeze the result before revealing the
   source label.
5. Repeat with Baby B.
6. Use a cry with a different pattern from the same baby to show identity is not a copied waveform.
7. If the first query is uncertain, capture one independent retry and make a joint decision.
8. Permit playback of the nearest enrollment as secondary evidence.

Enrollment and query audio must be different source recordings. A duplicate, volume-adjusted copy,
or segment cut from the same source recording is not an independent trial.

### 4.2 Human-imitation recognition

1. Create `Prasshanna` and `Other adult` as `human_imitation` profiles.
2. Enroll each with at least three independent 6-12 second performances when available.
3. Use CryCeleb-ECAPA for every human-imitation enrollment and query.
4. Run a blind query without revealing the performer.
5. Return a match, retry request, or unresolved result.
6. If needed, add one independent retry to the same attempt and re-evaluate.
7. Reveal the performer only after the result is frozen.

Online recordings may be used as stress-test profiles if they contain independent performances by
the same known adult. They do not calibrate a universal threshold, and source-channel limitations
must be disclosed.

### 4.3 Personalized incident memory

Each infant profile receives at least six clearly labeled demo incidents. Every incident contains:

- a distinct managed recording;
- local timestamp and cyclic hour;
- caregiver-entered or transcript-grounded notes;
- ordered interventions;
- explicit caregiver outcome;
- `worked`, `did_not_work`, or `unknown` provenance;
- optional structured care-state tags such as `last_feed_2_to_4h`, `awake_over_2h`, or
  `recent_diaper`.

After a query resolves to one infant:

1. Search only that profile's incidents.
2. Rank similar incidents using the transparent POC inputs.
3. Show the best-supported prior action.
4. Show how many relevant incidents support it.
5. Display one short possible pattern only when repeated caregiver context supports it.
6. Keep the prior recording available as optional evidence.

Example:

> This resembles two previous early-morning incidents for Baby A. Walking was the final recorded
> action that helped in both. The last feed was three hours ago, so a feeding-time pattern is
> possible; the cry alone does not establish the cause.

If history is insufficient:

> Not enough history for a reliable pattern yet. Keep listening and add an outcome when you can.

## 5. System architecture

```text
iPhone HTTPS capture
        |
        v
decode + preserve raw + exact linear normalization
        |
        v
quality / cry-event / source-kind gates
        |
        v
IDENTITY ATTEMPT
  profile kind selects one identity encoder
  infant=fixed-rig MFCC87 | imitation=CryCeleb-ECAPA
  local segments + whole recording + profile enrollments
        |
        +------ match ----------------------+
        |                                   |
        +------ uncertain -> one retry -----+
        |                                   |
        +------ unresolved/invalid -> stop  |
                                            v
                                  accepted profile
                                            |
                                            v
STATE REPRESENTATION + STRUCTURED CONTEXT
  cry dynamics, cyclic time, care-state tags, notes
                                            |
                                            v
PROFILE-ISOLATED INCIDENT RETRIEVAL
                                            |
                                            v
OUTCOME EVIDENCE + GROUNDED LANGUAGE
                                            |
                                            v
large readable guidance + optional playback
```

Identity, state similarity, and nuisance/channel evidence are separate roles:

- **identity evidence** may name a profile;
- **state evidence** may rank that accepted profile's incidents;
- **nuisance evidence** may reject or down-weight a capture but may never name a profile;
- **language reasoning** may explain structured evidence but may never override the gates.

## 6. Capture and preprocessing

### 6.1 Managed representations

For each uploaded capture retain:

1. immutable source upload and SHA-256;
2. canonical raw 16 kHz mono PCM WAV;
3. identity-normalized WAV;
4. measured duration, RMS, peak, voiced fraction, MIME, device, and capture settings;
5. encoder and normalization versions.

Evidence playback uses the canonical raw WAV. Identity encoding uses the normalized WAV.
Transcription may use the normalized mixture when it improves intelligibility but stores the raw
source as evidence.

### 6.2 Exact linear normalization

- Measure RMS after canonical decode.
- Apply one constant gain so the identity input reaches -24.00 dB RMS.
- Do not use a compressor, dynamic limiter, pitch shift, or spectral filter.
- If the predicted normalized peak would exceed -1.0 dBFS, reject the capture and request a clearer
  recording rather than altering its dynamics.
- Preserve the pre-normalization measurements for audit.

This process removes overall level as an identity shortcut while preserving spectral and temporal
dynamics.

### 6.3 Quality states

Return stable reason codes for:

- missing or undecodable upload;
- empty or too-short audio;
- insufficient voiced material;
- near-silence;
- clipping or unsafe normalization headroom;
- unsupported source kind;
- model unavailable;
- duplicate enrollment/query;
- stale or mismatched encoder version.

Invalid audio never becomes an all-zero embedding and never creates a profile.

### 6.4 Continuous care capture

One deliberate tap starts a hands-free session. The phone may remain placed down while the
caregiver moves with the baby.

- Maintain a bounded rolling buffer.
- Detect candidate cry events.
- Preserve only selected event clips by default.
- Keep caregiver speech and infant cry in the same raw mixture for episode processing.
- Do not source-separate before the validated fingerprint/transcription path.
- Keep the last stable guidance visible while waiting for clearer evidence.
- Treat the measured three-minute locked-screen pass as POC evidence, not an unlimited-duration
  guarantee.

## 7. Identity subsystem

### 7.1 Per-kind encoder policy

Encoder selection is versioned configuration:

```python
IDENTITY_ENCODER_BY_KIND = {
    "infant": "mfcc87-v1",
    "human_imitation": "ecapa-cryceleb-v1",
}
```

The selected encoder is stored with every enrollment and attempt capture. Embeddings from different
encoders are never compared.

The infant mapping is valid only for the fixed verified presentation path until cross-channel
infant trials support a different choice.

### 7.2 Multi-view evidence

For each query:

- compute one whole-recording embedding;
- compute embeddings for fixed-length voiced segments;
- discard invalid segments using quality gates;
- score every valid view against every independent enrollment;
- aggregate with a frozen robust rule that cannot be dominated by one segment or enrollment.

Before prospective blind trials, the implementation must compare these versioned candidate rules
using reference-only leave-one-recording-out trials:

1. median of all valid view-to-enrollment scores;
2. mean after trimming the highest and lowest score when at least five scores exist, otherwise
   median;
3. local/global joint score: `0.5 * whole-recording score + 0.5 * median(segment scores)`, followed
   by the median across independent enrollments.

Select the rule that maximizes correct resolved trials while allowing zero wrong profile names.
Break ties by the largest minimum winning margin, then by the simpler rule in the order above.
Freeze the selected rule, thresholds, dataset digests, and configuration version before any
prospective blind query. Revealed blind queries may verify the choice but may not select or tune it.

A retry contributes another independent set of whole and segment views to the same attempt. It is
not concatenated into a synthetic waveform. The frozen aggregation rule is rerun over the combined
valid evidence from both captures.

### 7.3 Profiles

A profile is caregiver-confirmed and persistent. It contains:

- display label and kind;
- status `provisional`, `ready`, or `archived`;
- independent enrollments and managed audio;
- encoder version and embedding;
- capture quality and source metadata;
- created/updated timestamps.

At least two usable independent enrollments make the current schema ready. The demo target is three
or more enrollments per profile.

### 7.4 Pending attempts and retry

An uncertain query is an unresolved attempt, not a new identity.

```text
identity_attempt
  id
  kind
  status: pending | matched | unresolved | invalid
  started_at
  resolved_profile_id
  resolved_at

identity_attempt_capture
  attempt_id
  audio path and digest
  embedding / encoder version
  ranked candidates
  score / margin / reason codes
  capture quality
  captured_at
```

Flow:

1. First capture starts an attempt.
2. A passing decision resolves to an existing profile.
3. An uncertain result stays pending and retains internal candidate evidence.
4. One independent retry is appended to the same attempt.
5. Multi-capture evidence is aggregated under the frozen rule.
6. If both gates pass, resolve all attempt captures to the existing profile.
7. If the second decision abstains, keep it unresolved and ask the caregiver to select an existing
   profile or deliberately enroll a new one.

Profile creation always requires explicit confirmation. A corrected caregiver label may link the
incident to a profile but does not silently promote that audio into an identity enrollment.

### 7.5 Identity result

```text
status: match | uncertain | unknown | invalid
profile: present only for match
kind: infant | human_imitation
band: strong | weak | none
support: nearest independent enrollment
retry_allowed: boolean
reasons: stable reason codes
versions: encoder, normalization, calibration, aggregation
```

Candidate scores remain debug/audit data. The human UI shows a name only when status is `match`.

### 7.6 Open-set handling

The POC distinguishes:

- **closed household recognition:** rank enrolled profiles and resolve with one retry;
- **unknown guard:** refuse recordings that do not meet the kind-specific absolute and margin
  gates.

The infant fixed-rig thresholds retain their measured calibration. Human-imitation thresholds
remain explicitly provisional until an independent cohort supports calibration. No local
five-person cohort is required to build or demonstrate enrolled-profile recognition.

Public or online recordings can broaden stress testing, but they cannot silently become the
calibration cohort when source identity or channel independence is uncertain.

### 7.7 Nuisance/channel diagnostics

The system records but does not identity-fuse:

- RMS and peak;
- voiced fraction;
- MIME/codec and sample rate;
- capture device and browser settings;
- CMN64 or another channel-reduced diagnostic;
- simulated room, band-limit, and speaker perturbation results in regression tests.

A future product may fuse calibrated encoder log-likelihood ratios after an adequate cohort
supports the transforms and weights. Raw cosine averaging is prohibited.

## 8. Cry-state and scenario representation

Identity asks who. State retrieval asks which prior incident feels acoustically and contextually
similar for that already-accepted profile.

### 8.1 State features

The state representation may include:

- pitch median, spread, percentiles, and trajectory;
- harmonicity, entropy, jitter, shimmer, and roughness;
- spectral centroid and spectral-shape dynamics;
- cry-unit duration and bout rhythm;
- inter-cry pauses and onset/offset behavior;
- intensity contour after level normalization;
- voiced fraction and modulation dynamics;
- a learned general cry-state embedding when it improves held-out retrieval.

Raw recording length is not an identity feature. Total session length is often an operator or
capture artifact. Cry-unit and bout timing may participate in state retrieval after validation.

### 8.2 Context

POC ranking uses the implemented components:

| component | weight |
|---|---:|
| acoustic state similarity | 0.65 |
| cyclic time-of-day similarity | 0.20 |
| structured/caregiver tag overlap | 0.15 |

Missing components are removed and active weights renormalize.

Structured tags may encode:

- time since feeding bucket;
- time awake / sleep-state bucket;
- recent diaper event;
- recent soothing action;
- room/noise notes;
- caregiver-observed behavior.

This includes care context without inventing additional top-level weights. Duration and
gap-since-previous remain stored and explainable but are not ranked until measured evidence shows
they improve retrieval.

### 8.3 Profile isolation

Scenario retrieval accepts an already-resolved profile ID. It must never:

- search another profile's episodes;
- infer identity from context;
- call scenario retrieval after an uncertain identity;
- include the current episode as its own nearest prior incident.

## 9. Incidents, interventions, and outcomes

Every completed incident stores:

- accepted profile ID;
- source identity attempt ID;
- start/end timestamps;
- managed audio;
- state fingerprint/version;
- transcript;
- structured context/tags;
- ordered interventions with literal transcript evidence where available;
- explicit caregiver outcome and provenance;
- `worked` tri-state;
- optional caregiver correction.

### 9.1 Evidence policy

- Prefer caregiver-confirmed outcomes over inferred outcomes.
- `unknown` is different from `did_not_work`.
- An action is reported as helpful only from stored incidents marked resolved.
- The primary tally uses `worked_last`: the final recorded intervention before a resolved outcome.
- Counts are longitudinal evidence, not causal proof.
- One incident never creates a general rule.

### 9.2 Offline extraction

The offline baseline must remain functional without a reasoning API:

1. Whisper `base.en` produces the transcript.
2. A deterministic, evidence-span-preserving extractor recognizes a controlled intervention
   vocabulary such as holding, rocking, walking, feeding, burping, diaper checking, pacifier use,
   swaddling, and changing environment.
3. Unknown language remains unstructured text rather than becoming an invented action.
4. A local or remote LLM provider may improve extraction and explanation only when its output
   validates against the same schema and literal transcript evidence.

The system must not depend on venue internet to save incidents or generate basic grounded guidance.

## 10. Language reasoning and guidance

The language layer receives structured evidence only:

- identity status and reason codes;
- selected incident IDs;
- deterministic contribution labels;
- interventions and outcomes;
- context similarities;
- evidence spans and provenance.

It may:

- summarize why prior incidents were selected;
- express what previously helped;
- state a contextual possibility with uncertainty;
- ask one useful missing-context question;
- produce large, readable caregiver language.

It may not:

- change identity;
- introduce a cause absent from context/history;
- recommend an action absent from supporting history;
- convert debug scores to probabilities;
- remove uncertainty or provenance;
- generate medical advice.

Every generated statement must have a deterministic template fallback.

## 11. Persistence and contracts

Retain the existing tables:

- `profile`;
- `enrollment`;
- `identity_query`;
- `episode`;
- `baseline`.

Add:

- `identity_attempt`;
- `identity_attempt_capture`;
- `care_event` for feeding, sleep, diaper, and other timestamped structured context.

`identity_query` remains the immutable per-decision audit. Attempt tables group retries and retain
candidate evidence. `care_event` provides deterministic recency facts without placing them in
identity.

Required service interfaces:

```python
begin_identity_attempt(kind, candidate_profile_ids=None) -> attempt
add_identity_capture(attempt_id, audio_path, capture_metadata=None) -> attempt_result
retry_identity_attempt(attempt_id, audio_path, capture_metadata=None) -> attempt_result
resolve_identity_attempt(attempt_id, confirmed_profile_id=None) -> attempt_result

save_care_event(profile_id, event_type, occurred_at, details=None) -> care_event
build_current_context(profile_id, now=None, transcript=None, tags=None) -> context
find_scenarios(profile_id, state_vector, current_context=None, k=3) -> scenarios
build_guidance(profile_id, scenarios, current_context=None) -> guidance
```

All interfaces return stable structured states and never require consumers to parse generated
prose.

## 12. Mobile experience

### 12.1 Enrollment

- Choose Infant or Human imitation.
- Enter a display label.
- Capture three guided independent takes.
- Show quality, take count, and profile readiness.
- Refuse duplicates and unusable audio.

### 12.2 Identity query

- One prominent Start button.
- Large state: listening, processing, matched, retry needed, unresolved, or invalid.
- If uncertain, preserve Attempt 1 and offer one Retry button.
- Display a profile name only after a passing result.
- Offer supporting-audio playback below the result.

### 12.3 Hands-free care

- One deliberate Start listening action.
- Phone can be placed down.
- Large text remains readable from across the room.
- Stable message does not flicker on every chunk.
- Pause/stop/playback controls remain small and low.
- Show identity confirmation, evidence-backed prior action, and short provenance.

## 13. Error handling

| condition | behavior |
|---|---|
| mic permission denied | show exact recovery instruction |
| HTTPS/certificate failure | block capture and show local setup check |
| screen/background capture stops | retain completed chunks and show resume |
| decode failure | preserve source upload, mark invalid, allow retry |
| too quiet or clipped | show distance/volume correction; do not identify |
| encoder unavailable | block that kind, never silently switch score spaces |
| first identity uncertain | retain pending attempt and request one retry |
| second identity uncertain | keep unresolved; ask for explicit profile selection |
| insufficient incident history | show not-enough-history state |
| offline extraction incomplete | save transcript and outcome; use deterministic fallback |
| no grounded helpful action | do not generate a suggestion |

## 14. Privacy and integrity

- Obtain consent for every audible adult.
- Treat infant recordings and embeddings as sensitive local data.
- Keep raw audio, derived embeddings, and decisions deletable by profile and incident.
- Do not enroll online adults into the presentation profile set without a clear source label.
- Never use a blind query for calibration after its label is revealed.
- Record encoder, normalization, calibration, aggregation, and capture versions with decisions.
- Remove the temporary iPhone root certificate after local testing.

## 15. Verification and acceptance

### 15.1 Unit and contract tests

- per-kind encoder selection;
- encoder-space isolation;
- exact-RMS normalization and clipping refusal;
- duplicate refusal;
- attempt creation, retry grouping, and explicit-only profile creation;
- no identity from time/notes/context;
- no cross-profile scenario retrieval;
- self-match exclusion;
- missing-context weight renormalization;
- evidence-span validation;
- offline deterministic extraction;
- guidance never exceeds stored evidence.

### 15.2 Model trials

Infant:

- at least two profiles;
- three or more independent enrollments each;
- held-out queries captured through the presentation phone path;
- a different cry pattern from the same baby;
- one permitted retry;
- zero wrong profile names in the frozen trial;
- document resolved, abstained, and invalid separately.

Human imitation:

- Prasshanna and one other known adult;
- three independent enrollments each when available;
- CryCeleb-ECAPA only for the identity decision;
- exact RMS normalization;
- matched replay-master trial;
- real same-person cross-device capture when feasible;
- channel-perturbation regression suite remains 9/9;
- prospective blind queries after rules freeze;
- no imitation calibration written from two people.

### 15.3 End-to-end scenario

The POC passes when:

1. the phone enrolls two profiles;
2. a held-out query resolves correctly immediately or after one retry;
3. no wrong profile is named;
4. the accepted profile alone supplies scenario candidates;
5. at least six usable prior incidents support retrieval;
6. the UI shows a history-grounded action and provenance;
7. a caregiver outcome is saved and updates future memory;
8. optional evidence playback works;
9. the complete path works without upstream internet after provisioning.

### 15.4 Performance budgets

- warmed identity encoding: target under 1 second per capture;
- identity result excluding capture time: target under 3 seconds;
- offline transcription for a 40-second incident: measured approximately 5.6 seconds;
- complete episode finalization: measured approximately 7.6 seconds;
- UI retains stable listening feedback during longer processing.

## 16. Delivery sequence

The implementation plan will divide work into these milestones:

1. **Measurement controls:** matched replay capture, exact normalization, phone-path infant trials.
2. **Identity core:** per-kind encoders, normalized managed audio, multi-view scoring, pending
   attempts, one retry.
3. **Offline incident memory:** deterministic intervention extraction, care events, scenario
   retrieval, outcome evidence, grounded guidance.
4. **Mobile wrapper:** enrollment, query, hands-free care, evidence playback, readable states.
5. **Demo pack:** seeded incident histories, blind-query controls, offline preflight, reset/wipe,
   narrative and evidence.

No milestone may broaden a measured claim. A failed gate produces a documented fallback rather
than an uncalibrated threshold or hidden model substitution.

## 17. Research basis

- [CryCeleb: A Speaker Verification Dataset Based on Infant Cry Sounds](https://huggingface.co/papers/2305.00969)
  establishes infant cry verification as a distinct, difficult open-set task.
- [A Unified Learning and Evaluation Framework for Infant Cry-based Verification](https://pubmed.ncbi.nlm.nih.gov/41335787/)
  supports fixed-length segment training and local-plus-whole-recording multi-view evaluation.
- [Infant cries convey both stable and dynamic information about age and identity](https://pmc.ncbi.nlm.nih.gov/articles/PMC11332224/)
  found identity and age information but could not reliably classify hunger, discomfort, or
  isolation from cry acoustics.
- [InfantCryNet](https://proceedings.mlr.press/v260/hong25a.html) supports pretrained audio
  representations, statistical/multi-head pooling, and efficient deployment as a longer-term
  cry-state research direction.

## 18. Explicitly deferred

- universal unknown-person calibration;
- raw-score or uncalibrated encoder fusion;
- medical or universal cry-cause classification;
- automatic profile creation or self-training from uncertain queries;
- production biometric security claims;
- cross-device infant claims beyond measured trials;
- learned personalized scenario weights before adequate longitudinal data exists.
