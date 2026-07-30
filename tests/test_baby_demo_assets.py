from __future__ import annotations

import hashlib
import json
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "demo_assets" / "baby_audio"
MANIFEST = ASSET_ROOT / "manifest.json"
SHOWCASE_ROOT = ASSET_ROOT / "warning-demo"
SHOWCASE_MANIFEST = SHOWCASE_ROOT / "showcase-manifest.json"


class BabyDemoAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.showcase = json.loads(SHOWCASE_MANIFEST.read_text(encoding="utf-8"))

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

        for record in self.showcase["assets"]:
            path = SHOWCASE_ROOT / record["path"]
            declared.append(path.resolve())
            self.assertTrue(path.is_file(), record["path"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                record["asset_sha256"],
            )
            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
                self.assertEqual(
                    wav.getnchannels(),
                    record["format"]["channels"],
                )
                self.assertEqual(
                    wav.getframerate(),
                    record["format"]["sample_rate_hz"],
                )
                self.assertAlmostEqual(
                    duration,
                    record["format"]["duration_seconds"],
                    places=2,
                )

        for record in self.showcase["supporting_files"]:
            path = SHOWCASE_ROOT / record["path"]
            declared.append(path.resolve())
            self.assertTrue(path.is_file(), record["path"])
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                record["sha256"],
            )
            with wave.open(str(path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
                self.assertEqual(wav.getnchannels(), record["channels"])
                self.assertEqual(wav.getframerate(), record["sample_rate_hz"])
                self.assertAlmostEqual(duration, record["duration_seconds"], places=2)

        curated_group_wavs = sorted(
            path.resolve()
            for group in self.manifest["groups"]
            for path in (ASSET_ROOT / group["directory"]).rglob("*.wav")
        )
        curated_declared = sorted(
            (ASSET_ROOT / record["path"]).resolve()
            for group in self.manifest["groups"]
            for record in group["records"]
        )
        self.assertEqual(curated_declared, curated_group_wavs)

    def test_showcase_has_three_distinct_verified_latching_sources(self):
        records = self.showcase["assets"]
        self.assertEqual([record["order"] for record in records], [1, 2, 3])
        self.assertEqual(
            [Path(record["source_recording"]).name for record in records],
            ["07-X4.wav", "13-X7.wav", "15-X8.wav"],
        )
        self.assertEqual(len({record["source_sha256"] for record in records}), 3)
        for record in records:
            probe = record["six_second_quiet_probe"]
            self.assertEqual(probe["cry_gate_status"], "infant_cry_detected")
            self.assertEqual(probe["identity_status"], "match")
            self.assertEqual(probe["profile"], "Demo Baby")
            self.assertEqual(probe["chunk_status"], "guidance_latched")
            for subtitle_key in ("subtitle", "distinct_output_spike_subtitle"):
                subtitle = SHOWCASE_ROOT / record[subtitle_key]
                self.assertTrue(subtitle.is_file(), record[subtitle_key])

        distinct = self.showcase["validated_distinct_output_spike"]["result"]
        self.assertEqual((distinct["passed"], distinct["tested"]), (3, 3))
        self.assertEqual(
            [item["recommendation"] for item in distinct["outputs"]],
            [
                "What helped before: offered bottle.",
                "What helped before: held baby upright.",
                "What helped before: turned on white noise.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
