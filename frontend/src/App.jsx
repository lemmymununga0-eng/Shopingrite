import { Suspense, lazy } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./context/AuthContext";
import Layout from "./components/Layout";
import StoreLayout from "./layouts/StoreLayout";
import Login from "./pages/Login";
import Register from "./pages/Register";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import PaymentCard from "./pages/PaymentCard";
import Transaction from "./pages/Transaction";
import ModelDemo from "./pages/ModelDemo";
import Alerts from "./pages/Alerts";
import History from "./pages/History";
import TransactionDetail from "./pages/TransactionDetail";
import Profile from "./pages/Profile";
import Settings from "./pages/Settings";
import About from "./pages/About";
import ScamChecker from "./components/ScamChecker";

// Heavier or role-specific areas load only when visited.
const Dashboard = lazy(() => import("./pages/Dashboard"));
const StoreHome = lazy(() => import("./store/StoreHome"));
const Catalogue = lazy(() => import("./store/Catalogue"));
const ProductDetail = lazy(() => import("./store/ProductDetail"));
const Cart = lazy(() => import("./store/Cart"));
const Checkout = lazy(() => import("./store/Checkout"));
const Orders = lazy(() => import("./store/Orders"));
const OrderView = lazy(() => import("./store/Orders").then(m => ({ default: m.OrderView })));
const Investigations = lazy(() => import("./pages/Investigations"));
const ScamWatch = lazy(() => import("./pages/ScamWatch"));
const SecurityMonitor = lazy(() => import("./pages/SecurityMonitor"));
const InventoryMonitor = lazy(() => import("./pages/InventoryMonitor"));
const Reports = lazy(() => import("./pages/Reports"));
const Users = lazy(() => import("./pages/AdminPages").then(m => ({ default: m.Users })));
const AuditTrail = lazy(() => import("./pages/AdminPages").then(m => ({ default: m.AuditTrail })));
const Integrations = lazy(() => import("./pages/AdminPages").then(m => ({ default: m.Integrations })));

const wait = <div className="loading" role="status">Loading…</div>;
const lazyEl = el => <Suspense fallback={wait}>{el}</Suspense>;

/** Frontend gate for convenience only. The API verifies the token on every request. */
export function Protected({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="loading" role="status">Checking your session…</div>;
  return user ? children : <Navigate to="/login" replace state={{ from: location }} />;
}

/** The staff console is for staff roles. Customers are sent to the store. (The API enforces this too.) */
export function StaffOnly({ children }) {
  const { user, loading, role } = useAuth();
  const location = useLocation();
  if (loading) return <div className="loading" role="status">Checking your session…</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  if (role === "customer") return <Navigate to="/shop" replace />;
  return children;
}

export function NotFound() {
  return <div className="not-found"><div>
    <h1>404 — Page not found</h1><p className="muted-text">That page does not exist.</p>
    <Link className="btn btn-primary" to="/dashboard">Go to Dashboard</Link></div></div>;
}

function CheckWebsite() {
  return <div className="scam-page"><h1>Check a website</h1>
    <p className="muted-text">Got a suspicious link or message? Paste the web address. We analyse the text of the address only and never open the site. You can also report it for review.</p>
    <ScamChecker/></div>;
}

export default function App() {
  return <Routes>
    <Route path="/login" element={<Login/>}/>
    <Route path="/register" element={<Register/>}/>
    <Route path="/forgot-password" element={<ForgotPassword/>}/>
    <Route path="/reset-password" element={<ResetPassword/>}/>
    <Route path="/" element={<Navigate to="/shop" replace/>}/>

    {/* Customer store: browsing is public; cart, checkout and orders need sign-in. */}
    <Route path="/shop" element={<StoreLayout/>}>
      <Route index element={lazyEl(<StoreHome/>)}/>
      <Route path="products" element={lazyEl(<Catalogue/>)}/>
      <Route path="products/:id" element={lazyEl(<ProductDetail/>)}/>
      <Route path="cart" element={<Protected>{lazyEl(<Cart/>)}</Protected>}/>
      <Route path="checkout" element={<Protected>{lazyEl(<Checkout/>)}</Protected>}/>
      <Route path="order-confirmation/:id" element={<Protected>{lazyEl(<OrderView confirmation/>)}</Protected>}/>
      <Route path="orders" element={<Protected>{lazyEl(<Orders/>)}</Protected>}/>
      <Route path="orders/:id" element={<Protected>{lazyEl(<OrderView/>)}</Protected>}/>
      <Route path="check-website" element={<Protected><CheckWebsite/></Protected>}/>
      <Route path="*" element={<div className="not-found"><div><h1>Page not found</h1><Link className="shop-btn" to="/shop">Back to the store</Link></div></div>}/>
    </Route>

    {/* Staff console (separate shell and navigation). */}
    <Route element={<StaffOnly><Layout/></StaffOnly>}>
      <Route path="/dashboard" element={lazyEl(<Dashboard/>)}/>
      <Route path="/investigations" element={lazyEl(<Investigations/>)}/>
      <Route path="/scamwatch" element={lazyEl(<ScamWatch/>)}/>
      <Route path="/security" element={lazyEl(<SecurityMonitor/>)}/>
      <Route path="/inventory" element={lazyEl(<InventoryMonitor/>)}/>
      <Route path="/reports" element={lazyEl(<Reports/>)}/>
      <Route path="/users" element={lazyEl(<Users/>)}/>
      <Route path="/audit" element={lazyEl(<AuditTrail/>)}/>
      <Route path="/integrations" element={lazyEl(<Integrations/>)}/>
      <Route path="/payment-card" element={<PaymentCard/>}/>
      <Route path="/payment" element={<Transaction/>}/>
      <Route path="/model-demo" element={<ModelDemo/>}/>
      <Route path="/alerts" element={<Alerts/>}/>
      <Route path="/history" element={<History/>}/>
      <Route path="/transactions/:id" element={<TransactionDetail/>}/>
      <Route path="/profile" element={<Profile/>}/>
      <Route path="/settings" element={<Settings/>}/>
      <Route path="/about" element={<About/>}/>
      <Route path="/transaction" element={<Navigate to="/payment" replace/>}/>
      <Route path="*" element={<NotFound/>}/>
    </Route>
  </Routes>;
}
