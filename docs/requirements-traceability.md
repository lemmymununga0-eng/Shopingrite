# Requirements traceability

Status legend: PASS executed successfully, FAIL executed and failed, BLOCKED required dependency or credential unavailable, NOT TESTED not executed. Statuses start as NOT TESTED and are filled from real runs in `IMPLEMENTATION_REPORT.md`.

| Req (brief section) | Implementation | Verified by | Status |
|---|---|---|---|
| Store screens 1-7 (7) | `frontend/src/store/*` | vitest, Playwright | NOT TESTED |
| DB-backed products/stock (8) | `models.py`, `seed.py`, `inventory_service.py` | `tests/test_products.py`, `test_inventory.py` | NOT TESTED |
| Atomic checkout, no oversell, rollback (8) | `order_service.py` | `tests/test_orders.py::concurrency/rollback` | NOT TESTED |
| Order snapshots; currency explicit (8) | `order_items`, `STORE_CURRENCY` | `test_orders.py` | NOT TESTED |
| Stock-adjust audit event (8) | `audit_service.py` | `test_inventory.py` | NOT TESTED |
| Simulated payment, no card data (3, 7) | `payment_service.py`, checkout UI | `test_orders.py`, UI test | NOT TESTED |
| ML schema validation, leakage prevention, metrics (9) | `app/ml/*` | existing + new `test_ml_*` | NOT TESTED |
| Configurable threshold/risk bands (9) | `config.py`, `predict.py`, `pca_demo.py` | `test_ml_config.py` | NOT TESTED |
| Checkout never uses model (9) | order service has no model import | `test_orders.py` | NOT TESTED |
| Unified Investigation Centre (10) | `investigation_service.py`, `/investigations` | `test_investigations.py` | NOT TESTED |
| Case permissions and audit (10) | `permissions.py`, `audit_service.py` | `test_investigations.py` | NOT TESTED |
| ScamWatch (11) | `scamwatch_service.py`, `/scamwatch/*` | `test_scamwatch.py` (mock provider) | NOT TESTED |
| ScamWatch live provider (11) | optional Safe Browsing adapter | none possible without a key | BLOCKED |
| No SSRF / no URL fetch (11) | design: no outbound fetch of submitted URLs | `test_scamwatch.py::no_fetch` | NOT TESTED |
| Security Monitor (12) | `security_events.py`, `/security/*` | `test_security_events.py` | NOT TESTED |
| Redaction (12) | `core/security.py::redact` | `test_redaction.py` | NOT TESTED |
| Staff console on real records (13) | `/reports/overview`, console UI | pytest + Playwright | NOT TESTED |
| Reports with explanations; no unsupported savings claims (14) | `/reports/*`, Reports page | `test_reports.py` | NOT TESTED |
| Auth, roles, ownership (15) | `auth.py`, `permissions.py`, local auth | `test_auth_roles.py` | NOT TESTED |
| Supabase auth/RLS live (15) | existing code + migration | none possible | BLOCKED |
| Endpoints (16) | routers listed in `architecture.md` | `test_api_contract.py` | NOT TESTED |
| Env configuration (17) | `.env.example` files | manual + `test_config.py` | NOT TESTED |
| Backend / frontend / E2E tests (18) | `backend/tests`, `frontend/src/tests`, `frontend/e2e` | executed | NOT TESTED |
| Security review (19) | `docs/security.md` | executed checklist | NOT TESTED |
| Second review (20) | `IMPLEMENTATION_REPORT.md` | diff review | NOT TESTED |
| Documentation (22) | README, report | read-through | NOT TESTED |
