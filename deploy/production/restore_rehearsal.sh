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
identity_file="$(read_value BACKUP_AGE_IDENTITY_FILE)"
latest="$(oci os object list --namespace-name "$namespace" --bucket-name "$bucket" \
  --prefix backups/daily/ --all --query 'sort_by(data,&"time-modified")[-1].name' --raw-output)"
[[ "$latest" == *.age ]] || { printf 'No encrypted daily recovery point found\n' >&2; exit 1; }

encrypted="${rehearsal_directory}/backup.age"
checksum="${encrypted}.sha256"
plain="${rehearsal_directory}/backup.dump"
oci os object get --namespace-name "$namespace" --bucket-name "$bucket" \
  --name "$latest" --file "$encrypted" >/dev/null
oci os object get --namespace-name "$namespace" --bucket-name "$bucket" \
  --name "${latest}.sha256" --file "$checksum" >/dev/null
expected_checksum="$(tr -d '[:space:]' <"$checksum")"
actual_checksum="$(sha256sum "$encrypted" | awk '{print $1}')"
[[ "$expected_checksum" == "$actual_checksum" ]] \
  || { printf 'Encrypted backup checksum mismatch\n' >&2; exit 1; }
age --decrypt --identity "$identity_file" --output "$plain" "$encrypted"
pg_restore --list "$plain" >/dev/null

docker run --detach --name "$container_name" --tmpfs /var/lib/postgresql/data \
  --env POSTGRES_PASSWORD=rehearsal-only \
  postgres:17-alpine@sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73 >/dev/null
until docker exec "$container_name" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
docker exec "$container_name" createdb -U postgres campushire_restore_rehearsal
docker cp "$plain" "${container_name}:/tmp/backup.dump"
docker exec "$container_name" pg_restore -U postgres -d campushire_restore_rehearsal \
  --no-owner --no-privileges /tmp/backup.dump
docker exec "$container_name" psql -U postgres -d campushire_restore_rehearsal \
  -v ON_ERROR_STOP=1 -Atc 'select count(*) >= 0 from alembic_version' | grep -qx t
printf 'Isolated encrypted restore rehearsal passed for %s\n' "$latest"
