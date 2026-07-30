import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.test_product_http_api import ProductServer


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "data" / "audio" / "round2_h"
IMITATION_ROOT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "audio"
    / "imitation_trial_sources"
)
HUMAN_DEMO_ROOT = Path(__file__).resolve().parents[1] / "demo_assets" / "human_audio"


class RealAudioProductApiTests(unittest.TestCase):
    def setUp(self):
        from src import config, store

        baseline = store.get_baseline(config.POPULATION_KEY)
        self.assertIsNotNone(baseline, "population baseline must be built")
        self.product = ProductServer(cry_detector_status=True)
        self.addCleanup(self.product.close)
        store.save_baseline(
            config.POPULATION_KEY,
            baseline["mu"],
            baseline["sd"],
            baseline["n"],
            self.product.db_path,
        )

    def _create_profile(self, name, kind="infant"):
        return self.product.json(
            "POST",
            "/api/profiles",
            {"display_name": name, "kind": kind},
        )["json"]["profile"]

    def _upload_path(self, method, path, fixture_path):
        audio = fixture_path.read_bytes()
        content_type = {
            ".m4a": "audio/mp4",
            ".mp4": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg",
            ".opus": "audio/ogg",
        }.get(fixture_path.suffix.casefold(), "audio/wav")
        return self.product.request(
            method,
            path,
            audio,
            {"Content-Type": content_type, "Content-Length": str(len(audio))},
        )

    def _upload(self, method, path, fixture):
        return self._upload_path(method, path, FIXTURE_ROOT / fixture)

    @unittest.skipUnless(FIXTURE_ROOT.is_dir(), "live fixed-rig fixtures are unavailable")
    def test_real_phone_audio_reaches_the_ordered_care_chunk_route(self):
        from src import care_sessions

        profile = self._create_profile("Baby X")
        session = self.product.json(
            "POST",
            "/api/care-sessions",
            {"profile_id": profile["id"]},
        )["json"]["session"]
        fixture = FIXTURE_ROOT / "13-X7.wav"
        audio = fixture.read_bytes()
        with patch.object(
            care_sessions.cry_gate,
            "classify",
            return_value={
                "status": "no_cry_detected",
                "label": None,
                "reason_codes": ["no_infant_cry_evidence"],
                "analyzed_duration_s": 8.0,
                "analysis_view_count": 1,
                "model_version": "ast-audioset-baby-cry-v1",
            },
        ):
            response = self.product.request(
                "POST",
                f"/api/care-sessions/{session['id']}/chunks",
                audio,
                {
                    "Content-Type": "audio/wav",
                    "Content-Length": str(len(audio)),
                    "X-Capture-Sequence": "1",
                    "X-Capture-Source": "microphone",
                    "X-Capture-Device": "iPhone Safari",
                },
            )

        self.assertEqual(201, response["status"], response)
        self.assertEqual(1, response["json"]["session"]["last_sequence"])
        self.assertEqual("no_cry_detected", response["json"]["chunk"]["status"])

    @unittest.skipUnless(FIXTURE_ROOT.is_dir(), "live fixed-rig fixtures are unavailable")
    def test_real_fixed_rig_audio_survives_product_ingest_and_identifies_both_profiles(self):
        baby_x = self._create_profile("Baby X")
        baby_y = self._create_profile("Baby Y")
        for profile, fixtures in (
            (baby_x, ["01-X1.wav", "03-X2.wav", "05-X3.wav"]),
            (baby_y, ["02-Y1.wav", "04-Y2.wav", "06-Y3.wav"]),
        ):
            for fixture in fixtures:
                enrolled = self._upload(
                    "POST",
                    f"/api/profiles/{profile['id']}/enroll",
                    fixture,
                )
                self.assertEqual(201, enrolled["status"], enrolled["body"])

        retried = []
        for expected, fixture, retry_fixture in (
            ("Baby X", "13-X7.wav", "15-X8.wav"),
            ("Baby X", "15-X8.wav", "13-X7.wav"),
            ("Baby Y", "14-Y7.wav", "16-Y8.wav"),
            ("Baby Y", "16-Y8.wav", "14-Y7.wav"),
        ):
            attempt = self.product.json(
                "POST",
                "/api/identity/attempts",
                {"kind": "infant"},
            )["json"]["attempt"]
            response = self._upload(
                "POST",
                f"/api/identity/attempts/{attempt['id']}/captures",
                fixture,
            )
            self.assertEqual(200, response["status"], response["body"])
            result = json.loads(response["body"].decode("utf-8"))["identity"]
            if result["status"] == "uncertain":
                self.assertIs(result["retry_allowed"], True, result)
                retried.append(fixture)
                response = self._upload(
                    "POST",
                    f"/api/identity/attempts/{attempt['id']}/retry",
                    retry_fixture,
                )
                self.assertEqual(200, response["status"], response["body"])
                result = json.loads(response["body"].decode("utf-8"))["identity"]
            self.assertEqual("match", result["status"], result)
            self.assertEqual(expected, result["profile"]["display_name"])
        self.assertEqual(["16-Y8.wav"], retried)

    @unittest.skipUnless(FIXTURE_ROOT.is_dir(), "live fixed-rig fixtures are unavailable")
    def test_real_cry_identity_returns_profile_history_guidance_and_playable_evidence(self):
        from src import audio_ingest, careflow, fingerprint, store

        baby_x = self._create_profile("Baby X")
        baby_y = self._create_profile("Baby Y")
        for profile, fixtures in (
            (baby_x, ["01-X1.wav", "03-X2.wav", "05-X3.wav"]),
            (baby_y, ["02-Y1.wav", "04-Y2.wav", "06-Y3.wav"]),
        ):
            for fixture in fixtures:
                response = self._upload(
                    "POST",
                    f"/api/profiles/{profile['id']}/enroll",
                    fixture,
                )
                self.assertEqual(201, response["status"], response["body"])

        subject_id = f"profile-{baby_x['id']}"
        first_at = datetime.now(timezone.utc) - timedelta(days=6)
        prior_ids = []
        prior_fixtures = [
            "01-X1.wav",
            "03-X2.wav",
            "05-X3.wav",
            "07-X4.wav",
            "09-X5.wav",
            "11-X6.wav",
        ]
        for index, fixture in enumerate(prior_fixtures):
            ingested = audio_ingest.ingest_audio(
                (FIXTURE_ROOT / fixture).read_bytes(),
                "audio/wav",
                storage_root=self.product.data_root,
            )
            self.assertEqual("ready", ingested["status"], ingested)
            prior_ids.append(
                store.save_episode(
                    {
                        "subject_id": subject_id,
                        "started_at": (first_at + timedelta(days=index)).isoformat(),
                        "duration_s": fingerprint.duration_s(ingested["canonical_path"]),
                        "audio_path": ingested["canonical_path"],
                        "fingerprint": fingerprint.compute_windowed(
                            ingested["canonical_path"]
                        ),
                        "transcript": "I walked with the baby.",
                        "interventions": [
                            {
                                "order": 1,
                                "action": "walked",
                                "evidence": "walked",
                            }
                        ],
                        "outcome": "Walking settled the baby.",
                        "outcome_src": "seed",
                        "worked": True,
                        "context": {
                            "hour_local": 19,
                            "minutes_since_prev_episode": 1440.0,
                            "subject_age_days": None,
                            "tags": ["overtired"],
                        },
                    },
                    self.product.db_path,
                )
            )

        attempt = self.product.json(
            "POST",
            "/api/identity/attempts",
            {"kind": "infant"},
        )["json"]["attempt"]
        identified = self._upload(
            "POST",
            f"/api/identity/attempts/{attempt['id']}/captures",
            "13-X7.wav",
        )
        self.assertEqual(200, identified["status"], identified["body"])
        identity_result = json.loads(identified["body"].decode("utf-8"))["identity"]
        self.assertEqual("match", identity_result["status"], identity_result)
        self.assertEqual("Baby X", identity_result["profile"]["display_name"])

        with (
            patch.object(careflow.session.speech, "transcribe", return_value=""),
            patch.object(
                careflow.session.speech,
                "extract_interventions",
                return_value=[],
            ),
        ):
            completed = self.product.json(
                "POST",
                f"/api/incidents/{attempt['id']}/complete",
                {
                    "caregiver_answer": "Walking worked and the baby settled.",
                    "tags": ["overtired"],
                },
            )

        self.assertEqual(200, completed["status"], completed)
        result = completed["json"]
        self.assertEqual("complete", result["status"])
        self.assertEqual("Baby X", result["identity"]["display_name"])
        self.assertEqual("grounded", result["guidance"]["status"])
        self.assertEqual("walked", result["guidance"]["action"])
        self.assertEqual(
            "This resembles earlier incidents for this profile.",
            result["guidance"]["interpretation"],
        )
        self.assertEqual(
            "What helped before: walked.",
            result["guidance"]["recommendation"],
        )
        self.assertGreaterEqual(result["guidance"]["support_count"], 1)
        self.assertTrue(
            set(result["guidance"]["incident_ids"]).issubset(set(prior_ids))
        )
        self.assertTrue(result["scenarios"])
        evidence_url = result["scenarios"][0]["audio_url"]
        playback = self.product.request("GET", evidence_url)
        self.assertEqual(200, playback["status"])
        self.assertGreater(len(playback["body"]), 1000)

    @unittest.skipUnless(IMITATION_ROOT.is_dir(), "imitation fixtures are unavailable")
    def test_real_imitation_queries_identify_the_enrolled_person_through_product_api(self):
        prasshanna = self._create_profile("Prasshanna", "human_imitation")
        decoy = self._create_profile("Control", "human_imitation")
        for profile, fixtures in (
            (
                prasshanna,
                [
                    "prasshanna-01.wav",
                    "prasshanna-02.wav",
                    "prasshanna-03.wav",
                ],
            ),
            (decoy, ["control-01.wav", "control-02.wav"]),
        ):
            for fixture in fixtures:
                enrolled = self._upload_path(
                    "POST",
                    f"/api/profiles/{profile['id']}/enroll",
                    IMITATION_ROOT / fixture,
                )
                self.assertEqual(201, enrolled["status"], enrolled["body"])

        retried = []
        for fixture, retry_fixture in (
            ("blind-query-01.wav", "blind-query-02.wav"),
            ("blind-query-02.wav", "blind-query-01.wav"),
        ):
            attempt = self.product.json(
                "POST",
                "/api/identity/attempts",
                {"kind": "human_imitation"},
            )["json"]["attempt"]
            response = self._upload_path(
                "POST",
                f"/api/identity/attempts/{attempt['id']}/captures",
                IMITATION_ROOT / fixture,
            )
            self.assertEqual(200, response["status"], response["body"])
            result = json.loads(response["body"].decode("utf-8"))["identity"]
            if result["status"] == "uncertain":
                self.assertIs(result["retry_allowed"], True, result)
                retried.append(fixture)
                response = self._upload_path(
                    "POST",
                    f"/api/identity/attempts/{attempt['id']}/retry",
                    IMITATION_ROOT / retry_fixture,
                )
                self.assertEqual(200, response["status"], response["body"])
                result = json.loads(response["body"].decode("utf-8"))["identity"]
            self.assertEqual("match", result["status"], result)
            self.assertEqual("Prasshanna", result["profile"]["display_name"])
        self.assertEqual(["blind-query-02.wav"], retried)

    @unittest.skipUnless(HUMAN_DEMO_ROOT.is_dir(), "human demo fixtures are unavailable")
    def test_new_person_confirmation_accepts_same_source_and_rejects_mixed_sources(self):
        person_a = self._create_profile("Person A", "human_imitation")
        enrolled = self._upload_path(
            "POST",
            f"/api/profiles/{person_a['id']}/enroll",
            HUMAN_DEMO_ROOT / "prasshanna-01.wav",
        )
        self.assertEqual(201, enrolled["status"], enrolled["body"])

        same_attempt = self.product.json(
            "POST",
            "/api/identity/attempts",
            {"kind": "human_imitation"},
        )["json"]["attempt"]
        first = self._upload_path(
            "POST",
            f"/api/identity/attempts/{same_attempt['id']}/captures",
            HUMAN_DEMO_ROOT / "second-person-01.m4a",
        )
        first_identity = json.loads(first["body"].decode("utf-8"))["identity"]
        self.assertEqual("candidate_new_profile", first_identity.get("novelty"))
        self.assertEqual(
            "Person A",
            first_identity["closest_profile"]["display_name"],
        )
        confirmed = self._upload_path(
            "POST",
            f"/api/identity/attempts/{same_attempt['id']}/retry",
            HUMAN_DEMO_ROOT / "second-person-02.m4a",
        )
        confirmed_identity = json.loads(confirmed["body"].decode("utf-8"))["identity"]
        self.assertEqual("confirmed_new_profile", confirmed_identity.get("novelty"))
        self.assertIn("novelty_pair_consistent", confirmed_identity["reasons"])

        mixed_attempt = self.product.json(
            "POST",
            "/api/identity/attempts",
            {"kind": "human_imitation"},
        )["json"]["attempt"]
        first = self._upload_path(
            "POST",
            f"/api/identity/attempts/{mixed_attempt['id']}/captures",
            HUMAN_DEMO_ROOT / "second-person-01.m4a",
        )
        first_identity = json.loads(first["body"].decode("utf-8"))["identity"]
        self.assertEqual("candidate_new_profile", first_identity.get("novelty"))
        rejected = self._upload_path(
            "POST",
            f"/api/identity/attempts/{mixed_attempt['id']}/retry",
            HUMAN_DEMO_ROOT / "control-01.wav",
        )
        rejected_identity = json.loads(rejected["body"].decode("utf-8"))["identity"]
        self.assertNotEqual("confirmed_new_profile", rejected_identity.get("novelty"))
        self.assertIn("novelty_pair_inconsistent", rejected_identity["reasons"])

    @unittest.skipUnless(HUMAN_DEMO_ROOT.is_dir(), "human demo fixtures are unavailable")
    def test_incremental_live_session(self):
        from tools import live_session_eval

        result = live_session_eval.evaluate_mode(
            HUMAN_DEMO_ROOT / "manifest.json",
            "staged",
        )
        summary = result["summary"]

        self.assertEqual(10, result["fixture_inventory_count"])
        self.assertEqual(10, len(result["observations"]))
        self.assertEqual(10, summary["total_submissions"])
        self.assertEqual(10, summary["valid_observations"])
        self.assertEqual(3, summary["represented_people"])
        self.assertEqual(3, summary["participants_created"])
        self.assertEqual(0, summary["wrong_person"])
        self.assertEqual(0, summary["duplicate_profiles"])
        self.assertEqual(0, summary["known_person_split"])
        self.assertTrue(result["release_gate"]["passed"], result)
