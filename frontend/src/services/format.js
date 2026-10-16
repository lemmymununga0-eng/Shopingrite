export const money = n => new Intl.NumberFormat("en-ZA", { style: "currency", currency: "ZAR" }).format(Number(n || 0));
/** Money from integer minor units (cents) in the currency the API reports. Never assumes a currency. */
export const moneyC = (cents, currency = "ZAR") => {
  try { return new Intl.NumberFormat("en-ZA", { style: "currency", currency }).format(Number(cents || 0) / 100); }
  catch { return `${currency} ${(Number(cents || 0) / 100).toFixed(2)}`; }
};
export const pct = p => `${(Number(p) * 100).toFixed(1)}%`;
export const when = iso => (iso ? new Date(iso).toLocaleString() : "—");
export const REVIEW_LABELS = { new: "New", confirmed_fraud: "Confirmed fraud", false_positive: "False positive" };
export const ROLE_LABELS = { customer: "Customer", fraud_analyst: "Fraud analyst", security_analyst: "Security analyst", admin: "Administrator", analyst: "Fraud analyst" };
export const STAFF_ROLES = ["fraud_analyst", "security_analyst", "admin", "analyst"];
export const BRAND = import.meta.env.VITE_APP_BRAND || "FraudGuard";
