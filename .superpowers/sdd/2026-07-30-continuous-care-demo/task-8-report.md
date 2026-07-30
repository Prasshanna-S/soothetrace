# Task 8 accelerated phone care client report

## Status

GREEN for an experimental phone test build.

The Listen page now uses the live minimum care-session HTTP surface. History and Baby remain
clearly labeled as limited in this test build because their detail routes are not available yet.
This is not a presentation-release claim.

## Implemented

- Imported Claude's daylight nursery layout, WebGL orb, manifest, and local PNG artwork.
- Excluded `capture.html`.
- Loaded active infant profiles from `GET /api/profiles`.
- Defaulted to `Demo Baby` when that named profile exists.
- Added an obvious baby selector and disabled it during an open session.
- Gated Start on `health.care.ready` and a selected infant profile.
- Requested audio-only microphone access, read applied track settings, and created the server
  care session before showing a live state.
- Kept one MediaStream for each uninterrupted live stretch.
- Produced complete independent MediaRecorder files every 6 seconds.
- Added one active upload plus at most one completed waiting file.
- Kept the same bytes and sequence across network retries.
- Advanced the client sequence only from a server-accepted `last_sequence`.
- Reconciled an out-of-order response through `GET /api/care-sessions/{id}`.
- Made sequence conflicts terminal instead of silently changing bytes or sequence.
- Drained the current file, active upload, and waiting file before server Pause or Stop.
- Reacquired the microphone before server Resume and released it if Resume failed.
- Cleared the LIVE state immediately on track mute or end.
- Rendered cry presence only from server fields.
- Kept `no_cry_detected` and `cry_uncertain` free of guidance and incident output.
- Distinguished uneven and quiet invalid captures from actual decoder failures in listener copy.
- Latched only the first grounded server decision.
- Presented a server-owned infant detection before revealing a decision returned in the same
  chunk response, using a nonblocking 1200 ms presentation delay.
- Added a backend evidence gate for `Demo Baby`: the first grounded selected infant-cry segment
  becomes a private candidate. Three additional selected infant-cry segments must confirm the
  same grounded recommendation before the fourth consistent segment can return a decision.
- Rendered the backend-owned progress copy for evidence 1 through 4 without estimating cry
  presence or decision eligibility in the browser.
- Rendered the server recommendation and evidence without rewriting or fallback advice.
- Restricted representative audio playback to profile-scoped incident URLs.
- Used real disabled controls to block playback while the microphone is live.
- Connected structured Save and Discard to the server.
- Added true radio semantics and arrow-key behavior to the settled choice.
- Expanded desktop to a real wide layout while keeping phone portrait and landscape layouts.
- Changed WebGL to premultiplied transparent output and clipped the canvas itself so iOS cannot
  composite the orb as a white rectangle.
- Primed Web Audio during the trusted Start and Resume clicks without blocking session startup,
  reused the context when the microphone arrived, and retained the connected source until stop.
- Mapped microphone RMS through the fixed-rig calibrated curve with separate attack and release
  smoothing. This changes orb energy only and never changes cry status, color, or guidance.
- Added calm internal shader rotation for listening and detected states. Reduced motion disables
  the turn, and the canvas itself never spins.
- Simplified the profile chip, aligned the live timer with it, and enlarged the orb in short
  landscape without adding Pro Max scrolling.
- Kept a latched result visible after Stop as a full-width horizontal summary, followed by the
  caregiver form, and cleared all decision presentation before the next session.
- Reworded the outcome question to ask whether the action helped the baby calm down, while keeping
  the existing true, false, and null payload values.
- Removed the simulated default path, hard-coded baby, client-authored safety advice, narrow
  desktop column, low-contrast secondary text, and undersized controls.

## TDD evidence

Initial focused static tests failed against the previous client on the missing care pages,
portrait-only manifest, missing route calls, and narrow desktop layout.

The browser acceptance later caught an infinite scale animation that made Start never stable.
Removing that motion made the exact test pass.

The iPhone orb report produced a focused WebKit compositing test. It failed on unpremultiplied
alpha, then passed after the fragment output, context, and canvas clipping were corrected.

The iPhone phase-label report produced a browser regression for back-to-back state changes. It
failed on delayed text timers, then passed after status replacement became synchronous.

The Pro Max landscape regression exposed two separate overflow causes: the desktop breakpoint
activating on a short phone viewport, and the suggestion entrance transform extending below the
visible page. The desktop breakpoint now requires sufficient height, and the transform animation
is disabled only for short landscape.

The live orb regression first measured the quiet and cry states as the same exported energy. The
calibrated RMS curve then separated the fixed-rig floor from a loud cry while retaining server-only
classification. A second regression exposed the old activation order as microphone first, context
second. Web Audio is now primed before the microphone permission await.

The accelerated segment contract failed while the client still rotated at 12 seconds. The
validated 6-second constant made that focused test pass.

The internal motion and caregiver-copy contracts failed before the shader and wording changes.
The first sequential browser run also showed that Stop hid the latched result. The final browser
run completed three start, latch, stop, and discard cycles with a fresh result each time.

The same-response sequencing regression initially showed the grounded card immediately, with no
detected orb state or reveal timer. The corrected path first renders the server detection, advances
the accepted upload immediately, then reveals the exact first server decision after 1200 ms.

The evidence-gate regression initially latched the first grounded `Demo Baby` chunk. The corrected
backend holds that candidate, exposes confirmation progress without its hidden content, and permits
the fourth consistent grounded chunk to latch. A changed recommendation restarts confirmation at
zero, while normal infant profiles retain their calibrated first-grounded-result behavior.

## Verification

```text
node --check web/app.js
PASS

python -m unittest tests.test_web_client -v
15 tests passed

python -m unittest tests.test_care_sessions -v
42 tests passed

node tests/test_live_session_browser.mjs
PASS
```

The browser test verifies:

- default `Demo Baby` selection and switching to `Learning Baby`;
- selected profile sent during session creation;
- same-document navigation with one retained MediaStream;
- failed-upload retry with the same bytes and sequence 1;
- Stop only after upload drain;
- exact server guidance text;
- structured outcome Save;
- no suggestion or incident output for `no_cry_detected`;
- synchronous replacement of the visible analysis phase label;
- reason-aware listener copy for uneven, quiet, and unreadable segments;
- detected status and orb state before a same-response grounded decision;
- one held candidate and three visible confirmations with no early decision, followed by
  fourth-consistent-segment eligibility;
- one delayed reveal, immutable first decision, and reset cleanup of the pending timer;
- quiet and cry microphone levels reaching distinct exported orb energy bands;
- Web Audio priming before the first microphone permission await without blocking Start;
- no CSP violation on the production policy;
- no horizontal overflow at 430 by 932, 932 by 430, and 1440 by 900;
- no vertical scroll in the plain or latched 932 by 430 Pro Max landscape view with safe areas;
- an enlarged short-landscape orb and a timer centered with the active profile;
- a full-width post-Stop result and unclipped follow-up form;
- three sequential sessions with no stale decision or recommendation;
- a desktop shell wider than a phone column.

`git diff --check`, capture exclusion, and the web forbidden-dash scan passed.

## Remaining caveats

- The browser acceptance uses a deterministic fake microphone and fake HTTP responses. A physical
  iPhone run against the temporary HTTPS server is still required.
- History, incident detail, Baby detail, and care-event routes are not implemented in this slice.
- The PNG files are checked in under `web/img`, but the current HTTP server serves only the four
  top-level web files. The client falls back to embedded owner artwork until `/img` receives an
  explicit static allowlist route.
- Full Python discovery remains deferred under the owner-approved accelerated test-build mode.
  The complete 42-test care-session module and the 15-test web-client module passed.
- Five consecutive fixed-rig baby query passes are still required before calling the recorded
  choreography presentation-safe.
