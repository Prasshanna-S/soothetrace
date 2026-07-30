"""Static browser contract for the continuous care client (Listen build).

Replaces the operator-console suite on this branch: web/ is now the care app, so
the old assertions describe files that no longer exist. Coordination note in
docs/MESSAGES.md per the O9 plan, Task 8. Behavioral tests arrive with API
wiring in tests/test_live_session_browser.mjs.

Everything here reads the shipped files; nothing needs a browser.
"""
import json
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "app.css").read_text(encoding="utf-8")
JS = (WEB / "app.js").read_text(encoding="utf-8")
MANIFEST = (WEB / "manifest.webmanifest").read_text(encoding="utf-8")


class DocumentContractTests(unittest.TestCase):
    def test_single_document_has_three_destinations(self):
        for element_id in ("page-listen", "page-history", "page-baby",
                           "tab-listen", "tab-history", "tab-baby"):
            self.assertIn('id="%s"' % element_id, INDEX)
        self.assertEqual(1, INDEX.count("<html"), "one document, no reloads")

    def test_listen_page_carries_every_required_static_element(self):
        for element_id in (
            "listen-name", "btn-profile-switch", "health-pill", "orb",
            "analysis-status", "btn-start", "consent-line", "rec-chip",
            "rec-chip-time", "btn-pause", "btn-resume", "btn-stop",
            "suggestion-card", "g-headline", "g-recommendation",
            "g-evidence-summary", "g-interpretation", "basis-list",
            "incident-list", "outcome-form", "outcome-action", "settled-seg",
            "outcome-notes", "outcome-tags", "btn-save-outcome", "btn-discard",
            "safety-line", "saved-block", "interrupted-banner",
            "connection-banner", "error-banner", "preview-bar",
        ):
            self.assertIn('id="%s"' % element_id, INDEX, element_id)

    def test_fixed_chrome_lives_outside_the_animated_page(self):
        """An animated transform on an ancestor captures position fixed, so the
        control capsule must sit outside every .page container."""
        self.assertGreater(INDEX.index('id="ctl-capsule"'),
                           INDEX.index("</main>"))

    def test_start_listening_ships_disabled_until_readiness(self):
        start = re.search(r'<button[^>]*id="btn-start"[^>]*>', INDEX).group(0)
        self.assertIn("disabled", start)

    def test_settled_control_offers_exactly_the_three_allowed_values(self):
        for value in ('data-settled="true"', 'data-settled="false"',
                      'data-settled="null"'):
            self.assertIn(value, INDEX)

    def test_outcome_fields_carry_the_complete_route_limits(self):
        self.assertIn('maxlength="500"', INDEX)     # action
        self.assertIn('maxlength="1000"', INDEX)    # notes

    def test_every_inline_svg_use_site_declares_a_viewbox(self):
        for tag in re.findall(r"<svg [^>]*>", INDEX):
            if 'width="0"' in tag:                  # the hidden defs sheet
                continue
            self.assertIn("viewBox=", tag, tag)

    def test_light_status_bar_pairing(self):
        self.assertIn('name="apple-mobile-web-app-status-bar-style" content="default"', INDEX)
        self.assertIn('name="color-scheme" content="light"', INDEX)


class StylesheetContractTests(unittest.TestCase):
    def test_light_scheme_and_tap_floor(self):
        self.assertIn("color-scheme: light", CSS)
        self.assertIn("--tap: 44px", CSS)

    def test_ios_form_zoom_guard(self):
        self.assertIn("font-size: 16px;                       /* 16px floor stops iOS zoom", CSS)

    def test_dynamic_viewport_height(self):
        self.assertIn("min-height: 100dvh", CSS)

    def test_reduced_motion_is_honoured(self):
        self.assertIn("prefers-reduced-motion: reduce", CSS)

    def test_hands_free_capsule_is_body_scoped(self):
        self.assertIn('body[data-decision="latched"] #ctl-capsule', CSS)

    def test_landscape_takeover_exists(self):
        self.assertIn("(orientation: landscape) and (max-height: 580px)", CSS)


class ScriptContractTests(unittest.TestCase):
    def test_plan_constants(self):
        self.assertIn("const CARE_SEGMENT_MS = 12000", JS)
        self.assertIn("const MAX_PENDING_SEGMENTS = 1", JS)
        self.assertIn("const ROUTES_GREEN = false", JS)

    def test_exact_cry_presence_copy(self):
        self.assertIn("No infant cry detected in this segment", JS)
        self.assertIn("Cry-like sound, listening for a clearer segment", JS)
        self.assertIn("Infant-cry-like sound detected", JS)

    def test_capture_requests_flat_audio(self):
        self.assertIn("echoCancellation: false", JS)
        self.assertIn("noiseSuppression: false", JS)
        self.assertIn("autoGainControl: false", JS)

    def test_rotation_never_uses_timeslice_fragments(self):
        """recorder.start() must be argument free: start(timeslice) fragments are
        not standalone files, and only the first carries container headers."""
        self.assertIn("recorder.start()", JS)
        self.assertIsNone(re.search(r"recorder\.start\([^)]", JS))

    def test_wake_lock_and_interruption_handling(self):
        self.assertIn('navigator.wakeLock.request("screen")', JS)
        for event in ('"mute"', '"unmute"', '"ended"'):
            self.assertIn('addEventListener(%s' % event, JS)

    def test_guidance_renders_only_server_fields_verbatim(self):
        for field in ("headline", "interpretation", "recommendation",
                      "evidence_summary", "support_count"):
            self.assertIn(field, JS)
        self.assertIn("setText(ui.gRecommendation", JS)

    def test_first_decision_is_immutable(self):
        self.assertIn("if (state.decision) return;", JS)

    def test_playback_is_blocked_while_the_microphone_is_live(self):
        self.assertIn("if (state.micLive) return;", JS)
        self.assertIn("Playback is blocked while the microphone is live", JS)

    def test_no_dynamic_html_injection(self):
        """innerHTML only ever receives literal strings; data goes via textContent."""
        for line in JS.splitlines():
            if ".innerHTML" in line and "=" in line:
                self.assertNotIn("${", line, line)
        self.assertIn("textContent", JS)

    def test_image_slots_fall_back_to_the_icon_sheet(self):
        self.assertIn("function slotImage", JS)
        self.assertIn("ICONS[fallbackIconKey]", JS)


class ManifestContractTests(unittest.TestCase):
    def test_manifest_parses_and_has_no_orientation_lock(self):
        data = json.loads(MANIFEST)
        self.assertEqual("Cry Memory", data["name"])
        self.assertNotIn("orientation", data)


class PlainTextTests(unittest.TestCase):
    def test_every_shipped_file_is_plain_ascii(self):
        for name, text in (("index.html", INDEX), ("app.css", CSS),
                           ("app.js", JS), ("manifest.webmanifest", MANIFEST)):
            offenders = sorted({c for c in text if ord(c) > 127})
            self.assertEqual([], offenders, "%s: %r" % (name, offenders))


if __name__ == "__main__":
    unittest.main()
