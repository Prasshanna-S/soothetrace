# Identity Accuracy Status

This document separates measured improvements from planned improvements. The current proof of
concept has two identity paths:

- Baby cry matching uses the deterministic MFCC87 encoder in the live fixed-rig demo.
- Human cry imitation matching uses the infant-adapted CryCeleb ECAPA encoder.

The server compares a query only with enrolled profiles of the same kind. Time, caregiver notes,
and prior outcomes do not influence identity. Those signals are used only after identity resolves,
when the system ranks earlier incidents from that profile.

## Metrics in plain language

| Metric | Meaning |
|---|---|
| Rank-1 | How often the correct profile is the nearest profile before the system applies any acceptance gate. |
| Coverage | How often the system names a profile instead of asking for another recording or remaining unresolved. |
| Precision when naming | Of the cases where a profile was named, how often that name was correct. |
| Wrong-name rate | Of the cases where a profile was named, how often that name was wrong. |
| Abstained | The system had insufficient evidence and did not guess. |

Coverage and precision must be read together. A system can obtain high precision by naming almost
nobody. It can obtain high coverage by guessing too often. The demo target is at least 50 percent
coverage and at least 75 percent precision when naming, measured on held-out queries.

## Exact recording-matched encoder comparison

Both encoders were evaluated on the same 46 proxy identities and the same 205 recordings. Pairs
used to select gates were disjoint from pairs used to evaluate them, and the roles were crossed.

| Encoder | Full-pool rank-1 | Two-profile rank-1 | Correct | Wrong | Abstained | Coverage | Precision when naming |
|---|---:|---:|---:|---:|---:|---:|---:|
| MFCC87 | 36.1% | 87.8% | 118 | 11 | 76 | 62.9% | 91.5% |
| CryCeleb ECAPA | 51.2% | 90.2% | 148 | 5 | 52 | 74.6% | 96.7% |

CryCeleb produced 30 more correct names, six fewer wrong names, and 24 fewer abstentions. Coverage
improved by 11.7 percentage points and precision when naming improved by 5.2 percentage points.
This is a measured improvement under the exact recording-matched proxy-corpus protocol.

A simple weighted fusion was also tested. Its crossed two-profile rank-1 was 89.8 percent, below
CryCeleb alone at 90.2 percent, so it was rejected.

The initial MFCC comparison used a stored population normalization baseline that included
evaluation audio. A stricter cross-fitted check rebuilt that baseline from each calibration half
only. MFCC then produced 113 correct names, 9 wrong names, 83 abstentions, 59.5 percent coverage,
and 92.6 percent precision. CryCeleb does not use this baseline and remained at 148 correct, 5
wrong, 52 abstentions, 74.6 percent coverage, and 96.7 percent precision.

## Why CryCeleb is not yet the live infant default

The small fixed-rig infant study favored MFCC87:

- MFCC87 rank-1: 93.3 percent
- CryCeleb rank-1: 87.5 percent

The proxy corpus and the live demo use different recording channels. Encoder thresholds also have
different numeric scales. A threshold calibrated for MFCC87 must never be reused for CryCeleb.

CryCeleb can be promoted for infant matching only after:

1. enrollment and query use the same phone capture or file-upload channel;
2. the two encoders are evaluated on identical held-out phone-channel recordings;
3. CryCeleb improves correct identification or coverage while preserving the declared precision
   floor; and
4. thresholds are calibrated for CryCeleb on calibration recordings that are not reused as the
   final evaluation set.

Human imitation already uses CryCeleb because it won the local held-out comparison for that mode.

## Local product-path results

The current API acceptance set contains six held-out queries:

| Mode | Correct | Wrong | Needed retry |
|---|---:|---:|---:|
| Two infant profiles | 4 of 4 | 0 | 1 |
| Two adult imitation profiles | 2 of 2 | 0 | 1 |
| Combined | 6 of 6 | 0 | 2 |

These are useful demo checks, not population accuracy estimates. The samples are small and
correlated.

## Proxy corpus limitation

The public Donate-a-Cry corpus does not provide verified baby identity. This project uses the
filename or device UUID as a proxy identity. Corpus measurements therefore test whether the
pipeline can separate repeated sources and recording channels at scale. They do not establish
population-level baby recognition accuracy.

Broader claims require identity-labeled infant data with:

- at least two sessions per infant;
- multiple recordings per session;
- identity-disjoint training, calibration, and evaluation;
- crossed device and room conditions;
- enrolled-profile pools of several sizes; and
- open-set recordings from unenrolled infants.

## Next accuracy experiments

The next experiments are ordered by expected value:

1. Collect matched phone-channel enrollment and held-out query files for two infant profiles.
2. Run MFCC87 and CryCeleb on the exact same files and freeze the better operating point.
3. Test short overlapping CryCeleb slices and aggregate the normalized embeddings.
4. Test realistic codec, playback, room, noise, and resampling augmentation on enrollment views.
5. Fine-tune CryCeleb on identity-labeled infant data with session and device disjoint evaluation.

No experiment is promoted because it sounds promising. It must improve an untouched evaluation.
