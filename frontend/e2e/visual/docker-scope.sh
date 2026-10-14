#!/usr/bin/env bash
# SIGV2-1138: shared scoping for the two Docker-hosted e2e suites.
#
# Both suites cache node_modules, the npm cache and .next-build in named
# Docker volumes. Those names used to be global constants
# (sigv2-visual-node-modules, sigv2-visual-next-build, sigv2-visual-npm-cache),
# so two checkouts running a suite at the same time shared one set of mutable
# state. Observed consequences, all of which look like defects in the branch
# under test rather than harness collisions:
#
#   * "Another next build process is already running" - two `next build`
#     invocations against one .next-build volume.
#   * "Cannot find module playwright-core" with 28 phantom test failures - two
#     `npm ci` invocations tearing down and repopulating one node_modules
#     volume.
#   * One run removing the other's container during cleanup.
#   * A full design-compare reporting RENDER_FAILED on six screens that pass
#     when run scoped.
#
# The volumes are therefore scoped per checkout: every worktree (and the main
# clone) gets its own set, derived from the absolute repo root so the same
# checkout keeps its warm cache across runs. Overridable with
# SIGV2_VOLUME_SCOPE when a single checkout needs more than one isolated run.
#
# Within one checkout the two suites still SHARE the volumes on purpose: they
# build the same app from the same lockfile, and duplicating the cache per
# suite would double both disk use and cold-start time. Concurrency inside one
# checkout is instead made impossible rather than corrupting: the container
# name is scoped too, and `docker run --name` refuses a duplicate, so a second
# run in the same checkout fails immediately with an explanation instead of
# racing the first one through a shared volume.
#
# Sourced, not executed. Expects REPO_ROOT to be set, and SUITE_NAME to name
# the calling suite. Exports DOCKER, which both launchers use instead of a
# literal `docker`: SIGV2_DOCKER points it at a stand-in so the harness's own
# contract (a run that writes no report must not pass) can be tested without
# spending ten minutes of real container time. It is never set in normal use.

DOCKER="${SIGV2_DOCKER:-docker}"

# cksum is POSIX and present on macOS and Linux alike; sha1sum/shasum are not
# both. Ten digits of a checksum over the absolute path is plenty to separate
# the handful of checkouts that exist on one machine, and the basename keeps
# the volume list readable in `docker volume ls`.
_scope_slug() {
  local base
  # printf, not echo: a trailing newline is outside the allowed set and `tr`
  # would turn it into a stray dash in the middle of the volume name.
  base="$(printf '%s' "${1##*/}" | tr -c 'A-Za-z0-9_.-' '-')"
  printf '%s-%s' "$base" "$(printf '%s' "$1" | cksum | cut -d' ' -f1)"
}

VOLUME_SCOPE="${SIGV2_VOLUME_SCOPE:-$(_scope_slug "$REPO_ROOT")}"
# Docker object names must start with [a-zA-Z0-9] and then allow
# [a-zA-Z0-9_.-]; the slug above already satisfies that, but an operator-set
# SIGV2_VOLUME_SCOPE might not.
if ! printf '%s' "$VOLUME_SCOPE" | grep -Eq '^[a-zA-Z0-9][a-zA-Z0-9_.-]*$'; then
  echo "SIGV2_VOLUME_SCOPE must match [a-zA-Z0-9][a-zA-Z0-9_.-]*: got '$VOLUME_SCOPE'" >&2
  exit 1
fi

VOLUME_NODE_MODULES="sigv2-visual-${VOLUME_SCOPE}-node-modules"
VOLUME_NEXT_BUILD="sigv2-visual-${VOLUME_SCOPE}-next-build"
VOLUME_NPM_CACHE="sigv2-visual-${VOLUME_SCOPE}-npm-cache"
CONTAINER_NAME="sigv2-visual-${VOLUME_SCOPE}"

_existing_state="$("$DOCKER" ps -a --filter "name=^${CONTAINER_NAME}$" --format '{{.State}}' | head -1)"
if [ -n "$_existing_state" ]; then
  if [ "$_existing_state" = "running" ]; then
    echo "a suite is already running for this checkout (container ${CONTAINER_NAME})" >&2
    echo "both suites share one .next-build and one node_modules volume per checkout," >&2
    echo "so running them at once would corrupt both. Wait for it, or set" >&2
    echo "SIGV2_VOLUME_SCOPE to give this run its own isolated set of volumes." >&2
  else
    echo "a stale container named ${CONTAINER_NAME} is left over (state: ${_existing_state})" >&2
    echo "remove it with: docker rm ${CONTAINER_NAME}" >&2
  fi
  exit 1
fi

echo "${SUITE_NAME:-suite}: docker volumes scoped to '${VOLUME_SCOPE}' (${REPO_ROOT})" >&2
