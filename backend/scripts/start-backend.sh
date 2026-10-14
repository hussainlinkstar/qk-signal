#!/usr/bin/env sh
set -eu

run_migrations="${RUN_MIGRATIONS:-1}"
if [ "$run_migrations" = "1" ]; then
  echo "Running database migrations..."
  alembic upgrade head
else
  echo "Skipping database migrations."
fi

backend_host="${BACKEND_HOST:-0.0.0.0}"
backend_port="${BACKEND_PORT:-8000}"
backend_log_level="${BACKEND_LOG_LEVEL:-error}"
backend_reload="${BACKEND_RELOAD:-0}"
backend_reload_dir="${BACKEND_RELOAD_DIR:-/app}"
backend_access_log="${BACKEND_ACCESS_LOG:-0}"

set -- uvicorn main:app --host "$backend_host" --port "$backend_port" --log-level "$backend_log_level"

if [ "$backend_reload" = "1" ]; then
  set -- "$@" --reload
  if [ -n "$backend_reload_dir" ]; then
    set -- "$@" --reload-dir "$backend_reload_dir"
  fi
fi

if [ "$backend_access_log" != "1" ]; then
  set -- "$@" --no-access-log
fi

exec "$@"
