import { useCallback, useEffect, useState } from "react";
import { CreditCard, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorState, PageHeader, Skeleton, TransactionTable } from "../components/ui";
import { api } from "../services/api";
import { METHOD_OPTIONS, getPrefs, setPrefs } from "../services/prefs";

export default function PaymentCard() {
  const [method, setMethod] = useState(() => getPrefs().defaultMethod);
  const [saved, setSaved] = useState(false);
  const [storageError, setStorageError] = useState("");
  const [activity, setActivity] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setActivity(null); setError("");
    try { setActivity(await api.transactions({ payment_method: method, page_size: 5 })); }
    catch (e) { setError(e.message); }
  }, [method]);
  useEffect(() => { load(); }, [load]);

  function save(e) {
    e.preventDefault(); setSaved(false); setStorageError("");
    if (setPrefs({ defaultMethod: method })) setSaved(true); else setStorageError("Your browser blocked saving this preference.");
  }

  return <div>
    <PageHeader title="Payment Card" subtitle="Demonstration card and payment-method preference. No real payment is processed."/>
    <div className="dashboard-grid">
      <section className="panel">
        <div className="panel-heading"><h2><CreditCard size={18}/> Demo card</h2></div>
        <div className="card-visual" role="img" aria-label="Demo payment card, number masked">
          <small>DEMO CARD — NOT A REAL CARD</small>
          <div className="card-number">•••• •••• •••• 0000</div>
          <div className="card-meta"><span>FraudGuard Demo</span><span>Status: demonstration only</span></div>
        </div>
        <p className="notice info">This application never asks for, stores or processes full card numbers, CVVs, PINs or passwords, and cannot authorise real payments.</p>
      </section>
      <section className="panel">
        <h2><ShieldCheck size={18}/> Default payment method</h2>
        <p className="muted-text">Pre-selects the method on the New Payment form. Saved in this browser only.</p>
        <form onSubmit={save}>
          <div className="field"><label htmlFor="pm"><span>Payment method</span></label>
            <select id="pm" value={method} onChange={e => { setMethod(e.target.value); setSaved(false); }}>{METHOD_OPTIONS.map(m => <option key={m}>{m}</option>)}</select></div>
          <button className="btn btn-primary">Save preference</button>
        </form>
        {saved && <div className="notice success" role="status">Preference saved.</div>}
        {storageError && <div className="notice error" role="alert">{storageError}</div>}
        <Link to="/payment" className="secondary-link">Go to New Payment</Link>
      </section>
    </div>
    <section className="panel" style={{ marginTop: 16 }}>
      <div className="panel-heading"><h2>Recent activity — {method}</h2>{activity && <span>{activity.total} transaction{activity.total === 1 ? "" : "s"} with this method</span>}</div>
      {error ? <ErrorState error={error} onRetry={load}/> : !activity ? <Skeleton count={3}/> : activity.items.length ?
        <TransactionTable items={activity.items}/> : <EmptyState>No {method} transactions yet.</EmptyState>}
    </section>
  </div>;
}
