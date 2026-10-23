import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../services/api", () => ({ ApiError: class extends Error {}, setUnauthorizedHandler: () => {},
  api: { fraudModelStatus: vi.fn(), mlSummary: vi.fn(), labelQueue: vi.fn() } }));

import { api } from "../services/api";
import FraudModelPanel from "../components/FraudModelPanel";

const ready = { model: "creditcard_pca", label: "Card transaction fraud", state: "ready", ready: true, version: "v1", trained_at: "2026-10-23T09:00:00Z",
  is_fixture: false, dataset: { name: "creditcard-openml", licence: "Public" }, threshold: 0.31,
  test_metrics: { precision: 0.926, recall: 0.79, f1: 0.852, pr_auc: 0.8, false_positives: 6, support_legitimate: 56651 }, metrics_note: "Held-out test metrics." };
const untrained = { model: "paysim_mobile_money", label: "Mobile-money fraud", state: "not_trained", ready: false, detail: "No trained model has been promoted." };

beforeEach(() => {
  vi.clearAllMocks();
  api.mlSummary.mockResolvedValue({ prediction_status_counts: { unsupported_input_schema: 3 }, verified_outcome_counts: {} });
});

describe("fraud model panel", () => {
  it("shows real metadata for a ready model and an honest state for an untrained one", async () => {
    api.fraudModelStatus.mockResolvedValue({ models: [ready, untrained], store_scoring: { message: "Store orders use store_risk_v1." } });
    render(<MemoryRouter><FraudModelPanel/></MemoryRouter>);
    expect(await screen.findByText("Card transaction fraud")).toBeInTheDocument();
    expect(screen.getByText(/Version v1/)).toBeInTheDocument();
    expect(screen.getByText("92.6%")).toBeInTheDocument();
    expect(screen.getByText("Not trained")).toBeInTheDocument();
    expect(screen.getByText("No trained model has been promoted.")).toBeInTheDocument();
    expect(screen.getByText(/3 unsupported input schema/)).toBeInTheDocument();
  });

  it("says plainly that rules assess store orders and shows label progress", async () => {
    api.fraudModelStatus.mockResolvedValue({ models: [{ ...untrained, model: "store_grocery", label: "Grocery-store order risk" }],
      store_scoring: { method: "rules", message: "Store orders are scored by the rule engine store_risk_v1.",
        labels: { verified_fraud: 3, verified_legitimate: 40, distinct_customers: 12, required: { verified_fraud: 150, verified_legitimate: 1000, distinct_customers: 50 } } } });
    render(<MemoryRouter><FraudModelPanel/></MemoryRouter>);
    expect(await screen.findByText(/rules \(store_risk_v1\), not a trained model/)).toBeInTheDocument();
    expect(screen.getByText(/3 fraud of 150 needed/)).toBeInTheDocument();
    expect(screen.getByText("Not trained")).toBeInTheDocument();
  });

  it("lists orders waiting for a verified outcome, including the unflagged audit sample", async () => {
    api.fraudModelStatus.mockResolvedValue({ models: [untrained], store_scoring: {} });
    api.labelQueue.mockResolvedValue({ flagged_waiting: 1, audit_sample_waiting: 1, audit_sample_rate: "1 in 10 unflagged orders per week",
      items: [{ order_id: "a", reference: "ORD-1", why: "flagged by rules", rules_score: 45 }, { order_id: "b", reference: "ORD-2", why: "audit sample (unflagged)", rules_score: 0 }] });
    render(<MemoryRouter><FraudModelPanel/></MemoryRouter>);
    expect(await screen.findByRole("link", { name: "ORD-2" })).toHaveAttribute("href", "/orders?search=ORD-2");
    expect(screen.getByText(/audit sample \(unflagged\)/)).toBeInTheDocument();
  });

  it("flags an experimental model as recorded-only", async () => {
    api.fraudModelStatus.mockResolvedValue({ models: [{ ...ready, experimental: true }], store_scoring: {} });
    render(<MemoryRouter><FraudModelPanel/></MemoryRouter>);
    expect(await screen.findByText(/experimental: recorded only, never alerts/)).toBeInTheDocument();
  });

  it("labels a fixture model and never invents metrics when none exist", async () => {
    api.fraudModelStatus.mockResolvedValue({ models: [{ ...ready, is_fixture: true }, { ...untrained }], store_scoring: {} });
    render(<MemoryRouter><FraudModelPanel/></MemoryRouter>);
    expect(await screen.findByText(/test fixture, not real data/)).toBeInTheDocument();
    expect(screen.getAllByText("Precision")).toHaveLength(1);
  });

  it("reports an error instead of a made-up status", async () => {
    api.fraudModelStatus.mockRejectedValue(new Error("boom"));
    render(<MemoryRouter><FraudModelPanel/></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Model status unavailable: boom"));
  });
});
