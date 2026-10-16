"""Shared FastAPI dependencies: model, repository, rate limiting."""
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from .auth import User, current_user
from .db.base import Repository
from .ml.predict import Predictor


def get_predictor(request: Request) -> Predictor:
    return request.app.state.predictor


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


class RateLimiter:
    """Per-user sliding window held in memory (fine for one server process; use Redis for several)."""

    def __init__(self):
        self.hits = defaultdict(deque)

    def check(self, key: str, limit: int, window: float = 60.0):
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many prediction requests. Slow down.")
        q.append(now)


def predict_rate_limit(request: Request, user: User = Depends(current_user)) -> User:
    limiter: RateLimiter = request.app.state.limiter
    limiter.check(user.id, request.app.state.settings.predict_rate_limit_per_min)
    return user
