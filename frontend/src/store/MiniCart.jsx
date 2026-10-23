import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { X } from "lucide-react";
import { useStore } from "../context/StoreContext";
import { moneyC } from "../services/format";
import { FreeDelivery } from "./FreeDelivery";

/** Slide-in cart opened after adding from a product page, so shoppers can keep browsing or go straight to checkout. */
export default function MiniCart() {
  const { cart, store, drawerOpen, closeDrawer } = useStore();
  const closeBtn = useRef(null);
  useEffect(() => {
    if (!drawerOpen) return undefined;
    closeBtn.current?.focus();
    const onKey = e => e.key === "Escape" && closeDrawer();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen, closeDrawer]);
  if (!drawerOpen) return null;
  const items = cart?.items || [];
  return <>
    <div className="drawer-backdrop" onClick={closeDrawer} aria-hidden="true"/>
    <aside className="drawer" role="dialog" aria-modal="true" aria-label="Your cart">
      <header><h2>Your cart ({cart?.item_count || 0})</h2>
        <button type="button" className="icon-btn" ref={closeBtn} onClick={closeDrawer} aria-label="Close cart"><X size={20} aria-hidden="true"/></button></header>
      {items.length === 0 ? <div className="empty-cta"><p>Your cart is empty.</p><Link className="shop-btn" to="/shop/products" onClick={closeDrawer}>Start shopping</Link></div> : <>
        <ul>{items.map(l => <li key={l.item_id}>
          <img src={l.product.image_ref} alt="" width="60" height="45"/>
          <span>{l.product.name}<br/><small>{l.quantity} × {moneyC(l.product.effective_price_cents, cart.currency)}</small></span>
          <strong>{moneyC(l.line_total_cents, cart.currency)}</strong></li>)}</ul>
        <footer>
          <FreeDelivery subtotal={cart.subtotal_cents} threshold={store.free_delivery_over_cents} currency={cart.currency}/>
          <dl><div className="grand"><dt>Subtotal</dt><dd>{moneyC(cart.subtotal_cents, cart.currency)}</dd></div></dl>
          <Link className="shop-btn lg block" to="/shop/checkout" onClick={closeDrawer}>Go to checkout</Link>
          <Link className="shop-btn secondary block" to="/shop/cart" onClick={closeDrawer}>View full cart</Link>
        </footer></>}
    </aside>
  </>;
}
