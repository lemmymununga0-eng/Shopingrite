from datetime import datetime, timedelta, timezone

from app.db.stats import compute_stats

from .conftest import RISKY, auth, valid_payload


def row(day_offset=0, flagged=False, status=None, risk="Low", prob=0.1, amount=10):
    d = datetime.now(timezone.utc) - timedelta(days=day_offset)
    return {"amount": amount, "is_flagged": flagged, "review_status": status, "risk": risk, "probability": prob, "created_at": d.isoformat()}


def test_compute_stats_empty_has_no_invented_numbers():
    s = compute_stats([], 7)
    assert s["total_transactions"] == 0 and s["avg_probability"] is None and s["flag_rate"] is None
    assert len(s["daily"]) == 7 and all(p["total"] == 0 for p in s["daily"])


def test_compute_stats_counts():
    rows = [row(0, True, "new", "High", 0.9), row(0, True, "confirmed_fraud", "High", 0.8), row(1, True, "false_positive", "Medium", 0.4),
            row(1), row(2)]
    s = compute_stats(rows, 3)
    assert (s["total_transactions"], s["flagged"], s["open_alerts"], s["confirmed_fraud"], s["false_positive"], s["reviewed"]) == (5, 3, 1, 1, 1, 2)
    assert s["risk_counts"] == {"Low": 2, "Medium": 1, "High": 2} and s["flag_rate"] == 0.6
    assert sum(p["total"] for p in s["daily"]) == 5 and sum(p["flagged"] for p in s["daily"]) == 3
    assert [p["date"] for p in s["daily"]] == sorted(p["date"] for p in s["daily"])


def test_stats_endpoint_shape_and_period(client):
    client.post("/predict", json=valid_payload(), headers=auth())
    client.post("/predict", json=valid_payload(transaction_reference="TX-2", **RISKY), headers=auth())
    s = client.get("/transactions/stats?days=7", headers=auth()).json()
    assert s["total_transactions"] == 2 and s["period_days"] == 7 and len(s["daily"]) == 7
    assert s["open_alerts"] == s["flagged"] and sum(s["risk_counts"].values()) == 2
    assert client.get("/transactions/stats?days=0", headers=auth()).status_code == 422
    assert client.get("/transactions/stats?days=9999", headers=auth()).status_code == 422


def test_stats_reflect_reviews(client):
    t = client.post("/predict", json=valid_payload(**RISKY), headers=auth("alice")).json()["transaction"]
    client.patch(f"/alerts/{t['id']}", json={"status": "confirmed_fraud"}, headers=auth("ann", "analyst"))
    s = client.get("/transactions/stats", headers=auth("alice")).json()
    assert s["confirmed_fraud"] == 1 and s["open_alerts"] == 0 and s["reviewed"] == 1


def test_date_range_filter(client):
    client.post("/predict", json=valid_payload(), headers=auth())
    today = datetime.now(timezone.utc).date().isoformat()
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    assert client.get(f"/transactions?date_from={today}&date_to={today}", headers=auth()).json()["total"] == 1
    assert client.get(f"/transactions?date_from={tomorrow}", headers=auth()).json()["total"] == 0
    assert client.get(f"/transactions?date_to={yesterday}", headers=auth()).json()["total"] == 0
    assert client.get("/transactions?date_from=notadate", headers=auth()).status_code == 422
    assert client.get(f"/transactions?date_from={tomorrow}&date_to={yesterday}", headers=auth()).status_code == 422


def test_payment_method_filter(client):
    client.post("/predict", json=valid_payload(), headers=auth())
    client.post("/predict", json=valid_payload(transaction_reference="TX-M", payment_method="Mobile Money"), headers=auth())
    assert client.get("/transactions?payment_method=Mobile%20Money", headers=auth()).json()["total"] == 1
    assert client.get("/transactions?payment_method=Cash", headers=auth()).status_code == 422


def test_sorting(client):
    for i, amt in enumerate((50, 500, 5)):
        client.post("/predict", json=valid_payload(transaction_reference=f"S-{i}", amount=amt), headers=auth())
    asc = [t["amount"] for t in client.get("/transactions?sort_by=amount&sort_dir=asc", headers=auth()).json()["items"]]
    desc = [t["amount"] for t in client.get("/transactions?sort_by=amount&sort_dir=desc", headers=auth()).json()["items"]]
    assert asc == [5, 50, 500] and desc == [500, 50, 5]
    assert client.get("/transactions?sort_by=password", headers=auth()).status_code == 422
    assert client.get("/transactions?sort_by=amount;DROP", headers=auth()).status_code == 422
    assert client.get("/transactions?sort_dir=sideways", headers=auth()).status_code == 422


def test_alert_filters_by_risk_and_date(client):
    client.post("/predict", json=valid_payload(**RISKY), headers=auth("alice"))
    today = datetime.now(timezone.utc).date().isoformat()
    assert client.get(f"/alerts?date_from={today}", headers=auth("alice")).json()["total"] == 1
    assert client.get("/alerts?risk=Low", headers=auth("alice")).json()["total"] == 0
