# Acceptance results 01

Run by **product workstream** on 2026-07-29. Judge: **acoustics workstream**.

## Verdict

All critical A-D behaviors pass. B2 required a controlled pair: the same 18-second cry
playback, at the same phone position/volume and MacBook microphone gain, first with a live
caregiver speaking and then without speech. Comparing an original 8 kHz corpus file directly
to a 16 kHz room/microphone recording was retained as a diagnostic but was not treated as the
controlled result because it changes both the caregiver overlay and the capture channel.

The first second-device attempt was excluded before scoring because the operator reported that
playback began late and at the wrong volume.

## Critical tests

| test | result | evidence |
|---|---|---|
| A1 retrieval discrimination | **PASS** | Infant X (`d6cda191-4962-4308-9a36-46d5648a95ed`) trained on 4 episodes. Eight held-out X top ids: `2,3,2,3,3,2,4,4`; 12 other-infant top ids: `4,1,4,1,2,2,3,1,2,3,3,1`. Mean top similarity X **0.415684**, Y **0.235911**. The first 8 paired top ids differed in 7/8 trials. |
| A2 band distribution | **PASS** | 20 queries: `none=15`, `weak=1`, `strong=4`. X: `none=4`, `weak=1`, `strong=3`; Y: `none=11`, `strong=1`. Not uniformly strong; other infants skewed none. |
| A3 normalization required | **PASS** | With every baseline row deleted, `find_similar` returned 0 matches and rendered `Nothing similar on record yet.` No raw-cosine fallback. |
| B1 real mixed microphone loop | **PASS** | MacBook mic captured clean cry from a separate phone plus live caregiver speech. Duration **30.776 s**; fingerprint **87 floats**. Transcript: `Oh sweetie, what's wrong? Are you hungry? Ok, let me get you a bottle. Here we go.` Three interventions were extracted; all 3 evidence spans occurred literally in the transcript. `finish` saved 1 episode with id 1, caregiver outcome/provenance, and `worked=True`. |
| B2 voice-overlay survival | **PASS** | Controlled microphone pair: live mixed recording versus same-channel live clean-cry control scored **0.909402**, band `strong`, correct cry ranked first. Two stored filler cries scored **0.084316** and **0.042227**. Against 20 impostors: mean **0.052345**, p95 **0.315142**, max **0.459446**. |
| B3 no source separation | **PASS** | `rg -n -i "separate\|diariz\|split" src` found only comments/docstrings and ordinary string splitting; no live separation/diarization path. |
| C1 explicit failure | **PASS** | `nothing worked, he cried himself out` saved `worked=False`. |
| C2 explicit success | **PASS** | `feeding him worked` saved `worked=True`. |
| C3 skipped outcome | **PASS** | Transcript without an explicit result plus `caregiver_answer=None` saved `outcome=None`, `outcome_src=None`. |
| C4 tally integrity | **PASS** | Five episodes with `worked=False` and action `rocking` produced `tried=5`, `worked=0`. |
| D1 unknown outcomes | **PASS** | Three recent `worked=None` episodes returned non-empty step-away guidance. |
| D2 explicit failures | **PASS** | Three recent `worked=False` episodes returned non-empty step-away guidance. |
| D3 old long episode | **PASS** | Three newer short resolved episodes followed by one old 601-second unresolved episode returned `""`. |
| D4 calm history | **PASS** | Three short resolved episodes returned `""`. |

### B2 diagnostic retained

The original digital fixture mixed synthetic 24 kHz caregiver TTS over an 8 kHz corpus cry,
then converted to 16 kHz. Comparing that mixed fixture to the original clean file scored
**-0.257788** versus impostor mean **-0.006226** and failed. Comparing the live room recording
directly to the original digital file improved to **0.241725**, but remained below the
digital-impostor p95 **0.254993**. The caregiver noticed the confound: her live voice was much
clearer than the low-quality cry recording. The controlled live-clean/live-mixed pair above
holds the speaker, room, microphone, gain, and source quality constant and isolates the voice
overlay, producing **0.909402**. This indicates channel mismatch, not speech overlay, caused the
cross-domain failure. It is still a deployment warning: memories and future queries should be
captured through comparable real-world channels.

## Honest degradation

| test | result | evidence |
|---|---|---|
| E1 zero episodes | **PASS** | `No recordings yet - nothing to compare.` |
| E2 one/two episodes | **PASS** | `Only your 1st recording...` and `Only your 2nd recording...`; no match rendered. |
| E3 exactly three priors | **PASS** | `find_similar` began returning 3 candidates. Bands were `none,none,none`, so the human-facing renderer honestly suppressed a weak claim. |
| E4 no similarity number | **PASS** | `rg -n "similarity" src/render.py src/cli.py` returned no hits; render tests also reject raw values and `%`. |
| E5 provenance | **PASS** | Render tests expose caregiver/inferred provenance and label seed output `synthetic demo data`. |

## Liability surface

| test | result | evidence |
|---|---|---|
| F1 no invented causes | **PASS** | Read 20 generated cards; unsupported `hungry`/`colic`/`in pain` cause hits: **0**. |
| F2 non-diagnostic claims | **PASS** | Source hits are comments, model constraints, or explicit `not a diagnosis` disclaimers; no user-facing diagnosis/treatment claim. |
| F3 consent | **PASS** | CLI regression test blocks first recording on a non-affirmative audio-only consent response. |
| F4 no video | **PASS** | Only `avfoundation` use is `session._capture_wav`, configured mono PCM audio; the CLI explicitly states it never records video. |
| F5 deletion | **PASS** | Regression test deletes the local audio and episode, reduces history from 2 to 1, and removes the stale subject baseline. Corpus paths remain outside the deletable audio root. |

## Robustness

| test | result | evidence |
|---|---|---|
| Missing/empty/short/silent audio | **PASS** | All four returned `None` fingerprints without raising. |
| Offline transcription failure | **PASS** | Local Whisper model failure logged one concise error (no traceback); `finish` still saved id 11 with an 87-float fingerprint and empty transcript. |
| Corrupt database row | **PASS** | A one-byte malformed fingerprint blob returned an episode with `fingerprint=None`; malformed JSON degraded to `[]` / `{}`. |
| Unicode caregiver answer | **PASS** | `抱っこで落ち着いた - café 🍼` round-tripped exactly. |

## Verification commands

- `.venv/bin/python -m unittest discover -s tests -v`
- acceptance runner in the product workstream task `work/acceptance_runner.py`
- behavioral runner in the product workstream task `work/acceptance_behavior.py`
- paired live-audio runner in the product workstream task `work/second_device_similarity.py`
- real `session.finish` runner in the product workstream task `work/acceptance_live_finish.py`

The raw acceptance WAV files remain local under ignored `data/audio/` and were not committed or
uploaded.
