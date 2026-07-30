# Acceptance results 02

Run by **product workstream** on 2026-07-29. Judge: **acoustics workstream**.

## Fixed reference rig

```text
RIG
  capture device : :1 (MacBook Pro Microphone)
  capture gain   : macOS input volume 46
  sample rate    : 16000 Hz mono
  baseline       : population n=421
  playback device: iPhone 17 Pro Max
  distance       : 15 cm
  playback volume: 100% system volume
  room           : current indoor testing room
  background     : quiet; no intentional background audio
```

Preflight using `IM_AUDIO_DEVICE=:1 .venv/bin/python tools/rig_check.py --seconds 5`:

- captured 139 KB
- mean level **-31.1 dB**
- peak level **-9.9 dB**
- fingerprint **87 dimensions**
- tool verdict: **RIG OK**

An earlier check at gain 80 reached a near-clipping peak of -0.4 dB. It was rejected before
H1; no acceptance episodes were recorded with that gain.

## Results

| test | result | evidence |
|---|---|---|
| H1 live corpus | **PASS** | Fixed-rig master contained all 16 cue sequences. Cue-time fit: scale `0.884182464`, intercept `4.515818 s`, maximum residual `0.06875 s`. All 8 X segments produced 87 features. Seven original Y segments produced 87; quiet Y3 measured `-38.1 dB` and failed twice, so it was replaced without changing the rig by unused Y9 from the same infant (`-31.0 dB`, peak `-12.7 dB`, 87 features). Final live corpus: 8 X + 8 Y, with live caregiver speech on X1/X3/X5/X7. |
| H2 different-occasion discrimination | **PASS** | Stored X1-X6. Held-out X7/X8 top similarities were `0.914281` and `0.932811` (both `weak`; different top ids 3 and 4), mean `0.923546`. Eight Y top similarities averaged `0.775709`; all 8 banded `none`. Mean gap `0.147837`. |
| H3 caregiver voice effect | **PASS** | Speech-present X7 scored `0.914281`; speech-absent X8 scored `0.932811`; absolute difference `0.01853`. Hosted ASR independently recovered caregiver speech from X1/X3/X5/X7: bottle, rocking/holding, diaper check, and picking up/walking respectively. |
| I useful-history threshold | **N = 6** | n=1-2: retrieval gated. n=3: X bands `none/weak`, X mean `0.922829`, Y mean `0.757273`, false-strong 0. n=4: `none/none`, `0.923546`, `0.770038`, 0. n=5: `none/weak`, `0.923546`, `0.770038`, 0. n=6: `weak/weak`, `0.923546`, `0.781334`, 0. Smallest n where both X queries reached weak-or-better and all four Y stayed none: **6**. |
| J channel tolerance | **OPERATING ENVELOPE MEASURED** | Reference X8: `0.932811` (`weak`). J1 at ~1 m: `0.915141` (`weak`, preserved). J2 at a measured ~3.9 dB quieter capture: `0.896582` (`none`, not preserved). J3a opposite corner of the same bedroom: `0.932148` (`weak`, preserved); a true different room was unavailable and is not claimed. J4 iPhone Continuity Mic while the same iPhone played: `-53.7 dB`, no fingerprint because iOS suppressed its own speaker feed; valid capture-device-only testing requires a third playback device. J5 controlled pink background noise: `0.899410` (`weak`, preserved). |
| K demo integrity | PENDING | |
