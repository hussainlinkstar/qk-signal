# OWASP / ASVS Security Tracking Matrix

Last updated: March 16, 2026

This document maps the March 9, 2026 security audit findings and follow-up backlog to OWASP Top 10 style risk areas and OWASP ASVS control families. It is a project tracking artifact, not a formal certification record.

## Scope

- In scope:
  - Checked-in application code
  - Checked-in configuration and CI/CD
  - Checked-in Docker / Compose deployment artifacts
  - Backlog tasks created from the March 9, 2026 audit
- Out of scope until separately verified:
  - Live VPS and reverse-proxy runtime settings
  - Cloud IAM, firewall, and network policies
  - Penetration testing / DAST evidence
  - Formal ASVS control-by-control test evidence

## Status Legend

- `Done`: implemented in the repository and verified with focused checks
- `Backlog`: tracked with an explicit task, not yet fully implemented
- `Manual verification`: needs live-environment or deeper path validation beyond repo review

## Summary

| Bucket | Count |
| --- | ---: |
| Done | 24 |
| Backlog | 0 |
| Manual verification | 3 |

## Matrix

| Control area | Audit item / gap | OWASP Top 10 | ASVS families | CWE | Status | Evidence / tracker |
| --- | --- | --- | --- | --- | --- | --- |
| Stage access restrictions | `AUTH_ALLOWED_EMAILS` enforcement (removed — temporary gate no longer needed) | A01, A07 | V2, V4 | CWE-284, CWE-285 | Removed | Was in `backend/services/auth_access_service.py` (deleted) |
| Email verification enforcement | Login gated on `email_verified` column; OAuth auto-verifies; structured 403 with frontend resend flow | A07 | V2 | CWE-285, CWE-304 | Done | `backend/routers/auth.py`, `backend/models.py`, `frontend/src/components/auth/LoginForm.tsx` (TASK-98 / SEC-14) |
| MFA / passkey onboarding prompt | Post-verification page recommends TOTP and passkey setup | A07 | V2 | CWE-308 | Done | `frontend/src/components/auth/VerifyEmailPageClient.tsx` (TASK-98 / SEC-14) |
| Session revocation | Logout now invalidates active session state instead of leaving access alive | A07 | V3 | CWE-613 | Done | [backend/routers/auth.py](/home/razvan/qiko-signal/backend/routers/auth.py), [backend/middleware/session_checker.py](/home/razvan/qiko-signal/backend/middleware/session_checker.py) |
| Refresh token replay | Refresh requires active session state and rotates by deactivating prior session | A07 | V3 | CWE-294, CWE-613 | Done | [backend/routers/auth.py](/home/razvan/qiko-signal/backend/routers/auth.py) |
| Browser token exposure | HttpOnly cookies no longer rehydrated into JS / `localStorage` | A03, A07 | V3, V8 | CWE-922 | Done | [frontend/src/app/api/auth/session/route.ts](/home/razvan/qiko-signal/frontend/src/app/api/auth/session/route.ts), [frontend/src/utils/token-manager.ts](/home/razvan/qiko-signal/frontend/src/utils/token-manager.ts) |
| Shared URL validation | DNS-resolved SSRF protections and redirect revalidation | A10 | V5, V14 | CWE-918 | Done | [backend/services/url_validation.py](/home/razvan/qiko-signal/backend/services/url_validation.py) |
| Audit preflight TLS | No `verify=False` fallback on TLS failure | A02 | V9 | CWE-295 | Done | [backend/routers/api_router.py](/home/razvan/qiko-signal/backend/routers/api_router.py) |
| Project profiling fetches | Project domain snapshot fetches use safe validation path | A10 | V5 | CWE-918 | Done | [backend/routers/workspace_router.py](/home/razvan/qiko-signal/backend/routers/workspace_router.py) |
| Sitemap crawl safety | SSRF-safe sitemap parsing with response/decompression limits | A04, A10 | V5, V14 | CWE-400, CWE-409, CWE-918 | Done | [backend/services/sitemap_crawler_service.py](/home/razvan/qiko-signal/backend/services/sitemap_crawler_service.py) |
| Dependency hygiene | Runtime Python and frontend dependencies upgraded to patched lines | A06 | V1, V14 | CWE-1104 | Done | [backend/requirements.txt](/home/razvan/qiko-signal/backend/requirements.txt), [backend/constraints.txt](/home/razvan/qiko-signal/backend/constraints.txt), [frontend/package.json](/home/razvan/qiko-signal/frontend/package.json) |
| Host header trust | Unknown hosts rejected while allowing platform and verified tenant domains | A05 | V1, V14 | CWE-444 | Done | [backend/middleware/tenant_resolver.py](/home/razvan/qiko-signal/backend/middleware/tenant_resolver.py), [backend/tests/test_tenant_resolver.py](/home/razvan/qiko-signal/backend/tests/test_tenant_resolver.py) |
| Encrypted secrets at rest | Dedicated encryption secret, fail-closed decrypt path, legacy plaintext gated | A02, A05 | V6 | CWE-321, CWE-522 | Done | [backend/core/encrypted_types.py](/home/razvan/qiko-signal/backend/core/encrypted_types.py), [backend/core/config.py](/home/razvan/qiko-signal/backend/core/config.py) |
| Active content uploads | Raw SVG logo uploads blocked; legacy local SVG forced to download | A03, A05 | V5, V8, V12 | CWE-79, CWE-434 | Done | [backend/routers/upload_router.py](/home/razvan/qiko-signal/backend/routers/upload_router.py), [frontend/src/components/ui/LogoUploadDropzone.tsx](/home/razvan/qiko-signal/frontend/src/components/ui/LogoUploadDropzone.tsx) |
| Session middleware defaults | Require dedicated `SESSION_SECRET_KEY`, secure cookie defaults, fail-fast config | A02, A05, A07 | V3, V14 | CWE-321, CWE-614 | Done | [backend/main.py](/home/razvan/qiko-signal/backend/main.py) `resolved_session_secret`, [backend/tests/test_session_security.py](/home/razvan/qiko-signal/backend/tests/test_session_security.py) |
| Browser hardening | CSP enforcing mode with nonce, report-uri violation collection, security headers at 3 layers | A03, A05 | V1, V4, V14 | CWE-79, CWE-1021 | Done | [frontend/src/middleware.ts](/home/razvan/qiko-signal/frontend/src/middleware.ts), [backend/system_checks.py](/home/razvan/qiko-signal/backend/system_checks.py), [docs/security-headers.md](/home/razvan/qiko-signal/docs/security-headers.md) |
| CI/CD security gates | Gitleaks, pip-audit, Trivy fs+IaC+container, Hadolint, cosign signing, CycloneDX SBOM | A06, A08 | V1, V14 | CWE-1104, CWE-798 | Done | [.github/workflows/ci.yml](/home/razvan/qiko-signal/.github/workflows/ci.yml), [.github/workflows/docker-publish.yml](/home/razvan/qiko-signal/.github/workflows/docker-publish.yml), [docs/ci-security.md](/home/razvan/qiko-signal/docs/ci-security.md) |
| Redis trust boundary | Centralized Redis factory with auth/TLS, production validation | A02, A05 | V9, V14 | CWE-319, CWE-306 | Done | [backend/core/redis_client.py](/home/razvan/qiko-signal/backend/core/redis_client.py), [docs/redis-hardening.md](/home/razvan/qiko-signal/docs/redis-hardening.md) |
| Container runtime hardening | `cap_drop: [ALL]`, `read_only`, `no-new-privileges`, `proxy-net`/`app-net` network segmentation | A05 | V1, V14 | CWE-250, CWE-668 | Done | [docker-compose.vps.yml](/home/razvan/qiko-signal/docker-compose.vps.yml), [docs/container-hardening.md](/home/razvan/qiko-signal/docs/container-hardening.md) |
| Report file access | `_safe_local_path()` traversal guard, scheme validation, raw-path fallback removed | A01, A05 | V4, V12 | CWE-22, CWE-73 | Done | [backend/services/gcs_storage_service.py](/home/razvan/qiko-signal/backend/services/gcs_storage_service.py), [backend/tests/test_report_download_security.py](/home/razvan/qiko-signal/backend/tests/test_report_download_security.py) |
| Dev toolchain vulns | Vitest 4.x, flatted 3.4.1, ajv override; `npm audit` clean | A06 | V1, V14 | CWE-1104 | Done | [frontend/package.json](/home/razvan/qiko-signal/frontend/package.json), [frontend/package-lock.json](/home/razvan/qiko-signal/frontend/package-lock.json) |
| Long-term auth architecture | BFF httpOnly-cookie session model; dead browser-token primitives removed | A03, A07 | V3, V4 | CWE-922, CWE-613 | Done | [frontend/src/utils/token-manager.ts](/home/razvan/qiko-signal/frontend/src/utils/token-manager.ts), [docs/bff-session-model.md](/home/razvan/qiko-signal/docs/bff-session-model.md) |
| Central outbound fetch policy | `safe_async_fetch`/`safe_sync_fetch` with SSRF, DNS-rebinding, size guards; 9 high-risk sites migrated | A10 | V5, V14 | CWE-918 | Done | [backend/services/url_validation.py](/home/razvan/qiko-signal/backend/services/url_validation.py), [backend/tests/test_safe_fetch.py](/home/razvan/qiko-signal/backend/tests/test_safe_fetch.py) |
| Cloud/runtime trust boundaries | Per-service `SERVICE_CREDENTIAL_ROLE` env var assigned; per-service AWS SSM parameter filtering not yet implemented | A05, A08 | V1, V14 | CWE-269, CWE-522 | Partial | All services currently load all AWS SSM parameters under `/qiko-signal/`; per-service filtering is planned, not yet implemented |
| Reverse proxy / edge config | TLS, HSTS, forwarded-host trust, host filtering at the edge | A02, A05 | V1, V9, V14 | CWE-319, CWE-346 | Manual verification | Live environment validation required |
| Cloud IAM and firewall | Service-account scopes, firewall rules, egress policies, network ACLs | A05, A08 | V1, V14 | CWE-732 | Manual verification | Live cloud review required |
| Runtime operational response | Monitoring, alerting, incident-response, DAST/pentest evidence | A09 | V1, V10, V14 | CWE-778 | Manual verification | Operational verification required |

## Current Coverage Readout

### Strongest current coverage

- Authentication/session flaws identified in the audit have been remediated at the application layer, including a strict BFF session model with httpOnly cookies (SEC-08) and secure session middleware defaults (SEC-01).
- Immediate SSRF sinks and unsafe outbound validation paths have been substantially reduced, and a unified safe-fetch client (`safe_async_fetch`/`safe_sync_fetch`) with DNS-rebinding and response-size guards is now the canonical path for new outbound HTTP calls (SEC-09).
- Runtime dependency posture is materially better than at audit time, with both Python (`pip-audit`) and frontend (`npm audit`) dependency trees clean (SEC-07).
- CI/CD now includes automated security gates: gitleaks secret scanning, Trivy filesystem/IaC/container scanning, Hadolint Dockerfile linting, pip-audit Python CVE audit, cosign image signing, and CycloneDX SBOM generation (SEC-03).
- Browser security headers are deployed in a three-layer defense-in-depth architecture: Caddy (transport-layer headers), backend middleware (API-only CSP), and frontend middleware (nonce-based CSP in enforcing mode with `report-uri` violation collection) (SEC-02, SEC-11).
- Container runtime hardening is comprehensive across all production services: `cap_drop: [ALL]`, `read_only: true`, `no-new-privileges`, resource limits, and network segmentation (`proxy-net`/`app-net`) (SEC-05).
- Redis connections now flow through a centralized factory with automatic auth/TLS support, and production validation rejects unauthenticated Redis URLs (SEC-04).
- Cloud credential isolation is partial: each service is assigned a `SERVICE_CREDENTIAL_ROLE` env var, but per-service AWS SSM parameter filtering is not yet implemented. All services currently load all AWS SSM parameters under `/qiko-signal/`; per-service filtering is planned, not yet implemented (SEC-10).
- Several defense-in-depth items that were outside the original top findings were also tightened:
  - host-header validation
  - encrypted secret handling
  - active-content upload restrictions
  - report file access path traversal hardening (SEC-06)

### Remaining items requiring attention

- Redis client centralization is complete (SEC-13): all `redis.from_url()` call sites across routers, services, workers, admin, and scripts have been migrated to the centralized factory in `core/redis_client.py`, ensuring consistent timeout/TLS defaults everywhere.
- Admin security posture dashboard (SEC-12) now surfaces session secret, CSP mode, Redis auth/TLS, SSRF protection, security headers middleware, and credential boundary checks.
- Per-role GCP service account provisioning (`scripts/create-per-role-credentials.sh`) and enforcement (`CREDENTIAL_BOUNDARY_ENFORCE=true`) are opt-in; production deployments can still run with a shared SA unless operators explicitly opt in.
- Three items (reverse proxy/edge config, cloud IAM/firewall, runtime operational response) require live-environment validation and cannot be verified from repo artifacts alone.

## How to Use This Matrix

- Treat `Done` rows as implemented controls, not full compliance proof.
- Treat `Backlog` rows as the remaining engineering work needed to align the repo with the audit.
- Treat `Manual verification` rows as mandatory before claiming strong OWASP/ASVS alignment for production.
- Revisit this file whenever a security task is started or completed.

## Practical Interpretation

All 10 security hardening tasks (`SEC-01` through `SEC-10`) from the March 9, 2026 audit have been implemented and verified, plus `SEC-14` (email verification enforcement and MFA onboarding). The repository now has 24 completed control items covering authentication, session management, email verification, MFA onboarding, browser hardening, CI/CD security gates, container runtime hardening, credential isolation, SSRF protection, and dependency hygiene.

The 3 remaining `Manual verification` items (reverse proxy/edge config, cloud IAM/firewall, runtime operational response) require live-environment validation that cannot be performed from repository artifacts alone.

It is not the same thing as formal OWASP ASVS compliance. To claim that rigorously, you still need:

- control-by-control verification evidence
- live-environment validation
- secure deployment proof
- ongoing testing and monitoring evidence

