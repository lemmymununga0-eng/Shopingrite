import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { Field } from "../components/forms";
import { EmptyState, ErrorNotice, ErrorState, PageHeader, Pagination, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { ROLE_LABELS, when } from "../services/format";

const ROLES = ["customer", "fraud_analyst", "security_analyst", "admin"];

export function Users() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const load = useCallback(async () => { try { setData(await api.users()); setError(""); } catch (e) { setError(e.message); } }, []);
  useEffect(() => { load(); }, [load]);
  async function change(u, body) {
    setActionError("");
    try { await api.updateUser(u.id, body); await load(); } catch (e) { setActionError(e.message); }
  }
  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!data) return <Skeleton count={4}/>;
  return <div><PageHeader title="Users & Roles" subtitle="Local demonstration accounts. Every change is written to the audit trail."/>
    <div className="notice info" role="note">{data.note}</div>
    {!data.local_auth_enabled && <div className="notice info">Local demo sign-in is switched off, so these accounts cannot sign in.</div>}
    <ErrorNotice error={actionError}/>
    <div className="panel">{data.items.length === 0 ? <EmptyState><p>No local accounts.</p></EmptyState> :
      <div className="table-wrap table-cards"><table><thead><tr><th scope="col">Name</th><th scope="col">Email</th><th scope="col">Role</th><th scope="col">Active</th></tr></thead>
        <tbody>{data.items.map(u => { const me = u.id === user?.id; return <tr key={u.id}>
          <td data-label="Name">{u.full_name}{me && " (you)"}</td><td data-label="Email">{u.email}</td>
          <td data-label="Role"><label className="sr-only" htmlFor={`role-${u.id}`}>Role for {u.email}</label>
            <select id={`role-${u.id}`} value={u.role} disabled={me} onChange={e => change(u, { role: e.target.value })}>{ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}</select></td>
          <td data-label="Active"><label className="check"><input type="checkbox" checked={u.is_active} disabled={me} onChange={e => change(u, { is_active: e.target.checked })} aria-label={`Active: ${u.email}`}/> {u.is_active ? "Active" : "Disabled"}</label></td></tr>; })}</tbody></table></div>}</div></div>;
}

export function AuditTrail() {
  const [f, setF] = useState({ action: "", entity_type: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => { try { setData(await api.audit({ ...f, page, page_size: 25 })); setError(""); } catch (e) { setError(e.message); } }, [f, page]);
  useEffect(() => { load(); }, [load]);
  const set = k => e => { setPage(1); setF({ ...f, [k]: e.target.value }); };
  return <div><PageHeader title="Audit Trail" subtitle="Append-only record of significant actions. It cannot be edited or deleted from the application."/>
    <div className="panel"><div className="toolbar" role="search" aria-label="Filter audit events">
      <Field label="Action">{a => <input {...a} maxLength={60} value={f.action} onChange={set("action")} placeholder="e.g. case.status_changed"/>}</Field>
      <Field label="Entity type">{a => <select {...a} value={f.entity_type} onChange={set("entity_type")}><option value="">All</option>{["case", "order", "inventory", "scam_report", "user", "alert_thresholds"].map(v => <option key={v}>{v}</option>)}</select>}</Field>
      <Field label="From">{a => <input {...a} type="date" value={f.date_from} onChange={set("date_from")}/>}</Field>
      <Field label="To">{a => <input {...a} type="date" value={f.date_to} onChange={set("date_to")}/>}</Field></div>
      {error ? <ErrorState error={error} onRetry={load}/> : !data ? <Skeleton count={5}/> : data.items.length === 0 ? <EmptyState><p>No audit events match.</p></EmptyState> : <>
        <div className="table-wrap table-cards"><table><thead><tr><th scope="col">When</th><th scope="col">Actor</th><th scope="col">Action</th><th scope="col">Entity</th><th scope="col">Change</th></tr></thead>
          <tbody>{data.items.map(e => <tr key={e.id}><td data-label="When">{when(e.created_at)}</td><td data-label="Actor">{e.actor_id || "system"} {e.actor_role && <small>({e.actor_role})</small>}</td>
            <td data-label="Action">{e.action}</td><td data-label="Entity">{e.entity_type} {e.entity_id}</td>
            <td data-label="Change" className="wrap"><code>{JSON.stringify(e.before)} → {JSON.stringify(e.after)}</code></td></tr>)}</tbody></table></div>
        <Pagination page={page} pageSize={25} total={data.total} onChange={setPage}/></>}</div></div>;
}

const Row = ({ label, ok, children }) => <li className="integration-row">
  {ok === true ? <CheckCircle2 size={18} className="ok" aria-label="ok"/> : ok === false ? <XCircle size={18} className="bad" aria-label="not available"/> : <AlertTriangle size={18} className="warn" aria-label="note"/>}
  <div><strong>{label}</strong><div className="muted-text">{children}</div></div></li>;

export function Integrations() {
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => { try { setD(await api.integrations()); setError(""); } catch (e) { setError(e.message); } }, []);
  useEffect(() => { load(); }, [load]);
  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!d) return <Skeleton count={5}/>;
  return <div><PageHeader title="Model & Integrations" subtitle="What is configured and what is actually working. Secrets are never shown."/>
    <div className="notice info" role="note"><strong>{d.retailer_connection.note}</strong></div>
    <div className="panel"><ul className="integration-list">
      <Row label="Store" ok={null}>{d.store.name} · {d.store.currency} · {d.store.is_demo ? "demonstration data" : "live"} · Payment: {d.store.payment}</Row>
      <Row label="Application database" ok={d.database.application_db === "connected"}>{d.database.application_db} ({d.database.application_db_engine}); prediction store: {d.database.prediction_store}</Row>
      <Row label="Authentication" ok={d.authentication.supabase_configured ? null : false}>Supabase configured: {String(d.authentication.supabase_configured)} · live-tested: {String(d.authentication.supabase_live_tested)} · local demo sign-in: {d.authentication.local_demo_auth_enabled ? "ON" : "off"}{d.authentication.warning && <strong> — {d.authentication.warning}</strong>}</Row>
      <Row label="Payment-form fraud model" ok={d.payment_model.available}>{d.payment_model.available ? `${d.payment_model.version} · threshold ${d.payment_model.threshold}${d.payment_model.is_synthetic ? " · trained on SYNTHETIC data" : ""}` : d.payment_model.message}</Row>
      <Row label="PCA demo model" ok={d.pca_model.available}>{d.pca_model.available ? d.pca_model.version : d.pca_model.message}</Row>
      {d.scamwatch_providers.map(p => <Row key={p.name} label={`ScamWatch provider: ${p.name}`} ok={p.configured}>{p.kind} · {p.note}</Row>)}
      <Row label="Rate limits (per minute)" ok={null}>{Object.entries(d.rate_limits_per_minute).map(([k, v]) => `${k} ${v}`).join(" · ")}</Row>
      <Row label="Alert thresholds" ok={null}>{Object.entries(d.alert_thresholds).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")}</Row>
    </ul></div></div>;
}
