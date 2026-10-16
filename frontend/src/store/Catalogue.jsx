import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { EmptyState, ErrorState, Pagination, Skeleton } from "../components/ui";
import { api } from "../services/api";
import { ProductCard } from "./components";

const PAGE_SIZE = 12;
const SORTS = [["name", "Name A–Z"], ["price_asc", "Price: low to high"], ["price_desc", "Price: high to low"], ["newest", "Newest"]];

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
  }
  function clear() { setText(""); setMinP(""); setMaxP(""); setPriceError(""); setParams({}); }

  const category = categories.find(c => c.slug === q.category);
  return <div>
    <h1>{category ? category.name : q.on_offer ? "Special offers" : q.featured ? "Featured products" : "All products"}</h1>
    <form className="filters" onSubmit={applyFilters} role="search" aria-label="Filter products">
      <div className="field"><label htmlFor="f-search">Search</label>
        <input id="f-search" type="search" value={text} placeholder="e.g. milk" maxLength={60} onChange={e => setText(e.target.value)}/></div>
      <div className="field"><label htmlFor="f-cat">Category</label>
        <select id="f-cat" value={q.category || ""} onChange={e => update({ category: e.target.value })}>
          <option value="">All categories</option>{categories.map(c => <option key={c.id} value={c.slug}>{c.name}</option>)}</select></div>
      <div className="field"><label htmlFor="f-min">Min price</label>
        <input id="f-min" type="number" min="0" step="0.01" value={minP} onChange={e => setMinP(e.target.value)}/></div>
      <div className="field"><label htmlFor="f-max">Max price</label>
        <input id="f-max" type="number" min="0" step="0.01" value={maxP} onChange={e => setMaxP(e.target.value)}/></div>
      <div className="field"><label htmlFor="f-sort">Sort by</label>
        <select id="f-sort" value={q.sort || "name"} onChange={e => update({ sort: e.target.value })}>
          {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
      <label className="check"><input type="checkbox" checked={q.in_stock_only === "true"} onChange={e => update({ in_stock_only: e.target.checked })}/> In stock only</label>
      <div className="filter-actions"><button className="shop-btn" type="submit">Apply</button>
        <button className="shop-btn secondary" type="button" onClick={clear}>Clear</button></div>
      {priceError && <p className="field-error" role="alert">{priceError}</p>}
    </form>
    {error ? <ErrorState error={error} onRetry={load}/> : !result ? <Skeleton className="skeleton-chart" count={2}/> :
      result.items.length === 0 ? <EmptyState><p>No products match your filters.</p><button type="button" className="shop-btn" onClick={clear}>Clear filters</button></EmptyState> : <>
        <p className="muted-text" role="status" aria-live="polite">{result.total} product{result.total === 1 ? "" : "s"} found</p>
        <div className="product-grid">{result.items.map(p => <ProductCard key={p.id} product={p}/>)}</div>
        <Pagination page={page} pageSize={PAGE_SIZE} total={result.total} onChange={p => update({ page: p })}/></>}
  </div>;
}
