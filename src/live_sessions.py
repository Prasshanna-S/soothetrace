"""Persistent state machine for incremental, session-scoped identity discovery.

Filesystem locations and acoustic measurements are deliberately kept behind this
module's public rendering boundary. Callers receive stable participant labels,
classification states, reason codes, and audio playback URLs only.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone

try:
    from . import config, identity, store
except ImportError:
    import config
    import identity
    import store


SESSION_OPEN = "open"
SESSION_COMPLETED = "completed"
PARTICIPANT_PROVISIONAL = "provisional"
PARTICIPANT_ESTABLISHED = "established"
PENDING_NOVELTY_REASON = "pending_new_participant_evidence"
# With only two profiles, a first observation from a third source must rank one of them
# first. Keep that safe novelty unlabelled. A larger pool may expose its direction while
# the observation still remains pending and cannot reinforce or create a profile alone.
MIN_POOL_FOR_PENDING_DIRECTION = 3


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _conn(db_path=None) -> sqlite3.Connection:
    store.init_db(db_path)
    con = sqlite3.connect(db_path or config.DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _reason_codes(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(reason) for reason in raw]
    try:
        decoded = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(reason) for reason in decoded] if isinstance(decoded, list) else []


def _label(position: int) -> str:
    """Return spreadsheet-style stable labels: 1=A, 26=Z, 27=AA."""
    if position < 1:
        return ""
    letters = []
    value = position
    while value:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return f"Person {''.join(reversed(letters))}"


def _public_participant(row) -> dict | None:
    if not row:
        return None
    participant = dict(row)
    return {
        "id": participant["id"],
        "profile_id": participant["profile_id"],
        "display_name": participant["display_name"],
        "state": participant["state"],
        "support_count": participant["support_count"],
        "created_at": participant["created_at"],
        "established_at": participant["established_at"],
    }


def _participant_by_id(con: sqlite3.Connection, participant_id: int | None):
    if participant_id is None:
        return None
    return con.execute(
        "SELECT * FROM live_identity_participant WHERE id=?",
        (participant_id,),
    ).fetchone()


def _public_observation(con: sqlite3.Connection, row) -> dict:
    observation = dict(row)
    participant = _public_participant(
        _participant_by_id(con, observation["participant_id"])
    )
    closest = _public_participant(
        _participant_by_id(con, observation["closest_participant_id"])
    )
    return {
        "id": observation["id"],
        "sequence": observation["sequence"],
        "created_at": observation["created_at"],
        "source_type": observation["source_type"],
        "status": observation["status"],
        "participant_id": observation["participant_id"],
        "closest_participant_id": observation["closest_participant_id"],
        "participant": participant,
        "closest_participant": closest,
        "reinforced": bool(observation["reinforced"]),
        "reason_codes": _reason_codes(observation["reason_codes"]),
        "playback_url": f"/api/audio/live-observations/{observation['id']}",
    }


def _render_session(con: sqlite3.Connection, session_row) -> dict:
    participants = con.execute(
        "SELECT * FROM live_identity_participant WHERE session_id=? ORDER BY id",
        (session_row["id"],),
    ).fetchall()
    observations = con.execute(
        "SELECT * FROM live_identity_observation WHERE session_id=? "
        "ORDER BY sequence, id",
        (session_row["id"],),
    ).fetchall()
    return {
        "id": session_row["id"],
        "kind": session_row["kind"],
        "status": session_row["status"],
        "created_at": session_row["created_at"],
        "completed_at": session_row["completed_at"],
        "participants": [_public_participant(row) for row in participants],
        "observations": [_public_observation(con, row) for row in observations],
    }


def _session_row(con: sqlite3.Connection, session_id: int):
    return con.execute(
        "SELECT * FROM live_identity_session WHERE id=?",
        (session_id,),
    ).fetchone()


def create(kind: str = identity.KIND_IMITATION, db_path=None) -> dict:
    """Create an independent live session without modifying existing profiles."""
    if kind not in (identity.KIND_INFANT, identity.KIND_IMITATION):
        return {}
    con = _conn(db_path)
    try:
        cursor = con.execute(
            "INSERT INTO live_identity_session (kind, status, created_at) "
            "VALUES (?,?,?)",
            (kind, SESSION_OPEN, _now()),
        )
        con.commit()
        row = _session_row(con, int(cursor.lastrowid))
        return _render_session(con, row) if row else {}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def get(session_id: int, db_path=None) -> dict:
    """Return a path- and metric-free public snapshot of one session."""
    con = _conn(db_path)
    try:
        row = _session_row(con, session_id)
        return _render_session(con, row) if row else {}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def complete(session_id: int, db_path=None) -> dict:
    """Close a session. Completion is idempotent and never deletes its history."""
    con = _conn(db_path)
    try:
        row = _session_row(con, session_id)
        if not row:
            return {}
        if row["status"] != SESSION_COMPLETED:
            con.execute(
                "UPDATE live_identity_session SET status=?, completed_at=? WHERE id=?",
                (SESSION_COMPLETED, _now(), session_id),
            )
            con.commit()
            row = _session_row(con, session_id)
        return _render_session(con, row)
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def _capture_paths(audio_path: str, capture_metadata: dict | None) -> dict:
    metadata = capture_metadata if isinstance(capture_metadata, dict) else {}
    return {
        "source_type": (
            metadata.get("capture_source")
            or metadata.get("source_type")
            or metadata.get("source")
        ),
        "source_audio_path": (
            metadata.get("source_audio_path")
            or metadata.get("source_path")
            or audio_path
        ),
        "canonical_audio_path": (
            metadata.get("canonical_audio_path")
            or metadata.get("canonical_path")
            or audio_path
        ),
        "identity_audio_path": (
            metadata.get("identity_audio_path")
            or metadata.get("identity_path")
            or audio_path
        ),
        "capture_device_name": (
            metadata.get("capture_device_name")
            or metadata.get("device_name")
            or metadata.get("device")
        ),
    }


def _classification(
    status: str,
    participant=None,
    *,
    reinforced: bool = False,
    reasons=None,
) -> dict:
    return {
        "status": status,
        "participant": _public_participant(participant),
        "reinforced": bool(reinforced),
        "reason_codes": _reason_codes(reasons),
    }


def _result(con, session_row, observation, classification) -> dict:
    refreshed = _session_row(con, session_row["id"])
    return {
        "session": _render_session(con, refreshed),
        "observation": (
            _public_observation(con, observation) if observation is not None else None
        ),
        "classification": classification,
    }


def _insert_observation(
    con,
    session_id: int,
    sequence: int,
    paths: dict,
    digest: str,
    status: str,
    *,
    participant_id=None,
    closest_participant_id=None,
    reinforced=False,
    reasons=None,
    mutation_journal=None,
):
    cursor = con.execute(
        "INSERT INTO live_identity_observation ("
        "session_id, sequence, created_at, source_type, source_audio_path, "
        "canonical_audio_path, identity_audio_path, audio_sha256, status, "
        "participant_id, closest_participant_id, reinforced, reason_codes"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            session_id,
            sequence,
            _now(),
            paths["source_type"],
            paths["source_audio_path"],
            paths["canonical_audio_path"],
            paths["identity_audio_path"],
            digest,
            status,
            participant_id,
            closest_participant_id,
            int(bool(reinforced)),
            json.dumps(_reason_codes(reasons)),
        ),
    )
    observation_id = int(cursor.lastrowid)
    if mutation_journal is not None:
        mutation_journal["observation_ids"].append(observation_id)
    con.commit()
    return con.execute(
        "SELECT * FROM live_identity_observation WHERE id=?",
        (observation_id,),
    ).fetchone()


def _next_sequence(con, session_id: int) -> int:
    row = con.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM live_identity_observation "
        "WHERE session_id=?",
        (session_id,),
    ).fetchone()
    return int(row[0])


def _participants(con, session_id: int):
    return con.execute(
        "SELECT * FROM live_identity_participant WHERE session_id=? ORDER BY id",
        (session_id,),
    ).fetchall()


def _cleanup_failed_profile(profile_id: int, db_path=None) -> None:
    con = _conn(db_path)
    try:
        con.execute("DELETE FROM enrollment WHERE profile_id=?", (profile_id,))
        con.execute("DELETE FROM profile WHERE id=?", (profile_id,))
        con.commit()
    except sqlite3.Error:
        pass
    finally:
        con.close()


def _mutation_journal() -> dict:
    return {
        "created_profile_ids": [],
        "created_participant_ids": [],
        "enrollment_ids": [],
        "profile_statuses": {},
        "participant_states": {},
        "observation_ids": [],
    }


def _remember_enrollment(journal, profile_before, enrollment) -> None:
    if journal is None or enrollment.get("status") != "enrolled":
        return
    enrollment_id = enrollment.get("enrollment_id")
    if enrollment_id is not None:
        journal["enrollment_ids"].append(int(enrollment_id))
    if profile_before:
        journal["profile_statuses"].setdefault(
            int(profile_before["id"]),
            profile_before["status"],
        )


def _rollback_mutations(journal, db_path=None) -> None:
    """Compensate only rows created or changed by the failed submission."""
    if not journal:
        return
    con = _conn(db_path)
    try:
        for observation_id in reversed(journal["observation_ids"]):
            con.execute(
                "DELETE FROM live_identity_observation WHERE id=?",
                (observation_id,),
            )

        created_participants = set(journal["created_participant_ids"])
        for participant_id in reversed(journal["created_participant_ids"]):
            con.execute(
                "DELETE FROM live_identity_participant WHERE id=?",
                (participant_id,),
            )
        for participant_id, state in journal["participant_states"].items():
            if participant_id in created_participants:
                continue
            current = con.execute(
                "SELECT state, support_count, established_at "
                "FROM live_identity_participant WHERE id=?",
                (participant_id,),
            ).fetchone()
            expected = (
                state["state"],
                state["support_count"],
                state["established_at"],
            )
            if current and tuple(current) != expected:
                con.execute(
                    "UPDATE live_identity_participant "
                    "SET state=?, support_count=?, established_at=? WHERE id=?",
                    (*expected, participant_id),
                )

        created_profiles = set(journal["created_profile_ids"])
        for enrollment_id in reversed(journal["enrollment_ids"]):
            con.execute("DELETE FROM enrollment WHERE id=?", (enrollment_id,))
        for profile_id, status in journal["profile_statuses"].items():
            if profile_id in created_profiles:
                continue
            current = con.execute(
                "SELECT status FROM profile WHERE id=?",
                (profile_id,),
            ).fetchone()
            if current and current["status"] != status:
                con.execute(
                    "UPDATE profile SET status=? WHERE id=?",
                    (status, profile_id),
                )
        for profile_id in reversed(journal["created_profile_ids"]):
            con.execute("DELETE FROM enrollment WHERE profile_id=?", (profile_id,))
            con.execute("DELETE FROM profile WHERE id=?", (profile_id,))
        con.commit()
    except sqlite3.Error:
        con.rollback()
    finally:
        con.close()


def _create_participant(
    con,
    session_row,
    paths: dict,
    db_path=None,
    mutation_journal=None,
):
    position = len(_participants(con, session_row["id"])) + 1
    display_name = _label(position)
    profile = identity.create_profile(display_name, session_row["kind"], db_path)
    if not profile:
        return None, ["profile_creation_failed"]
    if mutation_journal is not None:
        mutation_journal["created_profile_ids"].append(int(profile["id"]))
    enrollment = identity.enroll(
        profile["id"],
        paths["identity_audio_path"],
        capture_device_name=paths["capture_device_name"],
        source_type=session_row["kind"],
        db_path=db_path,
        duplicate_profile_scope={
            row["profile_id"]
            for row in _participants(con, session_row["id"])
        },
    )
    _remember_enrollment(mutation_journal, profile, enrollment)
    if enrollment.get("status") != "enrolled":
        _cleanup_failed_profile(profile["id"], db_path)
        return None, [enrollment.get("reason") or "audio_unusable"]
    created_at = _now()
    cursor = con.execute(
        "INSERT INTO live_identity_participant ("
        "session_id, profile_id, display_name, state, support_count, created_at"
        ") VALUES (?,?,?,?,?,?)",
        (
            session_row["id"],
            profile["id"],
            display_name,
            PARTICIPANT_PROVISIONAL,
            1,
            created_at,
        ),
    )
    participant_id = int(cursor.lastrowid)
    if mutation_journal is not None:
        mutation_journal["created_participant_ids"].append(participant_id)
    con.commit()
    return _participant_by_id(con, participant_id), ["new_participant"]


def _reinforce(
    con,
    participant,
    paths: dict,
    session_kind: str,
    db_path=None,
    mutation_journal=None,
):
    profile_before = identity.get_profile(participant["profile_id"], db_path)
    enrollment = identity.enroll(
        participant["profile_id"],
        paths["identity_audio_path"],
        capture_device_name=paths["capture_device_name"],
        source_type=session_kind,
        db_path=db_path,
        duplicate_profile_scope={
            row["profile_id"]
            for row in _participants(con, participant["session_id"])
        },
    )
    _remember_enrollment(mutation_journal, profile_before, enrollment)
    if enrollment.get("status") != "enrolled":
        return None, [enrollment.get("reason") or "enrollment_failed"]
    if mutation_journal is not None:
        mutation_journal["participant_states"].setdefault(
            int(participant["id"]),
            {
                "state": participant["state"],
                "support_count": int(participant["support_count"]),
                "established_at": participant["established_at"],
            },
        )
    support_count = int(participant["support_count"]) + 1
    state = (
        PARTICIPANT_ESTABLISHED
        if support_count >= 2
        else PARTICIPANT_PROVISIONAL
    )
    established_at = (
        participant["established_at"]
        or (_now() if state == PARTICIPANT_ESTABLISHED else None)
    )
    con.execute(
        "UPDATE live_identity_participant "
        "SET support_count=?, state=?, established_at=? WHERE id=?",
        (support_count, state, established_at, participant["id"]),
    )
    con.commit()
    return _participant_by_id(con, participant["id"]), ["participant_reinforced"]


def _pair_evidence(
    con: sqlite3.Connection,
    session_id: int,
    participants,
    query_path: str,
    kind: str,
    db_path=None,
):
    """Batch existing and pending references into one score-free comparison."""
    compared_participants = []
    pending = _pending_observations(con, session_id)
    reference_paths = []
    for participant in participants:
        references = identity.profile_reference_audio(participant["profile_id"], db_path)
        for reference_path in references:
            compared_participants.append(participant)
            reference_paths.append(reference_path)
    reference_paths.extend(
        observation["identity_audio_path"]
        for observation in pending
    )
    results = identity.recordings_consistent_many(
        reference_paths,
        query_path,
        kind,
        db_path,
    )
    participant_count = len(compared_participants)
    return (
        list(zip(compared_participants, results[:participant_count])),
        list(zip(pending, results[participant_count:])),
    )


def _unique_consistent_participant(pair_results):
    """Return the one participant supported by pair evidence, or abstain."""
    consistent = {
        participant["id"]: participant
        for participant, result in pair_results
        if result.get("consistent")
    }
    return next(iter(consistent.values())) if len(consistent) == 1 else None


def _safe_novel(pair_results) -> bool:
    if not pair_results:
        return False
    for _, result in pair_results:
        reasons = set(_reason_codes(result.get("reasons")))
        if result.get("consistent"):
            return False
        if "novelty_pair_inconsistent" not in reasons:
            return False
    return True


def _pair_unusable(pair_results) -> bool:
    unusable_reasons = {
        "missing_audio",
        "no_usable_voiced_audio",
        "novelty_pair_audio_unusable",
    }
    return any(
        unusable_reasons.intersection(_reason_codes(result.get("reasons")))
        for _, result in pair_results
    )


def _pending_observations(con: sqlite3.Connection, session_id: int):
    """Return unresolved outlier evidence that has not since been enrolled."""
    rows = con.execute(
        "SELECT observation.* FROM live_identity_observation observation "
        "WHERE observation.session_id=? "
        "AND observation.participant_id IS NULL "
        "AND observation.reinforced=0 "
        "AND observation.status IN ('possible_new', 'leaning') "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM enrollment "
        "  JOIN live_identity_participant participant "
        "    ON participant.profile_id=enrollment.profile_id "
        "  WHERE participant.session_id=observation.session_id "
        "    AND enrollment.audio_sha256=observation.audio_sha256"
        ") ORDER BY observation.sequence, observation.id",
        (session_id,),
    ).fetchall()
    return [
        row
        for row in rows
        if PENDING_NOVELTY_REASON in _reason_codes(row["reason_codes"])
    ]


def _unique_consistent_pending(pending_pair_results):
    """Return one prior pending observation supported by the new recording."""
    consistent = [
        observation
        for observation, result in pending_pair_results
        if result.get("consistent")
    ]
    return consistent[0] if len(consistent) == 1 else None


def _paths_from_observation(observation) -> dict:
    return {
        "source_type": observation["source_type"],
        "source_audio_path": observation["source_audio_path"],
        "canonical_audio_path": observation["canonical_audio_path"],
        "identity_audio_path": observation["identity_audio_path"],
        "capture_device_name": None,
    }


def _create_participant_from_pending(
    con: sqlite3.Connection,
    session_row,
    pending_observation,
    current_paths: dict,
    db_path=None,
    mutation_journal=None,
):
    """Create one established participant from two separately stored recordings."""
    participant, create_reasons = _create_participant(
        con,
        session_row,
        _paths_from_observation(pending_observation),
        db_path,
        mutation_journal,
    )
    if not participant:
        return None, create_reasons
    established, reinforce_reasons = _reinforce(
        con,
        participant,
        current_paths,
        session_row["kind"],
        db_path,
        mutation_journal,
    )
    if established:
        return established, [
            "pending_outlier_pair_consistent",
            *create_reasons,
            *reinforce_reasons,
        ]

    con.execute(
        "DELETE FROM live_identity_participant WHERE id=?",
        (participant["id"],),
    )
    con.commit()
    _cleanup_failed_profile(participant["profile_id"], db_path)
    return None, [*create_reasons, *reinforce_reasons]


def _closest_from_candidates(participants, candidates):
    by_profile = {row["profile_id"]: row for row in participants}
    for candidate in candidates or []:
        participant = by_profile.get(candidate.get("profile_id"))
        if participant:
            return participant
    return None


def submit_observation(
    session_id: int,
    audio_path: str,
    capture_metadata: dict | None = None,
    db_path=None,
) -> dict:
    """Store one observation and advance session identity only on strong evidence."""
    con = _conn(db_path)
    mutation_journal = _mutation_journal()
    try:
        session_row = _session_row(con, session_id)
        if not session_row:
            return {}
        if session_row["status"] == SESSION_COMPLETED:
            return _result(
                con,
                session_row,
                None,
                _classification(
                    "session_completed",
                    reasons=["session_completed"],
                ),
            )

        paths = _capture_paths(audio_path, capture_metadata)
        identity_path = paths["identity_audio_path"]
        if not identity_path or not os.path.isfile(identity_path):
            return _result(
                con,
                session_row,
                None,
                _classification("invalid", reasons=["missing_audio"]),
            )
        digest = _sha256(identity_path)
        if not digest:
            return _result(
                con,
                session_row,
                None,
                _classification("invalid", reasons=["missing_audio"]),
            )

        sequence = _next_sequence(con, session_id)
        duplicate = con.execute(
            "SELECT * FROM live_identity_observation "
            "WHERE session_id=? AND audio_sha256=? ORDER BY sequence LIMIT 1",
            (session_id, digest),
        ).fetchone()
        if duplicate:
            participant_id = duplicate["participant_id"]
            closest_participant_id = duplicate["closest_participant_id"]
            participant = _participant_by_id(con, participant_id)
            if duplicate["status"] == "invalid":
                reasons = _reason_codes(duplicate["reason_codes"]) or ["audio_unusable"]
                observation = _insert_observation(
                    con,
                    session_id,
                    sequence,
                    paths,
                    digest,
                    "invalid",
                    participant_id=participant_id,
                    closest_participant_id=closest_participant_id,
                    reasons=reasons,
                    mutation_journal=mutation_journal,
                )
                return _result(
                    con,
                    session_row,
                    observation,
                    _classification("invalid", participant, reasons=reasons),
                )
            observation = _insert_observation(
                con,
                session_id,
                sequence,
                paths,
                digest,
                "duplicate",
                participant_id=participant_id,
                closest_participant_id=closest_participant_id,
                reasons=["duplicate_audio"],
                mutation_journal=mutation_journal,
            )
            return _result(
                con,
                session_row,
                observation,
                _classification(
                    "duplicate",
                    participant,
                    reasons=["duplicate_audio"],
                ),
            )

        participants = _participants(con, session_id)
        if not participants:
            participant, reasons = _create_participant(
                con,
                session_row,
                paths,
                db_path,
                mutation_journal,
            )
            if participant:
                status = "provisional_created"
                participant_id = participant["id"]
            else:
                status = "invalid"
                participant_id = None
            observation = _insert_observation(
                con,
                session_id,
                sequence,
                paths,
                digest,
                status,
                participant_id=participant_id,
                reasons=reasons,
                mutation_journal=mutation_journal,
            )
            return _result(
                con,
                session_row,
                observation,
                _classification(status, participant, reasons=reasons),
            )

        pair_results = None
        pending_pair_results = None
        if (
            len(participants) == 1
            or any(
                participant["state"] == PARTICIPANT_PROVISIONAL
                for participant in participants
            )
        ):
            pair_results, pending_pair_results = _pair_evidence(
                con,
                session_id,
                participants,
                identity_path,
                session_row["kind"],
                db_path,
            )
        pair_consistent = _unique_consistent_participant(pair_results or [])
        pending_consistent = any(
            result.get("consistent")
            for _, result in (pending_pair_results or [])
        )
        if pair_consistent and not pending_consistent and (
            len(participants) == 1
            or pair_consistent["state"] == PARTICIPANT_PROVISIONAL
        ):
            participant, reasons = _reinforce(
                con,
                pair_consistent,
                paths,
                session_row["kind"],
                db_path,
                mutation_journal,
            )
            if participant:
                status = "participant"
                reinforced = True
            else:
                status = "invalid"
                reinforced = False
            observation = _insert_observation(
                con,
                session_id,
                sequence,
                paths,
                digest,
                status,
                participant_id=participant["id"] if participant else None,
                closest_participant_id=pair_consistent["id"],
                reinforced=reinforced,
                reasons=reasons,
                mutation_journal=mutation_journal,
            )
            return _result(
                con,
                session_row,
                observation,
                _classification(
                    status,
                    participant or pair_consistent,
                    reinforced=reinforced,
                    reasons=reasons,
                ),
            )

        if len(participants) == 1 and _pair_unusable(pair_results or []):
            reasons = [
                reason
                for _, pair in (pair_results or [])
                for reason in _reason_codes(pair.get("reasons"))
            ]
            observation = _insert_observation(
                con,
                session_id,
                sequence,
                paths,
                digest,
                "invalid",
                closest_participant_id=participants[0]["id"],
                reasons=reasons,
                mutation_journal=mutation_journal,
            )
            return _result(
                con,
                session_row,
                observation,
                _classification("invalid", participants[0], reasons=reasons),
            )

        profile_ids = [participant["profile_id"] for participant in participants]
        identified = identity.identify_within_profiles(
            identity_path,
            profile_ids,
            session_row["kind"],
            db_path,
        )
        reasons = _reason_codes(identified.get("reasons"))
        by_profile = {row["profile_id"]: row for row in participants}
        closest = _closest_from_candidates(
            participants,
            identified.get("candidates"),
        )

        if identified.get("status") == identity.STATUS_MATCH:
            known = by_profile.get(identified.get("profile_id"))
            if known:
                participant, reinforce_reasons = _reinforce(
                    con,
                    known,
                    paths,
                    session_row["kind"],
                    db_path,
                    mutation_journal,
                )
                reasons = reasons + reinforce_reasons
                status = "participant" if participant else "invalid"
                reinforced = participant is not None
                observation = _insert_observation(
                    con,
                    session_id,
                    sequence,
                    paths,
                    digest,
                    status,
                    participant_id=participant["id"] if participant else None,
                    closest_participant_id=known["id"],
                    reinforced=reinforced,
                    reasons=reasons,
                    mutation_journal=mutation_journal,
                )
                return _result(
                    con,
                    session_row,
                    observation,
                    _classification(
                        status,
                        participant or known,
                        reinforced=reinforced,
                        reasons=reasons,
                    ),
                )

        if identified.get("status") == identity.STATUS_INVALID:
            observation = _insert_observation(
                con,
                session_id,
                sequence,
                paths,
                digest,
                "invalid",
                closest_participant_id=closest["id"] if closest else None,
                reasons=reasons or ["audio_unusable"],
                mutation_journal=mutation_journal,
            )
            return _result(
                con,
                session_row,
                observation,
                _classification(
                    "invalid",
                    closest,
                    reasons=reasons or ["audio_unusable"],
                ),
            )

        pending_novelty = False
        novel_reasons = {"below_accept_threshold", "new_or_unenrolled_source"}
        if novel_reasons.intersection(reasons):
            if pair_results is None:
                pair_results, pending_pair_results = _pair_evidence(
                    con,
                    session_id,
                    participants,
                    identity_path,
                    session_row["kind"],
                    db_path,
                )
            if _safe_novel(pair_results):
                pending = _unique_consistent_pending(
                    pending_pair_results or [],
                )
                if pending:
                    participant, create_reasons = _create_participant_from_pending(
                        con,
                        session_row,
                        pending,
                        paths,
                        db_path,
                        mutation_journal,
                    )
                    reasons = reasons + create_reasons
                    status = "participant" if participant else "invalid"
                    observation = _insert_observation(
                        con,
                        session_id,
                        sequence,
                        paths,
                        digest,
                        status,
                        participant_id=participant["id"] if participant else None,
                        reinforced=participant is not None,
                        reasons=reasons,
                        mutation_journal=mutation_journal,
                    )
                    return _result(
                        con,
                        session_row,
                        observation,
                        _classification(
                            status,
                            participant,
                            reinforced=participant is not None,
                            reasons=reasons,
                        ),
                    )
                reasons = reasons + [PENDING_NOVELTY_REASON]
                pending_novelty = True

        status = (
            "possible_new"
            if (
                len(participants) == 1
                or (
                    pending_novelty
                    and len(participants) < MIN_POOL_FOR_PENDING_DIRECTION
                )
            )
            else ("leaning" if closest else "possible_new")
        )
        observation = _insert_observation(
            con,
            session_id,
            sequence,
            paths,
            digest,
            status,
            closest_participant_id=closest["id"] if closest else None,
            reasons=reasons or ["insufficient_identity_evidence"],
            mutation_journal=mutation_journal,
        )
        return _result(
            con,
            session_row,
            observation,
            _classification(
                status,
                closest,
                reasons=reasons or ["insufficient_identity_evidence"],
            ),
        )
    except (sqlite3.Error, TypeError, ValueError):
        try:
            con.rollback()
        except sqlite3.Error:
            pass
        _rollback_mutations(mutation_journal, db_path)
        return {}
    finally:
        con.close()


def observation_audio_path(observation_id: int, db_path=None) -> str | None:
    """Resolve the stored canonical playback file without exposing it publicly."""
    con = _conn(db_path)
    try:
        row = con.execute(
            "SELECT canonical_audio_path, identity_audio_path "
            "FROM live_identity_observation WHERE id=?",
            (observation_id,),
        ).fetchone()
        if not row:
            return None
        return row["canonical_audio_path"] or row["identity_audio_path"]
    except sqlite3.Error:
        return None
    finally:
        con.close()
