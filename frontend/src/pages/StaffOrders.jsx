import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Field } from "../components/forms";
import { ConfirmDialog, EmptyState, ErrorNotice, ErrorState, Modal, PageHeader, Pagination, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { moneyC, when } from "../services/format";
import { ORDER_STATUS, PAYMENT_STATUS } from "../store/Orders";

const DECISION = { allow: ["low", "Low"], review: ["medium", "Review"], high: ["high", "High"] };
// What an administrator may do next (mirrors the server's transition table; the server has the final say).
const NEXT = { awaiting_payment: ["cancelled"], payment_failed: ["cancelled"], confirmed: ["picking", "cancelled"], picking: ["ready", "cancelled"],
  ready: ["out_for_delivery", "completed", "cancelled"], out_for_delivery: ["completed"] };
const ACTION_LABEL = { picking: "Start picking", ready: "Mark ready", out_for_delivery: "Out for delivery", completed: "Mark completed", cancelled: "Cancel order" };

export const RiskPill = ({ risk }) => risk
  ? <span className={`risk-badge ${DECISION[risk.decision][0]}`} title={`Rule-based score ${risk.score}/100 (store_risk_v1)`}>{DECISION[risk.decision][1]} · {risk.score}</span>
  : <span className="muted-text">Not scored</span>;

function OutcomeForm({ order, outcomes, onSaved }) {
  const { role } = useAuth();
  const [outcome, setOutcome] = useState("legitimate");
  const [verified, setVerified] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const canReview = role === "admin" || role === "fraud_analyst";
  async function save(e) {
    e.preventDefault(); setBusy(true); setError("");
    try { await api.recordOutcome(order.id, { outcome, verified, note }); setNote(""); setVerified(false); await onSaved(); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <section aria-label="Outcome"><h3>Outcome</h3>
    {outcomes.length === 0 ? <p className="muted-text">No outcome recorded yet.</p> : <ul>{outcomes.map(o =>
      <li key={o.id}><strong>{o.outcome.replace(/_/g, " ")}</strong>{o.verified ? " (verified)" : " (unverified)"}{o.note && ` — ${o.note}`}</li>)}</ul>}
    {canReview && <form onSubmit={save}>
      <ErrorNotice error={error}/>
      <label>Result <select value={outcome} onChange={e => setOutcome(e.target.value)}>
        <option value="legitimate">Legitimate</option><option value="false_positive">False alarm</option>
        <option value="confirmed_fraud">Confirmed fraud</option><option value="undetermined">Undetermined</option></select></label>
      <label><input type="checkbox" checked={verified} onChange={e => setVerified(e.target.checked)}/> Verified with evidence (e.g. chargeback, customer contact)</label>
      <label>Note <input value={note} maxLength={500} onChange={e => setNote(e.target.value)}/></label>
      <button type="submit" className="btn btn-secondary" disabled={busy}>Record outcome</button>
      <p className="muted-text">Only verified outcomes can be used to train future models, and nothing retrains automatically.</p>
    </form>}</section>;
}

function OrderDetail({ id, onClose, onChanged }) {
  const { role } = useAuth();
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { try { setD(await api.staffOrder(id)); setError(""); } catch (e) { setError(e.message); } }, [id]);
  useEffect(() => { load(); }, [load]);

  async function run(fn) {
    setBusy(true); setError("");
    try { await fn(); await load(); onChanged(); } catch (e) { setError(e.message); } finally { setBusy(false); setConfirm(null); }
  }
  const o = d?.order;
  const actions = o && role === "admin" ? NEXT[o.status] || [] : [];
  return <Modal title={o ? `Order ${o.reference}` : "Order"} onClose={onClose} wide>
    <ErrorNotice error={error}/>
    {!d ? <Skeleton count={4}/> : <div className="order-detail">
      <p>Status <strong>{ORDER_STATUS[o.status] || o.status}</strong> · Payment <strong>{PAYMENT_STATUS[o.payment_status] || o.payment_status}</strong>
        {" "}({o.payment_method}{o.payment_mode !== "LIVE" ? `, ${o.payment_mode.toLowerCase()}` : ""}) · {moneyC(o.total_cents, o.currency)} · placed {when(o.created_at)}</p>
      <section aria-label="Customer"><h3>Customer</h3>
        <p>{o.contact_name} · {o.contact_email} · {o.contact_phone}{o.fulfilment === "delivery" && <><br/>{o.address_line}, {o.city}{o.area ? `, ${o.area}` : ""}</>}</p>
        {d.contact_masked && <p className="muted-text">Contact details are masked for your role.</p>}</section>
      <section aria-label="Risk assessment"><h3>Risk assessment</h3>
        {d.assessments.length === 0 ? <p className="muted-text">This order has not been scored.</p> : <>
          <p><RiskPill risk={d.assessments[0]}/> <span className="muted-text">{d.assessments[0].note}</span></p>
          {d.assessments[0].reasons.length === 0 ? <p>No rule fired.</p>
            : <ul>{d.assessments[0].reasons.map(r => <li key={r.rule}><strong>+{r.points}</strong> {r.text}</li>)}</ul>}
          {d.assessments.length > 1 && <p className="muted-text">{d.assessments.length - 1} earlier assessment(s): {d.assessments.slice(1).map(a => `${a.score} (${a.trigger.replace(/_/g, " ")})`).join(", ")}</p>}</>}
        {d.case && <p>Case: <Link to="/investigations">{d.case.case_reference}</Link> ({d.case.status}, {d.case.severity})</p>}</section>
      <section aria-label="Model results"><h3>Trained-model results</h3>
        {(d.ml_predictions || []).length === 0 ? <p className="muted-text">No model result recorded.</p> : <ul>{d.ml_predictions.map(m =>
          <li key={m.model}>{m.model.replace(/_/g, " ")}: <strong>{m.status === "ok" ? `${Math.round(m.probability * 100)}% (threshold ${m.threshold})` : m.status.replace(/_/g, " ")}</strong>
            {m.experimental && <span className="muted-text"> (experimental, no alert)</span>}
            {m.status === "unsupported_input_schema" && <span className="muted-text"> — the store does not collect this model's inputs, so no score was made up.</span>}
            {m.status === "model_unavailable" && <span className="muted-text"> — model not trained or not loaded.</span>}</li>)}</ul>}</section>
      <OutcomeForm order={o} outcomes={d.outcomes || []} onSaved={load}/>
      <section aria-label="Items"><h3>Items</h3>
        <ul>{o.items.map(i => <li key={i.sku}>{i.quantity} × {i.name} <span className="muted-text">({moneyC(i.line_total_cents, o.currency)})</span></li>)}</ul></section>
      <section aria-label="Payments"><h3>Payment attempts</h3>
        {o.payment_attempts.length === 0 ? <p className="muted-text">None.</p> : <ul>{o.payment_attempts.map(a =>
          <li key={a.reference}>{a.reference} · {a.method} · <strong>{a.status.replace(/_/g, " ")}</strong>{a.failure_reason && ` · ${a.failure_reason}`} · {when(a.created_at)}</li>)}</ul>}</section>
      <section aria-label="History"><h3>Status history</h3>
        <ul>{d.history.map((h, i) => <li key={i}>{when(h.at)}: {h.from ? `${ORDER_STATUS[h.from] || h.from} → ` : ""}{ORDER_STATUS[h.to] || h.to}{h.reason && ` (${h.reason})`}</li>)}</ul></section>
      {role === "admin" && <div className="dialog-actions">
        {o.payment_status === "refund_pending" && <button type="button" className="btn btn-primary" disabled={busy}
          onClick={() => setConfirm({ title: "Refund this order?", message: `This sends a full refund of ${moneyC(o.total_cents, o.currency)} to the customer through the payment provider. It can only be done once.`,
            label: "Refund", fn: () => api.refundOrder(o.id) })}>Refund customer</button>}
        {actions.map(s => <button key={s} type="button" className={`btn ${s === "cancelled" ? "btn-secondary" : "btn-primary"}`} disabled={busy}
          onClick={() => s === "cancelled"
            ? setConfirm({ title: "Cancel this order?", message: o.payment_status === "paid" ? "The customer has paid. Cancelling puts the order into 'refund pending' and returns the stock." : "The reserved stock is returned.", label: "Cancel order", fn: () => api.setOrderStatus(o.id, s) })
            : run(() => api.setOrderStatus(o.id, s))}>{ACTION_LABEL[s]}</button>)}</div>}
    </div>}
    {confirm && <ConfirmDialog title={confirm.title} message={confirm.message} confirmLabel={confirm.label} onCancel={() => setConfirm(null)} onConfirm={() => run(confirm.fn)}/>}
  </Modal>;
}

export default function StaffOrders() {
  const [params] = useSearchParams();
  const [f, setF] = useState({ status: params.get("status") || "", payment_status: params.get("payment_status") || "",
    decision: params.get("decision") || "", search: params.get("search") || "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);
  const set = k => e => { setPage(1); setF({ ...f, [k]: e.target.value }); };
  const load = useCallback(async () => {
    try { setData(await api.staffOrders({ ...f, page, page_size: 20 })); setError(""); } catch (e) { setError(e.message); }
    api.riskSummary().then(setSummary).catch(() => {});
  }, [f, page]);
  useEffect(() => { load(); }, [load]);

  return <div>
    <PageHeader title="Orders & Risk" subtitle="Every store order with its payment, rule-based risk score and case. Scores are signals for a person to review, never proof of fraud."/>
    {summary && <div className="stat-row" role="group" aria-label="Orders by risk">
      {["high", "review", "allow"].map(k => <div key={k} className="stat-card"><span className="stat-label">{DECISION[k][1]}</span><strong>{summary.counts[k]}</strong></div>)}</div>}
    <div className="panel">
      <div className="toolbar" role="search" aria-label="Filter orders">
        <Field label="Order status">{a => <select {...a} value={f.status} onChange={set("status")}><option value="">All</option>{Object.entries(ORDER_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>}</Field>
        <Field label="Payment">{a => <select {...a} value={f.payment_status} onChange={set("payment_status")}><option value="">All</option>{Object.entries(PAYMENT_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>}</Field>
        <Field label="Risk">{a => <select {...a} value={f.decision} onChange={set("decision")}><option value="">All</option><option value="high">High</option><option value="review">Review</option><option value="allow">Low</option></select>}</Field>
        <Field label="Search reference or name">{a => <input {...a} type="search" maxLength={40} value={f.search} onChange={set("search")}/>}</Field>
      </div>
      {error ? <ErrorState error={error} onRetry={load}/> : !data ? <Skeleton count={5}/> : data.items.length === 0 ? <EmptyState><p>No orders match.</p></EmptyState> : <>
        <div className="table-wrap table-cards"><table><thead><tr><th scope="col">Order</th><th scope="col">Placed</th><th scope="col">Customer</th><th scope="col">Total</th><th scope="col">Status</th><th scope="col">Payment</th><th scope="col">Risk</th></tr></thead>
          <tbody>{data.items.map(o => <tr key={o.id}>
            <td data-label="Order"><button type="button" className="link-button" onClick={() => setOpen(o.id)} aria-label={`Open order ${o.reference}`}>{o.reference}</button></td>
            <td data-label="Placed">{when(o.created_at)}</td><td data-label="Customer">{o.contact_name}</td>
            <td data-label="Total">{moneyC(o.total_cents, o.currency)}</td><td data-label="Status">{ORDER_STATUS[o.status] || o.status}</td>
            <td data-label="Payment">{PAYMENT_STATUS[o.payment_status] || o.payment_status}</td><td data-label="Risk"><RiskPill risk={o.risk}/></td></tr>)}</tbody></table></div>
        <Pagination page={page} pageSize={20} total={data.total} onChange={setPage}/></>}
    </div>
    {open && <OrderDetail id={open} onClose={() => setOpen(null)} onChanged={load}/>}
  </div>;
}
