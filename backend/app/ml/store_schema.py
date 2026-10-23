"""Versioned feature schema for grocery-store checkout risk: the ONLY inputs a store model may use.

Every field is something the store really records at (or before) the moment an order is assessed. Nothing here comes from the
outcome (shipping, delivery, chargeback, analyst verdict) and nothing is a secret: no passwords, no card numbers, no CVV, no
provider tokens, no names, e-mail addresses, phone numbers or street addresses (address reuse is reduced to a yes/no flag).

The values are produced by `services/store_risk.compute`, which stores exactly this dictionary with every assessment, so the
training data for a future model is the set of snapshots the store already keeps, taken at the time of the event.

Changing a field, its meaning or its allowed values requires a NEW version string; models record the version they were trained on and
are refused (schema_incompatible) when it differs.
"""
import math

SCHEMA_VERSION = "grocery_txn_v1"

PAYMENT_METHODS = ["card", "mtn_momo", "airtel_money", "cod", "simulated"]
FULFILMENTS = ["delivery", "collection"]
CURRENCIES = ["ZMW"]            # amounts are only comparable within one currency; any other currency is unsupported

# name, kind, allowed (range or values), missing-value handling, source, privacy note
FEATURE_SPECS = [
    dict(name="total_cents", kind="int", allowed=[1, 100_000_000], missing="reject", source="orders.total_cents",
         privacy="order value only"),
    dict(name="max_line_quantity", kind="int", allowed=[0, 10_000], missing="reject", source="max(order_items.quantity)",
         privacy="basket shape only, no product names"),
    dict(name="orders_last_hour", kind="int", allowed=[0, 1_000], missing="reject", source="count of this customer's orders in the hour up to the event",
         privacy="behavioural count for the customer's own account"),
    dict(name="prior_orders", kind="int", allowed=[0, 1_000_000], missing="reject", source="count of this customer's earlier orders",
         privacy="behavioural count for the customer's own account"),
    dict(name="prior_paid_orders", kind="int", allowed=[0, 1_000_000], missing="reject", source="count of this customer's earlier PAID orders",
         privacy="behavioural count for the customer's own account"),
    dict(name="average_paid_total_cents", kind="int", allowed=[0, 100_000_000], missing="0 when the customer has no paid orders",
         source="mean total of this customer's earlier paid orders", privacy="aggregate of the customer's own history"),
    dict(name="failed_payments_24h", kind="int", allowed=[0, 1_000], missing="reject", source="failed payment attempts by this customer in 24 h before the event",
         privacy="behavioural count; failure reasons are NOT used"),
    dict(name="rejected_checkouts_10m", kind="int", allowed=[0, 1_000], missing="reject", source="checkouts rejected (stock/validation) in the 10 min before the event",
         privacy="behavioural count"),
    dict(name="delivery_address_seen_before", kind="bool", allowed=[False, True], missing="False for collection orders or first orders",
         source="whether the delivery address matches one this customer used before", privacy="the address itself is never a feature, only this yes/no flag"),
    dict(name="fulfilment", kind="category", allowed=FULFILMENTS, missing="reject", source="orders.fulfilment", privacy="none"),
    dict(name="local_hour", kind="int", allowed=[0, 23], missing="reject", source="order creation time converted to Zambian local time",
         privacy="hour only, not the full timestamp"),
    dict(name="payment_method", kind="category", allowed=PAYMENT_METHODS, missing="reject", source="orders.payment_method (the chosen method, never card data)",
         privacy="method label only; card numbers never reach this store"),
]
GUARD_SPECS = [dict(name="currency", kind="category", allowed=CURRENCIES, source="orders.currency",
                    note="Guard only, not a model input: amounts in another currency are not comparable, so they are unsupported.")]

FEATURE_NAMES = [f["name"] for f in FEATURE_SPECS]
NUMERIC = [f["name"] for f in FEATURE_SPECS if f["kind"] in ("int", "bool")]
CATEGORICAL = {f["name"]: f["allowed"] for f in FEATURE_SPECS if f["kind"] == "category"}
SPEC = {f["name"]: f for f in FEATURE_SPECS}

# Deliberately NOT available / NOT used, with the reason (kept next to the schema so it is reviewed with it).
EXCLUDED = [
    ("payment outcome (paid/failed) of THIS order", "known only after the event: it would leak the future"),
    ("order status, delivery status, refund status", "known only after the event"),
    ("analyst outcome / case status", "this is the label, not an input"),
    ("customer name, e-mail, phone, address text", "personal data with no predictive need; address reuse is a yes/no flag"),
    ("card number, CVV, provider tokens, passwords", "never held by the store; must never be a feature"),
    ("IP address, device, country", "the store does not collect them"),
    ("customer id", "identifier: would let a model memorise customers; used only to keep a customer on one side of a split"),
]


def validate(features: dict) -> dict | None:
    """None when `features` is a complete, valid row of the schema. Otherwise a response dict with a clear status:
    unsupported_input_schema (names do not match, or an unsupported currency) or invalid_input (a bad value). Never coerces or pads."""
    supplied = set(features)
    allowed_names = set(FEATURE_NAMES) | {g["name"] for g in GUARD_SPECS}
    missing = [n for n in FEATURE_NAMES if n not in supplied]
    extra = sorted(supplied - allowed_names)
    if missing or extra:
        return {"status": "unsupported_input_schema", "message": "The supplied fields do not match the grocery transaction schema.",
                "schema_version": SCHEMA_VERSION, "missing_features": missing, "unexpected_features": extra, "required_features": FEATURE_NAMES}
    if "currency" in features and features["currency"] not in CURRENCIES:
        return {"status": "unsupported_input_schema", "message": f"Only {CURRENCIES} orders are supported; amounts in other currencies are not comparable.",
                "schema_version": SCHEMA_VERSION, "missing_features": [], "unexpected_features": ["currency"], "required_features": FEATURE_NAMES}
    problems = []
    for f in FEATURE_SPECS:
        v = features[f["name"]]
        if f["kind"] == "category":
            if v not in f["allowed"]:
                problems.append(f"{f['name']} must be one of {f['allowed']}")
        elif f["kind"] == "bool":
            if not isinstance(v, bool):
                problems.append(f"{f['name']} must be true or false")
        else:
            lo, hi = f["allowed"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v != int(v):
                problems.append(f"{f['name']} must be a whole number")
            elif not lo <= v <= hi:
                problems.append(f"{f['name']} must be between {lo} and {hi}")
    if problems:
        return {"status": "invalid_input", "message": "One or more values are not acceptable.", "schema_version": SCHEMA_VERSION, "problems": problems}
    return None


def row(features: dict) -> dict:
    """The model-input subset, in schema order (bool -> int). Call only after `validate` returned None."""
    return {n: (int(features[n]) if SPEC[n]["kind"] == "bool" else features[n]) for n in FEATURE_NAMES}


def document() -> list[dict]:
    """For the API / docs: the schema as data."""
    return [{**f, "schema_version": SCHEMA_VERSION} for f in FEATURE_SPECS]
