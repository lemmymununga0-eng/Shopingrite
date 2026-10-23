import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ value: {} }));
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth.value }));
vi.mock("../services/api", () => ({ ApiError: class extends Error {}, setUnauthorizedHandler: () => {},
  api: { cart: vi.fn(), paymentMethods: vi.fn(), storeInfo: vi.fn(), categories: vi.fn(), placeOrder: vi.fn(), checkoutLink: vi.fn() } }));

import { api } from "../services/api";
import { StoreProvider } from "../context/StoreContext";
import Checkout from "../store/Checkout";

const methods = { methods: [
  { id: "simulated", label: "Simulated payment (demonstration)", available: true, mode: "SIMULATED", scenarios: ["success"], reason: "" },
  { id: "card", label: "Visa / Mastercard", available: true, mode: "TEST", scenarios: [], reason: "" }] };
const cart = { items: [{ item_id: 1, quantity: 1, line_total_cents: 2500, issue: null, product: { id: 1, name: "Bananas", unit: "kg", effective_price_cents: 2500, currency: "ZMW", available_quantity: 9 } }],
  item_count: 1, currency: "ZMW", subtotal_cents: 2500, delivery_fee_cents: 3500, delivery_fee_note: "Delivery costs ZMW 35.00. Collection is free.", has_issues: false };

beforeEach(() => {
  vi.clearAllMocks();
  auth.value = { user: { id: "u1", email: "me@example.com", user_metadata: { full_name: "Mia Shopper" } }, role: "customer", loading: false };
  api.storeInfo.mockResolvedValue({ name: "Shop", currency: "ZMW", is_demo: true, delivery_cities: ["Lusaka"] });
  api.categories.mockResolvedValue([]);
  api.cart.mockResolvedValue(cart);
});

describe("payment method choice", () => {
  it("a default that loads late never overrides the method the customer already picked", async () => {
    // Development builds run effects twice, so the methods are requested twice and the second answer can arrive late.
    let calls = 0, releaseLate;
    api.paymentMethods.mockImplementation(() => {
      calls += 1;
      return calls === 1 ? Promise.resolve(methods) : new Promise(resolve => { releaseLate = () => resolve(methods); });
    });
    render(<StrictMode><MemoryRouter initialEntries={["/shop/checkout"]}><StoreProvider><Checkout/></StoreProvider></MemoryRouter></StrictMode>);
    await userEvent.type(await screen.findByLabelText("Phone number"), "0971234567");
    const next = () => userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await next();
    await userEvent.click(await screen.findByLabelText(/collect in store/i));
    await next(); await next();
    const simulated = await screen.findByRole("radio", { name: /simulated payment/i });
    await userEvent.click(simulated);
    expect(simulated).toBeChecked();
    await act(async () => { releaseLate(); await new Promise(r => setTimeout(r, 50)); });   // the late second answer arrives AFTER the pick
    expect(screen.getByRole("radio", { name: /simulated payment/i })).toBeChecked();
    expect(screen.getByRole("button", { name: /place demonstration order/i })).toBeInTheDocument();
    expect(calls).toBeGreaterThanOrEqual(2);
  });

  it("clicking Continue on the review step only moves to payment: it never places the order", async () => {
    // Regression: React reused the Continue button as the submit button, so the same click submitted the form.
    api.paymentMethods.mockResolvedValue(methods);
    api.placeOrder.mockResolvedValue({ id: "o-1", payment_status: "paid", payment_attempts: [] });
    render(<MemoryRouter initialEntries={["/shop/checkout"]}><StoreProvider><Checkout/></StoreProvider></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("Phone number"), "0971234567");
    const next = () => userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await next();
    await userEvent.click(await screen.findByLabelText(/collect in store/i));
    await next();                                                       // review step
    const continueButton = screen.getByRole("button", { name: "Continue" });
    await userEvent.click(continueButton);                              // -> payment step: the click that used to submit
    // Root cause: React reused this very element as the submit button, flipping its type before the browser's default
    // action ran (only a real browser then submits; jsdom does not). A separate element makes that impossible.
    const placeButton = await screen.findByRole("button", { name: /place demonstration order|place order/i });
    expect(placeButton).not.toBe(continueButton);
    expect(continueButton.isConnected).toBe(false);
    expect(await screen.findByRole("radio", { name: /simulated payment/i })).toBeInTheDocument();
    await new Promise(r => setTimeout(r, 100));
    expect(api.placeOrder).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /place demonstration order|place order/i })).toBeInTheDocument();
  });
});
