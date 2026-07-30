# Empirical Findings

*All experiments run 2026-07-29 on macOS ARM. Every number below came from a script in
`experiments/`, not from an estimate. Where a result contradicted an earlier assumption, the
correction is recorded rather than the conclusion quietly changed.*

Dataset: [donateacry-corpus](https://github.com/gveres/donateacry-corpus) - 457 usable `.wav`
recordings, 221 device UUIDs (a UUID = one family's phone ≈ one infant), labelled
hungry / tired / discomfort / belly_pain / burping.

⚠️ **Label imbalance: 382 of 457 are "hungry."** Predicting "hungry" always scores ~84%. This
is why published cry-classification accuracies on this corpus should be discounted. We
therefore used the corpus for **identity/similarity** work only, never for cause labels.

---

## 1. Do a single baby's crying episodes separate acoustically?

This was the make-or-break question. The feared failure mode was not "nothing matches" but
**"everything matches"** - if all of one baby's cries are near-identical, retrieval always
fires with high confidence and always returns whatever happened to be logged.

Method: 1.5 s segments (0.75 s hop) → fingerprint → z-score against corpus → cosine.
Fingerprint = 20 MFCC means + 20 SDs + 20 delta means + 20 delta SDs + F0 stats
(mean/SD/p10/p90) + spectral centroid mean/SD + voiced fraction = **87 dims**.
2611 segments from 421 recordings / 207 babies; 101 babies had ≥2 separate recordings.

| Comparison | n pairs | mean cosine | SD |
|---|---|---|---|
| A - same crying episode | 7,757 | **+0.383** | 0.269 |
| B - same baby, *different* episode | 21,029 | **+0.195** | 0.238 |
| C - different babies | 3,378,569 | **-0.002** | 0.200 |

| Test | Cohen's d | AUC |
|---|---|---|
| A vs B - can similarity tell one episode from another, same baby? | 0.74 | **0.701** |
| B vs C - does a baby's own cry resemble itself more than a stranger's? | 0.89 | **0.732** |

**→ The "everything matches" failure does not occur.** Separate episodes from the same infant
remain distinguishable (AUC 0.70), while still being far more similar to each other than to
other infants (AUC 0.73). Both halves are necessary and both hold.

This independently reproduces what the literature says cries encode - **identity**, not cause.
See `RESEARCH.md` §1.

## 2. Retrieval

**Segment level** (`run.py`): top-1 nearest neighbour from a *different recording* returns the
same baby **22.0%** of the time vs **~1.1%** chance (n=1982). ~20× chance.

**Episode level** (`run2.py`) - the real product unit; segments averaged per recording:

| Metric | Result |
|---|---|
| top-1 = same baby | **30.5%** (chance 0.7%) - **~43× chance** |
| median rank of a true same-baby episode | **7 of 421** |
| top-5 / top-10 | 45.7% / 53.3% |

**Context for how conservative this is:** the search pool was **421 episodes from 207
different babies**. The product searches *one* baby's handful of prior episodes. The real task
is dramatically easier than the benchmark. Also note this is a hand-rolled MFCC fingerprint
with **zero learning** - a trained embedding (e.g. CryCeleb-style) would beat it.

---

## 3. ❌ Source separation is harmful - do not do it

Test: a real corpus cry mixed with `say`-generated caregiver speech overlapping it
("Oh sweetie, what's wrong? Are you hungry? Okay, let me get your bottle, here we go"),
speech delayed 1.2 s so it lands *on top of* the crying.

Separator (`sep.py`): per-frame autocorrelation F0 → cry if ≥300 Hz, speech if 70-280 Hz,
majority-smoothed, then gated reconstruction.

**Corpus-normalized similarity to the clean original cry:**

| | cosine | percentile vs 430 impostor cries |
|---|---|---|
| separated cry channel | **+0.031** | 57.4th - *no better than a stranger* |
| untouched mixture | **+0.474** | 99.3rd |
| impostor reference (n=430) | mean +0.002, p95 +0.240, max +0.695 | - |

**Why it fails - the pitch ranges genuinely overlap:**

| | F0 median | p10 | p90 |
|---|---|---|---|
| cry | 432.4 Hz | 240.6 | 761.9 |
| caregiver (`say` Samantha) | 188.2 Hz | 166.7 | 280.7 |

Cry p10 (240 Hz) sits *below* caregiver p90 (281 Hz). No threshold separates them. Run on a
**pure cry with no speech at all**, the separator still mislabels **19.6%** of frames as
speech - and gating those away is what collapses the fingerprint.

**Transcription tells the same story.** Ground truth:
*"Oh sweetie, what's wrong? Are you hungry? Okay, let me get your bottle, here we go."*

| input | `gpt-4o-transcribe` output |
|---|---|
| **untouched mixture** | "Oh sweetie, what's wrong? Are you hungry? Ok, let me get your bottle. Here we go." ✅ |
| separated speech channel | "Oh, sweetie, what's wrong? Are you hungry?" ❌ *second half lost* |

**→ Feed the raw mixture to both paths.** Speech ASR ignores the cry on its own; the MFCC
fingerprint survives speech laid over it. The separation requirement was solving a problem
that does not exist.

---

## 4. ❌ Generative audio models confabulate non-speech events

`gpt-audio` was tested as a one-shot "interaction logger" (audio in → JSON event timeline).

**Speech: excellent.** Accurate transcription, clean structured JSON first try, no wrangling.

**Non-speech: unusable.** Given a clip containing a 3.5 s tremolo tone at -15.6 dB mean - 
*louder on average than the speech in the same file* (-24.1 dB) - it:

- **missed the tone entirely**, and
- **invented three events that were not in the file**: "background rustling," "a soft breath
  or sigh," "soft clinking, possibly glass or plastic," and
- placed the speech at 0.3 s when it began at 4.0 s.

A speech-free tone clip produced no answer at all ("Let's take a listen:" then nothing).

*Fair caveat:* a synthetic tremolo tone is out-of-distribution and a real cry would likely
fare better - untested. But fabricating three specific naturalistic events with confident
timestamps, in a file we constructed ourselves, is not excused by that.

**→ Never put a generative model in the non-speech detection path.** A wrong-but-confident
event log is worse than none: the pattern engine downstream will faithfully count fiction and
report high confidence in it. Use deterministic features for signal; use the LLM only for
speech and for narrating an already-verified log.

---

## 5. ⚠️ Normalization is load-bearing - the single most important implementation note

Comparing **raw** (un-normalized) fingerprints by cosine is meaningless. Measured:

| pair | raw cosine |
|---|---|
| a **completely different baby** | **+0.9999** |
| the target file vs **itself** (re-encoded) | +0.9915 |

Raw MFCC-statistic vectors share a large common component, so everything is ~0.99 similar to
everything. **This is exactly the "everything matches" failure mode, and it appears the instant
you skip normalization.** In the corpus-normalized space the same target's nearest non-self
neighbour drops to +0.491.

**→ Always z-score against a stored baseline (`mu`, `sd`) before cosine.** Ship those vectors
as part of the model. Skipping this yields an app that confidently gives the caregiver the
same answer forever while appearing to work.

---

## 6. Not yet tested

- **The stroke / dysarthric arm.** No result. Corpora (TORGO, UASpeech) are access-gated. A
  slurred word (~0.5-1.5 s, quiet, consonant-driven) gives a far thinner fingerprint than a
  7 s cry. *Possible advantage:* a patient reaching for "water" is an intentional, repeated
  articulation - plausibly **more** consistent across days than a cry. Untested either way.
- **Whether acoustically similar cries share a cause.** Untestable on this corpus (382/457
  "hungry"). The product design routes around it: the caregiver supplies the meaning.
- **Real-room robustness.** All cry audio here is 7 s phone recordings. Hackathon venue noise,
  device variation and mic distance are unmeasured.
- **Context features.** Time-of-day / time-since-feed are strongly supported by the colic
  literature (`RESEARCH.md` §1) but contribute nothing yet - the corpus has timestamps but no
  feed or intervention data.

---

## Environment notes

- `ffmpeg` and a `whisper` CLI are already on the target machine.
- An `OPENAI_API_KEY` exists at `~/apphatchery-discovery/.env`. That key has access to
  `gpt-audio`, `gpt-audio-1.5`, `gpt-4o-transcribe`, **`gpt-4o-transcribe-diarize`**,
  `gpt-realtime*`, `gpt-live-transcribe`, and `gpt-5.5` (125 models total).
- **Do not install `librosa`** - its `numba`/`llvmlite` dependency fails to build on
  Python 3.12 / macOS ARM. All features here are numpy + scipy only, by necessity.
- OpenAI has **no audio embedding endpoint**; acoustic fingerprinting must be local.
