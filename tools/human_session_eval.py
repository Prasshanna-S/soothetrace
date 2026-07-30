"""Evaluate a session of enrolled human cry imitators through the product HTTP API.

Examples:

    python tools/human_session_eval.py demo_assets/human_audio/manifest.json --mode demo
    python tools/human_session_eval.py demo_assets/human_audio/manifest.json --mode loo

`demo` uses the manifest's fixed enrollment and held-out query lists.
`loo` holds every file out once and enrolls the remaining files for that person.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import threading
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


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or manifest.get("kind") != "human_imitation":
        raise ValueError("manifest kind must be human_imitation")
    profiles = manifest.get("profiles")
    if not isinstance(profiles, list) or len(profiles) < 2:
        raise ValueError("at least two profiles are required")
    seen = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("each profile must be an object")
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("each profile requires an id")
        if profile_id in seen:
            raise ValueError(f"duplicate profile id: {profile_id}")
        seen.add(profile_id)
        if not isinstance(profile.get("display_name"), str) or not profile["display_name"]:
            raise ValueError(f"profile {profile_id} requires a display_name")
        files = profile.get("files")
        if not isinstance(files, list) or not files or any(not isinstance(x, str) for x in files):
            raise ValueError(f"profile {profile_id} requires audio files")
    return profiles


def summarize(rows):
    total = len(rows)
    confirmed_correct = sum(
        row["result_type"] == "matched" and row["result_name"] == row["expected"]
        for row in rows
    )
    confirmed_wrong = sum(
        row["result_type"] == "matched" and row["result_name"] != row["expected"]
        for row in rows
    )
    leaning_correct = sum(
        row["result_type"] == "leaning" and row["result_name"] == row["expected"]
        for row in rows
    )
    leaning_wrong = sum(
        row["result_type"] == "leaning" and row["result_name"] != row["expected"]
        for row in rows
    )
    unresolved = sum(row["result_type"] == "unresolved" for row in rows)
    direction_correct = confirmed_correct + leaning_correct
    direction_shown = direction_correct + confirmed_wrong + leaning_wrong
    return {
        "queries": total,
        "confirmed_correct": confirmed_correct,
        "confirmed_wrong": confirmed_wrong,
        "leaning_correct": leaning_correct,
        "leaning_wrong": leaning_wrong,
        "unresolved": unresolved,
        "confirmed_coverage": (
            (confirmed_correct + confirmed_wrong) / total if total else 0.0
        ),
        "direction_coverage": direction_shown / total if total else 0.0,
        "direction_correct_rate": direction_correct / total if total else 0.0,
        "direction_precision": (
            direction_correct / direction_shown if direction_shown else None
        ),
    }


def session_label(position):
    value = max(1, int(position))
    suffix = ""
    while value > 0:
        value -= 1
        remainder = value - (value // 26) * 26
        suffix = chr(65 + remainder) + suffix
        value //= 26
    return f"Person {suffix}"


def summarize_discovery(rows):
    first = [row for row in rows if row.get("phase") == "first_encounter"]
    known = [row for row in rows if row.get("phase") == "known_turn"]
    new_people_correct = sum(
        row["result_type"] == "new" and row["result_name"] == row["expected"]
        for row in first
    )
    known_turns_confirmed_correct = sum(
        row["result_type"] == "matched"
        and row["result_name"] == row["expected"]
        for row in known
    )
    known_turns_leaning_correct = sum(
        row["result_type"] == "leaning"
        and row["result_name"] == row["expected"]
        for row in known
    )
    known_turns_correct = (
        known_turns_confirmed_correct + known_turns_leaning_correct
    )
    known_turns_wrong = sum(
        row["result_type"] in {"matched", "leaning"}
        and row["result_name"] != row["expected"]
        for row in known
    )
    return {
        "first_encounters": len(first),
        "new_people_correct": new_people_correct,
        "new_people_missed": len(first) - new_people_correct,
        "known_turns": len(known),
        "known_turns_correct": known_turns_correct,
        "known_turns_confirmed_correct": known_turns_confirmed_correct,
        "known_turns_leaning_correct": known_turns_leaning_correct,
        "known_turns_wrong": known_turns_wrong,
        "known_turns_split_as_new": sum(
            row["result_type"] == "new" for row in known
        ),
        "known_turns_pending_retry": sum(
            row["result_type"] == "pending_retry" for row in known
        ),
        "known_turns_unresolved": sum(
            row["result_type"] == "unresolved" for row in known
        ),
    }


class LocalProduct:
    def __init__(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = str(root / "episodes.db")
        source_baseline = store.get_baseline(config.POPULATION_KEY)
        if source_baseline:
            store.init_db(self.db_path)
            store.save_baseline(
                config.POPULATION_KEY,
                source_baseline["mu"],
                source_baseline["sd"],
                source_baseline["n"],
                self.db_path,
            )
        self.server = http_api.build_http_server(
            ("127.0.0.1", 0),
            root / "audio",
            ROOT / "web",
            db_path=self.db_path,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, method, path, body=b"", headers=None):
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
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = {"status": "error", "reason": "unreadable_response"}
        return status, decoded

    def json(self, method, path, payload):
        body = json.dumps(payload).encode("utf-8")
        return self.request(
            method,
            path,
            body,
            {"Content-Type": "application/json", "Content-Length": str(len(body))},
        )

    def audio(self, method, path, audio_path):
        body = audio_path.read_bytes()
        mime = MIME_BY_SUFFIX.get(audio_path.suffix.casefold())
        if not mime:
            raise ValueError(f"unsupported audio suffix: {audio_path.suffix}")
        return self.request(
            method,
            path,
            body,
            {
                "Content-Type": mime,
                "Content-Length": str(len(body)),
                "X-Capture-Device": "human-session-evaluator",
                "X-Capture-Mode": "file",
            },
        )


def resolve_files(manifest_path, profiles):
    root = manifest_path.parent
    resolved = {}
    for profile in profiles:
        rows = {}
        for name in profile["files"]:
            path = (root / name).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            rows[name] = path
        resolved[profile["id"]] = rows
    return resolved


def classify(public_identity, expected, query):
    if public_identity.get("status") == "match":
        result_type = "matched"
        profile = public_identity.get("profile") or {}
    elif isinstance(
        public_identity.get("leaning_profile") or public_identity.get("closest_profile"),
        dict,
    ):
        result_type = "leaning"
        profile = (
            public_identity.get("leaning_profile")
            or public_identity.get("closest_profile")
        )
    else:
        result_type = "unresolved"
        profile = {}
    return {
        "query": query,
        "expected": expected,
        "result_type": result_type,
        "result_name": profile.get("display_name"),
        "retry_allowed": bool(public_identity.get("retry_allowed")),
        "direction": public_identity.get("direction"),
        "reasons": public_identity.get("reasons") or [],
    }


def run_one_session(profiles, resolved, enrollment_map, query_rows):
    product = LocalProduct()
    try:
        server_ids = {}
        for profile in profiles:
            status, payload = product.json(
                "POST",
                "/api/profiles",
                {
                    "display_name": profile["display_name"],
                    "kind": "human_imitation",
                },
            )
            if status != 201:
                raise RuntimeError(payload)
            server_ids[profile["id"]] = payload["profile"]["id"]

        for profile in profiles:
            for name in enrollment_map[profile["id"]]:
                status, payload = product.audio(
                    "POST",
                    f"/api/profiles/{server_ids[profile['id']]}/enroll",
                    resolved[profile["id"]][name],
                )
                if status != 201:
                    raise RuntimeError(
                        f"enrollment failed for {profile['display_name']} {name}: {payload}"
                    )

        rows = []
        display_names = {profile["id"]: profile["display_name"] for profile in profiles}
        for profile_id, name in query_rows:
            status, payload = product.json(
                "POST",
                "/api/identity/attempts",
                {"kind": "human_imitation"},
            )
            if status != 201:
                raise RuntimeError(payload)
            attempt_id = payload["attempt"]["id"]
            status, payload = product.audio(
                "POST",
                f"/api/identity/attempts/{attempt_id}/captures",
                resolved[profile_id][name],
            )
            if status != 200:
                raise RuntimeError(payload)
            rows.append(
                classify(
                    payload["identity"],
                    expected=display_names[profile_id],
                    query=name,
                )
            )
        return rows
    finally:
        product.close()


def run_demo(profiles, resolved):
    enrollment_map = {}
    query_rows = []
    for profile in profiles:
        enrollment = profile.get("demo_enrollment")
        queries = profile.get("demo_queries")
        if not isinstance(enrollment, list):
            enrollment = profile["files"]
        if not isinstance(queries, list):
            queries = []
        enrollment_map[profile["id"]] = enrollment
        query_rows.extend((profile["id"], name) for name in queries)
    return run_one_session(profiles, resolved, enrollment_map, query_rows)


def run_leave_one_out(profiles, resolved):
    rows = []
    for truth in profiles:
        for held_name in truth["files"]:
            enrollment_map = {}
            for profile in profiles:
                enrollment_map[profile["id"]] = [
                    name
                    for name in profile["files"]
                    if profile["id"] != truth["id"] or name != held_name
                ]
            rows.extend(
                run_one_session(
                    profiles,
                    resolved,
                    enrollment_map,
                    [(truth["id"], held_name)],
                )
            )
    return rows


def _create_and_enroll(product, display_name, audio_path, supporting_path=None):
    status, payload = product.json(
        "POST",
        "/api/profiles",
        {"display_name": display_name, "kind": "human_imitation"},
    )
    if status != 201:
        raise RuntimeError(payload)
    profile_id = payload["profile"]["id"]
    status, payload = product.audio(
        "POST",
        f"/api/profiles/{profile_id}/enroll",
        audio_path,
    )
    if status != 201:
        raise RuntimeError(f"enrollment failed for {display_name}: {payload}")
    if supporting_path is not None:
        status, payload = product.audio(
            "POST",
            f"/api/profiles/{profile_id}/enroll",
            supporting_path,
        )
        if status != 201:
            raise RuntimeError(
                f"second enrollment failed for {display_name}: {payload}"
            )
    return profile_id


def _start_query(product, audio_path):
    status, payload = product.json(
        "POST",
        "/api/identity/attempts",
        {"kind": "human_imitation"},
    )
    if status != 201:
        raise RuntimeError(payload)
    attempt_id = payload["attempt"]["id"]
    status, payload = product.audio(
        "POST",
        f"/api/identity/attempts/{attempt_id}/captures",
        audio_path,
    )
    if status != 200:
        raise RuntimeError(payload)
    return attempt_id, payload["identity"]


def _query_identity(product, audio_path):
    return _start_query(product, audio_path)[1]


def _retry_identity(product, attempt_id, audio_path):
    status, payload = product.audio(
        "POST",
        f"/api/identity/attempts/{attempt_id}/retry",
        audio_path,
    )
    if status != 200:
        raise RuntimeError(payload)
    return payload["identity"]


def run_discovery(profiles, resolved):
    """Replay the automatic session policy in arrival order.

    The first file for each truth source is treated as that person's first encounter. Every
    remaining file is a later known-person turn. A confirmed later turn is enrolled back into the
    matched profile, matching the browser's conservative online reinforcement rule.
    """
    product = LocalProduct()
    try:
        rows = []
        profile_ids_by_name = {}
        expected_names = {
            profile["id"]: session_label(index)
            for index, profile in enumerate(profiles, start=1)
        }

        consumed = {profile["id"]: 1 for profile in profiles}
        for index, profile in enumerate(profiles, start=1):
            name = profile["files"][0]
            path = resolved[profile["id"]][name]
            expected = expected_names[profile["id"]]
            if index == 1:
                profile_ids_by_name[expected] = _create_and_enroll(
                    product, expected, path
                )
                row = {
                    "query": name,
                    "expected": expected,
                    "result_type": "new",
                    "result_name": expected,
                    "retry_allowed": False,
                    "direction": None,
                    "reasons": ["first_valid_session_cry"],
                }
            else:
                attempt_id, identity_payload = _start_query(product, path)
                supporting_path = None
                if (
                    identity_payload.get("novelty") == "candidate_new_profile"
                    and identity_payload.get("retry_allowed")
                    and len(profile["files"]) > 1
                ):
                    retry_name = profile["files"][1]
                    supporting_path = resolved[profile["id"]][retry_name]
                    identity_payload = _retry_identity(
                        product, attempt_id, supporting_path
                    )
                    consumed[profile["id"]] = 2
                if identity_payload.get("novelty") == "confirmed_new_profile":
                    actual = session_label(len(profile_ids_by_name) + 1)
                    profile_ids_by_name[actual] = _create_and_enroll(
                        product, actual, path, supporting_path
                    )
                    row = {
                        "query": name,
                        "expected": expected,
                        "result_type": "new",
                        "result_name": actual,
                        "retry_allowed": False,
                        "direction": None,
                        "reasons": identity_payload.get("reasons") or [],
                    }
                else:
                    row = classify(identity_payload, expected, name)
                    if (
                        row["result_type"] == "matched"
                        and row["result_name"] in profile_ids_by_name
                    ):
                        product.audio(
                            "POST",
                            f"/api/profiles/{profile_ids_by_name[row['result_name']]}/enroll",
                            supporting_path or path,
                        )
            row["phase"] = "first_encounter"
            rows.append(row)

        for profile in profiles:
            expected = expected_names[profile["id"]]
            names = profile["files"][consumed[profile["id"]]:]
            position = 0
            while position < len(names):
                name = names[position]
                path = resolved[profile["id"]][name]
                attempt_id, identity_payload = _start_query(product, path)
                supporting_path = None
                if (
                    identity_payload.get("novelty") == "candidate_new_profile"
                    and identity_payload.get("retry_allowed")
                    and position + 1 < len(names)
                ):
                    retry_name = names[position + 1]
                    supporting_path = resolved[profile["id"]][retry_name]
                    identity_payload = _retry_identity(
                        product, attempt_id, supporting_path
                    )
                    position += 1
                if identity_payload.get("novelty") == "confirmed_new_profile":
                    actual = session_label(len(profile_ids_by_name) + 1)
                    profile_ids_by_name[actual] = _create_and_enroll(
                        product, actual, path, supporting_path
                    )
                    row = {
                        "query": name,
                        "expected": expected,
                        "result_type": "new",
                        "result_name": actual,
                        "retry_allowed": False,
                        "direction": None,
                        "reasons": identity_payload.get("reasons") or [],
                    }
                elif identity_payload.get("novelty") == "candidate_new_profile":
                    if supporting_path is None and identity_payload.get("retry_allowed"):
                        row = {
                            "query": name,
                            "expected": expected,
                            "result_type": "pending_retry",
                            "result_name": None,
                            "retry_allowed": True,
                            "direction": None,
                            "reasons": identity_payload.get("reasons") or [],
                        }
                    else:
                        row = classify(identity_payload, expected, name)
                else:
                    row = classify(identity_payload, expected, name)
                    if (
                        row["result_type"] == "matched"
                        and row["result_name"] in profile_ids_by_name
                    ):
                        product.audio(
                            "POST",
                            f"/api/profiles/{profile_ids_by_name[row['result_name']]}/enroll",
                            supporting_path or path,
                        )
                row["phase"] = "known_turn"
                rows.append(row)
                position += 1
        return rows
    finally:
        product.close()


def print_report(rows, summary):
    print(
        "phase".ljust(18),
        "query".ljust(28),
        "expected".ljust(18),
        "result".ljust(12),
        "profile",
    )
    print("-" * 96)
    for row in rows:
        print(
            row.get("phase", "").ljust(18),
            row["query"].ljust(28),
            row["expected"].ljust(18),
            row["result_type"].ljust(12),
            row["result_name"] or "",
        )
    print()
    print(json.dumps(summary, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Evaluate any number of enrolled human cry-imitator profiles."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--mode", choices=("demo", "loo", "discovery"), default="demo")
    parser.add_argument("--json", action="store_true", dest="json_only")
    args = parser.parse_args(argv)

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    profiles = validate_manifest(manifest)
    resolved = resolve_files(manifest_path, profiles)
    if args.mode == "demo":
        rows = run_demo(profiles, resolved)
        summary = summarize(rows)
    elif args.mode == "loo":
        rows = run_leave_one_out(profiles, resolved)
        summary = summarize(rows)
    else:
        rows = run_discovery(profiles, resolved)
        summary = summarize_discovery(rows)
    report = {"mode": args.mode, "rows": rows, "summary": summary}
    if args.json_only:
        print(json.dumps(report, indent=2))
    else:
        print_report(rows, report["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
