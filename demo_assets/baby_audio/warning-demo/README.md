# Demo Baby Three-Recording Showcase

This folder contains three 45-second playback files for three separate recording
sessions:

1. `demo-baby-x4-extended-playback.wav`
2. `demo-baby-x7-extended-playback.wav`
3. `demo-baby-x8-extended-playback.wav`

X4, X7, and X8 are three distinct 15-second recordings from the fixed-rig Baby X
trial. Each playback file repeats its one source recording three times so the
presenter has enough time to start the phone session. Repetition makes the file
longer, but it does not create extra evidence.

The `enrollment` folder contains three earlier, independent Baby X captures for
`Demo Baby` and three Baby Y captures for `Learning Baby`. The bootstrap uses
those six files to prepare the two profiles. The three X4, X7, and X8 showcase
files remain separate queries, so the demo is not matching a file against
itself.

X7 and X8 were held out from the X1 through X6 acceptance comparison. X4 was one
of the stored trial examples. These are controlled demonstration fixtures, not
population accuracy evidence.

## Quick rehearsal

1. Select `Demo Baby`.
2. Start a new listening session.
3. Start one playback file from its beginning.
4. Keep the playback device, volume, distance, room, phone position, and phone
   microphone unchanged.
5. Let four accepted six-second cry segments process. The first possible
   suggestion is therefore about 24 seconds after recording starts.
6. Stop the session after the guidance card latches.
7. Complete or discard the follow-up, then start a fresh session for the next
   file.

Do not switch devices or move the speaker between files. Room replay can change
the acoustic scores even when the file itself is unchanged.

## Verified six-second result

The first six seconds of each source were reduced with one constant gain to
about minus 39 dB RMS, then run through the real ingest, AST infant-cry gate,
infant identity, profile-only history retrieval, context ranking, guidance, and
care-session latch on disposable copies of the seeded live demo database.

| File | Cry gate | Profile result | One-chunk result |
| --- | --- | --- | --- |
| X4 | Infant cry detected | Demo Baby, strong | Guidance latched |
| X7 | Infant cry detected | Demo Baby, weak accepted match | Guidance latched |
| X8 | Infant cry detected | Demo Baby, strong | Guidance latched |

X5 and X6 were tested and excluded because their six-second probes did not pass
identity acceptance. The exact debug measurements, checksums, and exclusions
are in [`showcase-manifest.json`](showcase-manifest.json).

## What the calculation actually used

The verified run happened during the 3 PM hour with no current caregiver tag or
care event. That means the ranker used:

- Cry-pattern similarity at an active weight of 0.7647.
- Time-of-day similarity at an active weight of 0.2353.
- No current caregiver-note component. Missing notes were omitted, and the
  remaining weights were renormalized.
- Only Demo Baby's prior incidents after profile matching.

All three recordings selected synthetic demo incident 4, recorded at 6:45 PM.
That incident says the caregiver swaddled the baby, turned on white noise, and
reported that the baby settled. White noise was the final recorded action, so
the latched suggestion was:

> What helped before: turned on white noise.

The output is a memory-based suggestion. It is not a diagnosis, a claim about
why the baby is crying, or medical advice.

## Validated three-output memory arrangement

A second spike tested whether the same three files can support three distinct
recommendations without inventing a cause. It used a disposable database and
did not change the production database.

The disposable Demo Baby profile contained six clearly synthetic afternoon
memories:

- Two X4-pattern incidents where a bottle was offered and the caregiver
  reported that the baby settled.
- Two X7-pattern incidents where the baby was held upright and the caregiver
  reported that the baby settled.
- Two X8-pattern incidents where white noise was used and the caregiver
  reported that the baby settled.

Each leading six-second quiet probe then ran through the real cry gate,
identity, retrieval, guidance, and care-session latch:

| Query | Result | Evidence |
| --- | --- | --- |
| X4 | `What helped before: offered bottle.` | 2 similar recorded incidents |
| X7 | `What helped before: held baby upright.` | 2 similar recorded incidents |
| X8 | `What helped before: turned on white noise.` | 2 similar recorded incidents |

All three queries latched in one chunk, so this spike passed 3 out of 3. The
calculation used cry-pattern similarity and similar time of day. Current notes
were empty in this test. Exact results are in
[`showcase-manifest.json`](showcase-manifest.json).

This proves that distinct recorded histories can lead to distinct grounded
suggestions. It does not prove that the cry reveals hunger, reflux, discomfort,
or any other cause. The current default live seed still gives the common
white-noise story described above until the validated six-memory arrangement is
installed by the demo bootstrap.

## Spoken evidence scripts

### Video 1, X4

This is the first of three distinct recordings in the controlled Baby X trial.
The infant-cry gate detected a cry-like infant sound, and the profile matcher
selected Demo Baby. The memory ranker then combined the cry pattern with the
current time. The best prior incident was at 6:45 PM, when swaddling followed by
white noise was recorded and the caregiver said the baby settled. The app
suggests the last helpful step, white noise. This is a suggestion from this
baby's recorded history, not a diagnosis.

### Video 2, X7

This is a different held-out recording from the same controlled Baby X trial.
It includes caregiver speech, but the infant-cry gate still fired and the
profile matcher selected Demo Baby. The same profile-only memory calculation
used cry-pattern similarity and time of day. It found the 6:45 PM incident where
white noise was the last action before the caregiver reported that the baby
settled. The suggestion is based on that prior record, not on a claimed cause.

### Video 3, X8

This is another held-out recording from the controlled Baby X trial, without
caregiver speech. The infant-cry gate fired and the profile matcher produced a
strong Demo Baby match. The ranker compared only this profile's prior incidents
and included the current time. It selected the 6:45 PM incident where the
caregiver recorded swaddling and white noise, followed by a settled outcome.
The app suggests what helped before, while leaving the decision with the
caregiver.

Ready-to-overlay subtitle files are under [`captions`](captions/).
The current-runtime captions describe the existing common white-noise result.
The [`captions/distinct-output`](captions/distinct-output/) set describes the
validated three-output spike and must only be used with that six-memory demo
arrangement.
