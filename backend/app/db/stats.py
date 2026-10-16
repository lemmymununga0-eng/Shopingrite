"""Dashboard statistics, computed from real rows by one pure function (used by every repository)."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone

FIELDS = "amount,is_flagged,review_status,risk,probability,created_at"


def since_iso(days: int | None) -> str | None:
    """Start of the period (UTC midnight, `days` days including today), or None for all time."""
    if not days:
        return None
    start = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    return start.isoformat()


def _day(created_at) -> str:
    return str(created_at)[:10]


def compute_stats(rows: list[dict], days: int | None = None) -> dict:
    total = len(rows)
    flagged = sum(1 for r in rows if r["is_flagged"])
    status = Counter(r["review_status"] for r in rows if r["is_flagged"])
    risk = Counter(r["risk"] for r in rows)
    per_day: dict[str, list[int]] = {}
    for r in rows:
        d = per_day.setdefault(_day(r["created_at"]), [0, 0])
        d[0] += 1
        d[1] += 1 if r["is_flagged"] else 0
    if days:   # real zero-activity days are included so the chart's time axis is honest
        today = datetime.now(timezone.utc).date()
        for i in range(days):
            per_day.setdefault((today - timedelta(days=i)).isoformat(), [0, 0])
    daily = [{"date": d, "total": v[0], "flagged": v[1]} for d, v in sorted(per_day.items())]
    confirmed, false_pos = status.get("confirmed_fraud", 0), status.get("false_positive", 0)
    return {
        "total_transactions": total, "flagged": flagged, "lower_risk": total - flagged,
        "total_amount": round(sum(float(r["amount"]) for r in rows), 2),
        "open_alerts": status.get("new", 0), "confirmed_fraud": confirmed, "false_positive": false_pos,
        "reviewed": confirmed + false_pos,
        "avg_probability": round(sum(float(r["probability"]) for r in rows) / total, 4) if total else None,
        "flag_rate": round(flagged / total, 4) if total else None,
        "risk_counts": {k: risk.get(k, 0) for k in ("Low", "Medium", "High")},
        "daily": daily, "period_days": days,
    }
