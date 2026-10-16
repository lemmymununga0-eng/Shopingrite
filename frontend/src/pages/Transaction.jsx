import { useEffect, useState } from "react";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { ErrorNotice, ModelBanner, PageHeader, RiskBadge } from "../components/ui";
import { getPrefs } from "../services/prefs";
import { api } from "../services/api";
import { money, pct } from "../services/format";

export const METHODS = ["Card", "Bank Transfer", "Mobile Money"];
export const BRANCHES = ["Online", "Johannesburg CBD", "Cape Town V&A", "Durban North", "Pretoria Central"];

const newRef = () => `TX-${Date.now().toString(36).toUpperCase()}`;
const initial = () => ({ transaction_reference: newRef(), amount: "", payment_method: getPrefs().defaultMethod, hour: String(new Date().getHours()),
  failed_attempts: "0", new_device: "no", international: "no", customer_avg_spend: "", branch: "Online" });

/** Returns {errors, payload}. Mirrors the server's rules; the server remains the authority. */
export function validate(f) {
  const errors = {};
  if (!/^[A-Za-z0-9._-]{3,40}$/.test(f.transaction_reference)) errors.transaction_reference = "3–40 letters, numbers, dot, dash or underscore";
  const amount = Number(f.amount);
  if (f.amount === "" || !Number.isFinite(amount) || amount < 0.01 || amount > 1000000) errors.amount = "Enter an amount between 0.01 and 1,000,000";
  const avg = Number(f.customer_avg_spend);
  if (f.customer_avg_spend === "" || !Number.isFinite(avg) || avg < 0 || avg > 1000000) errors.customer_avg_spend = "Enter a value between 0 and 1,000,000";
  const hour = Number(f.hour);
  if (f.hour === "" || !Number.isInteger(hour) || hour < 0 || hour > 23) errors.hour = "Whole number from 0 to 23";
  const failed = Number(f.failed_attempts);
  if (!Number.isInteger(failed) || failed < 0 || failed > 10) errors.failed_attempts = "Whole number from 0 to 10";
  if (!METHODS.includes(f.payment_method)) errors.payment_method = "Choose a payment method";
  if (!BRANCHES.includes(f.branch)) errors.branch = "Choose a branch";
  const payload = { transaction_reference: f.transaction_reference, amount, payment_method: f.payment_method, hour,
    failed_attempts: failed, new_device: f.new_device === "yes", international: f.international === "yes",
    customer_avg_spend: avg, branch: f.branch };
  return { errors, payload };
}

export default function Transaction() {
  const [info, setInfo] = useState(null);
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.modelInfo().then(setInfo).catch(e => setError(e.message)); }, []);
  const update = e => setForm({ ...form, [e.target.name]: e.target.value });

  async function submit(e) {
    e.preventDefault(); setError(""); setResult(null);
    const { errors: errs, payload } = validate(form);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try { setResult(await api.predict(payload)); setForm(f => ({ ...f, transaction_reference: newRef() })); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const field = (name, label, input) => <div className="field"><label htmlFor={`f-${name}`}><span>{label}</span></label>{input}{errors[name] && <small className="field-error" role="alert">{errors[name]}</small>}</div>;
  const ctl = (name, props) => ({ id: `f-${name}`, name, value: form[name], onChange: update, "aria-invalid": errors[name] ? true : undefined, ...props });
  const t = result?.transaction;
  function reset() { setForm(initial()); setErrors({}); setError(""); setResult(null); }

  return <div>
    <PageHeader title="New Payment" subtitle="Enter the transaction details. The model estimates fraud risk; no real payment is processed."/>
    <ModelBanner info={info}/>
    <ErrorNotice error={error}/>
    <form onSubmit={submit} noValidate>
      <section className="panel"><div className="panel-heading"><h2>Transaction details</h2></div><div className="form-grid">
        {field("transaction_reference", "Transaction Reference", <input {...ctl("transaction_reference")}/>)}
        {field("amount", "Amount (ZAR)", <input {...ctl("amount", { type: "number", step: "0.01", min: "0.01", placeholder: "Enter amount" })}/>)}
        {field("payment_method", "Payment Method", <select {...ctl("payment_method")}>{METHODS.map(m => <option key={m}>{m}</option>)}</select>)}
        {field("branch", "Merchant / Branch", <select {...ctl("branch")}>{BRANCHES.map(b => <option key={b}>{b}</option>)}</select>)}
      </div></section>
      <section className="panel" style={{ marginTop: 16 }}><div className="panel-heading"><h2>Additional transaction information</h2></div><div className="form-grid">
        {field("hour", "Transaction Hour (0–23)", <input {...ctl("hour", { type: "number", min: "0", max: "23" })}/>)}
        {field("failed_attempts", "Failed Attempts", <input {...ctl("failed_attempts", { type: "number", min: "0", max: "10" })}/>)}
        {field("customer_avg_spend", "Customer Average Spend (ZAR)", <input {...ctl("customer_avg_spend", { type: "number", step: "0.01", min: "0", placeholder: "Typical spend per transaction" })}/>)}
        {field("new_device", "New Device?", <select {...ctl("new_device")}><option value="no">No</option><option value="yes">Yes</option></select>)}
        {field("international", "International Transaction?", <select {...ctl("international")}><option value="no">No</option><option value="yes">Yes</option></select>)}
      </div>
      <p className="muted-text">Do not enter card numbers, CVVs, PINs or passwords. This form never asks for them.</p>
      <div className="page-actions">
        <button className="btn btn-primary" disabled={busy || (info && !info.trained)}>{busy ? "Analyzing…" : "Submit for Analysis"}</button>
        <button type="button" className="btn btn-secondary" onClick={reset} disabled={busy}>Reset</button></div></section>
    </form>
    {t && <section className="panel result-panel" aria-live="polite">
      <h2>{t.is_flagged ? <ShieldAlert/> : <ShieldCheck/>} {t.prediction}</h2>
      <p>Reference: <strong>{t.transaction_reference}</strong> · Amount: {money(t.amount)}</p>
      <p>Risk level: <RiskBadge risk={t.risk}/></p>
      <p>Model fraud probability: <strong>{pct(t.probability)}</strong></p>
      <p>Model version: {t.model_version}</p>
      <p>Saved: {result.saved ? "Yes" : "No"}{t.is_flagged && " · An alert was created for review."} <Link className="text-link" to={`/transactions/${t.id}`}>View details</Link></p>
      {t.contributing_factors.length > 0 && <><strong>Observations on this transaction</strong><ul>{t.contributing_factors.map(c => <li key={c}>{c}</li>)}</ul></>}
      <p className="muted-text">{result.explanation_note} A risk prediction is an estimate, not proof of fraud.</p>
    </section>}
  </div>;
}
