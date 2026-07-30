# Identity model challenger results

Date: 2026-07-30

Scope: adult human identity while imitating a cry

Decision: keep the current CryCeleb ECAPA encoder

## What was tested

The challenger was the official WeSpeaker CAM++ large-margin model:

- artifact: [Wespeaker/wespeaker-voxceleb-campplus-LM](https://huggingface.co/Wespeaker/wespeaker-voxceleb-campplus-LM)
- architecture paper: [CAM++](https://arxiv.org/abs/2303.00332)
- runtime: official 29.3 MB ONNX checkpoint through ONNX Runtime
- input: 16 kHz mono audio, official 80-bin Kaldi filterbank with cepstral mean normalization
- embedding: 512 dimensions with L2 normalization before cosine comparison

The local evaluation used:

- three Prasshanna reference imitations;
- two control-person reference imitations;
- two blind Prasshanna queries;
- leave-one-out comparison across all five reference recordings; and
- the same nine channel perturbations used for the incumbent encoder.

Only Prasshanna references were perturbed. The control references and blind queries were left
untouched. This is a falsification test for channel dependence, not a substitute for more people.

## Plain-language result

| Measure | CAM++ challenger | Current CryCeleb encoder |
|---|---:|---:|
| reference recordings identified correctly | 4 of 5 | 5 of 5 |
| blind queries identified correctly | 1 of 2 | 2 of 2 |
| channel conditions with every decision correct | 0 of 9 | 9 of 9 |
| warm median inference time per file | 0.160 seconds | about 0.20 to 0.24 seconds |

CAM++ was modestly faster, but it consistently assigned the second blind Prasshanna query to the
control profile. Every tested channel condition retained that wrong decision. Speed cannot
compensate for a failed blind identity result.

## Decision

CAM++ does not enter the production encoder registry and `onnxruntime` does not enter the project
requirements.

The current routing remains:

- infant fixed-rig identification: `mfcc87-v1`;
- adult cry-imitation identification: `ecapa-cryceleb-v1`.

This result does not prove CryCeleb is generally accurate for adult imitations. It proves only that
CryCeleb is the stronger of these tested choices on the available held-out recordings and channel
perturbations.

## Other current candidates

- Microsoft WavLM Base+ speaker verification has downloadable weights and a reasonable robustness
  rationale, but its exact public checkpoint does not publish the relevant adult-cry or infant
  benchmark. It is much larger than the current model. It remains a future challenger only after a
  larger identity-disjoint recording set exists.
- A 2025 infant-verification repository reports gains from slice and multi-view evaluation, but it
  does not provide a new infant-adapted checkpoint. The local aggregation spike also found no
  candidate that beat the incumbent under the shipped gates.
- Cohort normalization is closed. Deeper local evaluation found no identity gain and worse
  safe-end true-accept behavior.

## Reproducibility note

The rejected model and benchmark script remain in the ignored `work/campplus/` directory for local
reproduction. They are not production dependencies.
