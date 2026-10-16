// Local DEMONSTRATION sign-in session (used only when Supabase is not configured and the backend has
// LOCAL_AUTH_ENABLED=true). sessionStorage is cleared when the tab closes. Display data only: the backend
// verifies the token on every request.
const KEY = "fg_local_session";

export function getLocalSession() {
  try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return null; }
}
export function setLocalSession(session) {
  try { sessionStorage.setItem(KEY, JSON.stringify(session)); } catch { /* storage unavailable */ }
}
export function clearLocalSession() {
  try { sessionStorage.removeItem(KEY); } catch { /* storage unavailable */ }
}
