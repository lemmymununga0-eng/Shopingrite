import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Topbar from "./Topbar";
import Sidebar from "./Sidebar";

export default function Layout() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => { setOpen(false); }, [pathname]);
  return <>
    <a href="#main" className="skip-link">Skip to content</a>
    <Topbar onMenuClick={() => setOpen(!open)} />
    <div className="app-shell">
      <div className={`mobile-backdrop ${open ? "visible" : ""}`} onClick={() => setOpen(false)} />
      <aside className={`sidebar ${open ? "open" : ""}`}><Sidebar onNavigate={() => setOpen(false)} /></aside>
      <main id="main" className="main-content"><div className="main-inner"><Outlet /></div></main>
    </div>
  </>;
}
