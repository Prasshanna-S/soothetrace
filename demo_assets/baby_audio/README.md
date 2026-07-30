# Baby Audio Rehearsal Fixtures

This folder contains three clearly separated public-corpus groups:

```text
baby_audio/
├── baby-1/
│   ├── baby-1-01.wav
│   ├── baby-1-02.wav
│   ├── baby-1-03.wav
│   ├── baby-1-04.wav
│   ├── baby-1-05.wav
│   └── baby-1-06.wav
├── baby-2/
│   ├── baby-2-01.wav
│   ├── baby-2-02.wav
│   ├── baby-2-03.wav
│   ├── baby-2-04.wav
│   ├── baby-2-05.wav
│   └── baby-2-06.wav
└── baby-3/
    ├── baby-3-01.wav
    ├── baby-3-02.wav
    ├── baby-3-03.wav
    ├── baby-3-04.wav
    ├── baby-3-05.wav
    └── baby-3-06.wav
```

Files `01`, `02`, and `03` are rehearsal enrollments. File `04` is a held-out rehearsal query,
file `05` is the one permitted retry, and file `06` is an extra stress-test clip. The full source
filename, app-install UUID, contributor label, timestamp, duration, and SHA-256 digest are
preserved in [`manifest.json`](manifest.json).

## Important identity limit

The public source groups clips by an app-install UUID. Its own documentation says that this value
identifies one installed app instance, not a verified baby. The labels Baby 1, Baby 2, and Baby 3
are useful demonstration proxies, not identity ground truth.

The 18 clips were deliberately curated for a stable rehearsal from larger source groups. Each
folder has its own app-install UUID. Results on these same clips are not independent accuracy
evidence. The measured infant result elsewhere in this repository comes from a separate two-infant
fixed-rig test.

## Rehearse through one fixed path

The shipped infant thresholds were calibrated on live room replay, not on raw 8 kHz corpus uploads.
For the intended demonstration, every enrollment and query must traverse the same path:

```text
phone speaker at fixed volume
        |
        v
same distance and room position
        |
        v
laptop microphone and Cry Memory browser
```

Use this sequence:

1. Start the Cry Memory server and open the desktop browser.
2. Select `Baby`.
3. Create profiles named `Baby 1`, `Baby 2`, and `Baby 3`.
4. Keep the phone volume, speaker, laptop microphone, distance, and room position unchanged.
5. Play `baby-1-01.wav` from the phone while recording in Cry Memory. Enroll that capture into
   Baby 1. Repeat with `baby-1-02.wav` and `baby-1-03.wav`.
6. Repeat step 5 for Baby 2 and Baby 3 with their `01`, `02`, and `03` files.
7. Record `baby-1-04.wav` through the same path and run a blind query. Repeat with each group's
   `04` file.
8. If a result requests one retry, use that group's `05` file through the same fixed path.
9. Keep `06` unused for an additional stress test. Do not submit an enrollment clip as its own
   query.

Do not enroll one profile by direct file upload and another through a microphone. That would let
the capture channel influence the result. Direct raw-file upload is useful for checking ingest and
playback, but it is not the calibrated infant-identity demonstration.

## Source and labels

The contributor-supplied filename labels such as `hungry` and `needs burping` are source metadata.
They are not diagnoses, are not used to decide identity, and are not proof of why a baby was crying.
See [`LICENSE-DATA.md`](LICENSE-DATA.md) for attribution, license links, and the grouping caveat.
