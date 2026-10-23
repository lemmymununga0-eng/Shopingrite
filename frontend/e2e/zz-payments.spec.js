// Real-payment journeys in a real browser: the store's API talks to a local stand-in for Flutterwave
// (e2e/fake-flutterwave.mjs), which serves a "hosted payment page" and sends a webhook like the real service does.
// Nothing here proves Flutterwave's own behaviour: that needs their sandbox (docs/DEPLOYMENT.md, acceptance test).
import { expect, test } from "@playwright/test";
import { API, FAKE_FLW, api, signInAs } from "./helpers.js";

test.describe.configure({ mode: "serial" });

const product = async (page, sku) => (await (await page.request.get(`${API}/products?search=${sku}`)).json()).items[0];
const stockOf = async (page, sku) => (await product(page, sku)).available_quantity;
const refunds = async page => (await (await page.request.get(`${FAKE_FLW.url}/__refunds`)).json()).refunds;

/** Signed-in customer: put `qty` of `sku` in the cart through the API, then walk the four checkout steps for collection. */
async function toPaymentStep(page, sku, qty = 1) {
  await signInAs(page, "Customer (store)");
  const p = await product(page, sku);
  expect((await api(page, "POST", "/cart/items", { product_id: p.id, quantity: qty })).status).toBeLessThan(300);
  await page.goto("/shop/checkout");
  await page.getByLabel("Phone number").fill("0971234567");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel(/collect in store/i).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Payment method" }).or(page.getByText("Payment method").first())).toBeVisible();
}
const orderIdFromUrl = page => page.url().split("?")[0].split("/").pop();

test("a customer pays by card on the provider's page and the order is confirmed", async ({ page }) => {
  const before = await stockOf(page, "DEMO-BK-002");
  await toPaymentStep(page, "DEMO-BK-002", 2);
  await expect(page.getByRole("radio", { name: /visa \/ mastercard/i })).toBeChecked();      // real payment is the default
  await expect(page.getByText(/after you place the order you go to the payment provider/i)).toBeVisible();
  await expect(page.getByLabel(/card number|cvv/i)).toHaveCount(0);                            // this site never asks for card data
  await page.getByRole("button", { name: "Place order and pay" }).click();

  await page.waitForURL(/127\.0\.0\.1:8798\/pay\//);
  await expect(page.getByText(/fake payment page/i)).toBeVisible();
  await page.getByRole("button", { name: "Approve payment" }).click();

  await page.waitForURL(/\/shop\/payment\//);
  await expect(page.getByTestId("payment-paid")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/test mode/i).first()).toBeVisible();
  const id = orderIdFromUrl(page);
  const o = (await api(page, "GET", `/orders/${id}`)).json;
  expect(o).toMatchObject({ status: "confirmed", payment_status: "paid", payment_method: "card", payment_mode: "TEST" });
  expect(o.payment_attempts).toHaveLength(1);
  expect(o.payment_attempts[0]).toMatchObject({ provider: "flutterwave", status: "succeeded" });
  expect(await stockOf(page, "DEMO-BK-002")).toBe(before - 2);

  await page.getByRole("link", { name: /view order confirmation/i }).click();
  await expect(page.getByText(/thank you\. your order was placed/i)).toBeVisible();
});

test("staff see that order with its payment and a risk score, with the customer's contact masked", async ({ page }) => {
  await signInAs(page, "Fraud analyst");
  await page.getByRole("link", { name: "Orders & Risk", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Orders & Risk" })).toBeVisible();
  await page.getByRole("button", { name: /^Open order ORD-/ }).first().click();       // newest first
  const dlg = page.getByRole("dialog");
  await expect(dlg.getByText(/risk assessment/i)).toBeVisible();
  await expect(dlg.getByText(/not machine learning/i)).toBeVisible();
  await expect(dlg.getByText(/PAY-[0-9A-F]{8}/)).toBeVisible();
  await expect(dlg.getByText(/masked for your role/i)).toBeVisible();
  await expect(dlg.getByText("0971234567")).toHaveCount(0);
  await expect(dlg.getByRole("button", { name: /refund|cancel order|start picking/i })).toHaveCount(0);   // analysts only read
  // no model is trained here: the console must say so instead of showing a score
  const models = dlg.getByRole("region", { name: "Model results" });
  await expect(models.getByText(/model unavailable/i).first()).toBeVisible();
  await expect(models.getByText(/%/)).toHaveCount(0);
  // a reviewer records an UNVERIFIED suspicion: it is stored and shown as unverified (so it can never become a training label)
  const outcome = dlg.getByRole("region", { name: "Outcome" });
  await outcome.getByRole("combobox").selectOption("undetermined");
  await outcome.getByRole("textbox").fill("e2e: customer contacted, awaiting reply");
  await outcome.getByRole("button", { name: "Record outcome" }).click();
  await expect(dlg.getByText(/undetermined/).first()).toBeVisible();
  await expect(dlg.getByText(/\(unverified\)/)).toBeVisible();
});

test("a declined payment can be retried and then succeeds", async ({ page }) => {
  await toPaymentStep(page, "DEMO-BK-003", 1);
  await page.getByRole("button", { name: "Place order and pay" }).click();
  await page.waitForURL(/127\.0\.0\.1:8798\/pay\//);
  await page.getByRole("button", { name: "Decline payment" }).click();
  await page.waitForURL(/\/shop\/payment\//);
  await expect(page.getByTestId("payment-failed")).toBeVisible({ timeout: 20_000 });
  const id = orderIdFromUrl(page);
  expect((await api(page, "GET", `/orders/${id}`)).json).toMatchObject({ status: "payment_failed", payment_status: "failed" });

  await page.getByRole("button", { name: "Pay by card" }).click();
  await page.waitForURL(/127\.0\.0\.1:8798\/pay\//);
  await page.getByRole("button", { name: "Approve payment" }).click();
  await page.waitForURL(/\/shop\/payment\//);
  await expect(page.getByTestId("payment-paid")).toBeVisible({ timeout: 20_000 });
  const o = (await api(page, "GET", `/orders/${id}`)).json;
  expect(o.payment_attempts.map(a => a.status)).toEqual(["failed", "succeeded"]);
});

test("leaving the provider's page without paying keeps the order unpaid until the customer stops the payment", async ({ page }) => {
  const before = await stockOf(page, "DEMO-BK-004");
  await toPaymentStep(page, "DEMO-BK-004", 1);
  await page.getByRole("button", { name: "Place order and pay" }).click();
  await page.waitForURL(/127\.0\.0\.1:8798\/pay\//);
  await page.getByRole("button", { name: "Cancel and go back" }).click();
  await page.waitForURL(/\/shop\/payment\//);
  await expect(page.getByTestId("payment-pending")).toBeVisible();                  // the URL says "cancelled"; the server says nothing was paid
  await expect(page.getByTestId("payment-paid")).toHaveCount(0);
  expect(await stockOf(page, "DEMO-BK-004")).toBe(before - 1);                        // stock is held while payment is possible
  await page.getByRole("button", { name: "Stop this payment" }).click();
  await expect(page.getByTestId("payment-cancelled")).toBeVisible();
  await page.getByRole("button", { name: "Cancel order" }).click();
  await expect.poll(() => stockOf(page, "DEMO-BK-004")).toBe(before);                 // released
});

test("cancelling a paid order flags a refund; an administrator refunds it once", async ({ page }) => {
  await toPaymentStep(page, "DEMO-BK-005", 1);
  await page.getByRole("button", { name: "Place order and pay" }).click();
  await page.waitForURL(/127\.0\.0\.1:8798\/pay\//);
  await page.getByRole("button", { name: "Approve payment" }).click();
  await page.waitForURL(/\/shop\/payment\//);
  await expect(page.getByTestId("payment-paid")).toBeVisible({ timeout: 20_000 });
  const id = orderIdFromUrl(page);
  const cancelled = await api(page, "POST", `/orders/${id}/cancel`);
  expect(cancelled.json).toMatchObject({ status: "cancelled", payment_status: "refund_pending" });
  await page.goto(`/shop/orders/${id}`);
  await expect(page.getByText(/will refund it to the account you paid from/i)).toBeVisible();
  expect((await api(page, "POST", `/orders/${id}/refund`)).status).toBe(403);          // customers cannot refund themselves

  await signInAs(page, "Administrator");
  await page.getByRole("link", { name: "Orders & Risk", exact: true }).click();
  await page.getByLabel("Payment", { exact: true }).selectOption("refund_pending");
  await page.getByRole("button", { name: /^Open order ORD-/ }).first().click();
  const dlg = page.getByRole("dialog");
  await dlg.getByRole("button", { name: "Refund customer" }).click();
  await page.getByRole("dialog").last().getByRole("button", { name: "Refund", exact: true }).click();
  await expect(page.getByRole("dialog").first().getByText(/Payment\s*Refunded/)).toBeVisible();
  expect(await refunds(page)).toHaveLength(1);
  expect((await api(page, "POST", `/orders/${id}/refund`)).status).toBe(409);          // never twice
  expect(await refunds(page)).toHaveLength(1);
});

test("cash on delivery goes straight to a confirmed, pay-on-delivery order", async ({ page }) => {
  await toPaymentStep(page, "DEMO-DE-002", 1);
  await page.getByRole("radio", { name: /cash on delivery/i }).check();
  await page.getByRole("button", { name: "Place order", exact: true }).click();
  await expect(page).toHaveURL(/\/shop\/order-confirmation\//);
  await expect(page.getByText(/thank you\. your order was placed/i)).toBeVisible();
  await expect(page.getByTestId("payment-status")).toHaveText("Pay on delivery");
});

test("an administrator adds a product and a customer can find it and see the price", async ({ page }) => {
  await signInAs(page, "Administrator");
  await page.getByRole("link", { name: "Products", exact: true }).click();
  await page.getByRole("button", { name: "New product" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("SKU").fill("E2E-MAIZE-5");
  await dlg.getByLabel("Name").fill("E2E Maize Meal 5kg");
  await dlg.getByLabel("Price (ZMW)").fill("55.50");
  await dlg.getByLabel("Brand").fill("E2E Mills");
  await dlg.getByLabel("Starting stock").fill("10");
  await dlg.getByRole("button", { name: "Save product" }).click();
  await expect(page.getByRole("row", { name: /E2E Maize Meal 5kg/ })).toContainText("55.50");

  await signInAs(page, "Customer (store)");
  await page.goto("/shop/products?search=E2E+Maize");
  const card = page.getByRole("article", { name: "E2E Maize Meal 5kg" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("55.50");
  expect((await product(page, "E2E-MAIZE-5")).available_quantity).toBe(10);
});
