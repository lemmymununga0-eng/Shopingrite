// Accessibility (axe) and mobile-layout checks against the running app.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signInAs } from "./helpers.js";

const seriousOrWorse = results => results.violations.filter(v => ["serious", "critical"].includes(v.impact));
const describeViolations = list => list.map(v => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map(n => n.target.join(" ")).join(" | ")}`).join("\n");

async function scan(page, name) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const bad = seriousOrWorse(results);
  expect(bad, `${name} has serious/critical accessibility violations:\n${describeViolations(bad)}`).toEqual([]);
}

test.describe("accessibility (axe, WCAG 2.1 A/AA, serious and critical only)", () => {
  test("store home, catalogue and product pages", async ({ page }) => {
    await page.goto("/shop");
    await expect(page.getByRole("heading", { name: "Featured products" })).toBeVisible();
    await scan(page, "store home");
    await page.goto("/shop/products");
    await expect(page.getByText(/products found/)).toBeVisible();
    await scan(page, "catalogue");
    await page.goto("/shop/products?search=milk");
    await page.getByRole("link", { name: "Full Cream Milk" }).first().click();
    await expect(page.getByRole("heading", { name: "Full Cream Milk" })).toBeVisible();
    await scan(page, "product detail");
  });
  test("login page", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Login" })).toBeVisible();
    await scan(page, "login");
  });
  test("cart and checkout", async ({ page }) => {
    await signInAs(page, "Customer (store)");
    await page.goto("/shop/products?search=milk");
    await page.getByRole("button", { name: /add to cart: full cream milk/i }).click();
    await expect(page.getByText(/added 1 × full cream milk/i)).toBeVisible();
    await page.goto("/shop/cart");
    await expect(page.getByRole("heading", { name: "Your cart" })).toBeVisible();
    await scan(page, "cart");
    await page.goto("/shop/checkout");
    await expect(page.getByRole("heading", { name: "Checkout" })).toBeVisible();
    await scan(page, "checkout");
  });
  test("staff console pages", async ({ page }) => {
    await signInAs(page, "Administrator");
    for (const [link, heading] of [["Dashboard", /dashboard/i], ["Investigations", "Investigation Centre"], ["Security Monitor", "Security Monitor"],
      ["ScamWatch", "ScamWatch"], ["Inventory & Orders", /inventory & order risk/i], ["Reports", /reports & business impact/i]]) {
      await page.getByRole("link", { name: link, exact: true }).click();
      await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
      await scan(page, link);
    }
  });
});

test.describe("mobile layout (375 x 812)", () => {
  test.use({ viewport: { width: 375, height: 812 } });
  const noHorizontalScroll = async page =>
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(1);

  test("store pages fit the screen and key actions stay reachable", async ({ page }) => {
    await page.goto("/shop");
    await expect(page.getByRole("heading", { name: "Featured products" })).toBeVisible();
    await noHorizontalScroll(page);
    await expect(page.getByRole("searchbox", { name: "Search products" })).toBeVisible();
    await page.goto("/shop/products");
    await expect(page.getByText(/products found/)).toBeVisible();
    await noHorizontalScroll(page);
    const add = page.getByRole("button", { name: /add to cart: /i }).first();
    await add.scrollIntoViewIfNeeded();
    await expect(add).toBeVisible();
    const box = await add.boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(40);                       // comfortable touch target
  });
  test("cart and checkout fit the screen", async ({ page }) => {
    await signInAs(page, "Customer (store)");
    await page.goto("/shop/products?search=milk");
    await page.getByRole("button", { name: /add to cart: full cream milk/i }).click();
    await expect(page.getByText(/added 1 × full cream milk/i)).toBeVisible();
    await page.goto("/shop/cart");
    await expect(page.getByRole("heading", { name: "Your cart" })).toBeVisible();
    await noHorizontalScroll(page);
    await page.goto("/shop/checkout");
    await expect(page.getByRole("heading", { name: "Checkout" })).toBeVisible();
    await noHorizontalScroll(page);
  });
  test("staff console uses the mobile menu and tables do not overflow the page", async ({ page }) => {
    await signInAs(page, "Security analyst");
    await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
    await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("link", { name: "Security Monitor", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Security Monitor" })).toBeVisible();
    await noHorizontalScroll(page);
  });
});
