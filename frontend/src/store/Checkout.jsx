import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Info } from "lucide-react";
import { EMAIL_RE, Field } from "../components/forms";
import { EmptyState, ErrorState, Loading } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useStore } from "../context/StoreContext";
import { ApiError, api } from "../services/api";
import { moneyC } from "../services/format";

const PHONE_RE = /^[0-9+()\s-]{7,20}$/;
const POSTAL_RE = /^[A-Za-z0-9 -]{3,12}$/;

export default function Checkout() {
  const { user } = useAuth();
  const { store, setCart, refreshCart } = useStore();
  const navigate = useNavigate();
  const [cart, setLocal] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [f, setF] = useState({ name: user?.user_metadata?.full_name || "", email: user?.email || "", phone: "", fulfilment: "delivery", line: "", city: "", postal: "" });
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState("");
  const [problems, setProblems] = useState([]);
  const [busy, setBusy] = useState(false);
  const set = k => e => setF({ ...f, [k]: e.target.value });

  const load = useCallback(async () => {
    try { const c = await api.cart(); setLocal(c); setCart(c); setLoadError(""); } catch (e) { setLoadError(e.message); }
  }, [setCart]);
  useEffect(() => { load(); }, [load]);

  if (loadError) return <ErrorState error={loadError} onRetry={load}/>;
  if (!cart) return <Loading text="Preparing checkout…"/>;
  if (!cart.items.length) return <EmptyState><h1>Nothing to check out</h1><Link className="shop-btn" to="/shop/products">Continue shopping</Link></EmptyState>;

  const delivery = f.fulfilment === "delivery";
  const fee = delivery ? cart.delivery_fee_cents : 0;
  const cities = store.delivery_cities || [];

  function validate() {
    const e = {};
    if (f.name.trim().length < 2) e.name = "Enter your full name";
    if (!EMAIL_RE.test(f.email.trim())) e.email = "Enter a valid email address";
    if (!PHONE_RE.test(f.phone.trim())) e.phone = "Enter a valid phone number";
    if (delivery) {
      if (f.line.trim().length < 5) e.line = "Enter your street address";
      if (!f.city.trim()) e.city = "Enter your city";
      else if (cities.length && !cities.some(c => c.toLowerCase() === f.city.trim().toLowerCase()))
        e.city = `We do not deliver to ${f.city.trim()} yet. Delivery areas: ${cities.join(", ")}. You can choose collection instead.`;
      if (!POSTAL_RE.test(f.postal.trim())) e.postal = "Enter a valid postal code";
    }
    return e;
  }

  async function submit(ev) {
    ev.preventDefault(); setSubmitError(""); setProblems([]);
    const e = validate(); setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      const body = { fulfilment: f.fulfilment, contact: { name: f.name.trim(), email: f.email.trim(), phone: f.phone.trim() },
        payment: { method: "simulated" } };
      if (delivery) body.address = { line: f.line.trim(), city: f.city.trim(), postal_code: f.postal.trim() };
      const order = await api.placeOrder(body);
      await refreshCart();
      navigate(`/shop/order-confirmation/${order.id}`, { replace: true });
    } catch (err) {
      setSubmitError(err.message);
      if (err instanceof ApiError && err.status === 409 && Array.isArray(err.body?.detail?.problems)) { setProblems(err.body.detail.problems); await load(); }
    } finally { setBusy(false); }
  }

  return <div>
    <h1>Checkout</h1>
    <div className="notice info demo-payment" role="note"><Info size={18} aria-hidden="true"/>
      <div><strong>Demonstration checkout.</strong> No card details are collected and no money is taken. The payment step is simulated and is not authorised by any bank.</div></div>
    <div className="checkout-grid">
      <form onSubmit={submit} noValidate aria-label="Checkout form">
        {submitError && <div className="notice error" role="alert">{submitError}
          {problems.length > 0 && <ul>{problems.map(p => <li key={p.product_id}>{p.message}</li>)}</ul>}
          {problems.length > 0 && <Link to="/shop/cart">Review your cart</Link>}</div>}
        <fieldset><legend>Contact details</legend>
          <Field label="Full name" error={errors.name}>{a => <input {...a} autoComplete="name" value={f.name} onChange={set("name")}/>}</Field>
          <Field label="Email address" error={errors.email}>{a => <input {...a} type="email" autoComplete="email" value={f.email} onChange={set("email")}/>}</Field>
          <Field label="Phone number" error={errors.phone}>{a => <input {...a} type="tel" autoComplete="tel" value={f.phone} onChange={set("phone")}/>}</Field>
        </fieldset>
        <fieldset><legend>Delivery or collection</legend>
          <label className="check"><input type="radio" name="fulfilment" value="delivery" checked={delivery} onChange={set("fulfilment")}/> Delivery ({cart.delivery_fee_note.split(".")[0]})</label>
          <label className="check"><input type="radio" name="fulfilment" value="collection" checked={!delivery} onChange={set("fulfilment")}/> Collect in store (free)</label>
          {delivery && <>
            <Field label="Street address" error={errors.line}>{a => <input {...a} autoComplete="street-address" value={f.line} onChange={set("line")}/>}</Field>
            <Field label="City" error={errors.city} hint={cities.length ? `We deliver to: ${cities.join(", ")}` : undefined}>{a => <input {...a} autoComplete="address-level2" list="cities" value={f.city} onChange={set("city")}/>}</Field>
            <datalist id="cities">{cities.map(c => <option key={c} value={c}/>)}</datalist>
            <Field label="Postal code" error={errors.postal}>{a => <input {...a} autoComplete="postal-code" value={f.postal} onChange={set("postal")}/>}</Field></>}
        </fieldset>
        <fieldset><legend>Payment</legend>
          <p>Demonstration payment (simulated). There is nothing to enter here.</p></fieldset>
        <button className="shop-btn" disabled={busy || cart.has_issues}>{busy ? "Placing order…" : "Place demonstration order"}</button>
        {cart.has_issues && <p className="field-error" role="alert">Fix the items in your cart first. <Link to="/shop/cart">Back to cart</Link></p>}
      </form>
      <aside className="summary" aria-label="Order summary"><h2>Order summary</h2>
        <ul>{cart.items.map(l => <li key={l.item_id}><span>{l.quantity} × {l.product.name}</span><span>{moneyC(l.line_total_cents, cart.currency)}</span></li>)}</ul>
        <dl><div><dt>Subtotal</dt><dd>{moneyC(cart.subtotal_cents, cart.currency)}</dd></div>
          <div><dt>{delivery ? "Delivery" : "Collection"}</dt><dd>{fee ? moneyC(fee, cart.currency) : "Free"}</dd></div>
          <div className="grand"><dt>Total</dt><dd>{moneyC(cart.subtotal_cents + fee, cart.currency)}</dd></div></dl>
        <p className="muted-text">Stock is checked again when you place the order.</p></aside>
    </div>
  </div>;
}
