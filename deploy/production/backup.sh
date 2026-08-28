#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

environment_file="${1:-/opt/campushire/config/production.env}"
backup_directory="$(mktemp -d /tmp/campushire-backup.XXXXXX)"
trap 'rm -rf -- "$backup_directory"' EXIT

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
recipient="$(read_value BACKUP_AGE_RECIPIENT)"
[[ -n "$namespace" && -n "$bucket" && -n "$recipient" ]] \
  || { printf 'Backup configuration is incomplete\n' >&2; exit 1; }

stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
plain="${backup_directory}/campushire-${stamp}.dump"
encrypted="${plain}.age"
docker compose --env-file "$environment_file" \
  --file deploy/staging/compose.yaml \
  --file deploy/oci/compose.override.yaml \
  --file deploy/production/compose.override.yaml \
  exec -T postgres pg_dump -U campushire -d campushire --format=custom >"$plain"
pg_restore --list "$plain" >/dev/null
age --recipient "$recipient" --output "$encrypted" "$plain"
sha256sum "$encrypted" | awk '{print $1}' >"${encrypted}.sha256"

for file in "$encrypted" "${encrypted}.sha256"; do
  oci os object put --namespace-name "$namespace" --bucket-name "$bucket" \
    --name "backups/daily/$(basename "$file")" --file "$file" --force >/dev/null
done
if [[ "$(date -u +%u)" == "7" ]]; then
  for file in "$encrypted" "${encrypted}.sha256"; do
    oci os object copy --namespace-name "$namespace" --bucket-name "$bucket" \
      --source-object-name "backups/daily/$(basename "$file")" \
      --destination-namespace "$namespace" --destination-bucket "$bucket" \
      --destination-object-name "backups/weekly/$(basename "$file")" >/dev/null
  done
fi
python3 scripts/prune_oci_backups.py --namespace "$namespace" --bucket "$bucket"
printf 'Encrypted off-host backup uploaded and verified: %s\n' "$stamp"
