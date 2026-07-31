"""Sanitized read-only snapshots for the local care demo monitor."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone

try:
    from . import care_sessions, config, store
except ImportError:
    import care_sessions
    import config
    import store


SEGMENT_TARGET_SECONDS = 3
MINIMUM_ANALYZED_AUDIO_SECONDS = 20
MINIMUM_SEGMENTS_BEFORE_DECISION = 7
EVENT_LIMIT = 12


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _json_object(raw) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _json_list(raw) -> list:
    try:
        value = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []
    return value if isinstance(value, list) else []


def _clean_strings(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _public_decision_progress(value) -> dict:
    if not isinstance(value, dict):
        return {}
    public = {}
    for field in (
        "consistent_grounded_segments",
        "required_consistent_grounded_segments",
        "additional_confirmations",
        "required_additional_confirmations",
        "segments_seen",
        "minimum_segments_before_decision",
    ):
        item = value.get(field)
        if type(item) is int and item >= 0:
            public[field] = item
    for field in (
        "analyzed_audio_seconds",
        "minimum_analyzed_audio_seconds",
    ):
        item = value.get(field)
        if (
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(item)
            and item >= 0
        ):
            public[field] = item
    if isinstance(value.get("decision_eligible"), bool):
        public["decision_eligible"] = value["decision_eligible"]
    if value.get("repeated_source") is True:
        public["repeated_source"] = True
    return public


def _format_count(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:g}"
    return ""


def _valid_demo_progress(progress: dict) -> bool:
    if not progress:
        return False
    required_consistent = progress.get("required_consistent_grounded_segments")
    minimum_segments = progress.get("minimum_segments_before_decision")
    minimum_audio = progress.get("minimum_analyzed_audio_seconds")
    if (
        type(required_consistent) is not int
        or required_consistent < 1
        or type(minimum_segments) is not int
        or minimum_segments < MINIMUM_SEGMENTS_BEFORE_DECISION
        or not isinstance(minimum_audio, (int, float))
        or isinstance(minimum_audio, bool)
        or minimum_audio < MINIMUM_ANALYZED_AUDIO_SECONDS
    ):
        return False
    if progress.get("decision_eligible") is not True:
        return True
    return (
        progress.get("consistent_grounded_segments", -1)
        >= required_consistent
        and progress.get("segments_seen", -1) >= minimum_segments
        and progress.get("analyzed_audio_seconds", -1) >= minimum_audio
    )


def _confirmation_view(
    progress: dict,
    decision: dict | None,
    demo_profile: bool,
) -> dict:
    if decision and not demo_profile:
        return {
            "state": "complete",
            "detail": "The selected profile's confirmation rules are complete.",
        }
    if not _valid_demo_progress(progress):
        return {
            "state": "waiting",
            "detail": (
                "Waiting for valid confirmation progress from the server."
            ),
        }
    details = []
    analyzed = progress.get("analyzed_audio_seconds")
    minimum_audio = progress.get("minimum_analyzed_audio_seconds")
    if analyzed is not None and minimum_audio is not None:
        details.append(
            f"{_format_count(analyzed)} of "
            f"{_format_count(minimum_audio)} seconds"
        )
    seen = progress.get("segments_seen")
    minimum_segments = progress.get("minimum_segments_before_decision")
    if seen is not None and minimum_segments is not None:
        details.append(f"{seen} of {minimum_segments} segments")
    consistent = progress.get("consistent_grounded_segments")
    required = progress.get("required_consistent_grounded_segments")
    if consistent is not None and required is not None:
        details.append(f"{consistent} of {required} consistent cry segments")
    if decision and progress.get("decision_eligible") is True:
        state = "complete"
    elif progress.get("repeated_source") is True:
        state = "review"
    else:
        state = "collecting"
    return {
        "state": state,
        "detail": ". ".join(details)
        or "Collecting the next distinct confirmation.",
    }


def _local_clock(value: str | None) -> tuple[str, str]:
    if not isinstance(value, str):
        return "Waiting for a segment", "unknown"
    try:
        captured = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "Time unavailable", "unknown"
    hour = captured.hour
    if 5 <= hour < 12:
        time_of_day = "morning"
    elif 12 <= hour < 17:
        time_of_day = "afternoon"
    elif 17 <= hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"
    clock = captured.strftime("%I:%M %p").lstrip("0")
    return clock, time_of_day


def _ingest_view(row, quality: dict) -> dict:
    duration = quality.get("duration_s")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        duration = None
    if row["status"] == "invalid":
        return {
            "state": "failed",
            "quality": "unusable",
            "detail": "The uploaded segment could not be used.",
            "duration_seconds": duration,
        }
    if not row["canonical_audio_path"]:
        return {
            "state": "waiting",
            "quality": "unknown",
            "detail": "Waiting for audio decode.",
            "duration_seconds": duration,
        }

    mean_db = quality.get("mean_db")
    peak_db = quality.get("peak_db")
    if isinstance(mean_db, (int, float)) and not isinstance(mean_db, bool) and mean_db < -45:
        label = "quiet"
        detail = "Decoded successfully. The captured level is quiet."
    elif isinstance(peak_db, (int, float)) and not isinstance(peak_db, bool) and peak_db > -1.2:
        label = "near limit"
        detail = "Decoded successfully. The captured level is near its limit."
    else:
        label = "usable"
        detail = "Decoded successfully into analysis-ready audio."
    return {
        "state": "decoded",
        "quality": label,
        "detail": detail,
        "duration_seconds": round(float(duration), 2) if duration is not None else None,
    }


def _cry_view(row) -> dict:
    status = row["cry_status"]
    reason_codes = _clean_strings(_json_list(row["cry_reason_codes"]))
    if status == "infant_cry_detected":
        state = "pass"
        label = "Infant cry detected"
        detail = "The cry gate passed this segment to the selected profile check."
    elif status == "cry_uncertain":
        state = "review"
        label = "Cry-like sound, not confirmed"
        detail = "The segment stayed below the infant-cry confirmation gate."
    elif status == "no_cry_detected":
        state = "rejected"
        label = "No infant cry detected"
        detail = "Identity and memory lookup were not run for this segment."
    elif status:
        state = "error"
        label = "Cry gate unavailable"
        detail = "The cry gate did not return a usable result."
    else:
        state = "waiting"
        label = "Waiting for cry gate"
        detail = "No decoded segment has reached the cry gate yet."
    return {
        "state": state,
        "label": label,
        "detail": detail,
        "model": row["cry_model_version"] if isinstance(row["cry_model_version"], str) else None,
        "reason_codes": reason_codes,
    }


def _identity_view(row, profile: dict, cry_state: str) -> dict:
    selected_id = profile.get("id")
    matched_id = row["matched_profile_id"]
    if cry_state != "pass":
        return {
            "state": "not_run",
            "label": "Identity not run",
            "detail": "Identity runs only after the infant cry gate passes.",
        }
    if isinstance(selected_id, int) and matched_id == selected_id:
        return {
            "state": "selected_profile",
            "label": "Selected profile comparison complete",
            "detail": (
                "The comparison opened "
                f"{profile.get('display_name', 'the selected baby')}'s "
                "recorded memory."
            ),
        }
    return {
        "state": "not_confirmed",
        "label": "Profile comparison did not open memory",
        "detail": "The selected profile's recorded memory was not searched.",
    }


def _memory_view(
    row,
    identity_state: str,
    decision: dict | None,
    decision_progress: dict,
) -> dict:
    if identity_state != "selected_profile":
        return {
            "state": "not_run",
            "label": "Memory lookup not run",
            "detail": "Memory stays closed until the selected profile is confirmed.",
        }
    if decision:
        support = decision.get("guidance", {}).get("support_count")
        count = support if isinstance(support, int) else 0
        return {
            "state": "grounded",
            "label": "Recorded history found",
            "detail": f"{count} prior supporting incident{'s' if count != 1 else ''}.",
        }
    if decision_progress.get("consistent_grounded_segments", 0) > 0:
        return {
            "state": "grounded",
            "label": "Prior memory found",
            "detail": "A recorded action and its context are being confirmed.",
        }
    if row["status"] == "matched_no_guidance":
        return {
            "state": "no_result",
            "label": "No grounded prior action",
            "detail": "The baby matched, but recorded history did not support guidance.",
        }
    return {
        "state": "searching",
        "label": "Checking recorded history",
        "detail": "The selected baby's earlier incidents are being checked.",
    }


def _guidance_view(decision: dict | None) -> dict:
    if decision:
        recommendation = decision.get("guidance", {}).get("recommendation")
        return {
            "state": "latched",
            "label": "Suggestion ready",
            "detail": recommendation if isinstance(recommendation, str) else "Recorded guidance is fixed for this session.",
        }
    return {
        "state": "waiting",
        "label": "No suggestion yet",
        "detail": "The monitor keeps listening until history supports a suggestion.",
    }


def _pipeline(
    latest: dict | None,
    decision: dict | None,
    decision_progress: dict,
    demo_profile: bool,
) -> list[dict]:
    if latest is None:
        return [
            {
                "key": key,
                "label": label,
                "state": "waiting",
                "detail": "Waiting for the first 3-second segment.",
            }
            for key, label in (
                ("received", "Received segment"),
                ("cry_gate", "Infant cry gate"),
                ("baby_match", "Selected baby check"),
                ("memory_context", "Memory and context"),
                ("confirmations", "Confirmations"),
                ("suggestion", "Suggestion"),
            )
        ]
    progress = decision_progress or latest.get("decision_progress") or {}
    confirmation = _confirmation_view(
        progress,
        decision,
        demo_profile,
    )
    suggestion_ready = bool(decision) and (
        not demo_profile
        or (
            _valid_demo_progress(progress)
            and progress.get("decision_eligible") is True
        )
    )
    return [
        {
            "key": "received",
            "label": "Received segment",
            "state": "complete" if latest["ingest"]["state"] == "decoded" else latest["ingest"]["state"],
            "detail": latest["ingest"]["detail"],
        },
        {
            "key": "cry_gate",
            "label": "Infant cry gate",
            "state": latest["cry_gate"]["state"],
            "detail": latest["cry_gate"]["detail"],
        },
        {
            "key": "baby_match",
            "label": "Selected baby check",
            "state": "pass" if latest["identity"]["state"] == "selected_profile" else latest["identity"]["state"],
            "detail": latest["identity"]["detail"],
        },
        {
            "key": "memory_context",
            "label": "Memory and context",
            "state": latest["memory"]["state"],
            "detail": latest["memory"]["detail"],
        },
        {
            "key": "confirmations",
            "label": "Confirmations",
            "state": confirmation["state"],
            "detail": confirmation["detail"],
        },
        {
            "key": "suggestion",
            "label": "Suggestion",
            "state": "complete" if suggestion_ready else "waiting",
            "detail": (
                latest["guidance"]["detail"]
                if suggestion_ready
                else "No suggestion is ready yet."
            ),
        },
    ]


def _event_message(status: str) -> tuple[str, str]:
    return {
        "guidance_latched": ("success", "Suggestion ready from recorded history"),
        "matched_guidance_already_latched": (
            "success",
            "Cry matched, existing suggestion kept",
        ),
        "matched_no_guidance": (
            "signal",
            "Profile comparison complete, no grounded action found",
        ),
        "not_selected_profile": (
            "warning",
            "Infant cry detected, profile memory stayed closed",
        ),
        "cry_uncertain": ("neutral", "Cry-like sound, waiting for a clearer segment"),
        "no_cry_detected": ("neutral", "No infant cry detected"),
        "invalid": ("error", "Segment could not be used"),
    }.get(status, ("neutral", "Segment processed"))


def _stored_decision_progress(raw) -> dict:
    stored_result = _json_object(raw)
    stored_chunk = stored_result.get("chunk")
    return _public_decision_progress(
        stored_chunk.get("decision_progress")
        if isinstance(stored_chunk, dict)
        else None
    )


def _latest_segment(row, profile: dict, decision: dict | None) -> dict:
    quality = _json_object(row["quality_json"])
    ingest = _ingest_view(row, quality)
    cry_gate = _cry_view(row)
    identity = _identity_view(row, profile, cry_gate["state"])
    decision_progress = _stored_decision_progress(row["result_json"])
    memory = _memory_view(
        row,
        identity["state"],
        decision,
        decision_progress,
    )
    guidance = _guidance_view(decision)
    reason_codes = _clean_strings(_json_list(row["reason_codes"]))
    latest = {
        "sequence": row["sequence"],
        "created_at": row["created_at"],
        "duration_seconds": ingest.pop("duration_seconds"),
        "status": row["status"],
        "ingest": ingest,
        "cry_gate": cry_gate,
        "identity": identity,
        "memory": memory,
        "guidance": guidance,
        "reason_codes": reason_codes,
    }
    if decision_progress:
        latest["decision_progress"] = decision_progress
    return latest


def _evidence(decision: dict | None) -> list[dict]:
    if not isinstance(decision, dict):
        return []
    rendered = []
    for scenario in decision.get("scenarios") or []:
        if not isinstance(scenario, dict) or not isinstance(scenario.get("episode_id"), int):
            continue
        rendered.append(
            {
                "incident_id": scenario["episode_id"],
                "recorded_at": scenario.get("started_at")
                if isinstance(scenario.get("started_at"), str)
                else None,
                "interventions": [
                    {
                        "order": item.get("order"),
                        "action": item.get("action"),
                        "evidence": item.get("evidence"),
                    }
                    for item in scenario.get("interventions") or []
                    if isinstance(item, dict)
                    and isinstance(item.get("order"), int)
                    and isinstance(item.get("action"), str)
                    and isinstance(item.get("evidence"), str)
                ],
                "outcome": scenario.get("outcome")
                if scenario.get("outcome") is None
                or isinstance(scenario.get("outcome"), str)
                else None,
                "outcome_source": scenario.get("outcome_src")
                if isinstance(scenario.get("outcome_src"), str)
                else None,
                "worked": scenario.get("worked")
                if scenario.get("worked") is None
                or isinstance(scenario.get("worked"), bool)
                else None,
                "contributions": _clean_strings(scenario.get("contributions")),
            }
        )
    return rendered


def _context_view(session: dict, latest: dict | None, decision: dict | None) -> dict:
    captured_at = (
        latest.get("created_at")
        if isinstance(latest, dict) and isinstance(latest.get("created_at"), str)
        else session.get("started_at")
    )
    local_time, time_of_day = _local_clock(captured_at)
    tags = _clean_strings(session.get("tags"))
    if latest is None:
        cry_value = "Waiting for the first segment"
    elif latest["cry_gate"]["state"] == "pass":
        cry_value = "Infant cry gate passed"
    else:
        cry_value = latest["cry_gate"]["label"]
    support = (
        decision.get("guidance", {}).get("support_count")
        if isinstance(decision, dict)
        else None
    )
    memory_value = (
        f"{support} supporting prior incident{'s' if support != 1 else ''}"
        if isinstance(support, int)
        else "No grounded incident selected yet"
    )
    return {
        "captured_at": captured_at,
        "local_time": local_time,
        "time_of_day": time_of_day,
        "tags": tags,
        "factors": [
            {"label": "Cry pattern", "value": cry_value},
            {
                "label": "Time",
                "value": f"{time_of_day.capitalize()} at {local_time}"
                if time_of_day != "unknown"
                else local_time,
            },
            {
                "label": "Care tags",
                "value": ", ".join(tags) if tags else "No explicit tags",
            },
            {"label": "Recorded memory", "value": memory_value},
        ],
    }


def _events(rows, profile: dict) -> list[dict]:
    rendered = []
    for row in rows[:EVENT_LIMIT]:
        tone, message = _event_message(row["status"])
        rendered.append(
            {
                "sequence": row["sequence"],
                "created_at": row["created_at"],
                "tone": tone,
                "message": message,
                "profile": profile.get("display_name"),
            }
        )
    return rendered


def snapshot(db_path: str | None = None) -> dict:
    """Return the latest care run without paths, hashes, scores, or embeddings."""
    store.init_db(db_path)
    connection = sqlite3.connect(db_path or config.DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT id FROM care_session ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {
                "status": "idle",
                "server_time": _now(),
                "segment_target_seconds": SEGMENT_TARGET_SECONDS,
                "session": None,
            }
        session = care_sessions.get(row["id"], db_path)
        if session.get("status") == "error":
            return {
                "status": "unavailable",
                "server_time": _now(),
                "segment_target_seconds": SEGMENT_TARGET_SECONDS,
                "session": None,
            }
        chunk_rows = connection.execute(
            "SELECT id, sequence, created_at, canonical_audio_path, "
            "quality_json, status, cry_status, cry_reason_codes, "
            "cry_model_version, matched_profile_id, reason_codes, result_json "
            "FROM care_session_chunk WHERE session_id=? "
            "ORDER BY sequence DESC LIMIT ?",
            (session["id"], EVENT_LIMIT),
        ).fetchall()
        decision = (
            session.get("decision")
            if isinstance(session.get("decision"), dict)
            else None
        )
        decision_progress = {}
        decision_id = decision.get("id") if decision else None
        if type(decision_id) is int:
            selected_row = next(
                (item for item in chunk_rows if item["id"] == decision_id),
                None,
            )
            if selected_row is None:
                selected_row = connection.execute(
                    "SELECT result_json FROM care_session_chunk "
                    "WHERE id=? AND session_id=?",
                    (decision_id, session["id"]),
                ).fetchone()
            if selected_row is not None:
                decision_progress = _stored_decision_progress(
                    selected_row["result_json"]
                )
    except sqlite3.Error:
        return {
            "status": "unavailable",
            "server_time": _now(),
            "segment_target_seconds": SEGMENT_TARGET_SECONDS,
            "session": None,
        }
    finally:
        connection.close()

    profile = session.get("profile") if isinstance(session.get("profile"), dict) else {}
    demo_profile = (
        profile.get("display_name") == config.CARE_DEMO_PROFILE_NAME
    )
    latest = _latest_segment(chunk_rows[0], profile, decision) if chunk_rows else None
    context_view = _context_view(session, latest, decision)
    monitor_session = {
        "id": session["id"],
        "state": session.get("status"),
        "started_at": session.get("started_at"),
        "last_sequence": session.get("last_sequence", 0),
        "profile": {
            "id": profile.get("id"),
            "display_name": profile.get("display_name"),
        },
        "context": context_view,
        "latest_segment": latest,
        "pipeline": _pipeline(
            latest,
            decision,
            decision_progress,
            demo_profile,
        ),
        "decision": decision,
        "evidence": _evidence(decision),
        "events": _events(chunk_rows, profile),
    }
    if decision_progress:
        monitor_session["decision_progress"] = decision_progress
    return {
        "status": "active"
        if session.get("status") in {"listening", "paused"}
        else "finished",
        "server_time": _now(),
        "segment_target_seconds": SEGMENT_TARGET_SECONDS,
        "session": monitor_session,
    }
