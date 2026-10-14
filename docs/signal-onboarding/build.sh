#!/usr/bin/env bash
# Build the Qiko Signal onboarding guide PDF with WeasyPrint, the same engine
# the product uses for its own PDF reports (backend/requirements.txt pins
# weasyprint==70.0).
#
# Usage:
#   ./build.sh
#
# By default it reuses the Signal backend virtualenv, which already has the
# pinned WeasyPrint. Set WEASYPRINT_PYTHON=/path/to/python to use another one.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/onboarding-guide.html"
OUT="$HERE/Qiko-Signal-Onboarding-Guide.pdf"

resolve_python() {
  if [ -n "${WEASYPRINT_PYTHON:-}" ]; then
    echo "$WEASYPRINT_PYTHON"
    return
  fi
  # In-repo location: <repo>/docs/signal-onboarding -> <repo>/backend/.venv
  # Workspace location: <ws>/docs/signal-onboarding -> <ws>/qiko-signal/backend/.venv
  for candidate in \
    "$HERE/../../backend/.venv/bin/python" \
    "$HERE/../../qiko-signal/backend/.venv/bin/python"
  do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return
    fi
  done
  echo ""
}

PY="$(resolve_python)"

if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "No interpreter with WeasyPrint found." >&2
  echo "Set WEASYPRINT_PYTHON to a python that has weasyprint==70.0 installed," >&2
  echo "or create the Signal backend virtualenv at backend/.venv." >&2
  exit 1
fi

"$PY" -c "import weasyprint; print('WeasyPrint', weasyprint.__version__)"
"$PY" -m weasyprint "$SRC" "$OUT"

echo "Wrote $OUT"
