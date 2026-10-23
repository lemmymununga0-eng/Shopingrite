import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Heart } from "lucide-react";
import { Loading } from "../components/ui";
import { api } from "../services/api";
import { ProductCard } from "./components";
import { useSaved } from "./savedItems";

/** Products the shopper hearted. Kept in this browser only; prices and stock are always read fresh from the server. */
export default function Saved() {
  const ids = useSaved();
  const [products, setProducts] = useState(null);
  useEffect(() => {
    let live = true;
    Promise.all(ids.map(id => api.product(id).catch(() => null)))
      .then(list => live && setProducts(list.filter(Boolean)));
    return () => { live = false; };
  }, [ids.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (ids.length === 0) return <div className="empty-cta"><Heart size={34} aria-hidden="true"/><h1>No saved items yet</h1>
    <p>Tap the heart on any product to keep it here for later.</p><Link className="shop-btn" to="/shop/products">Browse products</Link></div>;
  if (!products) return <Loading text="Loading your saved items…"/>;
  return <div><h1>Saved items</h1>
    <p className="muted-text">{products.length} product{products.length === 1 ? "" : "s"}. Saved on this device only.</p>
    <div className="product-grid">{products.map(p => <ProductCard key={p.id} product={p}/>)}</div></div>;
}
