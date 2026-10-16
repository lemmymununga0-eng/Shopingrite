import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ value: {} }));
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth.value }));
vi.mock("../services/api", () => ({
  api: { modelInfo: vi.fn(), predict: vi.fn(), transactions: vi.fn(), transaction: vi.fn(), alerts: vi.fn(), stats: vi.fn(), reviewAlert: vi.fn(), health: vi.fn() },
}));

import { api } from "../services/api";
import Transaction, { validate } from "../pages/Transaction";
import History from "../pages/History";
import Alerts from "../pages/Alerts";
import Dashboard from "../pages/Dashboard";
import Settings from "../pages/Settings";
import Profile from "../pages/Profile";
import PaymentCard from "../pages/PaymentCard";
import TransactionDetail from "../pages/TransactionDetail";

const tx = (over = {}) => ({
  id: "t1", user_id: "u1", transaction_reference: "TX-1", amount: 250, payment_method: "Card", hour: 14, failed_attempts: 0,
  new_device: false, international: false, customer_avg_spend: 240, branch: "Online", probability: 0.1234, risk: "Low",
  prediction: "Likely Legitimate", is_flagged: false, model_version: "rf-test", contributing_factors: [],
  review_status: null, review_notes: null, reviewed_by: null, reviewed_at: null, created_at: "2026-10-15T10:00:00Z", ...over,
});
const alertTx = (over = {}) => tx({ id: "a1", transaction_reference: "TX-ALERT", risk: "High", probability: 0.91, prediction: "Potential Fraud",
  is_flagged: true, review_status: "new", contributing_factors: ["International transaction"], ...over });
const page = (items, total = items.length) => ({ items, total, page: 1, page_size: 15 });
const STATS = { total_transactions: 7, flagged: 2, lower_risk: 5, total_amount: 1234.5, open_alerts: 1, confirmed_fraud: 1, false_positive: 0, reviewed: 1,
  avg_probability: 0.2, flag_rate: 0.2857, risk_counts: { Low: 5, Medium: 1, High: 1 }, period_days: 30,
  daily: [{ date: "2026-10-14", total: 3, flagged: 1 }, { date: "2026-10-15", total: 4, flagged: 1 }] };
const EMPTY_STATS = { ...STATS, total_transactions: 0, flagged: 0, lower_risk: 0, total_amount: 0, open_alerts: 0, confirmed_fraud: 0, reviewed: 0,
  avg_probability: null, flag_rate: null, risk_counts: { Low: 0, Medium: 0, High: 0 }, daily: [{ date: "2026-10-15", total: 0, flagged: 0 }] };
const MODEL = { trained: true, version: "rf-test", is_synthetic: true };
const view = (ui, path = "/") => render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  auth.value = { role: "customer", user: { id: "u1", email: "pat@x.co", user_metadata: { full_name: "Pat Doe" }, created_at: "2026-01-01T00:00:00Z" } };
  api.modelInfo.mockResolvedValue(MODEL);
  api.stats.mockResolvedValue(STATS);
});

describe("payment form validation", () => {
  const good = { transaction_reference: "TX-1", amount: "100", payment_method: "Card", hour: "12", failed_attempts: "0",
    new_device: "no", international: "no", customer_avg_spend: "90", branch: "Online" };
  it("accepts a valid form and builds a typed payload", () => {
    const { errors, payload } = validate(good);
    expect(errors).toEqual({});
    expect(payload).toMatchObject({ amount: 100, hour: 12, new_device: false, international: false });
  });
  it.each([
    [{ amount: "" }, "amount"], [{ amount: "-5" }, "amount"], [{ amount: "abc" }, "amount"], [{ hour: "24" }, "hour"],
    [{ hour: "1.5" }, "hour"], [{ failed_attempts: "11" }, "failed_attempts"], [{ customer_avg_spend: "" }, "customer_avg_spend"],
    [{ transaction_reference: "a b" }, "transaction_reference"], [{ branch: "Mars" }, "branch"], [{ payment_method: "Cash" }, "payment_method"],
  ])("rejects %j", (over, field) => { expect(validate({ ...good, ...over }).errors).toHaveProperty(field); });
});

describe("New Payment page", () => {
  async function fillAndSubmit() {
    await userEvent.type(screen.getByLabelText(/^Amount/), "5000");
    await userEvent.type(screen.getByLabelText(/Customer Average Spend/), "100");
    await userEvent.click(screen.getByRole("button", { name: /submit for analysis/i }));
  }
  it("blocks submission when the form is invalid", async () => {
    view(<Transaction/>);
    await screen.findByText(/real model loaded/i);
    await userEvent.click(screen.getByRole("button", { name: /submit for analysis/i }));
    expect((await screen.findAllByRole("alert")).length).toBeGreaterThan(0);
    expect(api.predict).not.toHaveBeenCalled();
  });
  it("sends the form to the API and shows the returned score, version, factors and a details link", async () => {
    api.predict.mockResolvedValue({ saved: true, explanation_note: "Rule checks only.", transaction: alertTx({ transaction_reference: "TX-NEW", amount: 5000 }) });
    view(<Transaction/>);
    await screen.findByText(/real model loaded/i);
    await fillAndSubmit();
    expect(await screen.findByText("Potential Fraud")).toBeInTheDocument();
    expect(screen.getByText("91.0%")).toBeInTheDocument();
    expect(screen.getByText(/Model version:/)).toHaveTextContent("rf-test");
    expect(screen.getByText("International transaction")).toBeInTheDocument();
    expect(screen.getByText(/alert was created/i)).toBeInTheDocument();
    expect(screen.getByText(/not proof of fraud/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view details/i })).toHaveAttribute("href", "/transactions/a1");
    const sent = api.predict.mock.calls[0][0];
    expect(sent).toMatchObject({ amount: 5000, customer_avg_spend: 100, new_device: false, payment_method: "Card" });
    expect(sent).not.toHaveProperty("probability");
  });
  it("shows the API error and no score when prediction fails", async () => {
    api.predict.mockRejectedValue(new Error("Model unavailable: Model file not found"));
    view(<Transaction/>);
    await screen.findByText(/real model loaded/i);
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent(/model unavailable/i);
    expect(screen.queryByText(/model fraud probability/i)).toBeNull();
  });
  it("disables analysis and says so when no model is available", async () => {
    api.modelInfo.mockResolvedValue({ trained: false, message: "Model file not found" });
    view(<Transaction/>);
    expect(await screen.findByText(/model unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit for analysis/i })).toBeDisabled();
  });
  it("Reset clears the form and any result", async () => {
    api.predict.mockResolvedValue({ saved: true, explanation_note: "x", transaction: alertTx() });
    view(<Transaction/>);
    await screen.findByText(/real model loaded/i);
    await fillAndSubmit();
    await screen.findByText("Potential Fraud");
    await userEvent.click(screen.getByRole("button", { name: /reset/i }));
    expect(screen.queryByText("Potential Fraud")).toBeNull();
    expect(screen.getByLabelText(/^Amount/)).toHaveValue(null);
  });
  it("starts with the default payment method from Settings", async () => {
    localStorage.setItem("fg_prefs", JSON.stringify({ defaultMethod: "Mobile Money" }));
    view(<Transaction/>);
    expect(screen.getByLabelText("Payment Method")).toHaveValue("Mobile Money");
  });
});

describe("Dashboard", () => {
  beforeEach(() => { api.transactions.mockResolvedValue(page([tx()])); api.alerts.mockResolvedValue(page([alertTx()])); });
  it("shows metrics from the API, not hardcoded numbers", async () => {
    view(<Dashboard/>);
    expect(await screen.findByText("1 awaiting review")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("28.6%")).toBeInTheDocument();                  // flag_rate 0.2857
    expect(screen.getByText(/avg risk 20.0%/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /7 total, 2 flagged/i })).toBeInTheDocument();   // chart summary computed from the daily series
    expect(screen.getByRole("img", { name: /Low 5, Medium 1, High 1/ })).toBeInTheDocument();
    expect(screen.getByText(/welcome, Pat/i)).toBeInTheDocument();
  });
  it("shows zeros and empty chart states when there is no data (no invented trend)", async () => {
    api.stats.mockResolvedValue(EMPTY_STATS); api.transactions.mockResolvedValue(page([])); api.alerts.mockResolvedValue(page([]));
    view(<Dashboard/>);
    expect((await screen.findAllByText(/no transactions in this period yet\./i)).length).toBe(2);   // banner + empty chart
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);              // flag rate unavailable, not 0%
    expect(screen.queryByRole("img", { name: /transactions per day/i })).toBeNull();
  });
  it("changing the period reloads the statistics", async () => {
    view(<Dashboard/>);
    await screen.findByText("1 awaiting review");
    await userEvent.selectOptions(screen.getByLabelText(/reporting period/i), "90");
    await waitFor(() => expect(api.stats).toHaveBeenLastCalledWith(90));
  });
  it("shows an error state with retry when the API is down, and no fake numbers", async () => {
    api.stats.mockRejectedValueOnce(new Error("Cannot reach the FraudGuard API. Is the backend running?"));
    view(<Dashboard/>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot reach/i);
    expect(screen.queryByText("Total Transactions")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Total Transactions")).toBeInTheDocument();
  });
});

describe("Transaction History", () => {
  it("renders records with view-details links", async () => {
    api.transactions.mockResolvedValue(page([tx(), tx({ id: "t2", transaction_reference: "TX-2" })]));
    view(<History/>);
    expect(await screen.findByText("TX-1")).toBeInTheDocument();
    expect(screen.getByText("TX-2")).toBeInTheDocument();
    expect(screen.getByText(/2 transactions saved/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view details for TX-2/i })).toHaveAttribute("href", "/transactions/t2");
  });
  it("shows an empty state", async () => {
    api.transactions.mockResolvedValue(page([]));
    view(<History/>);
    expect(await screen.findByText(/no transactions yet/i)).toBeInTheDocument();
  });
  it("shows an error with retry", async () => {
    api.transactions.mockRejectedValueOnce(new Error("Cannot reach the FraudGuard API.")).mockResolvedValue(page([tx()]));
    view(<History/>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot reach/i);
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("TX-1")).toBeInTheDocument();
  });
  it("applies search, risk, status and date filters, then clears them", async () => {
    api.transactions.mockResolvedValue(page([tx()]));
    view(<History/>);
    await screen.findByText("TX-1");
    await userEvent.type(screen.getByLabelText("Search reference"), "ABC");
    await userEvent.selectOptions(screen.getByLabelText("Risk level"), "High");
    await userEvent.type(screen.getByLabelText("From date"), "2026-10-01");
    await userEvent.type(screen.getByLabelText("To date"), "2026-10-15");
    await userEvent.click(screen.getByRole("button", { name: /apply/i }));
    await waitFor(() => expect(api.transactions).toHaveBeenLastCalledWith(expect.objectContaining(
      { search: "ABC", risk: "High", date_from: "2026-10-01", date_to: "2026-10-15", page: 1 })));
    api.transactions.mockResolvedValue(page([]));
    await userEvent.click(screen.getByRole("button", { name: /clear filters/i }));
    await waitFor(() => expect(api.transactions).toHaveBeenLastCalledWith(expect.objectContaining({ search: "", risk: "", date_from: "", date_to: "" })));
  });
  it("blocks an impossible date range", async () => {
    api.transactions.mockResolvedValue(page([tx()]));
    view(<History/>);
    await screen.findByText("TX-1");
    const calls = api.transactions.mock.calls.length;
    await userEvent.type(screen.getByLabelText("From date"), "2026-10-20");
    await userEvent.type(screen.getByLabelText("To date"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: /apply/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/must not be after/i);
    expect(api.transactions.mock.calls.length).toBe(calls);
  });
  it("sorts by a column and toggles direction", async () => {
    api.transactions.mockResolvedValue(page([tx()]));
    view(<History/>);
    await screen.findByText("TX-1");
    await userEvent.click(screen.getByRole("button", { name: "Amount" }));
    await waitFor(() => expect(api.transactions).toHaveBeenLastCalledWith(expect.objectContaining({ sort_by: "amount", sort_dir: "desc" })));
    await userEvent.click(screen.getByRole("button", { name: "Amount" }));
    await waitFor(() => expect(api.transactions).toHaveBeenLastCalledWith(expect.objectContaining({ sort_by: "amount", sort_dir: "asc" })));
    expect(screen.getByRole("columnheader", { name: /amount/i })).toHaveAttribute("aria-sort", "ascending");
  });
  it("starts with the search term from the top bar link", async () => {
    api.transactions.mockResolvedValue(page([tx()]));
    view(<History/>, "/history?search=TX-77");
    await waitFor(() => expect(api.transactions).toHaveBeenCalledWith(expect.objectContaining({ search: "TX-77" })));
    expect(screen.getByLabelText("Search reference")).toHaveValue("TX-77");
  });
  it("paginates", async () => {
    api.transactions.mockResolvedValue({ items: [tx()], total: 40, page: 1, page_size: 15 });
    view(<History/>);
    await screen.findByText(/page 1 of 3/i);
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(api.transactions).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })));
  });
  it("uses the rows-per-page preference", async () => {
    localStorage.setItem("fg_prefs", JSON.stringify({ pageSize: 25 }));
    api.transactions.mockResolvedValue(page([tx()]));
    view(<History/>);
    await waitFor(() => expect(api.transactions).toHaveBeenCalledWith(expect.objectContaining({ page_size: 25 })));
  });
});

describe("Transaction Details", () => {
  const route = <Routes><Route path="/transactions/:id" element={<TransactionDetail/>}/></Routes>;
  it("shows only fields returned by the API, and the not-proof disclaimer", async () => {
    api.transaction.mockResolvedValue(alertTx({ review_status: "confirmed_fraud", review_notes: "Called customer", reviewed_at: "2026-10-15T11:00:00Z" }));
    view(route, "/transactions/a1");
    expect(await screen.findByText("Potential Fraud")).toBeInTheDocument();
    expect(api.transaction).toHaveBeenCalledWith("a1");
    expect(screen.getByText("91.0%")).toBeInTheDocument();
    expect(screen.getByText("Called customer")).toBeInTheDocument();
    expect(screen.getByText(/not proof of fraud/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to history/i })).toHaveAttribute("href", "/history");
    expect(screen.queryByText(/card number|cvv/i)).toBeNull();
  });
  it("shows a clear error when the transaction is missing or belongs to someone else (404)", async () => {
    api.transaction.mockRejectedValue(new Error("Transaction not found"));
    view(route, "/transactions/zzz");
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
  });
});

describe("Alerts", () => {
  beforeEach(() => { api.alerts.mockResolvedValue(page([alertTx()])); });
  it("shows summary cards from real statistics and lists alerts", async () => {
    view(<Alerts/>);
    expect(await screen.findByText("TX-ALERT")).toBeInTheDocument();
    expect(screen.getByText("New Alerts")).toBeInTheDocument();
    expect(screen.getByText("Of 2 flagged")).toBeInTheDocument();
  });
  it("customers can view an alert but have no review controls", async () => {
    view(<Alerts/>);
    await userEvent.click(await screen.findByRole("button", { name: /view alert TX-ALERT/i }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("International transaction")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /save review/i })).toBeNull();
    expect(within(dialog).getByText(/only analysts and admins/i)).toBeInTheDocument();
  });
  it("lets an analyst review an alert with confirmation and shows the saved result", async () => {
    auth.value = { role: "analyst", user: { id: "an1" } };
    api.reviewAlert.mockResolvedValue(alertTx({ review_status: "confirmed_fraud", review_notes: "Called customer", reviewed_at: "2026-10-15T11:00:00Z" }));
    view(<Alerts/>);
    await userEvent.click(await screen.findByRole("button", { name: /review alert TX-ALERT/i }));
    const dialog = screen.getByRole("dialog", { name: /alert #TX-ALERT/i });
    await userEvent.selectOptions(within(dialog).getByLabelText("Review status"), "confirmed_fraud");
    await userEvent.type(within(dialog).getByLabelText("Reviewer notes"), "Called customer");
    await userEvent.click(within(dialog).getByRole("button", { name: /save review/i }));
    expect(api.reviewAlert).not.toHaveBeenCalled();                     // nothing is sent until confirmed
    await userEvent.click(within(screen.getByRole("dialog", { name: /save review\?/i })).getByRole("button", { name: /save review/i }));
    await waitFor(() => expect(api.reviewAlert).toHaveBeenCalledWith("a1", "confirmed_fraud", "Called customer"));
    expect(await screen.findByText(/review saved/i)).toBeInTheDocument();
    expect(screen.getByText("Confirmed fraud", { selector: ".risk-badge" })).toBeInTheDocument();
  });
  it("cancelling the confirmation sends nothing", async () => {
    auth.value = { role: "admin", user: { id: "ad1" } };
    view(<Alerts/>);
    await userEvent.click(await screen.findByRole("button", { name: /review alert TX-ALERT/i }));
    await userEvent.click(screen.getByRole("button", { name: /save review/i }));
    await userEvent.click(within(screen.getByRole("dialog", { name: /save review\?/i })).getByRole("button", { name: /cancel/i }));
    expect(api.reviewAlert).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: /save review\?/i })).toBeNull();
  });
  it("Escape closes the alert dialog", async () => {
    view(<Alerts/>);
    await userEvent.click(await screen.findByRole("button", { name: /view alert TX-ALERT/i }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("shows the API error when the review fails (e.g. 403)", async () => {
    auth.value = { role: "analyst", user: { id: "an1" } };
    api.reviewAlert.mockRejectedValue(new Error("Only analysts and admins can review alerts"));
    view(<Alerts/>);
    await userEvent.click(await screen.findByRole("button", { name: /review alert TX-ALERT/i }));
    await userEvent.click(screen.getByRole("button", { name: /save review/i }));
    await userEvent.click(within(screen.getByRole("dialog", { name: /save review\?/i })).getByRole("button", { name: /save review/i }));
    expect(await screen.findByText(/only analysts and admins can review alerts/i, { selector: ".notice" })).toBeInTheDocument();
  });
  it("filters by risk, status and date and shows an empty state", async () => {
    api.alerts.mockResolvedValue(page([]));
    view(<Alerts/>);
    expect(await screen.findByText(/no fraud alerts yet/i)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Review status"), "false_positive");
    await userEvent.selectOptions(screen.getByLabelText("Risk level"), "High");
    await userEvent.type(screen.getByLabelText("From date"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: /apply/i }));
    await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ review_status: "false_positive", risk: "High", date_from: "2026-10-01" })));
    expect(await screen.findByText(/no alerts match these filters/i)).toBeInTheDocument();
  });
});

describe("Profile", () => {
  it("shows the real account and a read-only role", () => {
    auth.value = { ...auth.value, role: "analyst", updateProfile: vi.fn() };
    view(<Profile/>);
    expect(screen.getAllByText("Pat Doe").length).toBeGreaterThan(0);
    expect(screen.getByText("pat@x.co")).toBeInTheDocument();
    expect(screen.getByText("analyst")).toBeInTheDocument();
    expect(screen.queryByLabelText(/role/i)).toBeNull();
  });
  it("saves a changed name, validates empty, and Cancel reverts", async () => {
    const updateProfile = vi.fn().mockResolvedValue();
    auth.value = { ...auth.value, updateProfile };
    view(<Profile/>);
    const input = screen.getByLabelText("Full name");
    await userEvent.clear(input);
    await userEvent.click(screen.getByRole("button", { name: /save changes/i }));
    expect(await screen.findByText("Enter your name")).toBeInTheDocument();
    expect(updateProfile).not.toHaveBeenCalled();
    await userEvent.type(input, "Patricia Doe");
    await userEvent.click(screen.getByRole("button", { name: /save changes/i }));
    await waitFor(() => expect(updateProfile).toHaveBeenCalledWith("Patricia Doe"));
    expect(await screen.findByText(/profile updated/i)).toBeInTheDocument();
    await userEvent.type(input, "x");
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(input).toHaveValue("Pat Doe");
  });
});

describe("Payment Card", () => {
  it("is clearly a demo card and lists real activity for the chosen method", async () => {
    api.transactions.mockResolvedValue({ items: [tx()], total: 4, page: 1, page_size: 5 });
    view(<PaymentCard/>);
    expect(screen.getByText(/demo card — not a real card/i)).toBeInTheDocument();
    expect(await screen.findByText(/4 transactions with this method/i)).toBeInTheDocument();
    expect(api.transactions).toHaveBeenCalledWith({ payment_method: "Card", page_size: 5 });
    await userEvent.selectOptions(screen.getByLabelText("Payment method"), "Mobile Money");
    await waitFor(() => expect(api.transactions).toHaveBeenLastCalledWith({ payment_method: "Mobile Money", page_size: 5 }));
  });
  it("saves the default method preference", async () => {
    api.transactions.mockResolvedValue(page([]));
    view(<PaymentCard/>);
    await userEvent.selectOptions(screen.getByLabelText("Payment method"), "Bank Transfer");
    await userEvent.click(screen.getByRole("button", { name: /save preference/i }));
    expect(await screen.findByText(/preference saved/i)).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("fg_prefs")).defaultMethod).toBe("Bank Transfer");
  });
});

describe("Settings", () => {
  beforeEach(() => { auth.value = { ...auth.value, updatePassword: vi.fn() }; });
  it("has the five sections as accessible tabs", () => {
    view(<Settings/>);
    expect(screen.getAllByRole("tab").map(t => t.textContent)).toEqual(
      ["Account Preferences", "Notifications", "Security", "Application Preferences", "Data and Privacy"]);
  });
  it("persists real preferences (notifications, page size, default method)", async () => {
    view(<Settings/>);
    await userEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    await userEvent.click(screen.getByRole("switch"));
    expect(JSON.parse(localStorage.getItem("fg_prefs")).alertBadge).toBe(false);
    await userEvent.click(screen.getByRole("tab", { name: "Application Preferences" }));
    await userEvent.selectOptions(screen.getByLabelText(/rows per page/i), "25");
    expect(JSON.parse(localStorage.getItem("fg_prefs")).pageSize).toBe(25);
  });
  it("validates and submits a password change through the auth provider", async () => {
    auth.value.updatePassword.mockResolvedValue();
    view(<Settings/>);
    await userEvent.click(screen.getByRole("tab", { name: "Security" }));
    await userEvent.type(screen.getByLabelText("New password"), "short");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "short");
    await userEvent.click(screen.getByRole("button", { name: /update password/i }));
    expect(await screen.findByText(/at least 8 characters/i, { selector: ".field-error" })).toBeInTheDocument();
    expect(auth.value.updatePassword).not.toHaveBeenCalled();
    await userEvent.clear(screen.getByLabelText("New password")); await userEvent.clear(screen.getByLabelText("Confirm new password"));
    await userEvent.type(screen.getByLabelText("New password"), "newpass123");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "newpass123");
    await userEvent.click(screen.getByRole("button", { name: /update password/i }));
    await waitFor(() => expect(auth.value.updatePassword).toHaveBeenCalledWith("newpass123"));
    expect(await screen.findByText(/password updated/i)).toBeInTheDocument();
  });
  it("shows model version, metrics and the synthetic-data warning under Data and Privacy", async () => {
    api.health.mockResolvedValue({ status: "ok", db_backend: "sqlite", auth_configured: true });
    api.modelInfo.mockResolvedValue({ trained: true, version: "rf-x", data_source: "synthetic", is_synthetic: true, threshold: 0.3,
      metrics: { precision: 0.25, recall: 0.62, f1: 0.36, pr_auc: 0.39, roc_auc: 0.84, test_rows: 4000, support_fraud: 247 },
      global_feature_importance: [{ feature: "amount", importance: 0.3 }], importance_note: "Global only." });
    view(<Settings/>);
    await userEvent.click(screen.getByRole("tab", { name: "Data and Privacy" }));
    expect(await screen.findByText("rf-x")).toBeInTheDocument();
    expect(screen.getByText(/do not show real-world/i)).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });
});
