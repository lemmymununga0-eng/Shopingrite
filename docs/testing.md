# Testing

Real results of the last full run are in `IMPLEMENTATION_REPORT.md`. Nothing is reported as passing unless it was run.

## Commands (Windows PowerShell)

```powershell
# Backend unit + API + concurrency tests
cd backend
python -m pytest -q

# Frontend component tests and production build
cd ..\frontend
npm test
npm run build

# Browser end-to-end tests (starts a real backend on :8799 and the Vite dev server on :5199,
# with throw-away databases in backend\data\e2e; needs Chromium once: npx playwright install chromium)
npm run test:e2e
```

## What each layer proves

| Layer | Files | Notes |
|---|---|---|
| Backend | `backend/tests/*.py` | Catalogue, stock, cart, checkout, rollback, **concurrent** reservations (threads at service and HTTP level), ownership, cancellation/restock, roles matrix, local auth, ScamWatch (mock provider, no-fetch proof), security events, thresholds, redaction, investigations rules, reports, admin, audit, migrations, restart persistence, model threshold/schema/training pipeline. |
| Frontend | `frontend/src/tests/*.jsx` | Store pages, stock labels, filters, cart, checkout errors, confirmation, orders, protected/staff routes, role-aware navigation, ScamWatch results, Security Monitor filters, investigation workflow, reports empty states. API is mocked here. |
| Browser | `frontend/e2e/*.spec.js` | Real backend + frontend: the 16-step workflow (store → cart → simulated checkout → order/stock check → model prediction → case → ScamWatch with the scripted mock provider → security event → role refusals → backend restart), axe accessibility scans, 375 px layout checks. |

## What the tests do **not** prove

* Live Supabase sign-in/RLS, live threat-intelligence providers and PostgreSQL were not exercised (BLOCKED / NOT TESTED).
* The mock ScamWatch provider and the synthetic fraud data show that the plumbing works, not that detection is accurate.
* The real Kaggle `creditcard.csv` is not on this machine, so the PCA model was only tested on a generated fixture.
