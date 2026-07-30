# Specification audit - 2026-07-29

**Auditor:** product workstream  
**Scope:** every repository document that makes a product, architecture, interface, acceptance,
demo, safety, or execution claim.  
**Purpose:** establish what is authoritative now, what is historical evidence, what conflicts,
and what must be corrected before implementation proceeds.

This is a consistency and implementation audit, not legal or medical advice. Legal claims below
are checked against current primary or near-primary sources, but counsel and Emory's IRB remain
the decision-makers for deployment or human-subjects research.

## Executive verdict

The repository contains a working and tested **legacy CLI episode-memory prototype**, plus a
well-specified but mostly unimplemented **identity-first mobile demo**. The documents frequently
describe those two states as though they were one. That is the main integrity problem.

The latest identity/context design is the correct product-direction document, subject to the
written review decisions acknowledged in `MESSAGES.md`. It is not yet an implementation
description. `CONTRACTS.md`, `ARCHITECTURE.md`, `WEBAPP.md`, `DEMO-READY.md`, `TASKS.md`, and the
README contain material conflicts with it and with the measured evidence.

The current codebase is healthier than several documents say:

- the CLI episode loop exists;
- 53 unit tests pass through `.venv/bin/python -m unittest discover -s tests`;
- live same-channel discrimination passed H2;
- the useful-history threshold is measured at six priors;
- `worked_last` is implemented and rendered;
- `session.finish()` already accepts a browser-upload-compatible audio path.

The current codebase is also much less complete than the newest design requires:

- no mobile client or HTTP API exists;
- no profile/enrollment/identity/session-event/guidance storage exists;
- no closed-set Baby A/B identity result has been measured;
- no adult-imitation identity result has been measured;
- no continuous iPhone capture has been proven;
- contextual scenario weighting and note-based guidance are not implemented.

## Authority map

### Authority as the repository stands

| order | document | authority | audit result |
|---:|---|---|---|
| 1 | `AGENTS.md` | collaboration process and ownership | Current, but its product framing and repo map predate the mobile identity wrapper. |
| 2 | `CONTRACTS.md` | frozen cross-agent interfaces | Normative but stale and internally inconsistent with current code. Must become v3 before new cross-agent implementation. |
| 3 | `docs/superpowers/specs/2026-07-29-identity-context-demo-design.md` | target product and future architecture | Best product source, reviewed by acoustics workstream; accepted corrections are still only in `MESSAGES.md`. |
| 4 | `LIABILITY.md` | safety and claim boundaries | Binding guardrail, but needs a mobile/continuous/visitor-retention addendum and primary-source cleanup. |
| 5 | `ACCEPTANCE-RESULTS-01.md`, `ACCEPTANCE-RESULTS-02.md`, `FINDINGS.md` | measured evidence | Historical evidence. Results must not be rewritten to match a newer narrative. Add corrections/addenda only. |
| 6 | `WEBAPP.md` | mobile transport constraints | Useful partial design, but superseded where it conflicts with the identity/context design and corrected J evidence. |
| 7 | `ARCHITECTURE.md` | legacy verified pipeline | Accurate for the old CLI pipeline only; not the current full architecture. |
| 8 | `ACCEPTANCE.md`, `ACCEPTANCE-02.md`, `DEMO-READY.md` | historical protocols/checklists | Preserve as historical. None is the final phone-demo acceptance plan. |
| 9 | `TASKS.md` | execution board | Operationally authoritative, but currently stale enough to misroute work. |
| 10 | `POSITIONING.md`, `RESEARCH.md`, README | narrative, evidence synthesis, onboarding | Not implementation authority. Several statements are stale or too causal. |
| 11 | `MESSAGES.md` | append-only decision log | Discovery mechanism only. It must never be the only source of a lasting contract or product rule. |

### Intended canonical set

Before visual implementation, reduce the normative surface to:

1. the revised identity/context product design;
2. `CONTRACTS.md` v3 for actual shared types and calls;
3. a new `ACCEPTANCE-03.md` for phone capture, identity, guidance, privacy, and repeated demo runs;
4. a revised mobile demo-day checklist;
5. `LIABILITY.md` with continuous-capture and ephemeral-visitor rules;
6. immutable evidence/results documents with dated addenda.

All older protocols should receive a clear `HISTORICAL` or `SUPERSEDED` banner, not silent edits
that erase what was actually tested.

## Critical conflicts

### P0 - must resolve before implementing the cross-agent wrapper

#### 1. The frozen contract disagrees with the code

`CONTRACTS.md` v2 says:

- `MIN_EPISODES_FOR_MATCH = 3`;
- `outcome_src` is only `caregiver | inferred | None`;
- `find_similar()` has a shorter signature;
- `compute()` is the only documented fingerprint entry point.

The current code uses:

- `MIN_EPISODES_FOR_MATCH = 6`;
- `outcome_src="seed"` in seed data and human-facing provenance handling;
- `find_similar(..., exclude_episode_id=None, db_path=None)`;
- `compute_windowed()`, `duration_s()`, and `build_context()` in the real session path;
- `intervention_tally()` with a `worked_last` field.

The schema comment also omits `seed`, even though the data and UI support it.

**Decision:** do not "fix" v2 piecemeal. Propose and ACK v3 with the existing real signatures
plus the new Profile, Enrollment, IdentityResult, Session, Event, ManagedCapture,
ScenarioResult, and GuidanceDecision shapes.

#### 2. The final capture direction conflicts across documents

The final presentation path is:

> MacBook plays infant audio → iPhone browser records → local Mac Python backend computes.

Conflicting legacy instructions still say:

- MacBook records through AVFoundation `:1`;
- the cry is loaded on the phone;
- `IM_AUDIO_DEVICE=:1` is a final demo prerequisite;
- seed and query on the old Mac microphone rig.

These occur in `DEMO-READY.md`, `ACCEPTANCE-02.md`, `ARCHITECTURE.md`, parts of `TASKS.md`, and
the README.

**Decision:** retain the Mac mic rig as a reference/regression rig only. It cannot seed or query
the final phone-browser identity roster.

#### 3. Final phone acceptance has a circular dependency

`TASKS.md` says frontend work is blocked until K passes, but final K now requires phone-browser
capture. A phone capture/upload slice must exist before K can be executed.

**Decision:** split "frontend" into:

- an unstyled capture spike required for acceptance; and
- visual design/polish gated by acceptance.

HTTPS, mic permission, applied settings, MediaRecorder chunking, upload, ffmpeg decode, and one
saved capture belong in the spike, not the visual layer.

#### 4. Identity is a target claim, not a verified capability

Measured evidence currently supports:

- same-infant/different-infant separation above chance in a broad corpus;
- live same-channel X-vs-Y discrimination for one stored subject;
- a 30.5% top-1 result in a 207-infant corpus benchmark.

It does **not** yet support:

- reliable two-profile Baby A/B closed-set identification through the phone channel;
- calibrated unknown rejection;
- repeated recognition of one visitor's performed cry;
- discrimination between different visitors' imitations.

The latest design correctly gates these claims, but the phrase "identity verified" elsewhere
would be false.

**Decision:** the two-profile phone-channel leave-one-recording-out result is the first acoustic
gate. If closed-set performance is not reliably near-perfect for the stage roster across three
clean runs, the honest fallback is verification-only, never a forced Baby A/B label.

#### 5. "What it could mean" must not become a system-authored cause

The new design safely requires repeated caregiver notes/tags, but its examples still include
system labels such as `Possible feeding-time pattern` and `Possible pattern: overtired`.
`LIABILITY.md` forbids the system from creating a cause/state label the caregiver did not supply.

**Decision:** render counts, time relationships, and the caregiver's own words:

> Similar cries happened near this time on 3 evenings. Two of your notes mentioned "feeding."

Do not render:

> Possible feeding-time pattern.  
> Possible pattern: overtired.

Likewise, "Try X" must mean "X was the last caregiver-reported action in N relevant resolved
episodes," not "the system predicts X will work."

#### 6. Visitor retention conflicts with the stated IRB-safe demo

`LIABILITY.md` says the safe demo collects nothing persistent and uses team/public data. The
new visitor-enrollment flow stores named profiles, audio, embeddings, and query audit records.

**Decision:** live visitor participation must be:

- preceded by explicit consent and a visible recording state;
- described as an interactive demonstration, not research;
- stored under an ephemeral display label, not an unnecessary legal name;
- deleted at the end of the demo session, including audio, embeddings, episodes, and query links;
- excluded from accuracy claims, training, publication, or retention.

If data is retained or used to produce generalizable findings, consult Emory's IRB before
collection. NIH's current guidance similarly requires proposed human-subjects research to be
submitted for IRB review or consideration of exemption before it starts.

### P1 - resolve before claiming the end-to-end demo is ready

#### 7. The J level claim was overstated

`WEBAPP.md` and `DEMO-READY.md` treat 3.9 dB as a measured breaking threshold. The exact results
refute a monotonic level rule:

| capture | level drift | similarity | band |
|---|---:|---:|---|
| J1, approximately 1 m | -6.7 dB | 0.915141 | weak |
| J2, playback volume changed | -3.9 dB | 0.896582 | none |

A larger level drop survived while a smaller one failed. `rig_check.py` has already been
corrected to treat level as a gross-rig smoke alarm rather than a calibrated predictor.

**Decision:** "keep playback volume and capture path fixed" is supported. "3.9 dB breaks a
match" is not.

#### 8. Continuous iPhone capture is unproven

The latest design describes a rolling hands-free session as though the browser can already
sustain it. The Screen Wake Lock specification allows user agents to deny or auto-release a
lock and requires release when a document is hidden. WebKit has documented capture failure and
recovery issues after backgrounding, and current iOS 26 bug reports show that media-service
resets can strand microphone capture until reload.

**Decision for v1 acceptance:**

- keep the app foregrounded;
- keep the screen awake;
- record bounded MediaRecorder chunks rather than one unbounded recording;
- set iPhone Auto-Lock to Never as the deterministic demo fallback;
- detect `visibilitychange`, track `ended`/`mute`, upload failures, and stale chunks;
- require a three-minute untouched foreground capture spike before the session framework depends
  on it;
- do not claim locked-screen or background capture.

#### 9. Requested browser constraints are not guarantees

Requesting `echoCancellation`, `noiseSuppression`, and `autoGainControl` as `false` does not prove
the browser applied them. The latest design correctly calls for `getSettings()`.

**Decision:** readiness must show requested and applied values separately. A strict identity
demo run fails preflight when a required setting is unavailable or ignored; ordinary care mode
may continue with a visible degraded-state warning after calibration.

#### 10. Context data in the product spec does not exist in the legacy episode model

The current `Context` stores:

- hour;
- minutes since previous episode;
- subject age.

It does not store structured current notes/tags, feed time, caregiver-entered meaning, or
continuous-session observations. The proposed ranking therefore cannot be implemented by merely
changing weights.

**Decision:** v3 must define current observations separately from prior Episode context and must
preserve the exact caregiver evidence used by every note contribution.

#### 11. The five-factor ranking was over-specified

The initial `0.55/0.15/0.15/0.10/0.05` weights are unvalidated. With a six-to-twelve episode demo
history, duration and previous-episode gap add explanation burden without demonstrated value.

**Accepted v1 decision:** use acoustics, cyclic time-of-day, and caregiver notes only, with
provisional `0.65/0.20/0.15` weights and missing-feature renormalization. Run an ablation and
show deterministic contribution values. These weights are product heuristics, not medical
probabilities.

#### 12. "Offline" has two meanings and the documents mix them

The acoustic path is local. Transcription is only offline when a compatible local Whisper CLI
is available and explicitly selected. Phone-to-Mac HTTPS must also work with venue internet
disabled, which requires a locally trusted certificate and a LAN/hotspot that still routes.

**Decision:** readiness reports separately:

- local server reachable;
- certificate trusted;
- model weights cached;
- acoustic identity available;
- transcription mode and health;
- external internet unavailable/available.

#### 13. Continuous listening adds privacy requirements not present in the CLI consent gate

A one-time CLI consent prompt is not enough for ambient sessions. The product needs:

- persistent listening/recording indication;
- explicit session start and stop;
- pause that actually stops capture;
- a rolling-buffer retention limit;
- discard of non-event audio;
- bystander consent guidance;
- local deletion and an auditable session summary;
- no hidden/background recording claim.

### P2 - documentation integrity and presentation quality

#### 14. README is stale

It says "prototype not yet built," but the legacy prototype and 53-test suite exist. It also
uses `python` without first activating the venv and presents corpus seeding as the normal demo
path.

#### 15. Historical acceptance files lack status banners

`ACCEPTANCE.md` still says no test has been run, although `ACCEPTANCE-RESULTS-01.md` proves A-D.
Its E3 still assumes three priors. `ACCEPTANCE-02.md` remains a valid historical protocol, but
its K path is not the final phone path.

Add `HISTORICAL - results in ...` banners. Do not rewrite the original criteria.

#### 16. `DEMO-READY.md` is no longer the final checklist

It explicitly says it replaces round 2, drops J1-J4, and mandates the Mac capture rig. J was
subsequently executed, the phone path became mandatory, and its findings affect the final
architecture.

Mark it superseded and write a phone-path checklist after Acceptance 03 exists.

#### 17. `ARCHITECTURE.md` overstates its completeness

"Nothing here is aspirational" is only true for the old episode-memory loop. The target now adds
identity, source routing, mobile capture, continuous sessions, and contextual guidance.
Its "one inference" and "freeze after CLI" guidance is legacy scope advice, not current design.

#### 18. `FINDINGS.md` mixes stable evidence with stale "not tested" text

Real-room and channel robustness are no longer wholly unmeasured: H and parts of J produced
evidence. A different physical room and independent capture-device-only test remain unmeasured.
The claim that a trained CryCeleb-style model "would beat" the engineered fingerprint is a
hypothesis until the model spike reports results.

#### 19. `POSITIONING.md` is too causal

"n-of-1 trial engine" and "what actually works" imply intervention-effect estimation. The current
data is an observational interaction log with caregiver-reported outcomes and a last-action
attribution heuristic. It lacks randomization, counterfactuals, washout control, and enough
repeated observations to claim a trial.

Safer positioning:

> A personal interaction-memory system that helps caregivers notice repeated
> intervention-outcome patterns in their own history.

The n-of-1 research direction can remain a future methodology, not a current capability claim.

#### 20. `TASKS.md` is materially stale

- L, M, and N are still blocked on completed I/J work.
- the remote is listed as missing although it exists;
- the old frontend gate is circular;
- O1 says phone→Mac enrollment without naming that audio playback is Mac→phone;
- ownership does not yet include profiles, API, sessions, or mobile client;
- old "Milestone 3 only if..." scope rules conflict with the approved identity wrapper.

## UX and interaction critique

The latest design has the correct hierarchy for hands-free care: one stable, large action; a
short evidence line; controls low on the screen; optional playback secondary. It also correctly
separates identity from scenario retrieval.

Before visual implementation, it still needs:

1. a persistent, unmistakable **Listening / Paused / Connection lost** state visible from across
   the room;
2. a no-touch recovery rule for temporarily invalid chunks;
3. a clear distinction between **who matched**, **what previously helped**, and **what the
   caregiver wrote**;
4. large text acceptance criteria measured on the actual iPhone at the expected viewing
   distance;
5. minimum 44-point touch targets, safe-area handling, and no control movement as text updates;
6. a stop/delete confirmation flow that is usable with one hand while holding a baby;
7. no hidden requirement to inspect a health/debug screen during the live act - the readiness
   gate must finish before the stage flow begins.

The "five functional views" should be routes/states over one coherent session model, not five
unrelated screens. The stage-critical path is:

> readiness → enrollment → blind identity reveal → identity-gated guidance → evidence.

Episode review can remain functional but lower priority.

## Evidence and source corrections

- Use the FDA's January 6, 2026 final **General Wellness: Policy for Low Risk Devices** guidance
  as the primary regulatory source:
  https://www.fda.gov/regulatory-information/search-fda-guidance-documents/general-wellness-policy-low-risk-devices
- FDA's key software boundary is whether the intended use is related to diagnosis, cure,
  mitigation, prevention, or treatment of a disease or condition. Product copy should be
  reviewed as a whole; a disclaimer does not rescue a treatment-like function.
- Georgia's one-party audio exception is in O.C.G.A. § 16-11-66(a), while private-place visual
  recording is addressed separately in § 16-11-62. The current blanket prose should cite both
  provisions and be reviewed by counsel before non-demo deployment.
- NIH currently states that proposed human-subjects research must be submitted for IRB review or
  consideration of exemption before it begins:
  https://irbo.nih.gov/irb-review/
- `getUserMedia()` is a secure-context API under the Media Capture and Streams specification:
  https://www.w3.org/TR/mediacapture-streams/
- Screen Wake Lock can be denied or released and is tied to document visibility:
  https://www.w3.org/TR/screen-wake-lock/

## Accepted decisions from the two-agent review

The following decisions are now agreed in `MESSAGES.md` and should be merged into the product
design before implementation:

- closed-set phone identity is an early measured gate;
- verification-only is the honest fallback if Baby A/B classification is not reliable;
- visitor imitation is a separate spike and not the opening act until validated;
- visitor data is explicit-consent and ephemeral;
- continuous capture is foreground/screen-awake for v1, in bounded chunks;
- initial scenario rank uses acoustics, time, and caregiver notes only;
- possible meanings are counts plus caregiver language, never system-authored state labels;
- identity is the routing proof; personalized memory remains the caregiver benefit;
- implementation priority is enrollment, blind reveal, hands-free guidance, then review.

## Required correction sequence

1. Merge the accepted review decisions into the identity/context design and mark its written
   review complete.
2. Draft and ACK `CONTRACTS.md` v3 before cross-agent implementation.
3. Unblock only the minimal phone capture spike; keep visual polish gated.
4. Run the two-profile infant and human-imitation model spikes.
5. Write `ACCEPTANCE-03.md` from measured model/capture behavior, not assumptions.
6. Update task ownership/status and remove circular blockers.
7. Add historical/superseded banners to old protocols and checklists.
8. Update `LIABILITY.md`, then README, architecture, findings, positioning, and the final demo
   checklist in that order.

## Verification record

Run during this audit:

```text
.venv/bin/python -m unittest discover -s tests
Ran 53 tests in 0.551s
OK
```

The first attempted command, `python -m unittest discover -s tests`, failed because `python` is
not on PATH in the non-activated shell. Documentation must either activate `.venv` first or use
`.venv/bin/python` explicitly.

The passing suite verifies the existing CLI/store/retrieval/render behavior. It does not verify
the proposed identity subsystem, mobile capture, HTTP API, continuous session, contextual rank,
or guidance provenance because those components do not exist yet.
