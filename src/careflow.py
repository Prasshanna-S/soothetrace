"""Identity-gated orchestration of retrieval, guidance, and incident saving."""

from __future__ import annotations

import os
import threading

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


_COMPLETION_LOCK = threading.Lock()
_COMPLETIONS_IN_PROGRESS: set[int] = set()


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


def _attempt_already_completed(
    subject_id: str,
    attempt_id: int,
    db_path: str | None,
) -> bool:
    for episode in store.list_episodes(subject_id, db_path):
        episode_context = episode.get("context")
        if (
            isinstance(episode_context, dict)
            and episode_context.get("identity_attempt_id") == attempt_id
        ):
            return True
    return False


def _matched_subject(attempt: dict) -> tuple[int, str] | None:
    profile_id = attempt.get("matched_profile_id")
    if not isinstance(profile_id, int):
        profile_id = attempt.get("resolved_profile_id")
    if attempt.get("status") not in {"match", "matched"} or not isinstance(
        profile_id,
        int,
    ):
        return None
    return profile_id, f"profile-{profile_id}"


def _claim_completion(attempt_id: int) -> bool:
    with _COMPLETION_LOCK:
        if attempt_id in _COMPLETIONS_IN_PROGRESS:
            return False
        _COMPLETIONS_IN_PROGRESS.add(attempt_id)
        return True


def _release_completion(attempt_id: int) -> None:
    with _COMPLETION_LOCK:
        _COMPLETIONS_IN_PROGRESS.discard(attempt_id)


def _profile_incident_view(
    profile_id: int,
    canonical_audio: str,
    explicit_tags: list[str] | None,
    now: str | None,
    db_path: str | None,
    required_kind: str | None = None,
) -> dict:
    profile = identity.get_profile(profile_id, db_path)
    if (
        not profile
        or (required_kind is not None and profile.get("kind") != required_kind)
    ):
        return _error("resolved_profile_unavailable")
    if not canonical_audio or not os.path.isfile(canonical_audio):
        return _error("managed_capture_unavailable")

    acoustic = fingerprint.compute_windowed(canonical_audio)
    if not acoustic:
        return _error("capture_has_no_identity_signal")

    current_context = context.build_current_context(
        profile_id,
        now=now,
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
        "_canonical_audio": canonical_audio,
        "_current_context": current_context,
    }


def preview_profile_incident(
    profile_id: int,
    canonical_audio: str,
    explicit_tags: list[str] | None = None,
    now: str | None = None,
    db_path: str | None = None,
) -> dict:
    """Preview one infant profile's history without an identity-attempt row."""
    try:
        return _profile_incident_view(
            profile_id,
            canonical_audio,
            explicit_tags,
            now,
            db_path,
            required_kind=identity.KIND_INFANT,
        )
    except Exception:
        return _error("incident_preview_failed")


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
    matched = _matched_subject(attempt)
    if matched is None:
        return _error("identity_not_matched", status="blocked")
    profile_id, subject_id = matched

    canonical_audio = _latest_canonical_capture(attempt)
    result = _profile_incident_view(
        profile_id,
        canonical_audio,
        explicit_tags,
        None,
        db_path,
    )
    if result.get("status") == "preview":
        result["_profile_id"] = profile_id
        result["_subject_id"] = subject_id
    return result


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
    if (
        not isinstance(attempt_id, int)
        or isinstance(attempt_id, bool)
        or attempt_id <= 0
    ):
        return _error("invalid_attempt")

    attempt = _matched_attempt(attempt_id, db_path)
    matched = _matched_subject(attempt)
    if matched is not None:
        _, existing_subject_id = matched
        if _attempt_already_completed(existing_subject_id, attempt_id, db_path):
            return _error("incident_already_completed", status="conflict")

    if not _claim_completion(attempt_id):
        return _error("incident_already_completed", status="conflict")
    try:
        if matched is not None:
            _, existing_subject_id = matched
            if _attempt_already_completed(existing_subject_id, attempt_id, db_path):
                return _error("incident_already_completed", status="conflict")
        view = _incident_view(attempt_id, explicit_tags, db_path)
        if view.get("status") != "preview":
            return view
        profile_id = view["_profile_id"]
        subject_id = view["_subject_id"]
        canonical_audio = view["_canonical_audio"]
        current_context = view["_current_context"]
        saved_context = {
            **current_context,
            "identity_attempt_id": attempt_id,
            "profile_id": profile_id,
        }

        episode = session.finish(
            subject_id,
            canonical_audio,
            caregiver_answer,
            db_path=db_path,
            context_override=saved_context,
        )
        episode_id = episode.get("id") if isinstance(episode, dict) else None
        if not isinstance(episode_id, int):
            return _error("incident_save_failed")

        saved_episode = store.get_episode(episode_id, db_path) or episode
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
    finally:
        _release_completion(attempt_id)
