# STORE_IMPLEMENTATION_PLAN.md

Principle: extend what works (FastAPI, SQLAlchemy, React, existing cart/order/inventory services and their tests). No rewrite. Each phase ends with tests run and results recorded in `IMPLEMENTATION_REPORT.md`. Schema changes are additive migrations, never resets.

## Phase 1: Audit and plan (done)
`STORE_AUDIT.md`, this file, stale-test fix.

## Phase 2: Catalogue, provenance, images, storefront polish
* Migration: `brands`, product columns (`brand_id`, `pack_size`, `price_status` = verified|estimated, `price_source_*`), `price_history`, `product_images` (url/path, alt text, source, licence, attribution, status), `promotions` (start/end, applicable area).
* Seed loader reads a reviewable data file (`backend/data/catalogue/*.csv|json`) with source URL, source type, date checked, store/location per product. Idempotent; never overwrites admin edits.
* Research Zambian products and prices with web search; record each in `docs/product-pricing-sources.md`. Anything not verifiable is `estimated`, shown as such to staff, and the storefront labels demonstration pricing honestly.
* Images: only licensed/free sources (Wikimedia Commons, Open Food Facts, manufacturer media with permission). Retailer images are not copied or hot-linked. Products without a correct image get a labelled placeholder and an entry in a catalogue image audit report. The wrong spinach image is replaced.
* Storefront: homepage banners/featured/offers from DB, delivery-area picker, sort (price, name, popularity from order counts), price-range and availability filters, pagination, related products, recently viewed, image fallback and `alt`, mobile nav, footer pages (delivery, privacy, terms).

## Phase 3: Cart and inventory
* Keep existing cart service. Add `stock_movements` ledger (every change with reason, actor, order) and `stock_reservations` with expiry.
* Reserve stock when an order awaits payment; release on failure, cancel or expiry (background sweep plus lazy release on read); deduct on paid or on confirmed cash-on-delivery.
* Tests: concurrency (two buyers, last unit), reservation expiry, ledger totals match inventory.

## Phase 4: Checkout and payments
* Step flow: customer details (Zambian phone `+260`/`09x`/`07x` validation), delivery (areas, fee rules, optional slots, labelled estimates), review, payment method, place order.
* `POST /checkout` requires an `Idempotency-Key`; same key returns the same order. Table `idempotency_keys`.
* Order states: `awaiting_payment`, `paid`, `payment_failed`, `cancelled`, then fulfilment states (`confirmed`, `picking`, `ready`, `out_for_delivery`, `completed`). Enforced transition table with `order_status_history`.
* Payment provider interface (`initiate`, `status`, `parse_webhook`). Implementations: **Simulated** (customer chooses success, failure, pending, cancelled, action-required in demo mode; unmistakable labelling; never asks for card numbers, PINs or OTPs), **Cash on delivery** (admin-enabled flag), and **stubs** for Airtel Money, MTN MoMo, card gateway that return `BLOCKED: not configured`. No endpoints invented; before any real adapter I will read the provider's current official docs.
* `payment_attempts` and `payment_events` with unique references; webhook endpoint with signature verification and duplicate-event protection ready for a real provider, exercised with the simulated provider's signed callbacks.
* Payment-result pages for all five states; confirmation page only says "paid" when status is paid (or labelled SIMULATED).

## Phase 5: FraudGuard integration
* New `store_risk_v1` rule engine: inputs are order amount, customer history, hour, failed payment attempts, order velocity, new delivery address, first-order flag, bulk quantity, payment method. Output stored in `fraud_assessments`: engine name and version, features used, score, decision (allow/review/high), plain-language reasons, timestamp. Labelled "rule-based, not machine learning" everywhere.
* Assessment runs at order creation and again on each payment attempt result. Threshold hit creates an alert and a case (reusing `ensure_case`).
* The existing ML model is untouched and stays on the manual "New Payment" screen. It is not called for orders because `new_device` and `international` have no real source (see audit section 4).
* Staff **Transaction explorer** lists orders joined to payments and assessments, with the same order and payment references; detail page shows risk indicators, linked alerts and cases, analyst notes and audit history. Staff views show masked contact details (for example `+260 97* *** 123`); full details only for roles that need them, and viewing is audited.
* Dashboard figures computed from stored rows.

## Phase 6: Admin and operations
* Product create/edit, price edit (writes `price_history`), image management, stock adjustment (writes ledger), order management (status transitions, cancel), payments monitor, delivery-area/fee settings, COD toggle, integration status page showing BLOCKED providers truthfully.

## Phase 7: Testing and hardening
* Backend: all items in the brief's section 12 list.
* Frontend: browsing, filters, cart, checkout validation, payment states, confirmation, order history, staff review, mobile layout.
* E2E (Playwright): full journey from storefront to staff console for success, plus failed and pending payments, verifying order, payment attempt, stock movement and assessment persisted.
* Production build, `npm audit`, `pip-audit`, restart-persistence check, independent re-read of the diff. Results reported as run, with failures stated.

## Honest limits I expect at the end
* Real Airtel/MTN/card payments: BLOCKED until merchant credentials exist.
* Prices not confirmed from a dated source: marked estimated.
* Product images: licensed or placeholder only; branded retailer photos will not be copied.
* Live Supabase: still untested.
* Rule-based fraud scoring, not a trained retail model, because no labelled retail fraud data exists.
