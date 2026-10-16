# Implementation Report

Date: 2026-10-16. Status legend: **PASS** executed successfully · **FAIL** executed and failed · **BLOCKED** a required dependency or credential is unavailable · **NOT TESTED** not executed.

## 1. What was built

The existing FraudGuard project (fraud-only console) was audited (`AUDIT_REPORT.md`), planned (`IMPLEMENTATION_PLAN.md`) and extended into two connected apps in one repository:

* **Customer store** `/shop`: categories, search, filter/sort/pagination, product details, server-side cart with stock revalidation, checkout (delivery or collection, delivery-area validation), simulated payment, order confirmation, order history and cancellation.
* **FraudGuard staff console** (separate shell, role-gated): operations overview, fraud alerts and model simulator, Investigation Centre, ScamWatch, Security Monitor with thresholds, inventory and order-risk view, reports with metric definitions, user/role admin, audit trail, model and integration status.
* **Backend**: roles `customer / fraud_analyst / security_analyst / admin` enforced on the server by one permission table; SQLAlchemy application database (SQLite, PostgreSQL via `DATABASE_URL`) with explicit migrations; transactional stock reservation; correlation ids; redacted security events; append-only audit; rate limits; local demonstration sign-in for offline use.

The project folder `GLORIAL WHY` started empty; by agreement the most recent project (`Shoprite_FraudGuard_Full_Project`) was copied in and Git-initialised. The Desktop original was not modified.

## 2. Audit findings and root causes (summary; full list in AUDIT_REPORT.md)

| Finding | Root cause | Outcome |
|---|---|---|
| No store, inventory, orders, ScamWatch, security events, cases, audit, reports, user admin | Prototype covered only the fraud console | Implemented |
| Could not run or demo without a live Supabase project | No local identity path | Local demo sign-in (off by default, refused in production) |
| Customers could use staff pages; one role for all "analysts" | Single shell, 3 roles | Separate shells, 4 roles, server-side permissions |
| Failures (401/403/429/500, model/provider errors) not recorded | No event store | `security_events` + thresholds + cases |
| UI/README used "Shoprite FraudGuard" branding | Hard-coded | Configurable neutral brand, demonstration labels |
| Fixed model threshold and PCA risk bands | Hard-coded | `MODEL_THRESHOLD`, `RISK_HIGH/MEDIUM`, `--threshold` |
| Bundled model file pickled by a different scikit-learn than installed | Model made in another environment | Backed up (`fraud_model.joblib.bak-sklearn-1.9.1`) and retrained locally |

## 3. Defects found while building, with fixes (all re-tested)

1. `normalize_url` accepted private/loopback addresses (an `except ValueError` swallowed the rejection). Caught by tests. **Fixed.**
2. Recording a security event inside an open SQLite transaction blocked 30 s and silently lost the event (login failures, provider failures). Caught by a 5-minute test run. **Fixed** (record after the transaction closes).
3. An analyst could take over a case already assigned to someone else. **Fixed.**
4. Chunked uploads without `Content-Length` bypassed the 20 kB limit. **Fixed** (byte-counting ASGI middleware, 413).
5. Failed sign-in displayed "session expired". **Fixed.**
6. Accessibility: contrast on store and console, button labels not starting with visible text, duplicate "Quantity" names, unlabeled chart SVG, focusable content inside a hidden chart, invalid `<dl>` content. **Fixed**; axe (WCAG 2.1 A/AA, serious+critical) passes on tested pages.
7. Dashboard dev server page reload on first chart load made browser tests flaky. **Fixed** (`optimizeDeps.include`); three consecutive full runs passed.

## 4. Test and build results (executed 2026-10-16)

| Check | Command | Result |
|---|---|---|
| Backend tests | `cd backend; python -m pytest -q` | **PASS: 299 passed** (baseline was 109) |
| Frontend tests | `cd frontend; npm test` | **PASS: 140 passed** in 6 files (baseline was 88) |
| Browser end-to-end (real servers) | `npm run test:e2e` | **PASS: 18 passed**, three consecutive full runs (a first run before stabilisation had failures, see section 3) |
| Production build | `npm run build` | **PASS** (main chunk 521 kB, dashboard chunk 432 kB, store and console pages lazy-loaded) |
| `npm audit --omit=dev` | | **PASS: 0 vulnerabilities** |
| `pip-audit -r requirements.txt` | | **PASS: no known vulnerabilities** |
| Secret scan (real `.env` values vs tracked files and built bundle) | script | **PASS: none found** |
| Live Supabase sign-in, JWKS, RLS, roles migration | | **BLOCKED** (no credentials) |
| Live Safe Browsing calls | | **BLOCKED** (no API key; adapter tested with mocked HTTP only) |
| Real Kaggle `creditcard.csv` training and metrics | | **BLOCKED** (file not on this machine; pipeline tested on a generated fixture) |
| PostgreSQL via `DATABASE_URL` | | **NOT TESTED** |
| Real devices, real phones, screen readers, full WCAG audit | | **NOT TESTED** (axe scan + 375 px viewport only) |
| GitHub Actions workflow (`.github/workflows/tests.yml`) | | **NOT TESTED** (never run on GitHub) |

### The 16-step end-to-end scenario (all PASS, run against a real backend and the Vite dev server)
Store loads → search "milk" → inspect database stock → add to cart (signed-in demo customer) → out-of-stock item rejected (UI disabled and server 409) → simulated checkout → order persisted and stock reduced by exactly the ordered quantity (verified through the API) → fraud analyst submits compatible model inputs → real model response (probability, version) → generated case opened and walked to "false positive" → URL submitted through the scripted mock ScamWatch provider and report persisted → failed sign-in becomes a security event with correlation id → customer refused by browser and API (403), fraud analyst refused the Security Monitor, security analyst refused user admin → admin stock adjustment audited → **backend restarted** and orders, stock, cases, scam reports, audit and events all still present.

## 5. Model metrics (actual, from `python -m app.ml.train_model --synthetic`)

The payment-form model is trained on **synthetic data whose labels come from a hand-written formula**, so these figures show the pipeline works, not that fraud is detected in reality.

| Metric | Value |
|---|---|
| Model | `rf-20261016-193131`, RandomForest, 200 trees, `class_weight=balanced_subsample`, stratified 80/20 split, seed 42 |
| Rows / fraud | 20 000 / 1 235 (6.2 %); held-out test 4 000 rows, 247 fraud |
| Threshold | 0.3 (configurable) |
| Precision / Recall / F1 | 0.251 / 0.623 / 0.358 |
| PR-AUC / ROC-AUC | 0.393 / 0.842 |
| Confusion matrix | TN 3293, FP 460, FN 93, TP 154 |

The PCA/Kaggle model has **no real metrics**: BLOCKED (dataset absent). Its pipeline validates the schema, excludes `Class` from inputs, handles missing/infinite values, drops duplicates before the stratified split, and reports the same metrics plus prevalence; this is covered by tests on a generated fixture only. No claim is made that any model was trained on retailer data.

## 6. Security review

See `docs/security.md` (controls, findings, residual risks). Summary: authorization on the server for every protected route (matrix test), ownership 404s, parameterised SQL, no XSS sinks, no SSRF surface, redaction, rate limits, byte-level request limit, secrets absent from Git and the bundle. Not claimed: production readiness, PCI compliance, live Supabase/RLS correctness.

## 7. Second review (independent pass over the full diff)

I re-read the complete diff against the baseline (`git diff 2e88c61`): 39 backend and 36 frontend application files changed; every removed line was inspected and is a replacement, not lost behaviour (auth, dependencies, factory, models, routers, sidebar/topbar, charts). Checks made: API contracts (frontend calls match routers, exercised end to end); ownership and role rules (matrix and per-resource tests); inventory transaction behaviour (race and rollback tests); model training/inference consistency (shared schema hash, threshold from one property); provider-error handling (inconclusive results, events); store/console separation (different shells, server-side 403, browser redirects). The review surfaced items 2-3 and 7 in section 3. This was a self-review by the same author; no separate reviewer agent was run.

## 8. Files changed (high level)

* **New backend**: `app/core/{permissions,security}.py`, `app/db/{models,session,seed}.py`, `app/db/migrations/`, `app/services/*` (inventory, cart, order, payment, order_risk, scamwatch, security_events, investigation, audit), `app/routers/{auth_local,products,inventory,cart,orders,scamwatch,security,investigations,reports,admin}.py`, `app/schemas/store.py`, 9 new test modules, `supabase/migrations/20261016000001_roles.sql`.
* **Modified backend**: `auth.py`, `config.py`, `dependencies.py`, `factory.py`, `ml/{predict,pca_demo,evaluation,train_model}.py`, legacy routers (permissions, case creation, events), requirements, `.env.example`.
* **New frontend**: `store/*`, `layouts/StoreLayout.jsx`, `context/StoreContext.jsx`, `components/{ScamChecker,OperationsOverview,badges}.jsx`, 8 console pages, `services/session.js`, `e2e/*`, `playwright.config.js`, 2 new test files.
* **Modified frontend**: `App.jsx`, `AuthContext.jsx`, `api.js`, `Sidebar/Topbar/Login/Register/About`, `Dashboard`, charts, CSS, `vite.config.js`.
* **Docs**: README, AUDIT_REPORT, IMPLEMENTATION_PLAN, this report, `docs/{architecture,data-model,security,testing,requirements-traceability}.md`, CI workflow.
* `docs/ARCHITECTURE.md` (old) was replaced by `docs/architecture.md` (same file on Windows; the old text is in Git history). The old model file was backed up, not deleted.

## 9. Remaining blockers and limits

1. Live Supabase auth/RLS and the new roles migration: **BLOCKED**.
2. Live threat-intelligence provider: **BLOCKED**. ScamWatch results in tests and the demo are heuristic or scripted mock.
3. Real Kaggle dataset and a properly labelled retail dataset do not exist here, so no model can honestly be called realistic: **BLOCKED**.
4. PostgreSQL mode and GitHub Actions: **NOT TESTED**.
5. In-memory rate limiter and event de-duplication (single process); SQLite serialises writers.
6. A full accessibility audit, real-device testing and a design comparison with any reference screenshots were not done.
7. Local demo accounts use a documented password and exist only while `LOCAL_AUTH_ENABLED=true`.
8. There is no real payment, inventory or order feed from any retailer, and none is claimed.

## 10. Exact commands to run the application (PowerShell)

```powershell
# one-time backend setup
cd backend
py -m venv venv ; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env            # then set LOCAL_AUTH_ENABLED=true for the offline demo
python -m app.ml.train_model --synthetic

# run backend (terminal 1)
uvicorn main:app --reload

# run frontend (terminal 2) - keep VITE_SUPABASE_* empty in frontend\.env for the local demo
cd frontend
npm install
npm run dev                        # http://localhost:5173  (API docs: http://127.0.0.1:8000/docs)

# tests
cd backend ; python -m pytest -q
cd ..\frontend ; npm test ; npm run build ; npx playwright install chromium ; npm run test:e2e
```
Demo accounts and the demo password are listed in `README.md` section 5.
