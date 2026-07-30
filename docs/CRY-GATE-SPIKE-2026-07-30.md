# Infant Cry Presence Gate Spike

Date: 2026-07-30

Status: candidate selected, production integration not yet complete.

## Question

Can a local, non-generative model reject ordinary sounds before infant identity and care-memory
retrieval, while staying fast enough for a 12-second rolling capture loop on the demo laptop?

## Candidates

The selected candidate is:

```text
MIT/ast-finetuned-audioset-10-10-0.4593
Target class: Baby cry, infant cry
Comparison class: Crying, sobbing
Runtime: PyTorch 2.6 plus Transformers 4.48.3
License: BSD 3-Clause
```

YAMNet is smaller, but its official path adds TensorFlow and a documented Keras compatibility
constraint. EfficientAT is also smaller, but its official environment pins an older Torch and
numpy stack and depends on `librosa`, which this repository deliberately excludes.

Primary sources:

- [MIT Audio Spectrogram Transformer checkpoint](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593)
- [Google AudioSet Baby cry, infant cry class](https://research.google.com/audioset/ontology/baby_cry_infant_cry.html)
- [ESC-50 repository](https://github.com/karolpiczak/ESC-50)
- [TensorFlow YAMNet tutorial](https://www.tensorflow.org/hub/tutorials/yamnet)
- [EfficientAT repository](https://github.com/fschmid56/EfficientAT)

## Measured rule

Use one centered view of at most 10 seconds from each 12-second segment.

```text
strong infant-cry-like event:
  infant score >= 0.040
  AND infant score >= 1.20 * generic crying score

borderline:
  not strong
  AND infant score >= 0.025

negative:
  infant score < 0.025
```

Only strong evidence may continue to infant identity. Borderline evidence is an abstention and
continues listening. No score is shown to a caregiver.

## Results

| set | strong accepted | strong rejected |
|---|---:|---:|
| ESC-50 `crying_baby` | 40 of 40 | 0 |
| ESC-50 sampled environmental negatives | 0 | 245 of 245 |
| checked-in infant clips | 14 of 18 | 4 of 18 |
| checked-in adult cry imitations | 0 | 10 of 10 |
| synthetic silence, white noise, tones, and chirp | 0 | 5 of 5 |

The borderline rule would recover three more checked-in infant clips, for 17 of 18, but it also
accepted one of 245 ESC-50 environmental negatives, a cat. Borderline therefore cannot trigger
identity or guidance.

ESC-50 official folds 1 to 3 were used for threshold selection. Folds 4 to 5 were untouched
evaluation data:

| split at borderline threshold | true positive | false positive | false negative | true negative |
|---|---:|---:|---:|---:|
| folds 1 to 3 | 24 | 1 | 0 | 146 |
| folds 4 to 5 | 16 | 0 | 0 | 98 |

The strong rule had no false positive or false negative in this sampled ESC-50 evaluation.

## Latency and footprint

Measured on the demo Mac CPU:

| measurement | result |
|---|---:|
| fresh process including imports | 6.81 seconds |
| first inference | 2.45 seconds |
| warm checked-in infant inference | about 0.45 to 0.98 seconds |
| warm mean | about 0.65 seconds |
| cached model | about 330 MB |
| measured process memory after inference | about 433 MB |

The model must be downloaded, pinned, cached, and warmed before the presentation. Inference is
offline after the model is cached.

## Rejected aggregation

Do not maximize across short overlapping windows.

| input view | adult imitations incorrectly strong |
|---|---:|
| one full centered view | 0 of 10 |
| maximum over 5-second windows | 4 of 10 |
| maximum over 3-second windows | 5 of 10 |

Several short-window adult scores rose into the 0.38 to 0.57 range. Short-window maximization is
both less safe and much slower for this demo.

## Claim boundary

This gate reports an infant-cry-like acoustic event. It does not:

- identify the infant;
- prove a biological infant against a skilled imitation;
- infer hunger, pain, tiredness, illness, or another cause;
- replace the separate infant identity gate;
- validate population accuracy.

The checked-in infant clips are direct 8 kHz corpus derivatives. They are not phone-to-laptop
same-channel captures. Fixed-rig rehearsal remains mandatory.

## Release gate

Before the presentation:

1. Every planned Baby 1 query must be strong in five consecutive fixed-rig runs.
2. Speech, music, clapping, water, room noise, a ringtone, and adult imitation must never produce a
   strong result in the fixed rig.
3. Borderline results must call neither identity nor history.
4. Model failure must block the care path.
5. Public payloads must contain no diagnostic scores.
6. Windows Python 3.12 startup and model warm-up must pass.

For a future claim beyond the hackathon set, collect at least 100 same-channel infant-cry segments
and 300 same-channel non-cry segments across sessions. A false-trigger claim below 0.1 percent per
segment would need roughly 3,000 held-out negative segments with zero false accepts for a
rule-of-three 95 percent upper bound. Report false alerts per hour.
