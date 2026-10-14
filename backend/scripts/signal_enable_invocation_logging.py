#!/usr/bin/env python3
"""EPIC 13 / Phase 2 — enable Bedrock model-invocation logging to S3.

Tagged Bedrock invocations (see core/bedrock_metadata) only become a distillation
training corpus once model-invocation logging is turned on. This script configures
that logging to an S3 bucket (optionally CloudWatch too), in the engine's Bedrock
region.

SAFETY: defaults to a DRY RUN (prints the config, makes no AWS call). Pass --apply
to actually call PutModelInvocationLoggingConfiguration. Requires control-plane AWS
credentials with bedrock:PutModelInvocationLoggingConfiguration and an S3 delivery
role (see the EPIC-13 doc for the role/policy).

Usage:
  python scripts/signal_enable_invocation_logging.py \
      --bucket qiko-signal-bedrock-logs --prefix bedrock-invocation-logs \
      --role-arn arn:aws:iam::ACCOUNT:role/BedrockInvocationLogging [--region eu-north-1] [--apply]
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _default_bedrock_region() -> str:
    """Default --region from the app's configured Bedrock region (SIGV2-1028),
    falling back to the BEDROCK_REGION env var when settings can't load."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    try:
        from core.bedrock_runtime import configured_bedrock_region

        return configured_bedrock_region()
    except Exception:
        return os.getenv("BEDROCK_REGION", "eu-north-1")


def build_logging_config(bucket: str, prefix: str, role_arn: str | None) -> dict:
    config: dict = {
        "s3Config": {"bucketName": bucket, "keyPrefix": prefix},
        "textDataDeliveryEnabled": True,
        "imageDataDeliveryEnabled": False,
        "embeddingDataDeliveryEnabled": False,
    }
    if role_arn:
        # roleArn is required when delivering to a customer-managed destination.
        config["s3Config"]["roleArn"] = role_arn
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enable Bedrock model-invocation logging to S3 (EPIC 13 phase 2)."
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket for invocation logs.")
    parser.add_argument("--prefix", default="bedrock-invocation-logs", help="S3 key prefix.")
    parser.add_argument(
        "--role-arn", default=None, help="IAM role ARN Bedrock assumes to write to S3."
    )
    parser.add_argument("--region", default=_default_bedrock_region(), help="Bedrock region.")
    parser.add_argument(
        "--apply", action="store_true", help="Actually call AWS (default: dry run)."
    )
    args = parser.parse_args(argv)

    logging_config = build_logging_config(args.bucket, args.prefix, args.role_arn)
    print(f"[region={args.region}] PutModelInvocationLoggingConfiguration loggingConfig=")
    print(json.dumps(logging_config, indent=2))

    if not args.apply:
        print("\nDRY RUN — no AWS call made. Re-run with --apply to enable logging.")
        return 0

    try:
        import boto3
    except ImportError:
        print("boto3 is required to --apply.", file=sys.stderr)
        return 2

    client = boto3.client("bedrock", region_name=args.region)
    client.put_model_invocation_logging_configuration(loggingConfig=logging_config)
    print(
        "\nApplied. Verify with: aws bedrock get-model-invocation-logging-configuration --region",
        args.region,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
