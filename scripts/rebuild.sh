#!/usr/bin/env bash
# =============================================================================
# rebuild.sh — Routine production update (thin wrapper)
#
# Delegates to the smart deployer: pulls origin/main and rebuilds only the
# service groups whose code changed. No Google Cloud / Secret Manager
# dependency — config comes from the instance .env files + runtime AWS SSM / DB.
#
# Usage:
#   ./scripts/rebuild.sh            # smart incremental rebuild
#   ./scripts/rebuild.sh --force    # rebuild everything
#   ./scripts/rebuild.sh --services "backend frontend"
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/deploy-production.sh" --non-interactive "$@"
