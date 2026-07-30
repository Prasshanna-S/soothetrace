"""Focused static contract for the accelerated continuous-care phone client.

The behavioral recorder contract is exercised in test_live_session_browser.mjs.
These checks guard the privacy, safety, accessibility, and packaging mistakes
that can be detected without a browser.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "web"
INDEX = WEB_ROOT / "index.html"
APP_JS = WEB_ROOT / "app.js"
APP_CSS = WEB_ROOT / "app.css"
MANIFEST = WEB_ROOT / "manifest.webmanifest"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class PhoneCareAssetTests(unittest.TestCase):
    def test_only_local_runtime_assets_are_required(self):
        """External assets would fail on the laptop hotspot used by the demo."""
        html = read(INDEX)
        self.assertNotRegex(html, r'(?:src|href)="https?://')
        for name in ("index.html", "app.js", "app.css", "manifest.webmanifest"):
            self.assertTrue((WEB_ROOT / name).is_file(), name)
        self.assertFalse((WEB_ROOT / "capture.html").exists())

    def test_manifest_allows_portrait_and_landscape(self):
        """A portrait-only manifest would break the planned landscape result."""
        manifest = json.loads(read(MANIFEST))
        self.assertNotEqual("portrait", manifest.get("orientation"))
        self.assertEqual("standalone", manifest.get("display"))


class PhoneCareMarkupTests(unittest.TestCase):
    REQUIRED_IDS = (
        "app-shell",
        "page-listen",
        "page-history",
        "page-baby",
        "tab-listen",
        "tab-history",
        "tab-baby",
        "profile-picker",
        "listen-name",
        "health-pill",
        "health-text",
        "error-banner",
        "connection-banner",
        "btn-conn-retry",
        "orb",
        "analysis-status",
        "suggestion-block",
        "g-headline",
        "g-recommendation",
        "g-evidence-summary",
        "g-interpretation",
        "basis-list",
        "incident-list",
        "btn-start",
        "btn-pause",
        "btn-resume",
        "btn-stop",
        "rec-chip",
        "rec-chip-state",
        "rec-chip-time",
        "outcome-form",
        "outcome-action",
        "settled-seg",
        "outcome-notes",
        "outcome-tags",
        "btn-save-outcome",
        "btn-discard",
        "history-limited",
        "baby-limited",
    )

    def setUp(self):
        self.html = read(INDEX)
        self.ids = re.findall(r'\bid="([^"]+)"', self.html)

    def test_live_path_elements_exist_exactly_once(self):
        """Missing or duplicate controls would make the phone path ambiguous."""
        for element_id in self.REQUIRED_IDS:
            with self.subTest(element_id=element_id):
                self.assertEqual(1, self.ids.count(element_id))
        self.assertEqual(len(self.ids), len(set(self.ids)))

    def test_accelerated_pages_are_honest_about_their_limits(self):
        """History and Baby must not look populated before their routes exist."""
        lowered = self.html.lower()
        self.assertIn("limited in this test build", lowered)
        self.assertIn("history", lowered)
        self.assertIn("baby", lowered)

    def test_no_profile_or_care_result_is_hard_coded(self):
        """The visible baby and guidance must come from the server."""
        combined = (self.html + read(APP_JS)).lower()
        self.assertNotIn("amara", combined)
        self.assertNotIn("preview_decision", combined)
        self.assertNotIn("what helped before: held baby upright", combined)

    def test_outcome_question_uses_direct_caregiver_wording(self):
        """The follow-up must use the approved plain-language choices."""
        self.assertIn("Did this help your baby calm down?", self.html)
        self.assertRegex(
            self.html,
            r'data-settled="true"[^>]*>\s*Yes\s*</button>',
        )
        self.assertRegex(
            self.html,
            r'data-settled="false"[^>]*>\s*Not yet\s*</button>',
        )
        self.assertRegex(
            self.html,
            r'data-settled="null"[^>]*>\s*Not sure\s*</button>',
        )
        self.assertNotIn("Did it settle?", self.html)


class PhoneCareScriptTests(unittest.TestCase):
    def setUp(self):
        self.js = read(APP_JS)
        self.compact = re.sub(r"\s+", "", self.js).lower()

    def test_default_path_has_no_simulated_or_route_gated_mode(self):
        """A mock query or false route switch could present a nonfunctional demo."""
        lowered = self.js.lower()
        for forbidden in (
            "routes_green",
            "preview_decision",
            "preview_steps",
            "initpreview",
            "?mock",
            "?preview",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lowered)

    def test_client_uses_the_minimum_care_http_surface(self):
        """Removing a route call would break a visible Listen action."""
        for fragment in (
            '"/api/health"',
            '"/api/profiles"',
            '"/api/care-sessions"',
            '"/chunks"',
            '"/pause"',
            '"/resume"',
            '"/stop"',
            '"/complete"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.js)
        self.assertIn('"delete"', self.compact)

    def test_capture_is_audio_only_and_uses_complete_six_second_files(self):
        """Video or timeslice fragments would violate the demo and decode contract."""
        lowered = self.js.lower()
        self.assertIn("const care_segment_ms = 6000", lowered)
        self.assertIn("const max_pending_segments = 1", lowered)
        self.assertIn("new mediarecorder(state.stream", lowered)
        self.assertNotRegex(lowered, r"\.start\s*\(\s*care_segment_ms")
        self.assertNotIn("getdisplaymedia", lowered)
        self.assertNotIn("video: true", lowered)

    def test_guidance_is_not_composed_in_the_browser(self):
        """The client may print server guidance but may not invent advice."""
        lowered = self.js.lower()
        for field in (
            "headline",
            "interpretation",
            "recommendation",
            "evidence_summary",
            "support_count",
            "basis",
            "scenarios",
        ):
            self.assertIn(field, lowered)
        for invented in (
            "you should",
            "we recommend",
            "best thing to try",
            "if you are getting overwhelmed",
            "consider talking to your pediatrician",
        ):
            with self.subTest(invented=invented):
                self.assertNotIn(invented, (read(INDEX) + self.js).lower())

    def test_outcome_validation_names_the_visible_choices(self):
        self.assertIn("Choose Yes, Not yet, or Not sure.", self.js)
        self.assertNotIn("Pick whether it settled", self.js)

    def test_no_forbidden_dash_characters_ship_in_web_copy(self):
        """The owner explicitly excludes em and en dashes from deliverables."""
        for path in (INDEX, APP_JS, APP_CSS, MANIFEST):
            with self.subTest(path=path.name):
                source = read(path)
                self.assertNotIn("\u2013", source)
                self.assertNotIn("\u2014", source)


class PhoneCareResponsiveTests(unittest.TestCase):
    def test_touch_targets_and_desktop_layout_are_explicit(self):
        """The desktop view must not remain a narrow mobile column."""
        css = read(APP_CSS).lower()
        self.assertRegex(css, r"--tap\s*:\s*44px")
        self.assertIn("@media (min-width: 900px) and (min-height: 581px)", css)
        self.assertIn("max-width: 1180px", css)
        self.assertIn("overflow-x: hidden", css)

    def test_orb_uses_webkit_safe_transparent_compositing(self):
        """Unpremultiplied WebGL alpha can render as a white canvas box on iOS."""
        js = re.sub(r"\s+", "", read(APP_JS))
        css = re.sub(r"\s+", "", read(APP_CSS)).lower()
        self.assertIn("premultipliedAlpha:true", js)
        self.assertNotIn("premultipliedAlpha:false", js)
        self.assertIn('gl_FragColor=vec4(rgb*a,a);', read(APP_JS))
        self.assertRegex(
            css,
            r"#orb\{[^}]*background:transparent;[^}]*border-radius:50%;",
        )

    def test_orb_motion_is_internal_and_reduced_motion_safe(self):
        """Listening motion must advect the shader, not spin the canvas."""
        js = re.sub(r"\s+", "", read(APP_JS))
        css = re.sub(r"\s+", "", read(APP_CSS)).lower()
        self.assertIn("uniformfloatuTurn;", js)
        self.assertIn("mat2rot2(floata)", js)
        self.assertIn("rot2(uTime*uTurn)", js)
        self.assertIn("reduce?0:cur.turn", js)
        self.assertNotIn("@keyframesorb-spin", css)
        self.assertNotRegex(css, r"#orb\{[^}]*animation:")


if __name__ == "__main__":
    unittest.main()
