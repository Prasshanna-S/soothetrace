# Third-party software, models, data, and assets

## Important scope

This file is an attribution and review checklist, not a legal clearance opinion. The MIT source licence applies only to original project code. Dependencies, model weights, datasets, audio fixtures, and images may have different terms.

## Runtime libraries

The project declares dependencies including NumPy, SciPy, SoundFile, Cryptography, PyTorch, TorchAudio, SpeechBrain, Hugging Face Hub, Transformers, OpenAI SDK, and python-dotenv. Each retains its own licence. Before distributing a binary, container, or hosted product, generate and review a complete dependency notice for the exact resolved versions.

## FFmpeg

FFmpeg is a system dependency used locally for audio decoding and conversion. FFmpeg builds can be LGPL, GPL, or include additional codec terms depending on build configuration. Distributors are responsible for selecting a compliant build and supplying required notices and source obligations.

## AudioSet AST cry-presence gate

The configured checkpoint identifier is `MIT/ast-finetuned-audioset-10-10-0.4593`, loaded through Transformers. It is a third-party model download and is not committed to this repository. Review the checkpoint card, its licence, AudioSet terms, and any attribution requirements before distribution or hosted use. The project applies its own label-selection and threshold logic; it does not own the underlying AST checkpoint.

## CryCeleb ECAPA checkpoint

The optional `human_imitation` path is configured to download `Ubenwa/ecapa-voxceleb-ft2-cryceleb` through SpeechBrain. The source code records an expected model licence of CC-BY-SA-4.0 and a CryCeleb dataset licence of CC-BY-NC-4.0, but this must be verified against the current model card and all upstream terms before release. Do not assume the model is cleared for commercial or hosted biometric use.

## Optional transcription and reasoning APIs

Online speech features use the configured API provider and are subject to that provider's current terms and privacy controls. Local Whisper CLI use is optional and separately installed. No Whisper model or API credential is bundled here.

## Donate-a-Cry fixtures

Some baby rehearsal fixtures identify their source as the Donate-a-Cry corpus at a pinned commit and carry an accompanying data notice. The source repository reports ODbL-1.0 for the database and DbCL-1.0 for contents. This does not itself settle privacy, personality-right, biometric, derivative-work, or commercial-use questions. Confirm the complete provenance and release basis before keeping or redistributing audio fixtures.

## Human audio and controlled baby demo audio

Human voice recordings, evaluation exports, and controlled baby demonstration media require separate provenance and consent review. They are not covered by this document or by the project MIT licence. Do not distribute them by default until a written release process, revocation process, and appropriate licence have been established.

## Visual assets

The repository includes local interface artwork. Its provenance must be recorded before public release. Keep author-created assets with a clear copyright statement, or replace third-party assets with assets that have a documented compatible licence and attribution.
