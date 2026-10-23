const num = n => new Intl.NumberFormat("en-ZM", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(n || 0));
/** Amount in major units. Zambian kwacha is written "K1,234.50". */
export const money = n => `K${num(n)}`;
/** Money from integer minor units (ngwee/cents) in the currency the API reports. Never assumes another currency. */
export const moneyC = (cents, currency = "ZMW") => {
  const major = Number(cents || 0) / 100;
  if (currency === "ZMW") return `K${num(major)}`;
  try { return new Intl.NumberFormat("en-ZM", { style: "currency", currency }).format(major); }
  catch { return `${currency} ${major.toFixed(2)}`; }
};
export const pct = p => `${(Number(p) * 100).toFixed(1)}%`;
export const when = iso => (iso ? new Date(iso).toLocaleString() : "—");
export const REVIEW_LABELS = { new: "New", confirmed_fraud: "Confirmed fraud", false_positive: "False positive" };
export const ROLE_LABELS = { customer: "Customer", fraud_analyst: "Fraud analyst", security_analyst: "Security analyst", admin: "Administrator", analyst: "Fraud analyst" };
export const STAFF_ROLES = ["fraud_analyst", "security_analyst", "admin", "analyst"];
export const BRAND = import.meta.env.VITE_APP_BRAND || "FraudGuard";
