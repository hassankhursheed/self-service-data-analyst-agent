#!/bin/sh
# Inside Compose the .env URLs point at the database as seen from the host
# (localhost:5433); Compose sets DB_HOSTPORT=db:5432 so the host:port part of both URLs
# is swapped. Without DB_HOSTPORT (a hosted platform such as Railway) nothing is changed.
set -eu
if [ -n "${DB_HOSTPORT:-}" ]; then
  target="$DB_HOSTPORT"
  swap() { printf '%s' "$1" | sed -E "s#@[^/@]+/#@${target}/#"; }
  if [ -n "${APP_DATABASE_URL:-}" ]; then APP_DATABASE_URL="$(swap "$APP_DATABASE_URL")"; export APP_DATABASE_URL; fi
  if [ -n "${ANALYTICS_DATABASE_URL:-}" ]; then ANALYTICS_DATABASE_URL="$(swap "$ANALYTICS_DATABASE_URL")"; export ANALYTICS_DATABASE_URL; fi
  export POSTGRES_HOST="${target%:*}" POSTGRES_PORT="${target#*:}"
fi
exec "$@"
