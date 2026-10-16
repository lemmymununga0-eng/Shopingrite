import { supabase } from "./supabase";
import { getLocalSession } from "./session";

const BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

async function accessToken() {
  const local = getLocalSession();
  if (local?.token) return local.token;
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data?.session?.access_token || null;
}

export class ApiError extends Error {
  constructor(message, status, body) { super(message); this.status = status; this.body = body; }
}

function describe(body, status) {
  if (typeof body.detail === "string" && !body.errors) return body.detail;
  if (body.detail && typeof body.detail === "object" && typeof body.detail.message === "string") {
    const extra = Array.isArray(body.detail.problems) ? " " + body.detail.problems.map(p => p.message).join(" ") : "";
    return body.detail.message + extra;
  }
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
  if (!response.ok) throw new ApiError(describe(body, response.status), response.status, body);
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

  // ---- store ----
  storeInfo: () => request("/store-info"),
  categories: () => request("/categories"),
  products: params => request(`/products${qs(params)}`),
  product: id => request(`/products/${encodeURIComponent(id)}`),
  cart: () => request("/cart"),
  addToCart: (product_id, quantity = 1) => request("/cart/items", { method: "POST", body: JSON.stringify({ product_id, quantity }) }),
  updateCartItem: (id, quantity) => request(`/cart/items/${id}`, { method: "PATCH", body: JSON.stringify({ quantity }) }),
  removeCartItem: id => request(`/cart/items/${id}`, { method: "DELETE" }),
  placeOrder: payload => request("/orders", { method: "POST", body: JSON.stringify(payload) }),
  orders: params => request(`/orders${qs(params)}`),
  order: id => request(`/orders/${encodeURIComponent(id)}`),
  cancelOrder: id => request(`/orders/${encodeURIComponent(id)}/cancel`, { method: "POST" }),

  // ---- local demo sign-in ----
  localLogin: (email, password) => request("/auth/local/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => request("/auth/me"),

  // ---- staff console ----
  overview: days => request(`/reports/overview${qs({ days })}`),
  fraudReport: params => request(`/reports/fraud${qs(params)}`),
  securityReport: days => request(`/reports/security${qs({ days })}`),
  inventory: params => request(`/inventory${qs(params)}`),
  adjustInventory: (id, body) => request(`/inventory/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  cases: params => request(`/investigations${qs(params)}`),
  createCase: body => request("/investigations", { method: "POST", body: JSON.stringify(body) }),
  caseDetail: id => request(`/investigations/${id}`),
  updateCase: (id, body) => request(`/investigations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  scamCheck: url => request("/scamwatch/check", { method: "POST", body: JSON.stringify({ url }) }),
  scamReport: (url, comment) => request("/scamwatch/reports", { method: "POST", body: JSON.stringify({ url, comment: comment || "" }) }),
  scamReports: params => request(`/scamwatch/reports${qs(params)}`),
  reviewScamReport: (id, review_status, notes) => request(`/scamwatch/reports/${id}`, { method: "PATCH", body: JSON.stringify({ review_status, notes: notes || null }) }),
  securityEvents: params => request(`/security/events${qs(params)}`),
  securityEvent: id => request(`/security/events/${id}`),
  securitySummary: days => request(`/security/summary${qs({ days })}`),
  thresholds: () => request("/security/thresholds"),
  setThresholds: values => request("/security/thresholds", { method: "PUT", body: JSON.stringify({ values }) }),
  users: () => request("/admin/users"),
  updateUser: (id, body) => request(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  audit: params => request(`/audit${qs(params)}`),
  integrations: () => request("/settings/integrations"),
};
