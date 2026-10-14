#!/usr/bin/env sh
set -eu

run_migrations="${RUN_MIGRATIONS:-0}"
if [ "$run_migrations" = "1" ]; then
  echo "Running database migrations..."
  alembic upgrade head
else
  echo "Skipping database migrations."
fi

exec python pdf_worker.py
