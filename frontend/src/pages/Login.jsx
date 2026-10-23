import { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { ShieldCheck, LockKeyhole, Mail, ShoppingCart, ArrowLeft, ScrollText, ShoppingBag } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { EMAIL_RE, Field, PasswordInput } from "../components/forms";
import { api } from "../services/api";
import { BRAND } from "../services/format";

const DEMO_ACCOUNTS = [["customer@example.com", "Customer (store)"], ["fraud.analyst@example.com", "Fraud analyst"], ["security.analyst@example.com", "Security analyst"], ["admin@example.com", "Administrator"]];
const DEMO_PASSWORD = "DemoPass!2026";

export default function Login() {
  const { user, role, login, loginLocal, logout, configured } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const staffMode = new URLSearchParams(location.search).get("staff") === "1";      // "Staff & admin sign-in" from the store
  const home = staffMode || role !== "customer" ? "/dashboard" : "/shop";
  const from = location.state?.from?.pathname || home;
  const [localOn, setLocalOn] = useState(false);
  const [adminOnly, setAdminOnly] = useState(false);
  const [shop, setShop] = useState({ name: "", is_demo: false });
  useEffect(() => {
    Promise.resolve(api.storeInfo?.()).then(d => {
      setLocalOn(!configured && Boolean(d?.local_auth_enabled)); setAdminOnly(Boolean(d?.console_admin_only));
      if (d) setShop({ name: d.name || "", is_demo: Boolean(d.is_demo) });
    }).catch(() => {});
  }, [configured]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (user && !(staffMode && role === "customer")) return <Navigate to={from} replace />;

  async function submit(e) {
    e.preventDefault(); setError("");
    const errs = {};
    if (!email.trim()) errs.email = "Enter your email address"; else if (!EMAIL_RE.test(email.trim())) errs.email = "Enter a valid email address";
    if (!password) errs.password = "Enter your password";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      let signedIn;
      if (!configured && localOn) signedIn = await loginLocal(email.trim(), password);
      else signedIn = await login(email.trim(), password);
      const r = signedIn?.app_metadata?.role || "customer";
      const hasConsole = r === "admin" || (!adminOnly && ["fraud_analyst", "security_analyst", "analyst"].includes(r));
      if (staffMode && !hasConsole) {          // staff sign-in is only for people who can use the console: never leave a customer signed in here
        await logout();
        setError(adminOnly ? "Only administrators can use the staff console. Customers can sign in from the store's Sign in button."
          : "This account does not have staff or administrator access. Customers can sign in from the store's Sign in button.");
        return;
      }
      navigate(location.state?.from?.pathname || (hasConsole ? "/dashboard" : "/shop"), { replace: true });
    }
    catch (err) { setError(!configured && localOn && /incorrect email or password/i.test(err.message) ? `${err.message} In local demonstration mode only the demo accounts below and accounts you registered here exist.` : err.message); }
    finally { setBusy(false); }
  }

  return <div className={`auth-page${staffMode ? "" : " shop"}`}>
    <section className="auth-art">{staffMode
      ? <div className="auth-logo"><ShieldCheck size={36}/> <div>{BRAND} <span>Console</span><small>Staff and administrators only</small></div></div>
      : <div className="auth-logo"><ShoppingCart size={34}/> <div>{shop.name || "Online store"}{shop.is_demo && <small>Independent demonstration. Not affiliated with any retailer.</small>}</div></div>}
      {staffMode
        ? <div className="auth-copy"><h1>Staff &amp; administrator access</h1><p>Sign in with your administrator account to manage orders, products and refunds, review fraud risk and watch security events.</p><ShieldCheck size={100} strokeWidth={1.4} aria-hidden="true"/></div>
        : <div className="auth-copy"><h1>Welcome back!</h1><p>Sign in to check out faster, follow your orders and keep your saved items.</p><ShoppingCart size={100} strokeWidth={1.4} aria-hidden="true"/></div>}
      {staffMode
        ? <div className="auth-features"><span><ShoppingBag size={19}/> Orders &amp; risk scores</span><span><ShieldCheck size={19}/> Fraud alerts and cases</span><span><ScrollText size={19}/> Audit trail</span></div>
        : <div className="auth-features"><span><LockKeyhole size={19}/> Secure sign-in</span><span><ShieldCheck size={19}/> Safer shopping</span><span><ShoppingCart size={19}/> Easy reordering</span></div>}
    </section>
    <section className="auth-form-side"><form className="auth-card" onSubmit={submit} noValidate>
      <Link className="back-link" to="/shop"><ArrowLeft size={15} aria-hidden="true"/> Back to the store</Link>
      <h2>{staffMode ? "Staff & admin sign-in" : "Login"}</h2><p>{staffMode ? "Administrator accounts only. Enter your email and password." : "Enter your email and password."}</p>
      {error && <div className="notice error" role="alert">{error}</div>}
      {!configured && !localOn && <div className="notice info">Setup required: add <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> to <code>frontend/.env</code> and restart the dev server before sign-in can work.</div>}
      <Field label="Email Address" error={errors.email}>{a => <div className="input-icon"><Mail size={16} aria-hidden="true"/>
        <input {...a} type="email" autoComplete="email" placeholder="Enter your email address" value={email} onChange={e => setEmail(e.target.value)}/></div>}</Field>
      <PasswordInput label="Password" error={errors.password} autoComplete="current-password" placeholder="Enter your password" value={password} onChange={e => setPassword(e.target.value)}/>
      <button className="primary-button" disabled={busy}>{busy ? "Signing in…" : "Login"}</button>
      {!configured && localOn && <div className="notice info" role="note" aria-label="Local demo accounts"><strong>Local demonstration sign-in.</strong> Not for production. Pick an account to fill the form:
        <ul className="demo-accounts">{DEMO_ACCOUNTS.filter(([, label]) => !staffMode || !label.startsWith("Customer")).map(([em, label]) => <li key={em}><button type="button" className="link-button" onClick={() => { setEmail(em); setPassword(DEMO_PASSWORD); }}>{label}</button></li>)}</ul></div>}
      <div className="auth-switch"><Link to="/forgot-password">Forgot your password?</Link></div>
      {staffMode ? <div className="auth-switch">Shopping? <Link to="/login">Customer sign-in</Link></div>
        : <><div className="auth-switch">Don't have an account? <Link to="/register">Register here</Link></div>
          <div className="auth-switch"><Link to="/login?staff=1" state={{ from: { pathname: "/dashboard" } }}>Staff &amp; admin sign-in</Link></div></>}
    </form></section>
  </div>;
}
