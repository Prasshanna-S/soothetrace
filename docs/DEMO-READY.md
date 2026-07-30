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
brew install uv ffmpeg node
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

## One-time setup from a clean Windows computer

Use 64-bit Windows 10 version 1809 or later, or Windows 11. The native scripts require WinGet,
ordinary Windows PowerShell 5.1 or PowerShell 7, internet during provisioning, and enough disk space
for the Python environment, public corpus, model checkpoint, managed audio, and optional browser
automation.

```powershell
winget install --id Git.Git --exact --source winget
```

Close every PowerShell window after Git finishes installing. Open a new PowerShell window, then
clone and provision the repository:

```powershell
git clone https://github.com/Prasshanna-S/interaction-memory.git
Set-Location ".\interaction-memory"
.\scripts\setup_windows.ps1 -InstallTools
```

If setup installs Python, FFmpeg, or Node, close every PowerShell window again. Open a new one,
return to the repository, and run `.\scripts\setup_windows.ps1` once more. The setup script requires
Python 3.12, checks `ffmpeg` and `ffprobe`, installs dependencies without virtual-environment
activation, clones the corpus at its required location, and builds the population baseline.

On Windows 11, install the optional browser interaction dependency with:

```powershell
.\scripts\setup_windows.ps1 -InstallTools -InstallPlaywright
```

Keep `-InstallTools` so setup can install Node if it is absent. If Node is installed, reopen
PowerShell and rerun the command with `-InstallPlaywright`. Current Playwright releases do not list
Windows 10 as a supported host. This does not prevent the core desktop or phone server from running.

If execution policy blocks the script:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -InstallTools
```

### Windows desktop rehearsal

```powershell
.\scripts\run_windows.ps1 -Mode Desktop
```

Wait for both encoder values to be `True`. In a second PowerShell window:

```powershell
Set-Location ".\interaction-memory"
.\scripts\run_windows.ps1 -Mode Health
Start-Process "http://127.0.0.1:8000"
```

Rehearse the browser microphone as the primary input. Also rehearse the audio-file upload so it is
ready as the Windows fallback if microphone permission, device selection, or room acoustics fail.

### Windows phone HTTPS

Find and inspect the active IPv4 LAN address:

```powershell
$LanIp = (
    Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
    Select-Object -First 1
).IPv4Address.IPAddress
$LanIp
```

Do not use `127.0.0.1`. The phone and computer must be on the same trusted network. Generate the
temporary certificate and serve its installable public profile:

```powershell
.\scripts\run_windows.ps1 -Mode Bootstrap -LanIp $LanIp
```

The launcher uses the portable certificate command
`.\.venv\Scripts\python.exe .\spikes\mobile_capture\make_cert.py $LanIp`. If Windows prompts for
firewall access, allow Python only on Private networks. Open the exact HTTP profile URL printed by
the launcher on the iPhone.

On the iPhone:

1. Allow the configuration profile to download.
2. Open **Settings > General > VPN & Device Management** and install
   **Interaction Memory Local Spike CA**.
3. Open **Settings > General > About > Certificate Trust Settings**.
4. Enable full trust for **Interaction Memory Local Spike CA** and confirm.
5. Stop the bootstrap server with Control-C.

Start the phone product server:

```powershell
.\scripts\run_windows.ps1 -Mode Phone -LanIp $LanIp
```

Wait for both encoder values to be `True`, then open `https://WINDOWS-LAN-IP:8443` on the iPhone.
The page must load without a certificate warning before microphone permission is requested.

### Windows rehearsal troubleshooting

- If a tool is missing after WinGet succeeds, reopen PowerShell to refresh `PATH`, return to the
  repository, and rerun setup.
- If execution policy blocks a launcher, use the one-process bypass above.
- If setup detects the wrong interpreter, remove only this checkout's `.venv` directory and rerun
  setup. Do not activate or reuse a different environment.
- If the corpus clone is incomplete, remove or rename only
  `experiments\donateacry-corpus`, then rerun setup.
- If the phone cannot connect, confirm the Windows network is Private, allow Python on Private
  networks, and check that the Wi-Fi does not isolate clients.
- If the phone reports a certificate warning, verify profile installation and full trust. Regenerate
  and reinstall it after any LAN IP change.
- A checkout path containing spaces is supported. Invoke a quoted script path with the call
  operator, for example
  `& "C:\Demo Files\interaction-memory\scripts\run_windows.ps1" -Mode Desktop`.

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

On Windows, use `.venv\Scripts\python.exe`, replace `/tmp` with `$env:TEMP`, and use the complete
PowerShell verification block in the [`README`](../README.md#verification).

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
[ ] The three included baby-audio folders are available on the playback device.
[ ] The three-profile human file demo has been reproduced.
[ ] A clean backup of data/episodes.db exists.
```

## Find the current LAN IP on macOS

On the tested Wi-Fi configuration:

```bash
ifconfig en0 | awk '/inet / {print $2}'
```

Use the non-loopback address, such as `10.21.6.4`. If `en0` has no address, inspect the `inet`
lines from `ifconfig` or find the active interface under System Settings > Network. Do not use
`127.0.0.1`. Recheck this address for every network and every rehearsal.

## Generate and trust the iPhone certificate on macOS

Replace `10.21.6.4` in this section with the current LAN address. Generate the certificate with
the same portable Python entry point used on Windows:

```bash
.venv/bin/python spikes/mobile_capture/make_cert.py 10.21.6.4
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

## Start and warm the phone server on macOS

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

The repository includes three public rehearsal groups under
[`demo_assets/baby_audio`](../demo_assets/baby_audio/README.md). Each folder has three enrollment
clips, one held-out query, one retry, and one extra stress-test clip.

The current infant thresholds were calibrated on live room replay. Use the laptop browser and play
the files from the phone into the laptop microphone, or use the phone browser and play the files
from the laptop. Never play and record on the same device.

1. Open Baby cry.
2. Create profiles named Baby 1, Baby 2, and Baby 3.
3. Fix the speaker volume, room position, device orientation, microphone, and distance.
4. For each folder, replay files `01`, `02`, and `03` through that unchanged path and enroll the
   three browser recordings into the matching profile.
5. Seed clearly synthetic care history for the three demo profiles:

   ```bash
   .venv/bin/python scripts/seed_demo_memory.py
   ```

   On Windows:

   ```powershell
   & .\.venv\Scripts\python.exe .\scripts\seed_demo_memory.py
   ```

6. Replay file `04` through the same path and run a blind query.
7. If the result asks for one retry, use that group's `05` file through the same fixed path.
8. Keep file `06` unused for an additional stress test.
9. If confirmed, reveal that profile's synthetic demo history, provenance label, and one
   supporting incident.
10. Save the current real outcome once.

Do not enroll one profile through file upload and another through microphone capture. The raw
8 kHz fixtures are useful ingest inputs, but direct-upload identity is not the calibrated
demonstration. Each Baby 1, Baby 2, and Baby 3 folder has its own source app-install UUID, but those
UUIDs are not verified infant identity labels. Never describe this fixture set as independent
accuracy evidence. The seeded interventions and outcomes are synthetic presentation data, not
evidence of real caregiver efficacy.

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
