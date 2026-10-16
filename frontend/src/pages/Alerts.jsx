import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BellRing, CheckCircle2, ClipboardCheck, RefreshCw, Search, ShieldAlert, ShieldX } from "lucide-react";
import StatCard from "../components/StatCard";
import { ConfirmDialog, EmptyState, ErrorNotice, ErrorState, Modal, PageHeader, Pagination, ReviewBadge, RiskBadge, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { money, pct, when } from "../services/format";
import { getPrefs } from "../services/prefs";

const STATUS_OPTIONS = [["new", "New"], ["confirmed_fraud", "Confirmed fraud"], ["false_positive", "False positive"]];
const BLANK = { search: "", risk: "", review_status: "", date_from: "", date_to: "" };

function AlertModal({ alert, canReview, onClose, onSaved }) {
  const [status, setStatus] = useState(alert.review_status || "new");
  const [notes, setNotes] = useState(alert.review_notes || "");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  async function save() {
    setConfirm(false); setBusy(true); setError(""); setSaved(false);
    try { const updated = await api.reviewAlert(alert.id, status, notes); setSaved(true); onSaved(updated); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  const label = STATUS_OPTIONS.find(o => o[0] === status)[1];

  return <Modal title={`Alert #${alert.transaction_reference}`} onClose={onClose} wide>
    <p className="muted-text">{when(alert.created_at)} · {alert.branch} · {alert.payment_method}</p>
    <dl className="detail-grid">
      <dt>Amount</dt><dd>{money(alert.amount)} (customer average {money(alert.customer_avg_spend)})</dd>
      <dt>Model prediction</dt><dd>{alert.prediction}</dd>
      <dt>Fraud probability</dt><dd>{pct(alert.probability)} <RiskBadge risk={alert.risk}/></dd>
      <dt>Model version</dt><dd>{alert.model_version}</dd>
    </dl>
    {alert.contributing_factors.length > 0 && <ul className="factor-list">{alert.contributing_factors.map(c => <li key={c}>{c}</li>)}</ul>}
    <p className="muted-text">A prediction is an estimate. It only becomes “confirmed fraud” when an authorised reviewer says so.</p>
    {alert.reviewed_at && <p className="muted-text">Last reviewed {when(alert.reviewed_at)}.</p>}
    {canReview ? <div className="review-form">
      <div className="field"><label htmlFor="rv-status"><span>Review status</span></label>
        <select id="rv-status" value={status} onChange={e => setStatus(e.target.value)}>{STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
      <div className="field"><label htmlFor="rv-notes"><span>Reviewer notes</span></label>
        <textarea id="rv-notes" value={notes} maxLength={1000} onChange={e => setNotes(e.target.value)}/></div>
      {saved && <div className="notice success" role="status">Review saved.</div>}
      <ErrorNotice error={error}/>
      <div className="dialog-actions">
        <Link className="btn btn-ghost" to={`/transactions/${alert.id}`}>Full details</Link>
        <button type="button" className="btn btn-secondary" onClick={onClose}>Close</button>
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => setConfirm(true)}>{busy ? "Saving…" : "Save review"}</button>
      </div></div> :
      <><p className="notice info">Only analysts and admins can review alerts.</p>
        <div className="dialog-actions"><Link className="btn btn-ghost" to={`/transactions/${alert.id}`}>Full details</Link>
          <button type="button" className="btn btn-secondary" onClick={onClose}>Close</button></div></>}
    {confirm && <ConfirmDialog title="Save review?" message={`Mark ${alert.transaction_reference} as “${label}”.`} confirmLabel="Save review"
      onConfirm={save} onCancel={() => setConfirm(false)}/>}
  </Modal>;
}

export default function Alerts() {
  const { role } = useAuth();
  const canReview = role === "analyst" || role === "admin";   // UI hint only; the API enforces it
  const [draft, setDraft] = useState(BLANK);
  const [applied, setApplied] = useState(BLANK);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(() => getPrefs().pageSize);
  const [data, setData] = useState({ items: [], total: 0 });
  const [stats, setStats] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, s] = await Promise.all([api.alerts({ ...applied, page, page_size: pageSize }), api.stats()]);
      setData(d); setStats(s); setError("");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [applied, page, pageSize]);
  useEffect(() => { load(); }, [load]);

  const set = k => e => setDraft({ ...draft, [k]: e.target.value });
  const badRange = draft.date_from && draft.date_to && draft.date_from > draft.date_to;
  function apply(e) { e.preventDefault(); if (badRange) return; setPage(1); setApplied({ ...draft, search: draft.search.trim() }); }
  function clear() { setDraft(BLANK); setApplied(BLANK); setPage(1); }
  const filtered = Object.values(applied).some(Boolean);

  function saved(updated) {
    setData(d => ({ ...d, items: d.items.map(x => x.id === updated.id ? updated : x) }));
    setSelected(updated);
    api.stats().then(setStats).catch(() => {});
  }

  return <div>
    <PageHeader title="Fraud Alerts" subtitle="Review transactions flagged for elevated fraud risk."
      actions={<button type="button" className="btn btn-secondary" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""}/> Refresh</button>}/>
    {stats && <div className="cards-4">
      <StatCard title="New Alerts" value={stats.open_alerts} note="Awaiting review" icon={ShieldAlert} color="red"/>
      <StatCard title="Confirmed Fraud" value={stats.confirmed_fraud} note="Confirmed by a reviewer" icon={ShieldX} color="purple"/>
      <StatCard title="False Positives" value={stats.false_positive} note="Cleared by a reviewer" icon={CheckCircle2} color="green"/>
      <StatCard title="Total Reviewed" value={stats.reviewed} note={`Of ${stats.flagged} flagged`} icon={ClipboardCheck} color="blue"/>
    </div>}
    <section className="panel">
      <div className="panel-heading"><h2><BellRing size={18}/> Alerts</h2></div>
      <form className="filters" onSubmit={apply} role="search">
        <div className="field"><label htmlFor="a-search"><span>Search reference</span></label><input id="a-search" value={draft.search} onChange={set("search")} maxLength={40} placeholder="e.g. TX-1001"/></div>
        <div className="field"><label htmlFor="a-risk"><span>Risk level</span></label><select id="a-risk" value={draft.risk} onChange={set("risk")}><option value="">All</option><option>Low</option><option>Medium</option><option>High</option></select></div>
        <div className="field"><label htmlFor="a-status"><span>Review status</span></label><select id="a-status" value={draft.review_status} onChange={set("review_status")}>
          <option value="">All</option>{STATUS_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
        <div className="field"><label htmlFor="a-from"><span>From date</span></label><input id="a-from" type="date" value={draft.date_from} onChange={set("date_from")}/></div>
        <div className="field"><label htmlFor="a-to"><span>To date</span></label><input id="a-to" type="date" value={draft.date_to} onChange={set("date_to")}/></div>
        <button className="btn btn-primary"><Search size={15}/> Apply</button>
        {(filtered || Object.values(draft).some(Boolean)) && <button type="button" className="btn btn-ghost" onClick={clear}>Clear filters</button>}
      </form>
      {badRange && <div className="notice error" role="alert">“From date” must not be after “To date”.</div>}
      {error ? <ErrorState error={error} onRetry={load}/> : loading && !data.items.length ? <Skeleton count={5}/> : data.items.length ?
        <div className="table-wrap table-cards"><table><thead><tr><th scope="col">Reference</th><th scope="col">Date</th><th scope="col">Amount</th>
          <th scope="col">Risk</th><th scope="col">Probability</th><th scope="col">Review status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead><tbody>
          {data.items.map(a => <tr key={a.id}><td data-label="Reference">{a.transaction_reference}</td><td data-label="Date">{when(a.created_at)}</td>
            <td data-label="Amount">{money(a.amount)}</td><td data-label="Risk"><RiskBadge risk={a.risk}/></td><td data-label="Probability">{pct(a.probability)}</td>
            <td data-label="Review status"><ReviewBadge status={a.review_status}/></td>
            <td><button type="button" className="btn btn-secondary" onClick={() => setSelected(a)} aria-label={`${canReview ? "Review" : "View"} alert ${a.transaction_reference}`}>{canReview ? "Review" : "View"}</button></td></tr>)}
        </tbody></table></div> :
        <EmptyState icon={ShieldAlert}>{filtered ? "No alerts match these filters." : "No fraud alerts yet. Alerts appear when the model flags a transaction."}</EmptyState>}
      {data.total > 0 && !error && <Pagination page={page} pageSize={pageSize} total={data.total} onChange={setPage}/>}
    </section>
    {selected && <AlertModal key={selected.id} alert={selected} canReview={canReview} onClose={() => setSelected(null)} onSaved={saved}/>}
  </div>;
}
