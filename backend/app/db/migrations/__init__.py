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


# (version, name, function(connection)). Append new steps; never edit or reorder old ones.
MIGRATIONS = [
    (1, "baseline schema", _baseline),
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
        with engine.begin() as conn:
            fn(conn)
            conn.execute(schema_migrations.insert().values(version=version, name=name, applied_at=utcnow()))
        applied.append(version)
    return applied
