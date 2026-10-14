#!/usr/bin/env sh
set -eu

run_migrations="${RUN_MIGRATIONS:-0}"
if [ "$run_migrations" = "1" ]; then
  echo "Running database migrations..."
  alembic upgrade head
else
  echo "Skipping database migrations."
fi

# Keep the Python worker as PID 1 so SIGTERM/SIGINT are delivered directly;
# graceful shutdown is handled inside queue_worker.py.
exec python queue_worker.py
