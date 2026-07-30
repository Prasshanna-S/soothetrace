"""Deterministic current context for profile-isolated incident retrieval."""

from __future__ import annotations

from datetime import datetime

try:
    from . import store
except ImportError:
    import store


def _aware_datetime(value: str | None) -> datetime | None:
    if value is None:
        return datetime.now().astimezone()
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _clean_tags(values: list[str] | None) -> list[str]:
    clean = []
    seen = set()
    for value in values or []:
        if not isinstance(value, str):
            continue
        tag = " ".join(value.strip().casefold().split())
        if tag and tag not in seen:
            clean.append(tag)
            seen.add(tag)
    return clean


def _hours_since(now: datetime, occurred_at: str | None) -> float | None:
    event_time = _aware_datetime(occurred_at)
    if event_time is None:
        return None
    elapsed = (now - event_time).total_seconds() / 3600.0
    if elapsed < 0:
        return None
    return elapsed


def _recency_tag(event_type: str, hours: float, details: dict) -> str | None:
    if event_type == "feeding":
        if hours < 2:
            return "last_feed_under_2h"
        if hours <= 4:
            return "last_feed_2_to_4h"
        return "last_feed_over_4h"
    if event_type == "sleep" and details.get("phase") == "end":
        if hours < 2:
            return "awake_under_2h"
        if hours <= 4:
            return "awake_2_to_4h"
        return "awake_over_4h"
    if event_type == "diaper" and hours < 2:
        return "recent_diaper"
    return None


def build_current_context(
    profile_id: int,
    now: str | None = None,
    transcript: str | None = None,
    tags: list[str] | None = None,
    db_path: str | None = None,
) -> dict:
    """Return current hour and literal context tags without inferring a cause."""
    del transcript
    if (
        not isinstance(profile_id, int)
        or isinstance(profile_id, bool)
        or profile_id <= 0
    ):
        return {}
    current = _aware_datetime(now)
    if current is None:
        return {}

    output_tags = _clean_tags(tags)
    seen_tags = set(output_tags)
    event_ids = []
    list_events = getattr(store, "list_care_events", None)
    if callable(list_events):
        try:
            events = list_events(profile_id, since=None, path=db_path)
        except Exception:
            events = []
    else:
        events = []

    latest_by_type = {}
    for event in events or []:
        if not isinstance(event, dict) or event.get("profile_id") != profile_id:
            continue
        event_type = event.get("event_type")
        if event_type not in {"feeding", "sleep", "diaper"}:
            continue
        event_time = _aware_datetime(event.get("occurred_at"))
        if event_time is None or event_time > current:
            continue
        existing = latest_by_type.get(event_type)
        if existing is None or event_time > existing[0]:
            latest_by_type[event_type] = (event_time, event)

    for event_type in ("feeding", "sleep", "diaper"):
        selected = latest_by_type.get(event_type)
        if selected is None:
            continue
        event = selected[1]
        hours = _hours_since(current, event.get("occurred_at"))
        if hours is None:
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        tag = _recency_tag(event_type, hours, details)
        if tag is None:
            continue
        if tag not in seen_tags:
            output_tags.append(tag)
            seen_tags.add(tag)
        if isinstance(event.get("id"), int):
            event_ids.append(event["id"])

    return {
        "hour_local": current.hour,
        "tags": output_tags,
        "care_event_ids": event_ids,
    }
