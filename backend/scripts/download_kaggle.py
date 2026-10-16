r"""Optional: download creditcard.csv with YOUR Kaggle account (python scripts/download_kaggle.py).

Needs: `pip install kaggle` and your own API token saved by Kaggle at %USERPROFILE%\.kaggle\kaggle.json
(Kaggle > Settings > API > Create New Token). This script never asks for, stores or prints credentials,
and you must have accepted the dataset's terms on the Kaggle website. Manual download also works:
see backend/data/README.md.
"""
import sys
from pathlib import Path

DATASET = "mlg-ulb/creditcardfraud"
DEST = Path(__file__).resolve().parents[1] / "data"


def main() -> int:
    target = DEST / "creditcard.csv"
    if target.exists():
        print(f"Already present: {target} (not downloading again).")
        return 0
    token = Path.home() / ".kaggle" / "kaggle.json"
    import os
    if not token.exists() and not (os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY")):
        print("BLOCKED: no Kaggle credentials found.\n"
              "Option 1: create an API token on kaggle.com (Settings > API) and save kaggle.json in "
              f"{token.parent}.\nOption 2: download the file manually and put it at {target}.")
        return 1
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError:
        print("The 'kaggle' package is not installed. Run: pip install kaggle")
        return 1
    try:
        api = KaggleApi()
        api.authenticate()
        DEST.mkdir(exist_ok=True)
        api.dataset_download_files(DATASET, path=str(DEST), unzip=True)
    except Exception as exc:                       # authentication, terms not accepted, network, rate limit
        print(f"Download failed ({type(exc).__name__}). Accept the dataset terms on Kaggle, check your token, "
              "or download manually.")
        return 1
    if not target.exists():
        print("Download finished but creditcard.csv was not found in the archive.")
        return 1
    print(f"Saved {target}. Next: python inspect_dataset.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
