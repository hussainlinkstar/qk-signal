#!/usr/bin/env bash
# =============================================================================
# setup-development.sh — Interactive local development environment setup
#
# Walks the developer through bootstrapping a local dev environment:
#   1. Generate passwords and secrets (DB, Redis, JWT, session)
#   2. Build containers
#   3. Health check
#
# Local dev uses dotenv (.env.development) with SSM_ENABLED=false.
# There is no Google Secret Manager dependency; deployed environments overlay
# AWS SSM Parameter Store at startup instead.
#
# Usage:
#   ./scripts/setup-development.sh
#
# Non-interactive mode:
#   ./scripts/setup-development.sh --non-interactive
#
# For the full onboarding guide, see deploy/LOCAL_DEV_RUNBOOK.md.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

NON_INTERACTIVE="false"
SKIP_DOCKER="false"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
usage() {
  cat <<'EOF'
Interactive development environment setup for Qiko Signal.

Usage:
  scripts/setup-development.sh [options]

Options:
  --non-interactive     Skip all prompts (use defaults)
  --skip-docker         Skip Docker container startup
  -h, --help            Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --non-interactive) NON_INTERACTIVE="true"; shift ;;
    --skip-docker)     SKIP_DOCKER="true"; shift ;;
    -h|--help)         usage; exit 0 ;;
    *)                 echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; }

prompt_value() {
  local varname="$1" prompt_text="$2" default="$3"
  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    eval "$varname=\"$default\""
    return
  fi
  local input
  read -rp "$(echo -e "${BOLD}$prompt_text${NC} [${default}]: ")" input
  eval "$varname=\"${input:-$default}\""
}

prompt_confirm() {
  local prompt_text="$1" default="${2:-y}"
  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    return 0
  fi
  local yn
  read -rp "$(echo -e "${BOLD}$prompt_text${NC} [${default}]: ")" yn
  yn="${yn:-$default}"
  [[ "$yn" =~ ^[Yy] ]]
}

gen_secret() {
  openssl rand -hex 32
}

gen_password() {
  openssl rand -base64 24 | tr -d '/+=' | head -c 32
}

set_env_value() {
  local file="$1" key="$2" value="$3"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

copy_if_missing() {
  local src="$1" dst="$2"
  if [[ -f "$dst" ]]; then
    echo "  SKIP   $dst (already exists)"
  else
    cp "$src" "$dst"
    echo "  CREATE $dst"
  fi
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}========================================"
echo "  Qiko Signal — Dev Environment Setup"
echo -e "========================================${NC}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Generate passwords and secrets
# ---------------------------------------------------------------------------
echo -e "${BOLD}--- Step 1/3: Generate Passwords & Secrets ---${NC}"
echo ""

# Create env files from examples first (needed for set_env_value)
copy_if_missing "$PROJECT_ROOT/.env.development.example" "$PROJECT_ROOT/.env.development"
copy_if_missing "$PROJECT_ROOT/backend/.env.development.example" "$PROJECT_ROOT/backend/.env.development"
copy_if_missing "$PROJECT_ROOT/frontend/.env.development.example" "$PROJECT_ROOT/frontend/.env.local"
echo ""

POSTGRES_PASSWORD="$(gen_password)"
REDIS_PASSWORD="$(gen_password)"
JWT_SECRET="$(gen_secret)"
JWT_SECRET_KEY="$(gen_secret)"
JWT_REFRESH_SECRET_KEY="$(gen_secret)"
SESSION_SECRET_KEY="$(gen_secret)"
OAUTH_TOKEN_ENCRYPTION_KEY="$(gen_secret)"

echo "  Generated secrets:"
echo ""
echo "    POSTGRES_PASSWORD         = ${POSTGRES_PASSWORD:0:8}..."
echo "    REDIS_PASSWORD            = ${REDIS_PASSWORD:0:8}..."
echo "    JWT_SECRET                = ${JWT_SECRET:0:12}..."
echo "    JWT_SECRET_KEY            = ${JWT_SECRET_KEY:0:12}..."
echo "    JWT_REFRESH_SECRET_KEY    = ${JWT_REFRESH_SECRET_KEY:0:12}..."
echo "    SESSION_SECRET_KEY        = ${SESSION_SECRET_KEY:0:12}..."
echo "    OAUTH_TOKEN_ENCRYPTION_KEY= ${OAUTH_TOKEN_ENCRYPTION_KEY:0:12}..."
echo ""

# Write secrets to .env.development
set_env_value "$PROJECT_ROOT/.env.development" "POSTGRES_PASSWORD" "$POSTGRES_PASSWORD"
set_env_value "$PROJECT_ROOT/.env.development" "DATABASE_URL" "postgresql://user:${POSTGRES_PASSWORD}@db:5432/dbname"
set_env_value "$PROJECT_ROOT/.env.development" "REDIS_PASSWORD" "$REDIS_PASSWORD"
set_env_value "$PROJECT_ROOT/.env.development" "REDIS_URL" "redis://:${REDIS_PASSWORD}@redis:6379"
set_env_value "$PROJECT_ROOT/.env.development" "JWT_SECRET" "$JWT_SECRET"
set_env_value "$PROJECT_ROOT/.env.development" "JWT_SECRET_KEY" "$JWT_SECRET_KEY"
set_env_value "$PROJECT_ROOT/.env.development" "JWT_REFRESH_SECRET_KEY" "$JWT_REFRESH_SECRET_KEY"
set_env_value "$PROJECT_ROOT/.env.development" "SESSION_SECRET_KEY" "$SESSION_SECRET_KEY"
set_env_value "$PROJECT_ROOT/.env.development" "OAUTH_TOKEN_ENCRYPTION_KEY" "$OAUTH_TOKEN_ENCRYPTION_KEY"
set_env_value "$PROJECT_ROOT/.env.development" "ENVIRONMENT" "development"

# Write JWT_SECRET to frontend env
set_env_value "$PROJECT_ROOT/frontend/.env.local" "JWT_SECRET" "$JWT_SECRET"

# Local dev uses pure dotenv (.env.development). Disable the AWS SSM overlay.
set_env_value "$PROJECT_ROOT/.env.development" "SSM_ENABLED" "false"

success "Passwords and secrets written to .env.development"

# ---------------------------------------------------------------------------
# Step 2: Start Docker containers
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}--- Step 2/3: Build & Start Containers ---${NC}"
echo ""

if [[ "$SKIP_DOCKER" == "true" ]]; then
  info "Skipping Docker startup (--skip-docker)"
else
  if prompt_confirm "Start Docker containers now?" "y"; then
    info "Starting infrastructure (db, redis)..."
    docker compose up -d db redis

    info "Waiting for database..."
    sleep 3

    info "Starting backend services..."
    docker compose up -d backend ai-service audit-worker email-worker pdf-worker \
      external-webhook-worker monitoring-worker visibility-worker \
      performance-worker cron-sweeper

    info "Starting frontend (dev mode with hot reload)..."
    docker compose --profile frontend-dev up -d frontend-dev

    echo ""
    success "All services started"
  else
    info "Skipping Docker startup"
  fi
fi

# ---------------------------------------------------------------------------
# Step 3: Health check
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}--- Step 3/3: Health Check ---${NC}"
echo ""

if [[ "$SKIP_DOCKER" == "true" ]]; then
  info "Skipping health check (Docker startup was skipped)"
else
  info "Waiting for backend to become healthy..."
  MAX_WAIT=60
  ELAPSED=0
  HEALTHY="false"

  while [[ $ELAPSED -lt $MAX_WAIT ]]; do
    if docker compose exec -T backend curl -sf http://localhost:8000/api/v1/health >/dev/null 2>&1; then
      HEALTHY="true"
      break
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    echo -ne "  Waiting... ${ELAPSED}s / ${MAX_WAIT}s\r"
  done

  echo ""
  if [[ "$HEALTHY" == "true" ]]; then
    success "Backend is healthy (${ELAPSED}s)"
  else
    warn "Backend health check timed out after ${MAX_WAIT}s"
    warn "Check logs: docker compose logs backend"
  fi

  echo ""
  info "Service status:"
  docker compose ps
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}========================================"
echo "  Setup Complete"
echo -e "========================================${NC}"
echo ""
echo "Environment files:"
echo "  .env.development"
echo "  backend/.env.development"
echo "  frontend/.env.local"
echo ""
echo -e "${BOLD}Next steps:${NC}"

if [[ "$SKIP_DOCKER" == "true" ]]; then
  echo "  1. docker compose up -d db redis"
  echo "  2. docker compose up -d backend ai-service audit-worker email-worker"
  echo "     pdf-worker external-webhook-worker monitoring-worker visibility-worker"
  echo "     performance-worker cron-sweeper"
  echo "  3. docker compose --profile frontend-dev up -d frontend-dev"
  echo "  4. Open http://localhost:3000"
else
  echo "  1. Open http://localhost:3000"
  echo "  2. Register a new account"
fi

echo ""
echo "See deploy/LOCAL_DEV_RUNBOOK.md for the full onboarding guide."
echo ""
