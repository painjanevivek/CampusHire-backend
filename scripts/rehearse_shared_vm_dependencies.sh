#!/usr/bin/env sh
set -eu

# Exercise bounded service failures on synthetic shared-VM staging. The script
# never stops the gateway or unrelated workloads and always attempts recovery.

project_dir=${CAMPUSHIRE_PROJECT_DIR:-/opt/campushire/current}
env_file=${CAMPUSHIRE_ENV_FILE:-/opt/campushire/config/staging.env}
base_url=${CAMPUSHIRE_PUBLIC_URL:-https://campushire.80-65-208-136.sslip.io}
cookie_jar=$(mktemp)

compose() {
  docker compose \
    --env-file "$env_file" \
    -f "$project_dir/deploy/staging/compose.yaml" \
    -f "$project_dir/deploy/shared-vm/compose.override.yaml" \
    "$@"
}

status_code() {
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$1"
}

wait_for_status() {
  url=$1
  expected=$2
  attempts=${3:-60}
  count=0
  while [ "$count" -lt "$attempts" ]; do
    actual=$(status_code "$url" || true)
    if [ "$actual" = "$expected" ]; then
      return 0
    fi
    count=$((count + 1))
    sleep 1
  done
  echo "Timed out waiting for $url to return $expected; last status was $actual." >&2
  return 1
}

wait_for_container_health() {
  container=$1
  attempts=${2:-90}
  count=0
  while [ "$count" -lt "$attempts" ]; do
    state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container" 2>/dev/null || true)
    if [ "$state" = "healthy" ] || [ "$state" = "running" ]; then
      return 0
    fi
    count=$((count + 1))
    sleep 1
  done
  echo "Timed out waiting for $container; last state was $state." >&2
  return 1
}

expect_value() {
  label=$1
  actual=$2
  expected=$3
  if [ "$actual" != "$expected" ]; then
    echo "$label expected $expected but received $actual." >&2
    return 1
  fi
}

recover_services() {
  compose start postgres redis qdrant clamav worker >/dev/null 2>&1 || true
  rm -f "$cookie_jar"
}
trap recover_services EXIT INT TERM

wait_for_status "$base_url/api/v1/health/live" 200
wait_for_status "$base_url/api/v1/health/ready" 200

# PostgreSQL is authoritative: liveness remains up while readiness fails closed.
compose stop postgres >/dev/null
postgres_live=$(status_code "$base_url/api/v1/health/live")
postgres_ready=$(status_code "$base_url/api/v1/health/ready")
expect_value postgres_live_during_outage "$postgres_live" 200
expect_value postgres_ready_during_outage "$postgres_ready" 503
compose start postgres >/dev/null
wait_for_container_health campushire-staging-postgres-1
wait_for_status "$base_url/api/v1/health/ready" 200

# Redis protects auth throttling: authentication fails closed while core health
# remains available, then returns to normal invalid-credential handling.
compose stop redis >/dev/null
curl --silent --show-error --cookie-jar "$cookie_jar" \
  --output /dev/null "$base_url/api/v1/auth/csrf"
csrf_token=$(awk '$6 == "campushire_csrf" {print $7}' "$cookie_jar" | tail -n 1)
test -n "$csrf_token"
redis_auth=$(curl --silent --show-error --cookie "$cookie_jar" \
  --header "Origin: $base_url" \
  --header "Content-Type: application/json" \
  --header "X-CSRF-Token: $csrf_token" \
  --data '{"email":"nobody@example.com","password":"invalid-password"}' \
  --output /dev/null --write-out '%{http_code}' \
  "$base_url/api/v1/auth/sign-in")
expect_value redis_auth_during_outage "$redis_auth" 503
compose start redis >/dev/null
wait_for_container_health campushire-staging-redis-1
redis_recovered_auth=$(curl --silent --show-error --cookie "$cookie_jar" \
  --header "Origin: $base_url" \
  --header "Content-Type: application/json" \
  --header "X-CSRF-Token: $csrf_token" \
  --data '{"email":"nobody@example.com","password":"invalid-password"}' \
  --output /dev/null --write-out '%{http_code}' \
  "$base_url/api/v1/auth/sign-in")
expect_value redis_auth_after_recovery "$redis_recovered_auth" 401

# Qdrant is non-authoritative: core readiness continues without the vector store.
compose stop qdrant >/dev/null
qdrant_live=$(status_code "$base_url/api/v1/health/live")
qdrant_ready=$(status_code "$base_url/api/v1/health/ready")
expect_value qdrant_live_during_outage "$qdrant_live" 200
expect_value qdrant_ready_during_outage "$qdrant_ready" 200
compose start qdrant >/dev/null
wait_for_container_health campushire-staging-qdrant-1

# Scanner and worker outages do not take the request-serving API down. Durable
# resume jobs are already verified separately by the performance rehearsal.
compose stop clamav >/dev/null
clamav_live=$(status_code "$base_url/api/v1/health/live")
expect_value clamav_live_during_outage "$clamav_live" 200
compose start clamav >/dev/null
wait_for_container_health campushire-staging-clamav-1

compose stop worker >/dev/null
worker_live=$(status_code "$base_url/api/v1/health/live")
expect_value worker_live_during_outage "$worker_live" 200
compose start worker >/dev/null
wait_for_container_health campushire-staging-worker-1

printf '%s\n' \
  "result=passed" \
  "postgres_live_during_outage=$postgres_live" \
  "postgres_ready_during_outage=$postgres_ready" \
  "postgres_ready_after_recovery=200" \
  "redis_auth_during_outage=$redis_auth" \
  "redis_auth_after_recovery=$redis_recovered_auth" \
  "qdrant_live_during_outage=$qdrant_live" \
  "qdrant_ready_during_outage=$qdrant_ready" \
  "clamav_live_during_outage=$clamav_live" \
  "worker_live_during_outage=$worker_live" \
  "all_services_recovered=true"
