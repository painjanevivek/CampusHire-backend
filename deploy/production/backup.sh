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
backup_bucket="$(read_value OCI_BACKUP_BUCKET)"
recipient="$(read_value BACKUP_AGE_RECIPIENT)"
[[ -n "$namespace" && -n "$bucket" && -n "$backup_bucket" && -n "$recipient" ]] \
  || { printf 'Backup configuration is incomplete\n' >&2; exit 1; }
[[ "$bucket" != "$backup_bucket" ]] \
  || { printf 'Backup bucket must differ from the live private-object bucket\n' >&2; exit 1; }

stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
database_dump="${backup_directory}/database.dump"
quarantine_listing="${backup_directory}/quarantine-objects.json"
clean_listing="${backup_directory}/clean-objects.json"
object_manifest="${backup_directory}/object-manifest.json"
private_objects="${backup_directory}/private-objects"
bundle="${backup_directory}/campushire-${stamp}.tar"
encrypted="${bundle}.age"
mkdir -p "$private_objects"
docker compose --env-file "$environment_file" \
  --file deploy/staging/compose.yaml \
  --file deploy/oci/compose.override.yaml \
  --file deploy/production/compose.override.yaml \
  exec -T postgres pg_dump -U campushire -d campushire --format=custom >"$database_dump"
pg_restore --list "$database_dump" >/dev/null

oci os object list --namespace-name "$namespace" --bucket-name "$bucket" \
  --prefix quarantine/ --all --output json >"$quarantine_listing"
oci os object list --namespace-name "$namespace" --bucket-name "$bucket" \
  --prefix clean/ --all --output json >"$clean_listing"
for prefix in quarantine/ clean/; do
  oci os object bulk-download --namespace-name "$namespace" --bucket-name "$bucket" \
    --prefix "$prefix" --download-dir "$private_objects" --no-overwrite >/dev/null
done
python3 scripts/private_object_recovery.py create \
  --recorded-at "$stamp" \
  --listing "$quarantine_listing" --listing "$clean_listing" \
  --object-root "$private_objects" --output "$object_manifest"

tar --create --file "$bundle" --directory "$backup_directory" \
  database.dump object-manifest.json private-objects
age --recipient "$recipient" --output "$encrypted" "$bundle"
sha256sum "$encrypted" | awk '{print $1}' >"${encrypted}.sha256"

for file in "$encrypted" "${encrypted}.sha256"; do
  oci os object put --namespace-name "$namespace" --bucket-name "$backup_bucket" \
    --name "backups/daily/$(basename "$file")" --file "$file" --force >/dev/null
  oci os object head --namespace-name "$namespace" --bucket-name "$backup_bucket" \
    --name "backups/daily/$(basename "$file")" >/dev/null
done
if [[ "$(date -u +%u)" == "7" ]]; then
  for file in "$encrypted" "${encrypted}.sha256"; do
    oci os object copy --namespace-name "$namespace" --bucket-name "$backup_bucket" \
      --source-object-name "backups/daily/$(basename "$file")" \
      --destination-namespace "$namespace" --destination-bucket "$backup_bucket" \
      --destination-object-name "backups/weekly/$(basename "$file")" >/dev/null
  done
fi
python3 scripts/prune_oci_backups.py --namespace "$namespace" --bucket "$backup_bucket"
printf 'Encrypted off-host backup uploaded and verified: %s\n' "$stamp"
