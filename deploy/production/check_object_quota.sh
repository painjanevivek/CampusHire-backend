#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

environment_file="${1:-/opt/campushire/config/production.env}"
[[ -f "${environment_file}" ]] || { printf 'Quota check: environment missing\n' >&2; exit 1; }

read_value() {
  python3 - "$environment_file" "$1" <<'PY'
import sys
from pathlib import Path
name = sys.argv[2]
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.startswith(f"{name}="):
        print(line.split("=", 1)[1], end="")
        break
PY
}

namespace="$(read_value OCI_OBJECT_NAMESPACE)"
bucket="$(read_value OCI_OBJECT_BUCKET)"
limit="$(read_value OCI_OBJECT_QUOTA_BYTES)"
limit="${limit:-14000000000}"
used="$(oci os object list --namespace-name "$namespace" --bucket-name "$bucket" \
  --all --query 'sum(data[].size)' --raw-output)"
[[ "$used" =~ ^[0-9]+$ ]] || { printf 'Quota check: invalid OCI usage response\n' >&2; exit 1; }
if (( used >= limit )); then
  printf 'Quota check: upload guard required (%s of %s bytes)\n' "$used" "$limit" >&2
  exit 2
fi
printf 'Object quota within production guard (%s of %s bytes)\n' "$used" "$limit"
