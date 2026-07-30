"""Local product API for the iPhone client and laptop inference server."""

from __future__ import annotations

import argparse
import ipaddress
import json
import shutil
import sqlite3
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from . import (
        audio_ingest,
        careflow,
        config,
        encoders,
        identity,
        live_sessions,
        store,
    )
except ImportError:
    import audio_ingest
    import careflow
    import config
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


def _handler_factory(data_root: Path, static_root: Path, db_path: str | None):
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

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/health":
                store.init_db(db_path)
                available_encoders = set(encoders.available())
                baseline = store.get_baseline(config.POPULATION_KEY, db_path)
                ffmpeg = shutil.which("ffmpeg") is not None
                database = Path(db_path or config.DB_PATH).is_file()
                infant = identity.encoder_for(identity.KIND_INFANT) in available_encoders
                imitation = identity.encoder_for(identity.KIND_IMITATION) in available_encoders
                infant_requires_baseline = encoders.needs_baseline(
                    identity.encoder_for(identity.KIND_INFANT)
                )
                infant_ready = infant and (
                    not infant_requires_baseline or bool(baseline)
                )
                ready = ffmpeg and database and infant_ready
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
):
    """Build the local product server. TLS wrapping is performed by the launcher."""
    audio_root = Path(data_root).resolve()
    web_root = Path(static_root).resolve()
    audio_root.mkdir(parents=True, exist_ok=True)
    store.init_db(db_path)
    return ThreadingHTTPServer(
        address,
        _handler_factory(audio_root, web_root, db_path),
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

    server = build_http_server(
        (args.host, args.port),
        args.data_root,
        args.static_root,
        db_path=args.db,
    )
    if not args.http:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)

    required_encoders = sorted(set(identity.ENCODER_FOR_KIND.values()))
    warmed = encoders.warm(required_encoders)
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
