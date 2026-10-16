const SEV_CLASS = { critical: "high", high: "high", medium: "medium", low: "low", info: "low" };
export const SeverityBadge = ({ severity }) => <span className={`risk-badge ${SEV_CLASS[severity] || "medium"}`}>{severity}</span>;

export const CASE_STATUS = { new: "New", investigating: "Investigating", confirmed: "Confirmed", false_positive: "False positive", resolved: "Resolved" };
export const CASE_STATUS_CLASS = { new: "medium", investigating: "medium", confirmed: "high", false_positive: "low", resolved: "low" };
export const StatusBadge = ({ status }) => <span className={`risk-badge ${CASE_STATUS_CLASS[status] || "medium"}`}>{CASE_STATUS[status] || status}</span>;

export const SOURCE_LABEL = { fraud_prediction: "Fraud prediction", scamwatch_report: "ScamWatch report", security_alert: "Security alert", order_anomaly: "Order anomaly", manual: "Manual" };
