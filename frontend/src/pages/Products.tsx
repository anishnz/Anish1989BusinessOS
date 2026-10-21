import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, money, quantity, when } from "../api";
import { useAuth } from "../auth";
import { useData } from "../components/useData";
import type { Page, Product, StockMovement } from "../types";

const REASONS: [string, string, string][] = [
  ["received", "Received", "Amount added"],
  ["counted", "Counted", "Amount now in stock"],
  ["waste", "Waste", "Amount taken off"],
  ["correction", "Correction", "Change (use - to take off)"],
];

function StockCell({ p }: { p: Product }) {
  if (!p.track_stock) return <span className="muted">–</span>;
  const bad = p.stock_state === "out" || p.stock_state === "below_zero";
  return (
    <span>
      {quantity(p.stock_quantity ?? "0", p.unit)}
      {p.stock_state !== "ok" && <div className={`small ${bad ? "error" : "muted"}`}>{p.stock_text}</div>}
    </span>
  );
}

/** Change stock by hand (task 2.2): needs Products - Edit. Every change is kept in the history. */
function StockForm({ product, onDone }: { product: Product; onDone: (p: Product) => void }) {
  const [reason, setReason] = useState("received");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: history, reload } = useData<StockMovement[]>(`/api/products/${product.id}/stock/`);

  async function save() {
    setBusy(true);
    setProblem("");
    try {
      onDone(await api<Product>(`/api/products/${product.id}/stock/`, { method: "POST", body: { reason, quantity: amount, note } }));
      setAmount("");
      setNote("");
      reload();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid" style={{ gap: 8 }}>
      <div className="row">
        <select aria-label="Why the stock changes" value={reason} onChange={(e) => setReason(e.target.value)}>
          {REASONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input aria-label={REASONS.find(([k]) => k === reason)?.[2]} placeholder={REASONS.find(([k]) => k === reason)?.[2]}
          inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} style={{ width: 170 }} />
        <span className="muted small">{product.unit === "kg" ? "kg" : product.unit === "pack" ? "packs" : "items"}</span>
        <input aria-label="Note" placeholder={reason === "waste" || reason === "correction" ? "Note (needed)" : "Note (optional)"}
          value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, minWidth: 160 }} maxLength={200} />
        <button className="primary" disabled={busy || !amount.trim()} onClick={save}>Save</button>
      </div>
      {problem && <p className="error small" role="alert" style={{ margin: 0 }}>{problem}</p>}
      {history && history.length > 0 && (
        <table className="small">
          <thead><tr><th>When</th><th>Why</th><th className="num">Change</th><th className="num">Then in stock</th><th>Note</th></tr></thead>
          <tbody>
            {history.slice(0, 8).map((m) => (
              <tr key={m.id}>
                <td>{when(m.at)}</td><td>{m.reason_label}{m.order_number ? ` #${m.order_number}` : ""}</td>
                <td className="num">{Number(m.change) > 0 ? "+" : ""}{quantity(m.change, product.unit)}</td>
                <td className="num">{quantity(m.quantity_after, product.unit)}</td>
                <td>{m.note}{m.actor_email && <div className="muted">{m.actor_email}</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function Products() {
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const { can } = useAuth();
  const lowOnly = params.get("stock") === "low";
  const { data, setData, error } = useData<Page<Product>>(`/api/products/?q=${encodeURIComponent(q)}&page_size=100${lowOnly ? "&stock=low" : ""}`);
  const canAdjust = can("products.edit");

  function replace(p: Product) {
    if (data) setData({ ...data, results: data.results.map((x) => (x.id === p.id ? p : x)) });
  }

  return (
    <div className="grid">
      <div className="row">
        <h1 style={{ marginRight: "auto" }}>Products</h1>
        {can("products.edit") && <a className="button" href="/admin/catalog/product/">Edit products (classic admin)</a>}
      </div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); setQ(term); }}>
        <input aria-label="Search products" placeholder="Name, code or other name" value={term} onChange={(e) => setTerm(e.target.value)} />
        <button type="submit">Search</button>
        <label className="row" style={{ margin: 0, fontWeight: 400 }}>
          <input type="checkbox" checked={lowOnly} onChange={(e) => setParams(e.target.checked ? { stock: "low" } : {})} /> Only low or out of stock
        </label>
      </form>
      {error && <p className="error">{error}</p>}
      <div className="card table-wrap">
        <table>
          <thead><tr><th>Product</th><th>Code</th><th>Category</th><th className="num">Price</th><th>Available</th><th className="num">In stock</th>{canAdjust && <th />}</tr></thead>
          <tbody>
            {data?.results.map((p) => (
              <Fragment key={p.id}>
                <tr>
                  <td>{p.name}</td><td className="muted">{p.sku || "–"}</td><td>{p.category_name || "–"}</td>
                  <td className="num">{money(p.price)}{p.unit === "kg" ? "/kg" : p.unit === "pack" ? "/pack" : ""}</td>
                  <td>{p.is_available ? "Yes" : <strong>No</strong>}</td>
                  <td className="num"><StockCell p={p} /></td>
                  {canAdjust && <td className="end">{p.track_stock && <button onClick={() => setOpen(open === p.id ? null : p.id)} aria-expanded={open === p.id}>Stock</button>}</td>}
                </tr>
                {canAdjust && open === p.id && (
                  <tr><td colSpan={7}><StockForm product={p} onDone={replace} /></td></tr>
                )}
              </Fragment>
            ))}
            {data && data.results.length === 0 && <tr><td colSpan={7} className="muted">No products.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
