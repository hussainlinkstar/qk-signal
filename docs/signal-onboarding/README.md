# Qiko Signal onboarding guide (SIGV2-1127)

Customer-facing, step-by-step onboarding guide for Qiko Signal. It follows the
same five steps, in the same order, as the approved in-app onboarding wizard.

## Contents

| File | What it is |
|---|---|
| `onboarding-guide.html` | The editable source. Edit this, never the PDF. |
| `Qiko-Signal-Onboarding-Guide.pdf` | The generated deliverable (10 pages, A4). |
| `build.sh` | One-command build. |
| `assets/qiko-logo.png` | Brand mark, copied from `qiko-signal/frontend/public/qiko-logo.png`. |
| `assets/fonts/` | Embedded fonts: Satoshi (display, copied from the app's own `src/app/fonts`), Inter (body) and Roboto Mono (labels). |

## Building

```bash
./build.sh
```

It renders with **WeasyPrint**, the same engine the product uses for its own PDF
reports (`qiko-signal/backend/requirements.txt` pins `weasyprint==70.0`). By
default it reuses the Signal backend virtualenv, which already has that pin:

```bash
# equivalent to what build.sh runs
../../qiko-signal/backend/.venv/bin/python -m weasyprint \
  onboarding-guide.html Qiko-Signal-Onboarding-Guide.pdf
```

Override the interpreter with `WEASYPRINT_PYTHON=/path/to/python ./build.sh` if
you have WeasyPrint installed elsewhere.

Fonts are embedded from `assets/fonts/`, so the build is offline and
deterministic and does not depend on what is installed on the machine.

## Visual system

Colour tokens, type scale, cover layout, section heads, card/verdict/pending
blocks and table styling are taken from the Signal PDF report source,
`Qiko-Signal-MVP-TBR/report-examples/report-source.html`, so the guide prints as
part of the same family as a real Signal report.

## Writing rules this document follows

- Scans are the only customer-facing unit. Credits are never mentioned.
- The scores are the **AIO score** and the **SEO score**.
- No em-dash (U+2014) anywhere in the source, the PDF or the commit message.
- Every factual claim is verified against the product as built (backend
  entitlements, product constants, shipped UI copy), not against the mockup.
  Plan entitlements come from `backend/app/config/plans.py` `CAPABILITY_MATRIX`.
- Nothing is promised that is not built. Where a wizard step leads somewhere
  incomplete or plan-gated, the guide says what actually happens.

## Sources of truth used

| Claim | Source |
|---|---|
| Wizard steps, order, field behaviour, GA4 flow | `frontend/src/components/onboarding/OnboardingWizard.tsx`, `ProjectSetupFields.tsx`, `frontend/src/i18n/en.json` (`onboarding.*`) |
| Plan entitlements | `backend/app/config/plans.py` (`CAPABILITY_MATRIX`, `MINIMUM_PLAN_BY_FEATURE`) |
| Scan allowance, rolling window, failures counting | `backend/services/scan_allowance_service.py` |
| Scan depths and runtimes | `backend/core/tier_labels.py`, `frontend/src/constants/tiers.ts` |
| Engine roster | `frontend/src/constants/measuredEngines.ts`, `backend/services/project_visibility_service.py` |
| Prompt limits | `backend/services/project_visibility_service.py` (`VISIBILITY_PLAN_LIMITS`) |
| Competitor gating | `backend/routers/workspace_router.py`, `backend/services/project_intelligence_service.py` |
| Run stages, succeeded/failed states | `frontend/src/lib/auditScanRun.ts`, `frontend/src/i18n/en.json` (`signalScanRun.*`) |
| Action plan, dismiss, mark done | `frontend/src/app/(app)/dashboard/projects/[projectId]/fixes/page.tsx`, `signalFixes.plan.*` |
