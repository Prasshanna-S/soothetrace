"""Minimal local server and storage primitives for the iOS capture spike.

This is deliberately isolated from the product service. It exists to measure browser and
transport behavior before the product architecture depends on either.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import ssl
import subprocess
import threading
import uuid
import wave
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from src import fingerprint


_MIME_EXTENSIONS = {
    "audio/mp4": ".m4a",
    "audio/mp4;codecs=mp4a.40.2": ".m4a",
    "video/mp4": ".mp4",
    "audio/webm": ".webm",
    "audio/webm;codecs=opus": ".webm",
    "audio/ogg": ".ogg",
    "audio/ogg;codecs=opus": ".ogg",
}


class SpikeStore:
    """Server-owned filesystem layout for untrusted browser captures."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.sessions_root = self.root / "sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self._event_lock = threading.Lock()

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        (self.sessions_root / session_id).mkdir(mode=0o700)
        return session_id

    def session_dir(self, session_id: str) -> Path:
        try:
            normalized = str(uuid.UUID(session_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("invalid spike session id") from exc
        if normalized != session_id:
            raise ValueError("spike session id must be canonical")
        path = (self.sessions_root / normalized).resolve()
        if path.parent != self.sessions_root:
            raise ValueError("spike session escaped storage root")
        return path

    def upload_path(self, session_id: str, sequence: int, mime: str) -> Path:
        if not isinstance(sequence, int) or isinstance(sequence, bool) or not 0 <= sequence <= 9999:
            raise ValueError("sequence must be an integer from 0 through 9999")
        normalized_mime = ";".join(
            part.strip() for part in (mime or "").lower().split(";")
        )
        extension = _MIME_EXTENSIONS.get(normalized_mime, ".bin")
        return self.session_dir(session_id) / f"capture-{sequence:04d}{extension}"

    def append_event(self, session_id: str, event: dict) -> None:
        if not isinstance(event, dict) or not isinstance(event.get("kind"), str):
            raise ValueError("event must be an object with a string kind")
        path = self.session_dir(session_id)
        if not path.is_dir():
            raise ValueError("unknown spike session")
        encoded = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        with self._event_lock:
            with (path / "events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")

    def read_events(self, session_id: str) -> list[dict]:
        path = self.session_dir(session_id) / "events.jsonl"
        if not path.exists():
            return []
        with self._event_lock:
            lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line]

    def save_upload(
        self,
        session_id: str,
        sequence: int,
        mime: str,
        payload: bytes,
    ) -> Path:
        if not payload:
            raise ValueError("capture payload is empty")
        path = self.upload_path(session_id, sequence, mime)
        if not path.parent.is_dir():
            raise ValueError("unknown spike session")
        try:
            with path.open("xb") as handle:
                handle.write(payload)
        except FileExistsError as exc:
            raise ValueError("capture sequence already exists") from exc
        return path

    def report(self, session_id: str) -> dict:
        session_dir = self.session_dir(session_id)
        if not session_dir.is_dir():
            raise ValueError("unknown spike session")
        uploads = [
            {"file": path.name, "bytes": path.stat().st_size}
            for path in sorted(session_dir.glob("capture-*"))
            if path.is_file()
        ]
        return {
            "session_id": session_id,
            "events": self.read_events(session_id),
            "uploads": uploads,
        }


def decode_upload(source: str | Path, decoded: str | Path) -> dict:
    """Decode a browser capture to canonical WAV and return measured facts."""
    source_path = Path(source)
    decoded_path = Path(decoded)
    if not source_path.is_file() or source_path.stat().st_size == 0:
        return {"ok": False, "error": "ffmpeg input is missing or empty"}
    decoded_path.parent.mkdir(parents=True, exist_ok=True)
    decoded_path.unlink(missing_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(decoded_path),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0 or not decoded_path.is_file():
        decoded_path.unlink(missing_ok=True)
        detail = (completed.stderr or completed.stdout or "unknown decoder error").strip()
        return {"ok": False, "error": f"ffmpeg decode failed: {detail[-1000:]}"}

    try:
        with wave.open(str(decoded_path), "rb") as handle:
            sample_rate = handle.getframerate()
            channels = handle.getnchannels()
            frames = handle.getnframes()
        samples = fingerprint.load_audio(str(decoded_path), sr=16000)
        if samples is None or len(samples) == 0:
            raise ValueError("decoded WAV contains no samples")
        rms = math.sqrt(float(np.mean(np.square(samples, dtype=np.float64))))
        peak = float(np.max(np.abs(samples)))
        acoustic = fingerprint.compute_windowed(str(decoded_path))
        return {
            "ok": True,
            "source_file": source_path.name,
            "decoded_file": decoded_path.name,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "source_bytes": source_path.stat().st_size,
            "duration_s": frames / sample_rate if sample_rate else 0.0,
            "sample_rate": sample_rate,
            "channels": channels,
            "mean_db": 20 * math.log10(max(rms, 1e-12)),
            "peak_db": 20 * math.log10(max(peak, 1e-12)),
            "fingerprint_dim": len(acoustic) if acoustic is not None else None,
        }
    except Exception as exc:
        decoded_path.unlink(missing_ok=True)
        return {"ok": False, "error": f"ffmpeg output validation failed: {exc}"}


def _handler_factory(store: SpikeStore, index_path: Path):
    assets_root = index_path.resolve().parent

    class SpikeHandler(BaseHTTPRequestHandler):
        server_version = "InteractionMemoryCaptureSpike/1"
        max_event_bytes = 64 * 1024
        max_upload_bytes = 64 * 1024 * 1024

        def log_message(self, format, *args):
            print(
                f"{datetime.now(timezone.utc).isoformat()} "
                f"{self.client_address[0]} {format % args}"
            )

        def _common_headers(self):
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")

        def _json(self, status: int, payload: dict):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str):
            self._json(status, {"error": message})

        def _body(self, maximum: int) -> bytes:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise ValueError("Content-Length is required")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length < 0 or length > maximum:
                raise ValueError(f"body exceeds {maximum} byte limit")
            return self.rfile.read(length)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/report":
                try:
                    session_id = parse_qs(parsed.query).get("session", [""])[0]
                    self._json(200, store.report(session_id))
                except ValueError as exc:
                    self._error(400, str(exc))
                return
            asset = {
                "/": index_path.resolve(),
                "/index.html": index_path.resolve(),
                "/app.js": assets_root / "app.js",
                "/app.css": assets_root / "app.css",
            }.get(parsed.path)
            if asset is None or not asset.is_file():
                self._error(404, "not found")
                return
            body = asset.read_bytes()
            content_type = (
                "text/javascript; charset=utf-8"
                if asset.suffix == ".js"
                else (
                    "text/css; charset=utf-8"
                    if asset.suffix == ".css"
                    else "text/html; charset=utf-8"
                )
            )
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; connect-src 'self'; "
                "style-src 'self'; media-src 'self'; object-src 'none'; base-uri 'none'",
            )
            self._common_headers()
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/session":
                    self._body(0)
                    self._json(201, {"session_id": store.create_session()})
                    return
                session_id = self.headers.get("X-Spike-Session", "")
                if parsed.path == "/api/events":
                    body = self._body(self.max_event_bytes)
                    event = json.loads(body.decode("utf-8"))
                    store.append_event(session_id, event)
                    self._json(201, {"stored": True})
                    return
                if parsed.path == "/api/upload":
                    body = self._body(self.max_upload_bytes)
                    sequence = int(self.headers.get("X-Spike-Sequence", ""))
                    mime = self.headers.get("Content-Type", "application/octet-stream")
                    saved = store.save_upload(session_id, sequence, mime, body)
                    self._json(
                        201,
                        {
                            "file": saved.name,
                            "bytes": saved.stat().st_size,
                            "mime": mime,
                        },
                    )
                    return
                self._error(404, "not found")
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._error(400, str(exc))

    return SpikeHandler


def build_http_server(address, store: SpikeStore, index_path: str | Path):
    """Build an unencrypted loopback-testable server; main() adds TLS."""
    return ThreadingHTTPServer(address, _handler_factory(store, Path(index_path)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the iOS capture spike over HTTPS.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args(argv)

    here = Path(__file__).resolve().parent
    server = build_http_server(
        (args.host, args.port),
        SpikeStore(args.data_root),
        here / "index.html",
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.cert, args.key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"Capture spike listening on https://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
