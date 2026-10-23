# Online grocery store + staff fraud and security console

Two connected apps in one repository:

* **Customer store** (`/shop`): a modern grocery storefront (search with live suggestions, category rail, filter sidebar with chips, quantity steppers on every product card, saved items, mini-cart with a free-delivery progress bar, order tracker and one-click *Buy again*): browse, add to a cart, check out and **pay for real** with
  card or MTN / Airtel mobile money (through Flutterwave's hosted payment page) or cash on delivery, follow orders, get
  e-mail updates.
* **Staff console** (`/dashboard` and friends), reached from the store's **Staff & admin sign-in** link. Only administrators get in when `CONSOLE_ADMIN_ONLY=true` (the production default); otherwise it is role-gated: **Orders & Risk** (every order with its payment, a transparent
  rule-based risk score and case), Products and Inventory, Investigation Centre, ScamWatch, Security Monitor, fraud alerts and
  the payment-risk model simulator, reports, users and roles, audit trail.

Stack: React + Vite, FastAPI + SQLAlchemy, SQLite locally / PostgreSQL in production, Supabase Auth, Flutterwave payments,
scikit-learn Random Forest (staff simulator only).

> **Deploying for real users? Read [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** (Render + Vercel + Supabase + Flutterwave, with
> an acceptance checklist and a go-live checklist). Everything below is for running it on your own computer.

## Honest status
* Real payments use Flutterwave's hosted page: the store never sees card numbers, PINs or one-time codes. Every payment is
  re-verified with Flutterwave's API before an order is marked paid. This is tested against a faithful **fake** of Flutterwave
  (unit tests and a real-browser run); it has **not** been run against Flutterwave's own sandbox, because that needs your
  account's keys. The acceptance test in `docs/DEPLOYMENT.md` does that in about ten minutes.
* Order risk scores come from `store_risk_v1`, a rule engine that uses only facts the store holds. It is **not machine
  learning** and a score is a signal for a person, never proof of fraud. The trained model (synthetic data) powers only the
  staff "New Payment" simulator.
* The sample catalogue (`SEED_DEMO_DATA=true`) has **invented prices**. A live store turns it off and adds real products in the
  Products screen; the API refuses to start in production otherwise.
* Terms, privacy and delivery pages on a live store are plain starting text; have them reviewed for your business.

## 1. What you need (local development)
Python 3.10+ (tested on 3.14), Node.js 20+ (tested on 22). No other service is required: SQLite, local sign-in and the
simulated payment provider work offline.

## 2. Backend
```powershell
cd backend
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
Edit `backend\.env` and set `LOCAL_AUTH_ENABLED=true` for the offline demo (never on a server others can reach). Then train the
staff-simulator model once and start the API:
```powershell
python -m app.ml.train_model --synthetic
uvicorn main:app --reload
```
API docs: http://127.0.0.1:8000/docs . The database and the sample catalogue are created on first start.

## 3. Frontend (second terminal)
```powershell
cd frontend
copy .env.example .env      # leave VITE_SUPABASE_* empty for the local demo
npm install
npm run dev                 # http://localhost:5173
```
Sign in with one of the four local demo accounts (password `DemoPass!2026`): `customer@example.com`,
`fraud.analyst@example.com`, `security.analyst@example.com`, `admin@example.com`.

## 4. Try real payments locally (Flutterwave test mode)
1. Create a free Flutterwave account, switch to **Test mode**, copy the secret key (`FLWSECK_TEST-...`).
2. In `backend\.env`: `FLW_SECRET_KEY=FLWSECK_TEST-...`, `FLW_WEBHOOK_HASH=<any long random string>`.
3. Restart the API. At checkout, *Visa / Mastercard* and *Mobile Money* are now offered (marked TEST MODE).
   Webhooks cannot reach `localhost`; that is fine locally, because the store also verifies when the customer returns.
   (Use a tunnel such as ngrok only if you want to see webhooks.)

## 5. Tests
```powershell
cd backend ; python -m pytest -q                         # API, payments, risk, catalogue, notifications ...
cd ..\frontend ; npm test ; npm run build                # components and pages
npx playwright install chromium                          # once
npm run test:e2e                                         # real servers + real browser + fake Flutterwave
```
CI (`.github/workflows/tests.yml`) also runs the store tests against real **PostgreSQL**.

## 6. Configuration
Every setting is documented in `backend/.env.example` and `frontend/.env.example`. The ones that matter most:
`DATABASE_URL`, `DB_BACKEND`, `STORE_NAME`, `STORE_CONTACT_*`, `DELIVERY_*`, `COD_ENABLED`, `FLW_*`, `FRONTEND_URL`,
`CORS_ORIGINS`, `SMTP_*` (optional e-mail), `RISK_*` / `ORDER_*` thresholds. In production (`ENVIRONMENT=production`) the API
refuses to start with an unsafe combination and says which setting to fix.

## 7. Project layout
```
backend/   main.py, app/ (routers, services, schemas, core, db, ml), tests/
frontend/  src/ (store/, pages/, components/, context/, services/, tests/), e2e/ (Playwright + fake Flutterwave)
supabase/  optional SQL for DB_BACKEND=supabase
docs/      DEPLOYMENT.md (start here), architecture, data-model, security, testing
render.yaml  frontend/vercel.json  .github/workflows/tests.yml
```

## 8. Troubleshooting
| Symptom | Fix |
|---|---|
| "Cannot reach the server" | Backend not running, or wrong `VITE_API_BASE` (restart `npm run dev` after editing). |
| No demo accounts on the login page | `LOCAL_AUTH_ENABLED=true` in `backend\.env` and empty `VITE_SUPABASE_*` in `frontend\.env`; restart both. |
| Card / mobile money not offered at checkout | `FLW_SECRET_KEY` is empty or the API was not restarted. |
| Paid in test mode but the order stays pending | Open the order's payment page: it verifies with Flutterwave on load and every 5 seconds. |
| "Model unavailable" on New Payment | Run `python -m app.ml.train_model --synthetic` and restart the API. |
| 403 on a staff page | Your role lacks that permission (enforced by the server). |
| `database is locked` | Another process holds the SQLite file; stop duplicate backends. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
