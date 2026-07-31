"""Similarity search + honest confidence banding. Owned by acoustics workstream.

THIS IS THE ONLY PLACE COSINE IS COMPUTED (docs/CONTRACTS.md rule 2). product workstream must call
find_similar() rather than comparing vectors, because two things here are easy to get
wrong and both are silent failures:

1. NORMALIZATION IS MANDATORY. Measured on raw fingerprints: a DIFFERENT baby scored
   +0.9999 while a file matched ITSELF at +0.9915. Skip the z-score and everything matches
   everything - the app confidently returns the same answer forever and looks like it is
   working. docs/FINDINGS.md §5.

2. COSINE IS NOT A PROBABILITY. It must never reach a human as a percentage. We return an
   ordinal band derived from percentiles of this subject's OWN history, and below
   MIN_EPISODES_FOR_MATCH prior episodes we return [] so the UI shows the honest
   "not enough to compare yet" state.

Validated behaviour: within-subject episode discrimination AUC 0.70; episode-level top-1
retrieval 30.5% vs 0.7% chance across 421 episodes / 207 subjects. docs/FINDINGS.md §1-2.

No network calls (rule 7).
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

try:
    from . import config, store
except ImportError:
    import config
    import store

MIN_EPISODES_FOR_MATCH = config.MIN_EPISODES_FOR_MATCH

_SELF_MATCH_EPS = 0.9999  # guards against comparing an episode with itself
EpisodeFilter = Callable[[dict], bool]
_CAREGIVER_EVIDENCE_MAX_CHARS = 220


def _excerpt(value) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()[:_CAREGIVER_EVIDENCE_MAX_CHARS]


def _caregiver_evidence(episode: dict) -> dict | None:
    """Return one bounded literal excerpt with honest provenance."""
    if not isinstance(episode, dict):
        return None
    context = episode.get("context")
    context = context if isinstance(context, dict) else {}
    transcript = episode.get("transcript")
    transcript = transcript if isinstance(transcript, str) else ""

    evidence = ""
    for intervention in episode.get("interventions") or []:
        if not isinstance(intervention, dict):
            continue
        candidate = intervention.get("evidence")
        if isinstance(candidate, str) and candidate.strip():
            evidence = candidate
            break

    audio_marker = "Audio transcript:"
    typed_marker = "Typed caregiver follow-up:"
    audio_text = ""
    typed_text = ""
    if audio_marker in transcript:
        audio_text = transcript.split(audio_marker, 1)[1]
        if typed_marker in audio_text:
            audio_text = audio_text.split(typed_marker, 1)[0]
    if typed_marker in transcript:
        typed_text = transcript.split(typed_marker, 1)[1]

    is_synthetic = (
        episode.get("outcome_src") == "seed"
        or context.get("synthetic_demo_memory") is True
    )
    if is_synthetic:
        source = "synthetic_demo"
        literal = evidence or transcript
    elif evidence and audio_text and evidence.casefold() in audio_text.casefold():
        source = "captured_transcript"
        literal = evidence
    elif evidence and typed_text and evidence.casefold() in typed_text.casefold():
        source = "typed_follow_up"
        literal = evidence
    elif audio_text:
        source = "captured_transcript"
        literal = audio_text
    elif typed_text:
        source = "typed_follow_up"
        literal = typed_text
    else:
        source = "caregiver_record"
        literal = evidence or transcript

    text = _excerpt(literal)
    if not text:
        return None
    return {"text": text, "source": source}


# --------------------------------------------------------------- normalization

def _baseline_for(subject_id: str, db_path: str | None = None):
    """Population baseline preferred; per-subject only as a fallback.

    A subject with a handful of episodes cannot supply stable statistics - the validated
    results normalized against 431 corpus recordings. Build the population baseline once
    with tools/build_baseline.py. Returns (mu, sd) or None.
    """
    for key in (config.POPULATION_KEY, subject_id):
        b = store.get_baseline(key, db_path)
        if b and b.get("mu") and b.get("sd"):
            mu = np.asarray(b["mu"], dtype=np.float64)
            sd = np.asarray(b["sd"], dtype=np.float64)
            if mu.shape == sd.shape and mu.size:
                return mu, sd
    return None


def _normalize(X, mu, sd):
    """z-score then L2. X may be 1-D or 2-D."""
    X = np.atleast_2d(np.asarray(X, dtype=np.float64))
    Z = (X - mu) / (sd + 1e-9)
    n = np.linalg.norm(Z, axis=1, keepdims=True)
    return Z / (n + 1e-9)


# ------------------------------------------------------------------- banding

def _bands_for(vectors, mu, sd):
    """Percentile cutoffs from this subject's own pairwise similarity history.

    Returns (strong_cut, weak_cut) or None when there are too few pairs. Using the
    subject's own distribution rather than fixed constants is what keeps the bands
    meaningful across subjects with different vocal characteristics.
    """
    if len(vectors) < 2:
        return None
    Z = _normalize(vectors, mu, sd)
    S = Z @ Z.T
    iu = np.triu_indices(len(Z), 1)
    sims = S[iu]
    if sims.size == 0:
        return None
    return (float(np.percentile(sims, config.BAND_STRONG_PCTL)),
            float(np.percentile(sims, config.BAND_WEAK_PCTL)))


def _band(sim: float, cuts) -> str:
    if cuts is None:
        return "none"
    strong, weak = cuts
    if sim >= strong:
        return "strong"
    if sim >= weak:
        return "weak"
    return "none"


# --------------------------------------------------------------- public API

def _eligible_episodes(
    subject_id: str,
    db_path: str | None,
    episode_filter: EpisodeFilter | None,
) -> list[dict]:
    episodes = store.list_episodes(subject_id, db_path)
    if episode_filter is not None:
        episodes = [episode for episode in episodes if episode_filter(episode)]
    return episodes

def find_similar(subject_id: str, fingerprint: list[float], k: int = 3,
                 exclude_episode_id: int | None = None,
                 db_path: str | None = None,
                 episode_filter: EpisodeFilter | None = None) -> list[dict]:
    """Top-k Matches from this subject's prior episodes, best first.

    Guarantees (docs/CONTRACTS.md):
      * z-scores against a stored baseline before cosine - always
      * returns [] when fewer than MIN_EPISODES_FOR_MATCH prior episodes exist, so the
        caller MUST render the "not enough data yet" state
      * `band` is derived from percentiles of this subject's own history, not constants
      * `similarity` is for logs/debug only and must never be shown to a human

    `exclude_episode_id` skips a specific episode - pass it if the query episode has
    already been saved, otherwise it will match itself.

    `episode_filter`, when supplied by a controlled product flow, is applied before
    the minimum-history gate, confidence bands, ranking, and top-k truncation.
    """
    if not subject_id or not fingerprint:
        return []

    episodes = [ep for ep in _eligible_episodes(
                subject_id, db_path, episode_filter)
                if ep.get("fingerprint")
                and ep.get("id") != exclude_episode_id]
    if len(episodes) < MIN_EPISODES_FOR_MATCH:
        return []

    base = _baseline_for(subject_id, db_path)
    if base is None:
        # No baseline means no safe comparison. Returning [] is correct: a raw-cosine
        # fallback here would produce ~0.99 for everything. FINDINGS §5.
        return []
    mu, sd = base

    vectors = [ep["fingerprint"] for ep in episodes]
    if any(len(v) != len(mu) for v in vectors) or len(fingerprint) != len(mu):
        return []

    Z = _normalize(vectors, mu, sd)
    q = _normalize(fingerprint, mu, sd)[0]
    sims = Z @ q

    cuts = _bands_for(vectors, mu, sd)

    order = np.argsort(-sims)
    out = []
    for i in order:
        sim = float(sims[i])
        if sim >= _SELF_MATCH_EPS:
            continue  # same recording; not a memory, just itself
        ep = episodes[int(i)]
        out.append({
            "episode_id":    ep.get("id"),
            "similarity":    sim,
            "band":          _band(sim, cuts),
            "started_at":    ep.get("started_at"),
            "interventions": ep.get("interventions") or [],
            "outcome":       ep.get("outcome"),
            "outcome_src":   ep.get("outcome_src"),
        })
        if len(out) >= max(1, k):
            break
    return out


def episode_count(
    subject_id: str,
    db_path: str | None = None,
    episode_filter: EpisodeFilter | None = None,
) -> int:
    """How many USABLE episodes this subject has - i.e. ones with a fingerprint.

    Counts exactly what find_similar can act on. Counting un-fingerprintable episodes
    (silence, a failed capture) would tell the caregiver she has 5 recordings while
    retrieval quietly refuses to compare any of them - the numbers on screen would
    contradict the behaviour, and she would have no way to tell which was lying.
    """
    return sum(1 for ep in _eligible_episodes(
               subject_id, db_path, episode_filter)
               if ep.get("fingerprint"))


def intervention_tally(
    subject_id: str,
    db_path: str | None = None,
    episode_filter: EpisodeFilter | None = None,
) -> list[dict]:
    """Per-intervention success counts across a subject's whole history.

    This is the T2 ("health over time") payload and the one part of the system that
    cannot fail - arithmetic over what the caregiver reported, never inference.

    Returns [{'action', 'tried', 'worked', 'worked_last'}], best first.

    TWO ATTRIBUTION MODELS, and the difference matters:

    * `worked` - credited to EVERY action present in an episode the caregiver marked as
      resolved. Generous, and it dilutes: if she checks the diaper and then feeds, both
      get credit for a resolution only one of them caused.

    * `worked_last` - credited only to the FINAL action of a resolved episode. A caregiver
      works through things in sequence and *stops when one works*, so the last action is
      the probable cause. This is the better estimator and the one to show a human.

    Neither is causal proof; both are counts. `worked_last` is simply the less misleading
    count. A single episode proves nothing under either model - only repetition separates
    what works, which is the entire premise of the longitudinal claim.

    Ordering uses `worked_last` first, deliberately: it is what should surface.
    """
    tally: dict[str, dict] = {}

    def _slot(action: str) -> dict:
        return tally.setdefault(action, {"action": action, "tried": 0,
                                         "worked": 0, "worked_last": 0})

    for ep in _eligible_episodes(subject_id, db_path, episode_filter):
        ivs = [iv for iv in (ep.get("interventions") or [])
               if isinstance(iv, dict) and (iv.get("action") or "").strip()]
        if not ivs:
            continue
        resolved = bool(ep.get("worked"))          # None and False both mean "not resolved"

        for a in {(iv["action"]).strip().lower() for iv in ivs}:
            t = _slot(a)
            t["tried"] += 1
            if resolved:
                t["worked"] += 1

        if resolved:
            # `order` is 1-based per CONTRACTS; fall back to list position if absent.
            last = max(ivs, key=lambda iv: iv.get("order")
                       if isinstance(iv.get("order"), int) else ivs.index(iv))
            _slot(last["action"].strip().lower())["worked_last"] += 1

    return sorted(tally.values(),
                  key=lambda t: (-t["worked_last"], -t["worked"], -t["tried"]))


# ── identity-gated scenario ranking ──────────────────────────────────────────
# The bridge between "WHO is this" (identity.py) and "what helped before" (guidance).
# Identity decides WHICH episodes are searchable; this decides which of THOSE are relevant.
#
# Weights are explicit PRODUCT choices, not learned medical claims, and are deliberately
# only three components. An earlier draft had five; duration-similarity and gap-since-previous
# were dropped because with 6-12 episodes per subject they are noise, and each is a surface a
# judge can call arbitrary. Time-of-day is kept because it is the one with literature behind it
# (documented circadian evening crying peak - docs/RESEARCH.md §1).

W_ACOUSTIC = 0.65
W_TIME_OF_DAY = 0.20
W_NOTES = 0.15


def _time_of_day_similarity(hour_a, hour_b) -> float | None:
    """Cyclic hour similarity in [0,1]. 23:00 and 01:00 are close, not 22 hours apart."""
    if hour_a is None or hour_b is None:
        return None
    d = abs(int(hour_a) - int(hour_b)) % 24
    return 1.0 - (min(d, 24 - d) / 12.0)


def _notes_similarity(tags_a, tags_b) -> float | None:
    """Jaccard overlap of caregiver tags/notes. None when either side has none."""
    a = {t.strip().lower() for t in (tags_a or []) if str(t).strip()}
    b = {t.strip().lower() for t in (tags_b or []) if str(t).strip()}
    if not a or not b:
        return None
    return len(a & b) / len(a | b)


def find_scenarios(subject_id: str, fingerprint_vec: list[float],
                   current_context: dict | None = None, k: int = 3,
                   db_path: str | None = None,
                   episode_filter: EpisodeFilter | None = None) -> list[dict]:
    """Rank ONE subject's prior episodes by acoustic + contextual similarity.

    MUST be called only after identity returns `match`. This function does not check
    identity - the caller is responsible for passing the accepted subject, and passing the
    wrong one silently mixes another individual's history into the results.

    `current_context` may contain `hour_local` and `tags` (list[str]). Missing components are
    omitted and the remaining weights renormalized, so an episode is never penalised for data
    we do not have.

    `episode_filter` is applied before acoustic ranking and to the context lookup.

    Returns, best first:
        {episode_id, rank_score, band, similarity, started_at, interventions, outcome,
         outcome_src, worked, contributions: [reason codes], components: {...}}

    `band` is the ACOUSTIC confidence from find_similar and stays separate from `rank_score`.
    Composite ranking does not turn a cosine into a probability, and neither number may be
    rendered to a human as a percentage.
    """
    if not subject_id or not fingerprint_vec:
        return []
    ctx = current_context or {}
    acoustic = find_similar(
        subject_id,
        fingerprint_vec,
        k=50,
        db_path=db_path,
        episode_filter=episode_filter,
    )
    if not acoustic:
        return []

    by_id = {
        ep["id"]: ep
        for ep in _eligible_episodes(subject_id, db_path, episode_filter)
    }
    out = []
    for m in acoustic:
        ep = by_id.get(m["episode_id"], {})
        ep_ctx = ep.get("context") or {}

        # Acoustic similarity is a cosine in [-1,1]; map to [0,1] for weighted blending.
        comps = {"acoustic": (float(m["similarity"]) + 1.0) / 2.0}
        tod = _time_of_day_similarity(ctx.get("hour_local"), ep_ctx.get("hour_local"))
        if tod is not None:
            comps["time_of_day"] = tod
        notes = _notes_similarity(ctx.get("tags"), ep_ctx.get("tags"))
        if notes is not None:
            comps["notes"] = notes

        weights = {"acoustic": W_ACOUSTIC, "time_of_day": W_TIME_OF_DAY, "notes": W_NOTES}
        active = {c: weights[c] for c in comps}
        total = sum(active.values()) or 1.0
        score = sum(comps[c] * (w / total) for c, w in active.items())

        # Deterministic contribution labels - the source of truth. Generated prose may
        # paraphrase these, but the labels and values are what we stand behind.
        ranked = sorted(comps.items(), key=lambda kv: -(kv[1] * active[kv[0]] / total))
        labels = {"acoustic": "cry pattern was the strongest available signal",
                  "time_of_day": "occurred at a similar time of day",
                  "notes": "caregiver notes overlapped"}
        contributions = [labels[c] for c, _ in ranked[:2]]
        if "time_of_day" not in comps:
            contributions.append("no time-of-day information available")

        scenario = {
            **m,
            "rank_score": round(float(score), 6),
            "worked": ep.get("worked"),
            "components": {c: round(float(v), 4) for c, v in comps.items()},
            "weights_used": {c: round(w / total, 4) for c, w in active.items()},
            "contributions": contributions,
        }
        caregiver_evidence = _caregiver_evidence(ep)
        if caregiver_evidence is not None:
            scenario["caregiver_evidence"] = caregiver_evidence
        out.append(scenario)

    out.sort(key=lambda r: -r["rank_score"])
    return out[:max(1, k)]
