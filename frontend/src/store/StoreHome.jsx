import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorState, Skeleton } from "../components/ui";
import { useStore } from "../context/StoreContext";
import { api } from "../services/api";
import { ProductCard } from "./components";

function Shelf({ title, items, link }) {
  if (!items.length) return null;
  return <section className="shelf" aria-labelledby={`shelf-${title}`}>
    <div className="shelf-head"><h2 id={`shelf-${title}`}>{title}</h2>{link && <Link to={link}>See all</Link>}</div>
    <div className="product-grid">{items.map(p => <ProductCard key={p.id} product={p}/>)}</div>
  </section>;
}

export default function StoreHome() {
  const { store } = useStore();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [categories, featured, offers] = await Promise.all([
        api.categories(), api.products({ featured: true, page_size: 8 }), api.products({ on_offer: true, page_size: 8 })]);
      setData({ categories, featured: featured.items, offers: offers.items }); setError("");
    } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  return <div>
    <section className="hero" aria-labelledby="hero-title">
      <h1 id="hero-title">Fresh groceries, demonstration edition</h1>
      <p>Browse {store.name}'s sample catalogue. Stock levels come from the store database, and checkout uses simulated payment.</p>
      <Link className="shop-btn" to="/shop/products">Shop all products</Link>
    </section>
    {error ? <ErrorState error={error} onRetry={load}/> : !data ? <Skeleton className="skeleton-chart" count={2}/> : <>
      <section aria-labelledby="cat-title"><h2 id="cat-title">Shop by category</h2>
        <ul className="category-tiles">{data.categories.map(c =>
          <li key={c.id}><Link to={`/shop/products?category=${c.slug}`}><img src={`/products/${c.slug}.svg`} alt="" width="64" height="48"/>
            <span>{c.name}</span><small>{c.product_count} products</small></Link></li>)}</ul></section>
      <Shelf title="Featured products" items={data.featured} link="/shop/products?featured=true"/>
      <Shelf title="Special offers" items={data.offers} link="/shop/products?on_offer=true"/>
      {!data.featured.length && !data.offers.length && <p className="muted-text">No featured products yet.</p>}
    </>}
  </div>;
}
