import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ value: {} }));
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth.value }));
vi.mock("../services/api", () => {
  const f = () => vi.fn();
  return { ApiError: class extends Error {}, setUnauthorizedHandler: () => {},
    api: { overview: f(), riskSummary: f(), staffOrders: f(), staffOrder: f(), inventory: f() } };
});

import { api } from "../services/api";
import StoreOverview from "../components/StoreOverview";
import StaffOrders from "../pages/StaffOrders";
import InventoryMonitor from "../pages/InventoryMonitor";

const overview = (over = {}) => ({
  orders: { by_status: { confirmed: 5, completed: 3, awaiting_payment: 2, cancelled: 1 }, revenue_by_currency_cents: { ZMW: 1234500 } },
  inventory: { low_stock_products: 4, out_of_stock_products: 2 }, cases: { open: 3, open_by_severity: {} }, scamwatch: { by_review_status: { pending: 1 } }, ...over });
const view = (ui, path = "/") => render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  auth.value = { user: { id: "a" }, role: "admin", loading: false };
  api.overview.mockResolvedValue(overview());
  api.riskSummary.mockResolvedValue({ counts: { allow: 7, review: 2, high: 1 } });
  api.staffOrders.mockResolvedValue({ items: [], total: 3, page: 1, page_size: 1 });
});

describe("store at a glance", () => {
  it("shows real revenue and order counts", async () => {
    view(<StoreOverview days={30}/>);
    const region = await screen.findByRole("region", { name: "Store at a glance" });
    expect(within(region).getByText("K12,345.00")).toBeInTheDocument();
    expect(within(region).getByText("11")).toBeInTheDocument();                       // 5 + 3 + 2 + 1 orders
    expect(within(region).getByText("1 high · 2 review")).toBeInTheDocument();
    expect(within(region).getByText("Pay these from Orders & Risk")).toBeInTheDocument();
  });
  it("lists only what needs a person, each linking to a pre-filtered screen", async () => {
    view(<StoreOverview days={30}/>);
    await screen.findByRole("region", { name: "Store at a glance" });
    const link = text => screen.getByText(text).closest("a");
    expect(link(/high-risk order to review/)).toHaveAttribute("href", "/orders?decision=high");
    expect(link(/orders flagged for review/)).toHaveAttribute("href", "/orders?decision=review");
    expect(link(/refunds waiting to be paid/)).toHaveAttribute("href", "/orders?payment_status=refund_pending");
    expect(link(/orders awaiting payment/)).toHaveAttribute("href", "/orders?status=awaiting_payment");
    expect(link(/products out of stock/)).toHaveAttribute("href", "/inventory?status=out_of_stock");
    expect(link(/open investigation cases/)).toHaveAttribute("href", "/investigations");
  });
  it("says all clear when nothing is waiting", async () => {
    api.overview.mockResolvedValue(overview({ orders: { by_status: {}, revenue_by_currency_cents: {} }, inventory: { low_stock_products: 0, out_of_stock_products: 0 },
      cases: { open: 0, open_by_severity: {} }, scamwatch: { by_review_status: {} } }));
    api.riskSummary.mockResolvedValue({ counts: { allow: 0, review: 0, high: 0 } });
    api.staffOrders.mockResolvedValue({ items: [], total: 0 });
    view(<StoreOverview days={30}/>);
    expect(await screen.findByText(/all clear/i)).toBeInTheDocument();
    expect(screen.getByText("K0.00")).toBeInTheDocument();
  });
  it("still renders when the risk summary is unavailable and reports an overview failure", async () => {
    api.riskSummary.mockRejectedValue(new Error("403"));
    view(<StoreOverview days={7}/>);
    expect(await screen.findByRole("region", { name: "Store at a glance" })).toBeInTheDocument();
    api.overview.mockRejectedValue(new Error("The database is unavailable."));
    view(<StoreOverview days={30}/>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/database is unavailable/i);
  });
});

describe("deep links from the dashboard", () => {
  it("the orders screen opens already filtered by the address", async () => {
    api.staffOrders.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
    view(<StaffOrders/>, "/orders?decision=high&payment_status=refund_pending");
    await waitFor(() => expect(api.staffOrders).toHaveBeenCalledWith(expect.objectContaining({ decision: "high", payment_status: "refund_pending" })));
    expect(screen.getByLabelText("Risk")).toHaveValue("high");
    expect(screen.getByLabelText("Payment")).toHaveValue("refund_pending");
  });
  it("the inventory screen opens on the chosen stock level and ignores junk", async () => {
    api.inventory.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
    view(<InventoryMonitor/>, "/inventory?status=out_of_stock");
    await waitFor(() => expect(api.inventory).toHaveBeenCalledWith(expect.objectContaining({ status: "out_of_stock" })));
    expect(screen.getByLabelText("Stock level")).toHaveValue("out_of_stock");
    view(<InventoryMonitor/>, "/inventory?status=drop-table");
    await waitFor(() => expect(api.inventory).toHaveBeenLastCalledWith(expect.objectContaining({ status: "" })));
  });
});
