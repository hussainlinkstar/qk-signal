#!/usr/bin/env sh
set -eu

echo "Starting Monitoring Worker..."
# Run as a long-lived container: loop instead of run-once, otherwise the process
# exits immediately and Docker's restart policy churns it in a backoff loop.
exec python monitoring_worker.py --loop --interval "${MONITORING_INTERVAL_SECONDS:-86400}"
