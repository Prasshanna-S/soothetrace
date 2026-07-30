#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <LAN-IP>" >&2
  exit 2
fi

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "${PYTHON:-python3}" "$script_dir/make_cert.py" "$1"
