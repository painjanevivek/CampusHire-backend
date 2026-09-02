#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

environment_file="${1:-/opt/campushire/config/production.env}"
evidence_directory="${2:-/var/lib/campushire/operations}"
script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backend_root="$(cd -- "${script_directory}/../.." && pwd)"

fail() { printf 'Production operations check blocked: %s\n' "$1" >&2; exit 2; }
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

[[ -f "$environment_file" ]] || fail "protected production environment is missing"
host="$(read_value PRODUCTION_HOST)"
namespace="$(read_value OCI_OBJECT_NAMESPACE)"
bucket="$(read_value OCI_OBJECT_BUCKET)"
[[ -n "$host" && -n "$namespace" && -n "$bucket" ]] \
  || fail "non-secret operations configuration is incomplete"

compose=(docker compose --env-file "$environment_file"
  --file "${backend_root}/deploy/staging/compose.yaml"
  --file "${backend_root}/deploy/oci/compose.override.yaml"
  --file "${backend_root}/deploy/production/compose.override.yaml")

curl --fail --silent --show-error --max-time 10 \
  "https://${host}/api/v1/health/ready" >/dev/null || fail "API readiness failed"
"${backend_root}/deploy/production/check_object_quota.sh" "$environment_file" >/dev/null \
  || fail "private object upload guard is closed"

for service in postgres redis qdrant clamav api worker frontend gateway; do
  container_id="$("${compose[@]}" ps --quiet "$service")"
  [[ -n "$container_id" ]] || fail "${service} container is absent"
  state="$(docker inspect --format '{{.State.Status}}' "$container_id")"
  [[ "$state" == "running" ]] || fail "${service} container is not running"
done
for service in postgres redis clamav api; do
  container_id="$("${compose[@]}" ps --quiet "$service")"
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_id")"
  [[ "$health" == "healthy" ]] || fail "${service} health check is ${health}"
done

disk_percent="$(df --output=pcent /opt/campushire | tail -n 1 | tr -dc '0-9')"
[[ "$disk_percent" =~ ^[0-9]+$ ]] || fail "local disk utilization is unreadable"
(( disk_percent < 70 )) || fail "local disk utilization reached the 70 percent guard"

certificate_end="$(
  printf '\n' | openssl s_client -servername "$host" -connect "${host}:443" 2>/dev/null \
    | openssl x509 -noout -enddate | cut -d= -f2-
)"
certificate_epoch="$(date --date "$certificate_end" +%s)"
now_epoch="$(date -u +%s)"
certificate_days="$(( (certificate_epoch - now_epoch) / 86400 ))"
(( certificate_days > 14 )) || fail "certificate expires inside 14 days"

latest_backup_epoch="$(
  oci os object list --namespace-name "$namespace" --bucket-name "$bucket" \
    --prefix backups/daily/ --all --output json | python3 -c '
import datetime as dt
import json
import sys
items = [item for item in json.load(sys.stdin).get("data", []) if item["name"].endswith(".age")]
if items:
    value = max(items, key=lambda item: item["time-modified"])["time-modified"]
    print(int(dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()), end="")
'
)"
[[ "$latest_backup_epoch" =~ ^[0-9]+$ ]] || fail "no encrypted daily recovery point exists"
backup_age_seconds="$(( now_epoch - latest_backup_epoch ))"
(( backup_age_seconds >= 0 && backup_age_seconds < 108000 )) \
  || fail "latest encrypted backup is at least 30 hours old"

install -d -m 0700 "$evidence_directory"
evidence="${evidence_directory}/operations-$(date -u +%Y-%m-%dT%H%M%SZ).json"
temporary="${evidence}.tmp"
python3 - "$temporary" "$disk_percent" "$certificate_days" "$backup_age_seconds" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

path, disk_percent, certificate_days, backup_age_seconds = sys.argv[1:]
payload = {
    "schema_version": 1,
    "recorded_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "api_ready": True,
    "required_containers_running": True,
    "required_health_checks_passed": True,
    "object_upload_guard_open": True,
    "disk_percent": int(disk_percent),
    "certificate_days_remaining": int(certificate_days),
    "backup_age_seconds": int(backup_age_seconds),
}
Path(path).write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
PY
chmod 0600 "$temporary"
mv -- "$temporary" "$evidence"
python3 - "$evidence_directory" <<'PY'
import sys
from pathlib import Path

directory = Path(sys.argv[1])
records = sorted(
    directory.glob("operations-*.json"),
    key=lambda item: item.stat().st_mtime,
    reverse=True,
)
for expired in records[2016:]:
    expired.unlink()
PY
printf 'Production operations check passed; evidence: %s\n' "$evidence"
