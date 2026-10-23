import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, ChevronRight, FolderSearch, Globe, PackageX, PlusCircle, RotateCcw, ShoppingBag, Store, Tags, Wallet } from "lucide-react";
import StatCard from "./StatCard";
import { api } from "../services/api";
import { moneyC } from "../services/format";

/** "Store at a glance": the shop's own numbers and a prioritised to-do list that links into pre-filtered screens.
 *  Every figure comes from stored records (orders, risk assessments, inventory, cases), never from a sample. */
export default function StoreOverview({ days = 30 }) {
  const [o, setO] = useState(null);
  const [risk, setRisk] = useState(null);
  const [refunds, setRefunds] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([
      Promise.resolve(api.overview?.(days)),
      Promise.resolve(api.riskSummary?.()).catch(() => null),
      Promise.resolve(api.staffOrders?.({ payment_status: "refund_pending", page_size: 1 })).then(r => r?.total ?? 0).catch(() => null),
    ]).then(([ov, rk, rf]) => { if (live) { setO(ov || null); setRisk(rk || null); setRefunds(rf); } })
      .catch(e => live && setError(e.message));
    return () => { live = false; };
  }, [days]);

  if (error) return <div className="notice error" role="alert">Store overview unavailable: {error}</div>;
  if (!o) return null;

  const status = o.orders?.by_status || {};
  const orderCount = Object.values(status).reduce((n, v) => n + v, 0);
  const revenue = o.orders?.revenue_by_currency_cents || {};
  const [currency, cents] = Object.entries(revenue)[0] || ["ZMW", 0];
  const counts = risk?.counts || { high: 0, review: 0 };
  const stockOut = o.inventory?.out_of_stock_products || 0;
  const stockLow = o.inventory?.low_stock_products || 0;
  const openCases = o.cases?.open || 0;
  const pendingScams = o.scamwatch?.by_review_status?.pending || 0;

  // [count, singular, plural, link, icon, tone]; only items that need a person are listed
  const todo = [
    [counts.high, "high-risk order to review", "high-risk orders to review", "/orders?decision=high", AlertTriangle, "high"],
    [counts.review, "order flagged for review", "orders flagged for review", "/orders?decision=review", AlertTriangle, "medium"],
    [refunds || 0, "refund waiting to be paid", "refunds waiting to be paid", "/orders?payment_status=refund_pending", RotateCcw, "high"],
    [status.awaiting_payment || 0, "order awaiting payment", "orders awaiting payment", "/orders?status=awaiting_payment", Wallet, "low"],
    [stockOut, "product out of stock", "products out of stock", "/inventory?status=out_of_stock", PackageX, "medium"],
    [stockLow, "product running low", "products running low", "/inventory?status=low_stock", PackageX, "low"],
    [openCases, "open investigation case", "open investigation cases", "/investigations", FolderSearch, "medium"],
    [pendingScams, "website report to review", "website reports to review", "/scamwatch", Globe, "low"],
  ].filter(([n]) => n > 0);

  return <section aria-label="Store at a glance" className="ops-overview">
    <div className="cards-4">
      <StatCard title="Revenue (paid orders)" value={moneyC(cents, currency)} note={`Last ${days} days`} icon={Wallet} color="green"/>
      <StatCard title="Orders" value={orderCount} note={`${status.confirmed || 0} confirmed · ${status.completed || 0} completed`} icon={ShoppingBag} color="blue"/>
      <StatCard title="Orders at risk" value={counts.high + counts.review} note={`${counts.high} high · ${counts.review} review`} icon={AlertTriangle} color="red"/>
      <StatCard title="Refunds due" value={refunds ?? "—"} note={refunds ? "Pay these from Orders & Risk" : "Nothing waiting"} icon={RotateCcw} color="purple"/>
    </div>
    <div className="chart-grid">
      <section className="panel"><div className="panel-heading"><h2>Needs attention</h2></div>
        {todo.length === 0 ? <p className="muted-text" style={{ display: "flex", gap: 8, alignItems: "center" }}><CheckCircle2 size={18} aria-hidden="true"/> All clear: nothing is waiting for you.</p> :
          <ul className="todo-list">{todo.map(([n, one, many, to, Icon, tone]) =>
            <li key={many}><Link to={to}><span className={`todo-ico ${tone}`}><Icon size={17} aria-hidden="true"/></span><span><strong>{n}</strong> {n === 1 ? one : many}</span><ChevronRight size={16} aria-hidden="true"/></Link></li>)}</ul>}
      </section>
      <section className="panel"><div className="panel-heading"><h2>Quick actions</h2></div>
        <div className="quick-actions">
          <Link className="btn btn-secondary" to="/products"><PlusCircle size={15} aria-hidden="true"/> Add a product</Link>
          <Link className="btn btn-secondary" to="/orders"><ShoppingBag size={15} aria-hidden="true"/> Orders &amp; risk</Link>
          <Link className="btn btn-secondary" to="/inventory"><Tags size={15} aria-hidden="true"/> Adjust stock</Link>
          <Link className="btn btn-secondary" to="/shop"><Store size={15} aria-hidden="true"/> Open the store</Link>
        </div>
        <p className="muted-text" style={{ marginTop: 12 }}>Risk scores come from transparent rules (store_risk_v1), not machine learning, and are a signal for a person to review.</p>
      </section>
    </div>
  </section>;
}
