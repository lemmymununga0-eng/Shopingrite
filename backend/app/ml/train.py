"""THE training entry point for the verified-data models.

    python -m app.ml.train --dataset creditcard-openml        # real card transactions (needs: scripts/fetch_datasets.py get creditcard-openml --accept-licence)
    python -m app.ml.train --dataset phiusiil                 # ScamWatch URL model
    python -m app.ml.train --dataset paysim                   # mobile money (needs a Kaggle download first)
    python -m app.ml.train --dataset creditcard-openml --fast # quick development run (smaller models); never promote its result to production
    python -m app.ml.train --list-models                      # states of every registered model
    python -m app.ml.train --rollback creditcard_pca          # go back to the previous validated version

What a run does (see app/ml/framework.py): split 80/20 FIRST, compare candidates by cross-validation on the training part, choose the
threshold and calibration on out-of-fold training predictions, refit, evaluate once on the untouched test part, run the validation
gate, and save a new version. A version is promoted to "current" only if the gate passes, so the last good model is never overwritten.

The older `python -m app.ml.train_model --synthetic` still builds the labelled-synthetic development model behind the staff payment form.
"""
import argparse
import sys
from pathlib import Path

from . import datasets as ds
from . import registry
from .evaluation import save_confusion_matrix_png
from .framework import SEED, chronological_robustness, train_task

MODEL_FOR_DATASET = {"creditcard-openml": "creditcard_pca", "paysim": "paysim_mobile_money", "phiusiil": "url_phishing"}
SPLIT_FOR_DATASET = {"creditcard-openml": "stratified", "paysim": "stratified", "phiusiil": "group"}


def run(dataset: str, fast: bool = False, max_rows: int | None = None, promote: bool = True, folds: int = 4,
        root: Path = ds.EXTERNAL_DIR, artifact_root: Path = registry.ARTIFACT_ROOT, spec=None, log=print,
        split_method: str | None = None, meta_extra: dict | None = None) -> dict:
    """Train one dataset end to end. `spec` lets tests supply a fixture TaskSpec instead of a downloaded file."""
    if spec is None:
        if dataset not in ds.LOADERS:
            raise ValueError(f"Unknown dataset '{dataset}'. Choose one of: {', '.join(ds.LOADERS)}")
        kwargs = {"max_rows": max_rows} if dataset == "phiusiil" else {}
        spec = ds.LOADERS[dataset](root, fast=fast, **kwargs)
    log(f"dataset {spec.dataset.get('name')}  rows after cleaning {len(spec.y):,}  fraud/positive {int(spec.y.sum()):,}  cleaning: {spec.cleaning}")
    result = train_task(spec, split_method=split_method or SPLIT_FOR_DATASET.get(dataset, "stratified"), folds=folds, seed=SEED, log=log)
    meta = result.metadata
    meta.update(meta_extra or {})
    rb = meta.get("rules_baseline")
    if rb:                                                    # a supervised model must add value over the rules it would replace
        rb["model_pr_auc"] = meta["metrics"]["pr_auc"]
        if meta["metrics"]["pr_auc"] <= rb["pr_auc"]:
            meta["validation"]["passed"] = False
            meta["validation"]["failures"].append(f"does not beat the rule engine: model PR-AUC {meta['metrics']['pr_auc']:.3f} vs rules {rb['pr_auc']:.3f}")
        else:
            meta["validation"]["checks"].append({"check": "beats the rule engine on the same held-out customers", "passed": True,
                                                 "detail": f"{meta['metrics']['pr_auc']:.3f} vs {rb['pr_auc']:.3f}"})
    if spec.order is not None and not fast:
        try:
            meta["robustness"] = {"chronological": chronological_robustness(spec, meta["selected"], meta["threshold"])}
        except Exception as exc:                                  # informational only: never blocks the main result
            meta["robustness"] = {"error": f"{type(exc).__name__}: {exc}"}
    if fast:
        meta["validation"]["passed"] = False
        meta["validation"]["failures"].append("--fast development run: smaller models; deliberately not promotable")
    from .framework import render_report
    report = render_report(meta)
    png = save_confusion_matrix_png(meta["metrics"]["confusion_matrix"], Path(artifact_root) / f"_{meta['version']}.png", meta["version"])
    vdir = registry.save_version(spec.model_name, meta["version"], result.pipeline, meta, report, png, artifact_root)
    if png:
        Path(png).unlink(missing_ok=True)
    out = {"model": spec.model_name, "version": meta["version"], "dir": str(vdir), "passed": meta["validation"]["passed"], "promoted": False,
           "metrics": meta["metrics"], "failures": meta["validation"]["failures"]}
    if promote and meta["validation"]["passed"]:
        registry.promote(spec.model_name, meta["version"], artifact_root)
        out["promoted"] = True
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", choices=list(ds.LOADERS))
    ap.add_argument("--fast", action="store_true", help="development run with smaller models; never promoted")
    ap.add_argument("--max-rows", type=int, help="subsample (phiusiil only) for a quicker run")
    ap.add_argument("--no-promote", action="store_true", help="save the candidate but do not make it current")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--rollback", metavar="MODEL")
    args = ap.parse_args(argv)

    if args.list_models:
        for name in ("creditcard_pca", "paysim_mobile_money", "url_phishing"):
            r = registry.load_current(name)
            print(f"{name:22} {r.state:20} {r.metadata.get('version', '-'):40} {r.detail}")
        return 0
    if args.rollback:
        try:
            print("rolled back:", registry.rollback(args.rollback))
            return 0
        except registry.RegistryError as exc:
            print(f"ERROR: {exc}")
            return 1
    if not args.dataset:
        ap.error("choose --dataset (or --list-models / --rollback)")
    try:
        out = run(args.dataset, args.fast, args.max_rows, not args.no_promote, args.folds)
    except ds.DatasetUnavailable as exc:
        print(f"BLOCKED: {exc}")
        return 3
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    m = out["metrics"]
    print(f"\nversion {out['version']}\n  precision {m['precision']:.4f}  recall {m['recall']:.4f}  F1 {m['f1']:.4f}  PR-AUC {m['pr_auc']:.4f}  ROC-AUC {m['roc_auc']:.4f}"
          f"\n  confusion matrix {m['confusion_matrix']}\n  validation gate: {'PASSED' if out['passed'] else 'FAILED'}"
          f"\n  promoted to current: {out['promoted']}\n  saved in {out['dir']}")
    for f in out["failures"]:
        print("  FAILED CHECK:", f)
    return 0 if out["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
