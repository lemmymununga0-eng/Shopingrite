import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2 } from "lucide-react";
import { EmptyState, ErrorState, Loading, Pagination } from "../components/ui";
import { useStore } from "../context/StoreContext";
import { api } from "../services/api";
import { moneyC, when } from "../services/format";

export const ORDER_STATUS = { awaiting_payment: "Awaiting payment", payment_failed: "Payment failed", confirmed: "Confirmed", picking: "Being picked", ready: "Ready", out_for_delivery: "Out for delivery", completed: "Completed", cancelled: "Cancelled" };
export const PAYMENT_STATUS = { pending: "Pending", requires_action: "Action required", paid: "Paid", failed: "Failed", cancelled: "Cancelled",
  cod_due: "Pay on delivery", refund_pending: "Refund pending", refunded: "Refunded" };
const METHOD_LABEL = { simulated: "Simulated", cod: "Cash on delivery", card: "Card", mtn_momo: "MTN Mobile Money", airtel_money: "Airtel Money" };
const StatusBadge = ({ status }) => <span className={`order-status ${status}`}>{ORDER_STATUS[status] || status}</span>;


/** Order progress like a parcel tracker. A cancelled order shows its own banner instead of steps. */
const STEP_AT = { awaiting_payment: 1, payment_failed: 1, confirmed: 2, picking: 2, ready: 3, out_for_delivery: 3, completed: 5 };
export function Tracker({ order }) {
  if (order.status === "cancelled") return null;
  const steps = ["Order placed", "Payment confirmed", "Preparing", order.fulfilment === "delivery" ? "Out for delivery" : "Ready to collect", "Completed"];
  const at = STEP_AT[order.status] ?? 1;
  return <ol className={`tracker${order.status === "payment_failed" ? " stopped" : ""}`} aria-label="Order progress">
    {steps.map((label, i) => <li key={label} className={i < at ? "done" : i === at ? "current" : ""} aria-current={i === at ? "step" : undefined}>{label}</li>)}
  </ol>;
}

/** One order: used for the confirmation page (after checkout) and the order-details page. */
export function OrderView({ confirmation = false }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const { refreshCart } = useStore();
  const [againBusy, setAgainBusy] = useState(false);
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const load = useCallback(async () => { try { setOrder(await api.order(id)); setError(""); } catch (e) { setError(e.message); } }, [id]);
  useEffect(() => { load(); }, [load]);

  /** Put every item of this order back in the cart (items that are gone or out of stock are skipped and listed). */
  async function buyAgain() {
    setActionError(""); setAgainBusy(true);
    const skipped = [];
    for (const it of order.items) {
      try { await api.addToCart(it.product_id, it.quantity); } catch { skipped.push(it.name); }
    }
    await refreshCart();
    setAgainBusy(false);
    if (skipped.length) setActionError(`Some items could not be added: ${skipped.join(", ")}.`);
    else navigate("/shop/cart");
  }
  async function cancel() {
    setActionError("");
    try { setOrder(await api.cancelOrder(id)); } catch (e) { setActionError(e.message); }
  }
  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!order) return <Loading text="Loading order…"/>;
  return <article aria-labelledby="order-title">
    {confirmation && ["paid", "cod_due"].includes(order.payment_status) && <div className="notice success confirm-banner" role="status"><CheckCircle2 size={20} aria-hidden="true"/> <strong>Thank you. Your {order.payment_mode === "SIMULATED" ? "demonstration " : ""}order was placed.</strong></div>}
    {["awaiting_payment", "payment_failed"].includes(order.status) && <div className="notice warn" role="status"><strong>This order is not paid yet.</strong> <Link to={`/shop/payment/${order.id}`}>Go to payment</Link></div>}
    <h1 id="order-title">Order <span data-testid="order-ref">{order.reference}</span></h1>
    <Tracker order={order}/>
    {order.status === "cancelled" && <div className="notice error" role="status">This order was cancelled.</div>}
    <p>Status: <StatusBadge status={order.status}/> · Payment: <strong data-testid="payment-status">{PAYMENT_STATUS[order.payment_status] || order.payment_status}</strong> · Placed {when(order.created_at)}</p>
    {order.payment_notice && <div className="notice info" role="note">{order.payment_notice}</div>}
    <div className="order-grid">
      <section aria-label="Items"><h2>Items</h2>
        <table><thead><tr><th scope="col">Item</th><th scope="col">Qty</th><th scope="col">Price</th><th scope="col">Total</th></tr></thead>
          <tbody>{order.items.map(i => <tr key={i.sku}><td>{i.name}</td><td>{i.quantity}</td><td>{moneyC(i.unit_price_cents, order.currency)}</td><td>{moneyC(i.line_total_cents, order.currency)}</td></tr>)}</tbody></table>
        <dl className="totals-dl"><div><dt>Subtotal</dt><dd>{moneyC(order.subtotal_cents, order.currency)}</dd></div>
          <div><dt>{order.fulfilment === "delivery" ? "Delivery" : "Collection"}</dt><dd>{order.delivery_fee_cents ? moneyC(order.delivery_fee_cents, order.currency) : "Free"}</dd></div>
          <div className="grand"><dt>Total</dt><dd>{moneyC(order.total_cents, order.currency)}</dd></div></dl></section>
      <section aria-label="Fulfilment"><h2>{order.fulfilment === "delivery" ? "Delivery" : "Collection"}</h2>
        {order.fulfilment === "delivery" ? <p>{order.contact_name}<br/>{order.address_line}<br/>{order.city}{order.area ? `, ${order.area}` : ""} {order.postal_code}
          {order.delivery_instructions && <><br/><em>Instructions: {order.delivery_instructions}</em></>}</p>
          : <p>Collect in store. Check this page for the status of your order; the store may phone <strong>{order.contact_phone}</strong> when it is ready.</p>}
        <p className="muted-text">Contact: {order.contact_email} · {order.contact_phone}</p></section>
    </div>
    {order.payment_attempts?.length > 0 && <section aria-label="Payment history"><h2>Payment history</h2>
      <table><thead><tr><th scope="col">Reference</th><th scope="col">Method</th><th scope="col">Result</th><th scope="col">When</th></tr></thead>
        <tbody>{order.payment_attempts.map(a => <tr key={a.reference}><td>{a.reference}</td><td>{a.mode === "SIMULATED" ? "Simulated" : METHOD_LABEL[a.method] || a.method}</td>
          <td>{a.status.replace(/_/g, " ")}</td><td>{when(a.created_at)}</td></tr>)}</tbody></table></section>}
    {order.payment_status === "refund_pending" && <div className="notice warn" role="status">A payment was received for this cancelled order. The store will refund it to the account you paid from; this can take several days.</div>}
    {actionError && <div className="notice error" role="alert">{actionError}</div>}
    <div className="cart-actions">
      <Link className="shop-btn secondary" to="/shop/orders">View my orders</Link>
      <Link className="shop-btn secondary" to="/shop/products">Continue shopping</Link>
      {["confirmed", "picking", "ready", "out_for_delivery", "completed", "cancelled"].includes(order.status) &&
        <button type="button" className="shop-btn" disabled={againBusy} onClick={buyAgain}>{againBusy ? "Adding…" : "Buy again"}</button>}
      {["awaiting_payment", "payment_failed", "confirmed"].includes(order.status) && <button type="button" className="shop-btn danger" onClick={cancel}>Cancel order</button>}
    </div>
  </article>;
}

export default function Orders() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => { try { setData(await api.orders({ page, page_size: 10 })); setError(""); } catch (e) { setError(e.message); } }, [page]);
  useEffect(() => { load(); }, [load]);
  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!data) return <Loading text="Loading your orders…"/>;
  if (!data.items.length) return <EmptyState><h1>No orders yet</h1><p>When you place an order it will appear here.</p><Link className="shop-btn" to="/shop/products">Start shopping</Link></EmptyState>;
  return <div><h1>My orders</h1>
    <ul className="order-list">{data.items.map(o => <li key={o.id}>
      <div><Link to={`/shop/orders/${o.id}`}><strong>{o.reference}</strong></Link><small>{when(o.created_at)}</small></div>
      <StatusBadge status={o.status}/><span>{o.items.reduce((n, i) => n + i.quantity, 0)} items</span><strong>{moneyC(o.total_cents, o.currency)}</strong></li>)}</ul>
    <Pagination page={page} pageSize={10} total={data.total} onChange={setPage}/></div>;
}
