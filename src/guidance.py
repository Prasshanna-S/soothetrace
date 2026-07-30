"""Pure selection of history-grounded caregiver guidance.

This module does not generate actions. It selects one final action that already appears in
resolved, profile-isolated scenario evidence and returns the incident IDs that support it.
"""

from __future__ import annotations


MIN_HISTORY = 6
MAX_SCENARIOS = 3


def _base(profile_id: int, history_count: int) -> dict:
    return {
        "profile_id": profile_id,
        "status": "no_helpful_history",
        "headline": "No recorded action to repeat yet",
        "interpretation": "No repeated helpful pattern is recorded for this profile yet.",
        "recommendation": None,
        "evidence_summary": None,
        "history_count": history_count,
        "action": None,
        "support_count": 0,
        "incident_ids": [],
        "outcomes": [],
        "pattern": None,
    }


def _final_intervention(items) -> dict | None:
    valid = [
        item
        for item in (items or [])
        if isinstance(item, dict)
        and isinstance(item.get("action"), str)
        and item["action"].strip()
    ]
    if not valid:
        return None
    indexed = list(enumerate(valid))
    _, final = max(
        indexed,
        key=lambda pair: (
            pair[1].get("order")
            if isinstance(pair[1].get("order"), int)
            else pair[0] + 1
        ),
    )
    return final


def _nonnegative_int(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _numeric(value) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def build_guidance(
    profile_id: int,
    scenarios: list[dict],
    tally: list[dict],
    history_count: int,
    current_context: dict | None = None,
) -> dict:
    """Choose one previously helpful action without introducing new advice."""
    count = history_count if isinstance(history_count, int) and history_count >= 0 else 0
    result = _base(profile_id, count)
    if not isinstance(profile_id, int) or isinstance(profile_id, bool) or profile_id <= 0:
        return {**result, "status": "invalid", "headline": "Profile unavailable"}
    if count < MIN_HISTORY:
        return {
            **result,
            "status": "insufficient_history",
            "headline": "Not enough history yet",
            "interpretation": (
                "There is not enough profile history yet to compare this incident."
            ),
        }

    grouped: dict[str, dict] = {}
    for position, scenario in enumerate((scenarios or [])[:MAX_SCENARIOS]):
        if not isinstance(scenario, dict) or scenario.get("worked") is not True:
            continue
        final = _final_intervention(scenario.get("interventions"))
        if final is None:
            continue
        action = " ".join(final["action"].strip().casefold().split())
        if not action:
            continue
        slot = grouped.setdefault(
            action,
            {"action": action, "first": position, "scenarios": []},
        )
        slot["scenarios"].append(scenario)

    if not grouped:
        return result

    tally_by_action = {
        " ".join(item["action"].strip().casefold().split()): item
        for item in (tally or [])
        if isinstance(item, dict)
        and isinstance(item.get("action"), str)
        and item["action"].strip()
    }
    selected = min(
        grouped.values(),
        key=lambda item: (
            -len(item["scenarios"]),
            -_nonnegative_int(
                tally_by_action.get(item["action"], {}).get("worked_last")
            ),
            item["first"],
        ),
    )
    support = selected["scenarios"]
    incident_ids = [
        scenario.get("episode_id")
        for scenario in support
        if isinstance(scenario.get("episode_id"), int)
    ]
    outcomes = []
    for scenario in support:
        text = scenario.get("outcome")
        source = scenario.get("outcome_src")
        incident_id = scenario.get("episode_id")
        if (
            isinstance(text, str)
            and text.strip()
            and source in {"caregiver", "inferred", "seed"}
            and isinstance(incident_id, int)
        ):
            outcomes.append(
                {
                    "incident_id": incident_id,
                    "text": text.strip(),
                    "source": source,
                }
            )

    time_support = sum(
        1
        for scenario in support
        if _numeric((scenario.get("components") or {}).get("time_of_day")) >= 0.75
    )
    notes_support = sum(
        1
        for scenario in support
        if _numeric((scenario.get("components") or {}).get("notes")) >= 0.5
    )
    pattern = None
    if time_support >= 2:
        pattern = "similar time of day"
    elif notes_support >= 2:
        pattern = "similar caregiver context"

    support_count = len(support)
    incident_word = "incident" if support_count == 1 else "incidents"
    display_action = selected["action"].rstrip(" .")
    return {
        **result,
        "status": "grounded",
        "headline": "What helped before",
        "interpretation": "This resembles earlier incidents for this profile.",
        "recommendation": f"What helped before: {display_action}.",
        "evidence_summary": (
            f"Supported by {support_count} similar recorded {incident_word}."
        ),
        "action": selected["action"],
        "support_count": support_count,
        "incident_ids": incident_ids,
        "outcomes": outcomes,
        "pattern": pattern,
    }
