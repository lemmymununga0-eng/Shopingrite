# Known issues and limits (current)

Older audits and reports are in `docs/history/`; they describe earlier states and are kept for reference only.

## Needs something from you before it can be proven (cannot be done from the code alone)
1. **Flutterwave sandbox and live behaviour.** The payment flow is tested end to end against a faithful fake (backend tests
   and a real-browser run). Two points in Flutterwave's own documentation are ambiguous and must be confirmed with the
   acceptance test in `docs/DEPLOYMENT.md`: that the hosted page offers Zambian mobile money for `payment_options:
   "mobilemoneyzambia"`, and the customer phone field name (`phonenumber`).
2. **Supabase sign-in in production.** Sign-up, e-mail confirmation, password reset and role claims were never run against a
   live project here (no credentials, and creating accounts is something only you should do). The API's token checks are
   covered by tests with signed test tokens.
3. **PostgreSQL.** The code is written for it and CI runs the store tests against a real PostgreSQL service, but nobody has
   run it on the machine this was developed on (no database server installed). The first push to GitHub shows the result.
4. **Real catalogue.** The sample catalogue has invented prices and generic images; production refuses to start with it. Real
   products, prices and images you may use must be entered by you in the Products screen. There is no image upload (files
   would vanish on most hosts); use an `https://` link or a file in `frontend/public/products/`.
5. **Legal text.** Terms, privacy and delivery pages on a live store are plain starting text; have them reviewed.

## Product limits
* Staff roles are assigned in Supabase (SQL), not inside the app: the app never holds Supabase's service-role key.
* No in-app editing of delivery fees/areas (they are settings), no delivery slots, no per-area fees, no saved addresses.
* Order risk uses rules, not machine learning. The trained model (synthetic data) powers only the staff "New Payment" simulator.
* E-mail covers order confirmed / progress / cancelled / refunded. There is no SMS or push, and no e-mail to staff.
* Refunds are always for the full order amount; partial refunds are done in Flutterwave's dashboard.
* One currency per store (ZMW by default); amounts are never converted.

## Operations limits
* The rate limiter and the "similar security events" throttle are in memory: with several API instances limits apply per instance.
* Real mobile-money confirmations can take minutes; the payment page checks every 5 seconds for 3 minutes, and the server also
  re-checks every minute, so a late confirmation still settles.
* A free Render instance sleeps; use an always-on plan for payments.
* Image credits page and demo wording appear only in demonstration mode (`STORE_IS_DEMO=true`).

## Dependency notes
* `npm audit` (full) reports advisories inside the vitest test runner (dev-only, never shipped). `npm audit --omit=dev` and
  `pip-audit` are run in CI.
* Model files use joblib (pickle): only ever load a model you trained yourself; the production build trains one on the server.
