import { useState } from "react";
import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import { Field } from "./forms";
import { api } from "../services/api";

export const VERDICT_TEXT = {
  malicious: ["high", "Known threat reported by a provider"], suspicious: ["medium", "Suspicious: warning signs found"],
  no_known_threat: ["low", "No known threat detected (this is not a guarantee of safety)"],
  inconclusive: ["medium", "Inconclusive: we could not reach a conclusion"],
};

export function VerdictBadge({ verdict }) {
  const [cls, text] = VERDICT_TEXT[verdict] || ["medium", verdict];
  const Icon = verdict === "malicious" || verdict === "suspicious" ? ShieldAlert : verdict === "no_known_threat" ? ShieldCheck : ShieldQuestion;
  return <span className={`risk-badge ${cls}`}><Icon size={13} aria-hidden="true"/> {text}</span>;
}

/** URL check and report form. The address is analysed as text on the server; it is never opened or fetched. */
export default function ScamChecker({ onReported }) {
  const [url, setUrl] = useState("");
  const [comment, setComment] = useState("");
  const [result, setResult] = useState(null);
  const [saved, setSaved] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function check(e) {
    e.preventDefault(); setError(""); setResult(null); setSaved(null);
    if (!url.trim()) { setError("Enter a web address to check."); return; }
    setBusy(true);
    try { setResult(await api.scamCheck(url.trim())); } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  async function report() {
    setError(""); setBusy(true);
    try { const r = await api.scamReport(url.trim(), comment); setSaved(r); onReported?.(r); } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return <div className="scam-checker">
    <form onSubmit={check} noValidate aria-label="Check a website">
      <Field label="Website address" hint="We analyse the text of the address only. We never open the website.">{a =>
        <input {...a} type="text" inputMode="url" autoComplete="off" placeholder="example.com/offer" maxLength={2048} value={url} onChange={e => setUrl(e.target.value)}/>}</Field>
      <button className="primary-button inline-btn" disabled={busy}>{busy && !result ? "Checking…" : "Check website"}</button>
    </form>
    {error && <div className="notice error" role="alert">{error}</div>}
    {result && <section className="scam-result" aria-label="Check result" aria-live="polite">
      <h3><VerdictBadge verdict={result.verdict}/></h3>
      <p className="muted-text">{result.normalized_url}</p>
      {result.simulated && <p className="notice info">Includes SIMULATED provider results (demonstration only).</p>}
      <ul className="provider-list">{result.providers.map(p => <li key={p.provider}>
        <strong>{p.provider}</strong> <span className="muted-text">({p.source}{p.simulated ? ", simulated" : ""})</span> — {p.status === "ok" ? p.detail : <em>{p.status}: {p.detail}</em>}
        {p.signals?.length > 0 && <ul>{p.signals.map(s => <li key={s}>{s}</li>)}</ul>}</li>)}</ul>
      {result.provider_errors.length > 0 && <p className="notice info">Some providers failed ({result.provider_errors.join(", ")}), so this result may be incomplete.</p>}
      <p className="disclaimer">{result.disclaimer}</p>
      {!saved && <div className="report-box"><Field label="Add a note (optional)">{a => <input {...a} maxLength={1000} value={comment} onChange={e => setComment(e.target.value)} placeholder="How did you find this link?"/>}</Field>
        <button type="button" className="secondary-button" onClick={report} disabled={busy}>Report this website</button></div>}
      {saved && <div className="notice success" role="status">{saved.message}</div>}
    </section>}
  </div>;
}
