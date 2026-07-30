"""Speech-path interfaces for the interaction-memory prototype."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

try:
    from . import config
except ImportError:
    import config

logger = logging.getLogger(__name__)

_INTERVENTION_PATTERNS = (
    (
        "checked diaper",
        re.compile(
            r"\b(?:checked|check|changed|change)"
            r"(?:\s+(?:his|her|their|the))?\s+diaper\b",
            re.IGNORECASE,
        ),
    ),
    (
        "offered feeding",
        re.compile(
            r"\b(?:(?:fed|feeding)\s+(?:him|her|them)|"
            r"(?:fed|feeding|offered|gave|tried|try)"
            r"(?:\s+(?:him|her|them))?(?:\s+(?:a|the))?"
            r"\s+(?:bottle|breast|milk))\b",
            re.IGNORECASE,
        ),
    ),
    ("burped", re.compile(r"\b(?:burped|burping|tried to burp)\b", re.IGNORECASE)),
    (
        "held",
        re.compile(
            r"\b(?:held|holding|picked\s+(?:him|her|them)\s+up)\b",
            re.IGNORECASE,
        ),
    ),
    ("rocked", re.compile(r"\brock(?:ed|ing)\b", re.IGNORECASE)),
    ("walked", re.compile(r"\bwalk(?:ed|ing)(?:\s+with)?\b", re.IGNORECASE)),
    (
        "offered pacifier",
        re.compile(
            r"\b(?:(?:offered|gave|used|use)"
            r"(?:\s+(?:him|her|them))?(?:\s+(?:a|the))?\s+)?"
            r"(?:pacifier|dummy|soother)\b",
            re.IGNORECASE,
        ),
    ),
    ("swaddled", re.compile(r"\bswaddl(?:ed|ing)\b", re.IGNORECASE)),
    (
        "changed environment",
        re.compile(
            r"\b(?:went|moved|took)(?:\s+\w+){0,5}"
            r"\s+(?:outside|room|quiet place)\b",
            re.IGNORECASE,
        ),
    ),
)

_NEGATED_ACTION = re.compile(
    r"\b(?:did\s+not|didn't|never|not|no)\b(?:\W+\w+){0,4}\W*$",
    re.IGNORECASE,
)

_OUTCOME_PATTERNS = (
    (
        False,
        re.compile(
            r"\b(?:did\s+not\s+work|didn't\s+work|still\s+crying|still\s+upset|"
            r"nothing\s+worked|not\s+working|kept\s+crying)\b",
            re.IGNORECASE,
        ),
    ),
    (
        True,
        re.compile(
            r"\b(?:settled(?:(?:\s+right)?\s+down)?|stopped\s+crying|calmed\s+down|"
            r"fell\s+asleep|that\s+worked)\b",
            re.IGNORECASE,
        ),
    ),
)


def _get_client():
    """Build an OpenAI client from the existing environment or configured .env."""
    from dotenv import dotenv_values
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and os.path.isfile(config.OPENAI_ENV_PATH):
        api_key = dotenv_values(config.OPENAI_ENV_PATH).get("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key, timeout=30.0, max_retries=1)


def _reason_json(instructions: str, payload: str) -> dict | None:
    """Call the configured reasoning model and parse one JSON object."""
    try:
        client = _get_client()
        if client is None:
            return None
        response = client.responses.create(
            model=config.REASONING_MODEL,
            instructions=instructions,
            input=f"Return one JSON object only.\n\n{payload}",
            text={"format": {"type": "json_object"}},
        )
        raw = getattr(response, "output_text", "")
        parsed = json.loads(raw) if raw else None
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        logger.exception("Reasoning-model JSON request failed")
        return None


def _transcribe_offline(wav_path: str) -> str:
    """Transcribe locally with the installed Whisper CLI."""
    try:
        with tempfile.TemporaryDirectory() as output_dir:
            completed = subprocess.run(
                [
                    "whisper",
                    wav_path,
                    "--model",
                    os.environ.get("IM_WHISPER_MODEL", "turbo"),
                    "--output_dir",
                    output_dir,
                    "--output_format",
                    "txt",
                    "--verbose",
                    "False",
                    "--fp16",
                    "False",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,
                check=False,
            )
            if completed.returncode != 0:
                details = completed.stderr.strip().splitlines()
                logger.error(
                    "Local Whisper failed: %s",
                    details[-1] if details else "unknown error",
                )
                return ""
            transcript_path = Path(output_dir) / f"{Path(wav_path).stem}.txt"
            if not transcript_path.is_file():
                return ""
            return transcript_path.read_text(encoding="utf-8").strip()
    except (OSError, subprocess.SubprocessError):
        logger.exception("Local Whisper transcription failed for %s", wav_path)
        return ""


def transcribe(wav_path: str) -> str:
    """Transcribe caregiver speech from the raw, unseparated audio mixture.

    Returns an empty string on failure and never raises.
    """
    if not wav_path or not os.path.isfile(wav_path):
        return ""
    if config.OFFLINE:
        return _transcribe_offline(wav_path)
    try:
        client = _get_client()
        if client is None:
            return ""
        with open(wav_path, "rb") as audio:
            response = client.audio.transcriptions.create(
                model=config.TRANSCRIBE_MODEL,
                file=audio,
            )
        text = response if isinstance(response, str) else getattr(response, "text", "")
        return text.strip() if isinstance(text, str) else ""
    except Exception:
        logger.exception("Transcription failed for %s", wav_path)
        return ""


def _action_is_negated(transcript: str, start: int) -> bool:
    sentence_start = max(
        transcript.rfind(".", 0, start),
        transcript.rfind("!", 0, start),
        transcript.rfind("?", 0, start),
        transcript.rfind(";", 0, start),
    )
    prefix = transcript[sentence_start + 1 : start]
    return bool(_NEGATED_ACTION.search(prefix[-80:]))


def _extract_interventions_local(transcript: str) -> list[dict]:
    matches = []
    for action, pattern in _INTERVENTION_PATTERNS:
        for match in pattern.finditer(transcript):
            if _action_is_negated(transcript, match.start()):
                continue
            matches.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "action": action,
                    "evidence": match.group(0),
                }
            )

    matches.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))
    grounded = []
    for item in matches:
        if any(
            item["start"] < kept["end"] and kept["start"] < item["end"]
            for kept in grounded
        ):
            continue
        grounded.append(item)
    return [
        {
            "order": order,
            "action": item["action"],
            "evidence": item["evidence"],
        }
        for order, item in enumerate(grounded, start=1)
    ]


def _infer_outcome_local(
    transcript: str,
    interventions: list[dict],
) -> dict | None:
    final_intervention_end = -1
    for item in interventions if isinstance(interventions, list) else []:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, str) or not evidence:
            continue
        position = transcript.find(evidence)
        if position >= 0:
            final_intervention_end = max(final_intervention_end, position + len(evidence))

    outcomes = []
    for worked, pattern in _OUTCOME_PATTERNS:
        for match in pattern.finditer(transcript):
            if final_intervention_end >= 0 and match.start() < final_intervention_end:
                continue
            outcomes.append((match.start(), match.group(0), worked))
    if not outcomes:
        return None
    _, evidence, worked = max(outcomes, key=lambda item: item[0])
    return {"outcome": evidence, "worked": worked}


def extract_interventions(transcript: str) -> list[dict]:
    """Return ordered, transcript-grounded caregiver interventions.

    Every returned item must contain a literal ``evidence`` span copied from
    the transcript. Unsupported actions are omitted.
    """
    if not isinstance(transcript, str) or not transcript.strip():
        return []
    if config.OFFLINE:
        return _extract_interventions_local(transcript)
    result = _reason_json(
        (
            "Extract only caregiver actions explicitly supported by the transcript. "
            "Do not infer causes, diagnoses, intentions, or unspoken actions. Return JSON "
            'as {"interventions":[{"order":1,"action":"short verb phrase",'
            '"evidence":"exact verbatim transcript span"}]}. Every evidence value must be '
            "copied exactly from the transcript. Return an empty array when unsupported."
        ),
        transcript,
    )
    items = result.get("interventions", []) if isinstance(result, dict) else []
    if not isinstance(items, list):
        return _extract_interventions_local(transcript)

    grounded = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        evidence = item.get("evidence")
        if not isinstance(action, str) or not action.strip():
            continue
        if not isinstance(evidence, str) or not evidence.strip():
            continue
        position = transcript.find(evidence)
        if position < 0:
            continue
        key = (action.strip().casefold(), evidence)
        if key in seen:
            continue
        seen.add(key)
        grounded.append((position, action.strip(), evidence))

    grounded.sort(key=lambda value: value[0])
    validated = [
        {"order": order, "action": action, "evidence": evidence}
        for order, (_, action, evidence) in enumerate(grounded, start=1)
    ]
    return validated or _extract_interventions_local(transcript)


def infer_outcome(
    transcript: str,
    interventions: list[dict],
) -> dict | None:
    """Infer a fallback outcome only when the transcript explicitly supports it.

    Returns ``{"outcome": str, "worked": bool}`` or ``None`` rather than
    guessing. Callers label a non-empty result with ``outcome_src="inferred"``.
    """
    if not isinstance(transcript, str) or not transcript.strip():
        return None
    if config.OFFLINE:
        return _infer_outcome_local(transcript, interventions)
    result = _reason_json(
        (
            "Determine whether the transcript explicitly says what happened after the "
            "caregiver's actions. Do not infer a cause or guess success from an action "
            "alone. Return JSON with outcome, worked, and evidence, where evidence is an "
            "exact verbatim transcript span and worked is true or false. If the outcome "
            'is not explicit, return {"outcome":null,"worked":null,"evidence":null}.'
        ),
        json.dumps(
            {
                "transcript": transcript,
                "interventions": interventions if isinstance(interventions, list) else [],
            },
            ensure_ascii=False,
        ),
    )
    if not isinstance(result, dict):
        return _infer_outcome_local(transcript, interventions)
    evidence = result.get("evidence")
    worked = result.get("worked")
    if not isinstance(evidence, str) or not evidence.strip():
        return _infer_outcome_local(transcript, interventions)
    if evidence not in transcript or not isinstance(worked, bool):
        return _infer_outcome_local(transcript, interventions)
    return {"outcome": evidence, "worked": worked}
