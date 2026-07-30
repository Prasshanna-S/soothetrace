# Liability & guardrails

*What we are allowed to build, say, and demo in a common, public, testable setting.
These are constraints on the product, not paperwork. §1 and §2 change what goes in the UI.*

---

## 1. ⚠️ FDA: "solving colic" is a claim we cannot make

The FDA does not regulate **low-risk general wellness products** as medical devices, provided
two conditions hold:

1. the intended use is **maintaining or promoting general health or healthy behaviours**, and
2. the product is **low risk** (non-invasive, non-implanted).

But - and this is the part that binds us - a general wellness product **"does not include
claims, functionality, or outputs that guide clinical management,"** and **"statements linking a
product to treatment, diagnosis, or mitigation of a disease may move the product outside the
wellness category."**

**Colic is a recognised medical condition.** So:

| ❌ Moves us OUT of general wellness | ✅ Stays inside |
|---|---|
| "helps solve colic" | "helps you keep track of what you've tried" |
| "identifies why your baby is crying" | "finds the most similar episode in your own log" |
| "recommends the treatment that will work" | "shows what you did last time" |
| any output that guides clinical management | a record of the caregiver's own history |

The FDA does explicitly permit one thing we want: general wellness products **may prompt the
user to consult a health care professional** when something looks unusual, *so long as they
make no disease-specific, diagnostic, or treatment-oriented statement.* So a
"consider talking to your pediatrician" prompt is allowed. "This looks like colic" is not.

Sources: [FDA General Wellness guidance summary](https://www.regdesk.co/blog/fda-guidance-summary-general-wellness-policy-for-low-risk-devices/) ·
[2026 updated guidance analysis (Troutman)](https://www.troutman.com/insights/fdas-2026-guidance-on-general-wellness-devices-policy-for-low-risk-devices/) ·
[updated General Wellness + CDS guidance (ArentFox)](https://www.afslaw.com/perspectives/alerts/fda-issues-updated-guidance-low-risk-general-wellness-devices-and-clinical) ·
[Exponent analysis](https://www.exponent.com/article/fda-clarifies-oversight-wearables-and-cds-software)

> **This is why the memory framing is not a retreat.** "Here is your own history" is a wellness
> product. "Here is what's wrong with your baby" is a regulated device we cannot ship, cannot
> validate, and cannot defend. The safe framing and the honest framing are the same framing.

**Enforced in code:** no output may contain a cause label the caregiver did not type herself.
The system quotes her back to her. See `CONTRACTS.md` rules 3-5.

## 2. ⚠️ Recording consent - audio only, never video

Relevant because the product records in a home, and because the hackathon demo records people.

**Georgia (Emory's jurisdiction) is one-party consent for audio** - you may record a
conversation you are a party to. **But Georgia is all-party consent for video in private
places.** The Georgia Supreme Court has held the all-party requirement applies to *images*
while one-party applies to *sound*. **Violations are a felony: 1-5 years and up to $10,000.**

Consequences, all of which we adopt:

1. **Audio only. Never add video.** It changes the legal posture from one-party to all-party in
   exactly the setting (a private home) where the product lives. `FINDINGS.md` already concluded
   vision adds engineering cost for little gain; the law settles it.
2. **If anyone other than the caregiver and infant is audible, get their consent.** A visiting
   nurse, a partner, a grandparent. Recording laws are about *conversations*, and an infant is
   not a party.
3. **Multi-state is a trap.** *"If you intend to record conversations involving people located
   in more than one state, you should play it safe and get the consent of all parties."* Any
   telehealth or two-location feature must be all-party consent. Park it under "coming soon."
4. **For the demo: get explicit recorded verbal consent from every person whose voice is
   captured**, even though Georgia would not require it. It costs eight seconds and it is the
   right posture in a room of colleagues.

Sources: [Georgia recording laws](https://www.recordinglaw.com/united-states-recording-laws/one-party-consent-states/georgia-recording-laws/) ·
[Digital Media Law Project - Georgia](https://www.dmlp.org/legal-guide/georgia-recording-law) ·
[Reporters Committee - Georgia](https://www.rcfp.org/reporters-recording-guide/georgia/)

## 3. IRB - the line we must not cross at a hackathon

**You cannot self-declare exemption.** *"Investigators do not make their own determination as to
whether a research study qualifies for an exemption - the IRB issues exemption
determinations."* ([NIH OHSRP](https://irbo.nih.gov/irb-review/exempt-review/),
[Johns Hopkins](https://www.hopkinsmedicine.org/institutional-review-board/guidelines-policies/guidelines/exempt-research))

So the line for the hackathon:

| ✅ Not human-subjects research - safe to do now | ❌ Requires Emory IRB approval first |
|---|---|
| Public corpus data (donateacry, HomeBank) | Recruiting real parents to use the app |
| The team's own voices, consenting, in-room | Collecting infant/parent audio from outside the team |
| Synthetic / generated audio | Any generalisable-knowledge claim from collected data |
| A demo that collects nothing persistent | Retaining identifiable recordings from participants |

**Practical rule: the hackathon build must be demonstrable using only the public corpus and the
team's own voices.** That is enough for a complete demo, and it keeps us entirely outside human
subjects regulation. The moment real parents are recruited, this goes to the Emory IRB - note
that exemption categories 2 and 3 plausibly apply (benign behavioural intervention with
prospective agreement, including audiovisual recording), but *the IRB decides, not us.*

Say on stage: *"the next step is an IRB protocol"* - that reads as competence, not caution.

## 4. Children's data

The subject is an infant. Even outside HIPAA (which binds covered entities, not a
direct-to-consumer app), infant audio is about as sensitive as consumer data gets, and COPPA
applies to services directed at children.

Rules for the MVP:

- **Local-first. The database and audio stay on device.** The acoustic path is already fully
  offline by design (`CONTRACTS.md` rule 7) - this makes it a privacy property, not an accident.
- **Only the audio needed for transcription leaves the device**, and only when `OFFLINE=False`.
  Offer the local `whisper` path as the private mode.
- **No accounts, no analytics, no telemetry in the MVP.** Nothing to breach.
- **Deletion must actually delete** - audio file plus row plus recomputed baseline.

## 5. 🔴 Required safety feature - not optional

From the colic literature (`RESEARCH.md` §2): excessive infant crying is associated with
caregiver frustration and sleep deprivation, and **colic is a documented risk factor for child
abuse.** Our user is, by definition, an exhausted person holding an inconsolable infant.

**Therefore the product must include, and the demo must show:**

- When an episode runs long or several fail in a row, surface the caregiver-directed message:
  **it is safe to put the baby down in a safe place and step away for a few minutes.** This is
  standard, non-diagnostic, universally endorsed guidance.
- Never imply the caregiver failed. Intervention history is shown as a record, never a score.
- The "consult a professional" prompt the FDA explicitly permits (§1).

This is genuinely the right thing to build. It is also the single feature that most clearly
signals we understood the population - and it costs an afternoon.

## 6. Cloud & credits

200 AWS + 200 Azure credits available. **Recommendation: spend almost none of it.**

- The acoustic path is local numpy - no cloud needed, and keeping it local is a privacy feature.
- Speech is OpenAI, already keyed.
- **Do not spread an MVP across three providers.** The rubric rewards a small finished thing;
  cloud plumbing is invisible to judges and is a classic scope trap.
- If a hosted demo is wanted: one small AWS instance for the API, nothing else. Azure's Speech
  service (which does diarization) is worth keeping in reserve **only** as a fallback if OpenAI
  transcription disappoints on the stroke arm - note it as an option, don't build it.

## 7. "Coming soon" - honest disabled surfaces

Showing the platform without overclaiming. These must be visibly disabled and labelled, never
faked with mock data presented as real:

- Stroke / aphasia mode - **zero empirical validation** (`FINDINGS.md` §6)
- Dementia and ICU modes
- Communication Passport export
- Clinician / pediatrician summary report
- Multi-caregiver shared record (⚠️ triggers §2.3 multi-state consent)
- Cross-subject population insights (⚠️ requires IRB, §3)

Rule: a disabled surface may describe what it *would* do. It may never display fabricated
output as though it were computed. A judge who taps a "coming soon" tile and finds invented
data has found the one thing that discredits everything else in the demo.

---

## The single-paragraph liability summary

We build an audio-only, local-first, general-wellness memory tool that records a caregiver's own
interactions with consent, reflects her own history back to her, never names a cause she did not
name, never claims to treat or diagnose colic, prompts professional consultation without
diagnosing, includes a caregiver-safety message, collects data only from the team and public
corpora until an IRB protocol exists, and never records video. Every one of those clauses maps
to a citation above.
