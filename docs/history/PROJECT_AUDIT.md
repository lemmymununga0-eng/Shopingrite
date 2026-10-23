# Project Audit (baseline, before MVP work)

Audited by reading every source file. No git repository existed; a file-level checkpoint of the original project
(without `node_modules`) was copied to `../_checkpoint_original/` (36 files). To restore, copy it back over this folder.

## Baseline checks (pre-existing state)
| Check | Result |
|---|---|
| `vite build` (frontend) | PASS (1641 modules, 207 kB JS) |
| `import main` (backend) | PASS |
| Automated tests | None existed |
| Trained model / dataset | NOT present (`creditcard.csv`, `fraud_model.joblib` missing) |
| Screenshots referenced by the brief | NOT present in the repo; UI was preserved from the existing CSS/JSX instead |
| Supabase credentials | NOT present (`frontend/.env` only sets `VITE_DEMO_MODE=true`) |

Environment: Windows 11, Python 3.14.0, Node 22.20, npm 10.9. scikit-learn 1.8, FastAPI 0.136, PyJWT, pytest are installed globally.

## Issues
Severity: C = critical, H = high, M = medium, L = low.

| # | Sev | File | Cause | Fix | Verify |
|---|---|---|---|---|---|
| 1 | C | backend/main.py | No authentication on any route, including `DELETE /transactions` | Verify Supabase JWT in a FastAPI dependency; role checks | auth tests (missing/invalid/expired token) |
| 2 | C | frontend/.env, AuthContext.jsx | `VITE_DEMO_MODE=true` gives every visitor a fake logged-in user; `dist/` was built that way | Remove demo bypass from the normal path; demo mode only via explicit flag, labelled, never reaches real API data | grep + frontend test |
| 3 | C | main.py / train_model.py / PaymentCard.jsx | Model needs Kaggle PCA features V1-V28; payment form collects unrelated fields. No form can produce a real prediction | Approach C: synthetic dataset matching the form (documented in DATASET_AND_FEATURES.md) | train + predict tests |
| 4 | H | main.py | History is one shared JSON file, not per user, rewritten per request (race conditions) | Repository layer: Supabase (RLS) or SQLite for local dev | persistence tests |
| 5 | H | main.py | Browser can POST `amount`, `payment_method` that are stored but not used by the model (displayed values can disagree with the scored values) | Single validated schema; stored values are the scored values | schema tests |
| 6 | H | main.py | `@app.on_event("startup")` deprecated; model load errors only printed | `lifespan`, explicit model status | /health test |
| 7 | H | main.py | No alert review (status / notes); no `PATCH /alerts/{id}`, no `GET /transactions/{id}` | Add endpoints and persistence | alert tests |
| 8 | M | train_model.py | Saved artifact has no version, metrics, or schema hash; stale/incompatible models load silently | Metadata + schema hash check at load | schema-mismatch test |
| 9 | M | main.py | Risk bands hardcoded 0.7/0.3 separately from model threshold | Thresholds in config, returned by /model-info | unit test |
| 10 | M | main.py | CORS origins hardcoded | `CORS_ORIGINS` env setting | config test |
| 11 | M | main.py | No rate limit or request-size limit | Simple in-process limiter on /predict | rate-limit test |
| 12 | M | requirements.txt | Unpinned, no test deps | Pin lower bounds, add pytest/httpx/PyJWT | install check |
| 13 | M | .gitignore | Missing venv, node_modules, model artifacts, datasets, caches | Extend | review |
| 14 | M | PaymentCard.jsx, Dashboard.jsx | Payment form submits nowhere; Dashboard has disabled dummy inputs | Wire to /predict; replace dummy form with a real action | frontend tests |
| 15 | M | Alerts/History/Dashboard | No loading states, search, filters, pagination, review UI | Shared components + features | frontend tests |
| 16 | M | Navbar.jsx | `alert()` for logout errors; no user menu | Inline error | review |
| 17 | M | api.js | No auth header; no 401 handling | Attach Supabase access token; sign out on 401 | frontend tests |
| 18 | L | Dashboard | Currency fixed to USD | Configurable currency (default ZAR) | review |
| 19 | L | Login/Register | No password recovery | Add reset-password flow when Supabase configured | review |
| 20 | L | repo | No tests, no docs beyond README, no migrations | Add tests, docs, SQL migrations | pytest / vitest |
| 21 | L | frontend/dist | Committed build built with demo flag | Rebuild without flag; ignore `dist/` | build |

## Preserved (working) features
Visual design (dark-green topbar, sidebar, white cards, badges), routing, Supabase auth wiring, Model Test concept, honest "no model" 503 behaviour.
