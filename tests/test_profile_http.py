import unittest

from src import identity, store
from tests.test_product_http_api import ProductServer


class ProfileHttpTests(unittest.TestCase):
    def setUp(self):
        self.product = ProductServer(cry_detector_status=True)
        self.addCleanup(self.product.close)
        created = self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": "Demo Baby", "kind": "infant"},
        )
        self.profile = created["json"]["profile"]
        self.incident_id = store.save_episode(
            {
                "subject_id": f"profile-{self.profile['id']}",
                "started_at": "2026-07-30T14:05:00+00:00",
                "duration_s": 12.0,
                "fingerprint": [0.5] * 87,
                "transcript": "I held her upright.",
                "interventions": [{"action": "held baby upright"}],
                "outcome": "She settled.",
                "outcome_src": "caregiver",
                "worked": True,
                "context": {"hour_local": 14, "tags": ["afternoon"]},
            },
            self.product.db_path,
        )

    def test_profile_history_and_detail_routes_match_browser_contract(self):
        summary = self.product.request(
            "GET",
            f"/api/profiles/{self.profile['id']}",
        )
        history = self.product.request(
            "GET",
            f"/api/profiles/{self.profile['id']}/incidents?limit=10",
        )
        detail = self.product.request(
            "GET",
            f"/api/profiles/{self.profile['id']}/incidents/{self.incident_id}",
        )

        self.assertEqual(200, summary["status"], summary["body"])
        self.assertEqual(1, summary["json"]["profile"]["memory_count"])
        self.assertEqual(200, history["status"], history["body"])
        incident = history["json"]["incidents"][0]
        self.assertEqual("held baby upright", incident["actions"][0]["action"])
        self.assertEqual(["afternoon"], incident["context"]["tags"])
        self.assertEqual(200, detail["status"], detail["body"])
        self.assertEqual(
            "I held her upright.",
            detail["json"]["incident"]["speech"]["segments"][0]["text"],
        )
        rendered = repr((summary["json"], history["json"], detail["json"]))
        self.assertNotIn("audio_path", rendered)
        self.assertNotIn("fingerprint", rendered)

    def test_local_visitor_session_is_immediately_consented(self):
        session = self.product.request("GET", "/api/visitor-session")
        consent = self.product.json(
            "POST",
            "/api/visitor-session/consent",
            {},
        )
        self.assertEqual(200, session["status"])
        self.assertTrue(session["json"]["visitor_session"]["consented"])
        self.assertEqual(200, consent["status"])
        self.assertTrue(consent["json"]["visitor_session"]["consented"])

    def test_human_baby_alias_creates_and_finishes_imitation_session(self):
        created = self.product.json(
            "POST",
            "/api/live-sessions",
            {"kind": "human_baby"},
        )
        self.assertEqual(201, created["status"], created["body"])
        self.assertEqual(
            identity.KIND_IMITATION,
            created["json"]["session"]["kind"],
        )
        session_id = created["json"]["session"]["id"]
        finished = self.product.json(
            "POST",
            f"/api/live-sessions/{session_id}/finish",
            {},
        )
        self.assertEqual(200, finished["status"], finished["body"])
        self.assertEqual("completed", finished["json"]["session"]["status"])


if __name__ == "__main__":
    unittest.main()
