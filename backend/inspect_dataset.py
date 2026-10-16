"""Inspect a CSV before training:  python inspect_dataset.py [path] [--schema auto|pca|payment] [--target NAME]

With no path it looks for data/creditcard.csv. Writes reports/dataset_report.txt and .json.
"""
import argparse
import sys
from pathlib import Path

from app.ml import dataset_report as dr

HERE = Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", type=Path, default=HERE / "data" / "creditcard.csv")
    ap.add_argument("--schema", choices=["auto", "pca", "payment"], default="auto")
    ap.add_argument("--target", default=None, help="label column name if it is not the default")
    args = ap.parse_args(argv)
    try:
        report = dr.inspect(args.path, args.schema, args.target)
    except dr.DatasetFileError as exc:
        print(f"ERROR: {exc}")
        if not args.path.exists():
            print("Place creditcard.csv in backend/data (see data/README.md) or pass the path to your CSV.")
        return 1
    print(dr.render_text(report))
    dr.write_reports(report, HERE / "reports")
    print(f"\nReport saved to {HERE / 'reports' / 'dataset_report.txt'} (and .json)")
    return 0 if report["training_ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
