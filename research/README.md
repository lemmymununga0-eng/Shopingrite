# Research package for the paper

Code, saved results and figures behind the manuscript *Auditable fraud-risk assessment for a Zambian online grocery store: leakage-controlled
benchmarks and a protocol for collecting verified labels*. Every number that reports our own results is read from `results/*.json` by
`paper/build.py`; nothing is typed by hand. Numbers quoted from other papers are typed in and carry a citation.

## Layout

| Path | What it holds |
|---|---|
| `card_experiments.py` | Card-fraud benchmark, protocol ablation, repeated splits, learning curve, permutation importance, scoring latency |
| `phishing_experiments.py` | Phishing-URL benchmark, feature-group ablation, controlled subset, one-cue-at-a-time perturbation, host-name replacement model, spot checks, score spread, importance |
| `store_experiments.py` | Rule-engine scenarios, checkout latency, engineering facts (endpoints, tables, tests, CI state) |
| `diagrams.py`, `make_figures.py` | Figures 1 to 13 (matplotlib) |
| `results/` | Saved results (JSON). `results/_scratch/` holds large arrays and is git-ignored |
| `figures/` | Figures used in the paper (PNG, 300 dpi) |
| `paper/` | Manuscript builder (`build.py`), renderer (`render_docx.js`), references (`refs.py`), author details (`author.json`), cover letter builder, `SUBMISSION_CHECKLIST.md` |

## Reproduce

```bash
pip install -r backend/requirements-dev.txt
python backend/scripts/fetch_datasets.py get creditcard-openml --accept-licence
python backend/scripts/fetch_datasets.py get phiusiil --accept-licence

cd backend                                     # the latency and spot-check steps score the models in the registry
python -m app.ml.train --dataset creditcard-openml
python -m app.ml.train --dataset phiusiil
cd ..

python research/card_experiments.py all        # about 50 minutes on a 12-thread computer
python research/phishing_experiments.py all    # about 30 minutes; run `benchmark` before the other steps
python research/store_experiments.py all
python research/diagrams.py && python research/make_figures.py

cd research/paper && npm install docx@9 && python build.py   # writes manuscript.docx
python build_cover.py                                         # writes cover_letter.docx
```

`paper/build.py` also reads `results/test_runs.json` (the pass counts of the last full test run, copied by hand from the pytest, vitest and
Playwright summaries) and imports the reviewed list of public API operations from `backend/tests/test_route_security.py`.

All seeds are fixed (42 for the main split; 11, 22, 33, 44, 55 for the repeated splits). Datasets are not stored in Git; each download is
checked against the SHA-256 recorded in its manifest. Results will differ slightly with other library versions; the saved JSON records the versions used.

## Notes on what the results do and do not show

* The card and phishing results come from public data and say nothing about fraud in a grocery store.
* The store scenarios describe the rules' behaviour on scripted checkouts. They are not an estimate of detection accuracy.
* The phishing benchmark is dominated by a collection artefact: every legitimate address is `https://www.<domain>` with no path. The original
  31-feature model learned that format (see the ablation, perturbation and controlled-subset results) and was replaced by a host-name model
  that passes the robustness gate in `backend/app/ml/datasets.py`. That model is weak and stays experimental.
