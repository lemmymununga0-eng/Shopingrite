"""Shared evaluation helpers used by both models (payment-form model and PCA demo model)."""
from pathlib import Path

import numpy as np
from sklearn.metrics import (accuracy_score, average_precision_score, classification_report, confusion_matrix,
                             f1_score, precision_score, recall_score, roc_auc_score)


def evaluate(y_true, proba, threshold: float) -> dict:
    """Metrics on HELD-OUT data. Accuracy is included but is misleading when fraud is rare."""
    y_true = np.asarray(y_true)
    pred = (np.asarray(proba) >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    out = {
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(y_true, pred)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "test_rows": int(len(y_true)),
        "support_legitimate": int((y_true == 0).sum()),
        "support_fraud": int((y_true == 1).sum()),
        "classification_report": classification_report(y_true, pred, labels=[0, 1],
                                                       target_names=["legitimate", "fraud"],
                                                       output_dict=True, zero_division=0),
    }
    # ROC-AUC and PR-AUC are only defined when both classes appear in the test set.
    if len(set(y_true.tolist())) == 2:
        out["roc_auc"] = float(roc_auc_score(y_true, proba))
        out["pr_auc"] = float(average_precision_score(y_true, proba))
    else:
        out["roc_auc"] = out["pr_auc"] = None
        out["warning"] = "Test set has only one class; ROC-AUC and PR-AUC are not defined."
    if out["support_fraud"] < 30:
        out["warning"] = (out.get("warning", "") + " Fewer than 30 fraud rows in the test set: "
                          "recall/precision are very unreliable.").strip()
    return out


def save_confusion_matrix_png(cm: dict, path: Path, title: str):
    """Write the confusion matrix as an image. Returns the path, or None if matplotlib is unavailable."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    grid = np.array([[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]])
    fig, ax = plt.subplots(figsize=(4.2, 3.8))
    ax.imshow(grid, cmap="Greens")
    ax.set_xticks([0, 1], ["Pred legit", "Pred fraud"])
    ax.set_yticks([0, 1], ["Actual legit", "Actual fraud"])
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{grid[i, j]:,}", ha="center", va="center", color="black", fontsize=12)
    ax.set_title(title, fontsize=10)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
