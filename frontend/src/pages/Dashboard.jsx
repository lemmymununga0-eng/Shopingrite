import { useCallback, useEffect, useState } from "react";
import { BellRing, CreditCard, Percent, PlusCircle, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import StatCard from "../components/StatCard";
import OperationsOverview from "../components/OperationsOverview";
import StoreOverview from "../components/StoreOverview";
import FraudModelPanel from "../components/FraudModelPanel";
import { ActivityChart, RiskChart, SplitChart } from "../components/charts";
import { EmptyState, ErrorState, ModelBanner, PageHeader, RiskBadge, Skeleton, TransactionTable } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { api } from "../services/api";
import { money, pct } from "../services/format";

const PERIODS = [[7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"]];

export default function Dashboard() {
  const { user } = useAuth();
  const [days, setDays] = useState(30);
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [model, setModel] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, t, a, m] = await Promise.all([
        api.stats(days), api.transactions({ page_size: 5 }), api.alerts({ page_size: 4, review_status: "new" }), api.modelInfo(),
      ]);
      setStats(s); setRecent(t.items); setAlerts(a.items); setModel(m); setError("");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [days]);
  useEffect(() => { load(); }, [load]);

  const first = (user?.user_metadata?.full_name || "").split(" ")[0];
  const none = stats && stats.total_transactions === 0;
  return <div>
    <PageHeader title={`Dashboard${first ? ` — welcome, ${first}` : ""}`} subtitle="Monitor transaction activity and fraud risk."
      actions={<>
        <label className="sr-only" htmlFor="period">Reporting period</label>
        <select id="period" className="btn btn-secondary" value={days} onChange={e => setDays(Number(e.target.value))}>
          {PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""}/> Refresh</button>
      </>}/>
    <ModelBanner info={model}/>
    <StoreOverview days={days}/>
    <OperationsOverview days={days}/>
    <FraudModelPanel/>
    {error && !stats ? <ErrorState error={error} onRetry={load}/> : loading && !stats ? <>
      <div className="cards-4"><Skeleton className="skeleton-card" count={4}/></div><Skeleton className="skeleton-chart" count={1}/></> : stats && <>
      <div className="cards-4">
        <StatCard title="Total Transactions" value={stats.total_transactions} note={`In the last ${days} days`} icon={CreditCard} color="blue"/>
        <StatCard title="Flagged Transactions" value={stats.flagged} note={`${stats.open_alerts} awaiting review`} icon={ShieldAlert} color="red"/>
        <StatCard title="Confirmed Fraud Cases" value={stats.confirmed_fraud} note={stats.reviewed ? `${stats.reviewed} alerts reviewed` : "No alerts reviewed yet"} icon={ShieldCheck} color="green"/>
        <StatCard title="Flag Rate" value={stats.flag_rate == null ? "—" : pct(stats.flag_rate)}
          note={stats.avg_probability == null ? "No data yet" : `Flagged ÷ total · avg risk ${pct(stats.avg_probability)}`} icon={Percent} color="purple"/>
      </div>
      {none && <div className="notice info">No transactions in this period yet. <Link to="/payment">Submit a payment</Link> to see activity here. Total value: {money(stats.total_amount)}.</div>}
      <div className="chart-grid">
        <section className="panel"><div className="panel-heading"><h2>Transaction activity</h2></div><ActivityChart daily={stats.daily}/>
          <p className="chart-caption">Transactions per day (UTC), last {days} days.</p></section>
        <section className="panel"><div className="panel-heading"><h2>Legitimate vs flagged</h2></div><SplitChart flagged={stats.flagged} lowerRisk={stats.lower_risk}/>
          <p className="chart-caption">Flagged = model probability above the threshold, not confirmed fraud.</p></section>
      </div>
      <div className="chart-grid">
        <section className="panel"><div className="panel-heading"><h2><BellRing size={18}/> Latest fraud alerts</h2><Link className="text-link" to="/alerts">View all</Link></div>
          {alerts.map(x => <div className="alert-row" key={x.id}><ShieldAlert size={17} aria-hidden="true"/>
            <div><strong>#{x.transaction_reference}</strong><p>{money(x.amount)} · {x.payment_method} · {pct(x.probability)}</p></div>
            <RiskBadge risk={x.risk}/><Link className="text-link" to={`/transactions/${x.id}`} aria-label={`View details for ${x.transaction_reference}`}>View</Link></div>)}
          {!alerts.length && <EmptyState icon={ShieldCheck}>No alerts awaiting review.</EmptyState>}</section>
        <section className="panel"><div className="panel-heading"><h2>Risk distribution</h2></div><RiskChart counts={stats.risk_counts}/></section>
      </div>
      <section className="panel"><div className="panel-heading"><h2>Recent transactions</h2><div><Link className="text-link" to="/history">View all</Link>
        {" · "}<Link className="text-link" to="/payment"><PlusCircle size={13}/> New payment</Link></div></div>
        {recent.length ? <TransactionTable items={recent}/> : <EmptyState>No transactions yet.</EmptyState>}</section>
    </>}
  </div>;
}
