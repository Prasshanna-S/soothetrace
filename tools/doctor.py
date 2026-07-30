"""Preflight check. Run this before a demo, and before trusting any test result.

Every check here exists because something actually went wrong once. It is not a generic
health check - it is a list of this project's real failure modes, each of which is silent:

  * Python 3.14 has no SciPy on this machine (the only failure product workstream hit in round 1)
  * no population baseline -> retrieval correctly returns nothing, which looks like a bug
  * mixed corpus + live episodes -> cross-channel matching measured at -0.258 vs 0.909
  * fingerprint DIM != 87 -> the measured results in FINDINGS.md no longer describe the code

Usage:  python tools/doctor.py [subject_id ...]
Exit 0 = ready. Exit 1 = at least one FAIL.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

FAILS = 0
WARNS = 0


def _matching_torch_versions(torch_version: str, audio_version: str) -> bool:
    torch_release, _, torch_build = torch_version.partition("+")
    audio_release, _, audio_build = audio_version.partition("+")
    if torch_release != audio_release:
        return False
    if torch_build and audio_build and torch_build != audio_build:
        return False
    return True


def _audio_devices_from_ffmpeg(system: str, output: str) -> list[str]:
    if system == "Windows":
        return [
            match.group(1)
            for line in output.splitlines()
            if (match := re.search(r'"([^"]+)"\s+\(audio\)', line))
        ]
    if system == "Darwin":
        devices = []
        in_audio = False
        for raw in output.splitlines():
            line = re.sub(r"^\[AVFoundation indev @ [^\]]*\]\s*", "", raw).strip()
            if line.lower().startswith("avfoundation audio devices"):
                in_audio = True
                continue
            if line.lower().startswith("avfoundation video devices"):
                in_audio = False
                continue
            match = re.match(r"^\[(\d+)\]\s+(.*)$", line)
            if in_audio and match:
                devices.append(match.group(2))
        return devices
    return []


def ok(msg):
    print(f"  \033[32m✓\033[0m {msg}")


def warn(msg):
    global WARNS
    WARNS += 1
    print(f"  \033[33m!\033[0m {msg}")


def fail(msg):
    global FAILS
    FAILS += 1
    print(f"  \033[31m✗\033[0m {msg}")


def check_python():
    print("\nPython")
    v = sys.version_info
    ok(f"operating system: {platform.system()} {platform.release()}")
    if v[:2] == (3, 12):
        ok(f"{v.major}.{v.minor}.{v.micro}")
    elif v[:2] >= (3, 13):
        warn(f"{v.major}.{v.minor} - the system python here is 3.14 and has NO SciPy. "
             f"Use: uv venv .venv --python 3.12")
    else:
        warn(f"{v.major}.{v.minor} - untested; 3.12 is the supported version")


def check_deps():
    print("\nDependencies")
    for mod in ("numpy", "scipy"):
        try:
            m = __import__(mod)
            ok(f"{mod} {getattr(m, '__version__', '?')}")
        except ImportError:
            fail(f"{mod} missing - the acoustic path cannot run")
    try:
        __import__("librosa")
        warn("librosa is installed - it is deliberately NOT a dependency "
             "(numba/llvmlite will not build on py3.12/macOS ARM). Harmless, but unexpected.")
    except ImportError:
        ok("librosa absent (correct - numpy/scipy only)")
    try:
        import torch
        import torchaudio

        if _matching_torch_versions(torch.__version__, torchaudio.__version__):
            ok(
                "matched torch / torchaudio "
                f"{torch.__version__} / {torchaudio.__version__}"
            )
        else:
            fail(
                "torch and torchaudio binary versions do not match: "
                f"{torch.__version__} / {torchaudio.__version__}"
            )
    except (ImportError, OSError) as exc:
        fail(f"torch / torchaudio unavailable: {exc}")
    try:
        import speechbrain

        ok(f"speechbrain {getattr(speechbrain, '__version__', '?')}")
    except (ImportError, OSError) as exc:
        fail(f"speechbrain unavailable: {exc}")
    if shutil.which("ffmpeg"):
        ok("ffmpeg on PATH")
    else:
        fail("ffmpeg NOT on PATH - all audio decoding goes through it, nothing will work")
    if shutil.which("whisper"):
        ok("whisper CLI present (offline transcription fallback available)")
    else:
        warn("whisper CLI absent - config.OFFLINE has no local fallback")


def check_modules():
    print("\nModules")
    try:
        import config, fingerprint, retrieve, store  # noqa: F401
        ok("config / fingerprint / retrieve / store import")
    except Exception as exc:                                  # noqa: BLE001
        fail(f"import failed: {exc}")
        return None
    import fingerprint as fp
    if fp.DIM == 87:
        ok("fingerprint.DIM == 87 (matches the measured results in FINDINGS.md)")
    else:
        fail(f"fingerprint.DIM == {fp.DIM}, expected 87 - FINDINGS.md no longer "
             f"describes this code")
    try:
        import diary, session, speech  # noqa: F401
        ok("diary / session / speech import")
    except Exception as exc:                                  # noqa: BLE001
        warn(f"speech-path import failed (fine if you are offline-only): {exc}")
    return True


def check_models():
    print("\nIdentity models")
    import encoders
    import identity

    required = sorted(set(identity.ENCODER_FOR_KIND.values()))
    warmed = encoders.warm(required)
    for name in required:
        if warmed.get(name):
            ok(f"{name} loaded")
        else:
            fail(
                f"{name} failed to load - identity requests using this encoder "
                "will be rejected"
            )


def check_storage_and_baseline(subjects):
    print("\nStorage & baseline")
    import config
    import retrieve
    import store

    store.init_db()
    if os.path.exists(config.DB_PATH):
        ok(f"database at {os.path.relpath(config.DB_PATH)}")
    else:
        fail(f"no database at {config.DB_PATH}")

    pop = store.get_baseline(config.POPULATION_KEY)
    if pop and pop.get("n", 0) >= 100:
        ok(f"population baseline present (n={pop['n']})")
    elif pop:
        warn(f"population baseline is thin (n={pop['n']}) - built from >=100 recordings is "
             f"the validated setup; run tools/build_baseline.py")
    else:
        fail("NO population baseline - find_similar() will correctly return [] for "
             "everything. Run tools/build_baseline.py")

    if not subjects:
        return
    print("\nSubjects")
    for s in subjects:
        eps = store.list_episodes(s)
        if not eps:
            warn(f"{s}: no episodes")
            continue
        usable = retrieve.episode_count(s)
        need = retrieve.MIN_EPISODES_FOR_MATCH
        line = f"{s}: {len(eps)} episodes, {usable} usable"
        if usable > need:
            ok(f"{line} (enough for recall; needs > {need} priors)")
        else:
            warn(f"{line} - NOT enough for a recall to render (needs > {need} priors); "
                 f"the demo will show 'not enough to compare yet'")

        # the failure this project's demo is most likely to hit
        audio_root = os.path.abspath(config.AUDIO_DIR)
        kinds = {("live" if (ep.get("audio_path") or "").startswith(audio_root) else "other")
                 for ep in eps if ep.get("audio_path")}
        if len(kinds) > 1:
            fail(f"{s}: MIXED CHANNELS (corpus + live). Cross-channel matching measured at "
                 f"-0.258 vs 0.909 same-channel. Re-seed live-only: "
                 f"tools/seed_live.py {s} --reset")
        elif kinds == {"live"}:
            ok(f"{s}: all episodes captured live (same channel)")

        seeded = sum(1 for ep in eps if ep.get("outcome_src") == "seed")
        if seeded:
            warn(f"{s}: {seeded} episode(s) carry outcome_src='seed' - synthetic. Never "
                 f"present these as a real result (LIABILITY.md §7)")

        unlabelled = sum(1 for ep in eps if ep.get("worked") is None)
        if unlabelled == len(eps):
            warn(f"{s}: no episode has an outcome - the recall card will have nothing to say")


def check_config():
    print("\nConfig")
    import config
    if config.OFFLINE:
        if shutil.which("whisper"):
            ok("OFFLINE=True and whisper present - no audio leaves this machine")
        else:
            fail("OFFLINE=True but no whisper CLI - transcription will silently produce "
                 "empty transcripts")
    else:
        ok("OFFLINE=False (transcription uses the API)")
        key = os.environ.get("OPENAI_API_KEY")
        if not key and os.path.isfile(config.OPENAI_ENV_PATH):
            ok(f"credentials file present at {config.OPENAI_ENV_PATH}")
        elif key:
            ok("OPENAI_API_KEY set in the environment")
        else:
            fail(f"no OPENAI_API_KEY and no {config.OPENAI_ENV_PATH} - transcription "
                 f"will return empty strings")


def check_audio_device():
    """Which microphone will session.record actually use?

    This matters more than it looks. Round 1 measured cross-channel matching at -0.258 vs
    0.909 same-channel, so the capture device must be IDENTICAL between seeding and querying.
    Browser capture is the primary demo path. The CLI also supports AVFoundation on macOS,
    DirectShow on Windows, and ALSA on Linux.
    """
    print("\nAudio input")
    system = platform.system()
    if system == "Darwin":
        command = [
            "ffmpeg",
            "-hide_banner",
            "-f",
            "avfoundation",
            "-list_devices",
            "true",
            "-i",
            "",
        ]
    elif system == "Windows":
        command = [
            "ffmpeg",
            "-hide_banner",
            "-list_devices",
            "true",
            "-f",
            "dshow",
            "-i",
            "dummy",
        ]
    elif system == "Linux":
        selected = os.environ.get("IM_AUDIO_DEVICE", "default")
        ok(f"CLI recording will use ALSA device {selected!r}")
        ok("browser microphone and upload remain available")
        return
    else:
        warn(f"CLI microphone enumeration is unsupported on {system or 'this system'}")
        ok("browser microphone and upload remain available")
        return

    try:
        p = subprocess.run(command, capture_output=True, timeout=15)
        text = (p.stderr or b"").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        warn("could not enumerate audio devices")
        return

    audio = _audio_devices_from_ffmpeg(system, text)
    if not audio:
        warn("no audio input devices found - check microphone privacy settings")
        return

    ok(f"{len(audio)} audio input device(s):")
    if system == "Windows":
        selected = os.environ.get("IM_AUDIO_DEVICE")
        for name in audio:
            marker = "  <-- CLI capture" if selected == name else ""
            print(f"      {name}{marker}")
        if not selected:
            warn(
                "IM_AUDIO_DEVICE is not set. Browser recording works, but CLI "
                "recording needs the exact microphone name shown above."
            )
            return
        chosen = next(
            (name for name in audio if name.casefold() == selected.casefold()),
            None,
        )
        if chosen is None:
            fail(f"IM_AUDIO_DEVICE={selected!r} does not match an audio device")
        else:
            ok(f"CLI recording will use {chosen!r}")
        return

    selected = os.environ.get("IM_AUDIO_DEVICE", ":0")
    try:
        index = int(selected.lstrip(":").split(":")[0])
    except ValueError:
        fail(f"IM_AUDIO_DEVICE={selected!r} is not an AVFoundation index")
        return
    for current, name in enumerate(audio):
        marker = "  <-- CLI capture" if current == index else ""
        print(f"      [{current}] {name}{marker}")
    if not 0 <= index < len(audio):
        fail(f"IM_AUDIO_DEVICE={selected} does not exist - capture will fail")
        return
    chosen = audio[index]
    builtin = [
        current
        for current, name in enumerate(audio)
        if "macbook" in name.lower() and "mic" in name.lower()
    ]
    if builtin and index not in builtin:
        warn(f"capturing from {chosen!r}, NOT the built-in mic "
             f"(index {builtin[0]}). Fine IF it is deliberate and IF you use the same "
             f"device for seeding and querying - cross-device matching measured -0.258. "
             f"To force the built-in mic: export IM_AUDIO_DEVICE=':{builtin[0]}'")
    else:
        ok(f"capturing from {chosen!r}")


def main() -> int:
    print("=" * 62)
    print(" interaction-memory preflight")
    print("=" * 62)
    check_python()
    check_deps()
    if check_modules():
        check_models()
        check_config()
        check_storage_and_baseline(sys.argv[1:])
    check_audio_device()
    print("\n" + "=" * 62)
    if FAILS:
        print(f" NOT READY - {FAILS} failure(s), {WARNS} warning(s)")
    elif WARNS:
        print(f" READY with {WARNS} warning(s) - read them before demoing")
    else:
        print(" READY")
    print("=" * 62)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
