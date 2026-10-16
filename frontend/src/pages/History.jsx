import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { History as HistoryIcon, RefreshCw, Search } from "lucide-react";
import { EmptyState, ErrorState, PageHeader, Pagination, Skeleton, TransactionTable } from "../components/ui";
import { api } from "../services/api";
import { getPrefs } from "../services/prefs";

const BLANK = { search: "", risk: "", review_status: "", date_from: "", date_to: "" };

export default function History() {
  const [params] = useSearchParams();
  const initial = { ...BLANK, search: (params.get("search") || "").slice(0, 40) };
  const [draft, setDraft] = useState(initial);
  const [applied, setApplied] = useState(initial);
  const [sort, setSort] = useState({ by: "created_at", dir: "desc" });
  const [page, setPage] = useState(1);
  const [pageSize] = useState(() => getPrefs().pageSize);
  const [data, setData] = useState({ items: [], total: 0 });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.transactions({ ...applied, page, page_size: pageSize, sort_by: sort.by, sort_dir: sort.dir });
      setData(d); setError("");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [applied, page, pageSize, sort]);
  useEffect(() => { load(); }, [load]);

  const set = k => e => setDraft({ ...draft, [k]: e.target.value });
  const badRange = draft.date_from && draft.date_to && draft.date_from > draft.date_to;
  function apply(e) { e.preventDefault(); if (badRange) return; setPage(1); setApplied({ ...draft, search: draft.search.trim() }); }
  function clear() { setDraft(BLANK); setApplied(BLANK); setPage(1); }
  function toggleSort(by) { setPage(1); setSort(s => s.by === by ? { by, dir: s.dir === "asc" ? "desc" : "asc" } : { by, dir: "desc" }); }
  const filtered = Object.values(applied).some(Boolean);

  return <div>
    <PageHeader title="Transaction History" subtitle={`${data.total} transaction${data.total === 1 ? "" : "s"} saved by the FraudGuard API.`}
      actions={<button type="button" className="btn btn-secondary" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""}/> Refresh</button>}/>
    <section className="panel">
      <div className="panel-heading"><h2><HistoryIcon size={18}/> Prediction records</h2></div>
      <form className="filters" onSubmit={apply} role="search">
        <div className="field"><label htmlFor="h-search"><span>Search reference</span></label><input id="h-search" value={draft.search} onChange={set("search")} placeholder="e.g. TX-1001" maxLength={40}/></div>
        <div className="field"><label htmlFor="h-risk"><span>Risk level</span></label><select id="h-risk" value={draft.risk} onChange={set("risk")}><option value="">All</option><option>Low</option><option>Medium</option><option>High</option></select></div>
        <div className="field"><label htmlFor="h-status"><span>Review status</span></label><select id="h-status" value={draft.review_status} onChange={set("review_status")}>
          <option value="">All</option><option value="new">New</option><option value="confirmed_fraud">Confirmed fraud</option><option value="false_positive">False positive</option></select></div>
        <div className="field"><label htmlFor="h-from"><span>From date</span></label><input id="h-from" type="date" value={draft.date_from} onChange={set("date_from")}/></div>
        <div className="field"><label htmlFor="h-to"><span>To date</span></label><input id="h-to" type="date" value={draft.date_to} onChange={set("date_to")}/></div>
        <button className="btn btn-primary"><Search size={15}/> Apply</button>
        {(filtered || Object.values(draft).some(Boolean)) && <button type="button" className="btn btn-ghost" onClick={clear}>Clear filters</button>}
      </form>
      {badRange && <div className="notice error" role="alert">“From date” must not be after “To date”.</div>}
      {error ? <ErrorState error={error} onRetry={load}/> : loading && !data.items.length ? <Skeleton count={6}/> : data.items.length ?
        <TransactionTable items={data.items} showReview sort={sort} onSort={toggleSort}/> :
        <EmptyState>{filtered ? "No transactions match these filters." : "No transactions yet. Submit a payment to create one."}</EmptyState>}
      {data.total > 0 && !error && <Pagination page={page} pageSize={pageSize} total={data.total} onChange={setPage}/>}
    </section>
  </div>;
}
