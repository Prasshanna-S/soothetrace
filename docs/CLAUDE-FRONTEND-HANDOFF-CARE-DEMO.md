# Claude Frontend Handoff: Continuous Care Demo

The owner will direct the visual design with Claude. This file is the stable functional contract
Claude must design around.

## What Claude owns

Claude owns the browser experience:

- `web/index.html`
- `web/app.css`
- `web/app.js`
- `web/manifest.webmanifest`
- browser-only test changes coordinated with the product workstream

Do not edit backend, schema, identity, retrieval, guidance, or threshold files. If a backend field
is missing, append the request to `docs/MESSAGES.md`.

## The three pages

Build one single-document application with three destinations:

1. Listen
2. History
3. Baby

Navigation must not reload the document because a reload terminates the microphone. Keep the
application shell, active baby, active care session, health state, microphone state, and navigation
outside individual page containers.

## Listen page

Required features:

- active baby name;
- local server health;
- Start listening disabled until `health.care.ready` is true;
- one Start listening action;
- animated listening blob;
- elapsed wall-clock time;
- persistent microphone-live indicator;
- small neutral analysis status;
- brief `No infant cry detected in this segment` and
  `Cry-like sound, listening for a clearer segment` states that never create a result card;
- Pause or Resume;
- Stop;
- no suggestion card when the backend has no grounded recommendation;
- first grounded recommendation fixed until Stop;
- exact support count;
- basis statements supplied by the server;
- supporting incidents with time, action, outcome, provenance, and audio;
- post-stop structured questions;
- save and discard;
- interrupted, connection-lost, decode-error, and resume states.

Cry-presence rendering:

- `no_cry_detected` means keep listening, show `No infant cry detected in this segment`, and render
  no identity, history, suggestion, or incident UI.
- `cry_uncertain` means keep listening, show
  `Cry-like sound, listening for a clearer segment`, and do not say an infant cry was confirmed.
- `infant_cry_detected` may show `Infant-cry-like sound detected`. It is an event gate, not an
  identity result.
- The backend alone decides cry presence. Do not infer it from volume, animation, transcript, or
  browser-side audio features.
- Do not show a probability, percentage, raw model label list, diagnosis, emotion, or cause.

Continuous recording behavior:

- Keep one microphone stream.
- Rotate finalized recorder blobs every 12 seconds.
- Record the next blob while the prior blob is analyzed.
- Keep at most one completed blob waiting behind the in-flight request.
- Use a real wall clock for elapsed time.
- Never use periodic blob count as elapsed time.
- Never claim the microphone is live after its track is muted or ended.
- Block every audio player while listening.

Landscape:

- Remove the current portrait-only manifest restriction.
- Do not depend on automatic orientation lock.
- When and only when the backend returns a nonempty latched recommendation, shrink the blob and
  controls, keep Pause or Resume and Stop near the bottom safe area, and let the recommendation
  fill most of the screen.
- Keep one evidence line visible without scrolling.
- Keep the recording state unmistakable.
- Portrait must remain fully usable.

## History page

Required features:

- chronological incidents for the active baby;
- loading, empty, pagination, missing-profile, and connection-error states;
- clear incident number, recorded date, and local time;
- duration;
- action and literal evidence;
- outcome;
- caregiver, inferred, or seed provenance;
- settled, still crying, or unknown state;
- context facts;
- short caregiver-speech excerpt when available;
- playable representative incident audio when the microphone is not live;
- an action that opens one incident in full;
- a full incident view with Overview, What was said, Context, and Evidence tabs;
- complete stored caregiver transcript;
- automatic-transcript warning;
- recorded-audio transcript and typed follow-up as separate labeled segments;
- literal speech excerpts labeled as action or outcome evidence;
- explicit no-transcript state.

Do not show a similarity band in chronological history. A band only exists relative to a current
query.

Label playback as a representative cry segment. The backend does not claim to archive the entire
continuous session. Label transcript text as caregiver speech, never as words spoken by the baby.
Keep typed follow-up values visually separate from words detected in the recording.
Do not imply word-level or sentence-level positions in the recording. The backend does not store
speech timestamps.

## Baby page

Required features:

- baby name;
- exact server profile status;
- exact independent training-clip count;
- exact memory count;
- training clips labeled by ordinal and captured time;
- training-clip duration and playback;
- a way to capture another enrollment;
- recent feeding, sleep, diaper, soothing, and note events;
- five-memory learning state;
- six-or-more-memory ready-for-recall state;
- loading, empty, and error states.

Do not invent a photo, birthday, age, gender, cry type, health state, or diagnosis.

## Backend shapes

Claude should consume these endpoints:

```text
GET  /api/health
GET  /api/profiles
GET  /api/profiles/{profile_id}
GET  /api/profiles/{profile_id}/incidents
GET  /api/profiles/{profile_id}/incidents/{incident_id}
GET  /api/profiles/{profile_id}/incidents/{incident_id}/audio
GET  /api/profiles/{profile_id}/care-events
POST /api/profiles/{profile_id}/care-events

POST   /api/care-sessions
GET    /api/care-sessions/{session_id}
POST   /api/care-sessions/{session_id}/chunks
POST   /api/care-sessions/{session_id}/pause
POST   /api/care-sessions/{session_id}/resume
POST   /api/care-sessions/{session_id}/stop
POST   /api/care-sessions/{session_id}/complete
DELETE /api/care-sessions/{session_id}
```

The exact payloads and state names are in
`docs/superpowers/specs/2026-07-30-continuous-care-demo-design.md`.

Do not begin API integration until the product workstream reports those routes green. Claude may
design the shell, page composition, and static states first.

## Guidance rendering

Render server fields verbatim:

- `guidance.headline`
- `guidance.interpretation`
- `guidance.recommendation`
- `guidance.evidence_summary`
- `guidance.support_count`
- `basis`
- `scenarios`

Do not compose, paraphrase, or invent care advice in JavaScript.

The large suggestion exists only when:

```text
session.decision != null
session.decision.guidance.status == "grounded"
session.decision.guidance.recommendation is nonempty
```

All other states keep the neutral listening experience.

## Existing code worth reusing

Reuse or carefully adapt:

- same-origin `apiJson` and `apiAudio`;
- MIME detection;
- applied microphone-setting readback;
- wake lock;
- track mute, unmute, and ended handling;
- global playback blocking;
- status and live-region helpers;
- incident-card rendering;
- provenance badges;
- profile readiness rendering;
- safe-area spacing;
- 44-pixel targets;
- `textContent` rather than HTML injection.

## Visual freedom

The owner and Claude may choose:

- composition;
- type scale;
- animation;
- blob style;
- color nuance;
- icons;
- transitions;
- card shape;
- spacing;
- how supporting evidence expands;
- how the three destinations navigate.

Those decisions must preserve every required state, evidence field, provenance label, safety rule,
and accessibility requirement above.

## Browser acceptance

Claude's browser work is not complete until it passes:

- 430 by 932 portrait;
- 932 by 430 landscape;
- desktop 1440 by 900;
- no horizontal overflow;
- no document reload during page changes;
- active microphone state remains visible;
- Pause or Resume and Stop remain reachable;
- stable latched recommendation;
- non-cry statuses never create a result card;
- evidence and provenance visible;
- chronological incident cards open a full tabbed detail view;
- representative audio, caregiver transcript, literal excerpts, context, and provenance are
  visible in incident detail;
- recorded speech and typed follow-up are never presented as the same source;
- missing transcripts have an honest empty state;
- playback blocked during listening;
- history and baby empty/error states;
- no client-authored cause or care recommendation;
- keyboard and screen-reader navigation;
- no em or en dash characters.
