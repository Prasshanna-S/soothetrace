# Windows Backend Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task.

**Goal:** Make the Cry Memory backend install, start, and exercise its real identity flow on a standard 64-bit Windows 10 or Windows 11 computer.

**Architecture:** Keep the Python HTTP server and browser client platform-neutral. Isolate operating-system differences at capture, model-cache, certificate, and setup boundaries. Validate those boundaries with unit tests and exercise the actual server on GitHub's Windows runner.

**Tech Stack:** Python 3.12, PowerShell, FFmpeg, SQLite, SpeechBrain ECAPA, PyTorch, GitHub Actions

## Global Constraints

- Preserve the measured identity behavior and all existing public demo assets.
- Keep PyTorch and TorchAudio on an officially compatible exact version pair.
- Do not require PowerShell virtual-environment activation.
- Do not require Windows Developer Mode or administrator-only symbolic links for the model cache.
- Keep the browser microphone and audio upload as the primary demo inputs.
- Keep the existing macOS path working.
- Run new behavioral tests red before changing production code.

### Task 1: Establish a clean baseline and claim the work

**Files:**
- Modify: `docs/TASKS.md`
- Modify: `docs/MESSAGES.md`

1. Run the complete Python suite with localhost integration-test access.
2. Record the existing result.
3. Claim O8 as product workstream and document the cross-owner maintenance scope.

### Task 2: Make local microphone capture platform-aware

**Files:**
- Modify: `tests/test_product_session.py`
- Modify: `src/session.py`
- Modify: `tools/doctor.py`

1. Add tests for Windows DirectShow, macOS AVFoundation, and Linux ALSA input arguments.
2. Run the tests and confirm the Windows case fails.
3. Add one platform boundary that returns the correct FFmpeg input arguments.
4. Reuse it in CLI capture and the operator preflight where practical.
5. Run focused tests and confirm all platforms pass.

### Task 3: Remove the Windows model-cache privilege failure

**Files:**
- Modify: `tests/test_acoustics_identity.py` or add a focused encoder test
- Modify: `src/encoders.py`
- Modify: `requirements.txt`

1. Add a test that requires SpeechBrain's copy strategy.
2. Run it and confirm the current default symlink strategy fails the assertion.
3. Pass `LocalStrategy.COPY` when downloading either ECAPA encoder.
4. Pin PyTorch and TorchAudio to the same officially supported version.
5. Verify the Windows dependency resolution produces a matched pair.

### Task 4: Generate iPhone HTTPS certificates without Bash

**Files:**
- Modify: `tests/test_mobile_capture_spike.py`
- Add: `spikes/mobile_capture/certificates.py`
- Add: `spikes/mobile_capture/make_cert.py`
- Modify: `spikes/mobile_capture/make_cert.sh`
- Modify: `requirements.txt`

1. Add tests for generated CA and server certificate properties and SAN values.
2. Run them and confirm the portable generator does not exist.
3. Implement certificate creation with Python's `cryptography` package.
4. Make the existing shell entry point delegate to the Python generator.
5. Verify the resulting server certificate and mobile profile end to end.

### Task 5: Fix Windows-only display and diagnostics issues

**Files:**
- Modify: `tests/test_product_render.py`
- Modify: `src/render.py`
- Modify: `tools/doctor.py`

1. Add a Windows-like `strftime` regression test.
2. Confirm the valid timestamp incorrectly falls back.
3. Format day and hour without platform-specific directives.
4. Extend diagnostics to identify the operating system, exact Torch versions, FFmpeg, and model warm status.

### Task 6: Add a native PowerShell setup and verification path

**Files:**
- Modify: `README.md`
- Modify: `docs/DEMO-READY.md`
- Add: `scripts/setup_windows.ps1`
- Add: `scripts/run_windows.ps1`

1. Add a repeatable Windows bootstrap that installs Python dependencies, clones the public baseline corpus, and builds the database.
2. Add a server launcher that resolves repository-relative paths safely, including paths containing spaces.
3. Document desktop HTTP, phone HTTPS, health checks, file upload, microphone capture, and common Windows failures.
4. Keep commands copyable in an ordinary PowerShell window.

### Task 7: Prove the backend on a real Windows runner

**Files:**
- Add: `.github/workflows/windows-backend.yml`
- Add or modify: focused Windows smoke tests

1. Install Python 3.12 and FFmpeg on `windows-latest`.
2. Install the real dependency set.
3. Run platform-focused unit tests.
4. Start the actual HTTP server from a path containing spaces.
5. Poll `/api/health`, load the UI, create a live session, and ingest a demo audio file.
6. Warm and run the adult encoder against a bundled consenting-participant clip.
7. Fail the job on startup, decode, model-load, or API regressions.

### Task 8: Revalidate, document evidence, and publish

**Files:**
- Modify: `docs/MESSAGES.md`
- Modify: `docs/TASKS.md`

1. Run the complete Python suite.
2. Run JavaScript syntax, documentation safety, browser layout, and real-audio evaluators.
3. Run the dependency resolver for Windows Python 3.12.
4. Push the branch and require a green Windows Actions run.
5. Mark O8 done with exact evidence, merge to main, and verify a fresh public clone.
