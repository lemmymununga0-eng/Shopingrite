"""Train the grocery-store risk model from VERIFIED analyst outcomes in the store database.

    python -m app.ml.train_store --status      # how many verified outcomes exist and what is still missing
    python -m app.ml.train_store               # train + validate + (if the gate passes) promote store_grocery
    python -m app.ml.train_store --no-promote  # save the candidate without making it current
    python -m app.ml.train_store --export labelled.csv   # write the labelled dataset (no names/contacts) for offline review

Exit codes: 0 trained and promoted/saved, 2 trained but failed validation, 3 BLOCKED (not enough verified labels).
No labels are generated, inferred or balanced here. A model trained on fewer than 1000 verified fraud cases is marked EXPERIMENTAL:
the application records its predictions but never raises alerts from it.
"""
import argparse
import sys
from pathlib import Path

from ..config import Settings
from ..db.session import Database
from . import registry
from . import store_dataset as sd
from . import store_schema as schema
from .train import run


def train_from_session(session, promote: bool = True, fast: bool = False, artifact_root: Path = registry.ARTIFACT_ROOT,
                       req: sd.Requirements | None = None, is_fixture: bool = False, folds: int = 4, log=print) -> dict:
    df, counts = sd.labelled_rows(session)
    spec = sd.store_task(df, fast=fast, is_fixture=is_fixture, req=req)          # raises InsufficientLabels
    fraud = int((df["label"] == 1).sum())
    extra = {"schema_version": schema.SCHEMA_VERSION, "experimental": fraud < sd.VALIDATED_AT_FRAUD, "label_counts": counts,
             "rules_baseline": sd.rules_baseline(df),
             "label_policy": "verified outcomes only: confirmed_fraud=1; legitimate/false_positive=0; unverified and undetermined excluded"}
    return run("store-grocery", fast=fast, promote=promote, folds=folds, artifact_root=artifact_root, spec=spec, log=log,
               split_method="group", meta_extra=extra)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--no-promote", action="store_true")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--export", metavar="CSV")
    args = ap.parse_args(argv)
    db = Database(Settings().app_database_url)
    db.create_all()                                   # same schema step the API runs at start-up (adds missing tables only)
    try:
        with db.session() as session:
            if args.status or args.export:
                r = sd.readiness(session)
                print(r["message"])
                print(f"  verified fraud {r['verified_fraud']}/{r['required']['verified_fraud']}, verified legitimate "
                      f"{r['verified_legitimate']}/{r['required']['verified_legitimate']}, customers {r['distinct_customers']}/{r['required']['distinct_customers']}")
                print("  excluded:", {k: v for k, v in r["counts"].items() if k.startswith("excluded")})
                if args.export:
                    df, _ = sd.labelled_rows(session)
                    df.drop(columns=["user_id"]).to_csv(args.export, index=False)          # customer ids are not exported
                    print(f"  wrote {len(df)} rows to {args.export} (no customer identifiers)")
                return 0
            try:
                out = train_from_session(session, promote=not args.no_promote, fast=args.fast)
            except sd.InsufficientLabels as exc:
                print(f"BLOCKED: {exc}\nRule-based scoring (store_risk_v1) stays in use. See docs/LABEL_COLLECTION.md.")
                return 3
    finally:
        db.dispose()
    m = out["metrics"]
    print(f"\nversion {out['version']} (EXPERIMENTAL unless 1000+ verified fraud cases)\n  precision {m['precision']:.4f}  recall {m['recall']:.4f}  "
          f"F1 {m['f1']:.4f}  PR-AUC {m['pr_auc']:.4f}\n  confusion matrix {m['confusion_matrix']}\n  validation gate: {'PASSED' if out['passed'] else 'FAILED'}"
          f"\n  promoted: {out['promoted']}")
    for f in out["failures"]:
        print("  FAILED CHECK:", f)
    return 0 if out["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
