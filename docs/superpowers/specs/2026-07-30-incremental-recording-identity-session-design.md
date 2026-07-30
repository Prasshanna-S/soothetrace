# Incremental Recording Identity Session Design

## Purpose

Build a demonstration session that accepts one short recording at a time and immediately reports
which participant it most resembles. The session improves as more recordings arrive. It does not
require the operator to enroll or name people before the demonstration.

This is a proof of concept for within-session cry-profile grouping. It does not claim universal
voice identification or prove a person's real-world identity.

## Demonstration Contract

1. The operator creates a new empty identity session.
2. The operator either records a roughly five-second cry or uploads one audio file.
3. The backend treats that submission as one independent observation.
4. The interface immediately reports one of:
   - `Person A`
   - `Leaning toward Person A`
   - `Possible new person`
   - `Recording needs another try`
5. A recording that is confidently outside every current participant creates a provisional
   participant with the next stable letter.
6. A provisional participant appears as a dotted bubble in the participant strip.
7. A second separately captured recording that strongly matches the provisional participant
   promotes it to an established participant with a solid bubble.
8. Every later recording is classified independently against the accumulated session profiles.
9. Weak results show a direction but do not reinforce a participant profile.
10. Strong results add the recording to that participant's reference set.
11. Starting a new session clears the demonstration participants without deleting infant profiles
    or unrelated caregiver history.

Uploading the same exact bytes twice does not count as two independent observations. Replaying the
same source through the phone microphone creates a new capture, but the demonstration must describe
that result as capture-path repeatability rather than independent proof of identity.

## Recommended Architecture

Use an incremental, dual-encoder participant model.

Each accepted observation receives:

- the existing learned CryCeleb ECAPA representation;
- the existing MFCC87 representation;
- a content digest;
- capture-quality measurements;
- the session identifier and capture time.

The session service compares a new observation with the reference recordings for every participant.
It aggregates recording-level comparisons rather than relying only on one centroid. This prevents
one unusual cry from permanently dragging a participant profile away from its other recordings.

The learned encoder supplies the primary direction. MFCC87 acts as an independent consistency
check. Existing calibrated thresholds remain encoder-specific. No raw score is shown in the normal
interface.

## Participant States

### Provisional

A participant becomes provisional when one valid observation is confidently separated from all
current participants. Its first observation is stored as evidence, but the interface clearly marks
the participant as still forming.

### Established

A provisional participant becomes established when a separately captured observation:

- is acoustically consistent with the provisional reference;
- clears the applicable same-participant gate on both encoders;
- is separated from the other current participants;
- is not byte-identical to an earlier observation.

Established means the within-session pattern has repeated. It does not mean the person's legal or
biometric identity has been established.

### Direction only

If one participant leads but the result does not clear the reinforcement gate, the response says
`Leaning toward Person X`. The observation is retained in the session timeline but does not alter
that participant's reference profile.

### Possible new person

If the observation appears outside every participant but does not clear the novelty gate, it is
shown as `Possible new person`. It does not create a bubble until the novelty gate is met.

### Invalid

Near-silence, clipping, failed decoding, insufficient voiced audio, and unavailable encoders return
an actionable retry message. Invalid recordings never create or reinforce participants.

## Stable Labels

Participant letters are allocated in creation order and remain stable for the session. Person A
does not become Person B merely because later evidence changes its relative similarity.

The first valid recording creates provisional Person A because there is no comparison pool yet.
Its second separately captured, consistent recording can establish Person A.

If later evidence conflicts with an earlier direction-only result, the latest participant profiles
govern new classifications. The original timeline entry remains labelled as the result produced at
that time. The proof of concept does not silently rewrite prior output.

## Backend Boundaries

Add a session orchestration layer rather than making the browser create and delete profiles
directly.

### Session

Stores:

- session identifier;
- kind, initially `human_imitation`;
- creation and completion timestamps;
- next participant letter;
- active status.

### Session participant

Stores:

- session identifier;
- underlying acoustic profile identifier;
- stable display label;
- `provisional` or `established`;
- independent supporting recording count.

### Session observation

Stores:

- session identifier;
- capture identifier and digest;
- result shown to the operator;
- closest participant, when available;
- whether it reinforced a participant;
- reason codes;
- creation time.

### API

The browser uses four session endpoints:

- `POST /api/live-sessions`
- `GET /api/live-sessions/{session_id}`
- `POST /api/live-sessions/{session_id}/observations`
- `POST /api/live-sessions/{session_id}/complete`

The observation response includes the current classification, the complete participant strip, and
the session timeline. It never exposes raw embedding vectors or calibration scores.

## Interface Structure

The approved interface has one primary workflow.

### Top

- session title and New session control;
- local server and microphone status;
- concise statement that each submission is classified separately.

### Main capture control

- large `Record 5 seconds` control;
- `Upload audio` control with the same visual weight;
- selected-file and recording-duration feedback;
- one Submit control when a file has been selected.

Recording and upload must call the same backend observation endpoint and produce the same result
shape.

### Latest result

The largest text on the screen shows:

- `Person A`;
- `Leaning toward Person A`;
- `Provisional Person B created`;
- or a specific retry instruction.

The supporting sentence explains whether the recording reinforced the participant, merely leaned
toward it, or started a new provisional pattern.

### Recording timeline

Each submitted recording appears once with:

- order number;
- playback control;
- classification shown at submission time;
- source, microphone or upload;
- `reinforced profile`, `direction only`, `new provisional`, or `invalid`.

### Participant strip

The bottom of the working screen contains the running participants:

- dotted border for provisional;
- solid border for established;
- stable letter and supporting-recording count;
- a short state label such as `Pattern forming` or `Repeated pattern`.

The participant strip remains visible after each result. It must not be displaced by roadmap,
disabled-feature, research, or liability panels during the demonstration.

## Error Handling

- A network interruption preserves the selected recording and offers Resubmit.
- A failed decode identifies the unsupported file rather than creating an empty observation.
- A duplicate byte digest is recorded as a duplicate and cannot promote a provisional participant.
- If an encoder is unavailable, the system stops the classification and names the missing
  component.
- If no participant clears the reinforcement or novelty gates, the interface shows a direction
  without changing any reference profile.

## Test Strategy

### Unit tests

- first valid observation creates provisional Person A;
- a consistent independent observation establishes Person A;
- a different observation creates provisional Person B;
- an exact duplicate cannot establish a participant;
- a weak result shows a direction without reinforcement;
- invalid audio changes no participant state;
- participant labels remain stable;
- a new session does not delete unrelated infant profiles.

### Real-audio regression

Use every consented human demonstration recording in chronological stress-test sequences:

- one-person repeated recordings;
- two-person alternating recordings;
- three-person alternating recordings;
- a deliberately difficult order with one recording per person before repeats;
- byte-identical duplicate uploads;
- microphone replays of source files when the fixed rig is available.

Report:

- correct direction rate for every valid recording after a comparison exists;
- confirmed match rate;
- wrong-person rate;
- provisional participants created correctly;
- duplicate participant profiles;
- abstentions or retry requests.

### Browser acceptance

At desktop and iPhone widths:

- create a new session;
- submit by upload;
- submit by microphone;
- observe provisional and established participant bubbles;
- replay a stored recording;
- verify that the latest result, timeline, and participant strip update without a page reload.

## Demonstration Language

Use:

> Each clip is processed separately. The system compares it with the patterns accumulated in this
> session. A dotted participant is provisional. A solid participant means a separately captured
> cry repeated the pattern.

Use:

> This recording is leaning toward Person B.

Do not say:

- the system knows the person's real identity;
- the result is certain;
- the two recordings prove that the speaker is the same human;
- an infant's cry proves hunger, pain, or another cause.

## Release Gate

Do not publish the redesigned interface or record the final desktop video until:

1. the user approves this interaction contract;
2. the backend real-audio stress test reports no hidden wrong assignments;
3. the browser test demonstrates both upload and microphone paths;
4. the full automated suite passes;
5. the repository naming and history cleanup is complete.
