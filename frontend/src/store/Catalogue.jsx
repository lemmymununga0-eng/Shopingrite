import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SlidersHorizontal, X } from "lucide-react";
import { EmptyState, ErrorState, Pagination, Skeleton } from "../components/ui";
import { api } from "../services/api";
import { CategoryIcon, ProductCard } from "./components";

const PAGE_SIZE = 12;
const SORTS = [["name", "Name A–Z"], ["price_asc", "Price: low to high"], ["price_desc", "Price: high to low"], ["popular", "Most popular"], ["newest", "Newest"]];

export default function Catalogue() {
  const [params, setParams] = useSearchParams();
  const q = Object.fromEntries(params.entries());
  const page = Math.max(1, Number(q.page) || 1);
  const [categories, setCategories] = useState([]);
  const [text, setText] = useState(q.search || "");
  const [minP, setMinP] = useState(q.min_price || "");
  const [maxP, setMaxP] = useState(q.max_price || "");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [priceError, setPriceError] = useState("");
  const [panel, setPanel] = useState(false);

  useEffect(() => { api.categories().then(setCategories).catch(() => {}); }, []);

  const key = params.toString();
  const load = useCallback(async () => {
    setResult(null);
    try {
      setResult(await api.products({ search: q.search, category: q.category, min_price: q.min_price, max_price: q.max_price,
        sort: q.sort || "name", in_stock_only: q.in_stock_only === "true" ? true : undefined,
        on_offer: q.on_offer === "true" ? true : undefined, featured: q.featured === "true" ? true : undefined,
        page, page_size: PAGE_SIZE }));
      setError("");
    } catch (e) { setError(e.message); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => { load(); }, [load]);

  function update(patch) {
    const next = new URLSearchParams(params);
    Object.entries({ page: undefined, ...patch }).forEach(([k, v]) => (v === "" || v == null || v === false) ? next.delete(k) : next.set(k, String(v)));
    setParams(next);
  }
  function applyFilters(e) {
    e.preventDefault();
    if (minP !== "" && maxP !== "" && Number(minP) > Number(maxP)) { setPriceError("The minimum price cannot be above the maximum price."); return; }
    setPriceError("");
    update({ search: text.trim(), min_price: minP, max_price: maxP });
    setPanel(false);
  }
  function clear() { setText(""); setMinP(""); setMaxP(""); setPriceError(""); setParams({}); setPanel(false); }

  const category = categories.find(c => c.slug === q.category);
  // active filters as removable chips (the same state the form edits, so they cannot disagree)
  const chips = [
    q.search && ["search", `Search: ${q.search}`, () => { setText(""); update({ search: "" }); }],
    category && ["category", category.name, () => update({ category: "" })],
    (q.min_price || q.max_price) && ["price", `Price: ${q.min_price || "0"} – ${q.max_price || "any"}`, () => { setMinP(""); setMaxP(""); update({ min_price: "", max_price: "" }); }],
    q.in_stock_only === "true" && ["stock", "In stock only", () => update({ in_stock_only: "" })],
    q.on_offer === "true" && ["offer", "On offer", () => update({ on_offer: "" })],
    q.featured === "true" && ["featured", "Featured", () => update({ featured: "" })],
  ].filter(Boolean);

  return <div>
    <nav aria-label="Breadcrumb" className="breadcrumb">Home / Products{category ? ` / ${category.name}` : ""}</nav>
    <h1>{category ? category.name : q.on_offer ? "Special offers" : q.featured ? "Featured products" : "All products"}</h1>
    <div className="catalogue">
      <form className={`filter-panel${panel ? " open" : ""}`} onSubmit={applyFilters} role="search" aria-label="Filter products">
        <div className="result-bar"><h2>Filters</h2><button type="button" className="icon-btn filter-toggle" onClick={() => setPanel(false)} aria-label="Close filters"><X size={18}/></button></div>
        <div className="filter-group"><h3>Categories</h3>
          <ul className="cat-list">
            <li><button type="button" className={!q.category ? "on" : ""} onClick={() => update({ category: "" })}>All categories</button></li>
            {categories.map(c => <li key={c.id}><button type="button" className={q.category === c.slug ? "on" : ""} aria-pressed={q.category === c.slug} onClick={() => update({ category: c.slug })}>
              <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><CategoryIcon slug={c.slug} size={16}/> {c.name}</span><small>{c.product_count}</small></button></li>)}
          </ul></div>
        <div className="field"><label htmlFor="f-search">Search</label>
          <input id="f-search" type="search" value={text} placeholder="e.g. milk, Zammilk, mealie meal" maxLength={60} onChange={e => setText(e.target.value)}/></div>
        <div className="field"><label htmlFor="f-cat">Category</label>
          <select id="f-cat" value={q.category || ""} onChange={e => update({ category: e.target.value })}>
            <option value="">All categories</option>{categories.map(c => <option key={c.id} value={c.slug}>{c.name}</option>)}</select></div>
        <div className="price-row">
          <div className="field"><label htmlFor="f-min">Min price</label><input id="f-min" type="number" min="0" step="0.01" value={minP} onChange={e => setMinP(e.target.value)}/></div>
          <div className="field"><label htmlFor="f-max">Max price</label><input id="f-max" type="number" min="0" step="0.01" value={maxP} onChange={e => setMaxP(e.target.value)}/></div></div>
        <label className="check"><input type="checkbox" checked={q.in_stock_only === "true"} onChange={e => update({ in_stock_only: e.target.checked })}/> In stock only</label>
        <label className="check"><input type="checkbox" checked={q.on_offer === "true"} onChange={e => update({ on_offer: e.target.checked })}/> On offer</label>
        <div className="filter-actions"><button className="shop-btn" type="submit">Apply</button>
          <button className="shop-btn secondary" type="button" onClick={clear}>Clear</button></div>
        {priceError && <p className="field-error" role="alert">{priceError}</p>}
      </form>

      <section aria-label="Results">
        <div className="result-bar">
          <p className="muted-text" role="status" aria-live="polite">{result ? `${result.total} product${result.total === 1 ? "" : "s"} found` : "Loading…"}</p>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button type="button" className="shop-btn secondary filter-toggle" onClick={() => setPanel(true)}><SlidersHorizontal size={16} aria-hidden="true"/> Filters</button>
            <div className="field" style={{ margin: 0, display: "flex", gap: 8, alignItems: "center" }}><label htmlFor="f-sort">Sort by</label>
              <select id="f-sort" value={q.sort || "name"} onChange={e => update({ sort: e.target.value })}>{SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
          </div>
        </div>
        {chips.length > 0 && <div className="chips" aria-label="Active filters">{chips.map(([k, label, remove]) =>
          <span key={k} className="chip">{label}<button type="button" onClick={remove} aria-label={`Remove filter: ${label}`}><X size={12} aria-hidden="true"/></button></span>)}</div>}
        {error ? <ErrorState error={error} onRetry={load}/> : !result ? <Skeleton className="skeleton-chart" count={2}/> :
          result.items.length === 0 ? <EmptyState><p>No products match your filters.</p><button type="button" className="shop-btn" onClick={clear}>Clear filters</button></EmptyState> : <>
            <div className="product-grid">{result.items.map(p => <ProductCard key={p.id} product={p}/>)}</div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={result.total} onChange={p => update({ page: p })}/></>}
      </section>
    </div>
  </div>;
}
