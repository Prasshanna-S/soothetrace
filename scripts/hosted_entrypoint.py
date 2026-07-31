"""Initialize one persistent hosted runtime, then replace this process with the API."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import hosted_bootstrap  # noqa: E402
from src import config, fingerprint, store  # noqa: E402


DEFAULT_BASELINE_ASSET = REPO_ROOT / "deploy" / "population-baseline.json"


def _baseline_payload(path: str | Path = DEFAULT_BASELINE_ASSET) -> dict:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("packaged population baseline must be an object")
    if payload.get("encoder") != "mfcc87-v1":
        raise ValueError("packaged population baseline encoder is invalid")
    n = payload.get("n")
    mu = payload.get("mu")
    sd = payload.get("sd")
    if type(n) is not int or n < 20:
        raise ValueError("packaged population baseline sample count is invalid")
    if (
        not isinstance(mu, list)
        or not isinstance(sd, list)
        or len(mu) != fingerprint.DIM
        or len(sd) != fingerprint.DIM
    ):
        raise ValueError("packaged population baseline dimension is invalid")
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        for value in [*mu, *sd]
    ):
        raise ValueError("packaged population baseline contains invalid values")
    if any(float(value) <= 0.0 for value in sd):
        raise ValueError("packaged population baseline scale is invalid")
    return payload


def ensure_population_baseline(
    database: str,
    asset_path: str | Path = DEFAULT_BASELINE_ASSET,
) -> bool:
    """Install the public baseline once and preserve any persistent replacement."""
    store.init_db(database)
    if store.get_baseline(config.POPULATION_KEY, database):
        return False
    payload = _baseline_payload(asset_path)
    store.save_baseline(
        config.POPULATION_KEY,
        payload["mu"],
        payload["sd"],
        payload["n"],
        database,
    )
    installed = store.get_baseline(config.POPULATION_KEY, database)
    if not installed or installed.get("n") != payload["n"]:
        raise RuntimeError("packaged population baseline could not be installed")
    return True


def _server_command(database: str, audio_root: str, port: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "src.http_api",
        "--behind-tls-proxy",
        "--host",
        "0.0.0.0",
        "--port",
        port,
        "--data-root",
        audio_root,
        "--static-root",
        os.environ.get("IM_STATIC_ROOT", "/app/web"),
        "--db",
        database,
    ]


def main() -> int:
    data_root = os.environ.get("IM_DATA_ROOT", config.DATA_ROOT)
    database = os.environ.get("IM_DB_PATH", config.DB_PATH)
    audio_root = os.environ.get("IM_AUDIO_DIR", config.AUDIO_DIR)
    port = os.environ.get("PORT", "10000")
    try:
        installed = ensure_population_baseline(database)
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Hosted entrypoint failed: {exc}", file=sys.stderr)
        return 1
    if installed:
        print("Installed packaged population baseline.", flush=True)

    result = hosted_bootstrap.main(
        ["--data-root", data_root, "--db", database]
    )
    if result != 0:
        return result

    command = _server_command(database, audio_root, port)
    os.execv(sys.executable, command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
