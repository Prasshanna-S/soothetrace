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
_PRIVATE_KEY_PARTS = (
    "path",
    "digest",
    "sha256",
    "embedding",
    "score",
    "similarity",
    "margin",
    "confidence",
    "probability",
)


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


def _is_private_key(key) -> bool:
    name = str(key).casefold()
    return name.startswith("_") or any(part in name for part in _PRIVATE_KEY_PARTS)


def _safe_value(value):
    if isinstance(value, dict):
        return {
            key: _safe_value(child)
            for key, child in value.items()
            if not _is_private_key(key)
        }
    if isinstance(value, list):
        return [_safe_value(child) for child in value]
    return value


def _decoded_decision(raw):
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return _safe_value(value) if isinstance(value, dict) else None


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
) -> None:
    try:
        root = Path(audio_root).resolve()
    except (OSError, RuntimeError, TypeError):
        return
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
            except (OSError, RuntimeError, TypeError):
                continue


def discard(
    session_id: int,
    audio_root: str | Path,
    db_path: str | None = None,
) -> dict:
    """Delete unsaved managed chunk audio and make the session immutable."""
    connection = _conn(db_path)
    try:
        row = _session_row(connection, session_id)
        if not row:
            return _error("no_such_care_session")
        if (
            row["status"] not in (LISTENING, PAUSED, AWAITING_OUTCOME)
            or row["episode_id"] is not None
        ):
            return _error("invalid_care_session_transition")
        _discard_paths(connection, session_id, audio_root)
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
