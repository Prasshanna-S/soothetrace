# Continuous Care Demo Design

Status: approved by the owner on 2026-07-30.

## 1. Goal

Build one complete proof-of-concept care loop:

1. A caregiver selects an enrolled baby and starts listening.
2. The phone appears to record continuously while it uploads short, independently decodable
   segments to the laptop.
3. A local, non-generative cry-presence gate rejects ordinary speech, music, silence, and
   environmental sounds before identity or memory retrieval.
4. The laptop checks cry-positive segments against the selected baby and that baby's recorded
   history.
5. Weak, silent, invalid, non-cry, unmatched, or unhelpful segments produce no suggestion.
6. The first grounded suggestion remains fixed until the caregiver stops.
7. Stop opens a short structured follow-up.
8. Completing the follow-up saves exactly one new incident.
9. The caregiver can later inspect the baby's profile, training clips, chronological history,
   representative audio, caregiver transcript, and grounded speech excerpts.

The demonstration must show both ends of the memory loop:

- an early state with five usable memories, where the system keeps listening and shows no
  suggestion;
- a mature state with at least six usable memories, where two distinct cry recordings from the
  same baby retrieve different, explicitly supported prior incidents;
- a negative state where speech and ordinary non-cry sounds create no identity result, memory
  lookup, suggestion, or incident.

This is a memory prosthetic, not a cry translator. The system never reports why a baby is crying.

## 2. Ownership and collaboration

The product workstream owns the functional care-session backend, persistence, API integration,
test harnesses, demo preparation, and release verification.

Claude receives a separate frontend handoff. Claude owns the visual design and edits only the
browser files unless the owner explicitly expands that scope. The handoff specifies features,
states, data, accessibility, and safety constraints. It does not dictate visual composition.

The owner has explicitly approved this build and the cross-file work required for the new
care-session persistence. Changes that cross the earlier ownership table must still be recorded in
`docs/MESSAGES.md`.

## 3. Non-goals

This build does not add:

- a medical diagnosis or inferred cause;
- a population recommendation;
- cloud accounts, authentication, or remote deployment;
- a cry-cause classifier or general-purpose sound understanding;
- automatic enrollment from continuous chunks;
- identity reinforcement from adjacent chunks;
- raw score or percentage-confidence display;
- automatic screen-orientation locking on iPhone;
- background recording after iOS ends or mutes the microphone;
- a full unbroken session-audio archive.

The saved incident uses the selected matched segment. The other short segments remain session audit
evidence until the session is completed or discarded.

## 4. Recommended architecture

Use a dedicated persistent care-session facade. Do not reuse `live_sessions`.

`live_sessions` assumes independent observations and may create or reinforce identity profiles.
Adjacent chunks from one continuous recording are correlated and must never count as independent
enrollment or retry evidence.

The browser keeps one microphone stream open and rotates a `MediaRecorder` into self-contained
segments. The server accepts complete HTTP uploads, not a WebSocket or chunked transfer stream.
The experience looks continuous, while every server input remains independently decodable by
FFmpeg.

The default segment target is 12 seconds:

```text
CARE_SEGMENT_MS = 12000
MAX_PENDING_SEGMENTS = 1
```

The client uses a wall-clock timer. It must not calculate elapsed time by multiplying the number of
segments because browser recording intervals are not exact.

The browser records segment N while the laptop processes segment N-1. At most one completed segment
may wait behind the in-flight request. If analysis becomes slower than capture, the client keeps
the newest completed segment and discards the older unsent one. It never creates an unbounded
queue.

## 5. End-to-end data flow

```text
Caregiver selects Baby 1
        |
        v
POST /api/care-sessions
        |
        v
Phone microphone stays active
        |
        v
12 second finalized segment
        |
        v
POST /api/care-sessions/{id}/chunks
        |
        +--> bounded ingest and FFmpeg decode
        |
        +--> local cry-presence gate
               |
               +--> no or uncertain: no identity, no history, keep listening
               |
               +--> yes: fixed-level identity view
                          |
                          v
                    non-enrolling infant identity against the full infant pool
                          |
                          v
                    selected Baby 1 matched?
                          |
                          +--> no: no history access, keep listening
                          |
                          +--> yes: canonical-audio care fingerprint
                                    |
                                    +--> server-local time
                                    +--> recent structured care context
                                    +--> optional caregiver tags
                                    |
                                    v
                               Baby 1 history only
                                    |
                                    v
                               ranked scenarios
                                    |
                                    v
                               grounded prior action?
                                    |
                                    +--> no: keep listening
                                    |
                                    +--> yes: latch first decision until Stop
```

Identity and care-memory ranking remain separate:

- cry presence is a separate precondition and never identifies a baby or a cause;
- identity uses audio only, same-kind profiles, calibration, and enrollment state;
- care retrieval runs only after the selected profile matches;
- care ranking uses cry pattern, time, and available context;
- actions and outcomes come only from stored caregiver or clearly synthetic history.

## 6. Care-session state machine

Server states:

```text
listening
paused
awaiting_outcome
complete
discarded
```

Transitions:

```text
create -> listening
listening -> paused
paused -> listening
listening -> awaiting_outcome
paused -> awaiting_outcome
awaiting_outcome -> complete
listening -> discarded
paused -> discarded
awaiting_outcome -> discarded
```

Invalid transitions return HTTP 409 with a stable reason code and do not change state.

Rules:

1. Chunks are accepted only while `listening`.
2. Pausing is a server-visible state, but the browser owns microphone release and reacquisition.
3. Stop rejects future chunks and moves the session to `awaiting_outcome`.
4. Complete saves exactly one incident and is idempotent.
5. Discard removes unsaved session audio and cannot be reversed.
6. A complete or discarded session is immutable.

Client-only transient states may include `requesting_permission`, `rotating_segment`,
`uploading`, `stopping`, `interrupted`, and `connection_lost`. They are not persisted server
states.

## 7. Chunk processing and stable guidance

Each chunk carries:

- a positive monotonic sequence number in `X-Capture-Sequence`;
- the existing content type;
- the existing capture source;
- the existing capture device and user-agent metadata.

Sequence rules:

1. The first accepted sequence is 1.
2. The next new sequence must equal the previous accepted sequence plus 1.
3. Repeating a sequence with the same digest returns the original result.
4. Repeating a sequence with different bytes returns HTTP 409 `sequence_conflict`.
5. Skipping a sequence returns HTTP 409 `out_of_order_chunk`.

Public chunk statuses:

```text
invalid
no_cry_detected
cry_uncertain
not_selected_profile
matched_no_guidance
guidance_latched
matched_guidance_already_latched
```

Processing:

1. Reuse `audio_ingest.ingest_audio`.
2. Reject empty, unsupported, corrupt, near-silent, clipped, or unusable audio with the existing
   reason codes.
3. Run the cry-presence gate on canonical raw audio.
4. If the gate returns `not_detected` or `uncertain`, do not run identity, do not read history,
   and do not select the chunk for incident completion.
5. Call the non-enrolling infant identity path against every active infant profile only after the
   gate returns `detected`.
6. If identity is uncertain, unresolved, or names another profile, do not read any history.
7. If the selected profile matches, compute the separate canonical-audio care fingerprint.
8. Build current context using server-local time, recent care events, and any session tags.
9. Search only `subject_id="profile-{selected_profile_id}"`.
10. Build guidance from stored worked incidents.
11. A public suggestion exists only when guidance status is `grounded` and recommendation is a
   nonempty string.
12. The first grounded result is latched as the session decision.
13. Later chunks can be audited but cannot replace the latched decision.

The browser must not show a blank card, an insufficient-history card, or a no-helpful-history card
as a suggestion. Those states keep the neutral listening experience.

### 7.1 Cry-presence gate

The care-session path requires a versioned, local, non-generative audio-event classifier with an
explicit infant-cry class. The initial candidate is the Audio Spectrogram Transformer checkpoint
`MIT/ast-finetuned-audioset-10-10-0.4593`, using the AudioSet class `Baby cry, infant cry`. The
model runs on the laptop, is cached before presentation, and must be available on macOS ARM and
Windows Python 3.12. The model card publishes a BSD 3-Clause license. AudioSet defines the target
as the sound of a young child crying or bawling. These are event-presence labels, not causes:

- [MIT Audio Spectrogram Transformer checkpoint](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593)
- [Google AudioSet Baby cry, infant cry class](https://research.google.com/audioset/ontology/baby_cry_infant_cry.html)

The adapter exposes only:

```json
{
  "status": "detected",
  "label": "Infant cry detected",
  "reason_codes": [],
  "detected_window_count": 2,
  "analyzed_duration_s": 12.0,
  "model_version": "ast-audioset-baby-cry-v1"
}
```

Allowed statuses are `detected`, `not_detected`, and `uncertain`. Raw logits, probabilities, top
labels, and thresholds are diagnostic data and never enter the public response. The internal
adapter evaluates the whole segment plus overlapping windows and requires repeat evidence rather
than one isolated high-scoring frame. Exact thresholds and the repeat rule are frozen only after
calibration on the checked-in infant clips and a held-out negative set.

The negative set must contain, at minimum:

- conversational caregiver speech;
- adult speech played from the demo phone;
- music;
- clapping or tapping;
- running water;
- white noise or fan noise;
- silence and ordinary room tone;
- a ringtone or alert;
- adult cry imitation.

Adult cry imitation is negative for an infant care session even though the separate human
participant demo may accept it. Mixed caregiver speech plus a real infant cry is positive. The
gate detects presence only. It never reports cry type, emotion, pain, hunger, urgency, or cause.

The model fails closed. If it is missing or cannot run, `/api/health` reports the infant care path
as unavailable, creating a care session returns HTTP 503 `cry_detector_unavailable`, and the
server never falls through to identity. A deterministic level or voiced-fraction check may reject
silence before model inference, but it may not replace the semantic cry gate.

Calibration and release acceptance use fixed-rig phone captures, not direct file inference alone.
The chosen rule must reject every required presentation negative and detect every planned Baby 1
demo query in five consecutive rehearsals. The release report must also show a confusion matrix on
all available labeled positive and negative fixtures. This is demo evidence, not a population
accuracy claim.

## 8. Server API

### 8.0 Readiness

`GET /api/health` adds a score-free care readiness block:

```json
{
  "ready": true,
  "care": {
    "ready": true,
    "cry_detector": {
      "ready": true,
      "model_version": "ast-audioset-baby-cry-v1"
    }
  }
}
```

`care.ready` is false when the cry detector or infant identity encoder is unavailable. The browser
must not enable Start listening until this value is true. The existing encoder readiness fields
remain unchanged.

### 8.1 Create

```http
POST /api/care-sessions
Content-Type: application/json

{"profile_id": 12, "tags": ["evening"]}
```

The profile must exist, be active, and have kind `infant`.

Response:

```json
{
  "session": {
    "id": 41,
    "status": "listening",
    "profile": {
      "id": 12,
      "display_name": "Baby 1",
      "kind": "infant",
      "status": "ready",
      "enrollments": 3
    },
    "started_at": "2026-07-30T20:15:00-04:00",
    "paused_at": null,
    "stopped_at": null,
    "completed_at": null,
    "last_sequence": 0,
    "decision": null
  }
}
```

### 8.2 Read

```http
GET /api/care-sessions/{session_id}
```

Returns the same public session shape. It never exposes paths, digests, embeddings, scores, or
margins.

### 8.3 Submit a segment

```http
POST /api/care-sessions/{session_id}/chunks
Content-Type: audio/mp4
X-Capture-Sequence: 1
X-Capture-Source: microphone
X-Capture-Device: iPhone Safari

<complete audio blob>
```

Response:

```json
{
  "session": {
    "id": 41,
    "status": "listening",
    "last_sequence": 1,
    "decision": null
  },
  "chunk": {
    "id": 88,
    "sequence": 1,
    "status": "matched_no_guidance",
    "reason_codes": ["insufficient_history"],
    "cry_presence": {
      "status": "detected",
      "label": "Infant cry detected",
      "reason_codes": [],
      "detected_window_count": 2,
      "analyzed_duration_s": 12.0,
      "model_version": "ast-audioset-baby-cry-v1"
    }
  }
}
```

When guidance is latched, `session.decision` is:

```json
{
  "id": 88,
  "latched_at": "2026-07-30T20:15:15-04:00",
  "profile": {
    "id": 12,
    "display_name": "Baby 1"
  },
  "guidance": {
    "status": "grounded",
    "headline": "What helped before",
    "interpretation": "This resembles earlier incidents for this profile.",
    "recommendation": "What helped before: held baby upright.",
    "evidence_summary": "Supported by 2 similar recorded incidents.",
    "support_count": 2,
    "incident_ids": [101, 97],
    "pattern": "similar time of day"
  },
  "basis": [
    "cry pattern was the strongest available signal",
    "occurred at a similar time of day"
  ],
  "scenarios": [
    {
      "episode_id": 101,
      "started_at": "2026-07-27T20:04:00-04:00",
      "interventions": [
        {
          "order": 1,
          "action": "held baby upright",
          "evidence": "held the baby upright"
        }
      ],
      "outcome": "The baby settled.",
      "outcome_src": "caregiver",
      "worked": true,
      "contributions": [
        "cry pattern was the strongest available signal",
        "occurred at a similar time of day"
      ],
      "audio_url": "/api/audio/episodes/101"
    }
  ]
}
```

Raw similarity, composite rank, paths, digests, embeddings, and hidden candidate profiles are
never public.

### 8.4 Pause, resume, and stop

```http
POST /api/care-sessions/{id}/pause
POST /api/care-sessions/{id}/resume
POST /api/care-sessions/{id}/stop
```

Each request has an empty JSON object body and returns the public session.

The browser stops or pauses its recorder before calling these endpoints. Stop waits for the
in-flight segment and the one bounded queued segment before calling the server.

### 8.5 Complete

```http
POST /api/care-sessions/{id}/complete
Content-Type: application/json

{
  "action": "Held the baby upright",
  "settled": true,
  "notes": "Settled after about two minutes",
  "tags": ["evening", "at home"]
}
```

Validation:

- `action` is required, trimmed, and limited to 500 characters;
- `settled` is `true`, `false`, or `null`;
- `notes` is optional, trimmed, and limited to 1000 characters;
- tags are optional strings, normalized, deduplicated, and limited to 20 entries;
- a selected matched chunk must exist.

The saved values are caregiver-sourced:

- the intervention evidence is the literal submitted action;
- `worked` is the submitted settled value;
- outcome is the literal selected state plus the optional note;
- `outcome_src` is `caregiver`;
- context includes the care session ID, selected chunk ID, selected profile ID, time, care-event
  IDs, and tags.

Repeated completion returns the original completed result and does not save another episode.

Before saving, the server transcribes the selected matched canonical segment once through the
existing local or configured speech path. It keeps the infant cry and caregiver speech in the same
raw mixture and never source-separates them. Transcription is not on the live suggestion path. A
transcription failure does not invent text and does not block the structured caregiver follow-up.

The saved episode uses the existing stable transcript labels so current and new incidents remain
compatible:

```text
Audio transcript: <automatic transcript from the representative segment>
Typed caregiver follow-up: <structured caregiver response>
```

The history serializer parses those labels into separate public segments. A legacy unlabeled
transcript remains `legacy_unlabeled_transcript`. A synthetic seed transcript remains
`synthetic_demo_memory`. Typed follow-up text is never presented as something heard in the
recording.

Literal action evidence retains its source only when the exact evidence occurs in exactly one
parsed transcript segment. Otherwise its source is `unknown`. No word or sentence timing is
available, so the API and browser never imply where in the audio a phrase occurred.

### 8.6 Discard

```http
DELETE /api/care-sessions/{id}
```

Discard removes unsaved managed segment files, marks the session discarded, and returns the public
session. Completed incidents are not deleted through this endpoint.

## 9. Persistence

Add two tables:

```text
care_session
  id
  profile_id
  status
  created_at
  paused_at
  stopped_at
  completed_at
  last_sequence
  latest_matched_chunk_id
  selected_chunk_id
  decision_json
  episode_id
  tags_json

care_session_chunk
  id
  session_id
  sequence
  created_at
  source_audio_path
  canonical_audio_path
  identity_audio_path
  audio_sha256
  status
  cry_status
  cry_reason_codes
  cry_model_version
  matched_profile_id
  reason_codes
  UNIQUE(session_id, sequence)
```

Add structured care events:

```text
care_event
  id
  profile_id
  event_type
  occurred_at
  details
  created_at
```

Allowed event types:

```text
feeding
sleep
diaper
soothing
note
```

Timestamps must be timezone-aware ISO 8601. Structured care events do not affect identity.
`context.build_current_context` may translate recent feeding, sleep-end, and diaper events into
deterministic context tags. It never produces a cause.

## 10. Profile, history, and care-event APIs

### 10.1 Baby details

```http
GET /api/profiles/{profile_id}
```

Response:

```json
{
  "profile": {
    "id": 12,
    "display_name": "Baby 1",
    "kind": "infant",
    "status": "ready",
    "enrollments": 3,
    "created_at": "2026-07-30T18:00:00-04:00",
    "memory_count": 6
  },
  "training_clips": [
    {
      "id": 31,
      "captured_at": "2026-07-30T18:02:00-04:00",
      "duration_s": 7.1,
      "playback_url": "/api/audio/enrollments/31"
    }
  ],
  "recent_care_events": []
}
```

Training clips are labeled in the browser by ordinal and captured time. Original upload filenames
are not retained and must not be invented.

### 10.2 Chronological history

```http
GET /api/profiles/{profile_id}/incidents?limit=25&cursor=MjAyNi0wNy0zMFQyMDoxNjowMC0wNDowMHwxMTk
```

Response:

```json
{
  "profile": {
    "id": 12,
    "display_name": "Baby 1",
    "kind": "infant",
    "status": "ready"
  },
  "incidents": [
    {
      "id": 119,
      "started_at": "2026-07-30T20:16:00-04:00",
      "timestamp_source": "capture_segment",
      "duration_s": 12.0,
      "actions": [
        {
          "order": 1,
          "action": "Held the baby upright",
          "evidence": "Held the baby upright"
        }
      ],
      "outcome": {
        "text": "The baby settled. Settled after about two minutes",
        "source": "caregiver",
        "settled": true
      },
      "speech": {
        "status": "available",
        "excerpt": "I held the baby upright..."
      },
      "context": {
        "hour_local": 20,
        "tags": ["evening", "at home"]
      },
      "provenance": {
        "kind": "caregiver",
        "label": "Recorded from caregiver input",
        "synthetic": false
      },
      "audio": {
        "status": "available",
        "url": "/api/profiles/12/incidents/119/audio",
        "role": "representative cry segment"
      },
      "detail_url": "/api/profiles/12/incidents/119"
    }
  ],
  "next_cursor": null
}
```

Chronological history does not show a similarity band because a band exists only relative to a
current query.

The list is newest first. The opaque cursor represents the `(started_at, id)` pair so tied or
backdated timestamps paginate deterministically. The list response keeps transcript text short.
`speech.excerpt` is derived from the stored audio transcript, limited to 160 characters, and
labeled as an automatic caregiver-speech transcript in the browser. It is never presented as words
spoken by the baby.

Only the following context fields are public:

- `hour_local`;
- normalized caregiver tags;
- resolved public feeding, sleep, diaper, soothing, and note facts.

Internal identity IDs, care-session IDs, selected chunk IDs, raw care-event IDs, seed slots,
capture metadata, paths, digests, acoustic features, and model versions never enter history
responses.

### 10.3 Full incident detail

```http
GET /api/profiles/{profile_id}/incidents/{incident_id}
```

Response:

```json
{
  "profile": {
    "id": 12,
    "display_name": "Baby 1",
    "kind": "infant",
    "status": "ready"
  },
  "incident": {
    "id": 119,
    "display_label": "Incident 6",
    "started_at": "2026-07-30T20:16:00-04:00",
    "timestamp_source": "capture_segment",
    "duration_s": 12.0,
    "speech": {
      "status": "available",
      "label": "What the caregiver said",
      "notice": "Automatic transcript. It may contain errors.",
      "segments": [
        {
          "source": "recorded_audio_transcript",
          "label": "Heard in the recording",
          "text": "I picked her up and held her upright."
        },
        {
          "source": "typed_caregiver_follow_up",
          "label": "Added after recording",
          "text": "Held the baby upright. Settled after about two minutes."
        }
      ],
      "evidence_excerpts": [
        {
          "kind": "intervention",
          "text": "picked her up",
          "label": "Action mentioned",
          "source": "recorded_audio_transcript"
        },
        {
          "kind": "intervention",
          "text": "held her upright",
          "label": "Action mentioned",
          "source": "recorded_audio_transcript"
        }
      ]
    },
    "actions": [
      {
        "order": 1,
        "action": "Held the baby upright",
        "evidence": {
          "text": "held her upright",
          "source": "recorded_audio_transcript"
        }
      }
    ],
    "outcome": {
      "text": "The baby settled. Settled after about two minutes",
      "source": "caregiver",
      "settled": true
    },
    "context": {
      "hour_local": 20,
      "tags": ["evening", "at home"],
      "care_events": []
    },
    "provenance": {
      "kind": "caregiver",
      "label": "Recorded from caregiver input",
      "synthetic": false
    },
    "audio": {
      "status": "available",
      "url": "/api/profiles/12/incidents/119/audio",
      "role": "representative cry segment"
    }
  }
}
```

The full detail endpoint returns only an incident that belongs to the requested profile. A profile
mismatch returns HTTP 404 and leaks no incident metadata. If no transcript was produced,
`speech.status` is `not_available`, `segments` and `evidence_excerpts` are empty, and the browser
says `No usable transcript was saved`. It does not claim that nobody spoke. Excerpts are literal
stored evidence spans only. The server never summarizes or invents speech for this view.

The representative audio is the selected matched cry segment used to save the incident, not a
claim that the entire care session was archived. The browser labels that distinction.

### 10.4 Profile-scoped incident audio

```http
GET /api/profiles/{profile_id}/incidents/{incident_id}/audio
```

The server verifies both `episode.subject_id == "profile-{profile_id}"` and that the stored file is
a managed canonical WAV. Missing audio and wrong-profile requests both return HTTP 404 without
revealing whether another profile owns the incident. History uses this route instead of the older
unscoped episode-audio route.

### 10.5 Care events

```http
GET /api/profiles/{profile_id}/care-events
POST /api/profiles/{profile_id}/care-events
```

Create body:

```json
{
  "event_type": "feeding",
  "occurred_at": "2026-07-30T18:30:00-04:00",
  "details": {}
}
```

Care events are displayed as context facts, never as causes.

## 11. Three-page browser contract for Claude

Use a single-document application. Switching pages must not reload the document or terminate the
microphone.

### 11.1 Listen

Must surface:

- active baby name and a profile-switch affordance while idle;
- local-server health;
- Start listening;
- an animated listening blob;
- elapsed session time from a wall clock;
- a persistent microphone-live indicator;
- a small analysis status;
- Pause or Resume and Stop;
- neutral listening with no suggestion card when the backend has nothing grounded;
- the first latched server suggestion;
- its exact support count;
- its basis statements;
- its supporting incidents and provenance;
- the stop-time structured follow-up;
- save, discard, connection-loss, interruption, and resume states.

Landscape takeover requirements:

- activate only when `session.decision.guidance.recommendation` is nonempty;
- keep the microphone-live state unmistakable;
- shrink the blob and controls;
- place Pause or Resume and Stop near the lower safe area;
- give the recommendation most of the available area;
- keep at least one evidence line visible without scrolling;
- never rely on automatic orientation lock;
- remain usable in portrait.

The first decision stays fixed until Stop.

### 11.2 History

Must surface:

- chronological incidents for the active baby;
- loading, empty, next-page, profile-not-found, and connection-error states;
- a clear incident number, recorded date, and local time;
- duration;
- recorded actions and their literal evidence;
- outcome;
- outcome provenance;
- worked, did not settle, or not recorded;
- safe context facts;
- a short caregiver-speech excerpt when available;
- playable representative incident audio while not listening;
- an open-full-detail action for each incident;
- a full incident view with separate Overview, What was said, Context, and Evidence tabs;
- the complete stored transcript with an automatic-transcript warning;
- recorded-audio transcript and typed follow-up rendered as separate labeled segments;
- literal speech evidence spans marked as action or outcome excerpts;
- a clear unavailable state when speech was not transcribed.

It must not display a query similarity band or invent a cause.

### 11.3 Baby

Must surface:

- baby name;
- server profile status;
- independent training-clip count;
- memory count;
- training clips with captured time, duration, and playback;
- recent feeding, sleep, diaper, soothing, and note events;
- a way to record additional training clips;
- the demo-preparation state for exactly five or at least six usable memories;
- loading, empty, and error states.

It must not invent age, birthday, photo, gender, cry type, health state, or diagnosis.

### 11.4 Shared browser behavior

- Keep one persistent application shell, health state, active profile, active session, and
  navigation.
- Use three navigation destinations: Listen, History, Baby.
- Mark the active destination with `aria-current`.
- Preserve 44-pixel minimum targets and safe-area padding.
- Keep server-authored guidance verbatim.
- Keep synthetic provenance impossible to miss.
- Block every audio player while the microphone is live.
- Show `No cry detected` as a brief neutral analysis state when the server returns
  `no_cry_detected`; do not create a suggestion card, profile result, history item, or incident.
- Show `Listening for a clearer cry` for `cry_uncertain`; do not imply that a cry was detected.
- Remove the manifest's portrait-only restriction.
- Handle iOS track mute, unmute, ended, page hide, and wake-lock failure honestly.
- Never say recording is active after the track ended.
- Never create client-authored care advice.

Claude may change composition, typography, animation, color nuance, illustration, spacing, and
transitions while honoring this behavioral contract.

## 12. Demo preparation and choreography

The public Baby 1, Baby 2, and Baby 3 folders are source groups based on app-install UUIDs. They
are demonstration proxies, not verified infant identities.

All enrollment, history, and live-query captures must traverse the same:

- playback speaker;
- volume;
- room;
- distance;
- orientation;
- recording microphone;
- browser ingest path.

The phone must record and the laptop must play. Never play and record on the same device.

Preparation:

1. Create Baby 1, Baby 2, and Baby 3.
2. Capture and enroll each folder's `01`, `02`, and `03` through the fixed rig.
3. Create exactly five Baby 1 prior incidents:
   - two captures of pattern A with one identical helpful action;
   - one capture of a neutral pattern marked unsuccessful;
   - two captures of pattern B with a different identical helpful action.
4. Use identical or omitted time and tags while validating acoustic pattern separation.
5. Keep every seeded item visibly labeled `seed`.
6. Save a database snapshot with five memories for the first video.
7. Complete one real or staged caregiver follow-up to create memory six.
8. Save a mature database snapshot for the second video and live demo.

Current candidate source choreography:

```text
Early no-suggestion capture: Baby 1 clip 02
Mature pattern A query:     Baby 1 clip 06
Mature pattern B query:     Baby 1 clip 04
Reserved retry:             Baby 1 clip 05
```

This order is a candidate until fixed-rig rehearsal passes. Clip 02 overlaps an enrollment source,
so it demonstrates the history threshold only and must not be cited as independent identity
evidence.

## 13. Demo evaluator

Add a dedicated care-demo evaluator. It must use captured fixed-rig files, not raw corpus uploads.

The evaluator passes only when:

1. The selected baby has at least two other enrolled infant profiles as comparison candidates.
2. Every planned positive query passes the cry-presence gate.
3. Speech, music, clapping, running water, room noise, a ringtone, and adult imitation each
   produce no identity attempt, no history lookup, no suggestion, and no incident.
4. The early state has exactly five usable memories.
5. The early query matches the selected baby but returns no recommendation.
6. Preview writes no episode.
7. Completion writes exactly one sixth episode.
8. Pattern A and pattern B each match the selected baby.
9. Both mature queries return grounded guidance.
10. The two recommendations differ.
11. The supporting incident-ID sets are nonempty and disjoint.
12. Every supporting incident belongs to the selected baby.
13. Every supporting audio URL returns HTTP 200.
14. Seeded evidence is visibly marked synthetic.
15. Every history detail exposes only its own profile's transcript and audio.
16. No raw score is present in any public payload.

Require five consecutive passes after the rig is frozen. A retry, wrong profile, repeated incident
set, missing audio, clock-dependent action, or changed capture path fails the choreography. Do not
lower thresholds during the presentation.

## 14. Error handling

- Invalid audio: record the reason, show no suggestion, continue listening.
- No cry detected: skip identity and history, show a brief neutral state, and continue listening.
- Cry uncertain: skip identity and history, ask only for a clearer cry, and continue listening.
- Cry detector unavailable: fail closed and block the infant care session.
- Another profile matched: do not reveal that profile's history in the selected baby's session.
- Identity uncertain: show no suggestion and continue.
- Insufficient history: show no suggestion and continue.
- No helpful prior action: show no suggestion and continue.
- Chunk upload failure: retain at most one retryable completed blob and continue recording.
- Server unavailable: show connection loss, stop claiming that analysis is active, and offer retry
  or safe stop.
- Track muted: display interrupted and require an honest resume.
- Track ended: stop the recording UI immediately.
- Pause: release microphone tracks and block chunks until resume.
- Stop during upload: finish capture, drain the bounded queue, then stop the server session.
- Complete without matched audio: return `no_matched_chunk` and do not write an incident.
- Duplicate complete: return the original completed result.
- Discard: remove unsaved segment audio.

## 15. Privacy, provenance, and claims

- Audio only. Never video.
- All processing and storage remain on the laptop.
- Every person whose voice may be captured must agree before recording.
- Profile history never crosses an identity boundary.
- Full transcript text appears only after opening one incident, not across every history card.
- Care context never affects identity.
- Time and care events are context, not a diagnosis.
- Cry presence is a gate, not a diagnosis, identity result, emotion label, or cause.
- Actions and outcomes retain caregiver, inferred, or seed provenance.
- Caregiver transcript text is automatic and may contain errors.
- Transcript excerpts are literal stored evidence spans, never generated summaries.
- Synthetic data is labeled in the primary card, history, and supporting evidence.
- No raw similarity or rank score is shown.
- No value is called a percentage confidence.
- The interface may say what helped before. It may not say what the cry means.

## 16. Verification

Implementation is not complete until all of the following pass:

- failing tests were observed before each production behavior was implemented;
- persistence and state-machine unit tests;
- cry-gate adapter tests and fail-closed tests;
- cry-negative tests for speech, music, clapping, water, room noise, ringtone, and adult imitation;
- mixed caregiver-speech plus infant-cry positive tests;
- proof that a non-cry chunk never calls identity or history retrieval;
- duplicate-sequence and idempotency tests;
- selected-profile history-isolation tests;
- first-grounded-decision latch tests;
- exactly-once completion tests;
- profile-details, history list, full incident detail, transcript-isolation, and care-event HTTP
  tests;
- profile-scoped incident-audio tests, including wrong-profile and missing-file 404 responses;
- browser tests at 430 by 932 and 932 by 430;
- navigation without document reload;
- persistent listening indicator and accessible controls;
- no suggestion for insufficient or unhelpful history;
- stable landscape suggestion takeover;
- playback blocked during listening;
- iPhone self-contained-segment FFmpeg decode test;
- three-minute foreground listening test;
- fixed-rig five-pass demo evaluator;
- fixed-rig cry-gate confusion matrix;
- the full Python suite;
- JavaScript syntax;
- Windows GitHub Actions;
- no em or en dash characters;
- no public debug scores, paths, digests, or embeddings.

The release notes must distinguish automated functional verification, fixed-rig rehearsal evidence,
and unproven population behavior.
