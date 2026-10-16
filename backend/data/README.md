# data/

Put datasets here. **CSV files and databases in this folder are git-ignored** (large / possibly licensed / private).

- `creditcard.csv` — Kaggle "Credit Card Fraud Detection" (https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud). Download it manually
  (free Kaggle account, accept the dataset terms), unzip, and copy `creditcard.csv` here. Expected columns: `Time, V1..V28, Amount, Class`.
- Your own payment data: any CSV with the columns in `app/ml/feature_schema.py` plus `is_fraud` (0/1).
- `fraudguard.db` — local SQLite database created by the API (do not edit by hand).

Then run `python inspect_dataset.py` from the backend folder.
