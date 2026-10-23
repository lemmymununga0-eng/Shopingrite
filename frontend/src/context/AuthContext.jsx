import { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "../services/supabase";
import { api, setUnauthorizedHandler } from "../services/api";
import { clearLocalSession, getLocalSession, setLocalSession } from "../services/session";
import { STAFF_ROLES } from "../services/format";

const Context = createContext(null);
const NOT_CONFIGURED = "Supabase is not configured. Copy frontend/.env.example to frontend/.env and add your project URL and anon key.";

export function AuthProvider({ children }) {
  // Without Supabase, a local DEMO session (if any) is restored from this tab's sessionStorage.
  const [user, setUser] = useState(() => (supabase ? null : getLocalSession()?.user || null));
  const [loading, setLoading] = useState(true);
  const [adminOnly, setAdminOnly] = useState(false);     // the server's CONSOLE_ADMIN_ONLY switch (the server enforces it; this only hides links)
  useEffect(() => { Promise.resolve(api.storeInfo?.()).then(d => setAdminOnly(Boolean(d?.console_admin_only))).catch(() => {}); }, []);

  useEffect(() => {
    if (!supabase) { setLoading(false); return; }
    supabase.auth.getSession().then(({ data }) => {
      setUser(data.session?.user || null);
      setLoading(false);
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user || null);
    });
    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearLocalSession();
      if (supabase) supabase.auth.signOut().catch(() => {});
      setUser(null);
    });
  }, []);

  async function login(email, password) {
    if (!supabase) throw new Error(NOT_CONFIGURED);
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      if (error.code === "email_not_confirmed") throw new Error("Please confirm your email first: open the confirmation link Supabase sent you, then sign in.");
      if (error.status === 429 || error.code === "over_request_rate_limit") throw new Error("Too many attempts. Wait a minute and try again.");
      throw new Error("Sign-in failed. Check your email and password, or register if you have no account yet.");
    }
    setUser(data.user);
    return data.user;
  }

  /** Local DEMONSTRATION sign-in (backend LOCAL_AUTH_ENABLED=true). Not a production login. */
  async function loginLocal(email, password) {
    const d = await api.localLogin(email, password);
    const profile = { id: d.user.id, email: d.user.email, user_metadata: { full_name: d.user.full_name },
                      app_metadata: { role: d.user.role } };
    setLocalSession({ token: d.access_token, user: profile });
    setUser(profile);
    return profile;
  }

  /** Local DEMONSTRATION sign-up (backend LOCAL_AUTH_ENABLED=true): creates a customer account and signs it in. */
  async function registerLocal(email, password, fullName) {
    const d = await api.localRegister(email, password, fullName);
    const profile = { id: d.user.id, email: d.user.email, user_metadata: { full_name: d.user.full_name }, app_metadata: { role: d.user.role } };
    setLocalSession({ token: d.access_token, user: profile });
    setUser(profile);
    return profile;
  }

  async function register(email, password, fullName) {
    if (!supabase) throw new Error(NOT_CONFIGURED);
    const { data, error } = await supabase.auth.signUp({ email, password, options: { data: { full_name: fullName } } });
    if (error) throw new Error(error.message || "Registration failed.");
    return data;
  }

  async function logout() {
    clearLocalSession();
    if (supabase) {
      const { error } = await supabase.auth.signOut();
      if (error) throw error;
    }
    setUser(null);
  }

  async function requestPasswordReset(email) {
    if (!supabase) throw new Error(NOT_CONFIGURED);
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/reset-password` });
    if (error) throw new Error("Could not send the reset email. Try again later.");
  }

  async function updatePassword(password) {
    if (!supabase) throw new Error(NOT_CONFIGURED);
    const { error } = await supabase.auth.updateUser({ password });
    if (error) throw new Error(error.message || "Could not update the password.");
  }

  async function updateProfile(fullName) {
    if (!supabase) throw new Error(NOT_CONFIGURED);
    const { data, error } = await supabase.auth.updateUser({ data: { full_name: fullName } });
    if (error) throw new Error(error.message || "Could not update your profile.");
    setUser(data.user);
  }

  // Display only. The API decides what this user may do, from the verified token.
  const tokenRole = user?.app_metadata?.role || "customer";
  const role = adminOnly && ["fraud_analyst", "security_analyst", "analyst"].includes(tokenRole) ? "customer" : tokenRole;
  const configured = Boolean(supabase);
  const isStaff = STAFF_ROLES.includes(role);

  return <Context.Provider value={{ user, loading, role, isStaff, configured, login, loginLocal, registerLocal, register, logout, requestPasswordReset, updatePassword, updateProfile }}>{children}</Context.Provider>;
}

export function useAuth() { return useContext(Context); }
