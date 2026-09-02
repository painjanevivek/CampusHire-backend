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
database_dump="${backup_directory}/database.dump"
quarantine_listing="${backup_directory}/quarantine-objects.json"
clean_listing="${backup_directory}/clean-objects.json"
object_manifest="${backup_directory}/object-manifest.json"
bundle="${backup_directory}/campushire-${stamp}.tar"
encrypted="${bundle}.age"
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
python3 - "$stamp" "$quarantine_listing" "$clean_listing" "$object_manifest" <<'PY'
import json
import sys
from pathlib import Path

recorded_at, quarantine_path, clean_path, output_path = sys.argv[1:]
objects = []
for source in (quarantine_path, clean_path):
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    for item in payload.get("data", []):
        objects.append(
            {
                "name": item["name"],
                "size": int(item["size"]),
                "etag": item.get("etag"),
                "time_modified": item.get("time-modified"),
            }
        )
manifest = {
    "schema_version": 1,
    "recorded_at_utc": recorded_at,
    "object_count": len(objects),
    "total_bytes": sum(item["size"] for item in objects),
    "objects": sorted(objects, key=lambda item: item["name"]),
}
Path(output_path).write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY

tar --create --file "$bundle" --directory "$backup_directory" \
  database.dump object-manifest.json
age --recipient "$recipient" --output "$encrypted" "$bundle"
sha256sum "$encrypted" | awk '{print $1}' >"${encrypted}.sha256"

for file in "$encrypted" "${encrypted}.sha256"; do
  oci os object put --namespace-name "$namespace" --bucket-name "$bucket" \
    --name "backups/daily/$(basename "$file")" --file "$file" --force >/dev/null
  oci os object head --namespace-name "$namespace" --bucket-name "$bucket" \
    --name "backups/daily/$(basename "$file")" >/dev/null
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
