# Test Results

Environment: Windows 11, Python 3.14.0, Node 22.20, npm 10.9. Dates 2026-10-15. All results below are from commands actually run.
Statuses: PASS / FAIL / BLOCKED / SKIPPED. "Mocked" tests do not prove live-service behaviour.

## Pass One — functional verification
| # | Check | Result | Notes |
|---|---|---|---|
| 1 | Python syntax/import (`compileall` app, main, tests) | PASS | |
| 2 | Backend tests (`pytest`) | PASS | 70 passed (first complete run after fixing two defects found by the tests, below) |
| 3 | Frontend tests (`vitest`) | PASS | 48 passed (one test bug fixed: ambiguous text match) |
| 4 | Lint | SKIPPED | no linter is configured in the project |
| 5 | Train model on synthetic data | PASS | 20,000 rows, 1,235 fraud (6.17%); test 4,000 rows. Precision 0.251, Recall 0.623, F1 0.358, PR-AUC 0.393, ROC-AUC 0.842. Synthetic: not real-world evidence |
| 6 | Load saved model + inference | PASS | `Predictor.load` -> available, probability in [0,1] |
| 7 | Persistence (SQLite) via live uvicorn process, then restart | PASS | transaction + analyst review (status, notes) still present after server restart |
| 8 | Persistence (Supabase) | BLOCKED | no credentials |
| 9 | Production build (`npm run build`) | PASS | 1645 modules |
| 10 | Live HTTP smoke (real uvicorn on :8765, scripted client, test-signed JWTs) | PASS | health 200; no token 401; predict 201 (High, flagged); other user 404; customer review 403; analyst review 200; stats; CORS preflight allows only localhost:5173 |
| 11 | Live Supabase auth / RLS / migration | BLOCKED | no project; SQL never executed |
| 12 | `npm audit --omit=dev` | PASS | 0 vulnerabilities after upgrading react-router-dom 6 -> 7 (tests and build re-run and pass) |
| 13 | `npm audit` (incl. dev) | FAIL (known) | 3 remain (tinypool critical, @vitest/mocker moderate) inside the vitest test runner; the fix is vitest 5, which npm could not install here (arborist error). Dev-only; does not ship to users |
| 14 | Python dependency audit | SKIPPED | no tool available |

Defects found and fixed during Pass One: global settings used by auth dependency (every valid token got 401); a `NaN` in the request body produced HTTP 500 instead of 422; float-equality assertion on multi-threaded forest output (test tolerance).

## Pass Two — independent regression and security review
Re-read modified sources, then re-ran everything.
| # | Check | Result | Notes |
|---|---|---|---|
| 1 | Secret scan (service_role, JWT-looking strings, sk_live) across source | PASS | none found; `.env` files git-ignored; only placeholders in `.env.example` |
| 2 | Demo-bypass scan, including built `dist` | PASS | no demo user/flag in source or `dist` |
| 3 | No auth configured on server | PASS | every protected route 401; `auth_configured:false` in /health |
| 4 | Forged token (wrong secret), expired, wrong audience, `alg=none` admin token | PASS | all 401 (alg=none test added as a regression test) |
| 5 | `user_metadata.role=admin` cannot review | PASS | 403 |
| 6 | `DB_BACKEND=supabase` without credentials | PASS | clear startup error |
| 7 | Backend tests re-run | PASS | 71 passed; again 71 passed with `-W error::ResourceWarning` after fix below |
| 8 | Frontend tests re-run | PASS | 48 passed |
| 9 | Production build re-run | PASS | |
| 10 | Frontend/backend contract (field names, pagination, auth header, error shape) | PASS (by tests + live smoke) | frontend tests mock the API, so the contract is checked by reading and by the live smoke, not by a browser run |
| 11 | Previously working features | PASS with changes | health/model-info/predict/history/alerts/settings kept; `/model-info` now requires login; `DELETE /transactions` intentionally removed; old Kaggle-PCA model test replaced by the real payment form |
| 12 | Browser/visual and responsive check | SKIPPED | not performed; no reference screenshots supplied |
| 13 | Login/registration/reset against real Supabase | BLOCKED | no credentials; page logic covered by mocked unit tests only |

Defect found and fixed during Pass Two: the SQLite repository never closed its connections (ResourceWarning, file-lock risk on Windows) — now closed on every call.
Also changed in Pass Two: httpx request logging silenced so Supabase request URLs are not logged.

## Test counts (final)
Backend 71 pass (API 48, ML 17, mocked Supabase adapter 6; includes parameterised cases). Frontend 48 pass (auth/navigation 13, pages 28, API client 7).

---

# Round 2 — ML data pipeline (inspection, PCA demo model, reports)
Same environment. Added: `inspect_dataset.py`, `train_model.py` (root wrapper), `app/ml/{evaluation,pca_demo,dataset_report}.py`, `/pca-demo/*` endpoints, PCA Model Demo page, `scripts/download_kaggle.py`, backend/data/models/reports READMEs.

## Pass 1 — components
| Check | Result | Notes |
|---|---|---|
| Python syntax/imports of new files | PASS | all new modules import; `-W error` parse of scripts |
| Dataset search (Downloads, Desktop, Documents, OneDrive) | PASS (search ran) — **no dataset found** | `creditcard.csv` is not on this computer |
| `python inspect_dataset.py` with the real (missing) dataset | PASS (correct failure) | exit 1, clear message with placement instructions |
| `python train_model.py --schema pca` with the real (missing) dataset | **BLOCKED** | no Kaggle data; no model trained; nothing fabricated |
| `python scripts/download_kaggle.py` | **BLOCKED** | no Kaggle credentials on this machine |
| Inspect/train on a small generated PCA-shaped **test fixture** | PASS | in pytest only; tests use temp folders and never write to `reports/` or `models/` |
| Payment-form model retrain (synthetic) with new metrics | PASS | accuracy 0.862, precision 0.251, recall 0.623, F1 0.358, PR-AUC 0.393, ROC-AUC 0.842, threshold 0.3; confusion TN 3293 FP 460 FN 93 TP 154; test rows 4000 (247 fraud). Synthetic: not real-world evidence. Reports + PNG written to `reports/` |
| Reload saved model and predict | PASS | |
| Backend tests | PASS | 100 passed (also with `-W error::ResourceWarning`) |
| Frontend tests | PASS | 57 passed |
| Production build | PASS | |

## Pass 2 — integration (live server on :8766, throwaway SQLite DB, test-signed JWTs, PCA model trained on the **fixture**)
| Check | Result |
|---|---|
| `/pca-demo/info` without token | PASS (401) |
| `/pca-demo/info` shows model version and data source | PASS (data source labelled "FIXTURE (not Kaggle)") |
| `/pca-demo/predict` valid row; fraud-like row scores higher (0.475 -> 1.0, High) | PASS |
| `/pca-demo/predict` missing feature | PASS (422) |
| PCA predictions not written to history | PASS |
| `/predict` (payment model) -> saved, flagged, alert visible to owner only (other user sees 0) | PASS |
| Analyst review 200, customer review 403 | PASS |
| `/model-info` includes accuracy, classification report, support | PASS |
| Server on :8000 after a clean restart exposes `/pca-demo/info` and `/pca-demo/predict` | PASS (checked via `/openapi.json`; the earlier auto-reload had NOT picked them up, so a restart is required after code changes on Windows) |
| Real Kaggle training / evaluation | **BLOCKED** (dataset) |
| Live Supabase sign-in / RLS | **BLOCKED** (no confirmed account / migration not run) |
| Browser visual check | SKIPPED |

Defects found in Round 2: backslash-n sequences mangled when generating `train_model.py` (caught by a syntax error and repaired); a no-op leftover block in `pca_demo.validate` (removed); a loose assertion in a cleaning test (tightened).


---

# Round 3 — UI/UX pass (design system, all screens, charts)
Added: new palette/tokens, app shell (sidebar with user + logout, top bar with title/search/notifications/user menu), shared components (`ui.jsx`, `forms.jsx`, `charts.jsx`), routes `/dashboard /payment-card /payment /transactions/:id` + 404 + intended-destination redirect, Recharts charts (dashboard lazy-loaded), alert detail dialog, sortable/filterable history, tabbed Settings, editable profile. Backend: date/method/sort filters, extended `/transactions/stats?days=` (one shared pure function for SQLite and Supabase).

| Check | Result | Notes |
|---|---|---|
| Backend tests | PASS | 109 passed (new: stats computation, period, review counts, date range, method filter, sorting incl. injection-style input, alert filters, mocked-Supabase query parameters) |
| Frontend tests | PASS | 88 passed (auth and navigation 25, pages 47, model demo 9, API client 7) |
| Production build | PASS | main bundle 498 kB, dashboard/chart chunk 430 kB loaded only on `/dashboard` |
| `npm audit --omit=dev` | PASS | 0 vulnerabilities (Recharts added) |
| Login and Register at desktop width (real headless Edge screenshot, no session needed) | PASS | viewed |
| Login and Register at 390 px (real 390 px iframe) | PASS | no overflow. A first headless attempt looked broken only because headless Edge has a ~500 px minimum window width |
| Authenticated pages (Dashboard, Alerts, History) at desktop and 390 px — **layout only**, rendered by the real app code in headless Edge against a temporary harness with a fake local session and **fixture API data** (harness deleted afterwards) | PASS (layout) | found and fixed: charts not rendering in screenshots (animation off), unaligned chart cards, missing field labels in mobile table cards, loose password-requirements spacing |
| Tablet width (about 820 px) for authenticated pages | NOT TESTED | login/register tablet screenshots were captured but not inspected |
| Payment Card, New Payment, Settings, Profile, Details, Model Demo visual check | NOT TESTED (visually) | covered by component tests only |
| Keyboard-only walkthrough, screen-reader check, colour-contrast measurement | NOT TESTED | labels, roles, focus styles, Escape-to-close and reduced-motion handling exist and some are unit-tested |
| Real sign-in, real data in the UI, Supabase persistence | BLOCKED | no confirmed Supabase account; migration not run |
| Server on :8000 restarted from the venv exposes new query parameters | PASS | checked through `/openapi.json` |

Backend gaps relative to the brief: no event-history/audit trail per transaction; no server-stored user preferences (preferences are per-browser); profile edits go through Supabase Auth directly; export is not implemented.
