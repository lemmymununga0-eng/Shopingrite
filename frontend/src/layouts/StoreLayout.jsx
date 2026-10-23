import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Heart, LogIn, LogOut, Package, ShieldCheck, ShoppingCart, Smartphone, Truck, UserRound } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { StoreProvider, useStore } from "../context/StoreContext";
import { moneyC } from "../services/format";
import MiniCart from "../store/MiniCart";
import SearchBox from "../store/SearchBox";
import { useSaved } from "../store/savedItems";
import "../store/store.css";

function UtilityBar() {
  const { store } = useStore();
  const { user, isStaff } = useAuth();
  const cities = (store.delivery_cities || []).slice(0, 4).join(", ");
  return <div className="util-bar"><div className="util-inner">
    <span><Truck size={14} aria-hidden="true"/> {store.free_delivery_over_cents ? `Free delivery over ${moneyC(store.free_delivery_over_cents, store.currency)}` : "Delivery and collection"}{cities ? ` · ${cities}` : ""}</span>
    <span className="util-links">
      <span><Smartphone size={14} aria-hidden="true"/> Pay with MTN, Airtel or card</span>
      <Link to="/shop/info/delivery">Delivery info</Link>
      <Link to="/shop/info/contact">Help &amp; contact</Link>
      {user && isStaff ? <Link to="/dashboard">Staff console</Link> : <Link to="/login?staff=1" state={{ from: { pathname: "/dashboard" } }}>Staff &amp; admin sign-in</Link>}
    </span></div></div>;
}

function Header() {
  const { store, cart, count, categories } = useStore();
  const { user, isStaff, logout } = useAuth();
  const navigate = useNavigate();
  const saved = useSaved().length;
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const menuRef = useRef(null);
  useEffect(() => {
    const close = e => menuRef.current && !menuRef.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close); return () => document.removeEventListener("mousedown", close);
  }, []);
  const name = user?.user_metadata?.full_name || user?.email || "";
  async function signOut() { setError(""); try { await logout(); setOpen(false); navigate("/shop"); } catch (e) { setError(e.message || "Could not sign out"); } }

  return <header className="store-header">
    <div className="store-bar">
      <Link to="/shop" className="store-brand" aria-label={`${store.name} home`}><img src="/store-logo.svg" alt="" width="38" height="38"/><span>{store.name}</span></Link>
      <SearchBox/>
      <nav className="store-actions" aria-label="Account and cart">
        {user ? <div className="account" ref={menuRef}>
          <button type="button" className="account-btn" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen(!open)}><UserRound size={20}/> <span>{name}</span></button>
          {open && <div className="account-menu" role="menu">
            <Link role="menuitem" to="/shop/orders" onClick={() => setOpen(false)}><Package size={16}/> My orders</Link>
            <Link role="menuitem" to="/shop/saved" onClick={() => setOpen(false)}><Heart size={16}/> Saved items</Link>
            <Link role="menuitem" to="/shop/check-website" onClick={() => setOpen(false)}><ShieldCheck size={16}/> Check a website</Link>
            {isStaff && <Link role="menuitem" to="/dashboard" onClick={() => setOpen(false)}>Staff console</Link>}
            <button role="menuitem" type="button" onClick={signOut}><LogOut size={16}/> Sign out</button>
            {error && <small className="field-error" role="alert">{error}</small>}</div>}
        </div> : <Link to="/login" state={{ from: { pathname: "/shop" } }} className="signin-link"><LogIn size={19}/> Sign in</Link>}
        <Link to="/shop/saved" className="hdr-btn" aria-label={`Saved items, ${saved}`}><Heart size={20} aria-hidden="true"/></Link>
        {/* No aria-label: the accessible name is built from the visible text (WCAG 2.5.3), "Cart: 2 K110.00" */}
        <Link to="/shop/cart" className="hdr-btn cart-link">
          <ShoppingCart size={20} aria-hidden="true"/><span className="sr-only">Cart: </span><span className="cart-count" data-testid="cart-count">{count}</span>
          <span className="cart-total">{cart ? moneyC(cart.subtotal_cents, cart.currency) : moneyC(0, store.currency)}</span></Link>
      </nav>
    </div>
    <div className="category-rail"><nav className="store-nav" aria-label="Store sections">
      <NavLink to="/shop" end>Home</NavLink><NavLink to="/shop/products" end>All products</NavLink>
      <NavLink to="/shop/products?on_offer=true" className="hot">Specials</NavLink>
      {categories.slice(0, 8).map(c => <NavLink key={c.slug} to={`/shop/products?category=${c.slug}`}>{c.name}</NavLink>)}
      <NavLink to="/shop/check-website">Check a website</NavLink>
    </nav></div>
  </header>;
}

function DemoRibbon() {
  const { store } = useStore();
  return store.is_demo ? <div className="demo-ribbon" role="note">Independent demonstration store · sample products and stock · payments are simulated</div> : null;
}

function Footer() {
  const { store, categories } = useStore();
  const { user, isStaff } = useAuth();
  return <footer className="store-footer">
    <div className="footer-grid">
      <div><h3>{store.name}</h3>
        <p>{store.is_demo ? store.disclaimer : "Fresh groceries and everyday essentials, delivered or ready to collect."}</p>
        <div className="pay-badges" aria-label="Payment methods"><span>MTN Mobile Money</span><span>Airtel Money</span><span>Visa</span><span>Mastercard</span><span>Cash on delivery</span></div></div>
      <div><h3>Shop</h3><ul><li><Link to="/shop/products">All products</Link></li><li><Link to="/shop/products?on_offer=true">Specials</Link></li>
        {categories.slice(0, 5).map(c => <li key={c.slug}><Link to={`/shop/products?category=${c.slug}`}>{c.name}</Link></li>)}</ul></div>
      <div><h3>Help</h3><nav aria-label="Store information"><ul><li><Link to="/shop/info/delivery">Delivery</Link></li><li><Link to="/shop/info/privacy">Privacy</Link></li>
        <li><Link to="/shop/info/terms">Terms</Link></li><li><Link to="/shop/info/contact">Contact</Link></li>{store.is_demo && <li><Link to="/shop/credits">Image credits</Link></li>}</ul></nav></div>
      <div><h3>Your account</h3><ul>{user ? <><li><Link to="/shop/orders">My orders</Link></li><li><Link to="/shop/saved">Saved items</Link></li></> : <li><Link to="/login">Sign in or register</Link></li>}
        <li><Link to="/shop/check-website">Check a suspicious website</Link></li></ul></div>
    </div>
    <div className="footer-base"><span>{store.is_demo ? "Not affiliated with, endorsed by, or connected to any real retailer. " : `© ${new Date().getFullYear()} ${store.legal_name || store.name}. `}Prices are in {store.currency}.</span>
      {user && isStaff ? <Link className="admin-entry" to="/dashboard"><ShieldCheck size={14} aria-hidden="true"/> Staff console</Link>
        : <Link className="admin-entry" to="/login?staff=1" state={{ from: { pathname: "/dashboard" } }}><ShieldCheck size={14} aria-hidden="true"/> Staff &amp; admin sign-in</Link>}</div>
  </footer>;
}

export default function StoreLayout() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo?.(0, 0); }, [pathname]);
  return <StoreProvider>
    <div className="store-root">
      <a href="#store-main" className="skip-link">Skip to content</a>
      <DemoRibbon/>
      <UtilityBar/>
      <Header/>
      <main id="store-main" className="store-main"><Outlet/></main>
      <Footer/>
      <MiniCart/>
    </div>
  </StoreProvider>;
}
