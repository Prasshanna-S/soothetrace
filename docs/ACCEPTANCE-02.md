# Acceptance round 2 - the product case

**Prerequisite:** round 1 passed (`ACCEPTANCE-RESULTS-01.md`). Owner: **product workstream executes**,
**acoustics workstream judges**. Report to `docs/ACCEPTANCE-RESULTS-02.md` with real numbers.

## Why round 2 exists

Round 1's most valuable result was not a pass. It was the B2 diagnostic:

| B2 variant | score | verdict |
|---|---|---|
| digital fixture (TTS over 8 kHz corpus cry) vs original | **-0.258** | ❌ |
| live room recording vs original digital file | **0.242** | ❌ below impostor p95 (0.255) |
| **live clean vs live mixed, same channel** | **0.909** | ✅ |

**Channel mismatch breaks matching. Caregiver speech overlay does not.** That is a deployment
constraint, and it has a consequence nobody had accounted for: *the demo seeds from 2015-era
8 kHz corpus files and would query with a live microphone - which is the failing comparison.*

Now line up what round 1 actually established:

| | corpus audio | live audio |
|---|---|---|
| **same** occasion | - | ✅ B2, 0.909 |
| **different** occasions | ✅ A1, 0.416 vs 0.236 | ❌ **NEVER TESTED** |

The empty cell **is the product.** Everything else is a proxy for it.

---

## 🔴 H - CRITICAL: different occasion, same channel, live audio

The one unproven link in the chain. Hold the channel constant, vary the occasion.

### Rig - write these down and do not change them mid-test

One playback device (phone) at a **fixed** distance and volume; one capture device (MacBook mic)
at **fixed** gain; one room. Record the rig settings in the results file. Every recording in H
and I must use this identical rig - that is the whole point.

### H1 - build the live corpus

1. Infant **X** = the corpus infant with the most recordings
   (`d6cda191-4962-4308-9a36-46d5648a95ed`, 13 available).
2. Infant **Y** = any other infant with ≥8 recordings.
3. Play **8 different X cries** through the rig, recording each (~15-20 s) → 8 X-live episodes.
4. Same for **8 Y cries** → 8 Y-live impostors.
5. **On 4 of the 8 X recordings, speak live caregiver lines over the playback** ("Are you hungry?
   Let me get your bottle") - real episodes have a caregiver in them. Vary the lines.

### H2 - the discrimination test 🔴

Store **6 X-live** episodes under one subject. Hold out **2 X-live**. Query with the 2 held-out
X-live plus all 8 Y-live.

- **PASS:** held-out X queries score materially higher than Y queries - the round-1 corpus gap
  was 0.416 vs 0.236, so look for a gap of at least that order - **and** X queries reach `weak`
  or `strong` while Y queries skew `none`.
- **FAIL:** X and Y overlap, or everything returns `none`, or everything returns `strong`.

🔴 **If H2 fails, stop and tell acoustics workstream immediately.** It means acoustic retrieval does not
survive real-world capture, and we pivot the retrieval key to context (time-of-day, gap since
last episode, duration, escalation) - which the circadian colic literature independently
supports (`RESEARCH.md` §1). **That pivot costs one sentence of framing, not the product.** Do
not attempt the pivot yourself; report and stop.

### H3 - does the caregiver's voice matter? 🔴

Within the H2 results, split X queries by whether caregiver speech was present.

- **PASS:** speech-present and speech-absent X queries score comparably. Confirms B2's 0.909 at
  the different-occasion level and re-confirms "never separate the audio."
- **FAIL:** speech-present scores collapse → the overlay conclusion only held for identical
  audio, and `FINDINGS.md` §3 needs qualifying.

---

## 🟠 I - how many episodes before it is actually useful?

Round 1's **E3** is the reason for this test: with exactly 3 priors, all bands came back
`none, none, none` and the renderer honestly suppressed the claim. So three episodes is enough
to be *honest* and not enough to be *useful*. `MIN_EPISODES_FOR_MATCH = 3` is currently a guess
I made, not a measurement.

Using the H live corpus, store X-live episodes incrementally - n = 1, 2, 3, 4, 5, 6 - and after
each, query the 2 held-out X-live and 4 Y-live.

Report a table: `n | X band(s) | X mean sim | Y mean sim | Y false-strong count`.

**Output is a number, not a pass/fail:** the smallest n where held-out X reaches `weak` or better
while Y stays `none`. That number replaces the current `3`.

Two consequences follow, both **acoustics workstream's** to action, so just report:
- `config.MIN_EPISODES_FOR_MATCH` gets set to the measured value.
- The demo must seed **at least** that many episodes before the recall moment.

---

## 🟠 J - where does the channel boundary actually sit?

B2 proved same-channel works and cross-channel fails. Real parents will not be careful. This
test finds out how much sloppiness the product tolerates - and it determines whether this is
viable outside a lab.

From the H rig as reference, change **exactly one** variable and re-measure similarity against
the same stored X-live episodes:

| # | Variation | Report |
|---|---|---|
| J1 | speaker distance ~30 cm vs ~1 m | similarity + band |
| J2 | playback volume ±6 dB | similarity + band |
| J3 | different room | similarity + band |
| J4 | different capture device (phone mic instead of MacBook) | similarity + band |
| J5 | background noise added (TV / tap running) | similarity + band |

**Output:** a tolerance list. Which variations preserve the match, and which destroy it.

This becomes real product copy and a real limitation to state on stage - *"recordings need to
come from the same device"* is an honest constraint, and naming it before a judge finds it is
worth more than hiding it. If **J4 fails hard**, the product is single-device-only; say so in
`LIABILITY.md` and the README rather than discovering it in front of someone.

---

## 🔴 K - demo integrity

The demo currently seeds from corpus files and would query live. **Per B2, that is the failing
comparison.** Verify the demo path end to end without any corpus audio in it.

1. Seed **N live episodes** (N = the number from test I) recorded through the demo's own rig,
   with caregiver speech and real caregiver answers.
2. Run the real CLI loop: `record` → `finish` → recall.

- **PASS:** the recall card shows a genuine `strong`/`weak` match against a real prior **live**
  episode, with real extracted interventions and a real caregiver-reported outcome, and
  `outcome_src` reads `caregiver` - **not** `seed`.
- **FAIL:** `none`, or the only matches are corpus-seeded, or provenance reads `seed`.

Also confirm: nothing in the demo path renders `outcome_src="seed"` output as though it were
real (`LIABILITY.md` §7).

---

## Reporting

```
| test | PASS/FAIL | evidence (actual values) |
```

Plus, at the top: **the rig description** (device, distance, volume, room, gain) - without it
the H and J numbers are not reproducible and mean nothing.

Report every 🔴 including passes. Any 🔴 failure stops feature work.

## What round 2 settles

If H, I, J and K pass, the honest description upgrades from *"a validated approach with an
unverified implementation"* to **"a verified implementation with a known operating envelope"**,
and the frontend can begin.

If H fails, we learn today that the retrieval key must change, and we still have every other
component, the whole positioning, both tracks, and the diary. That is a much better place to
find out than on stage.
