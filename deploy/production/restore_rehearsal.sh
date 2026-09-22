#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

environment_file="${1:-/opt/campushire/config/production.env}"
rehearsal_directory="$(mktemp -d /tmp/campushire-restore.XXXXXX)"
container_name="campushire-restore-$(date -u +%Y%m%d%H%M%S)"
cleanup() {
  docker rm --force "$container_name" >/dev/null 2>&1 || true
  rm -rf -- "$rehearsal_directory"
}
trap cleanup EXIT

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
rehearsal_bucket="$(read_value RESTORE_REHEARSAL_BUCKET)"
identity_file="$(read_value BACKUP_AGE_IDENTITY_FILE)"
[[ -n "$backup_bucket" && -n "$rehearsal_bucket" && -f "$identity_file" ]] \
  || { printf 'Restore rehearsal configuration is incomplete\n' >&2; exit 1; }
[[ "$bucket" != "$backup_bucket" && "$bucket" != "$rehearsal_bucket" \
   && "$backup_bucket" != "$rehearsal_bucket" ]] \
  || { printf 'Live, backup, and rehearsal buckets must be distinct\n' >&2; exit 1; }
latest="$(oci os object list --namespace-name "$namespace" --bucket-name "$backup_bucket" \
  --prefix backups/daily/ --all --output json | python3 -c '
import json
import sys
items = [item for item in json.load(sys.stdin).get("data", []) if item["name"].endswith(".age")]
if items:
    print(max(items, key=lambda item: item["time-modified"])["name"], end="")
')"
[[ "$latest" == *.age ]] || { printf 'No encrypted daily recovery point found\n' >&2; exit 1; }

encrypted="${rehearsal_directory}/backup.age"
checksum="${encrypted}.sha256"
bundle="${rehearsal_directory}/backup.tar"
database_dump="${rehearsal_directory}/database.dump"
object_manifest="${rehearsal_directory}/object-manifest.json"
oci os object get --namespace-name "$namespace" --bucket-name "$backup_bucket" \
  --name "$latest" --file "$encrypted" >/dev/null
oci os object get --namespace-name "$namespace" --bucket-name "$backup_bucket" \
  --name "${latest}.sha256" --file "$checksum" >/dev/null
expected_checksum="$(tr -d '[:space:]' <"$checksum")"
actual_checksum="$(sha256sum "$encrypted" | awk '{print $1}')"
[[ "$expected_checksum" == "$actual_checksum" ]] \
  || { printf 'Encrypted backup checksum mismatch\n' >&2; exit 1; }
age --decrypt --identity "$identity_file" --output "$bundle" "$encrypted"
tar --extract --file "$bundle" --directory "$rehearsal_directory" \
  database.dump object-manifest.json private-objects
pg_restore --list "$database_dump" >/dev/null
private_objects="${rehearsal_directory}/private-objects"
python3 scripts/private_object_recovery.py validate \
  --manifest "$object_manifest" --object-root "$private_objects"

restore_prefix="restore-rehearsal/$(date -u +%Y-%m-%dT%H%M%SZ)"
oci os object bulk-upload --namespace-name "$namespace" --bucket-name "$rehearsal_bucket" \
  --src-dir "$private_objects" --object-prefix "${restore_prefix}/" \
  --verify-checksum --no-overwrite >/dev/null
restored_listing="${rehearsal_directory}/restored-objects.json"
oci os object list --namespace-name "$namespace" --bucket-name "$rehearsal_bucket" \
  --prefix "${restore_prefix}/" --all --output json >"$restored_listing"
python3 scripts/private_object_recovery.py validate-upload \
  --manifest "$object_manifest" --restore-prefix "$restore_prefix" \
  --listing "$restored_listing"

docker run --detach --name "$container_name" --tmpfs /var/lib/postgresql/data \
  --env POSTGRES_PASSWORD=rehearsal-only \
  postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73 >/dev/null
until docker exec "$container_name" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
docker exec "$container_name" createdb -U postgres campushire_restore_rehearsal
docker cp "$database_dump" "${container_name}:/tmp/backup.dump"
docker exec "$container_name" pg_restore -U postgres -d campushire_restore_rehearsal \
  --no-owner --no-privileges /tmp/backup.dump
docker exec "$container_name" psql -U postgres -d campushire_restore_rehearsal \
  -v ON_ERROR_STOP=1 -Atc 'select count(*) >= 0 from alembic_version' | grep -qx t
printf 'Isolated database and private-object restore rehearsal passed for %s into %s/%s\n' \
  "$latest" "$rehearsal_bucket" "$restore_prefix"
