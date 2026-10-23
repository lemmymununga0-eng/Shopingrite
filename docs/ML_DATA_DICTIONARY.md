# ML data dictionary

Everything below is read from the dataset files and the saved model metadata, not assumed. Training data lives in
`backend/data/external/` (git-ignored). Model artifacts live in `backend/artifacts/fraud/` (git-ignored).

## Datasets actually used

| Dataset | File | Rows (raw → cleaned) | Positive class | Licence | Used for |
|---|---|---|---|---|---|
| Credit-card fraud (ULB), OpenML mirror id 1597 | `creditcard-openml/creditcard_openml.parquet` | 284,807 → 283,726 (1,081 exact duplicates removed) | 473 fraud (0.167%) | "Public" per OpenML | Task A: `creditcard_pca` |
| PhiUSIIL Phishing URL | `phiusiil/PhiUSIIL_Phishing_URL_Dataset.csv` | 235,795 → 235,370 (425 duplicate URLs removed) | 100,520 phishing (42.7%) | CC BY 4.0 (Prasad & Chandra, 2024) | Task B: `url_phishing` |

Each download has a manifest (`manifest.json`) with source URL, time, licence, size and sha256. Training refuses a file whose
checksum no longer matches. Verify with `python scripts/fetch_datasets.py verify`.

### Not used (and why)

| Dataset | Status |
|---|---|
| PaySim (Kaggle) | **BLOCKED**: needs a Kaggle account token (`~/.kaggle/kaggle.json`). No Hugging Face mirror has a verified licence, so none is substituted. Training code exists: `python -m app.ml.train --dataset paysim` exits 3 with the exact download command until the file is present. |
| Kaggle credit-card original, IEEE-CIS | BLOCKED, same reason (Kaggle credentials; IEEE-CIS also needs competition rules acceptance). The OpenML mirror above holds the same ULB data. |
| Open Food Facts, OpenStreetMap | Product and geography reference data. **Never** fraud-training data. |
| Instacart | Not downloaded; Kaggle competition rules apply (licence unverified) and it is not fraud data. |

## Task A: `creditcard_pca`

Target `Class` (shipped as text `'0'/'1'`, converted to integer; any other value stops training).

| Feature | Meaning |
|---|---|
| `V1`–`V28` | PCA components of the original (undisclosed) card features. Anonymised by the data owner; their meaning is unknowable. |
| `Amount` | Transaction amount, log-transformed inside the pipeline. |
| `Time` | Seconds since the first transaction (two-day window). **Not used raw**; converted to a 24-hour sin/cos cycle. Recorded in `excluded_features`. |

Consequence: the model can only score rows that already contain V1–V28. **A grocery order cannot supply them**, so store orders are
recorded as `unsupported_input_schema` (never scored, never padded with zeros).

## Task B: `url_phishing`

Target `is_phishing = 1 - label` (the dataset labels phishing as 0 and legitimate as 1; this is inverted deliberately and tested).
Inputs are computed from the **URL text only** by `url_features_one` in `backend/app/ml/datasets.py` (lengths, character counts, host/path/query structure, IP-host flag, TLD, keyword hits; the exact ordered list is `URL_FEATURE_NAMES`).

Excluded on purpose: all page-content columns (need fetching the page), dataset-wide statistics columns that cannot be recomputed for one
new URL (`URLSimilarityIndex`, `CharContinuationRate`, `TLDLegitimateProb`, `URLCharProb`), and identifiers (`FILENAME`, `Domain`, `Title`).
`Domain` is used only as the **group key** so one site never lands in both train and test.

## Task C: store orders

Store fields: order total, currency, hour placed (plus the rule-engine inputs). Neither model's inputs exist in the store, so the
recorded status is `unsupported_input_schema` with the list of missing features. The `store_risk_v1` rule engine remains the basis
for store decisions.

## Tables added

| Table | Purpose |
|---|---|
| `ml_predictions` | One row per (order, trigger, payment reference, model): status, model version, threshold, probability (null unless status `ok`), missing features. Unique constraint prevents duplicates. |
| `order_outcomes` | Append-only reviewer conclusions (`confirmed_fraud`, `false_positive`, `legitimate`, `undetermined`) with a `verified` flag. Only verified rows may be used as future labels. Nothing retrains automatically. |

Payments in this store are real Flutterwave hosted checkout when configured, or labelled simulated/COD; orders, payment attempts and
status history already existed and are unchanged.
