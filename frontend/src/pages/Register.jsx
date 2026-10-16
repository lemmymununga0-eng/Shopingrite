import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ShieldCheck, LockKeyhole, Mail, UserRound } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { EMAIL_RE, Field, PASSWORD_RULES, PasswordInput, passwordOk } from "../components/forms";

export default function Register() {
  const { user, register, configured } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState(""); const [email, setEmail] = useState("");
  const [password, setPassword] = useState(""); const [confirm, setConfirm] = useState("");
  const [agree, setAgree] = useState(false);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(""); const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/dashboard" replace />;

  async function submit(e) {
    e.preventDefault(); setError(""); setMessage("");
    const errs = {};
    if (!name.trim()) errs.name = "Enter your full name";
    if (!email.trim()) errs.email = "Enter your email address"; else if (!EMAIL_RE.test(email.trim())) errs.email = "Enter a valid email address";
    if (!passwordOk(password)) errs.password = "Password does not meet the requirements below";
    if (password !== confirm) errs.confirm = "The passwords do not match";
    if (!agree) errs.agree = "Please acknowledge that this is an educational demo";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const data = await register(email.trim(), password, name.trim());
      if (data.session) navigate("/dashboard");
      else setMessage("Account created. Check your email for a confirmation link, then sign in.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <div className="auth-page">
    <section className="auth-art"><div className="auth-logo"><ShieldCheck size={36}/><div>Shoprite <span>FraudGuard</span><small>Smart Payment Security. Real-Time Fraud Risk Analysis.</small></div></div>
      <div className="auth-copy"><h1>Create Your Account</h1><p>Join Shoprite FraudGuard and monitor transaction risk in this educational project.</p></div>
      <div className="auth-features"><span><ShieldCheck size={19}/> Real model status</span><span><LockKeyhole size={19}/> Authenticated access</span><span><UserRound size={19}/> Your account</span></div>
    </section>
    <section className="auth-form-side"><form className="auth-card" onSubmit={submit} noValidate>
      <h2>Register</h2><p>Fill in your details to create an account.</p>
      {error && <div className="notice error" role="alert">{error}</div>}{message && <div className="notice success" role="status">{message} <Link to="/login">Go to login</Link></div>}
      {!configured && <div className="notice info">Setup required: add your Supabase URL and anon key to <code>frontend/.env</code> to enable registration.</div>}
      <Field label="Full Name" error={errors.name}>{a => <div className="input-icon"><UserRound size={16} aria-hidden="true"/>
        <input {...a} autoComplete="name" value={name} onChange={e => setName(e.target.value)} placeholder="Enter your full name"/></div>}</Field>
      <Field label="Email Address" error={errors.email}>{a => <div className="input-icon"><Mail size={16} aria-hidden="true"/>
        <input {...a} type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Enter your email address"/></div>}</Field>
      <PasswordInput label="Password" error={errors.password} autoComplete="new-password" placeholder="Create a password" value={password} onChange={e => setPassword(e.target.value)}/>
      <ul className="req-list" aria-label="Password requirements">{PASSWORD_RULES.map(([label, test]) =>
        <li key={label} className={test(password) ? "ok" : ""}>{test(password) ? "✓" : "○"} {label}</li>)}</ul>
      <PasswordInput label="Confirm Password" error={errors.confirm} autoComplete="new-password" placeholder="Confirm your password" value={confirm} onChange={e => setConfirm(e.target.value)}/>
      <label className="checkbox-row"><input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)}/>
        <span>I understand this is an educational project that does not process real payments.</span></label>
      {errors.agree && <small className="field-error" role="alert">{errors.agree}</small>}
      <button className="primary-button" disabled={busy}>{busy ? "Creating account…" : "Create Account"}</button>
      <div className="auth-switch">Already have an account? <Link to="/login">Login here</Link></div>
    </form></section>
  </div>;
}
