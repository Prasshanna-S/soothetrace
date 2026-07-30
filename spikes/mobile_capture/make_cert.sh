#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <LAN-IP>" >&2
  exit 2
fi

lan_ip="$1"
case "$lan_ip" in
  *[!0-9.]*|"")
    echo "LAN IP must contain only digits and dots" >&2
    exit 2
    ;;
esac

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
cert_dir="$repo_root/data/audio/mobile-capture-spike/certs"
mkdir -p "$cert_dir"
chmod 700 "$cert_dir"

openssl genrsa -out "$cert_dir/rootCA.key" 3072
openssl req -x509 -new -sha256 -days 30 \
  -key "$cert_dir/rootCA.key" \
  -out "$cert_dir/rootCA.pem" \
  -subj "/CN=Interaction Memory Local Spike CA" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

openssl req -new -newkey rsa:2048 -nodes \
  -keyout "$cert_dir/server.key" \
  -out "$cert_dir/server.csr" \
  -subj "/CN=$lan_ip" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" \
  -addext "subjectAltName=IP:$lan_ip,IP:127.0.0.1,DNS:localhost"

openssl x509 -req -sha256 -days 30 \
  -in "$cert_dir/server.csr" \
  -CA "$cert_dir/rootCA.pem" \
  -CAkey "$cert_dir/rootCA.key" \
  -CAcreateserial \
  -copy_extensions copy \
  -out "$cert_dir/server.pem"

chmod 600 "$cert_dir/rootCA.key" "$cert_dir/server.key"
chmod 644 "$cert_dir/rootCA.pem" "$cert_dir/server.pem"
rm "$cert_dir/server.csr" "$cert_dir/rootCA.srl"

echo "$cert_dir/rootCA.pem"
echo "$cert_dir/server.pem"
