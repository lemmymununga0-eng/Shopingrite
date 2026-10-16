// End-to-end workflow against REAL servers (backend + Vite). Steps run in order and share state.
import { expect, test } from "@playwright/test";
import { api, restartBackend, signInAs, signOut } from "./helpers.js";

test.describe.configure({ mode: "serial" });

let orderRef = "";
let orderId = "";
let milkId = 0;
let milkStockBefore = 0;
const MILK = "DEMO-DE-001";            // Full Cream Milk, 150 in the seed
const TX_REF = `E2E-${Date.now().toString().slice(-8)}`;

test("1-2. the store loads, is labelled as a demonstration, and products can be found by search", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/shop$/);
  await expect(page.getByRole("heading", { name: /fresh groceries/i })).toBeVisible();
  await expect(page.getByText(/independent demonstration store/i).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Shop by category" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search products" }).fill("milk");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page).toHaveURL(/search=milk/);
  const card = page.getByRole("article", { name: "Full Cream Milk" });
  await expect(card).toBeVisible();
  await expect(card.getByTestId("stock-badge")).toHaveText("In stock");
});

test("3. product page shows database stock; an out-of-stock product cannot be added", async ({ page }) => {
  await page.goto("/shop/products?search=milk");
  await page.getByRole("link", { name: "Full Cream Milk" }).first().click();
  await expect(page.getByRole("heading", { name: "Full Cream Milk" })).toBeVisible();
  await expect(page.getByTestId("stock-badge")).toHaveText("In stock");
  const r = await page.request.get(`http://127.0.0.1:8799/products?search=${MILK}`);
  const p = (await r.json()).items[0];
  milkId = p.id; milkStockBefore = p.available_quantity;
  expect(milkStockBefore).toBe(150);

  await page.goto("/shop/products?search=spinach");
  const spinach = page.getByRole("article", { name: "Baby Spinach" });
  await expect(spinach.getByTestId("stock-badge")).toHaveText("Out of stock");
  await expect(page.getByRole("button", { name: /unavailable: baby spinach is out of stock/i })).toBeDisabled();
  await spinach.getByRole("link", { name: "Baby Spinach", exact: true }).click();
  await expect(page.getByText(/out of stock right now/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /add to cart/i })).toHaveCount(0);
});

test("4. a shopper signs in (local demo), adds milk to the cart, and the server rejects an unavailable item", async ({ page }) => {
  await page.goto("/shop/products?search=milk");
  await page.getByRole("button", { name: /add to cart: full cream milk/i }).click();      // signed out -> sign-in first
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByText(/local demonstration sign-in/i)).toBeVisible();
  await page.getByRole("button", { name: "Customer (store)" }).click();
  await page.getByRole("button", { name: "Login" }).click();
  await expect(page).toHaveURL(/\/shop/);

  await page.goto(`/shop/products/${milkId}`);
  await page.getByLabel("Quantity", { exact: true }).fill("2");
  await page.getByRole("button", { name: /add to cart/i }).click();
  await expect(page.getByText(/added 2 × full cream milk/i)).toBeVisible();
  await expect(page.getByTestId("cart-count")).toHaveText("2");

  const spinach = (await (await page.request.get("http://127.0.0.1:8799/products?search=DEMO-FP-004")).json()).items[0];
  const rejected = await api(page, "POST", "/cart/items", { product_id: spinach.id, quantity: 1 });
  expect(rejected.status).toBe(409);
  expect(rejected.json.detail).toMatch(/out of stock/i);

  await page.goto("/shop/cart");
  await expect(page.getByRole("heading", { name: "Your cart" })).toBeVisible();
  await expect(page.getByLabel("Order totals")).toContainText("Subtotal");
});

test("5-6. checkout is clearly simulated, creates an order, persists it and reduces stock", async ({ page }) => {
  await signInAs(page, "Customer (store)");
  await page.goto("/shop/cart");
  await page.getByRole("button", { name: /proceed to checkout/i }).click();
  await expect(page).toHaveURL(/\/shop\/checkout/);
  await expect(page.getByText(/no card details are collected/i)).toBeVisible();
  await expect(page.getByLabel(/card number/i)).toHaveCount(0);

  await page.getByLabel("Phone number").fill("0821234567");
  await page.getByLabel("Street address").fill("12 Test Street");
  await page.getByLabel("City").fill("Johannesburg");
  await page.getByLabel("Postal code").fill("2000");
  await page.getByRole("button", { name: /place demonstration order/i }).click();

  await expect(page.getByText(/your demonstration order was placed/i)).toBeVisible();
  orderRef = (await page.getByTestId("order-ref").textContent()).trim();
  expect(orderRef).toMatch(/^ORD-[0-9A-F]{8}$/);
  await expect(page.getByText(/no card was used and no money was taken/i)).toBeVisible();
  orderId = page.url().split("/").pop();

  const o = await api(page, "GET", `/orders/${orderId}`);
  expect(o.status).toBe(200);
  expect(o.json.reference).toBe(orderRef);
  expect(o.json.payment_mode).toBe("SIMULATED");
  expect(o.json.items[0]).toMatchObject({ sku: MILK, quantity: 2 });
  const after = (await (await page.request.get(`http://127.0.0.1:8799/products/${milkId}`)).json()).available_quantity;
  expect(after).toBe(milkStockBefore - 2);
  expect((await api(page, "GET", "/cart")).json.items).toHaveLength(0);

  await page.goto("/shop/orders");
  await expect(page.getByRole("link", { name: orderRef })).toBeVisible();
});

test("7. a customer cannot reach the staff console, in the browser or through the API", async ({ page }) => {
  await signInAs(page, "Customer (store)");
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/shop$/);
  await page.goto("/security");
  await expect(page).toHaveURL(/\/shop$/);
  for (const url of ["/security/events", "/investigations", "/admin/users", "/inventory", "/reports/overview", "/audit", "/transactions"]) {
    expect((await api(page, "GET", url)).status, url).toBe(403);
  }
  expect((await api(page, "PATCH", "/inventory/1", { set_available: 999, reason: "attempted by customer" })).status).toBe(403);
  const noToken = await page.request.get("http://127.0.0.1:8799/orders");
  expect(noToken.status()).toBe(401);
});

test("8-9. a fraud analyst submits compatible model inputs and gets a real model response and a case", async ({ page }) => {
  await signInAs(page, "Fraud analyst");
  await expect(page).toHaveURL(/\/dashboard/);
  await page.getByRole("link", { name: "New Payment" }).click();
  await expect(page.getByText(/real model loaded/i)).toBeVisible();
  await page.getByLabel("Transaction Reference").fill(TX_REF);
  await page.getByLabel("Amount (ZAR)").fill("9000");
  await page.getByLabel("Transaction Hour (0–23)").fill("2");
  await page.getByLabel("Failed Attempts").fill("5");
  await page.getByLabel("Customer Average Spend (ZAR)").fill("100");
  await page.getByLabel("New Device?").selectOption("yes");
  await page.getByLabel("International Transaction?").selectOption("yes");
  await page.getByRole("button", { name: "Submit for Analysis" }).click();
  const result = page.getByText(/model fraud probability/i);
  await expect(result).toBeVisible();
  await expect(page.getByText(/model version: rf-/i)).toBeVisible();
  await expect(page.getByText(/not proof of fraud/i).first()).toBeVisible();
  const probability = await page.locator("text=Model fraud probability").locator("strong").textContent();
  expect(probability).toMatch(/^\d+(\.\d)?%$/);
  await expect(page.getByText(/an alert was created for review/i)).toBeVisible();
});

test("10. the flagged prediction appears in the Investigation Centre and moves through its workflow", async ({ page }) => {
  await signInAs(page, "Fraud analyst");
  await page.getByRole("link", { name: "Investigations" }).click();
  await expect(page.getByRole("heading", { name: "Investigation Centre" })).toBeVisible();
  const row = page.getByRole("row", { name: new RegExp(`Fraud prediction.*${TX_REF}`) });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: /^Open CASE-/ }).click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.getByText(/not proof of wrongdoing/i).first()).toBeVisible();
  await dlg.getByRole("button", { name: "Assign to me" }).click();
  await expect(dlg.getByRole("button", { name: "Unassign" })).toBeVisible();
  await dlg.getByLabel("Add a note").fill("Reviewed the transaction pattern; contacting the customer.");
  await dlg.getByLabel("Status").selectOption("investigating");
  await dlg.getByRole("button", { name: "Save changes" }).click();
  await expect(dlg.locator(".note-list").getByText("Reviewed the transaction pattern; contacting the customer.")).toBeVisible();   // the saved note, not the textarea
  await dlg.getByLabel("Status").selectOption("false_positive");
  await dlg.getByRole("button", { name: "Save changes" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("row", { name: new RegExp(`False positive.*${TX_REF}`) })).toBeVisible();
  // the older alert screen reflects the case outcome
  await page.getByRole("link", { name: "Reports" }).click();
  await expect(page.getByRole("heading", { name: "Fraud signals" })).toBeVisible();
});

test("11-12. ScamWatch with the controlled mock provider reports, labels simulation and persists", async ({ page }) => {
  await signInAs(page, "Security analyst");
  await page.getByRole("link", { name: "ScamWatch" }).click();
  await page.getByLabel("Website address").fill("bad.example/win-a-prize");
  await page.getByRole("button", { name: "Check website" }).click();
  await expect(page.getByText(/known threat reported by a provider/i)).toBeVisible();
  await expect(page.getByText(/includes simulated provider results/i)).toBeVisible();
  await expect(page.getByText(/does not mean a website is safe/i)).toBeVisible();
  await page.getByRole("button", { name: "Report this website" }).click();
  await expect(page.getByText(/report was saved for review/i)).toBeVisible();
  await expect(page.getByRole("cell", { name: "http://bad.example/win-a-prize" })).toBeVisible();

  // a private address is rejected with a clear message, never fetched
  await page.getByLabel("Website address").fill("http://169.254.169.254/latest/meta-data");
  await page.getByRole("button", { name: "Check website" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /not accepted/i })).toBeVisible();

  // reviewing it is a security-analyst action
  await page.getByRole("button", { name: "Review bad.example" }).click();
  await page.getByRole("dialog").getByLabel("Review status").selectOption("reviewed_malicious");
  await page.getByRole("dialog").getByLabel("Analyst notes").fill("Confirmed phishing lure.");
  await page.getByRole("button", { name: "Save review" }).click();
  await expect(page.getByRole("cell", { name: "Confirmed malicious" })).toBeVisible();
});

test("13-14. security events are recorded and shown to the right role; other roles are refused", async ({ page }) => {
  // a failed sign-in creates a security event
  await signOut(page);
  await page.getByLabel("Email Address").fill("admin@example.com");
  await page.getByRole("textbox", { name: "Password" }).fill("definitely-wrong");
  await page.getByRole("button", { name: "Login" }).click();
  await expect(page.getByRole("alert")).toContainText(/incorrect email or password/i);

  await signInAs(page, "Security analyst");
  await page.getByRole("link", { name: "Security Monitor" }).click();
  await expect(page.getByRole("heading", { name: "Security Monitor" })).toBeVisible();
  await page.getByLabel("Category").selectOption("authentication");
  const failed = page.getByRole("row", { name: /auth\.login_failed/ }).first();
  await expect(failed).toBeVisible();
  await failed.getByRole("button", { name: /details for event/i }).click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.getByText(/correlation id/i)).toBeVisible();
  await expect(dlg.locator("code").first()).not.toHaveText("—");
  await page.keyboard.press("Escape");
  await expect(page.getByText(/does not monitor|not monitor any network/i)).toBeVisible();

  // role boundaries
  await expect(page.getByRole("link", { name: "Users & Roles" })).toHaveCount(0);
  expect((await api(page, "GET", "/admin/users")).status).toBe(403);
  expect((await api(page, "PATCH", "/inventory/1", { set_available: 1, reason: "nope nope" })).status).toBe(403);
  expect((await api(page, "GET", "/audit")).status).toBe(200);

  await signInAs(page, "Fraud analyst");
  expect((await api(page, "GET", "/security/events")).status).toBe(403);
  await page.goto("/security");
  await expect(page.getByRole("alert").first()).toContainText(/permission/i);

  await signInAs(page, "Administrator");
  await page.getByRole("link", { name: "Users & Roles" }).click();
  await expect(page.getByRole("heading", { name: "Users & Roles" })).toBeVisible();
  await expect(page.getByLabel("Role for admin@example.com")).toBeDisabled();
});

test("administrator adjusts stock with an audited reason", async ({ page }) => {
  await signInAs(page, "Administrator");
  await page.getByRole("link", { name: "Inventory & Orders" }).click();
  await page.getByLabel("Search product or SKU").fill("DEMO-BK-001");
  await page.getByRole("button", { name: "Adjust Brown Bread" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("New available quantity").fill("77");
  await dlg.getByLabel(/reason/i).fill("e2e stock count");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("row", { name: /Brown Bread/ })).toContainText("77");
  await page.getByRole("link", { name: "Audit Trail" }).click();
  await expect(page.getByRole("row", { name: /inventory\.adjusted/ }).first()).toContainText("77");
});

test("15-16. after the backend restarts, orders, stock, cases and scam reports are still there", async ({ page }) => {
  await restartBackend();
  await signInAs(page, "Customer (store)");
  const o = await api(page, "GET", `/orders/${orderId}`);
  expect(o.status).toBe(200);
  expect(o.json.reference).toBe(orderRef);
  const stockNow = (await (await page.request.get(`http://127.0.0.1:8799/products/${milkId}`)).json()).available_quantity;
  expect(stockNow).toBe(milkStockBefore - 2);
  await page.goto("/shop/orders");
  await expect(page.getByRole("link", { name: orderRef })).toBeVisible();

  await signInAs(page, "Security analyst");
  const cases = await api(page, "GET", "/investigations?page_size=100");
  expect(cases.json.items.some(c => c.summary.includes(TX_REF) && c.status === "false_positive")).toBe(true);
  expect(cases.json.items.some(c => c.source_type === "scamwatch_report")).toBe(true);
  const reports = await api(page, "GET", "/scamwatch/reports");
  expect(reports.json.items[0]).toMatchObject({ domain: "bad.example", review_status: "reviewed_malicious" });
  const audit = await api(page, "GET", "/audit?action=case.status_changed");
  expect(audit.json.total).toBeGreaterThanOrEqual(2);
  const events = await api(page, "GET", "/security/events?category=authentication");
  expect(events.json.items.some(e => e.event_type === "auth.login_failed")).toBe(true);
  expect((await page.request.get("http://127.0.0.1:8799/products?page_size=60")).ok()).toBe(true);
  expect((await (await page.request.get("http://127.0.0.1:8799/products?page_size=60")).json()).total).toBe(40);   // seed did not duplicate
});
