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
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

FAILS = 0
WARNS = 0


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
    `session._capture_wav` defaults to avfoundation index ':0', which on this machine is NOT
    the built-in microphone.
    """
    import re
    print("\nAudio input")
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation",
                            "-list_devices", "true", "-i", ""],
                           capture_output=True, timeout=15)
        text = (p.stderr or b"").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        warn("could not enumerate audio devices")
        return

    # Every line is prefixed "[AVFoundation indev @ 0x...] " - strip it, then take the
    # audio section only. (The earlier version filtered lines containing "AVFoundation",
    # which is all of them, so it always reported zero devices.)
    audio, in_audio = [], False
    for raw in text.splitlines():
        line = re.sub(r"^\[AVFoundation indev @ [^\]]*\]\s*", "", raw).strip()
        if line.lower().startswith("avfoundation audio devices"):
            in_audio = True
            continue
        if line.lower().startswith("avfoundation video devices"):
            in_audio = False
            continue
        m = re.match(r"^\[(\d+)\]\s+(.*)$", line)
        if in_audio and m:
            audio.append((m.group(1), m.group(2)))

    if not audio:
        warn("no audio input devices found - check System Settings > Privacy > Microphone")
        return

    selected = os.environ.get("IM_AUDIO_DEVICE", ":0")
    idx = selected.lstrip(":").split(":")[0]
    ok(f"{len(audio)} audio input device(s):")
    for i, name in audio:
        marker = "  <-- session.record will use this" if i == idx else ""
        print(f"      [{i}] {name}{marker}")

    chosen = dict(audio).get(idx)
    if chosen is None:
        fail(f"IM_AUDIO_DEVICE={selected} does not exist - capture will fail")
        return
    builtin = [i for i, n in audio if "macbook" in n.lower() and "mic" in n.lower()]
    if builtin and idx not in builtin:
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
