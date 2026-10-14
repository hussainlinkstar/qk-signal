# AWS Migration Plan — Qiko Signal Platform

> **Version:** 1.0  
> **Prepared:** May 2026  
> **Scope:** Full infrastructure migration from Hetzner VPS to AWS

---

## Table of Contents

1. [Current State](#1-current-state)
2. [Target AWS Architecture](#2-target-aws-architecture)
3. [Region Selection](#3-region-selection)
4. [Phase 0 — Prerequisites](#phase-0--prerequisites)
5. [Phase 1 — Networking (VPC)](#phase-1--networking-vpc)
6. [Phase 2 — Secrets Migration (GCP → AWS)](#phase-2--secrets-migration-gcp--aws)
7. [Phase 3 — Storage Migration (GCS → S3)](#phase-3--storage-migration-gcs--s3)
8. [Phase 4 — Database Migration (PostgreSQL)](#phase-4--database-migration-postgresql)
9. [Phase 5 — Compute Migration (15 Containers)](#phase-5--compute-migration-15-containers)
10. [Phase 6 — CI/CD Pipeline (GitHub Actions + ECR)](#phase-6--cicd-pipeline-github-actions--ecr)
11. [Phase 7 — DNS Cutover (Cloudflare → AWS)](#phase-7--dns-cutover-cloudflare--aws)
12. [Phase 8 — Monitoring (CloudWatch + Sentry)](#phase-8--monitoring-cloudwatch--sentry)
13. [Phase 9 — Cleanup](#phase-9--cleanup)
14. [Cost Estimate](#cost-estimate)
15. [Risk Register](#risk-register)

---

## 1. Current State

### Infrastructure

| Component | Current | Specs |
|---|---|---|
| **Host** | Hetzner CX43 VPS | 8 vCPU, 16 GB RAM, 160 GB SSD |
| **OS** | Ubuntu 24.04 LTS | — |
| **Reverse proxy (external)** | Traefik v3.6 | HTTPS via Let's Encrypt |
| **Reverse proxy (internal)** | Caddy 2.8 | Security headers, gzip |
| **Containers** | Docker Compose | 15 services |
| **Database** | PostgreSQL 18 | 102 MB data, Docker volume |
| **Cache** | Redis 8 | Docker volume |
| **Object storage** | Google Cloud Storage | `qiko.ai` bucket — reports + logos |
| **Secrets** | GCP Secret Manager | `GSM_ENABLED=true`, project `thothgraph` |
| **DNS / CDN** | Cloudflare | DNS + custom hostname white-label feature |
| **SSL** | Let's Encrypt (auto via Traefik) | — |

### Container Memory Map

| Container | Memory Limit | CPU Limit | Role |
|---|---|---|---|
| `backend` | 512 MB | 1.0 | FastAPI + SQLAlchemy |
| `frontend` | 256 MB | 0.5 | Next.js 15 |
| `audit-worker` | 1 GB | 1.5 | Core SEO/AEO/GEO audit engine |
| `ai-service` | 512 MB | 1.0 | AI provider orchestration |
| `pdf-worker` | 512 MB | 1.0 | WeasyPrint PDF generation |
| `visibility-worker` | 512 MB | 1.0 | Visibility/indexing tracking |
| `email-worker` | 256 MB | 0.5 | SMTP email sending |
| `billing-webhook-worker` | 256 MB | 0.5 | Stripe billing webhooks |
| `external-webhook-worker` | 256 MB | 0.5 | External webhook handling |
| `monitoring-worker` | 256 MB | 0.5 | Site monitoring |
| `performance-worker` | 256 MB | 0.5 | Performance tracking |
| `cron-sweeper` | 256 MB | 0.5 | Scheduled cron tasks |
| `caddy` | 128 MB | — | Internal reverse proxy |
| `db` | 512 MB | — | PostgreSQL 18 |
| `redis` | 128 MB | — | Redis 8 |
| **Total** | **~5.5 GB** | **~9 vCPU** | — |

### Third-Party Services (stay as-is)

| Service | Provider | Action |
|---|---|---|
| Stripe | Stripe | No change — API keys move to AWS Secrets Manager |
| Email | SMTP (Gmail) | No change |
| OpenAI / Anthropic / Google Gemini | Cloud AI | No change |
| Firecrawl / SerpAPI / Bing | APIs | No change |
| Sentry | Sentry.io | No change — keep for app error tracking |
| Cloudflare | Cloudflare | **Keep** — DNS + custom hostname white-label feature |

---

## 2. Target AWS Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Cloudflare DNS (keep)                                          │
│  qiko.ai → ALB                                          │
└───────────────────────┬─────────────────────────────────────────┘
                        │ HTTPS (ACM cert)
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  AWS Application Load Balancer (ALB)                           │
│  + ACM SSL Certificate (qiko.ai + *.qiko.ai)     │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  VPC — Private/Public subnets (2 AZs minimum)                  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  ECS Cluster (EC2 or Fargate — buyer decides)            │  │
│  │                                                          │  │
│  │  Task Groups:                                            │  │
│  │  ├── frontend (Next.js)                                  │  │
│  │  ├── backend (FastAPI)                                   │  │
│  │  ├── caddy (reverse proxy)                               │  │
│  │  ├── ai-service                                          │  │
│  │  ├── audit-worker                                        │  │
│  │  ├── pdf-worker                                          │  │
│  │  ├── email-worker                                        │  │
│  │  ├── billing-webhook-worker                              │  │
│  │  ├── external-webhook-worker                             │  │
│  │  ├── monitoring-worker                                   │  │
│  │  ├── visibility-worker                                   │  │
│  │  ├── performance-worker                                  │  │
│  │  └── cron-sweeper                                        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─────────────────┐    ┌──────────────────┐                   │
│  │  RDS PostgreSQL │    │  ElastiCache     │                   │
│  │  (or EC2 Docker)│    │  Redis           │                   │
│  └─────────────────┘    │  (or EC2 Docker) │                   │
│                         └──────────────────┘                   │
│  ┌──────────────────────────────────────────┐                  │
│  │  S3 Bucket: thothgraph-storage           │                  │
│  │  ├── reports/   (PDF audit reports)      │                  │
│  │  └── logos/     (user uploaded logos)    │                  │
│  └──────────────────────────────────────────┘                  │
│                                                                 │
│  ┌──────────────────────────────────────────┐                  │
│  │  AWS Secrets Manager                     │                  │
│  │  (replaces GCP Secret Manager)           │                  │
│  └──────────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘

CI/CD:
GitHub → GitHub Actions → ECR (Docker images) → ECS Deploy
```

---

## 3. Region Selection

**Recommended options — buyer decides:**

| Region | Code | Latency from Dubai | Notes |
|---|---|---|---|
| **Bahrain** ⭐ | `me-south-1` | ~20 ms | Closest to Dubai. Fewer managed services but sufficient. |
| **Ireland** | `eu-west-1` | ~120 ms | GDPR-friendly, mature, cheaper |
| **Frankfurt** | `eu-central-1` | ~120 ms | GDPR, Germany, stable |
| **UAE** | `me-central-1` | ~10 ms | AWS UAE (launched 2022) — most expensive, newer |

> **Recommendation:** If serving primarily UAE/GCC customers → `me-south-1` (Bahrain) or `me-central-1` (UAE).  
> If GDPR compliance is primary concern → `eu-west-1` (Ireland).

---

## Phase 0 — Prerequisites

**Estimated time: 1 day**

### AWS Account Setup

```bash
# 1. Create AWS account at aws.amazon.com
# 2. Enable MFA on root account
# 3. Create IAM admin user (never use root for operations)
# 4. Install AWS CLI
brew install awscli          # macOS
pip install awscli           # Linux

# 5. Configure credentials
aws configure
# AWS Access Key ID: [IAM user key]
# AWS Secret Access Key: [IAM user secret]
# Default region: me-south-1  (or your chosen region)
# Default output format: json

# 6. Verify
aws sts get-caller-identity
```

### Required IAM Permissions

Create an IAM role `thothgraph-deploy` with:
- `AmazonECS_FullAccess`
- `AmazonEC2ContainerRegistryFullAccess`
- `AmazonRDSFullAccess`
- `AmazonElastiCacheFullAccess`
- `AmazonS3FullAccess`
- `SecretsManagerReadWrite`
- `CloudWatchFullAccess`
- `ElasticLoadBalancingFullAccess`
- `AmazonVPCFullAccess`

### Tools to Install

```bash
# AWS CLI (already above)
# Docker (already installed)
# Terraform (optional but recommended for IaC)
brew install terraform

# ECS CLI (for ECS-specific operations)
brew install amazon-ecs-cli
```

---

## Phase 1 — Networking (VPC)

**Estimated time: 2-4 hours**

```bash
# Create VPC with Terraform or AWS Console

# VPC CIDR: 10.0.0.0/16
# Public subnets (for ALB): 10.0.1.0/24, 10.0.2.0/24  (2 AZs)
# Private subnets (for ECS, RDS): 10.0.10.0/24, 10.0.11.0/24 (2 AZs)

# Security Groups:
# sg-alb: inbound 80, 443 from 0.0.0.0/0
# sg-ecs: inbound 8000 (backend), 3000 (frontend), 80 (caddy) from sg-alb
# sg-rds: inbound 5432 from sg-ecs
# sg-redis: inbound 6379 from sg-ecs
```

### Terraform VPC (recommended)

```hcl
# infrastructure/vpc.tf
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "thothgraph-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["me-south-1a", "me-south-1b"]
  public_subnets  = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnets = ["10.0.10.0/24", "10.0.11.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true  # cost saving; use false for HA

  tags = { Project = "thothgraph" }
}
```

---

## Phase 2 — Secrets Migration (GCP → AWS Secrets Manager)

**Estimated time: 1-2 days**

### 2.1 Export All Secrets from GCP

```bash
# On current server — list all secrets
gcloud secrets list --project=thothgraph --format="value(name)"

# Export values (run for each secret)
gcloud secrets versions access latest \
  --secret=DATABASE_URL \
  --project=thothgraph
```

### 2.2 Create Secrets in AWS Secrets Manager

```bash
# Create each secret in AWS (example for DATABASE_URL)
aws secretsmanager create-secret \
  --name "thothgraph/production/DATABASE_URL" \
  --secret-string "postgresql://user:password@rds-endpoint:5432/dbname" \
  --region me-south-1

# Or batch create using a script:
```

```python
# scripts/migrate_secrets_to_aws.py
import boto3
import subprocess
import json

SECRETS = [
    "DATABASE_URL", "REDIS_URL", "JWT_SECRET_KEY", "JWT_REFRESH_SECRET_KEY",
    "SESSION_SECRET_KEY", "OAUTH_TOKEN_ENCRYPTION_KEY",
    "STRIPE_SECRET_KEY_LIVE", "STRIPE_WEBHOOK_SECRET_LIVE",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
    "SMTP_PASSWORD", "FIRECRAWL_API_KEY", "SERPAPI_API_KEY",
    "SENTRY_DSN", "CLOUDFLARE_API_TOKEN",
    "GCS_BUCKET_NAME",  # will become S3_BUCKET_NAME
]

client = boto3.client("secretsmanager", region_name="me-south-1")

for secret_name in SECRETS:
    # Get value from GCP (requires gcloud auth)
    result = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret", secret_name, "--project", "thothgraph"],
        capture_output=True, text=True
    )
    value = result.stdout.strip()
    if not value:
        print(f"SKIP (empty): {secret_name}")
        continue

    aws_name = f"thothgraph/production/{secret_name}"
    client.create_secret(Name=aws_name, SecretString=value)
    print(f"Created: {aws_name}")
```

### 2.3 Update env_bootstrap.py for AWS Secrets Manager

The file `backend/core/env_bootstrap.py` currently loads from GCP Secret Manager. Refactor it to support AWS:

```python
# backend/core/env_bootstrap.py — ADD AWS support

def _load_from_aws_secrets_manager(prefix: str = "thothgraph/production/"):
    """Load secrets from AWS Secrets Manager."""
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("secretsmanager")
    # List all secrets with the thothgraph/production/ prefix
    paginator = client.get_paginator("list_secrets")
    for page in paginator.paginate(
        Filters=[{"Key": "name", "Values": [prefix]}]
    ):
        for secret in page["SecretList"]:
            secret_name = secret["Name"]
            env_key = secret_name.replace(prefix, "")
            try:
                value = client.get_secret_value(SecretId=secret_name)
                os.environ.setdefault(env_key, value["SecretString"])
            except ClientError:
                pass

def bootstrap_environment():
    provider = os.environ.get("SECRETS_PROVIDER", "gsm")  # gsm | aws | env
    if provider == "aws":
        _load_from_aws_secrets_manager()
    elif provider == "gsm":
        _load_from_gsm()  # existing GCP implementation
    # else: use .env only
```

**Environment variable to add to `.env`:**
```bash
SECRETS_PROVIDER=aws   # gsm | aws | env
```

---

## Phase 3 — Storage Migration (GCS → S3)

**Estimated time: 1 day**

### 3.1 Create S3 Bucket

```bash
# Create bucket
aws s3api create-bucket \
  --bucket thothgraph-storage \
  --region me-south-1 \
  --create-bucket-configuration LocationConstraint=me-south-1

# Enable versioning (optional but recommended)
aws s3api put-bucket-versioning \
  --bucket thothgraph-storage \
  --versioning-configuration Status=Enabled

# Block public access
aws s3api put-public-access-block \
  --bucket thothgraph-storage \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,\
    BlockPublicPolicy=true,RestrictPublicBuckets=true
```

### 3.2 Migrate Existing Files from GCS

```bash
# Install gsutil (if not installed)
pip install google-cloud-storage boto3

# Migration script
python3 << 'EOF'
from google.cloud import storage as gcs
import boto3

gcs_client = gcs.Client(project="thothgraph")
s3_client  = boto3.client("s3", region_name="me-south-1")

bucket = gcs_client.bucket("qiko.ai")
s3_bucket = "thothgraph-storage"

for blob in bucket.list_blobs():
    data = blob.download_as_bytes()
    s3_client.put_object(
        Bucket=s3_bucket,
        Key=blob.name,
        Body=data,
        ContentType=blob.content_type or "application/octet-stream",
    )
    print(f"Migrated: {blob.name}")
EOF
```

### 3.3 Update Application Code

Replace GCS client with S3 in the backend storage service:

```python
# backend/services/storage_service.py — replace GCS with S3

import boto3

class S3StorageService:
    def __init__(self):
        self.client = boto3.client(
            "s3",
            region_name=os.environ["AWS_REGION"],
        )
        self.bucket = os.environ["S3_BUCKET_NAME"]

    def upload(self, key: str, data: bytes, content_type: str) -> str:
        self.client.put_object(
            Bucket=self.bucket, Key=key,
            Body=data, ContentType=content_type
        )
        return f"s3://{self.bucket}/{key}"

    def get_signed_url(self, key: str, expiry_seconds: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expiry_seconds,
        )
```

**New environment variables:**
```bash
S3_BUCKET_NAME=thothgraph-storage
AWS_REGION=me-south-1
# AWS credentials via IAM role (preferred) — no keys in .env
```

---

## Phase 4 — Database Migration (PostgreSQL)

**Estimated time: 4-8 hours**

### Option A — RDS PostgreSQL (Recommended for Production)

```bash
# Create RDS instance
aws rds create-db-instance \
  --db-instance-identifier thothgraph-db \
  --db-instance-class db.t3.medium \
  --engine postgres \
  --engine-version 18 \
  --master-username thothgraph \
  --master-user-password "$(openssl rand -base64 32)" \
  --allocated-storage 20 \
  --storage-type gp3 \
  --vpc-security-group-ids sg-rds \
  --db-subnet-group-name thothgraph-private \
  --backup-retention-period 7 \
  --deletion-protection \
  --no-publicly-accessible \
  --region me-south-1
```

### Option B — PostgreSQL in Docker on EC2 (Simple Migration)

Keep PostgreSQL in a Docker container on EC2, identical to current setup. Attach a separate EBS volume for data persistence.

```bash
# EBS volume for PostgreSQL data
aws ec2 create-volume \
  --availability-zone me-south-1a \
  --size 50 \
  --volume-type gp3 \
  --region me-south-1
```

### Data Migration (both options)

```bash
# 1. On current Hetzner server — dump database
docker exec thothgraph-db-1 \
  pg_dump -U user dbname --no-owner --no-acl \
  > thothgraph_$(date +%Y%m%d).sql

# 2. Transfer to AWS (via S3)
aws s3 cp thothgraph_$(date +%Y%m%d).sql \
  s3://thothgraph-storage/backups/

# 3. On AWS — restore
psql -h <rds-endpoint> -U thothgraph -d postgres \
  -c "CREATE DATABASE dbname;"

psql -h <rds-endpoint> -U thothgraph -d dbname \
  < thothgraph_$(date +%Y%m%d).sql
```

---

## Phase 5 — Compute Migration (15 Containers)

**Estimated time: 2-5 days**

### 5.1 ECR — Container Registry

```bash
# Create ECR repositories for each service
for SERVICE in backend frontend ai-service audit-worker pdf-worker \
  email-worker billing-webhook-worker external-webhook-worker \
  monitoring-worker visibility-worker performance-worker cron-sweeper caddy; do
  aws ecr create-repository \
    --repository-name thothgraph/$SERVICE \
    --region me-south-1
done

# Login to ECR
aws ecr get-login-password --region me-south-1 | \
  docker login --username AWS \
  --password-stdin 123456789.dkr.ecr.me-south-1.amazonaws.com
```

### 5.2 Build and Push Images

```bash
ACCOUNT=123456789
REGION=me-south-1
REGISTRY=$ACCOUNT.dkr.ecr.$REGION.amazonaws.com

# Build and push backend
docker build -t $REGISTRY/thothgraph/backend:latest ./backend
docker push $REGISTRY/thothgraph/backend:latest

# Build and push frontend
docker build -t $REGISTRY/thothgraph/frontend:latest ./frontend
docker push $REGISTRY/thothgraph/frontend:latest

# Repeat for all services...
```

### 5.3 ECS Cluster Setup

**Option A — Fargate (Serverless):**
```bash
aws ecs create-cluster \
  --cluster-name thothgraph \
  --capacity-providers FARGATE FARGATE_SPOT \
  --region me-south-1
```

**Option B — EC2 (Docker Compose on EC2 — simplest migration):**
```bash
# Launch EC2 instance (t3.xlarge: 4 vCPU, 16GB — matches current Hetzner)
aws ec2 run-instances \
  --image-id ami-xxxxxxxx  # Amazon Linux 2023 AMI for me-south-1 \
  --instance-type t3.xlarge \
  --key-name thothgraph-key \
  --security-group-ids sg-ecs \
  --subnet-id subnet-private \
  --iam-instance-profile Arn=arn:aws:iam::123456789:instance-profile/thothgraph-ec2 \
  --user-data file://scripts/ec2-user-data.sh \
  --region me-south-1

# ec2-user-data.sh: installs Docker, Docker Compose, clones repo, starts stack
```

### 5.4 Task Definitions (ECS Fargate)

Create ECS Task Definition for each service. Example for backend:

```json
{
  "family": "thothgraph-backend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::123456789:role/thothgraph-ecs-execution",
  "containerDefinitions": [
    {
      "name": "backend",
      "image": "123456789.dkr.ecr.me-south-1.amazonaws.com/thothgraph/backend:latest",
      "portMappings": [{"containerPort": 8000}],
      "secrets": [
        {"name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:me-south-1:123456789:secret:thothgraph/production/DATABASE_URL"},
        {"name": "JWT_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:me-south-1:123456789:secret:thothgraph/production/JWT_SECRET_KEY"}
      ],
      "environment": [
        {"name": "SECRETS_PROVIDER", "value": "aws"},
        {"name": "AWS_REGION", "value": "me-south-1"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/thothgraph",
          "awslogs-region": "me-south-1",
          "awslogs-stream-prefix": "backend"
        }
      }
    }
  ]
}
```

---

## Phase 6 — CI/CD Pipeline (GitHub Actions + ECR)

**Estimated time: 1 day**

### 6.1 GitHub Secrets to Configure

In GitHub → Settings → Secrets → Actions:

```
AWS_ACCESS_KEY_ID       → IAM deploy user key
AWS_SECRET_ACCESS_KEY   → IAM deploy user secret
AWS_REGION              → me-south-1
ECR_REGISTRY            → 123456789.dkr.ecr.me-south-1.amazonaws.com
ECS_CLUSTER             → thothgraph
```

### 6.2 GitHub Actions Workflow

```yaml
# .github/workflows/deploy.yml
name: Deploy to AWS

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ secrets.AWS_REGION }}

      - name: Login to ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build and push backend
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/thothgraph/backend:$IMAGE_TAG ./backend
          docker push $ECR_REGISTRY/thothgraph/backend:$IMAGE_TAG
          docker tag $ECR_REGISTRY/thothgraph/backend:$IMAGE_TAG \
                     $ECR_REGISTRY/thothgraph/backend:latest
          docker push $ECR_REGISTRY/thothgraph/backend:latest

      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster thothgraph \
            --service thothgraph-backend \
            --force-new-deployment \
            --region ${{ secrets.AWS_REGION }}
```

---

## Phase 7 — DNS Cutover (Cloudflare → AWS)

**Estimated time: 30 minutes (+ propagation)**

### 7.1 Pre-Cutover Checklist

- [ ] ALB is healthy and serving traffic on AWS
- [ ] SSL certificate issued via ACM for `qiko.ai` + `*.qiko.ai`
- [ ] All 15 containers running healthy on AWS
- [ ] Database replication confirmed (data matches)
- [ ] Redis warmed up on AWS
- [ ] Secrets verified accessible from AWS containers
- [ ] Smoke test passed (run `scripts/prod-audit-3flows.sh` against AWS endpoint)

### 7.2 ALB Setup

```bash
# Create ALB
aws elbv2 create-load-balancer \
  --name thothgraph-alb \
  --subnets subnet-public-1 subnet-public-2 \
  --security-groups sg-alb \
  --region me-south-1

# Request ACM certificate
aws acm request-certificate \
  --domain-name qiko.ai \
  --subject-alternative-names "*.qiko.ai" \
  --validation-method DNS \
  --region me-south-1
  # Then add CNAME validation record in Cloudflare
```

### 7.3 Cloudflare DNS Update

In Cloudflare DNS panel:

```
BEFORE:  qiko.ai A → 135.181.35.234 (Hetzner)
AFTER:   qiko.ai CNAME → thothgraph-alb-123.me-south-1.elb.amazonaws.com
```

> **Note:** Set TTL to 60s before cutover, restore to 300s after.

> **Important:** The Cloudflare custom hostname feature (white-label CNAME for clients) is preserved — it points to Cloudflare, which then routes to AWS ALB. No changes needed to the custom domain flow.

---

## Phase 8 — Monitoring (CloudWatch + Sentry)

**Estimated time: 4 hours**

### 8.1 CloudWatch Setup

```bash
# Create log groups
aws logs create-log-group --log-group-name /ecs/thothgraph --region me-south-1

# Container Insights for ECS
aws ecs put-account-setting \
  --name containerInsights \
  --value enabled \
  --region me-south-1

# Create dashboard
aws cloudwatch put-dashboard \
  --dashboard-name Qiko Signal \
  --dashboard-body file://infrastructure/cloudwatch-dashboard.json
```

### 8.2 Alarms to Create

```bash
# Backend CPU > 80%
aws cloudwatch put-metric-alarm \
  --alarm-name "thothgraph-backend-cpu-high" \
  --metric-name CPUUtilization \
  --namespace AWS/ECS \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions arn:aws:sns:me-south-1:123456789:thothgraph-alerts

# RDS CPU > 70%
# ALB 5xx error rate > 1%
# ElastiCache memory > 80%
```

### 8.3 Sentry (no changes)

Sentry DSN remains the same — just update `SENTRY_DSN` in AWS Secrets Manager.

---

## Phase 9 — Cleanup

**Estimated time: After 2 weeks stable on AWS**

1. **Keep Hetzner running 2 weeks** as hot standby — do not delete
2. Verify zero traffic hitting Hetzner (check Traefik logs)
3. Delete GCP Secret Manager secrets (after confirming AWS works)
4. Delete GCS bucket (after confirming S3 migration complete)
5. Cancel GCP project billing
6. Cancel Hetzner CX43 server

---

## Cost Estimate

### AWS Monthly Cost (approximate)

| Service | Spec | Monthly USD |
|---|---|---|
| **EC2 t3.xlarge** (compute) | 4 vCPU, 16 GB | ~$120 |
| **RDS db.t3.medium** (PostgreSQL) | 2 vCPU, 4 GB | ~$55 |
| **ElastiCache cache.t3.micro** (Redis) | 1 vCPU, 1 GB | ~$15 |
| **S3** (storage + requests) | ~5 GB | ~$5 |
| **ECR** (container images) | ~10 GB | ~$10 |
| **ALB** (load balancer) | — | ~$20 |
| **ACM** (SSL certificates) | — | Free |
| **Secrets Manager** (20 secrets) | — | ~$8 |
| **CloudWatch** (logs + metrics) | — | ~$15 |
| **NAT Gateway** | — | ~$35 |
| **Data transfer out** | ~50 GB/mo | ~$5 |
| **Total** | | **~$290–$350/mo** |

> **vs Hetzner current:** ~$50/month  
> **Delta:** +$240–300/month for managed AWS infrastructure

> **Cost optimization options:**
> - Use EC2 Reserved Instances (1 year): save ~40% on EC2 + RDS
> - Use ECS Fargate Spot for non-critical workers: save ~70% on worker tasks
> - Use S3 Intelligent-Tiering for older reports
> - Estimated with RI + Spot: **~$180–220/month**

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Database migration data loss | Low | Critical | Full dump + verify row counts before cutover |
| env_bootstrap.py refactor breaks secrets loading | Medium | High | Test in staging environment first |
| GCS → S3 missing files | Low | Medium | Verify file counts before and after migration |
| DNS propagation delay | Low | Medium | Set TTL to 60s 24h before cutover |
| Cloudflare custom hostname feature breaks | Low | High | Test custom domain flow on AWS before cutover |
| Higher AWS costs than estimated | Medium | Low | Set AWS billing alerts at $300/month |
| ECS container networking issues | Medium | High | Test all inter-service communication in staging |
| Redis data loss during migration | Low | Medium | Redis data is cache only — safe to flush and rebuild |

---

## Migration Checklist Summary

### Phase 0 — Prerequisites
- [ ] AWS account created, MFA enabled
- [ ] IAM user + role created with correct permissions
- [ ] AWS CLI configured and tested

### Phase 1 — Networking
- [ ] VPC created (public + private subnets, 2 AZs)
- [ ] Security groups configured
- [ ] NAT Gateway deployed

### Phase 2 — Secrets
- [ ] All secrets listed in GCP Secret Manager
- [ ] All secrets created in AWS Secrets Manager
- [ ] `env_bootstrap.py` updated for AWS provider
- [ ] `SECRETS_PROVIDER=aws` tested locally

### Phase 3 — Storage
- [ ] S3 bucket created and configured
- [ ] GCS → S3 migration script run
- [ ] File counts verified (GCS = S3)
- [ ] Storage service code updated (GCS → S3)
- [ ] Signed URL generation tested

### Phase 4 — Database
- [ ] RDS instance created (or EC2 EBS volume attached)
- [ ] PostgreSQL dump taken from Hetzner
- [ ] Dump restored to AWS RDS
- [ ] Row counts verified
- [ ] Alembic migration state verified

### Phase 5 — Compute
- [ ] ECR repositories created for all 15 services
- [ ] Docker images built and pushed to ECR
- [ ] ECS cluster created
- [ ] Task definitions created for all services
- [ ] Services deployed and healthy
- [ ] All 15 containers showing healthy status

### Phase 6 — CI/CD
- [ ] GitHub secrets configured
- [ ] `.github/workflows/deploy.yml` created and tested
- [ ] Test push triggers ECR build + ECS deploy

### Phase 7 — DNS Cutover
- [ ] ACM certificate issued and validated
- [ ] ALB created and attached to ECS services
- [ ] Smoke test passed on AWS endpoint
- [ ] Cloudflare DNS TTL reduced to 60s
- [ ] DNS record updated to ALB
- [ ] Traffic confirmed on AWS (zero on Hetzner)

### Phase 8 — Monitoring
- [ ] CloudWatch log groups created
- [ ] Container Insights enabled
- [ ] CloudWatch alarms configured
- [ ] SNS topic for alerts created
- [ ] Sentry DSN updated in AWS Secrets Manager

### Phase 9 — Cleanup
- [ ] 2 weeks stable on AWS confirmed
- [ ] GCP Secret Manager secrets deleted
- [ ] GCS bucket confirmed empty and deleted
- [ ] GCP project billing cancelled
- [ ] Hetzner server cancelled

---

*Document maintained in `ROADMAP/AWS-MIGRATION.md` — update as decisions are finalised.*
