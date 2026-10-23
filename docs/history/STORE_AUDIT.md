# STORE_AUDIT.md: findings from the existing project (2026-10-17)

Method: read the repository, ran `pytest` and `npm test` and `npm run build`. Browser E2E (`npm run test:e2e`) was **not** re-run for this audit.

## 1. Architecture as found

| Layer | What exists |
|---|---|
| Frontend | React + Vite + React Router. Two shells: customer store (`/shop/*`, `src/store/`) and staff console (`/dashboard` etc., `src/pages/`). |
| Backend | FastAPI + Pydantic + SQLAlchemy, about 49 endpoints in `backend/app/routers/`. Roles: customer, fraud_analyst, security_analyst, admin, enforced server-side. |
| Database | SQLite (`backend/data/fraudguard_app.db`), PostgreSQL optional but untested. Hand-written mini migration runner in `app/db/migrations/__init__.py`. |
| Auth | Local demo sign-in (`LOCAL_AUTH_ENABLED`) or Supabase (never tested live). |
| ML | RandomForest on **synthetic** data, 8 features (see section 4). Separate Kaggle-PCA demo model, untrained on real data. |
| Tests | Backend 299 (298 passed before today's fix; all pass now in `test_orders.py`), frontend 140 pass, build passes. |

## 2. What already works

* Catalogue: 40 seeded products, 8 categories, search, category filter, product pages, offer price, featured flag, stock status.
* Persistent cart in the database, server-side price and stock validation, quantity limits.
* Checkout creating durable orders with item snapshots; transaction-safe stock deduction with race and rollback tests; cancellation restores stock.
* Order ownership returns 404 for other customers.
* Staff console: dashboard, investigations (cases with notes), ScamWatch, Security Monitor, inventory, reports, users/roles, audit trail, integrations page.
* Order-risk **rules** (high value, bulk quantity, velocity, repeated rejections) open cases.
* Money is stored as integer cents with an explicit currency column. Default currency is now ZMW.
* Fix made today: `test_currency_mismatch_is_refused_not_mixed` used `ZMW` as the "foreign" currency, which stopped being foreign when the default became ZMW. It now uses `USD`.

## 3. What is missing or broken, measured against the brief

| # | Gap | Evidence |
|---|---|---|
| 1 | **Store orders do not reach FraudGuard.** Checkout never calls the model and never writes a `transactions` / fraud-assessment record. The staff Transactions, Alerts and History pages only show payments typed in by hand on "New Payment". | `order_risk.py` docstring: "Customer checkout never calls the fraud model". |
| 2 | **No payment model.** Payment is two string columns on `orders` (`payment_mode`, `payment_status`) and `SimulatedPaymentAdapter.authorize()` always returns approved. No payment attempts table, no references, no pending/failed/cancelled/action-required states, no retry, no provider abstraction, no webhooks. | `payment_service.py`, `models.py` `Order`. |
| 3 | **No idempotency.** Double-clicking checkout can only be stopped by the cart being emptied; there is no idempotency key. | grep: no idempotency handling in routers/schemas. |
| 4 | **Order states too thin.** Orders start as `confirmed`; there is no `awaiting_payment`, `payment_failed`, or `paid` state and no reservation expiry. | `ck_order_status` constraint. |
| 5 | **Product data is not retail-grade.** No brand, no pack size field (only a free-text `unit`), no price source URL, source type, date checked, store/location, promo start/end, price history, or "estimated vs verified" flag. Names are generic ("Bananas", "Full Cream Milk"). Prices are invented (`DEMO-` SKUs). | `Product` model, `seed.py`. |
| 6 | **Images are generic and sometimes wrong.** 23 JPEGs in `frontend/public/products/` come from Wikimedia Commons (credited in `credits.json`). They are not product photographs. At least one is clearly the wrong product: `DEMO-FP-004` (Baby Spinach) uses a "Palak Paneer" dish photo. Several products have no image. One image per product, no alt-text field, no source field in the database (attribution is a JSON file). | `credits.json`, `ls public/products`. |
| 7 | **Catalogue is small and not Zambian.** 40 products; categories are generic. No mealie meal, kapenta, nshima staples, Zambian brands, ZMW price research. | `seed.py`. |
| 8 | **Checkout is one form,** not the step-by-step flow asked for. Address uses `city` + `postal_code`; no area/neighbourhood, delivery instructions, Zambian phone validation, delivery slots or per-area fees. | `Order` model, `Checkout.jsx`. |
| 9 | **No store management UI.** The only admin product function is stock adjustment. No create/edit product, price edit, image management, or order management screen (status endpoint exists, no UI confirmed). | routers list, `InventoryMonitor.jsx`. |
| 10 | **Staff transaction views are separate from orders.** Transaction detail does not show order reference, payment attempts, linked alerts/cases or an audit history for the transaction. | routers `transactions.py`. |
| 11 | **Customer account:** register/sign-in/profile exist, but profile edits are local to the browser for demo accounts, and no saved addresses. | `Profile.jsx`, known issues. |
| 12 | **Migrations are hand-rolled** (no Alembic). Adequate for SQLite demo; weak for Postgres and for the many new tables below. | `db/migrations/`. |
| 13 | **Real payments, live Supabase, live Safe Browsing** remain BLOCKED (no credentials). | `IMPLEMENTATION_REPORT.md`. |
| 14 | **Documentation is duplicated/stale** (`docs/KNOWN_ISSUES.md` still says ZAR and "no browser check"; two audits, two plans, `security.md` vs `SECURITY_REVIEW.md`). | `docs/`. |

## 4. The FraudGuard model: what it accepts

`backend/app/ml/feature_schema.py` (not the Kaggle schema; the brief's Kaggle worry applies only to the separate PCA demo model):

| Feature | Can a real store order supply it honestly? |
|---|---|
| `amount` | Yes, order total in ZMW (model unit is a plain number; training data was synthetic). |
| `hour` | Yes, hour of order creation. |
| `failed_attempts` | Yes, once payment attempts are persisted (failed attempts for this customer in a recent window). |
| `customer_avg_spend` | Yes, from the customer's own order history (needs a defined fallback for first-time customers). |
| `payment_method` | Partly. Model categories are `Card`, `Bank Transfer`, `Mobile Money`. Mapping: card to Card, Airtel/MTN to Mobile Money. **Cash on delivery and simulated have no valid category** and must not be forced into one. |
| `branch` | Partly. Categories include `Online`; store orders would be `Online`. |
| `new_device` | **No.** The app does not collect a device fingerprint. Passing 0 or 1 would be invented. |
| `international` | **No.** There is no card-issuer country or IP geolocation. Passing a value would be invented. |

Conclusion: the 8-feature model **cannot be called honestly on a store order today**. Two features have no real source. Its training labels also come from a hand-written formula on synthetic data, so a "prediction" is not evidence of fraud.

**Recommendation:** build a separate, clearly labelled `store_risk_v1` rule engine for orders, using only fields that exist (amount vs customer history, hour, failed payment attempts, velocity, new delivery address, amount in the first order, bulk quantity, payment method). Store its version, features, score, decision and plain-language reasons. Never describe it as machine learning. Keep the existing model for the manual "New Payment" screen, or optionally feed it only if device and country signals are later collected.

## 5. Tables and endpoints needed (summary; details in the plan)

New tables: `product_images`, `product_price_sources`, `price_history`, `brands`, `stock_movements`, `stock_reservations`, `payment_attempts`, `payment_events` (webhook log), `delivery_areas`, `delivery_slots`, `promotions`, `fraud_assessments`, `idempotency_keys`, `order_status_history`. Extended: `products` (brand, pack size, price provenance, `price_status` verified/estimated), `orders` (area, instructions, delivery slot, new status set), `cases`/`security_events` (link to assessment and order).

New endpoints: `/checkout/quote`, `/checkout` (idempotency key), `/payments/{attempt}`, `/payments/simulated/{attempt}/resolve`, `/payments/webhooks/{provider}`, `/delivery/areas`, `/delivery/slots`, `/admin/products` CRUD, `/admin/products/{id}/images`, `/admin/orders`, `/admin/payments`, `/staff/transactions` (orders joined to payments and assessments), `/staff/assessments`.

## 6. Risks

1. The brief asks for real photographs of real branded products and verified Zambian prices. Retailer images are normally copyrighted and the sites' terms often forbid copying. I cannot verify prices or image rights from here without live research and your decision on image policy. Anything unverifiable must be marked **estimated** and **placeholder image**, not presented as real.
2. Real Airtel Money / MTN / card payments need merchant accounts. They stay BLOCKED.
3. A rule engine is honest but will not detect real fraud patterns; this is a demonstration of workflow.
