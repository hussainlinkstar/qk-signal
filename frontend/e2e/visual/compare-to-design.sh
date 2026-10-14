#!/usr/bin/env bash
# SIGV2-1066: run the approved-design <-> built-screen comparison inside the
# same pinned Playwright image as the regression suite, so design renders and
# built renders share one toolchain and one font rasteriser.
#
# Usage (via package.json scripts):
#   npm run test:design-compare          # compare against committed references
#   npm run test:design-compare:update   # re-record the design reference set
#                                        # (a deliberate, reviewable event)
#
# The approved MVP pages live outside this repo. Mount point inside the
# container is /design; override the host path with DESIGN_DIR.
#
# SIGV2-1219: this script launches, it does not contain. The steps that run
# inside the container live in design-compare-container.sh. It then refuses
# to exit 0 unless that run left a report newer than the moment it started,
# because the failure this ticket exists to remove was a silent one: the
# container exited 0 after the build having compared nothing at all, and the
# gate reported success. Divergence budgets are ratcheted from these numbers,
# so a run that measured nothing must never read as a pass.
set -euo pipefail

IMAGE="mcr.microsoft.com/playwright:v1.58.2-jammy@sha256:4698a73749c5848d3f5fcd42a2174d172fcad2b2283e087843b115424303a565"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

# SIGV2-1138: resolve the approved mockups from a git worktree too.
#
# The default used to be "$REPO_ROOT/../Qiko-Signal-MVP-TBR/mockup", which
# only exists for the main clone: from a worktree under .devin/worktrees/<key>
# the sibling directory is not there, the script exited 1, and anyone working
# in a worktree silently could not run the gating suite at all. The mockups sit
# next to the MAIN clone, so the main worktree's path is the one to resolve
# from, and `git worktree list --porcelain` reports it first by definition.
# Candidates are tried in order and every one tried is named on failure.
_candidates=()
if [ -n "${DESIGN_DIR:-}" ]; then
  _candidates+=("$DESIGN_DIR")
else
  _candidates+=("$REPO_ROOT/../Qiko-Signal-MVP-TBR/mockup")
  # SIGV2-1219: `|| true`, because `set -e` kills the script on a failed
  # command substitution in an assignment. With git's own stderr discarded
  # that produced a bare exit 128 and not one word of explanation.
  _main_root="$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null |
    awk '/^worktree /{print substr($0, 10); exit}' || true)"
  if [ -n "$_main_root" ] && [ "$_main_root" != "$REPO_ROOT" ]; then
    _candidates+=("$_main_root/../Qiko-Signal-MVP-TBR/mockup")
  fi
fi

DESIGN_DIR=""
for _candidate in "${_candidates[@]}"; do
  if [ -d "$_candidate" ]; then
    DESIGN_DIR="$(cd "$_candidate" && pwd)"
    break
  fi
done

if [ -z "$DESIGN_DIR" ]; then
  echo "approved design directory not found. Paths tried:" >&2
  for _candidate in "${_candidates[@]}"; do
    echo "  $_candidate" >&2
  done
  echo "set DESIGN_DIR to the Qiko-Signal-MVP-TBR/mockup checkout" >&2
  exit 1
fi
echo "approved mockups: $DESIGN_DIR" >&2

# SIGV2-1138: scoped per checkout, see docker-scope.sh.
SUITE_NAME="design-comparison"
# shellcheck source=./docker-scope.sh
. "$(dirname "$0")/docker-scope.sh"

# SIGV2-1219: the report is this gate's only evidence, so it is removed
# before the run and demanded after it. Removing it first means a stale
# report from a previous run cannot be mistaken for this run's answer; the
# timestamp floor below catches the case where the removal silently failed.
REPORT_DIR="$REPO_ROOT/frontend/e2e/design-comparison/report"
rm -rf "$REPORT_DIR"
STAMP="$(mktemp -t sigv2-design-compare.XXXXXX)"
trap 'rm -f "$STAMP"' EXIT
# `-nt` compares whole seconds in bash 3.2 (the macOS default), so give the
# stamp a one-second head start. A run that takes minutes does not notice,
# and a report written by this run is then strictly newer, always.
sleep 1

# SIGV2-1219: the steps that run inside the container are a FILE, not a
# quoted string. As `bash -lc '<script>'` they were one apostrophe in one
# comment away from being truncated in silence, which is exactly what
# happened: everything from the comment onwards was dropped, the container
# exited 0 after the build, and the gate passed without comparing anything.
# No `exec` either - this script has work to do after the container exits.
status=0
"$DOCKER" run --rm \
  --name "$CONTAINER_NAME" \
  -v "$REPO_ROOT:/repo" \
  -v "$DESIGN_DIR:/design:ro" \
  -v "$VOLUME_NODE_MODULES:/repo/frontend/node_modules" \
  -v "$VOLUME_NEXT_BUILD:/repo/frontend/.next-build" \
  -v "$VOLUME_NPM_CACHE:/root/.npm" \
  -w /repo/frontend \
  "$IMAGE" \
  bash /repo/frontend/e2e/visual/design-compare-container.sh "$@" || status=$?

# A report that is absent, or older than the moment this run started, means
# the comparison did not happen. Exiting 0 on either would hand back a
# verdict nothing earned, and budgets in thresholds.json get ratcheted from
# these numbers.
for _artifact in report.json report.md; do
  if [ ! -f "$REPORT_DIR/$_artifact" ]; then
    echo "" >&2
    echo "FAILED: no $REPORT_DIR/$_artifact after the run (container exit ${status})." >&2
    echo "compare.mjs did not run to completion, so nothing was measured. This is" >&2
    echo "a failure of the harness or of the run, never a pass: read the container" >&2
    echo "output above for the step that stopped." >&2
    exit 1
  fi
  if [ ! "$REPORT_DIR/$_artifact" -nt "$STAMP" ]; then
    echo "" >&2
    echo "FAILED: $REPORT_DIR/$_artifact predates this run (container exit ${status})." >&2
    echo "It is a leftover from an earlier run, not this one's answer." >&2
    exit 1
  fi
done

echo "divergence report: $REPORT_DIR/report.md" >&2
exit "$status"
