#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backend_root="$(cd -- "${script_directory}/../.." && pwd)"
environment_file="${1:-/opt/campushire/config/production.env}"

fail() { printf 'Production deployment blocked: %s\n' "$1" >&2; exit 1; }

[[ -f /etc/campushire-dedicated-production-host ]] \
  || fail "dedicated-host attestation is missing"
[[ "$(uname -m)" == "aarch64" ]] || fail "the bounded OCI target requires ARM64"
[[ -f "${environment_file}" ]] || fail "protected production environment is missing"
(( 8#$(stat -c '%a' "${environment_file}") <= 8#600 )) \
  || fail "production environment must use mode 0600"

(cd "${backend_root}" && python3 -m scripts.validate_production_environment "${environment_file}")
"${backend_root}/deploy/production/check_object_quota.sh" "${environment_file}"

compose=(docker compose --env-file "${environment_file}"
  --file "${backend_root}/deploy/staging/compose.yaml"
  --file "${backend_root}/deploy/oci/compose.override.yaml"
  --file "${backend_root}/deploy/production/compose.override.yaml")

"${compose[@]}" config --quiet
"${compose[@]}" pull
"${compose[@]}" up --detach --remove-orphans --wait --wait-timeout 420

production_host="$(python3 - "${environment_file}" <<'PY'
import sys
from pathlib import Path
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.startswith("PRODUCTION_HOST="):
        print(line.split("=", 1)[1], end="")
        break
PY
)"
curl --fail --silent --show-error --retry 12 --retry-all-errors \
  "https://${production_host}/api/v1/health/ready" >/dev/null
printf 'Immutable production deployment passed for %s\n' "${production_host}"
