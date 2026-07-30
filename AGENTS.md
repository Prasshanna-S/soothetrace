# AGENTS.md - read this first, every session

This repo is built by **two AI agents working in parallel** on the same working tree:

| Agent | Identity string | Owns |
|---|---|---|
| acoustics workstream | `acoustics workstream` | acoustic path, storage, retrieval |
| product workstream | `product workstream` | speech path, caregiver flow, CLI |

The human (Prasshanna) is the only one who changes ownership.

**Goal: the functionality, not a full product.** A working end-to-end loop beats a polished
shell. Do not build auth, accounts, deployment, or styling unless a task says to.

---

## THE FIVE RULES

**1. One owner per file. Never edit a file you do not own - with one exception.**
Ownership is listed in `docs/TASKS.md`. If you want a *change* inside someone else's file,
append a request to `docs/MESSAGES.md` and keep working on something else. Do not "just
quickly fix" it - that is how both agents lose an hour.

**The exception (added 2026-07-29): you MAY fix an outright bug in the other agent's file,
but you MUST log it in `docs/MESSAGES.md` in the same session.** Silence is the violation, not
the edit. Precedent: product workstream found that `store.recompute_baseline` left a *stale* per-subject
baseline row behind when a subject dropped below two fingerprints, and fixed it correctly - 
including guarding `POPULATION_KEY` so the population baseline can't be wiped. That fix was
right and is kept. It was not logged, which is the part to do differently.

Why logging is non-negotiable: the review model is "product workstream writes it, acoustics workstream tries to break
it, product workstream fixes it." An unlogged edit to the other's file breaks that loop silently - the
reviewer is now reviewing code they think they wrote.

**1b. Big artifacts get their own file - and ALWAYS a one-line pointer in `MESSAGES.md`.**
A 100-line spec appended to the log buries the log, so specs, reviews and results belong in
their own files (`ACCEPTANCE-02.md`, `REVIEW-01-acoustics.md`, ...). But `MESSAGES.md` read from the
bottom is the **only** discovery mechanism either agent has. A new file with no pointer is
invisible, and the human ends up hand-relaying it - which means the protocol has stopped working
and nobody notices. Learned the hard way on 2026-07-29: acoustics workstream wrote `ACCEPTANCE-02.md` with no
pointer, and product workstream could only find it because the human passed it along.

**2. Claim before you code.**
Edit your task's row in `docs/TASKS.md` to `IN_PROGRESS @you` *before* writing any code. If a
task is already `IN_PROGRESS` under the other agent, pick a different one.

**3. `docs/CONTRACTS.md` is frozen unless both agents agree.**
It defines every boundary between our code. To change it: propose in `docs/MESSAGES.md`,
wait for the other agent's `ACK`, then edit. Changing a contract unilaterally silently breaks
the other agent's work.

**4. Stub first, implement second.**
If you own a module the other agent imports, commit a **stub with correct signatures and
docstrings** before implementing the body. Return plausible dummy values. This unblocks them
immediately. A stub committed in 2 minutes saves an hour of blocking.

**5. Small commits, pull before push.**
`git pull --rebase` then push. Commit message must start with your identity:
`acoustics workstream: implement fingerprint normalization`. Never `--force`.

---

## Start-of-session checklist

1. Read `docs/MESSAGES.md` from the bottom - anything addressed to you?
2. Read `docs/TASKS.md` - what is `TODO` and unclaimed?
3. Skim `docs/CONTRACTS.md` - did it change since you last looked?
4. Claim a task, then work.

## End-of-session (or when you stop)

1. Set your task rows to `DONE` or back to `TODO` (never leave a stale `IN_PROGRESS`).
2. Append to `docs/MESSAGES.md`: what you finished, what you changed, anything the other
   agent must know.
3. Commit and push.

---

## Non-negotiable engineering constraints

These are conclusions from measured experiments, not preferences. Violating them reintroduces
bugs that were already found and fixed. Full evidence in `docs/FINDINGS.md`.

- **Never separate caregiver audio from infant audio.** Feed the raw mixture to both paths.
  Separation destroys the acoustic fingerprint (cosine +0.031 - no better than a stranger's
  cry) *and* truncates the transcript. `FINDINGS.md` §3.
- **Never put a generative model in the non-speech detection path.** `gpt-audio` invented three
  sound events that did not exist in a test file, with confident timestamps, while missing the
  loudest real event. `FINDINGS.md` §4.
- **Always z-score fingerprints against a stored baseline before cosine.** On raw vectors a
  *different* baby scored +0.9999 while a file matched *itself* at +0.9915. Skipping this makes
  everything match everything and the app looks like it works. `FINDINGS.md` §5.
- **Never transcribe the impaired speaker** (stroke arm). ASR emits confident, fluent, wrong
  text for dysarthric speech. Match the utterance acoustically; the caregiver supplies meaning.
- **Never render cosine similarity as a percentage confidence.** It is not a probability.
  Use the ordinal bands in `CONTRACTS.md`, and the honest "not enough data yet" state.
- **Do not install `librosa`.** Its numba/llvmlite dependency fails to build on Python 3.12 /
  macOS ARM. numpy + scipy only.
- **Never claim the system knows *why* the subject is crying.** It reports what happened before
  and what the caregiver did. The literature does not support cause-from-acoustics
  (`docs/RESEARCH.md` §1), and the product does not need it.

## Product framing (do not drift from this)

This is **a memory prosthetic for an exhausted caregiver**, not a cry translator.
An exhausted parent cannot remember what worked at 3am four nights ago, and for colic there is
no population-level answer to look up instead. See `docs/RESEARCH.md` §2 - the clinical
literature supports this framing and undermines the diagnostic one.

## Where things are

```
README.md              what this is
AGENTS.md              this file - the protocol
docs/CONTRACTS.md      🔒 interface boundaries - frozen, needs consensus
docs/TASKS.md          task board + file ownership
docs/MESSAGES.md       append-only inter-agent log
docs/FINDINGS.md       measured results; the "why" behind the constraints above
docs/RESEARCH.md       literature + competitive analysis
docs/ARCHITECTURE.md   the verified pipeline
experiments/           validated throwaway scripts (feats.py is the real reference impl)
src/                   the actual prototype
```
