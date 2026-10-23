"""Labelled grocery-order data: built ONLY from what the store itself recorded and a person verified.

  features = the `store_risk` feature snapshot saved with the order's FIRST assessment (trigger 'order_placed'), i.e. exactly what was
             known when the order arrived (see store_schema.py);
  label    = the order's latest outcome, and only if a reviewer marked it verified:
               confirmed_fraud -> 1;  legitimate, false_positive -> 0.
             'undetermined' outcomes and every unverified outcome are EXCLUDED. Suspicion, a rule firing, an open case, a high score or
             a failed payment is never a label. Orders with no outcome are unlabelled and are not used (they are not assumed legitimate).

Nothing here creates, guesses or balances labels. With no verified outcomes the dataset is empty and training is refused.
"""
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sqlalchemy import select

from ..db.models import FraudAssessment, Order, OrderOutcome
from . import store_schema as schema
from .datasets import candidates_default
from .framework import TaskSpec

MODEL_NAME = "store_grocery"
LABEL_OF = {"confirmed_fraud": 1, "legitimate": 0, "false_positive": 0}

# Minimum evidence before a supervised model is even attempted. The validation gate then still has to pass (>= 30 fraud rows in the
# held-out test set means roughly 150 verified fraud cases overall).
MIN_VERIFIED_FRAUD = 150
MIN_VERIFIED_LEGITIMATE = 1000
MIN_DISTINCT_CUSTOMERS = 50
# Below this many verified fraud cases a promoted model is still labelled EXPERIMENTAL (shadow mode: recorded, never alerts).
VALIDATED_AT_FRAUD = 1000


@dataclass
class Requirements:
    fraud: int = MIN_VERIFIED_FRAUD
    legitimate: int = MIN_VERIFIED_LEGITIMATE
    customers: int = MIN_DISTINCT_CUSTOMERS


def labelled_rows(session) -> tuple[pd.DataFrame, dict]:
    """(DataFrame of usable labelled orders, counts explaining what was included and excluded)."""
    latest: dict[str, OrderOutcome] = {}
    for o in session.scalars(select(OrderOutcome).order_by(OrderOutcome.id)):
        latest[o.order_id] = o                        # later rows replace earlier ones: the newest conclusion wins
    counts = {"orders_with_outcome": len(latest), "excluded_unverified": 0, "excluded_undetermined": 0,
              "excluded_no_assessment": 0, "excluded_invalid_features": 0, "used": 0}
    first = {}
    for a in session.scalars(select(FraudAssessment).where(FraudAssessment.trigger == "order_placed").order_by(FraudAssessment.id)):
        first.setdefault(a.order_id, a)
    orders = {o.id: o for o in session.scalars(select(Order).where(Order.id.in_(list(latest) or [""])))}
    rows = []
    for oid, out in latest.items():
        if not out.verified:
            counts["excluded_unverified"] += 1
            continue
        if out.outcome not in LABEL_OF:
            counts["excluded_undetermined"] += 1
            continue
        a, order = first.get(oid), orders.get(oid)
        if a is None or order is None:
            counts["excluded_no_assessment"] += 1
            continue
        f = json.loads(a.features_json or "{}")
        if schema.validate(f) is not None:
            counts["excluded_invalid_features"] += 1
            continue
        rows.append({"order_id": oid, "user_id": order.user_id, "created_at": order.created_at, **schema.row(f), "label": LABEL_OF[out.outcome],
                     "rules_score": a.score, "rules_decision": a.decision})
        counts["used"] += 1
    cols = ["order_id", "user_id", "created_at", *schema.FEATURE_NAMES, "label", "rules_score", "rules_decision"]
    return pd.DataFrame(rows, columns=cols), counts


def readiness(session, req: Requirements | None = None) -> dict:
    req = req or Requirements()
    df, counts = labelled_rows(session)
    fraud, legit = int((df["label"] == 1).sum()), int((df["label"] == 0).sum())
    customers = int(df["user_id"].nunique()) if len(df) else 0
    need = {"verified_fraud": (fraud, req.fraud), "verified_legitimate": (legit, req.legitimate), "distinct_customers": (customers, req.customers)}
    unflagged = int(((df["rules_decision"] == "allow")).sum()) if len(df) else 0
    short = [f"{k.replace('_', ' ')}: {have} of {want}" for k, (have, want) in need.items() if have < want]
    return {"schema_version": schema.SCHEMA_VERSION, "ready_to_train": not short, "verified_fraud": fraud, "verified_legitimate": legit,
            "distinct_customers": customers, "verified_from_unflagged_orders": unflagged, "required": {"verified_fraud": req.fraud, "verified_legitimate": req.legitimate, "distinct_customers": req.customers},
            "shortfall": short, "counts": counts,
            "message": ("Enough verified outcomes to attempt training." if not short else
                        "Not enough verified outcomes to train a supervised model: " + "; ".join(short) + ". Rule-based scoring (store_risk_v1) remains in use.")}


# ------------------------------------------------------------------------------------------------ the training task
def _prep(X: pd.DataFrame) -> pd.DataFrame:
    out = X.copy()
    out["log_total"] = np.log1p(out["total_cents"].astype(float))
    out["log_avg_paid"] = np.log1p(out["average_paid_total_cents"].astype(float))
    out["total_vs_usual"] = out["total_cents"].astype(float) / (out["average_paid_total_cents"].astype(float) + 100.0)
    out["night"] = (out["local_hour"].astype(int) < 5).astype(int)
    return out


NUM_COLS = ["log_total", "log_avg_paid", "total_vs_usual", "max_line_quantity", "orders_last_hour", "prior_orders", "prior_paid_orders",
            "failed_payments_24h", "rejected_checkouts_10m", "delivery_address_seen_before", "night"]


def _pre():
    return Pipeline([("features", FunctionTransformer(_prep, validate=False)),
                     ("cols", ColumnTransformer([
                         ("cat", OneHotEncoder(categories=[schema.FULFILMENTS, schema.PAYMENT_METHODS], handle_unknown="error"), ["fulfilment", "payment_method"]),
                         ("num", StandardScaler(), NUM_COLS)]))])


def store_task(df: pd.DataFrame, dataset: dict | None = None, fast: bool = False, is_fixture: bool = False,
               req: Requirements | None = None) -> TaskSpec:
    req = req or Requirements()
    if df.empty:
        raise InsufficientLabels("There are no verified outcomes yet.")
    fraud, legit = int((df["label"] == 1).sum()), int((df["label"] == 0).sum())
    customers = int(df["user_id"].nunique())
    if fraud < req.fraud or legit < req.legitimate or customers < req.customers:
        raise InsufficientLabels(f"Verified labels so far: {fraud} fraud (need {req.fraud}), {legit} legitimate (need {req.legitimate}), "
                                 f"{customers} customers (need {req.customers}).")
    df = df.sort_values("created_at").reset_index(drop=True)
    codes = pd.factorize(df["user_id"])[0]
    experimental = fraud < VALIDATED_AT_FRAUD
    return TaskSpec(
        model_name=MODEL_NAME, task="Grocery-store order risk (verified analyst outcomes)",
        dataset={"name": "store-verified-outcomes", "source": "this store's orders and verified analyst outcomes", "licence": "internal",
                 "licence_status": "own data", "sha256": "n/a (database snapshot)", "schema_version": schema.SCHEMA_VERSION, "rows_raw": int(len(df)),
                 **(dataset or {})},
        X=df[schema.FEATURE_NAMES].reset_index(drop=True), y=df["label"].rename("verified_fraud"), input_features=list(schema.FEATURE_NAMES),
        feature_types={n: schema.SPEC[n]["kind"] for n in schema.FEATURE_NAMES}, preprocessor=_pre, candidates=candidates_default(fast),
        target_definition="1 = a reviewer marked the order confirmed fraud AND verified it; 0 = verified legitimate or false alarm. "
                          "Unverified, undetermined and unreviewed orders are not used.",
        preprocessing_description="Money amounts are log-transformed, a total-versus-usual ratio and a night flag are derived, categories are one-hot "
                                  "encoded with fixed vocabularies, numbers are standardised with training-partition statistics only.",
        excluded_features=[{"name": n, "reason": r} for n, r in schema.EXCLUDED],
        derived_features=[{"name": "log_total", "from": "total_cents"}, {"name": "log_avg_paid", "from": "average_paid_total_cents"},
                          {"name": "total_vs_usual", "from": "total_cents / average_paid_total_cents"}, {"name": "night", "from": "local_hour"}],
        cleaning={"rows_used": int(len(df)), "verified_fraud": fraud, "verified_legitimate": legit, "distinct_customers": customers},
        groups=codes, order=df["created_at"].astype("int64").to_numpy(), min_pr_auc=0.3, is_fixture=is_fixture,
        source_note="Verified outcomes recorded by staff. Labels are only as good as the review process; see docs/LABEL_COLLECTION.md.",
        limitations=[
            "Selection bias: staff mostly review orders the rules already flagged, so verified labels over-represent rule-flagged orders. "
            "Unflagged orders are only labelled if sampled for audit.",
            "A customer's orders never straddle the train/test split (grouped by customer), so results measure generalisation to NEW customers.",
            f"{'EXPERIMENTAL: fewer than ' + str(VALIDATED_AT_FRAUD) + ' verified fraud cases. ' if experimental else ''}"
            f"Only {fraud} verified fraud cases: precision/recall estimates are wide.",
            "Outcome labels reflect what staff could verify (chargebacks, customer contact), not every fraud."])


class InsufficientLabels(Exception):
    """Not enough verified outcomes to train honestly. The message says what is missing."""


# ------------------------------------------------------------------------------------------------ rules baseline
def rules_baseline(df: pd.DataFrame, seed: int = 42) -> dict:
    """How well the EXISTING rule score ranks the same held-out customers the model will be tested on (same group split as training).
    A supervised model is only worth promoting if it beats this."""
    from sklearn.metrics import average_precision_score
    from .framework import group_split
    df = df.sort_values("created_at").reset_index(drop=True)          # same order store_task uses
    y = df["label"].to_numpy()
    split = group_split(y, pd.factorize(df["user_id"])[0], seed=seed)
    te = df.iloc[split.test_idx]
    return {"engine": "store_risk_v1", "test_rows": int(len(te)), "test_fraud": int(te["label"].sum()),
            "pr_auc": float(average_precision_score(te["label"], te["rules_score"])),
            "note": "PR-AUC of the rule score on the same held-out customers. A model must beat it to be promoted."}
