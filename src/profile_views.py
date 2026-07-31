"""Safe profile, History, and Baby projections for the browser app."""

from __future__ import annotations

from typing import Any

try:
    from . import database, identity, store
except ImportError:
    import database
    import identity
    import store


MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 20


def _error(reason: str) -> dict:
    return {"status": "error", "reason": reason}


def _strings(value: Any, *, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = " ".join(item.split()).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned[:120])
        if len(result) >= limit:
            break
    return result


def _interventions(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    rendered = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        public = {}
        for field in ("action", "evidence", "outcome"):
            text = item.get(field)
            if isinstance(text, str) and text.strip():
                public[field] = " ".join(text.split())[:500]
        worked = item.get("worked")
        if worked is None or isinstance(worked, bool):
            public["worked"] = worked
        if public:
            rendered.append(public)
    return rendered


def _time_context(context: dict) -> dict:
    public = {}
    hour = context.get("hour_local")
    if isinstance(hour, int) and not isinstance(hour, bool) and 0 <= hour <= 23:
        public["hour_local"] = hour
    gap = context.get("minutes_since_prev_episode")
    if isinstance(gap, (int, float)) and not isinstance(gap, bool) and gap >= 0:
        public["minutes_since_previous"] = round(float(gap), 2)
    return public


def _speech_segments(
    transcript: str,
    *,
    outcome_source: str | None,
    context: dict,
) -> list[dict]:
    """Project stored text with only the provenance its markers support."""
    if not transcript:
        return []
    audio_marker = "Audio transcript:"
    typed_marker = "Typed caregiver follow-up:"
    segments = []
    if audio_marker in transcript:
        audio_text = transcript.split(audio_marker, 1)[1]
        if typed_marker in audio_text:
            audio_text = audio_text.split(typed_marker, 1)[0]
        audio_text = " ".join(audio_text.split()).strip()[:1000]
        if audio_text:
            segments.append(
                {
                    "text": audio_text,
                    "source": "captured_transcript",
                    "label": "Captured transcript",
                }
            )
    if typed_marker in transcript:
        typed_text = transcript.split(typed_marker, 1)[1]
        typed_text = " ".join(typed_text.split()).strip()[:1000]
        if typed_text:
            segments.append(
                {
                    "text": typed_text,
                    "source": "typed_follow_up",
                    "label": "Caregiver typed",
                }
            )
    if segments:
        return segments
    synthetic = (
        outcome_source == "seed"
        or context.get("synthetic_demo_memory") is True
    )
    if synthetic:
        source = "synthetic_demo"
        label = "Synthetic demo transcript"
    elif outcome_source == "caregiver":
        source = "caregiver_record"
        label = "Caregiver record"
    else:
        source = "stored_record"
        label = "Stored transcript"
    return [
        {
            "text": " ".join(transcript.split()).strip()[:1000],
            "source": source,
            "label": label,
        }
    ]


def _render_incident(
    profile_id: int,
    episode: dict,
    *,
    detail: bool,
) -> dict:
    transcript = episode.get("transcript")
    transcript = transcript.strip() if isinstance(transcript, str) else ""
    context = episode.get("context")
    context = context if isinstance(context, dict) else {}
    result = {
        "id": episode["id"],
        "started_at": episode.get("started_at"),
        "duration_s": episode.get("duration_s"),
        "time": _time_context(context),
        "tags": _strings(context.get("tags")),
        "interventions": _interventions(episode.get("interventions")),
        "outcome": (
            episode.get("outcome")
            if isinstance(episode.get("outcome"), str)
            else None
        ),
        "outcome_source": (
            episode.get("outcome_src")
            if episode.get("outcome_src") in {"caregiver", "inferred", "seed"}
            else None
        ),
        "worked": (
            episode.get("worked")
            if episode.get("worked") is None
            or isinstance(episode.get("worked"), bool)
            else None
        ),
        "transcript_excerpt": transcript[:220],
        "audio_url": (
            f"/api/profiles/{profile_id}/incidents/{episode['id']}/audio"
            if isinstance(episode.get("audio_path"), str)
            and bool(episode["audio_path"])
            else None
        ),
    }
    result["actions"] = result["interventions"]
    result["context"] = {
        **result["time"],
        "tags": result["tags"],
    }
    result["audio"] = (
        {"url": result["audio_url"]} if result["audio_url"] else None
    )
    if detail:
        result["transcript"] = transcript
        result["speech"] = {
            "segments": _speech_segments(
                transcript,
                outcome_source=result["outcome_source"],
                context=context,
            )
        }
        supporting = context.get("supporting_incident_ids")
        result["supporting_incident_ids"] = [
            item
            for item in (supporting if isinstance(supporting, list) else [])
            if isinstance(item, int) and not isinstance(item, bool) and item > 0
        ][:20]
        notes = context.get("caregiver_notes")
        result["caregiver_notes"] = (
            notes.strip()[:1000]
            if isinstance(notes, str) and notes.strip()
            else None
        )
    return result


def _profile(profile_id: int, db_path: str | None) -> dict | None:
    if not isinstance(profile_id, int) or isinstance(profile_id, bool) or profile_id <= 0:
        return None
    return identity.get_profile(profile_id, db_path)


def summary(profile_id: int, db_path: str | None = None) -> dict:
    profile = _profile(profile_id, db_path)
    if not profile:
        return _error("profile_not_found")
    episodes = store.list_episodes(f"profile-{profile_id}", db_path)
    available = []
    if any(item.get("fingerprint") for item in episodes):
        available.append("acoustic_pattern")
    if any(
        isinstance(item.get("context"), dict)
        and isinstance(item["context"].get("hour_local"), int)
        for item in episodes
    ):
        available.append("time_of_day")
    if any(
        _strings(
            item.get("context", {}).get("tags")
            if isinstance(item.get("context"), dict)
            else None
        )
        for item in episodes
    ):
        available.append("caregiver_tags")
    if any(
        isinstance(item.get("transcript"), str) and item["transcript"].strip()
        for item in episodes
    ):
        available.append("caregiver_speech")
    if any(
        isinstance(item.get("outcome"), str) and item["outcome"].strip()
        for item in episodes
    ):
        available.append("previous_outcomes")
    connection = database.connect(db_path)
    try:
        enrollment_rows = connection.execute(
            "SELECT id,captured_at,duration_s FROM enrollment "
            "WHERE profile_id=? ORDER BY captured_at,id",
            (profile_id,),
        ).fetchall()
    finally:
        connection.close()
    enrollment_summaries = [
        {
            "id": row["id"],
            "captured_at": row["captured_at"],
            "duration_s": row["duration_s"],
            "playback_url": f"/api/audio/enrollments/{row['id']}",
        }
        for row in enrollment_rows
    ]
    return {
        "status": "ready",
        "profile": {
            "id": profile["id"],
            "display_name": profile["display_name"],
            "kind": profile["kind"],
            "status": profile["status"],
            "enrollment_count": profile.get("enrollments", 0),
            "enrollments": enrollment_summaries,
            "memory_count": len(episodes),
            "latest_memory_at": (
                episodes[0].get("started_at") if episodes else None
            ),
            "available_context": available,
        },
        "training_clips": enrollment_summaries,
    }


def incidents(
    profile_id: int,
    db_path: str | None = None,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    before_id: int | None = None,
) -> dict:
    profile = _profile(profile_id, db_path)
    if not profile:
        return _error("profile_not_found")
    safe_limit = (
        min(MAX_PAGE_SIZE, max(1, limit))
        if isinstance(limit, int) and not isinstance(limit, bool)
        else DEFAULT_PAGE_SIZE
    )
    episodes = store.list_episodes(f"profile-{profile_id}", db_path)
    if isinstance(before_id, int) and not isinstance(before_id, bool):
        episodes = [item for item in episodes if item.get("id", 0) < before_id]
    has_more = len(episodes) > safe_limit
    page = episodes[:safe_limit]
    return {
        "status": "ready",
        "profile": {
            "id": profile["id"],
            "display_name": profile["display_name"],
        },
        "incidents": [
            _render_incident(profile_id, item, detail=False)
            for item in page
        ],
        "next_before_id": page[-1]["id"] if has_more and page else None,
        "next_cursor": (
            str(page[-1]["id"]) if has_more and page else None
        ),
    }


def incident(
    profile_id: int,
    incident_id: int,
    db_path: str | None = None,
) -> dict:
    profile = _profile(profile_id, db_path)
    if not profile:
        return _error("profile_not_found")
    if (
        not isinstance(incident_id, int)
        or isinstance(incident_id, bool)
        or incident_id <= 0
    ):
        return _error("incident_not_found")
    episode = store.get_episode(incident_id, db_path)
    if not episode or episode.get("subject_id") != f"profile-{profile_id}":
        return _error("incident_not_found")
    return {
        "status": "ready",
        "profile": {
            "id": profile["id"],
            "display_name": profile["display_name"],
        },
        "incident": _render_incident(profile_id, episode, detail=True),
    }
