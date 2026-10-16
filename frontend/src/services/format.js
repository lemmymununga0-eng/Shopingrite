export const money = n => new Intl.NumberFormat("en-ZA", { style: "currency", currency: "ZAR" }).format(Number(n || 0));
export const pct = p => `${(Number(p) * 100).toFixed(1)}%`;
export const when = iso => (iso ? new Date(iso).toLocaleString() : "—");
export const REVIEW_LABELS = { new: "New", confirmed_fraud: "Confirmed fraud", false_positive: "False positive" };
