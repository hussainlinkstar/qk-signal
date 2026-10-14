#!/bin/bash
# =============================================================================
# deploy.sh — Production deploy (thin wrapper)
#
# Delegates to the smart deployer in non-interactive mode. Used by the
# auto-deploy webhook and for manual deploys.
#
# Usage:
#   cd /opt/docker/qiko-signal
#   ./deploy.sh                 # smart: pull + rebuild only what changed
#   ./deploy.sh --force         # rebuild everything
#
# No Google Cloud / Secret Manager dependency — config comes from the
# instance .env files + runtime AWS SSM / DB.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

exec "$SCRIPT_DIR/scripts/deploy-production.sh" --non-interactive "$@"
