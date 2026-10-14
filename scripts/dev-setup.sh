#!/bin/bash
# =============================================================================
# dev-setup.sh ? Bootstrap local dev environment
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo ""
echo "========================================"
echo "  Qiko Signal ? Dev Environment Setup"
echo "========================================"
echo ""

gen_secret() {
  openssl rand -hex 32
}

echo "--- [1/3] Creating development env files from examples ---"

copy_if_missing() {
  local src="$1" dst="$2"
  if [ -f "$dst" ]; then
    echo "  SKIP   $dst (already exists)"
  else
    cp "$src" "$dst"
    echo "  CREATE $dst"
  fi
}

copy_if_missing "$ROOT/.env.development.example" "$ROOT/.env.development"
copy_if_missing "$ROOT/backend/.env.development.example" "$ROOT/backend/.env.development"
copy_if_missing "$ROOT/frontend/.env.development.example" "$ROOT/frontend/.env.local"

echo ""
echo "--- [2/3] Generating local JWT secrets ---"

JWT_SECRET=$(gen_secret)
JWT_SECRET_KEY=$(gen_secret)
JWT_REFRESH_SECRET_KEY=$(gen_secret)
SESSION_SECRET_KEY=$(gen_secret)

set_env_value() {
  local file="$1" key="$2" value="$3"
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

set_env_value "$ROOT/.env.development" "JWT_SECRET" "$JWT_SECRET"
set_env_value "$ROOT/.env.development" "JWT_SECRET_KEY" "$JWT_SECRET_KEY"
set_env_value "$ROOT/.env.development" "JWT_REFRESH_SECRET_KEY" "$JWT_REFRESH_SECRET_KEY"
set_env_value "$ROOT/.env.development" "SESSION_SECRET_KEY" "$SESSION_SECRET_KEY"
set_env_value "$ROOT/.env.development" "ENVIRONMENT" "development"
set_env_value "$ROOT/frontend/.env.local" "JWT_SECRET" "$JWT_SECRET"
# Local dev uses pure dotenv (.env.development). Disable the AWS SSM overlay.
set_env_value "$ROOT/.env.development" "SSM_ENABLED" "false"

echo ""
echo "--- [3/3] Done! ---"
echo ""
echo "Your local development env files are ready:"
echo "  .env.development"
echo "  backend/.env.development (minimal backend-only overlay)"
echo "  frontend/.env.local"
echo ""
echo "Next steps:"
echo ""
echo "  # Start infrastructure first"
echo "  1. docker compose up -d db redis"
echo ""
echo "  # Start backend + all workers"
echo "  2. docker compose up -d backend ai-service audit-worker email-worker pdf-worker external-webhook-worker monitoring-worker visibility-worker performance-worker cron-sweeper"
echo ""
echo "  # Start dev frontend (hot reload)"
echo "  3. docker compose --profile frontend-dev up -d frontend-dev"
echo ""
echo "  4. Open http://localhost:3000"
echo ""
echo "See LOCAL_DEV_RUNBOOK.md for the full onboarding guide."
echo ""
