import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { RotateCcw, ShieldCheck, ShoppingCart, Truck } from "lucide-react";
import { ErrorState, Loading } from "../components/ui";
import { useStore } from "../context/StoreContext";
import { api } from "../services/api";
import { moneyC } from "../services/format";
import { Price, ProductCard, ProductImage, QuantityInput, SaveButton, StockBadge, useAddToCart } from "./components";
import { rememberViewed } from "./recent";

const SOURCE_LABEL = { observed: "Seen on a retailer website", estimated: "Demonstration estimate", verified: "Verified" };

export default function ProductDetail() {
  const { id } = useParams();
  const { store, openDrawer } = useStore();
  const [product, setProduct] = useState(null);
  const [error, setError] = useState("");
  const [qty, setQty] = useState(1);
  const [related, setRelated] = useState([]);
  const { busy, message, error: addError, add } = useAddToCart();

  const load = useCallback(async () => {
    try { setProduct(await api.product(id)); setError(""); } catch (e) { setError(e.message); }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!product) return;
    rememberViewed(product.id);
    api.products({ category: product.category_slug, page_size: 5 })
      .then(r => setRelated(r.items.filter(p => p.id !== product.id).slice(0, 4))).catch(() => setRelated([]));
  }, [product?.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!product) return <Loading text="Loading product…"/>;
  const out = product.stock_status === "out_of_stock";
  const max = Math.min(product.available_quantity, store.max_quantity_per_line || 20);
  const invalid = qty < 1 || qty > max;
  const free = store.free_delivery_over_cents ? moneyC(store.free_delivery_over_cents, store.currency) : null;
  return <article className="product-detail" aria-labelledby="pd-title">
    <nav aria-label="Breadcrumb" className="breadcrumb"><Link to="/shop/products">Products</Link> / <Link to={`/shop/products?category=${product.category_slug}`}>{product.category_name}</Link></nav>
    <div className="pd-grid">
      <div className="pd-media"><ProductImage product={product} alt={product.name}/></div>
      <div className="pd-info">
        {product.brand && <p className="product-brand">{product.brand}</p>}
        <h1 id="pd-title">{product.name}</h1>
        <p className="product-unit">{product.pack_size || product.unit} · SKU {product.sku}</p>
        <p className="pd-desc">{product.description}</p>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}><SaveButton product={product} className="shop-btn secondary" withLabel/></div>
        {product.is_demo && <details className="provenance"><summary>Price and photo information</summary>
          <dl>
            <dt>Price basis</dt><dd>{SOURCE_LABEL[product.price_status] || product.price_status}</dd>
            {product.price_source_url && <><dt>Source</dt><dd><a href={product.price_source_url} target="_blank" rel="noopener noreferrer">{product.price_source_name}</a>{product.price_checked_on ? `, checked ${product.price_checked_on}` : ""}</dd></>}
            <dt>Photo</dt><dd>{product.image_status === "licensed"
              ? <>Generic photograph, {product.image_license}. <a href={product.image_source.split(" - ")[0]} target="_blank" rel="noopener noreferrer">Credit</a></>
              : "Category illustration: a correct product photograph has not been added yet."}</dd>
          </dl>
          <p className="muted-text">Prices and stock are demonstration data. This store is not connected to any retailer.</p></details>}
      </div>
      <aside className="buy-box" aria-label="Buy this product">
        <Price product={product}/> <StockBadge product={product}/>
        {out ? <p className="notice info" role="status">This item is out of stock right now, so it cannot be added to your cart.</p> : <>
          <div><label htmlFor="pd-qty" className="qty-label">Quantity</label>
            <QuantityInput id="pd-qty" value={qty} onChange={setQty} max={max}/></div>
          {invalid && <p className="field-error" role="alert">Choose between 1 and {max}.</p>}
          <button type="button" className="shop-btn lg block" disabled={busy || invalid}
            onClick={() => add(product, qty).then(ok => { if (ok) { load(); openDrawer(); } })}>
            <ShoppingCart size={18} aria-hidden="true"/> {busy ? "Adding…" : "Add to cart"}</button></>}
        <p className="status-line" role="status" aria-live="polite">{message}</p>
        {addError && <p className="field-error" role="alert">{addError}</p>}
        <div className="deliver-note">
          <div><Truck size={18} aria-hidden="true"/><span>{free ? `Free delivery over ${free}.` : "Delivery or collection."} Choose at checkout.</span></div>
          <div><ShieldCheck size={18} aria-hidden="true"/><span>Pay securely by mobile money or card.</span></div>
          <div><RotateCcw size={18} aria-hidden="true"/><span>Cancel until we start preparing your order.</span></div>
        </div>
      </aside>
    </div>
    {related.length > 0 && <section className="shelf" aria-labelledby="related-title"><div className="shelf-head"><h2 id="related-title">Related products</h2></div>
      <div className="product-grid">{related.map(p => <ProductCard key={p.id} product={p}/>)}</div></section>}
  </article>;
}
