import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = { value: {} };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth.value }));
vi.mock("../services/api", () => {
  const f = () => vi.fn();
  return { ApiError: class extends Error {}, setUnauthorizedHandler: () => {},
    api: { staffOrders: f(), staffOrder: f(), riskSummary: f(), recordOutcome: f(), setOrderStatus: f(), refundOrder: f(),
      adminProducts: f(), createProduct: f(), updateProduct: f(), categories: f() } };
});

import { api } from "../services/api";
import StaffOrders from "../pages/StaffOrders";
import StaffProducts, { toCents } from "../pages/StaffProducts";

const row = (over = {}) => ({ id: "o-1", reference: "ORD-AAAA1111", created_at: "2026-10-21T10:00:00Z", status: "confirmed", payment_status: "paid",
  payment_method: "card", payment_mode: "TEST", total_cents: 25000, currency: "ZMW", fulfilment: "delivery", contact_name: "Mia Shopper", item_count: 2,
  risk: { score: 45, decision: "review", engine: "store_risk_v1" }, case: { id: 1, case_reference: "CASE-000001", status: "new", severity: "medium" }, ...over });
const detail = (orderOver = {}, extra = {}) => ({ contact_masked: false, case: row().case, history: [{ from: "", to: "awaiting_payment", reason: "order placed", at: "2026-10-21T10:00:00Z" }],
  assessments: [{ id: 2, engine: "store_risk_v1", trigger: "order_placed", score: 45, decision: "review", note: "Rule-based score for human review (store_risk_v1). Not machine learning and not proof of wrongdoing.",
    reasons: [{ rule: "high_value", points: 30, text: "Order total is at or above the high-value limit." }, { rule: "first_order_large", points: 15, text: "This is the customer's first paid order and it is large." }],
    features: {}, created_at: "2026-10-21T10:00:00Z" }],
  order: { ...row(), contact_email: "mia@example.com", contact_phone: "+260971234567", address_line: "12 Test Street", city: "Lusaka", area: "",
    items: [{ sku: "A", name: "Bananas", quantity: 2, line_total_cents: 5000 }], payment_attempts: [{ reference: "PAY-AAAA1111", method: "card", status: "succeeded", failure_reason: "", created_at: "2026-10-21T10:00:00Z" }], ...orderOver }, ...extra });
const view = ui => render(<MemoryRouter>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  auth.value = { user: { id: "a", email: "admin@example.com" }, role: "admin", loading: false };
  api.staffOrders.mockResolvedValue({ items: [row(), row({ id: "o-2", reference: "ORD-BBBB2222", risk: { score: 0, decision: "allow", engine: "store_risk_v1" }, case: null })], total: 2, page: 1, page_size: 20 });
  api.riskSummary.mockResolvedValue({ engine: "store_risk_v1", counts: { allow: 1, review: 1, high: 0 }, note: "x" });
  api.staffOrder.mockResolvedValue(detail());
});

describe("orders & risk", () => {
  it("lists orders with their risk and shows the counts", async () => {
    view(<StaffOrders/>);
    expect(await screen.findByRole("button", { name: "Open order ORD-AAAA1111" })).toBeInTheDocument();
    expect(screen.getByText("Review · 45")).toBeInTheDocument();
    expect(screen.getByText("Low · 0")).toBeInTheDocument();
    const counts = screen.getByRole("group", { name: "Orders by risk" });
    expect(within(counts).getByText("Review").nextSibling).toHaveTextContent("1");
  });
  it("passes filters to the API and resets to the first page", async () => {
    view(<StaffOrders/>);
    await screen.findByRole("button", { name: "Open order ORD-AAAA1111" });
    await userEvent.selectOptions(screen.getByLabelText("Risk"), "high");
    await waitFor(() => expect(api.staffOrders).toHaveBeenLastCalledWith(expect.objectContaining({ decision: "high", page: 1 })));
    await userEvent.type(screen.getByLabelText("Search reference or name"), "mia");
    await waitFor(() => expect(api.staffOrders).toHaveBeenLastCalledWith(expect.objectContaining({ search: "mia" })));
  });
  it("shows reasons in plain language, the case and the payment history in the detail", async () => {
    view(<StaffOrders/>);
    await userEvent.click(await screen.findByRole("button", { name: "Open order ORD-AAAA1111" }));
    const dlg = await screen.findByRole("dialog");
    expect(await within(dlg).findByText(/order total is at or above the high-value limit/i)).toBeInTheDocument();
    expect(within(dlg).getByText(/not machine learning/i)).toBeInTheDocument();
    expect(within(dlg).getByRole("link", { name: "CASE-000001" })).toBeInTheDocument();
    expect(within(dlg).getByText(/PAY-AAAA1111/)).toBeInTheDocument();
  });
  it("shows what the models said about the stored order, never an invented score", async () => {
    api.staffOrder.mockResolvedValue(detail({}, { ml_predictions: [
      { model: "store_grocery", status: "ok", probability: 0.82, threshold: 0.4, experimental: true, event_id: "o-1:order_placed:PAY-1" },
      { model: "creditcard_pca", status: "unsupported_input_schema", probability: null, experimental: false } ], outcomes: [] }));
    view(<StaffOrders/>);
    await userEvent.click(await screen.findByRole("button", { name: "Open order ORD-AAAA1111" }));
    const dlg = await screen.findByRole("dialog");
    const sec = await within(dlg).findByRole("region", { name: "Model results" });
    expect(within(sec).getByText(/82% \(threshold 0.4\)/)).toBeInTheDocument();
    expect(within(sec).getByText(/experimental, no alert/)).toBeInTheDocument();
    expect(within(sec).getByText(/unsupported input schema/)).toBeInTheDocument();
    expect(within(sec).getByText(/no score was made up/i)).toBeInTheDocument();
  });
  it("lets a reviewer record a verified outcome and sends exactly what was chosen", async () => {
    auth.value = { ...auth.value, role: "fraud_analyst" };
    api.staffOrder.mockResolvedValue(detail({}, { ml_predictions: [], outcomes: [] }));
    api.recordOutcome.mockResolvedValue({});
    view(<StaffOrders/>);
    await userEvent.click(await screen.findByRole("button", { name: "Open order ORD-AAAA1111" }));
    const dlg = await screen.findByRole("dialog");
    await userEvent.selectOptions(await within(dlg).findByLabelText("Result"), "confirmed_fraud");
    await userEvent.click(within(dlg).getByLabelText(/Verified with evidence/));
    await userEvent.type(within(dlg).getByLabelText("Note"), "chargeback");
    await userEvent.click(within(dlg).getByRole("button", { name: "Record outcome" }));
    await waitFor(() => expect(api.recordOutcome).toHaveBeenCalledWith("o-1", { outcome: "confirmed_fraud", verified: true, note: "chargeback" }));
  });
  it("tells analysts their view is masked and gives them no action buttons", async () => {
    auth.value = { ...auth.value, role: "fraud_analyst" };
    api.staffOrder.mockResolvedValue(detail({ contact_phone: "+26097****567", contact_email: "m***@example.com", address_line: "(hidden)" }, { contact_masked: true }));
    view(<StaffOrders/>);
    await userEvent.click(await screen.findByRole("button", { name: "Open order ORD-AAAA1111" }));
    const dlg = await screen.findByRole("dialog");
    expect(await within(dlg).findByText(/masked for your role/i)).toBeInTheDocument();
    expect(within(dlg).queryByText(/0971234567/)).not.toBeInTheDocument();
    expect(within(dlg).queryByRole("button", { name: /start picking|cancel order|refund/i })).not.toBeInTheDocument();
  });
  it("lets an administrator move an order along", async () => {
    api.setOrderStatus.mockResolvedValue({});
    view(<StaffOrders/>);
    await userEvent.click(await screen.findByRole("button", { name: "Open order ORD-AAAA1111" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start picking" }));
    await waitFor(() => expect(api.setOrderStatus).toHaveBeenCalledWith("o-1", "picking"));
  });
  it("asks for confirmation before cancelling a paid order", async () => {
    api.setOrderStatus.mockResolvedValue({});
    view(<StaffOrders/>);
    await userEvent.click(await screen.findByRole("button", { name: "Open order ORD-AAAA1111" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel order" }));
    expect(api.setOrderStatus).not.toHaveBeenCalled();
    const confirm = screen.getAllByRole("dialog").at(-1);
    expect(within(confirm).getByText(/refund pending/i)).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole("button", { name: "Cancel order" }));
    await waitFor(() => expect(api.setOrderStatus).toHaveBeenCalledWith("o-1", "cancelled"));
  });
  it("offers a refund only for orders waiting for one, after confirmation", async () => {
    api.staffOrder.mockResolvedValue(detail({ status: "cancelled", payment_status: "refund_pending" }));
    api.refundOrder.mockResolvedValue({});
    view(<StaffOrders/>);
    await userEvent.click(await screen.findByRole("button", { name: "Open order ORD-AAAA1111" }));
    await userEvent.click(await screen.findByRole("button", { name: "Refund customer" }));
    expect(api.refundOrder).not.toHaveBeenCalled();
    const dialogs = screen.getAllByRole("dialog");
    await userEvent.click(within(dialogs.at(-1)).getByRole("button", { name: "Refund" }));
    await waitFor(() => expect(api.refundOrder).toHaveBeenCalledWith("o-1"));
  });
  it("shows the API error instead of crashing", async () => {
    api.staffOrders.mockRejectedValue(new Error("The database is unavailable."));
    view(<StaffOrders/>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/database is unavailable/i);
  });
});

describe("toCents", () => {
  it.each([["125", 12500], ["125.5", 12550], ["K 99.99", 9999], ["1,250.00", 125000], ["0.05", 5]])("%s -> %s", (t, c) => expect(toCents(t)).toBe(c));
  it.each(["", "abc", "12.345", "-5", "1e3", "12,50x", "99999999"])("rejects %j", t => expect(toCents(t)).toBeNull());
});

describe("products", () => {
  const product = (over = {}) => ({ id: 5, sku: "ZM-1", name: "Mealie Meal", description: "", category_slug: "staples", category_name: "Staples", price_cents: 12500,
    offer_price_cents: null, effective_price_cents: 12500, currency: "ZMW", unit: "each", brand: "Mills", pack_size: "25 kg", image_ref: "", is_active: true,
    is_featured: false, price_status: "verified", available_quantity: 40, ...over });
  beforeEach(() => {
    api.adminProducts.mockResolvedValue({ items: [product()], total: 1, page: 1, page_size: 20 });
    api.categories.mockResolvedValue([{ slug: "staples", name: "Staples" }, { slug: "dairy", name: "Dairy" }]);
  });
  it("lists products and creates one with prices converted to cents", async () => {
    api.createProduct.mockResolvedValue({});
    view(<StaffProducts/>);
    expect(await screen.findByText("Mealie Meal")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New product" }));
    const dlg = await screen.findByRole("dialog");
    await userEvent.type(within(dlg).getByLabelText("SKU"), "ZM-NEW-1");
    await userEvent.type(within(dlg).getByLabelText("Name"), "Kapenta 500g");
    await userEvent.type(within(dlg).getByLabelText("Price (ZMW)"), "45.50");
    await userEvent.clear(within(dlg).getByLabelText("Starting stock")); await userEvent.type(within(dlg).getByLabelText("Starting stock"), "12");
    await userEvent.click(within(dlg).getByRole("button", { name: "Save product" }));
    await waitFor(() => expect(api.createProduct).toHaveBeenCalled());
    expect(api.createProduct.mock.calls[0][0]).toMatchObject({ sku: "ZM-NEW-1", name: "Kapenta 500g", price_cents: 4550, initial_quantity: 12, category_slug: "staples" });
    expect(api.createProduct.mock.calls[0][0].offer_price_cents).toBeUndefined();
  });
  it("refuses a malformed price before calling the API", async () => {
    view(<StaffProducts/>);
    await userEvent.click(await screen.findByRole("button", { name: "New product" }));
    const dlg = await screen.findByRole("dialog");
    await userEvent.type(within(dlg).getByLabelText("Name"), "Kapenta");
    await userEvent.type(within(dlg).getByLabelText("Price (ZMW)"), "12.345");
    await userEvent.click(within(dlg).getByRole("button", { name: "Save product" }));
    expect(await within(dlg).findByRole("alert")).toHaveTextContent(/price as a number/i);
    expect(api.createProduct).not.toHaveBeenCalled();
  });
  it("edits a product, clears the offer when the field is emptied and shows server errors", async () => {
    api.updateProduct.mockRejectedValueOnce(new Error("The offer price must be lower than the normal price.")).mockResolvedValue({});
    view(<StaffProducts/>);
    await userEvent.click(await screen.findByRole("button", { name: "Edit Mealie Meal" }));
    const dlg = await screen.findByRole("dialog");
    const price = within(dlg).getByLabelText("Price (ZMW)");
    await userEvent.clear(price); await userEvent.type(price, "130");
    await userEvent.click(within(dlg).getByRole("button", { name: "Save product" }));
    expect(await within(dlg).findByRole("alert")).toHaveTextContent(/offer price must be lower/i);
    await userEvent.click(within(dlg).getByRole("button", { name: "Save product" }));
    await waitFor(() => expect(api.updateProduct).toHaveBeenCalledTimes(2));
    expect(api.updateProduct.mock.calls[1][0]).toBe(5);
    expect(api.updateProduct.mock.calls[1][1]).toMatchObject({ price_cents: 13000, clear_offer: true });
  });
});
