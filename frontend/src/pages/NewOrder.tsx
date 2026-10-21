import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, money } from "../api";
import { useAuth } from "../auth";
import FulfilmentEditor, { EMPTY_FULFILMENT, type FulfilmentValue } from "../components/FulfilmentEditor";
import type { Customer, Order, Page, Product } from "../types";

interface Line { product: Product; quantity: string; note: string }

function useSearch<T>(path: string, term: string, enabled = true): T[] {
  const [items, setItems] = useState<T[]>([]);
  useEffect(() => {
    if (!enabled || term.trim().length < 2) {
      setItems([]);
      return;
    }
    const timer = window.setTimeout(() => {
      api<Page<T>>(`${path}${encodeURIComponent(term.trim())}`).then((p) => setItems(p.results.slice(0, 8))).catch(() => setItems([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [path, term, enabled]);
  return items;
}

export default function NewOrder() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const canSeeCustomers = can("crm.view");
  const [customerTerm, setCustomerTerm] = useState("");
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [productTerm, setProductTerm] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [notes, setNotes] = useState("");
  const [channel, setChannel] = useState("counter");
  const [how, setHow] = useState<FulfilmentValue>(EMPTY_FULFILMENT);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const customers = useSearch<Customer>("/api/customers/?q=", customerTerm, canSeeCustomers && !customer);
  const products = useSearch<Product>("/api/products/?available=true&q=", productTerm);

  function add(p: Product) {
    setLines([...lines, { product: p, quantity: String(Number(p.min_quantity)), note: "" }]);
    setProductTerm("");
  }

  const estimate = lines.reduce((sum, l) => sum + Number(l.product.price) * Number(l.quantity || 0), 0);

  async function save() {
    setBusy(true);
    setProblem("");
    try {
      const order = await api<Order>("/api/orders/", {
        method: "POST",
        body: {
          customer: customer?.id ?? null, channel, notes, ...how,
          lines: lines.map((l) => ({ product: l.product.id, quantity: l.quantity, note: l.note })),
        },
      });
      navigate(`/orders/${order.id}`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid" style={{ maxWidth: 820 }}>
      <p className="small"><Link to="/orders">← Orders</Link></p>
      <h1>New order</h1>
      <div className="card">
        <h2>Customer</h2>
        {customer ? (
          <div className="row"><strong>{customer.name}</strong><span className="muted">{customer.phone}</span><button onClick={() => setCustomer(null)}>Change</button></div>
        ) : canSeeCustomers ? (
          <>
            <input aria-label="Find customer" placeholder="Name or phone (leave empty for a walk-in)" value={customerTerm} onChange={(e) => setCustomerTerm(e.target.value)} style={{ width: "100%" }} />
            {customers.map((c) => (
              <div key={c.id}><button style={{ marginTop: 6, width: "100%", justifyContent: "flex-start" }} onClick={() => { setCustomer(c); setCustomerTerm(""); }}>{c.name} <span className="muted">{c.phone}</span></button></div>
            ))}
          </>
        ) : <p className="muted">Walk-in customer.</p>}
        <div className="row" style={{ marginTop: 10 }}>
          <label style={{ margin: 0 }}>Channel <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="counter">Counter</option><option value="phone">Phone</option><option value="whatsapp">WhatsApp</option><option value="website">Website</option>
          </select></label>
        </div>
      </div>

      <div className="card">
        <h2>Pickup or delivery</h2>
        <FulfilmentEditor value={how} productsTotal={estimate} onChange={(next) => {
          // The customer's saved address is a good start for a delivery.
          if (next.fulfilment === "delivery" && how.fulfilment !== "delivery" && !next.delivery_address && customer?.address) {
            next = { ...next, delivery_address: customer.address.replace(/\s+/g, " ").trim().slice(0, 200) };
          }
          setHow(next);
        }} />
      </div>

      <div className="card">
        <h2>Products</h2>
        <input aria-label="Find product" placeholder="Type a product name or code" value={productTerm} onChange={(e) => setProductTerm(e.target.value)} style={{ width: "100%" }} />
        {products.map((p) => (
          <div key={p.id}><button style={{ marginTop: 6, width: "100%", justifyContent: "flex-start" }} onClick={() => add(p)}>
            {p.name} <span className="muted">{money(p.price)}{p.unit === "kg" ? "/kg" : p.unit === "pack" ? "/pack" : ""}</span></button></div>
        ))}
        {lines.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table className="stack">
              <thead><tr><th>Product</th><th>Amount</th><th>Note</th><th className="num">Estimate</th><th /></tr></thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={i}>
                    <td className="lead">{l.product.name}</td>
                    <td data-label="Amount"><input aria-label={`Amount of ${l.product.name}`} inputMode="decimal" style={{ width: 80 }} value={l.quantity}
                      onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)))} /> {l.product.unit === "kg" ? "kg" : l.product.unit === "pack" ? "packs" : ""}
                      <div className="muted small">min {Number(l.product.min_quantity)}, steps of {Number(l.product.quantity_step)}</div></td>
                    <td data-label="Note"><input aria-label={`Note for ${l.product.name}`} value={l.note} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, note: e.target.value } : x)))} /></td>
                    <td className="num" data-label="Estimate">{money(Number(l.product.price) * Number(l.quantity || 0))}</td>
                    <td className="end"><button aria-label={`Remove ${l.product.name}`} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button></td>
                  </tr>
                ))}
              </tbody>
              <tfoot><tr><td colSpan={3} className="num"><strong>Estimate</strong> <span className="muted small">(prices are checked by the server)</span></td><td className="num"><strong>{money(estimate)}</strong></td><td /></tr></tfoot>
            </table>
          </div>
        )}
        <label htmlFor="notes">Notes</label>
        <textarea id="notes" rows={2} style={{ width: "100%" }} placeholder="For example: cut into small pieces" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      {problem && <p className="error" role="alert">{problem}</p>}
      <p><button className="primary" disabled={busy || lines.length === 0} onClick={save}>Save as draft</button></p>
    </div>
  );
}
