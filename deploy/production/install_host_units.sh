#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

[[ "${EUID}" -eq 0 ]] || { printf 'Host unit installation requires root\n' >&2; exit 1; }
id campushire >/dev/null 2>&1 \
  || { printf 'Non-login campushire service account is missing\n' >&2; exit 1; }

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install -d -o campushire -g campushire -m 0700 \
  /var/lib/campushire /var/lib/campushire/operations
for unit in \
  campushire-backup.service \
  campushire-backup.timer \
  campushire-operations-check.service \
  campushire-operations-check.timer; do
  install -o root -g root -m 0644 \
    "${script_directory}/systemd/${unit}" "/etc/systemd/system/${unit}"
done
systemctl daemon-reload
systemctl enable --now campushire-backup.timer campushire-operations-check.timer
systemctl is-enabled --quiet campushire-backup.timer campushire-operations-check.timer
printf 'CampusHire production host timers installed and enabled\n'
