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
API_BASE="$BASE_URL/api/v1"

OUT_DIR="${OUT_DIR:-reports/project-scoped-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT_DIR"

RUN_MAGIC_LINK_CREATE="${RUN_MAGIC_LINK_CREATE:-0}"
PROJECT_ID="${PROJECT_ID:-}"

log() {
  printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"
}

api_url() {
  local path="$1"
  printf '%s%s' "$API_BASE" "$path"
}

json_request() {
  local method="$1"
  local url="$2"
  local output_file="$3"
  local access_token="$4"
  local payload="${5:-}"

  local tmp_file
  tmp_file="$(mktemp)"

  local -a curl_cmd
  curl_cmd=(curl -sS -X "$method" "$url" -H "Accept: application/json")

  if [[ -n "$access_token" ]]; then
    curl_cmd+=(-H "Authorization: Bearer $access_token")
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

assert_jq() {
  local expression="$1"
  local file="$2"
  local message="$3"
  if ! jq -e "$expression" "$file" >/dev/null; then
    echo "Assertion failed: $message" >&2
    echo "File: $file" >&2
    cat "$file" >&2 || true
    exit 1
  fi
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

main() {
  log "Output directory: $OUT_DIR"
  log "API base: $API_BASE"

  local access_token
  access_token="$(resolve_access_token)"

  local projects_file="$OUT_DIR/01-projects.json"
  json_request GET "$(api_url /workspaces/current/projects)" "$projects_file" "$access_token"
  assert_jq 'type == "array"' "$projects_file" "Workspace projects response should be an array."

  local resolved_project_id="$PROJECT_ID"
  if [[ -z "$resolved_project_id" ]]; then
    resolved_project_id="$(jq -r '.[0].id // empty' "$projects_file")"
  fi
  if [[ -z "$resolved_project_id" ]]; then
    echo "No project found. Set PROJECT_ID explicitly or create a project first." >&2
    exit 1
  fi
  log "Using project_id=$resolved_project_id"

  local project_file="$OUT_DIR/02-project.json"
  json_request GET "$(api_url "/projects/$resolved_project_id")" "$project_file" "$access_token"
  assert_jq ".id == $resolved_project_id" "$project_file" "Project payload id mismatch."

  local audits_file="$OUT_DIR/03-project-audits.json"
  json_request GET "$(api_url "/projects/$resolved_project_id/audits?limit=5&include_full_report=false")" "$audits_file" "$access_token"
  assert_jq 'type == "array"' "$audits_file" "Project audits payload should be an array."

  local latest_audit_file="$OUT_DIR/04-project-latest-audit.json"
  json_request GET "$(api_url "/projects/$resolved_project_id/audits/latest?include_full_report=true")" "$latest_audit_file" "$access_token"
  assert_jq '(. == null) or (type == "object")' "$latest_audit_file" "Latest audit payload should be object or null."

  local data_sources_file="$OUT_DIR/05-project-data-sources.json"
  json_request GET "$(api_url "/projects/$resolved_project_id/data-sources")" "$data_sources_file" "$access_token"
  assert_jq 'type == "array" and length >= 1' "$data_sources_file" "Project data sources payload should contain entries."

  local magic_status_file="$OUT_DIR/06-project-magic-link-status.json"
  json_request GET "$(api_url "/projects/$resolved_project_id/magic-link-status")" "$magic_status_file" "$access_token"
  assert_jq '.status == "not_requested" or .status == "pending" or .status == "expired" or .status == "connected"' "$magic_status_file" "Invalid magic-link status."

  if [[ "$RUN_MAGIC_LINK_CREATE" == "1" ]]; then
    local magic_create_file="$OUT_DIR/07-project-magic-link-create.json"
    json_request \
      POST \
      "$(api_url "/projects/$resolved_project_id/magic-link")" \
      "$magic_create_file" \
      "$access_token" \
      '{"expires_in_hours":24}'
    assert_jq ".project_id == $resolved_project_id" "$magic_create_file" "Magic-link payload id mismatch."
    assert_jq '.link_url | type == "string" and test("/connect/")' "$magic_create_file" "Magic-link URL missing /connect/."
  else
    log "Skipping magic-link create test. Set RUN_MAGIC_LINK_CREATE=1 to enable."
  fi

  log "Project-scoped smoke checks passed."
  echo
  echo "Artifacts:"
  ls -1 "$OUT_DIR"
}

main "$@"
