# Technical architecture

## Scope

SootheTrace is a local-first prototype in which a browser client sends audio to a Python server. A future hosted version should keep the browser and API at one HTTPS origin. The source tree does not yet provide production authentication, encrypted storage, retention controls, or multi-tenant isolation.

## Data flow

```mermaid
flowchart TD
    A["Microphone or selected audio file"] --> B["Complete browser audio segment"]
    B --> C["Validate MIME and size"]
    C --> D["FFmpeg local decode to 16 kHz mono PCM WAV"]
    D --> E["Canonical audio retained in managed local storage"]
    D --> F["Fixed RMS identity copy"]
    F --> G["AudioSet AST gate"]
    G -->|"No or uncertain infant-cry-like evidence"| H["Abstain and show no care suggestion"]
    G -->|"Cry-like evidence"| I["Acoustic profile check"]
    I --> J["MFCC87 for infant profiles"]
    I --> K["Optional CryCeleb ECAPA for human-imitation profiles"]
    J --> L{"Selected profile accepted?"}
    K --> L
    L -->|"No or uncertain"| M["Abstain, retry, or unresolved state"]
    L -->|"Yes"| N["Read only this profile's prior incidents"]
    O["Current time"] --> P["Time-of-day similarity"]
    Q["Caregiver tags"] --> R["Tag overlap"]
    F --> S["Cry-pattern similarity"]
    N --> S
    N --> T["Previous actions and caregiver-reported outcomes"]
    P --> U["Heuristic incident ranking"]
    R --> U
    S --> U
    T --> V["Grounded action from the selected prior incident"]
    U --> V
    W["Optional transcript and caregiver note"] --> X["Transcript-supported action and outcome extraction"]
    X --> T
    V --> Y["Evidence-backed suggestion: what helped before"]
    Y --> Z["Caregiver records what was tried and whether it helped"]
    Z --> AA["SQLite episode, metadata, and managed audio references"]
    AA --> N
```

The diagram separates identity from retrieval intentionally. Current time, tags, transcripts, notes, previous actions, and outcomes never decide whose audio was recorded. They are eligible only after the selected profile passes the acoustic gate.

## Audio ingest and storage

`src/audio_ingest.py` accepts bounded supported audio uploads, retains source bytes, and uses local FFmpeg to create a 16 kHz mono PCM WAV. It creates a separate fixed-RMS identity WAV. No source separation, pitch processing, compression, or limiting is applied in the identity copy.

The prototype stores audio under the configured data root and persists application state in SQLite. Source paths, canonical paths, embeddings, digests, and private scoring information are implementation data. Public responses are allowlisted to avoid returning those internal details. This is not encrypted or authenticated storage.

## Infant-cry presence gate

The gate loads `MIT/ast-finetuned-audioset-10-10-0.4593` through Transformers. It reads two AudioSet labels, `Baby cry, infant cry` and `Crying, sobbing`, and applies project-specific thresholds plus a dominance rule.

This makes it a cry-presence filter, not an infant identifier. It reports infant-cry-like evidence for the current segment. It does not prove a biological infant, identify a particular infant, or determine why someone is crying. Gate failure is designed to block the downstream care flow.

## Acoustic profile paths

### Custom MFCC87 infant representation

The infant path uses `mfcc87-v1`, a project-specific deterministic feature representation rather than a trained neural model. It summarizes:

- 20 MFCC means and 20 MFCC standard deviations
- 20 delta-MFCC means and 20 delta-MFCC standard deviations
- pitch mean, standard deviation, 10th percentile, and 90th percentile
- spectral-centroid mean and standard deviation
- voiced-frame fraction

The implementation uses 1.5 second windows with a 0.75 second hop and averages usable window vectors. It then z-scores every vector against a stored population baseline and L2-normalizes it before cosine comparison. Raw MFCC87 cosine values are not valid comparison scores and must not be shown as confidence.

MFCC87 is the configured infant-demo representation. It is channel-sensitive and has only controlled fixed-rig evidence in this project.

### Optional CryCeleb ECAPA path

The registry can load the `Ubenwa/ecapa-voxceleb-ft2-cryceleb` ECAPA checkpoint through SpeechBrain. Its embeddings are L2-normalized directly and are not z-scored with the MFCC87 population baseline.

Current source uses this path for the separate `human_imitation` mode, where adults imitate cries. It is an optional model download, not a bundled model weight and not the shipped infant-demo default. The small adult-imitation result does not establish infant performance. Review the checkpoint card and applicable model and dataset terms before any hosted or commercial use.

## Profile decision and abstention

The server compares an input only with same-kind enrolled profiles. It can return a match, a weak or uncertain direction, a retry state, an unresolved state, or invalid input. A successful acoustic match is not a proof of identity. The current interface uses ordinal bands rather than presenting cosine similarity as a percentage confidence.

## Retrieval and suggestion

Once an infant profile is accepted, `src/retrieve.py` reads only that profile's past incidents. It scores candidates with a fixed heuristic:

| Available signal | Base weight | Meaning |
|---|---:|---|
| Cry-pattern similarity | 65% | Acoustic similarity to a prior incident |
| Time of day | 20% | Cyclic similarity of local hour |
| Caregiver tags | 15% | Jaccard overlap of supplied tags |

When a signal is unavailable, it is omitted and the other available weights are renormalized. These values are product choices, not a learned clinical model, probability, or causal explanation. The output should be read as: "this recorded action helped in a prior, acoustically and contextually similar incident," not "this is the action that will help now."

## Optional transcription and reasoning extraction

Speech processing is separate from the acoustic path. In default online mode, the configured transcription API model is `gpt-4o-transcribe`. With `IM_OFFLINE=1`, the code calls an externally installed Whisper CLI. The local Whisper dependency is optional and is not provisioned by `requirements.txt`.

An optional reasoning-model call can extract caregiver actions and outcomes from a transcript. It is instructed to return literal transcript evidence, and the implementation rejects unsupported evidence before storing it. A local regex extractor is available as a fallback. No generative model is used for infant-cry detection, acoustic identity, or causal interpretation.

## Hosted architecture requirements

The desired deployment presents the browser and API at one HTTPS origin, represented in public documentation as `https://HOSTED_URL/`. Before it can handle real audio, it needs authentication, authorization, tenant isolation, encrypted storage and transport, deletion and retention workflows, backup policy, operational monitoring, model supply-chain review, and privacy and security review.
