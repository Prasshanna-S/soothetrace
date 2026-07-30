"""Identity subsystem - WHO is this, decided on acoustics alone. Owned by acoustics workstream.

WHAT WORKS TODAY, MEASURED ON LIVE AUDIO (docs/ACCEPTANCE-RESULTS-02.md):
verification through a phone, in a room, with a caregiver talking over the cry - 
2/2 held-out own-history recordings found, **8/8 different infants correctly rejected**,
own-history 0.924 vs strangers 0.776. This module turns that measured result into a
service.

TWO HARD RULES, both from docs/superpowers/specs/2026-07-29-identity-context-demo-design.md:

1. **Identity is acoustic ONLY.** Time, notes, duration, outcomes and scenario labels must
   never touch this decision. Context leaking into identity would make a blind reveal a
   fraud, and it would be invisible from the outside.
2. **Two gates, both calibrated from real trials.** An absolute accept threshold AND a
   runner-up margin. A `match` requires both, so a query that resembles two profiles equally
   returns `uncertain` instead of picking one.

The encoder sits behind one call so a learned embedding (ECAPA/CryCeleb) can replace the
engineered fingerprint later without touching callers.

No network calls.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np

try:
    from . import config, encoders, fingerprint, store
except ImportError:
    import config
    import encoders
    import fingerprint
    import store

# ── encoder selection is PER KIND, and this is measured, not stylistic ───────
#
#   infant          -> mfcc87-v1          13/15 correct, ZERO wrong, on a fixed rig
#   human_imitation -> ecapa-cryceleb-v1  9/9 channel-robust
#
# WHY THEY DIFFER - one property explains it. mfcc87 is CHANNEL-SENSITIVE. On the fixed-rig
# infant task that helps: the rig is constant, so the channel signature is a free consistency
# bonus, and mfcc87 beat CryCeleb there. On cross-device human imitations it HURTS, because
# the channel differs between people and the model reads the channel instead of the voice.
#
# tools/channel_robustness.py perturbed one speaker's channel across 9 plausible alternative
# recording paths. mfcc87 held in only 4/9 - a bigger room, band limiting or a phone speaker
# each INVERTED both blind queries. CryCeleb held 9/9 with margins 0.14-0.26 throughout.
#
# ⚠️ CONSEQUENCE: wiring the visitor-imitation flow to mfcc87 would work in the room it was
# tested in and FAIL in the room we present in. That is not a hypothetical - it is what the
# bigger-room perturbation measured.
KIND_INFANT = "infant"
KIND_IMITATION = "human_imitation"

ENCODER_FOR_KIND = {
    KIND_INFANT: encoders.MFCC87,
    KIND_IMITATION: encoders.ECAPA_CRY,
}
DEFAULT_KIND = KIND_INFANT

# Kept for callers/tests that ask "which encoder by default"; prefer encoder_for(kind).
ENCODER_VERSION = ENCODER_FOR_KIND[DEFAULT_KIND]

# How a profile's several enrollments combine into one score. Measured 2026-07-30: three
# multi-view alternatives were evaluated on reference-only data and NONE beat this. 20 LOO
# trials cannot separate 8 configurations, so the simplest incumbent stands.
AGGREGATION_VERSION = "mean-whole-file-v1"

# Cohort normalization is NOT in the scoring path. Measured: it does not make single-profile
# identification safe (still ~1-in-14 same-rig false accepts, and the operating point moves
# from 7.1% to 19.6% depending on which cohort is drawn). Its real value is unknown-rejection.
COHORT_VERSION = None
NOVELTY_PAIR_VERSION = "dual-encoder-demo-v1"
DEFAULT_NOVELTY_PAIR_THRESHOLDS = {
    encoders.ECAPA_CRY: 0.50,
    encoders.MFCC87: 0.85,
}


def encoder_for(kind: str | None) -> str:
    return ENCODER_FOR_KIND.get(kind or DEFAULT_KIND, ENCODER_FOR_KIND[DEFAULT_KIND])

STATUS_MATCH, STATUS_UNCERTAIN, STATUS_INVALID = "match", "uncertain", "invalid"

CALIBRATION_PATH = os.path.join(os.path.dirname(config.DB_PATH), "calibration.json")

# Fallbacks used only if no calibration file exists. Deliberately conservative: it is far
# better to return `uncertain` than to confidently name the wrong subject on stage.
_DEFAULT_CALIBRATION = {
    "version": "uncalibrated-default",
    "encoder": ENCODER_VERSION,
    "accept_threshold": 0.85,
    "margin_threshold": 0.05,
    "strong_threshold": 0.90,
    "min_enrollments_ready": 2,
}


def load_calibration(kind: str | None = None) -> dict:
    """Versioned thresholds, never hard-coded presentation magic.

    ⚠️ THRESHOLDS ARE PER-KIND, and this matters more than it looks.

    NOTHING here is trained on any individual. There is no training step in this system at
    all: the encoder is fixed deterministic maths and enrollment merely stores an embedding
    at runtime. Any person or infant enrolled live works identically to one enrolled a week
    ago - the system has no privileged knowledge of anyone.

    What IS person-independent-but-kind-dependent is the SCORE SCALE. Infant cries replayed
    through a speaker and adults performing an imitation into a phone produce different
    similarity distributions, so a threshold measured on infants says nothing about
    imitations. Sharing one threshold across both would mean the imitation flow was
    calibrated on the wrong population - which would show up as confident wrong answers,
    the one failure mode we refuse.

    So `human_imitation` falls back to the conservative defaults until imitation trials
    exist. Conservative here means more `uncertain`, never more wrong names.
    """
    try:
        with open(CALIBRATION_PATH) as fh:
            c = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULT_CALIBRATION)

    # Calibration is tied to the encoder it was measured on: the infant thresholds were
    # measured on mfcc87 and are meaningless on the CryCeleb score scale. A per-kind entry
    # declares its OWN encoder, so check that FIRST - an earlier version checked only the
    # top-level field and therefore rejected the very entry it should have used.
    want = encoder_for(kind)
    per_kind = (c.get("per_kind") or {}).get(kind) if kind else None

    if per_kind is not None:
        if per_kind.get("encoder", want) != want:
            return {**_DEFAULT_CALIBRATION, "encoder": want,
                    "version": f"{c.get('version')}-PER-KIND-ENCODER-MISMATCH-{kind}"}
        return {**_DEFAULT_CALIBRATION, **c, **per_kind,
                "encoder": want, "version": f"{c.get('version')}:{kind}"}

    if want != c.get("encoder"):
        # No entry for this kind, and the top-level thresholds belong to another encoder.
        return {**_DEFAULT_CALIBRATION, "encoder": want,
                "version": f"{c.get('version')}-NO-CALIBRATION-FOR-{kind or DEFAULT_KIND}"}
    return {**_DEFAULT_CALIBRATION, **c}


def save_calibration(c: dict) -> None:
    os.makedirs(os.path.dirname(CALIBRATION_PATH), exist_ok=True)
    with open(CALIBRATION_PATH, "w") as fh:
        json.dump(c, fh, indent=1)


# ── embeddings ───────────────────────────────────────────────────────────────

def embed(audio_path: str, kind: str | None = None) -> list[float] | None:
    """Encode one recording with the encoder that kind was measured on.

    None when the audio is unusable. Never raises.
    """
    return encoders.encode(encoder_for(kind), audio_path)


def _novelty_pair_consistency_many(
    reference_audio_paths: list[str],
    query_audio_path: str,
    kind: str,
    db_path=None,
) -> list[dict]:
    """Check several references against one query without re-encoding the query.

    Being outside every enrolled profile is not enough. Two different unseen people can both
    be outliers. The session may create a new profile only when the two recordings are also
    consistent with each other.

    Human imitation uses two independent acoustic views. CryCeleb contributes the
    channel-robust identity view. MFCC contributes a same-rig spectral view that separates
    the three-person demonstration cohort where CryCeleb alone overlaps. Both gates must pass.
    Raw scores remain internal and are never returned by the public HTTP API.
    """
    references = list(reference_audio_paths or [])
    if not references:
        return []
    if kind != KIND_IMITATION:
        return [
            {
                "consistent": False,
                "version": NOVELTY_PAIR_VERSION,
                "reasons": ["novelty_pair_check_not_available_for_kind"],
            }
            for _ in references
        ]

    calibration = load_calibration(kind)
    version = calibration.get("novelty_pair_version", NOVELTY_PAIR_VERSION)
    thresholds = calibration.get("novelty_pair_thresholds")
    if not isinstance(thresholds, dict):
        thresholds = DEFAULT_NOVELTY_PAIR_THRESHOLDS

    scores = [{} for _ in references]
    usable = [True for _ in references]
    for encoder_name in (encoders.ECAPA_CRY, encoders.MFCC87):
        query = encoders.encode(encoder_name, query_audio_path)
        if query is None:
            return [
                {
                    "consistent": False,
                    "version": version,
                    "reasons": ["novelty_pair_audio_unusable"],
                }
                for _ in references
            ]
        reference_vectors = [
            encoders.encode(encoder_name, reference_path)
            for reference_path in references
        ]
        valid_indexes = [
            index
            for index, vector in enumerate(reference_vectors)
            if vector is not None
        ]
        for index, vector in enumerate(reference_vectors):
            if vector is None:
                usable[index] = False

        baseline = None
        if encoders.needs_baseline(encoder_name):
            baseline = _population_baseline(db_path)
            if baseline is None:
                return [
                    {
                        "consistent": False,
                        "version": version,
                        "reasons": ["novelty_pair_baseline_unavailable"],
                    }
                    for _ in references
                ]
        if not valid_indexes:
            continue
        try:
            prepared = encoders.prepare(
                encoder_name,
                [query, *[reference_vectors[index] for index in valid_indexes]],
                baseline,
            )
        except (TypeError, ValueError):
            return [
                {
                    "consistent": False,
                    "version": version,
                    "reasons": ["novelty_pair_audio_unusable"],
                }
                for _ in references
            ]
        for offset, index in enumerate(valid_indexes, 1):
            scores[index][encoder_name] = float(prepared[0] @ prepared[offset])

    results = []
    for index, pair_scores in enumerate(scores):
        if not usable[index]:
            results.append(
                {
                    "consistent": False,
                    "version": version,
                    "reasons": ["novelty_pair_audio_unusable"],
                }
            )
            continue
        consistent = all(
            pair_scores.get(encoder_name, -1.0)
            >= float(
                thresholds.get(
                    encoder_name,
                    DEFAULT_NOVELTY_PAIR_THRESHOLDS[encoder_name],
                )
            )
            for encoder_name in (encoders.ECAPA_CRY, encoders.MFCC87)
        )
        results.append(
            {
                "consistent": consistent,
                "version": version,
                "scores": pair_scores,
                "reasons": [
                    "novelty_pair_consistent"
                    if consistent
                    else "novelty_pair_inconsistent"
                ],
            }
        )
    return results


def _novelty_pair_consistency(first_audio_path: str, second_audio_path: str,
                              kind: str, db_path=None) -> dict:
    """Check that two outlier cries support one new human profile."""
    results = _novelty_pair_consistency_many(
        [first_audio_path],
        second_audio_path,
        kind,
        db_path,
    )
    return results[0] if results else {
        "consistent": False,
        "version": NOVELTY_PAIR_VERSION,
        "reasons": ["novelty_pair_audio_unusable"],
    }


def recordings_consistent(first_audio_path: str, second_audio_path: str,
                          kind: str, db_path=None) -> dict:
    """Return a public dual-encoder consistency decision without raw scores."""
    return public_pair_result(
        _novelty_pair_consistency(first_audio_path, second_audio_path, kind, db_path)
    )


def recordings_consistent_many(
    reference_audio_paths: list[str],
    query_audio_path: str,
    kind: str,
    db_path=None,
) -> list[dict]:
    """Return score-free pair decisions while encoding the shared query once."""
    return [
        public_pair_result(result)
        for result in _novelty_pair_consistency_many(
            reference_audio_paths,
            query_audio_path,
            kind,
            db_path,
        )
    ]


def public_pair_result(result: dict) -> dict:
    """Remove internal pair-comparison scores before a result crosses a public boundary."""
    return {
        "consistent": bool(result.get("consistent")),
        "version": result.get("version"),
        "reasons": list(result.get("reasons") or []),
    }


def _session_identity_result(result: dict) -> dict:
    """Keep session classification metadata while removing all acoustic measurements."""
    public = {
        key: result.get(key)
        for key in (
            "status", "profile_id", "display_name", "band", "reasons", "kind",
            "pool_size", "versions", "quality",
        )
    }
    public["candidates"] = [
        {
            key: candidate[key]
            for key in ("profile_id", "display_name", "kind")
            if key in candidate
        }
        for candidate in result.get("candidates", [])
    ]
    return public


def _population_baseline(db_path=None):
    """⚠️ db_path MUST be threaded through. An earlier version omitted it, so identity
    silently read the DEFAULT database's baseline regardless of which database the
    profiles lived in - caught by tests/test_acoustics_identity.py."""
    b = store.get_baseline(config.POPULATION_KEY, db_path)
    if not b or not b.get("mu") or not b.get("sd"):
        return None
    return np.asarray(b["mu"], dtype=np.float64), np.asarray(b["sd"], dtype=np.float64)


def _normalize(vecs, mu, sd):
    """z-score against the population baseline, then L2.

    ⚠️ MANDATORY. On raw fingerprints a DIFFERENT baby scored +0.9999 while a file matched
    ITSELF at +0.9915 - everything matches everything (docs/FINDINGS.md §5).
    """
    X = np.atleast_2d(np.asarray(vecs, dtype=np.float64))
    Z = (X - mu) / (sd + 1e-9)
    return Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)


def quality(audio_path: str) -> dict:
    """Capture quality straight from the samples - no ffmpeg subprocess needed."""
    y = fingerprint.load_audio(audio_path)
    if y is None or len(y) == 0:
        return {"mean_db": None, "peak_db": None, "voiced_fraction": 0.0, "duration_s": 0.0}
    rms = float(np.sqrt((y ** 2).mean() + 1e-12))
    peak = float(np.abs(y).max() + 1e-12)
    voiced = float(fingerprint._voiced_mask(y).mean())
    return {"mean_db": round(20 * np.log10(rms), 2),
            "peak_db": round(20 * np.log10(peak), 2),
            "voiced_fraction": round(voiced, 4),
            "duration_s": round(len(y) / fingerprint.SR, 3)}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _conn(db_path=None):
    store.init_db(db_path)
    con = sqlite3.connect(db_path or config.DB_PATH)
    con.row_factory = sqlite3.Row
    return con


# ── profiles ─────────────────────────────────────────────────────────────────

def create_profile(display_name: str, kind: str = KIND_INFANT, db_path=None) -> dict:
    if not display_name or kind not in (KIND_INFANT, KIND_IMITATION):
        return {}
    con = _conn(db_path)
    try:
        cur = con.execute(
            "INSERT INTO profile (display_name, kind, status, created_at) VALUES (?,?,?,?)",
            (display_name.strip(), kind, "provisional", _now()))
        con.commit()
        return get_profile(int(cur.lastrowid), db_path)
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def get_profile(profile_id: int, db_path=None) -> dict:
    con = _conn(db_path)
    try:
        row = con.execute("SELECT * FROM profile WHERE id=?", (profile_id,)).fetchone()
        if not row:
            return {}
        p = dict(row)
        p["enrollments"] = con.execute(
            "SELECT COUNT(*) FROM enrollment WHERE profile_id=?", (profile_id,)).fetchone()[0]
        return p
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def list_profiles(db_path=None) -> list[dict]:
    con = _conn(db_path)
    try:
        ids = [r[0] for r in con.execute(
            "SELECT id FROM profile WHERE status != 'archived' ORDER BY id")]
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [get_profile(i, db_path) for i in ids]


def profile_reference_audio(profile_id: int, db_path=None) -> list[str]:
    """Return one profile's enrollment paths, without exposing stored embeddings."""
    con = _conn(db_path)
    try:
        rows = con.execute(
            "SELECT audio_path FROM enrollment WHERE profile_id=? "
            "ORDER BY captured_at, id",
            (profile_id,),
        ).fetchall()
        return [r["audio_path"] for r in rows if r["audio_path"]]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def delete_profile(profile_id: int, db_path=None) -> dict:
    """Deletes the profile, its enrollments, and their managed audio.

    docs/LIABILITY.md §4 - deletion must actually delete. Refuses to touch audio outside
    AUDIO_DIR so corpus source files are never destroyed.
    """
    con = _conn(db_path)
    removed = 0
    try:
        rows = con.execute("SELECT audio_path FROM enrollment WHERE profile_id=?",
                           (profile_id,)).fetchall()
        root = os.path.abspath(config.AUDIO_DIR)
        for r in rows:
            p = r["audio_path"]
            if p and os.path.exists(p) and os.path.abspath(p).startswith(root):
                try:
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
        con.execute("DELETE FROM enrollment WHERE profile_id=?", (profile_id,))
        con.execute("DELETE FROM profile WHERE id=?", (profile_id,))
        con.commit()
        return {"deleted": True, "audio_files_removed": removed}
    except sqlite3.Error:
        return {"deleted": False, "audio_files_removed": removed}
    finally:
        con.close()


# ── enrollment ───────────────────────────────────────────────────────────────

def enroll(profile_id: int, audio_path: str, capture_device_name: str | None = None,
           source_type: str | None = None, db_path=None) -> dict:
    """Add one independent enrollment to a profile.

    A profile is the SET of its enrollments - never just the most recent clip. It stays
    `provisional` until it has `min_enrollments_ready` (default 2), because a single clip
    cannot tell within-source variation from between-source variation.
    """
    prof = get_profile(profile_id, db_path)
    if not prof:
        return {"status": "error", "reason": "no_such_profile"}
    if not audio_path or not os.path.exists(audio_path):
        return {"status": "error", "reason": "missing_audio"}

    enc = encoder_for(prof.get("kind"))
    vec = embed(audio_path, prof.get("kind"))
    q = quality(audio_path)
    if vec is None:
        return {"status": "rejected", "reason": "no_usable_voiced_audio", "quality": q}

    digest = _sha256(audio_path)
    con = _conn(db_path)
    try:
        dup = con.execute(
            "SELECT id FROM enrollment WHERE profile_id=? AND audio_sha256=?",
            (profile_id, digest)).fetchone()
        if dup:
            # Enrollment and query must always be distinct files (spec §4.5); the same
            # applies to two enrollments, or a profile "agrees with itself" for free.
            return {"status": "rejected", "reason": "duplicate_audio",
                    "existing_enrollment_id": dup["id"]}
        # ...and it must not be enrolled into a DIFFERENT profile of the same kind either.
        # Measured consequence of allowing it: two profiles containing one identical take
        # are mathematically indistinguishable, so every later query hits
        # `close_top_profiles` forever and the flow silently dies. A mis-tap during live
        # visitor enrollment is exactly how this happens.
        cross = con.execute(
            "SELECT e.id, e.profile_id, p.display_name FROM enrollment e "
            "JOIN profile p ON p.id = e.profile_id "
            "WHERE e.audio_sha256=? AND e.profile_id != ? AND p.kind = ?",
            (digest, profile_id, prof.get("kind"))).fetchone()
        if cross:
            return {"status": "rejected", "reason": "audio_already_enrolled_to_another_profile",
                    "existing_enrollment_id": cross["id"],
                    "existing_profile_id": cross["profile_id"],
                    "existing_profile_name": cross["display_name"]}
        cur = con.execute(
            "INSERT INTO enrollment (profile_id, audio_path, audio_sha256, captured_at, "
            "duration_s, capture_device_name, capture_quality, source_type, "
            "encoder_version, embedding) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (profile_id, audio_path, digest, _now(), q["duration_s"], capture_device_name,
             json.dumps(q), source_type or prof.get("kind"), enc,
             np.asarray(vec, dtype=np.float32).tobytes()))
        eid = int(cur.lastrowid)
        n = con.execute("SELECT COUNT(*) FROM enrollment WHERE profile_id=?",
                        (profile_id,)).fetchone()[0]
        ready = n >= load_calibration(prof.get("kind"))["min_enrollments_ready"]
        con.execute("UPDATE profile SET status=? WHERE id=?",
                    ("ready" if ready else "provisional", profile_id))
        con.commit()
    except sqlite3.Error as exc:
        con.rollback()
        return {"status": "error", "reason": str(exc)}
    finally:
        con.close()

    return {"status": "enrolled", "enrollment_id": eid, "enrollments": n,
            "profile_status": "ready" if ready else "provisional", "quality": q}


def _enrollments(db_path=None, kind=None,
                 profile_ids: set[int] | None = None) -> dict[int, list[dict]]:
    con = _conn(db_path)
    try:
        rows = con.execute(
            "SELECT e.id, e.profile_id, e.audio_path, e.embedding, e.encoder_version, "
            "p.display_name, p.kind, p.status FROM enrollment e "
            "JOIN profile p ON p.id = e.profile_id WHERE p.status != 'archived'").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    out: dict[int, list[dict]] = {}
    for r in rows:
        if kind and r["kind"] != kind:
            continue
        if profile_ids is not None and r["profile_id"] not in profile_ids:
            continue
        # With kind=None this used to compare every row against the DEFAULT encoder and so
        # silently returned only the infant family. Each row is now checked against the
        # encoder for ITS OWN kind, so a kind=None caller gets every family, correctly.
        want_enc = encoder_for(kind or r["kind"])
        if r["encoder_version"] != want_enc:
            continue           # never mix encoders in one comparison
        try:
            vec = np.frombuffer(r["embedding"], dtype=np.float32)
        except (ValueError, TypeError):
            continue      # corrupt blob: skip the enrollment, never raise (CONTRACTS rule 6)
        if vec.size != (encoders.dim(want_enc) or vec.size):
            continue      # wrong dimensionality for this encoder
        out.setdefault(r["profile_id"], []).append({
            "enrollment_id": r["id"], "audio_path": r["audio_path"], "vec": vec,
            "display_name": r["display_name"], "kind": r["kind"], "status": r["status"]})
    return out


# ── identification ───────────────────────────────────────────────────────────

def _band(score: float, cal: dict) -> str:
    if score >= cal["strong_threshold"]:
        return "strong"
    if score >= cal["accept_threshold"]:
        return "weak"
    return "none"


def _profile_kinds(db_path=None) -> set[str]:
    con = _conn(db_path)
    try:
        return {r[0] for r in con.execute(
            "SELECT DISTINCT p.kind FROM profile p JOIN enrollment e ON e.profile_id = p.id "
            "WHERE p.status != 'archived'")}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def _evaluate(kind: str, audio_path: str, db_path=None,
              profile_ids: set[int] | None = None) -> dict | None:
    """Score a query against ONE kind's profiles, using that kind's encoder and calibration.

    Families are evaluated separately and never compared to each other: an mfcc87 cosine and
    a CryCeleb cosine are different scales, so a cross-family "best score" would be
    meaningless. Returns None when this family has nothing to compare against.
    """
    pool = _enrollments(db_path, kind, profile_ids)
    if not pool:
        return None
    enc = encoder_for(kind)
    cal = load_calibration(kind)

    q = encoders.encode(enc, audio_path)
    if q is None:
        return {"status": STATUS_INVALID, "kind": kind, "cal": cal,
                "reasons": ["no_usable_voiced_audio"]}

    baseline = None
    if encoders.needs_baseline(enc):
        baseline = _population_baseline(db_path)
        if baseline is None:
            return {"status": STATUS_INVALID, "kind": kind, "cal": cal,
                    "reasons": ["no_population_baseline"]}

    scored = []
    for pid, ens in pool.items():
        vecs = [e["vec"] for e in ens]
        try:
            E = encoders.prepare(enc, vecs, baseline)
            qn = encoders.prepare(enc, q, baseline)[0]
        except (ValueError, TypeError):
            continue
        sims = E @ qn
        scored.append({
            "profile_id": pid, "display_name": ens[0]["display_name"],
            "kind": ens[0]["kind"], "status": ens[0]["status"],
            "score": float(np.mean(sims)), "enrollments": len(ens),
            "support": {"enrollment_id": ens[int(np.argmax(sims))]["enrollment_id"],
                        "audio_path": ens[int(np.argmax(sims))]["audio_path"],
                        "score": float(np.max(sims))}})
    if not scored:
        return None

    scored.sort(key=lambda x: -x["score"])
    top = scored[0]
    runner = scored[1] if len(scored) > 1 else None
    margin = float(top["score"] - runner["score"]) if runner else float("inf")

    reasons = []
    # ⛔ ONE PROFILE IS NOT ENOUGH TO MAKE AN IDENTIFICATION CLAIM.
    #
    # With a single enrolled profile there is no runner-up, so the margin gate cannot fire
    # and the ABSOLUTE threshold alone guards everything. That threshold is the weakest part
    # of the system: the measured verification distributions OVERLAP - 93.3% true-accept at
    # 6.7% FALSE-accept (data/calibration.json). Raising the bar does not fix it; an
    # unrelated source still false-accepted in testing.
    #
    # In the live visitor flow a false accept reads as: "first person enrols, second person
    # is told they are the first person." A ~1-in-15 chance of that on stage is not
    # acceptable, so we refuse the claim instead of gambling on it.
    #
    # Cost: the demo must enrol TWO subjects before querying. That is also better theatre - 
    # "which of you two is this?" beats "is this you?" - so the constraint is free.
    single_profile = runner is None
    bar = cal["accept_threshold"]
    if single_profile:
        single_reasons = [
            "only_one_enrolled_profile",
            "cannot_identify_without_a_comparison",
            "enrol_a_second_profile_to_compare",
        ]
        if top["score"] < bar:
            single_reasons += ["below_accept_threshold", "new_or_unenrolled_source"]
        return {"status": STATUS_UNCERTAIN, "kind": kind, "cal": cal, "top": top,
                "runner": None, "margin": float("inf"), "scored": scored,
                "reasons": single_reasons,
                "encoder": enc, "bar": bar}

    reasons_pre = []
    if top["score"] < bar:
        status = STATUS_UNCERTAIN
        reasons += ["below_accept_threshold", "new_or_unenrolled_source"]
    elif margin < cal["margin_threshold"]:
        status = STATUS_UNCERTAIN
        reasons.append("close_top_profiles")
    else:
        status = STATUS_MATCH
        reasons.append("acoustically_consistent_with_enrolled_profile")
        if top["status"] == "provisional":
            reasons.append("profile_provisional_single_enrollment")
    return {"status": status, "kind": kind, "cal": cal, "top": top, "runner": runner,
            "margin": margin, "scored": scored, "reasons": reasons_pre + reasons,
            "encoder": enc, "bar": bar}


def _identify(audio_path: str, kind: str | None = None, db_path=None,
              audit: bool = True, profile_ids: set[int] | None = None) -> dict:
    """WHO is this? Acoustics only - no context, ever.

    `kind` picks the family (and therefore the encoder and calibration). Leave it None to
    evaluate every enrolled family independently; a match is returned only when EXACTLY ONE
    family matches. If two families both match, the source type is ambiguous and we return
    `uncertain` rather than compare incomparable score scales.

    `score` and `margin` are DEBUG ONLY. Render `band` and `reasons`.
    """
    result = {"status": STATUS_INVALID, "profile_id": None, "display_name": None,
              "band": "none", "score": None, "margin": None, "support": None,
              "reasons": [], "candidates": [], "kind": kind, "pool_size": 0,
              "versions": {"encoder": encoder_for(kind), "calibration": None,
                           "aggregation": AGGREGATION_VERSION, "cohort": COHORT_VERSION}}

    if not audio_path or not os.path.exists(audio_path):
        result["reasons"] = ["missing_audio"]
        return result
    result["quality"] = quality(audio_path)

    kinds = [kind] if kind else sorted(_profile_kinds(db_path))
    if not kinds:
        result["status"] = STATUS_UNCERTAIN
        result["reasons"] = ["no_enrolled_profiles"]
        return result

    evaluated = [r for r in (_evaluate(k, audio_path, db_path, profile_ids) for k in kinds) if r]
    if not evaluated:
        result["status"] = STATUS_UNCERTAIN
        result["reasons"] = ["no_enrolled_profiles"]
        return result

    invalid = [r for r in evaluated if r["status"] == STATUS_INVALID]
    if len(invalid) == len(evaluated):
        result["reasons"] = invalid[0]["reasons"]
        result["versions"]["calibration"] = invalid[0]["cal"]["version"]
        return result

    usable = [r for r in evaluated if r["status"] != STATUS_INVALID]
    matches = [r for r in usable if r["status"] == STATUS_MATCH]

    if len(matches) > 1:
        chosen = max(matches, key=lambda r: r["margin"])
        chosen = {**chosen, "status": STATUS_UNCERTAIN,
                  "reasons": ["ambiguous_source_type",
                              "matched_more_than_one_family"]}
    elif matches:
        chosen = matches[0]
    else:
        # NO family matched. Do NOT compare raw scores across families - an mfcc87 cosine
        # and a CryCeleb cosine are different scales, and picking the numerically larger one
        # is the exact mistake this design exists to prevent. Compare each family's distance
        # to ITS OWN accept threshold, which is scale-aware.
        def _headroom(r):
            t = r.get("top")
            return (t["score"] - r["cal"]["accept_threshold"]) if t else -9.0
        chosen = max(usable, key=_headroom)

    cal = chosen["cal"]
    top = chosen.get("top")
    result.update({
        "status": chosen["status"], "reasons": chosen["reasons"], "kind": chosen["kind"],
        "versions": {"encoder": chosen.get("encoder", encoder_for(chosen["kind"])),
                     "calibration": cal["version"],
                     "aggregation": AGGREGATION_VERSION, "cohort": COHORT_VERSION}})
    if top:
        result.update({
            "score": top["score"], "support": top["support"],
            "margin": None if chosen["margin"] == float("inf") else chosen["margin"],
            # A band is a claim. If the status is not `match`, there is no claim to make - 
            # a renderer keying on band would otherwise display a confident result the
            # system explicitly refused.
            "band": _band(top["score"], cal) if chosen["status"] == STATUS_MATCH else "none",
            "pool_size": len(chosen["scored"]),
            "candidates": [{"profile_id": c["profile_id"],
                            "display_name": c["display_name"],
                            "kind": c["kind"],
                            "score": round(c["score"], 6)} for c in chosen["scored"][:4]]})
        if chosen["status"] == STATUS_MATCH:
            result["profile_id"] = top["profile_id"]
            result["display_name"] = top["display_name"]

    if audit:
        _audit(audio_path, result, cal, db_path)
    return result


def identify(audio_path: str, kind: str | None = None, db_path=None,
             audit: bool = True) -> dict:
    """WHO is this? Acoustics only - no context, ever.

    `kind` picks the family (and therefore the encoder and calibration). Leave it None to
    evaluate every enrolled family independently; a match is returned only when EXACTLY ONE
    family matches. If two families both match, the source type is ambiguous and we return
    `uncertain` rather than compare incomparable score scales.

    `score` and `margin` are DEBUG ONLY. Render `band` and `reasons`.
    """
    return _identify(audio_path, kind, db_path, audit)


def identify_within_profiles(audio_path: str, profile_ids: list[int], kind: str,
                             db_path=None, audit: bool = True) -> dict:
    """Identify against exactly the caller's session profile set.

    This is separate from ``candidate_profile_ids`` on identity attempts, which remains a
    display-only field and must never narrow that lifecycle's scoring pool.
    """
    return _session_identity_result(
        _identify(audio_path, kind, db_path, audit, set(profile_ids))
    )


def _audit(audio_path: str, res: dict, cal: dict, db_path=None) -> None:
    con = _conn(db_path)
    try:
        con.execute(
            "INSERT INTO identity_query (audio_path, audio_sha256, captured_at, "
            "result_status, matched_profile_id, supporting_enrollment_id, band, score, "
            "margin, reason_codes, encoder_version, calibration_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (audio_path, _sha256(audio_path), _now(), res["status"], res["profile_id"],
             (res["support"] or {}).get("enrollment_id"), res["band"], res["score"],
             None if res["margin"] in (None, float("inf")) else res["margin"],
             json.dumps(res["reasons"]), ENCODER_VERSION, cal["version"]))
        con.commit()
    except sqlite3.Error:
        pass
    finally:
        con.close()


# ── identity attempt lifecycle ────────────────────────────────────────────────
# `independent-retry-confirmation-v1` + refinement 5a, agreed in docs/MESSAGES.md.
#
# THE POINT OF THE RETRY: it is EVIDENTIAL, not a second roll of the dice. Capture 1 may
# only NOMINATE a profile; capture 2 must independently clear a STRICTER bar and name that
# same profile. Nothing is pooled - no waveform, embedding, cosine, margin or headroom is
# ever averaged across captures.
#
# WHY THE STRICTER BAR (5a): capture 2 is scored against the full pool with its own gates, so
# it carries the SAME false-accept probability as any capture. Two chances take attempt-level
# FAR from ~0.071 to ~0.125 - about 1.8x worse. Requiring margin >= 2x threshold (or score
# >= strong) restores roughly single-capture FAR. Genuine margins measured 0.14-0.26 against a
# 0.055 threshold, so 2x sits comfortably inside genuine range and rarely costs a real subject.
#
# AND A CAVEAT WORTH KNOWING: the "capture 2 must name capture 1's nomination" agreement is
# WEAKER evidence than it looks. For a given stranger, which enrolled profile is nearest is a
# stable property of that voice, not a fresh draw - both captures come from the same person and
# tend to pick the same profile. It filters an INCONSISTENT capture, not a consistent impostor.

ATTEMPT_OPEN, ATTEMPT_MATCH, ATTEMPT_UNRESOLVED = "open", "match", "unresolved"
RETRY_BAR_MULTIPLIER = 2.0

# Reasons where a second recording cannot possibly help, because the missing thing is a
# COMPARISON, not a better sample.
_NO_RETRY_REASONS = {"only_one_enrolled_profile", "no_enrolled_profiles"}


def _attempt(attempt_id: int, db_path=None) -> dict:
    con = _conn(db_path)
    try:
        row = con.execute("SELECT * FROM identity_attempt WHERE id=?", (attempt_id,)).fetchone()
        if not row:
            return {}
        a = dict(row)
        a["retry_allowed"] = bool(a["retry_allowed"])
        for f in ("candidate_profile_ids", "reasons"):
            try:
                a[f] = json.loads(a[f]) if a[f] else None
            except (json.JSONDecodeError, TypeError):
                a[f] = None
        caps = con.execute(
            "SELECT * FROM identity_attempt_capture WHERE attempt_id=? ORDER BY id",
            (attempt_id,)).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    a["captures"] = [_capture_row(c) for c in caps]
    a["valid_captures"] = sum(1 for c in a["captures"] if c["status"] != STATUS_INVALID)
    return a


def _capture_row(c) -> dict:
    d = dict(c)
    d["retry_bar_applied"] = bool(d["retry_bar_applied"])
    for f in ("capture_metadata", "quality", "candidates", "reasons"):
        try:
            d[f] = json.loads(d[f]) if d[f] else None
        except (json.JSONDecodeError, TypeError):
            d[f] = None
    return d


def begin_identity_attempt(kind: str, candidate_profile_ids: list[int] | None = None,
                           db_path: str | None = None) -> dict:
    """Open one identity incident.

    ⚠️ `candidate_profile_ids` restricts what a caller DISPLAYS, never what is SCORED.
    Scoring always runs against every non-archived profile of this kind, so the runner-up
    margin is computed against the full pool. Narrowing the scoring pool would remove a
    potential runner-up and INFLATE the margin, turning an honest `uncertain` into a
    confident match through an API parameter.
    """
    if kind not in (KIND_INFANT, KIND_IMITATION):
        return {"error": "bad_kind"}
    con = _conn(db_path)
    try:
        cur = con.execute(
            "INSERT INTO identity_attempt (kind, created_at, status, candidate_profile_ids, "
            "retry_allowed) VALUES (?,?,?,?,1)",
            (kind, _now(), ATTEMPT_OPEN,
             json.dumps(candidate_profile_ids) if candidate_profile_ids else None))
        con.commit()
        return _attempt(int(cur.lastrowid), db_path)
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    finally:
        con.close()


def _store_capture(attempt_id: int, seq: int, identity_audio_path: str,
                   capture_metadata: dict | None, res: dict, retry_bar_applied: bool,
                   db_path=None) -> int:
    meta = capture_metadata or {}
    v = res.get("versions") or {}
    con = _conn(db_path)
    try:
        cur = con.execute(
            "INSERT INTO identity_attempt_capture (attempt_id, seq, captured_at, "
            "source_audio_path, canonical_audio_path, identity_audio_path, audio_sha256, "
            "capture_metadata, quality, status, top_profile_id, score, margin, band, "
            "pool_size, candidates, reasons, encoder_version, calibration_version, "
            "aggregation_version, cohort_version, retry_bar_applied) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (attempt_id, seq, _now(),
             meta.get("source_path") or meta.get("source_audio_path"),
             meta.get("canonical_path") or meta.get("canonical_audio_path"),
             identity_audio_path, _sha256(identity_audio_path),
             json.dumps(meta), json.dumps(res.get("quality") or {}),
             res.get("status"),
             (res.get("candidates") or [{}])[0].get("profile_id")
             if res.get("candidates") else None,
             res.get("score"),
             None if res.get("margin") in (None, float("inf")) else res.get("margin"),
             res.get("band"), res.get("pool_size"),
             json.dumps(res.get("candidates") or []),
             json.dumps(res.get("reasons") or []),
             v.get("encoder"), v.get("calibration"), v.get("aggregation"), v.get("cohort"),
             1 if retry_bar_applied else 0))
        con.commit()
        return int(cur.lastrowid)
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def _close_attempt(attempt_id: int, status: str, reasons: list[str],
                   matched_profile_id=None, resolution_path=None,
                   resolution_source=None, db_path=None) -> None:
    con = _conn(db_path)
    try:
        con.execute(
            "UPDATE identity_attempt SET status=?, reasons=?, matched_profile_id=?, "
            "resolution_path=?, resolution_source=?, resolved_at=? WHERE id=?",
            (status, json.dumps(reasons), matched_profile_id, resolution_path,
             resolution_source, _now(), attempt_id))
        con.commit()
    except sqlite3.Error:
        pass
    finally:
        con.close()


def _set_nomination(attempt_id: int, profile_id, retry_allowed: bool, db_path=None) -> None:
    con = _conn(db_path)
    try:
        con.execute("UPDATE identity_attempt SET nominated_profile_id=?, retry_allowed=? "
                    "WHERE id=?", (profile_id, 1 if retry_allowed else 0, attempt_id))
        con.commit()
    except sqlite3.Error:
        pass
    finally:
        con.close()


def add_identity_capture(attempt_id: int, identity_audio_path: str,
                         capture_metadata: dict | None = None,
                         db_path: str | None = None) -> dict:
    """First capture of an attempt. Scores against the FULL same-kind pool.

    * `match`     -> resolves immediately, `resolution_path="first_capture"`.
    * `invalid`   -> recorded, does NOT consume the retry, attempt stays open.
    * `uncertain` -> nominates its top-ranked profile and permits one retry, EXCEPT when the
      reason is `only_one_enrolled_profile` / `no_enrolled_profiles`, where another recording
      cannot create the missing comparison.
    """
    a = _attempt(attempt_id, db_path)
    if not a:
        return {"error": "no_such_attempt"}
    if a["status"] != ATTEMPT_OPEN:
        return {"error": "attempt_immutable", "status": a["status"]}
    if a["valid_captures"] >= 1:
        return {"error": "first_capture_already_recorded",
                "hint": "use retry_identity_attempt"}

    res = identify(identity_audio_path, kind=a["kind"], db_path=db_path)
    invalid = res["status"] == STATUS_INVALID
    # seq 0 marks a capture that does not count against the two-capture budget
    _store_capture(attempt_id, 0 if invalid else 1, identity_audio_path,
                   capture_metadata, res, False, db_path)

    if invalid:
        return {**_attempt(attempt_id, db_path), "capture_status": STATUS_INVALID,
                "retry_consumed": False, "reasons": res["reasons"]}

    if res["status"] == STATUS_MATCH:
        _close_attempt(attempt_id, ATTEMPT_MATCH, res["reasons"], res["profile_id"],
                       "first_capture", "system", db_path)
        return {**_attempt(attempt_id, db_path), "capture_status": STATUS_MATCH}

    top = (res.get("candidates") or [{}])[0].get("profile_id") if res.get("candidates") else None
    novelty_candidate = {
        "below_accept_threshold",
        "new_or_unenrolled_source",
    }.issubset(set(res["reasons"]))
    can_retry = novelty_candidate or not (_NO_RETRY_REASONS & set(res["reasons"]))
    _set_nomination(attempt_id, top, can_retry, db_path)
    if not can_retry:
        _close_attempt(attempt_id, ATTEMPT_UNRESOLVED, res["reasons"], None, None, "system",
                       db_path)
    return {**_attempt(attempt_id, db_path), "capture_status": STATUS_UNCERTAIN,
            "nominated_profile_id": top, "reasons": res["reasons"]}


def retry_identity_attempt(attempt_id: int, identity_audio_path: str,
                           capture_metadata: dict | None = None,
                           db_path: str | None = None) -> dict:
    """Second capture. Independent, full pool, and held to the STRICTER 5a bar.

    Resolves ONLY if it matches on its own merits AND names capture 1's nomination.
    Never creates or enrols a profile.
    """
    a = _attempt(attempt_id, db_path)
    if not a:
        return {"error": "no_such_attempt"}
    if a["status"] != ATTEMPT_OPEN:
        return {"error": "attempt_immutable", "status": a["status"]}
    if not a["retry_allowed"]:
        return {"error": "retry_not_allowed", "reasons": a.get("reasons") or []}
    if a["valid_captures"] < 1:
        return {"error": "no_first_capture"}
    if a["valid_captures"] >= 2:
        return {"error": "retry_exhausted"}

    # ⛔ RETRY INDEPENDENCE IS ENFORCED HERE, ON THE BACKEND, BY DIGEST.
    #
    # A retry only means something if it is a genuinely NEW recording. Re-submitting the same
    # bytes gives the same embedding, so the "capture 2 must independently pass and agree"
    # rule degenerates into "capture 1, scored twice" and the attempt resolves on evidence it
    # never had.
    #
    # The client cannot be the guard. product workstream's audit found that client-side clip ids are
    # bypassed simply by re-selecting the same file from the picker: a fresh id, identical
    # bytes. Any client-side check is defeated the same way, so the rule lives in the store.
    digest = _sha256(identity_audio_path)
    if digest and any(c.get("audio_sha256") == digest for c in a.get("captures", [])):
        return {"error": "retry_audio_identical_to_earlier_capture",
                "reason": "a retry must be an independent recording, not the same bytes again",
                "audio_sha256": digest}

    res = identify(identity_audio_path, kind=a["kind"], db_path=db_path)
    invalid = res["status"] == STATUS_INVALID
    cal = load_calibration(a["kind"])

    # ── refinement 5a: a retry must clear a stricter bar than a first capture ──
    bar_met = True
    if res["status"] == STATUS_MATCH:
        m = res.get("margin")
        strict_margin = cal["margin_threshold"] * RETRY_BAR_MULTIPLIER
        bar_met = (m is None) or (m >= strict_margin) or \
                  (res.get("score") is not None and res["score"] >= cal["strong_threshold"])
        if not bar_met:
            res = {**res, "status": STATUS_UNCERTAIN,
                   "reasons": list(res["reasons"]) + ["retry_bar_not_met"]}

    if invalid:
        _store_capture(
            attempt_id,
            0,
            identity_audio_path,
            capture_metadata,
            res,
            False,
            db_path,
        )
        return {**_attempt(attempt_id, db_path), "capture_status": STATUS_INVALID,
                "retry_consumed": False, "reasons": res["reasons"]}

    first_capture = next(
        (
            capture
            for capture in a.get("captures", [])
            if capture.get("status") != STATUS_INVALID
        ),
        None,
    )
    first_reasons = set((first_capture or {}).get("reasons") or [])
    second_reasons = set(res.get("reasons") or [])
    novelty_reasons = {"below_accept_threshold", "new_or_unenrolled_source"}
    if (
        novelty_reasons.issubset(first_reasons)
        and novelty_reasons.issubset(second_reasons)
        and first_capture
        and first_capture.get("identity_audio_path")
    ):
        pair = _novelty_pair_consistency(
            first_capture["identity_audio_path"],
            identity_audio_path,
            a["kind"],
            db_path,
        )
        pair_reasons = [
            reason
            for reason in pair.get("reasons") or []
            if isinstance(reason, str)
        ]
        if pair.get("consistent"):
            final_reasons = list(res["reasons"]) + pair_reasons + [
                "new_profile_candidate_confirmed",
            ]
        else:
            final_reasons = list(res["reasons"]) + pair_reasons + [
                "retry_exhausted",
            ]
        res = {**res, "reasons": final_reasons}
        _store_capture(
            attempt_id,
            2,
            identity_audio_path,
            capture_metadata,
            res,
            False,
            db_path,
        )
        _close_attempt(
            attempt_id,
            ATTEMPT_UNRESOLVED,
            final_reasons,
            None,
            None,
            "system",
            db_path,
        )
        return {
            **_attempt(attempt_id, db_path),
            "capture_status": STATUS_UNCERTAIN,
            "reasons": final_reasons,
        }

    _store_capture(
        attempt_id,
        2,
        identity_audio_path,
        capture_metadata,
        res,
        res["status"] == STATUS_MATCH,
        db_path,
    )

    if res["status"] == STATUS_MATCH:
        if res["profile_id"] == a["nominated_profile_id"]:
            _close_attempt(attempt_id, ATTEMPT_MATCH,
                           list(res["reasons"]) + ["retry_confirmed_nomination"],
                           res["profile_id"], "retry_confirmed", "system", db_path)
            return {**_attempt(attempt_id, db_path), "capture_status": STATUS_MATCH}
        _close_attempt(attempt_id, ATTEMPT_UNRESOLVED,
                       list(res["reasons"]) + ["captures_disagree"], None, None, "system",
                       db_path)
        return {**_attempt(attempt_id, db_path), "capture_status": STATUS_MATCH,
                "reasons": ["captures_disagree"]}

    _close_attempt(attempt_id, ATTEMPT_UNRESOLVED,
                   list(res["reasons"]) + ["retry_exhausted"], None, None, "system", db_path)
    return {**_attempt(attempt_id, db_path), "capture_status": STATUS_UNCERTAIN,
            "reasons": list(res["reasons"]) + ["retry_exhausted"]}


def resolve_identity_attempt(attempt_id: int, confirmed_profile_id: int | None = None,
                             db_path: str | None = None) -> dict:
    """Human resolution of an attempt the system could not resolve.

    ⚠️ Recorded as `resolution_source="human"` and `resolution_path="human"`, DISTINCT from a
    machine match. A human-confirmed attempt must never be counted in any accuracy figure - 
    without that separation the audit cannot tell what the system identified from what a
    person told it, and every accuracy number becomes unfalsifiable.

    ⚠️ NEVER enrols the capture. Linking an incident to a profile is not evidence that this
    recording belongs in that profile, and auto-enrolling would let one mis-tap poison a
    profile permanently.
    """
    a = _attempt(attempt_id, db_path)
    if not a:
        return {"error": "no_such_attempt"}
    if a["status"] == ATTEMPT_MATCH and a.get("resolution_source") == "system":
        return {"error": "attempt_immutable", "status": a["status"]}
    if confirmed_profile_id is not None and not get_profile(confirmed_profile_id, db_path):
        return {"error": "no_such_profile"}

    if confirmed_profile_id is None:
        _close_attempt(attempt_id, ATTEMPT_UNRESOLVED,
                       (a.get("reasons") or []) + ["closed_without_resolution"],
                       None, None, "human", db_path)
    else:
        _close_attempt(attempt_id, ATTEMPT_MATCH,
                       (a.get("reasons") or []) + ["human_confirmed_not_machine_identified"],
                       confirmed_profile_id, "human", "human", db_path)
    return _attempt(attempt_id, db_path)


def get_identity_attempt(attempt_id: int, db_path: str | None = None) -> dict:
    """Full attempt with every capture, for audit and for the UI."""
    return _attempt(attempt_id, db_path)
