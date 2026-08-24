#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backend_root="$(cd -- "${script_directory}/../.." && pwd)"
environment_file="${1:-/opt/campushire/config/staging.env}"

fail() {
  printf 'OCI deployment failed: %s\n' "$1" >&2
  exit 1
}

for command in docker python3 curl; do
  command -v "${command}" >/dev/null 2>&1 || fail "${command} is required"
done

[[ "$(uname -m)" == "aarch64" ]] || fail "the Always Free deployment expects an ARM64 VM"
[[ -f "${environment_file}" ]] || fail "protected environment file is missing"

environment_mode="$(stat -c '%a' "${environment_file}")"
(( 8#${environment_mode} <= 8#600 )) || fail "protected environment file must use mode 0600"

python3 "${backend_root}/scripts/validate_oci_environment.py" "${environment_file}"

read_environment() {
  local name="$1"
  python3 - "${environment_file}" "${name}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
name = sys.argv[2]
for raw_line in path.read_text(encoding="utf-8").splitlines():
    if raw_line.startswith(f"{name}="):
        print(raw_line.split("=", 1)[1], end="")
        raise SystemExit(0)
raise SystemExit(f"missing {name}")
PY
}

parser_host="$(read_environment PARSER_DOCKER_HOST)"
parser_cert_directory="$(read_environment PARSER_CLIENT_CERT_DIR)"
parser_image="$(read_environment RESUME_PARSER_IMAGE)"
staging_host="$(read_environment STAGING_HOST)"

for certificate in ca.pem cert.pem key.pem; do
  [[ -f "${parser_cert_directory}/${certificate}" ]] \
    || fail "parser launcher TLS material is incomplete"
done

DOCKER_HOST="${parser_host}" \
DOCKER_TLS_VERIFY=1 \
DOCKER_CERT_PATH="${parser_cert_directory}" \
  docker version --format '{{.Server.Version}}' >/dev/null \
  || fail "authenticated rootless parser launcher is unavailable"

DOCKER_HOST="${parser_host}" \
DOCKER_TLS_VERIFY=1 \
DOCKER_CERT_PATH="${parser_cert_directory}" \
  docker pull "${parser_image}" >/dev/null

compose=(
  docker compose
  --env-file "${environment_file}"
  --file "${backend_root}/deploy/staging/compose.yaml"
  --file "${backend_root}/deploy/oci/compose.override.yaml"
)

"${compose[@]}" config --quiet
"${compose[@]}" pull
"${compose[@]}" up --detach --remove-orphans --wait --wait-timeout 420

curl \
  --fail \
  --silent \
  --show-error \
  --retry 12 \
  --retry-all-errors \
  --retry-delay 5 \
  "https://${staging_host}/api/v1/health/ready" >/dev/null

mkdir -p /opt/campushire
ln -sfn "${backend_root}" /opt/campushire/current
printf 'OCI staging deployment passed for %s\n' "${staging_host}"
