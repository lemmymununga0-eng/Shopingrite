import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ShieldAlert, FolderOpen, Globe, Boxes } from "lucide-react";
import StatCard from "./StatCard";
import { SeverityBadge, SOURCE_LABEL, StatusBadge } from "./badges";
import { api } from "../services/api";
import { when } from "../services/format";

/** Combined staff overview. Every figure comes from stored records via /reports/overview. */
export default function OperationsOverview({ days = 30 }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    Promise.resolve(api.overview?.(days)).then(x => live && x && setD(x)).catch(e => live && setError(e.message));
    return () => { live = false; };
  }, [days]);
  if (error) return <div className="notice error" role="alert">Operations overview unavailable: {error}</div>;
  if (!d) return null;
  const high = (d.cases.open_by_severity.high || 0) + (d.cases.open_by_severity.critical || 0);
  return <section aria-label="Operations overview" className="ops-overview">
    <div className="cards-4">
      <StatCard title="Open cases" value={d.cases.open} note={`${high} high priority`} icon={FolderOpen} color="red"/>
      <StatCard title="Scam reports" value={d.scamwatch.reports} note={`${d.scamwatch.by_review_status.pending || 0} pending review`} icon={Globe} color="purple"/>
      <StatCard title="Security events" value={d.security ? d.security.events_in_period : "—"} note={d.security ? `Last ${days} days` : "Security role only"} icon={ShieldAlert} color="blue"/>
      <StatCard title="Stock alerts" value={d.inventory.low_stock_products + d.inventory.out_of_stock_products} note={`${d.inventory.out_of_stock_products} out of stock`} icon={Boxes} color="green"/>
    </div>
    <div className="panel"><div className="panel-heading"><h2>Recent cases</h2><Link className="text-link" to="/investigations">Open Investigation Centre</Link></div>
      {d.cases.recent.length === 0 ? <p className="muted-text">No cases yet. They are created when a prediction is flagged, a website is reported, or a security alert fires.</p> :
        <ul className="alert-list">{d.cases.recent.map(c => <li key={c.id} className="alert-row"><div><strong>{c.case_reference}</strong> · {SOURCE_LABEL[c.source_type]}<p>{c.summary}</p><small>{when(c.created_at)}</small></div><SeverityBadge severity={c.severity}/> <StatusBadge status={c.status}/></li>)}</ul>}</div>
  </section>;
}
