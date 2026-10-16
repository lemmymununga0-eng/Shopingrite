# Requirements traceability

PASS = executed successfully. FAIL = executed and failed. BLOCKED = a required dependency or credential is unavailable. NOT TESTED = not executed. Counts and commands are in `IMPLEMENTATION_REPORT.md`.

| Requirement (brief section) | Implementation | Verified by | Status |
|---|---|---|---|
| Store screens 1-7 (7) | `frontend/src/store/*`, `layouts/StoreLayout.jsx` | `store.test.jsx` (28), Playwright workflow + axe + 375 px checks | PASS |
| DB-backed products and stock (8) | `db/models.py`, `db/seed.py`, `services/inventory_service.py` | `test_products.py`, `test_inventory.py`, E2E step 3 | PASS |
| Atomic checkout, no overselling, rollback (8) | `services/order_service.py` | `test_orders.py` (thread-level and HTTP-level races, rollback, double submit) | PASS |
| Order snapshots; explicit currency (8) | `order_items`, `STORE_CURRENCY` | `test_orders.py` (snapshot, currency mismatch refused) | PASS |
| Stock changes audited (8) | `services/audit.py` | `test_inventory.py`, `test_orders.py` | PASS |
| Cancellation restocks exactly once (8) | `order_service.change_status` | `test_orders.py` (incl. concurrent cancels) | PASS |
| Simulated payment, no card data (3, 7) | `services/payment_service.py`, strict schemas, checkout UI | `test_orders.py`, `store.test.jsx`, E2E | PASS |
| Checkout never uses the model (9) | order service has no model import | `test_orders.py::never_uses_the_model` | PASS |
| ML: schema validation, leakage prevention, metrics (9) | `app/ml/*` | `test_ml.py`, `test_training.py`, evaluation test | PASS (synthetic data / fixture only) |
| Real Kaggle training run (9) | `--schema pca` | `creditcard.csv` not present | BLOCKED |
| Configurable threshold and risk bands (9) | `MODEL_THRESHOLD`, `RISK_*`, `--threshold` | `test_reports_admin.py` | PASS |
| Unified Investigation Centre (10) | `services/investigation_service.py`, `/investigations` | `test_investigations.py` (22), E2E step 10 | PASS |
| Case permissions and audit trail (10) | `core/permissions.py`, `audit.py` | `test_investigations.py`, `test_auth_roles.py` | PASS |
| ScamWatch (11) | `services/scamwatch_service.py`, `/scamwatch/*` | `test_scamwatch.py` (46), E2E steps 11-12 | PASS (mock/heuristic) |
| ScamWatch live provider (11) | `SafeBrowsingProvider` | mocked HTTP only; no key, no live call | BLOCKED |
| No SSRF / no URL fetch (11) | design + private-address rejection | `test_scamwatch.py` (network transports patched to fail) | PASS |
| Security Monitor (12) | `services/security_events.py`, `/security/*` | `test_security_events.py`, `console.test.jsx`, E2E | PASS |
| Redaction (12) | `core/security.py::redact` | `test_security_events.py` | PASS |
| Staff console on stored records (13) | `/reports/overview`, `OperationsOverview` | `test_reports_admin.py`, `console.test.jsx` | PASS |
| Reports with definitions; no savings claims (14) | `routers/reports.py`, `Reports.jsx` | `test_reports_admin.py` | PASS |
| Authentication, roles, ownership (15) | `auth.py`, `permissions.py`, `routers/auth_local.py` | `test_auth_roles.py` (matrix over 13 endpoints x 4 roles) | PASS (local/test tokens) |
| Supabase auth, JWKS, RLS live (15) | existing code + two migrations | mocked JWKS test only; no project | BLOCKED |
| PostgreSQL via `DATABASE_URL` (5, 17) | SQLAlchemy models | not run against PostgreSQL | NOT TESTED |
| Endpoints (16) | routers listed in `architecture.md` | all exercised by backend tests; E2E | PASS |
| Environment configuration (17) | `.env.example` files, `config.py` | tests build `Settings` explicitly; README walkthrough | PASS |
| Backend, frontend, E2E tests (18) | `backend/tests`, `frontend/src/tests`, `frontend/e2e` | executed | PASS |
| Restart persistence (18) | SQLAlchemy + migrations | `test_data_survives_an_application_restart`, E2E step 15-16 | PASS |
| Security review (19) | `docs/security.md` | greps, `pip-audit`, `npm audit`, tests | PASS (see limitations) |
| Second review (20) | `IMPLEMENTATION_REPORT.md` | diff read; defects found and fixed | PASS |
| Documentation (22) | `README.md`, docs | written; commands executed | PASS |
| Mobile and accessibility (18) | CSS, labels, chart handling | axe (serious/critical) and 375 px checks on tested pages | PASS (not a full audit) |
