import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ShoppingCart, LockKeyhole, Mail, UserRound, ArrowLeft, Heart } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { EMAIL_RE, Field, PASSWORD_RULES, PasswordInput, passwordOk } from "../components/forms";

export default function Register() {
  const { user, role, register, registerLocal, configured } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState(""); const [email, setEmail] = useState("");
  const [password, setPassword] = useState(""); const [confirm, setConfirm] = useState("");
  const [agree, setAgree] = useState(false);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(""); const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  const [shop, setShop] = useState({ name: "", is_demo: false, local: false });
  useEffect(() => {
    Promise.resolve(api.storeInfo?.()).then(d => d && setShop({ name: d.name || "", is_demo: Boolean(d.is_demo), local: Boolean(d.local_auth_enabled) })).catch(() => {});
  }, []);
  const localMode = !configured && shop.local;       // offline demonstration: accounts live in the local database
  if (user) return <Navigate to={role === "customer" ? "/shop" : "/dashboard"} replace />;

  async function submit(e) {
    e.preventDefault(); setError(""); setMessage("");
    const errs = {};
    if (!name.trim()) errs.name = "Enter your full name";
    if (!email.trim()) errs.email = "Enter your email address"; else if (!EMAIL_RE.test(email.trim())) errs.email = "Enter a valid email address";
    if (!passwordOk(password)) errs.password = "Password does not meet the requirements below";
    if (password !== confirm) errs.confirm = "The passwords do not match";
    if (shop.is_demo && !agree) errs.agree = "Please acknowledge that this is an educational demo";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      if (localMode) { await registerLocal(email.trim(), password, name.trim()); navigate("/shop", { replace: true }); return; }
      const data = await register(email.trim(), password, name.trim());
      if (data.session) navigate("/shop", { replace: true });          // new accounts are customers: they belong in the store
      else setMessage("Account created. Check your email for a confirmation link, then sign in.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <div className="auth-page shop">
    <section className="auth-art"><div className="auth-logo"><ShoppingCart size={34}/><div>{shop.name || "Online store"}{shop.is_demo && <small>Independent demonstration. Not affiliated with any retailer.</small>}</div></div>
      <div className="auth-copy"><h1>Create your account</h1><p>Check out faster, follow your orders, and keep your saved items.</p></div>
      <div className="auth-features"><span><LockKeyhole size={19}/> Secure sign-in</span><span><Heart size={19}/> Saved items</span><span><UserRound size={19}/> Order history</span></div>
    </section>
    <section className="auth-form-side"><form className="auth-card" onSubmit={submit} noValidate>
      <Link className="back-link" to="/shop"><ArrowLeft size={15} aria-hidden="true"/> Back to the store</Link>
      <h2>Register</h2><p>Fill in your details to create an account.</p>
      {error && <div className="notice error" role="alert">{error}</div>}{message && <div className="notice success" role="status">{message} <Link to="/login">Go to login</Link></div>}
      {!configured && !localMode && <div className="notice info">Setup required: add your Supabase URL and anon key to <code>frontend/.env</code> to enable registration.</div>}
      {localMode && <div className="notice info" role="note">Local demonstration mode: your account is stored only in this computer's local database.</div>}
      <Field label="Full Name" error={errors.name}>{a => <div className="input-icon"><UserRound size={16} aria-hidden="true"/>
        <input {...a} autoComplete="name" value={name} onChange={e => setName(e.target.value)} placeholder="Enter your full name"/></div>}</Field>
      <Field label="Email Address" error={errors.email}>{a => <div className="input-icon"><Mail size={16} aria-hidden="true"/>
        <input {...a} type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Enter your email address"/></div>}</Field>
      <PasswordInput label="Password" error={errors.password} autoComplete="new-password" placeholder="Create a password" value={password} onChange={e => setPassword(e.target.value)}/>
      <ul className="req-list" aria-label="Password requirements">{PASSWORD_RULES.map(([label, test]) =>
        <li key={label} className={test(password) ? "ok" : ""}>{test(password) ? "✓" : "○"} {label}</li>)}</ul>
      <PasswordInput label="Confirm Password" error={errors.confirm} autoComplete="new-password" placeholder="Confirm your password" value={confirm} onChange={e => setConfirm(e.target.value)}/>
      {shop.is_demo && <><label className="checkbox-row"><input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)}/>
        <span>I understand this is an educational project that does not process real payments.</span></label>
      {errors.agree && <small className="field-error" role="alert">{errors.agree}</small>}</>}
      <button className="primary-button" disabled={busy}>{busy ? "Creating account…" : "Create Account"}</button>
      <div className="auth-switch">Already have an account? <Link to="/login">Login here</Link></div>
    </form></section>
  </div>;
}
