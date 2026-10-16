# Data model

Money is stored as **integer minor units** (cents) with an explicit `currency` per record; the store has one configured currency (`STORE_CURRENCY`, default `ZAR`) and mixing is rejected.

## SQLAlchemy database (`DATABASE_URL`)

| Table | Key columns | Constraints / indexes |
|---|---|---|
| `app_users` (local demo identities only) | id (uuid str), email, full_name, role, password_hash, is_active, created_at | unique(email); role CHECK in 4 roles |
| `categories` | id, slug, name, sort_order | unique(slug) |
| `products` | id, sku, name, description, category_id, price_cents, currency, image_ref, is_active, is_featured, offer_price_cents (nullable), unit, created_at, updated_at | unique(sku); CHECK price_cents >= 0; index(category_id, is_active) |
| `inventory` | product_id (PK, FK), available_quantity, reserved_quantity, reorder_threshold, updated_at | CHECK available_quantity >= 0, reserved_quantity >= 0 |
| `carts` | id, user_id, updated_at | unique(user_id) |
| `cart_items` | id, cart_id, product_id, quantity | unique(cart_id, product_id); CHECK quantity > 0 |
| `orders` | id, reference, user_id, status, fulfilment (delivery/collection), contact_name, contact_email, contact_phone, address_line, city, postal_code, subtotal_cents, delivery_fee_cents, total_cents, currency, payment_mode ("SIMULATED"), payment_status, created_at, updated_at | unique(reference); index(user_id, created_at) |
| `order_items` | id, order_id, product_id, sku, name_snapshot, unit_price_cents, quantity, line_total_cents | snapshots of purchased values |
| `security_events` | id, created_at, severity, category, event_type, message, actor_id, ip_hash, path, method, status_code, correlation_id, details_json | indexes on created_at, severity, category |
| `scam_reports` | id, normalized_url, url_hash, domain, report_count, first_reported_at, last_reported_at, reporter_id, verdict, provider_summary_json, review_status, analyst_notes, reviewed_by, reviewed_at | unique(url_hash) (duplicate handling) |
| `cases` | id, case_reference, source_type, source_record_id, severity, status, summary, evidence_reference, assigned_to, created_by, created_at, updated_at, resolved_at | unique(source_type, source_record_id) (idempotent auto-creation); status CHECK |
| `case_notes` | id, case_id, author_id, body, created_at | |
| `audit_events` | id, created_at, actor_id, actor_role, action, entity_type, entity_id, before_json, after_json, correlation_id | append-only (no update/delete API) |
| `alert_thresholds` | key (PK), value, updated_by, updated_at | |

## Legacy table (unchanged)
`transactions` (SQLite or Supabase): model prediction records with review status. `cases.source_type = 'fraud_prediction'` points at `transactions.id`.

## Statuses
- Order: `confirmed`, `cancelled` (demo flow; fulfilment statuses `picking`, `ready`, `out_for_delivery`, `completed` advanced by staff with permission).
- Case: `new`, `investigating`, `confirmed`, `false_positive`, `resolved`.
- Scam report review: `pending`, `reviewed_malicious`, `reviewed_benign`, `dismissed`.
- Severity: `info`, `low`, `medium`, `high`, `critical`.

## Seed data
`app.db.seed` creates categories, ~40 clearly labelled **demonstration** products with sample inventory (including low-stock and out-of-stock items) and four demo users. Seed is idempotent (keyed on SKU/email) and never deletes or overwrites existing rows.
