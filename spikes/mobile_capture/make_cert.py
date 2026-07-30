"""Generate local HTTPS certificates from macOS, Linux, or Windows."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .certificates import generate_certificates, server_certificate_matches_ip
except ImportError:
    from certificates import generate_certificates, server_certificate_matches_ip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the local CA and HTTPS certificate for an iPhone demo."
    )
    parser.add_argument("lan_ip", help="this laptop's LAN IP address")
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--check-existing",
        action="store_true",
        help="check that the existing server.pem is current and contains this IP",
    )
    args = parser.parse_args(argv)
    if args.check_existing:
        if args.output_dir:
            destination = Path(args.output_dir)
        else:
            root = Path(__file__).resolve().parents[2]
            destination = root / "data" / "audio" / "mobile-capture-spike" / "certs"
        certificate = destination / "server.pem"
        if server_certificate_matches_ip(certificate, args.lan_ip):
            print(certificate)
            return 0
        print(
            f"{certificate} is missing, expired, or does not contain {args.lan_ip}"
        )
        return 1
    paths = generate_certificates(args.lan_ip, args.output_dir)
    print(paths.root_certificate)
    print(paths.server_certificate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
