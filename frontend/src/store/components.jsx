import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ShoppingCart } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useStore } from "../context/StoreContext";
import { api } from "../services/api";
import { moneyC } from "../services/format";

export const STOCK_LABEL = { in_stock: "In stock", low_stock: "Low stock", out_of_stock: "Out of stock" };

/** Availability always comes from the API record (database), never from a number in this file. */
export function StockBadge({ product }) {
  const label = product.stock_status === "low_stock" ? `Low stock · only ${product.available_quantity} left` : STOCK_LABEL[product.stock_status];
  return <span className={`stock-badge ${product.stock_status}`} data-testid="stock-badge">{label}</span>;
}

export function Price({ product }) {
  const onOffer = product.offer_price_cents != null && product.offer_price_cents < product.price_cents;
  return <span className="price">
    <strong>{moneyC(product.effective_price_cents, product.currency)}</strong>
    {onOffer && <> <s className="was-price" aria-label={`was ${moneyC(product.price_cents, product.currency)}`}>{moneyC(product.price_cents, product.currency)}</s> <span className="offer-tag">Special</span></>}
  </span>;
}

/** Add-to-cart behaviour shared by the card and the detail page. Sends signed-out shoppers to sign in first. */
export function useAddToCart() {
  const { user } = useAuth();
  const { refreshCart } = useStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [state, setState] = useState({ busy: false, message: "", error: "" });
  async function add(product, quantity = 1) {
    if (!user) { navigate("/login", { state: { from: location } }); return false; }
    setState({ busy: true, message: "", error: "" });
    try {
      await api.addToCart(product.id, quantity);
      await refreshCart();
      setState({ busy: false, message: `Added ${quantity} × ${product.name} to your cart.`, error: "" });
      return true;
    } catch (e) {
      setState({ busy: false, message: "", error: e.message });
      return false;
    }
  }
  return { ...state, add };
}

export function ProductCard({ product }) {
  const { busy, message, error, add } = useAddToCart();
  const out = product.stock_status === "out_of_stock";
  return <article className="product-card" aria-label={product.name}>
    <Link to={`/shop/products/${product.id}`} className="product-image-link" aria-label={`View ${product.name}`}>
      <img src={product.image_ref} alt="" loading="lazy" width="400" height="300"/></Link>
    <div className="product-body">
      <h3><Link to={`/shop/products/${product.id}`}>{product.name}</Link></h3>
      <p className="product-unit">{product.unit}</p>
      <Price product={product}/>
      <StockBadge product={product}/>
      <button type="button" className="shop-btn" disabled={out || busy} onClick={() => add(product, 1)}
        aria-label={out ? `${product.name} is out of stock` : `Add ${product.name} to cart`}>
        <ShoppingCart size={16} aria-hidden="true"/> {out ? "Unavailable" : busy ? "Adding…" : "Add to cart"}</button>
      <p className="status-line" role="status" aria-live="polite">{message}</p>
      {error && <p className="field-error" role="alert">{error}</p>}
    </div>
  </article>;
}

export function QuantityInput({ id, value, onChange, max, min = 1, label = "Quantity" }) {
  const clamp = n => Math.max(min, Math.min(max ?? 1000, n));
  return <div className="qty" role="group" aria-label={label}>
    <button type="button" aria-label="Decrease quantity" onClick={() => onChange(clamp(value - 1))} disabled={value <= min}>−</button>
    <input id={id} type="number" inputMode="numeric" min={min} max={max} value={value} aria-label={label}
      onChange={e => { const n = Number(e.target.value); if (Number.isFinite(n) && n >= 0) onChange(Math.floor(n)); }}/>
    <button type="button" aria-label="Increase quantity" onClick={() => onChange(clamp(value + 1))} disabled={max != null && value >= max}>+</button>
  </div>;
}
