# ML implementation plan and checklist

Status key: [x] done and verified · [~] done, with a stated limitation · [ ] not done · [B] blocked

## Phase 0: audit
- [x] Read existing ML, router, store-risk and ScamWatch code
- [x] Independently verify downloader claims (`ML_AUDIT_REPORT.md`)

## Phase 1: datasets
- [x] Repair downloader (retries, schema checks, manifest + sha256, `status`/`verify`, licence acceptance)
- [x] Download ULB credit-card (OpenML mirror) and PhiUSIIL; both pass `verify`
- [B] PaySim, Kaggle credit-card, IEEE-CIS: need a Kaggle token
- [x] Data kept out of Git

## Phase 2: framework
- [x] Splits (stratified, group, chronological) with overlap assertion
- [x] Leakage exclusions recorded in metadata
- [x] Baselines + cross-validation, isotonic calibration, out-of-fold threshold, full metrics
- [x] Validation gate incl. fresh-process reload
- [x] Versioned registry with checksum, promote, rollback

## Phase 3: training
- [x] `python -m app.ml.train --dataset creditcard-openml` promoted
- [x] `python -m app.ml.train --dataset phiusiil` promoted
- [B] `--dataset paysim` (exit code 3 with exact command until the file exists)

## Phase 4: backend
- [x] `ModelService` loaded once at start-up; states ready / not_trained / artifact_missing / schema_incompatible / failed_validation
- [x] `GET /fraud/model-status`, `POST /fraud/predict` (strict names, ranges, no padding)
- [~] Legacy `/pca-demo` left on the old loader

## Phase 5: store integration
- [x] `ml_predictions` (unique per order/trigger/payment ref/model), `order_outcomes`, migration 6
- [x] Hook in `order_risk.evaluate`; alert only for a genuine flagged `ok` prediction
- [x] `POST/GET /staff/orders/{id}/outcome`, `GET /staff/ml-summary`
- [x] ScamWatch `ml_url` provider (opt-in; suspicion only)

## Phase 6: frontend
- [x] Dashboard model panel from real metadata + counts
- [x] Order detail shows model results and outcome form (fraud.review roles)

## Phase 7: tests
- [x] Downloader (mocked network), ML framework (fixtures), API, store integration, vitest
- [~] Playwright e2e re-run (see report)

## Phase 8: docs
- [x] `ML_AUDIT_REPORT.md`, `docs/ML_DATA_DICTIONARY.md`, `docs/ML_EVALUATION.md`, `ML_IMPLEMENTATION_REPORT.md`

## Phase 2: grocery-store transactions
- [x] Audit store fields; versioned schema `grocery_txn_v1` + docs
- [B] Grocery-labelled dataset: none exists (0 verified outcomes; PaySim blocked and not a match)
- [x] Verified-label export + reproducible training pipeline that refuses without enough labels
- [x] Experimental/shadow-mode policy, schema-version refusal, rollback
- [x] Store flow: order + payment attempt + assessment (rules) + model record (event id, idempotent) + case policy
- [x] Console displays method, model status, label progress, outcomes
- [x] Tests: backend 538, vitest 235, Playwright 25
- [ ] Random audit sampling tool, rules-vs-model comparison (future)
