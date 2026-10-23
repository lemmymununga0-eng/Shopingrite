import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Info, ShieldCheck } from "lucide-react";
import { EMAIL_RE, Field } from "../components/forms";
import { EmptyState, ErrorState, Loading } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useStore } from "../context/StoreContext";
import { ApiError, api } from "../services/api";
import { moneyC } from "../services/format";

/** Zambian mobile or landline: 097…, +260 97…, 260…; spaces, dashes and brackets are ignored. */
const PHONE_RE = /^(?:\+?260|0)[279]\d{8}$/;
export const SCENARIOS = [["success", "Payment succeeds"], ["failure", "Payment is declined"], ["pending", "Payment stays pending"],
  ["cancelled", "Customer cancels the payment"], ["action_required", "Extra customer action is required"]];
const STEPS = ["Your details", "Delivery", "Review", "Payment"];

export default function Checkout() {
  const { user } = useAuth();
  const { store, setCart, refreshCart } = useStore();
  const navigate = useNavigate();
  const [cart, setLocal] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [step, setStep] = useState(0);
  const [f, setF] = useState({ name: user?.user_metadata?.full_name || "", email: user?.email || "", phone: "", fulfilment: "delivery",
    line: "", city: "", area: "", instructions: "" });
  const [pay, setPay] = useState({ method: "simulated", scenario: "success" });
  const [methods, setMethods] = useState(null);
  const picked = useRef(false);          // once the customer chooses a method, the loaded default never overrides it
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState("");
  const [problems, setProblems] = useState([]);
  const [busy, setBusy] = useState(false);
  const keyRef = useRef({ body: "", key: "" });
  const set = k => e => setF({ ...f, [k]: e.target.value });

  const load = useCallback(async () => {
    try { const c = await api.cart(); setLocal(c); setCart(c); setLoadError(""); } catch (e) { setLoadError(e.message); }
  }, [setCart]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.paymentMethods().then(r => {
      setMethods(r.methods);
      // Prefer a real online method, then cash on delivery, and only then the demonstration provider.
      const first = ["card", "mtn_momo", "airtel_money", "cod", "simulated"].map(id => r.methods.find(m => m.id === id)).find(m => m?.available);
      if (first && !picked.current) setPay(p => ({ ...p, method: first.id }));
    }).catch(() => setMethods([]));
  }, []);

  if (loadError) return <ErrorState error={loadError} onRetry={load}/>;
  if (!cart) return <Loading text="Preparing checkout…"/>;
  if (!cart.items.length) return <EmptyState><h1>Nothing to check out</h1><Link className="shop-btn" to="/shop/products">Continue shopping</Link></EmptyState>;

  const delivery = f.fulfilment === "delivery";
  const fee = delivery ? cart.delivery_fee_cents : 0;
  const cities = store.delivery_cities || [];

  function validate(which) {
    const e = {};
    if (which === 0) {
      if (f.name.trim().length < 2) e.name = "Enter your full name";
      if (!EMAIL_RE.test(f.email.trim())) e.email = "Enter a valid email address";
      if (!PHONE_RE.test(f.phone.replace(/[\s().-]/g, ""))) e.phone = "Enter a valid Zambian phone number, for example 0971 234 567 or +260 971 234 567";
    }
    if (which === 1 && delivery) {
      if (f.line.trim().length < 5) e.line = "Enter your street address";
      if (!f.city.trim()) e.city = "Enter your city";
      else if (cities.length && !cities.some(c => c.toLowerCase() === f.city.trim().toLowerCase()))
        e.city = `We do not deliver to ${f.city.trim()} yet. Delivery areas: ${cities.join(", ")}. You can choose collection instead.`;
    }
    return e;
  }
  function next() {
    const e = validate(step); setErrors(e);
    if (!Object.keys(e).length) setStep(step + 1);
  }
  function back() { setErrors({}); setSubmitError(""); setStep(step - 1); }

  function buildBody() {
    const body = { fulfilment: f.fulfilment, contact: { name: f.name.trim(), email: f.email.trim(), phone: f.phone.trim() },
      payment: pay.method === "simulated" ? { method: "simulated", scenario: pay.scenario } : { method: pay.method } };
    if (delivery) {
      body.address = { line: f.line.trim(), city: f.city.trim() };
      if (f.area.trim()) body.area = f.area.trim();
      if (f.instructions.trim()) body.delivery_instructions = f.instructions.trim();
    }
    return body;
  }

  async function submit(ev) {
    ev.preventDefault(); setSubmitError(""); setProblems([]);
    const e = { ...validate(0), ...validate(1) }; setErrors(e);
    if (Object.keys(e).length) { setStep(Object.keys(validate(0)).length ? 0 : 1); return; }
    const body = buildBody();
    const text = JSON.stringify(body);
    // One key per distinct order request: a double click or a retry after a network error replays the same order.
    if (keyRef.current.body !== text) keyRef.current = { body: text, key: crypto.randomUUID() };
    setBusy(true);
    try {
      const order = await api.placeOrder(body, keyRef.current.key);
      await refreshCart();
      const settled = order.payment_status === "paid" || order.payment_status === "cod_due";
      const last = order.payment_attempts?.[order.payment_attempts.length - 1];
      if (last?.provider === "flutterwave" && last.status === "pending") {
        // Real payment: the customer pays on the provider's secure page and is sent back to /shop/payment/:id.
        try { const { url } = await api.checkoutLink(last.reference); window.location.assign(url); return; }
        catch { /* the payment page offers a "Pay now" button to try again */ }
      }
      navigate(settled ? `/shop/order-confirmation/${order.id}` : `/shop/payment/${order.id}`, { replace: true });
    } catch (err) {
      setSubmitError(err.message);
      if (err instanceof ApiError && err.status === 409 && Array.isArray(err.body?.detail?.problems)) { setProblems(err.body.detail.problems); await load(); }
    } finally { setBusy(false); }
  }

  const selected = (methods || []).find(m => m.id === pay.method);
  return <div>
    <h1>Checkout</h1>
    {store.is_demo && <div className="notice info demo-payment" role="note"><Info size={18} aria-hidden="true"/>
      <div><strong>Demonstration checkout.</strong> No card details are collected and no money is taken. The payment step is simulated and is not authorised by any bank.</div></div>}
    <ol className="steps" aria-label="Checkout steps">{STEPS.map((s, i) =>
      <li key={s} aria-current={i === step ? "step" : undefined} className={i < step ? "done" : i === step ? "current" : ""}><span>{i + 1}</span> {s}</li>)}</ol>
    <div className="checkout-grid">
      <form onSubmit={submit} noValidate aria-label="Checkout form">
        {submitError && <div className="notice error" role="alert">{submitError}
          {problems.length > 0 && <ul>{problems.map(p => <li key={p.product_id}>{p.message}</li>)}</ul>}
          {problems.length > 0 && <Link to="/shop/cart">Review your cart</Link>}</div>}

        {step === 0 && <fieldset><legend>Your details</legend>
          <Field label="Full name" error={errors.name}>{a => <input {...a} autoComplete="name" value={f.name} onChange={set("name")}/>}</Field>
          <Field label="Email address" error={errors.email}>{a => <input {...a} type="email" autoComplete="email" value={f.email} onChange={set("email")}/>}</Field>
          <Field label="Phone number" error={errors.phone} hint="Zambian number, for example 0971 234 567">{a => <input {...a} type="tel" autoComplete="tel" value={f.phone} onChange={set("phone")}/>}</Field>
        </fieldset>}

        {step === 1 && <fieldset><legend>Delivery or collection</legend>
          <label className="check"><input type="radio" name="fulfilment" value="delivery" checked={delivery} onChange={set("fulfilment")}/> Delivery ({cart.delivery_fee_note.split(".")[0]})</label>
          <label className="check"><input type="radio" name="fulfilment" value="collection" checked={!delivery} onChange={set("fulfilment")}/> Collect in store (free)</label>
          {delivery ? <>
            <Field label="Street address" error={errors.line}>{a => <input {...a} autoComplete="street-address" value={f.line} onChange={set("line")}/>}</Field>
            <Field label="City" error={errors.city} hint={cities.length ? `We deliver to: ${cities.join(", ")}` : undefined}>{a => <input {...a} autoComplete="address-level2" list="cities" value={f.city} onChange={set("city")}/>}</Field>
            <datalist id="cities">{cities.map(c => <option key={c} value={c}/>)}</datalist>
            <Field label="Area or neighbourhood (optional)">{a => <input {...a} value={f.area} maxLength={80} onChange={set("area")}/>}</Field>
            <Field label="Delivery instructions (optional)">{a => <textarea {...a} rows={2} maxLength={300} value={f.instructions} onChange={set("instructions")}/>}</Field>
            <p className="muted-text">Delivery time is an estimate.{store.is_demo && " This is a demonstration store, not a live courier promise."}</p></>
            : <p className="muted-text">Collection in store. Follow the status of your order under My orders; the store may phone you when it is ready.</p>}
        </fieldset>}

        {step === 2 && <fieldset><legend>Review your order</legend>
          <ul className="review-list">{cart.items.map(l => <li key={l.item_id}><span>{l.quantity} × {l.product.name}{l.product.pack_size ? ` (${l.product.pack_size})` : ""}</span><span>{moneyC(l.line_total_cents, cart.currency)}</span></li>)}</ul>
          <p><strong>{f.name}</strong> · {f.email} · {f.phone}</p>
          <p>{delivery ? <>Delivery to {f.line}, {f.city}{f.area ? `, ${f.area}` : ""}{f.instructions ? ` (${f.instructions})` : ""}</> : "Collect in store"}</p>
          <p className="muted-text">Prices and stock are checked again on the server when you place the order.</p>
        </fieldset>}

        {step === 3 && <fieldset><legend>Payment method</legend>
          {methods === null ? <Loading text="Loading payment methods…"/> : <ul className="pay-methods">
            {methods.map(m => <li key={m.id}><label className="check"><input type="radio" name="pay-method" value={m.id} checked={pay.method === m.id}
              disabled={!m.available} onChange={() => { picked.current = true; setPay({ ...pay, method: m.id }); }}/> {m.label}{m.mode === "SIMULATED" && " (no real money)"}</label>
              {!m.available && <small className="muted-text"> Not available: {m.reason}</small>}</li>)}</ul>}
          {selected?.id === "simulated" && <div className="demo-scenario">
            <Field label="Demonstration outcome" hint="Only in this demo: choose what the simulated provider answers.">{a =>
              <select {...a} value={pay.scenario} onChange={e => setPay({ ...pay, scenario: e.target.value })}>{SCENARIOS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>}</Field>
            <p className="muted-text">Nothing to enter here: no card number, PIN or one-time code is ever requested.</p></div>}
          {selected?.id === "cod" && <p className="muted-text">Pay the courier in cash when the order arrives. Nothing is charged now.</p>}
          {selected && ["card", "mtn_momo", "airtel_money"].includes(selected.id) && <p className="muted-text">
            After you place the order you go to the payment provider's secure page to pay{selected.id === "card" ? " by card" : " with mobile money"}.
            We never see or store your card number, PIN or one-time code.
            {selected.mode === "TEST" && " TEST MODE: no real money is taken."}</p>}
        </fieldset>}

        <div className="wizard-actions">
          {step > 0 && <button type="button" className="shop-btn secondary" onClick={back} disabled={busy}>Back</button>}
          {/* Distinct keys and explicit types: React must NOT reuse the Continue element as the submit button, or the
              same click that moves to the payment step would also submit the form and place the order. */}
          {step < 3 ? <button key="continue" type="button" className="shop-btn" onClick={next}>Continue</button>
            : <button key="place" type="submit" className="shop-btn" disabled={busy || cart.has_issues || !selected?.available}>{busy ? "Placing order…" : selected?.mode === "SIMULATED" ? "Place demonstration order" : selected?.mode === "COD" ? "Place order" : "Place order and pay"}</button>}
        </div>
        {cart.has_issues && <p className="field-error" role="alert">Fix the items in your cart first. <Link to="/shop/cart">Back to cart</Link></p>}
      </form>
      <aside className="summary" aria-label="Order summary"><h2>Order summary</h2>
        <ul>{cart.items.map(l => <li key={l.item_id}><span>{l.quantity} × {l.product.name}</span><span>{moneyC(l.line_total_cents, cart.currency)}</span></li>)}</ul>
        <dl><div><dt>Subtotal</dt><dd>{moneyC(cart.subtotal_cents, cart.currency)}</dd></div>
          <div><dt>{delivery ? "Delivery" : "Collection"}</dt><dd>{fee ? moneyC(fee, cart.currency) : "Free"}</dd></div>
          <div className="grand"><dt>Total</dt><dd>{moneyC(cart.subtotal_cents + fee, cart.currency)}</dd></div></dl>
        <p className="muted-text">Stock is checked again when you place the order.</p>
        <p className="secure-note"><ShieldCheck size={16} aria-hidden="true"/> Secure checkout. We never see or store your card number, PIN or one-time code.</p></aside>
    </div>
  </div>;
}
