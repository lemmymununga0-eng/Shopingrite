# FraudGuard backend

FastAPI service that scores transactions with scikit-learn Random Forest models. It does **not** process real payments.

## Two models, two datasets (read this first)
| | Payment-form model | PCA demo model |
|---|---|---|
| Used by | `POST /predict` and the **New Payment** page | `POST /pca-demo/predict` and the **PCA Model Demo** page |
| Data | 8 payment-form fields (`app/ml/feature_schema.py`) | Kaggle `creditcard.csv`: `Time`, `V1`–`V28`, `Amount`, label `Class` |
| Training data available now | **Synthetic** (labels from a formula). Metrics are a pipeline demonstration only | **Not yet trained: dataset not on this computer (BLOCKED)** |
| Saved to | `models/fraud_model.joblib` | `models/pca_demo_model.joblib` |
| Saved to history/DB | Yes | No |

Why two? The Kaggle V1–V28 columns are anonymised PCA components. They cannot be calculated from an amount, payment method, hour, etc., so the payment form can never drive that model. Nothing in this project maps form fields onto PCA features.

## Dataset: source, placement, limits
- **Source:** Kaggle "Credit Card Fraud Detection", https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud (ULB Machine Learning Group; database contents licence DbCL v1.0 – check the page and accept its terms before downloading).
- **What it is:** real but anonymised European card transactions (Sept 2013), 31 columns, `Class` 0 = legitimate, 1 = fraud, described by its publisher as extremely imbalanced (fraud well under 1% of rows; confirm with `inspect_dataset.py`). Row counts are *measured* by `inspect_dataset.py`, not assumed.
- **Limits:** two days of 2013 data, PCA-transformed features, no merchant/device/country fields; not representative of Shoprite or of South African payments.
- **Place the file at:** `backend\data\creditcard.csv` (see `data/README.md`). It is git-ignored.
- **Optional automatic download** (needs your own Kaggle token; nothing is ever hard-coded): `pip install kaggle`, save `kaggle.json` in `%USERPROFILE%\.kaggle`, then `python scripts\download_kaggle.py`.
- **Synthetic fallback** exists only for the payment-form model (`--synthetic`). It is never offered for the PCA model and is not Shoprite data.

## Setup (Windows PowerShell, from the project root)
```powershell
cd backend
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env        # then edit .env (see main README for Supabase values)
```

## Inspect, train, evaluate
```powershell
python inspect_dataset.py                       # looks for data\creditcard.csv; writes reports\dataset_report.txt/.json
python inspect_dataset.py data\other.csv --target label   # other file / label name
python train_model.py --schema pca              # PCA demo model from data\creditcard.csv
python train_model.py --synthetic               # payment-form model, synthetic data (development)
python train_model.py --csv data\payments.csv   # payment-form model on your own labelled CSV
```
`inspect_dataset.py` stops with a clear message if the file is missing, not a `.csv`, empty, unreadable, lacks the expected columns, has labels other than 0/1, or has a single class. Exit code 0 = ready to train.

**What training does:** validates the schema; reports (never silently) rows dropped for missing/infinite values and exact duplicates (duplicates are removed *before* the split so a row cannot appear in both train and test); stratified 80/20 split with seed 42; fits on the training part only; evaluates once on the untouched test part; saves the model only after it reloads and predicts. Nothing is tuned against the test set. A failed run never overwrites an existing model.

**Outputs** (in `reports\`): `*_training_report.txt/.json` (accuracy, precision, recall, F1, PR-AUC, ROC-AUC, confusion matrix, per-class report, support, threshold) and `*_confusion_matrix.png`. Model metadata (version, time, source, features and order, split, parameters, metrics, threshold) is stored inside the `.joblib` file.

**Reading the metrics:** accuracy is misleading when fraud is rare (a model that always answers "legitimate" scores very high accuracy on data that is almost all legitimate). A *false negative* is fraud that slips through; a *false positive* is a good payment flagged. Recall measures how much fraud is caught, precision how many flags are right; the threshold trades them off. ROC-AUC/PR-AUC are reported as `n/a` when the test set contains one class, and a warning is printed when it has fewer than 30 fraud rows.

## Run the API
```powershell
uvicorn main:app --reload
```
Docs: http://127.0.0.1:8000/docs. Every route except `/health` needs `Authorization: Bearer <Supabase access token>`.

| Endpoint | Purpose |
|---|---|
| `GET /health` | status, model loaded, database backend |
| `GET /model-info` | payment model version, metrics, threshold, global feature importance |
| `POST /predict` | score one payment, save it, create an alert if flagged |
| `GET /transactions`, `/transactions/{id}`, `/transactions/stats` | history (own rows; analysts see all) |
| `GET /alerts`, `PATCH /alerts/{id}` | flagged transactions; review (analyst/admin) |
| `GET /pca-demo/info`, `POST /pca-demo/predict` | Kaggle PCA demo model (not saved) |

Example (`$token` = a Supabase access token):
```powershell
curl.exe -X POST http://127.0.0.1:8000/predict -H "Authorization: Bearer $token" -H "Content-Type: application/json" `
  -d '{\"transaction_reference\":\"TX-1001\",\"amount\":250,\"payment_method\":\"Card\",\"hour\":14,\"failed_attempts\":0,\"new_device\":false,\"international\":false,\"customer_avg_spend\":240,\"branch\":\"Online\"}'
```
Response (values come from the model): `transaction.probability`, `risk`, `prediction`, `is_flagged`, `model_version`, `contributing_factors`, `saved`. The probability is a model **estimate, not proof of fraud**. If the model is missing the API answers `503` — it never invents a score. Risk levels: Low < 0.3, Medium 0.3–0.7, High ≥ 0.7; the payment model flags at ≥ 0.3 (PCA demo: 0.5).

## Tests
```powershell
python -m pytest
```
Uses small generated fixtures and temporary databases/model files; it never touches your real dataset or model. Frontend: `cd ..\frontend; npm test`.

## Troubleshooting
| Problem | Fix |
|---|---|
| `dataset not found` | put `creditcard.csv` in `backend\data` |
| `Missing required columns` | wrong file; the PCA model needs `Time, V1..V28, Amount, Class` |
| `Model unavailable` (503) | run a training command above, restart `uvicorn` |
| Model "different feature schema" | retrain after changing `feature_schema.py` |
| Port 8000 still answers after stopping | an old worker survived: `netstat -ano \| findstr :8000`, then `taskkill /PID <pid> /F` |
| `InconsistentVersionWarning` | model was saved with another scikit-learn version; retrain |

## Security limitations
- `.joblib` files are pickles: **loading one can run code**. Only load models you trained yourself; never put downloaded model files in `models\`.
- No card numbers, CVVs, PINs or passwords are collected or stored. Not PCI DSS compliant; not for real payments.
- In-memory rate limiter (one process). See `../docs/SECURITY_REVIEW.md`.
