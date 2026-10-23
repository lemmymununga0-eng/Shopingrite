# ML evaluation

All numbers below are copied from the saved `metadata.json` of the promoted versions (`backend/artifacts/fraud/<model>/versions/<version>/`,
with a `report.md` and confusion-matrix PNG beside it). They are **held-out test results from the dataset**, not live performance.

## Method (both models)

1. Clean (exact duplicates dropped, non-finite rows dropped and counted), then split **before** any fitting: 80/20, seed 42.
2. All fitting (scaler, encoders, imputers, models, calibrator, threshold) uses the training partition only. The test partition is
   scored once, after every choice has been made.
3. Candidates (Dummy prior baseline, logistic regression, random forest or gradient boosting) are compared by **cross-validated PR-AUC
   on the training partition**. PR-AUC is used because accuracy is meaningless at 0.17% fraud.
4. Probabilities are calibrated with isotonic regression fitted on **out-of-fold** training predictions; the alert threshold maximises
   F2 (recall weighted twice as much as precision) on those same out-of-fold predictions. The test set is not used for either.
5. A version is promoted only if the validation gate passes (both classes in test, ≥30 test fraud rows, PR-AUC above a per-task minimum and well
   above the dummy baseline, finite metrics, no train/test overlap, and the saved file reloads in a **fresh process** and reproduces predictions).
   The checksum of the model file is verified before every load. `--fast` runs can never be promoted.

## Task A: `creditcard_pca` (real transactions, anonymised features)

Version `creditcard-pca-20261023-091041`. Split: stratified random 80/20 (train 226,980 rows / 378 fraud; test 56,746 / 95 fraud).
Selected: random forest (`min_samples_leaf=2`), cross-validated PR-AUC 0.834 (logistic regression 0.736, gradient boosting 0.745, dummy 0.0017).

| Held-out test metric | Value |
|---|---|
| Threshold (chosen on training OOF) | 0.214 |
| Precision / Recall / F1 | 0.926 / 0.789 / 0.852 |
| PR-AUC / ROC-AUC | 0.800 / 0.929 (dummy PR-AUC 0.0017) |
| Accuracy | 0.9995 (a model that never flags anything scores 0.9983, so ignore this number) |
| Confusion matrix | TN 56,645 · FP 6 · FN 20 · TP 75 |
| False-positive rate / False-negative rate | 0.011% / 21.1% |
| Brier / expected calibration error | 0.00045 / 0.00024 |

Chronological robustness check (informational): oldest 80% train, newest 20% test gave PR-AUC 0.816, precision 0.875, recall 0.757 on 74 fraud rows.

**Read this carefully**
- 95 test fraud rows means each missed or caught case moves recall by about one point. The precision/recall figures have wide error bars.
- The data covers two days in 2013 for European card holders. No card or merchant identifier exists, so one card may appear on both sides of
  the random split, which can make results optimistic. The chronological check is the less optimistic number.
- The model needs V1–V28. It cannot score a grocery order and **is not used to decide anything about store orders**.

## Task B: `url_phishing` (URL text only)

Version `url-phishing-20261023-091413`. Split: **grouped by domain**, 80/20 (train 188,086 / 80,402 phishing; test 47,284 / 20,118 phishing).
Selected: logistic regression (C=1), cross-validated PR-AUC 0.9991 (gradient boosting 0.9990, dummy 0.427).

| Held-out test metric | Value |
|---|---|
| Threshold | 0.267 |
| Precision / Recall / F1 | 0.9988 / 0.9948 / 0.9968 |
| PR-AUC / ROC-AUC | 0.9986 / 0.9985 |
| Confusion matrix | TN 27,142 · FP 24 · FN 105 · TP 20,013 |
| Brier / expected calibration error | 0.0024 / 0.00044 |

**Do not trust these numbers outside this dataset.** A simple linear model reaching 99.9% from URL text is a sign the dataset is easy in
a specific way. Measured on the file: **100% of legitimate URLs are bare site roots served over HTTPS** (mean length 26 characters), while 49% of
phishing URLs use HTTPS, 28% carry a path, and the mean length is 46. Any link with a path or plain HTTP is therefore close to "phishing" by construction. Real links, short-lived phishing pages, and compromised legitimate sites will look different. For that reason ScamWatch uses
this model only to raise suspicion, never to clear a link, and only when the operator opts in with `SCAMWATCH_PROVIDERS=heuristic,ml_url`.

## Not evaluated

- **PaySim mobile-money model**: BLOCKED (no dataset, no model). The status panel shows "Not trained". Nothing is simulated in its place.
- **Live store traffic**: the store has no verified fraud labels yet. Recording `order_outcomes` is the path to collecting them; evaluating on them is future work.
- No external or temporal test set beyond the chronological check above.

## Reproduce

```bash
cd backend
python scripts/fetch_datasets.py status
python -m app.ml.train --dataset creditcard-openml     # ~5 minutes on a laptop; promotes only if the gate passes
python -m app.ml.train --dataset phiusiil
python -m app.ml.train --list-models
python -m app.ml.train --rollback creditcard_pca       # return to the previous promoted version
```

Retraining policy: retrain manually when new data is downloaded or verified outcomes have accumulated (hundreds of verified fraud cases at minimum).
The new version is compared on the same gate; the previous good version stays live until a new one passes and is promoted. There is no automatic
retraining on unverified analyst feedback.
