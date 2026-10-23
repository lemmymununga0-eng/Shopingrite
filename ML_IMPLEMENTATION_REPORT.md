# ML implementation report

Date: 2026-10-23. Statuses: PASS / FAIL / BLOCKED / NOT TESTED.

## Result in one paragraph
Two real-data models are trained, validated and live: card-transaction fraud (`creditcard_pca`, held-out PR-AUC 0.80) and ScamWatch URL phishing
(`url_phishing`, PR-AUC 0.9986, with strong dataset artefacts). The PaySim mobile-money model is BLOCKED by a missing Kaggle token. The store itself
**cannot** be scored by either model because it does not collect their inputs; orders record `unsupported_input_schema` and the `store_risk_v1` rule engine
stays authoritative. Nothing is fabricated.

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Previous agent's claims independently verified | PASS | `ML_AUDIT_REPORT.md` (wrong test path, Kaggle credit-card not downloadable as claimed) |
| 2 | Downloader repaired, manifest/checksum/licence, data out of Git | PASS | 24 offline tests; `git check-ignore` confirms `backend/data/external/` and `backend/artifacts/` ignored; nothing tracked |
| 3 | Credit-card data downloaded and verified | PASS | 284,807 rows, sha256 manifest, `verify` OK |
| 4 | PhiUSIIL downloaded and verified | PASS | 235,795 rows |
| 5 | PaySim / Kaggle / IEEE-CIS downloaded | **BLOCKED** | Needs `~/.kaggle/kaggle.json`; no unverified mirror substituted |
| 6 | Leakage-safe training (split first, train-only fitting, no tuning on test) | PASS | `framework.py`; tests for overlap, threshold, calibration |
| 7 | Baselines, CV, threshold, calibration, full metrics | PASS | `docs/ML_EVALUATION.md` |
| 8 | Versioned artifacts, checksum, fresh-process reload, rollback, no replacement before validation | PASS | registry tests incl. tampered file refused |
| 9 | One documented training entry point | PASS | `python -m app.ml.train` |
| 10 | Credit-card model trained and promoted | PASS | PR-AUC 0.800, precision 0.926, recall 0.789 (95 test fraud rows: wide error bars) |
| 11 | Phishing model trained and promoted | PASS (caveat) | PR-AUC 0.9986; legitimate rows are 100% bare HTTPS roots, so real-world accuracy will be lower |
| 12 | PaySim model trained | **BLOCKED** | `--dataset paysim` exits 3 with the exact command |
| 13 | Model loaded once; strict validation; honest states | PASS | `app/ml/service.py`, `tests/test_fraud_api.py` (10 tests) |
| 14 | `GET /fraud/model-status`, `POST /fraud/predict`; no fabricated scores; staff only | PASS | customers get 403; untrained gives 503 with no probability |
| 15 | Store persists prediction/status/version/threshold idempotently | PASS | `ml_predictions` unique key; `tests/test_store_ml.py` (6 tests) |
| 16 | Alert policy | PASS | alert only for genuine flagged `ok` results; unsupported/unavailable never alert |
| 17 | Verified analyst outcomes, append-only, no auto-retrain | PASS | `order_outcomes`, `fraud.review` permission, audit event |
| 18 | Store orders scored by the fraud model | **NOT POSSIBLE by design** | inputs absent; documented as `unsupported_input_schema` |
| 19 | Dashboard shows real status/metrics/counts | PASS | `FraudModelPanel`, 3 vitest tests |
| 20 | ScamWatch ML provider | PASS | opt-in, suspicion only, skipped when untrained, 2 tests |
| 21 | Backend regression | PASS | **500 passed** (`pytest tests`) |
| 22 | Frontend regression | PASS | **231 vitest passed** |
| 23 | Playwright e2e after these changes | **NOT TESTED** | last run (25 passing) predates the ML work; not re-run |
| 24 | Real payments (Flutterwave) end to end | NOT TESTED live | only against a fake; needs real keys |
| 25 | Live store model performance | NOT TESTED | no verified store labels exist |

## Commands

```bash
cd backend
python scripts/fetch_datasets.py status | verify
python scripts/fetch_datasets.py get creditcard-openml --accept-licence
python -m app.ml.train --dataset creditcard-openml        # promotes only if the gate passes
python -m app.ml.train --dataset phiusiil
python -m app.ml.train --list-models
python -m app.ml.train --rollback creditcard_pca
python -m pytest tests
# optional ScamWatch model signal:  SCAMWATCH_PROVIDERS=heuristic,ml_url
```

## Limitations and risks
- Artifacts are git-ignored: a new deployment shows "Not trained" until training is run there or artifacts are copied (set `ML_ARTIFACT_DIR`).
- The datasets sit in an OneDrive folder, which syncs them to the cloud.
- Card-model metrics rest on 95 fraud rows from two days in 2013; treat as a pipeline proof, not a store guarantee.
- Legacy `/pca-demo` still uses the old single-file loader; `/fraud/*` is the supported path.
- Fixture models used in tests are labelled `is_fixture` and never promoted.

## Rollback
`python -m app.ml.train --rollback <model>` restores the previous promoted version (checksum re-verified). Removing `backend/artifacts/fraud/<model>/current.json`
returns that model to "Not trained". Migration 6 only adds two tables.

---

# Phase 2: risk detection on actual grocery-store transactions (2026-10-23)

## Answer in short
- **Is there grocery-specific labelled data?** No. The store has recorded 0 verified outcomes, PaySim is BLOCKED (Kaggle token) and is a mobile-money simulation whose fields do not match grocery orders, and the public card data is anonymised.
- **Was a compatible supervised model trained?** **No, and none is claimed.** `python -m app.ml.train_store` exits 3 (BLOCKED) with "no verified outcomes yet". The only store models ever trained in this repo are tiny test fixtures (`is_fixture`) inside the test suite.
- **What assesses store orders today?** The rule engine **`store_risk_v1`** (labelled "rules" in the API and console). Every order also records what the `store_grocery` and `creditcard_pca` models could say: currently `model_unavailable` (no store model) and `unsupported_input_schema` / `model_unavailable` (card model), never a score.
- **Real held-out metrics for a grocery model:** none exist, so none are reported. (Card and phishing model metrics from phase 1 are unchanged and unrelated to store orders.)

## Supported store features (`grocery_txn_v1`, `docs/STORE_FEATURE_SCHEMA.md`)
12 inputs, all recorded at order time: order total, largest line quantity, customer's orders in the last hour, prior orders, prior paid orders, average paid total, failed payments in 24 h, rejected checkouts in 10 min, delivery-address-seen-before flag, fulfilment, local hour, payment method (+ a ZMW-only currency guard).
**Not available** (and therefore never used): IP, device, country, card data, customer text fields. **Excluded as leakage:** this order's payment/refund/delivery outcome and the analyst verdict.
Found while auditing: the real payment method id is `mtn_momo` (my first draft said `mtn_money`); the schema is now checked against a real checkout's stored snapshot in a test.

## What was built
| Item | Where |
|---|---|
| Versioned schema + strict validation (unsupported / invalid, no padding) | `app/ml/store_schema.py`, `GET /fraud/store-schema` |
| Verified-label dataset (verified `confirmed_fraud`=1; `legitimate`/`false_positive`=0; unverified, undetermined and unreviewed excluded; placement-time snapshot; newest outcome wins) | `app/ml/store_dataset.py` |
| Reproducible training from the store DB: customer-grouped 80/20 split, baselines, CV, OOF threshold and calibration, gate, versioning, rollback; refuses below 150 verified fraud / 1,000 legitimate / 50 customers; **EXPERIMENTAL below 1,000 verified fraud** | `python -m app.ml.train_store [--status|--export|--no-promote]` |
| Model service handles `store_grocery`; a model trained on another schema version is refused (`schema_incompatible`) | `app/ml/service.py` |
| Per-event model record with `event_id`, `experimental` flag; migration 7; idempotent | `ml_predictions`, `services/ml_scoring.py` |
| Alert policy: an alert needs status `ok` + flagged + **not experimental**. Experimental models run in shadow mode | `ml_scoring.alert_worthy` |
| Console: dashboard says "rules, not a trained model", shows verified-label progress; order detail shows rules, model results, experimental tag and an outcome form | `FraudModelPanel`, `StaffOrders` |
| Process documentation (label definition, selection-bias mitigation, commands) | `docs/LABEL_COLLECTION.md` |

## Which transactions are evaluated by what
| Event | Evaluated by |
|---|---|
| Every checkout (any payment method, simulated or real) | **Rules** `store_risk_v1` (always) |
| Same event, model record | `store_grocery`: `model_unavailable` until a model is trained and promoted; then `ok` (experimental, no alerts) |
| Same event, research model | `creditcard_pca`: `unsupported_input_schema` (needs V1-V28) |
| Non-ZMW currency, unknown payment method, malformed values | `unsupported_input_schema` / `invalid_input` |
Payment outcome is stored separately from the assessment: a paid order can be "review", and a high score is never treated as fraud.

## Tests actually run (this phase)
| Suite | Result |
|---|---|
| Backend `pytest tests` (full) | **538 passed** |
| New this phase | `tests/test_store_model.py` (38): schema validation (every missing field, sensitive/unexpected fields, bad values, currency), real-checkout snapshot validates, label rules, newest-wins, placement-time snapshot, training refusal, customer-grouped split, shadow mode (no alert), non-experimental alert, schema-version refusal, predict endpoint, access control, and one end-to-end checkout test (idempotent replay → 1 order / 1 payment attempt / 1 assessment / 2 model records → case → staff view → customer isolation → unverified vs verified outcome → label) |
| Frontend vitest (full) | **235 passed** |
| Playwright e2e (real backend + browser) | **25 passed**; the staff-order test now also checks "model unavailable" with no percentage shown and records an outcome through the UI |
Playwright first failed twice on my own new selectors (label substring ambiguity), then passed after the test was fixed; no product code changed for that.

## Remaining blockers and limits
1. **Verified labels** are the blocker for any supervised grocery model; `docs/LABEL_COLLECTION.md` is the path. Estimated need: ~150 verified fraud cases for a first (experimental) model.
2. Selection bias: staff mostly review rule-flagged orders. The weekly random audit sample is a documented process, **not yet enforced or tracked by software**.
3. No comparison of a model against the rules on the same test rows is implemented yet (needed before trusting any future model).
4. Real Flutterwave payments are only tested against a fake; live keys are required.
5. Model artifacts are git-ignored; a fresh deployment shows "Not trained" until trained there.
6. Legacy `/pca-demo` still uses the older loader.

---

# Phase 3: the phishing model was an artefact, and what was done about it (2026-10-23)

While preparing the journal paper, a perturbation test showed that the `url_phishing` model I had promoted (PR-AUC 0.9986) learned how the dataset's addresses were formatted,
not phishing. Every legitimate address in PhiUSIIL is `https://www.<domain>` with no path or trailing slash. Removing "www." from held-out legitimate addresses took the flagged share from
0.1% to 100%; rewriting phishing addresses in the legitimate format cut detection from 99.5% to 29.6%. Details and numbers: `docs/ML_EVALUATION.md`, `research/results/phishing_*.json`.

| Item | Status |
|---|---|
| Old model removed from the registry (replaced by a host-name-only model) | DONE |
| Robustness gate (`url_invariance_checks`) in the training entry point; the old feature set fails all 5 checks | DONE, tested |
| URL models are always `experimental`; ScamWatch `ml_url` skips them (no verdict is ever shown) | DONE, tested |
| Replacement: host-name features, threshold at 1% false alarms (held-out PR-AUC 0.863, precision 0.979, recall 0.523, 0.8% false alarms on benchmark data) | DONE, weak, experimental |
| Model scoring made single-threaded and single-pass (card model: median 330 ms to about 26 ms) | DONE, tested |
| A usable URL model | **BLOCKED**: needs legitimate addresses sampled like real traffic (paths, http, no "www.", small sites) |
