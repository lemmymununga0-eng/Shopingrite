# Known Issues and Limitations

> **Update (store + console MVP):** this file describes the earlier fraud-only prototype. The current blockers and limits are in
> `IMPLEMENTATION_REPORT.md` (section "Remaining blockers") and `docs/security.md` (section "Known limitations"). Items 1-2 below
> (live Supabase, Kaggle dataset) are still BLOCKED; items 3-4 are now covered by an axe/375 px browser run, which is not a full
> accessibility audit or a pixel comparison with any reference design.


## Blockers (cannot be completed without something from you)
1. **Live Supabase sign-in is untested.** A project URL, publishable key and JWT secret are now configured locally (git-ignored `.env` files) and the project's JWKS endpoint was fetched, but no account has completed sign-in (email-confirmation rate limit hit) and the SQL migration has not been run. Sign-up/sign-in, JWKS token verification, PostgREST calls, the SQL migration, RLS policies and the update trigger have not been run against a real project. Only mocked HTTP tests and a SQLite-backed live server run were done.
2. **Kaggle dataset not on this computer.** The PCA demo model is built and tested on a fixture but untrained on real data; `scripts/download_kaggle.py` needs your Kaggle token. 2b. **No real labelled payment dataset.** The model is trained on synthetic data; its metrics are not evidence of real fraud-detection quality.
3. **Screenshots were not supplied.** The existing CSS/layout was kept and extended; it could not be compared to your reference images.
4. **No browser/visual check.** Pages were verified by component tests and a production build, not by looking at them in a browser or testing real phone widths.

## Limitations
- Per-transaction "observations" are fixed rules, not model explanations (no SHAP/LIME).
- Rate limiter is in-memory, single process.
- Supabase dashboard statistics read at most 10,000 rows; use a SQL view for more.
- Model loading uses pickle (joblib): only load files you trained yourself.
- No in-app admin screen: analyst/admin roles are assigned in Supabase with SQL (see README).
- `backend/legacy_kaggle/train_model_kaggle_pca.py` is the old Kaggle PCA script, kept for reference and unused. `backend/data/predictions.json` is the old empty history file, now unused.
- Currency is shown as ZAR; amounts have no currency conversion.
- Payment Card page stores only a payment-method preference in browser localStorage.

## Dependency advisories (see TEST_RESULTS.md for the latest `npm audit`)
- Python: no auditing tool was available, so Python dependencies were not scanned.
