#!/bin/sh
set -eu

database_directory=/var/lib/clamav

freshclam --stdout || {
  if ! find "${database_directory}" -maxdepth 1 -type f \
    \( -name '*.cvd' -o -name '*.cld' \) -print -quit | grep -q .; then
    echo "ClamAV signatures are unavailable" >&2
    exit 1
  fi
  echo "FreshClam update failed; starting with the existing signature set" >&2
}

exec clamd --foreground=true --config-file=/etc/clamav/clamd.conf
