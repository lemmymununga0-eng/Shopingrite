import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ value: {} }));
vi.mock("../context/AuthContext", () => ({ useAuth: () => auth.value }));
vi.mock("../services/api", () => ({ api: { alerts: vi.fn() } }));

import { api } from "../services/api";
import App, { NotFound, Protected } from "../App";
import Login from "../pages/Login";
import Register from "../pages/Register";
import Sidebar from "../components/Sidebar";
import Topbar from "../components/Topbar";

const base = { user: null, loading: false, configured: true, role: "customer", login: vi.fn(), register: vi.fn(), logout: vi.fn() };
beforeEach(() => {
  vi.clearAllMocks();
  auth.value = { ...base, login: vi.fn(), register: vi.fn(), logout: vi.fn() };
  api.alerts.mockResolvedValue({ items: [], total: 0 });
});
const at = (path, ui) => render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);

describe("protected routes", () => {
  const routes = <Routes><Route path="/login" element={<div>LOGIN PAGE</div>}/><Route path="/" element={<Protected><div>SECRET</div></Protected>}/></Routes>;
  it("redirects signed-out users to login", () => { at("/", routes); expect(screen.getByText("LOGIN PAGE")).toBeInTheDocument(); expect(screen.queryByText("SECRET")).toBeNull(); });
  it("shows a loading state while the session is restored", () => {
    auth.value = { ...base, loading: true }; at("/", routes);
    expect(screen.getByRole("status")).toHaveTextContent(/checking your session/i); expect(screen.queryByText("SECRET")).toBeNull();
  });
  it("renders content for a signed-in user", () => { auth.value = { ...base, user: { id: "1" } }; at("/", routes); expect(screen.getByText("SECRET")).toBeInTheDocument(); });
  it("sends a signed-out visitor of a deep link to login", () => {
    at("/history", <App/>);
    expect(screen.getByRole("heading", { name: "Login" })).toBeInTheDocument();
  });
  it("shows a 404 page for unknown routes inside the app", () => {
    auth.value = { ...base, user: { id: "1", email: "a@b.co" } };
    at("/nope/nothing", <App/>);
    expect(screen.getByRole("heading", { name: /404/ })).toBeInTheDocument();
  });
  it("NotFound links back to the dashboard", () => {
    at("/x", <NotFound/>);
    expect(screen.getByRole("link", { name: /dashboard/i })).toHaveAttribute("href", "/dashboard");
  });
});

describe("login", () => {
  it("submits trimmed credentials", async () => {
    at("/login", <Login/>);
    await userEvent.type(screen.getByLabelText("Email Address"), " a@b.co ");
    await userEvent.type(screen.getByLabelText("Password"), "secret123");
    await userEvent.click(screen.getByRole("button", { name: "Login" }));
    expect(auth.value.login).toHaveBeenCalledWith("a@b.co", "secret123");
  });
  it("validates empty fields and email format without calling the API", async () => {
    at("/login", <Login/>);
    await userEvent.click(screen.getByRole("button", { name: "Login" }));
    expect(await screen.findByText("Enter your email address")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Email Address"), "not-an-email");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Login" }));
    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
    expect(auth.value.login).not.toHaveBeenCalled();
  });
  it("shows and hides the password", async () => {
    at("/login", <Login/>);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: /show password/i }));
    expect(input).toHaveAttribute("type", "text");
    await userEvent.click(screen.getByRole("button", { name: /hide password/i }));
    expect(input).toHaveAttribute("type", "password");
  });
  it("shows the failure message from the auth provider", async () => {
    auth.value.login.mockRejectedValue(new Error("Please confirm your email first"));
    at("/login", <Login/>);
    await userEvent.type(screen.getByLabelText("Email Address"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "wrongpass");
    await userEvent.click(screen.getByRole("button", { name: "Login" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/confirm your email/i);
  });
  it("returns to the page the visitor originally asked for", async () => {
    auth.value.login.mockImplementation(async () => { auth.value = { ...auth.value, user: { id: "1" } }; });
    render(<MemoryRouter initialEntries={[{ pathname: "/login", state: { from: { pathname: "/history" } } }]}>
      <Routes><Route path="/login" element={<Login/>}/><Route path="/history" element={<div>HISTORY PAGE</div>}/></Routes></MemoryRouter>);
    await userEvent.type(screen.getByLabelText("Email Address"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "secret123");
    await userEvent.click(screen.getByRole("button", { name: "Login" }));
    expect(await screen.findByText("HISTORY PAGE")).toBeInTheDocument();
  });
  it("shows setup guidance when Supabase is not configured", () => {
    auth.value = { ...base, configured: false }; at("/login", <Login/>);
    expect(screen.getByText(/setup required/i)).toBeInTheDocument();
  });
  it("links to registration and password recovery", () => {
    at("/login", <Login/>);
    expect(screen.getByRole("link", { name: /forgot your password/i })).toHaveAttribute("href", "/forgot-password");
    expect(screen.getByRole("link", { name: /register here/i })).toHaveAttribute("href", "/register");
  });
});

describe("registration", () => {
  async function fill({ password = "longenough1", confirm = password, agree = true } = {}) {
    await userEvent.type(screen.getByLabelText("Full Name"), "Pat Doe");
    await userEvent.type(screen.getByLabelText("Email Address"), "p@d.co");
    await userEvent.type(screen.getByLabelText("Password"), password);
    await userEvent.type(screen.getByLabelText("Confirm Password"), confirm);
    if (agree) await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
  }
  it("rejects a password that misses the requirements", async () => {
    at("/register", <Register/>); await fill({ password: "short" });
    expect(await screen.findByText(/does not meet the requirements/i)).toBeInTheDocument();
    expect(auth.value.register).not.toHaveBeenCalled();
  });
  it("updates the visible password requirements as you type", async () => {
    at("/register", <Register/>);
    await userEvent.type(screen.getByLabelText("Password"), "abcdefg1");
    const list = screen.getByRole("list", { name: /password requirements/i });
    expect(list).toHaveTextContent("✓ At least 8 characters"); expect(list).toHaveTextContent("✓ A number");
  });
  it("rejects mismatched passwords", async () => {
    at("/register", <Register/>); await fill({ password: "longenough1", confirm: "different12" });
    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
    expect(auth.value.register).not.toHaveBeenCalled();
  });
  it("requires the educational-demo acknowledgement", async () => {
    at("/register", <Register/>); await fill({ agree: false });
    expect(await screen.findByText(/please acknowledge/i)).toBeInTheDocument();
    expect(auth.value.register).not.toHaveBeenCalled();
  });
  it("registers and shows the email-confirmation message", async () => {
    auth.value.register.mockResolvedValue({ session: null });
    at("/register", <Register/>); await fill();
    await waitFor(() => expect(auth.value.register).toHaveBeenCalledWith("p@d.co", "longenough1", "Pat Doe"));
    expect(await screen.findByText(/check your email/i)).toBeInTheDocument();
  });
  it("shows provider errors such as rate limits", async () => {
    auth.value.register.mockRejectedValue(new Error("email rate limit exceeded"));
    at("/register", <Register/>); await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent(/rate limit/i);
  });
});

describe("navigation shell", () => {
  const signedIn = { ...base, user: { id: "1", email: "x@y.z", user_metadata: { full_name: "Xavier Doe" } }, role: "analyst" };
  it("sidebar lists every main screen, the signed-in user and a working Logout", async () => {
    auth.value = signedIn; at("/dashboard", <Sidebar onNavigate={() => {}}/>);
    for (const [name, href] of [["Dashboard", "/dashboard"], ["Payment Card", "/payment-card"], ["New Payment", "/payment"], ["Fraud Alerts", "/alerts"],
      ["Transaction History", "/history"], ["Profile", "/profile"], ["Settings", "/settings"], ["About", "/about"]]) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href", href);
    }
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveClass("active");
    expect(screen.getByText("Xavier Doe")).toBeInTheDocument(); expect(screen.getByText("analyst")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /logout/i }));
    expect(auth.value.logout).toHaveBeenCalled();
  });
  it("shows an inline error if sign-out fails", async () => {
    auth.value = { ...signedIn, logout: vi.fn().mockRejectedValue(new Error("network")) }; at("/dashboard", <Sidebar onNavigate={() => {}}/>);
    await userEvent.click(screen.getByRole("button", { name: /logout/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("network");
  });
  it("topbar shows the page title and the real count of alerts awaiting review", async () => {
    auth.value = signedIn;
    api.alerts.mockResolvedValue({ total: 3, items: [{ id: "a", transaction_reference: "TX-9", risk: "High", amount: 100 }] });
    at("/history", <Topbar onMenuClick={() => {}}/>);
    expect(screen.getByText("Transaction History")).toBeInTheDocument();
    const bell = await screen.findByRole("button", { name: /3 unreviewed alerts/i });
    await userEvent.click(bell);
    expect(await screen.findByText("#TX-9")).toBeInTheDocument();
  });
  it("topbar shows no fake badge when there are no alerts", async () => {
    auth.value = signedIn; at("/dashboard", <Topbar onMenuClick={() => {}}/>);
    await waitFor(() => expect(api.alerts).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /^notifications$/i })).toBeInTheDocument();
  });
  it("topbar hides notifications when the preference is off", async () => {
    localStorage.setItem("fg_prefs", JSON.stringify({ alertBadge: false }));
    auth.value = signedIn; at("/dashboard", <Topbar onMenuClick={() => {}}/>);
    expect(screen.queryByRole("button", { name: /notifications/i })).toBeNull();
    expect(api.alerts).not.toHaveBeenCalled();
  });
  it("topbar search goes to history with the reference", async () => {
    auth.value = signedIn;
    render(<MemoryRouter initialEntries={["/dashboard"]}><Topbar onMenuClick={() => {}}/><Routes><Route path="/history" element={<div>HISTORY</div>}/><Route path="*" element={null}/></Routes></MemoryRouter>);
    await userEvent.type(screen.getByLabelText(/search transactions by reference/i), "TX-77{Enter}");
    expect(await screen.findByText("HISTORY")).toBeInTheDocument();
  });
});
