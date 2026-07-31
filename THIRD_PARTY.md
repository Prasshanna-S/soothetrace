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

Human Baby is configured to download `Ubenwa/ecapa-voxceleb-ft2-cryceleb` through SpeechBrain. Its checkpoint and dataset terms have not been independently cleared by this project. Verify the current model card and every upstream term before release. Do not assume the model is cleared for commercial or hosted biometric use.

## Optional transcription and reasoning APIs

Online speech features use the configured API provider and are subject to that provider's current terms and privacy controls. Local Whisper CLI use is optional and separately installed. No Whisper model or API credential is bundled here.

## Donate-a-Cry fixtures

Some baby rehearsal fixtures identify their source as the Donate-a-Cry corpus at a pinned commit and carry an accompanying data notice. The source repository reports ODbL-1.0 for the database and DbCL-1.0 for contents. This does not itself settle privacy, personality-right, biometric, derivative-work, or commercial-use questions. Confirm the complete provenance and release basis before keeping or redistributing audio fixtures.

## Human audio and controlled baby demo audio

The human fixture README records the repository owner's confirmation that all
recorded adult participants agreed to public distribution. The controlled baby
showcase notice records its fixed-rig capture lineage and the repository owner's
instruction to publish the test files. Neither statement is an independent
rights audit. The audio files are not covered by the project MIT licence. Reuse
still requires review of the notices, upstream source terms, consent scope, and
any withdrawal process.

## Visual assets

The repository owner supplied the local interface artwork during the design
collaboration. The exact creator, generation tool, and original licence were
not recorded. [web/img/README.md](web/img/README.md) therefore excludes these
assets from the project MIT licence and asks downstream users not to reuse them
until provenance is clarified.
