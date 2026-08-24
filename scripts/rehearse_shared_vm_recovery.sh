#!/usr/bin/env sh
set -eu

# Rehearse PostgreSQL restore and Alembic rollback/roll-forward on the shared
# staging VM without modifying the active database. The deployment account must
# be able to run the CampusHire Compose project and Docker commands.

project_dir=${CAMPUSHIRE_PROJECT_DIR:-/opt/campushire/current}
env_file=${CAMPUSHIRE_ENV_FILE:-/opt/campushire/config/staging.env}
source_db=${CAMPUSHIRE_SOURCE_DB:-campushire}
restore_db=${CAMPUSHIRE_RESTORE_DB:-campushire_restore_rehearsal}
postgres_container=${CAMPUSHIRE_POSTGRES_CONTAINER:-campushire-staging-postgres-1}
api_container=${CAMPUSHIRE_API_CONTAINER:-campushire-staging-api-1}
dump_path="/tmp/${restore_db}.dump"

if [ "$source_db" != "campushire" ]; then
  echo "Refusing unexpected source database: $source_db" >&2
  exit 2
fi

if [ "$restore_db" != "campushire_restore_rehearsal" ]; then
  echo "Refusing unexpected rehearsal database: $restore_db" >&2
  exit 2
fi

compose() {
  docker compose \
    --env-file "$env_file" \
    -f "$project_dir/deploy/staging/compose.yaml" \
    -f "$project_dir/deploy/shared-vm/compose.override.yaml" \
    "$@"
}

psql_source() {
  docker exec "$postgres_container" \
    psql -v ON_ERROR_STOP=1 -U campushire -d "$source_db" "$@"
}

psql_restore() {
  docker exec "$postgres_container" \
    psql -v ON_ERROR_STOP=1 -U campushire -d "$restore_db" "$@"
}

database_exists() {
  docker exec "$postgres_container" \
    psql -v ON_ERROR_STOP=1 -U campushire -d postgres -Atc \
      "SELECT 1 FROM pg_database WHERE datname = '$restore_db';"
}

cleanup() {
  docker exec "$postgres_container" rm -f "$dump_path" >/dev/null 2>&1 || true
  if [ "$(database_exists 2>/dev/null || true)" = "1" ]; then
    docker exec "$postgres_container" \
      psql -v ON_ERROR_STOP=1 -U campushire -d postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$restore_db';" \
      >/dev/null
    docker exec "$postgres_container" \
      dropdb -U campushire --if-exists "$restore_db" >/dev/null
  fi
}
trap cleanup EXIT INT TERM

if [ "$(database_exists)" = "1" ]; then
  echo "Rehearsal database already exists; refusing to overwrite it." >&2
  exit 3
fi

count_sql="SELECT jsonb_build_object(
  'users', (SELECT count(*) FROM users),
  'institutions', (SELECT count(*) FROM institutions),
  'applications', (SELECT count(*) FROM applications),
  'audit_events', (SELECT count(*) FROM audit_events),
  'resume_processing_jobs', (SELECT count(*) FROM resume_processing_jobs),
  'resume_job_events', (SELECT count(*) FROM resume_job_events)
)::text;"

started_ms=$(date +%s%3N)
source_head=$(psql_source -Atc "SELECT version_num FROM alembic_version;")
source_counts=$(psql_source -Atc "$count_sql")

docker exec "$postgres_container" \
  pg_dump -U campushire -d "$source_db" --format=custom --file="$dump_path"
backup_ms=$(date +%s%3N)
backup_sha256=$(docker exec "$postgres_container" sha256sum "$dump_path" | awk '{print $1}')

docker exec "$postgres_container" createdb -U campushire "$restore_db"
docker exec "$postgres_container" \
  pg_restore -U campushire -d "$restore_db" --exit-on-error --no-owner "$dump_path"
restore_ms=$(date +%s%3N)

restored_head=$(psql_restore -Atc "SELECT version_num FROM alembic_version;")
restored_counts=$(psql_restore -Atc "$count_sql")
if [ "$restored_head" != "$source_head" ] || [ "$restored_counts" != "$source_counts" ]; then
  echo "Restored database verification failed." >&2
  exit 4
fi

source_url=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$api_container" |
  awk -F= '$1 == "DATABASE_URL" {sub(/^[^=]*=/, ""); print; exit}')
if [ -z "$source_url" ]; then
  echo "Unable to resolve the API database URL." >&2
  exit 5
fi
restore_url="${source_url%/*}/$restore_db"

compose run --rm --no-deps -T -e "DATABASE_URL=$restore_url" api alembic downgrade -1 >/dev/null
downgraded_head=$(psql_restore -Atc "SELECT version_num FROM alembic_version;")
if [ "$downgraded_head" = "$source_head" ]; then
  echo "Migration downgrade did not move the isolated database." >&2
  exit 6
fi

compose run --rm --no-deps -T -e "DATABASE_URL=$restore_url" api alembic upgrade head >/dev/null
forward_ms=$(date +%s%3N)
forward_head=$(psql_restore -Atc "SELECT version_num FROM alembic_version;")
forward_counts=$(psql_restore -Atc "$count_sql")
if [ "$forward_head" != "$source_head" ] || [ "$forward_counts" != "$source_counts" ]; then
  echo "Forward recovery verification failed." >&2
  exit 7
fi

active_head=$(psql_source -Atc "SELECT version_num FROM alembic_version;")
active_counts=$(psql_source -Atc "$count_sql")
if [ "$active_head" != "$source_head" ] || [ "$active_counts" != "$source_counts" ]; then
  echo "Active database changed during the isolated rehearsal." >&2
  exit 8
fi

printf '%s\n' \
  "result=passed" \
  "source_database_untouched=true" \
  "migration_head=$source_head" \
  "downgraded_head=$downgraded_head" \
  "authoritative_counts=$source_counts" \
  "backup_sha256=$backup_sha256" \
  "backup_duration_ms=$((backup_ms - started_ms))" \
  "restore_duration_ms=$((restore_ms - backup_ms))" \
  "rollback_forward_duration_ms=$((forward_ms - restore_ms))" \
  "total_duration_ms=$((forward_ms - started_ms))"
