# Public Human Cry-Imitation Test Audio

This directory contains the complete 10-recording cohort used by the incremental live-session
evaluation. The repository owner confirmed on 2026-07-30 that every recorded participant agreed
to public distribution of these recordings.

The files contain simulated crying by three adults. They are not infant recordings, do not
establish infant identity performance, and are not medical training data. No separate download is
needed.

## Cohort

| Manifest source | Files | Container and source format | Total duration |
|---|---:|---|---:|
| Prasshanna | 5 | PCM16 WAV, 16 kHz, mono | 51.6675 s |
| Second person | 3 | AAC M4A, 48 kHz, mono | 99.605333 s |
| Legacy control | 2 | PCM16 WAV, 16 kHz, mono | 22.2070 s |

The manifest records the truth grouping, not a global capture chronology. Evaluator orders are
fixed synthetic arrival orders that preserve the stated filename order within each source.

## Mechanical inventory

The live evaluator checks every listed file for presence, supported MIME, positive duration, byte
size, unique SHA-256, and agreement with the audio files in this directory before starting a
server.

| Truth source | File | MIME | Container | Duration | Bytes | SHA-256 |
|---|---|---|---|---:|---:|---|
| Prasshanna | `prasshanna-01.wav` | `audio/wav` | `wav` | 9.353500 s | 299390 | `607b4b901494aeb1a3e7140bfcd0ccf97b2bbfdbc5737bc24526973358eecf5d` |
| Prasshanna | `prasshanna-02.wav` | `audio/wav` | `wav` | 10.773500 s | 344830 | `af09fa9e2cad8d0962368f3d679ce7f076e57bafbacf6788e29bfe40b040093b` |
| Prasshanna | `prasshanna-03.wav` | `audio/wav` | `wav` | 12.033500 s | 385150 | `ab30332a87206122344eb9d2631388e1d243fb5960e9e5285b38b888f48697c0` |
| Prasshanna | `blind-query-01.wav` | `audio/wav` | `wav` | 9.393500 s | 300670 | `21309d187951fc65743e51d6e8555bd2c6e7ed1337c2d3b35102ff89e55ea200` |
| Prasshanna | `blind-query-02.wav` | `audio/wav` | `wav` | 10.113500 s | 323710 | `3d3d2103784c8a36f47a99df66fce77aeeb0bc59127865d7b5d4341d7e076f6a` |
| Second person | `second-person-01.m4a` | `audio/mp4` | `mov,mp4,m4a,3gp,3g2,mj2` | 31.381333 s | 301258 | `9e255126cd7a201836c34a8ab10eece4d31bc505981e034621ec66281ee8e170` |
| Second person | `second-person-02.m4a` | `audio/mp4` | `mov,mp4,m4a,3gp,3g2,mj2` | 32.405333 s | 305473 | `0e608fc3f24afd8394320f1e27c2a29d8acc2536b2c12dc9696a2b16170efa00` |
| Second person | `second-person-03.m4a` | `audio/mp4` | `mov,mp4,m4a,3gp,3g2,mj2` | 35.818667 s | 324313 | `56686eafdcb691cc45acbbde5e4d5934b7e1e6f04e063d83bed73329cf2eff60` |
| Legacy control | `control-01.wav` | `audio/wav` | `wav` | 10.053500 s | 321790 | `40cb8c40be8885cab9d3119ddab8f92573b016c351304ebc633b046b7d3f0176` |
| Legacy control | `control-02.wav` | `audio/wav` | `wav` | 12.153500 s | 388990 | `c2dec2b13497d443149a6f07078a014eab40f95f680c09693ee5f5a2b424be50` |

## Automated live-session result

Every observation below went through the real local HTTP API and ingest path. Each mode received a
fresh temporary database, managed-audio root, and server. The request contained only raw audio
bytes, the correct MIME, `X-Capture-Source: fixture-upload`, a neutral capture-device string, and a
neutral user agent.

Expected truth and fixture identity were never sent to the server. The evaluator applied manifest
truth only after each HTTP response returned.

### Summary

| Metric | One person | Staged | Difficult |
|---|---:|---:|---:|
| Total submissions | 5 | 10 | 10 |
| Valid observations | 5 | 10 | 10 |
| Comparison eligible | 4 | 9 | 9 |
| Correct established assignments | 4/4 | 5/5 | 5/5 |
| Correct directional assignments | 0/0 | 2/2 | 2/2 |
| Wrong named directions | 0/4 | 0/7 | 0/7 |
| Provisional participant responses | 1 | 1 | 1 |
| Represented people | 1/1 | 3/3 | 3/3 |
| Participants created | 1/1 | 3/3 | 3/3 |
| Duplicate profiles | 0 | 0 | 0 |
| Known-person splits | 0 | 0 | 0 |
| `possible_new` | 0 | 2 | 2 |
| Pending patterns at end | 0 | 1 | 1 |
| Direction coverage | 4/4 | 7/9 | 7/9 |
| Correct direction when shown | 4/4 | 7/7 | 7/7 |
| Reinforcements | 4 | 5 | 5 |
| Maximum observation latency | 3.513 s | 8.032 s | 11.525 s |

Both three-person release gates passed:

```text
represented_people = 3
participants_created = 3
wrong_person = 0
duplicate_profiles = 0
known_person_split = 0
```

Perfect direction coverage was not required and is not claimed.

### One-person rows

| Sequence | Fixture | Status | Participant | Reinforced | Latency |
|---:|---|---|---|---|---:|
| 1 | `prasshanna-01.wav` | `provisional_created` | Person A | no | 2.906 s |
| 2 | `prasshanna-02.wav` | `participant` | Person A | yes | 1.524 s |
| 3 | `prasshanna-03.wav` | `participant` | Person A | yes | 2.307 s |
| 4 | `blind-query-01.wav` | `participant` | Person A | yes | 2.354 s |
| 5 | `blind-query-02.wav` | `participant` | Person A | yes | 3.513 s |

### Staged rows

| Sequence | Fixture | Status | Participant | Direction correct | Reinforced | Latency |
|---:|---|---|---|---|---|---:|
| 1 | `prasshanna-01.wav` | `provisional_created` | Person A | not scored | no | 0.718 s |
| 2 | `prasshanna-02.wav` | `participant` | Person A | yes | yes | 1.145 s |
| 3 | `second-person-01.m4a` | `possible_new` | Person A as closest only | not scored | no | 3.281 s |
| 4 | `second-person-02.m4a` | `participant` | Person B | yes | yes | 7.407 s |
| 5 | `control-01.wav` | `possible_new` | Person A as closest only | not scored | no | 3.561 s |
| 6 | `control-02.wav` | `participant` | Person C | yes | yes | 5.114 s |
| 7 | `prasshanna-03.wav` | `participant` | Person A | yes | yes | 1.248 s |
| 8 | `second-person-03.m4a` | `leaning` | Person B | yes | no | 8.032 s |
| 9 | `blind-query-01.wav` | `participant` | Person A | yes | yes | 0.554 s |
| 10 | `blind-query-02.wav` | `leaning` | Person A | yes | no | 6.835 s |

### Difficult rows

| Sequence | Fixture | Status | Participant | Direction correct | Reinforced | Latency |
|---:|---|---|---|---|---|---:|
| 1 | `prasshanna-01.wav` | `provisional_created` | Person A | not scored | no | 0.384 s |
| 2 | `second-person-01.m4a` | `possible_new` | Person A as closest only | not scored | no | 2.029 s |
| 3 | `control-01.wav` | `possible_new` | Person A as closest only | not scored | no | 2.952 s |
| 4 | `prasshanna-02.wav` | `participant` | Person A | yes | yes | 4.118 s |
| 5 | `second-person-02.m4a` | `participant` | Person B | yes | yes | 7.278 s |
| 6 | `control-02.wav` | `participant` | Person C | yes | yes | 9.395 s |
| 7 | `prasshanna-03.wav` | `participant` | Person A | yes | yes | 0.965 s |
| 8 | `second-person-03.m4a` | `leaning` | Person B | yes | no | 11.525 s |
| 9 | `blind-query-01.wav` | `participant` | Person A | yes | yes | 1.133 s |
| 10 | `blind-query-02.wav` | `leaning` | Person A | yes | no | 6.725 s |

The two `possible_new` rows in each three-person order remain visible evidence. Person B and
Person C were created only after the second agreeing observation. The hard
`second-person-03.m4a` result leaned correctly toward Person B, did not reinforce it, and remained
one pending pattern instead of creating a duplicate Person D.

### Duplicate and invalid probes

| Sequence | Input | HTTP | Status | Support | Timeline | Latency |
|---:|---|---:|---|---:|---:|---:|
| 1 | `prasshanna-01.wav` | 201 | `provisional_created` | 1 | 1 | 0.609 s |
| 2 | exact same bytes | 201 | `duplicate` | 1 | 2 | 0.079 s |
| 3 | corrupt bytes with `audio/wav` | 422 | `invalid` | unchanged | 2 | 0.063 s |

The corrupt upload did not change participant state and did not add a third timeline row.

## Manual UI observation, not an automated metric

In a separate live UI check, the user reported that the female participant audio and a
phone-replayed version of the user's own cry repeatedly formed distinct session patterns. This
observation has no controlled numerator or denominator and is not included in the automated
tables above.

It demonstrates pattern separation in that tested session under those channel conditions. It does
not demonstrate channel-invariant person recognition, estimate population performance, or establish
infant identity.

## Reproduce

```bash
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode one-person
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode staged
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode difficult
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode probes
```

`--mode alternating` is a compatibility alias for `difficult`.

From the repository root, regenerate the complete gated artifact:

```bash
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json \
  --mode all \
  --output demo_assets/human_audio/live-session-results.json
```

`live-session-results.json` contains every exact public response, reason code, participant
snapshot, evaluator-only truth binding, and nanosecond latency. The older `results.json` measures
the manual-profile identity-attempt workflow and is retained only as legacy evidence.

## Honest interpretation

- This is a small, correlated cohort of ten recordings and three consenting adults.
- The files mix WAV and M4A containers and capture channels.
- Fixed synthetic order is not actual capture chronology.
- Counts are demonstration evidence, not population accuracy.
- A second recording supplies supporting evidence. It does not prove identity.
- Adult imitation does not establish infant performance.
- `leaning` is direction only and never reinforces a profile.
- The system does not infer why someone is crying.
