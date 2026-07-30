"""Measure incremental identity sessions through the real local HTTP API.

The manifest truth is used only after each HTTP response returns. Observation
requests contain raw audio bytes, the matching audio MIME, and neutral capture
metadata. They never contain a fixture name, expected person, expected label,
scenario, or evaluator mode.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config, http_api, store  # noqa: E402


MIME_BY_SUFFIX = {
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
}

SEQUENCES = {
    "one-person": [
        "prasshanna-01.wav",
        "prasshanna-02.wav",
        "prasshanna-03.wav",
        "blind-query-01.wav",
        "blind-query-02.wav",
    ],
    "staged": [
        "prasshanna-01.wav",
        "prasshanna-02.wav",
        "second-person-01.m4a",
        "second-person-02.m4a",
        "control-01.wav",
        "control-02.wav",
        "prasshanna-03.wav",
        "second-person-03.m4a",
        "blind-query-01.wav",
        "blind-query-02.wav",
    ],
    "difficult": [
        "prasshanna-01.wav",
        "second-person-01.m4a",
        "control-01.wav",
        "prasshanna-02.wav",
        "second-person-02.m4a",
        "control-02.wav",
        "prasshanna-03.wav",
        "second-person-03.m4a",
        "blind-query-01.wav",
        "blind-query-02.wav",
    ],
}

PENDING_REASON = "pending_new_participant_evidence"
PENDING_CONSUMED_REASON = "pending_outlier_pair_consistent"
NAMED_DIRECTION_STATUSES = {"participant", "leaning"}
INVALID_STATUSES = {"invalid", "session_completed"}
REQUEST_HEADERS = {
    "X-Capture-Source": "fixture-upload",
    "X-Capture-Device": "browser-audio-input",
    "User-Agent": "Mozilla/5.0",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_audio(path: Path) -> tuple[str, float]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "ffprobe failed"
        raise ValueError(f"unusable fixture {path.name}: {detail}")
    try:
        probed = json.loads(completed.stdout)
        format_data = probed["format"]
        container = str(format_data["format_name"])
        duration = float(format_data["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"missing audio metadata for {path.name}") from exc
    if not container or duration <= 0:
        raise ValueError(f"invalid audio metadata for {path.name}")
    return container, duration


def load_fixtures(manifest_path: str | Path) -> dict:
    """Validate and inventory every consented manifest fixture."""
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("kind") != "human_imitation":
        raise ValueError("manifest kind must be human_imitation")
    profiles = manifest.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("manifest profiles must be a non-empty list")

    fixture_root = manifest_path.parent.resolve()
    paths = {}
    truth_by_filename = {}
    display_by_source = {}
    inventory = []
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("each manifest profile must be an object")
        source_id = profile.get("id")
        display_name = profile.get("display_name")
        names = profile.get("files")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("each manifest profile requires an id")
        if source_id in display_by_source:
            raise ValueError(f"duplicate manifest profile id: {source_id}")
        if not isinstance(display_name, str) or not display_name:
            raise ValueError(f"profile {source_id} requires a display_name")
        if not isinstance(names, list) or not names:
            raise ValueError(f"profile {source_id} requires files")
        display_by_source[source_id] = display_name

        for name in names:
            if not isinstance(name, str) or not name:
                raise ValueError(f"profile {source_id} has an invalid filename")
            if name in paths:
                raise ValueError(f"duplicate manifest filename: {name}")
            path = (fixture_root / name).resolve()
            if fixture_root not in path.parents or not path.is_file():
                raise FileNotFoundError(path)
            mime = MIME_BY_SUFFIX.get(path.suffix.casefold())
            if mime is None:
                raise ValueError(f"unsupported fixture extension: {name}")
            size = path.stat().st_size
            if size <= 0:
                raise ValueError(f"empty fixture: {name}")
            container, duration = _probe_audio(path)
            digest = _sha256(path)
            paths[name] = path
            truth_by_filename[name] = source_id
            inventory.append(
                {
                    "filename": name,
                    "source_id": source_id,
                    "source_display_name": display_name,
                    "mime": mime,
                    "container": container,
                    "duration_seconds": duration,
                    "byte_size": size,
                    "sha256": digest,
                }
            )

    expected_names = set(SEQUENCES["staged"])
    actual_names = set(paths)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise ValueError(
            f"manifest fixture set differs from the fixed evaluation set: "
            f"missing={missing}, extra={extra}"
        )
    if len({item["sha256"] for item in inventory}) != len(inventory):
        raise ValueError("manifest fixtures must have distinct payload digests")

    directory_audio = {
        path.name
        for path in fixture_root.iterdir()
        if path.is_file() and path.suffix.casefold() in MIME_BY_SUFFIX
    }
    if directory_audio != actual_names:
        missing = sorted(actual_names - directory_audio)
        unlisted = sorted(directory_audio - actual_names)
        raise ValueError(
            f"audio directory differs from manifest: missing={missing}, "
            f"unlisted={unlisted}"
        )

    return {
        "manifest_path": manifest_path,
        "paths": paths,
        "truth_by_filename": truth_by_filename,
        "display_by_source": display_by_source,
        "inventory": inventory,
        "inventory_by_filename": {
            item["filename"]: item for item in inventory
        },
    }


class LocalProduct:
    """Fresh temporary database, managed-audio root, and HTTP server."""

    def __init__(self):
        baseline = store.get_baseline(config.POPULATION_KEY, config.DB_PATH)
        if baseline is None:
            raise RuntimeError(
                "population baseline is unavailable; run tools/build_baseline.py"
            )

        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = str(root / "episodes.db")
        store.init_db(self.db_path)
        store.save_baseline(
            config.POPULATION_KEY,
            baseline["mu"],
            baseline["sd"],
            baseline["n"],
            self.db_path,
        )
        self.server = http_api.build_http_server(
            ("127.0.0.1", 0),
            root / "managed-audio",
            ROOT / "web",
            db_path=self.db_path,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, method: str, path: str, body=b"", headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.server.server_address[1],
            timeout=30,
        )
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        status = response.status
        connection.close()
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"HTTP {status} returned non-JSON content for {path}"
            ) from exc
        return status, decoded

    def create_session(self) -> dict:
        body = json.dumps({"kind": "human_imitation"}).encode("utf-8")
        status, payload = self.request(
            "POST",
            "/api/live-sessions",
            body,
            {
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        if status != 201:
            raise RuntimeError(f"live session creation failed: {status} {payload}")
        return payload["session"]

    def session(self, session_id: int) -> dict:
        status, payload = self.request(
            "GET",
            f"/api/live-sessions/{session_id}",
        )
        if status != 200:
            raise RuntimeError(f"live session load failed: {status} {payload}")
        return payload["session"]

    def submit_audio(self, session_id: int, audio: bytes, mime: str):
        """Send no evaluator truth or fixture identity across the HTTP boundary."""
        headers = {
            "Content-Type": mime,
            "Content-Length": str(len(audio)),
            **REQUEST_HEADERS,
        }
        started_ns = time.perf_counter_ns()
        status, payload = self.request(
            "POST",
            f"/api/live-sessions/{session_id}/observations",
            audio,
            headers,
        )
        latency_ns = time.perf_counter_ns() - started_ns
        return status, payload, latency_ns


def _classification_row(
    *,
    sequence: int,
    fixture_name: str,
    expected_source: str | None,
    http_status: int,
    latency_ns: int,
    payload: dict,
    participant_count_before: int,
    label_truth: dict[str, str],
) -> dict:
    classification = payload.get("classification")
    if not isinstance(classification, dict):
        classification = {}
    status = classification.get("status")
    participant = classification.get("participant")
    if not isinstance(participant, dict):
        participant = {}
    label = participant.get("display_name")
    reason_codes = classification.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = []
    reason_codes = [reason for reason in reason_codes if isinstance(reason, str)]

    created_participant = False
    known_person_split = False
    if (
        expected_source is not None
        and isinstance(label, str)
        and label
        and status in {"provisional_created", "participant"}
        and label not in label_truth
    ):
        known_person_split = expected_source in label_truth.values()
        label_truth[label] = expected_source
        created_participant = True

    returned_truth = label_truth.get(label) if isinstance(label, str) else None
    direction_scored = status in NAMED_DIRECTION_STATUSES
    direction_correct = (
        returned_truth == expected_source if direction_scored else None
    )
    valid = status not in INVALID_STATUSES

    return {
        "sequence": sequence,
        "fixture": fixture_name,
        "expected_source": expected_source,
        "http_status": http_status,
        "latency_ns": latency_ns,
        "classification_status": status,
        "returned_participant": label,
        "returned_participant_truth": returned_truth,
        "participant_state": participant.get("state"),
        "support_count": participant.get("support_count"),
        "reinforced": classification.get("reinforced") is True,
        "reason_codes": reason_codes,
        "valid_observation": valid,
        "comparison_eligible": valid and participant_count_before > 0,
        "created_participant": created_participant,
        "known_person_split": known_person_split,
        "direction_scored": direction_scored,
        "direction_correct": direction_correct,
        "public_result": payload,
    }


def _summary(rows: list[dict], label_truth: dict, final_session: dict) -> dict:
    valid = [row for row in rows if row["valid_observation"]]
    comparison = [row for row in rows if row["comparison_eligible"]]
    established = [
        row for row in rows
        if row["classification_status"] == "participant"
    ]
    directional = [
        row for row in rows
        if row["classification_status"] == "leaning"
    ]
    named = established + directional
    correct_established = sum(
        row["direction_correct"] is True for row in established
    )
    correct_directional = sum(
        row["direction_correct"] is True for row in directional
    )
    wrong_person = sum(row["direction_correct"] is False for row in named)

    pending_patterns = 0
    for row in rows:
        reasons = set(row["reason_codes"])
        if PENDING_REASON in reasons:
            pending_patterns += 1
        if PENDING_CONSUMED_REASON in reasons:
            pending_patterns = max(0, pending_patterns - 1)

    source_counts = Counter(label_truth.values())
    participants = final_session.get("participants")
    if not isinstance(participants, list):
        participants = []
    direction_correct = correct_established + correct_directional
    expected_sources = {
        row["expected_source"]
        for row in rows
        if row["expected_source"] is not None
    }

    return {
        "total_submissions": len(rows),
        "valid_observations": len(valid),
        "comparison_eligible": len(comparison),
        "correct_established_assignments": correct_established,
        "established_assignment_denominator": len(established),
        "correct_directional_assignments": correct_directional,
        "directional_assignment_denominator": len(directional),
        "wrong_person": wrong_person,
        "wrong_person_denominator": len(named),
        "provisional_participants_created": sum(
            row["classification_status"] == "provisional_created"
            for row in rows
        ),
        "represented_people": len(source_counts),
        "represented_people_denominator": len(expected_sources),
        "participants_created": len(participants),
        "duplicate_profiles": sum(
            max(0, count - 1) for count in source_counts.values()
        ),
        "known_person_split": sum(
            row["known_person_split"] for row in rows
        ),
        "duplicate_uploads": sum(
            row["classification_status"] == "duplicate" for row in rows
        ),
        "invalid_recordings": sum(
            row["classification_status"] == "invalid" for row in rows
        ),
        "possible_new": sum(
            row["classification_status"] == "possible_new" for row in rows
        ),
        "pending_patterns": pending_patterns,
        "direction_shown": len(named),
        "direction_coverage_numerator": len(named),
        "direction_coverage_denominator": len(comparison),
        "direction_correct_numerator": direction_correct,
        "direction_correct_denominator": len(named),
        "reinforcements": sum(row["reinforced"] for row in rows),
        "max_observation_latency_ns": max(
            (row["latency_ns"] for row in rows),
            default=0,
        ),
    }


def _release_gate(summary: dict, represented_people: int) -> dict:
    checks = {
        "represented_people": (
            summary["represented_people"] == represented_people
        ),
        "participants_created": (
            summary["participants_created"] == represented_people
        ),
        "wrong_person": summary["wrong_person"] == 0,
        "duplicate_profiles": summary["duplicate_profiles"] == 0,
        "known_person_split": summary["known_person_split"] == 0,
    }
    return {
        "required": True,
        "expected_represented_people": represented_people,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _evaluate_sequence(fixtures: dict, mode: str) -> dict:
    product = LocalProduct()
    try:
        session = product.create_session()
        session_id = session["id"]
        label_truth = {}
        rows = []
        for index, fixture_name in enumerate(SEQUENCES[mode], start=1):
            participant_count_before = len(session.get("participants") or [])
            audio_path = fixtures["paths"][fixture_name]
            mime = fixtures["inventory_by_filename"][fixture_name]["mime"]

            # Truth is deliberately not read until the HTTP response has returned.
            http_status, payload, latency_ns = product.submit_audio(
                session_id,
                audio_path.read_bytes(),
                mime,
            )
            expected_source = fixtures["truth_by_filename"][fixture_name]
            if http_status not in {201, 422}:
                raise RuntimeError(
                    f"observation {index} returned HTTP {http_status}: {payload}"
                )
            row = _classification_row(
                sequence=index,
                fixture_name=fixture_name,
                expected_source=expected_source,
                http_status=http_status,
                latency_ns=latency_ns,
                payload=payload,
                participant_count_before=participant_count_before,
                label_truth=label_truth,
            )
            rows.append(row)
            session = payload.get("session") or session

        final_session = product.session(session_id)
        summary = _summary(rows, label_truth, final_session)
        represented = len(
            {
                fixtures["truth_by_filename"][name]
                for name in SEQUENCES[mode]
            }
        )
        gate = (
            _release_gate(summary, represented)
            if mode in {"staged", "difficult"}
            else {
                "required": False,
                "expected_represented_people": represented,
                "checks": {},
                "passed": None,
            }
        )
        return {
            "mode": mode,
            "sequence_description": (
                "Fixed synthetic arrival order, not capture chronology."
            ),
            "sequence": list(SEQUENCES[mode]),
            "fixture_inventory_count": len(fixtures["inventory"]),
            "request_contract": {
                "body": "raw audio bytes",
                "capture_source": REQUEST_HEADERS["X-Capture-Source"],
                "capture_device": REQUEST_HEADERS["X-Capture-Device"],
                "user_agent": REQUEST_HEADERS["User-Agent"],
                "truth_applied": "after each HTTP response",
            },
            "participant_truth_bindings": dict(label_truth),
            "observations": rows,
            "final_session": final_session,
            "summary": summary,
            "release_gate": gate,
        }
    finally:
        product.close()


def _evaluate_probes(fixtures: dict) -> dict:
    product = LocalProduct()
    try:
        session = product.create_session()
        session_id = session["id"]
        fixture_name = "prasshanna-01.wav"
        audio_path = fixtures["paths"][fixture_name]
        mime = fixtures["inventory_by_filename"][fixture_name]["mime"]
        label_truth = {}
        rows = []

        for index in (1, 2):
            participant_count_before = len(session.get("participants") or [])
            http_status, payload, latency_ns = product.submit_audio(
                session_id,
                audio_path.read_bytes(),
                mime,
            )
            expected_source = fixtures["truth_by_filename"][fixture_name]
            rows.append(
                _classification_row(
                    sequence=index,
                    fixture_name=fixture_name,
                    expected_source=expected_source,
                    http_status=http_status,
                    latency_ns=latency_ns,
                    payload=payload,
                    participant_count_before=participant_count_before,
                    label_truth=label_truth,
                )
            )
            session = payload.get("session") or session

        participant_before_invalid = list(session.get("participants") or [])
        participant_count_before = len(participant_before_invalid)
        http_status, payload, latency_ns = product.submit_audio(
            session_id,
            b"corrupt audio probe",
            "audio/wav",
        )
        rows.append(
            _classification_row(
                sequence=3,
                fixture_name="synthetic-corrupt-audio",
                expected_source=None,
                http_status=http_status,
                latency_ns=latency_ns,
                payload=payload,
                participant_count_before=participant_count_before,
                label_truth=label_truth,
            )
        )
        final_session = product.session(session_id)
        summary = _summary(rows, label_truth, final_session)

        first_support = rows[0]["support_count"]
        duplicate_support = rows[1]["support_count"]
        duplicate_timeline = len(
            rows[1]["public_result"].get("session", {}).get("observations", [])
        )
        checks = {
            "second_status_is_duplicate": (
                rows[1]["classification_status"] == "duplicate"
            ),
            "duplicate_does_not_change_support": (
                duplicate_support == first_support
            ),
            "duplicate_keeps_two_timeline_rows": duplicate_timeline == 2,
            "corrupt_audio_returns_422_invalid": (
                rows[2]["http_status"] == 422
                and rows[2]["classification_status"] == "invalid"
            ),
            "corrupt_audio_does_not_change_participants": (
                final_session.get("participants") == participant_before_invalid
            ),
            "corrupt_audio_does_not_add_timeline_row": (
                len(final_session.get("observations") or []) == 2
            ),
        }
        return {
            "mode": "probes",
            "sequence_description": (
                "Exact duplicate and corrupt-audio probes in one fresh session."
            ),
            "sequence": [
                fixture_name,
                fixture_name,
                "synthetic-corrupt-audio",
            ],
            "fixture_inventory_count": len(fixtures["inventory"]),
            "request_contract": {
                "body": "raw audio bytes",
                "capture_source": REQUEST_HEADERS["X-Capture-Source"],
                "capture_device": REQUEST_HEADERS["X-Capture-Device"],
                "user_agent": REQUEST_HEADERS["User-Agent"],
                "truth_applied": "after each HTTP response",
            },
            "participant_truth_bindings": dict(label_truth),
            "observations": rows,
            "final_session": final_session,
            "summary": summary,
            "release_gate": {
                "required": True,
                "checks": checks,
                "passed": all(checks.values()),
            },
        }
    finally:
        product.close()


def evaluate_mode(manifest_path: str | Path, mode: str) -> dict:
    """Evaluate one mode with a fresh temporary live HTTP service."""
    requested_mode = mode
    if mode == "alternating":
        mode = "difficult"
    if mode not in {*SEQUENCES, "probes"}:
        raise ValueError(f"unsupported evaluator mode: {requested_mode}")
    fixtures = load_fixtures(manifest_path)
    result = (
        _evaluate_probes(fixtures)
        if mode == "probes"
        else _evaluate_sequence(fixtures, mode)
    )
    if requested_mode != mode:
        result["requested_mode"] = requested_mode
    result["fixture_inventory"] = fixtures["inventory"]
    return result


def evaluate_all(manifest_path: str | Path) -> dict:
    """Run every mode independently and return one evidence bundle."""
    fixtures = load_fixtures(manifest_path)
    modes = {}
    for mode in ("one-person", "staged", "difficult"):
        modes[mode] = _evaluate_sequence(fixtures, mode)
    modes["probes"] = _evaluate_probes(fixtures)
    return {
        "schema_version": 1,
        "evidence_path": "real live-session HTTP API and ingest",
        "fixture_manifest": Path(manifest_path).name,
        "consent": {
            "public_distribution_confirmed_on": "2026-07-30",
            "recordings": len(fixtures["inventory"]),
            "participants": len(fixtures["display_by_source"]),
            "recording_type": "adult cry imitation",
        },
        "sequence_note": (
            "Evaluator orders are fixed synthetic arrivals, not capture chronology."
        ),
        "fixture_inventory": fixtures["inventory"],
        "modes": modes,
    }


def _required_gates_pass(report: dict) -> bool:
    if report.get("mode") in {"staged", "difficult", "probes"}:
        return report.get("release_gate", {}).get("passed") is True
    modes = report.get("modes")
    if isinstance(modes, dict):
        return all(
            modes[mode]["release_gate"]["passed"] is True
            for mode in ("staged", "difficult", "probes")
        )
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate incremental human identity through the real local HTTP API."
        )
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--mode",
        choices=(
            "one-person",
            "staged",
            "difficult",
            "alternating",
            "probes",
            "all",
        ),
        default="all",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = (
        evaluate_all(args.manifest)
        if args.mode == "all"
        else evaluate_mode(args.manifest, args.mode)
    )
    rendered = json.dumps(report, indent=2) + "\n"
    print(rendered, end="")
    passed = _required_gates_pass(report)
    if args.output is not None:
        if not passed:
            print(
                "required release gate failed; evidence file was not overwritten",
                file=sys.stderr,
            )
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
