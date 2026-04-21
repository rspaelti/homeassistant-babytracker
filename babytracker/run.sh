#!/usr/bin/with-contenv bashio
set -euo pipefail

export BT_DB_PATH=/data/babytracker.sqlite3
export BT_DATA_DIR=/data
export BT_PHOTOS_DIR=/data/photos
export BT_BACKUPS_DIR=/data/backups
export BT_WHO_DIR=/app/data/who
export BT_TIMEZONE="$(bashio::config 'timezone')"
export BT_OWLET_PREFIX="$(bashio::config 'owlet_entity_prefix')"
export BT_LOG_LEVEL="$(bashio::config 'log_level')"
export BT_NOTIFY_SERVICE="$(bashio::config 'notify_service')"
export BT_HA_URL="http://supervisor/core"
export BT_HA_TOKEN="${SUPERVISOR_TOKEN}"
export BT_INGRESS=1

mkdir -p "$BT_PHOTOS_DIR" "$BT_BACKUPS_DIR"

cd /app

bashio::log.info "Running Alembic migrations..."
uv run alembic upgrade head

bashio::log.info "Loading WHO LMS data if empty..."
uv run python -m babytracker.scripts.load_who --if-empty

bashio::log.info "Ensuring parent user exists..."
uv run python -m babytracker.scripts.seed || true

bashio::log.info "Starting Baby-Tracker on port 8099..."
exec uv run uvicorn babytracker.main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --proxy-headers \
    --forwarded-allow-ips '*' \
    --log-level "${BT_LOG_LEVEL}"
