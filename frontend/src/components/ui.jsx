import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowDown, ArrowUp, Inbox, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { REVIEW_LABELS, money, pct, when } from "../services/format";

export function PageHeader({ title, subtitle, actions }) {
  return <div className="page-heading"><div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</div>;
}

export function Loading({ text = "Loading…" }) {
  return <div className="loading" role="status"><Loader2 className="spin" size={18}/> {text}</div>;
}

export function Skeleton({ className = "skeleton-row", count = 1 }) {
  return <div aria-hidden="true">{Array.from({ length: count }, (_, i) => <div key={i} className={`skeleton ${className}`}/>)}</div>;
}

/** Inline error banner. */
export function ErrorNotice({ error, onRetry }) {
  if (!error) return null;
  return <div className="notice error" role="alert">{error}{onRetry && <> <button type="button" className="link-button" onClick={onRetry}>Retry</button></>}</div>;
}

/** Larger error block used when a whole section failed to load. */
export function ErrorState({ error, onRetry }) {
  if (!error) return null;
  return <div className="error-state" role="alert"><AlertTriangle size={28}/><p>{error}</p>
    {onRetry && <button type="button" className="btn btn-secondary" onClick={onRetry}><RefreshCw size={15}/> Try again</button>}</div>;
}

export function EmptyState({ children, icon: Icon = Inbox }) { return <div className="empty-state"><Icon size={30} aria-hidden="true"/>{children}</div>; }

export function RiskBadge({ risk }) { return <span className={`risk-badge ${String(risk).toLowerCase()}`}>{risk} risk</span>; }

export function ReviewBadge({ status }) {
  if (!status) return <span className="muted-text">—</span>;
  const cls = status === "confirmed_fraud" ? "high" : status === "false_positive" ? "low" : "medium";
  return <span className={`risk-badge ${cls}`}>{REVIEW_LABELS[status] || status}</span>;
}

export function ModelBanner({ info }) {
  if (!info) return null;
  if (!info.trained) {
    return <div className="mode-banner"><AlertTriangle size={18}/> Model unavailable — {info.message || "predictions are disabled"}</div>;
  }
  return <div className="mode-banner mode-good"><ShieldCheck size={18}/> Real model loaded · {info.version}{info.is_synthetic ? " · trained on SYNTHETIC data (development only)" : ""}</div>;
}

export function Pagination({ page, pageSize, total, onChange }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <nav className="pagination" aria-label="Pagination">
    <button type="button" className="btn btn-secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</button>
    <span>Page {page} of {pages} · {total} records</span>
    <button type="button" className="btn btn-secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</button>
  </nav>;
}

/** Accessible modal: focus moves in, Escape closes, focus returns to the opener. */
export function Modal({ title, onClose, children, wide = false }) {
  const ref = useRef(null);
  useEffect(() => {
    const opener = document.activeElement;
    ref.current?.focus();
    const onKey = e => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); opener?.focus?.(); };
  }, [onClose]);
  return <div className="dialog-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
    <div className={`dialog${wide ? " modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
      <h2>{title}</h2>{children}</div></div>;
}

export function ConfirmDialog({ title, message, confirmLabel = "Confirm", onConfirm, onCancel }) {
  return <Modal title={title} onClose={onCancel}>
    <p className="muted-text">{message}</p>
    <div className="dialog-actions">
      <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
      <button type="button" className="btn btn-primary" onClick={onConfirm}>{confirmLabel}</button>
    </div></Modal>;
}

const COLUMNS = [
  ["transaction_reference", "Reference", true], ["created_at", "Date", true], ["amount", "Amount", true],
  ["payment_method", "Method", false], ["prediction", "Prediction", false], ["probability", "Probability", true],
  ["risk", "Risk", true],
];

/** Transactions table. Sort headers appear when `onSort` is given; becomes stacked cards on phones. */
export function TransactionTable({ items, showReview = false, sort, onSort, linkTo = x => `/transactions/${x.id}` }) {
  return <div className="table-wrap table-cards"><table><thead><tr>
    {COLUMNS.map(([key, label, sortable]) => {
      const active = sort?.by === key;
      return <th key={key} scope="col" aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
        {sortable && onSort ? <button type="button" className="sort-btn" onClick={() => onSort(key)}>{label}
          {active && (sort.dir === "asc" ? <ArrowUp size={12}/> : <ArrowDown size={12}/>)}</button> : label}</th>;
    })}
    {showReview && <th scope="col">Review</th>}<th scope="col"><span className="sr-only">Actions</span></th>
  </tr></thead><tbody>
    {items.map(x => <tr key={x.id}>
      <td data-label="Reference">{x.transaction_reference}</td><td data-label="Date">{when(x.created_at)}</td>
      <td data-label="Amount">{money(x.amount)}</td><td data-label="Method">{x.payment_method}</td>
      <td data-label="Prediction">{x.prediction}</td><td data-label="Probability">{pct(x.probability)}</td>
      <td data-label="Risk"><RiskBadge risk={x.risk}/></td>
      {showReview && <td data-label="Review"><ReviewBadge status={x.review_status}/></td>}
      <td><Link className="text-link" to={linkTo(x)} aria-label={`View details for ${x.transaction_reference}`}>View details</Link></td>
    </tr>)}
  </tbody></table></div>;
}
