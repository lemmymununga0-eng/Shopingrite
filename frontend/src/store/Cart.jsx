import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Trash2 } from "lucide-react";
import { EmptyState, ErrorState, Loading } from "../components/ui";
import { useStore } from "../context/StoreContext";
import { api } from "../services/api";
import { moneyC } from "../services/format";
import { QuantityInput } from "./components";

export default function Cart() {
  const { store, setCart, refreshCart } = useStore();
  const navigate = useNavigate();
  const [cart, setLocal] = useState(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyId, setBusyId] = useState(null);

  const apply = useCallback(c => { setLocal(c); setCart(c); }, [setCart]);
  const load = useCallback(async () => {
    try { apply(await api.cart()); setError(""); } catch (e) { setError(e.message); }
  }, [apply]);
  useEffect(() => { load(); }, [load]);

  async function run(id, fn) {
    setActionError(""); setBusyId(id);
    try { apply(await fn()); } catch (e) { setActionError(e.message); await load(); }
    finally { setBusyId(null); }
  }

  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!cart) return <Loading text="Loading your cart…"/>;
  if (cart.items.length === 0) return <EmptyState><h1>Your cart is empty</h1><p>Add something fresh to get started.</p>
    <Link className="shop-btn" to="/shop/products">Continue shopping</Link></EmptyState>;

  const free = store.free_delivery_over_cents;
  return <div>
    <h1>Your cart</h1>
    {actionError && <div className="notice error" role="alert">{actionError}</div>}
    {cart.has_issues && <div className="notice error" role="alert">Some items need attention before you can check out.</div>}
    <ul className="cart-lines">{cart.items.map(l => <li key={l.item_id} className={`cart-line${l.issue ? " has-issue" : ""}`}>
      <img src={l.product.image_ref} alt="" width="72" height="54"/>
      <div className="cart-info"><Link to={`/shop/products/${l.product.id}`}>{l.product.name}</Link>
        <small>{moneyC(l.product.effective_price_cents, cart.currency)} · {l.product.unit}</small>
        {l.issue && <p className="field-error" role="alert">{l.issue_message}</p>}</div>
      <QuantityInput value={l.quantity} max={Math.max(1, Math.min(l.product.available_quantity, store.max_quantity_per_line || 20))}
        label={`Quantity of ${l.product.name}`}
        onChange={n => n !== l.quantity && (n < 1 ? null : run(l.item_id, () => api.updateCartItem(l.item_id, n)))}/>
      <strong className="line-total">{moneyC(l.line_total_cents, cart.currency)}</strong>
      <button type="button" className="icon-btn" aria-label={`Remove ${l.product.name}`} disabled={busyId === l.item_id}
        onClick={() => run(l.item_id, () => api.removeCartItem(l.item_id))}><Trash2 size={17}/></button>
    </li>)}</ul>
    <section className="totals" aria-label="Order totals">
      <dl>
        <div><dt>Subtotal</dt><dd>{moneyC(cart.subtotal_cents, cart.currency)}</dd></div>
        <div><dt>Delivery</dt><dd>{cart.delivery_fee_cents ? moneyC(cart.delivery_fee_cents, cart.currency) : "Free"}</dd></div>
        <div className="grand"><dt>Total if delivered</dt><dd>{moneyC(cart.subtotal_cents + cart.delivery_fee_cents, cart.currency)}</dd></div>
      </dl>
      <p className="muted-text">{cart.delivery_fee_note}{free ? "" : ""}</p>
      <div className="cart-actions">
        <Link className="shop-btn secondary" to="/shop/products">Continue shopping</Link>
        <button type="button" className="shop-btn" disabled={cart.has_issues}
          onClick={async () => { const c = await refreshCart(); if (c && !c.has_issues) navigate("/shop/checkout"); else load(); }}>Proceed to checkout</button>
      </div>
    </section>
  </div>;
}
