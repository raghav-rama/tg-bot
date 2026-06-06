#!/bin/sh
set -eu

APP_USER="${APP_USER:-app}"
APP_GROUP="${APP_GROUP:-app}"
SQLITE_PATH="${SQLITE_PATH:-./data/bot.db}"

sqlite_parent="$(dirname "$SQLITE_PATH")"

mkdir -p "$sqlite_parent"
chown -R "$APP_USER:$APP_GROUP" "$sqlite_parent"

exec su -s /bin/sh -c 'exec "$@"' "$APP_USER" sh "$@"
