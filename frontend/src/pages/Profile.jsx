import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { Field } from "../components/forms";
import { PageHeader } from "../components/ui";

export default function Profile() {
  const { user, role, updateProfile } = useAuth();
  const current = user?.user_metadata?.full_name || "";
  const [name, setName] = useState(current);
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const initial = (current || user?.email || "?").charAt(0).toUpperCase();

  async function save(e) {
    e.preventDefault(); setError(""); setSaved(false);
    const v = name.trim();
    if (!v) return setFieldError("Enter your name");
    if (v.length > 80) return setFieldError("Use 80 characters or fewer");
    setFieldError(""); setBusy(true);
    try { await updateProfile(v); setSaved(true); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return <div>
    <PageHeader title="Profile" subtitle="Your signed-in account information."/>
    <section className="panel">
      <div className="profile-row"><div className="profile-avatar" aria-hidden="true">{initial}</div>
        <div><h2>{current || "Name not provided"}</h2><p className="muted-text">{user?.email}</p></div></div>
      <hr className="soft-rule"/>
      <dl className="detail-grid">
        <dt>Role</dt><dd style={{ textTransform: "capitalize" }}>{role}</dd>
        <dt>Account created</dt><dd>{user?.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}</dd>
        <dt>Account ID</dt><dd>{user?.id || "—"}</dd>
        <dt>Email confirmed</dt><dd>{user?.email_confirmed_at ? "Yes" : "No"}</dd>
      </dl>
      <p className="muted-text">Your role is assigned by an administrator and checked by the API on every request. It cannot be changed here.</p>
    </section>
    <form className="panel" style={{ marginTop: 16 }} onSubmit={save} noValidate>
      <div className="panel-heading"><h2>Edit profile</h2></div>
      <Field label="Full name" error={fieldError}>{a => <input {...a} autoComplete="name" value={name} onChange={e => { setName(e.target.value); setSaved(false); }} maxLength={90}/>}</Field>
      {saved && <div className="notice success" role="status">Profile updated.</div>}
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="page-actions">
        <button className="btn btn-primary" disabled={busy || name.trim() === current}>{busy ? "Saving…" : "Save changes"}</button>
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => { setName(current); setFieldError(""); setError(""); setSaved(false); }}>Cancel</button>
      </div>
    </form>
  </div>;
}
