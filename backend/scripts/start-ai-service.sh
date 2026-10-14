#!/usr/bin/env sh
set -eu

ai_service_host="${AI_SERVICE_HOST:-0.0.0.0}"
ai_service_port="${AI_SERVICE_PORT:-8001}"
ai_service_log_level="${AI_SERVICE_LOG_LEVEL:-info}"
ai_service_reload="${AI_SERVICE_RELOAD:-0}"
ai_service_reload_dir="${AI_SERVICE_RELOAD_DIR:-/app}"

set -- uvicorn ai_service:app --host "$ai_service_host" --port "$ai_service_port" --log-level "$ai_service_log_level"

if [ "$ai_service_reload" = "1" ]; then
  set -- "$@" --reload
  if [ -n "$ai_service_reload_dir" ]; then
    set -- "$@" --reload-dir "$ai_service_reload_dir"
  fi
fi

exec "$@"
