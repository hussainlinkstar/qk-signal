#!/usr/bin/env bash
# =============================================================================
# deploy-production.sh — Smart production deployment (AWS, SSM/.env based)
#
# Smart features:
#   - Pulls origin/main and detects exactly what changed
#   - Rebuilds ONLY the affected service group(s):
#       backend/**            -> backend + all workers + ai-service
#       frontend/**           -> frontend
#       caddy / Caddyfile     -> caddy
#       docker-compose*.yml   -> full stack
#   - No-ops when nothing changed (unless --force)
#   - Concurrency lock (safe for webhook-triggered deploys)
#   - Health check with automatic rollback to the previous commit on failure
#
# Secrets/config come from the instance .env files + runtime AWS SSM / DB.
# There is NO Google Cloud / Secret Manager dependency.
#
# Usage:
#   ./scripts/deploy-production.sh                    # interactive
#   ./scripts/deploy-production.sh --non-interactive  # scripted / webhook
#   ./scripts/deploy-production.sh --force            # rebuild everything
#   ./scripts/deploy-production.sh --services "backend frontend"
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="docker-compose.vps.yml"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
LOCK_FILE="${DEPLOY_LOCK_FILE:-/tmp/qiko-deploy.lock}"

# Service groups — keep in sync with docker-compose.vps.yml.
# Every worker + ai-service builds from ./backend, so a backend change rebuilds them all.
INFRA_SERVICES="db redis"
BACKEND_SERVICES="backend ai-service audit-worker email-worker billing-webhook-worker pdf-worker external-webhook-worker monitoring-worker visibility-worker performance-worker cron-sweeper"
FRONTEND_SERVICES="frontend"
PROXY_SERVICES="caddy"
ALL_SERVICES="$INFRA_SERVICES $BACKEND_SERVICES $FRONTEND_SERVICES $PROXY_SERVICES"

NON_INTERACTIVE="false"
SKIP_BUILD="false"
SKIP_PULL="false"
FORCE="false"
EXPLICIT_SERVICES=""

usage() {
  cat <<'EOF'
Smart production deployment for Qiko Signal.

Usage:
  scripts/deploy-production.sh [options]

Options:
  --non-interactive     Skip all prompts (scripted / webhook deploys)
  --force               Rebuild every service regardless of detected changes
  --services "a b c"    Rebuild only these explicit services
  --skip-pull           Do not git pull (deploy current working tree, rebuild all)
  --skip-build          Pull code only, do not rebuild containers
  --skip-secrets        Deprecated no-op (kept for backward compatibility)
  -h, --help            Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --non-interactive) NON_INTERACTIVE="true"; shift ;;
    --force)           FORCE="true"; shift ;;
    --services)        EXPLICIT_SERVICES="${2:-}"; shift 2 ;;
    --skip-pull)       SKIP_PULL="true"; shift ;;
    --skip-build)      SKIP_BUILD="true"; shift ;;
    --skip-secrets)    shift ;;                 # deprecated no-op
    -h|--help)         usage; exit 0 ;;
    *)                 echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()     { echo -e "${RED}[ERROR]${NC} $*" >&2; }

prompt_confirm() {
  local prompt_text="$1" default="${2:-y}"
  [[ "$NON_INTERACTIVE" == "true" ]] && return 0
  local yn; read -rp "$(echo -e "${BOLD}$prompt_text${NC} [${default}]: ")" yn
  yn="${yn:-$default}"; [[ "$yn" =~ ^[Yy] ]]
}

dedupe() { tr ' ' '\n' | awk 'NF && !seen[$0]++' | tr '\n' ' '; }

# ---------------------------------------------------------------------------
# Concurrency lock (webhook-safe)
# ---------------------------------------------------------------------------
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  err "Another deploy is already running ($LOCK_FILE). Aborting."
  exit 1
fi

echo ""
echo -e "${BOLD}========================================"
echo "  Qiko Signal — Smart Production Deploy"
echo -e "========================================${NC}"

# ---------------------------------------------------------------------------
# Step 1: Pull latest code
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}--- Step 1/4: Pull (origin/${DEPLOY_BRANCH}) ---${NC}"
BEFORE_SHA="$(git rev-parse HEAD)"
if [[ "$SKIP_PULL" == "true" ]]; then
  info "Skipping git pull (--skip-pull)"
  AFTER_SHA="$BEFORE_SHA"
else
  git fetch origin "$DEPLOY_BRANCH"
  git reset --hard "origin/${DEPLOY_BRANCH}"
  AFTER_SHA="$(git rev-parse HEAD)"
  success "Code: ${BEFORE_SHA:0:8} -> ${AFTER_SHA:0:8}"
fi

# ---------------------------------------------------------------------------
# Step 2: Verify environment
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}--- Step 2/4: Verify environment ---${NC}"
if [[ ! -f ".env" ]]; then
  err ".env not found in $PROJECT_ROOT. Bootstrap it (scripts/seed_ssm.py + env) before deploying."
  exit 1
fi
success ".env present ($(wc -l < .env) lines)"
[[ -f "frontend/.env" ]] && success "frontend/.env present" || warn "frontend/.env missing — frontend NEXT_PUBLIC_* may use defaults."
export ENVIRONMENT="production" APP_ENV="production"

# ---------------------------------------------------------------------------
# Step 3: Decide what to (re)build
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}--- Step 3/4: Change detection ---${NC}"

# The stamp is the last commit that finished a deploy, health check included.
# Git movement alone is not proof: the pull happens in step 2, so if the build
# then fails or a container is not replaced, BEFORE_SHA == AFTER_SHA on every
# later run and the deploy reports "already up to date" forever while serving
# stale code. That happened, twice, undetected. Comparing against the stamp
# instead means an incomplete deploy is retried on the next run.
DEPLOY_STAMP="$PROJECT_ROOT/.deployed-sha"
LAST_DEPLOYED="$(cat "$DEPLOY_STAMP" 2>/dev/null | tr -d '[:space:]' || true)"

TARGET=""
if [[ -n "$EXPLICIT_SERVICES" ]]; then
  TARGET="$EXPLICIT_SERVICES"
  info "Explicit services: $TARGET"
elif [[ "$FORCE" == "true" || "$SKIP_PULL" == "true" ]]; then
  TARGET="$ALL_SERVICES"
  info "Full rebuild ($([[ "$FORCE" == "true" ]] && echo --force || echo --skip-pull))"
elif [[ "$LAST_DEPLOYED" == "$AFTER_SHA" ]]; then
  success "Already up to date (${AFTER_SHA:0:8}); nothing to deploy."
  exit 0
elif [[ -z "$LAST_DEPLOYED" ]]; then
  # No stamp yet: first run after this change, or the file was removed. Rebuild
  # everything once so the stamp starts from a known state.
  TARGET="$ALL_SERVICES"
  info "No deploy stamp found -> full rebuild to establish one"
else
  # Diff from the last *deployed* commit, not from the previous HEAD, so a
  # deploy that failed earlier still rebuilds what it missed.
  if [[ "$LAST_DEPLOYED" != "$BEFORE_SHA" ]]; then
    warn "Last successful deploy was ${LAST_DEPLOYED:0:8}, HEAD was ${BEFORE_SHA:0:8}: recovering the gap."
  fi
  CHANGED="$(git diff --name-only "$LAST_DEPLOYED" "$AFTER_SHA")"
  echo "$CHANGED" | sed 's/^/    /' | head -40
  if echo "$CHANGED" | grep -qE '^docker-compose.*\.ya?ml$|^\.env|^scripts/deploy'; then
    TARGET="$ALL_SERVICES"; info "Compose/deploy change -> full rebuild"
  else
    echo "$CHANGED" | grep -qE '^backend/' && TARGET="$TARGET $BACKEND_SERVICES"
    echo "$CHANGED" | grep -qE '^frontend/' && TARGET="$TARGET $FRONTEND_SERVICES"
    echo "$CHANGED" | grep -qiE '^caddy|Caddyfile' && TARGET="$TARGET $PROXY_SERVICES"
  fi
fi

TARGET="$(echo "$TARGET" | dedupe | sed 's/ *$//')"
if [[ -z "$TARGET" ]]; then
  # Nothing to build, so this commit counts as deployed. Without the stamp the
  # next run would diff from the old one again and keep re-listing these files.
  echo "$AFTER_SHA" > "$DEPLOY_STAMP"
  success "No service-affecting changes (docs/tests only); skipping rebuild."
  exit 0
fi
info "Rebuilding: $TARGET"

# ---------------------------------------------------------------------------
# Step 4: Build, deploy, health-check (+ rollback)
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}--- Step 4/4: Build & Deploy ---${NC}"
if [[ "$SKIP_BUILD" == "true" ]]; then
  info "Skipping build (--skip-build)"; exit 0
fi

docker compose -f "$COMPOSE_FILE" config -q && success "Compose valid"
prompt_confirm "Build & (re)start: $TARGET ?" "y" || { info "Aborted by operator."; exit 0; }

# shellcheck disable=SC2086
docker compose -f "$COMPOSE_FILE" up -d --build $TARGET
success "Services (re)started"

# The Caddyfile is bind-mounted, so changing it does not change the container
# spec and `up -d` treats caddy as already up to date. Every Caddyfile change
# therefore landed on disk and was never loaded. A graceful reload applies it
# without dropping connections, and the config is validated first so a bad file
# leaves the running config untouched instead of taking the site down.
if echo "$TARGET" | grep -qw caddy; then
  CADDY_CID="$(docker compose -f "$COMPOSE_FILE" ps -q caddy 2>/dev/null || true)"
  if [[ -n "$CADDY_CID" ]]; then
    if docker exec "$CADDY_CID" caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
      docker exec "$CADDY_CID" caddy reload --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null 2>&1 \
        && success "Caddy config reloaded" \
        || warn "Caddy reload failed; the previous config is still serving."
    else
      err "New Caddyfile is invalid; skipping reload. The previous config is still serving."
    fi
  fi
fi

health_ok() {
  local elapsed=0 max=90
  while [[ $elapsed -lt $max ]]; do
    if docker compose -f "$COMPOSE_FILE" ps backend --format '{{.Status}}' 2>/dev/null | grep -qi healthy; then return 0; fi
    if docker compose -f "$COMPOSE_FILE" exec -T backend curl -sf http://localhost:8000/api/v1/health >/dev/null 2>&1; then return 0; fi
    sleep 5; elapsed=$((elapsed+5)); echo -ne "  Waiting backend... ${elapsed}s/${max}s\r"
  done
  return 1
}

echo ""
if echo "$TARGET" | grep -qw backend; then
  if health_ok; then
    success "Backend healthy"
  else
    echo ""
    err "Backend unhealthy after deploy — rolling back to ${BEFORE_SHA:0:8}"
    git reset --hard "$BEFORE_SHA"
    # shellcheck disable=SC2086
    docker compose -f "$COMPOSE_FILE" up -d --build $TARGET
    if health_ok; then
      # What is running is BEFORE_SHA now, so the stamp has to say so, otherwise
      # the next run would think AFTER_SHA is live and never retry it.
      echo "$BEFORE_SHA" > "$DEPLOY_STAMP"
      warn "Rolled back to previous version (healthy)."
    else
      err "Rollback still unhealthy - manual intervention required."
    fi
    exit 1
  fi
fi

# Only now, past the build and the health check, is this commit really deployed.
echo "$AFTER_SHA" > "$DEPLOY_STAMP"

echo ""
docker compose -f "$COMPOSE_FILE" ps --format "table {{.Service}}\t{{.Status}}" 2>/dev/null || docker compose -f "$COMPOSE_FILE" ps
echo ""
echo -e "${BOLD}Deploy complete${NC} (${AFTER_SHA:0:8}). Verify: curl -s https://qiko.ai/signal/api/v1/system-status | head"
