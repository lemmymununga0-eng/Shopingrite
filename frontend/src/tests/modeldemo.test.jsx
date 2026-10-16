import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../services/api", () => ({ api: { pcaInfo: vi.fn(), pcaPredict: vi.fn() } }));
import { api } from "../services/api";
import ModelDemo, { PCA_FEATURES, parseRow } from "../pages/ModelDemo";

const INFO = { trained: true, version: "pca-test", n_rows: 1000, data_source: "fixture",
  metrics: { precision: 0.9, recall: 0.8, f1: 0.85, pr_auc: 0.8, support_fraud: 12 } };
const row = n => Array.from({ length: 30 }, (_, i) => (i === 0 ? n : 0.5)).join(",");
beforeEach(() => { vi.clearAllMocks(); api.pcaInfo.mockResolvedValue(INFO); });
const view = () => render(<MemoryRouter><ModelDemo/></MemoryRouter>);

describe("parseRow", () => {
  it("accepts 30 values and a trailing Class value", () => {
    expect(Object.keys(parseRow(row(1)).values)).toEqual(PCA_FEATURES);
    expect(parseRow(row(1) + ",0").values.Time).toBe(1);
  });
  it.each([["1,2,3"], [row(1).replace("0.5", "abc")], [""]])("rejects %j", t => { expect(parseRow(t).error).toBeTruthy(); });
});

describe("PCA model demo page", () => {
  it("states it is separate from the payment form", async () => {
    view();
    expect(await screen.findByText(/real model loaded/i)).toBeInTheDocument();
    expect(screen.getByText(/cannot be calculated from payment details/i)).toBeInTheDocument();
  });
  it("shows an unavailable message when the model is not trained and offers no submit button", async () => {
    api.pcaInfo.mockResolvedValue({ trained: false, message: "PCA demo model not trained." });
    view();
    expect(await screen.findByText(/not available/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /analyze/i })).toBeNull();
  });
  it("fills the fields from a pasted row and submits exactly the 30 named features", async () => {
    api.pcaPredict.mockResolvedValue({ prediction: 1, fraud_probability: 0.93, risk_level: "High", threshold: 0.5, model_version: "pca-test", note: "Not saved." });
    view();
    await screen.findByText(/real model loaded/i);
    await userEvent.click(screen.getByLabelText("Paste dataset row"));
    await userEvent.paste(row(7));
    await userEvent.click(screen.getByRole("button", { name: /fill fields/i }));
    await userEvent.click(screen.getByRole("button", { name: /analyze with pca/i }));
    await waitFor(() => expect(api.pcaPredict).toHaveBeenCalled());
    const sent = api.pcaPredict.mock.calls[0][0];
    expect(Object.keys(sent)).toEqual(PCA_FEATURES);
    expect(sent.Time).toBe(7);
    expect(await screen.findByText("Predicted fraud")).toBeInTheDocument();
    expect(screen.getByText("93.0%")).toBeInTheDocument();
  });
  it("shows the API error and no score on failure", async () => {
    api.pcaPredict.mockRejectedValue(new Error("PCA demo model unavailable"));
    view();
    await screen.findByText(/real model loaded/i);
    await userEvent.click(screen.getByRole("button", { name: /analyze with pca/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable/i);
    expect(screen.queryByText(/model fraud probability/i)).toBeNull();
  });
  it("reports a bad pasted row without calling the API", async () => {
    view();
    await screen.findByText(/real model loaded/i);
    await userEvent.click(screen.getByLabelText("Paste dataset row"));
    await userEvent.paste("1,2,3");
    await userEvent.click(screen.getByRole("button", { name: /fill fields/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/expected 30 values/i);
    expect(api.pcaPredict).not.toHaveBeenCalled();
  });
});
