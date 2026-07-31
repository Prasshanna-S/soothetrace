# SootheTrace orb presentation clip

This folder contains a 24 second, silent animation rendered from the same
WebGL orb used by the browser app.

## Ready to use

- `soothetrace-orb-status-alpha.mov`: 1080 by 1080 ProRes 4444 master with a
  transparent background. Use this when the presentation software supports
  alpha video.
- `soothetrace-orb-status-clean.mp4`: 1920 by 1080 H.264 version composited on
  the app background color, `#F1F2F8`. Use this for the most reliable playback
  in PowerPoint, browsers, and video editors.

Both clips are 24 seconds at 30 frames per second. They have no audio.

The animation moves through:

1. Listening
2. Sound detected
3. Checking infant cry
4. Infant cry detected
5. Comparing with this baby's memory
6. Matching time and prior context
7. Confirming against previous moments
8. Suggestion ready

## Rebuild

Run the dependency check:

```bash
node tools/render_orb_presentation.mjs --self-check
```

Render both outputs:

```bash
node tools/render_orb_presentation.mjs
```

Verify codecs, dimensions, duration, and real alpha variation:

```bash
node tools/render_orb_presentation.mjs --verify
```

The renderer loads the existing `web/index.html`, `web/app.css`, and
`web/app.js`. It hides the surrounding interface, drives the live orb states,
advances a deterministic animation clock, and captures transparent PNG frames
with Playwright. FFmpeg encodes those frames into the two delivery formats.
