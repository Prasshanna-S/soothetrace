# Cry Memory System Map and Data Flow

This document separates three claims that must not be mixed:

1. Who does this recording acoustically resemble?
2. Which prior incidents belong to that confirmed profile?
3. What previously recorded action appears in the most similar worked incidents?

One mixed recording creates two acoustic views. Identity uses the fixed-level `identity.wav`.
Care-memory retrieval separately computes an MFCC87 fingerprint from `canonical.wav`, and only
after infant identity is confirmed. Server-local time and manual caregiver tags can rank that
profile's own memories. They do not identify the profile. Caregiver actions, outcomes, history, and
capture metadata also do not decide identity.

The current proof of concept does not infer a medical cause from a cry. Structured feeding, sleep,
and diaper events are planned but are not wired into the current database or API.

## Mind map

```mermaid
mindmap
  root((Cry Memory))
    Browser inputs
      One mixed audio recording
        Cry or imitation
        Any caregiver speech in the same audio
      Selected infant or human mode
      Manual caregiver tags
      Typed caregiver follow-up
        Can ground literal actions and outcome
        Stored with an explicit typed follow-up label
      Request metadata
        MIME type
        Capture source
        Device header containing browser user agent
    Managed audio views
      Exact source bytes
      Canonical WAV at 16 kHz mono
        Care retrieval fingerprint
        Speech transcription
        Evidence playback
      Fixed RMS identity WAV
        Identity encoders
        Duplicate digest
    Human identity
      CryCeleb ECAPA profile association
      Existing session participants
      Calibration and support state
      New participant gate only
        CryCeleb ECAPA pair view
        MFCC87 pair view with population baseline
        Two independent outliers must agree
    Infant identity
      MFCC87 identity embedding
      Population z-score and L2
      Same-kind infant enrollments
      Match margin and retry gates
    Care retrieval after infant match
      Separate canonical-audio fingerprint
      Confirmed profile boundary
      Six or more usable prior incidents
      Server-local hour
      Optional manual tags
      Cry 65 percent
      Time 20 percent
      Tags 15 percent
      Available weights are renormalized
    What helped before
      Top three similar incidents
      Worked incidents only
      Final recorded action
      Whole-history tally breaks ties
      Support count may be one
      Recorded outcome provenance
    Current incident save
      Audio transcript plus typed follow-up evidence
      Literal caregiver actions and outcome
      Typed follow-up retains its explicit label
      Server completion time
      Manual tags
      Seed provenance when synthetic
    Browser display
      Profile or participant direction
      Match leaning retry or unresolved state
      Ordinal evidence wording
      Exact supporting incident count
      Incident time
      Recorded action and outcome provenance
      Evidence playback
      No raw scores paths or digests
      No full evidence text tags or guidance pattern field
    Private retention
      Enrollment embeddings
      Query audio and acoustic audit
      Query embedding is transient
      Path-specific capture metadata
      Original upload filename is not retained
    Guardrails
      No cause or diagnosis
      No generated treatment
      No score shown as probability
      No cross-profile history
      Abstain when evidence is weak
    Candidate signals not wired
      Feeding sleep and diaper events
      Client capture time
      Room and device calibration
      Motion or soothing movement
      Optional sensors
```

## What builds each claim and what appears on screen

Time is part of the care-memory claim, not the identity claim. The current implementation uses the
laptop server's local hour because the browser does not yet send a trusted client capture time.
Caregiver tags are optional manual inputs. A missing tag is treated as missing information, not as
negative evidence.

```mermaid
flowchart TB
    subgraph IdentityInputs["Inputs that can affect identity"]
        IA["Fixed RMS identity.wav"]
        IK["Selected infant or human-imitation kind"]
        IE["Earlier same-kind enrollments or current-session participants"]
        IC["Kind-specific calibration and population baseline where MFCC87 requires it"]
        IS["Support, pending-pattern, duplicate, nomination, and retry state"]
    end

    subgraph IdentityRules["Kind-specific identity rules"]
        HI["Human existing-profile direction: CryCeleb ECAPA only"]
        HN["Human new-person pair gate: CryCeleb ECAPA plus MFCC87"]
        BI["Infant direction: MFCC87 with population z-score and L2"]
        IR["Match, leaning, retry, unresolved, invalid, or new-participant state"]
        IA --> HI
        IA --> HN
        IA --> BI
        IK --> HI
        IK --> HN
        IK --> BI
        IE --> HI
        IE --> HN
        IE --> BI
        IC --> HI
        IC --> HN
        IC --> BI
        IS --> HI
        IS --> HN
        IS --> BI
        HI --> IR
        HN --> IR
        BI --> IR
    end

    subgraph CareInputs["Inputs that can affect care-memory ranking after an infant match"]
        CA["Separate MFCC87 retrieval fingerprint from canonical.wav"]
        CT["Server-local hour at preview or completion"]
        CG["Optional manual caregiver tags"]
        CH["Only that confirmed profile's usable prior incidents"]
        CP["Those incidents' actions, worked state, outcomes, and provenance"]
    end

    subgraph CareClaim["Profile-grounded care-memory result"]
        CR["Rank incidents: cry 65%, time 20%, tags 15%, with missing weights renormalized"]
        CS["Inspect worked incidents among the top three"]
        CW["Select each incident's final action; whole-history tally is a tie-breaker"]
        CO["Return exact support count and recorded outcome provenance"]
        CA --> CR
        CT --> CR
        CG --> CR
        CH --> CR
        CR --> CS
        CP --> CS --> CW --> CO
    end

    IR -->|"Confirmed infant profile only"| CH

    subgraph CurrentSave["Inputs used when saving the current infant incident"]
        MX["Canonical mixed audio"]
        AT["Caregiver speech transcript"]
        TA["Optional typed caregiver follow-up"]
        TE["Stored evidence prefixes text as Typed caregiver follow-up"]
        TS["Literal caregiver actions and outcome grounded in the labeled evidence"]
        SV["Saved incident with audio, fingerprint, actions, outcome, time, tags, and provenance"]
        MX --> AT --> TE
        TA --> TE --> TS --> SV
        CT --> SV
        CG --> SV
    end

    subgraph Shown["What the current browser shows"]
        UI1["Participant or profile direction and current status"]
        UI2["Ordinal evidence wording or band, never a probability"]
        UI3["Grounded history summary and exact support count"]
        UI4["Incident time, recorded action, outcome provenance, and playback"]
        UI5["Not shown: raw scores, paths, digests, full evidence text, tags, or guidance pattern field"]
    end

    IR --> UI1
    IR --> UI2
    CO --> UI3
    CO --> UI4

    subgraph StoredNotClaim["Path-specific private retention, never claim evidence"]
        AU["Managed source, canonical, and identity audio plus private digests and paths"]
        AM["Live observation source; enrollment device string; nested baby-attempt ingest metadata"]
        QE["Enrollment embeddings persist; query embeddings are transient"]
        FN["Original upload filename and a uniform separate user-agent field are not retained"]
    end

    subgraph Excluded["Explicitly excluded from identity and cause claims"]
        EX1["Server time, caregiver tags, actions, outcomes, and care history do not identify"]
        EX2["No input is interpreted as hunger, pain, diagnosis, or medical cause"]
        EX3["Feeding, sleep, diaper, motion, room calibration, and sensors are not wired"]
    end
```

The interface can therefore say "this resembles Baby 2" and show that a similar recorded Baby 2
incident ended after rocking, with the exact number of displayed supporting incidents. It does not
show that tags caused the rank, and it cannot honestly say "this pattern means hunger," "rocking is
a treatment," or "time proves identity."

## End-to-end data flow

```mermaid
flowchart TB
    subgraph Browser["Phone or laptop browser"]
        A["Microphone recording or audio upload"]
        B["Selected mode: infant or human imitation"]
        C["Optional caregiver tags"]
        D["Optional typed caregiver follow-up for actions and outcome"]
        E["Content type, capture source, device header, and browser user agent"]
    end

    subgraph Ingest["Local laptop ingest"]
        F["Bounded MIME and byte validation"]
        G["source.ext: exact received evidence"]
        H["canonical.wav: FFmpeg 16 kHz mono"]
        I["identity.wav: fixed RMS normalization"]
        J{"Usable voiced signal?"}
    end

    A --> F --> G --> H --> I --> J
    E --> K["Path-specific audit metadata; original upload filename is not sent"]
    K --> DB[(SQLite and managed audio)]
    CAL[(Calibration thresholds and population baseline)]
    G --> FILES[(Managed audio files)]
    H --> FILES
    I --> FILES

    J -->|"No"| INVALID["Invalid result with a retry path"]
    J -->|"Yes"| MODE{"Selected mode"}
    B --> MODE

    subgraph Human["Human imitation session"]
        HE["CryCeleb ECAPA embedding"]
        HA["Existing-participant association uses ECAPA only"]
        HM["MFCC87 pair view with population baseline"]
        HN["Dual-view pair gate only for a possible new participant"]
        HS["Score-free session state transition"]
        HP["Provisional or established participant"]
        HT["Participant strip, latest result, timeline, and playback"]
    end

    MODE -->|"Human imitation"| HE --> HA --> HS
    MODE -->|"Human imitation"| HM --> HN --> HS
    HE --> HN
    CAL --> HA
    CAL --> HN
    HS --> HP --> HT
    HS --> HT
    HMEM[(Session status, participants, support counts, digests, observations, and pending patterns)]
    HMEM --> HA
    HMEM --> HN
    HS --> HMEM
    HMEM --> DB

    subgraph InfantIdentity["Infant identity gate"]
        IE["MFCC87 identity embedding from identity.wav"]
        IB["Population z-score and L2"]
        IP["Same-kind enrolled infant profiles"]
        IG{"Profile match accepted?"}
    end

    MODE -->|"Infant"| IE --> IB --> IP --> IG
    CAL --> IB
    IP <--> PROFILES[(Profiles and enrollments)]
    PROFILES --> DB
    IG -->|"No"| ABSTAIN["Leaning, retry, unresolved, or invalid"]

    subgraph Context["Current context after identity"]
        CLOCK["Current server-local hour"]
        TAGS["Manually entered caregiver tags"]
        CC["Current context"]
    end

    CLOCK --> CC
    C --> TAGS --> CC

    subgraph Retrieval["Confirmed-profile memory retrieval"]
        RF["Separate MFCC87 retrieval fingerprint from canonical.wav"]
        PH["Only the matched profile's prior incidents"]
        GATE{"At least six usable prior incidents?"}
        CRY["Cry-pattern component: 65 percent when all inputs exist"]
        TIME["Time-of-day component: 20 percent when present"]
        NOTES["Tag overlap component: 15 percent when present"]
        RANK["Renormalized composite ranking"]
        TOP["Up to three most similar incidents"]
    end

    IG -->|"Yes"| PH
    H --> RF
    RF --> CRY --> RANK
    CC --> TIME --> RANK
    CC --> NOTES --> RANK
    PH --> GATE
    GATE -->|"Yes"| CRY
    GATE -->|"Yes"| TIME
    GATE -->|"Yes"| NOTES
    PH <--> EPISODES[(Profile-isolated episode history)]
    EPISODES --> DB
    RANK --> TOP

    subgraph Guidance["History-grounded output"]
        WORKED["Worked incidents among the top three"]
        ACTIONS["Final recorded action in each worked incident"]
        OUTCOMES["Recorded outcomes and caregiver, inferred, or seed provenance"]
        TALLY["Whole-profile final-action tally used only as a tie-breaker"]
        SELECT["Select one prior action when available; support may be one incident"]
        OUTPUT["API guidance, support count, provenance, pattern field, and playback"]
        UI["UI shows profile direction, band, guidance, action, outcome provenance, time, exact support, and playback"]
        HIDDEN["UI does not show raw scores, tags, full evidence text, or guidance pattern field"]
    end

    GATE -->|"No"| NOTENOUGH["Not enough history yet"]
    TOP --> WORKED --> ACTIONS --> SELECT --> OUTPUT
    PH --> TALLY --> SELECT
    WORKED --> OUTCOMES --> SELECT
    OUTPUT --> UI

    subgraph Completion["Complete the current incident"]
        OFFLINE{"Offline mode enabled?"}
        LOCAL["Local Whisper and deterministic evidence extraction"]
        HOSTED["OpenAI transcription and Responses API when configured"]
        EMPTY["No key or transcription failure: no audio transcript"]
        EVIDENCE["Stored evidence: audio transcript plus clearly labeled typed follow-up"]
        EXTRACT["Literal caregiver actions and outcome grounded in stored evidence"]
        SAVE["Save current incident once with audio, fingerprint, time, tags, and provenance"]
    end

    H --> OFFLINE
    OFFLINE -->|"Yes"| LOCAL --> EVIDENCE
    OFFLINE -->|"No and API key exists"| HOSTED --> EVIDENCE
    OFFLINE -->|"No key"| EMPTY --> EVIDENCE
    LOCAL -.->|"Transcription failure"| EMPTY
    HOSTED -.->|"Transcription failure"| EMPTY
    D --> EVIDENCE --> EXTRACT --> SAVE
    CC --> SAVE
    SAVE --> EPISODES

    QEM["Query embeddings exist only during comparison and are not stored"]
    IE --> QEM
    HE --> QEM

    subgraph Future["Candidate signals not used in the current ranking"]
        CAREEVENTS["Structured feeding, sleep, and diaper events"]
        CLIENTTIME["Client capture time"]
        AMBIENT["Ambient-noise characterization"]
        MOTION["Motion or soothing movement"]
        ROOM["Room and device calibration"]
        SENSORS["Optional temperature or wearable signals"]
    end
```

When one of the three ranking components is absent, the available weights are renormalized. Missing
tags do not count as negative evidence. The browser sends capture source plus an
`X-Capture-Device` value containing its user agent. Live observations retain capture source,
accepted enrollments retain that device string, and baby attempts retain nested ingest metadata.
The original upload filename is not sent, and the standard user-agent field is not retained
uniformly. None of this metadata increases an identity or care-memory score.

The incident API can return a guidance `pattern` field and stored evidence text. That evidence
prefixes typed text with `Typed caregiver follow-up:` rather than presenting it as transcribed
speech. The browser does not render either field. Query embeddings are used in memory during
comparison and then discarded.

## What contributes to each public result

| Public result | Inputs used now | Shown now | Inputs explicitly excluded |
|---|---|---|---|
| Human participant direction | Identity audio; CryCeleb ECAPA existing-profile view; prior session recordings; calibration; support and pending state. MFCC87 joins ECAPA only for the possible-new pair gate. | Participant label, status, ordinal evidence wording, exact support, timeline, playback | Time, tags, care history, actions, outcomes, expected-person labels |
| Infant identity | Identity audio; MFCC87; same-kind infant enrollments; population normalization; calibrated match, margin, and retry gates | Profile direction, evidence band, retry, unresolved, or invalid state | Time, tags, outcomes, interventions, care events |
| Similar prior incident ranking | Confirmed profile; separate canonical-audio fingerprint; server-local hour; manually entered tags; only that profile's history | Grounded summary and incident cards, without raw component scores or tags | Other profiles, the current follow-up entered after preview, capture metadata, structured care events |
| What helped before | Worked incidents among the top three; each incident's final recorded action; whole-history tally as a tie-breaker; recorded outcome provenance | Prior action, outcome provenance, exact supporting incident count, incident time, playback | New treatment generation, diagnosis, unsupported action, minimum support greater than one |
| Current incident record | Canonical audio; server completion timestamp; caregiver speech transcript; optional typed caregiver follow-up; literal interventions and outcome grounded in clearly labeled stored evidence; manual tags | Completion status and the saved incident card. Full evidence text and tags are not rendered. | Inferred medical cause, client capture time |

## Current data contract at a glance

| Data point | Collected now | Used for identity | Used for care-memory output | Shown in the current browser |
|---|---:|---:|---:|---:|
| Current mixed audio | Yes | Yes, through identity.wav | Yes, through a separate canonical-audio fingerprint after identity | Human observation playback, and infant playback after the incident is saved |
| Selected infant or human-imitation kind | Yes | Yes | Selects the workflow | Reflected by the active mode |
| Earlier same-kind recordings | Yes | Yes | Profile boundary only | Participant strip or profile direction |
| Calibration and population baseline | Yes | Yes | No | Readiness only, not raw values |
| Server-local time | Yes | No | Yes, 20% when all ranking inputs exist | Incident time |
| Manual caregiver tags | Optional | No | Yes, 15% when all ranking inputs exist | Input control only; not repeated in the result |
| Cry-pattern similarity | Yes | Yes, through the kind-specific identity view | Yes, through the separate retrieval fingerprint at 65% when all inputs exist | Evidence wording or band, not a raw score |
| Prior interventions | Yes, from audio transcript, clearly labeled typed follow-up, or seed data | No | Yes | Selected prior action |
| Prior caregiver outcomes | Optional | No | Yes | Recorded outcome and provenance |
| Supporting incident count | Derived | Human session structure only | Yes; it may be one | Yes, exactly |
| Caregiver speech in the audio | Optional | It remains in the unseparated identity input | Can ground literal actions and fallback outcome evidence | Full transcript is not shown |
| Typed caregiver follow-up | Optional | No | Can ground literal actions and the caregiver-sourced outcome; it is clearly labeled in stored evidence | Its resulting actions and outcome can appear on the saved incident, but the full evidence text is not shown |
| Query embedding | Transient | Yes | No | No, and it is not stored |
| Capture source and browser user agent | Sent, with path-specific retention | No | No | No |
| Synthetic demo memory | Optional seed script | No | Yes, when deliberately seeded | Seed provenance distinguishes it from a caregiver report |
| Feeding, sleep, diaper, motion, room, or sensor data | No | No | No | No |

## Storage boundaries

| Store | Data | Purpose |
|---|---|---|
| Managed audio directory | Exact upload bytes under a managed name, canonical WAV, normalized identity WAV | Reproducible processing and evidence playback |
| SQLite | Profiles, persisted enrollment embeddings, identity audit without query embeddings, live sessions, observations, incidents, context, outcomes, provenance, baseline | Local state and profile isolation |
| Local model directory | CryCeleb checkpoint copies | Offline reuse after the first download |
| Browser memory | Current controls, selected or recorded clip, and rendered public response | Transient interaction state, not the source of truth |
| OpenAI API, when offline mode is disabled and a key exists | Canonical audio for transcription, then transcript text for evidence extraction | Optional hosted speech path |

The server response uses an allowlist. It does not return local filesystem paths, acoustic
embeddings, similarity scores, margins, or private digests to the browser.
