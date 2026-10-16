import { supabase } from "./supabase";

const BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

async function accessToken() {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data?.session?.access_token || null;
}

function describe(body, status) {
  if (typeof body.detail === "string" && !body.errors) return body.detail;
  if (Array.isArray(body.errors) && body.errors.length) {
    return body.errors.map(e => `${e.field}: ${e.message}`).join("; ");
  }
  return `Request failed (${status})`;
}

async function request(path, options = {}) {
  const token = await accessToken();
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    });
  } catch {
    throw new Error("Cannot reach the FraudGuard API. Is the backend running?");
  }
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) {
    onUnauthorized();
    throw new Error("Your session has expired. Please sign in again.");
  }
  if (!response.ok) throw new Error(describe(body, response.status));
  return body;
}

const qs = params => {
  const p = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== "" && v != null) p.set(k, v); });
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  health: () => request("/health"),
  modelInfo: () => request("/model-info"),
  predict: payload => request("/predict", { method: "POST", body: JSON.stringify(payload) }),
  transactions: params => request(`/transactions${qs(params)}`),
  stats: days => request(`/transactions/stats${qs({ days })}`),
  transaction: id => request(`/transactions/${encodeURIComponent(id)}`),
  alerts: params => request(`/alerts${qs(params)}`),
  pcaInfo: () => request("/pca-demo/info"),
  pcaPredict: features => request("/pca-demo/predict", { method: "POST", body: JSON.stringify({ features }) }),
  reviewAlert: (id, status, notes) =>
    request(`/alerts/${id}`, { method: "PATCH", body: JSON.stringify({ status, notes: notes || null }) }),
};
