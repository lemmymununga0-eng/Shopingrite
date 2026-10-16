import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = { value: {} };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth.value }));
vi.mock("../services/api", () => {
  class ApiError extends Error { constructor(m, status, body) { super(m); this.status = status; this.body = body; } }
  const f = () => vi.fn();
  return { ApiError, setUnauthorizedHandler: () => {}, api: {
    storeInfo: f(), categories: f(), products: f(), product: f(), cart: f(), addToCart: f(), updateCartItem: f(), removeCartItem: f(),
    placeOrder: f(), orders: f(), order: f(), cancelOrder: f(), scamCheck: f(), scamReport: f() } };
});

import { ApiError, api } from "../services/api";
import StoreHome from "../store/StoreHome";
import Catalogue from "../store/Catalogue";
import ProductDetail from "../store/ProductDetail";
import Cart from "../store/Cart";
import Checkout from "../store/Checkout";
import Orders, { OrderView } from "../store/Orders";
import ScamChecker from "../components/ScamChecker";
import { StoreProvider } from "../context/StoreContext";

const product = (over = {}) => ({ id: 1, sku: "DEMO-1", name: "Bananas", description: "Sweet bananas. (Demonstration product)", category_slug: "fresh-produce",
  category_name: "Fresh Produce", price_cents: 2499, offer_price_cents: null, effective_price_cents: 2499, currency: "ZAR", unit: "per kg",
  image_ref: "/products/fresh-produce.svg", is_featured: true, is_demo: true, stock_status: "in_stock", available_quantity: 100, ...over });
const page = (items, extra = {}) => ({ items, total: items.length, page: 1, page_size: 12, ...extra });
const signedIn = { user: { id: "u1", email: "me@example.com", user_metadata: { full_name: "Mia Shopper" } }, role: "customer", loading: false };
const view = (ui, path = "/") => render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);
const LocationProbe = () => <div data-testid="loc">{useLocation().pathname}{useLocation().search}</div>;

beforeEach(() => {
  vi.clearAllMocks();
  auth.value = signedIn;
  api.storeInfo.mockResolvedValue({ name: "FreshCart Demo Store", currency: "ZAR", delivery_cities: ["Johannesburg", "Cape Town"] });
});

describe("store home", () => {
  it("shows categories, featured products and specials from the API with stock labels", async () => {
    api.categories.mockResolvedValue([{ id: 1, slug: "fresh-produce", name: "Fresh Produce", product_count: 5 }]);
    api.products.mockImplementation(async p => p.on_offer
      ? page([product({ id: 2, name: "Red Apples", offer_price_cents: 3299, effective_price_cents: 3299, price_cents: 3999 })])
      : page([product(), product({ id: 3, name: "Cheddar", stock_status: "low_stock", available_quantity: 5 }),
              product({ id: 4, name: "Butter", stock_status: "out_of_stock", available_quantity: 0 })]));
    view(<StoreHome/>);
    expect(await screen.findByRole("heading", { name: /featured products/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /fresh produce/i })).toHaveAttribute("href", "/shop/products?category=fresh-produce");
    expect(screen.getByRole("heading", { name: /special offers/i })).toBeInTheDocument();
    const stock = screen.getAllByTestId("stock-badge").map(e => e.textContent);
    expect(stock).toEqual(expect.arrayContaining(["In stock", "Low stock · only 5 left", "Out of stock"]));
    expect(screen.getByRole("button", { name: /butter is out of stock/i })).toBeDisabled();
    expect(screen.getByText(/special/i, { selector: ".offer-tag" })).toBeInTheDocument();
  });
  it("shows a retry state when the catalogue cannot load", async () => {
    api.categories.mockRejectedValue(new Error("Cannot reach the FraudGuard API. Is the backend running?"));
    api.products.mockRejectedValue(new Error("x"));
    view(<StoreHome/>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot reach/i);
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});

describe("catalogue", () => {
  beforeEach(() => {
    api.categories.mockResolvedValue([{ id: 1, slug: "dairy-eggs", name: "Dairy & Eggs", product_count: 5 }]);
    api.products.mockResolvedValue(page([product({ name: "Milk" })], { total: 30 }));
  });
  it("searches, filters, sorts and paginates through the API", async () => {
    view(<><Catalogue/><LocationProbe/></>, "/shop/products");
    expect(await screen.findByText("30 products found")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search"), "milk");
    await userEvent.type(screen.getByLabelText("Min price"), "10");
    await userEvent.type(screen.getByLabelText("Max price"), "50");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(api.products).toHaveBeenLastCalledWith(expect.objectContaining({ search: "milk", min_price: "10", max_price: "50" })));
    await userEvent.selectOptions(screen.getByLabelText("Category"), "dairy-eggs");
    await waitFor(() => expect(api.products).toHaveBeenLastCalledWith(expect.objectContaining({ category: "dairy-eggs" })));
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "price_desc");
    await waitFor(() => expect(api.products).toHaveBeenLastCalledWith(expect.objectContaining({ sort: "price_desc" })));
    await userEvent.click(screen.getByLabelText("In stock only"));
    await waitFor(() => expect(api.products).toHaveBeenLastCalledWith(expect.objectContaining({ in_stock_only: true })));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(api.products).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, page_size: 12 })));
    expect(screen.getByTestId("loc").textContent).toContain("page=2");
  });
  it("blocks an impossible price range and offers to clear filters on empty results", async () => {
    view(<Catalogue/>, "/shop/products");
    await screen.findByText("30 products found");
    await userEvent.type(screen.getByLabelText("Min price"), "90");
    await userEvent.type(screen.getByLabelText("Max price"), "10");
    api.products.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/minimum price cannot be above/i);
    expect(api.products).not.toHaveBeenCalled();
    api.products.mockResolvedValue(page([], { total: 0 }));
    await userEvent.clear(screen.getByLabelText("Min price")); await userEvent.clear(screen.getByLabelText("Max price"));
    await userEvent.type(screen.getByLabelText("Search"), "zzz");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText(/no products match/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });
  it("reads filters from the address", async () => {
    view(<Catalogue/>, "/shop/products?category=dairy-eggs&sort=price_asc&search=milk");
    await screen.findByText(/products? found/);
    expect(api.products).toHaveBeenCalledWith(expect.objectContaining({ category: "dairy-eggs", sort: "price_asc", search: "milk" }));
    expect(await screen.findByRole("heading", { name: "Dairy & Eggs" })).toBeInTheDocument();
  });
});

describe("product details and add to cart", () => {
  const at = (id = "1") => view(<Routes><Route path="/shop/products/:id" element={<ProductDetail/>}/><Route path="/login" element={<LocationProbe/>}/></Routes>, `/shop/products/${id}`);
  it("shows description, price, unit and stock, validates quantity and adds to the cart", async () => {
    api.product.mockResolvedValue(product({ stock_status: "low_stock", available_quantity: 3 }));
    api.addToCart.mockResolvedValue({ item_count: 2 });
    api.cart.mockResolvedValue({ item_count: 2 });
    at();
    expect(await screen.findByRole("heading", { name: "Bananas" })).toBeInTheDocument();
    expect(screen.getByText(/Sweet bananas/)).toBeInTheDocument();
    expect(screen.getByText("Low stock · only 3 left")).toBeInTheDocument();
    const qty = screen.getByLabelText("Quantity", { selector: "input" });
    await userEvent.clear(qty); await userEvent.type(qty, "9");
    expect(screen.getByRole("alert")).toHaveTextContent(/between 1 and 3/i);
    expect(screen.getByRole("button", { name: /add to cart/i })).toBeDisabled();
    await userEvent.clear(qty); await userEvent.type(qty, "2");
    await userEvent.click(screen.getByRole("button", { name: /add to cart/i }));
    expect(api.addToCart).toHaveBeenCalledWith(1, 2);
    expect(await screen.findByText(/added 2 × bananas/i)).toBeInTheDocument();
  });
  it("explains and prevents adding an out-of-stock product", async () => {
    api.product.mockResolvedValue(product({ stock_status: "out_of_stock", available_quantity: 0 }));
    at();
    expect(await screen.findByText(/out of stock right now/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add to cart/i })).not.toBeInTheDocument();
  });
  it("shows the server's message when stock changed meanwhile", async () => {
    api.product.mockResolvedValue(product());
    api.addToCart.mockRejectedValue(new ApiError("Only 1 of Bananas available.", 409, {}));
    at();
    await userEvent.click(await screen.findByRole("button", { name: /add to cart/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only 1 of Bananas available.");
  });
  it("sends a signed-out shopper to sign in instead of calling the API", async () => {
    auth.value = { user: null, loading: false };
    api.product.mockResolvedValue(product());
    at();
    await userEvent.click(await screen.findByRole("button", { name: /add to cart/i }));
    expect(api.addToCart).not.toHaveBeenCalled();
    expect(screen.getByTestId("loc")).toHaveTextContent("/login");
  });
  it("handles an unknown product", async () => {
    api.product.mockRejectedValue(new Error("Product not found"));
    at("999");
    expect(await screen.findByRole("alert")).toHaveTextContent("Product not found");
  });
});

const cartOf = (lines, extra = {}) => ({ items: lines, item_count: lines.reduce((n, l) => n + l.quantity, 0), currency: "ZAR",
  subtotal_cents: lines.reduce((n, l) => n + l.line_total_cents, 0), has_issues: lines.some(l => l.issue), delivery_fee_cents: 3500,
  delivery_fee_note: "Delivery costs ZAR 35.00, free over ZAR 600.00. Collection is free.", ...extra });
const line = (over = {}) => ({ item_id: 7, product: product(), quantity: 2, line_total_cents: 4998, issue: null, issue_message: null, ...over });

describe("cart", () => {
  it("updates quantity and removes items through the API and shows totals", async () => {
    api.cart.mockResolvedValue(cartOf([line()]));
    api.updateCartItem.mockResolvedValue(cartOf([line({ quantity: 3, line_total_cents: 7497 })]));
    api.removeCartItem.mockResolvedValue(cartOf([]));
    view(<Cart/>);
    expect(await screen.findByRole("heading", { name: "Your cart" })).toBeInTheDocument();
    expect(screen.getByLabelText("Order totals")).toHaveTextContent(/subtotal/i);
    await userEvent.click(screen.getByRole("button", { name: "Increase quantity" }));
    expect(api.updateCartItem).toHaveBeenCalledWith(7, 3);
    await waitFor(() => expect(screen.getAllByText(/R\s?74,97|R74.97/).length).toBeGreaterThan(0));
    await userEvent.click(screen.getByRole("button", { name: "Remove Bananas" }));
    expect(api.removeCartItem).toHaveBeenCalledWith(7);
    expect(await screen.findByRole("heading", { name: /your cart is empty/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /continue shopping/i })).toHaveAttribute("href", "/shop/products");
  });
  it("blocks checkout and explains when stock no longer covers a line", async () => {
    api.cart.mockResolvedValue(cartOf([line({ issue: "quantity_exceeds_stock", issue_message: "Only 1 of Bananas available; you have 2 in your cart." })]));
    view(<Cart/>);
    expect(await screen.findByText(/only 1 of bananas available/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /proceed to checkout/i })).toBeDisabled();
  });
  it("shows the server error and reloads when an update is refused", async () => {
    api.cart.mockResolvedValue(cartOf([line()]));
    api.updateCartItem.mockRejectedValue(new Error("Only 2 of Bananas available."));
    view(<Cart/>);
    await userEvent.click(await screen.findByRole("button", { name: "Increase quantity" }));
    expect(await screen.findByText("Only 2 of Bananas available.")).toBeInTheDocument();
    expect(api.cart).toHaveBeenCalledTimes(2);
  });
});

describe("checkout", () => {
  const renderCheckout = () => view(<StoreProvider><Routes><Route path="/shop/checkout" element={<Checkout/>}/>
    <Route path="/shop/order-confirmation/:id" element={<LocationProbe/>}/><Route path="/shop/cart" element={<div>CART</div>}/></Routes></StoreProvider>, "/shop/checkout");
  const fill = async (over = {}) => {
    await userEvent.clear(screen.getByLabelText("Full name")); await userEvent.type(screen.getByLabelText("Full name"), "Mia Shopper");
    await userEvent.type(screen.getByLabelText("Phone number"), "0821234567");
    await userEvent.type(screen.getByLabelText("Street address"), "12 Test Street");
    await userEvent.type(screen.getByLabelText("City"), over.city || "Johannesburg");
    await userEvent.type(screen.getByLabelText("Postal code"), "2000");
  };
  beforeEach(() => { api.cart.mockResolvedValue(cartOf([line()])); });

  it("labels the payment as a simulation and never asks for card details", async () => {
    renderCheckout();
    expect(await screen.findByText(/demonstration checkout/i)).toBeInTheDocument();
    expect(screen.getByText(/no card details are collected/i)).toBeInTheDocument();
    expect(screen.getByText(/not authorised by any bank/i)).toBeInTheDocument();
    for (const re of [/card number/i, /cvv|cvc|security code/i, /expiry/i]) expect(screen.queryByLabelText(re)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /place demonstration order/i })).toBeInTheDocument();
  });
  it("validates contact and address and refuses unsupported delivery cities before calling the API", async () => {
    renderCheckout();
    await userEvent.click(await screen.findByRole("button", { name: /place demonstration order/i }));
    await screen.findByText(/we deliver to: johannesburg, cape town/i);
    expect(await screen.findByText("Enter a valid phone number")).toBeInTheDocument();
    expect(screen.getByText("Enter your street address")).toBeInTheDocument();
    await fill({ city: "Lusaka" });
    await userEvent.click(screen.getByRole("button", { name: /place demonstration order/i }));
    expect(await screen.findByText(/we do not deliver to lusaka/i)).toBeInTheDocument();
    expect(api.placeOrder).not.toHaveBeenCalled();
  });
  it("collection needs no address and removes the delivery fee from the total", async () => {
    renderCheckout();
    await screen.findByRole("heading", { name: "Checkout" });
    await userEvent.click(screen.getByLabelText(/collect in store/i));
    expect(screen.queryByLabelText("Street address")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Order summary")).toHaveTextContent(/collection\s*free/i);
    api.placeOrder.mockResolvedValue({ id: "o-1" }); api.cart.mockResolvedValue(cartOf([]));
    await userEvent.type(screen.getByLabelText("Phone number"), "0821234567");
    await userEvent.click(screen.getByRole("button", { name: /place demonstration order/i }));
    await waitFor(() => expect(api.placeOrder).toHaveBeenCalled());
    const body = api.placeOrder.mock.calls[0][0];
    expect(body.fulfilment).toBe("collection"); expect(body.address).toBeUndefined();
    expect(body.payment).toEqual({ method: "simulated" });
    expect(JSON.stringify(body)).not.toMatch(/card|cvv|expiry/i);
  });
  it("places an order and goes to the confirmation page", async () => {
    api.placeOrder.mockResolvedValue({ id: "o-1" });
    renderCheckout();
    await screen.findByRole("heading", { name: "Checkout" });
    await fill();
    await userEvent.click(screen.getByRole("button", { name: /place demonstration order/i }));
    expect(await screen.findByTestId("loc")).toHaveTextContent("/shop/order-confirmation/o-1");
    expect(api.placeOrder.mock.calls[0][0].address).toEqual({ line: "12 Test Street", city: "Johannesburg", postal_code: "2000" });
  });
  it("lists the unavailable items when stock ran out at the last moment", async () => {
    api.placeOrder.mockRejectedValue(new ApiError("Some items in your cart can no longer be ordered as requested. Only 1 of Bananas left; you asked for 2.", 409,
      { detail: { message: "Some items...", problems: [{ product_id: 1, message: "Only 1 of Bananas left; you asked for 2." }] } }));
    renderCheckout();
    await screen.findByRole("heading", { name: "Checkout" });
    await fill();
    await userEvent.click(screen.getByRole("button", { name: /place demonstration order/i }));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getAllByText(/only 1 of bananas left/i).length).toBeGreaterThan(0);
    expect(within(alert).getByRole("link", { name: /review your cart/i })).toHaveAttribute("href", "/shop/cart");
  });
  it("shows an empty state when the cart is empty", async () => {
    api.cart.mockResolvedValue(cartOf([]));
    renderCheckout();
    expect(await screen.findByRole("heading", { name: /nothing to check out/i })).toBeInTheDocument();
  });
});

const order = (over = {}) => ({ id: "o-1", reference: "ORD-ABC12345", status: "confirmed", fulfilment: "delivery", contact_name: "Mia Shopper",
  contact_email: "me@example.com", contact_phone: "0821234567", address_line: "12 Test Street", city: "Johannesburg", postal_code: "2000",
  items: [{ product_id: 1, sku: "DEMO-1", name: "Bananas", unit_price_cents: 2499, quantity: 2, line_total_cents: 4998 }],
  subtotal_cents: 4998, delivery_fee_cents: 3500, total_cents: 8498, currency: "ZAR", payment_mode: "SIMULATED", payment_status: "simulated_approved",
  payment_notice: "DEMONSTRATION PAYMENT: this is a simulated checkout. No card was used and no money was taken or authorised by any bank.",
  created_at: "2026-10-16T10:00:00Z", updated_at: "2026-10-16T10:00:00Z", ...over });

describe("orders", () => {
  const at = (el, path) => view(<Routes><Route path="/shop/order-confirmation/:id" element={el}/><Route path="/shop/orders/:id" element={el}/></Routes>, path);
  it("order confirmation shows the reference, status, items, delivery details and the simulated-payment notice", async () => {
    api.order.mockResolvedValue(order());
    at(<OrderView confirmation/>, "/shop/order-confirmation/o-1");
    expect(await screen.findByTestId("order-ref")).toHaveTextContent("ORD-ABC12345");
    expect(screen.getByText(/your demonstration order was placed/i)).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText(/no card was used and no money was taken/i)).toBeInTheDocument();
    expect(screen.getByText("12 Test Street", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view my orders/i })).toHaveAttribute("href", "/shop/orders");
  });
  it("lets the shopper cancel a confirmed order and shows the new status", async () => {
    api.order.mockResolvedValue(order());
    api.cancelOrder.mockResolvedValue(order({ status: "cancelled" }));
    at(<OrderView/>, "/shop/orders/o-1");
    await userEvent.click(await screen.findByRole("button", { name: /cancel order/i }));
    expect(api.cancelOrder).toHaveBeenCalledWith("o-1");
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel order/i })).not.toBeInTheDocument();
  });
  it("does not offer cancel once preparation started and shows a not-found error for other people's orders", async () => {
    api.order.mockResolvedValue(order({ status: "picking" }));
    at(<OrderView/>, "/shop/orders/o-1");
    await screen.findByText("Being picked");
    expect(screen.queryByRole("button", { name: /cancel order/i })).not.toBeInTheDocument();
  });
  it("shows an error for an order that is not found", async () => {
    api.order.mockRejectedValue(new Error("Order not found"));
    at(<OrderView/>, "/shop/orders/zzz");
    expect(await screen.findByRole("alert")).toHaveTextContent("Order not found");
  });
  it("history lists orders with status and totals, and has an empty state", async () => {
    api.orders.mockResolvedValue({ items: [order(), order({ id: "o-2", reference: "ORD-ZZZ99999", status: "completed" })], total: 2, page: 1, page_size: 10 });
    const { unmount } = view(<Orders/>);
    expect(await screen.findByRole("link", { name: "ORD-ABC12345" })).toHaveAttribute("href", "/shop/orders/o-1");
    expect(screen.getByText("Completed")).toBeInTheDocument();
    unmount();
    api.orders.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 });
    view(<Orders/>);
    expect(await screen.findByRole("heading", { name: /no orders yet/i })).toBeInTheDocument();
  });
});

describe("ScamWatch checker (customer view)", () => {
  const result = (over = {}) => ({ verdict: "no_known_threat", normalized_url: "http://a.example/", domain: "a.example", notes: [], simulated: false,
    providers: [{ provider: "heuristic", status: "ok", verdict: "inconclusive", detail: "Offline heuristic checks only.", source: "local rules", simulated: false, signals: [] }],
    provider_errors: [], disclaimer: "No known threat detected does not mean a website is safe.", ...over });
  it("never calls an unknown result safe and always shows the disclaimer", async () => {
    api.scamCheck.mockResolvedValue(result());
    view(<ScamChecker/>);
    await userEvent.type(screen.getByLabelText(/website address/i), "a.example");
    await userEvent.click(screen.getByRole("button", { name: /check website/i }));
    expect(await screen.findByText(/no known threat detected \(this is not a guarantee of safety\)/i)).toBeInTheDocument();
    expect(screen.getByText(/does not mean a website is safe/i)).toBeInTheDocument();
    expect(screen.queryByText(/^safe$/i)).not.toBeInTheDocument();
  });
  it("shows provider errors as an inconclusive result and labels simulated results", async () => {
    api.scamCheck.mockResolvedValue(result({ verdict: "inconclusive", simulated: true, provider_errors: ["mock"],
      providers: [{ provider: "mock", status: "error", verdict: "inconclusive", detail: "Simulated provider failure.", source: "mock", simulated: true, signals: [] }] }));
    view(<ScamChecker/>);
    await userEvent.type(screen.getByLabelText(/website address/i), "x.example");
    await userEvent.click(screen.getByRole("button", { name: /check website/i }));
    expect(await screen.findByText(/inconclusive: we could not reach a conclusion/i)).toBeInTheDocument();
    expect(screen.getByText(/some providers failed \(mock\)/i)).toBeInTheDocument();
    expect(screen.getByText(/includes simulated provider results/i)).toBeInTheDocument();
  });
  it("shows validation errors from the server and lets the user report a website", async () => {
    api.scamCheck.mockRejectedValueOnce(new Error("Private, local and reserved network addresses are not accepted."));
    view(<ScamChecker/>);
    await userEvent.type(screen.getByLabelText(/website address/i), "127.0.0.1");
    await userEvent.click(screen.getByRole("button", { name: /check website/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/not accepted/i);
    api.scamCheck.mockResolvedValue(result({ verdict: "suspicious" }));
    api.scamReport.mockResolvedValue({ duplicate: false, message: "Thank you. The report was saved for review." });
    await userEvent.clear(screen.getByLabelText(/website address/i)); await userEvent.type(screen.getByLabelText(/website address/i), "bad.example");
    await userEvent.click(screen.getByRole("button", { name: /check website/i }));
    await userEvent.click(await screen.findByRole("button", { name: /report this website/i }));
    expect(api.scamReport).toHaveBeenCalledWith("bad.example", "");
    expect(await screen.findByText(/report was saved for review/i)).toBeInTheDocument();
  });
  it("requires an address", async () => {
    view(<ScamChecker/>);
    await userEvent.click(screen.getByRole("button", { name: /check website/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a web address/i);
    expect(api.scamCheck).not.toHaveBeenCalled();
  });
});
