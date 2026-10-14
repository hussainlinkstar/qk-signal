#!/usr/bin/env bash
set -euo pipefail

FORWARD_TO="${STRIPE_FORWARD_TO:-http://localhost:8000/api/v1/webhooks/stripe}"
EVENTS="${STRIPE_EVENTS:-}"

if ! command -v stripe >/dev/null 2>&1; then
  echo "Stripe CLI is not installed." >&2
  echo "Install it locally: https://docs.stripe.com/stripe-cli" >&2
  exit 1
fi

echo "Forwarding Stripe webhooks to: $FORWARD_TO"
echo "Use the printed signing secret as STRIPE_WEBHOOK_SECRET_TEST in local development."

if [[ -n "$EVENTS" ]]; then
  exec stripe listen --forward-to "$FORWARD_TO" --events "$EVENTS"
fi

exec stripe listen --forward-to "$FORWARD_TO"
