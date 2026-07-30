# Web app architecture - phone browser as the client

Decision: **mobile web app opened on the presenter's phone.** No iOS build, no TestFlight.
This document exists so that everything built from here on is compatible with that, and so the
three blockers below are solved in advance rather than on the day.

---

## The shape: phone is the client, the Mac is the server

```
  iPhone Safari  ──── HTTPS ────>  local server on the MacBook
  mic + UI                          FastAPI/Flask wrapper
                                          │
                                    the EXISTING verified Python
                                    fingerprint / store / retrieve / diary
```

**Nothing about the verified backend changes.** The web app is a thin HTTP layer plus a UI.
`fingerprint.load_audio()` already decodes through ffmpeg, so it accepts whatever the browser
uploads (WebM/Opus, MP4/AAC) with no changes.

### ⛔ What we must NOT do

**Do not reimplement the fingerprint in JavaScript.** Every measured number - AUC 0.70,
30.5% top-1, the 0.897-0.933 operating window, n=6 - describes the Python implementation. A JS
MFCC would be a different algorithm and would invalidate all of it. Audio goes to the server.

---

## 🔴 Blocker 1 - the phone cannot play the cry AND record it

Round-2 **J4** measured this by accident and it is the single most important consequence for the
demo: capturing on the iPhone's mic while the *same* iPhone played audio produced **-53.7 dB and
no fingerprint**, because **iOS suppresses its own speaker feed** (echo cancellation).

`getUserMedia` makes this worse - browsers apply echo cancellation, noise suppression and
auto-gain by default, all of which actively fight us.

**Consequences, both mandatory:**

1. **The cry must play from a different device than the one recording.** Phone records → cry plays
   from the MacBook speakers or a second phone. Never the same device.
2. **Disable browser audio processing** in the capture constraints, because auto-gain in particular
   will destroy level consistency, and level is the fragile axis (a 3.9 dB drift breaks a match):

```js
navigator.mediaDevices.getUserMedia({
  audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
})
```

Auto-gain control is not a nicety to switch off - it is the exact failure mode J measured.

## 🔴 Blocker 2 - mic access requires HTTPS, and a LAN IP will not do

`getUserMedia` only works in a **secure context**. `http://localhost` is exempt;
**`http://192.168.x.x` is not.** Open the app on your phone over a plain LAN address and iOS
Safari silently refuses microphone access.

Options, in order of reliability for a venue:

| Option | Works offline? | Cost |
|---|---|---|
| **Self-signed cert + trust the profile on the iPhone** | ✅ yes | fiddly once, then reliable - install the cert and enable full trust in Settings |
| **Tailscale** (`*.ts.net` with real certs) | needs its control plane | easy, but a network dependency |
| **cloudflared / ngrok tunnel** | ❌ no | trivial to start, dies with the internet |

**Recommendation: self-signed cert, set up and tested days before.** It is the only option that
survives a dead venue network, which is a standing risk. Do not discover this on the day - 
it is the most likely reason a phone demo fails.

## 🔴 Blocker 3 - the seeded episodes must be re-recorded through the phone

Every existing episode was captured on the **MacBook mic via ffmpeg**. Moving capture to the
iPhone browser changes the microphone, the sample rate, and adds lossy compression - which is
precisely the cross-channel comparison measured at **-0.258**.

**So: re-seed all six priors through the phone web app itself.** `tools/doctor.py` will FAIL on
mixed channels, which is the intended guard. Lossy compression is fine as long as it is
*consistent* - seeding and querying travel the same path, so the codec's effect cancels.

Plan for this in the schedule: it is ~10 minutes of recording that must happen after the web app
works and before anyone is watching, and the database should then be backed up.

---

## API surface (thin - the logic already exists)

| Endpoint | Maps to |
|---|---|
| `POST /api/episode` (multipart audio + `subject_id` + `caregiver_answer`) | `session.finish()` |
| `GET  /api/recall?subject_id=&episode_id=` | `retrieve.find_similar()` + `render.recall_card()` |
| `GET  /api/history?subject_id=` | `store.list_episodes()` + `retrieve.intervention_tally()` |
| `GET  /api/diary?subject_id=` | `diary.render_markdown()` |
| `GET  /api/health` | the `tools/doctor.py` checks, including **level drift** |

`session.record()` is bypassed - the browser captures instead - so `session.finish()` must accept
an uploaded file path. That is product workstream's module; it already takes `audio_path`, so an upload handler
that writes to `config.AUDIO_DIR` and calls `finish()` is sufficient.

**Keep `/api/health` on a screen you can glance at.** It is how you notice level drift before a
match silently fails in front of a judge.

## Making it read as an app, not a web page

- `manifest.json` with `"display": "standalone"` → Add to Home Screen removes all browser chrome
- `apple-mobile-web-app-capable` + `apple-mobile-web-app-status-bar-style` for iOS specifically
- `viewport-fit=cover` and `env(safe-area-inset-*)` so it sits correctly around the notch
- `touch-action: manipulation`, no hover states, ≥44 px touch targets
- one screen, one primary action - a big record button is the whole interface

**Add to Home Screen before presenting.** In standalone mode there is no address bar, which is
the single biggest difference between "a website" and "an app" to an audience.

## Honest constraints to keep on screen

These are measured, not hedges, and showing them is a strength:

- recordings must come from the **same device at a consistent volume** (3.9 dB breaks a match)
- **six prior episodes** before a recall renders - below that it says "not enough to compare yet"
- matches band `weak`, not `strong` - real, and deliberately not inflated

## The MacBook as the server - two blockers that only appear with more than one phone

### 🔴 Cert distribution kills casual multi-phone use

`getUserMedia` needs HTTPS, and a self-signed cert must be **trusted on every device that opens
the app**. On iOS that is: install a configuration profile, then go to a *different* Settings
screen (General → About → Certificate Trust Settings) and enable full trust - roughly six taps
across two locations, behind a security warning.

That is fine to do once on the presenter's phone. It is a non-starter for a stranger walking up.

**Three options, honestly ranked:**

| Option | Multi-phone? | Cost |
|---|---|---|
| **One phone - the presenter's** | no | zero. Visitors interact with *your* phone. |
| Real publicly-trusted cert for a hostname pointed at the LAN IP, with the laptop also serving DNS for it | yes | a domain, a cert issued in advance, dnsmasq on the hotspot. Days early, not on the day. |
| Cert profile on each visitor phone | technically | ~2 min per person plus a scary prompt. Do not. |

**Recommendation: one phone.** It removes cert distribution, removes request concurrency, and
simplifies consent because the presenter is present for every recording. "Visitors interact with
the presenter's phone" is also a *better* demo - it keeps the operator in control of the rig, which
matters because the rig is fragile.

### 🔴 Venue Wi-Fi will probably not let a phone reach the laptop

Most venue networks enable client isolation, so phone→laptop traffic is blocked even with a valid
cert. The robust answer is the laptop running **its own hotspot** with the phones joined to it.

**But that has a consequence people miss:** macOS Internet Sharing cannot share Wi-Fi over Wi-Fi,
so a laptop-hosted hotspot has **no upstream internet**. Everything local still works - but
`gpt-4o-transcribe` does not.

> **Therefore: demoing on your own hotspot REQUIRES `IM_OFFLINE=1` and the local whisper CLI.**
> That path has never been exercised end to end. It moves from "nice fallback" to "the actual
> demo configuration", and needs testing.

Identity, fingerprinting, retrieval and guidance are all local and unaffected. Only the transcript
depends on this, and an empty transcript degrades visibly rather than breaking the loop.

### Server shape

Since this is a long-running service rather than a CLI:

- **Load the encoder once at startup and keep it warm.** Per-request model loading would cost
  seconds and blow the p95 ≤ 5 s target.
- **SQLite in WAL mode** - concurrent readers, serialized writers, correct at this scale.
- **Serialize inference** behind a queue; ECAPA on an M2 Pro is fast, but concurrent requests
  should not contend for CPU mid-demo.
- **One process, no autoreload** in demo mode - a reload drops the warm model.
- **Back up `data/episodes.db` before presenting.** The database *is* the demo.

## Build order

1. HTTPS + mic access working on the phone (**blocker 2 - do this first, it can sink everything**)
2. Record → upload → `session.finish` → episode saved
3. Recall card rendering the real `band` and `outcome_src`
4. Re-seed six live episodes through the phone; back up the database
5. Visual design pass
6. "Coming soon" disabled surfaces

Steps 1-2 are the risk. Everything after is presentation.
