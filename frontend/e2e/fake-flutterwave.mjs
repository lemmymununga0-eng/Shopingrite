// A tiny stand-in for Flutterwave used ONLY by the browser tests (never deployed). It implements just what the store calls:
//   POST /v3/payments                              -> a hosted page link
//   GET  /pay/:tx_ref                              -> a page with Approve / Decline / Cancel buttons (what the customer would see)
//   GET  /v3/transactions/verify_by_reference      -> the result
//   POST /v3/transactions/:id/refund               -> a refund
// After the customer approves or declines, it also POSTs a webhook to the store with the shared secret hash, exactly like
// the real service, so the "redirect back + webhook" race is exercised for real.
import http from "node:http";

const PORT = Number(process.env.FAKE_FLW_PORT || 8798);
const KEY = process.env.FAKE_FLW_KEY || "FLWSECK_TEST-e2e";
const HOOK_URL = process.env.FAKE_FLW_WEBHOOK_URL || "http://127.0.0.1:8799/payments/webhooks/flutterwave";
const HOOK_HASH = process.env.FAKE_FLW_WEBHOOK_HASH || "e2e-hook-hash";
const txns = new Map();     // tx_ref -> { amount, currency, redirect_url, status, id }
const refunds = [];
let nextId = 880000;

const json = (res, code, body) => { res.writeHead(code, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
const readBody = req => new Promise(r => { let b = ""; req.on("data", c => (b += c)); req.on("end", () => r(b)); });

async function fireWebhook(t) {
  try {
    await fetch(HOOK_URL, { method: "POST", headers: { "content-type": "application/json", "verif-hash": HOOK_HASH },
      body: JSON.stringify({ event: "charge.completed", data: { id: t.id, tx_ref: t.tx_ref, status: t.status, amount: t.amount, currency: t.currency } }) });
  } catch { /* the store being down is the store's problem; Flutterwave would retry */ }
}

const page = t => `<!doctype html><meta charset="utf-8"><title>Fake Flutterwave</title>
<h1>Fake payment page (browser tests only)</h1><p>Pay <strong data-testid="amount">${t.currency} ${t.amount}</strong> for <span data-testid="ref">${t.tx_ref}</span></p>
<form method="post" action="/pay/${t.tx_ref}/approve"><button type="submit">Approve payment</button></form>
<form method="post" action="/pay/${t.tx_ref}/decline"><button type="submit">Decline payment</button></form>
<form method="post" action="/pay/${t.tx_ref}/cancel"><button type="submit">Cancel and go back</button></form>`;

const back = (t, status) => `${t.redirect_url}?status=${status}&tx_ref=${encodeURIComponent(t.tx_ref)}${status === "cancelled" ? "" : `&transaction_id=${t.id}`}`;

http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const authed = req.headers.authorization === `Bearer ${KEY}`;
  try {
    if (req.method === "GET" && url.pathname === "/health") return json(res, 200, { ok: true });
    if (req.method === "POST" && url.pathname === "/v3/payments") {
      if (!authed) return json(res, 401, { status: "error", message: "Invalid authorization key", data: null });
      const b = JSON.parse(await readBody(req));
      if (!b.tx_ref || !b.amount || b.currency !== "ZMW") return json(res, 400, { status: "error", message: "Invalid payload", data: null });
      txns.set(b.tx_ref, { tx_ref: b.tx_ref, amount: b.amount, currency: b.currency, redirect_url: b.redirect_url, status: "pending", id: ++nextId, options: b.payment_options });
      return json(res, 200, { status: "success", message: "Hosted Link", data: { link: `http://127.0.0.1:${PORT}/pay/${b.tx_ref}` } });
    }
    if (req.method === "GET" && url.pathname.startsWith("/pay/")) {
      const t = txns.get(decodeURIComponent(url.pathname.split("/")[2]));
      if (!t) { res.writeHead(404); return res.end("unknown payment"); }
      res.writeHead(200, { "content-type": "text/html" }); return res.end(page(t));
    }
    if (req.method === "POST" && url.pathname.startsWith("/pay/")) {
      const [, , ref, action] = url.pathname.split("/");
      const t = txns.get(decodeURIComponent(ref));
      if (!t) { res.writeHead(404); return res.end("unknown payment"); }
      if (action === "approve") t.status = "successful";
      if (action === "decline") t.status = "failed";
      if (action === "cancel") { res.writeHead(303, { location: back(t, "cancelled") }); return res.end(); }
      fireWebhook(t);                                       // like the real service, in addition to the redirect
      res.writeHead(303, { location: back(t, t.status) });
      return res.end();
    }
    if (req.method === "GET" && url.pathname === "/v3/transactions/verify_by_reference") {
      if (!authed) return json(res, 401, { status: "error", message: "Invalid authorization key", data: null });
      const t = txns.get(url.searchParams.get("tx_ref"));
      if (!t || t.status === "pending") return json(res, 400, { status: "error", message: "No transaction was found for this id", data: null });
      return json(res, 200, { status: "success", message: "Transaction fetched successfully",
        data: { id: t.id, tx_ref: t.tx_ref, amount: t.amount, currency: t.currency, status: t.status, payment_type: "mobilemoneyzm", processor_response: t.status === "failed" ? "Declined" : "Approved" } });
    }
    if (req.method === "POST" && /^\/v3\/transactions\/\d+\/refund$/.test(url.pathname)) {
      if (!authed) return json(res, 401, { status: "error", message: "Invalid authorization key", data: null });
      refunds.push(url.pathname);
      return json(res, 200, { status: "success", message: "Transaction refund initiated", data: { id: refunds.length, status: "completed", amount_refunded: 0 } });
    }
    if (req.method === "GET" && url.pathname === "/__refunds") return json(res, 200, { refunds });
    res.writeHead(404); res.end("not found");
  } catch (e) { json(res, 500, { status: "error", message: String(e), data: null }); }
}).listen(PORT, "127.0.0.1", () => console.log(`fake flutterwave on ${PORT}`));
