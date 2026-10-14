#!/usr/bin/env bash
set -euo pipefail

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd jq

BASE_URL="${BASE_URL:-https://qiko.ai/signal}"
BASE_URL="${BASE_URL%/}"

TARGET_URL="${TARGET_URL:-https://qiko.ai/signal}"
TARGET_ENTITY="${TARGET_ENTITY:-Qiko Signal}"
PROVIDER="${PROVIDER:-google}"

AUDIT_CATEGORY="${AUDIT_CATEGORY:-}"
AUDIT_MARKET="${AUDIT_MARKET:-}"
AUDIT_LANGUAGE="${AUDIT_LANGUAGE:-}"
AUDIT_ENTITIES="${AUDIT_ENTITIES:-}"

POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
POLL_TIMEOUT_SECONDS="${POLL_TIMEOUT_SECONDS:-900}"

OUT_DIR="${OUT_DIR:-reports/prod-audit-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT_DIR"

log() {
  printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"
}

api_url() {
  local path="$1"
  printf '%s/api/v1%s' "$BASE_URL" "$path"
}

json_request() {
  local method="$1"
  local url="$2"
  local output_file="$3"
  local auth_token="${4:-}"
  local payload="${5:-}"

  local tmp_file
  tmp_file="$(mktemp)"

  local -a curl_cmd
  curl_cmd=(curl -sS -X "$method" "$url" -H "Accept: application/json")

  if [[ -n "$auth_token" ]]; then
    curl_cmd+=(-H "Authorization: Bearer $auth_token")
  fi

  if [[ -n "$payload" ]]; then
    curl_cmd+=(-H "Content-Type: application/json" --data "$payload")
  fi

  local status
  status="$("${curl_cmd[@]}" -o "$tmp_file" -w "%{http_code}")"

  if [[ "$status" -lt 200 || "$status" -gt 299 ]]; then
    echo "Request failed: $method $url (HTTP $status)" >&2
    cat "$tmp_file" >&2 || true
    rm -f "$tmp_file"
    return 1
  fi

  if ! jq . "$tmp_file" >"$output_file" 2>/dev/null; then
    cp "$tmp_file" "$output_file"
  fi

  rm -f "$tmp_file"
}

resolve_access_token() {
  local access_token="${ACCESS_TOKEN:-}"
  access_token="$(printf '%s' "$access_token" | tr -d '\r\n')"

  if [[ -n "$access_token" ]]; then
    printf '%s' "$access_token"
    return 0
  fi

  local login_email="${LOGIN_EMAIL:-}"
  local login_password="${LOGIN_PASSWORD:-}"
  local login_mfa_code="${LOGIN_MFA_CODE:-}"

  if [[ -z "$login_email" || -z "$login_password" ]]; then
    echo "Missing authentication input." >&2
    echo "Set ACCESS_TOKEN or LOGIN_EMAIL + LOGIN_PASSWORD." >&2
    return 1
  fi

  local tmp_file
  tmp_file="$(mktemp)"

  local -a curl_cmd
  curl_cmd=(
    curl
    -sS
    -X POST
    "$(api_url /auth/login)"
    -H "Accept: application/json"
    -H "Content-Type: application/x-www-form-urlencoded"
    --data-urlencode "username=$login_email"
    --data-urlencode "password=$login_password"
  )

  if [[ -n "$login_mfa_code" ]]; then
    curl_cmd+=(--data-urlencode "mfa_code=$login_mfa_code")
  fi

  local status
  status="$("${curl_cmd[@]}" -o "$tmp_file" -w "%{http_code}")"

  if [[ "$status" -lt 200 || "$status" -gt 299 ]]; then
    echo "Login failed (HTTP $status)." >&2
    cat "$tmp_file" >&2 || true
    rm -f "$tmp_file"
    return 1
  fi

  access_token="$(jq -r '.access_token // empty' "$tmp_file" 2>/dev/null || true)"
  rm -f "$tmp_file"

  if [[ -z "$access_token" ]]; then
    echo "Login response did not include access_token." >&2
    return 1
  fi

  printf '%s' "$access_token"
}

build_job_payload() {
  local tier="$1"
  jq -nc \
    --arg url "$TARGET_URL" \
    --arg provider "$PROVIDER" \
    --arg tier "$tier" \
    --arg category "$AUDIT_CATEGORY" \
    --arg market "$AUDIT_MARKET" \
    --arg language "$AUDIT_LANGUAGE" \
    --arg entities "$AUDIT_ENTITIES" \
    '
    {
      url: $url,
      provider: $provider,
      tier: $tier
    }
    + (if $category != "" then {category: $category} else {} end)
    + (if $market != "" then {market: $market} else {} end)
    + (if $language != "" then {language: $language} else {} end)
    + (
      if $entities != "" then
        {
          entities: (
            $entities
            | split(",")
            | map(gsub("^\\s+|\\s+$"; ""))
            | map(select(length > 0))
          )
        }
      else
        {}
      end
    )
    '
}

run_guest_audit() {
  local guest_payload
  guest_payload="$(jq -nc --arg url "$TARGET_URL" --arg entity "$TARGET_ENTITY" '{url: $url, entity: $entity}')"

  log "Running Guest audit"
  json_request \
    POST \
    "$(api_url /guest-audit)" \
    "$OUT_DIR/01-guest-audit-final.json" \
    "" \
    "$guest_payload"
}

run_authenticated_audit() {
  local access_token="$1"
  local tier="$2"
  local file_prefix="$3"

  local create_file="$OUT_DIR/${file_prefix}-job-create.json"
  local status_latest_file="$OUT_DIR/${file_prefix}-job-status-latest.json"
  local status_log_file="$OUT_DIR/${file_prefix}-job-status-log.jsonl"
  local final_file="$OUT_DIR/${file_prefix}-final-audit.json"

  local job_payload
  job_payload="$(build_job_payload "$tier")"

  log "Creating ${tier} audit job"
  json_request \
    POST \
    "$(api_url /audit/jobs)" \
    "$create_file" \
    "$access_token" \
    "$job_payload"

  local job_id
  job_id="$(jq -r '.job_id // empty' "$create_file")"
  if [[ -z "$job_id" ]]; then
    echo "Missing job_id in create response for tier=$tier." >&2
    cat "$create_file" >&2 || true
    return 1
  fi

  : >"$status_log_file"
  local started_at_epoch
  started_at_epoch="$(date +%s)"

  while true; do
    json_request \
      GET \
      "$(api_url "/audit/jobs/$job_id")" \
      "$status_latest_file" \
      "$access_token"

    jq -c . "$status_latest_file" >>"$status_log_file" 2>/dev/null || cat "$status_latest_file" >>"$status_log_file"

    local status
    status="$(jq -r '.status // empty' "$status_latest_file")"
    local audit_id
    audit_id="$(jq -r '.audit_id // empty' "$status_latest_file")"

    if [[ "$status" == "succeeded" ]]; then
      if [[ -z "$audit_id" || "$audit_id" == "null" ]]; then
        echo "Job succeeded but audit_id is missing for tier=$tier." >&2
        cat "$status_latest_file" >&2 || true
        return 1
      fi

      log "${tier} job succeeded (audit_id=$audit_id). Fetching final audit JSON"
      json_request \
        GET \
        "$(api_url "/audits/$audit_id")" \
        "$final_file" \
        "$access_token"
      return 0
    fi

    if [[ "$status" == "failed" ]]; then
      echo "Job failed for tier=$tier." >&2
      cat "$status_latest_file" >&2 || true
      return 1
    fi

    local now_epoch elapsed_seconds
    now_epoch="$(date +%s)"
    elapsed_seconds=$((now_epoch - started_at_epoch))
    if (( elapsed_seconds >= POLL_TIMEOUT_SECONDS )); then
      echo "Timeout waiting for tier=$tier after ${POLL_TIMEOUT_SECONDS}s." >&2
      cat "$status_latest_file" >&2 || true
      return 1
    fi

    sleep "$POLL_INTERVAL_SECONDS"
  done
}

main() {
  log "Output directory: $OUT_DIR"
  log "Base URL: $BASE_URL"
  log "Target URL under test: $TARGET_URL"
  log "Provider: $PROVIDER"

  run_guest_audit

  local access_token
  access_token="$(resolve_access_token)"

  run_authenticated_audit "$access_token" "fast" "02-fast"
  run_authenticated_audit "$access_token" "smart" "03-smart"

  log "All 3 production audit tests completed"
  echo
  echo "Artifacts:"
  echo "  $OUT_DIR/01-guest-audit-final.json"
  echo "  $OUT_DIR/02-fast-final-audit.json"
  echo "  $OUT_DIR/03-smart-final-audit.json"
  echo
  echo "Job traces:"
  echo "  $OUT_DIR/02-fast-job-create.json"
  echo "  $OUT_DIR/02-fast-job-status-log.jsonl"
  echo "  $OUT_DIR/03-smart-job-create.json"
  echo "  $OUT_DIR/03-smart-job-status-log.jsonl"
}

main "$@"
