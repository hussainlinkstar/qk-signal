#!/usr/bin/env sh
set -eu

echo "Starting Performance Sync Worker..."
exec python performance_sync_worker.py
