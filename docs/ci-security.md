# CI/CD Security Gates

> SEC-03 implementation reference. Updated 2026-03-16.

## Overview

The CI pipeline includes a **Security Scanning** job that runs in parallel with
Backend CI and Frontend CI. All three must pass before the `ci-status` gate
reports green. The Docker publish workflow adds container-level scanning and
SBOM generation after image push.

## CI Security Job (`.github/workflows/ci.yml`)

| Step | Tool | What it checks | Failure mode |
|---|---|---|---|
| Secret scanning | **gitleaks** v2 | Hard-coded secrets, API keys, tokens in full git history | Blocks merge |
| Python dep audit | **pip-audit** | Known CVEs in `requirements.txt` + `requirements-dev.txt` | Blocks merge (`--strict`) |
| Filesystem scan (backend) | **Trivy** fs | CRITICAL/HIGH CVEs in Python packages | Blocks merge |
| Filesystem scan (frontend) | **Trivy** fs | CRITICAL/HIGH CVEs in npm packages | Blocks merge |
| IaC / config scan | **Trivy** config | Dockerfile + Compose misconfigurations | Advisory (exit 0) |
| Dockerfile lint (backend) | **Hadolint** | Dockerfile best-practice violations | Blocks at `warning` threshold |
| Dockerfile lint (frontend) | **Hadolint** | Dockerfile best-practice violations | Blocks at `warning` threshold |

## Docker Publish Scanning (`.github/workflows/docker-publish.yml`)

After each matrix image (backend, frontend) is built, pushed, and cosign-signed:

| Step | Tool | What it checks | Failure mode |
|---|---|---|---|
| Container scan | **Trivy** image | CRITICAL/HIGH CVEs in final image layers | Advisory (exit 0) |
| SBOM generation | **Trivy** CycloneDX | Full dependency inventory per image | Artifact retained 90 days |
| SBOM attachment | **cosign** attach | SBOM linked to image digest in registry | Non-blocking |

## Dependabot (`.github/dependabot.yml`)

Automated weekly PRs for:

- **pip** dependencies (`/backend`)
- **npm** dependencies (`/frontend`)
- **GitHub Actions** versions (`/`)
- **Docker** base images (`/backend`, `/frontend`)

## Configuration Files

| File | Purpose |
|---|---|
| `.gitleaks.toml` | Gitleaks allowlists and rule extensions |
| `.trivyignore` | CVE-level suppressions for Trivy (add with rationale comment) |
| `.github/dependabot.yml` | Dependabot schedule, ecosystems, and labels |

## Triaging Failures

### A dependency CVE blocks CI

1. Check if the CVE is fixable: `pip-audit --fix --dry-run` or `npm audit fix --dry-run`.
2. If a patch exists, update the dependency.
3. If no patch exists and the risk is accepted:
   - For Trivy: add the CVE to `.trivyignore` with a comment explaining the rationale.
   - For pip-audit: open an issue to track and re-check on next release.

### Gitleaks flags a false positive

1. Verify the finding is genuinely not a secret.
2. Add an allowlist entry in `.gitleaks.toml` (prefer path or regex patterns).
3. Re-run the scan locally: `gitleaks detect --source . -c .gitleaks.toml`.

### Hadolint warns on a Dockerfile

1. Review the rule at <https://github.com/hadolint/hadolint#rules>.
2. Fix the Dockerfile if possible.
3. If the warning is intentional, add an inline `# hadolint ignore=DLxxxx` comment.

### Container scan finds a CVE in a base image

Container scans are advisory (non-blocking) today. To fix:

1. Update the base image tag in the Dockerfile.
2. If the CVE is in the OS layer and unfixable, add it to `.trivyignore`.

## Running Locally

```bash
# Gitleaks
gitleaks detect --source . -c .gitleaks.toml -v

# pip-audit
pip-audit -r backend/requirements.txt -r backend/requirements-dev.txt --strict

# Trivy filesystem
trivy fs backend/ --severity CRITICAL,HIGH --ignore-unfixed
trivy fs frontend/ --severity CRITICAL,HIGH --ignore-unfixed

# Trivy config
trivy config . --severity CRITICAL,HIGH

# Hadolint
hadolint backend/Dockerfile
hadolint frontend/Dockerfile
```
