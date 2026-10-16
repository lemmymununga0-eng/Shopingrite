import { useCallback, useEffect, useState } from "react";
import { Field } from "../components/forms";
import { EmptyState, ErrorState, PageHeader, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { moneyC, pct } from "../services/format";

const Metric = ({ label, value, note }) => <div className="metric"><dt>{label}</dt><dd>{value ?? "—"}{note && <small>{note}</small>}</dd></div>;
const kv = o => Object.entries(o || {}).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ") || "none";

export default function Reports() {
  const { role } = useAuth();
  const [days, setDays] = useState(30);
  const [d, setD] = useState(null);
  const [fraud, setFraud] = useState(null);
  const [error, setError] = useState("");
  const [base, setBase] = useState({ rate: "", loss: "" });
  const canFraud = role === "fraud_analyst" || role === "admin";

  const load = useCallback(async () => {
    try { setD(await api.overview(days)); setError(""); } catch (e) { setError(e.message); }
  }, [days]);
  useEffect(() => { load(); }, [load]);
  const loadFraud = useCallback(async () => {
    if (!canFraud) return;
    try { setFraud(await api.fraudReport({ days, baseline_flag_rate: base.rate || undefined, assumed_loss_per_fraud: base.loss || undefined })); } catch { setFraud(null); }
  }, [days, base, canFraud]);
  useEffect(() => { loadFraud(); }, [loadFraud]);

  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!d) return <Skeleton className="skeleton-chart" count={3}/>;
  const empty = !d.fraud?.transactions_analysed && d.cases.open === 0 && !d.scamwatch.reports;
  const def = d.definitions;
  return <div>
    <PageHeader title="Reports & Business Impact" subtitle="Built only from records stored in this system. Each metric says how it is calculated."
      actions={<><label className="sr-only" htmlFor="rp-days">Period</label><select id="rp-days" className="btn btn-secondary" value={days} onChange={e => setDays(Number(e.target.value))}>{[7, 30, 90, 365].map(v => <option key={v} value={v}>Last {v} days</option>)}</select></>}/>
    {empty && <EmptyState><p>No activity recorded yet in this period. Run a prediction, report a website or place a demo order to see figures here.</p></EmptyState>}
    <section className="panel" aria-label="Fraud model results"><h2>Fraud signals</h2>
      {d.fraud ? <dl className="metrics">
        <Metric label="Transactions analysed" value={d.fraud.transactions_analysed} note={def.transactions_analysed}/>
        <Metric label="Flagged" value={d.fraud.flagged} note={def.flagged}/>
        <Metric label="Confirmed fraud" value={d.fraud.confirmed_fraud} note={def.confirmed_fraud}/>
        <Metric label="False positives" value={d.fraud.false_positive} note={def.false_positive}/></dl> : <p className="notice error" role="alert">{d.fraud_error}</p>}</section>
    <section className="panel" aria-label="Investigations"><h2>Investigations</h2>
      <dl className="metrics"><Metric label="Open cases" value={d.cases.open} note={def.open_cases}/>
        <Metric label="Average resolution" value={d.cases.resolution.average_hours == null ? "No closed cases yet" : `${d.cases.resolution.average_hours} h`} note={def.average_resolution_hours}/>
        <Metric label="Cases by status" value={kv(d.cases.by_status)}/><Metric label="Open by severity" value={kv(d.cases.open_by_severity)}/>
        <Metric label="Cases by source" value={kv(d.cases.by_source)}/><Metric label="Analyst workload (open)" value={kv(d.cases.workload_by_assignee)}/></dl></section>
    <section className="panel" aria-label="ScamWatch and inventory"><h2>ScamWatch, inventory and orders</h2>
      <dl className="metrics"><Metric label="Scam reports" value={d.scamwatch.reports} note={def.scam_reports}/><Metric label="By verdict" value={kv(d.scamwatch.by_verdict)}/>
        <Metric label="Low-stock products" value={d.inventory.low_stock_products}/><Metric label="Out-of-stock products" value={d.inventory.out_of_stock_products}/>
        <Metric label="Inventory anomalies" value={d.inventory.anomaly_cases} note={def.inventory_anomalies}/>
        <Metric label="Orders by status" value={kv(d.orders.by_status)} note={d.orders.note}/>
        <Metric label="Demo order value" value={Object.entries(d.orders.revenue_by_currency_cents).map(([c, v]) => moneyC(v, c)).join(", ") || "none"} note="Simulated payments only"/></dl></section>
    {d.security && <section className="panel" aria-label="Security"><h2>Security events</h2>
      <dl className="metrics"><Metric label="Events in period" value={d.security.events_in_period} note={def.security_events}/><Metric label="By severity" value={kv(d.security.by_severity)}/></dl></section>}
    {canFraud && <section className="panel" aria-label="Baseline comparison"><h2>Hypothetical baseline comparison</h2>
      <p className="muted-text">Enter your own assumptions. Results are labelled HYPOTHETICAL and are not money saved.</p>
      <div className="toolbar"><Field label="Assumed baseline flag rate (%)">{a => <input {...a} type="number" min="0" max="100" step="0.1" value={base.rate} onChange={e => setBase({ ...base, rate: e.target.value })}/>}</Field>
        <Field label="Assumed loss per fraud case">{a => <input {...a} type="number" min="0" step="1" value={base.loss} onChange={e => setBase({ ...base, loss: e.target.value })}/>}</Field></div>
      {fraud?.model && <p className="muted-text">{fraud.model.available ? `Model ${fraud.model.version}${fraud.model.is_synthetic ? " (trained on SYNTHETIC data)" : ""}, threshold ${fraud.model.threshold}. ${fraud.model.note}` : fraud.model.message}</p>}
      {fraud?.observed && <p>Review agreement among reviewed flags: {fraud.observed.review_agreement == null ? "n/a (nothing reviewed yet)" : pct(fraud.observed.review_agreement)} <small className="muted-text">({fraud.definitions.review_agreement})</small></p>}
      {fraud?.baseline_comparison && <div className="notice info" role="note"><strong>{fraud.baseline_comparison.label}</strong>
        <p>Observed flag rate: {fraud.baseline_comparison.observed_flag_rate_percent ?? "n/a"}%. Difference from baseline: {fraud.baseline_comparison.difference_in_flag_rate_points ?? "n/a"} points. Exposure identified in prototype: {fraud.baseline_comparison.exposure_identified_in_prototype ?? "n/a"}.</p>
        <p>{fraud.baseline_comparison.note}</p></div>}</section>}
  </div>;
}
