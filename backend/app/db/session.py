"""Engine and session factory for the application database (SQLite locally, PostgreSQL if configured)."""
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool



class Database:
    def __init__(self, url: str):
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        if self.is_sqlite:
            path = url.split("///", 1)[-1]
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            # NullPool: every unit of work gets its own connection, so a failed request can never leak state
            # into another one and file locking is released promptly.
            self.engine = create_engine(url, poolclass=NullPool, connect_args={"timeout": 30, "check_same_thread": False})
            self._configure_sqlite()
        else:
            self.engine = create_engine(url, pool_pre_ping=True)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    def _configure_sqlite(self):
        @event.listens_for(self.engine, "connect")
        def _on_connect(dbapi_conn, _record):
            dbapi_conn.isolation_level = None          # we control BEGIN ourselves (see below)
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        @event.listens_for(self.engine, "begin")
        def _on_begin(conn):
            # Take the write lock up front. Two checkouts therefore cannot both read the same stock level
            # and then both write; the second waits for the first to commit.
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    def create_all(self):
        """Bring the schema up to date (see db/migrations). Safe to run on every start."""
        from .migrations import migrate
        return migrate(self.engine)

    @contextmanager
    def session(self):
        """One transaction: commit on success, roll back on any error, always close."""
        s: Session = self._factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def ping(self) -> bool:
        try:
            with self.engine.connect() as c:
                c.exec_driver_sql("SELECT 1")
            return True
        except Exception:
            return False

    def dispose(self):
        self.engine.dispose()
