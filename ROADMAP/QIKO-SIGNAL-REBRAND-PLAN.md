# Rebrand Plan: Qiko Signal → Qiko Signal

> Status tracker for the full rebrand. Product is already live at **qiko.ai/signal**
> (path unchanged — no re-migration). Brand source: `Qiko Branding Guidelines.docx`.

## Decisions
- **Product name:** Qiko Signal
- **Headline metric:** "Signal Strength" (replaces "AI Visibility")
- **URL/path:** `qiko.ai/signal` (already deployed) — unchanged.
- **Support emails:** TBD — `@qiko.ai` vs keep `@qiko.ai` (default: `@qiko.ai`).
- **Tagline:** TBD (default: "Qiko Signal — AI visibility for SEO, AEO & GEO").

## Brand identity (from guidelines)
- Logo: Qiko wordmark, gradient blue `#2563EB` → purple `#9333EA`; monochrome Navy `#0D1B2A`. Source assets: `qiko-logo-wordmark.png`, `qiko/qiko-frontend/client/public/qiko-logo.{png,webp}`.
- Colours: Navy `#0D1B2A` (bg), Indigo `#6366F1` + Cyan `#22D3EE` (accents), Off-white `#F5F7FA`. success `#10B981` / warn `#F59E0B` / error `#EF4444`.
- Type: Satoshi (headings, self-host) + Inter (body).
- Replaces Qiko Signal orange `#FF4D2D`.

## Phases / tracker
- [ ] **F1 — Brand tokens & assets**: CSS vars + Tailwind palette; fonts Satoshi+Inter; logo SVG (light/dark) + favicon + icon-192/512 + apple-touch + og-image + manifest icons, all in Qiko brand. Keep filenames, swap content.
- [ ] **F2 — Frontend text**: title/meta/OG, manifest name, marketing pages (about/faq/docs/blog/terms/privacy/sample-report/volatility/system/trial-feedback), components, chat widget, i18n, AppLogo alt — all "Qiko Signal" → "Qiko Signal". Centralise via `BRAND_NAME` constant.
- [ ] **F3 — Backend**: email templates + subjects + footer + from-name, PDF audit report branding (`pdf_reports/branding.py`, `assembler.py`, `pdf_report_renderer.py`), support/from addresses, `EMAIL_FROM_NAME` env.
- [ ] **F4 — DB content**: brand strings in Postgres (`operational_settings` email_footer_defaults/support_info, case-studies, blog, templates), demo workspace names.
- [ ] **F5 — Build + deploy** frontend + backend; invalidate caches.
- [ ] **F6 — Verify**: Playwright on key pages (0 errors); `grep "Qiko Signal" == 0` in UI/output (excluding intentional technical refs); visual logo/colour/font check; OG/manifest/favicon.

## Surfaces checklist (don't miss)
title/meta · OG/Twitter · manifest (name + icons + colours) · favicon set · AppLogo + dark · chat widget · marketing pages · FAQ/docs/about/terms/privacy · i18n · email subject/body/footer/from-name · PDF audit reports · JSON-LD Organization · sitemap/robots/feed · support emails · DB content (case-studies/blog/templates) · Tailwind/CSS tokens · fonts · error/loading/404 pages · social-links · alt-texts.

## Scope (measured)
~106 non-test files reference "thothgraph"; 13 brand asset files in `frontend/public/`. LLM prompts contain no brand name (safe).
