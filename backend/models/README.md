# models/

Trained model files are written here by `python train_model.py ...` and are git-ignored:
`fraud_model.joblib` (payment-form model) and `pca_demo_model.joblib` (Kaggle PCA demo model).

Warning: `.joblib` files are pickles. Loading a file from an untrusted source can run arbitrary code. Only use models trained by this project on your own computer.
