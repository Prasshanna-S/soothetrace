"""Portable certificate generation for the local iPhone HTTPS demo."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class CertificatePaths:
    root_private_key: Path
    root_certificate: Path
    server_private_key: Path
    server_certificate: Path


def server_certificate_matches_ip(path: str | Path, lan_ip: str) -> bool:
    """Return whether a current server certificate is valid for this LAN address."""
    try:
        address = ipaddress.ip_address(lan_ip)
        certificate = x509.load_pem_x509_certificate(Path(path).read_bytes())
        san = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        if address not in san.get_values_for_type(x509.IPAddress):
            return False
        now = datetime.now(timezone.utc)
        not_before = certificate.not_valid_before_utc
        not_after = certificate.not_valid_after_utc
        return not_before <= now <= not_after
    except (OSError, ValueError, TypeError, x509.ExtensionNotFound):
        return False


def _write(path: Path, payload: bytes, mode: int) -> None:
    path.write_bytes(payload)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def generate_certificates(
    lan_ip: str,
    output_dir: str | Path | None = None,
) -> CertificatePaths:
    """Create a short-lived local CA and server certificate for one LAN address."""
    try:
        address = ipaddress.ip_address(lan_ip)
    except ValueError as exc:
        raise ValueError("LAN IP must be a valid IPv4 or IPv6 address") from exc
    if address.is_unspecified or address.is_multicast:
        raise ValueError("LAN IP must identify this computer on the local network")

    if output_dir is None:
        root = Path(__file__).resolve().parents[2]
        destination = root / "data" / "audio" / "mobile-capture-spike" / "certs"
    else:
        destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(destination, 0o700)
    except OSError:
        pass

    now = datetime.now(timezone.utc)
    valid_from = now - timedelta(minutes=5)
    valid_until = now + timedelta(days=30)
    root_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Interaction Memory Local Spike CA")]
    )
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    root_certificate = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_until)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(address))])
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(root_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_until)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(address),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.DNSName("localhost"),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )

    paths = CertificatePaths(
        root_private_key=destination / "rootCA.key",
        root_certificate=destination / "rootCA.pem",
        server_private_key=destination / "server.key",
        server_certificate=destination / "server.pem",
    )
    private_format = serialization.PrivateFormat.TraditionalOpenSSL
    encryption = serialization.NoEncryption()
    _write(
        paths.root_private_key,
        root_key.private_bytes(
            serialization.Encoding.PEM,
            private_format,
            encryption,
        ),
        0o600,
    )
    _write(
        paths.server_private_key,
        server_key.private_bytes(
            serialization.Encoding.PEM,
            private_format,
            encryption,
        ),
        0o600,
    )
    _write(
        paths.root_certificate,
        root_certificate.public_bytes(serialization.Encoding.PEM),
        0o644,
    )
    _write(
        paths.server_certificate,
        server_certificate.public_bytes(serialization.Encoding.PEM),
        0o644,
    )
    return paths
