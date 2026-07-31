# Security

## Prototype warning

SootheTrace is not a production service. Local mode is single-user. Hosted mode
adds anonymous per-visitor isolation and short-lived storage, but it does not
provide user accounts, verified identity, role-based authorization,
encryption-at-rest controls, mature operational monitoring, or an independent
security review.

## Local mode

- Run plain HTTP only on a loopback address such as `127.0.0.1`.
- Use the documented trusted local HTTPS setup for phone testing.
- Do not expose the local SQLite database, managed-audio directory, model
  cache, development certificate authority, or private keys to the internet.
- Keep API keys in environment variables or an ignored local configuration
  file.
- Treat recordings, transcripts, embeddings, and caregiver notes as sensitive.
  Use a computer and backups you control.

Local mode has one shared database and audio root. It is not safe for unrelated
or mutually untrusted users.

## Hosted prototype controls

When launched with `--behind-tls-proxy`, the service expects a trusted host to
terminate HTTPS. The current hosted path provides:

- an anonymous `Secure`, `HttpOnly`, `SameSite=Lax` visitor cookie;
- same-origin checks on mutation requests;
- one cloned SQLite database and one managed-audio directory per visitor;
- explicit consent before recording-related mutations;
- a fixed one-hour visitor-session expiry;
- request-driven removal of expired visitor storage;
- an immediate visitor-data delete endpoint;
- bounded request bodies, allowlisted static routes, `Cache-Control: no-store`,
  a restrictive microphone permissions policy, and common response hardening
  headers.

The visitor database and directory are created before consent so the demo can
load. Consent gates visitor recording mutations, not allocation of the
visitor-specific demo clone.

The anonymous cookie is a bearer token, not authentication. Anyone who obtains
it during its valid hour may act as that visitor. The current single-process
service also relies on SQLite and a process-level inference lock. Do not scale
it to multiple instances without redesigning state, locking, and cleanup.

## Remaining deployment work

Before accepting real family audio, complete threat modeling, account and
authorization design, secure secret management, encryption at rest, durable
audit and incident-response procedures, abuse and rate-limit controls, backup
and deletion testing, dependency and model supply-chain review, and an
independent security assessment.

## Reporting a vulnerability

Please do not file a public issue for a vulnerability that could expose
recordings, keys, or a running deployment. Contact the maintainers privately
through the hosting platform's private reporting channel with reproduction
steps, impact, and a safe proof of concept.

Until a dedicated security contact is published, do not send secrets or
personal recordings in a report.
