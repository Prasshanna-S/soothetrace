# Review 01 - acoustics workstream reviewing product workstream's `session.py` + `render.py`

**Date:** 2026-07-29 · **Reviewer:** acoustics workstream (read-only; no files edited)
**Verdict:** three semantic bugs. Combined effect: **the required caregiver-safety message
(`LIABILITY.md` §5) will almost never fire, and negative outcomes are stored as successes.**

Filed as a separate file rather than appended to `MESSAGES.md` because we were both writing
that file concurrently. Tracked on the board as tasks **2.11-2.13**.

Context first, because it matters: this code is disciplined and well-defended. Broad
`try/except` with logging, input validation on every entry point, safe filename sanitisation,
`os.path.isfile` guards, empty-case returns rather than raises. Nothing below is a style
complaint. All three are *semantic* - the code does exactly what it says, and what it says is
wrong.

---

## 🔴 BUG 1 - `session.finish`: any answer at all is recorded as success

```python
if answer:
    outcome = answer
    outcome_src = "caregiver"
    worked = True          # <-- unconditional
```

A caregiver answering **"nothing worked, he cried himself out"** is stored as `worked=True`.
That is the most important case in colic - the episode that did **not** resolve - and we invert
it. `tools/seed_demo.py` contains that exact sentence as script #5, so the bug is reachable with
data already in the repo.

**Knock-on damage, worse than the bug itself:**

1. `retrieve.intervention_tally()` credits **every** intervention in that episode as having
   worked. The T2 longitudinal payload - our headline claim - silently fills with false
   positives. A parent would be told that walking the baby works, because they told us it
   didn't.
2. `render.caregiver_guidance`'s `repeated_unsettled` check can then never observe a failure,
   which is BUG 2.

**Fix:** never infer valence from the *presence* of an answer. Either ask an explicit
"did it settle? y/n" as a separate prompt, or set `worked=None` when valence is unknown.
`None` is honest; `True` is a fabrication. `store.py` and `diary.py` both already handle `None`
correctly - `diary.daily_summary` counts it as neither resolved nor unresolved.

## 🔴 BUG 2 - `render.caregiver_guidance`: `worked is False` never matches reality

```python
repeated_unsettled = len(clean) >= 3 and all(e.get("worked") is False for e in clean[:3])
```

`session.finish` yields `worked=None` whenever the caregiver skips the question *and* inference
fails - **the most likely real path for an exhausted parent at 3am.** On that path it never
yields `False` at all. The strict `is False` test therefore fails, and the safety message does
not appear for precisely the person it was written for.

**Fix:** treat "did not settle" as `worked is not True` - `False` **or** `None`.
Under-firing a safety message is the expensive direction of this error, and this is the one
feature in the product where a false negative has a real-world cost (`RESEARCH.md` §2: colic is
a documented risk factor for child abuse).

## 🟠 BUG 3 - `render.caregiver_guidance`: `long_episode` scans all history forever

```python
long_episode = any(... e["duration_s"] >= 600 for e in clean)
```

`clean` is the whole episode list. One 10-minute episode *ever* recorded makes this `True` on
**every subsequent render, for the life of the record.** The message then appears constantly,
becomes wallpaper, and gets ignored - which is how a safety feature dies without anyone noticing
it stopped working. Alert fatigue is a failure mode, not an inconvenience.

**Fix:** scope to the current episode or the most recent few - `clean[:1]` or `clean[:3]`.

---

## Not bugs - flagged only

- `_display_time` uses `%-d` / `%-I`, which are BSD/glibc extensions. Fine on macOS; would
  raise on Windows. Irrelevant unless we ship elsewhere.
- `session.finish` always passes `subject_age_days=None`, so that context field is never
  populated. Low priority - `hour_local` is the feature with literature behind it
  (`RESEARCH.md` §1).
- `_capture_wav` is macOS-only (`-f avfoundation`) with an `IM_AUDIO_DEVICE` override. Correct
  choice for this machine; just note it in the README if anyone else ever runs it.

## What was right, and should not be changed

- `extract_interventions` verifies every `evidence` span with `transcript.find()` and drops
  anything not literally present. **Asking a model to be truthful is a hope; checking it is a
  guarantee.** This is stronger than `CONTRACTS.md` required.
- It re-derives intervention `order` from evidence *position* rather than trusting the model's
  `order` field - the model's ordering is unverifiable, the position isn't.
- `infer_outcome` requires the evidence span to be present **and** `worked` to be a real bool,
  returning `None` otherwise. Correctly conservative.
- `recall_card` filters to `strong`/`weak` bands and never prints a similarity number. Exactly
  per contract.
- Returning the verbatim span as `outcome` rather than a paraphrase - a quote cannot be a
  fabrication. Now documented in `CONTRACTS.md` as intended.
