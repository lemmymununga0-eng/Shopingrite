# Production readiness

Statuses: **PASS** (verified by a test or a command), **PARTIAL**, **BLOCKED** (needs something only the owner can provide), **NOT TESTED**.

## What is verified

| Area | Status | Evidence |
|---|---|---|
| Backend tests (SQLite) | PASS | full `pytest tests` run |
| Backend tests (real PostgreSQL, includes the new ML/outcome tables and migrations 6-7) | PASS if the `backend-postgres` CI job is green | `.github/workflows/tests.yml` runs them on Postgres 16; no Postgres exists on the development machine |
| Frontend unit tests, production build, `npm audit --omit=dev` | PASS | vitest; `npm run build`; 0 vulnerabilities |
| Browser end-to-end (checkout, payment states, staff console, access, mobile, accessibility) | PASS | Playwright against a real backend |
| Every API route refuses anonymous callers unless on a reviewed public list; every staff route answers 403 to a customer | PASS | `tests/test_route_security.py` (fails if a new endpoint forgets its check) |
| Security headers (API: nosniff, frame deny, no-store, CSP, HSTS in production; site: CSP, HSTS, frame deny) | PASS | `tests/test_route_security.py`, `frontend/vercel.json` |
| Unsafe production settings refuse to start (simulated payments, local auth, demo data, localhost CORS, missing webhook hash...) | PASS | `Settings.production_problems`, tested |
| Dependencies pinned to a safe range; runtime vs ML vs test requirements separated | PASS | `backend/requirements*.txt` |
| Fresh-install test run (the way CI and Render install) | see CI | a fresh-venv run was the cause of the first CI failure (missing `pyarrow`); fixed |
| Label export / audit queue use bounded SQL | PASS | no full-table loads |

## What cannot be verified from this machine
| Item | Status | What is needed |
|---|---|---|
| Live Flutterwave payments (card, MTN, Airtel) and webhooks | **BLOCKED** | your Flutterwave account; test keys first (`FLWSECK_TEST-...`). Only exercised against a fake so far |
| Supabase sign-in against the real project | NOT TESTED | your Supabase project values |
| Deployment on Render and Vercel | **BLOCKED** | your Render and Vercel accounts (see `docs/DEPLOYMENT.md`) |
| Real fraud/phishing performance on store traffic | not possible yet | verified outcomes (`docs/LABEL_COLLECTION.md`) |
| Load / capacity | NOT TESTED | no load test was run; one starter instance is sized for a small shop |

## Known limits you should accept before going live
- Rate limiting is in memory per instance: fine for one instance, not shared if you scale out.
- Payment settlement jobs run inside the API process: keep one always-on instance (`plan: starter`).
- Orders are assessed by rules (`store_risk_v1`), not a trained model. A high score opens a case for a person; it never blocks a customer.
- Trained ML models are not committed. A new deployment shows them as "Not trained" until you train or copy them; the store works without them.
- Back up the database (Supabase/Render daily backups) and test a restore before taking real money.
- Take real money only after a test-mode purchase, a refund and a webhook delivery have each been done end to end (`docs/DEPLOYMENT.md`, part 5).
