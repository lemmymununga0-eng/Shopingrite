"""Records the application's own security-relevant events and raises threshold alerts.

This monitors THIS application only. It does not watch any retailer network or production infrastructure.
Every field is redacted before it is stored.
"""
import json
import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import func, select

from ..core.security import redact, redact_text
from ..db.models import AlertThreshold, SecurityEvent, utcnow

log = logging.getLogger("fraudguard.security")

SEVERITIES = ("info", "low", "medium", "high", "critical")
CATEGORIES = ("authentication", "authorization", "rate_limit", "input", "application", "model", "provider",
              "privileged", "inventory", "order", "threshold")

DEFAULT_THRESHOLDS = {
    "auth_failures_per_10min": 10,       # from one client
    "rate_limit_hits_per_10min": 20,     # from one client
    "server_errors_per_10min": 5,        # application-wide
}
_WINDOW = timedelta(minutes=10)
# category -> (threshold key, grouped by client?)
_WATCHED = {"authentication": ("auth_failures_per_10min", True), "rate_limit": ("rate_limit_hits_per_10min", True),
            "application": ("server_errors_per_10min", False)}


class SecurityEvents:
    def __init__(self, db):
        self.db = db
        self._recent: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def seed_thresholds(self):
        with self.db.session() as s:
            for key, value in DEFAULT_THRESHOLDS.items():
                if s.get(AlertThreshold, key) is None:
                    s.add(AlertThreshold(key=key, value=value))

    def thresholds(self) -> dict[str, int]:
        with self.db.session() as s:
            rows = {r.key: r.value for r in s.scalars(select(AlertThreshold))}
        return {**DEFAULT_THRESHOLDS, **rows}

    def _throttled(self, key: tuple, seconds: float = 5.0) -> bool:
        """True if an identical event was recorded very recently (stops one repeated failure filling the table)."""
        now = time.monotonic()
        with self._lock:
            if len(self._recent) > 5000:
                self._recent = {k: t for k, t in self._recent.items() if now - t < seconds}
            last = self._recent.get(key)
            if last is not None and now - last < seconds:
                return True
            self._recent[key] = now
        return False

    def record(self, severity: str, category: str, event_type: str, message: str, *, actor_id=None, client_tag=None,
               path=None, method=None, status_code=None, correlation_id=None, details=None,
               dedupe: bool = False) -> int | None:
        """Never raises for storage problems: failing to record must not break the request that caused it."""
        if severity not in SEVERITIES or category not in CATEGORIES:
            raise ValueError("unknown severity or category")
        if dedupe and self._throttled((event_type, client_tag, actor_id, path)):
            return None
        try:
            with self.db.session() as s:
                ev = SecurityEvent(severity=severity, category=category, event_type=event_type,
                                   message=redact_text(message), actor_id=actor_id, client_tag=client_tag,
                                   path=(path or "")[:200] or None, method=method, status_code=status_code,
                                   correlation_id=correlation_id,
                                   details_json=json.dumps(redact(details or {}), default=str))
                s.add(ev)
                s.flush()
                event_id = ev.id
            log.info("security_event %s/%s %s cid=%s", category, severity, event_type, correlation_id)
        except Exception:
            log.exception("could not record security event")
            return None
        try:
            self._check_threshold(category, client_tag, correlation_id)
        except Exception:
            log.exception("threshold check failed")
        return event_id

    def _check_threshold(self, category: str, client_tag: str | None, correlation_id: str | None):
        watched = _WATCHED.get(category)
        if not watched:
            return
        key, per_client = watched
        limit = self.thresholds()[key]
        since = utcnow() - _WINDOW
        with self.db.session() as s:
            q = select(func.count()).select_from(SecurityEvent).where(
                SecurityEvent.category == category, SecurityEvent.created_at >= since)
            if category == "authentication":
                q = q.where(SecurityEvent.event_type.like("auth.%"))
            if per_client:
                q = q.where(SecurityEvent.client_tag == client_tag)
            if s.scalar(q) < limit:
                return
            marker = f"{key}:{client_tag or 'all'}"
            already = s.scalar(select(func.count()).select_from(SecurityEvent).where(
                SecurityEvent.category == "threshold", SecurityEvent.event_type == "threshold.exceeded",
                SecurityEvent.created_at >= since, SecurityEvent.message.contains(marker)))
            if already:
                return
            ev = SecurityEvent(severity="high", category="threshold", event_type="threshold.exceeded",
                               message=f"Alert threshold exceeded: {marker} (limit {limit} per 10 minutes)",
                               client_tag=client_tag, correlation_id=correlation_id,
                               details_json=json.dumps({"threshold": key, "limit": limit, "window_minutes": 10}))
            s.add(ev)
            s.flush()
            from .investigation_service import ensure_case   # local import: avoids an import cycle
            ensure_case(s, source_type="security_alert", source_record_id=str(ev.id), severity="high",
                        summary=ev.message, evidence_reference=f"security_event:{ev.id}", created_by=None,
                        correlation_id=correlation_id)
