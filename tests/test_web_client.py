"""Static-asset contract tests for the dual-mode web client in web/.

These tests exist because the client's hard rules are invisible at runtime until a demo is
already on stage. A regression here is a product failure, not a cosmetic one:

  * a numeric identity number reaching the DOM would present an unfalsifiable confidence;
  * a client-authored care string would be advice the system cannot defend;
  * a video capture call would move the legal posture from one-party to all-party consent;
  * a missing consent line, a missing manifest or a lost safe-area rule breaks the phone build.

Run: python -m unittest tests.test_web_client -v
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

# Only these four names are served by src/http_api.py's static route.
SERVED_FILES = ("index.html", "app.js", "app.css", "manifest.webmanifest")

REQUIRED_IDS = (
    # shell and global state
    "app-shell",
    "health-status",
    "mode-label",
    "error-banner",
    "secure-warning",
    "consent",
    "consent-text",
    # requirement 1: kind selection is the first screen
    "screen-mode",
    "mode-heading",
    "btn-kind-infant",
    "btn-kind-imitation",
    # requirement 2: record AND choose a file
    "screen-work",
    "work-heading",
    "btn-change-mode",
    "panel-capture",
    "capture-hint",
    "btn-record-start",
    "btn-record-stop",
    "rec-bar",
    "rec-bar-time",
    "rec-bar-note",
    "record-state",
    "record-timer",
    "playback-block-notice",
    "file-input",
    "clip-summary",
    "capture-diagnostics",
    "constraints-applied",
    "mime-selected",
    "clip-quality",
    # human imitation uses a dedicated live-session console
    "live-session-console",
    "live-capture-panel",
    "live-result-panel",
    "live-session-timeline",
    "live-participant-strip",
    "btn-new-live-session",
    # requirement 4: profiles with enrollment counts
    "panel-profiles",
    "profile-name-input",
    "manual-profile-create",
    "btn-create-profile",
    "profile-status",
    "profile-list",
    "profiles-empty",
    "session-summary",
    "session-phase",
    "btn-new-human-session",
    # requirement 3: enrollment and query are separate explicit actions
    "panel-enroll",
    "profile-select",
    "btn-enroll",
    "enroll-status",
    "panel-query",
    "btn-query",
    "query-status",
    # requirement 5: result states, including the one retry
    "panel-result",
    "result-heading",
    "result-status",
    "result-profile",
    "result-reasons",
    "retry-block",
    "retry-hint",
    "btn-retry",
    # requirement 6: server-authored guidance, large and stable
    "guidance-block",
    "guidance-interpretation",
    "guidance-recommendation",
    "guidance-evidence",
    "guidance-empty",
    "reveal-block",
    "btn-reveal-guidance",
    # requirement 7: supporting incidents below the result
    "incidents-block",
    "incidents-list",
    "incidents-empty",
    # requirement 8: outcome save stays available
    "outcome-form",
    "outcome-input",
    "outcome-tags",
    "btn-save-outcome",
    "outcome-status",
    # LIABILITY.md section 5
    "safety-message",
)

# Words that can only appear in the client if it is rendering an identity number. `score` and
# `margin` are DEBUG ONLY in src/identity.py and the HTTP layer never sends them; the client must
# not invent, request or display them either.
FORBIDDEN_JS_TOKENS = (
    "score",
    "margin",
    "similarity",
    "confidence",
    "percent",
    "toprecision",
)

# Any of these would mean video capture exists somewhere in the client. "video/" is deliberately
# broad: src/audio_ingest.py happens to decode "video/mp4", but an audio-only client must never
# name a video container as something it uploads, and a video MIME in the client is how that
# would start. A .mp4 from the file picker is relabelled audio/mp4 instead.
FORBIDDEN_VIDEO_TOKENS = (
    "getdisplaymedia",
    "video: true",
    "video:true",
    "imagecapture",
    "facingmode",
    "<video",
    "capturestream",
    "video/",
)

# Verbatim server copy from src/guidance.py. If any of it is hard-coded in the client, the client
# is authoring care text instead of printing what the server decided.
SERVER_GUIDANCE_LITERALS = (
    "This resembles earlier incidents for this profile.",
    "What helped before:",
    "Supported by",
    "No repeated helpful pattern is recorded",
    "There is not enough profile history yet",
)

# Cause vocabulary. docs/LIABILITY.md section 1: no output may contain a cause label the caregiver
# did not type herself, and a *placeholder* counts, because a placeholder puts the label in her
# mouth. Matched on word boundaries so that "window" does not read as "wind" and "overtired" and
# "tired" are caught separately. These are checked against index.html AND app.js, so neither a
# reason string, a status line nor an input hint can smuggle a cause in.
CAUSE_VOCABULARY = (
    "colic", "colicky", "hungry", "hunger", "starving", "teething", "teeth",
    "gas", "gassy", "wind", "reflux", "heartburn", "overtired", "tired",
    "exhausted", "lonely", "bored", "scared", "frightened", "overstimulated",
    "pain", "painful", "hurts", "hurting", "sick", "unwell", "fever", "earache",
    "diaper", "nappy", "growth spurt", "separation anxiety", "discomfort",
    "uncomfortable", "probably", "likely because", "the reason",
    "because your baby", "because the baby",
)

# Care-advice vocabulary. Guidance on a matched infant must be printed verbatim from the server's
# guidance.* fields, so ANY care verb hard-coded in the client is client-authored advice, whether
# or not it copies a server literal. The client's own imperatives are about operating the app
# ("Record again", "Lower the volume"), never about handling a baby.
CARE_ADVICE_VOCABULARY = (
    "rock", "rocking", "swaddle", "swaddling", "burp", "burping", "shush",
    "shushing", "soothe", "soothing", "pacifier", "dummy", "bottle", "feeding",
    "feed her", "feed him", "nurse", "nursing", "bounce", "bouncing", "cuddle",
    "cuddling", "massage", "white noise", "warm bath", "car ride",
    "most babies", "you should", "we recommend", "best thing to try",
    "try this", "will settle",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def collapse(source: str) -> str:
    """Whitespace-collapsed source, so a statement sequence can be asserted without pinning
    indentation. Used where the ORDER of two statements is the product rule."""
    return " ".join(source.split())


def function_body(source: str, name: str) -> str:
    """The braced body of `function name(...)`, by brace matching."""
    marker = f"function {name}("
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"function {name} is missing from the client")
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    raise AssertionError(f"unbalanced braces in {name}")


class AssetPresenceTests(unittest.TestCase):
    def test_every_served_file_exists(self):
        for name in SERVED_FILES:
            with self.subTest(name=name):
                self.assertTrue((WEB_ROOT / name).is_file(), f"web/{name} is missing")

    def test_no_unserved_assets_are_required(self):
        """src/http_api.py serves exactly four names, so nothing else may be referenced."""
        html = read(INDEX)
        for reference in re.findall(r'(?:href|src)="(/[^"]+)"', html):
            with self.subTest(reference=reference):
                self.assertIn(
                    reference.lstrip("/"),
                    SERVED_FILES,
                    f"{reference} is not one of the four static names the server serves",
                )


class ElementContractTests(unittest.TestCase):
    def setUp(self):
        self.html = read(INDEX)
        self.ids = re.findall(r'\bid="([^"]+)"', self.html)

    def test_required_ids_exist_exactly_once(self):
        for element_id in REQUIRED_IDS:
            with self.subTest(element_id=element_id):
                self.assertEqual(
                    self.ids.count(element_id),
                    1,
                    f'id="{element_id}" must appear exactly once in web/index.html',
                )

    def test_ids_are_unique(self):
        self.assertEqual(len(self.ids), len(set(self.ids)), "duplicate element ids")

    def test_every_id_the_script_looks_up_exists_in_the_markup(self):
        js = read(APP_JS)
        for element_id in re.findall(r'\bel\("([^"]+)"\)', js):
            with self.subTest(element_id=element_id):
                self.assertIn(element_id, self.ids, f"app.js reads a missing id: {element_id}")

    def test_file_input_accepts_audio_only(self):
        self.assertRegex(
            self.html,
            r'<input[^>]*type="file"[^>]*accept="audio/\*"',
            'the file path must be <input type="file" accept="audio/*">',
        )

    def test_enrollment_and_query_are_separate_labelled_actions(self):
        self.assertIn('id="panel-enroll"', self.html)
        self.assertIn('id="panel-query"', self.html)
        enroll = self.html.index('id="btn-enroll"')
        query = self.html.index('id="btn-query"')
        self.assertNotEqual(enroll, query)

    def test_supporting_incidents_and_outcome_come_after_the_result_text(self):
        guidance = self.html.index('id="guidance-block"')
        incidents = self.html.index('id="incidents-block"')
        outcome = self.html.index('id="outcome-form"')
        self.assertLess(guidance, incidents, "supporting incidents must sit below the result")
        self.assertLess(guidance, outcome, "outcome save must sit below the result")

    def test_live_regions_are_announced(self):
        self.assertIn('role="status"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('role="alert"', self.html)

    def test_headings_are_focusable_for_keyboard_focus_management(self):
        for element_id in ("mode-heading", "work-heading", "result-heading"):
            with self.subTest(element_id=element_id):
                self.assertRegex(
                    self.html,
                    rf'id="{element_id}"[^>]*tabindex="-1"',
                    f"{element_id} must be focusable so focus can move with the flow",
                )

    def test_no_inline_script_or_style_under_the_server_csp(self):
        """The server sends script-src 'self'; style-src 'self' - inline would be blocked."""
        self.assertNotRegex(self.html, r"<script(?![^>]*\bsrc=)[^>]*>")
        self.assertNotRegex(self.html, r"\sstyle=\"")
        self.assertNotRegex(self.html, r"\son[a-z]+=\"")


class LiveSessionContractTests(unittest.TestCase):
    """Static boundaries for the human-imitation live-session workspace."""

    def setUp(self):
        self.html = read(INDEX)
        self.js = read(APP_JS)
        self.css = read(APP_CSS)

    def test_live_workspace_anchors_exist_once(self):
        ids = re.findall(r'\bid="([^"]+)"', self.html)
        for element_id in (
            "live-session-console",
            "live-capture-panel",
            "live-result-panel",
            "live-session-timeline",
            "live-participant-strip",
            "btn-new-live-session",
        ):
            with self.subTest(element_id=element_id):
                self.assertEqual(1, ids.count(element_id))

    def test_live_client_calls_session_api_and_handles_every_public_state(self):
        self.assertIn('"/api/live-sessions"', self.js)
        self.assertIn("/observations", self.js)
        for status in (
            "provisional_created",
            "participant",
            "leaning",
            "possible_new",
            "duplicate",
            "invalid",
        ):
            with self.subTest(status=status):
                self.assertIn(f'"{status}"', self.js)

    def test_live_workspace_has_real_wide_layout_and_phone_collapse(self):
        self.assertIn("--workspace: 1180px;", self.css)
        self.assertIn(
            "grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);",
            self.css,
        )
        phone = re.search(
            r"@media\s*\(max-width:\s*819px\)\s*\{(?P<body>.*?)\n\}",
            self.css,
            re.DOTALL,
        )
        self.assertIsNotNone(phone, "the live workspace must collapse below 820px")
        self.assertRegex(
            phone.group("body"),
            r"#live-session-console\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)",
        )

    def test_human_mode_uses_live_console_without_removing_baby_surfaces(self):
        for element_id in (
            "panel-profiles",
            "panel-enroll",
            "panel-query",
            "panel-result",
            "guidance-block",
            "outcome-form",
            "not-in-this-build",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('ui.body.dataset.workflow = "live-session"', self.js)
        self.assertIn("show(ui.liveSessionConsole, liveMode)", self.js)
        self.assertIn("show(ui.legacyWorkflow, !liveMode)", self.js)

    def test_roadmap_stays_documented_but_never_enters_the_demo_surface(self):
        roadmap = re.search(
            r'<section\b(?=[^>]*\bid="not-in-this-build")[^>]*>',
            self.html,
        )
        self.assertIsNotNone(roadmap, "the documented roadmap markup must remain in index.html")
        self.assertRegex(
            roadmap.group(0),
            r"\bhidden\b",
            "the roadmap must be hidden on the initial mode screen",
        )
        self.assertNotIn(
            "ui.roadmap",
            self.js,
            "client mode changes must never reveal the documented roadmap",
        )


class MobileAndPwaTests(unittest.TestCase):
    def setUp(self):
        self.html = read(INDEX)
        self.css = read(APP_CSS)

    def test_manifest_is_linked_and_valid_json(self):
        self.assertIn('rel="manifest"', self.html)
        self.assertIn('href="/manifest.webmanifest"', self.html)
        manifest = json.loads(read(MANIFEST))
        self.assertIsInstance(manifest, dict)
        for key in ("name", "short_name", "start_url", "display", "icons"):
            with self.subTest(key=key):
                self.assertIn(key, manifest)
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/")
        self.assertTrue(manifest["icons"], "the manifest needs at least one icon")
        for icon in manifest["icons"]:
            with self.subTest(icon=icon.get("sizes")):
                # Only four static names are served, so an icon must be inline data.
                self.assertTrue(
                    icon["src"].startswith("data:image/"),
                    "icons must be data: URIs because the server serves no image route",
                )

    def test_ios_standalone_and_viewport(self):
        self.assertIn("viewport-fit=cover", self.html)
        self.assertIn('name="apple-mobile-web-app-capable"', self.html)
        self.assertIn('name="apple-mobile-web-app-status-bar-style"', self.html)
        self.assertNotIn("user-scalable=no", self.html)
        self.assertNotIn("maximum-scale=1", self.html)

    def test_safe_area_insets_are_handled(self):
        for side in ("top", "right", "bottom", "left"):
            with self.subTest(side=side):
                self.assertIn(f"env(safe-area-inset-{side}", self.css)

    def test_touch_targets_are_at_least_44px(self):
        self.assertRegex(self.css, r"--tap:\s*44px")
        self.assertIn("min-height: var(--tap)", self.css)
        self.assertIn("min-width: var(--tap)", self.css)
        for match in re.findall(r"min-(?:height|width):\s*(\d+)px", self.css):
            with self.subTest(value=match):
                self.assertGreaterEqual(int(match), 44, "a control is smaller than 44px")

    def test_reduced_motion_is_respected(self):
        self.assertIn("prefers-reduced-motion: reduce", self.css)

    def test_headline_text_is_room_readable_on_the_demo_phone(self):
        """A clamp() with a vw middle term COLLAPSES on a narrow screen: the phone gets the floor,
        not the ceiling. `clamp(1.45rem, 6vw, 2.3rem)` measured 36.8px on a 1280px laptop and only
        23.6px on a 393px iPhone, so asserting merely that clamp() is used proved nothing about the
        device the demo runs on. Each floor below is an absolute px value, and that floor is what
        an iPhone actually renders.
        """
        floors = {
            ".guidance-large": 34,
            ".verdict-name": 40,
            ".verdict": 24,
            ".guidance-evidence": 19,
        }
        for selector, minimum in floors.items():
            with self.subTest(selector=selector):
                match = re.search(
                    rf"\{selector}\s*\{{[^}}]*font-size:\s*clamp\(\s*([0-9.]+)px",
                    self.css,
                )
                self.assertIsNotNone(
                    match,
                    f"{selector} must set font-size with an absolute px floor inside clamp()",
                )
                self.assertGreaterEqual(
                    float(match.group(1)),
                    minimum,
                    f"{selector} collapses below {minimum}px on a 393px iPhone",
                )

    def test_single_dark_appearance_keeps_the_ios_status_bar_legible(self):
        """apple-mobile-web-app-status-bar-style=black-translucent makes iOS draw the status bar
        clock and battery in WHITE over the page. A light theme therefore hides them, and shows
        the audience an appearance nobody rehearsed."""
        self.assertIn('content="black-translucent"', self.html)
        self.assertIn('name="color-scheme" content="dark"', self.html)
        self.assertIn("color-scheme: dark", self.css)
        self.assertNotRegex(
            self.css,
            r"@media\s*\(\s*prefers-color-scheme:\s*light",
            "a light theme under a black-translucent status bar hides the clock and battery",
        )

    def test_disabled_controls_are_not_dimmed_into_illegibility(self):
        """opacity: 0.45 on a green primary composites to about 1.7:1 against the card, so the
        label of the control the presenter needs next is unreadable on a stage projector."""
        block = re.search(r"button\[disabled\]\s*\{([^}]*)\}", self.css)
        self.assertIsNotNone(block, "disabled controls need an explicit style")
        body = block.group(1)
        self.assertNotRegex(
            body, r"opacity:\s*0?\.\d", "do not dim a disabled control with opacity"
        )
        self.assertIn("background: var(--card-2)", body)
        self.assertIn("color: var(--ink-dim)", body)

    def test_recording_state_stays_visible_after_scrolling(self):
        """#record-state and #record-timer are in normal flow, and the next targets are hundreds
        of pixels below them, so scrolling used to hide the fact that the mic was live for up to
        two minutes."""
        js = read(APP_JS)
        self.assertIn('id="rec-bar"', self.html)
        self.assertRegex(self.css, r"\.rec-bar\s*\{[^}]*position:\s*fixed")
        self.assertRegex(self.css, r"\.rec-bar\s*\{[^}]*env\(safe-area-inset-top")
        self.assertIn("show(ui.recBar, recording)", js)
        self.assertIn("setText(ui.recBarTime, text)", js)
        # a two-minute hard stop must announce itself before it fires
        self.assertIn("RECORD_WARN_MS", js)
        self.assertRegex(self.css, r"\.rec-bar\[data-warn=\"true\"\]")
        # and idle must not look like armed: the idle timer is dimmed
        self.assertRegex(self.css, r'body:not\(\[data-recording="true"\]\)\s*\.timer')


class SafetyCopyTests(unittest.TestCase):
    def setUp(self):
        self.html = read(INDEX)

    def test_visible_consent_text(self):
        self.assertIn("Recording consent", self.html)
        self.assertIn("This app records audio only. It never records video.", self.html)
        self.assertNotIn('id="consent" hidden', self.html)

    def test_caregiver_safety_message_is_present(self):
        # docs/LIABILITY.md section 5 - required, not optional.
        flat = " ".join(self.html.split())
        self.assertIn("it is okay to place your baby on their back in a safe place", flat)
        self.assertIn("step away for a few minutes", flat)
        self.assertIn("consider talking to your pediatrician", flat)

    def test_no_cause_claim_copy(self):
        lowered = self.html.lower() + read(APP_JS).lower()
        for phrase in (
            "why your baby",
            "why the baby",
            "because your baby",
            "is hungry",
            "is in pain",
            "diagnosis",
            "diagnose",
            "the cause is",
        ):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, lowered, f"cause claim in client copy: {phrase}")

    def test_no_cause_vocabulary_anywhere_in_client_copy(self):
        """A single cause word is enough to break the product rule, and a placeholder counts.

        The earlier phrase blacklist let bare cause labels through: "overtired", "teething",
        "reflux" and "gas" all passed it, and one of them was shipping in the context-tag
        placeholder. Word boundaries, so "window" is not "wind".
        """
        lowered = self.html.lower() + read(APP_JS).lower()
        for word in CAUSE_VOCABULARY:
            with self.subTest(word=word):
                self.assertIsNone(
                    re.search(rf"\b{re.escape(word)}\b", lowered),
                    f"cause label in client copy: {word!r}. The system reports what the caregiver "
                    "said, never what it meant.",
                )

    def test_no_client_authored_care_advice_vocabulary(self):
        """Forbidding only the server's verbatim literals let INVENTED advice through.

        Care text on a matched infant comes from guidance.interpretation / .recommendation /
        .evidence_summary and nowhere else, so no care verb belongs in the client at all.
        """
        lowered = self.html.lower() + read(APP_JS).lower()
        for word in CARE_ADVICE_VOCABULARY:
            with self.subTest(word=word):
                self.assertIsNone(
                    re.search(rf"\b{re.escape(word)}\b", lowered),
                    f"client-authored care advice: {word!r}. Guidance is printed from the server, "
                    "never composed here.",
                )


class ScriptContractTests(unittest.TestCase):
    def setUp(self):
        self.js = read(APP_JS)
        self.lowered = self.js.lower()

    def test_no_numeric_identity_rendering(self):
        for token in FORBIDDEN_JS_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(
                    token,
                    self.lowered,
                    f"'{token}' must never appear in the client: identity numbers are debug only",
                )

    def test_no_percentage_formatting(self):
        self.assertNotIn("%", self.js, "no percentage may ever be rendered as confidence")

    def test_renders_status_band_and_reasons_only(self):
        self.assertIn("identity.status", self.js)
        self.assertIn("identity.band", self.js)
        self.assertIn("identity.reasons", self.js)

    def test_renders_a_non_confirmed_session_direction(self):
        self.assertIn("identity.leaning_profile", self.js)
        self.assertIn('"Leaning toward"', self.js)
        self.assertIn("Not confirmed", self.js)
        self.assertIn("clear_lead_not_confirmed", self.js)
        self.assertIn("close_call_not_confirmed", self.js)
        self.assertIn('dataset.verdict = "leaning"', self.js)
        self.assertIn('#panel-result[data-verdict="leaning"]', read(APP_CSS))

    def test_no_video_capture_anywhere(self):
        for token in FORBIDDEN_VIDEO_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, self.lowered, f"video capture token present: {token}")
        self.assertIn("video: false", self.js, "getUserMedia must explicitly ask for audio only")

    def test_guidance_comes_from_server_fields(self):
        for field in ("interpretation", "recommendation", "evidence_summary"):
            with self.subTest(field=field):
                self.assertIn(f"payload.{field}", self.js)
        self.assertIn("guidanceInterpretation", self.js)
        self.assertIn("guidanceRecommendation", self.js)
        self.assertIn("guidanceEvidence", self.js)

    def test_no_client_authored_care_copy(self):
        for literal in SERVER_GUIDANCE_LITERALS:
            with self.subTest(literal=literal):
                self.assertNotIn(
                    literal,
                    self.js,
                    "care text must be printed from the server response, never hard-coded",
                )

    def test_guidance_slots_receive_a_bare_server_value_and_nothing_else(self):
        """Checking that "payload.recommendation" merely APPEARS does not stop
        setText(ui.guidanceRecommendation, "Best thing to try now: " + payload.action).
        Every write into a guidance slot must be a bare value, or the empty reset.
        """
        allowed = {"interpretation", "recommendation", "evidence", '""'}
        calls = re.findall(r"setText\(\s*ui\.(guidance\w+),\s*([^)]*)\)", self.js)
        self.assertEqual(
            len(calls), 6, "expected three guidance writes and three resets"
        )
        for slot, argument in calls:
            with self.subTest(slot=slot, argument=argument):
                self.assertIn(
                    argument.strip(),
                    allowed,
                    f"{slot} is written with a composed value: the client must not author or "
                    "paraphrase care text",
                )

    def test_render_guidance_authors_no_text_of_its_own(self):
        """renderGuidance may select which server field goes in which slot. It may not write
        prose. The only string literals allowed in its body are the two typeof guards."""
        body = function_body(self.js, "renderGuidance")
        literals = set(re.findall(r'"([^"\\]*)"', body))
        literals |= set(re.findall(r"'([^'\\]*)'", body))
        literals |= set(re.findall(r"`([^`\\]*)`", body))
        self.assertEqual(
            literals - {"object", "string", ""},
            set(),
            "renderGuidance contains client-authored text",
        )

    def test_guidance_is_written_stably(self):
        """Requirement 6: the large result text must not be replaced on every render."""
        self.assertRegex(self.js, r"function setText\([^)]*\)\s*\{[^}]*textContent !== next")
        self.assertIn("setText(ui.guidanceInterpretation", self.js)
        self.assertIn("setText(ui.guidanceRecommendation", self.js)
        self.assertIn("setText(ui.guidanceEvidence", self.js)

    def test_capture_constraints_disable_browser_processing(self):
        for constraint in ("echoCancellation: false", "noiseSuppression: false", "autoGainControl: false"):
            with self.subTest(constraint=constraint):
                self.assertIn(constraint, self.js)

    def test_applied_constraints_are_read_back_and_displayed(self):
        self.assertIn("getSettings", self.js)
        self.assertIn("setText(\n    capture.constraints", self.js.replace("\r", ""))
        self.assertIn("constraints: ui.constraints", self.js)
        self.assertIn("constraints: ui.liveConstraints", self.js)

    def test_recorder_mime_is_feature_detected_not_hardcoded(self):
        self.assertIn("MediaRecorder.isTypeSupported", self.js)
        self.assertIn('"audio/mp4', self.js)
        self.assertIn('"audio/webm', self.js)
        # the uploaded Content-Type is whatever the browser produced
        self.assertIn('"Content-Type": clip.contentType', self.js)

    def test_secure_context_failure_is_explicit_and_actionable(self):
        self.assertIn("window.isSecureContext", self.js)
        self.assertIn("http://localhost", self.js)
        self.assertIn("NotAllowedError", self.js)

    def test_retry_requires_a_second_independent_recording(self):
        self.assertIn("sentClipIds", self.js)
        self.assertRegex(self.js, r"sentClipIds\.has\(state\.clip\.id\)")
        self.assertIn("second independent recording", self.js.lower())

    def test_invalid_capture_keeps_using_the_first_capture_route(self):
        """src/identity.py stores an invalid capture as seq 0: it is not the first capture, so the
        next clip must go to /captures again. Offering /retry there is refused by the server."""
        self.assertIn("firstCaptureDone", self.js)
        self.assertRegex(self.js, r"if \(state\.attempt && !state\.attempt\.firstCaptureDone\)")
        self.assertIn('if (status !== "invalid") state.attempt.firstCaptureDone = true;', self.js)
        self.assertRegex(self.js, r"attempt\.firstCaptureDone && attempt\.retryAllowed")

    def test_ios_audio_session_interruptions_cannot_leave_a_false_live_ui(self):
        """The worst on-stage outcome is a confident UI over a silent capture.

        iOS mutes the track for an audio session interruption (a call, Siri, Control Center) and
        ends it on a screen lock, and neither raises a recorder error. Backgrounding a standalone
        web app fires visibilitychange, not pagehide, so pagehide alone left the recorder stalled
        with the timer still climbing.
        """
        for event in ('"mute"', '"unmute"', '"ended"'):
            with self.subTest(event=event):
                self.assertIn(f"track.addEventListener({event}", self.js)
        self.assertIn('document.addEventListener("visibilitychange"', self.js)
        self.assertIn("document.hidden && state.recording", self.js)
        # iOS auto-locks in 30 seconds by default, well inside a two-minute capture
        self.assertIn('navigator.wakeLock.request("screen")', self.js)
        self.assertIn("releaseScreenAwake()", self.js)

    def test_playback_is_blocked_while_recording(self):
        self.assertRegex(self.js, r"function blockPlayback\(")
        self.assertIn("player.pause()", self.js)
        self.assertIn("blockPlayback(recording)", self.js)

    def test_outcome_provenance_is_always_rendered(self):
        self.assertIn("outcome_src", self.js)
        for source in ("caregiver", "inferred", "seed"):
            with self.subTest(source=source):
                self.assertIn(f"{source}:", self.js)
        self.assertIn("Synthetic demo data", self.js)

    def test_outcome_provenance_badge_is_attached_unconditionally(self):
        """Greping for the badge STRINGS does not prove the badge is attached.

        Blanking the text, or wrapping the append in `if (scenario.outcome_src)`, both left the
        older test green while a seeded row rendered with no provenance at all. The badge text and
        its append must be one unconditional statement pair, with a fallback for an absent value.
        """
        self.assertIn(
            'source.textContent = OUTCOME_SOURCE_TEXT[key] || "Outcome source not recorded"; '
            "item.appendChild(source);",
            collapse(self.js),
            "the provenance badge must be written with a fallback and appended unconditionally",
        )

    def test_supporting_incident_audio_is_a_playable_element(self):
        """Requirement 7 playback. Swapping the <audio> for a <span> broke nothing before."""
        flat = collapse(self.js)
        self.assertIn('const player = document.createElement("audio");', flat)
        self.assertIn("player.src = scenario.audio_url;", flat)
        self.assertIn("item.appendChild(player);", flat)
        self.assertIn("player.controls", self.js)

    def test_only_same_origin_api_calls(self):
        for url in re.findall(r'fetch\(\s*[`"\']([^`"\']+)', self.js):
            with self.subTest(url=url):
                self.assertTrue(url.startswith("/"), f"non-relative fetch: {url}")
        for path in re.findall(r'["\'`](/api/[^"\'`$]*)', self.js):
            with self.subTest(path=path):
                self.assertTrue(path.startswith("/api/"))
        # no remote origin may be requested: the server CSP is default-src 'self' anyway
        self.assertIsNone(
            re.search(r'(?:fetch|src|href|url)\s*[=(]\s*["\'`]https?://', self.js),
            "the client must never request a remote origin",
        )


class ApiSurfaceTests(unittest.TestCase):
    """Every path the client calls must exist in src/http_api.py."""

    def setUp(self):
        self.js = read(APP_JS)
        self.api = read(REPO_ROOT / "src" / "http_api.py")

    def test_client_paths_exist_in_the_server(self):
        expected = {
            "/api/health": '"/api/health"',
            "/api/profiles": '"/api/profiles"',
            "/api/identity/attempts": '"/api/identity/attempts"',
        }
        for path, needle in expected.items():
            with self.subTest(path=path):
                self.assertIn(path, self.js)
                self.assertIn(needle, self.api)

    def test_templated_paths_match_server_routes(self):
        self.assertIn("/api/profiles/${profileId}/enroll", self.js)
        self.assertIn('parts[3] == "enroll"', self.api)
        self.assertIn("/api/identity/attempts/${attempt.id}/captures", self.js)
        self.assertIn("/api/identity/attempts/${state.attempt.id}/retry", self.js)
        self.assertIn('parts[4] in {"captures", "retry"}', self.api)
        self.assertIn("/api/incidents/${state.attempt.id}/complete", self.js)
        self.assertIn("/api/incidents/${state.attempt.id}/preview", self.js)
        self.assertIn('parts[3] in {"preview", "complete"}', self.api)

    def test_supporting_audio_uses_the_server_supplied_url(self):
        # The client must not build audio URLs itself; the API returns audio_url per episode.
        self.assertIn("audio_url", self.js)
        self.assertIn('f"/api/audio/episodes/{episode_id}"', self.api)
        self.assertNotIn('"/api/audio/', self.js)

    def test_only_supported_upload_mimes_are_offered(self):
        ingest = read(REPO_ROOT / "src" / "audio_ingest.py")
        supported = set(re.findall(r'"((?:audio|video)/[^"]+)":\s*"\.', ingest))
        offered = set(re.findall(r'"((?:audio|video)/[a-z0-9.;=+-]+)",', self.js))
        self.assertTrue(offered, "the client must declare the formats it can upload")
        self.assertTrue(
            offered <= supported,
            f"client offers formats the server cannot decode: {sorted(offered - supported)}",
        )


class ReleaseGateTests(unittest.TestCase):
    """The wording and flow gates product workstream set in docs/MESSAGES.md before this could ship."""

    def setUp(self):
        self.html = read(INDEX)
        self.js = read(APP_JS)
        self.css = read(APP_CSS)
        self.flat = " ".join(self.html.split())

    def test_no_em_dash_anywhere(self):
        for path in (INDEX, APP_JS, APP_CSS, MANIFEST, Path(__file__)):
            with self.subTest(path=path.name):
                self.assertNotIn("\u2014", read(path), "em dash characters are not allowed")

    def test_history_is_read_through_the_read_only_preview_route(self):
        """Revealing history must not write an episode: that is what /preview is for."""
        api = read(REPO_ROOT / "src" / "http_api.py")
        self.assertIn('parts[3] in {"preview", "complete"}', api)
        self.assertIn("careflow.preview_incident", api)
        self.assertIn("/api/incidents/${state.attempt.id}/preview", self.js)
        self.assertIn("previewIncident", self.js)
        # a preview returns no episode, so the client must not expect one
        self.assertIn("renderIncidents(data.scenarios, null)", self.js)

    def test_exactly_one_incident_completion_call_site(self):
        """Two /complete calls would write two episodes for one cry."""
        self.assertEqual(
            1,
            len(re.findall(r"/complete`", self.js)),
            "there must be exactly one completion call site",
        )
        self.assertIn("state.incidentCompleted", self.js)
        self.assertIn("if (!state.attempt || state.incidentCompleted) return;", self.js)
        self.assertIn("state.incidentCompleted = true;", self.js)
        self.assertIn("ui.saveOutcome.disabled = true;", self.js)
        self.assertIn("ALREADY_SAVED", self.js)

    def test_the_reveal_button_says_it_saves_nothing(self):
        self.assertIn("Reading the history saves nothing", self.flat)

    def test_the_save_button_states_that_it_writes_one_incident(self):
        self.assertIn("Save this incident and its outcome", self.flat)
        self.assertIn("Saving writes exactly one incident for this profile", self.flat)

    def test_enrollment_claim_is_a_count_not_a_readiness_claim(self):
        self.assertIn("3 independent enrollment recordings captured", self.js)
        self.assertNotIn("Demo-ready", self.js)
        self.assertNotIn("demo-ready", self.js)
        self.assertNotIn("Demo-ready", self.html)

    def test_match_wording_is_a_comparison_not_an_identification_claim(self):
        self.assertIn('"Matched an enrolled profile"', self.js)
        self.assertNotIn("Identified", self.js)

    def test_no_universal_file_picker_claim(self):
        for phrase in ("works everywhere", "always works", "works on every"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.js.lower())
                self.assertNotIn(phrase, self.html.lower())

    def test_retry_independence_is_credited_to_the_server(self):
        """src/identity.py rejects a byte-identical retry; the client must explain that state."""
        identity_source = read(REPO_ROOT / "src" / "identity.py")
        self.assertIn("retry_audio_identical_to_earlier_capture", identity_source)
        self.assertIn("retry_audio_identical_to_earlier_capture", self.js)

    def test_human_mode_is_an_arbitrary_size_session(self):
        flat = " ".join(self.html.split())
        self.assertIn("Each microphone stop or file selection", flat)
        self.assertIn("New session", self.html)
        self.assertIn("createLiveSession", self.js)
        self.assertIn("submitLiveObservation", self.js)
        self.assertIn("renderLiveParticipants", self.js)
        self.assertIn("liveSession: null", self.js)
        self.assertNotIn("createHumanSession", self.js)
        self.assertNotIn("addNextParticipant", self.js)
        self.assertNotIn("processHumanSessionClip", self.js)
        self.assertNotIn('"DELETE"', self.js)
        self.assertNotIn("two-person", (self.html + self.js).lower())


if __name__ == "__main__":
    unittest.main()
