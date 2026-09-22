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

read_value() {
  python3 - "$environment_file" "$1" <<'PY'
import sys
from pathlib import Path
name = sys.argv[2]
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith(f"{name}="):
        print(line.split("=", 1)[1], end="")
        break
PY
}

compose=(docker compose --env-file "${environment_file}"
  --file "${backend_root}/deploy/staging/compose.yaml"
  --file "${backend_root}/deploy/oci/compose.override.yaml"
  --file "${backend_root}/deploy/production/compose.override.yaml")

"${compose[@]}" config --quiet
"${compose[@]}" pull

backend_sha="$(read_value BACKEND_GIT_SHA)"
frontend_sha="$(read_value FRONTEND_GIT_SHA)"
openapi_sha="$(read_value OPENAPI_SHA256)"
verify_image_label() {
  local image="$1" label="$2" expected="$3"
  local actual
  actual="$(docker image inspect --format "{{ index .Config.Labels \"${label}\" }}" "$image")"
  [[ "$actual" == "$expected" ]] \
    || fail "${image} label ${label} does not match the frozen candidate"
}
verify_image_label "$(read_value BACKEND_API_IMAGE)" org.opencontainers.image.revision "$backend_sha"
verify_image_label "$(read_value BACKEND_API_IMAGE)" com.campushire.openapi-sha256 "$openapi_sha"
verify_image_label "$(read_value BACKEND_WORKER_IMAGE)" org.opencontainers.image.revision "$backend_sha"
verify_image_label "$(read_value BACKEND_WORKER_IMAGE)" com.campushire.openapi-sha256 "$openapi_sha"
verify_image_label "$(read_value FRONTEND_IMAGE)" org.opencontainers.image.revision "$frontend_sha"
verify_image_label "$(read_value FRONTEND_IMAGE)" com.campushire.openapi-sha256 "$openapi_sha"
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
