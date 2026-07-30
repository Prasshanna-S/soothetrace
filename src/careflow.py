"""Identity-gated orchestration of retrieval, guidance, and incident saving."""

from __future__ import annotations

import os

try:
    from . import context, fingerprint, guidance, identity, retrieve, session, store
except ImportError:
    import context
    import fingerprint
    import guidance
    import identity
    import retrieve
    import session
    import store


def _error(reason: str, status: str = "error") -> dict:
    return {"status": status, "reason": reason}


def _matched_attempt(attempt_id: int, db_path: str | None) -> dict:
    getter = getattr(identity, "get_identity_attempt", None)
    if not callable(getter):
        return {}
    try:
        return getter(attempt_id, db_path=db_path) or {}
    except Exception:
        return {}


def _latest_canonical_capture(attempt: dict) -> str:
    captures = attempt.get("captures")
    if not isinstance(captures, list) or not captures:
        return ""
    latest = captures[-1] if isinstance(captures[-1], dict) else {}
    path = latest.get("canonical_audio_path")
    return path if isinstance(path, str) else ""


def _incident_view(
    attempt_id: int,
    explicit_tags: list[str] | None,
    db_path: str | None,
) -> dict:
    if (
        not isinstance(attempt_id, int)
        or isinstance(attempt_id, bool)
        or attempt_id <= 0
    ):
        return _error("invalid_attempt")

    attempt = _matched_attempt(attempt_id, db_path)
    profile_id = attempt.get("matched_profile_id")
    if not isinstance(profile_id, int):
        profile_id = attempt.get("resolved_profile_id")
    if attempt.get("status") not in {"match", "matched"} or not isinstance(
        profile_id,
        int,
    ):
        return _error("identity_not_matched", status="blocked")

    profile = identity.get_profile(profile_id, db_path)
    if not profile:
        return _error("resolved_profile_unavailable")

    canonical_audio = _latest_canonical_capture(attempt)
    if not canonical_audio or not os.path.isfile(canonical_audio):
        return _error("managed_capture_unavailable")
    acoustic = fingerprint.compute_windowed(canonical_audio)
    if not acoustic:
        return _error("capture_has_no_identity_signal")

    current_context = context.build_current_context(
        profile_id,
        tags=explicit_tags,
        db_path=db_path,
    )
    if not current_context:
        return _error("context_unavailable")

    subject_id = f"profile-{profile_id}"
    scenarios = retrieve.find_scenarios(
        subject_id,
        acoustic,
        current_context,
        k=3,
        db_path=db_path,
    )
    history_count = retrieve.episode_count(subject_id, db_path)
    tally = retrieve.intervention_tally(subject_id, db_path)
    guidance_payload = guidance.build_guidance(
        profile_id,
        scenarios,
        tally,
        history_count,
        current_context,
    )
    return {
        "status": "preview",
        "identity": {
            "profile_id": profile_id,
            "display_name": profile.get("display_name"),
            "kind": profile.get("kind"),
        },
        "scenarios": scenarios,
        "guidance": guidance_payload,
        "_profile_id": profile_id,
        "_subject_id": subject_id,
        "_canonical_audio": canonical_audio,
        "_current_context": current_context,
    }


def preview_incident(
    attempt_id: int,
    explicit_tags: list[str] | None = None,
    db_path: str | None = None,
) -> dict:
    """Read matched-profile history and guidance without saving the current incident."""
    try:
        result = _incident_view(attempt_id, explicit_tags, db_path)
        if result.get("status") != "preview":
            return result
        return {
            key: result[key]
            for key in ("status", "identity", "scenarios", "guidance")
        }
    except Exception:
        return _error("incident_preview_failed")


def complete_incident(
    attempt_id: int,
    caregiver_answer: str | None,
    explicit_tags: list[str] | None = None,
    db_path: str | None = None,
) -> dict:
    """Complete one incident only after identity has resolved to a stored profile."""
    try:
        view = _incident_view(attempt_id, explicit_tags, db_path)
        if view.get("status") != "preview":
            return view
        profile_id = view["_profile_id"]
        subject_id = view["_subject_id"]
        canonical_audio = view["_canonical_audio"]
        current_context = view["_current_context"]

        episode = session.finish(
            subject_id,
            canonical_audio,
            caregiver_answer,
            db_path=db_path,
        )
        episode_id = episode.get("id") if isinstance(episode, dict) else None
        if not isinstance(episode_id, int):
            return _error("incident_save_failed")

        saved_context = {
            **current_context,
            "identity_attempt_id": attempt_id,
            "profile_id": profile_id,
        }
        store.update_episode(episode_id, db_path, context=saved_context)
        saved_episode = store.get_episode(episode_id, db_path) or {
            **episode,
            "context": saved_context,
        }
        return {
            "status": "complete",
            "identity": {
                "profile_id": profile_id,
                "display_name": view["identity"].get("display_name"),
                "kind": view["identity"].get("kind"),
            },
            "episode": saved_episode,
            "scenarios": view["scenarios"],
            "guidance": view["guidance"],
        }
    except Exception:
        return _error("incident_completion_failed")
