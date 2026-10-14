#!/usr/bin/env sh
set -eu

echo "Starting Visibility Index Worker..."
exec python visibility_index_worker.py
