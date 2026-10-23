/** Recently viewed product ids, kept in this browser only (a per-device convenience, never required). */
const KEY = "recently-viewed";

export function getViewed() {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v.filter(Number.isInteger) : []; } catch { return []; }
}

export function rememberViewed(id, max = 8) {
  try { localStorage.setItem(KEY, JSON.stringify([id, ...getViewed().filter(x => x !== id)].slice(0, max))); } catch { /* storage unavailable */ }
}
