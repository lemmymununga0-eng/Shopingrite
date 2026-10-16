from pathlib import Path
import sys
import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "creditcard.csv"
MODEL_PATH = HERE / "fraud_model.joblib"

FEATURES = ["Time"] + [f"V{i}" for i in range(1, 29)] + ["Amount"]
REQUIRED = FEATURES + ["Class"]

def main():
    if not CSV_PATH.exists():
        print(f"ERROR: Dataset not found: {CSV_PATH}")
        print("Copy your compatible creditcard.csv into the backend folder and run again.")
        sys.exit(1)

    print("Loading dataset...")
    df = pd.read_csv(CSV_PATH)
    missing = [col for col in REQUIRED if col not in df.columns]
    if missing:
        print("ERROR: This dataset does not match the expected Kaggle credit-card schema.")
        print("Missing columns:", ", ".join(missing))
        print("Expected: Time, V1..V28, Amount, Class")
        sys.exit(1)

    df = df[REQUIRED].dropna()
    if df["Class"].nunique() < 2:
        print("ERROR: Class must contain both 0 (legitimate) and 1 (fraud).")
        sys.exit(1)

    X = df[FEATURES].astype(float)
    y = df["Class"].astype(int)
    print(f"Rows: {len(df):,}; fraud rows: {(y == 1).sum():,}; legitimate rows: {(y == 0).sum():,}")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=150,
        class_weight="balanced_subsample",
        random_state=42,
        n_jobs=-1,
        min_samples_leaf=2,
    )
    print("Training Random Forest...")
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    probs = model.predict_proba(X_test)[:, list(model.classes_).index(1)]

    print("\nClassification report:")
    print(classification_report(y_test, pred, digits=4, zero_division=0))
    print("Confusion matrix:")
    print(confusion_matrix(y_test, pred))
    try:
        print(f"ROC AUC: {roc_auc_score(y_test, probs):.4f}")
    except ValueError:
        print("ROC AUC unavailable for this split.")

    bundle = {
        "model": model,
        "features": FEATURES,
        "threshold": 0.5,
        "dataset_rows": int(len(df)),
        "fraud_rows": int((y == 1).sum()),
        "model_type": "RandomForestClassifier",
    }
    joblib.dump(bundle, MODEL_PATH)
    print(f"\nSaved trained model to: {MODEL_PATH}")
    print("Training complete. Keep in mind that a high test score alone does not prove production readiness.")

if __name__ == "__main__":
    main()
