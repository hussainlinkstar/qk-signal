#!/usr/bin/env python3
"""EPIC 13 / Phase 3 — submit a Bedrock Model Distillation job from invocation logs.

Distils a smaller "student" model from the teacher (Claude Sonnet 4.5) using
production invocation logs FILTERED by the requestMetadata use_case that
core/bedrock_metadata tags every call with (e.g. ``audit_expert_seo``,
``pre_scan``). This is how each domain gets its own cheaper/faster expert.

SAFETY: defaults to a DRY RUN (prints the create_model_customization_job params,
makes no AWS call — a real job incurs training cost). Pass --apply to submit.
Requires bedrock:CreateModelCustomizationJob + an S3 read/write role.

Usage:
  python scripts/signal_submit_distillation.py \
      --use-case audit_expert_seo \
      --student-model amazon.nova-lite-v1:0 \
      --logs-s3-uri s3://qiko-signal-bedrock-logs/bedrock-invocation-logs/AWSLogs \
      --output-s3-uri s3://qiko-signal-distillation/output/ \
      --role-arn arn:aws:iam::ACCOUNT:role/BedrockDistillation [--teacher-model ...] [--region eu-north-1] [--apply]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

DEFAULT_TEACHER = os.getenv("BEDROCK_SMART_MODEL", "eu.amazon.nova-pro-v1:0")


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


def build_job_kwargs(args) -> dict:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_use_case = args.use_case.replace("/", "-").replace(":", "-")
    job_name = args.job_name or f"signal-distill-{safe_use_case}-{stamp}"
    model_name = args.model_name or f"signal-expert-{safe_use_case}-{stamp}"
    return {
        "jobName": job_name,
        "customModelName": model_name,
        "roleArn": args.role_arn,
        "baseModelIdentifier": args.student_model,
        "customizationType": "DISTILLATION",
        "trainingDataConfig": {
            "invocationLogsConfig": {
                "usePromptResponse": True,
                "invocationLogSource": {"s3Uri": args.logs_s3_uri},
                "requestMetadataFilters": {"equals": {"use_case": args.use_case}},
            }
        },
        "outputDataConfig": {"s3Uri": args.output_s3_uri},
        "customizationConfig": {
            "distillationConfig": {
                "teacherModelConfig": {
                    "teacherModelIdentifier": args.teacher_model,
                    "maxResponseLengthForInference": args.max_response_length,
                }
            }
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Submit a Bedrock distillation job from invocation logs (EPIC 13 phase 3)."
    )
    parser.add_argument(
        "--use-case",
        required=True,
        help="requestMetadata use_case to filter logs (e.g. audit_expert_seo).",
    )
    parser.add_argument(
        "--student-model",
        required=True,
        help="Base model id for the student (e.g. amazon.nova-lite-v1:0).",
    )
    parser.add_argument(
        "--logs-s3-uri", required=True, help="S3 URI of the invocation logs (…/AWSLogs)."
    )
    parser.add_argument("--output-s3-uri", required=True, help="S3 URI for job output/metrics.")
    parser.add_argument(
        "--role-arn", required=True, help="IAM role for Bedrock to read logs / write output."
    )
    parser.add_argument(
        "--teacher-model",
        default=DEFAULT_TEACHER,
        help="Teacher model id (default: current BEDROCK_SMART_MODEL).",
    )
    parser.add_argument(
        "--max-response-length", type=int, default=2048, help="Max teacher response length."
    )
    parser.add_argument("--job-name", default=None, help="Override the generated job name.")
    parser.add_argument(
        "--model-name", default=None, help="Override the generated custom model name."
    )
    parser.add_argument("--region", default=_default_bedrock_region(), help="Bedrock region.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually submit the job (default: dry run; a real job costs money).",
    )
    args = parser.parse_args(argv)

    job_kwargs = build_job_kwargs(args)
    print(f"[region={args.region}] create_model_customization_job(")
    print(json.dumps(job_kwargs, indent=2))
    print(")")

    if not args.apply:
        print("\nDRY RUN — no AWS call made. Re-run with --apply to submit (incurs training cost).")
        return 0

    try:
        import boto3
    except ImportError:
        print("boto3 is required to --apply.", file=sys.stderr)
        return 2

    client = boto3.client("bedrock", region_name=args.region)
    response = client.create_model_customization_job(**job_kwargs)
    print("\nSubmitted. jobArn=", response.get("jobArn"))
    print(
        "Track with: aws bedrock get-model-customization-job --job-identifier <jobArn> --region",
        args.region,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
