import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock, XCircle } from "lucide-react";
import { ErrorState, Loading } from "../components/ui";
import { api } from "../services/api";
import { moneyC, when } from "../services/format";
import { SCENARIOS } from "./Checkout";

/** What the customer should see for each real state. A pending payment is never shown as successful. */
export function paymentState(order) {
  const last = order.payment_attempts?.[order.payment_attempts.length - 1];
  if (order.status === "cancelled") return order.payment_status === "refund_pending" || order.payment_status === "refunded" ? "refund" : "order_cancelled";
  if (order.payment_status === "paid") return "paid";
  if (order.payment_status === "cod_due") return "cod";
  if (order.payment_status === "requires_action") return "requires_action";
  if (order.payment_status === "pending") return "pending";
  if (order.payment_status === "cancelled") return "cancelled";
  if (order.payment_status === "failed" || last?.status === "failed") return "failed";
  return "pending";
}

const COPY = {
  paid: ["success", CheckCircle2, "Payment successful", "Your payment was confirmed."],
  cod: ["success", CheckCircle2, "Order placed: pay on delivery", "Nothing has been charged. Pay the courier in cash when the order arrives."],
  pending: ["info", Clock, "Payment pending", "We have not received confirmation yet. This order is NOT paid. Stock is held for you until the time shown below."],
  requires_action: ["warn", AlertTriangle, "More action needed to finish paying", "The provider needs you to complete a step before the payment can be confirmed. The order is NOT paid yet."],
  failed: ["error", XCircle, "Payment failed", "The payment was not completed. You can try again."],
  cancelled: ["error", XCircle, "Payment cancelled", "You cancelled the payment, so nothing was charged. You can try again or cancel the order."],
  order_cancelled: ["error", XCircle, "Order cancelled", "This order was cancelled (by you, by the store, or because the payment window ended) and its stock was released."],
  refund: ["warn", AlertTriangle, "Order cancelled: refund due", "This order was cancelled after a payment was received. The store will refund it to the account you paid from; this can take several days."],
};
const ONLINE_LABEL = { card: "Pay by card", mtn_momo: "Pay with MTN Mobile Money", airtel_money: "Pay with Airtel Money" };

export default function PaymentResult() {
  const { id } = useParams();
  const [order, setOrder] = useState(null);
  const [methods, setMethods] = useState([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [scenario, setScenario] = useState("success");
  const load = useCallback(async () => { try { setOrder(await api.order(id)); setError(""); } catch (e) { setError(e.message); } }, [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.paymentMethods().then(r => setMethods(r.methods)).catch(() => {}); }, []);

  const last = order?.payment_attempts?.[order.payment_attempts.length - 1];
  const awaitingOnline = !!order && last?.provider === "flutterwave" && last.status === "pending" && order.status !== "cancelled";
  const lastRef = last?.reference;

  // The customer just came back from the payment page (or is approving a mobile-money prompt): ask the server to check
  // with the provider now, then every 5 seconds for up to three minutes. The server, not this page, decides.
  useEffect(() => {
    if (!awaitingOnline) return undefined;
    let stopped = false, tries = 0;
    const tick = async () => {
      try { const r = await api.verifyPayment(lastRef); if (!stopped) setOrder(r.order); } catch { /* shown on the next manual check */ }
    };
    tick();
    const timer = setInterval(() => { if (++tries > 36) clearInterval(timer); else tick(); }, 5000);
    return () => { stopped = true; clearInterval(timer); };
  }, [awaitingOnline, lastRef]);

  async function run(fn) {
    setActionError(""); setBusy(true);
    try { await fn(); await load(); } catch (e) { setActionError(e.message); } finally { setBusy(false); }
  }
  async function payNow() {
    setActionError(""); setBusy(true);
    try { const { url } = await api.checkoutLink(lastRef); window.location.assign(url); }
    catch (e) { setActionError(e.message); setBusy(false); }
  }
  if (error) return <ErrorState error={error} onRetry={load}/>;
  if (!order) return <Loading text="Checking your payment…"/>;

  const state = paymentState(order);
  const [tone, Icon, title, text] = COPY[state];
  const simulatedOpen = last && last.provider === "simulated" && ["pending", "requires_action"].includes(last.status);
  const canRetry = ["failed", "cancelled"].includes(state) && order.status === "payment_failed";
  const onlineMethods = methods.filter(m => m.available && ONLINE_LABEL[m.id]);
  const simulatedAvailable = methods.some(m => m.id === "simulated" && m.available);
  return <article aria-labelledby="pay-title">
    <div className={`notice ${tone} pay-state`} role="status" data-testid={`payment-${state}`}><Icon size={22} aria-hidden="true"/>
      <div><h1 id="pay-title">{title}</h1><p>{text}{state === "paid" && last?.provider === "simulated" && " (This was a simulated payment: no real money moved.)"}</p></div></div>
    <dl className="totals-dl">
      <div><dt>Order</dt><dd data-testid="order-ref">{order.reference}</dd></div>
      <div><dt>Amount</dt><dd>{moneyC(order.total_cents, order.currency)}</dd></div>
      {last && <div><dt>Payment reference</dt><dd data-testid="payment-ref">{last.reference}</dd></div>}
      <div><dt>Order status</dt><dd>{order.status.replace(/_/g, " ")}</dd></div>
      {order.payment_due_at && ["pending", "requires_action", "failed", "cancelled"].includes(state) && order.status !== "cancelled" &&
        <div><dt>Stock held until</dt><dd>{when(order.payment_due_at)}</dd></div>}
    </dl>
    {order.payment_notice && <div className="notice info" role="note">{order.payment_notice}</div>}
    {last?.failure_reason && ["failed", "cancelled"].includes(state) && <p className="muted-text">Reason: {last.failure_reason}</p>}
    {actionError && <div className="notice error" role="alert">{actionError}</div>}

    {awaitingOnline && <section aria-label="Complete your payment" className="demo-scenario"><h2>Complete your payment</h2>
      <p className="muted-text">Pay on the provider's secure page. If you already paid or approved the prompt on your phone, this page updates by itself within a few seconds.</p>
      <div className="cart-actions">
        <button type="button" className="shop-btn" disabled={busy} onClick={payNow}>Pay now</button>
        <button type="button" className="shop-btn secondary" disabled={busy} onClick={() => run(async () => { const r = await api.verifyPayment(last.reference); setOrder(r.order); })}>I have paid: check status</button>
        <button type="button" className="shop-btn secondary" disabled={busy} onClick={() => run(() => api.cancelPayment(last.reference))}>Stop this payment</button></div></section>}

    {simulatedOpen && <section aria-label="Demonstration controls" className="demo-scenario"><h2>Demonstration controls</h2>
      <p className="muted-text">A real provider would answer by itself. Here you decide what the simulated provider says.</p>
      <div className="cart-actions">
        <button type="button" className="shop-btn" disabled={busy} onClick={() => run(() => api.simulatePayment(last.reference, "succeeded"))}>Simulate: payment approved</button>
        <button type="button" className="shop-btn secondary" disabled={busy} onClick={() => run(() => api.simulatePayment(last.reference, "failed"))}>Simulate: payment declined</button>
        <button type="button" className="shop-btn secondary" disabled={busy} onClick={() => run(() => api.simulatePayment(last.reference, "cancelled"))}>Simulate: customer cancels</button>
        <button type="button" className="shop-btn secondary" disabled={busy} onClick={load}>Refresh status</button></div></section>}

    {canRetry && <section aria-label="Try again" className="demo-scenario"><h2>Try again</h2>
      <div className="cart-actions">
        {onlineMethods.map(m => <button key={m.id} type="button" className="shop-btn" disabled={busy}
          onClick={() => run(async () => {
            const o = await api.payOrder(order.id, { method: m.id });
            const a = o.payment_attempts[o.payment_attempts.length - 1];
            const { url } = await api.checkoutLink(a.reference);
            window.location.assign(url);
          })}>{ONLINE_LABEL[m.id]}</button>)}
      </div>
      {simulatedAvailable && <>
        <label htmlFor="retry-scenario">Demonstration outcome</label>
        <select id="retry-scenario" value={scenario} onChange={e => setScenario(e.target.value)}>{SCENARIOS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        <div className="cart-actions"><button type="button" className="shop-btn" disabled={busy}
          onClick={() => run(() => api.payOrder(order.id, { method: "simulated", scenario }))}>Try the payment again</button></div></>}</section>}

    <div className="cart-actions">
      {(state === "paid" || state === "cod") && <Link className="shop-btn" to={`/shop/order-confirmation/${order.id}`}>View order confirmation</Link>}
      <Link className="shop-btn secondary" to={`/shop/orders/${order.id}`}>Order details</Link>
      <Link className="shop-btn secondary" to="/shop/orders">View my orders</Link>
      {["awaiting_payment", "payment_failed"].includes(order.status) &&
        <button type="button" className="shop-btn danger" disabled={busy} onClick={() => run(() => api.cancelOrder(order.id))}>Cancel order</button>}
    </div>
  </article>;
}
