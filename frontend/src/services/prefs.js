// Per-browser preferences. Everything here is actually used by the app; storage may be unavailable, so every access is guarded.
const KEY = "fg_prefs";
const DEFAULTS = { alertBadge: true, defaultMethod: "Card", pageSize: 15 };
export const PAGE_SIZES = [10, 15, 25, 50];
export const METHOD_OPTIONS = ["Card", "Bank Transfer", "Mobile Money"];

export function getPrefs() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
    return {
      alertBadge: typeof saved.alertBadge === "boolean" ? saved.alertBadge : DEFAULTS.alertBadge,
      defaultMethod: METHOD_OPTIONS.includes(saved.defaultMethod) ? saved.defaultMethod : DEFAULTS.defaultMethod,
      pageSize: PAGE_SIZES.includes(saved.pageSize) ? saved.pageSize : DEFAULTS.pageSize,
    };
  } catch { return { ...DEFAULTS }; }
}

/** Returns true if saved, false if the browser blocked storage. */
export function setPrefs(patch) {
  try { localStorage.setItem(KEY, JSON.stringify({ ...getPrefs(), ...patch })); return true; }
  catch { return false; }
}
