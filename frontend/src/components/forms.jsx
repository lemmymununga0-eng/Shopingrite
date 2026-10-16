import { useId, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

/** Label + control + error/hint, wired together for screen readers. `children` receives the props to spread on the control. */
export function Field({ label, error, hint, children }) {
  const id = useId();
  const describedBy = [error && `${id}-err`, hint && `${id}-hint`].filter(Boolean).join(" ") || undefined;
  return <div className="field">
    <label htmlFor={id}><span>{label}</span></label>
    {children({ id, "aria-invalid": error ? true : undefined, "aria-describedby": describedBy })}
    {hint && <small id={`${id}-hint`} className="field-hint">{hint}</small>}
    {error && <small id={`${id}-err`} className="field-error" role="alert">{error}</small>}
  </div>;
}

export function PasswordInput({ label, error, hint, ...props }) {
  const [shown, setShown] = useState(false);
  return <Field label={label} error={error} hint={hint}>{a =>
    <div className="password-wrap">
      <input {...a} {...props} type={shown ? "text" : "password"}/>
      <button type="button" className="password-toggle" onClick={() => setShown(!shown)}
        aria-label={shown ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`} aria-pressed={shown}>
        {shown ? <EyeOff size={17}/> : <Eye size={17}/>}</button>
    </div>}</Field>;
}

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/** Password rules shown to the user and enforced before sign-up (Supabase may enforce its own as well). */
export const PASSWORD_RULES = [
  ["At least 8 characters", p => p.length >= 8],
  ["A letter", p => /[A-Za-z]/.test(p)],
  ["A number", p => /\d/.test(p)],
];
export const passwordOk = p => PASSWORD_RULES.every(([, test]) => test(p));
