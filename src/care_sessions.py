"""Persistent infant care-session state with safe public snapshots."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import careflow, config, context, cry_gate, identity, session, store
except ImportError:
    import careflow
    import config
    import context
    import cry_gate
    import identity
    import session
    import store


LISTENING = "listening"
PAUSED = "paused"
AWAITING_OUTCOME = "awaiting_outcome"
COMPLETE = "complete"
DISCARDED = "discarded"

_ALLOWED = {
    (LISTENING, "pause"): PAUSED,
    (PAUSED, "resume"): LISTENING,
    (LISTENING, "stop"): AWAITING_OUTCOME,
    (PAUSED, "stop"): AWAITING_OUTCOME,
}

_CHUNK_INFERENCE_CLAIMS_LOCK = threading.Lock()
_CHUNK_INFERENCE_CLAIMS: dict[tuple[str, int, int], threading.Event] = {}
_SESSION_MUTATION_LOCKS_LOCK = threading.Lock()
_SESSION_MUTATION_LOCKS: dict[tuple[str, int], threading.Lock] = {}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _conn(db_path: str | None = None) -> sqlite3.Connection:
    store.init_db(db_path)
    connection = sqlite3.connect(db_path or config.DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _error(reason: str) -> dict:
    return {"status": "error", "reason": reason}


def _normalize_tags(tags: list[str] | None) -> list[str]:
    normalized = []
    seen = set()
    for value in tags or []:
        if not isinstance(value, str):
            continue
        tag = value.strip().casefold()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)
        if len(normalized) == 20:
            break
    return normalized


def _decoded_list(raw) -> list:
    try:
        value = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    return value if isinstance(value, list) else []


def _is_integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _database_key(db_path: str | None) -> str:
    raw_path = db_path or config.DB_PATH
    try:
        return str(Path(raw_path).resolve())
    except (OSError, RuntimeError, TypeError, ValueError):
        return str(raw_path)


def _session_mutation_lock(
    db_path: str | None,
    session_id: int,
) -> threading.Lock:
    key = (_database_key(db_path), session_id)
    with _SESSION_MUTATION_LOCKS_LOCK:
        lock = _SESSION_MUTATION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _SESSION_MUTATION_LOCKS[key] = lock
        return lock


def _string_fields(value, field_names: tuple[str, ...]) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        field: value[field]
        for field in field_names
        if isinstance(value.get(field), str)
    }


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _public_decision_profile(value) -> dict:
    public = _string_fields(value, ("display_name",))
    if isinstance(value, dict) and _is_integer(value.get("id")):
        public["id"] = value["id"]
    return public


def _public_guidance(value) -> dict:
    public = _string_fields(
        value,
        (
            "status",
            "headline",
            "interpretation",
            "recommendation",
            "evidence_summary",
            "pattern",
        ),
    )
    if not isinstance(value, dict):
        return public
    if _is_integer(value.get("support_count")):
        public["support_count"] = value["support_count"]
    if isinstance(value.get("incident_ids"), list):
        public["incident_ids"] = [
            item for item in value["incident_ids"] if _is_integer(item)
        ]
    return public


def _public_intervention(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    if (
        not _is_integer(value.get("order"))
        or not isinstance(value.get("action"), str)
        or not isinstance(value.get("evidence"), str)
    ):
        return None
    return {
        "order": value["order"],
        "action": value["action"],
        "evidence": value["evidence"],
    }


def _public_audio_url(value, profile_id: int, episode_id: int) -> str | None:
    del value
    if not _is_integer(profile_id) or not _is_integer(episode_id):
        return None
    return f"/api/profiles/{profile_id}/incidents/{episode_id}/audio"


def _public_scenario(value, profile_id: int) -> dict | None:
    if not isinstance(value, dict) or not _is_integer(value.get("episode_id")):
        return None
    public = {"episode_id": value["episode_id"]}
    public.update(_string_fields(value, ("started_at",)))
    if isinstance(value.get("interventions"), list):
        public["interventions"] = [
            intervention
            for item in value["interventions"]
            if (intervention := _public_intervention(item)) is not None
        ]
    for field in ("outcome", "outcome_src"):
        field_value = value.get(field)
        if field in value and (field_value is None or isinstance(field_value, str)):
            public[field] = field_value
    worked = value.get("worked")
    if "worked" in value and (worked is None or isinstance(worked, bool)):
        public["worked"] = worked
    if isinstance(value.get("contributions"), list):
        public["contributions"] = _string_list(value["contributions"])
    audio_url = _public_audio_url(
        value.get("audio_url"),
        profile_id,
        value["episode_id"],
    )
    if audio_url is not None:
        public["audio_url"] = audio_url
    return public


def _public_decision(value) -> dict:
    public = {}
    if _is_integer(value.get("id")):
        public["id"] = value["id"]
    if isinstance(value.get("latched_at"), str):
        public["latched_at"] = value["latched_at"]
    profile_id = None
    if isinstance(value.get("profile"), dict):
        public["profile"] = _public_decision_profile(value["profile"])
        if _is_integer(public["profile"].get("id")):
            profile_id = public["profile"]["id"]
    if isinstance(value.get("guidance"), dict):
        public["guidance"] = _public_guidance(value["guidance"])
    if isinstance(value.get("basis"), list):
        public["basis"] = _string_list(value["basis"])
    if isinstance(value.get("scenarios"), list) and profile_id is not None:
        public["scenarios"] = [
            scenario
            for item in value["scenarios"]
            if (scenario := _public_scenario(item, profile_id)) is not None
        ]
    return public


def _decoded_decision(raw):
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return _public_decision(value) if isinstance(value, dict) else None


def _public_profile(profile: dict) -> dict:
    return {
        "id": profile["id"],
        "display_name": profile["display_name"],
        "kind": profile["kind"],
        "status": profile["status"],
        "enrollments": profile["enrollments"],
    }


def _session_row(
    connection: sqlite3.Connection,
    session_id: int,
):
    return connection.execute(
        "SELECT * FROM care_session WHERE id=?",
        (session_id,),
    ).fetchone()


def _render_with_profile(row, profile: dict) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "profile": _public_profile(profile),
        "started_at": row["created_at"],
        "paused_at": row["paused_at"],
        "stopped_at": row["stopped_at"],
        "completed_at": row["completed_at"],
        "last_sequence": row["last_sequence"],
        "tags": _decoded_list(row["tags_json"]),
        "decision": _decoded_decision(row["decision_json"]),
    }


def _render(row, db_path: str | None = None) -> dict:
    profile = identity.get_profile(row["profile_id"], db_path)
    return _render_with_profile(row, profile)


def create(
    profile_id: int,
    tags: list[str] | None = None,
    db_path: str | None = None,
) -> dict:
    """Start a persistent session for one active infant profile."""
    profile = identity.get_profile(profile_id, db_path)
    if (
        not profile
        or profile.get("kind") != identity.KIND_INFANT
        or profile.get("status") == "archived"
    ):
        return _error("invalid_care_session_profile")
    connection = _conn(db_path)
    try:
        cursor = connection.execute(
            "INSERT INTO care_session ("
            "profile_id, status, created_at, last_sequence, tags_json"
            ") VALUES (?,?,?,?,?)",
            (
                profile_id,
                LISTENING,
                _now(),
                0,
                json.dumps(_normalize_tags(tags)),
            ),
        )
        connection.commit()
        row = _session_row(connection, int(cursor.lastrowid))
        return _render(row, db_path)
    except sqlite3.Error:
        return _error("care_session_storage_error")
    finally:
        connection.close()


def get(session_id: int, db_path: str | None = None) -> dict:
    """Return one path-free and metric-free public session snapshot."""
    connection = _conn(db_path)
    try:
        row = _session_row(connection, session_id)
        return _render(row, db_path) if row else _error("no_such_care_session")
    except sqlite3.Error:
        return _error("care_session_storage_error")
    finally:
        connection.close()


def _transition(
    session_id: int,
    operation: str,
    db_path: str | None = None,
) -> dict:
    connection = _conn(db_path)
    try:
        row = _session_row(connection, session_id)
        if not row:
            return _error("no_such_care_session")
        if operation == "stop" and row["status"] == AWAITING_OUTCOME:
            return _render(row, db_path)
        next_status = _ALLOWED.get((row["status"], operation))
        if not next_status:
            return _error("invalid_care_session_transition")
        fields = ["status=?"]
        values = [next_status]
        if operation == "pause":
            fields.append("paused_at=?")
            values.append(_now())
        elif operation == "stop":
            fields.append("stopped_at=?")
            values.append(_now())
        values.extend((session_id, row["status"]))
        cursor = connection.execute(
            f"UPDATE care_session SET {','.join(fields)} "
            "WHERE id=? AND status=?",
            values,
        )
        if cursor.rowcount != 1:
            connection.rollback()
            current = _session_row(connection, session_id)
            if (
                operation == "stop"
                and current
                and current["status"] == AWAITING_OUTCOME
            ):
                return _render(current, db_path)
            return _error("invalid_care_session_transition")
        connection.commit()
        updated = _session_row(connection, session_id)
        return _render(updated, db_path)
    except sqlite3.Error:
        connection.rollback()
        return _error("care_session_storage_error")
    finally:
        connection.close()


def pause(session_id: int, db_path: str | None = None) -> dict:
    """Pause a listening care session."""
    return _transition(session_id, "pause", db_path)


def resume(session_id: int, db_path: str | None = None) -> dict:
    """Resume a paused care session."""
    return _transition(session_id, "resume", db_path)


def stop(session_id: int, db_path: str | None = None) -> dict:
    """Stop capture and await the structured caregiver outcome."""
    return _transition(session_id, "stop", db_path)


def _episode_for_care_session(
    profile_id: int,
    session_id: int,
    db_path: str | None,
) -> dict | None:
    subject_id = f"profile-{profile_id}"
    for episode in store.list_episodes(subject_id, db_path):
        episode_context = episode.get("context")
        if (
            isinstance(episode_context, dict)
            and type(episode_context.get("care_session_id")) is int
            and episode_context["care_session_id"] == session_id
        ):
            return episode
    return None


def _completed_result(row, episode_id: int, db_path: str | None) -> dict:
    profile_id = row["profile_id"]
    return {
        "session": _render(row, db_path),
        "incident": {
            "id": episode_id,
            "detail_url": (
                f"/api/profiles/{profile_id}/incidents/{episode_id}"
            ),
        },
    }


def _completion_precheck(
    session_id: int,
    db_path: str | None,
) -> tuple[dict | None, dict | None]:
    connection = _conn(db_path)
    try:
        row = _session_row(connection, session_id)
        if not row:
            return _error("no_such_care_session"), None
        if _is_integer(row["episode_id"]):
            return _completed_result(row, row["episode_id"], db_path), None
        existing = _episode_for_care_session(
            row["profile_id"],
            session_id,
            db_path,
        )
        return None, existing
    except sqlite3.Error:
        return _error("care_session_storage_error"), None
    finally:
        connection.close()


def _representative_chunk(connection: sqlite3.Connection, row):
    chunk_id = (
        row["selected_chunk_id"]
        if _is_integer(row["selected_chunk_id"])
        else row["latest_matched_chunk_id"]
    )
    if not _is_integer(chunk_id):
        return None
    return connection.execute(
        "SELECT id, created_at, canonical_audio_path "
        "FROM care_session_chunk "
        "WHERE id=? AND session_id=? AND matched_profile_id=?",
        (chunk_id, row["id"], row["profile_id"]),
    ).fetchone()


def _attach_completed_episode(
    session_id: int,
    episode_id: int,
    db_path: str | None,
) -> bool:
    connection = _conn(db_path)
    try:
        cursor = connection.execute(
            "UPDATE care_session SET status=?, completed_at=?, episode_id=? "
            "WHERE id=? AND status=? AND episode_id IS NULL",
            (COMPLETE, _now(), episode_id, session_id, AWAITING_OUTCOME),
        )
        if cursor.rowcount == 1:
            connection.commit()
            return True
        connection.rollback()
        row = _session_row(connection, session_id)
        return bool(
            row
            and row["status"] == COMPLETE
            and row["episode_id"] == episode_id
        )
    except sqlite3.Error:
        connection.rollback()
        return False
    finally:
        connection.close()


def _finish_existing_episode(
    session_id: int,
    episode: dict,
    db_path: str | None,
) -> dict:
    episode_id = episode.get("id") if isinstance(episode, dict) else None
    if not _is_integer(episode_id):
        return _error("incident_save_failed")
    if not _attach_completed_episode(session_id, episode_id, db_path):
        return _error("care_session_storage_error")
    connection = _conn(db_path)
    try:
        row = _session_row(connection, session_id)
        if not row or row["episode_id"] != episode_id:
            return _error("care_session_storage_error")
        return _completed_result(row, episode_id, db_path)
    finally:
        connection.close()


def _complete_claimed(
    session_id: int,
    action: str,
    settled: bool | None,
    notes: str | None,
    tags: list[str] | None,
    db_path: str | None,
) -> dict:
    connection = _conn(db_path)
    try:
        row = _session_row(connection, session_id)
        if not row:
            return _error("no_such_care_session")
        if _is_integer(row["episode_id"]):
            return _completed_result(row, row["episode_id"], db_path)
        if row["status"] != AWAITING_OUTCOME:
            return _error("invalid_care_session_transition")

        existing = _episode_for_care_session(
            row["profile_id"],
            session_id,
            db_path,
        )
        if existing is not None:
            return _finish_existing_episode(session_id, existing, db_path)

        if (
            not isinstance(action, str)
            or not action.strip()
            or len(action.strip()) > 500
            or (settled is not None and type(settled) is not bool)
            or (notes is not None and not isinstance(notes, str))
            or (isinstance(notes, str) and len(notes.strip()) > 1000)
            or (
                tags is not None
                and (
                    not isinstance(tags, list)
                    or any(not isinstance(tag, str) for tag in tags)
                )
            )
        ):
            return _error("invalid_care_session_completion")

        chunk = _representative_chunk(connection, row)
        if chunk is None:
            return _error("no_matched_chunk")
        canonical_audio = chunk["canonical_audio_path"]
        if (
            not isinstance(canonical_audio, str)
            or not Path(canonical_audio).is_file()
        ):
            return _error("managed_capture_unavailable")
        started_at = chunk["created_at"]
        if not isinstance(started_at, str) or not started_at:
            return _error("care_session_storage_error")
        merged_tags = _normalize_tags(
            _decoded_list(row["tags_json"]) + (tags or [])
        )
        current_context = context.build_current_context(
            row["profile_id"],
            now=started_at,
            tags=merged_tags,
            db_path=db_path,
        )
        if not current_context:
            return _error("context_unavailable")
        episode_context = {
            **current_context,
            "care_session_id": session_id,
            "selected_chunk_id": chunk["id"],
            "profile_id": row["profile_id"],
        }
        profile_id = row["profile_id"]
    except sqlite3.Error:
        return _error("care_session_storage_error")
    finally:
        connection.close()

    episode = session.finish_structured(
        f"profile-{profile_id}",
        canonical_audio,
        action,
        settled,
        notes,
        started_at=started_at,
        db_path=db_path,
        context_override=episode_context,
    )
    episode_id = episode.get("id") if isinstance(episode, dict) else None
    if not _is_integer(episode_id):
        return _error("incident_save_failed")
    if _attach_completed_episode(session_id, episode_id, db_path):
        connection = _conn(db_path)
        try:
            completed = _session_row(connection, session_id)
            if completed and completed["episode_id"] == episode_id:
                return _completed_result(completed, episode_id, db_path)
        finally:
            connection.close()

    recovered = _episode_for_care_session(profile_id, session_id, db_path)
    if recovered is None:
        return _error("care_session_storage_error")
    return _finish_existing_episode(session_id, recovered, db_path)


def complete(
    session_id: int,
    action: str,
    settled: bool | None,
    notes: str | None = None,
    tags: list[str] | None = None,
    db_path: str | None = None,
) -> dict:
    """Save exactly one incident for a stopped session in this server process.

    The process lock coordinates completion and discard. Persistent context lookup
    recovers a saved episode after an interrupted attach, but cross-process
    exactly-once behavior would require schema-level uniqueness.
    """
    if not _is_integer(session_id) or session_id <= 0:
        return _error("no_such_care_session")
    try:
        prechecked, _ = _completion_precheck(session_id, db_path)
    except Exception:
        return _error("care_session_storage_error")
    if prechecked is not None:
        return prechecked
    with _session_mutation_lock(db_path, session_id):
        try:
            return _complete_claimed(
                session_id,
                action,
                settled,
                notes,
                tags,
                db_path,
            )
        except Exception:
            return _error("care_session_storage_error")


_CHUNK_STATUSES = {
    "invalid",
    "no_cry_detected",
    "cry_uncertain",
    "not_selected_profile",
    "matched_no_guidance",
    "guidance_latched",
    "matched_guidance_already_latched",
}

_CRY_PUBLIC_KEYS = {
    "status",
    "label",
    "reason_codes",
    "analyzed_duration_s",
    "analysis_view_count",
    "model_version",
}


def _source_digest(raw_path) -> str | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    digest = hashlib.sha256()
    try:
        with open(raw_path, "rb") as source:
            for block in iter(lambda: source.read(65536), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _public_cry_presence(value) -> dict:
    if not isinstance(value, dict):
        return {}
    public = {}
    for key in ("status", "model_version"):
        if isinstance(value.get(key), str):
            public[key] = value[key]
    label = value.get("label")
    if "label" in value and (label is None or isinstance(label, str)):
        public["label"] = label
    if isinstance(value.get("reason_codes"), list):
        public["reason_codes"] = _string_list(value["reason_codes"])
    duration = value.get("analyzed_duration_s")
    if (
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
    ):
        public["analyzed_duration_s"] = duration
    view_count = value.get("analysis_view_count")
    if _is_integer(view_count):
        public["analysis_view_count"] = view_count
    return {
        key: public[key]
        for key in value
        if key in _CRY_PUBLIC_KEYS and key in public
    }


def _public_stored_profile(value) -> dict:
    if not isinstance(value, dict):
        return {}
    public = _string_fields(value, ("display_name", "kind", "status"))
    for field in ("id", "enrollments"):
        if _is_integer(value.get(field)):
            public[field] = value[field]
    return public


def _public_stored_session(value) -> dict:
    if not isinstance(value, dict) or not _is_integer(value.get("id")):
        return {}
    public = {"id": value["id"]}
    if isinstance(value.get("status"), str):
        public["status"] = value["status"]
    if isinstance(value.get("profile"), dict):
        public["profile"] = _public_stored_profile(value["profile"])
    for field in ("started_at", "paused_at", "stopped_at", "completed_at"):
        item = value.get(field)
        if field in value and (item is None or isinstance(item, str)):
            public[field] = item
    if _is_integer(value.get("last_sequence")):
        public["last_sequence"] = value["last_sequence"]
    if isinstance(value.get("tags"), list):
        public["tags"] = _string_list(value["tags"])
    decision = value.get("decision")
    if decision is None:
        public["decision"] = None
    elif isinstance(decision, dict):
        public["decision"] = _public_decision(decision)
    return public


def _public_chunk(value) -> dict:
    if not isinstance(value, dict):
        return {}
    public = {}
    for field in ("id", "sequence"):
        if _is_integer(value.get(field)):
            public[field] = value[field]
    if value.get("status") in _CHUNK_STATUSES:
        public["status"] = value["status"]
    if isinstance(value.get("created_at"), str):
        public["created_at"] = value["created_at"]
    if isinstance(value.get("reason_codes"), list):
        public["reason_codes"] = _string_list(value["reason_codes"])
    cry_presence = _public_cry_presence(value.get("cry_presence"))
    if cry_presence:
        public["cry_presence"] = cry_presence
    return public


def _public_chunk_result(value) -> dict:
    if not isinstance(value, dict):
        return {}
    session = _public_stored_session(value.get("session"))
    chunk = _public_chunk(value.get("chunk"))
    if not session or not chunk:
        return {}
    return {"session": session, "chunk": chunk}


def _decoded_chunk_result(raw) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}
    return _public_chunk_result(value)


def _existing_chunk(connection, session_id: int, sequence: int):
    return connection.execute(
        "SELECT * FROM care_session_chunk WHERE session_id=? AND sequence=?",
        (session_id, sequence),
    ).fetchone()


def _sequence_resolution(
    connection: sqlite3.Connection,
    row,
    sequence: int,
    digest: str | None,
) -> dict | None:
    if sequence <= row["last_sequence"]:
        existing = _existing_chunk(connection, row["id"], sequence)
        if (
            existing
            and digest is not None
            and existing["audio_sha256"] == digest
        ):
            stored = _decoded_chunk_result(existing["result_json"])
            return stored or _error("care_session_storage_error")
        return _error("sequence_conflict")
    if sequence != row["last_sequence"] + 1:
        return _error("out_of_order_chunk")
    return None


def _reason_codes(value, fallback: str) -> list[str]:
    if isinstance(value, list):
        codes = _string_list(value)
        if codes:
            return codes
    return [fallback]


def _latched_decision(
    chunk_id: int,
    created_at: str,
    profile: dict,
    preview: dict,
) -> dict:
    guidance_payload = _public_guidance(preview.get("guidance"))
    incident_ids = set(guidance_payload.get("incident_ids") or [])
    scenarios = []
    for item in preview.get("scenarios") or []:
        scenario = _public_scenario(item, profile["id"])
        if (
            scenario is not None
            and scenario["episode_id"] in incident_ids
        ):
            scenarios.append(scenario)
    basis = []
    seen = set()
    for scenario in scenarios:
        for contribution in scenario.get("contributions") or []:
            if contribution not in seen:
                seen.add(contribution)
                basis.append(contribution)
    return _public_decision(
        {
            "id": chunk_id,
            "latched_at": created_at,
            "profile": {
                "id": profile["id"],
                "display_name": profile["display_name"],
            },
            "guidance": guidance_payload,
            "basis": basis,
            "scenarios": scenarios,
        }
    )


def _chunk_claim_key(
    db_path: str | None,
    session_id: int,
    sequence: int,
) -> tuple[str, int, int]:
    raw_path = db_path or config.DB_PATH
    try:
        database = str(Path(raw_path).resolve())
    except (OSError, RuntimeError, TypeError, ValueError):
        database = str(raw_path)
    return database, session_id, sequence


def _claim_chunk_inference(
    key: tuple[str, int, int],
) -> tuple[bool, threading.Event]:
    with _CHUNK_INFERENCE_CLAIMS_LOCK:
        existing = _CHUNK_INFERENCE_CLAIMS.get(key)
        if existing is not None:
            return False, existing
        completed = threading.Event()
        _CHUNK_INFERENCE_CLAIMS[key] = completed
        return True, completed


def _release_chunk_inference(
    key: tuple[str, int, int],
    completed: threading.Event,
) -> None:
    with _CHUNK_INFERENCE_CLAIMS_LOCK:
        if _CHUNK_INFERENCE_CLAIMS.get(key) is completed:
            _CHUNK_INFERENCE_CLAIMS.pop(key, None)
    completed.set()


def submit_chunk(
    session_id: int,
    sequence: int,
    ingested: dict,
    db_path: str | None = None,
) -> dict:
    """Claim and analyse one sequence without duplicating inference side effects."""
    created_at = _now()
    if (
        not _is_integer(session_id)
        or session_id <= 0
    ):
        return _error("no_such_care_session")
    if not _is_integer(sequence) or sequence <= 0:
        return _error("invalid_chunk_sequence")

    ingest = ingested if isinstance(ingested, dict) else {}
    source_path = ingest.get("source_path")
    digest = _source_digest(source_path)

    claim_key = _chunk_claim_key(db_path, session_id, sequence)
    while True:
        connection = _conn(db_path)
        try:
            row = _session_row(connection, session_id)
            if not row:
                return _error("no_such_care_session")
            resolved = _sequence_resolution(connection, row, sequence, digest)
            if resolved is not None:
                return resolved
            if row["status"] != LISTENING:
                return _error("invalid_care_session_transition")
        except sqlite3.Error:
            return _error("care_session_storage_error")
        finally:
            connection.close()

        owner, completed = _claim_chunk_inference(claim_key)
        if owner:
            break
        completed.wait()

    try:
        return _submit_claimed_chunk(
            session_id,
            sequence,
            ingest,
            created_at,
            db_path,
        )
    except Exception:
        return _error("care_session_storage_error")
    finally:
        _release_chunk_inference(claim_key, completed)


def _submit_claimed_chunk(
    session_id: int,
    sequence: int,
    ingest: dict,
    created_at: str,
    db_path: str | None,
) -> dict:
    """Run inference for the one in-process owner of a session sequence."""
    source_path = ingest.get("source_path")
    canonical_path = ingest.get("canonical_path")
    identity_path = ingest.get("identity_path")
    digest = _source_digest(source_path)

    connection = _conn(db_path)
    try:
        row = _session_row(connection, session_id)
        if not row:
            return _error("no_such_care_session")
        resolved = _sequence_resolution(connection, row, sequence, digest)
        if resolved is not None:
            return resolved
        if row["status"] != LISTENING:
            return _error("invalid_care_session_transition")
    except sqlite3.Error:
        return _error("care_session_storage_error")
    finally:
        connection.close()

    profile = identity.get_profile(row["profile_id"], db_path)
    if not profile:
        return _error("care_session_storage_error")

    quality = ingest.get("quality") if isinstance(ingest.get("quality"), dict) else {}
    capture = ingest.get("capture") if isinstance(ingest.get("capture"), dict) else {}
    ready = (
        ingest.get("status") == "ready"
        and digest is not None
        and isinstance(canonical_path, str)
        and Path(canonical_path).is_file()
        and isinstance(identity_path, str)
        and Path(identity_path).is_file()
    )
    analysis = {
        "status": "invalid",
        "reason_codes": [
            ingest.get("reason")
            if isinstance(ingest.get("reason"), str)
            else "invalid_ingest"
        ],
        "cry_presence": {},
        "matched_profile_id": None,
        "selected_match": False,
        "grounded": False,
        "preview": {},
    }

    if ready:
        try:
            cry_result = cry_gate.classify(canonical_path)
        except Exception:
            cry_result = {
                "status": "gate_unavailable",
                "reason_codes": ["cry_gate_model_unavailable"],
            }
        cry_presence = _public_cry_presence(cry_result)
        gate_status = cry_presence.get("status")
        analysis["cry_presence"] = cry_presence
        analysis["reason_codes"] = _reason_codes(
            cry_presence.get("reason_codes"),
            "cry_gate_unavailable",
        )
        if gate_status == "no_cry_detected":
            analysis["status"] = "no_cry_detected"
        elif gate_status == "cry_uncertain":
            analysis["status"] = "cry_uncertain"
        elif gate_status != "infant_cry_detected":
            analysis["status"] = "invalid"
        else:
            try:
                identity_result = identity.identify(
                    identity_path,
                    kind=identity.KIND_INFANT,
                    db_path=db_path,
                    audit=True,
                )
            except Exception:
                identity_result = {
                    "status": "uncertain",
                    "reasons": ["identity_unavailable"],
                }
            matched_profile_id = identity_result.get("profile_id")
            if _is_integer(matched_profile_id):
                analysis["matched_profile_id"] = matched_profile_id
            selected_match = (
                identity_result.get("status") in {"match", "matched"}
                and matched_profile_id == row["profile_id"]
            )
            analysis["reason_codes"] = _reason_codes(
                identity_result.get("reasons"),
                "identity_not_selected",
            )
            if not selected_match:
                analysis["status"] = "not_selected_profile"
            else:
                analysis["selected_match"] = True
                try:
                    preview = careflow.preview_profile_incident(
                        row["profile_id"],
                        canonical_path,
                        explicit_tags=_decoded_list(row["tags_json"]),
                        now=created_at,
                        db_path=db_path,
                    )
                except Exception:
                    preview = {
                        "status": "error",
                        "reason": "incident_preview_failed",
                    }
                analysis["preview"] = preview if isinstance(preview, dict) else {}
                guidance_payload = analysis["preview"].get("guidance")
                recommendation = (
                    guidance_payload.get("recommendation")
                    if isinstance(guidance_payload, dict)
                    else None
                )
                grounded = (
                    isinstance(guidance_payload, dict)
                    and guidance_payload.get("status") == "grounded"
                    and isinstance(recommendation, str)
                    and bool(recommendation.strip())
                )
                analysis["grounded"] = grounded
                if grounded:
                    analysis["reason_codes"] = ["grounded"]
                else:
                    preview_reason = analysis["preview"].get("reason")
                    guidance_status = (
                        guidance_payload.get("status")
                        if isinstance(guidance_payload, dict)
                        else None
                    )
                    analysis["reason_codes"] = [
                        preview_reason
                        if isinstance(preview_reason, str)
                        else (
                            guidance_status
                            if isinstance(guidance_status, str)
                            else "no_grounded_guidance"
                        )
                    ]
                analysis["status"] = "matched_no_guidance"

    connection = _conn(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = _session_row(connection, session_id)
        if not current:
            connection.rollback()
            return _error("no_such_care_session")
        resolved = _sequence_resolution(connection, current, sequence, digest)
        if resolved is not None:
            connection.rollback()
            return resolved
        if current["status"] != LISTENING:
            connection.rollback()
            return _error("invalid_care_session_transition")

        final_status = analysis["status"]
        latch_guidance = False
        if analysis["selected_match"] and analysis["grounded"]:
            if current["decision_json"]:
                final_status = "matched_guidance_already_latched"
            else:
                final_status = "guidance_latched"
                latch_guidance = True

        cry_presence = analysis["cry_presence"]
        cursor = connection.execute(
            "INSERT INTO care_session_chunk ("
            "session_id, sequence, created_at, source_audio_path, "
            "canonical_audio_path, identity_audio_path, audio_sha256, "
            "capture_metadata_json, quality_json, status, cry_status, "
            "cry_reason_codes, cry_model_version, matched_profile_id, "
            "reason_codes, result_json"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                sequence,
                created_at,
                source_path if isinstance(source_path, str) else None,
                canonical_path if isinstance(canonical_path, str) else None,
                identity_path if isinstance(identity_path, str) else None,
                digest,
                json.dumps(capture),
                json.dumps(quality),
                final_status,
                cry_presence.get("status"),
                json.dumps(cry_presence.get("reason_codes") or []),
                cry_presence.get("model_version"),
                analysis["matched_profile_id"],
                json.dumps(analysis["reason_codes"]),
                "{}",
            ),
        )
        chunk_id = int(cursor.lastrowid)

        assignments = ["last_sequence=?"]
        values = [sequence]
        if analysis["selected_match"]:
            assignments.append("latest_matched_chunk_id=?")
            values.append(chunk_id)
        if latch_guidance:
            decision = _latched_decision(
                chunk_id,
                created_at,
                profile,
                analysis["preview"],
            )
            assignments.extend(("selected_chunk_id=?", "decision_json=?"))
            values.extend((chunk_id, json.dumps(decision)))
        values.extend((session_id, LISTENING, current["last_sequence"]))
        updated = connection.execute(
            f"UPDATE care_session SET {','.join(assignments)} "
            "WHERE id=? AND status=? AND last_sequence=?",
            values,
        )
        if updated.rowcount != 1:
            connection.rollback()
            return _error("care_session_storage_error")

        session_row = _session_row(connection, session_id)
        chunk = {
            "id": chunk_id,
            "sequence": sequence,
            "status": final_status,
            "created_at": created_at,
            "reason_codes": analysis["reason_codes"],
        }
        if cry_presence:
            chunk["cry_presence"] = cry_presence
        result = _public_chunk_result(
            {
                "session": _render_with_profile(session_row, profile),
                "chunk": chunk,
            }
        )
        connection.execute(
            "UPDATE care_session_chunk SET result_json=? WHERE id=?",
            (json.dumps(result), chunk_id),
        )
        connection.commit()
        return result
    except sqlite3.Error:
        connection.rollback()
        return _error("care_session_storage_error")
    finally:
        connection.close()


def _discard_paths(
    connection: sqlite3.Connection,
    session_id: int,
    audio_root: str | Path,
) -> tuple[bool, int]:
    removed = 0
    try:
        root = Path(audio_root).resolve()
    except (OSError, RuntimeError, TypeError):
        return False, removed
    rows = connection.execute(
        "SELECT source_audio_path, canonical_audio_path, identity_audio_path "
        "FROM care_session_chunk WHERE session_id=?",
        (session_id,),
    ).fetchall()
    seen = set()
    for row in rows:
        for raw_path in row:
            if not raw_path:
                continue
            try:
                path = Path(raw_path).resolve()
                if path in seen or path == root or not path.is_relative_to(root):
                    continue
                seen.add(path)
                if path.is_file():
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
            except (OSError, RuntimeError, TypeError):
                return False, removed
    return True, removed


def _discard_claimed(
    session_id: int,
    audio_root: str | Path,
    db_path: str | None = None,
) -> dict:
    connection = _conn(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = _session_row(connection, session_id)
        if not row:
            connection.rollback()
            return _error("no_such_care_session")
        if (
            row["status"] not in (LISTENING, PAUSED, AWAITING_OUTCOME, DISCARDED)
            or row["episode_id"] is not None
        ):
            connection.rollback()
            return _error("invalid_care_session_transition")
        cleanup_complete, removed = _discard_paths(
            connection,
            session_id,
            audio_root,
        )
        if not cleanup_complete:
            if removed and row["status"] != DISCARDED:
                connection.execute(
                    "UPDATE care_session SET status=? WHERE id=? AND status=?",
                    (DISCARDED, session_id, row["status"]),
                )
                connection.commit()
            else:
                connection.rollback()
            return _error("care_session_cleanup_failed")
        if row["status"] == DISCARDED:
            connection.commit()
            return _render(row, db_path)
        cursor = connection.execute(
            "UPDATE care_session SET status=? "
            "WHERE id=? AND status=? AND episode_id IS NULL",
            (DISCARDED, session_id, row["status"]),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return _error("invalid_care_session_transition")
        connection.commit()
        updated = _session_row(connection, session_id)
        return _render(updated, db_path)
    except sqlite3.Error:
        connection.rollback()
        return _error("care_session_storage_error")
    finally:
        connection.close()


def discard(
    session_id: int,
    audio_root: str | Path,
    db_path: str | None = None,
) -> dict:
    """Delete unsaved managed chunk audio and make the session immutable."""
    with _session_mutation_lock(db_path, session_id):
        return _discard_claimed(session_id, audio_root, db_path)
