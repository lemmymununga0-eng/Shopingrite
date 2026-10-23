"""Figure 1 (system architecture) and Figure 2 (research workflow), drawn with matplotlib so they regenerate from code."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from _common import FIGS  # noqa: E402

# Okabe-Ito colour-blind-safe palette
BLUE, ORANGE, GREEN, RED, PURPLE, GREY, SKY = "#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#6B6B6B", "#56B4E9"
plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"], "font.size": 8})


def box(ax, x, y, w, h, text, fc="#FFFFFF", ec="#333333", fs=7.5, bold=False, lw=1.0, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.015", fc=fc, ec=ec, lw=lw, ls=ls, zorder=2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal", zorder=3, linespacing=1.2)


def arrow(ax, p, q, color="#333333", lw=1.0, style="-|>", ls="-"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=9, lw=lw, color=color, ls=ls, zorder=1))


def architecture():
    fig, ax = plt.subplots(figsize=(7.0, 5.4))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    def tier(y0, y1, title, fc, ec, tc, right=False):
        ax.add_patch(FancyBboxPatch((0.01, y0), 0.98, y1 - y0, boxstyle="round,pad=0.004,rounding_size=0.015", fc=fc, ec=ec, lw=0.8))
        ax.text(0.975 if right else 0.025, y1 - 0.012, title, fontsize=7.2, color=tc, fontweight="bold", va="top", ha="right" if right else "left")

    tier(0.835, 0.985, "Clients (browser)", "#F3F8FC", "#9DBBD3", BLUE)
    tier(0.215, 0.805, "API service (FastAPI): one process; models are loaded once at start-up", "#FBFBF5", "#C9C9A8", "#7A6A00")
    tier(0.015, 0.195, "Data and external services", "#F4FAF7", "#9CCDB8", GREEN, right=True)

    cx = [0.03, 0.275, 0.52, 0.765]
    cw = 0.205
    box(ax, 0.03, 0.855, 0.29, 0.085, "Customer storefront\n(React, on Vercel)", ec=BLUE)
    box(ax, 0.355, 0.855, 0.29, 0.085, "Staff console (admin only)\norders, risk, cases, models", ec=BLUE)
    box(ax, 0.68, 0.855, 0.29, 0.085, "Sign-in (Supabase Auth)\nJWT verified by the API", ec=GREY)

    yb = 0.600
    box(ax, cx[0], yb, cw, 0.105, "Checkout\norder + payment attempt\n(idempotent)", ec=ORANGE)
    box(ax, cx[1], yb, cw, 0.105, "Rule engine\nstore_risk_v1\n9 rules, 12 fields", ec=ORANGE, fc="#FFF3D9", bold=True)
    box(ax, cx[2], yb, cw, 0.105, "Alert policy\ncase if score ≥ 30\nor a hard rule fires", ec=RED)
    box(ax, cx[3], yb, cw, 0.105, "Staff outcomes\nappend-only,\nverified flag", ec=RED)
    yc = 0.425
    box(ax, cx[0], yc, cw, 0.105, "Payments\nFlutterwave checkout,\nwebhook + re-check", ec=ORANGE)
    box(ax, cx[1], yc, cw, 0.105, "Schema guard\ngrocery_txn_v1\nno padding or defaults", ec=PURPLE)
    box(ax, cx[2], yc, cw, 0.105, "Model service\nstore_grocery (experimental)\ncard model (research)", ec=PURPLE, fs=6.8)
    box(ax, cx[3], yc, cw, 0.105, "ScamWatch\nURL rules + phishing\nmodel (opt-in)", ec=PURPLE)
    yd = 0.255
    box(ax, 0.03, yd, 0.445, 0.115, "Label pipeline (offline, manual)\nverified outcomes → labelled data → grouped split\n→ calibrate → gate vs rules → registry", ec=GREY, fc="#F2F2F2", fs=7)
    box(ax, 0.525, yd, 0.445, 0.115, "Audit and security\nrole check on every route, audit log, security\nevents, rate limits, response headers", ec=GREY, fc="#F2F2F2", fs=7)

    ye = 0.030
    box(ax, 0.03, ye, 0.215, 0.11, "PostgreSQL\norders, assessments,\npredictions, outcomes", ec=GREEN, fs=7)
    box(ax, 0.275, ye, 0.2, 0.11, "Model artifacts\njoblib + metadata +\nSHA-256, current.json", ec=GREEN, fs=7)
    box(ax, 0.525, ye, 0.215, 0.11, "Flutterwave\ncard, MTN, Airtel", ec=GREEN)
    box(ax, 0.765, ye, 0.205, 0.11, "Public datasets\n(offline training only)", ec=GREEN, ls="--")

    for x in (0.175, 0.50, 0.825):
        arrow(ax, (x, 0.855), (x, 0.805), color=BLUE)
    for a, b in ((0, 1), (1, 2), (2, 3)):
        arrow(ax, (cx[a] + cw, yb + 0.052), (cx[b], yb + 0.052), color=RED if a >= 1 else "#333333")
    arrow(ax, (cx[1] + cw / 2, yb), (cx[1] + cw / 2, yc + 0.105), color=PURPLE)
    arrow(ax, (cx[1] + cw, yc + 0.052), (cx[2], yc + 0.052), color=PURPLE)
    arrow(ax, (0.2525, yd), (0.2525, ye + 0.11), color=GREEN)
    arrow(ax, (0.1375, yd), (0.1375, ye + 0.11), color=GREEN)
    ax.text(0.5, -0.025, "Arrows show the request path (blue, black, red, purple) and data storage (green). Dashed box: used offline only.", ha="center", fontsize=6.3, color=GREY)
    fig.savefig(FIGS / "fig01_architecture.png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def workflow():
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.5, 0.975, "Training and evaluation protocol (identical for every model and dataset)", ha="center", va="top", fontsize=8.5, fontweight="bold")
    steps = [
        ("1  Acquire", "download with licence\nacceptance, schema check,\nSHA-256 manifest", SKY),
        ("2  Clean", "drop duplicates and\nnon-finite rows; map labels;\nexclude leaky columns", SKY),
        ("3  Split first", "80/20 stratified (cards),\ndomain-grouped (URLs),\nchronological check", ORANGE),
        ("4  Select", "cross-validate candidates\non the training part only;\ncriterion: PR-AUC", ORANGE),
        ("5  Calibrate", "isotonic map and threshold\n(F2 or false-alarm cap) from\nout-of-fold training predictions", ORANGE),
        ("6  Test once", "refit, score the held-out\npart one time; bootstrap\nintervals, paired tests", GREEN),
        ("7  Gate", "≥30 fraud rows in test;\nbeats dummy and rules;\nreload; URL edit checks", GREEN),
        ("8  Register", "versioned artifact + SHA-256;\npromote only if the gate\npasses; roll back on demand", PURPLE),
    ]
    w, h = 0.225, 0.20
    xs = [0.02, 0.27, 0.52, 0.77]
    rows = [0.69, 0.43]
    for i, (t, d, c) in enumerate(steps):
        r, col = divmod(i, 4)
        x, y = xs[col], rows[r]
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.015", fc=c, ec="#333333", lw=0.8, alpha=0.9))
        ax.text(x + w / 2, y + h - 0.045, t, ha="center", va="center", fontsize=7.6, fontweight="bold")
        ax.text(x + w / 2, y + 0.075, d, ha="center", va="center", fontsize=6.3, linespacing=1.2)
    for i in range(7):
        r, col = divmod(i, 4)
        r2, col2 = divmod(i + 1, 4)
        if r == r2:
            arrow(ax, (xs[col] + w + 0.002, rows[r] + h / 2), (xs[col2] - 0.002, rows[r] + h / 2))
        else:
            arrow(ax, (xs[3] + w / 2, rows[0]), (xs[0] + w / 2, rows[1] + h))
    ax.add_patch(FancyBboxPatch((0.02, 0.03), 0.975, 0.33, boxstyle="round,pad=0.004,rounding_size=0.015", fc="#FFF5F0", ec=RED, lw=0.8))
    ax.text(0.5, 0.335, "Controls against leakage and over-optimism", ha="center", va="top", fontsize=7.6, fontweight="bold", color=RED)
    guards = ["no fitting before the split\n(scaler, encoder, calibrator)", "duplicates removed before\nsplitting; websites grouped",
              "test set never used to pick\nmodel, threshold or calibration", "uncertainty reported:\nbootstrap CI, 5 seeds, McNemar",
              "shortcut checks: ablation,\ncosmetic edits, control subset", "rules baseline: a model must\nbeat store_risk_v1"]
    for i, g in enumerate(guards):
        r, col = divmod(i, 3)
        ax.text(0.185 + col * 0.31, 0.235 - r * 0.115, g, ha="center", va="center", fontsize=6.4, linespacing=1.2)
    fig.savefig(FIGS / "fig02_workflow.png", dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    workflow()
    print("figures written to", FIGS)
