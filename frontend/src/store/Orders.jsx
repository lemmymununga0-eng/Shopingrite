import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle2 } from "lucide-react";
import { EmptyState, ErrorState, Loading, Pagination } from "../components/ui";
import { api } from "../services/api";
import { moneyC, when } from "../services/format";

export const ORDER_STATUS = { confirmed: "Confirmed", picking: "Being picked", ready: "Ready", out_for_delivery: "Out for delivery", completed: "Completed", cancelled: "Cancelled" };
const StatusBadge = ({ status }) => <span className={`order-status ${status}`}>{ORDER_STATUS[status] || status}</span>;

/** One order: used for the confirmation page (after checkout) and the order-details page. */
export function OrderView({ confirmation = false }) {
  const { id } = useParams();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const load = useCallback(async () => { try { setOrder(await api.order(id)); setError(""); } catch (e) { setError(e.message); } }, [id]);
  useEffect(() => { load(); }, [load]);

  async function cancel() {
    setActionError("");
    try { setOrder(await api.cancelOrder(id)); } catch (e) { setActionError(e.message); }
  }
  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!order) return <Loading text="Loading order…"/>;
  return <article aria-labelledby="order-title">
    {confirmation && <div className="notice success confirm-banner" role="status"><CheckCircle2 size={20} aria-hidden="true"/> <strong>Thank you. Your demonstration order was placed.</strong></div>}
    <h1 id="order-title">Order <span data-testid="order-ref">{order.reference}</span></h1>
    <p>Status: <StatusBadge status={order.status}/> · Placed {when(order.created_at)}</p>
    {order.payment_notice && <div className="notice info" role="note">{order.payment_notice}</div>}
    <div className="order-grid">
      <section aria-label="Items"><h2>Items</h2>
        <table><thead><tr><th scope="col">Item</th><th scope="col">Qty</th><th scope="col">Price</th><th scope="col">Total</th></tr></thead>
          <tbody>{order.items.map(i => <tr key={i.sku}><td>{i.name}</td><td>{i.quantity}</td><td>{moneyC(i.unit_price_cents, order.currency)}</td><td>{moneyC(i.line_total_cents, order.currency)}</td></tr>)}</tbody></table>
        <dl className="totals-dl"><div><dt>Subtotal</dt><dd>{moneyC(order.subtotal_cents, order.currency)}</dd></div>
          <div><dt>{order.fulfilment === "delivery" ? "Delivery" : "Collection"}</dt><dd>{order.delivery_fee_cents ? moneyC(order.delivery_fee_cents, order.currency) : "Free"}</dd></div>
          <div className="grand"><dt>Total</dt><dd>{moneyC(order.total_cents, order.currency)}</dd></div></dl></section>
      <section aria-label="Fulfilment"><h2>{order.fulfilment === "delivery" ? "Delivery" : "Collection"}</h2>
        {order.fulfilment === "delivery" ? <p>{order.contact_name}<br/>{order.address_line}<br/>{order.city} {order.postal_code}</p>
          : <p>Collect in store. We will email <strong>{order.contact_email}</strong> when it is ready.</p>}
        <p className="muted-text">Contact: {order.contact_email} · {order.contact_phone}</p></section>
    </div>
    {actionError && <div className="notice error" role="alert">{actionError}</div>}
    <div className="cart-actions">
      <Link className="shop-btn secondary" to="/shop/orders">View my orders</Link>
      <Link className="shop-btn secondary" to="/shop/products">Continue shopping</Link>
      {order.status === "confirmed" && <button type="button" className="shop-btn danger" onClick={cancel}>Cancel order</button>}
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
