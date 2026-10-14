#!/usr/bin/env sh
set -eu

echo "Starting Cron Sweeper..."
exec python cron_sweeper.py
