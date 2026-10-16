import { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { ShieldCheck, LockKeyhole, Mail, ShoppingCart } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { EMAIL_RE, Field, PasswordInput } from "../components/forms";
import { api } from "../services/api";
import { BRAND } from "../services/format";

const DEMO_ACCOUNTS = [["customer@example.com", "Customer (store)"], ["fraud.analyst@example.com", "Fraud analyst"], ["security.analyst@example.com", "Security analyst"], ["admin@example.com", "Administrator"]];
const DEMO_PASSWORD = "DemoPass!2026";

export default function Login() {
  const { user, role, login, loginLocal, configured } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const home = role === "customer" ? "/shop" : "/dashboard";
  const from = location.state?.from?.pathname || home;
  const [localOn, setLocalOn] = useState(false);
  useEffect(() => { if (!configured) Promise.resolve(api.storeInfo?.()).then(d => setLocalOn(Boolean(d?.local_auth_enabled))).catch(() => {}); }, [configured]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={from} replace />;

  async function submit(e) {
    e.preventDefault(); setError("");
    const errs = {};
    if (!email.trim()) errs.email = "Enter your email address"; else if (!EMAIL_RE.test(email.trim())) errs.email = "Enter a valid email address";
    if (!password) errs.password = "Enter your password";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      if (!configured && localOn) {
        const p = await loginLocal(email.trim(), password);
        navigate(location.state?.from?.pathname || (p.app_metadata.role === "customer" ? "/shop" : "/dashboard"), { replace: true });
      } else { await login(email.trim(), password); navigate(from, { replace: true }); }
    }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <div className="auth-page">
    <section className="auth-art"><div className="auth-logo"><ShieldCheck size={36}/> <div>{BRAND} <span>Console</span><small>Independent demonstration. Not affiliated with any retailer.</small></div></div>
      <div className="auth-copy"><h1>Welcome Back!</h1><p>Sign in to review transaction risk and fraud alerts.</p><ShoppingCart size={100} strokeWidth={1.4} aria-hidden="true"/></div>
      <div className="auth-features"><span><LockKeyhole size={19}/> Secure sign-in</span><span><ShieldCheck size={19}/> Fraud risk analysis</span><span><ShoppingCart size={19}/> Safer shopping</span></div>
    </section>
    <section className="auth-form-side"><form className="auth-card" onSubmit={submit} noValidate>
      <h2>Login</h2><p>Enter your email and password.</p>
      {error && <div className="notice error" role="alert">{error}</div>}
      {!configured && !localOn && <div className="notice info">Setup required: add <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> to <code>frontend/.env</code> and restart the dev server before sign-in can work.</div>}
      <Field label="Email Address" error={errors.email}>{a => <div className="input-icon"><Mail size={16} aria-hidden="true"/>
        <input {...a} type="email" autoComplete="email" placeholder="Enter your email address" value={email} onChange={e => setEmail(e.target.value)}/></div>}</Field>
      <PasswordInput label="Password" error={errors.password} autoComplete="current-password" placeholder="Enter your password" value={password} onChange={e => setPassword(e.target.value)}/>
      <button className="primary-button" disabled={busy}>{busy ? "Signing in…" : "Login"}</button>
      {!configured && localOn && <div className="notice info" role="note" aria-label="Local demo accounts"><strong>Local demonstration sign-in.</strong> Not for production. Pick an account to fill the form:
        <ul className="demo-accounts">{DEMO_ACCOUNTS.map(([em, label]) => <li key={em}><button type="button" className="link-button" onClick={() => { setEmail(em); setPassword(DEMO_PASSWORD); }}>{label}</button></li>)}</ul></div>}
      <div className="auth-switch"><Link to="/forgot-password">Forgot your password?</Link></div>
      <div className="auth-switch">Don't have an account? <Link to="/register">Register here</Link></div>
    </form></section>
  </div>;
}
