import { useState } from "react";
import { NavLink } from "react-router-dom";
import { LayoutDashboard, CreditCard, History, Bell, FlaskConical, UserRound, Settings, Info, ShieldCheck, PlusCircle, LogOut } from "lucide-react";
import { useAuth } from "../context/AuthContext";

const links = [
  ["/dashboard", "Dashboard", LayoutDashboard],
  ["/payment-card", "Payment Card", CreditCard],
  ["/payment", "New Payment", PlusCircle],
  ["/model-demo", "PCA Model Demo", FlaskConical],
  ["/alerts", "Fraud Alerts", Bell],
  ["/history", "Transaction History", History],
  ["/profile", "Profile", UserRound],
  ["/settings", "Settings", Settings],
  ["/about", "About", Info],
];

export default function Sidebar({ onNavigate }) {
  const { user, role, logout } = useAuth();
  const [error, setError] = useState("");
  const name = user?.user_metadata?.full_name || user?.email || "User";
  async function signOut() { setError(""); try { await logout(); } catch (e) { setError(e.message || "Could not sign out"); } }
  return <div className="sidebar-inner">
    <div className="sidebar-brand"><ShieldCheck size={27}/><div><strong>Shoprite <span>FraudGuard</span></strong><small>Smart Payment Security.</small></div></div>
    <nav className="sidebar-nav" aria-label="Main">{links.map(([to, label, Icon]) =>
      <NavLink key={to} to={to} onClick={onNavigate} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
        <Icon size={19} aria-hidden="true"/><span>{label}</span></NavLink>)}</nav>
    <div className="sidebar-user">
      <div className="sidebar-user-row"><span className="avatar" aria-hidden="true">{name.charAt(0).toUpperCase()}</span>
        <div><strong title={name}>{name}</strong><small>{role}</small></div></div>
      <button type="button" className="sidebar-logout" onClick={signOut}><LogOut size={16} aria-hidden="true"/> Logout</button>
      {error && <small className="field-error" role="alert">{error}</small>}
    </div>
  </div>;
}
