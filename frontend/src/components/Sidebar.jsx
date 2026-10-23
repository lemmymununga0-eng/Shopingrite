import { useState } from "react";
import { NavLink } from "react-router-dom";
import { LayoutDashboard, CreditCard, History, Bell, FlaskConical, UserRound, Settings, Info, ShieldCheck, PlusCircle, LogOut, FolderSearch, Globe, Activity, Boxes, BarChart3, Users, ScrollText, Plug, Store, ShoppingBag, Tags } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { BRAND } from "../services/format";

const STAFF = ["fraud_analyst", "security_analyst", "admin"];
const SECURITY = ["security_analyst", "admin"];
// [path, label, icon, roles allowed to see it]. Hiding a link is convenience only: the API enforces every permission.
const links = [
  ["/dashboard", "Dashboard", LayoutDashboard, STAFF],
  ["/investigations", "Investigations", FolderSearch, STAFF],
  ["/alerts", "Fraud Alerts", Bell, STAFF],
  ["/scamwatch", "ScamWatch", Globe, STAFF],
  ["/security", "Security Monitor", Activity, SECURITY],
  ["/orders", "Orders & Risk", ShoppingBag, STAFF],
  ["/inventory", "Inventory", Boxes, STAFF],
  ["/products", "Products", Tags, ["admin"]],
  ["/reports", "Reports", BarChart3, STAFF],
  ["/payment", "New Payment", PlusCircle, STAFF],
  ["/history", "Transaction History", History, STAFF],
  ["/model-demo", "PCA Model Demo", FlaskConical, STAFF],
  ["/payment-card", "Payment Card", CreditCard, STAFF],
  ["/users", "Users & Roles", Users, ["admin"]],
  ["/audit", "Audit Trail", ScrollText, SECURITY],
  ["/integrations", "Model & Integrations", Plug, STAFF],
  ["/profile", "Profile", UserRound, null],
  ["/settings", "Settings", Settings, null],
  ["/about", "About", Info, null],
];
const normalize = r => (r === "analyst" ? "fraud_analyst" : r);

export default function Sidebar({ onNavigate }) {
  const { user, role, logout } = useAuth();
  const [error, setError] = useState("");
  const name = user?.user_metadata?.full_name || user?.email || "User";
  async function signOut() { setError(""); try { await logout(); } catch (e) { setError(e.message || "Could not sign out"); } }
  return <div className="sidebar-inner">
    <div className="sidebar-brand"><ShieldCheck size={27}/><div><strong>{BRAND} <span>Console</span></strong><small>Staff security console</small></div></div>
    <nav className="sidebar-nav" aria-label="Main">{links.filter(([, , , roles]) => !roles || roles.includes(normalize(role))).map(([to, label, Icon]) =>
      <NavLink key={to} to={to} onClick={onNavigate} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
        <Icon size={19} aria-hidden="true"/><span>{label}</span></NavLink>)}</nav>
    <NavLink to="/shop" className="nav-link store-link"><Store size={19} aria-hidden="true"/><span>Customer store</span></NavLink>
    <div className="sidebar-user">
      <div className="sidebar-user-row"><span className="avatar" aria-hidden="true">{name.charAt(0).toUpperCase()}</span>
        <div><strong title={name}>{name}</strong><small>{role}</small></div></div>
      <button type="button" className="sidebar-logout" onClick={signOut}><LogOut size={16} aria-hidden="true"/> Logout</button>
      {error && <small className="field-error" role="alert">{error}</small>}
    </div>
  </div>;
}
