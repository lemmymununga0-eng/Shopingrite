import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ value: {} }));
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth.value }));
vi.mock("../services/api", () => {
  const f = () => vi.fn();
  return { ApiError: class extends Error {}, setUnauthorizedHandler: () => {},
    api: { storeInfo: f(), categories: f(), products: f(), product: f(), cart: f(), addToCart: f(), updateCartItem: f(), removeCartItem: f(),
      orders: f(), order: f(), cancelOrder: f(), paymentMethods: f(), storeOrders: f() } };
});

import { api } from "../services/api";
import { StoreProvider, useStore } from "../context/StoreContext";
import { ProductCard, SaveButton } from "../store/components";
import { FreeDelivery } from "../store/FreeDelivery";
import MiniCart from "../store/MiniCart";
import SearchBox from "../store/SearchBox";
import Saved from "../store/Saved";
import { OrderView, Tracker } from "../store/Orders";
import Login from "../pages/Login";

const product = (over = {}) => ({ id: 1, sku: "A-1", name: "Bananas", category_slug: "fresh-produce", price_cents: 2500, offer_price_cents: null, effective_price_cents: 2500,
  currency: "ZMW", unit: "per kg", image_ref: "/products/fresh-produce.svg", stock_status: "in_stock", available_quantity: 50, is_demo: false, ...over });
const line = (qty = 2) => ({ item_id: 7, product: product(), quantity: qty, line_total_cents: 2500 * qty, issue: null });
const cartOf = (lines) => ({ items: lines, item_count: lines.reduce((n, l) => n + l.quantity, 0), currency: "ZMW", subtotal_cents: lines.reduce((n, l) => n + l.line_total_cents, 0),
  has_issues: false, delivery_fee_cents: 3500, delivery_fee_note: "" });
const Here = () => { const l = useLocation(); return <div data-testid="loc">{l.pathname}{l.search}</div>; };
const view = (ui, path = "/") => render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  window.scrollTo = vi.fn();
  auth.value = { user: { id: "u1", email: "me@example.com" }, role: "customer", loading: false, configured: true, logout: vi.fn(), login: vi.fn() };
  api.storeInfo.mockResolvedValue({ name: "Mwila Foods", currency: "ZMW", is_demo: false, free_delivery_over_cents: 60000, max_quantity_per_line: 20, console_admin_only: false });
  api.categories.mockResolvedValue([]);
  api.cart.mockResolvedValue(cartOf([]));
});

describe("product card stepper", () => {
  it("shows Add to cart when the item is not in the cart", async () => {
    view(<StoreProvider><ProductCard product={product()}/></StoreProvider>);
    expect(await screen.findByRole("button", { name: "Add to cart: Bananas" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /quantity of bananas in your cart/i })).not.toBeInTheDocument();
  });
  it("turns into a stepper when the item is already in the cart, and changes the quantity through the API", async () => {
    api.cart.mockResolvedValue(cartOf([line(2)]));
    api.updateCartItem.mockResolvedValue(cartOf([line(3)]));
    view(<StoreProvider><ProductCard product={product()}/></StoreProvider>);
    const group = await screen.findByRole("group", { name: /quantity of bananas in your cart/i });
    expect(within(group).getByText("2 in cart")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add to cart: Bananas" })).not.toBeInTheDocument();
    await userEvent.click(within(group).getByRole("button", { name: "Increase quantity of Bananas" }));
    await waitFor(() => expect(api.updateCartItem).toHaveBeenCalledWith(7, 3));
    expect(await screen.findByText("3 in cart")).toBeInTheDocument();
  });
  it("removes the item when the quantity goes below one", async () => {
    api.cart.mockResolvedValue(cartOf([line(1)]));
    api.removeCartItem.mockResolvedValue(cartOf([]));
    view(<StoreProvider><ProductCard product={product()}/></StoreProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Decrease quantity of Bananas" }));
    await waitFor(() => expect(api.removeCartItem).toHaveBeenCalledWith(7));
    expect(await screen.findByRole("button", { name: "Add to cart: Bananas" })).toBeInTheDocument();
  });
  it("cannot go above the stock on hand", async () => {
    api.cart.mockResolvedValue(cartOf([line(3)]));
    view(<StoreProvider><ProductCard product={product({ available_quantity: 3, stock_status: "low_stock" })}/></StoreProvider>);
    expect(await screen.findByRole("button", { name: "Increase quantity of Bananas" })).toBeDisabled();
  });
  it("never offers to add an out-of-stock product", async () => {
    view(<StoreProvider><ProductCard product={product({ stock_status: "out_of_stock", available_quantity: 0 })}/></StoreProvider>);
    expect(await screen.findByRole("button", { name: "Unavailable: Bananas is out of stock" })).toBeDisabled();
  });
});

describe("saved items", () => {
  it("the heart toggles, remembers the choice and announces its state", async () => {
    view(<SaveButton product={product()}/>);
    const heart = screen.getByRole("button", { name: "Save Bananas for later" });
    expect(heart).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(heart);
    expect(await screen.findByRole("button", { name: "Remove Bananas from saved items" })).toHaveAttribute("aria-pressed", "true");
    expect(JSON.parse(localStorage.getItem("store_saved_products"))).toEqual([1]);
    await userEvent.click(screen.getByRole("button", { name: "Remove Bananas from saved items" }));
    expect(JSON.parse(localStorage.getItem("store_saved_products"))).toEqual([]);
  });
  it("the Saved page lists saved products with fresh data, and has an empty state", async () => {
    view(<StoreProvider><Saved/></StoreProvider>);
    expect(await screen.findByRole("heading", { name: /no saved items yet/i })).toBeInTheDocument();
    localStorage.setItem("store_saved_products", JSON.stringify([1, 2]));
    api.product.mockImplementation(async id => product({ id, name: id === 1 ? "Bananas" : "Milk" }));
    view(<StoreProvider><Saved/></StoreProvider>);
    expect(await screen.findByRole("article", { name: "Bananas" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Milk" })).toBeInTheDocument();
  });
});

describe("free-delivery bar", () => {
  it("tells the shopper how much more to add", () => {
    render(<FreeDelivery subtotal={45000} threshold={60000} currency="ZMW"/>);
    expect(screen.getByTestId("free-delivery")).toHaveTextContent(/add .*150\.00.* more for free delivery/i);
    expect(screen.getByRole("progressbar", { name: /free delivery/i })).toHaveAttribute("aria-valuenow", "75");
  });
  it("celebrates at the threshold and renders nothing without one", () => {
    const { container, rerender } = render(<FreeDelivery subtotal={60000} threshold={60000} currency="ZMW"/>);
    expect(screen.getByText(/you have free delivery/i)).toBeInTheDocument();
    rerender(<FreeDelivery subtotal={100} threshold={0} currency="ZMW"/>);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("mini cart", () => {
  const Harness = () => { const { openDrawer } = useStore(); return <><button onClick={openDrawer}>open cart</button><MiniCart/></>; };
  it("opens with the items and totals, offers checkout, and closes with Escape", async () => {
    api.cart.mockResolvedValue(cartOf([line(2)]));
    view(<StoreProvider><Harness/></StoreProvider>);
    await waitFor(() => expect(api.cart).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "open cart" }));
    const dlg = await screen.findByRole("dialog", { name: "Your cart" });
    expect(within(dlg).getByText(/2 × K25\.00/)).toBeInTheDocument();
    expect(within(dlg).getByRole("link", { name: "Go to checkout" })).toHaveAttribute("href", "/shop/checkout");
    expect(within(dlg).getByRole("link", { name: "View full cart" })).toHaveAttribute("href", "/shop/cart");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
  it("shows an empty message for an empty cart", async () => {
    view(<StoreProvider><Harness/></StoreProvider>);
    await userEvent.click(screen.getByRole("button", { name: "open cart" }));
    expect(await screen.findByText(/your cart is empty/i)).toBeInTheDocument();
  });
});

describe("search suggestions", () => {
  it("suggests matching products after a short pause and goes to the full results on submit", async () => {
    api.products.mockResolvedValue({ items: [product({ name: "Full Cream Milk", id: 9 })], total: 1 });
    view(<><SearchBox/><Here/></>);
    const box = screen.getByRole("searchbox", { name: "Search products" });
    await userEvent.type(box, "mi");
    expect(await screen.findByRole("link", { name: /full cream milk/i })).toHaveAttribute("href", "/shop/products/9");
    expect(api.products).toHaveBeenCalledWith(expect.objectContaining({ search: "mi", page_size: 5 }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("list", { name: "Suggestions" })).not.toBeInTheDocument();
    await userEvent.type(box, "lk{Enter}");
    expect(screen.getByTestId("loc")).toHaveTextContent("/shop/products?search=milk");
  });
  it("does not search for a single character and survives a failing API", async () => {
    api.products.mockRejectedValue(new Error("down"));
    view(<SearchBox/>);
    const box = screen.getByRole("searchbox", { name: "Search products" });
    await userEvent.type(box, "m");
    await new Promise(r => setTimeout(r, 400));
    expect(api.products).not.toHaveBeenCalled();
    await userEvent.type(box, "i");
    await new Promise(r => setTimeout(r, 400));
    expect(screen.queryByRole("list", { name: "Suggestions" })).not.toBeInTheDocument();
  });
});

describe("order tracker and buy again", () => {
  const order = (over = {}) => ({ id: "o-1", reference: "ORD-1", status: "picking", fulfilment: "delivery", payment_status: "paid", payment_mode: "TEST", currency: "ZMW",
    contact_name: "Mia", contact_email: "m@x.co", contact_phone: "+260971234567", address_line: "1 Rd", city: "Lusaka", postal_code: "", subtotal_cents: 5000,
    delivery_fee_cents: 0, total_cents: 5000, created_at: "2026-10-21T10:00:00Z", payment_attempts: [],
    items: [{ product_id: 1, sku: "A-1", name: "Bananas", unit_price_cents: 2500, quantity: 2, line_total_cents: 5000 }, { product_id: 2, sku: "M-1", name: "Milk", unit_price_cents: 100, quantity: 1, line_total_cents: 100 }], ...over });
  it.each([
    ["confirmed", "Preparing"], ["picking", "Preparing"], ["ready", "Out for delivery"], ["out_for_delivery", "Out for delivery"],
  ])("%s -> current step %s", (status, current) => {
    render(<Tracker order={order({ status })}/>);
    expect(screen.getByRole("list", { name: "Order progress" }).querySelector("[aria-current=step]")).toHaveTextContent(current);
  });
  it("uses Ready to collect for collection orders and marks every step done when completed", () => {
    const { rerender } = render(<Tracker order={order({ status: "ready", fulfilment: "collection" })}/>);
    expect(screen.getByText("Ready to collect")).toHaveAttribute("aria-current", "step");
    rerender(<Tracker order={order({ status: "completed" })}/>);
    expect(document.querySelectorAll(".tracker li.done")).toHaveLength(5);
  });
  it("shows no steps for a cancelled order", () => {
    render(<Tracker order={order({ status: "cancelled" })}/>);
    expect(screen.queryByRole("list", { name: "Order progress" })).not.toBeInTheDocument();
  });
  it("Buy again puts every item back in the cart and opens the cart", async () => {
    api.order.mockResolvedValue(order({ status: "completed" }));
    api.addToCart.mockResolvedValue({});
    view(<StoreProvider><Routes><Route path="/shop/orders/:id" element={<OrderView/>}/><Route path="/shop/cart" element={<div data-testid="cart-page">CART</div>}/></Routes></StoreProvider>, "/shop/orders/o-1");
    await userEvent.click(await screen.findByRole("button", { name: "Buy again" }));
    await waitFor(() => expect(api.addToCart).toHaveBeenCalledTimes(2));
    expect(api.addToCart).toHaveBeenNthCalledWith(1, 1, 2);
    expect(api.addToCart).toHaveBeenNthCalledWith(2, 2, 1);
    expect(await screen.findByTestId("cart-page")).toBeInTheDocument();
  });
  it("Buy again lists what could not be added instead of failing silently", async () => {
    api.order.mockResolvedValue(order({ status: "completed" }));
    api.addToCart.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("Milk is out of stock."));
    view(<StoreProvider><Routes><Route path="/shop/orders/:id" element={<OrderView/>}/></Routes></StoreProvider>, "/shop/orders/o-1");
    await userEvent.click(await screen.findByRole("button", { name: "Buy again" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be added: Milk/);
  });
});

describe("staff & admin sign-in", () => {
  const profile = role => ({ id: "x", email: "x@y.co", app_metadata: { role } });
  const page = (path = "/login?staff=1") => view(<Routes><Route path="/login" element={<Login/>}/><Route path="/dashboard" element={<div data-testid="console">CONSOLE</div>}/><Route path="/shop" element={<div data-testid="shop">SHOP</div>}/></Routes>, path);
  const fill = async () => {
    await userEvent.type(screen.getByLabelText("Email Address"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "secret123");
    await userEvent.click(screen.getByRole("button", { name: "Login" }));
  };
  beforeEach(() => { auth.value = { ...auth.value, user: null }; });

  it("has its own heading and a way back to the customer sign-in", () => {
    page();
    expect(screen.getByRole("heading", { name: "Staff & admin sign-in" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Customer sign-in" })).toHaveAttribute("href", "/login");
  });
  it("lets an administrator in to the console", async () => {
    auth.value.login = vi.fn().mockResolvedValue(profile("admin"));
    page(); await fill();
    expect(await screen.findByTestId("console")).toBeInTheDocument();
  });
  it("turns a customer account away and signs it out again", async () => {
    auth.value.login = vi.fn().mockResolvedValue(profile("customer"));
    auth.value.logout = vi.fn().mockResolvedValue();
    page(); await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent(/does not have staff or administrator access/i);
    expect(auth.value.logout).toHaveBeenCalled();
    expect(screen.queryByTestId("console")).not.toBeInTheDocument();
  });
  it("when the store is admin-only, an analyst is turned away too", async () => {
    api.storeInfo.mockResolvedValue({ console_admin_only: true });
    auth.value.login = vi.fn().mockResolvedValue(profile("fraud_analyst"));
    auth.value.logout = vi.fn().mockResolvedValue();
    page();
    await waitFor(() => expect(api.storeInfo).toHaveBeenCalled());
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent(/only administrators/i);
  });
  it("the normal customer sign-in is unchanged and links to the staff sign-in", async () => {
    auth.value.login = vi.fn().mockResolvedValue(profile("customer"));
    page("/login");
    expect(screen.getByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /staff & admin sign-in/i })).toHaveAttribute("href", "/login?staff=1");
    await fill();
    expect(await screen.findByTestId("shop")).toBeInTheDocument();
  });
});
