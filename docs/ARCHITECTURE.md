# Architecture (target for this MVP)

```
Browser (React + Vite)
  /shop/*      Customer store (public browse; cart/checkout/orders need sign-in)
  /dashboard, /alerts, /investigations, ...   FraudGuard staff console (existing paths kept; role-gated)
        | Bearer JWT (Supabase, or local demo token when LOCAL_AUTH_ENABLED)
        v
FastAPI  (app factory)  -- correlation-ID + body-limit + security-event middleware
  routers: system, auth, products, cart, orders, inventory, fraud(transactions/alerts/predict),
           pca-demo, scamwatch, security, investigations, reports, admin, audit
  core: config, permissions, security (token, hashing, redaction), rate limiter
  services: inventory, order, payment(simulated), fraud, order_risk, scamwatch(+providers), investigation, audit, security_events
        |                         |                              |
        v                         v                              v
 SQLAlchemy DB            Legacy Repository               ML artifacts (joblib, local path only)
 (SQLite | PostgreSQL)    (SQLite | Supabase PostgREST)   payment model, PCA demo model
```

## Separation of the two applications
Same repository and API, different front-end shells, navigation, branding and permissions. A customer token can call only store endpoints and its own orders/cart; console endpoints require a staff role on the **backend**. Hiding a menu item is never the control.

## Identity
- Production path: Supabase Auth; backend verifies HS256 secret or JWKS (existing `decode_token`).
- Local path (demo only): `POST /auth/local/login` issues HS256 tokens signed with `LOCAL_AUTH_SECRET` for seeded demo users. Disabled unless `LOCAL_AUTH_ENABLED=true`. The verifier accepts local tokens only when that flag is set.
- Role is read from `app_metadata.role` of the verified token only.

## Data stores
- **SQLAlchemy DB** (`DATABASE_URL`): users (local), categories, products, inventory, carts, orders, security_events, scam_reports, cases, case_notes, audit_events, settings. See `data-model.md`.
- **Legacy transactions table**: model predictions (SQLite or Supabase). Cases refer to predictions by string id, so either backend works.

## Order flow (transactional)
1. `POST /orders` validates input and the delivery option; opens one DB transaction.
2. For each cart line, `UPDATE inventory SET available_quantity = available_quantity - q, reserved_quantity... WHERE product_id = ? AND available_quantity >= q`. Zero rows updated => rollback entire order, return 409 with the unavailable lines.
3. Order and snapshot lines are inserted, stock-adjustment audit events written, cart emptied, commit.
4. Simulated payment adapter returns a labelled demo result (no card data accepted anywhere).
5. Order-risk rules run; anomalies become security events (and optionally cases).

## Fraud model boundaries
Customer checkout never feeds the model. The staff "transaction simulator" sends the 8 fields in `feature_schema.py`. The PCA model accepts only rows already containing Time, V1-V28, Amount. A model score is a signal for review; cases state this.

## Observability
Every request gets `X-Request-ID` (accepted if well-formed, else generated) returned in the response and stored on security events and audit events. Sensitive keys (`authorization`, `password`, `token`, `secret`, `apikey`, card-like numbers) are redacted before storage or logging.
