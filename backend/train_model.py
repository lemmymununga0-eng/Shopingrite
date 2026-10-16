r"""Train a model from the backend folder.

  python train_model.py --synthetic                 payment-form model on synthetic data (development)
  python train_model.py --csv data\my_payments.csv  payment-form model on your own labelled CSV
  python train_model.py --schema pca                separate Kaggle V1-V28 demo model (data\creditcard.csv)

See app/ml/train_model.py for the implementation.
"""
import sys

from app.ml.train_model import main

if __name__ == "__main__":
    sys.exit(main())
