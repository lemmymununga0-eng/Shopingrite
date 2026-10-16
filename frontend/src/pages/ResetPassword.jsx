import { useState } from "react";
import { Link } from "react-router-dom";
import { LockKeyhole, ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";

export default function ResetPassword() {
  const { user, loading, updatePassword } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault(); setError(""); setMessage("");
    if (password.length < 8) return setError("Use at least 8 characters for the password.");
    if (password !== confirm) return setError("The passwords do not match.");
    setBusy(true);
    try { await updatePassword(password); setMessage("Password updated. You can now continue to the app."); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <div className="auth-page auth-single">
    <section className="auth-form-side"><form className="auth-card" onSubmit={submit}>
      <h2><ShieldCheck size={20}/> Choose a new password</h2>
      {!loading && !user && <div className="notice info">Open this page from the link in your reset email. <Link to="/forgot-password">Request a new link</Link></div>}
      {error && <div className="notice error" role="alert">{error}</div>}
      {message && <div className="notice success" role="status">{message} <Link to="/">Continue</Link></div>}
      <label className="field"><span>New password</span><div className="input-icon"><LockKeyhole size={16}/>
        <input type="password" required minLength={8} autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)}/></div></label>
      <label className="field"><span>Confirm new password</span><div className="input-icon"><LockKeyhole size={16}/>
        <input type="password" required autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)}/></div></label>
      <button className="primary-button" disabled={busy || !user}>{busy ? "Saving…" : "Update password"}</button>
    </form></section>
  </div>;
}
