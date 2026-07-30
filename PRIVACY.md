# Privacy

## Current status

SootheTrace is a prototype. Do not use it with real family audio unless you understand and accept the local data handling described below. It has no production authentication, encryption, retention policy, account model, or deletion workflow.

## Data the prototype may handle

- audio uploaded from the browser or selected from a file
- canonical and normalized audio copies used for processing
- acoustic embeddings and similarity-related internal metadata
- profile names and enrollment references
- timestamps, caregiver tags, notes, actions, outcomes, and transcripts
- local SQLite records and managed-audio paths

Audio, voice characteristics, caregiver notes, and infant-related records can be sensitive personal data. Treat them accordingly.

## Local mode

In the current local mode, the Python server stores data under the configured data root. The default locations are `data/audio` for managed audio and `data/episodes.db` for SQLite state. They are local filesystem storage, not encrypted vaults. Anyone with sufficient access to the machine or its backups may be able to access them.

Do not commit these files. The repository ignores the normal runtime directories, but users remain responsible for their own backups, sharing settings, and device security.

## Optional cloud speech processing

Speech processing is optional. When online transcription is configured, the application sends the audio passed to the transcription client to that API provider. Optional reasoning extraction receives transcript text and supplied action context. Review the provider's current terms and data controls before enabling either feature, and obtain consent from every person whose speech may be captured.

`IM_OFFLINE=1` asks the code to use a separately installed local Whisper CLI instead. This avoids the configured transcription API call, but it does not make local storage secure by itself.

## Hosted future

`https://HOSTED_URL/` is only a deployment placeholder. A real hosted service must publish its own privacy notice and implement reviewed controls for authentication, authorization, encryption in transit and at rest, tenant isolation, retention, export, deletion, incident response, and processor management before accepting personal audio.

## Audio fixtures

Do not add personal recordings, consent forms, or raw evaluation exports to public Git history. Public audio fixtures require documented provenance, a deliberate distribution licence, a withdrawal process, and a privacy review. The presence of an audio file in a development tree does not establish permission to publish it.

## Contact and choices

This repository does not operate a public hosted service or collect account data. If a public service is deployed, this document must be replaced or supplemented with contact details, jurisdiction-specific disclosures, and a process for access, correction, deletion, and withdrawal requests.
