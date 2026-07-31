# Privacy

## Prototype scope

SootheTrace is a proof of concept, not a production account service. It has two
runtime modes with different data boundaries:

- Local mode is a single-user server that writes to one local database and
  audio root.
- Hosted mode gives each anonymous browser visitor an isolated, short-lived
  copy of the demo state.

Neither mode should be treated as a reviewed system for real family audio.
SootheTrace does not provide production authentication, encrypted storage,
regulatory compliance, or a complete privacy program.

## Data the prototype may handle

- audio uploaded from the browser or captured from the microphone
- canonical and normalized audio copies used for processing
- acoustic embeddings and similarity-related internal metadata
- profile names and enrollment references
- timestamps, caregiver tags, notes, actions, outcomes, and transcripts
- SQLite records and managed-audio paths

Audio, voice characteristics, caregiver notes, and infant-related records can
be sensitive personal data. Treat them accordingly.

## Local mode

Local mode is designed for one operator on one trusted computer. It has no
account boundary, tenant isolation, or automatic retention timer. All local
requests use the configured database and audio root. The default locations are
`data/episodes.db` and `data/audio`.

Local files are not encrypted vaults. Anyone with sufficient access to the
computer or its backups may be able to read them. The local operator is
responsible for recording consent, access to the computer, backups, sharing,
retention, and deletion.

Do not commit runtime databases, model caches, managed recordings, or generated
certificate keys. The repository ignores the normal runtime locations, but
that does not protect copies stored elsewhere.

## Hosted mode

Hosted mode is enabled only when the server runs behind a trusted HTTPS
terminating proxy. It uses an anonymous HttpOnly browser cookie as a session
token. It does not create a user account or verify a person's identity.

The first visitor request creates an isolated audio directory and clones the
read-only demo template into a visitor-specific SQLite database. This storage
allocation happens before recording consent so the browser can load the demo
profiles and history. The clone contains prepared demonstration state, not a
visitor recording.

Explicit consent is required before recording-related mutations are accepted.
After consent, recordings and changes are written only to that visitor's
database and managed-audio directory.

Each visitor session expires one hour after it is created. An expired session
cannot be reused. Its storage is removed when it is encountered or by the
request-driven cleanup process. The interface also exposes an immediate delete
action that removes the visitor registry entry, cloned database, and managed
audio directory.

These controls provide prototype isolation and bounded retention. They are not
account authentication, encryption at rest, a backup-erasure guarantee, or a
substitute for a reviewed privacy and security design.

## Optional speech processing

Speech processing is optional. When online transcription is configured, the
application sends the selected audio to that API provider. Optional reasoning
extraction receives transcript text and supplied action context. Review the
provider's current terms and data controls before enabling either feature, and
obtain consent from every person whose speech may be captured.

`IM_OFFLINE=1` asks the code to use a separately installed local Whisper CLI.
This avoids the configured transcription API call, but it does not make local
or hosted storage secure by itself.

## Public audio fixtures

The repository owner confirmed on July 30, 2026 that all three adults recorded
in `demo_assets/human_audio` agreed to public distribution of those ten
cry-imitation recordings. That permission applies to this small fixture set. It
does not turn the recordings into infant data, population evidence, or a
general-purpose biometric dataset.

The Baby 1, Baby 2, and Baby 3 fixtures under `demo_assets/baby_audio` come
from the external Donate-a-Cry corpus. Their source, pinned revision, stated
data licenses, and identity-grouping limits are documented in
[`demo_assets/baby_audio/LICENSE-DATA.md`](demo_assets/baby_audio/LICENSE-DATA.md).
Those source licenses do not establish verified infant identity or consent for
every biometric, privacy, medical, or commercial use.

The separate Baby X and Baby Y fixed-rig showcase files under
`demo_assets/baby_audio/warning-demo` have a distinct, incomplete provenance
record. Read that directory's `PROVENANCE.md` before using or redistributing
them.

Do not add new personal recordings, consent forms, or raw evaluation exports
to public Git history without documented provenance, permission to distribute,
a withdrawal process, and a privacy review.

## Contact and choices

No public hosted URL is claimed by this repository. Any public deployment must
publish operator contact details and jurisdiction-specific disclosures, and it
must define access, correction, deletion, withdrawal, incident response, and
processor-management procedures.
