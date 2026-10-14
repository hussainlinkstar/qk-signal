#!/usr/bin/env bash
# SIGV2-1219: the in-container half of run-in-docker.sh.
#
# A file, not a `bash -lc '<script>'` string, for the reason written up in
# design-compare-container.sh: one apostrophe inside one comment truncated
# its sibling script in silence and the gate passed having run nothing.
# Nothing here is quoted by a caller any more.
#
# Extra arguments are forwarded to Playwright.
set -euo pipefail

cd /repo/frontend

if [ ! -x node_modules/.bin/playwright ] || [ package-lock.json -nt node_modules/.install-stamp ]; then
  npm ci --no-audit --no-fund
  touch node_modules/.install-stamp
fi

npm run typecheck:e2e

# Match a clean CI checkout: leftover test-results/playwright-report
# artifacts contain binaries (webm, zip) that the Tailwind v4 content scan
# turns into garbage class names, breaking the CSS build.
rm -rf test-results playwright-report

NEXT_PUBLIC_ENABLE_RTL=true NEXT_TELEMETRY_DISABLED=1 npm run build

# Stub backend for the authed visual specs (SIGV2-1034): the suite baselines
# are recorded against this fixed data, not a live API. CI has no .env.local
# so BACKEND_URL falls through to http://localhost:8000; a developer checkout
# DOES have one and it points at the dev backend port, which is dead inside
# this container - the server-side /auth/me then 502s and every authed page
# redirects to /login. Shell env wins over .env files, so pin it here to keep
# local runs identical to CI.
node e2e/visual/stub-backend.mjs >/tmp/stub.log 2>&1 &
NEXT_PUBLIC_ENABLE_RTL=true NEXT_DIST_DIR=.next-build PORT=3123 \
  BACKEND_URL=http://localhost:8000 \
  nohup npx next start -p 3123 >/tmp/next.log 2>&1 &

# SIGV2-1219: the old loops carried on when a service never answered, so a
# dead app produced a wall of snapshot failures that looked like the branch's
# fault. Name the service, print its log, stop the run.
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
  echo "No test was run. Last 40 lines of ${service_log}:" >&2
  tail -n 40 "$service_log" >&2 || true
  return 1
}

wait_for "the built app" "http://localhost:3123/maintenance" 90 /tmp/next.log
wait_for "the stub backend" "http://localhost:8000/api/v1/auth/me" 30 /tmp/stub.log

# SIGV2-1219: caller arguments go BEFORE --project, never after.
# Playwright declares `--project <project-name...>`, which is variadic, so
# `--project "visual-*" e2e/visual/fixes.visual.spec.ts` handed the spec file
# to Playwright as a second PROJECT name and died with
# `Project(s) "e2e/visual/fixes.visual.spec.ts" not found` - a real argument
# being silently re-read as something else. Putting "$@" first means a test
# file, a --grep, or --update-snapshots all work the way they read.
status=0
E2E_BASE_URL=http://localhost:3123 npx playwright test "$@" --project "visual-*" || status=$?

# Surface every endpoint the pages asked for that the stub does not
# serve - each one renders an error toast that pollutes snapshots.
grep "stub miss:" /tmp/stub.log | sort -u || true

exit "$status"
