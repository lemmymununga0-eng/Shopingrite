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

## Task B: `url_phishing` (URL text only): a negative result

**Short version: the first model I trained scored PR-AUC 0.9986 and was useless for real links. It was replaced.**

The original model used 31 lexical features of the whole address. On the PhiUSIIL test partition (grouped by domain) it reached precision 0.9988, recall 0.9948 and PR-AUC 0.9986.
Those numbers are an artefact of how the dataset was built. In the file, **every legitimate address is `https://www.<domain>` with no path and no trailing slash**
(100% HTTPS, 100% "www.", 100% empty path), while phishing addresses are 49% HTTPS, 42% "www.", 40% empty path, 33% a lone "/" and 27% deeper paths. Only 0.6% of phishing addresses (627 of 100,520) match the legitimate template exactly.
`research/phishing_experiments.py` shows the consequences:

| Check (held-out addresses, original model) | Result |
|---|---|
| Two features (`is_https`, URL length) | PR-AUC 0.952 |
| Three features (`is_https`, `has_www`, `path_depth`) | PR-AUC 0.996 |
| Remove "www." from legitimate test addresses | 0.1% flagged becomes 100% flagged |
| Use http, add a trailing slash, or add a path (each alone) | 100% flagged |
| Rewrite phishing addresses as `https://www.<host>` | detection falls from 99.5% to 29.6% |
| Only addresses that already match the legitimate template | PR-AUC 0.28 (144 phishing test rows) |

Spot checks agreed: `https://google.com` and a GitHub link were flagged; `https://www.sparkasse-auth.com` was not.

**What changed in the product**
* `url_phishing` now uses only the canonical host name (10 features; scheme, "www.", port, path, query and trailing slash are ignored) and a threshold chosen for at most 1% false alarms.
* A new validation gate (`datasets.url_invariance_checks`, run by `app.ml.train`) refuses any URL model whose verdict on legitimate addresses changes when we remove "www.", switch to http, add a slash or a path, or whose detection of phishing collapses when the address is rewritten in the legitimate format. The old model fails all five checks.
* Every URL model is saved with `experimental: true`, and the ScamWatch provider `ml_url` skips experimental models. **No URL-model verdict is ever shown to a user.**

**The replacement is weak, honestly measured.** Held-out PR-AUC 0.863 (gradient boosting), precision 0.979, recall 0.523 at a 0.8% false-alarm rate on the benchmark's legitimate addresses
(logistic regression: 0.823, 0.976, 0.433). Its legitimate examples are popular sites with short names, so real small sites with long hyphenated names will be flagged (it scored a plausible
small-business domain 0.93), and it misses phishing addresses that use ordinary-looking hosts. Treat it as a research prototype.

Dataset-level lesson: the phishing dataset cannot support a deployable URL-text model. A useful one needs legitimate addresses sampled like real traffic (paths, plain http, no "www.", small sites).

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
