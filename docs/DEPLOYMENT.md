# Deployment guide: Render (API) + Vercel (website) + Supabase (sign-in) + Flutterwave (payments)

Follow the parts in order. Part 1-4 get a working store with **test** payments (no real money). Part 5 is the checklist
for switching to real money. Nothing here needs code changes: only settings.

```
Customer's browser ──► Vercel (website, /frontend)
        │                    │  calls
        │                    ▼
        │              Render (API, /backend) ──► PostgreSQL  (orders, products, cases, audit)
        │                    ▲      │
        │  pays on           │      └──────────► Flutterwave API (verify every payment)
        └──► Flutterwave ────┘ webhook
   Sign-in: Supabase Auth (the API only verifies its tokens)
```

## 0. What you need before you start
* The code in a GitHub repository: https://github.com/lemmymununga0-eng/Shopingrite (branch `master`, already pushed).
  `.env` files are git-ignored and must never be committed. Read `docs/PRODUCTION_READINESS.md` first: it lists what is verified and what is not.
* Accounts: Render, Vercel, Supabase (you have a project), Flutterwave (a free account gives test keys).

## 1. Database (PostgreSQL)
Pick one:
* **Supabase (recommended, no 30-day expiry)**: Project Settings > Database > Connection string > *Session pooler* (or
  *Direct*) > URI. Replace `[YOUR-PASSWORD]`. Do not use the *transaction* pooler on port 6543 unless you know you need it.
* **Render Postgres**: create a database in the same Render region and copy its *Internal Database URL*.

Keep the URL for step 2 (`DATABASE_URL`). The API creates every table itself on first start, and applies new
schema steps automatically on later deploys (`backend/app/db/migrations`).

## 2. API on Render
1. Render dashboard > **New > Blueprint** > pick the repository. Render reads `render.yaml` and proposes the `store-api` service.
2. Fill in the secrets Render asks for:

| Variable | Value |
|---|---|
| `DATABASE_URL` | from step 1 |
| `SUPABASE_URL` | Supabase > Project Settings > API > Project URL |
| `SUPABASE_ANON_KEY` | the **anon / publishable** key (never the service-role key) |
| `SUPABASE_JWT_SECRET` | Project Settings > API > JWT secret. **Leave empty** if your project uses asymmetric signing keys; the API then reads Supabase's public keys itself |
| `CORS_ORIGINS` | your Vercel address, e.g. `https://my-shop.vercel.app` (no trailing slash; fill in after step 3, then redeploy) |
| `FRONTEND_URL` | the same Vercel address |
| `STORE_NAME` | your shop's name |
| `FLW_SECRET_KEY` | `FLWSECK_TEST-...` from Flutterwave (Part 4) |
| `FLW_WEBHOOK_HASH` | a long random string you invent, for example from `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `CONSOLE_ADMIN_ONLY` | `true` (default in `render.yaml`): only administrator accounts can enter the staff console; fraud/security analyst accounts are treated as customers. Set `false` to let analysts use their own screens |
| `STORE_CONTACT_EMAIL`, `STORE_CONTACT_PHONE`, `STORE_CONTACT_ADDRESS`, `STORE_LEGAL_NAME` | shown on the Contact / Terms / Privacy pages. The e-mail is **required** |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | optional: customers get order confirmed / progress / refund e-mails. Any SMTP service (Brevo, SendGrid, Mailgun, Zoho ...). Leave `SMTP_HOST` empty to send none |
| `SCAMWATCH_PROTECTED_BRANDS`, `SCAMWATCH_OFFICIAL_DOMAINS` | your own brand name and real web addresses, so look-alike websites are flagged (defaults are placeholders) |

3. Deploy. The build installs Python packages and trains the risk model (`python -m app.ml.train_model --synthetic`).
   The service refuses to start if a setting is unsafe for production and says exactly which one (check **Logs**).
4. Open `https://<your-service>.onrender.com/health`: it should answer `{"status":"ok",...}`.

> Use a paid always-on instance (`plan: starter`). A free instance sleeps after 15 minutes; the first payment
> confirmation after a sleep is slow, and the safety-net job that settles missed webhooks does not run while it sleeps.

## 3. Website on Vercel
1. Vercel > **Add New > Project** > the same repository. Set **Root Directory** to `frontend`. Framework: Vite (auto-detected).
2. Environment variables (Production): `VITE_API_BASE` = your Render address (no trailing slash),
   `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_APP_BRAND` = your shop's name.
3. Deploy, then put the Vercel address into Render's `CORS_ORIGINS` and `FRONTEND_URL` and redeploy the API.
4. Supabase > Authentication > URL Configuration: set **Site URL** to the Vercel address and add it to **Redirect URLs**
   (password reset and e-mail confirmation links come back here).

## 4. Staff accounts
Customers register themselves on the website. Staff roles are set in Supabase (the website cannot grant them):
Supabase > SQL editor:
```sql
update auth.users
set raw_app_meta_data = raw_app_meta_data || '{"role":"admin"}'::jsonb
where email = 'you@example.com';
```
Roles: `admin`, `fraud_analyst`, `security_analyst` (anything else is a customer). The person signs out and in again.
The first administrator can then add products under **Products** and watch **Orders & Risk**.

## 5. Payments with Flutterwave
### 5a. Test mode (do this first)
1. Flutterwave dashboard, **Test mode** switched on > Settings > API keys > copy the **secret key** (`FLWSECK_TEST-...`) into Render's `FLW_SECRET_KEY`.
2. Settings > **Webhooks**: URL `https://<your-service>.onrender.com/payments/webhooks/flutterwave`, **Secret hash** = the exact
   `FLW_WEBHOOK_HASH` value, and turn webhook retries on. (Flutterwave retries three times, 30 minutes apart; the store also re-checks pending payments every minute.)
3. Settings > Checkout / payment methods: make sure **preferred / dashboard payment methods do not override** the methods the
   store asks for (Flutterwave's wording varies: "Disable preferred payment methods" must be OFF), and that **Card** and
   **Zambia mobile money** are enabled for ZMW.
4. **Acceptance test** (all must pass before real money):
   - [ ] Add a product (Products screen), sign in as a customer, buy it with *Visa / Mastercard* using a Flutterwave test card
         (Flutterwave's Testing page lists them) > redirected back > "Payment successful" > order **Confirmed**, stock reduced.
   - [ ] Buy with *MTN Mobile Money* using any number and the OTP `123456` (Flutterwave test mode approves Zambian mobile money automatically).
   - [ ] Close the payment page without paying > **Stop this payment** > order allows a retry.
   - [ ] As admin: the order shows under **Orders & Risk** with a risk score and the payment attempt.
   - [ ] Cancel a paid test order > status *Refund pending* > **Refund customer** works.
   - [ ] Render logs show no `amount_mismatch` or `webhook_bad_signature` events (Security Monitor).
   - [ ] **Webhook delivery**: in Flutterwave > Webhooks, the delivery log shows `200` responses.

Two details in Flutterwave's documentation are ambiguous, so confirm them in this test: (1) the hosted page must offer Zambian
mobile money when the store sends `payment_options: "mobilemoneyzambia"`; (2) the customer's phone number is sent as
`customer.phonenumber`. If either misbehaves, the fix is one line in `backend/app/services/flutterwave.py` and
`payment_service.py` (`FLW_OPTIONS`).

### 5b. Going live (real money): checklist
- [ ] Flutterwave account fully activated (business verification and settlement account completed in their dashboard).
- [ ] Acceptance test above passed on **test** keys on the production Render service.
- [ ] Replace `FLW_SECRET_KEY` with the **live** key (`FLWSECK-...`), set the webhook (URL + secret hash) again in **live** mode.
- [ ] Real products entered with real prices and images you may use; `SEED_DEMO_DATA=false`, `STORE_IS_DEMO=false` (the API refuses to start otherwise).
- [ ] Make one small real purchase yourself, then refund it from **Orders & Risk**.
- [ ] Put the store's real terms, delivery and privacy text in `frontend/src/store/Info.jsx` (they are placeholders until you edit them).
- [ ] Decide who handles refunds (administrators only) and watch **Orders & Risk** for *Refund pending* daily.
- [ ] Rotate any secret that was ever pasted into chat, e-mail or an unprotected file (including the local `backend/.env`, `frontend/.env`).

## 6. How payments stay correct (what to know when something looks odd)
* The website never decides a payment succeeded. After paying, the customer returns to `/shop/payment/<order>`; the API asks
  Flutterwave directly (`verify_by_reference`) and accepts only a **successful** result with the right reference, currency and
  an amount at least the order total. Anything else is logged as `payment.amount_mismatch` and the order stays unpaid.
* Webhooks only tell the API to check. A background job re-checks pending payments every minute, so a lost webhook or a
  closed browser tab still settles.
* A customer who pays **after** cancelling or after the 30-minute stock hold is not lost: the order is marked *Refund pending*.
* Orders are held for `PAYMENT_HOLD_MINUTES` (30); unpaid orders then cancel and the stock returns to sale.
* Staff see customers' phone and e-mail **masked**; only administrators see them in full (each view is audited).

## 7. Troubleshooting
| Symptom | Fix |
|---|---|
| Render log: `Unsafe production configuration` | The list names each setting to change. |
| Website says "Cannot reach the server" | `VITE_API_BASE` wrong, or `CORS_ORIGINS` is not exactly the Vercel address. |
| Sign-in works but every request is 401 | `SUPABASE_URL` differs from the website's, or the JWT secret is wrong (leave it empty for asymmetric-key projects). |
| "Online payments are not available" | `FLW_SECRET_KEY` empty/wrong on Render. |
| Paid, but the order stays *Pending* | Webhook URL or secret hash wrong (Flutterwave delivery log shows 401); the minute-by-minute check settles it within about two minutes anyway. |
| Customers cannot register | Supabase > Authentication > e-mail provider / rate limits / Site URL. |
| `psycopg` / connection errors | Use the **session** pooler or direct connection string; the password must be URL-encoded. |

## 8. Trained models in production (optional: the store works without them)
* Orders are always assessed by the rule engine `store_risk_v1`. The dashboard model panel shows each trained model as **Not trained**
  on a new deployment: that is correct, not an error.
* The card (V1-V28) and phishing models are research/ScamWatch models. To use the phishing signal in ScamWatch, train it where the data is
  available and copy `backend/artifacts/fraud/url_phishing/` to the server (or train on a one-off job with `pip install -r requirements-ml.txt`,
  `python scripts/fetch_datasets.py get phiusiil --accept-licence`, `python -m app.ml.train --dataset phiusiil`), set `SCAMWATCH_PROVIDERS=heuristic,ml_url`,
  and read the limits in `docs/ML_EVALUATION.md` first (the dataset makes the task look easier than real life).
* A grocery model needs verified outcomes first: see `docs/LABEL_COLLECTION.md`. Until then record outcomes in **Orders & Risk** and review the audit sample on the dashboard.
* Render installs only `requirements.txt` (runtime). `requirements-ml.txt` adds training tools; `requirements-dev.txt` adds the test tools.
* Set `ML_ARTIFACT_DIR` if you keep model files on a Render persistent disk (the default is `backend/artifacts/fraud`, which is wiped on each deploy).
