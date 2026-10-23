import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = { value: { user: null, loading: false, isStaff: false } };
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth.value }));
vi.mock("../services/api", () => {
  const f = () => vi.fn();
  return { ApiError: class extends Error {}, setUnauthorizedHandler: () => {}, api: { storeInfo: f(), cart: f(), categories: f(), products: f(), product: f() } };
});

import { api } from "../services/api";
import StoreLayout from "../layouts/StoreLayout";
import Info from "../store/Info";

const live = { name: "Mwila Foods", legal_name: "Mwila Foods Ltd", currency: "ZMW", is_demo: false, delivery_cities: ["Lusaka", "Ndola"], delivery_fee_cents: 3500,
  free_delivery_over_cents: 60000, contact_email: "shop@mwila.example", contact_phone: "+260 97 1234567", contact_address: "Plot 5, Cairo Road, Lusaka", disclaimer: "" };
const demo = { ...live, name: "FreshCart Demo Store", is_demo: true, disclaimer: "Independent demonstration store with sample products." };

const page = (topic) => render(<MemoryRouter initialEntries={[`/shop/info/${topic}`]}>
  <Routes><Route path="/shop" element={<StoreLayout/>}><Route path="info/:topic" element={<Info/>}/></Route></Routes></MemoryRouter>);

beforeEach(() => { vi.clearAllMocks(); window.scrollTo = vi.fn(); api.cart.mockResolvedValue({ items: [], item_count: 0 }); });

describe("live store (STORE_IS_DEMO=false)", () => {
  beforeEach(() => api.storeInfo.mockResolvedValue(live));

  it("shows no demonstration ribbon or disclaimer anywhere in the layout", async () => {
    page("contact");
    expect(await screen.findByText("Mwila Foods Ltd", { selector: "p" })).toBeInTheDocument();
    expect(screen.queryByText(/demonstration/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/not affiliated/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /image credits/i })).not.toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toHaveTextContent(/Mwila Foods Ltd/);
  });
  it("contact page shows the store's own details", async () => {
    page("contact");
    expect(await screen.findByRole("link", { name: "shop@mwila.example" })).toHaveAttribute("href", "mailto:shop@mwila.example");
    expect(screen.getByText(/\+260 97 1234567/)).toBeInTheDocument();
    expect(screen.getByText(/Plot 5, Cairo Road/)).toBeInTheDocument();
  });
  it("delivery page lists the real cities, fee and free-delivery limit", async () => {
    page("delivery");
    expect(await screen.findByText(/We deliver in: Lusaka, Ndola/)).toBeInTheDocument();
    expect(screen.getByText(/free for orders over/i)).toBeInTheDocument();
    expect(screen.queryByText(/no goods are shipped/i)).not.toBeInTheDocument();
  });
  it("privacy and terms say money is handled by the payment provider and refunds are real", async () => {
    page("privacy");
    expect(await screen.findByText(/never see or store card numbers/i)).toBeInTheDocument();
    page("terms");
    expect((await screen.findAllByText(/refund/i)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/no money is taken/i)).not.toBeInTheDocument();
  });
  it("says so honestly when contact details were never configured", async () => {
    api.storeInfo.mockResolvedValue({ ...live, contact_email: "", contact_phone: "", contact_address: "" });
    page("contact");
    expect(await screen.findByText(/have not been set/i)).toBeInTheDocument();
  });
  it("an unknown topic is a 404 page", async () => {
    page("nonsense");
    expect(await screen.findByRole("heading", { name: /page not found/i })).toBeInTheDocument();
  });
});

describe("demonstration store (STORE_IS_DEMO=true)", () => {
  beforeEach(() => api.storeInfo.mockResolvedValue(demo));
  it("still labels itself clearly", async () => {
    page("terms");
    expect((await screen.findAllByText(/independent demonstration/i)).length).toBeGreaterThan(1);    // ribbon + footer + terms
    expect(screen.getByRole("note")).toHaveTextContent(/demonstration store/i);
    expect(screen.getByRole("link", { name: /image credits/i })).toBeInTheDocument();
  });
});
