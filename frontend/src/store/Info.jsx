import { Link, useParams } from "react-router-dom";
import { useStore } from "../context/StoreContext";
import { moneyC } from "../services/format";

/** Delivery, privacy, terms and contact. A demonstration store says it is one; a live store shows its own details from
 *  the server's settings (STORE_CONTACT_*). The live wording is a plain starting point: have it reviewed for your business. */
export default function Info() {
  const { topic } = useParams();
  const { store } = useStore();
  const who = store.legal_name || store.name;
  const cities = (store.delivery_cities || []).join(", ") || "the cities we list at checkout";
  const fee = moneyC(store.delivery_fee_cents || 0, store.currency);
  const free = moneyC(store.free_delivery_over_cents || 0, store.currency);

  const demo = {
    delivery: ["Delivery and collection", <>
      <p>Home delivery is offered in: {cities}. Collection is free.</p>
      <p>The delivery fee is {fee}, free for orders over {free}.</p>
      <p>This is a demonstration store: no goods are shipped and no courier is connected. Any delivery time shown is an estimate, not a live logistics promise.</p></>],
    privacy: ["Privacy", <>
      <p>This demonstration keeps your name, contact details, address and orders in its own database so the order can be shown back to you and to staff reviewing it. Staff screens mask phone numbers and emails by default.</p>
      <p>No card numbers, PINs or one-time codes are ever requested. Do not enter real payment details anywhere in this demonstration.</p></>],
    terms: ["Terms of use", <>
      <p>This store is an independent demonstration. Products, prices and stock are sample data. Prices marked "Demo price" are estimates, not market prices. Orders create no real obligation and no money is taken.</p>
      <p>It is not affiliated with, endorsed by, or connected to Shoprite, Pick n Pay or any other retailer.</p></>],
    contact: ["Contact", <><p>This is a demonstration project, so there is no live customer-service line.</p></>],
  };

  const live = {
    delivery: ["Delivery and collection", <>
      <p>We deliver in: {cities}. Collection from the store is free.</p>
      <p>The delivery fee is {fee}; delivery is free for orders over {free}.</p>
      <p>Delivery times are estimates. If we cannot deliver or an item is unavailable, we will contact you on the phone number you gave at checkout.</p></>],
    privacy: ["Privacy", <>
      <p>{who} collects your name, e-mail address, phone number, delivery address and order history to take and deliver your orders and to protect against fraud. Only our staff who need it can see it; staff screens hide phone numbers and e-mail addresses unless a role requires them.</p>
      <p>Card and mobile-money details are entered on our payment provider's secure page. We never see or store card numbers, PINs or one-time codes; we keep only a payment reference and whether it succeeded.</p>
      <p>To see, correct or delete your information, contact us using the details on the Contact page.</p></>],
    terms: ["Terms of use", <>
      <p>Prices are in {store.currency} and include the items shown; delivery is charged separately as shown at checkout. An order is accepted when its payment is confirmed (or, for cash on delivery, when you place it). We may cancel an order if an item is unavailable or a payment cannot be verified, and we will refund any money taken.</p>
      <p>You can cancel an order until it is being prepared. Refunds go back to the account you paid from and can take several days to arrive.</p>
      <p>Orders are scored by automatic rules to spot possible fraud; a person reviews anything flagged before we act on it.</p></>],
    contact: ["Contact", <>
      <p>{who}</p>
      {store.contact_email && <p>E-mail: <a href={`mailto:${store.contact_email}`}>{store.contact_email}</a></p>}
      {store.contact_phone && <p>Phone: {store.contact_phone}</p>}
      {store.contact_address && <p>Address: {store.contact_address}</p>}
      {!store.contact_email && !store.contact_phone && <p>Contact details have not been set for this store yet.</p>}</>],
  };

  const page = (store.is_demo ? demo : live)[topic];
  if (!page) return <div className="not-found"><div><h1>Page not found</h1><Link className="shop-btn" to="/shop">Back to the store</Link></div></div>;
  return <article className="info-page"><h1>{page[0]}</h1>{page[1]}</article>;
}
