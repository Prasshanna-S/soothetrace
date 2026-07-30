# Research & Competitive Analysis

*Compiled 2026-07-29. Every claim is sourced. Where the literature contradicts the product
premise, that is stated plainly rather than smoothed over.*

---

## 1. Is the core premise scientifically supported?

The premise has two halves. **One is supported. One is not.**

### ❌ NOT supported: "a cry's sound reveals why the baby is crying"

This is the claim almost every existing cry app makes, and the literature does not support it.

- A 2023/2024 study in *Communications Psychology* found infant cries reliably convey
  **age and identity** - but **not** cause. The authors state that **"neither machine learning
  algorithms nor trained adult listeners can reliably recognize the causes of crying."**
  ([Nature Comms Psych](https://www.nature.com/articles/s44271-023-00022-z),
  [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11332224/))
- The same work **failed to validate Dunstan Baby Language**, the best-known "cry types"
  system, whose five categories were "defined without scientific validation."
  ([Wikipedia summary](https://en.wikipedia.org/wiki/Dunstan_Baby_Language))
- The historical view - discrete cry types each mapping to a discrete cause - is now
  considered wrong. Parents *can* discriminate very distinct contexts (**pain vs. mild
  discomfort**) but not fine-grained causes.
  ([review](https://link.springer.com/article/10.1186/s13636-021-00197-5))

**Pain is the exception.** Pain cries are genuinely distinguishable (higher-pitched wailing,
less silence). ChatterBaby reports ~85-90% accuracy on pain, but only ~71.5% when
discriminating fussy vs. hungry vs. pain.

**Beware the benchmark numbers.** A 2026 systematic review reports MFCC-based models at
**96.39%** on five classes, and humans at 33% vs. ML at 80.6% on the same data
([review](https://pmc.ncbi.nlm.nih.gov/articles/PMC12804663/),
[Frontiers](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2024.1337356/full)).
These come from small curated corpora. We independently confirmed why they should be
discounted: the standard public dataset (donateacry) is **382 "hungry" out of 457 files** - 
predicting "hungry" always yields ~84%. High reported accuracy on that data is mostly label
imbalance. See `FINDINGS.md`.

> **Implication: do not claim to identify why the baby is crying.** It is not defensible, and
> a judge who reads one paper can dismantle it.

### ✅ SUPPORTED: "a cry carries a stable individual signature"

This is precisely what the literature *does* say cries encode - **identity**. And it is the
half our design actually relies on.

- Infant cry **speaker verification** is an established research task with a public benchmark:
  **CryCeleb** (Ubenwa), ~800 infants. ([arXiv](https://arxiv.org/abs/2305.00969),
  [HuggingFace](https://huggingface.co/datasets/Ubenwa/CryCeleb2023))
- Our own measurements reproduce this: a baby's cries across separate occasions resemble each
  other far more than other infants' cries (AUC 0.73), *and* separate episodes from the same
  baby remain distinguishable from one another (AUC 0.70).

So the retrieval mechanism sits on the supported half of the science, and the interpretation
is handed to the human. That is the whole trick.

### ✅ SUPPORTED: context is genuinely predictive

The instinct to log time-of-day is well founded:

- Infant crying has a **circadian component**, with a consistent **evening peak around
  7-8pm** and a smaller peak 12 hours earlier.
- Crying follows a developmental arc - rising from ~2 weeks, and a meta-analysis of 28 diary
  studies found fuss/cry duration stable at **117-133 min/day** for six weeks, dropping to
  **68 min** by 10-12 weeks. (Notably, that meta-analysis found **no** universal 6-week peak.)
  ([J Pediatrics](https://www.jpeds.com/article/S0022-3476(17)30218-4/fulltext))
- Colicky infants show **disrupted circadian gene expression** vs. controls.

Time-of-day, time-since-feed and infant age carry real signal that acoustics alone do not.
**Context is not a garnish here - it is likely the strongest feature in the system.**

---

## 2. The colic literature is the single best thing in this analysis

This is what makes the project defensible by three non-clinicians:

- Colic has **no established cause and no cure**.
- **"No universal evidence-based guidelines exist"** for soothing.
- **"Although there is no evidence for the benefit of soothing techniques, they cost nothing,
  and the placebo effect of any therapeutic intervention... may reach up to 50%."**
- **"The goals of management are to help the parents cope with the crying"** - not to stop it.
- Excessive crying is associated with caregiver frustration and sleep deprivation, and colic
  is **a risk factor for child abuse**.

([StatPearls](https://www.ncbi.nlm.nih.gov/books/NBK518962/),
[Recent advances in managing infantile colic](https://pmc.ncbi.nlm.nih.gov/articles/PMC6134333/),
[Medscape](https://emedicine.medscape.com/article/927760-treatment))

Two consequences, both favourable:

1. **A tool aimed at helping the parent cope is aligned with the actual clinical goal of colic
   management.** A tool that claims to diagnose the cause is not. Our framing is the
   clinically endorsed one - by accident, but it is.
2. **Because no population-level answer exists, n-of-1 personalization is the scientifically
   appropriate response.** This is a real intellectual argument, not a hackathon dodge: when
   there is no general answer to look up, the only answer available is what worked for *this*
   infant. That is exactly what the system stores.

The child-abuse link also establishes genuine stakes without requiring anyone to make a
clinical claim on stage.

---

## 3. Competitive landscape

### 3a. Baby cry analyzers - **saturated and commoditized. Avoid competing here.**

The App/Play stores contain a dozen near-identical products: *Baby Cry Analyzer & Translator*,
*Baby Translator*, *Nanni AI*, *CryAnalyzer* (claims 20M cries analyzed, >80% accuracy),
*BabyLingo*. All do the same thing: record → classify into hunger/tired/discomfort/burping.

The credible one is **ChatterBaby** (UCLA Semel Institute, Ariana Anderson): 20,000+ sounds,
~90% on pain, published, in both stores, and **it already published the colic study** - cries
from parent-described colic had a **73% chance of being classified "painful"** in *Pediatric
Research*. ([UCLA Health](https://www.uclahealth.org/news/article/chatterbaby-an-app-that-helps-parents-know-when-and-why-their-baby-is-crying-used-in-new-research),
[Pediatric Research](https://www.nature.com/articles/s41390-019-0592-4))

> **Honest read: "AI tells you why your baby is crying" is a crowded market built on a
> scientifically shaky claim. Do not enter it. Our differentiation depends on *not* being
> this.**

### 3b. Logging + personalized prediction - **partially occupied**

**Huckleberry's SweetSpot** logs parent-entered data, compares against "hundreds of millions
of data points," and predicts optimal nap timing - explicitly getting **"smarter the more you
track."** ([Huckleberry](https://huckleberrycare.com/blog/sweetspot-your-smart-sleep-timing-companion))

> **This weakens any claim that "learns your individual baby from logs" is novel.** It is
> novel *for cry interventions*, not as a mechanism. Do not oversell this axis.

### 3c. Atypical speech / the stroke arm - **occupied by well-funded players**

- **Voiceitt** - personalized model for dysarthric speech factoring "tone, cadence, non-speech
  sounds and pauses." Critically, it uses a **closed dictionary with discrete speech
  recognition** - the user must **enroll by training known phrases**.
  ([Forbes](https://www.forbes.com/sites/gusalexiou/2021/06/30/voiceitt-app-for-atypical-speech---a-triumph-in-disability-co-design/))
- **Google Project Euphonia / Project Relate** - personalized ASR for non-standard speech.
  ([Google Research](https://research.google/blog/project-euphonias-personalized-speech-recognition-for-non-standard-speech/))
- ⭐ **"Latent Phrase Matching for Dysarthric Speech"** (Apple, Interspeech 2023 - 
  [arXiv 2306.05446](https://arxiv.org/pdf/2306.05446),
  [Apple ML Research](https://machinelearning.apple.com/research/latent-phrase-matching),
  [ISCA](https://www.isca-archive.org/interspeech_2023/yee23_interspeech.pdf))
- the closest prior art to our stroke design, and **it validates the core mechanism.**
  LPM is query-by-example personalized phrase recognition: it builds a per-phrase model from
  latent embeddings of a large-scale keyword spotter, trained on **small amounts of speech**,
  language-agnostic, with **no pronunciation lexicon**.

  Results, across 63 people with dysarthria in two languages:
  - **+60% recall vs. a commercial ASR system** on 32 people with dysarthria, *regardless of
    severity*
  - **+30.5% accuracy** on the public EasyCall dysarthric corpus
  - beats ASR even at 50 unique phrases, though it degrades as phrase count grows
  - **"phrase recognition performance is much higher for people with severe dysarthria than
    traditional ASR systems"**

  **This is a citation for our rule, not a threat to it.** Our `AGENTS.md` constraint "never
  transcribe the impaired speaker - match acoustically instead" is now backed by a peer-reviewed
  60% recall improvement. We reached it from a failure we measured; Apple reached it from the
  other direction. Use this in the pitch.

  What it does *not* do, and where we differ: LPM is **enrollment-based** (the user supplies
  samples per phrase) and **closed-set** (a fixed phrase list that degrades as it grows).

> **Honest read: the stroke arm is the most contested ground, not the most novel - but the
> mechanism is now externally validated.** Every system above requires the user to deliberately
> train known phrases against a fixed vocabulary. Ours has **no enrollment step and no fixed
> vocabulary**: the utterance is captured in the interaction that was going to happen anyway,
> and the caregiver supplies the meaning afterwards. That is the differentiator, and LPM's
> phrase-count degradation is the reason it matters.

### 3d. Communication dictionaries - **the actual white space**

AAC practice already contains our idea, on paper:

- A **"gesture dictionary"** - a caregiver-authored record of what an individual's idiosyncratic
  behaviours mean - is established practice for non-symbolic communicators.
  ([ASHA/NJC](https://www.asha.org/njc/aac/), [UNL AAC](https://aac.unl.edu/aac-terminology/))
- **Communication Passports** are a formal instrument for carrying this information between
  caregivers. ([communicationpassports.org.uk](https://www.communicationpassports.org.uk/),
  [PAMIS Digital Passports](https://pamis.org.uk/services/digital-passports/))

These are **hand-written, static documents**. Nobody generates them automatically from
recorded interactions. That gap is the strongest novelty claim available.

**Read: *Foundation Models in AAC: Opportunities and Challenges*** - Di Paola, Muraro,
Marinelli & Pilato, IEEE Systems Journal
([arXiv 2401.08866](https://arxiv.org/pdf/2401.08866),
[PDF](https://www.fondazioneartos.it/wp-content/uploads/2025/01/Articolo_CAA.pdf)).

It proposes **AMBRA**, a federated-learning + generative-AI platform for pervasive personalized
AAC. The problems it names as open are, almost exactly, the ones we are attacking:

- **Pre-defined symbol libraries "may not perfectly match an individual's needs, cultural
  background, or evolving communication abilities."** ← the personalization gap
- **Educators must manually author custom materials** - time-consuming, requires graphic design
  skill. ← the manual-authoring burden, which is the same burden as hand-writing a
  communication dictionary or a paper cry diary
- stigma, device cost, cultural barriers

**Both risk and support.** Support: a peer-reviewed AAC platform paper independently identifies
personalization-plus-manual-authoring as *the* open problem, which is our thesis. Risk: AMBRA is
prior art for "AI-enhanced personalized AAC platform," so we must not claim that framing as
novel. Our narrower claim survives intact: AMBRA personalizes the *symbols the user expresses
with*; we learn *what the caregiver did and whether it worked*. Expression vs. interpretation - 
still opposite directions.

---

## 4. So is it new, and is it worth doing?

**Not new:** cry classification (saturated, shaky), learning an individual from logs
(Huckleberry), personalized atypical-speech matching (Voiceitt, Euphonia, latent phrase
matching), the concept of a caregiver-authored communication dictionary (established AAC
practice).

**Genuinely new - three defensible claims, in order of strength:**

1. **The unit of learning is the interaction, not the signal.**
   Every competitor models the *signal* (what does this cry sound like?). This models
   *signal → response → outcome*: what did the caregiver do, and did it work? No product
   found in this review stores the intervention and its result. This is the strongest claim
   and it is architectural, not incremental.

2. **Zero enrollment. The label arrives retrospectively, from the person who was there.**
   Voiceitt needs you to train phrases. Cry apps ship a population model. Ours learns from an
   interaction that was going to happen anyway, and the caregiver supplies ground truth
   afterwards - *"what stopped the crying?"* This dodges the impossible problem (inferring
   cause from sound) by never attempting it.

3. **It produces a transferable artifact.** The learned record is, in effect, an
   auto-generated Communication Passport - handed to a night nurse, a relieving parent, the
   next shift. Paper passports exist and are valued; none are generated from real
   interactions. This is the clearest unmet need and the best bridge from babies to
   stroke/dementia.

**Weak claim - do not lead with it:** "one engine, many populations." Judges cannot verify it
in a demo and it invites the question of whether any of the arms is finished.

### Verdict

Worth doing - **but only in the memory framing, never the diagnostic framing.** The literature
actively supports the memory framing (no cure, no guidelines, goal is parental coping,
n-of-1 is appropriate) and actively undermines the diagnostic one (cause is not recoverable
from acoustics). The pivot from "why is your baby crying" to "here is what you did last time"
moves the project from a crowded market built on a contested claim to an unoccupied one built
on a supported claim.

---

## 5. Outstanding research tasks

- [x] **arXiv 2306.05446** (Latent Phrase Matching) - read; see §3c. **Validates our
      match-don't-transcribe rule with a +60% recall figure.** Enrollment-based and closed-set,
      so our no-enrollment differentiator holds.
- [x] **arXiv 2401.08866** (Foundation Models in AAC) - read; see §3d. Names
      personalization + manual authoring as the open problem; AMBRA is prior art for
      "AI-enhanced personalized AAC platform," so don't claim that phrasing as novel.
- [ ] Read the **Pediatric Research** colic/ChatterBaby paper in full.
- [ ] Check whether a validated **cry diary** instrument exists (the Barr Cry Diary was
      searched for but not confirmed; the **ColiQ** questionnaire did surface - 
      [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0929693X2100035X)).
      If a validated diary exists, "we automate a validated instrument" becomes a strong claim.
- [ ] Confirm whether any AAC product auto-generates a communication passport.
