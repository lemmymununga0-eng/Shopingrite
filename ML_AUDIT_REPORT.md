# ML audit report

Scope: dataset download, model training, serving and store integration, audited against the repository as it stood at the start of this work.
Statuses used throughout: **PASS**, **FAIL**, **BLOCKED** (cannot be done without something only the owner can provide), **NOT TESTED**.

## Starting state

| Area | Finding |
|---|---|
| Existing models | `app/ml/train_model.py` trained on **synthetic** payments (`synthetic.py`); `pca_demo.py` expected a Kaggle PCA file that was never downloaded. No real-data model existed. |
| Store scoring | `store_risk_v1` is a rule engine, not ML. Correctly labelled as such in code and UI. |
| Downloader (`backend/scripts/fetch_datasets.py`) | Written by a previous agent. Independently re-verified (below). |
| Registry / metadata | Single `.joblib` file with a small metadata dict; no versions, no checksum, no rollback, no validation gate. |

## Independent verification of the previous agent's downloader claims

| Claim | Result |
|---|---|
| "Tests exist at `backend/scripts/test_fetch_datasets.py`" | **FAIL**: that path does not exist. Tests are at `backend/tests/test_fetch_datasets.py`. |
| "Downloader fetches the datasets" | **PARTLY**: PhiUSIIL worked; Kaggle sources cannot work without credentials; no schema check, no retry, no verify command, no manifest checksum validation. Repaired (below). |
| "Credit-card dataset downloadable" | **FAIL as claimed** (Kaggle needs a token). Replaced by the OpenML mirror of the same ULB data, found by testing, with a documented licence ("Public"). |
| "PaySim available from Hugging Face" | **Not accepted**: mirrors have unverified/conflicting licences. Not used. |

Repairs made: retry with backoff, schema check for every dataset, `status` and `verify` commands, `--accept-licence` required for `get`,
manifest with source/time/licence/sha256/schema result, data kept under a git-ignored directory. 24 offline tests with the network mocked.

## Dataset suitability decision

| Dataset | Verdict |
|---|---|
| ULB credit card (OpenML) | Real labelled card fraud; anonymised features, so **only** useful to prove the training/serving pipeline on real data. Cannot score store orders. |
| PhiUSIIL | Suitable for the ScamWatch URL task; has strong collection artefacts (see `docs/ML_EVALUATION.md`). |
| PaySim | Best conceptual match for mobile money but simulated and **BLOCKED** (Kaggle token). |
| IEEE-CIS, Kaggle original | BLOCKED (credentials/rules). |
| OFF, OSM, Instacart | Not fraud data; never used for fraud training. |

Conclusion: **no available dataset matches what a grocery store can observe.** The honest design is therefore: Task A and B models are real and
validated on their own data; Task C (store orders) records `unsupported_input_schema` instead of fabricating inputs; the rule engine stays authoritative.

## Gaps closed in this work

Versioned, checksum-verified artifacts with promote/rollback; leakage-safe training framework with a validation gate; one documented entry point;
a model service loaded once at start-up with honest states; `/fraud/model-status` and `/fraud/predict`; idempotent `ml_predictions` and append-only
`order_outcomes` tables; staff UI for model status and outcomes; opt-in ScamWatch `ml_url` provider.

## Remaining gaps

- PaySim / Kaggle data: BLOCKED until a Kaggle token is provided (`kaggle.json`); exact steps in `docs/DATASETS.md`.
- Legacy `/pca-demo` endpoints still use the old single-file loader and report "not trained" unless that file is created; `/fraud/*` is the supported path.
- Model artifacts are not in Git by design; a fresh deployment shows "Not trained" until `python -m app.ml.train ...` is run there (or artifacts are copied).
- No real store fraud labels exist yet, so no model can be evaluated on store data.
