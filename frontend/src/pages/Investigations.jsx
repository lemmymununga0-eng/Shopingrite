import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { CASE_STATUS, SOURCE_LABEL, SeverityBadge, StatusBadge } from "../components/badges";
import { Field } from "../components/forms";
import { EmptyState, ErrorNotice, ErrorState, Modal, PageHeader, Pagination, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { when } from "../services/format";

const PAGE_SIZE = 15;

function CaseDialog({ id, onClose, onChanged }) {
  const { user } = useAuth();
  const [c, setC] = useState(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.caseDetail(id).then(d => { setC(d); setStatus(d.status); }).catch(e => setError(e.message)); }, [id]);

  async function save(body) {
    setError(""); setBusy(true);
    try { const d = await api.updateCase(id, body); setC(d); setStatus(d.status); setNote(""); onChanged(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  if (!c) return <Modal title="Case" onClose={onClose}>{error ? <ErrorNotice error={error}/> : <p>Loading…</p>}</Modal>;
  const mine = c.assigned_to === user?.id;
  return <Modal title={`Case ${c.case_reference}`} onClose={onClose} wide>
    <p><SeverityBadge severity={c.severity}/> <StatusBadge status={c.status}/> · {SOURCE_LABEL[c.source_type]}</p>
    <p>{c.summary}</p>
    <p className="muted-text">Evidence: {c.evidence_reference || "—"} · Created {when(c.created_at)} · Assigned to: {c.assigned_to ? (mine ? "you" : c.assigned_to) : "nobody"}</p>
    <p className="notice info" role="note">{c.signal_note}</p>
    <ErrorNotice error={error}/>
    <h3>Notes</h3>
    {c.notes.length === 0 ? <p className="muted-text">No notes yet.</p> : <ul className="note-list">{c.notes.map(n => <li key={n.id}><small>{when(n.created_at)} · {n.author_id}</small><br/>{n.body}</li>)}</ul>}
    <Field label="Add a note">{a => <textarea {...a} rows={2} maxLength={2000} value={note} onChange={e => setNote(e.target.value)}/>}</Field>
    <div className="toolbar">
      <Field label="Status">{a => <select {...a} value={status} onChange={e => setStatus(e.target.value)}>{Object.entries(CASE_STATUS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
      <button type="button" className="btn btn-primary" disabled={busy || (!note.trim() && status === c.status)}
        onClick={() => save({ ...(status !== c.status ? { status } : {}), ...(note.trim() ? { note: note.trim() } : {}) })}>Save changes</button>
      {!mine && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => save({ assigned_to: "me" })}>Assign to me</button>}
      {mine && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => save({ assigned_to: null })}>Unassign</button>}
    </div>
  </Modal>;
}

function NewCaseDialog({ onClose, onCreated }) {
  const [summary, setSummary] = useState("");
  const [severity, setSeverity] = useState("medium");
  const [evidence, setEvidence] = useState("");
  const [error, setError] = useState("");
  async function submit(e) {
    e.preventDefault(); setError("");
    if (summary.trim().length < 3) { setError("Describe the concern in at least 3 characters."); return; }
    try { await api.createCase({ summary: summary.trim(), severity, evidence_reference: evidence.trim() }); onCreated(); onClose(); }
    catch (err) { setError(err.message); }
  }
  return <Modal title="New manual case" onClose={onClose}><form onSubmit={submit} noValidate>
    <ErrorNotice error={error}/>
    <Field label="Summary">{a => <textarea {...a} rows={3} maxLength={500} value={summary} onChange={e => setSummary(e.target.value)}/>}</Field>
    <Field label="Severity">{a => <select {...a} value={severity} onChange={e => setSeverity(e.target.value)}>{["low", "medium", "high", "critical"].map(s => <option key={s}>{s}</option>)}</select>}</Field>
    <Field label="Evidence reference (optional)">{a => <input {...a} maxLength={300} value={evidence} onChange={e => setEvidence(e.target.value)} placeholder="e.g. ticket number"/>}</Field>
    <div className="dialog-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button><button className="btn btn-primary">Create case</button></div>
  </form></Modal>;
}

export default function Investigations() {
  const [f, setF] = useState({ status: "", severity: "", source_type: "", assigned_to: "", search: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try { setData(await api.cases({ ...f, page, page_size: PAGE_SIZE })); setError(""); } catch (e) { setError(e.message); }
  }, [f, page]);
  useEffect(() => { load(); }, [load]);
  const set = k => e => { setPage(1); setF({ ...f, [k]: e.target.value }); };

  return <div>
    <PageHeader title="Investigation Centre" subtitle="Cases from fraud predictions, website reports, security alerts and order checks. Every score or report is a signal for review, not proof of wrongdoing."
      actions={<button type="button" className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={15}/> New case</button>}/>
    <div className="panel">
      <div className="toolbar" role="search" aria-label="Filter cases">
        <Field label="Status">{a => <select {...a} value={f.status} onChange={set("status")}><option value="">All</option>{Object.entries(CASE_STATUS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
        <Field label="Severity">{a => <select {...a} value={f.severity} onChange={set("severity")}><option value="">All</option>{["critical", "high", "medium", "low"].map(s => <option key={s}>{s}</option>)}</select>}</Field>
        <Field label="Source">{a => <select {...a} value={f.source_type} onChange={set("source_type")}><option value="">All</option>{Object.entries(SOURCE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
        <Field label="Assigned">{a => <select {...a} value={f.assigned_to} onChange={set("assigned_to")}><option value="">Anyone</option><option value="me">Me</option><option value="unassigned">Unassigned</option></select>}</Field>
        <Field label="Search">{a => <input {...a} type="search" maxLength={80} value={f.search} onChange={set("search")} placeholder="Reference or summary"/>}</Field>
      </div>
      {error ? <ErrorState error={error} onRetry={load}/> : !data ? <Skeleton count={4}/> : data.items.length === 0 ? <EmptyState><p>No cases match. Cases appear here when a prediction is flagged, a website is reported, or a security alert fires.</p></EmptyState> :
        <><div className="table-wrap table-cards"><table><thead><tr><th scope="col">Case</th><th scope="col">Severity</th><th scope="col">Status</th><th scope="col">Source</th><th scope="col">Summary</th><th scope="col">Created</th><th scope="col"><span className="sr-only">Open</span></th></tr></thead>
          <tbody>{data.items.map(c => <tr key={c.id}>
            <td data-label="Case">{c.case_reference}</td><td data-label="Severity"><SeverityBadge severity={c.severity}/></td><td data-label="Status"><StatusBadge status={c.status}/></td>
            <td data-label="Source">{SOURCE_LABEL[c.source_type]}</td><td data-label="Summary" className="wrap">{c.summary}</td><td data-label="Created">{when(c.created_at)}</td>
            <td><button type="button" className="link-button" onClick={() => setOpenId(c.id)} aria-label={`Open ${c.case_reference}`}>Open</button></td></tr>)}</tbody></table></div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage}/></>}
    </div>
    {openId && <CaseDialog id={openId} onClose={() => setOpenId(null)} onChanged={load}/>}
    {creating && <NewCaseDialog onClose={() => setCreating(false)} onCreated={load}/>}
  </div>;
}
