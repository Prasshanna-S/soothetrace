# Evaluation and limitations

## Read this before using any result

SootheTrace is a proof of concept. Its measurements are controlled engineering checks, not clinical validation or population accuracy. The prototype is not validated for unseen infants, arbitrary homes, varying devices, or safety-critical use.

## What was checked

| Check | Observed result | What it does and does not show |
|---|---:|---|
| ESC-50 baby-cry subset | 40 of 40 accepted | A limited gate check on selected benchmark clips. It does not estimate real-world sensitivity. |
| Sampled environmental negatives | 245 of 245 rejected | A limited negative check. It does not establish a false-alarm rate. |
| Checked-in infant rehearsal fixtures | 14 of 18 accepted | Fixture behavior only. Those recordings are not a representative sample. |
| Adult cry-imitation fixtures at the infant gate | 10 of 10 rejected | A small adversarial check. It does not prove the gate distinguishes every adult from every infant. |
| Two-profile fixed-rig infant trial | 13 of 15 correct, 0 wrong names | Controlled replay under one setup. Two trials abstained or needed retry. It does not establish cross-device identity performance. |
| Controlled Demo Baby retrieval | 3 of 3 expected distinct suggestions | Demonstrates that seeded synthetic histories can produce three different grounded outputs. It does not show that a cry reveals a cause or that an action will work. |

The gate and profile results are affected by room acoustics, playback device, microphone, distance, gain, codec, background sound, and recording path. The fixed-rig infant trial should be treated as a narrow operating-envelope check.

## Human-imitation cohort

The separate human-imitation evaluation uses 10 correlated recordings from 3 consenting adults. It tests an open-session product path in which adults imitate cries. It is useful for checking that the implementation can create provisional participants, abstain, and avoid some wrong assignments in that small scenario.

It is not evidence of infant identity, voice-biometric performance, demographic fairness, real-world speaker recognition, or population accuracy. Human audio fixtures and detailed raw results require a separate privacy and release review before public distribution.

## Interpretation rules

- Do not convert cosine similarity, rank score, or an ordinal band into a probability or percentage confidence.
- Do not claim that acoustic similarity identifies a baby in unconstrained conditions.
- Do not claim the system knows why a baby is crying.
- Do not claim a previously helpful action will help in the current episode.
- Do not use the prototype as medical advice, an emergency monitor, or a substitute for a caregiver or clinician.

## What better evidence would require

A future evaluation should use verified and consented infant identity data with multiple sessions per infant, identity-disjoint calibration and test sets, varied phones and rooms, open-set recordings, preregistered operating points, and transparent reporting of coverage, wrong-name rate, abstention, false alarms, and uncertainty. A hosted or commercial product would also require privacy, security, clinical, and legal review.
