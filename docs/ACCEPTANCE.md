# Acceptance tests - does this do what the IDEA requires?

**Status: NOT ONE OF THESE HAS BEEN RUN.**

Every row on the task board says `DONE`. That is not evidence. Tasks 2.11-2.13 were three real
bugs sitting inside rows already marked `DONE`, two of which disabled the required safety
feature. **`DONE` is a claim; this file is the verification.**

These are **behavioural** tests written against the product intent, not unit tests against the
implementation. A module can pass every unit test and the product can still be a lie. Owner:
**product workstream executes** (it has reliable tooling); **acoustics workstream wrote them and judges the results.**

**No frontend work begins until every 🔴 CRITICAL test below passes.**

---

## The intent being tested

> The ambient listener is on during a real caregiving interaction - the baby crying *and* the
> caregiver talking. When the recording stops, the caregiver is asked what stopped the crying;
> if she says nothing, it is inferred from the conversation. The episode is stored. **The next
> time a similar cry appears, the system surfaces what worked before** - because an exhausted
> parent cannot remember what happened at 3am four nights ago, and for colic there is no
> population-level answer to look up instead.

Each test below maps to one clause of that paragraph.

---

## 🔴 A - CRITICAL: does retrieval actually discriminate?

**This is the test the entire product rests on, and it has never been run.** Everything else is
plumbing. If retrieval returns the same answer regardless of which cry is queried, then the app
is a lookup table with a similarity score painted on it, and the idea does not work.

The corpus experiment showed discrimination exists *in principle* (within-subject AUC 0.70,
`FINDINGS.md` §1). It has **not** been shown to survive the shipped pipeline.

### A1 - different query cries must return different matches 🔴

1. Seed one subject with episodes from corpus infant **X** (`tools/seed_demo.py`).
2. Query `find_similar` with a **held-out cry from infant X** → record top match id.
3. Query with a **cry from a different infant Y** → record top match id.
4. Repeat for at least 5 distinct held-out X cries and 5 Y cries.

- **PASS:** X queries rank X-derived episodes higher than Y queries do, on average, with the
  top-1 differing between the two groups in the majority of trials.
- **FAIL:** the same episode is returned as top-1 for nearly every query.
- ⚠️ **If this fails, stop all feature work and tell acoustics workstream.** It is a thesis failure, not a bug.

### A2 - the band must not be uniformly `strong` 🔴

Run 20 queries (mixed X and Y). Record the distribution of `band`.

- **PASS:** a spread across `strong` / `weak` / `none`. Y-infant queries should skew `none`.
- **FAIL:** everything returns `strong`. That is the "everything matches" failure
  (`FINDINGS.md` §5) reappearing downstream of normalization.

### A3 - normalization is actually applied 🔴

Delete the population baseline row, then query.

- **PASS:** `find_similar` returns `[]` and the UI renders the honest not-enough-data state.
- **FAIL:** it returns matches anyway → raw cosine leaked in, and every score will be ~0.99.

---

## 🔴 B - CRITICAL: does it work on REAL mixed audio?

All validation so far used corpus cries - 7-second clips of a baby alone. **The product records
a mother talking over a crying baby.** That is a different signal and it has never been through
the full pipeline.

### B1 - end-to-end on a real mixed recording 🔴

Record ~30 s: a cry playing from a speaker while someone speaks caregiver lines over it
("Are you hungry? Let me get your bottle."). Run the real `record` → `finish` path.

- **PASS, all four:**
  1. `fingerprint` returns 87 floats (not `None`)
  2. `transcript` contains the spoken caregiver words
  3. `interventions` is non-empty and **every** item's `evidence` appears verbatim in the transcript
  4. the episode saves and appears in `list_episodes`
- **FAIL:** any of the four.

### B2 - the fingerprint survives the caregiver's voice 🔴

Fingerprint the same cry (a) clean and (b) with speech over it. Normalize both, cosine them.

- **PASS:** clearly above the impostor distribution - the measured reference is **+0.474 vs an
  impostor mean of +0.002** (`FINDINGS.md` §3).
- **FAIL:** near the impostor mean → speech is destroying the signature in the shipped code even
  though it did not in the experiment.

### B3 - nobody re-introduced source separation 🔴

`grep -rn "separate\|diariz\|split" src/`

- **PASS:** no separation in the live path. `FINDINGS.md` §3 measured it destroying both channels.

---

## 🔴 C - CRITICAL: is the outcome recorded truthfully?

This is where the three bugs lived. Re-verify by behaviour, not by reading the diff.

### C1 - "nothing worked" must not be stored as success 🔴

`finish(..., caregiver_answer="nothing worked, he cried himself out")`

- **PASS:** `worked` is `False` or `None` - **not** `True`.
- **FAIL:** `worked is True`. Bug 2.11 is back.

### C2 - a genuine success is stored as success

`finish(..., caregiver_answer="feeding him worked")` → `worked is True`.

### C3 - skipping the question does not invent an outcome 🔴

`finish(..., caregiver_answer=None)` on audio whose transcript does not state an outcome.

- **PASS:** `outcome is None` and `outcome_src is None`, **or** `outcome_src == "inferred"` with
  an `outcome` that appears **verbatim** in the transcript.
- **FAIL:** an `outcome` that is nowhere in the transcript. That is a fabrication reaching the
  caregiver.

### C4 - the tally cannot be inflated 🔴

Seed 5 episodes where the caregiver said nothing worked. Run `intervention_tally`.

- **PASS:** `worked` counts are 0.
- **FAIL:** non-zero → false positives are entering our headline T2 claim.

---

## 🔴 D - CRITICAL: does the safety feature fire?

`LIABILITY.md` §5. Colic is a documented risk factor for child abuse; this is the one feature
where a false negative has a real-world cost.

### D1 - fires on repeated unresolved episodes 🔴

Three consecutive episodes with `worked=None` (the realistic exhausted-parent path).
**PASS:** `caregiver_guidance` returns the message. **FAIL:** returns `""` → bug 2.12 is back.

### D2 - fires with `worked=False` too 🔴
### D3 - does NOT fire forever after one long episode 🔴

One 10-minute episode, then three short resolved ones.
**PASS:** the message is absent on the recent ones. **FAIL:** still firing → bug 2.13 is back.

### D4 - does not fire on a calm history
Three resolved short episodes → returns `""`. No crying-wolf.

---

## 🟠 E - honest degradation

- **E1** - 0 episodes: no crash, renders the empty state.
- **E2** - 1 and 2 episodes: renders "only your Nth recording", **no match shown**.
- **E3** - exactly 3 priors: matches begin, bands sane.
- **E4** - no similarity number or percentage appears in ANY human-facing output.
  Check: `grep -rn "similarity" src/render.py src/cli.py` → must not reach output.
- **E5** - `outcome_src` is visible on every rendered outcome, and `"seed"` renders as
  visibly synthetic.

## 🟠 F - liability surface

- **F1** - no output anywhere names a *cause* the caregiver did not type. Read 20 rendered
  cards. No "hungry"/"colic"/"in pain" unless quoted from her.
- **F2** - the words "colic", "diagnose", "treat" do not appear in user-facing strings as claims.
  `grep -rni "colic\|diagnos\|treat" src/*.py` - every hit must be a comment or a doc.
- **F3** - consent gate appears before the first recording.
- **F4** - no video capture anywhere. `grep -rn "video\|avfoundation" src/` - audio device only.
- **F5** - `delete_episode` removes the row, the audio file, and refreshes the baseline; corpus
  files are never deleted.

## 🟡 G - robustness (should not crash)

Missing file · empty wav · 0.1 s wav · silence-only wav · no network (unplug wifi, `finish`
should still fingerprint and save with an empty transcript) · corrupt db row · unicode in the
caregiver answer.

**PASS:** degraded result, no traceback. Nothing may raise (`CONTRACTS.md` rule 6).

---

## How to report

Append to `MESSAGES.md`, or a new `docs/ACCEPTANCE-RESULTS-01.md` if MESSAGES is contended:

```
| test | PASS/FAIL | evidence (actual values, not "looks right") |
```

**Paste real numbers.** "A1 PASS" is not a result; "A1 PASS - X queries top-1 = ep 7,7,4,7,9;
Y queries top-1 = ep 2,11,2,2,11" is a result.

Report **every** 🔴 CRITICAL, even the passes. Any 🔴 failure stops feature work.

---

## The honest position right now

We have proven, with real measurements:
- a baby's cry episodes are acoustically discriminable in a **corpus experiment** (AUC 0.70)
- source separation is harmful, and generative models confabulate non-speech events
- normalization is mandatory

We have **not** proven:
- that discrimination survives **the shipped pipeline** (test A)
- that any of it works on **real caregiver-plus-infant audio** (test B)
- that outcomes are recorded **truthfully** after the bug fixes (test C)
- that the **safety feature fires** (test D)

Until A-D pass, the correct description of this project is *"a validated approach with an
unverified implementation."* Not "it works."
