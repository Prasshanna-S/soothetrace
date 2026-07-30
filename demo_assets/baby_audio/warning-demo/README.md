# Demo Baby Warning Playback

`demo-baby-x8-extended-playback.wav` is a recording-friendly playback fixture
for the controlled phone demonstration.

## File facts

- Duration: 45.000 seconds
- Format: mono 16-bit PCM WAV at 16 kHz
- SHA-256: `31b4f184db65b85f10e9acb95bc60c00b8013fee58f744acde806fde9c4a65f4`
- Composition: three exact, back-to-back copies of the 15-second X8 recording
- Source recording: `round2_h/15-X8.wav`
- Source SHA-256: `66ac3230db9dfbd5ddacf2057f9614f4b0741535f2794c019e6c2efc070da5d1`

The copies were concatenated without pitch shifting, time stretching, filtering,
or gain changes. A decoded-audio checksum confirms that the first 15 seconds of
the extended file are sample-identical to the source.

## Verified demo behavior

The X8 source was also tested at a conservative quiet-path level near -40 dB
RMS through the real ingest, infant-cry gate, infant identity, history retrieval,
and guidance path on disposable copies of the demo database.

| Leading window | Cry gate | Demo Baby identity | Guidance |
| --- | --- | --- | --- |
| 4 seconds | Infant cry detected | Strong, score 0.90105, margin 0.13437 | Latched |
| 6 seconds | Infant cry detected | Strong, score 0.92955, margin 0.12657 | Latched |
| 8 seconds | Infant cry detected | Strong, score 0.92906, margin 0.12915 | Latched |
| 10 seconds | Infant cry detected | Strong, score 0.92486, margin 0.13072 | Latched |

The returned suggestion was: `What helped before: turned on white noise.`

Use this file only as repeated playback for a controlled demonstration. The
three repetitions are not three independent recordings and must not be reported
as additional validation or accuracy evidence. For the intended test, play the
file from the phone or presentation device while the app records through its
microphone. Keep playback volume and device distance fixed.
