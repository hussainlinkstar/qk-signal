# Render free — mock frontend preview

Deploys **only** the Next.js frontend plus `e2e/visual/stub-backend.mjs` (no Postgres, Redis, or real API).

## URLs

| Service | Typical URL |
| --- | --- |
| App | `https://qk-signal-web.onrender.com` |
| Stub API | `https://qk-signal-stub.onrender.com` |

Free services sleep after ~15 minutes idle (~1 minute cold start).

## Deploy

1. Push this repo to GitHub.
2. Render Dashboard → **New** → **Blueprint** → select repo (`render.yaml`).
3. Apply. Wait for both services to go live.
4. Open `https://qk-signal-web.onrender.com/mock-signin`
5. Then visit `https://qk-signal-web.onrender.com/dashboard/audit/2`

## Local (same stack)

```bash
cd frontend
npm ci
npm run preview:mock
```

Then:

1. http://127.0.0.1:3000/mock-signin
2. http://127.0.0.1:3000/dashboard/audit/2
3. Other stub-backed routes: `/dashboard/overview`, `/dashboard/projects/9`, `/dashboard/billing`, etc.

## Notes

- `MOCK_PREVIEW=1` enables `/api/mock-signin`.
- Stub listens on `$PORT` (Render) or `8000` locally.
- Free web services cannot use private networking between each other; Blueprint wires `BACKEND_URL` to the stub’s public `RENDER_EXTERNAL_URL`.
