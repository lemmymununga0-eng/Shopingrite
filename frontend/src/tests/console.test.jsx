import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = { value: {} };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth.value }));
vi.mock("../services/api", () => {
  const names = ["cases", "caseDetail", "updateCase", "createCase", "scamCheck", "scamReport", "scamReports", "reviewScamReport",
    "securityEvents", "securityEvent", "securitySummary", "thresholds", "setThresholds", "inventory", "adjustInventory", "overview",
    "fraudReport", "users", "updateUser", "audit", "integrations", "alerts"];
  return { ApiError: class extends Error {}, setUnauthorizedHandler: () => {}, api: Object.fromEntries(names.map(n => [n, vi.fn()])) };
});

import { api } from "../services/api";
import Investigations from "../pages/Investigations";
import ScamWatch from "../pages/ScamWatch";
import SecurityMonitor from "../pages/SecurityMonitor";
import InventoryMonitor from "../pages/InventoryMonitor";
import Reports from "../pages/Reports";
import { AuditTrail, Integrations, Users } from "../pages/AdminPages";
import Sidebar from "../components/Sidebar";
import OperationsOverview from "../components/OperationsOverview";

const staff = role => ({ user: { id: "me", email: "me@example.com", user_metadata: { full_name: "Sam Analyst" } }, role, loading: false, logout: vi.fn() });
const view = ui => render(<MemoryRouter>{ui}</MemoryRouter>);
const list = (items, total = items.length) => ({ items, total, page: 1, page_size: 20 });
const aCase = (over = {}) => ({ id: 1, case_reference: "CASE-000001", source_type: "fraud_prediction", source_record_id: "t1", severity: "high", status: "new",
  summary: "Model score 0.91 (High risk) for transaction TX-1. A model score or report is a signal for review, not proof of wrongdoing.",
  evidence_reference: "transaction:t1", assigned_to: null, created_by: null, created_at: "2026-10-16T09:00:00Z", updated_at: "2026-10-16T09:00:00Z",
  resolved_at: null, note_count: 0, signal_note: "A model score or report is a signal for review, not proof of wrongdoing.", notes: [], ...over });

beforeEach(() => { vi.clearAllMocks(); auth.value = staff("fraud_analyst"); });

describe("role-aware navigation (convenience only; the API enforces permissions)", () => {
  const links = () => screen.getAllByRole("link").map(a => a.textContent.trim());
  it("fraud analysts see fraud tools but not the security monitor, users or audit trail", () => {
    auth.value = staff("fraud_analyst"); view(<Sidebar onNavigate={() => {}}/>);
    expect(links()).toEqual(expect.arrayContaining(["Investigations", "Fraud Alerts", "ScamWatch", "Reports"]));
    for (const hidden of ["Security Monitor", "Users & Roles", "Audit Trail"]) expect(links()).not.toContain(hidden);
  });
  it("security analysts see the security monitor and audit trail", () => {
    auth.value = staff("security_analyst"); view(<Sidebar onNavigate={() => {}}/>);
    expect(links()).toEqual(expect.arrayContaining(["Security Monitor", "Audit Trail"]));
    expect(links()).not.toContain("Users & Roles");
  });
  it("administrators see everything and can return to the customer store", () => {
    auth.value = staff("admin"); view(<Sidebar onNavigate={() => {}}/>);
    expect(links()).toEqual(expect.arrayContaining(["Security Monitor", "Users & Roles", "Audit Trail", "Customer store"]));
    expect(screen.getByRole("link", { name: "Customer store" })).toHaveAttribute("href", "/shop");
  });
});

describe("investigations workflow", () => {
  it("lists cases, filters through the API, and shows an empty state", async () => {
    api.cases.mockResolvedValue(list([aCase(), aCase({ id: 2, case_reference: "CASE-000002", source_type: "scamwatch_report", severity: "medium", summary: "Reported website bad.example" })]));
    view(<Investigations/>);
    expect(await screen.findByText("CASE-000001")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("Fraud prediction")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "high");
    await userEvent.selectOptions(screen.getByLabelText("Assigned"), "me");
    await waitFor(() => expect(api.cases).toHaveBeenLastCalledWith(expect.objectContaining({ severity: "high", assigned_to: "me", page: 1 })));
    api.cases.mockResolvedValue(list([]));
    await userEvent.type(screen.getByLabelText("Search"), "nothing");
    expect(await screen.findByText(/no cases match/i)).toBeInTheDocument();
  });
  it("states that a score is a signal, and walks a case from new to investigating with a note", async () => {
    api.cases.mockResolvedValue(list([aCase()]));
    api.caseDetail.mockResolvedValue(aCase());
    api.updateCase.mockResolvedValue(aCase({ status: "investigating", assigned_to: "me", note_count: 1, notes: [{ id: 1, author_id: "me", body: "Calling the customer", created_at: "2026-10-16T09:05:00Z" }] }));
    view(<Investigations/>);
    await userEvent.click(await screen.findByRole("button", { name: "Open CASE-000001" }));
    const dialog = await screen.findByRole("dialog", { name: /case-000001/i });
    expect(within(dialog).getAllByText(/not proof of wrongdoing/i).length).toBeGreaterThan(0);
    await userEvent.type(within(dialog).getByLabelText("Add a note"), "Calling the customer");
    await userEvent.selectOptions(within(dialog).getByLabelText("Status"), "investigating");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(api.updateCase).toHaveBeenCalledWith(1, { status: "investigating", note: "Calling the customer" });
    expect(await within(dialog).findByText("Calling the customer")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Unassign" }));
    expect(api.updateCase).toHaveBeenLastCalledWith(1, { assigned_to: null });
  });
  it("assigns to me and surfaces permission errors from the server", async () => {
    api.cases.mockResolvedValue(list([aCase({ source_type: "security_alert" })]));
    api.caseDetail.mockResolvedValue(aCase({ source_type: "security_alert" }));
    api.updateCase.mockRejectedValue(new Error("Your role does not handle this kind of case"));
    view(<Investigations/>);
    await userEvent.click(await screen.findByRole("button", { name: "Open CASE-000001" }));
    await userEvent.click(await screen.findByRole("button", { name: "Assign to me" }));
    expect(api.updateCase).toHaveBeenCalledWith(1, { assigned_to: "me" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/does not handle this kind of case/i);
  });
  it("creates a manual case with validation", async () => {
    api.cases.mockResolvedValue(list([]));
    api.createCase.mockResolvedValue(aCase());
    view(<Investigations/>);
    await userEvent.click(await screen.findByRole("button", { name: /new case/i }));
    await userEvent.click(screen.getByRole("button", { name: "Create case" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/at least 3 characters/i);
    const dlg = screen.getByRole("dialog");
    await userEvent.type(within(dlg).getByLabelText("Summary"), "Odd phone call from a customer");
    await userEvent.selectOptions(within(dlg).getByLabelText("Severity"), "high");
    await userEvent.click(within(dlg).getByRole("button", { name: "Create case" }));
    expect(api.createCase).toHaveBeenCalledWith({ summary: "Odd phone call from a customer", severity: "high", evidence_reference: "" });
  });
});

describe("ScamWatch console", () => {
  const report = (over = {}) => ({ id: 5, normalized_url: "http://bad.example/", domain: "bad.example", report_count: 2, verdict: "malicious",
    review_status: "pending", analyst_notes: "", last_reported_at: "2026-10-16T09:00:00Z", ...over });
  beforeEach(() => { api.integrations.mockResolvedValue({ scamwatch_providers: [{ name: "heuristic", configured: true, live_tested: false }] }); });
  it("shows history, provider status, and lets a security analyst review", async () => {
    auth.value = staff("security_analyst");
    api.scamReports.mockResolvedValue(list([report()]));
    api.reviewScamReport.mockResolvedValue({});
    view(<ScamWatch/>);
    expect(await screen.findByText("http://bad.example/")).toBeInTheDocument();
    expect(await screen.findByText(/heuristic \(configured, live calls not verified\)/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review bad.example" }));
    const dlg = screen.getByRole("dialog");
    await userEvent.selectOptions(within(dlg).getByLabelText("Review status"), "reviewed_malicious");
    await userEvent.type(within(dlg).getByLabelText("Analyst notes"), "confirmed by call");
    await userEvent.click(within(dlg).getByRole("button", { name: "Save review" }));
    expect(api.reviewScamReport).toHaveBeenCalledWith(5, "reviewed_malicious", "confirmed by call");
  });
  it("fraud analysts can read reports but get no review button", async () => {
    api.scamReports.mockResolvedValue(list([report()]));
    view(<ScamWatch/>);
    await screen.findByText("http://bad.example/");
    expect(screen.queryByRole("button", { name: /review bad.example/i })).not.toBeInTheDocument();
  });
  it("filters the report list and shows an empty state", async () => {
    api.scamReports.mockResolvedValue(list([]));
    view(<ScamWatch/>);
    expect(await screen.findByText(/no reports yet/i)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Verdict"), "malicious");
    await waitFor(() => expect(api.scamReports).toHaveBeenLastCalledWith(expect.objectContaining({ verdict: "malicious" })));
  });
});

describe("Security Monitor", () => {
  const ev = (over = {}) => ({ id: 9, created_at: "2026-10-16T09:00:00Z", severity: "medium", category: "authentication", event_type: "auth.invalid_token",
    message: "Invalid access token presented", correlation_id: "abc123abc123", path: "/cart", method: "GET", status_code: 401, ...over });
  beforeEach(() => {
    auth.value = staff("security_analyst");
    api.securitySummary.mockResolvedValue({ total: 4, by_severity: { medium: 3, high: 1 }, by_category: { authentication: 2, rate_limit: 1 } });
    api.thresholds.mockResolvedValue({ thresholds: { auth_failures_per_10min: 10 }, window_minutes: 10 });
    api.securityEvents.mockResolvedValue(list([ev()]));
  });
  it("shows summary cards, events, filters by severity/category/search/date and validates the date range", async () => {
    view(<SecurityMonitor/>);
    expect(await screen.findByText("auth.invalid_token")).toBeInTheDocument();
    expect(await screen.findByText("Events (7 days)")).toBeInTheDocument();
    expect(screen.getByText(/not monitor any network or production infrastructure/i)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "high");
    await userEvent.selectOptions(screen.getByLabelText("Category"), "rate_limit");
    await userEvent.type(screen.getByLabelText("Search"), "token");
    await waitFor(() => expect(api.securityEvents).toHaveBeenLastCalledWith(expect.objectContaining({ severity: "high", category: "rate_limit", search: "token" })));
    await userEvent.type(screen.getByLabelText("From"), "2026-10-20");
    await userEvent.type(screen.getByLabelText("To"), "2026-10-10");
    expect(await screen.findByText(/start date cannot be after the end date/i)).toBeInTheDocument();
  });
  it("opens event details with the correlation id and redacted details", async () => {
    api.securityEvent.mockResolvedValue({ ...ev(), actor_id: null, details: { fields: ["amount"] } });
    view(<SecurityMonitor/>);
    await userEvent.click(await screen.findByRole("button", { name: "Details for event 9" }));
    const dlg = await screen.findByRole("dialog", { name: /security event #9/i });
    expect(within(dlg).getByText("abc123abc123")).toBeInTheDocument();
    expect(within(dlg).getByText(/"fields"/)).toBeInTheDocument();
  });
  it("shows an empty state, and thresholds are read-only unless admin", async () => {
    api.securityEvents.mockResolvedValue(list([]));
    view(<SecurityMonitor/>);
    expect(await screen.findByText(/no security events match/i)).toBeInTheDocument();
    expect(await screen.findByLabelText(/auth failures per 10min/i)).toBeDisabled();
    expect(screen.getByText(/only administrators can change thresholds/i)).toBeInTheDocument();
  });
  it("administrators can save thresholds", async () => {
    auth.value = staff("admin");
    api.setThresholds.mockResolvedValue({ thresholds: { auth_failures_per_10min: 5 } });
    view(<SecurityMonitor/>);
    const input = await screen.findByLabelText(/auth failures per 10min/i);
    await userEvent.clear(input); await userEvent.type(input, "5");
    await userEvent.click(screen.getByRole("button", { name: /save thresholds/i }));
    expect(api.setThresholds).toHaveBeenCalledWith({ auth_failures_per_10min: 5 });
    expect(await screen.findByText(/thresholds saved/i)).toBeInTheDocument();
  });
  it("shows the API error when the caller lacks permission", async () => {
    api.securityEvents.mockRejectedValue(new Error("You do not have permission to do this"));
    view(<SecurityMonitor/>);
    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/i);
  });
});

describe("inventory, reports, admin pages", () => {
  it("inventory shows database stock and only admins can adjust (with a mandatory audited reason)", async () => {
    auth.value = staff("admin");
    api.inventory.mockResolvedValue(list([{ product_id: 3, sku: "DEMO-FP-003", name: "Tomatoes", available_quantity: 4, reserved_quantity: 1, reorder_threshold: 10, stock_status: "low_stock" }]));
    api.adjustInventory.mockResolvedValue({});
    view(<InventoryMonitor/>);
    expect(await screen.findByText("Tomatoes")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("Low stock")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Adjust Tomatoes" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/give a reason/i);
    await userEvent.type(screen.getByLabelText(/reason/i), "stock count correction");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(api.adjustInventory).toHaveBeenCalledWith(3, { set_available: 4, reason: "stock count correction" });
  });
  it("inventory is read-only for analysts", async () => {
    api.inventory.mockResolvedValue(list([{ product_id: 3, sku: "S", name: "Tomatoes", available_quantity: 4, reserved_quantity: 0, reorder_threshold: 10, stock_status: "low_stock" }]));
    view(<InventoryMonitor/>);
    await screen.findByText("Tomatoes");
    expect(screen.queryByRole("button", { name: /adjust/i })).not.toBeInTheDocument();
  });
  const overview = (over = {}) => ({ period_days: 30, definitions: { transactions_analysed: "t", flagged: "f", confirmed_fraud: "c", false_positive: "fp", open_cases: "oc", average_resolution_hours: "ar", scam_reports: "sr", inventory_anomalies: "ia", security_events: "se" },
    fraud: { transactions_analysed: 0, flagged: 0, confirmed_fraud: 0, false_positive: 0 }, fraud_error: null,
    cases: { open: 0, by_status: {}, open_by_severity: {}, by_source: {}, resolution: { average_hours: null, resolved_cases: 0 }, workload_by_assignee: {}, recent: [] },
    scamwatch: { reports: 0, by_review_status: {}, by_verdict: {} }, security: null,
    inventory: { low_stock_products: 3, out_of_stock_products: 4, anomaly_cases: 0 }, orders: { by_status: {}, revenue_by_currency_cents: {}, note: "Demonstration orders with simulated payment; no real money moved." }, ...over });
  it("reports show a clear empty state with zero figures rather than invented numbers", async () => {
    api.overview.mockResolvedValue(overview());
    api.fraudReport.mockResolvedValue({ model: { available: true, version: "rf-1", is_synthetic: true, threshold: 0.3, note: "Offline metrics say nothing about real fraud." }, observed: { review_agreement: null }, definitions: { review_agreement: "x" } });
    view(<Reports/>);
    expect(await screen.findByText(/no activity recorded yet/i)).toBeInTheDocument();
    expect(screen.getByText("No closed cases yet")).toBeInTheDocument();
    expect(screen.getByText(/no real money moved/i)).toBeInTheDocument();
  });
  it("the baseline comparison is labelled hypothetical", async () => {
    auth.value = staff("fraud_analyst");
    api.overview.mockResolvedValue(overview());
    api.fraudReport.mockImplementation(async p => ({ model: { available: false, message: "No model" }, observed: { review_agreement: 0.5 }, definitions: { review_agreement: "x" },
      ...(p.baseline_flag_rate ? { baseline_comparison: { label: "HYPOTHETICAL: assumptions supplied by the analyst, not measured data.", observed_flag_rate_percent: 6, difference_in_flag_rate_points: 1, exposure_identified_in_prototype: 0, note: "It is not money saved." } } : {}) }));
    view(<Reports/>);
    await userEvent.type(await screen.findByLabelText(/baseline flag rate/i), "5");
    expect((await screen.findAllByText(/HYPOTHETICAL/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/not money saved/i).length).toBeGreaterThan(0);
  });
  it("the operations overview on the dashboard comes from stored records and degrades quietly", async () => {
    api.overview.mockResolvedValue(overview({ cases: { ...overview().cases, open: 2, open_by_severity: { high: 1 }, recent: [{ id: 1, case_reference: "CASE-000001", source_type: "manual", severity: "high", status: "new", summary: "Odd call", created_at: "2026-10-16T09:00:00Z" }] } }));
    view(<OperationsOverview/>);
    expect(await screen.findByText("1 high priority")).toBeInTheDocument();
    expect(screen.getByText("Odd call")).toBeInTheDocument();
  });
  it("users page: admin changes a role; own row is locked; errors are shown", async () => {
    auth.value = staff("admin");
    api.users.mockResolvedValue({ note: "These are LOCAL demonstration accounts.", local_auth_enabled: true, items: [
      { id: "me", email: "me@example.com", full_name: "Me", role: "admin", is_active: true }, { id: "u2", email: "c@example.com", full_name: "Cust", role: "customer", is_active: true }] });
    api.updateUser.mockRejectedValueOnce(new Error("At least one active administrator must remain")).mockResolvedValue({});
    view(<Users/>);
    expect(await screen.findByLabelText("Role for me@example.com")).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Role for c@example.com"), "fraud_analyst");
    expect(api.updateUser).toHaveBeenCalledWith("u2", { role: "fraud_analyst" });
    expect(await screen.findByText(/at least one active administrator/i)).toBeInTheDocument();
  });
  it("audit trail lists actions and filters", async () => {
    api.audit.mockResolvedValue(list([{ id: 1, created_at: "2026-10-16T09:00:00Z", actor_id: "me", actor_role: "admin", action: "inventory.adjusted", entity_type: "inventory", entity_id: "3", before: { available_quantity: 4 }, after: { available_quantity: 9 } }]));
    view(<AuditTrail/>);
    expect(await screen.findByText("inventory.adjusted")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Entity type"), "case");
    await waitFor(() => expect(api.audit).toHaveBeenLastCalledWith(expect.objectContaining({ entity_type: "case" })));
  });
  it("integrations page is honest: no retailer connection, unverified providers, synthetic model", async () => {
    api.integrations.mockResolvedValue({ retailer_connection: { connected: false, note: "No real retailer system is connected. All store and event data is demonstration data." },
      store: { name: "FreshCart Demo Store", currency: "ZMW", is_demo: true, payment: "SIMULATED: no real payment provider is connected" },
      database: { application_db: "connected", application_db_engine: "sqlite", prediction_store: "sqlite" },
      authentication: { supabase_configured: false, supabase_live_tested: false, local_demo_auth_enabled: true, warning: "Local demonstration sign-in is ON." },
      payment_model: { available: true, version: "rf-1", threshold: 0.3, is_synthetic: true }, pca_model: { available: false, message: "PCA demo model not trained." },
      scamwatch_providers: [{ name: "safebrowsing", configured: false, kind: "external lookup", note: "Live calls have not been verified in this project." }],
      rate_limits_per_minute: { predict: 30 }, alert_thresholds: { auth_failures_per_10min: 10 } });
    view(<Integrations/>);
    expect(await screen.findByText(/no real retailer system is connected/i)).toBeInTheDocument();
    expect(screen.getByText(/trained on synthetic data/i)).toBeInTheDocument();
    expect(screen.getByText(/live calls have not been verified/i)).toBeInTheDocument();
    expect(screen.getByText(/local demonstration sign-in is on/i)).toBeInTheDocument();
  });
});
