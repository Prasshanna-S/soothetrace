# Demo Operator Runbook

This runbook is for the current phone-fronted, laptop-backed proof of concept. For architecture,
evidence limits, and the complete verification command set, return to the
[`README`](../README.md).

The full phone route has been exercised on a Mac laptop and an iPhone over trusted local HTTPS.
It is proof-of-concept evidence for that setup, not a guarantee across every macOS version, iOS
version, router, or venue network.

## One-time setup from a clean Mac

The Mac needs Command Line Tools, Homebrew, internet access during provisioning, and enough disk
space for the environment, public corpus, model checkpoint, managed audio, and optional browser
automation. The phone and Mac must be on the same local network, and that network must permit them
to reach each other.

```bash
xcode-select -p
brew install uv ffmpeg openssl@3 node
git clone https://github.com/Prasshanna-S/interaction-memory.git
cd interaction-memory
uv venv .venv --python 3.12
. .venv/bin/activate
uv pip install -r requirements.txt
git clone --depth 1 \
  https://github.com/gveres/donateacry-corpus.git \
  experiments/donateacry-corpus
.venv/bin/python tools/build_baseline.py
```

If `xcode-select -p` reports missing tools, run `xcode-select --install`, complete the macOS
installer, and repeat the checks. The baseline command must finish with `population baseline
saved`. Do not install `librosa`.

The optional browser interaction test also needs:

```bash
npm install --no-save --package-lock=false playwright
npx playwright install chromium
```

## Preflight evaluators and tests

Run the current incremental evaluator in every supported release mode:

```bash
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode one-person
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode staged
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode difficult
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json --mode probes
```

Run the combined gate without overwriting the checked-in evidence:

```bash
.venv/bin/python tools/live_session_eval.py \
  demo_assets/human_audio/manifest.json \
  --mode all \
  --output /tmp/cry-memory-live-session-results.json
```

`--mode alternating` is an alias for `difficult`. Run the earlier named-profile evaluator in all
three supported modes:

```bash
.venv/bin/python tools/human_session_eval.py \
  demo_assets/human_audio/manifest.json --mode demo
.venv/bin/python tools/human_session_eval.py \
  demo_assets/human_audio/manifest.json --mode loo
.venv/bin/python tools/human_session_eval.py \
  demo_assets/human_audio/manifest.json --mode discovery
```

Run the focused integration suites, then the entire Python suite:

```bash
.venv/bin/python -m unittest \
  tests.test_mobile_capture_spike \
  tests.test_product_real_audio_api.RealAudioProductApiTests.test_incremental_live_session \
  tests.test_live_session_http \
  tests.test_live_identity_sessions -v

.venv/bin/python -m unittest discover -s tests -v
```

Run the browser interaction test and JavaScript syntax check after the Playwright setup above:

```bash
node tests/test_live_session_browser.mjs
node --check web/app.js
```

These fixtures and evaluator outputs are demonstration evidence. They do not estimate population
accuracy or establish infant identity performance.

## Recommended presentation order

1. Start the laptop server and let both encoders warm.
2. Open the page on the iPhone and check that the header says `Local server ready`.
3. Show the saved-file baby flow.
4. Show the matched baby's prior caregiver history and evidence playback.
5. Switch to Human cry imitation.
6. Start a clean human session.
7. Let the automatic session register each person in turn.
8. Pass the phone around and run blind turns.

## Before the audience arrives

```text
[ ] Laptop is connected to power.
[ ] ffmpeg is available.
[ ] Python 3.12 virtual environment is installed.
[ ] Dependencies and CryCeleb model are already downloaded.
[ ] All automated tests pass.
[ ] Server starts without a model or database error.
[ ] iPhone trusts the local certificate.
[ ] iPhone and laptop are on the same network.
[ ] iPhone can open the HTTPS page.
[ ] Microphone permission is allowed for the page.
[ ] Included baby files are available in the iPhone Files app.
[ ] The three-profile human file demo has been reproduced.
[ ] A clean backup of data/episodes.db exists.
```

## Find the current LAN IP

On the tested Wi-Fi configuration:

```bash
ifconfig en0 | awk '/inet / {print $2}'
```

Use the non-loopback address, such as `10.21.6.4`. If `en0` has no address, inspect the `inet`
lines from `ifconfig` or find the active interface under System Settings > Network. Do not use
`127.0.0.1`. Recheck this address for every network and every rehearsal.

## Generate and trust the iPhone certificate

Replace `10.21.6.4` in this section with the current LAN address. The certificate script needs
OpenSSL 3, so keep the package-manager OpenSSL first on `PATH`:

```bash
PATH="$(brew --prefix openssl@3)/bin:$PATH" \
  ./spikes/mobile_capture/make_cert.sh 10.21.6.4
```

This writes a temporary 30-day local root and an IP-addressed server certificate under
`data/audio/mobile-capture-spike/certs/`. Never share `rootCA.key` or `server.key`.

Serve the installable public certificate profile:

```bash
.venv/bin/python spikes/mobile_capture/bootstrap.py \
  --host 0.0.0.0 \
  --port 8080 \
  --cert data/audio/mobile-capture-spike/certs/rootCA.pem
```

On the iPhone, open this exact URL in Safari:

```text
http://10.21.6.4:8080/Interaction-Memory-Spike-CA-corrected.mobileconfig
```

Then:

1. Allow the configuration profile to download.
2. Open Settings. Select **Profile Downloaded**, or go to **General > VPN & Device Management**,
   select **Interaction Memory Local Spike CA**, and install it. Enter the device passcode and
   acknowledge the certificate warning.
3. Go to **General > About > Certificate Trust Settings**.
4. Enable full trust for **Interaction Memory Local Spike CA** and confirm.
5. Stop the bootstrap server with Control-C.

Installing the profile and enabling trust are separate actions. If the LAN IP changes, regenerate
the certificate and repeat both actions.

## Start and warm the phone server

```bash
.venv/bin/python -m src.http_api \
  --host 0.0.0.0 \
  --port 8443 \
  --data-root data/audio \
  --static-root web \
  --db data/episodes.db \
  --cert data/audio/mobile-capture-spike/certs/server.pem \
  --key data/audio/mobile-capture-spike/certs/server.key
```

The service warms its required acoustic encoders before listening. The first run downloads the
human checkpoint into `models/`, so it requires internet and can take longer. Do not open the demo
until the process prints:

```text
Cry Memory ready at https://0.0.0.0:8443 with encoders {'ecapa-cryceleb-v1': True, 'mfcc87-v1': True}
```

Dictionary order is not significant. A `False` value means the corresponding encoder is not ready.
Resolve that before presenting.

Open `https://10.21.6.4:8443` on the iPhone. There should be no certificate warning. Allow
microphone access and confirm the header says `Local server ready`. A warning usually means the
phone does not fully trust the root, the URL uses an IP that is absent from the certificate, or the
network is intercepting local traffic.

For a laptop-only rehearsal that does not need phone microphone access, use:

```bash
.venv/bin/python -m src.http_api \
  --http \
  --host 127.0.0.1 \
  --port 8000 \
  --data-root data/audio \
  --static-root web \
  --db data/episodes.db
```

Open `http://127.0.0.1:8000` only on the Mac. The server rejects plain HTTP on a non-loopback host.

## Baby flow with only two devices

Use the phone file picker for saved baby recordings. This is the most reliable path and does not
need another playback device.

1. Open Baby cry.
2. Create or select at least two baby profiles.
3. Add three distinct enrollments to each profile.
4. Select a different file and run a blind query.
5. If confirmed, reveal recorded history.
6. Show caregiver provenance and play one supporting incident.
7. Save the current outcome once.

If an acoustic microphone demonstration is required, play the baby clip from the laptop and record
it on the iPhone. Never play and record on the same iPhone.

## Human participation flow

1. Open Human cry imitation.
2. Press Create new session.
3. Ask the first person to cry once. The session creates Person A.
4. Ask the next person to cry. If the app says Possible new participant, ask that same person for
   one fresh cry. Person B is created only if both clips remain outside the current profiles and
   are acoustically consistent with each other.
5. Repeat for Person C and any later participants.
6. Continue passing the phone around. Every later recording is processed automatically.

Read the card exactly:

- `Matched [name]` is a confirmed local comparison.
- `Possible new participant` shows the closest existing profile as an unconfirmed direction and
  requires one fresh cry before creating a profile.
- `New participant registered` means the two-cry outlier and pair-consistency rule passed.
- `Leaning toward [name], not confirmed` is a visible direction.
- `Closest existing profile [name], not confirmed` is direction after an unresolved attempt.

Do not describe a leaning result as a confirmed identity.

## Channel rules

- Keep enrollment and query capture paths as similar as practical.
- Keep phone orientation and distance stable.
- For acoustic replay, keep the speaker volume stable.
- Do not enroll WhatsApp audio for one person and direct microphone audio for another, then call
  the result identity. That can measure the channel instead of the person.
- If files came from different channels, replay all files through the same speaker-to-phone rig
  before drawing a person-level conclusion.

## If a query is uncertain

1. Use the one offered retry.
2. Make a genuinely new recording.
3. Keep the same participant, distance, and phone position.
4. Do not submit the same file again. The server rejects byte-identical retry audio.
5. If the second recording remains unresolved or disagrees, leave it unresolved.

## If the room is loud

- Move the phone closer to the source.
- Ask the room for five quiet seconds.
- Keep speech from bystanders out of the capture.
- Use a saved file instead of acoustic replay when appropriate.
- Do not lower identity gates during the presentation.

## If the network is unreliable

The phone only needs a working local connection to the laptop. Upstream internet is not required
for identity after dependencies and model files have been provisioned.

If phone-to-laptop traffic is blocked by venue Wi-Fi:

1. use a private hotspot or permitted local network;
2. verify the laptop IP and certificate coverage;
3. reload the page;
4. check the `Local server ready` header before continuing.

## Fast fallback

The included human cohort can prove the full multi-person backend without live acoustic risk:

```bash
.venv/bin/python tools/human_session_eval.py \
  demo_assets/human_audio/manifest.json \
  --mode demo
```

Expected directions:

```text
blind-query-01.wav       -> Matched Prasshanna
blind-query-02.wav       -> Leaning Prasshanna
second-person-03.m4a     -> Leaning Second person
```

## Final five-minute check

```text
[ ] Page loads on the phone.
[ ] Health header says Local server ready.
[ ] One saved audio file can be selected.
[ ] One microphone recording can be stopped and selected.
[ ] Profile list loads.
[ ] A human blind query shows Matched, Leaning, or Unresolved.
[ ] Clean human-session reset leaves baby profiles intact.
[ ] Baby history preview writes no incident.
[ ] Outcome save writes exactly one incident.
[ ] Supporting audio plays only while the microphone is stopped.
```

Freeze code and thresholds after this check. During the presentation, change the capture setup or
input method before changing the identity policy.

## After the demonstration

1. Stop the HTTPS server with Control-C.
2. On the iPhone, go to **Settings > General > VPN & Device Management**, select
   **Interaction Memory Local Spike CA**, and remove the profile.
3. Keep the private certificate keys only on the Mac. Move the generated certificate directory to
   Trash when it is no longer needed.

Removing the profile also removes the temporary trust decision from that iPhone.
