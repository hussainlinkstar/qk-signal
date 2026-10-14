#!/usr/bin/env bash
set -euo pipefail

compose_cmd=(docker compose)

backend_container_id="$(${compose_cmd[@]} ps -q backend)"
frontend_container_id="$(${compose_cmd[@]} ps -q frontend)"

if [[ -z "${backend_container_id}" || -z "${frontend_container_id}" ]]; then
  echo "Expected backend and frontend containers to be running."
  echo "Backend container ID: ${backend_container_id:-<missing>}"
  echo "Frontend container ID: ${frontend_container_id:-<missing>}"
  exit 1
fi

backend_container_name=$(docker inspect --format '{{.Name}}' "${backend_container_id}" | sed 's#^/##')
frontend_container_name=$(docker inspect --format '{{.Name}}' "${frontend_container_id}" | sed 's#^/##')

internal_backend_url="http://backend:8000/openapi.json"
external_backend_url="http://localhost:8000/openapi.json"
external_frontend_url="http://localhost:3000"

cat <<STATUS
Compose connectivity smoke test
Backend container: ${backend_container_name}
Frontend container: ${frontend_container_name}
Internal backend URL: ${internal_backend_url}
External backend URL: ${external_backend_url}
External frontend URL: ${external_frontend_url}
STATUS

python_cmd=$(command -v python3 || command -v python)

if [[ -z "${python_cmd}" ]]; then
  echo "Python is required to run this smoke test." >&2
  exit 1
fi

host_check() {
  local url="$1"
  "${python_cmd}" - <<PY
import sys
import urllib.request

url = "${url}"
try:
    with urllib.request.urlopen(url, timeout=5) as response:
        if response.status >= 400:
            raise SystemExit(1)
except Exception:
    raise SystemExit(1)
PY
}

internal_check() {
  local url="$1"
  "${compose_cmd[@]}" exec -T frontend node -e "fetch('${url}').then(res => { if (!res.ok) process.exit(1); }).catch(() => process.exit(1));"
}

failure=0

if ! internal_check "${internal_backend_url}"; then
  echo "Internal connectivity check failed: ${internal_backend_url}" >&2
  failure=1
fi

if ! host_check "${external_backend_url}"; then
  echo "External backend check failed: ${external_backend_url}" >&2
  failure=1
fi

if ! host_check "${external_frontend_url}"; then
  echo "External frontend check failed: ${external_frontend_url}" >&2
  failure=1
fi

if [[ "${failure}" -ne 0 ]]; then
  exit 1
fi

echo "Connectivity smoke test passed."
