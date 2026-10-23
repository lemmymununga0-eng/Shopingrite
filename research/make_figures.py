"""Figures 3-12 of the paper, drawn only from the saved results (research/results/*.json and _scratch/*.npz).
Figures 1-2 (architecture, workflow) come from diagrams.py.   python research/make_figures.py [fig ...]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from _common import FIGS, RESULTS, SCRATCH, load  # noqa: E402
from sklearn.metrics import precision_recall_curve, roc_curve  # noqa: E402

BLUE, ORANGE, GREEN, RED, PURPLE, GREY, SKY, YELLOW = "#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#6B6B6B", "#56B4E9", "#F0E442"
COL = {"logistic_regression": BLUE, "random_forest": GREEN, "hist_gradient_boosting": ORANGE}
LAB = {"logistic_regression": "Logistic regression", "random_forest": "Random forest", "hist_gradient_boosting": "Gradient boosting"}
plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"], "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
                     "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7, "axes.spines.top": False, "axes.spines.right": False})


def exists(*names):
    return all((RESULTS / f"{n}.json").exists() for n in names)


def save(fig, name):
    fig.savefig(FIGS / f"{name}.png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", name)


def panel_label(ax, s):
    ax.text(-0.02, 1.06, s, transform=ax.transAxes, fontsize=9, fontweight="bold", va="bottom", ha="right")


# ------------------------------------------------------------------------------------------------------------- Fig 3
def fig03():
    if not exists("card_benchmark", "phishing_benchmark", "phishing_controlled"):
        return print("skip fig03 (needs phishing results)")
    cb, pb, pc = load("card_benchmark"), load("phishing_benchmark"), load("phishing_controlled")
    fig, axs = plt.subplots(1, 3, figsize=(6.6, 2.5), gridspec_kw={"width_ratios": [1.0, 1.0, 1.25]})
    sp = cb["models"]["random_forest"]["split"]
    legit = sp["train_class_counts"]["legitimate"] + sp["test_class_counts"]["legitimate"]
    fraud = sp["train_class_counts"]["fraud"] + sp["test_class_counts"]["fraud"]
    ax = axs[0]
    ax.bar(["Legitimate", "Fraud"], [legit, fraud], color=[SKY, RED])
    ax.set_yscale("log")
    ax.set_ylabel("Transactions (log scale)")
    ax.set_title("Card data (ULB)")
    for i, v in enumerate([legit, fraud]):
        ax.text(i, v * 1.25, f"{v:,}", ha="center", fontsize=7)
    ax.set_ylim(100, 2e6)
    panel_label(ax, "(a)")
    sp2 = pb["models"]["logistic_regression"]["split"]
    pl = sp2["train_class_counts"]["legitimate"] + sp2["test_class_counts"]["legitimate"]
    pp = sp2["train_class_counts"]["fraud"] + sp2["test_class_counts"]["fraud"]
    ax = axs[1]
    ax.bar(["Legitimate", "Phishing"], [pl, pp], color=[SKY, RED])
    ax.set_ylabel("URLs")
    ax.set_title("Web addresses (PhiUSIIL)")
    for i, v in enumerate([pl, pp]):
        ax.text(i, v + 2500, f"{v:,}", ha="center", fontsize=7)
    ax.set_ylim(0, 160000)
    panel_label(ax, "(b)")
    ax = axs[2]
    sh = pc["share_of_class"]
    keys = [("HTTPS", "uses\nHTTPS"), ("www prefix", "starts\nwith www"), ("no trailing slash or path", "no path or\ntrailing slash"), ("exact legitimate template (https, www, no path)", "all three")]
    x = np.arange(len(keys))
    w = 0.36
    vals_l = [sh[k]["legitimate"] for k, _ in keys]
    vals_p = [sh[k]["phishing"] for k, _ in keys]
    ax.bar(x - w / 2, [v * 100 for v in vals_l], w, color=SKY, label="Legitimate")
    ax.bar(x + w / 2, [v * 100 for v in vals_p], w, color=RED, label="Phishing")
    ax.set_xticks(x)
    ax.set_xticklabels([lab for _, lab in keys], fontsize=6.3)
    ax.set_ylabel("Share of the class (%)")
    ax.set_title("Collection artefact in web addresses")
    ax.legend(frameon=False, loc="upper right", bbox_to_anchor=(1.0, 0.72), fontsize=6.5)
    ax.set_ylim(0, 118)
    for i, (a_, b_) in enumerate(zip(vals_l, vals_p)):
        ax.text(i - w / 2, a_ * 100 + 2, f"{a_ * 100:.0f}", ha="center", fontsize=6.5)
        ax.text(i + w / 2, b_ * 100 + 2, f"{b_ * 100:.1f}".rstrip("0").rstrip("."), ha="center", fontsize=6.5)
    panel_label(ax, "(c)")
    fig.tight_layout()
    save(fig, "fig03_datasets")


# ------------------------------------------------------------------------------------------------------------- Fig 4
def pct(x):
    """Percentage with enough digits that a tiny share is not shown as 0.0% and a near-total is not shown as 100.0%."""
    v = 100 * x
    return f"{v:.2f}%" if (0 < v < 0.1 or 99.9 < v < 100) else f"{v:.1f}%"


def cm_panel(ax, cm, title, pos_name):
    m = np.array([[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]])
    row = m / m.sum(axis=1, keepdims=True)
    ax.imshow(row, cmap="Blues", vmin=0, vmax=1)
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{m[i, j]:,}\n({pct(row[i, j])})", ha="center", va="center", fontsize=7.5, color="white" if row[i, j] > 0.55 else "black")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Legitimate", pos_name])
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Legitimate", pos_name], rotation=90, va="center")
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title(title)
    for s in ax.spines.values():
        s.set_visible(False)


def fig04():
    if not exists("card_benchmark", "phishing_benchmark"):
        return print("skip fig04")
    cb, pb = load("card_benchmark"), load("phishing_benchmark")
    fig, axs = plt.subplots(1, 2, figsize=(6.2, 2.9))
    cm_panel(axs[0], cb["models"]["random_forest"]["test"]["confusion_matrix"], "(a) Card fraud: random forest", "Fraud")
    cm_panel(axs[1], pb["models"]["logistic_regression"]["test"]["confusion_matrix"], "(b) Web addresses: original logistic regression", "Phishing")
    fig.tight_layout()
    save(fig, "fig04_confusion")


# ------------------------------------------------------------------------------------------------------------- Fig 5, 6
def curves(kind):
    if not (SCRATCH / "card_scores.npz").exists() or not (SCRATCH / "phish_scores.npz").exists():
        return print(f"skip {kind} curves")
    fams = ["logistic_regression", "random_forest", "hist_gradient_boosting"]
    fig, axs = plt.subplots(1, 2, figsize=(6.4, 3.0))
    for ax, (tag, fname, title) in zip(axs, [("card", "card_scores", "(a) Card fraud"), ("phish", "phish_scores", "(b) Web addresses (original models)")]):
        z = np.load(SCRATCH / f"{fname}.npz")
        y = z["y"]
        bench = load("card_benchmark" if tag == "card" else "phishing_benchmark")
        for f in fams:
            p = z[f]
            if kind == "roc":
                fpr, tpr, _ = roc_curve(y, p)
                ax.plot(fpr, tpr, color=COL[f], lw=1.3, label=f"{LAB[f]} (AUC {bench['models'][f]['test']['roc_auc']:.3f})")
            else:
                pr, rc, _ = precision_recall_curve(y, p)
                ax.plot(rc, pr, color=COL[f], lw=1.3, label=f"{LAB[f]} (AP {bench['models'][f]['test']['pr_auc']:.3f})")
                t = bench["models"][f]["test"]
                ax.plot([t["recall"]], [t["precision"]], "o", color=COL[f], ms=4.5, mec="black", mew=0.5)
        if kind == "roc":
            ax.plot([0, 1], [0, 1], ls="--", color=GREY, lw=0.8)
            ax.set_xlabel("False-positive rate")
            ax.set_ylabel("True-positive rate")
            if tag == "card":
                ax.set_xlim(0, 0.2)
                ax.set_ylim(0.4, 1.005)
                ax.set_xlabel("False-positive rate (first 20% shown)")
            else:
                ax.set_xlim(0, 0.05)
                ax.set_ylim(0.9, 1.002)
                ax.set_xlabel("False-positive rate (first 5% shown)")
            ax.legend(frameon=False, loc="lower right")
        else:
            prev = float(np.mean(y))
            ax.axhline(prev, ls="--", color=GREY, lw=0.8, label=f"No-skill (prevalence {prev:.4f})")
            ax.set_xlabel("Recall")
            ax.set_ylabel("Precision")
            ax.set_ylim(0, 1.02)
            ax.set_xlim(0, 1.0)
            if tag == "phish":
                ax.set_ylim(0.9, 1.002)
                ax.set_xlim(0.9, 1.0)
            ax.legend(frameon=False, loc="lower left", fontsize=6.5)
        ax.set_title(title)
    if kind == "pr":
        fig.text(0.5, -0.02, "Dots mark each model's operating point (threshold chosen on training data).", ha="center", fontsize=6.8, color=GREY)
    fig.tight_layout()
    save(fig, "fig05_roc" if kind == "roc" else "fig06_pr")


# ------------------------------------------------------------------------------------------------------------- Fig 7
def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def fig07():
    if not (SCRATCH / "card_scores.npz").exists() or not (SCRATCH / "phish_scores.npz").exists():
        return print("skip fig07")
    fig, axs = plt.subplots(1, 2, figsize=(6.2, 3.0))
    edges = {"card": [0, 0.0005, 0.005, 0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0001], "phish": [0, 0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]}
    for ax, (tag, fname, fam, title) in zip(axs, [("card", "card_scores", "random_forest", "(a) Card fraud: random forest"),
                                                  ("phish", "phish_scores", "logistic_regression", "(b) Web addresses: original logistic regression")]):
        z = np.load(SCRATCH / f"{fname}.npz")
        y, p = z["y"], z[fam]
        xs, ys, lo, hi, ns = [], [], [], [], []
        for a, b in zip(edges[tag][:-1], edges[tag][1:]):
            m = (p >= a) & (p < b)
            n = int(m.sum())
            if n < 15:
                continue
            k = int(y[m].sum())
            xs.append(float(p[m].mean()))
            ys.append(k / n)
            l, h = wilson(k, n)
            lo.append(k / n - l)
            hi.append(h - k / n)
            ns.append(n)
        ax.plot([0, 1], [0, 1], ls="--", color=GREY, lw=0.8, label="Perfect calibration")
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt="o-", color=GREEN if tag == "card" else BLUE, ms=4, lw=1, capsize=2, label="Observed (95% Wilson interval)")
        ax.set_xlabel("Mean predicted probability")
        ax.set_ylabel("Observed frequency")
        ax.set_title(title)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.05)
        ax.legend(frameon=False, loc="upper left", fontsize=6.5)
    fig.tight_layout()
    save(fig, "fig07_reliability")


# ------------------------------------------------------------------------------------------------------------- Fig 8
def fig08():
    if not exists("card_importance", "phishing_importance"):
        return print("skip fig08")
    ci, pi = load("card_importance"), load("phishing_importance")
    fig, axs = plt.subplots(1, 2, figsize=(6.4, 3.0))
    for ax, rows, title, color in ((axs[0], ci["permutation"][:10], "(a) Card fraud: random forest", GREEN), (axs[1], pi["permutation"][:10], "(b) Web addresses: original logistic regression", BLUE)):
        names = [r["feature"] for r in rows][::-1]
        vals = [r["mean_drop_in_pr_auc"] for r in rows][::-1]
        sds = [r["sd"] for r in rows][::-1]
        ax.barh(names, vals, xerr=sds, color=color, ecolor="black", error_kw={"lw": 0.7, "capsize": 2})
        ax.set_xlabel("Drop in PR-AUC when the feature is shuffled")
        ax.set_title(title)
    fig.tight_layout()
    save(fig, "fig08_importance")


# ------------------------------------------------------------------------------------------------------------- Fig 9
def fig09():
    if not exists("card_learning_curve", "card_seeds"):
        return print("skip fig09")
    lc, sd = load("card_learning_curve"), load("card_seeds")
    fig, axs = plt.subplots(1, 2, figsize=(6.4, 2.9))
    ax = axs[0]
    x = np.array(lc["train_sizes"])
    for key, color, lab in (("train", BLUE, "Training"), ("validation", RED, "Cross-validation")):
        m, s = np.array(lc[f"{key}_pr_auc_mean"]), np.array(lc[f"{key}_pr_auc_sd"])
        ax.plot(x, m, "o-", color=color, ms=3.5, lw=1.2, label=lab)
        ax.fill_between(x, m - s, m + s, color=color, alpha=0.15)
    ax.set_xlabel("Training rows")
    ax.set_ylabel("PR-AUC")
    ax.set_title("(a) Learning curve (random forest)")
    ax.set_ylim(0.4, 1.02)
    ax.legend(frameon=False, loc="lower right")
    ax = axs[1]
    for i, f in enumerate(("logistic_regression", "random_forest")):
        runs = sd["models"][f]["runs"]
        vals = [r["pr_auc"] for r in runs]
        ax.scatter(np.full(len(vals), i) + np.linspace(-0.12, 0.12, len(vals)), vals, color=COL[f], s=16, zorder=3)
        m = np.mean(vals)
        ax.hlines(m, i - 0.22, i + 0.22, color="black", lw=1)
        ax.text(i + 0.26, m, f"mean {m:.3f}\nSD {np.std(vals, ddof=1):.3f}", fontsize=6.5, va="center")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Logistic\nregression", "Random\nforest"])
    ax.set_xlim(-0.5, 1.8)
    ax.set_ylabel("Held-out PR-AUC")
    ax.set_title("(b) Five random splits")
    fig.tight_layout()
    save(fig, "fig09_curves_seeds")


# ------------------------------------------------------------------------------------------------------------- Fig 10
def fig10():
    if not exists("card_protocol"):
        return print("skip fig10")
    rows = load("card_protocol")["rows"]
    labels = ["A. Correct protocol", "B. Oversample before\nsplitting", "C. Keep duplicate rows"]
    metrics = [("pr_auc", "PR-AUC", BLUE), ("precision", "Precision", GREEN), ("recall", "Recall", ORANGE), ("f1", "F1", PURPLE)]
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    x = np.arange(len(rows))
    w = 0.19
    for i, (k, lab, c) in enumerate(metrics):
        v = [r[k] for r in rows]
        ax.bar(x + (i - 1.5) * w, v, w, color=c, label=lab)
        for xi, vi in zip(x + (i - 1.5) * w, v):
            ax.text(xi, vi + 0.012, f"{vi:.2f}", ha="center", fontsize=6)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Held-out score")
    ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.12))
    fig.tight_layout()
    save(fig, "fig10_protocol")


# ------------------------------------------------------------------------------------------------------------- Fig 11
def fig11():
    if not exists("phishing_ablation", "phishing_perturbation", "phishing_host_model"):
        return print("skip fig11")
    ab, pt, hm = load("phishing_ablation"), load("phishing_perturbation"), load("phishing_host_model")
    fig, axs = plt.subplots(1, 2, figsize=(6.7, 3.5), gridspec_kw={"width_ratios": [1.05, 1.0]})
    ax = axs[0]
    rows = ab["rows"][::-1]
    names = [r["features"].replace(" (is_https, has_port, has_www)", "").replace("Three collection cues (is_https, has_www, path_depth)", "Three cues: https, www, path depth") for r in rows]
    ax.barh(names, [r["pr_auc"] for r in rows], color=[BLUE if "All" in r["features"] else (RED if "cues" in r["features"] else SKY) for r in rows])
    for i, r in enumerate(rows):
        ax.text(r["pr_auc"] + 0.005, i, f"{r['pr_auc']:.3f}", va="center", fontsize=6.5)
    ax.set_xlim(0, 1.1)
    ax.set_xlabel("PR-AUC (domain-grouped test set)")
    ax.set_title("(a) Feature sets")
    ax.tick_params(axis="y", labelsize=6.2)
    ax = axs[1]
    host = hm["models"]["hist_gradient_boosting"]["cosmetic_flagged_shares"]
    cats = [("legitimate", "as released", "Legitimate: as released"), ("legitimate", "remove the www prefix", "Legitimate: remove www"), ("legitimate", "use http instead of https", "Legitimate: http"),
            ("legitimate", "add a trailing slash", "Legitimate: add slash"), ("legitimate", "add a path", "Legitimate: add a path"),
            ("phishing", "as released", "Phishing: as released"), ("phishing", "rewrite as https://www.<host> (legitimate template)", "Phishing: rewritten as template")]
    y = np.arange(len(cats))[::-1]
    lex = [pt[side][k]["flagged_share"] for side, k, _ in cats]
    hst = []
    for side, k, _ in cats:
        key = "rewrite as https://www.<host>" if k.startswith("rewrite") else k
        hst.append(host[side][key])
    ax.barh(y + 0.19, [v * 100 for v in lex], 0.36, color=ORANGE, label="Original model (31 features)")
    ax.barh(y - 0.19, [v * 100 for v in hst], 0.36, color=GREEN, label="Host-name model (10 features)")
    for yy, v1, v2 in zip(y, lex, hst):
        ax.text(v1 * 100 + 1.5, yy + 0.19, f"{v1 * 100:.1f}".rstrip("0").rstrip("."), va="center", fontsize=6.2)
        ax.text(v2 * 100 + 1.5, yy - 0.19, f"{v2 * 100:.1f}".rstrip("0").rstrip("."), va="center", fontsize=6.2)
    ax.set_yticks(y)
    ax.set_yticklabels([c for _, _, c in cats], fontsize=6.2)
    ax.set_xlim(0, 118)
    ax.set_xlabel("Addresses flagged (%)")
    ax.set_title("(b) Cosmetic changes to held-out addresses")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, fontsize=6.3)
    fig.tight_layout()
    save(fig, "fig11_shortcut")


# ------------------------------------------------------------------------------------------------------------- Fig 12
def fig12():
    if not exists("store_scenarios"):
        return print("skip fig12")
    d = load("store_scenarios")
    rules = ["high_value", "bulk_quantity", "first_order_large", "spend_spike", "order_velocity", "failed_payments", "new_address", "night_order", "repeated_rejections"]
    colors = dict(zip(rules, [RED, ORANGE, YELLOW, PURPLE, BLUE, SKY, GREEN, GREY, "#8B4513"]))
    sc = d["scenarios"][::-1]
    fig, ax = plt.subplots(figsize=(6.4, 3.3))
    for i, s in enumerate(sc):
        left = 0
        for r in s["rules"]:
            ax.barh(i, r["points"], left=left, color=colors.get(r["rule"], GREY), edgecolor="white", lw=0.6)
            left += r["points"]
        ax.text(left + 1.2, i, f"{s['score']}  {s['decision']}" + ("  (case opened)" if s["case_opened"] else ""), va="center", fontsize=6.8,
                bbox=dict(fc="white", ec="none", pad=0.6), zorder=5)
    ax.axvline(30, color="black", ls="--", lw=0.8)
    ax.axvline(60, color="black", ls="--", lw=0.8)
    ax.text(30.5, len(sc) - 0.35, "review", fontsize=6.5)
    ax.text(60.5, len(sc) - 0.35, "high", fontsize=6.5)
    ax.set_yticks(range(len(sc)))
    ax.set_yticklabels([s["name"] for s in sc], fontsize=7)
    ax.set_xlim(0, 118)
    ax.set_xlabel("Rule-engine score (points)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors[r]) for r in rules if any(r == x["rule"] for s in sc for x in s["rules"])]
    names = [r.replace("_", " ") for r in rules if any(r == x["rule"] for s in sc for x in s["rules"])]
    ax.legend(handles, names, frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.17), fontsize=6.5)
    fig.tight_layout()
    save(fig, "fig12_scenarios")


# ------------------------------------------------------------------------------------------------------------- Fig 13
def fig13():
    if not exists("card_benchmark", "phishing_benchmark"):
        return print("skip fig13")
    fig, axs = plt.subplots(1, 2, figsize=(6.4, 2.6))
    for ax, (res, title, lo_lim) in zip(axs, ((load("card_benchmark"), "(a) Card fraud", 0.0), (load("phishing_benchmark"), "(b) Web addresses (original models)", 0.99))):
        fams = ["logistic_regression", "random_forest", "hist_gradient_boosting"]
        ys = np.arange(len(fams))[::-1]
        for y, f in zip(ys, fams):
            t = res["models"][f]["test"]["pr_auc"]
            c = res["bootstrap"]["ci95"][f]["pr_auc"]
            ax.errorbar([t], [y], xerr=[[t - c["lo"]], [c["hi"] - t]], fmt="o", color=COL[f], ms=5, capsize=3, lw=1.2)
            ax.text(c["hi"] + (0.01 if lo_lim == 0 else 0.0004), y, f"{t:.3f}", va="center", fontsize=6.8)
        ax.set_yticks(ys)
        ax.set_yticklabels([LAB[f] for f in fams])
        ax.axvline(res["dummy"]["pr_auc"], color=GREY, ls="--", lw=0.8)
        ax.set_xlabel("PR-AUC with 95% bootstrap interval")
        ax.set_title(title)
        if lo_lim:
            ax.set_xlim(lo_lim, 1.0005)
        else:
            ax.set_xlim(0.45, 0.95)
    fig.tight_layout()
    save(fig, "fig13_comparison")


ALL = {"fig03": fig03, "fig04": fig04, "fig05": lambda: curves("roc"), "fig06": lambda: curves("pr"), "fig07": fig07, "fig08": fig08, "fig09": fig09,
       "fig10": fig10, "fig11": fig11, "fig12": fig12, "fig13": fig13}

if __name__ == "__main__":
    which = sys.argv[1:] or list(ALL)
    for k in which:
        ALL[k]()
