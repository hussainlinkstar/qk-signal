#!/usr/bin/env bash
# =============================================================================
# wipe-and-redeploy.sh — Full wipe + clean production redeploy
#
# WARNING: This destroys ALL Docker volumes including the database.
#          All persistent data will be permanently lost.
#
# Usage:
#   cd /opt/docker/qiko-signal
#   ./scripts/wipe-and-redeploy.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="docker-compose.vps.yml"

cd "$PROJECT_ROOT"

RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${RED}${BOLD}========================================"
echo "  WARNING: Full Wipe & Redeploy"
echo -e "========================================${NC}"
echo ""
echo -e "${RED}This will PERMANENTLY DESTROY:${NC}"
echo "  - All Docker volumes (PostgreSQL data, Redis data)"
echo "  - All Docker images and build cache"
echo "  - All container state"
echo ""
echo -e "${BOLD}This action cannot be undone.${NC}"
echo ""

read -rp "Type YES to proceed: " CONFIRM
if [[ "$CONFIRM" != "YES" ]]; then
  echo "Aborted."
  exit 1
fi

echo ""
echo "--- Stopping all containers ---"
docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true

echo ""
echo "--- Pruning Docker system ---"
docker system prune -af

echo ""
echo "--- Running production deploy ---"
exec "$SCRIPT_DIR/deploy-production.sh"
