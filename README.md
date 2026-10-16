# Shoprite FraudGuard

Educational fraud-detection MVP: **React + Vite** frontend, **FastAPI** backend, **scikit-learn Random Forest**, **Supabase** (Auth + Postgres).
It scores a payment form and lets analysts review flagged transactions. **It does not process real payments** and is not PCI DSS compliant.

> The bundled model is trained on **synthetic** data, so its metrics do not show real-world fraud-detection performance. See `docs/DATASET_AND_FEATURES.md`.

## Project layout
```
backend/   main.py, app/ (config, auth, routers, schemas, db, ml), tests/, models/ (trained file), legacy_kaggle/ (old script, unused)
frontend/  src/ (pages, components, context, services, tests)
supabase/  migrations/ (SQL for tables + Row Level Security)
docs/      audit, architecture, dataset, security, test plan and results
```

## 1. Software you need
Python 3.10+ (tested on 3.14), Node.js 20+ (tested on 22), VS Code. A free Supabase account is needed for real sign-in (step 5).

## 2. Backend setup (PowerShell, in VS Code: Terminal > New Terminal)
```powershell
cd backend
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```
If PowerShell blocks the activate script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 3. Train the model
```powershell
python -m app.ml.train_model --synthetic
```
This generates the synthetic dataset, trains, prints precision / recall / F1 / PR-AUC / ROC-AUC / confusion matrix and saves `backend\models\fraud_model.joblib`.
To use your own labelled data instead (columns listed in `docs/DATASET_AND_FEATURES.md`): `python -m app.ml.train_model --csv data\transactions.csv`.
Restart the API after retraining.

Dataset, training, reports and API details are in `backend/README.md`. The Kaggle PCA demo model needs `backend\data\creditcard.csv` (see `backend/data/README.md`); the payment-form model works now with `python train_model.py --synthetic`.

## 4. Configure the backend
```powershell
copy .env.example .env
```
Edit `backend\.env` (it is git-ignored). Fill in `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and either `SUPABASE_JWT_SECRET` (projects using the legacy JWT secret) or leave it empty (the API then verifies tokens through your project's JWKS endpoint).
`DB_BACKEND=sqlite` stores data in `backend\data\fraudguard.db` (local development); `DB_BACKEND=supabase` stores it in Supabase with Row Level Security.
Never use or paste the Supabase **service-role** key anywhere in this project.

## 5. Supabase setup
1. Create a project at supabase.com. In **Authentication > Providers** keep Email enabled (decide whether to require email confirmation).
2. In **SQL Editor**, paste and run `supabase\migrations\20261015000001_transactions.sql`.
3. Copy the project URL and **anon** public key (Project Settings > API) into `backend\.env` and `frontend\.env`.
4. Roles: everyone is a `customer` by default. To make someone an analyst or admin, run in the SQL Editor:
   ```sql
   update auth.users set raw_app_meta_data = raw_app_meta_data || '{"role":"analyst"}'::jsonb where email = 'analyst@example.com';
   ```
   (the person must sign in again to get a new token).

## 6. Start the backend
```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn main:app --reload
```
API docs: http://127.0.0.1:8000/docs. Health check: http://127.0.0.1:8000/health.

## 7. Start the frontend (second terminal)
```powershell
cd frontend
copy .env.example .env      # then fill VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY
npm install
npm run dev
```
Open http://localhost:5173, register, confirm your email if required, sign in.

## 8. Run the tests
```powershell
cd backend ; python -m pytest          # API, ML and mocked-Supabase tests
cd ..\frontend ; npm test              # component and API-client tests
cd ..\frontend ; npm run build         # production build
```
Verification passes and their real outcomes are recorded in `docs/TEST_RESULTS.md`.

## Screens and routes
| Route | Screen | Notes |
|---|---|---|
| `/login`, `/register`, `/forgot-password`, `/reset-password` | Authentication | Supabase Auth; show/hide password, validation, returns you to the page you first asked for |
| `/dashboard` | Dashboard | period filter, refresh, 4 summary cards, activity / split / risk charts, latest alerts, recent transactions |
| `/payment-card` | Payment Card | demo card only; default payment method; real recent activity for that method |
| `/payment` | New Payment | the 8 model fields -> `POST /predict`; result, risk, model version, link to details |
| `/model-demo` | PCA Model Demo | separate Kaggle V1-V28 model (needs `backend\data\creditcard.csv` and training) |
| `/alerts` | Fraud Alerts | summary cards, filters (risk, status, dates, search), detail dialog, analyst/admin review with notes |
| `/history` | Transaction History | search, risk/status/date filters, sortable columns, pagination, view details |
| `/transactions/:id` | Transaction Details | fields returned by the API only |
| `/profile`, `/settings`, `/about` | Profile, Settings (5 tabs), About | name edit, password change, real preferences, system status |
Unknown routes show a 404 page. The old `/transaction` address redirects to `/payment`.

Dashboard definitions: *Flag Rate* = flagged / total transactions in the period (model flags, **not** confirmed fraud); *Confirmed Fraud Cases* = alerts an analyst/admin marked confirmed. Charts use the stored records; days with no activity show as zero.

Preferences saved in this browser (Settings): alert bell on/off, default payment method, rows per page. Roles: customers see only their own data; analysts/admins see all and can review alerts.

## Common problems
| Symptom | Fix |
|---|---|
| "Cannot reach the FraudGuard API" | Backend not running, or `VITE_API_BASE` is wrong in `frontend\.env` (restart `npm run dev` after editing) |
| Login page says "Setup required" | `frontend\.env` is missing `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` |
| Everything returns 401 after signing in | Backend `.env` lacks `SUPABASE_JWT_SECRET` and `SUPABASE_URL`, or they belong to a different project |
| "Model unavailable" / 503 on predict | Run step 3 and restart `uvicorn`. After changing `feature_schema.py` you must retrain |
| 503 "database is unavailable" | `DB_BACKEND=supabase` but the migration was not applied, or the URL/key is wrong |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| CORS error in browser console | Add your frontend address to `CORS_ORIGINS` in `backend\.env` |

More: `docs/ARCHITECTURE.md`, `docs/SECURITY_REVIEW.md`, `docs/KNOWN_ISSUES.md`.
