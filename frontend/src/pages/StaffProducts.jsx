import { useCallback, useEffect, useState } from "react";
import { Field } from "../components/forms";
import { EmptyState, ErrorNotice, ErrorState, Modal, PageHeader, Pagination, Skeleton } from "../components/ui";
import { api } from "../services/api";
import { moneyC } from "../services/format";

/** "125", "125.5", "125.50" -> cents. Anything else is rejected, so a typo never becomes a price. */
export function toCents(text) {
  const t = String(text).trim().replace(/^K\s*/i, "").replace(/,/g, "");
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(t)) return null;
  return Math.round(Number(t) * 100);
}
const fromCents = c => (c == null ? "" : (c / 100).toFixed(2));

function ProductForm({ product, categories, onClose, onSaved }) {
  const editing = !!product;
  const [f, setF] = useState({ sku: "", name: "", description: "", category_slug: categories[0]?.slug || "", price: "", offer: "", brand: "", pack_size: "",
    unit: "each", image_ref: "", stock: "0", is_featured: false, is_active: true,
    ...(product ? { sku: product.sku, name: product.name, description: product.description, category_slug: product.category_slug, price: fromCents(product.price_cents),
      offer: fromCents(product.offer_price_cents), brand: product.brand, pack_size: product.pack_size, unit: product.unit, image_ref: product.image_ref,
      is_featured: product.is_featured, is_active: product.is_active } : {}) });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = k => e => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  async function save(e) {
    e.preventDefault(); setError("");
    const price = toCents(f.price), offer = f.offer.trim() ? toCents(f.offer) : null;
    if (price === null) { setError("Enter the price as a number such as 125 or 125.50."); return; }
    if (f.offer.trim() && offer === null) { setError("Enter the offer price as a number such as 99.50, or leave it empty."); return; }
    if (f.name.trim().length < 2) { setError("Enter a product name."); return; }
    const body = { name: f.name.trim(), description: f.description.trim(), category_slug: f.category_slug, price_cents: price, unit: f.unit.trim() || "each",
      brand: f.brand.trim(), pack_size: f.pack_size.trim(), image_ref: f.image_ref.trim(), is_featured: f.is_featured, is_active: f.is_active };
    setBusy(true);
    try {
      if (editing) { await api.updateProduct(product.id, offer === null ? { ...body, clear_offer: true } : { ...body, offer_price_cents: offer }); }
      else {
        const stock = Number(f.stock);
        if (!Number.isInteger(stock) || stock < 0) { setError("Starting stock must be a whole number, zero or more."); setBusy(false); return; }
        await api.createProduct({ ...body, sku: f.sku.trim(), initial_quantity: stock, ...(offer === null ? {} : { offer_price_cents: offer }) });
      }
      onSaved(); onClose();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <Modal title={editing ? `Edit ${product.name}` : "New product"} onClose={onClose} wide><form onSubmit={save} noValidate>
    <ErrorNotice error={error}/>
    {!editing && <Field label="SKU" hint="Letters, digits and dashes, for example ZM-MEAL-25KG">{a => <input {...a} maxLength={40} value={f.sku} onChange={set("sku")}/>}</Field>}
    <Field label="Name">{a => <input {...a} maxLength={160} value={f.name} onChange={set("name")}/>}</Field>
    <Field label="Category">{a => <select {...a} value={f.category_slug} onChange={set("category_slug")}>{categories.map(c => <option key={c.slug} value={c.slug}>{c.name}</option>)}</select>}</Field>
    <Field label="Price (ZMW)">{a => <input {...a} inputMode="decimal" value={f.price} onChange={set("price")}/>}</Field>
    <Field label="Offer price (ZMW, optional)" hint="Must be lower than the price. Empty = no offer.">{a => <input {...a} inputMode="decimal" value={f.offer} onChange={set("offer")}/>}</Field>
    <Field label="Brand">{a => <input {...a} maxLength={80} value={f.brand} onChange={set("brand")}/>}</Field>
    <Field label="Pack size">{a => <input {...a} maxLength={40} value={f.pack_size} onChange={set("pack_size")} placeholder="e.g. 25 kg"/>}</Field>
    <Field label="Unit">{a => <input {...a} maxLength={30} value={f.unit} onChange={set("unit")}/>}</Field>
    <Field label="Image address" hint="A path such as /products/meal.jpg or an https:// link to an image you have the right to use.">{a => <input {...a} maxLength={200} value={f.image_ref} onChange={set("image_ref")}/>}</Field>
    <Field label="Description">{a => <textarea {...a} rows={3} maxLength={2000} value={f.description} onChange={set("description")}/>}</Field>
    {!editing && <Field label="Starting stock">{a => <input {...a} type="number" min="0" value={f.stock} onChange={set("stock")}/>}</Field>}
    <label className="check"><input type="checkbox" checked={f.is_featured} onChange={set("is_featured")}/> Featured on the home page</label>
    <label className="check"><input type="checkbox" checked={f.is_active} onChange={set("is_active")}/> Visible in the store</label>
    <div className="dialog-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save product"}</button></div>
  </form></Modal>;
}

export default function StaffProducts() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [categories, setCategories] = useState([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState(null);       // null | "new" | product
  const load = useCallback(async () => { try { setData(await api.adminProducts({ search, page, page_size: 20 })); setError(""); } catch (e) { setError(e.message); } }, [search, page]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { api.categories().then(setCategories).catch(() => {}); }, []);

  return <div>
    <PageHeader title="Products" subtitle="Add products, change prices and withdraw items from sale. Every price change is kept in the price history and the audit trail."
      actions={<button type="button" className="btn btn-primary" disabled={!categories.length} onClick={() => setForm("new")}>New product</button>}/>
    <div className="panel">
      <div className="toolbar" role="search" aria-label="Filter products">
        <Field label="Search name, SKU or brand">{a => <input {...a} type="search" maxLength={60} value={search} onChange={e => { setPage(1); setSearch(e.target.value); }}/>}</Field></div>
      {error ? <ErrorState error={error} onRetry={load}/> : !data ? <Skeleton count={5}/> : data.items.length === 0 ? <EmptyState><p>No products match.</p></EmptyState> : <>
        <div className="table-wrap table-cards"><table><thead><tr><th scope="col">Product</th><th scope="col">SKU</th><th scope="col">Category</th><th scope="col">Price</th><th scope="col">Stock</th><th scope="col">Visible</th><th scope="col"><span className="sr-only">Edit</span></th></tr></thead>
          <tbody>{data.items.map(p => <tr key={p.id}><td data-label="Product">{p.name}{p.pack_size && <small> · {p.pack_size}</small>}</td><td data-label="SKU">{p.sku}</td><td data-label="Category">{p.category_name}</td>
            <td data-label="Price">{moneyC(p.effective_price_cents, p.currency)}{p.offer_price_cents != null && <small> (offer)</small>}{p.price_status !== "verified" && <small> · {p.price_status}</small>}</td>
            <td data-label="Stock">{p.available_quantity}</td><td data-label="Visible">{p.is_active ? "Yes" : "No"}</td>
            <td><button type="button" className="link-button" onClick={() => setForm(p)} aria-label={`Edit ${p.name}`}>Edit</button></td></tr>)}</tbody></table></div>
        <Pagination page={page} pageSize={20} total={data.total} onChange={setPage}/></>}
    </div>
    {form && <ProductForm product={form === "new" ? null : form} categories={categories} onClose={() => setForm(null)} onSaved={load}/>}
  </div>;
}
