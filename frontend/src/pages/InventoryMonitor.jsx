import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Field } from "../components/forms";
import { EmptyState, ErrorNotice, ErrorState, Modal, PageHeader, Pagination, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { STOCK_LABEL } from "../store/components";

function AdjustDialog({ item, onClose, onSaved }) {
  const [value, setValue] = useState(String(item.available_quantity));
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  async function save(e) {
    e.preventDefault(); setError("");
    const n = Number(value);
    if (!Number.isInteger(n) || n < 0) { setError("Enter a whole number, zero or more."); return; }
    if (reason.trim().length < 3) { setError("Give a reason (at least 3 characters). It is saved in the audit trail."); return; }
    try { await api.adjustInventory(item.product_id, { set_available: n, reason: reason.trim() }); onSaved(); onClose(); } catch (err) { setError(err.message); }
  }
  return <Modal title={`Adjust stock: ${item.name}`} onClose={onClose}><form onSubmit={save} noValidate>
    <p className="muted-text">Currently {item.available_quantity} available, {item.reserved_quantity} reserved by open orders.</p><ErrorNotice error={error}/>
    <Field label="New available quantity">{a => <input {...a} type="number" min="0" value={value} onChange={e => setValue(e.target.value)}/>}</Field>
    <Field label="Reason (audited)">{a => <input {...a} maxLength={300} value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. stock count correction"/>}</Field>
    <div className="dialog-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button><button className="btn btn-primary">Save</button></div>
  </form></Modal>;
}

export default function InventoryMonitor() {
  const { role } = useAuth();
  const [params] = useSearchParams();
  const [status, setStatus] = useState(["low_stock", "out_of_stock"].includes(params.get("status")) ? params.get("status") : "");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [adjusting, setAdjusting] = useState(null);
  const load = useCallback(async () => {
    try { setData(await api.inventory({ status, search, page, page_size: 20 })); setError(""); } catch (e) { setError(e.message); }
  }, [status, search, page]);
  useEffect(() => { load(); }, [load]);

  return <div>
    <PageHeader title="Inventory" subtitle="Stock held in the store database, with reserved quantities and reorder levels. Orders that trip the risk rules open cases in the Investigation Centre."
      actions={<Link className="btn btn-secondary" to="/investigations">View order-anomaly cases</Link>}/>
    <div className="panel">
      <div className="toolbar" role="search" aria-label="Filter inventory">
        <Field label="Stock level">{a => <select {...a} value={status} onChange={e => { setPage(1); setStatus(e.target.value); }}><option value="">All</option><option value="low_stock">Low stock</option><option value="out_of_stock">Out of stock</option></select>}</Field>
        <Field label="Search product or SKU">{a => <input {...a} type="search" maxLength={60} value={search} onChange={e => { setPage(1); setSearch(e.target.value); }}/>}</Field>
      </div>
      {error ? <ErrorState error={error} onRetry={load}/> : !data ? <Skeleton count={5}/> : data.items.length === 0 ? <EmptyState><p>No products match.</p></EmptyState> : <>
        <div className="table-wrap table-cards"><table><thead><tr><th scope="col">Product</th><th scope="col">SKU</th><th scope="col">Available</th><th scope="col">Reserved</th><th scope="col">Reorder at</th><th scope="col">Status</th>{role === "admin" && <th scope="col"><span className="sr-only">Adjust</span></th>}</tr></thead>
          <tbody>{data.items.map(i => <tr key={i.product_id}><td data-label="Product">{i.name}</td><td data-label="SKU">{i.sku}</td><td data-label="Available">{i.available_quantity}</td>
            <td data-label="Reserved">{i.reserved_quantity}</td><td data-label="Reorder at">{i.reorder_threshold}</td>
            <td data-label="Status"><span className={`stock-badge ${i.stock_status}`}>{STOCK_LABEL[i.stock_status]}</span></td>
            {role === "admin" && <td><button type="button" className="link-button" onClick={() => setAdjusting(i)} aria-label={`Adjust ${i.name}`}>Adjust</button></td>}</tr>)}</tbody></table></div>
        <Pagination page={page} pageSize={20} total={data.total} onChange={setPage}/></>}
    </div>
    {adjusting && <AdjustDialog item={adjusting} onClose={() => setAdjusting(null)} onSaved={load}/>}
  </div>;
}
