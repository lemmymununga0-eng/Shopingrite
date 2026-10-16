import { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "../services/supabase";
import { setUnauthorizedHandler } from "../services/api";

const Context = createContext(null);
const NOT_CONFIGURED = "Supabase is not configured. Copy frontend/.env.example to frontend/.env and add your project URL and anon key.";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

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
  }

  async function register(email, password, fullName) {
    if (!supabase) throw new Error(NOT_CONFIGURED);
    const { data, error } = await supabase.auth.signUp({ email, password, options: { data: { full_name: fullName } } });
    if (error) throw new Error(error.message || "Registration failed.");
    return data;
  }

  async function logout() {
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
  const role = user?.app_metadata?.role || "customer";
  const configured = Boolean(supabase);

  return <Context.Provider value={{ user, loading, role, configured, login, register, logout, requestPasswordReset, updatePassword, updateProfile }}>{children}</Context.Provider>;
}

export function useAuth() { return useContext(Context); }
