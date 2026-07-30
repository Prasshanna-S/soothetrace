"""Local product API for the iPhone client and laptop inference server."""

from __future__ import annotations

import argparse
import ipaddress
import json
import shutil
import sqlite3
import ssl
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from . import (
        audio_ingest,
        care_sessions,
        careflow,
        config,
        cry_gate,
        encoders,
        identity,
        live_sessions,
        store,
    )
except ImportError:
    import audio_ingest
    import care_sessions
    import careflow
    import config
    import cry_gate
    import encoders
    import identity
    import live_sessions
    import store


MAX_JSON_BYTES = 64 * 1024
_INFERENCE_LOCK = threading.Lock()


def _is_loopback_host(host: str) -> bool:
    if not isinstance(host, str):
        return False
    normalized = host.strip().casefold()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _profile_public(profile: dict) -> dict:
    return {
        key: profile.get(key)
        for key in ("id", "display_name", "kind", "status", "enrollments")
    }


def _public_identity(attempt: dict, db_path: str | None) -> dict:
    if not isinstance(attempt, dict):
        return {"status": "invalid", "retry_allowed": False, "reasons": ["invalid_result"]}
    capture = {}
    captures = attempt.get("captures")
    if isinstance(captures, list) and captures and isinstance(captures[-1], dict):
        capture = captures[-1]

    attempt_status = attempt.get("status")
    capture_status = attempt.get("capture_status") or capture.get("status")
    if attempt_status == "match":
        public_status = "match"
    elif attempt_status == "unresolved":
        public_status = "unresolved"
    elif capture_status == "invalid":
        public_status = "invalid"
    else:
        public_status = "uncertain"

    reasons = attempt.get("reasons")
    if not isinstance(reasons, list):
        reasons = capture.get("reasons")
    if not isinstance(reasons, list):
        reasons = []
    payload = {
        "attempt_id": attempt.get("id"),
        "status": public_status,
        "kind": attempt.get("kind"),
        "band": capture.get("band") if public_status == "match" else "none",
        "retry_allowed": bool(attempt.get("retry_allowed")) if public_status == "uncertain" else False,
        "reasons": [reason for reason in reasons if isinstance(reason, str)],
        "resolution_path": attempt.get("resolution_path"),
        "resolution_source": attempt.get("resolution_source"),
    }
    matched_profile_id = attempt.get("matched_profile_id")
    if not isinstance(matched_profile_id, int):
        matched_profile_id = attempt.get("resolved_profile_id")
    if public_status == "match" and isinstance(matched_profile_id, int):
        profile = identity.get_profile(matched_profile_id, db_path)
        if profile:
            payload["profile"] = _profile_public(profile)
    new_profile_candidate = {
        "below_accept_threshold",
        "new_or_unenrolled_source",
    }.issubset(set(reasons))
    if "new_profile_candidate_confirmed" in reasons:
        payload["novelty"] = "confirmed_new_profile"
    elif public_status == "uncertain" and new_profile_candidate:
        payload["novelty"] = "candidate_new_profile"
    closest_profile_id = capture.get("top_profile_id")
    if not isinstance(closest_profile_id, int):
        closest_profile_id = attempt.get("nominated_profile_id")
    pool_size = capture.get("pool_size")
    if (
        public_status in {"uncertain", "unresolved"}
        and isinstance(closest_profile_id, int)
        and isinstance(pool_size, int)
        and pool_size >= 1
    ):
        profile = identity.get_profile(closest_profile_id, db_path)
        if profile:
            closest = _profile_public(profile)
            payload["closest_profile"] = closest
            if not new_profile_candidate:
                payload["leaning_profile"] = closest
            if new_profile_candidate:
                payload["direction"] = "outside_profiles_not_confirmed"
            elif "close_top_profiles" in reasons:
                payload["direction"] = "close_call_not_confirmed"
            else:
                payload["direction"] = "clear_lead_not_confirmed"
    return payload


def _public_incident(result: dict) -> dict:
    episode = result.get("episode") if isinstance(result.get("episode"), dict) else {}
    episode_id = episode.get("id")
    public_episode = {
        key: episode.get(key)
        for key in (
            "id",
            "started_at",
            "duration_s",
            "transcript",
            "interventions",
            "outcome",
            "outcome_src",
            "worked",
            "context",
        )
    }
    if isinstance(episode_id, int):
        public_episode["audio_url"] = f"/api/audio/episodes/{episode_id}"

    public_scenarios = []
    for scenario in result.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        scenario_id = scenario.get("episode_id")
        visible = {
            key: scenario.get(key)
            for key in (
                "episode_id",
                "band",
                "started_at",
                "interventions",
                "outcome",
                "outcome_src",
                "worked",
                "contributions",
            )
        }
        if isinstance(scenario_id, int):
            visible["audio_url"] = f"/api/audio/episodes/{scenario_id}"
        public_scenarios.append(visible)

    payload = {
        "status": result.get("status"),
        "identity": result.get("identity"),
        "scenarios": public_scenarios,
        "guidance": result.get("guidance"),
    }
    if episode:
        payload["episode"] = public_episode
    return payload


def _public_live_participant(participant) -> dict | None:
    if not isinstance(participant, dict):
        return None
    return _public_live_scalars(
        participant,
        {
            "id": (int, False),
            "profile_id": (int, False),
            "display_name": (str, True),
            "state": (str, True),
            "support_count": (int, False),
            "created_at": (str, True),
            "established_at": (str, True),
        },
    )


def _public_live_scalars(source: dict, fields: dict) -> dict:
    public = {}
    for key, (expected_type, nullable) in fields.items():
        if key not in source:
            continue
        value = source[key]
        if value is None and nullable:
            public[key] = None
        elif type(value) is expected_type:
            public[key] = value
    return public


def _public_live_observation(observation) -> dict | None:
    if not isinstance(observation, dict):
        return None
    reason_codes = observation.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = []
    public = _public_live_scalars(
        observation,
        {
            "id": (int, False),
            "sequence": (int, False),
            "created_at": (str, True),
            "source_type": (str, True),
            "status": (str, True),
            "participant_id": (int, True),
            "closest_participant_id": (int, True),
            "reinforced": (bool, False),
        },
    )
    for key in ("participant", "closest_participant"):
        value = observation.get(key)
        if value is None:
            public[key] = None
        elif isinstance(value, dict):
            public[key] = _public_live_participant(value)
    public["reason_codes"] = [
        reason for reason in reason_codes if type(reason) is str
    ]
    observation_id = public.get("id")
    if type(observation_id) is int:
        public["playback_url"] = (
            f"/api/audio/live-observations/{observation_id}"
        )
    return public


def _public_live_session(session) -> dict:
    if not isinstance(session, dict):
        return {}
    participants = session.get("participants")
    if not isinstance(participants, list):
        participants = []
    observations = session.get("observations")
    if not isinstance(observations, list):
        observations = []
    public = _public_live_scalars(
        session,
        {
            "id": (int, False),
            "kind": (str, True),
            "status": (str, True),
            "created_at": (str, True),
            "completed_at": (str, True),
        },
    )
    public["participants"] = [
        rendered
        for participant in participants
        if (rendered := _public_live_participant(participant)) is not None
    ]
    public["observations"] = [
        rendered
        for observation in observations
        if (rendered := _public_live_observation(observation)) is not None
    ]
    return public


def _public_live_classification(classification) -> dict:
    if not isinstance(classification, dict):
        classification = {}
    reason_codes = classification.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = []
    public = _public_live_scalars(
        classification,
        {
            "status": (str, True),
            "reinforced": (bool, False),
        },
    )
    participant = classification.get("participant")
    if participant is None:
        public["participant"] = None
    elif isinstance(participant, dict):
        public["participant"] = _public_live_participant(participant)
    public["reason_codes"] = [
        reason for reason in reason_codes if type(reason) is str
    ]
    return public


def _public_live_result(result: dict) -> dict:
    if not isinstance(result, dict):
        result = {}
    return {
        "session": _public_live_session(result.get("session")),
        "observation": _public_live_observation(result.get("observation")),
        "classification": _public_live_classification(
            result.get("classification")
        ),
    }


def _live_invalid_result(session: dict, reason: str) -> dict:
    return _public_live_result(
        {
            "session": session,
            "observation": None,
            "classification": {
                "status": "invalid",
                "participant": None,
                "reinforced": False,
                "reason_codes": [reason],
            },
        }
    )


def _live_completed_result(session: dict) -> dict:
    return _public_live_result(
        {
            "session": session,
            "observation": None,
            "classification": {
                "status": "session_completed",
                "participant": None,
                "reinforced": False,
                "reason_codes": ["session_completed"],
            },
        }
    )


def _safe_managed_file(path: str | None, data_root: Path) -> Path | None:
    if not isinstance(path, str) or not path:
        return None
    try:
        candidate = Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    managed_root = (data_root / "managed").resolve()
    if candidate == managed_root or managed_root not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def _public_care_profile(value) -> dict:
    if not isinstance(value, dict):
        return {}
    public = {}
    for field in ("id", "enrollments"):
        if type(value.get(field)) is int:
            public[field] = value[field]
    for field in ("display_name", "kind", "status"):
        if isinstance(value.get(field), str):
            public[field] = value[field]
    return public


def _public_care_guidance(value) -> dict:
    if not isinstance(value, dict):
        return {}
    public = {}
    for field in (
        "status",
        "headline",
        "interpretation",
        "recommendation",
        "evidence_summary",
        "pattern",
    ):
        if isinstance(value.get(field), str):
            public[field] = value[field]
    if type(value.get("support_count")) is int:
        public["support_count"] = value["support_count"]
    if isinstance(value.get("incident_ids"), list):
        public["incident_ids"] = [
            item for item in value["incident_ids"] if type(item) is int
        ]
    return public


def _public_care_intervention(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    if (
        type(value.get("order")) is not int
        or not isinstance(value.get("action"), str)
        or not isinstance(value.get("evidence"), str)
    ):
        return None
    return {
        "order": value["order"],
        "action": value["action"],
        "evidence": value["evidence"],
    }


def _public_care_scenario(value, profile_id: int) -> dict | None:
    if not isinstance(value, dict) or type(value.get("episode_id")) is not int:
        return None
    episode_id = value["episode_id"]
    public = {"episode_id": episode_id}
    if isinstance(value.get("started_at"), str):
        public["started_at"] = value["started_at"]
    if isinstance(value.get("interventions"), list):
        public["interventions"] = [
            rendered
            for item in value["interventions"]
            if (rendered := _public_care_intervention(item)) is not None
        ]
    for field in ("outcome", "outcome_src"):
        item = value.get(field)
        if field in value and (item is None or isinstance(item, str)):
            public[field] = item
    if value.get("worked") is None or type(value.get("worked")) is bool:
        if "worked" in value:
            public["worked"] = value["worked"]
    if isinstance(value.get("contributions"), list):
        public["contributions"] = [
            item for item in value["contributions"] if isinstance(item, str)
        ]
    public["audio_url"] = (
        f"/api/profiles/{profile_id}/incidents/{episode_id}/audio"
    )
    return public


def _public_care_decision(value) -> dict:
    if not isinstance(value, dict):
        return {}
    public = {}
    if type(value.get("id")) is int:
        public["id"] = value["id"]
    if isinstance(value.get("latched_at"), str):
        public["latched_at"] = value["latched_at"]
    profile = _public_care_profile(value.get("profile"))
    if profile:
        public["profile"] = {
            key: profile[key] for key in ("id", "display_name") if key in profile
        }
    guidance = _public_care_guidance(value.get("guidance"))
    if guidance:
        public["guidance"] = guidance
    if isinstance(value.get("basis"), list):
        public["basis"] = [
            item for item in value["basis"] if isinstance(item, str)
        ]
    profile_id = public.get("profile", {}).get("id")
    if type(profile_id) is int and isinstance(value.get("scenarios"), list):
        public["scenarios"] = [
            rendered
            for item in value["scenarios"]
            if (rendered := _public_care_scenario(item, profile_id)) is not None
        ]
    return public


def _public_care_session(value) -> dict:
    if not isinstance(value, dict) or type(value.get("id")) is not int:
        return {}
    public = {"id": value["id"]}
    if isinstance(value.get("status"), str):
        public["status"] = value["status"]
    profile = _public_care_profile(value.get("profile"))
    if profile:
        public["profile"] = profile
    for field in ("started_at", "paused_at", "stopped_at", "completed_at"):
        item = value.get(field)
        if field in value and (item is None or isinstance(item, str)):
            public[field] = item
    if type(value.get("last_sequence")) is int:
        public["last_sequence"] = value["last_sequence"]
    if isinstance(value.get("tags"), list):
        public["tags"] = [
            item for item in value["tags"] if isinstance(item, str)
        ]
    if value.get("decision") is None:
        public["decision"] = None
    elif isinstance(value.get("decision"), dict):
        public["decision"] = _public_care_decision(value["decision"])
    return public


def _public_care_result(value) -> dict:
    if not isinstance(value, dict):
        return {}
    session = _public_care_session(value.get("session"))
    if not session:
        return {}
    public = {"session": session}
    incident = value.get("incident")
    if isinstance(incident, dict) and type(incident.get("id")) is int:
        public_incident = {"id": incident["id"]}
        if isinstance(incident.get("detail_url"), str):
            public_incident["detail_url"] = incident["detail_url"]
        public["incident"] = public_incident
    return public


def _public_cry_presence(value) -> dict:
    if not isinstance(value, dict):
        return {}
    public = {}
    for field in ("status", "model_version"):
        if isinstance(value.get(field), str):
            public[field] = value[field]
    label = value.get("label")
    if "label" in value and (label is None or isinstance(label, str)):
        public["label"] = label
    if isinstance(value.get("reason_codes"), list):
        public["reason_codes"] = [
            item for item in value["reason_codes"] if isinstance(item, str)
        ]
    duration = value.get("analyzed_duration_s")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        public["analyzed_duration_s"] = duration
    if type(value.get("analysis_view_count")) is int:
        public["analysis_view_count"] = value["analysis_view_count"]
    return public


def _public_care_chunk(value) -> dict:
    if not isinstance(value, dict):
        return {}
    public = {}
    for field in ("id", "sequence"):
        if type(value.get(field)) is int:
            public[field] = value[field]
    for field in ("status", "created_at"):
        if isinstance(value.get(field), str):
            public[field] = value[field]
    if isinstance(value.get("reason_codes"), list):
        public["reason_codes"] = [
            item for item in value["reason_codes"] if isinstance(item, str)
        ]
    cry_presence = _public_cry_presence(value.get("cry_presence"))
    if cry_presence:
        public["cry_presence"] = cry_presence
    return public


def _public_care_chunk_result(value) -> dict:
    if not isinstance(value, dict):
        return {}
    session = _public_care_session(value.get("session"))
    chunk = _public_care_chunk(value.get("chunk"))
    if not session or not chunk:
        return {}
    return {"session": session, "chunk": chunk}


def _managed_capture_directory(ingested: dict, data_root: Path) -> Path | None:
    if not isinstance(ingested, dict):
        return None
    managed_root = (data_root / "managed").resolve()
    parents = set()
    for field in ("source_path", "canonical_path", "identity_path"):
        raw_path = ingested.get(field)
        if not isinstance(raw_path, str):
            continue
        try:
            path = Path(raw_path).resolve()
        except (OSError, RuntimeError):
            return None
        if path.parent.parent != managed_root:
            return None
        parents.add(path.parent)
    if len(parents) != 1:
        return None
    capture_dir = parents.pop()
    return capture_dir if capture_dir.is_dir() else None


def _cleanup_unsaved_ingest(ingested: dict, data_root: Path) -> None:
    capture_dir = _managed_capture_directory(ingested, data_root)
    if capture_dir is None:
        return
    try:
        shutil.rmtree(capture_dir)
    except OSError:
        return


def _care_chunk_owns_ingest(
    session_id: int,
    sequence: int,
    source_path: str | None,
    db_path: str | None,
) -> bool:
    if not isinstance(source_path, str):
        return False
    try:
        connection = sqlite3.connect(db_path or config.DB_PATH)
        row = connection.execute(
            "SELECT source_audio_path FROM care_session_chunk "
            "WHERE session_id=? AND sequence=?",
            (session_id, sequence),
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        try:
            connection.close()
        except (UnboundLocalError, sqlite3.Error):
            pass
    if not row or not isinstance(row[0], str):
        return False
    try:
        return Path(row[0]).resolve() == Path(source_path).resolve()
    except (OSError, RuntimeError):
        return False


def _is_pcm_wav(path: Path) -> bool:
    try:
        with wave.open(str(path), "rb") as handle:
            return (
                handle.getnchannels() == 1
                and handle.getsampwidth() == 2
                and handle.getframerate() == 16000
                and handle.getnframes() > 0
                and handle.getcomptype() == "NONE"
            )
    except (OSError, EOFError, wave.Error):
        return False


def _care_error_status(reason: str) -> int:
    if reason == "no_such_care_session":
        return 404
    if reason == "cry_detector_unavailable":
        return 503
    if reason in {
        "invalid_care_session_transition",
        "invalid_chunk_sequence",
        "sequence_conflict",
        "out_of_order_chunk",
        "no_matched_chunk",
    }:
        return 409
    if reason in {
        "invalid_care_session_profile",
        "invalid_care_session_completion",
    }:
        return 400
    return 500


def _enrollment_audio(enrollment_id: int, db_path: str | None) -> str | None:
    store.init_db(db_path)
    try:
        connection = sqlite3.connect(db_path or config.DB_PATH)
        row = connection.execute(
            "SELECT audio_path FROM enrollment WHERE id=?",
            (enrollment_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        try:
            connection.close()
        except (UnboundLocalError, sqlite3.Error):
            pass
    return row[0] if row else None


def _handler_factory(
    data_root: Path,
    static_root: Path,
    db_path: str | None,
    encoder_status: dict[str, bool] | None = None,
    cry_detector_status: bool | None = None,
):
    class ProductHandler(BaseHTTPRequestHandler):
        server_version = "InteractionMemory/0.1"

        def log_message(self, format, *args):
            return

        def _headers(self):
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")

        def _json(self, status: int, payload: dict):
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._headers()
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, reason: str):
            self._json(status, {"status": "error", "reason": reason})

        def _body(self, maximum: int) -> bytes:
            raw = self.headers.get("Content-Length")
            if raw is None:
                raise ValueError("content_length_required")
            try:
                length = int(raw)
            except ValueError as exc:
                raise ValueError("invalid_content_length") from exc
            if length < 0 or length > maximum:
                raise ValueError("request_body_too_large")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete_request_body")
            return body

        def _json_body(self) -> dict:
            body = self._body(MAX_JSON_BYTES)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("malformed_json") from exc
            if not isinstance(payload, dict):
                raise ValueError("json_object_required")
            return payload

        def _static(self, path: str) -> bool:
            name = {
                "/": "index.html",
                "/index.html": "index.html",
                "/app.js": "app.js",
                "/app.css": "app.css",
                "/manifest.webmanifest": "manifest.webmanifest",
            }.get(path)
            if name is None:
                return False
            asset = (static_root / name).resolve()
            if static_root.resolve() not in asset.parents or not asset.is_file():
                self._error(404, "not_found")
                return True
            body = asset.read_bytes()
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".webmanifest": "application/manifest+json",
            }.get(asset.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; connect-src 'self'; "
                "style-src 'self'; media-src 'self'; img-src 'self' data:; "
                "object-src 'none'; base-uri 'none'; form-action 'self'",
            )
            self._headers()
            self.end_headers()
            self.wfile.write(body)
            return True

        def _play_audio(self, path: str):
            parts = path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "audio"]:
                self._error(404, "not_found")
                return
            try:
                record_id = int(parts[3])
            except ValueError:
                self._error(404, "not_found")
                return
            if parts[2] == "episodes":
                episode = store.get_episode(record_id, db_path)
                stored_path = episode.get("audio_path") if episode else None
            elif parts[2] == "enrollments":
                stored_path = _enrollment_audio(record_id, db_path)
            elif parts[2] == "live-observations":
                stored_path = live_sessions.observation_audio_path(record_id, db_path)
            else:
                self._error(404, "not_found")
                return
            audio = _safe_managed_file(stored_path, data_root)
            if audio is None or (
                parts[2] == "live-observations" and audio.name != "canonical.wav"
            ):
                self._error(404, "audio_unavailable")
                return
            body = audio.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self._headers()
            self.end_headers()
            self.wfile.write(body)

        def _play_profile_incident_audio(self, profile_id: int, incident_id: int):
            episode = store.get_episode(incident_id, db_path)
            stored_path = (
                episode.get("audio_path")
                if episode
                and episode.get("subject_id") == f"profile-{profile_id}"
                else None
            )
            audio = _safe_managed_file(stored_path, data_root)
            if audio is None or not _is_pcm_wav(audio):
                self._error(404, "audio_unavailable")
                return
            body = audio.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self._headers()
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/health":
                store.init_db(db_path)
                if encoder_status is None:
                    available_encoders = set(encoders.available())
                    warmed = {
                        name: name in available_encoders
                        for name in identity.ENCODER_FOR_KIND.values()
                    }
                else:
                    warmed = encoder_status
                baseline = store.get_baseline(config.POPULATION_KEY, db_path)
                ffmpeg = shutil.which("ffmpeg") is not None
                database = Path(db_path or config.DB_PATH).is_file()
                infant = bool(warmed.get(identity.encoder_for(identity.KIND_INFANT)))
                imitation = bool(warmed.get(identity.encoder_for(identity.KIND_IMITATION)))
                infant_requires_baseline = encoders.needs_baseline(
                    identity.encoder_for(identity.KIND_INFANT)
                )
                infant_ready = infant and (
                    not infant_requires_baseline or bool(baseline)
                )
                ready = ffmpeg and database and infant_ready and imitation
                care_ready = (
                    ffmpeg
                    and database
                    and infant_ready
                    and cry_detector_status is True
                )
                self._json(
                    200,
                    {
                        "status": "ready" if ready else "degraded",
                        "offline": bool(config.OFFLINE),
                        "ffmpeg": ffmpeg,
                        "whisper": shutil.which("whisper") is not None,
                        "database": database,
                        "population_baseline": bool(baseline),
                        "encoders": {
                            "infant": infant,
                            "human_imitation": imitation,
                        },
                        "care": {
                            "ready": care_ready,
                            "cry_detector": {
                                "ready": cry_detector_status is True,
                                "model_version": config.CRY_GATE_MODEL_VERSION,
                            },
                        },
                        "capture": {
                            "https_required": True,
                            "max_upload_bytes": audio_ingest.MAX_UPLOAD_BYTES,
                        },
                    },
                )
                return
            if path == "/api/profiles":
                self._json(
                    200,
                    {"profiles": [_profile_public(p) for p in identity.list_profiles(db_path)]},
                )
                return
            parts = path.strip("/").split("/")
            if (
                len(parts) == 3
                and parts[:2] == ["api", "care-sessions"]
            ):
                try:
                    session_id = int(parts[2])
                except ValueError:
                    self._error(404, "care_session_not_found")
                    return
                if session_id <= 0:
                    self._error(404, "care_session_not_found")
                    return
                result = care_sessions.get(session_id, db_path)
                if result.get("status") == "error":
                    self._error(
                        _care_error_status(result.get("reason", "")),
                        result.get("reason", "care_session_storage_error"),
                    )
                    return
                self._json(200, {"session": _public_care_session(result)})
                return
            if (
                len(parts) == 6
                and parts[:2] == ["api", "profiles"]
                and parts[3] == "incidents"
                and parts[5] == "audio"
            ):
                try:
                    profile_id = int(parts[2])
                    incident_id = int(parts[4])
                except ValueError:
                    self._error(404, "audio_unavailable")
                    return
                if profile_id <= 0 or incident_id <= 0:
                    self._error(404, "audio_unavailable")
                    return
                self._play_profile_incident_audio(profile_id, incident_id)
                return
            if len(parts) == 3 and parts[:2] == ["api", "live-sessions"]:
                try:
                    session_id = int(parts[2])
                except ValueError:
                    self._error(404, "live_session_not_found")
                    return
                session = live_sessions.get(session_id, db_path)
                if not session:
                    self._error(404, "live_session_not_found")
                    return
                self._json(200, {"session": _public_live_session(session)})
                return
            if path.startswith("/api/audio/"):
                self._play_audio(path)
                return
            if self._static(path):
                return
            self._error(404, "not_found")

        def _ingest(self) -> dict:
            body = self._body(audio_ingest.MAX_UPLOAD_BYTES)
            return audio_ingest.ingest_audio(
                body,
                self.headers.get("Content-Type", ""),
                capture_metadata={
                    "capture_device_name": self.headers.get("X-Capture-Device", ""),
                    "user_agent": self.headers.get("User-Agent", ""),
                },
                storage_root=data_root,
            )

        def _profile_create(self):
            payload = self._json_body()
            name = payload.get("display_name")
            kind = payload.get("kind")
            if (
                not isinstance(name, str)
                or not name.strip()
                or kind not in {identity.KIND_INFANT, identity.KIND_IMITATION}
            ):
                self._error(400, "invalid_profile")
                return
            profile = identity.create_profile(name, kind, db_path)
            if not profile:
                self._error(500, "profile_create_failed")
                return
            self._json(201, {"profile": _profile_public(profile)})

        def _live_session_create(self):
            payload = self._json_body()
            kind = payload.get("kind", identity.KIND_IMITATION)
            session = live_sessions.create(kind, db_path)
            if not session:
                self._error(400, "invalid_live_session")
                return
            self._json(201, {"session": _public_live_session(session)})

        def _care_session_create(self):
            if cry_detector_status is not True:
                self._error(503, "cry_detector_unavailable")
                return
            payload = self._json_body()
            profile_id = payload.get("profile_id")
            tags = payload.get("tags")
            if (
                type(profile_id) is not int
                or profile_id <= 0
                or (
                    tags is not None
                    and (
                        not isinstance(tags, list)
                        or any(not isinstance(tag, str) for tag in tags)
                    )
                )
            ):
                self._error(400, "invalid_care_session_profile")
                return
            result = care_sessions.create(profile_id, tags, db_path)
            if result.get("status") == "error":
                reason = result.get("reason", "care_session_storage_error")
                self._error(_care_error_status(reason), reason)
                return
            self._json(201, {"session": _public_care_session(result)})

        def _care_transition(self, session_id: int, operation: str):
            self._json_body()
            function = {
                "pause": care_sessions.pause,
                "resume": care_sessions.resume,
                "stop": care_sessions.stop,
            }[operation]
            result = function(session_id, db_path)
            if result.get("status") == "error":
                reason = result.get("reason", "care_session_storage_error")
                self._error(_care_error_status(reason), reason)
                return
            self._json(200, {"session": _public_care_session(result)})

        def _care_chunk(self, session_id: int):
            raw_sequence = self.headers.get("X-Capture-Sequence")
            try:
                sequence = int(raw_sequence)
            except (TypeError, ValueError):
                self._error(400, "invalid_capture_sequence")
                return
            if sequence <= 0 or str(sequence) != raw_sequence.strip():
                self._error(400, "invalid_capture_sequence")
                return
            ingested = self._ingest()
            with _INFERENCE_LOCK:
                result = care_sessions.submit_chunk(
                    session_id,
                    sequence,
                    ingested,
                    db_path,
                )
            owned = _care_chunk_owns_ingest(
                session_id,
                sequence,
                ingested.get("source_path"),
                db_path,
            )
            if not owned:
                _cleanup_unsaved_ingest(ingested, data_root)
            if result.get("status") == "error":
                reason = result.get("reason", "care_session_storage_error")
                self._error(_care_error_status(reason), reason)
                return
            public = _public_care_chunk_result(result)
            if not public:
                self._error(500, "care_session_storage_error")
                return
            status = 422 if public["chunk"].get("status") == "invalid" else 201
            self._json(status, public)

        def _care_complete(self, session_id: int):
            payload = self._json_body()
            with _INFERENCE_LOCK:
                result = care_sessions.complete(
                    session_id,
                    payload.get("action"),
                    payload.get("settled"),
                    payload.get("notes"),
                    payload.get("tags"),
                    db_path,
                )
            if result.get("status") == "error":
                reason = result.get("reason", "care_session_storage_error")
                self._error(_care_error_status(reason), reason)
                return
            public = _public_care_result(result)
            if not public:
                self._error(500, "care_session_storage_error")
                return
            self._json(200, public)

        def _live_session_observe(self, session_id: int):
            session = live_sessions.get(session_id, db_path)
            if not session:
                self._error(404, "live_session_not_found")
                return
            if session.get("status") == live_sessions.SESSION_COMPLETED:
                self._json(409, _live_completed_result(session))
                return

            ingested = self._ingest()
            if ingested.get("status") != "ready":
                self._json(
                    422,
                    _live_invalid_result(
                        session,
                        ingested.get("reason", "invalid_audio"),
                    ),
                )
                return

            capture_source = self.headers.get("X-Capture-Source", "") or "upload"
            capture_metadata = {
                "source_path": ingested["source_path"],
                "canonical_path": ingested["canonical_path"],
                "identity_path": ingested["identity_path"],
                "source_audio_path": ingested["source_path"],
                "canonical_audio_path": ingested["canonical_path"],
                "identity_audio_path": ingested["identity_path"],
                "capture_source": capture_source,
                "capture_device_name": self.headers.get("X-Capture-Device", ""),
                "user_agent": self.headers.get("User-Agent", ""),
            }
            with _INFERENCE_LOCK:
                result = live_sessions.submit_observation(
                    session_id,
                    ingested["identity_path"],
                    capture_metadata=capture_metadata,
                    db_path=db_path,
                )
            if not result:
                self._error(500, "live_observation_failed")
                return
            status = result.get("classification", {}).get("status")
            if status == "session_completed":
                response_status = 409
            elif status == "invalid":
                response_status = 422
            else:
                response_status = 201
            self._json(response_status, _public_live_result(result))

        def _live_session_complete(self, session_id: int):
            session = live_sessions.complete(session_id, db_path)
            if not session:
                self._error(404, "live_session_not_found")
                return
            self._json(200, {"session": _public_live_session(session)})

        def _profile_enroll(self, profile_id: int):
            profile = identity.get_profile(profile_id, db_path)
            if not profile:
                self._error(404, "profile_not_found")
                return
            ingested = self._ingest()
            if ingested.get("status") != "ready":
                self._json(422, ingested)
                return
            with _INFERENCE_LOCK:
                result = identity.enroll(
                    profile_id,
                    ingested["identity_path"],
                    capture_device_name=self.headers.get("X-Capture-Device"),
                    source_type=profile.get("kind"),
                    db_path=db_path,
                )
            status = 201 if result.get("status") == "enrolled" else 422
            self._json(status, result)

        def _attempt_create(self):
            payload = self._json_body()
            attempt = identity.begin_identity_attempt(
                payload.get("kind"),
                candidate_profile_ids=payload.get("candidate_profile_ids"),
                db_path=db_path,
            )
            if "error" in attempt:
                self._error(400, attempt["error"])
                return
            self._json(
                201,
                {
                    "attempt": {
                        "id": attempt.get("id"),
                        "kind": attempt.get("kind"),
                        "status": attempt.get("status"),
                        "retry_allowed": bool(attempt.get("retry_allowed")),
                    }
                },
            )

        def _attempt_capture(self, attempt_id: int, retry: bool):
            ingested = self._ingest()
            if ingested.get("status") != "ready":
                self._json(
                    422,
                    {
                        "identity": {
                            "attempt_id": attempt_id,
                            "status": "invalid",
                            "retry_allowed": not retry,
                            "reasons": [ingested.get("reason", "invalid_audio")],
                            "band": "none",
                        }
                    },
                )
                return
            metadata = {
                **ingested,
                "source_audio_path": ingested["source_path"],
                "canonical_audio_path": ingested["canonical_path"],
            }
            function = (
                identity.retry_identity_attempt if retry else identity.add_identity_capture
            )
            with _INFERENCE_LOCK:
                result = function(
                    attempt_id,
                    ingested["identity_path"],
                    capture_metadata=metadata,
                    db_path=db_path,
                )
            if "error" in result:
                self._error(409, result["error"])
                return
            self._json(200, {"identity": _public_identity(result, db_path)})

        def _incident_complete(self, attempt_id: int):
            payload = self._json_body()
            answer = payload.get("caregiver_answer")
            tags = payload.get("tags")
            if answer is not None and not isinstance(answer, str):
                self._error(400, "invalid_caregiver_answer")
                return
            if tags is not None and (
                not isinstance(tags, list)
                or any(not isinstance(tag, str) for tag in tags)
            ):
                self._error(400, "invalid_tags")
                return
            with _INFERENCE_LOCK:
                result = careflow.complete_incident(
                    attempt_id,
                    answer,
                    explicit_tags=tags,
                    db_path=db_path,
                )
            if result.get("status") == "blocked":
                self._json(409, result)
            elif result.get("status") == "conflict":
                self._json(409, result)
            elif result.get("status") != "complete":
                self._json(422, result)
            else:
                self._json(200, _public_incident(result))

        def _incident_preview(self, attempt_id: int):
            payload = self._json_body()
            tags = payload.get("tags")
            if tags is not None and (
                not isinstance(tags, list)
                or any(not isinstance(tag, str) for tag in tags)
            ):
                self._error(400, "invalid_tags")
                return
            with _INFERENCE_LOCK:
                result = careflow.preview_incident(
                    attempt_id,
                    explicit_tags=tags,
                    db_path=db_path,
                )
            if result.get("status") == "blocked":
                self._json(409, result)
            elif result.get("status") != "preview":
                self._json(422, result)
            else:
                self._json(200, _public_incident(result))

        def do_POST(self):
            path = urlparse(self.path).path
            parts = path.strip("/").split("/")
            try:
                if path == "/api/live-sessions":
                    self._live_session_create()
                    return
                if path == "/api/care-sessions":
                    self._care_session_create()
                    return
                if (
                    len(parts) == 4
                    and parts[:2] == ["api", "care-sessions"]
                    and parts[3] in {
                        "chunks",
                        "pause",
                        "resume",
                        "stop",
                        "complete",
                    }
                ):
                    try:
                        session_id = int(parts[2])
                    except ValueError:
                        self._error(404, "care_session_not_found")
                        return
                    if session_id <= 0:
                        self._error(404, "care_session_not_found")
                        return
                    if parts[3] == "chunks":
                        self._care_chunk(session_id)
                    elif parts[3] == "complete":
                        self._care_complete(session_id)
                    else:
                        self._care_transition(session_id, parts[3])
                    return
                if (
                    len(parts) == 4
                    and parts[:2] == ["api", "live-sessions"]
                    and parts[3] in {"observations", "complete"}
                ):
                    try:
                        session_id = int(parts[2])
                    except ValueError:
                        self._error(404, "live_session_not_found")
                        return
                    if parts[3] == "observations":
                        self._live_session_observe(session_id)
                    else:
                        self._live_session_complete(session_id)
                    return
                if path == "/api/profiles":
                    self._profile_create()
                    return
                if (
                    len(parts) == 4
                    and parts[:2] == ["api", "profiles"]
                    and parts[3] == "enroll"
                ):
                    self._profile_enroll(int(parts[2]))
                    return
                if path == "/api/identity/attempts":
                    self._attempt_create()
                    return
                if (
                    len(parts) == 5
                    and parts[:3] == ["api", "identity", "attempts"]
                    and parts[4] in {"captures", "retry"}
                ):
                    self._attempt_capture(int(parts[3]), parts[4] == "retry")
                    return
                if (
                    len(parts) == 4
                    and parts[:2] == ["api", "incidents"]
                    and parts[3] in {"preview", "complete"}
                ):
                    if parts[3] == "preview":
                        self._incident_preview(int(parts[2]))
                    else:
                        self._incident_complete(int(parts[2]))
                    return
                self._error(404, "not_found")
            except ValueError as exc:
                reason = str(exc)
                status = 413 if reason == "request_body_too_large" else 400
                self._error(status, reason or "bad_request")

        def do_DELETE(self):
            path = urlparse(self.path).path
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["api", "care-sessions"]:
                try:
                    session_id = int(parts[2])
                except ValueError:
                    self._error(404, "care_session_not_found")
                    return
                if session_id <= 0:
                    self._error(404, "care_session_not_found")
                    return
                result = care_sessions.discard(session_id, data_root, db_path)
                if result.get("status") == "error":
                    reason = result.get("reason", "care_session_storage_error")
                    self._error(_care_error_status(reason), reason)
                    return
                self._json(200, {"session": _public_care_session(result)})
                return
            if len(parts) != 3 or parts[:2] != ["api", "profiles"]:
                self._error(404, "not_found")
                return
            try:
                profile_id = int(parts[2])
            except ValueError:
                self._error(404, "not_found")
                return
            if not identity.get_profile(profile_id, db_path):
                self._error(404, "profile_not_found")
                return
            result = identity.delete_profile(profile_id, db_path)
            if not result.get("deleted"):
                self._error(500, "profile_delete_failed")
                return
            self._json(200, result)

    return ProductHandler


def build_http_server(
    address,
    data_root,
    static_root,
    db_path: str | None = None,
    encoder_status: dict[str, bool] | None = None,
    cry_detector_status: bool | None = None,
):
    """Build the local product server. TLS wrapping is performed by the launcher."""
    audio_root = Path(data_root).resolve()
    web_root = Path(static_root).resolve()
    audio_root.mkdir(parents=True, exist_ok=True)
    store.init_db(db_path)
    return ThreadingHTTPServer(
        address,
        _handler_factory(
            audio_root,
            web_root,
            db_path,
            encoder_status,
            cry_detector_status,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve the Cry Memory phone client over trusted local HTTPS."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--data-root", default=config.AUDIO_DIR)
    parser.add_argument("--static-root", default="web")
    parser.add_argument("--db", default=config.DB_PATH)
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve plain HTTP for a laptop-only localhost demo",
    )
    parser.add_argument("--cert")
    parser.add_argument("--key")
    args = parser.parse_args(argv)
    if not args.http and (not args.cert or not args.key):
        parser.error("--cert and --key are required unless --http is used")
    if args.http and not _is_loopback_host(args.host):
        parser.error("--http is allowed only with a loopback host such as 127.0.0.1")

    required_encoders = sorted(set(identity.ENCODER_FOR_KIND.values()))
    warmed = encoders.warm(required_encoders)
    cry_detector_ready = cry_gate.warm()
    server = build_http_server(
        (args.host, args.port),
        args.data_root,
        args.static_root,
        db_path=args.db,
        encoder_status=warmed,
        cry_detector_status=cry_detector_ready,
    )
    if not args.http:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)

    scheme = "http" if args.http else "https"
    print(
        f"Cry Memory ready at {scheme}://{args.host}:{args.port} "
        f"with encoders {warmed}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
