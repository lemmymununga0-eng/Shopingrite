import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { ErrorState, PageHeader, ReviewBadge, RiskBadge, Skeleton } from "../components/ui";
import { api } from "../services/api";
import { money, pct, when } from "../services/format";

const yesNo = v => (v ? "Yes" : "No");

export default function TransactionDetail() {
  const { id } = useParams();
  const [tx, setTx] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setTx(await api.transaction(id)); setError(""); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const D = ({ label, children }) => <><dt>{label}</dt><dd>{children}</dd></>;
  return <div>
    <p className="breadcrumb"><Link to="/history"><ArrowLeft size={13}/> Back to History</Link></p>
    <PageHeader title="Transaction Details" subtitle={tx ? `Reference ${tx.transaction_reference}` : "Loading transaction…"}/>
    {error ? <section className="panel"><ErrorState error={error} onRetry={load}/></section> : loading || !tx ? <Skeleton count={5}/> : <>
      <section className="panel">
        <div className="panel-heading"><h2>Model prediction</h2><div><RiskBadge risk={tx.risk}/> <ReviewBadge status={tx.review_status}/></div></div>
        <dl className="detail-grid">
          <D label="Prediction">{tx.prediction}</D><D label="Fraud probability">{pct(tx.probability)}</D>
          <D label="Risk level">{tx.risk}</D><D label="Flagged">{yesNo(tx.is_flagged)}</D>
          <D label="Model version">{tx.model_version}</D><D label="Recorded">{when(tx.created_at)}</D>
        </dl>
        <p className="muted-text">A model prediction estimates risk. It is not proof of fraud until an authorised reviewer confirms it.</p>
        {tx.contributing_factors.length > 0 && <><h3>Observations on this transaction</h3><ul className="factor-list">{tx.contributing_factors.map(c => <li key={c}>{c}</li>)}</ul>
          <p className="muted-text">Simple rule checks on the submitted values; not an explanation of the model.</p></>}
      </section>
      <section className="panel">
        <div className="panel-heading"><h2>Transaction details</h2></div>
        <dl className="detail-grid">
          <D label="Amount">{money(tx.amount)}</D><D label="Customer average spend">{money(tx.customer_avg_spend)}</D>
          <D label="Payment method">{tx.payment_method}</D><D label="Branch">{tx.branch}</D>
          <D label="Hour of day">{String(tx.hour).padStart(2, "0")}:00</D><D label="Failed attempts">{tx.failed_attempts}</D>
          <D label="New device">{yesNo(tx.new_device)}</D><D label="International">{yesNo(tx.international)}</D>
        </dl>
      </section>
      {tx.is_flagged && <section className="panel">
        <div className="panel-heading"><h2>Review</h2><Link className="btn btn-primary" to="/alerts">Open in Fraud Alerts</Link></div>
        <dl className="detail-grid">
          <D label="Status"><ReviewBadge status={tx.review_status}/></D><D label="Reviewed at">{when(tx.reviewed_at)}</D>
          <D label="Reviewer notes">{tx.review_notes || "—"}</D></dl>
      </section>}
    </>}
  </div>;
}
