"""Human-facing output with honest provenance and confidence language."""

from __future__ import annotations

from datetime import datetime


def _display_time(value: str | None) -> str:
    if not value:
        return "an earlier recording"
    try:
        return datetime.fromisoformat(value).strftime("%a %b %-d at %-I:%M %p")
    except (TypeError, ValueError):
        return "an earlier recording"


def _ordinal(value: int) -> str:
    value = max(0, int(value))
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def recall_card(matches: list[dict], episode_count: int) -> str:
    """Render the best prior match using ordinal bands only."""
    visible = [
        match
        for match in (matches or [])
        if isinstance(match, dict) and match.get("band") in {"strong", "weak"}
    ]
    if not visible:
        if episode_count <= 0:
            return "No recordings yet - nothing to compare."
        if episode_count <= 3:
            return (
                f"Only your {_ordinal(episode_count)} recording - "
                "not enough to compare yet."
            )
        return "Nothing similar on record yet."

    match = visible[0]
    lines = [
        f"{match['band'].upper()} MATCH",
        f"A similar recording happened {_display_time(match.get('started_at'))}.",
    ]
    actions = [
        item.get("action", "").strip()
        for item in (match.get("interventions") or [])
        if isinstance(item, dict) and item.get("action")
    ]
    if actions:
        lines.append(f"You previously tried: {', '.join(actions)}.")
    if match.get("outcome"):
        source = {
            "caregiver": "caregiver reported",
            "inferred": "inferred from transcript",
            "seed": "synthetic demo data",
        }.get(match.get("outcome_src"), "source unavailable")
        lines.append(f"Reported outcome ({source}): {match['outcome']}")
    return "\n".join(lines)


def caregiver_guidance(episodes: list[dict]) -> str:
    """Return caregiver-directed safety guidance after sustained distress."""
    clean = [episode for episode in (episodes or []) if isinstance(episode, dict)]
    long_episode = any(
        isinstance(episode.get("duration_s"), (int, float))
        and episode["duration_s"] >= 600
        for episode in clean[:1]
    )
    repeated_unsettled = (
        len(clean) >= 3
        and all(episode.get("worked") is not True for episode in clean[:3])
    )
    if not (long_episode or repeated_unsettled):
        return ""
    return (
        "If you are getting overwhelmed, it is okay to place your baby on their "
        "back in a safe place, such as an empty crib, and step away for a few minutes. "
        "Take a breath and return when you feel ready. If you are worried about the "
        "crying, consider talking to your pediatrician."
    )


def guidance_card(payload: dict) -> str:
    """Render structured history evidence without exposing debug scores."""
    if not isinstance(payload, dict):
        return "Guidance is unavailable."

    status = payload.get("status")
    if status == "insufficient_history":
        count = payload.get("history_count")
        count = count if isinstance(count, int) and count >= 0 else 0
        return (
            "Not enough history yet.\n"
            f"{count} usable incidents recorded. Six are needed before a pattern is shown."
        )
    if status == "no_helpful_history":
        return (
            "No recorded action to repeat yet.\n"
            "Add an outcome after this incident so the history can become more useful."
        )
    if status != "grounded":
        return "Guidance is unavailable."

    action = payload.get("action")
    if not isinstance(action, str) or not action.strip():
        return "No recorded action to repeat yet."
    support = payload.get("support_count")
    support = support if isinstance(support, int) and support > 0 else 0
    noun = "incident" if support == 1 else "incidents"
    lines = [
        "What helped before",
        f"Previously helpful: {action.strip()}.",
        f"Recorded as the final action in {support} prior {noun}.",
    ]

    outcomes = payload.get("outcomes")
    if isinstance(outcomes, list) and outcomes:
        first = outcomes[0] if isinstance(outcomes[0], dict) else {}
        text = first.get("text")
        source = {
            "caregiver": "caregiver reported",
            "inferred": "inferred from transcript",
            "seed": "synthetic demo data",
        }.get(first.get("source"))
        if isinstance(text, str) and text.strip() and source:
            lines.append(f"Recorded outcome ({source}): {text.strip()}")

    pattern = payload.get("pattern")
    if isinstance(pattern, str) and pattern.strip():
        lines.append(f"Possible repeated context: {pattern.strip()}.")
    lines.append("Based on this profile's recorded history, not a diagnosis.")
    return "\n".join(lines)


def identity_card(payload: dict) -> str:
    """Render identity state while revealing a profile only for an accepted match."""
    if not isinstance(payload, dict):
        return "Identity result unavailable."

    status = payload.get("status")
    reasons = {
        reason
        for reason in (payload.get("reasons") or [])
        if isinstance(reason, str)
    }
    if status == "match":
        name = payload.get("display_name")
        if not isinstance(name, str) or not name.strip():
            return "Identity result unavailable."
        band = payload.get("band")
        band_label = f"{band.upper()} ACOUSTIC MATCH" if band in {"strong", "weak"} else "MATCH"
        return f"{band_label}\n{name.strip()}"

    if status == "invalid":
        if reasons & {"near_silence", "no_usable_voiced_audio", "insufficient_voiced_audio"}:
            return (
                "The recording was too quiet to analyze.\n"
                "Move the sound closer or play it louder, then record again."
            )
        if reasons & {"clipping", "unsafe_normalization_headroom"}:
            return (
                "The recording was distorted.\n"
                "Lower the playback volume slightly, then record again."
            )
        return "That recording could not be analyzed. Record a fresh sample."

    if status == "unresolved":
        return (
            "The system could not identify this recording after two attempts.\n"
            "Choose an existing profile explicitly, or leave it unresolved."
        )

    if status == "uncertain":
        if "only_one_enrolled_profile" in reasons:
            return (
                "A comparison is required before identity can be tested.\n"
                "Enroll a second profile of this type, then record the query."
            )
        if "close_top_profiles" in reasons:
            message = "The recording could not separate the enrolled profiles."
        elif "ambiguous_source_type" in reasons:
            message = "The source type was ambiguous, so no profile was named."
        else:
            message = "There was not enough acoustic evidence to name a profile."
        if payload.get("retry_allowed") is True:
            message += "\nRecord one more independent sample."
        return message

    return "Identity result unavailable."
