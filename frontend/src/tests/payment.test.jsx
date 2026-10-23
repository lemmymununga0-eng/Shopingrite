import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../services/api", () => {
  const f = () => vi.fn();
  return { ApiError: class extends Error {}, setUnauthorizedHandler: () => {},
    api: { order: f(), paymentMethods: f(), verifyPayment: f(), checkoutLink: f(), cancelPayment: f(), payOrder: f(), cancelOrder: f(), simulatePayment: f() } };
});

import { api } from "../services/api";
import PaymentResult, { paymentState } from "../store/Payment";

const attempt = (over = {}) => ({ reference: "PAY-AAAA1111", method: "card", provider: "flutterwave", mode: "TEST", status: "pending", failure_reason: "",
  amount_cents: 8498, currency: "ZMW", created_at: "2026-10-21T10:00:00Z", updated_at: "2026-10-21T10:00:00Z", ...over });
const order = (over = {}) => ({ id: "o-1", reference: "ORD-ABC12345", status: "awaiting_payment", payment_status: "pending", payment_mode: "TEST",
  total_cents: 8498, currency: "ZMW", payment_due_at: "2026-10-21T10:30:00Z", payment_notice: "TEST MODE: payments are processed by the payment provider's test environment.",
  payment_attempts: [attempt()], ...over });
const methods = { methods: [
  { id: "simulated", label: "Simulated", available: false, mode: "SIMULATED" },
  { id: "card", label: "Visa / Mastercard", available: true, mode: "TEST" },
  { id: "mtn_momo", label: "MTN Mobile Money", available: true, mode: "TEST" },
  { id: "airtel_money", label: "Airtel Money", available: false, mode: "TEST" }] };
const show = () => render(<MemoryRouter initialEntries={["/shop/payment/o-1?status=successful&tx_ref=PAY-AAAA1111&transaction_id=99"]}>
  <Routes><Route path="/shop/payment/:id" element={<PaymentResult/>}/></Routes></MemoryRouter>);

let assign;
beforeEach(() => {
  vi.clearAllMocks();
  api.paymentMethods.mockResolvedValue(methods);
  assign = vi.fn();
  Object.defineProperty(window, "location", { configurable: true, value: { ...window.location, assign } });
});

describe("paymentState", () => {
  it.each([
    [{ status: "confirmed", payment_status: "paid", payment_attempts: [] }, "paid"],
    [{ status: "awaiting_payment", payment_status: "pending", payment_attempts: [] }, "pending"],
    [{ status: "payment_failed", payment_status: "failed", payment_attempts: [] }, "failed"],
    [{ status: "cancelled", payment_status: "refund_pending", payment_attempts: [] }, "refund"],
    [{ status: "cancelled", payment_status: "cancelled", payment_attempts: [] }, "order_cancelled"],
    [{ status: "confirmed", payment_status: "cod_due", payment_attempts: [] }, "cod"],
  ])("%o -> %s", (o, expected) => expect(paymentState(o)).toBe(expected));
});

describe("online payment page", () => {
  it("checks with the server as soon as the customer returns and shows success only when the server says paid", async () => {
    api.order.mockResolvedValue(order());
    api.verifyPayment.mockResolvedValue({ outcome: "succeeded", order: order({ status: "confirmed", payment_status: "paid", payment_attempts: [attempt({ status: "succeeded" })] }) });
    show();
    await waitFor(() => expect(api.verifyPayment).toHaveBeenCalledWith("PAY-AAAA1111"));
    expect(await screen.findByTestId("payment-paid")).toHaveTextContent(/payment successful/i);
    expect(screen.getByRole("link", { name: /view order confirmation/i })).toHaveAttribute("href", "/shop/order-confirmation/o-1");
  });
  it("never trusts the success in the URL: stays pending when the server says pending", async () => {
    api.order.mockResolvedValue(order());
    api.verifyPayment.mockResolvedValue({ outcome: "pending", order: order() });
    show();
    expect(await screen.findByTestId("payment-pending")).toHaveTextContent(/NOT paid/);
    expect(screen.queryByTestId("payment-paid")).not.toBeInTheDocument();
    expect(screen.getByText(/test mode/i)).toBeInTheDocument();
  });
  it("offers Pay now, which opens the provider page", async () => {
    api.order.mockResolvedValue(order());
    api.verifyPayment.mockResolvedValue({ outcome: "pending", order: order() });
    api.checkoutLink.mockResolvedValue({ url: "https://checkout.flutterwave.com/v3/hosted/pay/y" });
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Pay now" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.flutterwave.com/v3/hosted/pay/y"));
    expect(api.checkoutLink).toHaveBeenCalledWith("PAY-AAAA1111");
  });
  it("shows an error and stays on the page when the link cannot be created", async () => {
    api.order.mockResolvedValue(order());
    api.verifyPayment.mockResolvedValue({ outcome: "pending", order: order() });
    api.checkoutLink.mockRejectedValue(new Error("The payment page could not be created. Please try again in a moment."));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Pay now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be created/i);
    expect(assign).not.toHaveBeenCalled();
  });
  it("lets the customer stop the payment, then offers a retry with each available real method", async () => {
    api.order.mockResolvedValueOnce(order());
    api.verifyPayment.mockResolvedValue({ outcome: "pending", order: order() });
    api.cancelPayment.mockResolvedValue({ outcome: "cancelled" });
    api.order.mockResolvedValue(order({ status: "payment_failed", payment_status: "cancelled", payment_attempts: [attempt({ status: "cancelled" })] }));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Stop this payment" }));
    expect(api.cancelPayment).toHaveBeenCalledWith("PAY-AAAA1111");
    expect(await screen.findByTestId("payment-cancelled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pay by card" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pay with MTN Mobile Money" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pay with Airtel Money" })).not.toBeInTheDocument();   // not available
    expect(screen.queryByText(/demonstration controls/i)).not.toBeInTheDocument();
  });
  it("retrying creates a new attempt and goes to its payment page", async () => {
    const failed = order({ status: "payment_failed", payment_status: "failed", payment_attempts: [attempt({ status: "failed", failure_reason: "Insufficient funds" })] });
    api.order.mockResolvedValue(failed);
    api.payOrder.mockResolvedValue(order({ payment_attempts: [attempt({ status: "failed" }), attempt({ reference: "PAY-BBBB2222" })] }));
    api.checkoutLink.mockResolvedValue({ url: "https://checkout.flutterwave.com/v3/hosted/pay/z" });
    show();
    expect(await screen.findByTestId("payment-failed")).toHaveTextContent(/payment failed/i);
    expect(screen.getByText(/insufficient funds/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pay with MTN Mobile Money" }));
    await waitFor(() => expect(api.payOrder).toHaveBeenCalledWith("o-1", { method: "mtn_momo" }));
    await waitFor(() => expect(api.checkoutLink).toHaveBeenCalledWith("PAY-BBBB2222"));
    expect(assign).toHaveBeenCalledWith("https://checkout.flutterwave.com/v3/hosted/pay/z");
  });
  it("does not check with a payment provider for cash on delivery or simulated payments", async () => {
    api.order.mockResolvedValue(order({ status: "confirmed", payment_status: "cod_due", payment_mode: "COD", payment_notice: "",
      payment_attempts: [attempt({ provider: "cod", method: "cod", mode: "COD" })] }));
    show();
    expect(await screen.findByTestId("payment-cod")).toBeInTheDocument();
    expect(api.verifyPayment).not.toHaveBeenCalled();
  });
  it("explains a refund when a cancelled order had been paid", async () => {
    api.order.mockResolvedValue(order({ status: "cancelled", payment_status: "refund_pending", payment_attempts: [attempt({ status: "succeeded" })] }));
    show();
    expect(await screen.findByTestId("payment-refund")).toHaveTextContent(/refund/i);
    expect(api.verifyPayment).not.toHaveBeenCalled();
  });
});
