# Baby Audio Engineering Fixtures

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

Files `01`, `02`, and `03` are reference enrollments. File `04` is a held-out
rehearsal query, file `05` is the one permitted retry, and file `06` is an
extra stress-test clip. The full source filename, app-install UUID, contributor
label, timestamp, duration, and SHA-256 digest are preserved in
[`manifest.json`](manifest.json).

## Important identity limit

The public source groups clips by an app-install UUID. Its own documentation says that this value
identifies one installed app instance, not a verified baby. The labels Baby 1, Baby 2, and Baby 3
are useful demonstration proxies, not identity ground truth.

The 18 clips were deliberately curated for an engineering rehearsal from
larger source groups. Each folder has its own app-install UUID. Results on these
same clips are not independent accuracy evidence. The measured infant result
elsewhere in this repository comes from a separate two-infant fixed-rig test.

## Relationship to the current browser

The current SootheTrace browser presents two prepared infant profiles named
`Demo Baby` and `Learning Baby`, plus the separate `Human Baby` activity. It
does not expose a general create-and-enroll interface for the Baby 1, Baby 2,
and Baby 3 folders.

Use the long-form files in
[`warning-demo`](warning-demo/README.md) for the current Demo Baby presentation.
The setup command in the repository README prepares the matching profiles and
synthetic care memories before the server starts.

The Baby 1, Baby 2, and Baby 3 folders remain checked-in engineering fixtures
for controlled identity experiments and future profile-enrollment work. Do not
play them against the prepared Demo Baby profile and present the result as the
current app showcase.

## Fixed-path rule for identity experiments

The shipped infant thresholds were calibrated on live room replay, not on raw 8 kHz corpus uploads.
In any experiment that creates profiles from these 18 files, every enrollment
and query must traverse the same path:

```text
phone speaker at fixed volume
        |
        v
same distance and room position
        |
        v
laptop microphone and SootheTrace ingest
```

For each group, use `01`, `02`, and `03` only as enrollments. Use `04` as the
held-out query, `05` as one fresh retry, and `06` as an additional stress test.
Do not submit an enrollment clip as its own query.

Do not enroll one profile by direct file upload and another through a microphone. That would let
the capture channel influence the result. Direct raw-file upload is useful for checking ingest and
playback, but it is not the calibrated infant-identity demonstration.

## Source and labels

The contributor-supplied filename labels such as `hungry` and `needs burping`
are source metadata. They are not diagnoses, are not used to decide identity,
and are not proof of why a baby was crying. See
[`LICENSE-DATA.md`](LICENSE-DATA.md) for the source attribution, stated license
links, and identity and consent caveats. SootheTrace does not claim that the
source license establishes verified infant identity or permission for every
biometric, privacy, medical, or commercial use.
