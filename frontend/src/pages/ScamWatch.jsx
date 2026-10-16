import { useCallback, useEffect, useState } from "react";
import { Field } from "../components/forms";
import ScamChecker, { VerdictBadge } from "../components/ScamChecker";
import { EmptyState, ErrorNotice, ErrorState, Modal, PageHeader, Pagination, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { when } from "../services/format";

export const REVIEW_TEXT = { pending: "Pending review", reviewed_malicious: "Confirmed malicious", reviewed_benign: "Reviewed: benign", dismissed: "Dismissed" };

function ReviewDialog({ report, onClose, onSaved }) {
  const [status, setStatus] = useState(report.review_status);
  const [notes, setNotes] = useState(report.analyst_notes || "");
  const [error, setError] = useState("");
  async function save(e) {
    e.preventDefault(); setError("");
    try { await api.reviewScamReport(report.id, status, notes); onSaved(); onClose(); } catch (err) { setError(err.message); }
  }
  return <Modal title={`Review ${report.domain}`} onClose={onClose}><form onSubmit={save}>
    <p className="muted-text">{report.normalized_url} · {report.report_count} report(s)</p><p><VerdictBadge verdict={report.verdict}/></p>
    <ErrorNotice error={error}/>
    <Field label="Review status">{a => <select {...a} value={status} onChange={e => setStatus(e.target.value)}>{Object.entries(REVIEW_TEXT).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
    <Field label="Analyst notes">{a => <textarea {...a} rows={3} maxLength={2000} value={notes} onChange={e => setNotes(e.target.value)}/>}</Field>
    <div className="dialog-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button><button className="btn btn-primary">Save review</button></div>
  </form></Modal>;
}

export default function ScamWatch() {
  const { role } = useAuth();
  const canReview = role === "security_analyst" || role === "admin";
  const [f, setF] = useState({ review_status: "", verdict: "", search: "" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [reviewing, setReviewing] = useState(null);
  const [providers, setProviders] = useState([]);

  const load = useCallback(async () => {
    try { setData(await api.scamReports({ ...f, page, page_size: 15 })); setError(""); } catch (e) { setError(e.message); }
  }, [f, page]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.integrations?.().then(d => setProviders(d.scamwatch_providers || [])).catch(() => {}); }, []);
  const set = k => e => { setPage(1); setF({ ...f, [k]: e.target.value }); };

  return <div>
    <PageHeader title="ScamWatch" subtitle="Check suspicious web addresses and review what people have reported. Addresses are analysed as text and never opened."/>
    <div className="panel"><h2>Check a website</h2><ScamChecker onReported={load}/>
      {providers.length > 0 && <p className="muted-text">Providers: {providers.map(p => `${p.name} (${p.configured ? "configured" : "not configured"}${p.live_tested ? "" : ", live calls not verified"})`).join(" · ")}</p>}</div>
    <div className="panel"><h2>Report history</h2>
      <div className="toolbar" role="search" aria-label="Filter reports">
        <Field label="Review status">{a => <select {...a} value={f.review_status} onChange={set("review_status")}><option value="">All</option>{Object.entries(REVIEW_TEXT).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
        <Field label="Verdict">{a => <select {...a} value={f.verdict} onChange={set("verdict")}><option value="">All</option>{["malicious", "suspicious", "no_known_threat", "inconclusive"].map(v => <option key={v}>{v}</option>)}</select>}</Field>
        <Field label="Domain contains">{a => <input {...a} type="search" maxLength={60} value={f.search} onChange={set("search")}/>}</Field>
      </div>
      {error ? <ErrorState error={error} onRetry={load}/> : !data ? <Skeleton count={3}/> : data.items.length === 0 ? <EmptyState><p>No reports yet.</p></EmptyState> : <>
        <div className="table-wrap table-cards"><table><thead><tr><th scope="col">Website</th><th scope="col">Verdict</th><th scope="col">Reports</th><th scope="col">Last reported</th><th scope="col">Review</th>{canReview && <th scope="col"><span className="sr-only">Actions</span></th>}</tr></thead>
          <tbody>{data.items.map(r => <tr key={r.id}><td data-label="Website" className="wrap">{r.normalized_url}</td><td data-label="Verdict"><VerdictBadge verdict={r.verdict}/></td>
            <td data-label="Reports">{r.report_count}</td><td data-label="Last reported">{when(r.last_reported_at)}</td><td data-label="Review">{REVIEW_TEXT[r.review_status]}</td>
            {canReview && <td><button type="button" className="link-button" onClick={() => setReviewing(r)} aria-label={`Review ${r.domain}`}>Review</button></td>}</tr>)}</tbody></table></div>
        <Pagination page={page} pageSize={15} total={data.total} onChange={setPage}/></>}
    </div>
    {reviewing && <ReviewDialog report={reviewing} onClose={() => setReviewing(null)} onSaved={load}/>}
  </div>;
}
