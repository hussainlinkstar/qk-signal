#!/usr/bin/env bash
# SIGV2-1219: the in-container half of compare-to-design.sh.
#
# Why this is a file and not a string
# -----------------------------------
# These steps used to live inside compare-to-design.sh as one single-quoted
# argument to `bash -lc`. On 2026-10-07 a comment in the middle of it gained
# an apostrophe (SIGV2-1195, "a developer checkout's .env.local"), which
# closed that single-quoted string. The container was then handed only the
# text up to the apostrophe: install, build, start two background servers,
# end of script. It exited 0. The app was never started, compare.mjs never
# ran, no report was written, and `npm run test:design-compare` reported
# success. A gate that exits zero having checked nothing is worse than no
# gate, because it manufactures confidence; moving the script into a file
# removes the outer quoting that made it possible.
#
# Arguments are forwarded to compare.mjs (--screens=, --shard=,
# --update-reference, --write-thresholds).
set -euo pipefail

cd /repo/frontend

REPORT_DIR="e2e/design-comparison/report"

if [ ! -x node_modules/.bin/playwright ] || [ package-lock.json -nt node_modules/.install-stamp ]; then
  npm ci --no-audit --no-fund
  touch node_modules/.install-stamp
fi

# Match a clean CI checkout: leftover test-results/playwright-report artifacts
# contain binaries (webm, zip) that the Tailwind v4 content scan turns into
# garbage class names, breaking the CSS build.
rm -rf test-results playwright-report
# The report IS the evidence this gate produces. Delete it before the run so
# that a report left behind by an earlier run can never be read, by a person
# or by the launcher, as this run's answer.
rm -rf "$REPORT_DIR"

NEXT_PUBLIC_ENABLE_RTL=true NEXT_TELEMETRY_DISABLED=1 npm run build

node e2e/visual/stub-backend.mjs >/tmp/stub.log 2>&1 &
node e2e/design-comparison/serve-design.mjs >/tmp/design.log 2>&1 &
# Same pin as run-in-docker.sh: BACKEND_URL in a developer checkout .env.local
# points at the dev backend port, which is dead inside this container, so the
# server-side /auth/me fails and every authed page renders the login wall
# (SIGV2-1195). Shell env wins over .env files.
NEXT_PUBLIC_ENABLE_RTL=true NEXT_DIST_DIR=.next-build PORT=3123 \
  BACKEND_URL=http://localhost:8000 \
  nohup npx next start -p 3123 >/tmp/next.log 2>&1 &

# SIGV2-1219: a readiness loop that simply falls through is the same class of
# defect as the one above. The old loops ran `curl && break || sleep 1` and
# carried on regardless, so a server that never came up was handed to
# compare.mjs anyway: a gating run then blamed the branch for RENDER_FAILED,
# and a recording run would have recorded pictures of nothing. Each wait now
# names the service, and a timeout prints that service's log and stops the run.
wait_for() {
  service_name="$1"
  service_url="$2"
  service_tries="$3"
  service_log="$4"
  i=0
  while [ "$i" -lt "$service_tries" ]; do
    # -f -s, not -fsS: a connection refused while a server is still
    # coming up is expected, and 90 lines of curl noise buries the real
    # output. The timeout branch below is where the failure is stated.
    if curl -fs -o /dev/null "$service_url"; then
      echo "ready: ${service_name} (${service_url})"
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "FATAL: ${service_name} did not answer ${service_url} within ${service_tries}s." >&2
  echo "Nothing was compared. Last 40 lines of ${service_log}:" >&2
  tail -n 40 "$service_log" >&2 || true
  return 1
}

wait_for "the built app" "http://localhost:3123/maintenance" 90 /tmp/next.log
wait_for "the stub backend" "http://localhost:8000/api/v1/auth/me" 30 /tmp/stub.log
wait_for "the design server" "http://localhost:3100/signal.css" 30 /tmp/design.log

status=0
node e2e/design-comparison/compare.mjs "$@" || status=$?

# Surface every endpoint the pages asked for that the stub does not
# serve - each one renders an error toast that inflates the diff.
grep "stub miss:" /tmp/stub.log | sort -u || true

# compare.mjs writes report.json and report.md as its last act. No report
# means it did not finish, whatever it exited with, and that is a failure of
# the run rather than a pass.
if [ ! -f "${REPORT_DIR}/report.json" ] || [ ! -f "${REPORT_DIR}/report.md" ]; then
  echo "FATAL: compare.mjs exited ${status} without writing ${REPORT_DIR}/report.{json,md}." >&2
  echo "The comparison did not run to completion, so this run proves nothing." >&2
  exit 1
fi

exit "$status"
