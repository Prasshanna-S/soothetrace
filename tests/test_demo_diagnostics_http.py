"""HTTP contract tests for the projector-safe care demo monitor."""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from tests.test_product_http_api import ProductServer


class DemoDiagnosticsHttpTests(unittest.TestCase):
    def setUp(self):
        self.product = ProductServer(cry_detector_status=True)
        self.addCleanup(self.product.close)
        project_web = Path(__file__).resolve().parents[1] / "web"
        for name in ("backend.html", "backend.css", "backend.js"):
            source = project_web / name
            if source.is_file():
                (self.product.static_root / name).write_bytes(source.read_bytes())

    def _create_care_session(self):
        profile = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Demo Baby", "kind": "infant"},
        )["json"]["profile"]
        response = self.product.json(
            "POST",
            "/api/care-sessions",
            {
                "profile_id": profile["id"],
                "tags": ["before-feed", "nursery"],
            },
        )
        self.assertEqual(201, response["status"], response["body"])
        return profile, response["json"]["session"]

    def test_idle_snapshot_has_no_invented_session_or_decision(self):
        response = self.product.request("GET", "/api/demo-diagnostics")

        self.assertEqual(200, response["status"], response["body"])
        self.assertEqual("no-store", response["headers"]["cache-control"])
        self.assertEqual(
            {
                "status": "idle",
                "server_time": response["json"]["server_time"],
                "segment_target_seconds": 6,
                "session": None,
            },
            response["json"],
        )

    def test_snapshot_reports_the_latest_persisted_pipeline_and_exact_decision(self):
        profile, session = self._create_care_session()
        persisted_decision = {
            "id": 31,
            "latched_at": "2026-07-30T22:14:06-04:00",
            "profile": {
                "id": profile["id"],
                "display_name": "Demo Baby",
            },
            "guidance": {
                "status": "grounded",
                "headline": "What helped before",
                "interpretation": "This resembles a previous late-evening pattern.",
                "recommendation": "Try holding the baby upright.",
                "evidence_summary": "Helped in 2 similar recorded incidents.",
                "support_count": 2,
                "incident_ids": [7],
                "pattern": "Late evening, before a feed",
            },
            "basis": [
                "A similar cry pattern was recorded late in the evening.",
                "The earlier incident was tagged before-feed.",
            ],
            "scenarios": [
                {
                    "episode_id": 7,
                    "started_at": "2026-07-28T22:02:00-04:00",
                    "interventions": [
                        {
                            "order": 1,
                            "action": "Held upright",
                            "evidence": "Caregiver follow-up",
                        }
                    ],
                    "outcome": "Settled after a few minutes",
                    "outcome_src": "caregiver",
                    "worked": True,
                    "contributions": [
                        "time-of-day match",
                        "before-feed context",
                        "cry-pattern similarity",
                    ],
                }
            ],
        }
        connection = sqlite3.connect(self.product.db_path)
        try:
            connection.execute(
                "INSERT INTO care_session_chunk ("
                "session_id, sequence, created_at, source_audio_path, "
                "canonical_audio_path, identity_audio_path, audio_sha256, "
                "capture_metadata_json, quality_json, status, cry_status, "
                "cry_reason_codes, cry_model_version, matched_profile_id, "
                "reason_codes, result_json"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session["id"],
                    1,
                    "2026-07-30T22:14:06-04:00",
                    "/private/secret/source.m4a",
                    "/private/secret/canonical.wav",
                    "/private/secret/identity.wav",
                    "private-digest",
                    json.dumps(
                        {
                            "capture_device_name": "iPhone Safari",
                            "user_agent": "private browser fingerprint",
                        }
                    ),
                    json.dumps(
                        {
                            "duration_s": 6.18,
                            "mean_db": -24.5,
                            "peak_db": -4.2,
                            "voiced_fraction": 0.58,
                            "gain_db": 0.5,
                        }
                    ),
                    "guidance_latched",
                    "infant_cry_detected",
                    json.dumps(["infant_cry_evidence_strong"]),
                    "ast-audioset-baby-cry-v1",
                    profile["id"],
                    json.dumps(["grounded"]),
                    "{}",
                ),
            )
            chunk_id = connection.execute(
                "SELECT id FROM care_session_chunk WHERE session_id=?",
                (session["id"],),
            ).fetchone()[0]
            connection.execute(
                "UPDATE care_session SET last_sequence=?, "
                "latest_matched_chunk_id=?, selected_chunk_id=?, "
                "decision_json=? WHERE id=?",
                (
                    1,
                    chunk_id,
                    chunk_id,
                    json.dumps(persisted_decision),
                    session["id"],
                ),
            )
            connection.commit()
        finally:
            connection.close()

        response = self.product.request("GET", "/api/demo-diagnostics")

        self.assertEqual(200, response["status"], response["body"])
        payload = response["json"]
        self.assertEqual("active", payload["status"])
        self.assertEqual(6, payload["segment_target_seconds"])
        snapshot = payload["session"]
        self.assertEqual(session["id"], snapshot["id"])
        self.assertEqual("Demo Baby", snapshot["profile"]["display_name"])
        self.assertEqual(["before-feed", "nursery"], snapshot["context"]["tags"])
        self.assertEqual("night", snapshot["context"]["time_of_day"])
        self.assertEqual("10:14 PM", snapshot["context"]["local_time"])
        self.assertEqual(1, snapshot["latest_segment"]["sequence"])
        self.assertEqual(6.18, snapshot["latest_segment"]["duration_seconds"])
        self.assertEqual("decoded", snapshot["latest_segment"]["ingest"]["state"])
        self.assertEqual("usable", snapshot["latest_segment"]["ingest"]["quality"])
        self.assertEqual(
            "pass",
            snapshot["latest_segment"]["cry_gate"]["state"],
        )
        self.assertEqual(
            "selected_profile",
            snapshot["latest_segment"]["identity"]["state"],
        )
        self.assertEqual(
            "Try holding the baby upright.",
            snapshot["decision"]["guidance"]["recommendation"],
        )
        self.assertEqual(
            persisted_decision["basis"],
            snapshot["decision"]["basis"],
        )
        self.assertEqual(7, snapshot["evidence"][0]["incident_id"])
        self.assertEqual(
            [
                "time-of-day match",
                "before-feed context",
                "cry-pattern similarity",
            ],
            snapshot["evidence"][0]["contributions"],
        )
        self.assertEqual(
            ["ingest", "cry_gate", "identity", "memory", "guidance"],
            [step["key"] for step in snapshot["pipeline"]],
        )
        self.assertEqual("complete", snapshot["pipeline"][-1]["state"])
        self.assertEqual(1, snapshot["events"][0]["sequence"])
        self.assertEqual(
            "Guidance latched from recorded history",
            snapshot["events"][0]["message"],
        )

        encoded = json.dumps(payload).casefold()
        for forbidden in (
            "/private/secret",
            "private-digest",
            "browser fingerprint",
            "audio_sha256",
            "canonical_audio_path",
            "identity_audio_path",
            "source_audio_path",
            "embedding",
            "\"score\"",
            "\"margin\"",
        ):
            self.assertNotIn(forbidden.casefold(), encoded)

    def test_static_monitor_assets_are_served_with_the_same_origin_policy(self):
        expected_types = {
            "/backend.html": "text/html",
            "/backend.css": "text/css",
            "/backend.js": "text/javascript",
        }
        for path, content_type in expected_types.items():
            with self.subTest(path=path):
                response = self.product.request("GET", path)
                self.assertEqual(200, response["status"], response["body"])
                self.assertTrue(
                    response["headers"]["content-type"].startswith(content_type)
                )
                self.assertEqual("no-store", response["headers"]["cache-control"])
                self.assertIn(
                    "connect-src 'self'",
                    response["headers"]["content-security-policy"],
                )


if __name__ == "__main__":
    unittest.main()
