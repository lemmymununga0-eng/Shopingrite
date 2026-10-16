import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { LogIn, LogOut, Package, Search, ShieldCheck, ShoppingCart, UserRound } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { StoreProvider, useStore } from "../context/StoreContext";
import "../store/store.css";

function Header() {
  const { store, count } = useStore();
  const { user, isStaff, logout } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const menuRef = useRef(null);
  useEffect(() => {
    const close = e => menuRef.current && !menuRef.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close); return () => document.removeEventListener("mousedown", close);
  }, []);
  const name = user?.user_metadata?.full_name || user?.email || "";

  function search(e) { e.preventDefault(); navigate(`/shop/products${q.trim() ? `?search=${encodeURIComponent(q.trim())}` : ""}`); }
  async function signOut() { setError(""); try { await logout(); setOpen(false); navigate("/shop"); } catch (e) { setError(e.message || "Could not sign out"); } }

  return <header className="store-header">
    <div className="store-bar">
      <Link to="/shop" className="store-brand" aria-label={`${store.name} home`}><img src="/store-logo.svg" alt="" width="36" height="36"/><span>{store.name}</span></Link>
      <form className="store-search" onSubmit={search} role="search" aria-label="Search products">
        <label htmlFor="store-q" className="sr-only">Search products</label>
        <input id="store-q" type="search" placeholder="Search groceries" value={q} maxLength={60} onChange={e => setQ(e.target.value)}/>
        <button type="submit" aria-label="Search"><Search size={18}/></button></form>
      <nav className="store-actions" aria-label="Account and cart">
        <Link to="/shop/cart" className="cart-link" aria-label={`Cart, ${count} item${count === 1 ? "" : "s"}`}><ShoppingCart size={21}/><span className="cart-count" data-testid="cart-count">{count}</span></Link>
        {user ? <div className="account" ref={menuRef}>
          <button type="button" className="account-btn" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen(!open)}><UserRound size={19}/> <span>{name}</span></button>
          {open && <div className="account-menu" role="menu">
            <Link role="menuitem" to="/shop/orders" onClick={() => setOpen(false)}><Package size={15}/> My orders</Link>
            <Link role="menuitem" to="/shop/check-website" onClick={() => setOpen(false)}><ShieldCheck size={15}/> Check a website</Link>
            {isStaff && <Link role="menuitem" to="/dashboard" onClick={() => setOpen(false)}>Staff console</Link>}
            <button role="menuitem" type="button" onClick={signOut}><LogOut size={15}/> Sign out</button>
            {error && <small className="field-error" role="alert">{error}</small>}</div>}
        </div> : <Link to="/login" state={{ from: { pathname: "/shop" } }} className="signin-link"><LogIn size={18}/> Sign in</Link>}
      </nav>
    </div>
    <nav className="store-nav" aria-label="Store sections">
      <NavLink to="/shop" end>Home</NavLink><NavLink to="/shop/products">All products</NavLink>
      <NavLink to="/shop/products?on_offer=true">Specials</NavLink><NavLink to="/shop/check-website">Check a website</NavLink>
    </nav>
  </header>;
}

export default function StoreLayout() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo?.(0, 0); }, [pathname]);
  return <StoreProvider>
    <a href="#store-main" className="skip-link">Skip to content</a>
    <div className="demo-ribbon" role="note">Independent demonstration store · sample products and stock · payments are simulated</div>
    <Header/>
    <main id="store-main" className="store-main"><Outlet/></main>
    <Footer/>
  </StoreProvider>;
}

function Footer() {
  const { store } = useStore();
  return <footer className="store-footer"><p>{store.disclaimer}</p>
    <p>Not affiliated with, endorsed by, or connected to any real retailer. Currency: {store.currency}.</p></footer>;
}
