# Task board

**Claim by editing the Status cell to `IN_PROGRESS @you` BEFORE writing code.**
Statuses: `TODO` · `IN_PROGRESS acoustics workstream` · `IN_PROGRESS product workstream` · `BLOCKED` · `DONE`

Never leave a stale `IN_PROGRESS` - set it back to `TODO` if you stop.

---

## Milestone 1 - the loop works end to end (CLI only, no UI)

Definition of done: record two episodes for one subject; the second prints what the caregiver
did the first time. Nothing else. **This is the whole hackathon-critical path.**

| # | Task | File(s) | Owner | Status |
|---|---|---|---|---|
| 1.1 | Port `experiments/feats.py` → `src/fingerprint.py` behind the contract signature | `src/fingerprint.py` | acoustics workstream | DONE ✅ verified by product workstream |
| 1.2 | `config.py` with the values in CONTRACTS | `src/config.py` | acoustics workstream | DONE ✅ |
| 1.3 | `schema.sql` + `store.py` (init/save/update/get/list) | `src/store.py`, `src/schema.sql` | acoustics workstream | DONE ✅ |
| 1.4 | Baseline (mu/sd) - **population-first**, per-subject fallback | `src/store.py`, `tools/build_baseline.py` | acoustics workstream | DONE ✅ n=421, dim=87 |
| 1.5 | `retrieve.find_similar` + percentile banding + MIN_EPISODES gate | `src/retrieve.py` | acoustics workstream | DONE ✅ 2 strong / 1 weak on seed |
| 1.6 | **STUB FIRST** then implement `speech.transcribe` | `src/speech.py` | product workstream | DONE |
| 1.7 | `speech.extract_interventions` - evidence span mandatory | `src/speech.py` | product workstream | DONE |
| 1.8 | `speech.infer_outcome` - returns None rather than guessing | `src/speech.py` | product workstream | DONE |
| 1.9 | `session.record` - mic → 16 kHz mono wav | `src/session.py` | product workstream | DONE |
| 1.10 | `session.finish` - the full pipeline per CONTRACTS | `src/session.py` | product workstream | DONE |
| 1.11 | `cli.py`: `record` / `finish` / `history` commands | `src/cli.py` | product workstream | DONE |
| 1.12 | Seed script: replay one corpus infant's recordings as episodes | `tools/seed_demo.py` | acoustics workstream | DONE ✅ 12 episodes seeded |
| 1.13 | Run and verify 1.1-1.12 | - | product workstream | DONE ✅ passed 2026-07-29 |

## Milestone 2 - honest presentation

| # | Task | File(s) | Owner | Status |
|---|---|---|---|---|
| 2.1 | Recall card renderer; bands only, never a percentage | `src/render.py` | product workstream | DONE |
| 2.2 | "Not enough data yet" state (<3 episodes) | `src/render.py` | product workstream | DONE |
| 2.3 | Always surface `outcome_src` | `src/render.py` | product workstream | DONE |
| 2.4 | Context features into the Episode (hour, gap, age) | `src/fingerprint.py` | acoustics workstream | DONE ✅ `build_context()`, wired in seed |
| 2.5 | Offline switch: local `whisper` CLI when `config.OFFLINE` | `src/speech.py` | product workstream | DONE |
| 2.6 | 🔴 **Caregiver safety message** - long/repeated failed episodes → "it's safe to put the baby down and step away." **Required, not optional** (`LIABILITY.md` §5) | `src/render.py` | product workstream | DONE |
| 2.7 | "Consider talking to your pediatrician" prompt - non-diagnostic wording only (`LIABILITY.md` §1) | `src/render.py` | product workstream | DONE |
| 2.8 | Auto-generated **cry diary** export - the T2 deliverable; a manual paper instrument today | `src/diary.py` | acoustics workstream | DONE ✅ verified by product workstream on 12-episode seed |
| 2.9 | Consent gate before first recording; audio-only, no video, ever (`LIABILITY.md` §2) | `src/cli.py` | product workstream | DONE |
| 2.10 | Deletion that actually deletes: audio + row + recomputed baseline | `src/store.py` | product workstream | DONE ✅ stale-baseline regression covered |
| 2.11 | 🔴 **BUG:** `session.finish` sets `worked=True` for ANY caregiver answer - "nothing worked" is stored as a success, corrupting `intervention_tally` | `src/session.py` | product workstream | DONE ✅ explicit valence only |
| 2.12 | 🔴 **BUG:** `caregiver_guidance` tests `worked is False`, but the real path yields `None` - **the required safety message never fires** | `src/render.py` | product workstream | DONE |
| 2.13 | 🟠 **BUG:** `long_episode` scans all history, so one long episode fires the safety message forever → alert fatigue | `src/render.py` | product workstream | DONE |

> ⚠️ **Milestone 2 is not complete until 2.11-2.13 are fixed.** A milestone whose required
> safety feature does not fire is not done. Full analysis: [`REVIEW-01-acoustics.md`](REVIEW-01-acoustics.md).

## Milestone 3 - only if 1 and 2 are fully done

| # | Task | File(s) | Owner | Status |
|---|---|---|---|---|
Reassigned 2026-07-29 by demonstrated strength - see "Division of labour" below.

| # | Task | File(s) | Owner | Status |
|---|---|---|---|---|
| 3.0 | 🔴 **Adversarial review pass over every `DONE` row** - 2.11-2.13 prove `DONE` has been optimistic | all | acoustics workstream | TODO |
| 3.1 | Verification pass: run the full loop end to end, mic included, and report | - | product workstream | DONE ✅ A-D pass; `ACCEPTANCE-RESULTS-01.md` |
| 3.2 | Export a subject's record as a **Communication Passport** (`RESEARCH.md` §3d - the differentiator artifact) | `src/passport.py` | acoustics workstream | DONE. Third person on purpose, provisional under 3 episodes, seed data stamped at the top; 14 tests |
| 3.3 | ⭐ **Web UI** - 25% of the hackathon score is visual craft | `web/` | acoustics workstream | DONE. Neutral high-contrast system, one centered column, verified by rendering at 390/768/1280 |
| 3.4 | "Coming soon" disabled surfaces - stroke, dementia, ICU, passport, clinician report, multi-caregiver. **Must never display fabricated output as computed** (`LIABILITY.md` §7) | `web/` | acoustics workstream | DONE. `#not-in-this-build`, six surfaces, no handlers, each states WHY it is off |
| 3.5 | Demo script + pitch narrative, using only real computed output | `docs/DEMO.md` | acoustics workstream | DONE. Run of show, quotable-numbers table with mandatory caveats, withdrawn claims, banned sentences |
| 3.6 | Weight context alongside acoustics in ranking - **deferred, scope-freeze risk** | `src/retrieve.py` | acoustics workstream | DEFERRED |

## Division of labour - set by evidence, 2026-07-29

Reassigned after reviewing what each agent actually produced in session 1, not by preference.

**product workstream demonstrated:**
- **Implementation velocity** - 11 tasks shipped in one session, all to contract.
- **Defensive discipline** - validation at every entry point, safe empty returns, no raises.
- **Going beyond spec where it counts** - verifying `evidence` spans with `transcript.find()`
  rather than trusting the model was stronger than `CONTRACTS.md` asked for.
- **Environmental judgment** - caught that the git root is `/Users/prasshannas`, so acoustics workstream's
  suggested `--source=.` would have published the entire home directory. Real save.
- **Working tooling** - reliable shell and git, which acoustics workstream has not had this session.

**product workstream's weak axis:** *semantic* correctness. All three bugs in `REVIEW-01-acoustics.md` are
well-formed code that means the wrong thing - `worked=True` for any answer, `is False` where the
real value is `None`, an unbounded `any()`. Local correctness is high; "what does this mean for
an exhausted parent at 3am" is where it slips.

**acoustics workstream demonstrated:**
- **Empirical decisions that set the architecture** - the two measured dead ends (source
  separation, `gpt-audio` for non-speech) and the normalization trap.
- **Research and liability** - FDA general wellness boundary, IRB limits, Georgia recording law,
  the n-of-1 framing, LENA lineage, both prior-art papers.
- **Adversarial semantic review** - found three real bugs in code already marked `DONE`.

**acoustics workstream's weak axis:** *execution.* Shell access has succeeded roughly 1 call in 6 this
session. acoustics workstream must not own anything gated on running code.

### Therefore

| Work type | Owner | Why |
|---|---|---|
| Implementation of defined modules | **product workstream** | fastest and disciplined |
| Anything requiring execution, verification, git | **product workstream** | acoustics workstream's tooling is unreliable |
| Adversarial review of every `DONE` | **acoustics workstream** | caught 3 bugs product workstream shipped as done |
| Research, positioning, liability wording | **acoustics workstream** | already owns the evidence base |
| UI and visual design | **acoustics workstream** | 25% of score; acoustics workstream has the design tooling |
| Demo narrative and pitch | **acoustics workstream** | owns the framing and the constraints |

**The rule this produces: product workstream writes it, acoustics workstream tries to break it, product workstream fixes it.**
Neither marks its own work `DONE` on a semantic question.

> ⚠️ **Freeze scope after Milestone 2.** The rubric this is built against rewards a small
> finished thing over a large 80%-done one. A fourth act actively costs points.

---

## File ownership (authoritative - rule 1 in AGENTS.md)

| Path | Owner |
|---|---|
| `src/fingerprint.py`, `src/store.py`, `src/retrieve.py`, `src/config.py`, `src/schema.sql`, `src/diary.py` | acoustics workstream |
| `tools/**`, `experiments/**` | acoustics workstream |
| `requirements.txt`, `.gitignore` | acoustics workstream |
| `src/speech.py`, `src/session.py`, `src/cli.py`, `src/render.py` | product workstream |
| `docs/FINDINGS.md`, `docs/RESEARCH.md`, `docs/ARCHITECTURE.md` | acoustics workstream |
| `docs/CONTRACTS.md` | 🔒 both - consensus only |
| `docs/MESSAGES.md` | both - append only |
| `docs/TASKS.md` | both - edit only your own rows |
| `AGENTS.md`, `README.md` | acoustics workstream (propose changes via MESSAGES) |

## Known blockers

- ~~arXiv 2306.05446 / 2401.08866 not read~~ - **RESOLVED 2026-07-29**, both read via
  WebSearch. `RESEARCH.md` §3c/§5 updated. Key takeaway: Apple's Latent Phrase Matching
  reports **+60% recall over commercial ASR** for dysarthric speech, so
  "match, don't transcribe" is now a cited result rather than our inference.
- **Stroke/dysarthric arm has zero empirical validation *of our own*.** Do not build it in
  Milestone 1-2. When it is built, build it as phrase matching, never ASR.
- 🔴 **GitHub remote still not created** - delegated to product workstream (has working git); see MESSAGES.
  acoustics workstream's shell tool is down for the whole session (permission-classifier outage),
  which also blocks WebFetch. Local repo is the source of truth until the remote exists.
- **`config.OFFLINE` is a no-op** until task 2.5 lands - `transcribe()` always calls the API.

---

## Round 2 acceptance - the product case (spec: [`ACCEPTANCE-02.md`](ACCEPTANCE-02.md))

Round 1 passed but tested the wrong cell of the matrix. Channel mismatch was found to break
matching (B2: -0.258 cross-channel vs 0.909 same-channel) while caregiver speech overlay does
not. **Different-occasion matching on live audio has never been tested - and that is the product.**

| # | Task | Owner | Status |
|---|---|---|---|
| H1 | Build live corpus: 8 X cries + 8 Y cries through ONE fixed rig; caregiver speech over 4 of the X | product workstream | DONE ✅ 16 usable live episodes; quiet Y3 replaced by Y9 from same infant |
| H2 | 🔴 **CRITICAL** - different-occasion, same-channel discrimination. If this fails, STOP and report | product workstream | DONE ✅ X 0.923546 vs Y 0.775709; X weak, all Y none |
| H3 | 🔴 Does caregiver speech degrade different-occasion matching? | product workstream | DONE ✅ speech 0.914281 vs no-speech 0.932811 |
| I | Episode-count sweep n=1..6 → measure the real `MIN_EPISODES_FOR_MATCH` (current `3` is a guess; E3 showed 3 is too few) | product workstream | DONE ✅ measured useful threshold N=6 |
| J | Channel tolerance: distance, volume, room, device, background noise → operating envelope | product workstream | DONE ⚠️ volume boundary found; true-room/device tests require unavailable room/third device |
| K | 🔴 Demo integrity: seed from LIVE recordings, not corpus. Corpus-seeded + live-queried is the failing comparison | product workstream | IN_PROGRESS product workstream |
| L | Set `MIN_EPISODES_FOR_MATCH` to the measured value from I | acoustics workstream | BLOCKED on I |
| M | `tools/seed_live.py` - seed the demo from live recordings through the demo rig | acoustics workstream | BLOCKED on I |
| N | Document the operating envelope from J in README + LIABILITY | acoustics workstream | BLOCKED on J |

> **Frontend remains blocked until H, I, J, K pass.** Confirmed by the human: backend
> functionality fully verified first, UI only after.

## Identity-first demo wrapper

| # | Task | Owner | Status |
|---|---|---|---|
| O1 | Specify phone→Mac enrollment, open-set identity, evidence playback, and identity-gated contextual episode retrieval | product workstream | DONE ✅ |
| O2 | Audit every normative spec against code, measured evidence, final demo direction, privacy, and inter-document consistency | product workstream | IN_PROGRESS product workstream |
| O3 | Spike phone HTTPS mic capture, applied settings, bounded upload/decode, and 3-minute foreground continuity | product workstream | DONE ✅ screen-lock capture, MIME/upload/decode, and offline transcription measured; see `SPIKE-RESULTS-2026-07-29.md` |
| O4 | Exact managed-audio ingest and normalization | product workstream | DONE ✅ 8 focused tests; 97 total pass |
| O5 | Offline evidence extraction and grounded guidance | product workstream | DONE ✅ 18 new evidence/guidance tests; 115 total pass |
| O6 | Identity-attempt and care-event contract integration | product workstream | IN_PROGRESS product workstream |
| O7 | Incremental per-recording identity session, desktop workspace, real-audio stress test, and public handoff | product workstream | DONE. 295 tests; browser checks at 430, 900, and 1440 pixels; staged and difficult three-person gates passed with zero wrong named directions or profile splits |
| O8 | Native Windows 10/11 backend setup, model cache compatibility, portable capture and certificate paths, and Windows CI | product workstream | DONE. Windows PowerShell 5.1 setup and run launchers, encoder warm-up, ready-health gate, and real HTTP observation passed on GitHub Actions run 30551468918 |
