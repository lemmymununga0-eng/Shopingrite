# Audit Report: Shoprite FraudGuard (baseline before this work)

Audit date: 2026-10-16. Method: every source file under `backend/`, `frontend/src/`, `supabase/` and `docs/` was read; baseline checks were executed (results below). Nothing in application code was changed before this report was written.

## 1. Which project was audited

The open workspace (`GLORIAL WHY`) was **empty** and not a Git repository. Three candidate projects exist on the Desktop. By agreement with the project owner the most recent one, `Shoprite_FraudGuard_Full_Project\Shoprite_FraudGuard_Full_Project` (modified 2026-10-15), was **copied** into the workspace (excluding `node_modules`, caches, `.git`). The Desktop original was not modified. A Git repository was initialised and the imported state committed as the baseline (`2e88c61`). `.env` files, `*.joblib` and `*.db` are git-ignored and were verified as untracked. (`.env` files were copied but their values were not printed or committed; only variable names were inspected.)

## 2. Baseline checks (executed on the imported project)

| Check | Result |
|---|---|
| `python -m pytest` (backend) | PASS: 109 passed, 15.8 s |
| `npx vitest run` (frontend) | PASS: 88 passed in 4 files |
| `npx vite build` | PASS: 2277 modules; main chunk 498 kB, dashboard chunk 430 kB (Recharts) |
| `npm audit --omit=dev` | PASS: 0 vulnerabilities |
| Python dependency audit | NOT TESTED: `pip-audit` not installed |
| Live Supabase sign-in / RLS | BLOCKED: no tested live project (`docs/KNOWN_ISSUES.md`) |
| `creditcard.csv` present | No. PCA model artifact therefore absent |
| Browser end-to-end | NOT TESTED at baseline (no Playwright tests existed) |

Environment: Windows 11, Python 3.14.0, Node 22.20, npm 10.9, FastAPI 0.136, scikit-learn 1.8, SQLAlchemy 2.0.44 installed globally.

## 3. What exists (working, preserved)

- **Backend (FastAPI, app-factory pattern):** Supabase JWT verification (HS256 secret or JWKS ES256/RS256, role from `app_metadata` only); `/predict`, `/transactions` (+filters/pagination/stats), `/alerts` + `PATCH /alerts/{id}` (reviewer-only), `/model-info`, `/health`, `/pca-demo/*`; per-user rate limit on predict; 20 kB body limit; validation errors never echo values; repository abstraction with SQLite and Supabase-PostgREST implementations; RLS migration.
- **ML:** one feature schema (`feature_schema.py`) shared by form, API, trainer and predictor; Random Forest pipeline with stratified 80/20 split, duplicate removal, `class_weight=balanced_subsample`, schema-hash check at load, atomic artifact write, evaluation (precision/recall/F1/PR-AUC/ROC-AUC/confusion matrix). Trained model on **synthetic** data (PR-AUC 0.392, ROC-AUC 0.842, precision 0.26, recall 0.63) and honest labelling of that fact. A separate Kaggle-PCA pipeline (`pca_demo.py`) with column validation; `Class` is never a feature.
- **Frontend (React 18 + Vite + React Router 7):** Supabase login/registration/password reset, protected routes, dashboard (Recharts), new payment (model form), PCA model demo, alerts with analyst review, history with filters, profile, settings, about. Green design language in a single `index.css`.
- **Docs/tests:** 7 docs in `docs/`, 109 backend and 88 frontend tests.

## 4. Verified gaps against the product brief

| # | Gap | Evidence |
|---|---|---|
| G1 | **No customer grocery store at all.** No products, categories, cart, checkout, orders, order history. | No such routes/pages/tables |
| G2 | **No inventory or order engine.** No product/inventory/order tables, no stock reservation or transactions. | `sqlite_repo.py` schema has only `transactions` |
| G3 | **No ScamWatch.** | absent |
| G4 | **No Security Monitor / security-event store**; auth failures, 403s, 429s, 500s, model/provider failures are not recorded anywhere (only a log line for 500). | `auth.py`, `factory.py` |
| G5 | **No Investigation Centre / case management**; alerts carry only `review_status` on the transaction row. | schema |
| G6 | **No audit trail.** | `SECURITY_REVIEW.md` risk 6 |
| G7 | **No reports** beyond dashboard stats. | |
| G8 | **Roles are `customer/analyst/admin`** only; no separate fraud vs security analyst; no in-app user/role management. | `auth.py` |
| G9 | **No way to run locally without a real Supabase project.** Sign-in needs Supabase; with `DB_BACKEND=sqlite` there is still no local identity provider. A beginner cannot demo the app offline, and nothing can be exercised end-to-end in a browser without external credentials. | README step 5 |
| G10 | The customer-facing console pages (`New Payment`, `Payment Card`) let ordinary customers use the staff console. Customer and staff experiences are not separated. | `App.jsx` routes |
| G11 | Console and store have no distinct layout; only one app shell exists. | `Layout.jsx` |

## 5. Verified defects and risks in the existing code

| # | Sev | Finding | Root cause | Planned fix |
|---|---|---|---|---|
| D1 | M | UI/README/sidebar use the name "Shoprite FraudGuard" and the brand colour. The brief forbids implying official ownership/endorsement. | Hard-coded brand strings in `Sidebar.jsx`, `Topbar.jsx`, `Login.jsx`, README | Configurable brand (`VITE_APP_BRAND`, default "FraudGuard"), configurable store identity, visible "independent demonstration" notices |
| D2 | M | Risk bands in the PCA predictor are hard-coded (0.7/0.3, threshold 0.5); the payment model's decision threshold is fixed at training time and cannot be changed at inference without retraining. | `pca_demo.py:502`, `train_model.py` default | `MODEL_THRESHOLD`, `RISK_HIGH/RISK_MEDIUM` honoured by both predictors; threshold exposed in `/model-info` |
| D3 | M | Rate limiting exists only on `/predict` (in-memory). Login-adjacent, checkout and ScamWatch endpoints have none. | `dependencies.py` | Generic keyed limiter reused for checkout, cart writes, ScamWatch, local login |
| D4 | M | Failed token verification returns 401 but is **not recorded**, so brute-force/abuse cannot be seen. | `auth.py` | Security-event recorder on 401/403/429/422-rejection/500 |
| D5 | L | `/docs`, `/openapi.json` public. | FastAPI default | Setting `DOCS_ENABLED` (default on in dev; documented) |
| D6 | L | SQLite connections open per call without `PRAGMA foreign_keys` or WAL. | `sqlite_repo.py` | New SQLAlchemy layer sets both; legacy repo left intact |
| D7 | L | Supabase dashboard stats read at most 10 000 rows client-side. | `supabase_repo.py` | Documented limitation (unchanged) |
| D8 | L | Main JS bundle is 498 kB + 430 kB chart chunk; no code-splitting of the new areas. | single bundle | Lazy-load store and console route groups |
| D9 | L | Dead artefacts: `backend/legacy_kaggle/`, `data/predictions.json`, `.qodo/`. | history | Left in place (not mine to delete); documented |
| D10 | Info | Model loading uses `joblib` (pickle). Mitigated by loading only a configured local path and schema-hash check. | inherent | Document; add file-under-`artifacts` path guard |
| D11 | Info | The bundled payment model is trained on synthetic data; its metrics say nothing about real fraud detection. Already disclosed in the UI/docs. | no labelled retail dataset exists | Keep disclosures; extend wherever scores are shown |

No SQL-injection, secret-in-source or missing-ownership defects were found in the pre-existing transaction code: sort columns and filters are whitelisted/parameterised, ownership is enforced per request, `.env` is ignored.

## 6. Suspected / unverified

- Live Supabase JWKS verification, PostgREST calls and the RLS/trigger SQL are untested against a real project (BLOCKED, no credentials).
- Behaviour under concurrent writes to the legacy SQLite repository (new code uses atomic SQL; legacy path has only single inserts, low risk).
- Real Kaggle PCA training results (dataset absent).
- Accessibility and mobile layout were never checked in a browser.

## 7. Missing artefacts vs the target structure

The brief's target tree (`app/api`, `app/core`, `app/services`, `app/db/models.py`, `tests/`, `frontend/features/...`, `.github/workflows/tests.yml`, `docs/security.md`, `docs/testing.md`) does not exist. The existing layout (`app/routers`, `app/db/*_repo.py`, `frontend/src/pages`) is **retained**, and new code follows the same conventions (see `docs/architecture.md`) instead of a disruptive rename.

## 8. Priorities

1. Local auth + roles + security-event/audit foundation (unblocks everything and testing).
2. Store domain: products, inventory, cart, orders with atomic stock reservation.
3. Investigations, ScamWatch, Security Monitor, reports, user admin.
4. Store and console frontends; separation of the two.
5. Tests (unit, concurrency, UI, E2E), security review, second review, documentation.
