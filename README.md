# FraudGuard: demonstration grocery store + staff security console

Two connected apps in one project:

* **Customer store** (`/shop`): browse a sample grocery catalogue, search and filter, add to a cart, check out with a **simulated** payment, see order history.
* **FraudGuard staff console** (`/dashboard` and friends): transaction-risk model, ScamWatch (suspicious websites), Security Monitor, Investigation Centre (cases), inventory and order risk, reports, users and roles, audit trail.

> **This is an independent demonstration.** It is not affiliated with, endorsed by, or connected to Shoprite or any other retailer. Products, stock and customers are sample data. Payment is simulated: no card details are collected and no money moves. The fraud model is trained on **synthetic** data, so its scores say nothing about real fraud. A model score is a signal for a person to review, never proof of wrongdoing.

Stack: React + Vite + React Router, FastAPI + Pydantic + SQLAlchemy, scikit-learn Random Forest, SQLite locally (PostgreSQL optional), Supabase Auth optional.

## 1. What you need
Python 3.10+ (tested on 3.14), Node.js 20+ (tested on 22), VS Code. Nothing else for the local demo; Supabase is optional.

## 2. Backend setup (PowerShell: VS Code > Terminal > New Terminal)
```powershell
cd backend
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env      # skip this if you already have a backend\.env you want to keep
```
If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Edit `backend\.env` (it is git-ignored) and set, for the offline demo:
```
LOCAL_AUTH_ENABLED=true
```
That adds a **local demonstration sign-in** with four demo accounts. Never turn it on for a server other people can reach. Everything else works with the defaults.

## 3. Train the model (needed once)
```powershell
python -m app.ml.train_model --synthetic
```
This generates a synthetic development dataset, trains, prints precision / recall / F1 / PR-AUC / ROC-AUC and the confusion matrix, and saves `backend\models\fraud_model.joblib`. Use `--threshold 0.4` to store a different decision threshold, or set `MODEL_THRESHOLD` in `.env` to override it later without retraining.

**Kaggle dataset (optional PCA demo model):** download `creditcard.csv` from https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud (free account, accept the terms), put it in `backend\data\`, then:
```powershell
python inspect_dataset.py
python -m app.ml.train_model --schema pca
```
The Kaggle columns (`Time`, `V1`..`V28`, `Amount`; `Class` is the label and is never used as an input) cannot be made from ordinary retail fields, so this model is exposed only on its own staff page ("PCA Model Demo") and the customer checkout never uses it. A realistic retail model needs a properly labelled retail dataset.

## 4. Start the backend
```powershell
uvicorn main:app --reload
```
API docs: http://127.0.0.1:8000/docs . Health: http://127.0.0.1:8000/health . The app database (`backend\data\fraudguard_app.db`) and the sample catalogue are created automatically on first start. Restarting keeps your data.

## 5. Start the frontend (second terminal)
```powershell
cd frontend
copy .env.example .env      # skip if you already have one
npm install
npm run dev
```
**For the local demo leave `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` empty** in `frontend\.env` (restart `npm run dev` after editing). If they are filled in, the app uses Supabase sign-in instead and the demo accounts will not appear.

Open http://localhost:5173 . Click **Sign in**, then pick an account:

| Demo account (local sign-in only) | Role | Sees |
|---|---|---|
| customer@example.com | Customer | the store |
| fraud.analyst@example.com | Fraud analyst | fraud alerts, cases, reports |
| security.analyst@example.com | Security analyst | Security Monitor, ScamWatch review, audit trail |
| admin@example.com | Administrator | everything, users, stock adjustments |

Demo password for all four: `DemoPass!2026`. These accounts exist only while `LOCAL_AUTH_ENABLED=true`.

## 6. Try the demonstration checkout
1. Sign in as the customer, search "milk", open the product (the stock label comes from the database), add 2 to the cart.
2. Cart > Proceed to checkout. The page says plainly that payment is simulated and asks for no card details. Delivery is available in the cities listed in `DELIVERY_CITIES`; collection is free.
3. Place the order. You get an order reference; stock is reduced in the database; the order appears under **My orders**. Items that sell out in the meantime are reported and nothing is deducted.
4. Sign in as the fraud analyst, open **New Payment**, enter a risky example (amount 9000, hour 2, failed attempts 5, new device yes, international yes) and see the real model response. A flagged result opens a case under **Investigations**.

## 7. Run the tests
```powershell
cd backend ; python -m pytest -q
cd ..\frontend ; npm test ; npm run build
npx playwright install chromium     # once
npm run test:e2e                    # real servers + browser (ports 8799 and 5199)
```
See `docs/testing.md`; real results are in `IMPLEMENTATION_REPORT.md`.

## 8. Configuration
All settings are in `backend\.env.example` (documented placeholders) and `frontend\.env.example`. Highlights: `DATABASE_URL`, `STORE_NAME`, `STORE_CURRENCY` (default `ZAR`; the store never mixes currencies), delivery fee/threshold/cities, rate limits, `MODEL_THRESHOLD`, `RISK_HIGH`/`RISK_MEDIUM`, ScamWatch providers, `DOCS_ENABLED`, `CORS_ORIGINS`, `VITE_API_BASE`, `VITE_APP_BRAND`.

### Supabase (optional, for real sign-in)
1. Create a project; keep Email sign-in on. Run `supabase\migrations\20261015000001_transactions.sql`, then `20261016000001_roles.sql` in the SQL editor.
2. Put the project URL and **anon** key in `frontend\.env`; the URL and either the JWT secret (HS256 projects) or nothing (JWKS) in `backend\.env`. Never use the service-role key anywhere here.
3. Roles are set in Supabase: `update auth.users set raw_app_meta_data = raw_app_meta_data || '{"role":"security_analyst"}'::jsonb where email = '...';` (`customer`, `fraud_analyst`, `security_analyst`, `admin`; the person must sign in again).
Live Supabase sign-in and RLS have **not** been tested in this repository (no credentials).

### ScamWatch providers
`SCAMWATCH_PROVIDERS=heuristic` (default) uses offline rules that can raise suspicion but can never prove a site safe or malicious. `safebrowsing` adds Google Safe Browsing: set `SAFE_BROWSING_API_KEY` (this sends the URL to Google; check their terms and quotas). `mock` (development only) returns scripted answers from `SCAMWATCH_MOCK_VERDICTS`. The submitted address is never fetched by this server. "No known threat detected" never means "safe". Live provider calls have not been verified here.

## 9. Project layout
```
backend/   main.py, app/ (routers, services, schemas, core, db, ml), tests/, models/, data/
frontend/  src/ (store/, pages/, components/, layouts/, context/, services/, tests/), e2e/
supabase/  migrations/
docs/      architecture, data-model, security, testing, requirements-traceability
AUDIT_REPORT.md  IMPLEMENTATION_PLAN.md  IMPLEMENTATION_REPORT.md
```

## 10. Troubleshooting
| Symptom | Fix |
|---|---|
| "Cannot reach the FraudGuard API" | Backend not running, or wrong `VITE_API_BASE` (restart `npm run dev` after editing). |
| No demo accounts on the login page | Backend needs `LOCAL_AUTH_ENABLED=true`, and `frontend\.env` must have empty `VITE_SUPABASE_*`. Restart both. |
| "Model unavailable" / 503 on predict | Run step 3 and restart the backend. |
| Everything returns 401 | The token is for a different project or has expired; sign in again. |
| 403 on a staff page | Your role does not have that permission (enforced by the server). |
| `database is locked` | Another process holds the SQLite file; stop duplicate backends. |
| Port already in use | Another dev server is running; stop it or change the port. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Playwright cannot find a browser | `npx playwright install chromium` |
| scikit-learn "InconsistentVersionWarning" | The model file was made with another version: retrain with step 3. |
