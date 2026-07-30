# Security

## Prototype warning

SootheTrace is not ready to receive real user data from the public internet. It lacks production authentication, authorization, multi-user isolation, encryption-at-rest controls, operational monitoring, and a security review.

## Supported local use

- Run the HTTP development server only on loopback addresses such as `127.0.0.1`.
- Do not expose the local server, SQLite database, managed-audio directory, model cache, or development certificate authority to the internet.
- Keep API keys in environment variables or a local ignored configuration file. Never commit keys, certificates, private keys, databases, recordings, or generated audio.
- Treat uploaded audio and transcripts as sensitive. Use a machine and backups you control.
- Verify third-party model sources and dependency versions before use.

## Reporting a vulnerability

Please do not file public issues for a vulnerability that could expose recordings, keys, or a running deployment. Contact the repository maintainers privately through the hosting platform's private reporting channel, with reproduction steps, impact, and a safe proof of concept.

Until a dedicated security contact is published, do not send secrets or personal recordings in a report.

## Deployment gate

Before any hosted release, complete threat modeling, authentication and authorization design, secure secret management, encrypted transport and storage, tenant isolation, dependency and model supply-chain review, logging and incident response design, backup and deletion testing, and an independent security review.
