import { useEffect, useRef } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { EmptyState } from "./ui";
import { BarChart3 } from "lucide-react";

// Risk colours match the badges (always paired with text labels/legends, never colour alone).
export const RISK_COLORS = { Low: "#16A34A", Medium: "#D97706", High: "#DC2626" };
const GREEN = "#198754", RED = "#DC2626";

/** The chart is described by the text label on its wrapper; the drawing itself is hidden from assistive tech and
 *  nothing inside it may take keyboard focus (hidden but focusable content is an accessibility error). */
function Decorative({ children }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    const fix = () => el.querySelectorAll("[tabindex],a,button").forEach(n => n.setAttribute("tabindex", "-1"));
    fix();
    const mo = new MutationObserver(fix);
    mo.observe(el, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, []);
  return <div ref={ref} aria-hidden="true" style={{ width: "100%", height: "100%" }}>{children}</div>;
}

const shortDate = d => { const [, m, day] = d.split("-"); return `${day}/${m}`; };

export function ActivityChart({ daily }) {
  if (!daily?.some(d => d.total > 0)) return <EmptyState icon={BarChart3}>No transactions in this period yet.</EmptyState>;
  return <div className="chart-box" role="img" aria-label={`Transactions per day over ${daily.length} days: ${daily.reduce((a, d) => a + d.total, 0)} total, ${daily.reduce((a, d) => a + d.flagged, 0)} flagged.`}>
    <Decorative><ResponsiveContainer width="100%" height="100%">
      <AreaChart accessibilityLayer={false} data={daily} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB"/>
        <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11 }} minTickGap={18}/>
        <YAxis allowDecimals={false} tick={{ fontSize: 11 }}/>
        <Tooltip labelFormatter={l => `Date: ${l}`}/><Legend/>
        <Area isAnimationActive={false} type="monotone" dataKey="total" name="All transactions" stroke={GREEN} fill="#198754" fillOpacity={0.15}/>
        <Area isAnimationActive={false} type="monotone" dataKey="flagged" name="Flagged" stroke={RED} fill="#DC2626" fillOpacity={0.15}/>
      </AreaChart>
    </ResponsiveContainer></Decorative></div>;
}

export function SplitChart({ flagged, lowerRisk }) {
  const data = [{ name: "Lower risk", value: lowerRisk, color: GREEN }, { name: "Flagged", value: flagged, color: RED }];
  if (flagged + lowerRisk === 0) return <EmptyState icon={BarChart3}>No data yet.</EmptyState>;
  return <div className="chart-box sm" role="img" aria-label={`${lowerRisk} lower-risk and ${flagged} flagged transactions.`}>
    <Decorative><ResponsiveContainer width="100%" height="100%"><PieChart accessibilityLayer={false}>
      <Pie isAnimationActive={false} data={data} dataKey="value" nameKey="name" innerRadius={48} outerRadius={78} paddingAngle={2}>
        {data.map(d => <Cell key={d.name} fill={d.color}/>)}</Pie>
      <Tooltip/><Legend/></PieChart></ResponsiveContainer></Decorative></div>;
}

export function RiskChart({ counts }) {
  const data = ["Low", "Medium", "High"].map(k => ({ name: k, value: counts?.[k] ?? 0 }));
  if (data.every(d => d.value === 0)) return <EmptyState icon={BarChart3}>No data yet.</EmptyState>;
  return <div className="chart-box sm" role="img" aria-label={`Risk levels: ${data.map(d => `${d.name} ${d.value}`).join(", ")}.`}>
    <Decorative><ResponsiveContainer width="100%" height="100%"><BarChart accessibilityLayer={false} data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={false}/>
      <XAxis dataKey="name" tick={{ fontSize: 12 }}/><YAxis allowDecimals={false} tick={{ fontSize: 11 }}/>
      <Tooltip/><Bar isAnimationActive={false} dataKey="value" name="Transactions" radius={[6, 6, 0, 0]}>
        {data.map(d => <Cell key={d.name} fill={RISK_COLORS[d.name]}/>)}</Bar></BarChart></ResponsiveContainer></Decorative></div>;
}
