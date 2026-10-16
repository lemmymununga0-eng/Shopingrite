import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ShoppingCart } from "lucide-react";
import { ErrorState, Loading } from "../components/ui";
import { useStore } from "../context/StoreContext";
import { api } from "../services/api";
import { Price, QuantityInput, StockBadge, useAddToCart } from "./components";

export default function ProductDetail() {
  const { id } = useParams();
  const { store } = useStore();
  const [product, setProduct] = useState(null);
  const [error, setError] = useState("");
  const [qty, setQty] = useState(1);
  const { busy, message, error: addError, add } = useAddToCart();

  const load = useCallback(async () => {
    try { setProduct(await api.product(id)); setError(""); } catch (e) { setError(e.message); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!product) return <Loading text="Loading product…"/>;
  const out = product.stock_status === "out_of_stock";
  const max = Math.min(product.available_quantity, store.max_quantity_per_line || 20);
  const invalid = qty < 1 || qty > max;
  return <article className="product-detail" aria-labelledby="pd-title">
    <nav aria-label="Breadcrumb" className="breadcrumb"><Link to="/shop/products">Products</Link> / <Link to={`/shop/products?category=${product.category_slug}`}>{product.category_name}</Link></nav>
    <div className="pd-grid">
      <img src={product.image_ref} alt={product.name} width="400" height="300"/>
      <div>
        <h1 id="pd-title">{product.name}</h1>
        <p className="product-unit">{product.unit} · SKU {product.sku}</p>
        <Price product={product}/> <StockBadge product={product}/>
        <p>{product.description}</p>
        {out ? <p className="notice info" role="status">This item is out of stock right now, so it cannot be added to your cart.</p> : <>
          <label htmlFor="pd-qty" className="qty-label">Quantity</label>
          <QuantityInput id="pd-qty" value={qty} onChange={setQty} max={max}/>
          {invalid && <p className="field-error" role="alert">Choose between 1 and {max}.</p>}
          <button type="button" className="shop-btn" disabled={busy || invalid} onClick={() => add(product, qty).then(ok => ok && load())}>
            <ShoppingCart size={16} aria-hidden="true"/> {busy ? "Adding…" : "Add to cart"}</button></>}
        <p className="status-line" role="status" aria-live="polite">{message}</p>
        {addError && <p className="field-error" role="alert">{addError}</p>}
        <p className="muted-text">Demonstration product. Stock shown is sample data held in the store database.</p>
      </div>
    </div>
  </article>;
}
