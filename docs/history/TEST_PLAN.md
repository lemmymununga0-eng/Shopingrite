# Test Plan

| Layer | Tool | Location | What it covers |
|---|---|---|---|
| Backend API | pytest + FastAPI TestClient (real app, temp SQLite, test-signed JWTs) | backend/tests/test_api.py | health, auth (missing/invalid/expired/wrong audience), validation, no client-set scores, rate and size limits, ownership, roles, pagination/search/filters, alert review persistence, DB errors, CORS |
| ML | pytest | backend/tests/test_ml.py | dataset validation, training on fixture, reproducibility, metrics present, save/load round trip, preprocessing consistency, incompatible/corrupt/missing model, atomic save, risk bands |
| Supabase adapter | pytest + httpx MockTransport (**mocked**) | backend/tests/test_supabase_repo.py | request shape, user token forwarded, verified user id, filters, error mapping |
| Frontend | vitest + Testing Library (api layer mocked) | frontend/src/tests | auth pages, protected routes, sign-out, API client, payment validation/submission, history search/filter/pagination, alerts review with confirmation, dashboard, settings |
| Live HTTP smoke | uvicorn + scripted httpx client against a real process | run manually (see TEST_RESULTS.md) | full flow incl. restart persistence |
| Live Supabase | — | — | BLOCKED until credentials exist |
| Browser UI / responsive | — | — | Not performed (no automated browser run) |

Mocked tests are not live integration tests and are labelled as such in TEST_RESULTS.md.
Run: `cd backend; python -m pytest` and `cd frontend; npm test`.
