"""Application database models (see docs/data-model.md). Money is stored as integer minor units."""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, TypeDecorator,
                        UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator):
    """Always timezone-aware UTC in Python, even on SQLite which drops the zone."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class AppUser(Base):
    """Local DEMONSTRATION identities only. Production identities live in Supabase Auth."""
    __tablename__ = "app_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (CheckConstraint("role in ('customer','fraud_analyst','security_analyst','admin')", name="ck_user_role"),)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(default=0)
    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    price_cents: Mapped[int] = mapped_column(Integer)
    offer_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    unit: Mapped[str] = mapped_column(String(30), default="each")
    image_ref: Mapped[str] = mapped_column(String(200), default="")
    # --- retail details and provenance (price_status: 'verified' = checked against a dated source; 'observed' = seen on a
    # retailer page on price_checked_on, not guaranteed current; 'estimated' = demonstration figure, NOT a market price) ---
    brand: Mapped[str] = mapped_column(String(80), default="")
    pack_size: Mapped[str] = mapped_column(String(40), default="")
    price_status: Mapped[str] = mapped_column(String(12), default="estimated")
    price_source_name: Mapped[str] = mapped_column(String(120), default="")
    price_source_url: Mapped[str] = mapped_column(String(300), default="")
    price_source_type: Mapped[str] = mapped_column(String(30), default="")
    price_checked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    offer_starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    offer_ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    image_alt: Mapped[str] = mapped_column(String(200), default="")
    image_source: Mapped[str] = mapped_column(String(300), default="")
    image_license: Mapped[str] = mapped_column(String(80), default="")
    image_status: Mapped[str] = mapped_column(String(16), default="placeholder")   # licensed | placeholder
    is_active: Mapped[bool] = mapped_column(default=True)
    is_featured: Mapped[bool] = mapped_column(default=False)
    is_demo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    category: Mapped[Category] = relationship(back_populates="products")
    inventory: Mapped["Inventory"] = relationship(back_populates="product", uselist=False)
    __table_args__ = (CheckConstraint("price_cents >= 0", name="ck_product_price"),
                      CheckConstraint("offer_price_cents is null or offer_price_cents >= 0", name="ck_product_offer"),
                      Index("ix_products_category_active", "category_id", "is_active"))


class Inventory(Base):
    __tablename__ = "inventory"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    available_quantity: Mapped[int] = mapped_column(Integer)
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0)   # held by confirmed, not yet completed orders
    reorder_threshold: Mapped[int] = mapped_column(Integer, default=5)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    product: Mapped[Product] = relationship(back_populates="inventory")
    __table_args__ = (CheckConstraint("available_quantity >= 0", name="ck_inv_available"),
                      CheckConstraint("reserved_quantity >= 0", name="ck_inv_reserved"))


class Cart(Base):
    __tablename__ = "carts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    items: Mapped[list["CartItem"]] = relationship(back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    __table_args__ = (UniqueConstraint("cart_id", "product_id", name="uq_cart_product"),
                      CheckConstraint("quantity > 0", name="ck_cartitem_qty"))


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reference: Mapped[str] = mapped_column(String(24), unique=True)
    user_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="awaiting_payment")
    fulfilment: Mapped[str] = mapped_column(String(12))                  # delivery | collection
    contact_name: Mapped[str] = mapped_column(String(120))
    contact_email: Mapped[str] = mapped_column(String(254))
    contact_phone: Mapped[str] = mapped_column(String(30))
    address_line: Mapped[str] = mapped_column(String(200), default="")
    city: Mapped[str] = mapped_column(String(80), default="")
    postal_code: Mapped[str] = mapped_column(String(12), default="")
    subtotal_cents: Mapped[int] = mapped_column(Integer)
    delivery_fee_cents: Mapped[int] = mapped_column(Integer)
    total_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    payment_mode: Mapped[str] = mapped_column(String(12), default="SIMULATED")
    payment_method: Mapped[str] = mapped_column(String(20), default="simulated")
    # payment_status: pending | requires_action | paid | failed | cancelled | cod_due
    payment_status: Mapped[str] = mapped_column(String(24), default="pending")
    payment_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)   # stock hold ends here
    area: Mapped[str] = mapped_column(String(80), default="")
    delivery_instructions: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_orders_user_created", "user_id", "created_at"),
                      CheckConstraint("status in ('awaiting_payment','payment_failed','confirmed','picking','ready',"
                                      "'out_for_delivery','completed','cancelled')",
                                      name="ck_order_status"),
                      CheckConstraint("fulfilment in ('delivery','collection')", name="ck_order_fulfilment"))


class OrderItem(Base):
    """Snapshot of what was bought, so later price or name changes never rewrite history."""
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    sku: Mapped[str] = mapped_column(String(40))
    name_snapshot: Mapped[str] = mapped_column(String(160))
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    line_total_cents: Mapped[int] = mapped_column(Integer)
    order: Mapped[Order] = relationship(back_populates="items")


class SecurityEvent(Base):
    __tablename__ = "security_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    severity: Mapped[str] = mapped_column(String(10), index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(String(500))
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_tag: Mapped[str | None] = mapped_column(String(16), nullable=True)
    path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status_code: Mapped[int | None] = mapped_column(nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class ScamReport(Base):
    __tablename__ = "scam_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_url: Mapped[str] = mapped_column(String(2100))
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    report_count: Mapped[int] = mapped_column(Integer, default=1)
    first_reported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_reported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    reporter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reporter_comment: Mapped[str] = mapped_column(String(1000), default="")
    verdict: Mapped[str] = mapped_column(String(20), default="inconclusive")
    provider_summary_json: Mapped[str] = mapped_column(Text, default="[]")
    review_status: Mapped[str] = mapped_column(String(24), default="pending")
    analyst_notes: Mapped[str] = mapped_column(String(2000), default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (CheckConstraint("review_status in ('pending','reviewed_malicious','reviewed_benign','dismissed')",
                                      name="ck_scam_review"),)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_reference: Mapped[str] = mapped_column(String(20), unique=True)
    source_type: Mapped[str] = mapped_column(String(24))
    source_record_id: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16), default="new")
    summary: Mapped[str] = mapped_column(String(500))
    evidence_reference: Mapped[str] = mapped_column(String(300), default="")
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    notes: Mapped[list["CaseNote"]] = relationship(back_populates="case", cascade="all, delete-orphan",
                                                    order_by="CaseNote.id")
    __table_args__ = (UniqueConstraint("source_type", "source_record_id", name="uq_case_source"),
                      CheckConstraint("status in ('new','investigating','confirmed','false_positive','resolved')",
                                      name="ck_case_status"),
                      Index("ix_cases_status_severity", "status", "severity"))


class CaseNote(Base):
    __tablename__ = "case_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    author_id: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    case: Mapped[Case] = relationship(back_populates="notes")


class AuditEvent(Base):
    """Append-only. The API offers no way to change or delete these rows."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(64))
    before_json: Mapped[str] = mapped_column(Text, default="{}")
    after_json: Mapped[str] = mapped_column(Text, default="{}")
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AlertThreshold(Base):
    __tablename__ = "alert_thresholds"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class PriceHistory(Base):
    """Append-only record of every price change (seed load or administrator edit)."""
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    price_cents: Mapped[int] = mapped_column(Integer)
    offer_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    price_status: Mapped[str] = mapped_column(String(12))
    source_url: Mapped[str] = mapped_column(String(300), default="")
    recorded_by: Mapped[str] = mapped_column(String(64), default="seed")
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


def offer_is_active(p: "Product", today: date | None = None) -> bool:
    """An offer applies only inside its dates. An expired offer is never shown or charged."""
    if p.offer_price_cents is None:
        return False
    today = today or date.today()
    return (p.offer_starts_on is None or p.offer_starts_on <= today) and (p.offer_ends_on is None or p.offer_ends_on >= today)


def effective_price_cents(p: "Product", today: date | None = None) -> int:
    return p.offer_price_cents if offer_is_active(p, today) else p.price_cents


def active_offer_sql():
    """SQL twin of offer_is_active, for filtering and sorting in the database."""
    from sqlalchemy import and_, case, func, or_
    today = date.today()
    return case((and_(Product.offer_price_cents.is_not(None),
                      or_(Product.offer_starts_on.is_(None), Product.offer_starts_on <= today),
                      or_(Product.offer_ends_on.is_(None), Product.offer_ends_on >= today)),
                 Product.offer_price_cents), else_=None)


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str] = mapped_column(String(24), default="")
    to_status: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PaymentAttempt(Base):
    """One try at paying for an order. A failed attempt is kept; a retry creates a new row."""
    __tablename__ = "payment_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reference: Mapped[str] = mapped_column(String(24), unique=True)               # PAY-XXXXXXXX
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    method: Mapped[str] = mapped_column(String(20))                                # simulated | cod | airtel_money | ...
    provider: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(12), default="SIMULATED")            # SIMULATED | COD | LIVE
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    # initiated | pending | requires_action | succeeded | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="initiated")
    provider_reference: Mapped[str] = mapped_column(String(64), default="")        # Flutterwave transaction id once paid
    checkout_url: Mapped[str] = mapped_column(String(400), default="")             # hosted payment page (owner-only)
    failure_reason: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (CheckConstraint("status in ('initiated','pending','requires_action','succeeded','failed','cancelled')",
                                      name="ck_payment_attempt_status"),)


class PaymentEvent(Base):
    """Provider callbacks / simulated results. (provider, event_id) is unique, so a repeated event is ignored."""
    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey("payment_attempts.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(16), default="")
    signature_valid: Mapped[bool] = mapped_column(default=True)
    applied: Mapped[bool] = mapped_column(default=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_payment_event"),)


class PredictionRecord(Base):
    """Staff 'New Payment' predictions made with the payment-form model (DB_BACKEND=app). Timestamps are ISO text on
    purpose: the same strings the SQLite and Supabase backends use, so one stats function serves all three."""
    __tablename__ = "prediction_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    transaction_reference: Mapped[str] = mapped_column(String(60))
    amount: Mapped[float] = mapped_column()
    payment_method: Mapped[str] = mapped_column(String(20))
    hour: Mapped[int] = mapped_column(Integer)
    failed_attempts: Mapped[int] = mapped_column(Integer)
    new_device: Mapped[bool] = mapped_column()
    international: Mapped[bool] = mapped_column()
    customer_avg_spend: Mapped[float] = mapped_column()
    branch: Mapped[str] = mapped_column(String(30))
    probability: Mapped[float] = mapped_column()
    risk: Mapped[str] = mapped_column(String(10))
    prediction: Mapped[str] = mapped_column(String(20))
    is_flagged: Mapped[bool] = mapped_column()
    model_version: Mapped[str] = mapped_column(String(60))
    contributing_factors: Mapped[str] = mapped_column(Text, default="[]")
    review_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    __table_args__ = (CheckConstraint("review_status is null or review_status in ('new','confirmed_fraud','false_positive')",
                                      name="ck_prediction_review"),
                      Index("ix_prediction_flagged", "is_flagged", "review_status"))


class FraudAssessment(Base):
    """One risk assessment of an order by the rule engine `store_risk_v1` (rules, NOT machine learning). Rows are only
    added, never changed: the latest row for an order is its current assessment, older rows are the history."""
    __tablename__ = "fraud_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    engine: Mapped[str] = mapped_column(String(30))                    # store_risk
    version: Mapped[str] = mapped_column(String(10))                   # v1
    trigger: Mapped[str] = mapped_column(String(24), default="order_placed")   # order_placed | payment_failed | ...
    score: Mapped[int] = mapped_column(Integer)                        # 0-100
    decision: Mapped[str] = mapped_column(String(8))                   # allow | review | high
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")      # [{rule, points, text}]
    features_json: Mapped[str] = mapped_column(Text, default="{}")     # exactly the inputs used
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    __table_args__ = (CheckConstraint("decision in ('allow','review','high')", name="ck_assessment_decision"),
                      Index("ix_assessments_order_created", "order_id", "created_at"))


class IdempotencyKey(Base):
    """Replaying the same key returns the same order instead of creating a second one."""
    __tablename__ = "idempotency_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),)


class StockMovement(Base):
    """Append-only ledger of every stock change. Opening stock + all movements = the inventory row."""
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    delta_available: Mapped[int] = mapped_column(Integer)
    delta_reserved: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(30))     # initial_stock | order_reserved | order_cancelled | order_expired | order_completed | admin_adjustment
    order_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class MlPrediction(Base):
    """What the trained models said (or honestly could not say) about an order event. One row per
    (order, trigger, payment reference, model): replays and retries cannot add duplicates. A row with status other than 'ok'
    carries NO probability: the store never invents a score."""
    __tablename__ = "ml_predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(24))
    payment_ref: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32))                     # ok | unsupported_input_schema | model_unavailable | ...
    model_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    probability: Mapped[float | None] = mapped_column(nullable=True)
    threshold: Mapped[float | None] = mapped_column(nullable=True)
    flagged: Mapped[bool | None] = mapped_column(nullable=True)
    missing_features_json: Mapped[str] = mapped_column(Text, default="[]")
    experimental: Mapped[bool] = mapped_column(default=False)           # shadow mode: recorded, never alerts
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    __table_args__ = (UniqueConstraint("order_id", "trigger", "payment_ref", "model", name="uq_ml_prediction_event"),)


class OrderOutcome(Base):
    """A person's verified conclusion about an order (append-only; the latest row wins). Only rows with verified=True are
    eligible to become labels for future training, and nothing retrains automatically."""
    __tablename__ = "order_outcomes"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    outcome: Mapped[str] = mapped_column(String(24))
    verified: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str] = mapped_column(String(500), default="")
    reviewer_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    __table_args__ = (CheckConstraint("outcome in ('confirmed_fraud','false_positive','legitimate','undetermined')",
                                      name="ck_order_outcome"),)
