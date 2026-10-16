"""Reports built from stored records only. Each metric carries its definition.

Nothing here claims money saved. The optional baseline comparison is labelled HYPOTHETICAL and uses numbers the
analyst supplies; it describes exposure identified in this prototype, not realised savings.
"""
import logging
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from ..auth import User, require
from ..db.base import RepositoryError
from ..db.models import AuditEvent, Case, Inventory, Order, ScamReport, SecurityEvent, utcnow
from ..dependencies import get_repo, get_session

log = logging.getLogger("fraudguard")
router = APIRouter(prefix="/reports", tags=["reports"])


def _counts(session, col, *where):
    q = select(col, func.count()).group_by(col)
    for w in where:
        q = q.where(w)
    return {k: v for k, v in session.execute(q).all()}


def _fraud_stats(repo, user, days):
    try:
        return repo.stats(user, days), None
    except RepositoryError as exc:
        log.error("fraud stats unavailable: %s", exc)
        return None, "Prediction records are temporarily unavailable."


def _resolution_hours(session):
    rows = session.execute(select(Case.created_at, Case.resolved_at).where(Case.resolved_at.is_not(None))).all()
    hours = [(r - c).total_seconds() / 3600 for c, r in rows if r and c]
    return {"resolved_cases": len(hours), "average_hours": round(sum(hours) / len(hours), 2) if hours else None,
            "max_hours": round(max(hours), 2) if hours else None}


DEFINITIONS = {
    "transactions_analysed": "Predictions the model has produced and saved (staff simulator and API), in the period.",
    "flagged": "Predictions at or above the model threshold. A flag is a signal for review, not a finding of fraud.",
    "confirmed_fraud": "Flagged predictions an analyst marked confirmed after review.",
    "false_positive": "Flagged predictions an analyst marked as not fraud after review.",
    "review_agreement": "confirmed / (confirmed + false positives) among REVIEWED flags only. Small samples are unreliable and this is not model precision on unseen data.",
    "open_cases": "Cases whose status is new, investigating or confirmed.",
    "average_resolution_hours": "Mean time from case creation to closure (resolved or false positive), closed cases only.",
    "inventory_anomalies": "Cases opened by the order-risk rules (plain rules, not machine learning).",
    "scam_reports": "Distinct reported web addresses; repeated reports of one address raise its count instead of adding rows.",
    "security_events": "Events this application recorded about itself. Not network or infrastructure monitoring.",
}


@router.get("/overview")
def overview(request: Request, days: Annotated[int, Query(ge=1, le=365)] = 30,
             user: User = Depends(require("reports.view")), session=Depends(get_session), repo=Depends(get_repo)):
    since = utcnow() - timedelta(days=days)
    stats, stats_error = _fraud_stats(repo, user, days)
    cases_by_status = _counts(session, Case.status)
    open_cases = sum(cases_by_status.get(s, 0) for s in ("new", "investigating", "confirmed"))
    workload = {(a or "unassigned"): n for a, n in session.execute(
        select(Case.assigned_to, func.count()).where(Case.status.in_(("new", "investigating", "confirmed")))
        .group_by(Case.assigned_to)).all()}
    low = session.scalar(select(func.count()).select_from(Inventory).where(
        Inventory.available_quantity > 0, Inventory.available_quantity <= Inventory.reorder_threshold))
    out_of_stock = session.scalar(select(func.count()).select_from(Inventory).where(Inventory.available_quantity <= 0))
    orders_by_status = _counts(session, Order.status, Order.created_at >= since)
    order_totals = dict(session.execute(select(Order.currency, func.sum(Order.total_cents)).where(
        Order.created_at >= since, Order.status != "cancelled").group_by(Order.currency)).all())
    return {
        "period_days": days, "definitions": DEFINITIONS,
        "fraud": None if stats is None else {
            "transactions_analysed": stats["total_transactions"], "flagged": stats["flagged"],
            "confirmed_fraud": stats["confirmed_fraud"], "false_positive": stats["false_positive"],
            "open_alerts": stats["open_alerts"], "risk_counts": stats["risk_counts"], "daily": stats["daily"]},
        "fraud_error": stats_error,
        "cases": {"by_status": cases_by_status, "open": open_cases,
                  "open_by_severity": _counts(session, Case.severity, Case.status.in_(("new", "investigating", "confirmed"))),
                  "by_source": _counts(session, Case.source_type), "resolution": _resolution_hours(session),
                  "workload_by_assignee": workload,
                  "recent": [{"id": c.id, "case_reference": c.case_reference, "severity": c.severity, "status": c.status,
                              "source_type": c.source_type, "summary": c.summary, "created_at": c.created_at}
                             for c in session.scalars(select(Case).order_by(Case.created_at.desc(), Case.id.desc()).limit(6))]},
        "scamwatch": {"reports": session.scalar(select(func.count()).select_from(ScamReport)),
                      "by_review_status": _counts(session, ScamReport.review_status),
                      "by_verdict": _counts(session, ScamReport.verdict)},
        "security": ({"events_in_period": session.scalar(select(func.count()).select_from(SecurityEvent).where(
                          SecurityEvent.created_at >= since)),
                      "by_severity": _counts(session, SecurityEvent.severity, SecurityEvent.created_at >= since)}
                     if user.has("security.view") else None),
        "inventory": {"low_stock_products": low, "out_of_stock_products": out_of_stock,
                      "anomaly_cases": session.scalar(select(func.count()).select_from(Case).where(
                          Case.source_type == "order_anomaly"))},
        "orders": {"by_status": orders_by_status, "revenue_by_currency_cents": order_totals,
                   "note": "Demonstration orders with simulated payment; no real money moved."},
        "audit": ({"events_in_period": session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.created_at >= since))} if user.has("audit.view") else None),
    }


@router.get("/fraud")
def fraud_report(request: Request, days: Annotated[int, Query(ge=1, le=365)] = 30,
                 baseline_flag_rate: Annotated[float | None, Query(ge=0, le=100)] = None,
                 assumed_loss_per_fraud: Annotated[float | None, Query(ge=0, le=10_000_000)] = None,
                 user: User = Depends(require("reports.fraud")), repo=Depends(get_repo)):
    stats, err = _fraud_stats(repo, user, days)
    predictor = request.app.state.predictor
    model = ({"available": True, "version": predictor.metadata["version"], "is_synthetic": predictor.metadata["is_synthetic"],
              "threshold": predictor.threshold, "offline_test_metrics": predictor.metadata["metrics"],
              "note": "Offline metrics from the model's own held-out test split. If is_synthetic is true they say nothing about real fraud."}
             if predictor.available else {"available": False, "message": predictor.error})
    reviewed = None if stats is None else stats["confirmed_fraud"] + stats["false_positive"]
    out = {"period_days": days, "model": model, "error": err, "definitions": {k: DEFINITIONS[k] for k in (
        "transactions_analysed", "flagged", "confirmed_fraud", "false_positive", "review_agreement")}}
    if stats is not None:
        out["observed"] = {"transactions_analysed": stats["total_transactions"], "flagged": stats["flagged"],
                           "flag_rate": stats["flag_rate"], "risk_counts": stats["risk_counts"],
                           "confirmed_fraud": stats["confirmed_fraud"], "false_positive": stats["false_positive"],
                           "reviewed": reviewed, "open_alerts": stats["open_alerts"], "daily": stats["daily"],
                           "review_agreement": (round(stats["confirmed_fraud"] / reviewed, 4) if reviewed else None)}
        if baseline_flag_rate is not None or assumed_loss_per_fraud is not None:
            out["baseline_comparison"] = {
                "label": "HYPOTHETICAL: the numbers below are assumptions supplied by the analyst, not measured data.",
                "assumptions": {"baseline_flag_rate_percent": baseline_flag_rate,
                                "assumed_loss_per_fraud": assumed_loss_per_fraud},
                "observed_flag_rate_percent": None if stats["flag_rate"] is None else round(stats["flag_rate"] * 100, 2),
                "difference_in_flag_rate_points": (None if baseline_flag_rate is None or stats["flag_rate"] is None
                                                   else round(stats["flag_rate"] * 100 - baseline_flag_rate, 2)),
                "exposure_identified_in_prototype": (None if assumed_loss_per_fraud is None
                                                     else round(stats["confirmed_fraud"] * assumed_loss_per_fraud, 2)),
                "note": ("'Exposure identified' multiplies analyst-confirmed cases by the assumed loss. It is not money "
                         "saved: nothing was prevented or recovered, and the data is demonstration data.")}
    return out


@router.get("/security")
def security_report(days: Annotated[int, Query(ge=1, le=90)] = 7, user: User = Depends(require("reports.security")),
                    session=Depends(get_session)):
    since = utcnow() - timedelta(days=days)
    day = func.date(SecurityEvent.created_at)
    daily = [{"date": str(d), "events": n} for d, n in session.execute(
        select(day, func.count()).where(SecurityEvent.created_at >= since).group_by(day).order_by(day)).all()]
    by_type = dict(session.execute(select(SecurityEvent.event_type, func.count()).where(
        SecurityEvent.created_at >= since).group_by(SecurityEvent.event_type)).all())
    return {"period_days": days, "definitions": {"security_events": DEFINITIONS["security_events"]},
            "by_severity": _counts(session, SecurityEvent.severity, SecurityEvent.created_at >= since),
            "by_category": _counts(session, SecurityEvent.category, SecurityEvent.created_at >= since),
            "by_event_type": by_type, "daily": daily,
            "authentication_failures": sum(n for t, n in by_type.items() if t.startswith("auth.")),
            "rate_limit_events": by_type.get("rate_limit.exceeded", 0),
            "provider_failures": by_type.get("provider.failure", 0),
            "privileged_changes": sum(n for t, n in by_type.items() if t.startswith("privileged.")),
            "open_security_cases": session.scalar(select(func.count()).select_from(Case).where(
                Case.source_type.in_(("security_alert", "scamwatch_report")),
                Case.status.in_(("new", "investigating", "confirmed"))))}
