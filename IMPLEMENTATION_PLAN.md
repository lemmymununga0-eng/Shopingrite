# Implementation Plan

Principles: extend, do not replace. Keep the app-factory, `Repository` protocol for the legacy fraud table, the feature schema and the CSS design language. Every phase ends with executed tests; results go to `IMPLEMENTATION_REPORT.md`.

## Key decisions (with reasons)

| Decision | Reason |
|---|---|
| New domains (catalogue, inventory, carts, orders, ScamWatch, security events, cases, audit, users, settings) use **SQLAlchemy 2.0** with `DATABASE_URL` (SQLite default, PostgreSQL if configured). | One implementation that runs on both engines; needed for transactional stock reservation. SQLAlchemy is the brief's named option and is already installed. |
| The legacy `transactions` table keeps its two repositories (SQLite / Supabase-PostgREST). | Working, tested, and carries RLS; cases reference predictions by id string. |
| Stock reservation uses a **single conditional `UPDATE ... WHERE available_quantity >= :q`** inside one transaction per order (all lines or none), plus SQLite `BEGIN IMMEDIATE`. | Race-free without table locks; rolls back as a unit. Verified by a threaded test. |
| Local identity provider: `LOCAL_AUTH_ENABLED=true` adds `POST /auth/local/login` that verifies a scrypt-hashed password for a seeded **demo user** and issues an HS256 token the existing verifier accepts. Off by default; clearly labelled everywhere; refuses to start with the default secret unless explicitly acknowledged. | The only way for a beginner (and automated browser tests) to run offline. Supabase stays the production path. |
| Roles: `customer`, `fraud_analyst`, `security_analyst`, `admin`. Legacy `analyst` maps to `fraud_analyst`. A central permission table (`app/core/permissions.py`) is the sole authority. | Backend-enforced, testable, mirrors the brief. |
| One React app, two route trees with separate layouts: **store** under `/shop/*` (public browsing), **console** under existing paths (+new ones), role-gated, with a different shell and clearly distinct branding. `/` redirects to `/shop`. | Preserves existing routes/tests while separating the products. |
| Payment is a **simulated adapter** that never receives card data; orders say "Demonstration payment - no money taken". | Brief non-negotiables. |
| ScamWatch performs **no outbound fetch of the submitted URL**. Providers are lookups against fixed provider hosts (optional Google Safe Browsing, key from env) plus an offline heuristic provider and a test mock. | Removes the SSRF class entirely. |
| Customer checkout never calls the ML model. An order-risk **rule monitor** (documented rules, not ML) raises order anomalies. The ML console form remains a staff "transaction simulator" using the compatible 8-feature schema. | Honours the feature-contract rule. |
| Real PCA training requires `creditcard.csv` (absent): pipeline improved and tested on a generated, labelled-as-fixture frame; real-data run reported BLOCKED. | Never fabricate model results. |

## Phases

| # | Phase | Deliverables | Verification |
|---|---|---|---|
| 0 | Audit & docs | AUDIT_REPORT, this plan, architecture, data-model, traceability | done |
| 1 | Foundation | settings, SQLAlchemy engine/session, models, idempotent seed, correlation-ID middleware, security-event recorder, audit service, permissions, local auth, generic rate limiter | unit tests |
| 2 | Store engine | products/categories/inventory/cart/orders APIs and services, simulated payment, reservation, cancel/restock, stock audit | pytest incl. concurrency + rollback |
| 3 | Fraud integration | threshold/band config, prediction -> case creation, order-risk rules | pytest |
| 4 | ScamWatch | normalisation, providers, reports, duplicates, review | pytest with mock provider |
| 5 | Security Monitor + thresholds | event list/detail/filters/summary, threshold alerts | pytest |
| 6 | Investigations | cases, lifecycle, assignment, notes, permissions, audit | pytest |
| 7 | Reports, users, audit, integrations | `/reports/*`, `/admin/users`, `/audit`, `/settings/integrations` | pytest |
| 8 | Store UI | Home, Catalogue, Product, Cart, Checkout, Confirmation, Orders, login | vitest + browser |
| 9 | Console UI | Overview, Investigations, ScamWatch, Security Monitor, Inventory risk, Reports, Users, Audit, Settings; role-gated nav | vitest + browser |
| 10 | Tests | Playwright E2E with real servers, restart-persistence test, CI workflow | executed |
| 11 | Security + second review | checklist, fixes, diff review, docs, README, IMPLEMENTATION_REPORT | executed |

## Out of scope / blockers (declared up front)

- Live Supabase auth/RLS (no credentials) -> BLOCKED.
- Real Safe Browsing provider calls (no key, would incur external calls) -> BLOCKED; mock and heuristic tested.
- Real Kaggle training (dataset absent) -> BLOCKED.
- Real payments, real Shoprite data/integration -> never claimed.
- Deployment -> not performed.
