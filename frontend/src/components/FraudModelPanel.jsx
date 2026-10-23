import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import { pct, when } from "../services/format";

const STATE_TEXT = {
  ready: "Ready", not_trained: "Not trained", artifact_missing: "Model file missing", schema_incompatible: "Incompatible with the current schema",
  failed_validation: "Failed validation",
};

/** Real status of the trained models, read from each saved artifact's metadata. Nothing here is a sample or hard-coded:
 *  an untrained model shows "Not trained" and no metrics. Metrics are from rows held out before training, not live results. */
export default function FraudModelPanel() {
  const [data, setData] = useState(null);
  const [counts, setCounts] = useState(null);
  const [queue, setQueue] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([Promise.resolve(api.fraudModelStatus?.()), Promise.resolve(api.mlSummary?.()).catch(() => null),
      Promise.resolve(api.labelQueue?.()).catch(() => null)])
      .then(([s, c, q]) => { if (live) { setData(s || null); setCounts(c || null); setQueue(q || null); } })
      .catch(e => live && setError(e.message));
    return () => { live = false; };
  }, []);

  if (error) return <div className="notice error" role="alert">Model status unavailable: {error}</div>;
  if (!data) return null;
  const predictions = counts?.prediction_status_counts || {};
  const outcomes = counts?.verified_outcome_counts || {};
  return <section className="panel" aria-label="Fraud models">
    <h2>Fraud and phishing models</h2>
    {data.store_scoring && <div className="notice info" aria-label="Store scoring">
      <p><strong>Store orders are assessed by: {data.store_scoring.method === "rules" ? "rules (store_risk_v1), not a trained model" : data.store_scoring.method}.</strong></p>
      <p>{data.store_scoring.message}</p>
      {data.store_scoring.labels && <p className="muted-text">Verified outcomes collected: {data.store_scoring.labels.verified_fraud} fraud of {data.store_scoring.labels.required.verified_fraud} needed,
        {" "}{data.store_scoring.labels.verified_legitimate} legitimate of {data.store_scoring.labels.required.verified_legitimate}, from {data.store_scoring.labels.distinct_customers} of {data.store_scoring.labels.required.distinct_customers} customers.</p>}
    </div>}
    <div className="model-grid">
      {data.models.map(m => <article key={m.model} className="model-card" aria-label={m.label}>
        <h3>{m.label}</h3>
        <p><span className={`pill ${m.ready ? "pill-ok" : "pill-warn"}`}>{STATE_TEXT[m.state] || m.state}</span>
          {m.is_fixture && <span className="pill pill-warn"> test fixture, not real data</span>}
          {m.experimental && <span className="pill pill-warn"> experimental: recorded only, never alerts</span>}</p>
        {m.ready ? <>
          <p className="muted-text">Version {m.version} · trained {when(m.trained_at)} · data: {m.dataset?.name} ({m.dataset?.licence})</p>
          {m.test_metrics && <dl className="metric-list">
            <div><dt>Precision</dt><dd>{pct(m.test_metrics.precision)}</dd></div>
            <div><dt>Recall</dt><dd>{pct(m.test_metrics.recall)}</dd></div>
            <div><dt>F1</dt><dd>{m.test_metrics.f1?.toFixed(3)}</dd></div>
            <div><dt>PR-AUC</dt><dd>{m.test_metrics.pr_auc?.toFixed(3)}</dd></div>
            <div><dt>Threshold</dt><dd>{m.threshold?.toFixed(3)}</dd></div>
            <div><dt>False alarms</dt><dd>{m.test_metrics.false_positives} of {m.test_metrics.support_legitimate}</dd></div>
          </dl>}
          <p className="muted-text">{m.metrics_note}</p>
        </> : <p className="muted-text">{m.detail}</p>}
      </article>)}
    </div>
    {queue && queue.items?.length > 0 && <div aria-label="Orders needing a verified outcome">
      <h3>Orders waiting for a verified outcome</h3>
      <p className="muted-text">{queue.flagged_waiting} flagged by rules, plus {queue.audit_sample_waiting} unflagged orders in this week's audit sample ({queue.audit_sample_rate}).
        Reviewing the unflagged sample keeps future labels from covering only what the rules already catch.</p>
      <ul>{queue.items.map(i => <li key={i.order_id}><Link to={`/orders?search=${encodeURIComponent(i.reference)}`}>{i.reference}</Link> — {i.why}, rule score {i.rules_score}</li>)}</ul>
    </div>}
    <p className="muted-text">Store events recorded: {Object.keys(predictions).length === 0 ? "none yet" : Object.entries(predictions).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(", ")}.
      {" "}Verified outcomes: {Object.keys(outcomes).length === 0 ? "none yet" : Object.entries(outcomes).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(", ")}.</p>
  </section>;
}
