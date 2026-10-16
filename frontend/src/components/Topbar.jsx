import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Bell, ChevronDown, LogOut, Menu, Search, ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { money } from "../services/format";
import { getPrefs } from "../services/prefs";
import { BRAND } from "../services/format";

export const PAGE_TITLES = {
  "/dashboard": "Dashboard", "/payment-card": "Payment Card", "/payment": "New Payment", "/model-demo": "PCA Model Demo",
  "/alerts": "Fraud Alerts", "/history": "Transaction History", "/profile": "Profile", "/settings": "Settings", "/about": "About",
  "/investigations": "Investigation Centre", "/scamwatch": "ScamWatch", "/security": "Security Monitor", "/inventory": "Inventory & Orders",
  "/reports": "Reports & Business Impact", "/users": "Users & Roles", "/audit": "Audit Trail", "/integrations": "Model & Integrations",
};
export const titleFor = path => PAGE_TITLES[path] || (path.startsWith("/transactions/") ? "Transaction Details" : BRAND);

function useOutsideClose(ref, onClose) {
  useEffect(() => {
    const click = e => ref.current && !ref.current.contains(e.target) && onClose();
    const key = e => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", click); document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", click); document.removeEventListener("keydown", key); };
  }, [ref, onClose]);
}

function NotificationMenu() {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState({ total: 0, items: [], error: "" });
  const ref = useRef(null);
  const enabled = getPrefs().alertBadge;
  useOutsideClose(ref, () => setOpen(false));

  async function load() {
    try { const d = await api.alerts({ review_status: "new", page_size: 5 }); setState({ total: d.total, items: d.items, error: "" }); }
    catch (e) { setState(s => ({ ...s, error: e.message })); }
  }
  useEffect(() => { if (enabled) load(); }, [enabled]);
  if (!enabled) return null;

  return <div ref={ref} className="topbar-actions">
    <button className="icon-button" aria-haspopup="true" aria-expanded={open} aria-label={`Notifications${state.total ? `, ${state.total} unreviewed alerts` : ""}`}
      onClick={() => { setOpen(!open); if (!open) load(); }}>
      <Bell size={18}/>{state.total > 0 && <span className="badge-count" aria-hidden="true">{state.total > 99 ? "99+" : state.total}</span>}</button>
    {open && <div className="popover" role="region" aria-label="Notifications">
      <h3>Alerts awaiting review</h3>
      {state.error && <p className="muted-text" role="alert">{state.error}</p>}
      {!state.error && !state.items.length && <p className="muted-text">No alerts awaiting review.</p>}
      {state.items.map(a => <Link key={a.id} to="/alerts" onClick={() => setOpen(false)}>
        <strong>#{a.transaction_reference}</strong> · {a.risk} risk · {money(a.amount)}</Link>)}
      <Link to="/alerts" onClick={() => setOpen(false)}><strong>Open Fraud Alerts</strong></Link>
    </div>}
  </div>;
}

function UserMenu() {
  const { user, logout, role } = useAuth();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const ref = useRef(null);
  useOutsideClose(ref, () => setOpen(false));
  const name = user?.user_metadata?.full_name || user?.email || "User";
  async function signOut() { setError(""); try { await logout(); } catch (e) { setError(e.message || "Could not sign out"); } }
  return <div ref={ref} className="topbar-actions">
    <button className="user-menu-trigger" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
      <span className="avatar" aria-hidden="true">{name.charAt(0).toUpperCase()}</span>
      <span className="user-details"><strong>{name}</strong><small>{role}</small></span><ChevronDown size={15} aria-hidden="true"/></button>
    {open && <div className="popover" role="menu" style={{ width: 190 }}>
      <Link role="menuitem" to="/profile" onClick={() => setOpen(false)}>Profile</Link>
      <Link role="menuitem" to="/settings" onClick={() => setOpen(false)}>Settings</Link>
      <button role="menuitem" className="popover-item sidebar-logout" style={{ border: 0, borderRadius: 0 }} onClick={signOut}><LogOut size={15}/> Logout</button>
    </div>}
    {error && <span className="topbar-error" role="alert">{error}</span>}
  </div>;
}

export default function Topbar({ onMenuClick }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  function search(e) {
    e.preventDefault();
    const term = q.trim();
    if (term) navigate(`/history?search=${encodeURIComponent(term)}`);
  }
  return <header className="topbar">
    <button className="mobile-menu" onClick={onMenuClick} aria-label="Open navigation"><Menu size={23}/></button>
    <div className="topbar-brand"><ShieldCheck size={29}/><strong>{BRAND} <span>Console</span></strong></div>
    <div className="topbar-title"><small>{BRAND} staff console</small><strong>{titleFor(pathname)}</strong></div>
    <form className="topbar-search" role="search" onSubmit={search}>
      <Search size={15} aria-hidden="true"/><input aria-label="Search transactions by reference" placeholder="Search reference…" maxLength={40}
        value={q} onChange={e => setQ(e.target.value)}/></form>
    <NotificationMenu/><UserMenu/>
  </header>;
}
