# Dataset and Features

## What was found
No dataset exists in the project or the surrounding folders (`creditcard.csv` is absent, as is any other CSV). The original code
targeted the Kaggle credit-card dataset (`Time`, `V1`-`V28`, `Amount`, `Class`).

## Approach selected: C — clearly labelled synthetic development dataset
Why not the Kaggle dataset (approach B)? Its V1-V28 columns are anonymised PCA components. A payment form cannot supply them,
and mapping unrelated form fields onto them would be fabrication. Why not a real labelled dataset (approach A)? None is available,
and we must not invent labels for real transactions.

Instead `backend/app/ml/synthetic.py` generates rows with the fields the payment form really collects.

| Feature | Type | Allowed values |
|---|---|---|
| amount | number | 0.01 – 1,000,000 |
| hour | integer | 0 – 23 |
| failed_attempts | integer | 0 – 10 |
| new_device | 0/1 | |
| international | 0/1 | |
| customer_avg_spend | number | 0 – 1,000,000 |
| payment_method | category | Card, Bank Transfer, Mobile Money |
| branch | category | Online, Johannesburg CBD, Cape Town V&A, Durban North, Pretoria Central |
| **is_fraud** (target) | 0/1 | |

The single source of truth is `backend/app/ml/feature_schema.py`; its hash is stored in every model file, and a model with a
different hash is refused at load time.

## How the synthetic labels are made (important)
`is_fraud` is drawn from a hand-written logistic formula: higher when the amount is large relative to the customer's average,
the hour is 00:00-04:59, there are failed attempts, a new device, or an international transaction, plus random noise. A Random
Forest trained on this data learns that formula. **Its metrics therefore do not demonstrate real-world fraud-detection
performance.** The API, Settings page and About page say so.

## Audit of the generated dataset (20,000 rows, seed 42)
Columns 9, no missing values, no invalid values by construction (checked by `validate_dataframe`), fraud rate about 6.2%
(1,235 rows), so the classes are imbalanced and the model uses `class_weight="balanced_subsample"`.
Target leakage: the target is not among the features and no feature is derived from it.

## Using a real dataset later
Provide a CSV with the nine columns above, then run `python -m app.ml.train_model --csv path\to\file.csv`. The script validates the
file (missing columns, missing values, labels other than 0/1, out-of-range values, unknown categories) and stops with a clear
message if anything is wrong. Real labelled data should replace the synthetic data before any claim about detection quality.

## Training and evaluation
Stratified 80/20 split with a fixed seed (42). The model is fitted on the training split only; metrics come from the held-out 20%:
precision, recall, F1, PR-AUC, ROC-AUC, confusion matrix and test-set size. The flag threshold is 0.3 (favours recall); risk
bands are Low < 0.3, Medium 0.3-0.7, High >= 0.7. The artifact is written only after it reloads and returns a valid probability.

## Explanations
- Per-transaction "observations" are fixed rule checks on the submitted values (e.g. amount over 3x average). They are **not** an
  explanation of the model's decision.
- "Most important features" in Settings are global Random Forest importances, not explanations of any single prediction.

## Update: two models
- **Payment-form model (approach C, synthetic):** unchanged, drives `/predict` and the New Payment page.
- **PCA demo model (approach A):** `python train_model.py --schema pca` trains on the real Kaggle `creditcard.csv` when you place it in `backend/data`. It is served only through `/pca-demo/*` and the *PCA Model Demo* page, takes the 30 dataset columns exactly, is never fed from the payment form, and its predictions are not saved. **Status: not trained; dataset absent (BLOCKED).** Exact duplicates are removed before the split and counted in the training report.
- `python inspect_dataset.py` measures rows, columns, types, missing/infinite values, duplicates, label counts and fraud percentage from the actual file; see `backend/README.md`.
