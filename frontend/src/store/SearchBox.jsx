import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { api } from "../services/api";
import { moneyC } from "../services/format";

/** Header search with live suggestions (top matches with photo and price). Submitting always goes to the full results. */
export default function SearchBox() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const timer = useRef(null);

  useEffect(() => {
    const close = e => box.current && !box.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function onChange(e) {
    const v = e.target.value;
    setQ(v);
    clearTimeout(timer.current);
    if (v.trim().length < 2) { setItems([]); setOpen(false); return; }
    timer.current = setTimeout(async () => {
      try {
        const r = await api.products({ search: v.trim(), page_size: 5 });
        const list = Array.isArray(r?.items) ? r.items : [];
        setItems(list); setOpen(list.length > 0);
      } catch { setItems([]); setOpen(false); }
    }, 250);
  }
  useEffect(() => () => clearTimeout(timer.current), []);

  function submit(e) {
    e.preventDefault(); setOpen(false);
    navigate(`/shop/products${q.trim() ? `?search=${encodeURIComponent(q.trim())}` : ""}`);
  }
  function keys(e) {
    if (e.key === "Escape") setOpen(false);
    if (e.key === "ArrowDown" && open) { e.preventDefault(); box.current?.querySelector(".suggest a")?.focus(); }
  }
  function move(e) {
    const links = [...box.current.querySelectorAll(".suggest a")];
    const i = links.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); links[Math.min(i + 1, links.length - 1)]?.focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); if (i <= 0) box.current.querySelector("input").focus(); else links[i - 1].focus(); }
    if (e.key === "Escape") { setOpen(false); box.current.querySelector("input").focus(); }
  }

  return <div className="store-search" ref={box}>
    <form onSubmit={submit} role="search" aria-label="Search products">
      <label htmlFor="store-q" className="sr-only">Search products</label>
      <input id="store-q" type="search" placeholder="Search for mealie meal, milk, kapenta…" value={q} maxLength={60} autoComplete="off"
        aria-autocomplete="list" aria-controls={open ? "store-suggest" : undefined} onChange={onChange} onKeyDown={keys} onFocus={() => items.length && setOpen(true)}/>
      <button type="submit" aria-label="Search"><Search size={20} aria-hidden="true"/></button>
    </form>
    {open && <ul className="suggest" id="store-suggest" aria-label="Suggestions" onKeyDown={move}>
      {items.map(p => <li key={p.id}><Link to={`/shop/products/${p.id}`} onClick={() => { setOpen(false); setQ(""); }}>
        <img src={p.image_ref} alt="" width="44" height="44" loading="lazy"/>
        <span><strong>{p.name}</strong><small>{p.pack_size || p.unit} · {moneyC(p.effective_price_cents, p.currency)}</small></span></Link></li>)}
      <li><Link to={`/shop/products?search=${encodeURIComponent(q.trim())}`} onClick={() => setOpen(false)}><span><strong>See all results for “{q.trim()}”</strong></span></Link></li>
    </ul>}
  </div>;
}
