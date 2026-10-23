import { Truck } from "lucide-react";
import { moneyC } from "../services/format";

/** "Spend K X more for free delivery" progress bar (a common basket-building pattern). Renders nothing without a threshold. */
export function FreeDelivery({ subtotal, threshold, currency }) {
  if (!threshold) return null;
  const left = Math.max(0, threshold - subtotal);
  const pct = Math.min(100, Math.round((subtotal / threshold) * 100));
  return <div className="free-ship" data-testid="free-delivery">
    <p><Truck size={16} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 6 }}/>
      {left === 0 ? <strong>You have free delivery!</strong> : <>Add <strong>{moneyC(left, currency)}</strong> more for <strong>free delivery</strong></>}</p>
    <div className="bar" role="progressbar" aria-label="Progress to free delivery" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}><i style={{ width: `${pct}%` }}/></div>
  </div>;
}
