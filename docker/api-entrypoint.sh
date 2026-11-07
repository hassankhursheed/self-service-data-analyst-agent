#!/bin/sh
# The .env URLs point at the database as seen from the host (localhost:5433). Inside
# Compose the database is the "db" service, so swap the host:port part of both URLs.
set -eu
target="${DB_HOSTPORT:-db:5432}"
swap() { printf '%s' "$1" | sed -E "s#@[^/@]+/#@${target}/#"; }
if [ -n "${APP_DATABASE_URL:-}" ]; then APP_DATABASE_URL="$(swap "$APP_DATABASE_URL")"; export APP_DATABASE_URL; fi
if [ -n "${ANALYTICS_DATABASE_URL:-}" ]; then ANALYTICS_DATABASE_URL="$(swap "$ANALYTICS_DATABASE_URL")"; export ANALYTICS_DATABASE_URL; fi
export POSTGRES_HOST="${target%:*}" POSTGRES_PORT="${target#*:}"
exec "$@"
