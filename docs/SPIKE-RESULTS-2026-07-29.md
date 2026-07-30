# Mobile Capture and Offline Speech Spike Results

Date: 2026-07-29  
Owner: `product workstream`  
Status: Spike A pass; Spike B pass with a level-gate finding; Spike C transcription pass with an offline-extraction gap

These are proof-of-concept measurements, not production claims.

## Spike A - iPhone Safari continuous capture

### Setup

- Client: iPhone Safari
- Transport: trusted local HTTPS at `https://10.21.6.4:8443`
- Capture: one uninterrupted `MediaRecorder`
- Target duration: 180 seconds
- Test condition: phone face down; screen locked after capture began
- Session: `1e9685db-b775-41bc-b627-f6192119f6a3`

### Measured result

- Recording began at `2026-07-29T23:48:03.496Z`.
- Page became hidden at 26.253 seconds.
- While hidden, every reported recorder state remained `recording`.
- The microphone track remained `live` and was never reported muted.
- Heartbeats slowed from about two seconds to about three seconds after hiding.
- Timer requested stop at 180.054 seconds.
- Safari emitted one 3,407,739-byte blob at 180.190 seconds.
- Upload completed at 180.741 seconds while the page was still hidden.
- ffprobe measured 180.161 seconds of AAC audio at 48 kHz stereo in an MP4 container.

### Verdict

**PASS for the measured three-minute proof-of-concept case.** Screen lock did not stop,
suspend, or truncate capture. Mild JavaScript timer throttling did not affect the recording.
The Auto-Lock=Never and short-chunk mitigations were therefore not needed in this run.

This does not establish behavior beyond three minutes or across all iOS versions.

## Spike B - HTTPS, microphone facts, MIME, upload, and decode

### Browser facts

- Secure context: true
- Selected recorder MIME: `audio/mp4;codecs=mp4a.40.2`
- Actual blob MIME: `audio/mp4; codecs=mp4a.40.2`
- Applied sample rate: 48 kHz
- Applied `echoCancellation`: false
- Safari did not expose applied AGC or noise-suppression settings.

The MIME parser must tolerate optional whitespace after the semicolon.

### Audible capture

- Session: `0260a218-d5fc-4be6-93c0-bc22b0000831`
- Source SHA-256: `a56f161422b209317c38a1b8bd4c756a24317ac2c9b41071838647dda45bc8da`
- Source bytes: 753,150
- Decoded duration: 40.660 seconds
- Canonical decode: 16 kHz, mono, PCM WAV
- Mean level: -44.103 dB
- Peak level: -22.807 dB

### Fingerprint finding

The raw decoded recording produced no fingerprint. The identity encoder's voiced-frame gate is
fixed at -32 dB, and no 1.5-second window supplied the required 0.3 seconds above that gate.

Applying ffmpeg `loudnorm=I=-23:TP=-2:LRA=11` to the same decoded recording recovered a complete
87-dimensional fingerprint. The upload and identity signal were therefore present; the failure
was at fixed input-level gating.

### Verdict

**PASS for HTTPS, microphone acquisition, MIME handling, upload, and ffmpeg decode.**

**OPEN DECISION for the identity front end:** use measured canonical level normalization before
the existing encoder, or reject the capture with an explicit quality/retry state. Do not silently
interpret `None` as a new or different baby.

## Spike C - `IM_OFFLINE=1` local transcription

### Initial test

- Input: normalized canonical WAV from the audible iPhone capture
- `IM_OFFLINE=1`
- `IM_WHISPER_MODEL=base.en`
- `OPENAI_API_KEY` empty
- configured `.env` fallback disabled
- network not granted

### Initial result

- `/opt/homebrew/bin/whisper` is installed.
- Its expected cache directory contains no OpenAI-Whisper model.
- The configured path returned an empty transcript in 2.314 seconds.
- Failure occurred when Whisper tried to create/use `~/.cache/whisper`; no cached model was
  available to load.

A complete 464 MB `Systran/faster-whisper-small` CTranslate2 model is present in the Hugging Face
cache, but the `faster_whisper` runtime is not installed and the current code does not call it.
That asset is not counted as a pass for the configured path.

The user explicitly approved one-time model provisioning. The 139 MB `base.en` model was then
downloaded into the CLI's local cache before the offline verification run.

### Offline verification after provisioning

- Network access: denied
- `IM_OFFLINE=1`
- `IM_WHISPER_MODEL=base.en`
- OpenAI API key: empty
- configured `.env` fallback: disabled
- Input: the real 40.66-second normalized iPhone capture

Local transcription completed in **5.592 seconds** and returned:

```text
Hey baby, it's okay, I picked you up and walked around the room, rocking you helped
and you settle it down.
```

The intended sentence was "Hey baby, it's okay. I picked you up and walked around the room.
Rocking you helped, and you settled down." The transcript preserved the actionable content with
one minor tense/word-boundary error.

The complete `session.finish()` path was then run against an isolated SQLite database with network
denied. It completed in **7.641 seconds** and:

- saved episode ID 1;
- stored the usable transcript;
- stored a complete 87-dimensional fingerprint;
- stored the explicit caregiver outcome;
- set `outcome_src` to `caregiver`;
- set `worked` to true; and
- measured the correct 40.66-second duration.

### Verdict

**PASS for offline transcription and local episode persistence**, provided the model is
pre-provisioned before the venue.

**OPEN GAP for a wholly offline guidance pipeline:** `extract_interventions()` still calls the
online reasoning client. With network and credentials absent, the full loop correctly degraded to
an empty intervention list. A deterministic local extractor or a provisioned local reasoning
model is still required if automatic intervention extraction must work without upstream internet.

## Verification

After the spike code and MIME/decode fixes:

```text
Ran 89 tests in 7.888s
OK
```
