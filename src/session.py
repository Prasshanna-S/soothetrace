"""Recording and episode-finalization flow for interaction memory."""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
from datetime import datetime, timezone

try:
    from . import config, fingerprint, speech, store
except ImportError:
    import config
    import fingerprint
    import speech
    import store

logger = logging.getLogger(__name__)


def _explicit_worked(answer: str) -> bool | None:
    """Return valence only when the caregiver's own words state it explicitly."""
    normalized = " ".join(answer.casefold().replace("'", "'").split())
    negative_patterns = (
        r"\bnothing\s+(?:has\s+)?worked\b",
        r"\b(?:did|does)\s+not\s+work\b",
        r"\bdidn't\s+work\b",
        r"\bnot\s+(?:working|settled|settling|calmed|calming)\b",
        r"\bstill\s+(?:crying|upset|fussing)\b",
        r"\bcried\s+(?:himself|herself|themself|themselves)\s+out\b",
    )
    if any(re.search(pattern, normalized) for pattern in negative_patterns):
        return False
    positive_patterns = (
        r"\bworked\b",
        r"\bsettled(?:\s+down)?\b",
        r"\bstopped\s+crying\b",
        r"\bcalmed\s+down\b",
        r"\bfell\s+asleep\b",
    )
    if any(re.search(pattern, normalized) for pattern in positive_patterns):
        return True
    return None


def _capture_input_args(device: str | None = None) -> list[str]:
    """Return FFmpeg input arguments for the current desktop platform."""
    system = platform.system()
    configured = device if device is not None else os.environ.get("IM_AUDIO_DEVICE")
    if system == "Darwin":
        return ["-f", "avfoundation", "-i", configured or ":0"]
    if system == "Windows":
        if not configured:
            raise ValueError(
                "IM_AUDIO_DEVICE must name a Windows microphone for CLI recording"
            )
        name = configured.removeprefix("audio=")
        return ["-f", "dshow", "-i", f"audio={name}"]
    if system == "Linux":
        return ["-f", "alsa", "-i", configured or "default"]
    raise ValueError(f"unsupported microphone capture platform: {system or 'unknown'}")


def _capture_wav(output_path: str, seconds: float | None) -> bool:
    """Capture one canonical WAV through the platform's FFmpeg input backend."""
    try:
        capture_args = _capture_input_args()
    except ValueError as exc:
        logger.error("Microphone capture is not configured: %s", exc)
        return False
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        *capture_args,
    ]
    if seconds is not None:
        command.extend(["-t", str(seconds)])
    command.extend(
        [
            "-ac",
            "1",
            "-ar",
            str(config.SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            "-y",
            output_path,
        ]
    )
    try:
        if seconds is not None:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
            return completed.returncode == 0

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            input("Recording... press Enter to stop. ")
            _, _ = process.communicate(b"q\n", timeout=10)
        except (EOFError, KeyboardInterrupt):
            process.terminate()
            process.wait(timeout=10)
        return process.returncode == 0
    except (OSError, subprocess.SubprocessError):
        logger.exception("Microphone capture failed")
        return False


def record(subject_id: str, seconds: float | None = None) -> str:
    """Capture mic audio to a 16 kHz mono WAV and return its path.

    Returns an empty string on invalid input or capture failure.
    """
    if not isinstance(subject_id, str) or not subject_id.strip():
        return ""
    if seconds is not None and (
        not isinstance(seconds, (int, float)) or seconds <= 0
    ):
        return ""

    safe_subject = re.sub(r"[^A-Za-z0-9._-]+", "-", subject_id.strip()).strip("-")
    if not safe_subject:
        return ""
    os.makedirs(config.AUDIO_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_path = os.path.join(config.AUDIO_DIR, f"{safe_subject}-{timestamp}.wav")

    if not _capture_wav(output_path, float(seconds) if seconds is not None else None):
        try:
            os.remove(output_path)
        except OSError:
            pass
        return ""
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        return ""
    return output_path


def finish(
    subject_id: str,
    audio_path: str,
    caregiver_answer: str | None,
    *,
    db_path: str | None = None,
    context_override: dict | None = None,
) -> dict:
    """Finalize one episode from the raw recording and return the saved Episode."""
    if (
        not isinstance(subject_id, str)
        or not subject_id.strip()
        or not isinstance(audio_path, str)
        or not os.path.isfile(audio_path)
    ):
        return {}
    try:
        started_at = datetime.now(timezone.utc).astimezone().isoformat()
        previous = store.latest_episode(subject_id, db_path)
        acoustic = fingerprint.compute_windowed(audio_path)
        audio_transcript = speech.transcribe(audio_path)
        answer = caregiver_answer.strip() if isinstance(caregiver_answer, str) else ""
        if answer:
            evidence_parts = []
            if audio_transcript:
                evidence_parts.append(f"Audio transcript: {audio_transcript}")
            evidence_parts.append(f"Typed caregiver follow-up: {answer}")
            transcript = "\n".join(evidence_parts)
        else:
            transcript = audio_transcript
        interventions = speech.extract_interventions(transcript)

        if answer:
            outcome = answer
            outcome_src = "caregiver"
            worked = _explicit_worked(answer)
        else:
            inferred = speech.infer_outcome(transcript, interventions)
            if inferred:
                outcome = inferred["outcome"]
                outcome_src = "inferred"
                worked = inferred["worked"]
            else:
                outcome = None
                outcome_src = None
                worked = None

        episode_context = (
            dict(context_override)
            if isinstance(context_override, dict)
            else fingerprint.build_context(
                started_at,
                previous.get("started_at") if previous else None,
                subject_age_days=None,
            )
        )
        episode = {
            "id": None,
            "subject_id": subject_id.strip(),
            "started_at": started_at,
            "duration_s": fingerprint.duration_s(audio_path),
            "audio_path": audio_path,
            "fingerprint": acoustic,
            "transcript": transcript,
            "interventions": interventions,
            "outcome": outcome,
            "outcome_src": outcome_src,
            "worked": worked,
            "context": episode_context,
        }
        episode_id = store.save_episode(episode, db_path)
        if not episode_id:
            return episode
        saved = store.get_episode(episode_id, db_path)
        return saved or {**episode, "id": episode_id}
    except Exception:
        logger.exception("Episode finalization failed for %s", audio_path)
        return {}


def finish_structured(
    subject_id: str,
    audio_path: str,
    action: str,
    settled: bool | None,
    notes: str | None,
    *,
    started_at: str,
    db_path: str | None = None,
    context_override: dict | None = None,
    transcribe_audio: bool = True,
) -> dict:
    """Save one deterministic caregiver outcome for a representative segment."""
    clean_action = action.strip() if isinstance(action, str) else ""
    if (
        not isinstance(subject_id, str)
        or not subject_id.strip()
        or not isinstance(audio_path, str)
        or not os.path.isfile(audio_path)
        or not clean_action
        or len(clean_action) > 500
        or (settled is not None and type(settled) is not bool)
        or (notes is not None and not isinstance(notes, str))
        or not isinstance(started_at, str)
        or not started_at.strip()
    ):
        return {}
    clean_notes = notes.strip() if isinstance(notes, str) else ""
    if len(clean_notes) > 1000:
        return {}

    try:
        previous = store.latest_episode(subject_id.strip(), db_path)
        acoustic = fingerprint.compute_windowed(audio_path)
        audio_transcript = (
            speech.transcribe(audio_path).strip()
            if transcribe_audio
            else ""
        )
        extracted = (
            speech.extract_interventions(audio_transcript)
            if audio_transcript
            else []
        )

        intervention_pairs = []
        seen_pairs = set()
        structured_pair = (clean_action, clean_action)
        for item in extracted if isinstance(extracted, list) else []:
            if not isinstance(item, dict):
                continue
            extracted_action = item.get("action")
            evidence = item.get("evidence")
            if not isinstance(extracted_action, str) or not isinstance(evidence, str):
                continue
            pair = (extracted_action, evidence)
            if pair == structured_pair or pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            intervention_pairs.append(pair)
        intervention_pairs.append(structured_pair)
        interventions = [
            {"order": index, "action": item_action, "evidence": evidence}
            for index, (item_action, evidence) in enumerate(intervention_pairs, start=1)
        ]

        settled_label = {
            True: "yes",
            False: "no",
            None: "not recorded",
        }[settled]
        typed_follow_up = f"Action: {clean_action} Settled: {settled_label}."
        if clean_notes:
            typed_follow_up += f" Notes: {clean_notes}"
        transcript_parts = []
        if audio_transcript:
            transcript_parts.append(f"Audio transcript: {audio_transcript}")
        transcript_parts.append(f"Typed caregiver follow-up: {typed_follow_up}")
        transcript = "\n".join(transcript_parts)

        outcome = {
            True: "The baby settled.",
            False: "The baby did not settle.",
            None: "Whether the baby settled was not recorded.",
        }[settled]
        if clean_notes:
            outcome += f" {clean_notes}"

        episode_context = (
            dict(context_override)
            if isinstance(context_override, dict)
            else fingerprint.build_context(
                started_at,
                previous.get("started_at") if previous else None,
                subject_age_days=None,
            )
        )
        episode = {
            "id": None,
            "subject_id": subject_id.strip(),
            "started_at": started_at,
            "duration_s": fingerprint.duration_s(audio_path),
            "audio_path": audio_path,
            "fingerprint": acoustic,
            "transcript": transcript,
            "interventions": interventions,
            "outcome": outcome,
            "outcome_src": "caregiver",
            "worked": settled,
            "context": episode_context,
        }
        episode_id = store.save_episode(episode, db_path)
        if not episode_id:
            return episode
        saved = store.get_episode(episode_id, db_path)
        return saved or {**episode, "id": episode_id}
    except Exception:
        logger.exception("Structured episode finalization failed for %s", audio_path)
        return {}
