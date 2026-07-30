# Positioning - the sophisticated frame

*How to describe this so it reads as a serious instrument rather than a cry-translator app.
Every frame here is load-bearing and citable.*

---

## The one-sentence positioning

> **An n-of-1 trial engine disguised as a memory aid.**

Passive ambient capture of a real caregiving interaction, paired with an active caregiver
report at the moment of outcome, accumulating into a per-subject longitudinal record that
supports single-case inference about what actually works for *this* individual.

Everything below justifies each clause with literature.

---

## Why this frame is genuinely sophisticated (not just repackaging)

### 1. It is textbook passive + active digital phenotyping

**Digital phenotyping** = *"moment-by-moment quantification of the individual-level human
phenotype in situ using data from personal digital devices."* The field's canonical design
combines **passive** data (collected automatically, no user input) with **active** data
(**Ecological Momentary Assessment** - prompting the person to report on their experience in
real time, in their natural environment).

Our architecture is exactly that pairing, and it wasn't designed to be - it fell out of the
engineering:

| Our component | The established construct |
|---|---|
| Ambient audio during the interaction | **passive sensing** |
| "What stopped the crying?" on stop | **EMA** - active, in-the-moment, in situ |
| Per-subject accumulation over weeks | **longitudinal digital phenotyping** |

Sources: [Frontiers - digital phenotyping systematic review](https://www.frontiersin.org/journals/digital-health/articles/10.3389/fdgth.2026.1772744/full) ·
[EMA + passive sensing](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10333535/) ·
[Quantifying Maternal Health Using Digital Phenotyping](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12547330/)

> **Say "passive sensing plus ecological momentary assessment," not "the app listens and then
> asks a question."** Same system, entirely different altitude.

### 2. Ambient daylong home audio of infants is an established research instrument

This is the pedigree for the ambient-listening differentiator, and it removes the "is that
even acceptable?" objection before it's raised.

- The **LENA** system (wearable recorder + automated vocal analysis) has been the standard
  method for studying infant environments from **daylong naturalistic home recordings** for
  over a decade.
- **HomeBank** is a *public, permanent, extensible online repository* of daylong child-centred
  audio recorded in naturalistic environments.
- **ALICE** is an open-source analysis tool for the same recordings.
- The literature's own stated motivation is ours: laboratory observation does not generalise to
  real parent-child interaction, and manual transcription of naturalistic recordings has been
  the bottleneck making it *"impractical to scale or sustain."*

Sources: [Mapping the Early Language Environment (AJSLP)](https://pmc.ncbi.nlm.nih.gov/articles/PMC6195063/) ·
[HomeBank](https://www.lena.org/resources/research/research-database/homebank-an-online-repository-of-daylong-child-centered-audio-recordings/) ·
[ALICE](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8062390/) ·
[LENA literature review](https://www.sciencedirect.com/science/article/abs/pii/S0021992416301861)

> **We are the LENA lineage pointed at a different question.** LENA counts words to study
> language. We capture interactions to learn what soothes. Same accepted instrument class,
> unclaimed target.

### 3. ⭐ The strongest argument in the whole project

Single-case experimental design methodology states that **N-of-1 / alternating-treatment /
ABAB designs require an intervention with three properties: *immediate effects, short washout,
and on/off effects.***

**Infant soothing interventions have precisely those three properties.** You rock the baby; it
works or it doesn't, within minutes; the effect does not persist and does not contaminate the
next attempt.

And separately, from the colic literature (see `RESEARCH.md` §2): colic has **no established
cause, no cure, and no evidence-based soothing guidelines.**

Put those together:

> **Infant soothing is one of the rare interventions methodologically *ideal* for n-of-1
> inference, in a condition where population-level evidence does not exist - and nobody has
> ever instrumented it.**

The SCED literature makes the general case for us: *"There is considerable heterogeneity of
treatment effects in randomized trials, with the trial capturing the average benefit, which
cannot always be generalized to the individual patient. Whenever feasible, N-of-1 trials should
be preferred to other SCEDs and to group randomized controlled trials."*

So personalization here is not a product convenience. **It is the methodologically preferred
design for this exact class of problem.**

Sources: [SCEDs in developmental-behavioral pediatrics](https://pubmed.ncbi.nlm.nih.gov/14671479/) ·
[SCEDs for child neurological rehabilitation (DMCN)](https://onlinelibrary.wiley.com/doi/10.1111/dmcn.15513) ·
[Harvard Data Science Review - Personalized (N-of-1) Trials](https://hdsr.mitpress.mit.edu/pub/nqvadq0w/download/pdf) ·
[Single-case design in pediatric psychology](https://pubmed.ncbi.nlm.nih.gov/24003176/)

---

## Mapping to both hackathon tracks

We legitimately occupy both, and they are two halves of one instrument.

### T1 - Health data collection from non-obvious signals

The non-obvious signal is **not the cry**. Everyone records cries. The non-obvious signal is
**the caregiver's own speech and behaviour during the episode** - an untapped, continuously
available record of what was actually attempted.

| What we collect | Why it is non-obvious |
|---|---|
| Ordered intervention sequence, extracted from the caregiver's speech | Nobody logs *attempts*; apps log the cry |
| Outcome, from the caregiver at the moment of resolution | The only reliable ground truth available |
| Acoustic signature of the episode | Verified: carries individual identity (AUC 0.73) |
| Context: hour-of-day, gap since last episode | Strongly supported by circadian colic evidence |

The whole insight of T1 for us: **the intervention log is the valuable signal, and it is
sitting unrecorded in speech that is already happening in the room.**

### T2 - Health over time

A single episode is worth almost nothing. The record only becomes an answer through
accumulation - which is the definition of the track:

- Cross-episode retrieval (verified: AUC 0.70 within-subject)
- Per-subject intervention success rates that only exist longitudinally
- An auto-generated **cry diary** - currently a manual paper instrument in colic assessment
- Circadian pattern surfacing, which requires weeks (evening peak ~7-8pm is documented)

> **Framing for the room: T1 is the instrument, T2 is the finding. We built both because
> neither is useful alone.**

---

## The superset strategy - match them, then beat them

Per the directive: do what existing tools do well *and* our differentiator.

| Capability | Who does it well | Ours |
|---|---|---|
| Acoustic characterisation of a cry | ChatterBaby (~90% on pain) | ✅ include as *description* - intensity, duration, F0 - **never as a cause label** |
| Logging + personalised prediction | Huckleberry SweetSpot | ✅ include; ours logs *interventions*, not just sleep |
| Personalised acoustic matching | Voiceitt, Project Relate | ✅ same engine; ours needs **no enrollment** |
| Cry diary for clinical assessment | paper instruments | ✅ **auto-generated** - nobody does this |
| Communication passport / handover | paper (AAC practice) | ✅ **auto-generated** - nobody does this |
| **Interaction → outcome learning** | **nobody** | ⭐ **the differentiator** |
| **Ambient capture of the live interaction** | **nobody in this space** | ⭐ **the differentiator** |

**The defensible claim: every competitor models the signal. We model the interaction.** Two of
the seven rows above are unoccupied, and both are ours.

## Ambient listening as the differentiator - say it precisely

Weak: *"the app listens in the background."*

Strong: **"Existing tools ask the caregiver to point a phone at a crying baby and press
record - capturing the signal but discarding the response. We capture the whole episode as it
happens, so the caregiver's attempts and their outcome are preserved. The recording is the
interaction, not the cry."**

That sentence contains the technical differentiator, the data differentiator, and the reason
nobody else has the dataset. It is also literally what the verified pipeline does - the raw
mixture, un-separated, is what makes it possible (`FINDINGS.md` §3).

## The research-tool endgame

Position it as an instrument that generates evidence where none exists:

> Colic has no evidence-based guideline because the necessary data - thousands of
> intervention-outcome pairs, per infant, in situ, over the natural course of the condition - 
> has never been collected. **This is the collection instrument.** Whether it helps colic is
> the open question, and the tool is how you would answer it.

That is an honest, high-ceiling claim that requires **no** clinical assertion. We are not
claiming to treat colic. We are claiming to build the instrument that could tell you whether
anything does. See `LIABILITY.md` - this framing is also the regulatorily safe one, which is
not a coincidence.

## Language discipline

| ❌ Never say | ✅ Say instead |
|---|---|
| "solves colic" / "treats colic" | "helps you see what you have already tried" |
| "tells you why your baby is crying" | "finds the most similar episode on record" |
| "81% confident it's hunger" | "a similar episode: you fed him, it worked" |
| "diagnoses" / "detects a condition" | "describes" / "logs" / "recalls" |
| "AI understands your baby" | "your own history, searchable" |

The left column is a medical-device claim (`LIABILITY.md` §1) *and* scientifically unsupported
(`RESEARCH.md` §1). The right column is neither, and is a better product.
