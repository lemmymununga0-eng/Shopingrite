import { useState } from "react";
import { Link } from "react-router-dom";
import { Mail, ShieldCheck, ArrowLeft } from "lucide-react";
import { useAuth } from "../context/AuthContext";

export default function ForgotPassword() {
  const { requestPasswordReset } = useAuth();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault(); setError(""); setMessage(""); setBusy(true);
    try { await requestPasswordReset(email); setMessage("If an account exists for that email, a reset link has been sent."); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <div className="auth-page auth-single shop">
    <section className="auth-form-side"><form className="auth-card" onSubmit={submit}>
      <Link className="back-link" to="/shop"><ArrowLeft size={15} aria-hidden="true"/> Back to the store</Link>
      <h2><ShieldCheck size={20}/> Reset password</h2><p>Enter your email and we will send a reset link.</p>
      {error && <div className="notice error" role="alert">{error}</div>}
      {message && <div className="notice success" role="status">{message}</div>}
      <label className="field"><span>Email Address</span><div className="input-icon"><Mail size={16}/>
        <input type="email" required autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Enter your email address"/></div></label>
      <button className="primary-button" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
      <div className="auth-switch"><Link to="/login">Back to login</Link></div>
    </form></section>
  </div>;
}
