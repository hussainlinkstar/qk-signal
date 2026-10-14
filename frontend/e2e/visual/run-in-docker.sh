#!/usr/bin/env bash
# SIGV2-1045: run the visual-regression suite inside the pinned Playwright
# image. The app is also BUILT inside this image (never on the host), so local
# and CI baselines are produced by the same toolchain and the same Linux font
# rasteriser.
#
# Usage (via package.json scripts):
#   npm run test:e2e:visual          # compare against committed baselines
#   npm run test:e2e:visual:update   # record baselines deliberately
#
# Extra args are passed to Playwright AHEAD of --project (SIGV2-1219): the
# flag is variadic, so anything after it was read as another project name.
#   npm run test:e2e:visual -- e2e/visual/fixes.visual.spec.ts
#   npm run test:e2e:visual -- --grep "dashboard"
set -euo pipefail

# Tag + digest: the tag alone is mutable, so the digest pins the exact image
# that produces and compares baselines. Changing the image means re-recording
# baselines, reviewed - never a silent refresh.
IMAGE="mcr.microsoft.com/playwright:v1.58.2-jammy@sha256:4698a73749c5848d3f5fcd42a2174d172fcad2b2283e087843b115424303a565"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

# node_modules, the npm cache and .next-build live in named volumes so repeat
# runs skip reinstall and incremental builds stay fast, and so root-owned
# artifacts never land in the tree. SIGV2-1138: those names are scoped per
# checkout, because global ones let two worktrees destroy each other's run.
SUITE_NAME="visual-regression"
# shellcheck source=./docker-scope.sh
. "$(dirname "$0")/docker-scope.sh"

# SIGV2-1219: the steps that run inside the container are a FILE, not a
# quoted string, and caller arguments are passed through to it rather than
# being spliced into a shell string. See design-compare-container.sh for the
# apostrophe that silently truncated the sibling script.
exec "$DOCKER" run --rm \
  --name "$CONTAINER_NAME" \
  -v "$REPO_ROOT:/repo" \
  -v "$VOLUME_NODE_MODULES:/repo/frontend/node_modules" \
  -v "$VOLUME_NEXT_BUILD:/repo/frontend/.next-build" \
  -v "$VOLUME_NPM_CACHE:/root/.npm" \
  -w /repo/frontend \
  "$IMAGE" \
  bash /repo/frontend/e2e/visual/visual-regression-container.sh "$@"
