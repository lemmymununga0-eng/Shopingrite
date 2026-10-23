import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Apple, Beef, Cookie, CupSoda, Croissant, Fish, Heart, Milk, Minus, Package, Plus, ShoppingCart, SprayCan, Snowflake, Sparkles, Wheat } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useStore } from "../context/StoreContext";
import { api } from "../services/api";
import { moneyC } from "../services/format";
import { toggleSaved, useSaved } from "./savedItems";

export const STOCK_LABEL = { in_stock: "In stock", low_stock: "Low stock", out_of_stock: "Out of stock" };

/** A recognisable icon per category (matched on the slug, so new categories fall back to a box). */
const ICONS = [[/produce|fruit|veg/, Apple], [/meat|poultry|beef|chicken/, Beef], [/dairy|egg|milk/, Milk], [/bakery|bread/, Croissant],
  [/beverage|drink|juice/, CupSoda], [/frozen/, Snowflake], [/staple|grain|pantry|meal|rice/, Wheat], [/household|clean/, SprayCan],
  [/personal|care|beauty/, Sparkles], [/snack|sweet|biscuit/, Cookie], [/fish|kapenta/, Fish]];
export function CategoryIcon({ slug = "", size = 26 }) {
  const Icon = (ICONS.find(([re]) => re.test(slug)) || [null, Package])[1];
  return <Icon size={size} aria-hidden="true"/>;
}

/** Availability always comes from the API record (database), never from a number in this file. */
export function StockBadge({ product }) {
  const label = product.stock_status === "low_stock" ? `Low stock · only ${product.available_quantity} left` : STOCK_LABEL[product.stock_status];
  return <span className={`stock-badge ${product.stock_status}`} data-testid="stock-badge">{label}</span>;
}

const dayMonth = iso => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export function Price({ product }) {
  const onOffer = product.offer_price_cents != null && product.offer_price_cents < product.price_cents;
  return <span className="price">
    <strong>{moneyC(product.effective_price_cents, product.currency)}</strong>
    {onOffer && <> <s className="was-price" aria-label={`was ${moneyC(product.price_cents, product.currency)}`}>{moneyC(product.price_cents, product.currency)}</s> <span className="offer-tag">{product.is_demo ? "Demo offer" : "Offer"}{product.offer_ends_on ? ` · ends ${dayMonth(product.offer_ends_on)}` : ""}</span></>}
    {product.price_status === "estimated" && <span className="est-tag" title="A demonstration price, not a verified market price">Demo price</span>}
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

/** Heart button: saved items live in this browser only. */
export function SaveButton({ product, className = "heart", withLabel = false }) {
  const saved = useSaved().includes(product.id);
  // The icon-only heart is named for the product; the labelled button's name must CONTAIN its visible text (WCAG 2.5.3)
  const name = withLabel ? (saved ? `Saved: ${product.name} (select to remove)` : `Save for later: ${product.name}`)
    : (saved ? `Remove ${product.name} from saved items` : `Save ${product.name} for later`);
  return <button type="button" className={className} aria-pressed={saved} aria-label={name}
    onClick={() => toggleSaved(product.id)}><Heart size={18} aria-hidden="true"/>{withLabel && <span>{saved ? "Saved" : "Save for later"}</span>}</button>;
}

/** Instacart-style control: "Add" turns into − qty + once the product is in the cart. */
export function CartStepper({ product, itemId, quantity, max, onChange, busy }) {
  return <div className="stepper" role="group" aria-label={`Quantity of ${product.name} in your cart`}>
    <button type="button" aria-label={`Decrease quantity of ${product.name}`} disabled={busy} onClick={() => onChange(quantity - 1)}><Minus size={16} aria-hidden="true"/></button>
    <output aria-live="polite">{quantity} in cart</output>
    <button type="button" aria-label={`Increase quantity of ${product.name}`} disabled={busy || quantity >= max} onClick={() => onChange(quantity + 1)}><Plus size={16} aria-hidden="true"/></button>
  </div>;
}

export function ProductCard({ product }) {
  const { busy, message, error, add } = useAddToCart();
  const { cartLookup, store, setCart, refreshCart } = useStore();
  const [stepBusy, setStepBusy] = useState(false);
  const [stepError, setStepError] = useState("");
  const out = product.stock_status === "out_of_stock";
  const onOffer = product.offer_price_cents != null && product.offer_price_cents < product.price_cents;
  const inCart = cartLookup?.get(product.id);
  const max = Math.max(1, Math.min(product.available_quantity, store?.max_quantity_per_line || 20));

  async function change(n) {
    setStepBusy(true); setStepError("");
    try {
      const c = n < 1 ? await api.removeCartItem(inCart.itemId) : await api.updateCartItem(inCart.itemId, n);
      if (c && Array.isArray(c.items)) setCart(c); else await refreshCart();
    } catch (e) { setStepError(e.message); await refreshCart(); }
    finally { setStepBusy(false); }
  }

  return <article className="product-card" aria-label={product.name}>
    {/* The visible ribbon text ("Offer") must be part of the link's accessible name (WCAG 2.5.3). */}
    <Link to={`/shop/products/${product.id}`} className="product-image-link" aria-label={`View ${product.name}${onOffer ? ", Offer" : ""}`}>
      <ProductImage product={product} alt=""/>
      {onOffer && <span className="img-ribbon">Offer</span>}</Link>
    <SaveButton product={product}/>
    <div className="product-body">
      {product.brand && <p className="product-brand">{product.brand}</p>}
      <h3><Link to={`/shop/products/${product.id}`}>{product.name}</Link></h3>
      <p className="product-unit">{product.pack_size || product.unit}</p>
      <Price product={product}/>
      <StockBadge product={product}/>
      <div className="card-actions">
        {inCart && !out
          ? <CartStepper product={product} itemId={inCart.itemId} quantity={inCart.quantity} max={max} busy={stepBusy} onChange={change}/>
          : <button type="button" className="shop-btn" disabled={out || busy} onClick={() => add(product, 1)}
              aria-label={out ? `Unavailable: ${product.name} is out of stock` : `Add to cart: ${product.name}`}>
              <ShoppingCart size={16} aria-hidden="true"/> {out ? "Unavailable" : busy ? "Adding…" : "Add to cart"}</button>}
      </div>
      <p className="status-line" role="status" aria-live="polite">{message}</p>
      {(error || stepError) && <p className="field-error" role="alert">{error || stepError}</p>}
    </div>
  </article>;
}

/** Product photo. Falls back to the category illustration if a photo file is missing. */
export function ProductImage({ product, alt, ...rest }) {
  return <img src={product.image_ref} alt={alt ?? (product.image_alt || product.name)} loading="lazy" width="640" height="480"
    className={product.image_status === "placeholder" ? "img-placeholder" : undefined} {...rest}
    onError={e => { const fb = `/products/${product.category_slug}.svg`; if (!e.currentTarget.src.endsWith(fb)) e.currentTarget.src = fb; }}/>;
}

export function QuantityInput({ id, value, onChange, max, min = 1, label = "Quantity" }) {
  const clamp = n => Math.max(min, Math.min(max ?? 1000, n));
  return <div className="qty" role="group" aria-label={`${label} selector`}>
    <button type="button" aria-label="Decrease quantity" onClick={() => onChange(clamp(value - 1))} disabled={value <= min}>−</button>
    <input id={id} type="number" inputMode="numeric" min={min} max={max} value={value} aria-label={label}
      onChange={e => { const n = Number(e.target.value); if (Number.isFinite(n) && n >= 0) onChange(Math.floor(n)); }}/>
    <button type="button" aria-label="Increase quantity" onClick={() => onChange(clamp(value + 1))} disabled={max != null && value >= max}>+</button>
  </div>;
}

/** A horizontally scrolling row of products (home page shelves). */
export function Shelf({ title, items, link, linkLabel = "See all" }) {
  if (!items?.length) return null;
  const id = `shelf-${title}`;
  return <section className="shelf" aria-labelledby={id}>
    <div className="shelf-head"><h2 id={id}>{title}</h2>{link && <Link to={link}>{linkLabel} →</Link>}</div>
    <div className="shelf-row">{items.map(p => <ProductCard key={p.id} product={p}/>)}</div></section>;
}
