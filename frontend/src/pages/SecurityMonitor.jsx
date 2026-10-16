import { useCallback, useEffect, useState } from "react";
import { Activity, ShieldAlert } from "lucide-react";
import StatCard from "../components/StatCard";
import { SeverityBadge } from "../components/badges";
import { Field } from "../components/forms";
import { EmptyState, ErrorNotice, ErrorState, Modal, PageHeader, Pagination, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { when } from "../services/format";

const SEVERITIES = ["info", "low", "medium", "high", "critical"];
const CATEGORIES = ["authentication", "authorization", "rate_limit", "input", "application", "model", "provider", "privileged", "inventory", "order", "threshold"];
const PAGE_SIZE = 20;
const EMPTY = { severity: "", category: "", search: "", correlation_id: "", date_from: "", date_to: "" };

function EventDialog({ id, onClose }) {
  const [e, setE] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api.securityEvent(id).then(setE).catch(x => setError(x.message)); }, [id]);
  return <Modal title={`Security event #${id}`} onClose={onClose} wide>
    <ErrorNotice error={error}/>{!e && !error && <p>Loading…</p>}
    {e && <dl className="detail-list">
      <div><dt>When</dt><dd>{when(e.created_at)}</dd></div><div><dt>Severity</dt><dd><SeverityBadge severity={e.severity}/></dd></div>
      <div><dt>Category</dt><dd>{e.category}</dd></div><div><dt>Type</dt><dd>{e.event_type}</dd></div>
      <div><dt>Message</dt><dd>{e.message}</dd></div><div><dt>Request</dt><dd>{e.method} {e.path} → {e.status_code ?? "—"}</dd></div>
      <div><dt>Correlation ID</dt><dd><code>{e.correlation_id || "—"}</code></dd></div><div><dt>Actor</dt><dd>{e.actor_id || "—"}</dd></div>
      <div><dt>Details (redacted)</dt><dd><pre>{JSON.stringify(e.details, null, 2)}</pre></dd></div></dl>}
  </Modal>;
}

function Thresholds() {
  const { role } = useAuth();
  const [t, setT] = useState(null);
  const [edit, setEdit] = useState({});
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { api.thresholds().then(d => { setT(d); setEdit(d.thresholds); }).catch(e => setError(e.message)); }, []);
  async function save(e) {
    e.preventDefault(); setError(""); setMsg("");
    try { const d = await api.setThresholds(Object.fromEntries(Object.entries(edit).map(([k, v]) => [k, Number(v)]))); setEdit(d.thresholds); setMsg("Thresholds saved."); }
    catch (err) { setError(err.message); }
  }
  if (!t) return error ? <ErrorNotice error={error}/> : null;
  return <div className="panel"><h2>Alert thresholds</h2>
    <p className="muted-text">When one client or the application as a whole passes a limit within {t.window_minutes} minutes, an alert and an investigation case are created.</p>
    <form onSubmit={save} className="toolbar"><ErrorNotice error={error}/>
      {Object.keys(t.thresholds).map(k => <Field key={k} label={k.replace(/_/g, " ")}>{a => <input {...a} type="number" min="1" max="100000" value={edit[k] ?? ""} disabled={role !== "admin"} onChange={e => setEdit({ ...edit, [k]: e.target.value })}/>}</Field>)}
      {role === "admin" ? <button className="btn btn-primary toolbar-button">Save thresholds</button> : <span className="muted-text">Only administrators can change thresholds.</span>}
    </form>{msg && <div className="notice success" role="status">{msg}</div>}</div>;
}

export default function SecurityMonitor() {
  const [f, setF] = useState(EMPTY);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState(null);

  const load = useCallback(async () => {
    try { setData(await api.securityEvents({ ...f, page, page_size: PAGE_SIZE })); setError(""); } catch (e) { setError(e.message); }
  }, [f, page]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.securitySummary(7).then(setSummary).catch(() => {}); }, []);
  const set = k => e => { setPage(1); setF({ ...f, [k]: e.target.value }); };
  const badRange = f.date_from && f.date_to && f.date_from > f.date_to;

  return <div>
    <PageHeader title="Security Monitor" subtitle="Security-relevant events recorded by this application. It does not monitor any network or production infrastructure."/>
    {summary && <div className="cards-4">
      <StatCard title="Events (7 days)" value={summary.total} note="Recorded by this app" icon={Activity} color="blue"/>
      <StatCard title="High / critical" value={(summary.by_severity.high || 0) + (summary.by_severity.critical || 0)} note="Need attention" icon={ShieldAlert} color="red"/>
      <StatCard title="Authentication" value={summary.by_category.authentication || 0} note="Sign-in problems" icon={Activity} color="purple"/>
      <StatCard title="Rate limits" value={summary.by_category.rate_limit || 0} note="Requests refused" icon={Activity} color="green"/></div>}
    <div className="panel">
      <div className="toolbar" role="search" aria-label="Filter security events">
        <Field label="Severity">{a => <select {...a} value={f.severity} onChange={set("severity")}><option value="">All</option>{SEVERITIES.map(s => <option key={s}>{s}</option>)}</select>}</Field>
        <Field label="Category">{a => <select {...a} value={f.category} onChange={set("category")}><option value="">All</option>{CATEGORIES.map(s => <option key={s}>{s}</option>)}</select>}</Field>
        <Field label="Search">{a => <input {...a} type="search" maxLength={80} value={f.search} onChange={set("search")}/>}</Field>
        <Field label="Correlation ID">{a => <input {...a} maxLength={64} value={f.correlation_id} onChange={set("correlation_id")}/>}</Field>
        <Field label="From">{a => <input {...a} type="date" value={f.date_from} onChange={set("date_from")}/>}</Field>
        <Field label="To">{a => <input {...a} type="date" value={f.date_to} onChange={set("date_to")}/>}</Field>
        <button type="button" className="btn btn-secondary toolbar-button" onClick={() => { setF(EMPTY); setPage(1); }}>Clear</button>
      </div>
      {badRange && <div className="notice error" role="alert">The start date cannot be after the end date.</div>}
      {error ? <ErrorState error={error} onRetry={load}/> : !data ? <Skeleton count={5}/> : data.items.length === 0 ? <EmptyState><p>No security events match.</p></EmptyState> : <>
        <div className="table-wrap table-cards"><table><thead><tr><th scope="col">When</th><th scope="col">Severity</th><th scope="col">Category</th><th scope="col">Event</th><th scope="col">Message</th><th scope="col"><span className="sr-only">Details</span></th></tr></thead>
          <tbody>{data.items.map(e => <tr key={e.id}><td data-label="When">{when(e.created_at)}</td><td data-label="Severity"><SeverityBadge severity={e.severity}/></td>
            <td data-label="Category">{e.category}</td><td data-label="Event">{e.event_type}</td><td data-label="Message" className="wrap">{e.message}</td>
            <td><button type="button" className="link-button" onClick={() => setOpenId(e.id)} aria-label={`Details for event ${e.id}`}>Details</button></td></tr>)}</tbody></table></div>
        <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage}/></>}
    </div>
    <Thresholds/>
    {openId && <EventDialog id={openId} onClose={() => setOpenId(null)}/>}
  </div>;
}
