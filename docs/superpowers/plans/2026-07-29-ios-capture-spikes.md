# iOS Capture Spikes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether an iPhone Safari microphone capture survives three untouched minutes
with the phone face down, prove the exact HTTPS/settings/MIME/upload/ffmpeg path, and measure the
real offline Whisper session path with no upstream internet.

**Architecture:** A throwaway stdlib Python HTTPS server serves one minimal diagnostic page and
accepts raw MediaRecorder blobs. Spike A records one uninterrupted blob first and logs browser
events locally; only after that result may the page expose the Auto-Lock and bounded-chunk
mitigations. Spike B uploads one complete blob to a server-generated session, where ffmpeg
decodes it to 16 kHz mono WAV and the server returns measured duration, level, digest, and
fingerprint status.

**Tech Stack:** Python 3.12 standard library, OpenSSL, Safari MediaRecorder/getUserMedia,
JavaScript, ffmpeg/ffprobe, existing numpy/scipy fingerprint code.

## Global Constraints

- Do not implement product-design steps 3-8.
- Do not add profile, identity, scenario, guidance, or final web-app code.
- Phone records; MacBook is the separate playback source.
- Spike A precedes Spike B.
- Spike C follows the phone-path spikes and exercises the real `session.finish()` path.
- Spike A first uses one uninterrupted `MediaRecorder`, not chunking.
- Phone is face down and untouched for exactly three minutes.
- Screen-lock survival is observed, not assumed.
- If uninterrupted capture dies, test Auto-Lock=Never, then bounded short recordings.
- All uploaded paths are generated server-side.
- Generated CA keys, certificates, uploads, and decoded WAVs stay under ignored `data/audio/`.
- The page must show an explicit red recording state and never request video.

---

### Task 1: Certificate bootstrap and diagnostic server

**Files:**
- Create: `spikes/mobile_capture/server.py`
- Create: `spikes/mobile_capture/make_cert.sh`
- Test: `tests/test_mobile_capture_spike.py`

**Interfaces:**
- Produces: `SpikeServer`, `create_session()`, `decode_upload()`, and HTTPS routes used by both
  spikes.

- [ ] **Step 1: Write failing server tests**

Test that `POST /api/session` returns a server-generated UUID and that invalid session/sequence
input is rejected before any filesystem path is formed.

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
.venv/bin/python -m unittest tests.test_mobile_capture_spike -v
```

Expected: import failure because `spikes.mobile_capture.server` does not exist.

- [ ] **Step 3: Implement the minimum server**

Use `ThreadingHTTPServer`, strict content-length limits, JSON responses, `Cache-Control:
no-store`, and generated storage paths rooted at `data/audio/mobile-capture-spike`.

- [ ] **Step 4: Generate a local CA and LAN certificate**

`make_cert.sh 10.21.6.4` creates:

```text
data/audio/mobile-capture-spike/certs/rootCA.pem
data/audio/mobile-capture-spike/certs/rootCA.key
data/audio/mobile-capture-spike/certs/server.pem
data/audio/mobile-capture-spike/certs/server.key
```

The server certificate SAN includes `IP:10.21.6.4`, `DNS:localhost`, and `IP:127.0.0.1`.

- [ ] **Step 5: Verify tests GREEN**

Run the focused test and then all tests.

### Task 2: Spike A - uninterrupted three-minute capture

**Files:**
- Create: `spikes/mobile_capture/index.html`
- Modify: `spikes/mobile_capture/server.py`
- Test: `tests/test_mobile_capture_spike.py`

**Interfaces:**
- `POST /api/events` stores timestamped lifecycle events.
- `POST /api/upload` accepts the final uninterrupted blob.
- `GET /api/report?session=<uuid>` returns events and decode status.

- [ ] **Step 1: Write failing route tests**

Verify ordered event storage, blob-size limits, server-generated filenames, and report shape.

- [ ] **Step 2: Confirm RED**

Run the focused suite and check that missing routes fail for the expected reason.

- [ ] **Step 3: Implement the diagnostic page**

The page:

- requests audio only;
- starts one uninterrupted `MediaRecorder`;
- records `visibilitychange`, `pagehide`, `freeze`, track `mute`, `unmute`, and `ended`;
- displays elapsed time from a monotonic clock;
- stops automatically after 180 seconds;
- uploads the complete blob only after stop;
- shows no chunking control until the uninterrupted result exists.

- [ ] **Step 4: Run automated tests**

The automated suite verifies route and page invariants. It cannot prove iOS behavior.

- [ ] **Step 5: Execute on the iPhone**

Install and fully trust `rootCA.pem`, open `https://10.21.6.4:8443`, start capture, place the
phone face down, and do not touch it for three minutes.

Record:

- whether the screen locked;
- elapsed time observed on return;
- whether `dataavailable` and `stop` fired;
- final blob size and MIME;
- lifecycle/track events;
- whether ffmpeg decoded the blob and its measured duration.

- [ ] **Step 6: Only on failure, execute mitigations**

First repeat with iOS Auto-Lock set to Never using the same uninterrupted recorder. If that
still fails or stalls, enable ten-second complete bounded recordings and repeat for three
minutes.

### Task 3: Spike B - settings, MIME, upload, and decode

**Files:**
- Modify: `spikes/mobile_capture/index.html`
- Modify: `spikes/mobile_capture/server.py`
- Test: `tests/test_mobile_capture_spike.py`

**Interfaces:**
- Browser submits requested and applied audio settings.
- Server returns `sha256`, decoded duration, mean/peak dB, sample rate, channel count, and
  fingerprint dimension or null.

- [ ] **Step 1: Write failing decode/metadata tests**

Use a generated WAV fixture and a deliberately corrupt upload. Verify successful ffmpeg decode
and explicit corrupt-audio failure.

- [ ] **Step 2: Confirm RED**

Run the focused suite and see the missing decode result fail.

- [ ] **Step 3: Implement minimal decode and measurement**

Run ffmpeg without a shell:

```text
ffmpeg -v error -y -i <upload> -ac 1 -ar 16000 <decoded.wav>
```

Measure the decoded file with existing audio loading/fingerprint functions.

- [ ] **Step 4: Execute one real phone upload**

Report requested vs applied settings, actual selected/returned MIME, byte size, ffmpeg result,
duration, levels, and fingerprint status.

- [ ] **Step 5: Run all tests and write the spike result**

Save measured results to `docs/SPIKE-IOS-CAPTURE-RESULTS.md`. The result either unblocks a
foreground/screen-awake hands-free proof of concept or blocks the session framework with the
observed failure.

### Task 4: Spike C - offline transcription through the real loop

**Files:**
- Modify only if a spike defect is found: `src/speech.py`, `src/session.py`
- Test: `tests/test_product_speech.py`, `tests/test_product_session.py`
- Create: `docs/SPIKE-OFFLINE-TRANSCRIPTION-RESULTS.md`

**Interfaces:**
- Consumes: `IM_OFFLINE=1`, the installed local `whisper` CLI, and a real mixed audio fixture.
- Produces: measured transcript, intervention extraction result, saved Episode, and end-to-end
  wall-clock latency.

- [ ] **Step 1: Verify the local CLI and model are actually available**

Record the resolved executable, version/help output, local model path if reported, and whether a
first invocation attempts any download.

- [ ] **Step 2: Run with network unavailable**

Set `IM_OFFLINE=1`, remove any usable API credential from the process environment, and run
`session.finish()` on a real caregiver-plus-cry recording. The acoustic path and store must still
complete.

- [ ] **Step 3: Measure and judge the transcript**

Record:

- audio duration;
- total `session.finish()` wall-clock latency;
- transcription latency if separable;
- verbatim transcript;
- whether the essential caregiver action words are present;
- extracted interventions and evidence spans;
- saved `outcome_src`;
- whether any network request was attempted.

- [ ] **Step 4: If a defect appears, reproduce it with a failing test before fixing**

Do not change the production speech/session code merely to improve a subjective transcript.
Only fix a deterministic integration defect that has a failing automated test.

- [ ] **Step 5: Run the full suite and write the result**

The report must say whether local Whisper is usable as the likely demo configuration, usable
only as degraded mode, or blocked, with measured latency rather than an estimate.
