# Demo script and pitch narrative

Task 3.5. This is what to **say**. For what to **do** with the laptop and the phone, use
[`DEMO-READY.md`](DEMO-READY.md), which is the operator runbook.

Rule for this document: **every number in it is a real measured output**, and every one carries
the caveat that has to travel with it. Nothing here is rounded up, nothing is a projection, and
nothing describes a capability that is switched off in the build being shown.

---

## 1. The claim, in one sentence

> It is not a cry translator. It is a memory prosthetic: it records a real caregiving
> interaction, asks the caregiver afterwards what actually worked, and recalls that answer the
> next time a similar signal appears.

The unit of learning is **the interaction**: signal, then response, then outcome. Every existing
product models the cry. This models what the caregiver did and whether it helped.

Say this second, immediately, before anyone can assume otherwise:

> We never tell you why your baby is crying. We tell you what you did last time, and whether it
> worked.

## 2. What we deliberately do not claim

Leading with the limits is not modesty, it is the strongest position available, because every
obvious objection has already been answered before it is raised.

- **No cause, ever.** No "hungry", no "tired", no "colic detected". The system reports what a
  caregiver said she did. Cause claims are why cry-analyser apps get taken apart.
- **No diagnosis and no treatment.** This is a general wellness tool. A tool that claimed to
  diagnose colic would be a regulated medical device we could not defend.
- **No population comparison.** It never says "your baby cries more than normal", because that
  is a disease-adjacent claim.
- **Audio only. Never video.** One recording, and the caregiver's voice is never separated from
  the baby's.
- **Local only.** The matching path has no network and no AI model in it at all.

The honest framing and the safe framing are the same framing, and that is worth saying out loud:
colic has no established cause, no cure and no evidence-based soothing guidelines, and the stated
goal of clinical management is to help the parents cope.

## 3. Why this is new

There are three crowded neighbourhoods and one empty space.

| Neighbour | What they do | Why we are not them |
|---|---|---|
| Cry analysers | classify a cry into a cause | we never name a cause |
| AAC apps | help a person **express** | we help a caregiver **interpret** |
| Baby trackers | store what you type | we recognise the signal and retrieve against it |

The empty space: a **Communication Passport** and a caregiver-authored **gesture dictionary** are
established instruments in AAC practice for exactly this problem. Both are hand-written, static
paper documents. Nobody generates one automatically from recorded interactions. A cry diary is
the same story: a manual paper instrument in colic assessment, filled in by hand by an exhausted
parent for days.

That is the claim. Not "AI for babies". **Automatic generation of an instrument that clinical
practice already asks people to keep by hand.**

## 4. Run of show

Roughly six minutes. The order is deliberate: prove identity works before promising memory, and
put the audience in it before the numbers.

### Beat 1: the problem, 30 seconds

No slides. One question to the room:

> Who here has looked after a baby that would not stop crying at 3am? Four nights later, could
> you tell me what worked the first time?

Then: an exhausted parent cannot remember, and for colic there is no population answer to look up
instead. That is the gap.

### Beat 2: it knows who this is, 90 seconds

Open **Baby cry**, run a blind query against enrolled profiles from a file.

Show the verdict card. Read it exactly as written. The card says one of `Matched`,
`Leaning toward`, `Uncertain`, or `Unresolved`, and those words mean different things.

What to say while it computes:

> There is no neural network in this path. It is a mel-frequency fingerprint and a dot product,
> about two hundred lines of numpy, and it runs entirely on this laptop with the network off.

If it matches, say the honest version of the result:

> On our live two-infant rig, leave-one-out across every usable trial: thirteen right, two asked
> for another recording, and zero wrong. Asking again is not a failure. It is the system
> declining to guess.

### Beat 3: the memory, 90 seconds. This is the actual product.

With a confirmed match on screen, press **Show this profile's recorded history**.

The guidance block is written by the local server from that profile's own recorded incidents.
Point at the provenance badges, because they are the whole ethic of the thing:

- `caregiver reported` means she said it.
- `inferred from silence` means we inferred it and labelled it as weaker.
- `seeded example / synthetic` means it is demo data and describes nobody.

> Everything on this card came from her own history. The system has no opinion about why the baby
> was crying. It only remembers what she did and whether it stopped.

Then save one outcome, and note that it takes six episodes before a recall renders, measured
rather than guessed.

### Beat 4: the audience is in it, 2 minutes

This is the beat people remember, and it is the reason the human-imitation mode exists.

Switch to **Human cry imitation** and press **Create new session**. Pass the phone around. Ask
three or four people to imitate a cry, one at a time.

- The first valid cry becomes **Person A**.
- A clearly different voice shows **Possible new participant** and asks that same person for one
  more cry before it will create a profile.
- Later cries either match someone already enrolled, register as a clearly distinct new person,
  or stay uncertain.

Then hand the phone to someone who has already gone, without telling the room who it is, and let
the screen name them.

Say this before starting, so nobody thinks it is rigged:

> It does not know any of your voices. Nobody here is pre-registered. The session starts empty
> and builds itself from whoever speaks into it.

And say this if it abstains, which is a genuinely likely outcome:

> That is the two-gate design working. It has to clear an absolute bar and beat the runner-up by
> a margin. If it cannot do both, it refuses to name anyone rather than name the wrong person.

### Beat 5: what we proved does not work, 45 seconds

This is the credibility beat. Do not skip it.

> The obvious design is to separate the caregiver's voice from the baby's. We built it. The cry
> match fell to plus zero point zero three one, no better than a stranger's cry, and the
> transcript lost half its sentence. Infant and adult pitch ranges genuinely overlap.
>
> We also tried letting a generative audio model do the listening. Given a three and a half
> second tone that was louder than the speech in the same file, it missed the tone completely and
> invented three events that were not there, with confident timestamps. It is now banned from the
> signal path.

### Beat 6: the honest ceiling, 30 seconds

> Everything so far is two subjects on one rig, so we ran an independent check at scale: forty-six
> identities, two hundred and five held-out trials, five-fold cross-validation grouped by
> identity, thresholds chosen on training identities only.
>
> In the demo condition, two enrolled profiles, rank-one is 87.8 percent against 50 percent
> chance. On the untouched outer fold it named someone 48 times, was right 46 and wrong twice,
> and abstained 157 times. Precision when it names someone is 95.8 percent, and the Wilson
> 95-percent upper bound on the wrong-name rate is 14 percent.
>
> That last number is the one that keeps the rest honest. With only 48 named decisions, even zero
> observed errors would still admit a true rate near 7 percent.

Then close:

> This is a proof that the idea works, measured honestly, not a product claim.

## 5. Numbers you may quote, with the caveat each one requires

Never quote the left column without the right column.

| Number | The caveat that must be said with it |
|---|---|
| 13/15 correct, 2 retries, **0 wrong** | Two infants, one rig, leave-one-out. Not a population result. |
| AUC **0.806** separating same-baby from different-baby | 421 episodes, 207 infants, episode level. |
| same baby **+0.309** vs different babies **-0.003** | Cosine after population normalization, not a probability. |
| top-1 retrieval **30.5%** vs **0.7%** chance | About 43 times chance. Retrieval, not identification. |
| live: own history **0.924** vs strangers **0.776**, 8/8 strangers rejected | One rig, eight strangers. |
| caregiver speech overlaid: **0.914** vs **0.933** clean | This is why we never separate the voices. |
| pink background noise **0.899** | Survives. Useful for a loud venue. |
| **6 episodes** before a recall renders | Measured, not chosen. |
| pool of 2: **87.8%** rank-1 vs 50% chance | Corpus scale, grouped 5-fold CV, held out. |
| pool of 46: **36.1%** vs 2.2% chance | Same run. Degrades with pool size, as it must. |
| precision when naming **95.8%** (46 right, 2 wrong, 157 abstained) | 48 named decisions only. |
| Wilson upper bound **14.0%** on wrong names | Say this one unprompted. It is the ceiling. |
| distance to ~1 m (-6.7 dB): **0.915**, survives | Level drift is **not** monotonic. |
| playback at 50% (-3.9 dB): **0.897**, breaks | A smaller level drop broke it than one that survived. |
| different device: **-0.258** | Same-device only. Stated as a limitation, not hidden. |

Two numbers were **withdrawn** and must never be quoted again, because someone will have read an
earlier version of the docs:

- "Zero wrong across 46 identities." That came from thresholds searched on the same trials used to
  report it. Test-set tuning. Replaced by the grouped-CV result above.
- An AS-norm false-accept improvement. It was a dilution artifact of a cross-channel corpus in
  which raw scoring already rejects strangers, and it was retracted in full.

Saying "we withdrew this claim and here is why" is worth more than any number in the table.

## 6. The questions a judge will ask

**"Is this just a cry classifier?"**
No. A classifier maps a cry to a label. We never produce a label. We identify **who** is crying
and retrieve **what the caregiver did** last time a similar signal appeared.

**"So does it work on any baby?"**
Not yet, and we will not say otherwise. Enrollment and query must be on the same device and the
same recording path. Across devices the score falls to -0.258. That is the top limitation.

**"What if it names the wrong person?"**
It can. Precision when naming is 95.8 percent over 48 named decisions, upper bound 14 percent
wrong. That is why there are two gates and why abstaining is a first-class outcome rather than an
error state. A single profile cannot be identified at all: with nothing to compare against, the
system refuses.

**"Where does the AI happen?"**
Not in the matching path, deliberately. Speech transcription is a hosted call, and every action
it extracts has to quote the transcript or it is dropped. The identity decision is deterministic
signal processing, so it cannot hallucinate and it produces identical output for identical input.

**"Is this recording my voice right now?"**
Nothing is captured until someone presses Start recording, everyone audible is told and agrees
first, audio never leaves the laptop, and there is no video. The consent text is on screen the
whole time.

**"Why should I believe your numbers?"**
Because we will show you the ones that failed. Four documented dead ends are in the docs with the
measurements that killed them, and two published claims were withdrawn.

## 7. If something goes wrong live

Change the capture setup or the input method. **Never change the identity policy mid-demo.**

| What happens | What to say |
|---|---|
| Uncertain or Unresolved | "That is the design. It abstains rather than guess." Then use the one offered retry with a genuinely new recording. |
| It names the wrong person | "There it is, and this is why we quote a 14 percent upper bound rather than a zero." Do not re-run to get a better answer. |
| Room too loud | Move the phone closer, ask for five quiet seconds. Do not lower the gates. |
| Microphone permission fails | Switch to the saved-file path, which is the more reliable one anyway. |
| Nothing loads on the phone | Fall back to `tools/human_session_eval.py` on the laptop, and say that it is the same code path without the live capture. |

Two hard rules from measurements, not preferences:

1. **Never play audio through the device that is recording.** iOS suppresses its own speaker
   feed, measured at -53.7 dB with no usable fingerprint.
2. **Never change the playback volume between enrolling and querying**, because that is the
   perturbation that actually broke.

## 8. Track positioning

**T1, health data collection from non-obvious signals.** The signal is a cry, which is normally
treated as noise to be stopped. We extract identity from it locally, with no model in the path,
and pair it with a caregiver-reported outcome at the moment it happens. That pairing of a passive
sensor with an active in-the-moment report is what digital phenotyping calls ecological momentary
assessment, and our architecture is exactly that shape.

**T2, health over time.** One episode is worthless and we say so. The value is the accumulating
record: the tally of what was tried, what settled it, and what was tried last before it stopped.
That is the automatically generated cry diary and the automatically generated Communication
Passport, both of which exist today as hand-written paper instruments.

Both tracks, one architecture, and no capability claimed that is not in the build.

## 9. Sentences that must never be said

Straight bans. Each one either overclaims or converts a wellness tool into a medical device.

- "It knows why your baby is crying."
- "The baby is hungry / tired / in pain."
- "It detects colic." Or diagnoses, or treats, or cures anything.
- "It works on any baby / any phone / any voice." It does not work across devices.
- "It is 100 percent accurate." Or "it never gets it wrong."
- "Your baby cries more than normal."
- "It knows your voice." The session starts empty and nobody is pre-registered.
- Reading a `Leaning toward` result as a confirmed identity.
