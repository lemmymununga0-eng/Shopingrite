# Security Review

Not a certification. This is an educational MVP; it is not PCI DSS compliant and must not process real payments.

## Fixed
| Baseline issue | Fix |
|---|---|
| API had no authentication | Every route except `/health` needs a Supabase bearer token, verified by the API (signature, expiry, audience, required `sub`/`exp`) |
| `DELETE /transactions` wiped everything | Removed. No delete endpoint and no DELETE RLS policy exist |
| Fake "demo" logged-in user bypass | Removed from code and from `frontend/.env` (only the `VITE_DEMO_MODE` line was deleted); `dist/` rebuilt, contains no demo user |
| Client could send amount/method unrelated to scored values | One strict schema (`extra="forbid"`); clients cannot send score, risk, prediction, flag or user id (tested) |
| Identity from the browser | `user_id` is always the verified token's `sub` |
| Role trust | Role read only from `app_metadata` (not user-editable). `user_metadata.role` is ignored (tested) |
| Ownership | Customers only see their own rows (SQLite code check; Supabase RLS). Other users' ids return 404, not 403 |
| Alert review by anyone | `PATCH /alerts/{id}` needs analyst/admin (API) and an RLS update policy + trigger limiting updates to review columns |
| Hardcoded CORS | `CORS_ORIGINS` setting; only GET/POST/PATCH and Authorization/Content-Type headers; no credentials |
| No limits | Per-user rate limit on `/predict`, 20 kB body limit, page-size cap 100, field range validation |
| Error leakage | Validation errors do not echo submitted values (this also fixed a 500 on `NaN` input); DB errors return a generic 503; unhandled errors return a generic 500 |
| Stale/incompatible model silently used | Schema hash checked at load; incompatible model => 503 |
| Partial model files | Artifact written to a temp file, reloaded and test-predicted, then renamed into place |
| Secrets | `.env` files git-ignored; `.env.example` placeholders only; service-role key is never used or requested |
| No password recovery | Forgot/reset password pages using Supabase |

## Remaining risks
1. **Live Supabase never tested** — JWKS verification, PostgREST calls and RLS/trigger SQL are untested against a real project (BLOCKED: no credentials). Only mocked HTTP tests exist.
2. **Model loading uses `joblib`/pickle.** Load only model files you trained yourself; never place downloaded `.joblib` files in `backend/models`.
3. **Rate limiter is in-memory** (one process); restarting resets it, several workers each keep their own.
4. **Dashboard stats for Supabase** read up to 10,000 rows client-side; use a SQL view/RPC for larger data.
5. `/docs` and `/openapi.json` are public (they expose no data). Disable for production if desired.
6. No audit log of who viewed data; no MFA; relies on Supabase email confirmation settings.
7. Frontend access token is held by supabase-js in browser storage (library default), so XSS would expose it. No `dangerouslySetInnerHTML` is used.
8. `npm audit` / dependency scanning results are in TEST_RESULTS.md; Python dependency auditing tools were not available.
9. Roles must be assigned by an admin in Supabase (SQL below); there is no in-app admin screen.

```sql
update auth.users set raw_app_meta_data = raw_app_meta_data || '{"role":"analyst"}'::jsonb where email = 'analyst@example.com';
```
