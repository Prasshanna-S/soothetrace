"""Persistent infant care-session state with safe public snapshots."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import config, identity, store
except ImportError:
    import config
    import identity
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


def _public_audio_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    prefix = "/api/audio/episodes/"
    episode_id = value.removeprefix(prefix)
    if not value.startswith(prefix) or not episode_id.isdecimal():
        return None
    return value


def _public_scenario(value) -> dict | None:
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
    audio_url = _public_audio_url(value.get("audio_url"))
    if audio_url is not None:
        public["audio_url"] = audio_url
    return public


def _public_decision(value) -> dict:
    public = {}
    if _is_integer(value.get("id")):
        public["id"] = value["id"]
    if isinstance(value.get("latched_at"), str):
        public["latched_at"] = value["latched_at"]
    if isinstance(value.get("profile"), dict):
        public["profile"] = _public_decision_profile(value["profile"])
    if isinstance(value.get("guidance"), dict):
        public["guidance"] = _public_guidance(value["guidance"])
    if isinstance(value.get("basis"), list):
        public["basis"] = _string_list(value["basis"])
    if isinstance(value.get("scenarios"), list):
        public["scenarios"] = [
            scenario
            for item in value["scenarios"]
            if (scenario := _public_scenario(item)) is not None
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


def _render(row, db_path: str | None = None) -> dict:
    profile = identity.get_profile(row["profile_id"], db_path)
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


def discard(
    session_id: int,
    audio_root: str | Path,
    db_path: str | None = None,
) -> dict:
    """Delete unsaved managed chunk audio and make the session immutable."""
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
