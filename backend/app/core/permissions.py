"""The single source of truth for who may do what. Every protected route checks a permission here."""

CUSTOMER = "customer"
FRAUD_ANALYST = "fraud_analyst"
SECURITY_ANALYST = "security_analyst"
ADMIN = "admin"

ROLES = (CUSTOMER, FRAUD_ANALYST, SECURITY_ANALYST, ADMIN)
STAFF_ROLES = (FRAUD_ANALYST, SECURITY_ANALYST, ADMIN)

# Tokens issued before this change used "analyst"; it keeps meaning "fraud analyst".
ROLE_ALIASES = {"analyst": FRAUD_ANALYST}

_ALL_STAFF = set(STAFF_ROLES)

PERMISSIONS: dict[str, set[str]] = {
    # store (any signed-in user)
    "store.shop": set(ROLES),
    # inventory and orders (staff view; only admins change stock or fulfilment)
    "inventory.view": _ALL_STAFF,
    "inventory.adjust": {ADMIN},
    "orders.view_all": _ALL_STAFF,
    "orders.manage": {ADMIN},
    "catalogue.manage": {ADMIN},
    # fraud model, predictions and alerts
    "fraud.predict": _ALL_STAFF,
    "fraud.view": _ALL_STAFF,
    "fraud.review": {FRAUD_ANALYST, ADMIN},
    # ScamWatch: anyone signed in can check/report; staff review
    "scamwatch.check": set(ROLES),
    "scamwatch.view_all": _ALL_STAFF,
    "scamwatch.review": {SECURITY_ANALYST, ADMIN},
    # security monitor
    "security.view": {SECURITY_ANALYST, ADMIN},
    # investigations
    "cases.view": _ALL_STAFF,
    "cases.create": _ALL_STAFF,
    "cases.update": _ALL_STAFF,          # further limited by source type, see CASE_HANDLERS
    "cases.assign_any": {ADMIN},
    # reports, settings, administration
    "reports.view": _ALL_STAFF,
    "reports.fraud": {FRAUD_ANALYST, ADMIN},
    "reports.security": {SECURITY_ANALYST, ADMIN},
    "settings.view": _ALL_STAFF,
    "settings.edit": {ADMIN},
    "users.manage": {ADMIN},
    "audit.view": {SECURITY_ANALYST, ADMIN},
}

# Which analyst role works which kind of case. Admins work all of them.
CASE_HANDLERS: dict[str, set[str]] = {
    "fraud_prediction": {FRAUD_ANALYST, ADMIN},
    "order_anomaly": {FRAUD_ANALYST, ADMIN},
    "scamwatch_report": {SECURITY_ANALYST, ADMIN},
    "security_alert": {SECURITY_ANALYST, ADMIN},
    "manual": set(STAFF_ROLES),
}


def normalize_role(role: str | None) -> str:
    role = ROLE_ALIASES.get(role or "", role or CUSTOMER)
    return role if role in ROLES else CUSTOMER


def allowed(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())


def can_handle_case(role: str, source_type: str) -> bool:
    return role in CASE_HANDLERS.get(source_type, set())
