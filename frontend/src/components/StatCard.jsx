export default function StatCard({ title, value, note, icon: Icon, color = "green" }) {
  return <article className="stat-card">
    <div className={`stat-icon ${color}`}>{Icon && <Icon size={23} />}</div>
    <div className="stat-content"><p>{title}</p><h2>{value}</h2><span className="stat-note">{note}</span></div>
  </article>;
}
