import { useEffect, useState } from "react";
import { FlaskConical, ShieldAlert, ShieldCheck } from "lucide-react";
import { ErrorNotice, Loading, PageHeader, RiskBadge } from "../components/ui";
import { api } from "../services/api";
import { pct } from "../services/format";

export const PCA_FEATURES = ["Time", ...Array.from({ length: 28 }, (_, i) => `V${i + 1}`), "Amount"];

/** Parses 30 comma/space/tab separated numbers (one Kaggle row, without the Class column). */
export function parseRow(text) {
  const parts = text.trim().split(/[\s,;]+/).filter(Boolean);
  if (parts.length === 31) parts.pop();                      // tolerate a trailing Class value
  if (parts.length !== PCA_FEATURES.length) return { error: `Expected 30 values (Time, V1–V28, Amount), found ${parts.length}.` };
  const nums = parts.map(Number);
  if (nums.some(n => !Number.isFinite(n))) return { error: "Every value must be a finite number." };
  return { values: Object.fromEntries(PCA_FEATURES.map((f, i) => [f, nums[i]])) };
}

export default function ModelDemo() {
  const [info, setInfo] = useState(null);
  const [values, setValues] = useState(() => Object.fromEntries(PCA_FEATURES.map(f => [f, "0"])));
  const [paste, setPaste] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.pcaInfo().then(setInfo).catch(e => setError(e.message)); }, []);

  function applyPaste() {
    const r = parseRow(paste);
    if (r.error) return setError(r.error);
    setError(""); setValues(Object.fromEntries(Object.entries(r.values).map(([k, v]) => [k, String(v)])));
  }

  async function submit(e) {
    e.preventDefault(); setError(""); setResult(null);
    const features = {};
    for (const f of PCA_FEATURES) {
      const raw = String(values[f]).trim(), n = Number(raw);
      if (raw === "" || !Number.isFinite(n)) return setError(`${f} must be a valid number`);
      features[f] = n;
    }
    setBusy(true);
    try { setResult(await api.pcaPredict(features)); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const m = info?.metrics;
  return <div>
    <PageHeader title="PCA Model Demo" subtitle="Separate demonstration of the Kaggle credit-card model. Not connected to the payment form."/>
    <div className="notice info">This model needs the dataset's anonymised PCA features (V1–V28). They cannot be calculated from payment details, so this page takes a row from the dataset itself. Results are not saved to history.</div>
    <ErrorNotice error={error}/>
    {!info && !error ? <Loading/> : info && !info.trained ?
      <div className="notice info" role="status"><FlaskConical size={16}/> PCA demo model not available. {info.message}</div> :
      info && <>
        <div className="mode-banner mode-good"><ShieldCheck size={18}/> Real model loaded · {info.version} · trained on {info.n_rows.toLocaleString()} rows from {info.data_source}</div>
        {m && <p className="muted-text">Held-out test: precision {m.precision.toFixed(3)}, recall {m.recall.toFixed(3)}, F1 {m.f1.toFixed(3)}, PR-AUC {m.pr_auc?.toFixed(3) ?? "n/a"}, fraud rows in test {m.support_fraud}.</p>}
        <section className="panel">
          <label className="field"><span>Paste one dataset row (30 comma-separated values)</span>
            <textarea value={paste} onChange={e => setPaste(e.target.value)} rows={3} aria-label="Paste dataset row"/></label>
          <button type="button" className="secondary-button" onClick={applyPaste}>Fill fields from pasted row</button>
        </section>
        <form className="panel" onSubmit={submit}>
          <div className="feature-grid">{PCA_FEATURES.map(f => <label className="field" key={f}><span>{f}</span>
            <input type="number" step="any" value={values[f]} onChange={e => setValues({ ...values, [f]: e.target.value })}/></label>)}</div>
          <button className="primary-button form-submit" disabled={busy}>{busy ? "Analyzing…" : "Analyze with PCA model"}</button>
        </form>
      </>}
    {result && <section className="panel result-panel" aria-live="polite">
      <h2>{result.prediction === 1 ? <ShieldAlert/> : <ShieldCheck/>} {result.prediction === 1 ? "Predicted fraud" : "Predicted legitimate"}</h2>
      <p>Risk level: <RiskBadge risk={result.risk_level}/></p>
      <p>Model fraud probability: <strong>{pct(result.fraud_probability)}</strong> (threshold {result.threshold})</p>
      <p>Model version: {result.model_version}</p>
      <p className="muted-text">{result.note}</p>
    </section>}
  </div>;
}
