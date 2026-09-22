#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

environment_file="${1:-/opt/campushire/config/production.env}"
failed_unit="${2:-unknown}"

[[ -f "$environment_file" ]] \
  || { printf 'Operations alert configuration is missing\n' >&2; exit 1; }
[[ "$failed_unit" =~ ^[A-Za-z0-9_.@:-]+$ ]] \
  || { printf 'Operations alert unit name is invalid\n' >&2; exit 1; }

python3 - "$environment_file" "$failed_unit" <<'PY'
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

environment_path = Path(sys.argv[1])
failed_unit = sys.argv[2]
values: dict[str, str] = {}
for raw_line in environment_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if line and not line.startswith("#") and "=" in line:
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()

webhook = values.get("OPERATIONS_ALERT_WEBHOOK_URL", "")
owner = values.get("OPERATIONS_ALERT_OWNER_REFERENCE", "")
if not webhook or not owner:
    raise SystemExit("Operations alert webhook or owner reference is missing")

payload = json.dumps(
    {
        "schema_version": 1,
        "event": "campushire_systemd_unit_failed",
        "failed_unit": failed_unit,
        "host": socket.gethostname(),
        "owner_reference": owner,
        "occurred_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    },
    separators=(",", ":"),
).encode("utf-8")
request = Request(
    webhook,
    data=payload,
    headers={"Content-Type": "application/json", "User-Agent": "CampusHire-Operations/1"},
    method="POST",
)
with urlopen(request, timeout=15) as response:  # noqa: S310 - validated HTTPS deployment URL
    if not 200 <= response.status < 300:
        raise SystemExit(f"Operations alert endpoint returned HTTP {response.status}")
PY

printf 'Failure alert delivered for %s\n' "$failed_unit"
