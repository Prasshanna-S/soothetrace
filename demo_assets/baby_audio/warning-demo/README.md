# Demo Baby Three-Recording Showcase

This folder contains the three long-form playback files used for the controlled
`Demo Baby` showcase:

1. [X4, bottle](demo-baby-x4-extended-playback.wav)
2. [X7, upright](demo-baby-x7-extended-playback.wav)
3. [X8, white noise](demo-baby-x8-extended-playback.wav)

X4 and X8 are 45 seconds long. X7 is 46.5 seconds long. X4, X7, and X8 began
as three distinct 15-second fixed-rig recordings from the Baby X trial. Each
long-form file repeats its source three times so the presenter has time to
start the phone session and let the production confirmation gate finish. X7
has two 0.75-second quiet separators between copies so complete 3-second
recordings do not keep using the same fixed source alignment. Repetition
extends playback time. It does not create independent evidence.

The `enrollment` folder contains three earlier Baby X captures for `Demo Baby`
and three Baby Y captures for `Learning Baby`. The demo bootstrap uses those six
recordings to prepare two ready profiles. X4, X7, and X8 are not enrolled for
identity. Identity matching for `Demo Baby` uses X1, X2, and X3 instead.

Separately, the demo bootstrap copies the first 15 seconds of each X4, X7, and
X8 showcase asset to seed two clearly labeled synthetic retrieval memories per
pattern. This deliberate care-memory setup lets the showcase surface three
different history-based suggestions. It does not make the showcase assets
identity enrollments.

These files are controlled proof-of-concept fixtures. They do not establish
population accuracy.

See [PROVENANCE.md](PROVENANCE.md) before redistributing the audio.

## Current production gate

The browser creates complete 3-second recordings while one microphone stream
continues. Every accepted recording goes through managed ingest, the AudioSet
AST infant-cry gate, infant identity, profile-only history retrieval, context
ranking, and grounded guidance.

A suggestion can appear only when all of these conditions are true:

- The infant-cry gate is positive.
- The selected identity is `Demo Baby`.
- The same grounded history suggestion is seen in one candidate recording and
  five additional grounded confirmations.
- At least seven recordings have been processed.
- At least 20 seconds of audio have been analyzed.
- The current recording is not blocked by the exact and near-duplicate guard.

The duplicate guard keeps a replayed or acoustically near-identical chunk from
counting as a fresh confirmation. The three repetitions inside a long-form file
must not be described as three independent observations.

The phone can show local sound activity before the first server result. With
3-second chunks, the first server-confirmed infant-cry result is based on the
first 3 seconds of audio. Network and processing time can make the visible
result appear later than the audio timeline below.

## Verified long-form result

On July 30, 2026, all three files ran through the unchanged production pipeline
on a disposable database prepared by `scripts/prepare_care_demo.py`.

| File | Cry-positive recordings | First cry on audio timeline | Suggestion latch | Grounded suggestion |
| --- | ---: | ---: | ---: | --- |
| X4 | 7 of 7 | 3 seconds | 21 seconds | `What helped before: offered bottle.` |
| X7 | 10 of 10 | 3 seconds | 30 seconds | `What helped before: held baby upright.` |
| X8 | 7 of 7 | 3 seconds | 21 seconds | `What helped before: turned on white noise.` |

X7 needed more time because four recordings did not select the profile. The
system kept listening and produced its grounded suggestion after six distinct
grounded matches.

The exact machine-readable record is in
[showcase-manifest.json](showcase-manifest.json).

## What the suggestion uses

The demo bootstrap creates six clearly labeled synthetic history incidents for
`Demo Baby`:

- Two X4-pattern incidents where a bottle was offered and the caregiver
  reported that the baby settled.
- Two X7-pattern incidents where the baby was held upright and the caregiver
  reported that the baby settled.
- Two X8-pattern incidents where white noise was used and the caregiver
  reported that the baby settled.

The verified run used two active ranking factors:

- Cry-pattern similarity inside the selected profile.
- Similar time of day. The fresh acceptance database stored local hour 20 for
  the current context and all six synthetic history incidents.

No current caregiver note, tag, or care event was supplied, so those components
were omitted. In a real product, available caregiver notes, care events, time,
and other recorded context can add evidence. Missing context must not be
invented.

The result is a suggestion from recorded history. It is not a diagnosis, a
claim about why the baby is crying, or medical advice.

## Quick rehearsal

1. Prepare the demo database with `scripts/prepare_care_demo.py`.
2. Select `Demo Baby`.
3. Start a new listening session.
4. Start one playback file from its beginning.
5. Keep the playback device, volume, distance, room, phone position, and phone
   microphone unchanged.
6. Wait for the grounded suggestion card.
7. Stop and complete or discard the session.
8. Start a fresh session before playing the next file.

Use the full 46.5-second X7 file. Its observed latch point is 30 seconds. Do not
move the speaker or change volume between files because room replay can change
the acoustic result.

## Spoken evidence scripts

### Video 1, X4

This is X4, the first controlled query for Demo Baby. The infant-cry gate fires
on the first 3-second recording. The system keeps listening while the same
profile and grounded memory remain consistent. After at least 20 seconds, it
uses cry-pattern similarity and similar time of day to select two synthetic
history incidents where a bottle was offered and the caregiver recorded that
the baby settled. The app suggests what helped before. It does not diagnose a
cause.

### Video 2, X7

This is a different held-out recording from the same controlled Baby X trial.
The infant-cry gate remains positive even though caregiver speech is present.
Some identity recordings are not accepted, so the system continues listening.
At 30 seconds, six fresh
grounded matches support two synthetic history incidents where the baby was
held upright and then settled. The output is a history-based suggestion, not a
claim about why the baby is crying.

### Video 3, X8

This is another held-out recording from the controlled Baby X trial. The cry
gate fires on the first 3-second recording. After the confirmation and
20-second listening gates are satisfied, the ranker selects two synthetic
history incidents where white noise was used and the caregiver recorded a
settled outcome. The caregiver remains in control of what to try.

Detailed subtitle overlays are in [captions](captions/). Shorter overlays are in
[captions/distinct-output](captions/distinct-output/). Both sets describe the
current three-output bootstrap and use the observed 21, 30, and 21-second latch
points.
