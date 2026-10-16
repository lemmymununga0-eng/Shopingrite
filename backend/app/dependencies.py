"""Shared FastAPI dependencies: model, repositories, database, rate limiting."""
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from .auth import User, client_tag, current_user, optional_user
from .db.base import Repository
from .db.session import Database
from .ml.predict import Predictor


def get_predictor(request: Request) -> Predictor:
    return request.app.state.predictor


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_session(request: Request):
    """One database transaction per request: committed if the handler succeeds, rolled back if it raises."""
    with request.app.state.db.session() as session:
        yield session


def correlation(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


class RateLimiter:
    """Sliding window held in memory (fine for one server process; use Redis for several)."""

    def __init__(self):
        self.hits = defaultdict(deque)

    def check(self, key: str, limit: int, window: float = 60.0, message: str = "Too many requests. Slow down."):
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)
        q.append(now)


def predict_rate_limit(request: Request, user: User = Depends(current_user)) -> User:
    limiter: RateLimiter = request.app.state.limiter
    limiter.check("predict:" + user.id, request.app.state.settings.predict_rate_limit_per_min,
                  message="Too many prediction requests. Slow down.")
    return user


def limited(name: str, setting: str):
    """Rate-limit dependency factory. Keyed by user id when signed in, otherwise by a hashed client address."""
    def dep(request: Request, user: User | None = Depends(optional_user)) -> User | None:
        limit = getattr(request.app.state.settings, setting)
        who = user.id if user else client_tag(request)
        request.app.state.limiter.check(f"{name}:{who}", limit, message="Too many requests. Please wait a moment and try again.")
        return user
    return dep
