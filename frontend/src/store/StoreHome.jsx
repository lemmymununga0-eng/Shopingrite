import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Percent, ShieldCheck, Smartphone, Sprout, Store as StoreIcon, Truck } from "lucide-react";
import { ErrorState, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useStore } from "../context/StoreContext";
import { api } from "../services/api";
import { moneyC } from "../services/format";
import { CategoryIcon, Shelf } from "./components";
import { getViewed } from "./recent";

export default function StoreHome() {
  const { store } = useStore();
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [again, setAgain] = useState([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [categories, featured, offers] = await Promise.all([
        api.categories(), api.products({ featured: true, page_size: 8 }), api.products({ on_offer: true, page_size: 8 })]);
      const viewed = (await Promise.all(getViewed().slice(0, 6).map(id => api.product(id).catch(() => null)))).filter(Boolean);
      setData({ categories, featured: featured.items, offers: offers.items, viewed }); setError("");
    } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  // "Buy again": the products from the shopper's most recent order that are still on sale
  useEffect(() => {
    if (!user) { setAgain([]); return undefined; }
    let live = true;
    (async () => {
      try {
        const r = await api.orders?.({ page: 1, page_size: 1 });
        const ids = (Array.isArray(r?.items) ? r.items[0]?.items || [] : []).map(i => i.product_id).slice(0, 6);
        const found = (await Promise.all(ids.map(id => api.product(id).catch(() => null)))).filter(p => p && p.stock_status !== "out_of_stock");
        if (live) setAgain(found);
      } catch { /* a convenience only */ }
    })();
    return () => { live = false; };
  }, [user]);

  const free = store.free_delivery_over_cents ? moneyC(store.free_delivery_over_cents, store.currency) : null;
  return <div>
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-copy">
        <h1 id="hero-title">Everyday groceries for Zambian homes</h1>
        <p>Mealie meal, kapenta, fresh produce, household basics and more at {store.name}. Prices are in kwacha.{store.is_demo && " This is a demonstration store: stock is sample data and checkout uses simulated payment."}</p>
        <div className="hero-cta"><Link className="shop-btn accent lg" to="/shop/products">Shop all products</Link><Link className="shop-btn secondary lg" to="/shop/products?on_offer=true">See specials</Link></div>
      </div>
      <div className="hero-art" aria-hidden="true">{["🥬", "🍞", "🥛", "🍅", "🐟", "🍌"].map(e => <span key={e}>{e}</span>)}</div>
    </section>
    <div className="promo-tiles">
      <Link to="/shop/products?on_offer=true" className="promo-tile yellow"><span className="ico"><Percent size={22} aria-hidden="true"/></span><span><strong>Weekly specials</strong><small>Lower prices on everyday items</small></span></Link>
      <Link to="/shop/info/delivery" className="promo-tile"><span className="ico"><Truck size={22} aria-hidden="true"/></span><span><strong>{free ? `Free delivery over ${free}` : "Delivery or collection"}</strong><small>Home delivery or collect in store</small></span></Link>
      <Link to="/shop/info/terms" className="promo-tile"><span className="ico"><Smartphone size={22} aria-hidden="true"/></span><span><strong>Pay your way</strong><small>MTN, Airtel, card or cash on delivery</small></span></Link>
    </div>
    <div className="trust-strip" aria-label="Why shop with us">
      <div><Sprout size={26} aria-hidden="true"/><span><strong>Fresh quality</strong><small>Checked before it leaves the shelf</small></span></div>
      <div><ShieldCheck size={26} aria-hidden="true"/><span><strong>Secure payments</strong><small>We never see your card or PIN</small></span></div>
      <div><Truck size={26} aria-hidden="true"/><span><strong>Track your order</strong><small>From confirmed to delivered</small></span></div>
      <div><StoreIcon size={26} aria-hidden="true"/><span><strong>Local and trusted</strong><small>Orders are checked for fraud</small></span></div>
    </div>
    {error ? <ErrorState error={error} onRetry={load}/> : !data ? <Skeleton className="skeleton-chart" count={2}/> : <>
      <section aria-labelledby="cat-title"><h2 id="cat-title" style={{ marginTop: 26 }}>Shop by category</h2>
        <ul className="category-tiles">{data.categories.map(c =>
          <li key={c.id}><Link to={`/shop/products?category=${c.slug}`}><span className="ico"><CategoryIcon slug={c.slug}/></span>
            <span>{c.name}</span><small>{c.product_count} products</small></Link></li>)}</ul></section>
      <Shelf title="Featured products" items={data.featured} link="/shop/products?featured=true"/>
      <Shelf title={store.is_demo ? "Demo offers" : "Special offers"} items={data.offers} link="/shop/products?on_offer=true"/>
      <Shelf title="Buy again" items={again}/>
      <Shelf title="Recently viewed" items={data.viewed}/>
      {!data.featured.length && !data.offers.length && <p className="muted-text">No featured products yet.</p>}
    </>}
  </div>;
}
