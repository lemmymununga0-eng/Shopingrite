"""Tiny, explicit schema migrations for the application database.

`create_all` only creates MISSING tables; it never alters existing ones. When a later change needs an ALTER,
add a numbered step here. Steps run once, in order, each in its own transaction, and are recorded in
`schema_migrations`, so upgrading a database that holds real data never drops or recreates anything.
"""
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, select

from ..models import Base, utcnow

_meta = MetaData()
schema_migrations = Table("schema_migrations", _meta,
                          Column("version", Integer, primary_key=True),
                          Column("name", String(100), nullable=False),
                          Column("applied_at", DateTime(timezone=True), nullable=False))


def _baseline(conn):
    Base.metadata.create_all(conn)      # creates only the tables that do not exist yet


_PRODUCT_COLUMNS = [
    ("brand", "VARCHAR(80) NOT NULL DEFAULT ''"), ("pack_size", "VARCHAR(40) NOT NULL DEFAULT ''"),
    ("price_status", "VARCHAR(12) NOT NULL DEFAULT 'estimated'"), ("price_source_name", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("price_source_url", "VARCHAR(300) NOT NULL DEFAULT ''"), ("price_source_type", "VARCHAR(30) NOT NULL DEFAULT ''"),
    ("price_checked_on", "DATE"), ("offer_starts_on", "DATE"), ("offer_ends_on", "DATE"),
    ("image_alt", "VARCHAR(200) NOT NULL DEFAULT ''"), ("image_source", "VARCHAR(300) NOT NULL DEFAULT ''"),
    ("image_license", "VARCHAR(80) NOT NULL DEFAULT ''"), ("image_status", "VARCHAR(16) NOT NULL DEFAULT 'placeholder'"),
]


def _retail_columns(conn):
    """Add retail/provenance columns to an existing products table and create price_history."""
    from sqlalchemy import inspect, text
    have = {c["name"] for c in inspect(conn).get_columns("products")}
    for name, ddl in _PRODUCT_COLUMNS:
        if name not in have:
            conn.execute(text(f"ALTER TABLE products ADD COLUMN {name} {ddl}"))
    Base.metadata.create_all(conn)      # price_history (and any other missing table)


_ORDER_COLUMNS = [
    ("payment_method", "VARCHAR(20) NOT NULL DEFAULT 'simulated'"), ("payment_due_at", "DATETIME"),
    ("area", "VARCHAR(80) NOT NULL DEFAULT ''"), ("delivery_instructions", "VARCHAR(300) NOT NULL DEFAULT ''"),
]


def _payments_ledger_states(engine):
    """Payment attempts/events, idempotency keys, status history, stock ledger, and the wider order status set.

    SQLite cannot alter a CHECK constraint, so the orders table is rebuilt (SQLite's documented 12-step procedure).
    That needs foreign keys OFF, which cannot be changed inside a transaction, hence the raw connection. The whole
    rebuild is one transaction: it either completes or leaves the database as it was."""
    from sqlalchemy import inspect, text
    from sqlalchemy.schema import CreateIndex, CreateTable
    from sqlalchemy.dialects import sqlite
    from ..models import Order

    if engine.dialect.name == "sqlite":
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute("PRAGMA foreign_keys=OFF")
            cur.execute("BEGIN IMMEDIATE")
            try:
                have = {r[1] for r in cur.execute("PRAGMA table_info(orders)")}
                if have:
                    for name, ddl in _ORDER_COLUMNS:
                        if name not in have:
                            cur.execute(f"ALTER TABLE orders ADD COLUMN {name} {ddl}")
                    cur.execute("UPDATE orders SET payment_status='paid' WHERE payment_status='simulated_approved'")
                    sql = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='orders'").fetchone()[0]
                    if "awaiting_payment" not in sql:
                        ddl = str(CreateTable(Order.__table__).compile(dialect=sqlite.dialect()))
                        cur.execute(ddl.replace("CREATE TABLE orders (", "CREATE TABLE orders_new (", 1))
                        cols = ", ".join(r[1] for r in cur.execute("PRAGMA table_info(orders)").fetchall())
                        cur.execute(f"INSERT INTO orders_new ({cols}) SELECT {cols} FROM orders")
                        cur.execute("DROP TABLE orders")
                        cur.execute("ALTER TABLE orders_new RENAME TO orders")
                        for idx in Order.__table__.indexes:
                            cur.execute(str(CreateIndex(idx).compile(dialect=sqlite.dialect())))
                    bad = cur.execute("PRAGMA foreign_key_check").fetchall()
                    if bad:
                        raise RuntimeError(f"foreign key check failed after orders rebuild: {bad[:3]}")
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
            finally:
                cur.execute("PRAGMA foreign_keys=ON")
        finally:
            raw.close()
    else:
        with engine.begin() as conn:
            have = {c["name"] for c in inspect(conn).get_columns("orders")}
            for name, ddl in _ORDER_COLUMNS:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE orders ADD COLUMN {name} {ddl.replace('DATETIME', 'TIMESTAMPTZ')}"))
            conn.execute(text("UPDATE orders SET payment_status='paid' WHERE payment_status='simulated_approved'"))
            conn.execute(text("ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_order_status"))
            conn.execute(text("ALTER TABLE orders ADD CONSTRAINT ck_order_status CHECK (status in ('awaiting_payment',"
                              "'payment_failed','confirmed','picking','ready','out_for_delivery','completed','cancelled'))"))
    with engine.begin() as conn:
        Base.metadata.create_all(conn)      # new tables
        # Opening balance for the ledger: today's stock becomes the first movement of every product that has none.
        conn.execute(text(
            "INSERT INTO stock_movements (product_id, delta_available, delta_reserved, reason, note, created_at) "
            "SELECT i.product_id, i.available_quantity, i.reserved_quantity, 'initial_stock', 'opening balance (migration)', "
            "CURRENT_TIMESTAMP FROM inventory i WHERE NOT EXISTS (SELECT 1 FROM stock_movements m WHERE m.product_id = i.product_id)"))


_payments_ledger_states.engine_level = True


def _attempt_checkout_url(conn):
    """Hosted-checkout link on payment attempts (real payments)."""
    from sqlalchemy import inspect, text
    have = {c["name"] for c in inspect(conn).get_columns("payment_attempts")}
    if "checkout_url" not in have:
        conn.execute(text("ALTER TABLE payment_attempts ADD COLUMN checkout_url VARCHAR(400) NOT NULL DEFAULT ''"))


def _ml_experimental_flag(conn):
    """Shadow-mode flag on stored model results (the table itself came from step 6)."""
    from sqlalchemy import inspect, text
    have = {c["name"] for c in inspect(conn).get_columns("ml_predictions")}
    if "experimental" not in have:
        conn.execute(text("ALTER TABLE ml_predictions ADD COLUMN experimental BOOLEAN NOT NULL DEFAULT FALSE"))


# (version, name, function(connection)). Append new steps; never edit or reorder old ones.
MIGRATIONS = [
    (1, "baseline schema", _baseline),
    (2, "retail product details, price provenance, price history", _retail_columns),
    (3, "payment attempts, idempotency, status history, stock ledger, new order states", _payments_ledger_states),
    (4, "payment attempt checkout url", _attempt_checkout_url),
    (5, "fraud assessments", _baseline),            # create_all adds only the missing table
    (6, "ml predictions and order outcomes", _baseline),
    (7, "ml prediction experimental flag", _ml_experimental_flag),
]


def migrate(engine) -> list[int]:
    """Apply any pending steps and return the versions applied in this call."""
    _meta.create_all(engine)
    with engine.connect() as conn:
        done = {row[0] for row in conn.execute(select(schema_migrations.c.version))}
    applied = []
    for version, name, fn in MIGRATIONS:
        if version in done:
            continue
        if getattr(fn, "engine_level", False):          # manages its own transactions (see step 3)
            fn(engine)
            with engine.begin() as conn:
                conn.execute(schema_migrations.insert().values(version=version, name=name, applied_at=utcnow()))
        else:
            with engine.begin() as conn:
                fn(conn)
                conn.execute(schema_migrations.insert().values(version=version, name=name, applied_at=utcnow()))
        applied.append(version)
    return applied
