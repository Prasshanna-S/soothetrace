"""Serve an iOS-installable local CA profile without exposing any private key."""

from __future__ import annotations

import argparse
import plistlib
import ssl
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROFILE_PATH = "/Interaction-Memory-Spike-CA-corrected.mobileconfig"
CERTIFICATE_PATH = "/Interaction-Memory-Spike-CA.cer"


def build_mobileconfig(certificate_der: bytes) -> bytes:
    """Wrap one DER root certificate in an iOS configuration profile."""
    if not certificate_der:
        raise ValueError("certificate is empty")
    certificate_uuid = str(uuid.uuid4()).upper()
    profile_uuid = str(uuid.uuid4()).upper()
    return plistlib.dumps(
        {
            "PayloadContent": [
                {
                    "PayloadCertificateFileName": "Interaction-Memory-Spike-CA.cer",
                    "PayloadContent": certificate_der,
                    "PayloadDescription": "Trusts only the local Interaction Memory capture spike.",
                    "PayloadDisplayName": "Interaction Memory Local Spike CA",
                    "PayloadIdentifier": "local.interaction-memory.spike.ca",
                    "PayloadType": "com.apple.security.root",
                    "PayloadUUID": certificate_uuid,
                    "PayloadVersion": 1,
                }
            ],
            "PayloadDescription": (
                "Temporary local certificate authority for the Interaction Memory iPhone "
                "microphone spike. Remove after testing."
            ),
            "PayloadDisplayName": "Interaction Memory Local Spike CA",
            "PayloadIdentifier": "local.interaction-memory.spike.profile",
            "PayloadOrganization": "Interaction Memory local proof of concept",
            "PayloadRemovalDisallowed": False,
            "PayloadType": "Configuration",
            "PayloadUUID": profile_uuid,
            "PayloadVersion": 1,
        },
        fmt=plistlib.FMT_XML,
        sort_keys=True,
    )


def certificate_der_from_pem(path: Path) -> bytes:
    pem = path.read_text(encoding="ascii")
    return ssl.PEM_cert_to_DER_cert(pem)


def build_bootstrap_server(address, certificate_der: bytes, mobileconfig: bytes):
    class BootstrapHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", CERTIFICATE_PATH, PROFILE_PATH):
                self.send_error(404)
                return
            if self.path == "/":
                self.send_response(302)
                self.send_header("Location", CERTIFICATE_PATH)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if self.path == CERTIFICATE_PATH:
                self.send_response(200)
                self.send_header("Content-Type", "application/pkix-cert")
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="Interaction-Memory-Spike-CA.cer"',
                )
                self.send_header("Content-Length", str(len(certificate_der)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(certificate_der)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-apple-aspen-config")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="Interaction-Memory-Spike-CA-corrected.mobileconfig"',
            )
            self.send_header("Content-Length", str(len(mobileconfig)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(mobileconfig)

        def log_message(self, format, *args):
            print(f"{self.client_address[0]} {format % args}", flush=True)

    return ThreadingHTTPServer(address, BootstrapHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the iOS CA configuration profile.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cert", required=True)
    args = parser.parse_args(argv)

    certificate_der = certificate_der_from_pem(Path(args.cert))
    mobileconfig = build_mobileconfig(certificate_der)
    server = build_bootstrap_server(
        (args.host, args.port),
        certificate_der,
        mobileconfig,
    )
    print(f"Certificate profile listening on http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
