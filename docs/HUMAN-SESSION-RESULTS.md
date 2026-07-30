# Human Cry-Imitation Session Results

The human demo is an open-set, session-based identification flow. Create a new empty session and
start recording. The first valid cry creates Person A. Later cries are compared against the full
active pool.

- A confirmed cry is assigned to an existing person and strengthens that profile with another
  independent enrollment.
- A clear outlier asks for one fresh cry. Two independent outlier cries create the next person.
- A borderline cry shows a non-confirmed direction and is not enrolled automatically.

## Result states

- `Matched: Name` means the selected profile cleared the absolute similarity gate and the
  runner-up separation gate.
- `Leaning toward: Name` means that profile led the full pool, but the recording did not clear the
  absolute confirmation gate. The direction is visible but explicitly not confirmed.
- `Possible new participant` means one cry was outside the active profiles and a second independent
  cry is required. The nearest existing profile is still shown as an unconfirmed direction.
- `New participant registered` means two clear outlier cries also passed the pair-consistency
  check and created the next automatic label.
- `Closest existing profile` means the attempt ended without a confirmed match, but the interface
  still shows which current profile was nearest.

Raw similarity values are not probabilities and are not shown in the demo interface.

## Fixed three-person demo

Profiles:

1. Prasshanna
2. Second person
3. Legacy control

Enrollment and held-out query assignments come from
`demo_assets/human_audio/manifest.json`.

| Held-out query | Expected | Result | Shown profile |
|---|---|---|---|
| `blind-query-01.wav` | Prasshanna | Matched | Prasshanna |
| `blind-query-02.wav` | Prasshanna | Leaning | Prasshanna |
| `second-person-03.m4a` | Second person | Leaning | Second person |

Result: 3 of 3 showed the correct direction, with no wrong direction and no unresolved query.

## Exhaustive leave-one-out check

Every available recording was held out once. The remaining recordings for that person were used
as enrollment, and the query was compared against all three profiles through the product HTTP API.

| Metric | Result |
|---|---:|
| Profiles in every comparison | 3 |
| Held-out queries | 10 |
| Confirmed correct | 5 |
| Confirmed wrong | 0 |
| Correct leaning result | 5 |
| Wrong leaning result | 0 |
| Unresolved | 0 |
| Confirmed coverage | 50% |
| Direction coverage | 100% |
| Correct direction among all queries | 100% |

The machine-readable result is stored in
`demo_assets/human_audio/results.json`.

## Automatic open-set session

The arrival-order evaluation starts with no human profiles. The first available recording for each
source is treated as that person's first encounter. A possible-new result uses the next independent
file as its retry. Confirmed known-person turns reinforce only the matched profile.

| Metric | Result |
|---|---:|
| First-time people | 3 |
| Correct new profiles | 3 |
| Missed new people | 0 |
| Later known turns | 5 |
| Confirmed correct known turns | 3 |
| Known turns waiting for one retry | 2 |
| Wrong known-person assignments | 0 |
| Duplicate profiles created from known people | 0 |

The earlier naive policy created a new profile after one below-gate cry. It correctly found the
three first-time people but incorrectly split three later known turns into duplicate profiles. That
policy was rejected. In the available automatic sequence, the two-cry rule created no duplicate
profiles and left two hard known turns pending because another independent file was unavailable.

A separate product-path integrity trial used the first outlier from Second person and a retry from
Legacy control. Both were outside Person A, but their pair-consistency check failed, so no Person B
profile was created. Same-source pairs from Second person and Legacy control passed.

## Reproduce

Run the fixed demonstration assignment:

```bash
python tools/human_session_eval.py demo_assets/human_audio/manifest.json --mode demo
```

Run the exhaustive leave-one-out check:

```bash
python tools/human_session_eval.py demo_assets/human_audio/manifest.json --mode loo
```

Run the automatic empty-session arrival order:

```bash
python tools/human_session_eval.py demo_assets/human_audio/manifest.json --mode discovery
```

## Interpretation

This demonstrates that the current backend can maintain a session pool, rank every participant,
and consistently show the correct direction on the available files. It does not establish a
population accuracy rate. The cohort contains only three sources, some recordings share capture
channels, and the observations are correlated.

The next stronger study needs more people, independent recording sessions, and crossed devices.
