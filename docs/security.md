# Security notes

This is a demonstration MVP. Passing its tests does **not** make it production-ready, and it is not PCI DSS compliant. It never handles real card data.

## Controls in place (each has a test unless marked)

| Area | Control |
|---|---|
| Authentication | Backend verifies every token: signature, expiry, audience, required claims; algorithm confusion blocked (each key type only accepts its own algorithms; `none` rejected). Local demo tokens are accepted only while `LOCAL_AUTH_ENABLED=true`, with the issuer and secret checked. |
| Authorization | One permission table (`app/core/permissions.py`) enforced by `require(permission)` on the server. Hiding menu items is cosmetic. A parametrised test calls 13 endpoints as all four roles and compares with the table. Role comes only from `app_metadata`; `user_metadata` and other claims are ignored. |
| Ownership | Carts and orders are keyed by the token subject; other users get the same 404 as a missing record. Client-supplied user ids are rejected by strict schemas (`extra="forbid"`). |
| Staff separation | Fraud, security, inventory, reports, cases, audit and admin endpoints require staff roles. Customers get 403 (tested in browser and API). |
| Checkout | One database transaction; conditional stock `UPDATE`; rollback on any failure; concurrency tests (threads, service and HTTP level) prove no overselling. Prices and stock come from the database, never the client. |
| Payments | Simulated adapter only. The order schema has no card fields and rejects any (the value is never echoed). No payment credentials are stored. |
| SSRF | ScamWatch never fetches a submitted URL. Private, loopback, link-local and reserved addresses are rejected. A test patches the network transports to fail if any outbound call happens. The optional Safe Browsing adapter talks to one fixed host. |
| Injection | SQLAlchemy parameterised queries; sort/filter inputs whitelisted; `LIKE` wildcards escaped; React escapes output; no `dangerouslySetInnerHTML`. |
| Secrets | `.env` files git-ignored; `.env.example` has placeholders only; a scan confirmed no real env value appears in tracked files or the frontend bundle. Service-role keys are never used. The local demo secret is generated per machine into a git-ignored file. |
| Logging | Security events and audit records pass through `redact()` (tokens, Bearer headers, API keys in URLs, card-like numbers, secret-named keys). httpx request logging is off. Validation errors never echo values. Unhandled errors return a generic message plus a correlation id. |
| Abuse limits | Rate limits on login, checkout, cart writes, ScamWatch and prediction; 20 kB request limit enforced on the bytes actually received (chunked uploads included); page-size caps; field-range validation. |
| Monitoring | Auth, authorization, rate-limit, validation, application, model, provider, privileged and inventory events are recorded with correlation ids; configurable thresholds raise alerts and open cases. |
| Audit | Append-only `audit_events` written in the same transaction as the change (no update/delete API). |
| Local demo auth | Off by default; refuses to start if `ENVIRONMENT=production`; scrypt password hashing; login failures are indistinguishable between unknown user and wrong password; rate limited and logged. |

## Review findings and fixes (found by tests during this work)

| Finding | Fix |
|---|---|
| `normalize_url` accepted private addresses (the rejection was swallowed by an `except ValueError`). | Restructured; tests for loopback, RFC1918, link-local metadata address, IPv6 loopback. |
| Writing a security event while a checkout/login transaction was open blocked for 30 s on SQLite and silently lost the event. | Events are recorded only after the request transaction closes; provider failures are logged by the caller. |
| An analyst could take over a case already assigned to someone else. | Self-assignment over another assignee now needs an administrator. |
| Chunked uploads without `Content-Length` bypassed the size limit. | Byte-counting ASGI middleware replaces the response with 413. |
| A failed sign-in was shown as "session expired". | The 401 handler skips the login endpoint. |
| Accessibility: low contrast (store and console), duplicate/unmatching labels, unlabeled chart SVG, invalid `<dl>` content. | Fixed; axe (WCAG 2.1 A/AA, serious+critical) passes on the tested pages. |

## Known limitations / residual risks

1. **Live Supabase auth, JWKS and RLS were not tested** (no credentials). The roles migration `20261016000001_roles.sql` is also unexecuted. BLOCKED.
2. **Model files use joblib (pickle).** Only the configured local path is loaded; never place downloaded `.joblib` files in `backend/models`. The previous model (pickled by a different scikit-learn) was backed up and retrained locally.
3. **Rate limiter and `ScamWatch` duplicate-event throttle are in memory** (one process).
4. **Local demo accounts use a documented password.** Safe only because local auth is for offline demos; never expose such a server.
5. `/docs` is public unless `DOCS_ENABLED=false`.
6. Tokens for Supabase sessions live in supabase-js browser storage; local demo tokens in `sessionStorage` (cleared when the tab closes). XSS would expose them; no XSS sink was found.
7. No MFA, no account lockout beyond rate limiting, no CSRF protection needed (bearer header, no cookies).
8. SQLite serialises writers (`BEGIN IMMEDIATE`); use PostgreSQL for real concurrency. PostgreSQL support through `DATABASE_URL` was **not exercised** (NOT TESTED).
9. ScamWatch's offline heuristic can only raise suspicion; the Safe Browsing adapter has never been called live (BLOCKED).
10. The fraud model is trained on synthetic data; its scores say nothing about real fraud.
