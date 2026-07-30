from __future__ import annotations

import hashlib
import json
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "demo_assets" / "baby_audio"
MANIFEST = ASSET_ROOT / "manifest.json"


class BabyDemoAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_manifest_is_explicit_about_proxy_identity_and_license(self):
        self.assertEqual(
            self.manifest["identity_grouping_basis"],
            "shared_app_install_uuid_proxy_not_verified_infant",
        )
        self.assertFalse(self.manifest["independent_accuracy_dataset"])
        self.assertEqual(self.manifest["database_license"], "ODbL-1.0")
        self.assertEqual(self.manifest["contents_license"], "DbCL-1.0")
        self.assertTrue((ASSET_ROOT / "LICENSE-DATA.md").is_file())

    def test_three_groups_have_complete_rehearsal_sets(self):
        groups = self.manifest["groups"]
        self.assertEqual([group["label"] for group in groups], ["Baby 1", "Baby 2", "Baby 3"])
        self.assertEqual(len({group["source_app_install_uuid"] for group in groups}), 3)

        all_hashes = set()
        for group in groups:
            records = group["records"]
            self.assertEqual(len(records), 6)
            self.assertEqual(
                [record["demo_role"] for record in records],
                [
                    "enrollment",
                    "enrollment",
                    "enrollment",
                    "held_out_rehearsal_query",
                    "retry",
                    "extra",
                ],
            )
            expected_prefix = group["source_app_install_uuid"].casefold()
            for record in records:
                self.assertTrue(
                    Path(record["source_relative_path"]).name.casefold().startswith(expected_prefix)
                )
                self.assertNotIn(record["sha256"], all_hashes)
                all_hashes.add(record["sha256"])

        self.assertEqual(len(all_hashes), 18)

    def test_every_declared_wav_exists_and_matches_manifest(self):
        declared = []
        for group in self.manifest["groups"]:
            for record in group["records"]:
                path = ASSET_ROOT / record["path"]
                declared.append(path.resolve())
                self.assertTrue(path.is_file(), record["path"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record["sha256"])
                with wave.open(str(path), "rb") as wav:
                    duration = wav.getnframes() / wav.getframerate()
                    self.assertEqual(wav.getnchannels(), record["channels"])
                    self.assertEqual(wav.getframerate(), record["sample_rate_hz"])
                    self.assertAlmostEqual(duration, record["duration_seconds"], places=2)

        actual = sorted(path.resolve() for path in ASSET_ROOT.rglob("*.wav"))
        self.assertEqual(sorted(declared), actual)


if __name__ == "__main__":
    unittest.main()
